"""OK-WW's pre-update, and its Python packages checked after it (ledger #115).

One part per former file, each run on its own (tests/_parts.py): test_preupdate_okww.py, test_okww_deps_1108.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tmp  # loaded before the parts: its atexit cleanup and env default stay
from _parts import run_parts

_BEFORE_THE_PARTS = (_tmp,)


def _part_main():
    """OK-WW's pre-update must not start 鸣潮, and must put the switch back.

OK-WW updates through pyappify from a CNB git mirror, and that only happens
when ok-ww.exe - the pyappify shell - is the thing launched. But ok-ww.exe
honours "Auto Start Game When App Starts", which is on for unattended running.
Launching it at boot without disarming that would start the game itself, which
is the same hazard MAA's RunDirectly and MaaEnd's autostart already taught us.

    Formerly test_preupdate_okww.py.
    """
    import ast
    import json
    import os
    import sys
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.preupdate import preupdate
    from ark_relay.features.preupdate import preupdate_okww

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    def make(root: Path, autostart: bool) -> Path:
        d = root / "okww"
        cfgdir = d / "data" / "apps" / "ok-ww" / "working" / "configs"
        cfgdir.mkdir(parents=True, exist_ok=True)
        (cfgdir / "Basic Options.json").write_text(json.dumps({
            "Auto Start Game When App Starts": autostart,
            "Mute Game while in Background": True,
            "Use DirectML": "Yes",
        }, ensure_ascii=False), encoding="utf-8")
        (d / "data" / "apps" / "ok-ww").mkdir(parents=True, exist_ok=True)
        (d / "data" / "apps" / "ok-ww" / "app.json").write_text(json.dumps({
            "current_version": "v3.6.4", "update_state": "idle", "update_error": None,
        }), encoding="utf-8")
        return d


    def basic(d: Path) -> dict:
        return json.loads((d / "data" / "apps" / "ok-ww" / "working" / "configs"
                           / "Basic Options.json").read_text(encoding="utf-8"))


    def main(root: Path) -> int:
        d = make(root, autostart=True)

        was = preupdate_okww._okww_autostart(d, False)
        check("读到原值 True", was, True)
        check("已关掉自动开游戏", basic(d)["Auto Start Game When App Starts"], False)
        check("其他设置没被动到", basic(d)["Mute Game while in Background"], True)
        check("非布尔项也完好", basic(d)["Use DirectML"], "Yes")
        preupdate_okww._okww_autostart(d, True)
        check("能原样放回去", basic(d)["Auto Start Game When App Starts"], True)

        check("读得到 app.json 状态", preupdate_okww._okww_state(d)[:3],
              ("v3.6.4", "idle", ""))
        # 第四项是判断"到底检查过没有"的唯一依据，见 _okww_state 的注释。
        check("状态里带得出可用版本列表",
              isinstance(preupdate_okww._okww_state(d)[3], tuple), True)

        bad = root / "bad"
        (bad / "data" / "apps" / "ok-ww" / "working" / "configs").mkdir(parents=True)
        check("配置读不懂时返回 None", preupdate_okww._okww_autostart(bad, False), None)

        # No ok-ww.exe -> do nothing, and never leave the switch flipped.
        check("找不到 ok-ww.exe 时什么都不做", preupdate.run_okww(d, budget_s=1), "")
        check("跳过后开关仍是原值",
              basic(d)["Auto Start Game When App Starts"], True)
        check("目录为 None 时也安全", preupdate.run_okww(None), "")

        src = "".join(q.read_text(encoding="utf-8") for q in sorted((Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "preupdate").glob("preupdate*.py")))  # 预更新拆成了五个文件，一起看
        # 2026-08-25：控制台令牌拿不到时退回 session 0，OK-WW 的更新流程根本不跑，
        # 而未变的版本文件被读成"无需更新"——那天 v3.6.5 已经发布十四小时。
        # 拿不到桌面就必须拒绝启动，并把这件事报上去。
        check("拒绝在 session 0 启动",
              "_spawn_interactive(exe, root, require_console=True, minimized=True)" in src, True)
        check("拿不到控制台会话要上报",
              "拿不到控制台会话" in src, True)
        check("安静不等于没有更新",
              "无法确认是否检查过更新" in src, True)
        # The shape the user-switches guard accepts: the setter's old value goes back
        # through the same setter inside a `finally` of run_okww.
        fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run_okww")
        restores = [c for t in ast.walk(fn) if isinstance(t, ast.Try) for st in t.finalbody for c in ast.walk(st)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_okww_autostart"
                    and any(isinstance(a, ast.Name) and a.id == "was" for a in c.args)]
        check("在 finally 里还原开关", len({id(c) for c in restores}), 1)
        # 2026-08-24: flipping the JSON was not enough - a leftover `ok web` held the
        # settings in memory and wrote them back, so ok-ww.exe read True and started
        # 鸣潮 during a check that was meant to open nothing.
        check("改配置前先停掉在跑的实例", "_okww_quiesce(" in src
              and src.index("_okww_quiesce(", src.index("def run_okww"))
              < src.index("was = _okww_autostart"), True)
        # 数的是**真正的调用点**，不是字面量出现次数。2026-09-08 栽过一次：
        # 给 _okww_quiesce 加了个可注入的 sleep 参数（为了测试不真等两秒），
        # 定义那一行就不再长得像 `_okww_quiesce()`，字面量计数少了一个，测试当场变红——
        # 而调用点一个没少。按字面量数等于让断言依赖签名的写法。
        calls = sum(1 for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_okww_quiesce")
        check("收尾也清一次，不留游戏在后台", calls >= 2, True)

        # 2026-09-06: the pre-update judged 「无需更新」 three seconds after launch, while
        # OK-WW only checks for updates 30 s after its window shows (moved here from the
        # removed test_okww_patch_on_update.py, 2026-10-12).
        check("the minimum wait covers OK-WW's 30 s update check", preupdate.OKWW_MIN_WAIT_SECONDS >= 40, True)
        pre_src = "".join(q.read_text(encoding="utf-8") for q in sorted(
            (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "preupdate").glob("preupdate*.py")))
        check("the 「checked」 verdict waits at least that long",
              "clock() - launched >= OKWW_MIN_WAIT_SECONDS" in pre_src, True)

        timeout_mid_download(root)
        baseline_unknown(root)
        newer_listed_not_installed(root)
        stop_and_switch_memo(root)
        print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
        return 0 if not FAILED else 1


    def timeout_mid_download(root: Path) -> None:
        """Out of time while app.json still says downloading: a failure, never 「无需更新」."""
        m = preupdate_okww
        d = make(root / "dl", autostart=True)
        appjson = d / "data" / "apps" / "ok-ww" / "app.json"
        appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "downloading",
                                       "update_error": None, "available_versions": ["v3.7.4", "v3.7.3"]}),
                           encoding="utf-8")
        now = [0.0]
        out = m._okww_await_update(d, 240, "v3.7.3", ("v3.7.3",), m._okww_stamp(d),
                                   sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
        check("超时仍在下载：带回卡住的状态和最后读到的版本列表", out, ("", True, "", "downloading", ("v3.7.4", "v3.7.3")))
        check("等满了预算才算超时", now[0] >= 240, True)

        appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "idle",
                                       "update_error": None}), encoding="utf-8")
        now[0] = 0.0
        out = m._okww_await_update(d, 240, "v3.7.3", (), m._okww_stamp(d) - 10,
                                   sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
        check("空闲且检查过：照旧算查完，不算卡住", out, ("", True, "", "", ()))
        check("至少等过上游那 30 秒检查", now[0] >= m.OKWW_MIN_WAIT_SECONDS, True)

        probs = []
        m._okww_report(probs, 240, "v3.7.3", ("v3.7.4",), "", True, "", "downloading", Path("shot.png"))
        check("超时下载中：记成问题", len(probs), 1)
        check("问题里写了还在下载、没更新完", "还在「downloading」" in probs[0] and "没更新完" in probs[0], True)
        check("问题里明说不是无需更新", "不是「无需更新」" in probs[0], True)
        check("问题里带截图", "shot.png" in probs[0], True)
        probs = []
        m._okww_report(probs, 240, "v3.7.3", ("v3.7.3",), "", True, "", "", None)
        check("真没有新版：不记问题", probs, [])

        os.environ["ARK_STATE_DIR"] = str(root / "state")
        try:
            taken = []
            shot = m._okww_timeout_shot(lambda out: taken.append(out) or True)
            check("截图存进状态目录的 preupdate/", shot is not None and shot.parent == root / "state" / "preupdate", True)
            check("截图就是截下来的那张", taken, [shot])
            check("截不到时返回 None", m._okww_timeout_shot(lambda out: False), None)
            check("截图出错也不抛", m._okww_timeout_shot(lambda out: 1 / 0), None)
        finally:
            os.environ.pop("ARK_STATE_DIR", None)

        # run_okww end to end, with the machine-touching steps recorded instead of run.
        (d / "ok-ww.exe").write_text("", encoding="utf-8")
        saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_okww_quiesce", "_okww_close", "_close",
                                            "_okww_await_update", "_okww_timeout_shot")}
        order = []
        try:
            m._okww_quiesce = lambda *a, **kw: order.append("quiesce")
            m._okww_close = lambda *a, **kw: order.append("closed") or []
            m._close = lambda exe: order.append("close")
            m._okww_timeout_shot = lambda: order.append("shot") or Path("t.png")
            m._okww_await_update = lambda *a, **kw: ("", True, "", "downloading", ())
            m._spawn_interactive = lambda *a, **kw: order.append("spawn") or True
            probs = []
            check("超时下载中：不报已更新", m.run_okww(d, budget_s=240, problems=probs), "")
            check("超时下载中：问题里是没更新完", ["没更新完" in p for p in probs], [True])
            check("先停掉所有实例再启动我们自己的，截图在关之前，关的是我们启动的",
                  order, ["quiesce", "spawn", "shot", "close", "closed"])
            check("开关放回原值", basic(d)["Auto Start Game When App Starts"], True)

            order.clear()
            m._spawn_interactive = lambda *a, **kw: order.append("spawn") or False
            probs = []
            m.run_okww(d, budget_s=240, problems=probs)
            check("没启动成功就不去关 OK-WW", "close" in order, False)

            order.clear()
            m._spawn_interactive = lambda *a, **kw: order.append("spawn") or True
            m._okww_await_update = lambda *a, **kw: ("", True, "", "", ())
            probs = []
            m.run_okww(d, budget_s=240, problems=probs)
            check("没卡住就不截图", "shot" in order, False)

            # Something raises after the launch: OK-WW is still closed, then the switch goes back.
            order.clear()
            saved_set = m._okww_autostart

            def _set(root_, value):
                order.append(f"set {value}")
                return saved_set(root_, value)
            m._okww_autostart = _set
            m._okww_await_update = lambda *a, **kw: 1 / 0
            try:
                m.run_okww(d, budget_s=240, problems=[])
                check("中途出错照样往外抛", False, True)
            except ZeroDivisionError:
                check("中途出错照样往外抛", True, True)
            check("中途出错：先关 OK-WW，再把开关放回原值",
                  order, ["quiesce", "set False", "spawn", "close", "closed", "set True"])
            check("中途出错：开关是原值", basic(d)["Auto Start Game When App Starts"], True)

            # The switch cannot be put back: a WARNING (pushed to the group), naming it.
            import logging
            grabbed = []

            class _Grab(logging.Handler):
                def emit(self, record):
                    grabbed.append((record.levelno, record.getMessage()))
            h = _Grab()
            preupdate_okww.log.addHandler(h)
            calls = []
            # First call turns it off (it was on); the one putting it back fails.
            m._okww_autostart = lambda root_, value: (calls.append(value), True if len(calls) == 1 else None)[1]
            m._okww_await_update = lambda *a, **kw: ("", True, "", "", ())
            try:
                m.run_okww(d, budget_s=240, problems=[])
            finally:
                preupdate_okww.log.removeHandler(h)
                m._okww_autostart = saved_set
            check("改不回去：WARNING，说清是哪个开关",
                  [lv for lv, msg in grabbed if "自动开游戏" in msg and "没能改回" in msg], [logging.WARNING])
        finally:
            for k, v in saved.items():
                setattr(m, k, v)


    def baseline_unknown(root: Path) -> None:
        """app.json unreadable at the pre-launch read: the first version read later is
    not an update (audit row preupdate_okww.py:243 via :392)."""
        print("[baseline version unknown]")
        m = preupdate_okww
        d = make(root / "nobase", autostart=True)
        appjson = d / "data" / "apps" / "ok-ww" / "app.json"
        appjson.write_text(json.dumps({"current_version": "v3.7.4", "update_state": "idle",
                                       "update_error": None}), encoding="utf-8")
        real_await = m._okww_await_update
        now = [0.0]

        def fast_await(*a, **kw):
            now[0] = 0.0
            return real_await(*a, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0], **kw)

        out = fast_await(d, 240, "", (), m._okww_stamp(d) - 10)
        check("baseline unknown: a version read later is not settled as an update", out[0], "")

        (d / "ok-ww.exe").write_text("", encoding="utf-8")
        saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_okww_quiesce", "_okww_close", "_close",
                                            "_okww_await_update", "_okww_state")}
        reads = []
        real_state = m._okww_state
        try:
            m._okww_quiesce = lambda *a, **kw: None
            m._okww_close = lambda *a, **kw: []
            m._close = lambda exe: None
            m._spawn_interactive = lambda *a, **kw: True
            m._okww_await_update = fast_await
            # The pre-launch read fails (OK-WW was rewriting app.json); later reads work.
            m._okww_state = lambda r: (reads.append(1), ("", "", "", ()) if len(reads) == 1 else real_state(r))[1]
            probs = []
            got = m.run_okww(d, budget_s=240, problems=probs)
            check("baseline unknown: not reported as 「OK-WW 已更新」", got, "")
            check("baseline unknown: a problem says the version could not be compared",
                  sum(1 for p_ in probs if "版本号" in p_ and "没法比对" in p_ and "v3.7.4" in p_), 1)
        finally:
            for k, v in saved.items():
                setattr(m, k, v)


    def newer_listed_not_installed(root: Path) -> None:
        """OK-WW lists a newer version during the wait but does not install it: a problem,
    not 「无需更新」. The verdict used to read the list from before the launch, so
    the newer entry seen inside the wait never reached it (audit #10)."""
        print("[newer version listed during the wait, not installed]")
        m = preupdate_okww
        d = make(root / "newer", autostart=True)
        appjson = d / "data" / "apps" / "ok-ww" / "app.json"
        appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "idle",
                                       "update_error": None, "available_versions": ["v3.7.3"]}),
                           encoding="utf-8")
        (d / "ok-ww.exe").write_text("", encoding="utf-8")
        real_await = m._okww_await_update
        now = [0.0]

        def tick(s):
            # OK-WW's check: the list gains v3.7.4, the installed version stays v3.7.3.
            if now[0] == 0.0:
                appjson.write_text(json.dumps({"current_version": "v3.7.3", "update_state": "idle",
                                               "update_error": None,
                                               "available_versions": ["v3.7.4", "v3.7.3"]}),
                                   encoding="utf-8")
            now[0] += s

        def fast_await(*a, **kw):
            now[0] = 0.0
            return real_await(*a, sleep=tick, clock=lambda: now[0], **kw)

        saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_okww_quiesce", "_okww_close", "_close",
                                            "_okww_await_update")}
        try:
            m._okww_quiesce = lambda *a, **kw: None
            m._okww_close = lambda *a, **kw: []
            m._close = lambda exe: None
            m._spawn_interactive = lambda *a, **kw: True
            m._okww_await_update = fast_await
            probs = []
            got = m.run_okww(d, budget_s=240, problems=probs)
        finally:
            for k, v in saved.items():
                setattr(m, k, v)
        check("newer listed, not installed: not reported as updated", got, "")
        check("newer listed, not installed: a problem naming v3.7.4",
              [p_ for p_ in probs if "查到有 v3.7.4" in p_ and "没装上" in p_ and "v3.7.3" in p_] != [], True)
        probs = []
        m._okww_report(probs, 240, "v3.7.3", ("v3.7.4", "v3.7.3"), "", True, "", "", None)
        check("the verdict reads the list it is given (the latest one)", len(probs), 1)


    def stop_and_switch_memo(root: Path) -> None:
        """2026-10-16 02:35: a deploy rollback stopped the relay during the OK-WW wait, which
    could not hear the stop; the 15 s hard exit killed the process before the `finally`
    put the auto-start switch back, and the next run "restored" it to off. The wait now
    ends at the poll after a stop, a stopping relay launches nothing, and the switch's
    value is kept in state until it is back (restored on the next run or boot)."""
        print("[stop during the OK-WW pre-update; the switch survives a hard exit]")
        m = preupdate_okww

        def stop_after(n):
            asked = [0]

            def stopping():
                asked[0] += 1
                return asked[0] > n
            return stopping

        # (a) the wait itself: a stop at poll 2 ends it there, before the 45 s minimum.
        d = make(root / "stop", autostart=True)
        now = [0.0]
        out = m._okww_await_update(d, 240, "v3.6.4", (), m._okww_stamp(d),
                                   sleep=lambda s_: now.__setitem__(0, now[0] + s_), clock=lambda: now[0],
                                   stopping=stop_after(1))
        check("(a) stop at poll 2: ends after 6 s, no error, not stuck", (now[0], out[2], out[3]), (6.0, "", ""))

        (d / "ok-ww.exe").write_text("", encoding="utf-8")
        state = root / "stop-state"
        memo = state / m.AUTOSTART_MEMO
        real_await = m._okww_await_update
        saved = {k: getattr(m, k) for k in ("_spawn_interactive", "_okww_quiesce", "_okww_close", "_close",
                                            "_okww_await_update", "_okww_timeout_shot")}
        order = []
        try:
            m._okww_quiesce = lambda *a, **kw: order.append("quiesce")
            m._okww_close = lambda *a, **kw: order.append("closed") or []
            m._close = lambda exe: order.append("close")
            m._okww_timeout_shot = lambda: order.append("shot") or Path("t.png")
            m._spawn_interactive = lambda *a, **kw: order.append("spawn") or True
            seen = {}

            def fast_await(*a, **kw):
                # What a hard exit right now would leave behind: switch off, record says on.
                seen["switch"] = basic(d)["Auto Start Game When App Starts"]
                seen["memo"] = json.loads(memo.read_text(encoding="utf-8"))["was"] if memo.exists() else None
                now[0] = 0.0
                return real_await(*a, sleep=lambda s_: now.__setitem__(0, now[0] + s_), clock=lambda: now[0], **kw)
            m._okww_await_update = fast_await

            # (b) stop mid-wait: closed, switch back on, no note, no screenshot, record gone.
            probs = []
            # stopping() is asked on entry, after the quiesce, then at each poll: the 4th call is poll 2.
            got = m.run_okww(d, budget_s=240, problems=probs, state_dir=state, stopping=stop_after(3))
            check("(b) stop mid-wait: no verdict, no note", (got, probs), ("", []))
            check("(b) stop mid-wait: ends at the 2nd poll (6 s), then closes OK-WW",
                  (now[0], order), (6.0, ["quiesce", "spawn", "close", "quiesce"]))
            check("(b) the switch is back on", basic(d)["Auto Start Game When App Starts"], True)
            check("(b) during the wait the record held the original value", (seen["switch"], seen["memo"]), (False, True))
            check("(b) record removed once the switch is back", memo.exists(), False)

            # Stop before anything: nothing launched, nothing touched.
            order.clear()
            got = m.run_okww(d, budget_s=240, problems=probs, state_dir=state, stopping=lambda: True)
            check("stopping already: no quiesce, no launch", (got, order, probs), ("", [], []))

            # Stop during the quiesce (between the AUTO-MAS item and OK-WW): no switch flip, no launch.
            order.clear()
            flag = []
            m._okww_quiesce = lambda *a, **kw: order.append("quiesce") or flag.append(1)
            m._okww_close = lambda *a, **kw: order.append("closed") or []
            got = m.run_okww(d, budget_s=240, problems=probs, state_dir=state, stopping=lambda: bool(flag))
            check("stop during the quiesce: OK-WW not launched", (got, order, probs), ("", ["quiesce"], []))
            check("stop during the quiesce: switch untouched, no record", (basic(d)["Auto Start Game When App Starts"],
                                                                           memo.exists()), (True, False))
            m._okww_quiesce = lambda *a, **kw: order.append("quiesce")
            m._okww_close = lambda *a, **kw: order.append("closed") or []

            # (c) a hard exit left the switch off and the record on: the next run puts back "on".
            cfg = d / "data" / "apps" / "ok-ww" / "working" / "configs" / "Basic Options.json"
            data = basic(d)
            data["Auto Start Game When App Starts"] = False
            cfg.write_text(json.dumps(data), encoding="utf-8")
            state.mkdir(parents=True, exist_ok=True)
            memo.write_text(json.dumps({"was": True}), encoding="utf-8")
            m._okww_await_update = lambda *a, **kw: ("", True, "", "", ())
            order.clear()
            m.run_okww(d, budget_s=240, problems=[], state_dir=state, stopping=lambda: False)
            check("(c) next run: the switch goes back to the recorded on, not the off it found",
                  (basic(d)["Auto Start Game When App Starts"], memo.exists()), (True, False))

            # (d) audit 11-08 A-22: OK-WW does not close for real after the run. The switch still
            # goes back, but the record stays: a slow ok-ww.exe can write the switch off again on
            # its way out, and the next boot puts it back while nothing runs.
            m._okww_close = lambda *a, **kw: order.append("closed") or ["ok-ww.exe"]
            order.clear()
            m.run_okww(d, budget_s=240, problems=[], state_dir=state, stopping=lambda: False)
            check("(d) not closed for real: the switch goes back anyway, the record stays",
                  (order[-1], basic(d)["Auto Start Game When App Starts"], memo.exists()), ("closed", True, True))
            check("(d) the next boot finds the switch as recorded: record dropped, nothing said",
                  (m.restore_autostart_leftover(d, state, pids=lambda: []), memo.exists()), ("", False))
            data = basic(d)
            data["Auto Start Game When App Starts"] = False          # ok-ww.exe wrote it off on its way out
            cfg.write_text(json.dumps(data), encoding="utf-8")
            memo.write_text(json.dumps({"was": True}), encoding="utf-8")
            line = m.restore_autostart_leftover(d, state, pids=lambda: [])
            check("(d) ……or finds it written off again: put back on, said",
                  (basic(d)["Auto Start Game When App Starts"], memo.exists(), "放回" in line), (True, False, True))
            m._okww_close = lambda *a, **kw: order.append("closed") or []
        finally:
            for k, v in saved.items():
                setattr(m, k, v)

        # (c) at boot, pre-update or not: restored only while no OK-WW python runs.
        data = basic(d)
        data["Auto Start Game When App Starts"] = False
        (d / "data" / "apps" / "ok-ww" / "working" / "configs" / "Basic Options.json").write_text(
            json.dumps(data), encoding="utf-8")
        memo.write_text(json.dumps({"was": True}), encoding="utf-8")
        check("boot, OK-WW running: left alone", (m.restore_autostart_leftover(d, state, pids=lambda: [4242]),
                                                  basic(d)["Auto Start Game When App Starts"], memo.exists()),
              ("", False, True))
        check("boot, process list unreadable: left alone", (m.restore_autostart_leftover(d, state, pids=lambda: None),
                                                            memo.exists()), ("", True))
        line = m.restore_autostart_leftover(d, state, pids=lambda: [])
        check("boot, nothing running: put back on, record removed",
              (basic(d)["Auto Start Game When App Starts"], memo.exists(), "放回" in line), (True, False, True))
        check("boot, no record: nothing to do, no process query",
              m.restore_autostart_leftover(d, state, pids=lambda: 1 / 0), "")
        from ark_relay.core import texts
        check("the boot line is plain words", texts.plain(line), [])


    if __name__ == "__main__":
        with tempfile.TemporaryDirectory() as tmp:
            raise SystemExit(main(Path(tmp)))


