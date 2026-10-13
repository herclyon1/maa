"""The machine at D 00:00 for one replayed day: relay/tests/daysim/days/<D>/seed.json.

Gate (independent) mode of design.md section 2 ("Seed state"): the relay's real state
files dated before D, files nothing touched after D 00:00, the logs as they stood at
00:00 (byte prefixes of the corpus copies), and what only exists as of the pull rebuilt:

* state.json - the pull's copy minus everything stamped at or after D 00:00, with
  `modes` (debug_until, skip_next_shutdown, shutdown_skipped), the inbox version and
  the code version replayed from relay.log lines before 00:00.
* test-windows.json, relay-dispatches.json, estop-windows.json, phone-receipts.json -
  the entries that began before 00:00 (an entry still open then has until = null).

Every removal is listed under state_json.dropped, every guess under uncertain, so a
reviewer sees exactly what is reconstructed. Called by slice.py (build) with its Day.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta

import slice as sl

# Evidence folders older than this many days before D are left out of the seed (the
# relay only reads the last runs' folders; its 30-day cleanup just counts them).
EVIDENCE_KEEP_DAYS = 3
REBUILT = ("state.json", "test-windows.json", "relay-dispatches.json", "estop-windows.json",
           "phone-receipts.json")
DATE_IN_NAME = re.compile(r"(20\d\d)-?(\d\d)-?(\d\d)")


# ------------------------------------------------------------------ times inside state values
def as_time(v, year: int) -> "float | None":
    """A state value that names a moment -> unix time; None when it is not one."""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 1.5e9 < v < 2.2e9:
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip()
    if re.fullmatch(r"\d{12}", s):                              # boot id 202610131123
        return datetime.strptime(s, "%Y%m%d%H%M").replace(tzinfo=sl.BJ).timestamp()
    if re.fullmatch(r"\d\d-\d\d \d\d:\d\d", s):                  # receipts "10-12 12:05"
        return sl.parse_when(s, year)
    if re.match(r"\d{4}-\d\d-\d\d", s):
        try:
            dt = datetime.fromisoformat(s.split("|")[0])
        except ValueError:
            m = re.match(r"(\d{4}-\d\d-\d\d)", s)
            dt = datetime.fromisoformat(m.group(1))
        return (dt if dt.tzinfo else dt.replace(tzinfo=sl.BJ)).timestamp()
    return None


def key_date(key: str) -> "str | None":
    m = DATE_IN_NAME.search(key)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


TIME_FIELDS = ("at", "since", "started", "day", "boot", "start", "sent", "when")
# A run id as the relay keeps it (seen.txt, machinecheck-runs.json): <dirdate>/<user>/<stem>,
# the stem ending in the UTC+4 start time HH-MM-SS (collector.AUTOMAS_NAME_TZ).
RUN_ID = re.compile(r"^(\d{4}-\d\d-\d\d)/[^/\s]+/(?:\S*-)?(\d\d)-(\d\d)-(\d\d)$")


def run_id_time(s) -> "float | None":
    m = RUN_ID.match(s) if isinstance(s, str) else None
    if not m:
        return None
    d, hh, mi, ss = m.groups()
    try:
        return datetime.strptime(f"{d} {hh}:{mi}:{ss}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=sl.UTC4).timestamp()
    except ValueError:
        return None


def stamped_after(v, ctx) -> bool:
    """A record (dict with a time field) or run id that belongs at/after t0."""
    if isinstance(v, dict):
        return any((t := as_time(v.get(f), ctx.year)) is not None and t >= ctx.t0 for f in TIME_FIELDS)
    t = run_id_time(v)
    return t is not None and t >= ctx.t0


def strip_after(obj, path: str, ctx, dropped: list):
    """Drop dict keys dated D or later and records stamped at/after t0, recursively."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            p = f"{path}.{k}"
            kd = key_date(str(k))
            if kd and kd >= ctx.day:
                dropped.append(p)
                continue
            if isinstance(v, dict) and stamped_after(v, ctx):
                dropped.append(p)
                continue
            if not isinstance(v, (dict, list)) and (t := as_time(v, ctx.year)) is not None and t >= ctx.t0:
                dropped.append(p)
                continue
            out[k] = strip_after(v, p, ctx, dropped)
        return out
    if isinstance(obj, list):
        keep = []
        for i, v in enumerate(obj):
            if stamped_after(v, ctx):
                dropped.append(f"{path}[{i}]")
                continue
            keep.append(strip_after(v, f"{path}[{i}]", ctx, dropped))
        return keep
    return obj


