"""WeeklyGate driven end to end, with no fake gate.

Audit 2026-10-05 (E): WeeklyGate.maybe_reopen / enforce / _write_via_api were
only ever exercised through a stand-in gate object, so the code that actually
reads and writes the annihilation switch had no test. Here the real gate runs
against (a) an in-memory AUTO-MAS backend behind commands._mas - so
_find_user, read_setting and _write_via_api are the real functions - and
(b) a real ScriptConfig.json for the file fallback when the backend is down.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import annihilation as A
from ark_relay import commands
from ark_relay.config import SERVER_TZ

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


WED = datetime(2026, 9, 30, 10, 0, tzinfo=SERVER_TZ)
NEXT_MON = datetime(2026, 10, 5, 5, 0, tzinfo=SERVER_TZ)      # after the 04:00 reset
MON_EARLY = datetime(2026, 10, 5, 3, 0, tzinfo=SERVER_TZ)     # still last week


class Backend:
    """AUTO-MAS's script/user endpoints, as commands._mas sees them."""

    def __init__(self, value, *, ignores_writes=False):
        self.value, self.ignores_writes, self.updates = value, ignores_writes, []

    def __call__(self, path, body=None, timeout=20):
        if path == "/api/scripts/get":
            return {"data": {"s1": {"Info": {"Name": "MAA"}}}}
        if path == "/api/scripts/user/get":
            return {"data": {"u1": {"Info": {"Annihilation": self.value}}}}
        if path == "/api/scripts/user/update":
            self.updates.append(body)
            if not self.ignores_writes:
                self.value = body["data"]["Info"]["Annihilation"]
            return {"code": 200}
        raise AssertionError(path)


def down(*_a, **_k):
    raise OSError("backend down")


def automas_with_file(value):
    d = tmpdir()
    (d / "config").mkdir()
    (d / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s1"}],
        "s1": {"Info": {"Path": "D:/MAA"},
               "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Annihilation": value}}}}},
    }), encoding="utf-8")
    return d


def file_value(d):
    data = json.loads((d / "config" / "ScriptConfig.json").read_text(encoding="utf-8"))
    return data["s1"]["SubConfigsInfo"]["UserData"]["u1"]["Info"]["Annihilation"]


print("[_write_via_api, real function against the backend]")
be = Backend("Annihilation")
with mock.patch.object(commands, "_mas", be):
    check("same value -> ok, no update call", (A._write_via_api("Annihilation"), len(be.updates)),
          ((True, ""), 0))
    check("new value -> written and read back", A._write_via_api("Close"),
          (True, "已通过 AUTO-MAS 后端改写"))
    check("backend now holds Close", be.value, "Close")
be = Backend("Annihilation", ignores_writes=True)
with mock.patch.object(commands, "_mas", be):
    ok, why = A._write_via_api("Close")
    check("backend ignores write -> False, says so", (ok, "写了但没生效" in why), (False, True))

print("[on_success + enforce through the backend]")
be = Backend("Chernobog@Annihilation")
with mock.patch.object(commands, "_mas", be):
    g = A.WeeklyGate(tmpdir(), tmpdir())
    check("enforce before done -> nothing", g.enforce(WED), False)
    check("enforce before done -> switch untouched", be.value, "Chernobog@Annihilation")
    msg = g.on_success(WED)
    check("on_success names the map to restore", "Chernobog@Annihilation" in msg, True)
    check("on_success remembers week + restore_to", g._load(),
          {"done_week": A.week_key(WED), "restore_to": "Chernobog@Annihilation"})
    check("on_success twice -> quiet", g.on_success(WED), "")
    check("enforce -> closes", g.enforce(WED), True)
    check("backend now Close", be.value, "Close")
    check("enforce again when already Close -> nothing", g.enforce(WED), False)
    be.value = "Chernobog@Annihilation"          # AUTO-MAS wrote its in-memory copy back
    check("enforce after being flushed back -> closes again", (g.enforce(WED), be.value), (True, "Close"))

print("[maybe_reopen through the backend]")
with mock.patch.object(commands, "_mas", be):
    check("same week -> nothing", g.maybe_reopen(WED), "")
    check("Monday 03:00 is still last week -> nothing", g.maybe_reopen(MON_EARLY), "")
    check("still Close", be.value, "Close")
    msg = g.maybe_reopen(NEXT_MON)
    check("new week -> reopened to the remembered map", "Chernobog@Annihilation" in msg, True)
    check("backend restored", be.value, "Chernobog@Annihilation")
    check("state cleared", g._load(), {})

stuck = Backend("Close", ignores_writes=True)
with mock.patch.object(commands, "_mas", stuck):
    g2 = A.WeeklyGate(tmpdir(), tmpdir())
    g2._save({"done_week": A.week_key(WED), "restore_to": "Annihilation"})
    check("write does not take -> nothing reported", g2.maybe_reopen(NEXT_MON), "")
    check("write does not take -> state kept for retry", g2._load().get("done_week"), A.week_key(WED))

print("[backend down: the file is read and written instead]")
am = automas_with_file("Annihilation")
with mock.patch.object(commands, "_mas", down):
    g3 = A.WeeklyGate(tmpdir(), am)
    check("read_setting from the file", A.read_setting(am), "Annihilation")
    g3.on_success(WED)
    check("enforce writes Close into ScriptConfig", (g3.enforce(WED), file_value(am)), (True, "Close"))
    check("a backup was left", len(list((am / "config").glob("ScriptConfig.bak-*.json"))), 1)
    check("reopen next week via the file", "Annihilation" in g3.maybe_reopen(NEXT_MON), True)
    check("file restored", file_value(am), "Annihilation")
    check("state cleared", g3._load(), {})

print("[no AUTO-MAS dir configured: the gate does nothing]")
g4 = A.WeeklyGate(tmpdir(), None)
check("on_success", g4.on_success(WED), "")
check("enforce", g4.enforce(WED), False)
check("maybe_reopen", g4.maybe_reopen(NEXT_MON), "")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
