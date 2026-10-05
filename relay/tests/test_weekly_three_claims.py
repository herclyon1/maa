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
check("第一趟之后剩余：读数 2 减去之后领的 1 次", weeklyboss.left_after_claims(first), 1)

print("\n[领完之后：还有剩余就走上游进本路径重进，领满才停]")
ns = {}
exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)


class Skip(Exception):
    """Stands in for ok's TaskDisabledException."""


ns["TaskDisabledException"] = Skip
left_of = ns["_weekly_left"]
after = ns["_after_claim"]
readback = ns["_readback"]
check("读出 2/3", left_of("[本周剩余可收取次数：2/3_1.00, x60_0.79]"), 2)
check("读出 3/3（OCR 的全角斜杠）", left_of("本周剩余可收取次数：3／3"), 3)
check("读不到就是 None", left_of("[x60_0.79]"), None)

# The level page as the game showed it on the way back in, ok-script.log 2026-10-05:
# 22:15:19 after the first claim, 22:17:31 after the second, 22:39:48 after the third.
PAGE = {2: "本周剩余可收取次数：2/3_1.00", 1: "本周剩余可收取次数：1/3_1.00", 0: "本周剩余可收取次数：0/3_0.99"}


class Task:
    def __init__(self, left, reads=(), fail=None):
        self._ark_weekly_left, self.fail, self.reads = left, fail, list(reads)
        self.entries, self.logs, self.errors, self.shots = 0, [], [], []

    def log_info(self, msg):
        self.logs.append(msg)

    def log_error(self, msg, notify=False):
        self.errors.append((msg, notify))

    def screenshot(self, name):
        self.shots.append(name)

    def teleport_to_configured_boss_and_prepare(self):
        """The way back in up to the level page, as click_configured_boss_level reads
        it (the real one runs in test_okww_claim_readback.py)."""
        self.entries += 1
        if self.fail:
            raise self.fail
        raw = self.reads.pop(0)
        now = left_of(raw)
        before, self._ark_claim_before = self._ark_claim_before, None
        readback(self, before, now, raw)
        self._ark_weekly_left = now
        if now == 0:
            raise Skip()            # the 0/3 skip: no 单人挑战


def run(start, reads):
    """Upstream's loop, reduced: every lap ends in a claim inside the realm and
    _after_claim takes the way back in, until a deliberate stop ends the task."""
    t = Task(start, reads)
    claims = 0
    try:
        while claims < 5:
            claims += 1
            after(t)
    except Skip:
        pass
    return claims, t.entries, t


def stops(t):
    try:
        after(t)
    except Skip:
        return True
    return False


c, e, t = run(3, [PAGE[2], PAGE[1], PAGE[0]])
check("周一 3/3：一趟领 3 次，进选等级页 3 次（最后一次只读数，0/3 不进本）", (c, e), (3, 3))
check("每次都回读确认", [m for m in t.logs if "回读确认" in m],
      ["周本领奖：回读确认领到，本周剩余 3/3→2/3", "周本领奖：回读确认领到，本周剩余 2/3→1/3",
       "周本领奖：回读确认领到，本周剩余 1/3→0/3"])
check("没有报错", t.errors, [])
c, e, t = run(2, [PAGE[1], PAGE[0]])
check("周二 2/3：一趟领 2 次", (c, e), (2, 2))
c, e, t = run(1, [PAGE[0]])
check("只剩 1 次：领完回去读一眼 0/3 就停", (c, e), (1, 1))
check("领满写日志", t.logs[0], "周本领奖：本周三次已领满，回选等级页读一眼次数核对（读到 0/3 就不进本）")

