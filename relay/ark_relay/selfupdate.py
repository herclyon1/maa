"""The relay updates its own code at boot, over the same route as the inbox.

Until now new code reached this machine only when the Mac happened to be awake
and pushed it. That put a laptop in another country on the critical path of a
machine that runs unattended, and made every fix wait for a window where both
were up at once.

Same channel as the inbox, and the same door order (see _alternates): the
jsDelivr mirrors first, raw.githubusercontent last - measured 2026-08-21 from
the machine, raw answered 2 of 8 at an average of 38 seconds while
fastly.jsdelivr answered 8 of 8 at 426ms. A manifest lists each file with its
SHA-1, so a file is fetched only when it actually differs - an up-to-date
relay costs one small request.

This module itself never reloads code into the running process - reloading in
place is where self-updating systems go wrong. It only lands verified files on
disk; deciding what to do about that is the caller's job. service.py restarts
the service when this returns a non-empty list, so an update takes effect
within seconds instead of waiting for the next boot (operator order
2026-08-20: updates must take effect immediately). The restart is a fresh
process, not a reload.

Either every changed file lands or none does: a half-applied update leaves a
mixed-version relay, and the restart above would then boot straight into it.

Since 2026-09-18 the first door is the operator's own Tencent COS bucket (the
one evidence bundles go to): the deploy script PUTs `relay/latest.json`, the
manifest and one bundle of every file under `relay/<version>/`, and this
module GETs them with the same signed request evidence.Cos already makes.
Why: jsDelivr's caches are per node and refresh independently - on 2026-09-18
a manifest pushed at 02:31 was still the old one on the machine's node at
08:45, and the update only landed because a person deployed by hand. COS has
no cache layer: what was written is what is read. The four GitHub doors stay
as the fallback (COS answered 451 on 2026-09-13, an unpaid bill), and the
bucket's own lifecycle rule may delete the prefix one day - a missing object
is simply "COS has nothing", never an error.

Trust boundary, stated plainly: whoever can push to that repo can run code on
this machine. The repo is the operator's own and the transport is HTTPS, so the
exposure is the GitHub account itself - the same account that already decides
what the machine farms.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ, atomic_write_bytes

log = logging.getLogger("ark.selfupdate")

DEFAULT_BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
MANIFEST = "manifest.json"
# Wall-clock budget for one whole self-update round. Boot timing: on the
# morning shift the relay comes up at 08:47 and the queue starts at 09:00, on
# the evening shift 21:22 / 21:30 - the shorter of the two leaves only 8
# minutes. 240 seconds keeps a comfortable margin and is still enough to pull
# three to five files on a day when the CDNs are out of sync and only raw
# works. When it runs out, give up cleanly; the next boot (that same evening)
# tries again.
BUDGET_SECONDS = 240
# Per-attempt timeout for raw.githubusercontent. It is the only one of the four
# doors that serves no CDN cache, so when the CDNs lag behind it is the *only*
# door that can hand back new content - which means it must not be cut off too
# early: measured, it takes 38 seconds when it does succeed.
#
# This was 25, below that measured figure, while the comment claimed to be
# giving raw "one decent chance". It was not: on the boots where raw is the
# only usable door, a 25 s cut-off ends most attempts just before they would
# have returned. 45 leaves real headroom, and BUDGET_SECONDS still caps the
# round, so the cost of a door that is simply down is bounded either way.
RAW_TIMEOUT = 45


# How many files are fetched at once when they have to come one by one from
# the GitHub doors. Sequential fetching paid raw's 38 s per file; five files
# filled the whole 240 s budget (2026-09-18 plan). Six in flight keeps a
# twenty-file update inside one raw round-trip.
PARALLEL_FETCHES = 6
COS_PREFIX = "relay"
COS_LATEST = "latest.json"
COS_BUNDLE = "bundle.zip"
COS_TIMEOUT = 20


def _cos():
    """The evidence bucket's client, or None when COS is not configured on this machine."""
    from . import evidence  # noqa: PLC0415 - avoids importing evidence for machines without COS
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


