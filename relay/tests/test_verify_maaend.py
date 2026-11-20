"""MaaEnd collector, task-trail verification (#28), and Endfield failure classification."""
from __future__ import annotations

# ruff: noqa: PLC0415
import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


class _NoSource:
    """A record source with nothing new."""
    def fetch(self, seen):
        return []


class _Lines(logging.Handler):
    """Keeps the message of every record from `level` up."""
    def __init__(self, level):
        super().__init__(level)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class _Notes:
    """A notifier that keeps (title, body, alert) and reports every channel delivered."""
    def __init__(self):
        self.sent = []

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body, alert))
        return []


def _run_mc28_one_alarm():
    import gzip
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                      ARK_AUTOMAS_DIR=str(TMP / "nowhere"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                      ARK_LOG_FILE=str(TMP / "relay.log"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng_mod, texts
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features import handle, handle as runchecks, handle as unresolved
    from ark_relay.features import makeup
    from ark_relay.features import machinecheck as mc
    from ark_relay.features import machinechecks as runs
    from ark_relay.features import collector_maaend

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-task-trail"

    handle._ship_evidence = lambda eng, rec: "https://cos.example/endfield.zip"
    handle._hand_started = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None

    FAILED_0631 = ["拜访好友", "基建任务", "信用点购物", "转交委托", "据点交易", "环境监测", "自动囤货", "售卖弹性物资",
                   "购买稳定物资", "协议空间", "选剑演武", "自动采集", "日常奖励领取"]
    ABORT = ("2026-10-08_MaaEnd-06-31-06.log", datetime(2026, 10, 8, 10, 32, 8, tzinfo=SERVER_TZ), 2.2)
    RETRY = ("2026-10-08_MaaEnd-06-34-21.log", datetime(2026, 10, 8, 10, 35, 24, tzinfo=SERVER_TZ), 38)
    CRAFTED = ("2026-10-08_MaaEnd-05-29-15.log", datetime(2026, 10, 8, 9, 30, 13, tzinfo=SERVER_TZ), 60)
    MC28_FAILED = texts.machinecheck_failed("#28", "")
    REASON = "· 装备制造：终末地自己检查画面没过，把后面的任务全停了，这一项没做成"

    def held_28(state):
        return runs._state_get(state, getattr(runs, "HELD_28", "#28-held")) or {}

    def engine(state=None):
        """(Engine, Notes, state folder): a fresh Engine on `state` (a new folder when None)."""
        cfg = Config()
        if state is None:
            state = tmpdir() / "state"
            state.mkdir()
        cfg.state_dir = state
        end = tmpdir()
        (end / "debug").mkdir()
        (end / "debug" / "maafw.log").write_bytes(gzip.decompress((FIX / "maafw-2026-10-08.log.gz").read_bytes()))
        cfg.maaend_dir = str(end)
        notes = _Notes()
        e = eng_mod.Engine(cfg, source=_NoSource(), state=State(cfg.state_dir), notifier=notes)
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: None
        return e, notes, state

    def book(e, run, ok, rid=None, later_h=0):
        name, started, mins = run
        started += timedelta(hours=later_h)
        log = FIX / name
        rec = RunRecord(run_id=rid or f"2026-10-08/endfield/{name[11:-4]}", script="MaaEnd", user="endfield",
                        started=started, finished=started + timedelta(minutes=mins), ok=ok,
                        failed_tasks=[] if ok else list(FAILED_0631),
                        raw=collector_maaend.parse_maaend_log(log), log_path=log)
        handle._handle(e, rec)
        return rec

    def group(*notes):
        return [(t, b) for n in notes for t, b, alert in n.sent if alert]

    def show(*notes):
        for t, b in group(*notes):
            print(f"    group: {t} | {b[:120]!r}")

    def mc28_pushes(*notes):
        return [b for t, b in group(*notes) if t.startswith(MC28_FAILED)]

    print("[real shape: 06-31-06 ok=False with 13 failed tasks, held; its retry 06-34-21 ok=True]")
    e, notes, state = engine()
    book(e, ABORT, ok=False)
    check("nothing reaches the group while the abort waits for its retry", group(notes), [])
    row = mc.read(state).get("#28") or {}
    ev = str(row.get("evidence") or "")
    check("#28's FAIL of the held abort is on record, saying it waits for the retry",
          (row.get("status"), "等这一班的重试跑完" in ev), ("FAIL", True))
    check("…and does not say it went to the group", "进群里" in ev or "已写在" in ev, False)
    check("…and is kept to be settled", list(held_28(state)), ["2026-10-08/endfield/MaaEnd-06-31-06"])
    book(e, RETRY, ok=True)
    handle._flush_pending(e)
    show(notes)
    check("one group message for the abort and the retry", len(group(notes)), 1)
    title, body = group(notes)[0] if group(notes) else ("", "")
    check("…the retry's 「没证据」 alarm for both items", title, texts.unverified_alarm("终末地", "早班", 2))
    check("…carrying MaaEnd's own verdict and reason for 装备制造",
          (REASON in body, "账号编号显示不全" in body), (True, True))
    check("no 「上机核对没过：#28」 of its own", mc28_pushes(notes), [])
    check("nothing of #28 is left waiting", held_28(state), {})
    check("the per-record note is dropped after the checks", runchecks._UNVERIFIED, {})

    print("\n[real shape twice the same day: abort + retry in the morning, abort + retry in the evening]")
    e, notes, state = engine()
    book(e, ABORT, ok=False)
    book(e, RETRY, ok=True)
    handle._flush_pending(e)
    n_morning = len(group(notes))
    book(e, ABORT, ok=False, rid="2026-10-08/endfield/MaaEnd-14-31-06", later_h=8)
    book(e, RETRY, ok=True, rid="2026-10-08/endfield/MaaEnd-14-34-21", later_h=8)
    handle._flush_pending(e)
    show(notes)
    check("the morning abort: one message", n_morning, 1)
    check("the evening abort reaches the group too: two messages in all", len(group(notes)), 2)
    check("…the second is the evening run's own 「没证据」 alarm naming 装备制造 and MaaEnd's reason",
          [("装备制造" in b, "账号编号显示不全" in b) for _t, b in group(notes)[1:]], [(True, True)])
    check("…so #28 does not push it again", mc28_pushes(notes), [])
    check("nothing of #28 is left waiting", held_28(state), {})

    print("\n[ok=True abort twice the same day: the 「没证据」 alarm for the same items goes out once]")
    e, notes, state = engine()
    book(e, ABORT, ok=True)
    book(e, ABORT, ok=True, rid="2026-10-08/endfield/MaaEnd-14-31-06", later_h=8)
    show(notes)
    got = group(notes)
    check("two group messages for two aborts", len(got), 2)
    check("…the first the 「没证据」 alarm with the reason",
          (got[0][0] if got else "", REASON in (got[0][1] if got else "")),
          (texts.unverified_alarm("终末地", "早班", 1), True))
    check("…the second its own 「没证据」 alarm too (D210, audit 11-08 C-01), not #28's FAIL",
          (REASON in (got[1][1] if len(got) > 1 else ""), len(mc28_pushes(notes))), (True, 0))

    print("\n[the same ok=True record replayed (its handling broke off): still the one alarm it sent]")
    e, notes, state = engine()
    book(e, ABORT, ok=True)
    book(e, ABORT, ok=True)
    show(notes)
    check("one group message, the 「没证据」 alarm", [t for t, _ in group(notes)],
          [texts.unverified_alarm("终末地", "早班", 1)])

    print("\n[the held abort's retries never get through: its alarm goes out, and so does #28's FAIL]")
    e, notes, state = engine()
    real_after, real_refuse = unresolved.after_makeup, makeup.refuse_rejected
    unresolved.after_makeup = lambda eng, rec, now=None: (unresolved.UNRESOLVED, "补跑也没成")
    makeup.refuse_rejected = lambda eng, rec: None
    try:
        book(e, ABORT, ok=False)
        check("waiting, nothing sent", group(notes), [])
        handle._flush_pending(e)
    finally:
        unresolved.after_makeup, makeup.refuse_rejected = real_after, real_refuse
    show(notes)
    check("two messages: the failure alarm and #28's FAIL", len(group(notes)), 2)
    check("#28's FAIL for 装备制造 went out once the hold ended",
          [("装备制造" in b, "账号编号显示不全" in b) for b in mc28_pushes(notes)], [(True, True)])
    check("nothing of #28 is left waiting", held_28(state), {})

    print("\n[a relay restart between the abort and its retry]")
    e, notes, state = engine()
    book(e, ABORT, ok=False)
    e2, notes2, _ = engine(state)
    check("the abort is still held after the restart",
          [r.run_id for r in e2._pending.values()], ["2026-10-08/endfield/MaaEnd-06-31-06"])
    book(e2, RETRY, ok=True)
    handle._flush_pending(e2)
    show(notes, notes2)
    check("one group message, the 「没证据」 alarm with the reason",
          [(t, REASON in b) for t, b in group(notes, notes2)],
          [(texts.unverified_alarm("终末地", "早班", 2), True)])

    print("\n[a run of the same day that crafted is booked after the held abort: made up for]")
    e, notes, state = engine()
    book(e, ABORT, ok=False)
    book(e, CRAFTED, ok=True, rid="2026-10-08/endfield/MaaEnd-07-29-15")
    handle._flush_pending(e)
    show(notes)
    check("no group message names 装备制造", [t for t, b in group(notes) if "装备制造" in t + b], [])
    check("no 「上机核对没过：#28」", mc28_pushes(notes), [])
    check("nothing of #28 is left waiting", held_28(state), {})
    sec = [x for x in mc.daily_section(state).splitlines() if "#28" in x]
    print(f"    daily: {sec}")
    check("the daily section says the abort's 装备制造 failed and was made up for",
          any("装备制造" in x and "不用人管" in x for x in sec), True)

    return types.SimpleNamespace(**locals())


def _part_mc28_settle_once():
    """A held #28 FAIL reaches the group once, even when a state file cannot be written
or read at the wrong moment.
    """
    import logging

    base = _run_mc28_one_alarm()  # its own scenarios run on import

    from ark_relay.core import config as config_mod
    from ark_relay.features import handle, handle as unresolved
    from ark_relay.features import makeup
    from ark_relay.features import machinecheck as mc
    from ark_relay.features import machinechecks as runs

    ERRORS = _Lines(logging.ERROR)
    runs._log_runs.addHandler(ERRORS)

    REAL_AFTER, REAL_REFUSE = unresolved.after_makeup, makeup.refuse_rejected
    REAL_WRITE_TEXT, REAL_MC_WRITE = config_mod.atomic_write_text, mc._write
    REAL_READ_TEXT = Path.read_text
    unresolved.after_makeup = lambda eng, rec, now=None: (unresolved.UNRESOLVED, "补跑也没成")
    makeup.refuse_rejected = lambda eng, rec: None

    def pushes(notes):
        return len(base.mc28_pushes(notes))

    try:
        print("\n[A: machinecheck.json cannot be written once, right after #28's push]")
        e, notes, state = base.engine()
        base.book(e, base.ABORT, ok=False)
        check("held, nothing sent at booking", base.group(notes), [])
        left = {"n": 1}

        def _mc_write_fails_once(state_dir, data):
            if left["n"]:
                left["n"] -= 1
                raise OSError(13, "Permission denied (test)")
            return REAL_MC_WRITE(state_dir, data)

        mc._write = _mc_write_fails_once
        handle._flush_pending(e)
        mc._write = REAL_MC_WRITE
        first = pushes(notes)
        handle._flush_pending(e)
        check("the write did fail during that settle", left["n"], 0)
        check("#28 pushed once after the first tick", first, 1)
        check("…and still once after the second", pushes(notes), 1)
        check("nothing of #28 is left waiting", base.held_28(state), {})

        print("\n[B: machinecheck-runs.json cannot be replaced at all while the hold ends]")
        e, notes, state = base.engine()
        base.book(e, base.ABORT, ok=False)
        check("held, nothing sent at booking", base.group(notes), [])
        held_before = list(base.held_28(state))

        def _runs_file_locked(path, text, newline=None):
            if Path(path).name == runs.SEEN_FILE:
                raise PermissionError(13, "The process cannot access the file (test)")
            return REAL_WRITE_TEXT(path, text, newline)

        config_mod.atomic_write_text = _runs_file_locked
        ERRORS.lines.clear()
        counts = []
        try:
            for _ in range(3):
                handle._flush_pending(e)
                counts.append(pushes(notes))
        finally:
            config_mod.atomic_write_text = REAL_WRITE_TEXT
        check("#28 pushes over three ticks: once, not once per tick", counts, [1, 1, 1])
        check("the hold could not be cleared, and that is an ERROR",
              any("#28" in x and runs.SEEN_FILE in x for x in ERRORS.lines), True)
        check("the entry is still on file while the file is locked", list(base.held_28(state)), held_before)
        handle._flush_pending(e)
        check("once the file can be written: cleared", base.held_28(state), {})
        check("…without another push", pushes(notes), 1)

        print("\n[C: the hold is written, then one read of machinecheck-runs.json fails]")
        e, notes, state = base.engine()
        armed = {"read": False, "hit": 0}

        def _arm_after_hold(path, text, newline=None):
            armed["read"] = False
            REAL_WRITE_TEXT(path, text, newline)
            if Path(path).name == runs.SEEN_FILE and runs.HELD_28 in text and not armed["hit"]:
                armed["read"] = True

        def _read_fails_once(self, *a, **kw):
            if armed["read"] and self.name == runs.SEEN_FILE:
                armed["read"], armed["hit"] = False, armed["hit"] + 1
                raise OSError(5, "Input/output error (test)")
            return REAL_READ_TEXT(self, *a, **kw)

        config_mod.atomic_write_text = _arm_after_hold
        Path.read_text = _read_fails_once
        try:
            base.book(e, base.ABORT, ok=False)
        finally:
            config_mod.atomic_write_text, Path.read_text = REAL_WRITE_TEXT, REAL_READ_TEXT
        at_booking = pushes(notes)
        handle._flush_pending(e)
        handle._flush_pending(e)
        check("no #28 push at booking: the hold was written", at_booking, 0)
        check("#28 pushed once in all, when the hold ended", pushes(notes), 1)
        check("nothing of #28 is left waiting", base.held_28(state), {})
    finally:
        unresolved.after_makeup, makeup.refuse_rejected = REAL_AFTER, REAL_REFUSE
        config_mod.atomic_write_text, mc._write, Path.read_text = REAL_WRITE_TEXT, REAL_MC_WRITE, REAL_READ_TEXT



def _part_mc28_state():  # noqa: C901
    """Machine check #28's held FAILs and state/machinecheck-runs.json under the failures a
Windows relay meets: one cause reaches the group once, and no alarm is lost.
    """
    import contextlib
    import json
    import logging
    import os
    from datetime import datetime

    base = _run_mc28_one_alarm()  # its own scenarios run on import

    from ark_relay.core import statestore, texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import handle, handle as pushes, handle as runchecks
    from ark_relay.features import machinecheck as mc
    from ark_relay.features import machinechecks as runs

    DAY = "2026-10-08"
    R1, R2, R3 = (f"{DAY}/endfield/MaaEnd-0{h}-00-00" for h in (1, 2, 3))
    MC28 = texts.machinecheck_failed("#28", "")
    REAL_READ_TEXT, REAL_REPLACE, REAL_MC_WRITE = Path.read_text, os.replace, mc._write
    REAL_TASK_WINDOW, REAL_WINDOW = runs._task_window, runs.cm.maafw_window
    REAL_TASK_TIMES, REAL_TRAIL = runs.cm.task_times, runs.maaend_fwlog.trail_table
    REAL_RUNS_TIME, REAL_SS_WRITE = runs.time, statestore.atomic_write_text
    NO_WAITS = (0.0, 0.0, 0.0)

    ERRORS = _Lines(logging.ERROR)
    for name in ("ark.runs", "ark.machinecheck", "ark.pushes", "ark.unresolved", "ark.statestore"):
        logging.getLogger(name).addHandler(ERRORS)
    pushes.log.addHandler(ERRORS)

    class Notes:
        def __init__(self, errs=()):
            self.sent, self.errs = [], list(errs)

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body))
            return list(self.errs)

    class Rec:
        def __init__(self, rid):
            self.run_id, self.script, self.user = rid, "MaaEnd", "endfield"

    def entry(rid):
        return {"script": "MaaEnd", "user": "endfield", "day": DAY, "tasks": ["装备制造"],
                "evidence": f"{rid} 装备制造没做成", "covered": []}

    def fresh(*held, raw=None):
        """A state folder whose machinecheck-runs.json holds `held` and the other keys, or
    the bytes / text `raw`."""
        state = tmpdir() / "state"
        state.mkdir()
        data = {runs.HELD_28: {rid: entry(rid) for rid in held}, "#7-miss": 1, "#28-miss": 1, "#6": [R1]}
        raw = json.dumps(data, ensure_ascii=False) if raw is None else raw
        (state / runs.SEEN_FILE).write_bytes(raw.encode("utf-8") if isinstance(raw, str) else raw)
        return state

    def on_file(state, key):
        return json.loads((state / runs.SEEN_FILE).read_text(encoding="utf-8-sig")).get(key)

    def marks():
        got = set()
        return got, (lambda day, key: (day, key) in got, lambda day, key: got.add((day, key)))

    def settle(state, alerted, notes):
        """settle_28 with every hold over; the run ids #28 pushed so far."""
        runs.settle_28(state, lambda script, user: True, lambda day: [], notes, alerted=alerted)
        return sorted(rid for rid in (R1, R2, R3) for t, b in notes.sent if t.startswith(MC28) and rid in b)

    def ctx28(state, rid, alerted):
        return {"rec": Rec(rid), "held": [rid], "state_dir": state, "day": DAY, "alerted": alerted,
                "unverified_alarm": []}

    class read_fails:
        """Path.read_text of machinecheck-runs.json fails `n` times with `exc`."""

        def __init__(self, exc, n=1):
            self.exc, self.n = exc, n

        def __enter__(self):
            def _read(path, *a, **kw):
                if self.n and path.name == runs.SEEN_FILE:
                    self.n -= 1
                    raise self.exc
                return REAL_READ_TEXT(path, *a, **kw)
            Path.read_text = _read
            return self

        def __exit__(self, *a):
            Path.read_text = REAL_READ_TEXT

    class replace_locked:
        """os.replace onto machinecheck-runs.json refused `n` times as Windows refuses a
    file another handle holds open (ERROR_SHARING_VIOLATION -> PermissionError)."""

        def __init__(self, n):
            self.n = n

        def __enter__(self):
            def _replace(src, dst, *a, **kw):
                if self.n and Path(dst).name == runs.SEEN_FILE:
                    self.n -= 1
                    raise PermissionError(13, "being used by another process (test)")
                return REAL_REPLACE(src, dst, *a, **kw)
            os.replace = _replace
            return self

        def __exit__(self, *a):
            os.replace = REAL_REPLACE

    class no_waits:
        """A lock that outlasts every wait, without the test sleeping through the waits."""

        def __enter__(self):
            self.was = getattr(mc, "LOCK_WAITS", None)
            mc.LOCK_WAITS = NO_WAITS
            return self

        def __exit__(self, *a):
            if self.was is None:
                del mc.LOCK_WAITS
            else:
                mc.LOCK_WAITS = self.was

    def judge_one(state, result, notifier):
        """mc.judge with one check of event 「run」 that returns `result`."""
        saved = dict(mc.CHECKS)
        mc.CHECKS.clear()
        mc.CHECKS["#28"] = mc.Check("#28", saved["#28"].what, "A", ("run",), lambda ctx: result)
        try:
            return mc.judge(state, "run", {}, notifier=notifier)
        finally:
            mc.CHECKS.clear()
            mc.CHECKS.update(saved)

    def mc28_sent(notes):
        return len([t for t, _ in notes.sent if t.startswith(MC28)])

    def section(title, fn):
        print(f"\n[{title}]")
        ERRORS.lines.clear()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(f"{title}: ran to the end", f"{type(exc).__name__}: {exc}", "")
        finally:
            Path.read_text, os.replace, mc._write = REAL_READ_TEXT, REAL_REPLACE, REAL_MC_WRITE
            runs.time, statestore.atomic_write_text = REAL_RUNS_TIME, REAL_SS_WRITE

    mc.load()

    def item1():
        for exc in (PermissionError(13, "locked (test)"), OSError(5, "Input/output error (test)")):
            state = fresh(R1)
            with read_fails(exc) as rf:
                runs.covered_28(state, "MaaEnd", DAY, ["装备制造"])
            check(f"the first read did fail ({type(exc).__name__})", rf.n, 0)
            check("…the cover is on file anyway",
                  ((on_file(state, runs.HELD_28) or {}).get(R1) or {}).get("covered"), ["装备制造"])
            _, alerted = marks()
            check("…so the end of the hold pushes nothing of R1", settle(state, alerted, Notes()), [])
        state = fresh(R1)
        before = (state / runs.SEEN_FILE).read_bytes()
        runs.covered_28(state, "MaaEnd", "2026-10-09", ["装备制造"])
        check("an alarm about another day changes nothing", (state / runs.SEEN_FILE).read_bytes(), before)

    def item2():
        state = fresh(R1)                     # an older entry of R1 on file
        got, alerted = marks()
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=99):
            r = runs._fail_28(ctx28(state, R1, alerted), ["装备制造"], entry(R1)["evidence"])
        check("the hold could not be kept: a FAIL pushed at once", (r.status, r.deferred), (mc.FAIL, False))
        check("…not marked sent before its push", got, set())
        judge_one(state, r, Notes(errs=["企业微信 500 (test)"]))
        check("the push failed: still not marked sent", got, set())
        check("…so the older entry of R1 is pushed when its hold ends", settle(state, alerted, Notes()), [R1])

        state = fresh(R1)
        got, alerted = marks()
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=99):
            r = runs._fail_28(ctx28(state, R1, alerted), ["装备制造"], entry(R1)["evidence"])
        notes = Notes()
        judge_one(state, r, notes)
        check("a push that went out is marked sent", got, {(DAY, f"#28|{R1}")})
        check("…so the older entry of R1 is dropped without a second push",
              (mc28_sent(notes), settle(state, alerted, Notes())), (1, []))

    def item3():
        state = tmpdir() / "state"
        state.mkdir()

        def _locked(state_dir, data):
            raise PermissionError(13, "The process cannot access the file (test)")

        mc._write = _locked
        notes = Notes()
        try:
            judge_one(state, mc.Result(mc.FAIL, "装备制造没做成 (test)"), notes)
        except OSError as exc:
            check("judge does not raise", type(exc).__name__, "")
        check("machinecheck.json locked: the FAIL is pushed all the same", mc28_sent(notes), 1)
        check("…and the write that failed is an ERROR", any(mc.STATE_FILE in x for x in ERRORS.lines))

    def item4():
        good = json.dumps({runs.HELD_28: {R1: entry(R1)}, "#6": [R1]}, ensure_ascii=False)
        state = fresh(raw=b"\xef\xbb\xbf" + good.encode("utf-8"))
        check("a file with a UTF-8 BOM (Notepad) is read", sorted(runs._state_get(state, runs.HELD_28) or {}), [R1])
        check("…and written to, keeping what was in it",
              (runs._state_set(state, "#7-miss", 3), sorted(on_file(state, runs.HELD_28) or {})), (True, [R1]))
        check("…without an ERROR", ERRORS.lines, [])

        for name, text in (("broken JSON", good[:-9]), ("not a table", "[1, 2]")):
            ERRORS.lines.clear()
            state = fresh(raw=text)
            _, alerted = marks()
            r = runs._fail_28(ctx28(state, R3, alerted), ["装备制造"], entry(R3)["evidence"])
            runs._state_set(state, "#7-miss", 1)
            runs._mark_seen(state, "#6", [R2])
            copies = sorted(p.name for p in state.iterdir() if ".corrupt-" in p.name)
            check(f"{name}: copied aside as it was",
                  (len(copies), (state / copies[0]).read_text(encoding="utf-8") if copies else None), (1, text))
            check(f"{name}: one ERROR over three writes", len([x for x in ERRORS.lines if runs.SEEN_FILE in x]), 1)
            if name == "broken JSON":
                check("…naming the held FAIL it took with it", any(R1 in x for x in ERRORS.lines))
            check(f"{name}: then written from empty: R3 held, the others written",
                  (r.deferred, sorted(on_file(state, runs.HELD_28) or {}), on_file(state, "#7-miss"),
                   on_file(state, "#6")), (True, [R3], 1, [R2]))

    def item4b():
        state = fresh(R1, R2)
        check("read once while it can be read", sorted(runs._state_get(state, runs.HELD_28) or {}), [R1, R2])

        class Eng:
            class cfg:
                state_dir = None
            _pending = {}
            notifier = Notes()
            state = type("S", (), {"read_ledger": staticmethod(lambda day: [])})()

            def _script_running(self, name):
                return False

            def _already_alerted(self, day, key):
                return False

            def _mark_alerted(self, day, key):
                pass

        Eng.cfg.state_dir = state
        eng = Eng()
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
            for _ in range(3):
                runchecks._settle_held(eng)
        stuck = [x for x in ERRORS.lines if runs.SEEN_FILE in x]
        check("three ticks locked: one ERROR", len(stuck), 1)
        check("…naming the holds stuck behind it", bool(stuck) and R1 in stuck[0] and R2 in stuck[0])
        runchecks._settle_held(eng)
        check("readable again: both settled, each pushed once",
              (mc28_sent(eng.notifier), on_file(state, runs.HELD_28)), (2, {}))

    def item5():
        state = fresh(R1)
        with replace_locked(2) as rl:
            wrote = runs._state_set(state, "#7-miss", 2)
        check("os.replace refused twice, then let through", rl.n, 0)
        check("…written, no ERROR", (wrote, on_file(state, "#7-miss"), ERRORS.lines), (True, 2, []))
        check("…no temp file left behind", sorted(p.name for p in state.iterdir()), [runs.SEEN_FILE])
        with no_waits(), replace_locked(99):
            wrote = runs._state_set(state, "#7-miss", 5)
        check("a lock that outlasts the waits: not written, one ERROR",
              (wrote, on_file(state, "#7-miss"), len([x for x in ERRORS.lines if "PermissionError" in x])),
              (False, 2, 1))

    def item6():
        t0 = datetime(2026, 10, 8, 10, 0, tzinfo=SERVER_TZ)
        t1 = datetime(2026, 10, 8, 10, 2, tzinfo=SERVER_TZ)
        rec = type("R", (), {"run_id": R2, "script": "MaaEnd", "user": "endfield", "started": t0})()
        runs._task_window = lambda text, task: (t0, t1)
        runs.cm.maafw_window = lambda d, a, b: ([], "maafw.log 里这一段没有（test）")
        try:
            state = fresh()
            with read_fails(PermissionError(13, "locked (test)")) as rf:
                r = runs._c7({"rec": rec, "raw": {}, "log_text": "", "state_dir": state})
            check("#7: the read did fail once", rf.n, 0)
            check("#7: 1 on file + this run = 2, not started over at 1", on_file(state, "#7-miss"), 2)
            check("…so this second run in a row is the FAIL", getattr(r, "status", None), mc.FAIL)
        finally:
            runs._task_window, runs.cm.maafw_window = REAL_TASK_WINDOW, REAL_WINDOW
        e = {"t0": t0.isoformat(), "t1": t1.isoformat(), "found": False, "unread": True}
        runs.cm.task_times = lambda text: {"装备制造": (t0, t1)}
        runs.maaend_fwlog.trail_table = lambda d, times, text="": ({"装备制造": dict(e)}, "日志换过（test）")
        try:
            state = fresh()
            with read_fails(OSError(5, "Input/output error (test)")) as rf:
                runs._c28({"rec": rec, "raw": {}, "log_text": "", "state_dir": state, "held": []})
            check("#28: the read did fail once", rf.n, 0)
            check("#28: 1 on file + this run = 2, not started over at 1", on_file(state, "#28-miss"), 2)
            state = fresh()
            with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=99):
                r = runs._c28({"rec": rec, "raw": {}, "log_text": "", "state_dir": state, "held": []})
            check("#28: the count unreadable: the unread task waits, nothing reset on file",
                  (r, on_file(state, "#28-miss")), (None, 1))
        finally:
            runs.cm.task_times, runs.maaend_fwlog.trail_table = REAL_TASK_TIMES, REAL_TRAIL

    def item7():
        t0 = datetime(2026, 10, 8, 10, 0, tzinfo=SERVER_TZ)
        rec = type("R", (), {"run_id": R2, "script": "MaaEnd", "user": "endfield", "started": t0})()
        restarts = {R1: {"version": "v1.2.3", "started": t0.isoformat(), "done": R2, "held": False}}

        def ctx(state):
            return {"rec": rec, "raw": {}, "state_dir": state, "update_restarts": restarts, "relay_errors": []}

        state = fresh()                       # R1 is on #6's seen list
        with read_fails(PermissionError(13, "locked (test)")):
            r = runs._update_restart_check(ctx(state), "#6")
        check("one failed read: R1 judged already, not judged again", r, None)
        with no_waits(), read_fails(OSError(5, "Input/output error (test)"), n=99):
            r = runs._update_restart_check(ctx(state), "#24a")
        check("unreadable: not judged (it may have been)", r, None)
        check("…and not marked seen meanwhile", on_file(state, "#24a"), None)
        check("readable again: judged then",
              getattr(runs._update_restart_check(ctx(state), "#24a"), "status", None), mc.PASS)

    def item8():
        e, notes, state = base.engine()
        base.book(e, base.ABORT, ok=False)
        real_mark = e._mark_alerted
        mine = f"{pushes.UNVERIFIED_BY}|"

        def _mark(day, key):
            if key.startswith(mine):
                raise PermissionError(13, "state.json locked (test)")
            return real_mark(day, key)

        e._mark_alerted = _mark
        try:
            base.book(e, base.RETRY, ok=True)
        finally:
            e._mark_alerted = real_mark
        handle._flush_pending(e)
        base.show(notes)
        check("one group message for the abort and the retry", len(base.group(notes)), 1)
        check("…no 「上机核对没过：#28」 of its own", base.mc28_pushes(notes), [])
        check("no ERROR saying the 「没证据」 alarm did not go out", [x for x in ERRORS.lines if "没能推到群里" in x], [])
        check("the mark that could not be written is an ERROR saying so",
              any("已经发出" in x and "没记下" in x for x in ERRORS.lines))
        check("nothing of #28 is left waiting", base.held_28(state), {})

    class Eng4b:
        """The engine attributes runchecks._settle_held reads."""
        _pending = {}
        state = type("S", (), {"read_ledger": staticmethod(lambda day: [])})()

        def __init__(self, state):
            self.cfg = type("C", (), {"state_dir": state})()
            self.notifier = Notes()

        def _script_running(self, name):
            return False

        def _already_alerted(self, day, key):
            return False

        def _mark_alerted(self, day, key):
            pass

    def item9():
        state = fresh()                       # nothing held
        check("read once while it can be read: nothing held", runs._state_get(state, runs.HELD_28), {})
        eng = Eng4b(state)
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
            for _ in range(3):
                runchecks._settle_held(eng)
        check("locked, the last good read held nothing: no ERROR",
              [x for x in ERRORS.lines if runs.SEEN_FILE in x], [])
        ERRORS.lines.clear()
        state = fresh(R1)                     # never read in this process: what is held is unknown
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
            for _ in range(3):
                runchecks._settle_held(Eng4b(state))
        stuck = [x for x in ERRORS.lines if runs.SEEN_FILE in x]
        check("locked, never read: one ERROR saying what is held is not known",
              (len(stuck), bool(stuck) and "不知道" in stuck[0]), (1, True))

    class Sleeps:
        """runs.time with a sleep that only counts."""

        def __init__(self):
            self.n = 0

        def sleep(self, s):
            self.n += 1

    def one_pass():
        """runs.one_pass, or no pass at all where there is none (before 10-17)."""
        return getattr(runs, "one_pass", contextlib.nullcontext)()

    class ss_no_waits:
        """statestore.LOCK_WAITS set to no waits (set even where it does not exist yet)."""

        def __enter__(self):
            self.was = getattr(statestore, "LOCK_WAITS", None)
            statestore.LOCK_WAITS = NO_WAITS

        def __exit__(self, *a):
            if self.was is None:
                del statestore.LOCK_WAITS
            else:
                statestore.LOCK_WAITS = self.was

    def item10():
        state = fresh(R1)
        clock = runs.time = Sleeps()
        with read_fails(PermissionError(13, "locked (test)"), n=999):
            runs._state_read(state)
            runs._state_read(state)
        waits = len(mc.LOCK_WAITS)
        check("outside a booking or tick each locked read waits all of LOCK_WAITS", clock.n, 2 * waits)
        clock.n = 0
        with read_fails(PermissionError(13, "locked (test)"), n=999), one_pass():
            got = [runs._state_read(state) for _ in range(6)]
        check("inside one: only the first read waits, every read is None (never {})",
              (clock.n, got), (waits, [None] * 6))
        clock.n = 0
        with read_fails(PermissionError(13, "locked (test)"), n=999), one_pass():
            runs._state_read(state)
        check("the next booking or tick waits once again", clock.n, waits)
        clock.n = 0
        with one_pass():
            with read_fails(PermissionError(13, "locked (test)"), n=999):
                runs._state_read(state)
            runs._state_read(state)           # readable again: the lock is over
            with read_fails(PermissionError(13, "locked (test)"), n=999):
                runs._state_read(state)
        check("a lock that ends and comes back in one pass is waited out again", clock.n, 2 * waits)

        e, notes, st = base.engine()
        clock.n = 0
        with read_fails(PermissionError(13, "locked (test)"), n=9999):
            base.book(e, base.ABORT, ok=False)
            handle._flush_pending(e)
        check("one booking and one tick with the file locked: LOCK_WAITS waited once each",
              clock.n, 2 * waits)

    def item11():
        clock = runs.time = Sleeps()
        try:
            got = (runs._state_read(None), runs._state_get(None, runs.HELD_28), runs._seen(None, "#6"),
                   runs.held_stuck(None), runs._state_set(None, "#7-miss", 1))
        except TypeError as exc:
            got = f"TypeError: {exc}"
        check("no state folder: unreadable, nothing raised", got, (None, None, None, None, False))
        check("…without waiting", clock.n, 0)

    def item12():
        st = tmpdir() / "state"
        st.mkdir()
        store = statestore.StateStore(st)
        left = [2]

        def _locked_twice(path, text):
            if left[0] and Path(path).name == statestore.FILE:
                left[0] -= 1
                raise PermissionError(13, "state.json being scanned (test)")
            return REAL_SS_WRITE(path, text)

        statestore.atomic_write_text = _locked_twice
        try:
            with ss_no_waits():
                store.set("marks", f"alerted:{DAY}", ["k"])
            wrote = json.loads((st / statestore.FILE).read_text(encoding="utf-8"))["marks"].get(f"alerted:{DAY}")
        except OSError as exc:
            wrote = f"{type(exc).__name__}: {exc}"
        finally:
            statestore.atomic_write_text = REAL_SS_WRITE
        check("state.json locked twice, then let through: the day mark is written", wrote, ["k"])

    def item12b():
        st = tmpdir() / "state"
        st.mkdir()
        statestore.StateStore(st).set("marks", f"alerted:{DAY}", ["k"])
        good = (st / statestore.FILE).read_text(encoding="utf-8")

        def _read(path, *a, **kw):
            if path.name == statestore.FILE:
                raise PermissionError(13, "state.json being scanned (test)")
            return REAL_READ_TEXT(path, *a, **kw)

        Path.read_text = _read
        try:
            with ss_no_waits():
                statestore.StateStore(st).set("marks", f"alerted:{DAY}", ["k", "k2"])
            raised = ""
        except OSError as exc:
            raised = type(exc).__name__
        finally:
            Path.read_text = REAL_READ_TEXT
        check("a write whose read stays locked raises, never writing the empty fallback over it",
              (raised, (st / statestore.FILE).read_text(encoding="utf-8")), ("PermissionError", good))

    def item12c():
        e, notes, state = base.engine()
        base.book(e, base.ABORT, ok=False)
        real_mark = e._mark_alerted

        def _mark(day, key):
            raise PermissionError(13, "state.json locked (test)")

        e._mark_alerted = _mark
        try:
            base.book(e, base.RETRY, ok=True)
        finally:
            e._mark_alerted = real_mark
        handle._flush_pending(e)
        base.show(notes)
        check("every day mark refused: one group message for the abort and the retry", len(base.group(notes)), 1)
        check("…no 「上机核对没过：#28」 of its own", base.mc28_pushes(notes), [])
        check("…not kept to be sent again", e._unsent_unresolved, [])
        check("no ERROR saying the 「没证据」 alarm did not go out", [x for x in ERRORS.lines if "没能推到群里" in x], [])
        said = [x for x in ERRORS.lines if "没记" in x]
        check("one ERROR saying the alarm went out and its mark did not land",
              (len(said), bool(said) and "已进群" in said[0]), (1, True))
        check("nothing of #28 is left waiting", base.held_28(state), {})

    def item12d():
        e, notes, state = base.engine()
        base.book(e, base.ABORT, ok=False)
        mark = f"{pushes.UNVERIFIED_KIND}|"

        def _locked(path, text):
            # state.json held by a scan from the 「没证据」 day mark on: that write and every
            # later one of the booking are refused.
            if Path(path).name == statestore.FILE and mark in text:
                raise PermissionError(13, "state.json being scanned (test)")
            return REAL_SS_WRITE(path, text)

        statestore.atomic_write_text = _locked
        try:
            with ss_no_waits():
                base.book(e, base.RETRY, ok=True)
        finally:
            statestore.atomic_write_text = REAL_SS_WRITE
        handle._flush_pending(e)
        base.show(notes)
        check("state.json refused the mark: one group message for the abort and the retry", len(base.group(notes)), 1)
        check("…no 「上机核对没过：#28」 of its own", base.mc28_pushes(notes), [])
        check("no ERROR saying the 「没证据」 alarm did not go out", [x for x in ERRORS.lines if "没能推到群里" in x], [])
        said = [x for x in ERRORS.lines if "没记" in x]
        check("one ERROR for the lock: the alarm went out, its mark did not land",
              (len(said), bool(said) and "已进群" in said[0]), (1, True))
        check("the mark not on file is not answered from memory either",
              any(str(k).startswith(mark) for k in e.state.store.get("marks", f"alerted:{DAY}") or []), False)

    def item13():
        e, notes, state = base.engine()
        (state / runs.SEEN_FILE).write_text(json.dumps({"#6": []}), encoding="utf-8")
        check("read once while it can be read: nothing held", runs._state_get(state, runs.HELD_28), None)
        cover = "已由「没证据」报警带上"
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
            base.book(e, base.RETRY, ok=True)       # a 「没证据」 run, nothing held
            handle._flush_pending(e)
        check("the 「没证据」 alarm reaches the group once", len(base.group(notes)), 1)
        check("locked, the last good read held nothing: no ERROR about the #28 cover",
              [x for x in ERRORS.lines if cover in x], [])
        check("…the write the booking could not make is still one ERROR",
              len([x for x in ERRORS.lines if runs.SEEN_FILE in x]), 1)
        ERRORS.lines.clear()
        state = fresh(R1)                     # never read in this process: what is held is unknown
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
            runs.covered_28(state, "MaaEnd", DAY, ["装备制造"])
        check("locked, never read: the cover not written is still an ERROR",
              len([x for x in ERRORS.lines if cover in x]), 1)
        ERRORS.lines.clear()
        state = fresh(R1)
        check("read once: R1 held", list(runs._state_get(state, runs.HELD_28) or {}), [R1])
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
            runs.covered_28(state, "MaaEnd", DAY, ["装备制造"])
        check("locked while a FAIL was held: the cover not written is still an ERROR",
              len([x for x in ERRORS.lines if cover in x]), 1)

    for title, fn in (("1: covered_28 when its read fails once", item1),
                      ("2: a held run's FAIL pushed at once is marked sent only after its push", item2),
                      ("3: machinecheck.json locked while judging", item3),
                      ("4: a machinecheck-runs.json that stays broken", item4),
                      ("4b: held FAILs stuck behind a machinecheck-runs.json that stays locked", item4b),
                      ("5: a brief Windows lock on os.replace", item5),
                      ("6: #7 / #28 miss counts in one read and write", item6),
                      ("7: #6 / #24a when the seen list cannot be read", item7),
                      ("8: 「没证据」 sent, then its record's mark cannot be written", item8),
                      ("9: locked while nothing is held: no ERROR", item9),
                      ("10: a lock is waited out once per booking or tick", item10),
                      ("11: no state folder", item11),
                      ("12: state.json locked a moment while an alarm's day mark is written", item12),
                      ("12b: state.json locked while a write reads it first", item12b),
                      ("12c: 「没证据」 sent, then no day mark can be written", item12c),
                      ("12d: 「没证据」 sent, then state.json refuses its day mark", item12d),
                      ("13: covered_28 locked while nothing is held: no ERROR", item13)):
        section(title, fn)



