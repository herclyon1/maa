"""Push channels: 企业微信 self-built app (WeCom), 企业微信 group robot (WeComBot),
Server酱 (ServerChan), and the Notifier that routes each title to them.

Plain HTTP with urllib; no push library.
"""
from __future__ import annotations

import ipaddress
import json
import re
import logging
import random
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import http.client
from pathlib import Path
from ark_relay.core import texts
from ark_relay.core.config import Config, SERVER_TZ

log = logging.getLogger("ark.notify")

_HOLD_EXEMPT_PREFIXES = (
    texts.SHUTDOWN_CANCELLED,
    "⚠️ 明日方舟理智不够",
    texts.CONFIG_FAILED,
    texts.ALARM_HOLD_EXPIRED,
    texts.ALARM_SHUTDOWN_ABORTED,
    texts.ALARM_EARLY_SHUTDOWN,
    "🔁 鸣潮早班活跃没满",
)
_NOTE_TLS = threading.local()


def is_hold_exempt(title: str) -> bool:
    return title.startswith(_HOLD_EXEMPT_PREFIXES) or texts.is_cant_enter(title)

_TIMEOUT = 20
_RETRIES = 3
# Exponential backoff with full jitter: before retry k (0-based) wait a random time
# in [0, min(_BACKOFF_CAP, _BACKOFF_BASE * 2**k)]
# (https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/).
_BACKOFF_BASE = 1.5  # seconds
_BACKOFF_CAP = 10.0  # seconds; _post runs on the caller's thread, so the total stays bounded
_rng = random.Random()  # module-level so a test can make the jitter deterministic
# 企业微信 errcode -1 「系统繁忙」: its error-code page says to retry later, at most
# 3 times (https://developer.work.weixin.qq.com/document/path/90313) - retried in
# _post like a transport failure, within _RETRIES (= 3).
_BUSY_CODE = -1


def _backoff(attempt: int) -> float:
    """Full-jitter delay before retry `attempt` (0-based)."""
    return _rng.uniform(0.0, min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** attempt)))


class _Busy(Exception):
    """企业微信 errcode -1 (「系统繁忙」) inside _post's retry loop only."""


