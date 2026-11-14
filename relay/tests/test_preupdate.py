"""The boot pre-update: AUTO-MAS (forced check, a second try that finds the first install landed), OK-WW and its packages, once a day, problems, the session, the span, the expected token failure, unknown is not fine; and OK-WW copies that survive a words-only upstream change.

One part per former file, each run on its own (tests/_parts.py): test_preupdate.py, test_preupdate_automas_carry.py, test_preupdate_mas_force.py, test_preupdate_not_alarm.py, test_preupdate_okww.py, test_preupdate_once.py, test_preupdate_problems.py, test_preupdate_session.py, test_preupdate_span.py, test_preupdate_token.py, test_preupdate_unknown_not_fine.py, test_okww_shape.py.
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
    """When the boot-window pre-update is wanted: only before a queue still to come
today that runs OK-WW, the one program it still launches (its update overwrites
the local patches, re-applied right after). MaaEnd's own update is AUTO-MAS's
job since the 2026-10-11 switch-over. The launching itself is Windows-only.

    Formerly test_preupdate.py.
    """
    import json, os, sys
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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.preupdate import preupdate
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

Before: the first try clicked install, the backend took longer than MAS_INSTALL_WAIT_SECONDS
to come back on the new version, so it left a note and returned 「…（安装已启动，还没确认装成）」.
boot_stages._once_more ran it again; the backend now said the new version, the check said
nothing to update, the try returned "" - and `step(problems) or out` kept the first try's
「还没确认装成」, and after_update (the settings check after an update) never ran.

Pinned here, through the real _once_more with AUTO-MAS's HTTP faked:
* second try finds the first try's version running: 「AUTO-MAS 已更新：旧 → 新」, after_update
  called once with the new version, no note left, one recovered WARNING (daily report only);
* second try finds the old version still running: the first try's text and note stand, no
  after_update;
* without `carry` (any other caller): as before.

    Formerly test_preupdate_automas_carry.py.
    """
    import logging
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import boot_stages
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.preupdate import preupdate_automas as P


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
    """AUTO-MAS 查更新必须带 if_force，否则下载地址是过期的一次性令牌。

2026-08-29 查实：AUTO-MAS 从 08-27 起反复打「开始下载」却始终装不上，
版本一直停在 v5.4.0。真因不在 CDK（CDK 有效，版本检查一直是成功的），
在于两件事凑一起：

* `app/services/update.py:178-184` 把检查结果缓存四小时；
* MirrorChyan 的下载地址是**一次性令牌**，随检查响应带回来存进
  `mirror_chyan_download_url`，下载时直接用它。

于是走缓存 = 拿早就过期的令牌去下载 → 三次重试全 404 → 更新包一个字节都不落地
→ 中继在 `_wait_for_package` 里干等 600 秒超时。日志里只有「开始下载」，
没有任何失败行，看上去像网络慢，其实压根没在下。

机器上实测：不强制 → 404；`if_force=True` → 换到新令牌，状态码 200。

    Formerly test_preupdate_mas_force.py.
    """
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.preupdate import preupdate_automas as P  # run_automas 住在这个模块里，猴子补丁要打在它身上

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


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

        print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
        return 0 if not FAILED else 1


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


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_preupdate_not_alarm():
    """A pre-update item that gave no verdict is tried once more, then pushed to the group.

relay.log 09-29 08:49:14: MAA gave no verdict in its 180 seconds, then
08:50:34 ERROR 「预更新有 1 项没能确认」. From 10-05 (the user, 13:07: 「几乎就是遇到
一点小毛病就停下来报错」) until 2026-10-06 the notice was demoted to Server酱 and
not an alarm. The user's order of 2026-10-06, every error to the group robot,
every time (「不论多少次什么错误都要发」), reverses that. Pinned:

* an item with no verdict runs once more, as a person would; a verdict then
  leaves nothing to report and the day's pre-update counts as clean;
* no verdict twice -> one group alarm (alert=True, route group) saying the queue
  runs as usual and the scripts check themselves, and one WARNING line after it,
  marked as already in the group when the group robot took the alarm (errwatch
  does not push it a second time); nothing at ERROR;
* no second try when the next queue is too close for a whole one;
* the AUTO-MAS slot retries the same way (MAA and MaaEnd are no longer
  pre-updated: AUTO-MAS updates them, items 9a/9b of the 2026-10-11 hand-over);
* the game-update notice is a group alarm too, the same way.

    Formerly test_preupdate_not_alarm.py.
    """
    import logging
    import types

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

    import boot_stages
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.features.okww_patch import okww_overlay
    from ark_relay.features.preupdate import preupdate
    from ark_relay.features.phone import commands
    from ark_relay.core import texts
    from ark_relay.features.alarm.errwatch import ARK
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
    # AUTO-MAS answers: since audit s23 F2 the pre-update asks mas_up() rather than
    # running ensure_automas() a second time (test_automas_boot_one_alarm.py).
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
    from ark_relay.features.alarm import errwatch
    healed = [r for r in REC.records if r.levelno == logging.WARNING and getattr(r, errwatch.RECOVERED, False)]
    # 2026-10-12 (mute audit item 5): the first try's problem was deleted with only an INFO
    # line; a fault that fixed itself writes one red item (errwatch.recovered()) each time.
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
    from ark_relay.features.alarm import errwatch
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
    """OK-WW's pre-update must not start 鸣潮, and must put the switch back.

OK-WW updates through pyappify from a CNB git mirror, and that only happens
when ok-ww.exe - the pyappify shell - is the thing launched. But ok-ww.exe
honours "Auto Start Game When App Starts", which is on for unattended running.
Launching it at boot without disarming that would start the game itself, which
is the same hazard MAA's RunDirectly and MaaEnd's autostart already taught us.

    Formerly test_preupdate_okww.py.
    """
    import ast
    import json
    import os
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.preupdate import preupdate
    from ark_relay.features.preupdate import preupdate_okww

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


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

        src = "".join(q.read_text(encoding="utf-8") for q in sorted((Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "preupdate").glob("preupdate*.py")))  # 预更新拆成了五个文件，一起看
        # 2026-08-25：控制台令牌拿不到时退回 session 0，OK-WW 的更新流程根本不跑，
        # 而未变的版本文件被读成"无需更新"——那天 v3.6.5 已经发布十四小时。
        # 拿不到桌面就必须拒绝启动，并把这件事报上去。
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
        # 2026-08-24: flipping the JSON was not enough - a leftover `ok web` held the
        # settings in memory and wrote them back, so ok-ww.exe read True and started
        # 鸣潮 during a check that was meant to open nothing.
        check("改配置前先停掉在跑的实例", "_okww_quiesce(" in src
              and src.index("_okww_quiesce(", src.index("def run_okww"))
              < src.index("was = _okww_autostart"), True)
        # 数的是**真正的调用点**，不是字面量出现次数。2026-09-08 栽过一次：
        # 给 _okww_quiesce 加了个可注入的 sleep 参数（为了测试不真等两秒），
        # 定义那一行就不再长得像 `_okww_quiesce()`，字面量计数少了一个，测试当场变红——
        # 而调用点一个没少。按字面量数等于让断言依赖签名的写法。
        calls = sum(1 for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_okww_quiesce")
        check("收尾也清一次，不留游戏在后台", calls >= 2, True)

        # 2026-09-06: the pre-update judged 「无需更新」 three seconds after launch, while
        # OK-WW only checks for updates 30 s after its window shows (moved here from the
        # removed test_okww_patch_on_update.py, 2026-10-12).
        check("the minimum wait covers OK-WW's 30 s update check", preupdate.OKWW_MIN_WAIT_SECONDS >= 40, True)
        pre_src = "".join(q.read_text(encoding="utf-8") for q in sorted(
            (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "preupdate").glob("preupdate*.py")))
        check("the 「checked」 verdict waits at least that long",
              "clock() - launched >= OKWW_MIN_WAIT_SECONDS" in pre_src, True)

        timeout_mid_download(root)
        baseline_unknown(root)
        newer_listed_not_installed(root)
        stop_and_switch_memo(root)
        print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
        return 0 if not FAILED else 1


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

            # (d) audit 11-08 A-22: OK-WW does not close for real after the run. The switch still
            # goes back, but the record stays: a slow ok-ww.exe can write the switch off again on
            # its way out, and the next boot puts it back while nothing runs.
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

10-24 OK-WW updated itself to v3.7.11-beta.1, whose ok/core/plugins.py imports `packaging`;
its bundled Python had none and the morning run crashed at start three times. Pinned here,
with subprocess faked (no Windows, no pip):

* no OK-WW python on disk: nothing, no note;
* everything imports: nothing to do, no note, no install;
* requirements.txt read to the name (`onnxocr-ppocrv5>=0.0.20`, extras, markers);
* `packaging` missing (not in OK-WW's requirements.txt, the #115 case): installed, imported
  again, one WARNING marked recovered (daily report only), no note;
* a dist OK-WW lists that is not installed - found by its dist name (importlib.metadata), not
  by a module name (cv2 / opencv-python): installed as listed (round3b-1108);
* a missing module no listed dist is named after: not installed (pip would fetch whatever
  PyPI holds under a guessed name), a note for the group;
* the probe itself, run by this Mac's python: a dist not installed, a module ok.core.plugins
  imports (`import ok` alone never reaches it), a plugins file this ok-script lacks (no note);
* still missing after pip, or a probe that could not run: a note;
* run_okww calls it after closing OK-WW; worst_case_seconds counts its three guards.

    Formerly test_okww_deps_1108.py.
    """
    import inspect
    import logging
    import subprocess
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.alarm import errwatch
    from ark_relay.features.preupdate import preupdate, preupdate_okww as po
    from ark_relay.features.preupdate.preupdate_common import PWSH_GUARD_S


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
    REAL_REQ = (Path(__file__).resolve().parent / "gamesim" / "upstream" / "okww-v3.7.14-beta.2"
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
    # 11-14: splitlines, not split("\n") - on Windows the child prints CRLF and every line kept its \r,
    # so "DIST ..." never matched (relay-windows red since at least 11-10).
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
    """预更新一天只跑一遍。

2026-08-31：`wanted_today()` 只看「今天还有没有要跑 MaaEnd 的队列」，
没有记「今天已经跑过了」——于是**每次服务重启都重跑一整轮**，把
MAA / MaaEnd / OK-WW 挨个拉起来查更新。那天上午部署了三次，它跑了三次，
第三次 MAA 没在 180 秒内给出结论，推了一条「预更新没能确认」。
那条告警本身没说错，只是根本不该有第三次。

留出重试的口子：这一轮真有没确认的项时，隔 RETRY_MIN 分钟还能再试一次——
早上 08:45 查失败、09:00 队列就要开跑，那一次重试是有价值的。

    Formerly test_preupdate_once.py.
    """
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore
    from ark_relay.features.preupdate.preupdate import RETRY_MIN, mark_run, should_run

    FAILED: list[str] = []


    def check(what, got, want):
        if got != want:
            FAILED.append(f"{what}: 得到 {got!r}，应为 {want!r}")


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

        print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_preupdate_problems():
    """预更新查不出结果时，必须报错，而不是静静地当成「无需更新」。

2026-08-25 早上的实况：控制台令牌拿不到 → OK-WW 被扔进 session 0 →
它的更新流程根本没跑 → 版本文件原样不动 → 中继把这读成
「预更新：OK-WW 无需更新（v3.6.4）」写进日志就完事了。
而 v3.6.5 当时已经发布十四个小时，CNB 镜像上也有。手动在控制台会话里
重启一次，十秒就更新完了。

**假的「没问题」比诚实的失败更糟**：没人会去查一件被报告为正常的事。
所以每个 run_* 都要能把「我没能确认」这件事送出函数，
开机流程再把它作为**报警**发出去（不是日常通知）。
（那段开机流程 2026-09-08 从 service.py 搬进了同目录的 boot_stages.py，
整段一起走的，判据一个字没动。）

From 2026-10-05 until 2026-10-06 it was said, but not as an alarm; since the
user's order of 2026-10-06 (「不论多少次什么错误都要发」) it is a group alarm again
(see the note above the boot-stage checks below).

    Formerly test_preupdate_problems.py.
    """
    import os, sys
    import re

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.preupdate import preupdate


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
    except Exception as e:                      # noqa: BLE001
        check(f"默认不传也安全（炸了：{e}）", False)

    # Since 2026-10-05 an unconfirmed item is tried once more; what is still
    # unconfirmed is, since 2026-10-06, a group alarm (alert=True) and a WARNING line
    # after it, not an ERROR (an ERROR line would be a second group alarm of its own,
    # errwatch). The behaviour is pinned in test_preupdate_not_alarm.py; this only
    # checks the source.
    print("\n[开机流程照样说出来，当报警进群（2026-10-06 起）]")
    src = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
    check("收集 problems", "problems: list[str] = []" in src)
    # 2026-09-08 修：原来这里写了个循环，第一轮就 break，而且 f-string 里没有占位符，
    # 于是四个函数只查了一个、查的还是「源码里随便哪儿有 problems=problems」。
    # 现在逐个查：每个 preupdate.<函数>( 的调用参数里都要带 problems=problems。
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
    p = "".join(q.read_text(encoding="utf-8") for q in sorted((Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "preupdate").glob("preupdate*.py")))  # 预更新拆成了五个文件，一起看
    check("不再用「45 秒还是 idle 就算没更新」", "+ 45" not in p)
    check("靠版本列表判断检查过没有", "before_avail" in p)


def _part_preupdate_session():
    """The pre-update must not launch a GUI program from session 0.

The relay runs as LocalSystem, so its processes land in session 0, which has
no desktop. OK-WW is a GUI program: started there it would touch its own
log file and die (as MaaEnd and MAA did while the relay still pre-updated them). That failed silently for three nightly runs - the
pre-update simply timed out at its full budget every time and reported
"本轮照旧". Only _spawn_interactive, which hands the child the console user's
token, may start them.

    Formerly test_preupdate_session.py.
    """
    import ast

    SRC_FILES = sorted((Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "preupdate").glob("preupdate*.py"))  # 拆成了五个文件
    # The functions that actually start a program.
    LAUNCHERS = {"run_okww"}
    ALLOWED = {"_spawn_detached"}   # the fallback is the one place Popen belongs
    # Popen only once _here_in_console said this process runs on the console session, not in
    # session 0 (the installed relay, 11-08 R4-02): checked below that it asks first.
    ON_CONSOLE = {"_spawn_here"}

    FAILED = []


    def require(name, ok, detail=""):
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{'' if ok else ': ' + detail}")
        if not ok:
            FAILED.append(name)


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
            # AUTO-MAS's backend is not listening the moment the relay wakes at
            # boot. Asking once and giving up is what actually happened on
            # 2026-08-24 08:45:33, nine minutes before its backend answered.
            has_loop = any(isinstance(n, (ast.While, ast.For))
                           for n in ast.walk(fns_node["run_automas"]))
            require("等 AUTO-MAS 后端起来（不是问一次就放弃）", has_loop)
            require("等待时长有上限", "MAS_WAIT_SECONDS" in src)
        src_all = src
        require("等包的实现在", "def _wait_for_package" in src_all)
        # The gate that makes this safe lives in the relay's AUTO-MAS process probes, not here.
        svc = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "host" / "automas_procs.py").read_text(
            encoding="utf-8")
        require("中继在安装器运行时不抢着拉起 AUTO-MAS",
              "auto-mas-setup" in svc and "_installer_running" in svc)

        print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        sys.exit(main())


def _part_preupdate_span():
    """预更新通知统一成「程序 已更新：旧 → 新」。

2026-08-30 实证：MaaEnd 08:46:23 启动、08:46:33 就「刚更新完成」，通知只有
「已更新：v2.27.0-beta.1」——旧版本号靠日志正则没捞到。用户 2026-09-01
要求四个程序样式统一，都带老版本号 → 新版本号。

    Formerly test_preupdate_span.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.preupdate import preupdate_common


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
    """The service host's expected token failure (winerror 1314) is not a WARNING.

2026-10-12 08:46:12 the relay logged 「预更新：拿控制台令牌失败，改用计划任务方式」 as a WARNING with
the traceback ``pywintypes.error: (1314, 'WTSQueryUserToken', '客户端没有所需的特权。')``; the
scheduled task then started ok-ww.exe at 08:46:17, yet the WARNING went to the group as
「中继自己报错了」. 1314 is the normal case for a LocalSystem service (the code's own
comment). Other failures stay WARNINGs, and the fallback is still taken in both cases.

    Formerly test_preupdate_token.py.
    """
    import logging
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    FAILED = []


    def require(name, ok, detail=""):
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{'' if ok else ': ' + detail}")
        if not ok:
            FAILED.append(name)


    class WinErr(Exception):
        def __init__(self, code):
            super().__init__(code, "WTSQueryUserToken", "客户端没有所需的特权。")
            self.winerror = code


    def run(code, tcb=True):
        fake = {n: types.ModuleType(n) for n in ("win32con", "win32process", "win32profile", "win32ts")}
        fake["win32ts"].WTSGetActiveConsoleSessionId = lambda: 1
        saved = {n: sys.modules.get(n) for n in fake}
        sys.modules.update(fake)
        from ark_relay.features.preupdate import preupdate_common as pc

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
    if FAILED:
        print("FAILED:", FAILED)
        sys.exit(1)
    print("all checks passed")


def _part_preupdate_unknown_not_fine():
    """Pre-update: "could not tell" must reach the problem list, never read as fine.

2026-10-06 audit (BOARD/补丁审查-1005.md, MAA/启动器/更新):

1. preupdate_common._spawn_interactive: when pywin32 failed to import it went
   straight to a plain session-0 launch, ignoring require_console - the exact
   path of 08-25. Real lines (ark-evidence/relay-log-1006/relay.log:1338-1347):
       08-25 08:48:55 WARNING ark.preupdate  预更新：拿控制台令牌失败，退回普通启动
       08-25 08:49:40 INFO    ark.preupdate  预更新：OK-WW 无需更新（v3.6.4）
   (v3.6.5 had been out for fourteen hours.)

2. preupdate_automas.run_automas:
   (a) AUTO-MAS answers a failed check with HTTP 200 and this body
       (upstream AUTO-MAS-Project/AUTO-MAS c6ca4fb, app/api/update.py:57-75):
           UpdateCheckOut(code=500, status="error", message=..., if_need_update=False,
                          latest_version="", update_info={})
       which the relay logged as 「AUTO-MAS 已是 …（无需更新）」.
   (b) a failed install only went to the log, never to the problem list.

Run: python3 relay/tests/test_preupdate_unknown_not_fine.py

    Formerly test_preupdate_unknown_not_fine.py.
    """
    import os

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.preupdate import preupdate_common as C
    from ark_relay.features.preupdate import preupdate_okww as O
    from ark_relay.features.preupdate import preupdate_automas as A


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

11-02 OK-WW v3.7.14-beta.2 wrapped the log text of claim_daily and claim_battle_pass in
self.tr(...) and changed nothing else; the text hash no longer matched, both copies were
skipped and upstream's bodies ran. The shape (the syntax tree without docstrings, log text and
self.tr; comments and layout are not in the tree) is checked next to the hash. Pinned here:

* the shape the overrides compute at OK-WW start and the one okww_overlay computes before the
  run are the same function: same answers on every sample;
* _SHAPES holds the shapes of the bodies the hashes were copied from (the installed
  v3.7.14-beta.2 fixture), and the overrides file and okww_overlay.shapes() read one table;
* words only (the v3.7.13 form: no self.tr, f-strings, comments, a docstring, layout): the
  hash differs, the shape does not - drift() calls it adapted, drift_line says so without a
  fault word, said once;
* a coordinate, a call or a feature name changed: the shape differs - skipped, said every boot.

    Formerly test_okww_shape.py.
    """
    import ast
    import re

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parents[0]))
    sys.path.insert(0, str(HERE))

    from ark_relay.core import texts
    from ark_relay.features.okww_patch import okww_overlay as ov


    INST = HERE / "gamesim" / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task"
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
    check("覆盖文件里有四处", sorted(pinned), sorted(["DailyTask.claim_daily", "DailyTask.claim_battle_pass",
                                                  "FarmEchoTask.click_team_challenge", "BaseWWTask.get_stamina"]))
    for label, want in pinned.items():
        cls, name = label.split(".")
        # FarmEchoTask reaches BaseWWTask's click_team_challenge through src/combat/, which the
        # fixture does not carry: read it where it is defined.
        text = ov._method_text(classes, cls, name) or ov._method_text(classes, "BaseWWTask", name)
        check(f"{label} 对得上", ov._shape_text(text), want)
    check("没有正文就没有形状（不是空文本的哈希）", (ov._shape_text(""), theirs("")), ("", ""))
    check("这四处都是钉了哈希的", sorted(set(pinned) - {f"{c}.{m}" for c, m, _s, _a in ov.pins()}), [])


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


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_preupdate_automas_carry, _part_preupdate_mas_force, _part_preupdate_not_alarm, _part_main_2, _part_okww_deps, _part_preupdate_once, _part_preupdate_problems, _part_preupdate_session, _part_preupdate_span, _part_preupdate_token, _part_preupdate_unknown_not_fine, _part_okww_shape]))