def _part_mc28_task_trail():  # noqa: C901
    """Machine check #28 judged from MaaEnd's own steps, not from the desktop picture."""
    import gzip
    import json
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="", ARK_LOG_FILE=str(TMP / "relay.log"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.features import machinecheck as mc
    from ark_relay.features import collector_maaend, collector_maaend as maaend_fwlog
    from types import SimpleNamespace

    from ark_relay.core import ledger as core
    from ark_relay.core import ledger as ledger_rows
    from ark_relay.features import handle, handle as pushes
    from ark_relay.features import machinechecks as runs

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-task-trail"
    SHOT_TIMES = {k: v for k, v in json.loads((FIX / "shot-times.json").read_text(encoding="utf-8")).items()
                  if not k.startswith("_")}

    class N:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body, alert))
            return []

        def send_group(self, title, body=""):
            return self.send(title, body, alert=True)

    mc.load()
    NOW = datetime(2026, 10, 16, 21, 40, tzinfo=SERVER_TZ)

    def maaend(*names, edit=None):
        """A MaaEnd folder whose debug/ holds the named fixture logs, unpacked."""
        d = tmpdir()
        (d / "debug").mkdir()
        for name in names:
            text = gzip.decompress((FIX / name).read_bytes()).decode("utf-8")
            if edit:
                text = edit(text)
            (d / "debug" / name.removesuffix(".gz")).write_bytes(text.encode("utf-8"))
        return d

    def shots(state, prefix):
        """The pictures of one run under state/shots/, with the times they were really taken."""
        files = {}
        for rel, taken in SHOT_TIMES.items():
            if not rel.startswith(prefix):
                continue
            p = state / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"png")
            t = datetime.strptime(taken, "%Y-%m-%d %H:%M:%S").timestamp()
            os.utime(p, (t, t))
            files[rel.rsplit("-", 1)[-1].removesuffix(".png")] = rel
        return files

    class Ledger:
        """The ledger rows handle._book leaves for the next run: what
    records._trail_miss_streak and #28's 「another run did it」 read."""
        def __init__(self):
            self.rows = []

        def read_ledger(self, day):
            return [r for r in self.rows if r["started"][:10] == day]

    def judge(log, end_dir, state=None, files=None, ledger=None, later=0, book=True):
        """#28 on one fixture run, booked the way handle._book books it (records.
    _mark_task_trails, which #28 then reads) unless `book` is False. `ledger` holds the
    day's earlier rows and gets this run's row after; `later` moves the run's start by
    that many minutes, so the same log can stand for runs in a row."""
        path = log if isinstance(log, Path) else FIX / log
        text = path.read_text(encoding="utf-8")
        raw = collector_maaend.parse_maaend_log(path)
        if files:
            raw["tasks_shot_files"] = files
        day, run = path.name.removesuffix(".log").split("_")
        started = (datetime.strptime(f"{day} {run[7:]}", "%Y-%m-%d %H-%M-%S").replace(tzinfo=SERVER_TZ)
                   + timedelta(minutes=later))
        rec = RunRecord(run_id=f"{day}/endfield/{run}" + (f"+{later}" if later else ""), script="MaaEnd",
                        user="endfield", started=started, finished=started + timedelta(hours=1), ok=True,
                        failed_tasks=[], raw=raw, log_path=path)
        ledger = ledger if ledger is not None else Ledger()
        if book:
            handle._mark_task_trails(SimpleNamespace(cfg=SimpleNamespace(maaend_dir=str(end_dir)), state=ledger), rec)
        n = N()
        got = dict(mc.judge(state or tmpdir(), "run", {"rec": rec, "raw": raw, "log_text": text,
                                                       "maaend_dir": str(end_dir),
                                                       "ledger": ledger.read_ledger(day)}, notifier=n, now=NOW))
        ledger.rows.append({"run_id": rec.run_id, "script": "MaaEnd", "started": started.isoformat(),
                            "ok": True, "raw": raw})
        r = got.get("#28")
        pushed = [t for t, _, a in n.sent if a and t.startswith(texts.machinecheck_failed("#28", ""))]
        if r is not None:
            print(f"    #28 {r.status}: {r.evidence}")
            check("…the line reads as plain Chinese", texts.plain(r.evidence), [])
        return (r.status if r else None), (r.evidence if r else ""), pushed

    print("\n[10-08 06-31-06：装备制造查画面没过，终末地自己停了整条任务链；截图文件在 → 以前算它做成了]")
    state = tmpdir()
    st, ev, pushed = judge("2026-10-08_MaaEnd-06-31-06.log", maaend("maafw-2026-10-08.log.gz"), state,
                           shots(state, "shots/2026-10-08/MaaEnd-10-32-23/"))
    check("MaaEnd aborted its own chain after the scene check: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("evidence says MaaEnd stopped itself and quotes its own reason",
          ev.startswith("装备制造（10:34:11→10:34:16）终末地自己检查画面没过，把后面的任务全停了，这一项没做成，"
                        "它记的原因：左上角的账号编号显示不全，它说开着隐藏账号编号的模组会挡住左上方的字，认不出画面"), True)
    check("…and blames no scheduler", "调度程序" in ev, False)
    check("the gift before it counts as done, one 「赠送」 click",
          "做成的：赠送干员礼物（10:32:23→10:34:11）点了「赠送」1 次" in ev, True)
    # Without MaaEnd's abort step (its two lines taken out) the gear task only ran its
    # entry and the scene check: still a FAIL, said as no step that did the job.
    no_abort = maaend("maafw-2026-10-08.log.gz", edit=lambda t: "".join(
        x for x in t.splitlines(keepends=True) if '"name":"__SceneCheckAbortPipeline"' not in x))
    st, ev, pushed = judge("2026-10-08_MaaEnd-06-31-06.log", no_abort)
    check("no abort step: 装备制造 that only ran its entry is a FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("evidence names the task and its window", ev.startswith("装备制造（10:34:11→10:34:16）终末地自己的记录里只走了"), True)

    print("\n[10-08：同一天前一趟已经做成了装备制造，06-31-06 这趟终末地自己停了 → 不进群，日报里留原因]")
    day08, fw08 = Ledger(), maaend("maafw-2026-10-08.log.gz")
    st, _, pushed = judge("2026-10-08_MaaEnd-05-29-15.log", fw08, ledger=day08)
    check("05-29-15 crafted (09:33): PASS", (st, pushed), ("PASS", []))
    heal_state = tmpdir() / "state"   # techlog writes next to it, in ../tech
    heal_state.mkdir()
    st, ev, pushed = judge("2026-10-08_MaaEnd-06-31-06.log", fw08, heal_state, ledger=day08)
    check("06-31-06's abort is healed by that run: no FAIL, nothing pushed", (st, pushed), ("PASS", []))
    from ark_relay.core import statestore as techlog
    reds = techlog.unhandled("\n".join(f.read_text(encoding="utf-8")
                                       for f in techlog.tech_dir(heal_state).glob("*.md")))
    check("…but one 「自愈待查」 red item says a session has to look at why it stopped itself",
          [t.split("：")[:2] for _, t in reds], [["自愈待查", "上机核对 #28 2026-10-08/endfield/MaaEnd-06-31-06 装备制造"]])
    check("…its line keeps MaaEnd's reason and names the run that did it",
          "装备制造（10:34:11→10:34:16）终末地自己检查画面没过，把后面的任务全停了，这一项没做成，"
          "它记的原因：左上角的账号编号显示不全" in ev and "；同一天 05:29（东京 06:29）开始的那趟已经做成了，不用人管" in ev, True)
    section = mc.daily_section(heal_state)
    line28 = next((x for x in section.splitlines() if " #28 " in x), "")
    check("the daily section says #28 failed this run and another run made up for it, not just 「过了」",
          (line28.startswith("↻ #28 "), "这一趟没过，同一天另一趟补上了" in line28, "账号编号显示不全" in line28),
          (True, True, True))
    check("…in plain Chinese", texts.plain(line28), [])
    judge("2026-10-08_MaaEnd-06-34-21.log", maaend("maafw-2026-10-08.log.gz"), heal_state)
    check("a plain PASS later that day does not wipe it from the day's section",
          next((x for x in mc.daily_section(heal_state).splitlines() if " #28 " in x), "") == line28, True)
    row = day08.rows[-1]
    notes = ledger_rows._rows_for(row, datetime(2026, 10, 8, 10, 35, tzinfo=SERVER_TZ))[4]
    check("the daily report's row of 06-31-06 keeps the abort and its reason",
          any(n.startswith(ledger_rows.UNVERIFIED + "：装备制造（终末地自己检查画面没过") and "账号编号显示不全" in n
              for n in notes), True)
    check("…and no 「没证据」 item is left for the day: the earlier run backs it",
          dict(core.day_unverified_items(day08.rows)).get("MaaEnd"), None)
    check("a run of the day without the booked verdicts backs nothing",
          runs._done_elsewhere({"rec": None, "ledger": [dict(day08.rows[0], raw={})]}, "装备制造"), "")

    print("\n[10-08 日报：06-31-06 没做的那些，10:35 那趟重试按项说：选剑演武没证据，其余做成了]")
    judge("2026-10-08_MaaEnd-06-34-21.log", fw08, ledger=day08)
    FAILED_0631 = ["拜访好友", "基建任务", "信用点购物", "转交委托", "据点交易", "环境监测", "自动囤货", "售卖弹性物资",
                   "购买稳定物资", "协议空间", "选剑演武", "自动采集", "日常奖励领取"]
    aborted = dict(day08.rows[1], ok=False, failed_tasks=FAILED_0631)
    check("06-31-06 is the aborted run", aborted["run_id"].endswith("06-31-06"), True)
    later = day08.rows[-1]["raw"]
    check("in 06-34-21 only 选剑演武 lacks evidence among them, none is left unjudged",
          ([t for t in ledger_rows.maaend_unverified(later) if t in aborted["failed_tasks"]],
           ledger_rows.maaend_unjudged(later)), (["选剑演武"], []))
    note = core.retried_notes([day08.rows[0], aborted, day08.rows[-1]]).get(aborted["run_id"], "")
    print(f"    {note}")
    rest = sorted(t for t in aborted["failed_tasks"] if t != "选剑演武")
    check("the retry note says 做成了 for the twelve and 没证据 for 选剑演武 alone",
          note.endswith("开始的那趟重试里：" + "、".join(rest) + " 做成了；选剑演武 程序说做完了，但没证据，不算完成"), True)
    check("…in plain Chinese", texts.plain(note), [])
    unread_later = dict(day08.rows[-1], raw=dict(later, tasks_trail_miss=1, tasks_trail={
        t: dict(v, found=False, unread=True, ok=False) for t, v in later["tasks_trail"].items()}))
    note = core.retried_notes([aborted, unread_later]).get(aborted["run_id"], "")
    check("a retry whose own record was not read: those two 先不判, not 做成了",
          "环境监测、转交委托 终末地自己的记录没读到，先不判" in note and "选剑演武 程序说做完了" in note, True)
    all_backed = dict(day08.rows[-1], raw=dict(later, tasks_evidence=dict(later.get("tasks_evidence") or {}, 选剑演武=["x"])))
    check("all backed: one wording for the whole list, as before",
          core.retried_notes([aborted, all_backed]).get(aborted["run_id"], "").endswith("开始的那趟重试里做成了"), True)

    print("\n[10-08 05-29-15：四个任务都做成了；截图是结束后 5-6 秒拍的]")
    state = tmpdir()
    st, ev, pushed = judge("2026-10-08_MaaEnd-05-29-15.log", maaend("maafw-2026-10-08.log.gz"), state,
                           shots(state, "shots/2026-10-08/MaaEnd-09-30-35/"))
    check("PASS, nothing pushed", (st, pushed), ("PASS", []))
    for said in ("赠送干员礼物（09:30:36→09:33:02）点了「赠送」1 次", "装备制造（09:33:03→09:33:22）点了「制作」1 次",
                 "转交委托（09:37:39→09:39:28）确认转交了 5 单", "环境监测（09:40:57→09:44:14）接了委托、拍了监测照片"):
        check(f"evidence: {said}", said in ev, True)
    check("the gift picture is said to be taken 5 s after the task ended, next task already running",
          "shots/2026-10-08/MaaEnd-09-30-35 里 093302 那张 是它结束后 5 秒才拍到的，那时下一个任务已经开始" in ev, True)

    print("\n[10-08 06-34-21 重跑：转交委托、环境监测都没东西可做，是正常结束]")
    st, ev, pushed = judge("2026-10-08_MaaEnd-06-34-21.log", maaend("maafw-2026-10-08.log.gz"))
    check("PASS, nothing pushed", (st, pushed), ("PASS", []))
    check("evidence says nothing was there to transfer / photograph",
          "转交委托（10:37:01→10:37:28）两个地区都走了一遍，没有可转交的委托" in ev
          and "环境监测（10:38:44→10:38:50）两个监测终端都看过了，没有可接的委托" in ev, True)

    print("\n[10-13 05-36-57：送礼 1 次、制作 1 次、转交 5 单、环境监测没委托]")
    st, ev, pushed = judge("2026-10-13_MaaEnd-05-36-57.log", maaend("maafw-2026-10-13.log.gz"))
    check("PASS, nothing pushed", (st, pushed), ("PASS", []))
    check("evidence has all four", all(x in ev for x in ("点了「赠送」1 次", "点了「制作」1 次", "确认转交了 5 单",
                                                         "两个监测终端都看过了")), True)

    print("\n[10-16 09-53-33：四个任务的记录分在三个轮换下来的框架日志里]")
    ROT = ("maafw.bak.2026.10.16-13.57.50.72.log.gz", "maafw.bak.2026.10.16-14.00.46.901.log.gz",
           "maafw.bak.2026.10.16-14.04.13.468.log.gz")
    state = tmpdir()
    st, ev, pushed = judge("2026-10-16_MaaEnd-09-53-33.log", maaend(*ROT), state,
                           shots(state, "shots/2026-10-16/"))
    check("PASS, nothing pushed", (st, pushed), ("PASS", []))
    check("delivery found in the file rotated at 14:00:46.901, the moment it ended",
          "转交委托（13:58:58→14:00:46）确认转交了 5 单" in ev, True)
    check("the gift picture (taken 13:57:24, task ended 13:57:17.705) is 6 s late",
          "135717 那张 是它结束后 6 秒才拍到的" in ev, True)

    print("\n[终末地自己记成失败的任务：判不过]")
    failed_env = maaend(*ROT, edit=lambda t: t.replace(
        '[msg=Tasker.Task.Succeeded] [details={"entry":"EnvironmentMonitoringMain"',
        '[msg=Tasker.Task.Failed] [details={"entry":"EnvironmentMonitoringMain"'))
    st, ev, pushed = judge("2026-10-16_MaaEnd-09-53-33.log", failed_env)
    check("environment monitoring booked Failed by MaaFW: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("evidence says so", "环境监测（14:02:04→14:02:11）终末地自己记的结果是失败" in ev, True)

    print("\n[没有框架日志：第一趟不判（#28 和账本都不报），连续两趟判不过（两边都报）]")
    import logging

    class Levels(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.got = []

        def emit(self, record):
            self.got.append((record.levelno, record.getMessage()))

    FOUR = ["赠送干员礼物", "装备制造", "转交委托", "环境监测"]
    state, empty, book = tmpdir(), tmpdir(), Ledger()
    from ark_relay.features import handle as records

    levels, hlog = Levels(), records.log
    old_level = hlog.level
    hlog.addHandler(levels)
    hlog.setLevel(logging.DEBUG)
    st, _, pushed = judge("2026-10-13_MaaEnd-05-36-57.log", empty, state, ledger=book)
    hlog.removeHandler(levels)
    hlog.setLevel(old_level)
    first = book.rows[-1]["raw"]
    check("first run without MaaFW's log: #28 not judged, nothing pushed", (st, pushed), (None, []))
    check("…booked as the first miss in a row", first.get("tasks_trail_miss"), 1)
    check("…the ledger leaves the four unjudged, not unbacked",
          (ledger_rows.maaend_unverified(first), ledger_rows.maaend_unjudged(first)), ([], FOUR))
    check("…so the day has no 「没证据」 item to push (pushes._push_unverified)",
          dict(core.day_unverified_items(book.rows)).get("MaaEnd"), None)
    check("…said at INFO, nothing at WARNING or above (errwatch would push that to the group)",
          ([m for lv, m in levels.got if lv >= logging.WARNING],
           any(lv == logging.INFO and "连续第 1 趟" in m and "先不判" in m for lv, m in levels.got)), ([], True))
    notes = ledger_rows._rows_for(book.rows[-1], datetime(2026, 10, 13, 10, 0, tzinfo=SERVER_TZ))[4]
    check("…and the daily report says the record was not read, and that the four are not counted done",
          (any(n.startswith("终末地自己的记录这一趟没读到（连续第 1 趟），赠送干员礼物、装备制造、转交委托、环境监测 先不判")
               for n in notes), any("赠送干员礼物" in n for n in notes if n.startswith("做了"))), (True, False))
    check("…in plain Chinese", texts.plain(" ".join(notes)), [])
    st, ev, pushed = judge("2026-10-13_MaaEnd-05-36-57.log", empty, state, ledger=book, later=60)
    second = book.rows[-1]["raw"]
    check("second in a row: #28 FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("…saying the four cannot be seen", ev.startswith("连续 2 趟"), True)
    check("…and the ledger now calls them unbacked, so 「没证据」 goes to the group too",
          (second.get("tasks_trail_miss"), ledger_rows.maaend_unverified(second),
           dict(core.day_unverified_items(book.rows[-1:])).get("MaaEnd")), (2, FOUR, FOUR))
    st, _, _ = judge("2026-10-13_MaaEnd-05-36-57.log", maaend("maafw-2026-10-13.log.gz"), state, ledger=book,
                     later=120)
    check("with the log again: judged again, the streak starts over",
          (st, book.rows[-1]["raw"].get("tasks_trail_miss")), ("PASS", 0))
    st, _, pushed = judge("2026-10-13_MaaEnd-05-36-57.log", empty, state, ledger=book, later=180)
    check("one miss after that: not judged again", (st, pushed, book.rows[-1]["raw"].get("tasks_trail_miss")),
          (None, [], 1))
    # A record #28 sees without the booked verdicts reads MaaFW's log itself, counting
    # misses in its own state.
    state = tmpdir()
    st, _, _ = judge("2026-10-13_MaaEnd-05-36-57.log", empty, state, book=False)
    st2, _, pushed = judge("2026-10-13_MaaEnd-05-36-57.log", empty, state, book=False)
    check("not booked: the same wait, read by #28 itself", (st, st2, len(pushed)), (None, "FAIL", 1))
    st, _, _ = judge("2026-10-13_MaaEnd-05-36-57.log", maaend("maafw-2026-10-13.log.gz"), state, book=False)
    check("…and judged from the log when it is there", st, "PASS")

    print("\n[框架日志在一趟里面换了文件、前一段没了：没盖到的任务先不判，盖到的照判]")
    SPLIT = "[2026-10-08 09:38:30"

    def split_1008(*parts, edit=None):
        text = gzip.decompress((FIX / "maafw-2026-10-08.log.gz").read_bytes()).decode("utf-8")
        if edit:
            text = edit(text)
        lines = text.splitlines(keepends=True)
        files = {"bak": "".join(x for x in lines if x[:20] < SPLIT), "cur": "".join(x for x in lines if x[:20] >= SPLIT)}
        names = {"bak": "maafw.bak.2026.10.08-09.38.30.012.log", "cur": "maafw.log"}
        d = tmpdir()
        (d / "debug").mkdir()
        for part in parts:
            (d / "debug" / names[part]).write_text(files[part], encoding="utf-8")
        return d

    st, ev, pushed = judge("2026-10-08_MaaEnd-05-29-15.log", split_1008("bak", "cur"))
    check("both parts: the split alone changes nothing, PASS", (st, pushed, "确认转交了 5 单" in ev), ("PASS", [], True))
    part, levels = Ledger(), Levels()
    hlog.addHandler(levels)
    hlog.setLevel(logging.DEBUG)
    st, ev, pushed = judge("2026-10-08_MaaEnd-05-29-15.log", split_1008("cur"), ledger=part)
    hlog.removeHandler(levels)
    hlog.setLevel(old_level)
    raw = part.rows[-1]["raw"]
    OLD3 = ["赠送干员礼物", "装备制造", "转交委托"]
    check("only maafw.log: the three tasks before it are unread, 环境监测 is found",
          ({t: (v["found"], v["unread"]) for t, v in raw["tasks_trail"].items()}, raw["tasks_trail_miss"]),
          ({"赠送干员礼物": (False, True), "装备制造": (False, True), "转交委托": (False, True),
            "环境监测": (True, False)}, 1))
    check("…转交委托 too, though maafw.log holds its later steps: the log starts inside it",
          maaend_fwlog.log_reaches(maaend_fwlog.task_events(split_1008("cur"), datetime(2026, 10, 8, 9, 37, 39),
                                                            datetime(2026, 10, 8, 9, 39, 28)),
                                   datetime(2026, 10, 8, 9, 37, 39)), False)
    check("#28 judges 环境监测 and waits for the three: PASS, nothing pushed",
          (st, pushed, ev.startswith("环境监测（09:40:57→09:44:14）接了委托"),
           ev.endswith("赠送干员礼物、装备制造、转交委托 这一趟终末地自己的记录没盖到，先不判")), ("PASS", [], True, True))
    check("…the ledger leaves the three unjudged, none unbacked, no 「没证据」 for the day",
          (ledger_rows.maaend_unjudged(raw), ledger_rows.maaend_unverified(raw),
           dict(core.day_unverified_items(part.rows)).get("MaaEnd")), (OLD3, [], None))
    check("…said at INFO with what the log lacks, nothing at WARNING or above",
          ([m for lv, m in levels.got if lv >= logging.WARNING],
           any(lv == logging.INFO and "赠送干员礼物、装备制造、转交委托 在终末地自己的记录里读不到" in m
               and "开始前 5 秒里一条记录也没有" in m and "连续第 1 趟" in m for lv, m in levels.got)), ([], True))
    notes = ledger_rows._rows_for(part.rows[-1], datetime(2026, 10, 8, 10, 31, tzinfo=SERVER_TZ))[4]
    check("…and the daily report row says the three 先不判", any(
        n.startswith("终末地自己的记录这一趟没读到（连续第 1 趟），赠送干员礼物、装备制造、转交委托 先不判") for n in notes), True)
    check("…in plain Chinese", texts.plain(" ".join([ev, *notes])), [])
    st, ev, pushed = judge("2026-10-08_MaaEnd-05-29-15.log", split_1008("cur"), ledger=part, later=60)
    raw = part.rows[-1]["raw"]
    check("the same again the next run: #28 FAIL, pushed, naming only the three",
          (st, len(pushed), all(f"{t}（" in ev for t in OLD3), "环境监测（09:40:57→09:44:14）接了委托" in ev.split("。做成的：")[-1]),
          ("FAIL", 1, True, True))
    check("…said as not read twice in a row", "转交委托（09:37:39→09:39:28）连续 2 趟在终末地自己的记录里读不到" in ev, True)
    check("…and the ledger now calls the three unbacked, with that reason",
          (raw["tasks_trail_miss"], ledger_rows.maaend_unverified(raw), ledger_rows.maaend_unbacked_why(raw, "装备制造")),
          (2, OLD3, "终末地自己的记录连续 2 趟没读到这一项"))
    # A log that reaches the task's start but holds no run of it: not a rotation, so no
    # wait - the gear task's start lines taken out of the whole, unsplit log.
    no_gear = split_1008("bak", "cur", edit=lambda t: "".join(
        x for x in t.splitlines(keepends=True)
        if not ("Tasker.Task.Starting" in x and '"entry":"GearAssemblyStart"' in x)))
    cov = Ledger()
    st, ev, pushed = judge("2026-10-08_MaaEnd-05-29-15.log", no_gear, ledger=cov)
    check("the log covers 装备制造's start but has no run of it: FAIL and pushed at once, no wait",
          (st, len(pushed), ev.startswith("装备制造（09:33:03→09:33:22）在终末地自己的记录里找不到"),
           cov.rows[-1]["raw"]["tasks_trail_miss"], ledger_rows.maaend_unverified(cov.rows[-1]["raw"])),
          ("FAIL", 1, True, 0, ["装备制造"]))

    print("\n[读法：两个进程各记一遍的事件只算一次；子任务里的步骤算在发起它的任务上]")
    end = maaend("maafw-2026-10-08.log.gz")
    t0, t1 = datetime(2026, 10, 8, 9, 40, 57), datetime(2026, 10, 8, 9, 44, 14)
    events = maaend_fwlog.task_events(end, t0, t1)
    trail = maaend_fwlog.task_trail(events, "EnvironmentMonitoringMain", t0, t1)
    check("10-08 environment monitoring: Succeeded at 09:44:14.463",
          (trail["result"], f"{trail['ended']:%H:%M:%S.%f}"[:12]), ("Succeeded", "09:44:14.463"))
    check("the photo job ran as its own sub-task and is counted (AcceptEternalSunset once)",
          trail["nodes"].get("AcceptEternalSunset"), 1)
    g0, g1 = datetime(2026, 10, 8, 9, 30, 36), datetime(2026, 10, 8, 9, 33, 2)
    gift = maaend_fwlog.task_trail(maaend_fwlog.task_events(end, g0, g1), "GiftOperatorMain", g0, g1)
    check("both processes log every step; ConfirmGift (hit once, 09:30-09:33) counted 1 time, not 2",
          gift["nodes"].get("GiftOperatorConfirmGift"), 1)
    c0, c1 = datetime(2026, 10, 13, 9, 38, 17), datetime(2026, 10, 13, 9, 41, 36)
    gift13 = maaend_fwlog.task_trail(maaend_fwlog.task_events(maaend("maafw-2026-10-13.log.gz"), c0, c1),
                                     "GiftOperatorMain", c0, c1)
    check("10-13: a step is the node that was hit - ConfirmGift clicked once, its two dialog skips and "
          "the leave after it are their own steps (not 3 ConfirmGift)",
          (gift13["nodes"].get("GiftOperatorConfirmGift"), gift13["nodes"].get("GiftOperatorGiftDialog"),
           gift13["nodes"].get("GiftOperatorLeave")), (1, 2, 1))
    k0, k1 = datetime(2026, 10, 8, 10, 34, 11), datetime(2026, 10, 8, 10, 34, 16)
    gear = maaend_fwlog.task_trail(maaend_fwlog.task_events(end, k0, k1), "GearAssemblyStart", k0, k1)
    check("10-08 10:34 gear: MaaFW books it Succeeded, its trail holds MaaEnd's abort step once",
          (gear["result"], gear["nodes"].get("__SceneCheckAbortPipeline")), ("Succeeded", 1))
    no_end = maaend("maafw-2026-10-08.log.gz", edit=lambda t: "".join(
        x for x in t.splitlines(keepends=True)
        if not ("Tasker.Task.Succeeded" in x and '"entry":"GiftOperatorMain"' in x)))
    g1end = datetime(2026, 10, 8, 9, 33, 22)
    events = maaend_fwlog.task_events(no_end, g0, g1end)
    gift = maaend_fwlog.task_trail(events, "GiftOperatorMain", g0, g1)
    check("a gift run with no end event stops at its window: 装备制造's steps are not counted in it",
          (gift["ended"], gift["nodes"].get("GiftOperatorConfirmGift"), "GearAssemblyClickProduceBtn" in gift["nodes"]),
          (None, 1, False))

    print("\n[StopTask 这种节点照样记一步、任务记成功（10-16 13:58:58 信用点商店）]")
    c0, c1 = datetime(2026, 10, 16, 13, 58, 50), datetime(2026, 10, 16, 13, 58, 59)
    events = maaend_fwlog.task_events(maaend(*ROT), c0, c1)
    stop = [(w, d) for w, msg, d in events if msg == "Node.PipelineNode.Succeeded"
            and (d.get("node_details") or {}).get("name") == "CreditShoppingBuyItemStop"]
    check("the StopTask node has its Node.PipelineNode.Succeeded line, action StopTask",
          [(f"{w:%H:%M:%S.%f}"[:12], (d.get("action_details") or {}).get("action")) for w, d in stop][:1],
          [("13:58:58.769", "StopTask")])
    check("…and its task (CreditShoppingMain) is booked Succeeded at that instant",
          [f"{w:%H:%M:%S.%f}"[:12] for w, msg, d in events
           if msg == "Tasker.Task.Succeeded" and d.get("entry") == "CreditShoppingMain"][:1], ["13:58:58.769"])

    GEAR_TASK, GIFT_TASK = 200000002, 200000001

    def fw_step(at, task_id, node_id, name, parent):
        details = {"action_details": {"action": "DoNothing", "action_id": node_id + 200000000, "box": [0, 0, 0, 0],
                                      "detail": {}, "name": name, "success": True},
                   "focus": None, "name": parent,
                   "node_details": {"action_id": node_id + 200000000, "completed": True, "name": name,
                                    "node_id": node_id, "reco_id": node_id + 100000000},
                   "node_id": node_id, "task_id": task_id}
        return (f"[2026-10-13 {at}][INF][Px19280][Tx5463][Utils/EventDispatcher.hpp][L65]"
                f"[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] "
                f"[msg=Node.PipelineNode.Succeeded] [details={json.dumps(details, separators=(',', ':'))}] \n")

    def splice(drop_nodes, steps):
        """An edit for maaend(): the real 10-13 lines without the steps whose node_id is in
    `drop_nodes` (both processes' copies), plus `steps` [(time, task_id, name, parent)]."""
        def edit(text):
            keep = [x for x in text.splitlines(keepends=True)
                    if not any(f'"node_id":{n},' in x for n in drop_nodes)]
            return "".join(keep) + "".join(fw_step(at, task, 390000000 + i, name, parent)
                                           for i, (at, task, name, parent) in enumerate(steps))
        return edit

    def run_1013(edit):
        return judge("2026-10-13_MaaEnd-05-36-57.log", maaend("maafw-2026-10-13.log.gz", edit=edit))

    REWARD = (300000427, 300000436, 300000441)
    print("\n[装备制造：点了「制作」后背包已满（GearAssemblyCheckMaterialEnough），是没东西可做，不是做成了]")
    st, ev, pushed = run_1013(splice(REWARD, [
        ("09:41:46.900", GEAR_TASK, "GearAssemblyCheckMaterialEnough", "GearAssemblyClickProduceBtn")]))
    check("bag full: PASS (a normal end), nothing pushed", (st, pushed), ("PASS", []))
    check("evidence reads as the nothing-to-do end", "装备制造（09:41:36→09:41:55）背包已满，做不出来，算没东西可做" in ev, True)
    check("…not as 「点了「制作」1 次」", "点了「制作」" in ev, False)

    print("\n[装备制造：列表翻到底都做不了（GearAssemblyCheckFailedAndFinish）]")
    st, ev, pushed = run_1013(splice((300000426, *REWARD), [
        ("09:41:46.300", GEAR_TASK, "GearAssemblyCheckFailedAndContinue", "GearAssemblySelectFirstGear"),
        ("09:41:46.600", GEAR_TASK, "GearAssemblyGearListScrollEnd", "GearAssemblyCheckFailedAndContinue"),
        ("09:41:46.900", GEAR_TASK, "GearAssemblyCheckFailedAndFinish", "GearAssemblyGearListScrollEnd")]))
    check("nothing craftable: PASS, nothing pushed", (st, pushed), ("PASS", []))
    check("evidence names both causes the step recognises (NotEnough or NotUnlocked)",
          "装备制造（09:41:36→09:41:55）装备列表翻到底，没有能做的（材料不够或没解锁），算没东西可做" in ev, True)

    GIFT_AFTER_UI = (300000358, 300000361, 300000363, 300000366, 300000367, 300000368)

    def chain(t, pairs, step=0.08):
        """[(time, gift task, name, parent)] from second `t` of 09:41, `step` apart; and the next second."""
        out = []
        for name, parent in pairs:
            out.append((f"09:41:{t:06.3f}", GIFT_TASK, name, parent))
            t += step
        return out, t

    FULL = (("GiftOperatorGiftFull", "GiftOperatorGiftUI"),
            ("GiftOperatorGiftFullLeave", "GiftOperatorGiftFull"),
            ("GiftOperatorGiftFullBackInWorld", "GiftOperatorGiftFullLeave"))
    RETRY = (("GiftOperatorGiftFullRetry", "GiftOperatorGiftFullBackInWorld"),
             ("GiftOperatorEntry", "GiftOperatorGiftFullRetry"),
             ("GiftOperatorGiftUI", "GiftOperatorBranchGift"))

    print("\n[送礼：一个干员送满、换人后送出去了 → 还是做成了]")
    steps, _ = chain(29.5, FULL + RETRY, step=0.12)
    st, ev, pushed = run_1013(splice((), steps))
    check("one full operator, then the real ConfirmGift: PASS, said as the gift sent",
          (st, "赠送干员礼物（09:38:17→09:41:36）点了「赠送」1 次" in ev), ("PASS", True))

    print("\n[送礼：连换 5 次干员都送满了（GiftOperatorGiftFullFail）→ 没东西可做]")
    steps, t = chain(30.0, FULL)
    for _ in range(5):
        more, t = chain(t, RETRY + FULL)
        steps += more
    more, t = chain(t, (("GiftOperatorGiftFullFail", "GiftOperatorGiftFullBackInWorld"),))
    steps += more
    check("the synthetic chain ends before the task's end event (09:41:36.138)", t < 36.1, True)
    st, ev, pushed = run_1013(splice(GIFT_AFTER_UI, steps))
    check("all full: PASS (normal end), nothing pushed", (st, pushed), ("PASS", []))
    check("evidence reads as the nothing-to-do end",
          "赠送干员礼物（09:38:17→09:41:36）连换 5 次干员，礼物都已送满，算没东西可做" in ev, True)
    booked_failed = splice(GIFT_AFTER_UI, steps)
    st, ev, pushed = run_1013(lambda text: booked_failed(text).replace(
        '[msg=Tasker.Task.Succeeded] [details={"entry":"GiftOperatorMain"',
        '[msg=Tasker.Task.Failed] [details={"entry":"GiftOperatorMain"'))
    check("…the same when MaaFW books that stop as Failed", (st, "礼物都已送满，算没东西可做" in ev), ("PASS", True))

    print("\n[送礼：只碰到一次送满、后面什么也没有 → 不算没东西可做]")
    steps, _ = chain(30.0, FULL)
    st, ev, pushed = run_1013(splice(GIFT_AFTER_UI, steps))
    check("GiftFull alone is not an end (its next is the retry): FAIL, pushed", (st, len(pushed)), ("FAIL", 1))

    # ---- The ledger's 「没证据」 reads the same MaaFW judgment, not the picture ------------
    print("\n[账本：四个任务有没有证据看终末地自己的记录，桌面截图不算]")
    abort_log = FIX / "2026-10-08_MaaEnd-06-31-06.log"
    araw = collector_maaend.parse_maaend_log(abort_log)
    check("装备制造's only line, MaaEnd's scene-check note, is no evidence on its own (audit 11-08 B-07)",
          bool((araw.get("tasks_evidence") or {}).get("装备制造")), False)
    araw["tasks_shot"] = ["赠送干员礼物", "装备制造"]   # 103411 / 103416 in that bundle
    started = datetime(2026, 10, 8, 10, 32, 8, tzinfo=SERVER_TZ)
    arec = RunRecord(run_id="2026-10-08/endfield/MaaEnd-06-31-06", script="MaaEnd", user="endfield",
                     started=started, finished=started + timedelta(minutes=3), ok=True, failed_tasks=[],
                     raw=araw, log_path=abort_log)
    handle._mark_task_trails(SimpleNamespace(cfg=SimpleNamespace(maaend_dir=maaend("maafw-2026-10-08.log.gz"))), arec)
    trails = araw.get("tasks_trail") or {}
    check("booked: the gift did its job, the gear task did not",
          {t: v.get("ok") for t, v in trails.items()}, {"赠送干员礼物": True, "装备制造": False})
    check("the aborted gear task is unverified despite its picture and its log line",
          ledger_rows.maaend_unverified(araw), ["装备制造"])
    pics_only = {"tasks_done": ["赠送干员礼物", "装备制造", "转交委托", "环境监测"],
                 "tasks_evidence": {}, "tasks_shot": ["赠送干员礼物", "装备制造", "转交委托", "环境监测"],
                 "tasks_trail": {}}
    check("booked with the trail rule and nothing in MaaFW: a picture alone backs nothing",
          ledger_rows.maaend_unverified(pics_only), ["赠送干员礼物", "装备制造", "转交委托", "环境监测"])
    no_dir = RunRecord(run_id="x", script="MaaEnd", user="endfield", started=started,
                       finished=started + timedelta(minutes=3), ok=True, failed_tasks=[],
                       raw={"tasks_done": ["赠送干员礼物"]}, log_path=abort_log)
    handle._mark_task_trails(SimpleNamespace(cfg=SimpleNamespace(maaend_dir=None), state=Ledger()), no_dir)
    check("no MaaEnd folder configured: the gift is booked as not found, a first miss, so unjudged",
          ({t: v.get("found") for t, v in no_dir.raw.get("tasks_trail").items()}, no_dir.raw.get("tasks_trail_miss"),
           ledger_rows.maaend_unverified(no_dir.raw), ledger_rows.maaend_unjudged(no_dir.raw)),
          ({"赠送干员礼物": False}, 1, [], ["赠送干员礼物"]))

    print("\n[「没证据」的原因按项写：四个任务看终末地自己的记录，其余看日志里的回显]")
    judged = [{"script": "MaaEnd", "raw": {"tasks_trail": {"装备制造": {"found": True, "ok": False}}}},
              {"script": "MaaEnd", "raw": {"tasks_done": ["赠送干员礼物"]}}]

    def why(script, items):
        return pushes._unverified_why(script, items, judged)

    check("only tasks judged by their log line: that, MaaEnd's own record not named",
          (why("MaaEnd", ["基建任务"]), why("MaaEnd", ["赠送干员礼物"])), ("日志里没有游戏回显", "日志里没有游戏回显"))
    check("only tasks judged from MaaEnd's own record: that", why("MaaEnd", ["装备制造"]),
          "终末地自己的记录里看不到做成或没东西可做")
    check("both: each part names its tasks",
          why("MaaEnd", ["装备制造", "基建任务"]),
          "装备制造 在终末地自己的记录里看不到做成或没东西可做，基建任务 的日志里没有游戏回显")
    check("other games unchanged", why("MAA", ["剿灭"]), "日志里没有「剿灭模式 x/y」这行进度")
    check("all in plain Chinese",
          texts.plain(" ".join(why("MaaEnd", x) for x in (["基建任务"], ["装备制造"], ["装备制造", "基建任务"]))), [])

    print()
    print("\n[audit 11-08 B-07: a task with no end event does not take the next task's first nodes]")
    _t = datetime(2026, 11, 8, 10, 0, 0)
    _ev = [(_t, "Tasker.Task.Starting", {"entry": "GiftOperatorMain", "task_id": 1}),
           (_t + timedelta(seconds=10), "Node.PipelineNode.Succeeded", {"task_id": 1, "node_id": 1, "name": "GiftOperatorEnter"}),
           (_t + timedelta(seconds=20), "Tasker.Task.Starting", {"entry": "GearAssemblyStart", "task_id": 2}),
           (_t + timedelta(seconds=21), "Node.PipelineNode.Succeeded", {"task_id": 2, "node_id": 2, "name": "GiftOperatorConfirmGift"})]
    _tr = maaend_fwlog.task_trail(_ev, "GiftOperatorMain", _t, _t + timedelta(seconds=19))
    check("no end event: its own node is kept", _tr["nodes"].get("GiftOperatorEnter"), 1)
    check("the next task's node 2 s after its start is not borrowed", _tr["nodes"].get("GiftOperatorConfirmGift"), None)
    _ev2 = _ev[:2] + [(_t + timedelta(seconds=15), "Node.PipelineNode.Succeeded",
                       {"task_id": 559, "node_id": 3, "name": "EnvironmentMonitoringTakePhoto"})] + _ev[2:]
    _tr2 = maaend_fwlog.task_trail(_ev2, "GiftOperatorMain", _t, _t + timedelta(seconds=19))
    check("a sub-task's node before the next start still counts (sub-tasks post no Starting)",
          _tr2["nodes"].get("EnvironmentMonitoringTakePhoto"), 1)


def _part_mc28_one_alarm():
    _run_mc28_one_alarm()


def _part_maaend_app_log():
    """核对 MaaEnd 时必须连它自己的 app 日志一起看。"""
    import tempfile
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import handle
    from ark_relay.features import outcome

    HISTORY = "\n".join(
        f"[2026-08-29 09:3{i}:00.000] 任务开始: 任务{i}\n"
        f"[2026-08-29 09:3{i}:30.000] 任务完成: 任务{i}" for i in range(3))
    APP = "2026-08-29 09:54:38 INFO  [App] 自动执行任务完成，关闭自身\n"
    SHOTS = [f"2026.08.29-09.39.5{i}___ScenePrivateMapZoomOut.png" for i in range(3)]
    STUCK = ["2026.08.27-09.44.59_SceneAnyEnterWorld.png"]

    def _bad(checks):
        return [c.label for c in checks if not c.ok]

    def main() -> None:
        print("=== 只看 history 日志（早班那次的错误做法）===")
        got = outcome.maaend_checks(HISTORY, SHOTS)
        check("会误判成没跑完", "MaaEnd 跑完" in _bad(got), True)

        print("\n=== 连 app 日志一起看（修好之后）===")
        got2 = outcome.maaend_checks(HISTORY + "\n" + APP, SHOTS)
        check("不再误判没跑完", "MaaEnd 跑完" in _bad(got2), False)
        check("已恢复的截图不算故障", _bad(got2), [])
        check("但截图仍如实列出",
              any("出错截图" in c.label for c in got2), True)

        print("\n=== 万能跳转失败：跑完了也照样算故障 ===")
        got3 = outcome.maaend_checks(HISTORY + "\n" + APP, STUCK)
        check("SceneAnyEnterWorld 一律算故障", "界面没卡住" in _bad(got3), True)
        check("告警里带截图名",
              "SceneAnyEnterWorld" in (outcome.summarize(got3, "MaaEnd") or ""), True)

        print("\n=== a task started and never ended: AUTO-MAS reports it (hand-over grey item 3) ===")
        got4 = outcome.maaend_checks(
            "[x] 任务开始: 基质刷取\n" + APP, [])
        check("the relay no longer adds its own dangling-task check",
              [c.label for c in got4 if "收了尾" in c.label], [])

        print("\n=== _maaend_app_log 真的能读到那句 ===")
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "debug"
            d.mkdir(parents=True)
            (d / "2026-08-29-7.log").write_text(APP, encoding="utf-8")
            (d / "maafw.log").write_text("框架日志，不该被读进来\n", encoding="utf-8")
            started = datetime.now() - timedelta(hours=1)
            txt = handle._maaend_app_log(Path(td), started)
            check("读到了收尾标记", "自动执行任务完成" in txt, True)
            check("没把框架日志混进来", "框架日志" in txt, False)

    main()


def _part_maaend_dir_resolve():
    """MaaEnd 路径必须自己解析出来，解析不出来必须喊。"""
    import json
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core.config import Config

    def _automas(tmp: Path, path_value: str) -> Path:
        """造一个最小的 AUTO-MAS 配置目录，只够 plan.script_dir 认出 MaaEnd。"""
        cfg = tmp / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "ScriptConfig.json").write_text(json.dumps({
            "instances": [{"uid": "u1"}],
            "u1": {"Info": {"Name": "终末地", "Path": path_value}},
        }, ensure_ascii=False), encoding="utf-8")
        return tmp

    def main() -> None:
        print("=== maaend_dir 解析 ===")

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            want = tmp / "maaend"
            (want / "debug").mkdir(parents=True)
            _automas(tmp, str(want))

            # 1) 环境变量没设 → 从 AUTO-MAS 记录里解析出来
            c = Config(automas_dir=tmp, maaend_dir=None)
            check("环境变量没设时能从 AUTO-MAS 解析出来",
                  c.maaend_dir is not None and Path(c.maaend_dir) == want, True)

            # 2) 显式给了就不许被覆盖
            explicit = tmp / "elsewhere"
            c2 = Config(automas_dir=tmp, maaend_dir=explicit)
            check("显式配置优先，不被解析覆盖", Path(c2.maaend_dir), explicit)

            # 3) 没有 automas_dir 时不炸、保持 None
            c3 = Config(automas_dir=None, maaend_dir=None)
            check("没有 automas_dir 时保持 None 且不抛异常", c3.maaend_dir, None)

        # 4) AUTO-MAS 里查不到 MaaEnd → None，不许瞎编一个路径
        with tempfile.TemporaryDirectory() as td:
            tmp = _automas(Path(td), "")          # Path 为空 = 查不到
            c4 = Config(automas_dir=tmp, maaend_dir=None)
            check("AUTO-MAS 里查不到就是 None，不许编路径", c4.maaend_dir, None)

        print("\n=== 解析不出来时必须喊，不许静默 return ===")
        import logging
        from ark_relay.core import engine as E
        from ark_relay.features import handle as H

        class _Rec:
            run_id = "r/1"
            script = "MaaEnd"

        class _Eng:
            cfg = Config(automas_dir=None, maaend_dir=None)
            _archive_maaend_evidence = E.Engine._archive_maaend_evidence

        seen = []

        class _Cap(logging.Handler):
            def emit(self, r):
                seen.append((r.levelno, r.getMessage()))

        h = _Cap()
        H.log.addHandler(h)
        try:
            _Eng()._archive_maaend_evidence(_Rec())
        finally:
            H.log.removeHandler(h)

        check("maaend_dir 缺失时打了 ERROR",
              any(lv >= logging.ERROR for lv, _ in seen), True)
        check("ERROR 里点名 maaend_dir",
              any("maaend_dir" in m for _, m in seen), True)

    main()


def _part_maaend_false_green():
    """A MaaEnd run that ends cleanly but does no work must not be reported green."""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features.outcome import maaend_checks, summarize

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-09-10"

    def bad(checks):
        return {c.label: c.detail for c in checks if not c.ok}

    app = (FIX / "app-2026-09-10-4.log").read_text(encoding="utf-8")
    collect = (FIX / "MaaEnd-06-08-39.log").read_text(encoding="utf-8")
    daily = (FIX / "MaaEnd-05-38-38.log").read_text(encoding="utf-8")

    print("[10:08 那趟：自动采集 38 秒报完成，一条路线没走]")
    got = maaend_checks(collect + "\n" + app, [])
    b = bad(got)
    check("自动采集 被判为没干成", "自动采集 真的走了路线" in b)
    check("说清是几秒就报完成", "38 秒" in b.get("自动采集 真的走了路线", ""))
    check("新版本丢掉旧设置 被判为故障", "自动采集的设置" in b and "其他的设置" in b)
    check("说清丢了多少项（2 + 34 = 36）", "2 个路线选项" in b.get("自动采集的设置", "")
          and "34 个选项" in b.get("其他的设置", ""))
    check("点名 AutoCollectRoutes", "AutoCollectRoutes" in b.get("自动采集的设置", ""))
    check("「跑完」那一项仍然通过", "MaaEnd 跑完" not in b)
    msg = summarize(got, "MaaEnd")
    check("会给出人话告警", msg is not None and "没干成" in msg)
    check("没干成只数真没干的那一项", msg.splitlines()[0], "MaaEnd 这一轮有 1 项没干成，但它自己没报错：")
    check("设置被重置另起一段，不算没干成", "另外这一轮没按你的设置跑（新版本把设置重置成了默认值）：" in msg)
    check("同时有没干成时不算「只是设置」", texts.outcome_settings_only(msg), False)

    print("\n[09:39 那趟：日常全做了、基质刷了三次——不能误伤]")
    got2 = maaend_checks(daily + "\n2026-09-10 10:08:00 INFO [App] 自动执行任务完成，关闭自身\n", [])
    b2 = bad(got2)
    check("基质刷取 算干成", "基质刷取 真的刷了" not in b2)
    check("没有自动采集就不检查它", not any(k.startswith("自动采集") for k in b2))
    check("没有丢设置的行就不报", not any(k.endswith("的设置") for k in b2))
    check("整趟不报警", summarize(got2, "MaaEnd"), None)

    print("\n[协议空间：开了没进去也要报]")
    fake = ("[2026-09-10 09:00:00.000] 任务开始: ⚔️协议空间\n"
            "[2026-09-10 09:00:20.000] 任务完成: ⚔️协议空间\n"
            "2026-09-10 09:00:21 INFO [App] 自动执行任务完成，关闭自身\n")
    check("协议空间没进去被判为没干成", "协议空间 真的进了" in bad(maaend_checks(fake, [])))
    fake_ok = fake.replace("任务完成: ⚔️协议空间", "进入协议空间成功\n[2026-09-10 09:05:00.000] 任务完成: ⚔️协议空间")
    check("进了就通过", "协议空间 真的进了" not in bad(maaend_checks(fake_ok, [])))

    print("[排班说今天不采，秒完成是对的，不能当假绿]")
    skipped = ("[2026-09-11 10:01:51.385] 任务开始: 🧺自动采集\n"
               "[2026-09-11 10:01:51.482] 现在游戏时间是周五，根据执行周期跳过任务\n"
               "[2026-09-11 10:01:51.566] 任务完成: 🧺自动采集\n")
    check("按周期跳过不报「没走路线」", "自动采集 真的走了路线" not in bad(maaend_checks(skipped, [])))
    msg_skip = summarize(maaend_checks(skipped + fake, []), "MaaEnd") or ""
    check("跳过的单独一行「按周期今天不跑」", "按周期今天不跑：自动采集" in msg_skip.splitlines())
    check("跳过的不列进「干成的」", not any(ln.startswith("干成的") and "自动采集" in ln for ln in msg_skip.splitlines()))

    print("\n[2026-10-10 早班：新版把 6 项囤货清单改成开关，旧值被重置为默认——也算丢了旧设置]")
    app1010 = (fx_dir(Path(__file__), "fixtures") / "maaend-2026-10-10" / "app-2026-10-10-3.log").read_text(encoding="utf-8")
    b3 = bad(maaend_checks(app1010, [], own_log=True))
    check("类型变了被重置 被判为故障", "自动囤货的设置" in b3)
    check("说清是 6 个购买选项、没按设置买", "6 个购买选项被 MaaEnd 新版本重置成默认值，今天没按你的设置买"
          in b3.get("自动囤货的设置", ""))
    check("点名囤货那几项", "AutoStockBuyCulturalGoodsValleyIV" in b3.get("自动囤货的设置", ""))
    hist1010 = (fx_dir(Path(__file__), "replay") / "2026-10-10" / "endfield" / "MaaEnd-05-13-19.log").read_text(encoding="utf-8")
    msg3 = summarize(maaend_checks(hist1010 + "\n" + app1010, [], own_log=True), "MaaEnd") or ""
    check("只有设置被重置：不说「没干成」", "没干成" not in msg3)
    check("只有设置被重置：开头说没按你的设置跑", msg3.splitlines()[0],
          "MaaEnd 这一轮没按你的设置跑（新版本把设置重置成了默认值）：")
    check("推送认得这是「只是设置」", texts.outcome_settings_only(msg3), True)
    three = "\n".join([app1010] * 3)
    check("同一项出现几次只算一次", "6 个" in bad(maaend_checks(three, [], own_log=True)).get("自动囤货的设置", ""))
    check("别的 WARN（隐藏主窗口失败）不算丢设置",
          not any(k.endswith("的设置") for k in bad(maaend_checks(
              "2026-10-10 09:14:22 WARN  [App] 自启动时隐藏主窗口失败: Command plugin:window|hide not allowed by ACL\n", []))))


def _part_maaend_logged_out():
    """A MaaEnd task that failed because the account was logged in elsewhere names that as its cause.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.ledger import _with_causes
    from ark_relay.features import collector_maaend as C

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-11-05"
    HISTORY = (FIX / "history-MaaEnd-07-24-54-gathering.log").read_text(encoding="utf-8")
    FW_LINE = (FIX / "maafw-logged-out-ocr.log").read_text(encoding="utf-8")
    TMP = tmpdir()

    def maaend_dir(name, fw_text):
        d = TMP / name
        (d / "debug").mkdir(parents=True, exist_ok=True)
        if fw_text is not None:
            (d / "debug" / "maafw.log").write_text(fw_text, encoding="utf-8")
        return d

    def parse(name, history, fw_text):
        log = TMP / f"{name}.log"
        log.write_text(history, encoding="utf-8")
        return C.parse_maaend_log(log, maaend_dir(name, fw_text))

    print("[11-05 原样：11:43:57 弹「登录认证已失效」，11:54:57 自动采集失败]")
    out = parse("real", HISTORY, FW_LINE)
    check("记下弹框的时刻", out.get("maaend_logged_out_at"), "11:43:57")
    check("自动采集的原因是被挤下线", (out.get("maaend_fail_causes") or {}).get("自动采集"), C.LOGGED_OUT)
    check("报警「卡在」那一段带上原因", _with_causes(out.get("tasks_failed") or [], out.get("maaend_fail_causes")),
          ["自动采集（" + C.LOGGED_OUT + "）"])

    print("\n[框架日志里没有那句话、或者没有框架日志：不写原因]")
    out = parse("no-dialog", HISTORY, FW_LINE.replace(C.LOGGED_OUT_TEXT, "资源完整性"))
    check("没有那句话：不记时刻", "maaend_logged_out_at" in out, False)
    check("没有那句话：不写原因", (out.get("maaend_fail_causes") or {}).get("自动采集"), None)
    out = parse("no-fw", HISTORY, None)
    check("没有框架日志：不写原因", (out.get("maaend_fail_causes") or {}).get("自动采集"), None)

    print("\n[弹框之前就失败的任务：不算被挤下线]")
    early = "\n".join(line for line in HISTORY.splitlines() if line < "[2026-11-05 11:43:5")
    early += "\n[2026-11-05 11:43:00.000] 任务失败: 🧺自动采集\n"
    out = parse("early", early, FW_LINE)
    check("弹框前失败：不写原因", (out.get("maaend_fail_causes") or {}).get("自动采集"), None)


def _part_maaend_agreement():
    """#187: the game opened on the one-time 「协议更新」 dialog; the failed tasks name it."""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.ledger import _with_causes
    from ark_relay.features import collector_maaend as C
    from datetime import datetime

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-11-20"
    HISTORY = (FIX / "history-MaaEnd-05-32-21.log").read_text(encoding="utf-8")
    FW = (FIX / "maafw-agreement-ocr.log").read_text(encoding="utf-8")
    OLD = (fx_dir(Path(__file__), "fixtures") / "maaend-2026-11-05" / "maafw-logged-out-ocr.log").read_text(encoding="utf-8")
    TMP = tmpdir()

    def parse(name, history, fw_text):
        d = TMP / name
        (d / "debug").mkdir(parents=True, exist_ok=True)
        if fw_text is not None:
            (d / "debug" / "maafw.log").write_text(fw_text, encoding="utf-8")
        log = TMP / f"{name}.log"
        log.write_text(history, encoding="utf-8")
        return C.parse_maaend_log(log, d)

    print("[11-20 原样（证据包里的框架日志从 10:46:38 起）：10:46:39 读到「请您仔细阅读并同意以下协议」]")
    out = parse("real", HISTORY, FW)
    causes = out.get("maaend_fail_causes") or {}
    check("记下第一次读到的时刻", out.get("maaend_agreement_at"), "10:46:39")
    check("那之后失败的两个任务带上原因", {k: v for k, v in causes.items()},
          {"基质刷取": C.AGREEMENT, "日常奖励领取": C.AGREEMENT})
    check("那之前失败的不硬套（框架日志里看不到那时候）", "赠送干员礼物" in causes, False)
    check("报警「卡在」那一段", _with_causes(["基质刷取", "日常奖励领取"], causes),
          ["基质刷取（" + C.AGREEMENT + "）", "日常奖励领取（" + C.AGREEMENT + "）"])
    check("说法是平白中文", texts.plain(C.AGREEMENT), [])

    print("\n[游戏机上的整份框架日志从 09:3x 就有这句：第一个失败的任务起全都带上]")
    early = FW.replace("[2026-11-20 10:46:39.237]", "[2026-11-20 09:34:30.000]")
    out = parse("whole", HISTORY, early)
    causes = out.get("maaend_fail_causes") or {}
    check("15 个失败的都是这个原因", (len(causes), set(causes.values())), (15, {C.AGREEMENT}))
    check("自动采集是周五按周期跳过、完成的，不算", "自动采集" in causes, False)

    print("\n[11-20 游戏机上真实的样子：09:34-10:46 在压缩过的轮转文件里，maafw.log 从 10:46:38 起]")
    import gzip

    def rotated(d, stamp, text, suffix=".log.gz"):
        f = d / "debug" / f"maafw.bak.{stamp}{suffix}"
        f.write_bytes(gzip.compress(text.encode("utf-8")) if suffix.endswith(".gz") else text.encode("utf-8"))
        return f
    d = TMP / "gz"
    (d / "debug").mkdir(parents=True, exist_ok=True)
    (d / "debug" / "maafw.log").write_text(FW.replace(C.AGREEMENT_TEXT, "本次更新"), encoding="utf-8")
    rotated(d, "2026.11.20-09.40.02.867", FW.replace("[2026-11-20 10:46:39.237]", "[2026-11-20 09:34:28.920]"))
    rotated(d, "2026.11.20-10.13.19.711", "[2026-11-20 10:00:00.000][DBG] nothing\n")
    old = rotated(d, "2026.11.19-10.09.48.424", FW.replace("[2026-11-20 10:46:39.237]", "[2026-11-19 10:00:00.000]"))
    rotated(d, "2026.11.20-11.30.00.000", "[2026-11-20 11:00:00.000][DBG] after\n")
    rotated(d, "2026.11.20-12.00.00.000", "[2026-11-20 11:40:00.000][DBG] later\n")
    (d / "debug" / "maafw.bak.2026.11.20-10.13.19.711.log.gz.2026.11.21-00.00.00.000.tmp").write_bytes(b"\x1f\x8b broken")
    (d / "debug" / "maafw.bak.2026.11.20-10.40.00.000.log.gz").write_bytes(b"\x1f\x8b not really gzip")
    log = TMP / "gz.log"
    log.write_text(HISTORY, encoding="utf-8")
    out = C.parse_maaend_log(log, d)
    causes = out.get("maaend_fail_causes") or {}
    check("09:34:28 读到（压缩文件里）", out.get("maaend_agreement_at"), "09:34:28")
    check("15 个失败的都是这个原因", (len(causes), set(causes.values())), (15, {C.AGREEMENT}))
    names = [f.name for f in C._fw_files(d, datetime(2026, 11, 20, 9, 34, 22), datetime(2026, 11, 20, 10, 57, 46))]
    check("只读盖到这一趟的：前一天的不读、写到一半的 .tmp 不读、过了这一趟的只读紧接着的那一个",
          names, ["maafw.bak.2026.11.20-09.40.02.867.log.gz", "maafw.bak.2026.11.20-10.13.19.711.log.gz",
                  "maafw.bak.2026.11.20-10.40.00.000.log.gz", "maafw.bak.2026.11.20-11.30.00.000.log.gz", "maafw.log"])
    check("坏的压缩文件跳过，不出错", len(C.maafw_grep(d, datetime(2026, 11, 20, 9, 34, 22), datetime(2026, 11, 20, 10, 57, 46),
                                               (C.AGREEMENT_TEXT,))) > 0, True)
    check("不给时间段：跟以前一样只列不压缩的", [f.name for f in C._fw_files(d)], ["maafw.log"])
    rotated(d, "2026.11.20-09.40.02.867", FW.replace("[2026-11-20 10:46:39.237]", "[2026-11-20 09:34:28.920]"), ".log")
    names = [f.name for f in C._fw_files(d, datetime(2026, 11, 20, 9, 34, 22), datetime(2026, 11, 20, 10, 57, 46))]
    check("同一次轮转既有 .log 又有 .log.gz（11-15 那样）：只读一份", sum("09.40.02.867" in n for n in names), 1)
    old.unlink()

    print("\n[没有这句、或者没有框架日志：不写原因，跟以前一样]")
    out = parse("no-dialog", HISTORY, FW.replace(C.AGREEMENT_TEXT, "资源完整性"))
    check("没有那句话：不记时刻、不写原因", ("maaend_agreement_at" in out, out.get("maaend_fail_causes")), (False, None))
    out = parse("no-fw", HISTORY, None)
    check("没有框架日志：不写原因", out.get("maaend_fail_causes"), None)

    print("\n[两个框都有：被挤下线的说法排在协议窗口前面]")
    both = early + OLD.replace("2026-11-05 11:43:57", "2026-11-20 10:30:00")
    out = parse("both", HISTORY, both)
    causes = out.get("maaend_fail_causes") or {}
    check("10:30 之前失败的：协议窗口", causes.get("据点交易"), C.AGREEMENT)
    check("10:30 之后失败的：被挤下线", causes.get("基质刷取"), C.LOGGED_OUT)


def _part_maaend_recovered():
    """MaaEnd hung and the relay ends it: which of the two log lines is "recovered"."""
    import logging
    import os
    from datetime import datetime

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import errwatch, handle
    from ark_relay.features import maaend_watchdog
    from ark_relay.core import statestore as techlog, texts
    from ark_relay.core.config import SERVER_TZ, RunRecord

    class Refuses:
        """errwatch's notifier: the group refuses, so what it queues stays queued."""

        def send_group(self, title, body):
            return ["企业微信机器人：拒收"]

        def send(self, title, body, **kw):
            return ["拒收"]

    class Lines(logging.Handler):
        """Captures every ark.* record, so the test can read `ark_recovered`."""

        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def said(self, *parts):
            return [r for r in self.records if all(p in r.getMessage() for p in parts)]

    ARK_LOGGER = logging.getLogger(errwatch.ARK)
    LINES = Lines()
    ARK_LOGGER.addHandler(LINES)
    ARK_LOGGER.setLevel(logging.DEBUG)

    def watch():
        sd = tmpdir() / "state"                          # its own tech/ next to it (techlog.tech_dir)
        h = errwatch.ErrorKindAlert(Refuses(), state_dir=sd, known={}, retry=(3600.0,), fallback_after=1e9)
        ARK_LOGGER.addHandler(h)
        LINES.records.clear()
        return h, sd

    def unwatch(h):
        ARK_LOGGER.removeHandler(h)
        h.close()

    RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
    PID = 11224
    PROCS = [("MaaEnd.exe", PID), ("Endfield.exe", 18800)]   # no plugins: the kill loop stays quiet
    CRASH_LINE = "Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456"
    HUNG_MXU = ["2026-10-01 16:58:19 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: task-progress",
                "2026-10-01 16:58:22 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: tasks-completed"]

    class Dog:
        """One watchdog with everything outside replaced."""

        def __init__(self, mxu_lines):
            self.debug = tmpdir() / "debug"
            self.debug.mkdir()
            self.stderr = self.debug / "go-service.stderr.log"
            self.stderr.write_text("", encoding="utf-8")
            (self.debug / "2026-10-01-6.log").write_text("\n".join(mxu_lines) + "\n", encoding="utf-8")
            self.t, self.wall = 1000.0, datetime(2026, 10, 1, 16, 58, 22)
            self.notes, self.killed = _Notes(), []
            self.procs = list(PROCS)
            self.dog = maaend_watchdog.Watchdog(
                self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: RUNNING,
                processes=lambda: list(self.procs), kill=self._kill,
                plugin_paths=lambda: {}, active=True)
            self.dog.tick(1, "")                          # first sight of this MaaEnd

        def _kill(self, pid, image):
            self.killed.append((pid, image))
            return True, ""

        def at(self, hh, mm, ss):
            new = datetime(2026, 10, 1, hh, mm, ss)
            self.t += (new - self.wall).total_seconds()
            self.wall = new
            return self.dog.tick(1, "")

    def recovered_of(records, *parts):
        rows = [r for r in records if all(p in r.getMessage() for p in parts)]
        assert rows, f"no log record matching {parts}"
        return [getattr(r, errwatch.RECOVERED, False) for r in rows]

    print("[finished, did not exit -> left to AUTO-MAS (v5.7.0-beta.2): no kill, no send, no WARNING]")
    h, sd = watch()
    try:
        d = Dog(HUNG_MXU)
        for hh, mm, ss in ((16, 58, 53), (16, 59, 24), (17, 0, 0)):     # well past the old 30 s
            check(f"{hh}:{mm:02d}:{ss:02d}: nothing done", d.at(hh, mm, ss), None)
        check("never killed", d.killed, [])
        check("nothing sent", d.notes.sent, [])
        check("no 「卡死」 line", LINES.said("MaaEnd 卡死"), [])
        check("nothing queued for the group", h.pending(), [])
    finally:
        unwatch(h)

    print("\n[crash -> the ⚠️ is the one push; the 「卡死」 WARNING repeats it and is not queued (2026-10-11)]")
    h, sd = watch()
    try:
        d = Dog([])
        d.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        d.at(16, 59, 0)                                   # crash read -> kill
        check("the 「卡死」 WARNING is not marked recovered", recovered_of(LINES.records, "MaaEnd 卡死"), [False])
        check("it is not queued for the group (errwatch.group_pushed: the ⚠️ went out)",
              [str(x.get("line"))[:9] for x in h.pending()], [])
        check("the ⚠️ notice still rings", [(t, a) for t, _, a in d.notes.sent],
              [(texts.MAAEND_STUCK_KILLED, True)])
    finally:
        unwatch(h)

    print("\n[bookkeeping: the 「🟠 任务全部完成」 line with no AUTO-MAS kill line is pushed]")

    class _Cfg:
        def __init__(self, history_dir=None):
            self.history_dir = history_dir                # None: no app.log read, idle stays 0

    class _State:
        def __init__(self):
            self.marks = []

        def mark_raw(self, *a):
            self.marks.append(a)

    class _Eng:
        def __init__(self, history_dir=None):
            self.cfg = _Cfg(history_dir)
            self.state = _State()

    def automas_app_log(lines):
        """<automas>/history next to <automas>/debug/app.log, as collector reads it."""
        root = tmpdir() / "automas"
        (root / "history").mkdir(parents=True)
        (root / "debug").mkdir()
        (root / "debug" / "app.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return root / "history"

    SHIPPED = []
    _real_ship = handle._ship_evidence

    def _fake_ship(eng, rec):
        # The real one uploads to COS; here only who asked for a bundle is recorded.
        SHIPPED.append(rec.run_id)
        rec.raw["evidence_page"] = "https://example.invalid/bundle"
        return rec.raw["evidence_page"]

    def exit_rec(n):
        return RunRecord(run_id=f"2026-10-06/endfield/MaaEnd-05-28-0{n}", script="MaaEnd", user="endfield",
                         started=datetime(2026, 10, 6, 9, 51, 51, tzinfo=SERVER_TZ),
                         finished=datetime(2026, 10, 6, 9, 52, 54, tzinfo=SERVER_TZ), ok=True)

    handle._ship_evidence = _fake_ship
    h, sd = watch()
    try:
        rec = exit_rec(1)
        handle._mark_no_self_exit(_Eng(), rec)
        check("the bookkeeping line is not marked recovered",
              recovered_of(LINES.records, "🟠 MaaEnd", "任务全部完成"), [False])
        check("it is queued for the group", any("任务全部完成" in str(x.get("line")) for x in h.pending()), True)
        check("the no-exit run ships its evidence bundle", SHIPPED, [rec.run_id])
        handle._mark_no_self_exit(_Eng(), rec)
        check("a replay of the same record does not ship it twice", SHIPPED, [rec.run_id])
    finally:
        handle._ship_evidence = _real_ship
        unwatch(h)

    print("\n[bookkeeping: AUTO-MAS ended the finished MaaEnd -> recovered, a red item, not pushed]")
    MAS_RESULT = "2026-10-06 09:52:55.101 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: Success!, 日志锁已释放"
    MAS_ENDED = "2026-10-06 09:52:55.104 | WARNING  | MaaEnd 自动代理 | MaaEnd 队列已结束但进程未退出，正在中止脚本进程"
    handle._ship_evidence = _fake_ship
    SHIPPED.clear()
    h, sd = watch()
    try:
        rec = exit_rec(2)
        eng = _Eng(automas_app_log([MAS_RESULT, MAS_ENDED]))
        handle._mark_no_self_exit(eng, rec)
        rows = LINES.said("MaaEnd", "任务全部完成", "AUTO-MAS")
        check("one INFO line naming AUTO-MAS's kill", [r.levelno for r in rows], [logging.INFO])
        check("not marked recovered", [getattr(r, errwatch.RECOVERED, False) for r in rows], [False])
        red = [t for f in sorted(techlog.tech_dir(sd).glob("*.md")) for _, t in techlog.unhandled(f.read_text(encoding="utf-8"))
               if "任务全部完成" in t]
        check("no red item for it", red, [])
        check("nothing queued for the group", h.pending(), [])
        check("still booked for the technical log", [m[2:] for m in eng.state.marks], [("maaend_no_self_exit", 0)])
        check("still ships its evidence bundle", SHIPPED, [rec.run_id])
    finally:
        handle._ship_evidence = _real_ship
        unwatch(h)

    print("\n[bookkeeping: an AUTO-MAS kill line from another run is not this run's]")
    handle._ship_evidence = _fake_ship
    h, sd = watch()
    try:
        late = "2026-10-06 09:55:00.000 | WARNING  | MaaEnd 自动代理 | MaaEnd 队列已结束但进程未退出，正在中止脚本进程"
        rec = exit_rec(3)
        handle._mark_no_self_exit(_Eng(automas_app_log([MAS_RESULT, late])), rec)
        check("not marked recovered", recovered_of(LINES.records, "🟠 MaaEnd", "任务全部完成"), [False])
        check("it is queued for the group", any("任务全部完成" in str(x.get("line")) for x in h.pending()), True)
    finally:
        handle._ship_evidence = _real_ship
        unwatch(h)

    ARK_LOGGER.removeHandler(LINES)


def _part_maaend_reenable():  # noqa: C901
    """Boot: the booster step is read and rings the group when unknown; no task is switched off or on.
    """
    import json
    import logging
    import shutil
    import types
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()

    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any

    for _n in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
               "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_n, _Stub(_n))

    import boot_stages
    from ark_relay.features import collect_retry
    from ark_relay.features import errwatch
    from ark_relay.features import gameupdate
    from ark_relay.core import mastercfg, notify, texts
    from ark_relay.core.statestore import StateStore

    FIX = fx_dir(Path(__file__), "fixtures")
    MASTER = FIX / "maaend-2026-09-10" / "master-before.json"
    V_BETA4 = FIX / "maaend228" / "interface.json"                       # v2.28.0-beta.4
    V_BETA5 = FIX / "maaend-2026-09-10" / "interface.json"                 # v2.28.0-beta.5
    V_230 = FIX / "maaend-v2.30.0-beta.4-spmed"                            # interface + nodes
    NODES_230 = V_230 / "resource" / "pipeline" / "nodes.json"
    # The confirm step under neither of its names: v2.30's real file has it as
    # __AutoUseSpMedicationUseEmergencySpBooster, in the fixed shape (test_spmed.py).
    NODES_GONE = {k: v for k, v in json.loads(NODES_230.read_text(encoding="utf-8")).items()
                  if k not in ("AutoUseSpMedicationQuickUse", "__AutoUseSpMedicationUseEmergencySpBooster")}
    FOUR = ["GiftOperator", "GearAssembly", "DeliveryJobs", "EnvironmentMonitoring"]
    SP = "AutoUseSpMedication"
    SPMED = {"taskName": SP, "enabled": False, "enabledByController": {"Win32-Front": False}, "optionValues": {}}
    RSP = {"maaend_disabled_spmed": {"tasks": [SP], "since": "v2.28.0-beta.4"}}
    FIXED = {"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
        "YellowConfirmButtonType2", {"recognition": "OCR", "expected": "确认"}]}}}}
    BROKEN = {"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
        "YellowConfirmButtonType2", {"param": {"expected": "确认"}, "type": "OCR"}]}}}}
    NO_RECOGNITION = {"AutoUseSpMedicationQuickUse": {"next": ["AutoUseSpMedicationDialogText"]}}

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelname, record.getMessage()))

    CAP = Capture()
    logging.getLogger(errwatch.ARK).addHandler(CAP)
    logging.getLogger(errwatch.ARK).setLevel(logging.DEBUG)

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, bool(kw.get("alert"))))
            return []

    class Log:
        def __init__(self):
            self.lines = []

        def _rec(self, *a, **k):
            self.lines.append(a)

        info = warning = error = debug = exception = _rec

    # Only the booster check is under test: the later steps of the
    # stage (dead entries, option migration, route restore) are stubbed.
    mastercfg.prune_maaend_orphans = lambda *a: ([], "")
    mastercfg.migrate_maaend_options = lambda *a: ([], "")
    collect_retry.restore_master = lambda cfg: ""
    TITLE = getattr(texts, "SPMED_UNRECOGNISED", "<no such title>")

    def machine(*, version=None, nodes=None, off=(), extra_tasks=(), master=True, record=None):
        """state dir + MaaEnd dir + AUTO-MAS dir. Returns (cfg, master path, store)."""
        root = tmpdir()
        state = root / "state"
        state.mkdir()
        maaend = root / "maaend"
        maaend.mkdir()
        if version is not None:
            shutil.copy(version, maaend / "interface.json")
        if nodes is not None:
            (maaend / "resource" / "pipeline").mkdir(parents=True)
            if isinstance(nodes, Path):
                shutil.copy(nodes, maaend / "resource" / "pipeline" / "nodes.json")
            else:
                (maaend / "resource" / "pipeline" / "nodes.json").write_text(
                    json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
        automas = root / "automas"
        target = automas / "data" / "59da8762-sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
        if master:
            target.parent.mkdir(parents=True)
            j = json.loads(MASTER.read_text(encoding="utf-8"))
            tasks = j["instances"][0]["tasks"]
            tasks.extend(json.loads(json.dumps(t)) for t in extra_tasks)
            for t in tasks:
                if t.get("taskName") in off:
                    t["enabled"] = False
                    if isinstance(t.get("enabledByController"), dict):
                        t["enabledByController"] = {k: False for k in t["enabledByController"]}
            target.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
        store = StateStore(state)
        for key, value in (record or {}).items():
            store.set("updates", key, value)
        cfg = SimpleNamespace(state_dir=state, maaend_dir=maaend, automas_dir=automas)
        return cfg, target, store

    def enabled(target, names):
        j = json.loads(target.read_text(encoding="utf-8"))
        by = {t.get("taskName"): t.get("enabled") for t in j["instances"][0]["tasks"]}
        return {n: by.get(n) for n in names}

    def others(target, names):
        """Every task not named, as (name, enabled, controllers) - to prove nothing else moved."""
        j = json.loads(target.read_text(encoding="utf-8"))
        return [(t.get("taskName"), t.get("enabled"), json.dumps(t.get("enabledByController")))
                for t in j["instances"][0]["tasks"] if t.get("taskName") not in names]

    def updates(store):
        return dict(StateStore(store.dir).section("updates"))

    def boot(cfg):
        """One boot's re-enable stage. Returns (pushes, log lines of ark.*)."""
        n = Notes()
        CAP.lines.clear()
        boot_stages._stage_reenable_maaend(cfg, n, Log())
        return n.sent, list(CAP.lines)

    def spmed_pushes(sent):
        return [(t, a) for t, _b, a in sent if t == TITLE]

    others(MASTER, FOUR)
    check("fixture versions are what the names say",
          [json.loads(p.read_text(encoding="utf-8"))["version"]
           for p in (V_BETA4, V_BETA5, V_230 / "interface.json")],
          ["v2.28.0-beta.4", "v2.28.0-beta.5", "v2.30.0-beta.4"])
    check("the real v2.30.0-beta.4 nodes.json has no AutoUseSpMedicationQuickUse",
          "AutoUseSpMedicationQuickUse" in json.loads(NODES_230.read_text(encoding="utf-8")), False)

    print("\n[booster task on, MaaEnd v2.30 with the step under neither name: the group is told, every boot]")
    on_sp = dict(SPMED, enabled=True, enabledByController={"Win32-Front": True})
    cfg, target, store = machine(version=V_230 / "interface.json", nodes=NODES_GONE, extra_tasks=[on_sp])
    sent, lines = boot(cfg)
    check("the unknown booster step rings the group", spmed_pushes(sent), [(TITLE, True)])
    check("that title routes to the group", notify.route_of(TITLE, alert=True), "group")
    body = next((b for t, b, _a in sent if t == TITLE), "")
    check("the text says the task stays on and why it rings", ("一直开着" in body, "找不到" in body), (True, True))
    check("the text is plain Chinese", texts.plain(body), [])
    sent2, _ = boot(cfg)
    check("next boot: rings again (each time it is seen)", len(spmed_pushes(sent2)), 1)

    for label, nodes in (("node with no recognition block", NO_RECOGNITION), ("the 09-03 broken shape", BROKEN)):
        print(f"\n[{label}: group told]")
        cfg, target, store = machine(version=V_BETA5, nodes=nodes, extra_tasks=[on_sp])
        sent, _ = boot(cfg)
        check("group told", len(spmed_pushes(sent)), 1)
        check("not the old 「游戏更新没能确认」 info push", [t for t, _b, _a in sent if "没能确认" in t], [])

    print("\n[booster task on, no record, booster step unknown: the task is not touched, group told]")
    on_sp = dict(SPMED, enabled=True, enabledByController={"Win32-Front": True})
    cfg, target, store = machine(version=V_230 / "interface.json", nodes=NODES_GONE, extra_tasks=[on_sp])
    before = target.read_bytes()
    sent, _ = boot(cfg)
    check("master not rewritten", target.read_bytes(), before)
    check("group told", len(spmed_pushes(sent)), 1)

    print("\n[no record, fixed shape: nothing written, nothing pushed]")
    cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=FOUR)
    before = target.read_bytes()
    sent, _ = boot(cfg)
    check("master not rewritten", target.read_bytes(), before)
    check("no push", sent, [])

    print("\n[a leftover switch-off record: left alone, the master is not touched (s18 F5)]")
    cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=FOUR + ["AutoCollect"], extra_tasks=[SPMED],
                                 record={"maaend_disabled_1_5_3": {"disabled": FOUR},
                                         "maaend_reenable_next_boot": {"tasks": ["AutoCollect"]},
                                         **RSP})
    before = target.read_bytes()
    sent, lines = boot(cfg)
    check("master not rewritten", target.read_bytes(), before)
    check("records left as they were", sorted(k for k in updates(store) if k.startswith("maaend_")),
          ["maaend_disabled_1_5_3", "maaend_disabled_spmed", "maaend_reenable_next_boot"])
    check("nothing pushed, nothing logged about them", (sent, [m for _lv, m in lines if "开回" in m]), ([], []))
    check("the re-enable functions are gone",
          [n for n in ("maaend_enable", "maaend_reenable_records", "maaend_set_enabled") if hasattr(gameupdate, n)], [])

    print("\n[the booster step's shape, read from nodes.json]")
    shape = getattr(gameupdate, "spmed_shape", None)
    check("spmed_shape exists", callable(shape), True)
    if callable(shape):
        for label, nodes, want in (("fixed", FIXED, "fixed"), ("broken", BROKEN, "broken"),
                                   ("no recognition block", NO_RECOGNITION, "unknown"),
                                   ("v2.30: the step under its new name, fixed shape", NODES_230, "fixed"),
                                   ("the step under neither name", NODES_GONE, "missing")):
            check(label, shape(machine(nodes=nodes)[0].maaend_dir), want)
        check("nodes.json missing", shape(machine()[0].maaend_dir), "unreadable")
        check("no MaaEnd directory", shape(None), "")


