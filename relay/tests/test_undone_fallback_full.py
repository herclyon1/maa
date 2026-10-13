"""When the 「⚠️ 这一轮没干完」 push fails, the fallback errwatch pushes carries the
whole message, not its first line.

Audit 2026-10-13 s7 #6: errwatch keeps first_line only, and the WARNING's first
line ends at 「有项目没干成：」 (relay.log 10-11 09:30:45, 10-12 10:04:11), so the
undone items were cut off and the line went out under the relay-error title.
"""
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                  ARK_AUTOMAS_DIR=str(TMP / "nowhere"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import engine as eng_mod, texts         # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core.ledger import State                    # noqa: E402
from ark_relay.features.alarm import errwatch, handle      # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self, errs):
        self.sent, self.errs = [], errs

    def send(self, title, body="", **kw):
        self.sent.append((title, body))
        return list(self.errs)


class Src:
    def fetch(self, seen):
        return []


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, r):
        self.records.append(r)


handle._ship_evidence = lambda eng, rec: "https://cos.example/okww.zip"
handle._hand_started = lambda eng, rec: ""
handle._weekly_gates = lambda eng, rec: None
handle._push_unverified = lambda eng, rec: None

MSG = "OK-WW 这一轮有 2 项没干成，但它自己没报错：\n· 刷体力：没进本\n· 每日任务：活跃度 80/100"
START = datetime(2026, 10, 11, 9, 0, 5, tzinfo=SERVER_TZ)


def run(errs):
    cfg = Config()
    cfg.state_dir = TMP / f"s-{len(errs)}"
    cfg.state_dir.mkdir()
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes(errs))
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._verify_outcome = lambda r: MSG
    rec = RunRecord(run_id="2026-10-11/wuwa/OK-WW-05-00-05", script="OK-WW", user="wuwa",
                    started=START, finished=START + timedelta(minutes=30), ok=True)
    grab = Grab()
    handle.log.addHandler(grab)
    try:
        handle._handle(e, rec)
    finally:
        handle.log.removeHandler(grab)
    return [r for r in grab.records if "有项目没干成" in r.getMessage()]


print("[the push failed: errwatch gets the whole message under the alarm's title]")
lines = run(["group robot down"])
check("one WARNING", len(lines), 1)
given = getattr(lines[0], errwatch.ALARM, None) if lines else None
check("its own title", given[0] if given else None, texts.ROUND_INCOMPLETE)
check("every undone item in the body", bool(given) and "刷体力：没进本" in given[1] and "每日任务" in given[1], True)
check("the evidence link too", bool(given) and "https://cos.example/okww.zip" in given[1], True)

print("\n[the push went out: no second copy (group_pushed as before)]")
lines = run([])
check("not an own alarm", getattr(lines[0], errwatch.ALARM, None) if lines else "-", None)

print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
