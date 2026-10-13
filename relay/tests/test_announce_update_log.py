"""The update announcement says 「更新说明已记入当天日报」 only when it recorded them (audit s23 F6, 10-13).

boot_stages._stage_announce_update logged that line whenever the 🔄 send returned no
errors - and 🔄 is log-only (notify.route_of), so always - even with no
RELEASE-NOTES.md text, when nothing was handed to the daily report. relay/RELEASE-NOTES.md
is 0 bytes between deploys, so the empty case is live. The failed-send branch could no
longer happen and is gone.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir  # noqa: E402
import boot_stages  # noqa: E402
from ark_relay.features.report import report  # noqa: E402
from ark_relay.features.selfupdate import selfupdate  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **k):
        self.sent.append(title)
        return []


def announce(notes_text: "str | None"):
    """One announcement of version 123 from a code folder whose RELEASE-NOTES.md holds
    `notes_text` (None: no file). Returns (log lines, notes handed to the daily report)."""
    here = tmpdir()
    (here / "state").mkdir()
    if notes_text is not None:
        (here / "RELEASE-NOTES.md").write_text(notes_text, encoding="utf-8")
    kept = []
    saved = (boot_stages.HERE, selfupdate.take_failure, selfupdate.pending_announcement,
             report.remember_change)
    boot_stages.HERE = here
    selfupdate.take_failure = lambda root: None
    selfupdate.pending_announcement = lambda root: {"files": ["a.py"], "version": "123", "at": ""}
    report.remember_change = lambda state_dir, notes, version="", day=None: kept.append(notes)
    lines = Lines()
    lg = logging.getLogger("ark.test_announce_update_log")
    lg.addHandler(lines)
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    try:
        boot_stages._stage_announce_update(Notes(), lg)
    finally:
        (boot_stages.HERE, selfupdate.take_failure, selfupdate.pending_announcement,
         report.remember_change) = saved
        lg.removeHandler(lines)
    return lines.lines, kept


print("[no RELEASE-NOTES.md text: nothing goes to the daily report, and the log does not say it did]")
for text in ("", None):
    lines, kept = announce(text)
    check(f"notes {text!r}: nothing recorded", kept, [])
    check(f"notes {text!r}: no 「已记入当天日报」 line", any("已记入当天日报" in m for m in lines), False)
    check(f"notes {text!r}: says there were no notes", any("没有更新说明" in m for m in lines), True)

print("[notes present: recorded, and said so]")
lines, kept = announce("- 修好了一件事。")
check("recorded", kept, ["- 修好了一件事。"])
check("the 「已记入当天日报」 line", any(m == "更新说明已记入当天日报（v123）" for m in lines), True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
