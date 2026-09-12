"""Evidence bundles in the form each upstream project asks for, kept off the machine.

Each of the three issue templates wants its own program's log export, not a
folder we chose:

* MaaEnd: the 🗄️ button - `MaaEnd-logs-<version>-<stamp>-partNNN.zip`
  (MXU `src-tauri/src/commands/file_ops.rs::export_logs_blocking`).
* MAA: 「设置 → 问题反馈 → 生成日志压缩包」 - `report_<stamp>_partNN.zip`
  (`IssueReportUserControlModel.GenerateSupportPayload`).
* OK-WW: 「Export Logs」 - `<gui_title>-log.zip` of `screenshots/` + `logs/`
  (ok-script `ok/ui/qt/start/StartTab.py::export_logs`).

None of the three is reachable from outside its UI (a Tauri command, a WPF
button, a Qt button), so this module does what those buttons do, file for
file, from the source read on 2026-09-12 and pinned below. The pin is not
decoration: `check_sources()` fetches the same files from the upstream default
branch (through jsDelivr, which the machine can reach when github.com cannot)
and compares hashes, so a change upstream produces a notice the same morning
instead of a bundle that quietly stopped matching (the user's requirement of
2026-09-12: a source change 一定要能发现).

Where it goes (`pick_uploader`, first that is configured):

1. Tencent Cloud COS (`Cos`) - a bucket of his, signed PUT/GET with the XML
   API, nothing to install. Scriptable retrieval from the Mac
   (`scripts/mac/evidence.sh pull`). Needs COS_* in .env; nobody but the
   account owner can create that (the user, 2026-09-12: 「gofile换成能脚本取的cos」).
2. The WeCom app (`WeComFiles`) - the same credentials the relay already pushes
   with. Each file goes to him as a file message (he opens it in WeCom); files
   over 20 MB are cut into numbered pieces and joined back by `evidence.sh pull`,
   which fetches the media by id within WeCom's three-day window. Off-machine,
   no new account, reachable from the machine.
3. gofile.io (`Gofile`) - last resort: a guest folder only a person can download
   from through the web page (its API refuses guest listing; measured 2026-09-12).

The local copy under `state/evidence/` stays for thirty days.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ark.evidence")

# --------------------------------------------------------------- source pins
# Read and copied on 2026-09-12; `commit` is the last commit touching the file
# at that time, `sha256` is of the raw file. Renew both when re-verifying.


@dataclass(frozen=True)
class Pin:
    name: str
    repo: str
    branch: str
    path: str
    commit: str
    sha256: str


PINS = (
    Pin("MaaEnd 导出（MXU file_ops.rs）", "MistEO/MXU", "main",
        "src-tauri/src/commands/file_ops.rs",
        "eb0e21271ff6a64de8f42a6995c2f709e3463f8f",
        "041f79df6a804db2835e4c37c91e84d898e841c993d9bb925b93acd4dcc0f379"),
    Pin("MAA 生成日志压缩包（IssueReportUserControlModel.cs）",
        "MaaAssistantArknights/MaaAssistantArknights", "dev-v2",
        "src/MaaWpfGui/ViewModels/UserControl/Settings/IssueReportUserControlModel.cs",
        "1cd98d5c2147409f046cbccf148350517523ae9f",
        "b339163cb774a6db4e95f40a7de7462b3c496eed4a433a6dc08f08546f2962c2"),
    Pin("OK-WW Export Logs（ok-script StartTab.py）", "ok-oldking/ok-script", "master",
        "ok/ui/qt/start/StartTab.py",
        "41a59bc67e6708158a62cae970709e8e37a3305f",
        "9c5a481f46834dfb385f5b52110fa021d596a91df1037c91f84672fd5486f94a"),
)
JSDELIVR = "https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}"


def check_sources(fetch=None, timeout: int = 30) -> tuple[list[str], list[str]]:
    """(changed pin names, unreachable pin names) against the upstream default branches."""
    def _get(url: str) -> bytes:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    fetch = fetch or _get
    changed, unreachable = [], []
    for pin in PINS:
        try:
            raw = fetch(JSDELIVR.format(repo=pin.repo, branch=pin.branch, path=pin.path))
        except (urllib.error.URLError, OSError, ValueError):
            unreachable.append(pin.name)
            continue
        if hashlib.sha256(raw).hexdigest() != pin.sha256:
            changed.append(pin.name)
    return changed, unreachable


# ------------------------------------------------------ MaaEnd (MXU export)
# Mirrors export_logs_blocking: regular files first (debug/*.log|*.dmp sorted by
# name, then config/** recursively, then debug/<subdir>/**.{log,json,dmp}
# keeping the subfolder), then on_error and vision images newest first, split
# into volumes of at most MAX_VOLUME_BYTES, part numbers zero-padded to 2
# digits (3 when there are 100+ entries), named
# `<project>-logs-<version>-<YYYYmmdd-HHMMSS>-partNN.zip`.
MAAEND_MAX_VOLUME = 24_500_000
_IMAGE_EXT = (".png", ".jpg", ".jpeg")


def _walk_sorted(dir_: Path, prefix: str) -> list[tuple[Path, str]]:
    if not dir_.is_dir():
        return []
    out = []
    for p in dir_.rglob("*"):
        if p.is_file():
            rel = p.relative_to(dir_).as_posix()
            out.append((p, f"{prefix}/{rel}" if prefix else rel))
    out.sort(key=lambda t: t[1])
    return out


def maaend_entries(maaend_dir: Path) -> list[tuple[Path, str]]:
    """The export's file list in MXU's order. Public so a test can check it against a real tree."""
    debug = maaend_dir / "debug"
    if not debug.is_dir():
        return []
    regular: list[tuple[Path, str]] = []
    for p in sorted(debug.glob("*"), key=lambda q: q.name):
        if p.is_file() and p.suffix.lower() in (".log", ".dmp"):
            regular.append((p, p.name))
    regular += _walk_sorted(maaend_dir / "config", "config")
    for sub in sorted(q for q in debug.iterdir() if q.is_dir()):
        regular += [(p, n) for p, n in _walk_sorted(sub, sub.name)
                    if p.suffix.lower() in (".log", ".json", ".dmp")]
    images: list[tuple[Path, str]] = []
    for name in ("on_error", "vision"):
        d = debug / name
        if d.is_dir():
            files = [p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in _IMAGE_EXT]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            images += [(p, f"{name}/{p.relative_to(d).as_posix()}") for p in files]
    return regular + images


ZIP_LOCAL_HEADER_OVERHEAD = 64
ZIP_EOCD_BYTES = 22
ZIP_CENTRAL_DIR_FIXED_BYTES = 46
_TEXT_EXT = {".log", ".json", ".txt", ".toml", ".yaml", ".yml", ".xml", ".csv"}


def _estimate_compressed(path: Path, size: int) -> int:
    """MXU's conservative upper bound by extension: text /4, images and dumps as-is."""
    return size // 4 if path.suffix.lower() in _TEXT_EXT else size


