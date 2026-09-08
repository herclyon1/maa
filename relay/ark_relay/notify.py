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
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .config import Config

log = logging.getLogger("ark.notify")

_TIMEOUT = 20
_RETRIES = 3
_BACKOFF = 1.5  # seconds, multiplied by the attempt number


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
    another channel instead of sitting through pointless backoff.
    """
    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise  # the server answered - retrying cannot change the answer
        except (urllib.error.URLError, TimeoutError, OSError,
                json.JSONDecodeError) as exc:
            last = exc
            if attempt < _RETRIES - 1:
                delay = _BACKOFF * (attempt + 1)
                log.warning("推送传输失败（第 %d/%d 次），%.1fs 后重试: %s",
                            attempt + 1, _RETRIES, delay, exc)
                time.sleep(delay)
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

    def _send_one(self, text: str) -> None:
        url = (
            "https://qyapi.weixin.qq.com/cgi-bin/message/send"
            f"?access_token={self._access_token()}"
        )
        r = _post_json(url, {
            "touser": self.cfg.wecom_touser,
            "msgtype": "text",
            "agentid": int(self.cfg.wecom_agentid),
            "text": {"content": text},
        })
        if r.get("errcode") != 0:
            raise RuntimeError(f"企业微信发送失败: {r.get('errcode')} {r.get('errmsg')}")

    def send_text(self, text: str) -> None:
        for i, part in enumerate(self._split(text)):
            if i:
                time.sleep(0.4)  # keep the parts in order on the client
            self._send_one(part)

    def send_image(self, path: Path) -> None:
        media_id = self._upload(path)
        url = (
            "https://qyapi.weixin.qq.com/cgi-bin/message/send"
            f"?access_token={self._access_token()}"
        )
        r = _post_json(url, {
            "touser": self.cfg.wecom_touser,
            "msgtype": "image",
            "agentid": int(self.cfg.wecom_agentid),
            "image": {"media_id": media_id},
        })
        if r.get("errcode") != 0:
            raise RuntimeError(f"企业微信发图失败: {r.get('errcode')} {r.get('errmsg')}")

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
    that URL is a secret and lives only in .env.

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
                return
            errors.append(f"{url.split('/')[2]}: {r}")
        raise RuntimeError("Server酱 发送失败 -> " + "；".join(errors))


def _hint(name: str, err: str) -> str:
    """Turn a channel's raw error into something actionable on a phone."""
    if name == "企业微信" and "60020" in err:
        return ("可信 IP 不匹配。家宽拨号 IP 会变，去企业微信后台"
                "「应用 → 企业可信IP」把当前出口 IP 重新加进去。")
    return ""


# Alerts: fan out to every channel. If one channel is dead another must take
# over - reasoning in the Notifier class docstring.
_ALERT_ORDER = ("企业微信", "企业微信机器人", "Server酱")

