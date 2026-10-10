"""MaaEnd task-end screenshots, and the evidence bundle every MAA / MaaEnd alarm carries.

2026-10-05: four MaaEnd tasks (gifts, gear assembly, delivery jobs, environment
monitoring) leave only 「任务开始」 / 「任务完成」 in the AUTO-MAS log, so whether they did anything could not be
checked; and the 12:30 MaaEnd alarm (an update restart, MaaEnd-07-30-14) went
out without a bundle, because the update-restart branch held the record before
_hold_for_retry could ship one.

The maafw.log lines are built in the shape of the real ones
(fixtures/collect-watch-2026-09-14/maafw-attempt3.log, each event once from the
dispatcher and once echoed by the agent); entries, task numbers and times are
2026-10-05's: entries and task_ids from MXU's debug/2026-10-05-2.log (10:41:05 /
10:41:07), times from AUTO-MAS history MaaEnd-06-39-48.log.
"""
import json
import logging
import os
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(TMP / "history").mkdir()
MAAEND = TMP / "maaend"
(MAAEND / "debug").mkdir(parents=True)
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_MAAEND_DIR=str(MAAEND), ARK_STATE_DIR=str(TMP / "state"),
                  SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                  WECOM_BOT_URL="", ARK_PHONE_TOPIC="", COS_SECRET_ID="", COS_SECRET_KEY="",
                  COS_BUCKET="", COS_REGION="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collect_retry, collect_watch, evidence, handle, task_shots, texts  # noqa: E402
from ark_relay import engine as eng_mod                  # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.ledger import State                         # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


# --------------------------------------------------------------- 10-05's round
# (start time, end time, label as AUTO-MAS prints it, MaaFW entry)
ROUND = [
    ("10:41:07", "10:43:33", "🎁赠送干员礼物", "GiftOperatorMain"),
    ("10:43:33", "10:43:53", "🔧装备制造", "GearAssemblyStart"),
    ("10:43:53", "10:45:58", "🤝拜访好友", "VisitFriendsMain"),
    ("10:45:59", "10:46:43", "🎁基建任务", "DijiangRewards"),
    ("10:46:43", "10:49:09", "🛍️信用点购物", "CreditShoppingMain"),
    ("10:49:09", "10:50:55", "🚚转交委托", "DeliveryJobsMain"),
    ("10:50:55", "10:52:16", "🛒据点交易", "OutpostTradingSchedule"),
    ("10:52:16", "10:52:22", "🌿环境监测", "EnvironmentMonitoringMain"),
    ("10:52:22", "10:52:43", "📦自动囤货", "AutoStockpileMain"),
    ("10:52:43", "10:53:07", "💰售卖弹性物资", "AutoSellMain"),
    ("10:53:08", "10:54:48", "🏪购买稳定物资", "AutoStockStapleSchedule"),
    ("10:54:48", "10:58:00", "⚔️协议空间", "ProtocolSpaceSchedule"),
    ("10:58:00", "11:01:54", "🗡️选剑演武", "TrialOfSwordmancyMain"),
    ("11:01:54", "11:28:22", "🧺自动采集", "AutoCollectSchedule"),
    ("11:28:22", "11:30:10", "📅日常奖励领取", "DailyRewardStart"),
    ("11:30:10", "11:30:13", "❌关闭游戏（PC）", "CloseGamePC"),
]
LABELS = {entry: label for _, _, label, entry in ROUND}


def ev(day, hms, kind, entry, task_id, px="7172"):
    details = json.dumps({"entry": entry, "hash": "1dd55aee6e9ac409", "task_id": task_id,
                          "uuid": "00000000001E0236"}, separators=(",", ":"))
    return (f"[{day} {hms}.264][INF][Px{px}][Tx32558][Utils/EventDispatcher.hpp][L65]"
            f"[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] "
            f"[msg=Tasker.Task.{kind}] [details={details}] ")


def round_lines(day="2026-10-05", first_id=200000001, rows=ROUND):
    out = []
    for i, (t0, t1, _, entry) in enumerate(rows):
        tid = first_id + i
        for kind, hms in (("Starting", t0), ("Succeeded", t1)):
            out.append(ev(day, hms, kind, entry, tid))
            out.append(ev(day, hms, kind, entry, tid, px="18500"))   # the agent's echo
    return out


