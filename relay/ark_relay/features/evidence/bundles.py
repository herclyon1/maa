"""Evidence bundles in the layout each upstream project's own log export uses,
always limited to a time window (`window=(t0, t1)`, epoch seconds).

* MaaEnd: MXU `src-tauri/src/commands/file_ops.rs::export_logs_blocking`.
* MAA: `IssueReportUserControlModel.GenerateSupportPayload`.
* OK-WW: ok-script `ok/ui/qt/start/StartTab.py::export_logs`.

The upstream functions are pinned in sources.py.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path


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


def maaend_entries(maaend_dir: Path, window: "tuple[float, float]",
                   max_images: "int | None" = MAAEND_MAX_IMAGES) -> list[tuple[Path, str]]:
    """The export's file list in MXU's order, limited to `window` (epoch seconds).

    Only files modified inside the window are taken - the config always - and
    the screenshots are capped at `max_images` after dropping duplicates. The
    order and the volume rules are MXU's; the selection is ours. A test checks
    the order against a real export with a window covering the whole tree.
    """
    require_window(window)
    debug = maaend_dir / "debug"
    if not debug.is_dir():
        return []
    regular: list[tuple[Path, str]] = []
    for p in sorted(debug.glob("*"), key=lambda q: q.name):
        if p.is_file() and p.suffix.lower() in (".log", ".dmp") and _in_window(p, window):
            regular.append((p, p.name))
    regular += _walk_sorted(maaend_dir / "config", "config")
    for sub in sorted(q for q in debug.iterdir() if q.is_dir()):
        regular += [(p, n) for p, n in _walk_sorted(sub, sub.name)
                    if p.suffix.lower() in (".log", ".json", ".dmp") and _in_window(p, window)]
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
    paths = []
    for i, vol in enumerate(_volumes(entries, MAAEND_MAX_VOLUME), 1):
        paths.append(_write_zip(out_dir / f"{base}-part{i:0{width}d}.zip", vol))
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
