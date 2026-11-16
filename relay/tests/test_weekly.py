"""Weekly annihilation, sanity plan, weekly boss, garden, nightmare nest, and WuWa tables."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


def _part_annihilation_no_progress():
    """Annihilation without a progress line is not "done for the week".

2026-09-14 09:00-09:06 the Monday annihilation check ran three times at 17
sanity against a 25 cost; nothing was fought, yet every ledger row says
annihilation_done: true (fixtures/ledger-2026-09-14/ledger.jsonl lines 1-3).
collector_maa read "no 「剿灭模式」 line and no sanity spent" as "MAA saw the
cap was met and left". The only real logs we hold say otherwise: on 2026-09-21
21:32, with the week already full, MAA still fought once (-25) and printed
「剿灭模式 : 1800 / 1800」 (fixtures/maa-annihilation-2026-09-21, copied from
ark-evidence/M6-0923/automas/history/2026-09-21/arknights/MAA-17-30-02.log).
handle._weekly_gates used to close annihilation for the week on
annihilation_done of a run that reports success - and MAA reports Success! when
it stops for lack of sanity. Since the 2026-10-11 hand-over (item 13) AUTO-MAS
books the week itself, so handle must not touch the annihilation gate at all;
the parsed flag still feeds the daily report.

No 09-14 history log survived, so the "nothing fought" input is the 09-21 real
log with its fight block (开始行动 ... 剿灭模式) removed: annihilation
selected, chain started and finished, no fight, no progress - the 09-14 shape.

    Formerly test_annihilation_no_progress.py.
    """
    import json
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_maa
    from ark_relay.features.alarm import handle
    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ, RunRecord

    FX = fx_dir(Path(__file__), "fixtures") / "maa-annihilation-2026-09-21" / "MAA-17-30-02.log"


    TMP = tmpdir()
    real = FX.read_text(encoding="utf-8")
    # The fight block runs from the 「开始行动」 line through the 「剿灭模式」 line
    # (开始行动 / 理智 / 掉落统计 / drops / 剿灭模式); cut it out by content, not line
    # number - the file mixes line endings.
    a = real.rfind("\n", 0, real.index("开始行动 1 次, -25理智")) + 1
    b = real.index("\n", real.index("剿灭模式 : 1800 / 1800")) + 1
    unfought = TMP / "MAA-unfought.log"
    unfought.write_text(real[:a] + real[b:], encoding="utf-8")

    print("[真日志 09-21：打满那周照样打一把，有进度行]")
    full = collector_maa.parse_maa_log(FX)
    check("认出是剿灭", full.get("annihilation"), True)
    check("进度 1800/1800", full.get("annihilation_progress"), [1800, 1800])
    check("打满 = 完成", full.get("annihilation_done"), True)

    print("\n[没打（09-14 那种）：没有进度行、没花理智]")
    got = collector_maa.parse_maa_log(unfought)
    check("认出是剿灭", got.get("annihilation"), True)
    check("没有进度", got.get("annihilation_progress"), None)
    check("没花理智", got.get("sanity_spent"), None)
    check("不算完成", got.get("annihilation_done"), False)

    print("\n[consequence: a successful run never books annihilation in the relay]")


    class Gate:
        def __init__(self):
            self.calls = 0

        def on_success(self, now=None):
            self.calls += 1
            return "closed"


    class Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, msg):
            self.sent.append((title, msg))


    class Boss:
        def on_success(self, now=None):
            return ""


    class Eng:
        def __init__(self):
            self._annihilation = Gate()
            self._weeklyboss = Boss()
            self._garden = None
            self.notifier = Notifier()


    t = datetime(2026, 9, 14, 9, 2, tzinfo=SERVER_TZ)
    for label, raw in (("unfought run", got), ("full run", full)):
        eng = Eng()
        rec = RunRecord(run_id="2026-09-14/arknights/MAA-05-00-01", script="MAA", user="arknights",
                        started=t, finished=t, ok=True, raw=dict(raw))
        handle._weekly_gates(eng, rec)
        check(f"{label}: annihilation gate not asked", eng._annihilation.calls, 0)
        check(f"{label}: nothing sent", eng.notifier.sent, [])

    print("\n[日报：没进度行不写「此前已完成」]")
    e = {"run_id": "2026-09-14/arknights/MAA-05-00-01", "script": "MAA", "user": "u", "ok": True,
         "started": t.isoformat(), "finished": t.isoformat(), "duration_known": True,
         "transitional": False, "failed_tasks": [], "raw": got, "drops": {}, "recruits": {},
         "sanity": None, "sanity_full_at": ""}
    _, body = core.format_daily("2026-09-14", [e])
    check("不说已完成", "此前已完成" in body, False)
    check("说没读到进度", "没读到剿灭进度" in body, True)

    # Counter-examples kept from the other audit team's test (relay2-patchC-1005):
    # a progress line below the cap is "not done", and the ledger rows this fix is
    # about really are the no-progress, sanity-short shape.
    print("\n[真日志 09-07 截到 1480/1800：有进度但没满]")
    REAL0907 = fx_dir(Path(__file__), "replay") / "2026-09-07" / "arknights" / "MAA-05-00-00.log"
    lines0907 = REAL0907.read_text(encoding="utf-8").splitlines(keepends=True)
    cut = next(i for i, l in enumerate(lines0907) if "剿灭模式 : 1480 / 1800" in l)
    partial = TMP / "MAA-partial.log"
    partial.write_text("".join(lines0907[:cut + 1]), encoding="utf-8")
    part = collector_maa.parse_maa_log(partial)
    check("进度 1480/1800", part.get("annihilation_progress"), [1480, 1800])
    check("没满 = 没完成", part.get("annihilation_done"), False)
    _, body = core.format_daily("2026-09-14", [dict(e, raw=part)])
    check("日报写只打到", "剿灭只打到 1480/1800" in body, True)
    _, body = core.format_daily("2026-09-14", [dict(e, raw=full)])
    check("打满的日报写已打满", "本周剿灭已打满（1800/1800）" in body, True)

    print("\n[09-14 账本 1-3 行就是这个形状：理智不够、没有进度、却记成完成]")
    LEDGER = fx_dir(Path(__file__), "fixtures") / "ledger-2026-09-14" / "ledger.jsonl"
    old = [json.loads(x) for x in LEDGER.read_text(encoding="utf-8").splitlines()[:3]]
    check("三行都是理智 17/25、没有进度",
          all(r["raw"].get("maa_sanity_short") == {"have": 17, "cost": 25}
              and not r["raw"].get("annihilation_progress") for r in old), True)
    check("三行当时都被记成完成", [r["raw"].get("annihilation_done") for r in old], [True, True, True])


def _part_annihilation_not_healed_by_routine():
    """A Routine success does not heal an Annihilation failure; a locked 代理指挥 is named.

2026-10-26 Beijing: AUTO-MAS ran MAA in its Annihilation mode three times (09:00:57,
09:02:41, 09:04:5x), each stopped ten seconds into the fight at MAA's
Annihilation@UnableToAgent2 (the new map 灰石剧场, 代理指挥 locked; 每周报酬 0/1800),
then ran the Routine mode, which went through at 09:24. The relay read the Routine
success as AUTO-MAS's retry of the held failure: relay.log 09:24:51 「↩️ MAA 重试后成功，
改为自愈通知」 and 「自己好了，只进日报」; the daily line said 「09:07 补跑成功」. The
week's annihilation was never done and the group never heard of it - against the
user's rule that only what recovered by itself stays out of the group (relay/USER-SWITCHES.txt,
handle._flush_pending). Pinned here:

* a Routine success leaves a held Annihilation failure held, and it reaches the group;
* an Annihilation success still heals a held Annihilation failure (only the daily report);
* the asst.log line Annihilation@UnableToAgent marks the record, and the alarm and the
  daily row say 代理指挥 is locked (texts.ANNIHILATION_NO_PROXY);
* the daily report no longer calls the Routine run a 「补跑成功」 of the annihilation.

    Formerly test_annihilation_not_healed_by_routine.py.
    """
    import json
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.alarm import handle
    from ark_relay.features.alarm import records
    from ark_relay.features.verify import outcome
    from ark_relay.features.makeup import makeup
    from ark_relay.core import texts
    from ark_relay.core import engine as eng_mod
    from ark_relay.core import ledger_report
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    def automas_dir() -> Path:
        root = tmpdir()
        (root / "config").mkdir()
        sc = {"instances": [{"uid": "s-MAA"}], "s-MAA": {"Info": {"Name": "MAA", "Path": r"D:\ark\MAA"}}}
        qc = {"instances": [{"uid": "q0"}], "q0": {
            "Info": {"Name": "早班", "TimeEnabled": True},
            "SubConfigsInfo": {"TimeSet": {"instances": [], "t0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                               "QueueItem": {"instances": [], "i0": {"Info": {"ScriptId": "s-MAA"}}}}}}
        (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
        (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
        return root


    AUTOMAS = automas_dir()
    DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)


    def at(hh, mm=0, ss=0):
        return DAY.replace(hour=hh, minute=mm, second=ss)


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []

        def went_to_group(self):
            return True


    class Src:
        def fetch(self, seen):
            return []


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = AUTOMAS
        cfg.maa_dir = None
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        e._verify_outcome = lambda r: None
        e._archive_maaend_evidence = lambda r: None
        e._maintenance_today = lambda game: False
        return e


    def rec(started, minutes, ok, annihilation, failed=None):
        raw = {"annihilation": True, "fight_count": 0} if annihilation else {}
        if annihilation and ok:   # what collector_maa reads off a full annihilation week
            raw.update(fight_count=1, annihilation_progress=[1800, 1800], annihilation_done=True)
        return RunRecord(run_id=f"{started:%Y-%m-%d}/arknights/MAA-{started:%H-%M-%S}", script="MAA", user="arknights",
                         started=started, finished=started + timedelta(minutes=minutes), ok=ok,
                         failed_tasks=[] if ok else list(failed or ["剿灭作战"]), raw=dict(raw))


    def alarms(e):
        return [(t, b) for t, b, a in e.notifier.sent if a]


    handle._ship_evidence = lambda eng, r: ""
    handle._weekly_gates = lambda eng, r: None

    # What MAA's asst.log said at the first attempt's stop (2026-10-26 09:02:39), trimmed.
    LOCKED_LOG = ("[2026-10-26 09:02:38.378][INF] Start Task Chain: StartUp\n"
                  "[2026-10-26 09:02:39.816][TRC] asst::PipelineAnalyzer::analyze | MatchTemplate Annihilation@UnableToAgent2\n"
                  "[2026-10-26 09:02:40.343][INF] Assistant::append_callback | TaskChainError {\"taskchain\":\"Fight\"}\n")

    print("[the asst.log line marks a locked 代理指挥]")
    check("Annihilation@UnableToAgent2 is a locked proxy", outcome.maa_annihilation_no_proxy(LOCKED_LOG))
    check("a plain fight failure is not", outcome.maa_annihilation_no_proxy("TaskChainError {\"taskchain\":\"Fight\"}"), False)

    print("\n[three Annihilation failures, then a Routine success: not healed, the group hears it]")
    e = build()
    handle._maa_app_log = lambda maa_dir, started, until=None: LOCKED_LOG
    fails_in = [rec(at(9, 0, 57), 2, False, True), rec(at(9, 2, 41), 2, False, True), rec(at(9, 4, 51), 2, False, True)]
    for r in fails_in:
        handle._handle(e, r)
    check("the last Annihilation failure is held", (e._pending.get(("MAA", "arknights")) or fails_in[0]).run_id,
          fails_in[-1].run_id)
    check("…marked as a locked proxy", bool((e._pending[("MAA", "arknights")].raw or {}).get("annihilation_no_proxy")))
    handle._maa_app_log = lambda maa_dir, started, until=None: ""
    routine = rec(at(9, 6, 56), 17, True, False)
    handle._handle(e, routine)
    check("the Routine success left it held (not moved to recovered)",
          (("MAA", "arknights") in e._pending, ("MAA", "arknights") in e._recovered), (True, False))
    check("…and the ledger's later success skips the Routine run", records._later_success(e, fails_in[-1]), "")
    e._flush_pending()
    makeup.maybe_run(e, at(9, 30))
    e._flush_pending()
    got = alarms(e)
    check("one alarm reached the group", len(got), 1)
    check("…counting the three Annihilation tries, not the Routine round", any("重试 3 次" in b for _, b in got))
    check("…it says 代理指挥 is locked", any(texts.ANNIHILATION_NO_PROXY in b for _, b in got))
    check("…nothing held afterwards", ("MAA", "arknights") in e._pending, False)

    print("\n[the daily report: no 「补跑成功」 for the Routine run, the reason is the locked proxy]")
    entries = e.state.read_ledger(f"{DAY:%Y-%m-%d}")
    groups = ledger_report._bare_failure_groups(entries, [x for x in entries if not x["ok"]], [("早班", "09:00")])
    line = ledger_report._bare_line(next(iter(groups.values())))
    check("the row names the locked proxy", texts.ANNIHILATION_NO_PROXY in line)
    check("…and no make-up success", "补跑成功" in line, False)

    print("\n[an Annihilation success still heals a held Annihilation failure]")
    e = build()
    handle._maa_app_log = lambda maa_dir, started, until=None: ""
    first = rec(at(9, 0, 57), 2, False, True)
    handle._handle(e, first)
    handle._handle(e, rec(at(9, 3, 0), 15, True, True))
    check("moved to recovered", (("MAA", "arknights") in e._pending, ("MAA", "arknights") in e._recovered), (False, True))
    e._flush_pending()
    check("no failure alarm", [t for t, _ in alarms(e) if "没跑成" in t], [])

    print("\n[audit 11-08 B-04: the daily report's retry notes keep the two jobs apart too]")
    from ark_relay.core import ledger_report as _lr
    _ann = {"run_id": "d/arknights/MAA-05-00-00", "script": "MAA", "user": "arknights", "ok": False,
            "started": "2026-10-26T05:00:00+08:00", "failed_tasks": ["MAA 运行超时"], "raw": {"annihilation": True}}
    _rou = {"run_id": "d/arknights/MAA-06-00-00", "script": "MAA", "user": "arknights", "ok": True,
            "started": "2026-10-26T06:00:00+08:00", "failed_tasks": [], "raw": {"tasks_done": ["基建换班"]}}
    check("a Routine success is not the retry of a timed-out Annihilation", _lr.retried_notes([_ann, _rou]), {})
    _ann2 = dict(_rou, run_id="d/arknights/MAA-07-00-00", started="2026-10-26T07:00:00+08:00",
                 raw={"annihilation": True, "tasks_done": []})
    check("a later Annihilation success is", list(_lr.retried_notes([_ann, _rou, _ann2])), [_ann["run_id"]])


def _part_annihilation_status():
    """Annihilation (剿灭) weekly status, read from AUTO-MAS (hand-over item 13, 2026-10-11).

Running annihilation once a week is AUTO-MAS's job since the switch-over: with
the MAA account's Info.IfQuickConfig on it records the completed game-week in
Data.AnnihilationCompletedWeek and skips annihilation until the Monday 04:00
reset. The relay only reads. Here the gate is the real class against a fake
AUTO-MAS at the HTTP layer (urllib.request.urlopen, the transport under
commands._mas), and ScriptConfig.json is a real file.

Sources for the shapes used:
* the week marker: AUTO-MAS AutoProxy._current_week_marker,
  f"{iso_year:04d}-W{iso_week:02d}" on the UTC+4 game day; the machine held
  Data.AnnihilationCompletedWeek = "2026-W41" on 2026-10-11
  (BOARD/新中继-重叠可撤核对.md, settings table).
* API: every endpoint is POST; /api/scripts/get, /api/scripts/user/get
  {"scriptId"}; only the `data` member is read (docs/TOOLING.md "AUTO-MAS API").
