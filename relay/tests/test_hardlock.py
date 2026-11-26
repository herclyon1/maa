"""Hard lock (features/hardlock.py): what it stops, how a locked boot powers off, and that only
a release passing both of the user's unlock steps lifts it.

The user, 2026-11-26 ~10:50 (Tokyo): 「所有目前东西必须标记为不可用状态加上硬锁，什么时候根治完什么时候解除状态」;
10:54: 「所有东西必须挂上不可用的状态，必须逐个把出现过的问题根治后解除。」
"""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


def _good_release(H):
    return {"problems": [{"ledger_id": x, "problem": "p", "fix": "f", "test": "t", "evidence": "/e", "rc": 0}
                         for x in H.LEDGER], "unresolved": 0,
            "confirmed_root_cured": True, "fixed_by": ["fixer-1"], "main_sessions": ["main-1"],
            "verifier": {"agent_id": "verifier-9", "question": H.QUESTION, "verdict": H.VERDICT, "transcript": "/t"}}


def _part_lock_state():
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import hardlock as H

    import os
    d0 = tmpdir()
    (d0 / H.LOCK_FILE).write_text(json.dumps({"locked_at": "x"}), encoding="utf-8")
    old_env = os.environ.get("ARK_STATE_DIR")
    os.environ["ARK_STATE_DIR"] = str(d0)
    try:
        check("caller passes no state dir: still finds the relay's own (locked)", (H.active(""), H.active(None)), (True, True))
    finally:
        if old_env is None:
            os.environ.pop("ARK_STATE_DIR", None)
        else:
            os.environ["ARK_STATE_DIR"] = old_env
    d = tmpdir()
    check("no file, never locked: unlocked", H.active(d), False)
    (d / H.LOCK_FILE).write_text(json.dumps({"locked_at": "x"}), encoding="utf-8")
    check("lock file: locked", H.active(d), True)
    (d / H.LOCK_FILE).unlink()
    check("file deleted after it was seen: still locked (sticky)", H.active(d), True)
    (d / H.LOCK_FILE).write_text("{not json", encoding="utf-8")
    check("unreadable file: locked", H.active(d), True)

    rel = _good_release(H)
    check("a release passing both steps", H.released_ok(rel), True)
    check("a negated phrase is not pushing work (不要用户动手、禁止让用户点)",
          H.released_ok(dict(rel, note="不要用户动手；禁止让用户点按钮")), True)
    check("a problem field may quote the ledger (C-02)",
          H.released_ok(dict(rel, problems=[dict(rel["problems"][0], problem="习惯性「要用户 xxx」/ 逐项点头")] + rel["problems"][1:])), True)
    for label, bad in (
            ("no problems listed", dict(rel, problems=[])),
            ("a test not RC=0", dict(rel, problems=[dict(rel["problems"][0], rc=1)])),
            ("a problem left open", dict(rel, unresolved=1)),
            ("not confirmed", dict(rel, confirmed_root_cured=False)),
            ("verifier is the fixer", dict(rel, fixed_by=["verifier-9"])),
            ("another question", dict(rel, verifier=dict(rel["verifier"], question="修好了吗"))),
            ("another verdict", dict(rel, verifier=dict(rel["verifier"], verdict="差不多"))),
            ("no verifier", {k: v for k, v in rel.items() if k != "verifier"}),
            ("a ledger item missing", dict(rel, problems=rel["problems"][1:])),
            ("rc False passes as 0", dict(rel, problems=[dict(rel["problems"][0], rc=False)] + rel["problems"][1:])),
            ("unresolved False", dict(rel, unresolved=False)),
            ("nobody fixed it", dict(rel, fixed_by=[])),
            ("verifier is the main session", dict(rel, main_sessions=["verifier-9"])),
            ("pushes work to the user", dict(rel, note="最后请用户确认")),
            ("needs the user's own say-so", dict(rel, note="再有你本人放行才解锁")),
            ("no evidence", dict(rel, problems=[dict(rel["problems"][0], evidence="")] + rel["problems"][1:]))):
        check(f"release refused: {label}", H.released_ok(bad), False)
    (d / H.LOCK_FILE).write_text(json.dumps({"release": dict(rel, unresolved=2)}), encoding="utf-8")
    check("file with a bad release: still locked", H.active(d), True)
    (d / H.LOCK_FILE).write_text(json.dumps({"release": rel}), encoding="utf-8")
    check("file with a good release: unlocked", H.active(d), False)
    (d / H.LOCK_FILE).unlink()
    check("released, then the file removed: unlocked (the sticky mark went with the release)",
          H.active(d), False)