def _cos_manifest(cos, local_ver: int) -> tuple[dict, int] | None:
    """(manifest, version) from COS when it is newer than what runs here.

    latest.json is a hundred bytes: {"version": N, "uploaded": "<iso>"}. Only
    when N beats the local version is the real manifest fetched, so an
    up-to-date boot costs one tiny request.
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
        log.debug("COS 上是 v%s，本机 v%s，不用更新", ver, local_ver)
        return None
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
                    log.warning("COS 的 bundle 里没有 %s，退回 GitHub", rel)
                    return None
                body = z.read(rel)
                if _sha1(body) != files[rel]:
                    log.warning("COS 的 bundle 里 %s 哈希不对，退回 GitHub", rel)
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
        # HTTPException covers the truncated-stream path out of resp.read()
        # (IncompleteRead); it is not a subclass of OSError, and leaving it
        # out lets the exception escape and takes the retry with it.
        log.warning("取不到 %s: %s", url, exc)
        return None


def _alternates(url: str) -> list[str]:
    """The same file through a second door (jsDelivr CDN over the same repo).

    raw.githubusercontent is half-walled from the machine's network and has
    gone dark for whole evenings (2026-08-17). The repo, history and write
    path stay on GitHub; only the download exit changes. Every fetched file
    is still verified against the manifest's SHA-1, so a stale CDN copy can
    only ever mean "no update yet", never wrong code.
    (Duplicated from inbox.py on purpose: selfupdate refuses to create new
    files on the machine, so a shared module would never arrive.)
    """
    prefix = "https://raw.githubusercontent.com/"
    if not url.startswith(prefix):
        return [url]
    parts = url[len(prefix):].split("/", 3)
    if len(parts) < 4:
        return [url]
    owner, repo, branch, path = parts
    ref = f"gh/{owner}/{repo}@{branch}/{path}"
    # The order comes from measurements on the game machine in the early hours
    # of 2026-08-21 (8 attempts per door):
    #   fastly.jsdelivr  8/8  average 426ms      <- best
    #   cdn.jsdelivr     7/8  average 1956ms
    #   gcore.jsdelivr   7/8  average 2398ms
    #   raw.github       2/8  average 38179ms    <- worst, but always freshest
    # So raw goes last: it is the only door that serves no CDN cache, kept as a
    # fallback rather than a first choice.
    # (jsDelivr's cache is purged globally by scripts/mac/purge-cdn.py after
    # every push.)
    return [
        f"https://fastly.jsdelivr.net/{ref}",
        f"https://cdn.jsdelivr.net/{ref}",
        f"https://gcore.jsdelivr.net/{ref}",
        url,
    ]


# Netloc of the door that answered most recently, tried first from then on.
# raw.githubusercontent goes fully dark for whole evenings (observed 08-17 and
# again 08-20, 0/6 with jsDelivr at 6/6); without stickiness every file of a
# multi-file update pays a full timeout on the dead door before the live one,
# which turns a boot-time update into minutes of waiting for nothing.
_last_good = ""


def _netloc(url: str) -> str:
    """Host part of an http(s) URL; the URL itself when it has no host.

    Never raises: a misconfigured base URL must degrade into a failed fetch
    (caught downstream), not an IndexError before any fetch is attempted.
    """
    parts = url.split("/")
    return parts[2] if len(parts) > 2 else url


def _remaining(deadline: float | None) -> float:
    """Seconds left before the budget runs out; unlimited when there is none."""
    return 1e9 if deadline is None else deadline - time.monotonic()


def _get_with_retry(url: str, attempts: int = 3, timeout: int = 20,
                    expect_sha: str = "", deadline: float | None = None) -> bytes | None:
    """Fetch, retrying transient failures across both doors.

    Measured from the game machine: raw.githubusercontent answered 11 of 11 one
    hour and 7 of 10 the next, with the failures being TLS handshake and read
    timeouts rather than refusals. One attempt at boot therefore misses roughly
    a third of the time - and a boot is the only chance of the day. Three
    attempts take that under 3%, at the cost of a few seconds on the rare bad
    morning.
    """
    global _last_good  # noqa: PLW0603 - process-lifetime stickiness by design
    urls = _alternates(url)
    urls.sort(key=lambda u: _netloc(u) != _last_good)  # stable: keeps order
    for i in range(attempts):
        for u in urls:
            left = _remaining(deadline)
            if left <= 1:
                log.warning("更新时间预算用尽，放弃取 %s", url.rsplit("/", 1)[-1])
                return None
            # raw.githubusercontent measured 2 of 8 at an average of 38
            # seconds, the slowest of the four doors. It is only the "always
            # freshest" fallback and not worth burning the boot window on -
            # give it a short timeout: getting through is a bonus, and if it
            # does not it steps aside at once.
            per = min(timeout, left)
            if "raw.githubusercontent.com" in u:
                per = min(per, RAW_TIMEOUT)
            if (data := _get_once(u, int(max(2, per)))) is None:
                continue
            # Wrong content = this door served a stale copy, so move on to the
            # next one instead of giving up here. jsDelivr's refresh is not
            # atomic (measured 2026-08-21: the .py was already new while the
            # manifest was still old), so "fetched something" and "fetched the
            # right thing" have to be judged separately. The check used to sit
            # outside this loop, and then any CDN cache skew failed the whole
            # update outright, never even trying raw.githubusercontent, whose
            # content is always the freshest.
            if expect_sha and _sha1(data) != expect_sha:
                log.warning("%s 给的是旧副本（缓存未刷新），换下一扇门", _netloc(u))
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


def _atomic_write(target: Path, data: bytes) -> None:
    """Temp file + os.replace + fsync; see config.atomic_write_bytes.

    This thin wrapper is kept only because there are many call sites; there is
    a single implementation, merged 2026-09-08.
    """
    atomic_write_bytes(target, data)


def _safe_target(root: Path, rel: str) -> Path | None:
    """Resolve a manifest path inside `root`, or None if it escapes.

    A manifest is fetched from the network, so "../../windows/system32/..." has
    to be impossible by construction rather than by trusting the file.
    """
    if rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        return None
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _applied_version(root: Path) -> int:
    """The code version this machine is running. Kept in state.json under versions.code.

    Moved in from the standalone code-version.txt on 2026-09-08: that file was
    written directly from outside by the deploy script while the relay wrote it
    too, two writers each with their own format and neither aware of the other -
    exactly the same class of problem that broke the shutdown switch on the
    desktop. Both sides now go through statestore.
    """
    from .statestore import StateStore  # noqa: PLC0415
    try:
        return int(str(StateStore(root / "state").get("versions", "code") or 0).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _failure_path(root: Path) -> Path:
    return root / "state" / "update-failed.json"


def take_failure(root: Path) -> dict | None:
    """The pending "an update was available and did not land" note, cleared.

    A silent failure here is worse than the failure itself: the machine keeps
    running old code while everything downstream assumes the push took effect.
    "Believing you deployed is worse than not deploying" applies to this path
    exactly as it does to scp.
    """
    path = _failure_path(root)
    if not path.exists():
        return None
    try:
        note = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        note = None
    path.unlink(missing_ok=True)
    return note if isinstance(note, dict) else None


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
    """Return the pending "code was updated" note, once, and clear it.

    The process that applies an update cannot be the one that reports it: it is
    still running the old code and is about to replace itself. So the update is
    recorded here and announced by the process that comes up on the new code -
    which also means the message is only ever sent once the new code is really
    running, not merely written to disk.
    """
    path = _announce_path(root)
    if not path.exists():
        return None
    try:
        note = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        note = None
    # Remove it either way. A torn write - the machine is hard power-cut twice
    # a day - would otherwise sit there failing to parse on every boot forever.
    path.unlink(missing_ok=True)
    return note if isinstance(note, dict) else None


def pending_announcement(root: Path) -> dict | None:
    """What to tell the operator about a code update, or None if nothing new.

    Two sources, in order:

    The marker written by the process that applied the update, which carries
    the file list. It cannot exist for the very first update after this feature
    ships - the code that applies that one predates the marker - so there is a
    second source.

    The applied version compared against the last version announced. That needs
    no cooperation from the process that did the update, only the version file
    it has always written. A machine that has never announced anything is
    treated as having something to announce: it is either this feature's first
    boot (there genuinely was an update) or a fresh install, and one extra
    notice is a far cheaper mistake than a silent update.
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


