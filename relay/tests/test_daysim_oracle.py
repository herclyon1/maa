"""The day replay's oracle (tests/daysim/oracle.py) and drafter (tests/daysim/draft.py).

What is pinned here:
- the loader refuses an unreviewed entry, an entry without a checkable source, a
  must_not that names no fix or normal-state line, a commit the repo does not have,
  a USER-SWITCHES.txt line that does not exist, a dropped entry without `was`;
  the three reviewed days (10-06, 10-12, 10-13) load;
- each of the five invariants goes red on a crafted output and stays quiet on the
  matching good one;
- the matcher: a missing must, a must_not that happened and a strict push nobody
  expected each fail the day; a may covers;
- drift: a rule change or a deletion without `was` is refused;
- the real record judged against the reviewed days goes red on exactly the known
  bugs (R05, R20, R21, R30, R32 missing, R34, R35, R36 and the debug-skip /
  hand-run power-offs of the same causes) and on nothing else. The record files
  (fixtures/daysim-record-<D>.json) are what the old relay really did that day,
  shaped as outputs.json from the pulled machine state: alerts/<YYYYMMDD>.jsonl as
  group pushes, relay.log's 「已推送「…」」 / 「日报已推送」 lines as Server酱 pushes,
  「60 秒后关机」 as `shutdown /s`, its WARNING+ and ark.shutdown lines as `log`, the
  day's ledger rows; texts cut short and passed through draft.clean;
- draft.py reads only the record, never a simulator output, marks every entry
  unreviewed (so the loader refuses its output), masks secrets, and has no --update.
"""
import contextlib
import copy
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "daysim"))
sys.path.insert(0, str(HERE))
import draft  # noqa: E402
import oracle  # noqa: E402
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def require(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{'' if ok else ' - ' + str(detail)}")
    if not ok:
        fails.append(name)


DAY = "2026-10-12"


def entry(**f):
    base = {"id": "x-01", "kind": "push", "rule": "must", "ch": "group", "at": "11:49",
            "review": "reviewed", "why": "a reason", "src": "errors R32; f912c1f0"}
    base.update(f)
    return base


def doc(*items, **top):
    d = {"day": DAY, "scope": {"from": "00:00", "to": "24:00"}, "items": list(items)}
    d.update(top)
    return d


def refused(label, item, needle):
    problems = oracle.validate(doc(item))
    require(f"refused: {label}", any(needle in p for p in problems), problems)


def push(t, ch="group", title="⚠️ 这一轮没干完", text="· 周本领到了奖励", game="鸣潮"):
    return {"t": f"{DAY}T{t}+08:00", "ch": ch, "title": title, "text": text, "game": game}


def outputs(**f):
    o = {"boots": [], "pushes": [], "power": [], "mas_writes": [], "procs": [], "ledger": [],
         "report": None, "log": [], "sim_errors": []}
    o.update(f)
    return o


def failures(o, items, **kw):
    return oracle.check_day(o, doc(*items, **kw)).failures


print("[loader: the reviewed days load; draft-state and unsourced entries are refused]")
days = oracle.all_days()
check("the reviewed days are there", sorted(p.parent.name for p in days),
      ["2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-11", "2026-10-12", "2026-10-13"])
for p in days:
    try:
        n = len(oracle.load_expected(p)["items"])
    except oracle.OracleError as exc:
        n = exc.problems
    require(f"{p.parent.name} loads", isinstance(n, int) and n > 0, n)
check("a good entry passes", oracle.validate(doc(entry())), [])
refused("unreviewed", entry(review="unreviewed"), "not 'reviewed'")
refused("no review field", {k: v for k, v in entry().items() if k != "review"}, "not 'reviewed'")
refused("no src", entry(src=""), "no src")
refused("src 待核 alone", entry(src="待核"), "names nothing checkable")
refused("src prose", entry(src="the owner said so"), "names nothing checkable")
refused("must_not citing only a log line", entry(rule="must_not", src="relay.log 10-12 18:29:17"),
        "must_not cites the fix")
refused("commit not in the repo", entry(src="errors R32; 0123abcd9"), "not in this repository")
refused("USER-SWITCHES line past the end", entry(rule="must_not", src="USER-SWITCHES.txt:99999"),
        "has no line 99999")
refused("USER-SWITCHES line that is a header comment", entry(rule="must_not", src="USER-SWITCHES.txt:3"),
        "is not an entry line")
refused("no why", entry(why=""), "no why")
refused("unknown field (typo)", entry(text_hass=["周本"]), "unknown field")
refused("dropped without was", entry(rule="dropped"), "`was` must be")
refused("bad rule", entry(rule="should"), "rule 'should'")
refused("push without ch", {k: v for k, v in entry().items() if k != "ch"}, "needs ch")
refused("verdict without status", entry(kind="verdict", run="a/b/OK-WW-07-41-07"), "needs status")
refused("window backwards", entry(window=["12:00", "11:00"]), "window must be")
refused("at and window", entry(window=["11:00", "12:00"]), "not both")
two = oracle.validate(doc(entry(), entry()))
require("refused: id used twice", any("used twice" in p for p in two), two)
draft_entry = entry(review="unreviewed", src="alerts/20261012.jsonl:2")
check("a reviewed must_not citing USER-SWITCHES passes",
      oracle.validate(doc(entry(rule="must_not", src="USER-SWITCHES.txt:73; relay.log 10-12 21:45:34"))), [])
p = tmpdir() / "expected.json"
p.write_text(json.dumps(doc(draft_entry)), encoding="utf-8")
try:
    oracle.load_expected(p)
    got = "loaded"
except oracle.OracleError as exc:
    got = "refused" if any("unreviewed" in x for x in exc.problems) else exc.problems
check("load_expected refuses a draft file", got, "refused")

print("\n[drift: a rule change or a deletion keeps `was`]")
old = doc(entry(id="a", rule="must"), entry(id="b"))
new = doc(entry(id="a", rule="must_not", src="errors R32; f912c1f0"))
d = oracle.drift(old, new)
require("rule change without was is refused", any("'a' changed rule" in x for x in d), d)
require("deletion is refused", any("'b' was deleted" in x for x in d), d)
new_ok = doc(entry(id="a", rule="must_not", was={"rule": "must", "reason": "turned out normal"}),
             entry(id="b", rule="dropped", was={"rule": "must", "reason": "input never recorded"}))
check("with was on both, no drift", oracle.drift(old, new_ok), [])
check("dropped with was loads", oracle.validate(new_ok), [])

print("\n[matcher]")
r32 = entry(game="鸣潮", title_has="没干完", text_has=["周本"])
check("must present: day passes", failures(outputs(pushes=[push("11:49:23")]), [r32]), [])
f = failures(outputs(pushes=[push("12:30:00")]), [r32])
require("must outside its tolerance: red", any("x-01 must, missing" in x for x in f), f)
f = failures(outputs(pushes=[push("11:49:23", text="· 每日任务")]), [r32])
require("must with the wrong text: red", any("missing" in x for x in f), f)
f = failures(outputs(pushes=[push("11:49:23", game="终末地")]), [r32])
require("must for the wrong game: red", any("missing" in x for x in f), f)
r35 = entry(rule="must_not", ch="serverchan", at="18:29", title_has="🔎", src="errors R35; 8705ab8f")
f = failures(outputs(pushes=[push("18:29:17", ch="serverchan", title="🔎 速览（手动执行）")]), [r35])
require("must_not that happened: red", any("must_not, happened" in x for x in f), f)
f = failures(outputs(pushes=[push("09:00:00", title="🌙 今晚不关机", game="")]), [r32])
require("strict: a group push no entry expects is red",
        any("strict: no entry expects" in x for x in f), f)
may = entry(id="x-02", rule="may", title_has="今晚不关机", at="09:00", src="errors R21; 192dfefa")
check("a may covers that push", failures(outputs(pushes=[push("09:00:00", title="🌙 今晚不关机", game=""),
                                                         push("11:49:23")]), [r32, may]), [])
f = failures(outputs(pushes=[push("09:00:00", ch="ntfy", title="state"), push("11:49:23")]), [r32])
check("ntfy pushes are not strict", f, [])
rep = entry(id="x-03", kind="report", at="21:45", tol_min=15, title_has="📋", src="relay.log 10-12 21:45:34")
del rep["ch"]
check("a Server酱 push titled 📋 counts as the report",
      failures(outputs(pushes=[push("21:45:34", ch="serverchan", title="📋 日报", game="")]), [rep]), [])
check("outputs.report counts as the report",
      failures(outputs(report={"t": f"{DAY}T21:45:34+08:00", "title": "📋 日报", "text": ""}), [rep]), [])
f = failures(outputs(power=[{"t": f"{DAY}T12:10:36+08:00", "cmd": "shutdown /s /t 60"}]), [r32])
require("strict: a power command no entry expects is red",
        any("strict" in x and "power" in x for x in f), f)
f = failures(outputs(pushes=[push("11:49:23")],
                     log=["10-12 13:00:00 ERROR   ark.x  boom", "10-12 13:00:05 INFO    ark.y  fine"]), [r32])
require("strict: an ERROR line no entry expects is red", any("strict" in x and "boom" in x for x in f), f)
verdict = entry(id="x-04", kind="verdict", run="OK-WW-07-41-07", status="ok", failed_has=["周本"],
                src="ledger-2026-10-12.jsonl:6")
del verdict["ch"], verdict["at"]
row = {"run_id": "2026-10-12/wuwa/OK-WW-07-41-07", "script": "OK-WW", "ok": True, "failed_tasks": [],
       "started": f"{DAY}T11:41:20+08:00", "finished": f"{DAY}T11:49:18+08:00",
       "raw": {"okww_error": "周本：周本领奖：点了确认后没等到结算页"}}
check("verdict by stem, failed items from raw *_error",
      failures(outputs(pushes=[push("11:49:23")], ledger=[row]), [r32, verdict]), [])
gone = entry(id="x-05", kind="ledger", rule="must_not", run="2026-10-12/endfield/MaaEnd-06-58-11",
             src="errors R34; d9f3fd12")
del gone["ch"], gone["at"]
upd = dict(row, run_id="2026-10-12/endfield/MaaEnd-06-58-11", script="MaaEnd", ok=False, raw={})
f = failures(outputs(pushes=[push("11:49:23")], ledger=[row, upd]), [r32, verdict, gone])
require("ledger must_not: a booked update step is red", any("x-05 must_not" in x for x in f), f)

print("\n[invariant 1: a failed ledger row needs a group push]")
bad_row = dict(row, run_id="2026-10-12/endfield/MaaEnd-06-04-00", script="MaaEnd", ok=False,
               failed_tasks=["协议空间"], finished=f"{DAY}T10:58:09+08:00", raw={})
inv = oracle.invariants(outputs(ledger=[bad_row]), doc(r32))
require("failed row, no push: red", any(x.startswith("invariant 1") for x in inv), inv)
inv = oracle.invariants(outputs(ledger=[bad_row], pushes=[push("11:00:00", game="终末地", title="⚠️ 没干完")]),
                        doc(r32))
check("failed row with a 终末地 group push after it: quiet", inv, [])
inv = oracle.invariants(outputs(ledger=[bad_row], pushes=[push("09:00:00", game="终末地")]), doc(r32))
require("a push before the run ended does not count", any(x.startswith("invariant 1") for x in inv), inv)
healed = entry(id="x-06", rule="must_not", window=["10:58", "11:45"], game="终末地",
               run="2026-10-12/endfield/MaaEnd-06-04-00", src="USER-SWITCHES.txt:49")
del healed["at"]
check("covered by a sourced must_not on that run: quiet",
      oracle.invariants(outputs(ledger=[bad_row]), doc(r32, healed)), [])

print("\n[invariant 2: no shutdown /s inside a guard]")
off = {"t": "2026-10-13T11:13:55+08:00", "cmd": "shutdown /s /t 60"}
g13 = {"day": "2026-10-13", "scope": {"from": "00:00", "to": "15:26"},
       "guards": [{"from": "11:05:49", "to": "11:57:41", "what": "test window OK-WW", "src": "test-windows.json"}],
       "items": [r32]}
inv = oracle.invariants(outputs(power=[off]), g13)
require("power-off in the test window: red", any(x.startswith("invariant 2") for x in inv), inv)
check("same power-off with the window over: quiet",
      oracle.invariants(outputs(power=[dict(off, t="2026-10-13T12:10:00+08:00")]), g13), [])
check("a shutdown abort (/a) is no power-off",
      oracle.invariants(outputs(power=[dict(off, cmd="shutdown /a")]), g13), [])
g_none = dict(g13, guards=[])
inv = oracle.invariants(outputs(power=[off]), g_none,
                        debug_windows=[("2026-10-13T11:00:00+08:00", "2026-10-13T11:30:00+08:00", "debug mode")])
require("debug window passed by the caller: red", any("debug mode" in x for x in inv), inv)
hand = {"run_id": "2026-10-13/wuwa/OK-WW-07-05-49", "ok": True, "started": "2026-10-13T11:07:05+08:00",
        "finished": "2026-10-13T11:14:30+08:00", "raw": {"hand_started": "id"}}
inv = oracle.invariants(outputs(power=[off], ledger=[hand]), g_none)
require("power-off while a hand-started run is open: red", any("hand-started run" in x for x in inv), inv)

print("\n[invariant 3: at most 250 ntfy publishes per UTC day]")


def ntfy(n, start_h):
    return [{"t": f"2026-10-12T{start_h + i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}+08:00",
             "ch": "ntfy", "title": "s", "text": ""} for i in range(n)]


inv = oracle.invariants(outputs(pushes=ntfy(251, 9)), doc(r32))
require("251 in one UTC day: red", any(x.startswith("invariant 3") for x in inv), inv)
check("250: quiet", oracle.invariants(outputs(pushes=ntfy(250, 9)), doc(r32)), [])
split = ntfy(200, 1)[:200] + [dict(x, t=x["t"].replace("2026-10-12T01", "2026-10-12T09")) for x in ntfy(100, 1)]
check("300 in one Beijing day, split over two UTC days (08:00 Beijing): quiet",
      oracle.invariants(outputs(pushes=split), doc(r32)), [])

print("\n[invariant 4: every relay.log ERROR has a group push]")
err = "10-12 13:00:00 ERROR   ark.phone_banners  🔬 上机核对没过：#2"
inv = oracle.invariants(outputs(log=[err]), doc(r32))
require("ERROR, no push: red", any(x.startswith("invariant 4") for x in inv), inv)
check("ERROR with a group push 1 min later: quiet",
      oracle.invariants(outputs(log=[err], pushes=[push("13:01:00", title="🩺 中继自己报错了")]), doc(r32)), [])
inv = oracle.invariants(outputs(log=[err], pushes=[push("13:30:00", title="🩺 中继自己报错了")]), doc(r32))
require("push 30 min later, no boot between: red", any(x.startswith("invariant 4") for x in inv), inv)
check("ERROR before a power-off, pushed at the next boot: quiet",
      oracle.invariants(outputs(log=[err], boots=[{"start": f"{DAY}T15:00:00+08:00"}],
                                pushes=[push("15:02:00", title="🩺 中继自己报错了")]), doc(r32)), [])
check("a dict log entry works too",
      oracle.invariants(outputs(log=[{"t": f"{DAY}T13:00:00+08:00", "level": "WARNING", "logger": "a", "msg": "m"}]),
                        doc(r32)), [])

print("\n[invariant 5: no sim error]")
inv = oracle.invariants(outputs(sim_errors=["unrouted command: shutdown /r"]), doc(r32))
require("a sim error: red", any(x.startswith("invariant 5") for x in inv), inv)

print("\n[the real record against the reviewed days: red on exactly the known bugs]")
KNOWN = {
    # 1006-23/24: the machine's code kept a self-recovered WMI drop out of the group;
    # 324b640b (10-10) sends an unknown-cause one to the group, so the record lacks them.
    "2026-10-06": {"1006-01", "1006-02", "1006-03", "1006-04", "1006-05", "1006-06", "1006-09",
                   "1006-14", "1006-18", "1006-19", "1006-23", "1006-24"},
    # 1007-04 / 1008-04: the machine's code wrote a ledger row for MaaEnd's own update step
    # (R34, d9f3fd12); 1007-08 / 1008-13 / 1009-08 / 1009-12 / 1011-12: 「今晚不关机」 at the
    # shift start (R21, 192dfefa); 1007-17 / 1008-19: the 自动囤货 reset went unreported
    # (c1c80674); 1007-19: 「官方未公告」 for the Endfield banner (R22); 1009-05: R24
    # (bb58e515, da65e68d); 1009-17: the old AUTO-MAS left MaaEnd running unreported (E04);
    # 1011-10 / 1011-11: #11 false alarms (R06); 1011-16: the 21:46 alarm (R05).
    "2026-10-07": {"1007-04", "1007-08", "1007-17", "1007-19"},
    "2026-10-08": {"1008-04", "1008-13", "1008-19"},
    "2026-10-09": {"1009-05", "1009-08", "1009-12", "1009-17"},
    "2026-10-11": {"1011-10", "1011-11", "1011-12", "1011-16"},
    "2026-10-12": {"1012-01", "1012-02", "1012-15", "1012-17", "1012-18", "1012-20"},
    "2026-10-13": {"1013-12", "invariant 2"},
}
for p in days:
    day = p.parent.name
    rec = json.loads((HERE / "fixtures" / f"daysim-record-{day}.json").read_text(encoding="utf-8"))
    res = oracle.check_day(rec, oracle.load_expected(p))
    got = {x.split(" ", 1)[0] if not x.startswith("invariant") else " ".join(x.split(" ")[:2]).rstrip(":")
           for x in res.failures}
    check(f"{day}: the record fails exactly the known-bug entries", sorted(got), sorted(KNOWN[day]))
    require(f"{day}: the report shows expected beside actual",
            "why:" in res.report() and "actual" in res.report(), res.report()[:300])
fixed = json.loads((HERE / "fixtures" / "daysim-record-2026-10-13.json").read_text(encoding="utf-8"))
fixed["power"] = []
res = oracle.check_day(fixed, oracle.load_expected(HERE / "daysim" / "days" / "2026-10-13" / "expected.json"))
check("10-13 without the 11:13 power-off passes", res.failures, [])

print("\n[draft.py: only the record, unreviewed, secrets masked, no --update]")
# Built at run time so no key-id-shaped literal sits in the repository.
FAKE_KEY_ID = "AK" + "ID" + "abcdef123456"
rec_dir = tmpdir()
(rec_dir / "state" / "alerts").mkdir(parents=True)
(rec_dir / "relay.log").write_bytes(
    "10-11 23:00:00 INFO    ark.report  📋 2026-10-11 日报已推送（3 条记录）\n"
    "10-12 08:46:07 INFO    ark.service  📱 手机指令 debug_mode：🔧 调试模式已开启，至 10-12 21:10（下次）\n"
    "10-12 09:00:00 INFO    ark.x  a message with a bare \r in it\n"
    "10-12 11:49:59 INFO    ark.report  🔎 2026-10-12 已推送「手动执行」（覆盖 7 条记录）\n"
    "10-12 12:05:26 INFO    ark.service  📱 手机指令 debug_mode：调试模式已关闭，恢复正常运行\n"
    "10-12 12:10:36 INFO    ark.engine  本轮已处理完毕，60 秒后关机\n"
    "10-12 13:00:00 ERROR   ark.phone_banners  🔬 上机核对没过：#2\n".encode())
(rec_dir / "state" / "alerts" / "20261012.jsonl").write_text(json.dumps(
    {"ts": "2026-10-12 10:04:11", "game": "鸣潮", "title": "⚠️ 这一轮没干完",
     "text": "OK-WW 这一轮有 1 项没干成，证据包：https://x.cos.example/a.zip?q-sign-algorithm=sha1&q-ak="
             + FAKE_KEY_ID + "&q-signature=ff", "version": "v", "evidence_run": ""}, ensure_ascii=False) + "\n",
    encoding="utf-8")
(rec_dir / "state" / "ledger-2026-10-12.jsonl").write_text(json.dumps(
    {"run_id": "2026-10-12/wuwa/OK-WW-07-41-07", "ok": True, "failed_tasks": [],
     "started": "2026-10-12T11:41:20+08:00", "finished": "2026-10-12T11:49:18+08:00",
     "raw": {"okww_error": "周本：没等到结算页", "hand_started": "abc"}}, ensure_ascii=False) + "\n",
    encoding="utf-8")
# Simulator output lying next to the record must never be read.
(rec_dir / "outputs.json").write_text(json.dumps(outputs(pushes=[push("12:00:00", title="POISON")])),
                                      encoding="utf-8")
(rec_dir / "out" / DAY).mkdir(parents=True)
(rec_dir / "out" / DAY / "outputs.json").write_text('{"pushes": [{"title": "POISON"}]}', encoding="utf-8")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = draft.main([DAY, "--record", str(rec_dir)])
check("draft exits 0", rc, 0)
dr = json.loads(buf.getvalue())
blob = json.dumps(dr, ensure_ascii=False)
check("nothing from a simulator output", "POISON" in blob, False)
check("every entry unreviewed", {it["review"] for it in dr["items"]}, {"unreviewed"})
check("drafted kinds", sorted(it["kind"] for it in dr["items"]), ["log", "power", "push", "push", "verdict"])
check("only day D's lines (not 10-11's report)", any(it["kind"] == "report" for it in dr["items"]), False)
check("AKID masked and signed query dropped", (FAKE_KEY_ID in blob, "q-sign" in blob), (False, False))
check("debug window from the phone lines", [(g["from"], g["to"]) for g in dr["guards"] if g["what"] == "debug mode"],
      [("08:46:07", "12:05:26")])
check("hand-started run as a guard", [g["what"] for g in dr["guards"] if "hand" in g["what"]],
      ["hand-started run 2026-10-12/wuwa/OK-WW-07-41-07"])
check("relay.log line numbers count \\n only", [it["src"] for it in dr["items"] if it["kind"] == "power"],
      ["relay.log 10-12 12:10:36 (line 6)"])
problems = oracle.validate(dr)
require("the loader refuses the draft as it comes", any("unreviewed" in x for x in problems), problems)
rev = copy.deepcopy(dr)
for it in rev["items"]:
    it.update(review="reviewed", why="checked", src=it["src"] + "; errors R32")
check("once every entry is reviewed and sourced it loads", oracle.validate(rev), [])
for bad_flag in ("--update", "--out"):
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            draft.main([DAY, "--record", str(rec_dir), bad_flag, "x"])
        got = "accepted"
    except SystemExit as exc:
        got = exc.code
    check(f"draft has no {bad_flag}", got, 2)

print()
if fails:
    print(f"FAILED: {len(fails)}: {fails}")
    sys.exit(1)
print("all checks passed")
