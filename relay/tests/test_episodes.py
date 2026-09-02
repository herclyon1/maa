"""假报警两例（2026-09-02 早班实录）：

鸣潮：09:18 客户端更新重启（transitional）、09:20 失败、09:28 成功 →
      日报写了两个 ❌ 还推了 ⚠️ 自愈。应当整串算「更新插曲」：↪️、不计失败。
终末地：服务器维护，三趟每个任务 20 秒内失败、零完成 → 报了三次失败。
      应当认出「进不了游戏」：⏸、不计失败、只发一条说明。
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector, core, efstatus  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

print("[maaend_unreachable：任务全部秒败、零完成]")
def maaend_log(gap_s=20, done_at=None, n=4):
    t = datetime(2026, 9, 2, 9, 56, 23)
    names = ["🎁赠送干员礼物", "🔧装备制造", "🤝拜访好友", "🎁基建任务", "🛍️信用点购物"][:n]
    out = []
    for i, nm in enumerate(names):
        out.append(f"[{t:%Y-%m-%d %H:%M:%S}.249] 任务开始: {nm}")
        t += timedelta(seconds=gap_s)
        kind = "完成" if done_at == i else "失败"
        out.append(f"[{t:%Y-%m-%d %H:%M:%S}.717] 任务{kind}: {nm}")
    out.append(f"[{t:%Y-%m-%d %H:%M:%S}.145] 任务开始: ⛔ 结束进程")
    out.append(f"[{t:%Y-%m-%d %H:%M:%S}.595] 任务失败: ⛔ 结束进程")
    return "\n".join(out)
check("今天的形状 → 进不了游戏", collector.maaend_unreachable(maaend_log()), True)
check("有一个完成 → 不是", collector.maaend_unreachable(maaend_log(done_at=1)), False)
check("每个卡 5 分钟 → 不是（那是真故障）", collector.maaend_unreachable(maaend_log(gap_s=300)), False)
check("只败 2 个 → 不够数", collector.maaend_unreachable(maaend_log(n=2)), False)
check("结束进程那条不算", "结束进程" in maaend_log(), True)

print("[episode_kinds + 日报]")
def ent(run_id, script, hh, mm, dur, ok, transitional=False, raw=None, failed=None):
    st = datetime(2026, 9, 2, hh, mm, tzinfo=SERVER_TZ)
    return {"run_id": run_id, "script": script, "user": "u", "ok": ok,
            "started": st.isoformat(), "finished": (st + timedelta(minutes=dur)).isoformat(),
            "duration_known": True, "transitional": transitional,
            "failed_tasks": failed or ([] if ok else ["x"]), "raw": raw or {}}
today = [
    ent("maa", "MAA", 9, 0, 17, True),
    ent("ww1", "OK-WW", 9, 18, 1, False, transitional=True),
    ent("ww2", "OK-WW", 9, 20, 7, False, failed=["OK-WW 流程产生错误，请检查游戏状态"]),
    ent("ww3", "OK-WW", 9, 28, 13, True),
    ent("ef1", "MaaEnd", 9, 42, 6, False, raw={"maaend_unreachable": True}),
    ent("ef2", "MaaEnd", 9, 49, 6, False, raw={"maaend_unreachable": True}),
    ent("ef3", "MaaEnd", 9, 56, 5, False, raw={"maaend_unreachable": True}),
]
k = core.episode_kinds(today)
check("更新重启那条", k.get("ww1"), "update")
check("紧跟的失败也是插曲", k.get("ww2"), "update")
check("成功那条不标", k.get("ww3"), None)
check("终末地三条都是维护", [k.get(x) for x in ("ef1", "ef2", "ef3")], ["maintenance"] * 3)
title, body = core.format_daily("2026-09-02", today)
check("标题不再是 5 项失败", "维护日跳过，其余全绿 ✅" in title, True)
check("没有 ❌", "❌" in body, False)
check("鸣潮画 ↪️", body.count("↪️ OK-WW"), 2)
check("终末地画 ⏸", body.count("⏸ MaaEnd"), 3)
check("插曲说明", "游戏更新后重跑，不算失败" in body, True)
check("维护说明", "进不了游戏" in body, True)

print("[真故障不能被顺手洗白]")
real = [ent("a", "OK-WW", 9, 18, 7, False), ent("b", "OK-WW", 9, 28, 13, True)]
check("没有更新重启的失败→不是插曲", core.episode_kinds(real), {})
t2, b2 = core.format_daily("2026-09-02", real)
check("标题计 1 项失败", "1 项失败 ⚠️" in t2, True)
streak_no_success = [ent("a", "OK-WW", 9, 18, 1, False, transitional=True), ent("b", "OK-WW", 9, 20, 7, False)]
check("更新重启后最终没成功→仍是失败", core.episode_kinds(streak_no_success), {})

print("[官方公告：今天是不是版本更新日]")
data = json.loads((Path(__file__).parent / "fixtures" / "ef_bulletin_2026-09-02.json").read_text(encoding="utf-8"))
hint = efstatus.update_hint(datetime(2026, 9, 2, 10, 30, tzinfo=SERVER_TZ), fetch=lambda: data)
check("认出今天 10:00 版本更新", hint, "官方公告：今天 09:00 「雪凇幽梦」版本更新")
check("别的日子→空", efstatus.update_hint(datetime(2026, 9, 3, 10, 30, tzinfo=SERVER_TZ), fetch=lambda: data), "")
check("接口挂了→空不炸", efstatus.update_hint(fetch=lambda: (_ for _ in ()).throw(OSError())), "")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
