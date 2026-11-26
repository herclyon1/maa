"""Pre-shift updates, game client updates, Endfield windowed launch, and AUTO-MAS contract."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)
# relay/ first for every part, as each part used to put it (run_parts restores sys.path after one)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub_win32(*names: str) -> None:
    """Stand-ins for the Windows-only modules the relay imports (pywin32, wmi, ...) on the Mac:
    any attribute of one is a callable returning another stand-in. setdefault: a module already
    in sys.modules stays; run_parts drops what a part added once the part is over."""
    import types

    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()

    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any

    for name in names:
        sys.modules.setdefault(name, _Stub(name))


def _part_preupdate_main():
    """When the boot-window pre-update is wanted: only before a queue still to come
today that runs OK-WW, the one program it still launches (its update overwrites
the local patches, re-applied right after). MaaEnd's own update is AUTO-MAS's
job since the 2026-10-11 switch-over. The launching itself is Windows-only.
    """
    import json, os
    from datetime import datetime

    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)

    def write_schedule(*queues):
        """queues: (name, time, [script kinds])"""
        q, s, insts, sinsts = {}, {}, [], []
        for i, (name, t, kinds) in enumerate(queues):
            quid = f"q{i}"
            insts.append({"uid": quid})
            items = {}
            for j, kind in enumerate(kinds):
                suid = f"s{i}{j}"
                sinsts.append({"uid": suid})
                path = {"MaaEnd": "D:\\ark\\MaaEnd", "OK-WW": "D:\\ark\\okww"}.get(
                    kind, "D:\\MAA-v5.1.0-win-x64")
                s[suid] = {"Info": {"Name": kind, "Path": path},
                           "SubConfigsInfo": {"UserData": {}}}
                items[f"i{j}"] = {"Info": {"ScriptId": suid}}
            q[quid] = {"Info": {"Name": name, "TimeEnabled": True},
                       "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                          "QueueItem": items}}
        q["instances"] = insts; s["instances"] = sinsts
        (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(q), encoding="utf-8")
        (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(s), encoding="utf-8")

    os.environ.update(ARK_HISTORY_DIR=str(TMP), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="")
    from ark_relay.features import preupdate
    from ark_relay.core.config import SERVER_TZ


    def at(hh, mm):
        return datetime(2026, 8, 22, hh, mm, tzinfo=SERVER_TZ)

    print("[when to pre-update]")
    write_schedule(("新队列", "09:00", ["MAA", "OK-WW", "MaaEnd"]),
                   ("Evening-MAA", "21:30", ["MAA"]))
    check("08:47, morning queue still ahead", preupdate.wanted_today(AUTOMAS, at(8, 47)), True)
    check("21:22, only MAA left tonight",     preupdate.wanted_today(AUTOMAS, at(21, 22)), False)
    check("11:00, morning queue已过",          preupdate.wanted_today(AUTOMAS, at(11, 0)), False)

    write_schedule(("Evening-Both", "21:30", ["MAA", "OK-WW"]))
    check("evening queue does run OK-WW",     preupdate.wanted_today(AUTOMAS, at(21, 22)), True)

    write_schedule(("新队列", "09:00", ["MAA", "MaaEnd"]))
    check("no OK-WW anywhere",                preupdate.wanted_today(AUTOMAS, at(8, 47)), False)
    check("…but asked for MaaEnd it is there", preupdate.wanted_today(AUTOMAS, at(8, 47), kind="MaaEnd"), True)
    check("no AUTO-MAS dir",                  preupdate.wanted_today(None, at(8, 47)), False)


def _part_preupdate_automas_carry():
    """An AUTO-MAS install the first try could not see land, found landed by the second try
(audit 11-08 A-20; dispatch relay-opt-round4-1108 R4-04; preupdate_automas.run_automas `carry`).
    """
    import logging
    import types

    import boot_stages
    from ark_relay.features import errwatch
    from ark_relay.features import preupdate as P


    class Rows(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, bool(getattr(record, errwatch.RECOVERED, False)), record.getMessage()))


    class Machine:
        """AUTO-MAS v1 with v2 on offer. The install's own wait never sees v2; when `lands`, the
    backend reports v2 from the end of that wait on (the 155 s case), else stays on v1."""

        def __init__(self, lands):
            self.lands, self.installed, self.waited = lands, False, False

        def live(self):
            return "v2" if self.lands and self.installed and self.waited else "v1"

        def wait(self, want, deadline, stopping=None):
            self.waited = self.installed
            return "v1"

        def post(self, path, body=None):
            if path == "/api/update/install":
                self.installed = True
            if path == "/api/update/check":
                return {"code": 200, "if_need_update": self.live() != "v2", "latest_version": "v2"}
            return {"code": 200}


    saved = (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version,
             boot_stages._seconds_to_next_queue, boot_stages._stop_requested)
    rows = Rows()
    lg = logging.getLogger("ark.test_preupdate")
    lg.handlers[:] = [rows]
    lg.setLevel(logging.DEBUG)
    lg.propagate = False


    def run(lands, carry=True):
        m = Machine(lands)
        P._mas_post, P._live_version = m.post, m.live
        P._automas_version = lambda root: "v1"
        P._wait_for_package = lambda root, deadline, stopping=None: Path("AUTO-MAS-v2.zip")
        P._wait_for_version = m.wait
        boot_stages._seconds_to_next_queue = lambda d, now: 3600.0
        boot_stages._stop_requested = lambda: False
        rows.rows.clear()
        problems, after = [], []
        box: dict = {}
        out = boot_stages._once_more(types.SimpleNamespace(automas_dir="x"), lg, "AUTO-MAS", 1.0, problems,
                                     lambda problems: P.run_automas(Path("x"), budget_s=1.0, problems=problems,
                                                                    after_update=after.append,
                                                                    **({"carry": box} if carry else {})))
        return out, problems, after, [(lv, r) for lv, r, _ in rows.rows if lv != "INFO"]


    try:
        print("[第一次点了安装、没等到新版；第二次看到已经是新版：说已更新，补做更新后的核对]")
        out, problems, after, logged = run(lands=True)
        check("说已更新（旧 → 新）", out, "AUTO-MAS 已更新：v1 → v2")
        check("更新后的核对补做了一次，用的是新版本号", after, ["v2"])
        check("没有留下「没确认装成」的问题", problems, [])
        check("一条标自己好了的 WARNING（只进日报）", logged, [("WARNING", True)])

        print("\n[第二次还是旧版：第一次的话照旧，不做核对]")
        out, problems, after, _ = run(lands=False)
        check("照旧说「还没确认装成」", out.endswith("（安装已启动，还没确认装成）"), True)
        check("没做核对", after, [])
        check("留着没确认的问题", len(problems), 1)

        print("\n[不带 carry 的调用：和以前一样]")
        out, problems, after, _ = run(lands=True, carry=False)
        check("第二次没东西可说，第一次的话留着", out.endswith("（安装已启动，还没确认装成）"), True)
        check("不补核对", after, [])
    finally:
        (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version,
         boot_stages._seconds_to_next_queue, boot_stages._stop_requested) = saved


def _part_preupdate_mas_force():
    """AUTO-MAS 查更新必须带 if_force，否则下载地址是过期的一次性令牌。"""
    import types

    from ark_relay.features import preupdate as P  # run_automas 住在这个模块里，猴子补丁要打在它身上

    def main() -> int:
        calls = []

        def fake_post(path, body=None):
            calls.append((path, dict(body or {})))
            if path == "/api/update/check":
                return {"if_need_update": False, "latest_version": "v5.4.0"}
            return {}

        orig_post, orig_ver, orig_live = P._mas_post, P._automas_version, P._live_version
        P._mas_post = fake_post
        P._automas_version = lambda _root: "v5.4.0"
        P._live_version = lambda: ""
        try:
            P.run_automas(Path("."), budget_s=1)
        finally:
            P._mas_post, P._automas_version, P._live_version = orig_post, orig_ver, orig_live

        checks = [b for p, b in calls if p == "/api/update/check"]
        print("=== 查更新的调用 ===")
        for c in checks:
            print("  ", c)
        check("确实调了 /api/update/check", bool(checks), True)
        check("带了当前版本号",
              all(c.get("current_version") == "v5.4.0" for c in checks), True)
        check("带了 if_force=True（不带就会拿到过期令牌）",
              all(c.get("if_force") is True for c in checks), True)

        # res/version.json is stale since the Electron build; the backend's own
        # /api/core/health answer must be what the update check is asked with.
        calls.clear()
        P._mas_post, P._automas_version, P._live_version = fake_post, (lambda _root: "v5.5.0-beta.2"), (lambda: "v5.5.0-beta.4")
        try:
            P.run_automas(Path("."), budget_s=1)
        finally:
            P._mas_post, P._automas_version, P._live_version = orig_post, orig_ver, orig_live
        checks = [b for p, b in calls if p == "/api/update/check"]
        check("后端自报的版本压过 res/version.json 里的旧值",
              bool(checks) and all(c.get("current_version") == "v5.5.0-beta.4" for c in checks), True)
        # And when the backend cannot be asked, the file value still goes out.
        P._live_version = lambda: ""
        calls.clear()
        P._mas_post, P._automas_version = fake_post, (lambda _root: "v5.5.0-beta.2")
        try:
            P.run_automas(Path("."), budget_s=1)
        finally:
            P._mas_post, P._automas_version, P._live_version = orig_post, orig_ver, orig_live
        checks = [b for p, b in calls if p == "/api/update/check"]
        check("问不到后端时退回文件里的版本号",
              bool(checks) and all(c.get("current_version") == "v5.5.0-beta.2" for c in checks), True)

        # The install path must end with a verdict: the backend came back on the new
        # version (note says 已更新) or it did not (a problem is recorded).
        def post_with_update(path, body=None):
            calls.append((path, dict(body or {})))
            if path == "/api/update/check":
                return {"if_need_update": True, "latest_version": "v5.5.0-beta.4"}
            return {}
        orig_pack, orig_wait = P._wait_for_package, P._wait_for_version
        P._mas_post, P._automas_version = post_with_update, (lambda _root: "v5.5.0-beta.2")
        P._live_version = lambda: "v5.5.0-beta.2"
        P._wait_for_package = lambda _root, _deadline, *_a: Path("UpdatePack_v5.5.0-beta.4.zip")
        P._wait_for_version = lambda want, deadline, *_a: want
        problems = []
        note = P.run_automas(Path("."), budget_s=1, problems=problems)
        check("装成后通知说「已更新」", "已更新" in note and not problems, True)
        P._wait_for_version = lambda want, deadline, *_a: "v5.5.0-beta.2"
        try:
            problems = []
            note = P.run_automas(Path("."), budget_s=1, problems=problems)
        finally:
            P._mas_post, P._automas_version, P._live_version = orig_post, orig_ver, orig_live
            P._wait_for_package, P._wait_for_version = orig_pack, orig_wait
        check("没确认装成时记为未确认项", bool(problems) and "还没确认" in note, True)

        stop_hears_each_wait()

        return 0 if not fails else 1

    def stop_hears_each_wait() -> None:
        """2026-10-16 02:35: a stop came while the pre-update could not hear it and the 15 s
    hard exit killed the relay. Each AUTO-MAS wait ends at its next poll once the relay
    is stopping, with no problem note (nothing was judged; the next boot runs it again)."""
        import time
        print("\n[a stop during each AUTO-MAS wait ends it at the next poll]")

        def stop_after(n):
            asked = [0]

            def stopping():
                asked[0] += 1
                return asked[0] > n
            return stopping

        slept = []
        far = time.monotonic() + 3600
        # The waits sleep through the module's `time`: a fake one records the sleeps instead.
        real_time = P.time
        P.time = types.SimpleNamespace(sleep=slept.append, monotonic=time.monotonic)
        try:
            _stop_hears_each_wait(stop_after, slept, far)
        finally:
            P.time = real_time

    def _stop_hears_each_wait(stop_after, slept, far) -> None:
        import tempfile

        # The wait for the package (download running).
        with tempfile.TemporaryDirectory() as td:
            got = P._wait_for_package(Path(td), far, stop_after(1))
        check("package wait: None at the 2nd poll", (got, len(slept)), (None, 2))
        check("package wait: well inside the 15 s hard exit", sum(slept) <= 6, True)

        # The wait for the restarted backend (install running).
        slept.clear()
        orig_live = P._live_version
        P._live_version = lambda: ""
        try:
            got = P._wait_for_version("v5.7.0-beta.4", far, stop_after(1))
        finally:
            P._live_version = orig_live
        check("version wait: ends after one 5 s poll", (got, sum(slept)), ("", 5))

        # The wait for the backend to answer at all: no 「没有检查更新」 note.
        slept.clear()
        orig = (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version)

        def refused(path, body=None):
            raise OSError("refused")
        P._mas_post, P._automas_version, P._live_version = refused, (lambda _r: "v5.7.0-beta.3"), (lambda: "")
        try:
            problems = []
            note = P.run_automas(Path("."), problems=problems, stopping=stop_after(1))
            check("backend wait: stops after one poll, no note", (note, problems, sum(slept)), ("", [], 5))

            # Download running, then the stop: no install, no note.
            posts = []

            def post(path, body=None):
                posts.append(path)
                return {"if_need_update": True, "latest_version": "v5.7.0-beta.4"} if path == "/api/update/check" else {}
            P._mas_post = post
            P._wait_for_package, P._wait_for_version = orig[3], orig[4]
            slept.clear()
            problems = []
            with tempfile.TemporaryDirectory() as td:
                note = P.run_automas(Path(td), problems=problems, stopping=stop_after(1))
            check("download wait: stop -> no install, no note",
                  (note, problems, "/api/update/install" in posts, sum(slept) <= 6), ("", [], False, True))

            # Install started, then the stop while waiting for the new version: no note.
            posts.clear()
            slept.clear()
            P._wait_for_package = lambda _root, _deadline, *_a: Path("UpdatePack_v5.7.0-beta.4.zip")
            problems = []
            note = P.run_automas(Path("."), problems=problems, stopping=stop_after(1))
            check("install wait: stop -> no note, no 「还没确认」",
                  (note, problems, "/api/update/install" in posts, sum(slept) <= 6), ("", [], True, True))
        finally:
            (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version) = orig

    raise SystemExit(main())


def _part_preupdate_not_alarm():
    """A pre-update item that gave no verdict is tried once more, then pushed to the group."""
    import logging
    import types

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                 "win32com", "win32com.client")

    import boot_stages
    from ark_relay.features import gameupdate
    from ark_relay.features import okww_overlay
    from ark_relay.features import preupdate
    from ark_relay.features import commands
    from ark_relay.core import texts
    from ark_relay.features.errwatch import ARK
    from ark_relay.core.notify import route_of

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []

        def went_to_group(self):
            return True

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

    NO_VERDICT = "OK-WW 预更新：拿不到控制台会话，**没有检查更新**"
    marks = []
    boot_stages._stop_requested = lambda: False
    boot_stages.ensure_automas = lambda *a, **k: True
    commands.mas_up = lambda: True
    boot_stages._revive_automas = lambda: None
    preupdate.wanted_today = lambda *a, **k: True
    preupdate.should_run = lambda *a, **k: True
    preupdate.mark_run = lambda state_dir, now, clean: marks.append(clean)
    gameupdate.maaend_reenable_if_updated = lambda cfg: ""
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

    def stage(okww_answers, automas_answers=(), left=3600.0):
        REC.records.clear()
        marks.clear()
        calls = {"automas": [], "okww": []}
        preupdate.run_automas = scripted(list(automas_answers), calls["automas"])
        preupdate.run_okww = scripted(list(okww_answers), calls["okww"])
        boot_stages._seconds_to_next_queue = lambda automas_dir, now: left
        notes = Notes()
        boot_stages._stage_preupdate(CFG, notes, LOG)
        return notes, {k: len(v) for k, v in calls.items()}

    def errors():
        return [r.getMessage() for r in REC.records if r.levelno >= logging.ERROR]

    def said(fragment):
        return any(fragment in r.getMessage() for r in REC.records)

    print("[OK-WW gave no verdict, the second try did: nothing to report]")
    notes, calls = stage([NO_VERDICT, None])
    check("OK-WW ran twice", calls["okww"], 2)
    check("the log says it tried again", said("预更新：OK-WW 没给出结论"))
    check("no 「没能确认」 notice", [t for t, _, _ in notes.sent if "没能确认" in t], [])
    check("the day's pre-update is clean", marks, [True])
    check("nothing at ERROR", errors(), [])
    from ark_relay.features import errwatch
    healed = [r for r in REC.records if r.levelno == logging.WARNING and getattr(r, errwatch.RECOVERED, False)]
    check("one WARNING marked recovered for the first try's problem",
          [("OK-WW" in r.getMessage(), NO_VERDICT in r.getMessage()) for r in healed], [(True, True)])
    check("…its first line reads as plain words", [texts.plain(errwatch.first_line(r)) for r in healed], [[]])

    print("\n[no verdict twice (09-29 08:50:34): a group alarm (2026-10-06)]")
    notes, calls = stage([NO_VERDICT, NO_VERDICT])
    check("OK-WW ran twice", calls["okww"], 2)
    got = [(t, b, a) for t, b, a in notes.sent if "没能确认" in t]
    check("one notice", len(got), 1)
    title, body, alert = got[0] if got else ("", "", None)
    check("title", title, "⚠️ 预更新没能确认（1 项）")
    check("sent as an alert", alert, True)
    check("it goes to the group", route_of(title, alert=alert), "group")
    check("the item is listed once (the second try's note)", body.count("OK-WW 预更新"), 1)
    check("it says nobody has to act", "队列照常跑，明日方舟、终末地、鸣潮开跑时自己会查" in body)
    warn = [r for r in REC.records if r.levelno == logging.WARNING and "预更新有 1 项没能确认" in r.getMessage()]
    check("a WARNING line in the log", len(warn), 1)
    from ark_relay.features import errwatch
    check("…marked as already in the group (errwatch does not push it twice)",
          bool(warn) and getattr(warn[0], errwatch.PUSHED, False), True)
    check("nothing at ERROR (errwatch stays quiet)", errors(), [])
    check("not clean, so a later start may try again", marks, [False])

    print("\n[the next queue is too close: no second try]")
    notes, calls = stage([NO_VERDICT, None], left=120.0)
    check("OK-WW ran once", calls["okww"], 1)
    check("the log says why", said("离下一个队列只有 120 秒，不再试"))
    check("the alarm still goes out",
          [(t, a) for t, _, a in notes.sent if "没能确认" in t], [("⚠️ 预更新没能确认（1 项）", True)])

    print("\n[the AUTO-MAS slot retries the same way]")
    notes, calls = stage([None], automas_answers=["AUTO-MAS 预更新：后端 180 秒内没起来，**没有检查更新**"])
    check("AUTO-MAS asked twice", calls["automas"], 2)
    check("it answered the second time: clean", marks, [True])
    check("…and the first try's problem is one recovered WARNING",
          len([r for r in REC.records if getattr(r, errwatch.RECOVERED, False) and "AUTO-MAS" in r.getMessage()]), 1)
    check("nothing at ERROR", errors(), [])

    print("\n[an item that answers at once runs once]")
    notes, calls = stage([None])
    check("AUTO-MAS, OK-WW once each", calls, {"automas": 1, "okww": 1})
    check("no recovered WARNING when nothing failed", [r for r in REC.records if getattr(r, errwatch.RECOVERED, False)], [])
    check("clean", marks, [True])

    print("\n[game update that could not confirm: a group alarm, the WARNING after it]")
    REC.records.clear()
    gameupdate.should_run = lambda *a, **k: True
    gameupdate.boot_check = lambda cfg, budget_s, now: ([], ["终末地：启动器没响应，没能确认有没有新版本"])
    gameupdate.mark_run = lambda *a, **k: None
    boot_stages._boot_stamp = lambda now: "x"
    notes = Notes()
    boot_stages._stage_gameupdate(CFG, notes, LOG)
    got = [(t, a) for t, _, a in notes.sent]
    check("one alarm", got, [("⚠️ 游戏更新没能确认（1 项）", True)])
    check("it goes to the group", route_of(got[0][0], alert=got[0][1]) if got else "", "group")
    warn = [r for r in REC.records if r.levelno == logging.WARNING and "游戏更新有 1 项没能确认" in r.getMessage()]
    check("one WARNING, marked as already in the group", [getattr(r, errwatch.PUSHED, False) for r in warn], [True])
    check("nothing at ERROR", errors(), [])

    print("\n[the old tails are gone]")
    check("no 「机器跑的还是原来的版本」", "机器跑的还是原来的版本" in texts.preupdate_unconfirmed_tail(), False)
    check("no 「不用管」 in an alarm", "不用管" in texts.preupdate_unconfirmed_tail(), False)


def _part_main_2():
    """OK-WW's pre-update must not start 鸣潮, and must put the switch back."""
    import ast
    import json
    import os
    import tempfile

    from ark_relay.features import preupdate
    from ark_relay.features import preupdate as preupdate_okww

    def make(root: Path, autostart: bool) -> Path:
        d = root / "okww"
        cfgdir = d / "data" / "apps" / "ok-ww" / "working" / "configs"
        cfgdir.mkdir(parents=True, exist_ok=True)
        (cfgdir / "Basic Options.json").write_text(json.dumps({
            "Auto Start Game When App Starts": autostart,
            "Mute Game while in Background": True,
            "Use DirectML": "Yes",
        }, ensure_ascii=False), encoding="utf-8")
        (d / "data" / "apps" / "ok-ww").mkdir(parents=True, exist_ok=True)
        (d / "data" / "apps" / "ok-ww" / "app.json").write_text(json.dumps({
            "current_version": "v3.6.4", "update_state": "idle", "update_error": None,
        }), encoding="utf-8")
        return d

    def basic(d: Path) -> dict:
        return json.loads((d / "data" / "apps" / "ok-ww" / "working" / "configs"
                           / "Basic Options.json").read_text(encoding="utf-8"))

    def main(root: Path) -> int:
        d = make(root, autostart=True)

        was = preupdate_okww._okww_autostart(d, False)
        check("读到原值 True", was, True)
        check("已关掉自动开游戏", basic(d)["Auto Start Game When App Starts"], False)
        check("其他设置没被动到", basic(d)["Mute Game while in Background"], True)
        check("非布尔项也完好", basic(d)["Use DirectML"], "Yes")
        preupdate_okww._okww_autostart(d, True)
        check("能原样放回去", basic(d)["Auto Start Game When App Starts"], True)

        check("读得到 app.json 状态", preupdate_okww._okww_state(d)[:3],
              ("v3.6.4", "idle", ""))
        # 第四项是判断"到底检查过没有"的唯一依据，见 _okww_state 的注释。
        check("状态里带得出可用版本列表",
              isinstance(preupdate_okww._okww_state(d)[3], tuple), True)

        bad = root / "bad"
        (bad / "data" / "apps" / "ok-ww" / "working" / "configs").mkdir(parents=True)
        check("配置读不懂时返回 None", preupdate_okww._okww_autostart(bad, False), None)

        # No ok-ww.exe -> do nothing, and never leave the switch flipped.
        check("找不到 ok-ww.exe 时什么都不做", preupdate.run_okww(d, budget_s=1), "")
        check("跳过后开关仍是原值",
              basic(d)["Auto Start Game When App Starts"], True)
        check("目录为 None 时也安全", preupdate.run_okww(None), "")

        src = "".join(q.read_text(encoding="utf-8") for q in sorted((Path(__file__).resolve().parents[1] / "ark_relay" / "features").glob("preupdate*.py")))  # 预更新拆成了五个文件，一起看
        check("拒绝在 session 0 启动",
              "_spawn_interactive(exe, root, require_console=True, minimized=True)" in src, True)
        check("拿不到控制台会话要上报",
              "拿不到控制台会话" in src, True)
        check("安静不等于没有更新",
              "无法确认是否检查过更新" in src, True)
        # The shape the user-switches guard accepts: the setter's old value goes back
        # through the same setter inside a `finally` of run_okww.
        fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run_okww")
        restores = [c for t in ast.walk(fn) if isinstance(t, ast.Try) for st in t.finalbody for c in ast.walk(st)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_okww_autostart"
                    and any(isinstance(a, ast.Name) and a.id == "was" for a in c.args)]
        check("在 finally 里还原开关", len({id(c) for c in restores}), 1)
        check("改配置前先停掉在跑的实例", "_okww_quiesce(" in src
              and src.index("_okww_quiesce(", src.index("def run_okww"))
              < src.index("was = _okww_autostart"), True)
        calls = sum(1 for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_okww_quiesce")
        check("收尾也清一次，不留游戏在后台", calls >= 2, True)

        check("the minimum wait covers OK-WW's 30 s update check", preupdate.OKWW_MIN_WAIT_SECONDS >= 40, True)
        pre_src = "".join(q.read_text(encoding="utf-8") for q in sorted(
            (Path(__file__).resolve().parents[1] / "ark_relay" / "features").glob("preupdate*.py")))
        check("the 「checked」 verdict waits at least that long",
              "clock() - launched >= OKWW_MIN_WAIT_SECONDS" in pre_src, True)

        timeout_mid_download(root)
        baseline_unknown(root)
        newer_listed_not_installed(root)
        stop_and_switch_memo(root)
        return 0 if not fails else 1

    def timeout_mid_download(root: Path) -> None:
        """Out of time while app.json still says downloading: a failure, never 「无需更新」."""
        m = preupdate_okww
        d = make(root / "dl", autostart=True)
        appjson = d / "data" / "apps" / "ok-ww" / "app.json"
        appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "downloading",
                                       "update_error": None, "available_versions": ["v3.7.4", "v3.7.3"]}),
                           encoding="utf-8")
        now = [0.0]
        out = m._okww_await_update(d, 240, "v3.7.3", ("v3.7.3",), m._okww_stamp(d),
                                   sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
        check("超时仍在下载：带回卡住的状态和最后读到的版本列表", out, ("", True, "", "downloading", ("v3.7.4", "v3.7.3")))
        check("等满了预算才算超时", now[0] >= 240, True)

        appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "idle",
                                       "update_error": None}), encoding="utf-8")
        now[0] = 0.0
        out = m._okww_await_update(d, 240, "v3.7.3", (), m._okww_stamp(d) - 10,
                                   sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
        check("空闲且检查过：照旧算查完，不算卡住", out, ("", True, "", "", ()))
        check("至少等过上游那 30 秒检查", now[0] >= m.OKWW_MIN_WAIT_SECONDS, True)

        probs = []
        m._okww_report(probs, 240, "v3.7.3", ("v3.7.4",), "", True, "", "downloading", Path("shot.png"))
        check("超时下载中：记成问题", len(probs), 1)
        check("问题里写了还在下载、没更新完", "还在「downloading」" in probs[0] and "没更新完" in probs[0], True)
        check("问题里明说不是无需更新", "不是「无需更新」" in probs[0], True)
        check("问题里带截图", "shot.png" in probs[0], True)
        probs = []
        m._okww_report(probs, 240, "v3.7.3", ("v3.7.3",), "", True, "", "", None)
        check("真没有新版：不记问题", probs, [])

        os.environ["ARK_STATE_DIR"] = str(root / "state")
        try:
            taken = []
            shot = m._okww_timeout_shot(lambda out: taken.append(out) or True)
            check("截图存进状态目录的 preupdate/", shot is not None and shot.parent == root / "state" / "preupdate", True)
            check("截图就是截下来的那张", taken, [shot])
            check("截不到时返回 None", m._okww_timeout_shot(lambda out: False), None)
            check("截图出错也不抛", m._okww_timeout_shot(lambda out: 1 / 0), None)
        finally:
            os.environ.pop("ARK_STATE_DIR", None)

        # run_okww end to end, with the machine-touching steps recorded instead of run.
        (d / "ok-ww.exe").write_text("", encoding="utf-8")
        saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_okww_quiesce", "_okww_close", "_close",
                                            "_okww_await_update", "_okww_timeout_shot")}
        order = []
        try:
            m._okww_quiesce = lambda *a, **kw: order.append("quiesce")
            m._okww_close = lambda *a, **kw: order.append("closed") or []
            m._close = lambda exe: order.append("close")
            m._okww_timeout_shot = lambda: order.append("shot") or Path("t.png")
            m._okww_await_update = lambda *a, **kw: ("", True, "", "downloading", ())
            m._spawn_interactive = lambda *a, **kw: order.append("spawn") or True
            probs = []
            check("超时下载中：不报已更新", m.run_okww(d, budget_s=240, problems=probs), "")
            check("超时下载中：问题里是没更新完", ["没更新完" in p for p in probs], [True])
            check("先停掉所有实例再启动我们自己的，截图在关之前，关的是我们启动的",
                  order, ["quiesce", "spawn", "shot", "close", "closed"])
            check("开关放回原值", basic(d)["Auto Start Game When App Starts"], True)

            order.clear()
            m._spawn_interactive = lambda *a, **kw: order.append("spawn") or False
            probs = []
            m.run_okww(d, budget_s=240, problems=probs)
            check("没启动成功就不去关 OK-WW", "close" in order, False)

            order.clear()
            m._spawn_interactive = lambda *a, **kw: order.append("spawn") or True
            m._okww_await_update = lambda *a, **kw: ("", True, "", "", ())
            probs = []
            m.run_okww(d, budget_s=240, problems=probs)
            check("没卡住就不截图", "shot" in order, False)

            # Something raises after the launch: OK-WW is still closed, then the switch goes back.
            order.clear()
            saved_set = m._okww_autostart

            def _set(root_, value):
                order.append(f"set {value}")
                return saved_set(root_, value)
            m._okww_autostart = _set
            m._okww_await_update = lambda *a, **kw: 1 / 0
            try:
                m.run_okww(d, budget_s=240, problems=[])
                check("中途出错照样往外抛", False, True)
            except ZeroDivisionError:
                check("中途出错照样往外抛", True, True)
            check("中途出错：先关 OK-WW，再把开关放回原值",
                  order, ["quiesce", "set False", "spawn", "close", "closed", "set True"])
            check("中途出错：开关是原值", basic(d)["Auto Start Game When App Starts"], True)

            # The switch cannot be put back: a WARNING (pushed to the group), naming it.
            import logging
            grabbed = []

            class _Grab(logging.Handler):
                def emit(self, record):
                    grabbed.append((record.levelno, record.getMessage()))
            h = _Grab()
            preupdate_okww.log.addHandler(h)
            calls = []
            # First call turns it off (it was on); the one putting it back fails.
            m._okww_autostart = lambda root_, value: (calls.append(value), True if len(calls) == 1 else None)[1]
            m._okww_await_update = lambda *a, **kw: ("", True, "", "", ())
            try:
                m.run_okww(d, budget_s=240, problems=[])
            finally:
                preupdate_okww.log.removeHandler(h)
                m._okww_autostart = saved_set
            check("改不回去：WARNING，说清是哪个开关",
                  [lv for lv, msg in grabbed if "自动开游戏" in msg and "没能改回" in msg], [logging.WARNING])
        finally:
            for k, v in saved.items():
                setattr(m, k, v)

    def baseline_unknown(root: Path) -> None:
        """app.json unreadable at the pre-launch read: the first version read later is
    not an update (audit row preupdate_okww.py:243 via :392)."""
        print("[baseline version unknown]")
        m = preupdate_okww
        d = make(root / "nobase", autostart=True)
        appjson = d / "data" / "apps" / "ok-ww" / "app.json"
        appjson.write_text(json.dumps({"current_version": "v3.7.4", "update_state": "idle",
                                       "update_error": None}), encoding="utf-8")
        real_await = m._okww_await_update
        now = [0.0]

        def fast_await(*a, **kw):
            now[0] = 0.0
            return real_await(*a, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0], **kw)

        out = fast_await(d, 240, "", (), m._okww_stamp(d) - 10)
        check("baseline unknown: a version read later is not settled as an update", out[0], "")

        (d / "ok-ww.exe").write_text("", encoding="utf-8")
        saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_okww_quiesce", "_okww_close", "_close",
                                            "_okww_await_update", "_okww_state")}
        reads = []
        real_state = m._okww_state
        try:
            m._okww_quiesce = lambda *a, **kw: None
            m._okww_close = lambda *a, **kw: []
            m._close = lambda exe: None
            m._spawn_interactive = lambda *a, **kw: True
            m._okww_await_update = fast_await
            # The pre-launch read fails (OK-WW was rewriting app.json); later reads work.
            m._okww_state = lambda r: (reads.append(1), ("", "", "", ()) if len(reads) == 1 else real_state(r))[1]
            probs = []
            got = m.run_okww(d, budget_s=240, problems=probs)
            check("baseline unknown: not reported as 「OK-WW 已更新」", got, "")
            check("baseline unknown: a problem says the version could not be compared",
                  sum(1 for p_ in probs if "版本号" in p_ and "没法比对" in p_ and "v3.7.4" in p_), 1)
        finally:
            for k, v in saved.items():
                setattr(m, k, v)

    def newer_listed_not_installed(root: Path) -> None:
        """OK-WW lists a newer version during the wait but does not install it: a problem,
    not 「无需更新」. The verdict used to read the list from before the launch, so
    the newer entry seen inside the wait never reached it (audit #10)."""
        print("[newer version listed during the wait, not installed]")
        m = preupdate_okww
        d = make(root / "newer", autostart=True)
        appjson = d / "data" / "apps" / "ok-ww" / "app.json"
        appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "idle",
                                       "update_error": None, "available_versions": ["v3.7.3"]}),
                           encoding="utf-8")
        (d / "ok-ww.exe").write_text("", encoding="utf-8")
        real_await = m._okww_await_update
        now = [0.0]

        def tick(s):
            # OK-WW's check: the list gains v3.7.4, the installed version stays v3.7.3.
            if now[0] == 0.0:
                appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "idle",
                                               "update_error": None,
                                               "available_versions": ["v3.7.4", "v3.7.3"]}),
                                   encoding="utf-8")
            now[0] += s

        def fast_await(*a, **kw):
            now[0] = 0.0
            return real_await(*a, sleep=tick, clock=lambda: now[0], **kw)

        saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_okww_quiesce", "_okww_close", "_close",
                                            "_okww_await_update")}
        try:
            m._okww_quiesce = lambda *a, **kw: None
            m._okww_close = lambda *a, **kw: []
            m._close = lambda exe: None
            m._spawn_interactive = lambda *a, **kw: True
            m._okww_await_update = fast_await
            probs = []
            got = m.run_okww(d, budget_s=240, problems=probs)
        finally:
            for k, v in saved.items():
                setattr(m, k, v)
        check("newer listed, not installed: not reported as updated", got, "")
        check("newer listed, not installed: a problem naming v3.7.4",
              [p_ for p_ in probs if "查到有 v3.7.4" in p_ and "没装上" in p_ and "v3.7.3" in p_] != [], True)
        probs = []
        m._okww_report(probs, 240, "v3.7.3", ("v3.7.4", "v3.7.3"), "", True, "", "", None)
        check("the verdict reads the list it is given (the latest one)", len(probs), 1)

    def stop_and_switch_memo(root: Path) -> None:
        """2026-10-16 02:35: a deploy rollback stopped the relay during the OK-WW wait, which
    could not hear the stop; the 15 s hard exit killed the process before the `finally`
    put the auto-start switch back, and the next run "restored" it to off. The wait now
    ends at the poll after a stop, a stopping relay launches nothing, and the switch's
    value is kept in state until it is back (restored on the next run or boot)."""
        print("[stop during the OK-WW pre-update; the switch survives a hard exit]")
        m = preupdate_okww

        def stop_after(n):
            asked = [0]

            def stopping():
                asked[0] += 1
                return asked[0] > n
            return stopping

        # (a) the wait itself: a stop at poll 2 ends it there, before the 45 s minimum.
        d = make(root / "stop", autostart=True)
        now = [0.0]
        out = m._okww_await_update(d, 240, "v3.6.4", (), m._okww_stamp(d),
                                   sleep=lambda s_: now.__setitem__(0, now[0] + s_), clock=lambda: now[0],
                                   stopping=stop_after(1))
        check("(a) stop at poll 2: ends after 6 s, no error, not stuck", (now[0], out[2], out[3]), (6.0, "", ""))

        (d / "ok-ww.exe").write_text("", encoding="utf-8")
        state = root / "stop-state"
        memo = state / m.AUTOSTART_MEMO
        real_await = m._okww_await_update
        saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_okww_quiesce", "_okww_close", "_close",
                                            "_okww_await_update", "_okww_timeout_shot")}
        order = []
        try:
            m._okww_quiesce = lambda *a, **kw: order.append("quiesce")
            m._okww_close = lambda *a, **kw: order.append("closed") or []
            m._close = lambda exe: order.append("close")
            m._okww_timeout_shot = lambda: order.append("shot") or Path("t.png")
            m._spawn_interactive = lambda *a, **kw: order.append("spawn") or True
            seen = {}

            def fast_await(*a, **kw):
                # What a hard exit right now would leave behind: switch off, record says on.
                seen["switch"] = basic(d)["Auto Start Game When App Starts"]
                seen["memo"] = json.loads(memo.read_text(encoding="utf-8"))["was"] if memo.exists() else None
                now[0] = 0.0
                return real_await(*a, sleep=lambda s_: now.__setitem__(0, now[0] + s_), clock=lambda: now[0], **kw)
            m._okww_await_update = fast_await

            # (b) stop mid-wait: closed, switch back on, no note, no screenshot, record gone.
            probs = []
            # stopping() is asked on entry, after the quiesce, then at each poll: the 4th call is poll 2.
            got = m.run_okww(d, budget_s=240, problems=probs, state_dir=state, stopping=stop_after(3))
            check("(b) stop mid-wait: no verdict, no note", (got, probs), ("", []))
            check("(b) stop mid-wait: ends at the 2nd poll (6 s), then closes OK-WW",
                  (now[0], order), (6.0, ["quiesce", "spawn", "close", "quiesce"]))
            check("(b) the switch is back on", basic(d)["Auto Start Game When App Starts"], True)
            check("(b) during the wait the record held the original value", (seen["switch"], seen["memo"]), (False, True))
            check("(b) record removed once the switch is back", memo.exists(), False)

            # Stop before anything: nothing launched, nothing touched.
            order.clear()
            got = m.run_okww(d, budget_s=240, problems=probs, state_dir=state, stopping=lambda: True)
            check("stopping already: no quiesce, no launch", (got, order, probs), ("", [], []))

            # Stop during the quiesce (between the AUTO-MAS item and OK-WW): no switch flip, no launch.
            order.clear()
            flag = []
            m._okww_quiesce = lambda *a, **kw: order.append("quiesce") or flag.append(1)
            m._okww_close = lambda *a, **kw: order.append("closed") or []
            got = m.run_okww(d, budget_s=240, problems=probs, state_dir=state, stopping=lambda: bool(flag))
            check("stop during the quiesce: OK-WW not launched", (got, order, probs), ("", ["quiesce"], []))
            check("stop during the quiesce: switch untouched, no record", (basic(d)["Auto Start Game When App Starts"],
                                                                           memo.exists()), (True, False))
            m._okww_quiesce = lambda *a, **kw: order.append("quiesce")
            m._okww_close = lambda *a, **kw: order.append("closed") or []

            # (c) a hard exit left the switch off and the record on: the next run puts back "on".
            cfg = d / "data" / "apps" / "ok-ww" / "working" / "configs" / "Basic Options.json"
            data = basic(d)
            data["Auto Start Game When App Starts"] = False
            cfg.write_text(json.dumps(data), encoding="utf-8")
            state.mkdir(parents=True, exist_ok=True)
            memo.write_text(json.dumps({"was": True}), encoding="utf-8")
            m._okww_await_update = lambda *a, **kw: ("", True, "", "", ())
            order.clear()
            m.run_okww(d, budget_s=240, problems=[], state_dir=state, stopping=lambda: False)
            check("(c) next run: the switch goes back to the recorded on, not the off it found",
                  (basic(d)["Auto Start Game When App Starts"], memo.exists()), (True, False))

            m._okww_close = lambda *a, **kw: order.append("closed") or ["ok-ww.exe"]
            order.clear()
            m.run_okww(d, budget_s=240, problems=[], state_dir=state, stopping=lambda: False)
            check("(d) not closed for real: the switch goes back anyway, the record stays",
                  (order[-1], basic(d)["Auto Start Game When App Starts"], memo.exists()), ("closed", True, True))
            check("(d) the next boot finds the switch as recorded: record dropped, nothing said",
                  (m.restore_autostart_leftover(d, state, pids=lambda: []), memo.exists()), ("", False))
            data = basic(d)
            data["Auto Start Game When App Starts"] = False          # ok-ww.exe wrote it off on its way out
            cfg.write_text(json.dumps(data), encoding="utf-8")
            memo.write_text(json.dumps({"was": True}), encoding="utf-8")
            line = m.restore_autostart_leftover(d, state, pids=lambda: [])
            check("(d) ……or finds it written off again: put back on, said",
                  (basic(d)["Auto Start Game When App Starts"], memo.exists(), "放回" in line), (True, False, True))
            m._okww_close = lambda *a, **kw: order.append("closed") or []
        finally:
            for k, v in saved.items():
                setattr(m, k, v)

        # (c) at boot, pre-update or not: restored only while no OK-WW python runs.
        data = basic(d)
        data["Auto Start Game When App Starts"] = False
        (d / "data" / "apps" / "ok-ww" / "working" / "configs" / "Basic Options.json").write_text(
            json.dumps(data), encoding="utf-8")
        memo.write_text(json.dumps({"was": True}), encoding="utf-8")
        check("boot, OK-WW running: left alone", (m.restore_autostart_leftover(d, state, pids=lambda: [4242]),
                                                  basic(d)["Auto Start Game When App Starts"], memo.exists()),
              ("", False, True))
        check("boot, process list unreadable: left alone", (m.restore_autostart_leftover(d, state, pids=lambda: None),
                                                            memo.exists()), ("", True))
        line = m.restore_autostart_leftover(d, state, pids=lambda: [])
        check("boot, nothing running: put back on, record removed",
              (basic(d)["Auto Start Game When App Starts"], memo.exists(), "放回" in line), (True, False, True))
        check("boot, no record: nothing to do, no process query",
              m.restore_autostart_leftover(d, state, pids=lambda: 1 / 0), "")
        from ark_relay.core import texts
        check("the boot line is plain words", texts.plain(line), [])

    if __name__ == "__main__":
        with tempfile.TemporaryDirectory() as tmp:
            raise SystemExit(main(Path(tmp)))


