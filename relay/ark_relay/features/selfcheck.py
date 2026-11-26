"""After-shift check: the sign-off items the relay had no check of its own for.

scripts/mac/lib/healthcheck.py is the hand-run sign-off check. Everything else in it
is already judged by the relay itself (boot self-check, the daily report's relay
lines, the machine checks). These four were not, so they run here once after every
finished morning / evening shift. The 游戏-中继二 session's scope cut of 10-10 23:3x
listed six; 验收 dropped MAA's IfActivityFirst and IfFight on 10-11 (his own phone
settings - his 09-11 「管我刷什么干嘛」 - and the daily report is for him to read):

1. MAA's annihilation switch is not "Close" with this game-week not done
   (annihilation.WeeklyGate.switch_off_line - the same rule as the boot alarm);
2. (a note, not a fault) the one-shot 「下次跑完不关机」 mark is not armed when the shift ends (modes.skip_armed;
   armed, it skips this shift's power-off and the machine stays on until the next shift);
3. (a note, not a fault) debug mode is not on (modes.debug_active);
4. no test window run-one.sh opened is still open (report.test_windows).

When: the first tick after a scheduled shift on this boot has every script
recorded and its records seen landing (shutdown._not_shift returns None - which
already leaves out a run started by hand and a relay restarted after the shift).
Once per shift: the shift's due time is kept in state.json marks. It runs before
the daily report and the shutdown decision of that tick: the report then carries
the line, and the 「下次跑完不关机」 mark is read before the shutdown step spends it.

A due shift whose scripts all recorded but that _not_shift rules out (started by
hand, records not seen landing) gets one INFO line 「收工体检（晚班）这班没查：<why>」
instead, so the daily report says the shift went unchecked.
"""
from __future__ import annotations

import logging
import hashlib
import json
import os
import re
import threading
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from ark_relay.core import config as names, texts
from pathlib import Path, PureWindowsPath
from dataclasses import dataclass

_log_shiftcheck = logging.getLogger("ark.shiftcheck")

MARK = "shiftcheck_shift"     # state.json marks: the due time of the last shift checked
_last_failure = [""]          # the last reason maybe_run could not tell whether a shift finished
_last_unjudged = [""]         # the last "<due> <why>" a due shift was said not to be judged


def judge(annihilation_line: "str | None", skip_armed: bool, debug_on: bool, debug_until: str,
          windows: list) -> list[Check]:
    """The four items from what was read. `annihilation_line` is switch_off_line's text
    ('' when the switch is fine, None when it could not be read)."""
    out: list[Check] = []
    out.append(Check(texts.SHIFTCHECK_ANNIHILATION, None if annihilation_line is None else not annihilation_line,
                     texts.SHIFTCHECK_ANNIHILATION_UNREAD if annihilation_line is None else annihilation_line))
    # Items 2 and 3 are switches the owner sets himself (USER-SWITCHES.txt): on, they
    # hold (ok) and carry a detail, which summary prints as a note, never as 「不对」.
    out.append(Check(texts.SHIFTCHECK_SKIP, True, texts.SHIFTCHECK_SKIP_ON if skip_armed else ""))
    out.append(Check(texts.SHIFTCHECK_DEBUG, True, texts.shiftcheck_debug_on(debug_until) if debug_on else ""))
    still = [w for w in windows if isinstance(w, dict) and w.get("until") is None]
    out.append(Check(texts.SHIFTCHECK_TEST_WINDOW, not still,
                     texts.shiftcheck_test_window_on(str(still[0].get("since") or "")) if still else ""))
    return out


def summary(shift: str, checks: list[Check]) -> str:
    bad = [(c.name, c.detail) for c in checks if c.ok is False]
    unread = [(c.name, c.detail) for c in checks if c.ok is None]
    notes = [(c.name, c.detail) for c in checks if c.ok is True and c.detail]
    return texts.shiftcheck_summary(shift, len(checks), bad, unread, notes)


def read(eng, now: datetime) -> list[Check]:
    """Read the four items on the machine and judge them."""
    from ark_relay.features import modes  # noqa: PLC0415
    from ark_relay.features import report  # noqa: PLC0415
    state_dir = eng.cfg.state_dir
    gate = getattr(eng, "_annihilation", None)
    try:
        ann = gate.switch_off_line(now) if gate is not None else None
    except Exception as exc:  # noqa: BLE001 - an unreadable switch is a 「判不了」, not a crash
        _log_shiftcheck.warning("收工体检：剿灭开关读不到（%s: %s）", type(exc).__name__, exc)
        ann = None
    return judge(ann, modes.skip_armed(state_dir), modes.debug_active(state_dir, now),
                 modes.debug_until(state_dir), report.test_windows(state_dir))


def finished_shift(eng, now: datetime) -> "dict | None":
    """The scheduled shift on this boot that has just finished (the latest-due queue of
    it), or None when none has (the same test the shutdown decision uses)."""
    from ark_relay.features import shutdown  # noqa: PLC0415
    booted = eng._boot_time(now)
    if booted is None:
        return None
    shift = shutdown._shift_queues(eng, now, booted)
    if not shift:
        return None
    last = max(shift, key=lambda q: q["due"])
    reason = shutdown._not_shift(eng, now, eng._recent_entries(now), booted, shift)
    # 「shift-held」: the shift finished; a make-up or update after it took only its power-off.
    if reason is None or reason[0] == "shift-held":
        return last
    code, why = reason
    if code == "not-shift":
        # Due, every script recorded, yet not a shift that may be judged (started by
        # hand, records not seen landing): one line per shift and reason, so the daily
        # report shows the shift was skipped rather than nothing at all.
        said = f"{last['due'].isoformat()} {why}"
        if _last_unjudged[0] != said:
            _last_unjudged[0] = said
            _log_shiftcheck.info("%s%s）这班没查：%s", texts.SHIFTCHECK_HEAD, _shift_name(last), why)
    return None


def _shift_name(last: dict) -> str:
    return names.canonical(str(last.get("name") or "")).strip("?") or (
        names.MORNING if last["due"].hour < 12 else names.EVENING)   # plan gives "?" for no name


