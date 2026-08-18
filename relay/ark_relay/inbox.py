"""Config changes queued from anywhere, applied when the machine next boots.

The machine is powered off most of the day, and the person who wants to change
what it farms is in another country. Neither end can rely on the other being
awake, so the instruction goes somewhere that is always up and the machine
collects it on its own.

That somewhere is a plain file in the project's GitHub repo, fetched over
raw.githubusercontent.com. Three things decided it, all measured from the
machine itself rather than assumed:

  * github.com is unreachable from there (10s timeout), so `git clone`/`pull`
    can never work - but raw.githubusercontent.com answered 11 out of 11
    times, 0.65-3.3s. Fetching one file is a different route from cloning.
  * a public repo needs no token, so nothing secret has to live on someone
    else's PC.
  * the file is written by a person, occasionally, and a repo gives that
    person a web editor, a diff and a history for free.

The one thing this design cannot promise is delivery: that same raw endpoint
timed out earlier the same day. So the applied version is reported in the daily
push. A change that silently failed to arrive is then visible as a version that
did not move, instead of a machine quietly farming last week's plan.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import maaend, queues, sanity_plan
from .commands import apply_command

log = logging.getLogger("ark.inbox")


def label_version(version: int) -> str:
    """2026081702 -> '08-17 v2'. Falls back to the raw number.

    The version has to be an integer so "strictly newer" can be decided without
    ambiguity - raw.githubusercontent is a CDN and can hand back a stale copy,
    and comparing dates as text invites the wrong answer at a month boundary.
    Encoding the date into the integer as YYYYMMDDNN keeps that property while
    letting the push say when the change was made instead of "v1", which tells
    the reader nothing.
    """
    text = str(version)
    if len(text) != 10:
        return f"v{version}"
    try:
        return f"{text[4:6]}-{text[6:8]} v{int(text[8:10])}"
    except ValueError:
        return f"v{version}"

DEFAULT_URL = ("https://raw.githubusercontent.com/herclyon1/maa/main/"
               "queue/config.json")


def _alternates(url: str) -> list[str]:
    """The same file through a second door.

    raw.githubusercontent is half-walled from the machine's network - the
    evening of 2026-08-17 it timed out and 429'd for hours straight, and the
    operator's pause order queued that morning never arrived before the run
    it was meant to stop. jsDelivr serves the identical GitHub content over a
    CDN with far better reachability from there. The repo, its history and
    the write path stay on GitHub untouched; only the download exit changes.
    A stale CDN copy is harmless by construction: versions apply only when
    strictly newer, and selfupdate verifies every file against its SHA-1.

    (Deliberately duplicated in selfupdate.py rather than shared: selfupdate
    refuses to create new files on the machine, so a new shared module would
    never arrive there.)
    """
    prefix = "https://raw.githubusercontent.com/"
    if not url.startswith(prefix):
        return [url]
    parts = url[len(prefix):].split("/", 3)
    if len(parts) < 4:
        return [url]
    owner, repo, branch, path = parts
    return [url, f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}"]


def _fetch(url: str, timeout: int = 20, attempts: int = 3) -> dict | None:
    """Fetch the queued file, retrying transient failures across both doors.

    Measured from the game machine: 11 of 11 one hour, 7 of 10 the next, the
    failures being TLS handshake and read timeouts. Boot is the only chance of
    the day to collect a change, so one attempt would silently drop roughly a
    third of them.
    """
    urls = _alternates(url)
    for i in range(attempts):
        for u in urls:
            if (data := _fetch_once(u, timeout)) is not None:
                return data
        if i + 1 < attempts:
            time.sleep(3 * (i + 1))
    return None


def _fetch_once(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ark-relay"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("取不到待办文件（%s）: %s", url, exc)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("待办文件不是合法 JSON: %s", exc)
        return None
    return data if isinstance(data, dict) else None


class Inbox:
    """Remembers which version has been applied; applies newer ones once."""

    def __init__(self, state_dir: Path, url: str = "", maaend_dir: Path | None = None,
                 automas_dir: Path | None = None):
        self.url = url or DEFAULT_URL
        self.marker = Path(state_dir) / "inbox-version.txt"
        self.maaend_dir = maaend_dir
        self.automas_dir = automas_dir
        # Whether the last poll actually reached the queue file. "Could not
        # fetch" and "fetched, nothing new" both return quietly from poll();
        # the caller needs to tell them apart to keep retrying the former -
        # a pause order that fails to download is not a pause order.
        self.last_fetch_ok = True

    @property
    def applied_version(self) -> int:
        try:
            return int(self.marker.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return 0

    def _remember(self, version: int) -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(str(version), encoding="utf-8")

    def poll(self) -> tuple[int, list[str]]:
        """Fetch, and apply if it is newer. Returns (version_now, messages).

        Messages are empty when nothing changed - the overwhelmingly common
        case. This runs on a machine that boots twice a day and is expected to
        do nothing at all on almost every one of those boots.
        """
        have = self.applied_version
        data = self._fetch_or_none()
        self.last_fetch_ok = data is not None
        if data is None:
            return have, []

        try:
            version = int(data.get("version") or 0)
        except (TypeError, ValueError):
            log.warning("待办文件的 version 不是整数，忽略")
            return have, []

        # Strictly greater, never merely different. raw.githubusercontent is a
        # CDN and can serve a stale copy for a few minutes; on "different" that
        # would re-apply an older plan and flip the machine back and forth.
        if version <= have:
            return have, []

        note = str(data.get("note") or "").strip()
        commands = data.get("commands")
        if not isinstance(commands, list):
            log.warning("待办文件 v%s 没有 commands 数组，忽略", version)
            return have, []

        log.info("收到待办 v%s（当前 v%s）：%s", version, have, note or "(无说明)")
        messages = self._apply(commands)
        # Recorded even when a command failed. Retrying the same broken batch
        # on every boot would push the same failure every morning and never
        # get better; the failure is reported instead, and the fix is a new
        # version - which is also how the operator learns it did not land.
        self._remember(version)
        head = f"⚙️ 配置已更新 · {label_version(version)}"
        if note:
            head += f"\n{note}"
        return version, [head, *messages]

    def _fetch_or_none(self) -> dict | None:
        return _fetch(self.url)

    def _apply(self, commands: list) -> list[str]:
        out: list[str] = []
        # MaaEnd changes are batched so an interdependent set lands together.
        maaend_batch = [c for c in commands
                        if isinstance(c, dict) and c.get("action") == "maaend_option"]
        others = [c for c in commands
                  if isinstance(c, dict) and c.get("action") != "maaend_option"]

        if maaend_batch:
            if not self.maaend_dir:
                out.append("✗ 终末地：找不到安装路径，跳过")
            else:
                ok, detail = maaend.apply_changes(self.maaend_dir, maaend_batch)
                out.append(("✅ 终末地：" if ok else "✗ 终末地：") + detail)

        for cmd in [c for c in others if c.get("action") == "queue"]:
            if not self.automas_dir:
                out.append("✗ 队列：找不到 AUTO-MAS 目录，跳过")
                continue
            ok, detail = queues.apply(
                self.automas_dir, str(cmd.get("name") or ""),
                cmd.get("enabled"), cmd.get("scripts"))
            out.append(("✅ " if ok else "✗ ") + detail)

        for cmd in [c for c in others if c.get("action") == "sanity_plan"]:
            # The one that actually decides what MaaEnd farms. Everything it
            # writes lands in AUTO-MAS, because AUTO-MAS overwrites MaaEnd's
            # own copy on every launch.
            if not self.automas_dir:
                out.append("✗ 理智方案：找不到 AUTO-MAS 目录，跳过")
                continue
            ok, detail = sanity_plan.set_plan(
                self.automas_dir, str(cmd.get("tab") or ""),
                str(cmd.get("line") or ""), str(cmd.get("rewards_set") or ""))
            out.append(("✅ 理智方案：" if ok else "✗ 理智方案：") + detail)

        for cmd in [c for c in others
                    if c.get("action") not in ("sanity_plan", "queue")]:
            # The file can only be written by whoever can push to the repo, so
            # authorship is the confirmation that gate ② asks for.
            ok, detail = apply_command({**cmd, "confirmed": True})
            out.append(("✅ " if ok else "✗ ") + f"{cmd.get('action')}: {detail}")
        return out
