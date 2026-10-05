"""A copy of every group alarm in the COS object alerts/<Beijing YYYYMMDD>.jsonl.

The user, 2026-10-06 00:23, asked for a copy of every alarm the relay sends to the
group, made at the moment it is sent, for his Mac to keep (「中继每往群里发一条报警，
就同时抄一份给 Mac」). The machine writes, the Mac reads the bucket with its own keys.

One JSON object per line, exactly these fields (empty string when unknown):

    ts            "YYYY-MM-DD HH:MM:SS", Beijing time (UTC+8) computed from UTC,
                  so neither the machine's clock zone nor the Mac's (Tokyo) matters
    game          明日方舟 / 终末地 / 鸣潮 when the title names exactly one of them
                  (else the body, when it names exactly one), else ""
    title, text   what was pushed, verbatim
    version       the relay code version that sent it (StateStore versions/code)
    evidence_run  the run id (<date>/<user>/<stem>) the alarm names, else ""

How it gets there. The line is first appended to state/alerts/<day>.jsonl on
the caller's thread (a local write, so nothing is lost when the process dies
right after the alarm); a thread of its own then PUTs that whole day file to
COS. The day file *is* the object's content, so a PUT that failed is repaired
by the next one, and pending days are flushed again at boot (`flush_async`).
A day file that was started without a local copy of the object (a fresh
state dir) first GETs the object and keeps its lines, so a wiped state dir
does not overwrite the day's earlier alarms; no PUT happens until that GET
has an answer.

Uses the relay's existing COS client (phone.state_cos, the bucket the
heartbeat and the phone state already go to) and phone.cos_put / cos_get,
with a private ACL: only key holders read it. The object falls under the
bucket's 30-day lifecycle rule like everything else outside relay/.

A COS failure never delays or stops the alarm, and is said once on this
module's logger as a WARNING, again only after it worked in between. Like every
WARNING it reaches the group (errwatch), except when the copy was made for one
of errwatch's own pushes: that copy runs on a thread of errwatch's push path, so
its failure cannot ring the group, start another copy and feed itself.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("ark.alertlog")

BEIJING = timezone(timedelta(hours=8))
PREFIX = "alerts"
FIELDS = ("ts", "game", "title", "text", "version", "evidence_run")
TIMEOUT = 15
KEEP_DAYS = 7          # local day files kept once they are on COS
_DAY = re.compile(r"^\d{8}$")

# The three games by the names the notification texts use (texts.py) and the
# script names AUTO-MAS runs them under. Case-sensitive: 「MAA」 is MAA's own
# name, while 「MaaEnd」 is Endfield's.
_GAMES = (("明日方舟", re.compile(r"明日方舟|(?<![A-Za-z])MAA(?![A-Za-z])")),
          ("终末地", re.compile(r"终末地|MaaEnd")),
          ("鸣潮", re.compile(r"鸣潮|OK-WW")))
# collector.py: run_id = f"{date}/{user}/{stem}"; evidence keys spell it with "_"
# (evidence.uploaders: prefix=run_id.replace("/", "_")).
_RUN = re.compile(r"(?<!\d)(\d{4}-\d\d-\d\d)[/_]([A-Za-z]+)[/_]([A-Za-z][\w-]*?-\d\d-\d\d-\d\d)(?![\w-])")


def beijing(now: "datetime | None" = None) -> datetime:
    """`now` (default: the current UTC instant) in Beijing time."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("a naive time cannot be placed in Beijing time")
    return now.astimezone(BEIJING)


def key_for(day: str) -> str:
    """The COS object for a Beijing day 'YYYYMMDD'."""
    return f"{PREFIX}/{day}.jsonl"


def _games_in(text: str) -> list[str]:
    return [g for g, rx in _GAMES if rx.search(text or "")]


def game_of(title: str, text: str) -> str:
    """The one game the title names, else the one game the body names, else ''."""
    for part in (title, text):
        found = _games_in(part)
        if len(found) == 1:
            return found[0]
        if found:
            return ""        # more than one: not one game's alarm
    return ""


def run_of(title: str, text: str) -> str:
    """The first run id the alarm names, as date/user/stem; '' when none."""
    m = _RUN.search(f"{title}\n{text}")
    return "/".join(m.groups()) if m else ""


def row(title: str, text: str, version: str = "", now: "datetime | None" = None) -> dict:
    return {"ts": beijing(now).strftime("%Y-%m-%d %H:%M:%S"),
            "game": game_of(title, text),
            "title": str(title or ""),
            "text": str(text or ""),
            "version": str(version or ""),
            "evidence_run": run_of(title, text)}


