"""Stopping the relay: a denied stop, the stop event's manual reset, the stop push's errwatch budget, a slow network, the watchdog's push.

One part per former file, each run on its own (tests/_parts.py): test_stop_denied.py, test_stop_event_manual_reset.py, test_stop_push_errwatch_budget.py.
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


def _part_stop_denied():
    """app_main.stop(): a stop event this account may not set ends the task at once.

2026-10-11: on the cloud runner the relay ran as SYSTEM and the runner's admin could
not open its stop event (winerror 5). stop() took that for "event not made yet" and
waited its 40 s, exit 1, relay still up (package-windows runs 38095462157 and
38095838036). Now access denied ends the task (schtasks /end) straight away; only a
missing event (winerror 2, the relay still starting) is waited for.

    Formerly test_stop_denied.py.
    """

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    import app_main


    class Relay:
        """A fake relay: `answers` is what each ask() gets; it exits `exit_after` s after a
    stop that reached it (asked or the task ended)."""

        def __init__(self, answers, exit_after=3.0):
            self.t = 0.0
            self.answers = list(answers)
            self.exit_after = exit_after
            self.stop_at = None
            self.asks = 0
            self.ended_at = None

        def clock(self):
            return self.t

        def sleep(self, s):
            self.t += s

        def running(self):
            return self.stop_at is None or self.t < self.stop_at + self.exit_after

        def ask(self):
            self.asks += 1
            got = self.answers.pop(0) if self.answers else self.answers_last
            self.answers_last = got
            if got == "asked":
                self.stop_at = self.t
            return got

        def end_task(self):
            self.ended_at = self.t
            self.stop_at = self.t


    def stop(r):
        return app_main._stop(r.running, r.ask, r.end_task, sleep=r.sleep, clock=r.clock)


    print("[access denied: the task is ended at once, no 40 s wait]")
    r = Relay(["denied"], exit_after=1.0)
    check("result", stop(r), 0)
    check("task ended at the first ask", r.ended_at, 0.0)
    check("done in seconds", r.t <= 3.0, True)
    check("asked once", r.asks, 1)

    print("[event not made yet (relay starting): asked again, no task end]")
    r = Relay(["not yet", "not yet", "asked"])
    check("result", stop(r), 0)
    check("no task end", r.ended_at, None)
    check("asks", r.asks, 3)

    print("[normal stop]")
    r = Relay(["asked"])
    check("result", stop(r), 0)
    check("no task end", r.ended_at, None)

    print("[access denied and the task end does not take: 1 after STOP_WAIT_S, one end only]")
    r = Relay(["denied"], exit_after=10_000)
    ends = []
    r.end_task = lambda: ends.append(r.t)
    check("result", stop(r), 1)
    check("task ended once", len(ends), 1)
    check("gave up at STOP_WAIT_S", app_main.STOP_WAIT_S <= r.t <= app_main.STOP_WAIT_S + 1, True)

    print("[not running at all]")
    r = Relay([], exit_after=0)
    r.stop_at = -1.0
    check("result", stop(r), 0)
    check("never asked", r.asks, 0)

    print("[the hard end is written to the relay's log first (review round 9 #25)]")
    order = []
    r = Relay(["denied"], exit_after=1.0)
    real_end = r.end_task
    r.end_task = lambda: (order.append("end"), real_end())
    app_main._stop(r.running, r.ask, r.end_task, sleep=r.sleep, clock=r.clock,
                   note=lambda msg: order.append(("note", msg)))
    check("note before the end", [o if o == "end" else o[0] for o in order], ["note", "end"])
    check("note names the task and the account", app_main.MAIN_TASK in order[0][1] and "账号" in order[0][1],
          True)

    import os
    log = tmpdir() / "relay.log"
    log.write_text("10-11 08:00:00 INFO    ark.app  earlier line\n", encoding="utf-8")
    os.environ["ARK_LOG_FILE"] = str(log)
    app_main._log_line("停止请求被拒：测试")
    lines = log.read_text(encoding="utf-8").splitlines()
    check("earlier line kept", lines[0].endswith("earlier line"), True)
    check("one line added", len(lines), 2)
    check("relay's format, WARNING", " WARNING ark.app.stop  停止请求被拒：测试" in lines[1], True)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_stop_event_manual_reset():
    """停服务的事件必须是手动复位的（CreateEvent 第二个参数为 1）。

