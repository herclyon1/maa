"""Auto-makeup retries and Endfield gathering retry rounds."""
from __future__ import annotations

# ruff: noqa: PLC0415
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


class _Messages(logging.Handler):
    """Keeps the message of every WARNING-and-above record."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class _NoSrc:
    """An order source with nothing in it."""

    def fetch(self, seen):
        return []


def _part_collect_history_db():
    """AUTO-MAS v5.8.0-beta.2 records runs in data/history.db, not in per-run JSON files."""
    import shutil
    from datetime import timedelta, timezone

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector


    FX = fx_dir(Path(__file__), "fixtures") / "automas-58-history-2026-10-28"
    BJ = timezone(timedelta(hours=8))

    if True:
        root = tmpdir() / "automas"
        shutil.copytree(FX, root)
        history = root / "history"

        recs = collector.scan(history, set())
        by = {r.run_id: r for r in recs}
        print("scan 读到：", [(r.run_id, r.script, r.ok) for r in recs])

        check("读到 4 趟（MaaEnd 装更新那一条不算一趟）", len(recs), 4)
        check("run_id 跟旧格式同一种形状", sorted(by), sorted([
            "2026-10-28/arknights/MAA-05-01-00",
            "2026-10-28/wuwa/OK-WW-05-18-01",
            "2026-10-28/wuwa/OK-WW-05-19-51",
            "2026-10-28/endfield/MaaEnd-05-33-08",
        ]))

        maa = by.get("2026-10-28/arknights/MAA-05-01-00")
        if maa:
            check("MAA 成功", maa.ok)
            check("MAA 开始时间（北京）取日志第一行 09:01", maa.started.astimezone(BJ).strftime("%H:%M"), "09:01")
            check("MAA 结束时间（北京）取日志最后一行 09:17", maa.finished.astimezone(BJ).strftime("%H:%M"), "09:17")
            check("MAA 理智从 {kind, value} 拆出来是 2", maa.raw.get("sanity"), 2)
            check("MAA 掉落从 {kind, value} 拆出来、按关卡摊平", (maa.raw.get("drop_statistics") or {}).get("固源岩"), 24)
            check("MAA 公招统计从 {kind, value} 拆出来", maa.raw.get("recruit_statistics"), {"4★": 2, "3★": 1})
            check("MAA 带着 AUTO-MAS 的记录编号", maa.raw.get("automas_record_id"), "71bade62-8710-47f9-bd0d-3ef3f4efab47")
            check("MAA 日志路径是 0.log", maa.log_path and maa.log_path.name, "0.log")

        first = by.get("2026-10-28/wuwa/OK-WW-05-18-01")
        if first:
            check("OK-WW 游戏更新那一趟算过渡、不算失败", (first.transitional, first.failed_tasks), (True, []))
            check("OK-WW 脚本名从前缀读出", first.script, "OK-WW")
        okww = by.get("2026-10-28/wuwa/OK-WW-05-19-51")
        check("OK-WW 重跑那一趟成功", bool(okww and okww.ok))
        end = by.get("2026-10-28/endfield/MaaEnd-05-33-08")
        check("MaaEnd 成功", bool(end and end.ok))
        if end:
            check("MaaEnd 结束时间（北京）10:03", end.finished.astimezone(BJ).strftime("%H:%M"), "10:03")

        # already seen: nothing comes back
        check("都记过的再扫一遍是空的", collector.scan(history, set(by)), [])

    print("\n[audit 11-08 B-01: readers of a ledger entry's log find v5.8's <date>/<record id>/0.log]")
    if True:
        from ark_relay.core.ledger import State, strip_incomplete_items
        from ark_relay.features import collect_retry as cr
        from ark_relay.features import outcome
        end = by.get("2026-10-28/endfield/MaaEnd-05-33-08")
        entry = {"script": "MaaEnd", "run_id": end.run_id, "raw": dict(end.raw)} if end else {}
        got = collector.resolve_history_log(history, entry)
        check("resolve_history_log finds the 0.log by the record id", got and got.parts[-3:],
              ("2026-10-28", "b6acb2fc-cd77-4f28-86dd-6f192c7d2f86", "0.log"))
        check("no record id and no old .log: None", collector.resolve_history_log(history, {"run_id": "2026-10-28/x/y"}), None)
        check("the gathering retry reads the day's MaaEnd log (was: never found, so never retried)",
              cr._history_log(history, entry) == got, True)
        ok = outcome.latest_okww_run_log(history)
        check("latest_okww_run_log finds an OK-WW 0.log through history.db (was: only OK-WW-*.log)",
              bool(ok) and ok[0].parts[-2] in ("978d8567-f7bf-4f9f-b402-6afca1880ba0",
                                               "a1a4259e-e90d-4749-bbbd-57f63d6ffd62"), True)
        two = ("MaaEnd 这一轮有 2 项没干成，但它自己没报错：\n· 自动采集 真的走了路线：30 秒就报\n"
               "· 基质刷取 真的刷了：5 秒就报\n干成的：MaaEnd 跑完")
        check("a re-walked gathering clears only its own item", strip_incomplete_items(two, cr.GATHERING_UNDONE),
              "MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n· 基质刷取 真的刷了：5 秒就报\n干成的：MaaEnd 跑完")
        st_led = State(tmpdir() / "ledstate")
        if end:
            st_led.append_ledger(end)
            st_led.mark_incomplete("2026-10-28", end.run_id, two)
            check("State.clear_incomplete_items rewrites the ledger entry",
                  st_led.clear_incomplete_items("2026-10-28", end.run_id, cr.GATHERING_UNDONE), True)
            check("State.clear_incomplete_items leaves the other undone item",
                  st_led.read_ledger("2026-10-28")[0].get("incomplete"),
                  "MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n· 基质刷取 真的刷了：5 秒就报\n干成的：MaaEnd 跑完")
        check("gathering the only item: cleared",
              strip_incomplete_items("MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n· 自动采集 真的走了路线：x", cr.GATHERING_UNDONE), "")
        check("the gathering settings item is not the retry's to clear",
              strip_incomplete_items("MaaEnd 这一轮没按你的设置跑：\n· 自动采集的设置：3 个路线选项", cr.GATHERING_UNDONE),
              "MaaEnd 这一轮没按你的设置跑：\n· 自动采集的设置：3 个路线选项")
        fw = ("[2026-10-27 22:10:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15End\"}\n"
              "[2026-10-28 10:05:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15Failed\"}\n")
        check("yesterday's later clock time is not after today's retry start",
              cr.judge(fw, ["AutoCollectRoute15"], "2026-10-28 10:00:00"), {"AutoCollectRoute15": False})
        fw2 = ("[2026-10-27 23:58:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15Start\"}\n"
               "[2026-10-28 00:03:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15End\"}\n")
        check("a retry begun before midnight still reads the lines after it",
              cr.judge(fw2, ["AutoCollectRoute15"], "2026-10-27 23:57:00"), {"AutoCollectRoute15": True})

    print("\n[audit 11-08 B-07: history.db failing in a row, a same-second row, a 0.log not there yet]")
    if True:
        import sqlite3

        class _Cap(logging.Handler):
            def __init__(self):
                super().__init__()
                self.rows = []

            def emit(self, r):
                self.rows.append((r.levelname, r.getMessage()))
        cap = _Cap()
        logging.getLogger(collector.log.name).addHandler(cap)
        bad = tmpdir() / "bad" / "automas"
        (bad / "data").mkdir(parents=True)
        (bad / "history").mkdir()
        (bad / "data" / "history.db").write_bytes(b"not a database at all" * 100)
        collector._db_fail_streak[0] = 0
        for _ in range(5):
            collector._db_rows(bad / "history")
        warns = [m for lv, m in cap.rows if lv == "WARNING" and "history.db" in m]
        check("unreadable 5 times in a row: one WARNING (at the 3rd)", len(warns), 1)
        collector._db_rows(history)
        check("read again: the streak is reset", collector._db_fail_streak[0], 0)
        logging.getLogger(collector.log.name).removeHandler(cap)

        # no history.db (AUTO-MAS before v5.8.0-beta.2): the JSON layout alone, no error
        (root / "data" / "history.db").unlink()
        check("没有 history.db 时什么也不读、不报错", collector.scan(history, set()), [])

        twin = tmpdir() / "twin"
        shutil.copytree(FX, twin / "automas")
        db = twin / "automas" / "data" / "history.db"
        con = sqlite3.connect(db)
        row = list(con.execute("SELECT * FROM records WHERE script_name='MAA'").fetchone())
        cols = [r[1] for r in con.execute("pragma table_info(records)")]
        row[cols.index("id")] = "0badc0de-0000-0000-0000-000000000000"
        row[cols.index("timestamp")] = row[cols.index("timestamp")] + 0.2      # same second, a bit later
        row[cols.index("log_path")] = "2026-10-28/0badc0de-0000-0000-0000-000000000000/0.log"
        con.execute(f"INSERT INTO records VALUES ({','.join('?' * len(row))})", row)
        con.commit()
        con.close()
        th = twin / "automas" / "history"
        shutil.copytree(th / "2026-10-28" / "71bade62-8710-47f9-bd0d-3ef3f4efab47",
                        th / "2026-10-28" / "0badc0de-0000-0000-0000-000000000000")
        ids = sorted(r.run_id for r in collector.scan(th, set()) if r.script == "MAA")
        check("two MAA rows of one second: both booked, the later one suffixed",
              ids, ["2026-10-28/arknights/MAA-05-01-00", "2026-10-28/arknights/MAA-05-01-00-0badc0de"])
        (th / "2026-10-28" / "0badc0de-0000-0000-0000-000000000000" / "0.log").unlink()
        collector._db_log_missing.clear()
        ids = [r.run_id for r in collector.scan(th, {"2026-10-28/arknights/MAA-05-01-00"}) if r.script == "MAA"]
        check("its 0.log not there yet: waited for, not booked without it", ids, [])

    if fails:
        print(f"✗ {len(fails)} 项不过")
        sys.exit(1)
    print("PASS test_collect_history_db")


def _part_collect_main():
    """Per-route gathering retry, checked against the real files of 2026-09-11."""
    import http.server
    import json
    import threading

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import collect_retry as cr


    FX = fx_dir(Path(__file__), "fixtures") / "collect-retry-2026-09-11"
    zh = json.loads((FX / "zh_cn.json").read_text(encoding="utf-8"))
    labels = cr.failed_labels_from_locale(zh)

    print("[补跑仍没走通、连续两天没走通：报群；开始补跑、补跑走通：不推，只进日报（2026-10-06 05:07）]")


    def _retry_outcome(verdict, failures_before=None):
        """maybe_run with the retry itself stubbed: (what it sent, with alert or not; its state dir)."""
        import types
        from datetime import datetime as _dt
        sd = tmpdir()
        if failures_before:
            (sd / "collect-retry").mkdir(parents=True)
            (sd / "collect-retry" / "failures.json").write_text(json.dumps(failures_before), encoding="utf-8")
        sent = []
        eng = types.SimpleNamespace(
            cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(sd), history_dir=str(sd), automas_dir=None),
            state=types.SimpleNamespace(read_ledger=lambda d: [], mark_incomplete=lambda *a: True,
                                    clear_incomplete_items=lambda *a: True),
            notifier=types.SimpleNamespace(send=lambda t, b, **kw: sent.append((t, kw.get("alert", False))) or []),
            _scripts_running=lambda: False)
        saved = (cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master)
        cr.latest_gathering_run = lambda entries, hist, labels: ({"run_id": "r1"}, list(verdict))
        cr.run_retry = lambda *a, **k: (dict(verdict), "")
        cr._locale, cr.restore_master = (lambda d: zh), (lambda cfg: "")
        try:
            cr.maybe_run(eng, now=_dt(2026, 9, 12, 12, 0).astimezone(), day="2026-09-12")
        finally:
            cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master = saved
        return sent, sd


    from ark_relay.features import report as _report
    from ark_relay.core import texts as _texts
    from ark_relay.core.notify import route_of as _route_of
    got, _ = _retry_outcome({"AutoCollectRoute15": False})
    check("仍没走通：报群", [x for x in got if x[0] == _texts.COLLECT_RETRY_FAILED], [(_texts.COLLECT_RETRY_FAILED, True)])
    check("…开始补跑那条不发（结果才定）", [x for x in got if x[0] == _texts.COLLECT_RETRY_START], [])
    got, _ = _retry_outcome({"AutoCollectRoute15": None})
    check("没结论：也报群", [x for x in got if x[0] == _texts.COLLECT_RETRY_FAILED], [(_texts.COLLECT_RETRY_FAILED, True)])
    got, _ = _retry_outcome({"AutoCollectRoute15": False}, {"AutoCollectRoute15": ["2026-09-11"]})
    check("连续两天：报群", [x for x in got if x[0] == _texts.COLLECT_RECURRENT], [(_texts.COLLECT_RECURRENT, True)])
    got, sd = _retry_outcome({"AutoCollectRoute15": True})
    check("补跑走通：开始那条不发", [x for x in got if x[0] == _texts.COLLECT_RETRY_START], [])
    check("补跑走通：只有「补跑后全部走完」一条，不带 alert", got, [(_texts.COLLECT_RETRY_OK, False)])
    check("…它走日志，不推", _route_of(_texts.COLLECT_RETRY_OK), "log")
    check("日报 retry_line 严格为空（补跑细节仅进技术日志）",
          (_report.retry_line(sd, "2026-09-12"),
           _report._retry_tech_line(sd, "2026-09-12").startswith("自动采集补跑：走通 ")), ("", True))

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
    check("撞上「战斗中无法使用」先等再点：碰设备出错转去等",
          ov["__MapNavigatorObstacleDevice_InteractPost"]["on_error"][0], "ArkRelayObstacleCombatWait")
    check("…等 8 秒，最多 4 次，之后照 MaaEnd 原样放弃",
          (ov["ArkRelayObstacleCombatWait"]["pre_delay"], ov["ArkRelayObstacleCombatWait"]["max_hit"],
           ov["ArkRelayObstacleCombatWait"]["next"][-1], ov["__MapNavigatorObstacleDevice_InteractPost"]["on_error"][-1]),
          (8000, 4, "__MapNavigatorObstacleDevice_NoHit", "__MapNavigatorObstacleDevice_NoHit"))
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
    v = cr.judge(maafw, ["AutoCollectRoute15", "AutoCollectRoute16"], "2026-09-11 00:50:00")
    check("16 走完了", v["AutoCollectRoute16"], True)
    check("15 这次失败（之前那次 End 在窗口外不算）", v["AutoCollectRoute15"], False)
    check("没出现的路线没有结论", cr.judge(maafw, ["AutoCollectRoute3"], "2026-09-11 00:50:00"), {"AutoCollectRoute3": None})

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

    print("\n[不再收窄母本路线（2026-10-06「我开的任务是谁说要关的」）；旧版本收窄过的照样改回]")
    check("收窄母本的函数没了", hasattr(cr, "narrow_master"), False)
    root = tmpdir()
    mdir = root / "data" / "abc" / "Default" / "ConfigFile"
    mdir.mkdir(parents=True)
    FULL_W = ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"]
    FULL_V = ["Route4", "Route5", "Route6", "Route13", "Route14"]
    master = {"instances": [{"tasks": [{"taskName": "AutoCollect", "enabled": True, "optionValues": {
        "AutoCollectSchedule": {"type": "checkbox", "caseNames": ["AutoCollectScheduleSaturday"]},
        "AutoCollectValleyIVRareRoutes": {"type": "checkbox", "caseNames": ["Route4"]},
        "AutoCollectWulingRareRoutes": {"type": "checkbox", "caseNames": ["Route15", "Route16"]},
        "AutoCollectValleyIVCommonRoutes": {"type": "checkbox", "caseNames": []},
        "AutoCollectMode": {"type": "select", "caseName": "Always"}}}]}]}
    (mdir / "mxu-MaaEnd.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
    class Cfg2:
        automas_dir = root; state_dir = root / "state"
    (Cfg2.state_dir / "collect-retry").mkdir(parents=True)
    (Cfg2.state_dir / "collect-retry" / "narrow.json").write_text(json.dumps({
        "run_id": "2026-09-12/endfield/MaaEnd-10-05-00", "at": "2026-09-12T10:34:00",
        "lists": {"AutoCollectValleyIVRareRoutes": FULL_V, "AutoCollectWulingRareRoutes": FULL_W,
                  "AutoCollectValleyIVCommonRoutes": []}}, ensure_ascii=False), encoding="utf-8")
    back = cr.restore_master(Cfg2)
    check("改回有说明", "改回原来的 11 条" in back, True)
    doc = json.loads((mdir / "mxu-MaaEnd.json").read_text(encoding="utf-8"))
    ov = doc["instances"][0]["tasks"][0]["optionValues"]
    check("武陵改回", ov["AutoCollectWulingRareRoutes"]["caseNames"], FULL_W)
    check("四号谷地改回", ov["AutoCollectValleyIVRareRoutes"]["caseNames"], FULL_V)
    check("排班和模式不动", (ov["AutoCollectSchedule"]["caseNames"], ov["AutoCollectMode"]["caseName"]), (["AutoCollectScheduleSaturday"], "Always"))
    check("记录删掉了", (Cfg2.state_dir / "collect-retry" / "narrow.json").exists(), False)
    check("没有记录时改回是空操作", cr.restore_master(Cfg2), "")
    check("母本里一个字都没再动", json.loads((mdir / "mxu-MaaEnd.json").read_text(encoding="utf-8")), doc)

    # ---------------------------------------------------------------- silent-failure audit
    import types
    from datetime import datetime as _dt2


    class _Lines(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelname, record.getMessage()))


    _LOG = _Lines()
    _ARK = logging.getLogger(cr.log.name.rsplit(".", 1)[0])   # every relay logger's parent
    _ARK.addHandler(_LOG)
    _ARK.setLevel(logging.DEBUG)

    # docs/SILENT-FAILURES-AUDIT.md collect_retry.py:453 - no locale means no failed
    # route can be recognised; that used to be logged as 「全部路线走通」.
    print("\n[MaaEnd locale unreadable: not 「all routes passed」, said once]")
    _sd = tmpdir()
    _eng = types.SimpleNamespace(
        cfg=types.SimpleNamespace(state_dir=_sd, maaend_dir=str(_sd / "maaend"), history_dir=str(_sd), automas_dir=None),
        state=types.SimpleNamespace(read_ledger=lambda d: [], mark_incomplete=lambda *a: True,
                                    clear_incomplete_items=lambda *a: True),
        notifier=types.SimpleNamespace(send=lambda *a, **k: []),
        _scripts_running=lambda: False)
    _saved = (cr.latest_gathering_run, cr.restore_master)
    # What the real one gives: with no labels nothing is recognised as failed.
    cr.latest_gathering_run = lambda entries, hist, labels: ({"run_id": "r1"}, ["AutoCollectRoute15"] if labels else [])
    cr.restore_master = lambda cfg: ""
    cr._LOCALE_SAID.clear()
    try:
        _LOG.lines.clear()
        for _ in range(2):
            check("no retry claimed", cr.maybe_run(_eng, now=_dt2(2026, 9, 12, 12, 0).astimezone(), day="2026-09-12"), False)
        check("never says every route passed", any("全部路线走通" in m for _, m in _LOG.lines), False)
        check("one WARNING for two calls (the shutdown decision calls it repeatedly)",
              len([m for lv, m in _LOG.lines if lv == "WARNING" and "路线" in m]), 1)
        (_sd / "maaend" / "locales" / "interface").mkdir(parents=True)
        (_sd / "maaend" / "locales" / "interface" / "zh_cn.json").write_text("{ broken", encoding="utf-8")
        cr._LOCALE_SAID.clear()
        _LOG.lines.clear()
        cr.maybe_run(_eng, now=_dt2(2026, 9, 12, 12, 0).astimezone(), day="2026-09-12")
        check("corrupt locale: warned too", len([m for lv, m in _LOG.lines if lv == "WARNING"]), 1)
    finally:
        cr.latest_gathering_run, cr.restore_master = _saved

    # docs/SILENT-FAILURES-AUDIT.md collect_retry.py:235 - a corrupt failures.json was
    # silently reset, so the two-day 复发性 alarm could never fire.
    print("\n[failures.json unreadable: said, and the bad file kept aside before it is replaced]")
    _store = tmpdir() / "collect-retry" / "failures.json"
    _store.parent.mkdir(parents=True)
    _store.write_text('{"AutoCollectRoute15": ["2026-09-11"', encoding="utf-8")
    _LOG.lines.clear()
    _d = cr.record_failures(_store, "2026-09-12", ["AutoCollectRoute15"])
    check("today is still recorded", _d, {"AutoCollectRoute15": ["2026-09-12"]})
    check("a WARNING says the history was unreadable",
          len([m for lv, m in _LOG.lines if lv == "WARNING" and "failures" in m]), 1)
    _aside = [p for p in _store.parent.iterdir() if p.name != "failures.json"]
    check("the unreadable file is copied aside, byte for byte",
          [p.read_text(encoding="utf-8") for p in _aside], ['{"AutoCollectRoute15": ["2026-09-11"'])


def _part_collect_blocked():  # noqa: C901
    import urllib.error
    """A gathering route that hit 「战斗中无法使用」 is booked as not gathered and re-run (ledger #29).

Route 10 (重红柱状菌) walks past a relay device; when a fight is on, the game says
「战斗中无法使用，请脱离战斗后尝试」, MaaEnd saves an on_error picture of the node
MapNavigatorObstacleDevice_InteractPost, and still ends the route normally - no
「采集失败」 line, AutoCollectRoute10End in maafw.log. Route 10 then picked up 2
(10-05), 0 (10-08) and 4 (10-12) against 6-10 on good runs, and nothing said so:
relay.log 10-14 09:59:16 says the retry found nothing to re-run: 「…全部路线走通，没有要补的」.

Fixtures (tests/fixtures/collect-blocked-1005-1012) are the 自动采集 stretch of the
real AUTO-MAS history logs (2026-10-05 MaaEnd-06-39-48, 10-08 MaaEnd-06-34-21,
10-12 MaaEnd-06-04-00 and MaaEnd-06-58-38; MaaEnd-06-47-30 is the whole 2026-09-11 run
that was cut short after its 「路线5：轻黯石」 line) and the route 9-11 node lines of
maafw.bak.2026.10.12-10.56.34.166.log. The picture names are the real ones from
MaaEnd's debug/on_error; the 10-05 one is recorded to the second only
(归档-1012/今日报错-1005.txt:18, 11:17:28), so its milliseconds are 000.

    Formerly test_collect_blocked_1012.py.
    """
    import json
    import os
    import types
    from datetime import datetime


    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="", ARK_LOG_FILE=str(TMP / "relay.log"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import ledger as ledger_rows, texts
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.core.notify import route_of
    from ark_relay.features import collect_retry as cr
    from ark_relay.features import report
    from ark_relay.features import machinecheck as mc
    from ark_relay.features import collector_maaend as cm, outcome

    FX = fx_dir(Path(__file__), "fixtures") / "collect-blocked-1005-1012"
    ZH = json.loads((fx_dir(Path(__file__), "fixtures") / "collect-retry-2026-09-11" / "zh_cn.json")
                    .read_text(encoding="utf-8"))
    R10 = "路线10：重红柱状菌"
    PIC = "{}___MapNavigatorObstacleDevice_InteractPost.png"
    P1005 = PIC.format("2026.10.05-11.17.28.000")
    P1008A = PIC.format("2026.10.08-10.17.01.129")   # the 05-29-15 run's, outside 06-34-21's routes
    P1008 = PIC.format("2026.10.08-10.59.41.495")
    P1012A = PIC.format("2026.10.12-10.44.55.895")
    P1012 = PIC.format("2026.10.12-11.25.16.239")


    def log(name):
        return (FX / name).read_text(encoding="utf-8")


    def maaend_dir(*pics):
        d = tmpdir()
        (d / "debug" / "on_error").mkdir(parents=True)
        (d / "locales" / "interface").mkdir(parents=True)
        (d / "locales" / "interface" / "zh_cn.json").write_text(json.dumps(ZH, ensure_ascii=False), encoding="utf-8")
        for p in pics:
            (d / "debug" / "on_error" / p).write_bytes(b"")
        return d


    print("[每一趟：出错截图落在路线10 的时段里 → 记成路线10 没采到]")
    for name, pics, want in (("MaaEnd-06-39-48.log", [P1005], P1005),
                             ("MaaEnd-06-34-21.log", [P1008A, P1008], P1008),
                             ("MaaEnd-06-04-00.log", [P1012A, P1012], P1012A),
                             ("MaaEnd-06-58-38.log", [P1012A, P1012], P1012)):
        got = cm.blocked_routes(log(name), pics) if hasattr(cm, "blocked_routes") else None
        check(f"{name}: 只有路线10，截图 {want[:23]}", got, {R10: [want]})

    print("\n[日报那一行：16/17 条，路线10 撞上「战斗中无法使用」没采到（10-05 那趟）]")
    src = tmpdir() / "MaaEnd-06-39-48.log"
    src.write_text(log("MaaEnd-06-39-48.log"), encoding="utf-8")
    raw = cm.parse_maaend_log(src, maaend_dir(P1005))
    check("记下这条没采到", raw.get("maaend_collect_blocked"), [R10])
    check("17 条里 16 条算走通", (raw.get("maaend_collect_done"), raw.get("maaend_collect_total")), (16, 17))
    fin = datetime(2026, 10, 5, 11, 30, 13)
    block = "\n".join(ledger_rows._block({"script": "MaaEnd", "ok": True, "raw": raw}, fin))
    line = next((x for x in block.split("；") + block.splitlines() if "自动采集" in x and "走通" in x), "")
    check("日报原文仅列正常完成路线数，不含撞上/没采到报错文案",
          ("自动采集 16/17 条走通" in block, "战斗中无法使用" not in block, "没采到" not in block),
          (True, True, True))
    print("    " + line.strip())
    check("日报这句是人话", texts.plain(line), [])

    print("\n[半路断掉的那趟（09-11 06-47-30，最后一行是「路线5：轻黯石」）：后来的截图不算它的]")
    later = PIC.format("2026.09.11-12.30.00.000")
    cut = log("MaaEnd-06-47-30.log")
    check("半路断掉：后面的截图都不认成路线5", cm.blocked_routes(cut, [later, P1005, P1008, P1012A, P1012]), {})
    check("…路线5 的时段就停在日志最后一行", cm.route_windows(cut)[-1][1:],
          (datetime(2026, 9, 11, 10, 55, 6, 912000), datetime(2026, 9, 11, 10, 55, 6, 912000)))
    in_r4 = PIC.format("2026.09.11-10.53.40.000")
    check("…前面的路线照旧能认（10:53:40 落在路线4）", cm.blocked_routes(cut, [in_r4]), {"路线4：纯晶多齿叶": [in_r4]})
    src = tmpdir() / "MaaEnd-06-47-30.log"
    src.write_text(cut, encoding="utf-8")
    raw = cm.parse_maaend_log(src, maaend_dir(later))
    check("日报那行不写「撞上…没采到」", raw.get("maaend_collect_blocked"), None)
    check("5 条照旧都算走通", (raw.get("maaend_collect_done"), raw.get("maaend_collect_total")), (5, 5))

    print("\n[跑完当场的核对：不判失败（不进群），交给关机前补跑；不再算「已重试恢复」]")
    text = log("MaaEnd-06-04-00.log") + "\n2026-10-12 10:57:01 INFO  [App] 自动执行任务完成，关闭自身\n"
    checks = outcome.maaend_checks(text, [P1012A], own_log=True)
    retry = [c for c in checks if c.kind == getattr(outcome, "RETRY", "?")]
    check("路线10 交给补跑", [c.label for c in retry],
          [texts.collect_blocked_check(R10)] if hasattr(texts, "collect_blocked_check") else ["?"])
    check("没有失败项（这时不进群，补跑结果才定）", [c.label for c in checks if not c.ok], [])
    check("不再写成「出错截图 1 张（已重试恢复）」", [c.label for c in checks if "已重试恢复" in c.label], [])
    check("说给人听的话是人话", texts.plain(retry[0].label) if retry else ["?"], [])

    print("\n[关机前补跑：真实 10-08 那趟（AUTO-MAS 整轮重跑的 06-34-21）补路线10]")


    def maybe_run(verdict, failures_before=None, day="2026-10-08", pics=(P1008A, P1008)):
        """maybe_run over the real history log and picture; only MXU's part is stubbed.
    Returns (routes handed to the retry, what was sent, the day's stamp)."""
        sd, hist, md = tmpdir(), tmpdir(), maaend_dir(*pics)
        (hist / "2026-10-08" / "endfield").mkdir(parents=True)
        (hist / "2026-10-08" / "endfield" / "MaaEnd-06-34-21.log").write_text(log("MaaEnd-06-34-21.log"), encoding="utf-8")
        if failures_before:
            (sd / "collect-retry").mkdir(parents=True)
            (sd / "collect-retry" / "failures.json").write_text(json.dumps(failures_before), encoding="utf-8")
        sent, asked = [], []
        eng = types.SimpleNamespace(
            cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(md), history_dir=str(hist),
                                      automas_dir=None),
            state=types.SimpleNamespace(read_ledger=lambda d: [{"script": "MaaEnd",
                                                                "run_id": "2026-10-08/endfield/MaaEnd-06-34-21"}],
                                        mark_incomplete=lambda *a: True,
                                        clear_incomplete_items=lambda *a: True),
            notifier=types.SimpleNamespace(send=lambda t, b, **kw: sent.append((t, b, kw.get("alert", False))) or []),
            _scripts_running=lambda: False)
        saved = (cr.run_retry, cr._locale, cr.restore_master)
        cr.run_retry = lambda md, routes, *a, **k: (asked.append(list(routes)) or {r: verdict for r in routes}, "")
        cr._locale, cr.restore_master = (lambda d: ZH), (lambda cfg: "")
        from ark_relay.features import makeup
        saved_mc = makeup._machinecheck
        makeup._machinecheck = lambda *a, **k: None
        try:
            cr.maybe_run(eng, now=datetime(2026, 10, 8, 12, 0, tzinfo=SERVER_TZ), day=day)
        finally:
            cr.run_retry, cr._locale, cr.restore_master = saved
            makeup._machinecheck = saved_mc
        stamp = sd / "collect-retry" / f"{day}.json"
        return asked, sent, (json.loads(stamp.read_text(encoding="utf-8")) if stamp.exists() else {}), (sd, md)


    asked, sent, stamp, (sd, md) = maybe_run(True)
    check("补的是路线10（没有「采集失败」那一行也补）", asked, [["AutoCollectRoute10"]])
    check("补跑走通：不进群，只进日报", [(t, route_of(t, alert=a)) for t, _, a in sent],
          [(texts.COLLECT_RETRY_OK, "log")])
    check("日报 retry_line 严格为空；技术日志写清为什么补",
          (report.retry_line(sd, "2026-10-08", md),
           report._retry_tech_line(sd, "2026-10-08", md)),
          ("", "自动采集补跑：第一趟撞上「战斗中无法使用」没采到：路线10：重红柱状菌；走通 路线10：重红柱状菌"))
    check("…技术日志那句是人话", texts.plain(report._retry_tech_line(sd, "2026-10-08", md)), [])
    asked, sent, stamp, _ = maybe_run(False)
    check("补跑还没采到：照旧报群", [(t, a) for t, _, a in sent], [(texts.COLLECT_RETRY_FAILED, True)])
    asked, sent, stamp, _ = maybe_run(False, {"AutoCollectRoute10": ["2026-10-07"]})
    check("连续两天：照旧按复发报群", [(t, a) for t, _, a in sent], [(texts.COLLECT_RECURRENT, True)])

    print("\n[MaaEnd 的路线名里找不到这条：说一次，不每个关机判断都说（每条警告都会进群）]")


    class _Warns(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.n = 0

        def emit(self, record):
            self.n += "路线名里找不到" in record.getMessage()


    warns = _Warns()
    cr.log.addHandler(warns)
    no_label = {k: v for k, v in ZH.items() if k != "option.AutoCollectRoute10.label"}
    for _ in range(2):
        got = cr.blocked_route_ids(log("MaaEnd-06-34-21.log"), [P1008], no_label)
    check("认不出就不补，也不瞎猜", got, {})
    check("两次判断只警告一次", warns.n, 1)
    cr.log.removeHandler(warns)

    print("\n[补跑时又撞上：路线10 走到了 End，但截图在 Start 和 End 之间 → 判没走通]")
    fw = log("maafw-2026-10-12-routes9-11.log")
    check("只看 End 会判走通（maafw 10:45:39 AutoCollectRoute10End）", cr.judge(fw, ["AutoCollectRoute10"], "2026-10-12 10:40:00"),
          {"AutoCollectRoute10": True})
    got = cr.retry_blocked(fw, ["AutoCollectRoute10"], "2026-10-12 10:40:00", [P1012A, P1012]) \
        if hasattr(cr, "retry_blocked") else None
    check("截图 10:44:55 在路线10 的 10:43:58–10:45:39 里", got, {"AutoCollectRoute10": [P1012A]})
    check("补跑开始前的截图不算", cr.retry_blocked(fw, ["AutoCollectRoute10"], "2026-10-12 10:46:00", [P1012A])
          if hasattr(cr, "retry_blocked") else None, {})

    print("\n[上机核对 #29：按截图认，不再按日志里的提示原文（那句话哪份日志都没有）]")
    mc.load()
    REC = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-58-38", script="MaaEnd", user="endfield",
                    started=datetime(2026, 10, 12, 11, 9, 47, tzinfo=SERVER_TZ),
                    finished=datetime(2026, 10, 12, 11, 36, 56, tzinfo=SERVER_TZ), ok=True, failed_tasks=[], raw={})


    def c29(checks, raw=None, pics=(P1012A, P1012)):
        n = types.SimpleNamespace(sent=[])
        n.send = lambda t, b="", alert=False, **kw: n.sent.append((t, alert)) or []
        n.send_group = lambda t, b="": n.send(t, b, alert=True)
        r = dict(mc.judge(tmpdir(), "run", {"rec": REC, "raw": raw or {}, "log_text": log("MaaEnd-06-58-38.log"),
                                            "maaend_dir": str(maaend_dir(*pics)),
                                            "outcome": None if checks is None else {"checks": checks}},
                          notifier=n, now=datetime(2026, 10, 12, 21, 0, tzinfo=SERVER_TZ))).get("#29")
        if r is not None:
            print(f"    #29 {r.status}: {r.evidence}")
        return r.status if r else None, r.evidence if r else ""


    good = outcome.maaend_checks(log("MaaEnd-06-58-38.log"), [P1012])
    st, ev = c29(good, {"maaend_collect_total": 17, "maaend_collect_blocked": [R10]})
    check("记成没采到、交给补跑：PASS", (st, R10 in ev, P1012 in ev), ("PASS", True, True))
    st, ev = c29([outcome.Check("出错截图 1 张（已重试恢复）", True)])
    check("核对没记它（改之前的样子）：FAIL", st, "FAIL")
    st, ev = c29(good, {"maaend_collect_total": 17})
    check("日报那行没写：FAIL", st, "FAIL")
    st, ev = c29(None, {"maaend_collect_total": 17, "maaend_collect_blocked": [R10]})
    check("失败的那趟（没做结果核对）：日报记了就 PASS", st, "PASS")
    st, ev = c29(None, {"maaend_collect_total": 17})
    check("失败的那趟：日报也没记：FAIL", st, "FAIL")

    print("\n[边界：同一秒里按毫秒分（截图名、历史日志、maafw.log 都带毫秒），日志和补跑用同一条规矩]")
    R11 = "路线11：重黯石"
    ms = {k: PIC.format("2026.10.12-10.45.39." + k) for k in ("400", "500", "600")}
    check("in_window 是半开区间", [cm.in_window(datetime(2026, 1, 1, 0, 0, s), datetime(2026, 1, 1, 0, 0, 1),
                                                datetime(2026, 1, 1, 0, 0, 2)) for s in (0, 1, 2)]
          if hasattr(cm, "in_window") else None, [False, True, False])
    check("截图名的毫秒：MaaFW 不补零，「.93」是 93 毫秒",
          cm.shot_time(PIC.format("2026.10.15-16.39.29.93")), datetime(2026, 10, 15, 16, 39, 29, 93000))
    check("截图名的毫秒：.895", cm.shot_time(P1012A), datetime(2026, 10, 12, 10, 44, 55, 895000))
    check("截图名只隔一个下划线的也认（2026-10-08 的 AutoCollectRoute1Start）",
          cm.shot_time("2026.10.08-10.01.43.463_AutoCollectRoute1Start.png"), datetime(2026, 10, 8, 10, 1, 43, 463000))
    for k, want_log, want_fw in (("400", R10, "AutoCollectRoute10"),   # before End .489 and 路线11 .533
                                 ("500", R10, "AutoCollectRoute10"),   # after End, before Route11 is announced
                                 ("600", R11, "AutoCollectRoute11")):  # after 路线11 .533 / Route11 .510
        check(f"日志：10:45:39.{k} 算{want_log[:4]}",
              cm.blocked_routes(log("MaaEnd-06-04-00.log"), [ms[k]]), {want_log: [ms[k]]})
        check(f"补跑：10:45:39.{k} 算 {want_fw}（和日志一致）",
              cr.retry_blocked(fw, ["AutoCollectRoute10", "AutoCollectRoute11"], "2026-10-12 10:40:00", [ms[k]]),
              {want_fw: [ms[k]]})
    # A retry of route 10 alone, stopped short (no task-end event, as after tasks/stop on a
    # timeout): its window ends at its End node. With the task's end it runs on to that,
    # as the history log's last route does (below).
    fw10 = "\n".join(x for x in fw.splitlines() if "AutoCollectRoute11" not in x)
    check("补跑只补路线10、半路停了（没有任务结束）：时段停在它的 End（10:45:39.489），.500 不算它的",
          cr.retry_blocked(fw10, ["AutoCollectRoute10"], "2026-10-12 10:40:00", [ms["400"], ms["500"]]),
          {"AutoCollectRoute10": [ms["400"]]})
    # 11:36:55.978 is 06-58-38's 「任务完成: 🧺自动采集」: .900 is still 路线17's, .990 no route's.
    END_IN, END_EDGE = PIC.format("2026.10.12-11.36.55.900"), PIC.format("2026.10.12-11.36.55.990")
    check("日志：「任务完成: 自动采集」之前 78 毫秒的截图算路线17",
          cm.blocked_routes(log("MaaEnd-06-58-38.log"), [END_IN]), {"路线17：塔罗斯菌": [END_IN]})
    check("日志：「任务完成: 自动采集」之后的截图不算任何路线",
          cm.blocked_routes(log("MaaEnd-06-58-38.log"), [END_EDGE]), {})
    st, ev = c29(outcome.maaend_checks(log("MaaEnd-06-58-38.log"), [END_EDGE]),
                 {"maaend_collect_total": 17}, pics=(END_EDGE,))
    check("#29：这张也不算这一趟的（不报「认不出是哪条路线」）", st, None)

    print("\n[#29 和跑完当场的核对看同一批截图、同一个时间（截图名里的时间）]")
    # The outcome check used to take the round's pictures by file time and #29 by name
    # time: a picture whose file time is off (copied, touched later) was #29's and not the
    # check's, and #29 then failed 「核对没把它记成没采到」 on a picture the check never saw.
    from ark_relay.features import handle as runchecks, handle as verdict

    hist = tmpdir() / "MaaEnd-06-58-38.log"
    hist.write_text(log("MaaEnd-06-58-38.log"), encoding="utf-8")


    def end_to_end(pic, mtime):
        """verdict._verify_outcome over the real history log, then #29 on what it kept."""
        md = maaend_dir(pic)
        os.utime(md / "debug" / "on_error" / pic, (mtime.timestamp(), mtime.timestamp()))
        rec = RunRecord(run_id=REC.run_id, script="MaaEnd", user="endfield", started=REC.started,
                        finished=REC.finished, ok=True, failed_tasks=[], raw={}, log_path=hist)
        eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=str(md), state_dir=tmpdir()))
        verdict._verify_outcome(eng, rec)
        checked = runchecks._OUTCOME.pop(rec.run_id, None)
        booked = [c.label for c in (checked or {}).get("checks") or [] if c.kind == outcome.RETRY]
        n = types.SimpleNamespace(sent=[])
        n.send = lambda t, b="", alert=False, **kw: n.sent.append((t, alert)) or []
        n.send_group = lambda t, b="": n.send(t, b, alert=True)
        r = dict(mc.judge(tmpdir(), "run", {"rec": rec, "raw": {"maaend_collect_total": 17,
                                                                "maaend_collect_blocked": [R10]},
                                            "log_text": log("MaaEnd-06-58-38.log"), "maaend_dir": str(md),
                                            "outcome": checked},
                          notifier=n, now=datetime(2026, 10, 12, 21, 0, tzinfo=SERVER_TZ))).get("#29")
        return booked, (r.status if r else None)


    # P1012 is named 11:25:16 (inside the run); its file written two days later.
    booked, st = end_to_end(P1012, datetime(2026, 10, 14, 9, 0, tzinfo=SERVER_TZ))
    check("文件时间在这一趟外、名字在里面：核对记了路线10", booked, [texts.collect_blocked_check(R10)])
    check("…#29 判的就是这一张：PASS（不再 FAIL「核对没把它记成没采到」）", st, "PASS")
    # Named the morning before, its file time inside the run: the run's picture by neither.
    old_pic = PIC.format("2026.10.11-11.25.16.239")
    booked, st = end_to_end(old_pic, datetime(2026, 10, 12, 11, 25, 16, tzinfo=SERVER_TZ))
    check("名字在这一趟外、文件时间在里面：核对不记", booked, [])
    check("…#29 也不判", st, None)

    print("\n[只隔一个下划线的息壤中继器截图：日报、补跑名单、补跑结果、#29 用同一个认法]")
    ONE = "{}_MapNavigatorObstacleDevice_InteractPost.png"
    P1008_1, P1012_1 = ONE.format("2026.10.08-10.59.41.495"), ONE.format("2026.10.12-11.25.16.239")
    P1012A_1 = ONE.format("2026.10.12-10.44.55.895")
    has_matcher = hasattr(cm, "is_obstacle_shot")
    check("一个下划线的息壤中继器截图算", cm.is_obstacle_shot(P1012_1) if has_matcher else None, True)
    check("三个下划线的也算", cm.is_obstacle_shot(P1012) if has_matcher else None, True)
    check("别的节点的截图不算", cm.is_obstacle_shot("2026.10.08-10.01.43.463_AutoCollectRoute1Start.png")
          if has_matcher else None, False)
    md1 = maaend_dir(P1012_1, "2026.10.12-11.20.00.000_AutoCollectRoute1Start.png")
    check("on_error 里只挑出息壤中继器那张", cm.obstacle_shots(md1), [P1012_1])
    src = tmpdir() / "MaaEnd-06-58-38.log"
    src.write_text(log("MaaEnd-06-58-38.log"), encoding="utf-8")
    raw1 = cm.parse_maaend_log(src, md1)
    check("日报那行：路线10 没采到、16/17 条走通",
          (raw1.get("maaend_collect_blocked"), raw1.get("maaend_collect_done"), raw1.get("maaend_collect_total")),
          ([R10], 16, 17))
    check("补跑名单（_blocked_in）有路线10", cr._blocked_in(src, md1, ZH), {"AutoCollectRoute10": [P1012_1]})
    check("补跑结果：又撞上就判没走通", cr.retry_blocked(fw, ["AutoCollectRoute10"], "2026-10-12 10:40:00", [P1012A_1]),
          {"AutoCollectRoute10": [P1012A_1]})
    st, ev = c29(outcome.maaend_checks(log("MaaEnd-06-58-38.log"), [P1012_1]), raw1, pics=(P1012_1,))
    check("#29：核对和日报都记了这张：PASS", st, "PASS")
    asked, _, _, _ = maybe_run(True, pics=(P1008A, P1008_1))
    check("关机前补跑真去补路线10", asked, [["AutoCollectRoute10"]])

    print("\n[最后一条路线：日志和补跑都到任务结束为止（不是一个到「任务完成」、一个到 End）]")
    TASK_END = ('[2026-10-12 10:56:34.150][INF][Px2472][Tx52502][Utils/EventDispatcher.hpp][L65]'
                '[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.Succeeded] '
                '[details={"entry":"AutoCollectSchedule","hash":"","task_id":200000001,"uuid":""}]')
    check("任务结束那一行认的是补跑发的那个任务（ENTRY）", cr.ENTRY in cr._TASK_END.pattern, True)
    fw_end = fw + "\n" + TASK_END + "\n"
    both = ["AutoCollectRoute10", "AutoCollectRoute11"]
    tail_pic, after_pic = PIC.format("2026.10.12-10.50.00.000"), PIC.format("2026.10.12-10.56.34.200")
    hist11 = log("MaaEnd-06-04-00.log").split("[2026-10-12 10:47:16.806] 路线12")[0] \
        + "[2026-10-12 10:56:34.179] 任务完成: 🧺自动采集\n"
    check("日志：路线11 的 End 之后、任务完成之前的截图算路线11",
          cm.blocked_routes(hist11, [tail_pic]), {R11: [tail_pic]})
    check("补跑：同一张也算路线11（以前停在 End 10:47:16，判走通）",
          cr.retry_blocked(fw_end, both, "2026-10-12 10:40:00", [tail_pic]), {"AutoCollectRoute11": [tail_pic]})
    check("日志：任务完成之后的截图不算", cm.blocked_routes(hist11, [after_pic]), {})
    check("补跑：任务结束之后的截图也不算", cr.retry_blocked(fw_end, both, "2026-10-12 10:40:00", [after_pic]), {})
    check("只补路线10：时段到任务结束，.500 也算它的（和日志一样）",
          cr.retry_blocked(fw10 + "\n" + TASK_END + "\n", ["AutoCollectRoute10"], "2026-10-12 10:40:00",
                           [ms["400"], ms["500"]]),
          {"AutoCollectRoute10": [ms["400"], ms["500"]]})

    print("\n[没跑完的那趟：「界面没卡住」照旧写出那张截图的名字，路线10 只记一次]")
    # 06-04-00 as it is: no 「自动执行任务完成」 line (AUTO-MAS re-ran it).
    checks = outcome.maaend_checks(log("MaaEnd-06-04-00.log"), [P1012A])
    stuck = [c for c in checks if c.label == "界面没卡住"]
    check("「MaaEnd 跑完」判没跑完", [c.ok for c in checks if c.label == "MaaEnd 跑完"], [False])
    check("「界面没卡住」判失败、写了截图名", [(c.ok, P1012A in c.detail) for c in stuck], [(False, True)])
    check("路线10 还是只交给补跑一次", [c.label for c in checks if c.kind == outcome.RETRY],
          [texts.collect_blocked_check(R10)])

    print("\n[2026-11-23 (#191): InteractPost 截图按 OCR 区分「战斗中无法使用」和路边捡掉落物]")
    check("真战斗挡住（10:55 实机 OCR）算", cm.has_combat_block_text("战斗中无法使用请脱离战斗尝试 | 中继器"), True)
    check("真战斗挡住（11:02 实机 OCR 错字 战→戲）也算", cm.has_combat_block_text("戲斗中无法使用，请离战斗后尝沣"), True)
    check("真战斗挡住（无→天 容错）也算", cm.has_combat_block_text("战斗中天法使用请脱离战门后尝"), True)
    check("路边捡协议纹石/灼壳虫（11:41 实机 OCR）不算",
          cm.has_combat_block_text("背包空间已满，已丢弃部分物品在场景内 | 协议纹石 | 灼壳虫"), False)
    check("大世界探索界面（11:49 实机 OCR）不算",
          cm.has_combat_block_text("探索 | 日常·表象研究 | 前往异常点拍摄照片"), False)
    check("空 OCR 文本不算", cm.has_combat_block_text(""), False)
    md_ocr = maaend_dir(P1012, P1012A)
    loot_ocr = lambda _p: "背包空间已满，已丢弃部分物品在场景内 | 协议纹石 | 灼壳虫"  # noqa: E731
    combat_ocr = lambda _p: "戲斗中无法使用，请离战斗后尝沣"  # noqa: E731
    broken_ocr = lambda _p: None  # noqa: E731
    check("日志：路边捡东西的 InteractPost 不算被挡",
          cm.blocked_routes(log("MaaEnd-06-58-38.log"), [P1012], maaend_dir=md_ocr, ocr_fn=loot_ocr), {})
    check("日志：真「战斗中无法使用」仍算被挡",
          cm.blocked_routes(log("MaaEnd-06-58-38.log"), [P1012], maaend_dir=md_ocr, ocr_fn=combat_ocr), {R10: [P1012]})
    check("日志：OCR 失败（返回 None）时保守仍算被挡",
          cm.blocked_routes(log("MaaEnd-06-58-38.log"), [P1012], maaend_dir=md_ocr, ocr_fn=broken_ocr), {R10: [P1012]})
    check("补跑：路边捡东西的 InteractPost 不判路线失败",
          cr.final_verdict(fw, ["AutoCollectRoute10"], "2026-10-12 10:40:00", [], "", [P1012A],
                           maaend_dir=md_ocr, ocr_fn=loot_ocr),
          ({"AutoCollectRoute10": True}, {}))
    check("补跑：真「战斗中无法使用」仍判路线失败",
          cr.final_verdict(fw, ["AutoCollectRoute10"], "2026-10-12 10:40:00", [], "", [P1012A],
                           maaend_dir=md_ocr, ocr_fn=combat_ocr),
          ({"AutoCollectRoute10": False}, {"AutoCollectRoute10": [P1012A]}))
    from ark_relay.core import desktop as _desk
    from ark_relay.features import machinechecks as _mcs
    _orig_ocr = _desk.ocr_image_file
    cm._COMBAT_SHOT_CACHE.clear()
    try:
        _desk.ocr_image_file = loot_ocr
        done_log = log("MaaEnd-06-58-38.log") + "\n2026-10-12 11:32:00 自动执行任务完成\n"
        loot_checks = outcome.maaend_checks(done_log, [P1012], maaend_dir=md_ocr)
        check("核对：路边捡东西不记 RETRY", [c for c in loot_checks if c.kind == outcome.RETRY], [])
        check("核对：落进「出错截图 1 张（已重试恢复）」且为绿",
              [(c.label, c.ok) for c in loot_checks if "出错截图" in c.label],
              [("出错截图 1 张（已重试恢复）", True)])
        src_loot = tmpdir() / "MaaEnd-06-58-38-loot.log"
        src_loot.write_text(log("MaaEnd-06-58-38.log"), encoding="utf-8")
        raw_loot = cm.parse_maaend_log(src_loot, md_ocr)
        check("日报：17/17 全部走通、无被挡路线",
              (raw_loot.get("maaend_collect_blocked"), raw_loot.get("maaend_collect_done"), raw_loot.get("maaend_collect_total")),
              (None, 17, 17))
        ctx_loot = {"script": "MaaEnd", "rec": REC, "log_text": log("MaaEnd-06-58-38.log"),
                    "raw": raw_loot, "maaend_dir": md_ocr,
                    "outcome": {"checks": loot_checks, "shots": [P1012]}}
        check("#29：路边捡东西不触发、不误报 FAIL", _mcs._c29(ctx_loot), None)
    finally:
        _desk.ocr_image_file = _orig_ocr
        cm._COMBAT_SHOT_CACHE.clear()

    print("\n[补跑时又撞上「战斗中无法使用」的路线，在同一次补跑里单独再走一轮，按第二轮的结果算（账本 #170）]")
    A, B = "AutoCollectRoute10", "AutoCollectRoute11"


    def fwline(ts, msg, name=None):
        det = ('{"name":"%s"}' % name) if name else '{"entry":"AutoCollectSchedule","hash":"","task_id":1,"uuid":""}'
        return (f"[{ts}][INF][Px1][Tx1][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] "
                f"!!!OnEventNotify!!! [handle=true] [msg={msg}] [details={det}]")


    def walk(day_hm, rid, end="End"):
        return [fwline(f"{day_hm}:05.000", "Node.Recognition.Succeeded", rid + "Start"),
                fwline(f"{day_hm}:55.000", "Node.Action.Starting", rid + end)]


    S1, S2 = "2026-11-12 11:40:00", "2026-11-12 11:45:20"
    round1 = "\n".join(walk("2026-11-12 11:41", B) + walk("2026-11-12 11:43", A)
                       + [fwline("2026-11-12 11:45:10.000", "Tasker.Task.Succeeded")])
    hit1, hit2 = ONE.format("2026.11.12-11.43.30.000"), ONE.format("2026.11.12-11.46.30.000")
    end2 = fwline("2026-11-12 11:48:10.000", "Tasker.Task.Succeeded")
    walked2 = round1 + "\n" + "\n".join(walk("2026-11-12 11:46", A) + [end2])
    check("只走一轮：撞上的那条判没走通，记下那张图", cr.final_verdict(round1, [B, A], S1, [], "", [hit1]),
          ({B: True, A: False}, {A: [hit1]}))
    check("第二轮走通：两条都算走通，没有再撞上的", cr.final_verdict(walked2, [B, A], S1, [A], S2, [hit1]),
          ({B: True, A: True}, {}))
    check("第二轮又撞上：还是没走通，记的是第二轮那张图", cr.final_verdict(walked2, [B, A], S1, [A], S2, [hit1, hit2]),
          ({B: True, A: False}, {A: [hit2]}))
    failed2 = round1 + "\n" + "\n".join(walk("2026-11-12 11:46", A, end="Failed") + [end2])
    check("第二轮这条路线自己失败：没走通", cr.final_verdict(failed2, [B, A], S1, [A], S2, [hit1])[0], {B: True, A: False})
    check("第二轮没留下这条路线的结果（比如超时停掉）：不拿第一轮的 End 当走通",
          cr.final_verdict(round1, [B, A], S1, [A], S2, [hit1]), ({B: True, A: False}, {}))
    check("两轮都够时间：中途停掉的判断留足两轮", cr.STAMP_STALE.total_seconds() >= (cr.ROUNDS * 20 + 12) * 60, True)

    from ark_relay.features import efstart, maaend_launch
    from ark_relay.features import collector_maaend as cm2


    def two_rounds(second_text, again, shots, start_fails=False):
        """_bring_up_and_run over a fake MXU: returns (got_v, note, evidence, the overrides sent)."""
        sent_over, fw_now = [], {"text": ""}
        agents = {"n": 0}    # the agents the last task left attached, as MXU keeps them (#111)

        def api(path, body=None, timeout=30):
            if path.endswith("/agent/stop"):
                agents["n"] = 0
                return {}
            if path.endswith("/tasks/start"):
                if start_fails and sent_over:
                    raise OSError("connection reset")
                if agents["n"]:
                    raise urllib.error.HTTPError(path, 500, "agent failed to start", {}, None)
                agents["n"] = 2
                sent_over.append(json.loads(body["tasks"][0]["pipeline_override"]))
                fw_now["text"] = round1 if len(sent_over) == 1 else second_text
                return {}
            if "/maa/windows" in path:
                return [{"handle": 1}]
            return {"instances": {"automas": {"connected": True, "resource_loaded": True, "is_running": False}}}

        stamps = [S1, S2, "2026-11-12 11:49:00"]
        clock = types.SimpleNamespace(sleep=lambda s: None, strftime=lambda fmt: stamps.pop(0) if stamps else "2026-11-12 11:59:00")
        saved = (cr.api, cr._wait, cr._running, cr.mxu_port, cr.time, cr._close_game, cr._stop_agents, cr._maafw_text,
                 efstart.run_on_desktop, maaend_launch.restore_override, cm2.obstacle_shots)
        cr.api, cr._wait, cr._running, cr.mxu_port, cr.time = api, (lambda pred, seconds, step=3.0: pred()), \
            (lambda names: {"MaaEnd.exe"}), (lambda d, default=12701: 12701), clock
        cr._close_game, cr._maafw_text = (lambda *a: ""), (lambda d: fw_now["text"])     # _stop_agents is the real one
        efstart.run_on_desktop = lambda *a, **k: types.SimpleNamespace(code=efstart.OK, reason="")
        maaend_launch.restore_override = lambda d: ({"CloseGamePC": {}}, "")
        cm2.obstacle_shots = lambda d: list(shots)
        seen = {}
        try:
            got_v, note = cr._bring_up_and_run(tmpdir(), [B, A], {"first": True}, spawn=lambda *a: None, timeout=1200,
                                                 evidence=seen, state_dir=tmpdir(), again=again)
        finally:
            (cr.api, cr._wait, cr._running, cr.mxu_port, cr.time, cr._close_game, cr._stop_agents, cr._maafw_text,
             efstart.run_on_desktop, maaend_launch.restore_override, cm2.obstacle_shots) = saved
        return got_v, note, seen, sent_over


    got_v, note, seen, sent_over = two_rounds(walked2, lambda rs: {"only": rs}, [hit1])
    check("第二轮只发撞上的那条路线", sent_over, [{"first": True}, {"only": [A]}])
    check("第二轮走通：整次补跑算走通，记下补过第二轮", (got_v, "超时" in note, seen.get("second_round"), "blocked" in seen),
          ({B: True, A: True}, False, [A], False))
    got_v, _, seen, sent_over = two_rounds(walked2, lambda rs: {"only": rs}, [hit1, hit2])
    check("第二轮又撞上：没走通，照报", (got_v, seen.get("blocked"), seen.get("second_round")),
          ({B: True, A: False}, {A: [hit2]}, [A]))
    got_v, _, seen, sent_over = two_rounds(walked2, lambda rs: {"only": rs}, [hit1], start_fails=True)
    check("第二轮没起来：照第一轮的结果报（撞上、没走通）", (got_v, seen.get("blocked"), seen.get("second_round"), len(sent_over)),
          ({B: True, A: False}, {A: [hit1]}, None, 1))
    got_v, _, seen, sent_over = two_rounds(walked2, None, [hit1])
    check("不给第二轮的参数：只走一轮", (got_v, len(sent_over), seen.get("second_round")), ({B: True, A: False}, 1, None))
    got_v, _, seen, sent_over = two_rounds(walked2, lambda rs: {"only": rs}, [])
    check("第一轮没撞上：不走第二轮", (got_v, len(sent_over), seen.get("second_round")), ({B: True, A: True}, 1, None))

    print("\n[没干完的报警先问一句：这一趟哪几条路线会在关机前单独补（账本 #166 #170）]")
    from ark_relay.features import modes as _modes
    sd_a, hist_a, md_a = tmpdir(), tmpdir(), maaend_dir(P1008A, P1008)
    (hist_a / "2026-10-08" / "endfield").mkdir(parents=True)
    (hist_a / "2026-10-08" / "endfield" / "MaaEnd-06-34-21.log").write_text(log("MaaEnd-06-34-21.log"), encoding="utf-8")
    eng_a = types.SimpleNamespace(cfg=types.SimpleNamespace(state_dir=sd_a, maaend_dir=str(md_a), history_dir=str(hist_a),
                                                             automas_dir=None))
    rec_a = types.SimpleNamespace(run_id="2026-10-08/endfield/MaaEnd-06-34-21", script="MaaEnd", raw={},
                                  started=datetime(2026, 10, 8, 10, 34, 21, tzinfo=SERVER_TZ))
    saved_ahead = (cr._locale, _modes.debug_active)
    cr._locale = lambda d: ZH
    try:
        check("这一趟撞上的路线10：会单独补", cr.retry_ahead(eng_a, rec_a), ([cr.route_label("AutoCollectRoute10", ZH)], cr.AHEAD))
        _modes.debug_active = lambda sd, now=None: True
        check("调试模式开着：点名路线，说还补不了", cr.retry_ahead(eng_a, rec_a)[1], cr.AHEAD_DEBUG)
        _modes.debug_active = lambda sd, now=None: False
        (sd_a / "collect-retry").mkdir(parents=True)
        (sd_a / "collect-retry" / "2026-10-08.json").write_text(json.dumps({"started": "x"}), encoding="utf-8")
        check("当天的补跑还没出结果：算还会补", cr.retry_ahead(eng_a, rec_a)[1], cr.AHEAD)
        (sd_a / "collect-retry" / "2026-10-08.json").write_text(json.dumps({"started": "x", "finished": "y"}), encoding="utf-8")
        check("当天的补跑已经出过结果：说这一次用过了", cr.retry_ahead(eng_a, rec_a)[1], cr.AHEAD_SPENT)
        check("不是终末地的记录：不问", cr.retry_ahead(eng_a, types.SimpleNamespace(run_id="x", script="MAA", raw={}, started=rec_a.started)),
              ([], ""))
        check("找不到这一趟的日志：没有可说的", cr.retry_ahead(eng_a, types.SimpleNamespace(
            run_id="2026-10-08/endfield/MaaEnd-09-09-09", script="MaaEnd", raw={}, started=rec_a.started)), ([], ""))
    finally:
        cr._locale, _modes.debug_active = saved_ahead

    print("\n[补过第二轮：群里那条和当天的记号都写明]")
    saved_rr = cr.run_retry


    def fake_rr(verdict_of):
        def rr(md, routes, *a, **k):
            k["evidence"]["second_round"] = list(routes)
            if not verdict_of:
                k["evidence"]["blocked"] = {r: [hit2] for r in routes}
            return {r: verdict_of for r in routes}, ""
        return rr


    def maybe_run2(verdict_of):
        sd, hist, md = tmpdir(), tmpdir(), maaend_dir(P1008A, P1008)
        (hist / "2026-10-08" / "endfield").mkdir(parents=True)
        (hist / "2026-10-08" / "endfield" / "MaaEnd-06-34-21.log").write_text(log("MaaEnd-06-34-21.log"), encoding="utf-8")
        sent = []
        eng = types.SimpleNamespace(
            cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(md), history_dir=str(hist), automas_dir=None),
            state=types.SimpleNamespace(read_ledger=lambda d: [{"script": "MaaEnd", "run_id": "2026-10-08/endfield/MaaEnd-06-34-21"}],
                                        mark_incomplete=lambda *a: True, clear_incomplete_items=lambda *a: True),
            notifier=types.SimpleNamespace(send=lambda t, b, **kw: sent.append((t, b, kw.get("alert", False))) or []),
            _scripts_running=lambda: False)
        from ark_relay.features import makeup
        saved = (cr.run_retry, cr._locale, cr.restore_master, makeup._machinecheck)
        cr.run_retry, cr._locale, cr.restore_master = fake_rr(verdict_of), (lambda d: ZH), (lambda cfg: "")
        makeup._machinecheck = lambda *a, **k: None
        try:
            cr.maybe_run(eng, now=datetime(2026, 10, 8, 12, 0, tzinfo=SERVER_TZ), day="2026-10-08")
        finally:
            cr.run_retry, cr._locale, cr.restore_master, makeup._machinecheck = saved
        return sent, json.loads((sd / "collect-retry" / "2026-10-08.json").read_text(encoding="utf-8"))


    sent, stamp2 = maybe_run2(False)
    check("第二轮仍没走通：进群", [(t, a) for t, _, a in sent], [(texts.COLLECT_RETRY_FAILED, True)])
    check("正文写明单独又补了一轮、又撞上", (texts.collect_second_round([R10]) in sent[0][1], "补跑时又" in sent[0][1]), (True, True))
    check("正文是人话", texts.plain(sent[0][1]), [])
    check("当天的记号记了第二轮", stamp2.get("second_round"), ["AutoCollectRoute10"])
    sent, stamp2 = maybe_run2(True)
    check("第二轮走通：只进日报，不进群", [(t, route_of(t, alert=a)) for t, _, a in sent], [(texts.COLLECT_RETRY_OK, "log")])
    check("……日报那条也写了补过第二轮", texts.collect_second_round([R10]) in sent[0][1], True)
    cr.run_retry = saved_rr

    print("\nall checks passed" if not fails else f"\nFAILED: {len(fails)}")


