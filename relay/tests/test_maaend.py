"""MaaEnd's runs: the app log, the folder it resolves, a false green, logged out, recovered, re-enabled, stopped between tasks, the stub record, a silent task.

One part per former file, each run on its own (tests/_parts.py): test_maaend_app_log.py, test_maaend_dir_resolve.py, test_maaend_false_green.py, test_maaend_logged_out.py, test_maaend_recovered.py, test_maaend_reenable.py, test_maaend_stopped_between_tasks.py, test_maaend_stub_record.py, test_maaend_task_silent.py.
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


def _part_maaend_app_log():
    """核对 MaaEnd 时必须连它自己的 app 日志一起看。

2026-08-29 早班：中继推了一条「MaaEnd 这一轮有 2 项没干成」的告警，两条都是误报。

第一条「日志里没有『自动执行任务完成』」——这句收尾标记只写在 MaaEnd 自己的
`<maaend>/debug/YYYY-MM-DD-N.log` 里（`INFO [App] 自动执行任务完成，关闭自身`），
而核对时只喂了 AUTO-MAS 的 history 日志，那里面永远没有这句。翻 10 天 22 份
history 日志，出现 0 次——也就是这条判据恒为假。当天 MaaEnd 其实 09:54:38
打了那句，16 个任务全部收尾。**判据没错，错在没给它该看的文件。**

第二条「有 6 张出错截图」——那 6 张是 ScenePrivateMapZoomOut，重试后恢复，
环境监测和基质刷取都报了「任务完成」。万能跳转失败（SceneAnyEnterWorld）
仍然一律算故障，那是 2026-08-27 真事故的判据，不放宽。

    Formerly test_maaend_app_log.py.
    """
    import tempfile
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.alarm import handle
    from ark_relay.features.verify import outcome

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    HISTORY = "\n".join(
        f"[2026-08-29 09:3{i}:00.000] 任务开始: 任务{i}\n"
        f"[2026-08-29 09:3{i}:30.000] 任务完成: 任务{i}" for i in range(3))
    APP = "2026-08-29 09:54:38 INFO  [App] 自动执行任务完成，关闭自身\n"
    SHOTS = [f"2026.08.29-09.39.5{i}___ScenePrivateMapZoomOut.png" for i in range(3)]
    STUCK = ["2026.08.27-09.44.59_SceneAnyEnterWorld.png"]


    def _bad(checks):
        return [c.label for c in checks if not c.ok]


    def main() -> int:
        print("=== 只看 history 日志（早班那次的错误做法）===")
        got = outcome.maaend_checks(HISTORY, SHOTS)
        check("会误判成没跑完", "MaaEnd 跑完" in _bad(got), True)

        print("\n=== 连 app 日志一起看（修好之后）===")
        got2 = outcome.maaend_checks(HISTORY + "\n" + APP, SHOTS)
        check("不再误判没跑完", "MaaEnd 跑完" in _bad(got2), False)
        check("已恢复的截图不算故障", _bad(got2), [])
        check("但截图仍如实列出",
              any("出错截图" in c.label for c in got2), True)

        print("\n=== 万能跳转失败：跑完了也照样算故障 ===")
        got3 = outcome.maaend_checks(HISTORY + "\n" + APP, STUCK)
        check("SceneAnyEnterWorld 一律算故障", "界面没卡住" in _bad(got3), True)
        check("告警里带截图名",
              "SceneAnyEnterWorld" in (outcome.summarize(got3, "MaaEnd") or ""), True)

        print("\n=== a task started and never ended: AUTO-MAS reports it (hand-over grey item 3) ===")
        got4 = outcome.maaend_checks(
            "[x] 任务开始: 基质刷取\n" + APP, [])
        check("the relay no longer adds its own dangling-task check",
              [c.label for c in got4 if "收了尾" in c.label], [])

        print("\n=== _maaend_app_log 真的能读到那句 ===")
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "debug"
            d.mkdir(parents=True)
            (d / "2026-08-29-7.log").write_text(APP, encoding="utf-8")
            (d / "maafw.log").write_text("框架日志，不该被读进来\n", encoding="utf-8")
            started = datetime.now() - timedelta(hours=1)
            txt = handle._maaend_app_log(Path(td), started)
            check("读到了收尾标记", "自动执行任务完成" in txt, True)
            check("没把框架日志混进来", "框架日志" in txt, False)

        print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_maaend_dir_resolve():
    """MaaEnd 路径必须自己解析出来，解析不出来必须喊。

2026-08-28 查实：机器上的 `.env` 从来没设过 `ARK_MAAEND_DIR`
（`ARK_OKWW_DIR`、`ARK_AUTOMAS_DIR` 都设了，唯独漏了它）。
于是 `cfg.maaend_dir` 一直是 None，`Engine._archive_maaend_evidence`
在第一行 `if not src.is_dir(): return` 静默退出——**从写出来那天起一次都没跑成**。

代价是真的：MaaEnd 启动时会「Auto-cleared log files and debug artifacts」，
当天早上三轮选剑演武失败的 on_error 截图，在中午重试的瞬间就被清空了，
而本该抢救它们的代码从没执行过，还一个字都没打。

`plan.script_dir` 的文档字符串本来就写着「省得把 MaaEnd 路径配第二遍：
AUTO-MAS 已经知道了」——只是 `service.py` 用了，`Engine` 没用。
现在提到 `Config.__post_init__`，一次修好所有调用方。

    Formerly test_maaend_dir_resolve.py.
    """
    import json
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core.config import Config

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    def _automas(tmp: Path, path_value: str) -> Path:
        """造一个最小的 AUTO-MAS 配置目录，只够 plan.script_dir 认出 MaaEnd。"""
        cfg = tmp / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "ScriptConfig.json").write_text(json.dumps({
            "instances": [{"uid": "u1"}],
            "u1": {"Info": {"Name": "终末地", "Path": path_value}},
        }, ensure_ascii=False), encoding="utf-8")
        return tmp


    def main() -> int:
        print("=== maaend_dir 解析 ===")

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            want = tmp / "maaend"
            (want / "debug").mkdir(parents=True)
            _automas(tmp, str(want))

            # 1) 环境变量没设 → 从 AUTO-MAS 记录里解析出来
            c = Config(automas_dir=tmp, maaend_dir=None)
            check("环境变量没设时能从 AUTO-MAS 解析出来",
                  c.maaend_dir is not None and Path(c.maaend_dir) == want, True)

            # 2) 显式给了就不许被覆盖
            explicit = tmp / "elsewhere"
            c2 = Config(automas_dir=tmp, maaend_dir=explicit)
            check("显式配置优先，不被解析覆盖", Path(c2.maaend_dir), explicit)

            # 3) 没有 automas_dir 时不炸、保持 None
            c3 = Config(automas_dir=None, maaend_dir=None)
            check("没有 automas_dir 时保持 None 且不抛异常", c3.maaend_dir, None)

        # 4) AUTO-MAS 里查不到 MaaEnd → None，不许瞎编一个路径
        with tempfile.TemporaryDirectory() as td:
            tmp = _automas(Path(td), "")          # Path 为空 = 查不到
            c4 = Config(automas_dir=tmp, maaend_dir=None)
            check("AUTO-MAS 里查不到就是 None，不许编路径", c4.maaend_dir, None)

        print("\n=== 解析不出来时必须喊，不许静默 return ===")
        import logging
        from ark_relay.core import engine as E
        from ark_relay.features.alarm import handle as H

        class _Rec:
            run_id = "r/1"
            script = "MaaEnd"

        class _Eng:
            cfg = Config(automas_dir=None, maaend_dir=None)
            _archive_maaend_evidence = E.Engine._archive_maaend_evidence

        seen = []

        class _Cap(logging.Handler):
            def emit(self, r):
                seen.append((r.levelno, r.getMessage()))

        h = _Cap()
        H.log.addHandler(h)
        try:
            _Eng()._archive_maaend_evidence(_Rec())
        finally:
            H.log.removeHandler(h)

        check("maaend_dir 缺失时打了 ERROR",
              any(lv >= logging.ERROR for lv, _ in seen), True)
        check("ERROR 里点名 maaend_dir",
              any("maaend_dir" in m for _, m in seen), True)

        print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_maaend_false_green():
    """A MaaEnd run that ends cleanly but does no work must not be reported green.

