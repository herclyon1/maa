"""daysim W4: the recorded days under tests/daysim/days/ say what the machine recorded.

For every committed day (2026-10-06, 2026-10-12, 2026-10-13 until the pull) the input
feed that relay/tests/daysim/slice.py cut from the 10-13 15:26 machine pull is checked
against the record itself, re-read here with its own parsing:

* run events = the AUTO-MAS history pairs (json + log) whose start (the UTC+4 file
  name) falls in the day, none missing, none extra; each run ends at its .json's mtime;
* relay_start events = relay.log's 「服务模式启动」 lines of the day, line for line;
* every corpus file keeps the mtime of the file it came from;
* every sha256 an event or the seed names is the corpus bytes it points at;
* events are time-sorted, of the contract's kinds (design.md section 2), each with a
  src "<recorded file>:<line>" whose line exists;
* no secret pattern anywhere under relay/, nor in the day's corpus copies.

The record is too big for the repo: it lives in ~/Claude/daysim-corpus (corpus/<D>/
and the raw pull the manifest names). Where it is missing the record checks are
skipped with a line saying so - except on the owner's Mac, where a missing corpus fails.
"""
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "daysim"))
import slice as sl  # noqa: E402

DAYS = HERE / "daysim" / "days"
CORPUS = Path.home() / "Claude" / "daysim-corpus"
BJ = timezone(timedelta(hours=8))
UTC4 = timezone(timedelta(hours=4))
fails = []
# --full: read every byte of the corpus instead of the gate's sample.
FULL = "--full" in sys.argv


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f": {detail}"))
    if not ok:
        fails.append(name)


