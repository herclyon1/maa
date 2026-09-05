"""账本里一条时间不合法的记录，不能让整天的日报发不出去。

read_ledger 原来只查键在不在。日报和关机判定都要拿 started/finished 去
fromisoformat，值不合法照样 ValueError → 日报发不出 → 关机等日报 → 机器开一夜。
机器一天被硬断电两次，一行写坏是能发生的事。
"""
import json
import pathlib
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ark_relay import core                      # noqa: E402
from ark_relay.config import SERVER_TZ          # noqa: E402

fails = []
d = pathlib.Path(tempfile.mkdtemp())
st = core.State(d)
good = {"run_id": "a", "script": "MAA", "user": "u", "ok": True,
        "started": datetime(2026, 9, 6, 9, 0, tzinfo=SERVER_TZ).isoformat(),
        "finished": datetime(2026, 9, 6, 9, 20, tzinfo=SERVER_TZ).isoformat()}
bad_value = {**good, "run_id": "b", "started": "2026-09-06 09:0"}   # 被截断的一行
bad_type = {**good, "run_id": "c", "finished": None}
(d / "ledger-2026-09-06.jsonl").write_text(
    "\n".join(json.dumps(x) for x in (good, bad_value, bad_type)) + "\n", encoding="utf-8")

rows = st.read_ledger("2026-09-06")
ids = [r["run_id"] for r in rows]
if ids != ["a"]:
    fails.append(f"应只留下合法那条，得到 {ids}")

# 留下的那些，日报模板必须能渲染（这正是原来会炸的地方）
try:
    title, body = core.format_daily("2026-09-06", rows)
    if "MAA" not in body:
        fails.append("日报里没有那条合法记录")
except Exception as exc:  # noqa: BLE001
    fails.append(f"日报渲染炸了：{exc}")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
