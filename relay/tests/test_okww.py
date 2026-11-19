"""OK-WW collector, daily/nest/echo-farm overrides, and upstream patch pins."""
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)
# relay/ first for every part, as each part used to put it (run_parts restores sys.path after one)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub_win32(*names: str) -> None:
    """Stand-ins for the Windows-only modules the relay imports (pywin32, wmi, ...) on the Mac:
    any attribute of one is a callable returning another stand-in. setdefault: a module already
    in sys.modules stays; run_parts drops what a part added once the part is over."""
    import types

    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()

    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any

    for name in names:
        sys.modules.setdefault(name, _Stub(name))


class _AnyMeta(type):
    """A stand-in upstream class: any method _install_hooks reads exists and does nothing."""
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def anything(self, *a, **kw):
            return None
        return anything


class _Cfg:
    def __init__(self, root):
        self.okww_dir = root
        self.state_dir = root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)


def _part_okww_alive_cache():
    """OK-WW's python check on a phone publish: cached, and never asked by the stop push."""
    import contextlib
    import subprocess
    import tempfile
    import types

    from ark_relay.features import phone, redbutton, snapshot

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


def _part_okww_drift():
    """Before the run, the relay knows whether OK-WW's update broke a pinned copy."""

    from ark_relay.features import okww_overlay

    V373 = (fx_dir(Path(__file__), "fixtures")
            / "okww-NightmareNestTask-v3.7.3.py.txt").read_text(encoding="utf-8")
    # v3.7.2's find_nest differs from v3.7.3's in the box top only (diff of the two releases).
    V372 = V373.replace("counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re)",
                        "counts = self.ocr(0.35, 0.13, 1, 0.96, match=self.count_re)")
    # The OK-WW the machine runs (test_gl_okww_contract.INSTALLED): the pins are its bodies.
    INST = fx_dir(Path(__file__), "gamesim") / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task"
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
    check("six pins in all", len(okww_overlay.pins()), 6)
    check("get_total_daily_points pinned to v3.7.14-beta.2, not adapted",
          got.get("DailyTask.get_total_daily_points"), ("b082b5c41b29", False))
    check("claim_daily pinned to v3.7.14-beta.2, not adapted", got.get("DailyTask.claim_daily"), ("555de9348dc7", False))
    check("claim_battle_pass pinned to v3.7.14-beta.2, not adapted",
          got.get("DailyTask.claim_battle_pass"), ("0a11121c349a", False))
    check("upstream v3.7.14-beta.2 DailyTask on disk: no drift",
          okww_overlay.drift(okww(VINST, {"DailyTask.py": DAILY_INST})), [])
    changed = DAILY_INST.replace("    def claim_daily(self):\n", "    def claim_daily(self):\n        pass\n", 1)
    d = okww_overlay.drift(okww(VINST, {"DailyTask.py": changed}))
    check("a changed claim_daily is found before the run", [x["what"] for x in d], ["DailyTask.claim_daily"])
    changed = DAILY_INST.replace("points_boxes[0].name", "points_boxes[-1].name", 1)
    d = okww_overlay.drift(okww(VINST, {"DailyTask.py": changed}))
    check("a changed get_total_daily_points is found before the run", [x["what"] for x in d],
          ["DailyTask.get_total_daily_points"])

    print("\n[装着的 v3.7.14-beta.2 在盘上：对得上，不出声]")
    check("没有对不上的", okww_overlay.drift(okww(VINST)), [])
    check("一句话都不说", okww_overlay.drift_line(okww(VINST), tmpdir()), "")

    print("\n[盘上是旧版（或下一版）：开跑前就说，且只说一次]")
    d = okww_overlay.drift(okww(V372))
    check("找出 find_nest", [x["what"] for x in d], ["NightmareNestTask.find_nest"])
    check("算出来的就是旧版哈希", d[0]["got"] if d else "", "3b0271924cac")
    state = tmpdir()
    line = okww_overlay.drift_line(okww(V372), state)
    check("adapted only: no 对不上", "对不上" in line, False)
    check("说了会适配", "按新版适配" in line)
    check("names the method", "NightmareNestTask.find_nest" in line)
    from ark_relay.core import texts
    check("adapted only: healthy 🩹 title", texts.patches(1, [line]).startswith("🩹"), True)
    check("同一处第二次开机不再说", okww_overlay.drift_line(okww(V372), state), "")

    print("\n[skipped pin (no adapt): said at every boot - its override stays off until copied again]")
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


def _part_okww_error_event():
    """The reason a run failed is read from the last event's own tracebacks, grouped by time."""

    from ark_relay.features import outcome as co

    print("[the real 09-01 log: the weekly claim's own wait, not the wrapper]")
    real = (fx_dir(Path(__file__), "replay") / "2026-09-01" / "wuwa" / "OK-WW-06-35-43.log"
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
    real = (fx_dir(Path(__file__), "fixtures") / "m6-okww" / "0921-weekly.log").read_text(encoding="utf-8")
    check("09-21: the 10 s wait is said", co._okww_error(real).endswith("（等了 10 秒）"), True)
    wait = "2026-09-01 10:50:13,335 INFO TaskExecutor TaskExecutor:wait_until timeout <f> 10 seconds\n"
    far = wait + STACK[:5000] + "\n" + head("10:50:13,900", "FarmEchoTask", "farm 4c error, try handle monthly card")
    check("5000 characters back, same second: found", co._wait_before(far, far.rindex(" ERROR")), "10")
    stale = ("2026-09-01 10:49:00,000 INFO TaskExecutor TaskExecutor:wait_until timeout <f> 7 seconds\n"
             + head("10:50:13,900", "FarmEchoTask", "farm 4c error"))
    check("a wait a minute earlier is another event", co._wait_before(stale, stale.rindex(" ERROR")), "")


def _part_okww_error_reason():
    """OK-WW 失败原因要写真的，「进不了游戏」只给真没进去的那种。"""

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
    from ark_relay.features import outcome as _cok
    _said = []
    _h = type("H", (__import__("logging").Handler,), {"emit": lambda self, r: _said.append(r.getMessage())})()
    _cok._log_collector_okww.addHandler(_h)
    why = _cok._okww_say("FarmEchoTask", "这一趟按失败结束：周本：结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）", "ArkStopped")
    check("原因照用", why, "周本：结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）")
    check("不说不认识", "不认识" in why, False)
    check("不记「还没有翻译」的警告", [m for m in _said if "还没有翻译" in m], [])
    _cok._log_collector_okww.removeHandler(_h)

    print("[原文和异常都不认识：明说不认识，并且**把原文抄进来**]")
    UNK2 = UNKNOWN.replace("ok.task.exceptions.WaitFailedException", "ok.task.exceptions.SomethingNewException")
    (d / "unk2.log").write_text(UNK2, encoding="utf-8")
    u2 = collector.parse_okww_log(d / "unk2.log")
    got = u2.get("okww_error") or ""
    check("点名了是哪一步", got.startswith("无音区："), True)
    check("明说不认识", "中继还不认识这条错" in got, True)
    check("原文照抄进来了", "some brand new english message" in got, True)
    check("不出现「出错」「这一步」这类模糊词",
          any(k in got.split("原文照抄")[0] for k in ("这一步", "出错", "异常", "错误")), False)

    from ark_relay.features.outcome import _okww_say

    _said = _okww_say("TaskExecutor", "📅 Daily Task exception stopped", "Exception")
    check("这条真实日志行翻得出来", "还不认识" in _said, False)
    check("说的是日常清单停了", "日常清单整个停了" in _said, True)
    check("指到真正的原因在哪", "真正的原因" in _said, True)
    check("不许抢掉更靠谱的那条：回放里 09-01 那条仍报「等一个画面没等到」",
          "Daily Task exception stopped" in str(__import__("ark_relay.features.outcome", fromlist=["x"])._OKWW_MSG_ZH), False)
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
    from ark_relay.features import outcome as _co
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
    """AUTO-MAS 说「OK-WW 在完成任务前退出」，但 OK-WW 自己写了 Daily Task Completed → 这趟是做完的。"""
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
    """A run the overlay ended as failed is pushed with its reason once, without the OCR dump."""

    from ark_relay.features import outcome as co, outcome

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


def _part_okww_i18n():
    """OK-WW's zh_CN log lines are turned back into English from the machine's own catalogs (okww_i18n).
    """
    import os
    import shutil
    import time

    TMP = tmpdir()
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    from ark_relay.features import outcome as I
    from ark_relay.features import outcome

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
    shutil.copy(fx_dir(HERE, "fixtures") / "okww-i18n" / "ok-v3.7.19.po", real / I.PO_REL)
    shutil.copy(fx_dir(HERE, "fixtures") / "okww-i18n" / "okscript-3.0.3-zh_CN.ts", real / I.TS_REL)
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


def _part_okww_landed():
    """scripts/windows/okww-landed.py judges the OK-WW install the right way round."""
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
    check("no flag path built from the data folder", "no-stamina-farm.flag" in src, False)
    check("reads config.NO_STAMINA_FARM_FLAG",
          any(isinstance(n, ast.ImportFrom) and n.module == "ark_relay.core.config"
              and any(a.name == "NO_STAMINA_FARM_FLAG" for a in n.names) for n in ast.walk(tree)), True)
    from ark_relay.core import config
    overrides = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "okww_files"
                 / "ark_overrides.tasks.py").read_text(encoding="utf-8")
    check("the same path the override obeys", f'NO_STAMINA_FLAG = r"{config.NO_STAMINA_FARM_FLAG}"' in overrides, True)


def _part_okww_names_not_numbers():
    """日报里鸣潮刷的本和产出必须是人话，不许只有序号或一句笼统的类别。"""
    import pathlib
    import re

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.core.wuwa_tables import wuwa_tacet
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

    page_tacet = {1: ("衔梦照世之心", "茜染怀想之花"), 2: ("衔梦照世之心", "镜影流电之瞬"), 3: ("羽落空尘之歌", "冥途夜行之灯"),
                  4: ("羽落空尘之歌", "清邪荡煞之心"), 5: ("雪落无声之愿", "剪心辑梦之影"), 6: ("听唤语义之愿", "长路启航之星"),
                  7: ("长路启航之星", "斑驳粉饰之沫")}
    page_forge = {1: "陨翼云渊", 2: "静灭云渊", 3: "裂斩云渊", 4: "碎蚀云渊", 5: "沉熄云渊"}
    for idx, (_, sets) in wuwa_tacet.TACET.items():
        if page_tacet.get(idx) != (sets[0], sets[1]):
            fails.append(f"手机 TACET 里第 {idx} 项和 wuwa_tacet 对不上")

    from ark_relay.core.wuwa_tables import wuwa_forgery
    for idx, name in page_forge.items():
        if wuwa_forgery.FORGERY.get(idx, ("",))[0] != name:
            fails.append(f"手机 FORGE 第 {idx} 项（{name}）和 wuwa_forgery 对不上")

    # 手机给的每个序号都必须查得到名字，不许退化成「第 N 个」
    for idx in page_forge:
        if "没登记" in wuwa_forgery.label(idx):
            fails.append(f"手机能选第 {idx} 个凝素领域，但对照表里没有它")

    # 明日安排那一支也不许退化成序号（plan.py 以前自己抄了一份只有 4 条的表）
    for i in (1, 5, 15):
        line = f"体力刷 {wuwa_forgery.label(i)}，出 {wuwa_forgery.reward(i)}"
        if "#" in line or "没登记" in line:
            fails.append(f"明日安排第 {i} 个凝素领域退化成序号：{line}")

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
    """Which pythons count as OK-WW's own, and what an unreadable list means."""
    import fnmatch
    import re

    from ark_relay.features import preupdate as P

    def is_okww(cmdline: str, ps: str = P._OKWW_PY) -> bool:
        """Does the Where-Object of `ps` keep a process with this command line?"""
        pats = re.findall(r"-like\s+'([^']*)'", ps)
        return any(fnmatch.fnmatchcase(cmdline.lower(), p.lower()) for p in pats)

    print("[the filter: OK-WW's install folder, nothing else]")
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
    """Stopping OK-WW has to kill the script before the game."""
    import subprocess

    from ark_relay.features import preupdate as pk

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
    """鸣潮的运行结果要能进日报——即使它给不出掉落物。"""
    import json, os

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
    from ark_relay.core import collector
    from ark_relay.features import outcome as collector_okww
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
        src = (Path(__file__).resolve().parents[1] / "ark_relay" / "core" / "ledger.py").read_text(encoding="utf-8")
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
    """判断改用 OK-WW 自己写的结构化状态（info_set），散文只做兜底。"""

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.features import outcome as collector_okww

    REAL = (fx_dir(ROOT, "replay") / "2026-09-07" / "wuwa" / "OK-WW-07-27-50.log"
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
    from ark_relay.features import outcome as _oc

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


def _part_okww_battle_pass():
    """OK-WW's battle-pass line is about the battle pass, not about a fight."""

    from ark_relay.core import texts
    from ark_relay.features import outcome as collector_okww

    REAL = """2026-09-29 09:28:42,334 INFO TaskExecutor DailyTask:info_set current task in main esc=True
2026-09-29 09:28:43,334 INFO TaskExecutor DailyTask:battle pass
2026-09-29 09:28:53,798 INFO TaskExecutor TaskExecutor:wait_until timeout <function OCR.wait_ocr.<locals>.<lambda> at 0x000002BC775F9C60> 10 seconds
2026-09-29 09:28:53,798 ERROR TaskExecutor DailyTask:can not battle pass, maybe ended
2026-09-29 09:28:53,807 INFO TaskExecutor DailyTask:info_set current task wait main esc=True
"""
    REAL = REAL.replace("maybe ended\n", "maybe ended \n")    # upstream's line ends in a space
    WANT = f"日常清单：{texts.OKWW_BATTLE_PASS_UNCLAIMED}"

    print("[the battle-pass line is translated as the battle pass]")
    said = collector_okww._okww_say("DailyTask", "can not battle pass, maybe ended", "")
    check("the sentence for the raw line", said, WANT)
    check("it names 战令", "战令" in said)
    check("it no longer says 没能进入战斗", "没能进入战斗" in said, False)
    check("plain language", texts.plain(said), [])
    # When OK-WW records the line as the run's 错误 (info_set), the report takes this path.
    recorded = REAL.replace(
        "maybe ended \n",
        "maybe ended \n2026-09-29 09:28:53,799 INFO TaskExecutor DailyTask:info_set 错误 can not battle pass, maybe ended\n")
    recorded = "2026-09-29 09:27:30,000 INFO TaskExecutor DailyTask:info_set current task claim mail\n" + recorded
    check("recorded as the run's reason -> the same battle-pass sentence", collector_okww._okww_error(recorded), WANT)
    check("the 「not in combat」 line keeps its own fight wording",
          collector_okww._okww_say("BaseCombatTask", "combat check not in combat", ""), "战斗：没有进入战斗")


def _part_okww_battle_pass_claim():
    """OK-WW's battle pass (先约电台): a page that did not open is tried once more, then reported."""
    import ast
    import re
    import tempfile
    import textwrap
    import types

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    from ark_relay.core import texts
    from ark_relay.features import okww_overlay
    from ark_relay.features import outcome

    UPSTREAM = (fx_dir(HERE, "gamesim") / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task" / "DailyTask.py.txt").read_text(encoding="utf-8")

    def overlay():
        """A fresh copy of the overrides file. Its own install block fails here (no OK-WW) and is caught."""
        ns = {"__name__": "ark_overrides_test"}
        exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
        ns["_applied"].clear()
        ns["_skipped"].clear()
        return ns

    def upstream_method(text=UPSTREAM):
        """Upstream's claim_battle_pass as a plain function of self, cut out of the file."""
        tree = ast.parse(text)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DailyTask")
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "claim_battle_pass")
        lines = text.splitlines(keepends=True)[fn.lineno - 1:fn.end_lineno]
        scope = {"re": re}
        exec(compile(textwrap.dedent("".join(lines)), "DailyTask.py", "exec"), scope)
        return scope["claim_battle_pass"]

    class Box:
        def __init__(self, name):
            self.name = name

    class Game:
        """The world and the podcast page. `opens` says, per Alt+click, whether the page comes up."""

        def __init__(self, opens, level="37", icon=(0.86, 0.05)):
            self.opens = list(opens)
            self.icon = icon
            self.level = level
            self.page = False
            self.acts, self.logs, self.errors, self.shots = [], [], [], []

        # input
        def send_key_down(self, key):
            self.acts.append(("down", key))

        def send_key_up(self, key):
            self.acts.append(("up", key))

        def sleep(self, s):
            self.acts.append(("sleep", s))

        def click_relative(self, x, y, **kw):
            self.acts.append(("click_relative", x, y, tuple(sorted(kw.items()))))
            if (x, y) == self.icon:
                self.page = self.opens.pop(0) if self.opens else False

        def click(self, x, y, **kw):
            self.acts.append(("click", x, y, tuple(sorted(kw.items()))))

        # reading
        def wait_ocr(self, x, y, to_x, to_y, match=None, post_action=None, **kw):
            self.acts.append(("wait_ocr", x, y, to_x, to_y, match.pattern if match else None,
                              post_action is not None, tuple(sorted(kw.items()))))
            if post_action is not None and self.page:
                post_action()
            return [Box(self.level)] if self.page else None

        def ocr(self, *a, **kw):
            return [Box("先约电台" if self.page else "大世界")]

        def box_of_screen(self, *a):
            return a

        def screenshot(self, name):
            self.shots.append(name)

        def ensure_main(self, *a, **kw):
            self.page = False
            self.acts.append(("ensure_main",))

        # logging
        def log_info(self, msg, **kw):
            self.logs.append(msg)

        def log_error(self, msg, *a, **kw):
            self.errors.append(msg)

        # ok-script's translation (v3.7.14-beta.2 wraps log sentences in it); English here
        def tr(self, msg):
            return msg

    def as_log(game):
        """The lines as OK-WW writes them for the task executor (what the relay reads)."""
        out = [f"2026-10-12 09:30:{i:02d},000 INFO TaskExecutor DailyTask:{m}" for i, m in enumerate(game.logs)]
        out += [f"2026-10-12 09:31:{i:02d},000 ERROR TaskExecutor DailyTask:{m} " for i, m in enumerate(game.errors)]
        return "\n".join(out) + "\n"

    def no_logs(acts):
        return [a for a in acts if a[0] != "sleep"]

    ns = overlay()

    print("[the pin is upstream's real body]")
    with tempfile.TemporaryDirectory() as d:
        Path(d, "DailyTask.py").write_text(UPSTREAM, encoding="utf-8")
        got = okww_overlay._method_sha(okww_overlay._classes(Path(d)), "DailyTask", "claim_battle_pass")
    check("sha of claim_battle_pass in the installed v3.7.14-beta.2 == _BATTLE_PASS_SHA", got, ns["_BATTLE_PASS_SHA"])
    check("the overlay reads the same level box upstream does",
          "self.wait_ocr(0.2, 0.13, 0.32, 0.22" in UPSTREAM and ns["BATTLE_PASS_LEVEL_BOX"] == (0.2, 0.13, 0.32, 0.22), True)
    check("the overlay's line markers are the ones outcome reads",
          (ns["BATTLE_PASS_OK"], ns["BATTLE_PASS_RETRY"], ns["BATTLE_PASS_FAILED"], ns["BATTLE_PASS_UNCHECKED"]),
          (outcome._BATTLE_PASS_OK, outcome._BATTLE_PASS_RETRY, outcome._BATTLE_PASS_FAILED,
           outcome._BATTLE_PASS_UNCHECKED))

    print("\n[page opens at once: upstream's clicks, nothing more]")
    up = Game([True])
    upstream_method()(up)
    ours = Game([True])
    ns["_claim_battle_pass_checked"](ours)
    check("same inputs and reads as upstream, in the same order", no_logs(ours.acts), no_logs(up.acts))
    check("no screenshot, no error", (ours.shots, ours.errors), ([], []))
    check("the green line names the level read", ours.logs[-1], f"{ns['BATTLE_PASS_OK']}37）")
    c = outcome.battle_pass_checks(as_log(ours))
    check("relay: one green battle-pass item", [(x.label, x.ok, x.detail) for x in c],
          [(texts.OKWW_BATTLE_PASS_LABEL, True, "")])

    print("\n[first try misses (09-29 09:28), second opens: claimed in the same run]")
    g = Game([False, True])
    ns["_claim_battle_pass_checked"](g)
    opens = [a for a in g.acts if a[:3] == ("click_relative", 0.86, 0.05)]
    check("the page was opened exactly twice", len(opens), 2)
    check("a screenshot of the miss", g.shots, ["battle_pass_unopened_1"])
    check("back to the world between the two tries",
          g.acts.index(("ensure_main",)) < [i for i, a in enumerate(g.acts) if a[:3] == ("click_relative", 0.86, 0.05)][1],
          True)
    check("the miss says what the screen showed", any(m.startswith(ns["BATTLE_PASS_RETRY"]) and "整屏读到" in m
                                                       for m in g.logs), True)
    check("no ERROR line once the retry worked", g.errors, [])
    check("the claim clicks ran after the second open",
          ("click_relative", 0.04, 0.3, (("after_sleep", 1),)) in g.acts, True)
    c = outcome.battle_pass_checks(as_log(g))
    check("relay: green, saying it took a second try", [(x.ok, x.detail) for x in c],
          [(True, texts.OKWW_BATTLE_PASS_RETRIED)])

    print("\n[both tries miss: reported, nothing clicked blind]")
    g = Game([False, False])
    ns["_claim_battle_pass_checked"](g)
    check("opened twice, no third time", len([a for a in g.acts if a[:3] == ("click_relative", 0.86, 0.05)]), 2)
    check("two screenshots", g.shots, ["battle_pass_unopened_1", "battle_pass_unopened_2"])
    check("upstream's own sentence is still logged", g.errors, ["can not battle pass, maybe ended"])
    check("the failed line", any(m.startswith(ns["BATTLE_PASS_FAILED"]) for m in g.logs), True)
    check("no claim clicks on a page that is not there",
          [a for a in g.acts if a[0] == "click_relative" and a[1:3] != (0.86, 0.05)], [])
    check("ends back in the world", g.acts[-1], ("ensure_main",))
    c = outcome.battle_pass_checks(as_log(g))
    check("relay: one red item, the plain sentence", [(x.label, x.ok, x.detail) for x in c],
          [(texts.OKWW_BATTLE_PASS_LABEL, False, texts.OKWW_BATTLE_PASS_FAILED)])

    print("\n[installed on DailyTask: our copy when the body matches, upstream's otherwise]")

    def install(text):
        mod = types.ModuleType("src.task.DailyTask")
        mod.DailyTask = type("DailyTask", (), {})
        # inspect.getsource needs the function to come from a file; give it the fixture's text.
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
            fh.write("import re\n\n\nclass DailyTask:\n" + "".join(
                text.splitlines(keepends=True)[_span(text)[0]:_span(text)[1]]))
        scope = {}
        exec(compile(Path(fh.name).read_text(encoding="utf-8"), fh.name, "exec"), scope)
        mod.DailyTask.claim_battle_pass = scope["DailyTask"].claim_battle_pass
        sys.modules.update({"src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
                            "src.task.DailyTask": mod})
        n = overlay()
        n["_install_battle_pass"]()
        return n, mod.DailyTask

    def _span(text):
        tree = ast.parse(text)
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "DailyTask")
        fn = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == "claim_battle_pass")
        return fn.lineno - 1, fn.end_lineno

    n, cls = install(UPSTREAM)
    check("applied, nothing skipped", (n["_applied"], n["_skipped"]), (["DailyTask.claim_battle_pass"], []))
    g = Game([False, True])
    cls.claim_battle_pass(g)
    check("the installed method retries", len([a for a in g.acts if a[:3] == ("click_relative", 0.86, 0.05)]), 2)

    WORDED = re.sub(r"self\.tr\(('[^']*')\)", r"\1", UPSTREAM)
    check("the worded body really differs from the pin", WORDED != UPSTREAM, True)
    n, cls = install(WORDED)
    check("words only: applied, nothing skipped", (n["_applied"], n["_skipped"]), (["DailyTask.claim_battle_pass"], []))
    check("words only: listed as adapted, saying the structure is unchanged",
          [(a["what"], "代码结构没变" in a["why"]) for a in n["_adapted"]], [("DailyTask.claim_battle_pass", True)])
    g = Game([False, True])
    cls.claim_battle_pass(g)
    check("words only: our copy runs (it retries)",
          len([a for a in g.acts if a[:3] == ("click_relative", 0.86, 0.05)]), 2)

    CHANGED = UPSTREAM.replace("self.click_relative(0.86, 0.05)", "self.click_relative(0.87, 0.05)")
    n, cls = install(CHANGED)
    check("changed upstream body: listed as skipped", [s["what"] for s in n["_skipped"]],
          ["DailyTask.claim_battle_pass（战令没打开时再开一次）"])
    g = Game([False])
    cls.claim_battle_pass(g)
    check("changed upstream body: upstream's own runs (its click, one try)",
          [a for a in g.acts if a[0] == "click_relative"], [("click_relative", 0.87, 0.05, ())])
    check("changed upstream body: the log says so", any(m.startswith(ns["BATTLE_PASS_UNCHECKED"]) for m in g.logs), True)
    check("changed upstream body + miss: still red (upstream's sentence)",
          [(x.ok, x.detail) for x in outcome.battle_pass_checks(as_log(g))],
          [(False, texts.OKWW_BATTLE_PASS_UNCLAIMED)])
    g = Game([True], icon=(0.87, 0.05))
    cls.claim_battle_pass(g)
    check("changed upstream body + page opened: green, saying no retry was there",
          [(x.ok, x.detail) for x in outcome.battle_pass_checks(as_log(g))],
          [(True, texts.OKWW_BATTLE_PASS_UNCHECKED)])

    print("\n[the relay: the real 09-29 run is an item undone]")
    REAL_0929 = """2026-09-29 09:28:31,805 INFO TaskExecutor DailyTask:info_set current task claim mail
2026-09-29 09:28:42,334 INFO TaskExecutor DailyTask:info_set current task in main esc=True
2026-09-29 09:28:43,334 INFO TaskExecutor DailyTask:battle pass
2026-09-29 09:28:53,798 INFO TaskExecutor TaskExecutor:wait_until timeout <function OCR.wait_ocr.<locals>.<lambda> at 0x000002BC775F9C60> 10 seconds
2026-09-29 09:28:53,798 ERROR TaskExecutor DailyTask:can not battle pass, maybe ended
2026-09-29 09:28:53,807 INFO TaskExecutor DailyTask:info_set current task wait main esc=True
2026-09-29 09:28:56,346 INFO TaskExecutor DailyTask:info_set current task in main esc=True
2026-09-29 09:28:56,346 INFO TaskExecutor DailyTask:Daily Task Completed
"""
    checks = outcome.okww_checks(REAL_0929, expect_nest=False)
    bp = [x for x in checks if x.label == texts.OKWW_BATTLE_PASS_LABEL]
    check("09-29: a red battle-pass item", [(x.ok, x.detail) for x in bp], [(False, texts.OKWW_BATTLE_PASS_UNCLAIMED)])
    msg = outcome.summarize(checks, "OK-WW")
    check("09-29: the push names the battle pass", msg is not None and texts.OKWW_BATTLE_PASS_LABEL in msg, True)
    done_before = "2026-09-29 09:21:00,000 INFO TaskExecutor DailyTask:info_set total daily points 100\n" + REAL_0929
    bp = [x for x in outcome.okww_checks(done_before, expect_nest=False) if x.label == texts.OKWW_BATTLE_PASS_LABEL]
    check("dailies already done before the run: the battle pass is still checked", [x.ok for x in bp], [False])
    OLD = (fx_dir(HERE, "fixtures") / "okww-1006-run.log").read_text(encoding="utf-8", errors="replace")
    check("a clean run from before the overlay line: no battle-pass item, no false red",
          outcome.battle_pass_checks(OLD), [])
    LABEL = "战令改动在跑（没打开时同一趟再开一次）"
    ran = {c.label: c.ok for c in outcome.patch_effect_checks(as_log(ours))}
    check("patch check: our copy ran where upstream's step began", ran.get(LABEL), True)
    check("patch check: upstream's line alone (09-29) = our copy did not run",
          {c.label: c.ok for c in outcome.patch_effect_checks(REAL_0929)}.get(LABEL), False)
    check("patch check: upstream's ERROR line is not the trigger",
          LABEL in {c.label for c in outcome.patch_effect_checks(
              "2026-09-29 09:28:53,798 ERROR TaskExecutor DailyTask:can not battle pass, maybe ended \n")}, False)
    check("plain language", [texts.plain(t) for t in (texts.OKWW_BATTLE_PASS_LABEL, texts.OKWW_BATTLE_PASS_FAILED,
                                                        texts.OKWW_BATTLE_PASS_RETRIED, texts.OKWW_BATTLE_PASS_UNCHECKED)],
          [[], [], [], []])

    print("\n[between two seasons (11-11 09:32, alarm #164): the game says 暂未开播 - nothing owed]")
    REAL_1111 = (fx_dir(HERE, "fixtures") / "okww-1111-battle-pass-closed.log").read_text(encoding="utf-8")
    NOTICE = "当前先约电台各频道暂未开播，请于下期先约电台频道开启时间段内进入。"
    check("the sample holds the notice on both misses and upstream's ERROR line",
          (REAL_1111.count(NOTICE), "can not battle pass, maybe ended" in REAL_1111, "战令没领到：" in REAL_1111),
          (2, True, True))
    c = outcome.battle_pass_checks(REAL_1111)
    check("11-11: one item, passed, kind SKIPPED, the closed-season sentence",
          [(x.label, x.ok, x.detail, x.kind) for x in c],
          [(texts.OKWW_BATTLE_PASS_CLOSED, True, "", outcome.SKIPPED)])
    checks = outcome.okww_checks(REAL_1111, expect_nest=False, expect_stamina=False)
    check("11-11: nothing about the battle pass is red in the whole verdict",
          [x.label for x in checks if not x.ok and ("战令" in x.label or "战令" in x.detail)], [])
    check("11-11: the old red label is gone from the verdict",
          texts.OKWW_BATTLE_PASS_LABEL in [x.label for x in checks], False)
    check("11-11: no push for this run", outcome.summarize(checks, "OK-WW"), None)
    other = outcome.Check("别的一项", False, "别的原因")
    msg = outcome.summarize(checks + [other], "OK-WW")
    check("with another item red: said under 按周期今天不跑, not as undone nor as 干成的",
          ("有 1 项没干成" in msg, "按周期今天不跑：" + texts.OKWW_BATTLE_PASS_CLOSED in msg,
           texts.OKWW_BATTLE_PASS_CLOSED in msg.split("干成的：")[-1] if "干成的：" in msg else False),
          (True, True, False))
    # The last miss decides. Notice on the first try only, a blank page on the second: still red.
    lines = REAL_1111.splitlines()
    last = [i for i, ln in enumerate(lines) if "战令没领到：" in ln][-1]
    blank = "\n".join(lines[:last] + [lines[last].replace(NOTICE, "鸣潮")] + lines[last + 1:]) + "\n"
    check("notice gone on the last try: red as before",
          [(x.label, x.ok, x.detail) for x in outcome.battle_pass_checks(blank)],
          [(texts.OKWW_BATTLE_PASS_LABEL, False, texts.OKWW_BATTLE_PASS_FAILED)])
    # Notice on the first try, the page open on the second: claimed, said as a retry.
    retry = [ln for ln in lines if "战令：第一次没打开" in ln][0]
    opened = retry + "\n2026-11-11 09:32:16,526 INFO TaskExecutor DailyTask:" + ns["BATTLE_PASS_OK"] + "37）（第二次打开的）\n"
    check("notice on the first try, opened on the second: green with the retry said",
          [(x.label, x.ok, x.detail) for x in outcome.battle_pass_checks(opened)],
          [(texts.OKWW_BATTLE_PASS_LABEL, True, texts.OKWW_BATTLE_PASS_RETRIED)])
    # The word alone, away from the overlay's final-miss line, decides nothing.
    check("upstream's sentence alone plus the word elsewhere: red (no overlay line to read the screen from)",
          [(x.ok, x.detail) for x in outcome.battle_pass_checks(
              REAL_0929 + "2026-09-29 09:29:00,000 INFO TaskExecutor DailyTask:暂未开播\n")],
          [(False, texts.OKWW_BATTLE_PASS_UNCLAIMED)])
    check("the closed-season sentence is plain language", texts.plain(texts.OKWW_BATTLE_PASS_CLOSED), [])


def _part_okww_claim_readback():  # noqa: C901
    """Weekly boss claim: upstream's claim step with 确认 for its ESC, and the read-back."""
    import types

    from ark_relay.features import okww_overlay

    class Disabled(Exception):
        """ok.TaskDisabledException."""

    class Revived(Exception):
        """src.task.BaseCombatTask.CharRevivedException."""

    class BaseWWTask(metaclass=_AnyMeta):
        # Upstream v3.7.4 BaseWWTask.py:520-526, verbatim: ESC, i.e. 取消.
        def handle_claim_button(self):
            while self.wait_until(self.has_claim, raise_if_not_found=False, time_out=1.5):
                self.sleep(0.5)
                self.send_key('esc')
                self.sleep(0.5)
                return True

        # Upstream v3.7.4 BaseWWTask.py:584-590, with find_one('pick_up_f...') as `f_up`.
        def pick_f(self, handle_claim=True):
            if self.f_up:
                self.send_key('f', after_sleep=1)
                if not handle_claim:
                    return True
                if not self.handle_claim_button():
                    return True

        def click_on_book_target(self, serial_number, total_number, structure=None):
            self.events.append("book")
            return True                 # the team screen, no spoiler dialog

        # Upstream v3.7.3 BaseWWTask.py:1115-1117, verbatim: the overlay replaces it
        # only while its source still hashes to the pin.
        def click_team_challenge(self):
            self.wait_click_feature('team_start_challenge', raise_if_not_found=True, click_after_delay=0.5, after_sleep=1)
            self.wait_click_skip_dialog_confirm()

    class FarmEchoTask(BaseWWTask):
        def teleport_to_configured_boss(self):
            # Upstream v3.7.4 FarmEchoTask.py:273-308, reduced to the steps after the book.
            self.entries += 1
            is_team = self.click_on_book_target(1, 9)
            if is_team and not self.arena:
                self.click_configured_boss_level()
                self.click_solo_challenge()
                self.click_team_challenge()
            self.wait_in_team_and_world(time_out=120)
            return is_team

        def teleport_to_configured_boss_and_prepare(self):
            # Upstream v3.7.3 FarmEchoTask.py:243-266, reduced.
            try:
                self.teleport_to_configured_boss()
            except Exception as e:
                raise RuntimeError("Teleport to boss failed") from e
            self.prepared = "realm"

        def click_configured_boss_level(self):
            self.events.append("level")

        # Upstream v3.7.4 FarmEchoTask.py:374-378, verbatim.
        def click_solo_challenge(self):
            self.click(0.880, 0.911, after_sleep=2)
            self.wait_click_skip_dialog_confirm(time_out=1)

        def combat_once(self, wait_combat_time=200, raise_if_not_found=True, target=False):
            return True

        def incr_drop(self, dropped):
            self.events.append("incr")

    mods = {
        "ok": types.SimpleNamespace(TaskDisabledException=Disabled,
                                    Logger=types.SimpleNamespace(get_logger=lambda n: types.SimpleNamespace(
                                        info=lambda *a, **k: None, error=lambda *a, **k: None))),
        "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
        "src.task.BaseCombatTask": types.SimpleNamespace(CharRevivedException=Revived),
        "src.task.BaseWWTask": types.SimpleNamespace(BaseWWTask=BaseWWTask),
        "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=FarmEchoTask),
    }
    for name in ("DailyTask", "ForgeryTask", "SimulationTask", "TacetTask"):
        mods[f"src.task.{name}"] = types.SimpleNamespace(**{name: _AnyMeta(name, (), {})})
    _saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    if "FarmEchoTask.incr_drop" not in ns["_applied"]:
        ns["_install_claim"]()
    check("领奖、走去结晶、读次数、开启挑战四处都换上了", all(x in ns["_applied"] for x in (
        "FarmEchoTask.handle_claim_button", "FarmEchoTask.incr_drop", "FarmEchoTask.click_configured_boss_level",
        "FarmEchoTask.click_team_challenge")))
    ns["NO_CLAIM"] = str(Path(__file__).resolve().parent / "no-such-no-claim-flag")

    CLAIM_DIALOG = ["领取奖励需消耗60点结晶波片，请确认是否领取？", "取消", "确认"]
    SETTLEMENT = ["挑战成功", "退出副本", "重新挑战"]
    PAGE = {3: ["本周剩余可收取次数：3/3_1.00", "x60_0.79"], 2: ["本周剩余可收取次数：2/3_1.00", "x60_0.79"],
            1: ["本周剩余可收取次数：1/3_1.00", "x60_0.79"], 0: ["本周剩余可收取次数：0/3_0.99", "x60_0.79"]}
    UNREAD = ["x60_0.79"]

    class _At:
        """An OCR box with a place on the 1920x1080 screen."""
        def __init__(self, name, x, y):
            self.name, self.x, self.y, self.width, self.height = name, x, y, 40, 30

        def __str__(self):
            return (f"Box(name='{self.name}', x={self.x}, y={self.y}, width={self.width}, "
                    f"height={self.height}, confidence=100)")

    def claim_screen(wave, spare, cap="240"):
        """The claim dialog over the top bar (10-12 11:44:41: backup 24 at x=1208, y=50)."""
        return [_At(str(spare), 1208, 50), _At(f"{wave}/{cap}", 1480, 50), _At("15652", 1800, 50),
                _At(CLAIM_DIALOG[0], 700, 500), _At("取消", 640, 700), _At("确认", 1280, 700)]

    FULL = claim_screen(240, 0, cap="240+")
    TOPUP = claim_screen(41, 24)

    def task(left=None, pages=(), screens=(), after=(), dialogs=(), gems=0, arena_at=None, crystal=True,
             walk_error=None, claim_up=True, boss="Weekly Challenge"):
        t = object.__new__(FarmEchoTask)
        t.events, t.logs, t.errors, t.shots = [], [], [], []
        t.entries, t.arena, t.reads_after = 0, False, 0
        t.pages, t.screens, t.after, t.dialogs = list(pages), list(screens), list(after), list(dialogs)
        t.gems, t.arena_at, t.crystal, t.walk_error = gems, arena_at, crystal, walk_error
        t.claim_up, t.f_up = claim_up, True
        t.config = {"Teleport to Boss": boss}
        t._in_realm = True
        if left is not None:
            t._ark_weekly_left = left

        def ocr(box=None, **kw):
            if box == (0.58, 0.80):
                return t.pages.pop(0) if t.pages else UNREAD
            if box == (0.20, 0.35):
                t.reads_after += 1
                return t.after.pop(0) if t.after else []
            if box == (0.0, 0.0):
                return t.screens.pop(0) if t.screens else ["某个没见过的画面"]
            return []
        t.ocr = ocr
        t.box_of_screen = lambda x, y, to_x, to_y: (x, y)
        t.height_of_screen = lambda r: r * 1080
        t.in_world = lambda: False
        t.in_team_and_world = lambda: t.arena_at is not None and t.reads_after >= t.arena_at
        t.log_info = lambda msg, notify=False: t.logs.append(msg)
        t.log_error = lambda msg, notify=False: t.errors.append((msg, notify))
        t.screenshot = lambda name: t.shots.append(name)
        t.sleep = lambda s: None
        t.wait_until = lambda cond, **kw: cond()
        t.has_claim = lambda: t.claim_up
        t.find_treasure_icon = lambda: t.crystal

        def walk():
            t.events.append("walk")
            if t.walk_error:
                raise t.walk_error
        t.walk_to_treasure = walk

        def right():
            t.events.append("confirm")
            return "confirm-btn"
        t.click_dialog_right_button = right
        t.click_dialog_left_button = lambda: t.events.append("cancel")

        def click(*a, **kw):
            t.events.append("solo" if a[:2] == (0.880, 0.911) else f"click:{a[0]}")
        t.click = click
        t.click_relative = lambda x, y, **kw: t.events.append(f"rel:{x},{y}")
        t.back = lambda after_sleep=0: t.events.append("back")
        t.send_key = lambda key, **kw: t.events.append(f"key:{key}")
        t.ensure_main = lambda time_out=30: t.events.append("main")
        t.wait_in_team_and_world = lambda time_out=10, raise_if_not_found=True, esc=False: True

        def wait_feature(feature, **kw):
            if feature == "gem_add_stamina":
                if t.gems > 0:
                    t.gems -= 1
                    return "gem"
                return None
            return True                 # team_start_challenge is there
        t.wait_feature = wait_feature

        def wait_click_ocr(match=None, **kw):
            seen = t.screens.pop(0) if t.screens else ["某个没见过的画面"]
            hit = [b for b in seen if match.search(str(b))]
            if hit:
                t.events.append(f"click:{hit[0]}")
                return hit
            return None
        t.wait_click_ocr = wait_click_ocr
        t.wait_click_feature = lambda feature, **kw: t.events.append("start")
        t.wait_click_skip_dialog_confirm = lambda *a, **kw: t.events.append("skip-confirm")
        t.find_one = lambda *a, **kw: t.dialogs.pop(0) if t.dialogs else None
        return t

    def lap(t):
        """One lap's end: the fight is over, upstream calls incr_drop. 'stop' on a deliberate stop."""
        try:
            t.incr_drop(True)
        except Disabled:
            return "stop"
        return "on"

    print("[(E) 结晶按 F→领奖弹窗点确认（不按 ESC）→波片不够动用备用体力→确认→结算页「退出副本」→回去读到 2/3]")
    t = task(left=3, pages=[PAGE[2]], screens=[TOPUP, SETTLEMENT], gems=1)
    check("没停", lap(t), "on")
    claim = t.events[:t.events.index("click:退出副本") + 1]
    check("走去结晶、按 F、确认、备用体力两下、返回、再确认、点退出副本", claim,
          ["incr", "walk", "key:f", "confirm", "rel:0.7,0.71", "rel:0.7,0.71", "back", "click:confirm-btn",
           "click:退出副本"])
    check("领奖弹窗上没按 ESC（上游那一下换成了确认）", "key:esc" in t.events, False)
    check("认出弹窗那句照旧（中继认它算打过一场）", any(m.startswith("周本领奖：认出弹窗，点确认") for m in t.logs))
    check("说了动用备用体力", "周本领奖：波片不够，动用备用体力" in t.logs)
    check("截了领奖那一刻", "weekly_claimed" in t.shots)
    check("说了已点确认（中继数点击次数）", "周本领奖：已点确认" in t.logs)
    check("结算页点了退出副本", "周本领奖：结算页点了「退出副本」" in t.logs)
    check("回读确认 3/3→2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)
    check("重进了本（选等级→单人挑战→开启挑战）", [e for e in t.events if e in ("level", "solo", "start")],
          ["level", "solo", "start"])
    check("开启挑战后什么都没确认", "skip-confirm" in t.events, False)
    check("没报错", t.errors, [])
    check("这次的读数记下当下一次的「领前」", t._ark_weekly_left, 2)

    print("\n[波片够、不弹补体力：确认一下就到结算页]")
    t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    check("没停", lap(t), "on")
    check("确认一次就退出副本", t.events[:5], ["incr", "walk", "key:f", "confirm", "click:退出副本"])
    check("没碰备用体力", [e for e in t.events if e.startswith("rel:") or e == "back"], [])

    print("\n[周一一趟三次：3/3→2/3→1/3→0/3，最后那次只读数，0/3 不进本]")
    t = task(left=3, pages=[PAGE[2], PAGE[1], PAGE[0]], screens=[FULL, SETTLEMENT] * 3)
    got = [lap(t), lap(t), lap(t)]
    check("前两圈接着打，第三圈领完停（有意跳过）", got, ["on", "on", "stop"])
    check("三次回读都对上", [m for m in t.logs if "回读确认" in m],
          ["周本领奖：回读确认领到，本周剩余 3/3→2/3", "周本领奖：回读确认领到，本周剩余 2/3→1/3",
           "周本领奖：回读确认领到，本周剩余 1/3→0/3"])
    check("开启挑战只点了两次", t.events.count("start"), 2)
    check("读到 0/3 退回主界面", t.events[-1], "main")
    check("说了已领满", "本周周本次数已领满（0/3），不进本，跳过" in t.logs)
    check("一次 ESC 都没按", "key:esc" in t.events, False)
    check("没报错", t.errors, [])

    def on_screen(t):
        t.height_of_screen = lambda r: r * 1080
        return t

    print("\n[领奖弹窗：波片 17 + 备用 24 不够 60（10-12 11:44）：先读顶栏，点取消、按波片不足跳过，不动备用体力]")
    t = on_screen(task(left=3, screens=[claim_screen(17, 24)], gems=2))
    check("跳过（结束这趟周本）", lap(t), "stop")
    check("按 F 后直接点取消", t.events[:4], ["incr", "walk", "key:f", "cancel"])
    check("没点确认、没碰备用体力", [e for e in t.events if e in ("confirm", "back") or e.startswith("rel:")], [])
    check("说了波片不足那句（中继认它是波片不足）",
          any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))
    check("没说认出弹窗点确认（中继不当它领过）", any(m.startswith("周本领奖：认出弹窗") for m in t.logs), False)
    check("留图", "weekly_short_claim" in t.shots)
    check("按跳过结束：没留失败原因", getattr(t, "_ark_failed", None), None)
    check("没当报错推送", t.errors, [])

    print("\n[领奖弹窗：波片 41 + 备用 24 够 60：照旧确认、动用备用体力一次、领到]")
    t = on_screen(task(left=3, pages=[PAGE[2]], screens=[claim_screen(41, 24), SETTLEMENT], gems=1))
    check("没停", lap(t), "on")
    check("确认后动用备用体力", t.events[3:6], ["confirm", "rel:0.7,0.71", "rel:0.7,0.71"])
    check("回读确认 3/3→2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)

    print("\n[领奖弹窗：波片 60 够：照旧确认一下就到结算页]")
    t = on_screen(task(left=3, pages=[PAGE[2]], screens=[claim_screen(60, 0), SETTLEMENT]))
    check("没停", lap(t), "on")
    check("确认一次就退出副本", t.events[:5], ["incr", "walk", "key:f", "confirm", "click:退出副本"])

    print("\n[the claim dialog's bar: 「240/240+」 (0921-weekly.log:18) reads as 240, backup 0]")
    check("240/240+", ns["_waveplates"](on_screen(task()), claim_screen(240, 0, cap="240+")), (240, 0))
    check("41/240", ns["_waveplates"](on_screen(task()), claim_screen(41, 24)), (41, 24))
    check("0/240+ with a backup of 136 (the level page, 10-05 22:17:31)",
          ns["_waveplates"](on_screen(task()), claim_screen(0, 136, cap="240+")), (0, 136))
    t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    check("240/240+: not stopped", lap(t), "on")
    check("240/240+: the two values are in the log", "周本领奖：顶栏读到波片 240/240，备用 0" in t.logs)
    check("the claim line shows the /240 token", any(m.startswith("周本领奖：认出弹窗") and "240/240+" in m for m in t.logs))

    print("\n[bar not read: no blind 确认 (10-12 11:44 spent the backup that way) - picture, phone, stop]")
    t = task(left=3, pages=[PAGE[2]], screens=[[_At(CLAIM_DIALOG[0], 700, 500)], SETTLEMENT], gems=2)
    check("stopped", lap(t), "stop")
    check("nothing confirmed, backup untouched", [e for e in t.events if e in ("confirm", "back") or e.startswith("rel:")], [])
    check("picture", "weekly_claim_bar_unread" in t.shots)
    check("pushed to the phone, as a failure", len(t.errors) == 1 and t.errors[0][1] and "顶栏的波片没读全" in t.errors[0][0])
    check("ends as failed (a reason is kept)", "顶栏的波片没读全" in (getattr(t, "_ark_failed", None) or ""))

    print("\n[顶栏读到够（41+24）、备用体力用上了仍不够（又弹补体力）：返回、点取消、按波片不足跳过，不动结晶溶剂]")
    t = task(left=3, screens=[TOPUP], gems=2)
    check("跳过（结束这趟周本）", lap(t), "stop")
    check("备用体力一轮之后返回、取消，没再确认",
          t.events[3:], ["confirm", "rel:0.7,0.71", "rel:0.7,0.71", "back", "click:confirm-btn", "back", "cancel"])
    check("说了波片不足那句（中继认它是波片不足）",
          any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))
    check("没说已点确认", "周本领奖：已点确认" in t.logs, False)
    check("留图", "weekly_short_claim" in t.shots)
    check("按跳过结束：没留失败原因", getattr(t, "_ark_failed", None), None)
    check("没当报错推送", t.errors, [])

    print("\n[10-12 15:29 / 15:31: backup 0, waveplates short -> cancelled before 确认; the top-up (solute) is never clicked]")
    t = task(left=3, screens=[claim_screen(17, 0)], gems=2)
    check("skipped as short", lap(t), "stop")
    check("no confirm, no top-up clicks", [e for e in t.events if e in ("confirm", "back") or e.startswith("rel:")], [])
    check("the shortage line", any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))

    print("\n[bar reads 240 but the game still opens the top-up dialog -> cancel, picture, stop; no top-up clicks]")
    t = task(left=3, screens=[FULL, SETTLEMENT], gems=1)
    check("stopped", lap(t), "stop")
    check("confirm, then back + cancel, no top-up clicks", t.events[3:], ["confirm", "back", "cancel"])
    check("picture of the dialog", "weekly_topup_unexpected" in t.shots)
    check("pushed, as a failure", len(t.errors) == 1 and t.errors[0][1] and "不点补充" in t.errors[0][0])
    check("not counted as clicked", "周本领奖：已点确认" in t.logs, False)

    print("\n[a claim made through upstream's own pickup (pick_f in walk_find_echo) leaves us in the world: still read back and re-entered]")
    t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    check("upstream's pick_f took the claim and clicked 退出副本", t.pick_f(), None)
    check("the claim flag is set", getattr(t, "_ark_claimed", False), True)
    t.in_world = lambda: True                    # 退出副本 put us in the open world
    check("incr_drop does not stop", lap(t), "on")
    check("read back 3/3->2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)
    check("went back in (level page)", "level" in t.events)
    check("flag cleared", t._ark_claimed, False)
    check("no second walk to a crystal", t.events.count("walk"), 0)

    print("\n[回读次数没变：这次没领到，截图报手机，停下不再进本]")
    t = task(left=2, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    check("停下", lap(t), "stop")
    check("报到手机", t.errors, [("周本领奖：回读次数没变（2/3），这次没领到", True)])
    check("留图", "weekly_claim_unchanged" in t.shots)
    check("没点上游的选等级、没点开启挑战", [e for e in t.events if e in ("level", "start")], [])

    print("\n[回读没读到：截图报手机，停下]")
    t = task(left=3, pages=[UNREAD], screens=[FULL, SETTLEMENT])
    check("停下", lap(t), "stop")
    check("报到手机", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
    check("原文进日志", any("回读时选等级页读到" in m and "x60_0.79" in m for m in t.logs))
    check("留图", "weekly_readback_unread" in t.shots)

    print("\n[重进没经过选等级页（直接落在场地里）：次数没回读，停下]")
    t = task(left=3, screens=[FULL, SETTLEMENT])
    t.arena = True
    check("停下", lap(t), "stop")
    check("报回读没读到", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
    check("回读的账清掉，下一趟不拿它比", t._ark_claim_before, None)

    print("\n[no 「退出副本」 after 确认 (10-05 10:34:50 farm 4c error): picture, phone, stop - no ESC, no re-entry]")
    t = task(left=3, screens=[FULL])
    check("stopped", lap(t), "stop")
    check("pushed with the screen's text",
          len(t.errors) == 1 and t.errors[0][1] and "没等到结算页" in t.errors[0][0] and "某个没见过的画面" in t.errors[0][0])
    check("picture", "weekly_no_settlement" in t.shots)
    check("no ESC, no back", [e for e in t.events if e in ("key:esc", "back")], [])
    check("no re-entry", t.entries, 0)
    check("ends as failed", "没等到结算页" in (getattr(t, "_ark_failed", None) or ""))

    print("\n[10-12 09:51:50: the fight check broke first and the walk to the crystal failed (WaitFailedException): picture, phone, stop]")
    # ev OK-WW-05-18-47.log:1102-1109 - 「farm echo walk_find_echo None」, 「去结晶按 F」,
    # walk_to_treasure, 09:52:20 WaitFailedException. Handing it back (a8cc86b6) let
    # upstream's next lap ESC out of the realm with the reward not taken.

    class WaitFailedException(Exception):
        """ok.WaitFailedException."""

    t = task(left=3, walk_error=WaitFailedException())
    check("stopped", lap(t), "stop")
    check("walked once, no F", [e for e in t.events if e in ("walk", "key:f")], ["walk"])
    check("pushed with the reason", len(t.errors) == 1 and t.errors[0][1]
          and "没走到结晶" in t.errors[0][0] and "WaitFailedException" in t.errors[0][0])
    check("picture", t.shots, ["weekly_walk_failed"])
    check("ends as failed", "没走到结晶" in (getattr(t, "_ark_failed", None) or ""))
    check("nothing confirmed, no ESC", [e for e in t.events if e in ("confirm", "cancel", "key:esc")], [])

    print("\n[no crystal after the lap: picture, phone, stop - no walk]")
    t = task(left=3, crystal=False)
    check("stopped", lap(t), "stop")
    check("no walk, no F", [e for e in t.events if e in ("walk", "key:f")], [])
    check("pushed with the reason", len(t.errors) == 1 and t.errors[0][1] and "没看到结晶" in t.errors[0][0])
    check("picture", t.shots, ["weekly_no_crystal"])

    print("\n[领奖钩子遇到的不是领奖弹窗（退出副本的确认框也是这个取消按钮）：照上游按 ESC，不点确认]")
    t = task(screens=[["是否退出副本？", "取消", "确认"]])
    check("返回 True（上游的语义）", t.handle_claim_button(), True)
    check("按的是 ESC，没点确认", [e for e in t.events if e in ("key:esc", "confirm")], ["key:esc"])

    print("\n[没有弹窗：什么都不点，返回 None（上游的语义）]")
    t = task(claim_up=False)
    check("返回 None", t.handle_claim_button(), None)
    check("什么都没点", t.events, [])

    print("\n[不是周本（刷声骸走的是强敌）：领奖弹窗照上游按 ESC]")
    t = task(boss="Boss Challenge", screens=[CLAIM_DIALOG])
    check("返回 True", t.handle_claim_button(), True)
    check("按的是 ESC，没点确认", [e for e in t.events if e in ("key:esc", "confirm")], ["key:esc"])

    print("\n[进本前选等级页没读到本周剩余次数：截图报手机，停下不进本]")
    t = task(pages=[UNREAD])
    try:
        t.teleport_to_configured_boss_and_prepare()
        got = "in"
    except Disabled:
        got = "stop"
    check("停下（有意跳过，不算失败）", got, "stop")
    check("报到手机、带原文", len(t.errors) == 1 and t.errors[0][1] and "x60_0.79" in t.errors[0][0])
    check("留图", "weekly_left_unread" in t.shots)
    check("没点上游的选等级、没点单人挑战", [e for e in t.events if e in ("level", "solo", "start")], [])

    print("\n[进本前读到 3/3（22:13:04）：照常进本，记下 3]")
    t = task(pages=[PAGE[3]])
    t.teleport_to_configured_boss_and_prepare()
    check("进了本", t.prepared, "realm")
    check("记下 3", t._ark_weekly_left, 3)

    print("\n[开启挑战后有对话框、字一直认不出：不点确认，截图报手机，停下]")
    t = task(dialogs=["btn"] * 6)
    try:
        t.click_team_challenge()
        got = "on"
    except Disabled:
        got = "stop"
    check("停下", got, "stop")
    check("看满了整段（6 眼）", t.reads_after, 6)
    check("没点确认也没点取消", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], [])
    check("留图", "challenge_dialog_unknown" in t.shots)
    check("报到手机", len(t.errors) == 1 and t.errors[0][1] and "认不出的对话框" in t.errors[0][0])

    print("\n[开启挑战后没有对话框、到了场地：不再看，也不点任何确认]")
    t = task(arena_at=2)
    t.click_team_challenge()
    check("看到进场就停（2 眼）", t.reads_after, 2)
    check("什么都没确认", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], [])
    check("没报错", t.errors, [])

    print("\n[开启挑战后一直加载中、没有对话框：看满整段，不点确认，接着走]")
    t = task()
    t.click_team_challenge()
    check("看满 6 眼", t.reads_after, 6)
    check("什么都没确认", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], [])

    print("\n[2026-11-03 账本 #135：Boss 转阶段 walk_find_echo 检测到还在战斗（_in_combat=True）返回 False：接着打完再领结晶，不误报没看到结晶]")
    t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    t._in_combat = True
    def _resume_combat(**kw):
        t.events.append("resume-combat")
        t._in_combat = False
    t.combat_once = _resume_combat
    t.pick_echo = lambda: False
    t.walk_find_echo = lambda: (t.events.append("pick-echo"), True)[1]
    t.incr_drop(False)
    check("先接着打完再捡声骸再领奖", t.events[:7], ["incr", "resume-combat", "pick-echo", "incr", "walk", "key:f", "confirm"])
    check("领完剩余次数变 2", t._ark_weekly_left, 2)
    check("BaseWWTask.tr 返回英文原句（不让 zh_CN 破坏 AUTO-MAS 完成判定）",
          t.tr("Daily Task Completed"), "Daily Task Completed")

    print("\n[echo farm: the pickup toast's main stat, one log line per echo (2026-11-20)]")
    echo_stat = ns["echo_stat"]
    check("a clean read", echo_stat("生命"), "生命")
    check("the icon read as a letter is dropped", echo_stat("X治疗效果加成"), "治疗效果加成")
    check("暴击伤害 is not 暴击", (echo_stat("暴击伤害"), echo_stat("暴击")), ("暴击伤害", "暴击"))
    check("a partial read is unread, never a guess", (echo_stat("治疗效果"), echo_stat("治疗"), echo_stat("")), (None, None, None))
    check("two stats in one read are unread", echo_stat("生命 攻击"), None)
    _flag = tmpdir() / "farm.no-claim"
    _flag.write_text("", encoding="utf-8")

    def toast_task(reads, boss="Weekly Challenge"):
        tt = task(boss=boss)
        tt.toast = list(reads)
        tt.frames = 0
        tt.slept = []
        tt.sleep = lambda s: tt.slept.append(s)

        def nf():
            tt.frames += 1
        tt.next_frame = nf

        def ocr(box=None, **kw):
            if box == ns["ECHO_STAT_BOX"][:2]:
                return tt.toast.pop(0) if tt.toast else []
            return []
        tt.ocr = ocr
        return tt

    ns["NO_CLAIM"] = str(_flag)
    tt = toast_task([[], ["治疗效果加成"]])
    tt.incr_drop(True)
    drop = [m for m in tt.logs if m.startswith("刷声骸掉落：")]
    check("farming, an echo picked up: one line with the stat", (len(drop), "stat=治疗效果加成" in drop[0]), (1, True))
    check("read on the second look, from a fresh frame each time", (tt.frames, tt.slept[:2]), (2, [1.0, 0.3]))
    check("upstream's count still runs", "incr" in tt.events, True)
    tt = toast_task([])
    tt.incr_drop(True)
    drop = [m for m in tt.logs if m.startswith("刷声骸掉落：")]
    check("no toast read in six looks: unknown, not a guess", (len(drop), "stat=unknown" in drop[0], "looks=6" in drop[0]), (1, True, True))
    tt = toast_task([["治疗效果"]] * 6)
    tt.incr_drop(True)
    check("a cut-off stat stays unknown", "stat=unknown" in [m for m in tt.logs if m.startswith("刷声骸掉落：")][0], True)
    tt = toast_task([["生命"]])
    tt.incr_drop(False)
    check("nothing picked up: no toast read, no line", (tt.frames, [m for m in tt.logs if m.startswith("刷声骸掉落：")]), (0, []))
    tt = toast_task([["生命"]], boss="Boss Challenge")
    tt.incr_drop(True)
    check("an overworld boss farm counts too", "stat=生命" in " ".join(tt.logs), True)

    def boom(box=None, **kw):
        raise RuntimeError("ocr died")
    tt = toast_task([])
    tt.ocr = boom
    tt.incr_drop(True)
    check("an OCR failure is logged as unknown and the lap goes on",
          ("stat=unknown" in " ".join(tt.logs), "incr" in tt.events), (True, True))
    tt = toast_task([])

    def stop_now(s):
        raise Disabled()
    tt.sleep = stop_now
    try:
        tt.incr_drop(True)
        stopped = False
    except Disabled:
        stopped = True
    check("a deliberate stop goes up untouched", stopped, True)
    ns["NO_CLAIM"] = str(Path(__file__).resolve().parent / "no-such-no-claim-flag")
    tt = toast_task([["生命"]])
    tt.incr_drop(True)
    check("not farming (the daily weekly claim): no toast read", (tt.frames, [m for m in tt.logs if m.startswith("刷声骸掉落：")]), (0, []))

    # The coverage driver runs every test in one process: leave sys.modules as found.
    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def _part_okww_daily_chests():
    """OK-WW's daily activity chests: every chest up to the points is claimed, and checked."""
    import types

    import numpy as np
    from PIL import Image

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    from ark_relay.features import okww_overlay
    from ark_relay.features import outcome

    ns = {"__name__": "ark_overrides_test"}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)

    ROW = np.array(Image.open(fx_dir(HERE, "fixtures") / "ww-daily-80-1010-row.png").convert("RGB"))
    H, W = ROW.shape[:2]
    # The tier labels' glyph boxes in the fixture (x0, y0, x1, y1), measured on the picture.
    GLYPHS = {20: (592, 93, 615, 112), 40: (884, 93, 907, 112), 60: (1177, 93, 1201, 112),
              80: (1471, 93, 1493, 112), 100: (1749, 93, 1787, 112)}

    def box(name, x0, y0, x1, y1, pad=0):
        return types.SimpleNamespace(name=name, x=x0 - pad, y=y0 - pad, width=x1 - x0 + 1 + 2 * pad,
                                     height=y1 - y0 + 1 + 2 * pad)

    LABELS = [box(str(t), *g, pad=4) for t, g in GLYPHS.items()]
    # What else the OCR reads as a tier number: the big points 「80」 at the left, above the row,
    # and a quest row's 「20」 further up.
    DECOYS = [box("80", 225, 15, 280, 65), box("20", 180, 2, 205, 14)]

    print("[the row: labels, step, where the chests are]")
    labels = ns["tier_labels"](LABELS + DECOYS, H)
    check("five tiers, decoys dropped", sorted(labels), [20, 40, 60, 80, 100])
    check("the 80 kept is the row's", labels[80][1] > 90, True)
    step = ns["tier_step"](labels)
    check("one tier step ~ 293 px", abs(step - 293) <= 1, True)
    chest = {t: ns["chest_at"](labels, step, t) for t in labels}
    check("the 20 chest is the circle at (663, 75), within a pixel",
          abs(chest[20][0] - 663) <= 1 and abs(chest[20][1] - 75) <= 1, True)

    print("\n[his screenshot: 20-80 claimed, 100 not]")
    gray = ROW.mean(axis=2)
    scores = ns["tier_scores"](gray, labels, step)
    print("    scores:", scores)
    check("20-80 read as claimed", all(scores[t] >= ns["_CHECKED_MIN"] for t in (20, 40, 60, 80)), True)
    check("100 reads as not claimed", scores[100] < ns["_CHECKED_MIN"], True)
    small = np.array(Image.fromarray(ROW).resize((W * 3 // 5, H * 3 // 5))).mean(axis=2)
    lab_s = {t: (x * 0.6, y * 0.6) for t, (x, y) in labels.items()}
    sc_s = ns["tier_scores"](small, lab_s, ns["tier_step"](lab_s))
    check("the same at 0.6 of the size", [sc_s[t] >= ns["_CHECKED_MIN"] for t in (20, 40, 60, 80, 100)],
          [True, True, True, True, False])

    # The morning's state: the 100 chest's unclaimed picture over 20-80.
    R = 46
    cx100, cy100 = (round(v) for v in chest[100])
    UNCLAIMED = ROW[cy100 - R:cy100 + R, cx100 - R:cx100 + R].copy()
    CLAIMED = {t: ROW[round(chest[t][1]) - R:round(chest[t][1]) + R, round(chest[t][0]) - R:round(chest[t][0]) + R].copy()
               for t in (20, 40, 60, 80)}

    def morning():
        img = ROW.copy()
        for t in (20, 40, 60, 80):
            x, y = (round(v) for v in chest[t])
            img[y - R:y + R, x - R:x + R] = UNCLAIMED
        return img

    class Game:
        """The dailies page: OCR answers, clicks claim a chest (when the game takes them)."""

        def __init__(self, frame, points="80", takes=True, ocr_labels=None, chests=None, points_boxes=None):
            self.frame, self.points, self.takes = frame, points, takes
            self.points_boxes = points_boxes
            self.ocr_labels = LABELS + DECOYS if ocr_labels is None else ocr_labels
            self.chests = chest if chests is None else chests
            self.clicks, self.logs, self.keys = [], [], []

        def next_frame(self):
            return self.frame

        def ocr(self, *a, match=None, **k):
            if match is not None and "100" in match.pattern:
                return self.ocr_labels
            if self.points_boxes is not None:
                return self.points_boxes
            return [box(self.points, 225, 15, 280, 65)] if self.points else []

        def click_relative(self, rx, ry, **k):
            x, y = rx * self.frame.shape[1], ry * self.frame.shape[0]
            for t, (cx, cy) in self.chests.items():
                if abs(x - cx) < 30 and abs(y - cy) < 30:
                    self.clicks.append(t)
                    if self.takes and t in CLAIMED:
                        ix, iy = round(cx), round(cy)
                        self.frame = self.frame.copy()
                        self.frame[iy - R:iy + R, ix - R:ix + R] = CLAIMED[t]
                    return
            self.clicks.append(("miss", round(x), round(y)))

        def log_info(self, msg, **k):
            self.logs.append(msg)

        def send_key(self, key, **k):
            self.keys.append(key)

        def openF2Book(self, *a):  # noqa: N802
            self.keys.append("book")

        def click(self, *a, **k):
            pass

        def screenshot(self, name):
            self.logs.append(f"[shot {name}]")

    print("\n[the morning: 80 points, 20-80 not claimed -> each clicked, each checked]")
    g = Game(morning())
    check("before: 20-80 read as not claimed",
          [v < ns["_CHECKED_MIN"] for t, v in ns["tier_scores"](g.frame.mean(axis=2), labels, step).items() if t != 100],
          [True] * 4)
    ns["_claim_tiers"](g)
    check("clicked 20, 40, 60, 80 - not 100", g.clicks, [20, 40, 60, 80])
    check("the points line for the relay", "活跃奖励：活跃度 80" in g.logs, True)
    check("checked: all claimed", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)
    check("no ESC needed", g.keys, [])

    print("\n[the game does not take the clicks -> tried twice, then said, with a screenshot]")
    g = Game(morning(), takes=False)
    ns["_claim_tiers"](g)
    check("each chest tried twice", sorted(g.clicks), sorted([20, 40, 60, 80] * 2))
    failed = [m for m in g.logs if m.startswith("活跃奖励没领到：")]
    check("one 「没领到」 line naming 20-80", bool(failed) and "20、40、60、80 档点了没领到" in failed[0], True)
    check("screenshot taken", "[shot daily_reward_unclaimed]" in g.logs, True)

    print("\n[already claimed (his screenshot) -> nothing clicked, checked]")
    g = Game(ROW.copy())
    ns["_claim_tiers"](g)
    check("nothing clicked", g.clicks, [])
    check("checked", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)

    print("\n[points not read -> said, nothing clicked]")
    g = Game(morning(), points="")
    ns["_claim_tiers"](g)
    check("nothing clicked", g.clicks, [])
    check("said", any(m.startswith("活跃奖励没领到：活跃度的分数没读到") for m in g.logs), True)

    print("\n[10-11 09:29: all five claimed, the reward preview over the 100 chest -> checked, nothing clicked]")
    ROW11 = np.array(Image.open(fx_dir(HERE, "fixtures") / "ww-daily-140-1011-row.png").convert("RGB"))
    # Glyph boxes of the tier labels in that picture (x0, y0, x1, y1), and where each tick is
    # (the best match of the tick, searched over +-40 px): 「100」 is 45 px wide, the rest 29-31.
    GLYPHS11 = {20: (683, 174, 711, 193), 40: (937, 174, 967, 193), 60: (1193, 174, 1222, 193),
                80: (1449, 174, 1478, 193), 100: (1690, 174, 1734, 193)}
    TICKS11 = {80: (1520, 159), 100: (1776, 159)}
    LABELS11 = [box(str(t), *g, pad=4) for t, g in GLYPHS11.items()]
    lab11 = ns["tier_labels"](LABELS11, ROW11.shape[0])
    step11 = ns["tier_step"](lab11)
    ch11 = {t: ns["chest_at"](lab11, step11, t) for t in lab11}
    check("80 and 100 looked for within 5 px of their ticks",
          [abs(ch11[t][0] - x) <= 5 and abs(ch11[t][1] - y) <= 5 for t, (x, y) in TICKS11.items()], [True, True])
    gray11 = ROW11.mean(axis=2)
    sc11 = ns["tier_scores"](gray11, lab11, step11)
    print("    scores:", sc11)
    check("all five read as claimed, preview and all", [sc11[t] >= ns["_CHECKED_MIN"] for t in ns["DAILY_TIERS"]],
          [True] * 5)
    # The cause, kept on record: placed by the box centre (the code before), 100 misses its tick.
    by_centre = {int(b.name): (b.x + b.width / 2, b.y + b.height / 2) for b in LABELS11}
    old = ns["tier_scores"](gray11, by_centre, ns["tier_step"](by_centre))
    check("by the box centre the 100 tick is missed (the false alarm)",
          [old[t] >= ns["_CHECKED_MIN"] for t in ns["DAILY_TIERS"]], [True, True, True, True, False])
    g = Game(ROW11.copy(), points="140", takes=False, ocr_labels=LABELS11, chests=ch11)
    ns["_claim_tiers"](g)
    check("nothing clicked", g.clicks, [])
    check("checked: 领完核对通过", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)
    check("no 「没领到」", any(m.startswith("活跃奖励没领到") for m in g.logs), False)

    print("\n[the row is not found again after a click -> its own failure, no verdict from the frame before the click]")

    class LostRow(Game):
        def ocr(self, *a, match=None, **k):
            if match is not None and "100" in match.pattern and self.clicks:
                return []
            return super().ocr(*a, match=match, **k)

    g = LostRow(morning())
    ns["_claim_tiers"](g)
    check("stopped after the first click", g.clicks, [20])
    failed = [m for m in g.logs if m.startswith("活跃奖励没领到：")]
    check("one line: the row was lost after clicking 20", len(failed) == 1 and "点了 20 档宝箱后那一排宝箱认不出来了" in failed[0], True)
    check("not 「点了没领到」 for chests the game may have taken", any("点了没领到" in m for m in g.logs), False)
    check("screenshot daily_reward_row_lost", "[shot daily_reward_row_lost]" in g.logs, True)

    print("\n[a due tier whose label OCR missed was never clicked -> 「没点」, not 「点了没领到」]")
    g = Game(morning(), ocr_labels=[b for b in LABELS if b.name != "40"] + DECOYS)
    ns["_claim_tiers"](g)
    check("20, 60, 80 clicked; 40 not", g.clicks, [20, 60, 80])
    failed = [m for m in g.logs if m.startswith("活跃奖励没领到：")]
    check("40 said as not clicked", len(failed) == 1 and "40 档的数字没认出来，没点" in failed[0], True)
    check("40 not said as clicked", "40 档点了没领到" in failed[0] if failed else True, False)

    print("\n[points read too low: a claimed tick above them -> failure, not 「领完核对通过」]")
    g = Game(ROW.copy(), points="40")
    ns["_claim_tiers"](g)
    check("nothing clicked (20 and 40 already claimed)", g.clicks, [])
    failed = [m for m in g.logs if m.startswith("活跃奖励没领到：")]
    check("said: 60 and 80 claimed above 40", len(failed) == 1 and "活跃度读成 40，可 60、80 档已显示领过" in failed[0], True)
    check("no 「领完核对通过」", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), False)
    g = Game(ROW.copy(), points="80")
    ns["_claim_tiers"](g)
    check("the tier at the points read, claimed, is fine", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)

    print("\n[11-17 09:31 (#181): PP-OCRv6 reads quest-row scraps above the big number -> the big number wins]")
    # As the points box came back after OK-WW v3.8.3: the compass icon's edge 「4」 and the
    # clipped reward 「+40」 of the last quest row first, a quest row's 「20」, then the total.
    NOISE = [box("4", 195, 2, 210, 16), box("+40", 180, 2, 215, 14), box("20", 180, 4, 205, 16),
             box("140", 225, 15, 295, 65)]
    g = Game(morning(), points_boxes=NOISE)
    check("_read_points: 140, not 4, 40 or 20", ns["_read_points"](g), 140)
    ns["_claim_tiers"](g)
    check("the points line says 140", "活跃奖励：活跃度 140" in g.logs, True)
    check("all five chests clicked", sorted(set(g.clicks)), [20, 40, 60, 80, 100])
    check("no 「活跃度 4」 line", any("活跃度 4，" in m or m == "活跃奖励：活跃度 4" for m in g.logs), False)
    for label, boxes, want in (
            ("only the scraps (4, +40, 1/4): unread, not 4", [box("4", 195, 2, 210, 16), box("+40", 180, 2, 215, 14),
                                                             box("1/4", 180, 2, 215, 14)], None),
            ("「+20」 is a quest reward, not 20 points", [box("+20", 180, 2, 215, 14)], None),
            ("not a multiple of 10 (14 of a clipped 140): unread", [box("14", 225, 15, 260, 65)], None),
            ("0 points is a reading", [box("0", 225, 15, 250, 65)], 0),
            ("the same height: the lower one", [box("20", 180, 2, 205, 52), box("60", 225, 15, 280, 65)], 60),
            ("the order OCR gives them in does not matter", NOISE[::-1], 140),
            ("nothing read", [], None)):
        check(f"_read_points: {label}", ns["_read_points"](Game(morning(), points_boxes=boxes)), want)
    g = Game(morning(), points_boxes=NOISE[:3])
    ns["_claim_tiers"](g)
    check("the 11-17 boxes without the total: only the quest row's 20 is left -> 20 clicked, nothing above it",
          sorted(set(g.clicks)), [20])

    print("\n[short of 100 and nothing wrong with the chests -> the page is kept as a screenshot]")
    g = Game(ROW.copy(), points="80")
    ns["_claim_tiers"](g)
    check("80 points, checked: screenshot daily_reward_short", "[shot daily_reward_short]" in g.logs, True)
    check("...and still 「领完核对通过」", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)
    g = Game(ROW11.copy(), points="140", takes=False, ocr_labels=LABELS11, chests=ch11)
    ns["_claim_tiers"](g)
    check("140 points, all claimed: no screenshot", [m for m in g.logs if m.startswith("[shot ")], [])
    g = Game(ROW.copy(), points="40")
    ns["_claim_tiers"](g)
    check("a failure keeps its own screenshot only", [m for m in g.logs if m.startswith("[shot ")],
          ["[shot daily_reward_unclaimed]"])

    print("\n[the relay: the overlay's lines -> items undone (pushed as 「这一轮没干完」)]")
    LOG_OK = "活跃奖励：活跃度 80\n活跃奖励：领完核对通过（活跃度 80，已领 20、40、60、80）\nDaily Task Completed"
    got = {c.label: (c.ok, c.detail) for c in outcome.daily_reward_checks(LOG_OK)}
    check("claimed: green", got.get("每日活跃奖励领到了"), (True, ""))
    check("80 points: red, says how many", got.get("每日活跃满 100"), (False, "今天活跃 80 分，没满 100"))
    LOG_BAD = "活跃奖励：活跃度 80\n活跃奖励没领到：20、40、60、80 档点了没领到（活跃度 80）\nDaily Task Completed"
    got = {c.label: (c.ok, c.detail) for c in outcome.daily_reward_checks(LOG_BAD)}
    check("not claimed: red, says which", got.get("每日活跃奖励领到了"), (False, "20、40、60、80 档点了没领到（活跃度 80）"))
    LOG_FULL = "活跃奖励：活跃度 100\n活跃奖励：领完核对通过（…）"
    check("100 points: both green", [c.ok for c in outcome.daily_reward_checks(LOG_FULL)], [True, True])
    LOG_UP = "活跃奖励：没有核对，上游领奖正文变了（现在 abc，我们照着 2b4977b62f7c 抄的），照上游点 100 档"
    check("upstream changed: red", [(c.label, c.ok) for c in outcome.daily_reward_checks(LOG_UP)],
          [("每日活跃奖励领到了", False)])
    check("an old log says nothing new", outcome.daily_reward_checks("Daily Task Completed"), [])


def _part_okww_farm_hook():  # noqa: C901
    """Daily task: additional tasks first, the stamina farm to empty, one settlement shot."""
    import os
    import re
    import types

    from ark_relay.features import okww_overlay

    REPLAY = fx_dir(Path(__file__), "replay") / "2026-09-07" / "wuwa"

    def logged(path, lineno, pattern):
        """The integer `pattern` captures on line `lineno` of a replay log (1-based)."""
        # Bytes, not read_text: the logs mix CRLF with bare CR, and universal newlines
        # would count the bare CRs as lines and shift every number grep -n gives.
        line = path.read_bytes().decode("utf-8").split("\n")[lineno - 1].rstrip("\r")
        m = re.search(pattern, line)
        assert m, f"{path.name}:{lineno} no longer reads {pattern!r}: {line}"
        return int(m.group(1))

    # Real numbers. OK-WW-07-27-50.log:410-411 read the daily after the farm had spent
    # 180 (the old copy farmed on anyway: :419-420 read 75 + 26 and went in);
    # OK-WW-06-08-44.log:131 read 120 earlier that morning.
    DAY = REPLAY / "OK-WW-07-27-50.log"
    USED_FULL = logged(DAY, 410, r"DailyTask:info_set current daily progress (\d+)$")
    POINTS = logged(DAY, 411, r"DailyTask:info_set total daily points (\d+)$")
    CURRENT = logged(DAY, 419, r"TacetTask:info_set current_stamina (\d+)$")
    BACK_UP = logged(DAY, 420, r"TacetTask:info_set back_up_stamina (\d+)$")
    USED_PART = logged(REPLAY / "OK-WW-06-08-44.log", 131, r"current daily progress (\d+)$")

    class Disabled(Exception):
        """ok.TaskDisabledException."""

    class Revived(Exception):
        """src.task.BaseCombatTask.CharRevivedException."""

    class _Any(type):
        """A stand-in upstream class: any method the overlay reads exists and does nothing."""
        def __getattr__(cls, name):
            if name.startswith("__"):
                raise AttributeError(name)

            def anything(self, *a, **kw):
                return None
            return anything

    number_re = re.compile(r"^(\d+)$")
    stamina_re = re.compile(r"^(\d+)/(\d+)$")
    EV = []          # one call order across every task object

    class Box:
        def __init__(self, name, x=0):
            self.name, self.x = name, x

    class BaseWWTask(metaclass=_Any):
        # Upstream v3.7.3 BaseWWTask.py:409-424, verbatim: the overlay replaces it only
        # while its source still hashes to the pin (8ba6c1344ff8).
        def get_stamina(self):
            boxes = self.wait_ocr(0.49, 0.0, 0.92, 0.10, raise_if_not_found=False,
                                  match=[number_re, stamina_re])
            if not boxes:
                self.screenshot('stamina_error')
                return -1, -1, -1
            current = 0
            back_up = 0
            for box in boxes:
                if match := stamina_re.search(box.name):
                    current = int(match.group(1))
                elif match := number_re.search(box.name):
                    back_up = int(match.group(1))
            self.info_set('current_stamina', current)
            self.info_set('back_up_stamina', back_up)
            return current, back_up, current + back_up

    class TacetTask(BaseWWTask):
        def farm_tacet(self, daily=False, used_stamina=0, config=None, max_recovery_retries=3):
            # TacetTask.py:48-55: must_use is how much the daily step insists on spending.
            must_use = 180 - used_stamina if daily else 0
            EV.append(("farm_tacet", must_use, config))
            if self.farm_error:
                raise self.farm_error

        def use_stamina(self, once, must_use=0):
            # Upstream reads the stamina inside the reward dialog; the overlay's
            # get_stamina keys on this caller's name.
            self.read = self.get_stamina()
            return self.result

    class ForgeryTask(BaseWWTask):
        def farm_forgery(self, daily=False, used_stamina=0, config=None):
            EV.append(("farm_forgery", 180 - used_stamina if daily else 0, config))

    class SimulationTask(BaseWWTask):
        def farm_simulation(self, daily=False, used_stamina=0, config=None):
            EV.append(("farm_simulation", 180 - used_stamina if daily else 0, config))

    class DailyTask(BaseWWTask):
        def run(self):
            # Upstream v3.7.3 DailyTask.py:77-136, the calls in order (validation, login
            # and the nightmare nest left out).
            used_stamina, daily_reward_ready = self.open_daily()
            need_stamina = not daily_reward_ready and used_stamina < 180
            if need_stamina:
                target = self.config.get('Which to Farm', self.support_tasks[0])
                if target == self.support_tasks[0]:
                    self.get_task_by_class(TacetTask).farm_tacet(daily=True, used_stamina=used_stamina,
                                                                 config=self.config)
                elif target == self.support_tasks[1]:
                    self.get_task_by_class(ForgeryTask).farm_forgery(daily=True, used_stamina=used_stamina,
                                                                     config=self.config)
                else:
                    self.get_task_by_class(SimulationTask).farm_simulation(daily=True, used_stamina=used_stamina,
                                                                           config=self.config)
                self.sleep(4)
            self.claim_daily()
            self.claim_mail()
            self.sleep(1)
            self.claim_battle_pass()
            self.run_additional_tasks()
            self.log_info('Daily Task Completed', notify=True)

        def open_daily(self):
            EV.append("open_daily")
            return self.used, self.points >= 100

        def run_additional_tasks(self):
            EV.append("additional")
            if self.additional_error:
                raise self.additional_error

        def claim_daily(self):
            EV.append("claim_daily")

        def claim_mail(self):
            EV.append("claim_mail")

        def claim_battle_pass(self):
            EV.append("claim_battle_pass")

    # get_total_daily_points is replaced only while upstream's body hashes to the pin, so the
    # stand-in carries the installed v3.7.14-beta.2 body, from a file (inspect.getsource).
    import ast
    UP_DAILY = (fx_dir(Path(__file__), "gamesim") / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task"
                / "DailyTask.py.txt").read_text(encoding="utf-8")
    _fn = next(x for c in ast.parse(UP_DAILY).body if isinstance(c, ast.ClassDef) and c.name == "DailyTask"
               for x in c.body if isinstance(x, ast.FunctionDef) and x.name == "get_total_daily_points")
    _up_file = tmpdir() / "_upstream_daily_points.py"
    _up_file.write_text("import re\n\nnumber_re = re.compile(r'(\\d+)')\n\n\nclass DailyTask:\n"
                        + "".join(UP_DAILY.splitlines(keepends=True)[_fn.lineno - 1:_fn.end_lineno]), encoding="utf-8")
    _scope = {}
    exec(compile(_up_file.read_text(encoding="utf-8"), str(_up_file), "exec"), _scope)
    UPSTREAM_POINTS = _scope["DailyTask"].get_total_daily_points
    DailyTask.get_total_daily_points = UPSTREAM_POINTS

    mods = {
        "ok": types.SimpleNamespace(TaskDisabledException=Disabled,
                                    Logger=types.SimpleNamespace(get_logger=lambda n: types.SimpleNamespace(
                                        info=lambda *a, **k: None, error=lambda *a, **k: None))),
        "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
        "src.task.BaseCombatTask": types.SimpleNamespace(CharRevivedException=Revived),
        "src.task.BaseWWTask": types.SimpleNamespace(BaseWWTask=BaseWWTask),
        "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=_Any("FarmEchoTask", (), {})),
        "src.task.DailyTask": types.SimpleNamespace(DailyTask=DailyTask),
        "src.task.TacetTask": types.SimpleNamespace(TacetTask=TacetTask),
        "src.task.ForgeryTask": types.SimpleNamespace(ForgeryTask=ForgeryTask),
        "src.task.SimulationTask": types.SimpleNamespace(SimulationTask=SimulationTask),
    }
    _saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    print("[绑定都换上了]")
    for b in ("DailyTask.run", "DailyTask.open_daily", "DailyTask.run_additional_tasks", "DailyTask.claim_daily",
              "TacetTask.farm_tacet", "ForgeryTask.farm_forgery", "SimulationTask.farm_simulation",
              "TacetTask.use_stamina", "BaseWWTask.get_stamina", "DailyTask.get_total_daily_points"):
        check(f"{b} 已换上", b in ns["_applied"])
    check("get_total_daily_points 不在没贴上的里面",
          [s for s in ns["_skipped"] if s["what"] == "DailyTask.get_total_daily_points"], [])

    print("\n[11-17 (#181) get_total_daily_points：杂字在前、大号分数在后，读大号的]")

    def pbox(name, x0, y0, x1, y1):
        return types.SimpleNamespace(name=name, x=x0, y=y0, width=x1 - x0 + 1, height=y1 - y0 + 1)

    def points_task(boxes):
        t = types.SimpleNamespace(info={}, asked=[])
        t.info_set = lambda k, v: t.info.__setitem__(k, v)
        t.ocr = lambda *a, **k: (t.asked.append(a), boxes)[1]
        return t

    NOISE = [pbox("4", 195, 2, 210, 16), pbox("+40", 180, 2, 215, 14), pbox("20", 180, 4, 205, 16),
             pbox("140", 225, 15, 295, 65)]
    t = points_task(NOISE)
    check("上游原来的写法读成 4（就是 11-17 那条 total daily points 4）", (UPSTREAM_POINTS(t), t.info),
          (4, {"total daily points": 4}))
    t = points_task(NOISE)
    check("换上的读成 140", DailyTask.get_total_daily_points(t), 140)
    check("写进 total daily points", t.info, {"total daily points": 140})
    check("读的还是上游那个框", t.asked, [(0.19, 0.8, 0.30, 0.93)])
    for label, boxes in (("什么都没读到", []), ("只有杂字", NOISE[:2])):
        t = points_task(boxes)
        check(f"{label}：0 分，也写进去", (DailyTask.get_total_daily_points(t), t.info), (0, {"total daily points": 0}))

    tmp = str(tmpdir("ark-farm-hook-"))
    no_farm = os.path.join(tmp, "no-stamina-farm.flag")
    ns["NO_STAMINA_FLAG"] = no_farm
    SUPPORT = ["Tacet Suppression", "Forgery Challenge", "Simulation Challenge"]

    def wire(t):
        t.logs, t.shots, t.sleeps, t.info = [], [], [], {}
        t.log_info = lambda msg, notify=False: t.logs.append(msg)
        t.log_error = lambda msg, exception=None: t.logs.append(msg)
        t.screenshot = lambda name: t.shots.append(name)
        t.sleep = lambda s: t.sleeps.append(s)
        t.info_set = lambda k, v: t.info.__setitem__(k, v)
        t.ensure_main = lambda time_out=30: EV.append("ensure_main")
        return t

    def daily(used, points=POINTS, target=SUPPORT[0], additional_error=None, farm_error=None):
        EV.clear()
        farms = {c: wire(object.__new__(c)) for c in (TacetTask, ForgeryTask, SimulationTask)}
        farms[TacetTask].farm_error = farm_error
        d = wire(object.__new__(DailyTask))
        d.used, d.points, d.additional_error = used, points, additional_error
        d.config = {"Which to Farm": target}
        d.support_tasks = SUPPORT
        d.get_task_by_class = lambda cls: farms[cls]
        d.farms = farms
        return d

    def farm_calls():
        return [e for e in EV if isinstance(e, tuple)]

    # ---------------------------------------------------------------------------
    print(f"\n[附加任务（周本）排在读日常之前；尾巴上那次是空操作。已用 {USED_PART}/180]")
    d = daily(USED_PART)
    d.run()
    check("顺序：附加任务 → 读日常 → 刷体力 → 领日常", EV,
          ["additional", "open_daily", ("farm_tacet", 0, d.config), "claim_daily", "claim_mail",
           "claim_battle_pass"])
    check("附加任务只跑了一次（上游尾巴那次没再跑）", EV.count("additional"), 1)
    check("刷体力丢掉了 daily=/used_stamina=：must_use 0，刷到空", farm_calls()[0][1], 0)
    check("上游自己刷了，就不补刷", any("上游这趟不刷体力" in m for m in d.logs), False)
    check("上游读到的数留着", getattr(d, "_ark_daily_read", None), (USED_PART, False))

    print("\n[同一个实例跑第二趟：附加任务照样先跑]")
    d.run()
    check("第二趟也有附加任务", EV.count("additional"), 2)
    check("第二趟附加任务仍在读日常之前", EV.index("additional", 6) < EV.index("open_daily", 6))

    print("\n[附加任务出错不拖垮当趟日常]")
    d = daily(USED_PART, additional_error=RuntimeError("Teleport to boss failed"))
    d.run()
    check("记了错", any("附加任务出错，不拖垮当趟日常" in m for m in d.logs))
    check("留了图", d.shots, ["additional_tasks_error"])
    check("日常照跑：刷体力、领日常都在", farm_calls() != [] and "claim_daily" in EV)
    check("尾巴上没有再跑一次", EV.count("additional"), 1)

    print("\n[a TaskDisabledException (OK-WW's stop) from the additional tasks ends the daily, as upstream does]")
    d = daily(USED_PART, additional_error=Disabled())
    try:
        d.run()
        got = "ran on"
    except Disabled:
        got = "stopped"
    check("goes up, not swallowed", got, "stopped")
    check("not logged as an additional-task error", any("附加任务出错" in m for m in d.logs), False)
    check("the daily did not carry on", "claim_daily" in EV, False)

    # ---------------------------------------------------------------------------
    print(f"\n[周本花掉 {USED_FULL}：上游的闸门关了，剩下的 {CURRENT} + {BACK_UP} 照样刷掉]")
    d = daily(USED_FULL)
    d.run()
    check(f"读到已用 {USED_FULL}/180、活跃度 {POINTS}（OK-WW-07-27-50.log:410-411）",
          getattr(d, "_ark_daily_read", None), (USED_FULL, False))
    check("补刷了一次无音区，must_use 0", farm_calls(), [("farm_tacet", 0, d.config)])
    check("补刷在领日常之前", EV.index(("farm_tacet", 0, d.config)) < EV.index("claim_daily"))
    check("说了为什么补刷", any(f"上游这趟不刷体力（已用 {USED_FULL}/180" in m for m in d.logs))
    check("补刷后照上游那样等 4 秒", 4 in d.sleeps)
    check("「Daily Task Completed」在补刷之后（中继拿它当收尾）",
          d.logs.index("Daily Task Completed") > next(i for i, m in enumerate(d.logs) if "上游这趟不刷体力" in m))

    print("\n[活跃度已满 100：上游也不刷，照样补刷]")
    d = daily(0, points=100)
    d.run()
    check("补刷了一次", farm_calls(), [("farm_tacet", 0, d.config)])
    check("只刷了一次", len(farm_calls()), 1)

    print("\n[凝素领域 / 模拟领域：上游刷时丢参数，上游不刷时补刷的是同一个]")
    for target, name in ((SUPPORT[1], "farm_forgery"), (SUPPORT[2], "farm_simulation")):
        d = daily(USED_PART, target=target)
        d.run()
        check(f"{name}：上游刷，must_use 0", farm_calls(), [(name, 0, d.config)])
        d = daily(USED_FULL, target=target)
        d.run()
        check(f"{name}：上游不刷，补刷的也是它", farm_calls(), [(name, 0, d.config)])

    print("\n[补刷出错：记一笔、回主界面，日常奖励照领]")
    d = daily(USED_FULL, farm_error=RuntimeError("can't find gray_book_boss"))
    d.run()
    check("记了错", any("补刷体力出错，照常领日常奖励" in m for m in d.logs))
    check("留了图", d.shots, ["leftover_farm_error"])
    check("回了主界面再领", EV.index("ensure_main") < EV.index("claim_daily"))
    check("日常奖励照领", "claim_daily" in EV)

    print("\n[补刷时主动停（TaskDisabledException）照原样往上抛]")
    d = daily(USED_FULL, farm_error=Disabled())
    try:
        d.run()
        raised = False
    except Disabled:
        raised = True
    check("往上抛", raised)
    check("没领日常", "claim_daily" in EV, False)

    print("\n[标记文件在：三种刷体力都不花波片，补刷那条也不花]")
    Path(no_farm).write_text("")
    for used in (USED_PART, USED_FULL):
        d = daily(used)
        d.run()
        farm = d.farms[TacetTask]
        check(f"已用 {used}：一次都没进本", farm_calls(), [])
        check(f"已用 {used}：说了刷体力已禁用", any("刷体力已禁用（标记文件在）" in m for m in farm.logs))
        check(f"used {used}: the flag line once, not again from claim_daily",
              sum("刷体力已禁用" in m for m in farm.logs), 1)
        if used == USED_PART:
            check(f"used {used}: upstream reached the farm, so no 「按刷到空」 top-up line",
                  any("上游这趟不刷体力" in m for m in d.logs), False)
    check("补刷那条没有重复禁用的话", sum("刷体力已禁用" in m for m in d.farms[TacetTask].logs), 1)
    for cls, name in ((ForgeryTask, "farm_forgery"), (SimulationTask, "farm_simulation")):
        EV.clear()
        t = wire(object.__new__(cls))
        check(f"{name} 也挡住", getattr(t, name)(daily=True, used_stamina=0, config={}), None)
        check(f"{name} 没进本", farm_calls(), [])
    os.remove(no_farm)

    # ---------------------------------------------------------------------------
    print("\n[无音区结算：刷不动了停在结算页，留一张 tacet_drops]")
    t = wire(object.__new__(TacetTask))
    t.wait_ocr = lambda *a, **kw: [Box(str(BACK_UP), 1), Box(f"{CURRENT}/240", 2)]
    t.result = (False, 60)
    check("返回值原样", t.use_stamina(once=60, must_use=0), (False, 60))
    check("留了图", t.shots, ["tacet_drops"])
    t.result = (True, 60)
    t.shots = []
    check("还能接着刷：返回值原样", t.use_stamina(once=60, must_use=0), (True, 60))
    check("还能接着刷：不留图", t.shots, [])

    print("\n[体力读数：领奖框里读字原文进日志，真实文本]")
    t.result = (False, 60)
    t.use_stamina(once=60)
    check(f"读到 {CURRENT}+{BACK_UP}（OK-WW-07-27-50.log:419-420）", t.read, (CURRENT, BACK_UP, CURRENT + BACK_UP))
    check("current_stamina 照上游记", t.info.get("current_stamina"), CURRENT)
    check("读字原文进了日志（领奖框）", any(m.startswith("体力读字原文领奖框（第 1 次）") for m in t.logs))

    t = wire(object.__new__(TacetTask))
    t.wait_ocr = lambda *a, **kw: [Box("挑战成功", 1), Box("剩余180", 2)]
    t.result = (True, 60)
    t.use_stamina(once=60)
    check("一直没有 数/数：-1，不当 0", t.read, (-1, -1, -1))
    check("领奖框里读了 5 次", sum(m.startswith("体力读字原文领奖框") for m in t.logs), 5)
    check("每次之间睡 1 秒", t.sleeps, [1, 1, 1, 1])
    check("留了 stamina_error 图", "stamina_error" in t.shots)

    t = wire(object.__new__(TacetTask))
    t.wait_ocr = lambda *a, **kw: [Box("55", 1), Box("239/240", 2), Box("+", 3)]
    check("书页上读一次：239 + 55", t.get_stamina(), (239, 55, 294))
    check("书页上只读一次", sum(m.startswith("体力读字原文") for m in t.logs), 1)

    boss_file = os.path.join(tmp, "ark-okww-boss-material.json")
    ns["BOSS_MATERIAL_FILE"] = boss_file
    real_boss = ns["_boss_material"]
    boss_calls = []

    def boss_stub(result=None, error=None):
        def stub(task):
            boss_calls.append(type(task).__name__)
            EV.append("boss")
            if error is not None:
                raise error
            return result
        return stub

    print("\n[强敌领奖：没有标记文件，一字不差照旧]")
    ns["_boss_material"] = boss_stub("complete")
    boss_calls.clear()
    d = daily(USED_PART)
    d.run()
    check("没碰强敌那条", boss_calls, [])
    check("照旧刷无音区", farm_calls(), [("farm_tacet", 0, d.config)])
    check("没有强敌的话", any(ns["BOSS_LINE"] in m for m in d.farms[TacetTask].logs), False)

    print("\n[强敌领奖：标记在，只刷强敌，无音区关着（他 11-13：没刷完别去刷无音区，下一个刷什么未定）]")
    Path(boss_file).write_text('{"target": "莉莉"}', encoding="utf-8")
    for got in ("complete", "short", "off", "laps"):
        ns["_boss_material"] = boss_stub(got)
        boss_calls.clear()
        d = daily(USED_PART)
        d.run()
        check(f"{got}：强敌那条跑了一次，在 TacetTask 上", boss_calls, ["TacetTask"])
        check(f"{got}：无音区没刷", farm_calls(), [])
        check(f"{got}：说了这趟怎么结束、无音区不刷",
              any(f"这趟结束（{got}），无音区不刷" in m for m in d.farms[TacetTask].logs))
        check(f"{got}：日常照领", "claim_daily" in EV)
    print("\n[强敌领奖：上游闸门关着（已用 180）时，补刷那条也只走强敌]")
    ns["_boss_material"] = boss_stub("short")
    boss_calls.clear()
    d = daily(USED_FULL)
    d.run()
    check("补刷走的也是强敌，一次", (boss_calls, farm_calls()), (["TacetTask"], []))

    print("\n[强敌领奖：出错不拖垮，回主界面，剩下的体力不刷（无音区关着）]")
    ns["_boss_material"] = boss_stub(error=RuntimeError("培养目标页上没认出"))
    d = daily(USED_PART)
    d.run()
    farm = d.farms[TacetTask]
    check("记了错", any("出错，剩下的体力不刷（无音区关着）" in m for m in farm.logs))
    check("回了主界面", "ensure_main" in EV)
    check("无音区没刷、日常照领", (farm_calls(), "claim_daily" in EV), ([], True))

    print("\n[强敌领奖：OK-WW 的停止信号照原样往上抛]")
    ns["_boss_material"] = boss_stub(error=Disabled())
    d = daily(USED_PART)
    try:
        d.run()
        raised = False
    except Disabled:
        raised = True
    check("往上抛", raised)
    check("没再刷无音区", farm_calls(), [])

    print("\n[强敌领奖：凝素领域 / 模拟领域不走强敌那条]")
    ns["_boss_material"] = boss_stub("complete")
    for target, name in ((SUPPORT[1], "farm_forgery"), (SUPPORT[2], "farm_simulation")):
        boss_calls.clear()
        d = daily(USED_PART, target=target)
        d.run()
        check(f"{name}：没碰强敌", boss_calls, [])
        check(f"{name}：照旧", farm_calls(), [(name, 0, d.config)])

    print("\n[强敌领奖：标记文件的内容]")
    want = ns["_boss_material_want"]
    check("莉莉，行名默认共鸣者突破材料", want(), {"target": "莉莉", "row": "共鸣者突破材料"})
    Path(boss_file).write_text("{坏的", encoding="utf-8")
    check("坏 JSON：说不能用，不当成开着", "error" in want())
    Path(boss_file).write_text('{"row": "共鸣者突破材料"}', encoding="utf-8")
    check("没写培养目标：说不能用", "error" in want())
    os.remove(boss_file)
    check("没有文件：None", want(), None)

    class B:
        """ok-script's Box as far as the overlay reads it: str() is its text (ok Box.__str__)."""
        def __init__(self, name, x, y, w=120, h=33):
            self.name, self.x, self.y, self.width, self.height = name, x, y, w, h

        def __str__(self):
            return self.name

    PAGE = [B("培养目标", 288, 155), B("莉莉", 288, 190), B("所需材料", 940, 155),
            B("讨伐强敌", 342, 528), B("产出共鸣者突破材料", 392, 564), B("无音清剿", 342, 768), B("产出声骸材料", 356, 804),
            B("武器经验材料", 765, 270), B("106/106", 1085, 305, 60, 20), B("21/79", 1430, 305, 60, 20),
            B("直接挑战", 1650, 270),
            B("共鸣者突破材料", 765, 420), B("1/46", 1430, 455, 50, 20), B("直接挑战", 1650, 420),
            B("武器与技能素材", 765, 570), B("1/31", 1085, 605, 50, 20), B("0/87", 1430, 605, 50, 20),
            B("直接挑战", 1650, 570),
            B("156", 1100, 50), B("152/240", 1340, 50)]
    print("\n[强敌领奖：培养目标页上认那一行（真实截图的位置）]")
    owned, need, btn = ns["_boss_row"](PAGE, "共鸣者突破材料")
    check("数量读的是这一行的 1/46，不是上下两行", (owned, need), (1, 46))
    check("直接挑战是这一行的", getattr(btn, "y", None), 420)
    check("没有这一行：三个 None", ns["_boss_row"](PAGE[:3], "共鸣者突破材料"), (None, None, None))

    print("\n[强敌领奖：整趟走一遍——差两个，领一次，再读够了就停]")
    ns["_boss_material"] = real_boss
    Path(boss_file).write_text('{"target": "莉莉"}', encoding="utf-8")

    def page(owned_now, target="莉莉"):
        out = [b for b in PAGE if b.name not in ("1/46", "莉莉")]
        return out + [B(target, 288, 190), B(f"{owned_now}/46", 1430, 455, 50, 20)]

    def dialog(wave, spare):
        return [B(str(spare), 1186, 48), B(f"{wave}/240", 1410, 44), B("领取奖励", 450, 350),
                B("领取奖励需消耗60点结晶波片，请确认是否领取？", 630, 520), B("取消", 640, 678), B("确认", 1260, 678)]

    def fake_task(owned_now=44, wave=152, spare=156, target="莉莉", topup=0, settle=True, claim_dialog=True):
        t = wire(object.__new__(TacetTask))
        t.state = {"owned": owned_now, "wave": wave, "spare": spare, "screen": "world", "topups": topup}
        t.steps = []

        def book(feature=""):
            t.steps.append("book")
            t.state["screen"] = "page"
        t.openF2Book = book
        t.click_relative = lambda x, y, **kw: t.steps.append(("click", x, y))
        t.box_of_screen = lambda *a, **kw: None
        t.height_of_screen = lambda f: int(1080 * f)

        def ocr(box=None, **kw):
            sc = t.state["screen"]
            if sc == "page":
                return page(t.state["owned"], target)
            if sc == "dialog":
                return dialog(t.state["wave"], t.state["spare"])
            if sc == "settle":
                return [B("挑战成功", 900, 200), B("退出副本", 700, 950), B("重新挑战", 1200, 950)]
            return []
        t.ocr = ocr
        t.get_stamina = lambda: (t.state["wave"], t.state["spare"], t.state["wave"] + t.state["spare"])
        t.back = lambda after_sleep=0: t.steps.append("back")
        t.click_box = lambda b, after_sleep=0: t.steps.append(("box", b.name, b.y))
        t.click_team_challenge = lambda: t.steps.append("challenge")
        t.wait_in_team_and_world = lambda time_out=0: None
        t.combat_once = lambda **kw: t.steps.append("fight")
        t.walk_to_treasure = lambda: t.steps.append("walk")

        def f(handle_claim=True):
            t.steps.append(("f", handle_claim))
            if claim_dialog:
                t.state["screen"] = "dialog"
        t.pick_f = f
        t.info_incr = lambda k, v: t.info.__setitem__(k, t.info.get(k, 0) + v)
        t.wait_until = lambda cond, time_out=0, raise_if_not_found=False, **kw: cond()

        def left():
            t.steps.append("cancel")
            t.state["screen"] = "world"
        t.click_dialog_left_button = left

        def take():
            t.state["owned"] += 4
            t.state["wave"] -= 60
            t.state["screen"] = "settle" if settle else "world"

        def right():
            # The game: under 60 waveplates (or a forced top-up) the 「补充结晶波片」 dialog comes first.
            t.steps.append("confirm")
            if t.state["topups"] > 0 or t.state["wave"] < 60:
                t.state["screen"] = "topup"
                return "btn"
            take()
            return "btn"
        t.click_dialog_right_button = right

        def wait_feature(name, **kw):
            return t.state["screen"] == "topup"
        t.wait_feature = wait_feature

        def click(btn, after_sleep=0):
            # After the two top-up clicks: the backup became waveplates, 确认 again.
            t.steps.append(("again", btn))
            t.state["topups"] = 0
            t.state["wave"] += t.state["spare"]
            t.state["spare"] = 0
            if t.state["wave"] >= 60:
                take()
            else:
                t.state["screen"] = "topup"
        t.click = click

        def wait_click_ocr(match=None, **kw):
            if t.state["screen"] == "settle" and match.search("退出副本"):
                t.steps.append("exit")
                t.state["screen"] = "world"
                return True
            return None
        t.wait_click_ocr = wait_click_ocr
        return t

    t = fake_task()
    check("44/46：领一次（+4），48/46 后停在 complete", real_boss(t), "complete")
    check("确认只点了一次", t.steps.count("confirm"), 1)
    check("点的是莉莉那一行的直接挑战", ("box", "直接挑战", 420) in t.steps)
    check("顺序：书 → 培养目标 → 直接挑战 → 开启挑战 → 打 → 走到宝箱 → F（不让上游取消）→ 确认 → 退出副本",
          [s if not isinstance(s, tuple) else s[0] for s in t.steps][:9],
          ["book", "box", "box", "challenge", "fight", "walk", "f", "confirm", "exit"])   # 11-14: 培养目标 is clicked by its box
    check("第一下点的是「培养目标」那一格，第二下是直接挑战", [s[1] for s in t.steps if isinstance(s, tuple) and s[0] == "box"][:2], ["培养目标", "直接挑战"])
    check("按 F 时 handle_claim=False", ("f", False) in t.steps)
    check("记了花的体力 60", t.info.get("used stamina"), 60)
    check("留了领奖图", "boss_material_claimed" in t.shots)
    check("每圈开头都读一次数量（44 → 48）", [m for m in t.logs if m.startswith(ns["BOSS_LINE"] + "莉莉的共鸣者突破材料 ")],
          [ns["BOSS_LINE"] + "莉莉的共鸣者突破材料 44/46", ns["BOSS_LINE"] + "莉莉的共鸣者突破材料 48/46"])
    check("领奖框上读了顶栏", any("领奖框：顶栏读到波片 152/240，备用 156" in m for m in t.logs))

    t = fake_task(owned_now=10)
    check("10/46、波片 152 + 备用 156：领到不够一次为止", real_boss(t), "short")
    check("领了 5 次（152→92→32，补备用 188→128→68→8），补充框只出一次",
          (t.info.get("used stamina"), t.steps.count(("again", "btn"))), (300, 1))
    check("剩 8 停下，说了不够", any("体力 8 + 备用 0 不够领一次的 60" in m for m in t.logs))

    t = fake_task(owned_now=46)
    check("已经够了：一次不打", (real_boss(t), "fight" in t.steps), ("complete", False))
    t = fake_task(wave=10, spare=20)
    check("体力 + 备用不够 60：一次不打", (real_boss(t), "fight" in t.steps), ("short", False))
    t = fake_task(target="锁暝")
    check("培养目标换了人：不打，回 off", (real_boss(t), "fight" in t.steps), ("off", False))
    check("培养目标换了人：留图、记错", ("boss_material_target" in t.shots,
                                       any("培养目标不是莉莉" in m for m in t.logs)), (True, True))

    print("\n[强敌领奖：波片 30 + 备用 156——游戏弹补充框，用备用，再点一次确认]")
    t = fake_task(wave=30, spare=156, topup=1)
    real_boss(t)
    check("补充框：点了两下 (0.70, 0.71)、返回、再确认", (("click", 0.70, 0.71) in t.steps, ("again", "btn") in t.steps),
          (True, True))
    check("说了动用备用体力", any("动用备用体力" in m for m in t.logs))

    print("\n[强敌领奖：波片读到 152 够领，游戏却弹补充框——不点补充，抛出]")
    t = fake_task(wave=152, topup=1)
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("抛出并说清", "游戏却弹了补充波片的框" in got)
    check("取消了，没点补充", ("cancel" in t.steps, ("click", 0.70, 0.71) in t.steps), (True, False))

    print("\n[强敌领奖：波片 20 + 备用 20 不够一次——取消，不动备用]")
    t = fake_task(wave=20, spare=20)
    t.get_stamina = lambda: (80, 0, 80)          # the page read said enough; the dialog's bar says not
    check("返回 short", real_boss(t), "short")
    check("点了取消，没点确认", ("cancel" in t.steps, "confirm" in t.steps), (True, False))

    print("\n[强敌领奖：波片够时备用读不清不要紧（11-13 05:27:12 读成「14）」）；波片不够时读不清就停]")

    def odd_spare(t, spare_text):
        real = t.ocr

        def ocr(box=None, **kw):
            got = real(box=box, **kw)
            if t.state["screen"] == "dialog":
                got = [B(spare_text, 1208, 48, 60, 35) if b.name == str(t.state["spare"]) else b for b in got]
            return got
        t.ocr = ocr
        return t
    t = odd_spare(fake_task(owned_now=40, wave=362, spare=14), "14）")
    check("波片 362、备用读成「14）」：照样领", (real_boss(t), t.steps.count("confirm") >= 1), ("complete", True))
    t = odd_spare(fake_task(owned_now=40, wave=30, spare=156), "156）")
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("波片 30、备用读不清：不点确认，留图抛出", ("没读全" in got, "confirm" in t.steps, "boss_material_bar_unread" in t.shots),
          (True, False, True))

    print("\n[强敌领奖：一圈没打成（11-13 05:44:49 角色倒下、复活没开成地图）——回塔回血，从培养目标页重进]")

    def flaky(t, fails):
        left = [fails]

        def fight(**kw):
            t.steps.append("fight")
            if left[0] > 0:
                left[0] -= 1
                raise RuntimeError("combat check not in combat")
        t.combat_once = fight
        t.teleport_to_heal = lambda: t.steps.append("heal")
        return t
    t = flaky(fake_task(owned_now=40), 1)
    check("失败一次后照样刷满", real_boss(t), "complete")
    check("回了塔回血一次", t.steps.count("heal"), 1)
    check("说了重进、留了图", (any("这一圈没打成" in m for m in t.logs), "boss_material_lap_failed" in t.shots), (True, True))
    t = flaky(fake_task(owned_now=40), 3)
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("连着 3 圈没打成：停下", ("连着 3 圈没打成" in got, t.steps.count("heal")), (True, 2))
    t = flaky(fake_task(owned_now=40), 1)

    def no_heal():
        raise RuntimeError("Can not find a teleport to heal")
    t.teleport_to_heal = no_heal
    check("回塔没成也照样重进", real_boss(t), "complete")

    print("\n[强敌领奖：刚登录完 F2 指南没打开（11-13 05:49:39）——回主界面再试]")
    t = fake_task(owned_now=40)
    real_book = t.openF2Book
    book_fails = [1]

    def book(feature=""):
        if book_fails[0]:
            book_fails[0] -= 1
            raise Exception("can't find gray_book_boss, make sure f2 is the hotkey for book")
        real_book(feature)
    t.openF2Book = book
    check("没打开一次，再试就刷满", real_boss(t), "complete")
    check("说了再试、留了图", (any("F2 指南没打开" in m for m in t.logs), "boss_material_book" in t.shots), (True, True))
    t = fake_task(owned_now=40)

    def never(feature=""):
        raise Exception("can't find gray_book_boss")
    t.openF2Book = never
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("一直打不开：试 3 次后停下", "连着 3 次没打开 F2 指南" in got)

    print("\n[强敌领奖：培养目标页还没画出来（11-13 05:59:19 被当成换了人）——等一等，等不到就重进]")
    t = fake_task(owned_now=40)
    blank = [2]
    real_ocr = t.ocr

    def slow(box=None, **kw):
        if t.state["screen"] == "page" and blank[0]:
            blank[0] -= 1
            return [B(".187ms", 1776, 79), B("1", 1736, 210)]
        return real_ocr(box=box, **kw)
    t.ocr = slow
    check("前两眼是空的，第三眼出来了：照常刷满", real_boss(t), "complete")
    check("没说换了人", any("培养目标不是" in m for m in t.logs), False)
    t = fake_task(owned_now=40)
    t.ocr = lambda box=None, **kw: [B(".187ms", 1776, 79)]
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("一直空着：重进 2 次后停下，不说换了人", ("没等到培养目标页" in got, any("培养目标不是" in m for m in t.logs)),
          (True, False))

    print("\n[强敌领奖：领奖框刚出来时顶栏还没画好（11-13 06:11:26）——多看几眼]")
    t = fake_task(owned_now=40)
    torn = [2]
    real_ocr2 = t.ocr

    def drawing(box=None, **kw):
        got = real_ocr2(box=box, **kw)
        if t.state["screen"] == "dialog" and torn[0]:
            torn[0] -= 1
            return [b for b in got if "/240" not in b.name] + [B("城", 1386, 9)]
        return got
    t.ocr = drawing
    check("顶栏前两眼没读到、第三眼读到：照常领", real_boss(t), "complete")
    check("确认点了", "confirm" in t.steps)

    print("\n[强敌领奖：刷够以后那一行从培养目标页上消失（11-13 06:25:08）——算够了，不算认不出]")
    t = fake_task(owned_now=44)
    real_ocr3 = t.ocr

    def gone(box=None, **kw):
        got = real_ocr3(box=box, **kw)
        if t.state["screen"] == "page" and t.state["owned"] >= 46:
            got = [b for b in got if b.name not in ("共鸣者突破材料", f"{t.state['owned']}/46")
                   and not (b.name == "直接挑战" and b.y == 420)]
            # what stays in its place on the real page: the gathered flower, same word in its label, 前往 not 直接挑战
            got = got + [B("突破材料", 814, 420), B("0/60", 1490, 455, 50, 20), B("前往", 1698, 420)]
        return got
    t.ocr = gone
    check("左栏那句「产出共鸣者突破材料」确实在屏上（旧判断就栽在它身上）", any(b.name == "产出共鸣者突破材料" for b in PAGE))
    check("领到 48 后那一行没了：complete", real_boss(t), "complete")
    check("说了够了、为什么", any("已经够了（培养目标页上不再列这一行）" in m for m in t.logs))

    print("\n[强敌领奖：那一行没了以后右栏画得慢（11-13 06:30:54，6 眼都只有左上角）——多等几眼]")
    t = fake_task(owned_now=46)
    late = [8]
    real_ocr4 = t.ocr

    def slow_panel(box=None, **kw):
        if t.state["screen"] == "page":
            if late[0]:
                late[0] -= 1
                return [B("素材获取", 102, 50), B("17", 1112, 48), B("5/240", 1400, 48), B("当期", 200, 150),
                        B("莉莉", 288, 190)]
            return [b for b in real_ocr4(box=box, **kw) if b.name not in ("共鸣者突破材料", "46/46")
                    and not (b.name == "直接挑战" and b.y == 420)]
        return real_ocr4(box=box, **kw)
    t.ocr = slow_panel
    check("8 眼后右栏才出来、那一行没了：complete，不报错", real_boss(t), "complete")

    print("\n[强敌领奖：按左栏读到的「培养目标」那一格去点，不点死坐标（11-14 双子星）]")
    t = fake_task(owned_now=44)
    real_boss(t)
    check("点的是读到的那一格", (("box", "培养目标", 155) in t.steps, ("click", 0.22, 0.17) in t.steps), (True, False))

    print("\n[强敌领奖：左栏已经没有「培养目标」（练满或取消了，模拟领域顶到最上面）——不点、不报错，算够了]")
    t = fake_task(owned_now=44)
    t.ocr = lambda box=None, **kw: ([B("素材获取", 102, 50), B("模拟领域", 342, 190), B("产出经验材料", 356, 226), B("讨伐强敌", 342, 430),
                                    B("产出共鸣者突破材料", 392, 466), B("无音清剿", 342, 670)] if t.state["screen"] == "page" else [])
    check("没有培养目标：complete", real_boss(t), "complete")
    check("没点死坐标、没打、退出了指南", (("click", 0.22, 0.17) in t.steps, "fight" in t.steps, "back" in t.steps), (False, False, True))
    check("说了为什么，用的是中继认得的那句（已经够了（…））",
          any("已经够了（素材获取左栏没有「培养目标」这一格" in m for m in t.logs))

    print("\n[强敌领奖：指南开了却一个字都没读到——照旧点老位置，走后面的重试]")
    t = fake_task(owned_now=44)
    real_ocr6 = t.ocr
    blank = [3]

    def nothing_first(box=None, **kw):
        if t.state["screen"] == "page" and blank[0] > 0:
            blank[0] -= 1
            return []
        return real_ocr6(box=box, **kw)
    t.ocr = nothing_first
    real_boss(t)
    check("前三眼空白：点了老位置", ("click", 0.22, 0.17) in t.steps)

    print("\n[强敌领奖：页面认不出时，报错行里是整屏读到的每一个名字，不是前几百个字（11-13 06:36:46）]")
    t = fake_task(owned_now=46)
    real_ocr5 = t.ocr

    class Real(B):                          # prints the way ok-script's Box does: about 85 characters each
        def __str__(self):
            return f"Box(name='{self.name}', x={self.x}, y={self.y}, width=116, height=35, confidence=100)"

    def no_header(box=None, **kw):
        if t.state["screen"] == "page":
            return [Real("素材获取", 102, 50), Real("17", 1112, 48), Real("5/240", 1400, 48), Real("当期", 200, 150),
                    Real("莉莉", 288, 190), Real("武器经验材料", 765, 270), Real("106/106", 1085, 305),
                    Real("直接挑战", 1650, 270), Real("突破材料", 765, 420), Real("0/60", 1430, 455),
                    Real("前往", 1650, 420), Real("最后一行的字", 765, 870)]
        return real_ocr5(box=box, **kw)
    t.ocr = no_header
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("认不出那一行：停下", "没认出「共鸣者突破材料」那一行" in got, True)
    check("整屏的名字都在报错行里，最后一个也在", ("武器经验材料" in got, "前往" in got, "最后一行的字" in got), (True, True, True))
    check("名字之间不夹坐标", "confidence=" in got.split("整屏读到")[1], False)

    print("\n[强敌领奖：按 F 没出「领取奖励」框——留图抛出（外面交给无音区）]")
    t = fake_task(claim_dialog=False)
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("抛出", ("没出「领取奖励」框" in got, "boss_material_no_claim" in t.shots), (True, True))

    print("\n[强敌领奖：确认后没等到「退出副本」——留图抛出]")
    t = fake_task(settle=False)
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("抛出", ("没等到结算页的「退出副本」" in got, "boss_material_no_settlement" in t.shots), (True, True))
    os.remove(boss_file)

    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def _part_okww_merge_step():
    """The step list does not claim 「声骸五合一」 from the line logged before the merge."""

    from ark_relay.features import outcome as co

    T = "2026-10-12 10:{:02d}:00,000 {} TaskExecutor {}"
    MERGE_FAILED = "\n".join([
        T.format(1, "INFO", "MergeEchoTask:check discarded echo"),
        T.format(2, "ERROR", "MergeEchoTask:MergeEchoTask Failed"),
    ])
    GARDEN = T.format(3, "INFO", "GardenTask:garden counter 2/3")

    print("[merge started and failed: not listed as done]")
    steps = co._okww_steps(MERGE_FAILED, 0)
    check("no 声骸五合一", any("五合一" in s for s in steps), False)

    print("\n[the garden's 「不算完成」 marking is unchanged]")
    check("garden ran, not read as done", co._okww_steps(GARDEN, 0), ["周常乐园（没读到做完，不算完成）"])


def _part_okww_plan_bits():
    """Tomorrow's OK-WW plan lines, read from the master config that takes effect."""
    import json
    import os
    from unittest import mock

    os.environ["ARK_STATE_DIR"] = str(tmpdir())        # no no-stamina-farm flag
    os.environ.pop("ARK_OKWW_DIR", None)
    from ark_relay.core import plan

    def automas(daily, *, farm=None, quick=None):
        root = tmpdir()
        d = root / "data" / "okww-sid" / "Default" / "ConfigFile"
        d.mkdir(parents=True)
        (d / "DailyTask.json").write_text(json.dumps(daily), encoding="utf-8")
        if farm is not None:
            (d / "FarmEchoTask.json").write_text(json.dumps(farm), encoding="utf-8")
        if quick is not None:
            (root / "config").mkdir()
            (root / "config" / "ScriptConfig.json").write_text(json.dumps({
                "s9": {"Info": {"Name": "OK-WW"},
                       "SubConfigsInfo": {"UserData": {"u1": {
                           "Info": {"IfQuickConfig": True}, "Task": quick}}}}}), encoding="utf-8")
        return root, d

    print("[_okww_plan_bits]")
    check("no AUTO-MAS dir -> nothing", plan._okww_plan_bits(None), [])
    check("no data dir -> nothing", plan._okww_plan_bits(tmpdir()), [])

    root, _ = automas({"Which to Farm": "Simulation Challenge", "Material Selection": "Shell Credit",
                       "Additional Tasks to Run After Daily Task": ["Auto Farm all Nightmare Nest"]})
    bits = plan._okww_plan_bits(root)
    check("master read: stamina line", bits[0], "体力刷 模拟领域·贝币")
    check("master read: nest farmed to full", any("全部点位，刷到打满" in b for b in bits), True)
    check("nest-full is not repeated as an extra task", any(b.startswith("附加") for b in bits), False)

    root, _ = automas({"Which to Farm": "Simulation Challenge", "Material Selection": "Shell Credit",
                       "Additional Tasks to Run After Daily Task": []},
                      quick={"WhichToFarm": "Simulation Challenge", "MaterialSelection": "Weapon EXP",
                             "WhichTacetSuppressionToFarm": 1, "WhichForgeryChallengeToFarm": 1,
                             "FarmNightmareNestForDailyEcho": False, "AdditionalTasks": []})
    check("quick config on -> its value wins over the master",
          plan._okww_plan_bits(root)[0], "体力刷 模拟领域·武器经验")

    print("[_okww_extra_bit]")
    _, d = automas({}, farm={"Teleport to Boss": "Weekly Challenge", "Boss Level": "90",
                             "Which Weekly Boss to Teleport": 2})
    with mock.patch.object(plan, "_weekly_boss_state", lambda: (False, "")):
        check("weekly-boss commandeered, not done -> fought tomorrow",
              plan._okww_extra_bit(d, ["Teleport and Farm 4C Echo"], {}),
              "附加 周本 战歌重奏第 2 个（90 级），明天会打")
    with mock.patch.object(plan, "_weekly_boss_state", lambda: (True, "鸣式·利维亚坦")):
        check("weekly-boss quota full -> says not fought",
              plan._okww_extra_bit(d, ["Teleport and Farm 4C Echo"], {}),
              "附加 周本 鸣式·利维亚坦（90 级），本周已打满，明天不打")
    _, d2 = automas({}, farm={"Teleport to Boss": "Normal"})
    check("not commandeered -> named as the echo task (translated when the pack has it)",
          plan._okww_extra_bit(d2, ["Teleport and Farm 4C Echo"], {"Teleport and Farm 4C Echo": "传送刷4C声骸"}),
          "附加 传送刷4C声骸")
    check("more than two -> first two and a count",
          plan._okww_extra_bit(d2, ["A", "B", "C"], {}), "附加 A、B 等 3 项")
    check("only nest-full / nothing -> no line",
          (plan._okww_extra_bit(d2, ["Auto Farm all Nightmare Nest"], {}), plan._okww_extra_bit(d2, [], {})),
          ("", ""))


def _part_okww_revive_and_retry():  # noqa: C901
    """Echo farm and weekly boss: deaths go to upstream, and retries stop after three failures.
    """
    import os
    import re
    import types

    from ark_relay.features import okww_overlay

    REPLAY = fx_dir(Path(__file__), "replay")

    class Disabled(Exception):
        """ok.TaskDisabledException."""

    class Revived(Exception):
        """src.task.BaseCombatTask.CharRevivedException."""

    class _Any(type):
        """A stand-in upstream class: any method the overlay reads exists and does nothing."""
        def __getattr__(cls, name):
            if name.startswith("__"):
                raise AttributeError(name)

            def anything(self, *a, **kw):
                return None
            return anything

    class Box:
        """ok-script's OCR box: the overlay reads .name and str()."""
        def __init__(self, name, x=0, y=0, width=10, height=10):
            self.name, self.x, self.y, self.width, self.height = name, x, y, width, height

        def __str__(self):
            return f"Box(name='{self.name}', x={self.x}, y={self.y}, width={self.width}, height={self.height})"

    class BaseWWTask(metaclass=_Any):
        pass

    class FarmEchoTask(BaseWWTask):
        def revive_action(self):
            # Upstream v3.7.4 FarmEchoTask.py:92-106, reduced: in a realm it hands over to
            # BaseCombatTask.revive_action (:227-240: close_revive_popup cancels the popup,
            # then leave and heal; returns True, is_revived untouched); in the overworld it
            # walks back to the boss and sets is_revived.
            if not self._in_realm:
                self.events.append("upstream-revive")
                self.is_revived = True
                return True
            self.events.append("cancel-popup")
            return True

        def run(self, retries=3):
            # Upstream v3.7.4 FarmEchoTask.py:108-125, verbatim apart from the stand-ins
            # (start_time and WWOneTimeTask.run left out): the retry is self.run(retries - 1)
            # from its own except, i.e. through whatever FarmEchoTask.run is bound to.
            self.retries_seen.append(retries)
            try:
                return self.do_run()
            except Disabled:
                pass
            except Exception:
                self.log_info("farm 4c error, try handle monthly card")
                if retries > 0 and (self.handle_claim_button() or self.handle_monthly_card()):
                    self.run(retries - 1)
                else:
                    raise

        def do_run(self):
            self.bodies += 1
            if self.bodies <= self.failures:
                raise RuntimeError("Teleport to boss failed")
            return "farmed"

        def handle_claim_button(self):
            return self.claim_button

        def handle_monthly_card(self):
            return False

        def combat_once(self, wait_combat_time=200, raise_if_not_found=True, target=False):
            # What BaseCombatTask.raise_not_in_combat (:310-332) does on a death: call
            # revive_action, then raise CharRevivedException when it returned True.
            if self.dies:
                if self.revive_action():
                    raise Revived("combat check not in combat")
                raise RuntimeError("revive failed")
            return True

    mods = {
        "ok": types.SimpleNamespace(TaskDisabledException=Disabled,
                                    Logger=types.SimpleNamespace(get_logger=lambda n: types.SimpleNamespace(
                                        info=lambda *a, **k: None, error=lambda *a, **k: None))),
        "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
        "src.task.BaseCombatTask": types.SimpleNamespace(CharRevivedException=Revived),
        "src.task.BaseWWTask": types.SimpleNamespace(BaseWWTask=BaseWWTask),
        "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=FarmEchoTask),
    }
    for name in ("DailyTask", "ForgeryTask", "SimulationTask", "TacetTask"):
        mods[f"src.task.{name}"] = types.SimpleNamespace(**{name: _Any(name, (), {})})
    _saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    # The function itself, not its name: a class made inside a part is named
    # "_part_okww_revive_and_retry.<locals>.FarmEchoTask".
    upstream_revive = FarmEchoTask.__dict__["revive_action"]
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    print("[绑定都换上了]")
    for b in ("FarmEchoTask.combat_once", "FarmEchoTask.run"):
        check(f"{b} 已换上", b in ns["_applied"])
    print("[revive_action is upstream's own again]")
    check("revive_action not in the applied list", "FarmEchoTask.revive_action" in ns["_applied"], False)
    check("FarmEchoTask.revive_action is still upstream's function",
          FarmEchoTask.__dict__["revive_action"] is upstream_revive, True)
    check("the overlay source has no revive_action override",
          '@override(FarmEchoTask, "revive_action")' in okww_overlay.source_text(), False)

    # farming_echoes() is 「the no-claim flag file exists」; point it at a temp file.
    tmp = str(tmpdir("ark-revive-"))
    flag = os.path.join(tmp, "ark-okww-farm.no-claim")
    ns["NO_CLAIM"] = flag

    def task(in_realm=True):
        t = object.__new__(FarmEchoTask)
        t.events, t.logs, t.clicks, t.waits = [], [], [], []
        t._in_realm = in_realm
        t.is_revived = False
        t.dies = False
        t.bodies, t.failures, t.claim_button = 0, 0, True
        t.retries_seen = []
        t.log_info = lambda msg, notify=False: t.logs.append(msg)
        t.log_error = lambda msg, notify=False, **kw: t.logs.append(msg)
        t.click = lambda target, after_sleep=0: t.clicks.append(str(getattr(target, "name", target)))
        t.wait_in_team_and_world = lambda time_out=10, **kw: t.waits.append(time_out) or True
        return t

    # ---------------------------------------------------------------------------
    print("\n[revive_action: a realm death while farming echoes runs upstream's revive (cancel the popup), no revive item]")
    Path(flag).write_text("")
    t = task()
    check("returns upstream's result", t.revive_action(), True)
    check("upstream cancelled the popup", t.events, ["cancel-popup"])
    check("nothing clicked by the overlay (no 「确认」, no revive item)", t.clicks, [])
    check("is_revived not set (do_run re-teleports)", t.is_revived, False)
    os.remove(flag)

    # ---------------------------------------------------------------------------
    print("\n[combat_once: a realm death while farming echoes goes up to upstream's do_run re-teleport]")
    Path(flag).write_text("")
    t = task()
    t.dies = True
    try:
        t.combat_once(wait_combat_time=5, raise_if_not_found=False)
        raised = False
    except Revived:
        raised = True
    check("CharRevivedException goes up (do_run: re-teleport, cap 3)", raised)
    check("did not say it carries on in place", any("复活成功" in m for m in t.logs), False)
    os.remove(flag)

    print("\n[combat_once：上游的复活（周本）照样往上抛，交给 do_run 重新传送]")
    t = task()
    t.dies = True
    try:
        t.combat_once(wait_combat_time=5, raise_if_not_found=False)
        raised = False
    except Revived:
        raised = True
    check("CharRevivedException 往上抛", raised)
    check("没说「接着刷」", any("复活成功" in m for m in t.logs), False)

    print("\n[combat_once：上游大世界那份复活也回到了 boss 跟前（is_revived），同样接着刷、不受 3 次上限]")
    t = task(in_realm=False)
    t.dies = True
    check("返回 None，不往上抛", t.combat_once(), None)
    check("走的是上游的复活", t.events, ["upstream-revive"])
    check("is_revived 留着", t.is_revived, True)

    print("\n[combat_once：没死就原样返回]")
    t = task()
    check("返回上游的结果", t.combat_once(), True)

    # ---------------------------------------------------------------------------
    print("\n[FarmEchoTask.run：上游自己的 except 里无限重试，包一层数到 3 就停——按失败结束，不是跳过]")
    cap = ns["_MAX_FARM_RETRIES"]
    check("上限是 3", cap, 3)
    t = task()
    t.failures = 99
    got = None
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("连续失败：任务按失败结束（OK-WW 记失败的普通异常）", type(got).__name__, "ArkStopped")
    check("不是 OK-WW 的「跳过」（TaskDisabledException）", isinstance(got, Disabled), False)
    check("失败原因写在异常里", str(got), f"连续 {cap} 次失败，退出本次任务，不再重试")
    check("上游正文只跑了 3 次", t.bodies, cap)
    check("日志：连续 3 次失败", any(f"连续 {cap} 次失败，退出本次任务，不再重试" in m for m in t.logs))
    check("日志：按失败结束", any(m.startswith(ns["FAILED_MARK"]) for m in t.logs))
    check("上游每次都记了 farm 4c error", sum("farm 4c error" in m for m in t.logs), cap)
    check("深度计数归零", t._ark_depth, 0)

    print("\n[FarmEchoTask.run：下一次运行从 0 数起]")
    t.bodies = 0
    try:
        t.run()
    except ns["ArkStopped"]:
        pass
    check("又是 3 次", t.bodies, cap)
    check("深度计数归零", t._ark_depth, 0)

    print("\n[FarmEchoTask.run：中途认不出的画面停下（_stop）——上游 run() 照常收尾，最外层按失败结束]")
    t = task()
    t.screenshot = lambda name: t.events.append(f"shot {name}")

    def _odd_lap(self=t):
        self.bodies += 1
        ns["_stop"](self, "weekly_claim_unchanged", "周本领奖：回读次数没变（2/3），这次没领到")
    t.do_run = _odd_lap
    got = None
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("按失败结束", (type(got).__name__, str(got)), ("ArkStopped", "周本领奖：回读次数没变（2/3），这次没领到"))
    check("上游的 except TaskDisabledException 收了这一停：没重试、没 farm 4c error",
          (t.bodies, any("farm 4c error" in m for m in t.logs)), (1, False))
    check("留了图", "shot weekly_claim_unchanged" in t.events, True)
    check("深度计数归零、原因清掉", (t._ark_depth, t._ark_failed), (0, None))

    print("\n[FarmEchoTask.run: a waveplate shortage (_skip_short) is a normal state - returns, no FAILED_MARK, no ArkStopped]")
    t = task()

    def _short_lap(self=t):
        self.bodies += 1
        self.log_info("波片不足挡住开启挑战，点取消跳过本次周本")
        ns["_skip_short"](self)
    t.do_run = _short_lap
    got = "returned"
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("缺波片：正常返回，不抛 ArkStopped", got, "returned")
    check("缺波片：日志没有按失败结束", any(m.startswith(ns["FAILED_MARK"]) for m in t.logs), False)
    check("缺波片：上游收了这一停，没重试", (t.bodies, any("farm 4c error" in m for m in t.logs)), (1, False))
    check("缺波片：深度归零、没留原因", (t._ark_depth, t._ark_failed), (0, None))

    print("\n[FarmEchoTask.run: a non-waveplate stop right after still raises ArkStopped]")
    t = task()
    t.screenshot = lambda name: t.events.append(f"shot {name}")

    def _odd_lap2(self=t):
        self.bodies += 1
        ns["_stop"](self, "weekly_claim_unchanged", "周本领奖：回读次数没变（2/3），这次没领到")
    t.do_run = _odd_lap2
    got = None
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("非波片停下仍按失败结束", (type(got).__name__, str(got)), ("ArkStopped", "周本领奖：回读次数没变（2/3），这次没领到"))
    check("非波片停下：日志写了按失败结束", any(m.startswith(ns["FAILED_MARK"]) for m in t.logs), True)

    print("\n[FarmEchoTask.run：真没事可做（上游自己的跳过）照旧是跳过]")
    t = task()

    def _done_lap(self=t):
        self.bodies += 1
        raise Disabled()
    t.do_run = _done_lap
    got = "returned"
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("上游的跳过：正常返回，不算失败", got, "returned")

    print("\n[FarmEchoTask.run：第 2 次成了就不再报停]")
    t = task()
    t.failures = 1
    try:
        t.run()
        stopped = False
    except Disabled:
        stopped = True
    check("没抛", stopped, False)
    check("跑了 2 次", t.bodies, 2)
    check("没说连续失败", any("连续" in m for m in t.logs), False)
    check("深度计数归零", t._ark_depth, 0)
    check("v3.7.4 retry count passed through the wrapper: 3, then 2", t.retries_seen, [3, 2])

    print("\n[FarmEchoTask.run: v3.7.4 self.run(retries - 1) goes through the wrapper without a TypeError]")
    t = task()
    t.failures = 1
    got = None
    try:
        got = t.run()
    except TypeError as e:  # the 10-13 bug: the wrapper was def run(self)
        got = f"TypeError: {e}"
    check("retry after one failure returns upstream's result", got, None)
    check("upstream body ran twice", t.bodies, 2)
    check("each retry reached upstream with one less", t.retries_seen, [3, 2])
    t = task()
    t.failures = 0
    check("run(retries=1) reaches upstream as 1", (t.run(1), t.retries_seen), ("farmed", [1]))

    print("\n[FarmEchoTask.run：上游自己放弃（没领奖按钮也没月卡）时原样抛]")
    t = task()
    t.failures, t.claim_button = 99, False
    try:
        t.run()
        got = None
    except RuntimeError as e:
        got = str(e)
    check("上游的错原样上来", got, "Teleport to boss failed")
    check("只跑了 1 次", t.bodies, 1)
    check("深度计数归零", t._ark_depth, 0)

    # ---------------------------------------------------------------------------
    print("\n[有记录的那次副本里阵亡，是在 combat_once 里抛的（覆盖面就在那儿）]")
    log = (REPLAY / "2026-09-01" / "wuwa" / "OK-WW-02-01-22.log").read_text(encoding="utf-8")
    dead = log.index("FarmEchoTask:raise_not_in_combat char dead")
    check("2026-09-01 06:03:27 阵亡", "2026-09-01 06:03:27,238 INFO TaskExecutor FarmEchoTask:raise_not_in_combat char dead" in log)
    check("上游当时复活失败", "06:03:27,239 INFO TaskExecutor FarmEchoTask:info_set Revive Failed" in log)
    trace = log[dead:dead + 1500]
    check("报错的那一圈停在 farm 4c error", "farm 4c error, try handle monthly card" in trace)
    check("调用栈里是 do_run → combat_once", bool(re.search(r"in do_run\s+self\.combat_once\(", trace)))

    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def _part_okww_stamina_end():
    """结束时的剩余波片要认 OK-WW 自己报的那个数。"""

    from ark_relay.core import collector

    REAL = """
2026-08-28 13:40:57,971 INFO TaskExecutor ForgeryTask:info_set current_stamina 240
2026-08-28 13:41:59,293 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 240 >= 80
2026-08-28 13:42:49,641 INFO TaskExecutor ForgeryTask:info_set current_stamina 160
2026-08-28 13:42:49,641 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 160 >= 80
2026-08-28 13:43:40,617 INFO TaskExecutor ForgeryTask:info_set current_stamina 80
2026-08-28 13:43:40,618 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 80 >= 80
2026-08-28 13:43:44,857 INFO TaskExecutor BaseWWTask:current stamina: 0 not enough to continue
2026-08-28 13:43:48,859 INFO TaskExecutor ForgeryTask:used all stamina
2026-08-28 13:44:57,176 INFO TaskExecutor DailyTask:Daily Task Completed
"""

    NO_END_LINE = "\n".join(
        l for l in REAL.splitlines() if "not enough to continue" not in l)

    NEST = """
2026-08-29 00:21:27,418 INFO TaskExecutor NightmareNestTask:Box(name='已击败残象：26/41', x=890) is not complete
2026-08-29 00:23:27,182 INFO TaskExecutor NightmareNestTask:nightmare nest: 指定点位都已打满，跳过
"""


    def _parse(text):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "OK-WW.log"
            f.write_text(text, encoding="utf-8")
            return collector.parse_okww_log(f)


    def main() -> int:
        print("=== 08-28 的真实日志 ===")
        out = _parse(REAL)
        check("剩余取 OK-WW 自己报的 0，不是开打前的 80",
              out.get("okww_stamina_left"), 0)
        check("标明这是精确值", out.get("okww_stamina_left_exact"), True)

        print("\n=== 没有收尾那行时，退回旧读数但要标明不精确 ===")
        out2 = _parse(NO_END_LINE)
        check("退回最后一条开打前读数", out2.get("okww_stamina_left"), 80)
        check("标明不是结束余量", out2.get("okww_stamina_left_exact"), False)

        print("\n=== 残象聚落进度 ===")
        out3 = _parse(NEST)
        check("no okww_nest field (dropped 2026-10-13, read by nothing)", "okww_nest" in out3, False)
        check("抓到已打满", out3.get("okww_nest_full"), True)

        return 0 if not fails else 1


    raise SystemExit(main())


def _part_okww_stamina_nest_verdict():
    """刷体力 and the nest item are judged from the lines of the task that did the work."""

    from ark_relay.features import outcome as collector_okww, outcome

    FX = fx_dir(Path(__file__), "fixtures")

    def line(t, who, msg):
        return f"2026-10-13 10:{t},000 INFO TaskExecutor {who}:{msg}\n"

    def stamina(text):
        got = [c for c in outcome.okww_checks(text, expect_nest=False, expect_daily=False) if c.label == "刷体力"]
        return (got[0].ok, got[0].detail) if got else None

    def stopped(text):
        out = {}
        collector_okww._okww_progress(text, out)
        return out.get("okww_stopped")

    # Read with a fallback so that the checks run, and fail, on code without them.
    UNREAD_SAY = getattr(outcome, "STAMINA_UNREAD_SAY", "体力读不出来，没刷")
    nest_state = getattr(outcome, "nest_state", lambda text: None)
    UNREAD = "体力读了 1 次都没有「数/数」，按没读到处理（-1），不当 0"

    print("[stamina (a): the weekly boss's and the nest's fights are not stamina farming]")
    weekly_only = (line("00:01", "FarmEchoTask", "teleport_to_boss prepared as realm")
                   + line("00:20", "FarmEchoTask", "enter combat None")
                   + line("01:30", "FarmEchoTask", "start walk_to_treasure")
                   + line("02:00", "NightmareNestTask", "enter combat None"))
    ok, why = stamina(weekly_only)
    check("weekly boss + nest fights only: 刷体力 not passed", ok, False)
    check("…and it says nothing was entered", "既没进本" in why)
    ok, _ = stamina(weekly_only + line("05:00", "TacetTask", "enter combat None"))
    check("a TacetTask fight passes", ok, True)
    ok, _ = stamina(weekly_only + line("05:00", "SimulationTask", "start walk_to_treasure"))
    check("a SimulationTask walk to the treasure passes", ok, True)
    ok, why = stamina(weekly_only + line("05:00", "ForgeryTask", "not enough stamina"))
    check("ForgeryTask 「not enough stamina」 with no fight: passed as a shortage", (ok, why), (True, "体力不足，本来就没得刷"))

    print("\n[stamina (d): the 「不刷体力」 flag file was there - not farmed, and said why]")
    flagged = (weekly_only
               + line("04:00", "TacetTask", "刷体力已禁用（标记文件在），这一趟不花波片")
               + line("06:00", "DailyTask", "Daily Task Completed"))
    ok, why = stamina(flagged)
    check("the flag line: 刷体力 not passed, with the flag as the reason", (ok, why), (False, "不刷体力的标记还在"))
    check("the daily report's stop reason says the same", stopped(flagged), "不刷体力的标记还在")
    ok, why = stamina(weekly_only + line("04:00", "ForgeryTask", "刷体力已禁用（标记文件在），这一趟不花波片"))
    check("ForgeryTask prefix too", (ok, why), (False, "不刷体力的标记还在"))

    print("\n[stamina (b): three revives and upstream stops farming - a failure]")
    died = (line("05:00", "TacetTask", "info_set current_stamina 180")
            + line("05:10", "TacetTask", "enter combat None")
            + line("05:40", "TacetTask", "farm_tacet: death recovered, re-enter from F2 book")
            + line("06:10", "TacetTask", "enter combat None")
            + line("06:40", "TacetTask", "farm_tacet: death recovered, re-enter from F2 book")
            + line("07:10", "TacetTask", "enter combat None")
            + line("07:40", "TacetTask", "farm_tacet: exceeded recovery retries (3), stop farming"))
    ok, why = stamina(died)
    check("farm_tacet exceeded recovery retries: 刷体力 failed", ok, False)
    check("…says the character died 3 times and farming stopped", ("死了 3 次" in why, "停止刷体力" in why), (True, True))
    check("daily report does not say 「体力不够再开一局」", stopped(died) == "体力不够再开一局", False)
    check("daily report gives the same reason", stopped(died), why)
    ok, _ = stamina(line("05:00", "ForgeryTask", "enter combat None")
                    + line("07:40", "ForgeryTask", "farm_domain: exceeded recovery retries (3), stop farming"))
    check("farm_domain exceeded recovery retries: failed too", ok, False)
    ok, _ = stamina(line("05:00", "TacetTask", "enter combat None")
                    + line("07:40", "FarmEchoTask", "farm 4c: exceeded recovery retries (3), stop farming"))
    check("the echo farm's own give-up is not a stamina failure", ok, True)

    print("\n[stamina (c): -1 read, then upstream's 「used all stamina」 / 「not enough stamina」]")
    tacet_unread = (line("05:00", "TacetTask", UNREAD)
                    + line("05:00", "TacetTask", "info_set current_stamina -1")
                    + line("05:02", "TacetTask", UNREAD)
                    + line("05:02", "TacetTask", "info_set current_stamina -1")
                    + line("05:03", "TacetTask", "used all stamina"))
    ok, why = stamina(weekly_only + tacet_unread)
    check("tacet: -1 twice then 「used all stamina」, no tacet fight: failed", ok, False)
    check("…says stamina could not be read", why, UNREAD_SAY)
    check("daily report says the same, not 「体力不够再开一局」", stopped(weekly_only + tacet_unread), UNREAD_SAY)
    domain_unread = (line("05:00", "SimulationTask", UNREAD)
                     + line("05:00", "SimulationTask", "info_set current_stamina -1")
                     + line("05:01", "SimulationTask", "not enough stamina"))
    ok, why = stamina(domain_unread)
    check("simulation: -1 then 「not enough stamina」: failed, not 「体力不足」", (ok, why), (False, UNREAD_SAY))
    check("daily report does not say 「一局都没开成」", stopped(domain_unread), UNREAD_SAY)
    reread = (line("05:00", "TacetTask", UNREAD)
              + line("05:00", "TacetTask", "info_set current_stamina -1")
              + line("05:02", "TacetTask", "info_set current_stamina 30")
              + line("05:03", "TacetTask", "used all stamina"))
    ok, why = stamina(reread)
    check("tacet: -1, then the click-and-reread got 30, then 「used all stamina」: a real shortage", (ok, why),
          (True, "体力不足，本来就没得刷"))
    check("…and the daily report keeps its usual wording", stopped(reread), "体力不够再开一局")
    after_fight = (line("05:00", "TacetTask", "info_set current_stamina 180")
                   + line("05:10", "TacetTask", "enter combat None")
                   + line("06:00", "TacetTask", "体力领奖框读了 3 次都没有「数/数」，按没读到处理（-1），不当 0"))
    ok, _ = stamina(after_fight)
    check("a -1 in the reward dialog after a tacet fight still passes", ok, True)
    ok, _ = stamina(line("05:00", "DailyTask", UNREAD) + line("05:03", "TacetTask", "info_set current_stamina 20")
                    + line("05:03", "TacetTask", "used all stamina"))
    check("a -1 logged by another task does not taint the tacet shortage", ok, True)

    print("\n[nest: an unreachable nest plus another task's traceback is not a fight]")
    weekly_err = (FX / "m6-okww" / "0921-weekly.log").read_text(encoding="utf-8")
    check("the 0921 log carries click_team_challenge only in traceback frames",
          ("self.click_team_challenge()" in weekly_err, "NightmareNestTask:" in weekly_err), (True, False))
    unreachable = (line("00:01", "NightmareNestTask", "opened gray_book_boss")
                   + line("00:05", "NightmareNestTask", "nightmare nest unreachable, skip this run: go_nest:48:18")
                   + weekly_err)
    check("_NEST_ENGAGED does not match", bool(outcome._NEST_ENGAGED.search(unreachable)), False)
    got = {c.label: c for c in outcome.okww_checks(unreachable, expect_nest=True, expect_daily=False, expect_stamina=False)}
    check("verdict: 残象聚落 not done", got["残象聚落"].ok, False)
    check("verdict: says travel failed", "传送不过去" in got["残象聚落"].detail)
    step = collector_okww._nest_step(unreachable)
    check("daily step is not the bare name (booked as farmed)", step in ("残象聚落", "梦魇巢穴"), False)
    check("daily step says travel failed", "传送不过去" in step)
    for frame in ("    self.wait_in_team_and_world(time_out=120)\n",
                  "    return self.reset_to_false(reason='echo captured')\n"):
        t = line("00:05", "NightmareNestTask", "nightmare nest unreachable, skip this run") + frame
        check(f"a traceback frame {frame.strip()[:30]!r} is no fight", nest_state(t), "unreachable")

    print("\n[nest: the step and the verdict read one classifier, in every state]")
    SAMPLES = {
        "filter_missing": line("00:01", "NightmareNestTask", outcome._NEST_FILTER_MISSING),
        "not_found": line("00:01", "NightmareNestTask", "nightmare nest: 列表里没找到指定的点位 ['落渊南丘']"),
        "count_unread": line("00:01", "NightmareNestTask", "nightmare nest: " + outcome._NEST_COUNT_UNREAD),
        "full": line("00:01", "NightmareNestTask", "nightmare nest: 指定点位都已打满，跳过"),
        "fought": line("00:01", "NightmareNestTask", "enter combat None"),
        "partly": line("00:01", "NightmareNestTask", "enter combat None")
                  + line("00:02", "NightmareNestTask",
                         "nightmare nest: 传送两次都不过去，这一轮不打了 go_nest:48:18（梦枢天罗残象聚落）"),
        "unreachable": line("00:01", "NightmareNestTask", "nightmare nest unreachable, skip this run"),
        "failed": line("00:01", "NightmareNestTask", "opened gray_book_boss")
                  + "2026-10-13 10:00:02,000 ERROR TaskExecutor DailyTask:NightmareNestTask Failed\n",
        "quit": line("00:01", "NightmareNestTask", "opened gray_book_boss"),
    }
    for key, text in SAMPLES.items():
        check(f"{key}: nest_state", nest_state(text), key)
        verdict = [c for c in outcome.okww_checks(text, expect_nest=True, expect_daily=False, expect_stamina=False)
                   if c.label.startswith("残象聚落") and not c.label.startswith(("残象聚落只刷", "残象聚落没进"))]
        step = collector_okww._nest_step(text)
        bare = step in ("残象聚落", "梦魇巢穴")
        check(f"{key}: step booked as farmed ⇔ verdict 「残象聚落」 ok", bare,
              bool(verdict) and verdict[0].ok and verdict[0].label == "残象聚落")
        check(f"{key}: step and verdict agree on done / not done", ("已刷满" in step or bare), verdict[0].ok)
    check("fought, then the task failed: still booked as fought by both",
          (nest_state(SAMPLES["fought"] + SAMPLES["failed"]),
           collector_okww._nest_step(SAMPLES["fought"] + SAMPLES["failed"])), ("fought", "梦魇巢穴"))


def _part_okww_upstream_no_farm():
    """When upstream's own gate skips the stamina farm, the verdict says so."""

    from ark_relay.features import outcome

    T = "2026-10-14 09:{:02d}:00,000 {} TaskExecutor {}"
    OPEN = [T.format(27, "INFO", "DailyTask:open_daily"),
            T.format(27, "INFO", "DailyTask:info_set current daily progress 180"),
            T.format(27, "INFO", "DailyTask:info_set total daily points 60")]
    LEFTOVER = T.format(28, "INFO", "DailyTask:上游这趟不刷体力（已用 180/180，活跃度满 False），按「刷到空」把剩下的体力刷掉")
    DONE = T.format(40, "INFO", "DailyTask:Daily Task Completed")

    def stamina(*lines):
        got = [c for c in outcome.okww_checks("\n".join([*OPEN, *lines, DONE]) + "\n", expect_nest=False)
               if c.label == "刷体力"]
        return [(c.ok, c.detail) for c in got]

    print("[180/180, the overlay's leftover farm fought: green]")
    check("green", stamina(LEFTOVER, T.format(29, "INFO", "TacetTask:enter combat None")), [(True, "")])

    print("\n[180/180, the leftover farm raised: red, saying so]")
    got = stamina(LEFTOVER, T.format(29, "ERROR", "DailyTask:补刷体力出错，照常领日常奖励: Teleport failed"))
    check("red", [ok for ok, _ in got], [False])
    check("names upstream's skip and the error",
          bool(got) and "上游这趟不刷体力" in got[0][1] and "补刷时出错：Teleport failed" in got[0][1], True)

    print("\n[180/180, no leftover line at all: red, upstream's gate named]")
    got = stamina()
    check("red", [ok for ok, _ in got], [False])
    check("says upstream read 180/180 and the leftover farm did not run",
          bool(got) and "180/180" in got[0][1] and "补刷没有跑到" in got[0][1], True)

    print("\n[under 180, nothing: the old wording]")
    text = "\n".join([T.format(27, "INFO", "DailyTask:info_set current daily progress 0"), DONE]) + "\n"
    check("unchanged", [c.detail for c in outcome.okww_checks(text, expect_nest=False) if c.label == "刷体力"],
          ["既没进本，也没说体力不足"])


def _part_okww_nest_capture():
    """Nest overrides, part two: both entries, an unread count, an adapted install."""
    import re
    import types

    from ark_relay.features import outcome as collector_okww, outcome
    from ark_relay.features import okww_overlay

    UPSTREAM = (fx_dir(Path(__file__), "gamesim") / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task" / "NightmareNestTask.py.txt").read_text(encoding="utf-8")

    def upstream_class(text=UPSTREAM):
        class WWOneTimeTask:
            def run(self):
                pass

            def tr(self, msg):          # ok-script's translation, English here
                return msg

        ok = types.ModuleType("ok")
        ok.Logger = types.SimpleNamespace(get_logger=lambda name: types.SimpleNamespace(info=lambda *a: None))
        ok.run_task = lambda *a, **kw: None
        combat = types.ModuleType("src.task.BaseCombatTask")
        combat.BaseCombatTask = type("BaseCombatTask", (), {})
        combat.CharRevivedException = type("CharRevivedException", (Exception,), {})
        onetime = types.ModuleType("src.task.WWOneTimeTask")
        onetime.WWOneTimeTask = WWOneTimeTask
        sys.modules.update({"ok": ok, "cv2": types.ModuleType("cv2"), "config": types.SimpleNamespace(config={}),
                            "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
                            "src.task.BaseCombatTask": combat, "src.task.WWOneTimeTask": onetime})
        path = tmpdir() / "NightmareNestTask.py"
        path.write_text(text, encoding="utf-8")
        mod = types.ModuleType("src.task.NightmareNestTask")
        mod.__file__ = str(path)
        exec(compile(text, str(path), "exec"), mod.__dict__)
        sys.modules["src.task.NightmareNestTask"] = mod
        return mod.NightmareNestTask

    def overlay(cls_text=UPSTREAM):
        cls = upstream_class(cls_text)
        ns = {}
        exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
        for k in ("_applied", "_skipped", "_adapted"):
            ns[k].clear()
        ns["TaskDisabledException"] = type("TaskDisabledException", (Exception,), {})
        ns["_install_nest"]()
        return cls, ns

    class Box:
        def __init__(self, name, y, height=30):
            self.name, self.x, self.y, self.width, self.height = name, 889, y, 198, height

    def fake(cls, pages, ns, only="落渊南丘", capture=False):
        """A task whose screen is pages[page]; a page may be a list of reads, used in turn."""
        t = object.__new__(cls)
        t.config = {ns["ONLY_NESTS"]: only, "Which to Farm": ["Tacet Discord Nest"]}
        t.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        t._unreachable_nests, t._nest_deaths, t.queues = set(), {}, []
        t._nest_tab_of_current_nest = "go_nest"
        t._capture_mode = t._capture_success = False
        t.page, t.reads, t.events, t.errors, t.infos, t.fought, t.shots = 0, 0, [], [], [], [], []

        def ocr(x, y, to_x, to_y, match=None):
            screen = pages[t.page]
            if screen and isinstance(screen[0], list):          # successive reads of one page
                screen = screen[min(t.reads, len(screen) - 1)]
                if match:
                    t.reads += 1
            return [Box(b.name, b.y, b.height) for b in screen if not match or match.search(b.name)]
        t.ocr = ocr
        t.open_boss_book = lambda name: setattr(t, "page", 0)
        t.click = lambda *a, **kw: setattr(t, "page", 1) if a and a[0] == 0.9730 else None
        t.openF2Book = lambda name: t.events.append("book")
        # DailyTask replaces ensure_main with a no-op before run_capture_mode (DailyTask.py:98).
        t.ensure_main = (lambda *a, **kw: None) if capture else (lambda time_out=0: t.events.append("main"))
        t.log_info = lambda msg, notify=False: t.infos.append(msg)
        t.log_error = lambda msg, notify=False: t.errors.append((msg, notify))
        t.screenshot = lambda name: t.shots.append(name)
        t.sleep = lambda s: None
        t.width_of_screen = lambda f: f * 1920
        t.height_of_screen = lambda f: f * 1080

        def combat_nest(nest):
            t.fought.append(nest.cache_key)
            t._capture_success = capture       # a capture lap that got its echo ends the loop
        t.combat_nest = combat_nest
        return t

    NAME_NEW, NAME_NANQIU = Box("新区残象聚落", 300), Box("落渊南丘残象聚落", 450)
    PAGE2 = [Box("别的残象聚落", 300), Box("已击败残象：3/24", 374)]

    def page1(nanqiu):
        return [NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU, Box(f"已击败残象：{nanqiu}", 524)]

    # 南丘's count box centre is (524 + 15) / 1080 = 0.499 of the screen: row slot 25.
    NANQIU_KEY = "go_nest:41:25"

    Nest, ns = overlay()

    print("\n[两个入口都换上了]")
    check("run 与 run_capture_mode 都换上了", all(f"NightmareNestTask.{m}" in ns["_applied"]
                                                for m in ("run", "run_capture_mode")))
    check("没有跳过的", ns["_skipped"], [])

    for entry in ("run", "run_capture_mode"):
        capture = entry == "run_capture_mode"
        print(f"\n[{entry}：上一轮留下的状态先清掉]")
        t = fake(Nest, [page1("10/41"), PAGE2], ns, capture=capture)
        # Left over from a previous call on the same instance (DailyTask keeps one):
        # without the reset this stamp reads as 「tried, no progress」 and 南丘 is skipped.
        t._ark_nest_tried = {f"{NANQIU_KEY}@10"}
        t._ark_nest_progress = {NANQIU_KEY: "10"}
        t._ark_nest_seen, t._ark_nest_missed = True, ["旧的"]
        getattr(t, entry)()
        check("进了南丘", t.fought[:1], [NANQIU_KEY])
        if capture:
            check("抓到声骸就收手（只打一局）", len(t.fought), 1)
        check("过滤来源本轮说了", any("nightmare nest: 只刷 ['落渊南丘']" in m for m in t.infos))
        check("没报错", t.errors, [])

        print(f"\n[{entry}：两屏都没有南丘，结束时报一次]")
        t = fake(Nest, [[NAME_NEW, Box("已击败残象：0/48", 374)], PAGE2], ns, capture=capture)
        getattr(t, entry)()
        check("一局没打", t.fought, [])
        check("报了一次列表里没找到，并推送", [("列表里没找到指定的点位" in e[0], e[1]) for e in t.errors],
              [(True, True)])

    print("\n[find_nest 换不上：两个入口都不刷]")
    gone = UPSTREAM.replace("    def find_nest(self):", "    def find_nest_renamed(self):")
    check("样本确实改到了", gone != UPSTREAM)
    Nest3, ns3 = overlay(gone)
    check("find_nest 记为没贴上", [s["what"] for s in ns3["_skipped"]], ["NightmareNestTask.find_nest"])
    for entry in ("run", "run_capture_mode"):
        t = fake(Nest3, [page1("10/41"), PAGE2], ns3, capture=entry == "run_capture_mode")
        getattr(t, entry)()
        check(f"{entry} 一局没打", t.fought, [])
        check(f"{entry} 说了这一轮不刷", any("这一轮不刷巢穴" in m for m in t.infos))

    print("\n[南丘的名字读到了、计数没读到：停下、截图、报警，不说打满]")
    misread = [NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU, Box("已击败残象：1O/41", 524)]
    t = fake(Nest, [misread, PAGE2], ns)
    t.run()
    check("一局没打（也没去打上面那个 0/48）", t.fought, [])
    check("截了 nest_count_unread", t.shots, ["nest_count_unread"])
    check("报警一次，并推送", [e[1] for e in t.errors], [True])
    msg = t.errors[0][0] if t.errors else ""
    check("报警写明计数没读到", ns["NEST_COUNT_UNREAD"] in msg)
    check("报警带着识字原文", "1O/41" in msg)
    check("报警写明不是打满", "不是打满" in msg)
    check("没说已打满", any("都已打满" in m for m in t.infos), False)

    print("\n[两个指定点位：一个满了、一个计数没读到 → 不能报「都已打满」]")
    two = [Box("落渊南丘残象聚落", 300), Box("已击败残象：41/41", 374),
           Box("别处残象聚落", 450), Box("已击败", 524)]
    t = fake(Nest, [two, PAGE2], ns, only="落渊南丘,别处")
    t.run()
    check("一局没打", t.fought, [])
    check("没说已打满", any("都已打满" in m for m in t.infos), False)
    check("报的是计数没读到", [ns["NEST_COUNT_UNREAD"] in e[0] for e in t.errors], [True])

    print("\n[计数那一行一时没渲染出来：再看一眼，读到了就照常刷，不报警]")
    late = [[NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU],      # wanted_rows' wait: one count is up
            [NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU],      # find_nest's first read: 南丘 not yet
            page1("10/41")]                                              # the second look
    t = fake(Nest, [late, PAGE2], ns)
    t.run()
    check("进了南丘", t.fought[:1], [NANQIU_KEY])
    check("没报警", t.errors, [])
    check("没截计数没读到的图", "nest_count_unread" in t.shots, False)

    print("\n[上游改了 find_nest、按新版适配装上：每轮在 OK-WW 日志里说一句]")
    changed = UPSTREAM.replace("counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re)",
                               "counts = self.ocr(0.35, 0.3, 1, 0.96, match=self.count_re)  # moved again")
    check("样本确实改到了", changed != UPSTREAM)
    Nest2, ns2 = overlay(changed)
    check("记在已适配里", [a["what"] for a in ns2["_adapted"]], ["NightmareNestTask.find_nest"])
    for entry in ("run", "run_capture_mode"):
        t = fake(Nest2, [page1("10/41"), PAGE2], ns2, capture=entry == "run_capture_mode")
        getattr(t, entry)()
        check(f"{entry} 说了过滤是适配装上的", any(ns2["NEST_ADAPTED"] in m for m in t.infos))
        check(f"{entry} 照样只进南丘", t.fought[:1], [NANQIU_KEY])
    t = fake(Nest, [page1("10/41"), PAGE2], ns)
    t.run()
    check("没适配时不说", any(ns["NEST_ADAPTED"] in m for m in t.infos), False)

    print("\n[中继读日志：两句新话进了结果判定和日报]")
    check("计数没读到：覆盖层与判定用同一句", ns["NEST_COUNT_UNREAD"], outcome._NEST_COUNT_UNREAD)
    check("已适配：覆盖层与判定用同一句", ns["NEST_ADAPTED"], outcome._NEST_ADAPTED)
    # Lines as OK-WW writes them: ok-script prefixes log_info / log_error with the task name.
    head = ("2026-10-06 09:20:01 INFO TaskExecutor NightmareNestTask:open_boss_book canxiang\n"
            "2026-10-06 09:20:02 INFO TaskExecutor NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）\n")
    unread_log = head + ("2026-10-06 09:20:05 ERROR TaskExecutor NightmareNestTask:nightmare nest: "
                         f"{ns['NEST_COUNT_UNREAD']}（名字所在行 [465]），这一屏不刷——**不是打满**。\n")
    steps = collector_okww._okww_steps(unread_log, 0)
    check("日报：计数没读到", [s for s in steps if "残象聚落" in s], ["残象聚落（计数没读到，停下没刷）"])
    verdict = [k for k in outcome.okww_checks(unread_log, expect_nest=True) if "残象聚落" in k.label]
    check("判定：残象聚落不算过", [(k.ok, "计数没读到" in k.detail) for k in verdict], [(False, True)])
    adapted_log = head + (f"2026-10-06 09:20:02 INFO TaskExecutor NightmareNestTask:nightmare nest: "
                          f"{ns['NEST_ADAPTED']}，这一轮请核对只进了指定点位\n"
                          "2026-10-06 09:21:00 INFO TaskExecutor NightmareNestTask:enter combat None\n")
    steps = collector_okww._okww_steps(adapted_log, 0)
    check("日报：残象聚落旁写着按新版适配", [s for s in steps if "残象聚落" in s],
          ["残象聚落（只刷指定点位的过滤按 OK-WW 新版适配，请核对）"])
    plain = head + "2026-10-06 09:21:00 INFO TaskExecutor NightmareNestTask:enter combat None\n"
    check("没适配时日报照旧", [s for s in collector_okww._okww_steps(plain, 0) if "残象聚落" in s], ["残象聚落"])


def _part_okww_nest_expected():
    """Whether a run should have farmed nests follows upstream's own condition."""
    import json

    from ark_relay.features.handle import _okww_nest_expected

    def automas(daily=None, nest=None):
        root = tmpdir()
        d = root / "data" / "okww-id" / "Default" / "ConfigFile"
        d.mkdir(parents=True)
        if daily is not None:
            (d / "DailyTask.json").write_text(json.dumps(daily), encoding="utf-8")
        if nest is not None:
            (d / "NightmareNestTask.json").write_text(json.dumps(nest), encoding="utf-8")
        return root

    ADDS = "Additional Tasks to Run After Daily Task"
    ECHO = "Farm Nightmare Nest for Daily Echo"
    AUTO = "Auto Farm all Nightmare Nest"

    print("[Auto Farm all Nightmare Nest: nests run]")
    check("in the additional tasks", _okww_nest_expected(automas({ADDS: [AUTO], ECHO: False})), True)

    print("\n[the daily-echo flag: only when the farm target is not Tacet Suppression]")
    check("flag on, farming Tacet (upstream skips the nest)",
          _okww_nest_expected(automas({ECHO: True, "Which to Farm": "Tacet Suppression", ADDS: []})), False)
    check("flag on, farming Forgery", _okww_nest_expected(automas({ECHO: True, "Which to Farm": "Forgery Challenge"})), True)
    check("flag absent = default on; target absent = default Tacet", _okww_nest_expected(automas({ADDS: []})), False)
    check("flag absent = default on, farming Simulation",
          _okww_nest_expected(automas({"Which to Farm": "Simulation Challenge"})), True)
    check("flag off, farming Forgery", _okww_nest_expected(automas({ECHO: False, "Which to Farm": "Forgery Challenge"})), False)

    print("\n[a leftover nest filter does not make nests run]")
    check("filter text, Auto Farm unticked, farming Tacet",
          _okww_nest_expected(automas({ECHO: True, ADDS: []}, {"Only Farm These Nests": "落渊南丘"})), False)

    print("\n[the config cannot be read: None, never a guess]")
    check("no automas dir", _okww_nest_expected(None), None)
    check("no DailyTask.json (only the nest config)",
          _okww_nest_expected(automas(None, {"Only Farm These Nests": "落渊南丘"})), None)

    print("\n[the verdict's 「cannot read the config」 item names the file that decides (item 19)]")
    import types

    from ark_relay.features import handle as verdict

    seen = {}
    real_judged = verdict._judged
    verdict._judged = lambda rec, checks, *a, **k: seen.setdefault("checks", checks)
    try:
        log = tmpdir() / "OK-WW.log"
        log.write_text("Daily Task Completed\n", encoding="utf-8")
        rec = types.SimpleNamespace(script="OK-WW", log_path=log)
        eng = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=automas(None, {"Only Farm These Nests": "x"})))
        verdict._verify_outcome(eng, rec)
    finally:
        verdict._judged = real_judged
    detail = next((c.detail for c in seen.get("checks", []) if c.label == "能读到 OK-WW 生效中的配置"), "")
    check("names DailyTask.json", "DailyTask.json" in detail, True)
    check("no longer names NightmareNestTask.json", "NightmareNestTask.json" in detail, False)


def _part_okww_nest_fought_then_full():
    """A nest fought until full is 「fought」, not 「full, skipped」 (audit 2026-10-13 item 11)."""

    from ark_relay.features import outcome as co, outcome

    T = "2026-10-13 09:27:{:02d},000 INFO TaskExecutor NightmareNestTask:{}"
    CLICK = T.format(34, "left_click 已击败残象：0/48 (1729, 348) after_sleep 2")
    FIGHT = T.format(46, "enter combat None")
    FULL = T.format(59, "nightmare nest: 指定点位都已打满，跳过（截图 nest_all_full）")

    print("[fought, then all full: fought]")
    both = "\n".join([CLICK, FIGHT, FULL])
    check("nest_state", outcome.nest_state(both), "fought")
    check("the step does not say 已刷满", "已刷满" in co._nest_step(both), False)
    got = [c for c in outcome.okww_checks(both, expect_nest=True) if c.label.startswith("残象聚落")]
    check("the verdict item", [(c.label, c.ok) for c in got], [("残象聚落", True)])

    print("\n[full before any fight: a skip]")
    check("nest_state", outcome.nest_state(FULL), "full")
    got = [c for c in outcome.okww_checks(FULL, expect_nest=True) if c.label.startswith("残象聚落")]
    check("the verdict item", [(c.label, c.ok) for c in got], [("残象聚落（已满，跳过）", True)])


def _part_okww_nest_names():
    """「Only these nests」: the cap rule and the overlay's nest names, both must pass."""

    from ark_relay.features import outcome

    T = "2026-10-14 09:00:{:02d},000 INFO TaskExecutor NightmareNestTask:{}"

    def lines(*events, only="落渊南丘"):
        out = [T.format(0, f"nightmare nest: 只刷 {[n for n in only.split(',')]}")]
        for i, (kind, val) in enumerate(events, 1):
            out.append(T.format(i, f"left_click 已击败残象：0/{val} (1729, 347) after_sleep 2" if kind == "click"
                                else f"nightmare nest: nest name: {val}"))
        out.append(T.format(59, "enter combat None"))          # a fight, so the scope item is said
        return "\n".join(out) + "\n"

    def scope(text, only):
        return [(c.ok, c.detail) for c in outcome.nest_filter_checks(text, only) if c.label == "残象聚落没进别的点位"]

    print("[review case: two clicks both logged 落渊南丘, caps 48 and 41 -> red]")
    text = lines(("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41), ("name", "落渊南丘残象聚落"))
    got = scope(text, "落渊南丘")
    check("red", [ok for ok, _ in got], [False])
    check("says the two caps", "48、41" in (got[0][1] if got else ""), True)

    print("\n[real order (name, then click), both wanted nests: green]")
    text = lines(("name", "梦枢天罗残象聚落"), ("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41),
                 only="梦枢天罗,落渊南丘")
    check("green", [ok for ok, _ in scope(text, "梦枢天罗,落渊南丘")], [True])
    check("each click gets the name logged before it", outcome._nest_clicks(text),
          [("48", "梦枢天罗残象聚落"), ("41", "落渊南丘残象聚落")])

    print("\n[two wanted nests, a third click on the neighbouring 48 row under 落渊南丘's name: red]")
    text = lines(("name", "梦枢天罗残象聚落"), ("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41),
                 ("name", "落渊南丘残象聚落"), ("click", 48), only="梦枢天罗,落渊南丘")
    got = scope(text, "梦枢天罗,落渊南丘")
    check("red although only two caps in all", [ok for ok, _ in got], [False])
    check("names the name with two caps", "「落渊南丘」" in (got[0][1] if got else ""), True)

    print("\n[a 「?」 click still counts for the cap rule]")
    text = lines(("name", "落渊南丘残象聚落"), ("click", 41), ("name", "?"), ("click", 48))
    check("named 41 + unnamed 48 for one wanted name: red", [ok for ok, _ in scope(text, "落渊南丘")], [False])

    print("\n[old logs without name lines: the cap rule as before]")
    text = lines(("click", 48), ("click", 48))
    check("same cap twice: green", [ok for ok, _ in scope(text, "落渊南丘")], [True])
    text = lines(("click", 48), ("click", 41))
    check("two caps for one name: red", [ok for ok, _ in scope(text, "落渊南丘")], [False])

    print("\n[the Mac-side checkers pass the configured names, not a literal (10-15, alarm f7a4bb6a)]")
    import re
    from ark_relay.core.mastercfg import ONLY_NESTS
    text = lines(("name", "梦枢天罗残象聚落"), ("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41),
                 only=",".join(ONLY_NESTS))
    check("the 10-15 run under the configured names: green", [ok for ok, _ in scope(text, ",".join(ONLY_NESTS))], [True])
    LIB = Path(__file__).resolve().parents[2] / "scripts" / "mac" / "lib"
    literal = re.compile(r"nest_filter_checks\(\s*[^,()]+,\s*([\"'])[^\"']*\1\s*\)")
    for name in ("okww_effective.py", "healthcheck.py"):
        src = (LIB / name).read_text(encoding="utf-8")
        check(f"{name} calls nest_filter_checks", "nest_filter_checks(" in src, True)
        check(f"{name}: no literal nest name passed to it", literal.findall(src), [])


def _part_okww_nest_travel_retry():
    """A nest given up after two failed travels is 「not done」 in the verdict and the report, even when another nest was fought.
    """

    from ark_relay.features import okww_overlay
    from ark_relay.features import outcome as co, outcome

    REAL = (fx_dir(Path(__file__), "fixtures") / "okww-1027-nest-unreachable.log").read_text(encoding="utf-8")
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    GAVE_UP = ns["NEST_GAVE_UP_LINE"]

    def verdict(text):
        got = [c for c in outcome.okww_checks(text, expect_nest=True, expect_daily=False, expect_stamina=False)
               if c.label == "残象聚落"]
        return (got[0].ok, got[0].detail) if got else None

    def after(text, at, msg):
        """`text` with one NightmareNestTask line inserted before the line stamped `at`."""
        line = f"2026-10-27 {at},000 INFO TaskExecutor NightmareNestTask:{msg}\n"
        i = text.index(f"2026-10-27 {at}")
        return text[:i] + line + text[i:]

    print("[the real 10-27 log, before the overlay retried: booked 「fought」 - the gap]")
    check("nest_state", outcome.nest_state(REAL), "fought")
    check("no nest given up (the line did not exist yet)", outcome.nests_given_up(REAL), [])

    print("\n[retried and travelled: still 「fought」, nothing named]")
    retried = after(REAL, "09:25:05,676", "nightmare nest: 传送不过去，马上再试一次 go_nest:48:18")
    check("nest_state", outcome.nest_state(retried), "fought")
    check("verdict ok", verdict(retried), (True, "有进本/战斗记录"))
    check("step is the bare name", co._nest_step(retried), "残象聚落")

    print("\n[the second try failed too: 「partly」, red, the nest named]")
    both = after(retried, "09:25:18,365", f"{GAVE_UP}go_nest:48:18（梦枢天罗残象聚落）")
    check("the relay's pattern reads the overlay's own line", outcome.nests_given_up(both), ["梦枢天罗残象聚落"])
    check("nest_state", outcome.nest_state(both), "partly")
    check("verdict red, names the nest", verdict(both),
          (False, "有一处点位传送两次都不过去，那一处没打（梦枢天罗残象聚落）"))
    check("step says which one was not farmed", co._nest_step(both), "残象聚落（有一处传送两次都不过去，那一处没打）（梦枢天罗残象聚落）")

    print("\n[given up and nothing else fought: 「unreachable」 as before]")
    alone = REAL[:REAL.index("2026-10-27 09:25:05,676")] + f"2026-10-27 09:25:05,700 INFO TaskExecutor NightmareNestTask:{GAVE_UP}go_nest:48:18（梦枢天罗残象聚落）\n"
    check("nest_state", outcome.nest_state(alone), "unreachable")
    check("verdict red", verdict(alone)[0], False)


def _part_okww_nest_v373():
    """OK-WW v3.7.3 changed find_nest; the 「only 落渊南丘」 filter must survive that and the next one.
    """
    import re
    import types

    from ark_relay.core import texts
    from ark_relay.features import okww_overlay

    UPSTREAM = (fx_dir(Path(__file__), "gamesim") / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task" / "NightmareNestTask.py.txt").read_text(encoding="utf-8")

    def upstream_class(text=UPSTREAM):
        """Upstream's NightmareNestTask, loaded from a real file so inspect.getsource works."""
        class WWOneTimeTask:
            def run(self):
                pass

            def tr(self, msg):          # ok-script's translation, English here
                return msg

        ok = types.ModuleType("ok")
        ok.Logger = types.SimpleNamespace(get_logger=lambda name: types.SimpleNamespace(info=lambda *a: None))
        combat = types.ModuleType("src.task.BaseCombatTask")
        combat.BaseCombatTask = type("BaseCombatTask", (), {})
        combat.CharRevivedException = type("CharRevivedException", (Exception,), {})
        onetime = types.ModuleType("src.task.WWOneTimeTask")
        onetime.WWOneTimeTask = WWOneTimeTask
        sys.modules.update({"ok": ok, "cv2": types.ModuleType("cv2"), "config": types.SimpleNamespace(config={}),
                            "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
                            "src.task.BaseCombatTask": combat, "src.task.WWOneTimeTask": onetime})
        ok.run_task = lambda *a, **kw: None
        path = tmpdir() / "NightmareNestTask.py"
        path.write_text(text, encoding="utf-8")
        mod = types.ModuleType("src.task.NightmareNestTask")
        mod.__file__ = str(path)
        exec(compile(text, str(path), "exec"), mod.__dict__)
        sys.modules["src.task.NightmareNestTask"] = mod
        return mod.NightmareNestTask

    def overlay():
        ns = {}
        exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
        for k in ("_applied", "_skipped", "_adapted"):
            ns[k].clear()
        ns["TaskDisabledException"] = type("TaskDisabledException", (Exception,), {})
        return ns

    class Box:
        def __init__(self, name, y, height=30):
            self.name, self.x, self.y, self.width, self.height = name, 889, y, 198, height

        def __repr__(self):
            return self.name

    def fake(cls, pages, ns, only="落渊南丘"):
        """A task whose screen is `pages[page]`; go_nest_scroll's click turns the page."""
        t = object.__new__(cls)
        t.config = {ns["ONLY_NESTS"]: only, "Which to Farm": ["Tacet Discord Nest"]}   # the master's value
        t.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        t._unreachable_nests, t._nest_deaths, t.queues = set(), {}, []
        t._nest_tab_of_current_nest = "go_nest"
        t.page, t.tops, t.events, t.errors, t.infos, t.fought = 0, [], [], [], [], []

        def ocr(x, y, to_x, to_y, match=None):
            t.tops.append(y)
            # Fresh boxes every read, as OCR gives: find_nest moves the one it returns.
            return [Box(b.name, b.y, b.height) for b in pages[t.page] if not match or match.search(b.name)]
        t.ocr = ocr
        t.open_boss_book = lambda name: setattr(t, "page", 0)
        t.click = lambda *a, **kw: setattr(t, "page", 1) if a and a[0] == 0.9730 else None
        t.openF2Book = lambda name: t.events.append("book")
        t.ensure_main = lambda time_out=0: t.events.append("main")
        t.log_info = lambda msg, notify=False: t.infos.append(msg)
        t.log_error = lambda msg, notify=False: t.errors.append(msg)
        t.sleep = lambda s: None
        t.width_of_screen = lambda f: f * 1920
        t.height_of_screen = lambda f: f * 1080
        t.combat_nest = lambda nest: t.fought.append(nest.cache_key)
        return t

    Nest = upstream_class()
    ns = overlay()

    print("\n[钉的是 v3.7.3 的 find_nest]")
    check("上游（机器上装的版本）find_nest 的哈希就是我们钉的", ns["_src_sha"](Nest.find_nest), ns["_NEST_FIND_SHA"])
    check("识字区上沿从上游读出来是 0.25", ns["_upstream_nest_top"](Nest.find_nest), 0.25)
    ns["_install_nest"]()
    check("find_nest 换上了", "NightmareNestTask.find_nest" in ns["_applied"])
    check("没有跳过的", ns["_skipped"], [])
    check("也没有要适配的", ns["_adapted"], [])

    NAME_NEW, NAME_NANQIU = Box("新区残象聚落", 300), Box("落渊南丘残象聚落", 450)

    def page1(nanqiu):
        return [NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU, Box(f"已击败残象：{nanqiu}", 524)]

    PAGE2 = [Box("别的残象聚落", 300), Box("已击败残象：3/24", 374)]

    print("\n[南丘没满：只进南丘，不碰上面那个 0/48]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns)
    t.run()
    check("打了一局", len(t.fought), 1)
    check("进的是 /41 那一行（南丘）", ":41:" in (t.fought or [""])[0])
    check("识字区一律用 0.25", set(t.tops), {0.25})
    check("no extra ensure_main between the books when nothing was unreachable", t.events[:3], ["main", "book", "book"])
    check("计数没涨就不再进", any("no progress after an attempt" in m for m in t.infos))
    check("没报错", t.errors, [])

    print("\n[南丘满了：第二屏没有南丘也不报错]")
    t = fake(Nest, [page1("41/41"), PAGE2], ns)
    t.run()
    check("一局没打", t.fought, [])
    check("说了已打满", any("指定点位都已打满" in m for m in t.infos))
    check("第二屏找不到南丘不算错", t.errors, [])

    print("\n[两屏都没有南丘：结束时报一次]")
    t = fake(Nest, [[NAME_NEW, Box("已击败残象：0/48", 374)], PAGE2], ns)
    t.run()
    check("一局没打", t.fought, [])
    check("只报一次", len(t.errors), 1)
    check("报的是列表里没找到", "列表里没找到指定的点位" in (t.errors or [""])[0])

    print("\n[上游下次再改 find_nest：照样换上并按新版读识字区，不跳过]")
    changed = UPSTREAM.replace("counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re)",
                               "counts = self.ocr(0.35, 0.3, 1, 0.96, match=self.count_re)  # moved again")
    check("样本确实改到了", changed != UPSTREAM)
    Nest2 = upstream_class(changed)
    ns2 = overlay()
    ns2["_install_nest"]()
    check("find_nest 仍然换上了", "NightmareNestTask.find_nest" in ns2["_applied"])
    check("记在「已适配」里", [a["what"] for a in ns2["_adapted"]], ["NightmareNestTask.find_nest"])
    check("不在「没贴上」里", ns2["_skipped"], [])
    t = fake(Nest2, [page1("10/41"), PAGE2], ns2)
    t.run()
    check("识字区跟着上游改成 0.3", set(t.tops), {0.3})
    check("照样只进南丘", ":41:" in (t.fought or [""])[0])

    print("\n[进点位和传送不过去都留图（中继二 10-05 23:3x）]")
    check("进点位、传送两处都换上了", all(x in ns["_applied"] for x in (
        "NightmareNestTask.combat_nest", "NightmareNestTask._travel_to_nest_or_skip")))
    t = fake(Nest, [page1("10/41"), PAGE2], ns)
    del t.combat_nest
    t.shots, t.backs = [], []
    t.screenshot = lambda name: t.shots.append(name)
    t.wait_feature = lambda *a, **kw: (_ for _ in ()).throw(Exception("wait_feature timeout"))
    try:
        Nest.combat_nest(t, Box("落渊南丘残象聚落", 450))
    except Exception:  # noqa: BLE001
        pass
    check("点进点位前截了列表", t.shots[:1], ["nest_go"])
    check("日志说了点进点位", any("点进点位" in m for m in t.infos))
    t.shots = []
    t.wait_until = lambda *a, **kw: None          # no 快速旅行 button: unreachable
    t.back = lambda after_sleep=0: t.backs.append(1)
    nest = types.SimpleNamespace(cache_key="落渊南丘:41:450")
    check("传送不过去照上游返回 False", Nest._travel_to_nest_or_skip(t, nest), False)
    check("传送前后各一张图", t.shots, ["nest_travel", "nest_unreachable"])
    check("上游那句 unreachable 照样写", any("nightmare nest unreachable" in m for m in t.infos))
    check("我们那句「传送不过去」也写了（日报靠它核这层在跑）", any("nightmare nest: 传送不过去" in m for m in t.infos))

    print("\n[find_nest 根本换不上：这一轮不刷，绝不按上游刷全部]")
    gone = UPSTREAM.replace("    def find_nest(self):", "    def find_nest_renamed(self):")
    Nest3 = upstream_class(gone)
    Nest3.find_nest = Nest3.find_nest_renamed
    del Nest3.find_nest
    ns3 = overlay()
    ns3["_install_nest"]()
    check("find_nest 记为没贴上", [s["what"] for s in ns3["_skipped"]], ["NightmareNestTask.find_nest"])
    check("原因说的是方法没了，不是上沿读不出", ["没有这个方法了" in s["why"] for s in ns3["_skipped"]], [True])
    t = fake(Nest3, [page1("10/41"), PAGE2], ns3)
    t.run()
    check("一局没打", t.fought, [])
    check("说了这一轮不刷", any("这一轮不刷巢穴" in m for m in t.infos))

    print("\n[上游的识字区上沿读不出来：不猜 0.25，记为没贴上进群，这一轮不刷]")
    OCR_LINE = "counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re)"
    unreadable = UPSTREAM.replace(OCR_LINE, "box = (0.35, 0.25, 1, 0.96)\n"
                                  "        counts = self.ocr(*box, match=self.count_re)")
    too_low = UPSTREAM.replace(OCR_LINE, "counts = self.ocr(0.35, 0.7, 1, 0.96, match=self.count_re)")
    check("样本确实改到了", unreadable != UPSTREAM and too_low != UPSTREAM)
    for label, text in (("正则对不上", unreadable), ("读到的值不像样（0.7）", too_low)):
        Nest4 = upstream_class(text)
        ns4 = overlay()
        check(f"{label}：读不出上沿", ns4["_upstream_nest_top"](Nest4.find_nest), None)
        ns4["_install_nest"]()
        check(f"{label}：find_nest 没换上", "NightmareNestTask.find_nest" in ns4["_applied"], False)
        check(f"{label}：记为没贴上", [s["what"] for s in ns4["_skipped"]], ["NightmareNestTask.find_nest"])
        check(f"{label}：不记为已适配", ns4["_adapted"], [])
        check(f"{label}：别的巢穴改动照样换上", all(x in ns4["_applied"] for x in (
            "NightmareNestTask.run", "NightmareNestTask.get_nest_to_go")))
        t = fake(Nest4, [page1("10/41"), PAGE2], ns4)
        t.run()
        check(f"{label}：一局没打", t.fought, [])
        check(f"{label}：没拿任何上沿去识字（不猜 0.25）", t.tops, [])
        check(f"{label}：说了这一轮不刷", any("这一轮不刷巢穴" in m for m in t.infos))
        # The existing not-applied path, end to end: the overrides' own report file ->
        # okww_overlay.report_line -> the boot push title (boot_stages: alert=True, group).
        report = tmpdir() / "ark-okww-overlay.json"
        real_os, real_report = ns4["os"], okww_overlay.REPORT
        ns4["os"], ns4["REPORT"] = types.SimpleNamespace(name="nt"), str(report)
        try:
            ns4["_write_report"]()
        finally:
            ns4["os"] = real_os
        okww_overlay.REPORT = report
        try:
            line = okww_overlay.report_line()
        finally:
            okww_overlay.REPORT = real_report
        check(f"{label}：开机推送里有 find_nest 没贴上",
              "没贴上" in line and "NightmareNestTask.find_nest" in line and "上沿" in line)
        check(f"{label}：推送标题是没贴上", texts.patches(1, [line]), "⚠️ OK-WW 补丁有 1 条没贴上（共 1 条）")

    print("\n[daily: ensure_main is upstream's no-op lambda; an unreachable nest leaves the map open -> one back before the book]")
    ns5 = overlay()
    ns5["_install_nest"]()
    t = fake(Nest, [page1("10/41"), PAGE2], ns5)
    t.ensure_main = lambda *a, **kw: None            # DailyTask.py:99, verbatim shape
    t.world, t.shots = False, []
    t.in_team_and_world = lambda: t.world

    def _back(after_sleep=0):
        t.events.append("back")
        t.world = len([e for e in t.events if e == "back"]) >= 2   # upstream's back, then ours

    t.back = _back
    t.screenshot = lambda name: t.shots.append(name)
    t.find_one = lambda *a, **kw: None
    t._find_travel_button = lambda: None
    t.wait_until = lambda cond, **kw: None if cond == t._find_travel_button else cond()
    nest = types.SimpleNamespace(cache_key="落渊南丘:41:450")
    check("travel fails as upstream's does", Nest._travel_to_nest_or_skip(t, nest), False)
    check("upstream's own back ran, the map is still open", (t.events, t.world), (["back"], False))
    Nest.get_nest_to_go(t)
    check("one more back, then the book", t.events[:3], ["back", "back", "book"])
    check("no picture of a stuck map", "nest_map_still_open" in t.shots, False)

    print("\n[the world is already on screen after the unreachable nest -> no back (it would open the game menu)]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns5)
    t.ensure_main = lambda *a, **kw: None
    t.in_team_and_world = lambda: True
    t.back = lambda after_sleep=0: t.events.append("back")
    t._ark_close_map = True
    Nest.get_nest_to_go(t)
    check("straight to the book", t.events[:1], ["book"])

    print("\n[the back did not bring the world back -> picture and a log line, the book is tried anyway]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns5)
    t.ensure_main = lambda *a, **kw: None
    t.in_team_and_world = lambda: False
    t.back = lambda after_sleep=0: t.events.append("back")
    t.wait_until = lambda cond, **kw: cond()
    t.shots = []
    t.screenshot = lambda name: t.shots.append(name)
    t.box_of_screen = lambda *a: a
    t.ocr = lambda *a, **kw: []
    t._ark_close_map = True
    Nest.get_nest_to_go(t)
    check("one back, then the book", t.events[:2], ["back", "book"])
    check("picture of the stuck map", t.shots, ["nest_map_still_open"])
    check("said so in the log", any("关了一次地图，还是没回到大世界" in m for m in t.infos))

    print("\n[nothing unreachable -> get_nest_to_go never presses back]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns5)
    t.in_team_and_world = lambda: False
    t.back = lambda after_sleep=0: t.events.append("back")
    Nest.get_nest_to_go(t)
    check("no back", "back" in t.events, False)

    print("\n[the nest clicked is logged by name as well as by key: 「nightmare nest: nest name: <name>」]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns)
    t.run()
    key = t.fought[0]
    t.shots = []
    t.screenshot = lambda name: t.shots.append(name)
    t.wait_feature = lambda *a, **kw: (_ for _ in ()).throw(Exception("wait_feature timeout"))
    try:
        Nest.combat_nest(t, types.SimpleNamespace(cache_key=key))
    except Exception:  # noqa: BLE001
        pass
    check("the key line as before", any(m == f"nightmare nest: 点进点位 {key}（截图 nest_go）" for m in t.infos))
    check("the name line, as OCR read it beside the count",
          [m for m in t.infos if m.startswith("nightmare nest: nest name: ")], ["nightmare nest: nest name: 落渊南丘残象聚落"])
    check("the prefix is a constant the relay can import", ns["NEST_NAME_LINE"], "nightmare nest: nest name: ")
    t.infos = []
    try:
        Nest.combat_nest(t, types.SimpleNamespace(cache_key="go_nest:48:999"))
    except Exception:  # noqa: BLE001
        pass
    check("a key with no name read: 「?」", [m for m in t.infos if m.startswith("nightmare nest: nest name: ")],
          ["nightmare nest: nest name: ?"])

    print("\n[without the 只刷 filter the name is read too (one more read of the list), not 「?」]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns, only="")
    t.run()
    key = t.fought[0]
    t.screenshot = lambda name: None
    t.wait_feature = lambda *a, **kw: (_ for _ in ()).throw(Exception("wait_feature timeout"))
    try:
        Nest.combat_nest(t, types.SimpleNamespace(cache_key=key))
    except Exception:  # noqa: BLE001
        pass
    check("no filter: the first row's name, 「新区残象聚落」", [m for m in t.infos if m.startswith("nightmare nest: nest name: ")],
          ["nightmare nest: nest name: 新区残象聚落"])

    print("\n[10-27: a travel that failed once is tried again at once; only a second failure gives the nest up]")
    NestTarget = sys.modules["src.task.NightmareNestTask"].NestTarget
    MENGSHU = [Box("梦枢天罗残象聚落", 300), Box("已击败残象：0/48", 374),
               Box("落渊南丘残象聚落", 450), Box("已击败残象：10/41", 524)]

    def travel_fake(ns_, results):
        """A nest run whose 快速旅行 works or not by `results`, in order (True = travelled; then always works)."""
        t = fake(Nest, [MENGSHU, PAGE2], ns_, only="梦枢天罗,落渊南丘")
        tries = iter(results)
        t.shots = []
        t.screenshot = lambda name: t.shots.append(name)
        t.in_team_and_world = lambda: True               # the map closed: no extra back
        t.back = lambda after_sleep=0: t.events.append("back")
        t._find_first_feature = lambda names, threshold: None
        t.find_one = lambda *a, **kw: None
        t.wait_in_team_and_world = lambda **kw: True
        # Upstream's travel: no 快速旅行 button found = unreachable, as a click that did nothing.
        t.wait_until = lambda cond, **kw: (Box("gray_teleport", 1007) if next(tries, True) else None) \
            if cond == t._find_travel_button else cond()
        t.combat_nest = lambda nest: t.fought.append(nest.cache_key) if Nest._travel_to_nest_or_skip(t, nest) else None
        return t

    ns6 = overlay()
    ns6["_install_nest"]()
    t = travel_fake(ns6, [False, True])
    t.run()
    mengshu = [k for k in t.fought if k.endswith(":48:18")]
    check("fail, then travel: 梦枢天罗 fought on the second try", len(mengshu), 1)
    check("落渊南丘 still fought after it", len(t.fought), 2)
    check("said it tries again", [m for m in t.infos if "马上再试一次" in m], [f"nightmare nest: 传送不过去，马上再试一次 {mengshu[0]}"])
    check("no give-up line", any(m.startswith(ns6["NEST_GAVE_UP_LINE"]) for m in t.infos), False)

    t = travel_fake(ns6, [False, False, True])
    t.run()
    check("fail twice: 梦枢天罗 not fought, 落渊南丘 still is", [k.split(":")[1] for k in t.fought], ["41"])
    gave_up = [m for m in t.infos if m.startswith(ns6["NEST_GAVE_UP_LINE"])]
    check("the give-up line names the nest", [m.endswith("（梦枢天罗残象聚落）") for m in gave_up], [True])
    check("then cached as upstream does", any("skip cached unreachable nightmare nest" in m for m in t.infos), True)
    check("tried exactly twice", sum("nightmare nest unreachable" in m for m in t.infos), 2)

    print("\n[the retry is per run: the next run tries again, then retries again]")
    t2 = travel_fake(ns6, [False, True])
    t2.__dict__.update(_ark_travel_retried={"go_nest:48:18"})   # left over from an earlier run
    t2.run()
    check("a new run starts with nothing retried", [k.split(":")[1] for k in t2.fought], ["48", "41"])

    print("\n[a nest whose travel failed once is not cached: its key and no-progress stamp are dropped]")
    t = travel_fake(ns6, [False])
    key = "go_nest:48:18"
    t._ark_nest_progress, t._ark_nest_tried, t._ark_travel_retried = {key: "0"}, {f"{key}@0"}, set()
    t._unreachable_nests.add(key)                          # what upstream does for a NestTarget
    check("travel fails as upstream's", Nest._travel_to_nest_or_skip(t, NestTarget(Box("x", 0), key)), False)
    check("un-cached", key in t._unreachable_nests, False)
    check("stamp dropped", t._ark_nest_tried, set())
    check("both pictures as before", t.shots, ["nest_travel", "nest_unreachable"])


def _part_okww_no_challenge_window():
    """The no-challenge-button reason is told from the line of the same raise, by time."""

    from ark_relay.features import outcome as co

    STACK = "".join(f'  File "x{i}.py", line {i}, in f\n    g()\n' for i in range(200))   # ~5.5 KB
    NO_BTN = "2026-09-21 10:20:58,624 INFO TaskExecutor FarmEchoTask:找不到开启挑战，整屏读到: [失坠困咎之庭_1.00]\n"

    def head(ts):
        return (f"2026-09-21 {ts} ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card "
                "Traceback (most recent call last):\n")

    TAIL = "    raise RuntimeError('Teleport to boss failed') from e\nRuntimeError: Teleport to boss failed\n"
    SAY = "选了等级后没等到「开启挑战」"

    print("[the real fixture still reads as no challenge button]")
    real = (fx_dir(Path(__file__), "fixtures") / "m6-okww" / "0921-weekly.log").read_text(encoding="utf-8")
    check("0921-weekly", SAY in co._okww_error(real), True)

    print("\n[the line 0.02 s before, but more than 3000 characters back: found]")
    text = NO_BTN + STACK + head("10:20:58,644") + TAIL
    check("found by time", SAY in co._okww_error(text), True)

    print("\n[the line a minute before, close in the text: another event]")
    text = NO_BTN.replace("10:20:58,624", "10:19:50,000") + head("10:20:58,644") + TAIL
    check("not this raise", SAY in co._okww_error(text), False)

    print("\n[header without a timestamp: the 3000-character window]")
    text = NO_BTN + " ERROR TaskExecutor FarmEchoTask:farm 4c error Traceback (most recent call last):\n" + TAIL
    check("near in the text: found", co._said_before(text, text.index(" ERROR"), co._NO_CHALLENGE), True)


def _part_okww_weekly_boss_step():
    """周本要进 OK-WW 的步骤清单，否则「领满记账、周一恢复」永远触发不了。"""

    from ark_relay.core import collector

    d = tmpdir()
    def steps(text):
        f = d / "x.log"; f.write_text(text, encoding="utf-8")
        return collector.parse_okww_log(f).get("okww_steps") or []

    HEAD = "2026-09-07 11:28:57,378 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
    OCR = "2026-09-07 11:29:12,120 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：{k}/3_0.99, x60_0.79]\n"
    CLAIM = "2026-09-07 10:00:32,309 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
    CAP = "2026-09-07 11:31:04,847 INFO TaskExecutor FarmEchoTask:周本领奖：没认出领奖弹窗，整屏读到 [提示_1.00, 收取物资次数已达到上限，是否退出副本？_0.99, 退出副本_1.00]\n"
    ERR = "2026-09-07 10:00:43,366 ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card Traceback (most recent call last):\n"

    # The overlay's read-back after a claim (format fixed with the overlay; see outcome.WEEKLY_CLAIM_OK).
    BACK = "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 {k}/3→{n}/3\n"
    SAME = "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读次数没变（{k}/3），这次没领到\n"
    UNREAD = "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读没读到本周剩余次数\n"
    LAND = "2026-09-07 10:06:50,862 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm\n"
    FIGHT = "2026-09-07 10:06:52,779 INFO TaskExecutor FarmEchoTask:enter combat None\n"

    check("领满后进本：已完成、已领满", steps(HEAD + OCR.format(k=0) + CAP), ["周本（已完成，本周已领满）"])
    check("领了一次、回读确认：正常退出", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2)),
          ["周本（已完成，领了 1 次，本周还剩 2 次）"])
    check("领了一次但卡结算页（09-07 早）、回读确认", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2) + ERR),
          ["周本（领了 1 次，之后出错，原因见失败于）"])

    print("\n[「已点确认」只是点了，回读确认才算领到]")
    check("旧日志只有「已点确认」：不算领到、不写已完成", steps(HEAD + OCR.format(k=3) + CLAIM),
          ["周本（点了确认 1 次、领完没再读次数，没核实领到）"])
    check("旧日志只有「已点确认」又出错（09-07 早的原样）", steps(HEAD + OCR.format(k=3) + CLAIM + ERR),
          ["周本（点了确认 1 次、领完没再读次数，没核实领到，之后出错，原因见失败于）"])
    check("回读次数没变：没领到", steps(HEAD + OCR.format(k=2) + CLAIM + SAME.format(k=2)),
          ["周本（领完再读次数没变 1 次，没领到）"])
    check("回读没读到：不算领到", steps(HEAD + OCR.format(k=2) + CLAIM + UNREAD),
          ["周本（领完再读没读到剩余次数 1 次，没核实领到）"])
    check("一次确认、一次没变：领了 1 次另说那次", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2) + CLAIM + SAME.format(k=2)),
          ["周本（已完成，领了 1 次，本周还剩 2 次；另有领完再读次数没变 1 次，没领到）"])

    print("\n[剩余次数没读到不等于领满]")
    # A verified claim with no counter reading anywhere: unknown, never 「本周已领满」.
    no_read = HEAD + CLAIM + "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 ?/3→?/3\n"
    check("这种行不会被当成回读确认", steps(no_read), ["周本（点了确认 1 次、领完没再读次数，没核实领到）"])
    from ark_relay.features import outcome
    orig = outcome.weekly_left
    outcome.weekly_left = lambda text: None
    try:
        check("领到了但读不到剩余：说没读到，不说领满", steps(HEAD + CLAIM + BACK.format(k=3, n=2)),
              ["周本（已完成，领了 1 次，本周剩余次数没读到）"])
    finally:
        outcome.weekly_left = orig

    print("\n[没有开打的记录就不说「打了」]")
    check("打了没领（有 enter combat）", steps(HEAD + OCR.format(k=3) + LAND + FIGHT), ["周本（打了，没领到奖励）"])
    check("进了本没打（10-05 早：只有 prepared as）", steps(HEAD + OCR.format(k=3) + LAND), ["周本（进了本，没打起来，没领到奖励）"])
    check("没进本", steps(HEAD + OCR.format(k=3)), ["周本（没进本，一次没打）"])
    NOWAVE = "2026-09-01 11:01:39,518 INFO TaskExecutor FarmEchoTask:波片不足挡住开启挑战，点取消跳过本次周本\n"
    check("波片不够跳过：说奖励没领、没打", steps(HEAD + OCR.format(k=1) + NOWAVE), ["周本（奖励没领：结晶波片不足，这一趟没打）"])
    NOWAVE_END = ("2026-09-01 11:01:40,000 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本：结晶波片不够领奖"
              "（游戏提示「结晶波片不足，无法获取奖励」），点了取消，这一趟没打\n")
    check("波片不够跳过＋按失败结束：日报同一行", steps(HEAD + OCR.format(k=1) + NOWAVE + NOWAVE_END),
          ["周本（奖励没领：结晶波片不足，这一趟没打）"])
    check("领到一次后波片不够：日报说剩下的没领", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2) + NOWAVE + NOWAVE_END),
          ["周本（已完成，领了 1 次，本周还剩 2 次；剩下的奖励没领：结晶波片不足）"])
    check("没开周本就不写", steps("2026-09-07 11:34:06,670 INFO TaskExecutor DailyTask:open_daily\n"), [])
    check("剩余 0 次、没弹上限对话（09-02 的样本）：也算已领满", steps(HEAD + OCR.format(k=0)), ["周本（已完成，本周已领满）"])

    print("\n[周常乐园：上游现在记的是中文「乐园任务完成, 已达到上限」（GardenTask.run，2026-09-14 读的源码）]")
    G = "2026-09-14 10:02:11,001 INFO TaskExecutor GardenTask:Garden current: [Box(name='2000/2000')]\n"
    check("做完了（中文）", steps(G + "2026-09-14 10:02:12,001 INFO TaskExecutor GardenTask:乐园任务完成, 已达到上限\n"), ["周常乐园（本周已完成）"])
    check("做完了（旧英文）", steps("x GardenTask:weekly garden already completed\n"), ["周常乐园（本周已完成）"])
    check("跑了但没有完成那句：不算完成", steps(G), ["周常乐园（没读到做完，不算完成）"])


def _part_okww_weekly_entry_paths():  # noqa: C901
    """Weekly boss entry: one path that looks at every screen, for every screen seen so far."""
    import types

    from ark_relay.features import okww_overlay

    class Disabled(Exception):
        """ok.TaskDisabledException."""

    class Revived(Exception):
        """src.task.BaseCombatTask.CharRevivedException."""

    class BaseWWTask(metaclass=_AnyMeta):
        def click_on_book_target(self, serial_number, total_number, structure=None):
            # Upstream (v3.7.3 BaseWWTask.py:1070-1112): click 前往, then wait 10 s for
            # the travel or team screen; True means the team screen.
            self.events.append("book")
            if self.book == "team":
                return True
            raise Exception("wait_feature timeout")

        # Upstream v3.7.3 BaseWWTask.py:1115-1117, verbatim: the overlay replaces it
        # only while its source still hashes to the pin.
        def click_team_challenge(self):
            self.wait_click_feature('team_start_challenge', raise_if_not_found=True, click_after_delay=0.5, after_sleep=1)
            self.wait_click_skip_dialog_confirm()

    class FarmEchoTask(BaseWWTask):
        def teleport_to_configured_boss(self):
            # Upstream v3.7.4 FarmEchoTask.py:273-308, reduced to the steps after the book.
            is_team = self.click_on_book_target(1, 4)
            self.events.append("after-book")
            if is_team:
                if self.config.get('Teleport to Boss', 'No') == 'Weekly Challenge':
                    self.click_configured_boss_level()
                    self.click_solo_challenge()
                self.click_team_challenge()
            else:
                self.realm_entry_at_heal_point = False
                self.events.append("travel")
            self.wait_in_team_and_world(time_out=120)
            self.sleep(2)
            return is_team

        def teleport_to_configured_boss_and_prepare(self):
            # Upstream v3.7.3 FarmEchoTask.py:243-266, reduced.
            try:
                if self.teleport_to_configured_boss():
                    walk = "realm"
                else:
                    walk = self.walk_after_boss_teleport()
            except Exception as e:
                raise RuntimeError("Teleport to boss failed") from e
            self.prepared = walk

        def walk_after_boss_teleport(self):
            self.events.append("walk")
            return "realm"

        def click_configured_boss_level(self):
            # Upstream's level click; the overlay reads the claims left before it.
            if getattr(self, "level_missing", False):
                raise RuntimeError("Can not find boss level 80")   # upstream's own raise (:370)
            self.events.append("level")

        # Upstream v3.7.4 FarmEchoTask.py:374-378, verbatim.
        def click_solo_challenge(self):
            self.click(0.880, 0.911, after_sleep=2)
            self.wait_click_skip_dialog_confirm(time_out=1)

        def combat_once(self, wait_combat_time=200, raise_if_not_found=True, target=False):
            if self.revive:
                raise Revived()
            return self.combat

        def incr_drop(self, dropped):
            self.events.append("incr")

    mods = {
        "ok": types.SimpleNamespace(TaskDisabledException=Disabled,
                                    Logger=types.SimpleNamespace(get_logger=lambda n: types.SimpleNamespace(
                                        info=lambda *a, **k: None, error=lambda *a, **k: None))),
        "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
        "src.task.BaseCombatTask": types.SimpleNamespace(CharRevivedException=Revived),
        "src.task.BaseWWTask": types.SimpleNamespace(BaseWWTask=BaseWWTask),
        "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=FarmEchoTask),
    }
    for name in ("DailyTask", "ForgeryTask", "SimulationTask", "TacetTask"):
        mods[f"src.task.{name}"] = types.SimpleNamespace(**{name: _AnyMeta(name, (), {})})
    _saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    ns = {}
    # Loading the file installs everything it can, as on the machine; the nest part
    # finds no NightmareNestTask here and stops the chain before the claim, so the
    # claim is installed by hand - once, or the wrappers would wrap each other.
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    if "FarmEchoTask.incr_drop" not in ns["_applied"]:
        ns["_install_claim"]()
    check("进本这几处都换上了", all(x in ns["_applied"] for x in (
        "BaseWWTask.click_on_book_target", "FarmEchoTask.teleport_to_configured_boss",
        "FarmEchoTask.click_configured_boss_level", "FarmEchoTask.combat_once", "FarmEchoTask.incr_drop")))
    check("开启挑战那段的钉值对得上上游 3.7.3 原文（daeaf5a0f809）",
          "FarmEchoTask.click_team_challenge" in ns["_applied"])
    check("不再有「认不出就去大世界走路」那条", "_EarlyLanded" in ns, False)

    DIALOG = ["Box(name='提前到达目标位置可能影响剧情体验，是否确认前往？', x=600, y=502, width=693, height=33, confidence=99)"]
    LEVEL_PAGE = ("Box(name='定序诸理之律', x=102, y=52, width=168, height=33, confidence=100) "
                  "Box(name='136', x=1326, y=42, width=72, height=43, confidence=100) "
                  "Box(name='0/240+', x=1584, y=40, width=254, height=45, confidence=97) "
                  "Box(name='推荐等级40', x=206, y=169, width=150, height=39, confidence=100) Box(name='天演溯心', x=121")
    LEFT_2 = ["本周剩余可收取次数：2/3_1.00", "x60_0.79"]          # replay 09-07 :160
    LEFT_1 = ["本周剩余可收取次数：1/3_1.00", "x60_0.79"]          # ok-script.log 10-05 22:17:31
    LEFT_0 = ["本周剩余可收取次数：0/3_1.00", "x60_0.79"]
    LOADING = ("", False, False)
    ARENA = ("Lv.90", True, True)
    WORLD = ("终端", True, False)

    class Late:
        name = "team_close"

    def task(book="dialog", looks=(LOADING,), left=LEFT_1, start=True, after=(), late=None):
        t = object.__new__(FarmEchoTask)
        t.events, t.logs, t.shots, t.waits, t.clicks = [], [], [], [], []
        t.book, t.looks, t.i, t.left, t.start, t.after, t.late = book, list(looks), 0, left, start, list(after), late
        t.combat, t.revive = True, False
        t.config = {"Teleport to Boss": "Weekly Challenge"}
        t._in_realm = True

        def look():
            return t.looks[min(max(t.i - 1, 0), len(t.looks) - 1)]

        def ocr(box=None, **kw):
            if box == (0.25, 0.40):
                return DIALOG if t.book == "dialog" else ["Box(name='传送', x=1, y=1)"]
            if box == (0.58, 0.80):
                return t.left
            if box == (0.20, 0.35):
                return t.after
            if box == (0.0, 0.0):
                t.i += 1
                return [look()[0]]
            return []
        t.ocr = ocr
        t.box_of_screen = lambda x, y, to_x, to_y: (x, y)
        t.in_team_and_world = lambda: look()[1]
        t.in_realm = lambda: look()[2]
        t.in_world = lambda: look()[1] and not look()[2]
        t.log_info = lambda msg, notify=False: t.logs.append(msg)
        t.log_error = lambda msg, notify=False: t.logs.append(msg)
        t.find_one = lambda *a, **kw: None          # no dialog after 开启挑战
        t.click_dialog_right_button = lambda: t.events.append("confirm")
        t.click_dialog_left_button = lambda: t.events.append("cancel")
        t.wait_in_team_and_world = lambda time_out=10, raise_if_not_found=True, esc=False: t.waits.append(time_out) or True
        t.screenshot = lambda name: t.shots.append(name)
        t.click = lambda *a, **kw: t.clicks.append(a)
        t.ensure_main = lambda time_out=30: t.events.append("main")

        def wait_feature(feature, **kw):
            if feature == "team_start_challenge":
                return t.start
            return t.late
        t.wait_feature = wait_feature

        def wait_click_feature(feature, **kw):
            if not t.start:
                raise Exception("no team_start_challenge")
            t.events.append("start")
        t.wait_click_feature = wait_click_feature
        t.wait_click_skip_dialog_confirm = lambda **kw: t.events.append("skip-confirm")
        t.wait_until = lambda cond, **kw: cond()
        t.walk_to_treasure = lambda: t.events.append("treasure")
        t.pick_f = lambda handle_claim=True: t.events.append("f")
        t.sleep = lambda s: None
        return t

    def entered(t):
        return [e for e in t.events if e in ("confirm", "level", "start", "walk", "travel")]

    def stopped(t):
        try:
            t.teleport_to_configured_boss_and_prepare()
        except ns["_ArkStop"]:
            # The overlay's own stop: FarmEchoTask.run ends the run as FAILED when a
            # reason was kept, as SKIPPED when none was (_skip_short).
            why = getattr(t, "_ark_failed", None)
            return f"fail: {why}" if why else "skip"
        except Disabled:
            return "skip"
        except RuntimeError as exc:
            return f"stop: {exc}"
        return "in"

    print("\n[(a) 有框→确认后是选等级页（10-05 22:17 天演溯心）：交回上游原路，选等级→单人挑战→开启挑战]")
    t = task(looks=[LOADING, (LEVEL_PAGE, False, False)])
    check("进了本", stopped(t), "in")
    check("点确认→选等级→开启挑战", entered(t), ["confirm", "level", "start"])
    check("单人挑战点的是上游那个位置", t.clicks, [(0.880, 0.911)])
    check("走的是上游开书之后的原路", "after-book" in t.events)
    check("当成已进本", t.prepared, "realm")
    check("加载慢一拍也等到了（看了两眼）", t.i, 2)
    check("截了选等级页", "early_open_team" in t.shots)
    check("说了是选等级页、框里读到什么", any("选等级页" in m for m in t.logs)
          and any("框里读到：" in m and "剧情体验" in m for m in t.logs))
    check("读了本周剩余次数", t._ark_weekly_left, 1)

    print("\n[(b) 有框→确认后直接在 Boss 场地里（09-09 天傀劫煞）：当已进本，不点选等级]")
    t = task(looks=[LOADING, LOADING, ARENA])
    check("进了本", stopped(t), "in")
    check("只点了确认", entered(t), ["confirm"])
    check("当成已进本", t.prepared, "realm")
    check("截了落地图", "early_open_landed" in t.shots)
    check("说了直接进场", any("直接进场" in m for m in t.logs))

    print("\n[the same arena drop reached from TacetTask / ForgeryTask (click_on_book_target is bound on BaseWWTask): no _EarlyOpen]")
    t = task(looks=[LOADING, LOADING, ARENA])
    t.config = {"Which Tacet Suppression to Farm": 1}
    try:
        got = t.click_on_book_target(1, 21, [4, 5, 5, 7])
    except ns["_EarlyOpen"]:
        got = "raised _EarlyOpen"
    check("returns upstream's team-screen answer, True", got, True)
    check("the boss teleport flag is not left set", getattr(t, "_ark_boss_teleport", False), False)

    print("\n[(c) 没有框（09-07 正常进本）：上游原路，选等级→单人挑战→开启挑战]")
    t = task(book="team", left=LEFT_2)
    check("进了本", stopped(t), "in")
    check("选等级→开启挑战，没点确认", entered(t), ["level", "start"])
    check("单人挑战点的是上游那个位置", t.clicks, [(0.880, 0.911)])
    check("读了本周剩余次数 2/3", t._ark_weekly_left, 2)
    check("没截认不出的图", "weekly_entry_unknown" in t.shots, False)

    print("\n[(c') 没有框、传送界面过了上游的 10 秒才来：多等 15 秒等到队伍界面，照常进本]")
    t = task(book="slow", late=Late())
    check("进了本", stopped(t), "in")
    check("选等级→开启挑战", entered(t), ["level", "start"])
    check("说了多等到了", any("多等 15 秒等到了" in m for m in t.logs))

    class Map:
        name = "fast_travel_custom"

    print("\n[有框→确认后是传送地图（09-09 868d09f5 处理过、cfdd4f04 丢了）：讨伐强敌按上游传送原路走]")
    t = task(late=Map())
    t.config = {"Teleport to Boss": "Boss Challenge"}
    check("进了本", stopped(t), "in")
    check("走的是上游传送那条（不是队伍界面）", entered(t), ["confirm", "travel", "walk"])
    check("截了地图", "early_open_map" in t.shots)

    print("\n[有框→周本却出了传送地图：周本没有地图这一屏，截图停下，不走路]")
    t = task(late=Map())
    check("停下了", stopped(t).startswith("stop:"))
    check("没走路", "walk" in t.events, False)
    check("截了认不出的图", "weekly_entry_unknown" in t.shots)

    print("\n[有框→确认后是队伍界面：按上游原路进本]")
    t = task(late=Late())
    check("进了本", stopped(t), "in")
    check("选等级→开启挑战", entered(t), ["confirm", "level", "start"])

    print("\n[有框→确认后落在大世界：认不出，截图停下，不走路]")
    t = task(looks=[LOADING, WORLD, WORLD, WORLD])
    got = stopped(t)
    check("停下了（上游的 Teleport to boss failed）", got.startswith("stop: Teleport to boss failed"))
    check("没去大世界走路", "walk" in t.events, False)
    check("没点选等级", "level" in t.events, False)
    check("截了认不出的图", "weekly_entry_unknown" in t.shots)
    check("日志写了认不出和整屏的字", any("认不出" in m and "终端" in m and "in_world=True" in m for m in t.logs))

    print("\n[有框→确认后两分钟都没认出的画面：截图停下]")
    t = task(looks=[("加载中", False, False)])
    check("停下了", stopped(t).startswith("stop:"))
    check("看满了两分钟（60 眼）", t.i, 60)
    check("截了认不出的图", "weekly_entry_unknown" in t.shots)
    check("没走路", "walk" in t.events, False)

    print("\n[没有框、多等 15 秒也没来：截图停下，不走路]")
    t = task(book="slow", late=None, looks=[("某个没见过的界面", False, False)])
    check("停下了", stopped(t).startswith("stop:"))
    check("截了认不出的图", "weekly_entry_unknown" in t.shots)
    check("日志写了整屏的字", any("认不出" in m and "某个没见过的界面" in m for m in t.logs))
    check("没走路", "walk" in t.events, False)

    print("\n[选等级页上读到 0/3：不进本，跳过（不算失败）]")
    t = task(looks=[LOADING, (LEVEL_PAGE, False, False)], left=LEFT_0)
    check("跳过", stopped(t), "skip")
    check("没点开启挑战", "start" in t.events, False)
    check("退回主界面", "main" in t.events)
    check("说了已领满", any("已领满（0/3）" in m for m in t.logs))

    class _At:
        """An OCR box with a place on the 1920x1080 screen."""
        def __init__(self, name, x, y):
            self.name, self.x, self.y, self.width, self.height = name, x, y, 40, 30

        def __str__(self):
            return f"Box(name='{self.name}', x={self.x}, y={self.y}, width=40, height=30, confidence=100)"

    # The reminder after 单人挑战 (v3.7.4 FarmEchoTask.py:375-376: 「无法获取奖励, 是否继续进入」;
    # the game's wording, docs/OKWW-WEEKLY-BOSS.md), over the top bar (backup, waveplates/240).
    REMINDER = "结晶波片不足，无法获取奖励，请确认是否继续进入？"

    def solo_dialog(t, wave, spare, text=REMINDER):
        """After the click on 单人挑战 a dialog is up, until 取消 or 确认 is clicked."""
        t.height_of_screen = lambda r: r * 1080
        t.dialog_up = False
        bar = ([_At(str(spare), 1208, 50)] if spare is not None else []) + \
              ([_At(f"{wave}/240", 1480, 50)] if wave is not None else [])
        screen = bar + [_At(text, 700, 500), _At("取消", 640, 700), _At("确认", 1280, 700)]
        base_ocr, base_click = t.ocr, t.click

        def ocr(box=None, **kw):
            if box == (0.0, 0.0) and t.dialog_up:
                return list(screen)
            return base_ocr(box=box, **kw)

        def click(*a, **kw):
            base_click(*a, **kw)
            if a[:2] == (0.880, 0.911):
                t.dialog_up = True

        def answer(name):
            t.events.append(name)
            t.dialog_up = False
        t.ocr, t.click = ocr, click
        t.find_one = lambda *a, **kw: "confirm-btn" if t.dialog_up else None
        t.click_dialog_left_button = lambda: answer("cancel")
        t.click_dialog_right_button = lambda: answer("confirm")
        return t

    print("\n[v3.7.4: after 单人挑战 the 「无法获取奖励」 reminder, waveplates 17 + backup 24 < 60 -> 取消, skipped as short]")
    t = solo_dialog(task(book="team"), 17, 24)
    check("skipped", stopped(t), "skip")
    check("no reason kept (a shortage, not a failure)", getattr(t, "_ark_failed", None), None)
    check("取消 clicked, never 确认, 开启挑战 never clicked", [e for e in t.events if e in ("cancel", "confirm", "start")], ["cancel"])
    check("upstream's confirm-and-tick never ran", "skip-confirm" in t.events, False)
    check("the shortage line the relay reads", any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))
    check("the two values in the log", any("顶栏读到波片 17/240，备用 24" in m for m in t.logs))
    check("picture", "nowave_dialog" in t.shots)
    check("no failed mark", any(ns["FAILED_MARK"] in m for m in t.logs), False)

    print("\n[the reminder with waveplates 41 + backup 24 >= 60 contradicts the game (it shows only when short) -> 取消, picture, stop]")
    t = solo_dialog(task(book="team"), 41, 24)
    got = stopped(t)
    check("stopped as failed, saying the read and the game disagree", got.startswith("fail:") and "读数和游戏对不上" in got)
    check("取消 clicked, never 确认, 开启挑战 never clicked", [e for e in t.events if e in ("cancel", "confirm", "start")], ["cancel"])
    check("no tick (upstream's wait_click_skip_dialog_confirm not called)", "skip-confirm" in t.events, False)
    check("picture of the dialog", "solo_dialog_contradicts" in t.shots)
    check("not the shortage line (not a skip)", any(m.startswith("结晶波片不足") for m in t.logs), False)

    print("\n[a dialog after 单人挑战 that is not the reminder -> picture, phone, stop; nothing clicked]")
    t = solo_dialog(task(book="team"), 41, 24, text="某个没见过的对话框")
    got = stopped(t)
    check("stopped as failed", got.startswith("fail:") and "认不出的对话框" in got)
    check("nothing answered, 开启挑战 not clicked", [e for e in t.events if e in ("cancel", "confirm", "start")], [])
    check("picture", "solo_dialog_unknown" in t.shots)

    print("\n[the reminder but the top bar is not read -> no blind 确认: picture, stop]")
    t = solo_dialog(task(book="team"), None, None)
    got = stopped(t)
    check("stopped as failed", got.startswith("fail:") and "顶栏的波片没读全" in got)
    check("nothing answered", [e for e in t.events if e in ("cancel", "confirm", "start")], [])
    check("picture", "solo_dialog_bar_unread" in t.shots)

    print("\n[no dialog after 单人挑战 -> straight on to 开启挑战, nothing answered]")
    t = task(book="team", left=LEFT_2)
    check("went in", stopped(t), "in")
    check("level, 开启挑战; no 确认/取消", entered(t), ["level", "start"])

    print("\n[echo farm on the weekly config (no-claim flag): upstream's click_solo_challenge runs, tick and all]")
    import tempfile
    flag = Path(tempfile.mkdtemp(prefix="ark-entry-")) / "ark-okww-farm.no-claim"
    flag.write_text("")
    real_flag, ns["NO_CLAIM"] = ns["NO_CLAIM"], str(flag)
    try:
        t = solo_dialog(task(book="team"), 17, 24)
        t.wait_click_skip_dialog_confirm = lambda **kw: t.events.append(f"skip-confirm {kw}")
        t.click_solo_challenge()
    finally:
        flag.unlink()
        flag.parent.rmdir()
        ns["NO_CLAIM"] = real_flag
    check("upstream's own: the click, then confirm-and-tick within 1 s",
          (t.clicks, [e for e in t.events if e.startswith("skip-confirm")]), ([(0.880, 0.911)], ["skip-confirm {'time_out': 1}"]))

    print("\n[echo farm (Boss Challenge): a 4C boss's level page has no weekly counter -> upstream's level click, no stop]")
    t = task(left=["Box(name='推荐等级50', x=206, y=169)"])
    t.config = {"Teleport to Boss": "Boss Challenge"}
    got = "on"
    try:
        t.click_configured_boss_level()
    except Exception as exc:  # noqa: BLE001
        got = f"stop: {exc!r} {getattr(t, '_ark_failed', None)}"
    check("not stopped", got, "on")
    check("upstream's level click ran", t.events, ["level"])
    check("no weekly screenshot, no weekly read", (t.shots, any("周本本周剩余次数原文" in m for m in t.logs)), ([], False))

    print("\n[echo farm (Boss Challenge) through the book onto the level page -> Boss Level picked, 单人挑战, then 开启挑战]")
    LEVEL_PAGE = ["Box(name='推荐等级80', x=206, y=169)", "Box(name='推荐等级90', x=206, y=609)", "Box(name='单人挑战', x=1650, y=980)"]

    def boss_challenge(screen, start_btn=False, missing=False):
        t = task(book="team")
        t.config = {"Teleport to Boss": "Boss Challenge", "Boss Level": "80"}
        base = t.ocr

        def ocr(box=None, **kw):
            if box == (0.0, 0.0):
                return list(screen)
            if box == (0.030, 0.113):
                return [b for b in screen if "推荐等级" in b]
            return base(box=box, **kw)
        t.ocr = ocr
        t.find_one = lambda feature, **kw: "start-btn" if start_btn and feature == "team_start_challenge" else None
        t.level_missing = missing
        t.wait_click_skip_dialog_confirm = lambda **kw: t.events.append("skip-confirm")
        return t

    t = boss_challenge(LEVEL_PAGE)
    check("went in", stopped(t), "in")
    check("level, then upstream's 单人挑战 (click and confirm-and-tick), then 开启挑战",
          ([e for e in t.events if e in ("level", "skip-confirm", "start")], (0.880, 0.911) in t.clicks),
          (["level", "skip-confirm", "start"], True))
    check("logged the level clicked and what the page listed",
          any(m.startswith("刷声骸选等级：选等级页点了 Lv.80。读到 ") and "推荐等级90" in m for m in t.logs))

    print("\n[echo farm (Boss Challenge) through the book onto a team screen with no level list -> logged once, on as upstream]")
    t = boss_challenge(["Box(name='开启挑战', x=1750, y=980)"], start_btn=True)
    check("went in", stopped(t), "in")
    check("no level click, no 单人挑战; 开启挑战", ([e for e in t.events if e in ("level", "skip-confirm", "start")],
                                              (0.880, 0.911) in t.clicks), (["start"], False))
    check("one line, with the screen", [m for m in t.logs if m.startswith("刷声骸选等级：")],
          ["刷声骸选等级：前往后是队伍界面（没有选等级页），不选等级，按游戏记住的等级进（设置 Lv.80）。"
           "整屏读到 Box(name='开启挑战', x=1750, y=980)"])

    print("\n[the level page without the configured level -> no raise: logged, 单人挑战, 开启挑战]")
    t = boss_challenge(LEVEL_PAGE, missing=True)
    check("went in", stopped(t), "in")
    check("单人挑战 and 开启挑战 still", [e for e in t.events if e in ("level", "skip-confirm", "start")], ["skip-confirm", "start"])
    check("said the level was not found", any("选等级页上没找到 Lv.80" in m for m in t.logs))

    print("\n[nothing known after 前往 -> logged once, on as upstream (no raise from here)]")
    t = boss_challenge(["Box(name='加载中', x=1, y=1)"])
    check("went in", stopped(t), "in")
    check("one 「认不出的画面」 line", sum(m.startswith("刷声骸选等级：前往后是认不出的画面") for m in t.logs), 1)

    print("\n[the weekly boss keeps upstream's own level and 单人挑战 calls: no second level pick]")
    t = solo_dialog(task(book="team", left=LEFT_2), 0, 0)
    t.find_one = lambda *a, **kw: None
    stopped(t)
    check("no 刷声骸选等级 line on the weekly path", any(m.startswith("刷声骸选等级") for m in t.logs), False)

    print("\n[周本的复活交给上游 do_run 重新传送]")
    # The weekly boss is not the echo farm, so the revive is upstream's tower revive and
    # the exception goes up to do_run (v3.7.3 FarmEchoTask.py:204-216); the in-place
    # revive that combat_once swallows is in test_okww_revive_and_retry.py.
    t = task()
    t.revive = True
    try:
        t.combat_once()
        went_up = False
    except Revived:
        went_up = True
    check("周本的复活往上抛给上游", went_up)

    # The coverage driver runs every test in one process: leave sys.modules as found.
    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def _part_okww_weekly_spend():
    """Verified weekly-boss claims count in 「消耗 波片」 (audit 2026-10-13 item 12)."""

    from ark_relay.features import outcome as co

    def spent(*lines):
        p = tmpdir() / "OK-WW.log"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return co.parse_okww_log(p).get("okww_stamina_spent")

    def claim(before):
        return (f"2026-10-12 11:5{before},000 INFO TaskExecutor FarmEchoTask:"
                f"周本领奖：回读确认领到，本周剩余 {before}/3→{before - 1}/3")

    def reading(n, task="TacetTask"):
        return f"2026-10-12 11:40:00,000 INFO TaskExecutor {task}:info_set current_stamina {n}"

    print("[claims with no reading around them: 60 each]")
    check("three verified claims", spent(claim(3), claim(2), claim(1)), 180)

    print("\n[a claim between two readings whose drop shows it: not counted twice]")
    check("240 -> claim -> 180", spent(reading(240, "FarmEchoTask"), claim(3), reading(180, "FarmEchoTask")), 60)
    check("240 -> claim -> 240 (no drop shown): still 60", spent(reading(240), claim(3), reading(240)), 60)

    print("\n[stamina farm and claims in one run: both]")
    check("tacet 240 -> 120, then one claim", spent(reading(240), reading(120), claim(1)), 180)

    print("\n[a claim that did not read back as taken costs nothing here]")
    same = "2026-10-12 11:50,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读次数没变（2/3），这次没领到"
    check("unchanged count", spent(same), None)

    print("\n[a drop a little short of 60 is the claim plus regeneration (item 18)]")
    # review-C/wk.py: 100 -> claim -> 42 twelve minutes later reported 118.
    t = ("2026-10-14 09:00:00,000 INFO TaskExecutor TacetTask:info_set current_stamina 100\n"
         "2026-10-14 09:10:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3\n"
         "2026-10-14 09:12:00,000 INFO TaskExecutor TacetTask:info_set current_stamina 42\n")
    check("100 -> claim -> 42: 58, not 118", spent(t), 58)

    def full(*lines):
        p = tmpdir() / "OK-WW.log"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return co.parse_okww_log(p)

    TOPUP = "2026-10-12 15:29:47,649 INFO TaskExecutor FarmEchoTask:周本领奖：波片不够，动用备用体力"
    print("\n[a claim topped up with backup: the backup is counted (item 18)]")
    bar = "2026-10-12 15:29:44,000 INFO TaskExecutor FarmEchoTask:周本领奖：顶栏读到波片 20/240，备用 100"
    got = full(bar, TOPUP, claim(3))
    check("top bar read: 20 waveplates, 40 backup", (got.get("okww_stamina_spent"), got.get("okww_backup_spent")), (20, 40))
    print("\n[10-12 15:29 / 15:31 shape: topped up, top bar not logged - said, not guessed]")
    got = full(claim(3), TOPUP, claim(2), TOPUP, claim(1))
    check("only the plain claim in 波片", got.get("okww_stamina_spent"), 60)
    check("the two topped-up claims counted as unread", got.get("okww_weekly_topup_unread"), 2)
    from datetime import datetime

    from ark_relay.core import ledger as ledger_rows
    cost = ledger_rows._block_okww(got, datetime(2026, 10, 12, 15, 33))[1]
    check("the daily report says so", any("另有周本领奖 2 次用备用体力补足" in c for c in cost), True)


def _part_okww_overlay_main():
    """Ark's OK-WW changes live in OK-WW's own extension point, not in its source."""
    import json

    from ark_relay.features import okww_overlay

    print("[装到 OK-WW 自己的扩展目录里，不碰它的源文件]")
    root = tmpdir()
    dest = okww_overlay.target(root)
    check("路径在 ok_tasks 下", dest.parent.name, "ok_tasks")
    check("装之前没有", dest.is_file(), False)
    line = okww_overlay.install(root)
    check("装上了", dest.is_file())
    check("说了装到哪", "ok_tasks" in line)
    check("内容一字不差", dest.read_text(encoding="utf-8"), okww_overlay.source_text())
    check("再装一次什么都不做", okww_overlay.install(root), "")
    try:
        okww_overlay.install(None)
        check("目录是 None 时直说", False)
    except okww_overlay.OverlayTrouble as exc:     # a failure by construction (the _part_okww_overlay_faults part)
        check("目录是 None 时直说", "找不到" in str(exc))

    print("[没有目录也要自己建，不能因为缺个文件夹就装不上]")
    root2 = tmpdir()
    okww_overlay.install(root2)
    check("建好了目录并写进去", okww_overlay.target(root2).is_file())

    print("[ok-script 只执行「文件里有类」的 .py，所以那个类必须在]")
    src = okww_overlay.source_text()
    check("文件里有顶层类", "\nclass " in src)
    check("重绑之前先检查方法还在不在", "上游没有这个方法了" in src)
    check("抄整段的要比对上游正文", "expect_sha" in src)
    check("传送界面等不到时会多等一次", "多等 15 秒" in src)
    check("多等那次不许自己抛，找不到才抛", "raise_if_not_found=False" in src)
    whole = [l for l in src.splitlines() if "@override(" in l]
    pinned = [l for l in whole if "expect_sha=" in l]
    check("整段替换的都钉住了上游哈希", len(pinned) >= 1)
    check("被替换的是那两个小方法", any("click_team_challenge" in l or "find_nest" in l
                                        for l in pinned))

    print("[没贴上必须报出来，不许闷着]")
    real = okww_overlay.REPORT
    try:
        okww_overlay.REPORT = tmpdir() / "report.json"
        check("没有报告时不说话", okww_overlay.report_line(), "")
        okww_overlay.REPORT.write_text(json.dumps({"applied": ["A.b"], "skipped": []}),
                                       encoding="utf-8")
        check("全贴上了也不说话", okww_overlay.report_line(), "")
        okww_overlay.REPORT.write_text(json.dumps(
            {"applied": [], "skipped": [{"what": "FarmEchoTask.revive_action",
                                         "why": "上游没有这个方法了（改名或删了）"}]}),
            encoding="utf-8")
        line = okww_overlay.report_line()
        check("点名是哪一条没贴上", "revive_action" in line)
        check("说了为什么", "改名" in line)
        okww_overlay.REPORT.write_text(json.dumps({"error": "Traceback ... ImportError"}),
                                       encoding="utf-8")
        check("整个文件炸了也要说", "一条都没生效" in okww_overlay.report_line())
        okww_overlay.REPORT.write_text(json.dumps(
            {"applied": ["FarmEchoTask.revive_action", "FarmEchoTask.handle_claim_button"],
             "skipped": [], "error": "Traceback ... KeyError"}), encoding="utf-8")
        line = okww_overlay.report_line()
        check("part-way: not 「一条都没生效」", "一条都没生效" in line, False)
        check("part-way: names what applied", "已生效 2 条" in line and "handle_claim_button" in line, True)
        check("part-way: names what did not", "没生效" in line and "NightmareNestTask.find_nest" in line, True)
        check("part-way: an applied one is not listed as not applied",
              "revive_action" not in line.split("没生效")[1], True)
        check("part-way: still the error and its trouble words", "KeyError" in line and "自己报错了" in line, True)
    finally:
        okww_overlay.REPORT = real

    print("[闸门本身：拿坏样本喂它，必须拦住]")
    # The gate is the whole reason this is safer than editing upstream's files. A gate
    # that does not fire is worse than none, so it is fed known-bad input here.
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    ns["_applied"].clear()
    ns["_skipped"].clear()

    class Upstream:
        def still_here(self):
            return "上游的"

    @ns["override"](Upstream, "still_here")
    def _mine(self):
        return "我们的"

    check("方法在就换掉", Upstream().still_here(), "我们的")
    check("记到已贴上里", ns["_applied"], ["Upstream.still_here"])

    ns["_applied"].clear()
    ns["_skipped"].clear()

    @ns["override"](Upstream, "上游改名之后就没有的方法")
    def _orphan(self):
        return "不该生效"

    check("上游没这个方法就不贴", ns["_applied"], [])
    check("而且要记下来", len(ns["_skipped"]), 1)
    check("说清了原因", "上游没有这个方法了" in ns["_skipped"][0]["why"])

    ns["_applied"].clear()
    ns["_skipped"].clear()

    @ns["override"](Upstream, "still_here", expect_sha="0123456789ab")
    def _stale(self):
        return "照着旧正文抄的"

    check("上游正文变了就不贴", ns["_applied"], [])
    check("并且说明是正文对不上", "正文变了" in ns["_skipped"][0]["why"])
    check("原来那份没被换掉", Upstream().still_here(), "我们的")

    real_sha = ns["_src_sha"](Upstream.still_here)
    ns["_applied"].clear()
    ns["_skipped"].clear()

    @ns["override"](Upstream, "still_here", expect_sha=real_sha)
    def _fresh(self):
        return "对得上就贴"

    check("正文对得上就照贴", Upstream().still_here(), "对得上就贴")
    check("没有被跳过的", ns["_skipped"], [])

    print("\n[the gate compares call shapes: a copy that does not take upstream's parameters is not bound]")

    class Up2:
        def run(self, retries=3):
            return f"upstream {retries}"

        def pick(self, box, *, near=None):
            return "upstream pick"

        def free(self, *a, **kw):  # how the test fakes look: no constraint from upstream
            return "upstream free"

    def gate(name, fn):
        ns["_applied"].clear()
        ns["_skipped"].clear()
        ns["override"](Up2, name)(fn)
        return list(ns["_applied"]), [x["why"] for x in ns["_skipped"]]

    applied, why = gate("run", lambda self: "ours")
    check("ours run(self) vs upstream run(self, retries=3): not bound", applied, [])
    check("listed as skipped, naming the parameter", len(why) == 1 and "参数变了" in why[0] and "retries" in why[0], True)
    check("upstream's own run left in place", Up2().run(2), "upstream 2")
    applied, _ = gate("run", lambda self, *a, **kw: "wrapper")
    check("a (self, *a, **kw) wrapper is bound", applied, ["Up2.run"])
    applied, _ = gate("run", lambda self, retries=3: "same")
    check("the same shape is bound", applied, ["Up2.run"])
    applied, why = gate("pick", lambda self, b, *, near=None: "renamed")
    check("a renamed parameter (box -> b) is not bound: callers may pass box=", applied, [])
    applied, why = gate("pick", lambda self, box: "no near")
    check("a dropped keyword-only parameter is not bound", applied, [])
    applied, why = gate("pick", lambda self, box, extra, *, near=None: "needs more")
    check("ours requiring a parameter upstream lacks is not bound", applied, [])
    applied, _ = gate("run", lambda self, retries: "required")
    check("ours requiring what upstream leaves optional is not bound", applied, [])
    applied, _ = gate("free", lambda self: "plain")
    check("upstream *a/**kw constrains nothing (the fakes' shape)", applied, ["Up2.free"])

    print("\n[体力读数：数/数 没读到是「没读到」，不是 0]")
    parse = ns["_parse_stamina"]
    check("09-21 截图原样", parse(["55", "240/240", "+"]), (240, 55))
    check("240/240 拆成两块也拼得回", parse(["55", "240", "/240"]), (240, 55))
    check("拆成三块也拼得回", parse(["55", "240", "/", "240"]), (240, 55))
    check("备用只取数/数左边那块，右边的数不覆盖", parse(["55", "240/240", "120"]), (240, 55))
    check("左边不是纯数字就没有备用", parse(["+", "120/240"]), (120, 0))
    check("一块数/数都拼不出来 = 没读到（上游这里当 0）", parse(["240", "55"]), None)
    check("什么都没读到", parse([]), None)
    check("真读到 0/240 就是 0", parse(["0/240"]), (0, 0))

    class _Box:
        def __init__(self, name, x=0, y=0, width=10, height=10):
            self.name, self.x, self.y, self.width, self.height = name, x, y, width, height

        def __str__(self):
            return f"Box(name='{self.name}')"

    class FakeTask:
        """Plays back a script of screens; records what the override does."""

        def __init__(self, frames, start_after=None, strip=None):
            self.frames, self.start_after, self.strip = frames, start_after, strip or []
            self.clicks, self.logs, self.shots, self.slept = [], [], [], 0

        def wait_feature(self, name, **kw):
            return self.start_after is not None and len(self.clicks) >= self.start_after

        def box_of_screen(self, *xy):
            return xy

        def ocr(self, box=None):
            return self.frames(box)

        def wait_ocr(self, *box, **kw):
            return self.strip.pop(0) if self.strip else []

        def click_box(self, b, after_sleep=0):
            self.clicks.append((b.x + b.width // 2, b.y + b.height // 2))

        def screenshot(self, name):
            self.shots.append(name)

        def log_info(self, msg):
            self.logs.append(msg)

        def sleep(self, s):
            self.slept += s

    solo_btn = _Box("单人挑战", 1474, 965, 124, 36)
    still_solo = lambda box: [solo_btn]  # noqa: E731
    confirm = ns["_confirm_solo"]
    t = FakeTask(still_solo, start_after=0)
    check("开启挑战已经在：一下都不补", (confirm(t), t.clicks), (0, []))
    t = FakeTask(still_solo, start_after=1)
    check("09-21 那种：仍是单人挑战就点它读到的位置", (confirm(t), t.clicks), (1, [(1536, 983)]))
    check("补点前截图", t.shots, ["solo_retry_1"])
    check("补点写日志", any("补点第 1 次 (1536,983)" in m for m in t.logs), True)
    t = FakeTask(still_solo)
    check("最多补 3 次", (confirm(t), len(t.clicks)), (3, 3))
    check("3 次都没进要说", any("3 次都没进开启挑战" in m for m in t.logs), True)
    t = FakeTask(lambda box: [_Box("结晶波片不足，无法获取奖励")])
    check("波片不足弹窗不补点，交给原来那段", (confirm(t), t.clicks), (0, []))
    t = FakeTask(lambda box: [_Box("别的画面")] if box == (0.0, 0.0, 1.0, 1.0) else [])
    check("屏上没有单人挑战不乱点", (confirm(t), t.clicks), (0, []))

    read = ns["_read_stamina"]
    t = FakeTask(None, strip=[[_Box("55", 1351), _Box("/240", 1600), _Box("240", 1551)]])
    check("按横坐标排好再拼", read(t, False), (240, 55))
    check("读字原文进日志", any("['55', '240', '/240']" in m for m in t.logs), True)
    t = FakeTask(None, strip=[[_Box("240")], [_Box("55"), _Box("240/240", 5)]])
    check("领奖框没读到隔 1 秒再读", (read(t, True), t.slept), ((240, 55), 1))
    t = FakeTask(None, strip=[[_Box("240")]])
    check("F2 书页只读一次，没读到交回上游（-1 分支）", (read(t, False), t.slept), (None, 0))
    t = FakeTask(None, strip=[])
    check("领奖框读 5 次都没有就算没读到", (read(t, True), t.slept, t.shots), (None, 4, ["stamina_error"]))

    print("\n[母本指路文件：改动文件靠它读「只刷落渊南丘」]")
    automas = tmpdir()
    mdir = automas / "data" / "c5e9-okww" / "Default" / "ConfigFile"
    mdir.mkdir(parents=True)
    (mdir / "DailyTask.json").write_text("{}", encoding="utf-8")
    pointer = tmpdir() / "ark-okww-master.txt"
    okww_overlay.MASTER_POINTER = pointer
    try:
        okww_overlay.write_master_pointer(tmpdir())
        check("母本找不到就说清楚", False)
    except okww_overlay.OverlayTrouble as exc:     # a failure by construction (the _part_okww_overlay_faults part)
        check("母本找不到就说清楚", "找不到" in str(exc))
    check("写好了不吭声", okww_overlay.write_master_pointer(automas), "")
    check("指向母本目录", pointer.read_text(encoding="utf-8"), str(mdir))
    check("已是这个值就不重写", okww_overlay.write_master_pointer(automas), "")
    check("改动文件里读的是同一个路径", 'r"C:\\ProgramData\\ark-okww-master.txt"' in okww_overlay.source_text())

    print("\n[最新一趟 OK-WW 日志：按修改时间取最新，一周内]")
    from ark_relay.features import outcome
    hist = tmpdir()
    check("没有历史目录", outcome.latest_okww_run_log(hist / "nope"), None)
    check("目录空着", outcome.latest_okww_run_log(hist), None)
    d1 = hist / "2026-09-12" / "wuwa"; d1.mkdir(parents=True)
    d2 = hist / "2026-09-13" / "wuwa"; d2.mkdir(parents=True)
    (d1 / "OK-WW-05-20-09.log").write_text("old\n", encoding="utf-8")
    (d2 / "OK-WW-05-19-22.log").write_text("new NightmareNestTask\n", encoding="utf-8")
    import os as _os
    import time as _time
    _os.utime(d1 / "OK-WW-05-20-09.log", (_time.time() - 86400, _time.time() - 86400))
    got = outcome.latest_okww_run_log(hist)
    check("取到最新那趟", got[0].name if got else None, "OK-WW-05-19-22.log")
    check("连正文一起给", got[1] if got else None, "new NightmareNestTask\n")

    print("\n[the launch argument is OK-WW's own since v3.7.4: no hook on start_controller.execute]")
    src_now = okww_overlay.source_text()
    import re as _re
    hooked = _re.search(r"""start_controller\w*\s*\.\s*execute\b|override\([^)]*["']execute["']""",
                        src_now.split("# The launch-argument hook")[0])
    check("no execute override", bool(hooked), False)
    check("that check still fires on a hook", bool(_re.search(
        r"""start_controller\w*\s*\.\s*execute\b|override\([^)]*["']execute["']""",
        "import ok.core.start_controller\nok.core.start_controller.execute = mine\n")), True)
    check("no _install_launch", "_install_launch" in src_now, False)


def _part_okww_overlay_faults():
    """An overlay that is not in place reaches the group, whatever its words."""
    import os
    import types

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
                  "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi",
                  "pythoncom", "win32com", "win32com.client")

    import boot_stages
    from ark_relay.core import texts
    from ark_relay.core.notify import route_of
    from ark_relay.features import okww_overlay as ov

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []

    REAL = {k: getattr(ov, k) for k in ("atomic_write_text", "master_config_dir", "MASTER_POINTER", "REPORT")}
    MASTER = TMP / "master"
    MASTER.mkdir()

    def boot(okww_dir, *, write=None, master="ok"):
        """Run the boot stage once with a fresh pointer and no report; ([(title, alert)], [body])."""
        ov.MASTER_POINTER = tmpdir() / "pointer.txt"
        ov.REPORT = tmpdir() / "report.json"           # absent: report_line says nothing
        ov.master_config_dir = lambda automas_dir, marker: MASTER if master == "ok" else None
        ov.atomic_write_text = write or REAL["atomic_write_text"]
        cfg = types.SimpleNamespace(okww_dir=okww_dir, automas_dir=None, state_dir=tmpdir())
        notes = Notes()
        try:
            boot_stages._stage_patch_okww(cfg, notes, boot_stages.log)
        finally:
            for k, v in REAL.items():
                setattr(ov, k, v)
        return [(t, a) for t, _, a in notes.sent], [b for _, b, _ in notes.sent]

    def is_alarm(label, sent):
        check(f"{label}: one push", len(sent), 1)
        title, alert = sent[0] if sent else ("", False)
        check(f"{label}: ⚠️ title", title.startswith("⚠️"), True)
        check(f"{label}: routed to the group", route_of(title, alert=alert), "group")

    def raising(name):
        """atomic_write_text that raises OSError for the file called `name`."""
        def w(path, text, newline=None):
            if Path(path).name == name:
                raise OSError(13, "Access is denied")
            return REAL["atomic_write_text"](path, text, newline)
        return w

    def garbling(name):
        """atomic_write_text that writes something else into the file called `name`."""
        def w(path, text, newline=None):
            return REAL["atomic_write_text"](path, text + "x" if Path(path).name == name else text, newline)
        return w

    print("[healthy: installed once -> 🩹, log only]")
    sent, bodies = boot(tmpdir())
    check("one push", len(sent), 1)
    check("🩹 title", sent[0][0].startswith("🩹") if sent else False, True)
    check("log only", route_of(sent[0][0], alert=sent[0][1]) if sent else "", "log")
    check("says where it went", "ok_tasks" in (bodies[0] if bodies else ""), True)

    print("\n[every failure path: ⚠️, group]")
    sent, _ = boot(None)
    is_alarm("no OK-WW directory", sent)
    sent, _ = boot(tmpdir(), write=garbling(ov.FILE_NAME))
    is_alarm("overrides read back different", sent)
    sent, _ = boot(tmpdir(), write=raising(ov.FILE_NAME))
    is_alarm("overrides cannot be written", sent)
    sent, _ = boot(tmpdir(), master=None)
    is_alarm("no master directory", sent)
    sent, _ = boot(tmpdir(), write=raising("pointer.txt"))
    is_alarm("pointer cannot be written", sent)
    sent, _ = boot(tmpdir(), write=garbling("pointer.txt"))
    is_alarm("pointer reads back different", sent)

    print("\n[the raise itself, not the words, makes it a failure]")
    try:
        ov.install(None)
        check("install(None) raises", False, True)
    except ov.OverlayTrouble as exc:
        check("install(None) raises OverlayTrouble with a plain line", "OK-WW" in str(exc), True)
    check("a fault counts even when no trouble word matches",
          texts.patches(1, ["随便什么话"], ["随便什么话"]).startswith("⚠️"), True)
    check("a fault that also has a trouble word is counted once",
          "1 条没贴上" in texts.patches(1, ["OK-WW 有改动没贴上"], ["OK-WW 有改动没贴上"]), True)
    check("the old two-argument call is unchanged", texts.patches(2, ["a", "b"]), "🩹 OK-WW 补丁（2 条）")


def _part_okww_overlay_install_guard():
    """install() leaves ok_tasks/ark_overrides.py alone unless it must change, and never
rewrites it under a running OK-WW (audit 2026-10-13, A2).
    """
    import os

    from ark_relay.core import desktop as procs, texts
    from ark_relay.core import config as C
    from ark_relay.features import okww_overlay as ov


    REAL_RUNNING = getattr(ov, "okww_running", None)
    asked = []


    def running(answer):
        def f():
            asked.append(answer)
            return answer
        return f


    WANT = ov.source_text().encode("utf-8")

    print("[CRLF copy on disk (same text, other bytes): rewritten to the exact bytes]")
    root = tmpdir()
    dest = ov.target(root)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(WANT.replace(b"\n", b"\r\n"))
    ov.okww_running = running(False)
    try:
        line = ov.install(root)
        check("rewritten", dest.read_bytes(), WANT)
        check("says where", "ok_tasks" in line)

        print("\n[identical bytes: nothing written, no process list asked for]")
        asked.clear()
        os.utime(dest, (1_000_000_000, 1_000_000_000))
        check("returns ''", ov.install(root), "")
        check("process list not asked", asked, [])
        check("file not touched (mtime kept)", int(dest.stat().st_mtime), 1_000_000_000)

        print("\n[different bytes while OK-WW runs: left alone, a logged line]")
        dest.write_bytes(b"# an older overlay\n")
        ov.okww_running = running(True)
        line = ov.install(root)
        check("file unchanged", dest.read_bytes(), b"# an older overlay\n")
        check("says OK-WW is running", "正在运行" in line)
        check("not a fault: 🩹 title", texts.patches(1, [line]).startswith("🩹"))

        print("\n[different bytes, cannot tell whether OK-WW runs: written]")
        ov.okww_running = running(None)
        ov.install(root)
        check("written", dest.read_bytes(), WANT)
    finally:
        ov.okww_running = REAL_RUNNING

    print("\n[okww_running: pythonw.exe with ok-ww on its command line is OK-WW]")
    real_pp, real_win = procs.python_processes, C.IS_WINDOWS
    seen = {}


    def pp(rows):
        def f(**kw):
            seen.update(kw)
            return rows
        return f


    try:
        C.IS_WINDOWS = True
        procs.python_processes = pp([(1, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"),
                                     (2, r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe "
                                         r"D:\ark\okww\data\apps\ok-ww\working\main.py -t 1 -e")])
        check("OK-WW up", ov.okww_running(), True)
        check("asks for python.exe and pythonw.exe", seen.get("hosts"), C.PYTHON_HOSTS)
        check("leaves the outage alarm to the boot self-check", seen.get("warn"), False)
        procs.python_processes = pp([(1, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py")])
        check("only AUTO-MAS: not up", ov.okww_running(), False)
        procs.python_processes = pp(None)
        check("list unreadable: cannot tell", ov.okww_running(), None)
    finally:
        C.IS_WINDOWS = real_win
        procs.python_processes = real_pp
    check("not Windows: cannot tell", ov.okww_running(), None)

    print("\n[procs.python_processes(hosts=...) queries every host name]")
    queries = []
    real_q = procs._query_once
    procs._query_once = lambda query=procs._QUERY: (queries.append(query), ([], ""))[1]
    try:
        procs.python_processes(hosts=C.PYTHON_HOSTS)
        procs.python_processes()
    finally:
        procs._query_once = real_q
    check("pythonw.exe and python.exe both in the query",
          bool(queries) and "Name='pythonw.exe'" in queries[0] and "Name='python.exe'" in queries[0])
    check("the default query is unchanged", queries[1:], [procs._QUERY])


def _part_okww_overlay_pending():
    """An overlay install skipped because OK-WW was running is tried again before the
relay next starts a run itself, and is said to the group if it still cannot be done.
    """
    import logging
    import os
    import types


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")


    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
                  "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi",
                  "pythoncom", "win32com", "win32com.client")

    import boot_stages
    from ark_relay.features import okww_overlay as ov
    from ark_relay.features import commands
    from ark_relay.features import preupdate
    from ark_relay.features import errwatch

    errwatch.system_shutting_down = lambda: False


    class Warnings(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    W = Warnings()
    ov.log.addHandler(W)
    REAL_RUNNING = ov.okww_running
    running = {"now": True}
    ov.okww_running = lambda: running["now"]
    WANT = ov.source_text().encode("utf-8")

    try:
        print("[skipped at boot while OK-WW runs: pending]")
        root = tmpdir()
        dest = ov.target(root)
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"# old overlay\n")
        ov.install(root)
        check("file left alone", dest.read_bytes(), b"# old overlay\n")
        check("pending", ov._pending.get("dir"), root)

        print("\n[tried again while OK-WW still runs: a WARNING (to the group), file left alone]")
        W.lines.clear()
        line = ov.retry_pending("单独开跑「OK-WW」前")
        check("one warning", len(W.lines), 1)
        check("says where and that the old overlay runs", "单独开跑「OK-WW」前" in line and "旧" in line, True)
        check("file still the old one", dest.read_bytes(), b"# old overlay\n")

        print("\n[tried again once OK-WW stopped: installed, no warning, nothing pending]")
        running["now"] = False
        W.lines.clear()
        ov.retry_pending("预更新后")
        check("installed", dest.read_bytes(), WANT)
        check("no warning", W.lines, [])
        check("nothing pending", ov._pending, {})
        check("nothing pending: no-op", ov.retry_pending("x"), "")

        print("\n[the relay's own dispatch tries it before starting]")
        order = []
        real = (ov.retry_pending, commands._mas, commands._note_dispatch)
        ov.retry_pending = lambda where: order.append(("retry", where)) or ""
        commands._note_dispatch = lambda what: None

        def mas(path, body=None):
            if path == "/api/scripts/get":
                return {"data": {"s1": {"Info": {"Name": "OK-WW"}}}}
            if path == "/api/queue/get":
                return {"data": {"q1": {"Info": {"Name": "早班"}}}}
            order.append(("dispatch", body["tasks"]["0"]["uid"]))
            return {"status": "success"}
        commands._mas = mas
        try:
            commands.run_script("OK-WW")
            check("script: retry before dispatch", [k for k, _ in order], ["retry", "dispatch"])
            order.clear()
            commands._run_now("早班")
            check("queue: retry before dispatch", [k for k, _ in order], ["retry", "dispatch"])
            print("\n[the pre-update tries it after closing OK-WW]")
            order.clear()
            real_pre = (preupdate.run_okww, ov.drift_line)
            preupdate.run_okww = lambda okww, problems=None, **_k: order.append(("preupdate", "")) or ""
            ov.drift_line = lambda okww, state_dir: ""
            try:
                notes = types.SimpleNamespace(send=lambda *a, **k: [])
                cfg = types.SimpleNamespace(okww_dir=root, automas_dir=None, state_dir=tmpdir())
                boot_stages._preupdate_okww(cfg, notes, boot_stages.log, [])
            finally:
                preupdate.run_okww, ov.drift_line = real_pre
            check("pre-update, then retry", [k for k, _ in order], ["preupdate", "retry"])
        finally:
            ov.retry_pending, commands._mas, commands._note_dispatch = real
    finally:
        ov.okww_running = REAL_RUNNING
        ov._pending.clear()


def _part_okww_overlay_param_start():
    """The task AUTO-MAS names on OK-WW's command line (`-t 1 -e`) is started, not dropped."""
    import threading
    import types

    from ark_relay.features import okww_overlay

    FIXTURE = fx_dir(Path(__file__), "fixtures") / "okww-v3.7.20-beta.3-start_controller.py.txt"
    CANCELLED = "was cancelled while the game was starting"
    NAMES = ("ok", "ok.device", "ok.device.capture", "ok.core", "ok.core.events", "ok.core.notifications",
             "ok.util", "ok.util.process", "ok.core.start_controller")
    saved = {n: sys.modules.get(n) for n in NAMES}

    class Signal:
        def __init__(self):
            self.sent = []

        def emit(self, *a):
            self.sent.append(a)

    class Log:
        def __init__(self, lines):
            self.lines = lines

        def info(self, msg, *a):
            self.lines.append(str(msg))

        error = warning = debug = info

    class Task:
        def __init__(self, name, executor):
            self.name, self.executor = name, executor
            self._enabled = False
            self.paused = False
            self.exit_after_task = False

        @property
        def enabled(self):
            return self._enabled

        def info_clear(self):
            pass

        def __repr__(self):
            return f"<{self.name}>"

    class Executor:
        def __init__(self):
            self.onetime_tasks = [Task("DailyTask", self), Task("Other", self)]
            self.current_task = None
            self.paused = False
            self.queued = []
            self.started = 0

        def get_all_tasks(self):
            return list(self.onetime_tasks)

        def enqueue_onetime_task(self, task):
            self.queued.append(task)

        def start(self):
            self.started += 1

    def world(fixture_text):
        """Fresh stand-ins, the upstream file executed on them. -> (StartController, og, log lines)."""
        lines = []
        og = types.SimpleNamespace(executor=Executor(), app=None,
                                   device_manager=types.SimpleNamespace(do_refresh=lambda *a: None))
        ok = types.ModuleType("ok")
        ok.og = og
        ok.Handler = type("Handler", (), {"__init__": lambda self, *a: None, "post": lambda self, fn: fn()})
        ok.Logger = type("Logger", (), {"get_logger": staticmethod(lambda name: Log(lines))})
        mods = {"ok": ok}
        for name, attrs in (("ok.device", {}), ("ok.core", {}), ("ok.util", {}),
                            ("ok.device.capture", {"BaseWindowsCaptureMethod": object, "BrowserCaptureMethod": object}),
                            ("ok.core.events", {"communicate": types.SimpleNamespace(starting_emulator=Signal(), task=Signal())}),
                            ("ok.core.notifications", {"alert_error": lambda *a, **k: None, "alert_info": lambda *a, **k: None}),
                            ("ok.util.process", {"is_admin": lambda: True, "execute": lambda *a, **k: None,
                                                 "WINDOWS_START_METHOD_START": "start"})):
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            mods[name] = m
        sys.modules.update(mods)
        sc = types.ModuleType("ok.core.start_controller")
        sys.modules["ok.core.start_controller"] = sc
        exec(compile(fixture_text, "start_controller.py", "exec"), sc.__dict__)
        return sc.StartController, og, lines

    def controller(cls, start_exe=False, device_ok=True):
        sub = type("C", (cls,), {"check_auto_hdr": lambda self: None,
                                 "check_gpu_driver_post_processing": lambda self: None,
                                 "start_device": lambda self, initial_refresh_done=False: device_ok})
        return sub({"windows": {"start_exe": start_exe}}, threading.Event())

    def install():
        """The overrides file executed in this world, as ok-script does at start-up."""
        ns = {"__name__": "ark_overrides_test"}
        exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
        return ns

    text = FIXTURE.read_text(encoding="utf-8")
    try:
        print("[上游 v3.7.20-beta.3 自己：命令行带起的任务被它当成已取消]")
        cls, og, lines = world(text)
        c = controller(cls)
        daily = og.executor.onetime_tasks[0]
        check("upstream alone: do_start returns True all the same", c.do_start(0, True), True)
        check("upstream alone: says it was cancelled", any(CANCELLED in x for x in lines), True)
        check("upstream alone: the daily task is not enabled", (daily.enabled, og.executor.queued), (False, []))

        print("[装上我们的改动：照常起跑]")
        cls, og, lines = world(text)
        ns = install()
        check("listed as applied", "StartController._do_start" in ns["_applied"], True)
        check("not listed as skipped", [x for x in ns["_skipped"] if "StartController" in x["what"]], [])
        c = controller(cls)
        daily, other = og.executor.onetime_tasks
        check("do_start(0, exit_after)", c.do_start(0, True), True)
        check("no 'was cancelled' line", [x for x in lines if CANCELLED in x], [])
        check("the daily task is enabled and queued once", (daily.enabled, og.executor.queued), (True, [daily]))
        check("exit after the task (-e) is kept", daily.exit_after_task, True)
        check("the executor is started", og.executor.started, 1)
        check("nothing left waiting", c._pending[1], [])
        check("the other task is untouched", (other.enabled, other.exit_after_task), (False, False))
        check("our line names the task", any(ns["PARAM_START"] in x and "DailyTask" in x for x in lines), True)

        print("[上游自己的取消逻辑不受影响]")
        cls, og, lines = world(text)
        install()
        c = controller(cls)
        daily, other = og.executor.onetime_tasks
        c._add_pending(other)
        check("a task asked for in the window can still be cancelled", c.cancel_task(other), True)
        check("its queued start is skipped", c.do_start(other, False, from_queue=True), False)
        check("and it stays disabled", other.enabled, False)
        c._do_start(other, False)                # reached directly, without being pending: upstream drops it
        check("a non-pending task object is still dropped by upstream", (other.enabled, any(CANCELLED in x for x in lines)),
              (False, True))
        c._add_pending(other)
        check("a pending one is started", (c.do_start(other, False, from_queue=True), other.enabled), (True, True))

        print("[游戏没起来：不留一个「等着」的任务]")
        cls, og, lines = world(text)
        install()
        c = controller(cls, start_exe=True, device_ok=False)
        daily = og.executor.onetime_tasks[0]
        check("a failed launch returns False", c.do_start(0, True), False)
        check("the daily task is not left on the pending list", c._pending[1], [])
        check("and is not enabled", daily.enabled, False)

        print("[下标不对：照上游自己的报法]")
        cls, og, lines = world(text)
        install()
        c = controller(cls)
        check("a bad index is upstream's own failure", c.do_start(9, True), False)
        check("nothing waiting, nothing queued", (c._pending[1], og.executor.queued), ([], []))

        print("[没有待启动名单的旧版：不动它]")
        old = text.replace("    def _pending(self):", "    def _pending_gone(self):")
        cls, og, lines = world(old)
        before = cls._do_start
        ns = install()
        check("not applied, not skipped", ("StartController._do_start" in ns["_applied"],
                                           [x for x in ns["_skipped"] if "StartController" in x["what"]]), (False, []))
        check("upstream's _do_start is still upstream's", cls._do_start is before, True)

        print("[上游把 _do_start 改名或改了参数：不贴，记进没贴上]")
        cls, og, lines = world(text.replace("    def _do_start(self, task=None, exit_after=False):",
                                            "    def _do_start2(self, task=None, exit_after=False):")
                               .replace("self._do_start(task, exit_after)", "self._do_start2(task, exit_after)"))
        ns = install()
        why = [x["why"] for x in ns["_skipped"] if "StartController" in x["what"]]
        check("renamed away: skipped with the reason", ("StartController._do_start" in ns["_applied"], len(why),
                                                        "没有这个方法" in (why or [""])[0]), (False, 1, True))
        cls, og, lines = world(text.replace("    def _do_start(self, task=None, exit_after=False):",
                                            "    def _do_start(self, task=None, exit_after=False, *, reason):"))
        before = cls._do_start
        ns = install()
        why = [x["why"] for x in ns["_skipped"] if "StartController" in x["what"]]
        check("a parameter ours cannot pass on: skipped, upstream's left in place",
              ("StartController._do_start" in ns["_applied"], len(why), cls._do_start is before), (False, 1, True))

        print("[param_task_pending 本身]")
        ns = install()
        fn = ns["param_task_pending"]
        holder = types.SimpleNamespace(_pending=(threading.Lock(), []))
        check("an index puts the task on the list", (fn(holder, 1, ["a", "b"]), holder._pending[1]), ("b", ["b"]))
        check("twice is once", (fn(holder, 1, ["a", "b"]), holder._pending[1]), ("b", ["b"]))
        for junk in (None, True, "1", object()):
            check(f"{junk!r} is not an index", fn(holder, junk, ["a", "b"]), None)
        check("no list on this upstream", fn(types.SimpleNamespace(), 0, ["a"]), None)
    finally:
        for n, m in saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m


def _part_okww_overlay_copies():
    import re
    from pathlib import Path

    from ark_relay.features import okww_overlay

    src = okww_overlay.source_text()

    # Everything we change, and the marker that proves it is still in the file.
    CHANGES = {
        "复活之后接着刷下一趟": "刷声骸模式：复活成功，接着刷下一趟",
        "连败三次就收手": "次失败，退出本次任务，不再重试",
        "周本进本前读剩余次数": "本周周本次数已领满（0/3）",
        "波片不足就跳过周本": "单人挑战后的提醒框",
        "无音区结算页留一张图": "tacet_drops",
        "附加任务提到刷体力之前": "附加任务出错，不拖垮当趟日常",
        "标记文件在就不刷体力": "刷体力已禁用（标记文件在）",
        "附加任务一趟只跑一次": "makes their trailing call a no-op",
        "每趟开始时把那个标记清零": "self._ark_additional_ran = False",
        "限时提前开放的剧情提示框": "限时提前开放的剧情提示框",
        "限时提前开放后直接进场": "限时提前开放：确认后直接进场",
        "主动跳过的信号照原样抛": "isinstance(exc.__cause__, TaskDisabledException)",
        "传送界面来晚了再等一次": "多等 15 秒",
        "巢穴只刷指定点位": "Only Farm These Nests",
        "周本打完按 F 领奖": "周本领奖：已点确认",
        "周本领完点退出副本": "退出副本",
        "巢穴没打满就接着打": "is not complete",
        "巢穴白打一局就拉黑": "no progress after an attempt",
        "周本单人挑战没接就补点": "补点第",
        "体力数/数没读到不当 0": "不当 0",
    }

    print("[每一条改动都还在]")
    for name, marker in CHANGES.items():
        check(name, marker in src)

    # A replacement stops upstream's body from running, so it must be pinned.
    # Everything else wraps.
    REPLACEMENTS = {"click_team_challenge", "find_nest", "get_stamina", "get_total_daily_points"}

    print("[只有四处整段替换，而且都钉了指纹]")
    bound = re.findall(r'@override\((\w+), "(\w+)"([^)]*)\)', src)
    bound += [(c, m, r) for c, m, r in re.findall(r'override\((\w+), "(\w+)"([^)]*)\)\(', src)]
    names = {m for _, m, _ in bound}
    check("绑上的方法数不为零", len(names) > 0)
    for cls, meth, rest in bound:
        if meth in REPLACEMENTS:
            check(f"{cls}.{meth} 钉了指纹", "expect_sha" in rest)
        else:
            check(f"{cls}.{meth} 不是整段替换", "expect_sha" in rest, False)

    print("[不许再出现整段抄件：抄件里必然带着上游的循环和分支]")
    for banned in ("def farm_do_run(", "def farm_teleport(", "def daily_run(",
                   "def tacet_farm(", "def farm_run("):
        check(f"没有 {banned.strip('def (')}", banned in src, False)

    print("[包一层的必须真的调用上游那份]")
    for captured in ("nest_run(self", "capture_run(self", "next_nest(self", "daily_run(self", "farm_run(self", "farm_combat(self", "pick_level(self", "tacet_stamina(self",
                     "open_daily(self", "run_additional(self", "original(self",
                     "inner(self", "outer(self", "prepare(self"):
        check(f"调用了 {captured.split('(')[0]}", captured in src)

    print("\n[每一条绑定都要么有「触发→痕迹」核对，要么有一个真的去跑它的测试]")
    from ark_relay.features import outcome
    TESTS = Path(__file__).resolve().parent
    bound = set(re.findall(r'@override\((\w+), "(\w+)"', src))
    bound |= set(re.findall(r'_farm_hook\((\w+), "(\w+)"\)', src))
    bound = {f"{c}.{m}" for c, m in bound}
    labels = {lbl for lbl, *_ in outcome._PATCH_EFFECTS} | {"无音区改动在跑（结算页留图）"}
    check("旧的「写个理由就算」那张表已经删了", hasattr(outcome, "PATCH_NO_TRIGGER"), False)
    for key in sorted(bound):
        covered = key in outcome.PATCH_COVERAGE
        tested = key in outcome.BEHAVIOUR_TESTS
        check(f"{key} 有核对或有测试", covered or tested)
        if covered:
            check(f"{key} 指向的核对真的存在", outcome.PATCH_COVERAGE[key] in labels)
        if tested:
            f = TESTS / outcome.BEHAVIOUR_TESTS[key]
            check(f"{key} 的测试文件在", f.is_file())
            meth = key.split(".")[1]
            check(f"{key} 的测试文件提到 {meth}", f.is_file() and meth in f.read_text(encoding="utf-8"))
    stale = (set(outcome.PATCH_COVERAGE) | set(outcome.BEHAVIOUR_TESTS)) - bound
    check("登记表里没有已经不存在的绑定", sorted(stale), [])


def _part_echo_farm_main():  # noqa: C901
    """Farm a boss until a wall-clock time, then put everything back."""
    import json
    from datetime import datetime

    from ark_relay.features import echofarm
    from ark_relay.core.config import SERVER_TZ

    ORIGINAL = {"Teleport to Boss": "Weekly Challenge", "Boss Level": "90",
                "Which Boss Challenge to Teleport": 1, "Which Weekly Boss to Teleport": 1,
                "Repeat Farm Count": 3, "Echo Pickup Method": "Walk"}

    def fresh():
        """An OK-WW tree shaped the way the machine's is: the live config sits under
    the pyappify working directory, not at the install root. The first attempt on
    2026-09-09 looked at the root and the command answered 「找不到」."""
        root = tmpdir()
        d = root.joinpath(*echofarm._WORKING, "configs")
        d.mkdir(parents=True)
        (d / "FarmEchoTask.json").write_text(json.dumps(ORIGINAL, ensure_ascii=False), encoding="utf-8")
        return _Cfg(root)

    def cfg_now(c):
        return json.loads(echofarm._cfg_path(c.okww_dir).read_text(encoding="utf-8"))

    launched = []
    echofarm._launch = lambda: (launched.append(1), (True, ""))[1]
    echofarm.stop_okww = lambda: launched.append("stop")
    _real_stop_script = echofarm.stop_okww_script
    echofarm.stop_okww_script = lambda: launched.append("script") or ""
    # The marker file lives in C:\ProgramData on the machine. Point it at a temp path so
    # the tests never write into the repo (and never into a real machine path either).
    echofarm.NO_CLAIM = str(tmpdir() / "no-claim")

    print("[配置路径：按机器上的真实布局找，找不到就说找不到]")
    _empty = tmpdir()
    check("没有配置文件时不假装有", echofarm._cfg_path(_empty).is_file(), False)
    check("目录是 None 时返回 None", echofarm._cfg_path(None), None)

    print("[结束时刻：认得 08:30，认不出的一律拒绝]")
    now = datetime(2026, 9, 9, 4, 0, tzinfo=SERVER_TZ)
    NOW = now
    check("今天还没到就是今天", echofarm.resolve_until("08:30", now).strftime("%m-%d %H:%M"), "09-09 08:30")
    check("已经过了就是明天", echofarm.resolve_until("03:00", now).strftime("%m-%d %H:%M"), "09-10 03:00")
    for bad in ("25:00", "8点半", "", None, "08:70"):
        check(f"拒绝 {bad!r}", echofarm.resolve_until(bad, now), None)

    print("\n[开跑：配置改成打指定 boss，原来那份完整存下来]")
    c = fresh()
    ok, msg = echofarm.start(c, 1, "08:30", "天傀劫煞", now=NOW)
    check("开跑了", ok, True)
    check("话里有目标和时刻（手机的时间）", "天傀劫煞" in msg and "09:30" in msg and "机器时间" not in msg, True)
    check("真的启动了一次", len(launched), 1)
    after = cfg_now(c)
    check("改成了打强敌", after["Teleport to Boss"], "Boss Challenge")
    check("第几个", after["Which Boss Challenge to Teleport"], 1)
    check("次数交给时钟，不再是 3", after["Repeat Farm Count"], echofarm.BIG_COUNT)
    check("等级是会掉声骸的最低一档 80（50 级不掉声骸）", after["Boss Level"], "80")
    check("配置里写的就是 FARM_LEVEL", after["Boss Level"], echofarm.FARM_LEVEL)
    check("不是原来那个 90", echofarm.FARM_LEVEL != ORIGINAL["Boss Level"], True)
    check("原配置一字不落地存着", echofarm.current(c.state_dir)["saved"], ORIGINAL)

    print("\n[正在刷的时候不许再开一趟]")
    ok2, msg2 = echofarm.start(c, 2, "09:00", "别的")
    check("被拒", ok2, False)
    check("说清在刷什么、刷到几点", "天傀劫煞" in msg2 and "09:30" in msg2, True)

    print("\n[没到点什么都不做]")
    check("还早", echofarm.tick(c, datetime(2026, 9, 9, 7, 0, tzinfo=SERVER_TZ)), "")
    check("还在记录里", bool(echofarm.current(c.state_dir)), True)

    print("\n[到点：停掉、原样还原、状态清空]")
    note = echofarm.tick(c, datetime(2026, 9, 9, 8, 30, tzinfo=SERVER_TZ))
    check("出了收工的话", "到点了" in note and "天傀劫煞" in note, True)
    check("停过了", "stop" in launched, True)
    check("配置一字不差地还原", cfg_now(c), ORIGINAL)
    check("状态清空", echofarm.current(c.state_dir), {})
    check("再 tick 一次什么都不做", echofarm.tick(c, datetime(2026, 9, 9, 9, 0, tzinfo=SERVER_TZ)), "")

    print("\n[跑到一半改收工时刻：提前或延后都行，别的不动]")
    c = fresh()
    echofarm._launch = lambda: (launched.append(1), (True, ""))[1]
    echofarm.start(c, 1, "08:30", "天傀劫煞", now=NOW)
    _before = dict(echofarm.current(c.state_dir))
    ok, msg = echofarm.retime(c, "21:00", now=NOW)
    check("改成功", ok, True)
    check("话里有新旧两个时刻（手机的时间）", "09:30" in msg and "22:00" in msg, True)
    check("话里说了还剩多久", "还剩" in msg, True)
    check("记录里的收工时刻真的变了", echofarm.current(c.state_dir)["until"][11:], "21:00")
    check("原配置一字没动", echofarm.current(c.state_dir)["saved"], _before["saved"])
    check("开跑时刻没被改掉", echofarm.current(c.state_dir)["started"], _before["started"])
    check("提前也行", echofarm.retime(c, "05:00", now=NOW)[1].count(":") >= 2, True)
    # A time already past rolls to tomorrow, the same rule as starting a farm.
    check("已经过去的时刻算明天的，和开跑时同一条规则",
          echofarm.retime(c, "03:00", now=datetime(2026, 9, 9, 4, 0, tzinfo=SERVER_TZ))[0], True)
    check("确实记成了明天", echofarm.current(c.state_dir)["until"][:10], "2026-09-10")
    for bad in ("25:00", "九点", ""):
        check(f"看不懂的时刻拒绝 {bad!r}", echofarm.retime(c, bad, now=NOW)[0], False)
    echofarm.finish(c, "收尾")
    check("没在刷的时候改不了", echofarm.retime(c, "21:00", now=NOW)[0], False)
    check("而且说清是没在刷", "没有在刷" in echofarm.retime(c, "21:00", now=NOW)[1], True)

    print("\n[刷的时候手机改了母本：收工按现在的母本还原，五项都核（11-08 [D-06]）]")
    c = fresh()
    echofarm.start(c, 3, "08:30", "第 3 个")
    _changed = dict(ORIGINAL, **{"Which Weekly Boss to Teleport": 7})
    _saved_truth = echofarm._truth
    echofarm._truth = lambda cfg, working: dict(_changed)
    echofarm.finish(c, "手动停止")
    echofarm._truth = _saved_truth
    check("刷的时候改的周本序号还在", cfg_now(c).get("Which Weekly Boss to Teleport"), 7)
    c = fresh()
    echofarm.start(c, 3, "08:30", "第 3 个")
    echofarm._truth = lambda cfg, working: json.loads(working.read_text(encoding="utf-8"))
    echofarm.finish(c, "手动停止")
    echofarm._truth = _saved_truth
    check("母本读不到时（拿到的是刷声骸那份）：还用开刷时记下的", cfg_now(c), ORIGINAL)

    print("\n[手动停：一样还原]")
    c = fresh()
    echofarm.start(c, 3, "08:30", "第 3 个")
    note = echofarm.finish(c, "手动停止")
    check("话里说是手动停的", "手动停止" in note, True)
    check("配置还原", cfg_now(c), ORIGINAL)

    print("\n[the engine's wrap-up: a failed one is a group alarm, a clean one is not]")
    import types
    from datetime import timedelta
    from ark_relay.core import texts
    from ark_relay.core.engine import Engine
    from ark_relay.core.notify import route_of

    class _Sent:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return []

    def _wrapup(c):
        """The engine's tick step on the real clock; (route, is a wrap-up title) of each push."""
        eng = types.SimpleNamespace(cfg=c, notifier=_Sent())
        Engine._echo_farm_deadline(eng)
        return [(route_of(t, alert=a), "收工" in t) for t, _, a in eng.notifier.sent]

    def _farm(**fields):
        c = fresh()
        echofarm.start(c, 1, "08:30", "天傀劫煞", now=NOW)      # until 2026-09-09 08:30: long past
        rec = echofarm.current(c.state_dir)
        rec.update(fields)
        echofarm._store(c.state_dir).set("queues", "echo_farm", rec)
        return c

    import ark_relay.features.weeklyboss as _wbw
    _wrap_log = tmpdir() / "wrap.log"
    _wrap_real = _wbw._okww_log
    _wbw._okww_log = lambda: _wrap_log
    _wrap_log.write_text("2026-09-09 04:01:00,000 INFO TaskExecutor FarmEchoTask:enter combat None\n"
                         "2026-09-09 04:02:00,000 INFO TaskExecutor FarmEchoTask:farm echo on the face\n",
                         encoding="utf-8")
    check("on time, all put back, OK-WW farmed: one info wrap-up", _wrapup(_farm()), [("info", True)])
    _wrap_log.write_text("2026-09-09 03:00:00,000 INFO TaskExecutor FarmEchoTask:farm echo before the start\n"
                         + "".join(f"2026-09-09 04:{m:02d}:00,000 INFO hwnd_window changed\n" for m in range(1, 50)),
                         encoding="utf-8")
    check("on time but nothing farmed since the start: the group", _wrapup(_farm()), [("group", True)])
    _c0 = _farm()
    _note0, _bad0 = echofarm.tick_result(_c0)
    check("…and the line says nothing was farmed", ("一次都没刷到" in _note0, _bad0), (True, True))
    _wrap_log.write_text("2026-09-09 04:01:00,000 INFO TaskExecutor FarmEchoTask:enter combat None\n"
                         "2026-09-09 04:02:00,000 INFO TaskExecutor FarmEchoTask:farm echo on the face\n",
                         encoding="utf-8")
    _c1 = _farm()
    _note1, _bad1 = echofarm.tick_result(_c1)
    check("a farmed night's line gives the count", ("有 2 次进展" in _note1, _bad1), (True, False))
    check("…without the log name or 「配置已还原」", ("OK-WW 日志" in _note1 or "配置已还原" in _note1, "从 " in _note1), (False, True))

    print("\n[the wrap-up names the level the game showed, never the configured one]")
    _BS = "INFO TaskExecutor FarmEchoTask:boss_string is "
    _wrap_log.write_text(
        f"2026-09-09 03:50:00,000 {_BS}[Lv.90天演溯心·衍律化形_0.92]\n"     # an earlier session
        f"2026-09-09 04:01:00,000 {_BS}[]\n"
        f"2026-09-09 04:01:30,000 {_BS}[Lv.90.天傀劫煞_0.97]\n"
        "2026-09-09 04:02:00,000 INFO TaskExecutor FarmEchoTask:farm echo on the face\n"
        f"2026-09-09 04:03:00,000 {_BS}[Lv.90天傀劫煞_0.97]\n"
        f"2026-09-09 04:04:00,000 {_BS}[]\n", encoding="utf-8")
    _level_since = getattr(echofarm, "level_since", lambda started: None)   # absent before: fail, not crash
    check("the newest level read since the start",
          _level_since(echofarm._started_at(echofarm.current(_farm().state_dir))), ("90", "天傀劫煞"))
    _n5, _b5 = echofarm.tick_result(_farm())
    check("…is in the wrap-up line", "刷天傀劫煞（游戏里 Lv.90）结束" in _n5, True)
    check("…and the configured level is not", "80" in _n5, False)
    _wrap_log.write_text(
        f"2026-09-09 03:50:00,000 {_BS}[Lv.90天演溯心·衍律化形_0.92]\n"
        f"2026-09-09 04:01:00,000 {_BS}[]\n"
        "2026-09-09 04:02:00,000 INFO TaskExecutor FarmEchoTask:farm echo on the face\n", encoding="utf-8")
    _n6, _b6 = echofarm.tick_result(_farm())
    check("no level read in this farm: 「等级没读到」, not the configured 80",
          ("刷天傀劫煞（等级没读到）结束" in _n6, "80" in _n6), (True, False))
    _wrap_log.write_text(
        f"2026-09-09 04:01:30,000 {_BS}[Lv.90天演溯心·衍律化形_0.92]\n"
        "2026-09-09 04:02:00,000 INFO TaskExecutor FarmEchoTask:farm echo on the face\n", encoding="utf-8")
    _n7, _b7 = echofarm.tick_result(_farm())
    check("a different boss read off the screen is named as read",
          "刷天傀劫煞（游戏里读到的是 Lv.90 天演溯心·衍律化形）结束" in _n7, True)
    _wrap_log.write_text(
        "2026-09-09 04:01:00,000 INFO TaskExecutor FarmEchoTask:enter combat None\n"
        "2026-09-09 04:02:00,000 INFO TaskExecutor FarmEchoTask:farm echo on the face\n", encoding="utf-8")
    _wbw._okww_log = lambda: None
    check("on time, OK-WW log unreadable: the group (unknown is not fine)", _wrapup(_farm()), [("group", True)])
    _c2 = fresh()
    echofarm.start(_c2, 1, "08:30", "天傀劫煞", now=NOW)
    _note2, _bad2 = echofarm._finish(_c2, "手动停止")
    check("a stop by hand is not judged on progress", _bad2, False)
    _wbw._okww_log = lambda: _wrap_log
    check("end time unreadable, farm stopped: the group", _wrapup(_farm(until="坏的")), [("group", True)])
    _launch_was, _quiet_was = echofarm._launch, echofarm.quiet_minutes
    echofarm._launch = lambda: (False, "启动计划任务失败")
    echofarm.quiet_minutes = lambda now=None, since=None: 30.0
    try:
        tomorrow = (datetime.now(tz=SERVER_TZ) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        got = _wrapup(_farm(until=tomorrow, started="2026-09-09 04:00"))
    finally:
        echofarm._launch, echofarm.quiet_minutes = _launch_was, _quiet_was
    check("OK-WW stopped and the relaunch failed: the group", got, [("group", True)])
    _stop_was = echofarm.stop_okww
    echofarm.stop_okww = lambda: texts.echo_farm_game_left(["Client-Win64-Shipping.exe"])
    try:
        got = _wrapup(_farm())
    finally:
        echofarm.stop_okww = _stop_was
    check("on time but the game left open: the group", got, [("group", True)])
    _wbw._okww_log = _wrap_real

    # docs/SILENT-FAILURES-AUDIT.md echofarm.py:423 - a failed restore used to replace
    # the note, so 「游戏没关掉」 from stop_okww never reached the receipt.
    print("\n[finish: every warning reaches the receipt, none overwrites another]")
    _stub_stop = echofarm.stop_okww
    echofarm.stop_okww = lambda: "；**游戏没关掉（Client-Win64-Shipping.exe），已交给我们这边去关**"
    try:
        c = fresh()
        echofarm.start(c, 3, "08:30", "第 3 个")
        echofarm._cfg_path(c.okww_dir).unlink()
        note = echofarm.finish(c, "手动停止")
        check("config missing: says so", "找不到配置文件" in note, True)
        check("…and still says the game is up", "游戏没关掉" in note, True)
        c = fresh()
        echofarm.start(c, 3, "08:30", "第 3 个")
        _real_write = echofarm.atomic_write_text
        echofarm.atomic_write_text = lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
        try:
            note = echofarm.finish(c, "手动停止")
        finally:
            echofarm.atomic_write_text = _real_write
        check("restore failed: says so", "没能改回去" in note, True)
        check("…and still says the game is up", "游戏没关掉" in note, True)
    finally:
        echofarm.stop_okww = _stub_stop

    print("\n[还原的是母本那份，不是 working 里上一次刷声骸留下的]")
    c = fresh()
    leftover = dict(ORIGINAL, **{"Teleport to Boss": "Boss Challenge", "Repeat Farm Count": 30})
    echofarm._cfg_path(c.okww_dir).write_text(json.dumps(leftover, ensure_ascii=False), encoding="utf-8")
    c.automas_dir = tmpdir()
    _md = c.automas_dir / "data" / "sid" / "Default" / "ConfigFile"; _md.mkdir(parents=True)
    (_md / "DailyTask.json").write_text("{}", encoding="utf-8")
    (_md / "FarmEchoTask.json").write_text(json.dumps(ORIGINAL, ensure_ascii=False), encoding="utf-8")
    echofarm.start(c, 3, "08:30", "第 3 个")
    check("刷的时候是刷声骸的设置", cfg_now(c)["Which Boss Challenge to Teleport"], 3)
    echofarm.finish(c, "手动停止")
    check("停了以后是母本的周本设置，不是 working 里的残留", cfg_now(c), ORIGINAL)

    print("\n[启动失败时不许把配置留在改过的样子]")
    c = fresh()
    echofarm._launch = lambda: (False, "计划任务起不来")
    ok3, msg3 = echofarm.start(c, 1, "08:30", "天傀劫煞")
    check("报失败", ok3, False)
    check("话里说了已还原", "已还原" in msg3, True)
    check("配置确实没动", cfg_now(c), ORIGINAL)
    check("没留下半个状态", echofarm.current(c.state_dir), {})

    print("\n[「第几个」只收 1..30 的数字]")
    echofarm._launch = lambda: (True, "")
    for bad in (0, 31, "一", None):
        c2 = fresh()
        check(f"拒绝 {bad!r}", echofarm.start(c2, bad, "08:30")[0], False)
        check(f"拒绝 {bad!r} 后配置没动", cfg_now(c2), ORIGINAL)

    print("\n[farm by main stat (2026-11-20): done only when the count read off the toasts reaches the target]")
    from ark_relay.features import okww_overlay as _ov
    _ovns = {}
    exec(compile(_ov.source_text(), "ark_overrides.py", "exec"), _ovns)
    check("the relay's stat list is the overlay's", echofarm.ECHO_STATS, _ovns["ECHO_STATS"])
    check("…and so is the line it counts", echofarm.DROP_LINE, _ovns["ECHO_DROP_LINE"])
    echofarm._launch = lambda: (launched.append(1), (True, ""))[1]
    for bad, why in (({"target_stat": "治疗", "target_count": 30}, "不认识"),
                     ({"target_stat": "治疗效果加成", "target_count": 0}, "没给刷几个"),
                     ({"target_stat": "治疗效果加成", "target_count": 501}, "超出范围"),
                     ({"target_stat": "治疗效果加成", "target_count": "三十"}, "要是数字")):
        cb = fresh()
        okb, msgb = echofarm.start(cb, 2, "08:30", now=NOW, weekly=True, **bad)
        check(f"refused: {bad}", (okb, why in msgb, cfg_now(cb) == ORIGINAL), (False, True, True))
    ct = fresh()
    okt, msgt = echofarm.start(ct, 2, "08:30", "千傀重楼", now=NOW, weekly=True,
                               target_stat="治疗效果加成", target_count=3)
    rect = echofarm.current(ct.state_dir)
    check("started, the target on the record", (okt, rect.get("target_stat"), rect.get("target_count")),
          (True, "治疗效果加成", 3))
    check("the reply says it stops on the count, the time is the latest stop", ("捡满 3 个才收工" in msgt, "最晚也在" in msgt), (True, True))
    cplain = fresh()
    echofarm.start(cplain, 1, "08:30", "天傀劫煞", now=NOW)
    check("by time as before: no target fields", "target_count" in echofarm.current(cplain.state_dir), False)
    echofarm.finish(cplain, "收尾")

    _dl = tmpdir() / "ok-script.log"
    _wbw2 = __import__("ark_relay.features.weeklyboss", fromlist=["x"])
    _real_dl, _quiet_dl = _wbw2._okww_log, echofarm.quiet_minutes
    _wbw2._okww_log = lambda: _dl
    echofarm.quiet_minutes = lambda now=None, since=None: 0.0

    def drop(hhmm, stat):
        return f"2026-09-09 {hhmm}:00,000 INFO TaskExecutor FarmEchoTask:刷声骸掉落：stat={stat} looks=2 raw='{stat}'\n"
    try:
        _dl.write_text(drop("03:50", "治疗效果加成")            # before this farm: not counted
                       + "2026-09-09 04:05:00,000 INFO TaskExecutor FarmEchoTask:farm echo on the face\n"
                       + drop("04:05", "治疗效果加成") + drop("04:07", "生命") + drop("04:09", "unknown")
                       + drop("04:11", "治疗效果加成"), encoding="utf-8")
        check("counted since the start only", echofarm.drops_since(echofarm._started_at(rect)),
              {"总捡": 4, "未读出": 1, "治疗效果加成": 2, "生命": 1})
        note, failed = echofarm.tick_result(ct, datetime(2026, 9, 9, 4, 12, tzinfo=SERVER_TZ))
        check("2 of 3: keeps farming", (note, failed), ("", False))
        check("the counts are on the record for the phone", {k: echofarm.current(ct.state_dir).get(k) for k in ("已出", "总捡", "未读出")},
              {"已出": 2, "总捡": 4, "未读出": 1})
        _dl.write_text(_dl.read_text(encoding="utf-8") + drop("04:20", "治疗效果加成"), encoding="utf-8")
        note, failed = echofarm.tick_result(ct, datetime(2026, 9, 9, 4, 21, tzinfo=SERVER_TZ))
        check("3 of 3: done, a clean wrap-up", ("刷满了" in note, "已出 3/3" in note, failed), (True, True, False))
        check("the wrap-up gives this farm's pickups and the unread", ("捡到声骸 5 个" in note, "1 个没读出主词条" in note), (True, True))
        check("…and puts everything back", (echofarm.current(ct.state_dir), cfg_now(ct)), ({}, ORIGINAL))

        cs = fresh()
        echofarm.start(cs, 2, "08:30", "千傀重楼", now=NOW, weekly=True, target_stat="治疗效果加成", target_count=30)
        note, failed = echofarm.tick_result(cs, datetime(2026, 9, 9, 8, 31, tzinfo=SERVER_TZ))
        check("the backstop before the target: says 目标未满 with the count, never 完成",
              ("目标未满" in note, "已出 3/30" in note, "刷满" in note), (True, True, False))
        check("…and it is not a fault (progress was made)", failed, False)
        cu = fresh()
        echofarm.start(cu, 2, "08:30", "千傀重楼", now=NOW, weekly=True, target_stat="治疗效果加成", target_count=1)
        _wbw2._okww_log = lambda: None
        note, failed = echofarm.tick_result(cu, datetime(2026, 9, 9, 4, 30, tzinfo=SERVER_TZ))
        check("log unreadable: no count, so no 刷满 - it keeps going", note, "")
        note, failed = echofarm.tick_result(cu, datetime(2026, 9, 9, 8, 31, tzinfo=SERVER_TZ))
        check("…and at the backstop says the count is unknown", ("目标未满" in note, "个数不准" in note), (True, True))
    finally:
        _wbw2._okww_log, echofarm.quiet_minutes = _real_dl, _quiet_dl

    print("\n[weekly boss farm (2026-10-22): Weekly Challenge, its own index key, no-claim marker on; level 80 like the overworld farm (2026-11-19)]")
    echofarm._launch = lambda: (launched.append(1), (True, ""))[1]
    cw = fresh()
    okw, msgw = echofarm.start(cw, 2, "08:30", "周本第 2 个", now=NOW, weekly=True)
    check("weekly farm started", okw, True)
    w = cfg_now(cw)
    check("teleport mode is the weekly one", w["Teleport to Boss"], "Weekly Challenge")
    check("weekly index written", w["Which Weekly Boss to Teleport"], 2)
    check("overworld index untouched", w["Which Boss Challenge to Teleport"], ORIGINAL["Which Boss Challenge to Teleport"])
    check("weekly farm level 80, not the claim's 90", w["Boss Level"], "80")
    check("weekly farm level is FARM_LEVEL", w["Boss Level"], echofarm.FARM_LEVEL)
    check("master copy still has the claim's 90", ORIGINAL["Boss Level"], "90")
    check("count handed to the clock", w["Repeat Farm Count"], echofarm.BIG_COUNT)
    check("no-claim marker on", echofarm.no_claim_on(), True)
    check("record says weekly", echofarm.current(cw.state_dir).get("weekly"), True)
    echofarm.finish(cw, "手动停止")
    check("config restored after a weekly farm", cfg_now(cw), ORIGINAL)
    check("claim level 90 back after a weekly farm", cfg_now(cw)["Boss Level"], "90")
    check("marker off after a weekly farm", echofarm.no_claim_on(), False)
    for bad in (0, 10):
        cb = fresh()
        check(f"weekly index {bad} refused (OK-WW lists 1..9)", echofarm.start(cb, bad, "08:30", weekly=True, now=NOW)[0], False)
        check(f"config untouched after weekly {bad}", cfg_now(cb), ORIGINAL)

    print("\n[刷声骸期间必须挂着「不领奖」标记：领一次奖 60 波片，通宵刷会掏空账号]")
    echofarm._launch = lambda: (launched.append(1), (True, ""))[1]
    c = fresh()
    check("开跑前没有标记", echofarm.no_claim_on(), False)
    echofarm.start(c, 1, "08:30", "天傀劫煞")
    check("开跑后标记挂上了", echofarm.no_claim_on(), True)
    echofarm.finish(c, "手动停止")
    check("收工后标记撤了", echofarm.no_claim_on(), False)

    print("\n[启动失败也不许把标记留在机器上]")
    c = fresh()
    echofarm._launch = lambda: (False, "计划任务起不来")
    echofarm.start(c, 1, "08:30", "天傀劫煞")
    check("失败后没留标记", echofarm.no_claim_on(), False)
    echofarm._launch = lambda: (launched.append(1), (True, ""))[1]

    print("\n[OK-WW 长时间一行日志都不写就自己停下来并说话]")
    import ark_relay.features.weeklyboss as _wb
    _real_log = _wb._okww_log
    _logfile = tmpdir() / "ok-ww.log"
    _logfile.write_text("2026-09-09 04:30:00 INFO farm echo on the face\n", encoding="utf-8")
    _wb._okww_log = lambda: _logfile
    try:
        check("读不出日志时不猜", echofarm.quiet_minutes(datetime(2026, 9, 9, 5, 0, tzinfo=SERVER_TZ)) is not None, True)
        c = fresh()
        echofarm.start(c, 1, "08:30", "天傀劫煞", now=NOW)
        _rec = echofarm.current(c.state_dir)
        _rec["started"] = "2026-09-09 04:00"
        echofarm._store(c.state_dir).set("queues", "echo_farm", _rec)
        import os as _os
        _quiet_since = datetime(2026, 9, 9, 4, 30, tzinfo=SERVER_TZ).timestamp()
        _os.utime(_logfile, (_quiet_since, _quiet_since))
        check("刚开跑一分钟不算停", echofarm.tick(c, datetime(2026, 9, 9, 4, 1, tzinfo=SERVER_TZ)), "")
        _before = len(launched)
        check("五分钟没刷到东西就自己重开", echofarm.tick(c, datetime(2026, 9, 9, 4, 36, tzinfo=SERVER_TZ)), "")
        check("真的重开了一次", launched[_before:].count(1), 1)
        check("重开次数记下来了", echofarm.current(c.state_dir)["restarts"], 1)
        check("刚重开完不重复开", echofarm.tick(c, datetime(2026, 9, 9, 4, 38, tzinfo=SERVER_TZ)), "")
        check("还是只开过一次", launched[_before:].count(1), 1)
        check("第一次只重开脚本，不动游戏", "stop" in launched[_before:], False)
        check("first relaunch: the old OK-WW script is stopped before the new one starts",
              launched[_before:], ["script", 1])

        _rec3 = echofarm.current(c.state_dir)
        _rec3["restarted"] = "2026-09-09 04:36"
        echofarm._store(c.state_dir).set("queues", "echo_farm", _rec3)
        _mid = len(launched)
        check("还是没进展就再来一次", echofarm.tick(c, datetime(2026, 9, 9, 4, 42, tzinfo=SERVER_TZ)), "")
        check("第二次连游戏一起重启", "stop" in launched[_mid:], True)
        check("重开次数记到 2", echofarm.current(c.state_dir)["restarts"], 2)
        check("这时还在刷，没收工", bool(echofarm.current(c.state_dir)), True)

        print("\n[重开了还是不写日志就别硬撑，收工并说清重开过几次]")
        _rec2 = echofarm.current(c.state_dir)
        _rec2["restarts"] = echofarm.MAX_RESTARTS
        echofarm._store(c.state_dir).set("queues", "echo_farm", _rec2)
        note = echofarm.tick(c, datetime(2026, 9, 9, 4, 55, tzinfo=SERVER_TZ))
        check("收工了", "天傀劫煞" in note and "重开" in note, True)
        check("配置还原了", cfg_now(c), ORIGINAL)
        check("状态清空", echofarm.current(c.state_dir), {})
        check("标记也撤了", echofarm.no_claim_on(), False)
        _wb._okww_log = lambda: None
        c = fresh()
        echofarm.start(c, 1, "08:30", "天傀劫煞")
        check("读不到日志时不许乱停", echofarm.tick(c, datetime(2026, 9, 9, 5, 0, tzinfo=SERVER_TZ)), "")
        echofarm.finish(c, "收尾")
    finally:
        _wb._okww_log = _real_log

    print("\n[判据是「有没有刷到东西」，不是「日志有没有在写」]")
    _noisy = tmpdir() / "noisy.log"
    _wb2 = __import__("ark_relay.features.weeklyboss", fromlist=["x"])
    _real2 = _wb2._okww_log
    _wb2._okww_log = lambda: _noisy
    try:
        _noisy.write_text(
            "2026-09-09 04:00:00 INFO farm echo on the face\n"
            + "".join(f"2026-09-09 04:{m:02d}:00 INFO hwnd_window:do_update_window_size changed\n"
                     for m in range(1, 40)),
            encoding="utf-8")
        stuck = echofarm.quiet_minutes(datetime(2026, 9, 9, 4, 40, tzinfo=SERVER_TZ))
        check("日志一直在写，但四十分钟没刷到东西 → 算卡住", round(stuck), 40)
        _noisy.write_text(
            "2026-09-09 04:00:00 INFO hwnd_window:do_update_window_size changed\n"
            "2026-09-09 04:39:00 INFO FarmEchoTask:farm echo walk_find_echo True\n",
            encoding="utf-8")
        fresh_ = echofarm.quiet_minutes(datetime(2026, 9, 9, 4, 40, tzinfo=SERVER_TZ))
        check("刚刷到东西就不算卡住", round(fresh_), 1)
        check("阈值给到五分钟（一趟约一分钟，死一次约两分钟）",
              echofarm.RESTART_QUIET_MINUTES, 5)

        import os as _os2
        _noise = "".join(f"2026-09-09 05:{m // 60:02d}:{m % 60:02d},000 INFO TaskExecutor retry loop "
                         + "x" * 200 + "\n" for m in range(0, 3000))
        _noisy.write_text("2026-09-09 04:00:00,000 INFO FarmEchoTask:farm echo on the face\n" + _noise,
                          encoding="utf-8")
        check("fixture: the progress line is beyond the 300 KB tail",
              _noisy.stat().st_size - len("2026-09-09 04:00:00,000 INFO FarmEchoTask:farm echo on the face\n")
              > echofarm._TAIL_BYTES, True)
        _t = datetime(2026, 9, 9, 5, 50, tzinfo=SERVER_TZ)
        _os2.utime(_noisy, (_t.timestamp(), _t.timestamp()))
        check("no progress in the tail: measured from the launch, not the fresh mtime",
              round(echofarm.quiet_minutes(_t, datetime(2026, 9, 9, 5, 20, tzinfo=SERVER_TZ))), 30)
        check("no launch time: measured from the tail's first line (a floor)",
              echofarm.quiet_minutes(_t) >= 5, True)
        _c3 = fresh()
        echofarm.start(_c3, 1, "08:30", "天傀劫煞", now=NOW)
        _r3 = echofarm.current(_c3.state_dir)
        _r3["started"] = "2026-09-09 05:20"
        echofarm._store(_c3.state_dir).set("queues", "echo_farm", _r3)
        _was3 = echofarm._launch
        _l3 = []
        echofarm._launch = lambda: (_l3.append(1), (True, ""))[1]
        try:
            echofarm.tick(_c3, _t)
        finally:
            echofarm._launch = _was3
        check("a noisy stuck farm gets its restart", (len(_l3), echofarm.current(_c3.state_dir).get("restarts")), (1, 1))
        echofarm.finish(_c3, "收尾")
    finally:
        _wb2._okww_log = _real2

    print("\n[an earlier session's progress in the same file does not count for this launch]")
    import gzip as _gz
    _day = tmpdir() / "ok-script.2026-10-12.log"
    _day.write_bytes(_gz.decompress((fx_dir(Path(__file__), "fixtures")
                                     / "ok-script-2026-10-12-cut-152532.log.gz").read_bytes()))
    _real4 = _wbw._okww_log
    _wbw._okww_log = lambda: _day
    try:
        _q = echofarm.quiet_minutes(datetime(2026, 10, 12, 15, 33, 30, tzinfo=SERVER_TZ),
                                    datetime(2026, 10, 12, 15, 28, tzinfo=SERVER_TZ))
        check("measured from the 15:28 restart, not the 11:47 line", round(_q, 1), 5.5)
        check("…so below the stall stop", _q < echofarm.STALL_MINUTES, True)
        _q0 = echofarm.quiet_minutes(datetime(2026, 10, 12, 15, 25, 40, tzinfo=SERVER_TZ),
                                     datetime(2026, 10, 12, 15, 23, tzinfo=SERVER_TZ))
        check("two minutes into the launch reads two minutes", round(_q0, 1), 2.7)
    finally:
        _wbw._okww_log = _real4

    print("\n[midnight rotation: a farm fighting through 00:00 is not 63 minutes quiet (#185, 2026-11-20 00:00:02)]")
    import os as _os5
    _rot = tmpdir()
    _old = _rot / "ok-script.2026-11-19.log"
    _new = _rot / "ok-script.log"

    def _put(path, text, hh_mm_ss):
        path.write_text(text, encoding="utf-8")
        _ts = hh_mm_ss.timestamp()
        _os5.utime(path, (_ts, _ts))

    _since5 = datetime(2026, 11, 19, 22, 57, tzinfo=SERVER_TZ)
    _at5 = datetime(2026, 11, 20, 0, 0, 2, tzinfo=SERVER_TZ)
    _real5 = _wbw._okww_log
    _wbw._okww_log = lambda: _new
    try:
        # The machine's two files at 00:00:02: the renamed one ends 23:59:59 with its last
        # progress at 23:58:54,223; the new one holds two seconds of combat, no progress yet.
        _put(_old, "2026-11-19 22:57:30,000 INFO TaskExecutor FarmEchoTask:enter combat\n"
                   "2026-11-19 23:58:54,223 INFO TaskExecutor FarmEchoTask:enter combat\n"
                   "2026-11-19 23:59:59,500 INFO TaskExecutor BaseCombatTask:switch_next_char end 0.057s\n",
             datetime(2026, 11, 19, 23, 59, 59, tzinfo=SERVER_TZ))
        _put(_new, "2026-11-20 00:00:00,762 INFO TaskExecutor BaseCombatTask:switch_next_char current_con 0.82\n"
                   "2026-11-20 00:00:01,294 INFO TaskExecutor TaskExecutor:wait_until timeout\n",
             datetime(2026, 11, 20, 0, 0, 1, tzinfo=SERVER_TZ))
        _q5 = echofarm.quiet_minutes(_at5, _since5)
        check("two seconds after the switch: quiet since 23:58:54, about a minute", round(_q5, 1), 1.1)
        check("…below the relaunch threshold", _q5 < echofarm.RESTART_QUIET_MINUTES, True)
        # Stuck for real across the switch: no progress in either file since the launch.
        _put(_old, "2026-11-19 22:50:00,000 INFO TaskExecutor FarmEchoTask:enter combat\n"
                   "2026-11-19 23:59:59,500 INFO TaskExecutor TaskExecutor:wait_until timeout\n",
             datetime(2026, 11, 19, 23, 59, 59, tzinfo=SERVER_TZ))
        check("no progress in either file since the launch: measured from the launch",
              round(echofarm.quiet_minutes(_at5, _since5)), 63)
        # A rotated file last written before this launch is not read: its progress is not this launch's.
        _put(_old, "2026-11-19 22:40:00,000 INFO TaskExecutor FarmEchoTask:enter combat\n",
             datetime(2026, 11, 19, 22, 40, tzinfo=SERVER_TZ))
        check("a file older than the launch is not read", round(echofarm.quiet_minutes(_at5, _since5)), 63)
        # A newest file cut at the tail has unread lines before it: its tail stays the floor,
        # older files are not consulted.
        _put(_old, "2026-11-19 23:59:00,000 INFO TaskExecutor FarmEchoTask:enter combat\n",
             datetime(2026, 11, 19, 23, 59, 59, tzinfo=SERVER_TZ))
        _put(_new, "".join(f"2026-11-20 00:{m // 60:02d}:{m % 60:02d},000 INFO TaskExecutor retry loop " + "x" * 200 + "\n"
                           for m in range(0, 1800)), datetime(2026, 11, 20, 0, 30, tzinfo=SERVER_TZ))
        check("fixture: the new file is beyond the tail", _new.stat().st_size > echofarm._TAIL_BYTES, True)
        _q6 = echofarm.quiet_minutes(datetime(2026, 11, 20, 0, 30, tzinfo=SERVER_TZ), _since5)
        # No progress in the tail of a cut file: measured from the launch as before (93), not
        # from the older file's 23:59 progress (that would read 31).
        check("a cut newest file: older files not consulted, the launch is the floor", round(_q6), 93)
    finally:
        _wbw._okww_log = _real5

    print("\n[进度关键词：只认今天真的会写出来的句子]")
    _replay = (fx_dir(Path(__file__), "replay") / "2026-09-07" / "wuwa"
               / "OK-WW-06-00-55.log").read_text(encoding="utf-8")
    from ark_relay.features import okww_overlay as _ov
    _overrides = _ov.source_text()
    for _k in echofarm.PROGRESS:
        check(f"「{_k}」今天还有人写（上游真实日志或覆盖层）", _k in _replay or _k in _overrides, True)
    _REAL = [
        "2026-09-07 10:06:50,862 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm",
        "2026-09-07 10:06:52,779 INFO TaskExecutor FarmEchoTask:enter combat None",
        "2026-09-07 10:07:53,984 INFO TaskExecutor FarmEchoTask:farm echo on the face",
        "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:限时提前开放：确认后直接进场，in_realm=True，整屏读到 []",
        "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:刷声骸模式：复活成功，接着刷下一趟",
    ]
    for _line in _REAL:
        _msg = _line.split("FarmEchoTask:", 1)[1]
        check(f"真有人写：{_msg[:30]}", _line in _replay or _msg.split("，")[0] in _overrides, True)
        check(f"算进度：{_msg[:30]}", any(k in _line for k in echofarm.PROGRESS), True)
    _NOT = [
        # The retired bosstip text patch's sentence: nothing writes it any more.
        "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:限时提前开放：已经在场地里，跳过队伍和传送这两步",
        # The overrides when the death dialog is not one they know: stuck, not moving.
        "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:刷声骸模式：这不像死亡弹窗，不乱点。整屏读到 []",
        "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:刷声骸模式：复活这一步没做成 TimeoutError()",
    ]
    for _line in _NOT:
        check(f"不算进度：{_line.split('FarmEchoTask:', 1)[1][:30]}", any(k in _line for k in echofarm.PROGRESS), False)
    _wb3 = __import__("ark_relay.features.weeklyboss", fromlist=["x"])
    _real3, _f3 = _wb3._okww_log, tmpdir() / "kw.log"
    _wb3._okww_log = lambda: _f3
    try:
        _f3.write_text(_REAL[0] + "\n" + "\n".join(_NOT) + "\n", encoding="utf-8")
        check("卡在认不出的死亡弹窗上：从最后一次真进度算起",
              round(echofarm.quiet_minutes(datetime(2026, 9, 9, 4, 40, tzinfo=SERVER_TZ))),
              round((datetime(2026, 9, 9, 4, 40) - datetime(2026, 9, 7, 10, 6, 50)).total_seconds() / 60))
        _f3.write_text("\n".join(_NOT) + "\n" + _REAL[3] + "\n", encoding="utf-8")
        check("确认后直接进场算刚动过", round(echofarm.quiet_minutes(datetime(2026, 9, 9, 4, 40, tzinfo=SERVER_TZ))), 1)
    finally:
        _wb3._okww_log = _real3

    print("\n[开跑时刻读不出来也不当成卡死]")
    check("读不出开跑时刻返回 None", echofarm._started_at({"started": "不是时间"}), None)
    check("读得出就是那个时刻", echofarm._started_at({"started": "2026-09-09 04:00"}).hour, 4)

    print("\n[stopping only the old script: bounded in time, confirmed gone, or the full stop]")
    import ark_relay.features.preupdate as _pko
    import logging as _lg

    class _Clock:
        """A monotonic clock that pwsh calls and sleeps move forward."""
        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t

    def _stop_run(answers, pwsh_secs=0.5):
        """Run the real stop_okww_script against fake pwsh: `answers` are what each
    list call returns (a list, None, or "slow" for a call that runs to its timeout).
    (result, seconds taken, timeouts handed to pwsh, naps)."""
        clk, timeouts, naps, seq = _Clock(), [], [], iter(answers)

        def stop(timeout=None):
            timeouts.append(timeout)
            clk.t += min(pwsh_secs, timeout)

        def pids(timeout=None):
            timeouts.append(timeout)
            got = next(seq)
            if got == "slow":
                clk.t += timeout
                return None
            clk.t += min(pwsh_secs, timeout)
            return got

        def nap(n):
            naps.append(n)
            clk.t += n
        real = _pko._stop_okww_python, _pko.okww_python_pids
        _pko._stop_okww_python, _pko.okww_python_pids = stop, pids
        try:
            t0 = clk.t
            try:
                res = _real_stop_script(sleep=nap, clock=clk)
            except (TypeError, StopIteration) as e:    # an older signature or an endless loop
                res = f"crashed: {type(e).__name__}"
            return res, clk.t - t0, timeouts, naps
        finally:
            _pko._stop_okww_python, _pko.okww_python_pids = real

    # None before this bound existed, so the checks below fail rather than crash.
    _BOUND = getattr(echofarm, "STOP_SCRIPT_SECONDS", None)
    _res, _took, _to, _naps = _stop_run([[4242], [4242], []])
    check("gone on the third look: ''", _res, "")
    check("…after two one-second naps", _naps, [1, 1])
    _res, _took, _to, _naps = _stop_run([[4242]] * 100)
    check("still listed at the end: 'running'", _res, "running")
    check("…within the step's time", _BOUND is not None and _took <= _BOUND + 1, True)
    _res, _took, _to, _naps = _stop_run([None, []])
    check("unreadable once, then empty: '' (asked again, not given up)", _res, "")
    check("…asked again at once, no nap", _naps, [])
    _res, _took, _to, _naps = _stop_run([None, None, []])
    check("unreadable twice in a row: 'unreadable'", _res, "unreadable")
    _res, _took, _to, _naps = _stop_run(["slow", "slow", []], pwsh_secs=0.5)
    check("a hung pwsh: 'unreadable'", _res, "unreadable")
    check("…and the step still ends in about STOP_SCRIPT_SECONDS",
          _BOUND is not None and _took <= _BOUND + 2, True)
    check("…every pwsh call got only the time left, never its 60 s guard",
          _BOUND is not None and all(x is not None and x <= _BOUND for x in _to), True)

    class _Warn(_lg.Handler):
        def __init__(self):
            super().__init__(_lg.WARNING)
            self.msgs = []

        def emit(self, record):
            self.msgs.append(record.getMessage())

    for _why, _says, _want in (("running", "停不掉", ["script", "stop", 1]),
                               ("unreadable", "查了两次都查不到", ["script", "stop", 1]),
                               ("", None, ["script", 1])):
        _c3 = fresh()
        echofarm.start(_c3, 1, "08:30", "天傀劫煞", now=NOW)
        _r3 = echofarm.current(_c3.state_dir)
        _r3["started"] = "2026-09-09 04:00"
        echofarm._store(_c3.state_dir).set("queues", "echo_farm", _r3)
        _wb._okww_log = lambda: _logfile
        echofarm.stop_okww_script = lambda w=_why: (launched.append("script"), w)[1]
        _h = _Warn()
        echofarm.log.addHandler(_h)
        try:
            _b3 = len(launched)
            echofarm.tick(_c3, datetime(2026, 9, 9, 4, 36, tzinfo=SERVER_TZ))
            check(f"first relaunch, old script {_why or 'gone'}: {_want}", launched[_b3:], _want)
            check(f"…the warning says why ({_says})",
                  any("连游戏一起关了" in m and _says in m for m in _h.msgs) if _says
                  else not any("连游戏一起关了" in m for m in _h.msgs), True)
        finally:
            echofarm.log.removeHandler(_h)
            echofarm.stop_okww_script = lambda: launched.append("script") or ""
            _wb._okww_log = _real_log

    print("\n[收工那一步本身：先停计划任务，再把 OK-WW 的进程停干净]")
    # The real function, not the stub - it is what actually ends the run on the machine.
    import subprocess as _sp
    import ark_relay.features.preupdate as _pk
    _ran, _quiesced = [], []
    _real_run, _real_q = _sp.run, _pk._okww_quiesce
    class _Done:
        returncode = 0
        stdout = b""
        stderr = b""

    _sp.run = lambda *a, **k: (_ran.append(list(a[0]) if a else []), _Done())[1]
    _pk._okww_quiesce = lambda *a, **k: _quiesced.append(1)
    try:
        # The stub above replaced the module attribute; reload to get the real one back.
        import importlib
        _mod = importlib.reload(sys.modules["ark_relay.features.echofarm"])
        _mod.STOP_BAT = str(tmpdir() / "ark-okww-stop.bat")   # never the repo cwd
        _mod.stop_okww()
        check("结束了计划任务", any("schtasks" in c and "/end" in c for c in _ran), True)
        check("任务名对得上", any(_mod.TASK_NAME in c for c in _ran), True)
        check("把 OK-WW 的进程也停了", _quiesced, [1])
        check("游戏也关干净了就不多话", _mod.stop_okww(sleep=lambda _s: None), "")

        print("\n[游戏关不掉就必须说出来，不许报「已收工」]")
        _mod.game_alive = lambda timeout=None: ["Client-Win64-Shipping.exe"]
        _ran.clear()
        _note = _mod.stop_okww(sleep=lambda _s: None)
        check("话里点名还活着的进程", "Client-Win64-Shipping.exe" in _note, True)
        check("话里说了没关掉、已交给我们这边去关", ("没关掉" in _note, "已交给我们这边去关" in _note), (True, True))
        check("从交互桌面那边补了一刀", any(_mod.STOP_TASK in c for c in _ran), True)

        # docs/SILENT-FAILURES-AUDIT.md echofarm.py:250 - a process list that cannot be
        # read is not a clean desktop.
        print("\n[tasklist fails: never read as 「the game is closed」]")
        _mod = importlib.reload(sys.modules["ark_relay.features.echofarm"])
        _mod.STOP_BAT = str(tmpdir() / "ark-okww-stop.bat")
        _sp.run = lambda *a, **k: (_ for _ in ()).throw(OSError("tasklist missing"))
        left = _mod.game_alive()
        check("not empty", bool(left), True)
        check("names no real process (nothing gets killed by that name)",
              any(x in _mod.GAME_PROCS for x in left), False)
        _sp.run = lambda *a, **k: (_ran.append(list(a[0]) if a else []), _Done())[1] \
            if a and a[0] and a[0][0] != "tasklist" else (_ for _ in ()).throw(OSError("tasklist missing"))
        _note = _mod.stop_okww(sleep=lambda _s: None)
        check("stop does not say 收工 cleanly", _note != "" and "程序列表" in _note, True)

        print("\n[OK-WW's own pythonw counts as still up]")
        class _Py(_Done):
            stdout = b'[{"ProcessId": 777}]'
        _ran.clear()
        _sp.run = lambda *a, **k: (_ran.append(list(a[0]) if a else []),
                                   _Py() if a and any("pythonw.exe" in str(x) for x in a[0]) else _Done())[1]
        check("a live OK-WW script is named, in plain words", _mod.game_alive(), ["OK-WW 脚本"])
        _note = _mod.stop_okww(sleep=lambda _s: None)
        check("stop does not report clean while it lives", "OK-WW 脚本" in _note, True)
        check("…without the program file or its number", ("pythonw" in _note, "777" in _note, "编号" in _note),
              (False, False, False))
        class _Py2(_Done):
            stdout = b'[{"ProcessId": 777}, {"ProcessId": 778}]'
        _sp.run = lambda *a, **k: (_ran.append(list(a[0]) if a else []),
                                   _Py2() if a and any("pythonw.exe" in str(x) for x in a[0]) else _Done())[1]
        check("two of them are still named once", _mod.game_alive(), ["OK-WW 脚本"])
        check("the desktop kill takes it by PID",
              "taskkill /F /PID 777" in Path(_mod.STOP_BAT).read_text(encoding="utf-8"), True)
        _sp.run = lambda *a, **k: (_ for _ in ()).throw(OSError("no pwsh")) \
            if a and any("pythonw.exe" in str(x) for x in a[0]) else _Done()
        check("python list unreadable: not read as gone", _mod.game_alive(), [_mod.UNREADABLE_SCRIPT])
        _sp.run = lambda *a, **k: _Done()
        check("nothing up: clean", _mod.game_alive(), [])
    finally:
        _sp.run, _pk._okww_quiesce = _real_run, _real_q

    print("\n[the wrap-up stop is bounded in time, and out of time it never says clean]")
    _mod = importlib.reload(sys.modules["ark_relay.features.echofarm"])
    _mod.STOP_BAT = str(tmpdir() / "ark-okww-stop.bat")
    _BOUND2 = getattr(_mod, "STOP_OKWW_SECONDS", None)   # None before the bound: checks fail, not crash

    def _wrapup_stop(alive, query_secs):
        """The real stop_okww with fake time: `alive` gives each look's answer, and every
    query runs `query_secs`, or to its timeout when None (a hung pwsh).
    (note, seconds taken, timeouts handed out, looks)."""
        clk = _Clock()
        handed, looks = [], []

        def spend(timeout):
            handed.append(timeout)
            clk.t += timeout if query_secs is None else min(query_secs, timeout or 60)

        def quiesce(sleep=None, launcher_root=None, left=None):
            spend(left() if left else 60)
            spend(left() if left else 60)
            clk.t += 2

        def alive_now(timeout=None):
            spend(timeout if timeout is not None else 60)
            looks.append(1)
            return alive(len(looks))

        def pids(timeout=None):
            spend(timeout if timeout is not None else 60)
            return None if query_secs is None else [4242]

        def nap(n):
            clk.t += n
        real = (_sp.run, _pk._okww_quiesce, _pk.okww_python_pids, _mod.game_alive, _mod._kill_on_desktop)
        _sp.run = lambda *a, **k: _Done()
        _pk._okww_quiesce, _pk.okww_python_pids = quiesce, pids
        _mod.game_alive, _mod._kill_on_desktop = alive_now, (lambda pids=(): None)
        try:
            t0 = clk.t
            try:
                note = _mod.stop_okww(sleep=nap, clock=clk)
            except TypeError as e:          # an older signature
                note = f"crashed: {type(e).__name__}"
            return note, clk.t - t0, handed, looks
        finally:
            (_sp.run, _pk._okww_quiesce, _pk.okww_python_pids, _mod.game_alive, _mod._kill_on_desktop) = real

    _note, _took, _handed, _looks = _wrapup_stop(lambda n: [_mod.UNREADABLE_SCRIPT], None)
    # Past the bound each remaining call still gets its one-second minimum: two in the
    # quiesce, the look, the PID query, plus the quiesce's 2 s pause.
    check("every query hangs: the stop still ends near its bound (at most 6 s past)",
          _BOUND2 is not None and _took <= _BOUND2 + 6, True)
    check("…instead of the ten minutes it could take", _took < 120, True)
    check("…every query got only the time left", _BOUND2 is not None and all(x <= _BOUND2 for x in _handed), True)
    check("…and the line does not say clean", (_note != "", "关干净" in _note, "已交给我们这边去关" in _note), (True, True, True))
    check("…it names what was last seen", _mod.UNREADABLE_SCRIPT in _note, True)
    _note, _took, _handed, _looks = _wrapup_stop(lambda n: ["Client-Win64-Shipping.exe"] if n < 3 else [], 0.5)
    check("a normal stop: clean on the third look", (_note, len(_looks)), ("", 3))
    _note, _took, _handed, _looks = _wrapup_stop(lambda n: ["Client-Win64-Shipping.exe"], 0.5)
    check("a game that stays up with quick queries: ten looks after the first, as before", len(_looks), 11)
    check("…the old 「没关掉」 line naming it", ("没关掉" in _note, "Client-Win64-Shipping.exe" in _note), (True, True))
    check("…inside the bound", _BOUND2 is not None and _took <= _BOUND2, True)


def _part_echo_farm_stop_and_backlog():
    """The red button ends an echo farm, and a farm order that waited out its deadline is refused.
    """
    import json
    import os
    import types
    from datetime import datetime, timedelta

    _stub_win32("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom")

    from ark_relay.features import commands
    from ark_relay.features import echofarm
    from ark_relay.features import redbutton  # estop() reads its stop steps here
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import phone as phone_channel

    ORIGINAL = {"Teleport to Boss": "Weekly Challenge", "Which Boss Challenge to Teleport": 1,
                "Repeat Farm Count": 3}

    def fresh():
        root = tmpdir()
        d = root.joinpath(*echofarm._WORKING, "configs")
        d.mkdir(parents=True)
        (d / "FarmEchoTask.json").write_text(json.dumps(ORIGINAL), encoding="utf-8")
        return _Cfg(root)

    launched = []
    echofarm._launch = lambda: (launched.append("launch"), (True, ""))[1]
    echofarm.stop_okww = lambda: launched.append("stop")
    echofarm.NO_CLAIM = str(tmpdir() / "no-claim")

    def at(d, hh, mm):
        return datetime(2026, 10, d, hh, mm, tzinfo=SERVER_TZ)

    print("\n[关机时 22:00 按「刷到 08:30」、第二天 08:45 开机才收到：不开刷]")
    c, launched[:] = fresh(), []
    ok, msg = echofarm.start(c, 1, "08:30", "天傀劫煞", now=at(6, 8, 45), sent=at(5, 22, 0))
    check("拒收", ok, False)
    check("没开 OK-WW", launched, [])
    check("没留刷声骸记录", echofarm.current(c.state_dir), {})
    check("配置没动", json.loads(echofarm._cfg_path(c.okww_dir).read_text(encoding="utf-8")), ORIGINAL)
    check("说了是几点发的、已经过了", "10-05 22:00 发的" in msg and "已经过了 08:30" in msg)

    print("\n[同一条、08:00 开机就收到：照常刷到当天 08:30，不顺延到后天]")
    c, launched[:] = fresh(), []
    ok, msg = echofarm.start(c, 1, "08:30", "天傀劫煞", now=at(6, 8, 0), sent=at(5, 22, 0))
    check("开刷了", ok)
    check("刷到 10-06 08:30", echofarm.current(c.state_dir).get("until"), "2026-10-06 08:30")

    print("\n[在线按的（几秒前发出）：和以前一样]")
    c, launched[:] = fresh(), []
    ok, _ = echofarm.start(c, 1, "21:00", "天傀劫煞", now=at(5, 20, 0), sent=at(5, 20, 0) - timedelta(seconds=3))
    check("开刷了", ok)
    check("刷到当天 21:00", echofarm.current(c.state_dir).get("until"), "2026-10-05 21:00")
    c, launched[:] = fresh(), []
    ok, _ = echofarm.start(c, 1, "08:30", "天傀劫煞", now=at(5, 20, 0))
    check("不知道发出时刻的：按现在算，顺延到明天", (ok, echofarm.current(c.state_dir).get("until")),
          (True, "2026-10-06 08:30"))

    print("\n[指令带来的发出时刻（unix 秒）交给 echofarm.start]")
    got = {}
    real_start = echofarm.start
    echofarm.start = lambda cfg, boss, until, name, sent=None, **kw: (got.update(sent=sent), (True, ""))[1]
    commands.apply_command({"action": "echo_farm", "confirmed": True, "boss": 1, "until": "08:30",
                            "sent": int(at(5, 22, 0).timestamp())})
    check("换成了机器时区的时刻", got.get("sent"), at(5, 22, 0))
    commands.apply_command({"action": "echo_farm", "confirmed": True, "boss": 1, "until": "08:30"})
    check("没带就是 None", got.get("sent"), None)

    print("\n[weekly: true from the App reaches echofarm.start, with a weekly name when none is sent (2026-10-22)]")
    echofarm.start = lambda cfg, boss, until, name, sent=None, weekly=False, **kw: (
        got.update(boss=boss, name=name, weekly=weekly), (True, ""))[1]
    commands.apply_command({"action": "echo_farm", "confirmed": True, "boss": 1, "until": "08:30", "weekly": True})
    check("weekly passed on", got.get("weekly"), True)
    check("default name says weekly, not 讨伐强敌's 1", got.get("name"), "周本第 1 个")
    commands.apply_command({"action": "echo_farm", "confirmed": True, "boss": 1, "until": "08:30"})
    check("no weekly key = overworld", got.get("weekly"), False)
    check("overworld default name from wuwa_boss", got.get("name"), "天傀劫煞")
    commands.apply_command({"action": "echo_farm", "confirmed": True, "boss": 1, "until": "08:30", "weekly": "yes"})
    check("only a real true means weekly", got.get("weekly"), False)
    echofarm.start = real_start

    class Eng:
        def scripts_running(self):
            return False

    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, kw.get("alert", False)))
            return False

    class Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def exception(self, *a, **k): pass

    print("\n[开机读到的 echo_farm：发出时刻按 ntfy 收到的时间带进去，回执失败不报警]")
    bodies = []
    real_apply = commands.apply_command
    commands.apply_command = lambda body: (bodies.append(dict(body)), (False, "过期了"))[1]
    notes = Notes()
    fn = phone_channel._make_phone_cmd(Eng(), notes, Log(), types.SimpleNamespace(watch=lambda: None),
                                     lambda *_: None, tmpdir())
    fn({"action": "echo_farm", "boss": 1, "until": "08:30",
        "_meta": {"sent": 1759672800, "ntfy_time": 1759672805, "via": "backlog"}})
    fn({"action": "echo_farm", "boss": 1, "until": "08:30", "_meta": {"sent": 1759672800, "via": "backlog"}})
    fn({"action": "set_stage", "value": "1-7", "_meta": {"sent": 1759672800, "ntfy_time": 1759672805}})
    commands.apply_command = real_apply
    check("ntfy 的时间优先（手机钟可能快几分钟）", bodies[0].get("sent"), 1759672805)
    check("没有 ntfy 时间就用手机的", bodies[1].get("sent"), 1759672800)
    check("别的指令不加这个字段", "sent" in bodies[2], False)
    check("失败回执报群（每一条都带 alert=True）", [a for _, a in notes.sent], [True, True, True])

    print("\n[刷声骸进行中按「停止一切」：刷声骸一起结束，tick 不再把它开起来]")
    c, launched[:] = fresh(), []
    os.environ["ARK_OKWW_DIR"] = str(c.okww_dir)
    echofarm.start(c, 1, "23:00", "天傀劫煞", now=at(5, 20, 0))
    redbutton._estop_stop_via_mas = lambda: ["早班"]
    redbutton._estop_kill = lambda: None
    redbutton._estop_alive = lambda: []
    redbutton._estop_live_tasks = lambda: []
    launched[:] = []
    ok, msg = commands.estop(sleep=lambda n: None, state_dir=c.state_dir)
    check("说停了", ok)
    check("回执写了刷声骸也停了", "刷声骸也停了：刷天傀劫煞（等级没读到）结束" in msg)
    check("刷声骸记录没了", echofarm.current(c.state_dir), {})
    check("配置还原了", json.loads(echofarm._cfg_path(c.okww_dir).read_text(encoding="utf-8")), ORIGINAL)
    check("之后的 tick 不再开 OK-WW", (echofarm.tick(c, now=at(5, 20, 30)), launched), ("", ["stop"]))

    print("\n[没在刷声骸：回执和以前一样]")
    ok, msg = commands.estop(sleep=lambda n: None, state_dir=c.state_dir)
    check("没提刷声骸", (ok, "刷声骸" in msg), (True, False))

    print("\n[结束刷声骸出错：不说「已停一切」]")
    real_finish = echofarm.finish
    echofarm.finish = lambda cfg, why: (_ for _ in ()).throw(OSError("磁盘满"))
    ok, msg = commands.estop(sleep=lambda n: None, state_dir=c.state_dir)
    echofarm.finish = real_finish
    check("算没停干净", ok, False)
    check("说了刷声骸没结束、怎么办", "刷声骸没结束" in msg and "结束刷声骸" in msg)

    print("\n[手动停刷声骸 / 红按钮：收工出问题报群，干净收工不报群]")
    from ark_relay.core import texts

    def troubles(n):
        return [a for t, a in n.sent if t == texts.ECHO_FARM_TROUBLE]

    def farm_then(press, game_left):
        c = fresh()
        os.environ.update(ARK_OKWW_DIR=str(c.okww_dir), ARK_STATE_DIR=str(c.state_dir))
        echofarm.stop_okww = lambda: launched.append("stop")
        echofarm.start(c, 1, "23:00", "天傀劫煞", now=at(5, 20, 0))
        if game_left:
            echofarm.stop_okww = lambda: "；**游戏还开着**"
        n = Notes()
        phone_channel._make_phone_cmd(Eng(), n, Log(), types.SimpleNamespace(watch=lambda: None),
                                      lambda *_: None, c.state_dir)(press)
        echofarm.stop_okww = lambda: launched.append("stop")
        check("刷声骸记录没了", echofarm.current(c.state_dir), {})
        return n

    n = farm_then({"action": "echo_farm_stop", "confirmed": True}, game_left=True)
    check("手机停、游戏还开着：报群一条", troubles(n), [True])
    n = farm_then({"action": "echo_farm_stop", "confirmed": True}, game_left=False)
    check("手机停、干净收工：不报群", troubles(n), [])
    # The red button's real estop waits between its steps; the stop steps are stubbed
    # above, so the waits are skipped too (phone_channel calls commands.estop).
    _real_estop = commands.estop
    commands.estop = lambda sleep=None, state_dir=None: _real_estop(sleep=lambda _n: None, state_dir=state_dir)
    n = farm_then({"action": "estop"}, game_left=True)
    check("红按钮、游戏还开着：报群一条", troubles(n), [True])
    n = farm_then({"action": "estop"}, game_left=False)
    check("红按钮、干净收工：不报群", troubles(n), [])


if __name__ == "__main__":
    sys.exit(run_parts([_part_okww_alive_cache, _part_okww_drift, _part_okww_error_event, _part_okww_error_reason, _part_okww_exit_race, _part_okww_failed_reason, _part_okww_i18n, _part_okww_landed, _part_okww_names_not_numbers, _part_okww_python_filter, _part_okww_quiesce_order, _part_okww_report, _part_okww_structured, _part_okww_battle_pass, _part_okww_battle_pass_claim, _part_okww_claim_readback, _part_okww_daily_chests, _part_okww_farm_hook, _part_okww_merge_step, _part_okww_plan_bits, _part_okww_revive_and_retry, _part_okww_stamina_end, _part_okww_stamina_nest_verdict, _part_okww_upstream_no_farm, _part_okww_nest_capture, _part_okww_nest_expected, _part_okww_nest_fought_then_full, _part_okww_nest_names, _part_okww_nest_travel_retry, _part_okww_nest_v373, _part_okww_no_challenge_window, _part_okww_weekly_boss_step, _part_okww_weekly_entry_paths, _part_okww_weekly_spend, _part_okww_overlay_main, _part_okww_overlay_faults, _part_okww_overlay_install_guard, _part_okww_overlay_pending, _part_okww_overlay_param_start, _part_okww_overlay_copies, _part_echo_farm_main, _part_echo_farm_stop_and_backlog]))