def ts(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def events_of(day: str) -> list:
    return [json.loads(x) for x in (DAYS / day / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def seed_of(day: str) -> dict:
    return json.loads((DAYS / day / "seed.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ independent readers of the record
def history_pairs(daydata: Path, day: str, t0: float, t1: float) -> dict:
    """{dirdate/user/stem: (start, json mtime)} for every history pair starting in [t0, t1)."""
    out = {}
    base = daydata / "D/ark/automas/history"
    d = datetime.strptime(day, "%Y-%m-%d")
    for k in (-1, 0, 1):
        dirdate = (d + timedelta(days=k)).strftime("%Y-%m-%d")
        for js in sorted((base / dirdate).glob("*/*.json")):
            hh, mi, ss = js.stem.split("-")[-3:]
            start = datetime.strptime(f"{dirdate} {hh}:{mi}:{ss}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC4).timestamp()
            if t0 <= start < t1:
                require(f"history pair has its .log: {js.parent.name}/{js.stem}", js.with_suffix(".log").exists())
                out[f"{dirdate}/{js.parent.name}/{js.stem}"] = (start, js.stat().st_mtime)
    return out


def relay_boot_lines(relay_log: Path, year: int, t0: float, t1: float) -> list:
    """(time, line number) of each 「服务模式启动」 line the relay itself wrote in [t0, t1)."""
    out = []
    with relay_log.open("rb") as f:                # lines end at \n only, as grep -n counts them
        for n, raw in enumerate(f, 1):
            line = raw.decode("utf-8", "replace")
            m = re.match(r"(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d) INFO +ark\.service +服务模式启动", line)
            if m:
                t = datetime(year, *(int(x) for x in m.groups()), tzinfo=BJ).timestamp()
                if t0 <= t < t1:
                    out.append((t, n))
    return out


def source_mtime(daydata: Path, source: str) -> float:
    return (daydata / source.split("!")[0]).stat().st_mtime


def line_count(path: Path, member: "str | None" = None) -> int:
    if member:
        with zipfile.ZipFile(path) as z:
            return z.read(member).count(b"\n") + 1
    return path.read_bytes().count(b"\n") + 1


# ------------------------------------------------------------------ the checks
def check_shape(day: str, evs: list, seed: dict) -> None:
    print(f"\n[{day}: contract shape]")
    t0, t1 = ts(seed["t0"]), ts(seed["t1"])
    check(f"{day} t0 is Beijing midnight", seed["t0"], f"{day}T00:00:00+08:00")
    bad_kind = [e for e in evs if e.get("kind") not in sl.KINDS]
    require(f"{day} every kind is a contract kind", not bad_kind, bad_kind[:2])
    bad_keys = [e for e in evs if not {"t", "kind", "src"} <= set(e)]
    require(f"{day} every event has t, kind, src", not bad_keys, bad_keys[:2])
    bad_t = [e["t"] for e in evs if not e["t"].endswith("+08:00") or not t0 <= ts(e["t"]) < t1]
    require(f"{day} every t is ISO+08:00 inside the day", not bad_t, bad_t[:3])
    times = [ts(e["t"]) for e in evs]
    require(f"{day} events are time-sorted", times == sorted(times))
    bad_src = [e["src"] for e in evs if not re.fullmatch(r"[CD]/\S.*:\d+", e["src"])]
    require(f"{day} every src is <recorded file>:<line>", not bad_src, bad_src[:3])
    paths = [f["path"] for f in seed["files"]]
    require(f"{day} seed files: one entry per machine path", len(paths) == len(set(paths)),
            [p for p in set(paths) if paths.count(p) > 1][:3])
    big = [(p.name, p.stat().st_size) for p in (DAYS / day).iterdir() if p.stat().st_size > 400_000]
    require(f"{day} in-repo files stay small (corpus holds the bytes)", not big, big)


def check_record(day: str, evs: list, seed: dict, corpus: Path) -> None:
    man = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    daydata = Path(man["daydata"])
    t0, t1 = ts(seed["t0"]), ts(seed["t1"])
    have_raw = daydata.is_dir()
    print(f"\n[{day}: against the record ({'raw pull ' + daydata.name if have_raw else 'corpus copies only'})]")
    rec_root = daydata if have_raw else corpus / "files"

    # runs = history pairs
    pairs = history_pairs(rec_root, day, t0, t1)
    runs = {f"{e['dir']}/{e['user']}/{e['stem']}": e for e in evs if e["kind"] == "run"}
    check(f"{day} run events = AUTO-MAS history pairs", sorted(runs), sorted(pairs))
    for rid, (start, js_mtime) in pairs.items():
        e = runs.get(rid)
        if e:
            check(f"{day} {rid} starts at its UTC+4 name", ts(e["start"]), start)
            require(f"{day} {rid} ends at its .json mtime", abs(ts(e["end"]) - js_mtime) < 1e-3,
                    (e["end"], js_mtime))

    # boots = 「服务模式启动」 lines
    relay_log = rec_root / sl.RELAY_LOG
    lines = relay_boot_lines(relay_log, int(day[:4]), t0, t1)
    starts = [(ts(e["t"]), int(e["src"].rsplit(":", 1)[1])) for e in evs if e["kind"] == "relay_start"]
    check(f"{day} relay_start events = relay.log 「服务模式启动」 lines", starts, lines)

    # mtimes
    bad = []
    for rel, m in man["files"].items():
        disk = (corpus / rel).stat().st_mtime
        if abs(disk - ts(m["mtime"])) > 1e-3:
            bad.append((rel, "disk", disk, m["mtime"]))
        if have_raw and m["transform"] != "rebuilt" and abs(source_mtime(daydata, m["source"]) - disk) > 1e-3:
            bad.append((rel, "source", m["source"]))
    require(f"{day} every corpus file has its source's mtime ({len(man['files'])} files)", not bad, bad[:3])

    # sha256 of what the events and the seed name. The gate (10 s a file, deploy-relay.sh
    # TEST_FILE_MAX_S) reads the small files whole and every log file's first and last
    # chunk; --full reads every byte (about 1 GB for the three days).
    sizes = {rel: m["size"] for rel, m in man["files"].items()}
    refs = []
    for e in evs:
        for k in ("json", "log", "res", "req"):
            if isinstance(e.get(k), dict):
                refs.append((e[k]["file"], None, None, e[k]["sha256"], e["src"]))
        if "file" in e and "sha256" in e:
            refs.append((e["file"], e.get("off"), e.get("len"), e["sha256"], e["src"]))
    for f in seed["files"]:
        rel = f.get("file") or "files/" + f["path"].replace(":", "", 1)
        refs.append((rel, 0 if "len" in f else None, f.get("len"), f["sha256"], f["path"]))
    by_file: dict = {}
    for r in refs:
        by_file.setdefault(r[0], []).append(r)
    bad, n_read = [], 0
    for rel, rs in sorted(by_file.items()):
        size = (corpus / rel).stat().st_size
        if size != sizes.get(rel):
            bad.append((rel, "size", size, sizes.get(rel)))
            continue
        if not FULL and size > 1_000_000:
            slices = sorted((r for r in rs if r[1] is not None), key=lambda r: r[1])
            rs = slices[:1] + slices[-1:] if slices else []
            rs = [r for r in rs if r[2] <= 4_000_000]
        with (corpus / rel).open("rb") as fh:
            for _rel, off, n, want, who in rs:
                fh.seek(off or 0)
                got = sha(fh.read(n) if off is not None else fh.read())
                n_read += 1
                if got != want:
                    bad.append((who, rel, off, n))
    require(f"{day} sha256 of what events and seed name ({n_read} of {len(refs)} read; size of all)", not bad, bad[:3])

    if FULL and have_raw:
        counts: dict = {}
        bad = []
        for e in evs:
            path, n = e["src"].rsplit(":", 1)
            src, _, member = path.partition("!")
            key = (src, member)
            if key not in counts:
                counts[key] = line_count(daydata / src, member or None)
            if not 1 <= int(n) <= counts[key]:
                bad.append(e["src"])
        require(f"{day} every src line exists in the recorded file", not bad, bad[:3])

    # The copies that were rewritten on the way in are where a secret could survive;
    # --full scans every copy.
    hits = []
    for rel, m in man["files"].items():
        if FULL or m["transform"] == "rebuilt" or m["size"] <= 5_000_000:
            if h := sl.secret_hits((corpus / rel).read_bytes()):
                hits.append((rel, h))
    require(f"{day} no secret pattern in the corpus copies", not hits, hits[:3])


def check_1012(evs: list) -> None:
    print("\n[2026-10-12: what the day was]")
    k = lambda kind: [e for e in evs if e["kind"] == kind]  # noqa: E731
    check("10 runs (MAA x3, MaaEnd x5, OK-WW x2)", len(k("run")), 10)
    check("18 relay starts, 4 of them before 09:13 (design.md section 1)",
          (len(k("relay_start")), sum(e["t"] < "2026-10-12T09:13" for e in k("relay_start"))), (18, 4))
    check("08:45:38 self-update restart is a stop/start", [e["how"] for e in k("relay_stop")][0], "self_update")
    mine = [e["t"] for e in k("relay_stop") if e["relay_poweroff"]]
    check("12:11:36 power-off was the relay's own (an output, not an input)", mine, ["2026-10-12T12:11:36+08:00"])
    check("22:13:33 shutdown came from outside", [e["t"] for e in k("power_off")], ["2026-10-12T22:13:33+08:00"])
    check("power on at 08:44 (estimated) and 14:22 (relay's own boot line)",
          [(e["t"], e["how"]) for e in k("power_on")],
          [("2026-10-12T08:44:26+08:00", "estimated"), ("2026-10-12T14:22:00+08:00", "boot_line")])
    check("phone orders: debug_mode on/off x4, skip_shutdown",
          [(e["action"], (e["args"] or {}).get("on")) for e in k("phone_order")],
          [("debug_mode", False), ("debug_mode", True), ("debug_mode", True), ("debug_mode", False),
           ("skip_shutdown", True)])
    check("test windows 18:25:41-18:29:19 and 20:03:36-20:06:44 open and close",
          [(e["op"], e["t"][11:19]) for e in k("file") if e["op"].startswith("test_window")],
          [("test_window_open", "18:25:41"), ("test_window_close", "18:29:19"),
           ("test_window_open", "20:03:36"), ("test_window_close", "20:06:44")])
    okww = [e for e in k("log_rotate") if e["path"].endswith("ok-script.log")]
    check("OK-WW log rotates at its first line of the day", [(e["t"], e["to"].rsplit("/", 1)[1]) for e in okww],
          [("2026-10-12T08:46:29+08:00", "ok-script.2026-10-11.log")])
    trig = [(e["t"][11:16], e["trigger"]) for e in k("mas_backend") if e["op"] == "task_start"]
    check("AUTO-MAS trigger sources from app.log (R10)", trig[:3],
          [("09:00", "scheduled_task"), ("11:41", "manual_task"), ("15:12", "manual_task")])


def check_seed_1013(seed: dict) -> None:
    print("\n[2026-10-13 seed: the state at 00:00 rebuilt from 10-12's relay.log]")
    st = seed["state_json"]
    check("skip_next_shutdown armed at 10-12 19:23 and not yet used", st["modes"].get("skip_next_shutdown"), True)
    check("debug mode off (closed 10-12 15:37)", "debug_until" in st["modes"], False)
    check("relay stopped and machine off at 00:00 (shutdown 10-12 22:13)",
          (seed["machine"]["power"], seed["machine"]["relay"]), ("off", "stopped"))
    check("10-12's daily-report mark kept, 10-13's alert marks dropped",
          ("marks.report:2026-10-12" in st["dropped"], "marks.alerted:2026-10-13" in st["dropped"]), (False, True))
    wins = [(w["since"], w["until"]) for w in seed["test_windows"]]
    check("test windows begun before 00:00 kept, 10-13's left to its event",
          wins[-1], ("2026-10-12T20:03:36+08:00", "2026-10-12T20:06:44+08:00"))


def check_redaction() -> None:
    print("\n[redaction: the patterns catch a COS signed link and mask it]")
    akid = "AK" + "ID" + "Ab1" * 11                      # built here so this file holds no key shape
    link = f"x.zip?q-sign-algorithm=sha1&q-ak={akid}&q-key-time=1;2&q-signature={'ab' * 20} ok"
    check("a real-looking key id is a hit", sl.secret_hits(link.encode()), ["cos-akid"])
    masked = sl.redact_bytes(link.encode())
    check("masked: no hit left", sl.secret_hits(masked), [])
    require("masked: key id and signature both gone", b"AKIDREDACTED" in masked and b"q-signature=REDACTED" in masked,
            masked)
    check("masking keeps the line count", masked.count(b"\n"), link.count("\n"))
    hook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + "1a2b3c4d-" * 4
    check("a group-bot webhook key is a hit", sl.secret_hits(hook.encode()), ["wecom-webhook-key"])


def check_tree() -> None:
    print("\n[no secret pattern anywhere under relay/]")
    hits = []
    for dirpath, dirs, names in os.walk(HERE.parent):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for n in names:
            p = Path(dirpath) / n
            if h := sl.secret_hits(p.read_bytes()):
                hits.append((str(p.relative_to(HERE.parent)), h))
    require("relay/ holds no webhook key, COS key id, token or API key", not hits, hits[:5])


check_redaction()
check_tree()
days = sorted(p.name for p in DAYS.iterdir() if p.is_dir())
check("committed days", days, ["2026-10-06", "2026-10-12", "2026-10-13"])
owner_mac = sys.platform == "darwin" and (Path.home() / "Claude" / "maa-automation").is_dir()
for day in days:
    evs, seed = events_of(day), seed_of(day)
    check_shape(day, evs, seed)
    corpus = CORPUS / day
    if (corpus / "manifest.json").exists():
        check_record(day, evs, seed, corpus)
    elif owner_mac:
        require(f"{day} corpus present on the owner's Mac ({corpus})", False, "make it: relay/tests/daysim/slice.py <day> --daydata <pull>")
    else:
        print(f"  - {day}: no corpus on this machine ({corpus}); record checks skipped")
check_1012(events_of("2026-10-12"))
check_seed_1013(seed_of("2026-10-13"))

print(f"\n{'all checks passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
