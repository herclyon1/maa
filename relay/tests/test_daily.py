"""The daily report: format, partial failures, range prefixes and the technical log.

One part per former file, each run on its own (tests/_parts.py): test_daily_format.py, test_daily_partial_failure.py, test_daily_range_prefix.py, test_daily_techlog.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tmp  # loaded before the parts: its atexit cleanup and env default stay
from _parts import run_parts

_BEFORE_THE_PARTS = (_tmp,)


def _part_daily_format():
    """日报三家一个语义模板，以 MAA 为样板（用户 2026-09-02）：

  做了　刷（什么）×次数
  消耗　理智 N，吃药 N（鸣潮：波片 N，备用体力 N；终末地：理智 N，加强剂 N）
  产出　这次刷本的掉落
  剩余　理智 N/上限，回满时刻
  备注　额外任务

鸣潮和终末地的数字全部从它们的真实日志里算出来（夹具是 09-02 / 09-01 实录）。

    Formerly test_daily_format.py.
    """
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir
    from ark_relay.core import collector
    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ

    FX = Path(__file__).parent / "fixtures"
    fails = []
    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
        if not ok:
            fails.append(label)

    def ent(run_id, script, hh, mm, dur, ok=True, **kw):
        st = datetime(2026, 9, 2, hh, mm, tzinfo=SERVER_TZ)
        e = {"run_id": run_id, "script": script, "user": "u", "ok": ok,
             "started": st.isoformat(), "finished": (st + timedelta(minutes=dur)).isoformat(),
             "duration_known": True, "transitional": False, "failed_tasks": [] if ok else ["x"],
             "raw": {}, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}
        e.update(kw)
        return e

    print("[鸣潮：从真实日志算出来]")
    ww = collector.parse_okww_log(FX / "okww_sim_2026-09-02.log")
    check("刷的本", ww.get("okww_farm"), "模拟领域·贝币")
    check("产出类别", ww.get("okww_farm_reward"), "贝币")
    check("进本 2 局", ww.get("okww_runs"), 2)
    check("波片 168→88→8 花了 160", ww.get("okww_stamina_spent"), 160)
    check("备用体力没动", ww.get("okww_backup_spent"), None)
    check("进了游戏就不是 unreachable", ww.get("okww_unreachable"), None)
    bad = tmpdir() / "bad.log"; bad.write_text("2026-09-02 09:18:58,791 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮 is not connected\n", encoding="utf-8")
    check("等不到窗口且一局没开 → unreachable", collector.parse_okww_log(bad).get("okww_unreachable"), True)
    check("剩 8", ww.get("okww_stamina_left"), 8)
    check("两局都是双倍", ww.get("okww_runs_double"), 2)
    check("产出按满难度算：2×84000×2", ww.get("okww_farm_drops"), {"贝币": 336000})
    ww["sanity_full_at"] = "2026-09-03 08:53"

    print("[终末地：从真实日志算出来]")
    ef = collector.parse_maaend_log(FX / "maaend_full_2026-09-01.log")
    check("刷本任务", ef.get("maaend_farm"), "基质刷取")
    check("地点", ef.get("maaend_farm_place"), "枢纽区")
    check("次数", ef.get("maaend_farm_runs"), 2)
    check("理智 234→154→74 花了 160", ef.get("maaend_sanity_spent"), 160)
    check("刷本掉落只算基质", ef.get("maaend_farm_drops"), {"无暇基质": 6, "高纯基质": 4})
    check("没吃加强剂", ef.get("maaend_medicine"), None)
    check("剩余理智 74/360", (ef.get("sanity"), ef.get("sanity_cap")), (74, 360))
    check("失败清单为空", ef.get("tasks_failed"), None)

    print("[三家五行，同一语义]")
    entries = [
        ent("maa", "MAA", 9, 0, 17, raw={"stages": ["1-7"], "run_times": 10, "sanity_spent": 120,
                                           "medicine_used": 1},
            drops={"龙门币": 1440, "固源岩": 25}, recruits={"3★": 2}, sanity=0,
            sanity_full_at="理智将在 2026-09-03 06:07 回满"),
        ent("ww", "OK-WW", 9, 28, 13, raw=ww),
        ent("ef", "MaaEnd", 9, 42, 25, raw=ef, sanity=ef["sanity"], sanity_full_at="2026-09-02 21:00"),
        ent("bad", "OK-WW", 21, 30, 5, ok=False, failed_tasks=["OK-WW 流程产生错误"]),
    ]
    title, body = core.format_daily("2026-09-02", entries)
    print(body)
    blocks = [b for b in body.split("\n\n") if b.strip()]
    rows = lambda blk: blk.splitlines()[1:]  # noqa: E731
    check("MAA", rows(blocks[0]), [
        "· 做了　刷 1-7 ×10",
        "· 消耗　理智 120，吃药 1",
        "· 产出　龙门币×1440 固源岩×25",
        "· 剩余　理智 0，次日 06:07 回满（东京 07:07）",
        "· 备注　公招 3★×2"])
    check("鸣潮", rows(blocks[1]), [
        "· 做了　刷 模拟领域·贝币 ×2（双倍）",
        "· 消耗　波片 160，备用体力 0",
        "· 产出　贝币×336000",
        "· 剩余　波片 8/240，备用 0，次日 08:53 回满（东京 09:53）",
        "· 备注　残象聚落（已刷满）；周本（已完成，本周已领满）"])
    check("终末地", rows(blocks[2]), [
        "· 做了　刷 基质刷取·枢纽区 ×2",
        "· 消耗　理智 160，加强剂 0",
        "· 产出　无暇基质×6 高纯基质×4",
        "· 剩余　理智 74/360，本日 21:00 回满（东京 22:00）",
        # 2026-10-05 rule: a task counts as done only with something from the game in
        # the log (or a task-end picture); this log has nothing but 任务开始/任务完成
        # for these four, so they are named as unverified, not counted.
        "· 备注　日常 1-5 项完成；没证据，不算完成（只有程序自己说做完了）：赠送干员礼物、装备制造、拜访好友、自动采集"])
    # 2026-10-11 (验收): a failure with nothing to show is one line saying why, no rows,
    # and names the game, not the tool.
    check("失败的只有一行，说清为什么", blocks[3], "❌ 鸣潮 21:30–21:35（东京 22:30–22:35）没跑成（鸣潮 流程产生错误）")
    check("「体力不够再开一局」不再出现", "体力不够" in body, False)
    foot = core.daily_footnote(entries)
    check("名单当注释放最末（只列有证据的）", foot, "———————\n日常：1.基建任务 2.信用点购物 3.应急理智加强剂 4.选剑演武 5.日常奖励领取")
    check("标题不说全绿，点名没证据的项数", title.endswith("终末地 4 项没证据 ⚠️"), True)
    check("没有终末地成功记录就没有注释", core.daily_footnote(entries[:2]), "")
    # 作战关掉的那一趟：不能五行全横杠，也不能把「没读过理智」印成「理智 0」。
    # 2026-09-04 补跑就是这个形状：做了/消耗/产出/备注 四个横杠 + 一句「剩余 理智 0」，
    # 而账号里明明还有理智——那个 0 是 MAA 没读时的默认值，不是余量。
    _nf = {"script": "MAA", "ok": True, "sanity": 0,
           "started": "2026-09-04T12:41:00+08:00", "finished": "2026-09-04T12:52:00+08:00",
           "raw": {}, "drops": {}, "recruits": {}}
    _blk = "\n".join(core._block(_nf, datetime.fromisoformat(_nf["finished"])))
    check("作战关掉时说清做了什么", "只做日常" in _blk, True)
    check("没读过理智不印成理智 0", "理智 0" in _blk, False)
    # 真打完把理智花到 0 的，那个 0 要照印
    _f = dict(_nf, raw={"stages": ["1-7"], "sanity_spent": 120})
    _blk2 = "\n".join(core._block(_f, datetime.fromisoformat(_f["finished"])))
    check("真刷到 0 要照印", "理智 0" in _blk2, True)

    print("\n[不是采集日的那条自动采集记录不列出来（2026-09-13 周日 10:02→10:03）]")
    skip = ent("2026-09-13/endfield/MaaEnd-06-02-49", "MaaEnd", 10, 2, 1, True,
              raw={"tasks_done": ["自动采集", "结束进程"], "maaend_collect_skipped": "周日"})
    real = ent("2026-09-13/endfield/MaaEnd-05-36-46", "MaaEnd", 9, 37, 25, True,
              raw={"tasks_done": ["赠送干员礼物", "装备制造", "拜访好友"],
                   "tasks_evidence": {"赠送干员礼物": "获得 信用 ×400", "装备制造": "获得 嵌晶玉 ×25"},
                   "tasks_shot": ["拜访好友"]})
    t2, b2 = core.format_daily("2026-09-13", [real, skip])
    check("日报只有一条终末地", b2.count("终末地　"), 1)
    check("没有那条 0 分钟的", "10:02→10:03" in b2, False)
    check("标题还是全绿", "全绿" in t2, True)
    walked = ent("2026-09-14/endfield/MaaEnd-06-02-49", "MaaEnd", 10, 2, 30, True,
                raw={"tasks_done": ["自动采集", "结束进程"], "maaend_collect_total": 17, "maaend_collect_done": 17})
    t3, b3 = core.format_daily("2026-09-14", [walked])
    check("真走了路线的那条照常列", "自动采集 17/17 条走通" in b3, True)

    print("\n[剿灭理智不够连试三次：一行（2026-09-14 真实账本）]")
    a1 = ent("2026-09-14/arknights/MAA-05-00-01", "MAA", 9, 0, 2, False, failed_tasks=["MAA 部分任务执行失败"],
             raw={"annihilation": True, "maa_sanity_short": {"have": 17, "cost": 25}})
    a2 = ent("2026-09-14/arknights/MAA-05-02-33", "MAA", 9, 3, 1, False, failed_tasks=["MAA 部分任务执行失败"],
             raw={"annihilation": True, "maa_sanity_short": {"have": 17, "cost": 25}})
    a3 = ent("2026-09-14/arknights/MAA-05-04-50", "MAA", 9, 5, 1, False, failed_tasks=["MAA 部分任务执行失败"],
             raw={"annihilation": True, "maa_sanity_short": {"have": 17, "cost": 25}})
    daily = ent("2026-09-14/arknights/MAA-05-07-00", "MAA", 9, 7, 11, True, raw={"tasks_done": ["基建换班"]})
    t4, b4 = core.format_daily("2026-09-14", [a1, a2, a3, daily])
    check("标题全绿带说明", "全绿 ✅（有一关理智不够没打）" in t4, True)
    check("三次合成一行", b4.count("剿灭检查"), 1)
    check("写明连试 3 次", "连试 3 次" in b4, True)
    check("时间跨到最后一次", "09:00→09:06" in b4, True)
    check("备注写理智数", "理智 17 不够这关要的 25" in b4, True)
    check("日常那趟单独一行", b4.count("明日方舟　"), 1)

    print("\n[audit 11-08 C-02: a task left unjudged (MaaEnd's own record unread once) keeps the title off 全绿]")
    from ark_relay.core import ledger_report as _lr
    _e = {"run_id": "2026-11-08/endfield/MaaEnd-05-30-00", "script": "MaaEnd", "user": "endfield", "ok": True,
          "started": "2026-11-08T09:30:00+08:00", "finished": "2026-11-08T10:20:00+08:00", "failed_tasks": [],
          "raw": {"tasks_done": ["赠送干员礼物", "日常奖励领取"], "tasks_trail_miss": 1,
                  "tasks_trail": {"赠送干员礼物": {"found": False, "unread": True}},
                  "tasks_evidence": {"日常奖励领取": "获得 x"}}}
    check("unjudged this day", _lr.day_unjudged_items([_e]), ["赠送干员礼物"])
    _t, _ = _lr.format_daily("2026-11-08", [_e])
    check("title says 待核, not 全绿", ("待核" in _t, "全绿" in _t), (True, False))
    _e2 = dict(_e, run_id="2026-11-08/endfield/MaaEnd-13-30-00", started="2026-11-08T17:30:00+08:00",
               raw={"tasks_done": ["赠送干员礼物"], "tasks_trail_miss": 0,
                    "tasks_trail": {"赠送干员礼物": {"found": True, "ok": True}}})
    check("another run of the day backed it: not 待核", _lr.day_unjudged_items([_e, _e2]), [])

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_daily_partial_failure():
    """A run that failed one task still has to report the nineteen it finished.