def _part_collect_retry_cutoff():
    """The gathering retry, cut off mid-way, is run once more; every way out closes MaaEnd and the game.
    """
    import json
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import collect_retry as cr
    from ark_relay.features import preupdate as pc


    FX = fx_dir(Path(__file__), "fixtures") / "collect-retry-2026-09-11"
    zh = json.loads((FX / "zh_cn.json").read_text(encoding="utf-8"))
    NOW = datetime(2026, 9, 12, 12, 0).astimezone()
    killed, ran = [], []
    cr._kill = lambda name: killed.append(name)


    def outcome(stamp: dict | None, stopping: bool = False):
        """maybe_run with the retry stubbed and `stamp` already on disk: (ran?, stamp after).
    `stopping`: the relay is told to stop while the retry runs."""
        sd = tmpdir()
        f = sd / "collect-retry" / "2026-09-12.json"
        if stamp is not None:
            f.parent.mkdir(parents=True)
            f.write_text(json.dumps(stamp), encoding="utf-8")
        eng = types.SimpleNamespace(
            cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(sd), history_dir=str(sd), automas_dir=None),
            state=types.SimpleNamespace(read_ledger=lambda d: [], mark_incomplete=lambda *a: True,
                                    clear_incomplete_items=lambda *a: True),
            notifier=types.SimpleNamespace(send=lambda t, b, **kw: []), _scripts_running=lambda: False)
        saved = (cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master, pc.going_down)
        cr.latest_gathering_run = lambda entries, hist, labels: ({"run_id": "r1"}, ["AutoCollectRoute15"])
        cr.run_retry = lambda *a, **k: (ran.append(1), ({"AutoCollectRoute15": None}, "中继正在停止，不等开游戏的助手了")
                                        if stopping else ({"AutoCollectRoute15": True}, ""))[1]
        cr._locale, cr.restore_master = (lambda d: zh), (lambda cfg: "")
        pc.going_down = lambda: bool(ran) and stopping
        del ran[:], killed[:]
        try:
            cr.maybe_run(eng, now=NOW, day="2026-09-12")
        finally:
            cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master, pc.going_down = saved
        return bool(ran), json.loads(f.read_text(encoding="utf-8"))


    print("[补跑开始后中继停了：印记没有结束时间，过了补跑最长用时就再补一次]")
    cut = {"run_id": "r1", "routes": ["AutoCollectRoute15"], "started": (NOW - timedelta(hours=2)).isoformat()}
    did, after = outcome(cut)
    check("两小时前开始、没结束 → 再补一次", did, True)
    check("先关掉留下的 MaaEnd 和游戏", killed[:2], ["MaaEnd.exe", "Endfield.exe"])
    check("这次跑完写了结束时间", "finished" in after, True)
    did, _ = outcome(dict(cut, started=(NOW - timedelta(minutes=10)).isoformat()))
    check("10 分钟前开始的（可能还在跑）→ 不动", did, False)
    did, _ = outcome(dict(cut, finished=NOW.isoformat()))
    check("跑完了的 → 不再跑", did, False)

    print("\n[补跑跑到一半中继要停（审计 11-08 A-23）：印记不写结束，下次启动照「中途停了」再补]")
    did, after = outcome(None, stopping=True)
    check("跑过", did, True)
    check("印记没有结束时间、没有结论", ("finished" in after, "passed" in after), (False, False))
    did, after = outcome(dict(cut, cut_off="earlier"))
    check("已经补过一次又断了 → 不再补", did, False)
    check("写上结束，后面不再每次都说", "finished" in after, True)
    # Review of c6922283: the give-up stamp had no passed/failed, so the daily report said
    # 「开始了，还没有结果」 for a retry that was given up.
    from ark_relay.features import report
    gs = tmpdir()
    (gs / "collect-retry").mkdir(parents=True)
    (gs / "collect-retry" / "2026-09-12.json").write_text(json.dumps(after, ensure_ascii=False), encoding="utf-8")
    line = report._retry_tech_line(gs, "2026-09-12")
    check("日报 retry_line 为空", report.retry_line(gs, "2026-09-12"), "")
    check("技术日志不说「还没有结果」", "还没有结果" in line, False)
    check("技术日志说补跑两次都没跑完、哪条路线没结论", ("补跑两次都没跑完" in line, "没结论" in line), (True, True))
    did, _ = outcome(None)
    check("没有印记 → 照常跑", did, True)

    print("\n[补跑被打断后这次没补成（脚本还在跑）：下一次调用不再报、不再关一遍]")
    # Review of c6922283: the WARNING and the kills came before the early returns while the
    # stamp was rewritten only on the path that re-runs, so every later tick said and killed again.


    sd = tmpdir()
    f = sd / "collect-retry" / "2026-09-12.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps(cut), encoding="utf-8")
    eng = types.SimpleNamespace(
        cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(sd), history_dir=str(sd), automas_dir=None),
        state=types.SimpleNamespace(read_ledger=lambda d: []), _scripts_running=lambda: True)
    saved = (cr.latest_gathering_run, cr._locale, cr.restore_master)
    cr.latest_gathering_run = lambda entries, hist, labels: ({"run_id": "r1"}, ["AutoCollectRoute15"])
    cr._locale, cr.restore_master = (lambda d: zh), (lambda cfg: "")
    w = _Messages()
    cr.log.addHandler(w)
    del killed[:]
    try:
        r1 = cr.maybe_run(eng, now=NOW, day="2026-09-12")
        r2 = cr.maybe_run(eng, now=NOW + timedelta(minutes=1), day="2026-09-12")
    finally:
        cr.log.removeHandler(w)
        cr.latest_gathering_run, cr._locale, cr.restore_master = saved
    check("两次都没补（脚本还在跑）", (r1, r2), (False, False))
    check("只报一次没跑完", sum("没跑完" in m for m in w.lines), 1)
    check("只关一次 MaaEnd 和游戏", killed, ["MaaEnd.exe", "Endfield.exe"])
    check("印记还没写结束，脚本停了还会补", "finished" in json.loads(f.read_text(encoding="utf-8")), False)

    print("\n[没跑完的两句警告原样进群：时刻写成「10-22 16:44」，不带 ISO 的「T16」（账本 #110）]")
    from ark_relay.core.texts import plain
    w2 = _Messages()
    cr.log.addHandler(w2)
    try:
        outcome(cut)
        outcome(dict(cut, cut_off="earlier"))
    finally:
        cr.log.removeHandler(w2)
    said = [m for m in w.lines + w2.lines if "没跑完" in m]
    check("两种没跑完都说了", (any("再补一次" in m for m in said), any("今天不再补" in m for m in said)), (True, True))
    check("每句都是白话（texts.plain 没挑出毛病）", [plain(m) for m in said], [[] for _ in said])
    check("时刻是机器上的「月-日 时:分」", all(cr._clock(cut["started"]) in m for m in said), True)
    check("读不懂的时刻原样留着", cr._clock("earlier"), "earlier")

    print("\n[run_retry 半路放弃（MaaEnd 不响应）也关掉 MaaEnd 和游戏]")
    md = tmpdir() / "maaend"
    (md / "debug").mkdir(parents=True)
    (md / "debug" / "2026-09-12-1.log").write_bytes((FX / "mxu-app-override-line.log").read_bytes())
    cr._running = lambda names: set()
    cr._wait = lambda pred, seconds, step=3.0: False
    cr.mxu_port = lambda d: 12701
    cr.time = types.SimpleNamespace(sleep=lambda s: None, strftime=lambda f: "00:00:00", time=lambda: 0)
    del killed[:]
    verdict, note = cr.run_retry(md, ["AutoCollectRoute15"], "saturday", spawn=lambda exe, cwd, args: None)
    check("放弃了", note, "MaaEnd 起来 60 秒了还不响应")
    check("关掉了 MaaEnd 和游戏", sorted(killed), ["Endfield.exe", "MaaEnd.exe"])

    print("\n[关游戏前先停掉补跑那组助手：MXU 不停旧的，新的连不上（10-22 21:56:40，账本 #111）]")
    import urllib.error
    calls, attached = [], {"n": 2}   # the gathering's go-service and cpp-algo, still attached


    def fake_api(path, body=None, timeout=30):
        calls.append(path.rsplit("/", 2)[-2] + "/" + path.rsplit("/", 1)[-1])
        if path.endswith("/agent/stop"):
            attached["n"] = 0
        elif path.endswith("/tasks/start"):
            if attached["n"]:
                # mxu-tauri.log 21:56:40: 「Connection failed: MaaFramework internal error: status 0」
                raise urllib.error.HTTPError(path, 500, "agent failed to start", {}, None)
            attached["n"] = 2
        return {}


    saved_api, saved_wait = cr.api, cr._wait
    cr.api, cr._wait = fake_api, (lambda pred, seconds, step=3.0: pred())
    try:
        why = cr._close_game("automas", {"CloseGamePC": {}}, lambda: {"is_running": False}, tmpdir())
    finally:
        cr.api, cr._wait = saved_api, saved_wait
    check("关游戏这一步被接下了（不再是 HTTPError）", why, "")
    check("先停旧助手，再开关游戏任务", calls[:2], ["agent/stop", "tasks/start"])


