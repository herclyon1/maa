"""Push channels.

Both APIs here were verified against the live services before being written:
WeCom returned errcode=0, Server酱 accepted the same key AUTO-MAS uses.

Kept as plain HTTP rather than a library so there is no guessing about a
dependency's surface. `onepush` can be swapped in later if more channels are
needed - it natively supports Server酱 and WeCom.
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
# in [0, min(_BACKOFF_CAP, _BACKOFF_BASE * 2**k)]. "The solution isn't to remove
# backoff. It's to add jitter." (https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)
# Until 2026-10-10 the wait was a fixed 1.5 s x attempt, so every sender that failed
# together retried together.
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
    """POST with retries, but only for transport failures.

    An alert gets one chance: nothing re-sends it if the push is dropped. And
    the push does get dropped - measured from Japan, sctapi.ftqq.com
    occasionally blows past the timeout mid-TLS-handshake and then answers in
    a second on the very next attempt. Losing a real failure alert to one
    flaky handshake is not acceptable, so transport errors are retried.

    An HTTP status is an answer, not a transport failure: a 403 endpoint will
    keep saying 403, and errcode=60020 will keep saying 60020. Those are
    raised immediately so the caller can fall through to another endpoint or
    another channel instead of sitting through pointless backoff. The one
    exception is 企业微信's errcode -1 「系统繁忙」, which its error-code page says
    to retry (at most 3 times) - retried here like a transport failure.

    The waits between attempts are exponential with full jitter (_backoff).
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
                # over. Until 2026-10-06 05:07 each failed attempt was a WARNING, so
                # errwatch pushed it to the group even when the next attempt went through.
                log.info("推送传输失败（第 %d/%d 次），%.1fs 后重试: %s",
                         attempt + 1, _RETRIES, delay, exc)
                time.sleep(delay)
            continue
        if last is not None:
            # Went through on a later attempt: recovered by itself, so the daily
            # report's list of the relay's own faults only, not the group. The user,
            # 2026-10-06 05:07, on faults that fixed themselves: 「报错后自己好了的，只进日报、不进群。」
            # A send whose every attempt failed raises below, and the caller logs
            # that as a WARNING / ERROR (Notifier.send, _announce_outage) - pushed.
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

    # 企业微信 text messages are capped at 2048 BYTES (not characters), and the
    # API silently truncates rather than erroring - a long daily report just
    # arrives with its tail missing. Split on line boundaries instead.
    _LIMIT = 1800  # leave room for the "(1/3)" marker

    @staticmethod
    def _hard_wrap(line: str, limit: int) -> list[str]:
        """Break one over-limit line at character boundaries, by UTF-8 bytes.

        An unbroken line has to be cut somewhere: the app API silently
        truncates past its byte cap, and the bot API *rejects* the whole
        message - and since the body is retried verbatim, a single model-
        written paragraph over the cap used to fail the daily report on every
        retry, which the shutdown path then waited on all night.
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

    This is the only way to reach 企业微信 from a machine whose public IP
    rotates. The self-built app above authenticates by IP, so the Mac in Japan
    (a shared IPv4-over-IPv6 address) and the game box behind dial-up
    broadband both get errcode=60020 the moment their address changes. A group
    robot authenticates by the key embedded in its URL instead, which is why
    that URL is a secret: it lives in the machine's .env and in the Mac's
    ~/.config/ark/push.env, never in this repo.

    The robot posts into a group chat rather than as a direct app message, and
    is capped at 20 messages per minute. Neither matters here: this system
    sends a handful of messages a day, all of them to the same person.
    """

    # 2026-08-31: this used to send markdown. 企业微信 itself accepts it, but
    # this group is a **WeChat** group, and WeChat does not understand a robot's
    # markdown - all the user saw on the phone was the single line 「暂不支持此
    # 消息类型，点击前往企业微信查看」, i.e. every group notification was wasted.
    # Switched to plain text, which both WeChat and 企业微信 understand. The byte
    # cap for text is 2048 (markdown's is 4096), so the margin here had to come
    # down with it.
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
                    # An earlier endpoint refused it and this one took it: recovered
                    # by itself, so the daily report only (the user's rule of
                    # 2026-10-06 05:07, quoted at _post). Its transport attempts are
                    # INFO lines (_post), so without this line the daily report would
                    # not show it at all.
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


# Three channels, three jobs (the user, 2026-09-14 evening):
#
#   企业微信群机器人  the real alarms only - nothing else, no 「中继已更新」, no
#                    progress notes, no test noise. One exception, sent from the
#                    Mac and never from here: 「总统令第 N 条」, the user's ruling
#                    on a question the sessions could not settle (BOARD A45 (3),
#                    2026-09-23; scripts/mac/push.py --decree)
#   Server酱          the daily report, and every other notification that means
#                    something
#   企业微信自建应用   (the private chat) never on its own - only text the user
#                    dictates by hand (push.py --private)
#
# Earlier that day everything went to the group; before that, alerts fanned out
# to all three. The daily report moved from the group to Server酱 the same night:
# the group robot caps a text message at 2048 bytes, so the report arrived as
# three or four 「(1/4)」 pieces (his words: 「企业群机器人的文字上限有，日报改成
# server酱推送」); Server酱 renders the whole report as one Markdown message.
# The group falls back to Server酱 when the robot refuses (an alarm must reach
# him); the daily falls back to the group (split) when Server酱 refuses; info
# that Server酱 refuses is returned as undelivered, never escalated.
_GROUP_ORDER = ("企业微信机器人", "Server酱")
_DAILY_ORDER = ("Server酱", "企业微信机器人")
_INFO_ORDER = ("Server酱",)
_ORDERS = {"group": _GROUP_ORDER, "daily": _DAILY_ORDER, "info": _INFO_ORDER}