def _part_okww_deps():
    """OK-WW's own Python packages are checked after the pre-update (ledger #115; dispatch
relay-opt-round3-1108 O-01; preupdate_okww.ensure_okww_deps).
    """
    import inspect
    import logging
    import subprocess
    from types import SimpleNamespace

    from ark_relay.features import errwatch
    from ark_relay.features import preupdate, preupdate as po
    from ark_relay.features.preupdate import PWSH_GUARD_S


    class Rows(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, bool(getattr(record, errwatch.RECOVERED, False)), record.getMessage()))


    rows = Rows()
    po.log.addHandler(rows)
    po.log.setLevel(logging.DEBUG)
    po.log.propagate = False


    def okww(requirements=None):
        root = tmpdir()
        py = root.joinpath(*po._OKWW_PYTHON)
        py.parent.mkdir(parents=True)
        py.write_text("", encoding="utf-8")
        working = root.joinpath(*po._OKWW_WORKING)
        working.mkdir(parents=True)
        if requirements is not None:
            (working / "requirements.txt").write_text(requirements, encoding="utf-8")
        return root


    class Fake:
        """subprocess.run: each probe prints the next of `probes`; pip answers `pip_rc`."""

        def __init__(self, *probes, pip_rc=0, raise_probe=None):
            self.probes, self.pip_rc, self.raise_probe = list(probes), pip_rc, raise_probe
            self.calls = []

        def __call__(self, args, **kw):
            self.calls.append(list(args))
            if args[1:3] == ["-m", "pip"]:
                return SimpleNamespace(returncode=self.pip_rc, stdout=b"", stderr=b"")
            if self.raise_probe is not None:
                raise self.raise_probe
            out = self.probes.pop(0) if self.probes else ""
            return SimpleNamespace(returncode=0, stdout=out.encode("utf-8"), stderr=b"")

        def pips(self):
            return [c[c.index("install") + 1:] for c in self.calls if c[1:3] == ["-m", "pip"]]


    def run(root, fake):
        rows.rows.clear()
        problems = []
        out = po.ensure_okww_deps(root, problems, run=fake)
        return out, problems, [(lv, r) for lv, r, _ in rows.rows if lv != "INFO"]


    REQ = ("# autogenerated\nok-script[ocr,qt]==3.0.3\n    # via -r\nopencv-python==4.12.0.88\npywin32==311\n"
           "onnxocr-ppocrv5>=0.0.20\n")
    FLAGS = ["--disable-pip-version-check", "--no-input"]
    REAL_REQ = (fx_dir(Path(__file__), "gamesim") / "upstream" / "okww-v3.7.14-beta.2"
                / "requirements.txt.txt").read_text(encoding="utf-8")

    print("[读 OK-WW 自己的依赖清单：名字到版本号、额外项、环境标记为止]")
    pins = po._okww_pins(okww(REAL_REQ).joinpath(*po._OKWW_WORKING))
    check("装着的 v3.7.14-beta.2 清单：onnxocr-ppocrv5>=0.0.20 的名字不带版本号",
          pins.get("onnxocr-ppocrv5"), "onnxocr-ppocrv5>=0.0.20")
    check("……ok-script[ocr,qt]==2.0.22 去掉额外项当名字", pins.get("ok-script"), "ok-script[ocr,qt]==2.0.22")
    check("……每个 key 都是纯名字", [k for k in pins if any(c in k for c in "=<>!~[ ;")], [])
    marked = po._okww_pins(okww("pywin32==311 ; sys_platform == \"win32\"\n").joinpath(*po._OKWW_WORKING))
    check("带环境标记的：名字对、装的时候不带标记", marked, {"pywin32": "pywin32==311"})

    print("\n[没有 OK-WW 自带的 Python：什么都不做]")
    check("空目录", po.ensure_okww_deps(tmpdir(), [], run=Fake()), "")

    print("\n[都装着、都导入得了：不装、不报]")
    fake = Fake("")
    out, problems, logged = run(okww(REQ), fake)
    check("没补装、没问题、没 WARNING", (out, problems, logged, fake.pips()), ("", [], [], []))
    check("试导入用的是 OK-WW 自己的 python", fake.calls[0][1], "-c")

    print("\n[缺 packaging（#115，OK-WW 清单里没有）：照样补装，核对过，只进日报]")
    fake = Fake("MODULE packaging\n", "")
    out, problems, logged = run(okww(REQ), fake)
    check("装的是 packaging", fake.pips(), [FLAGS + ["packaging"]])
    check("返回补装了什么", out, "OK-WW 缺的 Python 包已补装：packaging")
    check("没有要报群的问题", problems, [])
    check("一条标自己好了的 WARNING", logged, [("WARNING", True)])

    print("\n[清单里的包没装（按包名查，不靠模块名）：按清单写的装回]")
    fake = Fake("DIST opencv-python\nDIST pywin32\nDIST onnxocr-ppocrv5\nMODULE cv2\n", "")
    out, problems, _ = run(okww(REQ), fake)
    check("按清单装 opencv-python、pywin32、onnxocr-ppocrv5（cv2 由 opencv-python 带回）",
          fake.pips(), [FLAGS + ["opencv-python==4.12.0.88", "pywin32==311", "onnxocr-ppocrv5>=0.0.20"]])
    check("装完 cv2 也导入得了：不报「清单里没有」", problems, [])
    check("返回里有它们", "opencv-python" in out and "cv2" in out, True)

    print("\n[缺的模块哪个包都对不上：不装，报出来]")
    fake = Fake("MODULE yaml\n")
    out, problems, logged = run(okww(REQ), fake)
    check("一个包都没装（yaml 不是包名，猜了可能装错）", fake.pips(), [])
    check("一条问题，说了缺什么、为什么没装", [("yaml" in p and "依赖清单里没有" in p) for p in problems], [True])
    check("没有 WARNING", logged, [])

    print("\n[装完还缺：报出来]")
    fake = Fake("MODULE packaging\n", "MODULE packaging\n", pip_rc=1)
    out, problems, logged = run(okww(REQ), fake)
    check("说补装没成、带 pip 结果", [("自动补装没成" in p and "pip 结果 1" in p) for p in problems], [True])
    check("不算补好了", (out, logged), ("", []))

    print("\n[试导入跑不起来：说没能核对]")
    fake = Fake(raise_probe=subprocess.TimeoutExpired("python", PWSH_GUARD_S))
    out, problems, _ = run(okww(REQ), fake)
    check("一条问题：没能核对", [("没能核对" in p) for p in problems], [True])

    print("\n[真跑一次探针（这台 Mac 的 Python）：按包名、按导入都查得出来]")
    w = tmpdir()
    (w / "requirements.txt").write_text("ark-fake-dist>=1\nno-such-dist-for-ark-test==1.0\n", encoding="utf-8")
    # An installed dist without depending on what this python has: its metadata next to the
    # probe (the probe puts '.' first on sys.path, where importlib.metadata looks too).
    (w / "ark_fake_dist-1.0.dist-info").mkdir()
    (w / "ark_fake_dist-1.0.dist-info" / "METADATA").write_text("Metadata-Version: 2.1\nName: ark-fake-dist\nVersion: 1.0\n",
                                                               encoding="utf-8")
    (w / "config.py").write_text("", encoding="utf-8")
    (w / "ok" / "core").mkdir(parents=True)
    (w / "ok" / "__init__.py").write_text("", encoding="utf-8")
    (w / "ok" / "core" / "__init__.py").write_text("", encoding="utf-8")
    (w / "ok" / "core" / "plugins.py").write_text("import no_such_module_for_ark_test\n", encoding="utf-8")
    got = subprocess.run([sys.executable, "-c", po._DEPS_PROBE], cwd=str(w), capture_output=True, timeout=60)
    lines = set(got.stdout.decode("utf-8", "replace").splitlines()) - {""}
    check("清单里没装的包：DIST 按包名报", "DIST no-such-dist-for-ark-test" in lines, True)
    check("装着的（ark-fake-dist）不报", any(x.startswith("DIST ark-fake-dist") for x in lines), False)
    check("ok.core.plugins 里缺的模块：MODULE 报出来（只导入 ok 碰不到它）",
          "MODULE no_such_module_for_ark_test" in lines, True)
    check("config、ok 本身都在：不报", {"MODULE config", "MODULE ok"} & lines, set())
    (w / "ok" / "core" / "plugins.py").unlink()
    got = subprocess.run([sys.executable, "-c", po._DEPS_PROBE], cwd=str(w), capture_output=True, timeout=60)
    check("这一版 ok-script 没有 ok.core.plugins：不算缺包",
          any(x.startswith("MODULE ok") for x in got.stdout.decode("utf-8", "replace").splitlines()), False)

    print("\n[接在预更新里、算进最长时长]")
    src = inspect.getsource(po.run_okww)
    check("run_okww 关掉 OK-WW（核实关干净）之后核对", src.index("still = _okww_close()") < src.index("ensure_okww_deps(root, problems)"), True)
    check("worst_case_seconds 里有它的三次（试导入、pip、再试导入）",
          "+ 3 * PWSH_GUARD_S" in inspect.getsource(preupdate.worst_case_seconds), True)


def _part_preupdate_once():
    """预更新一天只跑一遍。"""
    from datetime import datetime, timedelta

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore
    from ark_relay.features.preupdate import RETRY_MIN, mark_run, should_run

    def main() -> int:
        d = tmpdir()
        now = datetime(2026, 8, 31, 8, 45, tzinfo=SERVER_TZ)

        check("没记账过 → 跑", should_run(d, now), True)
        check("没有 state 目录 → 跑（不因为记不住就不干活）",
              should_run(None, now), True)

        mark_run(d, now, clean=True)
        check("今天干净地跑过 → 服务重启不重跑",
              should_run(d, now + timedelta(minutes=1)), False)
        check("过一整天 → 再跑",
              should_run(d, now + timedelta(days=1)), True)

        mark_run(d, now, clean=False)
        check("这轮有没确认的项，刚过一分钟 → 先别急着重试",
              should_run(d, now + timedelta(minutes=1)), False)
        check(f"隔了 {RETRY_MIN} 分钟 → 允许重试一次",
              should_run(d, now + timedelta(minutes=RETRY_MIN)), True)

        # 记账文件坏掉不能变成「从此不跑」
        (d / "state.json").write_text("{坏的", encoding="utf-8")     # 状态文件整个坏掉
        check("记账文件损坏 → 照跑", should_run(d, now), True)
        StateStore(d).set("updates", "preupdate", {"day": "2026-08-31"})   # 缺 at
        check("记账缺时间戳 → 照跑", should_run(d, now), True)

        print("all checks passed" if not fails else "FAILED: " + "; ".join(fails))
        return 0 if not fails else 1

    raise SystemExit(main())


def _part_preupdate_problems():
    """预更新查不出结果时，必须报错，而不是静静地当成「无需更新」。"""
    import os
    import re

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
    from ark_relay.features import preupdate

    print("[每个 run_* 都收得下 problems]")
    import inspect
    for name in ("run_automas", "run_okww"):
        sig = inspect.signature(getattr(preupdate, name))
        check(f"{name} 有 problems 参数", "problems" in sig.parameters)

    print("\n[找不到程序 = 一个问题，不是沉默]")
    empty = TMP / "empty"
    empty.mkdir(exist_ok=True)
    for name, fn in (("OK-WW", preupdate.run_okww),):
        problems = []
        fn(empty, budget_s=1, problems=problems)
        check(f"{name} 找不到 exe 会报一条", len(problems), 1)
        check(f"{name} 的问题里点名了程序", any(name in p for p in problems))

    print("\n[AUTO-MAS 读不到版本号也要报]")
    problems = []
    preupdate.run_automas(empty, budget_s=1, problems=problems)
    check("报了一条", len(problems), 1)
    check("说的是没有检查更新", any("没有检查更新" in p for p in problems))

    print("\n[problems 为 None 时不能炸]")
    try:
        preupdate.run_okww(empty, budget_s=1)
        preupdate.run_automas(empty, budget_s=1)
        check("默认不传也安全", True)
    except Exception as e:  # noqa: BLE001
        check(f"默认不传也安全（炸了：{e}）", False)

    print("\n[开机流程照样说出来，当报警进群（2026-10-06 起）]")
    src = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
    check("收集 problems", "problems: list[str] = []" in src)
    for fname in ("run_automas", "run_okww"):
        calls = re.findall(rf"preupdate\.{fname}\((?:[^()]|\([^()]*\))*\)", src, re.S)
        check(f"boot_stages.py 里调了 preupdate.{fname}", len(calls) >= 1, True)
        check(f"preupdate.{fname} 每次调用都传了 problems",
              all("problems=problems" in c for c in calls), True)
    i = src.find('texts.unconfirmed("预更新"')
    check("有「预更新没能确认」这条通知（标题来自 texts）", i >= 0)
    seg = src[i:i + 400]
    check("带 alert=True（进群）", "alert=True" in seg, True)
    check("日志是 WARNING 不是 ERROR", 'log.warning("预更新有 %d 项没能确认' in src and 'log.error("预更新有' not in src)
    check("明说了队列照常跑、脚本开跑时自己会查", "preupdate_unconfirmed_tail()" in seg
          and "队列照常跑，明日方舟、终末地、鸣潮开跑时自己会查" in (Path(__file__).resolve().parents[1] / "ark_relay" / "core" / "texts.py").read_text(encoding="utf-8"))

    print("\n[没有回到旧的「安静即成功」写法]")
    p = "".join(q.read_text(encoding="utf-8") for q in sorted((Path(__file__).resolve().parents[1] / "ark_relay" / "features").glob("preupdate*.py")))  # 预更新拆成了五个文件，一起看
    check("不再用「45 秒还是 idle 就算没更新」", "+ 45" not in p)
    check("靠版本列表判断检查过没有", "before_avail" in p)


def _part_preupdate_session():
    """The pre-update must not launch a GUI program from session 0."""
    import ast

    SRC_FILES = sorted((Path(__file__).resolve().parents[1] / "ark_relay" / "features").glob("preupdate*.py"))  # 拆成了五个文件
    # The functions that actually start a program.
    LAUNCHERS = {"run_okww"}
    ALLOWED = {"_spawn_detached"}   # the fallback is the one place Popen belongs
    ON_CONSOLE = {"_spawn_here"}

    def popen_calls(fn):
        out = []
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Popen"):
                out.append(node.lineno)
        return out

    def calls_named(fn, name):
        return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == name for n in ast.walk(fn))

    def main() -> int:
        tree = ast.parse("")
        for f in SRC_FILES:
            tree.body += ast.parse(f.read_text(encoding="utf-8")).body
        fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        fns_node = fns

        require("_spawn_interactive 存在", "_spawn_interactive" in fns)
        for name in sorted(LAUNCHERS):
            fn = fns.get(name)
            if fn is None:
                require(f"{name} 存在", False, "函数不见了")
                continue
            lines = popen_calls(fn)
            require(f"{name} 不直接 Popen", not lines, f"第 {lines} 行仍在直接启动")
            require(f"{name} 走 _spawn_interactive", calls_named(fn, "_spawn_interactive"))

        for name in sorted(ON_CONSOLE):
            fn = fns.get(name)
            asked = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "_here_in_console"] if fn else []
            lines = popen_calls(fn) if fn else []
            require(f"{name} 先问是不是在桌面会话里，才 Popen", bool(asked and lines) and max(asked) < min(lines),
                    f"_here_in_console 在第 {asked} 行，Popen 在第 {lines} 行")
        for name, fn in fns.items():
            if name in ALLOWED or name in LAUNCHERS or name in ON_CONSOLE:
                continue
            lines = popen_calls(fn)
            if lines:
                require(f"{name} 不应直接 Popen", False, f"第 {lines} 行")

        # The desktop is the whole point; losing this string re-breaks it silently.
        src = "".join(f.read_text(encoding="utf-8") for f in SRC_FILES)
        require("指定了 winsta0\\default 桌面", "winsta0" in src)
        require("拿的是控制台会话令牌", "WTSQueryUserToken" in src)
        # AUTO-MAS is the one of the three that must never be launched by the
        # pre-update: it is already running, and its update is an HTTP question.
        fns = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        require("有 run_automas", "run_automas" in fns)
        if "run_automas" in fns:
            require("run_automas 不启动任何进程",
                  not popen_calls(fns_node["run_automas"]) and
                  not calls_named(fns_node["run_automas"], "_spawn_interactive"))
        # AUTO-MAS installs by extracting UpdatePack_*.zip and launching
        # AUTO-MAS-Setup.exe, and install_update() refuses outright when the package
        # is not on disk. So the order matters: check, download, wait for the
        # package to settle, only then install. Calling install straight after
        # download returns would just get "未检测到更新包, 请先下载更新".
        if "run_automas" in fns_node:
            literals = [n.value for n in ast.walk(fns_node["run_automas"])
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            joined = " ".join(literals)
            for ep in ("/api/update/check", "/api/update/download",
                       "/api/update/install"):
                require(f"run_automas 会调 {ep}", ep in joined)
            require("安装前先等更新包落地",
                  calls_named(fns_node["run_automas"], "_wait_for_package"))
            has_loop = any(isinstance(n, (ast.While, ast.For))
                           for n in ast.walk(fns_node["run_automas"]))
            require("等 AUTO-MAS 后端起来（不是问一次就放弃）", has_loop)
            require("等待时长有上限", "MAS_WAIT_SECONDS" in src)
        src_all = src
        require("等包的实现在", "def _wait_for_package" in src_all)
        # The gate that makes this safe lives in the relay's AUTO-MAS process probes, not here.
        svc = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "automas_keeper.py").read_text(
            encoding="utf-8")
        require("中继在安装器运行时不抢着拉起 AUTO-MAS",
              "auto-mas-setup" in svc and "_installer_running" in svc)

        return 0 if not fails else 1

    sys.exit(main())


def _part_preupdate_span():
    """预更新通知统一成「程序 已更新：旧 → 新」。"""

    from ark_relay.features import preupdate as preupdate_common

    print("[_span：旧 → 新，缺旧版明说]")
    check("正常", preupdate_common._span("v1", "v2"), "v1 → v2")
    check("同版=旧版没读到（不许吞成一个版本号）", preupdate_common._span("v2", "v2"), "（旧版本没读到）→ v2")
    check("旧版没读到要明说", preupdate_common._span("", "v2"), "（旧版本没读到）→ v2")

    tmpdir()
    print("[每段文案同一种形状]")
    import re
    shape = re.compile(r"^(AUTO-MAS|OK-WW) (已|有)更新：\S+ → \S+")
    for msg in [f"AUTO-MAS 有更新：{preupdate_common._span('v5.5.0-beta.1', 'v5.5.0')}（安装中，装完自动重启）",
                f"OK-WW 已更新：{preupdate_common._span('v3.6.6-beta.1', 'v3.6.6')}"]:
        check(msg, bool(shape.match(msg)), True)


def _part_preupdate_token():
    """The service host's expected token failure (winerror 1314) is not a WARNING."""
    import logging
    import types

    class WinErr(Exception):
        def __init__(self, code):
            super().__init__(code, "WTSQueryUserToken", "客户端没有所需的特权。")
            self.winerror = code

    def run(code, tcb=True):
        fake = {n: types.ModuleType(n) for n in ("win32con", "win32process", "win32profile", "win32ts")}
        fake["win32ts"].WTSGetActiveConsoleSessionId = lambda: 1
        saved = {n: sys.modules.get(n) for n in fake}
        sys.modules.update(fake)
        from ark_relay.features import preupdate as pc

        def boom(session):
            raise WinErr(code)

        took = []
        old_tok, old_fb, old_tcb = pc._console_primary_token, pc._spawn_fallback, pc._tcb_enabled
        pc._console_primary_token = boom
        pc._tcb_enabled = lambda: tcb
        pc._spawn_fallback = lambda *a, **k: took.append(True) or True
        records = []
        h = logging.Handler()
        h.emit = records.append
        pc.log.addHandler(h)
        try:
            ok = pc._spawn_interactive(Path("C:/ok-ww/ok-ww.exe"), Path("C:/ok-ww"), ())
        finally:
            pc.log.removeHandler(h)
            pc._console_primary_token, pc._spawn_fallback, pc._tcb_enabled = old_tok, old_fb, old_tcb
            for n, m in saved.items():
                if m is None:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = m
        return ok, took, records

    # The machine's real case: the service host holds no SE_TCB_NAME - the token route is not tried at all.
    ok, took, recs = run(1314, tcb=False)
    require("没有权限：直接走计划任务", ok and took == [True])
    require("没有权限：没有 WARNING", not [r for r in recs if r.levelno >= logging.WARNING],
            str([(r.levelname, r.getMessage()) for r in recs]))
    ok, took, recs = run(1314)
    require("1314：走计划任务", ok and took == [True])
    require("1314：没有 WARNING", not [r for r in recs if r.levelno >= logging.WARNING],
            str([(r.levelname, r.getMessage()) for r in recs]))
    ok, took, recs = run(5)
    require("别的错：照样走计划任务", ok and took == [True])
    require("别的错：仍是 WARNING", any(r.levelno == logging.WARNING for r in recs))
    if fails:
        print("FAILED:", fails)
        sys.exit(1)


