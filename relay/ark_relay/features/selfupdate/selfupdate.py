"""The relay updates its own code at boot.

Doors, in order:

1. The COS bucket evidence bundles go to (evidence.Cos, signed GET). The deploy
   script writes relay/latest.json ({"version": N, "uploaded": ...}) and, under
   relay/<N>/, the manifest and bundle.zip holding every file. COS has no cache layer.
2. Only when SELFUPDATE_GITHUB_FALLBACK=1 (off by default, GITHUB_FALLBACK_ENV): the
   repo through three jsDelivr mirrors and raw.githubusercontent (_alternates). The
   manifest is read from `main`, the files from the manifest's own tag
   `relay-<version>` (_pinned_base).

When COS answers and its latest version is not newer than the local one, the round
ends there: every deploy writes COS last, so GitHub cannot be ahead of it. When COS
cannot be used and the fallback is off, the round is recorded as failed,
reported at the next boot, and that boot tries again.

The manifest lists every file with its hash: the `sha256` map (SHA-256) and `files`
(SHA-1, for machines whose code reads only `files`). A file is fetched only when its
local copy differs, and every fetched file is checked against the manifest.

All or nothing: every changed file is downloaded and verified first (_stage_files),
written to a staging directory, then swapped in (_write_staged); a failed swap puts
back the files already swapped.

This module never reloads code into the running process. check() returns the files
that landed; boot_stages._stage_selfupdate restarts the relay as a fresh process
when that list is not empty.

Trust: whoever can push to the repo or write to the bucket can run code on this
machine. Both are the user's own; the transport is HTTPS.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import re
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from ark_relay.core.config import SERVER_TZ, atomic_write_bytes

log = logging.getLogger("ark.selfupdate")

DEFAULT_BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
MANIFEST = "manifest.json"
# Wall-clock budget for one whole round. The relay boots 8 minutes before the
# evening queue (21:22 / 21:30) and 13 before the morning one (08:47 / 09:00).
# When the budget runs out the round gives up; the next boot tries again.
BUDGET_SECONDS = 240
# Per-attempt timeout for raw.githubusercontent, the only door with no CDN cache.
# Measured from the machine, a successful fetch from it averaged 38 s; 45 leaves
# headroom, and BUDGET_SECONDS still caps the round.
RAW_TIMEOUT = 45


# How many files are fetched at once from the GitHub doors.
PARALLEL_FETCHES = 6
# The GitHub doors are used only when the machine's .env sets this to 1
# (docs/OPERATIONS.md). Off by default since 2026-09-18 (the user's decision).
# relay.log from 08-16 to 09-18, 521 rounds: raw.githubusercontent failed the
# manifest fetch 206 times; the jsDelivr mirrors served a stale copy of a file
# 29 times across the 33 rounds that needed files.
GITHUB_FALLBACK_ENV = "SELFUPDATE_GITHUB_FALLBACK"
COS_PREFIX = "relay"
COS_LATEST = "latest.json"
COS_BUNDLE = "bundle.zip"
COS_TIMEOUT = 20


def github_fallback() -> bool:
    """Whether the GitHub doors may be asked at all this round."""
    return os.environ.get(GITHUB_FALLBACK_ENV, "").strip() == "1"


def _cos():
    """The evidence bucket's client, or None when COS is not configured on this machine."""
    from ark_relay.features.evidence import evidence  # noqa: PLC0415
    keys = [os.environ.get(k, "") for k in ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION")]
    if not all(keys):
        return None
    return evidence.Cos(*keys, prefix=COS_PREFIX)


def _cos_get(cos, key: str, timeout: int = COS_TIMEOUT) -> bytes | None:
    """One signed GET. None for anything that is not a body: a missing object
    (the lifecycle rule, or a version never uploaded), a refused key, a dead
    link. The caller falls back; nothing here is worth an alarm."""
    import urllib.parse  # noqa: PLC0415
    full = f"{cos.prefix}/{key}"
    url = f"https://{cos.host}/" + urllib.parse.quote(full, safe="/")
    req = urllib.request.Request(url, headers={"Authorization": cos.authorization("GET", full),
                                               "User-Agent": "ark-relay"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        log.info("COS 没有 %s（%s）", key, exc.code)
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
        log.warning("取不到 COS 的 %s: %s", key, exc)
    return None


def _cos_manifest(cos, local_ver: int) -> tuple[dict | None, int] | None:
    """What COS says about the latest deploy. Three answers:

    * None: COS could not be used (no object, refused key, dead link, bad data);
    * (None, N): COS answered and N is not newer than `local_ver` - nothing to do
      anywhere, since every deploy writes COS last;
    * (manifest, N): N is newer and its manifest checked out.
    """
    data = _cos_get(cos, COS_LATEST)
    if data is None:
        return None
    try:
        ver = int(json.loads(data).get("version") or 0)
    except (ValueError, TypeError, AttributeError):
        log.warning("COS 的 latest.json 不是合法的版本记录")
        return None
    if ver <= local_ver:
        return None, ver
    data = _cos_get(cos, f"{ver}/{MANIFEST}")
    if data is None:
        return None
    try:
        m = json.loads(data)
    except json.JSONDecodeError:
        log.warning("COS 的 manifest 不是合法 JSON")
        return None
    if not isinstance(m, dict) or not isinstance(m.get("files"), dict):
        return None
    if _manifest_version(m) != ver:
        log.warning("COS 的 latest.json 说 v%s，manifest 却是 v%s，不信它", ver, _manifest_version(m))
        return None
    return m, ver


def _cos_bundle(cos, ver: int, files: dict, wanted: list[str]) -> dict[str, bytes] | None:
    """Every wanted file out of one bundle.zip on COS, each verified against the
    manifest. None when the bundle is missing or any wanted file is wrong."""
    data = _cos_get(cos, f"{ver}/{COS_BUNDLE}", timeout=60)
    if data is None:
        return None
    out: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            names = set(z.namelist())
            for rel in wanted:
                if rel not in names:
                    log.warning("COS 的 bundle 里没有 %s", rel)
                    return None
                body = z.read(rel)
                if not _matches(body, files[rel]):
                    log.warning("COS 的 bundle 里 %s 哈希不对", rel)
                    return None
                out[rel] = body
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        log.warning("COS 的 bundle 读不了: %s", exc)
        return None
    return out


def _get_once(url: str, timeout: int = 20) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ark-relay"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError, ValueError,
            http.client.HTTPException) as exc:
        # HTTPException (e.g. IncompleteRead out of resp.read()) is not an OSError.
        log.warning("取不到 %s: %s", url, exc)
        return None


def _alternates(url: str) -> list[str]:
    """The doors to one raw.githubusercontent URL: the three jsDelivr mirrors of the
    same repo path, then the URL itself. Any other URL is its only door.

    Every fetched file is checked against the manifest, so a stale CDN copy can only
    mean "no update yet". inbox.py has its own copy of this function.
    """
    prefix = "https://raw.githubusercontent.com/"
    if not url.startswith(prefix):
        return [url]
    parts = url[len(prefix):].split("/", 3)
    if len(parts) < 4:
        return [url]
    owner, repo, branch, path = parts
    ref = f"gh/{owner}/{repo}@{branch}/{path}"
    # Order measured from the game machine on 2026-08-21, 8 attempts per door:
    #   fastly.jsdelivr  8/8  average 426ms
    #   cdn.jsdelivr     7/8  average 1956ms
    #   gcore.jsdelivr   7/8  average 2398ms
    #   raw.github       2/8  average 38179ms (no CDN cache, so always freshest)
    return [
        f"https://fastly.jsdelivr.net/{ref}",
        f"https://cdn.jsdelivr.net/{ref}",
        f"https://gcore.jsdelivr.net/{ref}",
        url,
    ]


# Netloc of the door that answered most recently; tried first from then on, so the
# files after the first do not each wait out a timeout on a dead door.
_last_good = ""


def _netloc(url: str) -> str:
    """Host part of an http(s) URL; the URL itself when it has no host. Never raises."""
    parts = url.split("/")
    return parts[2] if len(parts) > 2 else url


def _remaining(deadline: float | None) -> float:
    """Seconds left before the budget runs out; unlimited when there is none."""
    return 1e9 if deadline is None else deadline - time.monotonic()


def _get_with_retry(url: str, attempts: int = 3, timeout: int = 20,
                    expect_sha: str = "", deadline: float | None = None) -> bytes | None:
    """Fetch `url` through every door, up to `attempts` passes, within `deadline`.

    With `expect_sha`, a body that does not match is a stale copy and the next door
    is tried. Returns the first matching body, or None.
    """
    global _last_good  # noqa: PLW0603
    urls = _alternates(url)
    urls.sort(key=lambda u: _netloc(u) != _last_good)  # stable: keeps order
    for i in range(attempts):
        for u in urls:
            left = _remaining(deadline)
            if left <= 1:
                log.warning("更新时间预算用尽，放弃取 %s", url.rsplit("/", 1)[-1])
                return None
            per = min(timeout, left)
            if "raw.githubusercontent.com" in u:
                per = min(per, RAW_TIMEOUT)
            if (data := _get_once(u, int(max(2, per)))) is None:
                continue
            if expect_sha and not _matches(data, expect_sha):
                log.warning("%s 给的内容和清单对不上（缓存里是旧副本），换下一扇门", _netloc(u))
                continue
            _last_good = _netloc(u)
            return data
        if i + 1 < attempts:
            nap = min(3 * (i + 1), max(0.0, _remaining(deadline) - 1))
            if nap <= 0:
                return None
            time.sleep(nap)
    return None


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _matches(data: bytes, want) -> bool:
    """Does `data` hash to `want`? The algorithm follows the digest's length:
    64 hex digits is SHA-256 (the manifest's `sha256` map), 40 is SHA-1 (`files`).
    Anything else matches nothing."""
    if not isinstance(want, str):
        return False
    if len(want) == 64:
        return hashlib.sha256(data).hexdigest() == want
    if len(want) == 40:
        return _sha1(data) == want
    return False


_HEX = re.compile(r"[0-9a-f]+")


def _expected_hashes(manifest: dict) -> "dict | None":
    """The hash each file is checked against: the `sha256` map when the manifest
    has one, `files` (SHA-1) when it has none. None when the `sha256` map is there
    but does not cover exactly the files listed, or holds anything but SHA-256
    digests: a manifest that disagrees with itself is not used."""
    files = manifest["files"]
    s256 = manifest.get("sha256")
    if s256 is None:
        log.info("清单没有 SHA-256 表（旧格式），这一轮按 SHA-1 校验")
        return files
    if (not isinstance(s256, dict) or set(s256) != set(files)
            or not all(isinstance(h, str) and len(h) == 64 and _HEX.fullmatch(h) for h in s256.values())):
        log.warning("清单的 SHA-256 表和文件表对不上，这份清单不可信，本次不更新")
        return None
    return s256


def _swap_in(src: Path, dst: Path) -> None:
    """One staged file into place. Its own name so a test can make it fail."""
    os.replace(src, dst)


def _atomic_write(target: Path, data: bytes) -> None:
    """config.atomic_write_bytes. Its own name so a test can make it fail."""
    atomic_write_bytes(target, data)


def _safe_target(root: Path, rel: str) -> Path | None:
    """Resolve a manifest path inside `root`, or None if it escapes (absolute, `..`)."""
    if rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        return None
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


# ------------------------------------------------------------------ on-disk notes
# state.json versions.code / versions.announced; state/update-failed.json (a round
# that did not land, reported and cleared at the next boot); state/update-announce.json
# (a round that landed, announced by the process that boots on the new code).

def _stored_version(root: Path, key: str) -> int:
    """state.json versions.<key> as a number; 0 when missing or not a number."""
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    try:
        return int(str(StateStore(root / "state").get("versions", key) or 0).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _applied_version(root: Path) -> int:
    """The code version this machine is running (state.json versions.code)."""
    return _stored_version(root, "code")


def _announced_version(root: Path) -> int:
    return _stored_version(root, "announced")


def _take_note(path: Path) -> dict | None:
    """The JSON object in `path`, once: the file is removed whether or not it parses
    (a torn write would otherwise fail to parse at every boot)."""
    if not path.exists():
        return None
    try:
        note = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        note = None
    path.unlink(missing_ok=True)
    return note if isinstance(note, dict) else None


def _failure_path(root: Path) -> Path:
    return root / "state" / "update-failed.json"


def take_failure(root: Path) -> dict | None:
    """The pending "an update was available and did not land" note, cleared."""
    return _take_note(_failure_path(root))


def _record_failure(root: Path, reason: str, remote: int, local: int,
                    pending: list[str]) -> None:
    try:
        _atomic_write(_failure_path(root), json.dumps({
            "reason": reason, "remote": remote, "local": local,
            "files": pending[:12], "count": len(pending),
            "at": datetime.now(tz=SERVER_TZ).isoformat(),
        }, ensure_ascii=False).encode("utf-8"))
    except OSError:
        log.warning("记不下更新失败的原因", exc_info=True)


def _clear_failure(root: Path) -> None:
    _failure_path(root).unlink(missing_ok=True)


def _announce_path(root: Path) -> Path:
    return root / "state" / "update-announce.json"


def take_announcement(root: Path) -> dict | None:
    """The pending "code was updated" note, once, cleared."""
    return _take_note(_announce_path(root))


def pending_announcement(root: Path) -> dict | None:
    """What to tell the user about a code update, or None if nothing new.

    Two sources, in order:
    1. the note written by the round that applied the update (it carries the file list);
    2. the applied version compared with the last version announced. A machine that
       has announced nothing yet counts as having something to announce (a first boot
       of this code, or a fresh install).
    """
    note = take_announcement(root)
    current = _applied_version(root)
    announced = _announced_version(root)
    if note is None:
        if not current or current == announced:
            return None
        note = {"version": current, "previous": announced or None, "files": []}
    _remember_announced(root, current or int(note.get("version") or 0))
    return note


def _remember_announced(root: Path, version: int) -> None:
    if not version:
        return
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    try:
        StateStore(root / "state").set("versions", "announced", str(version))
    except OSError:
        # Worst case the same update is announced twice.
        log.warning("记不住已通知的版本号，可能重复推送一次", exc_info=True)


def _record_announcement(root: Path, note: dict) -> None:
    try:
        _atomic_write(_announce_path(root),
                      json.dumps(note, ensure_ascii=False).encode("utf-8"))
    except OSError:
        # The update has landed either way; only its announcement is lost.
        log.warning("记不下更新通知，本次更新不会有推送", exc_info=True)


def _remember_version(root: Path, version: int) -> None:
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    try:
        StateStore(root / "state").set("versions", "code", str(version))
    except OSError:
        log.warning("记不住代码版本号，下次可能重复检查", exc_info=True)


def _best_manifest(base: str, deadline: float | None = None) -> dict | None:
    """Fetch the manifest from every door and keep the highest version.

    The manifest itself cannot be verified, and a CDN door may serve the previous
    one; versions only go up, so the highest is the newest. When no manifest has a
    version, the first one fetched is used.
    """
    best: dict | None = None
    best_ver = -1
    fallback: dict | None = None
    for url in _alternates(base + MANIFEST):
        left = _remaining(deadline)
        if left <= 1:
            log.warning("取 manifest 时预算已用尽，用手头最好的一份")
            break
        per = min(20.0, left)
        if "raw.githubusercontent.com" in url:
            per = min(max(per, float(RAW_TIMEOUT)), left)
        if (data := _get_once(url, int(max(2, per)))) is None:
            continue
        try:
            m = json.loads(data)
        except json.JSONDecodeError:
            log.warning("%s 给的 manifest 不是合法 JSON", _netloc(url))
            continue
        if not isinstance(m, dict) or not isinstance(m.get("files"), dict):
            continue
        if fallback is None:
            fallback = m
        ver = _manifest_version(m)
        if ver > best_ver:
            best, best_ver = m, ver
    if best is not None and best_ver > 0:
        log.debug("选用 v%s 的 manifest", best_ver)
        return best
    return fallback


def _manifest_version(manifest: dict) -> int:
    """The version the manifest claims; no such field, or a non-number, is 0.
    _is_downgrade compares that 0 like any other version."""
    try:
        return int(manifest.get("version") or 0)
    except (TypeError, ValueError):
        return 0


def _is_downgrade(remote_ver: int, local_ver: int) -> bool:
    """Whether the manifest just fetched is older than the version already applied here.

    A CDN can serve a whole previous release (old manifest and old files with
    matching hashes). Once this machine has applied a versioned manifest, anything
    older is refused - including an unversioned manifest (remote_ver 0), which is
    why the test is not `remote_ver and local_ver and ...`.
    """
    return bool(local_ver and remote_ver < local_ver)


# A manifest file this machine does not have yet is created when it has one of
# these suffixes (paths stay confined by _safe_target); any other new file stops
# the round. Allowed since 2026-09-15 by the user's decision, so a new module lands
# without a manual deploy.
_NEW_FILE_SUFFIXES = (".py", ".md", ".txt", ".json")
# Where _write_staged lands a round before swapping it in. Under root, so the
# swap is a rename on the same volume; make-manifest.py never lists it.
STAGING_DIR = ".selfupdate-staging"


def _may_create(rel: str) -> bool:
    return rel.endswith(_NEW_FILE_SUFFIXES)


def _wanted_files(root: Path, files: dict) -> list[str]:
    """The files this round intends to change, worked out before any download, so a
    failure report can list what did not land."""
    wanted: list[str] = []
    for rel, want in sorted(files.items()):
        target = _safe_target(root, rel)
        if target is None:
            continue
        if not target.exists():
            if _may_create(rel):
                wanted.append(rel)
            continue
        if not _matches(target.read_bytes(), want):
            wanted.append(rel)
    return wanted


_REF_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_RAW_PREFIX = "https://raw.githubusercontent.com/"


def _pinned_base(base: str, manifest: dict) -> str:
    """The base URL to fetch this manifest's files from: its own git tag, not the branch.

    make-manifest.py writes `ref` (`relay-<version>`) into every manifest and
    deploy-relay.sh pushes a tag of that name on the same commit. A tag never moves,
    so every door serves the right bytes for it; jsDelivr caches a branch for up to
    12 hours.

    A manifest without `ref`, or with one that is not a plain tag name, keeps the
    branch (the manifest is network data, so `ref` is checked before it goes into a URL).
    """
    ref = manifest.get("ref")
    if not isinstance(ref, str) or not _REF_OK.fullmatch(ref):
        return base
    if not base.startswith(_RAW_PREFIX):
        return base
    parts = base[len(_RAW_PREFIX):].split("/", 3)
    if len(parts) < 4:
        return base
    owner, repo, _branch, path = parts
    return f"{_RAW_PREFIX}{owner}/{repo}/{ref}/{path}"


def _stage_files(root: Path, base: str, files: dict, deadline: float | None,
                 remote_ver: int, local_ver: int,
                 wanted: list[str], cos=None) -> list[tuple[str, Path, bytes]] | None:
    """Download and verify every file that needs changing; write nothing; return the batch.

    When any file cannot be fetched with the right content, the failure is recorded
    and None returned: the round is abandoned as a whole.

    Doors: the COS bundle (one request for everything), then - only with the GitHub
    fallback on - the GitHub doors file by file, PARALLEL_FETCHES at a time.
    """
    plan: list[tuple[str, Path]] = []
    for rel, want in sorted(files.items()):
        target = _safe_target(root, rel)
        if target is None:
            log.warning("manifest 里的路径越界，已忽略: %s", rel)
            continue
        if not target.exists() and not _may_create(rel):
            log.warning("清单里有本机没有的新文件 %s，不是源码文件，整轮更新放弃"
                        "（这种文件只能由一次人工部署送上来）", rel)
            _record_failure(root, f"{rel}：清单里的新文件不是源码文件，自更新不创建它。"
                            "在电脑上跑一次部署脚本就能补上",
                            remote_ver, local_ver, wanted)
            return None
        if target.exists() and _matches(target.read_bytes(), want):
            continue
        if not target.exists():
            log.info("清单里的新文件 %s 本机没有，这轮一起创建", rel)
        plan.append((rel, target))
    if not plan:
        return []

    bodies: dict[str, bytes] = {}
    if cos is not None and remote_ver:
        got = _cos_bundle(cos, remote_ver, files, [rel for rel, _ in plan])
        if got is not None:
            log.info("从 COS 的 bundle 里取到 %d 个文件", len(got))
            bodies = got

    missing = [rel for rel, _ in plan if rel not in bodies]
    if missing and not github_fallback():
        log.warning("COS 的更新包里拿不到 %d 个文件（例如 %s），备用线路已关，本次不更新",
                    len(missing), missing[0])
        _record_failure(root, "腾讯云桶上的更新包拿不到或校验不对（原因见日志），备用线路已关，"
                        "本次不更新；下次开机会再试", remote_ver, local_ver, wanted)
        return None
    if missing:
        def fetch(rel: str) -> tuple[str, bytes | None]:
            return rel, _get_with_retry(base + rel, expect_sha=files[rel], deadline=deadline)
        with ThreadPoolExecutor(max_workers=min(PARALLEL_FETCHES, len(missing))) as pool:
            for rel, data in pool.map(fetch, missing):
                if data is None:
                    log.warning("%s 所有门都拿不到正确内容，本次更新整体放弃（已下 %d 个"
                                "文件都不落盘，下次启动重来）", rel, len(bodies))
                    _record_failure(root, f"{rel}：几条下载线路都没拿到新代码（线路上还是旧内容，"
                                    "或最慢那条来不及走完）",
                                    remote_ver, local_ver, wanted)
                    return None
                bodies[rel] = data
    return [(rel, target, bodies[rel]) for rel, target in plan]


def _write_staged(root: Path, staged: list[tuple[str, Path, bytes]],
                  remote_ver: int, local_ver: int, wanted: list[str]) -> "list[str] | None":
    """Put the staged content in place, all of it or none; the files that landed, or None.

    Three steps, each of which leaves the originals in place when it fails:
    1. every new file is written to STAGING_DIR and read back; every original is
       read into memory;
    2. the staged files are swapped in one by one (a rename on the same volume);
    3. if a swap fails, the files already swapped get their original bytes back and
       files that did not exist before are removed.
    A failure here is a disk or permission fault, recorded as such.
    """
    stage = root / STAGING_DIR
    shutil.rmtree(stage, ignore_errors=True)       # a round killed mid-way leaves one
    originals: list["bytes | None"] = []
    try:
        for rel, target, data in staged:
            tmp = stage / rel
            tmp.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(tmp, data)
            if tmp.read_bytes() != data:
                raise OSError(f"{rel}: 暂存区里读回来的内容和下载的不一样")
            originals.append(target.read_bytes() if target.exists() else None)
    except OSError:
        log.exception("暂存这一轮的新文件失败，原文件一个都没动，本次不更新")
        shutil.rmtree(stage, ignore_errors=True)
        _record_failure(root, "写入新代码失败（磁盘或权限），原文件一个都没动，本次不更新；下次开机会再试",
                        remote_ver, local_ver, wanted)
        return None

    done = 0
    try:
        for rel, target, _data in staged:
            # A new module may sit in a new package directory; the path itself
            # was confined to root by _safe_target when it was staged.
            target.parent.mkdir(parents=True, exist_ok=True)
            _swap_in(stage / rel, target)
            done += 1
    except OSError:
        rel = staged[done][0]
        log.exception("把新文件 %s 换上去失败，已换上的 %d 个改回原样", rel, done)
        put_back = []
        for (back_rel, target, _data), orig in zip(staged[:done], originals[:done]):
            try:
                if orig is None:
                    target.unlink(missing_ok=True)
                else:
                    _atomic_write(target, orig)
            except OSError:
                log.exception("把 %s 改回原样也失败了", back_rel)
                put_back.append(back_rel)
        shutil.rmtree(stage, ignore_errors=True)
        _record_failure(root, (f"换上新代码时 {rel} 失败（磁盘或权限，或文件被占用），"
                               + (f"{'、'.join(put_back)} 没能改回原样，机器上新旧代码混着"
                                  if put_back else "已换上的都改回了原样")
                               + "，本次不更新；下次开机会再试"),
                        remote_ver, local_ver, wanted)
        return None
    shutil.rmtree(stage, ignore_errors=True)
    return [rel for rel, _target, _data in staged]


def check(root: Path, base_url: str = "",
          budget_s: float = BUDGET_SECONDS) -> list[str]:
    """Fetch and apply any changed files. Returns the manifest paths that landed.

    `budget_s` is the wall-clock budget for the whole round (0: none); when it runs
    out the round gives up rather than hold up the queue.
    """
    base = (base_url or DEFAULT_BASE).rstrip("/") + "/"
    deadline = time.monotonic() + budget_s if budget_s else None
    local_ver = _applied_version(root)
    cos = None
    manifest = None
    fallback = github_fallback()
    try:
        cos = _cos()
    except Exception:  # a broken COS client must not stop the GitHub path
        log.warning("COS 客户端建不起来", exc_info=True)
    if cos is None and not fallback:
        # No door at all: a WARNING, since from outside "no update" looks like
        # "up to date".
        log.warning("自更新没有线路：COS 没配置（或建不起来），GitHub 备用线路已关")
        _record_failure(root, "腾讯云桶没配置好，备用线路又是关着的，这次没法更新",
                        0, local_ver, [])
        return []
    if cos is not None:
        found = _cos_manifest(cos, local_ver)
        if found is not None:
            manifest, cos_ver = found
            if manifest is None:
                log.info("COS 上最新一次部署是 v%s，本机 v%s，已是最新，不再问 GitHub",
                         cos_ver, local_ver)
                _clear_failure(root)    # up to date means nothing is outstanding
                return []
            log.info("COS 上有新版 v%s（本机 v%s）", cos_ver, local_ver)
    if manifest is None:
        if not fallback:
            log.warning("COS 上拿不到最新一次部署，备用线路已关，本次不更新，下次开机再试")
            _record_failure(root, "腾讯云桶上拿不到这次部署的清单（原因见日志），备用线路已关，"
                            "本次不更新；下次开机会再试", 0, local_ver, [])
            return []
        # The manifest is GitHub's: its bundle is not on COS under that version
        # (or COS is what just failed), so the files come from GitHub too.
        cos = None
        manifest = _best_manifest(base, deadline)
    if manifest is None:
        return []
    remote_ver = _manifest_version(manifest)
    files = _expected_hashes(manifest)
    if files is None:
        _record_failure(root, "这次部署的清单自相矛盾（SHA-256 表和文件表对不上），本次不更新",
                        remote_ver, local_ver, [])
        return []

    if _is_downgrade(remote_ver, local_ver):
        log.warning("拿到的清单更旧（v%s < 本机 v%s，0 表示没有版本号），"
                    "多半是缓存未刷新，本次不更新", remote_ver, local_ver)
        return []

    wanted = _wanted_files(root, files)
    if not wanted:
        _clear_failure(root)        # nothing to do means nothing is outstanding

    staged = _stage_files(root, _pinned_base(base, manifest), files, deadline,
                          remote_ver, local_ver, wanted, cos)
    if staged is None:
        return []

    updated = _write_staged(root, staged, remote_ver, local_ver, wanted)
    if updated is None:
        # Nothing landed (the originals are back in place) and the failure is
        # recorded; none of the success bookkeeping below may run.
        return []

    if updated:
        # Remove compiled bytecode so the restart cannot run stale .pyc files.
        for cache in root.rglob("__pycache__"):
            for pyc in cache.glob("*.pyc"):
                pyc.unlink(missing_ok=True)
        log.info("代码已更新 %d 个文件: %s", len(updated), "、".join(updated))
    # Reached only when the whole manifest is in place (including when nothing
    # needed changing), so the version is recorded; a failed round returned above.
    if remote_ver:
        _remember_version(root, remote_ver)
    if updated:
        _clear_failure(root)        # this round landed; the old complaint is stale
        _record_announcement(root, {
            "version": remote_ver, "previous": local_ver, "files": updated,
            "at": datetime.now(tz=SERVER_TZ).isoformat(),
        })
    return updated
