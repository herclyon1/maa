"""MAA's drop blocks carry a running total per stage. Both directions are easy
to get wrong, and both have been wrong in production.

The log lines here are the real format, taken from a 2026-08-15 run:

    [2026-08-15 09:06:29.091][INF][TaskQueueViewModel]     <2> TO-5 掉落统计: 
    龙门币 : 864 (+864)
    [2026-08-15 09:06:58.883][INF][TaskQueueViewModel]     <2> 完成任务: 理智作战

The stage line carries a bracketed timestamp; the item lines do not, and the
next timestamped line is what closes the block. An earlier version of this file
used timestamps without brackets, which `_HAS_TS` does not match - so the block
never closed and the tests passed without exercising the real path.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

P = "[INF][TaskQueueViewModel]     <2>"
def ts(hhmmss: str, rest: str) -> str:
    return f"[2026-08-15 {hhmmss}.091]{P} {rest}"

def parse(log: str) -> dict:
    p = Path(tempfile.mkdtemp()) / "run.log"
    p.write_text(log, encoding="utf-8")
    return collector.parse_maa_log(p)

print("[sanity: the real format parses at all]")
out = parse("\n".join([
    ts("09:04:12", "开始行动 1~6 次, -72理智"),
    ts("09:06:29", "TO-5 掉落统计: "),
    "龙门币 : 864 (+864)",
    ts("09:06:58", "完成任务: 理智作战"),
]))
check("stage found", out.get("stages"), ["TO-5"])
check("drop found", out.get("drop_statistics"), {"龙门币": 864})
check("sanity spent", out.get("sanity_spent"), 72)

print("\n[one stage, two batches - running total, take the last]")
out = parse("\n".join([
    ts("09:04:12", "开始行动 1~10 次, -120理智"),
    ts("09:25:00", "TO-5 掉落统计: "),
    "龙门币 : 1440 (+1440)",
    "技巧概要·卷2 : 2 (+2)",
    "当前次数 : 10",
    ts("09:26:00", "开始行动 11~17 次, -84理智"),
    ts("09:45:00", "TO-5 掉落统计: "),
    "龙门币 : 2448 (+1008)",
    "技巧概要·卷2 : 4 (+2)",
    "当前次数 : 7",
    ts("09:46:00", "完成任务: 理智作战"),
]))
check("龙门币 = last block, not the sum", out["drop_statistics"]["龙门币"], 2448)
check("技巧概要·卷2", out["drop_statistics"]["技巧概要·卷2"], 4)
check("次数 IS summed", out.get("run_times"), 17)
check("one stage", out.get("stages"), ["TO-5"])
check("sanity summed", out.get("sanity_spent"), 204)

print("\n[two different stages - totals are per stage, summed across]")
out = parse("\n".join([
    ts("21:32:00", "剿灭作战 掉落统计: "),
    "龙门币 : 500 (+500)",
    "当前次数 : 1",
    ts("21:34:00", "完成任务: 剿灭作战"),
    ts("22:10:00", "1-7 掉落统计: "),
    "龙门币 : 2448 (+2448)",
    "当前次数 : 17",
    ts("22:11:00", "完成任务: 理智作战"),
]))
check("龙门币 summed ACROSS stages", out["drop_statistics"]["龙门币"], 2948)
check("both stages", out.get("stages"), ["剿灭作战", "1-7"])
check("次数 summed", out.get("run_times"), 18)

print("\n[two stages, two batches each - both rules at once]")
out = parse("\n".join([
    ts("09:00:00", "剿灭作战 掉落统计: "),
    "龙门币 : 300 (+300)",
    ts("09:05:00", "剿灭作战 掉落统计: "),
    "龙门币 : 500 (+200)",
    ts("09:10:00", "1-7 掉落统计: "),
    "龙门币 : 1000 (+1000)",
    ts("09:20:00", "1-7 掉落统计: "),
    "龙门币 : 2448 (+1448)",
    ts("09:21:00", "完成任务: 理智作战"),
]))
check("500 + 2448", out["drop_statistics"]["龙门币"], 2948)

print("\n[a timestamped line really does close the block]")
# If it did not, 完成任务 and everything after would keep feeding the block.
out = parse("\n".join([
    ts("09:10:00", "1-7 掉落统计: "),
    "龙门币 : 1000 (+1000)",
    ts("09:11:00", "完成任务: 理智作战"),
    "龙门币 : 9999 (+8999)",
]))
check("stray line after the block ignored", out["drop_statistics"]["龙门币"], 1000)

print("\n[medicine]")
out = parse("\n".join([
    ts("09:04:03", "已使用理智药 1(+1)"),
    ts("09:10:00", "1-7 掉落统计: "),
    "龙门币 : 1000 (+1000)",
    ts("09:11:00", "完成任务: 理智作战"),
]))
check("medicine used", out.get("medicine_used"), 1)

print("\n[no drops at all]")
out = parse(ts("21:30:00", "开始任务") + "\n" + ts("21:31:00", "任务完成"))
check("no key", "drop_statistics" in out, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