* ScriptConfig.json: instances[] + <uid>/{Info, SubConfigsInfo/UserData/<uid>/...}
  (docs/CONFIG.md); MAA's install path D:\\ark\\maa.

    Formerly test_annihilation_status.py.
    """
    import json
    import logging
    import os
    import urllib.error
    import urllib.request
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ["ARK_MAS_PORT"] = "36163"   # config.mas_base(); the fake below answers only there
    from ark_relay.features.weekly import annihilation as A
    from ark_relay.features.alarm import errwatch
    from ark_relay.core.config import SERVER_TZ


    class Capture(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelname, record.getMessage()))


    CAP = Capture()
    logging.getLogger(errwatch.ARK).addHandler(CAP)
    logging.getLogger(errwatch.ARK).setLevel(logging.DEBUG)

    MAA_SID, MAA_UID = "8e4f0b4a-maa-script", "c2d1a0f3-maa-user"
    END_SID, END_UID = "59da8762-maaend-script", "a7b6c5d4-maaend-user"

    # Monday 2026-10-05 is game-week 2026-W41; the reset is 04:00 server time.
    MON_0846 = datetime(2026, 10, 5, 8, 46, 3, tzinfo=SERVER_TZ)
    MON_0300 = datetime(2026, 10, 5, 3, 0, tzinfo=SERVER_TZ)
    print("[week marker: the one AUTO-MAS writes]")
    check("10-05 08:46 is W41", A.week_key(MON_0846), "2026-W41")
    check("10-05 03:00 still belongs to W40 (reset is 04:00)", A.week_key(MON_0300), "2026-W40")
    check("single-digit week is zero-padded like AUTO-MAS's",
          A.week_key(datetime(2026, 1, 7, 12, 0, tzinfo=SERVER_TZ)), "2026-W02")


    class Backend:
        """AUTO-MAS's backend as seen through urlopen.

    mode: "up" answers; "down" refuses every connection (AUTO-MAS not running);
    "hung" accepts and never answers (timeout); "no_maa" answers without "MAA".
    """

        def __init__(self, user, mode="up"):
            self.mode = mode
            self.calls = []
            self.scripts = {MAA_SID: {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"}},
                            END_SID: {"Info": {"Name": "MaaEnd", "Path": "D:\\ark\\maaend"}}}
            self.users = {MAA_SID: {MAA_UID: user}, END_SID: {END_UID: {"Info": {"Name": "endfield"}}}}

        def urlopen(self, req, timeout=None):
            url = req.full_url
            assert url.startswith("http://127.0.0.1:36163/"), url
            path = url[len("http://127.0.0.1:36163"):]
            body = json.loads((req.data or b"{}").decode())
            self.calls.append(path)
            if self.mode == "down":
                raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
            if self.mode == "hung":
                raise TimeoutError("timed out")
            if path == "/api/scripts/get":
                if self.mode == "no_maa":
                    return _Resp({"data": {END_SID: self.scripts[END_SID]}})
                return _Resp({"data": self.scripts})
            if path == "/api/scripts/user/get":
                return _Resp({"data": self.users.get(body["scriptId"], {})})
            raise AssertionError(f"the status read must not call {path}")


    class _Resp:
        def __init__(self, obj):
            self._raw = json.dumps(obj, ensure_ascii=False).encode()

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    _real_urlopen = urllib.request.urlopen


    def user(week, switch="Annihilation"):
        return {"Info": {"Name": "arknights", "Annihilation": switch, "IfQuickConfig": True},
                "Data": {"AnnihilationCompletedWeek": week}}


    def world(backend_user, file_user=None, mode="up"):
        root = tmpdir()
        automas = root / "automas"
        (automas / "config").mkdir(parents=True)
        cfg = {
            "instances": [{"uid": MAA_SID}, {"uid": END_SID}],
            MAA_SID: {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"},
                      "SubConfigsInfo": {"UserData": {"instances": [{"uid": MAA_UID}],
                                                      MAA_UID: file_user or backend_user}}},
            END_SID: {"Info": {"Name": "MaaEnd", "Path": "D:\\ark\\maaend"},
                      "SubConfigsInfo": {"UserData": {END_UID: {"Info": {"Name": "endfield"}}}}},
        }
        (automas / "config" / "ScriptConfig.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        be = Backend(backend_user, mode)
        urllib.request.urlopen = be.urlopen
        return A.WeeklyGate(root / "state", automas), be


    try:
        print("\n[AUTO-MAS recorded this week: done, and the line says so]")
        g, be = world(user("2026-W41"))
        check("settings", g.settings(MON_0846), {"本周已完成": True, "当前": "Annihilation"})
        check("week_line", g.week_line(MON_0846), "明日方舟 · 剿灭：本周已打满，暂停到下周一")
        check("reads only (no update call)", [c for c in be.calls if "update" in c], [])

        print("\n[recorded last week: not done, the switch is named]")
        g, be = world(user("2026-W40", "Chernobog@Annihilation"))
        check("settings", g.settings(MON_0846), {"本周已完成": False, "当前": "Chernobog@Annihilation"})
        check("week_line", g.week_line(MON_0846), "明日方舟 · 剿灭：本周还没打满，开关开着（Chernobog@Annihilation）")
        check("Monday 03:00 still counts W40 as this week", g.settings(MON_0300)["本周已完成"], True)

        print("\n[switch off (Close), week not done: the line says off, and the boot alarms]")
        g, be = world(user("2026-W40", "Close"))
        check("week_line says the switch is off, not on",
              g.week_line(MON_0846), "明日方舟 · 剿灭：本周还没打满，开关关着，这周不会打")
        line = g.switch_off_line(MON_0846)
        check("switch_off_line names it", ("开关是关闭" in line, "不会把它打开" in line), (True, True))
        check("…in plain words (texts gate)", A.texts.plain(line), [])

        class Engine:
            _annihilation, _garden, _weeklyboss = g, None, None

        class Notifier:
            def __init__(self):
                self.sent = []

            def send(self, title, body, **kw):
                self.sent.append((title, body, kw.get("alert")))
                return []

        import types
        for name in ("win32event", "win32api", "win32con", "win32file", "win32process",
                     "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
            sys.modules.setdefault(name, types.ModuleType(name))
        import boot_stages
        blog = logging.getLogger(errwatch.ARK + ".boot")
        CAP.lines.clear()
        n = Notifier()
        g._status = lambda now=None, _s=g._status: _s(MON_0846)
        boot_stages._stage_annihilation(Engine(), n, blog)
        check("one group alarm at boot", [(t, a) for t, _b, a in n.sent], [(A.texts.ANNIHILATION_OFF, True)])
        check("one WARNING logged", len([m for lv, m in CAP.lines if lv == "WARNING" and "剿灭" in m]), 1)
        check("the setting is not written", [c for c in be.calls if "update" in c], [])

        print("\n[switch off but this week done (AUTO-MAS's own skip): no alarm]")
        g, be = world(user("2026-W41", "Close"))
        check("no alarm line", g.switch_off_line(MON_0846), "")
        print("\n[switch on, not done: no alarm]")
        g, be = world(user("2026-W40", "Annihilation"))
        check("no alarm line", g.switch_off_line(MON_0846), "")
        print("\n[unreadable: not this alarm]")
        g, be = world(user("2026-W40", "Close"), mode="hung")
        check("no alarm line", g.switch_off_line(MON_0846), "")

        print("\n[never recorded: not done]")
        g, be = world({"Info": {"Name": "arknights", "Annihilation": "Annihilation"}})
        check("no Data section -> not done", g.settings(MON_0846)["本周已完成"], False)

        print("\n[backend down: the file is safe and read]")
        g, be = world(user("2026-W40"), file_user=user("2026-W41"), mode="down")
        check("refused connection -> ScriptConfig.json", g.settings(MON_0846), {"本周已完成": True, "当前": "Annihilation"})

        print("\n[backend up but not answering properly: no stale file value, said once]")
        A._READ_SAID.clear()
        CAP.lines.clear()
        g, be = world(user("2026-W40"), file_user=user("2026-W41"), mode="hung")
        check("hung backend: not the file's stale week (unknown)", g.settings(MON_0846), {"本周已完成": None, "当前": ""})
        check("…and the line says it could not read", g.week_line(MON_0846), "明日方舟 · 剿灭：读不到调度程序记的本周进度")
        warns = [m for lv, m in CAP.lines if lv == "WARNING" and "读不出方舟账号的设置" in m]
        check("one WARNING for two reads", len(warns), 1)
        g, be = world(user("2026-W41"), mode="no_maa")
        check("backend answers without MAA: not the file either", g.settings(MON_0846)["本周已完成"], None)

        print("\n[machine going down: the backend is not asked, the file is read, nothing warned]")
        # 10-11 21:46:43 (relay.log): SvcStop's last state push asked the backend while Windows
        # was killing AUTO-MAS -> ConnectionResetError 10054 -> WARNING -> group push.
        from ark_relay.features.alarm import errwatch
        A._READ_SAID.clear()
        CAP.lines.clear()
        g, be = world(user("2026-W40"), file_user=user("2026-W41"), mode="up")
        def reset(req, timeout=None):
            be.calls.append(req.full_url)
            raise ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。")
        urllib.request.urlopen = reset
        errwatch.mark_os_shutdown()     # SvcShutdown: Windows is going down
        try:
            check("stopping: settings from ScriptConfig.json", g.settings(MON_0846), {"本周已完成": True, "当前": "Annihilation"})
            check("stopping: backend not asked", be.calls, [])
            check("stopping: no WARNING", [m for lv, m in CAP.lines if lv == "WARNING"], [])
        finally:
            errwatch._os_shutdown.clear()
        A._READ_SAID.clear()
        # Mute audit 10-12 item 10: a plain service stop (sc stop, the self-update restart) is
        # not the machine going down - AUTO-MAS stays up, so it is asked, and failing is said.
        be.calls.clear()
        CAP.lines.clear()
        errwatch.mark_stopping()
        try:
            g.settings(MON_0846)
            check("service stop only: the backend is asked", len(be.calls) >= 1, True)
            check("service stop only: the reset warns (pushed)",
                  len([m for lv, m in CAP.lines if lv == "WARNING" and "读不出方舟账号的设置" in m]), 1)
        finally:
            errwatch.clear_stopping()
        A._READ_SAID.clear()
        CAP.lines.clear()
        check("not stopping: the same reset still warns (a live backend failing is a fault)",
              (g.settings(MON_0846)["当前"], len([m for lv, m in CAP.lines if lv == "WARNING" and "读不出方舟账号的设置" in m])),
              ("", 1))

        print("\n[no AUTO-MAS dir: nothing asked]")
        g = A.WeeklyGate(tmpdir(), None)
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked"))
        check("unknown, nothing read", g.settings(MON_0846), {"本周已完成": None, "当前": ""})
    finally:
        urllib.request.urlopen = _real_urlopen


def _part_annihilation_unreadable_none():
    """An unreadable annihilation week record is "unknown", not "not done".

Audit 2026-10-13 (weekly block, finding 5): WeeklyGate.settings() returned
bool(done), so when AUTO-MAS's record could not be read (_status gives done None)
the phone payload said 本周已完成 False and tomorrow's plan
(plan._annihilation_done_tomorrow) wrote 「剿灭 Annihilation」 - "it will run" -
instead of saying it could not tell. week_line already said 读不到 for the same
state. settings() now carries None, and the plan says 「剿灭 本周打没打满读不到」,
the wording the weekly boss uses (plan.py, _weekly_boss_state).

plan._annihilation_done_tomorrow's except stays: settings() does raise on a
ScriptConfig.json of the wrong shape (a top-level list -> AttributeError in
_maa_users), checked below; it now also answers None.

Plan text through next_plan with the machine's AUTO-MAS config
(fixtures/automas-config-2026-10-11), its MAA switch set to "Annihilation".

    Formerly test_annihilation_unreadable_none.py.
    """

    import json
    import logging
    import shutil
    from datetime import datetime
    from unittest import mock

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.weekly import annihilation as A

    AUTOMAS_FX = fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11" / "config"
    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and no relay test may reach the internet (run 38363145659 sat in those
    # fetches on Windows until the 180 s limit).
    plan.maintenance_lines = lambda day: []

    FAILED: list[str] = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
        if not ok:
            FAILED.append(name)


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.records: list[logging.LogRecord] = []

        def emit(self, record):
            self.records.append(record)


    MON = datetime(2026, 10, 12, 8, 46, tzinfo=SERVER_TZ)
    TUE_NOON = datetime(2026, 10, 13, 12, tzinfo=SERVER_TZ)

    print("[settings(): unreadable is None, not False]")
    with mock.patch.object(A, "_maa_user", lambda d: {}):
        check("AUTO-MAS unreadable", A.WeeklyGate(None, Path("automas")).settings(MON),
              {"本周已完成": None, "当前": ""})
    check("no AUTO-MAS dir", A.WeeklyGate(None, None).settings(MON), {"本周已完成": None, "当前": ""})
    done = {"Info": {"Annihilation": "Annihilation"}, "Data": {"AnnihilationCompletedWeek": A.week_key(MON)}}
    with mock.patch.object(A, "_maa_user", lambda d: done):
        check("readable and done", A.WeeklyGate(None, Path("automas")).settings(MON)["本周已完成"], True)
    not_done = {"Info": {"Annihilation": "Annihilation"}, "Data": {}}
    with mock.patch.object(A, "_maa_user", lambda d: not_done):
        check("readable, never recorded: False", A.WeeklyGate(None, Path("automas")).settings(MON)["本周已完成"], False)

    print("\n[week_key: the plain strftime]")
    check("Monday 04:00 is the new week", A.week_key(datetime(2026, 10, 12, 4, 0, tzinfo=SERVER_TZ)), "2026-W42")
    check("Monday 03:59 is the old one", A.week_key(datetime(2026, 10, 12, 3, 59, tzinfo=SERVER_TZ)), "2026-W41")

    print("\n[tomorrow's plan says it cannot tell]")
    automas = tmpdir() / "automas"
    shutil.copytree(AUTOMAS_FX, automas / "config")
    sc = automas / "config" / "ScriptConfig.json"
    cfg = json.loads(sc.read_text(encoding="utf-8"))
    for inst in cfg["instances"]:
        node = cfg[inst["uid"]]
        if node.get("Info", {}).get("Path", "").lower().endswith("maa"):
            for uid, user in node["SubConfigsInfo"]["UserData"].items():
                if isinstance(user, dict):
                    user["Info"]["Annihilation"] = "Annihilation"
    sc.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    plan._tomorrow = lambda: TUE_NOON
    with mock.patch.object(A, "_maa_user", lambda d: {}):
        check("_annihilation_done_tomorrow -> None", plan._annihilation_done_tomorrow(automas), None)
        lines = [ln.strip() for ln in plan.next_plan(automas).splitlines() if "剿灭" in ln]
    check("the plan line", sorted(set(lines)), ["剿灭 本周打没打满读不到"])
    with mock.patch.object(A, "_maa_user", lambda d: not_done):
        lines = [ln.strip() for ln in plan.next_plan(automas).splitlines() if "剿灭" in ln]
    check("readable, not done: the map, as before", sorted(set(lines)) != ["剿灭 本周打没打满读不到"] and bool(lines), True)

    print("\n[a ScriptConfig.json of the wrong shape: settings() raises, the plan still says 读不到]")
    bad = tmpdir() / "bad"
    (bad / "config").mkdir(parents=True)
    (bad / "config" / "ScriptConfig.json").write_text("[]", encoding="utf-8")
    grab = Grab()
    logging.getLogger().addHandler(grab)
    with mock.patch.object(A, "_going_down", lambda: True):      # read the file, skip the backend
        try:
            A.WeeklyGate(None, bad).settings(MON)
            raised = False
        except AttributeError:
            raised = True
        check("settings() raises", raised, True)
        check("plan answers None", plan._annihilation_done_tomorrow(bad), None)
    logging.getLogger().removeHandler(grab)
    check("one WARNING", len([r for r in grab.records if "剿灭" in r.getMessage()]), 1)

    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    sys.exit(1 if FAILED else 0)


def _part_annihilation_skipped_checked_on_skland():
    """A pass MAA skipped because the terminal listed no annihilation counts as done only on Skland's figure.

2026-11-16 Beijing 09:02:19 MAA 6.22 found no annihilation entry in the terminal's to-do list,
said the week was maybe done and fought nothing (fixtures/maa-annihilation-2026-11-16/
MAA-05-00-29.log, the real evidence-bundle 0.log of that pass). No progress line, so both of
the morning's MAA records went to the group as unverified (ledger #174). The week was in fact
full: Skland read campaign.reward 1800/1800 at 09:20:38, storeTs 09:09:57, and the account had
spent ~89 sanity while the machine was off (1/210 at 11-15 21:36, 26/210 at 09:03). Pinned here:

* the parser marks the skip (annihilation_no_entry) and still says not done, no progress;
* the 09-14 shape (no skip line) is not marked, so it never reaches Skland;
* handle asks Skland once and backs the pass only when the figure is full and stored in
  the pass's own game-week; stale, short, failing or missing-token readings give None and
  the alarm goes out as before; a pass that is not a skip never calls Skland;
