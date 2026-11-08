"""The update announcement: dedup, the announce-update log.

One part per former file, each run on its own (tests/_parts.py): test_update_announce.py, test_update_announce_dedup.py, test_announce_update_log.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_main():
    """Cover the "tell me the moment an update takes effect" path.

The tricky case is the first update after this feature ships: the process that
applies it is running the old code and cannot leave a marker, so the
announcement has to be derivable from the version file alone.

    Formerly test_update_announce.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.selfupdate import selfupdate as su


    def fresh():
        root = tmpdir()
        (root / "state").mkdir()
        return root

    print("[first update ever - old code applied it, left no marker]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260821200000")
    n = su.pending_announcement(r)
    check("announces", bool(n), True)
    check("version", n and n["version"], 20260821200000)
    check("no file list", n and n["files"], [])
    check("second boot is silent", su.pending_announcement(r), None)

    print("\n[normal update - marker carries the file list]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260822090000")
    (r / "state" / "announced-version.txt").write_text("20260821200000")
    su._record_announcement(r, {"version": 20260822090000, "previous": 20260821200000,
                                "files": ["ark_relay/core/engine.py"], "at": "2026-08-22T09:00:00+08:00"})
    n = su.pending_announcement(r)
    check("file list survives", n and n["files"], ["ark_relay/core/engine.py"])
    check("previous version", n and n["previous"], 20260821200000)
    check("not repeated", su.pending_announcement(r), None)

    print("\n[no update - must stay silent]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260822090000")
    (r / "state" / "announced-version.txt").write_text("20260822090000")
    check("silent", su.pending_announcement(r), None)

    print("\n[corrupt marker must not crash or block]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260822090000")
    (r / "state" / "announced-version.txt").write_text("20260821200000")
    (r / "state" / "update-announce.json").write_text("{not json")
    n = su.pending_announcement(r)
    check("falls back to version comparison", bool(n), True)
    check("corrupt marker removed", (r / "state" / "update-announce.json").exists(), False)

    print("\n[no version file at all - fresh install, nothing to say]")
    r = fresh()
    check("silent", su.pending_announcement(r), None)

    print("\n[failure is announced too - a silent one leaves old code running]")
    r = fresh()
    su._record_failure(r, "缓存未刷新", 20260821113000, 20260821111012,
                       ["ark_relay/core/engine.py", "ark_relay/core/ledger.py"])
    f = su.take_failure(r)
    check("reported", bool(f), True)
    check("reason", f and f["reason"], "缓存未刷新")
    check("file list", f and f["files"], ["ark_relay/core/engine.py", "ark_relay/core/ledger.py"])
    check("count", f and f["count"], 2)
    check("not repeated", su.take_failure(r), None)

    print("\n[a later success clears the stale complaint]")
    r = fresh()
    su._record_failure(r, "x", 1, 2, ["a.py"])
    su._clear_failure(r)
    check("cleared", su.take_failure(r), None)

    print("\n[corrupt failure marker is removed, not retried forever]")
    r = fresh()
    (r / "state" / "update-failed.json").write_text("{broken")
    check("returns nothing", su.take_failure(r), None)
    check("file removed", (r / "state" / "update-failed.json").exists(), False)

    print("\n[failure and success markers are independent]")
    r = fresh()
    (r / "state" / "code-version.txt").write_text("20260822090000")
    su._record_failure(r, "x", 1, 2, ["a.py"])
    check("failure present", bool(su.take_failure(r)), True)
    check("announcement still works", bool(su.pending_announcement(r)), True)

    print("\n[raw gets a timeout above its measured median]")
    check("RAW_TIMEOUT > 38s median", su.RAW_TIMEOUT > 38, True)


def _part_update_announce_dedup():
    """The same change deployed twice must not be pushed twice.

A deploy refused by a gate, fixed, and deployed again is two versions but one
change. On 2026-09-09 the user got the same paragraph twice inside five minutes
and asked why. The version number differs every time, so it cannot be the test;
what he reads is the release notes, so those are what gets compared.

    Formerly test_update_announce_dedup.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.statestore import StateStore


    root = tmpdir()
    (root / "state").mkdir()
    st = StateStore(root / "state")

    print("[「上一条推送的说明」是个正经登记字段，写得进也读得回]")
    check("一开始是空的", st.get("versions", "announced_notes"), None)
    st.set("versions", "announced_notes", "- 改了甲\n- 改了乙")
    check("换个实例读得回", StateStore(root / "state").get("versions", "announced_notes"),
          "- 改了甲\n- 改了乙")

    print("\n[判据就是原文相等：一样不推，改一个字就推]")
    last = StateStore(root / "state").get("versions", "announced_notes")
    check("一模一样 → 不推", "- 改了甲\n- 改了乙" == last, True)
    check("多一行 → 推", "- 改了甲\n- 改了乙\n- 改了丙" == last, False)
    check("空说明不参与比较（回退到列文件名那条路）", bool("") and "" == last, False)

    print("\n[开机那一段真的用了这个字段，而不是只登记不看]")
    boot = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
    check("读了它", 'get("versions", "announced_notes")' in boot, True)
    check("推成功之后才写", 'set("versions", "announced_notes", notes)' in boot, True)
    check("跳过时仍然记下版本号，免得下次又当成新的",
          "_remember_announced(HERE, int(note.get(\"version\") or 0))" in boot, True)


def _part_announce_update_log():
    """The update announcement says 「更新说明已记入当天日报」 only when it recorded them (audit s23 F6, 10-13).

boot_stages._stage_announce_update logged that line whenever the 🔄 send returned no
errors - and 🔄 is log-only (notify.route_of), so always - even with no
RELEASE-NOTES.md text, when nothing was handed to the daily report. relay/RELEASE-NOTES.md
is 0 bytes between deploys, so the empty case is live. The failed-send branch could no
longer happen and is gone.

    Formerly test_announce_update_log.py.
    """
    import logging

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import boot_stages
    from ark_relay.features.report import report
    from ark_relay.features.selfupdate import selfupdate


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
        lg = logging.getLogger("ark.test_update_announce")
        lg.addHandler(lines)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        try:
            boot_stages._stage_announce_update(Notes(), lg, here / "state")
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


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_update_announce_dedup, _part_announce_update_log]))
