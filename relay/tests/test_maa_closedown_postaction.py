#!/usr/bin/env python3
"""MAA's CloseDown post-action cut off by AUTO-MAS's own close is not 「开了没收尾」.

Real record, 2026-10-21 (fixtures/maa-2026-10-21/asst-callbacks.log: the task
chain lines of that morning's D:\\ark\\maa\\debug\\asst.log, unchanged). The run
ended with 「任务已全部完成！」 and AllTasksCompleted at 09:19:25.078; MAA's post
action 「退出 明日方舟」 started CloseDown at 09:19:25.579; AUTO-MAS stopped
MAA.exe at 09:19:25.929 and quit LDPlayer instance 1000 itself. CloseDown's
completion receipt never came, and at 09:19:35 the relay pushed 「⚠️ 明日方舟早班
没干完：CloseDown」 to the group (ledger #107).

A CloseDown that starts before the run's tasks are all completed is still a
dangling chain, and any other dangling chain still fails.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify.outcome import maa_checks

LOG = (Path(__file__).parent / "fixtures" / "maa-2026-10-21" / "asst-callbacks.log").read_text(encoding="utf-8")
fails = []


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok or not detail else f": {detail}"))
    if not ok:
        fails.append(name)


def bad(checks):
    return {c.label: c.detail for c in checks if not c.ok}


require("the real record ends with a CloseDown start and no receipt",
        LOG.rstrip().endswith('"taskchain":"CloseDown","taskid":7,"uuid":"d912769d7cb0ae0a"}')
        or 'TaskChainStart {"taskchain":"CloseDown"' in LOG.splitlines()[-1])
got = bad(maa_checks(LOG))
require("CloseDown after AllTasksCompleted is not 「开了没收尾」", "每一项都做到了结尾" not in got, repr(got))

no_all_done = "\n".join(l for l in LOG.splitlines() if "AllTasksCompleted" not in l)
require("without AllTasksCompleted a dangling CloseDown still fails",
        "CloseDown" in bad(maa_checks(no_all_done)).get("每一项都做到了结尾", ""))

lines = LOG.splitlines()
award_start = next(i for i, l in enumerate(lines) if 'TaskChainStart {"taskchain":"Award"' in l)
cut_award = "\n".join(l for i, l in enumerate(lines) if not (i > award_start and '"taskchain":"Award"' in l and "Start" not in l))
require("another dangling chain still fails",
        "Award" in bad(maa_checks(cut_award)).get("每一项都做到了结尾", ""))

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall checks passed")
