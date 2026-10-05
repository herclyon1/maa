"""A pre-update item that gave no verdict is tried once more, then said - never an alarm.

relay.log 09-29 08:49:14: MAA gave no verdict in its 180 seconds, then
08:50:34 ERROR 「预更新有 1 项没能确认」: the notice went out with alert=True and the
ERROR line itself was a group alarm (errwatch.py, 「🩺 中继自己报错了」). Nobody had
anything to do: the queue ran as usual and every program checks for updates when
it starts. The user, 10-05 13:07: 「几乎就是遇到一点小毛病就停下来报错」. Pinned:

* an item with no verdict runs once more, as a person would; a verdict then
  leaves nothing to report and the day's pre-update counts as clean;
* no verdict twice -> one WARNING line and one notice without alert, routed off
  the group, saying the queue runs as usual and the scripts check themselves;
  no record at ERROR anywhere under "ark";
* no second try when the next queue is too close for a whole one;
* the MaaEnd and OK-WW slots retry the same way;
* the game-update notice is a WARNING and not an alarm either.
"""
import logging
import sys
import types
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
             "win32com", "win32com.client"):
    sys.modules.setdefault(name, _Stub(name))

import boot_stages  # noqa: E402
from ark_relay import gameupdate, okww_overlay, okww_patch, plan, preupdate, texts  # noqa: E402
from ark_relay.errwatch import ARK  # noqa: E402
from ark_relay.notify import route_of  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []


class Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


REC = Records()
ARK_LOG = logging.getLogger(ARK)          # every module logs under it; errwatch listens here
ARK_LOG.addHandler(REC)
ARK_LOG.setLevel(logging.DEBUG)
LOG = ARK_LOG.getChild("service")         # what service.py hands the boot stages

NO_VERDICT = "MAA 预更新：180 秒内没给出更新结论，**本轮没有确认过是否有更新**"
marks = []
boot_stages._stop_requested = lambda: False
boot_stages.ensure_automas = lambda *a, **k: True
boot_stages._revive_automas = lambda: None
preupdate.wanted_today = lambda *a, **k: True
preupdate.should_run = lambda *a, **k: True
preupdate.mark_run = lambda state_dir, now, clean: marks.append(clean)
preupdate.run_automas = lambda automas_dir, problems=None: ""
plan.script_dir = lambda *a, **k: Path("maa")
gameupdate.maaend_reenable_if_updated = lambda cfg: ""
okww_patch.ensure_patches = lambda okww: []
okww_overlay.drift_line = lambda okww, state_dir: ""
CFG = types.SimpleNamespace(automas_dir=None, maaend_dir=Path("maaend"), okww_dir=Path("okww"), state_dir=None)


def scripted(answers, calls, verdict=""):
    """A run_* that leaves the next note in `answers` (None = it gave a verdict)."""
    def run(*a, problems=None, **k):
        calls.append(1)
        note = answers.pop(0) if answers else None
        if note:
            problems.append(note)
            return ""
        return verdict
    return run


def stage(maa_answers, maaend_answers=(), okww_answers=(), left=3600.0):
    REC.records.clear()
    marks.clear()
    calls = {"maa": [], "maaend": [], "okww": []}
    preupdate.run_maa = scripted(list(maa_answers), calls["maa"])
    preupdate.run = scripted(list(maaend_answers), calls["maaend"])
    preupdate.run_okww = scripted(list(okww_answers), calls["okww"])
    boot_stages._seconds_to_next_queue = lambda automas_dir, now: left
    notes = Notes()
    boot_stages._stage_preupdate(CFG, notes, LOG)
    return notes, {k: len(v) for k, v in calls.items()}


def errors():
    return [r.getMessage() for r in REC.records if r.levelno >= logging.ERROR]


def said(fragment):
    return any(fragment in r.getMessage() for r in REC.records)


print("[MAA gave no verdict, the second try did: nothing to report]")
notes, calls = stage([NO_VERDICT, None])
check("MAA ran twice", calls["maa"], 2)
check("the log says it tried again", said("预更新：MAA 没给出结论"))
check("no 「没能确认」 notice", [t for t, _, _ in notes.sent if "没能确认" in t], [])
check("the day's pre-update is clean", marks, [True])
check("nothing at ERROR", errors(), [])

print("\n[no verdict twice (09-29 08:50:34): said, not an alarm]")
notes, calls = stage([NO_VERDICT, NO_VERDICT])
check("MAA ran twice", calls["maa"], 2)
got = [(t, b, a) for t, b, a in notes.sent if "没能确认" in t]
check("one notice", len(got), 1)
title, body, alert = got[0] if got else ("", "", None)
check("title", title, "⚠️ 预更新没能确认（1 项）")
check("not sent as an alert", alert, False)
check("it does not go to the group", route_of(title, alert=alert), "info")
check("the item is listed once (the second try's note)", body.count("MAA 预更新"), 1)
check("it says nobody has to act", "队列照常跑，明日方舟、终末地、鸣潮开跑时自己会查" in body)
check("a WARNING line in the log",
      any(r.levelno == logging.WARNING and "预更新有 1 项没能确认" in r.getMessage() for r in REC.records))
check("nothing at ERROR (errwatch stays quiet)", errors(), [])
check("not clean, so a later start may try again", marks, [False])

print("\n[the next queue is too close: no second try]")
notes, calls = stage([NO_VERDICT, None], left=120.0)
check("MAA ran once", calls["maa"], 1)
check("the log says why", said("离下一个队列只有 120 秒，不再试"))
check("the notice still goes out, not as an alert",
      [(t, a) for t, _, a in notes.sent if "没能确认" in t], [("⚠️ 预更新没能确认（1 项）", False)])

print("\n[the MaaEnd and OK-WW slots retry the same way]")
notes, calls = stage([None], maaend_answers=["MaaEnd 预更新：180 秒内没等到更新检查结束"],
                     okww_answers=["OK-WW 预更新：拿不到控制台会话，**没有检查更新**"])
check("MaaEnd ran twice, OK-WW ran twice", (calls["maaend"], calls["okww"]), (2, 2))
check("both answered the second time: clean", marks, [True])
check("nothing at ERROR", errors(), [])

print("\n[an item that answers at once runs once]")
notes, calls = stage([None])
check("MAA, MaaEnd, OK-WW once each", calls, {"maa": 1, "maaend": 1, "okww": 1})
check("clean", marks, [True])

print("\n[game update that could not confirm: a WARNING, not an alarm]")
REC.records.clear()
gameupdate.should_run = lambda *a, **k: True
gameupdate.boot_check = lambda cfg, budget_s, now: ([], ["终末地：启动器没响应，没能确认有没有新版本"])
gameupdate.mark_run = lambda *a, **k: None
boot_stages._boot_stamp = lambda now: "x"
notes = Notes()
boot_stages._stage_gameupdate(CFG, notes, LOG)
got = [(t, a) for t, _, a in notes.sent]
check("one notice, no alert", got, [("⚠️ 游戏更新没能确认（1 项）", False)])
check("it does not go to the group", route_of(got[0][0], alert=got[0][1]) if got else "", "info")
check("nothing at ERROR", errors(), [])

print("\n[the old tail is gone]")
check("no 「机器跑的还是原来的版本」", "机器跑的还是原来的版本" in texts.preupdate_unconfirmed_tail(), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
