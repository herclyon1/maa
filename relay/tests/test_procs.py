"""Processes and the host: the app host covers the service, the e-stop verifies, the farm launcher, hidden-launch quoting, launcher states, WMI process lists, relaunch, a rollback whose stop failed, unknown processes, waiting for the network, closing a watch handle.

One part per former file, each run on its own (tests/_parts.py): test_apphost_covers_service.py, test_estop_verifies.py, test_farm_launcher.py, test_hidden_launch_quoting.py, test_launcher_states.py, test_procs_wmi.py, test_relaunch.py, test_rollback_stop_failed.py, test_unknown_process_list.py, test_wait_network.py, test_watch_handle_close.py.
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


def _part_apphost_covers_service():  # noqa: C901 - the whole body of the file this part was
    """app_main.AppHost has every attribute the code it runs reads off it.

2026-10-11: 971a1a27 made service.main call self._stop_in_boot, which AppHost did not
borrow; the installed relay died at every start with "'AppHost' object has no attribute
'_stop_in_boot'" and every switch-over went back to the old relay (cloud run
38094295924). Read from the source (pywin32 is not on the Mac).

Review round 8 #24: the first version of this test read only the borrowed methods'
own `self.xxx`. The host also travels as an argument - service.main passes it to
service._loop(svc, ...) and boot_stages._stage_inbox_and_phone(svc, ...), which hands it
on to _start_phone_channel; app_main gives it to two threads - and a `svc.xxx` there
that AppHost lacks fails the same way. The walk below follows the host through those
calls (a plain or module-qualified call, or threading.Thread(target=f, args=(...)))
into any function of app_main, service or boot_stages, as deep as it goes.

    Formerly test_apphost_covers_service.py.
    """
    import ast

    RELAY = Path(__file__).resolve().parents[1]
    # The files the host travels through, by the name the code calls them by. service.py's main
    # loop and boot_stages' phone channel moved into the package on 2026-10-11.
    MODULES = {"app_main": "app_main.py", "service": "service.py", "boot_stages": "boot_stages.py",
               "mainloop": "ark_relay/features/host/mainloop.py",
               "phone_channel": "ark_relay/features/phone/phone_channel.py"}


    def cls(tree: ast.Module, name: str) -> ast.ClassDef:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        raise SystemExit(f"FAIL no class {name}")


    def host_has(tree: ast.Module) -> "tuple[set[str], dict[str, str]]":
        """What AppHost defines, and which ArkRelayService methods it borrows (name -> source)."""
        host = cls(tree, "AppHost")
        has = {t.id for n in host.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
        has |= {n.name for n in host.body if isinstance(n, ast.FunctionDef)}
        has |= {n.attr for n in ast.walk(host) if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
                and isinstance(n.value, ast.Name) and n.value.id == "self"}
        borrowed = {t.id: n.value.attr for n in host.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)
                    and isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Attribute)
                    and n.value.value.attr == "ArkRelayService"}
        return has, borrowed


    def _params(fn) -> "list[str]":
        return [a.arg for a in fn.args.posonlyargs + fn.args.args]


    def _is(node, name: str) -> bool:
        return isinstance(node, ast.Name) and node.id == name


    def module_funcs(trees: "dict[str, ast.Module]") -> "tuple[dict[str, dict], dict[int, str]]":
        """Each file's functions by the name its code calls them, and the file each one lives in."""
        funcs = {m: {n.name: n for n in t.body if isinstance(n, ast.FunctionDef)} for m, t in trees.items()}
        home = {id(f): m for m, fs in funcs.items() for f in fs.values()}
        # `from ark_relay.features.host.mainloop import _loop`: the name is that module's function.
        for m, t in trees.items():
            for n in ast.walk(t):
                if isinstance(n, ast.ImportFrom) and (n.module or "").rsplit(".", 1)[-1] in trees:
                    src = n.module.rsplit(".", 1)[-1]
                    funcs[m].update({a.asname or a.name: funcs[src][a.name] for a in n.names
                                     if a.name in funcs[src]})
        return funcs, home


    def walk_host(trees: "dict[str, ast.Module]") -> "tuple[dict[str, str], set[str], set[str]]":
        """Every attribute read off the host, with the call path that reaches it; every one
    stored on it; and the functions the walk went through."""
        funcs, home = module_funcs(trees)
        methods = {n.name: n for n in cls(trees["service"], "ArkRelayService").body
                   if isinstance(n, ast.FunctionDef)}
        has, borrowed = host_has(trees["app_main"])
        used: "dict[str, str]" = {}
        stored: "set[str]" = set()
        seen: "set[tuple]" = set()

        def callee(mod: str, ref) -> "tuple[str, ast.FunctionDef] | None":
            if isinstance(ref, ast.Name) and ref.id in funcs[mod]:
                return home[id(funcs[mod][ref.id])], funcs[mod][ref.id]
            if (isinstance(ref, ast.Attribute) and isinstance(ref.value, ast.Name)
                    and ref.value.id in funcs and ref.attr in funcs[ref.value.id]):
                return ref.value.id, funcs[ref.value.id][ref.attr]
            return None

        def visit(mod: str, fn, param: str, path: str) -> None:
            if (mod, fn.name, param) in seen:
                return
            seen.add((mod, fn.name, param))
            for n in ast.walk(fn):
                if isinstance(n, ast.Attribute) and _is(n.value, param):
                    if isinstance(n.ctx, ast.Store):
                        stored.add(n.attr)
                    else:
                        used.setdefault(n.attr, path)
                if not isinstance(n, ast.Call):
                    continue
                # host.method(...): a borrowed service method runs with self = the host.
                if (isinstance(n.func, ast.Attribute) and _is(n.func.value, param)
                        and borrowed.get(n.func.attr) in methods):
                    src = borrowed[n.func.attr]
                    visit("service", methods[src], "self", f"{path} > {src}")
                # f(..., host, ...) / mod.f(..., host, ...)
                hit = callee(mod, n.func)
                if hit:
                    cmod, cfn = hit
                    names = _params(cfn)
                    for i, a in enumerate(n.args):
                        if _is(a, param) and i < len(names):
                            visit(cmod, cfn, names[i], f"{path} > {cmod}.{cfn.name}")
                    for kw in n.keywords:
                        if _is(kw.value, param) and kw.arg:
                            visit(cmod, cfn, kw.arg, f"{path} > {cmod}.{cfn.name}")
                # threading.Thread(target=f, args=(..., host, ...))
                kws = {kw.arg: kw.value for kw in n.keywords}
                target = callee(mod, kws.get("target"))
                if target and isinstance(kws.get("args"), ast.Tuple):
                    cmod, cfn = target
                    names = _params(cfn)
                    for i, a in enumerate(kws["args"].elts):
                        if _is(a, param) and i < len(names):
                            visit(cmod, cfn, names[i], f"{path} > thread {cmod}.{cfn.name}")

        for name, src in sorted(borrowed.items()):
            if src in methods:                         # not a class attribute such as _svc_name_
                visit("service", methods[src], "self", f"AppHost.{name}")
        # Where app_main makes the host: `host = _host_class()()`.
        for fn in funcs["app_main"].values():
            if any(isinstance(n, ast.Assign) and any(_is(t, "host") for t in n.targets) for n in ast.walk(fn)):
                visit("app_main", fn, "host", f"app_main.{fn.name}")
        return used, stored, {f"{m}.{f}" for m, f, _ in seen}


    def missing(trees) -> "dict[str, str]":
        has, _ = host_has(trees["app_main"])
        used, stored, _ = walk_host(trees)
        return {a: p for a, p in used.items() if a not in has and a not in stored}


    def parse() -> "dict[str, ast.Module]":
        return {m: ast.parse((RELAY / f).read_text(encoding="utf-8")) for m, f in MODULES.items()}


    def plant(trees, mod: str, fn: str, param: str, attr: str):
        """A read of `<param>.<attr>` at the top of mod.fn, in a fresh copy of the trees."""
        out = parse()
        for n in ast.walk(out[mod]):                 # module functions and methods alike
            if isinstance(n, ast.FunctionDef) and n.name == fn:
                n.body.insert(0, ast.Expr(ast.Attribute(ast.Name(param, ast.Load()), attr, ast.Load())))
                return out
        raise SystemExit(f"FAIL no {mod}.{fn}")


    def borrowed_only(trees) -> "set[str]":
        """The first version's reading: the borrowed methods' own self.xxx, nothing else."""
        has, borrowed = host_has(trees["app_main"])
        methods = {n.name: n for n in cls(trees["service"], "ArkRelayService").body
                   if isinstance(n, ast.FunctionDef)}
        used = {n.attr for src in borrowed.values() if src in methods for n in ast.walk(methods[src])
                if isinstance(n, ast.Attribute) and _is(n.value, "self")}
        return used - has


    trees = parse()

    print("[the real AppHost covers everything the host reaches]")
    _, _, reached = walk_host(trees)
    for fn in ("service.main", "mainloop._loop", "boot_stages._stage_inbox_and_phone",
               "phone_channel._start_phone_channel", "app_main._end_session_window", "app_main._stop_requests"):
        require(f"walk reaches {fn}", fn in reached)
    gaps = missing(trees)
    require("AppHost lacks nothing", not gaps, "; ".join(f"{a} (via {p})" for a, p in sorted(gaps.items())))
    has, borrowed = host_has(trees["app_main"])
    require("AppHost borrows ArkRelayService.main (else this test reads the wrong thing)", "main" in borrowed)

    print("[a host attribute AppHost lacks is caught wherever the host travels]")
    for mod, fn, param in (("mainloop", "_loop", "svc"),
                           ("phone_channel", "_start_phone_channel", "svc"),
                           ("app_main", "_stop_requests", "host"),
                           ("service", "main", "self")):
        planted = plant(trees, mod, fn, param, "_not_on_host")
        got = missing(planted)
        require(f"{mod}.{fn}: {param}._not_on_host is reported", "_not_on_host" in got,
              got.get("_not_on_host", "not reported"))

    print("[971a1a27's own case: AppHost without _stop_in_boot]")
    t = parse()
    host = cls(t["app_main"], "AppHost")
    host.body = [n for n in host.body if not (isinstance(n, ast.Assign) and any(_is(x, "_stop_in_boot") for x in n.targets))]
    got = missing(t)
    require("_stop_in_boot is reported", "_stop_in_boot" in got, got.get("_stop_in_boot", "not reported"))

    print("[the first version missed the round-8 case: service._loop(svc) reading svc.xxx]")
    require("borrowed-methods-only reading misses it",
          "_not_on_host" not in borrowed_only(plant(trees, "mainloop", "_loop", "svc", "_not_on_host")))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_estop_verifies():
    """The red button on the phone must not say 「已停一切」 unless it checked.

The conclusion of 2026-08-26, in the user's own words, was 「你没有进行任何有效的停止
行为，全是我手动关的」. The phone button kept that shape: stop through the AUTO-MAS
API, run taskkill twice, then return a hard-coded success - no look at what was
actually left, and the message went straight out as a push.

Two things make that worse than doing nothing. AUTO-MAS retries the whole queue when
one of its members is killed under it, so "killed it twice" says nothing about the
state half a minute later; and the process list it did surface never contained
Wuthering Waves' real process names, which is exactly how the 08-26 check passed
while the game was running.

So: verify, retry once, and tell the truth either way.

    Formerly test_estop_verifies.py.
    """
    import json


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.phone import commands
    # estop() reads its stop steps and _mas from redbutton, so the fakes go there.
    from ark_relay.features.phone import redbutton


    print("[要杀要查的名单里必须有鸣潮的三个真名——08-26 的假确认就漏在这里]")
    for exe in ("Wuthering Waves.exe", "Client-Win64-Shipping.exe", "KRSDKExternal.exe",
                "ok-ww.exe", "MAA.exe", "MaaEnd.exe", "Endfield.exe", "dnplayer.exe"):
        check(f"名单含 {exe}", exe in redbutton._ESTOP_EXES, True)
    print("  ✓ 终末地启动器 Games.exe 也在" if "Games.exe" in redbutton._ESTOP_EXES else "")
    check("终末地启动器也在", "Games.exe" in redbutton._ESTOP_EXES, True)


    class Rig:
        """Stands in for the four actions: API stop, kill, who is alive, which AUTO-MAS tasks are unfinished.

    task_rounds are the successive answers to the AUTO-MAS task check (None =
    unreadable); when omitted the answer is "no tasks", so the older scenarios
    exercise the process check alone."""

        def __init__(self, alive_rounds, task_rounds=()):
            self.alive_rounds = list(alive_rounds)
            self.task_rounds = list(task_rounds)
            self.kills = 0
            self.stops = 0
            self.slept = 0
            self.state = tmpdir()

        def install(self):
            redbutton._estop_stop_via_mas = lambda: (setattr(self, "stops", self.stops + 1),
                                                    ["早班"])[1]
            redbutton._estop_kill = lambda: setattr(self, "kills", self.kills + 1)
            redbutton._estop_alive = lambda: (self.alive_rounds.pop(0)
                                             if self.alive_rounds else [])
            redbutton._estop_live_tasks = lambda: (self.task_rounds.pop(0)
                                                  if self.task_rounds else [])
            return self

        def sleep(self, n):
            self.slept += n

        def run(self):
            return commands.estop(sleep=self.sleep, state_dir=self.state)


    real = (redbutton._estop_stop_via_mas, redbutton._estop_kill, redbutton._estop_alive,
            redbutton._estop_live_tasks, redbutton._mas)

    print("\n[一轮就干净：说成功，而且说的是「确认没了」不是「已经杀过了」]")
    r = Rig([[]]).install()
    ok, msg = r.run()
    check("返回成功", ok, True)
    check("话里说了确认", "确认没了" in msg, True)
    check("只停了一轮接口", r.stops, 1)

    print("\n[第一次查还有残留：必须再停一轮，然后才许说成功]")
    r = Rig([["MAA.exe"], []]).install()
    ok, msg = r.run()
    check("返回成功", ok, True)
    check("停了两轮接口", r.stops, 2)

    print("\n[两轮都停不住：不许说成功，要点名还活着谁，并指到 estop.sh]")
    r = Rig([["Client-Win64-Shipping.exe"], ["Client-Win64-Shipping.exe"]]).install()
    ok, msg = r.run()
    check("返回失败", ok, False)
    check("不含「已停一切」", "已停一切" in msg, False)
    check("点名了还活着的（用中文说游戏名）", "鸣潮" in msg, True)
    check("指到电脑上的紧急停止脚本", "紧急停止" in msg, True)
    check("说清为什么中继自己停不住", "整队重跑" in msg, True)
    check("不许在推送里出现进程名", "Client-Win64-Shipping" in msg, False)

    print("\n[进程表读不到时按「还活着」算——不知道不许说成全清]")
    r = Rig([["进程表读不到"], ["进程表读不到"]]).install()
    ok, msg = r.run()
    check("返回失败", ok, False)
    check("话里说了读不到", "进程表读不到" in msg, True)

    print("\n[09-30 早上那样：游戏都杀没了，AUTO-MAS 已经换到下一个脚本在跑——再停一轮，清了才说成功]")
    r = Rig([[], []], [[("t-2", "MaaEnd")], []]).install()
    ok, msg = r.run()
    check("返回成功", ok, True)
    check("因为 AUTO-MAS 还有任务而停了第二轮", r.stops, 2)
    check("成功的话里也说了 AUTO-MAS 没有在跑的任务", "AUTO-MAS 也没有在跑的任务了" in msg, True)

    print("\n[两轮后 AUTO-MAS 还记着有任务在跑：不许说成功，点名那个任务]")
    r = Rig([[], []], [[("t-2", "早班")], [("t-3", "早班")]]).install()
    ok, msg = r.run()
    check("返回失败", ok, False)
    check("以「没停干净：」开头", msg.startswith("没停干净："), True)
    check("点名了 AUTO-MAS 还在跑的任务", "AUTO-MAS 还记着有任务在跑：早班" in msg, True)
    check("不含「已停一切」", "已停一切" in msg, False)
    check("指到电脑上的紧急停止脚本", "紧急停止" in msg, True)
    check("说清为什么中继自己停不住", "整队重跑" in msg, True)

    print("\n[进程和任务都还在：两样都点名，游戏用中文名]")
    r = Rig([["MaaEnd.exe"], ["MaaEnd.exe"]], [[("t", "早班")], [("t", "早班")]]).install()
    ok, msg = r.run()
    check("返回失败", ok, False)
    check("游戏用中文名", "终末地的脚本" in msg, True)
    check("任务也点名", "早班" in msg, True)
    check("不出现进程名", "MaaEnd.exe" in msg, False)

    print("\n[AUTO-MAS 的任务列表读不到：按「还在跑」算，不许说全清]")
    r = Rig([[], []], [None, None]).install()
    ok, msg = r.run()
    check("返回失败", ok, False)
    check("再停了一轮", r.stops, 2)
    check("以「没停干净：」开头", msg.startswith("没停干净："), True)
    check("说了问不到", "问不到 AUTO-MAS 还有没有任务在跑" in msg, True)

    print("\n[按下的时间写进 estop-windows.json：开始和结束都有，读回来是一段]")
    r = Rig([[]]).install()
    r.run()
    rows = json.loads((r.state / commands.ESTOP_WINDOWS_FILE).read_text(encoding="utf-8"))
    check("记了一笔", len(rows), 1)
    check("有开始也有结束", sorted(rows[0]), ["end", "start"])
    wins = commands.estop_windows(r.state)
    check("读回来一段", len(wins), 1)
    check("开始不晚于结束", wins[0][0] <= wins[0][1], True)
    check("带时区（北京时间）", wins[0][0].utcoffset().total_seconds(), 8 * 3600)

    print("\n[按了没写完（中继中途死了）：没有结束的不算窗口，原因不明，不兜底 10 分钟（09-30 18:04 定）]")
    d = tmpdir()
    (d / commands.ESTOP_WINDOWS_FILE).write_text(
        json.dumps([{"start": "2026-09-30T09:46:40+08:00"},
                    {"start": "2026-09-30T20:00:00+08:00", "end": "2026-09-30T20:01:00+08:00"}]), encoding="utf-8")
    w = commands.estop_windows(d)
    check("只剩有结束的那段", [x[0].strftime("%H:%M") for x in w], ["20:00"])
    from datetime import datetime
    _T = commands.SERVER_TZ
    check("没结束的那次按下：落在它后面的趟不标",
          commands.estop_label(w, datetime(2026, 9, 30, 9, 40, tzinfo=_T), datetime(2026, 9, 30, 9, 47, tzinfo=_T)), "")

    print("\n[停掉 = 按下时还在跑、且结束落在按下期间（09-30 18:04 定）]")
    W = [(datetime(2026, 9, 30, 9, 46, 28, tzinfo=_T), datetime(2026, 9, 30, 9, 47, 22, tzinfo=_T))]
    check("09:38 开始、09:46:58 结束（09-30 那趟 OK-WW）→ 标",
          commands.estop_label(W, datetime(2026, 9, 30, 9, 38, tzinfo=_T), datetime(2026, 9, 30, 9, 46, 58, tzinfo=_T)),
          "09:46 停一切")
    check("按下期间开始又结束（09-30 那趟 MaaEnd）→ 标",
          commands.estop_label(W, datetime(2026, 9, 30, 9, 46, 58, tzinfo=_T), datetime(2026, 9, 30, 9, 47, 10, tzinfo=_T)),
          "09:46 停一切")
    check("跨过按下、一直跑到按下结束之后 → 不是它停的，不标",
          commands.estop_label(W, datetime(2026, 9, 30, 9, 40, tzinfo=_T), datetime(2026, 9, 30, 10, 5, tzinfo=_T)), "")
    check("按下之前就结束了 → 不标",
          commands.estop_label(W, datetime(2026, 9, 30, 9, 30, tzinfo=_T), datetime(2026, 9, 30, 9, 46, tzinfo=_T)), "")
    check("不带时区的按北京时间算",
          commands.estop_label(W, datetime(2026, 9, 30, 9, 38), datetime(2026, 9, 30, 9, 47)), "09:46 停一切")
    check("没有文件时是空的", commands.estop_windows(tmpdir()), [])
    (d / commands.ESTOP_WINDOWS_FILE).write_text("{坏", encoding="utf-8")
    check("坏文件不抛异常", commands.estop_windows(d), [])

    print("\n[只留最近 20 笔]")
    d = tmpdir()
    for _ in range(25):
        Rig([[]]).install()
        commands.estop(sleep=lambda n: None, state_dir=d)
    check("20 笔", len(json.loads((d / commands.ESTOP_WINDOWS_FILE).read_text(encoding="utf-8"))), 20)

    (redbutton._estop_stop_via_mas, redbutton._estop_kill, redbutton._estop_alive,
     redbutton._estop_live_tasks, redbutton._mas) = real

    print("\n[停的时候发的是 AUTO-MAS 在跑任务的 taskId，不是脚本 / 队列编号（09-30 的根因）]")
    calls = []


    def fake_mas(path, body=None, timeout=20):
        calls.append((path, body))
        if path == "/api/scripts/get":
            return {"data": {"script-uuid": {"Info": {"Name": "OK-WW"}}}}
        if path == "/api/queue/get":
            return {"data": {"queue-uuid": {"Info": {"Name": "早班"}}}}
        return {"code": 200, "message": "操作成功"}


    redbutton._mas = fake_mas
    redbutton._estop_live_tasks = lambda: [("dispatch-abc", "MaaEnd"), ("dispatch-def", "早班")]
    got = redbutton._estop_stop_via_mas()
    check("返回停到的标签", got, ["MaaEnd", "早班"])
    check("按 taskId 逐个发停止", calls, [("/api/dispatch/stop", {"taskId": "dispatch-abc"}),
                                        ("/api/dispatch/stop", {"taskId": "dispatch-def"})])
    check("没去读脚本和队列编号", any(p in ("/api/scripts/get", "/api/queue/get") for p, _ in calls), False)

    calls.clear()
    redbutton._estop_live_tasks = lambda: None
    got = redbutton._estop_stop_via_mas()
    check("读不到在跑的任务：不谎称停到了什么", got, [])
    check("读不到时退回按脚本 / 队列编号发（无害）", [b for p, b in calls if p == "/api/dispatch/stop"],
          [{"taskId": "script-uuid"}, {"taskId": "queue-uuid"}])

    # Audit 11 #6: AUTO-MAS answers a stop it could not do with code 500 (app/api/
    # dispatch.py stop_task), not an HTTP error; that task was listed as stopped.
    redbutton._mas = lambda path, body=None, timeout=20: (
        {"code": 500, "status": "error", "message": "KeyError: 'dispatch-abc'"}
        if body == {"taskId": "dispatch-abc"} else {"code": 200, "status": "success", "message": "操作成功"})
    redbutton._estop_live_tasks = lambda: [("dispatch-abc", "MaaEnd"), ("dispatch-def", "早班")]
    check("a refused stop (code 500) is not listed as stopped", redbutton._estop_stop_via_mas(), ["早班"])
    redbutton._mas, redbutton._estop_live_tasks = real[4], real[3]

    print("\n[读 AUTO-MAS 在跑的任务：用 GET 读 runtime-snapshot，只收没结束的，口径和 engine 同一个]")
    import urllib.request as _ur
    real_urlopen = _ur.urlopen
    seen_req = []


    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    SNAP = {"tasks": [
        {"taskId": "done-1", "mode": "AutoProxy",
         "task_info": [{"name": "OK-WW", "status": "完成"}]},
        {"taskId": "live-2", "mode": "AutoProxy",
         "task_info": [{"name": "OK-WW", "status": "完成"}, {"name": "MaaEnd", "status": "运行"}]},
        {"taskId": "fresh-3", "mode": "早班", "task_info": []},
    ]}


    def fake_urlopen(req, timeout=None):
        seen_req.append(req)
        return Resp(json.dumps(SNAP, ensure_ascii=False).encode("utf-8"))


    _ur.urlopen = fake_urlopen
    live = redbutton._estop_live_tasks()
    check("只收没结束的两个", [t for t, _ in live], ["live-2", "fresh-3"])
    check("标签用任务名以「、」连", live[0][1], "OK-WW、MaaEnd")
    check("没有任务名时用 mode", live[1][1], "早班")
    check("是 GET（传的是地址，不带请求体）", isinstance(seen_req[0], str), True)
    check("读的是 runtime-snapshot", seen_req[0].endswith("/api/dispatch/runtime-snapshot"), True)
    from ark_relay.core import engine as _engine
    check("和 engine 的判断一致", bool(live), _engine._judge_snapshot(SNAP))


    def _down(*a, **k):
        raise OSError("连不上")


    _ur.urlopen = _down
    check("读不到时返回 None（不是空列表）", redbutton._estop_live_tasks(), None)
    _ur.urlopen = real_urlopen

    print("\n[查活着谁：认名字不分大小写，一个不落]")
    import subprocess as _sp
    from ark_relay.core import config as _config
    from ark_relay.features.okww_patch import okww_overlay as _ov
    from ark_relay.features.phone import snapshot as _snap
    real_okww_running = _ov.okww_running
    real_run, real_win = _sp.run, _config.IS_WINDOWS
    _config.IS_WINDOWS = True     # the machine: the red button lists processes


    class Out:
        def __init__(self, text):
            self.stdout = text.encode("utf-8")


    _ov.okww_running = lambda: False
    _sp.run = lambda *a, **k: Out('"MAA.exe","1","Console"\n"client-win64-shipping.exe","2","C"\n')
    check("大小写不同也认得出", set(redbutton._estop_alive()),
          {"MAA.exe", "Client-Win64-Shipping.exe"})
    _sp.run = lambda *a, **k: Out('"explorer.exe","1","Console"\n')
    check("干净时是空的", redbutton._estop_alive(), [])


    def _boom(*a, **k):
        raise OSError("tasklist 挂了")


    print("\n[OK-WW's python: invisible to tasklist names, seen by its command line (audit 11 #3)]")
    # OK-WW runs as pythonw.exe (config.py "process names"); a press while it ran could
    # answer 「确认没了」 with OK-WW still up.
    _sp.run = lambda *a, **k: Out('"pythonw.exe","1","Console"\n')
    _ov.okww_running = lambda: True
    check("OK-WW's python alive -> not clear", len(redbutton._estop_alive()), 1)
    _ov.okww_running = lambda: None
    check("its process list unread -> counted alive", len(redbutton._estop_alive()), 1)
    _ov.okww_running = lambda: False
    check("gone -> clear", redbutton._estop_alive(), [])
    _ov.okww_running = lambda: True
    check("told as 鸣潮的脚本", [getattr(redbutton, "_ESTOP_LABELS", {}).get(a) for a in redbutton._estop_alive()],
          ["鸣潮的脚本"])

    class Txt:
        def __init__(self, text):
            self.stdout = text


    _sp.run = lambda *a, **k: Txt("AUTO-MAS.exe 1 Console\npythonw.exe 2 Console\n")
    for got_ww, want in ((True, True), (None, True), (False, False)):
        _ov.okww_running = lambda v=got_ww: v
        getattr(_snap, "_okww_alive", {}).update(at=None)   # each case asks afresh (30 s cache)
        o = {}
        _snap._runtime(o)
        check(f"the App's running list: okww_running {got_ww} -> ok-ww {want}", o.get("程序", {}).get("ok-ww"), want)
    _ov.okww_running = real_okww_running

    _sp.run = _boom
    check("读不到时不许返回空", redbutton._estop_alive(), ["读不到正在运行的程序列表"])
    _sp.run, _config.IS_WINDOWS = real_run, real_win


