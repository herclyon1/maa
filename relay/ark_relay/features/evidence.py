"""The relay's relay.log and AUTO-MAS's debug/app.log, cut to an evidence
window, so a bundle carries what both programs wrote around the run.
"""
from __future__ import annotations

import re
import hashlib
import urllib.error
import urllib.request
import json
import time
import urllib.parse
import uuid
import shutil
import zipfile
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from ark_relay.core.config import atomic_write_text, SERVER_TZ, atomic_write_bytes
from dataclasses import dataclass
from ark_relay.core.statestore import tail_bytes

# A line stamp: `[YYYY-MM-DD HH:MM:SS` / `YYYY-MM-DDTHH:MM:SS` (AUTO-MAS) or
# `MM-DD HH:MM:SS` (relay.log, no year).
_CTX_TS = re.compile(r"^(?:\[)?(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)"
                     r"|^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)")

# Two more stamps MaaEnd's debug/ logs use, read only when a caller asks for
# them (`more=True`, the MaaEnd bundle): mxu-tauri.log `[YYYY-MM-DD][HH:MM:SS]`
# and go-service.log's JSON lines `{..."time":"YYYY-MM-DDTHH:MM:SS+08:00"...}`.
# Local time like the others: the machine's clock is +08:00.
_MORE_TS = re.compile(r'^\[(\d{4})-(\d\d)-(\d\d)\]\[(\d\d):(\d\d):(\d\d)\]'
                      r'|^\{.*?"time":"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)')


def _line_ts(line: str, year: int, more: bool = False) -> "float | None":
    m = _CTX_TS.match(line)
    if not m and more and (mm := _MORE_TS.match(line)):
        g = mm.groups()
        try:
            return datetime(*(int(x) for x in (g[:6] if g[0] else g[6:]))).timestamp()
        except ValueError:
            return None
    if not m:
        return None
    if m.group(1):
        y, mo, d, h, mi, sec = (int(x) for x in m.groups()[:6])
    else:
        y = year
        mo, d, h, mi, sec = (int(x) for x in m.groups()[6:])
    try:
        return datetime(y, mo, d, h, mi, sec).timestamp()
    except ValueError:
        return None


def slice_log(src: Path, window: "tuple[float, float]", dst: Path, tail_bytes: "int | None" = 50_000_000,
              *, more: bool = False) -> "Path | None":
    """Copy the lines of `src` stamped inside `window` into `dst`; continuation
    lines (tracebacks) follow their stamped line. The relay log stamps MM-DD
    without a year, AUTO-MAS's app.log stamps the full date. None when nothing
    fell in the window or the file cannot be read.

    `tail_bytes=None` reads the whole file line by line (a MaaEnd log of 60 MB
    is not held in memory) and does not reach into `<src>.1`; `more` also reads
    the MaaEnd stamps in _MORE_TS."""
    year = datetime.fromtimestamp(window[0]).year
    # A window across New Year: a yearless 01-01 stamp dated in the start's
    # year falls eleven months before the window; date it in the end's year.
    year_end = datetime.fromtimestamp(window[1]).year
    keep = False
    n = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if tail_bytes is None:
            lines = _file_lines(src)
        else:
            from ark_relay.core.statestore import tail_bytes as _tail  # noqa: PLC0415
            # Reaches into <src>.1 when a rotation moved part of the window there (logfile.py).
            lines = iter(_tail(src, tail_bytes)[0].decode("utf-8", errors="replace").splitlines())
        picked: list[str] = []
        for line in lines:
            ts = _line_ts(line, year, more)
            if ts is not None and ts < window[0] and year_end != year:
                ts = _line_ts(line, year_end, more)
            if ts is not None:
                keep = window[0] <= ts <= window[1]
            if keep:
                picked.append(line + "\n")
                n += 1
        atomic_write_text(dst, "".join(picked))
    except OSError:
        dst.unlink(missing_ok=True)
        return None
    if not n:
        dst.unlink(missing_ok=True)
        return None
    return dst


def _file_lines(src: Path):
    with src.open("rb") as f:
        for raw in f:
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")


def first_ts(src: Path, more: bool = False, head_bytes: int = 65536) -> "float | None":
    """The stamp of the first stamped line in the first `head_bytes` of `src`
    (the year of a yearless stamp is taken from the file's mtime); None when
    none is readable there."""
    try:
        with src.open("rb") as f:
            head = f.read(head_bytes)
        year = datetime.fromtimestamp(src.stat().st_mtime).year
    except OSError:
        return None
    for line in head.decode("utf-8", errors="replace").splitlines():
        if (ts := _line_ts(line, year, more)) is not None:
            return ts
    return None


def context_files(cfg, window: "tuple[float, float]", out_dir: Path, *,
                  relay_until: "float | None" = None) -> list[Path]:
    """The relay's relay.log and AUTO-MAS's debug/app.log, cut to the window.

    `relay_until` stretches the relay.log slice to that moment. The relay
    handles a run only once AUTO-MAS writes its record at the end of the whole
    script, so what the relay did about the run lies after the run's own
    window. The handler passes the moment it cuts; a hand-run export leaves it
    out.
    """
    import os  # noqa: PLC0415
    out: list[Path] = []
    relay_log = os.environ.get("ARK_LOG_FILE", "")
    if relay_log:
        rwin = (window[0], max(window[1], relay_until)) if relay_until else window
        if p := slice_log(Path(relay_log), rwin, out_dir / "relay.log"):
            out.append(p)
    automas = getattr(cfg, "automas_dir", None)
    if automas:
        if p := slice_log(Path(automas) / "debug" / "app.log", window, out_dir / "automas-app.log"):
            out.append(p)
    return out