Real logs, 2026-09-10. MaaEnd had updated to v2.28.0-beta.5 at boot; the master
config still carried the old 自动采集 route keys, MaaEnd discarded them on load
(36 「已丢弃保存值」 lines), the scheduler walked zero routes, wrote 「任务完成」
after 38 seconds, AUTO-MAS recorded Success, and the report opened with 全绿.
The user's words, on why a false green is worse than a false red: 「明明没有完成任务，却按照完成任务的通知去报，这个其实比假红更严重」.

    Formerly test_maaend_false_green.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features.verify.outcome import maaend_checks, summarize

    FIX = Path(__file__).parent / "fixtures" / "maaend-2026-09-10"


    def bad(checks):
        return {c.label: c.detail for c in checks if not c.ok}


    app = (FIX / "app-2026-09-10-4.log").read_text(encoding="utf-8")
    collect = (FIX / "MaaEnd-06-08-39.log").read_text(encoding="utf-8")
    daily = (FIX / "MaaEnd-05-38-38.log").read_text(encoding="utf-8")

    print("[10:08 那趟：自动采集 38 秒报完成，一条路线没走]")
    got = maaend_checks(collect + "\n" + app, [])
    b = bad(got)
    check("自动采集 被判为没干成", "自动采集 真的走了路线" in b)
    check("说清是几秒就报完成", "38 秒" in b.get("自动采集 真的走了路线", ""))
    check("新版本丢掉旧设置 被判为故障", "自动采集的设置" in b and "其他的设置" in b)
    check("说清丢了多少项（2 + 34 = 36）", "2 个路线选项" in b.get("自动采集的设置", "")
          and "34 个选项" in b.get("其他的设置", ""))
    check("点名 AutoCollectRoutes", "AutoCollectRoutes" in b.get("自动采集的设置", ""))
    check("「跑完」那一项仍然通过", "MaaEnd 跑完" not in b)
    msg = summarize(got, "MaaEnd")
    check("会给出人话告警", msg is not None and "没干成" in msg)
    check("没干成只数真没干的那一项", msg.splitlines()[0], "MaaEnd 这一轮有 1 项没干成，但它自己没报错：")
    check("设置被重置另起一段，不算没干成", "另外这一轮没按你的设置跑（新版本把设置重置成了默认值）：" in msg)
    check("同时有没干成时不算「只是设置」", texts.outcome_settings_only(msg), False)

    print("\n[09:39 那趟：日常全做了、基质刷了三次——不能误伤]")
    got2 = maaend_checks(daily + "\n2026-09-10 10:08:00 INFO [App] 自动执行任务完成，关闭自身\n", [])
    b2 = bad(got2)
    check("基质刷取 算干成", "基质刷取 真的刷了" not in b2)
    check("没有自动采集就不检查它", not any(k.startswith("自动采集") for k in b2))
    check("没有丢设置的行就不报", not any(k.endswith("的设置") for k in b2))
    check("整趟不报警", summarize(got2, "MaaEnd"), None)

    print("\n[协议空间：开了没进去也要报]")
    fake = ("[2026-09-10 09:00:00.000] 任务开始: ⚔️协议空间\n"
            "[2026-09-10 09:00:20.000] 任务完成: ⚔️协议空间\n"
            "2026-09-10 09:00:21 INFO [App] 自动执行任务完成，关闭自身\n")
    check("协议空间没进去被判为没干成", "协议空间 真的进了" in bad(maaend_checks(fake, [])))
    fake_ok = fake.replace("任务完成: ⚔️协议空间", "进入协议空间成功\n[2026-09-10 09:05:00.000] 任务完成: ⚔️协议空间")
    check("进了就通过", "协议空间 真的进了" not in bad(maaend_checks(fake_ok, [])))


    print("[排班说今天不采，秒完成是对的，不能当假绿]")
    skipped = ("[2026-09-11 10:01:51.385] 任务开始: 🧺自动采集\n"
               "[2026-09-11 10:01:51.482] 现在游戏时间是周五，根据执行周期跳过任务\n"
               "[2026-09-11 10:01:51.566] 任务完成: 🧺自动采集\n")
    check("按周期跳过不报「没走路线」", "自动采集 真的走了路线" not in bad(maaend_checks(skipped, [])))
    # 2026-10-12: a skipped 自动采集 was listed under 「干成的」 as 「自动采集 真的走了路线」.
    msg_skip = summarize(maaend_checks(skipped + fake, []), "MaaEnd") or ""
    check("跳过的单独一行「按周期今天不跑」", "按周期今天不跑：自动采集" in msg_skip.splitlines())
    check("跳过的不列进「干成的」", not any(ln.startswith("干成的") and "自动采集" in ln for ln in msg_skip.splitlines()))

    print("\n[2026-10-10 早班：新版把 6 项囤货清单改成开关，旧值被重置为默认——也算丢了旧设置]")
    # Real MaaEnd app log of that morning. From 10-03 to 10-10 every launch said
    # 「选项 "AutoStockBuy…" 的类型已从 "checkbox" 变更为 "switch"，已重置为默认值」 and
    # bought by the defaults instead of the per-item lists in the master; this
    # check stayed green because it only knew the 「已丢弃保存值」 wording.
    app1010 = (Path(__file__).parent / "fixtures" / "maaend-2026-10-10" / "app-2026-10-10-3.log").read_text(encoding="utf-8")
    b3 = bad(maaend_checks(app1010, [], own_log=True))
    check("类型变了被重置 被判为故障", "自动囤货的设置" in b3)
    check("说清是 6 个购买选项、没按设置买", "6 个购买选项被 MaaEnd 新版本重置成默认值，今天没按你的设置买"
          in b3.get("自动囤货的设置", ""))
    check("点名囤货那几项", "AutoStockBuyCulturalGoodsValleyIV" in b3.get("自动囤货的设置", ""))
    # 2026-10-12: this alone was said as 「MaaEnd 这一轮有 1 项没干成」 - the work was done, by defaults.
    # With AUTO-MAS's own record of that run (tests/replay/2026-10-10), every task finished.
    hist1010 = (Path(__file__).parent / "replay" / "2026-10-10" / "endfield" / "MaaEnd-05-13-19.log").read_text(encoding="utf-8")
    msg3 = summarize(maaend_checks(hist1010 + "\n" + app1010, [], own_log=True), "MaaEnd") or ""
    check("只有设置被重置：不说「没干成」", "没干成" not in msg3)
    check("只有设置被重置：开头说没按你的设置跑", msg3.splitlines()[0],
          "MaaEnd 这一轮没按你的设置跑（新版本把设置重置成了默认值）：")
    check("推送认得这是「只是设置」", texts.outcome_settings_only(msg3), True)
    three = "\n".join([app1010] * 3)
    check("同一项出现几次只算一次", "6 个" in bad(maaend_checks(three, [], own_log=True)).get("自动囤货的设置", ""))
    check("别的 WARN（隐藏主窗口失败）不算丢设置",
          not any(k.endswith("的设置") for k in bad(maaend_checks(
              "2026-10-10 09:14:22 WARN  [App] 自启动时隐藏主窗口失败: Command plugin:window|hide not allowed by ACL\n", []))))


