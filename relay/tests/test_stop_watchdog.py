"""Watchdog stop-push handoff, deploy watcher, and COS publishing."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir

_SHARED = (check, fails, require, tmpdir)


def _part_stop_push_watchdog():
    import logging
    import os
    import re
    import threading
    import types
    from datetime import datetime

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(RELAY))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(ROOT / "packaging" / "watchdog"))

    DATA = tmpdir()
    (DATA / "state").mkdir()
    os.environ["ARK_HOME"] = str(DATA)
    for _k in ("ARK_LOG_FILE", "ARK_STATE_DIR", "ARK_PHONE_TOPIC", "ARK_PHONE_PIN"):
        os.environ.pop(_k, None)
    LOG = DATA / "relay.log"


    # ---------------------------------------------------------------- pywin32, faked

    def _module(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m


    class _Event:
        def __init__(self):
            self.set = False


    def _wait(evt, ms):
        return 0 if evt.set else 258


    win32service = _module(
        "win32service", SERVICE_ACCEPT_STOP=0x1, SERVICE_ACCEPT_PAUSE_CONTINUE=0x2, SERVICE_ACCEPT_SHUTDOWN=0x4,
        SERVICE_ACCEPT_PRESHUTDOWN=0x100, SERVICE_CONTROL_SHUTDOWN=0x5, SERVICE_CONTROL_PRESHUTDOWN=0xF,
        SERVICE_STOP_PENDING=3, SERVICE_AUTO_START=2)


    class ServiceFramework:
        """pywin32 311's win32serviceutil.ServiceFramework, the parts the watchdog relies on."""

        def __init__(self, args):
            self.statuses = []

        def GetAcceptedControls(self):  # noqa: N802
            accepted = 0
            if hasattr(self, "SvcStop"):
                accepted |= win32service.SERVICE_ACCEPT_STOP
            if hasattr(self, "SvcPause") and hasattr(self, "SvcContinue"):
                accepted |= win32service.SERVICE_ACCEPT_PAUSE_CONTINUE
            if hasattr(self, "SvcShutdown"):
                accepted |= win32service.SERVICE_ACCEPT_SHUTDOWN
            return accepted

        def SvcOther(self, control):  # noqa: N802
            return None

        def SvcOtherEx(self, control, event_type, data):  # noqa: N802
            return self.SvcOther(control)

        def ReportServiceStatus(self, status, waitHint=5000, win32ExitCode=0, svcExitCode=0):  # noqa: N802
            self.statuses.append((status, waitHint))


    class _PyError(Exception):
        pass


    _module("pywintypes", error=_PyError)
    _module("servicemanager", LogMsg=lambda *a: None, EVENTLOG_INFORMATION_TYPE=4, PYS_SERVICE_STARTED=1)
    _module("win32api", GetSystemMetrics=lambda i: 0, CloseHandle=lambda h: None)
    _module("win32event", CreateEvent=lambda *a: _Event(), SetEvent=lambda e: setattr(e, "set", True),
            WaitForSingleObject=_wait, WAIT_TIMEOUT=258)
    _module("win32serviceutil", ServiceFramework=ServiceFramework)
    _module("win32ts")

    import ark_watchdog as W
    import app_main
    from ark_relay.features import machinecheck as mc
    from ark_relay.features import phone
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import machinechecks as sysmc
    from ark_relay.features import errwatch

    # ---------------------------------------------------------------- relay.log and #11

    NOW = datetime(2026, 10, 11, 14, 27, tzinfo=SERVER_TZ)


    def logline(stamp, msg, level="INFO", name="ark.service"):
        return f"{stamp} {level:<7} {name}  {msg}"


    START = "服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）"
    MARK = "中继代码版本 v20261011042937"
    BEFORE = [
        logline("10-11 13:40:02", START), logline("10-11 13:40:02", MARK),
        logline("10-11 13:40:31", "📱 已上报状态到手机（开机；今天 ntfy 已用 30 条）"),
        logline("10-11 14:25:10", "收到停止通知（Windows 关机）"),
    ]
    BOOT_NOW = [logline("10-11 14:26:04", START), logline("10-11 14:26:04", MARK)]
    DOG = [logline("10-11 14:25:31", app_main.STOP_PUSH_START, name="ark.app.stop_push"),
           logline("10-11 14:25:33", "📱 已上报状态到手机（停止前；今天 ntfy 已用 31 条）", name="ark.app.stop_push")]


    class N:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body, alert))
            return []

        def alert_log(self):
            return None


    def judge11(lines):
        d = tmpdir()
        f = d / "relay.log"
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sysmc._SESSION.clear()
        got = dict(mc.judge(d, "boot", {"log_file": str(f)}, notifier=N(), now=NOW))
        return got.get("#11")


    print("[a. 14:25: stop notice, the relay's push cut off, the watchdog's push after it -> #11 passes]")
    r = judge11(BEFORE + DOG + BOOT_NOW)
    check("#11 passed", r and r.status, mc.PASS)
    check("the evidence names the watchdog's line", "看门服务代发" in (r.evidence if r else ""), True)

    print("[a. the same log without the watchdog's line -> #11 still fails]")
    r = judge11(BEFORE + BOOT_NOW)
    check("#11 failed", r and r.status, mc.FAIL)
    check("as before: the relay stopped first", "中继先停下了" in (r.evidence if r else ""), True)

    print("[a. the watchdog tried and did not get it out -> fails with its reason]")
    r = judge11(BEFORE + [DOG[0], logline("10-11 14:25:41", "状态没能上报到手机（停止前）：COS 403；手机上留着上一份状态",
                                         level="WARNING", name="ark.app.stop_push")] + BOOT_NOW)
    check("#11 failed", r and r.status, mc.FAIL)
    check("with the reason", "COS 403" in (r.evidence if r else ""), True)

    print("[a. no stop notice (the relay ended before logging it), the watchdog's push there -> passes]")
    r = judge11(BEFORE[:3] + DOG + BOOT_NOW)
    check("#11 passed", r and r.status, mc.PASS)
    r = judge11(BEFORE[:3] + BOOT_NOW)
    check("without it: still the old failure", r and r.status, mc.FAIL)

    CUT = logline("10-11 14:25:20", "停止前那份状态 10 秒还没发完，中继不再等，手机上可能还是上一份状态")
    SVC_STOP = BEFORE[:3] + [logline("10-11 14:25:10", "收到停止通知（停止中继）"), CUT]
    BOOT_PUSHED = BOOT_NOW + [logline("10-11 14:26:50", "📱 已上报状态到手机（开机；今天 ntfy 已用 32 条）")]
    held = []
    hook = logging.Handler()
    hook.emit = lambda rec: held.append(rec)
    sysmc._log_system.setLevel(logging.INFO)
    sysmc._log_system.addHandler(hook)

    print("[d. a service stop's push cut off, the restarted relay's boot push went out -> passes, closed as INFO]")
    r = judge11(SVC_STOP + BOOT_PUSHED)
    check("#11 passed", r and r.status, mc.PASS)
    check("the evidence names the boot push", "开机" in (r.evidence if r else "") and "重启后" in (r.evidence if r else ""), True)
    check("service restart boot-push closure logs INFO (not pushed, not daily-report error)",
          (any(x.levelno == logging.INFO and "开机那份已送到手机" in x.getMessage() for x in held),
           [x for x in held if x.levelno == logging.WARNING]),
          (True, []))

    print("[d. the same cut-off at a Windows shutdown -> still fails: its next start is the next power-on]")
    r = judge11(BEFORE + [CUT] + BOOT_PUSHED)
    check("#11 failed", r and r.status, mc.FAIL)

    print("[d. a service stop's push cut off and no boot push after it -> fails]")
    r = judge11(SVC_STOP + BOOT_NOW)
    check("#11 failed", r and r.status, mc.FAIL)
    sysmc._log_system.removeHandler(hook)

    print("[a+b. the real stop_push writes the line #11 reads into relay.log]")
    LOG.write_text("\n".join(BEFORE) + "\n", encoding="utf-8")
    published = []


    class FakeBox:
        """phone.Mailbox as stop_push builds it; publish succeeds unless told otherwise."""
        ok = True

        def __init__(self, topic, pin, state_dir, cos=None):
            self.enabled, self.last_error, self.last_route = True, "", "腾讯云"
            self.quota = phone.Quota(state_dir)

        def publish(self, body):
            published.append(body)
            if not FakeBox.ok:
                self.last_error = "COS 403"
            return FakeBox.ok


    phone.Mailbox = FakeBox
    phone.state_payload = lambda cfg, state_dir: {"at": 1}
    code = app_main.stop_push()
    check("sent: exit code 0", code, 0)
    check("one publish", len(published), 1)
    text = LOG.read_text(encoding="utf-8")
    check("the start line is in relay.log", app_main.STOP_PUSH_START in text, True)
    check("the push line under ark.stop_push",
          bool(re.search(r"INFO\s+ark\.app\.stop_push\s+📱 已上报状态到手机（停止前；", text)), True)
    check("send_state left the marker", phone.stop_pushed(DATA / "state"), True)
    r = judge11(text.splitlines() + BOOT_NOW)
    check("#11 on that relay.log passes", r and r.status, mc.PASS)

    print("[b. the relay's own push got out (marker) -> stop_push sends nothing]")
    n0 = len(published)
    check("skipped: exit code 2", app_main.stop_push(), 2)
    check("no publish", len(published), n0)
    check("says so in relay.log", app_main.STOP_PUSH_SKIP in LOG.read_text(encoding="utf-8"), True)

    print("[b. the phone channel coming up clears the marker; a failed push leaves none]")
    phone.clear_stop_pushed(DATA / "state")
    check("cleared", phone.stop_pushed(DATA / "state"), False)
    FakeBox.ok = False
    check("not sent: exit code 1", app_main.stop_push(), 1)
    check("no marker after a failed push", phone.stop_pushed(DATA / "state"), False)
    check("the failure line #11 reads",
          "状态没能上报到手机（停止前）：COS 403" in LOG.read_text(encoding="utf-8"), True)
    _today = datetime.now(tz=__import__("ark_relay.core.config", fromlist=["SERVER_TZ"]).SERVER_TZ).strftime("%Y-%m-%d")
    check("errwatch took the failure line (it goes to the group)",
          any("状态没能上报到手机" in str(r.get("line")) for r in errwatch.day_faults(DATA / "state", _today)), True)
    FakeBox.ok = True

    print("[b. a send that hangs: stop_push gives up after its time and says so]")
    gate = threading.Event()
    real_send = phone.send_state
    phone.send_state = lambda *a, **k: (gate.wait(5), (True, None, ""))[1]
    check("not sent: exit code 1", app_main.stop_push(wait_s=0.2), 1)
    gate.set()
    phone.send_state = real_send
    check("the failure line names the wait",
          "状态没能上报到手机（停止前）：看门服务等了 0 秒还没发完" in LOG.read_text(encoding="utf-8"), True)

    print("[b. boot_stages clears the marker when the phone channel comes up]")
    src = (RELAY / "ark_relay" / "features" / "phone.py").read_text(encoding="utf-8")
    body = src[src.index("def _start_phone_channel"):src.index("def publish_state")]
    check("clear_stop_pushed(cfg.state_dir) in _start_phone_channel", "clear_stop_pushed(cfg.state_dir)" in body, True)
    check("publish_state goes through phone.send_state", "send_state(box, cfg, why, log)" in src, True)

    print("[b. the watchdog runs stop-push once per shutdown, after a running relay had its seconds]")


    class Clock:
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            return self.t

        def sleep(self, s):
            self.t += s


    for label, alive, want_waited in [("relay gone already", [False], 0.0),
                                      ("relay exits after 1 s", [True, True, False], 1.0),
                                      ("relay never exits: waits ALIVE_WAIT_S, then still once", [True], W.ALIVE_WAIT_S)]:
        clock, pushes = Clock(), []
        states = list(alive)
        got = W.last_push(relay_running=lambda: states.pop(0) if len(states) > 1 else states[0],
                          push=lambda timeout: pushes.append(timeout) or "送到了", sleep=clock.sleep, clock=clock)
        check(f"{label}: one push", len(pushes), 1)
        check(f"{label}: with PUSH_TIMEOUT_S", pushes[0], W.PUSH_TIMEOUT_S)
        check(f"{label}: waited", clock.t, want_waited)
        check(f"{label}: its result logged", got, "送到了")

    print("[b. the command the watchdog runs is one app_main knows, through launch.py]")
    dog_src = (ROOT / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8")
    check("launch.py stop-push", '"launch.py"), "stop-push"]' in dog_src, True)
    check("app_main dispatches stop-push", '"stop-push": _stop_push_exit' in (RELAY / "app_main.py").read_text(encoding="utf-8"),
          True)
    check("the same session-ending file name", W.SESSION_ENDING.name, app_main.SESSION_ENDING)
    check("the send fits in the command's time", app_main.STOP_PUSH_WAIT_S < W.PUSH_TIMEOUT_S, True)
    check("wait + command fit in the preshutdown time", W.ALIVE_WAIT_S + W.PUSH_TIMEOUT_S < W.PRESHUTDOWN_MS / 1000, True)

    print("[c. the watchdog accepts PRESHUTDOWN (and still STOP and SHUTDOWN)]")
    svc = W.WatchdogService(["ArkRelayWatchdog"])
    acc = svc.GetAcceptedControls()
    check("SERVICE_ACCEPT_PRESHUTDOWN", bool(acc & win32service.SERVICE_ACCEPT_PRESHUTDOWN), True)
    check("SERVICE_ACCEPT_STOP", bool(acc & win32service.SERVICE_ACCEPT_STOP), True)
    check("SERVICE_ACCEPT_SHUTDOWN", bool(acc & win32service.SERVICE_ACCEPT_SHUTDOWN), True)

    print("[c. the PRESHUTDOWN handler flags, reports STOP_PENDING, sets the stop event and returns]")
    calls = []
    W.last_push = lambda **k: calls.append(1) or "送到了"
    W._log = lambda line: calls.append(line)
    check("handler returns NO_ERROR (None)", svc.SvcOtherEx(win32service.SERVICE_CONTROL_PRESHUTDOWN, 0, None), None)
    check("flag set", svc.watch.shutting_down, True)
    check("stop event set", svc.stop_event.set, True)
    check("STOP_PENDING with the preshutdown time as wait hint",
          svc.statuses[-1], (win32service.SERVICE_STOP_PENDING, W.PRESHUTDOWN_MS))
    check("no push inside the handler", calls.count(1), 0)
    svc.SvcDoRun()
    check("SvcDoRun pushed once after the loop", calls.count(1), 1)
    check("and logged it", any(isinstance(c, str) and c.startswith("Windows 关机，停止前那份状态：送到了") for c in calls), True)

    print("[c. a plain stop (sc stop, the installer) pushes nothing]")
    svc2 = W.WatchdogService(["ArkRelayWatchdog"])
    calls.clear()
    svc2.SvcStop()
    svc2.SvcDoRun()
    check("no push", calls.count(1), 0)
    check("other controls still go to pywin32's SvcOtherEx", svc2.SvcOtherEx(0x80, 0, None), None)

    print("[c. once Windows is going down the watchdog does not start the relay again]")
    started = []
    W.main_running = lambda: False
    W.someone_logged_on = lambda: True
    W.start_main = lambda: started.append(1) or True
    w = W.Watch()
    w.tick(30.0)
    check("relay gone, nothing going down: started", len(started), 1)
    w = W.Watch()
    w.shutting_down = True
    w.tick(30.0)
    check("after PRESHUTDOWN: not started", len(started), 1)
    W.SESSION_ENDING.write_text("x", encoding="utf-8")
    w = W.Watch()
    w.tick(30.0)
    check("the relay's session is ending (its marker): not started", len(started), 1)
    os.utime(W.SESSION_ENDING, (0, 0))
    w.tick(60.0)
    check("a marker older than ENDING_HOLD_S no longer holds it", len(started), 2)
    check("app_main deletes the marker at start and writes it on WM_ENDSESSION",
          ("(DATA / SESSION_ENDING).unlink" in (RELAY / "app_main.py").read_text(encoding="utf-8"),
           "_mark_session_ending()" in (RELAY / "app_main.py").read_text(encoding="utf-8")), (True, True))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_deploy_watch():
    import importlib.util
    import tempfile
    from datetime import datetime

    ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("deploy_watch", ROOT / "scripts/windows/deploy_watch.py")
    dw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dw)


    CRASH_LOOP = """10-10 16:27:59 INFO    ark.service  系统的程序启动通知已取消订阅（用了 0.0 秒），中继停下时不留订阅
10-10 16:28:03 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）
10-10 16:28:03 INFO    ark.service  中继代码版本 v20261010082756
10-10 16:28:12 INFO    ark.service  📱 已上报状态到手机（开机；今天 ntfy 已用 44 条）
10-10 16:28:14 INFO    ark.phone  📱 ntfy 今天这个 IP 已用 44 条（中继自己发的 43 条）
10-10 16:28:21 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）
10-10 16:28:21 INFO    ark.service  中继代码版本 v20261010082756
"""

    SELFCHECK_RED = """10-10 16:33:03 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）
10-10 16:33:03 INFO    ark.service  中继代码版本 v20261010083249
10-10 16:33:17 INFO    ark.service  开机自检 ✓ 看得到机器上在跑哪些程序
10-10 16:33:17 WARNING ark.service  开机自检 ✗ 读得到每个程序是怎么启动的（系统自带的那条路）：读不到——看门狗只能靠调度程序有没有应答来判断，它退出时不会立刻察觉
10-10 16:33:17 INFO    ark.service  开机自检 ✓ 调度程序有应答
10-10 16:33:19 INFO    ark.service  已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄
"""

    GOOD = """10-10 16:05:30 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）
10-10 16:05:30 INFO    ark.service  中继代码版本 v20261010080447
10-10 16:05:44 INFO    ark.service  开机自检 12 项全部成立
10-10 16:05:46 INFO    ark.service  已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄
10-10 16:05:46 INFO    ark.service  已挂上 AUTO-MAS 进程句柄，它一退出立即拉起
"""


    def j(text, since, *, elapsed=120, total=120, pids=(4242,), states=("RUNNING",), events=(), mode="deploy", version="",
          cap=None):
        lines = dw.lines_since(text, datetime.strptime(since, "%Y-%m-%d %H:%M:%S"))
        kw = {} if cap is None else {"preupdate_cap": cap}
        return dw.judge(lines, pids=list(pids), states=list(states), events=list(events),
                        elapsed=elapsed, total=total, mode=mode, version=version, **kw)


    print("[16:28 那一版：启动几秒就崩、又起来]")
    v, why = j(CRASH_LOOP, "2026-10-10 16:28:02", elapsed=20)
    check("不等满两分钟就判失败", v, "fail")
    check("说是重启了", "又重启" in why)
    check("上一个进程停下前的行不算", j(CRASH_LOOP, "2026-10-10 16:28:02", elapsed=10)[0], "fail")
    check("只看到第一次启动时还在等", j(CRASH_LOOP.split("10-10 16:28:21")[0], "2026-10-10 16:28:02", elapsed=10)[0], "wait")
    check("进程号变了也算重启", j(GOOD, "2026-10-10 16:05:29", elapsed=30, pids=(4242, 4242, 5120))[0], "fail")
    check("系统日志 7031 也算", j(GOOD, "2026-10-10 16:05:29", elapsed=30, events=("事件 7031（2026-10-10T07:05:50 UTC）",))[0], "fail")
    unread = j(GOOD, "2026-10-10 16:05:29", events=("系统日志读不到（OSError），判不了中继有没有意外退出",))
    check("系统日志读不到：判失败，不当没崩", unread, ("fail", "系统日志读不到（OSError），判不了中继有没有意外退出"))
    check("服务停了算", j(GOOD, "2026-10-10 16:05:29", elapsed=30, states=("RUNNING", "STOPPED"))[0], "fail")

    print("\n[16:33 那一版：起来了，但自检有 ✗、没挂上句柄]")
    v, why = j(SELFCHECK_RED, "2026-10-10 16:33:02", elapsed=20)
    check("自检一出 ✗ 就判失败", v, "fail")
    check("说出是哪一项", why.startswith("开机自检有项不成立：读得到每个程序是怎么启动的"))
    v, why = j(SELFCHECK_RED.replace("WARNING ark.service  开机自检 ✗", "INFO    ark.service  开机自检 ✓"),
               "2026-10-10 16:33:02")
    check("没有 ✗、但两分钟内没等到「全部成立」和句柄：失败", v, "fail")
    check("说缺哪两行", "全部成立" in why and "已挂上 AUTO-MAS 进程句柄" in why)

    print("\n[正常的一次：两分钟里一次启动、自检全过、挂上句柄]")
    check("没满实测崩溃间隔：继续盯", j(GOOD, "2026-10-10 16:05:29", elapsed=20)[0], "wait")
    check("满了实测崩溃间隔、三项都齐：通过，不再干等两分钟", j(GOOD, "2026-10-10 16:05:29", elapsed=25)[0], "ok")
    check("满两分钟：通过", j(GOOD, "2026-10-10 16:05:29")[0], "ok")
    check("一行都没有：两分钟到了算失败", j("", "2026-10-10 16:05:29")[0], "fail")

    print("\n[10-16 02:33 部署重启正好是当天第一次开机：预更新在跑，句柄要等它跑完才挂]")
    PREUPDATE_1016 = r"""10-16 02:33:29 INFO    ark.service  服务模式启动，监视 D:\ark\automas\history（变更即处理，兜底 30 秒）
10-16 02:33:29 INFO    ark.service  中继代码版本 v20261015183310
10-16 02:33:30 INFO    ark.selfupdate  COS 上最新一次部署是 v20261015101332，本机 v20261015183310，已是最新，不再问 GitHub
10-16 02:33:30 INFO    ark.notify  不推送（日报或手机页已有）：🔄 中继已更新 ｜ 刚刚生效 版本 v20261015101332 → v20261015183310  - 中继读终末地（MaaEnd）任务说明文件变快了：这些文件九成以上本来就是标准格式，现在直接读，只有带注释的那几个才逐字清理。在 Mac 上量：以前每次开机要把 4.7 MB 逐字过五遍，约 1.5 秒白白耗在这上面，现在不到 0.2 秒。读出来的内容和以前一字不差，手机上看到的选项、写配置的校验都不变。  更
10-16 02:33:30 INFO    ark.service  更新说明已记入当天日报（v20261015183310）
10-16 02:33:33 INFO    ark.macpush  报警直送 Mac 没送到（URLError: <urlopen error [WinError 10061] 由于目标计算机积极拒绝，无法连接。>），13 条留着，下一条报警或下次开机再补
10-16 02:33:35 INFO    ark.service  上游导出代码核对：三处都和登记的一致
10-16 02:33:39 INFO    ark.phone  状态 44167 字节，压缩到 13023 字节
10-16 02:33:41 INFO    ark.service  📱 已上报状态到手机（开机；今天 ntfy 已用 148 条）
10-16 02:33:41 INFO    ark.machinecheck  上机核对 #10 过了：02:33:39 森空岛会话交给手机（6 项都在）；森空岛给的终末地体力：curStamina=134 maxStamina=360 maxTs=1792186851
10-16 02:33:43 INFO    ark.phone  📱 手机通道已连上（长连接，不轮询）
10-16 02:33:43 INFO    ark.phone  📱 ntfy 今天这个 IP 已用 148 条（中继自己发的 143 条）
10-16 02:33:46 INFO    ark.service  开机：终末地开游戏：开游戏助手的入口已指向 C:\Program Files\ArkRelay\versions\20261015183310
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 看得到机器上在跑哪些程序
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 读得到每个程序是怎么启动的（系统自带的那条路）
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序有应答
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序的后台程序在跑
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序的开机任务计划还在
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序还管着两个游戏客户端的更新（明日方舟、鸣潮）
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 队列的排期读得到、至少一条开着定时
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 中继要读的调度程序设置都在原处
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 日志文件所在目录能写
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 状态目录能写
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 调度程序的历史目录在
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 至少一条通知通道配好了
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 手机通道配好了
10-16 02:33:46 INFO    ark.service  开机自检 ✓ 中继装了读图组件（读官方长图（卡池几点几分）、压缩报警截图）
10-16 02:33:46 INFO    ark.service  开机自检 14 项全部成立
10-16 02:33:46 INFO    ark.preupdate  预更新：AUTO-MAS 后端自报 v5.7.0-beta.3（res/version.json 还写着 v5.5.0-beta.2，新版不再改那个文件）
10-16 02:33:46 INFO    ark.preupdate  预更新：AUTO-MAS 有更新 v5.7.0-beta.3 → v5.7.0-beta.4，开始下载
10-16 02:34:10 INFO    ark.preupdate  预更新：更新包就绪（UpdatePack_v5.7.0-beta.4.zip），开始安装
10-16 02:34:58 INFO    ark.preupdate  预更新：AUTO-MAS 已更新到 v5.7.0-beta.4（后端重启后自报）
10-16 02:34:58 INFO    ark.service  调度程序升级到 v5.7.0-beta.4 后，中继要读的调度程序设置都在原处：成立
10-16 02:34:58 INFO    ark.notify  推送已送到：info 路，Server酱 收下 ｜ 🆕 预更新
10-16 02:35:02 INFO    ark.preupdate  预更新：中继服务没有拿控制台令牌的权限（这台机器上一直如此），直接用计划任务启动 ok-ww.exe
10-16 02:35:07 INFO    ark.preupdate  预更新：已通过计划任务在交互会话启动 ok-ww.exe
10-16 02:35:07 INFO    ark.preupdate  预更新：已启动 OK-WW（已临时关掉自动开游戏），最多 240 秒
"""
    # Before anything imports ark_relay: once imported, a later root would read the cached module.
    _bad = dw.preupdate_cap_s(ROOT / "no-such-dir")
    check("读不到中继代码：上限 0，说清原因", (_bad[0], "ModuleNotFoundError" in _bad[1]), (0.0, True))
    CAP, CAP_WHY = dw.preupdate_cap_s(ROOT / "relay")
    sys.path.insert(0, str(ROOT / "relay"))
    from ark_relay.features import preupdate as _pre
    check("预更新时长上限读的是中继自己的 worst_case_seconds()", (CAP, CAP_WHY), (_pre.worst_case_seconds(), ""))
    check("上限比两分钟长得多（AUTO-MAS 下载 600 秒、OK-WW 240 秒都在里面）", CAP > 600 + 240, True)
    S1016 = "2026-10-16 02:33:28"
    v, why = j(PREUPDATE_1016, S1016, elapsed=125, total=120, cap=CAP)
    check("(i) 只缺句柄、预更新在跑：两分钟过了继续等，不退回", v, "wait")
    check("(i) 说明在等预更新", "预更新" in why, True)
    check("没给上限（读不到中继代码）：照旧两分钟判失败", j(PREUPDATE_1016, S1016, elapsed=125, total=120)[0], "fail")
    check("(ii) 预更新期间又重启：马上失败",
          j(PREUPDATE_1016 + PREUPDATE_1016.splitlines()[0] + "\n", S1016, elapsed=125, total=120, cap=CAP)[0], "fail")
    check("预更新期间进程号变了：马上失败",
          j(PREUPDATE_1016, S1016, elapsed=125, total=120, cap=CAP, pids=(4242, 5120))[0], "fail")
    check("预更新期间系统日志记下意外退出：马上失败",
          j(PREUPDATE_1016, S1016, elapsed=125, total=120, cap=CAP, events=("事件 7031（2026-10-15T18:34:00 UTC）",))[0], "fail")
    red = PREUPDATE_1016.replace("INFO    ark.service  开机自检 ✓ 调度程序有应答",
                                 "WARNING ark.service  开机自检 ✗ 调度程序有应答")
    check("预更新在跑但自检有 ✗：马上失败", j(red, S1016, elapsed=30, total=120, cap=CAP)[0], "fail")
    v, why = j(PREUPDATE_1016, S1016, elapsed=120 + CAP + 1, total=120, cap=CAP)
    check("(iii) 超过预更新最长时长还没句柄：失败", v, "fail")
    check("(iii) 说清超过了预更新最长时长", "预更新最长" in why and "已挂上 AUTO-MAS 进程句柄" in why, True)
    no_selfcheck = "\n".join(ln for ln in PREUPDATE_1016.splitlines() if "全部成立" not in ln)
    check("还缺「全部成立」时不因预更新多等", j(no_selfcheck, S1016, elapsed=125, total=120, cap=CAP)[0], "fail")
    check("句柄挂上了：通过", j(PREUPDATE_1016 + "10-16 02:37:08 INFO    ark.service  已挂上 AUTO-MAS 进程句柄，它一退出立即拉起\n",
                              S1016, elapsed=220, total=120, cap=CAP)[0], "ok")
    check("没给代码目录：上限 0", dw.preupdate_cap_s(None), (0.0, "没给中继代码目录"))

    got = []
    real_watch = dw.watch
    dw.watch = lambda *a: got.append(a) or 0
    try:
        dw.main(["deploy_watch.py", "watch", "relay.log", S1016, "120", "deploy", "--pkg", "--root", "C:\\A B\\versions\\9"])
    finally:
        dw.watch, dw.PKG = real_watch, False
    check("--root 传到 watch，其余参数位置不变", got, [("relay.log", S1016, 120.0, "deploy", "", "C:\\A B\\versions\\9")])
    pkg_sh = (ROOT / "scripts/mac/lib/deploy-pkg.sh").read_text(encoding="utf-8")
    check("安装版部署把刚起来的版本文件夹交给盯梢", '"$WATCH_S" deploy --pkg \\\n      --root "$APP_WIN\\\\versions\\\\$NEW"' in pkg_sh, True)
    check("老服务部署也交代码目录", "$WATCH_S deploy --root ${REMOTE_DIR" in (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8"), True)

    print("\n[退回之后：一次启动、版本是上一版]")
    check("版本对：通过", j(GOOD, "2026-10-10 16:05:29", total=60, mode="rollback", version="v20261010080447")[0], "ok")
    check("状态表里的版本号不带 v、日志里带 v：算对上（10-10 演练）",
          j(GOOD, "2026-10-10 16:05:29", total=60, mode="rollback", version="20261010080447")[0], "ok")
    check("版本不对：失败", j(GOOD, "2026-10-10 16:05:29", total=60, mode="rollback", version="v20261010083249")[0], "fail")
    check("退回后又重启：失败", j(CRASH_LOOP, "2026-10-10 16:28:02", elapsed=20, total=60, mode="rollback",
                              version="v20261010082756")[0], "fail")

    print("\n[存一份、放回去]")
    with tempfile.TemporaryDirectory() as td:
        root, backup = Path(td) / "ark-relay", Path(td) / "prev"
        (root / "ark_relay" / "__pycache__").mkdir(parents=True)
        (root / "ark_relay" / "core").mkdir()
        (root / "ark_relay" / "core" / "desktop.py").write_text("old procs", encoding="utf-8")
        (root / "service.py").write_text("old service", encoding="utf-8")
        (root / "ark_relay" / "__pycache__" / "procs.cpython-314.pyc").write_bytes(b"x")
        (root / ".env").write_text("secret", encoding="utf-8")
        info = dw.snapshot(root, backup, ["ark_relay/core/desktop.py", "service.py", "ark_relay/brand_new.py"], "v1")
        check("存下两份旧文件、记下一份新文件", (sorted(info["kept"]), info["new"]),
              (["ark_relay/core/desktop.py", "service.py"], ["ark_relay/brand_new.py"]))
        (root / "ark_relay" / "core" / "desktop.py").write_text("new procs", encoding="utf-8")
        (root / "service.py").write_text("crashing service", encoding="utf-8")
        (root / "ark_relay" / "brand_new.py").write_text("new file", encoding="utf-8")
        info = dw.restore(root, backup)
        check("旧文件放回", ((root / "ark_relay" / "core" / "desktop.py").read_text(encoding="utf-8"),
                           (root / "service.py").read_text(encoding="utf-8")), ("old procs", "old service"))
        check("新加的文件删掉", (root / "ark_relay" / "brand_new.py").exists(), False)
        check("旧的 .pyc 清掉", (root / "ark_relay" / "__pycache__").exists(), False)
        check("没碰别的文件", (root / ".env").read_text(encoding="utf-8"), "secret")
        check("记得上一版的版本号", info["code_version"], "v1")
        dw.snapshot(root, backup, ["service.py"], "v2")
        check("再存一次是新的一份，不叠旧的", sorted(p.name for p in (backup / "files").rglob("*") if p.is_file()), ["service.py"])

    print("\n[部署脚本的顺序：先存再推；盯完才发 COS、才说部署完成；失败退回]")
    sh = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
    pos = {k: sh.find(k) for k in ("snapshot ${REMOTE_DIR", "tar --no-mac-metadata -czf - $CHANGED", "\nrestart_service\n",
                                    "$WATCH_S deploy", "publish-cos.py\"", "echo \"✅ 部署完成", "restore ${REMOTE_DIR", "\n    exit 12", "\n  exit 13")}
    check("每一段都在", [k for k, v in pos.items() if v < 0], [])
    check("存档在推文件之前", pos["snapshot ${REMOTE_DIR"] < pos["tar --no-mac-metadata -czf - $CHANGED"])
    check("盯梢在重启之后、发 COS 之前", pos["\nrestart_service\n"] < pos["$WATCH_S deploy"] < pos["publish-cos.py\""])
    check("盯梢在「部署完成」之前", pos["$WATCH_S deploy"] < pos["echo \"✅ 部署完成"])
    check("没稳住就退回，退回后报失败", pos["$WATCH_S deploy"] < pos["restore ${REMOTE_DIR"] < pos["\n    exit 12"] < pos["\n  exit 13"])
    check("默认盯 120 秒", 'WATCH_S="${WATCH_S:-120}"' in sh)

    print()
    print("[deploy-relay.sh sets WATCH_S before the installed-relay steps read it]")
    _sh = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
    check("WATCH_S default comes before lib/deploy-pkg.sh is sourced",
          0 <= _sh.find('WATCH_S="${WATCH_S:-') < _sh.find('lib/deploy-pkg.sh"'), True)

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_publish_cos_args():
    """publish-cos.py: only a bare call publishes, and standalone runs refuse while the game PC is online on an older version."""
    import importlib.util
    import os
    import subprocess as _sp
    import types as _types

    ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("publish_cos", ROOT / "scripts/mac/publish-cos.py")
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)

    reached = []
    probed = []

    class _Stop(Exception):
        pass

    def _client():
        reached.append(True)
        raise _Stop

    orig_client = pc._client
    orig_online = pc._online_check
    orig_relay = pc.RELAY
    orig_env = os.environ.get("ARK_FROM_DEPLOY_RELAY")
    d = tmpdir()
    (d / "manifest.json").write_text('{"version": 20261124015958, "files": {}}', encoding="utf-8")
    try:
        os.environ.pop("ARK_FROM_DEPLOY_RELAY", None)
        pc._client = _client
        pc.RELAY = d
        pc._online_check = lambda ver: probed.append(ver) or None

        for args, rc in ((["--help"], 0), (["-h"], 0), (["--dry-run"], 2), (["--check", "x"], 2)):
            reached.clear()
            probed.clear()
            check(f"{' '.join(args)}：不连 COS、不探测、退出码 {rc}",
                  (pc.main(list(args)), reached, probed), (rc, [], []))

        reached.clear()
        probed.clear()
        try:
            pc.main(["--check"])
        except _Stop:
            pass
        check("--check：跳过在线探测、照常连 COS", (reached, probed), ([True], []))

        reached.clear()
        probed.clear()
        try:
            pc.main([])
        except _Stop:
            pass
        check("不带参数（离线放行）：先查在线状态、再连 COS", (reached, probed), ([True], [20261124015958]))

        reached.clear()
        probed.clear()
        pc._online_check = lambda ver: probed.append(ver) or "游戏机当前在线且尚未装上"
        check("不带参数（在线旧版）：拒发、不连 COS、退出码 1",
              (pc.main([]), reached, probed), (1, [], [20261124015958]))

        reached.clear()
        probed.clear()
        os.environ["ARK_FROM_DEPLOY_RELAY"] = "1"
        try:
            pc.main([])
        except _Stop:
            pass
        check("ARK_FROM_DEPLOY_RELAY=1：跳过在线探测直接连 COS", (reached, probed), ([True], []))
        os.environ.pop("ARK_FROM_DEPLOY_RELAY", None)

        # Test _online_check itself (cross-platform: mock socket + subprocess, zero network).
        pc._online_check = orig_online
        orig_conn = pc.socket.create_connection
        orig_run = pc.subprocess.run

        class _DummySock:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        try:
            def _offline(*a, **kw):
                raise OSError("timed out")

            pc.socket.create_connection = _offline
            check("_online_check：机器离线放行", pc._online_check(20261124015958), None)

            pc.socket.create_connection = lambda *a, **kw: _DummySock()
            pc.subprocess.run = lambda *a, **kw: _types.SimpleNamespace(returncode=0, stdout="20261123025410\n")
            msg = pc._online_check(20261124015958)
            check("_online_check：在线且旧版拒发并指明 deploy-relay.sh",
                  bool(msg) and "deploy-relay.sh" in msg and "20261123025410" in msg, True)

            pc.subprocess.run = lambda *a, **kw: _types.SimpleNamespace(returncode=0, stdout="20261124015958\n")
            check("_online_check：在线且同版放行（COS 抖动补推）", pc._online_check(20261124015958), None)

            pc.subprocess.run = lambda *a, **kw: _types.SimpleNamespace(returncode=0, stdout="20261124015958-1\n")
            check("_online_check：在线且重部署同版后缀 -1 放行", pc._online_check(20261124015958), None)

            pc.subprocess.run = lambda *a, **kw: _types.SimpleNamespace(returncode=255, stdout="")
            check("_online_check：在线但 SSH 非零 fail-closed 拒发", bool(pc._online_check(20261124015958)), True)

            pc.subprocess.run = lambda *a, **kw: _types.SimpleNamespace(returncode=0, stdout="   \n")
            check("_online_check：在线但读空 fail-closed 拒发", bool(pc._online_check(20261124015958)), True)

            def _ssh_timeout(*a, **kw):
                raise _sp.TimeoutExpired("ssh", 10)

            pc.subprocess.run = _ssh_timeout
            check("_online_check：在线但 SSH 超时 fail-closed 拒发", bool(pc._online_check(20261124015958)), True)

            # Offline publish records pending_deploy.json after ok readback; ARK_FROM_DEPLOY_RELAY does not.
            import json as _json
            pend_file = d / "pending_deploy.json"
            orig_pend = os.environ.get("ARK_PENDING_DEPLOY")
            orig_put, orig_get = pc._put, pc._get
            try:
                os.environ["ARK_PENDING_DEPLOY"] = str(pend_file)
                os.environ.pop("ARK_FROM_DEPLOY_RELAY", None)
                pc._online_check = orig_online
                pc._client = lambda: _types.SimpleNamespace(probe=lambda: None)
                pc.socket.create_connection = _offline
                pc._put = lambda *a, **kw: None
                pc._get = lambda *a, **kw: _json.dumps({"version": 20261124015958}).encode("utf-8")
                pc.subprocess.run = lambda *a, **kw: _types.SimpleNamespace(returncode=0, stdout="deadbeef\n")
                check("离线单发 COS 成功返回 0", pc.main([]), 0)
                items = _json.loads(pend_file.read_text(encoding="utf-8"))
                check("离线单发 COS 写 pending_deploy.json", [x["version"] for x in items], ["20261124015958"])
                pend_file.unlink()
                os.environ["ARK_FROM_DEPLOY_RELAY"] = "1"
                check("deploy-relay.sh 内调用返回 0", pc.main([]), 0)
                check("deploy-relay.sh 内调用不写 pending_deploy.json", pend_file.exists(), False)
            finally:
                pc._put, pc._get = orig_put, orig_get
                if orig_pend is None:
                    os.environ.pop("ARK_PENDING_DEPLOY", None)
                else:
                    os.environ["ARK_PENDING_DEPLOY"] = orig_pend
        finally:
            pc.socket.create_connection = orig_conn
            pc.subprocess.run = orig_run
    finally:
        pc._client = orig_client
        pc._online_check = orig_online
        pc.RELAY = orig_relay
        if orig_env is None:
            os.environ.pop("ARK_FROM_DEPLOY_RELAY", None)
        else:
            os.environ["ARK_FROM_DEPLOY_RELAY"] = orig_env

    print()
    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_publish_cos_notes():
    """The COS bundle must hold the bytes the manifest names."""
    import hashlib
    import importlib.util
    import re

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay"))


    spec = importlib.util.spec_from_file_location("publish_cos", ROOT / "scripts" / "mac" / "publish-cos.py")
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)

    print("[发之前逐个核哈希]")
    d = tmpdir()
    notes = "这次改了什么\n".encode("utf-8")
    (d / "RELEASE-NOTES.md").write_bytes(notes)
    (d / "a.py").write_bytes(b"x = 1\n")
    manifest = {"files": {"RELEASE-NOTES.md": hashlib.sha1(notes).hexdigest(),
                          "a.py": hashlib.sha1(b"x = 1\n").hexdigest()}}
    pc.RELAY = d
    check("文件和清单一致：放行", pc.stale_files(manifest), [])
    (d / "RELEASE-NOTES.md").write_bytes(b"")
    check("说明被清空：拦下并点名", pc.stale_files(manifest), ["RELEASE-NOTES.md"])
    (d / "a.py").unlink()
    check("文件没了也拦", pc.stale_files(manifest), ["RELEASE-NOTES.md", "a.py"])

    print("\n[部署脚本：先发 COS，再清空说明；默认推 origin/main、清 CDN、快进顶层；COS 失败不清空]")
    sh = (ROOT / "scripts" / "mac" / "deploy-relay.sh").read_text(encoding="utf-8")
    pub = sh.index('"$MAC_PY" "$HERE/../scripts/mac/publish-cos.py"')
    m_clear = re.search(r'\n[ \t]*: > "\$NOTES"\n', sh)
    clear = m_clear.start() if m_clear else -1
    check("发 COS 在清空之前", clear > 0 and pub < clear, True)
    check("只发一次", sh.count('"$MAC_PY" "$HERE/../scripts/mac/publish-cos.py"'), 1)
    check("仅在该行前置 ARK_FROM_DEPLOY_RELAY=1（不全局 export）",
          'ARK_FROM_DEPLOY_RELAY=1 "$MAC_PY" "$HERE/../scripts/mac/publish-cos.py"' in sh
          and "export ARK_FROM_DEPLOY_RELAY" not in sh, True)
    check("不把公开仓库推送拆进 --push 开关，默认推 origin/main 并清 CDN 与快进顶层",
          "PUSH_GITHUB" not in sh
          and "push -q origin HEAD:refs/heads/main" in sh
          and 'purge-cdn.py" --no-wait' in sh
          and 'lib/ff-toplevel.sh"' in sh, True)
    check("COS 失败不清空说明且不提交清空提交",
          sh.count('if [ "$COS_OK" = 1 ]; then') >= 3, True)
    branch_chk = sh.index('if [ "$BRANCH" != main ]; then')
    mk_man = sh.index('"$MAC_PY" make-manifest.py > /dev/null')
    check("非 --dry-run 必须在 main 分支，且在 make-manifest 之前检查",
          branch_chk < mk_man, True)
    check("--dry-run 绝不调用 make-manifest.py 写脏 relay/manifest.json",
          'if [ "$DRY_RUN" = 0 ]; then\n  "$MAC_PY" make-manifest.py > /dev/null\nfi' in sh, True)

    print("\n[上传失败重试：10-05 两次部署都被链路打断（SSL EOF、HTTP 400），手动重发都成]")
    import io as _io
    import ssl
    import urllib.error


    class FakeCos:
        prefix, host = "relay", "bucket.cos.example"

        def __init__(self):
            self.signed = 0

        def authorization(self, method, key):
            self.signed += 1
            return f"sig{self.signed}"


    tries, slept = [], []
    real_urlopen, real_sleep = pc.urllib.request.urlopen, pc.time.sleep


    class Ok:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""


    def flaky(outcomes):
        def urlopen(req, timeout=0):
            tries.append(req.get_header("Authorization"))
            o = outcomes.pop(0)
            if o == "ok":
                return Ok()
            raise o
        return urlopen


    pc.time.sleep = slept.append
    try:
        eof = urllib.error.URLError(ssl.SSLEOFError(8, "EOF occurred in violation of protocol (_ssl.c:1129)"))
        bad = urllib.error.HTTPError("u", 400, "Bad Request", {}, _io.BytesIO(b"<Code>RequestTimeout</Code>"))
        pc.urllib.request.urlopen = flaky([eof, bad, "ok"])
        cos = FakeCos()
        pc._put(cos, "1/bundle.zip", b"x", "application/zip")
        check("SSL EOF、400 之后第三次成了", len(tries), 3)
        check("每次重新签名", tries, ["sig1", "sig2", "sig3"])
        check("中间等了 5、15 秒", slept, [5, 15])
        tries[:], slept[:] = [], []
        pc.urllib.request.urlopen = flaky([eof, eof, eof, eof])
        try:
            pc._put(FakeCos(), "1/bundle.zip", b"x", "application/zip")
            raised = ""
        except RuntimeError as exc:
            raised = str(exc)
        check("四次都不成：报错带原因", ("上传失败" in raised and "EOF" in raised, len(tries)), (True, 4))
        tries[:] = []
        denied = urllib.error.HTTPError("u", 403, "Forbidden", {}, _io.BytesIO(b"<Code>AccessDenied</Code>"))
        pc.urllib.request.urlopen = flaky([denied])
        try:
            pc._put(FakeCos(), "1/bundle.zip", b"x", "application/zip")
            raised = ""
        except RuntimeError as exc:
            raised = str(exc)
        check("403 不重试、原样报出", ("AccessDenied" in raised, len(tries)), (True, 1))
    finally:
        pc.urllib.request.urlopen, pc.time.sleep = real_urlopen, real_sleep