def _part_maaend_stopped_between_tasks():
    """A MaaEnd that stopped between two tasks is not a finished round."""
    import json
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

    HERE = pathlib.Path(__file__).resolve().parent

    FIX = fx_dir(HERE, "fixtures")
    LOG_0928 = (FIX / "maaend-farm-drops" / "2026-09-28a.log").read_text(encoding="utf-8").splitlines(keepends=True)
    LOG_0901 = (FIX / "maaend_full_2026-09-01.log").read_text(encoding="utf-8")
    # Line 164 starts 环境监测, line 165 completes it, and line 166 starts the next task.
    assert "任务完成: 🌿环境监测" in LOG_0928[164], LOG_0928[164]
    assert "任务开始: 🌿环境监测" in LOG_0928[163], LOG_0928[163]
    assert "任务完成: ❌关闭游戏（PC）" in LOG_0928[-1], LOG_0928[-1]
    STOPPED = "".join(LOG_0928[:165])     # stopped right after 环境监测 completed
    STUCK = "".join(LOG_0928[:164])       # 环境监测 started, never ended
    FULL = "".join(LOG_0928)

    root = tmpdir()
    day = root / "2026-09-28" / "endfield"
    day.mkdir(parents=True)
    _n = [0]

    def record(result, log, stem=None):
        _n[0] += 1
        stem = stem or f"MaaEnd-06-{_n[0]:02d}-00"
        (day / f"{stem}.json").write_text(json.dumps({"maaend_result": result}, ensure_ascii=False), encoding="utf-8")
        (day / f"{stem}.log").write_text(log, encoding="utf-8")
        return stem, collector.parse_record(day / f"{stem}.json", root)

    print("[stopped after 环境监测; AUTO-MAS lists 自动采集, which never started]")
    stem_stopped, r = record("[日常] MaaEnd 部分任务执行失败: 🧺自动采集", STOPPED)
    check("not a success", r.ok, False)
    check("keeps AUTO-MAS's list", r.failed_tasks, ["自动采集"])
    check("not marked as a name mismatch", r.raw.get("maaend_name_mismatch"), None)

    print("\n[stopped after 环境监测, killed for 进程超时]")
    _, r = record("MaaEnd 进程超时", STOPPED)
    check("not a success", r.ok, False)
    check("says it timed out", r.failed_tasks, ["MaaEnd 进程超时"])
    check("not marked done-then-hung", r.raw.get("maaend_done_then_hung"), None)

    print("\n[the full 09-28 11:22 log, killed for 进程超时 -> done, then hung]")
    _, r = record("MaaEnd 进程超时", FULL)
    check("ok", r.ok, True)
    check("no failures", r.failed_tasks, [])
    check("marked done-then-hung", r.raw.get("maaend_done_then_hung"), True)

    print("\n[the full 09-28 log, AUTO-MAS cannot match a renamed task (关闭游戏 era)]")
    _, r = record("MaaEnd 部分任务执行失败: SellProduct", FULL)
    check("ok", r.ok, True)
    check("records the name AUTO-MAS missed", r.raw.get("maaend_name_mismatch"), ["SellProduct"])

    print("\n[the full 09-01 log, renamed task (结束进程 era)]")
    d01 = root / "2026-09-01" / "endfield"
    d01.mkdir(parents=True)
    (d01 / "MaaEnd-03-00-00.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: SellProduct"}, ensure_ascii=False), encoding="utf-8")
    (d01 / "MaaEnd-03-00-00.log").write_text(LOG_0901, encoding="utf-8")
    r = collector.parse_record(d01 / "MaaEnd-03-00-00.json", root)
    check("ok", r.ok, True)
    check("records the name AUTO-MAS missed", r.raw.get("maaend_name_mismatch"), ["SellProduct"])

    print("\n[stuck mid-task: 环境监测 started, no end]")
    _, r = record("MaaEnd 部分任务执行失败: 🌿环境监测", STUCK)
    check("partial failure stays a failure", (r.ok, r.failed_tasks), (False, ["环境监测"]))
    _, r = record("MaaEnd 进程超时", STUCK)
    check("timeout stays a failure", (r.ok, r.failed_tasks), (False, ["MaaEnd 进程超时"]))

    print("\n[never started: the log has no task line at all]")
    _, r = record("MaaEnd 部分任务执行失败: 🎁赠送干员礼物", "".join(LOG_0928[:13]))
    check("partial failure stays a failure", (r.ok, r.failed_tasks), (False, ["赠送干员礼物"]))
    _, r = record("MaaEnd 进程超时", "".join(LOG_0928[:13]))
    check("timeout stays a failure", (r.ok, r.failed_tasks), (False, ["MaaEnd 进程超时"]))

    print("\n[closing task started but never completed]")
    _, r = record("MaaEnd 进程超时", "".join(LOG_0928[:-1]))
    check("not a success", r.ok, False)

    print("\n[a task started after the closing task]")
    _, r = record("MaaEnd 进程超时", FULL + "[2026-09-28 11:22:11.000] 任务开始: 🧺自动采集\n"
                  "[2026-09-28 11:22:12.000] 任务完成: 🧺自动采集\n")
    check("not a success", r.ok, False)

    print("\n[re-judging the ledger only moves towards done]")
    run_id = f"2026-09-28/endfield/{stem_stopped}"
    old = {"run_id": run_id, "script": "MaaEnd", "ok": False, "failed_tasks": ["自动采集"], "raw": {}}
    fresh = collector.refresh_raw(old, root)
    check("stopped run stays failed", (fresh.get("ok"), fresh.get("failed_tasks")), (False, ["自动采集"]))
    old_ok = {"run_id": run_id, "script": "MaaEnd", "ok": True, "failed_tasks": [], "raw": {}}
    fresh = collector.refresh_raw(old_ok, root)
    check("an entry already marked ok is left ok", (fresh.get("ok"), fresh.get("failed_tasks")), (True, []))

    print("\n[audit 11-08 B-02/B-03: a closing task does not excuse tasks that never started]")
    from ark_relay.features.collector_maaend import _maaend_all_done
    from ark_relay.features import outcome
    full = "".join(LOG_0928)
    check("the real 09-28 round, closing task last: done", _maaend_all_done(full), True)
    no_proto = "".join(x for x in LOG_0928 if "⚔️协议空间" not in x)
    check("closing task ran, but a display name AUTO-MAS lists never started: not done",
          _maaend_all_done(no_proto, ["协议空间"]), False)
    check("the listed name did start (AUTO-MAS's stale verdict): still done", _maaend_all_done(full, ["协议空间"]), True)
    check("a bare key AUTO-MAS could not name still passes (09-06 SellProduct)", _maaend_all_done(full, ["SellProduct"]), True)
    twice = full.replace("[2026-09-28 11:22:07.978] 任务开始: ❌关闭游戏（PC）",
                         "[2026-09-28 11:22:07.000] 任务开始: 🎁赠送干员礼物\n[2026-09-28 11:22:07.978] 任务开始: ❌关闭游戏（PC）")
    check("a task started twice and completed once is not done (count, not set)", _maaend_all_done(twice), False)
    cut = [c for c in outcome._maaend_cut_short(twice) if not c.ok]
    check("maaend_checks: started without an end is a failed check", [c.label for c in cut], ["赠送干员礼物 跑完"])
    stop_log = (FIX / "maaend_stop_task_2026-10-08.log").read_text(encoding="utf-8")
    cut = outcome._maaend_cut_short(stop_log)
    check("10-08 10:34 MaaEnd stopped itself before the closing task: failed check", [c.label for c in cut],
          ["MaaEnd 没被中途停掉"])
    hung = full + "[2026-09-28 11:40:00.000] 任务开始: 停止任务\n[2026-09-28 11:40:00.100] 任务完成: 停止任务\n"
    check("a stop after the closing task (AUTO-MAS stopping a done MaaEnd) is not a failure",
          outcome._maaend_cut_short(hung), [])