def _part_farm_launcher():
    """The farm launcher must not leave a console window on top of the game.

2026-09-09: the .bat ran pythonw in the foreground, so cmd.exe's console stayed open
over the middle of the screen for the whole run. OK-WW screenshots the game window,
read the black console where the confirm dialog should have been, and every teleport
failed with 「Teleport to boss failed」. Three runs, no echoes, and not one line in the
log pointing at the window. `start ""` hands OK-WW off and lets the .bat end.

    Formerly test_farm_launcher.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import os
    import subprocess

    from ark_relay.features.echofarm import echofarm


    root = tmpdir()
    py = root / "data" / "apps" / "ok-ww" / "python" / "pythonw.exe"
    main = root.joinpath(*echofarm._WORKING, "main.py")
    py.parent.mkdir(parents=True)
    main.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    main.write_text("", encoding="utf-8")

    bat = tmpdir() / "farm.bat"
    echofarm.BAT = str(bat)
    os.environ["ARK_OKWW_DIR"] = str(root)

    ran = []
    real_run = subprocess.run


    class Done:
        returncode = 0
        stderr = b""


    subprocess.run = lambda *a, **k: (ran.append(list(a[0]) if a else []), Done())[1]
    try:
        ok, why = echofarm._launch()
    finally:
        subprocess.run = real_run

    print("[启动脚本本身]")
    check("说启动成功", ok)
    check("没有理由要报", why, "")
    text = bat.read_text(encoding="utf-8")
    check("用 start 交棒后立刻退出", 'start ""' in text)
    check("交给 pythonw，它自己不带控制台", "pythonw.exe" in text)
    check("工作目录切到 OK-WW 那边", "cd /d" in text)
    check("跑的是 FarmEchoTask 那一号", f"-t {echofarm.OKWW_TASK_INDEX}" in text)

    print("[计划任务这一步]")
    check("建了任务", any("schtasks" in c and "/create" in c for c in ran))
    check("跑了任务", any("schtasks" in c and "/run" in c for c in ran))
    check("任务在交互桌面上跑", any("/it" in c for c in ran))

    print("[程序不在就直说，不要建一个跑不起来的任务]")
    py.unlink()
    ok2, why2 = echofarm._launch()
    check("报失败", ok2, False)
    check("话里说了找不到什么", "找不到" in why2)


def _part_hidden_launch_quoting():  # noqa: C901 - the whole body of the file this part was
    """The windowless launch builds a PowerShell command that survives a path with a space.