class Cam:
    """A fake desktop: writes a file, or raises on the calls listed in `bad`."""

    def __init__(self, bad=()):
        self.calls, self.bad = [], set(bad)

    def __call__(self, out_dir, name):
        self.calls.append(name)
        if len(self.calls) in self.bad:
            raise OSError("desktop agent did not come up")
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"{name}.png"
        p.write_bytes(b"\x89PNG fake " + name.encode())
        return p


class Cfg:
    automas_dir = AUTOMAS
    maaend_dir = MAAEND
    state_dir = TMP / "watch-state"


print("[10-05's round: one picture per 任务完成, plus the first 任务开始]")
cam = Cam()
shooter = task_shots.Shooter(Cfg.state_dir, LABELS, cam)
w = collect_watch.Watcher(Cfg, None, shooter)
w.feed("\n".join(round_lines()))
check("nothing taken on the watcher's thread", cam.calls, [])
check("17 queued (16 ends + the first start)", shooter.queue.qsize(), 17)
check("all 17 taken", shooter.drain(), 17)
run = Cfg.state_dir / "shots" / "2026-10-05" / "MaaEnd-10-41-07"
names = sorted(p.name for p in run.iterdir())
check("first: the 'before' picture", names[0], "104107-赠送干员礼物.png")
check("the four that read nothing are all there",
      all(f in names for f in ("104333-赠送干员礼物.png", "104353-装备制造.png",
                               "105055-转交委托.png", "105222-环境监测.png")), True)
check("last: 关闭游戏（PC）, emoji gone", names[-1], "113013-关闭游戏（PC）.png")
check("the echo does not double anything", len(names), 17)

print("\n[a picture that fails does not stop the next ones; one warning per run]")
cam = Cam(bad={2, 3})
shooter = task_shots.Shooter(TMP / "s2", LABELS, cam)
w = collect_watch.Watcher(Cfg, None, shooter)
w.feed("\n".join(round_lines()[:12]))        # first three tasks: 1 start + 3 ends
class Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


grab = Grab()
task_shots.log.addHandler(grab)
check("4 tried, 2 saved", (shooter.drain(), len(cam.calls)), (2, 4))
check("one warning for the run", sum("任务截图没拿到" in m for m in grab.msgs), 1)
check("the ones after the failures still saved",
      sorted(p.name for p in (TMP / "s2" / "shots" / "2026-10-05" / "MaaEnd-10-41-07").iterdir()),
      ["104107-赠送干员礼物.png", "104558-拜访好友.png"])

print("\n[a relaunch (MaaFW numbers from 200000001 again) is a new run with its own 'before' picture]")
cam = Cam()
shooter = task_shots.Shooter(TMP / "s3", LABELS, cam)
w = collect_watch.Watcher(Cfg, None, shooter)
w.feed("\n".join(round_lines()[:8]))
w.feed("\n".join(round_lines(rows=[("11:35:00", "11:36:00", "🤝拜访好友", "VisitFriendsMain")])))
shooter.drain()
check("two run folders", sorted(p.name for p in (TMP / "s3" / "shots" / "2026-10-05").iterdir()),
      ["MaaEnd-10-41-07", "MaaEnd-11-35-00"])
check("the relaunch's first start and its end",
      sorted(p.name for p in (TMP / "s3" / "shots" / "2026-10-05" / "MaaEnd-11-35-00").iterdir()),
      ["113500-拜访好友.png", "113600-拜访好友.png"])
print("    自动采集 runs 26 minutes without a task event; that is not a new run")
cam = Cam()
shooter = task_shots.Shooter(TMP / "s4", LABELS, cam)
for ln in round_lines():
    shooter.on_line(ln)
shooter.drain()
check("one folder for the whole round", [p.name for p in (TMP / "s4" / "shots" / "2026-10-05").iterdir()],
      ["MaaEnd-10-41-07"])

print("\n[entry -> name comes from MaaEnd's own task declarations and zh_cn locale]")
(MAAEND / "tasks").mkdir()
(MAAEND / "interface.json").write_text(json.dumps({"version": "v2.32.0-beta.1",
                                                    "import": ["tasks/GiftOperator.json"]}), encoding="utf-8")
(MAAEND / "tasks" / "GiftOperator.json").write_text(json.dumps({"task": [
    {"name": "GiftOperator", "label": "$task.GiftOperator.label", "entry": "GiftOperatorMain"}]}), encoding="utf-8")
(MAAEND / "locales" / "interface").mkdir(parents=True)
(MAAEND / "locales" / "interface" / "zh_cn.json").write_text(json.dumps(
    {"task.GiftOperator.label": "🎁赠送干员礼物"}, ensure_ascii=False), encoding="utf-8")
