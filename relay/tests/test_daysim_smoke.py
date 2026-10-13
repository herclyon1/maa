"""daysim W5: the day replay runs end to end (design.md section 6, W5's row).

Without the recorded corpus (CI) it checks the World's own pieces:
* the boot plan of 2026-10-12: 18 relay lives, 4 of them before 09:13, each ending at
  its recorded stop, the first one counted from the estimated power-on;
* the inputs rebuilt from the record: phone orders as the phone page sends them
  (debug_mode off is {"off": true}: a body {"on": false} would turn it ON), inbox
  files as scripts/mac/order.sh writes them;
* at one recorded second the AUTO-MAS task opens before its run starts;
* the scheduler adapter files W2's "sim_errors" and W3's "sim_error" as one kind;
* a boot refuses to start the relay unless every network door is the fake's.

With the corpus (the owner's Mac; a missing corpus fails there) it replays the
morning of 2026-10-12 up to 09:20 - four boots, each its own process - and checks
the two MAA verdicts (both runs ok, handled after AUTO-MAS wrote their files at
09:18:45), that every boot ended by its own stop, that pushes were captured as
outputs, and that no sim error happened (no unrouted command, URL or socket).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "daysim"))
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


check("daysim world.py, boot.py and run.py exist",
      all((HERE / "daysim" / f).is_file() for f in ("world.py", "boot.py", "run.py")))
if fails:
    print(f"\n{len(fails)} failed: {fails}")
    sys.exit(1)

import world as W  # noqa: E402

# ---- the boot plan
events, seed = W.load_day("2026-10-12")
boots = W.plan_boots(events, seed)
check("10-12: 18 relay lives", len(boots), 18)
check("10-12: 4 of them before 09:13",
      sum(b["start"] < W.epoch("2026-10-12T09:13:00+08:00") for b in boots), 4)
check("10-12: the first starts at 08:45:26, after the estimated power-on 08:44:26",
      (W.iso(boots[0]["start"]), W.iso(boots[0]["power_on"]), boots[0]["after"]),
      ("2026-10-12T08:45:26+08:00", "2026-10-12T08:44:26+08:00", "power_on"))
check("10-12: the 12:00:27 life ends at the relay's own power-off 12:11:36",
      (W.iso(boots[7]["end"]), boots[7]["relay_poweroff"]), ("2026-10-12T12:11:36+08:00", True))
check("10-12: the last life ends at the outside shutdown 22:13:33",
      (W.iso(boots[-1]["end"]), boots[-1]["how"]), ("2026-10-12T22:13:33+08:00", "windows_shutdown"))
cut = W.plan_boots(events, seed, W.epoch("2026-10-12T09:20:00+08:00"))
check("10-12 until 09:20: 4 lives, the last cut at 09:20 (day_end)",
      (len(cut), W.iso(cut[-1]["end"]), cut[-1]["how"]), (4, "2026-10-12T09:20:00+08:00", "day_end"))
s13, e13 = W.load_day("2026-10-13")[1], W.load_day("2026-10-13")[0]
b13 = W.plan_boots(e13, s13)
check("10-13: the last life has no recorded stop and ends at the pull 15:26:37",
      (W.iso(b13[-1]["end"]), b13[-1]["how"]), ("2026-10-13T15:26:37+08:00", "day_end"))
e06, s06 = W.load_day("2026-10-06")
check("10-06: the relay was running at 00:00, so the first life starts at t0",
      (W.iso(W.plan_boots(e06, s06)[0]["start"]), W.plan_boots(e06, s06)[0]["after"]),
      ("2026-10-06T00:00:00+08:00", "running_at_t0"))

# ---- inputs rebuilt from the record
check("phone debug_mode off -> {off: true}",
      W.phone_body({"action": "debug_mode", "args": {"on": False}}),
      {"action": "debug_mode", "off": True, "confirmed": True})
check("phone debug_mode on -> the page's 90-minute body",
      W.phone_body({"action": "debug_mode", "args": {"on": True}}),
      {"action": "debug_mode", "minutes": 90, "confirmed": True})
check("phone skip_shutdown on", W.phone_body({"action": "skip_shutdown", "args": {"on": True}}),
      {"action": "skip_shutdown"})
check("inbox 「调试模式」 -> one debug_mode command",
      W.inbox_doc({"version": "2026101201", "title": "从电脑发来的指令：调试模式"})["commands"],
      [{"action": "debug_mode"}])
check("inbox 「空（安全状态）」 -> no command",
      W.inbox_doc({"version": "2026101202", "title": "从电脑发来的指令：空（安全状态）"})["commands"], [])
tl = W.timeline(events)
at1141 = [(x["kind"], x["ev"].get("op")) for x in tl if W.iso(x["t"]) == "2026-10-12T11:41:07+08:00"]
check("11:41:07: the AUTO-MAS task opens before the hand-started run starts",
      at1141.index(("mas_backend", "task_start")) < at1141.index(("run_start", None)), True)
inbox = [x for x in tl if x["kind"] == "inbox"]
check("inbox files are in place a minute before the relay's recorded reads",
      [W.iso(x["t"]) for x in inbox], ["2026-10-12T08:45:00+08:00", "2026-10-12T12:09:00+08:00"])


class _SC:
    def __init__(self):
        self.got = []
        self.now = self.at = self.park = self.advance = self.poke = lambda *a, **k: None

    def out(self, kind, **f):
        self.got.append(kind)


sc = _SC()
W.Sched(sc).out("sim_errors", what="x")
W.Sched(sc).out("sim_error", what="y")
check("W2's sim_errors and W3's sim_error are one kind", sc.got, ["sim_error", "sim_error"])
try:
    W.assert_offline(object())
    refused = False
except SystemExit:
    refused = True
check("a boot without the network fakes refuses to start the relay", refused)

# ---- the morning of 10-12, end to end
corpus = W.CORPUS_ROOT / "2026-10-12"
owner_mac = sys.platform == "darwin" and (Path.home() / "Claude" / "maa-automation").is_dir()
if (corpus / "manifest.json").exists():
    import run
    out = tmpdir("daysim-smoke-")
    r = run.run_day("2026-10-12", code=W.RELAY, until="09:20", out_root=out)
    o = json.loads((out / "2026-10-12" / "outputs.json").read_text(encoding="utf-8"))
    rows = {x["run_id"]: x for x in o["ledger"]}
    for stem in ("MAA-05-00-26", "MAA-05-03-42"):
        row = rows.get(f"2026-10-12/arknights/{stem}") or {}
        check(f"verdict {stem}: ok, no failed item", (row.get("ok"), row.get("failed_tasks")), (True, []))
    check("4 boots, each ended by its own stop", [b["exit"] for b in o["boots"]], ["returned"] * 4)
    check("no sim error", o["sim_errors"], [])
    check("pushes captured as outputs (group and ntfy)",
          {"group", "ntfy"} <= {p["ch"] for p in o["pushes"]}, True)
    check("the morning stays within the day's budget", r["real_s"] < run.DAY_CAP_S, True)
elif owner_mac:
    check(f"10-12 corpus present on the owner's Mac ({corpus})", False)
else:
    print(f"  - no corpus on this machine ({corpus}); the end-to-end morning is skipped")

print(f"\n{'all checks passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