def maybe_run(eng, now: datetime) -> "list[Check] | None":
    """Run the check once for a shift that just finished. Returns the checks, or None
    when there was nothing to do now. Never raises."""
    try:
        last = finished_shift(eng, now)
        if last is None:
            return None
        key = last["due"].isoformat()
        store = eng.state.store
        if store.get("marks", MARK) == key:
            return None
        # Marked before judging: a check that crashes must not run again on every tick.
        store.set("marks", MARK, key)
        shift = _shift_name(last)
    except Exception as exc:  # noqa: BLE001
        # Asked again on every tick: logged once per distinct failure, not once a tick.
        why = f"{type(exc).__name__}: {exc}"
        if _last_failure[0] != why:
            _last_failure[0] = why
            _log_shiftcheck.exception("收工体检：判不了这班跑完没有，这一轮不查")
        return None
    _last_failure[0] = ""
    try:
        checks = read(eng, now)
    except Exception:  # noqa: BLE001
        _log_shiftcheck.exception(texts.shiftcheck_broken(shift))
        return []
    if any(c.ok is False for c in checks):
        _log_shiftcheck.warning(summary(shift, checks))
    else:
        _log_shiftcheck.info(summary(shift, checks))
    return checks


_log_tape = logging.getLogger("ark.tape")

BEIJING = timezone(timedelta(hours=8))
DIR = "tape"
DAY_CAP_BYTES = 4 * 1024 * 1024
# Day files kept, today included: two weeks of days to pull and replay.
KEEP_DAYS = 14
# A body longer than this is kept as an excerpt (`cut`) plus the hash of the whole.
# Measured in the same replay: the biggest single answer was 210 425 bytes (a banner
# source); every answer of those days fits whole.
BODY_CAP = 256 * 1024
# AUTO-MAS config files the relay reads (grep "...Config.json" over relay/: only these).
CONFIG_FILES = ("QueueConfig.json", "ScriptConfig.json", "PlanConfig.json")
_DAY_FILE = re.compile(r"^(\d{8})\.jsonl$")
_ERROR_CAP = 300

# ---------------------------------------------------------------- masking
# (name, pattern, replacement). The lookahead keeps an already masked value from
# matching again; values are token characters only. relay/tests/daysim/slice.py imports
# this tuple, so the corpus and the tape mask the same shapes.
SECRET_PATTERNS = (
    ("cos-akid", rb"AKID(?!REDACTED)[0-9A-Za-z]{12,}", rb"AKIDREDACTED"),
    ("cos-signature", rb"(q-signature=)(?!REDACTED)[0-9a-fA-F]{16,}", rb"\1REDACTED"),
    ("wecom-webhook-key", rb"(webhook/send\?key=)(?!REDACTED)[0-9A-Za-z-]{16,}", rb"\1REDACTED"),
    ("wecom-corpsecret", rb"(corpsecret=)(?!REDACTED)[0-9A-Za-z_-]{16,}", rb"\1REDACTED"),
    ("access-token", rb"(access_token=)(?!REDACTED)[0-9A-Za-z_-]{16,}", rb"\1REDACTED"),
    ("serverchan-key", rb"\bSCT(?!REDACTED)[0-9A-Za-z]{16,}", rb"SCTREDACTED"),
    ("github-token", rb"\bgh[pousr]_[0-9A-Za-z]{30,}", rb"ghx_REDACTED"),
    ("api-key", rb"\bsk-(?!REDACTED)[0-9A-Za-z_-]{30,}", rb"sk-REDACTED"),
    ("cdk", rb"(?i)(cdk[\"']?\s*[:=]\s*[\"']?)(?!REDACTED)[0-9A-Za-z]{16,}", rb"\1REDACTED"),
)
_SECRET_RES = [(re.compile(p.decode("ascii")), r.decode("ascii")) for _n, p, r in SECRET_PATTERNS]
# The game UID as OK-WW's OCR reads it off the screen: the label, a colon, the digits
# (lint-repo.sh item 12). The digits become UIDREDACT cut to their length.
UID_RE = re.compile("(特征码(?::|：) *)([0-9]+)")
MASK = "<已隐藏>"          # scripts/mac/redact.py's MASK
# scripts/mac/redact.py SECRET_KEY_HINTS / SECRET_KEY_ALLOW (test_verify.py keeps them equal).
KEY_HINTS = ("key", "cdk", "secret", "token", "password", "passwd", "credential",
             "sendkey", "webhook", "cookie", "authorization", "auth", "corpsecret",
             "apikey", "access", "private", "signature")
KEY_ALLOW = ("keyboard", "keymap", "hotkey", "keyword", "monkey", "keep",
             "accesskeytype", "privateworld")


def mask_text(s: str) -> str:
    """Every SECRET_PATTERNS shape and the game UID masked in `s`."""
    for rx, rep in _SECRET_RES:
        s = rx.sub(rep, s)
    return UID_RE.sub(lambda m: m.group(1) + ("UIDREDACT" * 4)[:len(m.group(2))], s)


def secret_key(key: str) -> bool:
    k = key.lower()
    return not any(a in k for a in KEY_ALLOW) and any(h in k for h in KEY_HINTS)


def mask_json(obj):
    """A JSON value with every secret-named non-empty string replaced by MASK
    (scripts/mac/redact.py walk) and every other string through mask_text."""
    if isinstance(obj, dict):
        return {k: (MASK if secret_key(str(k)) and isinstance(v, str) and v else mask_json(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_json(v) for v in obj]
    if isinstance(obj, str):
        return mask_text(obj)
    return obj


# ---------------------------------------------------------------- the file
_lock = threading.Lock()
_st: dict = {"dir": None, "automas_dir": None, "day": None, "size": 0, "full": False,
             "last": {}, "events": set(), "config": False}


def _now(now: "datetime | None") -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(BEIJING)


def install(state_dir, automas_dir=None, now: "datetime | None" = None) -> None:
    """Start the tape in <state_dir>/tape: a `boot` line and, unless today's tape has
    them already, AUTO-MAS's config files."""
    try:
        with _lock:
            _st.update(dir=Path(state_dir) / DIR, automas_dir=Path(automas_dir) if automas_dir else None,
                       day=None, size=0, full=False, last={}, events=set(), config=False)
        _write({"kind": "boot", "pid": os.getpid()}, now)
    except Exception as exc:  # noqa: BLE001 - recording never stops the relay
        _log_tape.debug("tape install: %s", exc)


def uninstall() -> None:
    """Back to recording nothing (the tests' tear-down)."""
    with _lock:
        _st.update(dir=None, automas_dir=None, day=None, last={}, events=set())


def _write(rec: dict, now: "datetime | None") -> None:
    """Append one line to the day's file; opening a new day prunes old files and adds
    the config snapshot when the day has none."""
    t = _now(now)
    day = t.strftime("%Y%m%d")
    stamp = t.isoformat(timespec="milliseconds")
    with _lock:
        if _st["dir"] is None:
            return
        if _st["day"] != day:
            _open_day(day, t)
        lines = [_line({"t": stamp, **rec})]
        if not _st["config"]:
            _st["config"] = True
            lines += [_line({"t": stamp, **c}) for c in _config_records()]
        for ln in lines:
            _append(ln, stamp)


def _line(rec: dict) -> str:
    return mask_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":"))) + "\n"