@dataclass(frozen=True)
class Pin:
    name: str
    repo: str
    branch: str
    path: str
    commit: str
    sha256: str
    # The functions whose bodies are what this relay mirrors. Only their text is
    # hashed, so a change elsewhere in the upstream file does not count.
    regions: tuple[str, ...] = ()


_HEADER = {
    ".cs": r"^\s*(?:public|private|internal|protected|static|async|override|virtual|sealed|\s)*[\w<>\[\]?]+\s+{name}\s*(?:<[^>]*>)?\s*\(",
    ".rs": r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+{name}\b",
    ".py": r"^\s*def\s+{name}\s*\(",
}


def region_text(raw: str, path: str, names: tuple[str, ...]) -> str:
    """The bodies of `names` in `raw`, joined, in the given order.

    Brace languages: from the header to the brace that closes the one opened after
    it. Python: from the header to the last line indented deeper than it. A name
    that is not found contributes the marker `<missing NAME>`, so a renamed function
    changes the hash instead of silently shrinking the pinned text.
    """
    ext = path[path.rfind("."):]
    lines = raw.splitlines()
    out = []
    for name in names:
        pat = re.compile(_HEADER[ext].format(name=re.escape(name)))
        start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
        if start is None:
            out.append(f"<missing {name}>")
            continue
        if ext == ".py":
            indent = len(lines[start]) - len(lines[start].lstrip())
            end = start
            for i in range(start + 1, len(lines)):
                ln = lines[i]
                if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
                    break
                end = i
            out.append("\n".join(lines[start:end + 1]))
            continue
        depth, seen, end = 0, False, start
        for i in range(start, len(lines)):
            for ch in lines[i]:
                if ch == "{":
                    depth += 1; seen = True
                elif ch == "}":
                    depth -= 1
            if seen and depth == 0:
                end = i
                break
        out.append("\n".join(lines[start:end + 1]))
    return "\n\n".join(out)


def pinned_text(pin: "Pin", raw: bytes) -> bytes:
    """What gets hashed for `pin`: the named regions when it has any, else the file."""
    if not pin.regions:
        return raw
    return region_text(raw.decode("utf-8", "replace"), pin.path, pin.regions).encode("utf-8")


PINS = (
    Pin("MaaEnd 导出（MXU file_ops.rs）", "MistEO/MXU", "main",
        "src-tauri/src/commands/file_ops.rs",
        "316ac0f6fb0ba7dd1187f8667c4a50b1b159db35",
        "1573c2683360d9056d3eb39ca7fdaae4afe1e822134cdb00ca264fa4f0cff849",
        ("export_logs_blocking", "collect_files_recursively", "collect_debug_subdir_files",
         "add_file_to_zip", "normalize_archive_path", "is_image_file", "has_extension",
         "estimate_compressed_upper_bound", "pre_compress_measure")),
    Pin("MAA 生成日志压缩包（IssueReportUserControlModel.cs）",
        "MaaAssistantArknights/MaaAssistantArknights", "dev-v2",
        "src/MaaWpfGui/ViewModels/UserControl/Settings/IssueReportUserControlModel.cs",
        # GenerateSupportPayload is `public async Task`: the C# header pattern in
        # _HEADER accepts `async` for it.
        "53870a7a5214c04ae25abd5a02f0bcfb8ad99507",
        "c392771bccda4f98eb1caa22404d37491c8c8c8414e94e001198c6357c2dafaa",
        ("GenerateSupportPayload", "CopyDirectoryIfExists")),
    Pin("OK-WW Export Logs（ok-script diagnostics.py）", "ok-oldking/ok-script", "master",
        "ok/ui/qt/shell/diagnostics.py",
        "f90444e11713496bd41de389a886501673531bad",
        "d43f0e28ce473e881945ede50ee7aaa8a9c73bcbc3ff4a9e788189b24804230c",
        ("export_logs",)),
)


JSDELIVR = "https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}"


def check_sources(fetch=None, timeout: int = 30) -> tuple[list[str], list[str]]:
    """(changed pin names, unreachable pin names) against the upstream default branches."""
    def _get(url: str) -> bytes:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    fetch = fetch or _get
    changed, unreachable = [], []
    LAST_SEEN.clear()
    LAST_ERRORS.clear()
    for pin in PINS:
        try:
            raw = fetch(JSDELIVR.format(repo=pin.repo, branch=pin.branch, path=pin.path))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            unreachable.append(pin.name)
            LAST_ERRORS[pin.name] = f"{type(exc).__name__}: {getattr(exc, 'reason', None) or exc}"
            continue
        seen = hashlib.sha256(pinned_text(pin, raw)).hexdigest()
        LAST_SEEN[pin.name] = seen
        if seen != pin.sha256:
            changed.append(pin.name)
    return changed, unreachable


# Fingerprint of each pin as last fetched by check_sources(), so the boot stage
# can tell "the same change as yesterday" from a new one.
LAST_SEEN: dict[str, str] = {}

