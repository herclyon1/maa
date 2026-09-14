"""Phone-order receipts: the relay's answer to each order shows on the phone page."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import modes

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


print("[回执：记下来、最新在后、只留最近几条]")
d = tmpdir()
check("一开始是空的", modes.receipts(d), [])
modes.add_receipt(d, "skip_shutdown", True, "已取消，跑完照常关机")
modes.add_receipt(d, "set_stage", False, "没有这个字段")
r = modes.receipts(d)
check("两条", [(x["action"], x["ok"]) for x in r], [("skip_shutdown", True), ("set_stage", False)])
check("带时间", all(len(x["at"]) == 11 for x in r), True)
for i in range(20):
    modes.add_receipt(d, "x", True, str(i))
check(f"最多 {modes.RECEIPTS_KEEP} 条", len(modes.receipts(d)), modes.RECEIPTS_KEEP)
check("留的是最新的", modes.receipts(d)[-1]["text"], "19")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
