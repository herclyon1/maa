"""Config: no bot, a config-check skip, one warning, and who writes it.

One part per former file, each run on its own (tests/_parts.py): test_config_no_bot.py, test_config_skip_1016.py, test_config_warn_once.py, test_config_writers.py.
"""
from __future__ import annotations
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tmp  # loaded before the parts: its atexit cleanup and env default stay
from _parts import run_parts

_BEFORE_THE_PARTS = (_tmp,)


def _part_config_no_bot():
    """A config with Server酱 but no group robot must start, with a warning.

Audit s6 #2 (2026-10-13): Config.validate reported a missing WECOM_BOT_URL as a
problem (「没有它一条都送不到」), and a problem stops the relay at boot
(boot_stages / cmd_local). Group alarms fall back to Server酱
(notify._GROUP_ORDER), so that setup works; it is a warning now.

    Formerly test_config_no_bot.py.
    """
    import logging
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    HIST = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), WECOM_BOT_URL="", SERVERCHAN_KEY="SCT-test",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_AGENTID="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import Config

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
        if not ok:
            fails.append(label)


    said: list = []
    h = logging.Handler()
    h.emit = lambda r: said.append((r.levelname, r.getMessage()))
    ARK_ROOT = "ark"   # the parent of every relay logger
    logging.getLogger(ARK_ROOT).addHandler(h)

    print("[Server酱 only: starts, warns that alarms go to Server酱]")
    cfg = Config()
    check("no blocking problem", cfg.validate(), [])
    check("one WARNING line naming the fallback",
          [lvl for lvl, m in said if "WECOM_BOT_URL" in m and "Server酱" in m], ["WARNING"])

    print("\n[WeCom app only: group alarms have no channel at all -> still a problem]")
    os.environ.update(SERVERCHAN_KEY="", WECOM_CORPID="c", WECOM_SECRET="s", WECOM_AGENTID="1")
    check("blocked", len(Config().validate()), 1)

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")
    sys.exit(1 if fails else 0)