LAST_ERRORS: dict[str, str] = {}


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
            from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
            atomic_write_text(self.cred, json.dumps({"token": self.token, "folder": self.folder}))
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

    PAGE_TTL_S = 31 * 86400

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
        """'' when the bucket accepts this key; otherwise the reason it never will.

        Only a refusal (_REFUSED) or a missing setting is such a reason. A connection that
        fails is raised: the caller's tries (evidence.save_and_upload, three with a pause)
        probe again before any PUT, so a big file is still never sent into a dead
        connection. Until 11-08 any connection failure here (WinError 10053 is also how an
        account in arrears can answer) was a refusal for the round, and one dropped HEAD
        lost that round's evidence (audit 11-08 C-18).
        """
        if not (self.sid and self.skey and self.bucket and self.region):
            return "COS 设置不全（.env 里缺 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION）"
        req = urllib.request.Request(f"https://{self.host}/", method="HEAD",
                                     headers={"Authorization": self.authorization("HEAD", "")})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read()
        except urllib.error.HTTPError as exc:
            if exc.code in self._REFUSED:
                return f"COS 回了 {exc.code}：{self._REFUSED[exc.code]}"
        return ""

    def size(self, key: str, timeout: int = 20) -> "int | None":
        """The bytes of the object `key` as the bucket holds it (HEAD, Content-Length);
        None when there is no such object (404). Any other answer is raised."""
        url = f"https://{self.host}/" + urllib.parse.quote(key, safe="/")
        req = urllib.request.Request(url, method="HEAD", headers={"Authorization": self.authorization("HEAD", key)})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return int(r.headers.get("Content-Length") or 0)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

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


def require_window(window) -> None:
    """Every bundle is cut by a time window; None is a caller's mistake."""
    if window is None:
        raise ValueError("evidence bundle needs a time window")


def _write_zip(zp: Path, entries, compression: int = zipfile.ZIP_DEFLATED) -> Path:
    """Write `entries` ((file, name in the archive) pairs) into the archive `zp`."""
    with zipfile.ZipFile(zp, "w", compression) as zf:
        for p, name in entries:
            zf.write(p, name)
    return zp


# ------------------------------------------------------ MaaEnd (MXU export)
# Mirrors export_logs_blocking: regular files first (debug/*.log|*.dmp sorted by
# name, then config/** recursively, then debug/<subdir>/**.{log,json,dmp}
# keeping the subfolder), then on_error and vision images newest first, split
# into volumes of at most MAAEND_MAX_VOLUME bytes, part numbers zero-padded to 2
# digits (3 when there are 100+ entries), named
# `<project>-logs-<version>-<YYYYmmdd-HHMMSS>-partNN.zip`.
MAAEND_MAX_VOLUME = 24_500_000


_IMAGE_EXT = (".png", ".jpg", ".jpeg")


# How many error screenshots one run's bundle carries at most (newest first,
# duplicates dropped). A 1280x720 PNG from MaaEnd is about 1 MB and cannot be
# recompressed here (no image library on the machine; the relay has no
# dependencies), so the count is the lever.
MAAEND_MAX_IMAGES = 12


def _in_window(p: Path, window: "tuple[float, float] | None") -> bool:
    if window is None:
        return True
    try:
        return window[0] <= p.stat().st_mtime <= window[1]
    except OSError:
        return False


def _log_in_window(p: Path, window: "tuple[float, float]") -> bool:
    """A MaaEnd .log that holds part of the window."""
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return False
    if mtime < window[0]:
        return False
    if mtime <= window[1]:
        return True
    head = first_ts(p, more=True)
    return head is None or head <= window[1]


def _crosses_window(p: Path, window: "tuple[float, float]") -> bool:
    """A log that also holds lines outside the window: worth cutting to it."""
    try:
        if p.stat().st_mtime > window[1]:
            return True
    except OSError:
        return False
    head = first_ts(p, more=True)
    return head is not None and head < window[0]


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


def _dedup(paths: list[Path]) -> list[Path]:
    """Drop images whose bytes were already seen (retries save the same screen again)."""
    seen: set[str] = set()
    out = []
    for p in paths:
        try:
            h = hashlib.sha1(p.read_bytes()).hexdigest()
        except OSError:
            continue
        if h in seen:
            continue
        seen.add(h)
        out.append(p)
    return out


def _maaend_keep(p: Path, window: "tuple[float, float]") -> bool:
    return _log_in_window(p, window) if p.suffix.lower() == ".log" else _in_window(p, window)


def _cut_to_window(entries: list[tuple[Path, str]], window: "tuple[float, float]",
                   slice_dir: Path) -> list[tuple[Path, str]]:
    """Each .log that runs past either end of the window replaced by its lines
    inside it (slice_log, written under `slice_dir`); a log whose stamps cannot
    be read, or that has none inside, goes in whole."""
    out = []
    for p, name in entries:
        if p.suffix.lower() == ".log" and _crosses_window(p, window):
            if cut := slice_log(p, window, slice_dir / name, tail_bytes=None, more=True):
                out.append((cut, name))
                continue
        out.append((p, name))
    return out