2026-10-11 (07d90b11) the windowless route moved the program path into the task's
arguments. `subprocess.list2cmdline` puts double quotes round any argument with a
space, and `_spawn_via_task` pasted that string inside a double-quoted PowerShell
string (`-Argument "..."`): the first inner quote closed it. The OK-WW failure
screenshot starts C:\\Program Files\\PowerShell\\7\\pwsh.exe (handle.py, `_PWSH7`), so
its task action got a cut-off argument string plus loose words, and the picture was
never taken. relay.log has no 「pwsh.exe（无窗口）」 line since that change.

No PowerShell here: the command `_spawn_via_task` hands to pwsh is captured and
parsed with PowerShell's argument-mode quoting rules (about_Quoting_Rules,
about_Parsing), then the -Argument value is split the way a Windows program splits
its command line (CommandLineToArgvW), and must give back the exact arguments.

    Formerly test_hidden_launch_quoting.py.
    """
    import subprocess
    from pathlib import Path, PureWindowsPath

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.preupdate import preupdate_common as C


    def ps_statements(script: str) -> list[list[str]]:
        """Statements of a PowerShell command line, each a list of argument-mode tokens.

    Quoting as PowerShell reads it: '...' is literal ('' is one quote); "..." ends at
    the next unescaped " (`x and "" escape); a token that starts with a quote ends at
    its closing quote, a bare token runs on through embedded quoted parts until white
    space or ';'. Enough for the one statement under test; not a full parser."""
        out, cur, i, n = [], [], 0, len(script)
        while i < n:
            c = script[i]
            if c in " \t":
                i += 1
                continue
            if c == ";":
                out.append(cur)
                cur = []
                i += 1
                continue
            tok, started_quoted = "", c in "'\""
            while i < n and script[i] not in " \t;":
                q = script[i]
                if q == "'":
                    i += 1
                    while i < n:
                        if script[i] == "'" and i + 1 < n and script[i + 1] == "'":
                            tok += "'"
                            i += 2
                        elif script[i] == "'":
                            i += 1
                            break
                        else:
                            tok += script[i]
                            i += 1
                elif q == '"':
                    i += 1
                    while i < n:
                        if script[i] == "`" and i + 1 < n:
                            tok += script[i + 1]
                            i += 2
                        elif script[i] == '"' and i + 1 < n and script[i + 1] == '"':
                            tok += '"'
                            i += 2
                        elif script[i] == '"':
                            i += 1
                            break
                        else:
                            tok += script[i]
                            i += 1
                else:
                    tok += q
                    i += 1
                    continue
                if started_quoted:
                    break
            cur.append(tok)
        if cur:
            out.append(cur)
        return out


    def win_argv(line: str) -> list[str]:
        """Split a command line as the C runtime / CommandLineToArgvW does (the inverse of list2cmdline)."""
        args, cur, inq, have, i = [], "", False, False, 0
        while i < len(line):
            c = line[i]
            if c == "\\":
                j = i
                while j < len(line) and line[j] == "\\":
                    j += 1
                k = j - i
                if j < len(line) and line[j] == '"':
                    cur += "\\" * (k // 2)
                    if k % 2:
                        cur += '"'
                        i = j + 1
                    else:
                        i = j
                    have = True
                    continue
                cur += "\\" * k
                i = j
                have = True
                continue
            if c == '"':
                inq = not inq
                have = True
                i += 1
                continue
            if c in " \t" and not inq:
                if have:
                    args.append(cur)
                cur, have = "", False
                i += 1
                continue
            cur += c
            have = True
            i += 1
        if have:
            args.append(cur)
        return args


    def action_params(script: str) -> dict:
        """The New-ScheduledTaskAction statement as {"-Execute": v, ..., "loose": [...]}."""
        stmt = next(s for s in ps_statements(script) if any("New-ScheduledTaskAction" in t for t in s))
        toks = stmt[stmt.index(next(t for t in stmt if t.endswith("New-ScheduledTaskAction"))) + 1:]
        got, loose, i = {}, [], 0
        while i < len(toks):
            if toks[i] in ("-Execute", "-Argument", "-WorkingDirectory") and i + 1 < len(toks):
                got[toks[i]] = toks[i + 1]
                i += 2
            else:
                loose.append(toks[i])
                i += 1
        got["loose"] = loose
        return got


    def captured_command(exe, cwd, args):
        """The -Command string _spawn_hidden_via_task passes to pwsh, with pythonw.exe present."""
        seen = []

        def fake_run(argv, **kw):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        saved = C.subprocess.run, C._pythonw, C._pwsh
        C.subprocess.run = fake_run
        C._pythonw = lambda: PureWindowsPath(r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe")
        C._pwsh = lambda: str(C._PWSH7)
        try:
            ok = C._spawn_hidden_via_task(exe, cwd, args)
        finally:
            C.subprocess.run, C._pythonw, C._pwsh = saved
        check("the launch reports success", ok, True)
        return seen[0][seen[0].index("-Command") + 1]


    print("[the OK-WW failure screenshot: pwsh.exe under C:\\Program Files, windowless]")
    work = tmpdir() / "desktop"             # no space: the program path alone breaks the old string
    ps1 = r"C:\ProgramData\ark-relay\state\okww-shot.ps1"
    script_args = ("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1)
    cmd = captured_command(PureWindowsPath(str(C._PWSH7)), work, script_args)
    got = action_params(cmd)
    _, want_args, _ = C.hidden_plan(PureWindowsPath(str(C._PWSH7)), work, script_args,
                                    PureWindowsPath(r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe"))
    check("no loose word left beside -Execute / -Argument / -WorkingDirectory", got["loose"], [])
    check("-Execute is pythonw.exe, whole", got.get("-Execute"),
          r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe")
    check("-Argument is the whole list2cmdline string", got.get("-Argument"), subprocess.list2cmdline(list(want_args)))
    check("the task's program gets back every argument, pwsh.exe's path in one piece",
          win_argv(got.get("-Argument", "")), list(want_args))
    check("-WorkingDirectory is the folder", got.get("-WorkingDirectory"), str(work))

    print("\n[a program path with no space: the route that worked before still does]")
    cmd = captured_command(PureWindowsPath(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
                           tmpdir() / "desktop", ("-File", "agent.ps1"))
    got = action_params(cmd)
    check("no loose word", got["loose"], [])
    check("arguments round-trip", win_argv(got.get("-Argument", ""))[-3:],
          [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", "-File", "agent.ps1"])

    print("\n[a folder with a space and a quote in its name: the quote is written twice inside '...']")
    odd = tmpdir() / "it's here"
    cmd = captured_command(PureWindowsPath(str(C._PWSH7)), odd, ("-File", "a.ps1"))
    got = action_params(cmd)
    check("no loose word", got["loose"], [])
    check("-WorkingDirectory keeps the quote and the space", got.get("-WorkingDirectory"), str(odd))
    check("the launcher path in the folder comes back whole", (win_argv(got.get("-Argument", "")) + ["", ""])[1],
          str(odd / C.HIDDEN_LAUNCHER_NAME))

    print("\n[the tokenizer itself reads the 10-11 command the way PowerShell does]")
    old = ('$a=New-ScheduledTaskAction -Execute "C:\\py\\pythonw.exe" -Argument "-I C:\\w\\l.py '
           '"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -File a.ps1" -WorkingDirectory "C:\\w";')
    got = action_params(old)
    check("the old double-quoted -Argument is cut at the inner quote", got.get("-Argument"), "-I C:\\w\\l.py ")
    check("and leaves loose words that bind to no parameter", len(got["loose"]) > 0, True)


def _part_launcher_states():
    """Launcher screens the update flows must not misread (audit 2026-10-06).

