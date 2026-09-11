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

Where it goes: gofile.io, an anonymous free host reachable from the machine
(GitHub, R2 and pixeldrain are not; measured 2026-09-12). A guest account is
created on first upload and its token kept in the state dir, so every bundle
lands in one folder the Mac can list. Guest files are kept ten days after
their last access - long enough to read them while the machine is off, not an
archive. The local copy under `state/evidence/` stays for thirty days.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
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
    up = uploader or Gofile(state_dir)
    for p in paths:
        # gofile answered 500 to the very first 24 MB upload on 2026-09-12 and
        # took the next one fine; three tries with a pause cover that.
        for attempt in range(1, 4):
            try:
                result["uploaded"].append(up.upload(p))
                break
            except Exception as exc:  # noqa: BLE001 - one failed upload must not lose the rest
                log.warning("证据上传失败 %s（第 %d 次）: %s", p.name, attempt, exc)
                if attempt == 3:
                    result["errors"].append(f"upload {p.name}: {type(exc).__name__}: {exc}")
                else:
                    time.sleep(15 * attempt)
    if result["uploaded"]:
        result["page"] = result["uploaded"][0].get("page", "")
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

