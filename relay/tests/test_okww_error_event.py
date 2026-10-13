"""The reason a run failed is read from the last event's own tracebacks, grouped by time.

OK-WW prints one raise as several tracebacks (the task, DailyTask.run_task_by_class,
TaskExecutor's 「Daily Task exception stopped」); the innermost one carries the
reason. collector_okww._okww_error grouped them by distance in the text (6000
characters). On 2026-09-01 06:35 (tests/replay/2026-09-01/wuwa/OK-WW-06-35-43.log)
the stacks between one event's headers were 36352 / 36937 characters long, so the
task's own header fell out and the reason became the wrapper's 「任务执行：等一个画面没等到」.
Audit 2026-10-13 item 7: grouped by timestamp now (headers within 2 s = one event).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify import collector_okww as co

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


print("[the real 09-01 log: the weekly claim's own wait, not the wrapper]")
real = (Path(__file__).resolve().parent / "replay" / "2026-09-01" / "wuwa" / "OK-WW-06-35-43.log"
        ).read_text(encoding="utf-8", errors="replace")
err = co._okww_error(real)
check("names the task", err.startswith("周本："), True)
check("the wait it timed out on", "等一个画面没等到" in err and "10 秒" in err, True)

STACK = "".join(f'  File "x{i}.py", line {i}, in f\n    g()\n' for i in range(600))   # ~16 KB


def head(ts, who, msg):
    return f"2026-09-01 {ts} ERROR TaskExecutor {who}:{msg} Traceback (most recent call last):\n"


print("\n[one event, headers far apart in the text but within 2 s: grouped]")
text = ("2026-09-01 10:50:13,335 INFO TaskExecutor TaskExecutor:wait_until timeout <f> 10 seconds\n"
        + head("10:50:13,348", "FarmEchoTask", "farm 4c error, try handle monthly card")
        + STACK + "ok.task.exceptions.WaitFailedException\n\n"
        + head("10:50:14,879", "DailyTask", "run_task_by_class <class 'src.task.FarmEchoTask.FarmEchoTask'>")
        + STACK + "ok.task.exceptions.WaitFailedException\n\n"
        + head("10:50:15,017", "TaskExecutor", "📅 Daily Task exception stopped")
        + STACK + "ok.task.exceptions.WaitFailedException\n")
check("the task's own header wins", co._okww_error(text).startswith("周本："), True)

print("\n[two events minutes apart, close in the text: not merged]")
text = (head("10:40:00,000", "NightmareNestTask", "NightmareNestTask Failed")
        + "ok.task.exceptions.TaskDisabledException\n\n"
        + head("10:45:00,000", "TaskExecutor", "📅 Daily Task exception stopped")
        + "ok.task.exceptions.WaitFailedException\n")
cluster = co._last_event(text, list(co._OKWW_TB_HEAD.finditer(text)))
check("the earlier event stays out", [m.group(1) for m in cluster], ["TaskExecutor"])

print("\n[header lines without a timestamp: the old distance rule]")
text = (" ERROR TaskExecutor FarmEchoTask:x Traceback (most recent call last):\n"
        + " ERROR TaskExecutor TaskExecutor:y Traceback (most recent call last):\n")
check("near in the text: one event",
      len(co._last_event(text, list(co._OKWW_TB_HEAD.finditer(text)))), 2)

print("\n[how long it waited: the timeout line of the same raise, found by time (item 8)]")
# Measured over every real log on 2026-10-13: the timeout line is at most 0.62 s
# before its header, but up to 2558 characters back; the old window was 600.
real = (Path(__file__).resolve().parent / "fixtures" / "m6-okww" / "0921-weekly.log").read_text(encoding="utf-8")
check("09-21: the 10 s wait is said", co._okww_error(real).endswith("（等了 10 秒）"), True)
wait = "2026-09-01 10:50:13,335 INFO TaskExecutor TaskExecutor:wait_until timeout <f> 10 seconds\n"
far = wait + STACK[:5000] + "\n" + head("10:50:13,900", "FarmEchoTask", "farm 4c error, try handle monthly card")
check("5000 characters back, same second: found", co._wait_before(far, far.rindex(" ERROR")), "10")
stale = ("2026-09-01 10:49:00,000 INFO TaskExecutor TaskExecutor:wait_until timeout <f> 7 seconds\n"
         + head("10:50:13,900", "FarmEchoTask", "farm 4c error"))
check("a wait a minute earlier is another event", co._wait_before(stale, stale.rindex(" ERROR")), "")

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