def _part_preupdate_unknown_not_fine():
    """Pre-update: "could not tell" must reach the problem list, never read as fine."""
    import os

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))

    from ark_relay.features import preupdate as C
    from ark_relay.features import preupdate as O
    from ark_relay.features import preupdate as A

    # ── 1. pywin32 import failure must not bypass require_console ──────────────
    # Force the ImportError even if this ever runs on Windows with pywin32 present.
    WIN32 = ("win32con", "win32process", "win32profile", "win32ts")
    saved_mods = {m: sys.modules.get(m) for m in WIN32}
    for m in WIN32:
        sys.modules[m] = None   # `import m` now raises ImportError

    calls = []
    orig_task, orig_detached = C._spawn_via_task, C._spawn_detached
    C._spawn_detached = lambda exe, cwd, args=(): calls.append("detached") or True
    exe = TMP / "ok-ww.exe"
    exe.write_bytes(b"")
    try:
        print("[pywin32 missing, scheduled task also fails, require_console=True]")
        C._spawn_via_task = lambda exe, cwd, args=(): calls.append("task") or False
        got = C._spawn_interactive(exe, TMP, require_console=True, minimized=True)
        check("refuses instead of launching into session 0", got, False)
        check("tried the scheduled task, never the plain launch", calls, ["task"])

        print("\n[pywin32 missing, scheduled task works]")
        calls.clear()
        C._spawn_via_task = lambda exe, cwd, args=(): calls.append("task") or True
        got = C._spawn_interactive(exe, TMP, require_console=True)
        check("launched through the scheduled task", (got, calls), (True, ["task"]))

        print("\n[pywin32 missing, require_console=False (MaaEnd) keeps its fallback]")
        calls.clear()
        C._spawn_via_task = lambda exe, cwd, args=(): calls.append("task") or False
        got = C._spawn_interactive(exe, TMP)
        check("task first, then plain launch", (got, calls), (True, ["task", "detached"]))

        print("\n[OK-WW pre-update with pywin32 missing: the 08-25 morning]")
        calls.clear()
        patched = {"_okww_state": lambda root: ("v3.6.4", "", "", ()),
                   "_okww_stamp": lambda root: 0.0,
                   "_okww_quiesce": lambda *a, **k: None,
                   "_okww_autostart": lambda root, value: True,
                   # (new version, checked, error, stuck, latest list) - preupdate_okww._okww_await_update
                   "_okww_await_update": lambda *a, **k: ("", False, "", "", ()),
                   "_okww_report": lambda *a, **k: None,
                   "_close": lambda *a, **k: None}
        saved_o = {k: getattr(O, k) for k in patched}
        for k, v in patched.items():
            setattr(O, k, v)
        try:
            problems = []
            note = O.run_okww(TMP, budget_s=1, problems=problems)
        finally:
            for k, v in saved_o.items():
                setattr(O, k, v)
        check("nothing reported as updated", note, "")
        check("never launched into session 0", "detached" in calls, False)
        check("problem list says the check did not happen",
              any("没有检查更新" in p for p in problems), True)
    finally:
        C._spawn_via_task, C._spawn_detached = orig_task, orig_detached
        for m, v in saved_mods.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v

    # ── 2. AUTO-MAS answers that are not a verdict ─────────────────────────────
    # Upstream error body for a failed check (app/api/update.py:63-72, c6ca4fb).
    # Field set and the message format f"{type(e).__name__}: {e}" are upstream's;
    # the message text is illustrative - no real error body has been captured
    # (relay.log only logs our verdict, not AUTO-MAS's answer).
    CHECK_ERROR = {"code": 500, "status": "error",
                   "message": "ConnectError: All connection attempts failed",
                   "if_need_update": False, "latest_version": "", "update_info": {}}
    # Upstream OutBase on a failed download/install (update.py:100-102, 177-179).
    OUT_ERROR = {"code": 500, "status": "error", "message": "RuntimeError: boom"}
    CHECK_UPDATE = {"code": 200, "status": "success", "message": "操作成功",
                    "if_need_update": True, "latest_version": "v5.5.0-beta.5",
                    "update_info": {}}

    def run_mas(answers, *, pack=Path("UpdatePack_v5.5.0-beta.5.zip")):
        """Run run_automas against scripted answers; returns (note, problems, paths posted, waits)."""
        posted, waits = [], []

        def fake_post(path, body=None):
            posted.append(path)
            a = answers.get(path, {})
            if isinstance(a, Exception):
                raise a
            return a

        saved = (A._mas_post, A._automas_version, A._live_version,
                 A._wait_for_package, A._wait_for_version)
        A._mas_post = fake_post
        A._automas_version = lambda _root: "v5.5.0-beta.4"
        A._live_version = lambda: ""
        A._wait_for_package = lambda _root, _deadline, *_a: waits.append("package") or pack
        A._wait_for_version = lambda want, deadline, *_a: waits.append("version") or "v5.5.0-beta.4"
        try:
            problems = []
            note = A.run_automas(TMP, budget_s=1, problems=problems)
        finally:
            (A._mas_post, A._automas_version, A._live_version,
             A._wait_for_package, A._wait_for_version) = saved
        return note, problems, posted, waits

    print("\n[AUTO-MAS check fails: HTTP 200, code 500, if_need_update=False]")
    note, problems, posted, _ = run_mas({"/api/update/check": CHECK_ERROR})
    check("not reported as 无需更新 - one problem recorded", len(problems), 1)
    check("problem says the check did not happen",
          bool(problems) and "没有检查更新" in problems[0], True)
    check("problem carries AUTO-MAS's own message",
          bool(problems) and "ConnectError" in problems[0], True)
    check("no download attempted", "/api/update/download" in posted, False)

    print("\n[AUTO-MAS check answer without if_need_update]")
    _, problems, _, _ = run_mas({"/api/update/check": {"latest_version": "v5.5.0"}})
    check("missing field is a problem, not 无需更新",
          len(problems) == 1 and "if_need_update" in problems[0], True)

    print("\n[AUTO-MAS genuinely current]")
    note, problems, posted, _ = run_mas({"/api/update/check": {
        "code": 200, "status": "success", "message": "操作成功",
        "if_need_update": False, "latest_version": "v5.5.0-beta.4", "update_info": {}}})
    check("no problem, no note, no download",
          (note, problems, "/api/update/download" in posted), ("", [], False))

    print("\n[AUTO-MAS download refused (code 409 in HTTP 200)]")
    _, problems, _, waits = run_mas({
        "/api/update/check": CHECK_UPDATE,
        # update.py:91-94, verbatim
        "/api/update/download": {"code": 409, "status": "error",
                                 "message": "已有更新任务在进行中, 请勿重复操作"}})
    check("recorded as 下载没能启动", len(problems) == 1 and "下载没能启动" in problems[0], True)
    check("did not wait out the download budget", "package" in waits, False)

    print("\n[AUTO-MAS install request raises]")
    note, problems, _, waits = run_mas({
        "/api/update/check": CHECK_UPDATE,
        "/api/update/install": OSError("connection reset")})
    check("install failure is in the problem list",
          len(problems) == 1 and "安装没能启动" in problems[0], True)
    check("nothing reported as updated", note, "")

    print("\n[AUTO-MAS install answers code 500 in HTTP 200]")
    note, problems, _, waits = run_mas({
        "/api/update/check": CHECK_UPDATE, "/api/update/install": OUT_ERROR})
    check("install error body is in the problem list",
          len(problems) == 1 and "安装没能启动" in problems[0], True)
    check("did not wait for a restart that was never started", "version" in waits, False)


def _part_okww_shape():
    """A pinned OK-WW copy survives an upstream change that is only words (ledger #130; dispatch
relay-opt-round3-1108 O-02).
    """
    import ast
    import re

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parents[0]))
    sys.path.insert(0, str(HERE))

    from ark_relay.core import texts
    from ark_relay.features import okww_overlay as ov


    INST = fx_dir(HERE, "gamesim") / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task"
    DAILY = (INST / "DailyTask.py.txt").read_text(encoding="utf-8")


    def overrides_shape():
        """The overrides file's own _shape_text, without OK-WW: only its shape helpers, run here."""
        tree = ast.parse(ov.source_text())
        keep = {"_LOG_CALLS", "_canon", "_is_text", "_WordsOut", "_shape_text"}
        body = [n for n in tree.body if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in keep)
                or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in keep for t in n.targets))]
        ns = {}
        imports = ast.parse("import ast\nimport hashlib\nimport textwrap\n").body
        exec(compile(ast.Module(body=imports + body, type_ignores=[]), "ark_overrides.py", "exec"), ns)
        return ns["_shape_text"]


    print("[两边算的是同一个形状]")
    theirs = overrides_shape()
    src = tmpdir() / "src"
    src.mkdir()
    for f in INST.glob("*.py.txt"):
        (src / f.name[:-4]).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    classes = ov._classes(src)
    samples = []
    for cls, (lines, methods, _bases) in classes.items():
        for name in methods:
            samples.append(ov._method_text(classes, cls, name))
    check("扫到了很多方法", len(samples) > 50, True)
    check("每一个方法两边算的都一样", [i for i, t in enumerate(samples) if theirs(t) != ov._shape_text(t)], [])
    check("没有一个算成空的", [i for i, t in enumerate(samples) if not ov._shape_text(t)], [])

    print("\n[钉住的形状就是装着的 v3.7.14-beta.2 那几段]")
    pinned = ov.shapes()
    check("覆盖文件里有五处", sorted(pinned), sorted(["DailyTask.claim_daily", "DailyTask.claim_battle_pass",
                                                  "DailyTask.get_total_daily_points",
                                                  "FarmEchoTask.click_team_challenge", "BaseWWTask.get_stamina"]))
    for label, want in pinned.items():
        cls, name = label.split(".")
        # FarmEchoTask reaches BaseWWTask's click_team_challenge through src/combat/, which the
        # fixture does not carry: read it where it is defined.
        text = ov._method_text(classes, cls, name) or ov._method_text(classes, "BaseWWTask", name)
        check(f"{label} 对得上", ov._shape_text(text), want)
    check("没有正文就没有形状（不是空文本的哈希）", (ov._shape_text(""), theirs("")), ("", ""))
    check("这五处都是钉了哈希的", sorted(set(pinned) - {f"{c}.{m}" for c, m, _s, _a in ov.pins()}), [])


    def okww(daily_text):
        root = tmpdir()
        d = root.joinpath(*ov._SRC)
        d.mkdir(parents=True)
        for f in INST.glob("*.py.txt"):
            (d / f.name[:-4]).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        (d / "DailyTask.py").write_text(daily_text, encoding="utf-8")
        return root


    print("\n[只改了字（v3.7.13 那样）：哈希变了、形状没变 —— 照样换上，只说一次，不算毛病]")
    WORDS = re.sub(r"self\.tr\(('[^']*')\)", r"\1", DAILY)
    WORDS = WORDS.replace("    def claim_daily(self):\n", "    def claim_daily(self):\n        # a comment upstream added\n", 1)
    WORDS = WORDS.replace("self.log_info('claim daily reward via  coordinate')",
                          "self.log_info(f'claim daily reward via coordinate {1}')")
    check("真的改了 claim_daily 和 claim_battle_pass 的文字", WORDS != DAILY, True)
    found = {d["what"]: d for d in ov.drift(okww(WORDS))}
    check("两处都看出了哈希变化", sorted(found), ["DailyTask.claim_battle_pass", "DailyTask.claim_daily"])
    check("两处都算适配（只改了字）", [(d["adapt"], d["words"]) for d in found.values()], [(True, True)] * 2)
    state = tmpdir()
    line = ov.drift_line(okww(WORDS), state)
    check("那句话说只改了日志文字、照样换上", "只改了" in line and "照样换上" in line, True)
    check("……不带「对不上」", "对不上" in line, False)
    check("……标题是 🩹（不是 ⚠️）", texts.patches(1, [line]).startswith("🩹"), True)
    check("……第二次开机不再说", ov.drift_line(okww(WORDS), state), "")

    print("\n[改了坐标或调用：形状变了 —— 照旧不换、每次开机都说]")
    for label, changed in (("坐标", DAILY.replace("self.click_relative(0.86, 0.05)", "self.click_relative(0.87, 0.05)")),
                           ("少了一步", DAILY.replace("self.ensure_main()", "pass", 1))):
        check(f"{label}：确实改了正文", changed != DAILY, True)
        d = [x for x in ov.drift(okww(changed)) if not x["adapt"]]
        check(f"{label}：算不上（跳过）", bool(d) and all(not x["words"] for x in d), True)
        state = tmpdir()
        first = ov.drift_line(okww(changed), state)
        check(f"{label}：说对不上、等重抄", "对不上" in first and "等我们重抄" in first, True)
        check(f"{label}：第二次开机照样说", ov.drift_line(okww(changed), state), first)

    print("\n[文字里的功能名不是日志：改了照样算变了]")
    FEATURE = DAILY.replace("'gray_book_quest'", "'gray_book_quest_v2'")
    if FEATURE != DAILY:
        found = {d["what"]: d for d in ov.drift(okww(FEATURE))}
        check("改了找图用的名字：不算只改了字", [d["words"] for d in found.values()], [False] * len(found))
    else:
        print("  · (the fixture names no gray_book_quest feature in DailyTask)")


