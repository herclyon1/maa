"""OK-WW's runs: the alive cache, drift, error events and reasons, the exit race, failed reasons, i18n, landed, names not numbers, the Python filter, the quiesce order, the report, structured lines.

One part per former file, each run on its own (tests/_parts.py): test_okww_alive_cache.py, test_okww_drift.py, test_okww_error_event.py, test_okww_error_reason.py, test_okww_exit_race.py, test_okww_failed_reason.py, test_okww_i18n.py, test_okww_landed.py, test_okww_names_not_numbers.py, test_okww_python_filter.py, test_okww_quiesce_order.py, test_okww_report.py, test_okww_structured.py.
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


def _part_okww_alive_cache():
    """OK-WW's python check on a phone publish: cached, and never asked by the stop push.

snapshot._runtime asked redbutton._okww_python_alive on every publish (f6a8e515);
an unreadable process list retries 3 x 3 s (procs.python_processes), so the
停止前 push, which must land inside SvcStop's 15 s timer, could stall 6 s+.
Now one answer serves snapshot.OKWW_ALIVE_TTL seconds, and the 停止前 / 关机前
pushes (phone.send_state) never ask: they report the last answer, or 「没查」.

    Formerly test_okww_alive_cache.py.
    """
    import contextlib
    import subprocess
    import tempfile
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.phone import phone, redbutton, snapshot

    # getattr: on the old code (no cache) the test reaches its assertions and fails there.
    CACHE = getattr(snapshot, "_okww_alive", {"at": 0.0, "alive": None})
    TTL = getattr(snapshot, "OKWW_ALIVE_TTL", 30.0)
    NO_QUERY = getattr(snapshot, "no_process_query", contextlib.nullcontext)


    asked = []


    def fake_alive():
        asked.append(1)
        return True


    class Box:
        last_error = ""
        quota = types.SimpleNamespace(total=lambda: 0)

        def publish(self, payload):
            return True


    def tmp():
        return tempfile.mkdtemp()


    cfg = types.SimpleNamespace(automas_dir=tmp(), maaend_dir=tmp(), okww_dir=tmp(), state_dir=tmp())
    saved = (redbutton._okww_python_alive, subprocess.run, dict(CACHE))
    redbutton._okww_python_alive = fake_alive
    subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout="", stderr="", returncode=0)
    try:
        print("\n[30 秒内两次上报只查一次鸣潮脚本的 python]")
        CACHE.update(at=None, alive=None)
        a = snapshot.read_runtime()
        b = snapshot.read_runtime()
        check("查了一次", len(asked), 1)
        check("两次都报鸣潮脚本在跑", [a["程序"].get("ok-ww"), b["程序"].get("ok-ww")], [True, True])

        print("\n[停止前那份不查，报上次的结果]")
        asked.clear()
        CACHE["at"] = (CACHE["at"] or 0.0) - TTL - 1    # the cached answer is stale
        ok, payload, _ = phone.send_state(Box(), cfg, "停止前")
        check("送到了", ok, True)
        check("停止前没查", len(asked), 0)
        check("停止前报上次的结果", "ok-ww" in (payload.get("run") or {}).get("在跑的", []), True)

        print("\n[关机前一次都没查过：不查，写「没查」]")
        CACHE.update(at=None, alive=None)
        phone.send_state(Box(), cfg, "关机前")
        check("关机前没查", len(asked), 0)
        with NO_QUERY():
            check("没查过时写「没查」", snapshot.read_runtime().get("OK-WW python"), "没查")

        print("\n[普通上报过期了照常再查]")
        phone.send_state(Box(), cfg, "刷新")
        check("刷新查了一次", len(asked), 1)
    finally:
        redbutton._okww_python_alive, subprocess.run = saved[0], saved[1]
        CACHE.clear()
        CACHE.update(saved[2])

    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)
    print("\nall passed")


def _part_okww_drift():
    """Before the run, the relay knows whether OK-WW's update broke a pinned copy.

10-03 OK-WW went to v3.7.3 and changed find_nest. Nothing looked until the morning
run's result check, which pushed 「这一轮没干完」 to the group on 10-04 and 10-05.
okww_overlay.drift() reads the source on disk after the pre-update (and at boot) and
hashes each pinned method the way the overrides do (inspect.getsource), so the
mismatch is a line at boot, said once - not an alarm after the run.

    Formerly test_okww_drift.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay


    V373 = (Path(__file__).resolve().parent / "fixtures"
            / "okww-NightmareNestTask-v3.7.3.py.txt").read_text(encoding="utf-8")
    # v3.7.2's find_nest differs from v3.7.3's in the box top only (diff of the two releases).
    V372 = V373.replace("counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re)",
                        "counts = self.ocr(0.35, 0.13, 1, 0.96, match=self.count_re)")
    # The OK-WW the machine runs (test_gl_okww_contract.INSTALLED): the pins are its bodies.
    INST = Path(__file__).resolve().parent / "gamesim" / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task"
    VINST = (INST / "NightmareNestTask.py.txt").read_text(encoding="utf-8")
    DAILY_INST = (INST / "DailyTask.py.txt").read_text(encoding="utf-8")


    def okww(nest_text, extra=None):
        root = tmpdir()
        src = root.joinpath(*okww_overlay._SRC)
        src.mkdir(parents=True)
        # Windows line ends, as on the machine: the hash must not depend on them.
        (src / "NightmareNestTask.py").write_bytes(nest_text.replace("\n", "\r\n").encode("utf-8"))
        for name, text in (extra or {}).items():
            (src / name).write_text(text, encoding="utf-8")
        return root


    print("\n[钉住的三处都从覆盖文件里读出来]")
    got = {f"{c}.{m}": (sha, a) for c, m, sha, a in okww_overlay.pins()}
    check("find_nest 钉 v3.7.14-beta.2，且会适配", got.get("NightmareNestTask.find_nest"), ("cae94d349d31", True))
    check("周本开启挑战钉住，不适配", got.get("FarmEchoTask.click_team_challenge", ("", None))[1], False)
    check("体力读数钉住", "BaseWWTask.get_stamina" in got)

    print("\n[the two copies that check their own fingerprint are pinned too (audit 2026-10-13, A3)]")
    # claim_daily and claim_battle_pass compare _src_sha with a constant inside the
    # overrides instead of through expect_sha=; until 10-13 pins() read only the
    # expect_sha= form, so the pre-run drift check covered 3 of 5.
    check("five pins in all", len(okww_overlay.pins()), 5)
    check("claim_daily pinned to v3.7.14-beta.2, not adapted", got.get("DailyTask.claim_daily"), ("555de9348dc7", False))
    check("claim_battle_pass pinned to v3.7.14-beta.2, not adapted",
          got.get("DailyTask.claim_battle_pass"), ("0a11121c349a", False))
    check("upstream v3.7.14-beta.2 DailyTask on disk: no drift",
          okww_overlay.drift(okww(VINST, {"DailyTask.py": DAILY_INST})), [])
    changed = DAILY_INST.replace("    def claim_daily(self):\n", "    def claim_daily(self):\n        pass\n", 1)
    d = okww_overlay.drift(okww(VINST, {"DailyTask.py": changed}))
    check("a changed claim_daily is found before the run", [x["what"] for x in d], ["DailyTask.claim_daily"])

    print("\n[装着的 v3.7.14-beta.2 在盘上：对得上，不出声]")
    check("没有对不上的", okww_overlay.drift(okww(VINST)), [])
    check("一句话都不说", okww_overlay.drift_line(okww(VINST), tmpdir()), "")

    print("\n[盘上是旧版（或下一版）：开跑前就说，且只说一次]")
    d = okww_overlay.drift(okww(V372))
    check("找出 find_nest", [x["what"] for x in d], ["NightmareNestTask.find_nest"])
    check("算出来的就是旧版哈希", d[0]["got"] if d else "", "3b0271924cac")
    state = tmpdir()
    line = okww_overlay.drift_line(okww(V372), state)
    # find_nest is adapted automatically: logged, but not worded as a fault (audit
    # 2026-10-13, A5 - 「对不上」 made the title ⚠️ for a copy that needs nothing).
    check("adapted only: no 对不上", "对不上" in line, False)
    check("说了会适配", "按新版适配" in line)
    check("names the method", "NightmareNestTask.find_nest" in line)
    from ark_relay.core import texts
    check("adapted only: healthy 🩹 title", texts.patches(1, [line]).startswith("🩹"), True)
    check("同一处第二次开机不再说", okww_overlay.drift_line(okww(V372), state), "")

    print("\n[skipped pin (no adapt): said at every boot - its override stays off until copied again]")
    # The user, 2026-10-06: 「不论多少次什么错误都要发」. Until then a skipped copy was said
    # once per distinct mismatch, like an adapted one.
    farm = ("class FarmEchoTask:\n    def click_team_challenge(self):\n"
            "        return 'changed upstream'\n")
    state = tmpdir()
    first = okww_overlay.drift_line(okww(VINST, {"FarmEchoTask.py": farm}), state)
    check("first boot: said", "FarmEchoTask.click_team_challenge" in first and "等我们重抄" in first)
    again = okww_overlay.drift_line(okww(VINST, {"FarmEchoTask.py": farm}), state)
    check("second boot, same mismatch: said again", again, first)
    check("skipped: counted and worded as a fault", "有 1 处和新版对不上" in first, True)
    both = okww_overlay.drift_line(okww(V372, {"FarmEchoTask.py": farm}), tmpdir())
    check("skipped + adapted: only the skipped one is counted", "有 1 处和新版对不上" in both, True)
    check("skipped + adapted: the adapted one still said", "NightmareNestTask.find_nest" in both, True)

    print("\n[方法在父类里：顺着父类找]")
    base = "class BaseWWTask:\n    def get_stamina(self):\n        return 1\n"
    child = "from x import BaseWWTask\n\n\nclass FarmEchoTask(BaseWWTask):\n    def other(self):\n        pass\n"
    classes = okww_overlay._classes(okww(V373, {"BaseWWTask.py": base, "FarmEchoTask.py": child}).joinpath(*okww_overlay._SRC))
    check("子类没有就找到父类的", okww_overlay._method_sha(classes, "FarmEchoTask", "get_stamina")
          == okww_overlay._method_sha(classes, "BaseWWTask", "get_stamina") != "")

    print("\n[读不出来的不算对不上]")
    check("文件不在就不报", okww_overlay.drift(tmpdir()), [])
    check("没给目录也不报", okww_overlay.drift(None), [])

    print("\n[运行时报告里的「已适配」也说成人话]")
    okww_overlay.REPORT = tmpdir() / "r.json"
    okww_overlay.REPORT.write_text('{"applied": [], "skipped": [], "adapted": [{"what": "NightmareNestTask.find_nest", "why": "x"}], "error": ""}', encoding="utf-8")
    check("说了已按新版适配", "已按新版适配：NightmareNestTask.find_nest" in okww_overlay.report_line())

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_error_event():
    """The reason a run failed is read from the last event's own tracebacks, grouped by time.

OK-WW prints one raise as several tracebacks (the task, DailyTask.run_task_by_class,
TaskExecutor's 「Daily Task exception stopped」); the innermost one carries the
reason. collector_okww._okww_error grouped them by distance in the text (6000
characters). On 2026-09-01 06:35 (tests/replay/2026-09-01/wuwa/OK-WW-06-35-43.log)
the stacks between one event's headers were 36352 / 36937 characters long, so the
task's own header fell out and the reason became the wrapper's 「任务执行：等一个画面没等到」.
Audit 2026-10-13 item 7: grouped by timestamp now (headers within 2 s = one event).

    Formerly test_okww_error_event.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww as co


    print("[the real 09-01 log: the weekly claim's own wait, not the wrapper]")
    real = (Path(__file__).resolve().parent / "replay" / "2026-09-01" / "wuwa" / "OK-WW-06-35-43.log"
            ).read_text(encoding="utf-8", errors="replace")
    err = co._okww_error(real)
    check("names the task", err.startswith("周本："), True)
    check("the wait it timed out on", "等一个画面没等到" in err and "10 秒" in err, True)

    STACK = "".join(f'  File "x{i}.py", line {i}, in f\n    g()\n' for i in range(600))   # ~16 KB


    def head(ts, who, msg):
        return f"2026-09-01 {ts} ERROR TaskExecutor {who}:{msg} Traceback (most recent call last):\n"


    print("\n[one event, headers far apart in the text but within 2 s: grouped]")
    text = ("2026-09-01 10:50:13,335 INFO TaskExecutor TaskExecutor:wait_until timeout <f> 10 seconds\n"
            + head("10:50:13,348", "FarmEchoTask", "farm 4c error, try handle monthly card")
            + STACK + "ok.task.exceptions.WaitFailedException\n\n"
            + head("10:50:14,879", "DailyTask", "run_task_by_class <class 'src.task.FarmEchoTask.FarmEchoTask'>")
            + STACK + "ok.task.exceptions.WaitFailedException\n\n"
            + head("10:50:15,017", "TaskExecutor", "📅 Daily Task exception stopped")
            + STACK + "ok.task.exceptions.WaitFailedException\n")
    check("the task's own header wins", co._okww_error(text).startswith("周本："), True)

    print("\n[two events minutes apart, close in the text: not merged]")
    text = (head("10:40:00,000", "NightmareNestTask", "NightmareNestTask Failed")
            + "ok.task.exceptions.TaskDisabledException\n\n"
            + head("10:45:00,000", "TaskExecutor", "📅 Daily Task exception stopped")
            + "ok.task.exceptions.WaitFailedException\n")
    cluster = co._last_event(text, list(co._OKWW_TB_HEAD.finditer(text)))
    check("the earlier event stays out", [m.group(1) for m in cluster], ["TaskExecutor"])

    print("\n[header lines without a timestamp: the old distance rule]")
    text = (" ERROR TaskExecutor FarmEchoTask:x Traceback (most recent call last):\n"
            + " ERROR TaskExecutor TaskExecutor:y Traceback (most recent call last):\n")
    check("near in the text: one event",
          len(co._last_event(text, list(co._OKWW_TB_HEAD.finditer(text)))), 2)

    print("\n[how long it waited: the timeout line of the same raise, found by time (item 8)]")
    # Measured over every real log on 2026-10-13: the timeout line is at most 0.62 s
    # before its header, but up to 2558 characters back; the old window was 600.
    real = (Path(__file__).resolve().parent / "fixtures" / "m6-okww" / "0921-weekly.log").read_text(encoding="utf-8")
    check("09-21: the 10 s wait is said", co._okww_error(real).endswith("（等了 10 秒）"), True)
    wait = "2026-09-01 10:50:13,335 INFO TaskExecutor TaskExecutor:wait_until timeout <f> 10 seconds\n"
    far = wait + STACK[:5000] + "\n" + head("10:50:13,900", "FarmEchoTask", "farm 4c error, try handle monthly card")
    check("5000 characters back, same second: found", co._wait_before(far, far.rindex(" ERROR")), "10")
    stale = ("2026-09-01 10:49:00,000 INFO TaskExecutor TaskExecutor:wait_until timeout <f> 7 seconds\n"
             + head("10:50:13,900", "FarmEchoTask", "farm 4c error"))
    check("a wait a minute earlier is another event", co._wait_before(stale, stale.rindex(" ERROR")), "")

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_error_reason():
    """OK-WW 失败原因要写真的，「进不了游戏」只给真没进去的那种。

