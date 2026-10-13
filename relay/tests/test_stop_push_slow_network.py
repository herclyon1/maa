"""The watchdog's shutdown push finishes inside its time even with AUTO-MAS dead and a slow network.

2026-10-11 15:41:40 (machine time), the first forced reboot with the watchdog push in
place: relay.log has the push starting at 15:41:53, two refused AUTO-MAS calls (2 s
each), 「状态 44272 字节，压缩到 13347 字节」 at 15:42:08 - logged inside Mailbox.publish
right before the COS PUT - and at 15:42:28 「看门服务等了 35 秒还没发完」. ntfy's cache
holds the state notice 「state 1791704529 13347」 received 15:42:09, and that notice is
only sent once the state is stored on COS. So the state reached the phone; the push was
then waiting for the optional notice's answer (20 s a socket operation, a second try
after 3 s) and the 35 s ran out: a delivered state logged as a failure, #11 to the group.

Reproduced here with the real app_main.stop_push, the real Mailbox and the real
state_payload, the wire faked: every AUTO-MAS call is refused after a delay, COS answers,
ntfy takes the request and never answers, Skland hangs. Time runs at SCALE (a fake
operation sleeps its time-out x SCALE), the budget is scaled the same way.
  1. with the old limits (no AUTO-MAS skip, a 20 s notice with a retry) the push runs
     out its time: the 15:42 failure;
  2. with stop-push's limits it ends well inside the budget, logs the success line #11
     reads and leaves the marker; AUTO-MAS is not called; ntfy is tried once;
  3. COS hanging too (a DNS lookup no socket time-out covers): it gives up at its time
     with the failure line, never later;
  4. the relay's own Mailbox and the plan's site reads keep their defaults.
"""
import os
import socket
import sys
import threading
import time
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

DATA = tmpdir()
(DATA / "state").mkdir()
os.environ.update(ARK_HOME=str(DATA), ARK_PHONE_TOPIC="arktest-topic", ARK_PHONE_PIN="1234",
                  SKLAND_TOKEN="test-token")
for _k in ("ARK_LOG_FILE", "ARK_STATE_DIR", "ARK_AUTOMAS_DIR"):
    os.environ.pop(_k, None)
LOG = DATA / "relay.log"
SCALE = 0.05

import urllib.request  # noqa: E402

import app_main  # noqa: E402
from ark_relay.features.phone import phone  # noqa: E402
from ark_relay.core import skland  # noqa: E402
from ark_relay.features.maintenance import maintenance  # noqa: E402
from ark_relay.features.phone import commands, mailbox, mas_client  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


print("[4. defaults before stop-push touches anything]")
check("Mailbox notice: 20 s an operation", mailbox.Mailbox.POST_TIMEOUT, 20)
check("Mailbox: two tries", mailbox.Mailbox.ATTEMPTS, 2)
check("official sites: 20 s, two tries", (maintenance.GET_TIMEOUT, maintenance.GET_ATTEMPTS), (20, 2))
check("Skland: 20 s", skland._TIMEOUT, 20)

# ---------------------------------------------------------------- the faked wire

calls = {"mas": 0, "ntfy": 0, "cos": 0, "other": 0}
cos_hangs = [False]
cos_release = threading.Event()


def mas_post(path, body=None, timeout=20):
    """AUTO-MAS is gone: Windows answers a refused local connect after about 2 s."""
    calls["mas"] += 1
    time.sleep(2 * SCALE)
    raise ConnectionRefusedError(10061, "refused")


commands.mas_post = mas_client.mas_post = mas_post


def urlopen(req, timeout=None, **kw):
    """ntfy (and anything else on the net) takes the request and never answers: the
    operation waits out its time-out."""
    url = req.full_url if hasattr(req, "full_url") else str(req)
    calls["ntfy" if url.startswith(phone.NTFY) else "other"] += 1
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
    before = LOG.read_text(encoding="utf-8") if LOG.exists() else ""
    real_limits = app_main._stop_push_limits
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
# Since audit 11 #2 (2026-10-13) a phone publish reads only snapshot.read_runtime, so
# AUTO-MAS is not asked even without stop-push's limits; ntfy alone runs out the time.
check("AUTO-MAS not asked even without stop-push's limits", calls["mas"], 0)
check("the timing line says the send did not finish", "还没发完" in new.split("看门服务代发用时：", 1)[-1], True)

print("[2. stop-push's limits: the same wire -> sent well inside the budget]")
code, took, new, marker = run(BUDGET)
check("sent: exit code 0", code, 0)
check(f"took {took:.2f} s, under half the budget ({BUDGET:.1f} s)", took < BUDGET / 2, True)
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