def _open_day(day: str, t: datetime) -> None:
    d = _st["dir"]
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{day}.jsonl"
    size, full, has_config, last, events = 0, False, False, {}, set()
    if p.exists():
        data = p.read_bytes()
        if data and not data.endswith(b"\n"):
            # A line cut by a power-off: end it, so the next line starts a line of its own.
            with open(p, "ab") as f:
                f.write(b"\n")
            data += b"\n"
        size = len(data)
        full = b'"kind":"truncated"' in data[-200:]
        has_config = b'"kind":"config"' in data
        last, events = _known(data)
    _st.update(day=day, size=size, full=full, last=last, events=events, config=has_config)
    _prune(d, t)


def _known(data: bytes) -> "tuple[dict, set]":
    """What an earlier boot already put on today's tape: the last answer per request
    and the System log events, so a restart does not write them all again."""
    last: dict = {}
    events: set = set()
    for ln in data.splitlines():
        try:
            rec = json.loads(ln)
            if rec.get("kind") in ("mas", "web"):
                last[_key(rec)] = {"fp": _fingerprint(rec), "seen": datetime.fromisoformat(rec["t"]), "n": 0}
            elif rec.get("kind") == "syslog":
                events.update(_sha(x) for x in rec.get("events") or [])
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return last, events


def _prune(d: Path, t: datetime) -> None:
    oldest = (t - timedelta(days=KEEP_DAYS - 1)).strftime("%Y%m%d")
    for p in d.iterdir():
        m = _DAY_FILE.match(p.name)
        if m and m.group(1) < oldest:
            try:
                p.unlink()
            except OSError as exc:
                _log_tape.debug("tape: cannot delete %s: %s", p, exc)


def _append(line: str, stamp: str) -> None:
    if _st["full"]:
        return
    n = len(line.encode("utf-8"))
    if _st["size"] + n > DAY_CAP_BYTES:
        line = _line({"t": stamp, "kind": "truncated", "cap": DAY_CAP_BYTES})
        _st["full"] = True
        n = len(line.encode("utf-8"))
    with open(_st["dir"] / f"{_st['day']}.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(line)
    _st["size"] += n


def _config_records() -> list[dict]:
    base = _st["automas_dir"]
    if base is None:
        return []
    from ark_relay.core import mastercfg as masconfig  # noqa: PLC0415 - the tape imports nothing of the relay at load
    out = []
    for name in CONFIG_FILES:
        p = masconfig.source(base / "config" / name)   # v5.8 keeps them as YAML
        try:
            raw = p.read_bytes()
            mt = datetime.fromtimestamp(p.stat().st_mtime, BEIJING).isoformat(timespec="seconds")
        except OSError as exc:
            out.append({"kind": "config", "file": name, "error": _err(exc)})
            continue
        out.append({"kind": "config", "file": name, "mtime": mt, **_body(raw)})
    return out


# ---------------------------------------------------------------- what gets recorded
def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:_ERROR_CAP]


def _bytes(raw) -> bytes:
    return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw or b"")


def _body(raw) -> dict:
    """A received body: len, sha256 of the whole, and the content (_content)."""
    raw = _bytes(raw)
    return {"len": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), **_content(raw)}


def _content(raw: bytes) -> dict:
    """The content as `json` / `text`, or an `excerpt` with `cut` past BODY_CAP."""
    out: dict = {}
    text = raw.decode("utf-8-sig", "replace")
    if len(raw) > BODY_CAP:
        out["excerpt"] = mask_text(text[:BODY_CAP])
        out["cut"] = True
        return out
    try:
        out["json"] = mask_json(json.loads(text))
    except ValueError:
        out["text"] = mask_text(text)
    return out


def _status(resp) -> "int | None":
    for name in ("status", "code"):
        v = getattr(resp, name, None)
        if isinstance(v, int):
            return v
    return None