def _part_scheduled_boot():
    from datetime import datetime
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import hardlock as H

    at = lambda hm: datetime.strptime(f"2026-11-26 {hm}", "%Y-%m-%d %H:%M").replace(tzinfo=SERVER_TZ)  # noqa: E731
    times = ("08:40", "21:20")
    check("08:45 (the plug's boot) is scheduled", H.scheduled_boot(at("08:45"), times), True)
    check("21:21 (the RTC alarm) is scheduled", H.scheduled_boot(at("21:21"), times), True)
    check("14:00 is a boot by hand", H.scheduled_boot(at("14:00"), times), False)
    check("22:30 is a boot by hand", H.scheduled_boot(at("22:30"), times), False)


def _part_locked_power_off():
    import json
    import types
    from datetime import datetime, timedelta
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import hardlock as H, modes, shutdown

    d = tmpdir()
    (d / H.LOCK_FILE).write_text(json.dumps({"locked_at": "x"}), encoding="utf-8")
    now = datetime(2026, 11, 26, 21, 12, tzinfo=SERVER_TZ)

    def eng(booted, running=False, up_s=3600):
        return types.SimpleNamespace(
            cfg=types.SimpleNamespace(shutdown_after_run=True, shutdown_min_uptime=300, state_dir=d),
            state=types.SimpleNamespace(dir=d), _shutdown_issued=False,
            _boot_time=lambda _now: booted, _started_at=now - timedelta(seconds=up_s),
            _scripts_running=lambda: running)

    morning = datetime(2026, 11, 26, 8, 45, 12, tzinfo=SERVER_TZ)
    v = shutdown.decide(eng(morning), now)
    check("locked, scheduled boot, idle: powers off", (v.go, v.code), (True, "go"))
    v = shutdown.decide(eng(morning, running=True), now)
    check("locked, a game still running: stays on", (v.go, v.code), (False, "running"))
    v = shutdown.decide(eng(datetime(2026, 11, 26, 14, 0, tzinfo=SERVER_TZ)), now)
    check("locked, boot by hand: stays on", (v.go, v.code), (False, "hardlock-hold"))
    v = shutdown.decide(eng(morning, up_s=60), now)
    check("locked, relay up a minute: waits the uptime floor", (v.go, v.code), (False, "uptime"))
    v = shutdown.decide(eng(None), now)
    check("locked, boot time unreadable: stays on", (v.go, v.code), (False, "hardlock-hold"))
    store = modes._store(d)
    store.set("modes", "debug_until", "2026-11-26 21:30")
    v = shutdown.decide(eng(morning), now)
    check("locked, debug mode holding: stays on until it ends", (v.go, v.code), (False, "hardlock-hold"))
    store.set("modes", "debug_until", "2026-11-26 21:10")
    v = shutdown.decide(eng(morning), now)
    check("locked, debug mode ended 21:10: powers off at 21:12", (v.go, v.code), (True, "go"))
    # A debug mode ordered within 150 minutes of a power-on runs over the next cycle (modes.set_debug):
    # one ordered at 06:30 holds to 21:10, past the 08:40 mains cut. Locked, it does not hold then.
    store.set("modes", "debug_until", "2026-11-27 21:10")
    m27 = datetime(2026, 11, 27, 8, 45, 12, tzinfo=SERVER_TZ) - timedelta(days=1)
    for hm, want in (("08:20", (False, "hardlock-hold")), ("08:26", (True, "go-cut")), ("08:39", (True, "go-cut")),
                     ("08:41", (False, "hardlock-hold"))):
        t = datetime(2026, 11, 27, int(hm[:2]), int(hm[3:]), tzinfo=SERVER_TZ)
        e = eng(m27)
        e._started_at = t - timedelta(hours=2)
        v = shutdown.decide(e, t)
        check(f"locked, debug held over 08:40, at {hm}", (v.go, v.code), want)