def _part_config_skip():
    """AUTO-MAS refused to start a script of a running queue: said at once, with its reason.

Replays 2026-10-16. The morning shift (早班 09:00: MAA, OK-WW, MaaEnd) ran MAA and
OK-WW; at 09:34:05 AUTO-MAS's own config check refused MaaEnd (it could not find the
official Endfield launcher) and moved on, writing no history record. The relay said
nothing until the hour backstop: 10:34 「🔌 MaaEnd 没有运行（早班）」 without the
reason, a 🩺 copy of it, 12:08 「⏰ 一直没出结果」 for the same thing, a 全绿 interim
report at 11:34, and the shutdown held on 「还差 MaaEnd」 for the rest of the boot.

Sources: app.log lines 291-306 below are verbatim from D:\\ark\\automas\\debug\\app.log
(10-16), except the 09:00 「创建任务」 line, which is built from the task id in
line 306 in the shape trigger.py documents. The ledger rows are the machine's
ledger-2026-10-16.jsonl (run_id, script, user, started, finished, ok, transitional);
the relay.log timeline is relay-1016.log 220-254 (09:34:07 tick, 10:34:12 backstop).

    Formerly test_config_skip_1016.py.
    """
    import json
    import logging
    import os
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "debug").mkdir()
    MORNING, EVENING = "cc32e55a-55d0-408d-980d-642e66d111ae", "6f09a385-b0ae-4ff6-9890-50339bdaddeb"
    S_MAA, S_OKWW, S_END = ("754d129e-d587-435b-b75f-a0b91aac7020", "c5e96ddc-aae9-4a73-b6fe-1312a417382d",
                            "59da8762-8fa7-4260-8aee-10f9ca00097a")
    doc = {"instances": [{"uid": MORNING, "type": "QueueConfig"}, {"uid": EVENING, "type": "QueueConfig"}]}
    for uid, name, t, items in ((MORNING, "早班", "09:00", (S_MAA, S_OKWW, S_END)), (EVENING, "晚班", "21:30", (S_MAA,))):
        doc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                    "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": t}}},
                                       "QueueItem": {str(i): {"Info": {"ScriptId": s}} for i, s in enumerate(items)}}}
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    scripts = {"instances": [{"uid": s} for s in (S_MAA, S_OKWW, S_END)]}
    for uid, name, path, user in ((S_MAA, "maa明日方舟", "D:\\ark\\MAA", "arknights"),
                                  (S_OKWW, "鸣潮", "D:\\ark\\okww", "wuwa"),
                                  (S_END, "MaaEnd", "D:\\ark\\maaend", "endfield")):
        scripts[uid] = {"Info": {"Name": name, "Path": path},
                        "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": user}}}}}
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(scripts, ensure_ascii=False), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), ARK_SHUTDOWN_AFTER_RUN="1",
                      ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.core import ledger as core, texts
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features.alarm import errwatch, missed
    from ark_relay.features.run import runwatch
    from ark_relay.features.shutdown import shutdown
    from ark_relay.features.selfcheck import machinecheck as _mc
    _mc.load()
    _mc_real = dict(_mc.CHECKS)
    _mc.CHECKS.clear()

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
        if not ok:
            fails.append(label)


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return False


    class Src:
        def fetch(self, seen):
            return []


    def at(hh, mm, ss=0):
        return datetime(2026, 10, 16, hh, mm, ss, tzinfo=SERVER_TZ)


    APPLOG = AUTOMAS / "debug" / "app.log"
    LINES = [
        # Built from line 306's task id (the queue's own task), trigger.py's documented shape.
        "2026-10-16 09:00:00.780 | INFO     | 业务调度 | 创建任务: b5f541de-20a4-4b73-856a-027cd91161b2, 模式: AutoProxy, 触发来源: scheduled_task",
        # Verbatim, app.log 291-306.
        "2026-10-16 09:34:04.904 | INFO     | 配置管理 | 开始处理通用日志, 日志长度: 637, 日志标记: Success!",
        "2026-10-16 09:34:04.906 | SUCCESS  | 配置管理 | 通用日志统计完成, 日志路径: D:\\ark\\automas\\history\\2026-10-16\\wuwa\\OK-WW-05-20-13.log",
        "2026-10-16 09:34:04.917 | INFO     | OK-WW 通知工具 | 开始推送通知, 模式: 统计信息, 标题: 10-16 |√|  wuwa 的 OK-WW 自动代理统计报告",
        "2026-10-16 09:34:04.919 | SUCCESS  | OK-WW 自动代理 | 用户 50ca12aa-0288-4592-982e-60f0bd6dc74e 的 OK-WW 自动代理任务已完成",
        "2026-10-16 09:34:04.920 | INFO     | 任务执行 | 任务收尾完成: AutoProxyTask - 用时: 1.172秒",
        "2026-10-16 09:34:04.920 | INFO     | OK-WW 调度器 | 复原 OK-WW 脚本配置文件: D:\\ark\\automas\\data\\c5e96ddc-aae9-4a73-b6fe-1312a417382d\\Temp",
        "2026-10-16 09:34:04.948 | INFO     | 任务执行 | 任务执行结束，开始收尾: OkwwManager",
        "2026-10-16 09:34:04.948 | INFO     | OK-WW 调度器 | 复原 OK-WW 脚本配置文件: D:\\ark\\automas\\data\\c5e96ddc-aae9-4a73-b6fe-1312a417382d\\Temp",
        "2026-10-16 09:34:04.984 | INFO     | OK-WW 通知工具 | 开始推送通知, 模式: 代理结果, 标题: 10-16 | OK-WW的自动代理任务报告",
        "2026-10-16 09:34:04.986 | INFO     | 任务执行 | 任务收尾完成: OkwwManager - 用时: 0.031秒",
        "2026-10-16 09:34:04.988 | INFO     | 业务调度 | 任务开始: 59da8762-8fa7-4260-8aee-10f9ca00097a",
        "2026-10-16 09:34:05.023 | WARNING  | MaaEnd 调度器 | 未通过配置检查: 未找到终末地官方启动器, 请选择鹰角官方启动器 Launcher.exe 或 Games.exe！",
        "2026-10-16 09:34:05.027 | INFO     | 任务执行 | 任务执行结束，开始收尾: MaaEndManager",
        "2026-10-16 09:34:05.029 | INFO     | 任务执行 | 任务收尾完成: MaaEndManager - 用时: 0.000秒",
        "2026-10-16 09:34:05.029 | INFO     | 任务执行 | 任务执行结束，开始收尾: Task",
        "2026-10-16 09:34:05.030 | INFO     | 业务调度 | 任务结束: b5f541de-20a4-4b73-856a-027cd91161b2",
    ]
    SKIP_AT = 12          # index of the 未通过配置检查 line

    # ledger-2026-10-16.jsonl, as on the machine.
    LEDGER = [("2026-10-16/arknights/MAA-05-00-24", "MAA", "arknights", at(9, 0, 27), at(9, 18, 20), True, False),
              ("2026-10-16/wuwa/OK-WW-05-18-27", "OK-WW", "wuwa", at(9, 19, 47), at(9, 20, 1), False, True),
              ("2026-10-16/wuwa/OK-WW-05-20-13", "OK-WW", "wuwa", at(9, 21, 26), at(9, 33, 54), True, False)]


    def build(state_dir=None, lines=None):
        APPLOG.write_text("".join(ln + "\n" for ln in LINES[:lines]), encoding="utf-8")
        cfg = Config()
        cfg.state_dir = state_dir or tmpdir()
        st = State(cfg.state_dir)
        if state_dir is None:
            st.ledger_path("2026-10-16").write_text("\n".join(json.dumps(
                {"run_id": r, "script": s, "user": u, "started": a.isoformat(), "finished": b.isoformat(), "ok": ok,
                 "failed_tasks": [], "transitional": tr, "raw": {}}) for r, s, u, a, b, ok, tr in LEDGER) + "\n",
                encoding="utf-8")
        e = eng.Engine(cfg, source=Src(), state=st, notifier=Notes())
        e._scripts_running = lambda: False
        e._boot_time = lambda now: at(8, 45, 0)        # relay-1016.log: the relay came up 08:45-08:46
        e._started_at = at(8, 45, 18)
        e._handled_any = True                          # it saw MAA and OK-WW land (09:18:29, 09:34:07)
        e.state.report_sent = lambda d: True
        return e


    def alarms(e):
        return [(t, b) for t, b, a in e.notifier.sent if a]


    print("[10-16 09:34:07: the tick that read app.log tells the group at once, with AUTO-MAS's reason]")
    e = build()
    e._run_watch(at(9, 34, 7))
    got = alarms(e)
    check("one alarm", len(got), 1)
    title, body = got[0] if got else ("", "")
    check("title names MaaEnd and the shift", title, "🔌 MaaEnd 没有运行（早班）")
    check("body gives the reason in plain words", "AUTO-MAS 开跑前检查没过：找不到终末地官方启动器" in body, True)
    check("body says the run did not happen and needs a fix", "没开跑" in body and "要有人去改" in body, True)
    check("body passes texts.plain()", texts.plain(body), [])
    check("no English file names or 调度器 in it", ("Launcher.exe" in body, "调度器" in body), (False, False))

    print("\n[the skip is the shift's MaaEnd result: on the ledger as a failed run]")
    rows = [r for r in e.state.read_ledger("2026-10-16") if r["script"] == "MaaEnd"]
    check("one MaaEnd row", len(rows), 1)
    check("…failed, at 09:34:05", (rows[0]["ok"], rows[0]["started"][:19]) if rows else None,
          (False, "2026-10-16T09:34:05"))

    def overdue_at(e):
        """One minute past the shift's overdue deadline, from the same source shutdown._shift_overdue
    uses (runwatch.planned_minutes + OVERRUN_SLACK_MIN). On the machine it was 12:08 (158 min
    planned); this fixture has no history, so planned is the default and the deadline later.
    A check before the deadline proves nothing: the overdue alarm cannot fire yet."""
        limit, _ = runwatch.planned_minutes(e, 9, 0, at(9, 0))
        return at(9, 0) + timedelta(minutes=limit + runwatch.OVERRUN_SLACK_MIN + 1)


    print("\n[10:34 (the hour backstop) and the overdue check (12:08 on the machine): nothing more for the same fault]")
    first = list(got)
    e._check_missed_runs(at(10, 34, 12))
    check("no 10:34 「缺项」 alarm: only the 09:34 one", alarms(e), first)
    shutdown._alarm_shift_overdue(e, overdue_at(e))
    check("no 「一直没出结果」 alarm past the overdue deadline", alarms(e), first)
    check("the 09:34 one was not empty", len(first), 1)
    check("no overdue wake-up left for 早班", shutdown.overdue_moments(e, at(9, 35)), [])

    print("\n[the shutdown gate: the shift is over at the skip, so the machine is not held on]")
    v = shutdown.decide(e, at(9, 35))
    check("not 「shift-running」 (还差 MaaEnd)", v.code != "shift-running", True)
    check("…the decision right after the shift says go", v.code, "go")

    print("\n[the interim / daily title is not 全绿]")
    # The same steps report._compose_daily runs before format_daily (no history log for the row).
    from ark_relay.core import collector
    from ark_relay.features.report import report
    entries = [collector.refresh_raw(r, HIST, None) for r in e.state.read_ledger("2026-10-16")]
    report._fill_single_run_sanity(entries)
    entries, _tests = core.split_test(entries, [])
    title2, body2 = core.format_daily("2026-10-16", entries, shifts=[("早班", "09:00"), ("晚班", "21:30")])
    check("title is not 全绿", "全绿" in title2, False)
    check("title says 终末地早班没跑成", "终末地早班没跑成" in title2, True)
    check("the row gives the reason", "开跑前检查没过：找不到终末地官方启动器" in body2, True)

    print("\n[a relay restarted on the same day re-reads app.log from the top: no second alarm]")
    e2 = build(state_dir=e.cfg.state_dir)
    e2._run_watch(at(9, 50))
    check("restarted relay: nothing pushed", alarms(e2), [])
    check("still one MaaEnd row", len([r for r in e2.state.read_ledger("2026-10-16") if r["script"] == "MaaEnd"]), 1)

    print("\n[the skip line lands ~100 ms after the queue moves on: one extra wake right after running stops]")
    e3 = build(lines=SKIP_AT)                          # the 09:34:04.988 poll: skip line not written yet
    e3._run_watch(at(9, 34, 4))
    check("nothing yet", alarms(e3), [])
    moments = runwatch.next_moments(e3, at(9, 34, 4), True)
    check("while running: the minute recheck", [m for m, _ in moments], [at(9, 35, 4)])
    moments = runwatch.next_moments(e3, at(9, 34, 7), False)
    check("running went true -> false: one wake within seconds",
          len(moments) == 1 and at(9, 34, 7) < moments[0][0] <= at(9, 34, 20), True)
    check("asked again before it: the same wake", runwatch.next_moments(e3, at(9, 34, 8), False), moments)
    after = moments[0][0] + timedelta(seconds=1) if moments else at(9, 35)
    check("after it: nothing", runwatch.next_moments(e3, after, False), [])
    with APPLOG.open("a", encoding="utf-8") as fh:
        fh.write("".join(ln + "\n" for ln in LINES[SKIP_AT:]))
    e3._run_watch(moments[0][0] if moments else at(9, 34, 17))
    check("that wake reads the skip and alarms", len(alarms(e3)), 1)

    print("\n[without a skip line, the 「缺项」 check wakes at due + partial_grace, not at the hour backstop]")
    e4 = build(lines=SKIP_AT)
    e4._run_watch(at(9, 34, 7))
    nd = e4.next_deadline(at(9, 34, 7))
    check("next wake is 10:15 (09:00 + 75)", nd and nd[0], at(10, 15))
    cap = []


    class _H(logging.Handler):
        def emit(self, rec):
            cap.append(rec)


    h = _H()
    missed.log.addHandler(h)
    try:
        e4._check_missed_runs(at(10, 15, 5))
    finally:
        missed.log.removeHandler(h)
    check("the 10:15 alarm went out", [t for t, _ in alarms(e4)], ["🔌 MaaEnd 没有运行（早班）"])
    check("its log line is marked as already in the group (no 🩺 copy)",
          [bool(getattr(r, errwatch.PUSHED, False)) for r in cap if r.levelno >= logging.WARNING], [True])
    check("no overdue wake-up left for 早班 (MaaEnd is already in the group)", shutdown.overdue_moments(e4, at(10, 16)), [])
    shutdown._alarm_shift_overdue(e4, overdue_at(e4))
    check("and past the overdue deadline it is not said again", [t for t, _ in alarms(e4)], ["🔌 MaaEnd 没有运行（早班）"])

    print("\n[the same run with OK-WW also still missing: the overdue alarm still names OK-WW, not MaaEnd]")
    e5 = build(lines=SKIP_AT)
    e5.state.ledger_path("2026-10-16").write_text("\n".join(json.dumps(
        {"run_id": r, "script": s, "user": u, "started": a.isoformat(), "finished": b.isoformat(), "ok": ok,
         "failed_tasks": [], "transitional": tr, "raw": {}}) for r, s, u, a, b, ok, tr in LEDGER[:1]) + "\n",
        encoding="utf-8")
    missed._settle(e5, "2026-10-16", "2026-10-16/早班/09:00/MaaEnd")
    shutdown._alarm_shift_overdue(e5, overdue_at(e5))
    over = [b for t, b in alarms(e5) if "一直没出结果" in t]
    check("one overdue alarm", len(over), 1)
    check("…it names OK-WW and not MaaEnd", (("OK-WW" in over[0]) or ("鸣潮" in over[0]), "MaaEnd" in over[0]) if over else None,
          (True, False))

    print("\n[the skip alarm fails to send: the machine is held on, as for any failed alarm, and it goes out later]")


    class Down(Notes):
        def __init__(self):
            super().__init__()
            self.up = False

        def send(self, title, body="", **kw):
            if not self.up:
                return ["wecom: down"]
            return super().send(title, body, **kw)


    e6 = build()
    e6.notifier = Down()
    e6._run_watch(at(9, 34, 7))
    check("nothing went out", alarms(e6), [])
    check("the skip waits to be sent again", len(e6._unsent_skips), 1)
    v6 = shutdown.decide(e6, at(9, 34, 8))
    check("the shutdown waits for it (not go)", v6.code, "pending")
    e6.notifier.up = True
    e6._run_watch(at(9, 35, 7))
    check("next tick: the alarm with the reason goes out",
          [("找不到终末地官方启动器" in b) for t, b in alarms(e6)], [True])
    check("nothing left to send", e6._unsent_skips, [])
    check("then the shutdown says go", shutdown.decide(e6, at(9, 35, 8)).code, "go")

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    _mc.CHECKS.update(_mc_real)
    sys.exit(1 if fails else 0)


