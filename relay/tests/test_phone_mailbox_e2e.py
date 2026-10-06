"""The phone mailbox end to end, against a real ntfy server on this Mac.

phone.Mailbox, the boot path (boot_stages.boot_backlog + _make_phone_cmd), the
real command (commands.apply_command set_wait_time), the receipt
(modes.add_receipt) and the state the phone reads (phone.state_payload, posted
through Mailbox.publish) all run unchanged; the only server is a real ntfy
(v2.28.0 built from source, ~/.local/bin/ntfy-server, or NTFY_SERVER) listening
on a free loopback port. Every other address is refused by a guard on urlopen,
and the test fails if anything tried ntfy.sh or any other non-loopback host.

Three machines, one topic and one state dir each:
  a. on: a settings change sent while the stream is held is executed live,
     the receipt and the state carrying it reach the topic.
  b. off 6 h: the order sent while it was off is still held by ntfy; the boot
     read executes it, and no blind window is recorded.
  c. off 13 h: ntfy has dropped the order before the boot; nothing runs and
     relay.信箱空窗 holds exactly {from: last read, to: boot - 12 h, boot}.

Clock. ntfy refuses a cache-duration or manager-interval under 5 s ("manager
interval cannot be lower than five seconds", measured 2026-10-07), and an
expired message stays readable until the next manager run (measured: up to
+4.3 s past `expires`), so the server's retention cannot be scaled to exactly
6/12 or 13/12 of anything. The two are decoupled instead: the server keeps a
message 5 s and the test observes it there or gone; the relay's clock
(phone.time) is the real clock plus an offset that jumps 6 h / 13 h for the
boot. phone.NTFY_CACHE_SEC stays the shipped 12 h, so the window is checked in
the units the machine really uses. The 6 h case boots within ~1 s of the
order (still held: a message lives at least 4 s); the 13 h case boots only
after a direct read of the server shows the order gone.

Basis: "cache-duration: defines the duration for which messages are stored in
the cache (default is 12h)." (https://docs.ntfy.sh/config/)
"""
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

# boot_stages imports the Windows service modules at top level (same stubs as
# test_phone_channel_boot.py).


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
              "win32com", "win32com.client"):
    sys.modules.setdefault(_name, _Stub(_name))

STATE_ROOT = tmpdir()
os.environ["ARK_STATE_DIR"] = str(STATE_ROOT / "unused")
os.environ["ARK_AUTOMAS_DIR"] = str(STATE_ROOT / "unused-mas")

import boot_stages                     # noqa: E402
from ark_relay import commands, modes, phone  # noqa: E402
from ark_relay.statestore import StateStore  # noqa: E402

PIN = "8964"
HOUR = 3600
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


# ---------------------------------------------------------------- the server

SERVER = os.environ.get("NTFY_SERVER") or os.path.expanduser("~/.local/bin/ntfy-server")
CONFIG = """\
listen-http: "127.0.0.1:{port}"
base-url: "http://127.0.0.1:{port}"
cache-file: "{dir}/cache.db"
cache-duration: "5s"
manager-interval: "5s"
keepalive-interval: "5s"
visitor-request-limit-exempt-hosts: "127.0.0.1,::1"
visitor-message-daily-limit: 100000000
visitor-request-limit-burst: 100000
visitor-request-limit-replenish: "1ms"
visitor-subscription-limit: 1000
visitor-topic-creation-limit-burst: 0
log-level: "warn"
"""
_real_urlopen = urllib.request.urlopen