2026-09-07 09:02 部署停服务时，relay.log 里手机通道打了一整段 traceback
（AttributeError: 'NoneType' object has no attribute 'peek'）。
它的 except 里明明先问了 stop()，可 stop_event 是自动复位事件：
主循环、手机通道、心跳三个线程都用 WaitForSingleObject(…, 0) 轮它，
谁先看到谁把信号吃掉，其余线程看到的就是「没停」。手机通道于是把
被 close() 掐断的连接当成意外断线；心跳同理可能发不出下线。
2026-08-31 几次「卡在 STOP_PENDING」也是同一个根：主循环没抢到信号。

    Formerly test_stop_event_manual_reset.py.
    """
    import re

    SRC = Path(__file__).resolve().parents[1] / "service.py"
    text = SRC.read_text(encoding="utf-8")
    # 只盯 stop_event；proc_evt（进程退出）只有主循环一个消费者，自动复位是对的。
    hits = re.findall(r"self\.stop_event\s*=\s*win32event\.CreateEvent\(None,\s*(\d)\s*,", text)
    print("  stop_event 的 CreateEvent 第二个参数：", hits)
    ok = hits == ["1"]

    # 第二道：main() 返回后必须自己报告 STOPPED 并 os._exit，不能交给解释器收尾。
    # 2026-09-07 实测：主流程 09:16:42 返回、剩下的全是 daemon 线程，SCM 却 27.5 秒后
    # 才看到停止，15 秒硬保险一次都没触发（Timer 线程在收尾阶段拿不到 GIL）。
    run = text[text.index("def SvcDoRun"):text.index("\n    def ", text.index("def SvcDoRun") + 10)]
    tail_ok = ("ReportServiceStatus(win32service.SERVICE_STOPPED)" in run
               and run.rstrip().endswith("os._exit(0)"))
    print("  SvcDoRun 以 ReportServiceStatus(STOPPED) + os._exit 收尾：", tail_ok)
    ok = ok and tail_ok
    print("all checks passed" if ok else "FAILED: stop_event 不是手动复位（CreateEvent 第二个参数要是 1）")
    sys.exit(0 if ok else 1)


def _part_stop_push_errwatch_budget():
    """stop-push's errwatch: the relay's power-off probe, and the whole run inside the watchdog's time.

