"""AUTO-MAS: the backend match, one alarm at boot, its revival, the contract watch, the hand-over.

One part per former file, each run on its own (tests/_parts.py): test_automas_backend_match.py, test_automas_boot_one_alarm.py, test_automas_boot_revival.py, test_automas_contract_watch.py, test_automas_handover.py.
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


def _part_automas_backend_match():
    """Only AUTO-MAS's own main.py is the backend; a failed OpenProcess tries the next match (audit s15 #3).

_automas_running / _automas_handle took any python.exe with "main.py" on its command
line. OK-WW runs `D:\\ark\\okww\\data\\apps\\ok-ww\\working\\main.py`
(tests/fixtures/okww_argv_20261012.log, ok-script.2026-10-12.log line 1) and may run
as python.exe (preupdate_okww.py). Then a dead backend read as alive while OK-WW ran
(nothing revived), and with no handle held an OK-WW start was adopted as the backend
(its exit logged as 「AUTO-MAS 后台意外退出了」). And the first match whose OpenProcess
failed ended the search, so a live backend listed after it was never attached.

The backend's command line as WMI returned it on the machine (2026-10-10, see
test_procs.py): `D:\\ark\\automas\\runtime\\environment\\venv\\Scripts\\python.exe main.py`.

    Formerly test_automas_backend_match.py.
    """
    import ast
    import re
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
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))

    from ark_relay.features.host import automas_procs
    from ark_relay.features.phone import commands


    line = (Path(__file__).parent / "fixtures" / "okww_argv_20261012.log").read_text(encoding="utf-8")
    okww_script = ast.literal_eval(re.search(r"(\[.*?\])", line).group(1))[0]
    OKWW = rf"D:\ark\okww\data\apps\ok-ww\python\python.exe {okww_script}"
    BACKEND = r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"
    check("record: OK-WW runs a main.py", okww_script.endswith("main.py"), True)

    commands.mas_up = lambda: (_ for _ in ()).throw(AssertionError("the list was readable"))

    print("[后台没在跑、只有鸣潮脚本在跑：不算后台在跑]")
    automas_procs._python_processes = lambda: [(25244, OKWW)]
    check("_automas_running", automas_procs._automas_running(), False)
    opened = []


    def _open(access, inherit, pid):
        opened.append(pid)
        return f"handle:{pid}"


    automas_procs.win32api.OpenProcess = _open
    check("_automas_handle does not adopt OK-WW", automas_procs._automas_handle(), None)
    check("OK-WW's pid never opened", opened, [])

    print("[后台在跑：认得出]")
    automas_procs._python_processes = lambda: [(25244, OKWW), (5088, BACKEND)]
    check("_automas_running", automas_procs._automas_running(), True)
    check("_automas_handle takes the backend", automas_procs._automas_handle(), "handle:5088")
    automas_procs._python_processes = lambda: [(6000, "d:/ARK/AutoMAS/repo/Main.py")]
    check("forward slashes and case do not matter", automas_procs._automas_running(), True)

    print("[第一个匹配打不开：接着试下一个]")
    opened.clear()


    def _open_second(access, inherit, pid):
        opened.append(pid)
        if pid == 4100:
            raise OSError("access denied / gone")
        return f"handle:{pid}"


    automas_procs.win32api.OpenProcess = _open_second
    automas_procs._python_processes = lambda: [(4100, BACKEND), (5088, BACKEND)]
    check("the second match is attached", automas_procs._automas_handle(), "handle:5088")


def _part_automas_boot_one_alarm():  # noqa: C901 - the whole body of the file this part was
    """One AUTO-MAS start failure at boot is one group message (audit s23 F2, 10-13).

Before: ensure_automas logged 「AUTO-MAS 拉起后 120 秒内接口仍不通」 as a plain ERROR
(errwatch pushes it: 🩺), then the boot caller phone_channel._start_phone_channel sent
「🔌 AUTO-MAS 启动不起来」 for the same fault; on the morning boot _stage_preupdate
called ensure_automas() again - another 150 s wait, kill, 120 s wait and the same
ERROR (a second 🩺) - before its own 「预更新没能确认」. Last real cases: 09-04 22:49:26
and 09-17 21:21:28.