2026-09-07 早班三趟：开头一句「waiting for game to start error … is not connected」
（几秒后就连上了），跑了 41 分钟，倒在周本结算页（FarmEchoTask 抛 WaitFailedException），
没开过无音区的局。日报把三趟都写成「进不了游戏（服务器维护／客户端待更新），今天跳过」。
用户：「这三次报错可不是因为他没进去游戏。这个检查报错原因的机制有问题。」

    Formerly test_okww_error_reason.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector


    TODAY = """2026-09-07 09:19:33,751 INFO MainThread ok:ok-script init v3.6.7
2026-09-07 09:20:14,057 ERROR ok.core.start_controller start_controller:Game window is not connected BitBlt_True_1920x1080
2026-09-07 09:20:14,057 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮   is not connected, please select the game window.
2026-09-07 09:20:29,575 INFO ok.core.start_controller start_controller:check_device_error: capturing frame (1920, 1080)
2026-09-07 09:20:35,000 INFO TaskExecutor DailyTask:info_set current task wait main esc=True
2026-09-07 09:24:01,913 ERROR TaskExecutor CombatCheck:target_enemy failed, try recheck break out of combat
2026-09-07 10:00:32,309 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认
2026-09-07 10:00:43,326 INFO TaskExecutor TaskExecutor:wait_until timeout <function FindFeature.wait_click_feature.<locals>.<lambda> at 0x0000021FA99996C0> 10 seconds
2026-09-07 10:00:43,366 ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card Traceback (most recent call last):
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\src\\task\\FarmEchoTask.py", line 103, in run
    return self.do_run()
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\ok\\task\\TaskExecutor.py", line 445, in wait_condition
    raise WaitFailedException()
ok.task.exceptions.WaitFailedException
2026-09-07 10:00:44,876 ERROR TaskExecutor DailyTask:run_task_by_class <class 'src.task.FarmEchoTask.FarmEchoTask'> Traceback (most recent call last):
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\ok\\task\\task.py", line 1116, in run_task_by_class
    task.run()
ok.task.exceptions.WaitFailedException
2026-09-07 10:00:44,885 INFO TaskExecutor DailyTask:info_set 错误
2026-09-07 10:00:44,891 ERROR TaskExecutor TaskExecutor:📅 Daily Task exception stopped Traceback (most recent call last):
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\ok\\task\\TaskExecutor.py", line 571, in execute
    task.run()
ok.task.exceptions.WaitFailedException
2026-09-07 10:00:44,900 INFO TaskExecutor FeatureSet:read_from_json D:\\ark\\okww\\data\\apps\\ok-ww\\working\\assets
"""
    STUCK = """2026-09-02 09:18:58,791 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮 is not connected
2026-09-02 09:19:10,000 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮 is not connected
"""
    d = tmpdir()
    (d / "today.log").write_text(TODAY, encoding="utf-8")
    (d / "stuck.log").write_text(STUCK, encoding="utf-8")

    print("[今天的形状：开头窗口连不上、后来跑了 41 分钟、倒在周本]")
    t = collector.parse_okww_log(d / "today.log")
    check("不是「进不了游戏」", t.get("okww_unreachable"), None)
    check("真实原因是人话", t.get("okww_error"), "周本：等一个画面没等到（等了 10 秒）")
    import re as _re
    check("通知字段里除 Boss 外不许有英文", bool(_re.search(r"[A-Za-z]", (t.get("okww_error") or "").replace("Boss", ""))), False)

    print("[2026-09-02 的形状：只会等窗口，什么都没干]")
    s = collector.parse_okww_log(d / "stuck.log")
    check("这才是进不了游戏", s.get("okww_unreachable"), True)
    check("没有 traceback 就没有原因", s.get("okww_error"), None)

    print("[记录里失败清单换成真实原因]")
    import json
    h = d / "2026-09-07" / "wuwa"; h.mkdir(parents=True)
    (h / "OK-WW-05-19-17.json").write_text(json.dumps({"general_result": "OK-WW 流程产生错误，请检查游戏状态"}), encoding="utf-8")
    (h / "OK-WW-05-19-17.log").write_text(TODAY, encoding="utf-8")
    rec = collector.parse_record(h / "OK-WW-05-19-17.json", d)
    check("判失败", rec.ok, False)
    check("失败于写真实原因", rec.failed_tasks, ["周本：等一个画面没等到（等了 10 秒）"])
    check("不标 unreachable", rec.raw.get("okww_unreachable"), None)

    print("[没见过的原文、认识的异常：按异常写具体的，带等了多久]")
    UNKNOWN = TODAY.replace("FarmEchoTask:farm 4c error, try handle monthly card", "TacetTask:some brand new english message")
    (d / "unknown.log").write_text(UNKNOWN, encoding="utf-8")
    u = collector.parse_okww_log(d / "unknown.log")
    check("按异常写", u.get("okww_error"), "无音区：等一个画面没等到（等了 10 秒）")
    check("不漏英文", bool(_re.search(r"[A-Za-z]", u.get("okww_error") or "")), False)

    print("[中继自己的覆盖层按失败结束：原因本来就是中文，照用，不说不认识]")
    from ark_relay.features.verify import collector_okww as _cok
    _said = []
    _h = type("H", (__import__("logging").Handler,), {"emit": lambda self, r: _said.append(r.getMessage())})()
    _cok.log.addHandler(_h)
    why = _cok._okww_say("FarmEchoTask", "这一趟按失败结束：周本：结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）", "ArkStopped")
    check("原因照用", why, "周本：结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）")
    check("不说不认识", "不认识" in why, False)
    check("不记「还没有翻译」的警告", [m for m in _said if "还没有翻译" in m], [])
    _cok.log.removeHandler(_h)

    print("[原文和异常都不认识：明说不认识，并且**把原文抄进来**]")
    # 2026-09-08 改的：原来这里只说「原文已记进日志，要补翻译」。那天 OK-WW 早班连败三次，
    # 通知就是这么写的——而机器跑完早班就断电了，日志要等到 21:20 那趟开机才够得着。
    # 人看着告警想知道出了什么事的那一刻，恰恰是日志最够不着的那一刻。
    # 所以现在原文照抄进通知：英文一行看得懂，总比「不知道发生了什么」强。
    UNK2 = UNKNOWN.replace("ok.task.exceptions.WaitFailedException", "ok.task.exceptions.SomethingNewException")
    (d / "unk2.log").write_text(UNK2, encoding="utf-8")
    u2 = collector.parse_okww_log(d / "unk2.log")
    got = u2.get("okww_error") or ""
    check("点名了是哪一步", got.startswith("无音区："), True)
    check("明说不认识", "中继还不认识这条错" in got, True)
    check("原文照抄进来了", "some brand new english message" in got, True)
    check("不出现「出错」「这一步」这类模糊词",
          any(k in got.split("原文照抄")[0] for k in ("这一步", "出错", "异常", "错误")), False)

    # ---- The outermost of the three tracebacks (real line, 2026-09-08 21:50) ----
    # The relay logged 「OK-WW 报错中继还没有翻译…任务 TaskExecutor，异常 Exception，
    # 原文「📅 Daily Task exception stopped」」. That wrapper only says the daily list
    # stopped; the reason is in the innermost traceback. Leaving it untranslated meant
    # the notification could only say it did not recognise the error.
    from ark_relay.features.verify.collector_okww import _okww_say

    _said = _okww_say("TaskExecutor", "📅 Daily Task exception stopped", "Exception")
    check("这条真实日志行翻得出来", "还不认识" in _said, False)
    check("说的是日常清单停了", "日常清单整个停了" in _said, True)
    check("指到真正的原因在哪", "真正的原因" in _said, True)
    check("不许抢掉更靠谱的那条：回放里 09-01 那条仍报「等一个画面没等到」",
          "Daily Task exception stopped" in str(__import__("ark_relay.features.verify.collector_okww", fromlist=["x"])._OKWW_MSG_ZH), False)
    check("不认识的错还是照旧说不认识",
          "还不认识" in _okww_say("TaskExecutor", "完全没见过的错", "WeirdError"), True)
    check("v3.7.14-beta.2 zh_CN 请在大世界并在队伍中开始 翻得出人话",
          _okww_say("TaskExecutor", "请在大世界并在队伍中开始!", ""),
          "任务执行：开跑时游戏不在大世界、或者没有出战队伍，OK-WW 不肯开工")
    _garden_then_farm = (
        "2026-11-02 10:07:16,454 INFO TaskExecutor GardenTask:info_set current task garden_new_stage\n"
        "2026-11-02 10:33:59,555 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本领奖：这一圈打完没看到结晶，不领就会被上游按 ESC 退本，停下。\n"
        "2026-11-02 10:33:59,603 ERROR TaskExecutor DailyTask:run_task_by_class <class 'src.task.FarmEchoTask.FarmEchoTask'> Traceback (most recent call last):\n"
        "  File \"task.py\", line 1118, in run_task_by_class\n"
        "    task.run()\n"
        "ark_overrides.ArkStopped: 周本领奖：这一圈打完没看到结晶，不领就会被上游按 ESC 退本，停下。\n"
    )
    check("周常乐园跑完后周本抛 run_task_by_class 不误算到周常乐园头上",
          _cok._okww_error(_garden_then_farm),
          "周本领奖：这一圈打完没看到结晶，不领就会被上游按 ESC 退本，停下。")

    print("\n[「游戏即将重启」弹窗：看客户端到底换没换文件（2026-09-12 09:21 只是反作弊刷新）]")
    import os as _os
    from ark_relay.features.verify import collector_okww as _co
    g = tmpdir()
    root = g / "Wuthering Waves Game"
    (root / "Client" / "Binaries" / "Win64" / "AntiCheatExpert").mkdir(parents=True)
    (root / "Client" / "Saved").mkdir(parents=True)
    (root / "Client" / "Content").mkdir(parents=True)
    exe = root / "Client" / "Binaries" / "Win64" / "Client-Win64-Shipping.exe"
    exe.write_text("x")
    _os.utime(exe, (0, 1_700_000_000))          # installed long ago, not written today
    ok = g / "okww"
    cfgd = ok / "data" / "apps" / "ok-ww" / "working" / "configs"
    cfgd.mkdir(parents=True)
    (cfgd / "devices.json").write_text('{"path": "' + str(exe).replace("\\", "\\\\") + '"}', encoding="utf-8")
    _os.environ["ARK_OKWW_DIR"] = str(ok)
    check("从 devices.json 找到游戏根目录", _co.wuwa_game_root(Path("x")), root)
    import time as _time
    now = _time.time()
    log = d / "restart.log"
    t0 = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(now - 120))
    t1 = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(now + 60))
    log.write_text(f"{t0},004 INFO MainThread ok:ok-script init\n{t1},647 INFO TaskExecutor DailyTask:游戏更新成功, 游戏即将重启\n", encoding="utf-8")
    (root / "Client" / "Binaries" / "Win64" / "AntiCheatExpert" / "pld.dat").write_text("ace")
    (root / "Client" / "Saved" / "LocalStorage.db").write_text("save")
    r = _co.parse_okww_log(log)
    check("弹窗记下了", r.get("okww_restart_dialog"), True)
    # The paths are as the OS spells them: _client_change reports str() of the path
    # relative to the game root, 「AntiCheatExpert\pld.dat」 on the machine (the user's
    # own words, 2026-09-12, in its docstring) and "/" on the Mac. Both checks failed
    # on the Windows CI runner (run 37519943859) against the "/" spelling.
    check("只有反作弊和存档变了 → 反作弊组件，带文件名", (r.get("okww_client_change"), r.get("okww_client_files")),
          ("anticheat", [str(Path("AntiCheatExpert") / "pld.dat")]))
    (root / "Client" / "Content" / "Paks.pak").write_text("new pak")
    r2 = _co.parse_okww_log(log)
    check("pak 变了 → 客户端更新，列出文件", (r2.get("okww_client_change"), r2.get("okww_client_files")),
          ("patch", [str(Path("Client") / "Content" / "Paks.pak")]))
    (root / "Client" / "Content" / "Paks.pak").unlink(); (root / "Client" / "Binaries" / "Win64" / "AntiCheatExpert" / "pld.dat").unlink()
    check("什么都没变 → 没有变", _co.parse_okww_log(log).get("okww_client_change"), "none")
    del _os.environ["ARK_OKWW_DIR"]