def _part_gameupdate_main():  # noqa: C901
    """大版本更新自动化：决策逻辑用假桌面/假命令跑一遍，不碰网络不碰机器。"""
    import json
    import types

    from ark_relay.features import gameupdate as gu
    from ark_relay.features import gameupdate_games as gug
    from ark_relay.core.desktop import Line, Screen

    class FakeDesk:
        """按顺序回放屏幕；记录点了什么。"""
        def __init__(self, screens):
            self.screens = list(screens); self.clicks = []
        def _scr(self):
            texts = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
            return Screen([Line(t, 100, 100 + 30 * i, 80, 20) for i, t in enumerate(texts)], Path("x.png"))
        def read(self, focus=None, settle_ms=0):
            return self._scr()
        def click_text(self, text, focus=None):
            self.clicks.append(text); return True
        def click(self, x, y, focus=None):
            self.clicks.append((x, y)); return True

    spawned = []
    gug._spawn = lambda exe, cwd=None: spawned.append(exe.name) or True
    gug.kill = lambda *names: None
    gu.kill = lambda *names: None
    nosleep = lambda s: None  # noqa: E731

    print("[终末地：已是「开始游戏」就什么都不做]")
    d = FakeDesk([["登录", "开始游戏"]])
    out = gu.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), sleep=nosleep)
    check("不更新", out, ""); check("没点任何东西", d.clicks, [])

    print("[终末地：更新→装完→拉游戏→重启→标题画面]")
    d = FakeDesk([["登录", "更新游戏"], ["正在下载"], ["安装中"], ["开始游戏"],
                  ["资源初始化更新完成，请重启游戏", "确认"], ["正在编译着色器"], ["点击任意位置继续"]])
    probs = []
    out = gu.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), poll_s=0, problems=probs, sleep=nosleep)
    check("报了更新", out, "终末地 客户端已通过启动器更新")
    check("点击顺序", d.clicks, ["更新游戏", "开始游戏", "确认", "开始游戏"])
    check("重启经启动器，没直接拉 Endfield.exe", "Endfield.exe" in spawned, False)
    check("没有问题", probs, [])

    print("[终末地：读不到按钮要报问题]")
    d = FakeDesk([["登录", "公告"]]); probs = []
    out = gu.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), problems=probs, sleep=nosleep)
    check("空", out, ""); check("问题里说没读到", any("没读到按钮" in x for x in probs), True)

    ST = tmpdir()

    print("[登记：哪个游戏要更新]")
    from datetime import datetime as _dt
    check("空", gu.pending(ST), {})
    check("登记", gu.mark_pending(ST, "终末地", "公告说今天版本更新"), True)
    check("重复登记不算", gu.mark_pending(ST, "终末地", "又来"), False)
    check("读回", gu.pending(ST), {"终末地": "公告说今天版本更新"})
    gu.clear_pending(ST, "终末地"); check("清掉", gu.pending(ST), {})

    print("[开机只做便宜判断：不开启动器，只登记]")
    class Cfg: pass
    cfg = Cfg(); cfg.state_dir = ST; cfg.maa_dir = None; cfg.maaend_dir = None; cfg.okww_dir = None
    now = _dt(2026, 9, 2, 8, 46)
    notes, probs = gu.boot_check(cfg, budget_s=600, now=now, maint_sources={}, hint=lambda n: "官方公告：今天 09:00 版本更新")
    check("公告有版本更新 → 登记终末地", gu.pending(ST), {"终末地": "官方公告：今天 09:00 版本更新"})
    check("开机不发更新通知", notes, [])
    gu.clear_pending(ST, "终末地")
    notes, probs = gu.boot_check(cfg, budget_s=600, now=now, maint_sources={}, hint=lambda n: "")
    check("公告没说 → 不登记", gu.pending(ST), {})

    print("[队列跑完后：更新 + 只在当天没跑成时重跑]")
    cfg.maaend_dir = ST / "maaend"; (cfg.maaend_dir / "config").mkdir(parents=True, exist_ok=True)
    game = ST / "hg" / "games" / "Endfield Game" / "Endfield.exe"; game.parent.mkdir(parents=True, exist_ok=True); game.write_bytes(b"")
    (ST / "hg" / "Launcher.exe").write_bytes(b"")
    (cfg.maaend_dir / "config" / "mxu-MaaEnd.json").write_text(json.dumps({"connectedProgramPath": str(game)}), encoding="utf-8")
    (ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "MaaEnd", "ok": False, "raw": {"maaend_unreachable": True}}) + "\n", encoding="utf-8")
    gu.mark_pending(ST, "终末地", "今天 MaaEnd 进不了游戏")
    dispatched = []
    d = FakeDesk([["登录", "更新游戏"], ["正在下载"], ["开始游戏"], ["请重启游戏", "确认"], ["点击任意位置继续"]])
    notes, probs, reran = gu.run_deferred(cfg, now=now, desk=d, dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=nosleep)
    check("更新通知带依据", notes, ["终末地 客户端已通过启动器更新（依据：今天 MaaEnd 进不了游戏）"])
    check("当天因客户端过时没跑成 → 重跑 MaaEnd", reran, ["MaaEnd"])
    check("登记已清", gu.pending(ST), {})
    # 当天已经成功过：启动器说已是最新，不重跑
    (ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "MaaEnd", "ok": True, "raw": {}}) + "\n", encoding="utf-8")
    gu.mark_pending(ST, "终末地", "公告说今天版本更新")
    dispatched.clear()
    notes, probs, reran = gu.run_deferred(cfg, now=now, desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=nosleep)
    check("已是最新 → 不发更新通知", notes, [])
    check("当天成功过 → 不重跑", reran, [])
    check("登记也清了", gu.pending(ST), {})

    print("[普通任务失败不重跑（09-02 晚上把用户挤下线的教训）]")
    (ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "MaaEnd", "ok": False, "failed_tasks": ["赠送干员礼物"], "raw": {}}) + "\n", encoding="utf-8")
    gu.mark_pending(ST, "终末地", "公告说今天版本更新")
    dispatched.clear()
    notes, probs, reran = gu.run_deferred(cfg, now=now, desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=nosleep)
    check("普通失败 → 不重跑", reran, [])
    check("登记清掉", gu.pending(ST), {})
    notes, probs = gu.boot_check(cfg, budget_s=600, now=now, maint_sources={}, hint=lambda n: "官方公告：今天 09:00 版本更新")
    check("普通失败的日子开机仍会登记（由 needs_rerun 拦）", gu.pending(ST), {"终末地": "官方公告：今天 09:00 版本更新"})
    gu.clear_pending(ST, "终末地")
    (ST / "gameupdate-off.flag").write_text("", encoding="utf-8")
    gu.mark_pending(ST, "终末地", "x")
    check("总开关关着 → 什么都不做", gu.run_deferred(cfg, now=now, desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: (True, "ok"), sleep=nosleep), ([], [], []))
    (ST / "gameupdate-off.flag").unlink(); gu.clear_pending(ST, "终末地")

    print("[鸣潮：客户端交给 AUTO-MAS 更新（10b），中继不开启动器，只在等不到窗口时重跑]")
    (ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "OK-WW", "ok": False, "raw": {"okww_unreachable": True}}) + "\n", encoding="utf-8")
    gu.mark_pending(ST, "鸣潮", "官方公告：今天更新维护")
    dispatched.clear(); spawned.clear()
    d = FakeDesk([["公告", "立即更新"]])
    notes, probs, reran = gu.run_deferred(cfg, now=now, desk=d, dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=nosleep)
    check("没开启动器", spawned, [])
    check("没点任何东西", d.clicks, [])
    check("没有更新通知、没有问题", (notes, probs), ([], []))
    check("等不到窗口那种失败 → 重跑 OK-WW（AUTO-MAS 在这趟里更新）", reran, ["OK-WW"])
    check("登记已清", gu.pending(ST), {})
    (ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "OK-WW", "ok": False, "raw": {}}) + "\n", encoding="utf-8")
    gu.mark_pending(ST, "鸣潮", "x")
    notes, probs, reran = gu.run_deferred(cfg, now=now, desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: (True, "ok"), sleep=nosleep)
    check("普通失败 → 不重跑 OK-WW", reran, [])
    check("鸣潮的旧更新流程已删", any(hasattr(m, n) for m in (gu, gug)
                                       for n in ("update_wuwa", "wuwa_launcher", "wuwa_update_day")), False)

    print("[维护日：窗口落盘、撞上算维护、队列后等开服再补跑]")
    from datetime import timedelta as _td
    w_start = _dt(2026, 9, 4, 6, 0, tzinfo=gu.SERVER_TZ); w_end = _dt(2026, 9, 4, 12, 0, tzinfo=gu.SERVER_TZ)
    gu.save_windows(ST, {"明日方舟": (w_start, w_end, "官方公告：09-04 06:00–12:00 停机维护")})
    check("09:00 的 MAA 撞上维护", bool(gu.in_maintenance(ST, "MAA", _dt(2026, 9, 4, 9, 0, tzinfo=gu.SERVER_TZ))), True)
    check("开服 45 分钟内仍算（客户端还没更新）", bool(gu.in_maintenance(ST, "MAA", _dt(2026, 9, 4, 12, 30, tzinfo=gu.SERVER_TZ))), True)
    check("下午就不算", gu.in_maintenance(ST, "MAA", _dt(2026, 9, 4, 15, 0, tzinfo=gu.SERVER_TZ)), "")
    check("别的游戏不受影响", gu.in_maintenance(ST, "MaaEnd", _dt(2026, 9, 4, 9, 0, tzinfo=gu.SERVER_TZ)), "")
    # The row as the collector books it: the round rule (makeup.maa_round_work_done)
    # reads run_id / started / finished, and a maintenance attempt clears only when its
    # log shows no fight (fight_count 0).
    (ST / "ledger-2026-09-04.jsonl").write_text(json.dumps({
        "script": "MAA", "run_id": "2026-09-04/maa/MAA-09-00-01", "started": "2026-09-04T09:00:01+08:00",
        "finished": "2026-09-04T09:03:10+08:00", "ok": False, "failed_tasks": ["MAA 在完成任务前中止"],
        "raw": {"maintenance": "官方公告", "fight_count": 0}}) + "\n", encoding="utf-8")
    check("撞上维护的失败 → 该补跑", gu.needs_rerun(ST, _dt(2026, 9, 4, 13, 0), "MAA"), True)
    cfg.maa_dir = None
    gu.mark_pending(ST, "明日方舟", "官方公告")
    slept = []
    ticks0 = [_dt(2026, 9, 4, 13, 0, tzinfo=gu.SERVER_TZ)]
    def clk0():
        ticks0.append(ticks0[-1] + _td(minutes=10)); return ticks0[-1]
    notes, probs, reran = gu.run_deferred(cfg, now=_dt(2026, 9, 4, 13, 0, tzinfo=gu.SERVER_TZ), desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: (True, "ok"), sleep=lambda s: slept.append(s), clock=clk0)
    check("明日方舟不用准备客户端：开服后直接补跑 MAA", (reran, 600 in slept, probs), (["MAA"], False, []))
    # 终末地：客户端准备好了、离开服还远 → 关游戏、一分钟一分钟等到开服、缓 2 分钟、再补跑
    gu.save_windows(ST, {"终末地": (_dt(2026, 9, 4, 6, 0, tzinfo=gu.SERVER_TZ), _dt(2026, 9, 4, 12, 0, tzinfo=gu.SERVER_TZ), "官方公告")})
    (ST / "ledger-2026-09-04.jsonl").write_text(json.dumps({"script": "MaaEnd", "ok": False, "raw": {"maintenance": "官方公告"}}) + "\n", encoding="utf-8")
    gu.mark_pending(ST, "终末地", "官方公告")
    slept.clear(); dispatched.clear()
    killed = []
    gu.kill = lambda *names: killed.append(names)
    ticks1 = [_dt(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ)]
    def clk1():
        ticks1.append(ticks1[-1] + _td(minutes=1)); return ticks1[-1]
    notes, probs, reran = gu.run_deferred(cfg, now=_dt(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ), desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=lambda s: slept.append(s), clock=clk1)
    check("先准备好再等开服：一分钟一分钟等，开服后缓 2 分钟，然后补跑", (slept.count(60) >= 1, 120 in slept, reran), (True, True, ["MaaEnd"]))
    check("离开服还远：只关终末地，不碰鸣潮（s18 F2）", killed, [("Endfield.exe",)])
    gu.save_windows(ST, {})
    gu.clear_pending(ST, "明日方舟")

    print("[白天维护 10:00–16:00，早班 09:00 在开服前就跑完了：不等到 16:02，早班照常关机（清单-1108 A-03）]")
    _ledger_0904 = (ST / "ledger-2026-09-04.jsonl").read_text(encoding="utf-8")
    (ST / "ledger-2026-09-04.jsonl").write_text(json.dumps({
        "script": "MAA", "run_id": "2026-09-04/maa/MAA-09-00-01", "started": "2026-09-04T09:00:01+08:00",
        "finished": "2026-09-04T09:40:10+08:00", "ok": True, "raw": {}}) + "\n", encoding="utf-8")
    gu.save_windows(ST, {"明日方舟": (_dt(2026, 9, 4, 10, 0, tzinfo=gu.SERVER_TZ), _dt(2026, 9, 4, 16, 0, tzinfo=gu.SERVER_TZ), "官方公告：09-04 10:00–16:00")})
    gu.mark_pending(ST, "明日方舟", "官方公告")
    slept.clear(); dispatched.clear()
    ticks3 = [_dt(2026, 9, 4, 9, 45, tzinfo=gu.SERVER_TZ)]
    def clk3():
        ticks3.append(ticks3[-1] + _td(minutes=1)); return ticks3[-1]
    notes, probs, reran = gu.run_deferred(cfg, now=_dt(2026, 9, 4, 9, 45, tzinfo=gu.SERVER_TZ), desk=FakeDesk([["x"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=lambda s: slept.append(s), clock=clk3)
    check("早班已跑完、不用补跑 → 一分钟都不等", (slept, dispatched, reran, probs), ([], [], [], []))
    check("……登记清掉，线程马上结束，早班的关机不被扣住", "明日方舟" in gu.pending(ST), False)
    check("终末地照旧由中继更新客户端（这条不放过它）", (gu.relay_updates_client("终末地"), gu.relay_updates_client("明日方舟")), (True, False))
    gu.save_windows(ST, {})
    (ST / "ledger-2026-09-04.jsonl").write_text(_ledger_0904, encoding="utf-8")

    print("[维护日：队列时刻落在窗口里 → 摘掉；补跑完加回]")
    gu.save_windows(ST, {})
    (ST / "queue-skips.json").unlink(missing_ok=True)
    import ark_relay.core.plan as _plan
    _plan_backup = _plan.schedule
    _plan.schedule = lambda d: [{"name": "早班", "times": ["09:00"], "items": ["s1"]}, {"name": "晚班", "times": ["21:30"], "items": ["s1"]}]
    cfg.automas_dir = ST
    skipped = []
    src_ak = {"明日方舟": lambda n: (_dt(2026, 9, 4, 6, 0, tzinfo=gu.SERVER_TZ), _dt(2026, 9, 4, 12, 0, tzinfo=gu.SERVER_TZ), "官方公告：09-04 06:00–12:00")}
    notes, probs = gu.boot_check(cfg, budget_s=600, now=_dt(2026, 9, 4, 8, 46, tzinfo=gu.SERVER_TZ), maint_sources=src_ak, hint=lambda n: "",
                                 skipper=lambda q, sc: skipped.append((q, sc)) or {"queue": q, "queueId": "Q", "script": sc, "scriptId": "S", "position": 0, "queueItemId": "I", "days": ["Friday"]})
    check("早班 09:00 在窗口里 → 从早班摘掉 MAA", skipped, [("早班", "MAA")])
    check("晚班 21:30 不在窗口里 → 不摘", len(skipped), 1)
    check("登记了明日方舟", "明日方舟" in gu.pending(ST), True)
    check("摘掉的记在案", [r["script"] for r in gu.skips(ST)], ["MAA"])
    check("被摘掉的即使没失败记录也要补跑", gu.needs_rerun(ST, _dt(2026, 9, 4, 13, 0), "MAA"), True)
    restored = []
    dispatched.clear()
    ticks = [_dt(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ)]
    def clk2():
        ticks.append(ticks[-1] + _td(minutes=1)); return ticks[-1]
    gu.save_windows(ST, {"明日方舟": (_dt(2026, 9, 4, 6, 0, tzinfo=gu.SERVER_TZ), _dt(2026, 9, 4, 12, 0, tzinfo=gu.SERVER_TZ), "官方公告：09-04 06:00–12:00")})
    notes, probs, reran = gu.run_deferred(cfg, now=_dt(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ), desk=FakeDesk([["x"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=lambda s: None, clock=clk2)
    check("明日方舟：等到开服再补跑被摘掉的 MAA（客户端交给 AUTO-MAS）", (reran, dispatched, probs), (["MAA"], ["MAA"], []))
    check("明日方舟等开服：什么游戏都不关（终末地、鸣潮可能是他自己开的，s18 F2）", killed, [("Endfield.exe",)])
    gu.kill = lambda *names: None
    gu.save_windows(ST, {})
    gu.clear_pending(ST, "明日方舟")
    done = gu.restore_skips(ST, restorer=lambda rec: restored.append(rec["script"]) or True)
    check("加回", (done, restored, gu.skips(ST)), (["MAA→「早班」"], ["MAA"], []))
    _plan.schedule = _plan_backup

    print("[停一切停掉的那趟既不算成功也不算失败（2026-09-30 鸣潮 3.7 维护日漏接）]")
    import logging

    class _Keep(logging.Handler):
        def __init__(self):
            super().__init__(logging.INFO); self.recs = []
        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage(), record.exc_info is not None))

    keep = _Keep(); gu.log.addHandler(keep); gu.log.setLevel(logging.INFO)
    T = gu.SERVER_TZ
    L930 = [
        {"script": "MAA", "run_id": "2026-09-30/maa/MAA-05-01-02", "started": "2026-09-30T05:01:02+08:00",
         "finished": "2026-09-30T05:39:10+08:00", "ok": True, "raw": {}},
        {"script": "OK-WW", "run_id": "2026-09-30/wuwa/OK-WW-09-19-00", "started": "2026-09-30T09:19:00+08:00",
         "finished": "2026-09-30T09:20:00+08:00", "ok": False,
         "raw": {"evidence_page": "x", "general_result": "失败", "okww_error": "进不了游戏"}},
        {"script": "OK-WW", "run_id": "2026-09-30/wuwa/OK-WW-09-30-00", "started": "2026-09-30T09:30:00+08:00",
         "finished": "2026-09-30T09:31:00+08:00", "ok": False,
         "raw": {"evidence_page": "x", "general_result": "失败", "okww_error": "进不了游戏"}},
        {"script": "OK-WW", "run_id": "2026-09-30/wuwa/OK-WW-05-40-56", "started": "2026-09-30T09:40:56+08:00",
         "finished": "2026-09-30T09:47:00+08:00", "ok": True,
         "raw": {"evidence_page": "x", "general_result": "Success!", "manual_stop": "09:46 停一切"}},
        {"script": "MaaEnd", "run_id": "2026-09-30/endfield/MaaEnd-05-46-45", "started": "2026-09-30T09:46:45+08:00",
         "finished": "2026-09-30T09:47:10+08:00", "ok": False,
         "raw": {"maaend_result": "中止", "manual_stop": "09:46 停一切"}},
    ]

    def _ledger930(rows):
        (ST / "ledger-2026-09-30.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                                     encoding="utf-8")

    _ledger930(L930)
    n930 = _dt(2026, 9, 30, 8, 49, 50, tzinfo=T)
    check("last_run_ok(OK-WW)：跳过停一切那趟，看前一趟 → False", gu.last_run_ok(ST, n930, "OK-WW"), False)
    check("last_run_ok(MaaEnd)：唯一一趟是停一切 → 等于今天没跑过", gu.last_run_ok(ST, n930, "MaaEnd"), None)
    check("last_run_ok(MAA) 不受影响", gu.last_run_ok(ST, n930, "MAA"), True)
    check("needs_rerun(OK-WW)：前一趟是普通失败 → 不补跑", gu.needs_rerun(ST, n930, "OK-WW"), False)
    check("needs_rerun(MaaEnd)：只有停一切那趟 → 不补跑", gu.needs_rerun(ST, n930, "MaaEnd"), False)
    _ledger930(L930[:3] + [dict(L930[2], raw={"okww_unreachable": True})] + L930[3:])
    check("needs_rerun(OK-WW)：停一切之前那趟是进不了游戏，但今天被停一切停过 → 不补跑",
          gu.needs_rerun(ST, n930, "OK-WW"), False)
    _ledger930(L930[:3] + [dict(L930[2], raw={"maintenance": "官方公告：维护"})] + L930[3:])
    check("needs_rerun(OK-WW)：前一趟带维护标记 + 最后一趟停一切 → 不补跑",
          gu.needs_rerun(ST, n930, "OK-WW"), False)
    check("stopped_today 给出按下的时刻", gu.stopped_today(ST, n930, "OK-WW"), "09:46 停一切")
    check("stopped_today：没被停过的脚本 → 空", gu.stopped_today(ST, n930, "MAA"), "")
    with (ST / "ledger-2026-09-30.jsonl").open("a", encoding="utf-8") as _f:
        _f.write('{"script": "MAA", "ok": tr\n[1, 2]\n')
    check("账目最后一行撕裂：stopped_today 仍记得停一切", gu.stopped_today(ST, n930, "OK-WW"), "09:46 停一切")
    check("账目最后一行撕裂：last_run_ok 仍看得到前面的趟", gu.last_run_ok(ST, n930, "OK-WW"), False)
    _ledger930(L930)
    _ledger930([r for r in L930 if r["script"] != "MaaEnd"][:3]
               + [dict(L930[2], run_id="2026-09-30/wuwa/OK-WW-09-35-00", raw={"okww_unreachable": True})])
    check("needs_rerun(OK-WW)：没被停过、最后一趟进不了游戏 → 照旧补跑", gu.needs_rerun(ST, n930, "OK-WW"), True)
    _ledger930(L930)
    print("[被停一切停过的脚本：run_deferred 不补跑，通知里写「已停，未补」]")
    _calls, _reran, _probs, _notes = [], [], [], []
    gu._rerun_script(types.SimpleNamespace(state_dir=ST), n930, lambda sc: _calls.append(sc) or (True, "ok"),
                     "OK-WW", _reran, _probs, _notes)
    check("没派", (_calls, _reran, _probs), ([], [], []))
    check("通知写已停未补", _notes, ["OK-WW：今天 09:46 停一切停过，已停，未补"])

    src_ww = {"鸣潮": lambda n: (_dt(2026, 9, 30, 4, 0, tzinfo=T), _dt(2026, 9, 30, 11, 0, tzinfo=T),
                                 "官方公告：「甲」3.7版本内容说明（09-30 04:00–11:00）")}
    _plan.schedule = lambda d: [{"name": "早班", "times": ["09:00"], "items": ["s1"]}, {"name": "晚班", "times": ["21:30"], "items": ["s1"]}]
    (ST / "queue-skips.json").unlink(missing_ok=True)
    for g in list(gu.pending(ST)):
        gu.clear_pending(ST, g)
    gu._store(ST).set("updates", "queue_skips", [])
    skipped = []; keep.recs.clear()
    notes, probs = gu.boot_check(cfg, budget_s=600, now=n930, maint_sources=src_ww, hint=lambda n: "",
                                 skipper=lambda q, sc: skipped.append((q, sc)) or {"queue": q, "queueId": "Q", "script": sc, "scriptId": "S", "position": 0, "queueItemId": "I", "days": ["Friday"]})
    check("今天的 5 条账本 + 鸣潮维护 → 登记鸣潮", "鸣潮" in gu.pending(ST), True)
    check("早班 09:00 在维护窗口里 → 从早班摘掉 OK-WW", skipped, [("早班", "OK-WW")])
    msgs = [m for _l, m, _e in keep.recs]
    check("日志：终末地公告说了今天没有版本更新", any("终末地公告——今天没有版本更新" in m for m in msgs), True)
    check("日志：维护公告列出鸣潮窗口", any("维护公告——鸣潮 04:00–11:00" in m for m in msgs), True)
    check("日志：维护公告登记了鸣潮", any(m.startswith("游戏更新：已登记 鸣潮 待更新（官方公告：「甲」3.7版本内容说明") for m in msgs), True)

    print("[对照：最后一趟 OK-WW 是真成功 → 不登记，日志写明原因]")
    for g in list(gu.pending(ST)):
        gu.clear_pending(ST, g)
    gu._store(ST).set("updates", "queue_skips", [])
    _ledger930(L930[:3] + [dict(L930[3], raw={"evidence_page": "x", "general_result": "Success!"})] + L930[4:])
    skipped = []; keep.recs.clear()
    notes, probs = gu.boot_check(cfg, budget_s=600, now=n930, maint_sources=src_ww, hint=lambda n: "",
                                 skipper=lambda q, sc: skipped.append((q, sc)) or None)
    check("今天真成功过 → 不登记鸣潮", "鸣潮" in gu.pending(ST), False)
    check("也不从队列摘", skipped, [])
    msgs = [m for _l, m, _e in keep.recs]
    check("日志：维护那条写「已成功过，不登记」", any("鸣潮维护——" in m and "OK-WW 今天已成功过，不登记" in m for m in msgs), True)

    print("[开机检查：公告读不到要说出来]")
    keep.recs.clear()
    gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={}, hint=lambda n: "")
    check("开机检查：没有维护也写一行", any("维护公告——今天没有游戏停服维护" in m for _l, m, _e in keep.recs), True)
    keep.recs.clear()
    def _hint_boom(n):
        raise OSError("终末地公告连不上")
    _n, _p = gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={}, hint=_hint_boom)
    check("终末地公告读挂 → warning", sum(1 for l, m, _e in keep.recs if l == logging.WARNING and "终末地公告读不到" in m), 1)
    check("终末地公告读挂 → 进 problems", _p, ["终末地：官方公告读不到，今天有没有版本更新不知道"])
    # The log must not contradict the problem: unreadable is not "no update today"
    check("终末地公告读挂 → 不再写「今天没有版本更新」",
          [m for _l, m, _e in keep.recs if "终末地公告——今天没有版本更新" in m], [])
    check("公告读挂的警告不说「当作」", [m for _l, m, _e in keep.recs if "当作今天" in m], [])
    import ark_relay.features.maintenance as _mt
    _mt_today = _mt.today
    _mt.today = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("维护模块坏了"))
    keep.recs.clear()
    gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={}, hint=lambda n: "")
    check("维护公告整体读挂 → warning", sum(1 for l, m, _e in keep.recs if l == logging.WARNING and "维护公告整体读不到" in m), 1)
    _mt.today = _mt_today

    print("[维护公告读不到：保留今天早先存的窗口，不写「今天没有维护」]")
    W_WW = (_dt(2026, 9, 30, 4, 0, tzinfo=T), _dt(2026, 9, 30, 11, 0, tzinfo=T), "官方公告：鸣潮 3.7")
    W_OLD = (_dt(2026, 9, 28, 4, 0, tzinfo=T), _dt(2026, 9, 28, 11, 0, tzinfo=T), "官方公告：前天的")
    gu.save_windows(ST, {"鸣潮": W_WW, "终末地": W_OLD})
    keep.recs.clear()
    gu.boot_check(cfg, budget_s=600, now=n930, hint=lambda n: "",
                  maint_sources={"鸣潮": lambda n: (_ for _ in ()).throw(OSError("连不上")),
                                 "明日方舟": lambda n: None})
    check("鸣潮读挂 → 今天的窗口还在", gu.windows(ST).get("鸣潮"), W_WW)
    check("前天的窗口不沿用", "终末地" in gu.windows(ST), False)
    msgs = [m for _l, m, _e in keep.recs]
    check("日志说读不到、沿用", any("维护公告读不到（鸣潮），沿用已存窗口：鸣潮 04:00–11:00" in m for m in msgs), True)
    check("日志不说今天没有维护", any("今天没有游戏停服维护" in m for m in msgs), False)
    check("沿用的窗口不再走登记（早先登记过）", "鸣潮" in gu.pending(ST), False)
    gu.save_windows(ST, {"鸣潮": W_WW})
    _mt.today = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("维护模块坏了"))
    keep.recs.clear()
    gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={}, hint=lambda n: "")
    _mt.today = _mt_today
    check("整体读挂 → 窗口也还在", gu.windows(ST).get("鸣潮"), W_WW)
    check("整体读挂 → 日志说全部读不到", any("维护公告读不到（全部），沿用已存窗口：鸣潮" in m for _l, m, _e in keep.recs), True)
    gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={"鸣潮": lambda n: None}, hint=lambda n: "")
    check("读到了、确实没有 → 窗口清掉", gu.windows(ST), {})
    for g in list(gu.pending(ST)):
        gu.clear_pending(ST, g)
    gu._store(ST).set("updates", "queue_skips", [])
    gu.save_windows(ST, {})
    _plan.schedule = _plan_backup
    gu.log.removeHandler(keep)

    print("[每次开机只跑一遍]")
    from datetime import datetime
    check("没记录→跑", gu.should_run(ST, datetime.now(), boot_id="b1"), True)
    gu.mark_run(ST, datetime.now(), boot_id="b1")
    check("同一次开机→不跑", gu.should_run(ST, datetime.now(), boot_id="b1"), False)
    check("下一次开机→跑", gu.should_run(ST, datetime.now(), boot_id="b2"), True)

    print("[桌面 Screen 匹配忽略空格]")
    s = Screen([Line("更 新 游 戏", 10, 10, 50, 20)])
    check("有", s.has("更新游戏"), True); check("中心", s.find("更新游戏").center, (35, 20))
    s3 = Screen([Line("@丹始游戏", 1324, 782, 200, 40)])
    check("错一个字仍命中（OCR 把开认成丹）", s3.find("开始游戏") is not None, True)
    check("错一个字不会串到别的按钮", s3.find("更新游戏") is None, True)
    check("两字以下不容错", Screen([Line("确人", 0, 0, 10, 10)]).find("确认") is None, True)

    print("[2026-10-06 审计：读不到 ≠ 没事]")
    from ark_relay.features import maintenance as _efs
    gu.log.addHandler(keep)
    A = tmpdir()
    acfg = Cfg(); acfg.state_dir = A; acfg.maa_dir = A / "maa"; acfg.maaend_dir = None; acfg.okww_dir = None
    acfg.automas_dir = A
    # 2. Endfield, default hint: efstatus.update_hint swallowed every error and returned "",
    #    so boot_check's own except never ran and an unreachable bulletin read as "no update".
    import urllib.request as _ur
    _uo = _ur.urlopen
    def _no_net(*a, **k):
        raise OSError("bulletin unreachable")
    _ur.urlopen = _no_net
    keep.recs.clear()
    try:
        _n, _p = gu.boot_check(acfg, budget_s=600, now=n930, maint_sources={})
    finally:
        _ur.urlopen = _uo
    check("终末地默认公告接口连不上 → problems", [x for x in _p if x.startswith("终末地")],
          ["终末地：官方公告读不到，今天有没有版本更新不知道"])
    check("efstatus 非 strict 仍返回空（handle.py 只拿它当旁证）",
          _efs.update_hint(fetch=_no_net), "")
    # 3. MAA's unreachable flag: needs_rerun("MAA") could only be true via skips / maintenance.
    _ledger_rows = [{"script": "MAA", "run_id": "2026-09-30/maa/MAA-05-01-02", "started": "2026-09-30T05:01:02+08:00",
                     "finished": "2026-09-30T05:09:10+08:00", "ok": False,
                     "failed_tasks": ["MAA 未能正确登录 PRTS"], "raw": {"maa_unreachable": True}}]
    (A / "ledger-2026-09-30.jsonl").write_text("".join(json.dumps(r) + "\n" for r in _ledger_rows), encoding="utf-8")
    check("MAA 失败且 raw 带 maa_unreachable → needs_rerun", gu.needs_rerun(A, n930, "MAA"), True)
    _ledger_rows[0]["raw"] = {"maa_error": "关卡失败"}
    (A / "ledger-2026-09-30.jsonl").write_text("".join(json.dumps(r) + "\n" for r in _ledger_rows), encoding="utf-8")
    check("MAA 普通失败 → 不重跑", gu.needs_rerun(A, n930, "MAA"), False)
    E = A / "maaend"; (E / "resource" / "pipeline").mkdir(parents=True)
    (E / "interface.json").write_text(json.dumps({"version": "v2.28.0-beta.4"}), encoding="utf-8")
    master = A / "data" / "u1" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"; master.parent.mkdir(parents=True)
    def _master(on):
        master.write_text(json.dumps({"instances": [{"tasks": [{"taskName": "AutoUseSpMedication", "enabled": on}]}]}),
                          encoding="utf-8")
    def _sp_on():
        return json.loads(master.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["enabled"]
    acfg.maaend_dir = E
    def _nodes(node):
        (E / "resource" / "pipeline" / "nodes.json").write_text(json.dumps({"AutoUseSpMedicationQuickUse": node}),
                                                                encoding="utf-8")
    for _label, _node, _shape in (
            ("认不出的写法（没有 recognition）", {"next": ["AutoUseSpMedicationRewardsConfirm"], "action": "Click"}, "unknown"),
            ("坏的写法（beta.5，原样摘自 gameupdate.py 的注释）",
             {"recognition": {"param": {"all_of": ["YellowConfirmButtonType2", {"param": {}, "type": "OCR"}]}}}, "broken"),
            ("修好的写法（PR #5453）",
             {"recognition": {"param": {"all_of": ["YellowConfirmButtonType2", {"recognition": {"param": {}, "type": "OCR"}}]}}},
             "")):
        _nodes(_node)
        _master(True)
        check(f"{_label} → 每次开机都查，要报的就报", (gu.spmed_check(acfg), gu.spmed_check(acfg)), (_shape, _shape))
        check(f"{_label} → 任务开着就不动", _sp_on(), True)
    gu.log.removeHandler(keep)

    print("[终末地：更新后说客户端过时，下一轮启动器「开始游戏」不能算就绪]")
    # The problem string is the one update_endfield notes after the install
    # (gameupdate_games.py 「终末地：更新后游戏仍说客户端已过时」); round two is what the
    # launcher then shows, 「开始游戏」 -> prepare returns (True, "") = "no update needed".
    _rounds = iter([
        lambda pr: (pr.append("终末地：更新后游戏仍说客户端已过时"), (False, ""))[1],
        lambda pr: (True, ""),
        lambda pr: (True, ""),
    ])
    _orig_prep = gu._prepare_client
    gu._prepare_client = lambda cfg, desk, game, problems, sleep, **k: next(_rounds)(problems)
    _ticks = iter(range(100))
    from datetime import datetime as _dt, timedelta as _tdl
    _t0 = _dt(2026, 10, 6, 9, 0)
    _pr: list = []
    _ready, _note = gu._prepare_until_ready(None, None, "终末地", deadline=_t0 + _tdl(minutes=25),
                                            clock=lambda: _t0 + _tdl(minutes=10 * next(_ticks)),
                                            sleep=lambda s: None, problems=_pr)
    gu._prepare_client = _orig_prep
    check("过时之后的「无需更新」不算就绪", _ready, False)
    check("留一条问题说清楚", any("客户端已过时" in x and "没准备好" in x for x in _pr), True)

    print("[a round that was not ready for another reason, then a ready one: one recovered red item (2026-10-12)]")
    from ark_relay.features import errwatch
    from ark_relay.core import texts

    class _AllRecords(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, r):
            self.records.append(r)

    def _retry(rounds, minutes=60):
        it = iter(rounds)
        t = [_t0]                # each round takes 10 minutes; the clock reads, never advances
        def _round(problems):
            t[0] += _tdl(minutes=10)
            return next(it, lambda pr: (False, ""))(problems)
        gu._prepare_client = lambda cfg, desk, game, problems, sleep, **k: _round(problems)
        keep = _AllRecords()
        gu.log.addHandler(keep)
        pr: list = []
        try:
            ready, _ = gu._prepare_until_ready(None, None, "终末地", deadline=_t0 + _tdl(minutes=minutes),
                                               clock=lambda: t[0], sleep=lambda s: None, problems=pr)
        finally:
            gu.log.removeHandler(keep)
            gu._prepare_client = _orig_prep
        healed = [r.getMessage() for r in keep.records if getattr(r, errwatch.RECOVERED, False)]
        for r in keep.records:
            if getattr(r, errwatch.RECOVERED, False):
                check("the recovered line's first line reads as plain words", texts.plain(errwatch.first_line(r)), [])
        return ready, pr, healed

    _CLICK = "终末地：点「更新游戏」没点上"
    _ready, _pr, _healed = _retry([lambda pr: (pr.append(_CLICK), (False, ""))[1],
                                   lambda pr: (True, "终末地 客户端已通过启动器更新")])
    check("click missed, next round ready: ready, nothing left to push", (_ready, _pr), (True, []))
    check("…one recovered WARNING naming the first round's problem", [(_CLICK in m) for m in _healed], [True])
    _ready, _pr, _healed = _retry([lambda pr: (pr.append("终末地：更新后游戏仍说客户端已过时"), (False, ""))[1],
                                   lambda pr: (True, "终末地 客户端已通过启动器更新")])
    check("package not out yet, then updated: no red item (the expected wait)", (_ready, _pr, _healed), (True, [], []))
    _SHOT = "终末地：启动器画面没读到按钮（截图 x）：…"
    _ready, _pr, _healed = _retry([lambda pr: (pr.append(_CLICK), (False, ""))[1],
                                   lambda pr: (pr.append(_SHOT), (False, ""))[1]], minutes=25)
    check("not ready by the deadline: the earlier round's problem is reported too",
          (_ready, any(_CLICK in x for x in _pr), any(_SHOT in x for x in _pr), _healed), (False, True, True, []))

    print("[终末地：一轮更新等下载的时间不超过离截止还剩的时间（s18 F6）]")
    _budgets = []
    _saved_f6 = (gu.endfield_paths, gu.update_endfield)
    gu.endfield_paths = lambda d: (Path("Endfield.exe"), Path("Launcher.exe"))
    gu.update_endfield = lambda desk, g, l, budget_s=2400, problems=None, sleep=None: _budgets.append(budget_s) or ""
    try:
        _t0 = _dt(2026, 9, 4, 13, 0, tzinfo=gu.SERVER_TZ)
        _ready, _ = gu._prepare_until_ready(cfg, FakeDesk([["x"]]), "终末地", deadline=_t0 + _td(minutes=25),
                                            clock=lambda: _t0, sleep=nosleep, problems=[])
        check("离截止还剩 25 分钟：这一轮最多等 25 分钟", _budgets, [1500.0])
        _budgets.clear()
        gu._prepare_until_ready(cfg, FakeDesk([["x"]]), "终末地", deadline=_t0 + _td(hours=3),
                                clock=lambda: _t0, sleep=nosleep, problems=[])
        check("还剩 3 小时：照旧最多 40 分钟", _budgets, [2400.0])
    finally:
        gu.endfield_paths, gu.update_endfield = _saved_f6

    print("[终末地：等 10 分钟后已过截止，就不再跑一轮 0 预算的更新]")
    # Review of 838eb436: round 1 ends 10 minutes in with a 15-minute deadline; the old loop
    # slept 600 s and ran round 2 with budget 0, which wrote a bogus 「0 分钟内没等到」.
    _rb = []
    _t = [_t0]

    def _round_f6(cfg, desk, game, problems, sleep, budget_s=2400.0):
        _rb.append(budget_s)
        _t[0] += _tdl(minutes=10)
        problems.append(f"终末地：{budget_s / 60:.0f} 分钟内没等到下载完")
        return False, ""

    gu._prepare_client = _round_f6
    try:
        _pr = []
        _ready, _ = gu._prepare_until_ready(None, None, "终末地", deadline=_t0 + _tdl(minutes=15),
                                            clock=lambda: _t[0], sleep=lambda s: None, problems=_pr)
    finally:
        gu._prepare_client = _orig_prep
    check("只跑一轮（15 分钟预算），没有 0 预算的第二轮", _rb, [900.0])
    check("报的是那一轮的问题，不是「0 分钟内没等到」", _pr, ["终末地：15 分钟内没等到下载完"])


def _part_gameupdate_wait_open():
    """Endfield ready but no rerun needed skips open wait; open wait stops on going_down."""
    import json
    import types
    from datetime import datetime as _dt, timedelta as _td

    from ark_relay.core.desktop import Line, Screen
    from ark_relay.features import errwatch, gameupdate as gu, gameupdate_games as gug

    class FakeDesk:
        def __init__(self, screens):
            self.screens = list(screens)
            self.clicks = []

        def read(self, focus=None, settle_ms=0):
            texts = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
            return Screen([Line(t, 100, 100 + 30 * i, 80, 20) for i, t in enumerate(texts)], Path("x.png"))

        def click_text(self, text, focus=None):
            self.clicks.append(text)
            return True

    ST = tmpdir()
    cfg = types.SimpleNamespace(state_dir=ST, automas_dir=None, maa_dir=None,
                                maaend_dir=ST / "maaend", okww_dir=None)
    (cfg.maaend_dir / "config").mkdir(parents=True, exist_ok=True)
    game = ST / "hg" / "games" / "Endfield Game" / "Endfield.exe"
    game.parent.mkdir(parents=True, exist_ok=True)
    game.write_bytes(b"")
    (ST / "hg" / "Launcher.exe").write_bytes(b"")
    (cfg.maaend_dir / "config" / "mxu-MaaEnd.json").write_text(
        json.dumps({"connectedProgramPath": str(game)}), encoding="utf-8")

    saved = (gug._spawn, gug.kill, gu.kill, gu.restore_skips)
    gug._spawn = lambda exe, cwd=None: True
    gug.kill = lambda *names: None
    gu.kill = lambda *names: None
    restored = []
    real_restore = gu.restore_skips
    gu.restore_skips = lambda sd, restorer=None, **kw: real_restore(
        sd, restorer=lambda rec: restored.append(rec["script"]) or True, **kw)
    try:
        win = (_dt(2026, 9, 4, 6, 0, tzinfo=gu.SERVER_TZ),
               _dt(2026, 9, 4, 16, 0, tzinfo=gu.SERVER_TZ), "官方公告：09-04 06:00–16:00")
        now = _dt(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ)

        print("[终末地客户端更新就绪但今天已跑成（needs_rerun=False）：不等 5.5 小时开服]")
        (ST / "ledger-2026-09-04.jsonl").write_text(
            json.dumps({"script": "MaaEnd", "ok": True, "raw": {}}) + "\n", encoding="utf-8")
        gu.save_windows(ST, {"终末地": win})
        gu.mark_pending(ST, "终末地", "官方公告")
        slept, dispatched = [], []
        t_cur = [now]

        def clk():
            t_cur[0] += _td(minutes=1)
            return t_cur[0]

        d = FakeDesk([["更新游戏"], ["正在下载"], ["开始游戏"], ["点击任意位置继续"]])
        notes, probs, reran = gu.run_deferred(
            cfg, now=now, desk=d,
            dispatch=lambda s: dispatched.append(s) or (True, "ok"),
            sleep=slept.append, clock=clk, stopping=lambda: False)
        check("客户端照常更新并出通知", any("已通过启动器更新" in n for n in notes), True)
        check("不等开服（没有 60 秒轮询，也没有 120 秒开服缓冲）", (60 in slept, 120 in slept), (False, False))
        check("不补跑、没问题", (dispatched, reran, probs), ([], [], []))
        check("登记已清", gu.pending(ST), {})

        print("\n[终末地客户端更新就绪但今天被停一切停过：不等开服，仍写「已停，未补」]")
        (ST / "ledger-2026-09-04.jsonl").write_text(
            json.dumps({"script": "MaaEnd", "ok": False,
                        "raw": {"maintenance": "官方公告", "manual_stop": "09:46 停一切"}}) + "\n",
            encoding="utf-8")
        gu.save_windows(ST, {"终末地": win})
        gu.mark_pending(ST, "终末地", "官方公告")
        slept.clear(); dispatched.clear(); t_cur[0] = now
        notes, probs, reran = gu.run_deferred(
            cfg, now=now, desk=FakeDesk([["开始游戏"]]),
            dispatch=lambda s: dispatched.append(s) or (True, "ok"),
            sleep=slept.append, clock=clk, stopping=lambda: False)
        check("不等开服", (60 in slept, 120 in slept), (False, False))
        check("通知写已停未补、不补跑", (any("已停，未补" in n for n in notes), dispatched, reran), (True, [], []))
        check("登记已清", gu.pending(ST), {})

        print("\n[等开服循环期间 stopping() 变真：立刻退出、不补跑、保留登记、改回队列跳过]")
        (ST / "ledger-2026-09-04.jsonl").write_text(
            json.dumps({"script": "MaaEnd", "ok": False, "raw": {"maintenance": "官方公告"}}) + "\n",
            encoding="utf-8")
        gu.save_windows(ST, {"终末地": win})
        gu.mark_pending(ST, "终末地", "官方公告")
        gu._add_skip(ST, {"queue": "早班", "queueId": "Q", "script": "MaaEnd", "scriptId": "S",
                          "position": 0, "queueItemId": "I", "days": ["Friday"], "day": "2026-09-04"})
        slept.clear(); dispatched.clear(); restored.clear(); t_cur[0] = now
        stop_after = [0]

        def fake_sleep_stop(s):
            slept.append(s)
            if s == 60:
                stop_after[0] += 1

        notes, probs, reran = gu.run_deferred(
            cfg, now=now, desk=FakeDesk([["开始游戏"]]),
            dispatch=lambda s: dispatched.append(s) or (True, "ok"),
            sleep=fake_sleep_stop, clock=clk, stopping=lambda: stop_after[0] >= 2)
        check("睡两次 60 秒后感应到停机即停，不睡 120 秒", (slept.count(60), 120 in slept), (2, False))
        check("不补跑、不记故障", (dispatched, reran, probs), ([], [], []))
        check("未完成补跑故保留待更新登记", "终末地" in gu.pending(ST), True)
        check("队列跳过仍安全改回", restored, ["MaaEnd"])

        print("\n[默认不传 stopping：感应 errwatch.going_down() 立即退出等开服]")
        gu.save_windows(ST, {"终末地": win})
        gu.mark_pending(ST, "终末地", "官方公告")
        slept.clear(); dispatched.clear(); t_cur[0] = now
        errwatch.clear_stopping()
        try:
            def sleep_sets_stopping(s):
                slept.append(s)
                if s == 60:
                    errwatch.mark_stopping()

            notes, probs, reran = gu.run_deferred(
                cfg, now=now, desk=FakeDesk([["开始游戏"]]),
                dispatch=lambda s: dispatched.append(s) or (True, "ok"),
                sleep=sleep_sets_stopping, clock=clk)
            check("默认 stopping 绑定 going_down：睡 1 次 60 秒即停、不睡 120 秒",
                  (slept.count(60), 120 in slept, dispatched), (1, False, []))
        finally:
            errwatch.clear_stopping()

        print("\n[客户端超截止未就绪放弃（今天不补跑）：清掉待更新登记，重启和次日不再重复拉起刷告警]")
        win_short = (_dt(2026, 9, 4, 6, 0, tzinfo=gu.SERVER_TZ),
                     _dt(2026, 9, 4, 12, 0, tzinfo=gu.SERVER_TZ), "官方公告：09-04 06:00–12:00")
        (ST / "ledger-2026-09-04.jsonl").write_text(
            json.dumps({"script": "MaaEnd", "ok": False, "raw": {"maintenance": "官方公告"}}) + "\n",
            encoding="utf-8")
        gu.save_windows(ST, {"终末地": win_short})
        gu.mark_pending(ST, "终末地", "官方公告")
        slept.clear(); dispatched.clear()
        late = _dt(2026, 9, 4, 13, 55, tzinfo=gu.SERVER_TZ)
        t_late = [late]

        def clk_late():
            t_late[0] += _td(minutes=1)
            return t_late[0]

        notes, probs, reran = gu.run_deferred(
            cfg, now=late, desk=FakeDesk([["登录", "公告"]]),
            dispatch=lambda s: dispatched.append(s) or (True, "ok"),
            sleep=slept.append, clock=clk_late, stopping=lambda: False)
        check("超截止放弃记入问题", any("仍没准备好客户端，今天不补跑" in p for p in probs), True)
        check("不补跑", (dispatched, reran), ([], []))
        check("放弃后已清掉待更新登记", gu.pending(ST), {})
        # 当天重启（已过 14:00 截止）及次日再调 run_deferred：不再拉起、不再刷告警
        again_reads = []

        class _NoReadDesk:
            def read(self, *a, **k):
                again_reads.append(1)
                return Screen([], Path("x.png"))

        after_restart = _dt(2026, 9, 4, 14, 5, tzinfo=gu.SERVER_TZ)
        check("重启后再调 run_deferred 直接空返",
              gu.run_deferred(cfg, now=after_restart, desk=_NoReadDesk(),
                              dispatch=lambda s: dispatched.append(s) or (True, "ok"),
                              sleep=slept.append, clock=lambda: after_restart, stopping=lambda: False),
              ([], [], []))
        check("重启后没有再去读启动器", again_reads, [])

        print("\n[跨零点维护窗（now=Day1 23:40、clock=Day2 00:05、end=Day2 02:00）：统一按 now 查账本，等开服再补跑]")
        day1_now = _dt(2026, 9, 4, 23, 40, tzinfo=gu.SERVER_TZ)
        day2_start = _dt(2026, 9, 5, 0, 5, tzinfo=gu.SERVER_TZ)
        day2_end = _dt(2026, 9, 5, 2, 0, tzinfo=gu.SERVER_TZ)
        win_mid = (_dt(2026, 9, 4, 23, 0, tzinfo=gu.SERVER_TZ), day2_end, "官方公告：09-04 23:00–09-05 02:00")
        (ST / "ledger-2026-09-05.jsonl").unlink(missing_ok=True)
        (ST / "ledger-2026-09-04.jsonl").write_text(
            json.dumps({"script": "MaaEnd", "ok": False, "raw": {"maintenance": "官方公告"}}) + "\n"
            + json.dumps({"script": "OK-WW", "ok": False, "raw": {"maintenance": "官方公告"}}) + "\n",
            encoding="utf-8",
        )
        for game_name, script_name in (("终末地", "MaaEnd"), ("鸣潮", "OK-WW")):
            gu.save_windows(ST, {game_name: win_mid})
            gu.mark_pending(ST, game_name, "官方公告")
            t_mid = [day2_start]
            slept_mid, disp_at, killed_mid = [], [], []
            gu.kill = lambda *names, _k=killed_mid: _k.extend(names)

            def _mid_sleep(s, _t=t_mid, _sl=slept_mid):
                _sl.append(s)
                _t[0] += _td(seconds=s)

            notes, probs, reran = gu.run_deferred(
                cfg, now=day1_now, desk=FakeDesk([["开始游戏"]]),
                dispatch=lambda s, _t=t_mid, _da=disp_at: _da.append((s, _t[0])) or (True, "ok"),
                sleep=_mid_sleep, clock=lambda _t=t_mid: _t[0], stopping=lambda: False)
            check(f"{game_name} 跨零点正常等开服（睡满 60 秒轮询 + 120 秒开服缓冲）",
                  (slept_mid.count(60) >= 115, 120 in slept_mid), (True, True))
            check(f"{game_name} 仅在 02:00 开服且缓冲后才派发，不提前派发",
                  (reran, probs, len(disp_at) == 1 and disp_at[0][0] == script_name
                   and disp_at[0][1] >= day2_end + _td(seconds=120)),
                  ([script_name], [], True))
            if game_name == "终末地":
                check("终末地等开服期间先关掉客户端进程", "Endfield.exe" in killed_mid, True)
            check(f"{game_name} 补跑后清掉登记", gu.pending(ST), {})
    finally:
        gug._spawn, gug.kill, gu.kill, gu.restore_skips = saved


def _part_gameupdate_restore_paths():
    """A script pulled from a queue for a game update goes back on every path."""
    import types
    from datetime import datetime

    from ark_relay.features import gameupdate as gu

    def _cfg():
        st = tmpdir()
        return types.SimpleNamespace(state_dir=st, automas_dir=None, maa_dir=None, maaend_dir=None, okww_dir=None)

    REC = {"queue": "早班", "queueId": "Q", "script": "MAA", "scriptId": "S", "position": 1}
    restored = []
    saved = gu.restore_skips

    def _fake_restorer(rec):
        restored.append((rec["script"], rec.get("day")))
        return True

    def _restore(state_dir, restorer=None, **kw):
        return saved(state_dir, restorer=_fake_restorer, **kw)

    gu.restore_skips = _restore
    try:
        print("[队列后那一步中途出错：摘掉的照样加回]")
        cfg = _cfg()
        gu._add_skip(cfg.state_dir, dict(REC, day="2026-09-04"))
        gu.mark_pending(cfg.state_dir, "明日方舟", "维护")
        real_prep = gu._prepare_until_ready
        gu._prepare_until_ready = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            gu.run_deferred(cfg, now=datetime(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ), desk=object(),
                            dispatch=lambda s: (True, "ok"), sleep=lambda s: None)
            check("异常照样往外抛（由调用方报）", False, True)
        except RuntimeError:
            check("异常照样往外抛（由调用方报）", True, True)
        finally:
            gu._prepare_until_ready = real_prep
        check("出错也加回了", (restored, gu.skips(cfg.state_dir)), ([("MAA", "2026-09-04")], []))

        print("\n[总开关关着 / 没登记了：摘掉的也加回]")
        restored.clear()
        cfg = _cfg()
        gu._add_skip(cfg.state_dir, dict(REC, day="2026-09-04"))
        gu.run_deferred(cfg, now=datetime(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ), desk=object())
        check("没登记：加回", [r[0] for r in restored], ["MAA"])

        print("\n[开机：之前哪天摘掉没加回的先加回；今天摘的不动]")
        restored.clear()
        cfg = _cfg()
        gu._add_skip(cfg.state_dir, dict(REC, day="2026-09-04"))
        gu._add_skip(cfg.state_dir, dict(REC, queueId="Q2", queue="晚班", day="2026-09-05"))
        gu._add_skip(cfg.state_dir, dict(REC, queueId="Q3", queue="午班"))          # written before records had a day
        gu.boot_check(cfg, budget_s=0, now=datetime(2026, 9, 5, 8, 40, tzinfo=gu.SERVER_TZ),
                      hint=lambda n: "", maint_sources={})
        check("前一天的和没写日期的加回了", sorted(restored, key=str), sorted([("MAA", "2026-09-04"), ("MAA", None)], key=str))
        check("今天摘的留着", [r["queue"] for r in gu.skips(cfg.state_dir)], ["晚班"])
    finally:
        gu.restore_skips = saved


def _part_efstart_main():
    """Endfield is started through the official launcher, never as Endfield.exe (2026-10-15)."""
    import json

    from ark_relay.features import efstart as ef
    from ark_relay.features import efstart as setup

    FX = fx_dir(Path(__file__), "fixtures") / "maaend-v2.33.0-launch"
    BETA2 = fx_dir(Path(__file__), "gamesim") / "upstream" / "maaend-v2.33.0-beta.2"

    class Probe:
        """A start with nothing to do: the game is not running and the pretask exits 0."""

        def __init__(self):
            self.ran = []

        def probes(self):
            return ef.Probes(running=lambda names: set(), kill=lambda *n: True,
                             run=lambda argv, cwd, timeout: (self.ran.append(argv), (0, ""))[1],
                             wake=lambda: True, sleep=lambda s: None)

    print("\n[一次开游戏：running.json 只在开的时候有；没说 MaaEnd 在哪 → 2]")
    home = tmpdir() / "efstart"
    home.mkdir()
    md = tmpdir() / "maaend"
    import shutil
    shutil.copytree(FX, md)
    (md / "agent").mkdir()
    (md / "agent" / "go-service.exe").write_bytes(b"")
    w = Probe()
    seen = []

    class _Lock:
        def __init__(self, got):
            self.got = got

        def __call__(self, wait_s):
            return self

        def __enter__(self):
            seen.append((home / ef.RUNNING).exists())
            return self.got

        def __exit__(self, *a):
            return False

    r = ef.run_once(home, "test", "", probes=w.probes(), single=_Lock(True))
    check("没说 MaaEnd 在哪就是 2", r.code, ef.SETUP)
    r = ef.run_once(home, "test", md, probes=w.probes(), single=_Lock(True))
    check("说了就开（预任务退出 0 → 0）", (r.code, len(w.ran)), (ef.OK, 1))
    check("结束后 running.json 没了", (home / ef.RUNNING).exists(), False)
    r = ef.run_once(home, "test", md, probes=w.probes(), single=_Lock(False))
    check("锁一直被别人占着 → 9", (r.code, len(w.ran)), (ef.BUSY, 1))

    print("\n[看门狗：开游戏助手在等（running.json 的 PID 是 pythonw）→ 认得出]")
    sd = tmpdir()
    (sd / "efstart").mkdir()
    (sd / "efstart" / ef.RUNNING).write_text(json.dumps({"pid": 4242}), encoding="utf-8")
    check("PID 在、是 pythonw", ef.helper_alive(sd, [("pythonw.exe", 4242), ("MaaEnd.exe", 1)]), True)
    check("PID 不在", ef.helper_alive(sd, [("MaaEnd.exe", 1)]), False)
    check("PID 被别的程序用了", ef.helper_alive(sd, [("notepad.exe", 4242)]), False)

    from ark_relay.features import maaend_watchdog

    RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
    procs = [("MaaEnd.exe", 100), ("pythonw.exe", 4242)]          # no go-service yet: tasks not started
    clock = {"t": 1000.0}
    killed = []
    dbg = sd / "debug"
    dbg.mkdir()
    (dbg / "go-service.stderr.log").write_text("", encoding="utf-8")

    class _N:
        def send(self, *a, **k):
            return []

    dog = maaend_watchdog.Watchdog(_N(), dbg, clock=lambda: clock["t"], snapshot=lambda: RUNNING,
                                   processes=lambda: procs, kill=lambda pid, img: killed.append(pid) or (True, ""),
                                   plugin_paths=lambda: {}, active=True, state_dir=sd)
    for _ in range(20):                       # 20 minutes waiting on the helper, no plugin, no log line
        clock["t"] += 60
        dog.tick(0, "")
    check("助手在等的 20 分钟里不杀 MaaEnd", killed, [])
    (sd / "efstart" / ef.RUNNING).unlink()
    for _ in range(20):
        clock["t"] += 60
        dog.tick(0, "")
    check("助手结束后照旧判（插件一直没起来 → 杀）", killed, [100])

    print("\n[收集补跑：游戏由开游戏助手开，不再直接起 Endfield.exe]")
    from ark_relay.features import collect_retry as cr
    import types

    md = tmpdir() / "maaend"
    (md / "debug").mkdir(parents=True)
    started = []
    saved = (cr._running, cr._wait, cr.api, cr.mxu_port, cr.time, ef.run_on_desktop)
    cr._running = lambda names: {"MaaEnd.exe"}
    cr._wait = lambda pred, seconds, step=3.0: pred() if seconds != 60 else True
    cr.api = lambda path, body=None, timeout=30: {"instances": {}} if "state" in path else []
    cr.mxu_port = lambda d: 12701
    cr.time = types.SimpleNamespace(sleep=lambda s: None, strftime=lambda f: "00:00:00", time=lambda: 0)
    ef.run_on_desktop = lambda state_dir, spawn, *a, **k: started.append(state_dir) or ef.Result(ef.SETUP, "开游戏的助手没装好")
    spawned = []
    try:
        verdict, note = cr._bring_up_and_run(FX, ["AutoCollectRoute15"], {}, spawn=lambda exe, cwd, args: spawned.append(exe),
                                             timeout=10, evidence=None, state_dir=sd)
    finally:
        cr._running, cr._wait, cr.api, cr.mxu_port, cr.time, ef.run_on_desktop = saved
    check("经开游戏助手开", started, [sd])
    check("没直接起任何程序", spawned, [])
    check("助手没开起来就不补，说原因", note, "游戏没经官方启动器开起来：开游戏的助手没装好")

    print("\n[run_on_desktop：用中继的 pythonw 起助手入口，等它的结果文件]")
    sd2 = tmpdir()
    (sd2 / "efstart").mkdir()
    (sd2 / "efstart" / ef.TRAMPOLINE).write_text("# trampoline\n", encoding="utf-8")
    calls = []

    def fake_spawn(exe, cwd, args):
        calls.append((Path(exe).name, args[0], args[1:3]))
        res = Path(args[args.index("--result") + 1])
        res.write_text(json.dumps({"code": 0, "reason": "终末地已经开着，没再开"}), encoding="utf-8")
        return True

    r = ef.run_on_desktop(sd2, fake_spawn, md, pythonw=Path("pythonw.exe"), sleep=lambda s: None)
    check("起的是 pythonw 跑入口", calls, [("pythonw.exe", str(sd2 / "efstart" / ef.TRAMPOLINE), ("--caller", "relay"))])
    check("拿到助手的结果", (r.code, r.reason), (ef.OK, "终末地已经开着，没再开"))
    check("结果文件用完删掉", list((sd2 / "efstart").glob("result-*.json")), [])

    print("\n[run_on_desktop：中继要停了就不再等助手（审计 11-08 A-23：这一等在主循环里，停机会被拖到强退）]")
    polls = []
    r = ef.run_on_desktop(sd2, lambda exe, cwd, args: True, md, pythonw=Path("pythonw.exe"),
                          sleep=lambda s_: polls.append(s_), stopping=lambda: len(polls) >= 2)
    check("停了：不判结论，回 STOPPED", (r.code, r.code in ef.RAN, len(polls)), (ef.STOPPED, False, 2))
    check("STOPPED 不和助手的退出码撞号", ef.STOPPED not in (ef.OK, ef.SETUP, ef.PRETASK, ef.LAUNCHER, ef.TIMED_OUT,
                                                          ef.UNREADABLE, ef.BUSY), True)

    print("\n[_single：互斥锁用完，句柄关掉（PyHANDLE 自己的 Close）]")

    class _H:
        closed = False

        def Close(self):  # noqa: N802
            self.closed = True

    h = _H()
    fake_ev = types.SimpleNamespace(CreateMutex=lambda *a: h, WaitForSingleObject=lambda hh, ms: 0, WAIT_OBJECT_0=0,
                                    WAIT_ABANDONED=0x80, ReleaseMutex=lambda hh: released.append(hh))
    released = []
    saved_mod = sys.modules.get("win32event")
    sys.modules["win32event"] = fake_ev
    try:
        with ef._single(1) as got:
            pass
        check("拿到锁、放了锁、关了句柄", (got, released == [h], h.closed), (True, True, True))
        h2 = _H()
        fake_ev.CreateMutex = lambda *a: h2
        fake_ev.WaitForSingleObject = lambda hh, ms: 0x102          # WAIT_TIMEOUT
        with ef._single(1) as got:
            pass
        check("没等到锁：不放锁，照样关句柄", (got, h2.closed), (False, True))
    finally:
        if saved_mod is None:
            sys.modules.pop("win32event", None)
        else:
            sys.modules["win32event"] = saved_mod

    print("\n[10-16：开游戏交还给调度程序自己的官方启动器方式（AUTO-MAS v5.7.0-beta.4 / #1394）]")
    from ark_relay.core import texts
    from ark_relay.features import commands

    pyw = "C:\\Program Files\\ArkRelay\\runtime\\python\\pythonw.exe"
    orig = {"id": "jw75pty", "customName": "▶️ 启动 Endfield.exe", "enabled": True,
            "program": "D:\\endfield\\Hypergryph Launcher\\games\\Endfield Game\\Endfield.exe", "args": "",
            "waitForExit": False, "skipIfRunning": True, "useCmd": False}
    mas_entry = {"id": "automas-endfield", "program": "D:\\endfield\\Endfield.exe", "waitForExit": False}
    ours = {"id": "jw75pty", "customName": "▶️ 经官方启动器启动终末地（中继）", "enabled": True, "program": pyw,
            "args": '"C:\\ProgramData\\ark-relay\\state\\efstart\\efstart.py" --caller maaend',
            "waitForExit": True, "skipIfRunning": False, "useCmd": False}
    doc = {"instances": [{"name": "automas", "preActions": [dict(mas_entry), dict(ours)]}]}
    changed, removed = setup.remove_preactions(doc)
    check("母本里中继那条（id 是 jw75pty，不是 ark-efstart）删掉了", (changed, [a["id"] for a in removed]), (True, ["jw75pty"]))
    check("调度程序自己那条原样留着", doc["instances"][0]["preActions"], [mas_entry])
    check("再删一次不变", setup.remove_preactions(doc), (False, []))
    check("没有往母本里加任何东西的入口了", hasattr(setup, "rewrite_preactions"), False)

    root = tmpdir()
    lroot = root / "endfield" / "Hypergryph Launcher"
    game_dir = lroot / "games" / "Endfield Game"
    game_dir.mkdir(parents=True)
    (game_dir / "Endfield.exe").write_text("", encoding="utf-8")
    (lroot / "Launcher.exe").write_text("", encoding="utf-8")
    (lroot / "1.6.0").mkdir()
    (lroot / "1.6.0" / "Games.exe").write_text("", encoding="utf-8")
    game_exe = str(game_dir / "Endfield.exe")
    setup._is_file = lambda p: Path(str(p).replace("\\", "/")).is_file()
    setup._subdirs = lambda p: [str(x) for x in Path(str(p).replace("\\", "/")).iterdir() if x.is_dir()] \
        if Path(str(p).replace("\\", "/")).is_dir() else []

    print("\n[调度程序找启动器的规矩，照它 endfield_launcher.py 的写法]")
    check("游戏本体：往上找到 Launcher.exe 加带 Games.exe 的版本文件夹",
          Path(str(setup.launcher_for(game_exe)).replace("\\", "/")), lroot / "Launcher.exe")
    home = root / "state" / "efstart"
    home.mkdir(parents=True)
    cmd = home / "start-endfield.cmd"
    cmd.write_text("@echo off\r\n", encoding="utf-8")
    check("10-16 那样指着批处理：找不到（调度程序就是这样拒绝的）", setup.launcher_for(str(cmd)), None)
    check("指定 Games.exe：换成上两层的 Launcher.exe",
          Path(str(setup.launcher_for(str(cmd), str(lroot / "1.6.0" / "Games.exe"))).replace("\\", "/")),
          lroot / "Launcher.exe")
    check("指定别的程序：不算", setup.launcher_for(game_exe, str(game_dir / "Endfield.exe")), None)
    (lroot / "1.6.0" / "Games.exe").unlink()
    check("没有版本文件夹：不认（Launcher.exe 这个名字太常见）", setup.launcher_for(game_exe), None)
    (lroot / "1.6.0" / "Games.exe").write_text("", encoding="utf-8")

    print("\n[install：路径改回游戏本体、由 MaaEnd 开窗口（10-17）、等待改回、母本里的助手删掉；再跑不写；restore 不放回直接开]")
    automas = root / "automas"
    cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
    cfgdir.mkdir(parents=True)
    master = cfgdir / "mxu-MaaEnd.json"
    master.write_text(json.dumps({"instances": [{"name": "automas", "tasks": [],
                                                  "preActions": [dict(mas_entry), dict(ours)]}]},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    (home / ef.TARGET).write_text(json.dumps({
        "game": game_exe, "launcher": str(lroot / "Launcher.exe"), "cmd": str(cmd),
        "trampoline": str(home / ef.TRAMPOLINE),
        "original": {"preactions": [dict(orig, program=game_exe)], "game_path": game_exe, "wait_time": 60}}),
        encoding="utf-8")
    mas = {"data": {"s1": {"Info": {"Name": "MaaEnd", "Path": str(FX)},
                           "Game": {"Path": str(cmd), "LaunchMode": "Launcher", "LauncherPath": "",
                                    "Arguments": "", "WaitTime": 180, "ControllerType": "Win32-Front",
                                    "SetResolution": True, "CloseOnFinish": True, "RestoreDisplayType": "Fullscreen",
                                    "RestoreResolution": "1920x1080"}}}}
    writes = []

    def fake_mas(path, body=None, timeout=20):
        if path == "/api/scripts/get":
            return json.loads(json.dumps(mas))
        if path == "/api/scripts/update":
            writes.append(body)
            for k, v in body["data"].items():
                mas["data"][body["scriptId"]][k].update(v)
            return {"code": 200}
        raise AssertionError(path)

    cfg = types.SimpleNamespace(state_dir=root / "state", automas_dir=automas, maaend_dir=None)
    saved_mas = commands._mas
    commands._mas = fake_mas
    try:
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        g = mas["data"]["s1"]["Game"]
        check("全部对上", ok, True)
        check("调度程序的终末地路径改回游戏本体（不再是批处理）", g["Path"], game_exe)
        check("启动方式是由 MaaEnd 开（窗口设置本来就对）", g["LaunchMode"], "MaaEnd")
        check("启动器路径留空，让调度程序自己找", g["LauncherPath"], "")
        check("等待改回原来的 60 秒（不再提到 180）", g["WaitTime"], 60)
        check("写的只有路径、启动方式和等待（窗口设置本来就对，没写）",
              sorted(k for w in writes for k in w["data"]["Game"]), ["LaunchMode", "Path", "WaitTime"])
        back = json.loads(master.read_text(encoding="utf-8"))["instances"][0]["preActions"]
        check("母本读回来：只剩调度程序自己那条，没有助手，也没放回直接开 Endfield.exe", back, [mas_entry])
        check("批处理删了", cmd.exists(), False)
        check("开游戏助手的入口还在（中继自己的补采集要用）",
              repr(str(Path("C:/relay/versions/7"))) in (home / ef.TRAMPOLINE).read_text(encoding="utf-8"), True)
        tgt = json.loads((home / ef.TARGET).read_text(encoding="utf-8"))
        check("记录里不再有批处理", "cmd" in tgt, False)
        check("原来的值一个没丢", tgt["original"]["game_path"], game_exe)
        n_writes, master_text = len(writes), master.read_text(encoding="utf-8")
        ok2, notes2 = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("再跑一次：照样全好、什么都不说", (ok2, notes2), (True, []))
        check("再跑一次：调度程序没再写", len(writes), n_writes)
        check("再跑一次：母本没再写", master.read_text(encoding="utf-8"), master_text)

        g["LaunchMode"] = "Client"
        ok3, _ = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("启动方式被改成直接开：改回由 MaaEnd 开", (ok3, g["LaunchMode"]), (True, "MaaEnd"))

        # 「启动器启动」 (MaaEnd without its launcher pretask: the fallback) needs AUTO-MAS's own rule to find it.
        mas["data"]["s1"]["Info"]["Path"] = str(BETA2)
        (lroot / "1.6.0" / "Games.exe").unlink()
        ok4, notes4 = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("经官方启动器开、调度程序找不到启动器：不算好，说清楚它会拒绝开终末地",
              (ok4, g["LaunchMode"], any(texts.ENDFIELD_NO_LAUNCHER in n for n in notes4)), (False, "Launcher", True))
        check("这句是人话", texts.plain(texts.ENDFIELD_NO_LAUNCHER), [])
        (lroot / "1.6.0" / "Games.exe").write_text("", encoding="utf-8")
        mas["data"]["s1"]["Info"]["Path"] = str(FX)

        master.write_text(json.dumps({"instances": [{"name": "automas", "preActions": [dict(mas_entry), dict(ours)]}]}),
                          encoding="utf-8")
        g["WaitTime"] = 180
        okr, _ = setup.restore(cfg)
        back = json.loads(master.read_text(encoding="utf-8"))["instances"][0]["preActions"]
        check("restore：母本里没有直接开 Endfield.exe 的那条，也没有助手", back, [mas_entry])
        check("restore：路径还是游戏本体（不放回批处理）、等待改回", (okr, g["Path"], g["WaitTime"]), (True, game_exe, 60))
    finally:
        commands._mas = saved_mas

    print("\n[开机和调度程序升级后都核对一遍]")
    import boot_stages
    seen = []
    saved = (setup.install, boot_stages.selfcheck if hasattr(boot_stages, "selfcheck") else None)
    from ark_relay.features import selfcheck
    saved_rc = selfcheck.report_contract
    setup.install = lambda c, **k: (seen.append(c) or (True, []))
    selfcheck.report_contract = lambda *a, **k: None
    # The backend answers here (boot_stages.await_backend asks it before install()).
    saved_up = commands.mas_up
    commands.mas_up = lambda: True

    class _L:
        def __init__(self):
            self.warned = []

        def info(self, *a, **k):
            pass

        def warning(self, msg, *a, **k):
            self.warned.append(msg % a)

        def exception(self, *a, **k):
            self.warned.append(a[0])

    try:
        boot_stages._contract_after_update("CFG", None, _L(), "v5.7.0-beta.4")
        check("调度程序升级后（开机那次核对是对着旧版的）再核对一遍", seen, ["CFG"])
        setup.install = lambda c, **k: (False, ["一句"])
        lg = _L()
        boot_stages._contract_after_update("CFG", None, lg, "v5.7.0-beta.4")
        check("没对上：一条 WARNING（进群）", len(lg.warned), 1)
    finally:
        setup.install, selfcheck.report_contract = saved[0], saved_rc
        commands.mas_up = saved_up


def _part_maaend_windowed_start():  # noqa: C901
    """Endfield starts windowed through MaaEnd's own launcher pretask, and goes back to fullscreen (10-17).
    """
    import json
    import logging
    import shutil
    import types

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parent))

    from ark_relay.core import texts
    from ark_relay.features import efstart as ef
    from ark_relay.features import efstart as setup
    from ark_relay.features import collect_retry as cr
    from ark_relay.features import commands
    try:
        from ark_relay.features import maaend_launch as ml
    except ImportError:                 # the code before this change
        ml = None

    # Names this change brings in, looked up so the file runs (and fails check by check) on the code before it.
    NO_MAAEND_START = getattr(texts, "ENDFIELD_NO_MAAEND_START", "\0 not defined")
    PRETASK = getattr(ef, "PRETASK", -5)

    FX = fx_dir(HERE, "fixtures") / "maaend-v2.33.0-launch"
    BETA2 = fx_dir(HERE, "gamesim") / "upstream" / "maaend-v2.33.0-beta.2"     # still the old GameSetting pretask
    MACHINE_ARGS = ('{"LaunchGamePCRegion":"CN","LaunchGamePCLauncherPath":"Auto","LaunchGamePCGameSetting":"Yes",'
                    '"LaunchGamePCLanguage":"Unchanged","LaunchGamePCDisplayType":"Window","LaunchGamePCResolution":"1280x720",'
                    '"LaunchGamePCGraphicsQuality":"Unchanged","LaunchGamePCFrameRate":"Unchanged","LaunchGamePCAutoHDR":"Unchanged"}')
    RESTORE = {"CloseGamePC": {"attach": {"ApplyGameSetting": True, "GameSettingRegion": "CN",
                                          "GameSettingLanguage": "Unchanged", "GameSettingDisplayType": "Fullscreen",
                                          "ResolutionWidth": 1920, "ResolutionHeight": 1080}}}

    def maaend_copy(edit=None) -> Path:
        """The fixture MaaEnd in a temp folder, with go-service.exe where AUTO-MAS finds it."""
        d = tmpdir() / "maaend"
        shutil.copytree(FX, d)
        (d / "agent").mkdir()
        (d / "agent" / "go-service.exe").write_bytes(b"")
        if edit:
            edit(d)
        return d

    def edit_json(path: Path, fn) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        fn(data)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    print("[maaend_launch: MaaEnd v2.33.0's own files give exactly what AUTO-MAS sent on 10-17]")
    check("maaend_launch exists", ml is not None)
    if ml is not None:
        plan, why = ml.launch_plan(FX, "Win32-Front")
        check("the pretask's program as declared", (plan or {}).get("exec"), "agent/go-service")
        check("arguments: --pretask LaunchGamePC + the machine's 11:31:05 options, byte for byte",
              (plan or {}).get("args"), ["--pretask", "LaunchGamePC", MACHINE_ARGS])
        d = maaend_copy()
        check("its program: agent/go-service.exe in the MaaEnd folder (.exe added as AUTO-MAS adds it)",
              ml.executable(d, "agent/go-service"), d / "agent" / "go-service.exe")
        check("no program there: None", ml.executable(tmpdir(), "agent/go-service"), None)
        check("CloseGamePC override: fullscreen 1920x1080, both sizes, region/language as its defaults",
              ml.restore_override(FX), (RESTORE, ""))
        check("the machine's controller Win32-Front: everything there", ml.check(FX, "Win32-Front"), "")

        print("\n[a MaaEnd that cannot do it: refused with a plain reason, nothing guessed]")
        reasons = {
            "controller ADB": ml.check(FX, "ADB"),
            "no controller set": ml.check(FX, ""),
            "v2.33.0-beta.2 (GameSetting, no LaunchGamePC)": ml.check(BETA2, "Win32-Front"),
            "no MaaEnd folder": ml.check(tmpdir() / "nothing", "Win32-Front"),
            "1280x720 renamed": ml.check(maaend_copy(lambda d: edit_json(
                d / "tasks" / "pretasks" / "LaunchGamePC.json",
                lambda j: j["option"]["LaunchGamePCResolution"]["cases"][0].update(name="1280*720"))), "Win32-Front"),
            "Window case gone": ml.check(maaend_copy(lambda d: edit_json(
                d / "tasks" / "pretasks" / "LaunchGamePC.json",
                lambda j: j["option"]["LaunchGamePCDisplayType"]["cases"].pop(0))), "Win32-Front"),
            "CloseGamePC without the height attach": ml.check(maaend_copy(lambda d: edit_json(
                d / "tasks" / "CloseGamePC.json",
                lambda j: j["option"]["CloseGamePCGameSettingResolution"]["pipeline_override"]["CloseGamePC"]["attach"]
                .pop("ResolutionHeight"))), "Win32-Front"),
            "CloseGamePC gone": ml.check(maaend_copy(lambda d: edit_json(
                d / "interface.json", lambda j: j["import"].pop())), "Win32-Front"),
        }
        # AUTO-MAS sends only LaunchGamePCGameSetting (AutoProxy.py:2199-2207 @fdfb0fd); every other
        # option is LaunchGamePC.json's default case, so a default that is not the window case starts
        # the game that way even though the case still exists.
        for opt, other in (("LaunchGamePCDisplayType", "Fullscreen"), ("LaunchGamePCResolution", "1920x1080"),
                           ("LaunchGamePCRegion", "Global"), ("LaunchGamePCLauncherPath", "Manual")):
            reasons[f"{opt} default {other}"] = ml.check(maaend_copy(lambda d, o=opt, v=other: edit_json(
                d / "tasks" / "pretasks" / "LaunchGamePC.json",
                lambda j: j["option"][o].update(default_case=v))), "Win32-Front")
        reasons["(the relay's own start sends the values itself: still planned with DisplayType default Fullscreen)"] = (
            "" if ml.launch_plan(maaend_copy(lambda d: edit_json(
                d / "tasks" / "pretasks" / "LaunchGamePC.json",
                lambda j: j["option"]["LaunchGamePCDisplayType"].update(default_case="Fullscreen"))))[0] else "refused")
        planned = reasons.pop("(the relay's own start sends the values itself: still planned with DisplayType default Fullscreen)")
        check("the relay's own start sends every value itself: a changed default does not stop it", planned, "")
        for what, why in reasons.items():
            check(f"{what}: refused", bool(why), True)
        check("every reason is plain Chinese", {w: texts.plain(r) for w, r in reasons.items() if texts.plain(r)}, {})

        print("\n[a stored __MXU_PRETASK__LaunchGamePC entry in AUTO-MAS's MaaEnd config overrides the defaults]")
        stored = getattr(ml, "stored_override", None)
        check("maaend_launch.stored_override exists", callable(stored))
        if callable(stored):
            def doc(*ovs):
                return {"instances": [{"id": f"i{n}", "tasks": [{"taskName": "__MXU_PRETASK__LaunchGamePC",
                                                                "optionValues": ov}]} for n, ov in enumerate(ovs)]}
            check("no entry (AUTO-MAS adds an empty one): fine", stored({"instances": [{"tasks": []}]}), "")
            check("only the switch AUTO-MAS writes itself: fine",
                  stored(doc({"LaunchGamePCGameSetting": {"type": "switch", "value": False}})), "")
            check("the same window values stored: fine", stored(doc({
                "LaunchGamePCDisplayType": {"type": "select", "caseName": "Window"},
                "LaunchGamePCResolution": {"type": "select", "caseName": "1280x720"},
                "LaunchGamePCRegion": {"type": "select", "caseName": "CN"},
                "LaunchGamePCLauncherPath": {"type": "select", "caseName": "Auto"}})), "")
            overrides = {
                "DisplayType Fullscreen stored": stored(doc({"LaunchGamePCDisplayType": {"type": "select", "caseName": "Fullscreen"}})),
                "Resolution 1920x1080 stored as value": stored(doc({"LaunchGamePCResolution": {"type": "select", "value": "1920x1080"}})),
                "Region Global in a second instance": stored(doc({}, {"LaunchGamePCRegion": {"type": "select", "caseName": "Global"}})),
                "LauncherPath Manual stored": stored(doc({"LaunchGamePCLauncherPath": {"type": "select", "caseName": "Manual"}})),
                "an entry AUTO-MAS cannot read": stored(doc({"LaunchGamePCDisplayType": "Window"})),
                "no config to read": stored(None),
            }
            for what, why in overrides.items():
                check(f"{what}: refused", bool(why), True)
            check("every reason is plain Chinese", {w: texts.plain(r) for w, r in overrides.items() if texts.plain(r)}, {})

    # ─────────────────────────── efstart_setup.install ───────────────────────────

    print("\n[efstart_setup: AUTO-MAS on 「MaaEnd 启动」 with the four window settings, written before the mode]")
    root = tmpdir()
    lroot = root / "endfield" / "Hypergryph Launcher"
    game_dir = lroot / "games" / "Endfield Game"
    game_dir.mkdir(parents=True)
    (game_dir / "Endfield.exe").write_text("", encoding="utf-8")
    (lroot / "Launcher.exe").write_text("", encoding="utf-8")
    (lroot / "1.6.0").mkdir()
    (lroot / "1.6.0" / "Games.exe").write_text("", encoding="utf-8")
    game_exe = str(game_dir / "Endfield.exe")
    setup._is_file = lambda p: Path(str(p).replace("\\", "/")).is_file()
    setup._subdirs = lambda p: [str(x) for x in Path(str(p).replace("\\", "/")).iterdir() if x.is_dir()] \
        if Path(str(p).replace("\\", "/")).is_dir() else []
    automas = root / "automas"
    cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
    cfgdir.mkdir(parents=True)
    (cfgdir / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"name": "automas", "preActions": []}]}),
                                            encoding="utf-8")
    home = root / "state" / "efstart"
    home.mkdir(parents=True)
    (home / ef.TARGET).write_text(json.dumps({"game": game_exe, "original": {"game_path": game_exe, "wait_time": 60}}),
                                  encoding="utf-8")
    BEFORE = {"ControllerType": "Win32-Front", "LaunchMode": "Launcher", "Path": game_exe, "LauncherPath": "",
              "WaitTime": 60, "SetResolution": False, "CloseOnFinish": True, "RestoreDisplayType": "Window",
              "RestoreResolution": "Off", "RestoreResolutionWidth": 1920, "RestoreResolutionHeight": 1080,
              "IfAutoUpdate": False}
    mas = {"data": {"59da8762": {"Info": {"Name": "MaaEnd", "Path": str(FX)}, "Game": dict(BEFORE)}}}
    writes, refuse = [], set()

    def fake_mas(path, body=None, timeout=20):
        if path == "/api/queue/get":    # commands.mas_up: the backend answers (boot_stages.await_backend)
            return {"code": 200, "data": {}}
        if path == "/api/scripts/get":
            return json.loads(json.dumps(mas))
        if path == "/api/scripts/update":
            (k, v), = body["data"]["Game"].items()
            if k in refuse:
                return {"code": 500, "message": "正在运行, 无法更新配置项"}
            writes.append((k, v))
            mas["data"][body["scriptId"]]["Game"][k] = v
            return {"code": 200}
        raise AssertionError(path)

    cfg = types.SimpleNamespace(state_dir=root / "state", automas_dir=automas, maaend_dir=None)
    game = mas["data"]["59da8762"]["Game"]
    saved_mas = commands._mas
    commands._mas = fake_mas
    try:
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("all done", ok, True)
        check("LaunchMode MaaEnd and the four settings as run on 10-17",
              {k: game[k] for k in ("LaunchMode", "SetResolution", "CloseOnFinish", "RestoreDisplayType", "RestoreResolution")},
              {"LaunchMode": "MaaEnd", "SetResolution": True, "CloseOnFinish": True,
               "RestoreDisplayType": "Fullscreen", "RestoreResolution": "1920x1080"})
        check("written: the three that differed, then the mode last",
              writes, [("SetResolution", True), ("RestoreDisplayType", "Fullscreen"), ("RestoreResolution", "1920x1080"),
                       ("LaunchMode", "MaaEnd")])
        check("nothing else touched (path, launcher path, wait, the custom size)",
              {k: game[k] for k in BEFORE if k not in ("LaunchMode", "SetResolution", "RestoreDisplayType", "RestoreResolution")},
              {k: v for k, v in BEFORE.items() if k not in ("LaunchMode", "SetResolution", "RestoreDisplayType",
                                                             "RestoreResolution")})
        n = len(writes)
        check("run again: all done, nothing said", setup.install(cfg, code_root=Path("C:/relay/versions/7")), (True, []))
        check("run again: nothing written", len(writes), n)

        (lroot / "1.6.0" / "Games.exe").unlink()
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("「MaaEnd 启动」 and AUTO-MAS's own launcher rule finds nothing: fine (MaaEnd finds it itself)",
              (ok, [x for x in notes if texts.ENDFIELD_NO_LAUNCHER in x]), (True, []))
        (lroot / "1.6.0" / "Games.exe").write_text("", encoding="utf-8")

        print("\n[MaaEnd cannot start it windowed: back to 「启动器启动」, and the group hears it]")
        mas["data"]["59da8762"]["Info"]["Path"] = str(BETA2)
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("not done", ok, False)
        check("LaunchMode back to Launcher", game["LaunchMode"], "Launcher")
        check("said why, naming what an unticked box then does", any(NO_MAAEND_START in x for x in notes))
        check("that sentence is plain", texts.plain(NO_MAAEND_START), [])
        import boot_stages

        class _Log:
            def __init__(self):
                self.warned = []

            def info(self, *a, **k):
                pass

            def warning(self, msg, *a, **k):
                self.warned.append(msg % a)

            def exception(self, msg, *a, **k):
                self.warned.append("EXC " + msg % a)
        lg = _Log()
        boot_stages._endfield_launch(cfg, lg, "开机")
        check("at boot: one WARNING (errwatch pushes it to the group) naming it",
              (len(lg.warned), NO_MAAEND_START in (lg.warned or [""])[0]), (1, True))
        check("…said again at the next boot while it lasts (not an INFO note)",
              (boot_stages._endfield_launch(cfg, lg, "开机"), len(lg.warned)), (None, 2))

        print("\n[MaaEnd's default is not the window: AUTO-MAS would start it fullscreen, so 「启动器启动」 stays]")
        game.update(BEFORE)
        lg.warned.clear()
        mas["data"]["59da8762"]["Info"]["Path"] = str(maaend_copy(lambda d: edit_json(
            d / "tasks" / "pretasks" / "LaunchGamePC.json",
            lambda j: j["option"]["LaunchGamePCDisplayType"].update(default_case="Fullscreen"))))
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("DisplayType default Fullscreen: not done, still 「启动器启动」", (ok, game["LaunchMode"]), (False, "Launcher"))
        check("…and said", any(NO_MAAEND_START in x for x in notes))
        boot_stages._endfield_launch(cfg, lg, "开机")
        check("…as a WARNING at boot", (len(lg.warned), NO_MAAEND_START in (lg.warned or [""])[0]), (1, True))

        print("\n[AUTO-MAS's MaaEnd config stores a fullscreen pretask value: 「启动器启动」 stays]")
        mas["data"]["59da8762"]["Info"]["Path"] = str(FX)
        mfile = cfgdir / "mxu-MaaEnd.json"
        plain_master = mfile.read_text(encoding="utf-8")

        def stored_master(ov):
            mfile.write_text(json.dumps({"instances": [{"name": "automas", "preActions": [], "tasks": [
                {"taskName": "__MXU_PRETASK__LaunchGamePC", "enabled": False, "optionValues": ov}]}]}), encoding="utf-8")
        stored_master({"LaunchGamePCDisplayType": {"type": "select", "caseName": "Fullscreen"}})
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("stored DisplayType Fullscreen: not done, still 「启动器启动」", (ok, game["LaunchMode"]), (False, "Launcher"))
        check("…and said", any(NO_MAAEND_START in x for x in notes))
        stored_master({"LaunchGamePCDisplayType": {"type": "select", "caseName": "Window"},
                       "LaunchGamePCGameSetting": {"type": "switch", "value": False}})
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("stored Window (the same as the default): 「MaaEnd 启动」", (ok, game["LaunchMode"]), (True, "MaaEnd"))
        mfile.write_text(plain_master, encoding="utf-8")

        print("\n[a window setting AUTO-MAS refuses: the mode is not switched]")
        mas["data"]["59da8762"]["Info"]["Path"] = str(FX)
        game.update(BEFORE)
        refuse.add("RestoreResolution")
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("not done, still 「启动器启动」", (ok, game["LaunchMode"]), (False, "Launcher"))
        check("…and said", any(NO_MAAEND_START in x for x in notes))
        refuse.clear()

        print("\n[restore (by hand): back to 「启动器启动」 and the values before]")
        setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        okr, _ = setup.restore(cfg)
        check("restore", (okr, {k: game[k] for k in ("LaunchMode", "SetResolution", "CloseOnFinish",
                                                     "RestoreDisplayType", "RestoreResolution")}),
              (True, {"LaunchMode": "Launcher", "SetResolution": False, "CloseOnFinish": True,
                      "RestoreDisplayType": "Window", "RestoreResolution": "Off"}))
    finally:
        commands._mas = saved_mas

    # ─────────────────────────── efstart: the relay's own start ───────────────────────────

    print("\n[efstart: the relay's own start runs MaaEnd's pretask on the desktop and checks its exit code]")
    has_flow = hasattr(ef, "start_via_maaend")
    check("efstart starts the game through MaaEnd's pretask", has_flow)
    check("nothing in efstart ticks the DirectX 11 box any more",
          [n for n in ("_ensure_d3d11", "_toggle_d3d11", "D3D11_BOX_FROM_START", "box_brightness") if hasattr(ef, n)], [])

    class Desk:
        """The machine as the helper sees it: processes, the pretask's exit code, the display."""

        def __init__(self, *, game=False, code=0):
            self.game, self.code, self.events = game, code, []

        def running(self, names):
            return {n for n in names if n == "Endfield.exe" and self.game}

        def kill(self, *names):
            self.events.append(("kill",) + names)
            self.game = self.game and "Endfield.exe" not in names
            return True

        def run(self, argv, cwd, timeout):
            self.events.append(("run", argv, cwd, timeout))
            if self.code == 0:
                self.game = True
            return self.code, "launcher pipeline failed" if self.code else ""

        def wake(self):
            self.events.append(("wake",))
            return True

        def probes(self):
            return ef.Probes(running=self.running, kill=self.kill, run=self.run, wake=self.wake, sleep=lambda s: None)

    if has_flow:
        md = maaend_copy()
        w = Desk()
        r = ef.start_via_maaend(md, w.probes())
        check("exit 0: OK", r.code, ef.OK)
        check("woke the display, then ran go-service.exe --pretask LaunchGamePC <the 10-17 options> "
              "from the MaaEnd folder with AUTO-MAS's 240 s",
              w.events, [("wake",), ("run", [str(md / "agent" / "go-service.exe"), "--pretask", "LaunchGamePC", MACHINE_ARGS],
                                    str(md), 240)])
        w = Desk(game=True)
        r = ef.start_via_maaend(md, w.probes())
        check("game already open: closed first (the pretask would skip the window), then started",
              ([e[0] for e in w.events], r.code), (["kill", "wake", "run"], ef.OK))
        w = Desk(code=1)
        r = ef.start_via_maaend(md, w.probes())
        check("exit 1: failed, and counted as a start that ran (window settings written)",
              (r.code, r.code in ef.RAN), (ef.PRETASK, True))
        w = Desk(code=None)
        check("past 240 s: timed out, also counted as ran", (lambda x: (x.code, x.code in ef.RAN))(
            ef.start_via_maaend(md, w.probes())), (ef.TIMED_OUT, True))
        w = Desk()
        r = ef.start_via_maaend(maaend_copy(lambda d: (d / "agent" / "go-service.exe").unlink()), w.probes())
        check("no go-service.exe: refused before anything runs", (r.code, r.code in ef.RAN, w.events), (ef.SETUP, False, []))
        r = ef.start_via_maaend(BETA2, Desk().probes())
        check("a MaaEnd without the pretask: refused", r.code, ef.SETUP)
        check("every reason is plain", [texts.plain(x) for x in (r.reason,) if texts.plain(x)], [])
        check("no MaaEnd folder given: refused", ef.run_once(tmpdir(), "relay", "", probes=Desk().probes()).code, ef.SETUP)

        sd = tmpdir()
        (sd / "efstart").mkdir()
        (sd / "efstart" / ef.TRAMPOLINE).write_text("# trampoline\n", encoding="utf-8")
        calls = []

        def fake_spawn(exe, cwd, args):
            calls.append(args)
            Path(args[args.index("--result") + 1]).write_text(json.dumps({"code": 0, "reason": "ok"}), encoding="utf-8")
            return True
        r = ef.run_on_desktop(sd, fake_spawn, md, pythonw=Path("pythonw.exe"), sleep=lambda s: None)
        check("run_on_desktop hands the helper the MaaEnd folder",
              (r.code, calls[0][calls[0].index("--maaend") + 1] if calls and "--maaend" in calls[0] else None),
              (ef.OK, str(md)))

    # ─────────────────────────── collect_retry ───────────────────────────

    print("\n[collect_retry: the game starts the same way, and fullscreen is written back before MaaEnd closes]")
    CLOSE_LINE = ('[2026-10-17 11:33:31.200][INF][Px1][Tx2][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] '
                  '!!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.{}] '
                  '[details={{"entry":"CloseGamePC","hash":"","task_id":200000002,"uuid":""}}]')

    class MXU:
        def __init__(self, md, close="Succeeded"):
            self.md, self.close, self.calls = md, close, []
            (md / "debug").mkdir(exist_ok=True)
            (md / "debug" / "maafw.log").write_text("", encoding="utf-8")

        def __call__(self, path, body=None, timeout=30):
            self.calls.append((path, body))
            if path == "/maa/state":
                return {"instances": {"automas": {"connected": True, "resource_loaded": True, "is_running": False}}}
            if path.startswith("/maa/windows"):
                return [{"handle": 4242}]
            if path.endswith("/tasks/start") and body["tasks"][0]["entry"] == "CloseGamePC" and self.close:
                with (self.md / "debug" / "maafw.log").open("a", encoding="utf-8") as fh:
                    fh.write(CLOSE_LINE.format(self.close) + "\n")
            return {}

        def entries(self):
            return [(p.rsplit("/", 1)[-1], b["tasks"][0]["entry"] if p.endswith("/tasks/start") else None)
                    for p, b in self.calls if p.endswith(("/tasks/start", "/agent/stop"))]

    def retry(md, mxu, started=None):
        seen, got = [], {}
        saved = (cr._running, cr._wait, cr.api, cr.mxu_port, cr.time, ef.run_on_desktop)
        cr._running = lambda names: {"MaaEnd.exe"}
        cr._wait = lambda pred, seconds, step=3.0: bool(pred())
        cr.api = mxu
        cr.mxu_port = lambda d: 12701
        cr.time = types.SimpleNamespace(sleep=lambda s: None, strftime=lambda f: "00:00:00", time=lambda: 0)
        ef.run_on_desktop = lambda state_dir, spawn, *a, **k: (seen.append((state_dir,) + a) or
                                                               (started or ef.Result(ef.OK, "开了")))
        try:
            verdict, note = cr._bring_up_and_run(md, ["AutoCollectRoute15"], {}, spawn=lambda *a: None, timeout=10,
                                                 evidence=got, state_dir="SD")
        finally:
            cr._running, cr._wait, cr.api, cr.mxu_port, cr.time, ef.run_on_desktop = saved
        return seen, note, got

    md = maaend_copy()
    mxu = MXU(md)
    seen, note, got = retry(md, mxu)
    check("the helper is given the MaaEnd folder", seen, [("SD", md)])
    check("gathering, the gathering's agents stop, CloseGamePC, then its agents stop",
          mxu.entries(), [("start", "AutoCollectSchedule"), ("stop", None), ("start", "CloseGamePC"), ("stop", None)])
    close_body = next((b for p, b in mxu.calls if p.endswith("/tasks/start") and b["tasks"][0]["entry"] == "CloseGamePC"), None)
    check("CloseGamePC carries the fullscreen 1920x1080 override",
          json.loads(close_body["tasks"][0]["pipeline_override"]) if close_body else None, RESTORE)
    check("…with MaaEnd's agents (CloseGameAction lives in go-service)",
          [a["child_exec"] for a in (close_body or {}).get("agent_configs", [])], ["agent/go-service", "agent/cpp-algo"])
    check("succeeded: nothing to add", (note, got.get("not_restored")), ("", None))

    md = maaend_copy()
    seen, note, got = retry(md, MXU(md, close="Failed"))
    check("CloseGamePC failed: the note says fullscreen was not written back", "没改回全屏" in note)
    check("…and maybe_run hears of it", bool(got.get("not_restored")))
    check("…in plain words", texts.plain(note), [])

    md = maaend_copy()
    seen, note, got = retry(md, MXU(md), ef.Result(PRETASK, "MaaEnd 开游戏没成功（退出码 1）"))
    check("the pretask ran and failed: no window, nothing to close it with; said", ("没改回全屏" in note, bool(got)),
          (True, True))
    md = maaend_copy()
    seen, note, got = retry(md, MXU(md), ef.Result(ef.SETUP, "开游戏的助手没装好"))
    check("the pretask never ran: nothing about fullscreen", ("没改回全屏" in note, got), (False, {}))
    md = maaend_copy(lambda d: edit_json(d / "interface.json", lambda j: j["import"].pop()))
    seen, note, got = retry(md, MXU(md))
    check("a MaaEnd that cannot write fullscreen back: the game is not started at all", (seen, bool(note)), ([], True))

    print("\n[maybe_run: every route walked but fullscreen not back → a WARNING (the group); otherwise none]")

    class _Warn(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    def outcome(not_restored):
        from datetime import datetime as _dt
        sd = tmpdir()
        zh = json.loads((fx_dir(HERE, "fixtures") / "collect-retry-2026-09-11" / "zh_cn.json").read_text(encoding="utf-8"))
        sent = []
        eng = types.SimpleNamespace(
            cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(sd), history_dir=str(sd), automas_dir=None),
            state=types.SimpleNamespace(read_ledger=lambda d: [], mark_incomplete=lambda *a: True,
                                        clear_incomplete_items=lambda *a: True),
            notifier=types.SimpleNamespace(send=lambda t, b, **kw: sent.append((t, kw.get("alert", False))) or []),
            _scripts_running=lambda: False)

        def fake_retry(*a, evidence=None, **k):
            if not_restored and evidence is not None:
                evidence["not_restored"] = "MaaEnd 关游戏时没能把显示设置写回"
            return {"AutoCollectRoute15": True}, ""
        saved = (cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master)
        cr.latest_gathering_run = lambda entries, hist, labels: ({"run_id": "r1"}, ["AutoCollectRoute15"])
        cr.run_retry, cr._locale, cr.restore_master = fake_retry, (lambda d: zh), (lambda cfg: "")
        h = _Warn()
        cr.log.addHandler(h)
        try:
            cr.maybe_run(eng, now=_dt(2026, 10, 17, 21, 0).astimezone(), day="2026-10-17")
        finally:
            cr.log.removeHandler(h)
            cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master = saved
        return [x for x in h.lines if "全屏" in x], sent

    warned, sent = outcome(True)
    check("not back: one WARNING", len(warned), 1)
    check("the routes still count as walked (daily report only)", sent, [(texts.COLLECT_RETRY_OK, False)])
    check("back: no WARNING", outcome(False)[0], [])

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_automas_backend_match():
    """Only AUTO-MAS's own main.py is the backend; a failed OpenProcess tries the next match (audit s15 #3).
    """
    import ast
    import re

    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom")

    from ark_relay.features import automas_keeper as automas_procs
    from ark_relay.features import commands

    line = (fx_dir(Path(__file__), "fixtures") / "okww_argv_20261012.log").read_text(encoding="utf-8")
    okww_script = ast.literal_eval(re.search(r"(\[.*?\])", line).group(1))[0]
    OKWW = rf"D:\ark\okww\data\apps\ok-ww\python\python.exe {okww_script}"
    BACKEND = r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"
    check("record: OK-WW runs a main.py", okww_script.endswith("main.py"), True)

    commands.mas_up = lambda: (_ for _ in ()).throw(AssertionError("the list was readable"))

    print("[后台没在跑、只有鸣潮脚本在跑：不算后台在跑]")
    automas_procs._python_processes = lambda: [(25244, OKWW)]
    check("_automas_running", automas_procs._automas_running(), False)
    opened = []

    def _open(access, inherit, pid):
        opened.append(pid)
        return f"handle:{pid}"

    automas_procs.win32api.OpenProcess = _open
    check("_automas_handle does not adopt OK-WW", automas_procs._automas_handle(), None)
    check("OK-WW's pid never opened", opened, [])

    print("[后台在跑：认得出]")
    automas_procs._python_processes = lambda: [(25244, OKWW), (5088, BACKEND)]
    check("_automas_running", automas_procs._automas_running(), True)
    check("_automas_handle takes the backend", automas_procs._automas_handle(), "handle:5088")
    automas_procs._python_processes = lambda: [(6000, "d:/ARK/AutoMAS/repo/Main.py")]
    check("forward slashes and case do not matter", automas_procs._automas_running(), True)

    print("[第一个匹配打不开：接着试下一个]")
    opened.clear()

    def _open_second(access, inherit, pid):
        opened.append(pid)
        if pid == 4100:
            raise OSError("access denied / gone")
        return f"handle:{pid}"

    automas_procs.win32api.OpenProcess = _open_second
    automas_procs._python_processes = lambda: [(4100, BACKEND), (5088, BACKEND)]
    check("the second match is attached", automas_procs._automas_handle(), "handle:5088")


