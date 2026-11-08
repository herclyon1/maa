"""MAA: checks, the close-down post-action, a rejected config, the start watchdog, unreachable and its notes, window overlap, writing the master first.

One part per former file, each run on its own (tests/_parts.py): test_maa_checks.py, test_maa_closedown_postaction.py, test_maa_config_rejected.py, test_maa_start_watchdog.py, test_maa_unreachable_cleared_notes.py, test_maa_window_overlap.py, test_maa_write_master_first.py.
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


def _part_maa_checks():
    """MAA 的结果核对——2026-08-30 之前这里是个洞，第一版判据又太吵。

洞：`_verify_outcome` 走到 MAA 直接 return None（=全干成），
所以 MAA 只要进程正常退出就恒为绿。

太吵：第一版按错误字符串计数判，拿真实日志空跑时 08-29 晚和 08-30 早
**两趟都会被推送**，推的还是已确认无害的噪音。换成结构化判据：
每条任务链都该有一对 TaskChainStart / TaskChainCompleted。

    Formerly test_maa_checks.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.alarm.handle import _maa_app_log
    from ark_relay.features.verify.outcome import maa_checks, summarize

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    CHAINS = ["StartUp", "Fight", "Infrast", "Recruit", "Mall", "Award", "CloseDown"]


    def run(chains=CHAINS, *, drop_end=(), error=(), stopped=(), extra=""):
        """造一段 asst.log：每条链一对 Start/Completed，可指定谁不收尾/谁报错。"""
        out = []
        for c in chains:
            out.append(f'[2026-08-30 09:00:00][INF] TaskChainStart '
                       f'{{"taskchain":"{c}","taskid":1}}')
            if c in error:
                out.append(f'[2026-08-30 09:10:00][INF] TaskChainError '
                           f'{{"taskchain":"{c}","taskid":1}}')
            elif c in stopped:
                out.append(f'[2026-08-30 09:10:00][INF] TaskChainStopped '
                           f'{{"taskchain":"{c}","taskid":1}}')
            elif c not in drop_end:
                out.append(f'[2026-08-30 09:10:00][INF] TaskChainCompleted '
                           f'{{"taskchain":"{c}","taskid":1}}')
        return "\n".join(out) + extra


    def main():
        print("正常一轮：七条链各一对，不许推送")
        check("全绿", summarize(maa_checks(run()), "MAA"), None)

        print("已确认无害的噪音不许把它变成告警")
        noisy = run(extra="\n[2026-08-30 09:05:00][ERR] skill has no recognition result" * 21
                          + "\n[2026-08-30 09:05:00][ERR] Unknown task: FightSeries-OldMethodFlag" * 10
                          + "\n[2026-08-30 09:06:00][TRC] asst::InfrastAbstractTask::on_run_fails | enter")
        check("噪音再多也全绿", summarize(maa_checks(noisy), "MAA"), None)

        print("开了没收尾——这才是「队列卡死、自己不吭声」的形状")
        got = maa_checks(run(drop_end=("Infrast",)))
        check("判失败", any(c.label == "每一项都做到了结尾" and not c.ok for c in got), True)
        check("说出是哪条链",
              any("Infrast" in c.detail for c in got if not c.ok), True)

        print("任务链报错 / 被中止")
        check("Error 判失败",
              any(not c.ok for c in maa_checks(run(error=("Fight",)))), True)
        check("Stopped 判失败",
              any(not c.ok for c in maa_checks(run(stopped=("Mall",)))), True)

        print("已完成的链后面多一条停止回执不算中止（2026-09-22 21:47:10.864 CloseDown 真实形状）")
        late = run(extra='\n[2026-09-22 21:47:11][INF] TaskChainStopped {"taskchain":"CloseDown","taskid":7}')
        check("收尾后的停止回执全绿", summarize(maa_checks(late), "MAA"), None)

        print("一条任务链事件都没有 = 窗口切错，不许当成没问题")
        got2 = maa_checks("随便什么日志，没有 TaskChain")
        check("判失败", any(not c.ok for c in got2), True)
        check("空文本同样不许全绿", summarize(maa_checks(""), "MAA") is not None, True)

        print("_maa_app_log 的切窗：起点和终点都要管")
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            dbg = Path(d) / "debug"
            dbg.mkdir()
            (dbg / "asst.log").write_text(
                "[2026-08-29 21:42:19][TRC] 上一趟\n"
                "  上一趟的续行\n"
                "[2026-08-30 09:09:41][INF] 本趟\n"
                "  本趟的续行\n"
                "[2026-08-30 23:00:00][INF] 下一趟\n",
                encoding="utf-8")
            got3 = _maa_app_log(d, datetime(2026, 8, 30, 9, 0),
                                datetime(2026, 8, 30, 10, 0))
            check("上一趟不带进来", "上一趟" in got3, False)
            check("上一趟的续行也不带", "上一趟的续行" in got3, False)
            check("本趟带进来", "本趟" in got3, True)
            check("本趟的续行带进来", "本趟的续行" in got3, True)
            check("下一趟不带进来（这就是没有上界时的 bug）", "下一趟" in got3, False)

            no_top = _maa_app_log(d, datetime(2026, 8, 30, 9, 0))
            check("不给上界时下一趟会进来（duration_known=False 时的取舍）",
                  "下一趟" in no_top, True)

            check("目录没配返回 None（不是空串——空串会被判据当成全绿）",
                  _maa_app_log(None, datetime(2026, 1, 1)), None)
            check("窗口内一行都没有也返回 None",
                  _maa_app_log(d, datetime(2030, 1, 1)), None)

        print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_maa_closedown_postaction():
    """MAA's CloseDown post-action cut off by AUTO-MAS's own close is not 「开了没收尾」.

Real record, 2026-10-21 (fixtures/maa-2026-10-21/asst-callbacks.log: the task
chain lines of that morning's D:\\ark\\maa\\debug\\asst.log, unchanged). The run
ended with 「任务已全部完成！」 and AllTasksCompleted at 09:19:25.078; MAA's post
action 「退出 明日方舟」 started CloseDown at 09:19:25.579; AUTO-MAS stopped
MAA.exe at 09:19:25.929 and quit LDPlayer instance 1000 itself. CloseDown's
completion receipt never came, and at 09:19:35 the relay pushed 「⚠️ 明日方舟早班
没干完：CloseDown」 to the group (ledger #107).

A CloseDown that starts before the run's tasks are all completed is still a
dangling chain, and any other dangling chain still fails.

    Formerly test_maa_closedown_postaction.py.
    """
    #!/usr/bin/env python3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify.outcome import maa_checks

    LOG = (Path(__file__).parent / "fixtures" / "maa-2026-10-21" / "asst-callbacks.log").read_text(encoding="utf-8")


    def bad(checks):
        return {c.label: c.detail for c in checks if not c.ok}


    require("the real record ends with a CloseDown start and no receipt",
            LOG.rstrip().endswith('"taskchain":"CloseDown","taskid":7,"uuid":"d912769d7cb0ae0a"}')
            or 'TaskChainStart {"taskchain":"CloseDown"' in LOG.splitlines()[-1])
    got = bad(maa_checks(LOG))
    require("CloseDown after AllTasksCompleted is not 「开了没收尾」", "每一项都做到了结尾" not in got, repr(got))

    no_all_done = "\n".join(l for l in LOG.splitlines() if "AllTasksCompleted" not in l)
    require("without AllTasksCompleted a dangling CloseDown still fails",
            "CloseDown" in bad(maa_checks(no_all_done)).get("每一项都做到了结尾", ""))

    lines = LOG.splitlines()
    award_start = next(i for i, l in enumerate(lines) if 'TaskChainStart {"taskchain":"Award"' in l)
    cut_award = "\n".join(l for i, l in enumerate(lines) if not (i > award_start and '"taskchain":"Award"' in l and "Start" not in l))
    require("another dangling chain still fails",
            "Award" in bad(maa_checks(cut_award)).get("每一项都做到了结尾", ""))

    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)
    print("\nall checks passed")


