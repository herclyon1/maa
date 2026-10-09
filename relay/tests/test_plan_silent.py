"""Tomorrow's plan says when a source it needs could not be read (audit
docs/SILENT-FAILURES-AUDIT.md, plan.py rows).

The plan is rebuilt on every phone-state publish, and a WARNING is a group
message: each unreadable source is said once per condition, again only after it
read fine in between.
"""
import json
import logging
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

os.environ["ARK_STATE_DIR"] = str(tmpdir())
os.environ.pop("ARK_OKWW_DIR", None)
from ark_relay import plan

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        out = [r for r in self.records if r.levelno >= logging.WARNING]
        self.records.clear()
        return out


grab = Grab()
logging.getLogger("ark.plan").addHandler(grab)


def fresh():
    getattr(plan, "_last_error", {}).clear()
    grab.records.clear()


def farm_dir(text):
    d = tmpdir()
    if text is not None:
        (d / "FarmEchoTask.json").write_text(text, encoding="utf-8")
    return d


print("[row 1: FarmEchoTask.json unreadable]")
fresh()
bad = farm_dir("{not json")
got = plan._okww_extra_bit(bad, ["Teleport and Farm 4C Echo"], {"Teleport and Farm 4C Echo": "传送刷4C声骸"})
check("unreadable -> says the slot cannot be read, not the 4C name", got, "附加 周本/4C 设置读不到")
check("unreadable -> one WARNING", len(grab.warnings()), 1)
plan._okww_extra_bit(bad, ["Teleport and Farm 4C Echo"], {})
check("same condition again -> no second WARNING", len(grab.warnings()), 0)
good = farm_dir(json.dumps({"Teleport to Boss": "Normal"}))
check("readable -> named as the echo task",
      plan._okww_extra_bit(good, ["Teleport and Farm 4C Echo"], {"Teleport and Farm 4C Echo": "传送刷4C声骸"}),
      "附加 传送刷4C声骸")
check("readable -> no WARNING", len(grab.warnings()), 0)
plan._okww_extra_bit(bad, ["Teleport and Farm 4C Echo"], {})
check("broken again after a good read -> WARNING again", len(grab.warnings()), 1)
check("missing file is not an error -> echo name, no WARNING",
      (plan._okww_extra_bit(farm_dir(None), ["Teleport and Farm 4C Echo"], {}), len(grab.warnings())),
      ("附加 Teleport and Farm 4C Echo", 0))

print("[row 2: weekly-boss bookkeeping unreadable]")
fresh()
weekly = farm_dir(json.dumps({"Teleport to Boss": "Weekly Challenge", "Boss Level": "90",
                              "Which Weekly Boss to Teleport": 2}))
broken = mock.patch("ark_relay.weeklyboss.WeeklyBossGate.settings", side_effect=OSError("state.json locked"))
with broken:
    got = plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {})
    check("unknown -> says it cannot tell, not 「明天会打」", got,
          "附加 周本 战歌重奏第 2 个（90 级），本周打没打满读不到")
    check("unknown -> one WARNING", len(grab.warnings()), 1)
    plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {})
    check("same condition again -> no second WARNING", len(grab.warnings()), 0)
with mock.patch("ark_relay.weeklyboss.WeeklyBossGate.settings",
                return_value={"本周已打": False, "名字": ""}):
    check("readable -> 明天会打",
          plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {}).endswith("明天会打"), True)
with broken:
    plan._okww_extra_bit(weekly, ["Teleport and Farm 4C Echo"], {})
    check("broken again after a good read -> WARNING again", len(grab.warnings()), 1)

print("[row 3: AUTO-MAS ScriptConfig.json unreadable]")
fresh()


def automas(script_config):
    root = tmpdir()
    d = root / "data" / "okww-sid" / "Default" / "ConfigFile"
    d.mkdir(parents=True)
    (d / "DailyTask.json").write_text(json.dumps({
        "Which to Farm": "Simulation Challenge", "Material Selection": "Shell Credit",
        "Additional Tasks to Run After Daily Task": ["Some Master Task"]}), encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "ScriptConfig.json").write_text(script_config, encoding="utf-8")
    return root


bad_root = automas("{broken")
bits = plan._okww_plan_bits(bad_root)
check("unreadable -> 附加任务读不到 instead of the master's list",
      [b for b in bits if b.startswith("附加")], ["附加任务读不到"])
check("unreadable -> one WARNING", len(grab.warnings()), 1)
plan._okww_plan_bits(bad_root)
check("same condition again -> no second WARNING", len(grab.warnings()), 0)
off_root = automas(json.dumps({}))
check("readable, quick config off -> the master's list",
      [b for b in plan._okww_plan_bits(off_root) if b.startswith("附加")], ["附加 Some Master Task"])
check("readable -> no WARNING", len(grab.warnings()), 0)
plan._okww_plan_bits(bad_root)
check("broken again after a good read -> WARNING again", len(grab.warnings()), 1)

print("[row 4: annihilation weekly gate unreadable]")
fresh()
with mock.patch("ark_relay.annihilation.WeeklyGate._load", side_effect=RuntimeError("gate broke")):
    check("unreadable -> still no reopen value", plan._annihilation_reopens(None), "")
    w = grab.warnings()
    check("unreadable -> one WARNING with the traceback", (len(w), bool(w and w[0].exc_info)), (1, True))
    plan._annihilation_reopens(None)
    check("same condition again -> no second WARNING", len(grab.warnings()), 0)
with mock.patch("ark_relay.annihilation.WeeklyGate._load", return_value={}):
    plan._annihilation_reopens(None)
    check("readable -> no WARNING", len(grab.warnings()), 0)
with mock.patch("ark_relay.annihilation.WeeklyGate._load", side_effect=RuntimeError("gate broke")):
    plan._annihilation_reopens(None)
    check("broken again after a good read -> WARNING again", len(grab.warnings()), 1)

print("[row 5: maintenance_lines unexpected error]")
fresh()
import datetime as _dt  # noqa: E402
day = _dt.date(2026, 10, 11)
with mock.patch("ark_relay.maintenance.today", side_effect=KeyError("window")):
    check("error -> no line (as before)", plan.maintenance_lines(day), [])
    w = grab.warnings()
    check("error -> one WARNING with the traceback", (len(w), bool(w and w[0].exc_info)), (1, True))
    plan.maintenance_lines(day)
    check("same condition again -> no second WARNING", len(grab.warnings()), 0)
with mock.patch("ark_relay.maintenance.today", return_value={}):
    plan.maintenance_lines(day)
    check("works -> no WARNING", len(grab.warnings()), 0)
with mock.patch("ark_relay.maintenance.today", side_effect=KeyError("window")):
    plan.maintenance_lines(day)
    check("broken again after it worked -> WARNING again", len(grab.warnings()), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