def _part_automas_boot_one_alarm():
    """One AUTO-MAS start failure at boot is one group message (audit s23 F2, 10-13)."""
    import logging
    import time
    import types
    from datetime import datetime, timezone

    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                 "win32com", "win32com.client")

    import boot_stages
    from ark_relay.core import texts
    from ark_relay.features import errwatch
    from ark_relay.features import okww_overlay
    from ark_relay.features import commands, phone, phone as phone_channel
    from ark_relay.features import preupdate

    class Records(logging.Handler):
        """Every record under the "ark" logger, as errwatch sees them."""

        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.recs: list[logging.LogRecord] = []

        def emit(self, record):
            self.recs.append(record)

        def pushed_by_errwatch(self) -> list[str]:
            """WARNING / ERROR lines errwatch would push: not marked as already in the group."""
            return [r.getMessage() for r in self.recs if r.levelno >= logging.WARNING
                    and not getattr(r, errwatch.PUSHED, False) and not getattr(r, errwatch.RECOVERED, False)]

    class Notes:
        def __init__(self):
            self.sent: list[tuple[str, bool]] = []

        def send(self, title, body="", **kw):
            self.sent.append((title, bool(kw.get("alert"))))
            return []

        def went_to_group(self):
            return True

        def alarms(self) -> list[str]:
            return [t for t, alert in self.sent if alert]

    REC = Records()
    ARK = logging.getLogger(errwatch.ARK)
    ARK.addHandler(REC)
    ARK_LEVEL = ARK.level
    ARK.setLevel(logging.DEBUG)

    # AUTO-MAS never answers; a fake clock so the 120 s wait costs nothing.
    clock = {"t": 0.0}
    real_sleep, real_monotonic = boot_stages.time.sleep, boot_stages.time.monotonic
    saved = (commands.mas_up, boot_stages.shell_running, boot_stages._revive_automas,
             boot_stages._stop_requested, phone.Mailbox, phone.Heartbeat, phone.state_payload,
             phone_channel._make_phone_cmd)

    def advance(s):
        clock["t"] += s

    class FakeBox:
        def __init__(self, topic, pin, state_dir, cos=None):
            self.topic, self.cos, self.enabled = topic, cos, True
            self.quota = phone.Quota(state_dir)
            self.last_error = ""

        def publish(self, body):
            return True

        def fetch(self):
            return []

        def listen(self, on_cmd, stop, **kw):
            pass

    class FakeHb:
        def __init__(self, *a, **k): pass
        def loop(self, stop): return None
        def watch(self): pass

    def fake_make_phone_cmd(*a, **k):
        def run(body):
            pass
        run.drain = lambda: None
        return run

    try:
        boot_stages.time.sleep = advance
        boot_stages.time.monotonic = lambda: clock["t"]
        commands.mas_up = lambda: False
        boot_stages.shell_running = lambda: False
        boot_stages._revive_automas = lambda: None
        boot_stages._stop_requested = lambda: False
        phone.Mailbox, phone.Heartbeat = FakeBox, FakeHb
        phone.state_payload = lambda cfg, state_dir: {"at": 1}
        phone_channel._make_phone_cmd = fake_make_phone_cmd

        print("[boot: AUTO-MAS does not come up after the revival]")
        sd = tmpdir()
        cfg = types.SimpleNamespace(phone_topic="topic-abc", phone_pin="8964", state_dir=sd,
                                    cos_secret_id="", cos_secret_key="", cos_bucket="", cos_region="")
        engine = types.SimpleNamespace(scripts_running=lambda: False, _started_at=datetime.now(timezone.utc))
        notes = Notes()
        log = logging.getLogger("ark.test_preupdate")
        phone_channel._start_phone_channel(types.SimpleNamespace(stop_event=None), cfg, engine, notes, log)
        time.sleep(0.05)               # the listener thread
        # Only the AUTO-MAS ones: the fake state payload fails a machine check of its own.
        down = [t for t in notes.alarms() if "AUTO-MAS" in t]
        loud = [m for m in REC.pushed_by_errwatch() if "AUTO-MAS" in m]
        check("the 🔌 alarm went out once", down, [texts.AUTOMAS_DOWN])
        check("errwatch has nothing more to push for it", loud, [])
        check("so the group gets one message", len(down) + len(loud), 1)
        check("the ERROR line is still in relay.log (selfcheck reads 「秒内…仍不通」)",
              any("秒内接口仍不通" in r.getMessage() for r in REC.recs), True)

        print("[the morning pre-update right after: no second wait, one problem line]")
        REC.recs.clear()
        ensured: list[int] = []
        real_ensure = boot_stages.ensure_automas
        boot_stages.ensure_automas = lambda *a, **k: ensured.append(1) or real_ensure(*a, **k)
        asked = {"automas": 0, "okww": 0}

        def run_automas(*a, problems=None, **k):
            asked["automas"] += 1
            problems.append("AUTO-MAS 预更新：接口不通，没查到版本")
            return ""

        def run_okww(*a, problems=None, **k):
            asked["okww"] += 1
            return ""

        saved_pre = (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run,
                     preupdate.run_automas, preupdate.run_okww, okww_overlay.retry_pending,
                     okww_overlay.drift_line, boot_stages._seconds_to_next_queue)
        preupdate.wanted_today = lambda *a, **k: True
        preupdate.should_run = lambda *a, **k: True
        marks: list[bool] = []
        preupdate.mark_run = lambda state_dir, now, clean: marks.append(clean)
        preupdate.run_automas, preupdate.run_okww = run_automas, run_okww
        okww_overlay.retry_pending = lambda *a, **k: None
        okww_overlay.drift_line = lambda *a, **k: ""
        boot_stages._seconds_to_next_queue = lambda automas_dir, now: 3600.0
        t0 = clock["t"]
        notes = Notes()
        pcfg = types.SimpleNamespace(automas_dir=None, okww_dir=Path("okww"), state_dir=None)
        try:
            boot_stages._stage_preupdate(pcfg, notes, log)
        finally:
            (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run,
             preupdate.run_automas, preupdate.run_okww, okww_overlay.retry_pending,
             okww_overlay.drift_line, boot_stages._seconds_to_next_queue) = saved_pre
            boot_stages.ensure_automas = real_ensure
        check("no second ensure_automas", ensured, [])
        check("no second 150 + 120 s wait", clock["t"] - t0, 0.0)
        check("the AUTO-MAS item is skipped, OK-WW still runs", asked, {"automas": 0, "okww": 1})
        check("no second 「仍不通」 ERROR", any("仍不通" in r.getMessage() for r in REC.recs), False)
        unconfirmed = [t for t in notes.alarms() if t.startswith(texts.unconfirmed("预更新", 1)[:6])]
        check("one 「没能确认」 alarm with one line", unconfirmed, [texts.unconfirmed("预更新", 1)])
        check("the day's pre-update is not clean (tried again next boot)", marks, [False])
    finally:
        boot_stages.time.sleep, boot_stages.time.monotonic = real_sleep, real_monotonic
        (commands.mas_up, boot_stages.shell_running, boot_stages._revive_automas,
         boot_stages._stop_requested, phone.Mailbox, phone.Heartbeat, phone.state_payload,
         phone_channel._make_phone_cmd) = saved
        ARK.removeHandler(REC)
        ARK.setLevel(ARK_LEVEL)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_automas_boot_revival():
    """The boot-time revival must wait for a shell that is already starting, kill the
runtime as well when it does restart, and the keeper must not go blind without wmic.
    """
    import types


    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                 "win32com", "win32com.client")

    import logging

    import boot_stages
    import service
    from ark_relay.features import automas_keeper as automas_procs
    from ark_relay.features import commands
    from ark_relay.features import errwatch
    from ark_relay.core import texts


    _real_sleep, _real_monotonic = boot_stages.time.sleep, boot_stages.time.monotonic
    boot_stages.time.sleep = lambda s: None
    clock = {"t": 0.0}
    boot_stages.time.monotonic = lambda: clock["t"]


    def _tick(seconds):
        """Every sleep(3) inside _wait_for_api advances the fake clock."""
        def sleep(s):
            clock["t"] += s
        boot_stages.time.sleep = sleep


    _tick(3)
    # The win32 stubs above answer every call with a truthy object, which would make
    # errwatch.system_shutting_down() read "going down"; the stop signal is driven
    # explicitly by the cases below.
    boot_stages._stop_requested = lambda: False
    revived = []
    boot_stages._revive_automas = lambda: revived.append(clock["t"])


    class _Levels(logging.Handler):
        """ensure_automas's lines (logger ark.service): (level, first line, marked recovered)."""

        def __init__(self):
            super().__init__(logging.DEBUG)
            self.got = []

        def emit(self, record):
            self.got.append((record.levelname, record.getMessage().splitlines()[0],
                             bool(getattr(record, errwatch.RECOVERED, False))))

        def loud(self):
            """WARNING / ERROR lines errwatch pushes to the group (not marked recovered)."""
            return [m for lv, m, rec in self.got if lv in ("WARNING", "ERROR") and not rec]

        def recovered(self):
            return [m for lv, m, rec in self.got if lv == "WARNING" and rec]


    _levels = _Levels()
    _svc_log = service.log
    _svc_log.addHandler(_levels)
    _svc_log.setLevel(logging.DEBUG)


    def _api(up_after):
        """mas_up() answers True once the fake clock passes `up_after` seconds."""
        return lambda: clock["t"] >= up_after


    print("[窗口已在、接口还没开：等它，不杀]")
    clock["t"] = 0; revived.clear()
    boot_stages.shell_running = lambda: True
    commands.mas_up = _api(30)
    check("等到接口开了就返回 True", boot_stages.ensure_automas(timeout=120, grace=150), True)
    check("没有杀过一次", revived, [])
    check("等了约 30 秒", 27 <= clock["t"] <= 33)

    print("\n[窗口在但宽限期内接口一直不开：宽限期满才杀、再等 timeout]")
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    commands.mas_up = _api(10**9)
    check("最终返回 False", boot_stages.ensure_automas(timeout=120, grace=150), False)
    check("杀了一次", len(revived), 1)
    check("是在宽限期（150 秒）之后才杀的", revived[0] >= 150)
    check("杀完又等了 timeout", clock["t"] >= 150 + 120)
    # Not back: the ERROR (pushed), and only that - the steps before it are INFO.
    check("not recovered: one line for the group, the ERROR", _levels.loud(),
          ["AUTO-MAS 拉起后 120 秒内接口仍不通"])
    check("nothing marked recovered", _levels.recovered(), [])

    print("\n[窗口在、宽限期满才杀、杀后起来了：进群（没应答的原因不明，2026-10-10 前只进日报）]")
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    commands.mas_up = _api(170)
    check("returns True", boot_stages.ensure_automas(timeout=120, grace=150), True)
    check("one line for the group, naming the wait that failed",
          [("窗口开着、等了 150 秒还没应答" in m) for m in _levels.loud()], [True])
    check("nothing marked recovered", _levels.recovered(), [])

    print("\n[窗口根本不在：立刻拉起]")
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    boot_stages.shell_running = lambda: False
    commands.mas_up = _api(20)
    check("拉起后接口开了返回 True", boot_stages.ensure_automas(timeout=120, grace=150), True)
    check("立刻杀/拉起，没有先等宽限期", revived == [0.0])
    check("nothing marked recovered", _levels.recovered(), [])
    rec_lines = _levels.loud()
    check("one WARNING for the group", len(rec_lines), 1)
    check("plain words, and selfcheck still reads it (「AUTO-MAS 已…秒）」)",
          bool(rec_lines) and not texts.plain(rec_lines[0]) and rec_lines[0].startswith("AUTO-MAS 已")
          and rec_lines[0].endswith("秒）"), True)
    from ark_relay.features import selfcheck
    day_line = "09-30 08:40:10 WARNING  ark.service  " + (rec_lines[0] if rec_lines else "")
    check("selfcheck's daily lines still count it as 「重开后起来了」",
          any("重开后起来了" in x for x in selfcheck.daily_lines("2026-09-30", day_line)), True)

    print("\n[拉起后、等它起来时服务停了（不是中继自己关机）：没确认起来，报群]")
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    commands.mas_up = _api(10**9)
    boot_stages._stop_requested = lambda: clock["t"] >= 9
    check("returns False", boot_stages.ensure_automas(timeout=120, grace=150), False)
    check("one WARNING for the group", [("服务就停了" in m) for m in _levels.loud()], [True])
    clock["t"] = 0; revived.clear(); _levels.got.clear()
    errwatch._relay_poweroff[0] = lambda: True
    check("the relay's own power-off: returns False", boot_stages.ensure_automas(timeout=120, grace=150), False)
    errwatch._relay_poweroff[0] = lambda: False
    check("... and nothing for the group", _levels.loud(), [])
    boot_stages._stop_requested = lambda: False

    print("\n[等待中收到停止信号：立刻返回，不杀不拉，不发「AUTO-MAS 没起来」]")
    clock["t"] = 0; revived.clear()
    boot_stages.shell_running = lambda: True
    commands.mas_up = _api(10**9)
    boot_stages._stop_requested = lambda: clock["t"] >= 9
    check("停止一到就返回 False", boot_stages.ensure_automas(timeout=120, grace=150), False)
    check("在停止后一次轮询内退出（不到 15 秒）", clock["t"] < 15, True)
    check("没有杀过 AUTO-MAS", revived, [])
    clock["t"] = 0; revived.clear()
    boot_stages.shell_running = lambda: False
    boot_stages._stop_requested = lambda: True
    check("窗口不在但正在停止：也不拉", boot_stages.ensure_automas(timeout=120, grace=150), False)
    check("确实没拉", revived, [])
    boot_stages._stop_requested = lambda: False

    print("\n[接口本来就通：什么都不做]")
    clock["t"] = 0; revived.clear()
    commands.mas_up = lambda: True
    check("直接 True", boot_stages.ensure_automas(), True)
    check("没动手", revived, [])

    print("\n[_revive_automas 连 auto-mas-runtime.exe 一起杀]")
    ran = []
    import importlib
    importlib.reload(boot_stages)
    boot_stages.time.sleep = lambda s: None
    boot_stages.subprocess.run = lambda cmd, **kw: (ran.append(" ".join(cmd)),
                                                    types.SimpleNamespace(returncode=0, stdout=b""))[1]
    boot_stages._revive_automas()
    check("先杀窗口", any("taskkill /IM AUTO-MAS.exe /F" in c for c in ran))
    check("再杀 runtime（不杀它，新窗口会卡在 MUTATION_IN_PROGRESS）",
          any("taskkill /IM auto-mas-runtime.exe /F" in c for c in ran))
    check("然后 /end 再 /run", ran[-2].startswith("schtasks /end") and ran[-1].startswith("schtasks /run"))
    check("杀窗口在杀 runtime 之前",
          [i for i, c in enumerate(ran) if "AUTO-MAS.exe" in c][0]
          < [i for i, c in enumerate(ran) if "auto-mas-runtime.exe" in c][0])

    print("\n[开机拉不起来要立刻报警（群）]")
    check("文案在 texts 里且是人话", texts.plain(texts.automas_boot_down_body()), [])
    from ark_relay.core.notify import route_of
    check("走群机器人", route_of(texts.AUTOMAS_DOWN, alert=True), "group")

    print("\n[没有 wmic 的机器上 keeper 不许装瞎]")
    automas_procs._python_processes = lambda: None          # the query itself failed
    commands.mas_up = lambda: False
    check("进程表读不到、接口不通 → 不在（以前是「假定活着」）", automas_procs._automas_running(), False)
    commands.mas_up = lambda: True
    check("进程表读不到、接口通 → 在", automas_procs._automas_running(), True)
    automas_procs._python_processes = lambda: [(4132, r'"C:\Program Files\Python314\python.exe" C:\ProgramData\x.py')]
    commands.mas_up = lambda: True
    check("有 python 但不是 main.py → 不在（接口不算，句柄要挂在进程上）",
          automas_procs._automas_running(), False)
    automas_procs._python_processes = lambda: [(21932, r'"D:\ark\automas\runtime\environment\python\python.exe" D:\ark\automas\repo\main.py')]
    check("有 main.py → 在", automas_procs._automas_running(), True)

    print("\n[AUTO-MAS 的收尾记录不当成一趟运行核对]")
    from ark_relay.features import handle
    check("识别文本来自真实记录", handle.MAAEND_NOTHING_TO_RUN in handle.MAAEND_NOTHING_TO_RUN_LOG)
    import tempfile
    from datetime import datetime
    from ark_relay.core.config import RunRecord, SERVER_TZ
    with tempfile.TemporaryDirectory() as td:
        lp = Path(td) / "MaaEnd-06-32-49.log"
        lp.write_text("MaaEnd 没有可执行任务，请检查任务配置, 无日志记录", encoding="utf-8")
        rec = RunRecord(run_id="2026-09-17/endfield/MaaEnd-06-32-49", script="MaaEnd", user="endfield",
                        started=datetime(2026, 9, 17, 10, 32, 49, tzinfo=SERVER_TZ),
                        finished=datetime(2026, 9, 17, 10, 32, 49, tzinfo=SERVER_TZ), ok=True,
                        raw={"maaend_result": "[自动采集] MaaEnd 没有可执行任务，请检查任务配置"}, log_path=lp)
        eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=td, automas_dir=td, maa_dir=td))
        check("收尾记录 → 不报「没干完」", handle._verify_outcome(eng, rec), None)

    boot_stages.time.sleep, boot_stages.time.monotonic = _real_sleep, _real_monotonic

    print()
    if fails:
        print("FAILED:", fails); sys.exit(1)


