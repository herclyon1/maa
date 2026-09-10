"""A failed outcome check must reach the ledger and the daily headline.

Before 2026-09-10 the check only produced a push; the ledger line kept `ok: true`
and the evening report still said 全绿 for a run that walked zero routes.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import core

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


with tempfile.TemporaryDirectory() as d:
    st = core.State(Path(d)) if hasattr(core, "State") else None
    if st is None:
        # The ledger lives on whichever class owns append_ledger/read_ledger.
        owner = next(v for v in vars(core).values()
                     if isinstance(v, type) and hasattr(v, "read_ledger") and hasattr(v, "mark_incomplete"))
        st = owner(Path(d))
    day = "2026-09-10"
    e1 = {"run_id": f"{day}/endfield/MaaEnd-05-38-38", "script": "MaaEnd", "user": "endfield",
          "started": "2026-09-10T09:38:38", "finished": "2026-09-10T10:08:38", "ok": True,
          "failed_tasks": [], "raw": {"tasks_done": ["赠送干员礼物", "装备制造", "拜访好友", "基建任务"]}}
    e2 = {"run_id": f"{day}/endfield/MaaEnd-06-08-39", "script": "MaaEnd", "user": "endfield",
          "started": "2026-09-10T10:08:39", "finished": "2026-09-10T10:09:35", "ok": True,
          "failed_tasks": [], "raw": {"tasks_done": ["自动采集"]}}
    with st.ledger_path(day).open("w", encoding="utf-8") as f:
        f.write(json.dumps(e1, ensure_ascii=False) + "\n" + json.dumps(e2, ensure_ascii=False) + "\n")

    print("[写回账本]")
    why = ("MaaEnd 这一轮有 2 项没干成，但它自己没报错：\n"
           "· 新版本认得全部旧设置：MaaEnd 新版本不认 36 项旧设置\n"
           "· 自动采集 真的走了路线：自动采集 38 秒就报「任务完成」，日志里没有走了路线的痕迹")
    check("找得到那条并写回", st.mark_incomplete(day, e2["run_id"], why))
    check("找不到的 run_id 返回 False", st.mark_incomplete(day, "nope", why), False)
    back = st.read_ledger(day)
    check("两条都还在", len(back), 2)
    check("第一条没被碰", "incomplete" not in back[0])
    check("第二条带上原因", back[1].get("incomplete"), why)
    check("ok 仍然是 True（不进重试队列）", back[1]["ok"], True)

    print("\n[日报]")
    title, body = core.format_daily(day, back)
    check("标题不再是全绿", "全绿" not in title)
    check("标题说几项没干完", "1 项没干完" in title)
    check("那一趟的图标是 ⚠️", "⚠️ MaaEnd" in body)
    check("正文写明没干完的原因", "没干完：" in body and "自动采集" in body)
    check("多条原因并成一行，冒号后面不带分号", "：；" not in body and "没报错：MaaEnd 新版本" in body)
    check("好的那趟还是 ✅", "✅ MaaEnd" in body)

    print("\n[没有 incomplete 时一切照旧]")
    title2, _ = core.format_daily(day, [e1])
    check("纯绿仍报全绿", "全绿 ✅" in title2)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