def maaend_entries(maaend_dir: Path, window: "tuple[float, float]",
                   max_images: "int | None" = MAAEND_MAX_IMAGES) -> list[tuple[Path, str]]:
    """The export's file list in MXU's order, limited to `window` (epoch seconds).

    Only files modified inside the window are taken - the config always, and
    a .log that was still being written at t1 (_log_in_window) - and the
    screenshots are capped at `max_images` after dropping duplicates. The
    order and the volume rules are MXU's; the selection is ours. A test checks
    the order against a real export with a window covering the whole tree.
    """
    require_window(window)
    debug = maaend_dir / "debug"
    if not debug.is_dir():
        return []
    regular: list[tuple[Path, str]] = []
    for p in sorted(debug.glob("*"), key=lambda q: q.name):
        if p.is_file() and p.suffix.lower() in (".log", ".dmp") and _maaend_keep(p, window):
            regular.append((p, p.name))
    regular += _walk_sorted(maaend_dir / "config", "config")
    for sub in sorted(q for q in debug.iterdir() if q.is_dir()):
        regular += [(p, n) for p, n in _walk_sorted(sub, sub.name)
                    if p.suffix.lower() in (".log", ".json", ".dmp") and _maaend_keep(p, window)]
    images: list[tuple[Path, str]] = []
    for name in ("on_error", "vision"):
        d = debug / name
        if d.is_dir():
            files = [p for p in d.rglob("*")
                     if p.is_file() and p.suffix.lower() in _IMAGE_EXT and _in_window(p, window)]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            files = _dedup(files)
            if max_images is not None:
                files = files[:max(0, max_images - len(images))]
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


def bundle_maaend(maaend_dir: Path, out_dir: Path, version: str, window: "tuple[float, float]",
                  stamp: datetime | None = None) -> list[Path]:
    entries = maaend_entries(maaend_dir, window)
    if not entries:
        return []
    stamp = stamp or datetime.now()
    base = f"MaaEnd-logs-{version}-{stamp.strftime('%Y%m%d-%H%M%S')}"
    width = 3 if len(entries) >= 100 else 2
    out_dir.mkdir(parents=True, exist_ok=True)
    # The cut copies live only until the volumes are written.
    slice_dir = out_dir / f"{base}-slices"
    try:
        entries = _cut_to_window(entries, window, slice_dir)
        paths = []
        for i, vol in enumerate(_volumes(entries, MAAEND_MAX_VOLUME), 1):
            paths.append(_write_zip(out_dir / f"{base}-part{i:0{width}d}.zip", vol))
    finally:
        shutil.rmtree(slice_dir, ignore_errors=True)
    return paths


# ----------------------------------------------------------- MAA (report)
# Mirrors GenerateSupportPayload: part01 = config/** + resource/*_custom.* +
# cache/** + debug root files; part02.. = debug subfolder files newer than three
# days, 20 MB per part. Upstream also writes a report_<stamp>.zip of everything;
# this mirror does not.
MAA_PART = 20 * 1024 * 1024


def bundle_maa(maa_dir: Path, out_dir: Path, window: "tuple[float, float]",
               stamp: datetime | None = None) -> list[Path]:
    require_window(window)
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
    # Upstream takes the debug subfolders of the last three days; the window
    # takes their place.
    sub = [(p, n) for p, n in _walk_sorted(debug, "debug")
           if p.parent != debug and _in_window(p, window) and not p.name.lower().startswith("report")]
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    if part01:
        paths.append(_write_zip(out_dir / f"{base}_part01.zip", part01))
    for i, vol in enumerate(_volumes(sub, MAA_PART), 2):
        paths.append(_write_zip(out_dir / f"{base}_part{i:02d}.zip", vol))
    return paths


# ---------------------------------------------------------- OK-WW (export)
# Mirrors StartTab.export_logs: every file under <working>/screenshots and
# <working>/logs, paths relative to the working dir, one zip named
# `<gui_title>-log.zip`.
def bundle_okww(working_dir: Path, out_dir: Path, window: "tuple[float, float]",
                gui_title: str = "ok-ww") -> list[Path]:
    require_window(window)
    out_dir.mkdir(parents=True, exist_ok=True)
    zp = out_dir / f"{gui_title}-log.zip"
    n = 0
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in ("screenshots", "logs"):
            d = working_dir / folder
            if not d.is_dir():
                continue
            for p in sorted(d.rglob("*")):
                if p.is_file() and _in_window(p, window):
                    zf.write(p, p.relative_to(working_dir).as_posix())
                    n += 1
    if n == 0:
        zp.unlink(missing_ok=True)
        return []
    return [zp]


def bundle_for(script: str, cfg, out_dir: Path, window: "tuple[float, float]") -> list[Path]:
    """The right export for a script, from the directories the relay already knows, limited to `window`."""
    require_window(window)
    if script == "MaaEnd" and cfg.maaend_dir:
        version = "unknown"
        try:
            version = json.loads((Path(cfg.maaend_dir) / "interface.json").read_text(encoding="utf-8")).get("version", version)
        except (OSError, ValueError):
            pass
        return bundle_maaend(Path(cfg.maaend_dir), out_dir, version, window)
    if script == "MAA" and cfg.maa_dir:
        return bundle_maa(Path(cfg.maa_dir), out_dir, window)
    if script == "OK-WW" and cfg.okww_dir:
        return bundle_okww(Path(cfg.okww_dir) / "data" / "apps" / "ok-ww" / "working", out_dir, window)
    return []


def pack_one(out: Path, paths: list[Path]) -> Path:
    """All of a run's evidence files into one archive, stored (not re-compressed)."""
    return _write_zip(out, [(p, p.name) for p in paths], zipfile.ZIP_STORED)