def _part_maaend_logged_out():
    """A MaaEnd task that failed because the account was logged in elsewhere names that as its cause.

2026-11-05 11:43:57 (Beijing) the account was logged in on another device (his brother). The game put
「登录认证已失效，请重新登录」 over everything; MaaFW's batch OCR logged it in maafw.log
(fixtures/maaend-2026-11-05/maafw-logged-out-ocr.log, one real line), every route after it failed, and
AUTO-MAS booked 「任务失败: 🧺自动采集」 at 11:54:57 (fixtures/.../history-MaaEnd-07-24-54-gathering.log,
real lines). The alarm said gathering failed and nothing more. Checked, on those real lines:
* the failed task gets the logged-out cause and the record the dialog's time;
* the alarm's 卡在 part carries it (ledger_rows._with_causes);
* no dialog in the framework log, or no framework log: no cause;
* a task that failed before the dialog: no cause.

    Formerly test_maaend_logged_out.py.
    """


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.ledger_rows import _with_causes
    from ark_relay.features.verify import collector_maaend as C

    FIX = Path(__file__).resolve().parent / "fixtures" / "maaend-2026-11-05"
    HISTORY = (FIX / "history-MaaEnd-07-24-54-gathering.log").read_text(encoding="utf-8")
    FW_LINE = (FIX / "maafw-logged-out-ocr.log").read_text(encoding="utf-8")
    TMP = tmpdir()


    def maaend_dir(name, fw_text):
        d = TMP / name
        (d / "debug").mkdir(parents=True, exist_ok=True)
        if fw_text is not None:
            (d / "debug" / "maafw.log").write_text(fw_text, encoding="utf-8")
        return d


    def parse(name, history, fw_text):
        log = TMP / f"{name}.log"
        log.write_text(history, encoding="utf-8")
        return C.parse_maaend_log(log, maaend_dir(name, fw_text))


    print("[11-05 原样：11:43:57 弹「登录认证已失效」，11:54:57 自动采集失败]")
    out = parse("real", HISTORY, FW_LINE)
    check("记下弹框的时刻", out.get("maaend_logged_out_at"), "11:43:57")
    check("自动采集的原因是被挤下线", (out.get("maaend_fail_causes") or {}).get("自动采集"), C.LOGGED_OUT)
    check("报警「卡在」那一段带上原因", _with_causes(out.get("tasks_failed") or [], out.get("maaend_fail_causes")),
          ["自动采集（" + C.LOGGED_OUT + "）"])

    print("\n[框架日志里没有那句话、或者没有框架日志：不写原因]")
    out = parse("no-dialog", HISTORY, FW_LINE.replace(C.LOGGED_OUT_TEXT, "资源完整性"))
    check("没有那句话：不记时刻", "maaend_logged_out_at" in out, False)
    check("没有那句话：不写原因", (out.get("maaend_fail_causes") or {}).get("自动采集"), None)
    out = parse("no-fw", HISTORY, None)
    check("没有框架日志：不写原因", (out.get("maaend_fail_causes") or {}).get("自动采集"), None)

    print("\n[弹框之前就失败的任务：不算被挤下线]")
    early = "\n".join(line for line in HISTORY.splitlines() if line < "[2026-11-05 11:43:5")
    early += "\n[2026-11-05 11:43:00.000] 任务失败: 🧺自动采集\n"
    out = parse("early", early, FW_LINE)
    check("弹框前失败：不写原因", (out.get("maaend_fail_causes") or {}).get("自动采集"), None)