Real data, 2026-09-09. Endfield ran for 1h20m: it farmed 基质 18 times, spent 1422
sanity, collected the whole daily and the pass rewards, and 据点交易 failed. AUTO-MAS
retried that one step two minutes later and it worked.

What the user received was a red run carrying one line, 「失败于：据点交易」, and a
green two-minute run with four 「—」 rows and 「日常 1-1 项完成」. Everything the long
run did was thrown away by the renderer, and there was no way to tell the day had
in fact gone fine. His words: 「这终末地通知就是一坨屎吧」.

    Formerly test_daily_partial_failure.py.
    """
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger as core

    fails = []


    def check(label, got, want=True):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
        if not ok:
            fails.append(label)


    entries = json.loads((Path(__file__).parent / "fixtures" / "daily-2026-09-09.json")
                         .read_text(encoding="utf-8"))
    # The 09-09 ledger predates the evidence rule (2026-10-05): no task has an
    # evidence line on record, so as booked every listed task is unverified.
    bare_title, _ = core.format_daily("2026-09-09", entries)
    check("账上没有证据：标题不说全绿，说没证据", ("全绿" in bare_title, "项没证据" in bare_title), (False, True))
    # What this test is about is the rendering of a partial failure; give each task
    # the evidence a real log would carry so the rest reads as it did on the day.
    for e in entries:
        raw = e.get("raw") or {}
        if raw.get("tasks_done"):
            raw["tasks_evidence"] = {t: "获得 信用 ×400" for t in raw["tasks_done"]}
    title, body = core.format_daily("2026-09-09", entries)
    blocks = body.split("\n\n")
    long_run = next(b for b in blocks if "1h20m" in b)
    retry_run = next(b for b in blocks if "2m" in b and "终末地" in b)

    print("[跑了 80 分钟的那趟：做过的事必须都在]")
    check("说了刷什么刷了几次", "基质刷取" in long_run and "×18" in long_run)
    check("说了花掉的理智", "1422" in long_run)
    check("说了产出", "无暇基质" in long_run and "高纯基质" in long_run)
    check("说了剩余理智", "6/360" in long_run)
    check("不再只剩一行「失败于」", long_run.count("· ") >= 5)

    print("[重试成功要说清楚，而且只说一次]")
    check("点名是哪一项", "据点交易" in long_run)
    check("说了后来做成了", "重试里做成了" in long_run)
    check("没有自相矛盾的「失败」二字", "；失败" not in long_run)
    check("整天判成全绿", "全绿" in title)
    check("标题里点明有重试", "重试" in title)

    print("[两分钟的重试那趟：一行说完，不摆四个破折号]")
    check("只有一行", retry_run.count("· "), 1)
    check("那一行说了做的是什么", "据点交易" in retry_run)
    check("没有空占位", "—" not in retry_run)

    print("[脚注取的是真正做了日常的那趟，不是两分钟那趟]")
    foot = core.daily_footnote(entries)
    check("列出了完整日常", foot.count(".") >= 13)
    check("不是只有一项", "日常：1.据点交易" not in foot)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_daily_range_prefix():
    """「日常 1-N 项完成」 only when the run's list is the footnote's first N names.