def _part_orders_refused():
    import json
    import os
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import commands, hardlock as H, queues

    d = tmpdir()
    (d / H.LOCK_FILE).write_text(json.dumps({"locked_at": "x"}), encoding="utf-8")
    old = os.environ.get("ARK_STATE_DIR")
    os.environ["ARK_STATE_DIR"] = str(d)
    called = []
    real_mas = commands._mas
    commands._mas = lambda *a, **k: called.append(a) or {"status": "success", "data": {}}
    try:
        for cmd in ({"action": "run_now", "queue": "早班", "confirmed": True},
                    {"action": "set_stage", "value": "1-7", "confirmed": True},
                    {"action": "skip_shutdown", "confirmed": True}):
            ok, msg = commands.apply_command(cmd)
            check(f"locked: {cmd['action']} refused", (ok, "硬锁中" in msg), (False, True))
        ok, msg = commands.run_script("MaaEnd")
        check("locked: run_script refused", (ok, "硬锁中" in msg), (False, True))
        ok, msg = commands._run_now("晚班")
        check("locked: _run_now refused", (ok, "硬锁中" in msg), (False, True))
        check("locked: AUTO-MAS dispatch never called", called, [])
        ok, msg = queues.apply(d, "晚班", enabled=True, state_dir=d)
        check("locked: turning a queue timer back on refused", (ok, "硬锁中" in msg), (False, True))
        check("debug mode is still taken while locked", "debug_mode" in H.ORDERS_WHILE_LOCKED, True)
    finally:
        commands._mas = real_mas
        if old is None:
            os.environ.pop("ARK_STATE_DIR", None)
        else:
            os.environ["ARK_STATE_DIR"] = old


def _part_engine_steps_named():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import engine
    src = (Path(__file__).resolve().parents[1] / "ark_relay" / "core" / "engine.py").read_text(encoding="utf-8")
    for name in sorted(engine.LOCKED_STEPS):
        check(f"locked step 「{name}」 is a step of the tick", f'("{name}", self.' in src, True)