def _part_config_warn_once():
    """Warnings from the config readers are said once per condition, not on every call.

errwatch pushes every WARNING to the group, and read_maaend / read_maa / the plan
run on every phone publish (50-80 a day on 10-10..10-12) and every engine tick;
relay.log 09-10 shows the same 「AutoCollectRoutes 没有中文名」 three times.
A condition that clears and comes back is said again.

    Formerly test_config_warn_once.py.
    """
    #!/usr/bin/env python3

    import json
    import logging
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from _tmp import tmpdir
    from ark_relay.core import mastercfg, mastercfg_maa, plan

    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    class Catch(logging.Handler):
        def __init__(self) -> None:
            super().__init__(logging.WARNING)
            self.msgs: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.msgs.append(record.getMessage())


    catch = Catch()
    for name in ("ark.mastercfg", "ark.plan"):
        logging.getLogger(name).addHandler(catch)


    def said(part: str) -> int:
        return sum(part in m for m in catch.msgs)


    root = tmpdir()
    automas = root / "automas"
    (automas / "data" / "sid" / "Default" / "ConfigFile").mkdir(parents=True)
    master = automas / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
    maaend = root / "maaend"
    (maaend / "tasks").mkdir(parents=True)
    (maaend / "interface.json").write_text('{"import": ["tasks/AutoCollect.json"]}', encoding="utf-8")
    (maaend / "tasks" / "AutoCollect.json").write_text(json.dumps({
        "task": [{"name": "AutoCollect", "label": "$task.AutoCollect.label", "option": ["AutoCollectMode"]}],
        "option": {"AutoCollectMode": {"type": "select", "label": "$opt.AutoCollectMode", "cases": []}}}),
        encoding="utf-8")

    print("[MaaEnd master copy missing, read twice]")
    mastercfg.read_maaend(automas, maaend)
    mastercfg.read_maaend(automas, maaend)
    require("「母本配置文件不在」 said once", said("母本配置文件不在") == 1, repr(catch.msgs))

    print("[master back, with an untranslated option and no language pack]")
    master.write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
        {"taskName": "AutoCollect", "enabled": True,
         "optionValues": {"AutoCollectMode": {"type": "select", "caseName": "Always"}}}]}]}), encoding="utf-8")
    for _ in range(3):
        mastercfg.read_maaend(automas, maaend)
    require("「没有中文名」 said once over three reads", said("没有中文名") == 1, repr(catch.msgs))
    require("「没有可选值」 said once over three reads", said("没有可选值") == 1, repr(catch.msgs))
    require("「中文语言包」 said once over four reads", said("中文语言包") == 1, repr(catch.msgs))

    print("[master gone again: the condition came back, so it is said again]")
    master.unlink()
    mastercfg.read_maaend(automas, maaend)
    require("「母本配置文件不在」 said a second time", said("母本配置文件不在") == 2, repr(catch.msgs))

    print("[MAA master copy missing, read twice]")
    catch.msgs.clear()
    mastercfg_maa.read_maa(automas)
    mastercfg_maa.read_maa(automas)
    require("MAA 「母本配置文件不在」 said once", said("母本配置文件不在") == 1, repr(catch.msgs))

    print("[AUTO-MAS QueueConfig.json broken, read on every tick]")
    cfg = root / "AUTO-MAS" / "config"
    cfg.mkdir(parents=True)
    (cfg / "QueueConfig.json").write_text("{broken", encoding="utf-8")
    for _ in range(3):
        plan.schedule(root / "AUTO-MAS")
    require("「读取 QueueConfig.json 失败」 said once", said("读取 QueueConfig.json 失败") == 1, repr(catch.msgs))

    print("[no AUTO-MAS config directory, plan built twice]")
    plan.next_plan(root / "nowhere")
    plan.next_plan(root / "nowhere")
    require("「找不到 AUTO-MAS 配置目录」 said once", said("找不到 AUTO-MAS 配置目录") == 1, repr(catch.msgs))

    print("[no app.asar, labels asked twice]")
    plan._asar_value_labels(root / "AUTO-MAS", root)
    plan._asar_value_labels(root / "AUTO-MAS", root)
    require("「找不到 app.asar」 said once", said("找不到 app.asar") == 1, repr(catch.msgs))

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)


