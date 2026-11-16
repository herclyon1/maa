"""Boot sequence, backend readiness, AUTO-MAS keeper, and update announcements."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


def _part_boot_backend_wait():
    """Boot steps that need the AUTO-MAS backend wait for it right before they run.

Real sequence, 2026-10-17 21:20 (relay-2026-10-17.log on the evidence bucket):
21:20:55 ensure_automas logged that AUTO-MAS came up by itself after 24 s; 21:21:25
efstart_setup found the API refusing the connection (a WARNING, ledger #104); 21:21:30
the boot self-check failed its "scheduler answers" and "backend process running" lines
(the self-check alarm, ledger #105). The backend's processes then on the machine had
started 21:21:34 and it answered again by 21:23: AUTO-MAS restarted its own backend
mid-boot, and the steps judged it in the gap.

Here the backend is down for the first polls (a fake clock, no real sleep): the boot
steps must wait and pass with no alarm; still down past the limit, the same failure
lines as before must come, saying how long they waited. Fails on the code before
boot_stages.await_backend (the steps asked once, at once).

    Formerly test_boot_backend_wait.py.
    """
    import logging
    import os
    import tempfile
    import types

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    import boot_stages
    from ark_relay.core import texts
    from ark_relay.features.gameupdate import efstart_setup
    from ark_relay.features.phone import commands
    from ark_relay.features.selfcheck import selfcheck


    class _Rec(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def warnings(self):
            return [r.getMessage() for r in self.records if r.levelno >= logging.WARNING]


    class _Notifier:
        channels = ["企业微信机器人"]

        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert))
            return []


    # The fake machine: the clock only moves when the relay sleeps; the backend answers
    # from `back_at` on (None: never).
    now = [0.0]
    back_at = [None]
    polls = [0]


    def _up() -> bool:
        polls[0] += 1
        return back_at[0] is not None and now[0] >= back_at[0]


    # The relay's own waits read the time module (as tests/test_automas_boot_one_alarm.py
    # fakes it); nothing else in this test sleeps.
    boot_stages.time.monotonic = lambda: now[0]
    boot_stages.time.sleep = lambda s: now.__setitem__(0, now[0] + s)
    boot_stages._stop_requested = lambda: False
    commands.mas_up = _up


    def _mas(path, body=None, timeout=20):
        if not _up():
            raise ConnectionRefusedError(10061, "refused")
        return {"code": 200, "data": {}}


    commands._mas = _mas


    def _install(cfg):
        """efstart_setup.install's answer when the API refuses (its own text) or answers."""
        if not _up():
            return False, ["调度程序没应答，终末地的开游戏设置没核对：连不上"]
        return True, []


    efstart_setup.install = _install
    efstart_setup.check_d3d11 = lambda: None

    BACKEND = (4242, r"D:\ark\automas\AUTO-MAS\backend\.venv\Scripts\python.exe D:\ark\automas\AUTO-MAS\main.py")
    _real_run = selfcheck.run


    def _run(cfg, **kw):
        """The real self-check, its machine reads faked: the process table holds the
    backend only while the API answers (a restarting backend has neither)."""
        return _real_run(cfg, procs=lambda: [BACKEND] if _up() else [(1, "explorer.exe")],
                         run_ok=lambda cmd: (True, ""), schedule=lambda: [{"times": ["21:30"]}],
                         contract=lambda d: types.SimpleNamespace(missing=[], unreadable=[], judged=True),
                         # 11-14: the virtualization read is faked too. Unfaked it asked the real machine: the
                         # Mac has no pwsh (not judged), but the GitHub windows runner is a Hyper-V guest, so
                         # the self-check failed there on VIRT_NAME (relay-windows red since at least 11-10).
                         has_module=lambda m: True, virt=lambda: "VBS=0 HV=False", **kw)


    selfcheck.run = _run
    # The scripts' update settings are another line's business (an empty fake reply has none).
    selfcheck._handed_updates_gaps = lambda data: []


    def boot(down_for):
        """Power on with the backend down for `down_for` seconds (None: never back); run the
    two steps that alarmed on 10-17. Returns (warnings, notifier, the self-check lines)."""
        now[0], polls[0] = 1000.0, 0
        back_at[0] = None if down_for is None else now[0] + down_for
        boot_stages._backend_gave_up = [None]
        rec = _Rec()
        lg = logging.getLogger("ark.test_boot")
        lg.handlers[:] = [rec]
        lg.setLevel(logging.INFO)
        lg.propagate = False
        selfcheck.log.handlers[:] = [rec]
        selfcheck.log.setLevel(logging.INFO)
        n = _Notifier()
        with tempfile.TemporaryDirectory() as td:
            os.environ["ARK_LOG_FILE"] = str(Path(td) / "relay.log")
            cfg = types.SimpleNamespace(automas_dir=None, state_dir=td, history_dir=td,
                                        phone_topic="t", phone_pin="p")
            boot_stages._stage_endfield_start(cfg, n, lg)
            boot_stages._stage_selfcheck(cfg, n, lg)
        lines = {r.getMessage() for r in rec.records if r.getMessage().startswith("开机自检")}
        return rec.warnings(), n, lines


    def mas_lines(lines):
        return sorted(x for x in lines if "调度程序有应答" in x or "后台程序在跑" in x)


    print("\n[10-17 21:21: the backend restarts and is back after 60 s - the steps wait, no alarm]")
    warns, n, lines = boot(60)
    check("no WARNING (efstart_setup's 「连不上」 is not logged)", warns, [])
    check("no self-check alarm", [t for t, _, _ in n.sent if t == texts.SELFCHECK_FAILED], [])
    check("both AUTO-MAS self-check lines pass",
          mas_lines(lines), sorted(["开机自检 ✓ 调度程序的后台程序在跑", "开机自检 ✓ 调度程序有应答"]))
    check("waited about the 60 s, not the whole limit", 1060 <= now[0] < 1060 + 2 * boot_stages.BACKEND_POLL_SECONDS)
    check("polled every few seconds, not once", polls[0] > 10)

    print("\n[the backend never comes back - the same failures as before, saying the wait]")
    warns, n, lines = boot(None)
    limit = boot_stages.BACKEND_WAIT_SECONDS
    check("efstart_setup's WARNING, its own text kept",
          [w for w in warns if "终末地开游戏的设置没全对上" in w and "调度程序没应答，终末地的开游戏设置没核对：连不上" in w
           and f"等了 {limit} 秒" in w] != [])
    check("the self-check alarm, once", [t for t, _, _ in n.sent].count(texts.SELFCHECK_FAILED), 1)
    body = next((b for t, b, _ in n.sent if t == texts.SELFCHECK_FAILED), "")
    check("its body lists 调度程序有应答 with the wait", f"调度程序有应答：开机后中继叫过它一次，又等了 {limit} 秒，仍然没有应答" in body)
    check("its body lists 调度程序的后台程序在跑", "调度程序的后台程序在跑" in body)
    check("the boot waited the limit once, not again for the self-check",
          now[0], 1000.0 + limit)

    print("\n[the backend answers at once - nothing waits, nothing is logged about it]")
    warns, n, lines = boot(0)
    check("no WARNING", warns, [])
    check("no time spent", now[0], 1000.0)

    print("\n[ensure_automas already gave up (revived, 120 s, 🔌 sent): no second wait]")
    real_revive, real_shell = boot_stages._revive_automas, boot_stages.shell_running
    boot_stages._revive_automas, boot_stages.shell_running = (lambda: None), (lambda: False)
    now[0], back_at[0] = 1000.0, None
    boot_stages._backend_gave_up = [None]
    boot_stages.ensure_automas(timeout=120)
    boot_stages._revive_automas, boot_stages.shell_running = real_revive, real_shell
    t_after = now[0]
    rec = _Rec()
    lg = logging.getLogger("ark.test_boot")
    lg.handlers[:] = [rec]
    lg.propagate = False
    with tempfile.TemporaryDirectory() as td:
        boot_stages._stage_endfield_start(types.SimpleNamespace(automas_dir=None, state_dir=td), _Notifier(), lg)
    check("the step did not wait again", now[0], t_after)
    check("its failure line says the 120 s", any("等了 120 秒" in w for w in rec.warnings()))

    print("\n[a wait ran out, then the backend answered, then went again: the next step waits again]")
    # Audit 11-08 A-20: the gave-up mark was never cleared, so after one timeout at boot every
    # later step that found the backend down gave up at once and said it had waited 120 s.
    lg = logging.getLogger("ark.test_boot")
    lg.handlers[:] = [_Rec()]
    lg.propagate = False
    now[0], back_at[0] = 1000.0, None
    boot_stages._backend_gave_up = [120.0]
    back_at[0] = now[0]                                  # answering now
    check("answering: (True, 0)", boot_stages.await_backend(lg, "测试"), (True, 0.0))
    check("……the earlier gave-up wait is forgotten", boot_stages._backend_gave_up[0], None)
    back_at[0] = None                                    # down again
    t0 = now[0]
    up, waited = boot_stages.await_backend(lg, "测试")
    check("down again: waits the whole limit again, not the old 120 s at once",
          (up, waited, now[0] - t0 >= boot_stages.BACKEND_WAIT_SECONDS), (False, waited, True))
    check("……and says the time it waited this time", waited >= boot_stages.BACKEND_WAIT_SECONDS)

    print("\n[a stop mid-wait: the step neither waits on nor alarms]")
    now[0], back_at[0] = 1000.0, None
    boot_stages._backend_gave_up = [None]
    stops = iter([False, False, True])
    boot_stages._stop_requested = lambda: next(stops, True)
    rec = _Rec()
    lg = logging.getLogger("ark.test_boot")
    lg.handlers[:] = [rec]
    lg.propagate = False
    with tempfile.TemporaryDirectory() as td:
        boot_stages._stage_endfield_start(types.SimpleNamespace(automas_dir=None, state_dir=td), _Notifier(), lg)
    check("no WARNING", rec.warnings(), [])
    check("stopped after a few polls", now[0] < 1000.0 + 4 * boot_stages.BACKEND_POLL_SECONDS)
    boot_stages._stop_requested = lambda: False

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("\nall checks passed")


def _part_boot_config_alarm():
    """Config warnings and a bad-config exit at boot reach the group (audit s23 F1, 10-13).

Until 10-13 boot_stages._stage_bootstrap ran cfg.validate() - which logs
「配置提醒: …」 (config.py) and whose problems were logged as 「配置有问题」 before the
early return - before errwatch.install. Nothing buffers records logged before the
handler exists, so both reached relay.log only: a relay that would not start said
why to nobody, and the 「没有配置群机器人」 warning added 10-13 (0cd624e2) was never
pushed. Now errwatch is installed first, and the bad-config exit waits for its push.

Runs the real _stage_bootstrap with the real Config (from environment variables) and
a recording notifier in place of the real channels.

    Formerly test_boot_config_alarm.py.
    """

    import logging
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import boot_stages
    from ark_relay.core import notify
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.evidence import error_evidence


    class Recorder:
        """Stands in for notify.Notifier: takes every push, sends nothing."""

        made: list["Recorder"] = []

        def __init__(self, cfg):
            self._state_dir = Path(cfg.state_dir)
            self.sent: list[tuple[str, str]] = []
            Recorder.made.append(self)

        def send_group(self, title, body):
            self.sent.append((title, body))
            return []

        def send(self, title, body, **_k):
            self.sent.append((title, body))
            return []

        def went_to_group(self):
            return True


    def boot(env: dict) -> tuple[object, list, list]:
        """_stage_bootstrap under `env`; returns what it returned, the pushes made by the
    time it returned, and every push made once errwatch has drained."""
        keys = ("ARK_HISTORY_DIR", "ARK_STATE_DIR", "ARK_LOG_FILE", "SERVERCHAN_KEY",
                "WECOM_BOT_URL", "WECOM_CORPID", "WECOM_SECRET", "WECOM_AGENTID", "ARK_AUTOMAS_DIR")
        saved_env = {k: os.environ.get(k) for k in keys}
        real_notifier, real_upload = notify.Notifier, error_evidence.upload_daily_logs
        ark = logging.getLogger(errwatch.ARK)
        before = list(ark.handlers)
        # errwatch globals _stage_bootstrap sets: put back, so a later test in the same
        # process (the deploy gate runs them in one) does not push through this one's cfg.
        saved_errwatch = (errwatch._handler[0], errwatch._relay_poweroff[0], errwatch._evidence_uploader[0])
        Recorder.made.clear()
        for k in keys:
            os.environ.pop(k, None)
        os.environ.update(env)
        notify.Notifier = Recorder
        error_evidence.upload_daily_logs = lambda cfg: {}
        try:
            out = boot_stages._stage_bootstrap()
            at_return = [x for r in Recorder.made for x in r.sent]
            errwatch.drain(5.0)
        finally:
            for h in [h for h in ark.handlers if h not in before]:
                ark.removeHandler(h)
                h.close()
            errwatch._handler[0], errwatch._relay_poweroff[0], errwatch._evidence_uploader[0] = saved_errwatch
            notify.Notifier, error_evidence.upload_daily_logs = real_notifier, real_upload
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        sent = [x for r in Recorder.made for x in r.sent]
        return out, at_return, sent


    def said(sent, words: str) -> bool:
        return any(words in title + body for title, body in sent)


    print("[bad config (no history folder) plus a config warning (no group robot)]")
    state = tmpdir()
    out, at_return, sent = boot({"ARK_STATE_DIR": str(state), "ARK_LOG_FILE": str(state / "relay.log"),
                                 "ARK_HISTORY_DIR": str(state / "no-such-folder"), "SERVERCHAN_KEY": "test-key"})
    check("the relay does not start", out, None)
    # The push quotes the record's first line, which is plain words; the setting names
    # stay in relay.log (texts.plain would not quote them).
    check("the exit reached the group before it", said(at_return, "中继没有启动"), True)
    check("the warning reached the group too", said(sent, "读设置"), True)
    check("one push each, not one per problem", len(sent), 2)

    print("[good config with the same warning: the relay starts and the warning is pushed]")
    state = tmpdir()
    history = state / "history"
    history.mkdir()
    out, _, sent = boot({"ARK_STATE_DIR": str(state), "ARK_LOG_FILE": str(state / "relay.log"),
                         "ARK_HISTORY_DIR": str(history), "SERVERCHAN_KEY": "test-key"})
    check("the relay starts", out is not None, True)
    check("the 配置提醒 warning reached the group (from 「读设置」, ark.config)", said(sent, "读设置"), True)
    check("nothing about not starting", said(sent, "没有启动"), False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_boot_restore_recovered():
    """boot_stages._stage_reenable_maaend: a narrowed MaaEnd master left over from the
last session and put back at boot is a fault the relay got over by itself.

The user on 2026-10-06 05:07, about faults the relay recovered from by itself: 「报错后自己好了的，只进日报、不进群」.
Until then 「开机：…（上次关机前没改回）」 was a plain WARNING, so a master the
relay had just put right before anything ran still rang the group. Now:
* put back (the gathering routes, or the make-up's narrowing) -> one WARNING
  marked errwatch.recovered(): not pushed, in the daily report tagged with
  the words 「自己好了，只进日报」 there;
* could not be put back -> the WARNING stays plain, pushed.
Every other step of the stage is faked; a real errwatch handler on the
stage's logger shows what is pushed and what the daily report lists.

    Formerly test_boot_restore_recovered.py.
    """
    import logging
    import tempfile
    import time
    import types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages
    from ark_relay.features.makeup import collect_retry, makeup
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.core import mastercfg
    from ark_relay.core.config import SERVER_TZ


    class Records(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def warnings(self):
            return [(r.getMessage(), bool(getattr(r, errwatch.RECOVERED, False)))
                    for r in self.records if r.levelno == logging.WARNING]


    class Pushes:
        def __init__(self):
            self.sent = []

        def send(self, title, body, **k):
            self.sent.append((title, body))
            return []


    def run(restore_master, try_restore):
        """One pass of the stage with the two restores faked; (records, pushes, state dir)."""
        state = Path(tempfile.mkdtemp(prefix="boot-restore-"))
        rec, pushes = Records(), Pushes()
        lg = logging.getLogger(f"ark.test_boot_restore.{id(rec)}")
        lg.propagate = False
        lg.setLevel(logging.DEBUG)
        lg.addHandler(rec)
        h = errwatch.ErrorKindAlert(pushes, state_dir=state, known={}, pace=0, retry=(0.05,))
        lg.addHandler(h)
        collect_retry.restore_master = restore_master
        makeup.maaend_still_running = lambda state_dir: False
        makeup.try_restore = try_restore
        cfg = types.SimpleNamespace(state_dir=state, automas_dir=state, maaend_dir=state)
        boot_stages._stage_reenable_maaend(cfg, types.SimpleNamespace(send=lambda *a, **k: []), lg)
        end = time.time() + 3
        while time.time() < end and h.pending():
            time.sleep(0.02)
        time.sleep(0.1)
        h.close()
        return rec, pushes, state


    saved = (gameupdate.spmed_check, mastercfg.prune_maaend_orphans,
             mastercfg.migrate_maaend_options, collect_retry.restore_master, makeup.maaend_still_running,
             makeup.try_restore)
    gameupdate.spmed_check = lambda cfg: None
    mastercfg.prune_maaend_orphans = lambda a, m: ([], "")
    mastercfg.migrate_maaend_options = lambda a, m: (False, "")
    ROUTES = "母本里的采集路线已改回原来的 12 条（2026-10-05/endfield/MaaEnd-21-40-00 那趟之后临时改过）"
    MAKEUP = "终末地母本已改回补跑前的样子"
    try:
        print("[both narrowings left over and put back at boot: daily report only]")
        rec, pushes, state = run(lambda cfg: ROUTES, lambda cfg, notifier=None: (MAKEUP, ""))
        warns = rec.warnings()
        check("two WARNINGs, both marked recovered", [r for _, r in warns], [True, True])
        check("they say what was put back and that it was left over",
              all("上次关机前没改回" in m and "这次开机改回了" in m for m, _ in warns) and len(warns) == 2)
        check("nothing reached the group", pushes.sent, [])
        section = errwatch.daily_section(state, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
        check("the daily report lists them, tagged 「自己好了，只进日报」",
              "采集路线已改回" in section and section.count("自己好了，只进日报") == 2)

        print("\n[the make-up's narrowing could not be put back: pushed]")
        rec, pushes, state = run(lambda cfg: "", lambda cfg, notifier=None: ("", "找不到终末地的母本"))
        check("one WARNING, not marked recovered", [r for _, r in rec.warnings()], [False])
        check("it reached the group", len(pushes.sent), 1)

        print("\n[nothing left over: nothing said]")
        rec, pushes, state = run(lambda cfg: "", lambda cfg, notifier=None: ("", ""))
        check("no WARNING", rec.warnings(), [])
    finally:
        (gameupdate.spmed_check, mastercfg.prune_maaend_orphans,
         mastercfg.migrate_maaend_options, collect_retry.restore_master, makeup.maaend_still_running,
         makeup.try_restore) = saved


def _part_keeper_blind_backoff():
    """The keeper does not back off when it revived nothing (audit s15 #1, 2026-10-13).

Machine record (tests/fixtures/keeper_blind_20261010.log, relay.log 10-10 16:14:07):
the process table could not be read (「读得到每个程序是怎么启动的…读不到」) while
AUTO-MAS answered (「✓ 调度程序有应答」). Five relay starts from 16:14 to 17:21 got no
backend handle. In that state _automas_running() is True (it falls back to the
API), nothing is revived, and every handle-less check still doubled revive_wait:
checks at 180, 360, 720, 1440, 2880 s ... out to every 30 minutes, with not one
keeper line in the log. A backend that died then was found up to 30 minutes late.

Now: the wait doubles only after a real revival; a backend that is up but cannot
be attached is checked every procwatch.AUTOMAS_CHECK_SECONDS, and that is said
once at INFO.

    Formerly test_keeper_blind_backoff.py.
    """
    import itertools
    import logging
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                  "win32evtlog", "win32gui"):
        sys.modules.setdefault(_name, _Stub(_name))

    import time

    import boot_stages
    from ark_relay.features.host import automas_keeper, automas_procs, procwatch
    from ark_relay.features.phone import commands


    # The machine's state, read from its own self-check lines.
    lines = (fx_dir(Path(__file__), "fixtures") / "keeper_blind_20261010.log").read_text(encoding="utf-8").splitlines()
    procs_unreadable = any("读得到每个程序是怎么启动的" in ln and "读不到" in ln for ln in lines)
    api_answers = any("✓ 调度程序有应答" in ln for ln in lines)
    check("record: process table unreadable", procs_unreadable, True)
    check("record: API answering", api_answers, True)

    clock = [1000.0]
    time.monotonic = lambda: clock[0]
    automas_procs._python_processes = lambda: None if procs_unreadable else []
    commands.mas_up = lambda: api_answers
    procwatch._start_process_watch = lambda evt, alive, log: True
    revives = []
    boot_stages._revive_automas = lambda: revives.append(clock[0])


    class _Keep(logging.Handler):
        def __init__(self):
            super().__init__()
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, record.getMessage()))


    keep = _Keep()
    log = automas_keeper.log
    log.addHandler(keep)
    log.setLevel(logging.INFO)


    class _Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, *a, **k):
            self.sent.append(title)


    print("[进程表读不到、接口有应答：没拉起过就不退避，按活性检查间隔查]")
    k = automas_keeper._AutomasKeeper(log, _Notifier())
    check("no handle at start", k.handle, None)
    keep.rows.clear()
    checks = []
    start = clock[0]
    while clock[0] - start < 2 * 3600:
        clock[0] += k.cap_wait(3600.0)
        due = k.revive_deadline
        k.check(False, clock[0])
        if due is not None and clock[0] >= due:
            checks.append(clock[0])
    gaps = [round(b - a) for a, b in itertools.pairwise(checks)]
    check("checks within the first two hours (>= 40, was 5)", len(checks) >= 40, True)
    check("no gap longer than the liveness interval", max(gaps) if gaps else None, procwatch.AUTOMAS_CHECK_SECONDS)
    check("nothing revived", revives, [])
    said = [m for lv, m in keep.rows if "挂不上它的进程句柄" in m]
    check("said once", len(said), 1)
    check("at INFO", [lv for lv, m in keep.rows if "挂不上它的进程句柄" in m], ["INFO"])

    print("[真拉起过、没起来：照旧翻倍退避]")
    automas_procs._python_processes = lambda: []
    commands.mas_up = lambda: False
    automas_procs._installer_running = lambda: False
    automas_procs._automas_shell_running = lambda: False
    clock[0] = 50000.0
    k2 = automas_keeper._AutomasKeeper(log, _Notifier())
    waits = []
    for _ in range(4):
        clock[0] = k2.revive_deadline
        k2.check(False, clock[0])
        waits.append(round(k2.revive_deadline - clock[0]))
    check("180, 360, 720, 1440", waits, [180, 360, 720, 1440])
    check("four revivals", len(revives), 4)

    print("[拦着没拉（安装程序开着）：不翻倍]")
    automas_procs._installer_running = lambda: True
    revives.clear()
    clock[0] = 90000.0
    k3 = automas_keeper._AutomasKeeper(log, _Notifier())
    waits = []
    for _ in range(3):
        clock[0] = k3.revive_deadline
        k3.check(False, clock[0])
        waits.append(round(k3.revive_deadline - clock[0]))
    check("held: the wait stays 180", waits, [180, 180, 180])
    check("held: nothing revived", revives, [])


def _part_keeper_exit():  # noqa: C901
    """The AUTO-MAS keeper: an exit while the machine goes down is INFO with its reason; any other exit is decided by whether the backend comes back.

2026-10-06 log sweep (08-20 to 10-05): 「AUTO-MAS 后端退出了」 68 times and
「AUTO-MAS 后端不在，正在拉起（第 1 次）」 62 times, every one at WARNING. The keeper
never asked whether the machine was going down - and the relay powers the machine
off after every queue (`shutdown /s /t 60`), so Windows closing the session took
the backend with it, the keeper read that as a crash and started a revival
against a closing session. Every WARNING now reaches the group (2026-10-06).

The going-down signals are errwatch's (mark_stopping: the relay's power-off and
SvcStop/SvcShutdown; Windows' SM_SHUTTINGDOWN), and the keeper waits a moment
for one when the exit comes first. Time is a virtual clock: nothing here waits.

Since the user's rule of 2026-10-06 05:07 (「报错后自己好了的，只进日报、不进群」)
any other exit is INFO with its evidence and decided later: the backend back
(the relay's revival, or by itself after an update) -> one WARNING marked
errwatch.recovered(), the daily report only; not back at the
REVIVE_ALERT_AFTER-th check -> 「🔌 AUTO-MAS 启动不起来」 (alert=True) after three
failed revivals, a WARNING while the relay holds off (an installer on screen);
not back when the service stops -> a WARNING. A real errwatch handler on each
keeper's logger shows what is pushed and what the daily report lists.

    Formerly test_keeper_exit.py.
    """
    import logging
    import subprocess
    import tempfile
    import time
    import types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    SYNCHRONIZE = 0x00100000
    closed, opened = [], []
    exit_codes = {}

    w32api = _Stub("win32api")
    w32api.CloseHandle = lambda h: closed.append(h)


    def open_process(access, inherit, pid):
        opened.append(access)
        if access != SYNCHRONIZE and refuse_query[0]:
            raise OSError("access denied")
        return f"handle:{pid}"


    w32api.OpenProcess = open_process
    refuse_query = [False]
    w32con = _Stub("win32con")
    w32con.SYNCHRONIZE = SYNCHRONIZE
    w32process = _Stub("win32process")


    def get_exit_code(h):
        if h not in exit_codes:
            raise OSError("no query right")
        return exit_codes[h]


    w32process.GetExitCodeProcess = get_exit_code
    w32event = _Stub("win32event")
    w32event.CreateEvent = lambda *a: object()
    w32event.SetEvent = lambda h: None

    FAKES = {"win32api": w32api, "win32con": w32con, "win32process": w32process, "win32event": w32event}
    for name in ("win32serviceutil", "win32service", "win32file", "servicemanager", "win32security",
                 "win32ts", "win32profile", "wmi", "pythoncom", "win32com", "win32com.client"):
        FAKES[name] = _Stub(name)
    saved = {k: sys.modules.get(k) for k in [*FAKES, "service"]}
    sys.modules.update(FAKES)
    sys.modules.pop("service", None)
    import boot_stages
    import service  # a fresh copy built on the fakes above
    from ark_relay.features.host import automas_keeper, automas_procs, dirwatch, mainloop, procwatch, shutdown_signs
    from ark_relay.features.alarm import errwatch
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ

    # The backend's API answers unless a case says otherwise (清单-1108 A-06: a handle is
    # adopted only once the API answers; the cases on that are at the end).
    api = {"up": True}
    automas_keeper._api_up = lambda: api["up"]


    def set_time(t):
        """service.py's code now lives in several modules, each reading its own `time`; swap it in all."""
        for m in (service, shutdown_signs, procwatch, dirwatch, automas_keeper, mainloop):
            m.time = t


    class VClock:
        def __init__(self):
            self.now, self.due = 5000.0, []

        def monotonic(self):
            return self.now

        def sleep(self, s):
            self.now += max(0.0, s)
            for item in [d for d in self.due if d[0] <= self.now]:
                self.due.remove(item)
                item[1]()

        def at(self, delay, fn):
            self.due.append((self.now + delay, fn))

        def time(self):
            return self.now


    TASKS = {"plain": b"explorer.exe 4 Console", "setup": b"AUTO-MAS-Setup.exe 1234 Console",
             "shell": b"AUTO-MAS.exe 18864 Console"}
    tasks = {"list": TASKS["plain"]}


    def fake_run(cmd, **kw):
        key = " ".join(cmd).lower()
        if key.startswith("tasklist /fi imagename eq auto-mas.exe"):
            out = TASKS["shell"] if b"auto-mas.exe" in tasks["list"].lower() else b"INFO: No tasks are running"
        elif key.startswith("tasklist"):
            out = tasks["list"]
        else:
            out = b""
        return types.SimpleNamespace(stdout=out, returncode=0)


    class Records(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def at(self, level):
            return [r.getMessage() for r in self.records if r.levelno == level]


    class Notifier:
        def __init__(self):
            self.sent = []
            self.calls = []

        def send(self, title, body, **k):
            self.sent.append(title)
            self.calls.append((title, body, k.get("alert", False)))
            return []


    class Pushes:
        """errwatch's notifier: what its WARNING / ERROR records pushed to the group."""

        def __init__(self):
            self.sent = []

        def send(self, title, body, **k):
            self.sent.append((title, body))
            return []


    def pushed(rec, want=0, secs=3.0):
        """The group pushes errwatch made from the keeper's records (waits for its push thread)."""
        end = time.time() + secs
        while time.time() < end and (rec.errwatch.pending() or len(rec.pushes.sent) < want):
            time.sleep(0.02)
        time.sleep(0.1)
        return [b for _, b in rec.pushes.sent]


    def stop(k):
        """The service's stop reaching the keeper (absent before 2026-10-06: nothing happens)."""
        getattr(k, "stopping", lambda: None)()


    def daily(rec):
        return errwatch.daily_section(rec.state, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))


    orig = (errwatch.system_shutting_down, procwatch.time, subprocess.run, boot_stages._revive_automas,
            automas_procs._automas_running, automas_procs._automas_handle, procwatch._start_process_watch,
            automas_procs._python_processes)
    errwatch.system_shutting_down = lambda: False
    subprocess.run = fake_run
    events = {"xml": []}      # the System log's 1074 / 1075 events, newest first
    shutdown_signs._shutdown_event_xml = lambda *a: events["xml"]


    def ev1074(when_utc, process, user):
        """A User32 1074 as EvtRender gives it (layout per the event's param1..param7)."""
        params = [process, "INS", "Other (Unplanned)", "0x0", "power off", "", user]
        data = "".join(f'<Data Name="param{i}">{v}</Data>' for i, v in enumerate(params, 1))
        return ('<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
                '<Provider Name="User32"/><EventID Qualifiers="32768">1074</EventID>'
                f'<TimeCreated SystemTime="{when_utc}"/><Channel>System</Channel></System>'
                f'<EventData>{data}</EventData></Event>')


    def ev1075(when_utc):
        return ('<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
                '<Provider Name="User32"/><EventID Qualifiers="32768">1075</EventID>'
                f'<TimeCreated SystemTime="{when_utc}"/></System><EventData><Data Name="param1">x</Data>'
                '</EventData></Event>')
    revived = []
    boot_stages._revive_automas = lambda: revived.append(procwatch.time.now)


    def keeper(handle="handle:21932"):
        """A keeper holding `handle`, as _loop builds it (its own __init__, WMI listener faked)."""
        rec = Records()
        log = logging.getLogger(f"ark.test.keeper.{len(revived)}.{id(rec)}")
        log.propagate = False
        log.setLevel(logging.DEBUG)
        log.addHandler(rec)
        rec.state, rec.pushes = Path(tempfile.mkdtemp(prefix="keeper-exit-")), Pushes()
        rec.errwatch = errwatch.ErrorKindAlert(rec.pushes, state_dir=rec.state, known={}, pace=0, retry=(0.05,))
        log.addHandler(rec.errwatch)
        automas_procs._automas_handle = lambda: handle
        procwatch._start_process_watch = lambda evt, alive, lg: True
        k = automas_keeper._AutomasKeeper(log, Notifier())
        return k, rec


    def run_exit(code, task_list="plain", down=None, down_after=None, running_after=False, down_after_fn=None):
        """The backend's handle signals; returns (records, revivals)."""
        exit_codes.clear()
        if code is not None:
            exit_codes["handle:21932"] = code
        tasks["list"] = TASKS[task_list]
        revived.clear()
        vt = VClock()
        set_time(vt)
        k, rec = keeper()
        if down:
            down()
        if down_after is not None:
            vt.at(down_after, down_after_fn or errwatch.mark_stopping)
        automas_procs._automas_running = lambda: running_after
        automas_procs._automas_handle = lambda: None
        try:
            k.check(True, vt.now)
        finally:
            set_time(orig[1])
            errwatch._stopping.clear()
            errwatch._relay_poweroff[0] = lambda: False
        return rec, list(revived), k


    def relay_poweroff():
        """The relay itself issued the machine power-off (errwatch.relay_shutdown_issued)."""
        errwatch._relay_poweroff[0] = lambda: True


    def first(msg):
        return msg.splitlines()[0]


    try:
        print("[the relay's own power-off (issued 60 s before): INFO, no revival]")
        rec, rv, k = run_exit(0x40010004, down=relay_poweroff)
        check("no WARNING", rec.at(logging.WARNING), [])
        check("INFO says it is the relay's own power-off, with the exit code",
              any("不算故障" in m and "0x40010004" in m and "中继自己发出了关机命令" in m for m in rec.at(logging.INFO)))
        check("no revival against the closing session", rv, [])
        check("handle let go", k.handle, None)

        # Mute audit 10-12 item 10: after an exit put down to the relay's own power-off no
        # deadline was armed, so when that power-off was cancelled (「下次跑完不关机」) and the
        # machine stayed up, nothing ever revived AUTO-MAS or said it was gone.
        print("\n[the relay's power-off cancelled after the exit: the next check revives it and says so]")
        rec, rv, k = run_exit(0x40010004, down=relay_poweroff)   # run_exit puts the power-off back: cancelled
        check("a check is armed while the power-off is under way", k.revive_deadline is not None, True)
        # cap_wait reads time.monotonic(), so ask it on the virtual clock the deadline was set
        # on (a fresh VClock reads the same 5000.0 run_exit's check got). On the real clock the
        # answer depended on the machine's uptime: a Mac up for days read the deadline as long
        # past (1 s), a Windows runner booted minutes before (monotonic counts from boot there)
        # read it as over an hour away (3600 s, run 38360295330).
        vt = VClock()
        set_time(vt)
        try:
            check("so the loop wakes for it, no later than the deadline",
                  k.cap_wait(3600.0), max(1.0, (k.revive_deadline or 0) - vt.now))
            check("which is well inside the hour", k.cap_wait(3600.0) < 3600.0, True)
        finally:
            set_time(orig[1])
        vt = VClock()
        set_time(vt)
        revived.clear()
        automas_procs._automas_running = lambda: False
        try:
            k.check(False, (k.revive_deadline or 0) + 1)
        finally:
            set_time(orig[1])
        check("revived once the power-off is off", len(revived), 1)
        check("one WARNING (pushed): AUTO-MAS is not running", [("没在运行" in m) for m in rec.at(logging.WARNING)], [True])

        # 清单-1108 A-06: the relay issues its power-off from this same loop thread
        # (engine.tick -> shutdown._maybe_shutdown), so nothing can set the flag while the
        # keeper rules on an exit there; the 15 s settle wait only held the loop.
        print("\n[a power-off 2 s after the exit cannot come from another thread: the keeper does not wait]")
        rec, rv, k = run_exit(1, down_after=2.0, down_after_fn=relay_poweroff)
        check("ruled at once: an exit nothing explained, no 15 s stall",
              (k.gone is not None, any("不算故障" in m for m in rec.at(logging.INFO))), (True, False))

        # The user, 2026-10-06: only the planned power-off the relay itself started may
        # stay out of the group; every other shutdown is pushed.
        print("\n[a `shutdown /s` by hand: the service stop control comes 2 s later - pushed at the stop]")
        rec, rv, k = run_exit(1, down_after=2.0)
        check("not called 「not a fault」", any("不算故障" in m for m in rec.at(logging.INFO)), False)
        stop(k)
        warns = rec.at(logging.WARNING)
        check("the stop: one WARNING, the backend not back", len(warns) == 1 and "中继停下时还没重新起来" in warns[0])
        check("it reached the group", len(pushed(rec, 1)), 1)
        stop(k)
        check("said once", len(rec.at(logging.WARNING)), 1)

        print("\n[10-10 04:28: Windows shut down by hand, the stop notice right after the exit was ruled on - pushed, said as the shutdown]")
        rec, rv, k = run_exit(1)
        vt = VClock()
        vt.now = k.gone["at"] + 1.0     # relay.log 04:28:44 the exit line, 04:28:45 「收到停止通知（Windows 关机）」
        set_time(vt)
        errwatch.mark_os_shutdown()
        errwatch.mark_stopping()
        try:
            stop(k)
        finally:
            set_time(orig[1])
            errwatch._stopping.clear()
            errwatch._os_shutdown.clear()
        warns = rec.at(logging.WARNING)
        check("one WARNING", len(warns), 1)
        check("it says Windows shut down, not 「意外退出…没在关机」",
              bool(warns) and "Windows 关机" in warns[0] and "没在关机" not in warns[0] and "意外" not in warns[0])
        check("it reached the group", len(pushed(rec, 1)), 1)

        # 2026-10-10 04:28 (machine clock): `shutdown /s /t 60` by hand wrote its 1074 at
        # 04:27:24 (20:27:24 UTC); AUTO-MAS exited ~04:28:29; the stop notice came 04:28:45.
        print("\n[10-10 04:28 sample: a 1074 80 s before the exit - no revival, the stop says who shut down]")
        events["xml"] = [ev1074("2026-10-09T20:27:24.5512345Z", r"C:\Windows\system32\shutdown.exe (INS)",
                                r"INS\Administrator")]
        try:
            rec, rv, k = run_exit(1)
            check("no revival into the closing session", rv, [])
            check("INFO names the requester and the time",
                  any("shutdown.exe" in m and "04:27:24" in m for m in rec.at(logging.INFO)))
            check("not called 「意外退出」", any("意外退出" in m for m in rec.at(logging.INFO)), False)
            vt = VClock()
            vt.now = k.gone["at"] + 1.0
            set_time(vt)
            k.check(False, vt.now)                   # a loop wake before the stop: still no revival
            check("still no revival on the next wake", list(revived), [])
            errwatch.mark_os_shutdown()
            errwatch.mark_stopping()
            try:
                stop(k)
            finally:
                set_time(orig[1])
                errwatch._stopping.clear()
                errwatch._os_shutdown.clear()
            warns = rec.at(logging.WARNING)
            check("one WARNING at the stop", len(warns), 1)
            check("it says Windows shut down, by whom and when",
                  bool(warns) and "Windows 关机" in warns[0] and "shutdown.exe" in warns[0]
                  and "INS\\Administrator" in warns[0] and "04:27:24" in warns[0])
            check("it reached the group", len(pushed(rec, 1)), 1)
        finally:
            events["xml"] = []

        print("\n[a 1074 followed by a 1075 (shutdown /a): not a shutdown - revived at once, said as unexpected]")
        events["xml"] = [ev1075("2026-10-09T20:27:40Z"),
                         ev1074("2026-10-09T20:27:24Z", r"C:\Windows\system32\shutdown.exe (INS)", r"INS\Administrator")]
        try:
            rec, rv, k = run_exit(1)
        finally:
            events["xml"] = []
        check("revived once", len(rv), 1)
        check("said as an unexpected exit", any("意外退出" in m for m in rec.at(logging.INFO)))

        print("\n[a 1074 but the machine stays up past SHUTDOWN_NO_SHOW_SECONDS: revived then]")
        events["xml"] = [ev1074("2026-10-09T20:27:24Z", r"C:\Windows\system32\shutdown.exe (INS)", r"INS\Administrator")]
        try:
            rec, rv, k = run_exit(1)
            check("not revived at once", rv, [])
            vt = VClock()
            vt.now = k.gone["at"] + automas_keeper.SHUTDOWN_NO_SHOW_SECONDS + 1
            set_time(vt)
            automas_procs._automas_running = lambda: False
            try:
                k.check(False, vt.now)
            finally:
                set_time(orig[1])
            check("revived once the shutdown did not come", len(revived), 1)
            check("said why", any("还没关机" in m for m in rec.at(logging.INFO)))
        finally:
            events["xml"] = []

        print("\n[the relay's own power-off (10-09 21:41:51 / 21:49:11 wrote a 1074 too): INFO, nothing pushed]")
        events["xml"] = [ev1074("2026-10-09T13:41:51Z", r"C:\Windows\system32\shutdown.exe (INS)", "NT AUTHORITY\\SYSTEM")]
        try:
            rec, rv, k = run_exit(1, down=relay_poweroff)
            stop(k)
        finally:
            events["xml"] = []
        check("no WARNING", rec.at(logging.WARNING), [])
        check("no revival", rv, [])
        check("nothing reached the group", pushed(rec), [])

        print("\n[shutdown_requested reads the newest event: 1074 alone, 1075 newest, nothing]")
        got = shutdown_signs.shutdown_requested([ev1074("2026-10-09T20:27:24.5512345Z", "p.exe (INS)", "INS\\u")])
        check("process / user / clock (UTC -> the machine's clock)",
              (got or {}).get("process") == "p.exe (INS)" and (got or {}).get("user") == "INS\\u"
              and (got or {}).get("clock") == "04:27:24")
        check("1075 newest -> None", shutdown_signs.shutdown_requested([ev1075("2026-10-09T20:28:00Z"),
                                                                ev1074("2026-10-09T20:27:24Z", "p", "u")]), None)
        check("no events -> None", shutdown_signs.shutdown_requested([]), None)

        print("\n[Windows itself says it is shutting down (SM_SHUTTINGDOWN), not the relay: pushed at the stop]")
        errwatch.system_shutting_down = lambda: True
        try:
            rec, rv, k = run_exit(1)
        finally:
            errwatch.system_shutting_down = lambda: False
        check("not called 「not a fault」", any("不算故障" in m for m in rec.at(logging.INFO)), False)
        stop(k)
        check("the stop: one WARNING", len(rec.at(logging.WARNING)), 1)
        check("it reached the group", len(pushed(rec, 1)), 1)

        print("\n[an exit nothing explains: INFO with the evidence, then the revival at INFO; nothing pushed yet]")
        rec, rv, k = run_exit(0xC0000005)
        check("no WARNING yet (undecided)", rec.at(logging.WARNING), [])
        said = [m for m in rec.at(logging.INFO) if "意外退出" in m]
        line = first(said[0]) if said else ""
        check("one INFO line on the exit", len(said), 1)
        check("it is plain Chinese", texts.plain(line), [])
        check("it carries the exit code", "0xC0000005" in line)
        check("and what was ruled out", "没在关机" in line and "没在装更新" in line)
        check("and whether the window was there", "窗口也没了" in line)
        check("revived once", len(rv), 1)
        check("the revival line itself is INFO",
              any("正在重新打开" in m for m in rec.at(logging.INFO)))
        check("nothing reached the group", pushed(rec), [])

        print("\n[... and the relay's revival brings it back: ONE WARNING, pushed - why it exits is not known (2026-10-10)]")
        set_time(VClock())
        automas_procs._automas_running = lambda: True
        automas_procs._automas_handle = lambda: "handle:31000"
        try:
            k.check(False, k.revive_deadline + 1)
        finally:
            set_time(orig[1])
        warns = rec.at(logging.WARNING)
        check("one WARNING", len(warns), 1)
        line = first(warns[0]) if warns else ""
        check("「AUTO-MAS 后台意外退出过（…退出码…），中继已重新打开」",
              line.startswith("AUTO-MAS 后台意外退出过（") and "退出码 0xC0000005" in line and "中继已重新打开" in line)
        check("it is plain Chinese (the daily report quotes it)", texts.plain(line), [])
        check("not marked recovered", [getattr(r, errwatch.RECOVERED, False) for r in rec.records
                                       if r.levelno == logging.WARNING], [False])
        check("pushed, once", [("中继已重新打开" in x) for x in pushed(rec)], [True])
        section = daily(rec)
        check("the daily report lists it, not tagged 「自己好了，只进日报」",
              "中继已重新打开" in section and "自己好了，只进日报" not in section)
        check("the keeper holds the new backend", (k.handle, k.gone), ("handle:31000", None))

        print("\n[the exit code cannot be read: said so, at INFO]")
        rec, rv, _ = run_exit(None, task_list="shell")
        said = [m for m in rec.at(logging.INFO) if "意外退出" in m]
        check("INFO saying the code could not be read and the window is up",
              len(said) == 1 and "读不到" in said[0] and "窗口还在" in said[0])
        check("no WARNING yet", rec.at(logging.WARNING), [])

        print("\n[an update installer is running when it exits: INFO, hands off]")
        rec, rv, k = run_exit(0, task_list="setup")
        said = [m for m in rec.at(logging.INFO) if "退出了" in m]
        check("INFO saying an installer was up", len(said) == 1 and "安装" in said[0])
        check("no WARNING yet", rec.at(logging.WARNING), [])
        check("not called 「not a fault」", any("不算故障" in m for m in rec.at(logging.INFO)), False)
        check("no revival while it installs", rv, [])

        print("\n[... the update done, AUTO-MAS starts its backend itself: one WARNING, daily report only]")
        automas_procs._automas_handle = lambda: "handle:32000"
        k.on_process_started()
        warns = rec.at(logging.WARNING)
        line = first(warns[0]) if warns else ""
        check("one WARNING: back, and not by the relay",
              len(warns) == 1 and "现在又在运行了" in line and "不是中继打开的" in line)
        check("marked recovered", [getattr(r, errwatch.RECOVERED, False) for r in rec.records
                                   if r.levelno == logging.WARNING], [True])
        check("not pushed", pushed(rec), [])

        print("\n[an installer run that never comes back: pushed at the REVIVE_ALERT_AFTER-th check]")
        rec, rv, k = run_exit(0, task_list="setup")
        vt = VClock()
        set_time(vt)
        automas_procs._automas_running = lambda: False
        automas_procs._automas_handle = lambda: None
        tasks["list"] = TASKS["setup"]
        try:
            for _ in range(automas_keeper.REVIVE_ALERT_AFTER - 1):
                vt.now = k.revive_deadline + 1
                k.check(False, vt.now)
        finally:
            set_time(orig[1])
        warns = rec.at(logging.WARNING)
        check("one WARNING (not marked recovered)",
              [getattr(r, errwatch.RECOVERED, False) for r in rec.records if r.levelno == logging.WARNING], [False])
        line = first(warns[0]) if warns else ""
        check("it says it has not come back, with the exit and the installer",
              "还没回来" in line and "退出码 0x0" in line and "安装或卸载程序还开着" in line)
        check("it reached the group", len(pushed(rec, 1)), 1)
        check("still no revival while the installer is up", rv + revived, [])
        stop(k)
        check("the stop does not push it a second time", len(rec.at(logging.WARNING)), 1)

        print("\n[the relay's revivals fail: 「🔌 AUTO-MAS 启动不起来」 really fires, with the exit that started it]")
        rec, rv, k = run_exit(0xC0000005)
        vt = VClock()
        set_time(vt)
        automas_procs._automas_running = lambda: False
        automas_procs._automas_handle = lambda: None
        tasks["list"] = TASKS["plain"]
        try:
            for _ in range(automas_keeper.REVIVE_ALERT_AFTER - 1):
                vt.now = k.revive_deadline + 1
                k.check(False, vt.now)
        finally:
            set_time(orig[1])
        calls = k.notifier.calls
        check("one alarm: 🔌 AUTO-MAS 启动不起来, alert=True",
              [(t, a) for t, _, a in calls], [(texts.AUTOMAS_DOWN, True)])
        from ark_relay.core.notify import route_of
        check("that title goes to the group", route_of(texts.AUTOMAS_DOWN, alert=True), "group")
        body = calls[0][1] if calls else ""
        check("its body names the exit that started it", "起因" in body and "0xC0000005" in body)
        check("the revivals up to it were INFO (no WARNING)", rec.at(logging.WARNING), [])
        set_time(vt)
        try:
            vt.now = k.revive_deadline + 1
            k.check(False, vt.now)
        finally:
            set_time(orig[1])
        check("a revival after the alarm is a WARNING again (pushed, as before)",
              len(rec.at(logging.WARNING)), 1)

        print("\n[the deadline passes with no backend (not after an exit): plain WARNING]")
        revived.clear()
        vt = VClock()
        set_time(vt)
        tasks["list"] = TASKS["plain"]
        k, rec = keeper(handle=None)
        automas_procs._automas_running = lambda: False
        automas_procs._automas_handle = lambda: None
        try:
            k.check(False, k.revive_deadline + 1)
        finally:
            set_time(orig[1])
        warns = rec.at(logging.WARNING)
        check("one WARNING", len(warns), 1)
        check("plain Chinese, says what is wrong", bool(warns) and not texts.plain(warns[0])
              and "没在运行" in warns[0], True)
        check("revived", len(revived), 1)

        print("\n[the deadline passes while the relay's own power-off is under way: leave it]")
        revived.clear()
        vt = VClock()
        set_time(vt)
        k, rec = keeper(handle=None)
        relay_poweroff()
        try:
            vt.now = k.revive_deadline + 1
            k.check(False, vt.now)
            wait = k.cap_wait(3600.0)
        finally:
            set_time(orig[1])
            errwatch._stopping.clear()
            errwatch._relay_poweroff[0] = lambda: False
        check("no revival", revived, [])
        check("no WARNING", rec.at(logging.WARNING), [])
        check("and the loop is not woken every second meanwhile", wait >= 60, True)

        print("\n[the keeper's stopping() reaches the WMI listener]")
        stops = []
        k, rec = keeper()
        k.wmi_alive["watch"] = types.SimpleNamespace(stopping=lambda: stops.append(1))
        stop(k)
        check("the listener was told", stops, [1])
        check("nothing pending, nothing said", rec.at(logging.WARNING), [])

        print("\n[the listener found itself broken before _start_process_watch returned]")
        automas_procs._automas_handle = lambda: "handle:1"
        procwatch._start_process_watch = lambda evt, alive, lg: (alive.update(ok=False), True)[1]
        k = automas_keeper._AutomasKeeper(logging.getLogger("ark.test_boot"), Notifier())
        check("the keeper does not overwrite that with 'alive'", k.wmi_alive["ok"], False)

        print("\n[the handle is opened with the right to read the exit code, and without it if refused]")
        automas_procs._automas_handle = orig[5]
        automas_procs._python_processes = lambda: [(21932, r"D:\ark\automas\runtime\python.exe D:\ark\automas\repo\main.py")]
        opened.clear()
        refuse_query[0] = False
        check("got a handle", automas_procs._automas_handle(), "handle:21932")
        check("asked for SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION", opened, [SYNCHRONIZE | 0x1000])
        opened.clear()
        refuse_query[0] = True
        check("refused: still a handle", automas_procs._automas_handle(), "handle:21932")
        check("second try with SYNCHRONIZE alone", opened, [SYNCHRONIZE | 0x1000, SYNCHRONIZE])

        print("\n[清单-1108 A-06: a revived backend is adopted only once its API answers]")
        vt = VClock()
        set_time(vt)
        try:
            k, rec = keeper(handle=None)
            k.revive_failures, k.revive_wait = 2, 720.0
            automas_procs._automas_handle = lambda: "handle:31000"
            api["up"] = False
            k.on_process_started()
            check("process up, API silent: handle held, the revivals still counted",
                  (k.handle, k.revive_failures, k.api_since is not None), ("handle:31000", 2, True))
            check("the loop wakes to ask again", k.cap_wait(3600.0), automas_keeper.API_RECHECK_SECONDS)
            k.check(False, vt.now + 30)
            check("still silent: nothing reset, no WARNING yet", (k.revive_failures, rec.at(logging.WARNING)), (2, []))
            vt.now += automas_keeper.API_GRACE_SECONDS
            k.check(False, vt.now)
            k.check(False, vt.now + 30)
            check("silent past the grace: one WARNING (pushed), said once",
                  [("接口一直没响应" in m) for m in rec.at(logging.WARNING)], [True])
            api["up"] = True
            k.check(False, vt.now + 60)
            check("the API answers: adopted, the revival state reset",
                  (k.revive_failures, k.revive_wait, k.api_since, k.cap_wait(3600.0)),
                  (0, float(automas_keeper.REVIVE_FIRST_WAIT), None, 3600.0))
            api["up"] = False
            k.handle, k.revive_deadline = None, vt.now + 61
            automas_procs._automas_running = lambda: True
            k.check(False, vt.now + 62)
            check("found by the liveness check with the API silent: held, not adopted", k.api_since is not None, True)
            exit_codes["handle:31000"] = 1
            automas_procs._automas_running = lambda: False
            automas_procs._automas_handle = lambda: None
            k.check(True, vt.now + 120)
            check("its exit clears the API wait", (k.api_since, k.api_warned), (None, False))
        finally:
            set_time(orig[1])
            api["up"] = True


        print("\n[清单-1108 A-06: a revival kills the process trees and any leftover backend, and says what schtasks answered]")
        ran = []
        real_run, real_bt = subprocess.run, boot_stages.time
        subprocess.run = lambda cmd, **kw: (ran.append(cmd), types.SimpleNamespace(
            returncode=0x41301 if cmd[:2] == ["schtasks", "/run"] else 0, stdout=b"already running"))[1]
        boot_stages.time = types.SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic, time=time.time)
        automas_procs._python_processes = lambda: [(31000, r"D:\ark\automas\runtime\python.exe D:\ark\automas\repo\main.py"),
                                                   (2, r"C:\python.exe other.py")]
        grab = Records()
        boot_stages.log.addHandler(grab)
        lvl = boot_stages.log.level
        boot_stages.log.setLevel(logging.DEBUG)
        try:
            orig[3]()
        finally:
            subprocess.run, boot_stages.time = real_run, real_bt
            boot_stages.log.removeHandler(grab)
            boot_stages.log.setLevel(lvl)
        check("the shell and the runtime with their children (/T)",
              ran[:2], [["taskkill", "/IM", "AUTO-MAS.exe", "/F", "/T"], ["taskkill", "/IM", "auto-mas-runtime.exe", "/F", "/T"]])
        check("the leftover backend by its pid, nothing else", [c for c in ran if "/PID" in c], [["taskkill", "/PID", "31000", "/F", "/T"]])
        check("schtasks /run's refusal is said with its code", any("0x41301" in m for m in grab.at(logging.INFO)), True)
    finally:
        (errwatch.system_shutting_down, procwatch.time, subprocess.run, boot_stages._revive_automas,
         automas_procs._automas_running, automas_procs._automas_handle, procwatch._start_process_watch,
         automas_procs._python_processes) = orig
        errwatch._stopping.clear()
        for key, v in saved.items():
            if v is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = v