def _part_automas_contract_watch():
    """scripts/mac/lib/automas_contract_watch.py: a new AUTO-MAS release is compared with the settings
the relay reads before the game machine installs it.
    """
    import io
    from contextlib import redirect_stdout

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parents[1] / "scripts" / "mac" / "lib"))
    sys.path.insert(0, str(HERE.parent))
    from ark_relay.core import mastercfg as masuser  # after the sys.path lines above
    try:
        import automas_contract_watch as w
        from ark_relay.core import mastercfg as mascontract
    except ImportError:          # the code before this change
        w = mascontract = None

    BETA2 = fx_dir(HERE, "fixtures") / "automas-models" / "config.py.txt"
    BETA3 = fx_dir(HERE, "fixtures") / "automas-models" / "config-v5.7.0-beta.3-excerpt.py.txt"
    BETA4 = fx_dir(HERE, "fixtures") / "automas-models" / "config-v5.7.0-beta.4-excerpt.py.txt"
    NEW_IN_BETA4 = ["MaaEndConfig Game.LaunchMode", "MaaEndConfig Game.LauncherPath"]
    NEW_IN_V58 = ["MaaEndConfig Update.Channel", "MaaEndConfig Update.TakeoverEnabled"]


    def run_main(*argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = w.main(list(argv))
        return code, buf.getvalue()


    check("the tool and the relay's list exist", w is not None and mascontract is not None)
    if w is not None and mascontract is not None:
        beta2, beta3 = w.parse(BETA2.read_text(encoding="utf-8")), w.parse(BETA3.read_text(encoding="utf-8"))
        beta4 = w.parse(BETA4.read_text(encoding="utf-8"))

        def named(gaps):
            return [g.split(":")[0] for g in gaps]
        # The list as it stood before masuser: the moved MAA user items read from Info only.
        before = [mascontract.Item(i.kind, i.level, "Info", i.key, i.use, i.source)
                  if i.level == "user" and i.key in masuser.MOVED else i for i in mascontract.CONTRACT]

        print("[v5.7.0-beta.3 against the list before masuser: the 10-14 move is named]")
        gaps = w.compare(beta3, before, version="v5.7.0-beta.4")
        moved = sorted(g.split(":")[0] + " -> " + g.split("moved to ")[1].split(" (")[0]
                       for g in gaps if "moved to" in g)
        check("every MAA user item the relay read from Info is reported moved", moved, [
            "MaaUserConfig Info.Annihilation -> Task.Annihilation",
            "MaaUserConfig Info.MedicineNumb -> Stage.MedicineNumb",
            "MaaUserConfig Info.SeriesNumb -> Stage.SeriesNumb",
            "MaaUserConfig Info.Stage -> Stage.Stage",
            "MaaUserConfig Info.StageMode -> Stage.StageMode",
            "MaaUserConfig Info.Stage_1 -> Stage.Stage_1",
            "MaaUserConfig Info.Stage_2 -> Stage.Stage_2",
            "MaaUserConfig Info.Stage_3 -> Stage.Stage_3",
        ])
        check("nothing else is reported but the two settings beta.4 brought in",
              sorted(set(named(gaps)) - {m.split(" -> ")[0] for m in moved}), NEW_IN_BETA4)
        check("v5.7.0-beta.2 against that same list: only those two (it still kept the rest in Info)",
              named(w.compare(beta2, before, version="v5.7.0-beta.4")), NEW_IN_BETA4)

        print("\n[the current list (mascontract + masuser)]")
        check("v5.7.0-beta.4 with version: nothing changed",
              w.compare(beta4, mascontract.CONTRACT, masuser.MOVED, version="v5.7.0-beta.4"), [])
        check("v5.7.0-beta.4 unversioned: flags only v5.8.0 MaaEnd Update items",
              sorted(named(w.compare(beta4, mascontract.CONTRACT, masuser.MOVED))), NEW_IN_V58)
        check("v5.7.0-beta.3: only the two settings beta.4 brought in",
              named(w.compare(beta3, mascontract.CONTRACT, masuser.MOVED, version="v5.7.0-beta.4")), NEW_IN_BETA4)
        check("v5.7.0-beta.2: the same two",
              named(w.compare(beta2, mascontract.CONTRACT, masuser.MOVED, version="v5.7.0-beta.4")), NEW_IN_BETA4)
        v58 = {k: dict(v) for k, v in beta4.items()}
        v58["MaaEndConfig"][("Update", "TakeoverEnabled")] = None
        v58["MaaEndConfig"][("Update", "Channel")] = None
        check("v5.8.0 with MaaEnd Update.TakeoverEnabled + Channel: nothing changed",
              w.compare(v58, mascontract.CONTRACT, masuser.MOVED, version="v5.8.0"), [])

        print("\n[a key a release drops is reported, a whole class too]")
        fake = [mascontract.Item("MAA", "user", "Stage", "NoSuchKey", "stage", "x.py:f"),
                mascontract.Item("plan", "plan", "Info", "Mode", "plan_table", "x.py:f")]
        no_plan = {k: v for k, v in beta3.items() if k != "MaaPlanConfig"}
        out = w.compare(no_plan, fake, masuser.MOVED)
        check("a dropped key", any(g.startswith("MaaUserConfig Stage.NoSuchKey: no longer defined") for g in out))
        check("a dropped class", any(g.startswith("MaaPlanConfig Info.Mode: class MaaPlanConfig is gone") for g in out))

        print("\n[parsing: helpers called with self, f-string keys, loop rows]")
        check("MaaEnd's helper items count for MaaEndUserConfig",
              ("Task", "SanityTaskType") in beta3["MaaEndUserConfig"])
        check("f\"If{task}\" becomes the pattern If*", ("Task", "If*") in beta3["MaaEndUserConfig"])
        check("legacy_group is read", beta3["MaaUserConfig"][("Stage", "Stage")], ("Info", "Stage"))

        print("\n[exit codes]")
        code, text = run_main("--file", str(BETA4))
        check("nothing changed: exit 0", code, 0)
        orig = mascontract.CONTRACT
        mascontract.CONTRACT = tuple(before)
        try:
            code, text = run_main("--file", str(BETA4))
        finally:
            mascontract.CONTRACT = orig
        check("something changed: exit 2", code, 2)
        check("and it is printed", "Info.Stage: moved to Stage.Stage" in text)
        real_http = w._http
        w._gh = lambda path: None

        def offline(url):
            raise w.urllib.error.URLError("offline")
        w._http = offline
        try:
            code, text = run_main()
        finally:
            w._http = real_http
        check("GitHub cannot be read: exit 3", code, 3)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_automas_handover():
    """relay/handover/automas_handover.py against a fake AUTO-MAS at the HTTP layer."""

    import io
    import json
    import os
    import urllib.error
    import urllib.request
    from contextlib import nullcontext

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "handover"))
    os.environ["ARK_MAS_PORT"] = "36163"
    import automas_handover as H
    from ark_relay.core import mastercfg as masuser

    H.this_week = lambda: "2026-W41"   # the game week every case below is run in

    MAA, END, OKWW, UID = "s-maa", "s-end", "s-okww", "u-1"

    def merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v

    class Backend:
        """mode: "up" | "down" (connection refused) | "running" (updates answer
    code 500 「正在运行, 无法更新配置项」, the message commands._refused cites)."""

        def __init__(self, mode="up", annihilation="Close", quick=True, server="Official", selfstart=True,
                     beta3=False):
            self.mode = mode
            self.beta3 = beta3
            self.calls = []
            self.scripts = {
                MAA: {"Info": {"Name": "MAA"}, "Run": {"IfCheckGameUpdate": False, "IfAutoInstallGameApk": False,
                                                      "HardTimeLimit": 120}},
                END: {"Info": {"Name": "MaaEnd"}, "Run": {"HardTimeLimit": 120}},
                OKWW: {"Info": {"Name": "OK-WW"}, "Run": {"HardTimeLimit": 120, "RunTimeLimit": 120},
                       "Game": {"Enabled": False, "Path": "", "IfAutoUpdate": True}},
            }
            self.users = {
                MAA: {UID: {"Info": {"Annihilation": annihilation, "IfQuickConfig": quick, "Server": server,
                                     "AnnihilationStartWeekday": "Monday"},
                            "Data": {"AnnihilationCompletedWeek": "2026-W41"}}},
                END: {UID: {"Info": {}}},
                OKWW: {UID: {"Info": {}}},
            }
            self.setting = {"Start": {"IfSelfStart": selfstart}}
            if beta3:
                # AUTO-MAS v5.7.0-beta.3 after its first start: the two annihilation items live
                # in Task only (app/models/config.py of that tag, Task_Annihilation and
                # Task_AnnihilationStartWeekday with legacy_group="Info").
                info = self.users[MAA][UID]["Info"]
                self.users[MAA][UID]["Task"] = {k: info.pop(k) for k in ("Annihilation", "AnnihilationStartWeekday")}

        def urlopen(self, req, timeout=None):
            path = req.full_url[len("http://127.0.0.1:36163"):]
            body = json.loads((req.data or b"{}").decode())
            self.calls.append((path, body))
            if self.mode == "down":
                raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
            if path.endswith("/update") and self.mode == "running":
                return _Resp({"code": 500, "status": "error", "message": "正在运行, 无法更新配置项"})
            if path == "/api/scripts/get":
                return _Resp({"code": 200, "data": self.scripts})
            if path == "/api/scripts/user/get":
                return _Resp({"code": 200, "data": self.users[body["scriptId"]]})
            if path == "/api/setting/get":
                return _Resp({"code": 200, "data": self.setting})
            if path == "/api/scripts/update":
                merge(self.scripts[body["scriptId"]], body["data"])
                return _Resp({"code": 200})
            if path == "/api/scripts/user/update":
                moved = set((body["data"].get("Info") or {})) & set(masuser.MOVED)
                if self.beta3 and moved:
                    # beta.3's backend has no Info.Annihilation item any more and refuses it.
                    return _Resp({"code": 500, "status": "error", "message": f"未知配置项 Info.{sorted(moved)[0]}"})
                merge(self.users[body["scriptId"]][body["userId"]], body["data"])
                return _Resp({"code": 200})
            if path == "/api/setting/update":
                merge(self.setting, body["data"])
                return _Resp({"code": 200})
            raise AssertionError(f"endpoint not prepared by this test: {path}")

        def updates(self):
            return [p for p, _ in self.calls if p.endswith("/update")]

    class _Resp:
        def __init__(self, obj):
            self._raw = json.dumps(obj, ensure_ascii=False).encode()

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    _real = urllib.request.urlopen

    def run(be, *argv):
        urllib.request.urlopen = be.urlopen
        out = io.StringIO()
        old, sys.stdout = sys.stdout, out
        try:
            code = H.main(list(argv))
        finally:
            sys.stdout = old
        return code, out.getvalue()

    try:
        with nullcontext(tmpdir()) as d:   # tmpdir() is a plain Path, removed at exit
            state = Path(d) / "state"
            state.mkdir()
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W40", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]

            print("plan reads only (the relay closed it last week; the week has rolled)")
            be = Backend()
            code, out = run(be, "plan", *sd)
            check("plan exit 0", code, 0)
            check("plan sends no update", be.updates(), [])
            check("plan shows the annihilation map it would restore",
                  "'Close' -> 'Chernobog@Annihilation'" in out, True)
            check("plan prints the hard limit fact", "Run.HardTimeLimit = 120" in out, True)

            print("apply changes, reads back, saves the old values")
            code, out = run(be, "apply", *sd)
            check("apply exit 0", code, 0)
            check("annihilation restored to the saved map",
                  be.users[MAA][UID]["Info"]["Annihilation"], "Chernobog@Annihilation")
            check("arknights client update on", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], True)
            check("arknights apk install on", be.scripts[MAA]["Run"]["IfAutoInstallGameApk"], True)
            check("wuwa untouched without --with-wuwa-update", be.scripts[OKWW]["Game"]["Enabled"], False)
            saved = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
            check("old annihilation value saved", saved.get("user:MAA:Info.Annihilation"), "Close")
            check("old update switch saved", saved.get("script:MAA:Run.IfCheckGameUpdate"), False)

            print("apply again is a no-op and keeps the first old values")
            n = len(be.updates())
            code, _ = run(be, "apply", *sd)
            check("second apply exit 0", code, 0)
            check("second apply sends no update", len(be.updates()), n)
            saved2 = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
            check("backup still holds the pre-handover values", saved2, saved)

            print("rollback puts exactly the old values back")
            code, out = run(be, "rollback", "--state-dir", str(state))
            check("rollback exit 0", code, 0)
            check("annihilation back to Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("update switch back off", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], False)
            check("backup removed after a full rollback", (state / H.BACKUP_FILE).exists(), False)

        print("the moved keys are the same here as in the relay (this file cannot import it)")
        check("MOVED equals ark_relay.core.masuser.MOVED", getattr(H, "MOVED", None), masuser.MOVED)

        with nullcontext(tmpdir()) as d:   # tmpdir() is a plain Path, removed at exit
            state = Path(d)
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W40", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]

            print("AUTO-MAS v5.7.0-beta.3 (annihilation under Task): apply and rollback use Task")
            be = Backend(beta3=True)
            code, out = run(be, "plan", *sd)
            check("plan reads the Close from Task", "'Close' -> 'Chernobog@Annihilation'" in out, True)
            check("plan reads the start weekday from Task", "Info.AnnihilationStartWeekday = 'Monday'" in out, True)
            code, out = run(be, "apply", *sd)
            check("apply exit 0", code, 0)
            check("annihilation restored in Task", be.users[MAA][UID]["Task"]["Annihilation"], "Chernobog@Annihilation")
            check("no Info.Annihilation written back", "Annihilation" in be.users[MAA][UID]["Info"], False)
            saved = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
            check("backup keeps the old key", saved.get("user:MAA:Info.Annihilation"), "Close")
            code, out = run(be, "rollback", "--state-dir", str(state))
            check("rollback exit 0", code, 0)
            check("rollback puts Close back in Task", be.users[MAA][UID]["Task"]["Annihilation"], "Close")

        with nullcontext(tmpdir()) as d:   # tmpdir() is a plain Path, removed at exit
            state = Path(d)
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]

            print("a Close the relay never set (no done_week) stays Close")
            be = Backend()
            code, out = run(be, "apply", *sd)
            check("exit 0", code, 0)
            check("annihilation left Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("no write to annihilation", [b for p, b in be.calls if p == "/api/scripts/user/update"], [])
            check("says why", "no done_week" in out, True)

            print("done_week without a saved map: AUTO-MAS's own default, as the old relay did")
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W40"}}}), encoding="utf-8")
            be = Backend()
            code, _ = run(be, "apply", *sd)
            check("restored to the default map", be.users[MAA][UID]["Info"]["Annihilation"], "Annihilation")

            print("done this week, AUTO-MAS has no record of it: hand the record over, then open")
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W41", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")
            be = Backend()
            be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"] = "2026-W40"
            code, out = run(be, "plan", *sd)
            check("plan exit 0", code, 0)
            check("plan sends no update", be.updates(), [])
            check("plan shows the record it would write", "'2026-W40' -> '2026-W41'" in out, True)
            check("plan shows the map it would then restore", "'Close' -> 'Chernobog@Annihilation'" in out, True)
            code, out = run(be, "apply", *sd)
            check("apply exit 0", code, 0)
            check("AUTO-MAS now knows this week is done",
                  be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"], "2026-W41")
            check("annihilation restored", be.users[MAA][UID]["Info"]["Annihilation"], "Chernobog@Annihilation")
            writes = [b["data"] for p, b in be.calls if p == "/api/scripts/user/update"]
            check("the record is written before the switch opens",
                  writes[:2], [{"Data": {"AnnihilationCompletedWeek": "2026-W41"}},
                               {"Info": {"Annihilation": "Chernobog@Annihilation"}}])
            code, _ = run(be, "rollback", "--state-dir", str(state))
            check("rollback puts the old record back", be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"], "2026-W40")
            check("rollback closes it again", be.users[MAA][UID]["Info"]["Annihilation"], "Close")

            print("done this week but the record write is refused: the switch stays Close")
            be = Backend(mode="running")
            be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"] = "2026-W40"
            code, out = run(be, "apply", *sd)
            check("exit 1", code, 1)
            check("annihilation left Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("says it needs the record", "Data.AnnihilationCompletedWeek='2026-W41'" in out, True)
            (state / "state.json").unlink()

            print("quick config off: annihilation is not handed over")
            be = Backend(quick=False)
            code, out = run(be, "apply", *sd)
            check("exit 1", code, 1)
            check("annihilation left Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("says why", "Info.IfQuickConfig" in out, True)

            print("not the official server: client update not handed over")
            be = Backend(server="Bilibili")
            code, out = run(be, "apply", *sd)
            check("exit 1", code, 1)
            check("update switch left off", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], False)

            print("a task running: the backend refuses, nothing reported as done")
            be = Backend(mode="running")
            code, out = run(be, "apply", *sd)
            check("exit 1", code, 1)
            check("refusal reported", "正在运行" in out, True)

            print("backend down")
            be = Backend(mode="down")
            code, out = run(be, "apply", *sd)
            check("exit 2", code, 2)

            print("self start off is switched on")
            be = Backend(selfstart=False)
            code, _ = run(be, "apply", *sd)
            check("IfSelfStart true", be.setting["Start"]["IfSelfStart"], True)

            print("--with-wuwa-update without a launcher: refuses, does not enable")
            be = Backend()
            code, out = run(be, "apply", "--with-wuwa-update", *sd)
            check("exit 1", code, 1)
            check("Game.Enabled still off", be.scripts[OKWW]["Game"]["Enabled"], False)
            check("says the launcher was not found", "launcher.exe not found" in out, True)

            print("--with-wuwa-update with the launcher next to the game folder")
            game = Path(d) / "Wuthering Waves Game" / "Wuthering Waves.exe"
            game.parent.mkdir()
            game.write_text("")
            launcher = Path(d) / "Wuthering Waves" / "launcher.exe"
            launcher.parent.mkdir()
            launcher.write_text("")
            cfg = Path(d) / "okww" / "data" / "apps" / "ok-ww" / "working" / "configs"
            cfg.mkdir(parents=True)
            (cfg / "Game.json").write_text(json.dumps({"path": str(game)}), encoding="utf-8")
            be = Backend()
            code, out = run(be, "plan", "--with-wuwa-update", *sd)
            check("plan with wuwa exit 0", code, 0)
            check("plan with wuwa sends no update", be.updates(), [])
            check("plan shows the three wuwa lines", out.count("[10b]"), 3)
            code, out = run(be, "apply", "--with-wuwa-update", *sd)
            check("exit 0", code, 0)
            check("launcher path set", be.scripts[OKWW]["Game"]["Path"], str(launcher))
            check("game start handed over", be.scripts[OKWW]["Game"]["Enabled"], True)

        with nullcontext(tmpdir()) as d:
            state = Path(d)
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W40", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")

            print("the relay closed it once but the switch is open now: left as it is")
            be = Backend(annihilation="Annihilation")
            code, _ = run(be, "apply", *sd)
            check("exit 0", code, 0)
            check("annihilation untouched", be.users[MAA][UID]["Info"]["Annihilation"], "Annihilation")
            (state / H.BACKUP_FILE).unlink(missing_ok=True)

            print("--only 13: annihilation only, the other AUTO-MAS settings neither read nor changed")
            be = Backend(selfstart=False)
            code, out = run(be, "plan", "--only", "13", *sd)
            check("plan exit 0", code, 0)
            check("plan prints only step 13", sorted({l.split("]")[0] for l in out.splitlines() if l.startswith("[")}),
                  ["[13"])
            code, out = run(be, "apply", "--only", "13", *sd)
            check("apply exit 0", code, 0)
            check("annihilation restored", be.users[MAA][UID]["Info"]["Annihilation"], "Chernobog@Annihilation")
            check("arknights update switch untouched", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], False)
            check("self start untouched", be.setting["Start"]["IfSelfStart"], False)
            check("setting never read", [p for p, _ in be.calls if p.startswith("/api/setting/")], [])
            (state / H.BACKUP_FILE).unlink(missing_ok=True)

            print("--only 10a --only 20: those two, annihilation left Close")
            be = Backend(selfstart=False)
            code, _ = run(be, "apply", "--only", "10a", "--only", "20", *sd)
            check("exit 0", code, 0)
            check("annihilation left Close", be.users[MAA][UID]["Info"]["Annihilation"], "Close")
            check("arknights update switch on", be.scripts[MAA]["Run"]["IfCheckGameUpdate"], True)
            check("self start on", be.setting["Start"]["IfSelfStart"], True)

            print("--only with an unknown step is refused, nothing done")
            be = Backend()
            err, sys.stderr = sys.stderr, io.StringIO()
            try:
                run(be, "apply", "--only", "99", *sd)
                code = 0
            except SystemExit as exc:
                code = exc.code
            finally:
                sys.stderr = err
            check("argparse exit 2", code, 2)
            check("no call made", be.calls, [])
        with nullcontext(tmpdir()) as d:   # tmpdir() is a plain Path, removed at exit
            state = Path(d)
            sd = ["--state-dir", str(state), "--okww-dir", str(Path(d) / "okww")]
            print("uninstall with the old relay gone: 13, 10a, 10b stay with AUTO-MAS, the rest goes back")
            (state / "state.json").write_text(json.dumps(
                {"weekly": {"annihilation": {"done_week": "2026-W41", "restore_to": "Chernobog@Annihilation"}}}),
                encoding="utf-8")
            launcher = Path(d) / "Wuthering Waves" / "launcher.exe"
            real_launcher, H.wuwa_launcher = H.wuwa_launcher, lambda okww_dir: launcher
            try:
                be = Backend(selfstart=False)
                be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"] = "2026-W40"
                be.scripts[OKWW]["Game"]["IfAutoUpdate"] = False
                code, _ = run(be, "apply", "--with-wuwa-update", *sd)
                check("apply exit 0", code, 0)
                saved = json.loads((state / H.BACKUP_FILE).read_text(encoding="utf-8"))["old"]
                handed = {st["target"].key for st in H.steps(state, Path(d), True) if st["id"] in ("13", "10a", "10b")}
                check("every 13 / 10a / 10b setting the handover changes is kept with AUTO-MAS",
                      sorted(handed - set(getattr(H, "KEPT_WITHOUT_OLD_RELAY", ()))), [])
                check("the backup holds all of them and 20", sorted(saved), sorted(handed | {"setting::Start.IfSelfStart"}))
                try:
                    code, out = run(be, "rollback", "--old-relay-gone", "--state-dir", str(state))
                except SystemExit as exc:      # the old argparse: no such option
                    code, out = exc.code, ""
                check("rollback exit 0", code, 0)
                check("annihilation stays open", be.users[MAA][UID]["Info"]["Annihilation"], "Chernobog@Annihilation")
                check("this week's record stays", be.users[MAA][UID]["Data"]["AnnihilationCompletedWeek"], "2026-W41")
                check("arknights client update stays on",
                      (be.scripts[MAA]["Run"]["IfCheckGameUpdate"], be.scripts[MAA]["Run"]["IfAutoInstallGameApk"]),
                      (True, True))
                check("wuwa update stays on", be.scripts[OKWW]["Game"],
                      {"Enabled": True, "Path": str(launcher), "IfAutoUpdate": True})
                check("20 (not the old relay's job) is put back", be.setting["Start"]["IfSelfStart"], False)
                check("says what it left", out.count("left with AUTO-MAS"), 7)
                check("backup removed", (state / H.BACKUP_FILE).exists(), False)
            finally:
                H.wuwa_launcher = real_launcher
    finally:
        urllib.request.urlopen = _real


def _part_automas_jobfix():
    """AUTO-MAS's job-object fallback is put back in its venv at boot and after an AUTO-MAS update (11-09).
    """
    import ast
    import hashlib
    import logging
    import os
    import types
    from unittest import mock

    import boot_stages
    from ark_relay.features import automas_keeper as jf

    print("[the payload: the two files session 2499 tried on the machine, byte for byte]")
    check("module unchanged", hashlib.sha256(jf.payload("zz_automas_job_fix.py")).hexdigest(),
          "979bea5fe532c281e6a843018fc48dd14b8a79e9ff3423beb0094f27d623a7b2")
    check(".pth imports the module", jf.payload("zz_automas_job_fix.pth"), b"import zz_automas_job_fix\n")
    tree = ast.parse(jf.payload("zz_automas_job_fix.py").decode("utf-8"))
    check("the module is Python and imports only sys at its top",
          [n.names[0].name for n in tree.body if isinstance(n, ast.Import)], ["sys"])
    # site.addsitedir reads .pth files in sorted order: after pywin32.pth, so win32job imports.
    check(".pth sorts after pywin32.pth and _virtualenv.pth",
          sorted(["_virtualenv.pth", "pywin32.pth", "zz_automas_job_fix.pth"])[-1], "zz_automas_job_fix.pth")

    print("\n[heal: no AUTO-MAS, or no venv in it -> nothing written]")
    check("no AUTO-MAS folder", (jf.site_dir(None), jf.heal(None)), (None, []))
    bare = tmpdir()
    check("AUTO-MAS without the venv", (jf.site_dir(bare), jf.heal(bare)), (None, []))

    print("\n[heal: missing -> all put back; right -> untouched; one changed -> that one]")
    root = tmpdir()
    site = root.joinpath(*jf.SITE_PACKAGES)
    site.mkdir(parents=True)
    check("all missing: all written", jf.heal(root),
          ["zz_automas_job_fix.py", "zz_automas_job_fix.pth", "zz_automas_ld_adb.py", "zz_automas_ld_adb.pth"])
    check("……byte for byte", [(site / n).read_bytes() == jf.payload(n) for n in jf.FILES], [True] * 4)
    os.utime(site / "zz_automas_job_fix.py", (1_000_000, 1_000_000))
    check("already right: nothing written", jf.heal(root), [])
    check("……mtime not touched", (site / "zz_automas_job_fix.py").stat().st_mtime, 1_000_000)
    (site / "zz_automas_job_fix.pth").write_bytes(b"import something_else\n")
    check("the .pth changed: only it is put back", jf.heal(root), ["zz_automas_job_fix.pth"])
    check("……and reads right", (site / "zz_automas_job_fix.pth").read_bytes(), jf.payload("zz_automas_job_fix.pth"))
    (site / "zz_automas_job_fix.py").unlink()
    with mock.patch.object(jf, "atomic_write_bytes", lambda path, data: path.write_bytes(data[:-1])):
        try:
            jf.heal(root)
            raised = None
        except OSError as exc:
            raised = str(exc)
    check("a read-back that differs raises", bool(raised) and "读回来不一样" in raised, True)

    print("\n[the boot stage says it: put back is INFO, not placed is a WARNING (the group)]")
    lines: list[tuple[int, str]] = []
    lg = logging.getLogger("ark.test_preupdate")
    lg.propagate = False
    lg.setLevel(logging.INFO)
    h = type("H", (logging.Handler,), {"emit": lambda self, r: lines.append((r.levelno, r.getMessage()))})()
    lg.addHandler(h)
    try:
        (site / "zz_automas_job_fix.py").unlink(missing_ok=True)
        boot_stages._stage_automas_jobfix(types.SimpleNamespace(automas_dir=root), lg)
        check("put back: one INFO naming it", [(lv, "补回去了" in m and "zz_automas_job_fix.py" in m) for lv, m in lines],
              [(logging.INFO, True)])
        lines.clear()
        boot_stages._stage_automas_jobfix(types.SimpleNamespace(automas_dir=root), lg)
        check("already right: silent", lines, [])
        boot_stages._stage_automas_jobfix(types.SimpleNamespace(automas_dir=None), lg)
        boot_stages._stage_automas_jobfix(types.SimpleNamespace(), lg)
        check("no AUTO-MAS in the config: silent", lines, [])
        boot_stages._stage_automas_jobfix(types.SimpleNamespace(automas_dir=bare), lg)
        check("no venv: one INFO", [(lv, "没地方放" in m) for lv, m in lines], [(logging.INFO, True)])
        lines.clear()
        (site / "zz_automas_job_fix.py").unlink()
        with mock.patch.object(jf, "atomic_write_bytes", mock.Mock(side_effect=PermissionError(13, "denied"))):
            boot_stages._stage_automas_jobfix(types.SimpleNamespace(automas_dir=root), lg)
        check("a write refused: one WARNING saying what it risks",
              [(lv, "没能放好" in m and "拒绝访问" in m) for lv, m in lines], [(logging.WARNING, True)])
        lines.clear()

        print("\n[after the pre-update installs a new AUTO-MAS: put back too]")
        from ark_relay.features import selfcheck
        cfg = types.SimpleNamespace(automas_dir=root)
        with mock.patch.object(selfcheck, "report_contract", lambda *a: None), \
                mock.patch.object(boot_stages, "_endfield_launch", lambda *a: None):
            boot_stages._contract_after_update(cfg, None, lg, "v5.2.0")
        check("the file is back", (site / "zz_automas_job_fix.py").read_bytes() == jf.payload("zz_automas_job_fix.py"), True)
        check("……said with the version", [("调度程序升级到 v5.2.0 后" in m) for _, m in lines], [True])
    finally:
        lg.removeHandler(h)


def _part_automas_ld_adb():
    """AUTO-MAS hands MAA the LDPlayer instance's own ADB address, not another port its VM listens on (11-09).
    """
    import ast
    import dataclasses
    import subprocess

    from ark_relay.features import automas_keeper as jf

    print("[the payload: a module, and a .pth that imports it after pywin32.pth]")
    src = jf.payload("zz_automas_ld_adb.py").decode("utf-8")
    check(".pth imports the module", jf.payload("zz_automas_ld_adb.pth"), b"import zz_automas_ld_adb\n")
    tree = ast.parse(src)
    check("the module imports only sys at its top",
          [n.names[0].name for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)], ["sys"])
    check(".pth sorts after pywin32.pth",
          sorted(["_virtualenv.pth", "pywin32.pth", "zz_automas_ld_adb.pth"])[-1], "zz_automas_ld_adb.pth")

    print("\n[fix: only a 127.0.0.1 port that is not the instance's own changes]")
    ns: dict = {}
    exec(compile(src.split("\nclass _Hook")[0], "zz_automas_ld_adb.py", "exec"), ns)
    fix = ns["fix"]
    check("11-09 09:04 port for instance 1000", fix("1000", "127.0.0.1:12508"), "emulator-7554")
    check("11-09 09:01 port", fix("1000", "127.0.0.1:11159"), "emulator-7554")
    check("its own port 7555 stays (11-08 21:54 connected on it)", fix("1000", "127.0.0.1:7555"), "127.0.0.1:7555")
    check("emulator-7554 stays (11-09 09:03 connected on it)", fix("1000", "emulator-7554"), "emulator-7554")
    check("instance 0's own 5555 stays", fix("0", "127.0.0.1:5555"), "127.0.0.1:5555")
    check("instance 0 on another port", fix("0", "127.0.0.1:16384"), "emulator-5554")
    check("an empty address stays", fix("1000", ""), "")

    @dataclasses.dataclass
    class Info:          # the shape of AUTO-MAS's app/models/emulator.py DeviceInfo (a dataclass, 11-09)
        title: str
        status: int
        adb_address: str
        app_launch: str = ""
    old = Info("t", 0, "127.0.0.1:12508", "launched")
    new = ns["_with_address"](old, "emulator-7554")
    check("a dataclass is copied with the new address, the rest kept",
          (new.adb_address, new.app_launch, old.adb_address), ("emulator-7554", "launched", "127.0.0.1:12508"))

    print("\n[loaded the way AUTO-MAS loads it: the .pth patches LDManager.getInfo when ldplayer is imported]")
    root = tmpdir()
    site = root / "site"
    site.mkdir()
    for name in ("zz_automas_ld_adb.py", "zz_automas_ld_adb.pth"):
        (site / name).write_bytes(jf.payload(name))
    pkg = root / "proj" / "app" / "utils" / "common" / "emulator"
    pkg.mkdir(parents=True)
    for d in (root / "proj" / "app", root / "proj" / "app" / "utils" / "common", pkg):
        (d / "__init__.py").write_text("")
    (root / "proj" / "app" / "utils" / "__init__.py").write_text(
        "import logging\ndef get_logger(n):\n    return logging.getLogger(n)\n")
    (pkg / "ldplayer.py").write_text(
        "import dataclasses\n"
        "@dataclasses.dataclass\n"
        "class DeviceInfo:\n    title: str\n    status: int\n    adb_address: str\n"
        "class LDManager:\n"
        "    def __init__(self, port):\n        self.port = port\n"
        "    async def getInfo(self, idx):\n"
        "        ids = [idx] if idx is not None else ['1000', '0']\n"
        "        return {i: DeviceInfo('t', 1, f'127.0.0.1:{self.port}' if self.port else f'emulator-{5554 + int(i) * 2}')"
        " for i in ids}\n"
        "class LDPlayer14Manager(LDManager):\n"
        "    async def getInfo(self, idx):\n        return await super().getInfo(idx)\n")
    drive = (
        "import asyncio, site, sys\n"
        "site.addsitedir(sys.argv[1]); sys.path.insert(0, sys.argv[2])\n"
        "from app.utils.common.emulator import ldplayer as m\n"
        "async def go():\n"
        "    out = [m.LDManager._automas_ld_adb_fix]\n"
        "    for port in (12508, 7555, 0):\n"
        "        out.append((await m.LDManager(port).getInfo('1000'))['1000'].adb_address)\n"
        "    out.append({k: v.adb_address for k, v in (await m.LDManager(5555).getInfo(None)).items()})\n"
        "    out.append((await m.LDPlayer14Manager(14245).getInfo('1000'))['1000'].adb_address)\n"
        "    print(repr(out))\n"
        "asyncio.run(go())\n")
    r = subprocess.run([sys.executable, "-I", "-c", drive, str(site), str(root / "proj")],
                       capture_output=True, text=True, timeout=60)
    check("patched, the stray ports rewritten, the right ones kept, the LDPlayer 14 subclass too",
          r.stdout.strip(), repr([True, "emulator-7554", "127.0.0.1:7555", "emulator-7554",
                                  {"1000": "emulator-7554", "0": "127.0.0.1:5555"}, "emulator-7554"]))
    check("……nothing on stderr", r.stderr, "")


