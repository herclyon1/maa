"""The ledger tells the truth about killed runs: their verdict and their end.

2026-10-01, seven records. Two were wrong in the ledger and so in the daily
report: MaaEnd's 15:24 attempt (plugin crashed, AUTO-MAS killed it for
「MaaEnd 进程超时」) read as a success, and every timed-out attempt ended at its
log's last line - OK-WW at 09:19 / 11:21 / 13:22 - instead of when AUTO-MAS
killed it (11:20 / 13:21 / 15:23). The JSON verdicts and app.log result lines
below are verbatim from the machine; the run logs keep their real first and
last stamps.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector
from ark_relay.config import SERVER_TZ
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


root = tmpdir() / "AUTO-MAS"
hist = root / "history"
(root / "debug").mkdir(parents=True)
(root / "debug" / "app.log").write_text("\n".join([
    "2026-10-01 09:18:16.344 | INFO     | MAA 自动代理 | MAA 任务结果: Success!, 日志锁已释放",
    "2026-10-01 11:20:12.246 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
    "2026-10-01 13:21:12.400 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
    "2026-10-01 15:23:06.615 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
    "2026-10-01 16:10:00.012 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 进程超时, 日志锁已释放",
    "2026-10-01 16:11:10.839 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 部分任务执行失败: 🎁赠送干员礼物, 日志锁已释放",
    "2026-10-01 17:27:43.100 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: Success!, 日志锁已释放",
]) + "\n", encoding="utf-8")


def record(user, stem, verdict, log_lines):
    d = hist / "2026-10-01" / user
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.json").write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
    (d / f"{stem}.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return collector.parse_record(d / f"{stem}.json", hist)


def at(hh, mm, ss=0):
    return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)


def okww_log(h, m, s, h2, m2, s2):
    return [f"2026-10-01 {h:02d}:{m:02d}:{s:02d},787 INFO MainThread ok:ok-script init v3.6.9-beta.1",
            f"2026-10-01 {h2:02d}:{m2:02d}:{s2:02d},632 INFO MainThread UpdateCard:update_available=False"]


print("[OK-WW's three timed-out attempts end when AUTO-MAS killed them]")
for stem, a, b, want in (("OK-WW-05-18-20", (9, 18, 37), (9, 19, 16), at(11, 20, 12)),
                         ("OK-WW-07-20-22", (11, 20, 35), (11, 21, 10), at(13, 21, 12)),
                         ("OK-WW-09-21-22", (13, 21, 35), (13, 22, 10), at(15, 23, 6))):
    r = record("wuwa", stem, {"general_result": "OK-WW 运行超时"}, okww_log(*a, *b))
    check(f"{stem} failed", r.ok, False)
    check(f"{stem} ends {want:%H:%M:%S}", r.finished, want)
    check(f"{stem} starts where its log starts", r.started, at(*a))

print("\n[MaaEnd 15:24: plugin crashed, killed for 进程超时 -> a failure, ending 16:10:00]")
r = record("endfield", "MaaEnd-11-23-07", {"maaend_result": "MaaEnd 进程超时"}, [
    "[2026-10-01 15:24:12.047] 正在连接窗口... Endfield",
    "[2026-10-01 15:26:00.000] 任务开始: 🎁赠送干员礼物",
    "[2026-10-01 15:27:00.000] 任务完成: 🎁赠送干员礼物",
    "[2026-10-01 15:28:00.000] 任务开始: 🛍️信用点购物",
    "[2026-10-01 15:29:59.681] 信用 ×300"])
check("not a success", r.ok, False)
check("says it timed out", r.failed_tasks, ["MaaEnd 进程超时"])
check("ends 16:10:00", r.finished, at(16, 10, 0))

print("\n[MaaEnd 16:11: a real partial failure keeps its own log end]")
r = record("endfield", "MaaEnd-12-10-02",
           {"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物、🔧装备制造"},
           ["[2026-10-01 16:11:06.462] 正在连接窗口... Endfield",
            "[2026-10-01 16:11:06.808] 稳定性最好，需要游戏窗口保持在最前且不被遮挡，会完全抢占鼠标"])
check("failed", r.ok, False)
check("its tasks", r.failed_tasks, ["赠送干员礼物", "装备制造"])
check("ends 16:11:06", r.finished, at(16, 11, 6))

print("\n[MaaEnd 16:12 Success!, MAA 09:00 Success! - unchanged]")
r = record("endfield", "MaaEnd-12-11-12", {"maaend_result": "Success!"},
           ["[2026-10-01 16:12:15.138] 正在连接窗口... Endfield",
            "[2026-10-01 16:58:19.333] 任务开始: ❌关闭游戏（PC）",
            "[2026-10-01 16:58:22.143] 任务完成: ❌关闭游戏（PC）"])
check("MaaEnd ok", (r.ok, r.finished), (True, at(16, 58, 22)))
r = record("arknights", "MAA-05-00-01", {"maa_result": "Success!"},
           ["[2026-10-01 09:00:50.368][INF][Bootstrapper] ===", "[2026-10-01 09:18:15.000][INF] done"])
check("MAA ok", (r.ok, r.finished), (True, at(9, 18, 15)))

print("\n[MaaEnd finished every task, then never exited and was killed (09-28 11:22 shape)]")
r = record("endfield", "MaaEnd-07-22-00", {"maaend_result": "MaaEnd 进程超时"}, [
    "[2026-10-01 10:29:47.000] 任务开始: 🎁赠送干员礼物",
    "[2026-10-01 10:40:00.000] 任务完成: 🎁赠送干员礼物",
    "[2026-10-01 11:22:10.000] 任务开始: ❌关闭游戏（PC）",
    "[2026-10-01 11:22:10.500] 任务完成: ❌关闭游戏（PC）"])
check("the work was done -> ok", r.ok, True)
check("marked as done-then-hung", r.raw.get("maaend_done_then_hung"), True)
check("its work ended at 11:22:10", r.finished, at(11, 22, 10))

print("\n[no app.log (older day, rotated away) -> keep the log end]")
(root / "debug" / "app.log").unlink()
r = record("wuwa", "OK-WW-01-00-00", {"general_result": "OK-WW 运行超时"}, okww_log(5, 0, 0, 5, 1, 0))
check("falls back to the log", r.finished, at(5, 1, 0))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