def _part_selfcheck_while_locked():
    import json
    import logging
    import os
    import types
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features import commands, hardlock as H, selfcheck as SC

    check("MAS_CONTRACT_CHECK is NOT exempt under hardlock",
          texts.MAS_CONTRACT_CHECK in SC.LOCK_NOT_JUDGED, False)
    check("queue timer check stays exempt under hardlock",
          "队列的排期读得到、至少一条开着定时" in SC.LOCK_NOT_JUDGED, True)

    d = tmpdir()
    (d / H.LOCK_FILE).write_text(json.dumps({"locked_at": "x"}), encoding="utf-8")
    fake_ok_contract = [
        SC.Check("队列的排期读得到、至少一条开着定时", False, "没有一条开着定时的队列"),
        SC.Check(texts.MAS_CONTRACT_CHECK, True, ""),
        SC.Check("状态目录能写", True, ""),
    ]
    real_run = SC.run
    SC.run = lambda cfg, **k: list(fake_ok_contract)
    sent = []
    notifier = types.SimpleNamespace(send=lambda *a, **k: sent.append(a) or [], channels=[])
    lines = []

    class H2(logging.Handler):
        def emit(self, r):
            lines.append(r.getMessage())
    lg = logging.getLogger("ark.test_hardlock")
    lg.addHandler(H2())
    lg.setLevel(logging.INFO)
    try:
        got = SC.report(types.SimpleNamespace(state_dir=d), notifier, log_=lg)
    finally:
        SC.run = real_run
    check("locked: only the queue-timer line is skipped when contract passes", [c.ok for c in got], [True, True, True])
    check("locked: what the queue-timer check found stays on the line", "没有一条开着定时的队列" in got[0].name, True)
    check("locked: no self-check alarm pushed when only queue timer is off", sent, [])
    check("locked: the all-pass line the deploy watch waits for", any("项全部成立" in ln for ln in lines), True)

    # Read-only MAS_CONTRACT_CHECK must STILL fail with ✗ and alarm while hard-locked.
    fake_bad_contract = [
        SC.Check("队列的排期读得到、至少一条开着定时", False, "没有一条开着定时的队列"),
        SC.Check(texts.MAS_CONTRACT_CHECK, False, "终末地的理智用途和基质设置少字段"),
        SC.Check("状态目录能写", True, ""),
    ]
    sent.clear()
    lines.clear()
    SC.run = lambda cfg, **k: list(fake_bad_contract)
    try:
        got = SC.report(types.SimpleNamespace(state_dir=d), notifier, log_=lg)
    finally:
        SC.run = real_run
    check("locked: MAS_CONTRACT_CHECK failure is still judged False (no fake green)",
          [c.ok for c in got], [True, False, True])
    check("locked: MAS_CONTRACT_CHECK failure logs ✗",
          any(f"开机自检 ✗ {texts.MAS_CONTRACT_CHECK}" in ln for ln in lines), True)
    check("locked: MAS_CONTRACT_CHECK failure pushes SELFCHECK_FAILED alarm",
          (len(sent), sent[0][0] if sent else ""), (1, texts.SELFCHECK_FAILED))

    # End-to-end: real selfcheck.report() under hardlock against a v5.8 automas_dir missing IfAutoEssence.
    am = tmpdir("locked-bad-contract-")
    (am / "config").mkdir()
    (am / "log").mkdir()
    (am / "config" / "scripts.yaml").write_text(
        "order:\n  - uid: s-end\n    type: MaaEndConfig\n"
        "data:\n  s-end:\n    Info:\n      Name: MaaEnd\n      Path: D:\\ark\\maaend\n"
        "    Game:\n      WaitTime: 60\n      Path: D:\\g\\Endfield.exe\n"
        "      LaunchMode: Launcher\n      LauncherPath: D:\\g\\Launcher.exe\n"
        "      ControllerType: Win32\n      SetResolution: false\n      CloseOnFinish: true\n"
        "      RestoreDisplayType: Window\n      RestoreResolution: Off\n"
        "    Update:\n      TakeoverEnabled: true\n      Channel: beta\n"
        "    UserData:\n      order:\n        - uid: u-end\n          type: MaaEndUserConfig\n"
        "      data:\n        u-end:\n          Info:\n            Name: ef\n"
        "          Task:\n            IfProtocolSpace: false\n"
        "            IfAutoUseSpMedication: true\n"
        "            SanityTaskType: OperatorProgression\n"
        "            AutoEssenceSpecifiedLocation: VFTheHub\n",
        encoding="utf-8",
    )
    (am / "config" / "queues.yaml").write_text("order: []\ndata: {}\n", encoding="utf-8")
    (am / "config" / "plans.yaml").write_text("order: []\ndata: {}\n", encoding="utf-8")
    saved_log = os.environ.get("ARK_LOG_FILE")
    os.environ["ARK_LOG_FILE"] = str(am / "log" / "relay.log")
    orig_mas = commands._mas
    orig_live_ver = SC._live_automas_version
    orig_run = SC.run
    sent.clear()
    lines.clear()
    try:
        commands._mas = lambda *a, **k: {"data": {}}
        SC._live_automas_version = lambda: "v5.8.0"
        SC.run = lambda cfg, **k: orig_run(
            cfg,
            procs=lambda: [(1, r"D:\ark\automas\repo\main.py")],
            mas_up=lambda: True,
            schedule=lambda: [],
            channels=lambda: ["群"],
            run_ok=lambda cmd: (True, ""),
            has_module=lambda m: True,
            virt=lambda: "VBS=0 HV=False",
        )
        got_e2e = SC.report(
            types.SimpleNamespace(automas_dir=str(am), state_dir=d, history_dir=str(am),
                                  phone_topic="t", phone_pin="1234"),
            notifier, log_=lg,
        )
    finally:
        SC.run = orig_run
        commands._mas = orig_mas
        SC._live_automas_version = orig_live_ver
        if saved_log is None:
            os.environ.pop("ARK_LOG_FILE", None)
        else:
            os.environ["ARK_LOG_FILE"] = saved_log
    c_map = {c.name: c for c in got_e2e}
    check("locked e2e: missing IfAutoEssence reports MAS_CONTRACT_CHECK as False (✗)",
          (c_map[texts.MAS_CONTRACT_CHECK].ok, "终末地的理智用途和基质设置" in c_map[texts.MAS_CONTRACT_CHECK].detail),
          (False, True))
    check("locked e2e: queue timer off stays skipped (✓)",
          any(c.name.startswith("队列的排期读得到、至少一条开着定时（硬锁中不判") and c.ok for c in got_e2e), True)
    check("locked e2e: pushes SELFCHECK_FAILED alarm for the broken contract",
          (len(sent), sent[0][0] if sent else ""), (1, texts.SELFCHECK_FAILED))

    other = [SC.Check("调度程序有应答", False, "没应答")]
    SC.run = lambda cfg, **k: list(other)
    try:
        got = SC.report(types.SimpleNamespace(state_dir=d), notifier, log_=lg)
    finally:
        SC.run = real_run
    check("locked: any other failure is still a failure", [c.ok for c in got], [False])