def _part_mas_address():
    """AUTO-MAS 的地址只有一处出处，而且 ARK_MAS_PORT 真的管得住全部。"""
    import ast
    import os
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    print("[地址只有一处出处]")
    hard = []
    for p in sorted([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks", "machinechecks.py"} & set(p.parts)]):
        if p.name == "config.py":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if re.search(r"127\.0\.0\.1:\s*\{?36163|:36163", line):
                hard.append(f"{p.name}:{i}")
    check("别处不许再写死", hard, [])

    print("[出处是函数，不是模块级常量]")
    cfg = ast.parse((ROOT / "ark_relay" / "core" / "config.py").read_text(encoding="utf-8"))
    names = {n.name for n in cfg.body if isinstance(n, ast.FunctionDef)}
    check("config.mas_base 存在且是函数", "mas_base" in names, True)
    consts = [t.id for n in cfg.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name)]
    check("没有模块级的地址常量", [c for c in consts if "MAS" in c.upper()], [])

    print("[ARK_MAS_PORT 真的管用]")
    from ark_relay.core.config import mas_base
    old = os.environ.get("ARK_MAS_PORT")
    try:
        os.environ["ARK_MAS_PORT"] = "39999"
        check("改端口立刻生效", mas_base(), "http://127.0.0.1:39999")
        del os.environ["ARK_MAS_PORT"]
        check("不设时回落到 36163", mas_base(), "http://127.0.0.1:36163")
    finally:
        if old is None:
            os.environ.pop("ARK_MAS_PORT", None)
        else:
            os.environ["ARK_MAS_PORT"] = old


def _part_mas_api_silent():
    """mas-api.py must exit non-zero when AUTO-MAS answered with an HTTP error."""
    import contextlib
    import importlib.util
    import io

    ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("mas_api", ROOT / "scripts" / "mac" / "mas-api.py")
    mas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mas)

    def run(answer):
        mas.call = lambda path, body=None, method="POST": answer
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = mas.main(["post", "/api/scripts/get"])
        return rc, out.getvalue()

    print("[HTTP error with a JSON body]")
    rc, out = run({"__status": 422, "__detail": {"detail": "field required"}})
    check("the detail is printed", "field required" in out, True)
    check("exit 1", rc, 1)

    print("[HTTP error with a non-JSON body]")
    rc, out = run({"__status": 500, "__body": "Internal Server Error"})
    check("the body is printed", "Internal Server Error" in out, True)
    check("exit 1 (non-JSON body)", rc, 1)

    print("[normal answers stay 0]")
    check("a dict answer exits 0", run({"code": 200, "data": {}})[0], 0)
    check("a list answer exits 0", run([{"a": 1}])[0], 0)