* the backed pass's ledger line clears annihilation from the day's unverified items for every
  record of the day, the routine run's included; without it annihilation stays on the list.
    """
    import os
    from datetime import datetime, timedelta

    os.environ.update(ARK_STATE_DIR=str(tmpdir() / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_maa
    from ark_relay.features.alarm import handle
    from ark_relay.core import skland
    from ark_relay.core import ledger_report
    from ark_relay.core.config import SERVER_TZ, RunRecord

    FX = fx_dir(Path(__file__), "fixtures") / "maa-annihilation-2026-11-16" / "MAA-05-00-29.log"
    OLD = fx_dir(Path(__file__), "fixtures") / "maa-annihilation-2026-09-21" / "MAA-17-30-02.log"

    print("[真日志 11-16：终端里没剿灭入口，MAA 跳过]")
    got = collector_maa.parse_maa_log(FX)
    check("认出是剿灭", got.get("annihilation"), True)
    check("认出是跳过", got.get("annihilation_no_entry"), True)
    check("没有进度", got.get("annihilation_progress"), None)
    check("MAA 的猜测不算完成", got.get("annihilation_done"), False)
    old = collector_maa.parse_maa_log(OLD)
    check("打过的那种不算跳过", old.get("annihilation_no_entry"), None)

    MON = datetime(2026, 11, 16, 9, 0, 29, tzinfo=SERVER_TZ)

    def rec(raw):
        return RunRecord(run_id="2026-11-16/arknights/MAA-05-00-29", script="MAA", user="arknights",
                         started=MON, finished=MON + timedelta(minutes=2), ok=True, raw=dict(raw))

    class Cfg:
        skland_token = "t"

    class Eng:
        def __init__(self, token="t"):
            self.cfg = Cfg()
            self.cfg.skland_token = token
            self.marks = []

            class St:
                def mark_raw(st, day, run_id, key, value):
                    self.marks.append((day, run_id, key, value))
                    return True
            self.state = St()

    calls = []
    reading = {}

    def fake_login(token, d_id=""):
        calls.append("login")
        if reading.get("raise"):
            raise skland.SklandError("boom")
        return object()

    def fake_anni(cred):
        calls.append("info")
        return dict(reading["value"])

    real_login, real_anni = skland.login, skland.arknights_annihilation
    skland.login, skland.arknights_annihilation = fake_login, fake_anni
    try:
        skip = {"annihilation": True, "annihilation_no_entry": True, "annihilation_done": False}
        stored_now = int(datetime(2026, 11, 16, 9, 9, 57, tzinfo=SERVER_TZ).timestamp())
        last_week = int(datetime(2026, 11, 16, 3, 50, tzinfo=SERVER_TZ).timestamp())

        print("\n[森空岛：本周已满、数据是本周存的 → 算打满]")
        reading.clear(); reading["value"] = {"current": 1800, "total": 1800, "store_ts": stored_now}
        r = rec(skip)
        full = handle._annihilation_checked_full(Eng(), r)
        check("读到 1800/1800", (full or {}).get("current"), 1800)
        e = Eng()
        handle._say_annihilation_checked(e, r, full)
        check("记在这一趟上", r.raw.get("annihilation_official", {}).get("total"), 1800)
        check("写回账本", [m[2] for m in e.marks], ["annihilation_official"])
        check("理智不够那条不再认它", handle._annihilation_sanity_short(e, r), None)

        print("\n[其余情况一律照旧报没证据]")
        reading["value"] = {"current": 1800, "total": 1800, "store_ts": last_week}
        check("周一 04:00 前存的数 → 不算", handle._annihilation_checked_full(Eng(), rec(skip)), None)
        reading["value"] = {"current": 1480, "total": 1800, "store_ts": stored_now}
        check("1480/1800 → 不算", handle._annihilation_checked_full(Eng(), rec(skip)), None)
        reading["value"] = {"current": 1800, "total": 1800, "store_ts": 0}
        check("不知道哪天存的 → 不算", handle._annihilation_checked_full(Eng(), rec(skip)), None)
        reading["raise"] = True
        check("森空岛出错 → 不算、不抛", handle._annihilation_checked_full(Eng(), rec(skip)), None)
        reading.clear(); reading["value"] = {"current": 1800, "total": 1800, "store_ts": stored_now}
        check("没有凭证 → 不算", handle._annihilation_checked_full(Eng(token=""), rec(skip)), None)
        calls.clear()
        check("不是跳过（09-14 那种）→ 不算",
              handle._annihilation_checked_full(Eng(), rec({"annihilation": True, "annihilation_done": False})), None)
        check("不是跳过就不去问森空岛", calls, [])
    finally:
        skland.login, skland.arknights_annihilation = real_login, real_anni

    print("\n[当天账本：剿灭那趟有官方读数 → 早班两趟都不再报剿灭没证据]")
    anni_row = {"run_id": "2026-11-16/arknights/MAA-05-00-29", "script": "MAA", "ok": True,
                "raw": {**skip, "annihilation_official": {"current": 1800, "total": 1800,
                                                          "store_ts": stored_now,
                                                          "read_at": "2026-11-16 09:17:15"}}}
    routine_row = {"run_id": "2026-11-16/arknights/MAA-05-02-20", "script": "MAA", "ok": True,
                   "raw": {"sanity_spent": 24}}
    items = dict(ledger_report.day_unverified_items([anni_row, routine_row]))
    check("MAA 没有没证据的项", items.get("MAA"), None)
    bare = {**anni_row, "raw": dict(skip)}
    items = dict(ledger_report.day_unverified_items([bare, routine_row]))
    check("没有官方读数 → 剿灭照旧没证据", bool(items.get("MAA")), True)


def _part_annihilation_day_rechecked():
    """A later MAA record of the day backs an earlier skipped pass the first Skland read missed.

