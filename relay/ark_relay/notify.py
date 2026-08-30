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

from .config import Config, atomic_write_text

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

    # 2026-08-31：原来发的是 markdown。企业微信自己收得下，但这个群是**微信群**，
    # 微信不认机器人的 markdown，用户手机上只看到一行「暂不支持此消息类型，
    # 点击前往企业微信查看」——等于每一条群通知都白发了。改成纯文本，
    # 微信和企业微信都认。text 的字节上限是 2048（markdown 是 4096），
    # 所以这里的余量也要跟着降。
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


# 报警：全渠道扇出。一个渠道挂了，另一个必须顶上——理由见 Notifier 的类注释。
_ALERT_ORDER = ("企业微信", "企业微信机器人", "Server酱")

# 日常：只发一个，第一个成功就停，后面的根本不会被调用。
#
# Server酱 排第一是实测结论：它没有 IP 白名单，用户 2026-08-24 明确说
# "server酱长期稳定（从来没出过问题）"。企业微信恰恰相反——两台机器都在
# 家宽后面，公网 IP 一转就 errcode 60020 全拒。
#
# 为什么不是"全发更保险"：同一份日报同时落到微信和 Server酱只是烦，不会
# 更可靠。冗余的价值在报警，不在日常；把两者混为一谈的结果是真告警被日常
# 噪声淹掉。用户 2026-08-24 当场提的："不要重复"。
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
        # 每个渠道上一次的失败原因，用来压掉重复告警（见 _fan_out）。
        self._last_send_error: dict[str, str] = {}
        self._down_path = Path(cfg.state_dir) / "channels-down.json"
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

    def _load_down(self) -> dict[str, str]:
        try:
            data = json.loads(self._down_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save_down(self) -> None:
        try:
            atomic_write_text(self._down_path,
                              json.dumps(self._announced_down, ensure_ascii=False))
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
        ones are never even attempted - that is what keeps a routine报告 from
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
                # 同一条失败只说一次。企业微信的 60020（IP 不在白名单）是持续性的，
                # 2026-08-26 一天刷了 74 条一模一样的告警——重复的噪音会把真正
                # 变化了的失败淹掉。错误内容变了才再说一次；恢复了也说一次。
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
        someone has to act on. Everything else (日报、预更新、剿灭、待办)
        goes to **one** channel; see the note on `_ROUTINE_ORDER`.
        """
        if alert:
            delivered, failed = self._fan_out(title, body)
        else:
            delivered, failed = self._fan_out(
                title, body, order=_ROUTINE_ORDER, stop_on_first=True)
        if not delivered:
            errs = [f"{n}: {e}" for n, e in failed.items()]
            # 返回非空 = **一条渠道都没送到**。11 个调用点里有很多把返回值丢了
            # （`notifier.send("🆕 预更新", note)` 这种），于是「这条通知谁都没
            # 收到」会被静默扔掉。在这里记一条 ERROR，任何调用点都漏不掉。
            # 2026-08-30 全量审查时发现，和「静默变绿」是同一类毛病。
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
        """只发企业微信群机器人。

        用户 2026-08-31 定的：卡池开服前一天在群里说一声，其余时间他自己
        看 Server酱 就行。所以这条**不能**走 `send()`——那个按
        `_ROUTINE_ORDER` 走，Server酱 优先，第一个成功就停，永远到不了群里。
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

    def send_image(self, path: Path) -> list[str]:
        if not self.wecom.enabled:
            return ["企业微信未配置，无法发图"]
        try:
            self.wecom.send_image(path)
            return []
        except Exception as exc:  # noqa: BLE001
            return [f"企业微信发图: {exc}"]
