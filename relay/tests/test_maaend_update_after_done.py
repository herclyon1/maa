"""MaaEnd restarting itself into a new build after its shift's round was done: no make-up, no push.

relay.log, 10-04 09:51:26 (and the same shape 10-05 11:30:44), three lines in one
second: the round 2026-10-04/endfield/MaaEnd-05-26-41 booked as done (静默记账),
the attempt MaaEnd-05-50-53 held as MaaEnd's restart into v2.32.0-beta.1, then
the final failure pushed to the group (「最终失败，告警已推送（尝试 2 次）」).

The round had got everything done; the next attempt was only MaaEnd installing
v2.32.0-beta.1 and restarting. With no success after it, it was pushed as the
final failure; with the make-up rules it would have been held, given no make-up
and pushed to the group as unresolved. The user, 10-05 13:07: 「中继我就要求一个，
他不要再报错了」 - from then until 2026-10-06 such an attempt was a log line only.
His order of 2026-10-06, 「不论多少次什么错误都要发」, put it in the group under its
own title (「⚠️ 终末地装新版重启了这一趟（前面那趟已做完）」); at 05:07 that day he
took that back for what had recovered: 「报错后自己好了的，只进日报、不进群。」 The
round was done, so nothing is left broken. Pinned here:

* success first, then the update restart, in the same shift -> not held, no
  make-up, nothing pushed, one log line saying 「只进日报」; the ledger keeps it,
  and the daily report books it as the update (a ↪️ row naming the build), not
  as a failure;
* the same pair arriving the other way round -> the same;
* the success was in another shift -> the restart is held and rings as before;
* a success that left work undone does not count;
* 10-05's pair (06-39-48 / 07-30-14, v2.32.0-beta.2) -> dropped as well.

Started times are the run ids + 4 h, which matches every number in relay.log:
10-04 09:26:41 + 23 min ends 09:49, the restart starts 09:50:53, the records
land 09:51:26; 10-05 10:39:48 + 49 min ends 11:28, restart 11:30:14, land 11:30:44.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
MAAEND = TMP / "maaend"
(MAAEND / "debug").mkdir(parents=True)
(TMP / "history").mkdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_MAAEND_DIR=str(MAAEND),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collect_retry, core, handle, unresolved   # noqa: E402
from ark_relay import engine as eng_mod                         # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord       # noqa: E402
from ark_relay.core import State                                # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def automas_dir(queues) -> Path:
    """An AUTO-MAS config dir shaped like the machine's: queues = [(name, [times], [kinds])]."""
    root = tmpdir()
    (root / "config").mkdir()
    paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
    sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
    for k, p in paths.items():
        sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
    qc = {"instances": []}
    for n, (name, times, kinds) in enumerate(queues):
        uid = f"q{n}"
        qc["instances"].append({"uid": uid})
        ts = {"instances": []}
        for i, t in enumerate(times):
            ts[f"t{i}"] = {"Info": {"Enabled": True, "Time": t}}
        items = {"instances": []}
        for i, k in enumerate(kinds):
            items[f"i{i}"] = {"Info": {"ScriptId": f"s-{k}"}}
        qc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                   "SubConfigsInfo": {"TimeSet": ts, "QueueItem": items}}
    (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
    (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
    return root


# The machine: 早班 09:00 runs MaaEnd, 晚班 21:30 is MAA only.
MACHINE = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA"])])
# For the other-shift case MaaEnd has to be in both.
BOTH = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA", "MaaEnd"])])


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return False


class Src:
    def fetch(self, seen):
        return []


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


LINES = Lines()
handle.log.addHandler(LINES)
handle.log.setLevel(logging.DEBUG)

handle._ship_evidence = lambda eng, rec: ""
handle._weekly_gates = lambda eng, rec: None
collect_retry.restore_master = lambda cfg: ""


def mxu_install(at: datetime, version: str) -> None:
    """MXU's own log for the attempt that installed `version` at its start."""
    f = MAAEND / "debug" / f"{at:%Y-%m-%d}-1.log"
    old = f.read_text(encoding="utf-8") if f.exists() else ""
    s = at.strftime("%Y-%m-%d %H:%M:%S")
    f.write_text(old + "\n".join([
        f"{s} INFO  [App] 检测到待安装更新: {version}",
        f"{s} INFO  [App] 开始安装更新: D:/ark/maaend/cache\\11002.zip -> D:\\ark\\maaend",
        f"{s} INFO  [App] 更新安装完成",
        f"{s} INFO  [App] 已清除待安装更新信息",
    ]) + "\n", encoding="utf-8")


def t(day, hh, mm, ss=0):
    return datetime(2026, 10, day, hh, mm, ss, tzinfo=SERVER_TZ)


def success(day, run, start, minutes):
    return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                     started=start, finished=start + timedelta(minutes=minutes), ok=True, failed_tasks=[],
                     raw={"maaend_result": "Success!"})


def restart(day, run, start):
    return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                     started=start, finished=start + timedelta(seconds=30), ok=False,
                     failed_tasks=["赠送干员礼物", "据点交易", "日常奖励领取"],
                     raw={"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物"})


