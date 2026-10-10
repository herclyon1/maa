"""Where evidence files are uploaded: Tencent Cloud COS (`Cos`, the only store
evidence.uploaders() returns) and gofile.io (`Gofile`, kept for a hand-run
upload). `PermanentUploadError` is a refusal a retry cannot change.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


GOFILE = "https://api.gofile.io"


class Gofile:
    """Guest uploads into one folder, token and folder id remembered in the state dir."""

    def __init__(self, state_dir: Path):
        self.cred = state_dir / "evidence" / "gofile.json"
        self.token = ""
        self.folder = ""
        if self.cred.exists():
            try:
                d = json.loads(self.cred.read_text(encoding="utf-8"))
                self.token, self.folder = d.get("token", ""), d.get("folder", "")
            except (OSError, ValueError):
                pass

    def _server(self, timeout: int) -> str:
        with urllib.request.urlopen(f"{GOFILE}/servers", timeout=timeout) as r:
            d = json.loads(r.read())
        return d["data"]["servers"][0]["name"]

    def upload(self, path: Path, timeout: int = 900) -> dict:
        boundary = uuid.uuid4().hex
        fields = []
        if self.token:
            fields.append(("token", self.token))
        if self.folder:
            fields.append(("folderId", self.folder))
        body = b""
        for k, v in fields:
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode()
        body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"https://{self._server(timeout)}.gofile.io/contents/uploadfile", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                     **({"method": "POST"}))
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        if d.get("status") != "ok":
            raise RuntimeError(f"gofile: {d}")
        data = d["data"]
        if not self.token:
            self.token = data.get("guestToken", "")
            self.folder = data.get("parentFolder", "")
            self.cred.parent.mkdir(parents=True, exist_ok=True)
            self.cred.write_text(json.dumps({"token": self.token, "folder": self.folder}), encoding="utf-8")
        return {"id": data.get("id"), "name": data.get("name"), "page": data.get("downloadPage"),
                "size": path.stat().st_size, "md5": data.get("md5")}


class Cos:
    """Tencent Cloud COS through the XML API: one signed PUT per file, no SDK.

    Signature per the official recipe (q-sign-algorithm=sha1): SignKey =
    HMAC-SHA1(SecretKey, KeyTime); StringToSign = "sha1\n{KeyTime}\n{sha1(HttpString)}\n";
    HttpString = "{method}\n{path}\n\nhost={host}\n". Objects land under
    `<run_id>/<name>`; the returned `url` is the plain object URL and `page` a
    signed GET of it valid PAGE_TTL_S - the bucket is private, so the plain URL
    answers 403 to anyone tapping it in a push.
    """

    PAGE_TTL_S = 7 * 86400

    def __init__(self, secret_id: str, secret_key: str, bucket: str, region: str, prefix: str = ""):
        self.sid, self.skey, self.bucket, self.region = secret_id, secret_key, bucket, region
        self.host = f"{bucket}.cos.{region}.myqcloud.com"
        self.prefix = prefix.strip("/")

    def authorization(self, method: str, key: str, now: "int | None" = None, ttl: int = 3600) -> str:
        import hashlib  # noqa: PLC0415
        import hmac  # noqa: PLC0415
        start = int(now if now is not None else time.time()) - 60
        key_time = f"{start};{start + ttl}"
        sign_key = hmac.new(self.skey.encode(), key_time.encode(), hashlib.sha1).hexdigest()
        path = "/" + urllib.parse.quote(key, safe="/")
        http_string = f"{method.lower()}\n{path}\n\nhost={self.host}\n"
        string_to_sign = f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
        signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()
        return ("q-sign-algorithm=sha1&q-ak=" + self.sid + "&q-sign-time=" + key_time + "&q-key-time=" + key_time
                + "&q-header-list=host&q-url-param-list=&q-signature=" + signature)

    def signed_get(self, key: str, ttl: "int | None" = None) -> str:
        """A GET URL for `key` that opens without the keys (query-string signature)."""
        url = f"https://{self.host}/" + urllib.parse.quote(key, safe="/")
        return url + "?" + self.authorization("GET", key, ttl=ttl or self.PAGE_TTL_S)

    def object_key(self, path: Path) -> str:
        return f"{self.prefix}/{path.name}" if self.prefix else path.name

    # Answers a retry cannot change. 451 is what COS returns for an account in
    # arrears (「UnavailableForLegalReasons ... account is arrears」). probe() asks
    # with a HEAD on the bucket before a PUT is sent.
    _REFUSED = {451: "腾讯云账号欠费，要充值", 403: "密钥不对或没有这个桶的权限", 401: "密钥不对"}

    def probe(self, timeout: int = 20) -> str:
        """'' when the bucket accepts this key; otherwise the reason it never will."""
        req = urllib.request.Request(f"https://{self.host}/", method="HEAD",
                                     headers={"Authorization": self.authorization("HEAD", "")})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read()
        except urllib.error.HTTPError as exc:
            if exc.code in self._REFUSED:
                return f"COS 回了 {exc.code}：{self._REFUSED[exc.code]}"
        except (urllib.error.URLError, OSError) as exc:
            # No connection (e.g. WinError 10053, as an account in arrears can
            # answer): the PUT would fail the same way, so this round uploads nothing.
            return f"连不上 COS（{getattr(exc, 'reason', exc)}），这一轮不传"
        return ""

    def upload(self, path: Path, timeout: int = 900) -> dict:
        if reason := self.probe():
            raise PermanentUploadError(reason)
        key = self.object_key(path)
        url = f"https://{self.host}/" + urllib.parse.quote(key, safe="/")
        req = urllib.request.Request(url, data=path.read_bytes(), method="PUT",
                                     headers={"Authorization": self.authorization("PUT", key),
                                              "Content-Type": self._content_type(path)})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read()
        except urllib.error.HTTPError as exc:
            if exc.code in self._REFUSED:
                raise PermanentUploadError(f"COS 回了 {exc.code}：{self._REFUSED[exc.code]}") from exc
            raise
        return {"name": path.name, "size": path.stat().st_size, "store": "cos", "key": key,
                "url": url, "page": self.signed_get(key)}

    @staticmethod
    def _content_type(path: Path) -> str:
        # A log opens as text in the phone's browser instead of a download prompt.
        if path.suffix.lower() in (".log", ".txt"):
            return "text/plain; charset=utf-8"
        return "application/octet-stream"


class PermanentUploadError(RuntimeError):
    """The store refused for a reason a retry cannot change (wrong credentials,
    IP not on the allow-list): move to the next store at once."""