def _part_maaend_stub_record():
    """A MaaEnd record AUTO-MAS wrote for an attempt that never ran is not a run."""
    import os
    import shutil
    import tempfile
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.features import evidence
    from ark_relay.features import handle
    from ark_relay.core import ledger as core

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-09-18"

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "history"
        d = root / "2026-09-18" / "endfield"
        d.mkdir(parents=True)
        for f in FIX.iterdir():
            shutil.copy(f, d / f.name)
        recs = {n: collector.parse_record(d / f"{n}.json", root) for n in ("MaaEnd-05-26-03", "MaaEnd-05-54-35", "MaaEnd-05-54-44")}

        print("[空记录：解析为「中途重启」，不算失败、不进失败清单]")
        stub = recs["MaaEnd-05-54-35"]
        check("解析出来了", stub is not None)
        check("不算成功", stub.ok, False)
        check("标为中途重启", stub.transitional, True)
        check("失败清单为空", stub.failed_tasks, [])
        real1, real3 = recs["MaaEnd-05-26-03"], recs["MaaEnd-05-54-44"]
        check("真失败的两趟照旧：不是中途重启、失败清单有基质刷取",
              (real1.transitional, real3.transitional, real1.failed_tasks, real3.failed_tasks),
              (False, False, ["基质刷取"], ["基质刷取"]))

        print("\n[尝试次数：只数真跑过的]")
        ledger = [{"run_id": r.run_id, "script": r.script, "user": r.user, "ok": r.ok,
                   "started": r.started.isoformat(), "finished": r.finished.isoformat(),
                   "failed_tasks": r.failed_tasks, "transitional": r.transitional, "raw": r.raw}
                  for r in (real1, stub, real3)]
        eng = types.SimpleNamespace(state=types.SimpleNamespace(read_ledger=lambda day: ledger))
        check("三条记录，尝试 2 次", handle._attempts(eng, real3, "2026-09-18"), 2)

        print("\n[日报：空记录不成一行；两趟真失败合并为一行]")
        core.episode_kinds(ledger)
        title, body = core.format_daily("2026-09-18", ledger, "", "")
        check("空记录不出现在日报里", "05-54-35" not in body and "未捕获" not in body)
        check("基质刷取的失败出现", "基质刷取" in body)
        check("标题不是全绿", "全绿" not in title)
        check("日报里有一行信息：重启 1 次、未计失败", "终末地装新版后自己重启 1 次，未计失败" in body)
        check("标题只数两趟真失败，不含空记录", "终末地失败 2 次" in title)

        print("\n[老版本记的账没有 transitional 标记（09-18 早上的三条就是）：照样不算失败]")
        old_ledger = [dict(e) for e in ledger]
        for e in old_ledger:
            e.pop("transitional", None)
        title_o, body_o = core.format_daily("2026-09-18", old_ledger, "", "")
        check("没有标记也不成一行", "05-54-35" not in body_o and "未捕获" not in body_o)
        check("没有标记也只算 2 次失败（09-18 晚报成了 3 项）", "终末地失败 2 次" in title_o)
        check("信息行照样有", "终末地装新版后自己重启 1 次，未计失败" in body_o)
        check("没有重启的日子不出这一行", "自更新重启" not in core.format_daily("2026-09-18", [e for e in ledger if e is not ledger[1]], "", "")[1])

    print("\n[证据包带上 relay.log 与调度程序 app.log 的时间窗切片]")
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "automas" / "debug").mkdir(parents=True)
        t0 = datetime(2026, 9, 18, 9, 54, 0)
        relay_log = t / "relay.log"
        relay_log.write_text(
            "09-18 09:40:00 INFO    ark.service  太早，不在窗内\n"
            "09-18 09:54:36 WARNING ark.handle  ⏳ MaaEnd 失败，暂不推送，等重试结果\n"
            "Traceback (most recent call last):\n"
            "  File \"x.py\", line 1\n"
            "09-18 10:30:00 INFO    ark.service  太晚，不在窗内\n", encoding="utf-8")
        (t / "automas" / "debug" / "app.log").write_text(
            "2026-09-18 09:20:00.000 | INFO | 早\n"
            "2026-09-18 09:54:35.100 | INFO | MaaEnd 自动代理 | 启动 MaaEnd\n"
            "2026-09-18 09:54:44.200 | WARNING | MaaEnd 自动代理 | 未捕获到日志\n"
            "2026-09-18 11:00:00.000 | INFO | 晚\n", encoding="utf-8")
        os.environ["ARK_LOG_FILE"] = str(relay_log)
        cfg = types.SimpleNamespace(automas_dir=t / "automas", state_dir=t / "state", maaend_dir=None, maa_dir=None, okww_dir=None, history_dir=None)
        win = (t0.timestamp(), (t0 + timedelta(minutes=12)).timestamp())
        files = evidence.context_files(cfg, win, t / "out")
        names = sorted(p.name for p in files)
        check("两个切片都在", names, ["automas-app.log", "relay.log"])
        rl = (t / "out" / "relay.log").read_text(encoding="utf-8")
        check("中继日志只留窗内的行，堆栈续行跟着", "09:54:36" in rl and "Traceback" in rl and "line 1" in rl and "太早" not in rl and "太晚" not in rl)
        al = (t / "out" / "automas-app.log").read_text(encoding="utf-8")
        check("调度程序日志只留窗内的行", "09:54:35" in al and "未捕获到日志" in al and "早" not in al.replace("早", "", 0) or ("09:20" not in al and "11:00" not in al))
        res = evidence.save_and_upload(cfg, "MaaEnd", "2026-09-18/endfield/MaaEnd-05-54-35", window=win)
        check("save_and_upload 的包里带上了两个切片", set(("relay.log", "automas-app.log")) <= set(res["files"]))
        check("没有 COS 时不炸、包照打", bool(res["archive"]))


