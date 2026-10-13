"""The 「像没进游戏」 note is on every MaaEnd failure alarm, not only the held one.

Review of s7 #5 (5a407a4f): _confirm_unreachable's WARNING became INFO and only
pushes._push_unresolved (the held final alarm) adds texts.UNREACHABLE_SHAPE_NOTE.
A MaaEnd failure alarmed straight away - a run a person started at AUTO-MAS, a run
停一切 cut short - said it nowhere. Both now carry it (or the 「公告没读到」 note when
the notices could not be read), as the held alarm does.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                  ARK_AUTOMAS_DIR=str(TMP / "nowhere"), ARK_MAAEND_DIR="", SERVERCHAN_KEY="",
                  ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import engine as eng_mod                    # noqa: E402
from ark_relay.core import texts                                 # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core.ledger import State                          # noqa: E402
from ark_relay.features.alarm import handle                      # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body))
        return []


class Src:
    def fetch(self, seen):
        return []


handle._ship_evidence = lambda eng, r: ""
handle._weekly_gates = lambda eng, r: None
handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: ""   # no official notice today
WHO = {"hand": ("", "task-hand"), "stop": ("06:10 停一切", "")}


def build(state_dir):
    cfg = Config()
    cfg.state_dir = state_dir
    cfg.maaend_dir = None
    e = eng_mod.Engine(cfg, source=Src(), state=State(state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._archive_maaend_evidence = lambda r: None
    return e


T0 = datetime(2026, 10, 12, 6, 4, tzinfo=SERVER_TZ)

for how, label in (("hand", "有人在 AUTO-MAS 上手动开的"), ("stop", "停一切停掉的")):
    print(f"\n[{label}那趟终末地：每个任务秒败、零完成、没有官方公告 → 报警里写「像没进游戏」]")
    stop, hand = WHO[how]
    handle._estop_overlap = lambda eng, r, s=stop: s
    handle._hand_started = lambda eng, r, h=hand: h
    state = TMP / how
    state.mkdir()
    e = build(state)
    rec = RunRecord(run_id=f"2026-10-12/endfield/MaaEnd-06-04-{how}", script="MaaEnd", user="endfield",
                    started=T0, finished=T0 + timedelta(minutes=1), ok=False,
                    failed_tasks=["协议空间", "自动采集"], raw={"maaend_unreachable": True})
    handle._handle(e, rec)
    check("按普通失败处理（形状留着）", (rec.raw.get("maaend_unreachable_shape"), rec.raw.get("maaend_unreachable")),
          (True, None))
    check("当场报了一条", len(e.notifier.sent), 1)
    check("那条里写了「像没进游戏」", texts.UNREACHABLE_SHAPE_NOTE in (e.notifier.sent or [("", "")])[0][1])

print("\n[公告没读到 → 写「没读到」那句]")
handle._estop_overlap = lambda eng, r: ""
handle._hand_started = lambda eng, r: "task-hand"


def _unread(now=None, fetch=None, strict=False):
    raise OSError("efstatus down")


handle.efstatus.update_hint = _unread
state = TMP / "unread"
state.mkdir()
e = build(state)
rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-04-unread", script="MaaEnd", user="endfield",
                started=T0, finished=T0 + timedelta(minutes=1), ok=False,
                failed_tasks=["协议空间"], raw={"maaend_unreachable": True})
handle._handle(e, rec)
body = (e.notifier.sent or [("", "")])[0][1]
check("写了「没读到」", texts.UNREACHABLE_UNREAD_NOTE in body)
check("不写「今天没有官方公告」", texts.UNREACHABLE_SHAPE_NOTE in body, False)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