When the game screen is unknown or unreadable, update_endfield must not claim
"up to date", must not click blindly and must not kill a launcher that is
downloading. (update_wuwa went on 2026-10-12: AUTO-MAS updates Wuthering Waves,
item 10b.) Fake desktop only: no Windows, no processes.

Where the screens come from:
* The words 正在下载 / 安装中 (Hypergryph) were read off the machine on 2026-09-02
  and are quoted in gameupdate_games.py; no relay.log line carries a whole launcher screen, so those
  screens are built from those words.
* relay-log-1006/relay.log lines 5356-5397 (09-02 15:48-15:50): the desktop agent
  timed out (「桌面助手 … 超时没有结果」) and both launchers were reported as
  「启动器画面没读到按钮」 with an empty or garbage dump - the "unreadable" case.
* relay-log-1006/relay.log lines 10430-10437 (09-04 12:38:55-12:40:17): a real
  Arknights prewarm, three bottom taps and then 「开始唤醒」. Replayed below.
* The focus-missing screen is built from AGENT_PS's fields (the agent logs
  「focus: 没有 $f 的窗口」 and, since this audit, sets focus_missing); no real line.
* SPACE_DIALOG: the launcher's 「系统提示」 disk-space confirm after 「更新游戏」, 2026-10-15
  (relay.log 09:33:18 「已点「更新游戏」」, then 40 minutes of desktop-icon dumps; the
  relay's own screenshot shot-0956fb2a.png 09:33:52). The lines are what the agent's
  two OCR passes read off that screenshot, coordinates on the 1920x1080 screen; the
  desktop-icon lines are cut down to three neutral ones (the others are file names
  on his desktop). CONFIRM_BOX is the white 「确认」 button measured on the same
  screenshot's pixels - neither OCR pass reads its text.

    Formerly test_launcher_states.py.
    """
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.gameupdate import gameupdate_games as gug
    from ark_relay.core.desktop import Line, Screen


    # ── a clock that only moves when the code sleeps, so every budget runs out ──
    clock = {"t": 0.0}
    slept = []


    def fake_sleep(s):
        slept.append(s)
        clock["t"] += s


    gug.time = types.SimpleNamespace(monotonic=lambda: clock["t"], sleep=fake_sleep)

    # ── what was killed / closed / spawned, in order with the clicks ──
    events = []
    gug.kill = lambda *names: events.append(("kill",) + names)
    gug._spawn = lambda exe, cwd=None: events.append(("spawn", exe.name)) or True


    class FakeDesk:
        """Replays screens in order (the last one repeats). A screen is a list of
    OCR lines, or ("missing", [lines]) for a read whose focus window was not found
    - its lines then belong to whatever window was in front."""

        def __init__(self, screens, click_ok=True):
            self.screens = list(screens)
            self.click_ok = click_ok
            self.clicks = []

        def read(self, focus=None, settle_ms=0):
            spec = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
            missing = isinstance(spec, tuple) and spec[0] == "missing"
            if isinstance(spec, tuple) and spec[0] == "error":
                # The desktop agent failed (Desktop.read: ok false -> Screen.error)
                events.append(("read", focus, ("<error>",)))
                return Screen([], Path("shot-x.png"), error=spec[1])
            texts = spec[1] if missing else spec
            scr = Screen([Line(t, 100, 100 + 30 * i, 80, 20) for i, t in enumerate(texts)], Path("shot-x.png"))
            scr.focus_missing = missing
            events.append(("read", focus, tuple(texts)))
            return scr

        def _ok(self, what):
            ok = self.click_ok(what) if callable(self.click_ok) else self.click_ok
            self.clicks.append(what)
            events.append(("click", what, ok))
            return ok

        def click_text(self, text, focus=None):
            return self._ok(text)

        def click(self, x, y, focus=None):
            return self._ok((x, y))


    def reset():
        events.clear()
        slept.clear()
        clock["t"] = 0.0


    def before_first_click(kind):
        """Events of `kind` that happened before anything was clicked."""
        out = []
        for e in events:
            if e[0] == "click":
                break
            if e[0] == kind:
                out.append(e)
        return out


    EF = (Path("Endfield.exe"), Path("Launcher.exe"))

    print("[1 终末地：启动器窗口没找到，前台别的窗口有「开始游戏」→ 不算无需更新，报问题，不点不杀]")
    reset(); probs = []
    d = FakeDesk([("missing", ["开始游戏"])])
    out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
    check("返回空", out, "")
    check("记了问题，点名窗口", any("没找到启动器窗口" in p and "Games" in p for p in probs))
    check("问题带截图", any("shot-x.png" in p for p in probs))
    check("什么都没点", d.clicks, [])
    check("没杀 Games.exe", [e for e in events if e[0] == "kill" and "Games.exe" in e], [])

    print("\n[3 终末地：一打开启动器就在「正在下载」→ 不点不杀，等它装完]")
    reset(); probs = []
    d = FakeDesk([["鹰角启动器", "正在下载 45%"], ["安装中"], ["开始游戏"], ["点击任意位置继续"]])
    out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
    check("等到开始游戏前没杀 Games.exe", [e for e in before_first_click("kill") if "Games.exe" in e], [])
    check("没点「更新游戏」", "更新游戏" in d.clicks, False)
    check("没报没读到按钮", [p for p in probs if "没读到按钮" in p], [])
    check("报了更新", out, "终末地 客户端已通过启动器更新")
    print("  （认不出的画面照旧报问题带截图）")
    reset(); probs = []
    d = FakeDesk([["-以％36．。6．78678967", "么"]])   # relay.log 5397's garbage dump
    out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
    check("返回空", out, "")
    check("报没读到按钮带截图", any("没读到按钮" in p and "shot-x.png" in p for p in probs))

    print("\n[5 终末地：装完了但「开始游戏」没点上 → 不睡 90 秒假装开了，句子里说清]")
    reset(); probs = []
    d = FakeDesk([["更新游戏"], ["开始游戏"]], click_ok=lambda w: w != "开始游戏")
    out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
    check("句子说没点上", "没点上" in out, True)
    check("没睡那 90 秒", 90 in slept, False)
    check("没进游戏那段（没读 Endfield 窗口）", [e for e in events if e[0] == "read" and e[1] == "Endfield"], [])
    print("  （「请重启游戏」的「确认」没点上：照样关掉重开，不中断）")
    reset(); probs = []
    d = FakeDesk([["更新游戏"], ["开始游戏"], ["资源初始化更新完成，请重启游戏", "确认"], ["点击任意位置继续"]],
                 click_ok=lambda w: w != "确认")
    out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
    # Client 1.6.3 (2026-10-15) runs only when the launcher starts it: the restart clicks
    # 「开始游戏」 on the launcher again and never starts Endfield.exe itself.
    check("经启动器重开了游戏（又点了开始游戏）", d.clicks.count("开始游戏"), 2)
    check("没直接起 Endfield.exe", ("spawn", "Endfield.exe") in events, False)
    check("报了更新", out, "终末地 客户端已通过启动器更新")
    print("\n[6 终末地：更新后仍「客户端版本已过时」/ 15 分钟没到标题 → 不说已更新]")
    reset(); probs = []
    d = FakeDesk([["更新游戏"], ["开始游戏"], ["客户端版本已过时"]])
    out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
    check("返回空", out, "")
    check("问题保留", any("客户端已过时" in p for p in probs))
    reset(); probs = []
    d = FakeDesk([["更新游戏"], ["开始游戏"], ["正在编译着色器"]])
    out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
    check("超时返回空", out, "")
    check("超时问题保留", any("15 分钟" in p for p in probs))

    print("\n[桌面助手自己失败（relay.log 5356-5397：「桌面助手 … 超时没有结果」）→ 未知，不当成「没按钮」]")
    reset(); probs = []
    d = FakeDesk([("error", "超时")])
    out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
    check("终末地：返回空", out, "")
    check("终末地：问题说读屏失败和原因", any("读屏失败" in p and "超时" in p for p in probs), True)
    check("终末地：没说成「没读到按钮」", any("没读到按钮" in p for p in probs), False)
    check("终末地：什么都没点", d.clicks, [])
    check("终末地：没杀 Games.exe", [e for e in events if e[0] == "kill" and "Games.exe" in e], [])
    # ── 2026-10-15: the disk-space confirm that nothing clicked ──
    SPACE_DIALOG = [
        Line("控]面板", 90, 61, 48, 11), Line("Clashfor", 163, 61, 52, 10), Line("Windows", 163, 78, 53, 10),
        # whole-screen pass
        Line("-所需空间：", 749, 475, 77, 12), Line("-剩余空间：", 749, 501, 77, 12),
        Line("-补丁&72G", 760, 540, 68, 11), Line("1&99G（包衤卜丁：872G）", 840, 477, 178, 13),
        Line("1409G", 840, 503, 56, 11),
        # launcher-window pass (2x crop, mapped back to the screen)
        Line("系统提示", 929, 416, 64, 16), Line("-所需空间：18．99G（包台补丁：872G)", 749, 474, 269, 15),
        Line("剩空间：140．59G", 766, 500, 131, 13), Line("-补丁&72G", 760, 539, 68, 11),
    ]
    CONFIRM_BOX = (968, 587, 1170, 626)


    class DialogLauncher:
        """The real launcher: 「更新游戏」 opens the confirm, and the confirm stays on screen
    until a click lands inside 「确认」; then it downloads, then shows 「开始游戏」.
    `button_works=False` is a launcher whose 「确认」 does nothing."""

        def __init__(self, dialog_first=False, button_works=True):
            self.state = "dialog" if dialog_first else "update"
            self.button_works = button_works
            self.clicks = []
            self.downloading = 0

        def read(self, focus=None, settle_ms=0):
            if focus == "Endfield":
                lines = [Line("点击任意位置继续", 900, 900, 160, 20)]
            elif self.state == "update":
                lines = [Line("更新游戏", 1380, 790, 90, 20)]
            elif self.state == "dialog":
                lines = list(SPACE_DIALOG)
            elif self.state == "downloading" and self.downloading < 2:
                self.downloading += 1
                lines = [Line("正在下载 45%", 700, 790, 120, 20)]
            else:
                lines = [Line("开始游戏", 1380, 790, 90, 20)]
            events.append(("read", focus, tuple(ln.text for ln in lines)))
            return Screen(lines, Path("shot-x.png"))

        def click_text(self, text, focus=None):
            # The agent finds the text in its own OCR of the screen: 「确认」 is never read.
            ok = (text == "更新游戏" and self.state == "update") or \
                 (text == "开始游戏" and self.state == "downloading")
            if text == "更新游戏" and ok:
                self.state = "dialog"
            self.clicks.append(text)
            events.append(("click", text, ok))
            return ok

        def click(self, x, y, focus=None):
            self.clicks.append((x, y))
            hit = CONFIRM_BOX[0] <= x <= CONFIRM_BOX[2] and CONFIRM_BOX[1] <= y <= CONFIRM_BOX[3]
            events.append(("click", (x, y), True))
            if hit and self.button_works and self.state == "dialog":
                self.state = "downloading"
            return True


    def confirm_hits(d):
        return [c for c in d.clicks if isinstance(c, tuple)
                and CONFIRM_BOX[0] <= c[0] <= CONFIRM_BOX[2] and CONFIRM_BOX[1] <= c[1] <= CONFIRM_BOX[3]]


    print("\n[10-15 终末地：点「更新游戏」后弹「系统提示」（所需空间）→ 点「确认」，不干等 40 分钟]")
    reset(); probs = []
    d = DialogLauncher()
    out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
    check("「确认」点在按钮里", len(confirm_hits(d)), 1)
    check("没报「40 分钟内没等到」", [p for p in probs if "没等到" in p], [])
    check("等到开始游戏前没杀 Games.exe", [e for e in before_first_click("kill") if "Games.exe" in e], [])
    check("报了更新", out, "终末地 客户端已通过启动器更新")

    print("\n[10-15 终末地：上一轮留下的「系统提示」一打开就在 → 点「确认」，不当成没读到按钮去杀启动器]")
    reset(); probs = []
    d = DialogLauncher(dialog_first=True)
    out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
    check("「确认」点在按钮里", len(confirm_hits(d)), 1)
    check("没报没读到按钮", [p for p in probs if "没读到按钮" in p], [])
    check("没点「更新游戏」", "更新游戏" in d.clicks, False)
    check("报了更新", out, "终末地 客户端已通过启动器更新")

    print("\n[10-15 终末地：「确认」点了也不走 → 点三次就报问题带截图，不干等，不杀启动器]")
    reset(); probs = []
    d = DialogLauncher(button_works=False)
    out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
    check("返回空", out, "")
    check("点了三次「确认」", len(confirm_hits(d)), 3)
    check("问题说「系统提示」还在、带截图", any("系统提示" in p and "shot-x.png" in p for p in probs))
    check("没等满 40 分钟", sum(slept) < 2400, True)
    check("没杀 Games.exe", [e for e in events if e[0] == "kill" and "Games.exe" in e], [])

    print("\n[认不出的启动器画面 → 报问题，但不杀启动器（可能在用别的字下载）]")
    reset(); probs = []
    d = FakeDesk([["-以％36．。6．78678967", "么"]])
    gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
    check("没杀 Games.exe", [e for e in events if e[0] == "kill" and "Games.exe" in e], [])
    print("\nPASS" if not fails else f"\nFAILED: {fails}")


def _part_procs_wmi():
    """procs.python_processes on the machine as it was after 2026-10-10 16:05.

16:05:10 the relay's DispatchWithEvents generated pywin32's early-bound wrapper
of the WMI scripting library. From then on every Win32_Process row came back as
an early-bound SWbemObject: `row.ProcessId` raised AttributeError, the process
table was unreadable, the 16:14:07 boot self-check went red and the keeper never
attached its handle to AUTO-MAS. Reproduced on the machine 16:40 (AttributeError
"ISWbemObject ... has no attribute 'ProcessId'", then "Win32 exception occurred
releasing IUnknown" for the rows the traceback had kept past CoUninitialize).

The fakes below behave the same way: rows without the attributes, only
Properties_; and every COM object records whether it is still alive when
CoUninitialize runs (the 16:27 retry crashed pythonservice.exe that way).

    Formerly test_procs_wmi.py.
    """
    import gc
    import logging
    import types
    import weakref

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import procs


    class _ComError(Exception):
        def __init__(self, hresult):
            super().__init__(hresult, "fake", None, None)
            self.hresult = hresult


    _alive = weakref.WeakSet()
    _leaked = []          # objects still alive at a CoUninitialize


    class _Com:
        def __init__(self):
            _alive.add(self)


    class _Prop(_Com):
        def __init__(self, value):
            super().__init__()
            self.Value = value


    class _EarlyBoundRow(_Com):
        """An early-bound SWbemObject: the class's properties only through Properties_."""

        def __init__(self, pid, cmd):
            super().__init__()
            self._p = {"ProcessId": pid, "CommandLine": cmd}

        def Properties_(self, name):  # noqa: N802 - COM's name
            if name not in self._p:
                raise _ComError(-2147352567)          # 0x80020009, as on the machine
            return _Prop(self._p[name])


    class _Result(_Com):
        def __init__(self, rows, fail_at=None):
            super().__init__()
            self.rows, self.fail_at = rows, fail_at

        def __iter__(self):
            for i, r in enumerate(self.rows):
                if i == self.fail_at:
                    raise _ComError(-2147217358)      # 0x80041032 WBEM_E_CALL_CANCELLED
                yield r


    plan = []             # per try: "ok" | "cancel"


    class _Services(_Com):
        def ExecQuery(self, q):  # noqa: N802 - COM's name
            step = plan.pop(0) if plan else "ok"
            rows = [_EarlyBoundRow(5088, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"),
                    _EarlyBoundRow(2076, r"C:\Program Files\Python314\python.exe x.py")]
            return _Result(rows, fail_at=0 if step == "cancel" else None)


    def _co_uninit():
        gc.collect()
        _leaked.extend(type(o).__name__ for o in list(_alive))


    sys.modules["pythoncom"] = types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=_co_uninit)
    client = types.SimpleNamespace(GetObject=lambda moniker: _Services())
    sys.modules["win32com"] = types.SimpleNamespace(client=client)
    sys.modules["win32com.client"] = client


    class _Logs(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)


    logs = _Logs()
    procs.log.addHandler(logs)
    procs.log.setLevel(logging.DEBUG)
    slept = []
    procs._sleep = slept.append

    print("[16:05 之后那台机器：每一行都是早绑定对象，只能从 Properties_ 读]")
    rows = procs.python_processes()
    check("读得到两行", rows, [(5088, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"),
                             (2076, r"C:\Program Files\Python314\python.exe x.py")])
    check("反初始化时没有活着的 COM 对象", _leaked, [])
    check("没报警", [r for r in logs.records if r.levelno >= logging.WARNING], [])

    print("\n[一次失败后读到：等一下再试，不进群，但记一条自己好了（「自愈待查」红项）]")
    # Until 2026-10-12 the retry that read the list was an INFO line only: a fault that
    # fixed itself with no red item (audit 10-12 #7). errwatch.recovered() writes it.
    from ark_relay.features.alarm import errwatch
    plan[:] = ["cancel", "ok"]
    logs.records.clear()
    rows = procs.python_processes()
    check("第二次读到", rows is not None and len(rows), 2)
    check("中间等了一次", slept, [procs.PAUSE_SECONDS])
    check("失败那次带错误码", any("0x80041032" in r.getMessage() for r in logs.records))
    warned = [r for r in logs.records if r.levelno >= logging.WARNING]
    check("一条警告，标了自己好了（不进群，写红项）",
          [(getattr(r, errwatch.RECOVERED, False), "0x80041032" in r.getMessage()) for r in warned], [(True, True)])
    check("失败那次也没有对象活过反初始化", _leaked, [])

    print("\n[每次都失败：只报一条警告，带错误码；同一段没恢复不再报]")
    plan[:] = ["cancel"] * 6
    logs.records.clear()
    slept.clear()
    check("读不到返回 None", procs.python_processes(), None)
    check("试了 3 次、中间等 2 次", slept, [procs.PAUSE_SECONDS] * 2)
    warns = [r.getMessage() for r in logs.records if r.levelno >= logging.WARNING]
    check("一条警告", len(warns), 1)
    check("警告带错误码", bool(warns) and "0x80041032" in warns[0])
    check("说得出为什么", "0x80041032" in procs.last_failure())
    check("第二轮仍读不到也不再报", (procs.python_processes(), len([r for r in logs.records if r.levelno >= logging.WARNING])), (None, 1))
    check("异常没有让对象活过反初始化", _leaked, [])

    print("\n[自检调用时不另报：自检自己报那一条]")
    procs._state["warned"] = False
    plan[:] = ["cancel"] * 3
    logs.records.clear()
    check("warn=False 读不到也返回 None", procs.python_processes(warn=False), None)
    check("不报警", [r for r in logs.records if r.levelno >= logging.WARNING], [])
    plan[:] = ["cancel"] * 3
    check("自检报过的那段，看门狗再读不到也不重复报",
          (procs.python_processes(), [r for r in logs.records if r.levelno >= logging.WARNING]), (None, []))

    print("\n[没有 pywin32 的机器：一次就停，不等]")
    del sys.modules["pythoncom"]
    sys.modules["pythoncom"] = None
    slept.clear()
    check("返回 None", procs.python_processes(warn=False), None)
    check("没等", slept, [])

    print()
    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_relaunch():
    """After an update or a rollback the relay starts again within seconds, not with the
watchdog's next check.

2026-10-11 (review round 7 #22, round 2 #13): restart_soon ran `cmd /c timeout /t 3 &
schtasks /run` detached. timeout.exe needs console input and returns at once in a
detached process, so the task run came while the relay still held the task and was
ignored (MultipleInstances IgnoreNew); only the watchdog brought it back, up to 30 s
later. Now packaging/launch.py `relaunch` waits for the relay's mutex to go before it
runs the task, and runs it again if the relay does not show.

2026-10-11 (review round 8 #23): switch.py stop() - before an upgrade, at uninstall and
at revert - stopped the watchdog and the relay but not this helper; within two minutes
of an update it started the relay again under the installer. The helper now gives up
once a watchdog it saw running stops, and still restarts when the watchdog was already
down (package_smoke stage 4c).

    Formerly test_relaunch.py.
    """
    import re

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(RELAY))
    sys.path.insert(0, str(ROOT / "packaging"))

    import launch
    import pkg_layout


    class Machine:
        """A fake clock, the relay's mutex and the task. `exits_after`: polls until the old
    relay is gone (None = never). `ignored_runs`: task runs that start nothing."""

        def __init__(self, exits_after, ignored_runs=0, alive_now=True, watchdog=None):
            self.t = 0.0
            # watchdog: what each query answers, in order, the last one repeating
            # (False = running, True = stopped / stopping, None = not installed).
            self.watchdog = list(watchdog or [False])
            self.wd_queries = 0
            self.polls = 0
            self.exits_after = exits_after
            self.ignored = ignored_runs
            self.alive = alive_now
            self.runs = []                  # clock time of each task run
            self.alive_at_run = []

        def clock(self):
            return self.t

        def sleep(self, s):
            self.t += s

        def running(self):
            self.polls += 1
            if self.alive and self.exits_after is not None and self.polls > self.exits_after:
                self.alive = False
            return self.alive

        def watchdog_stopping(self):
            self.wd_queries += 1
            return self.watchdog.pop(0) if len(self.watchdog) > 1 else self.watchdog[0]

        def run_task(self):
            self.runs.append(self.t)
            self.alive_at_run.append(self.alive)
            if self.alive:
                return                      # IgnoreNew: the running one stays, nothing new
            if self.ignored:
                self.ignored -= 1
                return
            self.alive = True
            self.exits_after = None


    def relaunch(m):
        return launch.relaunch(running=m.running, run_task=m.run_task, sleep=m.sleep, clock=m.clock,
                               watchdog_stopping=m.watchdog_stopping)


    print("[the old relay takes 6 s to exit: one task run, after it is gone]")
    m = Machine(exits_after=12)
    check("result", relaunch(m), 0)
    check("task runs", len(m.runs), 1)
    check("relay was gone at the run", m.alive_at_run, [False])
    check("run came within a second of the exit", m.runs[0] <= 6.5, True)

    print("[the first task run starts nothing: it is run again]")
    m = Machine(exits_after=4, ignored_runs=1)
    check("result", relaunch(m), 0)
    check("task runs", len(m.runs), 2)
    check("second run within TASK_UP_S of the first", m.runs[1] - m.runs[0] <= launch.TASK_UP_S + 0.5, True)

    print("[the relay is already gone when the helper starts (rollback stops it first)]")
    m = Machine(exits_after=0)
    check("result", relaunch(m), 0)
    check("task run at once", m.runs, [0.0])

    print("[the old relay never exits: no task run, exit 1]")
    m = Machine(exits_after=None)
    check("result", relaunch(m), 1)
    check("task runs", m.runs, [])
    check("gave up after EXIT_WAIT_S", launch.EXIT_WAIT_S <= m.t <= launch.EXIT_WAIT_S + 1, True)

    print("[no task run starts anything: exit 2 after TASK_TRIES]")
    m = Machine(exits_after=0, ignored_runs=99)
    check("result", relaunch(m), 2)
    check("task runs", len(m.runs), launch.TASK_TRIES)

    print("[the watchdog starts it first: the helper's run is a no-op and it reports 0]")
    m = Machine(exits_after=2)
    real_run = m.run_task


    def watchdog_first():
        m.alive = True                      # the watchdog's run won the race
        m.exits_after = None
        real_run()


    m.run_task = watchdog_first
    check("result", relaunch(m), 0)

    print("[upgrade / uninstall / revert: stop() stops the watchdog, then the relay: no start, exit 3]")
    m = Machine(exits_after=12, watchdog=[False, False, False, True])
    check("result", relaunch(m), 3)
    check("task runs", m.runs, [])

    print("[the watchdog is stopped once the relay is already gone: no start, exit 3]")
    m = Machine(exits_after=0, watchdog=[False, True])
    check("result", relaunch(m), 3)
    check("task runs", m.runs, [])

    print("[stop-pending after the first run took nothing: no second run, exit 3]")
    m = Machine(exits_after=0, ignored_runs=1, watchdog=[False, False, True])
    check("result", relaunch(m), 3)
    check("task runs", len(m.runs), 1)

    print("[the watchdog was already stopped when the helper started (package_smoke 4c): restart]")
    m = Machine(exits_after=4, watchdog=[True])
    check("result", relaunch(m), 0)
    check("task runs", len(m.runs), 1)

    print("[no watchdog installed: restart]")
    m = Machine(exits_after=4, watchdog=[None])
    check("result", relaunch(m), 0)
    check("task runs", len(m.runs), 1)

    print("[the watchdog runs throughout: asked before every run]")
    m = Machine(exits_after=0, ignored_runs=99)
    check("result", relaunch(m), 2)
    check("queries: one at start, one before each run", m.wd_queries, 1 + launch.TASK_TRIES)

    print("[launch.py's watchdog name matches the service's]")
    watchdog_src = (ROOT / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8")
    check("watchdog", launch.WATCHDOG, re.search(r'^NAME = "(.+)"$', watchdog_src, re.M).group(1))

    print("[restart_soon starts launch.py relaunch with the package's pythonw, detached]")
    app = Path("C:/Program Files/ArkRelay")
    calls = []


    def popen(cmd, creationflags=0):
        calls.append((cmd, creationflags))


    pkg_layout.restart_soon(app, popen=popen)
    check("one process", len(calls), 1)
    cmd, flags = calls[0]
    check("command", cmd, [str(app / "runtime" / "python" / "pythonw.exe"), str(app / "launch.py"),
                           "relaunch"])
    check("no cmd.exe / timeout.exe in it", any("timeout" in c or c.lower().startswith("cmd") for c in cmd),
          False)
    if sys.platform == "win32":
        import subprocess
        check("detached", bool(flags & subprocess.DETACHED_PROCESS), True)
        check("own process group", bool(flags & subprocess.CREATE_NEW_PROCESS_GROUP), True)

    print("[a job that forbids breakaway: started again without that flag]")
    calls.clear()


    def popen_no_breakaway(cmd, creationflags=0):
        calls.append(creationflags)
        if len(calls) == 1 and sys.platform == "win32":
            raise PermissionError(5, "Access is denied")


    pkg_layout.restart_soon(app, popen=popen_no_breakaway)
    if sys.platform == "win32":
        import subprocess
        check("two tries", len(calls), 2)
        check("second without breakaway", bool(calls[1] & subprocess.CREATE_BREAKAWAY_FROM_JOB), False)
    else:
        check("started", len(calls), 1)

    print("[launch.py's names match app_main's]")
    import app_main
    check("mutex", launch.MUTEX, app_main.MUTEX)
    check("task", launch.MAIN_TASK, pkg_layout.MAIN_TASK)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_rollback_stop_failed():
    """`app_main.py rollback` says so and exits 1 when the relay does not stop.

Audit s24 F4 (10-13): rollback() switched current.txt, printed `current -> <prev>`,
ignored stop()'s result and returned 0. When the relay did not stop within stop()'s
40 s, `launch.py relaunch` waited its 120 s and gave up, and the version rolled away
from ran on until the next restart while current.txt and the pin named the earlier one.
Now a failed stop prints what is true (current.txt changed, the relay still running,
the earlier version starts at the next restart), skips the restart helper, exits 1.

    Formerly test_rollback_stop_failed.py.
    """
    import contextlib
    import io

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    import app_main
    import pkg_layout


    def rollback_with(stop_result):
        restarts = []
        real = pkg_layout.app_root, pkg_layout.rollback, pkg_layout.restart_soon, app_main.stop
        pkg_layout.app_root = lambda _here: Path("/app")
        pkg_layout.rollback = lambda _app: "100"
        pkg_layout.restart_soon = lambda app: restarts.append(app)
        app_main.stop = lambda: stop_result
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = app_main.rollback()
        finally:
            pkg_layout.app_root, pkg_layout.rollback, pkg_layout.restart_soon, app_main.stop = real
        return code, out.getvalue(), restarts


    print("[the relay stops]")
    code, out, restarts = rollback_with(0)
    check("exit 0", code, 0)
    check("says current -> 100", "current -> 100" in out, True)
    check("restart helper started", len(restarts), 1)

    print("[the relay does not stop]")
    code, out, restarts = rollback_with(1)
    check("exit 1", code, 1)
    check("does not claim the switch took effect", "current -> 100" in out, False)
    check("says the relay did not stop", "did not stop" in out, True)
    check("says when 100 starts", "next restart" in out, True)
    check("no restart helper (it would wait 120 s and give up)", restarts, [])

    if fails:
        print("FAIL:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_unknown_process_list():
    """A process list that cannot be read is "unknown", never a yes (review of 2026-10-07, item 2).

procs.py records the incident this guards against: from 2026-08-28 to 09-17 the
keeper read "cannot tell" as "alive" and went blind for three weeks - no
revival, no alarm, and the evening queue of the 17th was lost. Two probes still
turned "cannot tell" into a definite answer; the one left here
(gameupdate_games._alive / wait_ready went with the WuWa launcher update on
2026-10-12, AUTO-MAS item 10b):

* automas_procs._installer_running answered True ("an installer is on screen") when
  tasklist failed, and _revive then logged 「安装程序正在运行」 - a sentence that
  was not true. Now it answers None; _revive still keeps its hands off (killing
  a window mid-install is the worse mistake, see test_verify.py) but says
  what actually happened: the process list could not be read.

    Formerly test_unknown_process_list.py.
    """
    import subprocess
    import types

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


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))

    import boot_stages
    from ark_relay.features.host import automas_keeper, automas_procs


    def _boom(*a, **k):
        raise OSError("tasklist is gone")


    # ------------------------------------------------------------ service.py
    print("[automas_procs._installer_running：进程表读不到 → None，不是「有安装程序」]")
    orig_run = automas_procs.subprocess.run
    automas_procs.subprocess.run = _boom
    check("读不到 → None", automas_procs._installer_running(), None)
    automas_procs.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"AUTO-MAS-Setup.exe 1 Console", b"")
    check("有安装程序 → True", automas_procs._installer_running(), True)
    automas_procs.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"explorer.exe 4 Console", b"")
    check("没有 → False", automas_procs._installer_running(), False)
    automas_procs.subprocess.run = orig_run


    class _Log:
        def __init__(self): self.rows = []
        def info(self, msg, *a, **k): self.rows.append(("INFO", msg % a if a else msg))
        def warning(self, msg, *a, **k): self.rows.append(("WARNING", msg % a if a else msg))
        def exception(self, msg, *a, **k): self.rows.append(("ERROR", msg % a if a else msg))


    class _Notifier:
        def __init__(self): self.sent = []
        def send(self, title, body, **k): self.sent.append(title); return []


    print("\n[_revive：进程表读不到时不动 AUTO-MAS，但说的是「读不到」而不是「安装程序在跑」]")
    k = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
    k.log, k.notifier = _Log(), _Notifier()
    k.revive_failures = 0
    k.revive_alerted = False
    k.shell_only_since = None
    k.shell_grace_noted = False
    k.gone = None
    revived = []
    saved = (automas_procs._installer_running, automas_procs._automas_shell_running, boot_stages._revive_automas)
    automas_procs._installer_running = lambda: None
    automas_procs._automas_shell_running = lambda: False
    boot_stages._revive_automas = lambda: revived.append(1)
    k._revive(1000.0)
    check("不去重新打开（装到一半被关掉更糟）", revived, [])
    said = " ".join(m for _, m in k.log.rows)
    check("没说「安装程序正在运行」", "安装程序正在运行" in said, False)
    check("说了进程表读不到", "读不到" in said, True)
    check("没有待定的退出时这一句是 WARNING（不是静默）", any(lv == "WARNING" for lv, _ in k.log.rows), True)
    automas_procs._installer_running, automas_procs._automas_shell_running, boot_stages._revive_automas = saved