# ------------------------------------------------------------------ modes from relay.log
# The lines modes.py's callers log when a mode changes (service.py phone/inbox results,
# engine.py, shutdown.py). Matched outside machinecheck/notify, which quote them.
DEBUG_ON = re.compile(r"调试模式已开启，至 (\d\d-\d\d \d\d:\d\d)")
SKIPPED_DEBUG = re.compile(r"^🔧 调试模式：这一次关机已跳过（([^）]+)）")
SKIPPED_MARK = re.compile(r"^⏸ 「下次跑完不关机」用掉了：这一次关机跳过（([^）]+)）")
INBOX_V = re.compile(r"^收到待办 v(\d+)")


def replay_modes(recs: list, ctx) -> "tuple[dict, dict]":
    """(modes, facts) as of t0 from the relay.log lines before it."""
    modes: dict = {}
    facts: dict = {"inbox_version": None, "code": None, "phone_ids_after_t0": []}
    for r in recs:
        if r.t >= ctx.t0:
            if r.logger == "ark.phone" and (m := sl.PHONE.match(r.msg)):
                facts["phone_ids_after_t0"].append(m.group(4))
            continue
        if r.logger in ("ark.machinecheck", "ark.notify"):
            continue
        msg = r.msg
        if (m := DEBUG_ON.search(msg)) and r.logger == "ark.service":
            t = sl.parse_when(m.group(1), ctx.year)
            modes["debug_until"] = datetime.fromtimestamp(t, sl.BJ).strftime("%Y-%m-%d %H:%M")
        elif ("调试模式已关闭" in msg and r.logger == "ark.service") or \
                (msg.startswith("🔧 调试模式已结束") and r.logger == "ark.engine"):
            if modes.pop("debug_until", None) is not None and "已关闭" in msg:
                # set_debug(off) also clears the skip debug mode wrote (modes.DEBUG_SKIP_TAG).
                if str(modes.get("shutdown_skipped", "")).endswith("|debug"):
                    modes.pop("shutdown_skipped")
        if r.logger == "ark.service" and ("已记下「下次跑完不关机」" in msg or "下一次跑完不关机（只跳过这一次" in msg):
            modes["skip_next_shutdown"] = True
        elif r.logger == "ark.service" and ("已取消，跑完照常关机" in msg or "已撤回还没用上的「下次跑完不关机」" in msg
                                            or (msg.startswith("待办: ✅") and "取消「下次跑完不关机」" in msg)):
            modes.pop("skip_next_shutdown", None)
        elif r.logger == "ark.shutdown" and msg.startswith("⏸ 有人按了「这次别关机」，本次关机已跳过"):
            # Builds before 10-12 spent the mark this way (relay.log 09-26 21:47:30 -> 21:48:00).
            modes.pop("skip_next_shutdown", None)
        elif r.logger == "ark.shutdown" and (m := SKIPPED_MARK.match(msg)):
            modes.pop("skip_next_shutdown", None)
            modes["shutdown_skipped"] = m.group(1)
        elif r.logger == "ark.shutdown" and (m := SKIPPED_DEBUG.match(msg)):
            modes["shutdown_skipped"] = m.group(1) + "|debug"
        if r.logger == "ark.inbox" and (m := INBOX_V.match(msg)):
            facts["inbox_version"] = m.group(1)
        if r.logger == "ark.service" and (m := sl.VERSION.match(msg)):
            facts["code"] = m.group(1)
    return modes, facts


def iso_week(t: float) -> str:
    y, w, _ = datetime.fromtimestamp(t, sl.BJ).isocalendar()
    return f"{y}-W{w:02d}"