def _post(req: urllib.request.Request) -> dict:
    """POST with retries for transport failures and 企业微信's errcode -1.

    Nothing re-sends an alert whose push was dropped, so transport errors
    (timeouts, resets, unreadable replies) are retried up to _RETRIES times, with
    exponential full-jitter waits (_backoff).

    An HTTP status is an answer, not a transport failure (a 403 stays 403,
    errcode 60020 stays 60020): it is raised at once so the caller can try
    another endpoint or channel. The one answer retried is 企业微信's errcode -1
    「系统繁忙」, which its error-code page says to retry (at most 3 times).
    """
    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("errcode") == _BUSY_CODE:
                raise _Busy(f"errcode -1 {data.get('errmsg', '')}".strip())
        except urllib.error.HTTPError:
            raise  # the server answered - retrying cannot change the answer
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError,
                OSError, json.JSONDecodeError, UnicodeDecodeError, _Busy) as exc:
            last = exc
            if attempt < _RETRIES - 1:
                delay = _backoff(attempt)
                # INFO: whether this is a fault is known only once the attempts are
                # over; a send that goes through on a later attempt is not pushed.
                log.info("推送传输失败（第 %d/%d 次），%.1fs 后重试: %s",
                         attempt + 1, _RETRIES, delay, exc)
                time.sleep(delay)
            continue
        if last is not None:
            # Went through on a later attempt: one WARNING marked recovered, which
            # goes to the daily report's list of the relay's own faults, not the
            # group (USER-SWITCHES.txt, notify.py:_post). A send whose every attempt
            # failed raises below and the caller logs it (Notifier.send,
            # _announce_outage), which is pushed.
            from ark_relay.features import errwatch  # noqa: PLC0415
            log.warning("推送传输失败 %d 次，第 %d 次送到了: %s", attempt, attempt + 1, last,
                        extra=errwatch.recovered())
        return data
    if isinstance(last, _Busy):
        # Busy every time: hand the caller the answer itself, so it reads as the
        # server's refusal (errcode -1) rather than an exception from in here.
        return {"errcode": _BUSY_CODE, "errmsg": str(last)}
    raise last if last else RuntimeError("推送失败，原因未知")


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _post(urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}))


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    return _post(urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"}))


class WeCom:
    """企业微信自建应用. Plain text only (push.py --private).

    The caller's public IP must be in the app's trusted-IP list or every
    request comes back errcode=60020.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._token = ""
        self._token_expires = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.wecom_corpid and self.cfg.wecom_secret)

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token
        url = (
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
            f"?corpid={self.cfg.wecom_corpid}&corpsecret={self.cfg.wecom_secret}"
        )
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("errcode") != 0:
            raise RuntimeError(f"gettoken 失败: {data.get('errcode')} {data.get('errmsg')}")
        self._token = data["access_token"]
        # Tokens last 7200s; refresh a little early.
        self._token_expires = time.time() + int(data.get("expires_in", 7200)) - 300
        return self._token

    # 企业微信 text messages are capped at 2048 BYTES (not characters) and the API
    # truncates silently past that, so long text is split on line boundaries.
    _LIMIT = 1800  # leave room for the "(1/3)" marker

    @staticmethod
    def _hard_wrap(line: str, limit: int) -> list[str]:
        """Break one over-limit line at character boundaries, by UTF-8 bytes.

        The app API truncates silently past its byte cap and the bot API rejects
        the whole message, so a line over the cap is cut.
        """
        out, cur, size = [], [], 0
        for ch in line:
            n = len(ch.encode("utf-8"))
            if cur and size + n > limit:
                out.append("".join(cur))
                cur, size = [], 0
            cur.append(ch)
            size += n
        if cur:
            out.append("".join(cur))
        return out or [""]

    @classmethod
    def _split(cls, text: str, limit: int = _LIMIT) -> list[str]:
        if len(text.encode("utf-8")) <= limit:
            return [text]
        lines: list[str] = []
        for line in text.split("\n"):
            if len(line.encode("utf-8")) > limit:
                lines.extend(cls._hard_wrap(line, limit))
            else:
                lines.append(line)
        parts, cur, size = [], [], 0
        for line in lines:
            n = len(line.encode("utf-8")) + 1
            if cur and size + n > limit:
                parts.append("\n".join(cur))
                cur, size = [], 0
            cur.append(line)
            size += n
        if cur:
            parts.append("\n".join(cur))
        total = len(parts)
        return [f"（{i}/{total}）\n{p}" for i, p in enumerate(parts, 1)]

    def _message(self, msgtype: str, content: dict, failed: str) -> None:
        """POST one message/send call; raise RuntimeError("<failed>: errcode errmsg") on refusal."""
        url = (
            "https://qyapi.weixin.qq.com/cgi-bin/message/send"
            f"?access_token={self._access_token()}"
        )
        r = _post_json(url, {
            "touser": self.cfg.wecom_touser,
            "msgtype": msgtype,
            "agentid": int(self.cfg.wecom_agentid),
            msgtype: content,
        })
        if r.get("errcode") != 0:
            raise RuntimeError(f"{failed}: {r.get('errcode')} {r.get('errmsg')}")

    def _send_one(self, text: str) -> None:
        self._message("text", {"content": text}, "企业微信发送失败")

    def send_text(self, text: str) -> None:
        for i, part in enumerate(self._split(text)):
            if i:
                time.sleep(0.4)  # keep the parts in order on the client
            self._send_one(part)


_WECOM_IMAGE_LIMIT = 1_800_000   # official cap is 2MB; leave room for the fields around the base64


def _image_bytes_for_wecom(path: Path, limit: int = _WECOM_IMAGE_LIMIT) -> bytes:
    """Read the image; if it is over the cap, shrink it to JPEG with Pillow.

    A 1920x1080 game screenshot in PNG is routinely 2.3MB.
    """
    raw = path.read_bytes()
    if len(raw) <= limit and path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        return raw
    from io import BytesIO  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415
    img = Image.open(BytesIO(raw)).convert("RGB")
    width = 1280
    for quality in (85, 75, 60):
        im = img if img.width <= width else img.resize(
            (width, round(img.height * width / img.width)))
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        if buf.tell() <= limit:
            return buf.getvalue()
        width = 960
    return buf.getvalue()


# A line carrying a link the reader needs (the evidence bundle, a log): kept by WeComBot._cap.
_LINK_LINE = re.compile(r"证据包[：:]|日志[：:]\s*https?://|https?://")


class WeComBot:
    """企业微信群机器人 - a webhook, with no trusted-IP list.

    The self-built app authenticates by the caller's IP (errcode 60020 when the
    IP is not in its trusted list); both machines have changing public IPs. The
    group robot authenticates by the key in its URL, so the URL is a secret: it
    is in the machine's .env and the Mac's ~/.config/ark/push.env, not in this
    repo. It posts into a group chat and is capped at 20 messages per minute.
    """

    # Plain text, not markdown: the group is a WeChat group and WeChat shows a
    # robot's markdown as 「暂不支持此消息类型」. The text cap is 2048 bytes.
    _LIMIT = 1800
    MAX_PARTS = 3

    def __init__(self, cfg: Config):
        self.url = cfg.wecom_bot_url

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    @classmethod
    def _cap(cls, text: str) -> str:
        """`text` cut to what fits in MAX_PARTS parts (split numbering included), ending with a
        note of how much was left out; unchanged when it fits."""
        if len(WeCom._split(text, cls._LIMIT)) <= cls.MAX_PARTS:
            return text
        budget = cls._LIMIT * cls.MAX_PARTS - 400     # room for the 「（i/N）」 prefixes and the note
        lines = text.split("\n")
        tail_idx = [i for i, ln in enumerate(lines) if _LINK_LINE.search(ln)][-3:]
        tail = [lines[i] for i in tail_idx]
        tail_size = sum(len(ln.encode("utf-8")) + 1 for ln in tail)
        if tail_size > budget // 4:
            tail, tail_idx, tail_size = [], [], 0
        budget -= tail_size
        lines = [ln for i, ln in enumerate(lines) if i not in set(tail_idx)]
        kept, size = [], 0
        for line in lines:
            n = len(line.encode("utf-8")) + 1
            if size + n > budget:
                if not kept:                            # one huge first line: cut inside it
                    kept.append(line.encode("utf-8")[:budget].decode("utf-8", "ignore"))
                break
            kept.append(line)
            size += n
        log.warning("群机器人：一条消息 %d 字节、要切成 %d 段，只发前 %d 段：%s",
                    len(text.encode("utf-8")), len(WeCom._split(text, cls._LIMIT)), cls.MAX_PARTS,
                    text.split("\n", 1)[0][:80])
        return "\n".join(kept) + "\n（中间还有很长一段没发，免得刷屏）" + "".join("\n" + ln for ln in tail) \
            if tail else "\n".join(kept) + "\n（后面还有很长一段没发，免得刷屏）"

    def send_text(self, text: str) -> None:
        for part in WeCom._split(self._cap(text), self._LIMIT):
            data = _post_json(self.url, {
                "msgtype": "text", "text": {"content": part},
            })
            if data.get("errcode") != 0:
                raise RuntimeError(
                    f"群机器人发送失败: {data.get('errcode')} {data.get('errmsg')}")

    def send_image(self, path: Path) -> None:
        """A group robot image message: base64 + md5; official cap 2MB, jpg/png."""
        import base64  # noqa: PLC0415
        import hashlib  # noqa: PLC0415
        raw = _image_bytes_for_wecom(Path(path))
        data = _post_json(self.url, {
            "msgtype": "image",
            "image": {"base64": base64.b64encode(raw).decode("ascii"),
                      "md5": hashlib.md5(raw).hexdigest()},
        })
        if data.get("errcode") != 0:
            raise RuntimeError(
                f"群机器人发图失败: {data.get('errcode')} {data.get('errmsg')}")


class ServerChan:
    """Server酱. `sctp...` = Server酱³, `SCT...` = Turbo - different endpoints.

    A 0 return code only means the API accepted the message. It does NOT mean
    it was delivered: if the account's message channel is misconfigured the
    message silently goes nowhere.
    """

    def __init__(self, cfg: Config):
        self.key = cfg.serverchan_key

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _endpoints(self) -> list[str]:
        """Both known Server酱 endpoints, most likely first.

        `sctp...` keys are Server酱³ and are documented to use a per-uid host,
        but the legacy sctapi host also accepts them - and is what AUTO-MAS
        itself uses successfully with this key. Try both rather than guess.
        """
        urls = [f"https://sctapi.ftqq.com/{self.key}.send"]
        if self.key.startswith("sctp"):
            uid = self.key[4:].split("t", 1)[0]
            if uid.isdigit():
                urls.append(f"https://{uid}.push.ft07.com/send/{self.key}.send")
        return urls

    def send_text(self, title: str, body: str = "") -> None:
        # Server酱 renders Markdown; a blank line keeps line breaks intact.
        payload = {"title": title[:100], "desp": body.replace("\n", "\n\n")}
        errors = []
        for url in self._endpoints():
            try:
                r = _post_form(url, payload)
            except Exception as exc:  # noqa: BLE001 - try the next endpoint
                errors.append(f"{url.split('/')[2]}: {exc}")
                continue
            code = r.get("code", r.get("errno"))
            if code in (0, None):
                # A 0 here only means accepted, NOT delivered: if the account's
                # message channel is misconfigured it silently goes nowhere.
                if errors:
                    # An earlier endpoint refused it and this one took it: one
                    # WARNING marked recovered, daily report only, not the group
                    # (USER-SWITCHES.txt, notify.py:ServerChan.send_text). The
                    # transport attempts in _post are INFO lines, so this is the
                    # line the daily report counts.
                    from ark_relay.features import errwatch  # noqa: PLC0415
                    log.warning("Server酱 前面的地址没送到（%s），换 %s 送到了", "；".join(errors),
                                url.split("/")[2], extra=errwatch.recovered())
                return
            errors.append(f"{url.split('/')[2]}: {r}")
        raise RuntimeError("Server酱 发送失败 -> " + "；".join(errors))


# Three channels, three jobs (docs/NOTIFICATIONS.md has the full title -> route table):
#
#   企业微信群机器人  real alarms only. Sent from the Mac and never from here:
#                    「总统令第 N 条」 (scripts/mac/push.py --decree)
#   Server酱          the daily report and every other notification that means
#                    something
#   企业微信自建应用   (the private chat) never from here - only text the user
#                    dictates by hand (push.py --private)
#
# Fallbacks: the group falls back to Server酱 when the robot refuses; the daily
# report falls back to the group (split into parts) when Server酱 refuses; info
# that Server酱 refuses is returned as undelivered, never escalated.
_GROUP_ORDER = ("企业微信机器人", "Server酱")
_DAILY_ORDER = ("Server酱", "企业微信机器人")
_INFO_ORDER = ("Server酱",)
_ORDERS = {"group": _GROUP_ORDER, "daily": _DAILY_ORDER, "info": _INFO_ORDER}

# Titles already shown by the daily report or the phone page are logged, not
# pushed, and count as delivered. docs/NOTIFICATIONS.md has the reason for each;
# test_notify_routing.py pins it.
_LOG_ONLY_PREFIXES = (
    "🔄 中继已更新",            # every deploy; the phone page shows the version
    "🗓️ 周常",                  # weekly gate closed/reopened; the phone page shows it
    "⏭️ 跳过模式",              # acknowledgement of a phone order
    "🛑 已停一切",              # acknowledgement of the phone's estop
    "📱 配置已修改",             # acknowledgement of a phone order
    "⚙️ 配置已更新",             # texts.INBOX_APPLIED: our own order.sh batch, all through (a ✗ is 📱 配置没改成)
    "🗂️ 证据包已送出机器",       # bookkeeping behind a failure the alarm already reported
    "✅ 自动采集：补跑后全部走完",
    # Failures are never on this list. texts.COLLECT_RETRY_START is not sent at
    # all (collect_retry.maybe_run): the retry's outcome is.
    "🩹 OK-WW 补丁",            # all patches bound - the healthy case; ⚠️ variant still goes out
    "🥚 开始刷声骸",            # acknowledgement of a phone order; 收工 still goes out
    "✅ ",                      # any successful phone-order acknowledgement (the page shows it)
)
# Only successes and acknowledgements are on the list above; every failure goes
# to the group, every time (docs/NOTIFICATIONS.md, the 🩺 row).


def _say_delivered(route: str, delivered: "list[str]", title: str) -> None:
    """One INFO line per delivered send: which route it took and which channel took it."""
    log.info("推送已送到：%s 路，%s 收下 ｜ %s", route, "、".join(delivered), title)


def route_of(title: str, *, alert: bool = False, daily: bool = False) -> str:
    """'group' | 'daily' | 'info' | 'log' for a title. Pure, so the doc table can be checked against it."""
    if daily:
        return "daily"
    if title.startswith(_LOG_ONLY_PREFIXES):
        return "log"
    if alert:
        return "group"
    return "info"


class Notifier:
    """Fan out to every configured channel; one failure must not silence the rest.

    **Delivered means at least one channel accepted it.** The caller holds
    undelivered messages on disk and retries them every poll cycle, and shutdown
    waits for that queue to drain, so a partial failure is not reported as a
    total one.

    A channel that refused a send another channel took is announced as its own
    alarm (_announce_outage), on every such send. 企业微信's app channel refuses
    every call from an IP outside its trusted list (errcode 60020), and both
    machines' public IPs change.
    """

    def __init__(self, cfg: Config):
        self.wecom = WeCom(cfg)
        self.wecom_bot = WeComBot(cfg)
        self.serverchan = ServerChan(cfg)
        self._state_dir = Path(cfg.state_dir)
        self._busy = threading.local()   # _announcing, per thread (see the property)
        self._cfg = cfg
        self._alerts = None       # alertlog.AlertLog, made on first use
        self._mac = None          # macpush.MacPush, made on first use
        self._last = threading.local()   # what the last send on this thread reached

    @property
    def _announcing(self) -> bool:
        """This thread is sending an outage notice (its own sends must not announce again)."""
        return getattr(self._busy, "announcing", False)

    @_announcing.setter
    def _announcing(self, value: bool) -> None:  # deadcode: allow (property setter)
        self._busy.announcing = value

    def went_to_group(self) -> bool:
        """Whether the last send / send_group on this thread was taken by the group robot.

        errwatch.group_pushed asks this: a log line repeating an alarm is kept out
        of the group only when that alarm really reached the group, not when it
        fell back to Server酱."""
        return "企业微信机器人" in getattr(self._last, "delivered", ())

    # ---------- the copy of every group alarm (alertlog.py) ----------

    def alert_log(self):
        if self._alerts is None:
            from ark_relay.features import errwatch as alertlog  # noqa: PLC0415
            self._alerts = alertlog.for_config(self._cfg)
        return self._alerts

    def mac_push(self):
        if self._mac is None:
            from ark_relay.features import macpush  # noqa: PLC0415
            self._mac = macpush.for_config(self._cfg)
        return self._mac

    def _copy_alarm(self, title: str, body: str, delivered: "list[str] | tuple" = ()) -> None:
        """Keep a delivered group alarm in COS alerts/<day>.jsonl (alertlog.py) and
        POST the same row to the Mac (macpush.py).

        The network parts run on threads of their own; never raises. Only delivered
        alarms are copied: an undelivered one is retried by its caller every tick.
        One `now` for both, so the Mac gets the very row COS has. `delivered` (the
        channels _fan_out reports as having taken it) becomes the row's channel."""
        from datetime import datetime, timezone  # noqa: PLC0415
        now = datetime.now(timezone.utc)
        version = ""
        channel = "、".join(delivered)
        try:
            version = str(self._store().get("versions", "code") or "")
            self.alert_log().copy(title, body, version, now, channel)
        except Exception:   # the copy must never break the alarm path
            log.warning("报警没能抄一份到本地/COS", exc_info=True)
        try:
            from ark_relay.features import errwatch as alertlog  # noqa: PLC0415
            self.mac_push().push(alertlog.row(title, body, version, now, channel))
        except Exception:   # nor may the push to the Mac
            log.warning("报警没能直送 Mac", exc_info=True)

    def _store(self):
        from ark_relay.core.statestore import StateStore  # noqa: PLC0415 - avoids an import cycle
        return StateStore(self._state_dir)

    def _enabled(self) -> list[tuple[str, object]]:
        return [(n, c) for n, c in (
            ("企业微信", self.wecom),
            ("企业微信机器人", self.wecom_bot),
            ("Server酱", self.serverchan),
        ) if c.enabled]

    @property
    def channels(self) -> list[str]:
        return [n for n, _ in self._enabled()]

    def _fan_out(self, title: str, body: str, *,
                 order: tuple[str, ...] | None = None,
                 stop_on_first: bool = False,
                 ) -> tuple[list[str], dict[str, str]]:
        """Try channels in `order`. -> (delivered names, {name: error})

        `stop_on_first` returns as soon as one channel accepts; the later ones
        are not attempted, so one message lands on the phone once.
        """
        delivered: list[str] = []
        failed: dict[str, str] = {}
        joined = f"{title}\n\n{body}" if body else title
        attempts = {
            "企业微信": (self.wecom, lambda: self.wecom.send_text(joined)),
            "企业微信机器人": (self.wecom_bot,
                        lambda: self.wecom_bot.send_text(joined)),
            "Server酱": (self.serverchan,
                        lambda: self.serverchan.send_text(title, body)),
        }
        for name in (order or _GROUP_ORDER):
            channel, call = attempts[name]
            if not channel.enabled:
                continue
            try:
                call()
            except Exception as exc:  # noqa: BLE001 - report, never crash the loop
                # Not logged here: the caller says it once per send - in the
                # outage notice's line (send -> _announce_outage), or in the
                # 「一条渠道都没送到」 / 「群通知没送到」 ERROR when nothing took it.
                failed[name] = str(exc)
            else:
                delivered.append(name)
                if stop_on_first:
                    break
        return delivered, failed

    def note_alarm(self, title: str) -> None:
        """Hold shutdown on any non-exempt group alarm; never raises, never re-enters."""
        if getattr(_NOTE_TLS, "busy", False):
            return
        _NOTE_TLS.busy = True
        try:
            from datetime import datetime  # noqa: PLC0415
            from ark_relay.core import statestore  # noqa: PLC0415
            from ark_relay.features import errwatch, modes, shutdown  # noqa: PLC0415

            if shutdown.in_abort_error():
                return
            if errwatch.os_shutdown() or errwatch.system_shutting_down():
                return
            if threading.current_thread().name.startswith(errwatch.PUSH_THREAD):
                return
            if is_hold_exempt(title):
                return
            evt_now = datetime.now(SERVER_TZ)
            if modes.in_preboot_blackout(evt_now):
                return
            sd = self._state_dir
            if statestore.in_store_write():
                boot_dt = shutdown._boot_time(None, evt_now)
                boot_iso = boot_dt.isoformat(timespec="seconds") if boot_dt else ""

                def _deferred() -> None:
                    if getattr(_NOTE_TLS, "busy", False):
                        return
                    _NOTE_TLS.busy = True
                    try:
                        if modes.set_alarm_hold(sd, title, now=evt_now, at=evt_now,
                                                external=False, boot_at=boot_iso):
                            shutdown.on_alarm_hold()
                    except Exception:  # noqa: BLE001 - deferred alarm hold must never crash worker
                        pass
                    finally:
                        _NOTE_TLS.busy = False

                threading.Thread(target=_deferred, name="ark-alarm-hold", daemon=True).start()
                return
            if modes.set_alarm_hold(sd, title, at=evt_now, external=False):
                shutdown.on_alarm_hold()
        except Exception:  # noqa: BLE001 - note_alarm must never break alarm sending
            pass
        finally:
            _NOTE_TLS.busy = False

    def send(self, title: str, body: str, *, alert: bool = False, daily: bool = False) -> list[str]:
        """Returns failures only when the message reached nobody.

        An empty list means the caller may consider the message delivered and
        stop holding it. A non-empty list means every channel refused it.

        `alert=True` (a real alarm someone has to act on) goes to the group
        robot; `daily=True` (the day's report) and everything else go to
        Server酱 (see the orders above).
        """
        self._last.delivered = ()
        route = route_of(title, alert=alert, daily=daily)
        if route == "log":
            log.info("不推送（日报或手机页已有）：%s ｜ %s", title, body.replace("\n", " ")[:200])
            return []
        if alert is True and route == "group":
            self.note_alarm(title)
        delivered, failed = self._fan_out(title, body, order=_ORDERS[route], stop_on_first=True)
        self._last.delivered = tuple(delivered)
        if not delivered:
            # `or [...]`: with no channel configured `failed` is empty, and an
            # empty list would tell the caller "delivered". (Config.validate
            # refuses to start without a channel.)
            errs = ([f"{n}: {e}" for n, e in failed.items()]
                    or ["一个通知渠道都没有配，这条消息没有任何人收到"])
            # Many call sites ignore the return value, so "nobody received
            # this" is logged as an ERROR here.
            log.error("通知一条渠道都没送到：%s ｜ 标题：%s", "；".join(errs), title)
            return errs
        _say_delivered(route, delivered, title)
        if route == "group":
            self._copy_alarm(title, body, delivered)
        if failed and not self._announcing:
            self._announce_outage(failed, delivered)
        elif failed:
            for name, err in failed.items():
                log.warning("%s推送失败: %s", name, err)
        return []

    def send_group(self, title: str, body: str) -> list[str]:
        """Send via the 企业微信 group robot only.

        The group gets a heads-up the day before a banner goes live; other
        notifications go to Server酱. So this does not go through `send()`: an info
        title routes to `_INFO_ORDER`, which is Server酱 only.
        """
        delivered, failed = self._fan_out(title, body,
                                          order=("企业微信机器人",),
                                          stop_on_first=True)
        self._last.delivered = tuple(delivered)
        if delivered:
            _say_delivered("group", delivered, title)
            self._copy_alarm(title, body, delivered)
            return []
        errs = [f"{n}: {e}" for n, e in failed.items()] or ["企业微信机器人没开"]
        log.error("群通知没送到：%s ｜ 标题：%s", "；".join(errs), title)
        return errs

    def _announce_outage(self, failed: dict[str, str], delivered: list[str]) -> None:
        """Report each channel that refused this send as its own alarm, via the
        channels still alive - on every send it refused."""
        if not failed:
            return
        lines = []
        for name, err in failed.items():
            lines.append(f"· {name}：{err}")
        lines += [
            "",
            f"刚才那条消息已通过 {'、'.join(delivered)} 送达，没有丢。",
            "但这条通道在修好之前一直是坏的。",
        ]
        self._announcing = True
        title = f"🔌 推送通道故障：{'、'.join(failed)}"
        try:
            self.note_alarm(title)
            # Announce via the channels still alive in _GROUP_ORDER, stopping once one accepts.
            alive = tuple(n for n in _GROUP_ORDER if n not in failed) or _GROUP_ORDER
            sent, _ = self._fan_out(title, "\n".join(lines), order=alive, stop_on_first=True)
        finally:
            self._announcing = False
        if sent:
            _say_delivered("group", sent, title)
            self._copy_alarm(title, "\n".join(lines), sent)
        # The log line for each refusal. When the notice above reached the group
        # robot, errwatch does not push the line again (one fault, one push: this send).
        from ark_relay.features import errwatch  # noqa: PLC0415
        extra = {errwatch.PUSHED: True} if "企业微信机器人" in sent else {}
        for name, err in failed.items():
            log.warning("%s推送失败: %s", name, err, extra=extra)

    def send_group_image(self, path: Path) -> list[str]:
        """Send an image via the group robot. The self-built-app route needs an
        IP allowlist (60020); this one does not."""
        if not self.wecom_bot.enabled:
            return ["群机器人未配置"]
        try:
            self.wecom_bot.send_image(Path(path))
        except Exception as exc:  # noqa: BLE001
            log.warning("群机器人发图失败: %s", exc)
            return [str(exc)]
        _say_delivered("group", ["企业微信机器人"], f"图片 {Path(path).name}")
        return []