The fixture is the two real 2026-10-08 Endfield ledger records. The footnote key
comes from 05-29-15 (13 tasks, starting 赠送干员礼物、装备制造); the 10:35 run
06-34-21 did 12 others plus 自动采集. Before, its row said 「日常 1-13 项完成」,
naming tasks it never did.

    Formerly test_daily_range_prefix.py.
    """
    #!/usr/bin/env python3
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger as core

    fails = []


    def require(name, ok, detail=""):
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
        if not ok:
            fails.append(name)


    es = [json.loads(x) for x in (Path(__file__).parent / "fixtures" / "ledger-1008-maaend-two-lists.jsonl").read_text(encoding="utf-8").splitlines()]
    _t, body = core.format_daily("2026-10-08", es, "", "")
    blocks = body.split("\n\n")
    late = next(b for b in blocks if "10:35→11:12" in b)
    early = next(b for b in blocks if "09:30→10:30" in b)
    require("10:35 run names its own tasks", "日常 1-" not in late and "做了 拜访好友" in late, late)
    require("10:35 run lists 自动采集 it did", "自动采集、日常奖励领取" in late, late)
    require("the footnote's own run keeps 1-13", "日常 1-13 项完成" in early, early)
    require("footnote starts with 05:29's list", core.daily_footnote(es).startswith("———————\n日常：1.赠送干员礼物 2.装备制造"))

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_daily_techlog():
    """The daily report keeps what a person reads; the technical parts go to the technical log.