def _part_maaend_recovered():
    """MaaEnd hung and the relay ends it: which of the two log lines is "recovered".

The morning shift of 2026-10-06 pushed three messages for one event - the watchdog
ERROR, the ⚠️ notice, the bookkeeping ERROR (all in relay-1006.log). The ⚠️ stays a
group alarm (it is written for the human). The other two are the same event written
as ERRORs in the log; the user's rule of 2026-10-06 05:07 made them daily-report-only
when the relay's own kill let AUTO-MAS wrap the round up. Since 2026-10-10 both are
pushed again: why MaaEnd does not exit is not known and it keeps happening (10-09
09:33, 10-10 09:38), so it is not a fault that fixed itself. What follows was:

* the watchdog's 「MaaEnd 卡死」 WARNING after a crash / stall / plugin-gone kill:
  the ⚠️ is that event's one push (errwatch.group_pushed);
* handle._mark_no_self_exit's 「🟠 任务全部完成」 bookkeeping line: pushed, unless
  AUTO-MAS (v5.7.0-beta.2) logged that it ended the finished MaaEnd right after
  recording the result - then recovered (daily report) with a 「自愈待查」 red item.
  The watchdog no longer judges a MaaEnd that finished but did not exit (upstream
  MistEO/MXU#371): AUTO-MAS ends it itself.

MXU lines and the stderr crash line are verbatim machine lines (the same ones
test_maaend_watchdog.py replays, from D:\\ark\\maaend\\debug);
the 10-06 evidence pack is not in COS (a successful run has no bundle), so the 09:51:51
lines themselves could not be fetched.

    Formerly test_maaend_recovered.py.
    """
    import logging
    import os
    from datetime import datetime


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.alarm import errwatch, handle
    from ark_relay.features.run import maaend_watchdog
    from ark_relay.core import techlog, texts
    from ark_relay.core.config import SERVER_TZ, RunRecord


    class Notes:
        """The watchdog's notifier: the ⚠️ notice lands here."""

        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []


    class Refuses:
        """errwatch's notifier: the group refuses, so what it queues stays queued."""

        def send_group(self, title, body):
            return ["企业微信机器人：拒收"]

        def send(self, title, body, **kw):
            return ["拒收"]


    class Lines(logging.Handler):
        """Captures every ark.* record, so the test can read `ark_recovered`."""

        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def said(self, *parts):
            return [r for r in self.records if all(p in r.getMessage() for p in parts)]


    ARK_LOGGER = logging.getLogger(errwatch.ARK)
    LINES = Lines()
    ARK_LOGGER.addHandler(LINES)
    ARK_LOGGER.setLevel(logging.DEBUG)


    def watch():
        sd = tmpdir() / "state"                          # its own tech/ next to it (techlog.tech_dir)
        h = errwatch.ErrorKindAlert(Refuses(), state_dir=sd, known={}, retry=(3600.0,), fallback_after=1e9)
        ARK_LOGGER.addHandler(h)
        LINES.records.clear()
        return h, sd


    def unwatch(h):
        ARK_LOGGER.removeHandler(h)
        h.close()


    RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
    PID = 11224
    PROCS = [("MaaEnd.exe", PID), ("Endfield.exe", 18800)]   # no plugins: the kill loop stays quiet
    CRASH_LINE = "Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456"
    HUNG_MXU = ["2026-10-01 16:58:19 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: task-progress",
                "2026-10-01 16:58:22 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: tasks-completed"]


    class Dog:
        """One watchdog with everything outside replaced."""

        def __init__(self, mxu_lines):
            self.debug = tmpdir() / "debug"
            self.debug.mkdir()
            self.stderr = self.debug / "go-service.stderr.log"
            self.stderr.write_text("", encoding="utf-8")
            (self.debug / "2026-10-01-6.log").write_text("\n".join(mxu_lines) + "\n", encoding="utf-8")
            self.t, self.wall = 1000.0, datetime(2026, 10, 1, 16, 58, 22)
            self.notes, self.killed = Notes(), []
            self.procs = list(PROCS)
            self.dog = maaend_watchdog.Watchdog(
                self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: RUNNING,
                processes=lambda: list(self.procs), kill=self._kill,
                plugin_paths=lambda: {}, active=True)
            self.dog.tick(1, "")                          # first sight of this MaaEnd

        def _kill(self, pid, image):
            self.killed.append((pid, image))
            return True, ""

        def at(self, hh, mm, ss):
            new = datetime(2026, 10, 1, hh, mm, ss)
            self.t += (new - self.wall).total_seconds()
            self.wall = new
            return self.dog.tick(1, "")


    def recovered_of(records, *parts):
        rows = [r for r in records if all(p in r.getMessage() for p in parts)]
        assert rows, f"no log record matching {parts}"
        return [getattr(r, errwatch.RECOVERED, False) for r in rows]


    print("[finished, did not exit -> left to AUTO-MAS (v5.7.0-beta.2): no kill, no send, no WARNING]")
    h, sd = watch()
    try:
        d = Dog(HUNG_MXU)
        for hh, mm, ss in ((16, 58, 53), (16, 59, 24), (17, 0, 0)):     # well past the old 30 s
            check(f"{hh}:{mm:02d}:{ss:02d}: nothing done", d.at(hh, mm, ss), None)
        check("never killed", d.killed, [])
        check("nothing sent", d.notes.sent, [])
        check("no 「卡死」 line", LINES.said("MaaEnd 卡死"), [])
        check("nothing queued for the group", h.pending(), [])
    finally:
        unwatch(h)

    print("\n[crash -> the ⚠️ is the one push; the 「卡死」 WARNING repeats it and is not queued (2026-10-11)]")
    h, sd = watch()
    try:
        d = Dog([])
        d.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
        d.at(16, 59, 0)                                   # crash read -> kill
        check("the 「卡死」 WARNING is not marked recovered", recovered_of(LINES.records, "MaaEnd 卡死"), [False])
        check("it is not queued for the group (errwatch.group_pushed: the ⚠️ went out)",
              [str(x.get("line"))[:9] for x in h.pending()], [])
        check("the ⚠️ notice still rings", [(t, a) for t, _, a in d.notes.sent],
              [(texts.MAAEND_STUCK_KILLED, True)])
    finally:
        unwatch(h)

    print("\n[bookkeeping: the 「🟠 任务全部完成」 line with no AUTO-MAS kill line is pushed]")


    class _Cfg:
        def __init__(self, history_dir=None):
            self.history_dir = history_dir                # None: no app.log read, idle stays 0


    class _State:
        def __init__(self):
            self.marks = []

        def mark_raw(self, *a):
            self.marks.append(a)


    class _Eng:
        def __init__(self, history_dir=None):
            self.cfg = _Cfg(history_dir)
            self.state = _State()


    def automas_app_log(lines):
        """<automas>/history next to <automas>/debug/app.log, as collector reads it."""
        root = tmpdir() / "automas"
        (root / "history").mkdir(parents=True)
        (root / "debug").mkdir()
        (root / "debug" / "app.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return root / "history"


    SHIPPED = []
    _real_ship = handle._ship_evidence


    def _fake_ship(eng, rec):
        # The real one uploads to COS; here only who asked for a bundle is recorded.
        SHIPPED.append(rec.run_id)
        rec.raw["evidence_page"] = "https://example.invalid/bundle"
        return rec.raw["evidence_page"]


    handle._ship_evidence = _fake_ship
    h, sd = watch()
    try:
        rec = RunRecord(run_id="2026-10-06/endfield/MaaEnd-05-28-01", script="MaaEnd", user="endfield",
                        started=datetime(2026, 10, 6, 9, 51, 51, tzinfo=SERVER_TZ),
                        finished=datetime(2026, 10, 6, 9, 52, 54, tzinfo=SERVER_TZ), ok=True)
        handle._mark_no_self_exit(_Eng(), rec)
        check("the bookkeeping line is not marked recovered",
              recovered_of(LINES.records, "🟠 MaaEnd", "任务全部完成"), [False])
        check("it is queued for the group", any("任务全部完成" in str(x.get("line")) for x in h.pending()), True)
        # 10-06 09:51:51 and 10-09 09:31:56: an ok run ships no bundle on the failure
        # path, so MXU's log of the hang never left the machine. The no-exit run ships one.
        check("the no-exit run ships its evidence bundle", SHIPPED, [rec.run_id])
        handle._mark_no_self_exit(_Eng(), rec)
        check("a replay of the same record does not ship it twice", SHIPPED, [rec.run_id])
    finally:
        handle._ship_evidence = _real_ship
        unwatch(h)

    print("\n[bookkeeping: AUTO-MAS ended the finished MaaEnd -> recovered, a red item, not pushed]")
    # AUTO-MAS v5.7.0-beta.2 app/task/MaaEnd/AutoProxy.py: check_log logs the result, then
    # _wait_maaend_stage logs the kill; the result line's shape is the machine's
    # (2026-10-01 16:10:00.012 in that day's evidence bundle, automas-app.log).
    MAS_RESULT = "2026-10-06 09:52:55.101 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: Success!, 日志锁已释放"
    MAS_ENDED = "2026-10-06 09:52:55.104 | WARNING  | MaaEnd 自动代理 | MaaEnd 队列已结束但进程未退出，正在中止脚本进程"
    handle._ship_evidence = _fake_ship
    SHIPPED.clear()
    h, sd = watch()
    try:
        rec = RunRecord(run_id="2026-10-06/endfield/MaaEnd-05-28-02", script="MaaEnd", user="endfield",
                        started=datetime(2026, 10, 6, 9, 51, 51, tzinfo=SERVER_TZ),
                        finished=datetime(2026, 10, 6, 9, 52, 54, tzinfo=SERVER_TZ), ok=True)
        eng = _Eng(automas_app_log([MAS_RESULT, MAS_ENDED]))
        handle._mark_no_self_exit(eng, rec)
        rows = LINES.said("MaaEnd", "任务全部完成", "AUTO-MAS")
        # 10-12 20:38 the user asked why a case AUTO-MAS already fixed is reported at all -
        # AUTO-MAS ends it by design every time: one INFO line, no red item.
        check("one INFO line naming AUTO-MAS's kill", [r.levelno for r in rows], [logging.INFO])
        check("not marked recovered", [getattr(r, errwatch.RECOVERED, False) for r in rows], [False])
        red = [t for f in sorted(techlog.tech_dir(sd).glob("*.md")) for _, t in techlog.unhandled(f.read_text(encoding="utf-8"))
               if "任务全部完成" in t]
        check("no red item for it", red, [])
        check("nothing queued for the group", h.pending(), [])
        check("still booked for the technical log", [m[2:] for m in eng.state.marks], [("maaend_no_self_exit", 0)])
        check("still ships its evidence bundle", SHIPPED, [rec.run_id])
    finally:
        handle._ship_evidence = _real_ship
        unwatch(h)

    print("\n[bookkeeping: an AUTO-MAS kill line from another run is not this run's]")
    handle._ship_evidence = _fake_ship
    h, sd = watch()
    try:
        late = "2026-10-06 09:55:00.000 | WARNING  | MaaEnd 自动代理 | MaaEnd 队列已结束但进程未退出，正在中止脚本进程"
        rec = RunRecord(run_id="2026-10-06/endfield/MaaEnd-05-28-03", script="MaaEnd", user="endfield",
                        started=datetime(2026, 10, 6, 9, 51, 51, tzinfo=SERVER_TZ),
                        finished=datetime(2026, 10, 6, 9, 52, 54, tzinfo=SERVER_TZ), ok=True)
        handle._mark_no_self_exit(_Eng(automas_app_log([MAS_RESULT, late])), rec)
        check("not marked recovered", recovered_of(LINES.records, "🟠 MaaEnd", "任务全部完成"), [False])
        check("it is queued for the group", any("任务全部完成" in str(x.get("line")) for x in h.pending()), True)
    finally:
        handle._ship_evidence = _real_ship
        unwatch(h)

    ARK_LOGGER.removeHandler(LINES)


def _part_maaend_reenable():  # noqa: C901 - the whole body of the file this part was
    """Boot: the booster step is read and rings the group when unknown; no task is switched off or on.

The user, 2026-10-06, on the sanity booster: 「那个要一直开着，如果上游maaend改了导致没生效就要报警」,
and on who switched it off: 「我开的任务是谁说要关的」. Until then three boot-time functions in gameupdate.py
kept tasks off: the booster until its confirm node read as "fixed" and MaaEnd had
changed version, the four 1.5.3 dailies until MaaEnd changed version. Now every
leftover record (updates.maaend_disabled_1_5_3 / maaend_reenable_next_boot /
maaend_disabled_spmed) has its tasks switched on at the next boot, whatever the
version or the node shape, and is dropped; switching on is logged at INFO and not
pushed. The booster step is still read at every boot, and a shape the relay does not
know to work rings the group each time (texts.SPMED_UNRECOGNISED).

Since 10-13 (audit s18 F5) that re-enable step is gone: nothing writes those records
any more and the machine's state.json holds none of them (machine check #63 keeps
watching). A record found now is left alone and the master is not touched.

Run through boot_stages._stage_reenable_maaend, the entry the service calls at boot.

Inputs are real files:
* master: relay/tests/fixtures/maaend-2026-09-10/master-before.json (the
  machine's mxu-MaaEnd.json), placed at AUTO-MAS's
  data/<script id>/Default/ConfigFile/mxu-MaaEnd.json; the recorded tasks are
  switched off in the copy, which is the state the record describes. The
  standalone AutoUseSpMedication task (gone from MaaEnd since v2.28) is added to the
  copy the way the 09-03 master had it.
* MaaEnd version: interface.json from fixtures/maaend228 (v2.28.0-beta.4),
  fixtures/maaend-2026-09-10 (v2.28.0-beta.5) and
  fixtures/maaend-v2.30.0-beta.4-spmed (see its SOURCE.txt).
* nodes.json shapes: "fixed" / "broken" are the shapes described in gameupdate.py
  above SPMED_NODE (beta.5 read off the machine 09-03, upstream PR #5453); the
  "no recognition block" shape is the one gameupdate.py records for v2.28.0-beta.4
  (no copy of that file was kept, so it is built from the comment). The renamed-node
  shape is real (fixtures/maaend-v2.30.0-beta.4-spmed).

    Formerly test_maaend_reenable.py.
    """
    import json
    import logging
    import shutil
    import types
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for _n in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
               "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_n, _Stub(_n))

    import boot_stages
    from ark_relay.features.makeup import collect_retry
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.core import mastercfg, notify, texts
    from ark_relay.core.statestore import StateStore

    FIX = Path(__file__).resolve().parent / "fixtures"
    MASTER = FIX / "maaend-2026-09-10" / "master-before.json"
    V_BETA4 = FIX / "maaend228" / "interface.json"                       # v2.28.0-beta.4
    V_BETA5 = FIX / "maaend-2026-09-10" / "interface.json"                 # v2.28.0-beta.5
    V_230 = FIX / "maaend-v2.30.0-beta.4-spmed"                            # interface + nodes
    NODES_230 = V_230 / "resource" / "pipeline" / "nodes.json"
    # The confirm step under neither of its names: v2.30's real file has it as
    # __AutoUseSpMedicationUseEmergencySpBooster, in the fixed shape (test_spmed.py).
    NODES_GONE = {k: v for k, v in json.loads(NODES_230.read_text(encoding="utf-8")).items()
                  if k not in ("AutoUseSpMedicationQuickUse", "__AutoUseSpMedicationUseEmergencySpBooster")}
    FOUR = ["GiftOperator", "GearAssembly", "DeliveryJobs", "EnvironmentMonitoring"]
    SP = "AutoUseSpMedication"
    SPMED = {"taskName": SP, "enabled": False, "enabledByController": {"Win32-Front": False}, "optionValues": {}}
    RSP = {"maaend_disabled_spmed": {"tasks": [SP], "since": "v2.28.0-beta.4"}}
    FIXED = {"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
        "YellowConfirmButtonType2", {"recognition": "OCR", "expected": "确认"}]}}}}
    BROKEN = {"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
        "YellowConfirmButtonType2", {"param": {"expected": "确认"}, "type": "OCR"}]}}}}
    NO_RECOGNITION = {"AutoUseSpMedicationQuickUse": {"next": ["AutoUseSpMedicationDialogText"]}}


    class Capture(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelname, record.getMessage()))


    CAP = Capture()
    logging.getLogger(errwatch.ARK).addHandler(CAP)
    logging.getLogger(errwatch.ARK).setLevel(logging.DEBUG)


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, bool(kw.get("alert"))))
            return []


    class Log:
        def __init__(self):
            self.lines = []

        def _rec(self, *a, **k):
            self.lines.append(a)

        info = warning = error = debug = exception = _rec


    # Only the booster check is under test: the later steps of the
    # stage (dead entries, option migration, route restore) are stubbed.
    mastercfg.prune_maaend_orphans = lambda *a: ([], "")
    mastercfg.migrate_maaend_options = lambda *a: ([], "")
    collect_retry.restore_master = lambda cfg: ""
    TITLE = getattr(texts, "SPMED_UNRECOGNISED", "<no such title>")


    def machine(*, version=None, nodes=None, off=(), extra_tasks=(), master=True, record=None):
        """state dir + MaaEnd dir + AUTO-MAS dir. Returns (cfg, master path, store)."""
        root = tmpdir()
        state = root / "state"
        state.mkdir()
        maaend = root / "maaend"
        maaend.mkdir()
        if version is not None:
            shutil.copy(version, maaend / "interface.json")
        if nodes is not None:
            (maaend / "resource" / "pipeline").mkdir(parents=True)
            if isinstance(nodes, Path):
                shutil.copy(nodes, maaend / "resource" / "pipeline" / "nodes.json")
            else:
                (maaend / "resource" / "pipeline" / "nodes.json").write_text(
                    json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
        automas = root / "automas"
        target = automas / "data" / "59da8762-sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
        if master:
            target.parent.mkdir(parents=True)
            j = json.loads(MASTER.read_text(encoding="utf-8"))
            tasks = j["instances"][0]["tasks"]
            tasks.extend(json.loads(json.dumps(t)) for t in extra_tasks)
            for t in tasks:
                if t.get("taskName") in off:
                    t["enabled"] = False
                    if isinstance(t.get("enabledByController"), dict):
                        t["enabledByController"] = {k: False for k in t["enabledByController"]}
            target.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
        store = StateStore(state)
        for key, value in (record or {}).items():
            store.set("updates", key, value)
        cfg = SimpleNamespace(state_dir=state, maaend_dir=maaend, automas_dir=automas)
        return cfg, target, store


    def enabled(target, names):
        j = json.loads(target.read_text(encoding="utf-8"))
        by = {t.get("taskName"): t.get("enabled") for t in j["instances"][0]["tasks"]}
        return {n: by.get(n) for n in names}


    def others(target, names):
        """Every task not named, as (name, enabled, controllers) - to prove nothing else moved."""
        j = json.loads(target.read_text(encoding="utf-8"))
        return [(t.get("taskName"), t.get("enabled"), json.dumps(t.get("enabledByController")))
                for t in j["instances"][0]["tasks"] if t.get("taskName") not in names]


    def updates(store):
        return dict(StateStore(store.dir).section("updates"))


    def boot(cfg):
        """One boot's re-enable stage. Returns (pushes, log lines of ark.*)."""
        n = Notes()
        CAP.lines.clear()
        boot_stages._stage_reenable_maaend(cfg, n, Log())
        return n.sent, list(CAP.lines)


    def spmed_pushes(sent):
        return [(t, a) for t, _b, a in sent if t == TITLE]


    others(MASTER, FOUR)
    check("fixture versions are what the names say",
          [json.loads(p.read_text(encoding="utf-8"))["version"]
           for p in (V_BETA4, V_BETA5, V_230 / "interface.json")],
          ["v2.28.0-beta.4", "v2.28.0-beta.5", "v2.30.0-beta.4"])
    check("the real v2.30.0-beta.4 nodes.json has no AutoUseSpMedicationQuickUse",
          "AutoUseSpMedicationQuickUse" in json.loads(NODES_230.read_text(encoding="utf-8")), False)

    print("\n[booster task on, MaaEnd v2.30 with the step under neither name: the group is told, every boot]")
    on_sp = dict(SPMED, enabled=True, enabledByController={"Win32-Front": True})
    cfg, target, store = machine(version=V_230 / "interface.json", nodes=NODES_GONE, extra_tasks=[on_sp])
    sent, lines = boot(cfg)
    check("the unknown booster step rings the group", spmed_pushes(sent), [(TITLE, True)])
    check("that title routes to the group", notify.route_of(TITLE, alert=True), "group")
    body = next((b for t, b, _a in sent if t == TITLE), "")
    check("the text says the task stays on and why it rings", ("一直开着" in body, "找不到" in body), (True, True))
    check("the text is plain Chinese", texts.plain(body), [])
    sent2, _ = boot(cfg)
    check("next boot: rings again (each time it is seen)", len(spmed_pushes(sent2)), 1)

    for label, nodes in (("node with no recognition block", NO_RECOGNITION), ("the 09-03 broken shape", BROKEN)):
        print(f"\n[{label}: group told]")
        cfg, target, store = machine(version=V_BETA5, nodes=nodes, extra_tasks=[on_sp])
        sent, _ = boot(cfg)
        check("group told", len(spmed_pushes(sent)), 1)
        check("not the old 「游戏更新没能确认」 info push", [t for t, _b, _a in sent if "没能确认" in t], [])

    print("\n[booster task on, no record, booster step unknown: the task is not touched, group told]")
    on_sp = dict(SPMED, enabled=True, enabledByController={"Win32-Front": True})
    cfg, target, store = machine(version=V_230 / "interface.json", nodes=NODES_GONE, extra_tasks=[on_sp])
    before = target.read_bytes()
    sent, _ = boot(cfg)
    check("master not rewritten", target.read_bytes(), before)
    check("group told", len(spmed_pushes(sent)), 1)

    print("\n[no record, fixed shape: nothing written, nothing pushed]")
    cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=FOUR)
    before = target.read_bytes()
    sent, _ = boot(cfg)
    check("master not rewritten", target.read_bytes(), before)
    check("no push", sent, [])

    print("\n[a leftover switch-off record: left alone, the master is not touched (s18 F5)]")
    cfg, target, store = machine(version=V_BETA5, nodes=FIXED, off=FOUR + ["AutoCollect"], extra_tasks=[SPMED],
                                 record={"maaend_disabled_1_5_3": {"disabled": FOUR},
                                         "maaend_reenable_next_boot": {"tasks": ["AutoCollect"]},
                                         **RSP})
    before = target.read_bytes()
    sent, lines = boot(cfg)
    check("master not rewritten", target.read_bytes(), before)
    check("records left as they were", sorted(k for k in updates(store) if k.startswith("maaend_")),
          ["maaend_disabled_1_5_3", "maaend_disabled_spmed", "maaend_reenable_next_boot"])
    check("nothing pushed, nothing logged about them", (sent, [m for _lv, m in lines if "开回" in m]), ([], []))
    check("the re-enable functions are gone",
          [n for n in ("maaend_enable", "maaend_reenable_records", "maaend_set_enabled") if hasattr(gameupdate, n)], [])

    print("\n[the booster step's shape, read from nodes.json]")
    shape = getattr(gameupdate, "spmed_shape", None)
    check("spmed_shape exists", callable(shape), True)
    if callable(shape):
        for label, nodes, want in (("fixed", FIXED, "fixed"), ("broken", BROKEN, "broken"),
                                   ("no recognition block", NO_RECOGNITION, "unknown"),
                                   ("v2.30: the step under its new name, fixed shape", NODES_230, "fixed"),
                                   ("the step under neither name", NODES_GONE, "missing")):
            check(label, shape(machine(nodes=nodes)[0].maaend_dir), want)
        check("nodes.json missing", shape(machine()[0].maaend_dir), "unreadable")
        check("no MaaEnd directory", shape(None), "")