# This module's public names plus every name re-exported from the modules above
# (callers and tests say evidence.<name>); pyflakes and ruff count a listed name as used.

log = logging.getLogger("ark.evidence")

# A run's window is widened by this on both ends: MaaEnd's last lines land after
# AUTO-MAS has recorded the run, and the framework log rotates a little before.
WINDOW_SLACK = 300


# ------------------------------------------------- WeCom stores (not in uploaders())
# WeCom error codes a retry cannot change.
_WECOM_PERMANENT = {40001, 40013, 40014, 41001, 42001, 60020, 60011, 81013, 93000}


class WeComFiles:
    """Evidence as WeCom file messages to the same person the relay already pushes to.

    WeCom caps a file at 20 MB and keeps uploaded media for three days. The
    message reaches his phone the moment it is sent, so the evidence is readable
    with the machine off; the media id in the index lets the Mac fetch the bytes
    back within the three days. Bigger archives are refused here and go to the
    next store - never cut into pieces.
    """

    LIMIT = 20 * 1024 * 1024

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
        # One file per run, never cut into pieces: over WeCom's cap the file goes
        # to the next store instead.
        if len(data) > self.LIMIT:
            raise PermanentUploadError(f"企业微信文件上限 20 MB，这份 {len(data) // 1_000_000} MB")
        mid = self._upload_piece(path.name, data, timeout)
        self._send_file(mid)
        return {"name": path.name, "size": len(data), "store": "wecom", "media_id": mid,
                "expires": (datetime.now() + timedelta(days=3)).isoformat(timespec="seconds"),
                "page": "企业微信"}


def _wecom_post(url: str, data: bytes, ctype: str, timeout: int) -> dict:
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("errcode") != 0:
        msg = f"企业微信: {d.get('errcode')} {str(d.get('errmsg'))[:80]}"
        # 60020 = the machine's dial-up IP is not on the app's trusted list; only
        # the WeCom admin console can change that.
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

    LIMIT = 20 * 1024 * 1024

    def __init__(self, webhook: str):
        self.webhook = webhook
        q = urllib.parse.parse_qs(urllib.parse.urlparse(webhook).query)
        self.key = (q.get("key") or [""])[0]

    def upload(self, path: Path, timeout: int = 600) -> dict:
        data = path.read_bytes()
        if len(data) > self.LIMIT:
            raise PermanentUploadError(f"企业微信文件上限 20 MB，这份 {len(data) // 1_000_000} MB")
        boundary = "----ark" + uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="media"; filename="{path.name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n", data, f"\r\n--{boundary}--\r\n".encode()])
        d = _wecom_post(f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={self.key}&type=file",
                        body, f"multipart/form-data; boundary={boundary}", timeout)
        mid = d["media_id"]
        _wecom_post(self.webhook, json.dumps({"msgtype": "file", "file": {"media_id": mid}}).encode(),
                    "application/json", 60)
        return {"name": path.name, "size": len(data), "store": "wecom-bot", "media_id": mid, "page": "企业微信群"}


def pick_uploader(cfg, run_id: str = ""):
    """The first store in `uploaders(cfg)`, or None when COS is not configured."""
    ups = uploaders(cfg, run_id)
    return ups[0] if ups else None


def uploaders(cfg, run_id: str = "") -> list:
    """The configured stores, best first: COS alone (WeComFiles, WeComBotFiles and
    Gofile are not returned). An empty list means "COS not configured", and
    save_and_upload says so."""
    out: list = []
    if all(getattr(cfg, k, "") for k in ("cos_secret_id", "cos_secret_key", "cos_bucket", "cos_region")):
        out.append(Cos(cfg.cos_secret_id, cfg.cos_secret_key, cfg.cos_bucket, cfg.cos_region,
                       prefix=run_id.replace("/", "_")))
    return out


# ------------------------------------------------------------------ driver


def run_window(started: datetime, finished: "datetime | None") -> tuple[float, float]:
    """One run's window: its start and end widened by WINDOW_SLACK; an unknown end means now."""
    t0 = started.timestamp() - WINDOW_SLACK
    t1 = (finished.timestamp() if finished else time.time()) + WINDOW_SLACK
    return t0, t1