# What the daily report or the phone page already says is not pushed again -
# it is logged and counts as delivered. The full title→route table, with the
# reason for every line, is docs/NOTIFICATIONS.md; test_notify_routing.py pins it.
# The user, 2026-09-14: the core rule is not to disturb him - push nothing that
# is already in the daily report or on the phone page.
_LOG_ONLY_PREFIXES = (
    "🔄 中继已更新",            # every deploy; the phone page shows the version
    "🗓️ 周常",                  # weekly gate closed/reopened; the phone page shows it
    "⏭️ 跳过模式",              # acknowledgement of a phone order
    "🛑 已停一切",              # acknowledgement of the phone's estop
    "📱 配置已修改",             # acknowledgement of a phone order
    "🗂️ 证据包已送出机器",       # bookkeeping behind a failure the alarm already reported
    "✅ 自动采集：补跑后全部走完",
    # texts.COLLECT_RETRY_FAILED and COLLECT_RECURRENT are not on this list any more:
    # failures go to the group (the user, 2026-10-06: every error, every time). The
    # retry's start (texts.COLLECT_RETRY_START) is not sent at all
    # (collect_retry.maybe_run): its outcome decides.
    "🩹 OK-WW 补丁",            # all patches bound - the healthy case; ⚠️ variant still goes out
    "🥚 开始刷声骸",            # acknowledgement of a phone order; 收工 still goes out
    "✅ ",                      # any successful phone-order acknowledgement (the page shows it)
)
# Until 2026-10-06 two more lists kept failures from the group: the self-heal
# notice (「中途失败过，重试后成功」, daily report only) and the pre-update / game
# update that could not confirm (「⚠️ 预更新没能确认」 / 「⚠️ 游戏更新没能确认」, demoted
# to Server酱 even with alert=True). The user's order that day, every error to the
# group robot, every time (「不论多少次什么错误都要发」; in full in docs/NOTIFICATIONS.md,
# the 🩺 row), ended both lists; what stays on the log list above is success and
# acknowledgement only.


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

    **Delivered means at least one channel accepted it.** Reporting a partial
    failure as a total one is not the safe default it looks like: the caller
    holds undelivered messages on disk and retries every poll cycle, so one
    broken channel turns a single alert into the same alert every 30 seconds
    all night - and because shutdown waits for that queue to drain, the machine
    never powers off either.

    That failure mode is not hypothetical. Both machines sit behind dial-up
    consumer broadband whose public IP rotates, and 企业微信 rejects any call
    from an IP outside the app's trusted list (errcode 60020). The day the IP
    changes, every one of those consequences fires at once.

    A dead channel is still a real fault, so it is reported in its own right -
    through whichever channel still works - rather than swallowed: every send
    that a channel refused (and another one took) is announced, each time.

    From 2026-08-22 until 2026-10-06 the same fault on the same channel was
    announced once and then kept quiet until it changed or cleared (a record on
    disk, keyed by a fingerprint of the error with 企业微信's hint and egress IP
    stripped), and the 「推送失败」 log line was written only when the error text
    changed: that day the same 60020 notice had gone out over and over. The
    user's order of 2026-10-06, every error to the group robot and every
    time (「不论多少次什么错误都要发」), ended both of them.
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
        """A group alarm that was delivered is also kept in COS alerts/<day>.jsonl
        (the user, 2026-10-06 00:23). The COS part runs on its own thread. Never raises.

        Only once delivered: an undelivered alarm is retried by its caller every
        tick, and copying each attempt would write the same alarm over and over."""
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

        `stop_on_first` returns as soon as one channel accepts, so the later
        ones are never even attempted - that is what keeps a routine report from
        landing on the phone twice.
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
                # Until 2026-10-06 this logged only when the error text changed
                # (2026-08-26: 74 identical 60020 lines in a day); every failure
                # is said now (the user that day: 「不论多少次什么错误都要发」).
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
            # empty list would tell the caller "delivered" - a false green.
            # send_group already guarded this; send did not (found writing tests,
            # 2026-09-08). Production cannot reach this path today
            # (Config.validate refuses to start without a channel), but
            # "unreachable, so it does not matter" has been wrong once already.
            errs = ([f"{n}: {e}" for n, e in failed.items()]
                    or ["一个通知渠道都没有配，这条消息没有任何人收到"])
            # A non-empty return = **not one channel got it**. Many of the 11
            # call sites throw the return value away (things like
            # `notifier.send("🆕 预更新", note)`), so "nobody received this
            # notification" was being silently dropped. Log an ERROR here, which
            # no call site can miss. Found in the full audit on 2026-08-30; it is
            # the same class of defect as a silent green.
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

        Decided by the user on 2026-08-31: say something in the group the day
        before a banner goes live, and the rest of the time he just reads
        Server酱. So this **must not** go through `send()` - an info title routes
        to `_INFO_ORDER`, which is Server酱 only, so it would never reach the group.
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
        """Report a channel that refused this send as its own alarm, via the channels
        still alive - every send it refused (until 2026-10-06 once per fault)."""
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
            # The default order is the group's (_ALERT_ORDER), so this one reaches the group too.
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
