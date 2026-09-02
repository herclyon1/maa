"""日报三家一个语义模板，以 MAA 为样板（用户 2026-09-02）：

  做了　刷（什么）×次数
  消耗　理智 N，吃药 N（鸣潮：波片 N，备用体力 N；终末地：理智 N，加强剂 N）
  产出　这次刷本的掉落
  剩余　理智 N/上限，回满时刻
  备注　额外任务

鸣潮和终末地的数字全部从它们的真实日志里算出来（夹具是 09-02 / 09-01 实录）。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector, core  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

FX = Path(__file__).parent / "fixtures"
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

print("[鸣潮：从真实日志算出来]")
ww = collector.parse_okww_log(FX / "okww_sim_2026-09-02.log")
check("刷的本", ww.get("okww_farm"), "模拟领域·贝币")
check("产出类别", ww.get("okww_farm_reward"), "贝币")
check("进本 2 局", ww.get("okww_runs"), 2)
check("波片 168→88→8 花了 160", ww.get("okww_stamina_spent"), 160)
check("备用体力没动", ww.get("okww_backup_spent"), None)
check("剩 8", ww.get("okww_stamina_left"), 8)
check("两局都是双倍", ww.get("okww_runs_double"), 2)
check("产出按满难度算：2×84000×2", ww.get("okww_farm_drops"), {"贝币": 336000})
ww["sanity_full_at"] = "2026-09-03 08:53"

print("[终末地：从真实日志算出来]")
ef = collector.parse_maaend_log(FX / "maaend_full_2026-09-01.log")
check("刷本任务", ef.get("maaend_farm"), "基质刷取")
check("地点", ef.get("maaend_farm_place"), "枢纽区")
check("次数", ef.get("maaend_farm_runs"), 2)
check("理智 234→154→74 花了 160", ef.get("maaend_sanity_spent"), 160)
check("刷本掉落只算基质", ef.get("maaend_farm_drops"), {"无暇基质": 6, "高纯基质": 4})
check("没吃加强剂", ef.get("maaend_medicine"), None)
check("剩余理智 74/360", (ef.get("sanity"), ef.get("sanity_cap")), (74, 360))
check("失败清单为空", ef.get("tasks_failed"), None)

print("[三家五行，同一语义]")
entries = [
    ent("maa", "MAA", 9, 0, 17, raw={"stages": ["1-7"], "run_times": 10, "sanity_spent": 120,
                                       "medicine_used": 1},
        drops={"龙门币": 1440, "固源岩": 25}, recruits={"3★": 2}, sanity=0,
        sanity_full_at="理智将在 2026-09-03 06:07 回满"),
    ent("ww", "OK-WW", 9, 28, 13, raw=ww),
    ent("ef", "MaaEnd", 9, 42, 25, raw=ef, sanity=ef["sanity"], sanity_full_at="2026-09-02 21:00"),
    ent("bad", "OK-WW", 21, 30, 5, ok=False, failed_tasks=["OK-WW 流程产生错误"]),
]
title, body = core.format_daily("2026-09-02", entries)
print(body)
blocks = [b for b in body.split("\n\n") if b.strip()]
rows = lambda blk: blk.splitlines()[1:]
check("MAA", rows(blocks[0]), [
    "· 做了　刷 1-7 ×10",
    "· 消耗　理智 120，吃药 1",
    "· 产出　龙门币×1440 固源岩×25",
    "· 剩余　理智 0，次日 06:07 回满（东京 07:07）",
    "· 备注　公招 3★×2"])
check("鸣潮", rows(blocks[1]), [
    "· 做了　刷 模拟领域·贝币 ×2（双倍）",
    "· 消耗　波片 160，备用体力 0",
    "· 产出　贝币×336000",
    "· 剩余　波片 8/240，备用 0，次日 08:53 回满（东京 09:53）",
    "· 备注　残象聚落（已刷满）"])
check("终末地", rows(blocks[2]), [
    "· 做了　刷 基质刷取·枢纽区 ×2",
    "· 消耗　理智 160，加强剂 0",
    "· 产出　无暇基质×6 高纯基质×4",
    "· 剩余　理智 74/360，本日 21:00 回满（东京 22:00）",
    "· 备注　日常 1-9 项完成"])
check("失败的只有一行备注", rows(blocks[3]), ["· 备注　失败于：OK-WW 流程产生错误"])
check("「体力不够再开一局」不再出现", "体力不够" in body, False)
foot = core.daily_footnote(entries)
check("名单当注释放最末", foot, "———————\n日常：1.赠送干员礼物 2.装备制造 3.拜访好友 4.基建任务 5.信用点购物 6.应急理智加强剂 7.选剑演武 8.自动采集 9.日常奖励领取")
check("没有终末地成功记录就没有注释", core.daily_footnote(entries[:2]), "")
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
