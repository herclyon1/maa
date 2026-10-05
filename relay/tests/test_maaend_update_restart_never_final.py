"""A done MaaEnd round followed by MaaEnd restarting into its new build never ends in an alarm.

The operator, 2026-10-06: the only two group alarms of three days were both false,
10-04 09:51:26 and 10-05 11:30:44 (Beijing), each 「❌ MaaEnd 最终失败，告警已推送（尝试
2 次）」 right after 「✅ MaaEnd … 静默记账」 and 「↪️ … 是装新版 v2.32.0-beta.x 后的自重启，
先压着看后面的重试」. The user on it, 10-05 13:07: 「他不要再报错了」. Main fixed it on
10-05 (handle._drop_update_after_done, unresolved.done_in_shift); this drives the
same records through handle and the push step and pins that nothing reaches the
group - no alarm, no 「最终失败」, no WARNING / ERROR line (errwatch pushes those):

* the records as they landed (success, then the restart, then the push step);
* the restart landing while the shift could not be looked up (it is held), the
  push step then finds the done round and lets it go (handle._update_restart_done);
* the restart landing first, the success after it;
* a restart whose every task failed at once (the 「never got into the game」 shape):
  no 「像没进游戏…按普通失败处理」 WARNING about it (handle._confirm_unreachable).
Red on the code that sent those two alarms.
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

from ark_relay import collect_retry, handle               # noqa: E402
try:   # absent from the code that sent the two alarms (8f8250ea); the test still runs there
    from ark_relay import unresolved
except ImportError:
    unresolved = None
from ark_relay import engine as eng_mod                   # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core import State                          # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def automas_dir() -> Path:
    """AUTO-MAS config as on the machine: 早班 09:00 runs MaaEnd, 晚班 21:30 is MAA only."""
    root = tmpdir()
    (root / "config").mkdir()
    paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
    sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
    for k, p in paths.items():
        sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
    qc = {"instances": []}
    for n, (name, times, kinds) in enumerate((("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]),
                                              ("晚班", ["21:30"], ["MAA"]))):
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


MACHINE = automas_dir()


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []

    def send_group(self, title, body=""):
        self.sent.append((title, body, True))
        return []


class Src:
    def fetch(self, seen):
        return []


class Lines(logging.Handler):
    """Every ark.* line, with its level: a WARNING / ERROR one reaches the group (errwatch)."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append((record.levelno, record.getMessage()))


LINES = Lines()
ARK = logging.getLogger(handle.log.name.rsplit(".", 1)[0])
ARK.addHandler(LINES)
ARK.setLevel(logging.DEBUG)

handle._ship_evidence = lambda eng, rec: ""
handle._weekly_gates = lambda eng, rec: None
collect_retry.restore_master = lambda cfg: ""


def mxu_install(at: datetime, version: str) -> None:
    """MXU's own log for the attempt that installed `version` at its start (real shape, 10-01)."""
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


def restart(day, run, start, raw=None):
    return RunRecord(run_id=f"2026-10-{day:02d}/endfield/MaaEnd-{run}", script="MaaEnd", user="endfield",
                     started=start, finished=start + timedelta(seconds=30), ok=False,
                     failed_tasks=["赠送干员礼物", "据点交易", "日常奖励领取"],
                     raw=dict(raw or {}, maaend_result="MaaEnd 部分任务执行失败: 🎁赠送干员礼物"))


# The two mornings, run ids + 4 h as relay.log shows them (test_maaend_update_after_done.py).
mxu_install(t(4, 9, 50, 53), "v2.32.0-beta.1")
mxu_install(t(5, 11, 30, 14), "v2.32.0-beta.2")


def build():
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = MACHINE
    cfg.maaend_dir = MAAEND
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._verify_outcome = lambda r: None
    e._archive_maaend_evidence = lambda r: None
    return e


def drive(e, recs, flushes=1):
    LINES.lines.clear()
    for r in recs:
        handle._handle(e, r)
    for _ in range(flushes):
        e._flush_pending()