check("GiftOperatorMain", task_shots.entry_labels(MAAEND), {"GiftOperatorMain": "🎁赠送干员礼物"})
check("no MaaEnd dir", task_shots.entry_labels(None), {})
cam = Cam()
shooter = task_shots.Shooter(TMP / "s5", {}, cam)
shooter.on_line(ev("2026-10-05", "10:43:33", "Succeeded", "GiftOperatorMain", 200000001))
shooter.drain()
check("unknown entry -> named by the entry", cam.calls, ["104333-GiftOperatorMain"])

print("\n[off Windows nothing is started]")
check("start() is None here", task_shots.start(Cfg) if os.name != "nt" else None, None)

print("\n[evidence.desktop_shot: name it, move the agent's file]")
src = TMP / "agent-shot.png"
src.write_bytes(b"png")
got = evidence.desktop_shot(Cfg, TMP / "out", lambda: src, name="104333-赠送干员礼物", move=True, quiet=True)
check("named", got and got.name, "104333-赠送干员礼物.png")
check("moved, not copied", (src.exists(), got.read_bytes() if got else b""), (False, b"png"))


def boom():
    raise OSError("no desktop")


check("a failing agent -> None", evidence.desktop_shot(Cfg, TMP / "out", boom, quiet=True), None)

print("\n[retention: 3 days; only day folders under state/shots/]")
st = TMP / "ret"
for d in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"):
    (st / "shots" / d / "MaaEnd-10-00-00").mkdir(parents=True)
    (st / "shots" / d / "MaaEnd-10-00-00" / "x.png").write_bytes(b"x")
(st / "shots" / "notes").mkdir()
(st / "evidence").mkdir()
gone = task_shots.prune(st, today=date(2026, 10, 5))
check("removed", gone, ["2026-10-01", "2026-10-02"])
check("kept", sorted(p.name for p in (st / "shots").iterdir()), ["2026-10-03", "2026-10-04", "2026-10-05", "notes"])
check("nothing else touched", (st / "evidence").is_dir(), True)
check("no shots folder -> nothing", task_shots.prune(TMP / "none"), [])

# ---------------------------------------------------------------- Part B
print("\n[the update-restart record that is held ships its bundle at once, with the task pictures]")


class Notes:
    def __init__(self, fail_first=0):
        self.sent, self.fail_first = [], fail_first

    def send(self, title, body="", **kw):
        if kw.get("alert") and self.fail_first:
            self.fail_first -= 1
            return ["push down"]
        self.sent.append((title, body, kw.get("alert", False)))
        return []


class Src:
    def fetch(self, seen):
        return []


class Up:
    def __init__(self):
        self.files = []

    def upload(self, p):
        self.files.append(p)
        return {"page": "https://cos.example/ev/MaaEnd.zip", "store": "cos"}


def at(hh, mm, ss=0):
    return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)


# MXU's own log of the attempt that installed v2.31.0-beta.6 (verbatim, 2026-10-01-4.log)
(MAAEND / "debug" / "2026-10-01-4.log").write_text("\n".join([
    "2026-10-01 16:11:06 INFO  [App] 检测到待安装更新: v2.31.0-beta.6",
    "2026-10-01 16:11:06 INFO  [App] 开始安装更新: D:/ark/maaend/cache\\10697.zip -> D:\\ark\\maaend",
    "2026-10-01 16:11:07 INFO  [App] 更新安装完成",
]) + "\n", encoding="utf-8")
collect_retry.restore_master = lambda cfg: ""
handle._weekly_gates = lambda eng, rec: None
up = Up()
evidence.uploaders = lambda cfg, run_id: [up]
evidence.context_files = lambda cfg, window, dst, relay_until=None: []


def build(notes=None):
    cfg = Config()
    cfg.state_dir = tmpdir()
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=notes or Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._verify_outcome = lambda r: None
    e._alert_key = lambda r: handle._alert_key(e, r)
    return e


e = build()
shot_dir = Path(e.cfg.state_dir) / "shots" / "2026-10-01" / "MaaEnd-16-11-06"
shot_dir.mkdir(parents=True)
inside = shot_dir / "161130-赠送干员礼物.png"
inside.write_bytes(b"\x89PNG in window")
os.utime(inside, (at(16, 11, 30).timestamp(),) * 2)
outside = shot_dir / "090000-装备制造.png"
outside.write_bytes(b"\x89PNG other run")
os.utime(outside, (at(9, 0).timestamp(),) * 2)
rec = RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-10-02", script="MaaEnd", user="endfield",
                started=at(16, 11, 6), finished=at(16, 11, 6), ok=False, failed_tasks=["赠送干员礼物"],
                raw={"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物"})
