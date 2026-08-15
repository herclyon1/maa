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
    def _split(text: str, limit: int = _LIMIT) -> list[str]:
        if len(text.encode("utf-8")) <= limit:
            return [text]
        parts, cur, size = [], [], 0
        for line in text.split("\n"):
            n = len(line.encode("utf-8")) + 1
            if cur and size + n > limit:
                parts.append("\n".join(cur))
                cur, size = [], 0
            # A single line longer than the limit still has to go somewhere;
            # keep it whole rather than cutting mid-character.
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
    announced once per channel per process; the machine reboots twice a day, so
    a channel that stays broken keeps re-announcing itself until it is fixed.
    """

    def __init__(self, cfg: Config):
        self.wecom = WeCom(cfg)
        self.serverchan = ServerChan(cfg)
        self._announced_down: set[str] = set()
        self._announcing = False  # the outage alert itself goes out via _fan_out

    @property
    def channels(self) -> list[str]:
        names = []
        if self.wecom.enabled:
            names.append("企业微信")
        if self.serverchan.enabled:
            names.append("Server酱")
        return names

    def _fan_out(self, title: str, body: str) -> tuple[list[str], dict[str, str]]:
        """Try every enabled channel. -> (delivered names, {name: error})"""
        delivered: list[str] = []
        failed: dict[str, str] = {}
        attempts = (
            ("企业微信", self.wecom,
             lambda: self.wecom.send_text(f"{title}\n\n{body}" if body else title)),
            ("Server酱", self.serverchan,
             lambda: self.serverchan.send_text(title, body)),
        )
        for name, channel, call in attempts:
            if not channel.enabled:
                continue
            try:
                call()
            except Exception as exc:  # noqa: BLE001 - report, never crash the loop
                failed[name] = str(exc)
                log.warning("%s推送失败: %s", name, exc)
            else:
                delivered.append(name)
        return delivered, failed

    def send(self, title: str, body: str) -> list[str]:
        """Returns failures only when the message reached nobody.

        An empty list means the caller may consider the message delivered and
        stop holding it. A non-empty list means every channel refused it.
        """
        delivered, failed = self._fan_out(title, body)
        if not delivered:
            return [f"{n}: {e}" for n, e in failed.items()]
        # A channel that started working again becomes announceable once more.
        self._announced_down -= set(delivered)
        if not self._announcing:
            self._announce_outage(failed, delivered)
        return []

    def _announce_outage(self, failed: dict[str, str], delivered: list[str]) -> None:
        """Report a dead channel as its own alert, via the channels still alive."""
        fresh = {n: e for n, e in failed.items() if n not in self._announced_down}
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
            self._announced_down |= set(fresh)

    def send_image(self, path: Path) -> list[str]:
        if not self.wecom.enabled:
            return ["企业微信未配置，无法发图"]
        try:
            self.wecom.send_image(path)
            return []
        except Exception as exc:  # noqa: BLE001
            return [f"企业微信发图: {exc}"]
