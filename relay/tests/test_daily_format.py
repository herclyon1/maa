"""日报三家一个版式（用户 2026-09-02：「视觉上要看起来一样」）。

每一趟成功记录都是同样五行、同样顺序、同样标签：做了/消耗/产出/剩余/备注；
没有的写「—」。没跑成的只有一行「备注」。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import core  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

def ent(run_id, script, hh, mm, dur, ok=True, **kw):
    st = datetime(2026, 9, 2, hh, mm, tzinfo=SERVER_TZ)
    e = {"run_id": run_id, "script": script, "user": "u", "ok": ok,
         "started": st.isoformat(), "finished": (st + timedelta(minutes=dur)).isoformat(),
         "duration_known": True, "transitional": False, "failed_tasks": [] if ok else ["x"],
         "raw": {}, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}
    e.update(kw)
    return e

entries = [
    ent("maa", "MAA", 9, 0, 17, raw={"stages": ["1-7"], "run_times": 10, "sanity_spent": 120,
                                       "medicine_used": 1},
        drops={"龙门币": 1440, "固源岩": 25}, recruits={"3★": 2}, sanity=0,
        sanity_full_at="理智将在 2026-09-03 06:07 回满"),
    ent("ww", "OK-WW", 9, 28, 13, raw={"okww_runs": 2, "okww_stamina_left": 8, "okww_backup_stamina": 0,
                                        "okww_stamina_left_exact": True, "okww_nest_full": True,
                                        "okww_steps": ["模拟领域 ×2", "残象聚落（已刷满）"],
                                        "okww_stopped": "体力不够再开一局",
                                        "sanity_full_at": "2026-09-03 08:53"}),
    ent("ef", "MaaEnd", 9, 42, 25, raw={"tasks_done": ["赠送干员礼物", "装备制造"], "protocol_runs": 3,
                                         "sanity_cap": 360},
        sanity=12, drops={"武陵调度券": 320000}),
    ent("bad", "OK-WW", 21, 30, 5, ok=False, failed_tasks=["OK-WW 流程产生错误"]),
]
title, body = core.format_daily("2026-09-02", entries)
print(body)
blocks = [b for b in body.split("\n\n") if b.strip()]
labels = lambda blk: [l.split("　")[0] for l in blk.splitlines()[1:]]
want = ["· 做了", "· 消耗", "· 产出", "· 剩余", "· 备注"]
print("[三家五行一样]")
check("MAA 五行顺序", labels(blocks[0]), want)
check("鸣潮 五行顺序", labels(blocks[1]), want)
check("终末地 五行顺序", labels(blocks[2]), want)
print("[内容进对格子]")
check("MAA 做了", "刷 1-7 ×10" in blocks[0], True)
check("MAA 消耗含吃药", "理智 120，吃药 1" in blocks[0], True)
check("MAA 剩余带回满", "理智 0，次日 06:07 回满" in blocks[0], True)
check("MAA 备注公招", "· 备注　公招 3★×2" in blocks[0], True)
check("鸣潮 做了", "进本 2 次；任务 模拟领域 ×2、残象聚落（已刷满）" in blocks[1], True)
check("鸣潮 消耗宁可留空", "· 消耗　—" in blocks[1], True)
check("鸣潮 剩余", "波片 8/240，备用 0" in blocks[1], True)
check("鸣潮 备注", "残象聚落 落渊南丘 已刷满；体力不够再开一局" in blocks[1], True)
check("终末地 做了", "日常 2 项：1.赠送干员礼物、2.装备制造" in blocks[2], True)
check("终末地 消耗", "· 消耗　协议空间 3 次" in blocks[2], True)
check("终末地 剩余", "· 剩余　理智 12/360" in blocks[2], True)
print("[没跑成的只有一行备注]")
check("失败块两行", len(blocks[3].splitlines()), 2)
check("失败于在备注格", "· 备注　失败于：OK-WW 流程产生错误" in blocks[3], True)
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