def _part_maaend_watchdog_startup_lines():
    """Startup log lines within the first 0-30 s before a new MaaEnd PID is checked
    must count as progress (stall kill after 10 min), not as a blind/unreadable log."""
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features import maaend_watchdog

    RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
    WAITING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "等待"}]}]}
    PID1, PID2 = 21260, 200

    def procs_for(pid):
        base = [("System", 4), ("Endfield.exe", 18800), ("go-service.exe", 21932), ("cpp-algo.exe", 21940)]
        return base if pid is None else [*base, ("MaaEnd.exe", pid)]

    class _Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []

    class _Rig:
        def __init__(self, *, snap=WAITING, pid=None):
            self.t = 1000.0
            self.snap = snap
            self.procs = procs_for(pid)
            self.lines = 0
            self.stamp = "2026-11-26 09:00:05"
            self.killed = []
            self.notes = _Notes()
            self.debug = tmpdir() / "debug"
            self.debug.mkdir()
            (self.debug / "go-service.stderr.log").write_text("", encoding="utf-8")
            agent = str(self.debug.parent / "agent")
            paths = {21932: os.path.join(agent, "go-service.exe"),
                     21940: os.path.join(agent, "cpp-algo.exe")}
            self.dog = maaend_watchdog.Watchdog(
                self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: self.snap,
                processes=lambda: self.procs,
                kill=lambda p, img: self.killed.append(p) or (True, ""),
                plugin_paths=lambda: paths, active=True)

        def step(self, dt, *, new_lines=0):
            self.t += dt
            self.lines += new_lines
            return self.dog.tick(self.lines, self.stamp)

        def stall(self, minutes=11):
            for _ in range(minutes):
                self.step(60)

    print("[WAITING -> 0-30s 内新进程打完启动日志即卡死：10 分钟后真杀，不误报读不到日志]")
    r = _Rig(snap=WAITING, pid=None)
    r.step(60)                                  # t=1060: 30 s check sees WAITING, lines=0
    r.snap, r.procs = RUNNING, procs_for(PID1)
    r.step(2, new_lines=15)                     # t=1062 (<30s): startup burst 1, early return
    r.step(3, new_lines=25)                     # t=1065 (<30s): startup burst 2, then hangs forever
    r.step(30)                                  # t=1095 (>=30s): first sight of PID1
    r.stall()
    check("结束后杀掉了卡死进程和插件", r.killed, [PID1, 21932, 21940])
    check("发的是卡死报警，不是读不到日志", [t for t, _, _ in r.notes.sent], [texts.MAAEND_STUCK_KILLED])

    print("\n[上一趟结束（pid=None，已有 500 行）-> 新进程 0-30s 启动日志后卡死：仍真杀]")
    r = _Rig(snap=RUNNING, pid=None)
    r.lines = 500
    r.step(60)                                  # pid is None -> _checked_lines=500
    r.procs = procs_for(PID1)
    r.step(5, new_lines=30)                     # <30s: new PID writes 30 lines then hangs
    r.step(30)                                  # first sight of PID1
    r.stall()
    check("真杀新 PID", r.killed[:1], [PID1])
    check("报卡死而非盲报警", [t for t, _, _ in r.notes.sent], [texts.MAAEND_STUCK_KILLED])

    print("\n[同 30s 窗内换 PID（prev_pid 非空）：旧 PID 退出前多写 5 行、新 PID 日志不可读 → 报盲报警，不盲杀]")
    r = _Rig(snap=RUNNING, pid=PID1)
    r.step(60, new_lines=10)                    # PID1 running, lines=10
    r.step(5, new_lines=5)                      # <30s: old PID1 writes 5 lines before exiting
    r.procs = procs_for(PID2)                   # new PID 200 starts with unreadable maafw.log
    r.step(30)                                  # first sight of PID 200 (lines still 15)
    r.stall(minutes=12)
    check("同窗换 PID 不把旧 PID 的 5 行算成新 PID 产出：不杀 PID 200", r.killed, [])
    check("同窗换 PID 触发盲报警而非卡死强杀", [t for t, _, _ in r.notes.sent], [texts.MAAEND_WATCH_BLIND])

    print("\n[snap=None 或 procs=None 故障后紧接新 PID 启动且日志不可读 → 报盲报警，不盲杀]")
    for kind in ("snap", "procs"):
        r = _Rig(snap=WAITING, pid=None)
        r.step(60)                              # clean WAITING check, baseline = 0
        if kind == "snap":
            r.snap = None
        else:
            r.snap, r.procs = RUNNING, None
        r.step(30, new_lines=5)                 # failed check invalidates _checked_lines; 5 lines from outage window
        r.snap, r.procs = RUNNING, procs_for(PID2)
        r.step(35)                              # recovered: first sight of PID 200, log unreadable afterward
        r.stall(minutes=12)
        check(f"{kind}=None 故障后不继承旧基线误杀 PID 200", r.killed, [])
        check(f"{kind}=None 故障后触发盲报警", [t for t, _, _ in r.notes.sent], [texts.MAAEND_WATCH_BLIND])

    print("\n[刚开机首跳无前置空闲检查：不凭首跳已有行数盲杀，首跳后再有新行卡死才真杀]")
    r = _Rig(snap=RUNNING, pid=PID1)
    r.step(60, new_lines=40)                    # first tick ever (since_last=-inf), no prior clean idle check
    r.stall(minutes=12)
    check("无前置空闲检查且首跳后无新行：不盲杀、报盲报警",
          (r.killed, [t for t, _, _ in r.notes.sent]), ([], [texts.MAAEND_WATCH_BLIND]))
    r2 = _Rig(snap=RUNNING, pid=PID1)
    r2.step(60, new_lines=40)
    r2.step(60, new_lines=10)                   # confirmed lines written after PID1 first seen
    r2.stall()
    check("首跳后确有新行再卡死：10 分钟后真杀",
          (r2.killed[:1], [t for t, _, _ in r2.notes.sent]), ([PID1], [texts.MAAEND_STUCK_KILLED]))

    print("\n[对照：新 PID 确实一行未读到（日志真读不到）→ 照旧报盲报警不杀]")
    r = _Rig(snap=WAITING, pid=None)
    r.lines = 50
    r.step(60)                                  # WAITING, baseline=50
    r.snap, r.procs = RUNNING, procs_for(PID1)
    r.step(5)                                   # 0 new lines
    r.step(30)                                  # first sight of PID1, still 50
    r.stall(minutes=12)
    check("真读不到日志：不杀", r.killed, [])
    check("真读不到日志：报盲报警", [t for t, _, _ in r.notes.sent], [texts.MAAEND_WATCH_BLIND])


if __name__ == "__main__":
    sys.exit(run_parts([_part_stop_push_watchdog, _part_deploy_watch, _part_publish_cos_args, _part_publish_cos_notes, _part_maaend_watchdog_startup_lines]))