def _measure_compressed(path: Path) -> int:
    """Exact deflate size, the same algorithm the zip uses (MXU pre-compresses once when the estimate trips)."""
    import zlib  # noqa: PLC0415
    c = zlib.compressobj(level=-1, wbits=-15)
    n = 0
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            n += len(c.compress(chunk))
    return n + len(c.flush())


def _volumes(entries: list[tuple[Path, str]], max_bytes: int) -> list[list[tuple[Path, str]]]:
    """Split like MXU: by *compressed* bytes on disk, counting zip headers and the central directory.

    The written size of a volume is tracked as MXU's CountingWriter does it -
    each entry adds its deflated size plus a 64-byte local-header allowance,
    and the central directory (46 bytes + name per entry, 22 for the EOCD) is
    reserved. A file is only pre-compressed when the by-extension estimate
    would overflow; that is MXU's two-stage check, not an optimisation of ours.
    """
    vols: list[list[tuple[Path, str]]] = []
    i = 0
    while i < len(entries):
        vol: list[tuple[Path, str]] = []
        written = 0
        reserve = ZIP_EOCD_BYTES
        while i < len(entries):
            path, name = entries[i]
            cd = ZIP_CENTRAL_DIR_FIXED_BYTES + len(name.encode("utf-8"))
            size = path.stat().st_size
            est = _estimate_compressed(path, size) + ZIP_LOCAL_HEADER_OVERHEAD
            exact = None
            if vol and written + reserve + est + cd > max_bytes:
                exact = _measure_compressed(path) + ZIP_LOCAL_HEADER_OVERHEAD
                if written + reserve + exact + cd > max_bytes:
                    break
            vol.append((path, name))
            # MXU's counter holds the bytes really written, so an estimate
            # that was too kind (a .log full of random bytes) overflows this
            # volume but is corrected before the next file is judged.
            written += exact if exact is not None else _measure_compressed(path) + ZIP_LOCAL_HEADER_OVERHEAD
            reserve += cd
            i += 1
        vols.append(vol)
    return vols


