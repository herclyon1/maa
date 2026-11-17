"""Stop-push delivery resilience under slow or stalled network conditions."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir

_SHARED = (check, fails, require, tmpdir)


def _part_stop_push_slow_network():
    import os
    import socket
    import threading
    import time

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    DATA = tmpdir()
    (DATA / "state").mkdir()
    os.environ.update(ARK_HOME=str(DATA), ARK_PHONE_TOPIC="arktest-topic", ARK_PHONE_PIN="1234",
                      SKLAND_TOKEN="test-token")
    for _k in ("ARK_LOG_FILE", "ARK_STATE_DIR", "ARK_AUTOMAS_DIR"):
        os.environ.pop(_k, None)
    LOG = DATA / "relay.log"
    SCALE = 0.05

    import urllib.request

    import app_main
    from ark_relay.features import phone
    from ark_relay.core import skland
    from ark_relay.features import maintenance
    from ark_relay.features import commands, phone as mailbox, redbutton as mas_client


    print("[4. defaults before stop-push touches anything]")
    check("Mailbox notice: 20 s an operation", mailbox.Mailbox.POST_TIMEOUT, 20)
    check("Mailbox: two tries", mailbox.Mailbox.ATTEMPTS, 2)
    check("official sites: 20 s, two tries", (maintenance.GET_TIMEOUT, maintenance.GET_ATTEMPTS), (20, 2))
    check("Skland: 20 s", skland._TIMEOUT, 20)

    # ---------------------------------------------------------------- the faked wire

    calls = {"mas": 0, "ntfy": 0, "cos": 0, "other": 0}
    waited: list[float] = []      # the unscaled seconds each faked operation waited, this run
    cos_hangs = [False]
    cos_release = threading.Event()


    def mas_post(path, body=None, timeout=20):
        """AUTO-MAS is gone: Windows answers a refused local connect after about 2 s."""
        calls["mas"] += 1
        waited.append(2)
        time.sleep(2 * SCALE)
        raise ConnectionRefusedError(10061, "refused")


    commands.mas_post = mas_client.mas_post = mas_post


    def urlopen(req, timeout=None, **kw):
        """ntfy (and anything else on the net) takes the request and never answers: the
    operation waits out its time-out."""
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls["ntfy" if url.startswith(phone.NTFY) else "other"] += 1
        waited.append(timeout or 60)
        time.sleep((timeout or 60) * SCALE)
        raise socket.timeout("timed out")


    urllib.request.urlopen = urlopen


    def cos_put(cos, key, data, timeout, **kw):
        calls["cos"] += 1
        if cos_hangs[0]:
            cos_release.wait(1000)    # a DNS lookup: no socket time-out covers it
        return None                   # stored


    mailbox.cos_put = cos_put
    phone.state_cos = lambda cfg: object()
    real_payload = phone.state_payload
    # The real state, padded to the 15:42 size class (over INLINE_MAX: COS, then the notice).
    phone.state_payload = lambda cfg, sd: {**real_payload(cfg, sd), "pad": os.urandom(9000).hex()}


    def settle():
        """Let a send that outlived its process's time finish before the next case reads the log."""
        for t in threading.enumerate():
            if t.name == "stop-push":
                t.join(30)
        phone.clear_stop_pushed(DATA / "state")


    def run(wait_s, limits=True):
        for k in calls:
            calls[k] = 0
        waited.clear()
        before = LOG.read_text(encoding="utf-8") if LOG.exists() else ""
        real_limits = app_main._stop_push_limits
        # The send's own time only: the errwatch drain after it is a bounded step of its
        # own (errwatch.drain, inside the watchdog's margin).
        from ark_relay.features import errwatch
        errwatch.drain = lambda timeout=0: None
        if not limits:
            app_main._stop_push_limits = lambda box: None
        t0 = time.monotonic()
        try:
            code = app_main.stop_push(wait_s=wait_s)
        finally:
            app_main._stop_push_limits = real_limits
        took = time.monotonic() - t0
        marker = phone.stop_pushed(DATA / "state")
        settle()
        return code, took, LOG.read_text(encoding="utf-8")[len(before):], marker


    BUDGET = app_main.STOP_PUSH_WAIT_S * SCALE

    print("[1. the 15:42 run: old limits, AUTO-MAS dead, ntfy never answers -> runs out its time]")
    code, took, new, _ = run(BUDGET, limits=False)
    check("not sent: exit code 1", code, 1)
    check("the 15:42:28 line", "状态没能上报到手机（停止前）：看门服务等了" in new, True)
    check("AUTO-MAS not asked even without stop-push's limits", calls["mas"], 0)
    check("the timing line says the send did not finish", "还没发完" in new.split("看门服务代发用时：", 1)[-1], True)

    print("[2. stop-push's limits: the same wire -> sent well inside the budget]")
    REAL_WORK_S = 10.0
    code, took, new, marker = run(BUDGET + REAL_WORK_S)
    check("sent: exit code 0", code, 0)
    check(f"its waits add up to {sum(waited):g} s ({waited}), under half the {app_main.STOP_PUSH_WAIT_S} s "
      f"(wall clock {took:.2f} s, real work included)", sum(waited) < app_main.STOP_PUSH_WAIT_S / 2, True)
    check("the success line #11 reads", "📱 已上报状态到手机（停止前；" in new, True)
    check("no failure line", "状态没能上报到手机" in new, False)
    check("marker left for the relay-side skip", marker, True)
    check("AUTO-MAS not called at all (the backend is gone)", calls["mas"], 0)
    check("ntfy tried once", calls["ntfy"], 1)
    check("stored on COS once", calls["cos"], 1)
    check("the timing line names COS and the end", ("存腾讯云到" in new and "发完到" in new), True)
    check("the notice's miss is said, as delivered through COS",
          "状态的通知没发到手机信箱，状态已存到腾讯云" in new, True)

    print("[3. COS hangs as well (DNS): gives up at its time with the failure line]")
    cos_hangs[0] = True
    real_settle, settle = settle, lambda: None      # read the outcome while it still hangs
    code, took, new, marker = run(1.0)
    settle = real_settle
    cos_hangs[0] = False
    cos_release.set()
    settle()
    check("not sent: exit code 1", code, 1)
    check(f"took {took:.2f} s: at its time, not later", 0.9 < took < 2.5, True)
    check("the failure line", "状态没能上报到手机（停止前）：看门服务等了 1 秒还没发完" in new, True)
    check("no marker", marker, False)

    print("[4. the limits are stop-push's alone]")
    check("a new Mailbox still has 20 s and two tries",
          (mailbox.Mailbox("t", "p", DATA / "state").POST_TIMEOUT, mailbox.Mailbox.ATTEMPTS), (20, 2))
    check("stop-push's own: sites 4 s one try, Skland 4 s",
          (maintenance.GET_TIMEOUT, maintenance.GET_ATTEMPTS, skland._TIMEOUT),
          (app_main.STOP_PUSH_SITE_S, 1, app_main.STOP_PUSH_SKLAND_S))
    worst = app_main.STOP_PUSH_SKLAND_S + app_main.STOP_PUSH_SITE_S * 3 + mailbox.Mailbox.COS_TIMEOUT + app_main.STOP_PUSH_NOTICE_S
    check(f"one hung op per step still fits: {worst} s < {app_main.STOP_PUSH_WAIT_S} s", worst < app_main.STOP_PUSH_WAIT_S, True)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_stop_push_slow_network]))