def rebuild_state_json(ctx, raw: dict) -> "tuple[dict, dict]":
    dropped: list = []
    uncertain: list = []
    st = {}
    modes, facts = replay_modes(ctx.recs, ctx)
    for sec, body in raw.items():
        if sec == "modes":
            continue
        st[sec] = strip_after(body, sec, ctx, dropped) if isinstance(body, (dict, list)) else body
    st["modes"] = modes
    q = st.setdefault("queues", {})
    if facts["inbox_version"]:
        q["inbox_version"] = facts["inbox_version"]
    elif "inbox_version" in q:
        uncertain.append("queues.inbox_version (no 收到待办 line before t0)")
    after = set(facts["phone_ids_after_t0"])
    if isinstance(q.get("phone_seen"), list) and after:
        q["phone_seen"] = [i for i in q["phone_seen"] if i not in after]
        dropped.append(f"queues.phone_seen ids received after t0: {sorted(after)}")
    v = st.setdefault("versions", {})
    if facts["code"]:
        v["code"] = facts["code"]
        v["announced"] = facts["code"]
    for k in ("announced_notes",):
        if k in v:
            v.pop(k)
            uncertain.append(f"versions.{k} (only the pull's text exists)")
    week_d = iso_week(ctx.t0)
    monday = datetime.fromtimestamp(ctx.t0, sl.BJ).isoweekday() == 1
    for name, rec in (st.get("weekly") or {}).items():
        dw = rec.get("done_week") if isinstance(rec, dict) else None
        if not dw:
            continue
        if dw > week_d or (dw == week_d and monday):
            rec.pop("done_week")
            dropped.append(f"weekly.{name}.done_week={dw} (not done before {ctx.day} 00:00)")
        elif dw == week_d:
            uncertain.append(f"weekly.{name}.done_week={dw} (done this week; maybe after 00:00)")
    for k in list((st.get("marks") or {})):
        if k.startswith("banner:"):
            uncertain.append(f"marks.{k} (send time not recorded; kept)")
    return st, {"modes": modes, "dropped": dropped, "uncertain": uncertain}


def entries_before(ctx, data, fields: tuple) -> "tuple[list, list]":
    """List-of-dict state files: keep entries that began before t0; an entry that ended
    after t0 is reopened (until/end = null)."""
    keep, dropped = [], []
    for i, e in enumerate(data if isinstance(data, list) else []):
        begin = as_time(e.get(fields[0]), ctx.year) if isinstance(e, dict) else None
        if begin is None or begin >= ctx.t0:
            dropped.append(i)
            continue
        e = dict(e)
        if len(fields) > 1 and (end := as_time(e.get(fields[1]), ctx.year)) is not None and end >= ctx.t0:
            e[fields[1]] = None
        keep.append(e)
    return keep, dropped


# ------------------------------------------------------------------ files
def derived(ctx, rel: str, data: bytes, mtime: float) -> dict:
    return ctx.write(f"derived/{rel}", data, mtime, rel, "rebuilt")


def seed_mtime(ctx, mt: float) -> "tuple[float, bool]":
    return (mt, False) if mt < ctx.t0 else (ctx.t0 - 1, True)