# Routine: send to one channel only, stop at the first success - the later ones
# are never even called.
#
# Server酱 comes first as a measured conclusion: it has no IP allowlist, and the
# user said explicitly on 2026-08-24: "server酱长期稳定（从来没出过问题）".
# 企业微信 is the exact opposite - both machines sit behind consumer broadband,
# and the moment the public IP rotates everything is refused with errcode 60020.
#
# Why not "send everywhere, it is safer": the same daily report landing in both
# WeChat and Server酱 is merely annoying, not more reliable. Redundancy is worth
# it for alerts, not for routine traffic; conflating the two ends with real
# alerts drowned in routine noise. The user, on the spot on 2026-08-24:
# "不要重复".
_ROUTINE_ORDER = ("Server酱", "企业微信机器人", "企业微信")


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
    through whichever channel still works - rather than swallowed. It is
    announced once per channel per fault, and that record is kept on disk.

    It used to live in memory, "once per channel per process", on the reasoning
    that the machine reboots twice a day so a channel left broken would keep
    reminding. In practice the relay restarts far more often than the machine
    does - every self-update is a restart - and on 2026-08-22, a day of
    deployments, the same 企业微信 60020 notice went out over and over. A
    reminder that arrives on someone's phone that often is not a reminder, it
    is noise, and noise is what makes real alerts get ignored.

    Now: the same fault on the same channel is announced once and stays quiet
    until it either changes or clears. The fingerprint deliberately strips the
    parts of the message that differ every time - 企业微信's `hint: [...]` and
    the reported egress IP - so a rotating home IP does not read as a new fault.
    """

    def __init__(self, cfg: Config):
        self.wecom = WeCom(cfg)
        self.wecom_bot = WeComBot(cfg)
        self.serverchan = ServerChan(cfg)
        # The last failure reason per channel, used to suppress repeat alerts
        # (see _fan_out).
        self._last_send_error: dict[str, str] = {}
        self._state_dir = Path(cfg.state_dir)
        self._announced_down: dict[str, str] = self._load_down()
        self._announcing = False  # the outage alert itself goes out via _fan_out

    # ---------- which faults have already been reported ----------

    @staticmethod
    def _fingerprint(err: str) -> str:
        """What makes two failures 'the same fault'.

        企业微信's 60020 carries a fresh request hint and the current egress IP
        on every attempt, so the raw message never repeats. Strip both; what is
        left is the error code and its text, which is the thing that is either
        fixed or not.
        """
        s = re.sub(r"hint: ?\[[^\]]*\]", "", err)
        s = re.sub(r"from ip: ?[0-9a-fA-F:.]+", "", s)
        return " ".join(s.split())[:160]

    def _store(self):
        from .statestore import StateStore  # noqa: PLC0415 - avoids an import cycle
        return StateStore(self._state_dir)

    def _load_down(self) -> dict[str, str]:
        data = self._store().get("queues", "channels_down")
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save_down(self) -> None:
        try:
            self._store().set("queues", "channels_down", dict(self._announced_down))
        except OSError:
            # Worst case the notice repeats once more. Never let bookkeeping
            # about an alert break the alert path itself.
            log.warning("记不住已通报的通道故障", exc_info=True)

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
        for name in (order or _ALERT_ORDER):
            channel, call = attempts[name]
            if not channel.enabled:
                continue
            try:
                call()
            except Exception as exc:  # noqa: BLE001 - report, never crash the loop
                failed[name] = str(exc)
                # Say the same failure once. 企业微信's 60020 (IP not in the
                # allowlist) is persistent: on 2026-08-26 it produced 74
                # identical alerts in one day, and repeated noise drowns the
                # failures that actually changed. Speak up again only when the
                # error text changes; also say so once when it recovers.
                if self._last_send_error.get(name) != str(exc):
                    log.warning("%s推送失败: %s", name, exc)
                    self._last_send_error[name] = str(exc)
            else:
                if self._last_send_error.pop(name, None) is not None:
                    log.info("%s推送已恢复", name)
                delivered.append(name)
                if stop_on_first:
                    break
        return delivered, failed

    def send(self, title: str, body: str, *, alert: bool = False) -> list[str]:
        """Returns failures only when the message reached nobody.

        An empty list means the caller may consider the message delivered and
        stop holding it. A non-empty list means every channel refused it.

        `alert=True` fans out to **every** channel - use it only for faults
        someone has to act on. Everything else (the daily report, pre-update,
        annihilation, the to-do list) goes to **one** channel; see the note on
        `_ROUTINE_ORDER`.
        """
        if alert:
            delivered, failed = self._fan_out(title, body)
        else:
            delivered, failed = self._fan_out(
                title, body, order=_ROUTINE_ORDER, stop_on_first=True)
        if not delivered:
            # `or [...]`：一个通道都没配的时候 `failed` 是空的，返回空列表就等于
            # 告诉调用方「送到了」——正是「假的绿」。send_group 早就这么兜了，
            # send 漏了，2026-09-08 补测试时发现的不对称。
            # 现在生产上够不到这条路（Config.validate 不许一个通道都不配就启动），
            # 但这种「够不到所以无所谓」的判断错过一次就够了。
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
        # A channel that started working again becomes announceable once more.
        if any(n in self._announced_down for n in delivered):
            for n in delivered:
                self._announced_down.pop(n, None)
            self._save_down()
        if not self._announcing:
            self._announce_outage(failed, delivered)
        return []

    def send_group(self, title: str, body: str) -> list[str]:
        """Send via the 企业微信 group robot only.

        Decided by the user on 2026-08-31: say something in the group the day
        before a banner goes live, and the rest of the time he just reads
        Server酱. So this **must not** go through `send()` - that follows
        `_ROUTINE_ORDER`, where Server酱 comes first and the first success
        stops the loop, so it would never reach the group.
        """
        delivered, failed = self._fan_out(title, body,
                                          order=("企业微信机器人",),
                                          stop_on_first=True)
        if delivered:
            return []
        errs = [f"{n}: {e}" for n, e in failed.items()] or ["企业微信机器人没开"]
        log.error("群通知没送到：%s ｜ 标题：%s", "；".join(errs), title)
        return errs

    def _announce_outage(self, failed: dict[str, str], delivered: list[str]) -> None:
        """Report a dead channel as its own alert, via the channels still alive."""
        fresh = {n: e for n, e in failed.items()
                 if self._announced_down.get(n) != self._fingerprint(e)}
        if not fresh:
            return
        lines = []
        for name, err in fresh.items():
            lines.append(f"· {name}：{err}")
            if tip := _hint(name, err):
                lines.append(f"  {tip}")
        lines += [
            "",
            f"刚才那条消息已通过 {'、'.join(delivered)} 送达，没有丢。",
            "但这条通道在修好之前一直是坏的。",
        ]
        self._announcing = True
        try:
            sent, _ = self._fan_out(
                f"🔌 推送通道故障：{'、'.join(fresh)}", "\n".join(lines))
        finally:
            self._announcing = False
        if sent:
            for n, e in fresh.items():
                self._announced_down[n] = self._fingerprint(e)
            self._save_down()

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
