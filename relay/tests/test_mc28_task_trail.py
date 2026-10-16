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


def judge(log, end_dir, state=None, files=None):
    path = log if isinstance(log, Path) else FIX / log
    text = path.read_text(encoding="utf-8")
    raw = collector_maaend.parse_maaend_log(path)
    if files:
        raw["tasks_shot_files"] = files
    day, run = path.name.removesuffix(".log").split("_")
    started = datetime.strptime(f"{day} {run[7:]}", "%Y-%m-%d %H-%M-%S").replace(tzinfo=SERVER_TZ)
    rec = RunRecord(run_id=f"{day}/endfield/{run}", script="MaaEnd", user="endfield", started=started,
                    finished=started + timedelta(hours=1), ok=True, failed_tasks=[], raw=raw)
    n = N()
    got = dict(mc.judge(state or tmpdir(), "run", {"rec": rec, "raw": raw, "log_text": text,
                                                   "maaend_dir": str(end_dir)}, notifier=n, now=NOW))
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

print("\n[没有框架日志：第一趟不判，连续两趟判不过]")
state = tmpdir()
empty = tmpdir()
st, _, pushed = judge("2026-10-13_MaaEnd-05-36-57.log", empty, state)
check("first run without MaaFW's log: not judged, nothing pushed", (st, pushed), (None, []))
st, ev, pushed = judge("2026-10-13_MaaEnd-05-36-57.log", empty, state)
check("second in a row: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
check("…saying the four cannot be seen", ev.startswith("连续 2 趟"), True)
st, _, _ = judge("2026-10-13_MaaEnd-05-36-57.log", maaend("maafw-2026-10-13.log.gz"), state)
check("with the log again: judged again", st, "PASS")

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

print()
if fails:
    print(f"✗ {len(fails)} 条没过：{fails}")
    sys.exit(1)
print("all checks passed")