def _part_keeper_hold_once():
    """A hold that lasts is said at WARNING once, not at every check (review of bd80586d, 2026-10-13).

bd80586d stopped doubling revive_wait when a check revived nothing, so a hold
(an installer on screen, or the program list unreadable) re-armed at 180 s for as
long as it lasted, and each check logged its hold line at WARNING through `say`,
which errwatch pushes to the group: 40 pushes in 2 hours against 8 before (when
every check doubled the wait). Now the hold keeps the 180 s check and is said at
WARNING the first time, at INFO while it lasts; a real revival says it again.

    Formerly test_keeper_hold_once.py.
    """
    import logging
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                  "win32evtlog", "win32gui"):
        sys.modules.setdefault(_name, _Stub(_name))

    import time

    import boot_stages
    from ark_relay.features.host import automas_keeper, automas_procs, procwatch
    from ark_relay.features.phone import commands


    clock = [1000.0]
    time.monotonic = lambda: clock[0]
    automas_procs._python_processes = lambda: []
    commands.mas_up = lambda: False
    automas_procs._automas_shell_running = lambda: False
    procwatch._start_process_watch = lambda evt, alive, log: True
    revives = []
    boot_stages._revive_automas = lambda: revives.append(clock[0])


    class _Keep(logging.Handler):
        def __init__(self):
            super().__init__()
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, record.getMessage()))


    keep = _Keep()
    log = automas_keeper.log
    log.addHandler(keep)
    log.setLevel(logging.INFO)


    class _Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, *a, **k):
            self.sent.append(title)


    OLD_COUNT = 8   # before bd80586d: checks at 180, 540, 1260, 2700, 4500, 6300 s ... within 2 hours


    def two_hours(label, installer, hint):
        print(f"[{label}：两小时只报一次]")
        automas_procs._installer_running = lambda: installer
        revives.clear()
        clock[0] += 100000.0
        k = automas_keeper._AutomasKeeper(log, _Notifier())
        keep.rows.clear()
        checks = 0
        start = clock[0]
        while clock[0] - start < 2 * 3600:
            clock[0] = k.revive_deadline
            k.check(False, clock[0])
            checks += 1
        warned = [m for lv, m in keep.rows if lv == "WARNING" and hint in m]
        infos = [m for lv, m in keep.rows if lv == "INFO" and hint in m]
        check(f"{label}: still checked every 180 s", checks >= 40, True)
        check(f"{label}: nothing revived", revives, [])
        check(f"{label}: WARNINGs at most the old count ({OLD_COUNT})", len(warned) <= OLD_COUNT, True)
        check(f"{label}: one WARNING", len(warned), 1)
        check(f"{label}: the rest at INFO", len(infos), checks - 1)
        return k


    two_hours("安装程序开着", True, "安装程序正在运行")
    k = two_hours("读不到程序列表", None, "读不到正在运行的程序列表")

    print("[拦着之后真拉起过、又拦住：再说一次]")
    automas_procs._installer_running = lambda: False
    clock[0] = k.revive_deadline
    k.check(False, clock[0])
    check("revived once", len(revives), 1)
    automas_procs._installer_running = lambda: True
    keep.rows.clear()
    for _ in range(3):
        clock[0] = k.revive_deadline
        k.check(False, clock[0])
    check("a new hold after a revival: one WARNING",
          [lv for lv, m in keep.rows if "安装程序正在运行" in m], ["WARNING", "INFO", "INFO"])


