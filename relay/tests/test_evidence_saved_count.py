"""The 🗂️ evidence line counts the files inside the bundle, not the uploads.

The bundle goes up as one archive (evidence.save_and_upload packs every file into
one zip), so res["uploaded"] always holds one link. relay.log 2026-10-12 11:38:15
archived 14 files for MaaEnd-06-04-00, and the 11:38:26 line plus the 🗂️ message
said 「里面 1 个文件」 (audit s17 F2). The count is res["files"].
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import engine as eng_mod                    # noqa: E402
from ark_relay.core import texts                                 # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config, RunRecord   # noqa: E402
from ark_relay.core.ledger import State                          # noqa: E402
from ark_relay.features.alarm import handle                     # noqa: E402
from ark_relay.features.evidence import evidence                # noqa: E402

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
        self.sent.append((title, body))
        return []


class Src:
    def fetch(self, seen):
        return []


cfg = Config()
cfg.state_dir = tmpdir()
cfg.history_dir = None
e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
start = datetime(2026, 10, 12, 10, 5, tzinfo=SERVER_TZ)
rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-04-00", script="MaaEnd", user="endfield",
                started=start, finished=start + timedelta(minutes=30), ok=False, failed_tasks=["x"], raw={})
names = [f"f{i}.log" for i in range(14)]
evidence.save_and_upload = lambda *a, **k: {"files": names, "uploaded": ["https://cos/one.zip"],
                                            "page": "https://cos/page.html", "errors": []}
page = handle._ship_evidence(e, rec)
check("link returned", page, "https://cos/page.html")
saved = [b for t, b in e.notifier.sent if t == texts.EVIDENCE_SAVED]
check("one 🗂️ line", len(saved), 1)
check("it counts the 14 files in the bundle", bool(saved) and "里面 14 个文件" in saved[0], True)
check("not the one upload", bool(saved) and "里面 1 个文件" in saved[0], False)

print("\n" + (f"✗ {len(fails)} failed" if fails else "all checks passed"))
sys.exit(1 if fails else 0)