def _part_wait_network():
    """On a cold boot the relay starts before Windows has DNS. Measured
2026-08-21 21:20:19 - one second after service start, all four update doors
answered `[Errno 11001] getaddrinfo failed`, and the boot-window update was
abandoned before the doors were ever reachable.

2026-09-08：这个测试原来真去解析 raw.githubusercontent.com、真 sleep，跑一次 12 秒，
是全套里最慢的一个（第二名的两倍），而且没网就挂。现在用假时钟和假解析器——
不碰网络、瞬间跑完，等待时长也变成可精确断言的。

    Formerly test_wait_network.py.
    """
    import socket, types

    # service.py imports pywin32, which does not exist on this machine. Load just
    # the function under test by exec'ing its source in a namespace of its own.
    SRC = (Path(__file__).resolve().parents[1] / "service.py").read_text(encoding="utf-8")
    start = SRC.index("def _wait_for_network")
    end = SRC.index("class ArkRelayService")


    class Clock:
        """假时钟：sleep 只是把指针往前拨，不真等。`gaps` is the time slept between two
    DNS lookups (the lookup stub calls lookup())."""

        def __init__(self):
            self.now = 1000.0
            self.slept = []
            self.gaps = []
            self._since = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, s):
            self.slept.append(s)
            self._since += s
            self.now += s

        def lookup(self):
            if self._since:
                self.gaps.append(self._since)
            self._since = 0.0

        def end(self):
            self.lookup()
            return self.gaps


    def load(clock, stopping=lambda: False):
        """按给定时钟装一份被测函数。它自己 `import socket`，所以解析器要打真模块。
    `stopping` stands in for boot_stages._stop_requested (the stop request)."""
        ns = {"time": types.SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep),
              "boot_stages": types.SimpleNamespace(_stop_requested=stopping)}
        exec(compile(SRC[start:end], "service.py", "exec"), ns)
        return ns["_wait_for_network"]


    class Log:
        def __init__(self): self.lines = []
        def info(self, msg, *a): self.lines.append(("info", msg % a if a else msg))
        def warning(self, msg, *a): self.lines.append(("warn", msg % a if a else msg))


    real = socket.getaddrinfo
    FAKE_OK = [(2, 1, 6, "", ("140.82.114.4", 443))]

    try:
        print("[network already up: returns at once, says nothing]")
        socket.getaddrinfo = lambda *a, **kw: FAKE_OK
        clock, lg = Clock(), Log()
        check("returns True", load(clock)(lg, timeout=5), True)
        check("immediate", clock.slept, [])
        check("silent", lg.lines, [])

        print("\n[DNS down at first, up on the third try]")
        calls = []
        clock, lg = Clock(), Log()
        def flaky(*a, **kw):
            clock.lookup()
            calls.append(1)
            if len(calls) < 3:
                raise OSError(11001, "getaddrinfo failed")
            return FAKE_OK
        socket.getaddrinfo = flaky
        check("returns True", load(clock)(lg, timeout=30), True)
        check("kept trying", len(calls), 3)
        # Slept in one-second slices (to hear a stop); between two lookups 2 s, then 4 s.
        check("退避是 2 秒然后 4 秒", clock.end(), [2.0, 4.0])
        check("said it waited", any("DNS 还没起来" in m for _, m in lg.lines), True)
        check("said it recovered", any("网络已就绪" in m for _, m in lg.lines), True)

        print("\n[DNS never comes up: gives up inside the budget]")
        clock, lg = Clock(), Log()
        def down(*a, **kw):
            clock.lookup()
            raise OSError(11001, "getaddrinfo failed")
        socket.getaddrinfo = down
        check("returns False", load(clock)(lg, timeout=6), False)
        check("一秒都没超出预算", sum(clock.slept) <= 6.0, True)
        check("最后一次等待被预算截断，不是整轮翻倍", clock.end(), [2.0, 4.0])
        warns = [m for lv, m in lg.lines if lv == "warn"]
        check("warned", len(warns), 1)
        # service.main runs the self-update whatever this returns (audit s23 F5): the
        # warning must not say the fetch is skipped.
        check("does not claim the fetch is skipped", any("跳过取件" in m for m in warns), False)
        check("says it still tries the fetch", any("照样试一次取件" in m for m in warns), True)

        print("\n[a stop arrives during the wait: returns within a second, no warning]")
        # boot_stages.py's _stop_requested: a wait that cannot hear the stop is a hang,
        # ended by SvcStop's 15 s hard exit.
        clock, lg = Clock(), Log()
        socket.getaddrinfo = down
        stop_at = clock.now + 3.0
        check("returns False", load(clock, lambda: clock.now >= stop_at)(lg, timeout=90), False)
        check("within a second of the stop", clock.now - stop_at <= 1.0, True)
        check("no warning (a stop is not a network fault)", [lv for lv, _ in lg.lines if lv == "warn"], [])
    finally:
        socket.getaddrinfo = real