def bundle_maaend(maaend_dir: Path, out_dir: Path, version: str, stamp: datetime | None = None) -> list[Path]:
    entries = maaend_entries(maaend_dir)
    if not entries:
        return []
    stamp = stamp or datetime.now()
    base = f"MaaEnd-logs-{version}-{stamp.strftime('%Y%m%d-%H%M%S')}"
    width = 3 if len(entries) >= 100 else 2
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, vol in enumerate(_volumes(entries, MAAEND_MAX_VOLUME), 1):
        zp = out_dir / f"{base}-part{i:0{width}d}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for p, name in vol:
                zf.write(p, name)
        paths.append(zp)
    return paths


# ----------------------------------------------------------- MAA (report)
# Mirrors GenerateSupportPayload: part01 = config/** + resource/*_custom.* +
# cache/** + debug root files; part02.. = debug subfolder files newer than three
# days, 20 MB per part; plus the full report_<stamp>.zip of everything.
MAA_PART = 20 * 1024 * 1024


def bundle_maa(maa_dir: Path, out_dir: Path, stamp: datetime | None = None) -> list[Path]:
    stamp = stamp or datetime.now()
    base = f"report_{stamp.strftime('%m-%d_%H-%M-%S')}"
    debug, config, resource, cache = (maa_dir / n for n in ("debug", "config", "resource", "cache"))
    part01 = []
    part01 += _walk_sorted(config, "config")
    part01 += [(p, n) for p, n in _walk_sorted(resource, "resource") if "_custom." in p.name.lower()]
    part01 += _walk_sorted(cache, "cache")
    if debug.is_dir():
        part01 += [(p, f"debug/{p.name}") for p in sorted(debug.iterdir())
                   if p.is_file() and not p.name.lower().startswith("report")]
    cutoff = time.time() - 3 * 86400
    sub = [(p, n) for p, n in _walk_sorted(debug, "debug")
           if p.parent != debug and p.stat().st_mtime >= cutoff and not p.name.lower().startswith("report")]
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    if part01:
        zp = out_dir / f"{base}_part01.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for p, n in part01:
                zf.write(p, n)
        paths.append(zp)
    for i, vol in enumerate(_volumes(sub, MAA_PART), 2):
        zp = out_dir / f"{base}_part{i:02d}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for p, n in vol:
                zf.write(p, n)
        paths.append(zp)
    return paths


# ---------------------------------------------------------- OK-WW (export)
# Mirrors StartTab.export_logs: every file under <working>/screenshots and
# <working>/logs, paths relative to the working dir, one zip named
# `<gui_title>-log.zip`.

def bundle_okww(working_dir: Path, out_dir: Path, gui_title: str = "ok-ww") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    zp = out_dir / f"{gui_title}-log.zip"
    n = 0
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in ("screenshots", "logs"):
            d = working_dir / folder
            if not d.is_dir():
                continue
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(working_dir).as_posix())
                    n += 1
    if n == 0:
        zp.unlink(missing_ok=True)
        return []
    return [zp]


