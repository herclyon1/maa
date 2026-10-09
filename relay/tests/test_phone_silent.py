"""phone.state_payload says when the relay block or tomorrow's plan could not be
built (audit docs/SILENT-FAILURES-AUDIT.md, phone.py:1862 and :1884).

state_payload runs on every phone-state publish and a WARNING is a group
message, so each is said once per condition; the payload keeps its shape
(relay = {}, plan = "").
"""
import logging
import sys
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay import modes, phone, plan, snapshot

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def said(self, words):
        out = [r for r in self.records if r.levelno >= logging.WARNING and words in r.getMessage()]
        self.records.clear()
        return len(out)


grab = Grab()
logging.getLogger("ark.phone").addHandler(grab)
cfg = types.SimpleNamespace(automas_dir=str(tmpdir()), maaend_dir=str(tmpdir()), okww_dir=str(tmpdir()))
sd = tmpdir()


def payload():
    with mock.patch.object(snapshot, "read", lambda: {}):
        return phone.state_payload(cfg, sd)


print("[relay block raising]")
getattr(phone, "_last_error", {}).clear()
with mock.patch.object(modes, "debug_active", side_effect=RuntimeError("state broke")):
    st = payload()
    check("relay stays {} (shape unchanged)", st.get("relay"), {})
    check("one WARNING", grab.said("中继那一段"), 1)
    payload()
    check("same condition again -> no second WARNING", grab.said("中继那一段"), 0)
st = payload()
check("works -> a dict with its keys", isinstance(st["relay"], dict) and "调试模式" in st["relay"], True)
check("works -> no WARNING", grab.said("中继那一段"), 0)
with mock.patch.object(modes, "debug_active", side_effect=RuntimeError("state broke")):
    payload()
    check("broken again after it worked -> WARNING again", grab.said("中继那一段"), 1)

print("[plan.next_plan raising]")
getattr(phone, "_last_error", {}).clear()
with mock.patch.object(plan, "next_plan", side_effect=ValueError("bad queue")):
    st = payload()
    check("plan stays \"\" (type unchanged)", st.get("plan"), "")
    check("one WARNING", grab.said("明日安排"), 1)
    payload()
    check("same condition again -> no second WARNING", grab.said("明日安排"), 0)
with mock.patch.object(plan, "next_plan", return_value="📅 明日安排"):
    check("works -> the plan text", payload().get("plan"), "📅 明日安排")
    check("works -> no WARNING", grab.said("明日安排"), 0)
with mock.patch.object(plan, "next_plan", side_effect=ValueError("bad queue")):
    payload()
    check("broken again after it worked -> WARNING again", grab.said("明日安排"), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
