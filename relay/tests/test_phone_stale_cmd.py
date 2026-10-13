"""A phone command dropped as too old is marked handled (audit 9 A3, 2026-10-13).

wire.unpack returns None for a command older than MAX_AGE, and the mailbox
skipped it without adding its ntfy id to the handled list. While ntfy kept the
message, every boot and every reconnect re-read it and logged 「信箱里那条指令太老了」
again: relay.log 2026-10-05 logged the same two messages 11 times (the cause, a
phone clock a day off, was fixed in the App, ark-remote 745e96e).

Both read paths are checked: the boot read (Mailbox.fetch / _read_backlog) and
the held stream (Mailbox.listen). Fake network; nothing waits for real.
"""
import io
import json
import logging
import sys
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay.features.phone import mailbox as phone_mailbox
from ark_relay.features.phone import phone

PIN = "8964"
TOPIC = "topic-abc"
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        fails.append(label)


class FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(io.BytesIO(self._body))

    def read(self):
        return self._body

    def close(self):
        pass


def ntfy_lines(*msgs):
    """ntfy's JSON stream: one `message` event per (id, raw message)."""
    now = int(time.time())
    return "\n".join(json.dumps({"id": mid, "time": now, "event": "message", "message": raw})
                     for mid, raw in msgs).encode() + b"\n"


def cmd(body, ts):
    return json.dumps({"v": 1, "kind": "cmd", "pin": PIN, "ts": ts, "body": body})


def use(body):
    fake = types.SimpleNamespace(
        request=types.SimpleNamespace(Request=urllib.request.Request,
                                      urlopen=lambda req, timeout=None: FakeResp(body)),
        error=urllib.error)
    phone_mailbox.urllib = fake


class Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


logs = Logs()
logging.getLogger("ark.phone").addHandler(logs)
logging.getLogger("ark.phone").setLevel(logging.INFO)

now = int(time.time())
OLD = cmd({"action": "refresh"}, now - phone.MAX_AGE - 3600)
NEW = cmd({"action": "refresh"}, now - 60)
FOREIGN = json.dumps({"v": 1, "kind": "cmd", "pin": "0000", "ts": now - phone.MAX_AGE - 3600, "body": {}})
STATE = json.dumps({"v": 1, "kind": "state", "pin": PIN, "ts": now - 60, "body": {}})
BACKLOG = ntfy_lines(("m-old", OLD), ("m-new", NEW), ("m-foreign", FOREIGN), ("m-state", STATE))


def too_old_lines():
    return sum("太老了" in line for line in logs.lines)


print("[boot read: a too-old command is marked handled, and logged once]")
state = tmpdir()
use(BACKLOG)
mb = phone.Mailbox(TOPIC, PIN, state)
got = mb._read_backlog()
check("only the fresh command runs", [c["_meta"]["ntfy_id"] for c in got], ["m-new"])
check("the too-old command's id is marked handled (not a wrong PIN, not a state)",
      sorted(mb._seen), ["m-new", "m-old"])
mb2 = phone.Mailbox(TOPIC, PIN, state)          # the next boot
check("the mark survives a restart", "m-old" in mb2._seen, True)
before = too_old_lines()
check("the next boot does not run anything again", mb2._read_backlog(), [])
check("and does not log the too-old command again", too_old_lines() - before, 0)

print("\n[held stream: a too-old command is marked handled]")
state = tmpdir()
use(ntfy_lines(("s-old", OLD)))
mb = phone.Mailbox(TOPIC, PIN, state)
calls = []


def stop():
    """False for the loop check and the one line; True once the stream ends."""
    calls.append(1)
    return len(calls) > 2


mb.listen(lambda c: None, stop)
check("the stream marks it handled", mb._seen, ["s-old"])
check("on disk too", phone.Mailbox(TOPIC, PIN, state)._seen, ["s-old"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
