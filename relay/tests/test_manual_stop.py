"""A manual stop: the backfill, not self-healed.

One part per former file, each run on its own (tests/_parts.py): test_manual_stop_backfill.py, test_manual_stop_not_selfheal.py.
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


def _part_manual_stop_backfill():
    """Runs the red button cut short before the press was recorded get ⏹ at the next boot.

2026-09-30 09:46:28-09:47:22 (Beijing) the red button was pressed through a
one-off script, before commands.estop wrote estop-windows.json. The ledger
already held the OK-WW run it stopped (ok=True, which AUTO-MAS wrote as
Success!) and the MaaEnd run it stopped (ok=False), neither with
raw.manual_stop, so the evening report would show ✅ and ❌ for two runs nobody
let finish.

At boot, after the self-update, handle.backfill_manual_stops marks every ledger
line of today and yesterday that overlaps a press recorded in estop-windows.json,
and drops held alarms for those runs the way _handle does at record time. (The
09-30 window was shipped as a seed merged at boot until 10-03; removed 10-13.)
The report is rendered through report._compose_daily, the same function the
`python -m ark_relay report --again` command pushes.

    Formerly test_manual_stop_backfill.py.
    """
    import json
    import os
    import types
    from datetime import datetime


    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.phone import commands
    from ark_relay.features.alarm import handle
    from ark_relay.features.report import report
    handle._screenshot_to = lambda out: False   # the real one waits up to 10 s for a Windows screenshot file
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    # No network: the banner section and the report-writing model are stubbed, as in
    # test_report_due.py.
    report.plan = types.SimpleNamespace(next_plan=lambda d: "", activity_countdown=lambda d: "",
                                        schedule=lambda d: [])
    report.banners = types.SimpleNamespace(
        collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
        read_image=None, state_dir=None: ([], {}),
        image_reader=lambda state_dir: None,
        render=lambda rows, now, nxt, notes=None, trace=None, failed=None, leads=None: "",
        Trace=types.SimpleNamespace(new=lambda: None),
        save_trace=lambda state_dir, now, text, tr: None,
        update_history=lambda state_dir, now: [],
        opening_tomorrow=lambda now, nxt: [],
    )
    report.summary = types.SimpleNamespace(daily_report=lambda cfg, entries, plan="": "")


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return []

        def send_group(self, title, body):
            return []


    class Src:
        def fetch(self, seen):
            return []


    def at(d, hh, mm, ss=0):
        return datetime(2026, 9, d, hh, mm, ss, tzinfo=SERVER_TZ)


    def line(rid, script, user, s, f, ok, failed=None):
        return {"run_id": rid, "script": script, "user": user, "started": s.isoformat(),
                "finished": f.isoformat(), "ok": ok, "failed_tasks": failed or [],
                "duration_known": True, "transitional": False, "raw": {"tasks_done": ["日常"]} if ok else {}}


    OKWW = line("OK-WW-05-40-56", "OK-WW", "wuwa", at(30, 9, 38), at(30, 9, 46, 58), True)
    MAAEND = line("MaaEnd-05-46-45", "MaaEnd", "endfield", at(30, 9, 46, 58), at(30, 9, 47, 10), False,
                  ["据点交易"])
    MAA = line("MAA-09-00-00", "MAA", "ark", at(30, 9, 0), at(30, 9, 30), True)
    TORN = '{"run_id": "half'


    def build(windows=None):
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.history_dir = None
        cfg.automas_dir = None
        st = State(cfg.state_dir)
        p = st.ledger_path("2026-09-30")
        p.write_text("\n".join([json.dumps(MAA, ensure_ascii=False), json.dumps(OKWW, ensure_ascii=False),
                                TORN, json.dumps(MAAEND, ensure_ascii=False)]) + "\n", encoding="utf-8")
        if windows is not None:
            (Path(cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).write_text(json.dumps(windows), encoding="utf-8")
        e = eng_mod.Engine(cfg, source=Src(), state=st, notifier=Notes())
        e._scripts_running = lambda: False
        return e


    def stops(e, day="2026-09-30"):
        return {x["run_id"]: (x.get("raw") or {}).get("manual_stop") for x in e.state.read_ledger(day)}


    def kind_line(body, script):
        return next((ln for ln in body.splitlines() if f" {script}" in ln and ln[:1] in "✅❌⏹↻⚠"), "")


    EVENING = at(30, 21, 25)

    print("[改前的日报：两趟被停掉的显示成 ✅ / ❌]")
    e = build(windows=[])
    _, body0 = e._compose_daily("2026-09-30", e.state.read_ledger("2026-09-30"))
    check("OK-WW 原来是 ✅", kind_line(body0, "鸣潮")[:1], "✅")
    check("MaaEnd 原来是 ❌", kind_line(body0, "终末地")[:1], "❌")

    print("\n[窗口文件里有这次按下：两趟补记，窗口外的不动，第二次是空操作]")
    e = build(windows=[{"start": "2026-09-30T09:46:28+08:00", "end": "2026-09-30T09:47:22+08:00"}])
    n = handle.backfill_manual_stops(e, EVENING)
    got = stops(e)
    check("补了两趟", n, 2)
    check("OK-WW 记停一切", got.get("OK-WW-05-40-56"), "09:46 停一切")
    check("MaaEnd 记停一切", got.get("MaaEnd-05-46-45"), "09:46 停一切")
    check("窗口外的 MAA 不动", got.get("MAA-09-00-00"), None)
    raw_text = e.state.ledger_path("2026-09-30").read_text(encoding="utf-8")
    check("残行原样保留", TORN in raw_text.splitlines(), True)
    check("行数不变", len(raw_text.splitlines()), 4)
    before = raw_text
    check("再跑一次什么都不补", handle.backfill_manual_stops(e, EVENING), 0)
    check("文件逐字节不变", e.state.ledger_path("2026-09-30").read_text(encoding="utf-8"), before)

    print("\n[日报走 _compose_daily（report 命令同一个函数）：两趟都是 ⏹]")
    title, body = e._compose_daily("2026-09-30", e.state.read_ledger("2026-09-30"))
    check("OK-WW 那行是 ⏹", kind_line(body, "鸣潮")[:1], "⏹")
    check("MaaEnd 那行是 ⏹", kind_line(body, "终末地")[:1], "⏹")
    check("有被停一切停掉的备注", "被停一切中途停掉，不算成功也不算失败" in body, True)
    check("标题不算失败", "失败" in title, False)
    check("两趟都写「已停，未补」", body.count("已停，未补"), 2)

    print("\n[停掉之后同一脚本又跑过一趟：那趟停的不写「未补」]")
    later = line("OK-WW-10-30-00", "OK-WW", "wuwa", at(30, 10, 30), at(30, 10, 50), True)
    title, body = e._compose_daily("2026-09-30", e.state.read_ledger("2026-09-30") + [later])
    check("只剩 MaaEnd 那条写「已停，未补」", body.count("已停，未补"), 1)
    from ark_relay.core import ledger as _core
    check("共用判定：有 manual_stop 才算", [_core.manual_stop(x) for x in (
        {"raw": {"manual_stop": "09:46 停一切"}}, {"raw": {}}, {"raw": None}, {})], [True, False, False, False])

    # The 09-30 press, as estop-windows.json holds it.
    W0930 = [{"start": "2026-09-30T09:46:28+08:00", "end": "2026-09-30T09:47:22+08:00"}]

    print("\n[no press recorded: nothing is booked (the shipped seed went, audit 11 #7)]")
    # ESTOP_SEED / merge_estop_seed carried the 09-30 window for three days after
    # 2026-09-30 and did nothing after 10-03; they and their boot call are gone.
    e = build(windows=None)
    check("no window file: nothing booked", handle.backfill_manual_stops(e, EVENING), 0)
    check("and no window file written", (Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).exists(), False)
    check("the seed's names are gone", [n for n in ("ESTOP_SEED", "merge_estop_seed") if hasattr(commands, n)], [])

    print("\n[another press on record: the file is left as it is]")
    e = build(windows=[{"start": "2026-09-30T20:00:00+08:00", "end": "2026-09-30T20:01:00+08:00"}])
    handle.backfill_manual_stops(e, EVENING)
    w = json.loads((Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).read_text(encoding="utf-8"))
    check("only that press", [x.get("start")[11:16] for x in w], ["20:00"])

    print("\n[过了午夜（北京时间）：昨天的账本照样补]")
    e = build(windows=W0930)
    check("10-01 00:30 开机也补了两趟", handle.backfill_manual_stops(e, datetime(2026, 10, 1, 0, 30, tzinfo=SERVER_TZ)), 2)

    print("\n[压着的告警：被停掉的两趟相关的清掉，别的不动]")


    def rec_of(d, **over):
        x = dict(d, **over)
        return RunRecord(run_id=x["run_id"], script=x["script"], user=x["user"],
                         started=datetime.fromisoformat(x["started"]),
                         finished=datetime.fromisoformat(x["finished"]), ok=x["ok"],
                         failed_tasks=x["failed_tasks"], raw=dict(x["raw"]))


    e = build(windows=W0930)
    # 09:30 OK-WW failure moved to _recovered when the stopped OK-WW run read as a success.
    fail930 = rec_of(OKWW, run_id="OK-WW-05-21-00", started=at(30, 9, 21).isoformat(),
                     finished=at(30, 9, 30).isoformat(), ok=False, failed_tasks=["日常"], raw={})
    e._recovered[("OK-WW", "wuwa")] = fail930
    # The stopped MaaEnd run itself, held for the final alarm.
    e._pending[("MaaEnd", "endfield")] = rec_of(MAAEND)
    # Something unrelated that must stay.
    other = rec_of(MAA, run_id="MAA-08-00-00", ok=False, failed_tasks=["x"], raw={})
    e._pending[("MAA", "ark")] = other
    e._persist_pending()
    handle.backfill_manual_stops(e, EVENING)
    check("OK-WW 不算重试后成功", list(e._recovered), [])
    check("MaaEnd 不再等着重试", ("MaaEnd", "endfield") in e._pending, False)
    check("MAA 的照旧压着", list(e._pending), [("MAA", "ark")])
    # 2026-10-06: both failures are pushed now, not dropped (「只要是报错…都要发」).
    check("两条失败都进群", sorted(t for t, _ in e.notifier.sent), ["❌ MaaEnd 失败", "❌ OK-WW 失败"])
    check("都说明后面那趟是停一切停掉的", all("停一切停掉" in b for _, b in e.notifier.sent), True)
    disk = State(e.cfg.state_dir).load_pending()
    check("磁盘上也清掉了（重启读回一致）",
          (len(disk.get("pending") or []), len(disk.get("recovered") or [])), (1, 0))

    print("\n[被停掉那趟之后的新失败：不清]")
    e = build(windows=W0930)
    late = rec_of(MAAEND, run_id="MaaEnd-10-30-00", started=at(30, 10, 30).isoformat(),
                  finished=at(30, 10, 50).isoformat())
    e._pending[("MaaEnd", "endfield")] = late
    handle.backfill_manual_stops(e, EVENING)
    check("10:30 的失败还压着", ("MaaEnd", "endfield") in e._pending, True)

    print("\n[自愈之后又有真成功：那次自愈是真的，不清]")
    e = build(windows=W0930)
    real_ok = line("OK-WW-09-35-00", "OK-WW", "wuwa", at(30, 9, 32), at(30, 9, 36), True)
    p = e.state.ledger_path("2026-09-30")
    p.write_text(p.read_text(encoding="utf-8") + json.dumps(real_ok, ensure_ascii=False) + "\n", encoding="utf-8")
    e._recovered[("OK-WW", "wuwa")] = fail930
    handle.backfill_manual_stops(e, EVENING)
    check("09:36 真成功治好的自愈通知还在", list(e._recovered), [("OK-WW", "wuwa")])

    print("\n[开机阶段：出错不抛、写一行日志]")
    sys.modules.setdefault("win32event", types.ModuleType("win32event"))
    import boot_stages


    class Log:
        def __init__(self):
            self.lines = []

        def info(self, *a, **k):
            self.lines.append(a)

        def exception(self, *a, **k):
            self.lines.append(("EXC",) + a)


    lg = Log()
    e = build(windows=W0930)
    # The stage passes no clock, and backfill looks at yesterday and today only: pin "now" to the
    # evening of the fixture day, or this check starts failing two days after the fixture (2026-10-02).
    _real_backfill = handle.backfill_manual_stops
    handle.backfill_manual_stops = lambda eng, now=None: _real_backfill(eng, now or EVENING)
    try:
        boot_stages._stage_backfill_manual_stops(e, lg)
    finally:
        handle.backfill_manual_stops = _real_backfill
    check("阶段跑完两趟有停一切", sorted(v for v in stops(e).values() if v), ["09:46 停一切", "09:46 停一切"])
    real = handle.backfill_manual_stops
    handle.backfill_manual_stops = lambda *a, **k: 1 / 0
    try:
        boot_stages._stage_backfill_manual_stops(e, lg)
        check("出错不抛", True, True)
        check("记了异常", any(x and x[0] == "EXC" for x in lg.lines), True)
    finally:
        handle.backfill_manual_stops = real


def _part_manual_stop_not_selfheal():
    """A run the red button (停一切) cut short is a manual stop, not the retry that healed the day.

