"""Boot: waiting for the backend, the config alarm, recovered restores; and waking the display while Endfield starts.

One part per former file, each run on its own (tests/_parts.py): test_boot_backend_wait.py, test_boot_config_alarm.py, test_boot_restore_recovered.py.
"""
from __future__ import annotations

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
                         has_module=lambda m: True, **kw)


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


if __name__ == "__main__":
    sys.exit(run_parts([_part_boot_backend_wait, _part_boot_config_alarm, _part_boot_restore_recovered]))