def _part_maaend_bagfull():
    """An essence claim that never lands: a full bag when the storage-full notice was
seen, otherwise an ordinary failure that carries the raw MaaEnd lines.
    """
    #!/usr/bin/env python3

    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import collector_maaend as cm
    from ark_relay.core import texts
    from ark_relay.core import ledger as core
    from ark_relay.features.collector_maaend import CLAIM_UNCONFIRMED, parse_maaend_log
    from ark_relay.core.config import SERVER_TZ, RunRecord

    FIX = fx_dir(Path(__file__), "fixtures")
    FW_IN_WINDOW = (
        '[2026-09-24 10:16:40.100][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65]'
        '[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] '
        '[details={"action_id":500000076,"focus":null,"name":"AutoEssenceClaimConfirm","task_id":200000013}] \n'
        '[2026-09-24 10:16:40.101][INF][Px18500][Tx10532][Utils/EventDispatcher.hpp][L65]'
        '[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] '
        '[details={"action_id":500000076,"focus":null,"name":"AutoEssenceClaimConfirm","task_id":200000013}] \n'
        '[2026-09-24 10:16:45.000][DBG][Px7172][Tx32558][OCRer.cpp][L90][MaaNS::VisionNS::OCRer::analyze] noise\n'
        '[2026-09-24 10:20:00.000][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65]'
        '[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.Starting] later\n')

    def failure_text(raw: dict) -> str:
        t0 = datetime(2026, 9, 24, 10, 0, tzinfo=SERVER_TZ)
        r = RunRecord(run_id="2026-09-24/endfield/MaaEnd-06-07-50", script="MaaEnd", user="endfield",
                      started=t0, finished=t0, ok=False, failed_tasks=list(raw.get("tasks_failed") or []), raw=raw)
        return core.format_failure(r)[1]

    def main() -> None:
        end = tmpdir()
        (end / "debug").mkdir(parents=True)
        (end / "debug" / "maafw.log").write_bytes(
            (FIX / "maaend_bagfull_2026-09-25_maafw.log").read_bytes())
        r = parse_maaend_log(FIX / "maaend_bagfull_2026-09-25.log", end)
        causes = r.get("maaend_fail_causes") or {}
        require("the essence failure after the claim click is a full bag",
                causes == {"基质刷取": "背包满了"}, repr(causes))
        require("failure names stay unchanged (retries and alert keys match on them)",
                r.get("tasks_failed") == ["赠送干员礼物", "基质刷取", "日常奖励领取"],
                repr(r.get("tasks_failed")))
        line = core._fmt_failed(r["tasks_failed"], causes=causes)
        require("the alert line names the cause",
                line == "失败于：赠送干员礼物、基质刷取（背包满了）、日常奖励领取", line)
        advice = texts.known_cause(causes)
        require("the alert says to clear the bag", "清出背包空间" in advice, advice)
        require("the advice passes the plain-words gate", not texts.plain(advice),
                repr(texts.plain(advice)))
        require("a proven full bag carries no raw lines", not r.get("maaend_claim_lines"), repr(r.get("maaend_claim_lines")))

        print("[no storage-full notice: an ordinary failure, with the raw lines]")
        bare = parse_maaend_log(FIX / "maaend_bagfull_2026-09-25.log")
        require("without the framework log no cause is named (no softened 「unconfirmed」)",
                not bare.get("maaend_fail_causes"), repr(bare.get("maaend_fail_causes")))
        require("... and the failure is still a failure",
                "基质刷取" in (bare.get("tasks_failed") or []), repr(bare.get("tasks_failed")))
        claim = (bare.get("maaend_claim_lines") or {}).get("基质刷取") or {}
        require("the run log's lines from the click to the failure, verbatim",
                claim.get("run") == ["[2026-09-25 09:53:13.162] 👆点击确认领取按钮",
                                     "[2026-09-25 09:53:38.147] 任务失败: 🎱基质刷取"], repr(claim.get("run")))
        require("no MaaEnd folder: the framework part says why it is missing",
                (claim.get("fw"), claim.get("fw_why")) == ([], "没配终末地的目录"), repr(claim))
        body = failure_text(bare)
        require("the failure text names the task plainly", "· 失败于：赠送干员礼物、基质刷取、日常奖励领取" in body, body)
        require("... with no softened cause or bag advice",
                CLAIM_UNCONFIRMED not in body and "请看一眼背包" not in body and "也是这个样子" not in body, body)
        require("... and carries the raw lines", "[2026-09-25 09:53:13.162] 👆点击确认领取按钮" in body
                and "[2026-09-25 09:53:38.147] 任务失败: 🎱基质刷取" in body, body)

        empty = tmpdir()
        (empty / "debug").mkdir(parents=True)
        (empty / "debug" / "maafw.log").write_text("", encoding="utf-8")
        c24 = parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", empty)
        require("09-24: claim click then failure, no storage-full notice -> no cause",
                not c24.get("maaend_fail_causes"), repr(c24.get("maaend_fail_causes")))
        require("09-24: the essence failure is still reported",
                "基质刷取" in (c24.get("tasks_failed") or []), repr(c24.get("tasks_failed")))
        c24c = (c24.get("maaend_claim_lines") or {}).get("基质刷取") or {}
        require("09-24: the run log stretch starts at the click and ends at the failure",
                bool(c24c.get("run")) and "点击确认领取按钮" in c24c["run"][0] and "任务失败" in c24c["run"][-1],
                repr(c24c.get("run")))
        require("09-24: an empty framework log is said, not hidden",
                (c24c.get("fw"), c24c.get("fw_why")) == ([], "框架日志里这段时间没有记录"), repr(c24c))
        late = tmpdir()
        (late / "debug").mkdir(parents=True)
        (late / "debug" / "maafw.log").write_bytes(
            (FIX / "maaend_bagfull_2026-09-25_maafw.log").read_bytes())
        c24b = parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", late)
        require("a notice from another day's run does not count",
                not c24b.get("maaend_fail_causes"), repr(c24b.get("maaend_fail_causes")))

        print("[the framework log's lines of the same seconds go with it]")
        fwd = tmpdir()
        (fwd / "debug").mkdir(parents=True)
        (fwd / "debug" / "maafw.log").write_text(FW_IN_WINDOW, encoding="utf-8")
        cw = ((parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", fwd)
               .get("maaend_claim_lines") or {}).get("基质刷取") or {})
        fw = cw.get("fw") or []
        require("the event line inside the window, once (the second process's copy dropped)",
                len(fw) == 1 and "AutoEssenceClaimConfirm" in fw[0], repr(fw))
        require("stamp and level kept, process / thread / source brackets dropped",
                bool(fw) and fw[0].startswith("[2026-09-24 10:16:40.100][INF] !!!OnEventNotify!!!")
                and "Px7172" not in fw[0], repr(fw))
        require("lines after the failure are left out", not any("10:20:00" in x for x in fw), repr(fw))
        require("each line is cut to a length", all(len(x) <= 201 for x in fw), repr([len(x) for x in fw]))
        body = failure_text(parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", fwd))
        require("the failure text carries the framework line under its heading",
                texts.CLAIM_LINES_FW in body and "AutoEssenceClaimConfirm" in body, body)

        print("[a long stretch is capped: first and last lines, the count of the rest]")
        many = [f"[2026-09-24 10:16:{i:02d}.000] 第 {i} 行" for i in range(40)]
        capped = cm._cap(many)
        require("first and last lines kept, one line for the rest",
                capped[:cm.CLAIM_HEAD_LINES] == many[:cm.CLAIM_HEAD_LINES]
                and capped[-cm.CLAIM_TAIL_LINES:] == many[-cm.CLAIM_TAIL_LINES:]
                and capped[cm.CLAIM_HEAD_LINES] == texts.claim_lines_skipped(40 - cm.CLAIM_HEAD_LINES - cm.CLAIM_TAIL_LINES),
                repr(capped))

        ok = parse_maaend_log(FIX / "maaend_full_2026-09-01.log")
        require("a normal run has no causes", not ok.get("maaend_fail_causes"),
                repr(ok.get("maaend_fail_causes")))
        require("... and no claim lines", not ok.get("maaend_claim_lines"), repr(ok.get("maaend_claim_lines")))

    main()


def _part_maaend_bagfull_collect():
    """The 2026-09-25 full bag is still found by the collector on the machine."""
    #!/usr/bin/env python3

    import json
    import os

    os.environ.update(ARK_STATE_DIR=str(tmpdir()), ARK_AUTOMAS_DIR="", ARK_MAAEND_DIR="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import collector, texts
    from ark_relay.features import makeup
    from ark_relay.features import report
    from ark_relay.core import ledger as core
    from ark_relay.features.collector_maaend import BAG_FULL, CLAIM_UNCONFIRMED
    from ark_relay.core.config import Config
    from ark_relay.core.collector import LocalSource

    FIX = fx_dir(Path(__file__), "fixtures")
    STEM = "MaaEnd-05-47-21"

    def history() -> Path:
        root = tmpdir()
        d = root / "2026-09-25" / "endfield"
        d.mkdir(parents=True)
        (d / f"{STEM}.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: 🎱基质刷取"},
                                                   ensure_ascii=False), encoding="utf-8")
        (d / f"{STEM}.log").write_bytes((FIX / "maaend_bagfull_2026-09-25.log").read_bytes())
        return root

    def maaend(with_notice: bool) -> Path:
        root = tmpdir()
        (root / "debug").mkdir(parents=True)
        body = (FIX / "maaend_bagfull_2026-09-25_maafw.log").read_bytes() if with_notice else b""
        (root / "debug" / "maafw.log").write_bytes(body)
        return root

    def fetch(hist: Path, end: Path | None):
        cfg = Config()
        cfg.history_dir = hist
        cfg.maaend_dir = end
        recs = LocalSource(cfg).fetch(set())
        return recs[0] if len(recs) == 1 else None

    def main() -> None:
        print("[09-25 through the collector, MaaEnd folder from Config]")
        rec = fetch(history(), maaend(with_notice=True))
        require("one record", rec is not None)
        if rec is None:
            return
        causes = rec.raw.get("maaend_fail_causes") or {}
        require("still a failure", rec.ok is False and "基质刷取" in rec.failed_tasks,
                repr((rec.ok, rec.failed_tasks)))
        require("the full bag is found through the collector", causes.get("基质刷取") == BAG_FULL, repr(causes))
        require("the alarm text says to clear the bag", "清出背包空间" in texts.known_cause(causes),
                texts.known_cause(causes))
        bag_full = getattr(makeup, "bag_full", lambda c: None)
        require("the make-up clears the bag first", bag_full(causes) is True, repr(causes))

        print("[the same run when the framework log has no notice: an ordinary failure with its raw lines]")
        bare = fetch(history(), maaend(with_notice=False))
        bc = (bare.raw.get("maaend_fail_causes") or {}) if bare else {}
        require("still a failure", bare is not None and bare.ok is False and "基质刷取" in bare.failed_tasks)
        require("no cause is named (no softened 「unconfirmed」)", bc == {}, repr(bc))
        line = core._fmt_failed(bare.raw.get("tasks_failed") or [], causes=bc) if bare else ""
        require("the alert line is the plain failure", line == "失败于：赠送干员礼物、基质刷取、日常奖励领取", line)
        require("no bag advice", texts.known_cause(bc) == "", texts.known_cause(bc))
        claim = ((bare.raw.get("maaend_claim_lines") or {}).get("基质刷取") or {}) if bare else {}
        require("the raw run-log lines travel with the record",
                claim.get("run") == ["[2026-09-25 09:53:13.162] 👆点击确认领取按钮",
                                     "[2026-09-25 09:53:38.147] 任务失败: 🎱基质刷取"], repr(claim))
        _, body = core.format_failure(bare) if bare else ("", "")
        require("... and reach the failure text", "[2026-09-25 09:53:13.162] 👆点击确认领取按钮" in body, body)
        require("the make-up does not clear the bag without the notice", bag_full(bc) is False, repr(bc))
        nodir = fetch(history(), None)
        require("no MaaEnd folder at all: still a failure, raw lines attached, no cause",
                nodir is not None and not nodir.raw.get("maaend_fail_causes")
                and bool(((nodir.raw.get("maaend_claim_lines") or {}).get("基质刷取") or {}).get("run")))
        old = {"基质刷取": CLAIM_UNCONFIRMED}
        require("a ledger line from before 2026-10-06 is shown as a plain failure too",
                (core._fmt_failed(["基质刷取"], causes=old), texts.known_cause(old)) == ("失败于：基质刷取", ""),
                repr((core._fmt_failed(["基质刷取"], causes=old), texts.known_cause(old))))

        print("[evening recompute (report): a proven full bag is not downgraded]")
        hist = history()
        entry = {"run_id": f"2026-09-25/endfield/{STEM}", "script": "MaaEnd", "ok": False,
                 "failed_tasks": ["基质刷取"], "raw": {"maaend_fail_causes": {"基质刷取": BAG_FULL}}}
        later = collector.refresh_raw(entry, hist, maaend(with_notice=False))
        require("debug folder wiped since: still 背包满了",
                (later["raw"].get("maaend_fail_causes") or {}).get("基质刷取") == BAG_FULL, repr(later["raw"]))
        fresh = collector.refresh_raw(dict(entry, raw={}), hist, maaend(with_notice=True))
        require("an old entry without the cause gets it from the framework log",
                (fresh["raw"].get("maaend_fail_causes") or {}).get("基质刷取") == BAG_FULL, repr(fresh["raw"]))

        # The daily report's recompute hands the MaaEnd folder on.
        seen: list = []

        class Stop(Exception):
            pass

        def spy(e, hist_dir, end_dir=None):
            seen.append(end_dir)
            raise Stop

        class Eng:
            cfg = Config()

        Eng.cfg.history_dir = hist
        Eng.cfg.maaend_dir = Path("/maaend")
        real, collector.refresh_raw = collector.refresh_raw, spy
        try:
            report._compose_daily(Eng(), "2026-09-25", [entry])
        except Stop:
            pass
        finally:
            collector.refresh_raw = real
        require("the daily report recomputes with the MaaEnd folder", seen == [Path("/maaend")], repr(seen))

    main()