def _part_maa_config_rejected():
    """MAA refusing its own config, a round with no fight, and sanity MAA never read.

Morning shift 2026-10-10 (machine clock): MAA core had no navigation task for
the event stage YW-4, so the GUI could not hand the Fight task over -
gui.log says 「理智作战: 理智作战 序列化失败」 and then 「已停止」, with no
「开始任务: 理智作战」 at all. AUTO-MAS tried three times with the same config,
every record read 「MAA 在完成任务前中止」 with `sanity: 0` and an empty
`sanity_full_at`. The relay then

* held the failure 「⏳ 等重试结果」 for another tick although re-running the same
  config can only be refused again;
* refused the make-up with 「拿不准有没有打过仗」 although the log it had read
  showed not one fight;
* put 「剩余理智 0」 in the alarm although MAA never read sanity that round.

The real files are under tests/fixtures/maa-2026-10-10/: MAA-05-02-18 (the
failed try, json + log), MAA-05-00-01 (the first try, json only) and
MAA-08-05-07 (a normal run at 12:05 the same day: 14 fights on YW-4, sanity 2
with MAA's own refill sentence) as the control.

    Formerly test_maa_config_rejected.py.
    """
    import json
    import os
    import shutil
    from datetime import datetime


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import collector, summary, texts
    from ark_relay.features.alarm import handle
    from ark_relay.features.makeup import makeup
    from ark_relay.core import ledger as core
    from ark_relay.core import engine as eng_mod
    from ark_relay.features.selfcheck import machinecheck as _mc
    from ark_relay.features.verify.collector_maa import parse_maa_log
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State

    _mc.load()
    _mc_real = dict(_mc.CHECKS)
    _mc.CHECKS.clear()     # machine checks have their own tests (tests/test_mc.py)

    FX = Path(__file__).resolve().parent / "fixtures" / "maa-2026-10-10"
    SANITY_UNREAD = getattr(texts, "SANITY_UNREAD", "理智没读到")   # getattr: the red run predates it


    def history(day: str) -> Path:
        """The fixture records under history/<day>/arknights/, log dates moved to `day`
    (a make-up is only for a failure of today, makeup.eligible)."""
        d = HIST / day / "arknights"
        d.mkdir(parents=True, exist_ok=True)
        for f in FX.iterdir():
            if f.suffix == ".log":
                (d / f.name).write_text(f.read_text(encoding="utf-8").replace("2026-10-10", day), encoding="utf-8")
            else:
                shutil.copy(f, d / f.name)
        return d


    print("[MAA 自己不接受配置：从这一趟自己的日志里认出来，写明哪个任务、哪一关]")
    bad = parse_maa_log(FX / "MAA-05-02-18.log")
    good = parse_maa_log(FX / "MAA-08-05-07.log")
    rej = bad.get("maa_config_rejected") or ""
    check("失败那一趟：认出 MAA 不接受配置", bool(rej))
    check("写了任务名「理智作战」和「序列化失败」", ("理智作战" in rej, "序列化失败" in rej), (True, True))
    check("写了关卡 YW-4（取自 GetFightStage 那一行）", "YW-4" in rej)
    check("正常那一趟：没有这一项", "maa_config_rejected" in good, False)

    print("\n[打了几仗：日志读到了就记（0 也记）；读不到就不记，没数据不是零]")
    check("失败那一趟：0 仗", bad.get("fight_count"), 0)
    check("正常那一趟：14 仗（开始行动 1~10、11~14）", good.get("fight_count"), 14)
    check("正常那一趟：打过关的次数照旧", good.get("run_times"), 14)

    day = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    H = history(day)
    r_bad = collector.parse_record(H / "MAA-05-02-18.json", HIST)
    r_first = collector.parse_record(H / "MAA-05-00-01.json", HIST)
    r_good = collector.parse_record(H / "MAA-08-05-07.json", HIST)
    check("只有 json 的那一趟（第一次）：不记打了几仗", "fight_count" in (r_first.raw or {}), False)

    print("\n[理智：MAA 没读到（0 且没有回满时间）就是没读到，不是 0]")
    check("失败那一趟：理智记为没读到", (r_bad.sanity, r_bad.raw.get("sanity_unread")), (None, True))
    check("正常那一趟：理智 2 照旧", (r_good.sanity, r_good.raw.get("sanity_unread")), (2, None))
    _, body = core.format_failure(r_bad)
    check("报警里写「理智没读到」", SANITY_UNREAD in body)
    check("报警里不再写「剩余理智 0」", "剩余理智 0" in body, False)
    check("报警里写 MAA 不接受这份配置、哪个任务、哪一关",
          ("不接受这份配置" in body, "理智作战" in body, "YW-4" in body), (True, True, True))
    check("报警里写「一仗都没打」", "一仗都没打" in body)
    _, body_first = core.format_failure(r_first)
    check("日志都没有的那一趟：不说一仗都没打", "一仗都没打" in body_first, False)


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = AUTOMAS
        e = eng_mod.Engine(cfg, source=type("Src", (), {"fetch": lambda self, seen: []})(),
                           state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        return e


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []


    handle._ship_evidence = lambda eng, rec: ""
    summary.diagnose = lambda *a, **k: ""
    dispatched = []
    makeup._dispatch = lambda script: (dispatched.append(script), (True, "ok"))[1]
    makeup._kill_game = lambda: None

    print("\n[补跑：不接受配置的不补，理由写明；不再说「拿不准」]")
    e = build()
    e.state.append_ledger(r_bad)
    why = makeup.maa_work_done(e, r_bad)
    check("理由：MAA 不接受这份配置（理智作战 序列化失败，关卡 YW-4），原样补跑还是一样",
          why, "MAA 不接受这份配置（理智作战 序列化失败，关卡 YW-4），原样补跑还是一样")
    plain = collector.parse_record(H / "MAA-05-02-18.json", HIST)
    plain.raw.pop("maa_config_rejected", None)
    e = build()
    e.state.append_ledger(plain)
    why0 = makeup.maa_work_done(e, plain)
    check("别的失败、日志里 0 仗：说一仗都没打，不说拿不准", ("一仗都没打" in why0, "拿不准" in why0), (True, False))
    check("还是不补（只有没进游戏的才整轮补跑）", bool(why0))
    unread = collector.parse_record(H / "MAA-05-00-01.json", HIST)
    e = build()
    e.state.append_ledger(unread)
    check("日志读不到：照旧拿不准", "拿不准" in makeup.maa_work_done(e, unread))

    print("\n[整条链：两次失败落地 → 同一轮就进群一次，不压着等重试、不派补跑]")
    e = build()
    for r in (collector.parse_record(H / "MAA-05-00-01.json", HIST),
              collector.parse_record(H / "MAA-05-02-18.json", HIST)):
        e._handle(r)
    e._flush_pending()
    group = [(t, b) for t, b, a in e.notifier.sent if a]
    check("这一轮就进群一次", [t for t, _ in group], [texts.unresolved("明日方舟", "早班")])
    check("不再压着", dict(e._pending), {})
    body = group[-1][1] if group else ""
    check("开头写明没补跑的原因：不接受这份配置", "没补跑：MAA 不接受这份配置（理智作战 序列化失败，关卡 YW-4），原样补跑还是一样" in body)
    check("不再说拿不准", "拿不准" in body, False)
    check("理智没读到，不是 0", (SANITY_UNREAD in body, "剩余理智 0" in body), (True, False))
    makeup.maybe_run(e)
    check("没派补跑", dispatched, [])
    mk = makeup.read_marker(e.cfg.state_dir, day).get("MAA") or {}
    check("当天补跑记成不补，写明原因", (mk.get("result"), "不接受这份配置" in str(mk.get("note"))),
          (makeup.GAVE_UP, True))

    print("\n[记录落地顺序反过来（带原因的先到、只有 json 的后到）：照样这一轮进群、说清原因]")
    e = build()
    for r in (collector.parse_record(H / "MAA-05-02-18.json", HIST),
              collector.parse_record(H / "MAA-05-00-01.json", HIST)):
        e._handle(r)
    e._flush_pending()
    group2 = [(t, b) for t, b, a in e.notifier.sent if a]
    check("这一轮就进群一次", [t for t, _ in group2], [texts.unresolved("明日方舟", "早班")])
    body2 = group2[-1][1] if group2 else ""
    check("还是说 MAA 不接受这份配置、哪一关", ("没补跑：MAA 不接受这份配置" in body2, "YW-4" in body2), (True, True))
    check("还是说一仗都没打、理智没读到", ("一仗都没打" in body2, SANITY_UNREAD in body2), (True, True))
    check("两次都算上", "重试 2 次" in body2)
    if "--show" in sys.argv and group:
        print("\n----- alarm -----\n" + group[-1][0] + "\n" + body + "\n-----------------")

    _mc.CHECKS.update(_mc_real)


def _part_maa_start_watchdog():
    """A hung Arknights start -> end MAA.exe so AUTO-MAS restarts it now, not 45 minutes later (#137).

2026-11-05 早班: MAA began starting the game at 09:03:23 (asst.log TaskChainStart StartUp), saw
the integrity-check screen at 09:03:45 (GameStartCheckResourceOCR 「资源完整性」), then pressed
「开始唤醒」 every 4.4 s (GameStart, 609 times) until AUTO-MAS's own limit at 09:48:24. Normal
starts take 58-66 s; the retry took 101 s.

Replayed here with that day's line shapes. The clock, the AUTO-MAS snapshot, the process list,
the kill and the log file are stand-ins; nothing touches a real process. Checked:
* the 11-05 hang is ended 5 minutes after the last resource-check screen, not before, once;
* a normal start, a download (GameStartUpdateOCR repeating) and a resource check are not hangs;
* never blind: no snapshot, MAA not 「运行」, no process list, or the MAA that began the start gone;
* a new MAA (banner, new PID) or a closed chain (Completed / Error / Stopped) clears the start;
* other chains' presses do not count; reading resumes across partial lines, a rotated log and a
  relay that starts mid-hang (the backlog read, its first partial line skipped);
* the alarm: group route, the kill-failed title, and plain language for both texts;
* a kill that worked leaves 「超时|MAA|<time>」, so runwatch.retry_clock restarts the shift's clocks.

    Formerly test_maa_start_watchdog.py.
    """
    from datetime import datetime, timedelta


    TMP = tmpdir()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.notify import route_of
    from ark_relay.features.run import maa_start_watchdog as W


    T0 = datetime(2026, 11, 5, 9, 3, 23)
    PID = 16328


    def line(at, rest, pid=PID):
        return f"[{at:%Y-%m-%d %H:%M:%S}.760][INF][Px{pid}][Tx43461] {rest}\n"


    def chain(kind, name="StartUp"):
        return f'Assistant::append_callback | {kind} {{"taskchain":"{name}","taskid":1,"uuid":"d912769d7cb0ae0a"}}'


    def sub(task, n=1, name="StartUp", kind="SubTaskStart"):
        return ('Assistant::append_callback | ' + kind + ' {"class":"asst::ProcessTask","details":{"action":"ClickSelf",'
                f'"algorithm":"MatchTemplate","exec_times":{n},"max_times":2147483647,'
                '"result":{"rect":[611,652,58,58],"score":0.808239,"template":"GameStart.png"},'
                f'"task":"{task}"}},"first":["StartAtHome","StartWithSanity","SwitchTheme@ToggleSettingsMenu",'
                '"StartUpBegin"],"pre_task":"StartUpBegin","subtask":"ProcessTask",'
                f'"taskchain":"{name}","taskid":0,"uuid":"d912769d7cb0ae0a"}}')


    CUR_TASK = '{"class":"asst::ProcessTask","cur_task":"StartUp@GameStart","details":{"cur_retry":0,"retry_times":50}}'
    BANNER = ["-----------------------------", "MaaCore Process Start", "Version v6.21.4"]


    class World:
        """The machine as the watchdog sees it."""

        def __init__(self, name):
            self.dir = TMP / name
            (self.dir / "debug").mkdir(parents=True)
            self.log = self.dir / "debug" / "asst.log"
            self.log.write_bytes(b"")
            self.clock = T0
            self.snap = {"tasks": [{"task_info": [{"name": "MAA", "status": "运行"},
                                                  {"name": "MaaEnd", "status": "等待"}]}]}
            self.procs = [("System", 4), ("MAA.exe", PID), ("dnplayer.exe", 9000)]
            self.kills, self.sent = [], []
            self.kill_result = (True, "")
            self.dog = W.Watchdog(self, self.dir, now=lambda: self.clock, snapshot=lambda: self.snap,
                                  processes=lambda: self.procs, kill=self._kill, active=True)

        def _kill(self, pid, image):
            self.kills.append((pid, image))
            return self.kill_result

        def send(self, title, body, alert=False):
            self.sent.append((title, body, alert))
            return []

        def write(self, text):
            with self.log.open("ab") as fh:
                fh.write(text.encode("utf-8"))

        def at(self, t):
            self.clock = t
            return self.dog.tick()


    def hang_until(w, end, start=T0, pid=PID, every=4.4):
        """The 11-05 shape up to `end`: start, the resource check at +22 s, presses every 4.4 s."""
        w.write(line(start, chain("TaskChainStart"), pid))
        w.write(line(start + timedelta(seconds=3), sub("StartUpBegin"), pid))
        w.write(line(start + timedelta(seconds=22), sub("GameStartCheckResourceOCR"), pid))
        t, n = start + timedelta(seconds=29), 0
        while t <= end:
            n += 1
            w.write(line(t, sub("GameStart", n), pid))
            w.write(line(t + timedelta(seconds=3), sub("GameStart", n, kind="SubTaskCompleted"), pid))
            w.write(line(t + timedelta(seconds=4), CUR_TASK, pid))
            t += timedelta(seconds=every)
        return n


    print("[the 11-05 hang]")
    w = World("hang")
    check_at = T0 + timedelta(seconds=22)                    # the last resource-check screen, 09:03:45
    presses = hang_until(w, check_at + timedelta(seconds=299))
    check("4:59 after the last resource check: nothing", w.at(check_at + timedelta(seconds=299)), None)
    check("nothing ended yet", w.kills, [])
    w.write(line(check_at + timedelta(seconds=299.5), sub("GameStart", presses + 1)))
    presses += 1
    title = w.at(check_at + timedelta(seconds=300))
    check("5:00 after it: MAA is ended", title, texts.MAA_START_STUCK_KILLED)
    check("only MAA.exe, by the PID that wrote the start", w.kills, [(PID, "MAA.exe")])
    check("one group alarm", [(t, a) for t, _, a in w.sent], [(texts.MAA_START_STUCK_KILLED, True)])
    body = w.sent[0][1]
    check("the body says when the start began", "MAA 09:03 开始开明日方舟，5 分钟了还没进到游戏里" in body, True)
    check("the body counts the presses", f"「开始唤醒」点了 {presses} 次画面都没变" in body, True)
    check("the body says how long nothing moved", "最近 5 分钟没在下载更新，也没在校验资源" in body, True)
    check("a later look: no second kill, no second alarm", (w.at(check_at + timedelta(seconds=400)), len(w.kills), len(w.sent)),
          (None, 1, 1))

    print("[a normal start, a download, a resource check]")
    w = World("normal")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=29), sub("GameStart"))
            + line(T0 + timedelta(seconds=66), chain("TaskChainCompleted"))
            + line(T0 + timedelta(seconds=67), chain("TaskChainStart", "Fight")))
    check("finished in 66 s: nothing open", (w.at(T0 + timedelta(minutes=30)), w.dog.start), (None, None))
    w = World("download")
    w.write(line(T0, chain("TaskChainStart")))
    t = T0 + timedelta(seconds=30)
    while t < T0 + timedelta(minutes=20):
        w.write(line(t, sub("GameStartUpdateOCR")))
        t += timedelta(seconds=6)
    check("20 minutes of a download: not a hang", w.at(T0 + timedelta(minutes=20)), None)
    check("the download moved the clock", w.dog.start.progress > T0 + timedelta(minutes=19), True)
    w.write(line(T0 + timedelta(minutes=20, seconds=10), sub("GameStart")))
    check("4 minutes after the download ended: still nothing", w.at(T0 + timedelta(minutes=24)), None)
    check("5 minutes after: ended", w.at(T0 + timedelta(minutes=25)), texts.MAA_START_STUCK_KILLED)
    check("its text: 25 minutes in, quiet for the last 5", "25 分钟了还没进到游戏里" in w.sent[0][1]
          and "最近 5 分钟没在下载更新" in w.sent[0][1], True)

    print("[never blind]")
    for label, change in (("no snapshot", lambda w: setattr(w, "snap", None)),
                          ("MAA 完成 in the snapshot", lambda w: setattr(w, "snap", {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"}]}]})),
                          ("no process list", lambda w: setattr(w, "procs", None)),
                          ("a different MAA.exe PID", lambda w: setattr(w, "procs", [("MAA.exe", 19236)])),
                          ("PID there but not MAA.exe", lambda w: setattr(w, "procs", [("svchost.exe", PID)]))):
        w = World("blind-" + str(abs(hash(label))))
        hang_until(w, T0 + timedelta(minutes=10))
        change(w)
        check(label + ": nothing ended", (w.at(T0 + timedelta(minutes=10)), w.kills, w.sent), (None, [], []))
    w = World("gone")
    hang_until(w, T0 + timedelta(minutes=10))
    w.procs = [("System", 4)]
    w.at(T0 + timedelta(minutes=10))
    check("the MAA that began it is gone: the start is forgotten", w.dog.start, None)

    print("[a new MAA, a closed chain, other chains]")
    w = World("retry")
    hang_until(w, T0 + timedelta(minutes=10))
    w.write("".join(line(T0 + timedelta(minutes=10, seconds=5), b, 19236) for b in BANNER))
    check("a new MAA's banner clears the open start", (w.at(T0 + timedelta(minutes=11)), w.dog.start), (None, None))
    w.procs = [("MAA.exe", 19236)]
    hang_until(w, T0 + timedelta(minutes=17), start=T0 + timedelta(minutes=11), pid=19236)
    check("the retry's own clock: 5:00 after its own check screen",
          (w.at(T0 + timedelta(minutes=11, seconds=22 + 299)), w.at(T0 + timedelta(minutes=11, seconds=22 + 300))),
          (None, texts.MAA_START_STUCK_KILLED))
    check("the retry's PID is the one ended", w.kills, [(19236, "MAA.exe")])
    w = World("same-pid")
    hang_until(w, T0 + timedelta(minutes=10))
    w.write("".join(line(T0 + timedelta(minutes=10, seconds=5), b) for b in BANNER))
    check("a banner from the same PID (reused) still clears it", (w.at(T0 + timedelta(minutes=11)), w.dog.start), (None, None))
    for kind in ("TaskChainError", "TaskChainStopped"):
        w = World("closed-" + kind)
        hang_until(w, T0 + timedelta(minutes=10))
        w.write(line(T0 + timedelta(minutes=10, seconds=1), chain(kind)))
        check(kind + " closes the start", (w.at(T0 + timedelta(minutes=11)), w.dog.start), (None, None))
    w = World("other-chain")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=40), sub("GameStart", name="Fight"))
            + line(T0 + timedelta(seconds=41), chain("TaskChainCompleted", "Fight")))
    w.at(T0 + timedelta(minutes=1))
    check("a Fight press and a Fight end do not touch the start", (w.dog.start.presses, w.dog.start.at), (0, T0))

    print("[reading asst.log]")
    w = World("partial")
    whole = line(T0, chain("TaskChainStart"))
    w.write(whole[:40])
    w.at(T0 + timedelta(seconds=1))
    check("half a line: not read yet", w.dog.start, None)
    w.write(whole[40:])
    w.at(T0 + timedelta(seconds=2))
    check("the rest of it: read once", w.dog.start.at if w.dog.start else None, T0)
    w = World("rotated")
    hang_until(w, T0 + timedelta(minutes=2))
    w.at(T0 + timedelta(minutes=2))
    w.log.write_bytes(("".join(line(T0 + timedelta(minutes=3, seconds=1), b, 19236) for b in BANNER)
                       + line(T0 + timedelta(minutes=4), chain("TaskChainStart"), 19236)).encode())
    w.at(T0 + timedelta(minutes=4, seconds=10))
    check("a rotated log is read from its start", (w.dog.start.pid, w.dog.start.at), (19236, T0 + timedelta(minutes=4)))
    w = World("midway")
    filler = line(T0 - timedelta(hours=1), "x" * 300)
    w.write(filler * (W.BACKLOG_BYTES // len(filler) + 50))
    hang_until(w, T0 + timedelta(minutes=6))
    check("relay started mid-hang: the backlog finds the start and ends it", w.at(T0 + timedelta(minutes=6)),
          texts.MAA_START_STUCK_KILLED)
    w = World("old-open")
    w.write(line(T0 - timedelta(hours=12), chain("TaskChainStart"), 777))
    w.procs = [("MAA.exe", PID)]
    check("an old start left open by a MAA that is gone: nothing", (w.at(T0), w.kills), (None, []))
    w = World("off")
    w.dog.active = False
    hang_until(w, T0 + timedelta(minutes=10))
    check("not on Windows: never looks", (w.at(T0 + timedelta(minutes=10)), w.kills), (None, []))

    print("[the alarm]")
    w = World("kill-fails")
    w.kill_result = (False, "退出码 128")
    hang_until(w, T0 + timedelta(minutes=6))
    check("kill failed: its own title", w.at(T0 + timedelta(minutes=6)), texts.MAA_START_STUCK_KILL_FAILED)
    check("kill failed: says so", "结束 MAA 没成功（退出码 128）" in w.sent[0][1], True)
    check("kill failed: still one alarm", (w.at(T0 + timedelta(minutes=7)), len(w.sent)), (None, 1))
    for t in (texts.MAA_START_STUCK_KILLED, texts.MAA_START_STUCK_KILL_FAILED):
        check(f"{t}: the group route", route_of(t, alert=True), "group")
    for b in (texts.maa_start_stuck_body("09:03", 5, 69, True, "", 5),
              texts.maa_start_stuck_body("09:03", 25, 0, True, "", 5),
              texts.maa_start_stuck_body("09:03", 5, 69, False, "结束命令 30 秒没返回", 5)):
        check("plain language: " + b[:24], texts.plain(b), [])

    print("[the restart mark: the shift's clocks restart from the kill, as after AUTO-MAS's own timeout]")
    import types
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore
    from ark_relay.features.run import runwatch
    w = World("mark")
    w.dog.state_dir = w.dir / "state"
    w.dog.state_dir.mkdir()
    hang_until(w, T0 + timedelta(minutes=6))
    kill_at = T0 + timedelta(minutes=6)
    w.at(kill_at)
    store = StateStore(w.dog.state_dir)
    check("the kill leaves the timeout mark of its own moment", store.get("marks", "alerted:2026-11-05"),
          ["超时|MAA|09:09:23"])
    eng = types.SimpleNamespace(state=types.SimpleNamespace(store=store))
    due = datetime(2026, 11, 5, 9, 0, tzinfo=SERVER_TZ)
    check("runwatch.retry_clock restarts the shift from it", runwatch.retry_clock(eng, due, 87),
          datetime(2026, 11, 5, 9, 9, 23, tzinfo=SERVER_TZ))
    w = World("mark-failed-kill")
    w.dog.state_dir = w.dir / "state"
    w.dog.state_dir.mkdir()
    w.kill_result = (False, "退出码 128")
    hang_until(w, T0 + timedelta(minutes=6))
    w.at(T0 + timedelta(minutes=6))
    check("a kill that failed leaves no mark (nothing restarted)",
          StateStore(w.dog.state_dir).get("marks", "alerted:2026-11-05"), None)

    print("\n[audit 11-08 B-05: StartUp's end lost to a rotation does not get a fighting MAA killed]")
    w = World("rotated-mid-start")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=30), sub("StartUpBegin")))
    w.at(T0 + timedelta(seconds=31))
    # MAA writes StartUp's completion into asst.log, then rotates it before the next read.
    w.write(line(T0 + timedelta(seconds=60), chain("TaskChainCompleted")))
    w.log.rename(w.log.with_name("asst.bak.log"))
    w.log.write_bytes(line(T0 + timedelta(seconds=70), sub("FightBegin", name="Fight")).encode())
    w.at(T0 + timedelta(seconds=75))
    check("the completion line is read from asst.bak.log", w.dog.start, None)
    w = World("rotated-lost")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=30), sub("StartUpBegin")))
    w.at(T0 + timedelta(seconds=31))
    w.log.write_bytes(line(T0 + timedelta(seconds=70), chain("TaskChainStart", "Fight")).encode())   # no bak at all
    w.at(T0 + timedelta(seconds=75))
    check("no completion anywhere, but a Fight chain of the same MAA began: start closed", w.dog.start, None)
    check("so nothing is killed 10 minutes into the fight", (w.at(T0 + timedelta(minutes=10)), w.kills), (None, []))
    w = World("other-pid-chain")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=5), chain("TaskChainStart", "Fight"), pid=999))
    w.at(T0 + timedelta(seconds=6))
    check("another MAA's chain does not close this start", w.dog.start and w.dog.start.pid, PID)

    print("all checks passed" if not fails else f"FAILED: {fails}")