def _announced_version(root: Path) -> int:
    from .statestore import StateStore  # noqa: PLC0415
    try:
        return int(str(StateStore(root / "state").get("versions", "announced") or 0).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _remember_announced(root: Path, version: int) -> None:
    if not version:
        return
    from .statestore import StateStore  # noqa: PLC0415
    try:
        StateStore(root / "state").set("versions", "announced", str(version))
    except OSError:
        # Worst case the same update is announced twice. Better than dropping it.
        log.warning("记不住已通知的版本号，可能重复推送一次", exc_info=True)


def _record_announcement(root: Path, note: dict) -> None:
    try:
        _atomic_write(_announce_path(root),
                      json.dumps(note, ensure_ascii=False).encode("utf-8"))
    except OSError:
        # An update that lands without a notification is still an update; log
        # it and carry on rather than fail the whole round over the receipt.
        log.warning("记不下更新通知，本次更新不会有推送", exc_info=True)


def _remember_version(root: Path, version: int) -> None:
    from .statestore import StateStore  # noqa: PLC0415
    try:
        StateStore(root / "state").set("versions", "code", str(version))
    except OSError:
        log.warning("记不住代码版本号，下次可能重复检查", exc_info=True)


def _best_manifest(base: str, deadline: float | None = None) -> dict | None:
    """Fetch the manifest from every door and keep the highest version.

    The manifest is the baseline for every check and is the one thing that
    cannot itself be verified - so "use whichever door answers first" will not
    do. CDN refreshes are not atomic, and the door that answers first may well
    hand back the previous version (measured 2026-08-21: the files were already
    new while the manifest was still old); checking new files against an old
    manifest makes every one of them mismatch and the whole update fail forever.

    Version numbers only ever go up, so "take the highest" routes around a
    lagging door without having to trust any single one. The older format
    without a version falls back to "the first one fetched", which keeps
    backward compatibility.
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
            # `min(20, RAW_TIMEOUT)` left raw on 20 s here however large
            # RAW_TIMEOUT grew, so the door that alone can carry a fresh
            # manifest got the shortest allowance of all. Raise it to raw's
            # own budget, still bounded by what is left of the round.
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
        try:
            ver = int(m.get("version") or 0)
        except (TypeError, ValueError):
            ver = 0
        if ver > best_ver:
            best, best_ver = m, ver
    if best is not None and best_ver > 0:
        log.debug("选用 v%s 的 manifest", best_ver)
        return best
    return fallback


def _manifest_version(manifest: dict) -> int:
    """Read the version the manifest claims; no such field, or a non-number, counts as 0.

    This is its own step because "unreadable counts as 0" is not a casual
    fallback but the premise of the _is_downgrade gate below: the 0 really does
    take part in the comparison, it is not a neutral "unknown".
    """
    try:
        return int(manifest.get("version") or 0)
    except (TypeError, ValueError):
        return 0


def _is_downgrade(remote_ver: int, local_ver: int) -> bool:
    """Whether the manifest just fetched is older than the version already applied here.

    This is its own step because the whole gate rests on one counter-intuitive
    formulation (see the second comment paragraph below); buried inside check()
    it would be easy for someone later to "simplify while they are at it", and
    the price of that simplification is a silent downgrade.
    """
    # Refuse a manifest older than the one the machine already has. Downloads
    # go through a CDN, and a CDN can perfectly well be caching the previous
    # release as a whole set (old manifest + old .py, internally consistent and
    # matching hashes), which would "update" the machine back to old code while
    # the log looks entirely normal. Version numbers only ever go up, so this
    # gate turns a downgrade into an explicit warning rather than a silent
    # rollback.
    # Note this must not be written as `remote_ver and local_ver and ...`: an
    # old manifest with no version yields remote_ver == 0, which that form
    # waves straight through, and the machine gets "updated" back to old code.
    # That is exactly how a freshly deployed inbox.py was downgraded on
    # 2026-08-21, with the log saying it had updated 1 file and everything
    # looking perfectly normal.
    # Once this machine has applied a versioned manifest, anything older
    # (including an unversioned one) must be rejected.
    return bool(local_ver and remote_ver < local_ver)


# A manifest entry this machine does not have yet is created when it is plain
# relay source (the suffixes below); anything else is refused. A relay that can
# overwrite any existing .py already runs whatever the manifest says, so a new
# .py inside its own tree (paths are confined by _safe_target) opens no wider
# door; what it buys is that a module split (banners.py -> five files on
# 2026-09-08, resources.py on 2026-09-15) lands by itself instead of stalling
# every update until someone deploys by hand. The user's call, 2026-09-15,
# after resources.py stalled the morning update: relax it, a manual deploy for
# every new module is too much.
_NEW_FILE_SUFFIXES = (".py", ".md", ".txt", ".json")


def _may_create(rel: str) -> bool:
    return rel.endswith(_NEW_FILE_SUFFIXES)


def _wanted_files(root: Path, files: dict) -> list[str]:
    """Work out which files this round intends to change - before any download.

    This is its own step because the list serves only the failure report: when a
    download is abandoned midway, the report has to be able to say "these are
    the files that were going to change" rather than only which one it stopped on.
    """
    # What this round intends to change, worked out before any fetching, so a
    # failure report can say what did not land rather than only where it stopped.
    wanted: list[str] = []
    for rel, want in sorted(files.items()):
        target = _safe_target(root, rel)
        if target is None:
            continue
        if not target.exists():
            if _may_create(rel):
                wanted.append(rel)
            continue
        if _sha1(target.read_bytes()) != want:
            wanted.append(rel)
    return wanted


def _stage_files(root: Path, base: str, files: dict, deadline: float | None,
                 remote_ver: int, local_ver: int,
                 wanted: list[str], cos=None) -> list[tuple[str, Path, bytes]] | None:
    """Download and verify every file that needs changing, write not one byte to disk, return the batch.

    If any single file cannot be fetched with the correct content, record the
    failure reason and return None, meaning this round is abandoned as a whole.
    It is its own step so that the iron rule "download everything first, then
    write once" holds at a function boundary: staging and writing live in two
    different functions, which makes it impossible to write code that writes
    while it downloads.

    Order of doors: the COS bundle (one request for everything), then the
    GitHub doors file by file, PARALLEL_FETCHES at a time.
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
        if target.exists() and _sha1(target.read_bytes()) == want:
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
                  remote_ver: int, local_ver: int, wanted: list[str]) -> list[str]:
    """Write the staged content to disk in one go; return the ones that really landed.

    This is its own step because by the time it runs the network is entirely out
    of the picture: this section can only fail on disk or permissions, which is a
    completely different fault from "could not fetch it" above and calls for a
    different response.
    """
    updated: list[str] = []
    for rel, target, data in staged:
        try:
            # A new module may sit in a new package directory; the path itself
            # was confined to root by _safe_target when it was staged.
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, data)
        except OSError:
            # Everything has already been verified by this point, so failing to
            # write is a disk or permissions problem. Stop and let the next
            # boot redo it - carrying on would only spread the mixed version
            # further.
            log.exception("写入 %s 失败，停止本次更新", rel)
            _record_failure(root, f"写入 {rel} 失败（磁盘或权限），本次更新只落了一半",
                            remote_ver, local_ver, wanted)
            break
        updated.append(rel)
    return updated