Now the boot caller hands ensure_automas the notifier: 🔌 goes out and the ERROR line
is marked as already in the group (errwatch.group_pushed). The pre-update asks
mas_up() and, when AUTO-MAS is still not answering, skips its AUTO-MAS item with one
problem line instead of waiting again; OK-WW's item does not need AUTO-MAS and runs.

    Formerly test_automas_boot_one_alarm.py.
    """
    import logging
    import time
    import types
    from datetime import datetime, timezone

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
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                 "win32com", "win32com.client"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages
    from ark_relay.core import texts
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.okww_patch import okww_overlay
    from ark_relay.features.phone import commands, phone, phone_channel
    from ark_relay.features.preupdate import preupdate


    class Records(logging.Handler):
        """Every record under the "ark" logger, as errwatch sees them."""

        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.recs: list[logging.LogRecord] = []

        def emit(self, record):
            self.recs.append(record)

        def pushed_by_errwatch(self) -> list[str]:
            """WARNING / ERROR lines errwatch would push: not marked as already in the group."""
            return [r.getMessage() for r in self.recs if r.levelno >= logging.WARNING
                    and not getattr(r, errwatch.PUSHED, False) and not getattr(r, errwatch.RECOVERED, False)]


    class Notes:
        def __init__(self):
            self.sent: list[tuple[str, bool]] = []

        def send(self, title, body="", **kw):
            self.sent.append((title, bool(kw.get("alert"))))
            return []

        def went_to_group(self):
            return True

        def alarms(self) -> list[str]:
            return [t for t, alert in self.sent if alert]


    REC = Records()
    ARK = logging.getLogger(errwatch.ARK)
    ARK.addHandler(REC)
    ARK_LEVEL = ARK.level
    ARK.setLevel(logging.DEBUG)

    # AUTO-MAS never answers; a fake clock so the 120 s wait costs nothing.
    clock = {"t": 0.0}
    real_sleep, real_monotonic = boot_stages.time.sleep, boot_stages.time.monotonic
    saved = (commands.mas_up, boot_stages.shell_running, boot_stages._revive_automas,
             boot_stages._stop_requested, phone.Mailbox, phone.Heartbeat, phone.state_payload,
             phone_channel._make_phone_cmd)


    def advance(s):
        clock["t"] += s


    class FakeBox:
        def __init__(self, topic, pin, state_dir, cos=None):
            self.topic, self.cos, self.enabled = topic, cos, True
            self.quota = phone.Quota(state_dir)
            self.last_error = ""

        def publish(self, body):
            return True

        def fetch(self):
            return []

        def listen(self, on_cmd, stop, **kw):
            pass


    class FakeHb:
        def __init__(self, *a, **k): pass
        def loop(self, stop): return None
        def watch(self): pass


    def fake_make_phone_cmd(*a, **k):
        def run(body):
            pass
        run.drain = lambda: None
        return run


    try:
        boot_stages.time.sleep = advance
        boot_stages.time.monotonic = lambda: clock["t"]
        commands.mas_up = lambda: False
        boot_stages.shell_running = lambda: False
        boot_stages._revive_automas = lambda: None
        boot_stages._stop_requested = lambda: False
        phone.Mailbox, phone.Heartbeat = FakeBox, FakeHb
        phone.state_payload = lambda cfg, state_dir: {"at": 1}
        phone_channel._make_phone_cmd = fake_make_phone_cmd

        print("[boot: AUTO-MAS does not come up after the revival]")
        sd = tmpdir()
        cfg = types.SimpleNamespace(phone_topic="topic-abc", phone_pin="8964", state_dir=sd,
                                    cos_secret_id="", cos_secret_key="", cos_bucket="", cos_region="")
        engine = types.SimpleNamespace(scripts_running=lambda: False, _started_at=datetime.now(timezone.utc))
        notes = Notes()
        log = logging.getLogger("ark.test_automas")
        phone_channel._start_phone_channel(types.SimpleNamespace(stop_event=None), cfg, engine, notes, log)
        time.sleep(0.05)               # the listener thread
        # Only the AUTO-MAS ones: the fake state payload fails a machine check of its own.
        down = [t for t in notes.alarms() if "AUTO-MAS" in t]
        loud = [m for m in REC.pushed_by_errwatch() if "AUTO-MAS" in m]
        check("the 🔌 alarm went out once", down, [texts.AUTOMAS_DOWN])
        check("errwatch has nothing more to push for it", loud, [])
        check("so the group gets one message", len(down) + len(loud), 1)
        check("the ERROR line is still in relay.log (selfcheck reads 「秒内…仍不通」)",
              any("秒内接口仍不通" in r.getMessage() for r in REC.recs), True)

        print("[the morning pre-update right after: no second wait, one problem line]")
        REC.recs.clear()
        ensured: list[int] = []
        real_ensure = boot_stages.ensure_automas
        boot_stages.ensure_automas = lambda *a, **k: ensured.append(1) or real_ensure(*a, **k)
        asked = {"automas": 0, "okww": 0}

        def run_automas(*a, problems=None, **k):
            asked["automas"] += 1
            problems.append("AUTO-MAS 预更新：接口不通，没查到版本")
            return ""

        def run_okww(*a, problems=None, **k):
            asked["okww"] += 1
            return ""

        saved_pre = (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run,
                     preupdate.run_automas, preupdate.run_okww, okww_overlay.retry_pending,
                     okww_overlay.drift_line, boot_stages._seconds_to_next_queue)
        preupdate.wanted_today = lambda *a, **k: True
        preupdate.should_run = lambda *a, **k: True
        marks: list[bool] = []
        preupdate.mark_run = lambda state_dir, now, clean: marks.append(clean)
        preupdate.run_automas, preupdate.run_okww = run_automas, run_okww
        okww_overlay.retry_pending = lambda *a, **k: None
        okww_overlay.drift_line = lambda *a, **k: ""
        boot_stages._seconds_to_next_queue = lambda automas_dir, now: 3600.0
        t0 = clock["t"]
        notes = Notes()
        pcfg = types.SimpleNamespace(automas_dir=None, okww_dir=Path("okww"), state_dir=None)
        try:
            boot_stages._stage_preupdate(pcfg, notes, log)
        finally:
            (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run,
             preupdate.run_automas, preupdate.run_okww, okww_overlay.retry_pending,
             okww_overlay.drift_line, boot_stages._seconds_to_next_queue) = saved_pre
            boot_stages.ensure_automas = real_ensure
        check("no second ensure_automas", ensured, [])
        check("no second 150 + 120 s wait", clock["t"] - t0, 0.0)
        check("the AUTO-MAS item is skipped, OK-WW still runs", asked, {"automas": 0, "okww": 1})
        check("no second 「仍不通」 ERROR", any("仍不通" in r.getMessage() for r in REC.recs), False)
        unconfirmed = [t for t in notes.alarms() if t.startswith(texts.unconfirmed("预更新", 1)[:6])]
        check("one 「没能确认」 alarm with one line", unconfirmed, [texts.unconfirmed("预更新", 1)])
        check("the day's pre-update is not clean (tried again next boot)", marks, [False])
    finally:
        boot_stages.time.sleep, boot_stages.time.monotonic = real_sleep, real_monotonic
        (commands.mas_up, boot_stages.shell_running, boot_stages._revive_automas,
         boot_stages._stop_requested, phone.Mailbox, phone.Heartbeat, phone.state_payload,
         phone_channel._make_phone_cmd) = saved
        ARK.removeHandler(REC)
        ARK.setLevel(ARK_LEVEL)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_automas_boot_revival():
    """The boot-time revival must wait for a shell that is already starting, kill the
runtime as well when it does restart, and the keeper must not go blind without wmic.

