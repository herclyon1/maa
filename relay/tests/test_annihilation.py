"""Annihilation's weekly gate: no progress, not healed by a routine run, its status, an unreadable switch.

One part per former file, each run on its own (tests/_parts.py): test_annihilation_no_progress.py, test_annihilation_not_healed_by_routine.py, test_annihilation_status.py, test_annihilation_unreadable_none.py.
"""
from __future__ import annotations

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

    FX = Path(__file__).parent / "fixtures" / "maa-annihilation-2026-09-21" / "MAA-17-30-02.log"


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
    REAL0907 = Path(__file__).parent / "replay" / "2026-09-07" / "arknights" / "MAA-05-00-00.log"
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
    LEDGER = Path(__file__).parent / "fixtures" / "ledger-2026-09-14" / "ledger.jsonl"
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

    AUTOMAS_FX = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11" / "config"
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


if __name__ == "__main__":
    sys.exit(run_parts([_part_annihilation_no_progress, _part_annihilation_not_healed_by_routine, _part_annihilation_status, _part_annihilation_unreadable_none]))
