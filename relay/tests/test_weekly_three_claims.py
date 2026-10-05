"""The weekly boss claims every reward left in one run, not one a day.

The user, 2026-09-29 13:28: the report said 「领了 1 次，本周还剩 1 次」 - one
claim a day, three days for what one Monday run should do. One claim per call
to FarmEchoTask was never a design: until 2026-09-07 the three claims came
from AUTO-MAS retrying an error (replay/2026-09-07/wuwa below). The claim step
then learned to click 「退出副本」, the error and the retries went away, and the
laps after the claim ran in the open world where nothing is claimed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import collector, okww_overlay, weeklyboss
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


REPLAY = Path(__file__).resolve().parent / "replay" / "2026-09-07" / "wuwa"

print("[真实日志：09-07 那三次是报错重试凑的，每次调用只领 1 次]")
first = (REPLAY / "OK-WW-06-00-55.log").read_text(encoding="utf-8", errors="replace")
retry = (REPLAY / "OK-WW-06-08-44.log").read_text(encoding="utf-8", errors="replace")
check("第一趟领了几次", first.count("周本领奖：已点确认"), 1)
check("第一趟领完就报错（AUTO-MAS 因此重试）", "farm 4c error" in first, True)
check("重试那趟进本前剩余", weeklyboss.left_after_claims(retry.split("周本领奖")[0]), 1)
# 09-07 predates the read-back: its 「已点确认」 is a click, so the switch keeps the
# pre-entry reading (2) and the next entry's own reading (1/3, the retry) decides.
check("第一趟之后剩余：没回读就不减，留进本前读数 2", weeklyboss.left_after_claims(first), 2)
check("重试那趟自己读到 1", weeklyboss.left_after_claims(retry), 1)

print("\n[领完之后：还有剩余就走上游进本路径重进，领满才停]")
ns = {}
exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)


class Skip(Exception):
    """Stands in for ok's TaskDisabledException."""


ns["TaskDisabledException"] = Skip
left_of = ns["_weekly_left"]
after = ns["_after_claim"]
check("读出 2/3", left_of("[本周剩余可收取次数：2/3_1.00, x60_0.79]"), 2)
check("读出 3/3（OCR 的全角斜杠）", left_of("本周剩余可收取次数：3／3"), 3)
check("读不到就是 None", left_of("[x60_0.79]"), None)


class Task:
    def __init__(self, left, fail=None):
        self._ark_weekly_left, self.fail = left, fail
        self.entries, self.logs = 0, []

    def log_info(self, msg):
        self.logs.append(msg)

    def teleport_to_configured_boss_and_prepare(self):
        self.entries += 1
        if self.fail:
            raise self.fail


def run(start, laps=3):
    """Upstream's loop, reduced to what matters here: a lap ends in a claim
    while the task is in the realm; after it, _after_claim decides."""
    t = Task(start)
    claims, inside = 0, True
    for _ in range(laps):
        if not inside:
            continue            # open-world lap: incr_drop returns at in_world()
        claims += 1
        inside = after(t)
    return claims, t.entries


check("周一 3/3：一趟领 3 次、重进 2 次", run(3), (3, 2))
check("周二 2/3：一趟领 2 次、重进 1 次", run(2), (2, 1))
check("只剩 1 次：领完不再进本", run(1), (1, 0))
t = Task(1)
after(t)
check("领满写日志", t.logs, ["周本领奖：本周三次已领满，不再进本"])
t = Task(None)
check("读数没读到：照样重进，进本前 0/3 的闸会挡", (after(t), t.entries), (True, 1))
t = Task(3, fail=Skip())
try:
    after(t)
    check("波片不够 / 0/3 的有意跳过要往上抛", "没抛", "抛了")
except Skip:
    check("波片不够 / 0/3 的有意跳过要往上抛", "抛了", "抛了")
t = Task(3, fail=RuntimeError("Teleport to boss failed"))
check("重进失败：不崩，照旧跑完剩下的圈", after(t), False)
check("重进失败写日志", any("重新进本没做成" in m for m in t.logs), True)

print("\n[领奖钩子里真的调了它，且在 try 外面（有意跳过不被吞）]")
src = okww_overlay.source_text()
body = src[src.index("def incr_drop"):src.index("class _EarlyOpen")]
check("退出副本后调 _after_claim", "_after_claim(self)" in body, True)
tail = body[body.index("except Exception as exc"):]
check("_after_claim 在 except 之后", "_after_claim(self)" in tail, True)
check("进本前把剩余次数存下", "self._ark_weekly_left = _weekly_left(text)" in src, True)

print("\n[日报与开关：按游戏计数的最后一次读数（进本前或领完回读）]")
d = tmpdir()


def steps(text):
    f = d / "x.log"
    f.write_text(text, encoding="utf-8")
    return collector.parse_okww_log(f).get("okww_steps") or []


HEAD = "2026-10-05 10:01:00,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
OCR = "2026-10-05 10:02:00,000 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：{k}/3_0.99, x60_0.79]\n"
CLAIM = "2026-10-05 10:03:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
BACK = "2026-10-05 10:03:05,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 {k}/3→{n}/3\n"


def claim(k):
    """One claim the overlay re-read the counter for: k left before it."""
    return CLAIM + BACK.format(k=k, n=k - 1)


three = HEAD + OCR.format(k=3) + claim(3) + OCR.format(k=2) + claim(2) + OCR.format(k=1) + claim(1)
check("一趟三次：日报写本周已领满", steps(three), ["周本（已完成，领了 3 次，本周已领满）"])
check("一趟三次：开关记账剩 0（最后一次回读 1/3→0/3）", weeklyboss.left_after_claims(three), 0)
two = HEAD + OCR.format(k=3) + claim(3) + OCR.format(k=2) + claim(2)
check("波片只够两次：还剩 1 次", steps(two), ["周本（已完成，领了 2 次，本周还剩 1 次）"])
check("3/3 领 1 次还剩 2 次", steps(HEAD + OCR.format(k=3) + claim(3)),
      ["周本（已完成，领了 1 次，本周还剩 2 次）"])
check("只剩 1 次领完：本周已领满", steps(HEAD + OCR.format(k=1) + claim(1)),
      ["周本（已完成，领了 1 次，本周已领满）"])

print("\n[只点了确认、没回读：不算领到，开关不记账]")
clicks = HEAD + OCR.format(k=3) + CLAIM + OCR.format(k=2) + CLAIM + OCR.format(k=1) + CLAIM
check("三次只点确认：日报不写已完成", steps(clicks), ["周本（点了确认 3 次、领完没再读次数，没核实领到）"])
check("三次只点确认：剩余按最后一次读数 1，不减", weeklyboss.left_after_claims(clicks), 1)
check("回读次数没变：剩余按回读的数", weeklyboss.left_after_claims(
    HEAD + OCR.format(k=2) + CLAIM + "x FarmEchoTask:周本领奖：回读次数没变（2/3），这次没领到\n"), 2)
check("回读没读到：剩余按进本前读数", weeklyboss.left_after_claims(
    HEAD + OCR.format(k=2) + CLAIM + "x FarmEchoTask:周本领奖：回读没读到本周剩余次数\n"), 2)
check("一个读数都没有：None", weeklyboss.left_after_claims(HEAD + CLAIM), None)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
