"""The relay updates its own code at boot, over the same route as the inbox.

Until now new code reached this machine only when the Mac happened to be awake
and pushed it. That put a laptop in another country on the critical path of a
machine that runs unattended, and made every fix wait for a window where both
were up at once.

Same channel as the inbox: raw.githubusercontent.com, measured working from
here 11 times out of 11 while github.com times out outright. A manifest lists
each file with its SHA-1, so a file is fetched only when it actually differs -
an up-to-date relay costs one small request.

What this deliberately does NOT do is restart itself. Reloading code into a
running process is where self-updating systems go wrong; instead the new files
land on disk and the service picks them up the next time it starts, which on
this machine is every boot. A fix therefore takes effect the morning after it
is pushed, and never mid-run.

Trust boundary, stated plainly: whoever can push to that repo can run code on
this machine. The repo is the operator's own and the transport is HTTPS, so the
exposure is the GitHub account itself - the same account that already decides
what the machine farms.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("ark.update")

DEFAULT_BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
MANIFEST = "manifest.json"


def _get_once(url: str, timeout: int = 20) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ark-relay"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
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
    return [url, f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}"]


def _get_with_retry(url: str, attempts: int = 3, timeout: int = 20) -> bytes | None:
    """Fetch, retrying transient failures across both doors.

    Measured from the game machine: raw.githubusercontent answered 11 of 11 one
    hour and 7 of 10 the next, with the failures being TLS handshake and read
    timeouts rather than refusals. One attempt at boot therefore misses roughly
    a third of the time - and a boot is the only chance of the day. Three
    attempts take that under 3%, at the cost of a few seconds on the rare bad
    morning.
    """
    urls = _alternates(url)
    for i in range(attempts):
        for u in urls:
            if (data := _get_once(u, timeout)) is not None:
                return data
        if i + 1 < attempts:
            time.sleep(3 * (i + 1))
    return None


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()  # noqa: S324 - change detection, not security


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


def check(root: Path, base_url: str = "") -> list[str]:
    """Fetch and apply any changed files. Returns human-readable lines."""
    base = (base_url or DEFAULT_BASE).rstrip("/") + "/"
    raw = _get_with_retry(base + MANIFEST)
    if raw is None:
        return []
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("manifest 不是合法 JSON")
        return []
    files = manifest.get("files")
    if not isinstance(files, dict):
        return []

    updated: list[str] = []
    for rel, want in sorted(files.items()):
        target = _safe_target(root, rel)
        if target is None:
            log.warning("manifest 里的路径越界，已忽略: %s", rel)
            continue
        if not target.exists():
            # New files are a bigger step than updating one, and a relay that
            # can create arbitrary files is a wider door than this needs.
            log.info("跳过新增文件（需人工部署一次）: %s", rel)
            continue
        if _sha1(target.read_bytes()) == want:
            continue
        data = _get_with_retry(base + rel)
        if data is None or _sha1(data) != want:
            log.warning("%s 下载失败或校验不符，跳过", rel)
            continue
        target.write_bytes(data)
        updated.append(rel)

    if updated:
        # Stale bytecode has run on this machine before, so clear it here too.
        for cache in root.rglob("__pycache__"):
            for pyc in cache.glob("*.pyc"):
                pyc.unlink(missing_ok=True)
        log.info("代码已更新 %d 个文件，下次启动生效: %s", len(updated), "、".join(updated))
    return updated