def _part_collect_watch():
    """collect_watch: failed gathering routes are read from the live maafw.log, and the
master is never narrowed (the user, 2026-10-06: 「我开的任务是谁说要关的」);
lists an older relay version narrowed go back at the next attempt's start.
    """
    import json
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import collect_watch


    _drops = _Messages()
    from ark_relay.core import watch as _watch
    _watch.log.addHandler(_drops)


    FIX = fx_dir(Path(__file__), "fixtures") / "collect-watch-2026-09-14" / "maafw-attempt3.log"
    LINES = FIX.read_text(encoding="utf-8").splitlines()


    def _master(root):
        mdir = root / "data" / "abc" / "Default" / "ConfigFile"
        mdir.mkdir(parents=True)
        doc = {"instances": [{"tasks": [{"taskName": "AutoCollect", "enabled": True, "optionValues": {
            "AutoCollectSchedule": {"type": "checkbox", "caseNames": ["AutoCollectScheduleMonday"]},
            "AutoCollectValleyIVRareRoutes": {"type": "checkbox", "caseNames": ["Route4", "Route5", "Route6", "Route10", "Route13", "Route14"]},
            "AutoCollectWulingRareRoutes": {"type": "checkbox", "caseNames": ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"]},
            "AutoCollectMode": {"type": "select", "caseName": "Always"}}}]}]}
        (mdir / "mxu-MaaEnd.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return mdir / "mxu-MaaEnd.json"


    def _lists(f):
        ov = json.loads(f.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["optionValues"]
        return ov["AutoCollectValleyIVRareRoutes"]["caseNames"], ov["AutoCollectWulingRareRoutes"]["caseNames"]


    class _N:
        def __init__(self):
            self.sent = []

        def send(self, title, body, **kw):
            self.sent.append((title, body))


    def _setup():
        root = tmpdir()
        f = _master(root)
        maaend = root / "MaaEnd"
        (maaend / "debug").mkdir(parents=True)
        (maaend / "locales" / "interface").mkdir(parents=True)
        (maaend / "locales" / "interface" / "zh_cn.json").write_text(json.dumps(
            {"option.AutoCollectRoute10.label": "路线10：<b>晶簇</b>"}, ensure_ascii=False), encoding="utf-8")

        class Cfg:
            automas_dir = root
            state_dir = root / "state"
            maaend_dir = maaend
        Cfg.state_dir.mkdir()
        return Cfg, f, _N()


    FULL = (["Route4", "Route5", "Route6", "Route10", "Route13", "Route14"],
            ["Route1", "Route2", "Route3", "Route15", "Route16", "Route17"])


    def _old_narrowing(cfg, f, kept):
        """What a relay before 2026-10-06 left behind: the master narrowed to `kept`, the original in narrow.json."""
        doc = json.loads(f.read_text(encoding="utf-8"))
        ov = doc["instances"][0]["tasks"][0]["optionValues"]
        saved = {"AutoCollectValleyIVRareRoutes": list(FULL[0]), "AutoCollectWulingRareRoutes": list(FULL[1])}
        ov["AutoCollectValleyIVRareRoutes"]["caseNames"] = list(kept[0])
        ov["AutoCollectWulingRareRoutes"]["caseNames"] = list(kept[1])
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        nf = Path(cfg.state_dir) / "collect-retry" / "narrow.json"
        nf.parent.mkdir(parents=True, exist_ok=True)
        nf.write_text(json.dumps({"run_id": "11:20:22 自动采集失败", "at": "2026-09-14T11:20:22+08:00",
                                  "lists": saved}, ensure_ascii=False), encoding="utf-8")
        return nf


    print("[真实日志：Route10Failed 出现了，母本一条路线都不动，只记下来]")
    cfg, f, n = _setup()
    w = collect_watch.Watcher(cfg, n)
    before_failed = [ln for ln in LINES if "Route10Failed" not in ln and "Tasker.Task.Failed" not in ln]
    check("走到失败之前没有动作", w.feed("\n".join(before_failed)), [])
    failed_lines = [ln for ln in LINES if "Route10Failed" in ln or "Tasker.Task.Failed" in ln]
    check("失败了也没有动作", w.feed("\n".join(failed_lines)), [])
    check("母本原样（用户选的路线一条不关）", _lists(f), FULL)
    check("没有收窄记录", (Path(cfg.state_dir) / "collect-retry" / "narrow.json").exists(), False)
    check("记住了没走通的", w.failed, ["Route10"])
    check("不单独推送（失败从记录和补跑那里报）", n.sent, [])
    check("收窄的函数没了", (hasattr(collect_watch.Watcher, "_narrow"), hasattr(__import__("ark_relay.features.collect_retry").features.collect_retry, "narrow_master")),
          (False, False))

    print("\n[两条路线先后失败：都记下，母本还是不动]")
    cfg, f, n = _setup()
    w = collect_watch.Watcher(cfg, n)
    r10 = next(ln for ln in LINES if "Route10Failed" in ln)
    w.feed(r10)
    w.feed(r10.replace("Route10", "Route15"))
    check("两条都记下", w.failed, ["Route10", "Route15"])
    check("母本不动", _lists(f), FULL)
    start_line = next(ln for ln in LINES if "Tasker.Task.Starting" in ln)
    w.feed(start_line)
    check("新一趟开始就清空", w.failed, [])

    print("\n[11-20 (#187)：给看门狗数读到「协议更新」/「登录认证已失效」窗口的次数，含转义与 .log.gz 轮转]")
    import gzip
    import json as _json
    from ark_relay.features import collect_retry as _cr, makeup as _mk
    from ark_relay.core.config import RunRecord as _RR
    from datetime import datetime as _dt
    from ark_relay.core.config import SERVER_TZ as _TZ
    cfg, f, n = _setup()
    w = collect_watch.Watcher(cfg, n)
    agree = (fx_dir(Path(__file__), "fixtures") / "maaend-2026-11-20" / "maafw-agreement-ocr.log").read_text(encoding="utf-8")
    check("开始是 0", (w.agreement_seen, w.logout_seen), (0, 0))
    w.feed(agree)
    check("读到窗口那一行（OCR 行，不是事件行）：记一次", w.agreement_seen, 1)
    w.feed(_json.dumps({"text": "请您仔细阅读并同意以下协议"}))
    check("JSON \\uXXXX 转义也认", w.agreement_seen, 2)
    w.feed(_json.dumps({"text": "登录认证已失效"}))
    check("登录认证已失效也计次", w.logout_seen, 1)
    # 2026-11-28 (#209/#212): MaaEnd v3.3.0 logs param_.expected=["...","登录认证已失效",...]
    # on healthy screens with filtered_results_=[]; must NOT increment logout_seen / agreement_seen.
    w.feed('[2026-11-28 09:33:53.044][DBG][Px11764][Tx47189][OCRer.cpp][L87] OCR '
           '[all_results_=[{"box":[368,381,50,28],"score":0.96,"text":"Lv.60"}]] '
           '[filtered_results_=[]] [best_result_=null] [cost=119ms] [param_.model=] '
           '[param_.only_rec=false] [param_.expected=["自动登出","登录认证已失效","请您仔细阅读并同意以下协议"]]')
    w.feed('[2026-11-28 09:33:54.000][DBG][PipelineParser.cpp] {"expected":["登录认证已失效","请您仔细阅读并同意以下协议"]}')
    check("param_.expected 与 PipelineParser 词表不算真正读到弹窗", (w.agreement_seen, w.logout_seen), (2, 1))
    w.feed("\n".join(LINES))
    check("别的行不算", (w.agreement_seen, w.logout_seen), (2, 1))
    check("采集路线的记账照旧", w.failed, ["Route10"])
    # N2: collect_watch.poll follows rotated .log.gz tail
    cfg_gz, _f_gz, n_gz = _setup()
    w_gz = collect_watch.Watcher(cfg_gz, n_gz)
    log_gz = w_gz.log_path()
    head_txt = "[2026-11-20 09:34:00.000][INF] line1\n" * 5
    log_gz.write_text(head_txt, encoding="utf-8")
    w_gz.poll()
    rotated_gz = log_gz.parent / "maafw.bak.2026.11.20-09.40.02.867.log.gz"
    rotated_gz.write_bytes(gzip.compress((head_txt + agree).encode("utf-8")))
    log_gz.write_text("[2026-11-20 09:40:03.000][INF] fresh\n", encoding="utf-8")
    w_gz.poll()
    check("轮转成 .log.gz 后仍补读旧文件尾巴里的弹窗", w_gz.agreement_seen, 1)
    # R2-M1: clean MaaEnd restart truncating maafw.log must NOT replay an older run's leftover .log.gz
    import os as _os
    cfg_old, _f_old, n_old = _setup()
    w_old = collect_watch.Watcher(cfg_old, n_old)
    log_old = w_old.log_path()
    stale_gz = log_old.parent / "maafw.bak.2026.11.19-09.40.02.867.log.gz"
    stale_gz.write_bytes(gzip.compress((head_txt * 20 + agree).encode("utf-8")))
    _os.utime(stale_gz, (1700000000, 1700000000))
    log_old.write_text(head_txt * 10, encoding="utf-8")
    w_old.poll()
    log_old.write_text("[2026-11-20 09:00:00.000][INF] clean restart\n", encoding="utf-8")
    w_old.poll()
    check("重启清空 maafw.log 不误读昨天的残留 .log.gz", w_old.agreement_seen, 0)
    check("collect_retry._maafw_text 也能读 .log.gz", "请您仔细阅读并同意以下协议" in _cr._maafw_text(log_gz.parent), True)
    # N1: makeup.eligible skips the agreement dialog (it waits for a person's 同意) but not a logout:
    # the user, 2026-11-20 (B 10426, 10451), against holding back re-runs for fear of kicking someone off.
    now_t = _dt(2026, 11, 20, 10, 0, tzinfo=_TZ)
    for k, want, label in (("maaend_agreement_at", False, "协议窗口：不派无效整轮补跑"),
                           ("maaend_logged_out_at", True, "被别处登录挤下线：照常补跑")):
        r_blk = _RR("r1", "MaaEnd", "u", now_t, now_t, False, ["赠送干员礼物"], raw={k: "09:34:28"})
        check(label, _mk.eligible(r_blk, now_t), want)
    r_both = _RR("r1", "MaaEnd", "u", now_t, now_t, False, ["赠送干员礼物"],
                 raw={"maaend_agreement_at": "09:34:28", "maaend_logged_out_at": "10:30:00"})
    check("两样都有：协议窗口优先，不补跑", _mk.eligible(r_both, now_t), False)

    print("\n[旧版本收窄过的母本：新一趟（Tasker.Task.Starting）一开始就改回]")
    cfg, f, n = _setup()
    nf = _old_narrowing(cfg, f, (["Route10"], []))
    w = collect_watch.Watcher(cfg, n)
    notes = w.feed(start_line.replace("10:53:13", "11:21:43"))
    check("改回有说明", any("改回原来的 12 条" in x for x in notes), True)
    check("母本改回", _lists(f), FULL)
    check("收窄记录删掉", nf.exists(), False)
    check("没有记录时开始一趟什么都不做", w.feed(start_line), [])

    print("\n[只认调度器自己那一行；agent 回显的同一事件不算第二次]")
    cfg, f, n = _setup()
    w = collect_watch.Watcher(cfg, n)
    echo = [ln for ln in LINES if "Route10Failed" in ln]
    check("样本里事件被回显了两次", len(echo) >= 2 and all("EventDispatcher::notify" in x for x in echo), True)
    w.feed("\n".join(echo))
    check("只记一次、不推送", (w.failed, n.sent), (["Route10"], []))

    print("\n[读文件：增量读、跟着轮转走]")
    cfg, f, n = _setup()
    w = collect_watch.Watcher(cfg, n)
    lp = w.log_path()
    lp.write_text("\n".join(before_failed) + "\n", encoding="utf-8")
    check("第一次读完没有动作", w.poll(), [])
    check("偏移量走到文件尾", w._offset, lp.stat().st_size)
    with lp.open("a", encoding="utf-8") as fh:
        fh.write(failed_lines[0][:100])          # a half-written line
    w.poll()
    check("半行不算", w.failed, [])
    with lp.open("a", encoding="utf-8") as fh:
        fh.write(failed_lines[0][100:] + "\n")
    w.poll()
    check("补完那半行就认出失败", w.failed, ["Route10"])
    # Rotation: MaaFW renames the file and starts over; the retry's Task.Starting
    # lands in the new one.
    _old_narrowing(cfg, f, (["Route10"], []))
    lp.rename(lp.parent / "maafw.bak.2026.09.14-11.20.24.685.log")
    lp.write_text(start_line.replace("10:53:13", "11:21:43") + "\n", encoding="utf-8")
    notes = w.poll()
    check("轮转后读新文件，新一趟开始就改回旧收窄", _lists(f), FULL)
    check("偏移量重置到新文件", w._offset, lp.stat().st_size)

    print("\n[09-14 的时序：Failed 写进旧文件两秒后就轮转，尾巴要从 .bak 里补读]")
    cfg, f, n = _setup()
    w = collect_watch.Watcher(cfg, n)
    lp = w.log_path()
    lp.write_text("\n".join(before_failed) + "\n", encoding="utf-8")
    w.poll()
    with lp.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(failed_lines) + "\n")
    lp.rename(lp.parent / "maafw.bak.2026.09.14-11.20.24.685.log")     # not polled in between
    lp.write_text("x\n", encoding="utf-8")
    w.poll()
    check("从旧文件尾巴读到失败", w.failed, ["Route10"])
    check("母本还是不动", _lists(f), FULL)

    print("\n[audit 11-08 B-06: the old file's last line without a newline is still read]")
    cfg, f, n = _setup()
    w = collect_watch.Watcher(cfg, n)
    lp = w.log_path()
    lp.write_text("\n".join(before_failed) + "\n", encoding="utf-8")
    w.poll()
    _r10 = [ln for ln in failed_lines if "Route10Failed" in ln]
    with lp.open("a", encoding="utf-8") as fh:
        fh.write(_r10[-1])                                                 # the node line, no newline at the end
    lp.rename(lp.parent / "maafw.bak.2026.09.14-11.20.24.685.log")
    lp.write_text("x\n", encoding="utf-8")
    w.poll()
    check("the Failed node closing the old file is read", w.failed, ["Route10"])

    print("\n[线程：目录一有变化就读，不用定时]")
    cfg, f, n = _setup()
    nf = _old_narrowing(cfg, f, (["Route10"], []))
    lp = Path(cfg.maaend_dir) / "debug" / "maafw.log"
    lp.write_text("\n".join(before_failed) + "\n", encoding="utf-8")
    check("挂上了", collect_watch.start(cfg, n), True)
    with lp.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(failed_lines) + "\n" + start_line.replace("10:53:13", "11:21:43") + "\n")
    # On Windows FILE_NOTIFY_CHANGE_LAST_WRITE fires for the append itself; the Mac
    # kqueue in watch.py only sees the directory entry, so poke it with a new file.
    (lp.parent / "mxu-agent-0-1.log").write_text("x", encoding="utf-8")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and nf.exists():
        time.sleep(0.2)
    check("几秒内旧收窄就改回了", (_lists(f), nf.exists()), (FULL, False))

    print("\n[没有 MaaEnd 目录就不挂监听，并说明]")
    class _NoDir:
        maaend_dir = None
        state_dir = str(tmpdir())   # collect_watch.start prunes old task shots there first
    check("没目录返回 False", collect_watch.start(_NoDir, _N()), False)

    check("目录监听在测试期间没掉过", _drops.lines, [])


def _part_makeup_main():  # noqa: C901
    """A MAA / MaaEnd failure gets one make-up run; still failed after it, the group hears once.
    """
    import copy
    import json
    import os
    import types
    from datetime import datetime, timedelta


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import handle
    from ark_relay.features import makeup
    from ark_relay.features import report
    from ark_relay.features import shutdown
    from ark_relay.core import texts
    from ark_relay.core import ledger as core
    from ark_relay.core import engine as eng_mod
    from ark_relay.features.collector_maaend import BAG_FULL
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.features import machinecheck as _mc
    _mc.load()
    _mc_real = dict(_mc.CHECKS)   # put back at the end: the coverage pass runs every test file in one process
    _mc.CHECKS.clear()   # the alarms themselves are tested here; the machine checks in tests/test_mc.py
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import route_of


    FX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-09-10"
    MASTER = json.loads((FX / "master-before.json").read_text(encoding="utf-8"))
    THREE = ["赠送干员礼物", "基质刷取", "日常奖励领取"]          # 2026-09-25, as MaaEnd prints them, emoji stripped
    # Noon today: every stamp below stays on today's date whatever the hour the suite runs.
    NOW = datetime.now(tz=SERVER_TZ).replace(hour=12, minute=0, second=0, microsecond=0)


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []


    def put_master(doc) -> Path:
        """A fresh AUTO-MAS data dir holding `doc` as the MaaEnd master; returns its root."""
        root = tmpdir()
        d = root / "data" / "sid" / "Default" / "ConfigFile"
        d.mkdir(parents=True)
        (d / "mxu-MaaEnd.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return root


    def master_of(root: Path) -> dict:
        return json.loads((root / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json").read_text(encoding="utf-8"))


    def enabled(doc) -> list[str]:
        return [t["taskName"] for t in doc["instances"][0]["tasks"]
                if t.get("enabled") and not t["taskName"].startswith("__")]


    def build(automas=None):
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = automas
        cfg.maaend_dir = FX
        e = eng_mod.Engine(cfg, source=_NoSrc(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        return e


    def rec(script, started, ok=False, failed=None, raw=None, user=None, run_id=None):
        user = user or {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
        return RunRecord(run_id=run_id or f"{started:%Y-%m-%d}/{user}/{script}-{started:%H-%M-%S}",
                         script=script, user=user, started=started, finished=started + timedelta(minutes=5),
                         ok=ok, failed_tasks=list(failed or ([] if ok else ["x"])), raw=dict(raw or {}))


    def hold(e, r):
        e.state.append_ledger(r)
        e._pending[(r.script, r.user)] = r


    def alarms(e):
        return [t for t, _, a in e.notifier.sent if a]


    handle._ship_evidence = lambda eng, rec: ""
    real_dispatch, real_kill = makeup._dispatch, makeup._kill_game
    dispatched, killed = [], []
    makeup._kill_game = lambda: killed.append(makeup.GAME_EXE)
    earlier = NOW - timedelta(hours=1)

    print("[哪些失败要补跑：今天的明日方舟 / 终末地，维护、进不了游戏、停一切停的不补，鸣潮不归这里]")
    check("今天的终末地", makeup.eligible(rec("MaaEnd", earlier), NOW))
    check("今天的明日方舟", makeup.eligible(rec("MAA", earlier), NOW))
    check("鸣潮不补", makeup.eligible(rec("OK-WW", earlier), NOW), False)
    check("昨天的不补", makeup.eligible(rec("MaaEnd", NOW - timedelta(days=1)), NOW), False)
    check("维护日不补", makeup.eligible(rec("MaaEnd", earlier, raw={"maintenance": "维护"}), NOW), False)
    check("进不了游戏（有官方维护 / 更新公告为据）不补", makeup.eligible(rec("MaaEnd", earlier, raw={"maaend_unreachable": True}), NOW), False)
    # Only the log's shape, no official evidence (handle._confirm_unreachable): an
    # ordinary failure, made up like any other.
    check("只是秒败的形状、没有官方依据：补", makeup.eligible(rec("MaaEnd", earlier, raw={"maaend_unreachable_shape": True}), NOW), True)
    check("停一切停的不补", makeup.eligible(rec("MAA", earlier, raw={"manual_stop": "10:00 停一切"}), NOW), False)

    def _mfile(root: Path) -> Path:
        return root / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"


    print("\n[不关：终末地补跑按原设置整轮跑，母本一个字节都不改]")
    labels = makeup._labels(FX)
    check("语言包里的名字", (labels.get("GiftOperator"), labels.get("AutoEssence"), labels.get("DailyRewards")),
          ("赠送干员礼物", "基质刷取", "日常奖励领取"))
    check("收窄的函数没了（不关）", [n for n in ("plan_maaend", "narrow_master", "SKIP_TASKS", "NEVER_ENABLE")
                                  if hasattr(makeup, n)], [])
    MSTASH = copy.deepcopy(MASTER)
    tasks = MSTASH["instances"][0]["tasks"]
    tasks.insert(len(tasks) - 1, {"id": "stash01", "taskName": "StashBackpack", "enabled": False,
                                  "enabledByController": {"Win32-Front": False}})
    # The user's own setting, whatever it does: the relay does not switch it off either.
    tasks.insert(len(tasks) - 1, {"id": "decomp1", "taskName": "DecomposeWeaponEssence", "enabled": True,
                                  "enabledByController": {"Win32-Front": True}})
    WHOLE = getattr(makeup, "WHOLE_MAAEND", "<none>")
    for label, failed, causes in (("三项失败", THREE, {}),
                                  ("只有自动采集失败（以前不补）", ["自动采集"], {}),
                                  ("只有应急理智加强剂失败（以前不补）", ["应急理智加强剂"], {}),
                                  ("基质刷取失败、背包满没被证实", ["基质刷取"], {})):
        for doc in (MASTER, MSTASH):
            root = put_master(doc)
            text0 = _mfile(root).read_text(encoding="utf-8")
            e = build(root)
            r = rec("MaaEnd", earlier, failed=failed, raw={"maaend_fail_causes": causes} if causes else None)
            hold(e, r)
            dispatched.clear()
            makeup._dispatch = lambda script: (dispatched.append(script), (True, f"脚本「{script}」已单独开跑"))[1]
            tag = label + ("（母本有存放背包）" if doc is MSTASH else "")
            check(f"{tag}：派下去了", (makeup.maybe_run(e, NOW), dispatched), (True, ["MaaEnd"]))
            check(f"{tag}：母本逐字节没动（不关）", _mfile(root).read_text(encoding="utf-8") == text0, True)
            check(f"{tag}：开着的还是原来那些（不关）", enabled(master_of(root)), enabled(doc))
            check(f"{tag}：记的是按原设置整轮跑",
                  makeup.read_marker(e.cfg.state_dir, f"{NOW:%Y-%m-%d}").get("MaaEnd", {}).get("tasks"), [WHOLE])

    print("\n[背包满了（看到了仓储已满的提示）：先开「存放背包」排到最前，别的一项不动，跑完改回]")
    cfgn = types.SimpleNamespace(automas_dir=put_master(MASTER), state_dir=tmpdir(), maaend_dir=FX)
    check("没有存放背包这一项：说清楚，照原设置跑", makeup.stash_first(cfgn, "run-3", NOW),
          (False, "母本里没有存放背包这一项，没法先清背包"))
    root2 = put_master(MSTASH)
    cfg2 = types.SimpleNamespace(automas_dir=root2, state_dir=tmpdir(), maaend_dir=FX)
    check("开了、排到最前", makeup.stash_first(cfg2, "run-3", NOW), (True, ""))
    d2 = master_of(root2)
    names = [t["taskName"] for t in d2["instances"][0]["tasks"] if not t["taskName"].startswith("__")]
    check("存放背包排在第一个开着的任务前面", names[0], "StashBackpack")
    st = [t for t in d2["instances"][0]["tasks"] if t["taskName"] == "StashBackpack"][0]
    check("存放背包开关和控制器那份都开了", (st["enabled"], st["enabledByController"]), (True, {"Win32-Front": True}))
    check("别的任务开关一个没变（拆解基质是你自己开的，也不动）",
          [(t["taskName"], t.get("enabled"), t.get("enabledByController")) for t in d2["instances"][0]["tasks"]
           if t["taskName"] != "StashBackpack"],
          [(t["taskName"], t.get("enabled"), t.get("enabledByController")) for t in MSTASH["instances"][0]["tasks"]
           if t["taskName"] != "StashBackpack"])
    check("已经开着并排在最前：不再改", makeup.stash_first(cfg2, "run-3b", NOW), (False, ""))
    makeup.restore(cfg2)
    check("顺序和开关都改回", master_of(root2), MSTASH)

    print("\n[背包满了：补跑先清背包，跑完记录一落地就改回原样]")
    e = build(put_master(MSTASH))
    rb = rec("MaaEnd", earlier, failed=["基质刷取"], raw={"maaend_fail_causes": {"基质刷取": BAG_FULL}})
    hold(e, rb)
    dispatched.clear()
    makeup._dispatch = lambda script: (dispatched.append(script), (True, f"脚本「{script}」已单独开跑"))[1]
    check("派下去了", (makeup.maybe_run(e, NOW), dispatched), (True, ["MaaEnd"]))
    db = master_of(e.cfg.automas_dir)
    check("母本里存放背包开着、排第一，别的开关原样",
          ([t["taskName"] for t in db["instances"][0]["tasks"] if not t["taskName"].startswith("__")][0],
           sorted(set(enabled(db)) - {"StashBackpack"}) == sorted(enabled(MSTASH))), ("StashBackpack", True))
    check("记的是先存放背包再整轮跑", makeup.read_marker(e.cfg.state_dir, f"{NOW:%Y-%m-%d}")["MaaEnd"]["tasks"],
          ["存放背包", WHOLE])
    e._verify_outcome = lambda x: None
    handle._weekly_gates = lambda eng, rec: None
    handle._handle(e, rec("MaaEnd", NOW + timedelta(minutes=1), ok=True,
                          raw={"tasks_done": ["基质刷取"], "tasks_evidence": {"基质刷取": "当前理智 234/360"}}))
    check("记录落地：母本回到原样", master_of(e.cfg.automas_dir), MSTASH)
    check("日报 makeup_line 严格为空，细节在技术日志",
          (report.makeup_line(e.cfg.state_dir, f"{NOW:%Y-%m-%d}"),
           report._makeup_tech_line(e.cfg.state_dir, f"{NOW:%Y-%m-%d}")),
          ("", f"终末地失败后自动补跑「存放背包、{WHOLE}」，走通了（原来失败于：基质刷取）"))
    e = build(put_master(MASTER))
    hold(e, rec("MaaEnd", earlier, failed=["基质刷取"], raw={"maaend_fail_causes": {"基质刷取": BAG_FULL}}))
    dispatched.clear()
    check("母本里没有存放背包：照样补跑", (makeup.maybe_run(e, NOW), dispatched), (True, ["MaaEnd"]))
    check("母本没动", master_of(e.cfg.automas_dir), MASTER)
    check("记下没法先清背包（日报那一行带上）", makeup.read_marker(e.cfg.state_dir, f"{NOW:%Y-%m-%d}")["MaaEnd"]["note"],
          "背包满了，但母本里没有存放背包这一项，没法先清背包")

    print("\n[补跑一天一次：没派下去不算一次，派下去了就算]")
    dispatched.clear()
    day = f"{NOW:%Y-%m-%d}"
    e = build(put_master(MASTER))
    r = rec("MaaEnd", earlier, failed=THREE)
    hold(e, r)
    check("还没补过 → 压着", makeup.holding(e, r, NOW))
    makeup._dispatch = lambda script: (dispatched.append(script), (False, "连不上 AUTO-MAS"))[1]
    check("没派下去 → 下一轮再试", makeup.maybe_run(e, NOW), True)
    mk = makeup.read_marker(e.cfg.state_dir, day)["MaaEnd"]
    check("记成没能开跑", (mk["result"], mk["tries"]), (makeup.COULDNT_RUN, 1))
    check("没能开跑不算补过 → 仍压着", makeup.holding(e, r, NOW))
    check("没派下去，母本也没动", master_of(e.cfg.automas_dir), MASTER)
    check("两分钟内不再派", (makeup.maybe_run(e, NOW + timedelta(seconds=30)), len(dispatched)), (True, 1))
    check("闹钟定在两分钟后", makeup.next_moment(e.cfg.state_dir, NOW)[0], NOW + timedelta(seconds=makeup.RETRY_GAP_S))
    makeup._dispatch = lambda script: (dispatched.append(script), (True, f"脚本「{script}」已单独开跑"))[1]
    t2 = NOW + timedelta(seconds=makeup.RETRY_GAP_S + 1)
    check("过了两分钟再派，派下去了", makeup.maybe_run(e, t2), True)
    mk = makeup.read_marker(e.cfg.state_dir, day)["MaaEnd"]
    check("记成已派、第 2 次", (mk["result"], mk["tries"]), (makeup.DISPATCHED, 2))
    check("补的是按原设置整轮跑", mk["tasks"], [WHOLE])
    check("先关了游戏", killed[-1:], ["Endfield.exe"])
    check("母本原样（不关）", master_of(e.cfg.automas_dir), MASTER)
    check("不再借更新重跑的时刻（那会让整次开机后面的手动轮都不算手动）", hasattr(e, "_gu_rerun_at"), False)
    check("派下去了 → 不再压着", makeup.holding(e, r, t2), False)
    check("在跑 → 日报和关机都等它", makeup.in_flight(e.cfg.state_dir, t2), ["MaaEnd"])
    check("再来一轮不会派第二次", (makeup.maybe_run(e, t2 + timedelta(seconds=5)), dispatched.count("MaaEnd")), (False, 2))
    check("在跑的时候母本还是原样", master_of(e.cfg.automas_dir), MASTER)

    print("\n[补跑的记录落盘：走通 → 前面那几趟记成补跑做成了，母本改回]")
    mr = rec("MaaEnd", t2 + timedelta(minutes=1), ok=True,
             raw={"tasks_done": THREE,   # each with a game line of its own (core.maaend_unverified)
                  "tasks_evidence": {"赠送干员礼物": "获得 信用 ×400", "基质刷取": "当前理智 234/360",
                                     "日常奖励领取": "获得 通行证经验 ×2000"}})
    e._verify_outcome = lambda x: None
    handle._weekly_gates = lambda eng, rec: None
    handle._handle(e, mr)
    mk = makeup.read_marker(e.cfg.state_dir, day)["MaaEnd"]
    check("记成走通", mk["result"], makeup.OK)
    check("母本改回原样", master_of(e.cfg.automas_dir), MASTER)
    row = {x["run_id"]: x for x in e.state.read_ledger(day)}[r.run_id]
    check("原来那趟记上补跑做成的时间", bool((row.get("raw") or {}).get("makeup_ok")))
    check("压着的那条立即直推群排查并清空待推（无 _recovered 旁路）",
          (dict(e._pending), hasattr(e, "_recovered"), alarms(e)),
          ({}, False, [texts.makeup_passed("终末地", "早班")]))
    before_flush = len(e.notifier.sent)
    e._flush_pending()
    check("下一轮不重复推", len(e.notifier.sent), before_flush)
    check("不在跑了", makeup.in_flight(e.cfg.state_dir, t2 + timedelta(minutes=2)), [])
    title, body = core.format_daily(day, e.state.read_ledger(day))
    check("有前期真失败的日子标题中性不误标全绿，也不塞失败词",
          (title, "失败" not in title, "❌" not in body),
          (f"📋 {day[5:]} · 今日日报", True, True))
    check("日报 makeup_line 为空，细节仅在技术日志",
          (report.makeup_line(e.cfg.state_dir, day), report._makeup_tech_line(e.cfg.state_dir, day)),
          ("", f"终末地失败后自动补跑「{WHOLE}」，走通了（原来失败于：赠送干员礼物、基质刷取、日常奖励领取）"))

    print("\n[积压告警：补跑前压着不推，补跑后仍没成进群一次（这一班）]")
    e = build()
    m = rec("MAA", earlier, failed=["MAA 未能正确登录 PRTS"])
    hold(e, m)
    e._flush_pending()
    check("补跑前：不推", e.notifier.sent, [])
    check("补跑前：还压着", list(e._pending), [("MAA", "arknights")])
    dispatched.clear()
    n_killed = len(killed)
    makeup.maybe_run(e)
    check("明日方舟整个再跑一遍", (dispatched, makeup.read_marker(e.cfg.state_dir, day)["MAA"]["tasks"]), (["MAA"], ["整个 MAA"]))
    check("明日方舟不关终末地", len(killed), n_killed)
    m2r = rec("MAA", datetime.now(tz=SERVER_TZ) + timedelta(seconds=1), failed=["MAA 未能正确登录 PRTS"])
    handle._handle(e, m2r)
    check("补跑没成记成仍没成", makeup.read_marker(e.cfg.state_dir, day)["MAA"]["result"], makeup.FAILED)
    e._flush_pending()
    check("补跑后：进群一条，算早班（按原来那趟的开始时间）", alarms(e), [texts.unresolved("明日方舟", "早班")])
    check("补跑后：头一行说补跑也没成、卡在哪", e.notifier.sent[-1][1].splitlines()[0],
          "明日方舟早班没跑成，补跑也没成：卡在 MAA 未能正确登录 PRTS")
    check("补跑后：不再压着", dict(e._pending), {})
    check("日报 makeup_line 为空，技术日志有明细",
          (report.makeup_line(e.cfg.state_dir, day), report._makeup_tech_line(e.cfg.state_dir, day)),
          ("", "明日方舟失败后自动补跑，还是没成（明日方舟 未能正确登录 PRTS）"))

    print("\n[过了一天：昨天压着、没补跑的，进群一次说没补跑]")
    e = build()
    hold(e, rec("MaaEnd", NOW - timedelta(days=1, hours=1), failed=THREE))
    e._flush_pending()
    check("推一条", alarms(e), [texts.unresolved("终末地", "早班")])
    check("说没补跑和原因", "没补跑：没等到补跑就过了零点" in e.notifier.sent[-1][1], True)
    check("放下了", dict(e._pending), {})

    print("\n[鸣潮照旧：最终失败照样进群]")
    e = build()
    hold(e, rec("OK-WW", earlier, failed=["OK-WW 运行超时"]))
    e._flush_pending()
    check("推了一条报警", len(alarms(e)), 1)

    print("\n[「这一轮没干完」：终末地按这一班进群；鸣潮照旧「这一轮没干完」]")
    for script, want_title in (("MaaEnd", texts.unresolved_undone("终末地", "早班")), ("OK-WW", texts.ROUND_INCOMPLETE)):
        e = build()
        x = rec(script, earlier, ok=True)
        e.state.append_ledger(x)
        e._verify_outcome = lambda r: "有 1 项没干成"
        handle._handle_success(e, x, (x.script, x.user))
        check(f"{script} 进群的是「{want_title}」", alarms(e), [want_title])
        check(f"{script} 账本记了没干完", e.state.read_ledger(f"{earlier:%Y-%m-%d}")[0].get("incomplete"), "有 1 项没干成")

    print("\n[自动采集补跑没走通、复发：进群（2026-10-06 起：每个报错都进群），日报那行也带上]")
    src = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "collect_retry.py").read_text(encoding="utf-8")
    check("collect_retry 发报警（alert=True）", "alert=True" in src, True)
    check("补跑仍没走通：进群", route_of(texts.COLLECT_RETRY_FAILED, alert=True), "group")
    check("复发：进群", route_of(texts.COLLECT_RECURRENT, alert=True), "group")
    sd = tmpdir()
    (sd / "collect-retry").mkdir()
    (sd / "collect-retry" / f"{day}.json").write_text(json.dumps(
        {"passed": [], "failed": ["AutoCollectRoute15"], "unknown": [], "recurrent": ["AutoCollectRoute15"]}), encoding="utf-8")
    check("日报 retry_line 为空，技术日志说连续两天",
          (report.retry_line(sd, day), "连续两天没走通 AutoCollectRoute15" in report._retry_tech_line(sd, day)),
          ("", True))

    print("\n[MAA failed after 21:30: the decision waits for the make-up; nothing pushed (10-10 23:22: only 「关机被取消」 is)]")
    e = build()
    e.cfg.shutdown_after_run = True
    e._handled_any = True
    e._started_at = NOW - timedelta(hours=3)
    e.cfg.shutdown_min_uptime = 0
    e._report_cutoff = lambda now: now - timedelta(minutes=5)
    e._last_round_manual = lambda now, entries: False
    # The make-up gate is what is tested here, so the decision is taken as the one right after this
    # boot's shift (the whitelist itself: test_shutdown_whitelist.py).
    real_not_shift = shutdown._not_shift
    shutdown._not_shift = lambda *a: None
    hold(e, rec("MAA", earlier, failed=["MAA 未能正确登录 PRTS"]))
    v = shutdown.decide(e, NOW)
    check("判的是等补跑，不是「还有告警没推出去」", v.code, "makeup")
    shutdown._say_if_moment_passed(e, NOW, v)
    check("waiting for the make-up: nothing about powering off pushed", [t for t, _, a in e.notifier.sent if "关机" in t], [])
    dispatched.clear()
    e._maybe_makeup(NOW)
    check("补跑派下去了", dispatched, ["MAA"])
    check("派下去之后还是等补跑", shutdown.decide(e, NOW).code, "makeup")
    e._scripts_running = lambda: True
    v = shutdown.decide(e, NOW)
    check("补跑跑着的时候也是等补跑，不是「还有脚本在跑」", v.code, "makeup")
    shutdown._say_if_moment_passed(e, NOW, v)
    check("make-up running: still nothing pushed", [t for t, _, a in e.notifier.sent if "关机" in t], [])
    e._scripts_running = lambda: False
    e._report_cutoff = lambda now: now - timedelta(minutes=5)
    e.state.append_ledger(rec("MAA", earlier - timedelta(minutes=1), ok=True, run_id=f"{day}/arknights/MAA-ok"))
    report._maybe_daily_report(e, NOW)
    check("日报等补跑出结果", e.state.report_sent(day), False)
    stale = NOW + timedelta(minutes=makeup.STALE_MIN + 1)
    check("一直没出记录：十分钟后有闹钟", makeup.next_moment(e.cfg.state_dir, NOW)[0], NOW + timedelta(minutes=makeup.STALE_MIN, seconds=1))
    makeup.maybe_run(e, stale)
    check("十分钟没跑出记录 → 收尾", makeup.read_marker(e.cfg.state_dir, day)["MAA"]["result"], makeup.NO_RECORD)
    check("收尾后不再等", makeup.waiting(e, stale), [])
    check("日报 makeup_line 为空，技术日志有明细",
          (report.makeup_line(e.cfg.state_dir, day), report._makeup_tech_line(e.cfg.state_dir, day)),
          ("", f"明日方舟失败后派了自动补跑，{makeup.STALE_MIN} 分钟没跑出记录"))
    shutdown._not_shift = real_not_shift

    print("\n[还有脚本在跑：不补]")
    e = build()
    hold(e, rec("MAA", earlier, failed=["x"]))
    e._scripts_running = lambda: True
    dispatched.clear()
    check("在跑不派", (makeup.maybe_run(e, NOW), dispatched), (False, []))

    print("\n[母本读不出来：记成放弃，不每轮报错，也不再压着]")
    e = build(put_master(MASTER))
    bad = rec("MaaEnd", earlier, failed=THREE)
    hold(e, bad)
    real_prepare = makeup._prepare_maaend
    def boom(*a, **k):
        raise ValueError("Expecting value: line 1 column 1")
    makeup._prepare_maaend = boom
    dispatched.clear()
    check("不派、不抛", (makeup.maybe_run(e, NOW), dispatched), (False, []))
    mk = makeup.read_marker(e.cfg.state_dir, day)["MaaEnd"]
    check("记成放弃，带原因", (mk["result"], "ValueError" in mk["note"]), (makeup.GAVE_UP, True))
    check("不再压着", makeup.holding(e, bad, NOW), False)
    e._flush_pending()
    check("放下了，进群一次", (alarms(e), dict(e._pending)), ([texts.unresolved("终末地", "早班")], {}))
    check("说补跑没能开跑和原因", "补跑没能开跑（母本读写出错" in e.notifier.sent[-1][1], True)
    check("日报 makeup_line 为空，技术日志有明细",
          (report.makeup_line(e.cfg.state_dir, day),
           report._makeup_tech_line(e.cfg.state_dir, day).startswith("终末地失败后想自动补跑「赠送干员礼物、基质刷取、日常奖励领取」，没能开跑（母本读写出错")),
          ("", True))
    makeup._prepare_maaend = real_prepare

    import subprocess as _real_sub


    def mpath(root: Path) -> Path:
        return root / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"


    def mk_of(e, script, d=None):
        return makeup.read_marker(e.cfg.state_dir, d or day).get(script) or {}


    class Log:
        def __init__(self):
            self.lines = []

        def _rec(self, fmt, *a, **k):
            self.lines.append(fmt % a if a else fmt)

        info = warning = debug = error = _rec

        def exception(self, fmt, *a, **k):
            self.lines.append("EXC " + (fmt % a if a else fmt))


    print("\n[补跑派下去之后，「有没有在跑」的三秒缓存作废：同一轮的关机判断重新问 AUTO-MAS]")
    asked = []
    real_win, real_busy, real_subp = eng_mod.config.IS_WINDOWS, eng_mod._automas_busy, eng_mod.subprocess
    try:
        eng_mod.config.IS_WINDOWS = True
        answer = {"v": False}
        eng_mod._automas_busy = lambda: (asked.append(1), answer["v"])[1]
        eng_mod.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(stdout=b""),
                                                   SubprocessError=_real_sub.SubprocessError)
        eng_mod._SCRIPTS_CACHE.update(at=-1e9, val=False)
        check("派单前问了一次：没在跑", (eng_mod.Engine._scripts_running(), len(asked)), (False, 1))
        e = build()
        hold(e, rec("MAA", earlier, failed=["MAA 未能正确登录 PRTS"]))
        dispatched.clear()
        answer["v"] = True             # AUTO-MAS has started the make-up
        check("派下去了", (makeup.maybe_run(e, NOW), dispatched), (True, ["MAA"]))
        check("三秒内再问：不用旧的「没在跑」，重新问到「在跑」", (eng_mod.Engine._scripts_running(), len(asked)), (True, 2))
    finally:
        eng_mod.config.IS_WINDOWS, eng_mod._automas_busy, eng_mod.subprocess = real_win, real_busy, real_subp
        eng_mod._SCRIPTS_CACHE.update(at=-1e9, val=False)

    print("\n[调试模式开着：不补跑，失败马上进群，不是一直压着等（2026-10-06）]")
    from ark_relay.features import modes as _modes_dbg
    from ark_relay.features import handle as _unres_dbg
    _real_dbg = _modes_dbg.debug_active
    _modes_dbg.debug_active = lambda *a, **k: True
    try:
        e = build()
        held_dbg = rec("MAA", earlier, failed=["MAA 未能正确登录 PRTS"])
        hold(e, held_dbg)
        dispatched.clear()
        makeup.maybe_run(e, NOW)
        check("调试模式：没派补跑", dispatched, [])
        ent_dbg = makeup.read_marker(e.cfg.state_dir, f"{NOW:%Y-%m-%d}").get("MAA") or {}
        check("当天的补跑记为不补（调试模式）", (ent_dbg.get("result"), "调试模式" in str(ent_dbg.get("note"))),
              (makeup.GAVE_UP, True))
        check("那条失败不再等，马上推", _unres_dbg.after_makeup(e, held_dbg)[0], _unres_dbg.UNRESOLVED)
    finally:
        _modes_dbg.debug_active = _real_dbg

    print("\n[明日方舟：只有「根本没开始干活」才整个再跑；开始干活了的不补，免得再吃一份理智药]")
    LOGIN = ["MAA 未能正确登录 PRTS"]
    for label, r_, want in (
            ("登录没成、记录里没打过仗 → 补", rec("MAA", earlier, failed=LOGIN), ""),
            ("模拟器起不来 → 补", rec("MAA", earlier, failed=["模拟器启动失败"]), ""),
            ("「部分任务执行失败」拿不准 → 不补", rec("MAA", earlier, failed=["MAA 部分任务执行失败"]), "x"),
            ("登录没成但记录里花过理智 → 不补", rec("MAA", earlier, failed=LOGIN, raw={"sanity_spent": 72}), "x"),
            ("登录没成但有掉落 → 不补", rec("MAA", earlier, failed=LOGIN, raw={"drop_statistics": {"龙门币": 864}}), "x"),
            ("吃过理智药 → 不补", rec("MAA", earlier, failed=LOGIN, raw={"medicine_used": 1}), "x"),
            ("没写失败项 → 不补", rec("MAA", earlier, failed=[""]), "x")):
        e = build()
        hold(e, r_)
        check(label, bool(makeup.maa_work_done(e, r_)), bool(want))
    e = build()
    first = rec("MAA", earlier - timedelta(minutes=30), failed=LOGIN,
                raw={"sanity_spent": 120, "medicine_used": 2}, run_id=f"{day}/arknights/MAA-a1")
    last = rec("MAA", earlier, failed=LOGIN)
    e.state.append_ledger(first)
    hold(e, last)
    check("同一轮前一次打过仗（AUTO-MAS 的第一次）→ 不补", "开始干活" in makeup.maa_work_done(e, last))
    dispatched.clear()
    check("不派", (makeup.maybe_run(e, NOW), dispatched), (False, []))
    mk = mk_of(e, "MAA")
    check("记成放弃，写明为什么不补", (mk.get("result"), mk.get("note", "").startswith("不补跑：")), (makeup.GAVE_UP, True))
    check("不再压着", makeup.holding(e, last, NOW), False)
    e._flush_pending()
    check("放下了，进群一次", (alarms(e), dict(e._pending)), ([texts.unresolved("明日方舟", "早班")], {}))
    check("说为什么没补跑", "没补跑：这一轮已经开始干活" in e.notifier.sent[-1][1] and "理智药" in e.notifier.sent[-1][1], True)
    line = report._makeup_tech_line(e.cfg.state_dir, day)
    check("日报 makeup_line 为空；技术日志说不补跑和原因",
          (report.makeup_line(e.cfg.state_dir, day), "失败后没有自动补跑（" in line and "理智药" in line), ("", True))
    check("技术日志没有英文字段名", [w for w in ("sanity", "medicine", "drop") if w in line], [])
    e = build()
    e.state.append_ledger(rec("MAA", earlier - timedelta(hours=3), ok=True, raw={"sanity_spent": 200},
                              run_id=f"{day}/arknights/MAA-morning"))
    last2 = rec("MAA", earlier, failed=LOGIN)
    hold(e, last2)
    check("前一轮（走通的那轮）花的理智不算这一轮的 → 补", makeup.maa_work_done(e, last2), "")
    dispatched.clear()
    makeup.maybe_run(e, NOW)
    check("派下去了", dispatched, ["MAA"])

    print("\n[改动记录原子写，改之前先存一份完整母本；记录读不出来就用完整备份改回]")
    root = put_master(MSTASH)
    text0 = mpath(root).read_text(encoding="utf-8")
    cfg = types.SimpleNamespace(automas_dir=root, state_dir=tmpdir(), maaend_dir=FX)
    nf, bf = cfg.state_dir / "makeup" / "narrow.json", cfg.state_dir / "makeup" / "master-backup.json"
    written = []
    real_aw = makeup.atomic_write_text
    makeup.atomic_write_text = lambda path, data: (written.append(Path(path).name), real_aw(path, data))[1]
    makeup.stash_first(cfg, "run-b", NOW)
    makeup.atomic_write_text = real_aw
    check("先完整备份，再改动记录，再母本，都走原子写", written, ["master-backup.json", "narrow.json", "mxu-MaaEnd.json"])
    check("完整备份逐字节是原来的母本", bf.read_text(encoding="utf-8") == text0)
    nf.write_text("{坏的", encoding="utf-8")
    back, err = makeup.try_restore(cfg)
    check("用完整备份改回", ("完整备份" in back, err), (True, ""))
    check("母本逐字节回到原样", mpath(root).read_text(encoding="utf-8") == text0)
    check("两份都清掉", (nf.exists(), bf.exists()), (False, False))

    print("\n[改动记录和完整备份都读不出来：推一条真报警（只推一次），之后不再改母本，等人看]")
    makeup.stash_first(cfg, "run-c", NOW)
    nf.write_text("{坏", encoding="utf-8")
    bf.write_text("坏", encoding="utf-8")
    notes = Notes()
    back, err = makeup.try_restore(cfg, notes)
    check("改不回，说明原因", (back, "都读不出来" in err), ("", True))
    check("推了一条真报警", [(t, a) for t, _, a in notes.sent], [(texts.MAKEUP_RESTORE_FAILED, True)])
    check("报警进群", route_of(texts.MAKEUP_RESTORE_FAILED, alert=True), "group")
    check("正文是人话、带文件路径（Windows 路径的人话检查在 test_texts_gate）",
          ("自动改回失败，已交给我们这边去改回" in notes.sent[0][1], str(nf) in notes.sent[0][1]), (True, True))
    makeup.try_restore(cfg, notes)
    makeup.restore(cfg, Notes())
    check("只推一次", len(notes.sent), 1)
    check("记下了等我们这边改回", makeup.restore_broken(cfg.state_dir))
    changed_master = mpath(root).read_text(encoding="utf-8")
    check("之后不再改母本", makeup.stash_first(cfg, "run-d", NOW), (False, "上次临时改过的终末地设置还没改回，等我们这边改回"))
    check("母本没被再改", mpath(root).read_text(encoding="utf-8") == changed_master, True)
    e = build(root)
    e.cfg.state_dir = cfg.state_dir
    bad = rec("MaaEnd", earlier, failed=THREE)
    hold(e, bad)
    dispatched.clear()
    check("这时有终末地失败：补跑不派", (makeup.maybe_run(e, NOW), dispatched), (False, []))
    mk = mk_of(e, "MaaEnd")
    check("记成放弃，写明设置没改回", (mk.get("result"), "没能改回" in mk.get("note", "")), (makeup.GAVE_UP, True))
    check("不再压着、关机不等它", (makeup.holding(e, bad, NOW), makeup.waiting(e, NOW)), (False, []))
    check("报警没有再推", alarms(e), [])
    nf.unlink()
    makeup.restore(cfg)
    check("人删掉那份记录后，补跑恢复", makeup.restore_broken(cfg.state_dir), False)

    print("\n[母本本身读不出来：不抛，说明原因，改动记录留着下次再改回]")
    root5 = put_master(MSTASH)
    cfg5 = types.SimpleNamespace(automas_dir=root5, state_dir=tmpdir(), maaend_dir=FX)
    makeup.stash_first(cfg5, "run-e", NOW)
    mpath(root5).write_text("{坏", encoding="utf-8")
    back, err = makeup.try_restore(cfg5)
    check("没改回、有原因、记录留着", (back, "读写不成" in err, (cfg5.state_dir / "makeup" / "narrow.json").exists()),
          ("", True, True))
    mpath(root5).write_text(json.dumps(MSTASH, ensure_ascii=False), encoding="utf-8")
    real_unlink = Path.unlink
    Path.unlink = lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, "文件被占用"))
    try:
        back, err = makeup.try_restore(cfg5)
    finally:
        Path.unlink = real_unlink
    check("改回后删记录时文件被占用：不抛，带原因（调用方不会记 ERROR 进群）",
          (back, "PermissionError" in err), ("", True))

    print("\n[开头改回母本时出错：当天终末地补跑记成放弃，关机和日报不等到半夜]")
    e = build(put_master(MASTER))
    r5 = rec("MaaEnd", earlier, failed=THREE)
    hold(e, r5)
    real_try = makeup.try_restore
    def _locked(cfg, notifier=None):
        raise OSError("文件被占用")
    makeup.try_restore = _locked
    try:
        check("不抛、不派", makeup.maybe_run(e, NOW), False)
    finally:
        makeup.try_restore = real_try
    mk = mk_of(e, "MaaEnd")
    check("记成放弃，带原因", (mk.get("result"), "文件被占用" in mk.get("note", "")), (makeup.GAVE_UP, True))
    check("关机不再等终末地补跑", makeup.waiting(e, NOW), [])
    check("不再压着", makeup.holding(e, r5, NOW), False)
    check("没有闹钟（不会一直等）", makeup.next_moment(e.cfg.state_dir, NOW), None)

    print("\n[跨午夜：23:55 派的补跑，00:02 还算在跑，不去改回；零点后开始的记录记进昨天那份]")
    mid = NOW.replace(hour=0, minute=2)
    y_disp = mid - timedelta(minutes=7)
    yday = f"{y_disp:%Y-%m-%d}"
    root6 = put_master(MSTASH)
    e = build(root6)
    y_rec = rec("MaaEnd", y_disp - timedelta(hours=1), failed=THREE)
    e.state.append_ledger(y_rec)
    makeup.stash_first(e.cfg, y_rec.run_id, y_disp)
    WANT3 = enabled(master_of(root6))
    makeup._write_marker(e.cfg.state_dir, yday, {"MaaEnd": {"dispatched_at": y_disp.isoformat(), "result": makeup.DISPATCHED,
                                                           "tries": 1, "run_id": y_rec.run_id, "tasks": THREE}})
    check("过了零点还算在跑", makeup.in_flight(e.cfg.state_dir, mid), ["MaaEnd"])
    check("闹钟也看昨天那份", makeup.next_moment(e.cfg.state_dir, mid)[0],
          y_disp + timedelta(minutes=makeup.STALE_MIN, seconds=1))
    makeup.maybe_run(e, mid)
    check("在跑的时候不改回（存放背包还开着）", (enabled(master_of(root6)), "StashBackpack" in WANT3), (WANT3, True))
    e._script_running = lambda name: name == "MaaEnd"
    makeup.maybe_run(e, mid + timedelta(minutes=9))
    check("看到在跑，记在昨天那份里", bool(mk_of(e, "MaaEnd", yday).get("seen_running_at")))
    check("仍算在跑", makeup.in_flight(e.cfg.state_dir, mid + timedelta(minutes=15)), ["MaaEnd"])
    r_mid = rec("MaaEnd", mid + timedelta(minutes=1), ok=True)
    makeup.on_record(e, r_mid)
    makeup.after_outcome(e, r_mid, None)   # its own outcome check passed (handle._handle_success)
    check("零点后开始的记录也记进昨天那份", mk_of(e, "MaaEnd", yday).get("result"), makeup.OK)
    row = {x["run_id"]: x for x in e.state.read_ledger(yday)}[y_rec.run_id]
    check("昨天那条失败记上补跑做成", bool((row.get("raw") or {}).get("makeup_ok")))
    e = build()
    makeup._write_marker(e.cfg.state_dir, yday, {"MaaEnd": {"dispatched_at": y_disp.isoformat(),
                                                           "result": makeup.DISPATCHED, "tries": 1}})
    makeup.maybe_run(e, mid + timedelta(minutes=20))
    check("过了零点一直没跑出记录：照样收尾", mk_of(e, "MaaEnd", yday).get("result"), makeup.NO_RECORD)

    print("\n[开机改回：补跑还在跑（中继重启、机器没关）就不改回；AUTO-MAS 问不到或已跑完就照旧改回]")
    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()
    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any
    for _n in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
               "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_n, _Stub(_n))
    import boot_stages
    from ark_relay.features import collect_retry
    from ark_relay.features import gameupdate
    from ark_relay.core import mastercfg
    saved_fns = (gameupdate.spmed_check, mastercfg.prune_maaend_orphans,
                 mastercfg.migrate_maaend_options, collect_retry.restore_master, eng_mod._automas_snapshot)
    gameupdate.spmed_check = lambda cfg: ""
    mastercfg.prune_maaend_orphans = mastercfg.migrate_maaend_options = lambda a, b: (0, "")
    collect_retry.restore_master = lambda cfg: ""
    try:
        for label, snap, ago, restored in (
                ("补跑 2 分钟前派出、AUTO-MAS 说终末地还在跑 → 不改回",
                 {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}, 2, False),
                ("AUTO-MAS 说终末地跑完了 → 改回",
                 {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "完成"}]}]}, 2, True),
                ("AUTO-MAS 问不到（刚开机）→ 改回", None, 2, True),
                ("补跑是 30 分钟前派的、早没动静 → 改回",
                 {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}, 30, True)):
            root7 = put_master(MSTASH)
            cfg7 = types.SimpleNamespace(automas_dir=root7, state_dir=tmpdir(), maaend_dir=FX)
            now7 = datetime.now(tz=SERVER_TZ)
            makeup.stash_first(cfg7, "run-f", now7)
            makeup._write_marker(cfg7.state_dir, f"{now7 - timedelta(minutes=ago):%Y-%m-%d}",
                                 {"MaaEnd": {"dispatched_at": (now7 - timedelta(minutes=ago)).isoformat(),
                                             "result": makeup.DISPATCHED, "tries": 1}})
            eng_mod._automas_snapshot = lambda snap=snap: snap
            boot_stages._stage_reenable_maaend(cfg7, Notes(), Log())
            check(label, master_of(root7) == MSTASH, restored)
    finally:
        (gameupdate.spmed_check, mastercfg.prune_maaend_orphans,
         mastercfg.migrate_maaend_options, collect_retry.restore_master, eng_mod._automas_snapshot) = saved_fns

    print("\n[补跑算中继自己派的：commands.run_script 记下「脚本 MaaEnd」，关机判断读它，不靠更新重跑的时刻]")
    from ark_relay.features import commands
    from ark_relay.features import trigger
    sd8 = tmpdir()
    old_env = os.environ.get("ARK_STATE_DIR")
    os.environ["ARK_STATE_DIR"] = str(sd8)
    real_mas = commands._mas
    commands._mas = lambda path, body=None, timeout=20: (
        {"data": {"sid1": {"Info": {"Name": "MaaEnd"}}}} if path == "/api/scripts/get" else {"status": "success"})
    try:
        ok8, _ = commands.run_script("MaaEnd")
    finally:
        commands._mas = real_mas
        os.environ["ARK_STATE_DIR"] = old_env
    notes8 = trigger._read_dispatches(sd8)
    check("派下去了，记下是中继派的", (ok8, [d["what"] for d in notes8]), (True, ["脚本 MaaEnd"]))
    at8 = datetime.fromisoformat(notes8[0]["at"])
    e = build()
    e.cfg.state_dir = sd8
    e._round_is_manual = lambda group: True          # by the schedule alone the make-up's round reads as manual
    rows = [{"run_id": "m", "script": "MAA", "user": "arknights", "ok": True,
             "started": (at8 - timedelta(hours=4)).isoformat(), "finished": (at8 - timedelta(hours=3, minutes=45)).isoformat()},
            {"run_id": "mk", "script": "MaaEnd", "user": "endfield", "ok": True,
             "started": (at8 + timedelta(minutes=3)).isoformat(), "finished": (at8 + timedelta(minutes=20)).isoformat()}]
    check("隔了几小时的补跑那一轮：不算手动", shutdown._last_round_manual(e, at8 + timedelta(minutes=25), rows), False)
    check("引擎上没有更新重跑的时刻", getattr(e, "_gu_rerun_at", None), None)
    later = rows + [{"run_id": "h", "script": "MaaEnd", "user": "endfield", "ok": True,
                     "started": (at8 + timedelta(hours=3)).isoformat(), "finished": (at8 + timedelta(hours=3, minutes=20)).isoformat()}]
    check("补跑之后有人手动再跑一趟：仍算手动（不被补跑连带）",
          shutdown._last_round_manual(e, at8 + timedelta(hours=4), later), True)

    print("\n[补跑的结果只认它自己的记录：走通就定了；没成时只有 AUTO-MAS 紧跟着的重试能改；晚班改不了]")
    def booked(seq, start_result=makeup.DISPATCHED):
        e = build()
        ent = {"dispatched_at": NOW.isoformat(), "result": start_result, "tries": 1, "tasks": ["整个 MAA"]}
        makeup._write_marker(e.cfg.state_dir, day, {"MAA": ent})
        out = []
        for r_ in seq:
            makeup.on_record(e, r_)
            out.append(mk_of(e, "MAA").get("result"))
        return out
    a1 = rec("MAA", NOW + timedelta(minutes=1), failed=LOGIN)
    a2 = rec("MAA", a1.finished + timedelta(seconds=5), ok=True)
    eve_fail = rec("MAA", NOW + timedelta(hours=5), failed=["MAA 部分任务执行失败"])
    eve_ok = rec("MAA", NOW + timedelta(hours=5), ok=True)
    check("第一次没成、AUTO-MAS 紧跟着重试走通 → 走通", booked([a1, a2]), [makeup.FAILED, makeup.OK])
    check("走通之后晚班失败 → 仍是走通", booked([a2, eve_fail]), [makeup.OK, makeup.OK])
    check("没成之后晚班走通 → 仍是没成", booked([a1, eve_ok]), [makeup.FAILED, makeup.FAILED])
    check("同一条记录来两次不重复改", booked([a1, a1]), [makeup.FAILED, makeup.FAILED])
    check("十分钟没跑出记录后，晚班的记录不算它的", booked([eve_ok], makeup.NO_RECORD), [makeup.NO_RECORD])

    print("\n[没有 id 的任务：按名字和位置存原状，开存放背包时它们一项不动，存放背包照样挪位置，改回一模一样]")
    m3 = copy.deepcopy(MASTER)
    t3 = m3["instances"][0]["tasks"]
    t3.insert(3, {"taskName": "VisitFriends", "enabled": True})
    t3.insert(5, {"taskName": "SellProduct", "enabled": True, "enabledByController": {"Win32-Front": True}})
    t3.append({"taskName": "StashBackpack", "enabled": False})
    root3 = put_master(m3)
    cfg3 = types.SimpleNamespace(automas_dir=root3, state_dir=tmpdir(), maaend_dir=FX)
    check("开了存放背包", makeup.stash_first(cfg3, "run-g", NOW), (True, ""))
    d3 = master_of(root3)
    noid = [t for t in d3["instances"][0]["tasks"] if "id" not in t]
    check("没 id 的也一项不关（存放背包开了）", sorted((t["taskName"], t["enabled"]) for t in noid),
          [("SellProduct", True), ("StashBackpack", True), ("VisitFriends", True)])
    check("没 id 的控制器开关也不动", [t.get("enabledByController") for t in noid if t["taskName"] == "SellProduct"],
          [{"Win32-Front": True}])
    names3 = [t["taskName"] for t in d3["instances"][0]["tasks"] if not t["taskName"].startswith("__")]
    check("没 id 的存放背包挪到最前", names3[0], "StashBackpack")
    check("开着的还是原来那些，加上存放背包", sorted(enabled(d3)), sorted(enabled(m3) + ["StashBackpack"]))
    makeup.restore(cfg3)
    check("改回和原来一模一样（顺序、开关、没有的键）", master_of(root3), m3)

    print("\n[补跑走通：前面那趟「没干完」的终末地也算补上（整轮再跑过了）]")
    e = build(put_master(MASTER))
    inc = rec("MaaEnd", earlier - timedelta(minutes=30), ok=True, run_id=f"{day}/endfield/MaaEnd-inc")
    e.state.append_ledger(inc)
    e.state.mark_incomplete(day, inc.run_id, "有 1 项没干成")
    makeup._write_marker(e.cfg.state_dir, day, {"MaaEnd": {"dispatched_at": NOW.isoformat(), "result": makeup.DISPATCHED,
                                                           "tries": 1, "tasks": [WHOLE]}})
    mk_rec = rec("MaaEnd", NOW + timedelta(minutes=1), ok=True)
    makeup.on_record(e, mk_rec)
    check("结果核对之前不清（AUTO-MAS 说成功不算干完）",
          {x["run_id"]: x for x in e.state.read_ledger(day)}[inc.run_id].get("incomplete"), "有 1 项没干成")
    makeup.after_outcome(e, mk_rec, "MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n· 基质刷取 真的刷了：x")
    check("补跑自己核对没过：前面那条照旧没干完",
          {x["run_id"]: x for x in e.state.read_ledger(day)}[inc.run_id].get("incomplete"), "有 1 项没干成")
    e.state.mark_incomplete(day, inc.run_id, "有 1 项没干成")
    makeup._write_marker(e.cfg.state_dir, day, {"MaaEnd": {"dispatched_at": NOW.isoformat(), "result": makeup.DISPATCHED,
                                                           "tries": 1, "tasks": [WHOLE]}})
    mk_rec2 = rec("MaaEnd", NOW + timedelta(minutes=2), ok=True, run_id=f"{day}/endfield/MaaEnd-mk2")
    makeup.on_record(e, mk_rec2)
    makeup.after_outcome(e, mk_rec2, None)
    check("没干完那条清掉了", {x["run_id"]: x for x in e.state.read_ledger(day)}[inc.run_id].get("incomplete"), "")

    print("\n[the day's make-up marker is there but corrupt: no second make-up, said once]")


    _w = _Messages()
    makeup.log.addHandler(_w)
    try:
        dispatched.clear()
        makeup._dispatch = lambda script: (dispatched.append(script), (True, "ok"))[1]
        e = build(put_master(MASTER))
        r = rec("MaaEnd", earlier, failed=THREE)
        hold(e, r)
        bad = makeup._marker_file(e.cfg.state_dir, day)
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text('{"MaaEnd": {"dispatched_at": "20', encoding="utf-8")
        check("corrupt marker counts as spent", makeup.attempted(e.cfg.state_dir, day, "MaaEnd"), True)
        check("not held for a make-up (its alarm goes out)", makeup.holding(e, r, NOW), False)
        check("no make-up dispatched over three ticks",
              ([makeup.maybe_run(e, NOW + timedelta(seconds=s)) for s in (0, 150, 300)], dispatched),
              ([False, False, False], []))
        check("the corrupt file is left as it was", bad.read_text(encoding="utf-8"), '{"MaaEnd": {"dispatched_at": "20')
        check("one WARNING over all those reads", len([ln for ln in _w.lines if bad.name in ln]), 1)
        check("a missing marker is still not spent", makeup.attempted(e.cfg.state_dir, "2000-01-01", "MaaEnd"), False)
    finally:
        makeup.log.removeHandler(_w)

    makeup._dispatch, makeup._kill_game = real_dispatch, real_kill
    _mc.CHECKS.update(_mc_real)