mxu_install(t(4, 9, 50, 53), "v2.32.0-beta.1")
mxu_install(t(4, 21, 50, 53), "v2.32.0-beta.9")
mxu_install(t(5, 11, 30, 14), "v2.32.0-beta.2")
S4 = success(4, "05-26-41", t(4, 9, 26, 41), 23)
R4 = restart(4, "05-50-53", t(4, 9, 50, 53))
S5 = success(5, "06-39-48", t(5, 10, 39, 48), 49)
R5 = restart(5, "07-30-14", t(5, 11, 30, 14))


def build(automas, undone=None):
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = automas
    cfg.maaend_dir = MAAEND
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._verify_outcome = lambda r: undone
    e._archive_maaend_evidence = lambda r: None
    e._alert_key = lambda r: handle._alert_key(e, r)
    return e


def run(e, recs):
    LINES.lines.clear()
    for r in recs:
        handle._handle(e, r)
    e._flush_pending()
    return [(ti, b) for ti, b, a in e.notifier.sent if a]


def said(fragment):
    return any(fragment in ln for ln in LINES.lines)


DROPPED = "前面那趟已经做完"

print("[10-04 as it landed: success, then the update restart, same second, same shift]")
e = build(MACHINE)
got = run(e, [S4, R4])
check("nothing to the group", got, [])
check("no notice of any kind (not Server酱 either)", e.notifier.sent, [])
check("not held", dict(e._pending), {})
check("no self-heal either", dict(e._recovered), {})
check("the log says the earlier round was done, this was the update, daily report only",
      said(f"{R4.run_id} 前面那趟已经做完（{S4.run_id}），这趟是装新版 v2.32.0-beta.1 重启，只进日报"))
check("no 「先压着」", said("先压着看后面的重试"), False)
check("no 「最终失败」", said("最终失败"), False)
ledger = {x["run_id"]: x for x in e.state.read_ledger("2026-10-04")}
check("the restart stays in the ledger, named as the update",
      (ledger.get(R4.run_id, {}).get("raw") or {}).get("maaend_update_restart"), "v2.32.0-beta.1")
check("the success stays in the ledger", ledger.get(S4.run_id, {}).get("ok"), True)
entries = e.state.read_ledger("2026-10-04")
check("daily report books the restart as the update", core.episode_kinds(entries).get(R4.run_id), "update")
title, body = core.format_daily("2026-10-04", entries)
print("    " + title)
print("    " + body.replace("\n", "\n    ")[:500])
check("the daily title counts no MaaEnd failure", "终末地失败" in title, False)
check("the daily row says it was the update", "MaaEnd 装新版 v2.32.0-beta.1 后自己重启，用掉一次重试，不算失败" in body)
e._flush_pending()
check("a later tick says nothing", e.notifier.sent, [])
handle._handle(e, R4)      # the same record replayed (handling broke off midway)
check("a replay of the same record says nothing either", e.notifier.sent, [])