handle._handle(e, rec)
held = e._pending.get(("MaaEnd", "endfield"))
check("held as an update restart", bool(held and held.raw.get("maaend_update_restart")), True)
check("one bundle uploaded", len(up.files), 1)
check("page on rec.raw", held and held.raw.get("evidence_page"), "https://cos.example/ev/MaaEnd.zip")
inner = zipfile.ZipFile(up.files[0]).namelist() if up.files else []
check("the run's task picture is in the bundle", "161130-赠送干员礼物.png" in inner, True)
check("another run's picture is not", "090000-装备制造.png" in inner, False)
e._flush_pending()
got = [(t, b) for t, b, a in e.notifier.sent if a]
check("the final alarm went out", len(got), 1)
check("it carries the link", bool(got) and "https://cos.example/ev/MaaEnd.zip" in got[0][1], True)
check("no 'not shipped' line", bool(got) and texts.EVIDENCE_NOT_SHIPPED in got[0][1], False)
check("no second upload at alarm time", len(up.files), 1)

print("\n[final alarm with no link: _ship_evidence once before the send; still nothing -> one line in the body]")
calls = []
real_ship = handle._ship_evidence


def ship_fails(eng, r):
    calls.append(r.run_id)
    return ""


handle._ship_evidence = ship_fails
e = build(Notes(fail_first=1))
bare = RunRecord(run_id="2026-10-01/endfield/MaaEnd-12-30-00", script="MaaEnd", user="endfield",
                 started=at(12, 30), finished=at(12, 40), ok=False, failed_tasks=["自动采集"],
                 raw={"maaend_result": "MaaEnd 部分任务执行失败: 🧺自动采集"})
e._pending[("MaaEnd", "endfield")] = bare
e._flush_pending()
check("tried once before the send", calls, [bare.run_id])
check("push failed -> still held", ("MaaEnd", "endfield") in e._pending, True)
e._flush_pending()
check("the retry of the push does not upload again", calls, [bare.run_id])
got = [(t, b) for t, b, a in e.notifier.sent if a]
check("alarm sent on the second tick", len(got), 1)
check("body has the one line", bool(got) and got[0][1].count(texts.EVIDENCE_NOT_SHIPPED), 1)
print("    " + (got[0][1].replace("\n", "\n    ")[:400] if got else ""))

print("\n[same, but the late upload works -> the alarm carries the link and no extra line]")
calls.clear()


def ship_works(eng, r):
    calls.append(r.run_id)
    r.raw["evidence_page"] = "https://cos.example/late.zip"
    return "https://cos.example/late.zip"


handle._ship_evidence = ship_works
e = build()
e._pending[("MaaEnd", "endfield")] = RunRecord(
    run_id="2026-10-01/endfield/MaaEnd-12-31-00", script="MaaEnd", user="endfield",
    started=at(12, 31), finished=at(12, 40), ok=False, failed_tasks=["自动采集"],
    raw={"maaend_result": "MaaEnd 部分任务执行失败: 🧺自动采集"})
e._flush_pending()
got = [(t, b) for t, b, a in e.notifier.sent if a]
check("shipped once", len(calls), 1)
check("link in the alarm", bool(got) and "https://cos.example/late.zip" in got[0][1], True)
check("no 'not shipped' line", bool(got) and texts.EVIDENCE_NOT_SHIPPED in got[0][1], False)

print("\n[an OK-WW final alarm (the generic path) gets the same treatment]")
calls.clear()
handle._ship_evidence = ship_fails
e = build()
e._pending[("OK-WW", "wuwa")] = RunRecord(
    run_id="2026-10-01/wuwa/OK-WW-09-00-00", script="OK-WW", user="wuwa",
    started=at(9, 0), finished=at(9, 30), ok=False, failed_tasks=["周本"], raw={"general_result": "周本失败"})
e._flush_pending()
got = [(t, b) for t, b, a in e.notifier.sent if a]
check("tried once", len(calls), 1)
check("line in the body", bool(got) and texts.EVIDENCE_NOT_SHIPPED in got[0][1], True)
handle._ship_evidence = real_ship

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