def _part_okww_deps():
    """OK-WW's own Python packages are checked after the pre-update (ledger #115; dispatch
relay-opt-round3-1108 O-01; preupdate_okww.ensure_okww_deps).

10-24 OK-WW updated itself to v3.7.11-beta.1, whose ok/core/plugins.py imports `packaging`;
its bundled Python had none and the morning run crashed at start three times. Pinned here,
with subprocess faked (no Windows, no pip):

* no OK-WW python on disk: nothing, no note;
* everything imports: nothing to do, no note, no install;
* requirements.txt read to the name (`onnxocr-ppocrv5>=0.0.20`, extras, markers);
* `packaging` missing (not in OK-WW's requirements.txt, the #115 case): installed, imported
  again, one WARNING marked recovered (daily report only), no note;
* a dist OK-WW lists that is not installed - found by its dist name (importlib.metadata), not
  by a module name (cv2 / opencv-python): installed as listed (round3b-1108);
* a missing module no listed dist is named after: not installed (pip would fetch whatever
  PyPI holds under a guessed name), a note for the group;
* the probe itself, run by this Mac's python: a dist not installed, a module ok.core.plugins
  imports (`import ok` alone never reaches it), a plugins file this ok-script lacks (no note);
* still missing after pip, or a probe that could not run: a note;
* run_okww calls it after closing OK-WW; worst_case_seconds counts its three guards.

    Formerly test_okww_deps_1108.py.
    """
    import inspect
    import logging
    import subprocess
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    from ark_relay.features.alarm import errwatch
    from ark_relay.features.preupdate import preupdate, preupdate_okww as po
    from ark_relay.features.preupdate.preupdate_common import PWSH_GUARD_S

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
        if not ok:
            fails.append(label)


    class Rows(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, bool(getattr(record, errwatch.RECOVERED, False)), record.getMessage()))


    rows = Rows()
    po.log.addHandler(rows)
    po.log.setLevel(logging.DEBUG)
    po.log.propagate = False


    def okww(requirements=None):
        root = tmpdir()
        py = root.joinpath(*po._OKWW_PYTHON)
        py.parent.mkdir(parents=True)
        py.write_text("", encoding="utf-8")
        working = root.joinpath(*po._OKWW_WORKING)
        working.mkdir(parents=True)
        if requirements is not None:
            (working / "requirements.txt").write_text(requirements, encoding="utf-8")
        return root


    class Fake:
        """subprocess.run: each probe prints the next of `probes`; pip answers `pip_rc`."""

        def __init__(self, *probes, pip_rc=0, raise_probe=None):
            self.probes, self.pip_rc, self.raise_probe = list(probes), pip_rc, raise_probe
            self.calls = []

        def __call__(self, args, **kw):
            self.calls.append(list(args))
            if args[1:3] == ["-m", "pip"]:
                return SimpleNamespace(returncode=self.pip_rc, stdout=b"", stderr=b"")
            if self.raise_probe is not None:
                raise self.raise_probe
            out = self.probes.pop(0) if self.probes else ""
            return SimpleNamespace(returncode=0, stdout=out.encode("utf-8"), stderr=b"")

        def pips(self):
            return [c[c.index("install") + 1:] for c in self.calls if c[1:3] == ["-m", "pip"]]


    def run(root, fake):
        rows.rows.clear()
        problems = []
        out = po.ensure_okww_deps(root, problems, run=fake)
        return out, problems, [(lv, r) for lv, r, _ in rows.rows if lv != "INFO"]


    REQ = ("# autogenerated\nok-script[ocr,qt]==3.0.3\n    # via -r\nopencv-python==4.12.0.88\npywin32==311\n"
           "onnxocr-ppocrv5>=0.0.20\n")
    FLAGS = ["--disable-pip-version-check", "--no-input"]
    REAL_REQ = (Path(__file__).resolve().parent / "gamesim" / "upstream" / "okww-v3.7.14-beta.2"
                / "requirements.txt.txt").read_text(encoding="utf-8")

    print("[读 OK-WW 自己的依赖清单：名字到版本号、额外项、环境标记为止]")
    pins = po._okww_pins(okww(REAL_REQ).joinpath(*po._OKWW_WORKING))
    check("装着的 v3.7.14-beta.2 清单：onnxocr-ppocrv5>=0.0.20 的名字不带版本号",
          pins.get("onnxocr-ppocrv5"), "onnxocr-ppocrv5>=0.0.20")
    check("……ok-script[ocr,qt]==2.0.22 去掉额外项当名字", pins.get("ok-script"), "ok-script[ocr,qt]==2.0.22")
    check("……每个 key 都是纯名字", [k for k in pins if any(c in k for c in "=<>!~[ ;")], [])
    marked = po._okww_pins(okww("pywin32==311 ; sys_platform == \"win32\"\n").joinpath(*po._OKWW_WORKING))
    check("带环境标记的：名字对、装的时候不带标记", marked, {"pywin32": "pywin32==311"})

    print("\n[没有 OK-WW 自带的 Python：什么都不做]")
    check("空目录", po.ensure_okww_deps(tmpdir(), [], run=Fake()), "")

    print("\n[都装着、都导入得了：不装、不报]")
    fake = Fake("")
    out, problems, logged = run(okww(REQ), fake)
    check("没补装、没问题、没 WARNING", (out, problems, logged, fake.pips()), ("", [], [], []))
    check("试导入用的是 OK-WW 自己的 python", fake.calls[0][1], "-c")

    print("\n[缺 packaging（#115，OK-WW 清单里没有）：照样补装，核对过，只进日报]")
    fake = Fake("MODULE packaging\n", "")
    out, problems, logged = run(okww(REQ), fake)
    check("装的是 packaging", fake.pips(), [FLAGS + ["packaging"]])
    check("返回补装了什么", out, "OK-WW 缺的 Python 包已补装：packaging")
    check("没有要报群的问题", problems, [])
    check("一条标自己好了的 WARNING", logged, [("WARNING", True)])

    print("\n[清单里的包没装（按包名查，不靠模块名）：按清单写的装回]")
    fake = Fake("DIST opencv-python\nDIST pywin32\nDIST onnxocr-ppocrv5\nMODULE cv2\n", "")
    out, problems, _ = run(okww(REQ), fake)
    check("按清单装 opencv-python、pywin32、onnxocr-ppocrv5（cv2 由 opencv-python 带回）",
          fake.pips(), [FLAGS + ["opencv-python==4.12.0.88", "pywin32==311", "onnxocr-ppocrv5>=0.0.20"]])
    check("装完 cv2 也导入得了：不报「清单里没有」", problems, [])
    check("返回里有它们", "opencv-python" in out and "cv2" in out, True)

    print("\n[缺的模块哪个包都对不上：不装，报出来]")
    fake = Fake("MODULE yaml\n")
    out, problems, logged = run(okww(REQ), fake)
    check("一个包都没装（yaml 不是包名，猜了可能装错）", fake.pips(), [])
    check("一条问题，说了缺什么、为什么没装", [("yaml" in p and "依赖清单里没有" in p) for p in problems], [True])
    check("没有 WARNING", logged, [])

    print("\n[装完还缺：报出来]")
    fake = Fake("MODULE packaging\n", "MODULE packaging\n", pip_rc=1)
    out, problems, logged = run(okww(REQ), fake)
    check("说补装没成、带 pip 结果", [("自动补装没成" in p and "pip 结果 1" in p) for p in problems], [True])
    check("不算补好了", (out, logged), ("", []))

    print("\n[试导入跑不起来：说没能核对]")
    fake = Fake(raise_probe=subprocess.TimeoutExpired("python", PWSH_GUARD_S))
    out, problems, _ = run(okww(REQ), fake)
    check("一条问题：没能核对", [("没能核对" in p) for p in problems], [True])

    print("\n[真跑一次探针（这台 Mac 的 Python）：按包名、按导入都查得出来]")
    w = tmpdir()
    (w / "requirements.txt").write_text("ark-fake-dist>=1\nno-such-dist-for-ark-test==1.0\n", encoding="utf-8")
    # An installed dist without depending on what this python has: its metadata next to the
    # probe (the probe puts '.' first on sys.path, where importlib.metadata looks too).
    (w / "ark_fake_dist-1.0.dist-info").mkdir()
    (w / "ark_fake_dist-1.0.dist-info" / "METADATA").write_text("Metadata-Version: 2.1\nName: ark-fake-dist\nVersion: 1.0\n",
                                                               encoding="utf-8")
    (w / "config.py").write_text("", encoding="utf-8")
    (w / "ok" / "core").mkdir(parents=True)
    (w / "ok" / "__init__.py").write_text("", encoding="utf-8")
    (w / "ok" / "core" / "__init__.py").write_text("", encoding="utf-8")
    (w / "ok" / "core" / "plugins.py").write_text("import no_such_module_for_ark_test\n", encoding="utf-8")
    got = subprocess.run([sys.executable, "-c", po._DEPS_PROBE], cwd=str(w), capture_output=True, timeout=60)
    lines = set(got.stdout.decode("utf-8", "replace").split("\n")) - {""}
    check("清单里没装的包：DIST 按包名报", "DIST no-such-dist-for-ark-test" in lines, True)
    check("装着的（ark-fake-dist）不报", any(x.startswith("DIST ark-fake-dist") for x in lines), False)
    check("ok.core.plugins 里缺的模块：MODULE 报出来（只导入 ok 碰不到它）",
          "MODULE no_such_module_for_ark_test" in lines, True)
    check("config、ok 本身都在：不报", {"MODULE config", "MODULE ok"} & lines, set())
    (w / "ok" / "core" / "plugins.py").unlink()
    got = subprocess.run([sys.executable, "-c", po._DEPS_PROBE], cwd=str(w), capture_output=True, timeout=60)
    check("这一版 ok-script 没有 ok.core.plugins：不算缺包",
          any(x.startswith("MODULE ok") for x in got.stdout.decode("utf-8", "replace").split("\n")), False)

    print("\n[接在预更新里、算进最长时长]")
    src = inspect.getsource(po.run_okww)
    check("run_okww 关掉 OK-WW（核实关干净）之后核对", src.index("still = _okww_close()") < src.index("ensure_okww_deps(root, problems)"), True)
    check("worst_case_seconds 里有它的三次（试导入、pip、再试导入）",
          "+ 3 * PWSH_GUARD_S" in inspect.getsource(preupdate.worst_case_seconds), True)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_okww_deps]))