def state_files(ctx, out: list, info: dict) -> None:
    base = ctx.dd / sl.STATE
    lo = (datetime.strptime(ctx.day, "%Y-%m-%d") - timedelta(days=EVIDENCE_KEEP_DAYS)).strftime("%Y-%m-%d")
    omitted_evidence = set()
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        sub = str(p.relative_to(base))
        rel = f"{sl.STATE}/{sub}"
        if sub.startswith("desktop/"):
            continue                                   # slice.do_desktop / fake_desktop
        if sub.startswith("tape/"):
            continue                                   # slice.do_tape; the relay never reads it
        mt = p.stat().st_mtime
        if sub in REBUILT:
            continue
        kd = key_date(sub)
        if kd:
            if kd >= ctx.day:
                continue
            if sub.startswith("evidence/") and kd < lo:
                omitted_evidence.add(sub.split("/")[1])
                continue
            ref = ctx.put(rel)
            ent = {"path": sl.machine(rel), **ref}
            if mt >= ctx.t0:
                ent["modified_after_t0"] = True
            out.append(ent)
        elif mt < ctx.t0:
            out.append({"path": sl.machine(rel), **ctx.put(rel)})
        elif (ref := rebuild_undated(ctx, rel, p, info)) is not None:
            out.append({"path": sl.machine(rel), **ref, "rebuilt": True})
        else:
            info["unknown_at_t0"].append(sl.machine(rel))
    if omitted_evidence:
        info["notes"].append(f"{len(omitted_evidence)} evidence folders older than {lo} left out")
    # The rebuilt ones.
    sp = base / "state.json"
    if sp.exists():
        raw = json.loads(sp.read_text(encoding="utf-8-sig"))
        st, how = rebuild_state_json(ctx, raw)
        rel = f"{sl.STATE}/state.json"
        data = (json.dumps(st, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        ref = derived(ctx, rel, data, ctx.t0 - 1)
        out.append({"path": sl.machine(rel), **ref, "rebuilt": True})
        info["state_json"] = {"path": sl.machine(rel), **ref, **how}
    for name, fields in (("test-windows.json", ("since", "until")), ("relay-dispatches.json", ("at",)),
                         ("estop-windows.json", ("start", "end")), ("phone-receipts.json", ("at",))):
        p = base / name
        if not p.exists():
            continue
        try:
            data = json.loads(sl.redact_bytes(p.read_bytes()).decode("utf-8-sig"))
        except ValueError:
            info["unknown_at_t0"].append(sl.machine(f"{sl.STATE}/{name}"))
            continue
        keep, dropped = entries_before(ctx, data, fields)
        if not keep and not dropped:
            continue
        rel = f"{sl.STATE}/{name}"
        mt, _ = seed_mtime(ctx, p.stat().st_mtime)
        if dropped:
            ref = derived(ctx, rel, (json.dumps(keep, ensure_ascii=False) + "\n").encode("utf-8"), mt)
            info["rebuilt"][name] = {"kept": len(keep), "dropped_entries": dropped}
        else:
            ref = ctx.put(rel)
        out.append({"path": sl.machine(rel), **ref, **({"rebuilt": True} if dropped else {})})
        if name == "test-windows.json":
            info["test_windows"] = keep


def tech_files(ctx, out: list) -> None:
    """tech/<date>.md, the technical log the relay writes per day (techlog.py)."""
    base = ctx.dd / sl.RELAY_HOME / "tech"
    for p in sorted(base.glob("*")) if base.is_dir() else []:
        kd = key_date(p.name)
        if p.is_file() and kd and kd < ctx.day:
            out.append({"path": sl.machine(f"{sl.RELAY_HOME}/tech/{p.name}"),
                        **ctx.put(f"{sl.RELAY_HOME}/tech/{p.name}")})


def rebuild_undated(ctx, rel: str, p, info: dict) -> "dict | None":
    """A state file without a date in its name that changed after t0: keep what is
    stamped before t0 (seen.txt run ids, JSON records, JSONL lines). Values inside a
    kept record may still be newer (counters), so the result is marked approximate.
    None when the file as a whole is stamped after t0 or has no stamps to go by."""
    raw = sl.redact_bytes(p.read_bytes())
    name = rel.rsplit("/", 1)[-1]
    dropped: list = []
    if name == "seen.txt":
        lines = raw.decode("utf-8-sig").splitlines()
        keep = [x for x in lines if not stamped_after(x.strip(), ctx)]
        dropped = [len(lines) - len(keep)]
        data = ("\n".join(keep) + "\n").encode("utf-8")
    elif name.endswith(".jsonl"):
        keep = []
        for line in raw.decode("utf-8-sig").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                return None
            (dropped if stamped_after(rec, ctx) else keep).append(line)
        dropped = [len(dropped)]
        data = ("\n".join(keep) + "\n").encode("utf-8") if keep else b""
    elif name.endswith(".json"):
        try:
            obj = json.loads(raw.decode("utf-8-sig"))
        except ValueError:
            return None
        if stamped_after(obj, ctx):
            return None
        obj = strip_after(obj, name, ctx, dropped)
        data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    else:
        return None
    info["rebuilt"][rel.split("state/", 1)[1]] = {"approximate": True, "dropped": dropped}
    return derived(ctx, rel, data, ctx.t0 - 1)


def history_files(ctx, out: list) -> None:
    """Runs that ended before t0 are already on disk (the collector scans D-1 too)."""
    for r in sl.history_runs(ctx.dd, sl.dirdates_around(ctx.day, sl.SEED_HISTORY_DAYS, 0)):
        if r.end >= ctx.t0:
            continue
        for rel in (r.json_rel, r.log_rel):
            if rel:
                out.append({"path": sl.machine(rel), **ctx.put(rel)})


def relay_log_prefix(ctx, relay_ref: dict) -> dict:
    """relay.log up to the first line stamped at/after t0, cut from the redacted copy
    (line numbers are the source's; byte offsets are the copy's)."""
    first = next((r.n for r in ctx.recs if r.t >= ctx.t0), None)
    before = [r for r in ctx.recs if r.t < ctx.t0]
    data = (ctx.corpus / relay_ref["file"]).read_bytes()
    if first is None:
        n_bytes = len(data)
    else:
        n_bytes, line = 0, 1
        while line < first:
            n_bytes = data.index(b"\n", n_bytes) + 1
            line += 1
    return {"path": sl.machine(sl.RELAY_LOG), "file": relay_ref["file"], "len": n_bytes,
            "sha256": hashlib.sha256(data[:n_bytes]).hexdigest(),
            "mtime": sl.iso(before[-1].t if before else ctx.t0 - 1)}


def machine_at_t0(ctx, boots: list) -> dict:
    """Power and relay state at 00:00 from the last boot that started before it."""
    prior = [b for b in boots if b.start.t < ctx.t0]
    if not prior:
        return {"power": "unknown", "relay": "unknown"}
    b = prior[-1]
    if b.stop is None or b.stop.t >= ctx.t0:
        return {"power": "on", "relay": "running", "relay_version": b.version,
                "relay_started": sl.iso(b.start.t), "src": f"{sl.RELAY_LOG}:{b.start.n}"}
    off = b.stop_how == "windows_shutdown"
    return {"power": "off" if off else "on", "relay": "stopped", "relay_version": b.version,
            "last_stop": sl.iso(b.stop.t), "stop_how": b.stop_how, "src": f"{sl.RELAY_LOG}:{b.stop.n}"}


def build(ctx, *, boots: list, relay_ref: dict, mas_config: dict, other_files: list) -> dict:
    info = {"unknown_at_t0": [], "notes": list(ctx.notes), "rebuilt": {}, "test_windows": [],
            "state_json": None}
    files: list = []
    state_files(ctx, files, info)
    tech_files(ctx, files)
    history_files(ctx, files)
    for rel, ref in mas_config.items():
        mt = (ctx.dd / rel).stat().st_mtime
        smt, moved = seed_mtime(ctx, mt)
        files.append({"path": sl.machine(rel), **ref, "mtime": sl.iso(smt),
                      **({"reconstructed": True, "as_of": ref["mtime"]} if moved else {})})
    files += other_files
    files += ctx.log_seed
    files.append(relay_log_prefix(ctx, relay_ref))
    files.sort(key=lambda e: e["path"])
    return {
        "day": ctx.day, "t0": sl.iso(ctx.t0), "t1": sl.iso(ctx.t1), "mode": "gate",
        "corpus": f"~/Claude/daysim-corpus/{ctx.day}",
        "machine": machine_at_t0(ctx, boots),
        "state_json": info["state_json"],
        "test_windows": info["test_windows"],
        "rebuilt": info["rebuilt"],
        "unknown_at_t0": sorted(info["unknown_at_t0"]),
        "not_recorded": [
            "web answers (official sites, info sources): no recording; W3 fixtures",
            "AUTO-MAS API answers and its data/ folder (mxu-MaaEnd.json master copies): not pulled",
            "AUTO-MAS config at 00:00: the pull's copy stands in (mas_config events say reconstructed)",
            "state/desktop/: answered by fake_desktop from the recorded res-*.json, not seeded",
        ],
        "notes": info["notes"],
        "files": files,
    }