Real sequence, 2026-09-17 21:20 (first evening boot after AUTO-MAS v5.5.0-beta.6):
21:20:28 the logon task starts AUTO-MAS.exe, which begins its bootstrap
(repo sync, managed Python, locked dependencies); 21:20:39 the relay finds no
API, runs `taskkill /IM AUTO-MAS.exe` at once, `schtasks /run`; the bootstrap
child `auto-mas-runtime.exe` (pid 19116) survives and keeps the environment
lock; 21:20:45 the new shell fails with MUTATION_IN_PROGRESS and parks on
「等待用户处理」; 21:21:28 the relay gives up after 45 s with one ERROR line and
no alarm; the keeper (wmic gone since 25H2) reads "cannot tell" as alive and
never tries again; 21:30 the queue does not run; 21:55 「该跑没跑」.

    Formerly test_automas_boot_revival.py.
    """
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


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                 "win32com", "win32com.client"):
        sys.modules.setdefault(name, _Stub(name))

    import logging

    import boot_stages
    import service
    from ark_relay.features.host import automas_procs
    from ark_relay.features.phone import commands
    from ark_relay.features.alarm import errwatch
    from ark_relay.core import texts


    # boot_stages.time is the time module itself: put both back at the end, or every
    # test the coverage driver runs after this one in the same process sees a frozen
    # clock (10-05: gameupdate_games.update_wuwa's 40-minute wait never ended).
    _real_sleep, _real_monotonic = boot_stages.time.sleep, boot_stages.time.monotonic
    boot_stages.time.sleep = lambda s: None
    clock = {"t": 0.0}
    boot_stages.time.monotonic = lambda: clock["t"]


    def _tick(seconds):
        """Every sleep(3) inside _wait_for_api advances the fake clock."""
        def sleep(s):
            clock["t"] += s
        boot_stages.time.sleep = sleep


    _tick(3)
    # The win32 stubs above answer every call with a truthy object, which would make
    # errwatch.system_shutting_down() read "going down"; the stop signal is driven
    # explicitly by the cases below.
    boot_stages._stop_requested = lambda: False
    revived = []
    boot_stages._revive_automas = lambda: revived.append(clock["t"])


    class _Levels(logging.Handler):
        """ensure_automas's lines (logger ark.service): (level, first line, marked recovered)."""

        def __init__(self):
            super().__init__(logging.DEBUG)
            self.got = []

        def emit(self, record):
            self.got.append((record.levelname, record.getMessage().splitlines()[0],
                             bool(getattr(record, errwatch.RECOVERED, False))))

        def loud(self):
            """WARNING / ERROR lines errwatch pushes to the group (not marked recovered)."""
            return [m for lv, m, rec in self.got if lv in ("WARNING", "ERROR") and not rec]

        def recovered(self):
            return [m for lv, m, rec in self.got if lv == "WARNING" and rec]


    _levels = _Levels()
    _svc_log = service.log
    _svc_log.addHandler(_levels)
    _svc_log.setLevel(logging.DEBUG)


    def _api(up_after):
        """mas_up() answers True once the fake clock passes `up_after` seconds."""
        return lambda: clock["t"] >= up_after


    print("[窗口已在、接口还没开：等它，不杀]")
    clock["t"] = 0; revived.clear()
    boot_stages.shell_running = lambda: True
    commands.mas_up = _api(30)
    check("等到接口开了就返回 True", boot_stages.ensure_automas(timeout=120, grace=150), True)
    check("没有杀过一次", revived, [])
    check("等了约 30 秒", 27 <= clock["t"] <= 33)

    print("\n[窗口在但宽限期内接口一直不开：宽限期满才杀、再等 timeout]")
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    commands.mas_up = _api(10**9)
    check("最终返回 False", boot_stages.ensure_automas(timeout=120, grace=150), False)
    check("杀了一次", len(revived), 1)
    check("是在宽限期（150 秒）之后才杀的", revived[0] >= 150)
    check("杀完又等了 timeout", clock["t"] >= 150 + 120)
    # Not back: the ERROR (pushed), and only that - the steps before it are INFO.
    check("not recovered: one line for the group, the ERROR", _levels.loud(),
          ["AUTO-MAS 拉起后 120 秒内接口仍不通"])
    check("nothing marked recovered", _levels.recovered(), [])

    print("\n[窗口在、宽限期满才杀、杀后起来了：进群（没应答的原因不明，2026-10-10 前只进日报）]")
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    commands.mas_up = _api(170)
    check("returns True", boot_stages.ensure_automas(timeout=120, grace=150), True)
    check("one line for the group, naming the wait that failed",
          [("窗口开着、等了 150 秒还没应答" in m) for m in _levels.loud()], [True])
    check("nothing marked recovered", _levels.recovered(), [])

    print("\n[窗口根本不在：立刻拉起]")
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    boot_stages.shell_running = lambda: False
    commands.mas_up = _api(20)
    check("拉起后接口开了返回 True", boot_stages.ensure_automas(timeout=120, grace=150), True)
    check("立刻杀/拉起，没有先等宽限期", revived == [0.0])
    # Why AUTO-MAS was not answering is not known: pushed (2026-10-10; daily-report-only before).
    check("nothing marked recovered", _levels.recovered(), [])
    rec_lines = _levels.loud()
    check("one WARNING for the group", len(rec_lines), 1)
    check("plain words, and selfcheck still reads it (「AUTO-MAS 已…秒）」)",
          bool(rec_lines) and not texts.plain(rec_lines[0]) and rec_lines[0].startswith("AUTO-MAS 已")
          and rec_lines[0].endswith("秒）"), True)
    from ark_relay.features.selfcheck import selfcheck
    day_line = "09-30 08:40:10 WARNING  ark.service  " + (rec_lines[0] if rec_lines else "")
    check("selfcheck's daily lines still count it as 「重开后起来了」",
          any("重开后起来了" in x for x in selfcheck.daily_lines("2026-09-30", day_line)), True)

    print("\n[拉起后、等它起来时服务停了（不是中继自己关机）：没确认起来，报群]")
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    commands.mas_up = _api(10**9)
    boot_stages._stop_requested = lambda: clock["t"] >= 9
    check("returns False", boot_stages.ensure_automas(timeout=120, grace=150), False)
    check("one WARNING for the group", [("服务就停了" in m) for m in _levels.loud()], [True])
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    errwatch._relay_poweroff[0] = lambda: True
    check("the relay's own power-off: returns False", boot_stages.ensure_automas(timeout=120, grace=150), False)
    errwatch._relay_poweroff[0] = lambda: False
    check("... and nothing for the group", _levels.loud(), [])
    boot_stages._stop_requested = lambda: False

    print("\n[等待中收到停止信号：立刻返回，不杀不拉，不发「AUTO-MAS 没起来」]")
    # 2026-09-18 23:10: the self-update restarted the service inside this 150 s wait;
    # SvcStop waited 15 s and the hard guard force-exited the process.
    clock["t"] = 0; revived.clear()
    boot_stages.shell_running = lambda: True
    commands.mas_up = _api(10**9)
    boot_stages._stop_requested = lambda: clock["t"] >= 9
    check("停止一到就返回 False", boot_stages.ensure_automas(timeout=120, grace=150), False)
    check("在停止后一次轮询内退出（不到 15 秒）", clock["t"] < 15, True)
    check("没有杀过 AUTO-MAS", revived, [])
    clock["t"] = 0; revived.clear()
    boot_stages.shell_running = lambda: False
    boot_stages._stop_requested = lambda: True
    check("窗口不在但正在停止：也不拉", boot_stages.ensure_automas(timeout=120, grace=150), False)
    check("确实没拉", revived, [])
    boot_stages._stop_requested = lambda: False

    print("\n[接口本来就通：什么都不做]")
    clock["t"] = 0; revived.clear()
    commands.mas_up = lambda: True
    check("直接 True", boot_stages.ensure_automas(), True)
    check("没动手", revived, [])

    print("\n[_revive_automas 连 auto-mas-runtime.exe 一起杀]")
    ran = []
    import importlib
    importlib.reload(boot_stages)
    boot_stages.time.sleep = lambda s: None
    boot_stages.subprocess.run = lambda cmd, **kw: (ran.append(" ".join(cmd)),
                                                    types.SimpleNamespace(returncode=0, stdout=b""))[1]
    boot_stages._revive_automas()
    check("先杀窗口", any("taskkill /IM AUTO-MAS.exe /F" in c for c in ran))
    check("再杀 runtime（不杀它，新窗口会卡在 MUTATION_IN_PROGRESS）",
          any("taskkill /IM auto-mas-runtime.exe /F" in c for c in ran))
    check("然后 /end 再 /run", ran[-2].startswith("schtasks /end") and ran[-1].startswith("schtasks /run"))
    check("杀窗口在杀 runtime 之前",
          [i for i, c in enumerate(ran) if "AUTO-MAS.exe" in c][0]
          < [i for i, c in enumerate(ran) if "auto-mas-runtime.exe" in c][0])

    print("\n[开机拉不起来要立刻报警（群）]")
    check("文案在 texts 里且是人话", texts.plain(texts.automas_boot_down_body()), [])
    from ark_relay.core.notify import route_of
    check("走群机器人", route_of(texts.AUTOMAS_DOWN, alert=True), "group")

    print("\n[没有 wmic 的机器上 keeper 不许装瞎]")
    automas_procs._python_processes = lambda: None          # the query itself failed
    commands.mas_up = lambda: False
    check("进程表读不到、接口不通 → 不在（以前是「假定活着」）", automas_procs._automas_running(), False)
    commands.mas_up = lambda: True
    check("进程表读不到、接口通 → 在", automas_procs._automas_running(), True)
    automas_procs._python_processes = lambda: [(4132, r'"C:\Program Files\Python314\python.exe" C:\ProgramData\x.py')]
    commands.mas_up = lambda: True
    check("有 python 但不是 main.py → 不在（接口不算，句柄要挂在进程上）",
          automas_procs._automas_running(), False)
    automas_procs._python_processes = lambda: [(21932, r'"D:\ark\automas\runtime\environment\python\python.exe" D:\ark\automas\repo\main.py')]
    check("有 main.py → 在", automas_procs._automas_running(), True)

    print("\n[AUTO-MAS 的收尾记录不当成一趟运行核对]")
    from ark_relay.features.alarm import handle
    check("识别文本来自真实记录", handle.MAAEND_NOTHING_TO_RUN in handle.MAAEND_NOTHING_TO_RUN_LOG)
    import tempfile
    from datetime import datetime
    from ark_relay.core.config import RunRecord, SERVER_TZ
    with tempfile.TemporaryDirectory() as td:
        lp = Path(td) / "MaaEnd-06-32-49.log"
        lp.write_text("MaaEnd 没有可执行任务，请检查任务配置, 无日志记录", encoding="utf-8")
        rec = RunRecord(run_id="2026-09-17/endfield/MaaEnd-06-32-49", script="MaaEnd", user="endfield",
                        started=datetime(2026, 9, 17, 10, 32, 49, tzinfo=SERVER_TZ),
                        finished=datetime(2026, 9, 17, 10, 32, 49, tzinfo=SERVER_TZ), ok=True,
                        raw={"maaend_result": "[自动采集] MaaEnd 没有可执行任务，请检查任务配置"}, log_path=lp)
        eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=td, automas_dir=td, maa_dir=td))
        check("收尾记录 → 不报「没干完」", handle._verify_outcome(eng, rec), None)

    boot_stages.time.sleep, boot_stages.time.monotonic = _real_sleep, _real_monotonic

    print()
    if fails:
        print("FAILED:", fails); sys.exit(1)
    print("all checks passed")