def _part_maaend_stopped_between_tasks():
    """A MaaEnd that stopped between two tasks is not a finished round.

`_judge_result` overrules AUTO-MAS in two places when MaaEnd's own log says the
round was done: 「部分任务执行失败: X」 (AUTO-MAS's stale name table, 2026-09-06
SellProduct -> 据点交易) and 「MaaEnd 进程超时」 (done, then never exited,
2026-09-28 11:22). Both used to accept any log in which every started task also
completed. A MaaEnd that died or was killed right after one task's 「任务完成」
leaves exactly such a log, while the tasks AUTO-MAS names never started - and the
run went into the ledger and the daily report as green.

The round is finished only when its closing task (「❌关闭游戏（PC）」 since
2026-09-18, 「⛔ 结束进程」 before) ran last and completed.

Real data: fixtures/maaend-farm-drops/2026-09-28a.log (the 09-28 11:22
done-then-hung run, ends with 关闭游戏（PC） at lines 811-812) and
fixtures/maaend_full_2026-09-01.log (ends with 结束进程 at lines 49-50). The
stopped-between-tasks logs are real prefixes of 2026-09-28a.log.

    Formerly test_maaend_stopped_between_tasks.py.
    """
    import json
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

    HERE = pathlib.Path(__file__).resolve().parent

    FIX = HERE / "fixtures"
    LOG_0928 = (FIX / "maaend-farm-drops" / "2026-09-28a.log").read_text(encoding="utf-8").splitlines(keepends=True)
    LOG_0901 = (FIX / "maaend_full_2026-09-01.log").read_text(encoding="utf-8")
    # Line 164 starts 环境监测, line 165 completes it, and line 166 starts the next task.
    assert "任务完成: 🌿环境监测" in LOG_0928[164], LOG_0928[164]
    assert "任务开始: 🌿环境监测" in LOG_0928[163], LOG_0928[163]
    assert "任务完成: ❌关闭游戏（PC）" in LOG_0928[-1], LOG_0928[-1]
    STOPPED = "".join(LOG_0928[:165])     # stopped right after 环境监测 completed
    STUCK = "".join(LOG_0928[:164])       # 环境监测 started, never ended
    FULL = "".join(LOG_0928)

    root = tmpdir()
    day = root / "2026-09-28" / "endfield"
    day.mkdir(parents=True)
    _n = [0]


    def record(result, log, stem=None):
        _n[0] += 1
        stem = stem or f"MaaEnd-06-{_n[0]:02d}-00"
        (day / f"{stem}.json").write_text(json.dumps({"maaend_result": result}, ensure_ascii=False), encoding="utf-8")
        (day / f"{stem}.log").write_text(log, encoding="utf-8")
        return stem, collector.parse_record(day / f"{stem}.json", root)


    print("[stopped after 环境监测; AUTO-MAS lists 自动采集, which never started]")
    stem_stopped, r = record("[日常] MaaEnd 部分任务执行失败: 🧺自动采集", STOPPED)
    check("not a success", r.ok, False)
    check("keeps AUTO-MAS's list", r.failed_tasks, ["自动采集"])
    check("not marked as a name mismatch", r.raw.get("maaend_name_mismatch"), None)

    print("\n[stopped after 环境监测, killed for 进程超时]")
    _, r = record("MaaEnd 进程超时", STOPPED)
    check("not a success", r.ok, False)
    check("says it timed out", r.failed_tasks, ["MaaEnd 进程超时"])
    check("not marked done-then-hung", r.raw.get("maaend_done_then_hung"), None)

    print("\n[the full 09-28 11:22 log, killed for 进程超时 -> done, then hung]")
    _, r = record("MaaEnd 进程超时", FULL)
    check("ok", r.ok, True)
    check("no failures", r.failed_tasks, [])
    check("marked done-then-hung", r.raw.get("maaend_done_then_hung"), True)

    print("\n[the full 09-28 log, AUTO-MAS cannot match a renamed task (关闭游戏 era)]")
    _, r = record("MaaEnd 部分任务执行失败: SellProduct", FULL)
    check("ok", r.ok, True)
    check("records the name AUTO-MAS missed", r.raw.get("maaend_name_mismatch"), ["SellProduct"])

    print("\n[the full 09-01 log, renamed task (结束进程 era)]")
    d01 = root / "2026-09-01" / "endfield"
    d01.mkdir(parents=True)
    (d01 / "MaaEnd-03-00-00.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: SellProduct"}, ensure_ascii=False), encoding="utf-8")
    (d01 / "MaaEnd-03-00-00.log").write_text(LOG_0901, encoding="utf-8")
    r = collector.parse_record(d01 / "MaaEnd-03-00-00.json", root)
    check("ok", r.ok, True)
    check("records the name AUTO-MAS missed", r.raw.get("maaend_name_mismatch"), ["SellProduct"])

    print("\n[stuck mid-task: 环境监测 started, no end]")
    _, r = record("MaaEnd 部分任务执行失败: 🌿环境监测", STUCK)
    check("partial failure stays a failure", (r.ok, r.failed_tasks), (False, ["环境监测"]))
    _, r = record("MaaEnd 进程超时", STUCK)
    check("timeout stays a failure", (r.ok, r.failed_tasks), (False, ["MaaEnd 进程超时"]))

    print("\n[never started: the log has no task line at all]")
    _, r = record("MaaEnd 部分任务执行失败: 🎁赠送干员礼物", "".join(LOG_0928[:13]))
    check("partial failure stays a failure", (r.ok, r.failed_tasks), (False, ["赠送干员礼物"]))
    _, r = record("MaaEnd 进程超时", "".join(LOG_0928[:13]))
    check("timeout stays a failure", (r.ok, r.failed_tasks), (False, ["MaaEnd 进程超时"]))

    print("\n[closing task started but never completed]")
    _, r = record("MaaEnd 进程超时", "".join(LOG_0928[:-1]))
    check("not a success", r.ok, False)

    print("\n[a task started after the closing task]")
    _, r = record("MaaEnd 进程超时", FULL + "[2026-09-28 11:22:11.000] 任务开始: 🧺自动采集\n"
                  "[2026-09-28 11:22:12.000] 任务完成: 🧺自动采集\n")
    check("not a success", r.ok, False)

    print("\n[re-judging the ledger only moves towards done]")
    run_id = f"2026-09-28/endfield/{stem_stopped}"
    old = {"run_id": run_id, "script": "MaaEnd", "ok": False, "failed_tasks": ["自动采集"], "raw": {}}
    fresh = collector.refresh_raw(old, root)
    check("stopped run stays failed", (fresh.get("ok"), fresh.get("failed_tasks")), (False, ["自动采集"]))
    old_ok = {"run_id": run_id, "script": "MaaEnd", "ok": True, "failed_tasks": [], "raw": {}}
    fresh = collector.refresh_raw(old_ok, root)
    check("an entry already marked ok is left ok", (fresh.get("ok"), fresh.get("failed_tasks")), (True, []))

    print("\n[audit 11-08 B-02/B-03: a closing task does not excuse tasks that never started]")
    from ark_relay.features.verify.collector_maaend import _maaend_all_done
    from ark_relay.features.verify import outcome
    full = "".join(LOG_0928)
    check("the real 09-28 round, closing task last: done", _maaend_all_done(full), True)
    no_proto = "".join(x for x in LOG_0928 if "⚔️协议空间" not in x)
    check("closing task ran, but a display name AUTO-MAS lists never started: not done",
          _maaend_all_done(no_proto, ["协议空间"]), False)
    check("the listed name did start (AUTO-MAS's stale verdict): still done", _maaend_all_done(full, ["协议空间"]), True)
    check("a bare key AUTO-MAS could not name still passes (09-06 SellProduct)", _maaend_all_done(full, ["SellProduct"]), True)
    twice = full.replace("[2026-09-28 11:22:07.978] 任务开始: ❌关闭游戏（PC）",
                         "[2026-09-28 11:22:07.000] 任务开始: 🎁赠送干员礼物\n[2026-09-28 11:22:07.978] 任务开始: ❌关闭游戏（PC）")
    check("a task started twice and completed once is not done (count, not set)", _maaend_all_done(twice), False)
    cut = [c for c in outcome._maaend_cut_short(twice) if not c.ok]
    check("maaend_checks: started without an end is a failed check", [c.label for c in cut], ["赠送干员礼物 跑完"])
    stop_log = (FIX / "maaend_stop_task_2026-10-08.log").read_text(encoding="utf-8")
    cut = outcome._maaend_cut_short(stop_log)
    check("10-08 10:34 MaaEnd stopped itself before the closing task: failed check", [c.label for c in cut],
          ["MaaEnd 没被中途停掉"])
    hung = full + "[2026-09-28 11:40:00.000] 任务开始: 停止任务\n[2026-09-28 11:40:00.100] 任务完成: 停止任务\n"
    check("a stop after the closing task (AUTO-MAS stopping a done MaaEnd) is not a failure",
          outcome._maaend_cut_short(hung), [])

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_maaend_stub_record():
    """A MaaEnd record AUTO-MAS wrote for an attempt that never ran is not a run.

Real records, 2026-09-18 morning (tests/fixtures/maaend-2026-09-18/): AUTO-MAS
relaunched MaaEnd at 09:54:35 while MaaEnd was installing its own update and
restarting; the attempt's record is a 30-byte stub with 「未捕获到日志」. The
relay counted it: 「❌ MaaEnd 失败（尝试 3 次）」 for two real attempts, and the
report would have listed a third row. Also: every bundle now carries the
window's slice of relay.log and AUTO-MAS's app.log, because that stub could only
be explained from those two files and neither was in any bundle.

    Formerly test_maaend_stub_record.py.
    """
    import os
    import shutil
    import tempfile
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.features.evidence import evidence
    from ark_relay.features.alarm import handle
    from ark_relay.core import ledger as core

    FIX = Path(__file__).parent / "fixtures" / "maaend-2026-09-18"


    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "history"
        d = root / "2026-09-18" / "endfield"
        d.mkdir(parents=True)
        for f in FIX.iterdir():
            shutil.copy(f, d / f.name)
        recs = {n: collector.parse_record(d / f"{n}.json", root) for n in ("MaaEnd-05-26-03", "MaaEnd-05-54-35", "MaaEnd-05-54-44")}

        print("[空记录：解析为「中途重启」，不算失败、不进失败清单]")
        stub = recs["MaaEnd-05-54-35"]
        check("解析出来了", stub is not None)
        check("不算成功", stub.ok, False)
        check("标为中途重启", stub.transitional, True)
        check("失败清单为空", stub.failed_tasks, [])
        real1, real3 = recs["MaaEnd-05-26-03"], recs["MaaEnd-05-54-44"]
        check("真失败的两趟照旧：不是中途重启、失败清单有基质刷取",
              (real1.transitional, real3.transitional, real1.failed_tasks, real3.failed_tasks),
              (False, False, ["基质刷取"], ["基质刷取"]))

        print("\n[尝试次数：只数真跑过的]")
        ledger = [{"run_id": r.run_id, "script": r.script, "user": r.user, "ok": r.ok,
                   "started": r.started.isoformat(), "finished": r.finished.isoformat(),
                   "failed_tasks": r.failed_tasks, "transitional": r.transitional, "raw": r.raw}
                  for r in (real1, stub, real3)]
        eng = types.SimpleNamespace(state=types.SimpleNamespace(read_ledger=lambda day: ledger))
        check("三条记录，尝试 2 次", handle._attempts(eng, real3, "2026-09-18"), 2)

        print("\n[日报：空记录不成一行；两趟真失败合并为一行]")
        core.episode_kinds(ledger)
        title, body = core.format_daily("2026-09-18", ledger, "", "")
        check("空记录不出现在日报里", "05-54-35" not in body and "未捕获" not in body)
        check("基质刷取的失败出现", "基质刷取" in body)
        check("标题不是全绿", "全绿" not in title)
        check("日报里有一行信息：重启 1 次、未计失败", "终末地装新版后自己重启 1 次，未计失败" in body)
        check("标题只数两趟真失败，不含空记录", "终末地失败 2 次" in title)

        print("\n[老版本记的账没有 transitional 标记（09-18 早上的三条就是）：照样不算失败]")
        # The evening report of 2026-09-18 listed the stub as one of three failures:
        # the morning entries were booked by v20260918005050, before the flag existed.
        old_ledger = [dict(e) for e in ledger]
        for e in old_ledger:
            e.pop("transitional", None)
        title_o, body_o = core.format_daily("2026-09-18", old_ledger, "", "")
        check("没有标记也不成一行", "05-54-35" not in body_o and "未捕获" not in body_o)
        check("没有标记也只算 2 次失败（09-18 晚报成了 3 项）", "终末地失败 2 次" in title_o)
        check("信息行照样有", "终末地装新版后自己重启 1 次，未计失败" in body_o)
        check("没有重启的日子不出这一行", "自更新重启" not in core.format_daily("2026-09-18", [e for e in ledger if e is not ledger[1]], "", "")[1])

    print("\n[证据包带上 relay.log 与调度程序 app.log 的时间窗切片]")
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "automas" / "debug").mkdir(parents=True)
        t0 = datetime(2026, 9, 18, 9, 54, 0)
        relay_log = t / "relay.log"
        relay_log.write_text(
            "09-18 09:40:00 INFO    ark.service  太早，不在窗内\n"
            "09-18 09:54:36 WARNING ark.handle  ⏳ MaaEnd 失败，暂不推送，等重试结果\n"
            "Traceback (most recent call last):\n"
            "  File \"x.py\", line 1\n"
            "09-18 10:30:00 INFO    ark.service  太晚，不在窗内\n", encoding="utf-8")
        (t / "automas" / "debug" / "app.log").write_text(
            "2026-09-18 09:20:00.000 | INFO | 早\n"
            "2026-09-18 09:54:35.100 | INFO | MaaEnd 自动代理 | 启动 MaaEnd\n"
            "2026-09-18 09:54:44.200 | WARNING | MaaEnd 自动代理 | 未捕获到日志\n"
            "2026-09-18 11:00:00.000 | INFO | 晚\n", encoding="utf-8")
        os.environ["ARK_LOG_FILE"] = str(relay_log)
        cfg = types.SimpleNamespace(automas_dir=t / "automas", state_dir=t / "state", maaend_dir=None, maa_dir=None, okww_dir=None, history_dir=None)
        win = (t0.timestamp(), (t0 + timedelta(minutes=12)).timestamp())
        files = evidence.context_files(cfg, win, t / "out")
        names = sorted(p.name for p in files)
        check("两个切片都在", names, ["automas-app.log", "relay.log"])
        rl = (t / "out" / "relay.log").read_text(encoding="utf-8")
        check("中继日志只留窗内的行，堆栈续行跟着", "09:54:36" in rl and "Traceback" in rl and "line 1" in rl and "太早" not in rl and "太晚" not in rl)
        al = (t / "out" / "automas-app.log").read_text(encoding="utf-8")
        check("调度程序日志只留窗内的行", "09:54:35" in al and "未捕获到日志" in al and "早" not in al.replace("早", "", 0) or ("09:20" not in al and "11:00" not in al))
        res = evidence.save_and_upload(cfg, "MaaEnd", "2026-09-18/endfield/MaaEnd-05-54-35", window=win)
        check("save_and_upload 的包里带上了两个切片", set(("relay.log", "automas-app.log")) <= set(res["files"]))
        check("没有 COS 时不炸、包照打", bool(res["archive"]))

    print()
    if fails:
        print("FAILED:", fails); sys.exit(1)
    print("all checks passed")