2026-09-30 morning: OK-WW failed at 09:19 and 09:30 (both held in _pending). At
09:46:58 the phone's red button stopped the third attempt; AUTO-MAS recorded that
stopped run as Success!, and the relay took it as 「重试后成功」 - a self-heal
notice for a run nobody let finish, and a green row in the daily report.

commands.estop now writes when it was pressed (estop-windows.json); handle._handle
marks any run overlapping that window raw.manual_stop, books it, drops the held
failures' final alarm (they stay in the ledger) and does nothing else. The daily
report shows it as ⏹, never ✅, and never as the later run that 「做成了」 the
earlier failures.

    Formerly test_manual_stop_not_selfheal.py.
    """
    import json
    import os
    from datetime import datetime


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

    from ark_relay.features.makeup import collect_retry
    from ark_relay.features.phone import commands
    from ark_relay.features.alarm import handle
    from ark_relay.core import ledger as core
    handle._screenshot_to = lambda out: False   # the real one waits up to 10 s for a Windows screenshot file
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return False


    class Src:
        def fetch(self, seen):
            return []


    def at(hh, mm, ss=0):
        return datetime(2026, 9, 30, hh, mm, ss, tzinfo=SERVER_TZ)


    def rec(run_id, started, finished, script="OK-WW", user="wuwa", ok=False):
        return RunRecord(run_id=run_id, script=script, user=user, started=started, finished=finished,
                         ok=ok, failed_tasks=[] if ok else ["任务执行：卡在对话框"],
                         raw={"tasks_done": ["日常"]} if ok else {})


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._verify_outcome = lambda r: None
        return e


    def press(e, start, end):
        (Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).write_text(
            json.dumps([{"start": start.isoformat(timespec="seconds"),
                         "end": end.isoformat(timespec="seconds")}]), encoding="utf-8")


    gates = []
    handle._weekly_gates = lambda eng, r: gates.append(r.run_id)


    def morning(e):
        """The two genuine failures of 09-30, booked and held the way _hold_for_retry leaves them."""
        for rid, s, f in (("2026-09-30/wuwa/09-19-00", at(9, 12), at(9, 19)),
                          ("2026-09-30/wuwa/09-30-00", at(9, 21), at(9, 30))):
            r = rec(rid, s, f)
            e.state.append_ledger(r)
            e._pending[("OK-WW", "wuwa")] = r
        e._persist_pending()


    print("[09-30 原样：两次失败在等，第三趟被停一切停掉、AUTO-MAS 记成功]")
    e = build()
    morning(e)
    press(e, at(9, 46, 40), at(9, 47, 30))
    stopped = rec("2026-09-30/wuwa/09-47-05", at(9, 38), at(9, 47, 5), ok=True)
    e._handle(stopped)
    check("不进自愈", dict(e._recovered), {})
    check("前面的失败不再等着重试", dict(e._pending), {})
    check("重启读回来也是空的", dict(State(e.cfg.state_dir).load_pending() or {}).get("pending") or [], [])
    check("没走成功那条路（周常门没碰）", gates, [])
    # 2026-10-06: the failure before the stop is pushed, not dropped (「只要是报错…都要发」).
    check("停一切之前那次失败进群一条", [t for t, _ in e.notifier.sent], ["❌ OK-WW 失败"])
    check("说明后面那趟是停一切停掉的", all("停一切停掉" in b for _, b in e.notifier.sent), True)
    ledger = e.state.read_ledger("2026-09-30")
    row = [x for x in ledger if x["run_id"] == stopped.run_id]
    check("账本记了这一趟", len(row), 1)
    check("账本那行记着是停一切停掉的", (row[0]["raw"] or {}).get("manual_stop"), "09:46 停一切")
    check("前两次失败还在账本里", sum(1 for x in ledger if not x["ok"]), 2)

    print("\n[被停掉的那趟 AUTO-MAS 记成失败：也不当新失败压着等推]")
    e = build()
    press(e, at(9, 46, 40), at(9, 47, 30))
    e._handle(rec("2026-09-30/endfield/09-47-10", at(9, 47, 0), at(9, 47, 12),
                  script="MaaEnd", user="endfield"))
    check("没进待推", dict(e._pending), {})
    check("AUTO-MAS 记的失败照报一条（2026-10-06）", [t for t, _ in e.notifier.sent], ["❌ MaaEnd 失败"])
    check("说明是停一切停掉的", all("停一切停掉" in b for _, b in e.notifier.sent), True)

    print("\n[MaaEnd 被停掉：母本路线照样改回]")
    restored = []
    real_restore = collect_retry.restore_master
    collect_retry.restore_master = lambda cfg: restored.append(1) or ""
    e = build()
    press(e, at(9, 46, 40), at(9, 47, 30))
    e._handle(rec("2026-09-30/endfield/09-47-11", at(9, 47, 0), at(9, 47, 12),
                  script="MaaEnd", user="endfield", ok=True))
    check("restore_master 跑了", restored, [1])
    collect_retry.restore_master = real_restore

    print("\n[回归：窗口外的成功照旧算重试后成功（自愈）]")
    gates.clear()
    e = build()
    morning(e)
    press(e, at(8, 0), at(8, 1))
    ok_later = rec("2026-09-30/wuwa/09-47-05", at(9, 38), at(9, 47, 5), ok=True)
    e._handle(ok_later)
    check("进了自愈", list(e._recovered), [("OK-WW", "wuwa")])
    check("走了成功那条路", gates, [ok_later.run_id])
    row = [x for x in e.state.read_ledger("2026-09-30") if x["run_id"] == ok_later.run_id]
    check("账本那行没有手动停止记号", (row[0]["raw"] or {}).get("manual_stop"), None)

    print("\n[没有按过红按钮（没有文件）：照旧]")
    e = build()
    morning(e)
    e._handle(rec("2026-09-30/wuwa/09-47-05", at(9, 38), at(9, 47, 5), ok=True))
    check("进了自愈", list(e._recovered), [("OK-WW", "wuwa")])

    print("\n[日报：停掉的那趟是 ⏹ 不是 ✅，标题不说重试后成功]")


    def entry(rid, s, f, ok, raw=None, failed=None):
        return {"run_id": rid, "script": "OK-WW", "user": "wuwa",
                "started": s.isoformat(), "finished": f.isoformat(), "ok": ok,
                "failed_tasks": failed or [], "duration_known": True, "transitional": False,
                "raw": raw or {}}


    fail1 = entry("r1", at(9, 12), at(9, 19), False, failed=["日常"])
    fail2 = entry("r2", at(9, 21), at(9, 30), False, failed=["日常"])
    manual = entry("r3", at(9, 38), at(9, 47, 5), True,
                   raw={"manual_stop": "09:46 停一切", "tasks_done": ["日常"]})
    entries = [fail1, fail2, manual]
    check("episode_kinds 把它记成 manual", core.episode_kinds(entries).get("r3"), "manual")
    check("retried_notes 不把它当后来做成了", core.retried_notes(entries), {})
    title, body = core.format_daily("2026-09-30", entries)
    row3 = [ln for ln in body.splitlines() if "09:38" in ln]
    check("那一行的图标是 ⏹", bool(row3) and row3[0].startswith("⏹"), True)
    check("那一行不是 ✅", bool(row3) and row3[0].startswith("✅"), False)
    check("有备注说明被停一切停掉", "被停一切中途停掉，不算成功也不算失败" in body, True)
    check("标题不含「重试后成功」", "重试后成功" in title, False)
    # Since 2026-10-11 (验收) two bare failures in a row are one line and one title item.
    check("前两次仍按失败算（合成一行：连试 2 次没跑成）", ("鸣潮没跑成" in title, "连试 2 次没跑成" in body), (True, True))

    title, body = core.format_daily("2026-09-30", [manual])
    check("只有停掉的那趟：标题说有一趟被手动停止", title.endswith("其余全绿 ✅（有一趟被手动停止）"), True)

    ok_run = entry("r4", at(10, 0), at(10, 20), True, raw={"tasks_done": ["日常"]})
    retried = [fail1, ok_run, dict(manual, run_id="r5", started=at(11, 0).isoformat())]
    title, _ = core.format_daily("2026-09-30", retried)
    check("手动停止排在重试后成功之前", title.endswith("其余全绿 ✅（有一趟被手动停止）"), True)

    print("\n[记分牌不算停掉的那趟]")
    from ark_relay.features.report import scoreboard
    calls = []
    real_record = scoreboard.record
    scoreboard.record = lambda *a, **k: calls.append(a)
    st = State(tmpdir())
    st.append_ledger(rec("x/1", at(9, 38), at(9, 47), ok=True))
    m = rec("x/2", at(9, 38), at(9, 47), ok=True)
    m.raw["manual_stop"] = "09:46 停一切"
    st.append_ledger(m)
    check("只记了正常那趟", len(calls), 1)
    scoreboard.record = real_record


if __name__ == "__main__":
    sys.exit(run_parts([_part_manual_stop_backfill, _part_manual_stop_not_selfheal]))
