"""Every fault that fixed itself, and so stays out of the group, leaves a red item in the technical log.

The user, 2026-10-11 17:44 (Tokyo; his words are in relay/USER-SWITCHES.txt's header): what fixed
itself may stay out of the group, but we must look at it. So:

* techlog.add_red never hands out an id twice in one day's file (red_items numbers from 1 on
  every call: two calls in one minute gave the same id, and one `handled` cleared both);
* errwatch's one door for a record marked errwatch.recovered() writes one 「自愈待查」 red item
  with where and what the record said, every time; a plain WARNING writes none (it goes to the group);
* every errwatch.recovered() in the relay sits in the `extra=` of a log call, so it can only
  reach errwatch through that door (nothing marks a record recovered some other way);
* handle's heals (_self_heal_red) write one too;
* scripts/mac/techlog.py's patterns read these red items as unhandled until `handled`.
The USER-SWITCHES side (every `normal-state - recovered:` place has code that writes the red
item) is tests/test_mute_verdicts.py.
"""
import ast
import importlib.util
import logging
import os
import sys
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="", ARK_STATE_DIR=str(TMP / "state"),
                  SERVERCHAN_KEY="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))
from ark_relay.core import techlog  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.alarm import errwatch, handle  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def reds(state_dir, day):
    try:
        text = techlog.path_for(day, state_dir).read_text(encoding="utf-8")
    except OSError:
        return []
    return techlog.unhandled(text)


print("[add_red: ids stay unique within a day, across calls in the same minute]")
d = TMP / "a" / "state"
when = datetime(2026, 10, 11, 17, 50, tzinfo=SERVER_TZ)
first = techlog.add_red("2026-10-11", "x", ["one", "two"], state_dir=d, now=when)
second = techlog.add_red("2026-10-11", "y", ["three"], state_dir=d, now=when)
check("first call", first, ["R-20261011-1750-1", "R-20261011-1750-2"])
check("second call in the same minute goes on after them", second, ["R-20261011-1750-3"])
check("all three unhandled", [i for i, _ in reds(d, "2026-10-11")], first + second)
check("nothing to write writes nothing", techlog.add_red("2026-10-11", "z", ["  "], state_dir=d, now=when), [])
check("a text over several lines stays one red line",
      techlog.add_red("2026-10-11", "z", ["a\nb"], state_dir=TMP / "a2" / "state", now=when) != []
      and [t for _, t in reds(TMP / "a2" / "state", "2026-10-11")] == ["a b"], True)

print("[the Mac reader sees them, and `handled` clears exactly one]")
spec = importlib.util.spec_from_file_location("techlog_tool", RELAY.parent / "scripts" / "mac" / "techlog.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
text = techlog.path_for("2026-10-11", d).read_text(encoding="utf-8")
check("the reader's red pattern matches every red line",
      sum(1 for ln in text.splitlines() if tool.RED_LINE.match(ln)), 3)
text += "\n" + tool.handled_line("R-20261011-1750-2", "abc1234") + "\n"
check("one handled line clears that one only", [i for i, _ in techlog.unhandled(text)],
      ["R-20261011-1750-1", "R-20261011-1750-3"])

print("[errwatch: a recovered record writes one 「自愈待查」 red item, a plain WARNING none]")


class _N:
    channels = ()

    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body))
        return []


ARK = logging.getLogger(errwatch.ARK)
ARK.setLevel(logging.INFO)
sd = TMP / "b" / "state"
sd.mkdir(parents=True)
n = _N()
h = errwatch.ErrorKindAlert(n, state_dir=sd, known={}, pace=0, retry=(0.05,))
ARK.addHandler(h)
try:
    lg = logging.getLogger("ark.test_self_heal_red")
    lg.warning("手机通道断了 20 秒，自己重新连上了", extra=errwatch.recovered())
    lg.warning("手机通道断了 30 秒，自己重新连上了", extra=errwatch.recovered())
    lg.warning("这个没好")
    h.drain(timeout=5.0)
finally:
    ARK.removeHandler(h)
    h.close()
today = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
got = reds(sd, today)
check("two recovered records, two red items", len(got), 2)
check("each says 自愈待查, where, and what it said",
      [(t.startswith(techlog.SELF_HEAL), "ark.test_self_heal_red" in t, "自己重新连上了" in t) for _, t in got],
      [(True, True, True)] * 2)
check("their ids differ", len({i for i, _ in got}), 2)
check("the plain WARNING went to the group and wrote no red item",
      (len(n.sent), any("这个没好" in t for _, t in got)), (1, False))

print("[handle's heals write one too]")
eng = types.SimpleNamespace(cfg=types.SimpleNamespace(state_dir=str(TMP / "c" / "state")))
handle._self_heal_red(eng, "MaaEnd 2026-10-11/endfield/MaaEnd-05-30-34 中途失败过，重试后成功", "自动采集")
got = reds(TMP / "c" / "state", today)
check("one red item naming the run and the first failure",
      [("MaaEnd-05-30-34" in t, "自动采集" in t) for _, t in got], [(True, True)])

print("[every errwatch.recovered() in the relay is the extra= of a log call]")
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
bad, seen = [], 0
for path in sorted(RELAY.rglob("*.py")):
    if "tests" in path.relative_to(RELAY).parts:
        continue
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "recovered" and not node.args and not node.keywords):
            continue
        seen += 1
        up, ok = node, False
        while up in parents:
            par = parents[up]
            if isinstance(par, ast.keyword) and par.arg == "extra":
                call = parents.get(par)
                ok = (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                      and call.func.attr in LOG_METHODS)
                break
            if isinstance(par, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                break
            up = par
        if not ok and path.name != "errwatch.py":
            bad.append(f"{path.relative_to(RELAY)}:{node.lineno}")
check("found the calls", seen > 10, True)
check("none outside a log call's extra=", bad, [])
src = (RELAY / "ark_relay" / "features" / "alarm" / "errwatch.py").read_text(encoding="utf-8")
check("errwatch has no daily-only door any more", "def note_daily" in src, False)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
