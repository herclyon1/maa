"""Gathering: history.db, the gathering retry (and a blocked route), the cut-off retry, the collect watch.

One part per former file, each run on its own (tests/_parts.py): test_collect_history_db.py, test_collect_retry.py, test_collect_retry_cutoff.py, test_collect_watch.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_collect_history_db():
    """AUTO-MAS v5.8.0-beta.2 records runs in data/history.db, not in per-run JSON files.

The machine updated itself to it on 2026-10-28 08:47. The relay read only the JSON
layout, booked none of that morning's runs (MAA 09:01, OK-WW 09:18 and 09:19, MaaEnd
09:33) and pushed 「早班 没有运行」 at 10:04 (ledger #120). The fixture is that
morning's real history.db and the five 0.log files it points to.

    Formerly test_collect_history_db.py.
    """
    import shutil
    from datetime import timedelta, timezone

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector


    FX = Path(__file__).resolve().parent / "fixtures" / "automas-58-history-2026-10-28"
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
        from ark_relay.features.makeup import collect_retry as cr
        from ark_relay.features.verify import outcome
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
        import logging
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


def _part_main():
    """Per-route gathering retry, checked against the real files of 2026-09-11.

That day routes 15 and 16 failed in the 10:18 run, AUTO-MAS re-ran all 17,
and upstream declined a per-route retry (MaaEnd/MaaEnd#5660). The fixtures
are the AUTO-MAS log of that run, MXU's logged override line, and MaaEnd's
zh_cn locale.

    Formerly test_collect_retry.py.
    """
    import http.server
    import json
    import threading

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.makeup import collect_retry as cr


    FX = Path(__file__).resolve().parent / "fixtures" / "collect-retry-2026-09-11"
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


    from ark_relay.features.report import report as _report
    from ark_relay.core import texts as _texts
    from ark_relay.core.notify import route_of as _route_of
    got, _ = _retry_outcome({"AutoCollectRoute15": False})
    check("仍没走通：报群", [x for x in got if x[0] == _texts.COLLECT_RETRY_FAILED], [(_texts.COLLECT_RETRY_FAILED, True)])
    check("…开始补跑那条不发（结果才定）", [x for x in got if x[0] == _texts.COLLECT_RETRY_START], [])
    got, _ = _retry_outcome({"AutoCollectRoute15": None})
    check("没结论：也报群", [x for x in got if x[0] == _texts.COLLECT_RETRY_FAILED], [(_texts.COLLECT_RETRY_FAILED, True)])
    got, _ = _retry_outcome({"AutoCollectRoute15": False}, {"AutoCollectRoute15": ["2026-09-11"]})
    check("连续两天：报群", [x for x in got if x[0] == _texts.COLLECT_RECURRENT], [(_texts.COLLECT_RECURRENT, True)])
    # The user, 2026-10-06 05:07: 「报错后自己好了的，只进日报、不进群。」 The start is not
    # sent at all; all walked goes out only as COLLECT_RETRY_OK, which notify routes to
    # the log (not pushed); the daily report's 「自动采集补跑：…」 line carries both.
    got, sd = _retry_outcome({"AutoCollectRoute15": True})
    check("补跑走通：开始那条不发", [x for x in got if x[0] == _texts.COLLECT_RETRY_START], [])
    check("补跑走通：只有「补跑后全部走完」一条，不带 alert", got, [(_texts.COLLECT_RETRY_OK, False)])
    check("…它走日志，不推", _route_of(_texts.COLLECT_RETRY_OK), "log")
    check("日报那一行说走通了", _report.retry_line(sd, "2026-09-12").startswith("自动采集补跑：走通 "), True)

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
    # The master as a relay before 2026-10-06 left it after narrowing to 15, 16 and 4,
    # with the original lists saved in narrow.json.
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
    import logging
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


def _part_collect_blocked():
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

    from ark_relay.core import ledger_rows, texts
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.core.notify import route_of
    from ark_relay.features.makeup import collect_retry as cr
    from ark_relay.features.report import report
    from ark_relay.features.selfcheck import machinecheck as mc
    from ark_relay.features.verify import collector_maaend as cm, outcome

    FX = Path(__file__).resolve().parent / "fixtures" / "collect-blocked-1005-1012"
    ZH = json.loads((Path(__file__).resolve().parent / "fixtures" / "collect-retry-2026-09-11" / "zh_cn.json")
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
    check("日报原文", "自动采集 16/17 条走通，撞上「战斗中无法使用」没采到：路线10：重红柱状菌" in block, True)
    print("    " + line.strip())
    check("日报这句是人话", texts.plain(line), [])

    print("\n[半路断掉的那趟（09-11 06-47-30，最后一行是「路线5：轻黯石」）：后来的截图不算它的]")
    # on_error keeps pictures for days; refresh_raw re-parses every row of the day at report
    # time. A later run's picture (same day 12:30, or the real 10-05/10-08/10-12 ones) used
    # to land in the cut-short run's open last window and book 路线5 as not gathered.
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
        from ark_relay.features.makeup import makeup
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
    check("日报那句写了为什么补", report.retry_line(sd, "2026-10-08", md),
          "自动采集补跑：第一趟撞上「战斗中无法使用」没采到：路线10：重红柱状菌；走通 路线10：重红柱状菌")
    check("…是人话", texts.plain(report.retry_line(sd, "2026-10-08", md)), [])
    asked, sent, stamp, _ = maybe_run(False)
    check("补跑还没采到：照旧报群", [(t, a) for t, _, a in sent], [(texts.COLLECT_RETRY_FAILED, True)])
    asked, sent, stamp, _ = maybe_run(False, {"AutoCollectRoute10": ["2026-10-07"]})
    check("连续两天：照旧按复发报群", [(t, a) for t, _, a in sent], [(texts.COLLECT_RECURRENT, True)])

    print("\n[MaaEnd 的路线名里找不到这条：说一次，不每个关机判断都说（每条警告都会进群）]")
    import logging


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
    # A failed run is not outcome-checked (AUTO-MAS re-runs it: 10-12 06-04-00, 10-08 05-29-15);
    # its daily row is the booking (daysim 10-08 / 10-12 had #29 go red on exactly those).
    st, ev = c29(None, {"maaend_collect_total": 17, "maaend_collect_blocked": [R10]})
    check("失败的那趟（没做结果核对）：日报记了就 PASS", st, "PASS")
    st, ev = c29(None, {"maaend_collect_total": 17})
    check("失败的那趟：日报也没记：FAIL", st, "FAIL")

    print("\n[边界：同一秒里按毫秒分（截图名、历史日志、maafw.log 都带毫秒），日志和补跑用同一条规矩]")
    # 10-12 10:45:39 holds, to the millisecond (maafw.bak.2026.10.12-10.56.34.166.log and
    # the history log MaaEnd-06-04-00): AutoCollectRoute10End recognised .488 / acted .489,
    # AutoCollectRoute11Start recognised .510 - the moment MaaEnd announces 「路线11：重黯石」,
    # which AUTO-MAS stamps .533 - and acted .717. Cut to the second, a picture anywhere in
    # that second went to route 11 in the history log (route 10 booked as walked, route 11
    # re-run for nothing) and to route 11 or nothing in the retry (Start->End windows).
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
    from ark_relay.features.alarm import runchecks, verdict

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
    # MaaFW also writes on_error names with a single underscore before the node
    # (2026.10.08-10.01.43.463_AutoCollectRoute1Start.png). shot_time reads both, so the
    # outcome check and #29 took such a relay-device picture; obstacle_shots globbed only
    # ___ names, so the daily row and the retry list (_blocked_in) did not - #29 then failed
    # 「日报那一行没写它没采到」 and route 10 was never re-run.
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
    # A gathering task's last route ends, in the history log, at 「任务完成/任务失败: 自动采集」
    # (route_windows); MaaFW announces the same moment as Tasker.Task.Succeeded/Failed of
    # AutoCollectSchedule, some 25 s after the last route's End node (maafw-attempt3 of
    # 2026-09-14: AutoCollectRoute17End 11:19:57.922, Tasker.Task.Failed 11:20:23.065). The
    # retry used to close the last route at End, so a picture in that tail was the route's
    # in the daily row (re-run) and nobody's in the retry (judged walked).
    # Both logs below are constructed for a run whose last route is 11: the maafw fixture
    # keeps only the route 9-11 node lines, so it gains the task's end event; the history
    # log 06-04-00 is cut before its 「路线12」 line and gains its real 「任务完成」 line.
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

    print("\nall checks passed" if not fails else f"\nFAILED: {len(fails)}")


def _part_collect_retry_cutoff():
    """The gathering retry, cut off mid-way, is run once more; every way out closes MaaEnd and the game.

Audit s16 #2: the 「done today」 stamp is written before run_retry, which can take
half an hour. The relay does stop on this machine (relay.log:30844, 「10-10 12:29:59
收到停止通知（停止服务）」); a stamp left without `finished` then said 「已经跑过」 for
the rest of the day - no retry, no alarm, MaaEnd.exe / Endfield.exe left running.
run_retry's early 「gave up」 returns also left both running.

    Formerly test_collect_retry_cutoff.py.
    """
    import json
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.makeup import collect_retry as cr
    from ark_relay.features.preupdate import preupdate_common as pc


    FX = Path(__file__).resolve().parent / "fixtures" / "collect-retry-2026-09-11"
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
    from ark_relay.features.report import report
    gs = tmpdir()
    (gs / "collect-retry").mkdir(parents=True)
    (gs / "collect-retry" / "2026-09-12.json").write_text(json.dumps(after, ensure_ascii=False), encoding="utf-8")
    line = report.retry_line(gs, "2026-09-12")
    check("日报不说「还没有结果」", "还没有结果" in line, False)
    check("日报说补跑两次都没跑完、哪条路线没结论", ("补跑两次都没跑完" in line, "没结论" in line), (True, True))
    did, _ = outcome(None)
    check("没有印记 → 照常跑", did, True)

    print("\n[补跑被打断后这次没补成（脚本还在跑）：下一次调用不再报、不再关一遍]")
    # Review of c6922283: the WARNING and the kills came before the early returns while the
    # stamp was rewritten only on the path that re-runs, so every later tick said and killed again.
    import logging


    class _Warnings(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.msgs = []

        def emit(self, r):
            self.msgs.append(r.getMessage())


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
    w = _Warnings()
    cr.log.addHandler(w)
    del killed[:]
    try:
        r1 = cr.maybe_run(eng, now=NOW, day="2026-09-12")
        r2 = cr.maybe_run(eng, now=NOW + timedelta(minutes=1), day="2026-09-12")
    finally:
        cr.log.removeHandler(w)
        cr.latest_gathering_run, cr._locale, cr.restore_master = saved
    check("两次都没补（脚本还在跑）", (r1, r2), (False, False))
    check("只报一次没跑完", sum("没跑完" in m for m in w.msgs), 1)
    check("只关一次 MaaEnd 和游戏", killed, ["MaaEnd.exe", "Endfield.exe"])
    check("印记还没写结束，脚本停了还会补", "finished" in json.loads(f.read_text(encoding="utf-8")), False)

    print("\n[没跑完的两句警告原样进群：时刻写成「10-22 16:44」，不带 ISO 的「T16」（账本 #110）]")
    from ark_relay.core.texts import plain
    w2 = _Warnings()
    cr.log.addHandler(w2)
    try:
        outcome(cut)
        outcome(dict(cut, cut_off="earlier"))
    finally:
        cr.log.removeHandler(w2)
    said = [m for m in w.msgs + w2.msgs if "没跑完" in m]
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

Fixture: the real MaaFW event lines of 2026-09-14 attempt 3 (10:53-11:20),
where Route10 failed and AUTO-MAS retried all 17 routes at 11:21:43.

    Formerly test_collect_watch.py.
    """
    import json
    import logging
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.run import collect_watch


    # Every 「目录监听掉了」 the watcher logs while the test runs. It must stay empty:
    # the line Windows CI showed after the result line (2026-10-07) is the watcher
    # seeing its directory removed by _tmp's cleanup at exit, not a drop mid-test.
    class _Drops(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.msgs = []

        def emit(self, record):
            self.msgs.append(record.getMessage())


    _drops = _Drops()
    from ark_relay.core import watch as _watch
    _watch.log.addHandler(_drops)


    FIX = Path(__file__).resolve().parent / "fixtures" / "collect-watch-2026-09-14" / "maafw-attempt3.log"
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
    check("收窄的函数没了", (hasattr(collect_watch.Watcher, "_narrow"), hasattr(__import__("ark_relay.features.makeup.collect_retry").features.makeup.collect_retry, "narrow_master")),
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

    check("目录监听在测试期间没掉过", _drops.msgs, [])


if __name__ == "__main__":
    sys.exit(run_parts([_part_collect_history_db, _part_main, _part_collect_blocked, _part_collect_retry_cutoff, _part_collect_watch]))