Decision D-1010 (the user, 2026-10-10 22:47 Osaka; quoted in BOARD/DECISIONS.md and
docs/NOTIFICATIONS.md): the report is for a person to read; what we read goes
somewhere of our own (core/techlog.py, <state>/../tech/<day>.md).

Every technical source is seeded here, so each marker is first shown to land in the
technical log (proving the fixture produced it) and then shown to be absent from the
report body. With the change reverted, the body carries them again and this goes red:
* the deploy notes (remember_change) -> one sentence with their number in the report;
* the relay's own faults (errwatch day file), the machine checks, the boot self-check;
* the test-window count;
* a failed row's evidence link, MaaEnd's version, OK-WW's changed client files;
* rows name the game, not the script.
Also: written where the day's report is sent and marked, never by an interim look,
not twice on a retried send, and a technical log that cannot be written leaves the
report exactly as it was and still sends it.

No network: banners and the report-writing model are stubbed as in test_report_due.py.

    Formerly test_daily_techlog.py.
    """
    import json
    import os
    import re
    import sys
    import types
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.report import report
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core import ledger as core, techlog
    from ark_relay.core.ledger import State

    fails = []


    def check(label, got, want=True):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}" + ("" if ok else f": got {got!r:.400}, want {want!r}"))
        if not ok:
            fails.append(label)


    report.plan = types.SimpleNamespace(
        schedule=lambda automas_dir: [{"name": "早班", "times": ["09:00"]}, {"name": "晚班", "times": ["21:30"]}],
        next_plan=lambda automas_dir: "",
        activity_countdown=lambda automas_dir: "",
    )
    report.banners = types.SimpleNamespace(
        collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
        read_image=None, state_dir=None: ([], {}),
        image_reader=lambda state_dir: None,
        render=lambda rows, now, nxt, notes=None, trace=None, failed=None, leads=None: "",
        Trace=types.SimpleNamespace(new=lambda: None),
        save_trace=lambda state_dir, now, text, tr: None,
        update_history=lambda state_dir, now: [],
    )
    report.summary = types.SimpleNamespace(daily_report=lambda cfg, entries, plan="": "")

    TODAY = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    URL = "https://ark-evidence-1.cos.ap-shanghai.myqcloud.com/MAA-21-30.zip?q-signature=abc"
    VERSION = "v2.32.0-beta.1"
    PAK = "Content\\Paks\\pakchunk0.pak"
    # What a technical line looks like. None of it may reach the report body.
    TECH_IN_BODY = re.compile(
        r"Traceback|myqcloud\.com|证据包|v\d+\.\d+\.\d+|v20\d{12}|pakchunk|重试后成功|耗时"
        r"|今天中继改了什么|中继自己记下的报错|上机核对|中继体检|测试跑过")
    SCRIPT_ROW = re.compile(r"^\S+ (MAA|OK-WW|MaaEnd)(（|　)", re.M)
    TOOL_WORD = re.compile(r"(?<![A-Za-z])(MaaEnd|MAA|OK-WW|AUTO-MAS)(?![A-Za-z])")


    class Notifier:
        def __init__(self):
            self.sent: list = []
            self.broken = False

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body))
            return ["Server酱: 假装挂了"] if self.broken else []

        def send_group(self, title, body):
            return []

        def send_group_image(self, path):
            return []


    class Eng:
        """The slice of Engine the report uses; forwards exactly as engine.py does."""

        def __init__(self, state_dir: Path):
            self.cfg = types.SimpleNamespace(
                automas_dir=None, history_dir=None, okww_dir=None, skland_token="",
                state_dir=state_dir, last_run_after="21:30", interim_report=True)
            self.state = State(state_dir)
            self.notifier = Notifier()

        def _report_cutoff(self, now):
            return report._report_cutoff(self, now)

        def _scripts_running(self):
            return False

        def _unfinished_queues(self, now, entries):
            return []

        def _round_is_manual(self, new_entries):
            return False

        def _compose_daily(self, day, entries):
            return report._compose_daily(self, day, entries)

        def _announce_banners(self, now, nxt):
            return None

        def send_daily_now(self, mark=True, label="临时查看"):
            return report.send_daily_now(self, mark, label)


    def run(rid, script, hhmm, mins, ok, failed=(), transitional=False, **raw):
        start = datetime.fromisoformat(f"{TODAY}T{hhmm}:00+08:00")
        return {"run_id": f"{TODAY}/x/{rid}", "script": script, "user": "u",
                "started": start.isoformat(), "finished": (start + timedelta(minutes=mins)).isoformat(),
                "ok": ok, "failed_tasks": list(failed), "duration_known": True,
                "transitional": transitional, "raw": raw}


    ENTRIES = [
        # OK-WW: the restart dialog swapped a client file, then a clean run.
        run("ww1", "OK-WW", "09:00", 1, False, transitional=True, okww_restart_dialog=True,
            okww_client_change="patch", okww_client_files=[PAK]),
        run("ww2", "OK-WW", "09:02", 10, True, tasks_done=["日常"]),
        # MaaEnd: installed its new build and restarted, then a clean run.
        run("ef1", "MaaEnd", "09:20", 2, False, failed=["MaaEnd 进程超时"], maaend_update_restart=VERSION),
        run("ef2", "MaaEnd", "09:23", 20, True, tasks_done=["赠送干员礼物"]),
        # A test run inside a marked test window.
        run("test", "MAA", "12:00", 5, True, tasks_done=["日常"]),
        # MAA's evening run failed for good; its evidence bundle was uploaded.
        run("maa", "MAA", "21:30", 3, False, failed=["基建换班"], evidence_page=URL),
    ]


    def machine() -> Eng:
        """A machine with every technical source seeded."""
        root = tmpdir()
        sd = root / "state"
        sd.mkdir()
        e = Eng(sd)
        e.state.ledger_path(TODAY).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ENTRIES), encoding="utf-8")
        (sd / "test-windows.json").write_text(json.dumps(
            [{"since": f"{TODAY}T11:59:00+08:00", "until": f"{TODAY}T12:10:00+08:00"}]), encoding="utf-8")
        report.remember_change(sd, "周本领奖补回来了。", "20261011104917", day=TODAY)
        report.remember_change(sd, "通知分三路。", "20261011104918", day=TODAY)
        (sd / errwatch.DAY_DIR).mkdir()
        (sd / errwatch.DAY_DIR / f"{TODAY}.json").write_text(json.dumps({
            "k1": {"where": "ark.notify", "line": "推送重试后成功，耗时 3 秒", "count": 2, "pushed": 2,
                   "first": f"{TODAY} 10:00:00"}}, ensure_ascii=False), encoding="utf-8")
        log = root / "relay.log"
        log.write_text(f"{TODAY[5:]} 10:00:00 ERROR    ark.report 日报推送重试后成功\n", encoding="utf-8")
        os.environ["ARK_LOG_FILE"] = str(log)
        return e


    def at(hhmm):
        return datetime.fromisoformat(f"{TODAY}T{hhmm}:00+08:00").astimezone(SERVER_TZ)


    def tech_of(e) -> str:
        p = techlog.path_for(TODAY, e.cfg.state_dir)
        return p.read_text(encoding="utf-8") if p.exists() else ""


    print("[每一路技术内容都进技术日志（先证明它真被造出来了）]")
    e = machine()
    report._maybe_daily_report(e, at("22:00"))
    check("日报发出去了", len(e.notifier.sent), 1)
    check("当天记号落了", e.state.report_sent(TODAY), True)
    title, body = e.notifier.sent[-1]
    tech = tech_of(e)
    check("技术日志在 <state>/../tech/<日期>.md",
          techlog.path_for(TODAY, e.cfg.state_dir) == (e.cfg.state_dir.parent / "tech" / f"{TODAY}.md").resolve())
    for heading in ("今天中继改了什么", "中继自己记下的报错", "上机核对（部署后机器自己核）", "中继体检",
                    "测试窗口里的记录（不计入日报）", "日报各行的证据包、版本和文件"):
        check(f"技术日志有「## HH:MM {heading}」", bool(re.search(rf"^## \d\d:\d\d {re.escape(heading)}$", tech, re.M)))
    check("部署说明在技术日志里", "周本领奖补回来了" in tech and "通知分三路" in tech)
    check("中继自己的报错原话在技术日志里", "推送重试后成功，耗时 3 秒" in tech)
    check("测试那一趟的趟号在技术日志里", f"{TODAY}/x/test" in tech)
    check("证据包链接在技术日志里，带趟号", f"{TODAY}/x/maa 证据包 {URL}" in tech)
    check("终末地的版本号在技术日志里", f"{TODAY}/x/ef1 MaaEnd 装新版 {VERSION} 后自己重启" in tech)
    check("鸣潮换了的文件在技术日志里", f"{TODAY}/x/ww1 OK-WW 游戏更新换了的文件：{PAK}" in tech)

    print("\n[日报正文里一行技术内容都没有]")
    check("正文里没有技术行", TECH_IN_BODY.findall(body), [])
    check("行首是游戏名，不是脚本名", SCRIPT_ROW.findall(body), [])
    check("各游戏的行都在", all(f"{icon} {g}　" in body for icon, g in
                             (("↪️", "鸣潮"), ("✅", "鸣潮"), ("↪️", "终末地"), ("✅", "终末地"))))
    check("失败那一趟一行说清是哪一班、哪一步",
          "❌ 明日方舟 晚班 21:30–21:33（东京 22:30–22:33）没跑成（失败于：基建换班）" in body)
    check("鸣潮更新那一行还在，只是不点名文件", "游戏更新成功（更新了客户端文件），重启后重跑，不算失败" in body)
    check("终末地更新那一行还在，只是不报版本", "终末地装了新版后自己重启，用掉一次重试，不算失败" in body)
    check("部署只剩一句次数", body.rstrip().endswith("今天中继更新了 2 次"))
    check("测试那一趟不在日报里", "12:00→" in body, False)
    check("标题照旧点名失败的游戏和班次", "明日方舟晚班没跑成" in title)

    print("\n[只在发出并落记号的那一次写；重试发送不写第二遍]")
    e = machine()
    e.notifier.broken = True
    report._maybe_daily_report(e, at("22:00"))
    check("推送失败：不落记号", e.state.report_sent(TODAY), False)
    first = tech_of(e)
    check("推送失败那一次技术日志已经写了", "今天中继改了什么" in first)
    e.notifier.broken = False
    report._maybe_daily_report(e, at("22:05"))
    check("重试发出去了", e.state.report_sent(TODAY), True)
    check("重试没把技术日志再写一遍", tech_of(e).count("今天中继改了什么"), 1)

    print("\n[临时查看不写技术日志，正文一样干净]")
    e = machine()
    check("临时查看发出去了", e.send_daily_now(mark=False), True)
    check("临时查看不写技术日志", tech_of(e), "")
    check("临时查看的正文也没有技术行", TECH_IN_BODY.findall(e.notifier.sent[-1][1]), [])
    check("send_daily_now(mark=True) 写技术日志", (e.send_daily_now(mark=True), "日报各行的证据包" in tech_of(e)), (True, True))

    print("\n[技术日志写不进去：日报照旧、照发]")
    ok = machine()
    report._maybe_daily_report(ok, at("22:00"))
    e = machine()
    (e.cfg.state_dir.parent / "tech").write_text("not a directory", encoding="utf-8")
    report._maybe_daily_report(e, at("22:00"))
    check("日报照发、记号照落", (len(e.notifier.sent), e.state.report_sent(TODAY)), (1, True))
    check("正文和写得进去时一字不差", e.notifier.sent[-1][1], ok.notifier.sent[-1][1])
    check("一段都没记成已写，下次还能补", e.state.techlog_written(TODAY), set())

    print("\n[耗时留着：跑了多久是他看得懂的结果（验收 10-11）]")
    check("每行的时长还在", ("　10m　" in body, "　20m　" in body), (True, True))

    print("\n[跑完没自己退出：中继已替他收掉，进技术日志，不进行、不进标题（验收 10-11）]")
    hung = run("ef9", "MaaEnd", "09:20", 20, True, tasks_done=["赠送干员礼物"], tasks_shot=["赠送干员礼物"],
               maaend_no_self_exit=1)
    tech_rows: list = []
    t_hung, b_hung = core.format_daily(TODAY, [hung], tech=tech_rows)
    check("标题照旧全绿", t_hung.endswith("全绿 ✅"), True)
    check("正文里没有这一句", "没自己退出" in b_hung, False)
    check("技术日志那一行带趟号", tech_rows, [f"{TODAY}/x/ef9 终末地任务全完成，但跑完没自己退出（空等 1 分钟）"])

    print("\n[正文里不出现工具名，工具自己的话换成人话（验收 10-11）]")
    # 10-10's shape: MAA stopped three times at 09:00 (the stage it could not reach),
    # nothing done; no make-up (unsure whether it fought); a hand-started run at 12:15 got it
    # (12:15, not 12:05: machine() marks 11:59-12:10 as a test window).
    def maa_stop(rid, hhmm):
        return run(rid, "MAA", hhmm, 1, False, failed=["MAA 在完成任务前中止"], fight_count=0,
                   maa_result="MAA 在完成任务前中止", maa_config_rejected="理智作战 序列化失败，关卡 YW-4")


    day10 = [maa_stop("m1", "09:00"), maa_stop("m2", "09:01"), maa_stop("m3", "09:03"),
             run("m4", "MAA", "12:15", 19, True, stages=["YW-4"], run_times=14, sanity_spent=168,
                 hand_started="9c68")]
    e = machine()
    e.state.ledger_path(TODAY).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in day10), encoding="utf-8")
    from ark_relay.features.makeup import makeup, marker
    marker._write_marker(e.cfg.state_dir, TODAY, {"MAA": {
        "result": makeup.GAVE_UP, "run_id": f"{TODAY}/x/m3",
        "note": "不补跑：失败的不只是开始唤醒或连模拟器（MAA 在完成任务前中止），拿不准有没有打过仗"}})
    t10, b10 = e._compose_daily(TODAY, e.state.read_ledger(TODAY))
    check("标题、正文里一个工具名都没有", TOOL_WORD.findall(t10 + b10), [])
    e2 = machine()
    e2.state.ledger_path(TODAY).write_text(json.dumps(run(
        "x1", "MaaEnd", "09:20", 30, False, failed=["MaaEnd 进程超时"], tasks_done=["赠送干员礼物"],
        tasks_shot=["赠送干员礼物"]), ensure_ascii=False) + "\n", encoding="utf-8")
    t_x, b_x = e2._compose_daily(TODAY, e2.state.read_ledger(TODAY))
    check("工具自己的话换成人话", ("失败于：终末地跑得太久，被停掉了" in b_x, TOOL_WORD.findall(t_x + b_x)), (True, []))

    print("\n[连续几次空失败合成一行，写班次、原因和后来补上没有（验收 10-11）]")
    check("三次合成一行", [l for l in b10.splitlines() if l.startswith("❌")],
          ["❌ 明日方舟 早班 09:00–09:04（东京 10:00–10:04）连试 3 次没跑成（关卡 YW-4 当时走不到），12:15 手动补跑成功"])
    check("标题按一件事说", "明日方舟早班没跑成（12:15 补上了）" in t10, True)
    check("补跑那一行写班次和人话", "明日方舟早班失败后没有自动补跑（拿不准第一次打没打过仗，怕重复花理智），12:15 已手动补上" in b10,
          True)

    print("\n[重试的话留着：他从这句看出哪一项失败过（验收 10-11）]")
    retry = [run("r1", "MaaEnd", "09:20", 10, False, failed=["转交委托"], tasks_done=["赠送干员礼物"],
                 tasks_shot=["赠送干员礼物"]),
             run("r2", "MaaEnd", "09:40", 10, True, tasks_done=["转交委托"], tasks_shot=["转交委托"])]
    t_r, b_r = core.format_daily(TODAY, retry)
    check("正文写后来在哪一趟重试里做成了", "转交委托　后来在 09:40（东京 10:40）开始的那趟重试里做成了" in b_r, True)
    check("标题写有项目重试后成功", t_r.endswith("全绿 ✅（有项目重试后成功）"), True)

    print("\n[红项的格式：读取工具按这个认（ac38f466 的格式）]")
    when = datetime(2026, 10, 11, 21, 45, tzinfo=SERVER_TZ)
    d = tmpdir() / "state"
    check("每条红项带自己的编号", techlog.add_red(TODAY, "收工体检", ["收工体检：补丁不在", "明早的队列读不到"],
                                             state_dir=d, now=when),
          ["R-20261011-2145-1", "R-20261011-2145-2"])
    reds = [ln for ln in techlog.path_for(TODAY, d).read_text(encoding="utf-8").splitlines() if ln.startswith("🔴")]
    check("红项那一行的样子", reds, ["🔴 R-20261011-2145-1 收工体检：补丁不在",
                                  "🔴 R-20261011-2145-2 明早的队列读不到"])
    text = "\n".join(reds + [techlog.handled_line("R-20261011-2145-1", "abc1234")])
    check("已处理那一行的样子", techlog.handled_line("R-20261011-2145-1", "abc1234"),
          "✅ R-20261011-2145-1 已处理（abc1234）")
    check("处理过的不再算没处理", techlog.unhandled(text), [("R-20261011-2145-2", "明早的队列读不到")])
    d = tmpdir() / "state"
    check("空内容不写文件也算成功", (techlog.append(TODAY, "空", "  ", state_dir=d), techlog.path_for(TODAY, d).exists()),
          (True, False))
    check("一段写成 ## HH:MM 标题",
          (techlog.append(TODAY, "收工体检", "\n".join(reds), state_dir=d, now=when),
           techlog.path_for(TODAY, d).read_text(encoding="utf-8")),
          (True, "\n## 21:45 收工体检\n" + "\n".join(reds) + "\n"))

    print("\n[跨零点：记进前一天文件的红项和今天的自愈红项编号不撞（审查 10-13 s5 #2）]")
    # gamelog_errors writes into the round's start day with the current time as the
    # stamp; self_heal in the same minute writes into today's file. The Mac tool joins
    # all days by id, so a shared id hid one of the two.
    d = tmpdir() / "state"
    after_midnight = datetime(2026, 10, 13, 0, 20, tzinfo=SERVER_TZ)
    a = techlog.add_red("2026-10-12", "游戏日志里没登记的报错", ["23:50 开始的那一趟"], state_dir=d, now=after_midnight)
    b = techlog.self_heal("ark.gamelog_errors", "自己好了", state_dir=d, now=after_midnight)
    c = techlog.add_red("2026-10-12", "游戏日志里没登记的报错", ["又一趟"], state_dir=d, now=after_midnight)
    check("三条红项三个编号", len(set(a + b + c)), 3)
    joined = "".join(techlog.path_for(x, d).read_text(encoding="utf-8") for x in ("2026-10-12", "2026-10-13"))
    check("两天的文件合起来三条都还在", len(techlog.unhandled(joined)), 3)

    if fails:
        print(f"\nFAILED: {fails}")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    sys.exit(run_parts([_part_daily_format, _part_daily_partial_failure, _part_daily_range_prefix, _part_daily_techlog]))
