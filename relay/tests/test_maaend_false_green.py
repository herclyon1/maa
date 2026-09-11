"""A MaaEnd run that ends cleanly but does no work must not be reported green.

Real logs, 2026-09-10. MaaEnd had updated to v2.28.0-beta.5 at boot; the master
config still carried the old 自动采集 route keys, MaaEnd discarded them on load
(36 「已丢弃保存值」 lines), the scheduler walked zero routes, wrote 「任务完成」
after 38 seconds, AUTO-MAS recorded Success, and the report opened with 全绿.
The user's words, on why a false green is worse than a false red: 「明明没有完成任务，却按照完成任务的通知去报，这个其实比假红更严重」.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.outcome import maaend_checks, summarize

FIX = Path(__file__).parent / "fixtures" / "maaend-2026-09-10"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def bad(checks):
    return {c.label: c.detail for c in checks if not c.ok}


app = (FIX / "app-2026-09-10-4.log").read_text(encoding="utf-8")
collect = (FIX / "MaaEnd-06-08-39.log").read_text(encoding="utf-8")
daily = (FIX / "MaaEnd-05-38-38.log").read_text(encoding="utf-8")

print("[10:08 那趟：自动采集 38 秒报完成，一条路线没走]")
got = maaend_checks(collect + "\n" + app, [])
b = bad(got)
check("自动采集 被判为没干成", "自动采集 真的走了路线" in b)
check("说清是几秒就报完成", "38 秒" in b.get("自动采集 真的走了路线", ""))
check("新版本丢掉旧设置 被判为故障", "新版本认得全部旧设置" in b)
check("说清丢了多少项", "36 项" in b.get("新版本认得全部旧设置", ""))
check("点名 AutoCollectRoutes", "AutoCollectRoutes" in b.get("新版本认得全部旧设置", ""))
check("「跑完」那一项仍然通过", "MaaEnd 跑完" not in b)
msg = summarize(got, "MaaEnd")
check("会给出人话告警", msg is not None and "没干成" in msg)

print("\n[09:39 那趟：日常全做了、基质刷了三次——不能误伤]")
got2 = maaend_checks(daily + "\n2026-09-10 10:08:00 INFO [App] 自动执行任务完成，关闭自身\n", [])
b2 = bad(got2)
check("基质刷取 算干成", "基质刷取 真的刷了" not in b2)
check("没有自动采集就不检查它", not any(k.startswith("自动采集") for k in b2))
check("没有丢设置的行就不报", "新版本认得全部旧设置" not in b2)
check("整趟不报警", summarize(got2, "MaaEnd"), None)

print("\n[协议空间：开了没进去也要报]")
fake = ("[2026-09-10 09:00:00.000] 任务开始: ⚔️协议空间\n"
        "[2026-09-10 09:00:20.000] 任务完成: ⚔️协议空间\n"
        "2026-09-10 09:00:21 INFO [App] 自动执行任务完成，关闭自身\n")
check("协议空间没进去被判为没干成", "协议空间 真的进了" in bad(maaend_checks(fake, [])))
fake_ok = fake.replace("任务完成: ⚔️协议空间", "进入协议空间成功\n[2026-09-10 09:05:00.000] 任务完成: ⚔️协议空间")
check("进了就通过", "协议空间 真的进了" not in bad(maaend_checks(fake_ok, [])))


print("[排班说今天不采，秒完成是对的，不能当假绿]")
skipped = ("[2026-09-11 10:01:51.385] 任务开始: 🧺自动采集\n"
           "[2026-09-11 10:01:51.482] 现在游戏时间是周五，根据执行周期跳过任务\n"
           "[2026-09-11 10:01:51.566] 任务完成: 🧺自动采集\n")
check("按周期跳过不报「没走路线」", "自动采集 真的走了路线" not in bad(maaend_checks(skipped, [])))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
