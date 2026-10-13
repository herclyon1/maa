"""A daily text tape of the inputs the day pull cannot reconstruct (daysim W8).

The day replay (relay/tests/daysim) rebuilds a Beijing day from what the machine
keeps anyway: relay.log, AUTO-MAS's history and app.log, the game logs. Four kinds of
input leave no trace there, so the replay had to make them up (design.md section 4:
"a synthesized input can be wrong exactly where a bug hides"):

    mas     what the AUTO-MAS backend answered (phone/mas_client.mas_post and the
            engine's runtime-snapshot)
    syslog  the System log events the relay read (shutdown.shutdown_event_xml:
            1074 / 1075 power-off requests and cancels, 566, 6005)
    web     what the information sources answered (maintenance notices, Endfield's
            update hint, the banner sources)
    config  AUTO-MAS's QueueConfig / ScriptConfig / PlanConfig as the relay found them
            when a day's tape begins (the first boot of the day, or midnight)

One JSON object per line in <state>/tape/<Beijing YYYYMMDD>.jsonl, each with `t`
(Beijing time, ms) and `kind`; relay/tests/daysim/slice.py turns a pulled tape into
replay events. What is written is what the relay received: the status, the body (as
`json` when it parses, else `text`; past BODY_CAP only an `excerpt` with `cut`), its
length and the sha256 of the whole received bytes. An answer identical to the last one
recorded today for the same request is not written again; the next different one
carries `prev_seen` (when the old answer was last received) and `repeats` (how often).

Never in the way of the relay: every entry point swallows any exception (debug log
only), a line is appended and the file closed again under one lock, nothing here sends
or pushes anything, and no decision ever reads the tape. Until install() names the
state folder (boot_stages._stage_bootstrap) every call is a no-op, so tests and tools
that use the hooked functions write nothing. Past DAY_CAP_BYTES a day gets one
`truncated` line and nothing more; day files older than KEEP_DAYS are deleted here.

Secrets are masked before anything is written, with the repo's own rules (the relay
itself has none: the evidence uploads ship relay.log as it is): the shapes in
SECRET_PATTERNS (relay/tests/daysim/slice.py takes them from here), key-name masking of
JSON values (KEY_HINTS / KEY_ALLOW, the lists of scripts/mac/redact.py) and the game
UID label of lint-repo.sh item 12 (masked like relay/tests/daysim/pack.mask_uid).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("ark.tape")

BEIJING = timezone(timedelta(hours=8))
DIR = "tape"
# A day's tape stops at this size. Measured 2026-10-14 by replaying the seven recorded
# days (10-06 .. 10-13, relay/tests/daysim/run.py --all --keep) with the hooks in place:
# 448-458 KB a day, 94 % of it information-source answers (test_tape.py lists each day).
# The cap is nine times that, for a day whose AUTO-MAS answers change far more often
# than the replay's; 14 full days are 56 MB.
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
# scripts/mac/redact.py SECRET_KEY_HINTS / SECRET_KEY_ALLOW (test_tape.py keeps them equal).
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
        log.debug("tape install: %s", exc)


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
                log.debug("tape: cannot delete %s: %s", p, exc)


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
    out = []
    for name in CONFIG_FILES:
        p = base / "config" / name
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
        log.debug("tape %s %s: %s", kind, where, exc)


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
        log.debug("tape syslog: %s", exc)
