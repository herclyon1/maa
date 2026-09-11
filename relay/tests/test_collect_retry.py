"""Per-route gathering retry, checked against the real files of 2026-09-11.

That day routes 15 and 16 failed in the 10:18 run, AUTO-MAS re-ran all 17,
and upstream declined a per-route retry (MaaEnd/MaaEnd#5660). The fixtures
are the AUTO-MAS log of that run, MXU's logged override line, and MaaEnd's
zh_cn locale.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import collect_retry as cr
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


FX = Path(__file__).resolve().parent / "fixtures" / "collect-retry-2026-09-11"
zh = json.loads((FX / "zh_cn.json").read_text(encoding="utf-8"))
labels = cr.failed_labels_from_locale(zh)

print("[失败路线从真实日志里认出来，id 来自 MaaEnd 自己的语言文件]")
check("语言文件里有 25 条路线的失败文案", len(labels), 25)
check("标签去掉了 HTML", "路线15：红矛叶采集失败" in labels)
routes = cr.failed_routes((FX / "automas-MaaEnd-06-17-17.log").read_text(encoding="utf-8"), labels)
check("认出 15 和 16", routes, ["AutoCollectRoute15", "AutoCollectRoute16"])
check("走通的路线不算失败", "AutoCollectRoute1" not in routes)
check("没有失败行就是空", cr.failed_routes("[x] 路线1：受蚀玉化叶\n[y] 任务完成: 自动采集", labels), [])

print("\n[补跑参数来自 MXU 自己记的那一行，只留失败的路线，补上今天]")
parts = cr.logged_override((FX / "mxu-app-override-line.log").read_text(encoding="utf-8"))
check("解析出 MXU 的 26 段覆盖", len(parts), 26)
ov = cr.build_override(parts, routes, "saturday")
check("留下 15 的 Start/Dispatch", ov.get("AutoCollectRoute15Start") == {"enabled": True} and "AutoCollectRoute15Dispatch" in ov)
check("别的路线全部去掉", not any(k.startswith("AutoCollectRoute1S") or k.startswith("AutoCollectRoute4") for k in ov))
check("周六加进排班", ov["AutoCollectScheduleEnabled"]["attach"].get("saturday"), True)
check("原来的周五还在（attach 合并不是覆盖）", ov["AutoCollectScheduleEnabled"]["attach"].get("friday"), True)
check("键位等其他覆盖原样保留", ov.get("EnterCameraModeLongPress"), {"key": 82})
check("没有那一行就拒绝", cr.logged_override("2026-09-11 10:18:19 INFO [App] nothing here"), None)
try:
    cr.build_override(parts, routes, "someday")
    check("不认识的星期报错", False)
except ValueError:
    check("不认识的星期报错", True)

print("\n[结果从 MaaFW 的节点事件判，只看这次之后的]")
maafw = ("[2026-09-11 00:12:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15End\"}\n"
         "[2026-09-11 00:54:39.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute16Start\"}\n"
         "[2026-09-11 00:57:10.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute16End\"}\n"
         "[2026-09-11 00:58:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15Failed\"}\n")
v = cr.judge(maafw, ["AutoCollectRoute15", "AutoCollectRoute16"], "00:50:00")
check("16 走完了", v["AutoCollectRoute16"], True)
check("15 这次失败（之前那次 End 在窗口外不算）", v["AutoCollectRoute15"], False)
check("没出现的路线没有结论", cr.judge(maafw, ["AutoCollectRoute3"], "00:50:00"), {"AutoCollectRoute3": None})

print("\n[连续两天补跑失败＝复发，请人工]")
store = tmpdir() / "failures.json"
d1 = cr.record_failures(store, "2026-09-11", ["AutoCollectRoute15"])
check("第一天记一笔", d1, {"AutoCollectRoute15": ["2026-09-11"]})
check("一天不算复发", cr.recurrent(d1), [])
d2 = cr.record_failures(store, "2026-09-12", ["AutoCollectRoute15", "AutoCollectRoute16"])
check("第二天连着＝复发", cr.recurrent(d2), ["AutoCollectRoute15"])
check("16 只有一天，不算", "AutoCollectRoute16" not in cr.recurrent(d2))
d3 = cr.record_failures(store, "2026-09-14", ["AutoCollectRoute16"])
check("隔一天不连续，不算复发", cr.recurrent(d3), ["AutoCollectRoute15"])
cr.clear_failures(store, ["AutoCollectRoute15"])
check("走通一次就清零", "AutoCollectRoute15" not in json.loads(store.read_text(encoding="utf-8")))

print("\n[账本里取当天最后一趟终末地——AUTO-MAS 自己的重试排在后面]")
led = [{"script": "MAA", "run_id": "a"}, {"script": "MaaEnd", "run_id": "b"}, {"script": "MaaEnd", "run_id": "c"}]
check("取最后一趟", cr.last_maaend_run(led)["run_id"], "c")
check("没有就是 None", cr.last_maaend_run([{"script": "MAA", "run_id": "a"}]), None)
check("路线名是中文", cr.route_label("AutoCollectRoute15", zh), "路线15：红矛叶")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