def _part_hand_started_retry():
    """A task a person started at AUTO-MAS that retried inside itself gives one outcome."""
    import json
    import os
    from datetime import datetime, timedelta


    FX = fx_dir(Path(__file__), "fixtures") / "hand-started-1016"
    REAL_DAY = "2026-10-16"
    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "debug").mkdir()
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import collector, texts
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features import handle
    from ark_relay.features import collect_retry, makeup, makeup as marker
    from ark_relay.features import machinecheck as _mc

    _mc.load()
    _mc_real = dict(_mc.CHECKS)
    _mc.CHECKS.clear()     # machine checks have their own tests (tests/test_mc.py)

    TODAY = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    TASK = "c6d40887-2c99-43e7-9bbf-a94f9bf49d6d"


    def moved(data: bytes) -> bytes:
        return data.replace(REAL_DAY.encode(), TODAY.encode())


    (AUTOMAS / "debug" / "app.log").write_bytes(moved((FX / "app.log").read_bytes()))
    DAY_DIR = HIST / TODAY / "endfield"
    DAY_DIR.mkdir(parents=True)
    for f in (FX / "history" / REAL_DAY / "endfield").iterdir():
        (DAY_DIR / f.name).write_bytes(moved(f.read_bytes()))


    class Notes:
        def __init__(self):
            self.sent, self.down = [], False

        def send(self, title, body="", **kw):
            if self.down:
                return ["企业微信机器人 超时"]
            self.sent.append((title, body, kw.get("alert", False)))
            return []


    handle._ship_evidence = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None
    handle._push_unverified = lambda eng, rec: None   # task screenshots are not in the fixture
    collect_retry.restore_master = lambda cfg: ""
    dispatched = []
    makeup._dispatch = lambda script: (dispatched.append(script), (True, "ok"))[1]
    makeup._kill_game = lambda: None


    def build(state_dir=None):
        cfg = Config()
        cfg.state_dir = state_dir or tmpdir()
        cfg.automas_dir = AUTOMAS
        cfg.history_dir = HIST
        e = eng_mod.Engine(cfg, source=_NoSrc(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        return e


    def alarms(e):
        return [(t, b) for t, b, a in e.notifier.sent if a]


    def held_id(e, where="_pending"):
        r = getattr(e, where).get(KEY)
        return r.run_id if r is not None else None


    def records(*stems):
        got = collector.scan(HIST, set())
        return [r for r in got if not stems or r.run_id.rsplit("/", 1)[-1].removeprefix("MaaEnd-") in stems]


    KEY = ("MaaEnd", "endfield")
    FIRST, SECOND, THIRD = (f"{TODAY}/endfield/MaaEnd-{s}" for s in ("09-21-28", "09-23-36", "09-53-33"))

    print("[the real records: three runs reach the relay, all in task c6d40887]")
    recs = records()
    check("09-53-01 (the update install) is not a run; the other three are, in start order",
          [r.run_id for r in recs], [FIRST, SECOND, THIRD])
    check("results as AUTO-MAS wrote them", [(r.ok, r.raw.get("maaend_result")) for r in recs],
          [(False, "游戏启动失败"), (False, "MaaEnd 部分任务执行失败: 🚚转交委托、🗡️选剑演武、🎱基质刷取"),
           (True, "Success!")])

    print("\n[the whole task lands in one tick: retry healed pushes ⚠️ once (no double ❌)]")
    e = build()
    for r in records():
        handle._handle(e, r)
    e._flush_pending()
    makeup.maybe_run(e)
    check("all three booked as started by hand, task c6d40887",
          [x.get("raw", {}).get("hand_started") for x in e.state.read_ledger(TODAY)], [TASK] * 3)
    check("one retry-healed ⚠️ in the group (never two ❌)", [t for t, _ in alarms(e)], [texts.self_healed("MaaEnd")])
    check("nothing left held", dict(e._pending), {})
    check("no _recovered bypass on engine", hasattr(e, "_recovered"), False)
    check("no make-up dispatched", dispatched, [])
    check("no make-up marker written", makeup.read_marker(e.cfg.state_dir, TODAY), {})

    print("\n[step by step: 09-21-28 held, replaced by 09-23-36, healed by 09-53-33]")
    e = build()
    r1, r2, r3 = records()
    handle._handle(e, r1)
    check("09-21-28 (游戏启动失败) is held, not pushed", (held_id(e),
                                                      alarms(e)), (FIRST, []))
    check("held, it gets no make-up", (marker.candidates(e), KEY in e._pending and makeup.holding(e, e._pending[KEY])),
          ([], False))
    handle._handle(e, r2)
    check("09-23-36 replaces it (same task), still nothing pushed",
          (held_id(e), alarms(e)), (SECOND, []))
    handle._handle(e, r3)
    check("09-53-33's success settles the held 09-23-36 immediately via group ⚠️",
          (KEY in e._pending, [t for t, _ in alarms(e)]), (False, [texts.self_healed("MaaEnd")]))
    before_flush = len(alarms(e))
    e._flush_pending()
    check("the flush does not send a second time", len(alarms(e)), before_flush)

    print("\n[no later success in the task -> exactly one ❌, about the last failure, saying whose run]")
    e = build()
    for r in records("09-21-28", "09-23-36"):
        handle._handle(e, r)
    check("nothing pushed while the records are booked", alarms(e), [])
    e._flush_pending()
    makeup.maybe_run(e)
    got = alarms(e)
    check("one alarm", [t for t, _ in got], [texts.failed("MaaEnd")])
    body = got[0][1] if got else ""
    check("first line: started by hand", body.splitlines()[:1], [texts.HAND_STARTED_NOTE])
    check("names the last attempt's failed tasks", ("转交委托" in body, "选剑演武" in body, "基质刷取" in body),
          (True, True, True))
    check("not about 游戏启动失败 (the replaced attempt)", "游戏启动失败" in body, False)
    check("no make-up dispatched, no marker", (dispatched, makeup.read_marker(e.cfg.state_dir, TODAY)), ([], {}))
    check("queue empty", dict(e._pending), {})

    print("\n[the task is still running when a record lands -> nothing pushed until it stops]")
    e = build()
    running = {"MaaEnd"}
    e._script_running = lambda name: name in running
    e._scripts_running = lambda: bool(running)
    for r in records("09-21-28"):
        handle._handle(e, r)
    e._flush_pending()
    check("still running: held, nothing pushed", (KEY in e._pending, alarms(e)), (True, []))
    running.clear()
    e._flush_pending()
    check("stopped with no later record: one ❌ saying started by hand",
          [(t, b.splitlines()[0]) for t, b in alarms(e)], [(texts.failed("MaaEnd"), texts.HAND_STARTED_NOTE)])

    print("\n[the group robot is down at the flush: kept held, no make-up meanwhile, sent next tick]")
    e = build()
    for r in records("09-21-28", "09-23-36"):
        handle._handle(e, r)
    e.notifier.down = True
    e._flush_pending()
    makeup.maybe_run(e)
    check("not sent, still held", (alarms(e), held_id(e)), ([], SECOND))
    check("no make-up dispatched for a person's run", dispatched, [])
    check("no make-up marker written", makeup.read_marker(e.cfg.state_dir, TODAY), {})
    check("shutdown counts it as an alarm still to go out (not a make-up to wait for)",
          [r.run_id for r in e._pending.values() if not makeup.holding(e, r)], [SECOND])
    # A relay restart in between (a deploy): the hold survives with its task id.
    e2 = build(e.cfg.state_dir)
    check("restored from disk with its task id", (e2._pending.get(KEY).raw if KEY in e2._pending else {}).get("hand_started"), TASK)
    e2._flush_pending()
    check("robot back: exactly one ❌ saying started by hand",
          [(t, b.splitlines()[0]) for t, b in alarms(e2)], [(texts.failed("MaaEnd"), texts.HAND_STARTED_NOTE)])
    e2._flush_pending()
    check("not sent twice", len(alarms(e2)), 1)

    print("\n[the last attempt ran but left items undone -> only that round's ⚠️, the earlier failures healed]")
    e = build()
    e._verify_outcome = lambda r: "MaaEnd 这一轮有 1 项没干成" if r.ok else None
    for r in records():
        handle._handle(e, r)
    e._flush_pending()
    check("both earlier retry-healed ⚠️ and undone ⚠️ reach group, no ❌",
          [t for t, _ in alarms(e)], [texts.self_healed("MaaEnd"), texts.ROUND_INCOMPLETE])
    check("held failure settled, queue empty", dict(e._pending), {})

    def scheduled(hh: int, mm: int, ok: bool) -> RunRecord:
        """A shift's MaaEnd round (no hand_started: its own task, not c6d40887)."""
        t0 = datetime.now(tz=SERVER_TZ).replace(hour=hh, minute=mm, second=0, microsecond=0)
        return RunRecord(run_id=f"{TODAY}/endfield/MaaEnd-{hh:02d}-{mm:02d}-00", script="MaaEnd", user="endfield",
                         started=t0, finished=t0 + timedelta(minutes=20), ok=ok,
                         failed_tasks=[] if ok else ["协议空间"], raw={})


    def hand_alarms(e):
        return [(t, b) for t, b in alarms(e) if b.startswith(texts.HAND_STARTED_NOTE)]


    for why in ("the shift's MaaEnd is queued at the flush", "the group robot is down at the flush"):
        for ok in (False, True):
            print(f"\n[the person's last failure still held ({why}); then a shift's MaaEnd "
                  f"{'success' if ok else 'failure'} lands -> the person's ❌ goes out, not replaced or healed]")
            e = build()
            running = set()
            e._script_running = lambda name: name in running
            if why.startswith("the shift"):
                running.add("MaaEnd")
            for r in records("09-21-28", "09-23-36"):
                handle._handle(e, r)
            e.notifier.down = why.startswith("the group")
            e._flush_pending()
            check("held over the flush", (held_id(e), alarms(e)), (SECOND, []))
            e.notifier.down = False
            s = scheduled(14, 40, ok)
            handle._handle(e, s)
            got = hand_alarms(e)
            check("the person's ❌ went out at once, about 09-23-36's failed tasks",
                  ([t for t, _ in got], all(w in (got[0][1] if got else "") for w in ("转交委托", "选剑演武", "基质刷取"))),
                  ([texts.failed("MaaEnd")], True))
            check("no _recovered bypass", hasattr(e, "_recovered"), False)
            check("the shift's record is on its own path", held_id(e), None if ok else s.run_id)
            running.clear()
            for _ in range(3):
                e._flush_pending()
                makeup.maybe_run(e)
            check("still exactly one alarm about the person's task", len(hand_alarms(e)), 1)

    print("\n[the robot is still down when the shift's record lands -> the person's ❌ is queued, sent next tick]")
    e = build()
    for r in records("09-21-28", "09-23-36"):
        handle._handle(e, r)
    e.notifier.down = True
    e._flush_pending()
    handle._handle(e, scheduled(14, 40, False))
    check("queued to be sent, not lost", [x[2] for x in e._unsent_unresolved], [SECOND])
    e.notifier.down = False
    e._flush_pending()
    check("sent once the robot is back", len(hand_alarms(e)), 1)

    _mc.CHECKS.update(_mc_real)


def _part_makeup_midnight():
    """A MAA round that crossed midnight sits on two ledger files; the make-up reads both."""
    import os
    import shutil
    from datetime import datetime


    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(TMP / "AUTO-MAS"),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core.config import RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features import makeup

    FX = fx_dir(Path(__file__), "fixtures")


    class Eng:
        def __init__(self, days=("2026-10-02", "2026-10-03")):
            d = tmpdir()
            for day in days:
                shutil.copy(FX / f"ledger-midnight-{day}.jsonl", d / f"ledger-{day}.jsonl")
            self.state = State(d)
            self.cfg = type("C", (), {"state_dir": d})()


    makeup._machinecheck = lambda eng, ev: None


    def at(s):
        return datetime.fromisoformat(s)


    def rec(run_id, started, finished, ok, failed):
        return RunRecord(run_id=run_id, script="MAA", user="arknights", started=at(started),
                         finished=at(finished), ok=ok, failed_tasks=failed, raw={})


    print("\n[跨午夜那一轮：昨天那份账本里打过仗的那次也算，不再整个补跑]")
    e = Eng()
    held = rec("2026-10-02/arknights/MAA-20-18-59", "2026-10-03T00:19:45+08:00",
               "2026-10-03T00:19:46+08:00", False, ["MAA 未能正确登录 PRTS"])
    why = makeup.maa_work_done(e, held)
    check("23:44 那次打了 34 分钟 → 不补", bool(why), True)
    morning = rec("2026-10-03/arknights/MAA-05-00-02", "2026-10-03T09:00:50+08:00",
                  "2026-10-03T09:01:20+08:00", False, ["MAA 未能正确登录 PRTS"])
    check("早上 9 点那一轮跟昨晚隔了好几个小时 → 照样补",
          makeup.maa_work_done(Eng(days=("2026-10-02",)), morning), "")

    print("\n[补跑走通：昨天那份里同一轮的失败也记上补跑做成，前面走通的那轮不动]")
    e = Eng()
    since = at("2026-10-03T01:40:00+08:00")
    makeup._write_marker(e.cfg.state_dir, "2026-10-03", {"MAA": {
        "dispatched_at": since.isoformat(), "result": makeup.DISPATCHED, "tries": 1}})
    mk = rec("2026-10-03/arknights/MAA-makeup", "2026-10-03T01:41:00+08:00",
             "2026-10-03T02:00:00+08:00", True, [])
    makeup.on_record(e, mk)
    makeup.after_outcome(e, mk, None)   # its own outcome check passed (handle._handle_success)
    y = {x["run_id"]: x for x in e.state.read_ledger("2026-10-02")}
    t = {x["run_id"]: x for x in e.state.read_ledger("2026-10-03")}


    def tied(rows):
        return [k for k, v in rows.items() if (v.get("raw") or {}).get("makeup_ok")]


    check("今天那 4 次都记上", len(tied(t)), 4)
    check("昨天 23:40 起那 6 次都记上", len(tied(y)), 6)
    check("昨天 21:30 走通那次不动", bool((y["2026-10-02/arknights/MAA-17-30-03"].get("raw") or {}).get("makeup_ok")), False)


def _part_hand_started_runs():
    """A run a person starts from AUTO-MAS's own screen is told apart from the shift, and
its failures are pushed like any other's, saying whose run it was.
    """
    import json
    import os
    from datetime import datetime


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "debug").mkdir()
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import handle
    from ark_relay.features import runwatch
    from ark_relay.features import trigger
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    APP_LOG = """\
2026-09-25 21:30:00.780 | INFO     | 业务调度 | 创建任务: e715210d-7445-4ff4-97c4-642e1a55afe7, 模式: AutoProxy, 触发来源: scheduled_task
2026-09-25 22:01:10.000 | INFO     | 业务调度 | 任务结束: e715210d-7445-4ff4-97c4-642e1a55afe7
2026-10-03 00:19:50.991 | INFO     | 业务调度 | 创建任务: 68b6e221-419d-444b-aff7-8643822c64ce, 模式: AutoProxy, 触发来源: manual_task
2026-10-03 00:19:50.993 | SUCCESS  | 业务调度 | 任务 68b6e221-419d-444b-aff7-8643822c64ce 检索完成，包含 1 个脚本项
2026-10-03 00:19:50.994 | INFO     | 业务调度 | 开始运行任务: 68b6e221-419d-444b-aff7-8643822c64ce, 模式: AutoProxy
2026-10-03 00:40:01.000 | INFO     | 业务调度 | 任务 68b6e221-419d-444b-aff7-8643822c64ce 已结束
2026-10-03 01:00:00.100 | INFO     | 业务调度 | 创建任务: 0000aaaa-1111-2222-3333-444455556666, 模式: AutoProxy, 触发来源: manual_task
"""
    (AUTOMAS / "debug" / "app.log").write_text(APP_LOG, encoding="utf-8")


    class Notes:
        def __init__(self):
            self.sent, self.bodies = [], []

        def send(self, title, body="", **kw):
            self.sent.append((title, kw.get("alert", False)))
            self.bodies.append(body)
            return False


    def at(d, hh, mm, ss=0):
        return datetime(2026, 9 if d == 25 else 10, d, hh, mm, ss, tzinfo=SERVER_TZ)


    def rec(run_id, started, ok=False, script="MAA"):
        return RunRecord(run_id=run_id, script=script, user="arknights", started=started,
                         finished=started.replace(minute=started.minute + 5), ok=ok,
                         failed_tasks=[] if ok else ["自动肉鸽"], raw={})


    def build():
        cfg = Config()
        cfg.state_dir = TMP / "state"
        cfg.state_dir.mkdir(exist_ok=True)
        e = eng_mod.Engine(cfg, source=_NoSrc(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._verify_outcome = lambda r: None
        return e


    handle._weekly_gates = lambda eng, r: None
    handle._ship_evidence = lambda eng, r: ""      # no bundle upload in a test

    print("\n[读 AUTO-MAS 自己写的「触发来源」]")
    tasks = trigger.read(AUTOMAS)
    check("读到三个任务", [t.source for t in tasks], ["scheduled_task", "manual_task", "manual_task"])
    check("结束时间也读到了", tasks[1].ended, at(3, 0, 40, 1))
    check("「任务结束:」这种写法也认", tasks[0].ended, at(25, 22, 1, 10))
    check("00:20 那趟属于 00:19:50 建的手动任务", [t.id[:8] for t in trigger.tasks_at(tasks, at(3, 0, 20))], ["68b6e221"])
    check("定时那趟属于定时任务", [t.source for t in trigger.tasks_at(tasks, at(25, 21, 31))], ["scheduled_task"])

    print("\n[同时开着两个任务（10-02 23:43 就有）：有一个不是手动的就不算手动]")
    both = trigger.parse("""\
2026-10-04 09:00:00.100 | INFO     | 业务调度 | 创建任务: aaaa0000-0000-0000-0000-000000000001, 模式: AutoProxy, 触发来源: scheduled_task
2026-10-04 09:10:00.100 | INFO     | 业务调度 | 创建任务: bbbb0000-0000-0000-0000-000000000002, 模式: AutoProxy, 触发来源: manual_task
""".splitlines())
    check("两个都开着", len(trigger.tasks_at(both, at(4, 9, 20))), 2)
    check("不算手动", trigger.hand_started_at(both, at(4, 9, 20), TMP / "state"), None)
    check("只有手动那个开着时才算", trigger.hand_started_at(both[1:], at(4, 9, 20), TMP / "state").id[:4], "bbbb")

    print("\n[有人手动开的失败：记账、不补跑，同一任务的重试结束就报群并写明是手动开的]")
    from ark_relay.core import texts
    from ark_relay.features import makeup as marker
    e = build()
    r = rec("m1", at(3, 0, 20))
    e._handle(r)
    check("先压着，等同一任务后面那次", (("MAA", "arknights") in e._pending, e.notifier.sent), (True, []))
    check("压着也不补跑", marker.eligible(r, now=at(3, 0, 30)), False)
    e._flush_pending()
    check("没进待推队列", ("MAA", "arknights") in e._pending, False)
    check("报群一条", e.notifier.sent, [(texts.failed("MAA"), True)])
    check("头一行写明是手动开的", e.notifier.bodies[-1].splitlines()[:1] if e.notifier.bodies else [],
          [getattr(texts, "HAND_STARTED_NOTE", "-")])
    check("账上记了是手动开的", [x.get("raw", {}).get("hand_started", "")[:8]
                               for x in e.state.read_ledger("2026-10-03")], ["68b6e221"])

    print("\n[定时的失败：和以前一样压着]")
    e = build()
    e._handle(rec("s1", at(25, 21, 31)))
    check("进了待推队列", ("MAA", "arknights") in e._pending)

    print("\n[中继自己开的（AUTO-MAS 也记 manual_task）：和以前一样压着]")
    trigger.note_dispatch(TMP / "state", "队列 晚班", now=at(3, 0, 59, 58))
    e = build()
    e._handle(rec("r1", at(3, 1, 1)))
    check("进了待推队列", ("MAA", "arknights") in e._pending)

    print("\n[有人手动开的跑完了但有项目没干成：报「这一轮没干完」，写明是手动开的]")
    e = build()
    e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成"
    e._handle(rec("m2", at(3, 0, 25), ok=True))
    check("报群一条", e.notifier.sent, [(texts.ROUND_INCOMPLETE, True)])
    check("写明是手动开的", bool(e.notifier.bodies) and e.notifier.bodies[-1].startswith(
        getattr(texts, "HAND_STARTED_NOTE", "-")))

    print("\n[之前压着定时的失败、后来有人手动跑成：不发「重试后成功」，那次失败照报（审计 10-13 s7 #2）]")
    e = build()
    e._handle(rec("s2", at(3, 0, 10, 0).replace(day=2, hour=21, minute=31)))
    had = ("MAA", "arknights") in e._pending
    e._verify_outcome = lambda r: None
    e._handle(rec("m3", at(3, 0, 30), ok=True))
    check("先压着了", had)
    check("压着的那条清掉了", ("MAA", "arknights") in e._pending, False)
    check("无 _recovered 旁路", hasattr(e, "_recovered"), False)
    check("压着的那次失败照报进群，写明是有人手动跑成的",
          (e.notifier.sent[-1:], e.notifier.bodies[-1].splitlines()[:1] if e.notifier.bodies else []),
          ([(texts.failed("MAA"), True)], [texts.hand_fixed_note("00:30") if hasattr(texts, "hand_fixed_note") else "-"]))

    print("\n[超时：手动那趟也报（写明是手动开的），定时那趟照报]")
    e = build()
    now = at(3, 0, 30)
    ev = runwatch.Timeout(at(3, 0, 29), "MAA", "运行超时", 1, 3, at(3, 0, 20))
    check("手动那趟：发出去了", runwatch.check_timeouts(e, [ev], now), [])
    check("手动那趟也报", [a for _, a in e.notifier.sent], [True])
    check("…写明是手动开的", bool(e.notifier.bodies) and e.notifier.bodies[-1].startswith(
        getattr(texts, "HAND_STARTED_NOTE", "-")))
    (AUTOMAS / "debug" / "app.log").write_text(
        APP_LOG.replace("触发来源: manual_task", "触发来源: scheduled_task", 1), encoding="utf-8")
    runwatch.check_timeouts(e, [runwatch.Timeout(at(3, 0, 29, 30), "MAA", "运行超时", 2, 3, at(3, 0, 20))], now)
    check("定时那趟照报", [a for _, a in e.notifier.sent], [True, True])
    check("…不写手动", e.notifier.bodies[-1].startswith(getattr(texts, "HAND_STARTED_NOTE", "-")), False)
    (AUTOMAS / "debug" / "app.log").write_text(APP_LOG, encoding="utf-8")

    print("\n[班次超时：只算定时器开的那个任务（手动开的不是这一班，说它「这一班还没跑完」不对）]")
    e = build()
    check("手动任务不算班次超时", runwatch._not_the_shift(e, {"taskId": "68b6e221-419d-444b-aff7-8643822c64ce"}))
    check("定时任务照算", runwatch._not_the_shift(e, {"taskId": "e715210d-7445-4ff4-97c4-642e1a55afe7"}), False)
    check("日志里没有的照算", runwatch._not_the_shift(e, {"taskId": "deadbeef"}), False)
    check("中继自己开的照算", runwatch._not_the_shift(e, {"taskId": "0000aaaa-1111-2222-3333-444455556666"}), False)

    print("\n[读不到 AUTO-MAS 日志：一切照旧]")
    (AUTOMAS / "debug" / "app.log").unlink()
    e = build()
    e._handle(rec("x1", at(3, 0, 20)))
    check("进了待推队列", ("MAA", "arknights") in e._pending)

    print("\n[the relay's own-starts file is unreadable: said once, not on every read]")


    _w = _Messages()
    trigger.log.addHandler(_w)
    try:
        sd = tmpdir()
        check("no file: [] and nothing said", (trigger._read_dispatches(sd), _w.lines), ([], []))
        (sd / trigger.DISPATCH_FILE).write_text('[{"at": "2026-10-0', encoding="utf-8")
        got = [trigger._read_dispatches(sd) for _ in range(3)]
        check("corrupt: still []", got, [[], [], []])
        check("corrupt: one WARNING naming the consequence",
              len([ln for ln in _w.lines if "当成有人手动开的" in ln and trigger.DISPATCH_FILE in ln]), 1)
        (sd / trigger.DISPATCH_FILE).write_text("[]", encoding="utf-8")
        trigger._read_dispatches(sd)
        (sd / trigger.DISPATCH_FILE).write_text("{bad", encoding="utf-8")
        trigger._read_dispatches(sd)
        check("readable in between: said again when it breaks again", len(_w.lines), 2)
    finally:
        trigger.log.removeHandler(_w)

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_collect_retry_robustness():
    """collect_retry resilience: tasklist/taskkill timeouts and unreadable log files."""
    import json
    import os
    import subprocess
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features import collect_retry as cr

    FX = fx_dir(Path(__file__), "fixtures") / "collect-retry-2026-09-11"
    zh = json.loads((FX / "zh_cn.json").read_text(encoding="utf-8"))
    labels = cr.failed_labels_from_locale(zh)

    warns = _Messages()
    cr.log.addHandler(warns)
    saved_run = cr.subprocess.run
    try:
        print("[_running: passes timeout and degrades cleanly on TimeoutExpired / OSError]")
        seen_kw = {}

        def _fake_ok(argv, **kw):
            seen_kw.update(kw)
            return types.SimpleNamespace(stdout='"MaaEnd.exe","1234","Console","1","50,000 K"\n')

        cr.subprocess.run = _fake_ok
        check("_running parses CSV output", cr._running(("MaaEnd.exe", "Endfield.exe")), {"MaaEnd.exe"})
        check("_running sets a positive timeout",
              isinstance(seen_kw.get("timeout"), (int, float)) and seen_kw["timeout"] > 0, True)

        def _fake_timeout(argv, **kw):
            raise subprocess.TimeoutExpired(argv, kw.get("timeout") or 30)

        warns.lines.clear()
        cr.subprocess.run = _fake_timeout
        check("_running on TimeoutExpired returns empty set instead of hanging", cr._running(("MaaEnd.exe",)), set())
        check("_running logs one plain-Chinese WARNING",
              (len(warns.lines), [texts.plain(m) for m in warns.lines]), (1, [[]]))

        def _fake_oserr(argv, **kw):
            raise OSError("tasklist missing")

        warns.lines.clear()
        cr.subprocess.run = _fake_oserr
        check("_running on OSError returns empty set", cr._running(("MaaEnd.exe",)), set())
        check("_running OSError warning is plain Chinese",
              (len(warns.lines), [texts.plain(m) for m in warns.lines]), (1, [[]]))

        print("\n[_kill: timeout on first process does not skip killing the second in run_retry finally]")
        killed_cmds = []

        def _kill_first_times_out(argv, **kw):
            killed_cmds.append(list(argv))
            if len(killed_cmds) == 1:
                raise subprocess.TimeoutExpired(argv, kw.get("timeout") or 30)
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        warns.lines.clear()
        cr.subprocess.run = _kill_first_times_out
        md_k = tmpdir() / "maaend_kill"
        (md_k / "debug").mkdir(parents=True)
        (md_k / "debug" / "2026-09-12-1.log").write_bytes((FX / "mxu-app-override-line.log").read_bytes())
        saved_bring = cr._bring_up_and_run
        cr._bring_up_and_run = lambda *a, **k: ({"AutoCollectRoute15": True}, "")
        try:
            verdict, note = cr.run_retry(md_k, ["AutoCollectRoute15"], "saturday", spawn=lambda *a: None)
        finally:
            cr._bring_up_and_run = saved_bring
        check("run_retry still returns its verdict when first _kill times out", (verdict, note),
              ({"AutoCollectRoute15": True}, ""))
        check("both MaaEnd.exe and Endfield.exe got taskkill attempts",
              [cmd[-1] for cmd in killed_cmds], ["MaaEnd.exe", "Endfield.exe"])
        check("_kill timeout warning is plain Chinese",
              (len(warns.lines), [texts.plain(m) for m in warns.lines]), (1, [[]]))
    finally:
        cr.subprocess.run = saved_run
        cr.log.removeHandler(warns)

    print("\n[run_retry: unreadable / vanishing MXU app logs are skipped without crashing]")
    md = tmpdir() / "maaend_logs"
    dbg = md / "debug"
    dbg.mkdir(parents=True)
    older = dbg / "2026-09-12-1.log"
    newer = dbg / "2026-09-12-2.log"
    vanished = dbg / "2026-09-12-3.log"
    older.write_bytes((FX / "mxu-app-override-line.log").read_bytes())
    newer.write_text("locked newest log", encoding="utf-8")
    vanished.write_text("vanishing log", encoding="utf-8")
    os.utime(older, (1700000100, 1700000100))
    os.utime(newer, (1700000200, 1700000200))
    os.utime(vanished, (1700000300, 1700000300))

    real_read_text = Path.read_text
    real_stat = Path.stat
    called_overrides = []
    saved_bring = cr._bring_up_and_run
    saved_kill = cr._kill

    def _read_locked(self, *a, **kw):
        if self == newer:
            raise PermissionError(13, "log file locked (test)")
        return real_read_text(self, *a, **kw)

    def _stat_vanished(self, *a, **kw):
        if self == vanished:
            raise FileNotFoundError(2, "log vanished (test)")
        return real_stat(self, *a, **kw)

    Path.read_text = _read_locked
    Path.stat = _stat_vanished
    cr._bring_up_and_run = lambda _md, rs, ov, **kw: (called_overrides.append(ov) or {r: True for r in rs}, "")
    cr._kill = lambda name: None
    try:
        v, note = cr.run_retry(md, ["AutoCollectRoute15"], "saturday", spawn=lambda *a: None)
        check("skips vanished + locked newer logs and falls back to older override",
              (v, note, len(called_overrides)), ({"AutoCollectRoute15": True}, "", 1))
    finally:
        Path.read_text = real_read_text
        Path.stat = real_stat
        cr._bring_up_and_run = saved_bring
        cr._kill = saved_kill

    md_only = tmpdir() / "maaend_unreadable"
    (md_only / "debug").mkdir(parents=True)
    bad_log = md_only / "debug" / "2026-09-12-1.log"
    bad_log.write_text("cannot read", encoding="utf-8")
    spawned = []

    def _read_bad(self, *a, **kw):
        if self == bad_log:
            raise OSError(5, "I/O error (test)")
        return real_read_text(self, *a, **kw)

    Path.read_text = _read_bad
    try:
        v, note = cr.run_retry(md_only, ["AutoCollectRoute15"], "saturday", spawn=lambda *a: spawned.append(a))
    finally:
        Path.read_text = real_read_text
    check("all MXU app logs unreadable: refuses cleanly without spawning",
          (v, "找不到上一趟采集的参数" in note, spawned), ({"AutoCollectRoute15": None}, True, []))

    print("\n[latest_gathering_run: unreadable history log is skipped without crashing]")
    hist = tmpdir() / "history_err"
    (hist / "d").mkdir(parents=True)
    good_hist = hist / "d" / "good.log"
    locked_hist = hist / "d" / "locked.log"
    good_hist.write_text((FX / "automas-MaaEnd-06-17-17.log").read_text(encoding="utf-8"), encoding="utf-8")
    locked_hist.write_text("[x] 任务完成: 🧺自动采集\n", encoding="utf-8")

    def _read_hist_locked(self, *a, **kw):
        if self == locked_hist:
            raise PermissionError(13, "history log locked (test)")
        return real_read_text(self, *a, **kw)

    Path.read_text = _read_hist_locked
    try:
        rec, rts = cr.latest_gathering_run(
            [{"script": "MaaEnd", "run_id": "d/good"}, {"script": "MaaEnd", "run_id": "d/locked"}],
            hist, labels)
        check("skips unreadable newest history log and reads earlier MaaEnd run",
              (rec and rec["run_id"], rts), ("d/good", ["AutoCollectRoute15", "AutoCollectRoute16"]))
        rec2, rts2 = cr.latest_gathering_run([{"script": "MaaEnd", "run_id": "d/locked"}], hist, labels)
        check("only unreadable history log: returns (None, [])", (rec2, rts2), (None, []))
    finally:
        Path.read_text = real_read_text


def _part_retry_note_time():
    """The 「后来在 … 那趟重试里」 note names the retry by its start, on both clocks."""
    #!/usr/bin/env python3
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger as core

    es = [json.loads(x) for x in (fx_dir(Path(__file__), "fixtures") / "ledger-1008-maaend-two-lists.jsonl").read_text(encoding="utf-8").splitlines()]
    notes = core.retried_notes(es)
    got = notes.get("2026-10-08/endfield/MaaEnd-05-29-15", "")
    ok = got == "自动采集　后来在 10:35（东京 11:35）开始的那趟重试里做成了"
    print(("  ✓ " if ok else "  ✗ ") + got)
    print("\n" + ("all checks passed" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


def _part_makeup_outcome_undone_reverts_marker():
    """When a make-up exits ok=True but _verify_outcome finds undone work, after_outcome
    reverts makeup/<day>.json from OK to FAILED so report.makeup_line and handle.after_makeup
    do not claim it passed, and the held failure is not falsely marked self-healed."""
    import json
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import engine as eng_mod, texts
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features import handle, machinecheck as _mc, makeup, report

    TODAY = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    MASTER = {"instances": [{"controllerName": "Win32", "tasks": [
        {"id": "1", "taskName": "FarmEssence", "enabled": True},
    ]}]}

    def at(hh, mm):
        return datetime.fromisoformat(f"{TODAY}T{hh:02d}:{mm:02d}:00+08:00").astimezone(SERVER_TZ)

    def put_master():
        root = tmpdir()
        f = root / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps(MASTER, ensure_ascii=False, indent=2), encoding="utf-8")
        return root

    class Notes:
        def __init__(self):
            self.sent: list = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert))
            return []

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = put_master()
        cfg.maaend_dir = None
        cfg.history_dir = None
        e = eng_mod.Engine(cfg, source=_NoSrc(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda s: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        e._archive_maaend_evidence = lambda r: None
        e._maintenance_today = lambda g: False
        return e

    def rec(script, started, *, ok=False, failed=None, raw=None):
        user = "arknights" if script == "MAA" else "endfield"
        return RunRecord(
            run_id=f"{TODAY}/{user}/{script}-{started:%H-%M-%S}",
            script=script, user=user, started=started,
            finished=started + timedelta(minutes=10),
            ok=ok, failed_tasks=list(failed or []), raw=dict(raw or {}),
        )

    saved = (makeup._dispatch, makeup._kill_game, handle._ship_evidence, handle._weekly_gates, dict(_mc.CHECKS))
    _mc.CHECKS.clear()
    makeup._dispatch = lambda s: (True, "ok")
    makeup._kill_game = lambda: None
    handle._ship_evidence = lambda e, r: ""
    handle._weekly_gates = lambda e, r: None
    try:
        # 1. MaaEnd make-up exits ok=True but outcome check finds 基质刷取 undone
        e = build()
        fail = rec("MaaEnd", at(9, 5), failed=["基质刷取"])
        handle._handle(e, fail)
        e._flush_pending()
        check("MaaEnd 补跑派下去了", makeup.maybe_run(e, at(10, 5)), True)
        undone_msg = "MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n· 基质刷取 真的刷了：日志里没有刷基质"
        e._verify_outcome = lambda r: undone_msg
        mk = rec("MaaEnd", at(10, 6), ok=True, raw={"tasks_done": ["基质刷取"], "tasks_evidence": {"基质刷取": "x"}})
        handle._handle(e, mk)

        ent = makeup.read_marker(e.cfg.state_dir, TODAY)["MaaEnd"]
        check("MaaEnd 补跑结果核对没过：marker 改回 FAILED", ent["result"], makeup.FAILED)
        check("MaaEnd marker 写明没干完的项目", ent["note"], "跑完了但没干完：基质刷取")
        fail_row = {x["run_id"]: x for x in e.state.read_ledger(TODAY)}[fail.run_id]
        check("原失败行不写 makeup_ok", (fail_row.get("raw") or {}).get("makeup_ok"), None)
        line = report._makeup_tech_line(e.cfg.state_dir, TODAY)
        check("日报 makeup_line 为空；技术日志说还是没成且不带走通了",
              (report.makeup_line(e.cfg.state_dir, TODAY),
               "还是没成（跑完了但没干完：基质刷取）" in line, "走通了" in line), ("", True, False))
        check("技术日志 makeup 行是人话", texts.plain(line), [])
        check("handle.after_makeup 返回 UNRESOLVED", handle.after_makeup(e, fail, at(10, 20)), (handle.UNRESOLVED, "补跑也没成"))
        check("原失败留在 _pending 等报群（引擎无 _recovered 旁路）",
              (hasattr(e, "_recovered"), list(e._pending)), (False, [("MaaEnd", "endfield")]))
        e._flush_pending()
        titles = [t for t, _, a in e.notifier.sent if a]
        check("先报补跑没干完，再由 _flush_pending 报原失败补跑也没成",
              titles, [texts.unresolved_undone("终末地", "早班"), texts.unresolved("终末地", "早班")])
        check("报完后清空 _pending", dict(e._pending), {})

        # 2. MAA make-up exits ok=True but outcome check finds 基建换班 undone
        e2 = build()
        mfail = rec("MAA", at(9, 5), failed=["开始唤醒"], raw={"maa_unreachable": True})
        handle._handle(e2, mfail)
        e2._flush_pending()
        check("MAA 补跑派下去了", makeup.maybe_run(e2, at(10, 5)), True)
        e2._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：日志里没有换班"
        mmk = rec("MAA", at(10, 6), ok=True)
        handle._handle(e2, mmk)
        ment = makeup.read_marker(e2.cfg.state_dir, TODAY)["MAA"]
        mline = report._makeup_tech_line(e2.cfg.state_dir, TODAY)
        check("MAA marker 改回 FAILED 且写明基建换班", (ment["result"], ment["note"]), (makeup.FAILED, "跑完了但没干完：基建换班"))
        check("MAA 日报 makeup_line 为空，技术日志有明细",
              (report.makeup_line(e2.cfg.state_dir, TODAY), mline),
              ("", "明日方舟失败后自动补跑，还是没成（跑完了但没干完：基建换班）"))
        check("MAA 技术日志 makeup 行是人话", texts.plain(mline), [])
        check("MAA after_makeup 返回 UNRESOLVED", handle.after_makeup(e2, mfail, at(10, 20)), (handle.UNRESOLVED, "补跑也没成"))
        e2._flush_pending()
        check("MAA 两次报警分别覆盖没干完与原失败补跑没成",
              [t for t, _, a in e2.notifier.sent if a],
              [texts.unresolved_undone("明日方舟", "早班"), texts.unresolved("明日方舟", "早班")])

        # 3. Settings-only undone preserves prep_note + crash replay without _TIE_UP still reverts OK -> FAILED
        e3 = build()
        makeup._write_marker(e3.cfg.state_dir, TODAY, {
            "MaaEnd": {"dispatched_at": at(10, 5).isoformat(), "result": makeup.DISPATCHED,
                       "tries": 1, "tasks": [makeup.WHOLE_MAAEND], "prep_note": "背包满了，但找不到存放背包"},
        })
        rmk = rec("MaaEnd", at(10, 6), ok=True)
        makeup.on_record(e3, rmk)
        makeup._TIE_UP.pop(rmk.run_id, None)    # simulate restart between on_record and after_outcome
        settings_msg = f"MaaEnd 这一轮{texts.OUTCOME_SETTINGS_HEAD}\n· 基质刷取：被重置了"
        makeup.after_outcome(e3, rmk, settings_msg)
        ent3 = makeup.read_marker(e3.cfg.state_dir, TODAY)["MaaEnd"]
        line3 = report.makeup_line(e3.cfg.state_dir, TODAY)
        check("崩溃重放后也改回 FAILED 并保留 prep_note",
              (ent3["result"], "设置被重置成默认值：基质刷取" in ent3["note"], "背包满了" in ent3["note"]),
              (makeup.FAILED, True, True))
        check("设置重置时的 makeup_line 是人话", texts.plain(line3), [])

        # 4. Control: outcome check passes -> stays OK, marks makeup_ok, pushes group ⚠️ immediately (no _recovered)
        e4 = build()
        ok_fail = rec("MAA", at(9, 5), failed=["开始唤醒"], raw={"maa_unreachable": True})
        handle._handle(e4, ok_fail)
        e4._flush_pending()
        makeup.maybe_run(e4, at(10, 5))
        e4._verify_outcome = lambda r: None
        handle._handle(e4, rec("MAA", at(10, 6), ok=True))
        check("核对通过：marker 保持 OK，立即直推群并清空 _pending",
              (makeup.read_marker(e4.cfg.state_dir, TODAY)["MAA"]["result"],
               dict(e4._pending), [t for t, _, a in e4.notifier.sent if a]),
              (makeup.OK, {}, [texts.makeup_passed("明日方舟", "早班")]))
        before_e4 = len(e4.notifier.sent)
        e4._flush_pending()
        check("核对通过：后续不再重复推送", len(e4.notifier.sent), before_e4)
    finally:
        makeup._dispatch, makeup._kill_game, handle._ship_evidence, handle._weekly_gates = saved[:4]
        _mc.CHECKS.clear()
        _mc.CHECKS.update(saved[4])


if __name__ == "__main__":
    sys.exit(run_parts([_part_collect_history_db, _part_collect_main, _part_collect_blocked, _part_collect_retry_cutoff, _part_collect_retry_robustness, _part_collect_watch, _part_makeup_main, _part_hand_started_retry, _part_makeup_midnight, _part_hand_started_runs, _part_retry_note_time, _part_makeup_outcome_undone_reverts_marker]))