class AlertLog:
    """The local day files and their sync to COS.

    `put(key, data) -> None | why` and `get(key) -> (bytes | None, why)` are the
    uploader; None for `put` means this machine has no COS (lines are still kept
    locally). Tests pass fakes; production builds them from phone.cos_put/cos_get.
    """

    def __init__(self, state_dir, put=None, get=None):
        self.dir = Path(state_dir) / "alerts"
        self._put, self._get = put, get
        self._lock = threading.Lock()
        self._ok = True              # last sync worked; a failure is said once per change

    # ---------- local ----------

    def _file(self, day: str) -> Path:
        return self.dir / f"{day}.jsonl"

    def _mark_path(self, day: str) -> Path:
        return self.dir / f"{day}.cos.json"

    def _mark(self, day: str) -> dict:
        try:
            data = json.loads(self._mark_path(day).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"seeded": False, "synced": -1}
        return data if isinstance(data, dict) else {"seeded": False, "synced": -1}

    def _set_mark(self, day: str, mark: dict) -> None:
        from .config import atomic_write_text  # noqa: PLC0415
        atomic_write_text(self._mark_path(day), json.dumps(mark))

    def record(self, title: str, text: str, version: str = "", now: "datetime | None" = None) -> str:
        """Append one line to the day file; returns the Beijing day 'YYYYMMDD'."""
        entry = row(title, text, version, now)
        day = entry["ts"][:10].replace("-", "")
        line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            f = self._file(day)
            if not f.exists():
                # A day file the COS object has not been read into yet.
                self._set_mark(day, {"seeded": False, "synced": -1})
            with f.open("ab") as fh:
                fh.write(line)
        return day

    # ---------- COS ----------

    def _days(self) -> list[str]:
        try:
            names = sorted(p.stem for p in self.dir.glob("*.jsonl"))
        except OSError:
            return []
        return [d for d in names if _DAY.match(d)]

    def sync(self) -> list[str]:
        """PUT every day file COS does not have in full yet. -> problems ([] = all there)."""
        if self._put is None:
            return []
        problems: list[str] = []
        with self._lock:
            for day in self._days()[-KEEP_DAYS:]:
                f = self._file(day)
                mark = self._mark(day)
                try:
                    data = f.read_bytes()
                except OSError as exc:
                    problems.append(f"{day}: {exc}")
                    continue
                if mark.get("seeded") and mark.get("synced") == len(data):
                    continue
                if not mark.get("seeded"):
                    old, why = self._get(key_for(day)) if self._get else (None, "")
                    if why:
                        problems.append(f"{key_for(day)} 读不回来（{why}），先不写，免得盖掉")
                        continue
                    if old:
                        data = old + (b"" if old.endswith(b"\n") else b"\n") + data
                        f.write_bytes(data)
                    mark = {"seeded": True, "synced": -1}
                    self._set_mark(day, mark)
                why = self._put(key_for(day), data)
                if why:
                    problems.append(f"{key_for(day)}：{why}")
                    continue
                self._set_mark(day, {"seeded": True, "synced": len(data)})
            self._prune()
        if problems and self._ok:
            log.warning("报警抄到腾讯云 COS 没成，下一条报警或下次开机再补：%s", "；".join(problems))
        elif not problems and not self._ok:
            log.info("报警抄到腾讯云 COS 又成了")
        self._ok = not problems
        return problems

    def _prune(self) -> None:
        cutoff = (beijing() - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
        for day in self._days():
            if day >= cutoff:
                continue
            f = self._file(day)
            try:
                if self._mark(day).get("synced") == f.stat().st_size:
                    f.unlink()
                    self._mark_path(day).unlink(missing_ok=True)
            except OSError:
                pass

    def flush_async(self) -> "threading.Thread | None":
        """Sync on a thread of its own (never raises into the caller)."""
        if self._put is None:
            return None

        def run() -> None:
            try:
                self.sync()
            except Exception:   # the copy never breaks anything else
                log.warning("报警抄到腾讯云 COS 出错", exc_info=True)

        from . import errwatch  # noqa: PLC0415
        name = f"{errwatch.PUSH_THREAD}-copy" if errwatch.in_push_path() else "alarm-copy"
        t = threading.Thread(target=run, name=name, daemon=True)
        t.start()
        return t

    def copy(self, title: str, text: str, version: str = "", now: "datetime | None" = None):
        """Keep the line, then send the day to COS on a thread. -> that thread or None."""
        self.record(title, text, version, now)
        return self.flush_async()


def for_config(cfg) -> AlertLog:
    """The AlertLog of this machine: COS from COS_* when configured, local-only otherwise."""
    from . import phone  # noqa: PLC0415
    cos = phone.state_cos(cfg)
    if cos is None:
        return AlertLog(cfg.state_dir)
    return AlertLog(
        cfg.state_dir,
        put=lambda key, data: phone.cos_put(cos, key, data, TIMEOUT, public=False,
                                            content_type="application/x-ndjson; charset=utf-8"),
        get=lambda key: phone.cos_get(cos, key, TIMEOUT))
