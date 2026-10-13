"""A run the overlay ended as failed is pushed with its reason once, without the OCR dump.

Audit 2026-10-13 item 14, two real lines of 2026-10-12 (machine-okww-logs):
* 09:52 the overlay's reason started with the step 「周本领奖：」, but the prefix
  check looked for 「周本：」 only, so the pushed reason named the step twice;
* 11:45 the reason ended in 「整屏读到 [0_1.00, 41/240_1.00, …]」, a whole screen of
  OCR fragments, and that went into the alert and the verdict's detail. It stays in
  the log only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify import collector_okww as co, outcome

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


L1 = ("2026-10-12 09:52:20,812 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本领奖：这一步没做成 "
      "WaitFailedException()，停下不乱点 Traceback (most recent call last):\n"
      "ark_relay.ArkStopped\n")
L2 = ("2026-10-12 11:45:02,507 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本领奖：点了确认后没等到"
      "结算页（没有「退出副本」），停下不按 ESC。整屏读到 [0_1.00, 41/240_1.00, 🌟_0.53, 补充结晶波片_1.00, "
      "确认_1.00] Traceback (most recent call last):\n"
      "ark_relay.ArkStopped\n")
WEEKLY = "2026-10-12 11:40:00,000 INFO TaskExecutor FarmEchoTask:Teleport to Boss Weekly Challenge\n"

print("[the step is named once]")
check("09:52", co._okww_error(L1), "周本领奖：这一步没做成 WaitFailedException()，停下不乱点")
plain = ("2026-10-12 09:52:20,812 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：没进本 "
         "Traceback (most recent call last):\nx.ArkStopped\n")
check("a reason without the step still gets it", co._okww_error(plain), "周本：没进本")

print("\n[the OCR dump stays out of the pushed reason]")
check("11:45 okww_error", co._okww_error(L2), "周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC")
details = [c.detail for c in outcome.okww_checks(WEEKLY + L2, expect_nest=False) if not c.ok]
check("no check detail carries it", any("整屏读到" in d for d in details), False)
check("the weekly item still says why",
      any(d.startswith("周本领奖：点了确认后没等到结算页") for d in details), True)
check("without_screen_dump on a plain reason is the identity",
      outcome.without_screen_dump("周本：没进本"), "周本：没进本")

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
