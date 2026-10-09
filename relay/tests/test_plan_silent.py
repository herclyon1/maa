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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