def _part_maaend_task_silent():
    """maaend_task.py must not exit 0 when the run timed out or the agent did not stop.

Silent-failure audit row scripts/mac/lib/maaend_task.py:92: 「停 agent 失败」 was
printed and main still returned 0, as did the timeout path, so a chained `&&`
or any caller saw success while the MaaEnd agent might still be running.

    Formerly test_maaend_task_silent.py.
    """
    import contextlib
    import io

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
    import maaend_task as mt


    def run(agent_stop_fails, still_running):
        calls = []

        def api(path, body=None, timeout=30):
            calls.append(path)
            if path == "/maa/state":
                return {"instances": {"i1": {"connected": True, "resource_loaded": True,
                                             "is_running": still_running}}}
            if path.endswith("/agent/stop") and agent_stop_fails:
                raise OSError("connection reset")
            return {"ok": True}

        mt.api = api
        mt.preflight = lambda: ({"i1": {"connected": True, "resource_loaded": True}}, [])
        mt.pick_instance = lambda inst: "i1"
        mt.ensure_resource = lambda k: None
        mt.time.sleep = lambda s: None
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = mt.main(["maaend_task.py", "--entry", "E", "--go", "--timeout", str(1 if not still_running else 0)])
        return rc, out.getvalue(), calls


    print("[the run finished, agent stopped]")
    rc, out, calls = run(agent_stop_fails=False, still_running=False)
    check("exit 0", rc, 0)
    check("agent stop was asked", "/maa/instances/i1/agent/stop" in calls, True)

    print("[the run finished, agent stop failed]")
    rc, out, _ = run(agent_stop_fails=True, still_running=False)
    check("the failure is printed", "停 agent 失败" in out, True)
    check("exit non-zero after a failed agent stop", rc, 1)

    print("[the run timed out]")
    rc, out, calls = run(agent_stop_fails=False, still_running=True)
    check("the task was stopped", "/maa/instances/i1/tasks/stop" in calls, True)
    check("exit non-zero after a timeout", rc, 1)


if __name__ == "__main__":
    sys.exit(run_parts([_part_maaend_app_log, _part_maaend_dir_resolve, _part_maaend_false_green, _part_maaend_logged_out, _part_maaend_recovered, _part_maaend_reenable, _part_maaend_stopped_between_tasks, _part_maaend_stub_record, _part_maaend_task_silent]))