def _part_stop_during_boot():  # noqa: C901

    import logging
    import sys
    import threading
    import time
    import types
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages
    import service
    from _tmp import tmpdir
    from ark_relay.features.alarm import errwatch

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
        if not ok:
            fails.append(label)


    STAGES = ("selfupdate", "flush_copies", "patch_okww", "automas_jobfix", "backfill_manual_stops", "announce_update",
              "evidence_sources", "inbox_and_phone", "stagegate", "selfcheck", "preupdate",
              "reenable_maaend", "collect_watch", "gameupdate", "annihilation", "machinecheck")


    def boot(stop_during: str | None, updated: bool = False) -> list[str]:
        """Run service.main with every boot step recorded; `stop_during` asks for a
    stop while that step runs (as SvcStop does from another thread); `updated`
    makes the self-update find new code (the outgoing process returns)."""
        ran: list[str] = []
        svc = service.ArkRelayService.__new__(service.ArkRelayService)
        svc._stop_asked = threading.Event()

        def step(name):
            def run(*_a, **_k):
                ran.append(name)
                if name == stop_during:
                    svc._stop_asked.set()
                if name == "selfupdate":
                    return updated
                if name == "inbox_and_phone":
                    return None, None, None
                return None
            return run

        saved = {}
        for name in STAGES:
            saved[name] = getattr(boot_stages, f"_stage_{name}", None)
            setattr(boot_stages, f"_stage_{name}", step(name))
        real_bootstrap, real_net, real_loop = boot_stages._stage_bootstrap, service._wait_for_network, service._loop
        # cfg: only state_dir is read outside the recorded steps (_stage_announce_update's argument).
        boot_stages._stage_bootstrap = lambda: (logging.getLogger("ark.test"), types.SimpleNamespace(state_dir=None),
                                                None, None)
        service._wait_for_network = lambda log: None
        service._loop = lambda *a, **k: ran.append("loop")
        try:
            svc.main()
        finally:
            for name, fn in saved.items():
                if fn is None:
                    delattr(boot_stages, f"_stage_{name}")
                else:
                    setattr(boot_stages, f"_stage_{name}", fn)
            boot_stages._stage_bootstrap, service._wait_for_network, service._loop = \
                real_bootstrap, real_net, real_loop
        return ran


    print("[no stop: every boot step, then the main loop]")
    check("steps", boot(None), list(STAGES) + ["loop"])

    print("[stop during the update announcement (the smoke's case): nothing after it]")
    check("steps", boot("announce_update"), list(STAGES[:STAGES.index("announce_update") + 1]))

    print("[stop during patch_okww: nothing after it]")
    check("steps", boot("patch_okww"), list(STAGES[:STAGES.index("patch_okww") + 1]))

    print("[stop during the self-update: not even the OK-WW overrides]")
    check("steps", boot("selfupdate"), ["selfupdate"])

    print("[self-update found new code: the outgoing process flushes and patches nothing]")
    # relay.log 10-05 21:20:19 / 21:20:27: the same 🩹 note from the outgoing and the
    # new process, 8 s apart (audit s23 F3).
    check("steps", boot(None, updated=True), ["selfupdate"])

    print("[stop during the inbox step: no stage gate, no pre-update, no loop]")
    check("steps", boot("inbox_and_phone"), list(STAGES[:STAGES.index("inbox_and_phone") + 1]))


    print("[errwatch: close() ends the push thread inside a retry backoff]")


    class Refused:
        def __init__(self):
            self.tries = threading.Event()

        def send(self, title, body, **k):
            self.tries.set()
            return ["企业微信机器人: refused"]


    notifier = Refused()
    h = errwatch.ErrorKindAlert(notifier, state_dir=tmpdir(), known={}, retry=(30.0,))
    lg = logging.getLogger("ark.test.stopwake")
    lg.propagate = False
    lg.addHandler(h)
    lg.warning("something went wrong")
    check("first push tried", notifier.tries.wait(5), True)
    sender = h._sender
    time.sleep(0.2)                     # into the 30 s backoff
    t0 = time.monotonic()
    h.close()
    sender.join(5)
    check("push thread gone after close()", sender.is_alive(), False)
    check("close() woke it in under 2 s", time.monotonic() - t0 < 2, True)
    check("record still queued for the next start", len(h.pending()), 1)
    lg.removeHandler(h)


    print("[stop during the boot pre-update (10-16 02:35): no OK-WW launch, no mark_run, no alarm]")
    # 2026-10-16 02:35: a deploy rollback stopped the relay mid pre-update. A stop that only
    # ended the AUTO-MAS wait would go straight on to launch OK-WW (boot_stages forbids a
    # stopping process to start programs), and a pre-update cut short must be neither marked
    # done nor reported as 「没能确认」: the next boot runs it again.
    from ark_relay.features.okww_patch import okww_overlay
    from ark_relay.features.phone import commands
    from ark_relay.features.preupdate import preupdate


    class _Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **k):
            self.sent.append((title, k.get("alert", False)))
            return []


    def preupdate_stage(stop_in: str, notes_first: bool = False):
        """Run _stage_preupdate with every program step faked; `stop_in` names the step during
    which SvcStop arrives ("automas", "okww" or "" for none). Returns what ran."""
        ran: list[str] = []
        cfg = types.SimpleNamespace(automas_dir=Path("automas"), okww_dir=Path("okww"),
                                    state_dir=Path("state-never-written"))
        notifier = _Notifier()

        def automas(*_a, problems=None, **_k):
            ran.append("automas")
            if notes_first:
                problems.append("AUTO-MAS 预更新：等了 180 秒仍问不到更新状态，**没有检查更新**")
            if stop_in == "automas":
                errwatch.mark_stopping()
            return ""

        def okww(*_a, problems=None, **_k):
            ran.append("okww")
            if stop_in == "okww":
                errwatch.mark_stopping()
            return ""
        saved = (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run, preupdate.run_automas,
                 preupdate.run_okww, commands.mas_up, okww_overlay.retry_pending, okww_overlay.drift_line,
                 boot_stages._seconds_to_next_queue)
        preupdate.wanted_today = lambda *a, **k: True
        preupdate.should_run = lambda *a, **k: True
        preupdate.mark_run = lambda *a, **k: ran.append("mark_run")
        preupdate.run_automas = automas
        preupdate.run_okww = okww
        commands.mas_up = lambda *a, **k: True
        okww_overlay.retry_pending = lambda *a, **k: ran.append("retry_pending")
        okww_overlay.drift_line = lambda *a, **k: ran.append("drift_line") and ""
        boot_stages._seconds_to_next_queue = lambda *a, **k: 10 * 3600.0   # room for a second try
        # win32api is stubbed above, so GetSystemMetrics would read as "Windows is going down".
        real_shutting, errwatch.system_shutting_down = errwatch.system_shutting_down, lambda: False
        try:
            boot_stages._stage_preupdate(cfg, notifier, logging.getLogger("ark.test_boot"))
        finally:
            (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run, preupdate.run_automas,
             preupdate.run_okww, commands.mas_up, okww_overlay.retry_pending, okww_overlay.drift_line,
             boot_stages._seconds_to_next_queue) = saved
            errwatch._stopping.clear()
            errwatch.system_shutting_down = real_shutting
        return ran, [t for t, alert in notifier.sent if alert]


    ran, alarms = preupdate_stage("")
    check("no stop: both items, overrides, mark_run", ran, ["automas", "okww", "retry_pending", "drift_line", "mark_run"])
    ran, alarms = preupdate_stage("automas")
    check("(d) stop during the AUTO-MAS item: OK-WW never launched, no mark_run", ran, ["automas"])
    check("(d) no alarm", alarms, [])
    ran, alarms = preupdate_stage("okww")
    check("(e) stop during the OK-WW item: no override writes, no mark_run", ran, ["automas", "okww"])
    check("(e) no alarm", alarms, [])
    ran, alarms = preupdate_stage("automas", notes_first=True)
    check("a stopping relay gives an item no second try, and says nothing", (ran, alarms), (["automas"], []))


    print("[a stop during the second try is not a verdict: no recovered (self-fixed) line]")


    class _Records(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.got = []

        def emit(self, record):
            self.got.append((record.levelname, bool(getattr(record, errwatch.RECOVERED, False))))


    def once_more_stopped_on_retry():
        """Try 1 leaves a note; SvcStop arrives during try 2, which returns no note."""
        tries = []

        def step(problems):
            tries.append(1)
            if len(tries) == 1:
                problems.append("OK-WW 预更新：拿不到控制台会话，**没有检查更新**")
            else:
                errwatch.mark_stopping()
            return ""

        log = logging.getLogger("ark.test_boot")
        rec = _Records()
        log.addHandler(rec)
        saved = boot_stages._seconds_to_next_queue, errwatch.system_shutting_down
        boot_stages._seconds_to_next_queue = lambda *a, **k: 10 * 3600.0   # room for a second try
        errwatch.system_shutting_down = lambda: False
        problems: list[str] = []
        try:
            boot_stages._once_more(types.SimpleNamespace(automas_dir=Path("automas")), log, "OK-WW",
                                   240.0, problems, step)
        finally:
            boot_stages._seconds_to_next_queue, errwatch.system_shutting_down = saved
            errwatch._stopping.clear()
            log.removeHandler(rec)
        return len(tries), [r for r in rec.got if r[0] == "WARNING" or r[1]]


    tries, warned = once_more_stopped_on_retry()
    check("the retry ran (the stop came during it)", tries, 2)
    check("no WARNING and no recovered-tagged line", warned, [])


    print("[every boot puts back a switch a killed pre-update left off]")
    from ark_relay.features.preupdate import preupdate_okww
    asked = []
    saved = (preupdate_okww.restore_autostart_leftover, okww_overlay.install, okww_overlay.write_master_pointer,
             okww_overlay.report_line, okww_overlay.drift_line)
    preupdate_okww.restore_autostart_leftover = lambda okww, state: asked.append((okww, state)) or ""
    okww_overlay.install = okww_overlay.write_master_pointer = lambda *a, **k: ""
    okww_overlay.report_line = okww_overlay.drift_line = lambda *a, **k: ""
    try:
        boot_stages._stage_patch_okww(types.SimpleNamespace(automas_dir=None, okww_dir=Path("okww"), state_dir=Path("st")),
                                      _Notifier(), logging.getLogger("ark.test_boot"))
    finally:
        (preupdate_okww.restore_autostart_leftover, okww_overlay.install, okww_overlay.write_master_pointer,
         okww_overlay.report_line, okww_overlay.drift_line) = saved
    check("_stage_patch_okww restores from the record", asked, [(Path("okww"), Path("st"))])

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_smoke_boot_lines():
    import subprocess
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import fx_dir, tmpdir

    ROOT = Path(__file__).resolve().parents[2]
    SMOKE = ROOT / "scripts" / "windows" / "smoke.py"
    FIX = fx_dir(Path(__file__), "fixtures") / "relay-0909-boot-smoke.log"

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
        if not ok:
            fails.append(label)


    def run(log_text: str) -> str:
        work = tmpdir()
        # The script's DATA, given with --data. Until 10-13 it was a relative folder named
        # C:\ProgramData\ark-relay under the cwd, which on Windows is the real absolute
        # folder: the first run wrote the runner's own ProgramData, the second failed with
        # FileExistsError (run 38360295330).
        data = work / "data"
        data.mkdir()
        (data / "relay.log").write_text(log_text, encoding="utf-8")
        code = work / "code"
        (code / "ark_relay").mkdir(parents=True)
        (code / "ark_relay" / "__init__.py").write_text("", encoding="utf-8")
        r = subprocess.run([sys.executable, "-X", "utf8", str(SMOKE), f"--root={code}", f"--data={data}"],
                           cwd=work, capture_output=True, text=True, encoding="utf-8", timeout=60)
        return r.stdout


    lines = FIX.read_text(encoding="utf-8").splitlines()
    boot = next(i for i, ln in enumerate(lines) if "服务模式启动" in ln)
    since_boot = len(lines) - boot

    print("[09-09 12:57:24: more than 60 lines since the start]")
    check("the fixture has more than 60 lines from the start on", since_boot > 60, True)
    out = run(FIX.read_text(encoding="utf-8"))
    check("every line from the start on is read", f"SMOKE 启动后日志 {since_boot} 行" in out, True)
    check("the start-time failure one line after the start is reported",
          "启动后日志里有报错：09-09 12:57:24 ERROR   ark.service  启动时贴 OK-WW 补丁失败" in out, True)
    check("the previous process's error (12:57:20, before the start) is not",
          "09-09 12:57:20" in out, False)
    check("so the smoke fails", "SMOKE_FAIL" in out, True)

    print("\n[no start line in the file: the last 60 lines, as before]")
    out = run("\n".join(ln for ln in lines if "服务模式启动" not in ln) + "\n")
    check("60 lines read", "SMOKE 启动后日志 60 行" in out, True)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_update_announce_main():
    """Cover the "tell me the moment an update takes effect" path.

The tricky case is the first update after this feature ships: the process that
applies it is running the old code and cannot leave a marker, so the
announcement has to be derivable from the version file alone.

    Formerly test_update_announce.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.selfupdate import selfupdate as su


    def fresh():
        root = tmpdir()
        (root / "state").mkdir()
        return root

    print("[first update ever - old code applied it, left no marker]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260821200000")
    n = su.pending_announcement(r)
    check("announces", bool(n), True)
    check("version", n and n["version"], 20260821200000)
    check("no file list", n and n["files"], [])
    check("second boot is silent", su.pending_announcement(r), None)

    print("\n[normal update - marker carries the file list]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260822090000")
    (r / "state" / "announced-version.txt").write_text("20260821200000")
    su._record_announcement(r, {"version": 20260822090000, "previous": 20260821200000,
                                "files": ["ark_relay/core/engine.py"], "at": "2026-08-22T09:00:00+08:00"})
    n = su.pending_announcement(r)
    check("file list survives", n and n["files"], ["ark_relay/core/engine.py"])
    check("previous version", n and n["previous"], 20260821200000)
    check("not repeated", su.pending_announcement(r), None)

    print("\n[no update - must stay silent]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260822090000")
    (r / "state" / "announced-version.txt").write_text("20260822090000")
    check("silent", su.pending_announcement(r), None)

    print("\n[corrupt marker must not crash or block]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260822090000")
    (r / "state" / "announced-version.txt").write_text("20260821200000")
    (r / "state" / "update-announce.json").write_text("{not json")
    n = su.pending_announcement(r)
    check("falls back to version comparison", bool(n), True)
    check("corrupt marker removed", (r / "state" / "update-announce.json").exists(), False)

    print("\n[no version file at all - fresh install, nothing to say]")
    r = fresh()
    check("silent", su.pending_announcement(r), None)

    print("\n[failure is announced too - a silent one leaves old code running]")
    r = fresh()
    su._record_failure(r, "缓存未刷新", 20260821113000, 20260821111012,
                       ["ark_relay/core/engine.py", "ark_relay/core/ledger.py"])
    f = su.take_failure(r)
    check("reported", bool(f), True)
    check("reason", f and f["reason"], "缓存未刷新")
    check("file list", f and f["files"], ["ark_relay/core/engine.py", "ark_relay/core/ledger.py"])
    check("count", f and f["count"], 2)
    check("not repeated", su.take_failure(r), None)

    print("\n[a later success clears the stale complaint]")
    r = fresh()
    su._record_failure(r, "x", 1, 2, ["a.py"])
    su._clear_failure(r)
    check("cleared", su.take_failure(r), None)

    print("\n[corrupt failure marker is removed, not retried forever]")
    r = fresh()
    (r / "state" / "update-failed.json").write_text("{broken")
    check("returns nothing", su.take_failure(r), None)
    check("file removed", (r / "state" / "update-failed.json").exists(), False)

    print("\n[failure and success markers are independent]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260822090000")
    su._record_failure(r, "x", 1, 2, ["a.py"])
    check("failure present", bool(su.take_failure(r)), True)
    check("announcement still works", bool(su.pending_announcement(r)), True)

    print("\n[raw gets a timeout above its measured median]")
    check("RAW_TIMEOUT > 38s median", su.RAW_TIMEOUT > 38, True)


def _part_update_announce_dedup():
    """The same change deployed twice must not be pushed twice.

A deploy refused by a gate, fixed, and deployed again is two versions but one
change. On 2026-09-09 the user got the same paragraph twice inside five minutes
and asked why. The version number differs every time, so it cannot be the test;
what he reads is the release notes, so those are what gets compared.

    Formerly test_update_announce_dedup.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.statestore import StateStore


    root = tmpdir()
    (root / "state").mkdir()
    st = StateStore(root / "state")

    print("[「上一条推送的说明」是个正经登记字段，写得进也读得回]")
    check("一开始是空的", st.get("versions", "announced_notes"), None)
    st.set("versions", "announced_notes", "- 改了甲\n- 改了乙")
    check("换个实例读得回", StateStore(root / "state").get("versions", "announced_notes"),
          "- 改了甲\n- 改了乙")

    print("\n[判据就是原文相等：一样不推，改一个字就推]")
    last = StateStore(root / "state").get("versions", "announced_notes")
    check("一模一样 → 不推", "- 改了甲\n- 改了乙" == last, True)
    check("多一行 → 推", "- 改了甲\n- 改了乙\n- 改了丙" == last, False)
    check("空说明不参与比较（回退到列文件名那条路）", bool("") and "" == last, False)

    print("\n[开机那一段真的用了这个字段，而不是只登记不看]")
    boot = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
    check("读了它", 'get("versions", "announced_notes")' in boot, True)
    check("推成功之后才写", 'set("versions", "announced_notes", notes)' in boot, True)
    check("跳过时仍然记下版本号，免得下次又当成新的",
          "_remember_announced(HERE, int(note.get(\"version\") or 0))" in boot, True)


def _part_announce_update_log():
    """The update announcement says 「更新说明已记入当天日报」 only when it recorded them (audit s23 F6, 10-13).

boot_stages._stage_announce_update logged that line whenever the 🔄 send returned no
errors - and 🔄 is log-only (notify.route_of), so always - even with no
RELEASE-NOTES.md text, when nothing was handed to the daily report. relay/RELEASE-NOTES.md
is 0 bytes between deploys, so the empty case is live. The failed-send branch could no
longer happen and is gone.

    Formerly test_announce_update_log.py.
    """
    import logging

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import boot_stages
    from ark_relay.features.report import report
    from ark_relay.features.selfupdate import selfupdate


    class Lines(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **k):
            self.sent.append(title)
            return []


    def announce(notes_text: "str | None"):
        """One announcement of version 123 from a code folder whose RELEASE-NOTES.md holds
    `notes_text` (None: no file). Returns (log lines, notes handed to the daily report)."""
        here = tmpdir()
        (here / "state").mkdir()
        if notes_text is not None:
            (here / "RELEASE-NOTES.md").write_text(notes_text, encoding="utf-8")
        kept = []
        saved = (boot_stages.HERE, selfupdate.take_failure, selfupdate.pending_announcement,
                 report.remember_change)
        boot_stages.HERE = here
        selfupdate.take_failure = lambda root: None
        selfupdate.pending_announcement = lambda root: {"files": ["a.py"], "version": "123", "at": ""}
        report.remember_change = lambda state_dir, notes, version="", day=None: kept.append(notes)
        lines = Lines()
        lg = logging.getLogger("ark.test_boot")
        lg.addHandler(lines)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        try:
            boot_stages._stage_announce_update(Notes(), lg, here / "state")
        finally:
            (boot_stages.HERE, selfupdate.take_failure, selfupdate.pending_announcement,
             report.remember_change) = saved
            lg.removeHandler(lines)
        return lines.lines, kept


    print("[no RELEASE-NOTES.md text: nothing goes to the daily report, and the log does not say it did]")
    for text in ("", None):
        lines, kept = announce(text)
        check(f"notes {text!r}: nothing recorded", kept, [])
        check(f"notes {text!r}: no 「已记入当天日报」 line", any("已记入当天日报" in m for m in lines), False)
        check(f"notes {text!r}: says there were no notes", any("没有更新说明" in m for m in lines), True)

    print("[notes present: recorded, and said so]")
    lines, kept = announce("- 修好了一件事。")
    check("recorded", kept, ["- 修好了一件事。"])
    check("the 「已记入当天日报」 line", any(m == "更新说明已记入当天日报（v123）" for m in lines), True)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_boot_backend_wait, _part_boot_config_alarm, _part_boot_restore_recovered, _part_keeper_blind_backoff, _part_keeper_exit, _part_keeper_hold_once, _part_stop_during_boot, _part_smoke_boot_lines, _part_update_announce_main, _part_update_announce_dedup, _part_announce_update_log]))