def _part_config_writers():
    """The writers that touch production config, and the reader of the
sanity-booster step.

This is the 826 class of code: it edits the files the scripts actually run
from. The accident that day was a value written into production whose meaning
had been inferred rather than confirmed - it changed which stage was farmed and
burnt sanity potions. Nothing here had a test.

* `mastercfg.write_maa` may only ever accept the seven values MAA itself
  declares, must write **both** copies (the master and MAA's own, which the
  master overwrites at launch), and must read back what it wrote before
  reporting success. 「写完就说设好了」 is forbidden.
* `gameupdate.spmed_shape` reads the sanity-booster's confirm node. It no longer
  decides whether the task may run (it always runs); a shape other than the
  fixed one rings the group at boot. It looks at the shape, not at a version
  number: on 2026-09-03 the upstream fix was still unmerged.

    Formerly test_config_writers.py.
    """
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.core import mastercfg
    from _tmp import tmpdir

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
        if not ok:
            fails.append(label)


    def maa_tree(drones="Money"):
        """An AUTO-MAS data dir holding MAA's master config, plus a MAA dir."""
        root = tmpdir()
        master = root / "AUTO-MAS" / "data" / "abc123" / "Default" / "ConfigFile"
        master.mkdir(parents=True)
        doc = {"Current": "Default", "Configurations": {"Default": {"TaskQueue": [
            {"Type": "StartUp"},
            {"Type": "Infrast", "UsesOfDrones": drones},
            {"Type": "Award", "Award": True, "Mail": False, "FreeGacha": False, "Orundum": False,
             "Mining": False, "SpecialAccess": False},
        ]}}}
        (master / "gui.new.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        maa = root / "MAA" / "config"
        maa.mkdir(parents=True)
        (maa / "gui.new.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return root / "AUTO-MAS", root / "MAA"


    def drones_in(path):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return mastercfg._maa_infrast(doc)["UsesOfDrones"]


    print("[无人机用途：改一次，两份都写到了]")
    automas, maa = maa_tree("Money")
    ok, msg = mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "PureGold")
    check("成功", ok, True)
    check("母本写了", drones_in(automas / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json"),
          "PureGold")
    check("MAA 目录那份也写了", drones_in(maa / "config" / "gui.new.json"), "PureGold")
    check("报告写清前后", ("龙门币" in msg and "赤金" in msg), True)
    check("报告说了写了几份", "2 份" in msg, True)

    print("\n[本来就是这个值：照样算成功，但不许假装改过]")
    ok, msg = mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "PureGold")
    check("成功", ok, True)
    check("说的是「本来就用在」", "本来就用在" in msg, True)

    print("\n[不认识的取值必须当场拒绝——826 就是编了一个含义写进去]")
    ok, msg = mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "黄金")
    check("拒绝", ok, False)
    check("盘上没被改", drones_in(maa / "config" / "gui.new.json"), "PureGold")
    check("报告列出合法取值", "_NotUse" in msg, True)

    print("\n[没开放的路径一律拒绝，不许顺手写别的字段]")
    ok, msg = mastercfg.write_maa(automas, maa, "Infrast/Drones", "Money")
    check("拒绝", ok, False)
    check("说清只开放哪一项", "Infrast/UsesOfDrones" in msg, True)

    print("\n[母本里没有基建任务：拒绝，而不是凭空造一个]")
    automas2, maa2 = maa_tree()
    f = automas2 / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json"
    f.write_text(json.dumps({"Current": "Default",
                             "Configurations": {"Default": {"TaskQueue": [{"Type": "StartUp"}]}}}),
                 encoding="utf-8")
    ok, msg = mastercfg.write_maa(automas2, maa2, "Infrast/UsesOfDrones", "Money")
    check("拒绝", ok, False)
    check("说清找不到什么", "UsesOfDrones" in msg, True)

    print("\n[领取奖励的开关：邮件那项 09-14 发现一直是关的]")
    automas3, maa3 = maa_tree("Money")
    check("读出来是关", mastercfg.read_maa(automas3)["values"].get("Award/Mail"), False)
    ok, msg = mastercfg.write_maa(automas3, maa3, "Award/Mail", True)
    check("成功", ok, True)
    check("报告写清前后", "关 → 开" in msg and "邮件" in msg, True)
    for f in (automas3 / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json", maa3 / "config" / "gui.new.json"):
        check(f"{f.parent.parent.name} 那份写了", mastercfg._maa_award(json.loads(f.read_text(encoding="utf-8")))["Mail"], True)
    check("读回是开", mastercfg.read_maa(automas3)["values"].get("Award/Mail"), True)
    ok, msg = mastercfg.write_maa(automas3, maa3, "Award/Mail", True)
    check("本来就是开的", ok and "本来就是" in msg, True)
    ok, msg = mastercfg.write_maa(automas3, maa3, "Award/Mail", "yes")
    check("非布尔值拒绝", ok, False)
    ok, msg = mastercfg.write_maa(automas3, maa3, "Award/FreeGacha", True)
    check("免费单抽没开放，拒绝", ok, False)
    check("其他开关也在", set(k for k in mastercfg.read_maa(automas3)["values"] if k.startswith("Award/")),
          {"Award/Mail", "Award/Orundum", "Award/Mining", "Award/SpecialAccess"})

    print("\n[找不到母本时不许说成功]")
    ok, msg = mastercfg.write_maa(tmpdir(), None, "Infrast/UsesOfDrones", "Money")
    check("拒绝", ok, False)
    check("说清是找不到母本", "找不到" in msg, True)

    # ------------------------------------------------- MaaEnd：理智药那个确认节点长什么样

    def nodes(node):
        d = tmpdir()
        (d / "resource" / "pipeline").mkdir(parents=True)
        (d / "resource" / "pipeline" / "nodes.json").write_text(
            json.dumps({"AutoUseSpMedicationQuickUse": node} if node is not None else {},
                       ensure_ascii=False), encoding="utf-8")
        return d


    print("\n[理智药那个确认节点：修好了才认，光换版本号不算；认不出的每次开机报群，任务照开]")
    fixed = {"recognition": {"param": {"all_of": [{"recognition": "OCR", "expected": "确认"}]}}}
    check("修好了", gameupdate.spmed_shape(nodes(fixed)), "fixed")
    broken = {"recognition": {"param": {"all_of": [{"expected": "确认"}]}}}
    check("形状不对就是没修", gameupdate.spmed_shape(nodes(broken)), "broken")
    check("all_of 是空的：认不出", gameupdate.spmed_shape(
        nodes({"recognition": {"param": {"all_of": []}}})), "unknown")
    check("节点整个不在：改名或拿掉了", gameupdate.spmed_shape(nodes(None)), "missing")
    check("节点不是字典：认不出", gameupdate.spmed_shape(nodes("会开的")), "unknown")
    check("文件不存在：读不到", gameupdate.spmed_shape(tmpdir()), "unreadable")
    check("目录是 None：没东西可查", gameupdate.spmed_shape(None), "")

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_config_no_bot, _part_config_skip, _part_config_warn_once, _part_config_writers]))
