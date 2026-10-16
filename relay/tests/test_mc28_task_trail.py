"""Machine check #28 judged from MaaEnd's own steps, not from the desktop picture.

Verify ledger #28 (Endfield gift / gear / delivery / environment monitoring left no in-game picture): #28 passed
when the picture file existed, and the pictures show the next task - the COS bundle
2026-10-08_endfield_MaaEnd-05-29-15 has 093302-赠送干员礼物.png on the 装备制造 page and
103416-装备制造.png on the bare desktop after MaaEnd stopped itself at 10:34:16
(its scene check failed and __SceneCheckAbortPipeline ended the task chain; AUTO-MAS
sent no stop - verify ledger #28 review).
Now each task must show in MaaFW's own log (maaend_fwlog.task_trail) either the step
that does its job or a 「nothing to do」 end; the picture is named with how late it was.

Data (fixtures/maaend-task-trail/): the AUTO-MAS history logs of 2026-10-08
MaaEnd-05-29-15 / -06-31-06 / -06-34-21, 2026-10-13 MaaEnd-05-36-57 and 2026-10-16
MaaEnd-09-53-33; MaaFW's task and step event lines of those windows, cut unchanged
from the machine's maaend/debug/maafw*.log (pull 2026-10-13 15:26 for 10-08 and 10-13,
the COS evidence bundle of 10-16 for 10-16, kept in the three rotated files the lines
really sat in); and the pictures' real capture times from the evidence bundles
(shot-times.json).
"""
import gzip
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_STATE_DIR=str(TMP / "state"),
                  SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                  WECOM_BOT_URL="", ARK_PHONE_TOPIC="", ARK_LOG_FILE=str(TMP / "relay.log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import texts  # noqa: E402
from ark_relay.core.config import SERVER_TZ, RunRecord  # noqa: E402
from ark_relay.features.selfcheck import machinecheck as mc  # noqa: E402
from ark_relay.features.verify import collector_maaend, maaend_fwlog  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from ark_relay.core import ledger as core  # noqa: E402
from ark_relay.core import ledger_rows  # noqa: E402
from ark_relay.features.alarm import handle, pushes  # noqa: E402
from ark_relay.features.selfcheck.machinechecks import runs  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "maaend-task-trail"
SHOT_TIMES = {k: v for k, v in json.loads((FIX / "shot-times.json").read_text(encoding="utf-8")).items()
              if not k.startswith("_")}
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


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
from ark_relay.core import techlog  # noqa: E402
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
# The failed tasks AUTO-MAS booked for 06-31-06 (its history record; the 10-08 daysim
# ledger row 2026-10-08/endfield/MaaEnd-06-31-06): every task after the abort.
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
import logging  # noqa: E402


class Levels(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.got = []

    def emit(self, record):
        self.got.append((record.levelno, record.getMessage()))


FOUR = ["赠送干员礼物", "装备制造", "转交委托", "环境监测"]
state, empty, book = tmpdir(), tmpdir(), Ledger()
from ark_relay.features.alarm import records  # noqa: E402

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
# MaaFW rotates maafw.log into maafw.bak.<time>.log (10-16: three files in seven
# minutes, ROT above) and MaaEnd clears its debug folder when it restarts, so the
# files can begin inside a run. The real 10-08 lines, split at 09:38:30 - inside
# 05-29-15's 转交委托 (09:37:39→09:39:28) - into the rotated part and maafw.log.
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
# The gift task's all-full end, GiftOperatorGiftFullFail, is a StopTask node. Whether
# such a node is logged decides whether that end can be read at all: the real 10-16
# line of another StopTask node (CreditShoppingBuyItemStop, CreditShopping/Flow/
# BuyItem.json) shows it is, and that MaaFW books its task Succeeded. MaaFramework's
# Actuator::stop_task returns success; PipelineTask::run_next notifies the node before
# its loop checks need_to_stop.
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

# ---- The 「nothing to do」 ends, which no run on the machine has hit yet --------------
# GiftOperatorGiftFull / GiftOperatorGiftFullFail, GearAssemblyCheckMaterialEnough and
# GearAssemblyCheckFailedAndFinish have no Node.PipelineNode.Succeeded line in any
# maafw*.log of the corpus pull 2026-10-13 15:26 (D/ark/maaend/debug and the evidence
# bundles of 09-14..10-13) nor in the 10-16 bundle: no run hit them. A StopTask node
# is logged when hit (the check just above). So the trails below are synthetic:
# the real 10-13 run with its gift / gear steps replaced by the steps MaaEnd's own
# pipeline takes, each one in its predecessor's "next" list as written in
# assets/resource/pipeline/GearAssembly/GearAssembly.json and
# GiftOperator/GiftOperatorGiftFlow.json of MaaEnd v2.33.0-beta.3 (the version on the
# machine, daysim-corpus/_install/D/ark/maaend/interface.json):
#   GearAssemblySelectFirstGear.next = [ClickProduceBtn, CheckFailedAndContinue]
#   GearAssemblyClickProduceBtn.next = [CheckMaterialEnough 「检测背包是否已满，背包已满直接结束」,
#                                       SceneNoticeRewardsConfirm]
#   GearAssemblyCheckFailedAndContinue.next = [GearListScrollEnd, SwipeToNextRow]
#   GearAssemblyGearListScrollEnd.next = [CheckFailedAndFinish 「检查制作失败，退出任务」]
#   GiftOperatorGiftUI.next = [GiftFull, ClickGift]; GiftFull.next = [GiftFullLeave];
#   GiftFullLeave.next = [.., GiftFullBackInWorld]; GiftFullBackInWorld.next =
#   [GiftFullRetry (max_hit 5, next GiftOperatorEntry), GiftFullFail (StopTask)];
#   GiftFullFail's own desc: 「重试五次也只能找到送满的干员，正常失败」 (all operators full).
# A synthetic line carries what task_trail reads (time, task_id, node_id, the node hit
# and its predecessor) in the machine's line format.
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


# 10-13 gear (09:41:36→09:41:55): SelectFirstGear 300000425 at 09:41:45.408, then
# ClickProduceBtn 300000426, SceneNoticeRewardsConfirm 300000427, its click 300000436
# and __ScenePrivateNextTrue 300000441 before the task's end at 09:41:55.671.
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

# 10-13 gift (09:38:17→09:41:36): GiftOperatorGiftUI 300000354 at 09:41:29.394, then
# ClickGift 300000358, GiftSelected 300000361, ConfirmGift 300000363, GiftDialog
# 300000366 / 300000367, Leave 300000368; the task ends 09:41:36.138.
GIFT_AFTER_UI = (300000358, 300000361, 300000363, 300000366, 300000367, 300000368)


def chain(t, pairs, step=0.08):
    """[(time, gift task, name, parent)] from second `t` of 09:41, `step` apart; and the next second."""
    out = []
    for name, parent in pairs:
        out.append((f"09:41:{t:06.3f}", GIFT_TASK, name, parent))
        t += step
    return out, t


# One operator whose gifts are full. Between GiftOperatorEntry and the next GiftUI a
# retry walks the same steps as the real run (09:40:08-09:41:29); they are left out,
# the verdict reads only the named ones.
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
# GiftFullFail stops the task with StopTask, which MaaFW books Succeeded (the 10-16
# CreditShoppingBuyItemStop check above); the end step is read whatever is booked.
booked_failed = splice(GIFT_AFTER_UI, steps)
st, ev, pushed = run_1013(lambda text: booked_failed(text).replace(
    '[msg=Tasker.Task.Succeeded] [details={"entry":"GiftOperatorMain"',
    '[msg=Tasker.Task.Failed] [details={"entry":"GiftOperatorMain"'))
check("…the same when MaaFW books that stop as Failed", (st, "礼物都已送满，算没东西可做" in ev), ("PASS", True))

print("\n[送礼：只碰到一次送满、后面什么也没有 → 不算没东西可做]")
# Not a normal end: GiftFull's only next is GiftFullLeave, and when nothing more is
# logged MaaFW did not get on (on_error, the task booked Failed); an all-full run logs
# GiftFullFail, as a StopTask node is logged (10-16 13:58:58.769 above).
steps, _ = chain(30.0, FULL)
st, ev, pushed = run_1013(splice(GIFT_AFTER_UI, steps))
check("GiftFull alone is not an end (its next is the retry): FAIL, pushed", (st, len(pushed)), ("FAIL", 1))

# ---- The ledger's 「没证据」 reads the same MaaFW judgment, not the picture ------------
print("\n[账本：四个任务有没有证据看终末地自己的记录，桌面截图不算]")
abort_log = FIX / "2026-10-08_MaaEnd-06-31-06.log"
araw = collector_maaend.parse_maaend_log(abort_log)
check("the log alone has a line inside 装备制造 (MaaEnd's scene-check note)",
      bool((araw.get("tasks_evidence") or {}).get("装备制造")), True)
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
if fails:
    print(f"✗ {len(fails)} 条没过：{fails}")
    sys.exit(1)
print("all checks passed")
