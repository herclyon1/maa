"""The daily report: format, partial failures, range prefixes and the technical log; no model, the report coming due, the model's breaker.

One part per former file, each run on its own (tests/_parts.py): test_daily.py, test_no_model_daily_report.py, test_report_due.py, test_llm_breaker.py.
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
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ

    FX = Path(__file__).parent / "fixtures"

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

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger as core


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

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger as core


    es = [json.loads(x) for x in (Path(__file__).parent / "fixtures" / "ledger-1008-maaend-two-lists.jsonl").read_text(encoding="utf-8").splitlines()]
    _t, body = core.format_daily("2026-10-08", es, "", "")
    blocks = body.split("\n\n")
    late = next(b for b in blocks if "10:35→11:12" in b)
    early = next(b for b in blocks if "09:30→10:30" in b)
    require("10:35 run names its own tasks", "日常 1-" not in late and "做了 拜访好友" in late, late)
    require("10:35 run lists 自动采集 it did", "自动采集、日常奖励领取" in late, late)
    require("the footnote's own run keeps 1-13", "日常 1-13 项完成" in early, early)
    require("footnote starts with 05:29's list", core.daily_footnote(es).startswith("———————\n日常：1.赠送干员礼物 2.装备制造"))


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

No network: banners and the report-writing model are stubbed as in the _part_report_due part.

    Formerly test_daily_techlog.py.
    """
    import json
    import os
    import re
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.report import report
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core import ledger as core, techlog
    from ark_relay.core.ledger import State


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


def _part_no_model_daily_report():
    """The model-written daily report is gone; the template is the only path.

Retired on 08-30 (66711d4f: 「模型写日报是废除的规划（太贵）」) yet report.py still
tried summary.daily_report first; relay.log has 0 「日报由模型撰写」 lines and 129
「日报用结构化模板」. Had it run, it would have skipped split_test (test-window
runs in the report) and the retry / make-up / stage-gate lines.

    Formerly test_no_model_daily_report.py.
    """
    #!/usr/bin/env python3
    import inspect

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import summary
    from ark_relay.features.report import report

    for label, ok in (("summary.daily_report removed", not hasattr(summary, "daily_report")),
                      ("_compose_daily has no model branch", "日报由模型撰写" not in inspect.getsource(report._compose_daily))):
        print(("  ✓ " if ok else "  ✗ ") + label)
        if not ok:
            fails.append(label)


