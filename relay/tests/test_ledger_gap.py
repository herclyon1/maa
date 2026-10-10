"""scripts/mac/ledger-gap.py: a relay.log ERROR with no ledger line is listed.

10-10 04:28:51 the process-start listener's ERROR was fixed (30cc1e94) and never
written into BOARD/报错台账.txt; 验收 found it at 22:4x.
"""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ledger_gap", Path(__file__).resolve().parents[2] / "scripts" / "mac" / "ledger-gap.py")
lg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lg)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


ERR = ["ERR|10-10 04:28:51 ERROR   ark.service  系统的程序启动通知断了 6 秒（远程过程调用失败，0x800706BE），到中继停下时还没重新订上"]
BEFORE = "10-10 17:18 | 开机自检 2 项 ✗（16:14，中继二部署后）\n10-10 20:33 | 样图坐车层\n"
AFTER = BEFORE + "10-10 22:41 游戏-中继一 | relay.log 10-10 04:28:51 ERROR「系统的程序启动通知断了 6 秒」| 根因 | 已解决\n"

check("the 10-10 ledger before the entry: listed", len(lg.gaps(ERR, BEFORE)), 1)
check("after the entry: nothing", lg.gaps(ERR, AFTER), [])
check("date and minute must be on one line", lg.gaps(ERR, "10-10 something\n04:28 elsewhere\n") != [], True)
check("another day's 04:28 does not count", lg.gaps(ERR, "10-09 04:28 x\n") != [], True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
