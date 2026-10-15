"""daysim: one recorded relay boot, in a fresh process (design.md section 1, "Process model").

    python3.14 -I boot.py <spec.json>

The spec (written by run.py) names the day, the sim tree, the boot (plan_boots) and
where to write this boot's outputs. Order matters, and each step says why:

1. TZ is in the environment (run.py) and tzset runs first: relay.log stamps use
   localtime, and the oracle reads them as Beijing time.
2. The fakes are built before simclock.install(), so their own locks stay real
   locks (world.py module docstring); then the clock is installed, before any
   relay import.
3. The World applies every input up to the boot's start, then the relay is
   imported from the code copy in the sim tree and its host is built the way
   app_main._host_class builds it (the installed relay is app_main.py; relay.log
   says 「收到停止请求（app_main.py stop）」). The end-session window is not started:
   win32gui is not modelled, and a Windows shutdown reaches SvcShutdown from the
   World instead.
4. After main() returns: app_main.run's ending (wait for the stop push, the
   heartbeat's bye, errwatch.drain), then this boot's outputs are written and the
   process leaves with os._exit, as the relay does.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if hasattr(time, "tzset"):
    time.tzset()

import simclock  # noqa: E402
import world as W  # noqa: E402
from fake_desktop import FakeDesktop  # noqa: E402
from fake_mas import FakeMas  # noqa: E402
from fake_net import FakeNet  # noqa: E402
from fake_proc import ProcRouter, WinState  # noqa: E402
from fake_win import FakeWin  # noqa: E402

REAL_EXIT = os._exit
REAL_CLOCK = time.perf_counter      # taken before simclock patches time
CPU_CLOCK = time.process_time       # this process's CPU seconds (run.py's day budget)
# A boot that has not ended this long after its recorded end is a sim error (a stop
# the relay never finished). SvcStop's own hard exit is 15 s (service.py); the
# app_main ending waits up to 10 + 3 + 2 s more.
UNTIL_MARGIN_S = 900


class Capture(logging.Handler):
    """relay.log lines the oracle reads: WARNING and up, and every shutdown decision."""

    def __init__(self, sink: list):
        super().__init__(logging.DEBUG)
        self.sink = sink

    def emit(self, rec: logging.LogRecord) -> None:
        if rec.levelno < logging.WARNING and rec.name != "ark.shutdown":
            return
        try:
            msg = rec.getMessage()
        except Exception:  # noqa: BLE001 - a broken format is still a line
            msg = str(rec.msg)
        if rec.exc_info:
            msg += "\n" + "".join(traceback.format_exception(*rec.exc_info))[-3000:]
        self.sink.append({"t": W.iso(rec.created), "level": rec.levelname, "logger": rec.name, "msg": msg})


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    day, tree, boot = spec["day"], Path(spec["tree"]), spec["boot"]
    corpus = Path(spec["corpus"])
    out_path = Path(spec["out"])
    offline = bool(spec.get("offline"))
    real0, cpu0 = REAL_CLOCK(), CPU_CLOCK()

    # ---- 2. fakes first (real locks), then the clock
    sched = W.Sched(simclock)
    win = WinState(sched, power_on=boot["power_on"])
    fw = FakeWin(sched, win).install()
    router = ProcRouter(sched, win).install()
    mas = FakeMas(sched, tree / W.AUTOMAS_REL, tree / "_sim" / "mas-shadow", up=False)
    net = FakeNet(sched, mas=mas, mac_url=W.ALERT_URL).install()
    W.assert_offline(net)
    desk = FakeDesktop(sched)
    world = W.World(sched, day=day, tree=tree, corpus=corpus, boot=boot,
                    fakes=(win, fw, router, net, mas, desk))
    desk.spawn = world.desktop_spawn(desk.spawn)
    mas.version = world.automas_version(boot["start"])
    for ev in world.events:
        if ev["kind"] == "desktop":
            try:
                desk.add(W.epoch(ev["req"]["mtime"]),
                         json.loads((corpus / ev["req"]["file"]).read_text(encoding="utf-8-sig")),
                         json.loads((corpus / ev["res"]["file"]).read_text(encoding="utf-8-sig")))
            except (OSError, ValueError, KeyError):
                pass
    log_lines: list = []
    capture = Capture(log_lines)
    done = threading.Lock()
    result = {"exit": "running"}

    def finish(how: str, code: int = 0) -> None:
        if not done.acquire(False):
            return
        try:
            world.save()
        except Exception:  # noqa: BLE001
            simclock.out("sim_error", what="world state not saved", detail=traceback.format_exc()[-1500:])
        doc = {"boot": boot, "exit": how, "sim_end": W.iso(simclock.now()) if simclock._st.installed else None,
               "real_s": round(REAL_CLOCK() - real0, 3), "cpu_s": round(CPU_CLOCK() - cpu0, 3),
               "outputs": simclock.outputs(), "log": log_lines}
        tmp = out_path.with_name(out_path.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out_path)
        sys.stdout.flush()
        sys.stderr.flush()
        REAL_EXIT(code)

    def exit_hook(code=0):
        finish(result.get("exit") if result.get("exit") != "running" else "os._exit", code)

    os._exit = exit_hook

    simclock.install(boot["start"], power_on=boot["power_on"], steplog=tree / "_sim" / "steplog.txt",
                     until=boot["end"] + UNTIL_MARGIN_S)
    # ---- 3. the relay, from the code copy (on the path before the World's set-up: a
    # phone order is rebuilt from the relay's own boss table)
    code = tree / "_sim" / "code"
    sys.path.insert(0, str(code))
    world.prepare()
    if offline:
        finish("offline")

    pil_site = W.pillow_site(tree)
    if pil_site is not None:
        sys.path.append(str(pil_site))
    real_basic = logging.basicConfig

    def basic_config(**kw):
        real_basic(**kw)
        if capture not in logging.getLogger().handlers:
            logging.getLogger().addHandler(capture)
    logging.basicConfig = basic_config

    import service  # noqa: PLC0415 - chdirs to the code folder, as on the machine
    from ark_relay.core import config  # noqa: PLC0415
    config.IS_WINDOWS = True
    # The Endfield launcher helper's set-up at boot (gameupdate/efstart_setup.py) checks
    # Windows paths read from AUTO-MAS and the relay's own pythonw.exe: answered from the
    # sim tree, with the launcher where it is on the machine (Launcher.exe three levels
    # above Endfield.exe, the parent session 2026-10-15).
    from ark_relay.features.gameupdate import efstart_setup  # noqa: PLC0415
    launcher = W.tpath(tree, r"D:\endfield\Hypergryph Launcher\Launcher.exe")
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.touch()
    efstart_setup._is_file = lambda p: W.tpath(tree, str(p)).is_file()
    efstart_setup._find_pythonw = lambda: Path(r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe")
    os.chdir(tree / W.DATA_REL)          # app_main.run: os.chdir(DATA)
    desk.install()
    # Frozen code: the COS door says the version the machine already runs.
    try:
        from ark_relay.core.statestore import StateStore  # noqa: PLC0415
        local = int(str(StateStore(tree / W.DATA_REL / "state").get("versions", "code") or 0) or 0)
    except Exception:  # noqa: BLE001
        local = 0
    net.code_version = local
    net.cos["relay/latest.json"] = json.dumps({"version": local}).encode()

    class Host:
        """app_main._host_class's AppHost: service.ArkRelayService's stop code, no SCM."""

        _svc_name_ = service.ArkRelayService._svc_name_
        SvcStop = service.ArkRelayService.SvcStop
        SvcShutdown = service.ArkRelayService.SvcShutdown
        _wait_stop_push = service.ArkRelayService._wait_stop_push
        main = service.ArkRelayService.main
        _stop_in_boot = service.ArkRelayService._stop_in_boot

        def __init__(self) -> None:
            import win32event  # noqa: PLC0415
            self.stop_event = win32event.CreateEvent(None, 1, 0, None)
            self._stop_how = "停止中继"
            self._stop_asked = threading.Event()
            self._stop_pushed = threading.Event()

        def ReportServiceStatus(self, *_args) -> None:  # noqa: N802 - SvcStop calls it
            """No SCM to report to."""

    host = Host()
    world.schedule(host)
    how = "returned"
    try:
        host.main()
    except BaseException as exc:  # noqa: BLE001 - SimAbort and SimError included
        how = f"raised {type(exc).__name__}"
        simclock.out("sim_error", what="exception escaped main", detail=traceback.format_exc()[-3000:])
    # ---- 4. app_main.run's ending
    try:
        host._wait_stop_push()
        for t in threading.enumerate():
            if t.name == "phone-heartbeat":
                t.join(3)
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        errwatch.drain(2.0)
    except BaseException:  # noqa: BLE001
        simclock.out("sim_error", what="exception in the ending", detail=traceback.format_exc()[-3000:])
    result["exit"] = how
    finish(how)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
        REAL_EXIT(3)