t = Task(2, [PAGE[2]])
check("回读次数没变：停下", stops(t), True)
check("回读次数没变：报到手机", t.errors, [("周本领奖：回读次数没变（2/3），这次没领到", True)])
check("回读次数没变：留图", t.shots, ["weekly_claim_unchanged"])
t = Task(3, ["[x60_0.79]"])
check("回读没读到：停下", stops(t), True)
check("回读没读到：报到手机", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
check("回读没读到：原文进日志", any("x60_0.79" in m for m in t.logs), True)
t = Task(3, [PAGE[1]])
check("回读少了两次：对不上也停", (stops(t), t.shots), (True, ["weekly_readback_mismatch"]))

t = Task(None)
check("进本前没读到：停下，不再进本", (stops(t), t.entries), (True, 0))
check("进本前没读到：报到手机", t.errors[0][1] and "没读到本周剩余次数" in t.errors[0][0], True)
t = Task(3, fail=Skip())
try:
    after(t)
    check("波片不够 / 0/3 的有意跳过要往上抛", "没抛", "抛了")
except Skip:
    check("波片不够 / 0/3 的有意跳过要往上抛", "抛了", "抛了")
check("有意跳过不留回读的账", getattr(t, "_ark_claim_before", None), None)
t = Task(3, fail=RuntimeError("Teleport to boss failed"))
check("重进失败、没到选等级页：停下", stops(t), True)
check("重进失败：说了没回读", any("没回读" in m and "Teleport to boss failed" in m for m in t.logs), True)
check("重进失败：报回读没读到", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
check("重进失败：回读的账清掉", t._ark_claim_before, None)

print("\n[领奖钩子里真的调了它，且在 try 外面（有意跳过不被吞）]")
src = okww_overlay.source_text()
body = src[src.index("def incr_drop"):src.index("class _EarlyOpen")]
check("退出副本后调 _after_claim", "_after_claim(self)" in body, True)
tail = body[body.index("except Exception as exc"):]
check("_after_claim 在 except 之后", "_after_claim(self)" in tail, True)
check("进本前把剩余次数存下", "self._ark_weekly_left = now" in src, True)
check("选等级页上做回读", "_readback(self, before, now, raw)" in src, True)

print("\n[日报与开关：按最后一次读数减去之后领的次数]")
d = tmpdir()


def steps(text):
    f = d / "x.log"
    f.write_text(text, encoding="utf-8")
    return collector.parse_okww_log(f).get("okww_steps") or []


HEAD = "2026-10-05 10:01:00,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
OCR = "2026-10-05 10:02:00,000 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：{k}/3_0.99, x60_0.79]\n"
CLAIM = "2026-10-05 10:03:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
three = HEAD + OCR.format(k=3) + CLAIM + OCR.format(k=2) + CLAIM + OCR.format(k=1) + CLAIM
check("一趟三次：日报写本周已领满", steps(three), ["周本（已完成，领了 3 次，本周已领满）"])
check("一趟三次：开关记账剩 0", weeklyboss.left_after_claims(three), 0)
SKIP = "2026-10-05 10:04:00,000 INFO TaskExecutor FarmEchoTask:本周周本次数已领满（0/3），不进本，跳过\n"
back = three + OCR.format(k=0) + SKIP
check("第三次后回读 0/3 再跳过：日报照旧写领了 3 次", steps(back), ["周本（已完成，领了 3 次，本周已领满）"])
check("第三次后回读 0/3：开关记账剩 0", weeklyboss.left_after_claims(back), 0)
two = HEAD + OCR.format(k=3) + CLAIM + OCR.format(k=2) + CLAIM
check("波片只够两次：还剩 1 次", steps(two), ["周本（已完成，领了 2 次，本周还剩 1 次）"])
check("旧样本照旧：3/3 领 1 次还剩 2 次", steps(HEAD + OCR.format(k=3) + CLAIM),
      ["周本（已完成，领了 1 次，本周还剩 2 次）"])
check("只剩 1 次领完：本周已领满", steps(HEAD + OCR.format(k=1) + CLAIM),
      ["周本（已完成，领了 1 次，本周已领满）"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