def _part_okww_exit_race():
    """AUTO-MAS 说「OK-WW 在完成任务前退出」，但 OK-WW 自己写了 Daily Task Completed → 这趟是做完的。

2026-09-06 早班：09:36:18 Completed，09:36:24 进程退出，AUTO-MAS 只看见进程没了，
记成失败；重试那趟无事可做记成 ✅、五行全是「—」。日报因此 ❌ + 空 ✅，用户问是不是代码改坏了。
以证据（OK-WW 自己的日志）为准。

    Formerly test_okww_exit_race.py.
    """
    import json
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

    root = tmpdir()
    d = root / "2026-09-06" / "wuwa"; d.mkdir(parents=True)
    (d / "OK-WW-05-20-17.json").write_text(json.dumps({"general_result": "OK-WW 在完成任务前退出"}, ensure_ascii=False), encoding="utf-8")
    (d / "OK-WW-05-20-17.log").write_text(
        "2026-09-06 09:20:48,000 INFO TacetTask: start\n"
        "2026-09-06 09:36:18,776 INFO TaskExecutor DailyTask:Daily Task Completed\n"
        "2026-09-06 09:36:24,007 INFO MainThread handler:handler stopping global\n", encoding="utf-8")
    rec = collector.parse_record(d / "OK-WW-05-20-17.json", root)
    if rec is None or not rec.ok:
        fails.append(f"日志里有 Completed 却仍判失败：{rec and rec.failed_tasks}")
    if rec is not None and not rec.raw.get("okww_exit_race"):
        fails.append("没有标记这是 AUTO-MAS 的时序误判")

    # 真没做完的（日志里没有 Completed）照样是失败
    (d / "OK-WW-05-50-00.json").write_text(json.dumps({"general_result": "OK-WW 在完成任务前退出"}, ensure_ascii=False), encoding="utf-8")
    (d / "OK-WW-05-50-00.log").write_text("2026-09-06 09:50:00,000 INFO TacetTask: start\n", encoding="utf-8")
    rec2 = collector.parse_record(d / "OK-WW-05-50-00.json", root)
    if rec2 is None or rec2.ok:
        fails.append("没有 Completed 的退出应仍判失败")

    # 2026-11-03 ledger #135: OK-WW v3.7.14-beta.2 logged zh_CN completion then -e closed
    # the hwnd; AUTO-MAS saw connected:0 and recorded disconnect. The start-of-round
    # 4C farm prompt must not be mistaken for end-of-round completion.
    d1103 = root / "2026-11-03" / "5e401e6c"; d1103.mkdir(parents=True)
    (d1103 / "0.log").write_text(
        "2026-11-03 09:36:14,193 INFO TaskExecutor DailyTask:每日任务已完成，开始传送并刷取4C声骸\n"
        "2026-11-03 09:37:56,826 INFO TaskExecutor TacetTask:info_set current_stamina 240\n"
        "2026-11-03 09:38:08,164 INFO TaskExecutor TacetTask:当前体力大于等于双倍, 使用双倍体力\n"
        "2026-11-03 09:44:27,058 INFO TaskExecutor TacetTask:体力已用尽\n"
        "2026-11-03 09:44:50,415 INFO TaskExecutor DailyTask:每日任务已完成\n", encoding="utf-8")
    rec3 = collector.parse_db_record(
        ("5e401e6c", "2026-11-03T05:35:08", "2026-11-03", "wuwa", "OK-WW",
         "OK-WW 未连接游戏客户端", "{}", "2026-11-03/5e401e6c/0.log"),
        root)
    if rec3 is None or not rec3.ok or not rec3.raw.get("okww_exit_race"):
        fails.append(f"2026-11-03 每日任务已完成 + 未连接游戏客户端 应判成功：{rec3}")
    refreshed = collector.refresh_raw(
        {"run_id": "2026-11-03/wuwa/OK-WW-05-35-08", "script": "OK-WW", "ok": False,
         "failed_tasks": ["OK-WW 未连接游戏客户端"],
         "raw": {"general_result": "OK-WW 未连接游戏客户端", "automas_record_id": "5e401e6c"}},
        root, None)
    if not refreshed.get("ok") or refreshed.get("raw", {}).get("okww_stopped") != "体力不够再开一局":
        fails.append(f"refresh_raw 没按 automas_record_id 恢复成功：{refreshed}")

    # A run with only the start-of-round 4C prompt that later raised in the weekly boss stays failed.
    d1103_fail = root / "2026-11-03" / "160a2a9f"; d1103_fail.mkdir(parents=True)
    (d1103_fail / "0.log").write_text(
        "2026-11-03 09:18:10,000 INFO TaskExecutor DailyTask:每日任务已完成，开始传送并刷取4C声骸\n"
        "2026-11-03 09:25:07,521 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本领奖：这一圈打完没看到结晶，不领就会被上游按 ESC 退本，停下。\n"
        "2026-11-03 09:25:08,100 ERROR TaskExecutor TaskExecutor:📅 每日任务异常停止 Traceback (most recent call last):\n"
        "ark_overrides.ArkStopped: 周本领奖\n", encoding="utf-8")
    rec4 = collector.parse_db_record(
        ("160a2a9f", "2026-11-03T05:17:16", "2026-11-03", "wuwa", "OK-WW",
         "OK-WW 未连接游戏客户端", "{}", "2026-11-03/160a2a9f/0.log"),
        root)
    if rec4 is None or rec4.ok:
        fails.append(f"只有开头刷 4C 提示、中途报错的不能判成功：{rec4}")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_okww_failed_reason():
    """A run the overlay ended as failed is pushed with its reason once, without the OCR dump.

Audit 2026-10-13 item 14, two real lines of 2026-10-12 (machine-okww-logs):
* 09:52 the overlay's reason started with the step 「周本领奖：」, but the prefix
  check looked for 「周本：」 only, so the pushed reason named the step twice;
* 11:45 the reason ended in 「整屏读到 [0_1.00, 41/240_1.00, …]」, a whole screen of
  OCR fragments, and that went into the alert and the verdict's detail. It stays in
  the log only.

    Formerly test_okww_failed_reason.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww as co, outcome


    L1 = ("2026-10-12 09:52:20,812 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本领奖：这一步没做成 "
          "WaitFailedException()，停下不乱点 Traceback (most recent call last):\n"
          "ark_relay.ArkStopped\n")
    L2 = ("2026-10-12 11:45:02,507 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本领奖：点了确认后没等到"
          "结算页（没有「退出副本」），停下不按 ESC。整屏读到 [0_1.00, 41/240_1.00, 🌟_0.53, 补充结晶波片_1.00, "
          "确认_1.00] Traceback (most recent call last):\n"
          "ark_relay.ArkStopped\n")
    WEEKLY = "2026-10-12 11:40:00,000 INFO TaskExecutor FarmEchoTask:Teleport to Boss Weekly Challenge\n"

    print("[the step is named once]")
    check("09:52", co._okww_error(L1), "周本领奖：这一步没做成 WaitFailedException()，停下不乱点")
    plain = ("2026-10-12 09:52:20,812 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：没进本 "
             "Traceback (most recent call last):\nx.ArkStopped\n")
    check("a reason without the step still gets it", co._okww_error(plain), "周本：没进本")

    print("\n[the OCR dump stays out of the pushed reason]")
    check("11:45 okww_error", co._okww_error(L2), "周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC")
    details = [c.detail for c in outcome.okww_checks(WEEKLY + L2, expect_nest=False) if not c.ok]
    check("no check detail carries it", any("整屏读到" in d for d in details), False)
    check("the weekly item still says why",
          any(d.startswith("周本领奖：点了确认后没等到结算页") for d in details), True)
    check("without_screen_dump on a plain reason is the identity",
          outcome.without_screen_dump("周本：没进本"), "周本：没进本")

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_i18n():
    """OK-WW's zh_CN log lines are turned back into English from the machine's own catalogs (okww_i18n).