print("\n[the same pair the other way round: the update restart lands first]")
e = build(MACHINE)
got = run(e, [R4, S4])
check("nothing to the group", got, [])
check("not held", dict(e._pending), {})
check("not turned into a self-heal", dict(e._recovered), {})
check("the log says why", said(f"{R4.run_id} 前面那趟已经做完（{S4.run_id}）"))
check("no 「重试后成功」 (nothing was retried)", said("重试后成功"), False)
check("no notice of any kind", e.notifier.sent, [])
check("the daily report books it as the update too",
      core.episode_kinds(e.state.read_ledger("2026-10-04")).get(R4.run_id), "update")

print("\n[10-05 as it landed: 06-39-48 done, 07-30-14 installs v2.32.0-beta.2]")
e = build(MACHINE)
got = run(e, [S5, R5])
check("nothing to the group", got, [])
check("not held", dict(e._pending), {})
check("the log says why", said(f"{R5.run_id} 前面那趟已经做完（{S5.run_id}），这趟是装新版 v2.32.0-beta.2 重启，只进日报"))

print("\n[the success was in another shift: the restart is held and rings as before]")
late = restart(4, "17-50-53", t(4, 21, 50, 53))
e = build(BOTH)
check("the two are in different shifts",
      (unresolved.where(e, S4)[1], unresolved.where(e, late)[1]), ("早班", "晚班"))
got = run(e, [S4, late])
check("not dropped", said(DROPPED), False)
check("held, then one alarm for 晚班", (len(got), bool(got) and "晚班" in got[0][0]), (1, True))
e = build(BOTH)
got = run(e, [late, S4])
check("reverse order: not dropped either", said(DROPPED), False)
check("the daily report does not hide it", core.episode_kinds(e.state.read_ledger("2026-10-04")).get(late.run_id), None)

print("\n[a success that left work undone does not count]")
e = build(MACHINE, undone="MaaEnd 这一轮有 1 项没干成：\n· 据点交易：没做")
LINES.lines.clear()
handle._handle(e, S4)
handle._handle(e, R4)
check("not dropped", said(DROPPED), False)
check("held as before", list(e._pending), [("MaaEnd", "endfield")])
e = build(MACHINE, undone="MaaEnd 这一轮有 1 项没干成：\n· 据点交易：没做")
LINES.lines.clear()
handle._handle(e, R4)
handle._handle(e, S4)
check("reverse order: not dropped either", said(DROPPED), False)
check("reverse order: the held restart takes the usual path (retry healed)",
      (list(e._pending), list(e._recovered)), ([], [("MaaEnd", "endfield")]))
check("reverse order: not marked as the update on the ledger",
      ({x["run_id"]: x for x in e.state.read_ledger("2026-10-04")}[R4.run_id].get("raw") or {})
      .get("maaend_update_after_done"), None)

print("\n[a success stopped by the red button does not count]")
e = build(MACHINE)
e.state.append_ledger(S4)
e.state.mark_raw("2026-10-04", S4.run_id, "manual_stop", "10-04 09:49 停一切")
check("no done round", unresolved.done_in_shift(e, R4), "")
e.state.mark_raw("2026-10-04", S4.run_id, "manual_stop", "")
check("without the stop it is the done round", unresolved.done_in_shift(e, R4), S4.run_id)

print("\n[without any success the restart is held as before (10-01's path)]")
e = build(MACHINE)
LINES.lines.clear()
handle._handle(e, R4)
check("held", list(e._pending), [("MaaEnd", "endfield")])
check("「先压着」 as before", said("先压着看后面的重试"))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