ATTEMPTS = _RETRIES


_log_netretry = logging.getLogger("ark.netretry")

GATEWAY = frozenset({502, 503, 504})
# The pause between attempts goes through here, looked up at each call: the tests' door
# (they set it to a no-op instead of patching time.sleep for every module).
_sleep = time.sleep


def transient(exc: BaseException) -> bool:
    """`exc` is the network cutting a request short, worth another try (the module docstring)."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in GATEWAY
    return isinstance(exc, (TimeoutError, http.client.IncompleteRead, http.client.BadStatusLine,
                            ConnectionError, urllib.error.URLError))


def call(fn, what: str, limit: float, *, detail: str = "", clock=None, sleep=None):
    """fn(seconds) -> its result: the first attempt gets `limit`, each later one what is left
    of it. A transient failure is tried again while time is left after the pause; anything
    else, the last attempt's failure, or no time left raises. `what` names the request in
    plain words (the recovered WARNING's first line is quoted in the daily report); `detail`
    (a key, a URL) and the first failure go on its second line. `clock` / `sleep` (default
    time.monotonic / the module's _sleep, looked up at call time) are the tests' doors."""
    clock = clock or time.monotonic
    sleep = sleep or _sleep
    start = clock()
    first = ""
    left = limit
    for attempt in range(ATTEMPTS):
        try:
            got = fn(limit if attempt == 0 else left)
        except Exception as exc:
            pause = _backoff(attempt)
            if (not transient(exc) or attempt + 1 >= ATTEMPTS
                    or limit - (clock() - start) - pause <= 0):
                raise
            first = first or f"{type(exc).__name__}: {exc}"
            _log_netretry.info("%s 第 %d 次没成（%s: %s），%.1f 秒后再试：%s", what, attempt + 1, type(exc).__name__, exc,
                     pause, detail)
            sleep(pause)
            left = limit - (clock() - start)
            if left <= 0:
                raise
            continue
        if attempt:
            from ark_relay.features import errwatch  # noqa: PLC0415 - avoid an import cycle
            _log_netretry.warning("%s第一次没成，第 %d 次成了\n%s 第一次：%s", what, attempt + 1, detail, first,
                        extra=errwatch.recovered())
        return got
    raise RuntimeError("unreachable")


_REAL_URLOPEN = urllib.request.urlopen


def _pinned_create(pin_host: str, pin_ip: str):
    def create(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        host, port = address
        target = pin_ip if (host or "").lower() == pin_host else host
        return socket.create_connection((target, port), timeout, source_address)
    return create


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, pin_host: str, pin_ip: str):
        super().__init__()
        self._pin_host = pin_host
        self._pin_ip = pin_ip

    def http_open(self, req):
        return urllib.request.AbstractHTTPHandler.do_open(self, self._conn, req)

    def _conn(self, host, **kw):
        conn = http.client.HTTPConnection(host, **kw)
        conn._create_connection = _pinned_create(self._pin_host, self._pin_ip)
        return conn


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pin_host: str, pin_ip: str):
        super().__init__()
        self._pin_host = pin_host
        self._pin_ip = pin_ip

    def https_open(self, req):
        return urllib.request.AbstractHTTPHandler.do_open(
            self, self._conn, req, context=getattr(self, "_context", None))

    def _conn(self, host, **kw):
        conn = http.client.HTTPSConnection(host, **kw)
        conn._create_connection = _pinned_create(self._pin_host, self._pin_ip)
        return conn


def response_peer_ip(resp) -> str:
    """Peer IP of an open urllib response, or '' if unavailable (e.g. test mock)."""
    sock = getattr(getattr(getattr(resp, "fp", None), "raw", None), "_sock", None)
    if sock is None:
        return ""
    try:
        peer = sock.getpeername()
        return str(peer[0]) if peer else ""
    except OSError:
        return ""


def resolve_ips(url: str) -> list[str]:
    """Distinct TCP IPs for `url`'s host (empty for IP literals or proxied schemes)."""
    parts = urllib.parse.urlsplit(url)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return []
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return []
    except ValueError:
        pass
    proxies = urllib.request.getproxies()
    if (proxies.get(scheme) or proxies.get("all")) and not urllib.request.proxy_bypass(host):
        return []
    port = parts.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for _, _, _, _, sa in infos:
        ip = str(sa[0])
        if ip and ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def next_cdn_ip(url: str, tried_ips: set[str], peer_ip: str, pin_ip: str, *,
                opener=None, resolve=None) -> str:
    """Record a failed edge IP in `tried_ips` and return another resolved IP, else ''."""
    if opener is not None and opener is not _REAL_URLOPEN:
        return ""
    ips = (resolve or resolve_ips)(url)
    if len(ips) < 2:
        return ""
    if pin_ip:
        tried_ips.add(pin_ip)
    if peer_ip:
        tried_ips.add(peer_ip)
    if not pin_ip and (not peer_ip or peer_ip not in ips):
        tried_ips.add(ips[0])
    for ip in ips:
        if ip not in tried_ips:
            return ip
    return ""


def open_pinned(req: urllib.request.Request, timeout: float,
                pin_ip: str = "", *, opener=None):
    """Open `req`, optionally pinning TCP to `pin_ip` while keeping Host and TLS SNI."""
    base = opener or urllib.request.urlopen
    if not pin_ip or base is not _REAL_URLOPEN:
        return base(req, timeout=timeout)
    host = (urllib.parse.urlsplit(req.full_url).hostname or "").lower()
    if not host:
        return base(req, timeout=timeout)
    built = urllib.request.build_opener(
        _PinnedHTTPHandler(host, pin_ip),
        _PinnedHTTPSHandler(host, pin_ip),
    )
    return built.open(req, timeout=timeout)