class Ntfy:
    """The real ntfy server on a free loopback port; stop() ends only the PID it started."""

    def __init__(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.base = f"http://127.0.0.1:{self.port}"
        self.dir = tmpdir("ntfy-e2e-")
        self.proc = None
        self.started = 0.0

    def start(self):
        if not os.access(SERVER, os.X_OK):
            raise RuntimeError(f"no ntfy server binary at {SERVER}: build it with "
                               "ark-remote-replay scripts/replay/ntfy_local.py build (needs Go)")
        (self.dir / "server.yml").write_text(CONFIG.format(port=self.port, dir=self.dir))
        # Start just past a whole second: the manager's first prune then comes at
        # start + 5 s, after the 13 h order's `expires` (its send time truncated to
        # the second, + 5 s), so the order is gone at the first prune, not the second.
        time.sleep(1.02 - (time.time() % 1.0))
        self.started = time.time()
        self.proc = subprocess.Popen([SERVER, "serve", "--config", str(self.dir / "server.yml")],
                                     stdout=open(self.dir / "server.log", "w"), stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + 10
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"ntfy exited {self.proc.returncode}: "
                                   f"{(self.dir / 'server.log').read_text()[-400:]}")
            try:
                with _real_urlopen(f"{self.base}/v1/health", timeout=1) as r:
                    if json.loads(r.read()).get("healthy") is True:
                        return self
            except OSError:
                pass
            time.sleep(0.03)
        raise RuntimeError("ntfy not healthy within 10 s")

    def stop(self):
        p, self.proc = self.proc, None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(5)
        return p

    # What the phone does: post an envelope, read the topic.
    def send(self, topic: str, body: dict) -> dict:
        data = phone.pack(PIN, body, "cmd").encode("utf-8")
        req = urllib.request.Request(f"{self.base}/{topic}", data=data, method="POST")
        with _real_urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def held(self, topic: str) -> list:
        with _real_urlopen(f"{self.base}/{topic}/json?poll=1&since=all", timeout=5) as r:
            lines = [json.loads(x) for x in r.read().decode().splitlines() if x.strip()]
        return [e for e in lines if e.get("event") == "message"]

    def last_state(self, topic: str, now: float) -> "dict | None":
        """The newest state on the topic, as the phone reads it (inline envelope)."""
        out = None
        for env in self.held(topic):
            msg = phone.unpack(PIN, str(env.get("message") or ""), now=now)
            if msg and msg.get("kind") == "state":
                out = msg.get("body")
        return out


# ---------------------------------------------------------------- the fakes

class Clock:
    """phone.time: the real clock plus `offset` (the hours the machine was off)."""

    def __init__(self):
        self.offset = 0.0

    def time(self):
        return _real_time.time() + self.offset

    def __getattr__(self, name):
        return getattr(_real_time, name)


_real_time = time
clock = Clock()
phone.time = clock

blocked: list[str] = []
srv = Ntfy()


def guarded_urlopen(req, *a, **k):
    """Only the local ntfy is reachable; anything else is refused (and recorded)."""
    url = req if isinstance(req, str) else req.full_url
    if url.startswith(srv.base + "/"):
        return _real_urlopen(req, *a, **k)
    blocked.append(url)
    raise urllib.error.URLError("refused by test_phone_mailbox_e2e: only the local ntfy")


urllib.request.urlopen = guarded_urlopen
phone.NTFY = srv.base
phone.NTFY_ACCOUNT = f"{srv.base}/v1/account"


def offline_mas(path, body=None, timeout=20):
    raise RuntimeError("AUTO-MAS backend not running in this test")


commands._mas = offline_mas       # set_wait_time takes its file path (ScriptConfig.json)


class Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs: list[str] = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


plog = Logs()
# The state reader's warnings about the absent AUTO-MAS (refused by the guard)
# would otherwise go to stderr through logging's last-resort handler.
logging.getLogger().addHandler(logging.NullHandler())
phone.log.addHandler(plog)
phone.log.setLevel(logging.INFO)
log = logging.getLogger("ark.test_phone_mailbox_e2e")
log.addHandler(logging.NullHandler())
log.propagate = False

SID = "59da8762-8fa7-4f2b-9c1e-000000000001"


class Machine:
    """One relay: its own state dir, AUTO-MAS dir and topic."""

    def __init__(self, name: str):
        self.name = name
        self.topic = f"e2e-{name}-{os.getpid()}"
        self.sd = STATE_ROOT / name
        self.mas = STATE_ROOT / f"{name}-mas"
        self.sd.mkdir()
        cfgf = self.mas / "config" / "ScriptConfig.json"
        cfgf.parent.mkdir(parents=True)
        cfgf.write_text(json.dumps({SID: {"Info": {"Name": "MaaEnd"}, "Game": {"WaitTime": 60}}},
                                   indent=2), encoding="utf-8")
        self.cfgf = cfgf
        self.box = None
        self.stop = threading.Event()
        self.thread = None
        self.sent: list = []

    def wait_time(self) -> int:
        return json.loads(self.cfgf.read_text(encoding="utf-8"))[SID]["Game"]["WaitTime"]

    def boot(self, listen: bool = True):
        """What _start_phone_channel does with the mailbox: construct, boot read
        through boot_backlog under one held push, then hold the stream."""
        os.environ["ARK_STATE_DIR"] = str(self.sd)
        os.environ["ARK_AUTOMAS_DIR"] = str(self.mas)
        self.box = box = phone.Mailbox(self.topic, PIN, self.sd)
        cfg = types.SimpleNamespace(state_dir=self.sd, automas_dir=self.mas)
        push_state = phone.StatePusher(lambda why: box.publish(phone.state_payload(cfg, self.sd)))
        engine = types.SimpleNamespace(scripts_running=lambda: False)
        notifier = types.SimpleNamespace(send=lambda *a, **k: self.sent.append(a) or True)
        hb = types.SimpleNamespace(watch=lambda: None)
        run = boot_stages._make_phone_cmd(engine, notifier, log, hb, push_state, self.sd)
        self.stop.clear()
        push_state("开机")
        with push_state.held():
            for body in boot_stages.boot_backlog(box.fetch(), log):
                run(body)
        if listen:
            self.thread = threading.Thread(target=box.listen, args=(run, self.stop.is_set),
                                           daemon=True)
            self.thread.start()
            until = _real_time.time() + 5
            while not box.connected and _real_time.time() < until:
                _real_time.sleep(0.01)
        return box

    def shutdown(self):
        """SvcStop: stop flag, cut the stream (Mailbox.close keeps the mark).

        close() has to return at once and take the listener with it: until
        2026-10-07 it waited for the next line ntfy sent (a keepalive, 5 s
        here, 45 s on ntfy.sh) - see Mailbox.close."""
        self.stop.set()
        if self.box is not None:
            t = _real_time.time()
            self.box.close()
            took = _real_time.time() - t
            if self.thread is not None:
                check(f"{self.name}: Mailbox.close() returned at once (< 1 s, keepalive is 5 s)",
                      (took < 1.0) or round(took, 2), True)
        if self.thread is not None:
            self.thread.join(1.0)
            check(f"{self.name}: the listener thread ended with it", self.thread.is_alive(), False)
        self.thread = None

    def mark(self):
        return StateStore(self.sd).get("queues", "phone_mark")

    def receipts(self):
        return [r for r in modes.receipts(self.sd) if r.get("action") == "set_wait_time"]


def wait_for(cond, secs: float) -> bool:
    until = _real_time.time() + secs
    while _real_time.time() < until:
        if cond():
            return True
        _real_time.sleep(0.02)
    return bool(cond())


def order(value: int) -> dict:
    return {"action": "set_wait_time", "value": value, "confirmed": True}


t0 = time.time()
try:
    srv.start()
    print(f"[local ntfy up: {srv.base}, pid {srv.proc.pid}, cache 5 s]")
    A, B, C = Machine("a"), Machine("b"), Machine("c")

    # c first: its order has to be gone from the server before c boots again.
    C.boot()
    C.shutdown()
    c_mark = C.mark()
    c_msg = srv.send(C.topic, order(240))      # pressed while c is off
    if c_msg["time"] > int(srv.started):
        # Its expires falls after the manager's first prune: gone only at the
        # second one, ~5 s later than usual (the test then takes ~11 s).
        print(f"  (slow path: c's order sent {time.time() - srv.started:.2f} s after the server "
              "started, past the whole second; it is pruned at +10 s, not +5 s)")

    # ------------------------------------------------------------ a. on
    print("\n[a. machine on: a settings change arrives live, runs, is answered]")
    A.boot()
    check("a: stream held", A.box.connected, True)
    check("a: no blind window on a first boot", A.box.blind, None)
    a_msg = srv.send(A.topic, order(120))
    check("a: WaitTime changed to 120 by the live order", wait_for(lambda: A.wait_time() == 120, 5), True)
    check("a: an ok receipt for it", wait_for(lambda: any(r.get("ok") for r in A.receipts()), 5), True)
    check("a: its ntfy id remembered (it never runs twice)",
          a_msg["id"] in (StateStore(A.sd).get("queues", "phone_seen") or []), True)
    st = None
    if wait_for(lambda: (srv.last_state(A.topic, clock.time()) or {}).get("relay", {}).get("最近指令"), 5):
        st = srv.last_state(A.topic, clock.time())
    got = [(r.get("action"), r.get("ok")) for r in ((st or {}).get("relay") or {}).get("最近指令", [])]
    check("a: the state on the topic carries the receipt", ("set_wait_time", True) in got, True)
    check("a: and no blind window", ((st or {}).get("relay") or {}).get("信箱空窗"), [])
    A.shutdown()
    check("a: the read mark is on disk after shutdown", isinstance(A.mark(), int), True)

    # ------------------------------------------------------------ b. off 6 h
    print("\n[b. off 6 h: the order is still held, the boot read runs it, no window]")
    B.boot()
    B.shutdown()
    b_mark = B.mark()
    b_msg = srv.send(B.topic, order(180))
    clock.offset = 6 * HOUR
    plog.msgs.clear()
    B.boot(listen=False)
    check("b: the server still held the order at boot", any(e["id"] == b_msg["id"] for e in srv.held(B.topic)), True)
    check("b: WaitTime changed to 180 by the boot read", B.wait_time(), 180)
    check("b: an ok receipt for it", any(r.get("ok") for r in B.receipts()), True)
    check("b: Mailbox.blind is None", B.box.blind, None)
    check("b: mailbox_status() is empty", phone.mailbox_status(B.sd), [])
    check("b: no window line in the log", any("信箱空窗" in m for m in plog.msgs), False)
    st = srv.last_state(B.topic, clock.time())
    check("b: the state on the topic carries the receipt",
          ("set_wait_time", True) in [(r.get("action"), r.get("ok"))
                                      for r in ((st or {}).get("relay") or {}).get("最近指令", [])], True)
    check("b: and relay.信箱空窗 == []", ((st or {}).get("relay") or {}).get("信箱空窗"), [])
    B.shutdown()
    clock.offset = 0

    # ------------------------------------------------------------ c. off 13 h
    print("\n[c. off 13 h: ntfy dropped the order; the boot records the window]")
    gone = wait_for(lambda: not srv.held(C.topic), 12)
    check("c: the server dropped the order before the boot", gone, True)
    c_off = _real_time.time()
    clock.offset = 13 * HOUR
    plog.msgs.clear()
    C.boot(listen=False)
    boot = C.box._booted
    check("c: the boot is 13 h after the shutdown (relay clock)",
          abs(boot - (c_off + 13 * HOUR)) < 2, True)
    check("c: WaitTime unchanged (the order never arrived)", C.wait_time(), 60)
    check("c: no receipt", C.receipts(), [])
    want = {"from": c_mark, "to": boot - 12 * HOUR, "boot": boot}
    check("c: Mailbox.blind == {from: last read mark, to: boot - 12 h, boot}", C.box.blind, want)
    check("c: the window is kept on disk", StateStore(C.sd).get("queues", "phone_blind"), [want])
    blind = phone.mailbox_status(C.sd)
    check("c: mailbox_status() gives it as 从/到/开机",
          blind, [{"从": c_mark, "到": boot - 12 * HOUR, "开机": boot}])
    check("c: the dropped order was sent inside the window (从 <= its ntfy time <= 到)",
          bool(blind) and blind[0]["从"] <= c_msg["time"] <= blind[0]["到"], True)
    check("c: one window line in the log", sum("信箱空窗" in m for m in plog.msgs), 1)
    st = srv.last_state(C.topic, clock.time())
    check("c: the state on the topic carries relay.信箱空窗",
          ((st or {}).get("relay") or {}).get("信箱空窗"), blind)
    C.shutdown()
    clock.offset = 0

    print("\n[the network the relay reached]")
    check("nothing but the local ntfy was reached (refused: AUTO-MAS on loopback only)",
          [u for u in blocked if not u.startswith("http://127.0.0.1:")], [])
except Exception as exc:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    fails.append(type(exc).__name__)
finally:
    clock.offset = 0
    p = srv.stop()
    if p is not None:
        check("the ntfy this test started has exited", p.poll() is not None, True)
    shutil.rmtree(srv.dir, ignore_errors=True)
    print(f"  ({time.time() - t0:.1f} s)")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