Ledger #136 (2026-11-04): ok-script's 「当前游戏或模拟器不支持选择的截图方式!」 reached the group as an
unknown error because only a hand-written pair would have turned it back. Checked here:
* the .po and .ts readers (multi-line strings, escapes, obsolete / plural / unfinished entries);
* the tables: exact whole messages, concatenated prefixes, placeholders ({}, {name}, %s, %1),
  ambiguous translations dropped;
* normalize only touches a whole OK-WW log message: our own Chinese lines, OCR text and a short
  catalog word inside a longer message stay as they were, English logs are returned unchanged;
* with the real catalogs (OK-WW v3.7.19 ok.po, ok-script 3.0.3 zh_CN.ts, fixtures/okww-i18n) the
  #136 line and full upstream messages come back in English, and outcome.normalize_okww_log still
  applies the hand-written pairs for what the catalogs do not hold;
* a changed catalog is read again.

    Formerly test_okww_i18n.py.
    """
    import os
    import shutil
    import time


    TMP = tmpdir()
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    from ark_relay.features.verify import okww_i18n as I
    from ark_relay.features.verify import outcome


    def root_with(po_text=None, ts_text=None, name="r"):
        root = TMP / name
        if po_text is not None:
            p = root / I.PO_REL
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(po_text, encoding="utf-8")
        if ts_text is not None:
            t = root / I.TS_REL
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(ts_text, encoding="utf-8")
        root.mkdir(parents=True, exist_ok=True)
        return root


    def line(msg, logger="NightmareNestTask", level="INFO"):
        return f"2026-11-05 09:21:32,123 {level} TaskExecutor {logger}:{msg}"


    print("[readers]")
    PO = '''msgid ""
msgstr ""
"Language: zh_CN\\n"

msgid "Daily Task Completed"
msgstr "每日任务已完成"

msgid "enter combat "
msgstr "进入战斗，控物状态："

msgid ""
"teleport_to_boss "
"prepared as {}"
msgstr "首领传送准备结果：{}"

msgid "found {name} at {pos}"
msgstr "在{pos}找到{name}"

msgid "skip %s of %s"
msgstr "跳过%s/%s"

msgid "Start"
msgstr "开始"

msgid "Begin"
msgstr "开始"

msgid "quote \\"x\\""
msgstr "引号「\\"x\\"」"

#~ msgid "Old line"
#~ msgstr "旧的一句"

msgid "one apple"
msgid_plural "{} apples"
msgstr[0] "{}个苹果"

msgid "Untranslated"
msgstr ""
'''
    pairs = dict(I.po_pairs(PO))
    check("multi-line msgid joined", pairs.get("teleport_to_boss prepared as {}"), "首领传送准备结果：{}")
    check("escaped quotes read", pairs.get('quote "x"'), '引号「"x"」')
    check("obsolete entry left out", "Old line" in pairs, False)
    check("plural entry left out", "one apple" in pairs, False)
    check("empty translation left out", "Untranslated" in pairs, False)
    check("header entry left out", "" in pairs, False)
    TS = '''<?xml version="1.0" encoding="utf-8"?><TS version="2.1" language="zh_CN"><context><name>app</name>
<message><source>Selected capture method is not supported by the game or your system!</source><translation>当前游戏或模拟器不支持选择的截图方式!</translation></message>
<message><source>Game window is not connected, %1</source><translation>游戏窗口未连接，%1</translation></message>
<message><source>Half done</source><translation type="unfinished">做了一半</translation></message>
</context></TS>'''
    tp = dict(I.ts_pairs(TS))
    check("ts translation read", tp.get("Selected capture method is not supported by the game or your system!"), "当前游戏或模拟器不支持选择的截图方式!")
    check("ts unfinished left out", "Half done" in tp, False)
    check("broken ts: nothing, no crash", I.ts_pairs("<TS><message>"), [])

    print("[tables]")
    R = root_with(PO, TS, "small")
    t = I.tables(R)
    check("exact", t.message("每日任务已完成"), "Daily Task Completed")
    check("concatenated prefix (source ends in a space)", t.message("进入战斗，控物状态：True"), "enter combat True")
    check("placeholder", t.message("首领传送准备结果：True"), "teleport_to_boss prepared as True")
    check("named placeholders reordered", t.message("在(10, 20)找到残象"), "found 残象 at (10, 20)")
    check("printf placeholders", t.message("跳过3/5"), "skip 3 of 5")
    check("Qt %1 placeholder", t.message("游戏窗口未连接，请重开"), "Game window is not connected, 请重开")
    check("ambiguous translation (Start/Begin) dropped", t.message("开始"), None)
    check("not a catalog message", t.message("指定点位都已打满，跳过"), None)

    print("[normalize: whole messages only]")
    ours = "\n".join([
        line("nightmare nest: 只刷 ['落渊南丘']（设置来自母本）"),
        line("left_click 已击败残象：0/41 (1729, 347) after_sleep 2"),
        line("每日任务已完成还有别的字"),
        line("指定点位都已打满，跳过"),
    ]) + "\n"
    check("our own lines, OCR text and a catalog word inside a longer message stay", I.normalize(ours, R), ours)
    eng = line("Daily Task Completed", "DailyTask") + "\n" + line("enter combat True") + "\n"
    check("an English log comes back as the same object", I.normalize(eng, R) is eng, True)
    mixed = line("每日任务已完成", "DailyTask") + "\r\n" + line("指定点位都已打满，跳过") + "\n"
    check("a translated line turned back, line ending kept, other line untouched",
          I.normalize(mixed, R), line("Daily Task Completed", "DailyTask") + "\r\n" + line("指定点位都已打满，跳过") + "\n")
    check("not an OK-WW log line: untouched", I.normalize("每日任务已完成\n", R), "每日任务已完成\n")
    check("no catalogs at all: unchanged", I.normalize(mixed, TMP / "nowhere"), mixed)

    print("[the real catalogs: OK-WW v3.7.19 ok.po + ok-script 3.0.3 zh_CN.ts]")
    real = TMP / "real"
    (real / I.PO_REL).parent.mkdir(parents=True)
    (real / I.TS_REL).parent.mkdir(parents=True)
    shutil.copy(HERE / "fixtures" / "okww-i18n" / "ok-v3.7.19.po", real / I.PO_REL)
    shutil.copy(HERE / "fixtures" / "okww-i18n" / "okscript-3.0.3-zh_CN.ts", real / I.TS_REL)
    rt = I.tables(real)
    check("hundreds of whole messages read", len(rt.exact) > 1000, True)
    check("ledger #136: the framework's line from zh_CN.ts",
          I.normalize(line("当前游戏或模拟器不支持选择的截图方式!", "start_controller", "ERROR"), real),
          line("Selected capture method is not supported by the game or your system!", "start_controller", "ERROR"))
    check("a full upstream message the hand table only had half of",
          I.normalize(line("每日任务已完成，开始传送并刷取4C声骸", "DailyTask"), real),
          line("Daily task completed, start teleport to farm 4C echo", "DailyTask"))
    check("captured echo, full message",
          I.normalize(line("战斗中已吸收声骸，跳过搜索。"), real), line("Captured echo during combat, skipping search."))

    print("[outcome.normalize_okww_log: catalogs first, then the hand-written pairs]")
    os.environ["ARK_OKWW_DIR"] = str(real)
    check("catalog line", outcome.normalize_okww_log(line("战斗中已吸收声骸，跳过搜索。")),
          line("Captured echo during combat, skipping search."))
    check("a string only the hand-written pairs know still turns back",
          outcome.normalize_okww_log(line("等待游戏启动错误", "ok", "ERROR")), line("waiting for game to start error", "ok", "ERROR"))
    os.environ["ARK_OKWW_DIR"] = str(TMP / "nowhere")
    check("no catalogs on the machine: the hand-written pairs alone, as before",
          outcome.normalize_okww_log(line("战斗中已吸收声骸")), line("Captured echo during combat"))

    print("[a changed catalog is read again]")
    R2 = root_with('msgid "Alpha one"\nmsgstr "第一句"\n', None, "changing")
    check("before", I.tables(R2).message("第一句"), "Alpha one")
    time.sleep(0.01)
    (R2 / I.PO_REL).write_text('msgid "Alpha two"\nmsgstr "第一句"\n\nmsgid "Beta"\nmsgstr "第二句"\n', encoding="utf-8")
    os.utime(R2 / I.PO_REL, (time.time() + 5, time.time() + 5))
    check("after the upgrade: the new source", I.tables(R2).message("第一句"), "Alpha two")
    check("after the upgrade: the new string", I.tables(R2).message("第二句"), "Beta")

    print("all checks passed" if not fails else f"FAILED: {fails}")


def _part_okww_landed():
    """scripts/windows/okww-landed.py judges the OK-WW install the right way round.