def _part_automas_contract_watch():
    """scripts/mac/lib/automas_contract_watch.py: a new AUTO-MAS release is compared with the settings
the relay reads before the game machine installs it.

AUTO-MAS v5.7.0-beta.3 was published 2026-10-13 07:23 UTC and installed on the machine 10-14
08:46 Beijing; it moved the MAA user's stage items from Info to Stage. With the relay's list as it
stood before masuser (every MAA user item in Info), the tool must name that move from the release's
app/models/config.py alone; with the current list (ark_relay/core/mascontract.py + masuser) it must
report nothing for v5.7.0-beta.4, and for v5.7.0-beta.3 and v5.7.0-beta.2 only the two MaaEnd
launcher settings beta.4 brought in (Game.LaunchMode, Game.LauncherPath; read since 10-16).

Fixtures (public upstream source): fixtures/automas-models/config.py.txt is v5.7.0-beta.2's whole
config.py (already used by test_mas.py); config-v5.7.0-beta.3-excerpt.py.txt holds only the
ConfigItem statements of the listed settings from v5.7.0-beta.3, verbatim, under their classes;
config-v5.7.0-beta.4-excerpt.py.txt the same from v5.7.0-beta.4.
GitHub itself is not asked here (main() is given the file); the exit codes are checked on that path.

    Formerly test_automas_contract_watch.py.
    """
    import io
    from contextlib import redirect_stdout

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parents[1] / "scripts" / "mac" / "lib"))
    sys.path.insert(0, str(HERE.parent))
    from ark_relay.core import masuser  # after the sys.path lines above
    try:
        import automas_contract_watch as w
        from ark_relay.core import mascontract
    except ImportError:          # the code before this change
        w = mascontract = None

    BETA2 = HERE / "fixtures" / "automas-models" / "config.py.txt"
    BETA3 = HERE / "fixtures" / "automas-models" / "config-v5.7.0-beta.3-excerpt.py.txt"
    BETA4 = HERE / "fixtures" / "automas-models" / "config-v5.7.0-beta.4-excerpt.py.txt"
    # The two MaaEnd settings AUTO-MAS v5.7.0-beta.4 brought in (PR #1394, the launcher start);
    # the relay reads them since 10-16 (efstart_setup), so an older release lacks them.
    NEW_IN_BETA4 = ["MaaEndConfig Game.LaunchMode", "MaaEndConfig Game.LauncherPath"]


    def run_main(*argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = w.main(list(argv))
        return code, buf.getvalue()


    check("the tool and the relay's list exist", w is not None and mascontract is not None)
    if w is not None and mascontract is not None:
        beta2, beta3 = w.parse(BETA2.read_text(encoding="utf-8")), w.parse(BETA3.read_text(encoding="utf-8"))
        beta4 = w.parse(BETA4.read_text(encoding="utf-8"))

        def named(gaps):
            return [g.split(":")[0] for g in gaps]
        # The list as it stood before masuser: the moved MAA user items read from Info only.
        before = [mascontract.Item(i.kind, i.level, "Info", i.key, i.use, i.source)
                  if i.level == "user" and i.key in masuser.MOVED else i for i in mascontract.CONTRACT]

        print("[v5.7.0-beta.3 against the list before masuser: the 10-14 move is named]")
        gaps = w.compare(beta3, before)
        moved = sorted(g.split(":")[0] + " -> " + g.split("moved to ")[1].split(" (")[0]
                       for g in gaps if "moved to" in g)
        check("every MAA user item the relay read from Info is reported moved", moved, [
            "MaaUserConfig Info.Annihilation -> Task.Annihilation",
            "MaaUserConfig Info.MedicineNumb -> Stage.MedicineNumb",
            "MaaUserConfig Info.SeriesNumb -> Stage.SeriesNumb",
            "MaaUserConfig Info.Stage -> Stage.Stage",
            "MaaUserConfig Info.StageMode -> Stage.StageMode",
            "MaaUserConfig Info.Stage_1 -> Stage.Stage_1",
            "MaaUserConfig Info.Stage_2 -> Stage.Stage_2",
            "MaaUserConfig Info.Stage_3 -> Stage.Stage_3",
        ])
        check("nothing else is reported but the two settings beta.4 brought in",
              sorted(set(named(gaps)) - {m.split(" -> ")[0] for m in moved}), NEW_IN_BETA4)
        check("v5.7.0-beta.2 against that same list: only those two (it still kept the rest in Info)",
              named(w.compare(beta2, before)), NEW_IN_BETA4)

        print("\n[the current list (mascontract + masuser)]")
        check("v5.7.0-beta.4: nothing changed", w.compare(beta4, mascontract.CONTRACT, masuser.MOVED), [])
        check("v5.7.0-beta.3: only the two settings beta.4 brought in",
              named(w.compare(beta3, mascontract.CONTRACT, masuser.MOVED)), NEW_IN_BETA4)
        check("v5.7.0-beta.2: the same two", named(w.compare(beta2, mascontract.CONTRACT, masuser.MOVED)), NEW_IN_BETA4)

        print("\n[a key a release drops is reported, a whole class too]")
        fake = [mascontract.Item("MAA", "user", "Stage", "NoSuchKey", "stage", "x.py:f"),
                mascontract.Item("plan", "plan", "Info", "Mode", "plan_table", "x.py:f")]
        no_plan = {k: v for k, v in beta3.items() if k != "MaaPlanConfig"}
        out = w.compare(no_plan, fake, masuser.MOVED)
        check("a dropped key", any(g.startswith("MaaUserConfig Stage.NoSuchKey: no longer defined") for g in out))
        check("a dropped class", any(g.startswith("MaaPlanConfig Info.Mode: class MaaPlanConfig is gone") for g in out))

        print("\n[parsing: helpers called with self, f-string keys, loop rows]")
        check("MaaEnd's helper items count for MaaEndUserConfig",
              ("Task", "SanityTaskType") in beta3["MaaEndUserConfig"])
        check("f\"If{task}\" becomes the pattern If*", ("Task", "If*") in beta3["MaaEndUserConfig"])
        check("legacy_group is read", beta3["MaaUserConfig"][("Stage", "Stage")], ("Info", "Stage"))

        print("\n[exit codes]")
        code, text = run_main("--file", str(BETA4))
        check("nothing changed: exit 0", code, 0)
        orig = mascontract.CONTRACT
        mascontract.CONTRACT = tuple(before)
        try:
            code, text = run_main("--file", str(BETA4))
        finally:
            mascontract.CONTRACT = orig
        check("something changed: exit 2", code, 2)
        check("and it is printed", "Info.Stage: moved to Stage.Stage" in text)
        real_http = w._http
        w._gh = lambda path: None

        def offline(url):
            raise w.urllib.error.URLError("offline")
        w._http = offline
        try:
            code, text = run_main()
        finally:
            w._http = real_http
        check("GitHub cannot be read: exit 3", code, 3)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_automas_handover():
    """relay/handover/automas_handover.py against a fake AUTO-MAS at the HTTP layer.

Only `urllib.request.urlopen` is replaced. The config shapes are the ones the
handover reads on the machine (BOARD/新中继-重叠可撤核对.md, values read
2026-10-11 02:45-02:55 Beijing): MAA user Info.Annihilation "Close",
Info.IfQuickConfig true, Info.Server "Official"; MAA script
Run.IfCheckGameUpdate / Run.IfAutoInstallGameApk false; Start.IfSelfStart true.
Endpoints and bodies as relay/ark_relay/commands.py and annihilation.py use them
(every endpoint POST; /api/scripts/update {"scriptId","data"},
/api/scripts/user/update {"scriptId","userId","data"}); /api/setting/get and
/update {"data"} as AUTO-MAS app/api/setting.py (v5.7.0 line, 699de5a).

    Formerly test_automas_handover.py.
    """

    import io
    import json
    import os
    import urllib.error
    import urllib.request
    from contextlib import nullcontext

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "handover"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ["ARK_MAS_PORT"] = "36163"
    import automas_handover as H
    from ark_relay.core import masuser

    H.this_week = lambda: "2026-W41"   # the game week every case below is run in


    MAA, END, OKWW, UID = "s-maa", "s-end", "s-okww", "u-1"


    def merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v


    class Backend:
        """mode: "up" | "down" (connection refused) | "running" (updates answer
    code 500 「正在运行, 无法更新配置项」, the message commands._refused cites)."""

        def __init__(self, mode="up", annihilation="Close", quick=True, server="Official", selfstart=True,
                     beta3=False):
            self.mode = mode
            self.beta3 = beta3
            self.calls = []
            self.scripts = {
                MAA: {"Info": {"Name": "MAA"}, "Run": {"IfCheckGameUpdate": False, "IfAutoInstallGameApk": False,
                                                      "HardTimeLimit": 120}},
                END: {"Info": {"Name": "MaaEnd"}, "Run": {"HardTimeLimit": 120}},
                OKWW: {"Info": {"Name": "OK-WW"}, "Run": {"HardTimeLimit": 120, "RunTimeLimit": 120},
                       "Game": {"Enabled": False, "Path": "", "IfAutoUpdate": True}},
            }
            self.users = {
                MAA: {UID: {"Info": {"Annihilation": annihilation, "IfQuickConfig": quick, "Server": server,
                                     "AnnihilationStartWeekday": "Monday"},
                            "Data": {"AnnihilationCompletedWeek": "2026-W41"}}},
                END: {UID: {"Info": {}}},
                OKWW: {UID: {"Info": {}}},
            }
            self.setting = {"Start": {"IfSelfStart": selfstart}}
            if beta3:
                # AUTO-MAS v5.7.0-beta.3 after its first start: the two annihilation items live
                # in Task only (app/models/config.py of that tag, Task_Annihilation and
                # Task_AnnihilationStartWeekday with legacy_group="Info").
                info = self.users[MAA][UID]["Info"]
                self.users[MAA][UID]["Task"] = {k: info.pop(k) for k in ("Annihilation", "AnnihilationStartWeekday")}

        def urlopen(self, req, timeout=None):
            path = req.full_url[len("http://127.0.0.1:36163"):]
            body = json.loads((req.data or b"{}").decode())
            self.calls.append((path, body))
            if self.mode == "down":
                raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
            if path.endswith("/update") and self.mode == "running":
                return _Resp({"code": 500, "status": "error", "message": "正在运行, 无法更新配置项"})
            if path == "/api/scripts/get":
                return _Resp({"code": 200, "data": self.scripts})
            if path == "/api/scripts/user/get":
                return _Resp({"code": 200, "data": self.users[body["scriptId"]]})
            if path == "/api/setting/get":
                return _Resp({"code": 200, "data": self.setting})
            if path == "/api/scripts/update":
                merge(self.scripts[body["scriptId"]], body["data"])
                return _Resp({"code": 200})
            if path == "/api/scripts/user/update":
                moved = set((body["data"].get("Info") or {})) & set(masuser.MOVED)
                if self.beta3 and moved:
                    # beta.3's backend has no Info.Annihilation item any more and refuses it.
                    return _Resp({"code": 500, "status": "error", "message": f"未知配置项 Info.{sorted(moved)[0]}"})
                merge(self.users[body["scriptId"]][body["userId"]], body["data"])
                return _Resp({"code": 200})
            if path == "/api/setting/update":
                merge(self.setting, body["data"])
                return _Resp({"code": 200})
            raise AssertionError(f"endpoint not prepared by this test: {path}")

        def updates(self):
            return [p for p, _ in self.calls if p.endswith("/update")]


    class _Resp:
        def __init__(self, obj):
            self._raw = json.dumps(obj, ensure_ascii=False).encode()

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    _real = urllib.request.urlopen


    def run(be, *argv):
        urllib.request.urlopen = be.urlopen
        out = io.StringIO()
        old, sys.stdout = sys.stdout, out
        try:
            code = H.main(list(argv))
        finally:
            sys.stdout = old
        return code, out.getvalue()


    try:
        with nullcontext(tmpdir()) as d:   # tmpdir() is a plain Path, removed at exit
            state = Path(d) / "state"
            state.mkdir()
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W40", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]

            print("plan reads only (the relay closed it last week; the week has rolled)")
            be = Backend()
            code, out = run(be, "plan", *sd)
            check("plan exit 0", code, 0)
            check("plan sends no update", be.updates(), [])
            check("plan shows the annihilation map it would restore",
                  "'Close' -> 'Chernobog@Annihilation'" in out, True)
            check("plan prints the hard limit fact", "Run.HardTimeLimit = 120" in out, True)

            print("apply changes, reads back, saves the old values")
            code, out = run(be, "apply", *sd)
            check("apply exit 0", code, 0)
            check("annihilation restored to the saved map",
                  be.users[MAA][UID]["Info"]["Annihilation"], "Chernobog@Annihilation")
            check("arknights client update on", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], True)
            check("arknights apk install on", be.scripts[MAA]["Run"]["IfAutoInstallGameApk"], True)
            check("wuwa untouched without --with-wuwa-update", be.scripts[OKWW]["Game"]["Enabled"], False)
            saved = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
            check("old annihilation value saved", saved.get("user:MAA:Info.Annihilation"), "Close")
            check("old update switch saved", saved.get("script:MAA:Run.IfCheckGameUpdate"), False)

            print("apply again is a no-op and keeps the first old values")
            n = len(be.updates())
            code, _ = run(be, "apply", *sd)
            check("second apply exit 0", code, 0)
            check("second apply sends no update", len(be.updates()), n)
            saved2 = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
            check("backup still holds the pre-handover values", saved2, saved)

            print("rollback puts exactly the old values back")
            code, out = run(be, "rollback", "--state-dir", str(state))
            check("rollback exit 0", code, 0)
            check("annihilation back to Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("update switch back off", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], False)
            check("backup removed after a full rollback", (state / H.BACKUP_FILE).exists(), False)

        print("the moved keys are the same here as in the relay (this file cannot import it)")
        check("MOVED equals ark_relay.core.masuser.MOVED", getattr(H, "MOVED", None), masuser.MOVED)

        with nullcontext(tmpdir()) as d:   # tmpdir() is a plain Path, removed at exit
            state = Path(d)
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W40", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]

            print("AUTO-MAS v5.7.0-beta.3 (annihilation under Task): apply and rollback use Task")
            be = Backend(beta3=True)
            code, out = run(be, "plan", *sd)
            check("plan reads the Close from Task", "'Close' -> 'Chernobog@Annihilation'" in out, True)
            check("plan reads the start weekday from Task", "Info.AnnihilationStartWeekday = 'Monday'" in out, True)
            code, out = run(be, "apply", *sd)
            check("apply exit 0", code, 0)
            check("annihilation restored in Task", be.users[MAA][UID]["Task"]["Annihilation"], "Chernobog@Annihilation")
            check("no Info.Annihilation written back", "Annihilation" in be.users[MAA][UID]["Info"], False)
            saved = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
            check("backup keeps the old key", saved.get("user:MAA:Info.Annihilation"), "Close")
            code, out = run(be, "rollback", "--state-dir", str(state))
            check("rollback exit 0", code, 0)
            check("rollback puts Close back in Task", be.users[MAA][UID]["Task"]["Annihilation"], "Close")

        with nullcontext(tmpdir()) as d:   # tmpdir() is a plain Path, removed at exit
            state = Path(d)
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]

            print("a Close the relay never set (no done_week) stays Close")
            be = Backend()
            code, out = run(be, "apply", *sd)
            check("exit 0", code, 0)
            check("annihilation left Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("no write to annihilation", [b for p, b in be.calls if p == "/api/scripts/user/update"], [])
            check("says why", "no done_week" in out, True)

            print("done_week without a saved map: AUTO-MAS's own default, as the old relay did")
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W40"}}}), encoding="utf-8")
            be = Backend()
            code, _ = run(be, "apply", *sd)
            check("restored to the default map", be.users[MAA][UID]["Info"]["Annihilation"], "Annihilation")

            print("done this week, AUTO-MAS has no record of it: hand the record over, then open")
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W41", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")
            be = Backend()
            be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"] = "2026-W40"
            code, out = run(be, "plan", *sd)
            check("plan exit 0", code, 0)
            check("plan sends no update", be.updates(), [])
            check("plan shows the record it would write", "'2026-W40' -> '2026-W41'" in out, True)
            check("plan shows the map it would then restore", "'Close' -> 'Chernobog@Annihilation'" in out, True)
            code, out = run(be, "apply", *sd)
            check("apply exit 0", code, 0)
            check("AUTO-MAS now knows this week is done",
                  be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"], "2026-W41")
            check("annihilation restored", be.users[MAA][UID]["Info"]["Annihilation"], "Chernobog@Annihilation")
            writes = [b["data"] for p, b in be.calls if p == "/api/scripts/user/update"]
            check("the record is written before the switch opens",
                  writes[:2], [{"Data": {"AnnihilationCompletedWeek": "2026-W41"}},
                               {"Info": {"Annihilation": "Chernobog@Annihilation"}}])
            code, _ = run(be, "rollback", "--state-dir", str(state))
            check("rollback puts the old record back", be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"], "2026-W40")
            check("rollback closes it again", be.users[MAA][UID]["Info"]["Annihilation"], "Close")

            print("done this week but the record write is refused: the switch stays Close")
            be = Backend(mode="running")
            be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"] = "2026-W40"
            code, out = run(be, "apply", *sd)
            check("exit 1", code, 1)
            check("annihilation left Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("says it needs the record", "Data.AnnihilationCompletedWeek='2026-W41'" in out, True)
            (state / "state.json").unlink()

            print("quick config off: annihilation is not handed over")
            be = Backend(quick=False)
            code, out = run(be, "apply", *sd)
            check("exit 1", code, 1)
            check("annihilation left Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("says why", "Info.IfQuickConfig" in out, True)

            print("not the official server: client update not handed over")
            be = Backend(server="Bilibili")
            code, out = run(be, "apply", *sd)
            check("exit 1", code, 1)
            check("update switch left off", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], False)

            print("a task running: the backend refuses, nothing reported as done")
            be = Backend(mode="running")
            code, out = run(be, "apply", *sd)
            check("exit 1", code, 1)
            check("refusal reported", "正在运行" in out, True)

            print("backend down")
            be = Backend(mode="down")
            code, out = run(be, "apply", *sd)
            check("exit 2", code, 2)

            print("self start off is switched on")
            be = Backend(selfstart=False)
            code, _ = run(be, "apply", *sd)
            check("IfSelfStart true", be.setting["Start"]["IfSelfStart"], True)

            print("--with-wuwa-update without a launcher: refuses, does not enable")
            be = Backend()
            code, out = run(be, "apply", "--with-wuwa-update", *sd)
            check("exit 1", code, 1)
            check("Game.Enabled still off", be.scripts[OKWW]["Game"]["Enabled"], False)
            check("says the launcher was not found", "launcher.exe not found" in out, True)

            print("--with-wuwa-update with the launcher next to the game folder")
            game = Path(d) / "Wuthering Waves Game" / "Wuthering Waves.exe"
            game.parent.mkdir()
            game.write_text("")
            launcher = Path(d) / "Wuthering Waves" / "launcher.exe"
            launcher.parent.mkdir()
            launcher.write_text("")
            cfg = Path(d) / "okww" / "data" / "apps" / "ok-ww" / "working" / "configs"
            cfg.mkdir(parents=True)
            (cfg / "Game.json").write_text(json.dumps({"path": str(game)}), encoding="utf-8")
            be = Backend()
            code, out = run(be, "plan", "--with-wuwa-update", *sd)
            check("plan with wuwa exit 0", code, 0)
            check("plan with wuwa sends no update", be.updates(), [])
            check("plan shows the three wuwa lines", out.count("[10b]"), 3)
            code, out = run(be, "apply", "--with-wuwa-update", *sd)
            check("exit 0", code, 0)
            check("launcher path set", be.scripts[OKWW]["Game"]["Path"], str(launcher))
            check("game start handed over", be.scripts[OKWW]["Game"]["Enabled"], True)

        with nullcontext(tmpdir()) as d:
            state = Path(d)
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W40", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")

            print("the relay closed it once but the switch is open now: left as it is")
            be = Backend(annihilation="Annihilation")
            code, _ = run(be, "apply", *sd)
            check("exit 0", code, 0)
            check("annihilation untouched", be.users[MAA][UID]["Info"]["Annihilation"], "Annihilation")
            (state / H.BACKUP_FILE).unlink(missing_ok=True)

            print("--only 13: annihilation only, the other AUTO-MAS settings neither read nor changed")
            be = Backend(selfstart=False)
            code, out = run(be, "plan", "--only", "13", *sd)
            check("plan exit 0", code, 0)
            check("plan prints only step 13", sorted({l.split("]")[0] for l in out.splitlines() if l.startswith("[")}),
                  ["[13"])
            code, out = run(be, "apply", "--only", "13", *sd)
            check("apply exit 0", code, 0)
            check("annihilation restored", be.users[MAA][UID]["Info"]["Annihilation"], "Chernobog@Annihilation")
            check("arknights update switch untouched", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], False)
            check("self start untouched", be.setting["Start"]["IfSelfStart"], False)
            check("setting never read", [p for p, _ in be.calls if p.startswith("/api/setting/")], [])
            (state / H.BACKUP_FILE).unlink(missing_ok=True)

            print("--only 10a --only 20: those two, annihilation left Close")
            be = Backend(selfstart=False)
            code, _ = run(be, "apply", "--only", "10a", "--only", "20", *sd)
            check("exit 0", code, 0)
            check("annihilation left Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("arknights update switch on", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], True)
            check("self start on", be.setting["Start"]["IfSelfStart"], True)

            print("--only with an unknown step is refused, nothing done")
            be = Backend()
            err, sys.stderr = sys.stderr, io.StringIO()
            try:
                run(be, "apply", "--only", "99", *sd)
                code = 0
            except SystemExit as exc:
                code = exc.code
            finally:
                sys.stderr = err
            check("argparse exit 2", code, 2)
            check("no call made", be.calls, [])
        with nullcontext(tmpdir()) as d:   # tmpdir() is a plain Path, removed at exit
            state = Path(d)
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]
            print("uninstall with the old relay gone: 13, 10a, 10b stay with AUTO-MAS, the rest goes back")
            # s26 audit 2026-10-13: the old relay was retired 10-11 22:33; putting back its
            # Close and the update switches it owned would leave nobody doing those jobs.
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W41", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")
            launcher = Path(d) / "Wuthering Waves" / "launcher.exe"
            real_launcher, H.wuwa_launcher = H.wuwa_launcher, lambda okww_dir: launcher
            try:
                be = Backend(selfstart=False)
                be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"] = "2026-W40"
                be.scripts[OKWW]["Game"]["IfAutoUpdate"] = False
                code, _ = run(be, "apply", "--with-wuwa-update", *sd)
                check("apply exit 0", code, 0)
                saved = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
                handed = {st["target"].key for st in H.steps(state, Path(d), True) if st["id"] in ("13", "10a", "10b")}
                check("every 13 / 10a / 10b setting the handover changes is kept with AUTO-MAS",
                      sorted(handed - set(getattr(H, "KEPT_WITHOUT_OLD_RELAY", ()))), [])
                check("the backup holds all of them and 20", sorted(saved), sorted(handed | {"setting::Start.IfSelfStart"}))
                try:
                    code, out = run(be, "rollback", "--old-relay-gone", "--state-dir", str(state))
                except SystemExit as exc:      # the old argparse: no such option
                    code, out = exc.code, ""
                check("rollback exit 0", code, 0)
                check("annihilation stays open", be.users[MAA][UID]["Info"]["Annihilation"], "Chernobog@Annihilation")
                check("this week's record stays", be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"], "2026-W41")
                check("arknights client update stays on",
                      (be.scripts[MAA]["Run"]["IfCheckGameUpdate"], be.scripts[MAA]["Run"]["IfAutoInstallGameApk"]),
                      (True, True))
                check("wuwa update stays on", be.scripts[OKWW]["Game"],
                      {"Enabled": True, "Path": str(launcher), "IfAutoUpdate": True})
                check("20 (not the old relay's job) is put back", be.setting["Start"]["IfSelfStart"], False)
                check("says what it left", out.count("left with AUTO-MAS"), 7)
                check("backup removed", (state / H.BACKUP_FILE).exists(), False)
            finally:
                H.wuwa_launcher = real_launcher
    finally:
        urllib.request.urlopen = _real


if __name__ == "__main__":
    sys.exit(run_parts([_part_automas_backend_match, _part_automas_boot_one_alarm, _part_automas_boot_revival, _part_automas_contract_watch, _part_automas_handover]))