def _part_maaend_close_game_wrapup():
    """关闭游戏（PC） is the round's wrap-up step, not a daily task."""
    #!/usr/bin/env python3
    import json
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger as ledger_report, ledger as ledger_rows
    from ark_relay.core.config import SERVER_TZ

    e = json.loads((fx_dir(Path(__file__), "fixtures") / "ledger-1012-maaend-close-game.jsonl").read_text(encoding="utf-8"))
    raw = e["raw"]
    check("not unverified", ledger_rows.maaend_unverified(raw), [])
    check("not listed", ledger_rows._maaend_listed(raw), ["日常奖励领取"])
    notes = ledger_rows._block_maaend(e, raw, datetime(2026, 10, 12, 18, 28, tzinfo=SERVER_TZ))[4]
    check("notes name the daily task only", notes, ["做了 日常奖励领取"])

    gather = {"ok": True}
    graw = {"maaend_collect_skipped": "周日", "tasks_done": ["自动采集", "关闭游戏（PC）"]}
    check("gathering-only with 关闭游戏", ledger_report._skipped_gathering_only(gather, graw), True)


def _part_maaend_collect_items_v236():
    """MaaEnd v2.36.0-beta.5 picks 自动采集 by item, not by route (installed 2026-10-29 10:27 Beijing).
    """
    import json
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import mastercfg
    from ark_relay.features import collect_retry as cr
    from ark_relay.features import collector_maaend as cm, outcome

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-10-29"

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        maaend = d / "maaend"
        (maaend / "tasks").mkdir(parents=True)
        (maaend / "locales" / "interface").mkdir(parents=True)
        (maaend / "tasks" / "AutoCollect.json").write_bytes((FIX / "tasks" / "AutoCollect.json").read_bytes())
        (maaend / "locales" / "interface" / "zh_cn.json").write_bytes(
            (FIX / "locales" / "interface" / "zh_cn.json").read_bytes())
        (maaend / "interface.json").write_text(json.dumps({"import": ["tasks/AutoCollect.json"]}), encoding="utf-8")
        automas = d / "automas"
        cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfgdir.mkdir(parents=True)
        master = cfgdir / "mxu-MaaEnd.json"
        old = {
            "AutoCollectValleyIV": {"type": "switch", "value": True},
            "AutoCollectValleyIVRareRoutes": {"type": "checkbox", "caseNames": ["Route4", "Route13"]},
            "AutoCollectValleyIVCommonRoutes": {"type": "checkbox", "caseNames": ["CommonRoute1"]},
            "AutoCollectWuling": {"type": "switch", "value": True},
            "AutoCollectWulingRareRoutes": {"type": "checkbox", "caseNames": ["Route7", "Route15", "Route99"]},
            "AutoCollectWulingCommonRoutes": {"type": "checkbox", "caseNames": ["CommonRoute5"]},
            "AutoCollectMode": {"type": "select", "caseName": "Always"},
        }
        master.write_text(json.dumps({"instances": [{"tasks": [
            {"taskName": "AutoCollect", "enabled": True, "optionValues": old}]}]}), encoding="utf-8")

        changes, note = mastercfg.migrate_maaend_options(automas, maaend)
        print("\n".join("    " + c for c in changes))
        ov = json.loads(master.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["optionValues"]
        check("四号谷地稀有：路线4、13 → 纯晶多齿叶、中黯石",
              ov.get("AutoCollectValleyIVRareItems", {}).get("caseNames"),
              ["item_plant_crylplant_1_2", "item_plant_spcstone_1_2"])
        check("四号谷地一般：线路1 → 映火荞花", ov.get("AutoCollectValleyIVCommonItems", {}).get("caseNames"),
              ["item_plant_moss_spc_1"])
        check("武陵稀有：路线7 → 血菌和武陵石两样，路线15 → 红矛叶",
              ov.get("AutoCollectWulingRareItems", {}).get("caseNames"),
              ["item_plant_mushroom_2_1", "item_plant_spcstone_2_2", "item_plant_crylplant_2_3"])
        check("武陵一般：线路5 → 蓬茸锦草", ov.get("AutoCollectWulingCommonItems", {}).get("caseNames"),
              ["item_plant_grass_spc_1"])
        check("旧的路线项都去掉了", [k for k in ov if k.endswith("Routes")], [])
        check("对不上的路线（Route99）在说明里点了名", any("Route99" in c for c in changes))
        check("区域开关和模式原样留着", (ov["AutoCollectValleyIV"], ov["AutoCollectMode"]["caseName"]),
              ({"type": "switch", "value": True}, "Always"))

        r = mastercfg.read_maaend(automas, maaend)
        A = "AutoCollect/"
        for k in ("AutoCollectValleyIVRareItems", "AutoCollectValleyIVCommonItems",
                  "AutoCollectWulingRareItems", "AutoCollectWulingCommonItems"):
            check(f"手机页有 {k}，中文名", any("一" <= ch <= "鿿" for ch in r["labels"].get(A + k, "")))
        check("手机页没有没翻译的项", [k for k in r.get("untranslated", []) if k.startswith(A)], [])
        names = dict((v, n) for n, v in r["options"][A + "AutoCollectWulingRareItems"])
        check("武陵稀有的可选值带中文名", (names.get("item_plant_mushroom_2_1"), names.get("item_plant_spcstone_2_2")),
              ("血菌", "武陵石"))

        zh = json.loads((FIX / "locales" / "interface" / "zh_cn.json").read_text(encoding="utf-8"))
        labels = cr.failed_labels_from_locale(zh)
        check("补跑认得新版失败提示", labels.get("纯晶多齿叶采集失败"), "AutoCollectValleyIVChrysodendra1")
        check("两样一条路线的也认得", labels.get("血菌、武陵石采集失败"), "AutoCollectWulingBloodcapWulingstone1")
        log = "[12:00:01] 纯晶多齿叶采集失败\n[12:03:00] 轻黯石采集失败\n[12:05:00] 星门菌采集失败\n"
        check("从日志里挑出失败的路线", cr.failed_routes(log, labels),
              ["AutoCollectValleyIVChrysodendra1", "AutoCollectValleyIVKalkonyx1", "AutoCollectWulingCosmagaric1"])
        parts = [{
            "__AutoCollectValleyIVChrysodendraDispatch": {"enabled": True},
            "__AutoCollectValleyIVChrysodendraSkipped": {"enabled": True},
            "AutoCollectValleyIVChrysodendra1Start": {"enabled": True},
            "__AutoCollectWulingCrimsonSpearleafDispatch": {"enabled": True},
            "__AutoCollectWulingCrimsonSpearleafSkipped": {"enabled": True},
            "AutoCollectWulingCrimsonSpearleaf1Start": {"enabled": True},
            "AutoCollectScheduleEnabled": {"attach": {"monday": True}},
        }]
        o = cr.build_override(parts, ["AutoCollectValleyIVChrysodendra1"], "thursday")
        check("补跑只留失败那样的调度和路线",
              sorted(k for k in o if "Chrysodendra" in k or "CrimsonSpearleaf" in k),
              ["AutoCollectValleyIVChrysodendra1Start", "__AutoCollectValleyIVChrysodendraDispatch",
               "__AutoCollectValleyIVChrysodendraSkipped"])
        check("今天是采集日", o["AutoCollectScheduleEnabled"]["attach"].get("thursday"), True)
        o2 = cr.build_override([{}], ["AutoCollectWulingCosmagaric1"], "thursday")
        check("日志里没有的那样也会补上调度入口", (o2.get("__AutoCollectWulingCosmagaricDispatch"),
                                             o2.get("AutoCollectWulingCosmagaric1Start")),
              ({"enabled": True}, {"enabled": True}))
        mf = ('[2026-10-29 12:00:00.000][INF] [msg=Node.Action.Starting] {"name":"__AutoCollectValleyIVChrysodendra1Failed"}\n'
              '[2026-10-29 12:00:05.000][INF] [msg=Node.Action.Starting] {"name":"AutoCollectWulingCosmagaric1End"}\n')
        check("补跑结论认新版节点", cr.judge(mf, ["AutoCollectValleyIVChrysodendra1", "AutoCollectWulingCosmagaric1"],
                                         "00:00:00"),
              {"AutoCollectValleyIVChrysodendra1": False, "AutoCollectWulingCosmagaric1": True})

        log_1102 = "\n".join([
            "[2026-11-02 10:37:28.880] 开始执行任务, 数量: 1",
            "[2026-11-02 11:02:29.664] 任务开始: 🧺自动采集",
            "[2026-11-02 11:02:29.665] 正在前往四号谷地扫描拥有物资",
            "[2026-11-02 11:02:51.970] 正在前往武陵扫描拥有物资",
            "[2026-11-02 11:03:04.220] 仓库库存同步完成，开始按目标库存筛选采集物",
            "[2026-11-02 11:03:05.320] 采集纯晶多齿叶",
            "[2026-11-02 11:04:52.668] 采集轻黯石",
            "[2026-11-02 11:06:37.493] 采集轻红柱状菌",
            "[2026-11-02 11:07:39.258] 采集中黯石",
            "[2026-11-02 11:10:23.899] 采集晶化多齿叶",
            "[2026-11-02 11:11:23.671] 采集受蚀玉化叶",
            "[2026-11-02 11:13:02.786] 采集至晶多齿叶",
            "[2026-11-02 11:14:00.095] 采集血菌、武陵石",
            "[2026-11-02 11:17:37.438] 采集星门菌",
            "[2026-11-02 11:18:54.406] 采集燎石",
            "[2026-11-02 11:20:59.443] 采集重红柱状菌",
            "[2026-11-02 11:22:42.233] 采集重黯石",
            "[2026-11-02 11:24:21.668] 采集中红柱状菌",
            "[2026-11-02 11:25:10.574] 采集红矛叶",
            "[2026-11-02 11:26:26.877] 采集协议纹石",
            "[2026-11-02 11:28:24.733] 采集塔罗斯菌",
            "[2026-11-02 11:30:03.197] 任务完成: 🧺自动采集",
            "[2026-11-02 11:31:57.991] 自动执行任务完成",
        ])
        checks = {c.label: c.ok for c in outcome.maaend_checks(log_1102, [], own_log=True)}
        check("11-02 早班 16 条新版采集路线判为「自动采集 真的走了路线」", checks.get("自动采集 真的走了路线"), True)
        log_p = d / "0.log"
        log_p.write_text(log_1102, encoding="utf-8")
        parsed = cm.parse_maaend_log(log_p)
        check("11-02 早班路线计数 16/16", (parsed.get("maaend_collect_done"), parsed.get("maaend_collect_total")), (16, 16))

        shot = "2026.11.02-11.21.15.123___MapNavigatorObstacleDevice_InteractPost.png"
        check("新版路线撞上中继器能对上路线 ID",
              cr.blocked_route_ids(log_1102, [shot], zh),
              {"AutoCollectWulingRubyBolete1": [shot]})
        mf_blocked = (
            '[2026-11-02 11:20:59.400][INF] [msg=Node.Recognition.Succeeded] {"name":"AutoCollectWulingRubyBolete1Start"}\n'
            '[2026-11-02 11:22:40.000][INF] [msg=Node.Action.Starting] {"name":"AutoCollectWulingRubyBolete1End"}\n'
        )
        check("补跑复查认得新版路线节点窗口",
              cr.retry_blocked(mf_blocked, ["AutoCollectWulingRubyBolete1"], "11:00:00", [shot]),
              {"AutoCollectWulingRubyBolete1": [shot]})


def _part_maaend_collect_xianlu():
    """自动采集 walking only routes 1-3 is work done, not a false green."""
    #!/usr/bin/env python3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.outcome import maaend_checks

    text = (fx_dir(Path(__file__), "fixtures") / "maaend-collect-xianlu-1012.log").read_text(encoding="utf-8")
    got = {c.label: c.ok for c in maaend_checks(text, []) if "自动采集" in c.label}
    check("线路1-3 count as walked routes", got.get("自动采集 真的走了路线") is True, True)


def _part_maaend_farm_drops():
    """MaaEnd farming drops read from its 「获得以下物品：」 blocks (2026-09-29)."""
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.features import collector_maaend

    D = fx_dir(pathlib.Path(__file__), "fixtures") / "maaend-farm-drops"

    def farm(name):
        return collector_maaend._maaend_farm((D / name).read_text(encoding="utf-8"))

    def pick(d):
        """Farm name, place, runs and drops. Sanity is checked separately below,
    only for the Protocol Space logs, where it was worked out by hand."""
        keys = ("maaend_farm", "maaend_farm_place", "maaend_farm_runs", "maaend_farm_drops")
        return {k: d[k] for k in keys if k in d}

    def sanity(name):
        r = collector_maaend.parse_maaend_log(D / name)
        return {k: r.get(k) for k in ("maaend_sanity_spent", "sanity", "sanity_cap", "protocol_runs")}

    check("09-27 协议空间", pick(farm("2026-09-27.log")),
        {"maaend_farm": "协议空间", "maaend_farm_runs": 1,
         "maaend_farm_drops": {"折金票": 68000, "行动资历": 960}})
    check("09-27 理智", sanity("2026-09-27.log"),
        {"maaend_sanity_spent": 160, "sanity": 117, "sanity_cap": 360, "protocol_runs": 2})

    check("09-28a 协议空间", pick(farm("2026-09-28a.log")),
        {"maaend_farm": "协议空间", "maaend_farm_runs": 2,
         "maaend_farm_drops": {"折金票": 136000, "行动资历": 1920}})
    check("09-28a 理智", sanity("2026-09-28a.log"),
        {"maaend_sanity_spent": 320, "sanity": 6, "sanity_cap": 360, "protocol_runs": 2})

    r = farm("2026-09-28b.log")
    check("09-28b 没进去", pick(r), {"maaend_farm": "协议空间"})
    full = collector_maaend.parse_maaend_log(D / "2026-09-28b.log")
    check("09-28b 次数", full.get("maaend_farm_runs"), None)
    check("09-28b 产出", full.get("maaend_farm_drops"), None)
    check("09-28b 理智不足", full.get("sanity_exhausted"), True)
    check("09-28b 理智", sanity("2026-09-28b.log"),
        {"maaend_sanity_spent": None, "sanity": 17, "sanity_cap": 360, "protocol_runs": None})

    check("09-24 基质刷取", pick(farm("2026-09-24_MaaEnd-06-07-50.log")),
        {"maaend_farm": "基质刷取", "maaend_farm_place": "清波寨", "maaend_farm_runs": 2,
         "maaend_farm_drops": {"无暇基质": 6, "高纯基质": 4}})

    check("09-25 基质刷取 背包满", pick(farm("2026-09-25_MaaEnd-05-25-36.log")),
        {"maaend_farm": "基质刷取", "maaend_farm_place": "清波寨"})

    whole = collector_maaend._item_blocks((D / "2026-09-27.log").read_text(encoding="utf-8").splitlines())
    check("09-27 全日 信用", whole.get("信用"), 20 + 400 + 300)
    check("09-27 全日 武库配额", whole.get("武库配额"), 80)
    check("09-27 产出不含信用", "信用" in (farm("2026-09-27.log").get("maaend_farm_drops") or {}), False)

    # Not tied to the task name: the same log with the task renamed is still read
    # as the farming task because its own lines carry 「当前理智 N/M」.
    t27 = (D / "2026-09-27.log").read_text(encoding="utf-8")
    renamed = t27.replace("⚔️协议空间", "⚔️某新理智玩法")
    check("改名 仍认", pick(collector_maaend._maaend_farm(renamed)),
        {"maaend_farm": "某新理智玩法", "maaend_farm_runs": 1,
         "maaend_farm_drops": {"折金票": 68000, "行动资历": 960}})
    # Renamed and without the sanity readings: no farming task at all, and the
    # 基建任务 / 信用点购物 blocks do not turn into one.
    bare = "\n".join(x for x in renamed.splitlines() if "当前理智" not in x)
    check("改名无理智行 不认", collector_maaend._maaend_farm(bare), {})

    # Block boundary: the first non-item line closes it, even at the same
    # timestamp; a framework line closes it too.
    lines = [
        "[2026-09-27 09:46:37.319] 获得以下物品：",
        "[2026-09-27 09:46:37.319] 折金票 ×68000",
        "[2026-09-27 09:46:37.319] 继续行动",
        "[2026-09-27 09:46:37.319] 行动资历 ×960",
        "[2026-09-27 09:46:38.000] 获得以下物品：",
        "[2026-09-27 09:46:38.000] 信用 ×20",
        "[2026-09-27 09:46:38.001][ERR][Px1][Tx1][A.cpp][L1][f] size x 16",
        "[2026-09-27 09:46:38.002] 信用 ×400",
    ]
    check("块边界", collector_maaend._item_blocks(lines), {"折金票": 68000, "信用": 20})


def _part_maaend_two_farms():
    """Both sanity tasks in one round are both read."""
    #!/usr/bin/env python3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import collector_maaend as cm

    D = fx_dir(Path(__file__), "fixtures") / "maaend-farm-drops"

    def _task(path: Path, key: str) -> str:
        lines = path.read_text(encoding="utf-8").splitlines()
        a = next(i for i, x in enumerate(lines) if "任务开始" in x and key in x)
        b = next(i for i, x in enumerate(lines) if i > a and ("任务完成" in x or "任务失败" in x) and key in x)
        return "\n".join(lines[a:b + 1]) + "\n"

    def main() -> None:
        ps = _task(D / "2026-09-27.log", "协议空间")
        ess = _task(D / "2026-09-24_MaaEnd-06-07-50.log", "基质刷取")
        one_ps, one_ess = cm._maaend_farm(ps), cm._maaend_farm(ess)
        both = cm._maaend_farm(ps + ess)
        require("each part alone farmed something", one_ps.get("maaend_farm_runs") and one_ess.get("maaend_farm_runs"),
                repr((one_ps, one_ess)))
        require("both tasks are named", both.get("maaend_farm") == "协议空间、基质刷取", repr(both.get("maaend_farm")))
        require("runs add up", both.get("maaend_farm_runs") ==
                one_ps["maaend_farm_runs"] + one_ess["maaend_farm_runs"], repr(both.get("maaend_farm_runs")))
        want = dict(one_ps.get("maaend_farm_drops") or {})
        for k, n in (one_ess.get("maaend_farm_drops") or {}).items():
            want[k] = want.get(k, 0) + n
        require("drops of both are kept", both.get("maaend_farm_drops") == want, repr(both.get("maaend_farm_drops")))
        require("a single task reads as before", cm._maaend_farm(ps) == one_ps)

    main()


def _part_unreachable_evidence():
    """「进不了游戏」needs official evidence; the log's shape alone silences nothing."""
    import json
    import logging
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    from ark_relay.core import collector, texts
    from ark_relay.features import gameupdate
    from ark_relay.features import handle
    from ark_relay.features import makeup
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State

    FIX = fx_dir(ROOT, "fixtures") / "maaend_shape_local_fault_2026-09-25.log"

    DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    START = DAY.replace(hour=9, minute=55)

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = None
        cfg.maa_dir = None
        cfg.maaend_dir = tmpdir()
        (Path(cfg.maaend_dir) / "debug").mkdir()
        e = eng_mod.Engine(cfg, source=_NoSource(), state=State(cfg.state_dir), notifier=_Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        e._verify_outcome = lambda r: None
        e._maintenance_today = lambda game: False
        return e

    handle._ship_evidence = lambda eng, rec: ""
    makeup._dispatch = lambda script: (True, "已开跑")
    makeup._kill_game = lambda: None

    def rec_from_fixture():
        raw = collector.parse_maaend_log(FIX)
        return RunRecord(run_id=f"{START:%Y-%m-%d}/endfield/MaaEnd-{START:%H-%M-%S}", script="MaaEnd",
                         user="endfield", started=START, finished=START + timedelta(minutes=4), ok=False,
                         failed_tasks=["🎁赠送干员礼物", "🎱基质刷取", "📅日常奖励领取"], raw=raw)

    def ledger_raw(e, r):
        p = Path(e.cfg.state_dir) / f"ledger-{START:%Y-%m-%d}.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            ent = json.loads(line)
            if ent.get("run_id") == r.run_id:
                return ent.get("raw") or {}
        return None

    def cant_enter_sent(e):
        return any(t == texts.cant_enter("MaaEnd") for t, _b, _a in e.notifier.sent)

    check("反例日志确实是「秒败、零完成」的形状", collector.maaend_unreachable(FIX.read_text(encoding="utf-8")), True)

    print("[形状有、没有官方维护也没有更新公告 → 普通故障]")
    handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: ""
    e = build()
    r = rec_from_fixture()

    loud = _Lines(logging.WARNING)
    handle.log.addHandler(loud)
    handle._handle(e, r)
    handle.log.removeHandler(loud)
    check("held failure: no 「像没进游戏」 WARNING (errwatch would push it now)",
          [m for m in loud.lines if "像没进游戏" in m], [])
    check("压着等补跑", ("MaaEnd", "endfield") in e._pending)
    check("不记成进不了游戏", r.raw.get("maaend_unreachable"), None)
    check("账本上也不是进不了游戏", (ledger_raw(e, r) or {}).get("maaend_unreachable"), None)
    check("补跑有份", makeup.eligible(r), True)
    check("没登记客户端待更新", gameupdate.pending(e.cfg.state_dir), {})
    e._flush_pending()
    check("没发「进不了游戏」的说明", cant_enter_sent(e), False)
    check("没被当维护丢掉（还压着等补跑）", ("MaaEnd", "endfield") in e._pending)
    # The make-up did not fix it: the alarm goes to the group and names the shape.
    handle._push_unresolved(e, r, "补跑也没成", 1)
    body = e.notifier.sent[-1][1] if e.notifier.sent else ""
    check("报警里说了像没进游戏、按故障报", "像没进游戏" in body and "按故障报" in body, True)

    print("[形状有、公告读不到 → 普通故障，但记下「没读到」，不说成「没有公告」（审计 10-13 s1 #3）]")

    def hint_unreadable(now=None, fetch=None, strict=False):
        # efstatus.update_hint's own contract: "" on a failed read unless strict.
        if strict:
            raise OSError("notice page unreachable")
        return ""

    handle.efstatus.update_hint = hint_unreadable
    e = build()
    r = rec_from_fixture()
    handle._handle(e, r)
    check("还是普通故障", r.raw.get("maaend_unreachable"), None)
    check("记下公告没读到", r.raw.get("maaend_unreachable_unread"), True)
    check("账本上也记着", (ledger_raw(e, r) or {}).get("maaend_unreachable_unread"), True)
    check("没读到的说法不说「没有公告」", "没有官方" in getattr(texts, "UNREACHABLE_UNREAD_NOTE", "没有官方"), False)
    handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: ""
    e = build()
    r = rec_from_fixture()
    handle._handle(e, r)
    check("读到了、确实没有公告：不记没读到", r.raw.get("maaend_unreachable_unread"), None)

    print("[形状有 + 官方维护窗口 → 不补跑，进群一条，写明官方依据（2026-10-06 起）]")
    e = build()
    gameupdate._store(e.cfg.state_dir).set("updates", "maintenance_windows", {"终末地": {
        "start": DAY.replace(hour=6).isoformat(), "end": DAY.replace(hour=10).isoformat(),
        "why": "官方公告：06:00–10:00 停服维护"}})
    r = rec_from_fixture()
    handle._handle(e, r)
    check("记成进不了游戏", r.raw.get("maaend_unreachable"), True)
    check("账本上也是", (ledger_raw(e, r) or {}).get("maaend_unreachable"), True)
    check("补跑没份", makeup.eligible(r), False)
    check("登记了客户端待更新", "终末地" in gameupdate.pending(e.cfg.state_dir))
    e._flush_pending()
    check("进群一条「进不了游戏」", [t for t, _b, a in e.notifier.sent if a], [texts.cant_enter("MaaEnd")])
    check("…写着官方依据", any("官方依据：官方公告：06:00–10:00 停服维护" in b for t, b, a in e.notifier.sent if a), True)
    check("不再压着", dict(e._pending), {})
    e._flush_pending()
    check("下一轮不再推", len([t for t, _b, a in e.notifier.sent if a]), 1)

    print("[形状有 + 官方更新公告 → 不补跑，进群一条，写明那条公告]")
    handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: "官方公告：今天 10:00 「雪凇幽梦」版本更新"
    e = build()
    r = rec_from_fixture()
    handle._handle(e, r)
    check("记成进不了游戏", r.raw.get("maaend_unreachable"), True)
    check("补跑没份", makeup.eligible(r), False)
    e._flush_pending()
    check("进群一条「进不了游戏」", [t for t, _b, a in e.notifier.sent if a], [texts.cant_enter("MaaEnd")])
    check("…写着那条官方公告", any("官方依据：官方公告：今天 10:00 「雪凇幽梦」版本更新" in b
                              for t, b, a in e.notifier.sent if a), True)

    print("[形状有、公告没读到 → 报警用「没读到公告」那句，不说今天没有公告]")
    UNREAD = "（测试）官方公告没读到"
    texts.UNREACHABLE_UNREAD_NOTE = UNREAD
    e = build()
    r = rec_from_fixture()
    r.raw["maaend_unreachable_shape"] = True
    r.raw["maaend_unreachable_unread"] = True
    handle._push_unresolved(e, r, "补跑也没成", 1)
    body = e.notifier.sent[-1][1] if e.notifier.sent else ""
    check("用了没读到公告那句", UNREAD in body, True)
    check("没说今天没有公告", texts.UNREACHABLE_SHAPE_NOTE in body, False)


def _part_unreachable_note_pushed_now():
    """The 「像没进游戏」 note is on every MaaEnd failure alarm, not only the held one."""
    import os
    from datetime import datetime, timedelta

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                      ARK_AUTOMAS_DIR=str(TMP / "nowhere"), ARK_MAAEND_DIR="", SERVERCHAN_KEY="",
                      ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng_mod
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features import handle

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return []

    handle._ship_evidence = lambda eng, r: ""
    handle._weekly_gates = lambda eng, r: None
    handle.efstatus.update_hint = lambda now=None, fetch=None, strict=False: ""   # no official notice today
    WHO = {"hand": ("", "task-hand"), "stop": ("06:10 停一切", "")}

    def build(state_dir):
        cfg = Config()
        cfg.state_dir = state_dir
        cfg.maaend_dir = None
        e = eng_mod.Engine(cfg, source=_NoSource(), state=State(state_dir), notifier=Notes())
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
        e._flush_pending()   # a hand-started failure waits for its task's retries (handle._hold_hand_started)
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
    e._flush_pending()
    body = (e.notifier.sent or [("", "")])[0][1]
    check("写了「没读到」", texts.UNREACHABLE_UNREAD_NOTE in body)
    check("不写「今天没有官方公告」", texts.UNREACHABLE_SHAPE_NOTE in body, False)


if __name__ == "__main__":
    sys.exit(run_parts([_part_mc28_settle_once, _part_mc28_state, _part_mc28_task_trail, _part_mc28_one_alarm, _part_maaend_app_log, _part_maaend_dir_resolve, _part_maaend_false_green, _part_maaend_logged_out, _part_maaend_agreement, _part_maaend_recovered, _part_maaend_reenable, _part_maaend_stopped_between_tasks, _part_maaend_stub_record, _part_maaend_bagfull, _part_maaend_bagfull_collect, _part_maaend_close_game_wrapup, _part_maaend_collect_items_v236, _part_maaend_collect_xianlu, _part_maaend_farm_drops, _part_maaend_two_farms, _part_unreachable_evidence, _part_unreachable_note_pushed_now]))