def _part_watch_handle_close():
    """watch._windows must close a dropped change handle before opening a new one.

Audit s2 F5 (2026-10-13): when WaitForSingleObject / FindNextChangeNotification
failed, the loop dropped the handle and called FindFirstChangeNotificationW again
without FindCloseChangeNotification, leaking one kernel handle per rebuild.
kernel32 is faked here so the Windows path runs on any machine.

    Formerly test_watch_handle_close.py.
    """
    import ctypes
    import threading
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import watch


    class Fn:
        """A kernel32 function: restype / argtypes are set on it, calls go to `body`."""

        def __init__(self, body):
            self.body = body

        def __call__(self, *a):
            return self.body(*a)


    opened: list = []
    closed: list = []
    second_open = threading.Event()
    park = threading.Event()        # never set: the rebuilt handle just waits


    def first(path, sub, flags):
        h = len(opened) + 100
        opened.append(h)
        if len(opened) == 2:
            second_open.set()
        return h


    def wait(h, ms):
        if h == 100:
            return 0xFFFFFFFF       # WAIT_FAILED: the first handle drops
        park.wait()
        return 0


    k = types.SimpleNamespace(
        FindFirstChangeNotificationW=Fn(first),
        WaitForSingleObject=Fn(wait),
        FindNextChangeNotification=Fn(lambda h: 1),
        FindCloseChangeNotification=Fn(lambda h: closed.append(h) or 1),
    )
    ctypes.windll = types.SimpleNamespace(kernel32=k)
    watch.time = types.SimpleNamespace(sleep=lambda s: None)

    print("[the first handle drops; it is closed before the rebuild opens another]")
    check("watcher started", watch._windows("C:/x", threading.Event()), True)
    check("a second handle was opened", second_open.wait(5), True)
    check("the dropped handle was closed", closed, [100])

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")


if __name__ == "__main__":
    sys.exit(run_parts([_part_apphost_covers_service, _part_estop_verifies, _part_farm_launcher, _part_hidden_launch_quoting, _part_launcher_states, _part_procs_wmi, _part_relaunch, _part_rollback_stop_failed, _part_unknown_process_list, _part_wait_network, _part_watch_handle_close]))