def _part_report_due():
    """日报什么时候该发、什么时候不许发，以及发出去的那份里必须有什么。

**这里坏了的后果不是「少了一条通知」，是机器整夜不关。** `_maybe_shutdown` 的前提之一
就是 `report_sent(今天)`，日报发不出去 → 关机永远等不到条件 → 机器开一整夜
（docs/PITFALLS.md 里那次是判据写错：条件用「最后一趟的**结束时刻**」和 21:30 比，
队列挪到 21:25、21:28 跑完之后这个条件**永远为真**，日报永远发不出，机器永远不关）。

report.py 的 10 个函数里 5 个从来没被执行过，`_maybe_daily_report`、`_compose_daily`、
`_maybe_interim_report` 都在里面。这个文件补的就是这几条路，钉住六件事：

1. 昨天的日报没发出去，过了零点只剩今天这一次机会——必须先补昨天；
2. 同一天不许发两遍（记号是 `marks: report:<日期>`），但**推送失败时不许落记号**，
   否则那一天就永远丢了；
3. 一天里一条记录都没有时不发也不落记号（落了记号，晚到的那趟就永远不会被报）；
4. 到点之前、脚本还在跑、队列还没跑完，一律再等——尤其最后一条：cutoff 就是晚班的
   **发车时刻**，那几秒游戏还在启动，只看早班记录会写出一份「今天就这些」的假日报，
   还把当天记号落掉，晚班从此无人过问；
5. 末尾那行版本记分（`scoreboard.line`）必须真的挂上去，而且在我写的任何字之后——
   用户 2026-09-06：「我说『修好了』而它写『失败 1 趟』，谎话当场现形。」；
6. 模型撰写不可用时走结构化模板，那是**正常路径不是故障**，不许在日志里留假伤
   （天天一条假 WARNING，真的那条就没人看了）。

不联网：卡池和撰写模型都换成了本地假货，AUTO-MAS 目录一律 None。

    Formerly test_report_due.py.
    """
    import json
    import logging
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.report import report, scoreboard
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.ledger import State


    # ---------------------------------------------------------- 把外面的世界掐掉
    # 卡池要连 prts.wiki / 库街区 / 森空岛；撰写模型要连大模型。两个都换成本地假货，
    # 这个文件才既跑得快又不会因为别人家的网站抖一下就变红。
    SCHEDULE: list = []
    report.plan = types.SimpleNamespace(
        schedule=lambda automas_dir: list(SCHEDULE),
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


    class LogGrab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: list = []

        def emit(self, record):
            self.records.append(record)

        def worst(self):
            return max((r.levelno for r in self.records), default=0)


    GRAB = LogGrab()
    # 直接挂 report 自己那个 logger 对象，不写死日志名：名字要是改了，这里跟着走。
    report.log.addHandler(GRAB)
    report.log.setLevel(logging.DEBUG)


    # --------------------------------------------------------------- 替身零件
    class FakeNotifier:
        """记下发出去的每一条；`broken` 时每次都返回「一个渠道都没送到」。"""

        def __init__(self):
            self.sent: list = []
            self.groups: list = []
            self.broken = False

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert, daily))
            return ["Server酱: 假装挂了"] if self.broken else []

        def send_group(self, title, body):
            self.groups.append((title, body))
            return []

        def send_group_image(self, path):
            return []

        def titles(self):
            return [t for t, *_ in self.sent]


    class Eng:
        """Engine 里跟日报有关的那一小块，其余全部换成可控的替身。
    转发方式跟 engine.py 里一模一样，改了那边的签名这里会当场对不上。"""

        def __init__(self, state, *, interim=True, last_run_after="21:30"):
            self.cfg = types.SimpleNamespace(
                automas_dir=None, history_dir=None, okww_dir=None, skland_token="",
                state_dir=None, last_run_after=last_run_after, interim_report=interim)
            self.state = state
            self.notifier = FakeNotifier()
            self.running = False
            self.unfinished: list = []
            self.manual = False

        def _report_cutoff(self, now):
            return report._report_cutoff(self, now)

        def _scripts_running(self):
            return self.running

        def _unfinished_queues(self, now, entries):
            return list(self.unfinished)

        def _round_is_manual(self, new_entries):
            return self.manual

        def _compose_daily(self, day, entries):
            return report._compose_daily(self, day, entries)

        def _announce_banners(self, now, nxt):
            return None

        def send_daily_now(self, mark=True, label="临时查看"):
            return report.send_daily_now(self, mark, label)


    TODAY = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    YDAY = (datetime.now(tz=SERVER_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


    def entry(day, n=1, script="MAA", ok=True):
        start = datetime.fromisoformat(f"{day}T09:0{n}:00+08:00")
        return {"run_id": f"{day}/ark/0{n}", "script": script, "user": "ark",
                "started": start.isoformat(),
                "finished": (start + timedelta(minutes=20)).isoformat(),
                "ok": ok, "failed_tasks": [] if ok else ["某一步炸了"], "raw": {}}


    def make(entries_by_day=None, **kw):
        """一台干净的机器：真 State（记号和账本都是真的），假通知和假队列。"""
        st = State(tmpdir())
        for day, rows in (entries_by_day or {}).items():
            st.ledger_path(day).write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                encoding="utf-8")
        return Eng(st, **kw)


    def at(day, hhmm):
        return datetime.fromisoformat(f"{day}T{hhmm}:00+08:00").astimezone(SERVER_TZ)


    # =========================================================== 日报什么时候到点
    print("[到点时刻跟着 AUTO-MAS 自己的队列走，不是写死的]")
    SCHEDULE[:] = [{"name": "早班", "times": ["09:00"]},
                   {"name": "晚班", "times": ["21:25"]}]
    e = make()
    check("取最晚那一条队列的时刻",
          e._report_cutoff(at(TODAY, "12:00")).strftime("%H:%M"), "21:25")
    SCHEDULE[:] = []
    check("读不到队列才退回 ARK_LAST_RUN_AFTER",
          e._report_cutoff(at(TODAY, "12:00")).strftime("%H:%M"), "21:30")
    bad = make(last_run_after="晚上")
    try:
        got = bad._report_cutoff(at(TODAY, "12:00")).strftime("%H:%M")
    except Exception as exc:                      # noqa: BLE001
        got = f"抛了 {exc!r}"
    check("时刻写坏了兜底 21:30，不抛异常——抛了这一轮连关机也一起没了", got, "21:30")

    # ================================================= 昨天没发出去，今天必须先补
    print("\n[昨天的日报没发出去：过了零点只剩这一次机会]")
    e = make({YDAY: [entry(YDAY)], TODAY: [entry(TODAY)]})
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("补发那条排在最前", e.notifier.titles()[0].endswith("（补发）"), True)
    check("昨天的记号落上了", e.state.report_sent(YDAY), True)
    check("今天那条照发，不是拿补发顶替", len(e.notifier.sent), 2)
    check("今天的记号也落上了", e.state.report_sent(TODAY), True)

    print("\n[补发也推不出去时：不许落记号，下一轮还要再补]")
    e = make({YDAY: [entry(YDAY)]})
    e.notifier.broken = True
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("试着发了", len(e.notifier.sent), 1)
    check("昨天的记号绝不能落", e.state.report_sent(YDAY), False)
    e.notifier.broken = False
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("下一轮补上了", e.state.report_sent(YDAY), True)

    print("\n[昨天已经发过 / 昨天一条记录都没有：都不许补]")
    e = make({YDAY: [entry(YDAY)]})
    e.state.mark_report_sent(YDAY)
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("发过了就不重发", e.notifier.sent, [])
    e = make({TODAY: [entry(TODAY)]})
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("昨天没跑过就不补一份空的",
          [t for t in e.notifier.titles() if "补发" in t], [])

    # ============================================================ 同一天只发一遍
    print("\n[同一天不许发两遍]")
    e = make({TODAY: [entry(TODAY)]})
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("发了一条", len(e.notifier.sent), 1)
    check("落了 report:<日期> 记号", e.state.report_sent(TODAY), True)
    report._maybe_daily_report(e, at(TODAY, "22:05"))
    check("第二轮什么都不发", len(e.notifier.sent), 1)
    check("记号是写在 marks 里的",
          e.state.store.get("marks", f"report:{TODAY}") is not None, True)

    print("\n[当天部署过的更新说明进技术日志，日报只留一句次数（D-1010；更新通知本身不再推）]")
    from _tmp import tmpdir as _tmpd0


    def _tmpd():
        # <tmp>/state, so the technical log (<state>/../tech) stays inside the tmp dir.
        d = _tmpd0() / "state"
        d.mkdir()
        return d


    e = make({TODAY: [entry(TODAY)]})
    e.cfg.state_dir = _tmpd()
    report.remember_change(e.cfg.state_dir, "周本领奖补回来了。", "20260914104917", day=TODAY)
    report.remember_change(e.cfg.state_dir, "通知分三路。", "20260914104918", day=TODAY)
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    body = e.notifier.sent[-1][1]
    check("日报不带「今天中继改了什么」", "今天中继改了什么" in body, False)
    check("日报不带部署说明", "周本领奖补回来了" in body or "通知分三路" in body, False)
    check("日报末尾一句部署次数", body.rstrip().endswith("今天中继更新了 2 次"), True)
    tech = (e.cfg.state_dir.parent / "tech" / f"{TODAY}.md").read_text(encoding="utf-8")
    check("两次部署的说明都在技术日志里", "## " in tech and "今天中继改了什么" in tech
          and "周本领奖补回来了" in tech and "通知分三路" in tech, True)
    check("日报走的是 daily（进群）", e.notifier.sent[-1][3], True)
    e2 = make({TODAY: [entry(TODAY)]})
    e2.cfg.state_dir = _tmpd()
    report._maybe_daily_report(e2, at(TODAY, "22:00"))
    check("没部署过就没有这一句", "中继更新了" in e2.notifier.sent[-1][1], False)

    print("\n[当天补跑过的结果附在日报里（补跑开始/完成不再单独推）]")
    import json as _json
    e = make({TODAY: [entry(TODAY)]})
    e.cfg.state_dir = _tmpd()
    (e.cfg.state_dir / "collect-retry").mkdir()
    (e.cfg.state_dir / "collect-retry" / f"{TODAY}.json").write_text(_json.dumps(
        {"run_id": "x", "routes": ["AutoCollectRoute15", "AutoCollectRoute16"], "passed": ["AutoCollectRoute15"],
         "failed": ["AutoCollectRoute16"], "unknown": [], "note": ""}), encoding="utf-8")
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    body = e.notifier.sent[-1][1]
    check("日报里有补跑结果", "自动采集补跑：走通 AutoCollectRoute15；仍失败 AutoCollectRoute16" in body, True)

    print("\n[推送失败时不许落记号：落了这一天就永远丢了]")
    e = make({TODAY: [entry(TODAY)]})
    e.notifier.broken = True
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("没落记号", e.state.report_sent(TODAY), False)
    e.notifier.broken = False
    report._maybe_daily_report(e, at(TODAY, "22:01"))
    check("下一轮重发成功", len(e.notifier.sent), 2)
    check("这才落记号", e.state.report_sent(TODAY), True)

    # ================================================================ 什么时候等
    print("\n[没到点、还在跑、队列没跑完——一律再等]")
    e = make({TODAY: [entry(TODAY)]})
    report._maybe_daily_report(e, at(TODAY, "20:00"))
    check("没到点不发", e.notifier.sent, [])
    e.running = True
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("脚本还在跑不发", e.notifier.sent, [])
    e.running = False
    e.unfinished = ["晚班还没跑完"]
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("队列没跑完不发——cutoff 就是晚班发车时刻，那几秒游戏还没起来",
          e.notifier.sent, [])
    check("也没落记号，不然晚班从此没人问", e.state.report_sent(TODAY), False)
    e.unfinished = []
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("跑完了才发", len(e.notifier.sent), 1)

    print("\n[一天里一条记录都没有]")
    e = make({TODAY: []})
    report._maybe_daily_report(e, at(TODAY, "22:00"))
    check("不发空日报", e.notifier.sent, [])
    check("更不许落记号——落了，晚到的那趟就永远不会被报",
          e.state.report_sent(TODAY), False)
    print("  （人主动要的时候是另一回事：问了就得有答案）")
    e2 = make({TODAY: []})
    check("手动 report 命令照发", e2.send_daily_now(), True)
    check("正文说清楚今天没跑过", "今天没有任何运行记录。" in e2.notifier.sent[0][1], True)

    # ====================================================== 末尾那行版本记分牌
    print("\n[版本记分照算照记，但不再印进日报（用户 09-14：毫无意义）]")
    e = make({TODAY: [entry(TODAY, ok=False)]})
    e.state.store.set("versions", "code", "9.9.9")
    scoreboard.record(e.state.store, "9.9.9", ok=True)
    scoreboard.record(e.state.store, "9.9.9", ok=False)
    want_line = scoreboard.line(e.state.store, "9.9.9")
    check("记分牌自己算出来的那一串不是空的", want_line.startswith("代码 v9.9.9"), True)
    check("它数的是真跑过的趟数", "跑过 2 趟，失败 1 趟" in want_line, True)
    _, body = e._compose_daily(TODAY, e.state.read_ledger(TODAY))
    check("正文里不再有那一行", want_line in body, False)
    check("正文里没有「代码 v」字样", "代码 v" in body, False)
    e2 = make({TODAY: [entry(TODAY)]})
    _, body2 = e2._compose_daily(TODAY, e2.state.read_ledger(TODAY))
    check("没记录版本号时不留一截空尾巴", body2.rstrip(), body2)

    # ============================================== 结构化模板
    print("\n[日报只走结构化模板（模型撰写 08-30 废弃、已删），这是正常路径不是故障]")
    check("模型撰写那条路已删", hasattr(__import__("ark_relay.core.summary", fromlist=["x"]), "daily_report"), False)
    GRAB.records.clear()
    e = make({TODAY: [entry(TODAY)]})
    title, body = e._compose_daily(TODAY, e.state.read_ledger(TODAY))
    check("照样出得来一份日报", bool(title and body), True)
    check("走的是结构化模板那条路", "9:01" in body or "09:01" in body, True)
    check("日志里一条 WARNING 都不许有——假伤会让真伤没人看",
          GRAB.worst() < logging.WARNING, True)
    check("而且确实说了这是正常路径",
          any("正常路径" in r.getMessage() for r in GRAB.records), True)

    # ============================================================ 白天那份速览
    print("\n[白天速览：关掉就不发]")
    e = make({TODAY: [entry(TODAY)]}, interim=False)
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("开关关着就一条都不发", e.notifier.sent, [])

    print("\n[到点之后不发速览，让真日报说话]")
    e = make({TODAY: [entry(TODAY)]})
    report._maybe_interim_report(e, at(TODAY, "22:00"))
    check("过了 cutoff 就闭嘴", e.notifier.sent, [])

    print("\n[今天日报已经发过 / 没有记录 / 还在跑 / 队列没完：都不发]")
    e = make({TODAY: [entry(TODAY)]})
    e.state.mark_report_sent(TODAY)
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("日报发过了就不再速览", e.notifier.sent, [])
    e = make({TODAY: []})
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("没记录不发", e.notifier.sent, [])
    e = make({TODAY: [entry(TODAY)]})
    e.running = True
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("还在跑不发", e.notifier.sent, [])
    e.running = False
    e.unfinished = ["早班还没跑完"]
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("队列没跑完不发", e.notifier.sent, [])

    print("\n[早班跑完就发一份速览，但**不许吃掉当天的日报**]")
    e = make({TODAY: [entry(TODAY, 1), entry(TODAY, 2)]})
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("发了一条", len(e.notifier.sent), 1)
    check("标题是 🔎 不是 📋", e.notifier.titles()[0].startswith("🔎"), True)
    check("说清是临时查看", "（临时查看）" in e.notifier.titles()[0], True)
    check("当天日报的记号绝不能落——落了晚上那份就没了",
          e.state.report_sent(TODAY), False)
    check("记下这一轮盖到第几条", e.state.interim_covered(TODAY), 2)

    print("\n[同一轮不重发；补跑多出来的那一条要另算一轮]")
    report._maybe_interim_report(e, at(TODAY, "12:05"))
    check("同一轮闭嘴", len(e.notifier.sent), 1)
    rows = e.state.read_ledger(TODAY) + [entry(TODAY, 3)]
    e.state.ledger_path(TODAY).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    report._maybe_interim_report(e, at(TODAY, "15:00"))
    check("补跑了就再报一次", len(e.notifier.sent), 2)
    check("覆盖数跟着往前推", e.state.interim_covered(TODAY), 3)

    print("\n[手动触发的那一轮要说是手动的——人得知道这份速览为什么冒出来]")
    e = make({TODAY: [entry(TODAY)]})
    e.manual = True
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("标签是手动执行", "（手动执行）" in e.notifier.titles()[0], True)

    print("\n[速览推不出去时不许记覆盖数，否则这一轮就永远没人报了]")
    e = make({TODAY: [entry(TODAY)]})
    e.notifier.broken = True
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("试着发了", len(e.notifier.sent), 1)
    check("没记覆盖数", e.state.interim_covered(TODAY), 0)

    print("\n[只有我们自己的测试跑（测试窗口里）的一轮不推速览——测试不进他眼（10-12 18:29 实发过一次）]")
    e = make({TODAY: [entry(TODAY)]})
    e.cfg.state_dir = e.state.dir
    (e.state.dir / "test-windows.json").write_text(json.dumps(
        [{"since": f"{TODAY}T09:00:00+08:00", "until": f"{TODAY}T09:02:00+08:00"}]),
        encoding="utf-8")
    report._maybe_interim_report(e, at(TODAY, "12:00"))
    check("测试那一轮一条都不发", e.notifier.sent, [])
    check("但要记成已覆盖，下一轮真跑不把它算进去", e.state.interim_covered(TODAY), 1)
    rows = e.state.read_ledger(TODAY) + [entry(TODAY, 5)]
    e.state.ledger_path(TODAY).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    report._maybe_interim_report(e, at(TODAY, "15:00"))
    check("窗口外的真跑照常报", len(e.notifier.sent), 1)


def _part_llm_breaker():
    """The wording model is a garnish, but a dead endpoint is not free: each attempt
can cost the full 60 s timeout, inside the path that must finish before the
machine may power off. After a failure it rests summary.REST_S, then is asked again
(audit 11-08 B-D7: until then one failure closed it for the whole process); the group
hears of it once per process.

    Formerly test_llm_breaker.py.
    """
    import logging
    import sys, time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import summary


    class Cfg:
        llm_key = "sk-test"
        llm_provider = "openai"
        llm_model = "deepseek-chat"
        llm_base_url = "https://api.deepseek.com"

    calls = []
    def slow_and_broken(*a, **kw):
        calls.append(1)
        time.sleep(0.05)                      # stand-in for a 60 s timeout
        raise OSError("connection refused")

    summary.urllib.request.urlopen = slow_and_broken
    summary._endpoint_dead = None
    NOW = [1000.0]
    summary._clock = lambda: NOW[0]


    class Levels(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.levels = []

        def emit(self, record):
            self.levels.append(record.levelname)


    levels = Levels()
    summary.log.addHandler(levels)
    summary.log.setLevel(logging.DEBUG)
    summary.log.propagate = False

    print("[first call tries, and fails]")
    check("returns nothing", summary._ask(Cfg(), "hi"), "")
    check("did attempt", len(calls), 1)

    print("\n[every later call in this process is free]")
    t0 = time.monotonic()
    for _ in range(20):
        summary._ask(Cfg(), "hi")
    elapsed = time.monotonic() - t0
    check("no further attempts", len(calls), 1)
    check("cost ~nothing", elapsed < 0.05, True)
    check("one WARNING (the group hears of it)", levels.levels, ["WARNING"])

    print("\n[after the rest it is asked again; failing again is INFO, not a second push]")
    NOW[0] += summary.REST_S - 1
    summary._ask(Cfg(), "hi")
    check("just before the rest ends: still skipped", len(calls), 1)
    NOW[0] += 2
    summary._ask(Cfg(), "hi")
    check("after the rest: asked again", len(calls), 2)
    check("……that failure is INFO", levels.levels, ["WARNING", "INFO"])


    class Resp:
        def read(self):
            return '{"choices": [{"message": {"content": "好"}}]}'.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    summary.urllib.request.urlopen = lambda *a, **kw: calls.append(1) or Resp()
    NOW[0] += summary.REST_S
    check("back: the answer is used", summary._ask(Cfg(), "hi"), "好")
    check("……and the next call is not held back", (summary._endpoint_dead, summary._ask(Cfg(), "hi")), (None, "好"))
    summary.urllib.request.urlopen = slow_and_broken
    summary._endpoint_dead = NOW[0]          # dead again, resting
    calls[:] = [1]

    print("\n[the report still renders without it]")
    entry = {"run_id": "x", "script": "MAA", "user": "arknights",
             "started": "2026-08-21T21:30:00+08:00",
             "finished": "2026-08-21T22:15:00+08:00", "ok": True}
    check("diagnose returns empty, caller falls back",
          summary.diagnose(Cfg(), entry["script"], ["x"], "log tail"), "")

    print("\n[an explicit check must really ask again]")
    try:
        summary.check(Cfg())
    except Exception:  # noqa: BLE001
        pass
    check("breaker was reset by check()", len(calls), 2)

    print("\n[no key at all: never attempts]")
    class NoKey(Cfg):
        llm_key = ""
    summary._endpoint_dead = None
    before = len(calls)
    check("returns nothing", summary._ask(NoKey(), "hi"), "")
    check("no attempt", len(calls), before)


if __name__ == "__main__":
    sys.exit(run_parts([_part_daily_format, _part_daily_partial_failure, _part_daily_range_prefix, _part_daily_techlog, _part_no_model_daily_report, _part_report_due, _part_llm_breaker]))
