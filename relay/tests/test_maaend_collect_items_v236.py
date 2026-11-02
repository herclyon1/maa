"""MaaEnd v2.36.0-beta.5 picks 自动采集 by item, not by route (installed 2026-10-29 10:27 Beijing).

Real files from that release (tasks/AutoCollect.json and the zh_cn locale, fetched from MaaEnd/MaaEnd at the
tag). The four *Routes checkboxes became *Items checkboxes; the relay logged eight 「没有中文名」 warnings and
the gathering retry stopped recognising failures (账本 #122). Checked here:
- the master's route picks become the items those routes gathered (route 7 gathered two);
- the phone page lists the item lists with Chinese names and real choices, nothing untranslated;
- the retry reads v2.36's failure texts and keeps only the failed item's nodes in its override.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import mastercfg
from ark_relay.features.makeup import collect_retry as cr
from ark_relay.features.verify import collector_maaend as cm, outcome

FIX = Path(__file__).parent / "fixtures" / "maaend-2026-10-29"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    maaend = d / "maaend"
    (maaend / "tasks").mkdir(parents=True)
    (maaend / "locales" / "interface").mkdir(parents=True)
    (maaend / "tasks" / "AutoCollect.json").write_bytes((FIX / "tasks" / "AutoCollect.json").read_bytes())
    (maaend / "locales" / "interface" / "zh_cn.json").write_bytes(
        (FIX / "locales" / "interface" / "zh_cn.json").read_bytes())
    (maaend / "interface.json").write_text(json.dumps({"import": ["tasks/AutoCollect.json"]}), encoding="utf-8")
    automas = d / "automas"
    cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
    cfgdir.mkdir(parents=True)
    master = cfgdir / "mxu-MaaEnd.json"
    old = {
        "AutoCollectValleyIV": {"type": "switch", "value": True},
        "AutoCollectValleyIVRareRoutes": {"type": "checkbox", "caseNames": ["Route4", "Route13"]},
        "AutoCollectValleyIVCommonRoutes": {"type": "checkbox", "caseNames": ["CommonRoute1"]},
        "AutoCollectWuling": {"type": "switch", "value": True},
        "AutoCollectWulingRareRoutes": {"type": "checkbox", "caseNames": ["Route7", "Route15", "Route99"]},
        "AutoCollectWulingCommonRoutes": {"type": "checkbox", "caseNames": ["CommonRoute5"]},
        "AutoCollectMode": {"type": "select", "caseName": "Always"},
    }
    master.write_text(json.dumps({"instances": [{"tasks": [
        {"taskName": "AutoCollect", "enabled": True, "optionValues": old}]}]}), encoding="utf-8")

    changes, note = mastercfg.migrate_maaend_options(automas, maaend)
    print("\n".join("    " + c for c in changes))
    ov = json.loads(master.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["optionValues"]
    check("四号谷地稀有：路线4、13 → 纯晶多齿叶、中黯石",
          ov.get("AutoCollectValleyIVRareItems", {}).get("caseNames"),
          ["item_plant_crylplant_1_2", "item_plant_spcstone_1_2"])
    check("四号谷地一般：线路1 → 映火荞花", ov.get("AutoCollectValleyIVCommonItems", {}).get("caseNames"),
          ["item_plant_moss_spc_1"])
    check("武陵稀有：路线7 → 血菌和武陵石两样，路线15 → 红矛叶",
          ov.get("AutoCollectWulingRareItems", {}).get("caseNames"),
          ["item_plant_mushroom_2_1", "item_plant_spcstone_2_2", "item_plant_crylplant_2_3"])
    check("武陵一般：线路5 → 蓬茸锦草", ov.get("AutoCollectWulingCommonItems", {}).get("caseNames"),
          ["item_plant_grass_spc_1"])
    check("旧的路线项都去掉了", [k for k in ov if k.endswith("Routes")], [])
    check("对不上的路线（Route99）在说明里点了名", any("Route99" in c for c in changes))
    check("区域开关和模式原样留着", (ov["AutoCollectValleyIV"], ov["AutoCollectMode"]["caseName"]),
          ({"type": "switch", "value": True}, "Always"))

    r = mastercfg.read_maaend(automas, maaend)
    A = "AutoCollect/"
    for k in ("AutoCollectValleyIVRareItems", "AutoCollectValleyIVCommonItems",
              "AutoCollectWulingRareItems", "AutoCollectWulingCommonItems"):
        check(f"手机页有 {k}，中文名", any("一" <= ch <= "鿿" for ch in r["labels"].get(A + k, "")))
    check("手机页没有没翻译的项", [k for k in r.get("untranslated", []) if k.startswith(A)], [])
    names = dict((v, n) for n, v in r["options"][A + "AutoCollectWulingRareItems"])
    check("武陵稀有的可选值带中文名", (names.get("item_plant_mushroom_2_1"), names.get("item_plant_spcstone_2_2")),
          ("血菌", "武陵石"))

    zh = json.loads((FIX / "locales" / "interface" / "zh_cn.json").read_text(encoding="utf-8"))
    labels = cr.failed_labels_from_locale(zh)
    check("补跑认得新版失败提示", labels.get("纯晶多齿叶采集失败"), "AutoCollectValleyIVChrysodendra1")
    check("两样一条路线的也认得", labels.get("血菌、武陵石采集失败"), "AutoCollectWulingBloodcapWulingstone1")
    log = "[12:00:01] 纯晶多齿叶采集失败\n[12:03:00] 轻黯石采集失败\n[12:05:00] 星门菌采集失败\n"
    check("从日志里挑出失败的路线", cr.failed_routes(log, labels),
          ["AutoCollectValleyIVChrysodendra1", "AutoCollectValleyIVKalkonyx1", "AutoCollectWulingCosmagaric1"])
    parts = [{
        "__AutoCollectValleyIVChrysodendraDispatch": {"enabled": True},
        "__AutoCollectValleyIVChrysodendraSkipped": {"enabled": True},
        "AutoCollectValleyIVChrysodendra1Start": {"enabled": True},
        "__AutoCollectWulingCrimsonSpearleafDispatch": {"enabled": True},
        "__AutoCollectWulingCrimsonSpearleafSkipped": {"enabled": True},
        "AutoCollectWulingCrimsonSpearleaf1Start": {"enabled": True},
        "AutoCollectScheduleEnabled": {"attach": {"monday": True}},
    }]
    o = cr.build_override(parts, ["AutoCollectValleyIVChrysodendra1"], "thursday")
    check("补跑只留失败那样的调度和路线",
          sorted(k for k in o if "Chrysodendra" in k or "CrimsonSpearleaf" in k),
          ["AutoCollectValleyIVChrysodendra1Start", "__AutoCollectValleyIVChrysodendraDispatch",
           "__AutoCollectValleyIVChrysodendraSkipped"])
    check("今天是采集日", o["AutoCollectScheduleEnabled"]["attach"].get("thursday"), True)
    o2 = cr.build_override([{}], ["AutoCollectWulingCosmagaric1"], "thursday")
    check("日志里没有的那样也会补上调度入口", (o2.get("__AutoCollectWulingCosmagaricDispatch"),
                                         o2.get("AutoCollectWulingCosmagaric1Start")),
          ({"enabled": True}, {"enabled": True}))
    mf = ('[2026-10-29 12:00:00.000][INF] [msg=Node.Action.Starting] {"name":"__AutoCollectValleyIVChrysodendra1Failed"}\n'
          '[2026-10-29 12:00:05.000][INF] [msg=Node.Action.Starting] {"name":"AutoCollectWulingCosmagaric1End"}\n')
    check("补跑结论认新版节点", cr.judge(mf, ["AutoCollectValleyIVChrysodendra1", "AutoCollectWulingCosmagaric1"],
                                     "00:00:00"),
          {"AutoCollectValleyIVChrysodendra1": False, "AutoCollectWulingCosmagaric1": True})

    # Real 2026-11-02 morning MaaEnd-06-37-16 log lines (ledger #134): 16 item-named routes in 1654 s.
    log_1102 = "\n".join([
        "[2026-11-02 10:37:28.880] 开始执行任务, 数量: 1",
        "[2026-11-02 11:02:29.664] 任务开始: 🧺自动采集",
        "[2026-11-02 11:02:29.665] 正在前往四号谷地扫描拥有物资",
        "[2026-11-02 11:02:51.970] 正在前往武陵扫描拥有物资",
        "[2026-11-02 11:03:04.220] 仓库库存同步完成，开始按目标库存筛选采集物",
        "[2026-11-02 11:03:05.320] 采集纯晶多齿叶",
        "[2026-11-02 11:04:52.668] 采集轻黯石",
        "[2026-11-02 11:06:37.493] 采集轻红柱状菌",
        "[2026-11-02 11:07:39.258] 采集中黯石",
        "[2026-11-02 11:10:23.899] 采集晶化多齿叶",
        "[2026-11-02 11:11:23.671] 采集受蚀玉化叶",
        "[2026-11-02 11:13:02.786] 采集至晶多齿叶",
        "[2026-11-02 11:14:00.095] 采集血菌、武陵石",
        "[2026-11-02 11:17:37.438] 采集星门菌",
        "[2026-11-02 11:18:54.406] 采集燎石",
        "[2026-11-02 11:20:59.443] 采集重红柱状菌",
        "[2026-11-02 11:22:42.233] 采集重黯石",
        "[2026-11-02 11:24:21.668] 采集中红柱状菌",
        "[2026-11-02 11:25:10.574] 采集红矛叶",
        "[2026-11-02 11:26:26.877] 采集协议纹石",
        "[2026-11-02 11:28:24.733] 采集塔罗斯菌",
        "[2026-11-02 11:30:03.197] 任务完成: 🧺自动采集",
        "[2026-11-02 11:31:57.991] 自动执行任务完成",
    ])
    checks = {c.label: c.ok for c in outcome.maaend_checks(log_1102, [], own_log=True)}
    check("11-02 早班 16 条新版采集路线判为「自动采集 真的走了路线」", checks.get("自动采集 真的走了路线"), True)
    log_p = d / "0.log"
    log_p.write_text(log_1102, encoding="utf-8")
    parsed = cm.parse_maaend_log(log_p)
    check("11-02 早班路线计数 16/16", (parsed.get("maaend_collect_done"), parsed.get("maaend_collect_total")), (16, 16))

    shot = "2026.11.02-11.21.15.123___MapNavigatorObstacleDevice_InteractPost.png"
    check("新版路线撞上中继器能对上路线 ID",
          cr.blocked_route_ids(log_1102, [shot], zh),
          {"AutoCollectWulingRubyBolete1": [shot]})
    mf_blocked = (
        '[2026-11-02 11:20:59.400][INF] [msg=Node.Recognition.Succeeded] {"name":"AutoCollectWulingRubyBolete1Start"}\n'
        '[2026-11-02 11:22:40.000][INF] [msg=Node.Action.Starting] {"name":"AutoCollectWulingRubyBolete1End"}\n'
    )
    check("补跑复查认得新版路线节点窗口",
          cr.retry_blocked(mf_blocked, ["AutoCollectWulingRubyBolete1"], "11:00:00", [shot]),
          {"AutoCollectWulingRubyBolete1": [shot]})

print("\nall checks passed" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
