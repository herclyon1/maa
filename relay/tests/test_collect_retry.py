"""Per-route gathering retry, checked against the real files of 2026-09-11.

That day routes 15 and 16 failed in the 10:18 run, AUTO-MAS re-ran all 17,
and upstream declined a per-route retry (MaaEnd/MaaEnd#5660). The fixtures
are the AUTO-MAS log of that run, MXU's logged override line, and MaaEnd's
zh_cn locale.
"""
import http.server
import json
import sys
import threading
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

print("\n[MXU 真正绑定的端口从它自己的日志里读]")
md0 = tmpdir() / "m0"
(md0 / "debug").mkdir(parents=True)
check("没日志就是默认 12701", cr.mxu_port(md0), 12701)
(md0 / "debug" / "mxu-tauri.log").write_text(
    "[2026-09-12][01:27:08][INFO][mxu_lib::web_server] Web server listening on http://127.0.0.1:12701\n"
    "[2026-09-12][01:27:16][INFO][mxu_lib::web_server] Web server listening on http://127.0.0.1:12702 (fallback from default port 12701)\n",
    encoding="utf-8")
check("取最后一次绑定的端口", cr.mxu_port(md0), 12702)

print("\n[run_retry：没有 MXU 记的参数就拒绝，不编；接口封装能发请求]")
md = tmpdir() / "maaend"
(md / "debug").mkdir(parents=True)
(md / "debug" / "2026-09-12-1.log").write_text("2026-09-12 00:00:00 INFO [App] nothing\n", encoding="utf-8")
launched = []
verdict, note = cr.run_retry(md, ["AutoCollectRoute15"], "saturday", spawn=lambda exe, cwd, args: launched.append(exe))
check("拒绝并说明原因", "找不到上一趟采集的参数" in note)
check("拒绝时什么都没启动", launched, [])
check("没有结论", verdict, {"AutoCollectRoute15": None})
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"instances":{"automas":{"connected":true}}}')
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}")
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({"echo": body}).encode())
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
cr.MXU = f"http://127.0.0.1:{srv.server_port}/api"
check("GET 解析 JSON", cr.api("/maa/state")["instances"]["automas"]["connected"], True)
check("POST 带 JSON 体", cr.api("/x", {"a": 1})["echo"], {"a": 1})
srv.shutdown()

print("\n[账本里往回找最后一趟有采集结论的终末地——被手动停掉的重试没有结论，跳过]")
hist = tmpdir() / "history"
(hist / "d").mkdir(parents=True)
(hist / "d" / "b.log").write_text((FX / "automas-MaaEnd-06-17-17.log").read_text(encoding="utf-8"), encoding="utf-8")
(hist / "d" / "c.log").write_text("[2026-09-11 10:46:27.001] 任务开始: 🧺自动采集\n[2026-09-11 10:46:59.263] 线路1：受蚀玉化叶\n", encoding="utf-8")
led = [{"script": "MAA", "run_id": "d/a"}, {"script": "MaaEnd", "run_id": "d/b"}, {"script": "MaaEnd", "run_id": "d/c"}]
rec, rts = cr.latest_gathering_run(led, hist, labels)
check("跳过没结论的 c，取 b", rec["run_id"], "d/b")
check("b 的失败路线是 15、16", rts, ["AutoCollectRoute15", "AutoCollectRoute16"])
check("一趟都没有就是 None", cr.latest_gathering_run([{"script": "MAA", "run_id": "d/a"}], hist, labels), (None, []))
(hist / "d" / "e.log").write_text("[x] 任务开始: 🧺自动采集\n[y] 任务完成: 🧺自动采集\n", encoding="utf-8")
rec, rts = cr.latest_gathering_run(led + [{"script": "MaaEnd", "run_id": "d/e"}], hist, labels)
check("最后一趟全过就没有要补的", (rec["run_id"], rts), ("d/e", []))
check("路线名是中文", cr.route_label("AutoCollectRoute15", zh), "路线15：红矛叶")

print("\n[AUTO-MAS 自己的重跑轮：母本路线收窄成只剩失败的，下一条记录一到就改回]")
from datetime import datetime  # noqa: E402
root = tmpdir()
mdir = root / "data" / "abc" / "Default" / "ConfigFile"
mdir.mkdir(parents=True)
master = {"instances": [{"tasks": [{"taskName": "AutoCollect", "enabled": True, "optionValues": {
    "AutoCollectSchedule": {"type": "checkbox", "caseNames": ["AutoCollectScheduleSaturday"]},
    "AutoCollectValleyIVRareRoutes": {"type": "checkbox", "caseNames": ["Route4", "Route5", "Route6", "Route13", "Route14"]},
    "AutoCollectWulingRareRoutes": {"type": "checkbox", "caseNames": ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"]},
    "AutoCollectValleyIVCommonRoutes": {"type": "checkbox", "caseNames": []},
    "AutoCollectMode": {"type": "select", "caseName": "Always"}}}]}]}
(mdir / "mxu-MaaEnd.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
class Cfg2:
    automas_dir = root; state_dir = root / "state"
Cfg2.state_dir.mkdir()
note = cr.narrow_master(Cfg2, ["Route15", "Route16", "Route4"], "2026-09-12/endfield/MaaEnd-10-05-00", datetime(2026, 9, 12, 10, 34))
check("收窄有说明", "3/11" in note, True)
doc = json.loads((mdir / "mxu-MaaEnd.json").read_text(encoding="utf-8"))
ov = doc["instances"][0]["tasks"][0]["optionValues"]
check("武陵只剩 15、16", ov["AutoCollectWulingRareRoutes"]["caseNames"], ["Route15", "Route16"])
check("四号谷地只剩 4", ov["AutoCollectValleyIVRareRoutes"]["caseNames"], ["Route4"])
check("排班和模式不动", (ov["AutoCollectSchedule"]["caseNames"], ov["AutoCollectMode"]["caseName"]), (["AutoCollectScheduleSaturday"], "Always"))
check("原表存了", (Cfg2.state_dir / "collect-retry" / "narrow.json").exists(), True)
note2 = cr.narrow_master(Cfg2, ["Route15"], "again", datetime(2026, 9, 12, 11, 0))
saved = json.loads((Cfg2.state_dir / "collect-retry" / "narrow.json").read_text(encoding="utf-8"))
check("第二次收窄不覆盖原表", saved["lists"]["AutoCollectWulingRareRoutes"], ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"])
back = cr.restore_master(Cfg2)
check("改回有说明", "改回原来的 11 条" in back, True)
doc = json.loads((mdir / "mxu-MaaEnd.json").read_text(encoding="utf-8"))
ov = doc["instances"][0]["tasks"][0]["optionValues"]
check("武陵改回", ov["AutoCollectWulingRareRoutes"]["caseNames"], ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"])
check("四号谷地改回", ov["AutoCollectValleyIVRareRoutes"]["caseNames"], ["Route4", "Route5", "Route6", "Route13", "Route14"])
check("记录删掉了", (Cfg2.state_dir / "collect-retry" / "narrow.json").exists(), False)
check("没有记录时改回是空操作", cr.restore_master(Cfg2), "")
check("失败的路线不在表里就不动", cr.narrow_master(Cfg2, ["Route99"], "x", datetime(2026, 9, 12)), "")
check("全部失败也不动（收窄没有意义）", cr.narrow_master(Cfg2, ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17", "Route4", "Route5", "Route6", "Route13", "Route14"], "x", datetime(2026, 9, 12)), "")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