def _part_mas_labels():
    """AUTO-MAS field labels: every labelled ConfigItem is read (audit 11 #4, 2026-10-13)."""

    from ark_relay.features import phone as mas_labels

    # Kept as .txt so the repo's Python tools (ruff, the comment ratchet) do not read
    # upstream code as ours; laid out as AUTO-MAS's app/models for the run.
    SRC = fx_dir(Path(__file__), "fixtures") / "automas-models" / "config.py.txt"
    AM = tmpdir()
    (AM / "app" / "models").mkdir(parents=True)
    (AM / "app" / "models" / "config.py").write_bytes(SRC.read_bytes())
    out = mas_labels._mas_labels(AM)

    def label(game, path):
        return (out[game].get(path) or {}).get("label")

    print("[the AUTO-MAS source audit 11 ran on]")
    check("MAA Info.MedicineNumb (one-line ConfigItem before it)", label("MAA", "Info.MedicineNumb"), "理智药数量")
    check("MAA Task.IfFight (one-line ConfigItem)", label("MAA", "Task.IfFight"), "是否理智作战")
    check("MAA Task.IfStartUp keeps its own label (not swallowed)", label("MAA", "Task.IfStartUp"), "是否自动唤醒")
    check("MAA Info.Notes (one line) keeps its own label", label("MAA", "Info.Notes"), "备注")
    check("MaaEnd Task.SanityTaskType (config. in init_maaend_task_config)",
          label("MaaEnd", "Task.SanityTaskType"), "理智任务类型")
    check("MaaEnd Task.AutoEssenceSpecifiedLocation", label("MaaEnd", "Task.AutoEssenceSpecifiedLocation"), "基质刷取地点")
    check("multi-line items still read: MAA Info.Annihilation options",
          (label("MAA", "Info.Annihilation"), (out["MAA"].get("Info.Annihilation") or {}).get("options", [])[:2]),
          ("剿灭模式", ["Close", "Annihilation"]))
    check("OK-WW Task.WhichToFarm", label("OK-WW", "Task.WhichToFarm"), "每日任务体力用途")
    shown = sorted(f"{g}|{p}" for g in out for p in mas_labels.SHOWN if p in out[g])
    check("SHOWN fields labelled: 16 of 19 (TaskIndex, IfSanity, IfAutoUseSpMedication have none)", len(shown), 16)
    # No label may land on a field other than its own: each `##` line is the line
    # right above its ConfigItem in the source.
    src = SRC.read_text(encoding="utf-8")
    wrong = [f"{g}|{p}" for g, items in out.items() for p, info in items.items()
             if f'## {info["label"]}\n' not in src]
    check("every label is a `## ` line of the source", wrong, [])

    print("\n[a wrapped one-line call and a comment with a parenthesis]")
    d = tmpdir()
    (d / "app" / "models").mkdir(parents=True)
    (d / "app" / "models" / "config.py").write_text('''
def init_x(config) -> None:
    ## 甲
    config.Task_A = ConfigItem("Task", "A", 0)  # a (comment
    ## 乙
    config.Task_B = ConfigItem(
        "Task",
        "B",
        "x)",  # a ) in a string and a comment
        OptionsValidator(["p", "q"]),
    )


class MaaEndUserConfig(ConfigBase):
    def __init__(self):
        ## 丙
        self.Info_C = ConfigItem("Info", "C", f(1, 2))
        ## 丁
        self.Info_D = ConfigItem("Info", "D", 1)
        init_x(self)
''', encoding="utf-8")
    got = mas_labels._mas_labels(d)["MaaEnd"]
    check("labels", {k: v["label"] for k, v in got.items()},
          {"Info.C": "丙", "Info.D": "丁", "Task.A": "甲", "Task.B": "乙"})
    check("options inside a wrapped call", got.get("Task.B", {}).get("options"), ["p", "q"])


def _part_mas_user_pick():
    """The phone's changes, its snapshot and the plan look at one and the same AUTO-MAS user
(audit 11-08 D-11; dispatch relay-opt-round6-1108 R6-01; masuser.pick).
    """
    import json

    from ark_relay.core import mastercfg as masuser, plan
    from ark_relay.features import commands, snapshot


    def user(stage, **info):
        return {"Info": {"Name": stage, "Stage": stage, "Stage_1": "-", "Stage_2": "-", "Stage_3": "-",
                         "StageMode": "Fixed", "MedicineNumb": 0, **info}, "Task": {"IfFight": True}}


    def world(first_info=None, second_info=None):
        users = {"instances": [{"uid": "U1"}, {"uid": "U2"}],
                 "U1": user("1-7", **(first_info or {})), "U2": user("CE-6", **(second_info or {}))}
        d = tmpdir()
        (d / "config").mkdir()
        (d / "config" / "ScriptConfig.json").write_text(json.dumps(
            {"instances": [{"uid": "S"}], "S": {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"},
                                                "SubConfigsInfo": {"UserData": users}}}, ensure_ascii=False),
            encoding="utf-8")
        return d, users


    def answers(d, users):
        """(phone change goes to, phone shows from the backend, phone shows from the file, plan shows)."""
        def mas(path, body=None, timeout=15):
            if path == "/api/scripts/get":
                return {"data": {"S": {"Info": {"Name": "MAA"}}}}
            if path == "/api/scripts/user/get":
                return {"data": users}
            raise AssertionError(path)
        saved = (commands._mas, snapshot._post)
        commands._mas = mas
        snapshot._post = lambda path, body=None, timeout=15: mas(path, body)
        try:
            uid = commands._find_user("MAA")[1]
            out = {}
            snapshot._mas(out)
            shown = (out.get("MAA") or {}).get("关卡")
        finally:
            commands._mas, snapshot._post = saved
        files = snapshot.maa_from_files(d)["关卡"]
        planned = next(iter(plan._scripts(d / "config").values())).get("stage_info", {}).get("Stage")
        return users[uid]["Info"]["Stage"], shown, files, planned


    print("[两个账号都会跑：都看第一个]")
    check("改的、显示的（后台）、显示的（文件）、安排里的", answers(*world()), ("1-7",) * 4)

    print("\n[第一个停用（Status 关）：都看第二个]")
    check("同一个账号", answers(*world(first_info={"Status": False})), ("CE-6",) * 4)

    print("\n[第一个剩余天数 0：都看第二个]")
    check("同一个账号", answers(*world(first_info={"RemainedDay": 0})), ("CE-6",) * 4)

    print("\n[两个都不跑：退回第一个]")
    check("同一个账号", answers(*world(first_info={"Status": False}, second_info={"Status": False})), ("1-7",) * 4)

    print("\n[pick 本身]")
    check("没有用户", masuser.pick({}), None)
    check("只有 instances 列表", masuser.pick({"instances": [{"uid": "U1"}]}), None)
    check("后台的回答里先列 instances 也跳过", masuser.pick({"instances": [], "U9": {"Info": {}}})[0], "U9")


def _part_masconfig_yaml():
    """AUTO-MAS v5.8's YAML settings read like v5.7's JSON (core/masconfig.py, core/miniyaml.py).
    """
    import json

    from ark_relay.core import mastercfg as masconfig, mastercfg as miniyaml, plan

    print("[miniyaml: the constructs AUTO-MAS's files use]")
    doc = miniyaml.loads("""\
order:
- uid: aaa
  type: QueueConfig
- uid: bbb
  type: QueueConfig
data:
  aaa:
    Info:
      Name: 早班
      TimeEnabled: true
      Delay: 0
      Ratio: 1.5
      ScriptAfterTask: null
      Note: ~
    Pipeline: '{"Data": {"Week": "2026-W42",
      "Notes": "it''s", "Tag": "[{\\"text\\": \\"日常\\"}]"},
      "Run": 2}'
    Quoted: "a\\tb \\u4e2d
      c"
    Long: a plain line
      that folds
    Empty: {}
    None: []
    '2026-10-22': date key
""")
    check("an indentless sequence under its key", [x["uid"] for x in doc["order"]], ["aaa", "bbb"])
    info = doc["data"]["aaa"]["Info"]
    check("true / int / float / null / ~", (info["TimeEnabled"], info["Delay"], info["Ratio"],
                                            info["ScriptAfterTask"], info["Note"]), (True, 0, 1.5, None, None))
    check("a single-quoted string folded over three lines, '' kept as one quote",
          json.loads(doc["data"]["aaa"]["Pipeline"]), {"Data": {"Week": "2026-W42", "Notes": "it's",
                                                                "Tag": '[{"text": "日常"}]'}, "Run": 2})
    check("a double-quoted string: escapes and folding", doc["data"]["aaa"]["Quoted"], "a\tb 中 c")
    check("a plain scalar folded over lines", doc["data"]["aaa"]["Long"], "a plain line that folds")
    check("{} and []", (doc["data"]["aaa"]["Empty"], doc["data"]["aaa"]["None"]), ({}, []))
    check("a quoted key stays a string", doc["data"]["aaa"]["2026-10-22"], "date key")
    for bad in ("a: [1, 2]\n", "a: |\n  text\n", "a: &x 1\n", "a: !!str 1\n"):
        try:
            miniyaml.loads(bad)
            check(f"refuses {bad.strip()!r}", "parsed", "ValueError")
        except ValueError:
            check(f"refuses {bad.strip()!r}", True)

    print("\n[masconfig: v5.8's layout read in v5.7's shape]")
    QUEUES = """\
order:
- uid: q1
  type: QueueConfig
data:
  q1:
    Data:
      LastTimedStart: '2026-10-22T01:00:00Z'
    Info:
      Name: 早班
      TimeEnabled: true
      StartUpMode: Never
      AfterAccomplish: NoAction
    TimeSet:
      order:
      - uid: t1
        type: TimeSet
      data:
        t1:
          Info:
            Days:
            - Monday
            - Tuesday
            - Wednesday
            - Thursday
            - Friday
            - Saturday
            - Sunday
            Enabled: true
            Time: '2000-01-01T01:00:00Z'
    QueueItem:
      order:
      - uid: i1
        type: QueueItem
      data:
        i1:
          Info:
            ScriptId: s1
          Schedule:
            Days:
            - Monday
            - Tuesday
            - Wednesday
            - Thursday
            - Friday
            - Saturday
            - Sunday
            Enabled: true
            Mode: fixed_time
            Time: '1999-12-31T16:00:00Z'
"""
    old = masconfig.legacy(miniyaml.loads(QUEUES))
    check("order -> instances", old["instances"], [{"uid": "q1", "type": "QueueConfig"}])
    check("sub-collections go under SubConfigsInfo", sorted(old["q1"]["SubConfigsInfo"]), ["QueueItem", "TimeSet"])
    ts = old["q1"]["SubConfigsInfo"]["TimeSet"]["t1"]["Info"]
    check("09:00 Beijing written as 2000-01-01T01:00:00Z reads back as 09:00 (v5.7's form)", ts["Time"], "09:00")
    check("LastTimedStart in v5.7's form", old["q1"]["Data"]["LastTimedStart"], "2026-10-22 09:00")
    check("a queue item's time too",
          old["q1"]["SubConfigsInfo"]["QueueItem"]["i1"]["Schedule"]["Time"], "00:00")

    print("\n[the reader finds the YAML only when the JSON is gone]")
    root = tmpdir()
    cfg = root / "config"
    cfg.mkdir()
    (cfg / "queues.yaml").write_text(QUEUES, encoding="utf-8")
    check("no JSON: the YAML", masconfig.source(cfg / "QueueConfig.json").name, "queues.yaml")
    sched = plan.schedule(root)
    check("plan.schedule sees the 09:00 morning queue (10-23 it saw none)",
          [(q["name"], q["times"], q["items"]) for q in sched], [("早班", ["09:00"], ["s1"])])
    (cfg / "QueueConfig.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    check("JSON there (AUTO-MAS before v5.8): the JSON", masconfig.source(cfg / "QueueConfig.json").name,
          "QueueConfig.json")
    try:
        masconfig.read(cfg / "ScriptConfig.json")
        check("neither file: the error reading the JSON gives", "read", "FileNotFoundError")
    except FileNotFoundError:
        check("neither file: the error reading the JSON gives", True)

    print("\n[offline file-edit fallback on v5.8 YAML (11-08 [D-05])]")
    import os
    from ark_relay.features import commands
    from ark_relay.features import queues

    yroot = tmpdir()
    ycfg = yroot / "config"
    ycfg.mkdir()
    (ycfg / "queues.yaml").write_text(QUEUES, encoding="utf-8")
    SCRIPTS_YAML = """\
order:
- uid: s1
  type: ScriptConfig
- uid: s2
  type: ScriptConfig
data:
  s1:
    Info:
      Name: MAA
    UserData:
      order:
      - uid: u1
        type: MAAUserConfig
      data:
        u1:
          Info:
            Name: 默认用户
            Stage: CE-6
            MedicineNumb: 0
  s2:
    Info:
      Name: MaaEnd
    Game:
      WaitTime: 60
"""
    (ycfg / "scripts.yaml").write_text(SCRIPTS_YAML, encoding="utf-8")
    os.environ["ARK_AUTOMAS_DIR"] = str(yroot)
    orig_backend = commands._backend_scripts
    orig_refusal = commands._stage_refusal
    orig_q_backend = queues._enabled_via_backend
    commands._backend_scripts = lambda: (None, "")
    commands._stage_refusal = lambda s: ""
    queues._enabled_via_backend = lambda name, enabled: None
    try:
        ok_s, msg_s = commands._set_stage("1-7")
        check("YAML _set_stage ok", ok_s, True)
        check("YAML _set_stage read back", masconfig.read(ycfg / "ScriptConfig.json")["s1"]["SubConfigsInfo"]["UserData"]["u1"]["Info"]["Stage"], "1-7")
        ok_m, msg_m = commands._set_medicine(5)
        check("YAML _set_medicine ok", ok_m, True)
        check("YAML _set_medicine read back", masconfig.read(ycfg / "ScriptConfig.json")["s1"]["SubConfigsInfo"]["UserData"]["u1"]["Info"]["MedicineNumb"], 5)
        ok_w, msg_w = commands._set_wait_time(120)
        check("YAML _set_wait_time ok", ok_w, True)
        check("YAML _set_wait_time read back", masconfig.read(ycfg / "ScriptConfig.json")["s2"]["Game"]["WaitTime"], 120)
        ok_q, msg_q = queues.apply(yroot, "早班", enabled=False)
        check("YAML queues.apply ok", ok_q, True)
        check("YAML queues.apply read back", masconfig.read(ycfg / "QueueConfig.json")["q1"]["Info"]["TimeEnabled"], False)
        check("no stray JSON written next to YAML", (ycfg / "QueueConfig.json").exists() or (ycfg / "ScriptConfig.json").exists(), False)
    finally:
        commands._backend_scripts = orig_backend
        commands._stage_refusal = orig_refusal
        queues._enabled_via_backend = orig_q_backend


def _part_mascontract():
    """The relay notices at once when an AUTO-MAS update moves a setting it reads."""
    import inspect
    import json
    import os
    import types

    from _parts import stagegate_fx; fx = stagegate_fx()

    os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
    from ark_relay.core import texts
    from ark_relay.features import commands
    from ark_relay.features import preupdate as P
    from ark_relay.features import selfcheck
    try:
        from ark_relay.core import mastercfg as mascontract
    except ImportError:          # the code before this change
        mascontract = None

    def edit_user(root: Path, fn) -> Path:
        """Apply fn to the MAA user of the fixture's ScriptConfig.json."""
        f = root / "config" / "ScriptConfig.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        fn(data["S-MAA"]["SubConfigsInfo"]["UserData"]["U1"])
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return root

    def drop_stage(user):
        """A later AUTO-MAS that keeps the main stage neither in Stage nor in Info."""
        user["Stage"].pop("Stage")
        user["Info"].pop("Stage", None)

    print("[the list of AUTO-MAS settings the relay reads]")
    check("ark_relay/core/mastercfg.py exists", mascontract is not None)
    if mascontract is not None:
        items = mascontract.CONTRACT
        check("it lists the moved stage items at their new group",
              {("Stage", k) for k in ("Stage", "StageMode", "MedicineNumb")} <= {(i.group, i.key) for i in items})
        check("each item names its reader and a feature with plain words",
              [i.path for i in items if not i.source or i.use not in texts.MAS_SETTING_WHAT
               or i.use not in texts.MAS_SETTING_BREAKS], [])
        check("every script kind, the queue and the plan table are covered",
              {i.kind for i in items}, {"MAA", "MaaEnd", "OK-WW", "queue", "plan"})

    print("\n[the check on AUTO-MAS v5.7.0-beta.3's layout]")
    if mascontract is not None:
        beta3 = fx.automas_dir(tmpdir(), beta3=True)
        res = mascontract.check(beta3)
        check("beta.3 layout: nothing missing", [i.path for i in res.missing], [])
        check("beta.3 layout: the items were judged, not skipped", res.judged >= 30)
        check("beta.3 layout: no file unreadable", res.unreadable, [])

        def to_info(user):
            """The same user as an AUTO-MAS before beta.3 keeps it: the moved items in Info."""
            for k, g in mascontract.masuser.MOVED.items():
                if k in (user.get(g) or {}):
                    user["Info"][k] = user[g].pop(k)
        old = edit_user(fx.automas_dir(tmpdir(), beta3=True), to_info)
        check("the same items kept in Info (before beta.3) also pass", [i.path for i in mascontract.check(old).missing], [])

        gone = edit_user(fx.automas_dir(tmpdir(), beta3=True), drop_stage)
        res = mascontract.check(gone)
        check("a stage kept in neither Stage nor Info fails and names it",
              [(i.kind, i.path) for i in res.missing], [("MAA", "Stage.Stage")])
        lines = texts.mas_contract_lines(res.missing)
        check("the plain line says which setting and which column",
              lines, ["中继读不到方舟的关卡设置（关卡一栏里找不到），开跑前查关卡、明日安排、手机上显示和修改关卡都不对了"])
        check("that line is plain words", [p for x in lines for p in texts.plain(x)], [])

    print("\n[settings new in AUTO-MAS v5.7.0-beta.4: MaaEnd's launcher start (10-16)]")
    if mascontract is not None:
        launch = {(i.kind, i.path) for i in mascontract.CONTRACT if i.use == "maaend_launch"}
        check("MaaEnd Game.Path, Game.LaunchMode, Game.LauncherPath, Game.ControllerType are listed",
              launch, {("MaaEnd", "Game.Path"), ("MaaEnd", "Game.LaunchMode"), ("MaaEnd", "Game.LauncherPath"),
                       ("MaaEnd", "Game.ControllerType")})
        check("version order: beta.4 after beta.3, the release after its betas",
              (mascontract.version_key("v5.7.0-beta.3") < mascontract.version_key("v5.7.0-beta.4")
               < mascontract.version_key("v5.7.0") < mascontract.version_key("v5.7.1-beta.1"),
               mascontract.version_key("nonsense")), (True, None))
        b3 = fx.automas_dir(tmpdir(), beta3=True)
        new_keys = [("MaaEnd", "Game.LaunchMode"), ("MaaEnd", "Game.LauncherPath")]
        check("beta.4 installed, the two new keys absent: both named",
              [(i.kind, i.path) for i in mascontract.check(b3, "v5.7.0-beta.4").missing], new_keys)
        check("beta.3 installed: they are not judged", mascontract.check(b3, "v5.7.0-beta.3").missing, [])
        check("version unknown: not judged either", mascontract.check(b3, "").missing, [])

        def add_launch(root):
            f = root / "config" / "ScriptConfig.json"
            data = json.loads(f.read_text(encoding="utf-8"))
            data["S-END"]["Game"].update(LaunchMode="Launcher", LauncherPath="")
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return root
        check("beta.4 with them in place: nothing missing",
              mascontract.check(add_launch(fx.automas_dir(tmpdir(), beta3=True)), "v5.7.0-beta.4").missing, [])

        def drop_path(root):
            f = root / "config" / "ScriptConfig.json"
            data = json.loads(f.read_text(encoding="utf-8"))
            data["S-END"]["Game"].pop("Path")
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return root
        check("Game.Path is judged on every version",
              [(i.kind, i.path) for i in mascontract.check(drop_path(fx.automas_dir(tmpdir(), beta3=True))).missing],
              [("MaaEnd", "Game.Path")])

    print("\n[「MaaEnd 启动」's window settings, written by the relay since 10-17]")
    # efstart_setup sets Game.SetResolution / CloseOnFinish / RestoreDisplayType / RestoreResolution
    # and reads Game.ControllerType (maaend_launch.check). An AUTO-MAS that drops one must be
    # reported: listed, judged on every version (MaaEndConfig has them since v5.7.0-beta.2 at
    # least), and a missing one named in one plain line.
    if mascontract is not None:
        WINDOW_KEYS = ("SetResolution", "CloseOnFinish", "RestoreDisplayType", "RestoreResolution")
        window = [(i.kind, i.path, i.since) for i in mascontract.CONTRACT if i.use == "maaend_window"]
        check("the four window settings are listed, judged on every version",
              window, [("MaaEnd", f"Game.{k}", "") for k in WINDOW_KEYS])

        def drop_window(root):
            f = root / "config" / "ScriptConfig.json"
            data = json.loads(f.read_text(encoding="utf-8"))
            for k in (*WINDOW_KEYS, "ControllerType"):
                data["S-END"]["Game"].pop(k)
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return root
        gone = mascontract.check(drop_window(fx.automas_dir(tmpdir(), beta3=True)))
        check("an AUTO-MAS that drops them: all five named",
              sorted((i.kind, i.path) for i in gone.missing),
              sorted([("MaaEnd", f"Game.{k}") for k in (*WINDOW_KEYS, "ControllerType")]))
        lines = texts.mas_contract_lines(gone.missing)
        check("plain lines for them, one per feature", (len(lines), [p for x in lines for p in texts.plain(x)]), (2, []))
        check("the fixture as on the machine: nothing missing",
              mascontract.check(fx.automas_dir(tmpdir(), beta3=True)).missing, [])

    print("\n[the boot self-check has it as one item, routed like the others]")
    SELF_GOOD = dict(procs=lambda: [(1, r"D:\ark\automas\repo\main.py")], mas_up=lambda: True,
                     schedule=lambda: [{"name": "早班", "times": ["09:00"]}], channels=lambda: ["群"],
                     run_ok=lambda cmd: (True, ""), has_module=lambda m: True)

    class _Notifier:
        channels = ["企业微信机器人"]

        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert))
            return []

    def self_items(root):
        cfg = types.SimpleNamespace(automas_dir=str(root), state_dir=Path(root) / "state", history_dir=str(root),
                                    phone_topic="ark-x", phone_pin="1234")
        # The update settings are read from the backend; it is not asked in this test.
        orig = selfcheck._handed_updates_gaps
        orig_mas = commands._mas
        commands._mas = lambda *a, **k: {"data": {}}
        selfcheck._handed_updates_gaps = lambda scripts: []
        try:
            return selfcheck.run(cfg, **SELF_GOOD)
        finally:
            selfcheck._handed_updates_gaps, commands._mas = orig, orig_mas

    name = getattr(texts, "MAS_CONTRACT_CHECK", "中继要读的调度程序设置都在原处")
    os.environ["ARK_LOG_FILE"] = str(tmpdir() / "log" / "relay.log")
    good = [c for c in self_items(fx.automas_dir(tmpdir(), beta3=True)) if c.name == name]
    check("the self-check has the item", len(good), 1)
    check("it holds on the beta.3 layout", [c.ok for c in good], [True])
    bad = [c for c in self_items(edit_user(fx.automas_dir(tmpdir(), beta3=True), drop_stage)) if c.name == name]
    check("it fails when the stage cannot be found", [c.ok for c in bad], [False])
    check("its detail names the setting", bool(bad) and "方舟的关卡设置" in bad[0].detail)
    empty = [c for c in self_items(tmpdir()) if c.name == name]
    check("no settings folder: not judged (the queue line says it), not a second failure",
          [c.ok for c in empty], [None])

    print("\n[right after the pre-update installed a new AUTO-MAS, and only then]")
    has_hook = "after_update" in inspect.signature(P.run_automas).parameters
    check("run_automas takes an after_update hook", has_hook)

    def update_run(*, need: bool, confirmed: bool) -> list:
        """run_automas against a fake backend; the versions after_update was called with."""
        seen: list = []
        orig = (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version)

        def post(path, body=None):
            if path == "/api/update/check":
                return {"if_need_update": need, "latest_version": "v5.7.0-beta.3"}
            return {}
        P._mas_post, P._automas_version, P._live_version = post, (lambda _r: "v5.7.0-beta.2"), (lambda: "v5.7.0-beta.2")
        P._wait_for_package = lambda _root, _deadline, *_a: Path("UpdatePack_v5.7.0-beta.3.zip")
        P._wait_for_version = (lambda want, _d, *_a: want) if confirmed else (lambda want, _d, *_a: "v5.7.0-beta.2")
        try:
            kw = {"after_update": seen.append} if has_hook else {}
            P.run_automas(Path("."), budget_s=1, problems=[], **kw)
        finally:
            (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version) = orig
        return seen

    check("a new version came up: the check runs once, with it", update_run(need=True, confirmed=True), ["v5.7.0-beta.3"])
    check("no update: no check", update_run(need=False, confirmed=False), [])
    check("install not confirmed (version unchanged): no check", update_run(need=True, confirmed=False), [])
    boot = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
    check("the boot's pre-update passes the hook", "after_update=" in boot and "report_contract" in boot)

    print("\n[the post-update check pushes a miss to the group, under its own title]")
    report = getattr(selfcheck, "report_contract", None)
    check("selfcheck.report_contract exists", report is not None)
    if report is not None:
        n = _Notifier()
        cfg = types.SimpleNamespace(automas_dir=str(edit_user(fx.automas_dir(tmpdir(), beta3=True), drop_stage)))
        c = report(cfg, n, "v5.7.0-beta.3")
        check("a miss: one alarm", [(t, a) for t, _, a in n.sent], [(texts.AUTOMAS_CONTRACT, True)])
        body = n.sent[0][1] if n.sent else ""
        check("it says the version and what stops working",
              "v5.7.0-beta.3" in body and "方舟的关卡设置" in body and "开跑前查关卡" in body)
        check("the alarm is plain words", texts.plain(texts.AUTOMAS_CONTRACT + body), [])
        check("returns the failed check", c.ok, False)
        n = _Notifier()
        report(types.SimpleNamespace(automas_dir=str(fx.automas_dir(tmpdir(), beta3=True))), n, "v5.7.0-beta.3")
        check("nothing missing: nothing pushed", n.sent, [])
        n = _Notifier()
        report(types.SimpleNamespace(automas_dir=str(fx.automas_dir(tmpdir(), beta3=True))), n, "v5.7.0-beta.4")
        check("just updated to beta.4 and its launcher settings are not there: the alarm names them",
              bool(n.sent) and "终末地的游戏位置和开游戏方式" in n.sent[0][1])
        check("that alarm is plain words", texts.plain(n.sent[0][1] if n.sent else ""), [])

        class _Log:
            def __init__(self):
                self.warned = []

            def warning(self, msg, *args, **kw):
                self.warned.append(msg % args)

            def info(self, msg, *args, **kw):
                pass
        lg = _Log()
        c = report(types.SimpleNamespace(automas_dir=str(tmpdir())), _Notifier(), "v5.7.0-beta.3", lg)
        check("files unreadable after an update: not judged, and said as a WARNING (errwatch pushes it)",
              (c.ok, len(lg.warned)), (None, 1))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_masuser_beta3():
    """The relay reads and writes the MAA user's settings where AUTO-MAS keeps them."""
    import json
    import os
    from datetime import datetime

    from _parts import stagegate_fx; fx = stagegate_fx()

    os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
    from ark_relay.core import mastercfg as masuser, plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import stagegate as sg
    from ark_relay.features import snapshot, commands

    OLD = {"Info": {"Stage": "YW-4", "MedicineNumb": 3, "Annihilation": "Close"}, "Task": {}}
    NEW = {"Info": {"Name": "x"}, "Stage": {"Stage": "YW-4", "MedicineNumb": 3},
           "Task": {"Annihilation": "Close"}}

    print("[masuser]")
    for name, u in (("old (Info)", OLD), ("beta.3 (Stage / Task)", NEW)):
        check(f"{name}: Stage", masuser.get(u, "Stage"), "YW-4")
        check(f"{name}: MedicineNumb", masuser.get(u, "MedicineNumb"), 3)
        check(f"{name}: Annihilation", masuser.get(u, "Annihilation"), "Close")
        check(f"{name}: info_view has the stage", masuser.info_view(u).get("Stage"), "YW-4")
    check("old: Info.MedicineNumb stays", masuser.resolve(OLD, "Info.MedicineNumb"), "Info.MedicineNumb")
    check("beta.3: Info.MedicineNumb -> Stage.MedicineNumb", masuser.resolve(NEW, "Info.MedicineNumb"), "Stage.MedicineNumb")
    check("beta.3: Info.Annihilation -> Task.Annihilation", masuser.resolve(NEW, "Info.Annihilation"), "Task.Annihilation")
    check("an item that did not move keeps its path", masuser.resolve(NEW, "Task.IfFight"), "Task.IfFight")

    SAT9 = datetime(2026, 10, 10, 9, 0, tzinfo=SERVER_TZ)
    MORNING = fx.maa_dir(tmpdir())
    print("[stage gate on a beta.3 config]")
    check("beta.3: the gate reads Stage.Stage (YW-4 is a definite no on the 10-10 files)",
          sg.run_verdict(fx.automas_dir(tmpdir(), beta3=True), MORNING, SAT9)[:2], (sg.NO, "YW-4"))
    check("old layout unchanged", sg.run_verdict(fx.automas_dir(tmpdir()), MORNING, SAT9)[:2], (sg.NO, "YW-4"))

    print("[plan and snapshot on a beta.3 config]")
    d = fx.automas_dir(tmpdir(), beta3=True)
    maa = next(s for s in plan._scripts(d / "config").values() if s.get("kind") == "MAA")
    check("plan: stage mode", maa.get("stage_mode"), "Fixed")
    check("plan: stage", (maa.get("stage_info") or {}).get("Stage"), "YW-4")
    check("plan: annihilation from Task", maa.get("annihilation"), "Annihilation")
    snap = snapshot.maa_from_files(d)
    check("snapshot: 关卡", snap.get("关卡"), "YW-4")
    check("snapshot: 理智药", snap.get("理智药"), 0)
    check("snapshot: 剿灭", snap.get("剿灭"), "Annihilation")

    print("[phone writes go where the user keeps the item]")
    sent = []
    real = commands._find_user, commands._mas
    try:
        user = json.loads(json.dumps(NEW))
        commands._find_user = lambda script: ("S", "U", user)

        def fake_mas(route, payload):
            if route.endswith("/update"):
                sent.append(payload["data"])
                for g, items in payload["data"].items():
                    user.setdefault(g, {}).update(items)
                return {"code": 200}
            return {"data": {"U": user}}
        commands._mas = fake_mas
        failed, before, now = commands._user_item_via_api("MAA", "Info.MedicineNumb", 5)
        check("beta.3: the write goes to Stage.MedicineNumb and reads back 5", (failed, before, now, sent), ("", 3, 5, [{"Stage": {"MedicineNumb": 5}}]))
    finally:
        commands._find_user, commands._mas = real

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_preupdate_pack_vanished():
    """_wait_for_package tolerates OSError/FileNotFoundError when a candidate
    UpdatePack_*.zip disappears or gets renamed between glob() and stat()."""
    import types
    from ark_relay.features import preupdate as P

    clock = [1000.0]
    real_time, real_stat, real_glob = P.time, Path.stat, Path.glob

    def fake_sleep(s: float) -> None:
        clock[0] += s

    P.time = types.SimpleNamespace(sleep=fake_sleep, monotonic=lambda: clock[0])
    try:
        print("[一个候选包 stat() 时被清理消失：跳过它，继续等另一个稳住返回]")
        root = tmpdir()
        vanishing = root / "UpdatePack_old.zip"
        good = root / "UpdatePack_new.zip"
        vanishing.write_bytes(b"old-pack")
        good.write_bytes(b"new-pack-bytes")
        stat_hits = [0]

        def flaky_stat(self, *a, **k):
            if self.name == "UpdatePack_old.zip":
                stat_hits[0] += 1
                raise FileNotFoundError(2, "vanished mid-poll", str(self))
            return real_stat(self, *a, **k)

        Path.stat = flaky_stat
        try:
            got = P._wait_for_package(root, clock[0] + 60.0, stopping=lambda: False)
        finally:
            Path.stat = real_stat
        check("did not crash on vanished pack and returned good pack", got, good)
        check("vanished pack stat() actually hit FileNotFoundError", stat_hits[0] >= 1, True)

        print("[首轮所有候选包都消失 + 一次 glob 抛 OSError：重置稳定计时并最终拿到新包]")
        root2 = tmpdir()
        p2 = root2 / "UpdatePack_v2.zip"
        p2.write_bytes(b"v2-pack-bytes")
        poll_n = [0]

        def flaky_glob(self, pattern, *a, **k):
            if self == root2 and pattern == "UpdatePack_*.zip":
                poll_n[0] += 1
                if poll_n[0] == 1:
                    raise OSError("transient directory read failure")
                if poll_n[0] == 2:
                    return iter([root2 / "UpdatePack_gone.zip"])
            return real_glob(self, pattern, *a, **k)

        Path.glob = flaky_glob
        try:
            got2 = P._wait_for_package(root2, clock[0] + 60.0, stopping=lambda: False)
        finally:
            Path.glob = real_glob
        check("survived glob OSError and missing file then stabilized", got2, p2)
    finally:
        P.time = real_time


if __name__ == "__main__":
    sys.exit(run_parts([_part_preupdate_main, _part_preupdate_automas_carry, _part_preupdate_mas_force, _part_preupdate_not_alarm, _part_main_2, _part_okww_deps, _part_preupdate_once, _part_preupdate_problems, _part_preupdate_session, _part_preupdate_span, _part_preupdate_token, _part_preupdate_unknown_not_fine, _part_okww_shape, _part_gameupdate_main, _part_gameupdate_wait_open, _part_gameupdate_restore_paths, _part_efstart_main, _part_maaend_windowed_start, _part_automas_backend_match, _part_automas_boot_one_alarm, _part_automas_boot_revival, _part_automas_contract_watch, _part_automas_handover, _part_automas_jobfix, _part_automas_ld_adb, _part_mas_address, _part_mas_api_silent, _part_mas_labels, _part_mas_user_pick, _part_masconfig_yaml, _part_mascontract, _part_masuser_beta3, _part_preupdate_pack_vanished]))