Since 2026-09-09 the relay's OK-WW changes live in ok_tasks/ark_overrides.py and no
upstream file is edited (okww_overlay.py). The checker still expected 4 changed
spots in FarmEchoTask.py, so a clean install showed a red cross, and it passed
DailyTask.py / NightmareNestTask.py whatever their content (want=None). It also
never looked at the overlay itself. The script runs on import (it reads the
machine's .env), so its pure helpers are pulled out of the AST and run here.

    Formerly test_okww_landed.py.
    """
    import ast

    SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "windows" / "okww-landed.py"


    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    wanted = {"UPSTREAM_TASKS", "upstream_untouched", "overlay_problems"}
    nodes = [n for n in tree.body
             if (isinstance(n, ast.FunctionDef) and n.name in wanted)
             or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in wanted for t in n.targets))]
    ns: dict = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT), "exec"), ns)
    check("the helpers exist in the script", sorted(k for k in wanted if k in ns), sorted(wanted))
    check("no 'None means pass' left in the script", "want is None" in src, False)
    if fails:
        print("FAILED: " + ", ".join(fails))
        sys.exit(1)

    print("[upstream files: 0 changed spots, every one of them]")
    check("all three task files are checked",
          ns["UPSTREAM_TASKS"], ("FarmEchoTask.py", "DailyTask.py", "NightmareNestTask.py"))
    check("a pristine file passes", ns["upstream_untouched"](0), True)
    check("4 changed spots (the old patch count) fails", ns["upstream_untouched"](4), False)
    check("1 changed spot fails", ns["upstream_untouched"](1), False)
    loop = next(n for n in tree.body if isinstance(n, ast.For)
                and isinstance(n.iter, ast.Name) and n.iter.id == "UPSTREAM_TASKS")
    check("the file loop judges with upstream_untouched",
          any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "upstream_untouched" for c in ast.walk(loop)), True)

    print("[the overlay itself]")
    good = {"applied": ["DailyTask.run"], "skipped": [], "error": None}
    check("installed, same copy, bound: nothing to say", ns["overlay_problems"]("X", "X", good), [])
    check("not installed", len(ns["overlay_problems"](None, "X", good)), 1)
    check("an older copy", len(ns["overlay_problems"]("old", "X", good)), 1)
    check("no report yet", len(ns["overlay_problems"]("X", "X", {})), 1)
    check("report error", len(ns["overlay_problems"]("X", "X", dict(good, error="boom"))), 1)
    check("an override skipped",
          len(ns["overlay_problems"]("X", "X", dict(good, skipped=[{"what": "NightmareNestTask.find_nest"}]))), 1)
    check("nothing applied", len(ns["overlay_problems"]("X", "X", dict(good, applied=[]))), 1)
    check("the script runs the overlay check at top level",
          any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "overlay_problems"
              for n in tree.body if not isinstance(n, ast.FunctionDef) for c in ast.walk(n)), True)

    print("[the no-stamina flag: the override's own fixed path]")
    # 2026-10-13 audit: the checker built the flag path from the data folder, so it could
    # read a different file from the one the OK-WW override obeys.
    check("no flag path built from the data folder", "no-stamina-farm.flag" in src, False)
    check("reads config.NO_STAMINA_FARM_FLAG",
          any(isinstance(n, ast.ImportFrom) and n.module == "ark_relay.core.config"
              and any(a.name == "NO_STAMINA_FARM_FLAG" for a in n.names) for n in ast.walk(tree)), True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import config
    overrides = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "okww_patch" / "okww_files"
                 / "ark_overrides.tasks.py").read_text(encoding="utf-8")
    check("the same path the override obeys", f'NO_STAMINA_FLAG = r"{config.NO_STAMINA_FARM_FLAG}"' in overrides, True)


def _part_okww_names_not_numbers():
    """日报里鸣潮刷的本和产出必须是人话，不许只有序号或一句笼统的类别。

用户 2026-09-06 看到「刷 无音区 #2 ×2 / 产出 声骸与角色突破材料」：
「井号二是什么玩意儿？产出也是一坨屎」。08-26 凝素领域那一支已经改成写名字，
无音区这一支当时漏了。这条测试把两支一起钉死，以后再加第三种本也得过它。

    Formerly test_okww_names_not_numbers.py.
    """
    import pathlib
    import re

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector, wuwa_tacet
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

    BAD = re.compile(r"#\s*\d|声骸与角色突破材料|武器突破材料$|副本奖励")

    def run(log_text):
        p = tmpdir() / "x.log"
        p.write_text(log_text, encoding="utf-8")
        return collector.parse_okww_log(p)

    # 无音区：已登记的序号要写名字和两个套装
    raw = run("2026-09-05 09:20:00,000 INFO TacetTask: start\n"
              "2026-09-05 09:20:01,000 INFO info_set Teleport to Tacet Suppression 1\n"
              "2026-09-05 09:21:00,000 INFO 使用双倍体力\n")
    farm, rew = raw.get("okww_farm", ""), raw.get("okww_farm_reward", "")
    if "玄幽东岳" not in farm:
        fails.append(f"无音区 2 号应写玄幽东岳，得到 {farm!r}")
    if not ("羽落空尘之歌" in rew and "清邪荡煞之心" in rew):
        fails.append(f"产出应写两个套装名，得到 {rew!r}")
    for s in (farm, rew):
        if BAD.search(s):
            fails.append(f"还是笼统写法：{s!r}")

    # From WuWa 3.7 (2026-09-30) the list moved down by 2: read an index against the list of the log's own day (F2 read on the machine 09-30)
    for got, want in ((wuwa_tacet.label(2), "无音区·烬心域"), (wuwa_tacet.label(2, "2026-09-30"), "无音区·烬心域"),
                      (wuwa_tacet.label(2, "2026-09-29"), "无音区·玄幽东岳"), (wuwa_tacet.label(4), "无音区·玄幽东岳")):
        if got != want:
            fails.append(f"分版本查表：应为 {want}，得到 {got!r}")
    raw_new = run("2026-10-01 09:20:00,000 INFO TacetTask: start\n"
                  "2026-10-01 09:20:01,000 INFO info_set Teleport to Tacet Suppression 1\n")
    if "烬心域" not in raw_new.get("okww_farm", ""):
        fails.append(f"3.7 之后的日志 2 号应写烬心域，得到 {raw_new.get('okww_farm')!r}")

    # 没登记的序号：明说没登记，不许编名字
    farm2, rew2 = wuwa_tacet.label(17), wuwa_tacet.reward(17)
    if "没登记" not in farm2 or "没登记" not in rew2:
        fails.append(f"未登记序号要明说：{farm2!r} / {rew2!r}")

    # 凝素领域那一支同样不许退化回序号
    raw3 = run("2026-09-05 09:20:00,000 INFO ForgeryTask: start\n"
               "2026-09-05 09:20:01,000 INFO info_set Teleport to Forgery Challenge 0\n"
               "2026-09-05 09:21:00,000 INFO 使用双倍体力\n")
    if "陨翼云渊" not in raw3.get("okww_farm", ""):
        fails.append(f"凝素领域应写副本名，得到 {raw3.get('okww_farm')!r}")

    # 手机页能选到的每一个序号，报告都得叫得出名字。
    # 2026-09-08：手机页 FORGE 有 5 项、报告的表只有 4 条，选第 5 个就写成「凝素领域·#5」。
    js = (pathlib.Path(__file__).resolve().parents[2] / "web" / "schema.js").read_text(encoding="utf-8")   # TACET/FORGE 在 schema.js（app.js 2026-09-18 拆分）
    for idx, (_, sets) in wuwa_tacet.TACET.items():
        if f'[["{sets[0]}", "{sets[1]}"], {idx}]' not in js:
            fails.append(f"手机页 TACET 里第 {idx} 项和 wuwa_tacet 对不上")

    from ark_relay.core import wuwa_forgery
    import re as _re
    for m in _re.finditer(r'\["(\d+) · [^"]*（([^）"]+)）", (\d+)\]', js):
        idx = int(m.group(3))
        if wuwa_forgery.FORGERY.get(idx, ("",))[0] != m.group(2):
            fails.append(f"手机页 FORGE 第 {idx} 项（{m.group(2)}）和 wuwa_forgery 对不上")

    # 手机页给的每个序号都必须查得到名字，不许退化成「第 N 个」
    for m in _re.finditer(r'\["\d+ · [^"]*", (\d+)\]', js):
        if "没登记" in wuwa_forgery.label(int(m.group(1))):
            fails.append(f"手机页能选第 {m.group(1)} 个凝素领域，但对照表里没有它")

    # 明日安排那一支也不许退化成序号（plan.py 以前自己抄了一份只有 4 条的表）
    for i in (1, 5, 15):
        line = f"体力刷 {wuwa_forgery.label(i)}，出 {wuwa_forgery.reward(i)}"
        if "#" in line or "没登记" in line:
            fails.append(f"明日安排第 {i} 个凝素领域退化成序号：{line}")

    # All 20 forgery instances (in-game list re-read 2026-09-30; upstream ForgeryTask
    # structure [5, 5, 5, 5]): every index names its instance, and every region lists
    # the five weapon types in the same order.
    if sorted(wuwa_forgery.FORGERY) != list(range(1, 21)):
        fails.append(f"凝素领域对照表应是 1..20，得到 {sorted(wuwa_forgery.FORGERY)}")
    for i in range(1, 21):
        if "没登记" in wuwa_forgery.label(i):
            fails.append(f"凝素领域第 {i} 个没有名字")
    _order = ["迅刀", "音感仪", "长刃", "臂铠", "佩枪"]
    for start in (1, 6, 11, 16):
        rows = [wuwa_forgery.FORGERY.get(start + k) for k in range(5)]
        if None in rows or [r[1] for r in rows] != _order or len({r[2] for r in rows}) != 1:
            fails.append(f"凝素领域第 {start}..{start + 4} 个不是同一地区的 迅刀/音感仪/长刃/臂铠/佩枪：{rows}")
    if wuwa_forgery.label(16) != "凝素领域·熔毁废都（迅刀）":
        fails.append(f"第 16 个：{wuwa_forgery.label(16)}")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_okww_python_filter():
    """Which pythons count as OK-WW's own, and what an unreadable list means.

The filter (preupdate_okww._OKWW_PY) decides what game_alive reports, what
stop_okww_script stops, what _okww_left kills by number and what the full stop
takes down. It matched a bare '*ok-ww*', and PowerShell's -like ignores case, so
any python with "OK-WW" among its arguments was taken for OK-WW:
`dispatch_guard.py start OK-WW` matched itself (scripts/windows/dispatch_guard.py).
It now matches OK-WW's install folder. The -like patterns are run here with
fnmatch on lowered strings, which is what -like does for '*' and '?'.

okww_python_pids read a failed query (empty stdout) as "none running"; a nonzero
exit, or empty output with an error on stderr, is now None.

    Formerly test_okww_python_filter.py.
    """
    import fnmatch
    import re

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.preupdate import preupdate_okww as P


    def is_okww(cmdline: str, ps: str = P._OKWW_PY) -> bool:
        """Does the Where-Object of `ps` keep a process with this command line?"""
        pats = re.findall(r"-like\s+'([^']*)'", ps)
        return any(fnmatch.fnmatchcase(cmdline.lower(), p.lower()) for p in pats)


    print("[the filter: OK-WW's install folder, nothing else]")
    # OK-WW's real line, ok-script.2026-10-12.log 15:23:30, run by echofarm._launch's pythonw.
    REAL = r'"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe" D:\ark\okww\data\apps\ok-ww\working\main.py -t 2 -e'
    check("OK-WW as the echo farm starts it", is_okww(REAL), True)
    check("OK-WW's own python running -m ok",
          is_okww(r'"D:\ark\okww\data\apps\ok-ww\python\python.exe" -m ok run_task FarmEchoTask -e'), True)
    check("the dispatch gate asked about OK-WW is not OK-WW",
          is_okww(r'"C:\Python314\python.exe" C:\ark\scripts\dispatch_guard.py start OK-WW'), False)
    check("...nor a python that only names it in lower case",
          is_okww(r'"C:\Python314\python.exe" C:\tools\note.py ok-ww'), False)
    check("...nor the relay itself",
          is_okww(r'"C:\ark-relay\python\pythonservice.exe" C:\ark-relay\service.py'), False)
    estop = (Path(__file__).resolve().parents[2] / "scripts" / "mac" / "estop.sh").read_text(encoding="utf-8")
    check("the emergency stop's python filter is the folder too",
          re.findall(r'CommandLine -like "([^"]*)"', estop), [r"*\ok-ww\*"])

    print("[an unreadable list is None (unknown), never [] (none left)]")
    # 2026-10-13 review: pwsh started, the query failed, stdout was empty - and empty
    # read as "no OK-WW running", so the relaunch went ahead and game_alive said clean.


    class Done:
        def __init__(self, rc, out=b"", err=b""):
            self.returncode, self.stdout, self.stderr = rc, out, err


    real_py = P._okww_py
    cases = [
        ("nothing running: empty output, exit 0, no error", Done(0), []),
        ("one running", Done(0, b'{"ProcessId":4242}'), [4242]),
        ("two running", Done(0, b'[{"ProcessId":1},{"ProcessId":2}]'), [1, 2]),
        ("the query failed: exit 1, empty output", Done(1, b"", b"Get-CimInstance : Invalid class"), None),
        ("an error on stderr with empty output, exit 0", Done(0, b"", b"Get-CimInstance : Access denied"), None),
        ("a nonzero exit even with output", Done(1, b'{"ProcessId":4242}'), None),
        ("pwsh did not run at all", None, None),
    ]
    try:
        for label, done, want in cases:
            P._okww_py = lambda tail, timeout=None, d=done: d
            check(label, P.okww_python_pids(), want)
    finally:
        P._okww_py = real_py


def _part_okww_quiesce_order():
    """Stopping OK-WW has to kill the script before the game.

2026-09-09: the user stopped the echo farm from his phone, the relay reported it
stopped and put the config back - and 鸣潮 was still on screen. Two reasons, both
here: the game was killed first, so OK-WW was still alive to start it again; and the
process filter only matched `python.exe`, while the echo farm is deliberately launched
with `pythonw.exe` so no console window covers the game.

    Formerly test_okww_quiesce_order.py.
    """
    import subprocess

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.preupdate import preupdate_okww as pk


    calls = []
    real_run = subprocess.run


    class Done:
        returncode = 0
        stdout = b""
        stderr = b""


    subprocess.run = lambda *a, **k: (calls.append(list(a[0]) if a else []), Done())[1]
    try:
        pk._okww_quiesce(sleep=lambda _s: None)
    finally:
        subprocess.run = real_run

    flat = ["\n".join(str(x) for x in c) for c in calls]
    script_at = next((i for i, c in enumerate(flat) if "ok-ww" in c and "CimInstance" in c), -1)
    game_at = next((i for i, c in enumerate(flat) if "Client-Win64-Shipping.exe" in c), -1)

    print("[顺序：先停脚本，再关游戏]")
    check("停脚本这步在", script_at >= 0)
    check("关游戏这步在", game_at >= 0)
    check("脚本排在游戏前面", script_at >= 0 and game_at >= 0 and script_at < game_at)

    print("[进程名：pythonw 也要算，刷声骸用的就是它]")
    check("匹配 pythonw.exe", any("pythonw.exe" in c for c in flat))
    check("匹配 python.exe", any("python.exe" in c for c in flat))

    print("[游戏那几个进程一个都不能漏]")
    for name in ("ok-ww.exe", "Wuthering Waves.exe", "Client-Win64-Shipping.exe", "KRSDKExternal.exe"):
        check(f"关掉 {name}", any(name in c for c in flat))

    print("[鸣潮启动器 launcher.exe：只按完整路径停，别处同名的不动（2026-09-30）]")
    import json

    PROCS = [{"ProcessId": 4242, "ExecutablePath": "D:\\Wuthering Waves\\launcher.exe"},
             {"ProcessId": 5151, "ExecutablePath": "C:\\Program Files\\Other Game\\launcher.exe"}]


    class Listed(Done):
        stdout = json.dumps(PROCS).encode()


    calls.clear()


    def fake_run(*a, **k):
        cmd = list(a[0]) if a else []
        calls.append(cmd)
        return Listed() if any("Name='launcher.exe'" in str(x) for x in cmd) else Done()


    subprocess.run = fake_run
    try:
        pk._okww_quiesce(sleep=lambda _s: None)
    finally:
        subprocess.run = real_run
    kills = [c for c in calls if c[:1] == ["taskkill"]]
    check("路径是 \\Wuthering Waves\\launcher.exe 的那个被停（按 PID）",
          ["taskkill", "/F", "/PID", "4242"] in kills)
    check("别处的 launcher.exe 不动", any("5151" in c for c in kills), False)
    check("从不按进程名 launcher.exe 去杀", any("launcher.exe" in c for c in kills), False)
    check("列进程只查 launcher.exe", sum(1 for c in calls if any("Name='launcher.exe'" in str(x) for x in c)), 1)
    check("只有一个时 PowerShell 给的是对象不是数组，也认", (
        lambda: (setattr(Listed, "stdout", json.dumps(PROCS[0]).encode()),
                 setattr(subprocess, "run", fake_run),
                 pk._stop_wuwa_launcher())[-1])(), [4242])
    subprocess.run = real_run
    check("路径大小写与斜杠不影响", pk._is_wuwa_launcher("d:/wuthering waves/LAUNCHER.EXE"), True)
    check("游戏目录里的不算", pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher.exe"), False)
    check("读不到进程列表 → 什么都不停", (
        lambda: (setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no pwsh"))),
                 pk._stop_wuwa_launcher())[-1])(), [])
    subprocess.run = real_run

    print("[a caller's time budget reaches every PowerShell call (echofarm.stop_okww, 2026-10-13)]")
    _pwsh_timeouts = []


    def _rec(*a, **k):
        if a and "-Command" in a[0]:
            _pwsh_timeouts.append(k.get("timeout"))
        return Done()


    subprocess.run = _rec
    try:
        try:
            pk._okww_quiesce(sleep=lambda _s: None, left=lambda: 3.0)
        except TypeError as e:      # an older signature
            _pwsh_timeouts.append(f"crashed: {type(e).__name__}")
    finally:
        subprocess.run = real_run
    check("both PowerShell calls (OK-WW's python, the launcher list) get the budget's 3 s",
          _pwsh_timeouts, [3.0, 3.0])
    _pwsh_timeouts.clear()
    subprocess.run = _rec
    try:
        pk._okww_quiesce(sleep=lambda _s: None)
    finally:
        subprocess.run = real_run
    check("without a budget they keep the 60 s guard", _pwsh_timeouts, [60, 60])


def _part_okww_report():
    """鸣潮的运行结果要能进日报——即使它给不出掉落物。

OK-WW 是纯图像识别的战斗脚本，从不读结算界面，所以没有 MAA 那种
`drop_statistics` 可抄。它唯一公布的数字来自 ok-script 的 `info_set`
（该函数每次调用都会写日志），能拿到的是：投进去多少波片、换来几次进本、
日常任务停在哪里。运营 2026-08-25 的原话是「虽然它没有掉落物的显示，
但只能说够用了」。

另一处要点：AUTO-MAS 把 OK-WW 归在 `general_result` 这个通用键下，
和「通用脚本」共用，**光看键名认不出是哪个脚本**——只能靠文件名前缀。

    Formerly test_okww_report.py.
    """
    import json, os, sys

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.features.verify import collector_okww
    from ark_relay.core import ledger as core


    LOG = """\
2026-08-25 21:31:02 INFO ok.task.task DailyTask:info_set Chars 清宵, 折枝, 维里奈
2026-08-25 21:31:10 INFO ok.task.task DailyTask:info_set current daily progress 0
2026-08-25 21:31:11 INFO ok.task.task DailyTask:info_set total daily points 20
2026-08-25 21:31:30 INFO ok.task.task ForgeryTask:info_set current_stamina 240
2026-08-25 21:33:00 INFO ok.task.task BaseWWTask:使用单倍体力
2026-08-25 21:35:00 INFO ok.task.task ForgeryTask:info_set current_stamina 200
2026-08-25 21:35:01 INFO ok.task.task BaseWWTask:使用单倍体力
2026-08-25 21:37:00 INFO ok.task.task ForgeryTask:info_set current_stamina 160
2026-08-25 21:37:01 INFO ok.task.task BaseWWTask:当前体力大于等于双倍, 160 >= 80
2026-08-25 21:40:00 INFO ok.task.task ForgeryTask:info_set current_stamina 80
2026-08-25 21:40:01 INFO ok.task.task BaseWWTask:使用单倍体力
2026-08-25 21:42:00 INFO ok.task.task ForgeryTask:info_set current_stamina 40
2026-08-25 21:42:01 INFO ok.task.task BaseWWTask:使用单倍体力
2026-08-25 21:44:00 INFO ok.task.task ForgeryTask:info_set current_stamina 0
2026-08-25 21:44:01 INFO ok.task.task DomainTask:used all stamina
2026-08-25 21:44:30 INFO ok.task.task DailyTask:info_set current daily progress 180
2026-08-25 21:44:31 INFO ok.task.task DailyTask:info_set total daily points 100
2026-08-25 21:44:40 INFO ok.task.task DailyTask:info_set current task claim daily
2026-08-25 21:45:00 INFO ok.task.task DailyTask:info_set current task claim mail
2026-08-25 21:45:20 INFO ok.task.task DailyTask:battle pass
2026-08-25 21:45:40 INFO ok.task.task DailyTask:info_set current task check weekly garden
2026-08-25 21:46:00 INFO ok.task.task DailyTask:Daily Task Completed
"""

    log = TMP / "sample.log"
    log.write_text(LOG, encoding="utf-8")
    got = collector.parse_okww_log(log)

    print("[从日志里还原出来的数字]")
    # 240→200→160→80→40→0，逐段下降相加 = 240。首尾相减在有储备回补时会算少。
    check("消耗波片按逐段下降累加", got.get("okww_stamina_spent"), 240)
    check("进本次数 = 每次消耗体力各一条", got.get("okww_runs"), 5)
    check("no okww_daily field (dropped 2026-10-13, read by nothing)", "okww_daily" in got, False)
    check("活跃度带上限、满了要标出来", got.get("okww_points"), "100/100（已满）")
    # 2026-08-29 改口径：OK-WW 的 used all stamina 不是「剩 0」，是**剩下的不够
    # 再开一局**（凝素领域单次 40，剩 37 就进不去）。用户点名「用尽不是零吗？
    # 还剩 20 多」——原来那句直译是事实错误。
    check("为什么停下", got.get("okww_stopped"), "体力不够再开一局")
    # 只报有信息量的项，而且按实际成败标注——出现在日志里不等于做成了。
    check("跑完还剩多少波片", got.get("okww_stamina_left"), 0)
    check("任务按成败标注", got.get("okww_steps"), ["凝素领域 ×5"])

    print("\n[储备回补不能被算成没花]")
    refill = TMP / "refill.log"
    refill.write_text("info_set current_stamina 100\ninfo_set current_stamina 60\n"
                      "info_set current_stamina 240\ninfo_set current_stamina 200\n",
                      encoding="utf-8")
    check("只累加下降段", collector.parse_okww_log(refill).get("okww_stamina_spent"), 80)

    print("\n[体力不够时说得出原因]")
    short = TMP / "short.log"
    short.write_text("info_set current_stamina 18\nnot enough stamina\n", encoding="utf-8")
    check("报「体力不够」", collector.parse_okww_log(short).get("okww_stopped"),
          "体力不够，一局都没开成")

    print("\n[凝素领域要报人话名字，不是序号]")
    # 用户 2026-08-26：「他那个凝素领域第一个机器看得懂，人看不懂是什么啊」。
    # 序号→名字的表是实拍游戏内列表抄的，认不出的序号必须退回「第 N 个」，
    # 宁可少说也不能报错名字——列表顺序会随筛选和版本变。
    fl = collector_okww._forgery_label
    check("0 → 陨翼云渊", fl("info_set Teleport to Forgery Challenge 0"),
          "凝素领域·陨翼云渊（迅刀）")
    check("3 → 碎蚀云渊", fl("info_set Teleport to Forgery Challenge 3"),
          "凝素领域·碎蚀云渊（臂铠）")
    check("第 10 个（2026-09-04 补全的后半段）",
          fl("info_set Teleport to Forgery Challenge 9"), "凝素领域·余烬终课（佩枪）")
    check("表里真没有的序号要明说没登记，不许编名字",
          fl("info_set Teleport to Forgery Challenge 98"), "凝素领域（第 99 个，对照表没登记）")
    check("日志里根本没这行就只说「凝素领域」", fl("什么都没有"), "凝素领域")

    named = TMP / "named.log"
    named.write_text(
        "info_set current_stamina 240\n"
        "ForgeryTask:info_set Teleport to Forgery Challenge 0\n使用单倍体力\n"
        "ForgeryTask:info_set Teleport to Forgery Challenge 0\n使用单倍体力\n"
        "info_set current_stamina 80\n", encoding="utf-8")
    check("步骤里带上了副本名",
          collector.parse_okww_log(named).get("okww_steps"),
          ["凝素领域·陨翼云渊（迅刀） ×2"])

    print("\n[记录能被认出来是 OK-WW，而不是「通用脚本」]")
    root = TMP / "history"
    d = root / "2026-08-25" / "wuwa"
    d.mkdir(parents=True, exist_ok=True)
    j = d / "OK-WW-21-31-02.json"
    j.write_text(json.dumps({"general_result": "Success!"}), encoding="utf-8")
    (d / "OK-WW-21-31-02.log").write_text(LOG, encoding="utf-8")
    rec = collector.parse_record(j, root)
    check("解析出来了", rec is not None)
    if rec:
        check("脚本名来自文件名前缀", rec.script, "OK-WW")
        check("Success! 算成功", rec.ok, True)
        check("日志里的数字挂到了 raw 上", rec.raw.get("okww_runs"), 5)

    print("\n[日报里真的会写出来]")
    entry = {"script": "OK-WW", "user": "wuwa", "ok": True, "raw": got,
             "started": "2026-08-25 21:31", "finished": "2026-08-25 21:46",
             "duration_min": 15, "failed": [], "drops": {}, "recruits": {}}
    body = "\n".join(core._render_entries([entry])) if hasattr(core, "_render_entries") else ""
    if not body:                      # 渲染函数名不同就退回源码检查
        src = (Path(__file__).resolve().parents[1] / "ark_relay" / "core" / "ledger_rows.py").read_text(encoding="utf-8")
        # 2026-08-29 用户要求删掉的两项：
        #   消耗量——「我不需要啊，不要再塞进去了」
        #   活跃度/日常进度——读数被实测证伪（活跃度实际 160 报成 40，
        #   日常进度读成 0/180 而这一轮明明刷了）。错的数字比没有数字更糟，
        #   在把屏幕和日志对上之前不报。
        # 只看代码不看注释：注释里正写着「为什么不再报消耗量」，
        # 连注释一起搜必然误报。（同一个坑今天踩过第二次了。）
        src_code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        check("不再渲染消耗量", "消耗波片" in src_code, False)
        check("不再渲染活跃度/日常进度",
              "活跃度" in src_code or "日常波片" in src_code, False)
        check("渲染了备用体力（游戏里是两个数）", "备用" in src)
        check("渲染了任务列表", "okww_steps" in src)
        check("渲染了剩余波片", "波片" in src)
    else:
        check("写出了波片消耗", "消耗波片 240" in body)
        check("写出了进本次数", "进本 5 次" in body)


def _part_okww_structured():
    """判断改用 OK-WW 自己写的结构化状态（info_set），散文只做兜底。

根治第 1 项：上游自己报的状态才是判据。2026-09-08 之前，「实际刷了哪个无音区」
「哪一步出的错」都是从提示语里刮的，上游一改措辞就失效——今天修的一串 bug
全是这么来的。OK-WW 每一步都写 `info_set 键 值`，那是它自己的状态。

    Formerly test_okww_structured.py.
    """

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.features.verify import collector_okww


    REAL = (ROOT / "tests" / "replay" / "2026-09-07" / "wuwa" / "OK-WW-07-27-50.log"
            ).read_text(encoding="utf-8", errors="replace")

    print("[真实日志：读出上游自己报的状态]")
    info = collector_okww.okww_info(REAL)
    check("实际传送到第几个无音区（0 起算）", info["fields"].get("Teleport to Tacet Suppression"), 1)
    check("体力", info["fields"].get("current_stamina"), 75)
    check("备用体力", info["fields"].get("back_up_stamina"), 26)
    check("日常进度", info["fields"].get("current daily progress"), 180)
    check("角色名整行都是值，不按空格切", info["fields"].get("Chars"), "千咲, 洛瑟菈, 绯雪")
    check("走过哪几步", info["tasks"][:3], ["check weekly garden", "claim daily", "claim mail"])
    check("上游没报错误", info["error"], "")

    print("[刷的是哪个无音区：以上游报的实际序号为准]")
    check("玄幽东岳（配置写 2、上游报 1）", collector_okww._okww_farm(REAL)[0], "无音区·玄幽东岳")
    faked = REAL.replace("info_set Teleport to Tacet Suppression 1",
                         "info_set Teleport to Tacet Suppression 3")
    check("上游报 3 就是第 4 个", collector_okww._okww_farm(faked)[0], "无音区·冰原运输港")

    print("[体力先刷了培养目标的强敌材料（改动层 强敌领奖，2026-11-13）]")
    boss = ("2026-11-13 04:43:20,100 INFO TaskExecutor TacetTask:强敌领奖：莉莉的共鸣者突破材料 1/46\n"
            "2026-11-13 04:45:20,100 INFO TaskExecutor TacetTask:强敌领奖：领了一次，花 120 波片（领之前 1/46）\n"
            "2026-11-13 04:46:20,100 INFO TaskExecutor TacetTask:强敌领奖：莉莉的共鸣者突破材料 9/46\n")
    check("写成强敌·莉莉的材料，不写无音区", collector_okww._okww_farm(boss),
          ("强敌·莉莉共鸣者突破材料（最后读到 9/46）", "共鸣者突破材料"))
    check("后面又刷了无音区：带一句", collector_okww._okww_farm(
        boss + "2026-11-13 04:50:00,000 INFO TaskExecutor TacetTask:info_set Teleport to Tacet Suppression 0\n")[0],
          "强敌·莉莉共鸣者突破材料（最后读到 9/46），余下的刷了无音区")
    check("只读了数量、没领：照旧按无音区", collector_okww._okww_farm(boss.splitlines()[0] + "\n")[0],
          "无音区（日志里没有序号）")

    print("[刷体力这一项：强敌那条的几种结局]")
    from ark_relay.features.verify import outcome as _oc

    def stamina(log):
        got = [c for c in _oc.okww_checks(log, expect_nest=False, expect_daily=False) if c.label == "刷体力"]
        return (got[0].ok, got[0].detail) if got else None
    L = "2026-11-13 09:20:0{} INFO TaskExecutor TacetTask:{}\n"
    fought = L.format(1, "强敌领奖：莉莉的共鸣者突破材料 1/46") + L.format(2, "enter combat None") + \
        L.format(3, "强敌领奖：领了一次，花 60 波片（领之前 1/46）") + L.format(4, "强敌领奖：体力 8 + 备用 0 不够领一次的 60，这趟刷完")
    check("打了、领了、体力用完：绿", stamina(fought), (True, ""))
    full = L.format(1, "强敌领奖：莉莉的共鸣者突破材料 46/46") + \
        L.format(2, "强敌领奖：莉莉的共鸣者突破材料已经够了（46/46），体力先留着不刷（无音区关着，等定下一个刷什么）")
    check("材料够了、没打：绿，说体力留着", stamina(full),
          (True, "莉莉的共鸣者突破材料已经够了（46/46），体力先留着不刷（无音区关着，等定下一个刷什么）"))
    gone = L.format(1, "强敌领奖：莉莉的共鸣者突破材料已经够了（培养目标页上不再列这一行），体力先留着不刷（无音区关着，等定下一个刷什么）")
    check("那一行没了、没打：绿", stamina(gone),
          (True, "莉莉的共鸣者突破材料已经够了（培养目标页上不再列这一行），体力先留着不刷（无音区关着，等定下一个刷什么）"))
    short = L.format(1, "强敌领奖：莉莉的共鸣者突破材料 9/46") + L.format(2, "强敌领奖：体力 30 + 备用 0 不够领一次的 60，这趟刷完")
    check("体力不够一次、没打：绿，体力不足", stamina(short), (True, "体力不足，本来就没得刷"))
    failed = fought.replace("领了一次", "领了一次") + \
        "2026-11-13 09:25:00 ERROR TaskExecutor TacetTask:强敌领奖：出错，剩下的体力不刷（无音区关着）: 强敌领奖：打完走到宝箱按 F，没出「领取奖励」框。整屏读到 Box(...)\n"
    ok_, why = stamina(failed)
    check("出错：红，说刷到一半出错", (ok_, why.startswith("刷培养目标的突破材料没刷完：出错")), (False, True))
    check("出错：不带整屏的字", "Box(" in why, False)
    other = L.format(1, "强敌领奖：培养目标不是莉莉，不刷强敌，体力这趟不刷。整屏读到 x")
    check("培养目标换了人：红", stamina(other)[0], False)

    print("[上游自己说「错误 …」时，照它说的写，不用刮 traceback]")
    said = ("2026-09-08 01:00:00,000 INFO TaskExecutor DailyTask:info_set current task farm echo\n"
            "2026-09-08 01:00:01,000 INFO TaskExecutor DailyTask:info_set 错误 combat check not in combat\n")
    check("说清哪一步、什么事", collector_okww._okww_error(said), "周本：没有进入战斗")

    print("[包装层抛的错：任务名取出错那一刻的 current task，不是全程最后一个]")
    wrapped = (
        "2026-09-08 01:00:00,000 INFO TaskExecutor DailyTask:info_set current task nest start\n"
        "2026-09-08 01:00:01,000 ERROR TaskExecutor DailyTask:NightmareNestTask Failed Traceback (most recent call last):\n"
        "ok.task.exceptions.WaitFailedException\n"
        "2026-09-08 01:00:02,000 INFO TaskExecutor DailyTask:info_set current task claim daily\n")
    check("说的是残象聚落，不是后面那步领日常",
          collector_okww._okww_error(wrapped), "残象聚落：没打成")


if __name__ == "__main__":
    sys.exit(run_parts([_part_okww_alive_cache, _part_okww_drift, _part_okww_error_event, _part_okww_error_reason, _part_okww_exit_race, _part_okww_failed_reason, _part_okww_i18n, _part_okww_landed, _part_okww_names_not_numbers, _part_okww_python_filter, _part_okww_quiesce_order, _part_okww_report, _part_okww_structured]))