def _part_timers_off():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import hardlock as H

    q = {"a": {"Info": {"Name": "早班", "TimeEnabled": True, "StartUpMode": "Never"}},
         "b": {"Info": {"Name": "晚班", "TimeEnabled": False, "StartUpMode": "Always"}},
         "c": {"Info": {"Name": "备用", "TimeEnabled": False, "StartUpMode": "Never"}}}
    calls = []

    def mas(path, body=None):
        calls.append((path, body))
        return {"data": q} if path == "/api/queue/get" else {"status": "success"}
    got = H.timers_off(mas, force=True)
    check("turned back off: the timer and the start-up run", got, ["早班", "晚班"])
    check("writes only what is on", [c for c in calls if c[0] == "/api/queue/update"],
          [("/api/queue/update", {"queueId": "a", "data": {"Info": {"TimeEnabled": False}}}),
           ("/api/queue/update", {"queueId": "b", "data": {"Info": {"StartUpMode": "Never"}}})])
    calls.clear()
    check("again within a minute: not asked", (H.timers_off(mas), calls), ([], []))


def _part_wakes_every_minute():
    import json
    import types
    from datetime import datetime, timedelta
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import engine as E
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import hardlock as H

    d = tmpdir()
    (d / H.LOCK_FILE).write_text(json.dumps({"locked_at": "x"}), encoding="utf-8")
    fake = types.SimpleNamespace(_shutdown_issued=False, cfg=types.SimpleNamespace(state_dir=d, automas_dir=None))
    now = datetime(2026, 11, 26, 12, 0, tzinfo=SERVER_TZ)
    try:
        got = E.Engine.next_deadline(fake, now)
    except AttributeError:
        got = None      # the fake lacks what later candidates need; the lock's own wake is asserted below
    src = (Path(__file__).resolve().parents[1] / "ark_relay" / "core" / "engine.py").read_text(encoding="utf-8")
    check("locked: next_deadline adds a wake a minute out",
          "now + timedelta(seconds=hardlock.TIMERS_EVERY_S)" in src and H.TIMERS_EVERY_S == 60, True)
    if got is not None:
        check("locked: the earliest wake is within a minute", got[0] - now <= timedelta(seconds=60), True)


def _part_wechat_push_locked():
    import json
    import types
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import notify as N
    from ark_relay.features import hardlock as H

    d = tmpdir()
    cfg = types.SimpleNamespace(state_dir=d)
    n = N.Notifier.__new__(N.Notifier)
    n._state_dir = d
    n._last = __import__("threading").local()
    sent = []
    fake = types.SimpleNamespace(enabled=True, send_text=lambda *a: sent.append(a), send_image=lambda *a: sent.append(a))
    n.wecom = n.wecom_bot = n.serverchan = fake
    n._cfg = cfg
    check("no wechat lock file: not locked", H.active(d, "wechat"), False)
    (d / "HARDLOCK_WECHAT.json").write_text(json.dumps({"locked_at": "x"}), encoding="utf-8")
    check("wechat lock file: locked", H.active(d, "wechat"), True)
    check("the relay lock is a separate one", H.active(d, "relay"), False)
    check("locked: send() reaches no WeChat channel, caller told handled",
          (n.send("❌ 测试报警", "x", alert=True), n.send_group("测试", "x"), n.send_group_image(d / "a.png"), sent),
          ([], [], [], []))
    (d / "HARDLOCK_WECHAT.json").unlink()
    check("file deleted: still locked (sticky)", H.active(d, "wechat"), True)
    rel = _good_release(H)
    check("a relay release does not open the WeChat lock (W-01..W-03 missing)", H.released_ok(rel, "wechat"), False)
    w = dict(rel, problems=rel["problems"] + [dict(rel["problems"][0], ledger_id=x) for x in ("W-01", "W-02", "W-03")])
    (d / "HARDLOCK_WECHAT.json").write_text(json.dumps({"release": w}, ensure_ascii=False), encoding="utf-8")
    check("a release covering W-01..W-03: WeChat unlocked", H.active(d, "wechat"), False)


if __name__ == "__main__":
    sys.exit(run_parts([_part_lock_state, _part_scheduled_boot, _part_locked_power_off,
                        _part_orders_refused, _part_engine_steps_named, _part_selfcheck_while_locked,
                        _part_timers_off, _part_wakes_every_minute,
                        _part_wechat_push_locked]))