Review of e20dc77f + 7c1ba65c (audit 2026-10-13 s5):
  1. `app_main.py stop-push` installed errwatch without the relay's power-off probe, so
     errwatch.relay_shutdown_issued() was always false in that process. The engine that
     knows lives in the relay's process; the relay now keeps the moment in state.json
     (shutdown._record_poweroff) and stop-push's probe reads it
     (shutdown.relay_poweroff_recorded), cleared when the countdown is cancelled and
     stale after ISSUED_STUCK_MIN, as boot_stages._relay_poweroff_live.
  2. The lint commit moved stop-push's drain from 2 s to errwatch.drain's default (3 s);
     the slow-network test stubs the drain out. Here the real stop_push runs with the
     send hanging and a WARNING the group never acknowledges, the drain as it is, and
     STOP_PUSH_WAIT_S + what stop_push adds around the send + a Python start must stay
     inside the watchdog's PUSH_TIMEOUT_S (packaging/watchdog/ark_watchdog.py).

    Formerly test_stop_push_errwatch_budget.py.
    """
    import logging
    import os
    import re
    import subprocess
    import threading
    import time
    from datetime import datetime, timedelta

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    DATA = tmpdir()
    (DATA / "state").mkdir()
    os.environ.update(ARK_HOME=str(DATA), ARK_PHONE_TOPIC="arktest-topic", ARK_PHONE_PIN="1234",
                      SERVERCHAN_KEY="", WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="")
    for _k in ("ARK_LOG_FILE", "ARK_STATE_DIR", "ARK_AUTOMAS_DIR"):
        os.environ.pop(_k, None)

    import app_main
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.phone import phone
    from ark_relay.features.shutdown import shutdown

    STOP_PUSH_LOG = "ark.app.stop_push"   # app_main's logger for the watchdog's stop push


    class Eng:
        def __init__(self, state_dir):
            self.state = State(state_dir)


    STATE = app_main._relay_env()      # what stop_push and its Config() use
    record = getattr(shutdown, "_record_poweroff", lambda eng, at: None)
    recorded = getattr(shutdown, "relay_poweroff_recorded", lambda sd, now=None: False)
    now = datetime.now(tz=SERVER_TZ)

    print("[1. the relay's own power-off, seen from stop-push's process]")
    eng = Eng(STATE)
    record(eng, now - timedelta(minutes=1))
    check("recorded a minute ago: the relay's own power-off", recorded(STATE, now), True)
    check(f"recorded {shutdown.ISSUED_STUCK_MIN} min ago: stale, not ours any more",
          recorded(STATE, now + timedelta(minutes=shutdown.ISSUED_STUCK_MIN)), False)
    app_main._stop_push_errwatch(Config())
    check("stop-push's errwatch asks it: relay_shutdown_issued() is true", errwatch.relay_shutdown_issued(), True)
    record(eng, None)
    check("countdown cancelled: not the relay's power-off", errwatch.relay_shutdown_issued(), False)
    check("nothing recorded at all: not ours", recorded(DATA / "elsewhere", now), False)

    print("[2. the whole stop-push path inside the watchdog's time]")
    src = (RELAY.parent / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8")
    PUSH_TIMEOUT_S = int(re.search(r"^PUSH_TIMEOUT_S\s*=\s*(\d+)", src, re.M).group(1))
    release = threading.Event()


    class Hang:
        """The group never answers: errwatch's push is in flight for the whole drain."""
        _state_dir = STATE

        def send(self, *a, **k):
            release.wait(120)
            return []

        def __getattr__(self, name):
            return lambda *a, **k: []


    h = errwatch._handler[0]
    h._notifier = Hang()
    logging.getLogger(STOP_PUSH_LOG).warning("a WARNING the group does not acknowledge")
    phone.state_cos = lambda cfg: object()
    phone.send_state = lambda box, cfg, why, log: release.wait(120) or (False, "")   # the send hangs
    WAIT = 0.5
    t0 = time.monotonic()
    code = app_main.stop_push(wait_s=WAIT)
    took = time.monotonic() - t0
    around = took - WAIT
    check("the send ran out its time: exit code 1", code, 1)
    check(f"the drain is in it ({around:.2f} s around the send, drain default 3 s)", around >= 2.5, True)
    t1 = time.monotonic()
    # A fresh interpreter importing what stop_push imports (this process has them loaded already).
    subprocess.run([sys.executable, "-c", "import app_main, ark_relay.__main__, ark_relay.core.notify, "
                    "ark_relay.core.statestore, ark_relay.features.alarm.errwatch, ark_relay.features.phone.phone, "
                    "ark_relay.features.shutdown.shutdown"], cwd=RELAY, check=True, capture_output=True)
    start = time.monotonic() - t1
    total = app_main.STOP_PUSH_WAIT_S + around + start
    check(f"{app_main.STOP_PUSH_WAIT_S} s send + {around:.2f} s drain and the rest + {start:.2f} s start"
          f" = {total:.1f} s < the watchdog's {PUSH_TIMEOUT_S} s", total < PUSH_TIMEOUT_S, True)
    release.set()

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_stop_denied, _part_stop_event_manual_reset, _part_stop_push_errwatch_budget]))