def _part_maa_unreachable_cleared_notes():
    """test_maa_unreachable.py still passes on a relay tree whose RELEASE-NOTES.md is empty.

scripts/mac/deploy-relay.sh empties relay/RELEASE-NOTES.md and commits that to main on
every deploy, so an empty notes file is the normal state between deploys. The test read
the notes with a bare `next(...)` looking for the re-run line; on the emptied file that
raised StopIteration, the test exited 1 and the sections after it never ran. The test is
mapped to some 40 relay modules, so the deploy gate would have gone red on the first relay
change after the next deploy.

Here a copy of ark_relay sits next to an empty RELEASE-NOTES.md, and test_maa_unreachable.py
runs against it with --relay. Before the fix: exit 1, StopIteration. After: exit 0, and the
last section (the make-up in flight) still runs.

  python3 tests/test_maa_unreachable_cleared_notes.py

    Formerly test_maa_unreachable_cleared_notes.py.
    """

    import shutil
    import subprocess

    HERE = Path(__file__).resolve().parent
    RELAY = HERE.parent
    sys.path.insert(0, str(HERE))


    print("[部署后更新说明被清空：明日方舟进不了游戏那套测试照样跑完]")
    shadow = tmpdir()
    # A copy, not a symlink: the relay tests also run on Windows CI.
    shutil.copytree(RELAY / "ark_relay", shadow / "ark_relay",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (shadow / "RELEASE-NOTES.md").write_text("", encoding="utf-8")
    p = subprocess.run([sys.executable, str(HERE / "test_maa_unreachable.py"), "--relay", str(shadow)],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    check("退出码 0", p.returncode, 0)
    check("没有 StopIteration", "StopIteration" in p.stderr, False)
    check("最后一节也跑到了", "补跑落地后：更新照常起" in p.stdout, True)
    if fails:
        print(p.stdout[-2000:])
        print(p.stderr[-2000:])

    print("\nall checks passed" if not fails else f"\n{len(fails)} check(s) failed")


def _part_maa_window_overlap():
    """时间窗的 5 分钟余量会伸进下一趟，把下一趟的「开始」当成本趟的悬挂。

2026-08-31 晚上实测：第一趟 21:30:50→21:33:38（窗口到 21:38:38），
第二趟 21:33:43 就开跑，Infrast 21:35 开始、21:43 完成。
第一趟的窗口捞到了「Infrast 开始」却够不到「完成」，
推了一条「开了没收尾：Infrast」——而基建好好干完了，纯误报。

    Formerly test_maa_window_overlap.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import outcome


    def ev(ts, kind, chain):
        return (f'[2026-08-31 {ts}][INF][Px][Tx] '
                f'TaskChain{kind} {{"taskchain":"{chain}","uuid":"x"}}')

    # 第一趟：StartUp/Fight/CloseDown 各一对。之后是第二趟，只到 Infrast 开始就被切断。
    OVERLAP = "\n".join([
        ev("21:31:10", "Start", "StartUp"), ev("21:32:10", "Completed", "StartUp"),
        ev("21:32:11", "Start", "Fight"),   ev("21:33:30", "Completed", "Fight"),
        ev("21:33:31", "Start", "CloseDown"), ev("21:33:35", "Completed", "CloseDown"),
        # ↓ 这些是第二趟的，被 5 分钟余量捞进来了
        ev("21:33:50", "Start", "StartUp"), ev("21:34:40", "Completed", "StartUp"),
        ev("21:34:41", "Start", "Fight"),   ev("21:35:20", "Completed", "Fight"),
        ev("21:35:21", "Start", "Infrast"),          # 「完成」在 21:43，窗口够不到
    ])

    print("\n[越界的下一趟不许算进本趟]")
    res = outcome.maa_checks(OVERLAP)
    bad = [c for c in res if not c.ok]
    check("没有误报", [c.name for c in bad], [])

    print("\n[真的悬挂还是要报]")
    REAL = "\n".join([
        ev("21:31:10", "Start", "StartUp"), ev("21:32:10", "Completed", "StartUp"),
        ev("21:32:11", "Start", "Infrast"),          # 本趟自己的 Infrast 没收尾
    ])
    bad = [c for c in outcome.maa_checks(REAL) if not c.ok]
    check("报出来了", len(bad) >= 1, True)
    check("说的是 Infrast", any("Infrast" in (c.detail or "") for c in bad), True)

    print("\n[单趟不受影响]")
    ONE = "\n".join([
        ev("21:33:50", "Start", "StartUp"), ev("21:34:40", "Completed", "StartUp"),
        ev("21:35:21", "Start", "Infrast"), ev("21:43:20", "Completed", "Infrast"),
    ])
    check("全过", [c.name for c in outcome.maa_checks(ONE) if not c.ok], [])


def _part_maa_write_master_first():
    """MAA setting writes: the master copy is required, and a failure says what was written.

AUTO-MAS copies data/<script>/<user>/ConfigFile over MAA's config dir before each
run (AUTO-MAS v5.7 task/MAA/AutoProxy.py _copy_source_config). The old writer
skipped a missing master, wrote only MAA's own copy and reported success - the
change was gone at the next run. And when the second file failed, the first was
already written but the reply said the change was refused.

    Formerly test_maa_write_master_first.py.
    """
    #!/usr/bin/env python3

    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import mastercfg

    FAILED: list[str] = []
    DOC = {"Current": "Default", "Configurations": {"Default": {"TaskQueue": [
        {"Type": "StartUp"}, {"Type": "Infrast", "UsesOfDrones": "Money"}]}}}


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    def drones(f: Path) -> str:
        return mastercfg._maa_infrast(json.loads(f.read_text(encoding="utf-8")))["UsesOfDrones"]


    def tree(master_doc=DOC, own_doc=DOC):
        root = tmpdir()
        automas, maa = root / "AUTO-MAS", root / "MAA"
        mf = automas / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json"
        mf.parent.mkdir(parents=True)
        if master_doc is not None:
            mf.write_text(json.dumps(master_doc), encoding="utf-8")
        own = maa / "config" / "gui.new.json"
        own.parent.mkdir(parents=True)
        own.write_text(own_doc if isinstance(own_doc, str) else json.dumps(own_doc), encoding="utf-8")
        return automas, maa, mf, own


    def write(automas, maa):
        """write_maa's reply; an exception escaping it is a failure, kept as text."""
        try:
            return mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "PureGold")
        except Exception as exc:  # noqa: BLE001
            return None, f"raised {type(exc).__name__}: {exc}"


    print("[no master copy, MAA's own copy present]")
    automas, maa, mf, own = tree(master_doc=None)
    ok, msg = write(automas, maa)
    require("refused", ok is False, msg)
    require("MAA's own copy untouched", drones(own) == "Money", drones(own))
    require("says the master is missing", "母本" in msg, msg)

    print("[MAA's own copy has no Infrast task]")
    automas, maa, mf, own = tree(own_doc={"Current": "Default", "Configurations": {"Default": {"TaskQueue": []}}})
    ok, msg = write(automas, maa)
    require("refused", ok is False, msg)
    require("the master was not written either", drones(mf) == "Money", drones(mf))

    print("[MAA's own copy does not parse]")
    automas, maa, mf, own = tree(own_doc="{broken")
    ok, msg = write(automas, maa)
    require("refused without an exception, master untouched", ok is False and drones(mf) == "Money", msg)

    print("[MAA's own copy fails at write time, after the master]")
    automas, maa, mf, own = tree()
    real = mastercfg._write_maa_copies.__globals__["atomic_write_text"]


    def fail_own(path, text):
        if Path(path) == own:
            raise PermissionError("locked")
        real(path, text)


    mastercfg._write_maa_copies.__globals__["atomic_write_text"] = fail_own
    try:
        ok, msg = write(automas, maa)
    finally:
        mastercfg._write_maa_copies.__globals__["atomic_write_text"] = real
    require("master is written", drones(mf) == "PureGold", drones(mf))
    require("the reply says the master is already changed", "母本已经改好" in msg, msg)

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_maa_checks, _part_maa_closedown_postaction, _part_maa_config_rejected, _part_maa_start_watchdog, _part_maa_unreachable_cleared_notes, _part_maa_window_overlap, _part_maa_write_master_first]))