def said(fragment):
    return any(fragment in m for _, m in LINES.lines)


def alarms(e):
    return [ti for ti, _, a in e.notifier.sent if a]


def loud(e):
    """WARNING / ERROR lines: errwatch pushes each one to the group."""
    return [m for lv, m in LINES.lines if lv >= logging.WARNING]


for day, s_run, s_at, mins, r_run, r_at in ((4, "05-26-41", t(4, 9, 26, 41), 23, "05-50-53", t(4, 9, 50, 53)),
                                             (5, "06-39-48", t(5, 10, 39, 48), 49, "07-30-14", t(5, 11, 30, 14))):
    S, R = success(day, s_run, s_at, mins), restart(day, r_run, r_at)
    print(f"\n[10-0{day} as it landed: {S.run_id} done, then {R.run_id} restarts into its new build, then the push step]")
    e = build()
    drive(e, [S, R], flushes=2)
    check("the round was booked silently (「✅ … 静默记账」)", said(f"✅ MaaEnd {S.run_id}（{mins} 分钟）静默记账"))
    check("no 「最终失败」", said("最终失败"), False)
    check("no alarm of any kind went to the group", alarms(e), [])
    check("no WARNING / ERROR line (errwatch would push it)", loud(e), [])
    check("nothing held for a later push", dict(e._pending), {})

print("\n[the shift could not be looked up when the restart landed: held; the push step lets it go]")
S, R = success(4, "05-26-41", t(4, 9, 26, 41), 23), restart(4, "05-50-53", t(4, 9, 50, 53))
e = build()
real = getattr(unresolved, "done_in_shift", None) if unresolved is not None else None
check("unresolved.done_in_shift exists", real is not None)
if real is not None:
    calls = []

    def flaky(eng, rec):
        calls.append(rec.run_id)
        if len(calls) == 1:
            raise OSError("ledger busy")
        return real(eng, rec)
    unresolved.done_in_shift = flaky
    try:
        LINES.lines.clear()
        handle._handle(e, S)
        handle._handle(e, R)
        check("held when the lookup failed", list(e._pending), [("MaaEnd", "endfield")])
        e._flush_pending()
        e._flush_pending()
    finally:
        unresolved.done_in_shift = real
    check("let go at the push step: nothing held", dict(e._pending), {})
    check("no alarm went to the group", alarms(e), [])
    check("no 「最终失败」", said("最终失败"), False)
    check("the log says why", said(f"{R.run_id} 前面那趟已经做完（{S.run_id}）"))
    led = {x["run_id"]: x for x in e.state.read_ledger("2026-10-04")}
    check("the ledger books the restart as the update",
          (led[R.run_id].get("raw") or {}).get("maaend_update_after_done"), S.run_id)

print("\n[the restart lands first, the done round after it]")
S, R = success(5, "06-39-48", t(5, 10, 39, 48), 49), restart(5, "07-30-14", t(5, 11, 30, 14))
e = build()
drive(e, [R, S], flushes=2)
check("no alarm went to the group", alarms(e), [])
check("no 「最终失败」", said("最终失败"), False)
check("no WARNING / ERROR line", loud(e), [])
check("nothing held", (dict(e._pending), dict(e._recovered)), ({}, {}))

print("\n[every task of the restart failed at once (the 「never got into the game」 shape)]")
S = success(4, "05-26-41", t(4, 9, 26, 41), 23)
R = restart(4, "05-50-53", t(4, 9, 50, 53), raw={"maaend_unreachable_shape": True})
e = build()
drive(e, [S, R], flushes=2)
check("no 「像没进游戏…按普通失败处理」 WARNING about the restart", [m for m in loud(e) if "像没进游戏" in m], [])
check("no WARNING / ERROR line at all", loud(e), [])
check("no alarm went to the group", alarms(e), [])
check("the record carries no 「never got in」 note for an alarm", R.raw.get("maaend_unreachable_shape"), None)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
