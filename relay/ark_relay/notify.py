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
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .config import Config

log = logging.getLogger("ark.notify")

_TIMEOUT = 20


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


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

    def send_text(self, text: str) -> None:
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


class Notifier:
    """Fan out to every configured channel; one failure must not silence the rest."""

    def __init__(self, cfg: Config):
        self.wecom = WeCom(cfg)
        self.serverchan = ServerChan(cfg)

    @property
    def channels(self) -> list[str]:
        names = []
        if self.wecom.enabled:
            names.append("企业微信")
        if self.serverchan.enabled:
            names.append("Server酱")
        return names

    def send(self, title: str, body: str) -> list[str]:
        """Returns a list of human-readable failures (empty means all sent)."""
        errors: list[str] = []
        if self.wecom.enabled:
            try:
                self.wecom.send_text(f"{title}\n\n{body}" if body else title)
            except Exception as exc:  # noqa: BLE001 - report, never crash the loop
                errors.append(f"企业微信: {exc}")
                log.warning("企业微信推送失败: %s", exc)
        if self.serverchan.enabled:
            try:
                self.serverchan.send_text(title, body)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Server酱: {exc}")
                log.warning("Server酱推送失败: %s", exc)
        return errors

    def send_image(self, path: Path) -> list[str]:
        if not self.wecom.enabled:
            return ["企业微信未配置，无法发图"]
        try:
            self.wecom.send_image(path)
            return []
        except Exception as exc:  # noqa: BLE001
            return [f"企业微信发图: {exc}"]