def answer(kind: str, where: str, *, req=None, body=None, resp=None, error: "BaseException | None" = None,
           now: "datetime | None" = None) -> None:
    """One answer the relay received: `kind` "mas" (where = API path) or "web" (where =
    URL); `req` the request body; `body` the received bytes / text and `resp` the
    response (for its status), or `error` the exception the call raised (an HTTPError's
    code becomes `status`)."""
    try:
        if _st["dir"] is None:
            return
        rec: dict = {"kind": kind, ("path" if kind == "mas" else "url"): mask_text(str(where))}
        if req:
            rec["req"] = _req(req)
        st = _status(error if error is not None else resp)
        if st is not None:
            rec["status"] = st
        raw = b""
        if error is not None:
            rec["error"] = _err(error)
        else:
            raw = _bytes(body)
            rec.update(len=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        # The content is masked and parsed only when the line is written.
        _changed(rec, _key(rec), _fingerprint(rec), now, more=None if error is not None else lambda: _content(raw))
    except Exception as exc:  # noqa: BLE001 - recording never stops the relay
        _log_tape.debug("tape %s %s: %s", kind, where, exc)


def _key(rec: dict) -> tuple:
    """The request an answer belongs to, from the line as written (masked)."""
    return (rec["kind"], rec.get("path") or rec.get("url"),
            json.dumps(rec.get("req"), sort_keys=True, ensure_ascii=False))


def _fingerprint(rec: dict) -> str:
    """Equal for two answers that need not both be written: same status and bytes, or
    the same failure (status and exception type)."""
    if "error" in rec:
        return f"error|{rec.get('status')}|{str(rec['error']).split(':', 1)[0]}"
    return f"{rec.get('status')}|{rec['sha256']}"


def _sha(xml: str) -> str:
    return hashlib.sha256(mask_text(xml).encode("utf-8")).hexdigest()


def _req(req):
    if isinstance(req, (bytes, bytearray)):
        req = bytes(req).decode("utf-8", "replace")
        try:
            return mask_json(json.loads(req))
        except ValueError:
            return mask_text(req)
    return mask_json(req)


def _changed(rec: dict, key, fp: str, now, more=None) -> None:
    """Write `rec` (plus `more()`) unless the last answer recorded today for `key` had
    fingerprint `fp`."""
    t = _now(now)
    day = t.strftime("%Y%m%d")
    with _lock:
        last = _st["last"].get(key) if _st["day"] == day else None
        if last is not None and last["fp"] == fp:
            last["seen"], last["n"] = t, last["n"] + 1
            return
    if more is not None:
        rec.update(more())
    if last is not None:
        rec["prev_seen"] = last["seen"].isoformat(timespec="milliseconds")
        rec["repeats"] = last["n"]
    _write(rec, now)
    with _lock:
        if _st["day"] == day:
            _st["last"][key] = {"fp": fp, "seen": t, "n": 0}


def syslog(ids, window_s, xmls: "list[str] | None", error: "BaseException | None" = None,
           now: "datetime | None" = None) -> None:
    """One read of the System log (shutdown.shutdown_event_xml): the events not yet on
    today's tape, or the read's failure (written again only once it changes)."""
    try:
        if _st["dir"] is None:
            return
        base = {"kind": "syslog", "ids": [int(i) for i in ids], "window_s": int(window_s)}
        if xmls is None:
            why = _err(error) if error is not None else "unreadable"
            _changed({**base, "error": why}, ("syslog-error",), why.split(":", 1)[0], now)
            return
        day = _now(now).strftime("%Y%m%d")
        shas = [_sha(x) for x in xmls]
        with _lock:
            seen = _st["events"] if _st["day"] == day else set()
            new = [x for x, h in zip(xmls, shas, strict=True) if h not in seen]
        if not new:
            return
        _write({**base, "events": new}, now)
        with _lock:
            if _st["day"] == day:
                _st["events"].update(shas)
                _st["last"].pop(("syslog-error",), None)
    except Exception as exc:  # noqa: BLE001 - recording never stops the relay
        _log_tape.debug("tape syslog: %s", exc)


log = logging.getLogger("ark.selfcheck")

AUTOMAS_TASK = "AUTO-MAS_AutoStart"
_is_file = os.path.isfile      # tests replace it: the launcher path is a Windows path


def _launcher_ok(value) -> bool:
    """Game.Path as automas_handover.py step 10b sets it: the Kuro launcher.exe that
    wuwa_launcher found, a file that exists (AUTO-MAS updates WuWa through it)."""
    return (isinstance(value, str) and PureWindowsPath(value).name.lower() == "launcher.exe"
            and _is_file(value))


# The update settings the switch-over handed AUTO-MAS (relay/handover/automas_handover.py
# steps 10a and 10b; the relay's own client updates were removed, da65e68d and a0a7b7f2):
# (script name, setting path, what it does in plain words, holds when).
HANDED_UPDATES = (
    ("MAA", "Run.IfCheckGameUpdate", "明日方舟开跑前查客户端有没有新版", lambda v: v is True),
    ("MAA", "Run.IfAutoInstallGameApk", "明日方舟有新版就自己装上", lambda v: v is True),
    ("OK-WW", "Game.Enabled", "鸣潮由调度程序开关游戏", lambda v: v is True),
    ("OK-WW", "Game.Path", "鸣潮官方启动器的位置", _launcher_ok),
    ("OK-WW", "Game.IfAutoUpdate", "鸣潮开跑前更新客户端", lambda v: v is True),
)
UPDATES_NAME = "调度程序还管着两个游戏客户端的更新（明日方舟、鸣潮）"


def _handed_updates_gaps(scripts: dict) -> list[str]:
    """The HANDED_UPDATES settings that are not as handed over, in plain words; [] when
    all hold. `scripts` is /api/scripts/get's data: {script id: {Info, Run, Game, ...}}."""
    by_name = {str((sc.get("Info") or {}).get("Name") or "").lower(): sc
               for sc in scripts.values() if isinstance(sc, dict)}
    gaps = []
    for script, path, words, holds in HANDED_UPDATES:
        sc = by_name.get(script.lower())
        if sc is None:
            gaps.append(f"{words}：调度程序里没有 {script} 这个脚本")
            continue
        value = sc
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if holds(value):
            continue
        if value is None:
            now = "读不到这一项"
        elif isinstance(value, bool):
            now = "开着" if value else "关着"
        elif path.endswith(".Path"):
            # The path itself is left out: a folder name like 「Wuthering Waves」 is English.
            now = "指的不是官方启动器，或者那个文件已经不在了" if value else "空着"
        else:
            now = f"现在是「{value}」"
        gaps.append(f"{words}：{now}")
    from ark_relay.core import mastercfg  # noqa: PLC0415
    for g in mastercfg.check_maaend_preupdate(None, scripts=scripts):
        if g not in gaps:
            gaps.append(g)
    return gaps


def _is_backend(cmd: str) -> bool:
    """True if a python.exe command line is AUTO-MAS's backend: main.py run from under
    the install root's \\automas\\ directory (the host keeper's rule, 083ebcef).

    "main.py" alone also matched OK-WW (`D:\\ark\\okww\\data\\apps\\ok-ww\\working\\main.py`,
    which may run as python.exe): a dead backend then passed this check while OK-WW ran."""
    low = (cmd or "").lower().replace("/", "\\")
    return "main.py" in low and "\\automas\\" in low


@dataclass
class Check:
    name: str      # plain language, shown in the alarm
    ok: "bool | None"   # None: cannot be judged because a check it depends on failed
    detail: str = ""


def _run_ok(cmd: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=25)
        return r.returncode == 0, f"退出码 {r.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}"


def _writable(d: "Path | None") -> tuple[bool, str]:
    if not d:
        return False, "没配置"
    try:
        Path(d).mkdir(parents=True, exist_ok=True)
        probe = Path(d) / ".selfcheck-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, ""
    except OSError as exc:
        return False, f"{type(exc).__name__}"


def _has_module(name: str) -> bool:
    import importlib.util  # noqa: PLC0415
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# Python packages the relay imports lazily, so a missing one fails only when the
# code that needs it runs: (import name, pip package, what it is used for).
NEEDED_MODULES = (("PIL", "Pillow", "读官方长图（卡池几点几分）、压缩报警截图"),)


VIRT_NAME = "雷电模拟器能用上硬件加速（系统没开「基于虚拟化的安全」）"
_VIRT_PS = ("$d = Get-CimInstance -Namespace root\\Microsoft\\Windows\\DeviceGuard -ClassName Win32_DeviceGuard "
            "-ErrorAction Stop; $c = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop; "
            "'VBS=' + $d.VirtualizationBasedSecurityStatus + ' HV=' + $c.HypervisorPresent")


def _virt_layer() -> str:
    """'VBS=<0|1|2> HV=<True|False>' as the machine answers (VirtualizationBasedSecurityStatus
    2 = running; HypervisorPresent True = some hypervisor holds VT-x). Read-only. PowerShell 7
    with the pre-update's hang guard (pwsh + Get-CimInstance answers in about half a second)."""
    from ark_relay.features.preupdate import _PWSH7, PWSH_GUARD_S  # noqa: PLC0415
    r = subprocess.run([str(_PWSH7), "-NoProfile", "-Command", _VIRT_PS],
                       capture_output=True, text=True, timeout=PWSH_GUARD_S,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (r.stdout or "").strip()


def _virt_check(read) -> Check:
    """The VIRT_NAME line from `read()`'s answer; not judged (None) when the machine cannot
    be asked, so a failed query is never an alarm."""
    try:
        out = read()
    except (OSError, subprocess.SubprocessError) as exc:
        return Check(VIRT_NAME, None, f"判不了：问系统没问出来（{type(exc).__name__}）")
    m = re.search(r"VBS=(\d)\s+HV=(\w+)", out or "")
    if not m:
        return Check(VIRT_NAME, None, "判不了：系统没答出来")
    if m.group(1) == "2":
        return Check(VIRT_NAME, False, "系统打开了「基于虚拟化的安全」：雷电只能走慢路，早上头一次冷开机从 20 多秒"
                     "拖到 70 多秒，还会弹「系统界面没有响应」挡住游戏。11-04 晚系统自己开过一次，关它要改系统的安全设置")
    if m.group(2).lower() == "true":
        return Check(VIRT_NAME, False, "有别的虚拟化软件占着硬件加速：雷电只能走慢路，冷开机会慢好几倍")
    return Check(VIRT_NAME, True)


def _why(procs_mod) -> str:
    why = procs_mod.last_failure()
    return f"（{why}）" if why else ""


def _live_automas_version() -> str:
    """The running AUTO-MAS's own version ('' when it cannot be asked)."""
    try:
        from ark_relay.features.preupdate import _live_version  # noqa: PLC0415
        return _live_version()
    except Exception:  # noqa: BLE001 - unknown: the items new in a version are not judged
        return ""


def _contract(cfg, contract=None, version: "str | None" = None) -> "tuple[Check, list[str]]":
    """(the check, its plain lines per feature that cannot be read) - every AUTO-MAS setting
    the relay reads is where it looks (mascontract.check).

    Not judged (None) when no file could tell: the settings folder or a file is unreadable
    (the queue line above covers that) and nothing was found missing, or the files hold no
    script, queue or plan at all. `contract` replaces mascontract.check in tests."""
    from ark_relay.core import mastercfg as mascontract  # noqa: PLC0415
    name = texts.MAS_CONTRACT_CHECK
    try:
        if contract is not None:
            res = contract(getattr(cfg, "automas_dir", None))
        else:
            res = mascontract.check(getattr(cfg, "automas_dir", None),
                                    _live_automas_version() if version is None else version)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return Check(name, False, f"核对时出了 {type(exc).__name__}"), []
    lines = texts.mas_contract_lines(res.missing)
    if res.missing:
        return Check(name, False, texts.mas_contract_detail(res)), lines
    if res.unreadable or not res.judged:
        return Check(name, None, "判不了：" + (
            texts.mas_contract_detail(res) if res.unreadable else "设置里一个脚本、队列都没有")), []
    return Check(name, True), []


def contract_check(cfg, contract=None) -> Check:
    """The self-check line for the AUTO-MAS settings the relay reads (_contract)."""
    return _contract(cfg, contract)[0]


def run(cfg, *, procs=None, mas_up=None, schedule=None, channels=None,
        run_ok=_run_ok, has_module=_has_module, contract=None, mas_waited: float = 0.0,
        virt=_virt_layer) -> list[Check]:
    """All checks, in the order they are reported. Dependencies are injectable for tests.

    `mas_waited`: seconds the boot step waited for AUTO-MAS to answer before this ran
    (boot_stages.await_backend); said in the not-answering line."""
    from ark_relay.features import commands  # noqa: PLC0415
    from ark_relay.core import plan, desktop as _procs  # noqa: PLC0415
    procs = procs or (lambda: _procs.python_processes(warn=False))
    mas_up = mas_up or commands.mas_up
    schedule = schedule or (lambda: plan.schedule(getattr(cfg, "automas_dir", None)))
    out: list[Check] = []

    ok, why = run_ok(["tasklist", "/NH"])
    out.append(Check("看得到机器上在跑哪些程序", ok, why))
    rows = procs()
    out.append(Check("读得到每个程序是怎么启动的（系统自带的那条路）", rows is not None,
                     "" if rows is not None else f"读不到{_why(_procs)}——看门狗只能靠调度程序有没有应答来判断，它退出时不会立刻察觉；"
                     "调度程序的后台程序在不在跑也就判不了"))
    up = bool(mas_up())
    out.append(Check("调度程序有应答", up, "开机后中继叫过它一次" + (
        f"，又等了 {mas_waited:.0f} 秒" if mas_waited else "") + "，仍然没有应答"))
    # Without the process table this cannot be judged (None), so an unreadable
    # table is one failure, not two.
    out.append(Check("调度程序的后台程序在跑", None if rows is None else any(_is_backend(c) for _, c in rows),
                     "判不了：程序列表读不到" if rows is None else "在跑的程序里没有它的后台"))
    ok, why = run_ok(["schtasks", "/query", "/tn", AUTOMAS_TASK])
    out.append(Check("调度程序的开机任务计划还在", ok, why))
    # Not answering is the line above's failure: this one cannot be judged then (None).
    if not up:
        out.append(Check(UPDATES_NAME, None, "判不了：调度程序没应答"))
    else:
        try:
            scripts_data = commands._mas("/api/scripts/get")["data"]
            gaps = list(_handed_updates_gaps(scripts_data))
            from ark_relay.core import mastercfg  # noqa: PLC0415
            for g in mastercfg.check_maaend_preupdate(getattr(cfg, "automas_dir", None), scripts=scripts_data):
                if g not in gaps:
                    gaps.append(g)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            out.append(Check(UPDATES_NAME, False, f"读不到调度程序的脚本设置（{type(exc).__name__}）"))
        else:
            out.append(Check(UPDATES_NAME, not gaps, "；".join(gaps) + (
                "——这个游戏出新版时没人更新客户端" if gaps else "")))
    try:
        sched = schedule()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        sched = None
        why = f"{type(exc).__name__}"
    else:
        why = "" if sched else "没有一条开着定时的队列"
    out.append(Check("队列的排期读得到、至少一条开着定时", bool(sched), why))
    out.append(contract_check(cfg, contract))
    log_file = os.environ.get("ARK_LOG_FILE", "")
    ok, why = (False, "没配置") if not log_file else _writable(Path(log_file).parent)
    out.append(Check("日志文件所在目录能写", ok, why))
    ok, why = _writable(getattr(cfg, "state_dir", None))
    out.append(Check("状态目录能写", ok, why))
    hist = getattr(cfg, "history_dir", None)
    out.append(Check("调度程序的历史目录在", bool(hist) and Path(hist).is_dir(),
                     "" if hist else "没配置"))
    chans = channels() if channels else []
    out.append(Check("至少一条通知通道配好了", bool(chans), "一条都没配，报警发不出去"))
    out.append(Check("手机通道配好了", bool(getattr(cfg, "phone_topic", "") and getattr(cfg, "phone_pin", "")),
                     "手机页会一直显示关机"))
    for mod, pkg, used in NEEDED_MODULES:
        out.append(Check(f"中继装了读图组件（{used}）", bool(has_module(mod)),
                         f"没装：用中继那份 python.exe 跑 pip install {pkg}"))
    out.append(_virt_check(virt))
    return out


def _push(notifier, title: str, body: str) -> dict:
    """Send a failure to the group; the `extra` that marks the WARNING lines logged after it
    as delivered (errwatch.group_pushed), so errwatch does not push them a second time."""
    errs = notifier.send(title, body, alert=True)
    from ark_relay.features import errwatch  # noqa: PLC0415
    return errwatch.group_pushed(title, errs, notifier)


def report_contract(cfg, notifier, version: str, log_=None, contract=None) -> Check:
    """Right after the pre-update installed a new AUTO-MAS (preupdate_automas.run_automas's
    after_update): check the settings the relay reads again and push a miss to the group.

    The boot self-check runs before the pre-update (boot_stages: _stage_selfcheck, then
    _stage_preupdate), so on 10-14 the 08:45 boot check passed on the old AUTO-MAS and the
    08:46 install went unchecked until the next boot."""
    lg = log_ or log
    c, lines = _contract(cfg, contract, version)
    if c.ok is False:
        lines = lines or [c.detail]
        extra = _push(notifier, texts.AUTOMAS_CONTRACT, texts.automas_contract_body(version, lines))
        lg.warning("调度程序升级到 %s 后，%s：%s", version, c.name, c.detail, extra=extra)
    elif c.ok is None:
        # At boot the queue line covers unreadable files; after an update nothing else looks
        # again until the next boot, so this goes out (errwatch pushes WARNINGs to the group).
        lg.warning("调度程序升级到 %s 后，核对「%s」%s", version, c.name, c.detail)
    else:
        lg.info("调度程序升级到 %s 后，%s：成立", version, c.name)
    return c


def report(cfg, notifier, log_=None, mas_waited: float = 0.0) -> list[Check]:
    """Run, log every line, push the failures to the group. Returns the checks."""
    lg = log_ or log
    try:
        checks = run(cfg, channels=lambda: list(getattr(notifier, "channels", []) or []),
                     mas_waited=mas_waited)
    except Exception:  # noqa: BLE001 - the self-check itself must not take the boot down
        lg.exception("开机自检自己出错")
        return []
    bad = [c for c in checks if c.ok is False]
    pushed = {}
    if bad:
        # The ✗ lines logged below repeat this alarm (see _push).
        pushed = _push(notifier, texts.SELFCHECK_FAILED, texts.selfcheck_failed_body(
            len(checks), [(c.name, c.detail) for c in bad]))
    for c in checks:
        mark = "✓" if c.ok else "✗" if c.ok is False else "？"
        lg.log(logging.WARNING if c.ok is False else logging.INFO, "开机自检 %s %s%s",
               mark, c.name, f"：{c.detail}" if (c.detail and not c.ok) else "",
               extra=pushed if c.ok is False else None)
    if not bad and all(c.ok for c in checks):
        lg.info("开机自检 %d 项全部成立", len(checks))
    return checks


# ---------- the daily report's 「中继体检」 lines ----------

_TS = re.compile(r"^(\d\d-\d\d) (\d\d:\d\d):\d\d (\w+)\s+(\S+)\s+(.*)$")
# A start that ends on purpose before the AUTO-MAS step: the self-update restart
# (boot_stages._stage_selfupdate / app_main.SELF_UPDATE_LINE) and a stop that came
# in mid-boot (service.ArkRelayService._stop_in_boot).
_SELF_UPDATE = ("代码已更新，重启以立即生效", "代码已更新，切到新版本文件夹并重启")
_BOOT_STOP = "开机还没走完就收到停止"


def daily_lines(day: str, log_text: str) -> list[str]:
    """What the sign-off check used to need a person for, from the day's relay.log.

    The after-shift check's line for each shift that day (shiftcheck.py) is quoted
    after the two lines below.

    `day` is YYYY-MM-DD; the log carries MM-DD stamps. ERROR lines are counted
    and the first one quoted (when it reads as plain language); every boot's
    AUTO-MAS start-up is summarised: came up by itself, had to be killed and
    relaunched, or never came up.
    """
    md = day[5:]
    errors: list[tuple[str, str, str]] = []
    boots: list[str] = []
    shifts: list[str] = []      # the after-shift check's one line per shift (shiftcheck.py)
    pending = ""
    reached = False
    for line in log_text.splitlines():
        m = _TS.match(line)
        if not m or m.group(1) != md:
            continue
        hhmm, level, name, msg = m.group(2), m.group(3), m.group(4), m.group(5)
        if level == "ERROR":
            errors.append((hhmm, name, msg))
        if name == "ark.shiftcheck" and msg.startswith(texts.SHIFTCHECK_HEAD):
            shifts.append(msg)
            continue
        if msg.startswith("服务模式启动"):
            if pending:
                boots.append(f"{pending} " + ("开机时已经在" if reached else "中继刚启动就停了，还没看调度程序在不在"))
            pending = hhmm
            reached = False
            continue
        if msg.startswith("开机自检"):
            reached = True
        if pending and not reached and msg.startswith(_SELF_UPDATE):
            boots.append(f"{pending} 装新版后自己重启了")
            pending = ""
            continue
        if pending and not reached and msg.startswith(_BOOT_STOP):
            boots.append(f"{pending} 开机还没走完就被叫停了")
            pending = ""
            continue
        n_before = len(boots)
        # The four outcomes ensure_automas logs (boot_stages.py), matched on
        # the parts of each line that are not engineering words.
        if "自己起来了（等了" in msg:
            boots.append(f"{hhmm} 自己起来了{msg[msg.index('（'):]}")
        elif "杀掉重" in msg:
            boots.append(f"{hhmm} 等不到，杀掉重开")
        elif "秒内" in msg and "仍不通" in msg:
            boots.append(f"{hhmm} 重开后还是没应答")
        elif msg.startswith("AUTO-MAS 已") and msg.endswith("秒）"):
            boots.append(f"{hhmm} 重开后起来了{msg[msg.index('（'):]}")
        if len(boots) > n_before:
            pending = ""
    if pending:
        boots.append(f"{pending} 开机时已经在")
    out = []
    if errors:
        hhmm, name, msg = errors[0]
        part = texts.relay_part(name)
        said = (f"它说：{msg[:80]}" if not texts.plain(msg[:80])
                else f"原因：{c}，原文已记日志" if (c := texts.fault_cause(msg[:240]))
                else texts.RELAY_ERROR_UNREAD)
        out.append(f"· 中继今天报错 {len(errors)} 条，第一条 {hhmm} 出在「{part}」：{said}")
    else:
        out.append("· 中继今天没有报错")
    out.append("· 调度程序开机：" + ("；".join(boots) if boots else "开机时已经在"))
    out += [f"· {x}" for x in shifts]
    return out


def daily_section(day: str, log_file: "str | None" = None) -> str:
    """The section appended to the daily report; '' when no log is configured.

    An unreadable log still gives the section, saying so (left out, it would read
    as "nothing to say")."""
    path = log_file or os.environ.get("ARK_LOG_FILE", "")
    if not path:
        return ""
    from ark_relay.core.statestore import tail_bytes  # noqa: PLC0415
    try:
        # 8 MB of bytes always holds the last 2 M characters (UTF-8 is at most 4
        # bytes each), and reaches into relay.log.1 after a rotation (logfile.py).
        text = tail_bytes(path, 8_000_000)[0].decode("utf-8", errors="replace")[-2_000_000:]
    except OSError as exc:
        # The report line is plain words; the exception stays in the log.
        log.warning("日报的中继体检读不了 %s：%s: %s", path, type(exc).__name__, exc)
        why = ("文件不在" if isinstance(exc, FileNotFoundError)
               else "被占用或没有权限" if isinstance(exc, PermissionError) else "打不开")
        return f"中继体检\n· 中继日志读不到（{why}）"
    return "中继体检\n" + "\n".join(daily_lines(day, text))


# A relay.log line: 「MM-DD HH:MM:SS LEVEL  ark.name  message」. LEVEL is padded
# with spaces to the width of WARNING; the name is always an ark.* logger. The
# bare 「diag:」 and traceback lines have no leading timestamp and are skipped.
_LINE = re.compile(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+(WARNING|ERROR)\s+(ark\.[\w.]+)\s+(.*)$")

_CAL_MISS = re.compile(r"^鸣潮 (\S+) 版本活动日历读了 \d+ 行，没找到「(.+?)」的日期：(.*)$")
_CAL_IMG = re.compile(r"^这条公告只有图，没读到字：.*activity id=(\d+)「(\S+?)版本活动日历」(\S+)")
_CAL_FAIL = re.compile(r"^鸣潮版本活动日历读图失败")
_MC2 = re.compile(r"^🔬 上机核对没过：#2\b")
_SNAP = re.compile(r"^快照的 (_MAS错误|_队列错误) 这一段读不到")


class _Taken(list):
    """The records the real errwatch handler would queue for the group."""


def _handler(state_dir: Path):
    """A real ErrorKindAlert whose queue is this list: a record that reaches _take is a push."""
    from ark_relay.features import errwatch  # noqa: PLC0415

    class _NoSend:
        def send(self, *_a, **_k):
            return []

    h = errwatch.ErrorKindAlert(_NoSend(), state_dir=state_dir, known={})
    taken = _Taken()
    h._take = lambda record: taken.append(record)
    return h, taken


def _replay_calendar(miss: "re.Match | None", img: "re.Match | None") -> None:
    """The 10-06 06:20:17 calendar read again, as this version runs it: another source
    (the first banner's end + 1 min) had already given the second half's time, so
    _wuwa_second_half passes notes=None. The image reader returns the 78 OCR lines
    the log quoted. Then machine check #2 judges the trace through judge()."""
    from types import SimpleNamespace  # noqa: PLC0415

    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
    from ark_relay.features import banners as hub  # noqa: PLC0415
    from ark_relay.features import machinecheck as mc  # noqa: PLC0415

    ver = (miss and miss.group(1)) or (img and img.group(2)) or "3.7"
    pool = (miss and miss.group(2)) or "余心所向九死未悔"
    nid = (img and img.group(1)) or "50868"
    url = (img and img.group(3)) or "https://example.invalid/cal.png"
    words = (miss.group(3).split(" / ") if miss else [])
    ocr = [SimpleNamespace(text=w, x=0, y=40 * i, w=10 * len(w), h=30) for i, w in enumerate(words)]
    notice = {"activity": [{"id": nid, "tabTitle": f"{ver}版本活动日历", "startTimeMs": "1790712000000",
                            "content": f'<p><img src="{url}" alt="" width="1080" height="2159"></p>'}]}
    now = datetime(2026, 10, 6, 6, 20, 17, tzinfo=SERVER_TZ).replace(tzinfo=None)
    end = datetime(2026, 10, 22, 9, 59)
    tr = hub.Trace.new()
    hub._wuwa_calendar_start(notice, pool, now, end, lambda _url: ocr, None, tr)
    mc.load()
    only = {"#2": mc.CHECKS["#2"]}
    saved = dict(mc.CHECKS)
    mc.CHECKS.clear()
    mc.CHECKS.update(only)
    try:
        with tempfile.TemporaryDirectory() as td:
            mc.judge(td, "banners", {"trace": tr, "now": now}, notifier=None)
    finally:
        mc.CHECKS.clear()
        mc.CHECKS.update(saved)


def _replay_snapshot(labels: "set[str]") -> None:
    """The 10-06 06:21 snapshot read again, as this version runs it: the relay's own
    power-off is under way (what boot_stages wires into errwatch), and the AUTO-MAS
    sections that failed then fail the same way (its backend being torn down)."""
    from ark_relay.features import errwatch  # noqa: PLC0415
    from ark_relay.features import snapshot  # noqa: PLC0415

    def refused(_out):
        raise ConnectionRefusedError("AUTO-MAS backend going away")

    names = {"_MAS错误": "_mas", "_队列错误": "_queues"}
    saved = {n: getattr(snapshot, n) for n in ("_mas", "_queues", "_okww", "_runtime")}
    probe = errwatch._relay_poweroff[0]
    try:
        for label, n in names.items():
            setattr(snapshot, n, refused if label in labels else (lambda _out: None))
        snapshot._okww = snapshot._runtime = lambda _out: None
        errwatch._relay_poweroff[0] = lambda: True
        snapshot.read()
    finally:
        errwatch._relay_poweroff[0] = probe
        for n, fn in saved.items():
            setattr(snapshot, n, fn)


def okww_pushes(text: str, *, expect_nest: bool = False, expect_daily: bool = True,
                expect_stamina: bool = True, only_nest: str = "") -> list[str]:
    """The group pushes ``outcome.okww_checks`` would send for one OK-WW run log.

    Defaults match ``okww_checks``: daily and stamina are expected, no nest
    filter. Each entry is the paragraph ``outcome.summarize`` would push (which
    starts 「OK-WW 这一轮有 … 项没干成」); an empty list means the run is green."""
    from ark_relay.features.outcome import okww_checks, summarize  # noqa: PLC0415

    msg = summarize(okww_checks(text, expect_nest=expect_nest, expect_daily=expect_daily,
                                expect_stamina=expect_stamina, only_nest=only_nest), "OK-WW")
    return [msg] if msg else []


def errwatch_pushes(text: str) -> list[dict]:
    """The group pushes errwatch would send for the WARNING / ERROR lines of a relay.log.

    Each entry is ``{where, line, lineno}``. A line of a known 10-06 false alarm
    is replaced by what its producer, run again now under the real errwatch
    handler, pushes (lineno = the first source line of that producer, line =
    what this version would log); every other line pushes as written."""
    out: list[dict] = []
    cal: dict[str, "re.Match"] = {}
    cal_at = 0
    snap: set[str] = set()
    snap_at = 0
    for i, line in enumerate(text.splitlines(), 1):
        m = _LINE.match(line)
        if m is None:
            continue
        name, msg = m.group(2), m.group(3)
        if name == "ark.banners" and (hit := _CAL_MISS.match(msg) or _CAL_IMG.match(msg) or _CAL_FAIL.match(msg)):
            cal.setdefault(hit.re.pattern, hit)
            cal_at = cal_at or i
        elif name == "ark.phone_banners" and _MC2.match(msg):
            cal_at = cal_at or i
        elif name == "ark.snapshot" and (hit := _SNAP.match(msg)):
            snap.add(hit.group(1))
            snap_at = snap_at or i
        else:
            out.append({"where": name, "line": msg, "lineno": i})
    runs = []
    if cal_at:
        runs.append((cal_at, lambda: _replay_calendar(cal.get(_CAL_MISS.pattern), cal.get(_CAL_IMG.pattern))))
    if snap_at:
        runs.append((snap_at, lambda: _replay_snapshot(snap)))
    if runs:
        from ark_relay.features import errwatch  # noqa: PLC0415
        ark = logging.getLogger(errwatch.ARK)   # where boot_stages installs the handler
        with tempfile.TemporaryDirectory() as td:
            h, taken = _handler(Path(td) / "state")
            ark.addHandler(h)
            try:
                for at, run in runs:
                    before = len(taken)
                    run()
                    out += [{"where": r.name, "line": r.getMessage().splitlines()[0] if r.getMessage() else "",
                             "lineno": at} for r in taken[before:]]
            finally:
                ark.removeHandler(h)
    return sorted(out, key=lambda p: p["lineno"])


def _is_okww(path: str) -> bool:
    # The checked-in fixture is 「okww-1006-run.log」 and the evidence package's own
    # name is 「OK-WW-…」: both are OK-WW run logs (an exact 「OK-WW」 test missed the
    # fixture, so the deploy gate replayed it as a relay.log and found nothing).
    return re.search(r"ok-?ww", Path(path).name, re.I) is not None


def _pushed(path: str) -> list[str]:
    """The pushes replaying one file would send, as printable lines with their source."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"{path}: 读不了：{exc}"]
    if _is_okww(path):
        return [f"{path} → {push.splitlines()[0]}" for push in okww_pushes(text)]
    return [f"{path}:{p['lineno']} {p['where']}: {p['line'][:160]}" for p in errwatch_pushes(text)]


def main(argv: list[str]) -> int:
    """Replay the given log files; print every push with its source; 1 when any push."""
    pushed: list[str] = []
    for path in argv:
        pushed += _pushed(path)
    if pushed:
        for line in pushed:
            print(line)
        print(f"{len(pushed)} 条会推进群", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