2026-11-16 21:53 Beijing (ledger #177): the evening Routine record MAA-17-34-36 had no annihilation
in it - AUTO-MAS logged that it skipped the pass with the week booked as 2026-W47 - yet the day's
ledger still held the 09:00 pass with no Skland reading, so 剿灭 went to the group again under
「明日方舟晚班」. That 09:00 line was booked by the code before the Skland check; the same repeat
follows whenever the read at the pass's own landing misses. Pinned here:

* the Routine record reads Skland once and marks the earlier row (its own run_id, its own week);
  the day's unverified items then hold no annihilation;
* Skland failing, or a reading from last week, marks nothing and the item stays (alarm as before);
* no unbacked skip that day, or a non-MAA record, never calls Skland; failed, hand-stopped and
  sanity-short rows are not candidates;
* the hand-started path runs the same checks before pushing the day's unverified items.
    """
    import os
    from datetime import datetime, timedelta

    os.environ.update(ARK_STATE_DIR=str(tmpdir() / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.alarm import handle
    from ark_relay.core import skland
    from ark_relay.core import ledger_report
    from ark_relay.core.config import SERVER_TZ, RunRecord

    MORNING = datetime(2026, 11, 16, 9, 0, 29, tzinfo=SERVER_TZ)
    EVENING = datetime(2026, 11, 16, 21, 34, 36, tzinfo=SERVER_TZ)
    skip = {"annihilation": True, "annihilation_no_entry": True, "annihilation_done": False}
    stored_now = int(datetime(2026, 11, 16, 9, 9, 57, tzinfo=SERVER_TZ).timestamp())
    last_week = int(datetime(2026, 11, 16, 3, 50, tzinfo=SERVER_TZ).timestamp())

    def rows(extra=()):
        return [{"run_id": "2026-11-16/arknights/MAA-05-00-29", "script": "MAA", "user": "arknights",
                 "started": MORNING.isoformat(), "ok": True, "raw": dict(skip)},
                {"run_id": "2026-11-16/arknights/MAA-05-02-20", "script": "MAA", "user": "arknights",
                 "started": (MORNING + timedelta(minutes=2)).isoformat(), "ok": True,
                 "raw": {"sanity_spent": 24}}, *extra]

    class Eng:
        def __init__(self, ledger, token="t"):
            class Cfg:
                skland_token = token
            self.cfg = Cfg()
            self.ledger = ledger
            self.marks = []
            outer = self

            class St:
                def read_ledger(st, day):
                    return outer.ledger if day == "2026-11-16" else []

                def mark_raw(st, day, run_id, key, value):
                    outer.marks.append((day, run_id, key))
                    for e in outer.ledger:
                        if e["run_id"] == run_id:
                            e["raw"][key] = value
                    return True
            self.state = St()

    evening = RunRecord(run_id="2026-11-16/arknights/MAA-17-34-36", script="MAA", user="arknights",
                        started=EVENING, finished=EVENING + timedelta(minutes=18), ok=True,
                        raw={"sanity_spent": 204})
    calls = []
    reading = {}

    def fake_login(token, d_id=""):
        calls.append("login")
        if reading.get("raise"):
            raise skland.SklandError("boom")
        return object()

    def fake_anni(cred):
        calls.append("info")
        return dict(reading["value"])

    real_login, real_anni = skland.login, skland.arknights_annihilation
    skland.login, skland.arknights_annihilation = fake_login, fake_anni
    try:
        print("[11-16 晚班：Routine 那趟落地，早班跳过的剿灭还没读数 → 读一次森空岛，标在早班那行]")
        reading["value"] = {"current": 1800, "total": 1800, "store_ts": stored_now}
        e = Eng(rows())
        check("补核前当天有剿灭没证据", bool(dict(ledger_report.day_unverified_items(e.ledger)).get("MAA")), True)
        calls.clear()
        handle._annihilation_verdicts(e, evening)
        check("只读一次森空岛", calls, ["login", "info"])
        check("标在早班那一行", e.marks, [("2026-11-16", "2026-11-16/arknights/MAA-05-00-29", "annihilation_official")])
        check("晚班自己不沾", evening.raw.get("annihilation_official"), None)
        check("当天没有没证据的项了", dict(ledger_report.day_unverified_items(e.ledger)).get("MAA"), None)

        print("\n[森空岛出错 / 上周的数 → 不标，照旧报]")
        reading["raise"] = True
        e = Eng(rows())
        handle._annihilation_checked_day(e, evening)
        check("出错不标", e.marks, [])
        check("出错照旧没证据", bool(dict(ledger_report.day_unverified_items(e.ledger)).get("MAA")), True)
        reading.clear(); reading["value"] = {"current": 1800, "total": 1800, "store_ts": last_week}
        e = Eng(rows())
        handle._annihilation_checked_day(e, evening)
        check("上周存的数不标", e.marks, [])
        e = Eng(rows(), token="")
        calls.clear()
        handle._annihilation_checked_day(e, evening)
        check("没凭证不去问", calls, [])

        print("\n[不需要核的情况都不去问森空岛]")
        reading["value"] = {"current": 1800, "total": 1800, "store_ts": stored_now}
        backed = rows()
        backed[0]["raw"]["annihilation_official"] = {"current": 1800, "total": 1800, "store_ts": stored_now}
        for name, ledger, r in (
                ("早班已有读数", backed, evening),
                ("跳过那趟失败了", [{**rows()[0], "ok": False}], evening),
                ("跳过那趟被红按钮停了", [{**rows()[0], "raw": {**skip, "manual_stop": True}}], evening),
                ("跳过那趟理智不够", [{**rows()[0], "raw": {**skip, "maa_sanity_short": {"have": 20, "cost": 25}}}], evening),
                ("账本行坏了", [{"run_id": "x", "script": "MAA", "ok": True, "raw": dict(skip)}], evening),
                ("不是 MAA", rows(), RunRecord(run_id="2026-11-16/endfield/MaaEnd-06-12-46", script="MaaEnd",
                                              user="endfield", started=EVENING, finished=EVENING, ok=True))):
            calls.clear()
            e = Eng(ledger)
            handle._annihilation_checked_day(e, r)
            check(f"{name} → 不问", calls, [])

        print("\n[落地这趟自己就是跳过的剿灭 → 标在它自己身上]")
        own = RunRecord(run_id="2026-11-16/arknights/MAA-05-00-29", script="MAA", user="arknights",
                        started=MORNING, finished=MORNING + timedelta(minutes=2), ok=True, raw=dict(skip))
        e = Eng(rows())
        calls.clear()
        handle._annihilation_checked_day(e, own)
        check("还是只读一次", calls, ["login", "info"])
        check("标一次、标在它自己", e.marks, [("2026-11-16", "2026-11-16/arknights/MAA-05-00-29", "annihilation_official")])
        check("记录上也有", own.raw.get("annihilation_official", {}).get("total"), 1800)
    finally:
        skland.login, skland.arknights_annihilation = real_login, real_anni

    print("\n[有人手动开的那趟：推没证据之前同样先核剿灭]")
    order = []
    saved = handle._weekly_gates, handle._annihilation_verdicts, handle._push_unverified

    class HandEng:
        _pending = {}

        def _verify_outcome(self, rec):
            return ""
    try:
        handle._weekly_gates = lambda eng, rec: order.append("gates")
        handle._annihilation_verdicts = lambda eng, rec: order.append("annihilation")
        handle._push_unverified = lambda eng, rec: order.append("unverified")
        got = handle._hand_started_alarm(HandEng(), evening, ("MAA", "arknights"))
    finally:
        handle._weekly_gates, handle._annihilation_verdicts, handle._push_unverified = saved
    check("先核剿灭再推没证据", order, ["gates", "annihilation", "unverified"])
    check("跑完了不报", got, None)


def _part_sanity_plan_both_on():
    """Both sanity tasks on: the evening plan must name both, not only the first.

mastercfg.MAAEND_TREE_TASKS: MaaEnd puts ProtocolSpace and AutoEssence in the
same "sanity_sink" group and runs them in list order, so with both enabled the
first spends sanity and the second takes what is left. sanity_plan.read() took
on[0] only, so plan.py's 「理智用于 …」 line dropped 基质刷取 entirely.

Input is a real master copy already in the repo
(fixtures/maaend-2026-09-10/master-before.json): AutoEssence on, ProtocolSpace
off with its real options (干员养成 → 干员经验). The both-on case flips only
ProtocolSpace's `enabled`, the switch MaaEnd's own task list exposes.

Adapted from audit-maa-core-1006's test of the same name, which carried a
56 KB copy of the 2026-09-25 master for the same two facts; the labels are
the ones sanity_plan writes since the relay2-patchC-1005 version was chosen
(an unknown or missing ProtocolSpace tab is reported as unreadable).

    Formerly test_sanity_plan_both_on.py.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import sanity_plan

    FX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-09-10" / "master-before.json"


    def automas_with(data: dict, name: str) -> Path:
        root = tmpdir() / name / "automas"
        d = root / "data" / "59da8762" / "Default" / "ConfigFile"
        d.mkdir(parents=True)
        (d / "mxu-MaaEnd.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return root


    def edit_protocolspace(data: dict, fn) -> dict:
        out = json.loads(json.dumps(data))
        for ins in out["instances"]:
            for t in ins.get("tasks") or []:
                if t["taskName"] == "ProtocolSpace":
                    fn(t)
        return out


    real = json.loads(FX.read_text(encoding="utf-8"))
    tasks = [t for i in real["instances"] if i.get("id") == "automas" for t in i["tasks"]]
    order = [t["taskName"] for t in tasks if t["taskName"] in sanity_plan.SANITY_TASKS]
    check("real master: ProtocolSpace is listed before AutoEssence", order,
          ["ProtocolSpace", "AutoEssence"])

    print("\n[real master as is: only AutoEssence on]")
    r = sanity_plan.read(automas_with(real, "as-is"))
    check("label names essence farming only", r.get("label"), "基质刷取 → 藏剑谷 → 清波寨")
    check("one task", [t["tab"] for t in r.get("tasks") or []], ["Essence"])
    check("no 'both on' wording", "都开着" in (r.get("label") or ""), False)

    print("\n[both on: ProtocolSpace first, AutoEssence gets what is left]")
    both = edit_protocolspace(real, lambda t: t.__setitem__("enabled", True))
    r = sanity_plan.read(automas_with(both, "both"))
    check("top level still describes the first task", r.get("tab"), "OperatorProgression")
    check("each task in list order", [t["tab"] for t in r.get("tasks") or []],
          ["OperatorProgression", "Essence"])
    check("label names both, in order",
          r.get("label"),
          "干员养成 → 干员经验 → 高级认知载体、初级认知载体，用完再 基质刷取 → 藏剑谷 → 清波寨（2 项都开着，按母本顺序先打前面的）")
    check("understood", r.get("understood"), True)

    print("\n[ProtocolSpace on with no tab chosen: say it is unreadable, no blank]")
    notab = edit_protocolspace(both, lambda t: t["optionValues"].pop("ProtocolSpaceTab"))
    r = sanity_plan.read(automas_with(notab, "notab"))
    check("not understood", r.get("understood"), False)
    check("label says no tab was chosen, and still names the other task",
          r.get("label", "").split("，用完再 ")[:2],
          ["读不懂：ProtocolSpace 没有选页签，不知道理智会用在哪", "基质刷取 → 藏剑谷 → 清波寨（2 项都开着，按母本顺序先打前面的）"])


def _part_sanity_plan_master():
    """理智方案读写母本——不再依赖 AUTO-MAS 的快速配置。

2026-08-28：原实现写 MAS 用户配置的 `Task.SanityTaskType`，那条路要求
`Info.IfQuickConfig` 开着。快速配置被废掉后整个功能失效，这组用例
把新的口径钉住：母本里 `ProtocolSpace` / `AutoEssence` 谁 enabled 谁生效。

    Formerly test_sanity_plan_master.py.
    """
    import json
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.weekly import sanity_plan

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    def make(root: Path, *, essence_on: bool) -> Path:
        d = root / "automas" / "data" / "59da8762" / "Default" / "ConfigFile"
        d.mkdir(parents=True, exist_ok=True)
        (d / "mxu-MaaEnd.json").write_text(json.dumps({
            "instances": [{
                "id": "automas", "name": "AUTO-MAS",
                "tasks": [
                    {"id": "a1", "taskName": "DailyRewards", "enabled": True,
                     "optionValues": {}},
                    {"id": "a2", "taskName": "ProtocolSpace", "enabled": not essence_on,
                     "optionValues": {
                         "ProtocolSpaceTab": {"type": "select",
                                              "caseName": "OperatorProgression"},
                         "OperatorProgression": {"type": "select", "caseName": "Promotions"},
                         "PromotionsRewardsSetOption": {"type": "select",
                                                        "caseName": "Protoset"},
                     }},
                    {"id": "a3", "taskName": "AutoEssence", "enabled": essence_on,
                     "optionValues": {
                         "AutoEssenceChooseLocation": {"type": "checkbox",
                                                       "caseNames": ["VFTheHub"]},
                     }},
                ],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        return root / "automas"


    def main() -> int:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            am = make(root, essence_on=False)

            print("[读：协议空间]")
            r = sanity_plan.read(am)
            check("tab", r["tab"], "OperatorProgression")
            check("line", r["line"], "Promotions")
            check("有人话标签", "干员养成" in r["label"] and "干员进阶" in r["label"], True)

            print("\n[切到基质刷取]")
            ok, msg = sanity_plan.set_plan(am, "Essence", location="WLQingboStockade")
            check("写成功", ok, True)
            r = sanity_plan.read(am)
            check("tab 变了", r["tab"], "Essence")
            check("地点写进去了", r["locations"], ["WLQingboStockade"])
            check("标签是人话", r["label"], "基质刷取 → 清波寨")
            d = json.loads((am / "data/59da8762/Default/ConfigFile/mxu-MaaEnd.json")
                           .read_text(encoding="utf-8"))
            tasks = {x["taskName"]: x for x in d["instances"][0]["tasks"]}
            check("AutoEssence 开了", tasks["AutoEssence"]["enabled"], True)
            check("ProtocolSpace 关了", tasks["ProtocolSpace"]["enabled"], False)
            check("别的任务没被动", tasks["DailyRewards"]["enabled"], True)

            print("\n[基质刷取在「目标选择」模式：写地点没用，拒绝，不替他切回随机（审计 11-08 D-13）]")
            mf = am / "data/59da8762/Default/ConfigFile/mxu-MaaEnd.json"
            doc = json.loads(mf.read_text(encoding="utf-8"))
            ess = next(x for x in doc["instances"][0]["tasks"] if x["taskName"] == "AutoEssence")
            ess["optionValues"]["AutoEssenceMenu"] = {"type": "select", "caseName": "Target"}
            mf.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            before = mf.read_text(encoding="utf-8")
            ok, msg = sanity_plan.set_plan(am, "Essence", location="VFTheHub")
            check("目标选择 + 地点：拒绝", ok, False)
            check("……说清楚是哪种模式、为什么不生效", ("目标选择" in msg, "随机模式" in msg), (True, True))
            check("……母本一个字没动", mf.read_text(encoding="utf-8"), before)
            ok, _ = sanity_plan.set_plan(am, "Essence")
            check("目标选择、不写地点：照常", ok, True)
            check("……读出来的标签说目标选择，不说那个不生效的地点", sanity_plan.read(am)["label"], "基质刷取 → 目标选择")
            ess["optionValues"]["AutoEssenceMenu"] = {"type": "select", "caseName": "Random"}
            mf.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            ok, _ = sanity_plan.set_plan(am, "Essence", location="VFTheHub")
            check("随机模式 + 地点：照常写", (ok, sanity_plan.read(am)["locations"]), (True, ["VFTheHub"]))

            print("\n[切回协议空间]")
            ok, _ = sanity_plan.set_plan(am, "OperatorProgression", "SkillUp")
            check("写成功", ok, True)
            r = sanity_plan.read(am)
            check("line 变了", r["line"], "SkillUp")

            print("\n[拒绝造字段 / 拒绝造任务]")
            ok, msg = sanity_plan.set_plan(am, "WeaponProgression", "WeaponEXP")
            check("母本里没有 WeaponProgression 键就拒绝", ok, False)
            check("说清原因", "中继不会自己新建" in msg, True)

            am2 = make(root / "no_ess", essence_on=False)
            d2 = am2 / "data/59da8762/Default/ConfigFile/mxu-MaaEnd.json"
            dd = json.loads(d2.read_text(encoding="utf-8"))
            dd["instances"][0]["tasks"] = [
                x for x in dd["instances"][0]["tasks"] if x["taskName"] != "AutoEssence"]
            d2.write_text(json.dumps(dd, ensure_ascii=False), encoding="utf-8")
            ok, msg = sanity_plan.set_plan(am2, "Essence")
            check("母本里没有 AutoEssence 就拒绝（这正是那个静默故障）", ok, False)
            check("说清要先加任务", "拒绝新建" in msg, True)

            # Audit 2026-10-05 (C, sanity_plan.py:140-145): with both sanity tasks
            # on (mastercfg.MAAEND_TREE_TASKS says MaaEnd runs them in list order),
            # read() reported only the first, so tomorrow's plan never mentioned
            # essence farming (AutoEssence).
            print("\n[两项理智任务都开着]")
            am3 = make(root / "both", essence_on=False)
            f3 = am3 / "data/59da8762/Default/ConfigFile/mxu-MaaEnd.json"
            d3 = json.loads(f3.read_text(encoding="utf-8"))
            for x in d3["instances"][0]["tasks"]:
                if x["taskName"] in ("ProtocolSpace", "AutoEssence"):
                    x["enabled"] = True
            f3.write_text(json.dumps(d3, ensure_ascii=False), encoding="utf-8")
            r = sanity_plan.read(am3)
            check("两项都报", [t["tab"] for t in r["tasks"]], ["OperatorProgression", "Essence"])
            check("标签里有基质刷取", "基质刷取 → 枢纽区" in r["label"], True)
            check("标签按母本顺序：协议空间在前",
                  r["label"].index("干员养成") < r["label"].index("基质刷取"), True)
            check("顶层仍是第一项（老调用方不变）", r["tab"], "OperatorProgression")
            check("看得懂", r["understood"], True)
            # Counter-example: one task on keeps the old single label exactly.
            r1 = sanity_plan.read(am2)
            check("只开一项：标签不带「都开着」", "都开着" in r1["label"], False)
            check("只开一项：tasks 只有一个", len(r1["tasks"]), 1)

            print("\n[页签读不懂就说读不懂]")
            for x in d3["instances"][0]["tasks"]:
                if x["taskName"] == "ProtocolSpace":
                    x["optionValues"]["ProtocolSpaceTab"] = {"type": "select", "caseName": "NewTabV3"}
            f3.write_text(json.dumps(d3, ensure_ascii=False), encoding="utf-8")
            r = sanity_plan.read(am3)
            check("不认识的页签：understood False", r["understood"], False)
            check("标签说读不懂并带原值", "读不懂" in r["label"] and "NewTabV3" in r["label"], True)
            check("另一项照常报", "基质刷取" in r["label"], True)

            print("\n[找不到母本]")
            check("返回空而不是炸", sanity_plan.read(root / "nowhere"), {})
            ok, _ = sanity_plan.set_plan(root / "nowhere", "Essence")
            check("写也不炸", ok, False)

        print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_sanity_plan_reward_names():
    """The sanity plan speaks MaaEnd's own reward-set names, not AUTO-MAS's A / B.

Audit 2026-10-13 (weekly block, finding 1): sanity_plan keyed its reward table by
"RewardsSetA" / "RewardsSetB" - the names of AUTO-MAS's quick-config field
(fixtures/automas-models/config.py.txt:286-288), which this module does not use.
MaaEnd's master copy holds one case per line, defined in ProtocolSpace.json as
f"{line}RewardsSetOption" (fixtures/maaend-protocolspace-v2.30.0-rc.1,
tasks/ProtocolSpace.json:898-1010; Chinese labels in locales/interface/zh_cn.json).
On the machine's own master (fixtures/maaend-2026-09-10/master-before.json:
OperatorEXPRewardsSetOption = CognitiveCarriers) the old code:
- named no reward item (read()["item"] == ""),
- refused every value MaaEnd defines ("只能 RewardsSetA / RewardsSetB"),
- accepted "RewardsSetA", wrote a case MaaEnd does not define, and the phone's
  answer said ✅ (phone/inbox.py _apply).

MaaEnd's install is found the way production finds it: AUTO-MAS's own config
(fixtures/automas-config-2026-10-11) with the MaaEnd script's path pointed at
the v2.30.0-rc.1 definition fixture.

    Formerly test_sanity_plan_reward_names.py.
    """

    import json
    import shutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import mastercfg
    from ark_relay.features.phone import inbox
    from ark_relay.features.weekly import sanity_plan

    FX = fx_dir(Path(__file__), "fixtures")
    MASTER = FX / "maaend-2026-09-10" / "master-before.json"
    MAAEND = FX / "maaend-protocolspace-v2.30.0-rc.1"
    AUTOMAS_FX = FX / "automas-config-2026-10-11" / "config"

    FAILED: list[str] = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
        if not ok:
            FAILED.append(name)


    def setup(name: str) -> Path:
        """The real master with ProtocolSpace on, under an AUTO-MAS dir whose
    ScriptConfig points the MaaEnd script at the definition fixture."""
        automas = tmpdir() / name / "automas"
        cfg = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        data = json.loads(MASTER.read_text(encoding="utf-8"))
        for t in data["instances"][0]["tasks"]:
            if t["taskName"] == "ProtocolSpace":
                t["enabled"] = True
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        shutil.copytree(AUTOMAS_FX, automas / "config")
        sc = automas / "config" / "ScriptConfig.json"
        d = json.loads(sc.read_text(encoding="utf-8"))
        for inst in d["instances"]:
            info = d[inst["uid"]]["Info"]
            if "maaend" in str(info.get("Path", "")).lower():
                info["Path"] = str(MAAEND)
        sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return automas


    def protocolspace(automas: Path) -> dict:
        f = next((automas / "data").glob("*/Default/ConfigFile/mxu-MaaEnd.json"))
        d = json.loads(f.read_text(encoding="utf-8"))
        return next(t for t in d["instances"][0]["tasks"] if t["taskName"] == "ProtocolSpace")["optionValues"]


    print("[the reward table names exactly MaaEnd's cases, with MaaEnd's own Chinese]")
    opts, _ = mastercfg._maaend_defs(MAAEND)
    zh = json.loads((MAAEND / "locales" / "interface" / "zh_cn.json").read_text(encoding="utf-8"))
    want_table = {}
    for key, opt in opts.items():
        if key.endswith("RewardsSetOption"):
            line = key[: -len("RewardsSetOption")]
            for c in opt["cases"]:
                label = zh[c["label"][1:]]
                want_table[(line, c["name"])] = label.split(".", 1)[1]   # drop the "A." / "B." prefix
    check("REWARD == MaaEnd's cases and labels", sanity_plan.REWARD, want_table)

    print("\n[read(): the machine's master names the item that drops]")
    am = setup("read")
    r = sanity_plan.read(am)
    check("line", r.get("line"), "OperatorEXP")
    check("rewards_set is MaaEnd's case", r.get("rewards_set"), "CognitiveCarriers")
    check("item named", r.get("item"), "高级认知载体、初级认知载体")
    check("label ends with the item",
          r.get("label", "").split("，用完再 ")[0], "干员养成 → 干员经验 → 高级认知载体、初级认知载体")

    print("\n[set_plan(): a case MaaEnd defines is accepted and written]")
    ok, msg = sanity_plan.set_plan(am, "OperatorProgression", "OperatorEXP", "AdvancedCombatRecord")
    check("accepted", ok, True)
    check("written as MaaEnd's case",
          protocolspace(am).get("OperatorEXPRewardsSetOption"), {"type": "select", "caseName": "AdvancedCombatRecord"})
    check("read() now names B", sanity_plan.read(am).get("item"), "高级作战记录")
    ok, msg = sanity_plan.set_plan(am, "OperatorProgression", "Promotions", "Protodisk")
    check("Promotions + Protodisk accepted", ok, True)
    check("written", protocolspace(am).get("PromotionsRewardsSetOption", {}).get("caseName"), "Protodisk")

    print("\n[set_plan(): a value MaaEnd does not define is refused, nothing written]")
    am2 = setup("refuse")
    before = protocolspace(am2)
    ok, msg = sanity_plan.set_plan(am2, "OperatorProgression", "OperatorEXP", "RewardsSetA")
    check("AUTO-MAS's RewardsSetA refused", ok, False)
    check("refusal names MaaEnd's cases", "AdvancedCombatRecord" in msg and "CognitiveCarriers" in msg, True)
    check("master untouched", protocolspace(am2), before)
    ok, msg = sanity_plan.set_plan(am2, "OperatorProgression", "OperatorEXP", "Protodisk")
    check("another line's case refused", ok, False)
    ok, msg = sanity_plan.set_plan(am2, "OperatorProgression", "T-Creds", "CognitiveCarriers")
    check("a line with no reward set refuses any", ok, False)
    check("master still untouched", protocolspace(am2), before)

    print("\n[set_plan(): MaaEnd's definition unreadable -> refuse rather than guess]")
    am3 = setup("nodefs")
    sc = am3 / "config" / "ScriptConfig.json"
    d = json.loads(sc.read_text(encoding="utf-8"))
    for inst in d["instances"]:
        info = d[inst["uid"]]["Info"]
        if str(info.get("Path", "")) == str(MAAEND):
            info["Path"] = str(tmpdir() / "no-maaend-here")
    sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    ok, msg = sanity_plan.set_plan(am3, "OperatorProgression", "OperatorEXP", "CognitiveCarriers")
    check("refused", ok, False)
    check("says the definition could not be read", "读不到" in msg, True)

    print("\n[the phone's answer: no ✅ for a value MaaEnd does not define]")
    am4 = setup("phone")
    box = inbox.Inbox(tmpdir() / "state", automas_dir=am4)
    out = box._apply([{"action": "sanity_plan", "tab": "OperatorProgression",
                       "line": "OperatorEXP", "rewards_set": "RewardsSetA"}])
    check("answer is a refusal", [o.startswith("✗ 理智方案") for o in out], [True])
    out = box._apply([{"action": "sanity_plan", "tab": "OperatorProgression",
                       "line": "OperatorEXP", "rewards_set": "AdvancedCombatRecord"}])
    check("a real case gets ✅", [o.startswith("✅ 理智方案") for o in out], [True])

    print("\n[orders run in the order written (11-08 [D-08])]")
    _saved_ac = inbox.apply_command
    inbox.apply_command = lambda c: (True, "first")
    out = box._apply([{"action": "skip_today", "queue": "x"},
                      {"action": "sanity_plan", "tab": "OperatorProgression",
                       "line": "OperatorEXP", "rewards_set": "AdvancedCombatRecord"}])
    inbox.apply_command = _saved_ac
    check("the earlier order answers first", [o.startswith("✅ first") for o in out], [True, False])

    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    sys.exit(1 if FAILED else 0)


def _part_sanity_plan_weekday():
    """Tomorrow's sanity line honours MaaEnd's weekday ticks for the sanity tasks.

Audit 2026-10-13 (weekly block, finding 2): sanity_plan.read() took every
enabled ProtocolSpace / AutoEssence as "runs tomorrow", and plan.py printed
「理智用于 …」 for it, though MaaEnd runs a task only on the weekdays ticked in
its f"{task}Schedule" option (the master holds ProtocolSpaceSchedule /
AutoEssenceSchedule; with none saved MaaEnd uses the option's default_case).
plan._maaend_extra_bits already applies that rule to AutoCollect.

Input is the machine's own master (fixtures/maaend-2026-09-10/master-before.json:
AutoEssence on, ProtocolSpace off, all seven days ticked), with MaaEnd's
definitions from the same day's install fixture (AutoEssenceSchedule default_case
is all seven days). Checked through next_plan (the 「明日安排」 text), with the
machine's AUTO-MAS config (fixtures/automas-config-2026-10-11) pointing MaaEnd at
a temp install.

    Formerly test_sanity_plan_weekday.py.
    """

    import json
    import shutil
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.names import GAME_ZH

    FX = fx_dir(Path(__file__), "fixtures")
    MASTER = FX / "maaend-2026-09-10" / "master-before.json"
    MAAEND_FX = FX / "maaend-2026-09-10"
    AUTOMAS_FX = FX / "automas-config-2026-10-11" / "config"
    DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

    FAILED: list[str] = []

    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and run 38363145659 (Windows) sat in those fetches until the 180 s limit.
    plan.maintenance_lines = lambda day: []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
        if not ok:
            FAILED.append(name)


    def setup(name: str, edit) -> Path:
        root = tmpdir() / name
        automas = root / "automas"
        cfg = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        data = json.loads(MASTER.read_text(encoding="utf-8"))
        for t in data["instances"][0]["tasks"]:
            if t["taskName"] == "AutoCollect":
                t["enabled"] = False         # keeps the gathering line out of the way
            edit(t)
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        maaend = root / "maaend"
        maaend.mkdir()
        shutil.copy(MAAEND_FX / "interface.json", maaend / "interface.json")
        shutil.copytree(MAAEND_FX / "tasks", maaend / "tasks")
        shutil.copytree(AUTOMAS_FX, automas / "config")
        sc = automas / "config" / "ScriptConfig.json"
        d = json.loads(sc.read_text(encoding="utf-8"))
        for inst in d["instances"]:
            info = d[inst["uid"]]["Info"]
            if "maaend" in str(info.get("Path", "")).lower():
                info["Path"] = str(maaend)
        sc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return automas


    def sanity_lines(automas: Path, tomorrow: datetime) -> list[str]:
        """The sanity line(s) of the Endfield (MaaEnd) block in next_plan."""
        plan._tomorrow = lambda: tomorrow
        out, inside = [], False
        for ln in plan.next_plan(automas).splitlines():
            if ln.startswith("▸"):
                inside = ln == f"▸ {GAME_ZH['MaaEnd']}"
            elif inside and "理智" in ln:
                out.append(ln.strip())
        return out


    def days_but(task: str, skip: str):
        def edit(t):
            if t["taskName"] == task:
                t["optionValues"][f"{task}Schedule"]["caseNames"] = [
                    f"{task}Schedule{d}" for d in DAYS if d != skip]
        return edit


    def both_on(t):
        if t["taskName"] == "ProtocolSpace":
            t["enabled"] = True


    TUESDAY = datetime(2026, 10, 13, 12, tzinfo=SERVER_TZ)
    WEDNESDAY = datetime(2026, 10, 14, 12, tzinfo=SERVER_TZ)

    print("[the machine's master as is: AutoEssence on every day]")
    am = setup("as-is", lambda t: None)
    check("Tuesday names essence farming", sanity_lines(am, TUESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])

    print("\n[AutoEssence not ticked for Tuesday]")
    am = setup("no-tue", days_but("AutoEssence", "Tuesday"))
    got = sanity_lines(am, TUESDAY)
    check("Tuesday: not 「理智用于 基质刷取」", any(ln.startswith("理智用于") for ln in got), False)
    check("Tuesday: says the sanity task sits the day out", len(got) == 1 and "不跑" in got[0], True)
    check("Wednesday: still runs", sanity_lines(am, WEDNESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])

    print("\n[both on, ProtocolSpace not ticked for Tuesday: only essence farming]")
    def both_no_tue_ps(t):
        both_on(t)
        days_but("ProtocolSpace", "Tuesday")(t)
    am = setup("both-no-tue", both_no_tue_ps)
    check("Tuesday: essence farming only", sanity_lines(am, TUESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])
    got = sanity_lines(am, WEDNESDAY)
    check("Wednesday: both, ProtocolSpace first",
          len(got) == 1 and got[0].startswith("理智用于 干员养成") and "基质刷取" in got[0], True)

    print("\n[no AutoEssenceSchedule saved: MaaEnd's default_case (all seven days)]")
    am = setup("default", lambda t: t["optionValues"].pop("AutoEssenceSchedule", None)
               if t["taskName"] == "AutoEssence" else None)
    check("Tuesday names essence farming", sanity_lines(am, TUESDAY), ["理智用于 基质刷取 → 藏剑谷 → 清波寨"])

    print("\n[the default_case itself comes from MaaEnd's definition]")
    from ark_relay.features.weekly import sanity_plan
    bare = {"taskName": "AutoEssence", "optionValues": {}}
    check("all seven days from tasks/AutoEssence", sanity_plan._ticked_days(bare, MAAEND_FX), list(range(7)))
    check("no definition -> unknown (kept by read)", sanity_plan._ticked_days(bare, None), None)
    am = setup("say", days_but("AutoEssence", "Tuesday"))
    check("the sit-out line", sanity_lines(am, TUESDAY),
          ["理智任务明天（周二）不跑（基质刷取仅周一、三、四、五、六、日 跑）"])

    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    sys.exit(1 if FAILED else 0)


def _part_sanity_span():
    """理智/波片的「消耗」和「剩余」不能漏掉最后一趟。

两个游戏同一个毛病：读数都在每趟**开打前**播报。
* 终末地 09-03：五次领取只看到五个读数、四个步长，相邻差求和得 320，真花 400。
  正确写法是「趟数 × 步长」。
* 终末地 09-04：只刷一趟，一个读数零个步长，这一条自己算不出，
  要拿当天上一条的余量来补（116 → 37）。
* 鸣潮 09-04：收尾那行写的是 `current stamina: 37 must_use completed`，
  原正则只认 `not enough to continue`，于是最后一趟整个漏掉，
  报成「消耗 159、剩余 77」，真实是 199 和 37。

    Formerly test_sanity_span.py.
    """
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_maaend, collector_okww
    from ark_relay.features.report import report


    def chk(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")

    # 终末地：五次领取，读数 979→659
    end5 = "\n".join([
        "[2026-09-03 09:00:00.000] 任务开始: 🎱基质刷取",
        *[f"[2026-09-03 09:0{i}:00.000] 当前理智 {979 - 80 * i}/360" for i in range(5)],
        *["[2026-09-03 09:06:00.000] ✅已完成一次基质刷取"] * 5,
        "[2026-09-03 09:07:00.000] 任务完成: 🎱基质刷取",
    ])
    chk("终末地五趟消耗", collector_maaend._maaend_farm(end5).get("maaend_sanity_spent"), 400)

    # 终末地：只刷一趟，一个读数——这一条算不出，交给上层补
    end1 = "\n".join([
        "[2026-09-04 09:42:45.603] 任务开始: 🎱基质刷取",
        "[2026-09-04 09:44:00.149] ✅已完成一次基质刷取",
        "[2026-09-04 09:44:45.736] 当前理智 37/360",
        "[2026-09-04 09:44:49.380] 任务完成: 🎱基质刷取",
    ])
    one = collector_maaend._maaend_farm(end1)
    chk("单趟不硬编数字", one.get("maaend_sanity_spent"), None)
    chk("单趟留了口子", one.get("maaend_sanity_runs_only"), 1)
    es = [{"script": "MaaEnd", "sanity": 116, "raw": {}},
          {"script": "MaaEnd", "sanity": 37, "raw": dict(one)}]
    report._fill_single_run_sanity(es)
    chk("单趟由上一条补出", es[1]["raw"].get("maaend_sanity_spent"), 79)

    # 鸣潮：收尾用的是另一种句式
    ok = "\n".join([
        "info_set current_stamina 236", "info_set current_stamina 157",
        "info_set current_stamina 77",
        "current stamina: 37 must_use completed, no need to use back_up",
    ])
    got = collector_okww._okww_stamina(ok) if hasattr(collector_okww, "_okww_stamina") else None
    if got is None:
        tail = collector_okww._OKWW_STAMINA_END.findall(ok)
        chk("鸣潮收尾读数认得出", tail[-1] if tail else None, "37")
        series = [int(m.group(1)) for m in collector_okww._OKWW_STAMINA.finditer(ok)] + [int(tail[-1])]
        chk("鸣潮消耗", sum(a - b for a, b in zip(series, series[1:], strict=False) if a > b), 199)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_weeklyboss_count():
    """「任务跑完」不等于「三次领满」。

The weekly reward is claimed after the fight, 60 waveplates per claim (entering is free), so short waveplates mean fewer claims.
2026-08-31 实测：贝币刷取把波片吃到只剩 1 点，第二天早上只回到约 147，
只够领两次。而 on_success 原来只要任务跑完就记「本周已打」并摘掉开关——
第三次就永远丢了，而且不出声。

现在改成读游戏页面上的「本周剩余可收取次数」，归零才记账。

    Formerly test_weeklyboss_count.py.
    """
    import os, sys
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import weeklyboss as W
    from ark_relay.core.config import SERVER_TZ

    TMP = tmpdir()
    LOG = TMP / "ok-ww.log"
    os.environ["ARK_OKWW_LOG"] = str(LOG)
    STATE = TMP / "state"; STATE.mkdir()
    NOW = datetime(2026, 8, 31, 20, 0, tzinfo=SERVER_TZ)


    def gate():
        g = W.WeeklyBossGate(STATE, None)
        g.configure(index=1)
        return g

    def write(*lines):
        LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n[读得出剩余次数]")
    write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：3/3')]")
    check("读到 3", W.remaining_from_log(), 3)
    write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：3/3')]",
          "周本本周剩余次数原文: [Box(text='本周剩余可收取次数：1/3')]")
    check("取最后一条", W.remaining_from_log(), 1)
    write("什么都没有")
    check("读不到就是 None", W.remaining_from_log(), None)

    print("\n[weekly boss position: OK-WW lists 9 (total_weekly_number)]")
    (TMP / "sx").mkdir(); gx = W.WeeklyBossGate(TMP / "sx", None)
    check("9 is accepted", gx.configure(index=9)[0], True)
    check("10 is refused", gx.configure(index=10)[0], False)
    check("20 is refused", gx.configure(index=20)[0], False)
    check("0 is refused", gx.configure(index=0)[0], False)
    check("the refusal names the range", "1~9" in gx.configure(index=10)[1], True)

    print("\n[还剩就不许记账]")
    write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：2/3')]")
    g = gate()
    msg = g.on_success(NOW)
    check("说清楚还剩几次", "还剩 2 次" in msg, True)
    check("没记成已打完", g.settings(NOW)["本周已打"], False)

    print("\n[归零才记账]")
    write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：0/3')]")
    msg = g.on_success(NOW)
    check("记成已打完", g.settings(NOW)["本周已打"], True)
    check("话说得对", "三次已领满" in msg and msg.startswith("鸣潮 · 周本："), True)

    print("\n[读不到时宁可不记]")
    STATE2 = TMP / "s2"; STATE2.mkdir()
    write("什么都没有")
    g2 = W.WeeklyBossGate(STATE2, None); g2.configure(index=1)
    check("不记账", g2.on_success(NOW), "")
    check("开关继续挂着", g2.settings(NOW)["本周已打"], False)

    # docs/SILENT-FAILURES-AUDIT.md weeklyboss.py:263 - this was INFO only, so a broken
    # OCR patch meant the boss was never booked done and nobody was told.
    print("\n[remaining claims unreadable after a won round: a WARNING, not INFO]")
    import logging


    class _Lines(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelname, record.getMessage()))


    _log = _Lines()
    logging.getLogger(W.log.name.rsplit(".", 1)[0]).addHandler(_log)   # every relay logger's parent
    STATE3 = TMP / "s3"; STATE3.mkdir()
    write("什么都没有")
    check("still not booked", W.WeeklyBossGate(STATE3, None).on_success(NOW), "")
    check("one WARNING says the count could not be read",
          len([m for lv, m in _log.lines if lv == "WARNING" and "剩余次数" in m]), 1)

    print("\n[周日留下的 0/3 不算周一这趟（11-08 [D-02]）]")
    (TMP / "sd2").mkdir(); g2 = W.WeeklyBossGate(TMP / "sd2", None); g2.configure(index=1)
    write("2026-08-30 21:00:00,000 INFO 周本本周剩余次数原文: [Box(text='本周剩余可收取次数：0/3')]",
          "2026-08-31 20:00:05,000 INFO 进入周本失败")
    MON = datetime(2026, 8, 31, 20, 0, tzinfo=SERVER_TZ)
    check("周一这趟没读到次数：不记成打满", g2.on_success(MON, since=MON), "")
    write("2026-08-30 21:00:00,000 INFO 周本本周剩余次数原文: [Box(text='本周剩余可收取次数：0/3')]",
          "2026-08-31 20:00:05,000 INFO 周本本周剩余次数原文: [Box(text='本周剩余可收取次数：0/3')]")
    check("周一这趟自己读到 0/3：记成打满", "已领满" in g2.on_success(MON, since=MON), True)

    print("\n[周本序号：True / 乱值不收（11-08 [D-03]）]")
    check("True is refused", gx.configure(index=True)[0], False)
    check("'x' is refused", gx.configure(index="x")[0], False)
    check("'3' is accepted", gx.configure(index="3")[0], True)


def _part_weeklyboss_cycle():
    """周本要和剿灭一个作息：周一 04:00 自动挂回来，领满就摘掉、之后不再检测。

用户 2026-08-31：「我要的是能做到像明日方舟的剿灭那样的，每周一自动刷新
状态，然后优先打周本三次，完事才是普通体力副本。打完副本计入已完成，
并且之后不再检测，周一刷新。」

这里只测「挂上/摘掉/周一挂回来」这条状态机；
「周本排在体力副本之前」由 ok_tasks 覆盖层的 DailyTask.run 钩子保证，
见 docs/OKWW-WEEKLY-BOSS.md。

    Formerly test_weeklyboss_cycle.py.
    """
    import json, os, sys
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import weeklyboss as W
    from ark_relay.core.config import SERVER_TZ

    TMP = tmpdir()
    LOG = TMP / "ok.log"; os.environ["ARK_OKWW_LOG"] = str(LOG)
    STATE = TMP / "state"; STATE.mkdir()
    # 假 AUTO-MAS：母本目录靠 DailyTask.json 认出来
    CFG = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"
    CFG.mkdir(parents=True)
    (CFG / "DailyTask.json").write_text(json.dumps(
        {W.KEY: ["Auto Farm all Nightmare Nest"]}), encoding="utf-8")
    (CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")


    def tasks():
        return json.loads((CFG / "DailyTask.json").read_text(encoding="utf-8"))[W.KEY]

    def at(mon_day, hh, mm=0):
        return datetime(2026, 8, mon_day, hh, mm, tzinfo=SERVER_TZ)

    def left(n):
        LOG.write_text(f"周本本周剩余次数原文: [本周剩余可收取次数：{n}/3]\n", encoding="utf-8")

    g = W.WeeklyBossGate(STATE, TMP / "automas")
    g.configure(index=1)

    print("\n[开着就挂上，配置一起写对]")
    g.enforce(at(31, 10))
    check("附加任务里有周本", W.TASK_NAME in tasks(), True)
    farm = json.loads((CFG / "FarmEchoTask.json").read_text(encoding="utf-8"))
    check("传送目标", farm.get("Teleport to Boss"), W.WEEKLY)
    check("难度是最高级", farm.get("Boss Level"), W.MAX_LEVEL)
    check("次数", farm.get("Repeat Farm Count"), 3)

    print("\n[没领满就一直挂着——这正是剿灭没有、而周本必须有的]")
    left(2)
    g.on_success(at(31, 11))
    g.enforce(at(31, 11))
    check("还剩 2 次，开关不许摘", W.TASK_NAME in tasks(), True)

    print("\n[领满才摘掉，之后不再检测]")
    left(0)
    g.on_success(at(31, 12))
    check("记成本周已打", g.settings(at(31, 12))["本周已打"], True)
    g.enforce(at(31, 12))
    check("附加任务里已摘掉", W.TASK_NAME in tasks(), False)
    g.enforce(at(31, 20))          # 同一周内反复跑，不许再挂回去
    check("同周内再跑也不挂回来", W.TASK_NAME in tasks(), False)

    print("\n[周一 04:00 前仍算上一周]")
    # 2026-09-07 是周一。03:59 仍属于上一周，不许刷新。
    g.enforce(datetime(2026, 9, 7, 3, 59, tzinfo=SERVER_TZ))
    check("周一 03:59 还不刷新", W.TASK_NAME in tasks(), False)

    print("\n[过了周一 04:00 自动挂回来]")
    g.enforce(datetime(2026, 9, 7, 4, 1, tzinfo=SERVER_TZ))
    check("下周一自动挂回来", W.TASK_NAME in tasks(), True)
    check("状态不再显示「本周已打」",
          g.settings(datetime(2026, 9, 7, 4, 1, tzinfo=SERVER_TZ))["本周已打"], False)

    print("\n[没有总开关：和剿灭一样，只有「本周做完」才摘掉]")
    check("settings 里没有开关", "开" in g.settings(datetime(2026, 9, 7, 5, 0, tzinfo=SERVER_TZ)), False)
    check("次数固定 3", g.settings()["打几次"], 3)
    check("等级固定 90", g.settings()["难度等级"], "90")

    # docs/SILENT-FAILURES-AUDIT.md weeklyboss.py:75 - an unreadable FarmEchoTask.json
    # used to leave the weekly boss armed with no teleport target and no word.
    print("\n[FarmEchoTask.json unreadable while switching on: said once per condition]")
    import logging


    class _Lines(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelname, record.getMessage()))


    _log = _Lines()
    logging.getLogger(W.log.name.rsplit(".", 1)[0]).addHandler(_log)   # every relay logger's parent
    MON = datetime(2026, 9, 7, 5, 0, tzinfo=SERVER_TZ)
    (CFG / "FarmEchoTask.json").write_text("{ torn", encoding="utf-8")
    g.enforce(MON)
    g.enforce(MON)
    farm_warn = lambda: [m for lv, m in _log.lines if lv == "WARNING" and W.FARM in m]  # noqa: E731
    check("one WARNING for two rounds (enforce runs every round)", len(farm_warn()), 1)
    # 2026-10-13 audit: the task stayed listed with no target, and upstream's
    # validate_additional_tasks then raises before login (the whole daily fails).
    check("no target: the weekly boss is not left listed", W.TASK_NAME in tasks(), False)
    (CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")
    g.enforce(MON)
    check("readable again: the target is written",
          json.loads((CFG / "FarmEchoTask.json").read_text(encoding="utf-8")).get("Teleport to Boss"), W.WEEKLY)
    check("readable again: listed again", W.TASK_NAME in tasks(), True)

    (CFG / "FarmEchoTask.json").write_text("{ torn", encoding="utf-8")
    g.enforce(MON)
    check("after it cleared, a new failure is said again", len(farm_warn()), 2)

    print("\n[the target is written before the task is listed; a failed write lists nothing]")
    (CFG / "DailyTask.json").write_text(json.dumps({W.KEY: []}), encoding="utf-8")
    (CFG / "FarmEchoTask.json").write_text(json.dumps({"Teleport to Boss": "No"}), encoding="utf-8")
    order = []
    _real_write = W._write


    def _spy(f, cfg):
        order.append(Path(f).name)
        return _real_write(f, cfg)


    W._write = _spy
    try:
        g.enforce(MON)
    finally:
        W._write = _real_write
    check("FarmEchoTask.json first, DailyTask.json after", order, [W.FARM, W.DAILY])
    check("…and listed", W.TASK_NAME in tasks(), True)
    (CFG / "DailyTask.json").write_text(json.dumps({W.KEY: []}), encoding="utf-8")
    (CFG / "FarmEchoTask.json").write_text(json.dumps({"Teleport to Boss": "No"}), encoding="utf-8")
    W._write = lambda f, cfg: False if Path(f).name == W.FARM else _real_write(f, cfg)
    try:
        g.enforce(MON)
    finally:
        W._write = _real_write
    check("target write failed: the task is not listed", W.TASK_NAME in tasks(), False)
    g.enforce(MON)
    check("next round with a writable target: listed", W.TASK_NAME in tasks(), True)
    (CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")
    g.enforce(MON)


def _part_weeklyboss_reopen():
    """「新的一周」通知要带上鸣潮周本（用户 2026-09-07）。

2026-09-07（周一）08:48 的通知只有「新的一周，剿灭已重新开启」，
周本那边 weeklyboss.json 里 done_week 还是上周（2026-W36），
用户看不到周本这周会不会打、打哪个、打几次。

    Formerly test_weeklyboss_reopen.py.
    """
    import json, os, sys, types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import weeklyboss as W
    from ark_relay.core.config import SERVER_TZ


    TMP = tmpdir()
    os.environ["ARK_OKWW_LOG"] = str(TMP / "ok.log")
    STATE = TMP / "state"; STATE.mkdir()
    CFG = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"; CFG.mkdir(parents=True)
    (CFG / "DailyTask.json").write_text(json.dumps({W.KEY: []}), encoding="utf-8")
    (CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")

    MON = datetime(2026, 9, 7, 8, 48, tzinfo=SERVER_TZ)          # 2026-W37
    (STATE / "weeklyboss.json").write_text(json.dumps(
        {"enabled": True, "index": 1, "count": 3, "level": "90",
         "name": "千傀重楼", "done_week": "2026-W36"}), encoding="utf-8")
    g = W.WeeklyBossGate(STATE, TMP / "automas")

    print("[机器上 09-07 的状态：上周领满，周一开机]")
    line = g.maybe_reopen(MON)
    check("说清打哪个", line, "鸣潮 · 周本：千傀重楼，本周还没领满")
    check("记账已清", "done_week" in g._load(), False)
    check("同一次开机再问就不再说", g.maybe_reopen(MON), "")
    check("week_line 仍能报状态", g.week_line(MON), "鸣潮 · 周本：千傀重楼，本周还没领满")

    print("[本周已领满 / 开关关着]")
    g.on_success  # noqa: B018
    s = g._load(); s["done_week"] = "2026-W37"; g._save(s)
    check("已领满", g.week_line(MON), "鸣潮 · 周本：千傀重楼 本周三次已领满，暂停到下周一")
    check("没有总开关", "开" in g.settings(MON), False)

    print("[开机那一段：剿灭、周常乐园、周本合成一条「新的一周」，三行都在]")
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
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))
    # 开机的各个阶段 2026-09-08 从 service.py 搬进了 boot_stages.py；
    # 私有名要用就直接引它本尊，不经 service.py 转手。
    import boot_stages

    sent = []
    class N:
        def send(self, title, body, **kw): sent.append((title, body))
    class Log:
        def exception(self, *a, **k): print("    EXC", a)
    class Gate:
        def __init__(self, reopen, line): self._r, self._l = reopen, line; self.enforced = 0
        def maybe_reopen(self): return self._r
        def week_line(self): return self._l
        def enforce(self): self.enforced += 1
    class AnniStatus:
        """Annihilation since the 2026-10-11 hand-over: a status line only, no roll-over."""
        def __init__(self, line): self._l = line
        def week_line(self): return self._l
        def maybe_reopen(self): raise AssertionError("annihilation must not roll over in the relay any more")
        def enforce(self): raise AssertionError("annihilation must not be enforced by the relay any more")
    class Eng:
        def __init__(self, ann, garden, boss):
            self._annihilation, self._garden, self._weeklyboss = ann, garden, boss

    A_LINE = "明日方舟 · 剿灭：本周还没打满，开关开着（Annihilation）"
    G_LINE = "鸣潮 · 周常乐园：本周还没做，每趟都会去检查"
    B_LINE = "鸣潮 · 周本：千傀重楼，本周还没领满"
    B_FULL = "鸣潮 · 周本：千傀重楼 本周三次已领满，暂停到下周一"

    sent.clear(); boss = Gate(B_LINE, B_LINE); garden = Gate(G_LINE, G_LINE)
    boot_stages._stage_annihilation(Eng(AnniStatus(A_LINE), garden, boss), N(), Log())
    check("both roll over: one notice, annihilation status first", sent, [("🗓️ 新的一周", "\n".join([A_LINE, G_LINE, B_LINE]))])
    check("weekly boss is really put back before saying so", boss.enforced, 1)
    check("weekly garden likewise", garden.enforced, 1)

    sent.clear(); garden = Gate(G_LINE, G_LINE)
    boot_stages._stage_annihilation(Eng(AnniStatus(A_LINE), garden, Gate("", B_FULL)), N(), Log())
    check("only the garden rolls over: the other two still report", sent,
          [("🗓️ 新的一周", "\n".join([A_LINE, G_LINE, B_FULL]))])

    sent.clear()
    boot_stages._stage_annihilation(Eng(AnniStatus(A_LINE), Gate("", G_LINE), Gate("", B_LINE)), N(), Log())
    check("nothing rolls over: nothing sent (annihilation alone never triggers it)", sent, [])

    sent.clear()
    boot_stages._stage_annihilation(Eng(None, Gate(G_LINE, G_LINE), Gate("", B_LINE)), N(), Log())
    check("no annihilation gate: the other lines still go out", sent, [("🗓️ 新的一周", "\n".join([G_LINE, B_LINE]))])


def _part_garden_gate():
    """周常乐园的周门：本周做完就关掉检查，周一 04:00 开回来。

和剿灭那道门是同一个形状，所以周界口径必须一致——直接复用
`annihilation.week_key`，不许自己再算一遍。这个文件把三件事钉住：

  1. 周界就是周一 04:00（周一 03:59 还算上一周）；
  2. 记账只写状态文件，不碰配置（落盘交给 enforce）；
  3. enforce 幂等，而且新的一周会把检查放回去。

    Formerly test_garden_gate.py.
    """
    import json
    import tempfile
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import garden
    from ark_relay.features.weekly.annihilation import week_key
    from ark_relay.core.config import SERVER_TZ

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    def test_week_boundary() -> None:
        """周一 04:00 才翻篇。03:59 跑的那轮必须还算上一周。"""
        print("[周界：周一 04:00]")
        mon = datetime(2026, 8, 24, 3, 59, tzinfo=SERVER_TZ)      # 周一 03:59
        check("周一 03:59 和上周日同一周",
              week_key(mon) == week_key(mon - timedelta(hours=6)), True)
        check("周一 04:01 已经是新的一周",
              week_key(mon + timedelta(minutes=2)) != week_key(mon), True)


    def _make_master(root: Path, tasks: list[str]) -> Path:
        """造一份和机器上一样的母本：<automas>/data/<sid>/Default/ConfigFile/DailyTask.json"""
        d = root / "automas" / "data" / "c5e96ddc" / "Default" / "ConfigFile"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "DailyTask.json"
        f.write_text(json.dumps({
            "Which to Farm": "Forgery Challenge",
            garden.KEY: list(tasks),
            "Exit After Task": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return root / "automas"


    def _read(automas: Path) -> list[str]:
        f = automas / "data" / "c5e96ddc" / "Default" / "ConfigFile" / "DailyTask.json"
        return json.loads(f.read_text(encoding="utf-8"))[garden.KEY]


    def _other_keys(automas: Path) -> dict:
        f = automas / "data" / "c5e96ddc" / "Default" / "ConfigFile" / "DailyTask.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k != garden.KEY}


    def test_gate(tmp: Path) -> None:
        print("[记账 → 落盘 → 周一恢复]")
        now = datetime(2026, 8, 26, 12, 0, tzinfo=SERVER_TZ)   # 周三
        automas = _make_master(tmp, [garden.TASK_NAME, "Other Task"])
        g = garden.GardenGate(tmp, automas)
        before_other = _other_keys(automas)

        msg = g.on_success(now)
        check("第一次记账有回话", bool(msg), True)
        check("记账**不碰配置**（落盘留给 enforce）",
              garden.TASK_NAME in _read(automas), True)
        check("状态文件记下了本周", json.loads((tmp / "state.json").read_text())["weekly"]["garden"]["done_week"],
              week_key(now))
        check("同一周重复记账不再啰嗦", g.on_success(now), "")

        check("enforce 生效", g.enforce(now), True)
        check("检查已关掉", garden.TASK_NAME in _read(automas), False)
        check("同组别的任务没被误伤", "Other Task" in _read(automas), True)
        check("DailyTask 其余键原样保留", _other_keys(automas), before_other)
        check("已经关掉了就不再重复写", g.enforce(now), False)

        nxt = now + timedelta(days=7)
        check("新的一周会把检查放回去", g.enforce(nxt), True)
        check("检查回来了", garden.TASK_NAME in _read(automas), True)
        # The earlier week's booking is left for maybe_reopen at boot, so the new-week
        # notice still sees the roll-over (audit 10-13, test_garden_rollover_after_tick.py).
        check("过期记账留给开机清", json.loads((tmp / "state.json").read_text())["weekly"]["garden"].get("done_week"),
              week_key(now))
        check("开机清账并说新的一周", bool(g.maybe_reopen(nxt)), True)
        check("过期记账已清掉", json.loads((tmp / "state.json").read_text())["weekly"].get("garden") or {}, {})

        # Written but read back unchanged (another program wrote it back): not reported as set,
        # False, pushed again next round (audit 11-08 D-13).
        g.on_success(nxt)
        real_write = garden.atomic_write_text
        garden.atomic_write_text = lambda f, text: None          # the write "went through", the file did not change
        try:
            check("写了但读回来没变：不算改成", g.enforce(nxt), False)
            check("……开关还在（没谎称关了）", garden.TASK_NAME in _read(automas), True)
        finally:
            garden.atomic_write_text = real_write
        check("下一轮照常写成", g.enforce(nxt), True)

        # 找不到母本时必须安静地不动手，而不是抛异常把中继带崩
        g2 = garden.GardenGate(tmp, tmp / "nowhere")
        g2._save({"done_week": week_key(now)})
        check("母本找不到时 enforce 返回 False 而不炸", g2.enforce(now), False)


    def main(tmp: Path) -> int:
        test_week_boundary()
        test_gate(tmp)
        print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        with tempfile.TemporaryDirectory() as t:
            raise SystemExit(main(Path(t)))


def _part_garden_rollover_after_tick():
    """A periodic tick after Monday 04:00 must not eat the weekly garden's roll-over.

Audit 2026-10-13 (weekly block, finding 3). GardenGate.enforce() popped a
done_week from an earlier week itself (garden.py:113-114, :132-133), so the
boot-time WeekGate.maybe_reopen found nothing to roll over and the garden never
joined the new-week notice. The machine's record of Monday 2026-10-05 (Beijing
time, relay.log of the 10-13 copy):

    10-05 04:43:37 INFO    ark.garden  周常乐园检查已恢复
    10-05 08:45:19 INFO    ark.service  服务模式启动 ...
    10-05 08:46:03 INFO    ark.weeklyboss  新的一周，周本记账已清（上周 2026-W40）

No 「新的一周，周常乐园记账已清」 line: the 04:43 tick had already cleared it.
That day's new-week notice went out only because the weekly boss rolled over;
with only the garden done the week before, none would have gone out.

Replayed here: garden done in 2026-W40, switch off; ticks at 04:43:37 and 05:00
on Monday 10-05; boot at 08:46:03.

    Formerly test_garden_rollover_after_tick.py.
    """

    import json
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import boot_stages
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.weekly import garden as G
    from ark_relay.features.weekly.annihilation import week_key

    FAILED: list[str] = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
        if not ok:
            FAILED.append(name)


    SAT = datetime(2026, 10, 3, 20, 0, tzinfo=SERVER_TZ)
    TICK = datetime(2026, 10, 5, 4, 43, 37, tzinfo=SERVER_TZ)
    TICK2 = datetime(2026, 10, 5, 5, 0, 0, tzinfo=SERVER_TZ)
    BOOT = datetime(2026, 10, 5, 8, 46, 3, tzinfo=SERVER_TZ)


    class AtBoot(G.GardenGate):
        """The gate as the boot stage calls it (no `now`), pinned to 10-05 08:46:03."""

        def maybe_reopen(self, now=None):
            return super().maybe_reopen(now or BOOT)

        def enforce(self, now=None):
            return super().enforce(now or BOOT)

        def week_line(self, now=None):
            return super().week_line(now or BOOT)


    class Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, body, **kw):
            self.sent.append((title, body))
            return []


    class Log:
        def exception(self, *a, **k):
            FAILED.append("boot stage logged an exception")

        def warning(self, *a, **k):
            pass


    def master(tmp: Path) -> Path:
        cfg = tmp / "automas" / "data" / "sid" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        (cfg / "DailyTask.json").write_text(json.dumps({G.KEY: [G.TASK_NAME]}), encoding="utf-8")
        return cfg / "DailyTask.json"


    def switch_on(f: Path) -> bool:
        return G.TASK_NAME in json.loads(f.read_text(encoding="utf-8"))[G.KEY]


    check("10-03 is game-week 2026-W40", week_key(SAT), "2026-W40")
    check("10-05 04:43 is the new week 2026-W41", week_key(TICK), "2026-W41")

    print("\n[garden done in W40, switched off]")
    tmp = tmpdir()
    f = master(tmp)
    g = AtBoot(tmp / "state", tmp / "automas")
    g.on_success(SAT)
    check("switched off in W40", (g.enforce(SAT), switch_on(f)), (True, False))

    print("\n[Monday 04:43:37 tick puts the switch back; 05:00 tick finds nothing to do]")
    check("04:43:37 switch back on", (g.enforce(TICK), switch_on(f)), (True, True))
    check("05:00 no change", g.enforce(TICK2), False)
    check("not done this week", g.settings(TICK2), {"本周已完成": False})

    print("\n[08:46:03 boot: the garden still rolls over into the new week]")
    n = Notifier()
    engine = type("E", (), {"_garden": g, "_weeklyboss": None, "_annihilation": None})()
    boot_stages._stage_annihilation(engine, n, Log())
    check("a new-week notice goes out", [t for t, _ in n.sent], [texts.NEW_WEEK])
    check("it carries the garden's line", [b for _, b in n.sent], ["鸣潮 · 周常乐园：本周还没做，每趟都会去检查"])
    check("asked again: nothing more", g.maybe_reopen(), "")
    check("switch stays on", switch_on(f), True)

    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    sys.exit(1 if FAILED else 0)


def _part_garden_unified():
    """周常乐园和剿灭、周本一套接口：settings / week_line / maybe_reopen / configure。

用户 2026-09-07：「鸣潮有两个东西，一个是周常乐园（不消耗体力完成），一个是周本
材料（一周三次，要消耗体力）。我希望手机网页界面操作逻辑、中继每周判定他们的
逻辑、推送的通知里应该统一。目前通知是散开的而且没有周常乐园。」

    Formerly test_garden_unified.py.
    """
    import json, sys
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import garden as G
    from ark_relay.core.config import SERVER_TZ


    TMP = tmpdir()
    CFG = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"; CFG.mkdir(parents=True)
    (CFG / "DailyTask.json").write_text(json.dumps({G.KEY: ["Check Weekly Garden"]}), encoding="utf-8")
    def tasks():
        return json.loads((CFG / "DailyTask.json").read_text(encoding="utf-8"))[G.KEY]

    MON = datetime(2026, 9, 7, 8, 48, tzinfo=SERVER_TZ)
    SUN = datetime(2026, 9, 6, 12, 0, tzinfo=SERVER_TZ)
    g = G.GardenGate(TMP / "state", TMP / "automas")

    print("[默认开着、本周没做]")
    check("settings", g.settings(SUN), {"本周已完成": False})
    check("week_line", g.week_line(SUN), "鸣潮 · 周常乐园：本周还没做，每趟都会去检查")

    print("[周日做完 → 记账、摘掉]")
    check("on_success 的话", g.on_success(SUN), "鸣潮 · 周常乐园：本周已完成，暂停检查到下周一")
    check("本周已完成", g.settings(SUN)["本周已完成"], True)
    check("week_line", g.week_line(SUN), "鸣潮 · 周常乐园：本周已完成，暂停检查到下周一")
    check("enforce 摘掉", g.enforce(SUN), True)
    check("母本里没了", G.TASK_NAME in tasks(), False)

    print("[周一开机 → maybe_reopen 清账并给出状态行，enforce 挂回去]")
    check("maybe_reopen", g.maybe_reopen(MON), "鸣潮 · 周常乐园：本周还没做，每趟都会去检查")
    check("再问就不说了", g.maybe_reopen(MON), "")
    check("enforce 挂回去", g.enforce(MON), True)
    check("母本里回来了", G.TASK_NAME in tasks(), True)

    print("[没有总开关：和剿灭一样只显示状态]")
    check("settings 里没有开关", "开" in g.settings(MON), False)
    check("没有 configure", hasattr(g, "configure"), False)


def _part_nest_patch_visible():
    """A refused nest patch must not leave every report saying 「只打落渊南丘」.

「Only Farm These Nests」 is an option **our copy** of NightmareNestTask.py adds;
upstream has no such setting. So when the patch is refused - upstream restructured
the file and the hash no longer matches - nothing reads that value and every nest
gets farmed, all night. The config value is untouched, which is exactly why
tomorrow's plan went on announcing 「只打落渊南丘」: it read the config and never
looked at whether the code that honours it is there.

That breaks a standing instruction (nests: 落渊南丘 only) while every surface says
it is being kept. And the notification could not tell it either: a patch that could
not be applied shared its title with one that went on cleanly.

    Formerly test_nest_patch_visible.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features.okww_patch import okww_overlay
    from ark_relay.features.okww_patch.okww_overlay import nest_patch_present


    def okww(_body):
        """An OK-WW folder; presence is read from the overlay report, not from its files."""
        return tmpdir()


    print("[改动在不在，看 OK-WW 自己写下的那份报告，不看配置也不看源文件]")
    # Since 2026-09-09 the change lives in ok_tasks/ark_overrides.py, so the source file
    # is upstream's own and looking at it would report 「没贴上」 on a healthy machine -
    # which is what tomorrow's plan said that night.

    _real_report = okww_overlay.last_report
    try:
        okww_overlay.last_report = lambda: {"applied": ["NightmareNestTask.find_nest"],
                                            "skipped": [], "error": ""}
        check("绑上了就是在", nest_patch_present(okww(None)), True)
        okww_overlay.last_report = lambda: {
            "applied": [], "error": "",
            "skipped": [{"what": "NightmareNestTask.find_nest", "why": "上游正文变了"}]}
        check("被跳过了就是不在", nest_patch_present(okww(None)), False)
        okww_overlay.last_report = lambda: {"error": "Traceback ..."}
        check("整个文件炸了也是不在", nest_patch_present(okww(None)), False)
        # The file raised after find_nest was bound (audit 2026-10-13, A5): it is bound.
        okww_overlay.last_report = lambda: {"applied": ["NightmareNestTask.find_nest"], "error": "Traceback ..."}
        check("raised after binding find_nest: present", nest_patch_present(okww(None)), True)
        okww_overlay.last_report = lambda: {"applied": ["FarmEchoTask.run"], "error": "Traceback ..."}
        check("raised before binding find_nest: absent", nest_patch_present(okww(None)), False)
        okww_overlay.last_report = lambda: {}
        check("还没有报告时说不知道，不瞎猜", nest_patch_present(okww(None)), None)
    finally:
        okww_overlay.last_report = _real_report
    check("目录是 None 时说不知道", nest_patch_present(None), None)
    check("目录是 None 时说不知道", nest_patch_present(None), None)

    print("\n[补丁没贴上时，明日安排必须改口]")
    import os
    from ark_relay.core import plan
    nest = {"Only Farm These Nests": "落渊南丘"}
    zh = {"Tacet Discord Nest": "残象聚落"}

    # Presence is read from OK-WW's binding report (okww_overlay.last_report), not
    # from the source file. Until 2026-09-14 this block passed only because a stray
    # report file with an error in it sat in the repo's cwd - stub the report here.
    os.environ["ARK_OKWW_DIR"] = str(okww(None))
    okww_overlay.last_report = lambda: {"applied": ["NightmareNestTask.find_nest"], "skipped": []}
    good = plan._okww_nest_bit({}, nest, [], zh)
    if good is None:
        print("  · 这一段的函数名变了，跳过（下面的标题检查照跑）")
    else:
        check("贴上了就照常说只打南丘", "只打落渊南丘" in good, True)
        okww_overlay.last_report = lambda: {
            "applied": [], "skipped": [{"what": "NightmareNestTask.find_nest", "why": "结构变了"}]}
        bad = plan._okww_nest_bit({}, nest, [], zh)
        check("没贴上就说实话", "这一轮不会刷巢穴" in bad, True)
        check("而且点名了本该只打哪", "本该只打落渊南丘" in bad, True)
    okww_overlay.last_report = _real_report
    os.environ.pop("ARK_OKWW_DIR", None)

    print("\n[通知标题要分得出「贴上了」和「贴不上」]")
    check("全都贴上了", texts.patches(3, ["a 已贴上", "b 已贴上", "c 已贴上"]),
          "🩹 OK-WW 补丁（3 条）")
    t = texts.patches(3, ["a 已贴上", "巢穴任务**贴不上了**（上游结构变了）", "c 已贴上"])
    check("有贴不上的就换标题", t.startswith("⚠️"), True)
    check("标题里写清几条没贴上", "1 条没贴上" in t, True)
    check("没传明细时不瞎报", texts.patches(2), "🩹 OK-WW 补丁（2 条）")
    check("写不进去也算没贴上",
          texts.patches(1, ["某补丁 写不进去"]).startswith("⚠️"), True)


def _part_nest_source_pristine():
    """The health check's 「nest source = upstream's own」 item follows OK-WW's updates.

10-10 22:4x the item was red: the machine's working/src/task/NightmareNestTask.py
(11932 bytes, sha1 8e3a251042, 10-04 08:47) was compared byte for byte with the copy
stored in okww_files (08-27, 11138 bytes). The machine's file was upstream's own -
the same bytes as OK-WW v3.7.4 on cnb.cool and on GitHub - so every OK-WW update
turned the item red. It is judged against OK-WW's own git checkout (repo/); the stored
copy itself was removed 2026-10-12 with the code that restored it.

    Formerly test_nest_source_pristine.py.
    """
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay as O


    UPSTREAM = b"class NightmareNestTask:\n    def run(self):\n        pass\n"
    NEWER = UPSTREAM + b"\n# a later OK-WW release\n"
    WORK = ("data", "apps", "ok-ww", "working", "src", "task")
    REPO = ("data", "apps", "ok-ww", "repo", "src", "task")


    def machine(work, repo=None):
        root = Path(tempfile.mkdtemp())
        for parts, data in ((WORK, work), (REPO, repo)):
            if data is not None:
                f = root.joinpath(*parts, "NightmareNestTask.py")
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
        return root


    print("[the running copy is OK-WW's own checkout: green, whatever version]")
    ok, why = O.nest_source_pristine(machine(NEWER, NEWER))
    check("ok", ok, True)
    check("says size and sha1", f"{len(NEWER)} 字节" in why and "sha1" in why, True)
    check("ok with CRLF on the machine",
          O.nest_source_pristine(machine(UPSTREAM.replace(b"\n", b"\r\n"), UPSTREAM))[0], True)

    print("\n[someone edited the running copy: red]")
    ok, why = O.nest_source_pristine(machine(NEWER + b"x = 1\n", NEWER))
    check("not ok", ok, False)
    check("says it differs from OK-WW's own copy", "有人改过" in why, True)

    print("\n[the running copy missing: red]")
    ok, why = O.nest_source_pristine(machine(None, NEWER))
    check("not ok", ok, False)
    check("says it cannot read it", "读不了运行的那份" in why, True)

    print("\n[OK-WW's own checkout missing: red, says it cannot tell]")
    ok, why = O.nest_source_pristine(machine(NEWER))
    check("not ok", ok, False)
    check("says the checkout is unreadable", "git 副本读不了" in why, True)


def _part_nest_strings_pinned():
    """The two nest sentences the relay reads are written by our own override.

outcome.py and collector_okww.py decide whether the nests were farmed by looking
for two sentences in OK-WW's log (the "all full, skipping" one and the "spot not
found in the list" one). Both are printed by
relay/ark_relay/features/okww_patch/okww_files/ark_overrides.tasks.py - our file, not
upstream's (until 2026-09-09 the whole-file NightmareNestTask replacement printed them).
Nothing tied the two sides together: change a character in the override and 99 tests
stay green while the daily report starts saying, every day, that the nests were opened
and never fought.

    Formerly test_nest_strings_pinned.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww, outcome


    patched = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "okww_patch" / "okww_files"
               / "ark_overrides.tasks.py").read_text(encoding="utf-8")

    print("[读的那两句话，写的一侧必须还在补丁源码里]")
    check("「已打满」在补丁里", outcome._NEST_ALL_FULL in patched, True)
    check("「没找到点位」在补丁里", outcome._NEST_NOT_FOUND in patched, True)
    check("collector 那份正则也匹配补丁里的句子",
          bool(collector_okww._OKWW_NEST_FULL.search(patched)), True)

    print("\n[两个读的模块用的是同一句话，不许各写一份]")
    check("outcome 与 collector 一致",
          bool(collector_okww._OKWW_NEST_FULL.search(outcome._NEST_ALL_FULL)), True)


def _part_wuwa_bulletin():
    """Wuthering Waves banners: how the bulletin and the notices are read (2026-10-13 audit).

* Collaboration and memory banners say 「角色联动唤取」 / 「角色忆旅唤取」, not only
  「角色活动唤取」; the pool-name and notice-title patterns took only 活动.
* A bulletin that yields no debut (title or 「全新角色」 format changed) dropped every
  running pool without a log line; it now warns and reports them all.
* Once both halves are out, the 「下期」 line listed every wiki entry with the
  previewed badge, including a character whose own banner was running (锁暝,
  2026-10-22 audit run5.py); running and current-debut names are now left out.
  With no debut read (the fallback above), a name the bulletin quotes is left out
  too, and with no bulletin text the line is not said at all (review run6).

    Formerly test_wuwa_bulletin.py.
    """
    import logging
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ark_relay.features.banners.banners as _b
    from ark_relay.features.banners import wuwa as W


    print("[collaboration and memory banners: 联动 / 忆旅 as well as 活动]")
    for kind in ("活动", "联动", "忆旅"):
        body = f"<p>全新角色</p><p>5星共鸣者「某人」</p><p>※可通过[某池]角色{kind}唤取获得</p><p>全新武器</p>"
        check(f"bulletin pool name, 角色{kind}唤取", W.parse_wuwa_preview(body), [("某人", "某池")])
        nb = W.parse_wuwa_notice_banners({"recommend": [{
            "tabTitle": f"[某池]角色{kind}唤取",
            "content": "5星角色「某人」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}]})
        check(f"notice banner, 角色{kind}唤取", [(x.name, x.chars) for x in nb], [("某池", ("某人",))])
    check("a weapon banner is still not a character banner",
          W.parse_wuwa_notice_banners({"recommend": [{
              "tabTitle": "「碎骨」武器联动唤取",
              "content": "5星武器「某刀」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}]}), [])


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.recs = []

        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage()))


    def offline(url, *a, **k):
        raise OSError(f"offline: {url}")


    def home(*tabs):
        """A wiki homepage with one character tab per (banner, entry id, start, end)."""
        return {"code": 200, "data": {"contentJson": {"sideModules": [{
            "title": "角色活动唤取",
            "content": {"tabs": [{"name": n, "countDown": {"dateRange": [a, z]},
                                  "imgs": [{"linkConfig": {"entryId": e}}]} for n, e, a, z in tabs]}}]}}}


    def run_wuwa(now, page, notice, names, catalogue=None):
        """_wuwa against fakes; (banners, next, notes, WARNING messages)."""
        def fake(url, *a, **k):
            if url == W._WW_NOTICE:
                return notice
            if url.endswith("/wiki/core/homepage/getPage"):
                return page
            if url.endswith("/getEntryDetail"):
                eid = dict(x.split("=") for x in a[1].decode().split("&"))["id"]
                return {"code": 200, "data": {"name": names[eid]}}
            if url.endswith("/wiki/core/catalogue/item/getPage"):
                return {"code": 200, "data": {"results": {"records": catalogue or []}}}
            raise OSError(f"offline: {url}")
        g = Grab()
        _b.log.addHandler(g)
        real = _b._json, _b._text
        _b._json, _b._text = fake, offline
        notes: dict = {}
        try:
            got, nxt = _b._wuwa(now, notes=notes, trace=_b.Trace.new())
        finally:
            _b._json, _b._text = real
            _b.log.removeHandler(g)
        return got, nxt, notes, [m for lv, m in g.recs if lv == logging.WARNING]


    print("[no debut read from a fetched bulletin: warn, and report the running pools]")
    NOW = datetime(2026, 10, 13, 12, 0)
    page = home(("某某之池", "1", "2026-10-01 11:00", "2026-10-22 09:59"))
    renamed = {"game": [{"tabTitle": "3.7版本更新公告", "content": "<p>全新角色</p><p>5星共鸣者「某人」</p>"}]}
    got, _n, _notes, warns = run_wuwa(NOW, page, renamed, {"1": "某人"})
    check("bulletin title changed: the running pool is still reported", [b.name for b in got], ["某某之池"])
    check("…with a WARNING naming why", [m for m in warns if "读不出这一版的新角色" in m and "版本内容说明" in m] != [], True)
    reshaped = {"game": [{"tabTitle": "3.7版本内容说明", "content": "<p>全新角色</p><p>五星角色：某人</p><p>全新武器</p>"}]}
    got, _n, _notes, warns = run_wuwa(NOW, page, reshaped, {"1": "某人"})
    check("全新角色 format changed: the running pool is still reported", [b.name for b in got], ["某某之池"])
    check("…with a WARNING", [m for m in warns if "读不出这一版的新角色" in m and "写法变了" in m] != [], True)
    fine = {"game": [{"tabTitle": "3.7版本内容说明",
                      "content": "<p>全新角色</p><p>5星共鸣者「别人」</p><p>※可通过[别的池]角色活动唤取获得</p><p>全新武器</p>"}]}
    got, _n, _notes, warns = run_wuwa(NOW, page, fine, {"1": "某人"})
    check("a readable debut list still drops a rerun", [b.name for b in got], [])
    check("…without that WARNING", [m for m in warns if "读不出这一版的新角色" in m], [])

    print("[the next version's previewed characters leave out who is running now]")
    LATE = datetime(2026, 10, 22, 21, 30)
    both = {"game": [{"tabTitle": "3.7版本内容说明",
                      "content": "<p>全新角色</p><p>5星共鸣者「心」</p><p>※可通过[但愿长圆如此夜]角色活动唤取获得</p>"
                                 "<p>5星共鸣者「锁暝」</p><p>※可通过[余心所向九死未悔]角色活动唤取获得</p><p>全新武器</p>"}]}
    second = home(("余心所向九死未悔", "S", "2026-10-22 10:00", "2026-11-11 11:59"))


    def badge(name, a, z):
        return {"name": name, "content": {"showTeaserIcon": True, "showTeaserIconNum": 2,
                                          "teaserDateRange": [a, z]}}


    cat = [badge("锁暝", "2026-09-03 00:00:00", "2027-09-03 00:00:00"),
           badge("新来的", "2026-10-20 00:00:00", "2026-11-12 00:00:00")]
    got, _n, notes, _w = run_wuwa(LATE, second, both, {"S": "锁暝"}, cat)
    check("the running debut is reported", [b.name for b in got], ["余心所向九死未悔"])
    check("the 下期 note names only the one not out yet",
          notes.get("鸣潮", ""), "官方已预告下一版新角色：新来的")

    print("[no debut read (the fallback): this version's second half is not the next version's]")
    # 2026-10-13 review run6 (live data with the debut lines' star prefix rewritten):
    # first half running, the debut list unreadable, and this version's second-half
    # character was announced as the next version's.
    first = home(("但愿长圆如此夜", "X", "2026-10-01 11:00", "2026-10-22 09:59"))
    five = {"game": [{"tabTitle": "3.7版本内容说明",
                      "content": "<p>全新角色</p><p>五星共鸣者「心」</p><p>※可通过[但愿长圆如此夜]角色活动唤取获得</p>"
                                 "<p>五星共鸣者「锁暝」</p><p>※可通过[余心所向九死未悔]角色活动唤取获得</p><p>全新武器</p>"}]}
    cat13 = [badge("锁暝", "2026-09-03 00:00:00", "2027-09-03 00:00:00"),
             badge("新来的", "2026-10-01 00:00:00", "2026-11-12 00:00:00")]
    got, _n, notes, warns = run_wuwa(NOW, first, five, {"X": "心"}, cat13)
    check("fixture: no debut read, the running pool still reported",
          ([b.name for b in got], any("读不出这一版的新角色" in m for m in warns)), (["但愿长圆如此夜"], True))
    check("the bulletin's own second-half character is not called next version's",
          notes.get("鸣潮", ""), "官方已预告下一版新角色：新来的")
    untitled = {"game": [{"tabTitle": "3.7版本更新公告", "content": "<p>五星共鸣者「锁暝」</p>"}]}
    got, _n, notes, _w = run_wuwa(NOW, first, untitled, {"X": "心"}, cat13)
    check("no bulletin text at all: no 「next version」 claim, since none can be told apart",
          "下一版" in notes.get("鸣潮", ""), False)


def _part_wuwa_middot():
    """A debut whose name has a middle dot is not dropped as a rerun.

The Kuro wiki spells 秧秧·玄翎 with U+00B7 (wuwa_catalogue_2026-09-12.json); the
in-game notice spells it 秧秧・玄翎 with U+30FB (maint/ww_notice.json). _wuwa keeps
only the running pools whose character is in the bulletin's 「全新角色」 section,
comparing the strings as they are, so the running debut was filtered out as a
rerun and its line vanished without a warning. Runs _wuwa itself with fakes.

    Formerly test_wuwa_middot.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ark_relay.features.banners.banners as _b
    from ark_relay.features.banners import wuwa as W


    WIKI = "秧秧·玄翎"       # U+00B7, as the wiki writes it
    GAME = "秧秧・玄翎"       # U+30FB, as the game notice writes it
    NOW = datetime(2026, 10, 13, 12, 0)

    home = {"code": 200, "data": {"contentJson": {"sideModules": [{
        "title": "角色活动唤取",
        "content": {"tabs": [{"name": "某某之池",
                              "countDown": {"dateRange": ["2026-10-01 11:00", "2026-10-22 09:59"]},
                              "imgs": [{"linkConfig": {"entryId": 777}}]}]}}]}}}
    notice = {
        "game": [{"tabTitle": "3.7版本内容说明",
                  "content": f"<p>全新角色</p><p>5星共鸣者「{GAME}」</p>"
                             "<p>※可通过[某某之池]角色活动唤取获得</p><p>全新武器</p>"}],
        "recommend": [{"tabTitle": "[某某之池]角色活动唤取",
                       "content": f"5星角色「{GAME}」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}],
    }


    def fake_json(url, *a, **k):
        if url == W._WW_NOTICE:
            return notice
        if url.endswith("/wiki/core/homepage/getPage"):
            return home
        if url.endswith("/wiki/core/catalogue/item/getEntryDetail"):
            return {"code": 200, "data": {"name": WIKI}}
        if url.endswith("/wiki/core/catalogue/item/getPage"):
            return {"code": 200, "data": {"results": {"records": []}}}
        raise OSError(f"offline: {url}")


    def offline(url, *a, **k):
        raise OSError(f"offline: {url}")


    print("[parsers fold every middle dot to U+00B7]")
    check("bulletin debut", W.parse_wuwa_preview(notice["game"][0]["content"]), [(WIKI, "某某之池")])
    check("notice banner", W.parse_wuwa_notice_banners(notice)[0].chars, (WIKI,))
    for dot in ("·", "・", "･", "•", "‧"):
        check(f"U+{ord(dot):04X} folds", W._one_dot(f"秧秧{dot}玄翎"), WIKI)

    print("[_wuwa keeps the running debut]")
    real = _b._json, _b._text
    _b._json, _b._text = fake_json, offline
    try:
        tr = _b.Trace.new()
        got, _nxt = _b._wuwa(NOW, notes={}, trace=tr)
    finally:
        _b._json, _b._text = real
    check("the running debut is reported", [(b.name, b.chars) for b in got], [("某某之池", (WIKI,))])
    check("the game notice is matched to it",
          any("游戏公告" in x and "某某之池" in x for x in tr.sources), True)


def _part_wuwa_update_close():
    """Closing WuWa for real: the game, OK-WW and the Kuro launcher (preupdate_okww._okww_close).

The launcher runs as launcher_main.exe in a version folder
(D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe), which the old full-path match on
…\\Wuthering Waves\\launcher.exe missed (2026-09-30). And 「已关掉」 was said without
looking: taskkill from session 0 does not reach the game under its anti-cheat
(echofarm._kill_on_desktop, 2026-09-09), and its return code was never read.

The relay's own WuWa client update through the launcher (update_wuwa, whose ready
words and timeouts were tested here) went on 2026-10-12: AUTO-MAS updates the
client before an OK-WW run (item 10b).

    Formerly test_wuwa_update_close.py.
    """
    import json
    import subprocess
    from pathlib import Path, PureWindowsPath

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.echofarm import echofarm
    from ark_relay.features.preupdate import preupdate_okww as pk


    nosleep = lambda s: None  # noqa: E731

    print("[启动器进程：按启动器目录前缀认 launcher.exe 和 launcher_main.exe]")
    root = PureWindowsPath("D:/Wuthering Waves")
    check("版本子目录里的 launcher_main.exe", pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe", root), True)
    check("入口壳 launcher.exe", pk._is_wuwa_launcher("D:\\Wuthering Waves\\launcher.exe", root), True)
    check("斜杠和大小写不影响", pk._is_wuwa_launcher("d:/wuthering waves/2.6.5.0/LAUNCHER_MAIN.EXE", root), True)
    check("别的目录同名不算", pk._is_wuwa_launcher("C:\\Other\\launcher_main.exe", root), False)
    check("前缀要到目录边界（Wuthering Waves Game 不算）",
          pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher.exe", root), False)
    check("同目录别的程序不算", pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\Client.exe", root), False)
    check("没有目录时按 \\Wuthering Waves\\ 这一段认 launcher_main.exe",
          pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe"), True)
    check("没有目录时游戏本体目录不算", pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher_main.exe"), False)

    print("[taskkill 看返回码：失败的不算关掉]")
    PROCS = [{"ProcessId": 4242, "ExecutablePath": "D:\\Wuthering Waves\\launcher.exe"},
             {"ProcessId": 4343, "ExecutablePath": "D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe"},
             {"ProcessId": 5151, "ExecutablePath": "C:\\Program Files\\Other\\launcher_main.exe"}]


    class R:
        def __init__(self, rc=0, out=b""):
            self.returncode, self.stdout, self.stderr = rc, out, b"ERROR: Access is denied."


    calls = []
    real_run = subprocess.run


    def fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        if any("launcher_main.exe" in str(x) and "CimInstance" in str(x) for x in cmd):
            return R(0, json.dumps(PROCS).encode())
        if cmd[:3] == ["taskkill", "/F", "/PID"]:
            return R(0 if cmd[3] == "4242" else 1)
        return R()


    subprocess.run = fake_run
    try:
        stopped = pk._stop_wuwa_launcher(root)
    finally:
        subprocess.run = real_run
    kills = [c for c in calls if c[:1] == ["taskkill"]]
    check("两个都试了（按 PID）", [c[3] for c in kills], ["4242", "4343"])
    check("只记返回 0 的那个", stopped, [4242])
    check("别处的不碰", any("5151" in c for c in kills), False)
    check("列进程一次查两个名字", sum(1 for c in calls if any("Name='launcher_main.exe'" in str(x) for x in c)), 1)

    print("[_okww_close：关完复查，剩下的从桌面会话再关一次，再说实话]")
    bat = tmpdir() / "ark-okww-stop.bat"
    echofarm.STOP_BAT = str(bat)          # never the repo cwd
    alive = {"game": ["Client-Win64-Shipping.exe"], "procs": [PROCS[1]]}
    real_alive = echofarm.game_alive
    echofarm.game_alive = lambda timeout=None: list(alive["game"])
    calls.clear()


    def run2(cmd, *a, **k):
        calls.append(list(cmd))
        if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
            return R(0, json.dumps(alive["procs"]).encode())
        if cmd[:1] == ["taskkill"]:
            return R(1)                   # session 0 cannot reach it
        if cmd[:2] == ["schtasks", "/run"]:
            alive["game"], alive["procs"] = [], []    # the desktop door worked
        return R()


    subprocess.run = run2
    try:
        left = pk._okww_close(sleep=nosleep, launcher_root=root)
    finally:
        subprocess.run = real_run
    check("桌面那边关掉了 → []", left, [])
    text = bat.read_text(encoding="utf-8")
    check("bat 里按 PID 关启动器", "taskkill /F /PID 4343" in text, True)
    check("bat 里照旧按名字关游戏", 'taskkill /F /IM "Client-Win64-Shipping.exe"' in text, True)
    check("走了计划任务", any(c[:2] == ["schtasks", "/run"] for c in calls), True)

    alive.update(game=["Client-Win64-Shipping.exe"], procs=[PROCS[1]])


    def run3(cmd, *a, **k):
        calls.append(list(cmd))
        if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
            return R(0, json.dumps(alive["procs"]).encode())
        return R(1) if cmd[:1] == ["taskkill"] else R()


    subprocess.run = run3
    try:
        left = pk._okww_close(sleep=nosleep, launcher_root=root)
    finally:
        subprocess.run = real_run
    check("都没关掉 → 点名", left, ["Client-Win64-Shipping.exe", "launcher_main.exe"])

    # Bounded as echofarm.stop_okww (audit 11-08 A-22: run_okww now waits on this before it puts
    # the switch back): a look that takes long uses the budget up and the looks stop.
    clock = [0.0]


    def run4(cmd, *a, **k):
        calls.append(list(cmd))
        if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
            clock[0] += 20                # a slow WMI answer
            return R(0, json.dumps(alive["procs"]).encode())
        return R(1) if cmd[:1] == ["taskkill"] else R()


    subprocess.run = run4
    looks = []
    real_left = pk._okww_left
    pk._okww_left = lambda r, t=None: looks.append(t) or real_left(r, t)
    try:
        left = pk._okww_close(sleep=nosleep, launcher_root=root, clock=lambda: clock[0])
    finally:
        subprocess.run, pk._okww_left = real_run, real_left
    check("限时：用完 STOP_OKWW_SECONDS 就不再看（不是看满十次）", 1 < len(looks) < 10, True)
    check("……每次给 PowerShell 的时间不超过剩下的", all(t is not None and t <= echofarm.STOP_OKWW_SECONDS for t in looks), True)
    check("……照实说还在", left, ["Client-Win64-Shipping.exe", "launcher_main.exe"])

    alive.update(game=[], procs=[])
    subprocess.run = lambda cmd, *a, **k: (_ for _ in ()).throw(OSError("no pwsh")) \
        if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd) else R()
    try:
        left, pids = pk._okww_left(root)
    finally:
        subprocess.run = real_run
    check("启动器列表读不到 → 说读不到，不当没了", left, ["鸣潮启动器（查不到它还开没开着）"])
    check("…也没有 PID 可关", pids, [])

    print("[启动器列表：pwsh 里出错（没输出）不当成「启动器已关」（审计 11-08 A-22）]")
    for label, answer, want in (("返回码不是 0", R(1, b""), None),
                                ("返回码 0、没输出、stderr 有错", R(0, b""), None),
                                ("返回码 0、没输出、stderr 也空：真的一个都没有", None, []),
                                ("返回码 0、有列表", R(0, json.dumps(PROCS[:1]).encode()), [(4242, PROCS[0]["ExecutablePath"])])):
        if answer is None:
            answer = R(0, b"")
            answer.stderr = b""
        subprocess.run = lambda cmd, *a, _r=answer, **k: _r
        try:
            check(label, pk._wuwa_launcher_procs(root), want)
        finally:
            subprocess.run = real_run
    echofarm.game_alive = real_alive


def _part_boss_table_matches():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import wuwa_boss

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r} vs {want!r}" if not ok else f"  ✓ {label}")
        if not ok:
            fails.append(label)


    # web/schema.js `const BOSSES` as of 2026-11-17 (git show 1c8b5828:web/schema.js).
    PAGE = [(1, "天傀劫煞"), (2, "万囿牢·朽躯"), (3, "梦魇亚当·重锤"), (4, "无铭探索者")]
    check("手机那份和中继一字不差", PAGE, wuwa_boss.choices())

    print("\n[没登记的位置只说「第 N 个」，不许猜]")
    check("登记过的给名字", wuwa_boss.label(1), "天傀劫煞")
    check("没登记的说第几个", wuwa_boss.label(9), "第 9 个")
    check("不是数字也不崩", wuwa_boss.label("x"), "第 x 个")
    check("no VERIFIED constant (nothing read it)", hasattr(wuwa_boss, "VERIFIED"), False)
    check("天傀劫煞 is listed under 瑝珑·梦州 (2026-09-30 re-read)", wuwa_boss.BOSSES[1], ("天傀劫煞", "瑝珑·梦州"))

    print("\n[状态包里不许再带这张表——放进去当天就撑爆了 ntfy 的上限]")
    phone = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "phone" / "phone.py").read_text(encoding="utf-8")
    check("phone.py 不发 bosses", '"bosses"' in phone, False)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_annihilation_no_progress, _part_annihilation_not_healed_by_routine, _part_annihilation_status, _part_annihilation_unreadable_none, _part_annihilation_skipped_checked_on_skland, _part_annihilation_day_rechecked, _part_sanity_plan_both_on, _part_sanity_plan_master, _part_sanity_plan_reward_names, _part_sanity_plan_weekday, _part_sanity_span, _part_weeklyboss_count, _part_weeklyboss_cycle, _part_weeklyboss_reopen, _part_garden_gate, _part_garden_rollover_after_tick, _part_garden_unified, _part_nest_patch_visible, _part_nest_source_pristine, _part_nest_strings_pinned, _part_wuwa_bulletin, _part_wuwa_middot, _part_wuwa_update_close, _part_boss_table_matches]))
