"""Push channels: 企业微信 self-built app (WeCom), 企业微信 group robot (WeComBot),
Server酱 (ServerChan), and the Notifier that routes each title to them.

Plain HTTP with urllib; no push library.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from ark_relay.core.config import Config

log = logging.getLogger("ark.notify")

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
        except (urllib.error.URLError, TimeoutError, OSError,
                json.JSONDecodeError, _Busy) as exc:
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
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
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
    """企业微信自建应用. Plain text, no length games, supports images.

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

    def send_image(self, path: Path) -> None:
        media_id = self._upload(path)
        self._message("image", {"media_id": media_id}, "企业微信发图失败")

    def _upload(self, path: Path) -> str:
        """multipart/form-data upload; returns media_id (valid 3 days)."""
        boundary = f"----ark{uuid.uuid4().hex}"
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="media"; filename="{path.name}"\r\n'.encode(),
            f"Content-Type: {ctype}\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ])
        url = (
            "https://qyapi.weixin.qq.com/cgi-bin/media/upload"
            f"?access_token={self._access_token()}&type=image"
        )
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("errcode") != 0:
            raise RuntimeError(f"媒体上传失败: {data.get('errcode')} {data.get('errmsg')}")
        return data["media_id"]


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

    def __init__(self, cfg: Config):
        self.url = cfg.wecom_bot_url

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def send_text(self, text: str) -> None:
        for part in WeCom._split(text, self._LIMIT):
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
                    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
                    log.warning("Server酱 前面的地址没送到（%s），换 %s 送到了", "；".join(errors),
                                url.split("/")[2], extra=errwatch.recovered())
                return
            errors.append(f"{url.split('/')[2]}: {r}")
        raise RuntimeError("Server酱 发送失败 -> " + "；".join(errors))


def _hint(name: str, err: str) -> str:
    """Turn a channel's raw error into something actionable on a phone."""
    if name == "企业微信" and "60020" in err:
        m = re.search(r"from ip:\s*([\d.]+)", err)
        ip = m.group(1) if m else "（错误里没带地址）"
        return (f"机器现在的出口地址是 {ip}，不在企业微信应用的可信名单里。家宽拨号地址会变；"
                "去企业微信管理后台「应用管理 → 这个应用 → 企业可信IP」把这个地址加进去，加了就恢复。")
    return ""


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
        self._announcing = False  # the outage alert itself goes out via _fan_out
        self._cfg = cfg
        self._alerts = None       # alertlog.AlertLog, made on first use
        self._last = threading.local()   # what the last send on this thread reached

    def went_to_group(self) -> bool:
        """Whether the last send / send_group on this thread was taken by the group robot.

        errwatch.group_pushed asks this: a log line repeating an alarm is kept out
        of the group only when that alarm really reached the group, not when it
        fell back to Server酱."""
        return "企业微信机器人" in getattr(self._last, "delivered", ())

    # ---------- the copy of every group alarm (alertlog.py) ----------

    def alert_log(self):
        if self._alerts is None:
            from ark_relay.features.alarm import alertlog  # noqa: PLC0415
            self._alerts = alertlog.for_config(self._cfg)
        return self._alerts

    def _copy_alarm(self, title: str, body: str) -> None:
        """Keep a delivered group alarm in COS alerts/<day>.jsonl (alertlog.py).

        The COS part runs on its own thread; never raises. Only delivered alarms
        are copied: an undelivered one is retried by its caller every tick."""
        try:
            version = str(self._store().get("versions", "code") or "")
            self.alert_log().copy(title, body, version)
        except Exception:   # the copy must never break the alarm path
            log.warning("报警没能抄一份到本地/COS", exc_info=True)

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
        if route == "group":
            self._copy_alarm(title, body)
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
            self._copy_alarm(title, body)
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
            if tip := _hint(name, err):
                lines.append(f"  {tip}")
        lines += [
            "",
            f"刚才那条消息已通过 {'、'.join(delivered)} 送达，没有丢。",
            "但这条通道在修好之前一直是坏的。",
        ]
        self._announcing = True
        title = f"🔌 推送通道故障：{'、'.join(failed)}"
        try:
            # The default order is _GROUP_ORDER, so this reaches the group too.
            sent, _ = self._fan_out(title, "\n".join(lines))
        finally:
            self._announcing = False
        if sent:
            self._copy_alarm(title, "\n".join(lines))
        # The log line for each refusal. When the notice above reached the group
        # robot, errwatch does not push the line again (one fault, one push: this send).
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
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
        return []

    def send_image(self, path: Path) -> list[str]:
        if not self.wecom.enabled:
            return ["企业微信未配置，无法发图"]
        try:
            self.wecom.send_image(path)
            return []
        except Exception as exc:  # noqa: BLE001
            return [f"企业微信发图: {exc}"]
