"""Strict 4-category allowlist event source for forwarding to the friend's WeChat.

Only these four categories may ever be enqueued or delivered, and only to
`recipient_wechat_id == "No1Urgot"`:
  1. `next_day_new_banner`: tomorrow's new-character banners for the three games
     (明日方舟 / 终末地 / 鸣潮).
  2. `monthcard_expiring_5d`: monthly card expiring within 0..5 days
     (明日方舟 / 终末地 / 鸣潮).
  3. `arknights_activity_open`: Arknights (明日方舟 only) new/rerun activity open.
  4. `endfield_essence_filler`: Endfield (终末地 only) target-mode essence farming
     finished and switched back to filler mode.

Any other category, error/alarm, daily report, non-Arknights activity, non-Endfield
essence filler notice, >5-day or expired monthcard, or wrong recipient raises
ValueError immediately.

Events are persisted idempotently on disk under `state_dir` and synced to the
Mac-side `friend_notify.py` receiver only when BOTH `HARDLOCK` and
`HARDLOCK_WECHAT` are unlocked. While either lock is active, zero outbound
requests are triggered.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.friend_events")

CATEGORY_NEXT_DAY_BANNER = "next_day_new_banner"
CATEGORY_MONTHCARD_5D = "monthcard_expiring_5d"
CATEGORY_AK_ACTIVITY = "arknights_activity_open"
CATEGORY_ENDFIELD_ESSENCE_FILLER = "endfield_essence_filler"

ALLOWED_CATEGORIES = frozenset({
    CATEGORY_NEXT_DAY_BANNER,
    CATEGORY_MONTHCARD_5D,
    CATEGORY_AK_ACTIVITY,
    CATEGORY_ENDFIELD_ESSENCE_FILLER,
})
ALLOWED_GAMES = frozenset({"明日方舟", "终末地", "鸣潮"})
FRIEND_RECIPIENT_WECHAT_ID = "No1Urgot"
MONTHCARD_MAX_DAYS_LEFT = 5

QUEUE_FILE = "friend-events-queue.json"
SEEN_FILE = "friend-events-seen.json"
HARDLOCK_FILE = "HARDLOCK.json"
HARDLOCK_WECHAT_FILE = "HARDLOCK_WECHAT.json"
LOCKED_FLAG_FILE = "LOCKED_UNAVAILABLE.flag"
DEFAULT_FRIEND_NOTIFY_URL = "http://100.110.87.36:8931/friend-notify"
FRIEND_NOTIFY_PATH = "/friend-notify"
ALERTDAEMON_PORT = 8931

TIMEOUT = 5.0
MAX_QUEUE = 200
MAX_SEEN = 500
_RETRY_4XX = (408, 429)
_FORBIDDEN_TITLE_PREFIXES = (
    "❌", "🩺", "🔬", "📋", "🔎", "🚨", "🛑", "⏱️", "⏰", "🔌", "⚠️",
)


def _state_dir_of(cfg_or_dir: Any) -> Path:
    if isinstance(cfg_or_dir, (str, Path)):
        return Path(cfg_or_dir)
    sd = getattr(cfg_or_dir, "state_dir", None)
    if sd is None:
        raise ValueError("缺少状态目录")
    return Path(sd)


def validate_notify_url(url: str) -> str:
    """Validate friend-notify endpoint: NEVER allow the alertdaemon alarm root `/`."""
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("未配置好友提醒接收地址")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"好友提醒地址格式无效：{raw}")
    path = (parsed.path or "").rstrip("/") or "/"
    if path == "/":
        raise ValueError("禁止向报警根路径 '/' 投递好友提醒，必须使用 /friend-notify 或独立端口路径")
    if parsed.port == ALERTDAEMON_PORT and path != FRIEND_NOTIFY_PATH:
        raise ValueError(f"端口 {ALERTDAEMON_PORT} 只允许投递到 {FRIEND_NOTIFY_PATH}，拒绝路径 {path}")
    return raw


def _notify_url_of(cfg_or_dir: Any, explicit: str | None = None) -> str:
    if explicit is not None:
        return str(explicit).strip()
    if not isinstance(cfg_or_dir, (str, Path)):
        val = getattr(cfg_or_dir, "friend_notify_url", None)
        if val is not None:
            return str(val).strip()
    return str(os.environ.get("ARK_FRIEND_NOTIFY_URL", DEFAULT_FRIEND_NOTIFY_URL)).strip()


def _outbox_path_of(explicit: Path | str | None = None) -> Path | None:
    raw = explicit if explicit is not None else os.environ.get("ARK_FRIEND_NOTIFY_OUTBOX", "")
    s = str(raw or "").strip()
    return Path(s) if s else None


def _is_int_strict(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _check_game(category: str, game: Any) -> str:
    if not isinstance(game, str) or not game.strip():
        raise ValueError("缺少游戏名称")
    cleaned = game.strip()
    if category == CATEGORY_AK_ACTIVITY:
        if cleaned != "明日方舟":
            raise ValueError("活动开启提醒只允许明日方舟，不发其他游戏")
        return cleaned
    if category == CATEGORY_ENDFIELD_ESSENCE_FILLER:
        if cleaned != "终末地":
            raise ValueError("基质刷取切刷垫子提醒只允许终末地，不发其他游戏")
        return cleaned
    if category == CATEGORY_MONTHCARD_5D:
        if cleaned not in ALLOWED_GAMES:
            raise ValueError("月卡提醒只允许明日方舟、终末地或鸣潮")
        return cleaned
    parts = [p.strip() for p in cleaned.split("、") if p.strip()]
    if not parts or any(p not in ALLOWED_GAMES for p in parts):
        raise ValueError("卡池提醒只允许明日方舟、终末地或鸣潮")
    return "、".join(parts)


def _check_days_left(category: str, days_left: Any) -> int | None:
    if category == CATEGORY_MONTHCARD_5D:
        if not _is_int_strict(days_left) or not (0 <= days_left <= MONTHCARD_MAX_DAYS_LEFT):
            raise ValueError("月卡提醒只允许剩余 0 到 5 天")
        return int(days_left)
    if category == CATEGORY_NEXT_DAY_BANNER:
        if days_left is None:
            return 1
        if not _is_int_strict(days_left) or days_left != 1:
            raise ValueError("次日新卡池提醒只允许提前 1 天")
        return 1
    if days_left is not None:
        if category == CATEGORY_ENDFIELD_ESSENCE_FILLER:
            raise ValueError("基质刷取切刷垫子提醒不带剩余天数")
        raise ValueError("活动开启提醒不带剩余天数")
    return None


def validate_event(event: Any) -> dict[str, Any]:
    """Validate and normalize one friend-notify event. Raises ValueError on any violation."""
    if not isinstance(event, dict):
        raise ValueError("事件内容必须是字典")
    category = event.get("category")
    if not isinstance(category, str) or category not in ALLOWED_CATEGORIES:
        raise ValueError("不支持的消息类别：只允许明日新卡池、月卡五天内到期、明日方舟新活动、终末地基质切刷垫子")
    recipient = event.get("recipient_wechat_id")
    if recipient != FRIEND_RECIPIENT_WECHAT_ID:
        raise ValueError("接收微信号不对，只允许发给朋友号")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip() or "\n" in event_id or "\r" in event_id:
        raise ValueError("缺少有效的事件编号")
    title = event.get("title")
    text = event.get("text")
    if not isinstance(title, str) or not title.strip() or not isinstance(text, str) or not text.strip():
        raise ValueError("消息标题和正文不能为空")
    title_s = title.strip()
    if title_s.startswith(_FORBIDDEN_TITLE_PREFIXES):
        raise ValueError("报警、报错或日报标题不允许走朋友号通道")
    game = _check_game(category, event.get("game"))
    days_left = _check_days_left(category, event.get("days_left"))
    created_at = event.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        raise ValueError("缺少事件创建时间")
    try:
        datetime.fromisoformat(created_at.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("事件创建时间格式不对") from exc
    return {
        "event_id": event_id.strip(),
        "category": category,
        "game": game,
        "days_left": days_left,
        "title": title_s,
        "text": text.strip(),
        "recipient_wechat_id": FRIEND_RECIPIENT_WECHAT_ID,
        "created_at": created_at.strip(),
    }


def _to_server_tz(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=SERVER_TZ)
    return now.replace(tzinfo=SERVER_TZ) if now.tzinfo is None else now.astimezone(SERVER_TZ)


def build_event(*, event_id: str, category: str, game: str, title: str, text: str,
                days_left: int | None = None,
                recipient_wechat_id: str = FRIEND_RECIPIENT_WECHAT_ID,
                created_at: str | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    """Build and strictly validate a friend-notify event dict."""
    at = created_at
    if at is None:
        dt = _to_server_tz(now)
        at = dt.isoformat(timespec="seconds")
    return validate_event({
        "event_id": event_id,
        "category": category,
        "game": game,
        "days_left": days_left,
        "title": title,
        "text": text,
        "recipient_wechat_id": recipient_wechat_id,
        "created_at": at,
    })


def _lock_file_active(path: Path) -> str:
    """Fallback fail-closed inspection of one HARDLOCK*.json file when hardlock.py is absent."""
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"{path.name} 存在且无法读取，按锁定处理"
    if not isinstance(data, dict):
        return f"{path.name} 内容格式不对，按锁定处理"
    if data.get("locked") is False or data.get("unlocked") is True:
        return ""
    reason = str(data.get("reason") or "").strip()
    return f"{path.name} 锁定中（{reason}）" if reason else f"{path.name} 锁定中"


def hardlock_reason(state_dir: Path | str) -> str:
    """Return non-empty lock reason if HARDLOCK or HARDLOCK_WECHAT is active; '' when unlocked."""
    sd = Path(state_dir)
    flag = sd.parent / LOCKED_FLAG_FILE
    if flag.exists():
        return f"{LOCKED_FLAG_FILE} 存在，按锁定处理"
    try:
        from ark_relay.features import hardlock as hl  # noqa: PLC0415
    except ImportError:
        if why := _lock_file_active(sd / HARDLOCK_FILE):
            return why
        if why := _lock_file_active(sd / HARDLOCK_WECHAT_FILE):
            return why
        return ""
    except Exception as exc:  # noqa: BLE001 - fail-closed if hardlock module is broken
        return f"硬锁模块加载失败（{type(exc).__name__}），按锁定处理"
    try:
        if hl.active(sd, "relay"):
            return f"{HARDLOCK_FILE} 锁定中"
        if hl.active(sd, "wechat"):
            return f"{HARDLOCK_WECHAT_FILE} 锁定中"
    except Exception as exc:  # noqa: BLE001 - fail-closed on any hardlock check error
        return f"硬锁检查异常（{type(exc).__name__}），按锁定处理"
    return ""


def is_hardlocked(state_dir: Path | str) -> bool:
    """True when either HARDLOCK or HARDLOCK_WECHAT blocks outbound delivery."""
    return bool(hardlock_reason(state_dir))


class _DirCoord:
    """Per-state_dir shared mutex & single-flight drain coordinator across all queue instances."""

    def __init__(self) -> None:
        self.io_lock = threading.RLock()
        self.drain_lock = threading.Lock()
        self.bg_active = False
        self.bg_again = False
        self.next_queue: FriendEventQueue | None = None
        self.thread: threading.Thread | None = None


_COORDS_GUARD = threading.Lock()
_COORDS: dict[str, _DirCoord] = {}


def _coord_for(state_dir: Path) -> _DirCoord:
    key = str(state_dir.resolve())
    with _COORDS_GUARD:
        coord = _COORDS.get(key)
        if coord is None:
            coord = _DirCoord()
            _COORDS[key] = coord
        return coord


class FriendEventQueue:
    """Persistent idempotent friend-event queue with dual-hardlock outbound gate."""

    def __init__(self, state_dir: Path | str, url: str = "", timeout: float = TIMEOUT,
                 post=None, outbox_path: Path | str | None = None):
        self.state_dir = Path(state_dir)
        self.url = str(url or "").strip()
        self.timeout = timeout
        self._post = post
        self._outbox = Path(outbox_path) if outbox_path else None
        self._queue_path = self.state_dir / QUEUE_FILE
        self._seen_path = self.state_dir / SEEN_FILE
        self._coord = _coord_for(self.state_dir)
        self._lock = self._coord.io_lock

    def _load_queue(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._queue_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            log.warning("%s 读不出来，按空队列处理", QUEUE_FILE, exc_info=True)
            return []
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []

    def _save_queue(self, rows: list[dict[str, Any]]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not rows:
            self._queue_path.unlink(missing_ok=True)
            return
        atomic_write_text(self._queue_path, json.dumps(rows[-MAX_QUEUE:], ensure_ascii=False, indent=1))

    def _load_seen(self) -> dict[str, str]:
        try:
            data = json.loads(self._seen_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            log.warning("%s 读不出来，按空记录处理", SEEN_FILE, exc_info=True)
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save_seen(self, seen: dict[str, str]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if len(seen) > MAX_SEEN:
            items = sorted(seen.items(), key=lambda kv: kv[1])[-MAX_SEEN:]
            seen = dict(items)
        atomic_write_text(self._seen_path, json.dumps(seen, ensure_ascii=False, indent=1))

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._load_queue()

    def seen_ids(self) -> dict[str, str]:
        with self._lock:
            return self._load_seen()

    def enqueue(self, event: dict[str, Any]) -> bool:
        """Strictly validate and persist `event` once per `event_id`. Returns False if duplicate."""
        clean = validate_event(event)
        eid = clean["event_id"]
        with self._lock:
            seen = self._load_seen()
            queue = self._load_queue()
            if eid in seen or any(str(item.get("event_id") or "") == eid for item in queue):
                return False
            queue.append(clean)
            seen[eid] = clean["created_at"]
            self._save_queue(queue)
            self._save_seen(seen)
        return True

    def _deliver_one(self, row: dict[str, Any]) -> tuple[str, str]:
        clean = validate_event(row)
        if self._post is not None:
            return self._post(clean)
        if self._outbox is not None:
            try:
                self._outbox.parent.mkdir(parents=True, exist_ok=True)
                with self._outbox.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(clean, ensure_ascii=False) + "\n")
                return "ok", ""
            except OSError as exc:
                return "retry", f"{type(exc).__name__}: {exc}"
        if not self.url:
            return "retry", "未配置接收地址"
        try:
            target_url = validate_notify_url(self.url)
        except ValueError as exc:
            log.warning("拒绝向不合规地址投递好友微信事件（%s）：%s", exc, self.url)
            return "retry", str(exc)
        data = json.dumps(clean, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            target_url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500 and exc.code not in _RETRY_4XX:
                return "drop", f"HTTP {exc.code}"
            return "retry", f"HTTP {exc.code}"
        except (OSError, http.client.HTTPException) as exc:
            return "retry", f"{type(exc).__name__}: {exc}"
        return "ok", ""

    def _can_send(self) -> bool:
        return self._post is not None or self._outbox is not None or bool(self.url)

    @staticmethod
    def _validate_queued(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        try:
            return validate_event(row), ""
        except ValueError as exc:
            return None, str(exc)

    def _drain(self) -> int:
        while True:
            if why := hardlock_reason(self.state_dir):
                with self._lock:
                    left = len(self._load_queue())
                log.info("好友微信事件通道硬锁中（%s），零外发，%d 条留在本地队列", why, left)
                return left
            with self._lock:
                queue = self._load_queue()
                if not queue:
                    return 0
                head = queue[0]
            clean, bad_why = self._validate_queued(head)
            if clean is None:
                log.warning("队列里发现不合规的好友事件并已拦截丢弃（%s）：%s", bad_why, head.get("event_id", ""))
                with self._lock:
                    queue = self._load_queue()
                    if queue and queue[0].get("event_id") == head.get("event_id"):
                        queue.pop(0)
                        self._save_queue(queue)
                continue
            if not self._can_send():
                return len(queue)
            verdict, why = self._deliver_one(clean)
            if verdict == "retry":
                with self._lock:
                    left = len(self._load_queue())
                log.info("好友微信事件暂未送达 Mac（%s），%d 条留在本地队列", why, left)
                return left
            with self._lock:
                queue = self._load_queue()
                if queue and queue[0].get("event_id") == clean["event_id"]:
                    queue.pop(0)
                    self._save_queue(queue)
            if verdict == "drop":
                log.info("Mac 端拒收好友事件（%s），已丢弃：%s", why, clean["event_id"])

    def flush(self) -> int:
        """Deliver queued events oldest-first when unlocked. Serialized per state_dir."""
        if why := hardlock_reason(self.state_dir):
            left = len(self.pending())
            log.info("好友微信事件通道硬锁中（%s），跳过外发，待发 %d 条", why, left)
            return left
        if not self._can_send():
            return len(self.pending())
        with self._coord.drain_lock:
            return self._drain()

    def flush_async(self) -> threading.Thread | None:
        """Flush on the single shared per-state_dir daemon thread; skipped while hardlocked."""
        if hardlock_reason(self.state_dir) or not self._can_send():
            return None
        return _start_flush_thread(self)


def emit(cfg_or_dir: Any, event: dict[str, Any], *, url: str | None = None,
         post=None, outbox_path: Path | str | None = None, sync: bool = False) -> bool:
    """Validate, idempotently persist, and (only when unlocked) sync one friend event."""
    sd = _state_dir_of(cfg_or_dir)
    q = FriendEventQueue(
        sd,
        url=_notify_url_of(cfg_or_dir, explicit=url),
        post=post,
        outbox_path=_outbox_path_of(outbox_path),
    )
    added = q.enqueue(event)
    if not added:
        return False
    if why := hardlock_reason(sd):
        log.info("好友微信事件已记本地待发（硬锁中零外发：%s）：%s", why, event.get("event_id", ""))
        return True
    if sync:
        q.flush()
    else:
        q.flush_async()
    return True


def emit_next_day_banner(cfg_or_dir: Any, game: str, when: datetime, who: str, *,
                         now: datetime | None = None, title: str = "", text: str = "",
                         url: str | None = None, post=None, sync: bool = False) -> bool:
    """Emit a `next_day_new_banner` event for one banner opening tomorrow."""
    stamp = f"{when:%m-%d}" if (when.hour, when.minute) == (0, 0) else f"{when:%m-%d %H:%M}"
    ev_title = title or f"🎴 明天开新卡池：{game}"
    ev_text = text or (f"· {game}　{stamp} 开" + (f"　{who}" if who else ""))
    ev = build_event(
        event_id=f"{CATEGORY_NEXT_DAY_BANNER}:{game}:{when:%Y%m%d%H%M}",
        category=CATEGORY_NEXT_DAY_BANNER,
        game=game,
        days_left=1,
        title=ev_title,
        text=ev_text,
        now=now,
    )
    return emit(cfg_or_dir, ev, url=url, post=post, sync=sync)


def emit_monthcard_expiring(cfg_or_dir: Any, game: str, days_left: int, last_date: str = "", *,
                            now: datetime | None = None, text: str = "",
                            url: str | None = None, post=None, sync: bool = False) -> bool:
    """Emit a `monthcard_expiring_5d` event (strictly 0 <= days_left <= 5)."""
    at = _to_server_tz(now)
    ev_text = text or (
        f"{game}月卡还剩 {days_left} 天，最后一次领取是 {last_date}"
        if last_date else f"{game}月卡还剩 {days_left} 天，请及时续费"
    )
    ev = build_event(
        event_id=f"{CATEGORY_MONTHCARD_5D}:{game}:{at:%Y-%m-%d}:{days_left}",
        category=CATEGORY_MONTHCARD_5D,
        game=game,
        days_left=days_left,
        title="💳 月卡快到期",
        text=ev_text,
        now=at,
    )
    return emit(cfg_or_dir, ev, url=url, post=post, sync=sync)


def emit_arknights_activity_open(cfg_or_dir: Any, activity_id: str, title: str, text: str, *,
                                 game: str = "明日方舟", now: datetime | None = None,
                                 url: str | None = None, post=None, sync: bool = False) -> bool:
    """Emit an `arknights_activity_open` event (strictly Arknights only)."""
    ev = build_event(
        event_id=f"{CATEGORY_AK_ACTIVITY}:{activity_id}",
        category=CATEGORY_AK_ACTIVITY,
        game=game,
        days_left=None,
        title=title,
        text=text,
        now=now,
    )
    return emit(cfg_or_dir, ev, url=url, post=post, sync=sync)


def emit_endfield_essence_filler(cfg_or_dir: Any, run_id: str,
                                 weapons: list[str] | None = None, *,
                                 game: str = "终末地", title: str = "", text: str = "",
                                 now: datetime | None = None, url: str | None = None,
                                 post=None, sync: bool = False) -> bool:
    """Emit an `endfield_essence_filler` event (strictly Endfield only)."""
    from ark_relay.core import texts  # noqa: PLC0415
    ev_title = title or texts.ESSENCE_FILLER_SWITCHED
    ev_text = text or texts.essence_filler_friend_body(list(weapons or []))
    ev = build_event(
        event_id=f"{CATEGORY_ENDFIELD_ESSENCE_FILLER}:{run_id}",
        category=CATEGORY_ENDFIELD_ESSENCE_FILLER,
        game=game,
        days_left=None,
        title=ev_title,
        text=ev_text,
        now=now,
    )
    return emit(cfg_or_dir, ev, url=url, post=post, sync=sync)


def _start_flush_thread(q: FriendEventQueue) -> threading.Thread | None:
    """Spawn at most one background flush thread per state_dir; coalesce concurrent calls."""
    coord = q._coord
    with coord.io_lock:
        if coord.bg_active:
            coord.bg_again = True
            coord.next_queue = q
            return coord.thread
        coord.bg_active = True
        coord.bg_again = False
        coord.next_queue = None

        def run() -> None:
            active_q = q
            try:
                while True:
                    with coord.drain_lock:
                        active_q._drain()
                    with coord.io_lock:
                        if not coord.bg_again:
                            coord.bg_active = False
                            coord.thread = None
                            coord.next_queue = None
                            return
                        coord.bg_again = False
                        if coord.next_queue is not None:
                            active_q = coord.next_queue
                            coord.next_queue = None
            except Exception:
                log.warning("好友微信事件同步到 Mac 时出错", exc_info=True)
                with coord.io_lock:
                    coord.bg_active = False
                    coord.thread = None
                    coord.next_queue = None

        t = threading.Thread(target=run, name="friend-events-sync", daemon=True)
        coord.thread = t
        t.start()
        return t


def flush_pending(cfg_or_dir: Any, *, url: str | None = None, post=None,
                  outbox_path: Path | str | None = None,
                  async_flush: bool = False, timeout: float = TIMEOUT) -> int | None:
    """Flush any queued friend events once hardlocks are lifted.

    When `async_flush=True` (used by `Engine._flush_pending`), drains on the single
    per-state-dir background daemon thread with bounded HTTP timeout so the tick loop
    never stalls on an unreachable Mac.
    """
    sd = _state_dir_of(cfg_or_dir)
    coord = _coord_for(sd)
    with coord.io_lock:
        if not (sd / QUEUE_FILE).is_file():
            return 0
    if hardlock_reason(sd):
        return len(FriendEventQueue(sd).pending())
    q = FriendEventQueue(
        sd,
        url=_notify_url_of(cfg_or_dir, explicit=url),
        timeout=timeout,
        post=post,
        outbox_path=_outbox_path_of(outbox_path),
    )
    if not q._can_send():
        return len(q.pending())
    if async_flush:
        if not q.pending():
            return 0
        _start_flush_thread(q)
        return None
    return q.flush()