# ----------------------------------------------------------------- upload

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
    `<run_id>/<name>`; the returned `url` is a plain object URL that `sign_url`
    turns into a GET the Mac can fetch.
    """

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

    def object_key(self, path: Path) -> str:
        return f"{self.prefix}/{path.name}" if self.prefix else path.name

    def upload(self, path: Path, timeout: int = 900) -> dict:
        key = self.object_key(path)
        url = f"https://{self.host}/" + urllib.parse.quote(key, safe="/")
        req = urllib.request.Request(url, data=path.read_bytes(), method="PUT",
                                     headers={"Authorization": self.authorization("PUT", key),
                                              "Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
        return {"name": path.name, "size": path.stat().st_size, "store": "cos", "key": key,
                "url": url, "page": url}


class PermanentUploadError(RuntimeError):
    """The store refused for a reason a retry cannot change (wrong credentials,
    IP not on the allow-list): move to the next store at once."""


_WECOM_PERMANENT = {40001, 40013, 40014, 41001, 42001, 60020, 60011, 81013, 93000}


class WeComFiles:
    """Evidence as WeCom file messages to the same person the relay already pushes to.

    WeCom caps a file at 20 MB and keeps uploaded media for three days; a bigger
    file is cut into `<name>.p01of03` pieces (join with `evidence.sh pull` or
    `copy /b`). The message reaches his phone the moment it is sent, so the
    evidence is readable with the machine off; the media ids in the index let
    the Mac fetch the bytes back within the three days.
    """

    LIMIT = 19 * 1024 * 1024

    def __init__(self, cfg):
        self.cfg = cfg
        self._token = ""
        self._until = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._until:
            return self._token
        url = ("https://qyapi.weixin.qq.com/cgi-bin/gettoken"
               f"?corpid={self.cfg.wecom_corpid}&corpsecret={self.cfg.wecom_secret}")
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("errcode") != 0:
            raise RuntimeError(f"企业微信 gettoken: {d.get('errcode')} {d.get('errmsg')}")
        self._token, self._until = d["access_token"], time.time() + int(d.get("expires_in", 7200)) - 300
        return self._token

    def _post(self, url: str, data: bytes, ctype: str, timeout: int) -> dict:
        return _wecom_post(url, data, ctype, timeout)

    def _upload_piece(self, name: str, data: bytes, timeout: int) -> str:
        boundary = "----ark" + uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="media"; filename="{name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n", data, f"\r\n--{boundary}--\r\n".encode()])
        d = self._post("https://qyapi.weixin.qq.com/cgi-bin/media/upload"
                       f"?access_token={self.token()}&type=file", body,
                       f"multipart/form-data; boundary={boundary}", timeout)
        return d["media_id"]

    def _send_file(self, media_id: str) -> None:
        self._post(f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={self.token()}",
                   json.dumps({"touser": self.cfg.wecom_touser, "msgtype": "file",
                               "agentid": int(self.cfg.wecom_agentid), "file": {"media_id": media_id}}).encode(),
                   "application/json", 60)

    def upload(self, path: Path, timeout: int = 600) -> dict:
        data = path.read_bytes()
        pieces = split_pieces(path.name, data, self.LIMIT)
        sent = []
        for name, chunk in pieces:
            mid = self._upload_piece(name, chunk, timeout)
            self._send_file(mid)
            sent.append({"name": name, "media_id": mid, "size": len(chunk)})
        return {"name": path.name, "size": len(data), "store": "wecom", "pieces": sent,
                "expires": (datetime.now() + timedelta(days=3)).isoformat(timespec="seconds"),
                "page": "企业微信"}


def _wecom_post(url: str, data: bytes, ctype: str, timeout: int) -> dict:
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("errcode") != 0:
        msg = f"企业微信: {d.get('errcode')} {str(d.get('errmsg'))[:80]}"
        # 60020 = the machine's dial-up IP is not on the app's trusted list; that
        # is the state on 2026-09-12 and only the admin console can change it.
        if d.get("errcode") in _WECOM_PERMANENT:
            raise PermanentUploadError(msg)
        raise RuntimeError(msg)
    return d


class WeComBotFiles:
    """The same, through the group robot's webhook: no trusted-IP list, so it
    works from the dial-up line when the app API answers 60020. The file lands
    in the group he reads; nothing fetches it back by script (webhook media
    has no download API), so this is for his eyes, and the local copy stays
    under state/evidence/.
    """

    LIMIT = 19 * 1024 * 1024

    def __init__(self, webhook: str):
        self.webhook = webhook
        q = urllib.parse.parse_qs(urllib.parse.urlparse(webhook).query)
        self.key = (q.get("key") or [""])[0]

    def upload(self, path: Path, timeout: int = 600) -> dict:
        data = path.read_bytes()
        sent = []
        for name, chunk in split_pieces(path.name, data, self.LIMIT):
            boundary = "----ark" + uuid.uuid4().hex
            body = b"".join([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="media"; filename="{name}"\r\n'.encode(),
                b"Content-Type: application/octet-stream\r\n\r\n", chunk, f"\r\n--{boundary}--\r\n".encode()])
            d = _wecom_post(f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={self.key}&type=file",
                            body, f"multipart/form-data; boundary={boundary}", timeout)
            mid = d["media_id"]
            _wecom_post(self.webhook, json.dumps({"msgtype": "file", "file": {"media_id": mid}}).encode(),
                        "application/json", 60)
            sent.append({"name": name, "media_id": mid, "size": len(chunk)})
        return {"name": path.name, "size": len(data), "store": "wecom-bot", "pieces": sent, "page": "企业微信群"}


def split_pieces(name: str, data: bytes, limit: int) -> "list[tuple[str, bytes]]":
    """[(piece name, bytes)]: the file itself when it fits, else numbered pieces
    `<name>.p01of03` that concatenate back to the original."""
    if len(data) <= limit:
        return [(name, data)]
    n = (len(data) + limit - 1) // limit
    return [(f"{name}.p{i + 1:02d}of{n:02d}", data[i * limit:(i + 1) * limit]) for i in range(n)]


def pick_uploader(cfg, run_id: str = ""):
    """The first store in `uploaders(cfg)`; kept for callers that want one."""
    return uploaders(cfg, run_id)[0]


def uploaders(cfg, run_id: str = "") -> list:
    """Every configured store, best first: COS, the WeCom app, the WeCom group
    robot, gofile. `save_and_upload` walks down the list when one refuses."""
    out: list = []
    if all(getattr(cfg, k, "") for k in ("cos_secret_id", "cos_secret_key", "cos_bucket", "cos_region")):
        out.append(Cos(cfg.cos_secret_id, cfg.cos_secret_key, cfg.cos_bucket, cfg.cos_region,
                       prefix=run_id.replace("/", "_")))
    if getattr(cfg, "wecom_corpid", "") and getattr(cfg, "wecom_secret", "") and getattr(cfg, "wecom_agentid", ""):
        out.append(WeComFiles(cfg))
    if getattr(cfg, "wecom_bot_url", ""):
        out.append(WeComBotFiles(cfg.wecom_bot_url))
    out.append(Gofile(Path(cfg.state_dir)))
    return out


# ------------------------------------------------------------------ driver

def bundle_for(script: str, cfg, out_dir: Path) -> list[Path]:
    """The right export for a script, from the directories the relay already knows."""
    if script == "MaaEnd" and cfg.maaend_dir:
        version = "unknown"
        try:
            version = json.loads((Path(cfg.maaend_dir) / "interface.json").read_text(encoding="utf-8")).get("version", version)
        except (OSError, ValueError):
            pass
        return bundle_maaend(Path(cfg.maaend_dir), out_dir, version)
    if script == "MAA" and cfg.maa_dir:
        return bundle_maa(Path(cfg.maa_dir), out_dir)
    if script == "OK-WW" and cfg.okww_dir:
        return bundle_okww(Path(cfg.okww_dir) / "data" / "apps" / "ok-ww" / "working", out_dir)
    return []


def save_and_upload(cfg, script: str, run_id: str, extra: list[Path] = (), *, uploader=None) -> dict:
    """Build the bundle into state/evidence/<run_id>/bundle, upload it, append to the index. Never raises."""
    state_dir = Path(cfg.state_dir)
    dst = state_dir / "evidence" / run_id.replace("/", "_") / "bundle"
    result: dict = {"script": script, "run_id": run_id, "when": datetime.now().isoformat(timespec="seconds"),
                    "files": [], "uploaded": [], "errors": []}
    try:
        paths = bundle_for(script, cfg, dst)
        for p in extra:
            try:
                shutil.copy2(p, dst / p.name)
                paths.append(dst / p.name)
            except OSError as exc:
                result["errors"].append(f"copy {p.name}: {exc}")
        result["files"] = [p.name for p in paths]
    except Exception as exc:  # evidence must never block bookkeeping
        log.exception("证据包打不出来")
        result["errors"].append(f"bundle: {type(exc).__name__}: {exc}")
        paths = []
    stores = [uploader] if uploader else uploaders(cfg, run_id)
    dead: set[int] = set()          # stores that refused permanently this round
    for p in paths:
        ok = False
        for i, up in enumerate(stores):
            if i in dead:
                continue
            # gofile answered 500 to the very first 24 MB upload on 2026-09-12 and
            # took the next one fine; three tries with a pause cover that. A
            # permanent refusal (wrong key, IP not allowed) skips the tries and
            # the store.
            for attempt in range(1, 4):
                try:
                    result["uploaded"].append(up.upload(p))
                    ok = True
                    break
                except PermanentUploadError as exc:
                    log.warning("证据上传被拒 %s（%s，换下一条路）: %s", p.name, type(up).__name__, exc)
                    result["errors"].append(f"{type(up).__name__} {p.name}: {exc}")
                    dead.add(i)
                    break
                except Exception as exc:  # noqa: BLE001 - one failed upload must not lose the rest
                    log.warning("证据上传失败 %s（%s 第 %d 次）: %s", p.name, type(up).__name__, attempt, exc)
                    if attempt == 3:
                        result["errors"].append(f"{type(up).__name__} {p.name}: {type(exc).__name__}: {exc}")
                    else:
                        time.sleep(15 * attempt)
            if ok:
                break
    if result["uploaded"]:
        result["page"] = result["uploaded"][0].get("page", "")
        result["store"] = result["uploaded"][0].get("store", "gofile")
    idx = state_dir / "evidence" / "index.jsonl"
    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


def prune(state_dir: Path, days: int = 30) -> int:
    """Delete local evidence folders older than `days`. Returns how many went."""
    root = state_dir / "evidence"
    if not root.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    n = 0
    for d in root.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n

