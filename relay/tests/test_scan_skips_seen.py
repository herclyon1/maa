"""scan() 对处理过的记录不再解析：先按路径算 run_id，见过的直接跳过。

2026-09-07 实测：每个周期把整个 history 目录几百条记录全部重新解析一遍再过滤，
启动一次十几秒、停服务撞 15 秒硬保险、8 月的老失败记录每次都重新报警。
"""
import json, os, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

root = tmpdir()
for day, stem in (("2026-08-25", "MAA-05-00-00"), ("2026-09-07", "MAA-05-00-00")):
    d = root / day / "arknights"; d.mkdir(parents=True)
    (d / f"{stem}.json").write_text(json.dumps({"maa_result": "Success!"}), encoding="utf-8")
    (d / f"{stem}.log").write_text("x\n", encoding="utf-8")
    old = time.time() - 600
    os.utime(d / f"{stem}.json", (old, old))
calls = []
orig = collector.parse_record
collector.parse_record = lambda p, r: calls.append(p.name) or orig(p, r)
seen = {"2026-08-25/arknights/MAA-05-00-00"}
out = collector.scan(root, seen)
ok1 = [r.run_id for r in out] == ["2026-09-07/arknights/MAA-05-00-00"]
ok2 = len(calls) == 1
print("  ", "✓" if ok1 else "✗", "只返回没见过的", [r.run_id for r in out])
print("  ", "✓" if ok2 else "✗", "见过的根本不解析（解析次数）", len(calls))
print("all checks passed" if ok1 and ok2 else "FAILED")
sys.exit(0 if ok1 and ok2 else 1)