def check(root: Path, base_url: str = "",
          budget_s: float = BUDGET_SECONDS) -> list[str]:
    """Fetch and apply any changed files. Returns human-readable lines.

    `budget_s` is the wall-clock budget for the whole round; overrunning it
    means giving up cleanly. That is a hard requirement on the boot path: when
    the CDN caches are out of sync every file has to try all four doors (raw
    among them being slow), and 21 files is enough to drag past the 09:00 queue
    slot. Better to skip this update than to hold up the farming.
    """
    base = (base_url or DEFAULT_BASE).rstrip("/") + "/"
    deadline = time.monotonic() + budget_s if budget_s else None
    local_ver = _applied_version(root)
    cos = None
    manifest = None
    try:
        cos = _cos()
    except Exception:  # a broken COS client must not stop the GitHub path
        log.warning("COS 客户端建不起来，走 GitHub", exc_info=True)
    if cos is not None:
        if found := _cos_manifest(cos, local_ver):
            manifest, _ = found
            log.info("COS 上有新版 v%s（本机 v%s）", _manifest_version(manifest), local_ver)
    if manifest is None:
        # The manifest is GitHub's: its bundle is not on COS under that version
        # (or COS is what just failed), so the files come from GitHub too.
        cos = None
        manifest = _best_manifest(base, deadline)
    if manifest is None:
        return []
    files = manifest["files"]

    remote_ver = _manifest_version(manifest)
    if _is_downgrade(remote_ver, local_ver):
        log.warning("拿到的清单更旧（v%s < 本机 v%s，0 表示没有版本号），"
                    "多半是缓存未刷新，本次不更新", remote_ver, local_ver)
        return []

    wanted = _wanted_files(root, files)
    if not wanted:
        _clear_failure(root)        # nothing to do means nothing is outstanding

    staged = _stage_files(root, base, files, deadline, remote_ver, local_ver, wanted, cos)
    if staged is None:
        return []

    updated = _write_staged(root, staged, remote_ver, local_ver, wanted)

    if updated:
        # Stale bytecode has run on this machine before, so clear it here too.
        for cache in root.rglob("__pycache__"):
            for pyc in cache.glob("*.pyc"):
                pyc.unlink(missing_ok=True)
        log.info("代码已更新 %d 个文件: %s", len(updated), "、".join(updated))
    # The version is recorded only once this whole manifest has landed - which
    # includes the case where everything already matched and not a single file
    # changed (that too means the machine is on this version). A run that broke
    # out midway is not recorded, so the next boot starts over.
    if remote_ver and len(updated) == len(staged):
        _remember_version(root, remote_ver)
    if updated:
        _clear_failure(root)        # this round landed; the old complaint is stale
        _record_announcement(root, {
            "version": remote_ver, "previous": local_ver, "files": updated,
            "at": datetime.now(tz=SERVER_TZ).isoformat(),
        })
    return updated