def desktop_shot(cfg, out_dir: Path, screenshot=None, *, name: str = "", move: bool = False,
                 quiet: bool = False) -> "Path | None":
    """A picture of the real desktop, named by the moment it was taken, for an
    OK-WW failure bundle: OK-WW's own export is only its log plus the
    screenshots it chose to save, which can say nothing about the screen. The
    picture is taken when the record lands, which AUTO-MAS writes at the
    end of the whole script run - so it may show the state after a retry; the
    filename says when. None when the desktop cannot be reached (a Mac, a test,
    no interactive session).

    `name` (no extension) replaces the time-stamped default; `move` takes the
    agent's file instead of copying it, so state/desktop/ does not fill up with
    one copy of every picture (task_shots.py takes ~16 a round); `quiet` leaves
    the warning to the caller."""
    try:
        if screenshot is None:
            from ark_relay.core.desktop import Desktop  # noqa: PLC0415 - Windows-only helper
            screenshot = Desktop(Path(cfg.state_dir)).screenshot
        shot = screenshot()
        if not shot:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{name or 'desktop-' + datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        if move:
            shutil.move(str(shot), str(target))
        else:
            shutil.copy2(shot, target)
        return target
    except Exception:  # a missing picture must not cost the bundle
        if quiet:
            log.debug("桌面截图没拿到", exc_info=True)
        else:
            log.warning("桌面截图没拿到，证据包不带它", exc_info=True)
        return None


def save_and_upload(cfg, script: str, run_id: str, extra: list[Path] = (), *,
                    window: "tuple[float, float]", uploader=None, screenshot=None,
                    relay_until: "float | None" = None) -> dict:
    """Build the bundle into state/evidence/<run_id>/bundle, upload it, append to the index. Never raises past the bundle step.

    `relay_until`: see context_files."""
    require_window(window)
    state_dir = Path(cfg.state_dir)
    dst = state_dir / "evidence" / run_id.replace("/", "_") / "bundle"
    result: dict = {"script": script, "run_id": run_id, "when": datetime.now().isoformat(timespec="seconds"),
                    "files": [], "uploaded": [], "errors": []}
    try:
        paths = bundle_for(script, cfg, dst, window)
        # bundle_for makes the folder only when it found files of its own; the
        # extras (AUTO-MAS's record, task pictures) go in even when it did not.
        dst.mkdir(parents=True, exist_ok=True)
        for p in extra:
            try:
                shutil.copy2(p, dst / p.name)
                paths.append(dst / p.name)
            except OSError as exc:
                result["errors"].append(f"copy {p.name}: {exc}")
        for p in context_files(cfg, window, dst, relay_until=relay_until):
            paths.append(p)
        if script == "OK-WW":
            if shot := desktop_shot(cfg, dst, screenshot):
                paths.append(shot)
        result["files"] = [p.name for p in paths]
    except Exception as exc:  # evidence must never block bookkeeping
        log.exception("证据包打不出来")
        result["errors"].append(f"bundle: {type(exc).__name__}: {exc}")
        paths = []
    # One file per run: the upstream export and the
    # AUTO-MAS record go into a single archive, stored uncompressed (the parts
    # inside are already deflated). Unpack it to hand the parts to upstream.
    one: list[Path] = []
    if paths:
        try:
            one = [pack_one(dst.parent / f"{script}-{run_id.replace('/', '_')}.zip", paths)]
        except OSError as exc:
            result["errors"].append(f"pack: {exc}")
    result["archive"] = one[0].name if one else ""
    stores = [uploader] if uploader else uploaders(cfg, run_id)
    if one and not stores:
        result["errors"].append("没有配置 COS（.env 里缺 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION），证据包只留在机器上")
    dead: set[int] = set()          # stores that refused permanently this round
    for p in one:
        ok = False
        for i, up in enumerate(stores):
            if i in dead:
                continue
            # Three tries with a pause between them cover a store's passing
            # error. A permanent refusal (wrong key, IP not allowed) skips the
            # tries and the store.
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
    """Delete local evidence folders older than `days`. Returns how many went.

    `daily/` (error_evidence.py) gets new files every day, which keeps the
    folder's own time fresh: its files are pruned one by one instead (audit
    s17 F4)."""
    root = state_dir / "evidence"
    if not root.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    n = 0
    for d in root.iterdir():
        if d.is_dir() and d.name == "daily":
            gone = 0
            for f in d.iterdir():
                try:
                    if f.is_file() and f.stat().st_mtime < cutoff:
                        f.unlink()
                        gone += 1
                except OSError:
                    continue
            if gone:
                log.info("清掉 %d 个超过 %d 天的每日日志副本", gone, days)
        elif d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


_log_error_evidence = logging.getLogger("ark.error_evidence")

# The COS object folder: daily/relay-YYYY-MM-DD.log, daily/automas-app-YYYY-MM-DD.log.
DAILY_PREFIX = "daily"
# The whole-day log's cap. A day bigger than this uploads only its last part.
DAY_MAX_BYTES = 50 * 1024 * 1024
# At most one upload a minute from the error path (the object overwrites anyway).
THROTTLE_S = 60.0

# The last error-path upload attempt (epoch seconds, the caller's clock). Module
# state so errwatch and shutdown share one throttle; tests pass a fake clock.
_last_attempt = [0.0]
# The OCR cache of the official posters and calendars (banners.image_reader: url ->
# lines with positions), uploaded when it changed, so every poster the relay reads
# is kept as a real sample for the tests (each game version brings a new layout).
OCR_CACHE_MAX_BYTES = 20 * 1024 * 1024
_ocr_sent = [0.0]
# The last upload's {url, truncated}: a push inside the throttle minute still ends
# with the link (the day object is already there and is overwritten, not new).
_last_ok: dict = {}
_last_errors: list = []      # the last real attempt's errors, handed out with a throttled call
# One PUT's socket timeout. Cos.upload defaults to 900 s, which would hold
# a relay-error push (and the power-off) for a quarter of an hour on a stalled line.
UPLOAD_TIMEOUT_S = 60


def _daily_uploader(cfg):
    """The COS store for the day objects, or None when COS is not configured."""
    if all(getattr(cfg, k, "") for k in ("cos_secret_id", "cos_secret_key", "cos_bucket", "cos_region")):
        return Cos(cfg.cos_secret_id, cfg.cos_secret_key, cfg.cos_bucket, cfg.cos_region,
                   prefix=DAILY_PREFIX)
    return None


def _day_tail(src: Path, day_start: datetime, day_end: datetime, max_bytes: int) -> tuple[bytes, bool]:
    """The lines of `src` stamped inside the day, capped to the last `max_bytes`.

    Returns (bytes, truncated). b"" when the file cannot be read or has no line
    in the day. The relay log stamps MM-DD without a year (the day's year is
    passed to _line_ts); AUTO-MAS's app.log stamps the full date.
    """
    try:
        # A day's lines live at the tail; reading twice the cap is enough to
        # catch a day boundary that lands inside the cap. Through tail_bytes, so
        # a rotation earlier today does not cut the morning off (logfile.py).
        raw = tail_bytes(src, max_bytes * 2)[0].decode("utf-8", errors="replace")
    except OSError:
        return b"", False
    year = day_start.year
    keep = False
    out: list[str] = []
    for line in raw.splitlines(keepends=True):
        ts = _line_ts(line, year)
        if ts is not None:
            keep = day_start.timestamp() <= ts <= day_end.timestamp()
        if keep:
            out.append(line)
    data = "".join(out).encode("utf-8")
    truncated = len(data) > max_bytes
    if truncated:
        # A cut right after a newline already starts on a whole line, so nothing is
        # dropped then; otherwise the partial first line is. (relay.log lines end in
        # \r\n on Windows.)
        at_line_start = data[-max_bytes - 1:-max_bytes] == b"\n"
        data = data[-max_bytes:]
        nl = data.find(b"\n")
        if nl > 0 and not at_line_start:
            data = data[nl + 1:]   # drop the partial first line of the cut
    return data, truncated


def upload_daily_logs(cfg, *, force: bool = False, now: "datetime | None" = None,
                      clock=time.time, uploader=None) -> dict:
    """Upload today's relay.log and AUTO-MAS app.log to COS; the same keys are
    overwritten all day.

    Returns {"url", "at", "truncated", "errors", "skipped"}: `url` is the
    relay.log object's URL ("" when there is no relay log), `at` is the moment
    as HH:MM (server clock), `skipped` marks a throttle hit, `errors` the
    reasons an upload did not land. Never raises - an upload problem is reported
    in the result, not thrown at the caller.
    """
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    if not force and clock() - _last_attempt[0] < THROTTLE_S:
        return {"url": _last_ok.get("url", ""), "at": now.strftime("%H:%M"),
                "truncated": bool(_last_ok.get("truncated")), "errors": list(_last_errors),
                "skipped": True}
    up = uploader if uploader is not None else _daily_uploader(cfg)
    result = {"url": "", "at": now.strftime("%H:%M"), "truncated": False,
              "errors": [], "skipped": False}
    if up is None:
        result["errors"].append("没有配置 COS（.env 里缺 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION）")
        _last_attempt[0] = clock()
        _last_errors[:] = result["errors"]
        return result
    day = now.strftime("%Y-%m-%d")
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tmp_dir = Path(cfg.state_dir) / "evidence" / "daily"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for kind, src in _sources(cfg):
        data, truncated = _day_tail(src, day_start, now, DAY_MAX_BYTES)
        if not data:
            continue
        tmp = tmp_dir / f"{kind}-{day}.log"
        try:
            atomic_write_bytes(tmp, data)
            got = up.upload(tmp, timeout=UPLOAD_TIMEOUT_S)
        except PermanentUploadError as exc:
            result["errors"].append(f"{kind}: {exc}")
            break                      # the key/bucket refuses: the app.log would too
        except Exception as exc:       # noqa: BLE001 - a failed upload must not raise
            result["errors"].append(f"{kind}: {type(exc).__name__}: {exc}")
            continue
        if kind == "relay":
            result["url"] = got.get("page") or got.get("url", "")   # signed: the bucket is private
            result["truncated"] = truncated
            _last_ok.update(url=result["url"], truncated=truncated)
    _upload_ocr_samples(cfg, up, tmp_dir, day)
    _last_attempt[0] = clock()
    _last_errors[:] = result["errors"]
    return result


BACKFILL_DAYS = 3
_backfill: dict = {"day": None, "thread": None}
_backfill_lock = threading.Lock()


def _sources(cfg) -> "list[tuple[str, Path]]":
    """(kind, file) of the logs a day object is cut from: relay.log, AUTO-MAS's app.log."""
    srcs: list[tuple[str, Path]] = []
    if relay_log := os.environ.get("ARK_LOG_FILE", ""):
        srcs.append(("relay", Path(relay_log)))
    if automas := getattr(cfg, "automas_dir", None):
        srcs.append(("automas-app", Path(automas) / "debug" / "app.log"))
    return srcs


def backfill_past_days(cfg, *, now: "datetime | None" = None, uploader=None, days: int = BACKFILL_DAYS) -> dict:
    """For each of the `days` days before today: the day's lines still in relay.log and
    app.log, put on COS when that day's object is not there (404) or holds fewer bytes
    than the machine does. An object at least as long as the machine's part is left
    alone, so a larger one is never replaced. Today is the daily upload's, not this.

    Returns {"sent": [(day, kind, bytes on COS before or None, bytes sent)], "kept": n,
    "errors": [...]}. Never raises. Nothing of the error path's throttle or last link
    (_last_attempt, _last_ok, _last_errors) is touched: a relay-error push a moment later
    must still carry today's link, not a past day's.
    """
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    result: dict = {"sent": [], "kept": 0, "errors": []}
    up = uploader if uploader is not None else _daily_uploader(cfg)
    if up is None:
        return result
    tmp_dir = Path(cfg.state_dir) / "evidence" / "daily"
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for back in range(1, days + 1):
        day_start = today - timedelta(days=back)
        day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
        day = day_start.strftime("%Y-%m-%d")
        for kind, src in _sources(cfg):
            data, _truncated = _day_tail(src, day_start, day_end, DAY_MAX_BYTES)
            if not data:
                continue               # the machine holds nothing of that day (it was off, or the log moved on)
            tmp = tmp_dir / f"{kind}-{day}.log"
            try:
                held = up.size(up.object_key(tmp))
                if held is not None and held >= len(data):
                    result["kept"] += 1
                    continue
                tmp_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(tmp, data)
                up.upload(tmp, timeout=UPLOAD_TIMEOUT_S)
            except PermanentUploadError as exc:
                result["errors"].append(f"{day} {kind}: {exc}")
                return result          # the key/bucket refuses: every other object would too
            except Exception as exc:   # noqa: BLE001 - a failed back-fill must not raise
                result["errors"].append(f"{day} {kind}: {type(exc).__name__}: {exc}")
                if not hasattr(exc, "code"):
                    return result      # no answer at all (the line is down): the next object would wait as long
                continue
            result["sent"].append((day, kind, held, len(data)))
    return result


def _run_backfill(cfg, now: datetime) -> None:
    """One back-fill pass and its lines in relay.log. What it sent is an INFO line per
    object; a pass that could not finish is one WARNING (the group hears a day's log is
    still missing on COS), and the next start or midnight looks again."""
    try:
        got = backfill_past_days(cfg, now=now)
    except Exception:  # noqa: BLE001 - belt and braces: a thread must not die without a word
        _log_error_evidence.warning("前几天的中继日志有没有传到云上，这次没查成，下次中继启动或过零点再查", exc_info=True)
        return
    for day, kind, held, sent in got["sent"]:
        _log_error_evidence.info("云上 %s 那天的%s日志%s，已把机器上这一天的 %d 字节补传上去", day[5:],
                 "中继" if kind == "relay" else "调度程序",
                 "没有" if held is None else f"只有 {held} 字节", sent)
    if got["errors"]:
        _log_error_evidence.warning("前几天的日志有 %d 份没补传到云上，下次中继启动或过零点再补：%s",
                    len(got["errors"]), "；".join(got["errors"])[:300])


def backfill_step(cfg, now: "datetime | None" = None, *, start=None) -> bool:
    """The main loop's step (day_roll._DayRoll.check): one back-fill pass on a thread of
    its own, the first time it is called after the relay starts and the first time on
    each new server day. True when one was started. No timer of its own: it rides the
    loop's rounds. `start` replaces the thread in tests."""
    at = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    today = at.strftime("%Y-%m-%d")
    with _backfill_lock:
        if _backfill.get("day") == today:
            return False
        t = _backfill.get("thread")
        if t is not None and t.is_alive():
            return False
        _backfill["day"] = today
        if start is not None:
            start(lambda: _run_backfill(cfg, at))
            return True
        t = _backfill["thread"] = threading.Thread(target=_run_backfill, args=(cfg, at), name="daily-backfill",
                                                   daemon=True)
        t.start()
    return True


def _upload_ocr_samples(cfg, up, tmp_dir: Path, day: str) -> None:
    """Upload the poster OCR cache when it changed since the last upload. A failure
    is only logged: the samples are for the next fix, the push does not wait on them."""
    src = Path(cfg.state_dir) / "desktop" / "image-ocr.json"
    try:
        st = src.stat()
        if not 0 < st.st_size <= OCR_CACHE_MAX_BYTES or st.st_mtime <= _ocr_sent[0]:
            return
        tmp = tmp_dir / f"image-ocr-{day}.json"
        atomic_write_bytes(tmp, src.read_bytes())
        up.upload(tmp, timeout=UPLOAD_TIMEOUT_S)
        _ocr_sent[0] = st.st_mtime
    except FileNotFoundError:
        return
    except Exception:  # noqa: BLE001 - samples must never break the evidence upload
        _log_error_evidence.warning("海报识别结果没传上去", exc_info=True)

__all__ = ['GOFILE', 'Gofile', 'JSDELIVR', 'LAST_ERRORS', 'LAST_SEEN', 'MAAEND_MAX_IMAGES', 'MAAEND_MAX_VOLUME', 'MAA_PART', 'PINS', 'Pin', 'WINDOW_SLACK', 'WeComBotFiles', 'WeComFiles', 'ZIP_CENTRAL_DIR_FIXED_BYTES', 'ZIP_EOCD_BYTES', 'ZIP_LOCAL_HEADER_OVERHEAD', '_CTX_TS', '_HEADER', '_IMAGE_EXT', '_TEXT_EXT', '_dedup', '_estimate_compressed', '_in_window', '_line_ts', '_measure_compressed', '_volumes', '_walk_sorted', 'bundle_maa', 'bundle_maaend', 'bundle_okww', 'check_sources', 'desktop_shot', 'log', 'maaend_entries', 'pick_uploader', 'pinned_text', 'prune', 'region_text', 'run_window', 'save_and_upload', 'slice_log', 'uploaders']
