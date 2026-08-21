"""MAA's drop blocks carry a running total per stage. Both directions are easy
to get wrong, and both have been wrong in production."""
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

def parse(log: str) -> dict:
    p = Path(tempfile.mkdtemp()) / "run.log"
    p.write_text(log, encoding="utf-8")
    return collector.parse_maa_log(p)

print("[one stage, two batches - the 2448 regression]")
out = parse("""2026-08-21 09:04:00.123 开始行动 1~10 次
2026-08-21 09:25:00.000 TO-5 掉落统计:
龙门币 : 1440 (+1440)
技巧概要·卷2 : 2 (+2)
当前次数 : 10
2026-08-21 09:26:00.000 开始行动 11~17 次
2026-08-21 09:45:00.000 TO-5 掉落统计:
龙门币 : 2448 (+1008)
技巧概要·卷2 : 4 (+2)
当前次数 : 7
2026-08-21 09:46:00.000 任务完成
""")
check("龙门币 = last block, not the sum", out.get("drop_statistics", {}).get("龙门币"), 2448)
check("技巧概要·卷2", out.get("drop_statistics", {}).get("技巧概要·卷2"), 4)
check("次数 IS summed", out.get("run_times"), 17)
check("one stage", out.get("stages"), ["TO-5"])

print("\n[two different stages - the bug just fixed]")
out = parse("""2026-08-21 21:32:00.000 剿灭作战 掉落统计:
龙门币 : 500 (+500)
当前次数 : 1
2026-08-21 21:34:00.000 开始行动
2026-08-21 22:10:00.000 1-7 掉落统计:
龙门币 : 2448 (+2448)
当前次数 : 17
2026-08-21 22:11:00.000 任务完成
""")
check("龙门币 summed ACROSS stages", out.get("drop_statistics", {}).get("龙门币"), 2948)
check("both stages listed", out.get("stages"), ["剿灭作战", "1-7"])
check("次数 summed", out.get("run_times"), 18)

print("\n[two stages, each with two batches - both rules at once]")
out = parse("""2026-08-21 09:00:00.000 剿灭作战 掉落统计:
龙门币 : 300 (+300)
2026-08-21 09:05:00.000 剿灭作战 掉落统计:
龙门币 : 500 (+200)
2026-08-21 09:10:00.000 1-7 掉落统计:
龙门币 : 1000 (+1000)
2026-08-21 09:20:00.000 1-7 掉落统计:
龙门币 : 2448 (+1448)
2026-08-21 09:21:00.000 done
""")
check("500 + 2448", out.get("drop_statistics", {}).get("龙门币"), 2948)

print("\n[no drops at all]")
out = parse("2026-08-21 21:30:00.000 开始任务\n2026-08-21 21:31:00.000 任务完成\n")
check("no key", "drop_statistics" in out, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
