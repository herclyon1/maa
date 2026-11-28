"""Host process table, WMI process watcher, and Windows service watchdog."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


class _Any:
    """Stands in for any pywin32 attribute: callable, subclassable, truthy."""
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    """A pywin32 module that is not there: every public name is an _Any."""
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


def _time_setter(*mods):
    """service.py's code now lives in several modules, each reading its own `time`; the setter swaps it in all."""
    def set_time(t):
        for m in mods:
            m.time = t
    return set_time


def _module(name, **attrs):
    """Put a module with exactly these attributes in sys.modules (run_parts takes it out again)."""
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


def _part_apphost_covers_service():  # noqa: C901
    """app_main.AppHost has every attribute the code it runs reads off it."""
    import ast

    RELAY = Path(__file__).resolve().parents[1]
    MODULES = {"app_main": "app_main.py", "service": "service.py", "boot_stages": "boot_stages.py",
               "automas_keeper": "ark_relay/features/automas_keeper.py",
               "phone_channel": "ark_relay/features/phone.py"}

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
    for fn in ("service.main", "automas_keeper._loop", "boot_stages._stage_inbox_and_phone",
               "phone_channel._start_phone_channel", "app_main._end_session_window", "app_main._stop_requests"):
        require(f"walk reaches {fn}", fn in reached)
    gaps = missing(trees)
    require("AppHost lacks nothing", not gaps, "; ".join(f"{a} (via {p})" for a, p in sorted(gaps.items())))
    has, borrowed = host_has(trees["app_main"])
    require("AppHost borrows ArkRelayService.main (else this test reads the wrong thing)", "main" in borrowed)

    print("[a host attribute AppHost lacks is caught wherever the host travels]")
    for mod, fn, param in (("automas_keeper", "_loop", "svc"),
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
          "_not_on_host" not in borrowed_only(plant(trees, "automas_keeper", "_loop", "svc", "_not_on_host")))


def _part_estop_verifies():
    """The red button on the phone must not say 「已停一切」 unless it checked."""
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import commands
    # estop() reads its stop steps and _mas from redbutton, so the fakes go there.
    from ark_relay.features import redbutton

    print("[要杀要查的名单里必须有鸣潮的三个真名——08-26 的假确认就漏在这里]")
    for exe in ("Wuthering Waves.exe", "Client-Win64-Shipping.exe", "KRSDKExternal.exe",
                "ok-ww.exe", "MAA.exe", "MaaEnd.exe", "Endfield.exe", "dnplayer.exe"):
        check(f"名单含 {exe}", exe in redbutton._ESTOP_EXES, True)
    print("  ✓ 终末地启动器 Games.exe 也在" if "Games.exe" in redbutton._ESTOP_EXES else "")
    check("终末地启动器也在", "Games.exe" in redbutton._ESTOP_EXES, True)

    class Rig:
        """Stands in for the four actions: API stop, kill, who is alive, which AUTO-MAS tasks are unfinished.
        """

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
    from ark_relay.features import okww_overlay as _ov
    from ark_relay.features import snapshot as _snap
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
    """The farm launcher must not leave a console window on top of the game."""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import os
    import subprocess

    from ark_relay.features import echofarm

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


def _part_hidden_launch_quoting():  # noqa: C901
    """The windowless launch builds a PowerShell command that survives a path with a space."""
    import subprocess
    from pathlib import Path, PureWindowsPath

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import preupdate as C

    def ps_statements(script: str) -> list[list[str]]:
        """Statements of a PowerShell command line, each a list of argument-mode tokens."""
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
    cmd = captured_command(PureWindowsPath(r"C:\Tools\pwsh\pwsh.exe"),
                           tmpdir() / "desktop", ("-File", "agent.ps1"))
    got = action_params(cmd)
    check("no loose word", got["loose"], [])
    check("arguments round-trip", win_argv(got.get("-Argument", ""))[-3:],
          [r"C:\Tools\pwsh\pwsh.exe", "-File", "agent.ps1"])

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
    """Launcher screens the update flows must not misread (audit 2026-10-06)."""
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import gameupdate_games as gug
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


def _part_endfield_start_retry():
    """2026-11-25 Endfield v1.7: 「校验中」 is busy; missed 「开始游戏」 click retries quietly."""
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.desktop import Line, Screen
    from ark_relay.features import gameupdate_games as gug

    slept, clock = [], {"t": 0.0}

    def fake_sleep(s):
        slept.append(s)
        clock["t"] += s

    gug.time = types.SimpleNamespace(sleep=fake_sleep, monotonic=lambda: clock["t"])
    gug._spawn = lambda exe, cwd=None: True
    gug.kill = lambda *names: True

    class FakeDesk:
        def __init__(self, screens):
            self.screens = list(screens)
            self.clicks = []

        def read(self, focus=None, settle_ms=0):
            spec = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
            if isinstance(spec, tuple) and spec[0] == "missing":
                return Screen([], Path("shot-x.png"), focus_missing=True)
            return Screen([Line(t, 100, 100 + 30 * i, 80, 20) for i, t in enumerate(spec)], Path("shot-x.png"))

        def click_text(self, text, focus=None):
            self.clicks.append(text)
            return True

    EF = (Path("Endfield.exe"), Path("Launcher.exe"))

    print("[11-25 终末地：启动器「校验中」算正常忙碌，不当没认出]")
    slept.clear(); clock["t"] = 0.0; probs = []
    d = FakeDesk([["鹰角启动器", "校验中"], ["开始游戏"], ["点击任意位置继续"]])
    out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
    check("报了更新", out, "终末地 客户端已通过启动器更新")
    check("没有问题", probs, [])

    print("\n[11-25 终末地：第一次「开始游戏」点偏没起来 → 查到启动器还在就补点，不用干等 15 分钟]")
    slept.clear(); clock["t"] = 0.0; probs = []
    d = FakeDesk([
        ["更新游戏"], ["开始游戏"],
        ("missing", ["开始游戏"]),
        ("missing", ["开始游戏"]),
        ["开始游戏"],
        ["点击任意位置继续"],
    ])
    out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
    check("补点后成功", out, "终末地 客户端已通过启动器更新")
    check("一共点了 2 次「开始游戏」", d.clicks.count("开始游戏"), 2)
    check("没有问题", probs, [])

    print("\n[11-25 终末地：补点两次后仍一直没游戏窗口 → 提前收口报一条问题，不干等 15 分钟]")
    slept.clear(); clock["t"] = 0.0; probs = []

    class StuckStartDesk(FakeDesk):
        def read(self, focus=None, settle_ms=0):
            if focus == "Endfield":
                return Screen([], Path("shot-x.png"), focus_missing=True)
            return super().read(focus=focus, settle_ms=settle_ms)

    d = StuckStartDesk([["更新游戏"], ["开始游戏"]])
    out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
    check("返回空", out, "")
    check("点了 3 次「开始游戏」后收口", d.clicks.count("开始游戏"), 3)
    check("问题说清点了 3 次仍没窗口", any("点了 3 次" in p and "没等到游戏窗口" in p for p in probs), True)
    check("没干等满 15 分钟", sum(slept) < 900, True)


def _part_endfield_launcher_quiet():
    """Endfield launcher missing-window handling: quiet restart probe and download respawn."""
    import json
    import logging
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import desktop as dk
    from ark_relay.core.desktop import Desktop
    from ark_relay.features import gameupdate_games as gug

    slept, clock = [], {"t": 0.0}

    def fake_sleep(s):
        slept.append(s)
        clock["t"] += s

    gug.time = types.SimpleNamespace(sleep=fake_sleep, monotonic=lambda: clock["t"])
    gug.kill = lambda *names: True
    spawns = []
    gug._spawn = lambda exe, cwd=None: spawns.append(exe.name) or True
    EF = (Path("Endfield.exe"), Path("Launcher.exe"))

    def make_desk(responses):
        """Real Desktop backed by scripted agent JSON responses so WARNINGs are exercised."""
        queue = list(responses)

        def spawn_agent(exe, cwd, args):
            res = Path(args[-1])
            ans = queue.pop(0) if len(queue) > 1 else queue[0]
            res.write_text(json.dumps(ans, ensure_ascii=False), encoding="utf-8")
            return True

        return Desktop(tmpdir() / "state", spawn=spawn_agent, timeout=5)

    def ok_ocr(*words):
        return {"ok": True, "clicked": [], "log": ["focus: Games 「Launcher」"],
                "ocr": [{"text": w, "x": 100, "y": 100 + 30 * i, "w": 80, "h": 20} for i, w in enumerate(words)]}

    def ok_click(word):
        return {"ok": True, "clicked": [[140, 110]], "ocr": [], "log": [f"click_text: 点了「{word}」"]}

    def miss(focus):
        return {"ok": True, "focus_missing": True, "clicked": [], "ocr": [],
                "log": [f"focus: 没有 {focus} 的窗口", "skip click: focus missing"]}

    warns = []

    class _W(logging.Handler):
        def emit(self, rec):
            if rec.levelno >= logging.WARNING:
                warns.append(rec.getMessage())

    wh = _W()
    dk.log.addHandler(wh)
    try:
        print("[请重启游戏：首次试探点击启动器缺窗（缩进托盘）→ 静默不发 WARNING，拉回后正常点上]")
        slept.clear(); clock["t"] = 0.0; spawns.clear(); warns.clear(); probs = []
        d = make_desk([
            ok_ocr("更新游戏"),
            ok_click("更新游戏"),
            ok_ocr("开始游戏"),
            ok_click("开始游戏"),
            ok_ocr("资源初始化更新完成，请重启游戏", "确认"),
            ok_click("确认"),
            miss("Games"),
            ok_click("开始游戏"),
            ok_ocr("点击任意位置继续"),
        ])
        out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
        check("重启路径更新成功", out, "终末地 客户端已通过启动器更新")
        check("拉回了一次启动器（开头 + 重启后）", len(spawns), 2)
        check("试探缺窗不发桌面读屏/点击 WARNING", warns, [])
        check("没有问题", probs, [])

        print("\n[请重启游戏：拉回后第二次点击启动器仍缺窗 → 照常发 WARNING]")
        slept.clear(); clock["t"] = 0.0; spawns.clear(); warns.clear(); probs = []
        d = make_desk([
            ok_ocr("更新游戏"),
            ok_click("更新游戏"),
            ok_ocr("开始游戏"),
            ok_click("开始游戏"),
            ok_ocr("资源初始化更新完成，请重启游戏", "确认"),
            ok_click("确认"),
            miss("Games"),
            miss("Games"),
            ok_ocr("点击任意位置继续"),
        ])
        out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
        check("第二次正式点击仍缺窗时照常发 1 条 WARNING", len(warns), 1)
        check("仍等到了标题画面", out, "终末地 客户端已通过启动器更新")

        print("\n[下载等待循环：连续 2 帧缺窗不刷 WARNING，并 _spawn(launcher) 拉回后恢复完成]")
        slept.clear(); clock["t"] = 0.0; spawns.clear(); warns.clear(); probs = []
        d = make_desk([
            ok_ocr("更新游戏"),
            ok_click("更新游戏"),
            miss("Games"),
            miss("Games"),
            ok_ocr("正在下载 50%"),
            ok_ocr("开始游戏"),
            ok_click("开始游戏"),
            ok_ocr("点击任意位置继续"),
        ])
        out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
        check("拉回后下载完成", out, "终末地 客户端已通过启动器更新")
        check("连续 2 帧缺窗触发拉回启动器（开头 + 拉回）", len(spawns), 2)
        check("下载等待缺窗不发 WARNING", warns, [])
        check("没有问题", probs, [])

        print("\n[下载等待循环：仅缺窗 1 帧就恢复 → 不发 WARNING、不额外 _spawn]")
        slept.clear(); clock["t"] = 0.0; spawns.clear(); warns.clear(); probs = []
        d = make_desk([
            ok_ocr("更新游戏"),
            ok_click("更新游戏"),
            miss("Games"),
            ok_ocr("正在下载 80%"),
            ok_ocr("开始游戏"),
            ok_click("开始游戏"),
            ok_ocr("点击任意位置继续"),
        ])
        out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
        check("正常完成", out, "终末地 客户端已通过启动器更新")
        check("单帧缺窗不多拉启动器", len(spawns), 1)
        check("不发 WARNING", warns, [])

        print("\n[下载等待循环：持续缺窗拉回达上限后不再狂拉，超时照常报问题]")
        slept.clear(); clock["t"] = 0.0; spawns.clear(); warns.clear(); probs = []
        d = make_desk([
            ok_ocr("更新游戏"),
            ok_click("更新游戏"),
            miss("Games"),
        ])
        out = gug.update_endfield(d, *EF, budget_s=600, poll_s=30, problems=probs, sleep=fake_sleep)
        check("超时返回空", out, "")
        check("拉回次数有上限（开头 1 + 最多拉回 _EF_RESPAWN_TRIES）", len(spawns), 1 + gug._EF_RESPAWN_TRIES)
        check("循环内不刷桌面读屏 WARNING", warns, [])
        check("超时仍记问题", any("没等到「开始游戏」" in p for p in probs), True)
    finally:
        dk.log.removeHandler(wh)


def _part_procs_wmi():
    """procs.python_processes on the machine as it was after 2026-10-10 16:05."""
    import gc
    import logging
    import types
    import weakref

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import desktop as procs

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

        def Properties_(self, name):  # noqa: N802
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
        def ExecQuery(self, q):  # noqa: N802
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
    procs._log_procs.addHandler(logs)
    procs._log_procs.setLevel(logging.DEBUG)
    slept = []
    procs._sleep = slept.append

    print("[16:05 之后那台机器：每一行都是早绑定对象，只能从 Properties_ 读]")
    rows = procs.python_processes()
    check("读得到两行", rows, [(5088, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py"),
                             (2076, r"C:\Program Files\Python314\python.exe x.py")])
    check("反初始化时没有活着的 COM 对象", _leaked, [])
    check("没报警", [r for r in logs.records if r.levelno >= logging.WARNING], [])

    print("\n[一次失败后读到：瞬态重试记 INFO（带错误码），既不刷群也不进日报]")
    plan[:] = ["cancel", "ok"]
    logs.records.clear()
    rows = procs.python_processes()
    check("第二次读到", rows is not None and len(rows), 2)
    check("中间等了一次", slept, [procs.PAUSE_SECONDS])
    check("失败那次带错误码", any("0x80041032" in r.getMessage() for r in logs.records))
    check("瞬态重试恢复无 WARNING/ERROR，记在 INFO",
          ([r for r in logs.records if r.levelno >= logging.WARNING],
           any(r.levelno == logging.INFO and "0x80041032" in r.getMessage() for r in logs.records)),
          ([], True))
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


def _part_relaunch():
    """After an update or a rollback the relay starts again within seconds, not with the
watchdog's next check.
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


def _part_rollback_stop_failed():
    """`app_main.py rollback` says so and exits 1 when the relay does not stop."""
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


def _part_unknown_process_list():
    """A process list that cannot be read is "unknown", never a yes (review of 2026-10-07, item 2).
    """
    import subprocess

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))

    import boot_stages
    from ark_relay.features import automas_keeper, automas_keeper as automas_procs

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
    FAKE_OK = [(2, 1, 6, "", ("119.29.29.29", 443))]

    try:
        print("[network already up: returns at once, says nothing, uses domestic probe host]")
        probed_hosts = []
        def ok_lookup(host, port, *a, **kw):
            probed_hosts.append((host, port))
            return FAKE_OK
        socket.getaddrinfo = ok_lookup
        clock, lg = Clock(), Log()
        check("returns True", load(clock)(lg, timeout=5), True)
        check("immediate", clock.slept, [])
        check("silent", lg.lines, [])
        check("国内域名探针（绝不用 raw.githubusercontent.com）",
              bool(probed_hosts) and all("github" not in h.lower() for h, _ in probed_hosts), True)

        print("\n[DNS down at first, up on the third try]")
        calls = []
        clock, lg = Clock(), Log()
        def flaky(host, port, *a, **kw):
            clock.lookup()
            calls.append(host)
            if len(calls) < 3:
                raise OSError(11001, "getaddrinfo failed")
            return FAKE_OK
        socket.getaddrinfo = flaky
        check("returns True", load(clock)(lg, timeout=30), True)
        check("kept trying", len(calls), 3)
        check("多国内探针轮换且零 github 域名",
              len(set(calls)) >= 2 and all("github" not in h.lower() for h in calls), True)
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
    """watch._windows must close a dropped change handle before opening a new one."""
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


def _part_procwatch_cancel():  # noqa: C901
    """The process-start listener never leaves a live WMI subscription behind when the relay exits.
    """
    import gc
    import logging
    import threading
    import time
    import types
    import weakref

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    # ---------- a fake kernel: waitable objects and one STA message queue ----------

    COND = threading.Condition()
    MESSAGES = []          # callbacks COM would deliver to the listener's STA as window messages

    class Waitable:
        def __init__(self, name):
            self.name, self.signalled = name, False

        def set(self):
            with COND:
                self.signalled = True
                COND.notify_all()

    def post(fn):
        """WMI calling back into the sink: delivered only when the STA pumps."""
        with COND:
            MESSAGES.append(fn)
            COND.notify_all()

    w32event = _Stub("win32event")
    w32event.WAIT_OBJECT_0, w32event.INFINITE, w32event.QS_ALLINPUT = 0, 0xFFFFFFFF, 0x04FF
    set_events = []

    def _create_event(sa, manual, initial, name):
        return Waitable("event")

    def _set_event(h):
        set_events.append(h)
        if isinstance(h, Waitable):
            h.set()

    waits = []

    def _msg_wait(handles, wait_all, ms, mask):
        """MsgWaitForMultipleObjects: the first signalled handle's index, or len(handles) for a message."""
        waits.append((threading.current_thread().name, ms, mask))
        deadline = time.time() + 10      # a hung test fails instead of hanging
        with COND:
            while time.time() < deadline:
                for i, h in enumerate(handles):
                    if isinstance(h, Waitable) and h.signalled:
                        return w32event.WAIT_OBJECT_0 + i
                if MESSAGES:
                    return w32event.WAIT_OBJECT_0 + len(handles)
                COND.wait(0.05)
        raise RuntimeError("fake MsgWaitForMultipleObjects: nothing happened in 10 s")

    w32event.CreateEvent, w32event.SetEvent, w32event.MsgWaitForMultipleObjects = _create_event, _set_event, _msg_wait

    calls = []      # (what, thread name) in order

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: calls.append(("CoInitialize", threading.current_thread().name))
    pythoncom.CoUninitialize = lambda: calls.append(("CoUninitialize", threading.current_thread().name))

    def _pump():
        with COND:
            todo = MESSAGES[:]
            MESSAGES.clear()
        for fn in todo:
            fn()
        return 0

    pythoncom.PumpWaitingMessages = _pump

    class com_error(Exception):   # pywintypes' own name, which the code matches on
        pass

    pythoncom.com_error = com_error

    # WMI scripting: SWbemServices.ExecNotificationQueryAsync with an SWbemSink.
    sinks = []
    cancel_block = [None]     # a threading.Event Cancel waits on, to make it hang

    class FakeSink:
        """The makepy SWbemSink class DispatchWithEvents puts in front of the user's handler class."""

        def __init__(self):
            self.cancelled = 0
            self.query = None

        def Cancel(self):  # noqa: N802
            calls.append(("Cancel", threading.current_thread().name))
            self.cancelled += 1
            if cancel_block[0] is not None:
                cancel_block[0].wait(5)

    subscribed = threading.Event()
    script = []      # what each ExecNotificationQueryAsync does: None = succeed, an exception = raise

    class Services:
        def ExecNotificationQueryAsync(self, sink, query):  # noqa: N802
            calls.append(("ExecNotificationQueryAsync", threading.current_thread().name))
            step = script.pop(0) if script else None
            if step is not None:
                raise step
            sink.query = query
            sinks.append(sink)
            subscribed.set()

    client = types.ModuleType("win32com.client")
    client.GetObject = lambda moniker: Services()

    def _dispatch_with_events(progid, user_class):
        calls.append((f"DispatchWithEvents {progid}", threading.current_thread().name))
        cls = type("COMEventClass", (FakeSink, user_class), {})
        inst = cls()
        if "__init__" in user_class.__dict__:
            user_class.__init__(inst)
        return inst

    client.DispatchWithEvents = _dispatch_with_events
    pkg = types.ModuleType("win32com")
    pkg.client = client

    w32api = _Stub("win32api")
    host = {"proc": None}

    def _open_process(access, inherit, pid):
        host["proc"] = Waitable(f"process {pid}")
        host["opened"] = (access, pid)
        return host["proc"]

    w32api.OpenProcess = _open_process
    w32api.CloseHandle = lambda h: calls.append(("CloseHandle", threading.current_thread().name))
    # FormatMessage(0x800706BE) on a Chinese Windows; anything else is not in the system table.
    w32api.FormatMessage = lambda code: "远程过程调用失败。\r\n" if code == -2147023170 else (_ for _ in ()).throw(
        Exception("no text"))
    w32con = _Stub("win32con")
    w32con.SYNCHRONIZE = 0x00100000

    FAKES = {"win32event": w32event, "pythoncom": pythoncom, "win32com": pkg, "win32com.client": client,
             "win32api": w32api, "win32con": w32con}
    for name in ("win32serviceutil", "win32service", "win32file", "servicemanager", "win32security",
                 "win32ts", "win32profile", "wmi", "win32process"):
        FAKES[name] = _Stub(name)
    saved = {k: sys.modules.get(k) for k in [*FAKES, "service"]}
    sys.modules.update(FAKES)
    sys.modules.pop("service", None)
    import service  # a fresh copy built on the fakes above
    from ark_relay.features import automas_keeper, automas_keeper as dirwatch, automas_keeper as mainloop, procwatch, procwatch as shutdown_signs, procwatch as wmi_diag
    from ark_relay.features import errwatch
    from ark_relay.core import texts

    set_time = _time_setter(service, shutdown_signs, procwatch, dirwatch, automas_keeper, mainloop)

    class FastTime:
        """time for the listener: monotonic is real plus whatever sleep skipped; sleep returns at once."""

        def __init__(self):
            self.skipped = 0.0
            self.slept = []
            self.gate = None      # a threading.Event sleep waits on (real time), to hold the listener in its backoff

        def monotonic(self):
            return time.monotonic() + self.skipped

        def time(self):
            return time.time() + self.skipped

        def sleep(self, s):
            self.slept.append(s)
            if self.gate is not None:
                self.gate.wait(5)
            self.skipped += max(0.0, s)

    class Records(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def at(self, level):
            return [r.getMessage() for r in self.records if r.levelno == level]

    orig = (procwatch.time, wmi_diag._wmi_hosts, wmi_diag._uptime, wmi_diag._wmi_scm_events,
            errwatch.system_shutting_down, getattr(service, "_winmgmt_pid", None))
    wmi_diag._wmi_hosts = lambda: "winmgmt pid 1234; WmiPrvSE pids 5,6"
    wmi_diag._uptime = lambda: "1:00:00"
    wmi_diag._wmi_scm_events = lambda: "SCM winmgmt: none in 5 min"
    wmi_diag._winmgmt_pid = lambda: 1234
    errwatch.system_shutting_down = lambda: False

    def start(name):
        """A fresh listener through _start_process_watch, its real thread running; returns (alive, evt, rec, clock)."""
        sinks.clear()
        calls.clear()
        set_events.clear()
        waits.clear()
        script.clear()
        subscribed.clear()
        cancel_block[0] = None
        with COND:
            MESSAGES.clear()
        clock = FastTime()
        set_time(clock)
        rec = Records()
        log = logging.getLogger(f"ark.test.procwatch_cancel.{name}")
        log.propagate = False
        log.setLevel(logging.DEBUG)
        log.addHandler(rec)
        alive, evt = {"ok": True}, object()
        ok = procwatch._start_process_watch(evt, alive, log)
        check("the listener started", ok, True)
        return alive, evt, rec, clock

    def thread_alive():
        return any(t.name == "proc-watch" and t.is_alive() for t in threading.enumerate())

    def wait_for(pred, secs=3.0):
        end = time.time() + secs
        while time.time() < end and not pred():
            time.sleep(0.01)
        return pred()

    def names(what):
        return [c for c in calls if c[0] == what]

    try:
        print("[1. the stop cancels the live subscription and the listener has ended before stop returns]")
        alive, evt, rec, clock = start("stop")
        check("subscribed asynchronously, with an SWbemSink", wait_for(lambda: len(sinks) == 1))
        check("the query is the python.exe start trace",
              bool(sinks) and sinks[0].query == "SELECT * FROM Win32_ProcessStartTrace WHERE ProcessName = 'python.exe'")
        check("the listener waits on messages without a timeout (no polling)",
              wait_for(lambda: bool(waits)) and waits[0] == ("proc-watch", w32event.INFINITE, w32event.QS_ALLINPUT))
        alive["watch"].stopping()
        check("Cancel was called exactly once", sinks[0].cancelled if sinks else 0, 1)
        check("on the listener's own thread (the sink lives in its apartment)",
              names("Cancel"), [("Cancel", "proc-watch")])
        check("the listener has ended by the time stopping() returns", thread_alive(), False)
        order = [c[0] for c in calls if c[0] in ("Cancel", "CoUninitialize") and c[1] == "proc-watch"]
        check("COM uninitialised on that thread, after the cancel",
              (order, names("CoUninitialize")[-1:]), (["Cancel", "CoUninitialize"], [("CoUninitialize", "proc-watch")]))
        check("one INFO line says the subscription was cancelled",
              [m for m in rec.at(logging.INFO) if "已取消" in m] != [], True)
        check("no WARNING or ERROR for a clean stop",
              [r.getMessage() for r in rec.records if r.levelno >= logging.WARNING], [])
        alive["watch"].stopping()
        check("a second stop call does nothing more", sinks[0].cancelled if sinks else 0, 1)
        gone = weakref.ref(sinks[0]) if sinks else (lambda: "no sink")
        sinks.clear()
        gc.collect()
        check("nothing holds the sink any more (every COM reference dropped)", gone(), None)

        print("\n[2. a dropped subscription (OnCompleted 0x800706BE) is released and resubscribed as before]")
        alive, evt, rec, clock = start("drop")
        wait_for(lambda: len(sinks) == 1)
        first = sinks[0]
        post(lambda: first.OnCompleted(-2147023170, None, None))
        check("resubscribed", wait_for(lambda: len(sinks) == 2))
        check("the dead subscription was cancelled before the next one was made",
              [c[0] for c in calls if c[0] in ("Cancel", "ExecNotificationQueryAsync")][:3],
              ["ExecNotificationQueryAsync", "Cancel", "ExecNotificationQueryAsync"])
        # The backoff counts from the failure: _failed's wait for the power-off signal
        # (GOING_DOWN_SETTLE_SECONDS) plus whatever is left of the first 5 s.
        check("after the backoff the drop asked for (5 s, counted from the drop)",
              round(sum(clock.slept), 1), max(shutdown_signs.GOING_DOWN_SETTLE_SECONDS, 5.0))
        drop = [m for m in rec.at(logging.INFO) if "程序启动通知断了" in m]
        check("the drop is the same INFO line, with Windows' words and code",
              bool(drop) and "远程过程调用失败，0x800706BE" in drop[0].splitlines()[0])
        check("its diag line carries the scode", bool(drop) and "scode 0x800706BE" in drop[0])
        check("back by itself: one plain WARNING pushed to group",
              wait_for(lambda: len(rec.at(logging.WARNING)) == 1), True)
        check("alive again", alive["ok"], True)
        alive["watch"].stopping()
        check("the stop cancels the second one", sinks[1].cancelled, 1)
        check("and the listener ended", thread_alive(), False)

        print("\n[3. OnObjectReady wakes the main loop]")
        alive, evt, rec, clock = start("event")
        wait_for(lambda: len(sinks) == 1)
        s = sinks[0]
        post(lambda: s.OnObjectReady(object(), None))
        post(lambda: s.OnObjectReady(object(), None))
        check("evt set once per process start", wait_for(lambda: set_events.count(evt) == 2), True)
        check("the events are counted", wait_for(lambda: alive["watch"].sub and alive["watch"].sub["events"] == 2), True)
        check("delivered on the listener's thread only", {w[0] for w in waits}, {"proc-watch"})
        alive["watch"].stopping()
        check("ended", thread_alive(), False)

        print("\n[4. the WMI service host exiting under the subscription is a drop]")
        alive, evt, rec, clock = start("host")
        wait_for(lambda: len(sinks) == 1)
        check("the WMI service host was opened for SYNCHRONIZE", host.get("opened"), (0x00100000, 1234))
        host["proc"].set()
        check("resubscribed after it", wait_for(lambda: len(sinks) == 2))
        drop = [m for m in rec.at(logging.INFO) if "程序启动通知断了" in m]
        check("the drop says the service stopped, in plain words", bool(drop) and "发这项通知的服务停了" in drop[0].splitlines()[0])
        check("the diag names the host pid", bool(drop) and "winmgmt host pid 1234" in drop[0])
        alive["watch"].stopping()
        check("ended", thread_alive(), False)

        print("\n[5. a stop during the backoff: nothing to cancel, nothing subscribed after it]")
        alive, evt, rec, clock = start("backoff")
        wait_for(lambda: len(sinks) == 1)
        clock.gate = threading.Event()
        first = sinks[0]
        post(lambda: first.OnCompleted(-2147023170, None, None))
        check("in the backoff", wait_for(lambda: len(clock.slept) == 1))
        t0 = time.time()
        alive["watch"].stopping()
        check("stopping() did not wait for the backoff", time.time() - t0 < 1.0)
        clock.gate.set()
        check("the listener then ends", wait_for(lambda: not thread_alive()))
        check("without subscribing again", len(sinks), 1)

        print("\n[6. a cancel that hangs past the bound: one WARNING, the stop goes on]")
        service_bound = getattr(service, "CANCEL_WAIT_SECONDS", None)
        procwatch.CANCEL_WAIT_SECONDS = 0.3
        alive, evt, rec, clock = start("hang")
        wait_for(lambda: len(sinks) == 1)
        cancel_block[0] = threading.Event()
        t0 = time.time()
        alive["watch"].stopping()
        took = time.time() - t0
        check("stopping() returned within the bound", took < 1.5)
        warns = rec.at(logging.WARNING)
        check("one WARNING (not an ERROR)", (len(warns), rec.at(logging.ERROR)), (1, []))
        check("its first line is plain Chinese", bool(warns) and texts.plain(warns[0].splitlines()[0]) == [], True)
        cancel_block[0].set()
        wait_for(lambda: not thread_alive())
        if service_bound is not None:
            procwatch.CANCEL_WAIT_SECONDS = service_bound

        print("\n[7. a stop while the WMI hosts are being read (tasklist, up to 25 s): nothing to wait for, no WARNING]")
        alive, evt, rec, clock = start("hosts")
        wait_for(lambda: len(sinks) == 1)
        reading, gate, reads = threading.Event(), threading.Event(), []

        def slow_hosts():
            # The 1st read is the drop's diag line (_failed); the 2nd is cycle's, before the resubscribe.
            reads.append(1)
            if len(reads) == 2:
                reading.set()
                gate.wait(5)
            return "winmgmt pid 1234; WmiPrvSE pids 5,6"

        wmi_diag._wmi_hosts = slow_hosts
        first = sinks[0]
        post(lambda: first.OnCompleted(-2147023170, None, None))
        check("the listener is reading the hosts before resubscribing", reading.wait(3))
        t0 = time.time()
        alive["watch"].stopping()
        check("stopping() did not wait", time.time() - t0 < 1.0)
        check("no WARNING (nothing was subscribed)",
              [m for m in rec.at(logging.WARNING) if "没取消完" in m], [])
        gate.set()
        check("the listener then ends without subscribing again",
              (wait_for(lambda: not thread_alive()), len(sinks)), (True, 1))
        wmi_diag._wmi_hosts = lambda: "winmgmt pid 1234; WmiPrvSE pids 5,6"

        print("\n[8. DispatchWithEvents / makepy fails on the machine: the failed-subscribe path, the service goes on]")
        real_dwe = client.DispatchWithEvents
        tries = []

        def broken_dwe(progid, user_class):
            # pywin32's own words when it cannot build the makepy support (win32com/client/__init__.py)
            tries.append(1)
            raise TypeError("This COM object can not automate the makepy process - please run makepy manually for this object")

        client.DispatchWithEvents = broken_dwe
        alive, evt, rec, clock = start("makepy")
        check("it keeps retrying with the backoff", wait_for(lambda: len(tries) >= 3))
        check("nothing subscribed, nothing to cancel", (len(sinks), names("Cancel")), (0, []))
        first_info = [m for m in rec.at(logging.INFO) if "订不上" in m]
        check("first: INFO 「订不上」, not passed off as a Windows error",
              bool(first_info) and "不是系统返回的错误" in first_info[0].splitlines()[0]
              and "makepy" in first_info[0])
        check("the main loop falls back to the liveness check", alive["ok"], False)
        check("evt fired so the main loop sees it", evt in set_events)
        check("the WMI host handle is closed again each time", len(names("CloseHandle")) >= 3)
        t0 = time.time()
        alive["watch"].stopping()
        check("the stop does not wait (nothing live)", time.time() - t0 < 1.0)
        # The skipped backoff sleeps put the clock past OUTAGE_ALARM_SECONDS here, so the
        # one push is the 10-minute one; inside 10 minutes it is the at-stop one instead.
        errors = rec.at(logging.ERROR)
        check("one ERROR (pushed) for the whole outage, as for any failed subscribe",
              [("分钟没重新订上" in m or "到中继停下时还没重新订上" in m) for m in errors], [True])
        check("no cancel WARNING", [m for m in rec.at(logging.WARNING) if "没取消完" in m], [])
        check("the listener ends", wait_for(lambda: not thread_alive()))
        client.DispatchWithEvents = real_dwe
    finally:
        (procwatch.time, wmi_diag._wmi_hosts, wmi_diag._uptime, wmi_diag._wmi_scm_events,
         errwatch.system_shutting_down) = orig[:5]
        if orig[5] is not None:
            wmi_diag._winmgmt_pid = orig[5]
        errwatch._stopping.clear()
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _part_procwatch_drop():  # noqa: C901
    """The process-start listener: a shutdown is not a fault; a real drop is INFO with its evidence and decided by whether it comes back.
    """
    import gc
    import logging
    import subprocess
    import threading
    import types
    import weakref

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    # ---------- fakes: pywin32's service framework (311, verbatim logic), WMI ----------

    w32svc = _Stub("win32service")
    w32svc.SERVICE_ACCEPT_STOP, w32svc.SERVICE_ACCEPT_PAUSE_CONTINUE, w32svc.SERVICE_ACCEPT_SHUTDOWN = 1, 2, 4
    (w32svc.SERVICE_CONTROL_STOP, w32svc.SERVICE_CONTROL_PAUSE, w32svc.SERVICE_CONTROL_CONTINUE,
     w32svc.SERVICE_CONTROL_INTERROGATE, w32svc.SERVICE_CONTROL_SHUTDOWN) = 1, 2, 3, 4, 5
    w32svc.SC_MANAGER_CONNECT, w32svc.SERVICE_QUERY_STATUS = 1, 4
    w32svc.OpenSCManager = lambda *a: "scm"
    w32svc.OpenService = lambda scm, name, access: f"svc:{name}"
    w32svc.QueryServiceStatusEx = lambda h: {"ProcessId": 1234} if h == "svc:winmgmt" else {}
    w32svc.CloseServiceHandle = lambda h: None

    class ServiceFramework:
        """GetAcceptedControls and ServiceCtrlHandlerEx as pywin32 311 has them (win32/lib/win32serviceutil.py)."""

        def GetAcceptedControls(self):  # noqa: N802
            accepted = 0
            if hasattr(self, "SvcStop"):
                accepted |= w32svc.SERVICE_ACCEPT_STOP
            if hasattr(self, "SvcPause") and hasattr(self, "SvcContinue"):
                accepted |= w32svc.SERVICE_ACCEPT_PAUSE_CONTINUE
            if hasattr(self, "SvcShutdown"):
                accepted |= w32svc.SERVICE_ACCEPT_SHUTDOWN
            return accepted

        def ServiceCtrlHandlerEx(self, control, event_type, data):  # noqa: N802
            if control == w32svc.SERVICE_CONTROL_STOP:
                return self.SvcStop()
            elif control == w32svc.SERVICE_CONTROL_PAUSE:
                return self.SvcPause()
            elif control == w32svc.SERVICE_CONTROL_CONTINUE:
                return self.SvcContinue()
            elif control == w32svc.SERVICE_CONTROL_INTERROGATE:
                return self.SvcInterrogate()
            elif control == w32svc.SERVICE_CONTROL_SHUTDOWN:
                return self.SvcShutdown()
            return None

    w32su = _Stub("win32serviceutil")
    w32su.ServiceFramework = ServiceFramework

    w32event = _Stub("win32event")
    set_events = []
    w32event.SetEvent = lambda h: set_events.append(h)
    w32event.CreateEvent = lambda *a: object()
    w32event.WAIT_OBJECT_0, w32event.INFINITE, w32event.QS_ALLINPUT = 0, 0xFFFFFFFF, 0x04FF
    # Every wait ends on "a message is waiting": the pump below then delivers the
    # subscription's next scripted callback, or raises what ends it.
    w32event.MsgWaitForMultipleObjects = lambda handles, wait_all, ms, mask: len(handles)

    pythoncom = types.ModuleType("pythoncom")
    co = {"init": 0, "uninit": 0}
    pythoncom.CoInitialize = lambda: co.__setitem__("init", co["init"] + 1)
    pythoncom.CoUninitialize = lambda: co.__setitem__("uninit", co["uninit"] + 1)
    live = []     # the SWbemSink of the subscription made last

    def _pump():
        """PumpWaitingMessages: WMI's next callback into the live sink (Source.deliver)."""
        if live:
            live[-1]._src.deliver(live[-1])
        return 0

    pythoncom.PumpWaitingMessages = _pump

    class com_error(Exception):   # pywintypes' own name, which the code matches on
        pass

    # relay.log / docs/PITFALLS.md, verbatim
    RPC_FAILED = (-2147352567, "发生意外。", (0, "SWbemEventSource", "远程过程调用失败。 ", None, 0, -2147023170), None)

    class _Stop(BaseException):
        """Ends a scenario: neither the old nor the new listener catches it."""

    class VClock:
        """time.monotonic / time.sleep on a virtual clock, with callbacks due at given moments."""

        def __init__(self):
            self.now, self.due = 1000.0, []

        def monotonic(self):
            return self.now

        def sleep(self, s):
            self.now += max(0.0, s)
            for item in [d for d in self.due if d[0] <= self.now]:
                self.due.remove(item)
                item[1]()

        def at(self, delay, fn):
            self.due.append((self.now + delay, fn))

        def time(self):
            return self.now

    class Source:
        """What WMI does with one asynchronous subscription: `events` OnObjectReady
    callbacks, then the pump raises a fresh `then()` (what ended the old
    semisynchronous NextEvent - the drop's com_error, a Python error, or _Stop).
        """
        made = []

        def __init__(self, events, then, on_raise=None):
            self.left, self.then, self.on_raise = events, then, on_raise
            Source.made.append(weakref.ref(self))

        def deliver(self, sink):
            if self.left:
                self.left -= 1
                sink.OnObjectReady(object(), None)
                return
            if self.on_raise:
                self.on_raise()
            raise self.then()

    class Sink:
        """The makepy SWbemSink class in front of the listener's handler class."""

        def Cancel(self):  # noqa: N802
            self._src = None
            if live and live[-1] is self:
                live.pop()

    class Services:
        def __init__(self, script, seen):
            self.script, self.seen = script, seen

        def ExecNotificationQueryAsync(self, sink, q):  # noqa: N802
            # Which earlier subscriptions are still referenced while this one is registered.
            self.seen.append(sum(1 for r in Source.made if r() is not None))
            step = self.script.pop(0)
            if isinstance(step, type) and issubclass(step, BaseException):
                raise step()
            if isinstance(step, tuple):
                raise com_error(*step)
            sink._src = step()
            live.append(sink)

    def make_client(script, seen):
        client = types.ModuleType("win32com.client")
        client.GetObject = lambda moniker: Services(script, seen)
        client.DispatchWithEvents = lambda progid, user_class: type("COMEventClass", (Sink, user_class), {})()
        pkg = types.ModuleType("win32com")
        pkg.client = client
        return pkg, client

    class SyncThread:
        def __init__(self, target=None, name=None, daemon=None, **kw):
            self._target = target

        def start(self):
            self._target()

    FAKES = {"win32service": w32svc, "win32serviceutil": w32su, "win32event": w32event,
             "pythoncom": pythoncom}
    for name in ("win32api", "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi"):
        FAKES[name] = _Stub(name)
    saved = {k: sys.modules.get(k) for k in [*FAKES, "win32com", "win32com.client", "service"]}
    sys.modules.update(FAKES)
    sys.modules.pop("service", None)
    import service  # a fresh copy built on the fakes above
    from ark_relay.features import automas_keeper, automas_keeper as dirwatch, automas_keeper as mainloop, procwatch, procwatch as shutdown_signs
    from ark_relay.features import errwatch
    from ark_relay.core import texts

    set_time = _time_setter(service, shutdown_signs, procwatch, dirwatch, automas_keeper, mainloop)

    orig_ssd, orig_time, orig_run = errwatch.system_shutting_down, procwatch.time, subprocess.run
    errwatch.system_shutting_down = lambda: False

    def fake_run(cmd, **kw):
        key = " ".join(cmd).lower()
        out = b""
        if "wmiprvse" in key:
            out = b'"WmiPrvSE.exe","5","Services","0","9,000 K"\r\n"WmiPrvSE.exe","6","Services","0","9,000 K"\r\n'
        return types.SimpleNamespace(stdout=out, returncode=0)

    subprocess.run = fake_run

    class Records(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def at(self, level):
            return [r for r in self.records if r.levelno == level]

        def faults(self):
            return [r for r in self.records if r.levelno >= logging.WARNING]

        def loud(self):
            """What errwatch pushes to the group: every WARNING / ERROR."""
            return self.faults()

    def stop(alive):
        """The service's stop reaching the listener (_AutomasKeeper.stopping); absent before 2026-10-06."""
        watch = alive.get("watch")
        if watch is not None and hasattr(watch, "stopping"):
            watch.stopping()

    def scenario(script, before=None):
        """Run the listener over `script` until it ends; returns (records, alive, refs seen at each subscribe)."""
        rec = Records()
        gc.collect()
        Source.made.clear()
        live.clear()
        log = logging.getLogger(f"ark.test.procwatch.{id(script)}")
        log.propagate = False
        log.setLevel(logging.DEBUG)
        log.addHandler(rec)
        seen = []
        pkg, client = make_client(script, seen)
        sys.modules["win32com"], sys.modules["win32com.client"] = pkg, client
        vt = VClock()
        scenario.vt = vt      # a stop() after the run reads the same clock (stop_on_clock)
        set_time(vt)
        if before:
            before(vt)
        alive = {"ok": True}
        real_thread = threading.Thread
        threading.Thread = SyncThread
        try:
            procwatch._start_process_watch(object(), alive, log)
        except _Stop:
            pass
        finally:
            threading.Thread = real_thread
            set_time(orig_time)
            errwatch._stopping.clear()
            errwatch._relay_poweroff[0] = lambda: False
        return rec, alive, seen

    def stop_on_clock(alive):
        """stop() on the virtual clock the scenario ran on: the drop time is on that clock."""
        set_time(scenario.vt)
        try:
            stop(alive)
        finally:
            set_time(orig_time)

    def relay_poweroff():
        """The relay itself issued the machine power-off (errwatch.relay_shutdown_issued)."""
        errwatch._relay_poweroff[0] = lambda: True

    def first(record):
        return record.getMessage().splitlines()[0]

    try:
        print("[the relay's own power-off lands 0.3 s after WMI went: INFO, not a fault]")
        rec, alive, _ = scenario([
            lambda: Source(2, lambda: com_error(*RPC_FAILED),
                           on_raise=lambda: procwatch.time.at(0.3, relay_poweroff)),
            _Stop])
        check("no ERROR or WARNING for it", [first(r) for r in rec.faults()], [])
        check("said at INFO as the relay's own power-off",
              any("不算故障" in r.getMessage() and "中继自己发出了关机命令" in r.getMessage()
                  for r in rec.at(logging.INFO)))

        print("\n[a shutdown NOT started by the relay (by hand / sc stop, 2026-09-18 02:20): pushed at the stop]")
        rec, alive, _ = scenario([
            lambda: Source(2, lambda: com_error(*RPC_FAILED),
                           on_raise=lambda: procwatch.time.at(0.3, errwatch.mark_stopping)),
            _Stop])
        stop(alive)
        check("one ERROR (reaches the group), when the service stops with it not back",
              [("到中继停下时还没重新订上" in first(r)) for r in rec.loud()], [True])
        check("not called 「not a fault」", any("不算故障" in r.getMessage() for r in rec.records), False)

        print("\n[Windows shutting down by hand (10-10 04:28:51): the power-off request came first - INFO, not pushed]")
        REAL_0427 = (fx_dir(Path(__file__), "fixtures") /
                     "system-1010-0427-manual-shutdown.xml").read_text(encoding="utf-8").splitlines()
        orig_xml = shutdown_signs._shutdown_event_xml

        def windows_shutdown():
            errwatch.mark_os_shutdown()
            errwatch.mark_stopping()

        try:
            shutdown_signs._shutdown_event_xml = lambda *a: REAL_0427
            rec, alive, _ = scenario([
                lambda: Source(2, lambda: com_error(*RPC_FAILED),
                               on_raise=lambda: procwatch.time.at(0.3, windows_shutdown)),
                _Stop])
            errwatch.mark_os_shutdown()     # scenario() clears stopping; SvcShutdown's mark stays
            stop_on_clock(alive)
            check("no ERROR or WARNING for it", [first(r) for r in rec.loud()], [])
            check("said at INFO: who asked for the shutdown and when",
                  any("不算故障" in r.getMessage() and "04:27:24" in r.getMessage() and "INS\\Administrator" in r.getMessage()
                      for r in rec.at(logging.INFO)), True)

            print("\n[Windows shutting down, but its power-off request was logged after the drop: still pushed]")
            from datetime import datetime, timedelta, timezone
            later = (datetime.now(tz=timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
            shutdown_signs._shutdown_event_xml = lambda *a: [REAL_0427[0].replace("2026-10-09T20:27:24.6019833Z", later)]
            rec, alive, _ = scenario([
                lambda: Source(2, lambda: com_error(*RPC_FAILED),
                               on_raise=lambda: procwatch.time.at(0.3, windows_shutdown)),
                _Stop])
            errwatch.mark_os_shutdown()
            stop_on_clock(alive)
            check("one ERROR, as before", [("到中继停下时还没重新订上" in first(r)) for r in rec.loud()], [True])

            print("\n[Windows shutting down, System log unreadable: pushed]")
            shutdown_signs._shutdown_event_xml = lambda *a: None
            rec, alive, _ = scenario([
                lambda: Source(2, lambda: com_error(*RPC_FAILED),
                               on_raise=lambda: procwatch.time.at(0.3, windows_shutdown)),
                _Stop])
            errwatch.mark_os_shutdown()
            stop_on_clock(alive)
            check("one ERROR", len(rec.loud()), 1)
        finally:
            shutdown_signs._shutdown_event_xml = orig_xml
            errwatch._os_shutdown.clear()

        print("\n[the relay had already issued the power-off: INFO, and the retries stay quiet]")
        rec, alive, _ = scenario([lambda: Source(0, lambda: com_error(*RPC_FAILED))] + [RPC_FAILED] * 15 + [_Stop],
                                 before=lambda vt: relay_poweroff())
        check("no ERROR or WARNING through the whole outage", [first(r) for r in rec.faults()], [])

        print("\n[the relay's power-off cancelled while the listener is still down: the outage alarms again]")

        def cancel_later(vt):
            relay_poweroff()
            vt.at(30, lambda: errwatch._relay_poweroff.__setitem__(0, lambda: False))

        rec, alive, _ = scenario([lambda: Source(0, lambda: com_error(*RPC_FAILED))] + [RPC_FAILED] * 20 + [_Stop],
                                 before=cancel_later)
        check("still down 10 minutes after the cancel: one ERROR", len(rec.at(logging.ERROR)), 1)
        rec, alive, _ = scenario([lambda: Source(0, lambda: com_error(*RPC_FAILED))] + [RPC_FAILED] * 2 + [_Stop],
                                 before=lambda vt: relay_poweroff())
        stop_on_clock(alive)      # scenario() has put relay_shutdown_issued() back to False: cancelled
        check("cancelled, then the service stops with the listener down: one ERROR at the stop", len(rec.loud()), 1)
        rec, alive, _ = scenario([lambda: Source(0, lambda: com_error(*RPC_FAILED))] + [RPC_FAILED] * 2 + [_Stop],
                                 before=lambda vt: relay_poweroff())
        relay_poweroff()
        try:
            stop_on_clock(alive)  # the power-off still under way at the stop
        finally:
            errwatch._relay_poweroff[0] = lambda: False
        check("not cancelled: nothing at the stop either", [first(r) for r in rec.loud()], [])

        def cancel_soon(vt):
            relay_poweroff()
            vt.at(3, lambda: errwatch._relay_poweroff.__setitem__(0, lambda: False))

        rec, alive, _ = scenario([lambda: Source(0, lambda: com_error(*RPC_FAILED)), lambda: Source(0, _Stop)],
                                 before=cancel_soon)
        check("cancelled, then back by itself: one plain WARNING (pushed), as for any drop",
              len(rec.loud()), 1)

        print("\n[a drop while the machine stays up (10-05 22:45:46), back by itself: pushed - why it drops is not known (2026-10-10)]")
        rec, alive, seen = scenario([
            lambda: Source(2, lambda: com_error(*RPC_FAILED)),
            RPC_FAILED, RPC_FAILED,
            lambda: Source(0, _Stop)])
        drop = [r for r in rec.at(logging.INFO) if "程序启动通知断了" in r.getMessage()]
        check("the drop is INFO, naming the fallback", bool(drop) and "120 秒" in first(drop[0])
              and "AUTO-MAS" in first(drop[0]), True)
        errors = rec.loud()
        check("exactly one WARNING, for the group", len(errors), 1)
        line = first(errors[0]) if errors else ""
        check("its first line (what the daily report quotes) is plain Chinese", texts.plain(line), [])
        check("it names Windows' error and its code", "远程过程调用失败" in line and "0x800706BE" in line, True)
        check("and how long it was down", "断过" in line and "秒" in line, True)
        msg = errors[0].getMessage() if errors else ""
        check("evidence: the scode", "scode 0x800706BE" in msg)
        check("evidence: how long the subscription lived and what it delivered", "subscription up" in msg and "2 events" in msg)
        check("evidence: relay and machine uptime", "relay up" in msg and "machine up" in msg)
        check("evidence: the WMI service and provider hosts at subscribe and now",
              "WMI hosts at subscribe [winmgmt pid 1234; WmiPrvSE pids 5,6] now [winmgmt pid 1234" in msg)
        check("no traceback object riding on the record (the push would quote English)",
              bool(errors and errors[0].exc_info and errors[0].exc_info[0]), False)
        check("the resubscribe failures are INFO",
              sum("还没重新订上" in r.getMessage() for r in rec.at(logging.INFO)), 2)
        check("the recovery is said (that one WARNING)", "已经自己重新订上" in msg)
        check("the dead subscription was released before the next one was made", seen[1:], [0, 0, 0])
        check("listener marked alive again after the recovery", alive["ok"], True)

        print("\n[WMI stays broken: one ERROR after 10 minutes, not one a minute; back later: INFO closure]")
        rec, alive, _ = scenario([lambda: Source(0, lambda: com_error(*RPC_FAILED))] + [RPC_FAILED] * 15
                                 + [lambda: Source(0, _Stop)])
        check("one ERROR: the long outage (the drop itself was INFO)", len(rec.at(logging.ERROR)), 1)
        check("it says how long", any("分钟没重新订上" in first(r) for r in rec.at(logging.ERROR)))
        check("it reads as plain Chinese", [texts.plain(first(r)) for r in rec.at(logging.ERROR)], [[]])
        check("back at last: closed at INFO (no duplicate push, no daily report)",
              (any("期间报过群" in first(r) for r in rec.at(logging.INFO)), rec.at(logging.WARNING)), (True, []))

        print("\n[cannot subscribe at all, then a Python error: both INFO, both back by themselves, both pushed, both plain]")
        rec, alive, _ = scenario([RPC_FAILED, lambda: Source(0, lambda: AttributeError("NextEvent")),
                                  lambda: Source(0, _Stop)])
        check("the first drop says it could not subscribe (INFO)",
              any("订不上" in first(r) for r in rec.at(logging.INFO)))
        errors = rec.loud()
        check("two WARNINGs for the group", len(errors), 2)
        check("the first says it could not subscribe for a while", bool(errors) and "订不上" in first(errors[0]))
        check("the second is not passed off as a Windows error",
              len(errors) > 1 and "不是系统返回的错误" in first(errors[1]) and "AttributeError" in errors[1].getMessage())
        check("both plain", [texts.plain(first(r)) for r in errors], [[], []])

        print("\n[Windows' shutdown control reaches the service (pywin32 311 framework)]")
        svc = service.ArkRelayService.__new__(service.ArkRelayService)
        check("the service accepts SERVICE_CONTROL_SHUTDOWN",
              bool(svc.GetAcceptedControls() & w32svc.SERVICE_ACCEPT_SHUTDOWN))
        stops = []
        svc.SvcStop = lambda: stops.append("stop")
        try:
            svc.ServiceCtrlHandlerEx(w32svc.SERVICE_CONTROL_SHUTDOWN, 0, None)
        except AttributeError as exc:
            print(f"    ({exc})")
        check("and stops the way `sc stop` does (SvcStop marks stopping)", stops, ["stop"])
    finally:
        errwatch.system_shutting_down = orig_ssd
        errwatch._stopping.clear()
        subprocess.run = orig_run
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _part_wmi_listener():
    import logging
    import tempfile
    import time
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    FAKES = {}
    for name in ("win32serviceutil", "win32service", "win32file", "servicemanager", "win32security",
                 "win32ts", "win32profile", "wmi", "pythoncom", "win32com", "win32com.client",
                 "win32api", "win32con", "win32process", "win32event"):
        FAKES[name] = _Stub(name)
    FAKES["win32com"].client = FAKES["win32com.client"]     # `import win32com.client` reads the attribute
    saved = {k: sys.modules.get(k) for k in [*FAKES, "service"]}
    sys.modules.update(FAKES)
    sys.modules.pop("service", None)
    import service
    from ark_relay.features import automas_keeper, automas_keeper as dirwatch, automas_keeper as mainloop, procwatch, procwatch as shutdown_signs, procwatch as wmi_diag
    from ark_relay.features import errwatch
    from ark_relay.core.config import SERVER_TZ

    set_time = _time_setter(service, shutdown_signs, procwatch, dirwatch, automas_keeper, mainloop)

    class VClock:
        def __init__(self):
            self.now = 9000.0
            self.due = []

        def monotonic(self):
            return self.now

        def sleep(self, s):
            self.now += max(0.0, s)
            for item in [d for d in self.due if d[0] <= self.now]:
                self.due.remove(item)
                item[1]()

        def at(self, delay, fn):
            self.due.append((self.now + delay, fn))

    class Records(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

        def at(self, level):
            return [r for r in self.records if r.levelno == level]

    class Pushes:
        """errwatch's notifier: what reached the group."""

        def __init__(self):
            self.sent = []

        def send(self, title, body, **k):
            self.sent.append((title, body))
            return []

    def setup(name):
        """A logger with a recorder and a real errwatch handler on a fresh state dir."""
        state = Path(tempfile.mkdtemp(prefix="wmi-listener-"))
        rec, pushes = Records(), Pushes()
        lg = logging.getLogger(f"ark.test_wmi_listener.{name}")
        lg.propagate = False
        lg.setLevel(logging.DEBUG)
        lg.addHandler(rec)
        h = errwatch.ErrorKindAlert(pushes, state_dir=state, known={}, pace=0, retry=(0.05,))
        lg.addHandler(h)
        return lg, rec, pushes, h, state

    def settle(h, pushes, want, secs=3.0):
        """Wait (real time) until errwatch has nothing left to send and `want` pushes went out."""
        end = time.time() + secs
        while time.time() < end and (h.pending() or len(pushes.sent) < want):
            time.sleep(0.02)
        time.sleep(0.1)

    def daily(state):
        return errwatch.daily_section(state, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))

    def watch(lg):
        return procwatch._ProcessWatch(object(), {"ok": True}, lg, subscribe=lambda: None)

    FAILURE = ("远程过程调用失败，0x800706BE", "hresult 0x80020009, scode 0x800706BE, source -, text 远程过程调用失败。")
    LIVE = {"at": 0.0, "events": 3, "last": None}
    orig = (procwatch.time, wmi_diag._wmi_hosts, wmi_diag._uptime, errwatch.system_shutting_down,
            wmi_diag._wmi_scm_events)
    SCM = "SCM winmgmt: 7036 08:16:44Z Windows Management Instrumentation|已停止"
    wmi_diag._wmi_scm_events = lambda: SCM
    vt = VClock()
    set_time(vt)
    wmi_diag._wmi_hosts = lambda: "winmgmt pid 1234; WmiPrvSE pids 5,6"
    wmi_diag._uptime = lambda: "1:00:00"
    errwatch.system_shutting_down = lambda: False
    try:
        print("[a drop that resubscribes by itself within 10 minutes: pushed - why it drops is not known (2026-10-10)]")
        lg, rec, pushes, h, state = setup("recovered")
        w = watch(lg)
        w.sub = dict(LIVE, at=vt.now - 120)
        w._failed(FAILURE)
        check("the drop itself is not a WARNING or ERROR",
              [r.getMessage() for r in rec.records if r.levelno >= logging.WARNING], [])
        drop = [r.getMessage() for r in rec.at(logging.INFO) if "程序启动通知断了" in r.getMessage()]
        check("the drop is an INFO line carrying its diag line", bool(drop) and "diag: hresult" in drop[0])
        vt.sleep(25)
        w._subscribed()
        warns = rec.at(logging.WARNING)
        check("resubscribed: exactly one WARNING", len(warns), 1)
        msg = warns[0].getMessage() if warns else ""
        check("it says how long it was down and why", "断过" in msg and "秒" in msg and "远程过程调用失败" in msg)
        check("it carries the diag line", "\ndiag: hresult" in msg)
        check("the diag line carries the System log's winmgmt events", SCM in msg)
        settle(h, pushes, 1)
        check("it reached the group, once", [("系统的程序启动通知断过" in b) for _, b in pushes.sent], [True])
        section = daily(state)
        check("the techlog summary lists it, in its own words", "系统的程序启动通知断过" in section)
        check("not tagged 「自己好了，只进日报」", "自己好了，只进日报" in section, False)
        check("the listener is healthy again", (w.down_since, w.fault, w.alive["ok"]), (None, None, True))
        h.close()

        print("\n[still down at OUTAGE_ALARM_SECONDS: ERROR, pushed; the resubscribe after it closes at INFO]")
        lg, rec, pushes, h, state = setup("long")
        w = watch(lg)
        w.sub = dict(LIVE, at=vt.now - 60)
        w._failed(FAILURE)
        vt.sleep(procwatch.OUTAGE_ALARM_SECONDS + 1)
        w._failed(FAILURE)
        errors = rec.at(logging.ERROR)
        check("one ERROR at the threshold", len(errors), 1)
        check("it says how many minutes", bool(errors) and "分钟没重新订上" in errors[0].getMessage())
        settle(h, pushes, 1)
        check("it reached the group", len(pushes.sent), 1)
        vt.sleep(100)
        w._failed(FAILURE)
        check("a later failed retry of the same outage is INFO", len(rec.at(logging.ERROR)), 1)
        w._subscribed()
        check("back at last: closed at INFO with 期间报过群, no duplicate WARNING",
              (rec.at(logging.WARNING), any("期间报过群" in r.getMessage() for r in rec.at(logging.INFO))),
              ([], True))
        settle(h, pushes, 1)
        check("still only the one push", len(pushes.sent), 1)
        h.close()

        print("\n[the service stops (a shutdown by hand) with the drop not back: ERROR, pushed]")
        lg, rec, pushes, h, state = setup("stopped")
        w = watch(lg)
        w.sub = dict(LIVE, at=vt.now - 60)
        w._failed(FAILURE)
        vt.sleep(30)
        w.stopping()
        errors = rec.at(logging.ERROR)
        check("one ERROR", len(errors), 1)
        check("it says it was still not back when the relay stopped",
              bool(errors) and "到中继停下时还没重新订上" in errors[0].getMessage())
        check("with the diag line", bool(errors) and "\ndiag: hresult" in errors[0].getMessage())
        settle(h, pushes, 1)
        check("it reached the group", len(pushes.sent), 1)
        w.stopping()
        check("a second stop call says nothing more", len(rec.at(logging.ERROR)), 1)
        h.close()

        print("\n[the stop arrives while _failed still waits for the power-off signal: pushed too]")
        lg, rec, pushes, h, state = setup("stop-in-wait")
        w = watch(lg)
        w.sub = dict(LIVE, at=vt.now - 60)
        vt.at(2.0, w.stopping)
        w._failed(FAILURE)
        check("the stop pushed it as an ERROR (with the diag known so far)",
              [("到中继停下时" in r.getMessage(), "\ndiag: " in r.getMessage()) for r in rec.at(logging.ERROR)],
              [(True, True)])
        h.close()

        print("\n[a listener that never subscribed at all: same rules]")
        lg, rec, pushes, h, state = setup("never")
        w = watch(lg)
        w._failed(FAILURE)
        check("INFO 订不上", [r.levelno for r in rec.records if "订不上" in r.getMessage()], [logging.INFO])
        w._subscribed()
        check("subscribed later: one WARNING for the group", len(rec.at(logging.WARNING)), 1)
        h.close()

        print("\n[the relay's own power-off: INFO, nothing pushed, nothing in the report]")
        lg, rec, pushes, h, state = setup("poweroff")
        errwatch._relay_poweroff[0] = lambda: True
        w = watch(lg)
        w.sub = dict(LIVE, at=vt.now - 60)
        w._failed(FAILURE)
        w.stopping()
        check("no WARNING or ERROR", [r.getMessage() for r in rec.records if r.levelno >= logging.WARNING], [])
        check("INFO says it is the power-off", any("不算故障" in r.getMessage() for r in rec.at(logging.INFO)))
        check("the power-off drop does not read the System log",
              [SCM in r.getMessage() for r in rec.records], [False] * len(rec.records))
        errwatch._relay_poweroff[0] = lambda: False
        settle(h, pushes, 0)
        check("nothing pushed", pushes.sent, [])
        check("nothing in the daily report", daily(state), "")
        h.close()

        print("\n[_start_process_watch hands the listener to the keeper (alive['watch'])]")
        import pythoncom  # the stub installed above
        pythoncom.CoInitialize = lambda: None
        pythoncom.CoUninitialize = lambda: None
        threads = []
        real_thread = procwatch.threading.Thread
        procwatch.threading.Thread = lambda target, name, daemon: types.SimpleNamespace(
            start=lambda: threads.append(name))
        alive = {"ok": True}
        try:
            ok = procwatch._start_process_watch(object(), alive, logging.getLogger("ark.test_host").getChild("start"))
        finally:
            procwatch.threading.Thread = real_thread
        check("started", (ok, threads), (True, ["proc-watch"]))
        check("the listener is reachable for stopping()", isinstance(alive.get("watch"), procwatch._ProcessWatch))
    finally:
        (procwatch.time, wmi_diag._wmi_hosts, wmi_diag._uptime, errwatch.system_shutting_down,
         wmi_diag._wmi_scm_events) = orig
        errwatch._relay_poweroff[0] = lambda: False
        for key, v in saved.items():
            if v is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = v


def _part_procnames():
    import re

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import config as C

    ROOT = Path(__file__).resolve().parents[2]

    def text(rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    print("[名单本身：三个游戏、模拟器、三个脚本，一个都不能少]")
    for name in ("Endfield.exe", "Client-Win64-Shipping.exe", "dnplayer.exe",
                 "MAA.exe", "MaaEnd.exe", "ok-ww.exe"):
        check(f"名单里有 {name}", name in C.BUSY_PROCS, True)
    check("OK-WW 真身按命令行认", (C.OKWW_CMDLINE, "pythonw.exe" in C.PYTHON_HOSTS),
          ("ok-ww", True))

    print("\n[已经从这台机器上删掉的东西，不许还留在任何一份名单里]")
    # Only a quoted occurrence counts, i.e. the name actually being matched on.
    # Mentioning it in prose is allowed and useful: saying why it was removed beats
    # erasing every trace of it.
    for rel in ("relay/ark_relay/core/config.py", 
                "scripts/mac/watch-run.sh", "scripts/mac/estop.sh"):
        body = text(rel)
        check(f"{rel} 不再拿 MuMuPlayer 当判据",
              ('"MuMuPlayer' in body or "'MuMuPlayer" in body), False)

    print("\n[各处的名单都看得见鸣潮本体和模拟器——看不见就等于报「闲着」]")
    must = ("Client-Win64-Shipping", "dnplayer")
    for rel in ("scripts/mac/watch-run.sh",):
        body = text(rel)
        for m in must:
            check(f"{rel} 认得 {m}", m in body, True)

    est = text("scripts/mac/estop.sh")
    check("急停脚本认得雷电", "dnplayer" in est, True)
    check("急停脚本按命令行找 OK-WW 真身", "ok-ww" in est and "CommandLine" in est, True)

    print("\n[手机页那份进程表由同一个名单生成]")
    snap = text("relay/ark_relay/features/snapshot.py")
    check("snapshot 用的是 config 里那一份", "BUSY_PROCS" in snap, True)
    check("snapshot 不再自己写死名字",
          re.search(r'for n in \("AUTO-MAS", "MAA"', snap) is None, True)

    print("\n[派发闸门那份也得看得见鸣潮和模拟器]")
    dg = text("scripts/windows/dispatch_guard.py")
    check("派发闸门认得鸣潮本体", "Client-Win64-Shipping.exe" in dg, True)
    check("派发闸门认得雷电", "dnplayer.exe" in dg, True)
    check("派发闸门按命令行找 OK-WW", "pythonw.exe" in dg, True)


def _part_watchdog_copy():
    """The watchdog's three group-bot messages read as plain words, like every relay push."""
    import ast

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay"))

    from ark_relay.core.texts import plain

    src = (ROOT / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8")
    texts = {t.id: ast.literal_eval(n.value) for n in ast.parse(src).body
             if isinstance(n, ast.Assign) for t in n.targets
             if isinstance(t, ast.Name) and t.id.startswith(("ALERT_", "REASON_HEAD", "REASON_NONE"))}
    doc = (ROOT / "docs" / "NOTIFICATIONS.md").read_text(encoding="utf-8")

    bad = 0
    if set(texts) != {"ALERT_DOWN", "ALERT_NOBODY", "ALERT_CRASHLOOP", "REASON_HEAD", "REASON_NONE"}:
        print("FAIL: expected ALERT_DOWN, ALERT_NOBODY, ALERT_CRASHLOOP and the two REASON_ lines, found",
              sorted(texts))
        bad += 1
    for name, text in texts.items():
        filled = text.format(n=3, s=30, m=30)
        problems = plain(filled)
        title = filled.split("\n", 1)[0]
        # The REASON_ lines are appended to an alert, not alerts of their own.
        row = name.startswith("REASON_") or f"| {title} | group |" in doc
        print(f"{'ok' if not problems and row else 'FAIL'} {name}: {problems or 'plain'}; table row: {row}")
        bad += bool(problems) or not row
    import watchdog_guard as G

    guard_alerts = {k: v for k, v in vars(G).items() if k.startswith("ALERT_")}
    if set(guard_alerts) != {"ALERT_GAVE_UP", "ALERT_CANNOT_LOOK"}:
        print("FAIL: expected ALERT_GAVE_UP and ALERT_CANNOT_LOOK in watchdog_guard, found", sorted(guard_alerts))
        bad += 1
    for name, text in guard_alerts.items():
        # Filled the way failed() fills it; the reason is one _start writes.
        problems = plain(text % (3, "开到一半自己停了"))
        print(f"{'ok' if not problems else 'FAIL'} watchdog_guard.{name}: {problems or 'plain'}")
        bad += bool(problems)
    guard_src = (ROOT / "relay" / "watchdog_guard.py").read_text(encoding="utf-8")
    logged = [c.value for c in ast.walk(ast.parse(guard_src))
              if isinstance(c, ast.Constant) and isinstance(c.value, str) and "\n" not in c.value
              and any("\u4e00" <= ch <= "\u9fff" for ch in c.value)]   # docstrings have line breaks
    for text in logged:
        problems = plain(text.replace("%d", "3").replace("%s", "原因").replace("{START_WAIT_S}", "45"))
        if problems:
            print(f"FAIL watchdog_guard copy {text!r}: {problems}")
            bad += 1
    print(f"{'ok' if logged else 'FAIL'} watchdog_guard: {len(logged)} Chinese strings read")
    bad += not logged
    print("\n" + ("FAILED" if bad else "all checks passed"))
    sys.exit(1 if bad else 0)


def _part_watchdog_crashloop():
    """The watchdog says why the relay does not start, and rings when it keeps crashing."""
    import os
    import time

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(ROOT / "packaging"))
    sys.path.insert(0, str(ROOT / "packaging" / "watchdog"))

    DATA = tmpdir()
    os.environ["ARK_HOME"] = str(DATA)

    class _PyError(Exception):
        pass

    SHUTTING = {"on": 0}
    _module("pywintypes", error=_PyError)
    _module("servicemanager", LogMsg=lambda *a: None, EVENTLOG_INFORMATION_TYPE=4, PYS_SERVICE_STARTED=1)
    _module("win32api", GetSystemMetrics=lambda i: SHUTTING["on"], CloseHandle=lambda h: None)
    _module("win32event", CreateEvent=lambda *a: None, SetEvent=lambda e: None, WaitForSingleObject=lambda *a: 0,
            WAIT_TIMEOUT=258)
    _module("win32service", SERVICE_ACCEPT_PRESHUTDOWN=0x100, SERVICE_CONTROL_PRESHUTDOWN=0xF,
            SERVICE_STOP_PENDING=3, SERVICE_AUTO_START=2)
    _module("win32serviceutil", ServiceFramework=object)
    _module("win32ts")

    import ark_watchdog as W
    import launch

    # ---------------------------------------------------------------- a. the record
    print("[launch.py: a start that dies with a Python error leaves its traceback]")
    check("same file name on both sides", W.START_ERROR.name, launch.START_ERROR)
    check("same data folder on both sides", (W.DATA, launch.DATA), (DATA, DATA))
    code = tmpdir() / "versions" / "20261011120000"
    code.mkdir(parents=True)
    (code / "app_main.py").write_text("import ark_relay_module_that_is_not_there\n", encoding="utf-8")
    real_folder, real_argv = launch._code_folder, sys.argv
    launch._code_folder = lambda: code
    sys.argv = ["launch.py"]
    try:
        launch.main()
        raised = None
    except ModuleNotFoundError as exc:
        raised = exc
    finally:
        sys.argv = real_argv
    check("the error still goes on (the task sees the process fail)", type(raised).__name__, "ModuleNotFoundError")
    rec = (DATA / launch.START_ERROR).read_text(encoding="utf-8")
    check("the record names the error", "No module named 'ark_relay_module_that_is_not_there'" in rec)
    check("the record names the version folder and the command", (str(code) in rec, "launch.py run" in rec), (True, True))
    check("the record holds the traceback", "Traceback (most recent call last)" in rec)

    print("[launch.py: a stop / rollback / stop-push exit code is not an error]")
    (DATA / launch.START_ERROR).unlink()
    (code / "app_main.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    sys.argv = ["launch.py", "stop"]
    try:
        launch.main()
    except SystemExit:
        pass
    finally:
        sys.argv = real_argv
        launch._code_folder = real_folder
    check("no record for SystemExit", (DATA / launch.START_ERROR).exists(), False)

    print("[launch.py: only a start leaves a record; a stop / stop-push / rollback that dies does not]")
    (code / "app_main.py").write_text("raise RuntimeError('stop-push blew up')\n", encoding="utf-8")
    launch._code_folder = lambda: code
    for cmd in (["stop"], ["stop-push"], ["rollback"], [], ["run"]):
        sys.argv = ["launch.py", *cmd]
        try:
            launch.main()
        except RuntimeError:
            pass
        finally:
            sys.argv = real_argv
        there = (DATA / launch.START_ERROR).exists()
        check(f"launch.py {' '.join(cmd) or '(no argument)'}: {'recorded' if cmd in ([], ['run']) else 'no record'}",
              there, cmd in ([], ["run"]))
        if there:
            (DATA / launch.START_ERROR).unlink()
    launch._code_folder = real_folder

    print("[launch.py: the file keeps only the newest failures]")
    for i in range(400):
        launch.record_start_error(["run"], code, f"Traceback (most recent call last):\nboom number {i}\n" + "x" * 200)
    rec = (DATA / launch.START_ERROR).read_text(encoding="utf-8")
    check("capped", len(rec) <= launch.START_ERROR_MAX, True)
    check("the newest one is kept", rec.rstrip().endswith("x" * 200) and "boom number 399" in rec, True)

    # ---------------------------------------------------------------- the watchdog
    pushed, started = [], []
    running = {"on": False}
    W.main_running = lambda: running["on"]
    W.someone_logged_on = lambda: True
    W.start_main = lambda: started.append(1) or True
    W.push = lambda text: pushed.append(text) or True   # delivered
    W._log = lambda line: None
    NOW = time.time()

    def tick(w, minute, up=False, wall_base=NOW):
        running["on"] = up
        w.tick(minute * 60.0, wall=wall_base + minute * 60.0)

    print("\n[never comes up: 「中继停了」 at the 3rd start, with the record's last lines]")
    (DATA / launch.START_ERROR).unlink()
    launch.record_start_error(["run"], code, 'Traceback (most recent call last):\n  File "app_main.py", line 1\n'
                              "ModuleNotFoundError: No module named 'win32event'")
    os.utime(DATA / launch.START_ERROR, (NOW + 30, NOW + 30))
    w = W.Watch()
    for m in (0, 0.5, 1):
        tick(w, m)
    check("one push", len(pushed), 1)
    check("it is 「中继停了」", pushed[0].startswith("🔌 中继停了"), True)
    check("with the record's head line", W.REASON_HEAD in pushed[0], True)
    check("with the error line", pushed[0].rstrip().endswith("No module named 'win32event'"), True)
    check("short enough for the group bot", len(pushed[0].encode("utf-8")) < 2048, True)
    for m in (1.5, 2, 2.5, 3):
        tick(w, m)
    check("no crash-loop alarm on top of 「中继停了」 for the same stretch", len(pushed), 1)

    print("[a record from before this stretch is not shown]")
    os.utime(DATA / launch.START_ERROR, (NOW - 3600, NOW - 3600))
    pushed.clear()
    w = W.Watch()
    for m in (0, 0.5, 1):
        tick(w, m)
    check("「中继停了」 says there is no record", (W.REASON_HEAD in pushed[0], W.REASON_NONE in pushed[0]), (False, True))

    print("[comes up and dies again: 4 starts in 30 minutes quiet, the 5th rings once]")
    pushed.clear()
    w = W.Watch()
    for k in range(4):
        tick(w, 5 * k, up=True)
        tick(w, 5 * k + 0.5)                # gone again: the watchdog starts it
    check("4 starts: nothing", len(pushed), 0)
    tick(w, 20, up=True)
    tick(w, 20.5)
    check("5th start: one push", len(pushed), 1)
    check("it is the crash-loop alarm", pushed[0].startswith("🔌 中继反复崩溃重开"), True)
    check("it says 5 times in 30 minutes", "30 分钟内重开了 5 次" in pushed[0], True)
    check("no fresh record: says so", W.REASON_NONE in pushed[0], True)
    for k in range(5, 16):                  # still crashing every 5 minutes, to 75.5: within the hour
        tick(w, 5 * k, up=True)
        tick(w, 5 * k + 0.5)
    check("no second push within the hour", len(pushed), 1)
    tick(w, 80, up=True)
    tick(w, 80.5)                           # 60 minutes after the first push
    check("again after an hour while it still crashes", len(pushed), 2)

    print("[spread out: 5 starts over more than 30 minutes do not ring]")
    pushed.clear()
    w = W.Watch()
    for k in range(6):
        tick(w, 10 * k, up=True)
        tick(w, 10 * k + 0.5)
    check("one start every 10 minutes: nothing", len(pushed), 0)

    print("[starts at a shutdown are not counted]")
    pushed.clear()
    started.clear()
    w = W.Watch()
    SHUTTING["on"] = 1
    for k in range(6):
        tick(w, k)
    SHUTTING["on"] = 0
    check("no start, no push while Windows shuts down", (len(started), len(pushed)), (0, 0))
    W.SESSION_ENDING.write_text("x", encoding="utf-8")
    for k in range(6):
        tick(w, k)                          # within ENDING_HOLD_S of the marker
    W.SESSION_ENDING.unlink()
    check("none while the relay's session ends", (len(started), len(pushed), len(w.starts)), (0, 0, 0))

    print("[a record in Chinese is cut by bytes, so the alarm stays one group message]")
    launch.record_start_error(["run"], code, "Traceback (most recent call last):\n" + "\n".join(
        "RuntimeError: " + "读不了配置文件" * 30 for _ in range(8)))
    os.utime(DATA / launch.START_ERROR, (NOW + 30, NOW + 30))
    pushed.clear()
    w = W.Watch()
    for m in (0, 0.5, 1):
        tick(w, m)
    check("Chinese tail: under 2048 bytes", len(pushed[0].encode("utf-8")) < 2048, True)

    print("[the crash-loop record: one written during the stretch is shown]")
    pushed.clear()
    w = W.Watch()
    os.utime(DATA / launch.START_ERROR, (NOW + 10 * 60, NOW + 10 * 60))
    for k in range(5):
        tick(w, 5 * k, up=True)
        tick(w, 5 * k + 0.5)
    check("crash-loop push carries the record", (len(pushed), W.REASON_HEAD in pushed[-1]), (1, True))


def _part_watchdog_guard():  # noqa: C901
    """The relay starts its watchdog again (watchdog_guard.py), except when it was stopped on purpose.
    """
    import os
    import re
    import tempfile
    import time
    import types

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(RELAY))
    sys.path.insert(0, str(ROOT / "packaging"))

    import watchdog_guard as G

    class Logs:
        def __init__(self):
            self.lines = []

        def __enter__(self):
            self.real = G.log.info, G.log.error
            G.log.info = lambda msg, *a, **k: self.lines.append(("INFO", msg % a))
            G.log.error = lambda msg, *a, **k: self.lines.append(("ERROR", msg % a))
            return self

        def __exit__(self, *exc):
            G.log.info, G.log.error = self.real

    def guard(states, start_results=(), marker=False):
        states, results, started = list(states), list(start_results), []

        def start():
            started.append(1)
            return results.pop(0) if results else ""
        g = G.Guard(lambda: states.pop(0) if len(states) > 1 else states[0], start, lambda: marker)
        return g, started

    print("[what it does on each look]")
    for label, state, marker, want in [
            ("running: nothing", ("RUNNING", "AUTO"), False, "running"),
            ("starting up: wait", ("PENDING", "AUTO"), False, "pending"),
            ("not installed (old relay, dev run): nothing", ("MISSING", "OTHER"), False, "missing"),
            ("stopped, disabled (revert): leave it", ("STOPPED", "DISABLED"), False, "disabled"),
            ("stopped, manual start type: leave it", ("STOPPED", "OTHER"), False, "disabled"),
            ("stopped, marker from this boot: leave it", ("STOPPED", "AUTO"), True, "stopped on purpose"),
            ("stopped, automatic, no marker: start it", ("STOPPED", "AUTO"), False, "started")]:
        g, started = guard([state], marker=marker)
        with Logs():
            got = g.tick()
        check(label, (got, len(started)), (want, 1 if want == "started" else 0))

    print("[a start that fails: INFO each time, one ERROR at the third, quiet until it runs]")
    g, started = guard([("STOPPED", "AUTO")] * 6 + [("RUNNING", "AUTO")] + [("STOPPED", "AUTO")] * 3,
                       ["1053 timeout"] * 9)
    with Logs() as logs:
        for _ in range(10):
            g.tick()
    errors = [m for lvl, m in logs.lines if lvl == "ERROR"]
    check("two ERRORs in two outages of 3+ failures (errwatch pushes each)", len(errors), 2)
    check("ERROR says what failed", "1053 timeout" in errors[0], True)
    check("ERROR says our side has it, not a person to go and look",
          ("已交给我们这边" in errors[0], "看一眼" in errors[0]), (True, False))
    check("recovery is INFO only", [lvl for lvl, m in logs.lines if "又在跑了" in m], ["INFO"])
    check("the ERROR comes with the third failure, not before",
          [lvl for lvl, _ in logs.lines][:5], ["INFO", "INFO", "INFO", "ERROR", "INFO"])

    print("[a look that raises counts as a failure]")
    g = G.Guard(lambda: ("STOPPED", "AUTO"), lambda: "", lambda: False)
    with Logs() as logs:
        for _ in range(3):
            g.failed("OSError()", looked=False)
    check("third raise -> one ERROR", [lvl for lvl, _ in logs.lines].count("ERROR"), 1)
    check("it says the relay could not look, not that the watchdog is down",
          "查不了" in logs.lines[-1][1] and "看门服务停了" not in logs.lines[-1][1], True)

    print("[a watchdog found stopped that nobody stopped: WARNING to the group (audit 10-12 #6)]")

    class WarnLogs(Logs):
        """Logs, plus WARNINGs."""

        def __enter__(self):
            super().__enter__()
            self.real_warning = G.log.warning
            G.log.warning = lambda msg, *a, **k: self.lines.append(("WARNING", msg % a))
            return self

        def __exit__(self, *exc):
            G.log.warning = self.real_warning
            super().__exit__(*exc)

    g, started = guard([("STOPPED", "AUTO"), ("RUNNING", "AUTO")])
    with WarnLogs() as logs:
        got = [g.tick(), g.tick()]
    check("started, then running", got, ["started", "running"])
    check("one WARNING (pushed), saying it was started again", [(lvl, "重新打开" in m) for lvl, m in logs.lines
                                                                 if lvl != "INFO"], [("WARNING", True)])

    g, started = guard([("STOPPED", "AUTO")] * 2 + [("RUNNING", "AUTO")], ["1053 timeout", ""])
    with WarnLogs() as logs:
        got = [g.tick() for _ in range(3)]
    check("a failed start, then one that worked", got, ["start failed", "started", "running"])
    check("the stop is pushed once, at the first look, with why the start failed",
          [(lvl, "1053 timeout" in m) for lvl, m in logs.lines if lvl != "INFO"], [("WARNING", True)])

    g, started = guard([("STOPPED", "AUTO")] * 3, ["1053 timeout"] * 3)
    with WarnLogs() as logs:
        for _ in range(3):
            g.tick()
    check("three failed starts: the WARNING at the first look, the ERROR at the third",
          [lvl for lvl, _ in logs.lines if lvl != "INFO"], ["WARNING", "ERROR"])

    print("[a look that raised once, then worked: transient retry recorded at INFO, not pushed, not daily]")
    g, started = guard([("RUNNING", "AUTO")])
    with WarnLogs() as logs:
        g.failed("OSError()", looked=False)
        g.tick()
    check("no WARNING/ERROR, INFO notes it could look again",
          ([lvl for lvl, _ in logs.lines if lvl != "INFO"],
           any(lvl == "INFO" and "查不了" in m for lvl, m in logs.lines)), ([], True))
    g, started = guard([("RUNNING", "AUTO")])
    with WarnLogs() as logs:
        for _ in range(3):
            g.failed("OSError()", looked=False)
        g.tick()
    check("after the ERROR was pushed, the end is not a second report",
          [lvl for lvl, _ in logs.lines if lvl != "INFO"], ["ERROR"])

    print("[the marker counts only when written since the boot]")
    with tempfile.TemporaryDirectory() as d:
        m = Path(d) / G.MARKER
        check("no marker", G.marker_this_boot(m, time.time() - 100), False)
        m.write_text("x")
        check("written after the boot", G.marker_this_boot(m, time.time() - 100), True)
        old = time.time() - 3600
        os.utime(m, (old, old))
        check("left from before the boot (crashed installer, earlier estop): ignored",
              G.marker_this_boot(m, time.time() - 100), False)

    print("[one marker, the same on every side]")
    fake = {}
    for name in ("pywintypes", "win32service", "win32serviceutil"):
        fake[name] = sys.modules.get(name)
    pywintypes = types.ModuleType("pywintypes")
    pywintypes.error = type("error", (Exception,), {})
    win32service = types.ModuleType("win32service")
    win32service.SERVICE_STOPPED, win32service.SERVICE_RUNNING = 1, 4
    win32serviceutil = types.ModuleType("win32serviceutil")
    sys.modules.update(pywintypes=pywintypes, win32service=win32service, win32serviceutil=win32serviceutil)
    import switch

    check("switch.py's marker is the guard's (data folder, same name)",
          (switch.WATCHDOG_MARKER.name, str(switch.WATCHDOG_MARKER.parent)),
          (G.MARKER, r"C:\ProgramData\ark-relay"))
    estop = (ROOT / "scripts" / "mac" / "estop.sh").read_text(encoding="utf-8")
    stop_ps = estop[estop.index('PS_PKG_STOP="'):estop.index('PS_PKG_START="')]
    start_ps = estop[estop.index('PS_PKG_START="'):]
    marker_ps = r"'C:\\ProgramData\\ark-relay\\" + G.MARKER + "'"
    check("estop writes it", f"Set-Content -Path {marker_ps}" in stop_ps, True)
    check("estop writes it before sc stop",
          stop_ps.find("Set-Content -Path") < stop_ps.find("sc.exe stop ArkRelayWatchdog"), True)
    check("estop --restore deletes it before sc start",
          0 <= start_ps.find(f"Remove-Item -Path {marker_ps}") < start_ps.find("sc.exe start ArkRelayWatchdog"),
          True)

    print("[switch.py: marker before sc stop, deleted before sc start]")
    with tempfile.TemporaryDirectory() as d:
        switch.WATCHDOG_MARKER = Path(d) / G.MARKER
        steps = []
        states = [4, 1]          # RUNNING once (the relay raced it), then STOPPED

        def run(*cmd):
            steps.append(("marker" if switch.WATCHDOG_MARKER.exists() else "no marker",) + tuple(map(str, cmd)))
            return 0
        real_run, real_sleep = switch.run, switch.time.sleep
        switch.run, switch.time.sleep = run, lambda s: None
        win32serviceutil.QueryServiceStatus = lambda name: (0, states.pop(0) if len(states) > 1 else states[0])
        try:
            switch.stop_watchdog()
            check("every sc stop with the marker already there",
                  [s[0] for s in steps], ["marker", "marker"])
            check("stopped again after it came back", [s[1:3] for s in steps], [("sc.exe", "stop")] * 2)
            steps.clear()
            win32serviceutil.QueryServiceStatus = lambda name: (0, 4)
            check("start_watchdog -> 0", switch.start_watchdog(), 0)
            check("marker gone before sc start", steps[0][:3], ("no marker", "sc.exe", "start"))
        finally:
            switch.run, switch.time.sleep = real_run, real_sleep

    print("[the real start counts only a watchdog that comes up and stays (review round 10 #30)]")
    # Only the two Windows calls are stubbed: StartService and QueryServiceStatus.
    # 2 = START_PENDING, 1 = STOPPED, 4 = RUNNING (winsvc.h).

    class Clock:
        def __init__(self):
            self.t = 0.0

        def now(self):
            return self.t

        def wait(self, seconds):
            self.t += seconds
            return False

    def fake_service(states, start_error=None):
        """StartService records the call (raising start_error if given); each status query
    returns the next state, the last one from then on."""
        calls = {"start": 0}
        states = list(states)

        def start_service(name):
            calls["start"] += 1
            if start_error is not None:
                exc = pywintypes.error()
                exc.winerror, exc.strerror = start_error, {1056: "already running"}.get(start_error, "disabled")
                raise exc
        win32serviceutil.StartService = start_service
        win32serviceutil.QueryServiceStatus = lambda name: (0, states.pop(0) if len(states) > 1 else states[0])
        return calls

    def real_start(states, start_error=None):
        clock = Clock()
        calls = fake_service(states, start_error)
        return G._start(clock.wait, clock.now), calls["start"], clock.t

    got, starts, waited = real_start([2, 2, 1])
    check("START_PENDING then STOPPED (cloud run 38095391114) is a failure, not a start",
          (got, starts), ("开到一半自己停了", 1))
    got, starts, waited = real_start([2, 4])
    check("RUNNING and still RUNNING STEADY_S later: started", got, "")
    check("... after waiting the steady time, not at the first RUNNING", waited >= G.STEADY_S, True)
    check("RUNNING, then STOPPED within the steady time: a failure",
          real_start([2, 4, 4, 1])[0], "刚跑起来就又停了")
    check("never leaves START_PENDING: a failure at START_WAIT_S",
          real_start([2])[:1] + (real_start([2])[2] >= G.START_WAIT_S,),
          (f"开了 {G.START_WAIT_S} 秒还没跑起来", True))
    check("1056 (already starting) is watched too, and ends stopped: a failure",
          real_start([2, 1], start_error=1056)[0], "开到一半自己停了")
    check("another start error is the failure itself",
          real_start([1], start_error=1058)[0], "1058 disabled")
    fake_service([2])
    check("relay stopping while it waits: neither success nor failure",
          G._start(lambda s: True, Clock().now), None)

    print("[the guard over the real start: a watchdog that starts then stops reaches the ERROR]")

    def guard_over_real_start(looks, service_each_start):
        """looks: what each look finds; service_each_start: the states a start then goes through."""
        looks, clock = list(looks), Clock()

        def start():
            fake_service(service_each_start)
            return G._start(clock.wait, clock.now)
        return G.Guard(lambda: looks.pop(0) if len(looks) > 1 else looks[0], start, lambda: False)

    g = guard_over_real_start([("STOPPED", "AUTO")], [2, 2, 1])
    with Logs() as logs:
        got = [g.tick() for _ in range(3)]
    check("every start stops during START_PENDING: three failures", got, ["start failed"] * 3)
    errors = [m for lvl, m in logs.lines if lvl == "ERROR"]
    check("one ERROR at the third, with the reason", len(errors) == 1 and "开到一半自己停了" in errors[0], True)

    g = guard_over_real_start([("STOPPED", "AUTO")], [2, 4])
    with Logs() as logs:
        got = [g.tick() for _ in range(4)]
    check("comes up and stays, but is stopped again at every look: counted from the second",
          got, ["started", "started again", "started again", "started again"])
    check("... one ERROR, at the fourth look", [lvl for lvl, _ in logs.lines].count("ERROR"), 1)

    g = guard_over_real_start([("STOPPED", "AUTO"), ("RUNNING", "AUTO"), ("STOPPED", "AUTO")], [2, 4])
    with Logs() as logs:
        got = [g.tick() for _ in range(3)]
    check("a start that is still running at the next look: no failure, a later stop starts afresh",
          (got, g.fails), (["started", "running", "started"], 0))

    looks = [("STOPPED", "AUTO"), ("STOPPED", "AUTO"), ("STOPPED", "AUTO")]
    marks = [False, True, False]
    g = guard_over_real_start(looks, [2, 4])
    g.marker_this_boot = lambda: marks.pop(0)
    with Logs() as logs:
        got = [g.tick() for _ in range(3)]
    check("a look in between (stopped on purpose) means the next start is not 'stopped again'",
          (got, g.fails), (["started", "stopped on purpose", "started"], 0))
    check("the group ERROR does not claim it is down after a start that worked: it says found stopped",
          "留不住" in G.ALERT_GAVE_UP and "发现它停了" in G.ALERT_GAVE_UP, True)

    for name, mod in fake.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod

    src = (ROOT / "packaging" / "switch.py").read_text(encoding="utf-8")
    check("no other starter in switch.py (each goes through start_watchdog)",
          re.findall(r'run\("sc\.exe", "start", WATCHDOG\)', src), ['run("sc.exe", "start", WATCHDOG)'])

    print("[app_main starts the guard, packaged install only, stopping with the relay]")
    app = (RELAY / "app_main.py").read_text(encoding="utf-8")
    gate = app.index("if pkg_layout.app_root(HERE) is not None:")
    body = app[gate:app.index("threading.Thread(target=_end_session_window")]
    check("thread inside the packaged-install gate",
          "target=watchdog_guard.run, args=(host.stop_event, DATA)" in body, True)
    check("logger under ark. (errwatch hooks ark)", G.log.name.startswith("ark."), True)


def _part_watchdog_guard_missing():
    """A watchdog service that vanishes after the relay saw it installed is pushed once."""

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    import watchdog_guard as G

    class Logs:
        def __enter__(self):
            self.lines = []
            self.real = G.log.info, G.log.warning, G.log.error
            G.log.info = lambda msg, *a, **k: self.lines.append(("INFO", msg % a))
            G.log.warning = lambda msg, *a, **k: self.lines.append(("WARNING", msg % a))
            G.log.error = lambda msg, *a, **k: self.lines.append(("ERROR", msg % a))
            return self

        def __exit__(self, *exc):
            G.log.info, G.log.warning, G.log.error = self.real

    def run(states, marker=False):
        states = list(states)
        g = G.Guard(lambda: states.pop(0), lambda: "", lambda: marker)
        with Logs() as logs:
            got = [g.tick() for _ in range(len(states))]
        return got, [lvl for lvl, _ in logs.lines if lvl != "INFO"], logs.lines

    R, M, S = ("RUNNING", "AUTO"), ("MISSING", "OTHER"), ("STOPPED", "AUTO")

    print("[never installed (dev run, old relay): quiet]")
    got, loud, _ = run([M, M, M])
    check("missing at every look", got, ["missing"] * 3)
    check("no WARNING or ERROR", loud, [])

    print("[installed, then gone: one WARNING, not one per look]")
    got, loud, lines = run([R, M, M, M])
    check("looks", got, ["running", "missing", "missing", "missing"])
    check("one WARNING", loud, ["WARNING"])
    check("it says the service is gone and our side has it",
          [("不见了" in m and "已交给我们这边" in m) for lvl, m in lines if lvl == "WARNING"], [True])

    print("[seen stopped counts as installed too]")
    got, loud, _ = run([S, M])
    check("STOPPED_UNASKED, then one WARNING for the gone service", loud, ["WARNING", "WARNING"])

    print("[back, then gone again: a second WARNING]")
    got, loud, _ = run([R, M, R, M])
    check("two WARNINGs", loud, ["WARNING", "WARNING"])

    print("[removed on purpose (stop marker from this boot): quiet]")
    got, loud, _ = run([R, M, M], marker=True)
    check("no WARNING", loud, [])


def _part_watchdog_push_delivery():
    """The watchdog's own group alarm counts as sent only when the group bot took it."""
    import http.client
    import io
    import json
    import os

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(ROOT / "packaging" / "watchdog"))

    DATA = tmpdir()
    os.environ["ARK_HOME"] = str(DATA)
    (DATA / ".env").write_text("WECOM_BOT_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test\n",
                               encoding="utf-8")

    class _PyError(Exception):
        pass

    _module("pywintypes", error=_PyError)
    _module("servicemanager", LogMsg=lambda *a: None, EVENTLOG_INFORMATION_TYPE=4, PYS_SERVICE_STARTED=1)
    _module("win32api", GetSystemMetrics=lambda i: 0, CloseHandle=lambda h: None)
    _module("win32event", CreateEvent=lambda *a: None, SetEvent=lambda e: None, WaitForSingleObject=lambda *a: 0,
            WAIT_TIMEOUT=258)
    _module("win32service", SERVICE_ACCEPT_PRESHUTDOWN=0x100, SERVICE_CONTROL_PRESHUTDOWN=0xF,
            SERVICE_STOP_PENDING=3, SERVICE_AUTO_START=2)
    _module("win32serviceutil", ServiceFramework=object)
    _module("win32ts")

    import ark_watchdog as W

    class _Resp:
        def __init__(self, status, obj):
            self.status = status
            self._raw = io.BytesIO(json.dumps(obj).encode("utf-8"))

        def read(self):
            return self._raw.read()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    answers = []      # what each urlopen call does, in order: a reply or an exception
    posts = []

    def fake_urlopen(req, timeout=None):
        posts.append(json.loads(req.data.decode("utf-8"))["text"]["content"])
        a = answers.pop(0) if answers else _Resp(200, {"errcode": 0, "errmsg": "ok"})
        if isinstance(a, BaseException):
            raise a
        return a

    def refused():
        return _Resp(200, {"errcode": 45009, "errmsg": "api freq out of limit"})

    def dropped():
        # BadStatusLine is an HTTPException and not an OSError (RemoteDisconnected is both).
        return http.client.BadStatusLine("")

    W.urllib.request.urlopen = fake_urlopen
    logged = []
    W._log = logged.append
    running = {"on": False}
    logon = {"on": True}
    W.main_running = lambda: running["on"]
    W.someone_logged_on = lambda: logon["on"]
    W.start_main = lambda: True
    # No start record in these stretches: the alarm says so (REASON_NONE).
    W.START_ERROR = DATA / "no-start-error.txt"
    CAP = getattr(W, "PUSH_TRIES", 3)

    def new_watch():
        try:
            return W.Watch()
        except TypeError:               # the old signature, Watch(now)
            return W.Watch(0.0)

    def deliver(text):
        """push() as a bool; the old one returned None and let HTTPException out."""
        try:
            return W.push(text)
        except http.client.HTTPException as exc:
            return f"raised {type(exc).__name__}"

    print("[push(): delivered only on HTTP 200 with errcode 0]")
    answers[:] = [_Resp(200, {"errcode": 0, "errmsg": "ok"})]
    check("errcode 0: delivered", deliver("x"), True)
    answers[:] = [refused()]
    check("HTTP 200 with errcode 45009: not delivered", deliver("x"), False)
    check("... and the log says it did not get through", logged[-1].startswith("进群失败"), True)
    answers[:] = [dropped()]
    check("http.client.HTTPException is caught: not delivered", deliver("x"), False)
    answers[:] = [OSError(10051, "A socket operation was attempted to an unreachable network")]
    check("network not up (WinError 10051): not delivered", deliver("x"), False)
    answers[:] = [_Resp(200, "not a dict")]
    check("an answer that is not WeCom's: not delivered", deliver("x"), False)

    print("\n[「中继停了」 refused once: tried again at the next look, flag set only once it got through]")
    posts.clear()
    w = new_watch()
    answers[:] = [refused()]
    for t in (0, 30, 60):
        w.tick(t, wall=1_000_000.0 + t)
    check("3rd start: one push, refused", len(posts), 1)
    check("the alarm is not marked sent", w.alerted, False)
    w.tick(90, wall=1_000_090.0)
    check("next look: pushed again", len(posts), 2)
    check("delivered this time: marked sent", w.alerted, True)
    w.tick(120, wall=1_000_120.0)
    check("no third push once delivered", len(posts), 2)

    print(f"\n[「中继停了」 never gets through: {CAP} pushes, then give up and say so]")
    posts.clear()
    logged.clear()
    w = new_watch()
    answers[:] = [refused() for _ in range(10)]
    for k in range(10):
        w.tick(30 * k, wall=1_000_000.0 + 30 * k)
    check(f"pushed exactly {CAP} times", len(posts), CAP)
    check("given up: no more pushes this stretch", w.alerted, True)
    check("the give-up is in watchdog.log", any("不再重试" in x for x in logged), True)
    running["on"] = True
    w.tick(2900, wall=1_002_900.0)     # up again, past LOOP_WINDOW_S: no crash-loop alarm mixed in
    running["on"] = False
    answers[:] = [refused()]
    for k in range(100, 103):
        w.tick(30 * k, wall=1_000_000.0 + 30 * k)
    check("a new stretch after the relay ran again: tried again", len(posts), CAP + 1)

    print("\n[HTTPException from the bot: no endless re-send every 30 s]")
    posts.clear()
    w = new_watch()
    answers[:] = [dropped() for _ in range(20)]
    for k in range(20):
        try:
            w.tick(30 * k, wall=1_000_000.0 + 30 * k)
        except http.client.HTTPException:
            pass                        # what SvcDoRun's 「检查出错」 caught on the old code
    check(f"bounded by {CAP}", len(posts), CAP)

    print("\n[「没人登录」: same rule]")
    posts.clear()
    logon["on"] = False
    w = new_watch()
    answers[:] = [dropped(), refused()]
    for t in range(0, W.NOBODY_LIMIT_S + 30 * 5, 30):
        try:
            w.tick(float(t), wall=1_000_000.0 + t)
        except http.client.HTTPException:
            pass
    check("two failed, the third delivered", len(posts), 3)
    check("marked sent", w.nobody_alerted, True)
    logon["on"] = True

    print("\n[crash loop: refused, tried again at the next start]")
    posts.clear()
    w = new_watch()
    answers[:] = [refused()]
    for k in range(6):
        running["on"] = True
        w.tick(300.0 * k, wall=1_000_000.0 + 300 * k)
        running["on"] = False
        w.tick(300.0 * k + 30, wall=1_000_030.0 + 300 * k)
    check("5th start refused, 6th start delivered", (len(posts), w.loop_alerted_at), (2, 300.0 * 5 + 30))


def _part_gh_watchdog():
    """The GitHub Actions boot watchdog (scripts/watchdog.py; queue/watchdog.json has it off since
08-20): a daytime run by hand judges tonight's checks as not due, and a watchdog that cannot
ask Tailscale says so (audit 11-08 A-25; dispatch relay-opt-round5-1108 R5-02).
    """
    import importlib.util
    import json
    from datetime import datetime

    ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("gh_watchdog", ROOT / "scripts" / "watchdog.py")
    wd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wd)

    def srv(d, hh, mm):
        return datetime(2026, 11, d, hh, mm, tzinfo=wd.SERVER_TZ)

    print("[today_at：凌晨迟到的检查算前一晚，白天手动跑算今晚]")
    check("11-09 00:30 查 23:10：是 11-08 那晚的", wd.today_at("23:10", srv(9, 0, 30)), srv(8, 23, 10))
    check("11-08 10:00 查 23:10：是今晚的（还没到点）", wd.today_at("23:10", srv(8, 10, 0)), srv(8, 23, 10))
    check("11-08 10:00 查 08:40：今天早上的", wd.today_at("08:40", srv(8, 10, 0)), srv(8, 8, 40))
    check("UTC 时间传进来也按北京时间算（11-08 02:00 UTC = 10:00 北京）",
          wd.today_at("23:10", datetime(2026, 11, 8, 2, 0, tzinfo=wd.timezone.utc)), srv(8, 23, 10))
    last = srv(8, 9, 50)
    check("白天手动跑：晚上收工那项不判（之前会说「该关机了还在线」）",
          wd.run_check("shutdown", {"label": "晚上收工", "boot_since": "21:15", "min_off": "21:50", "off_by": "22:35"},
                       last, srv(8, 10, 0).astimezone(wd.timezone.utc)), None)

    print("\n[问不到 Tailscale：报一条「开机监督自身异常」，退出码 1；手动跑只打印]")
    cfg = tmpdir() / "watchdog.json"
    cfg.write_text(json.dumps({"enabled": True, "pause_until": "2000-01-01", "device": "ins",
                               "checks": {"20 1 * * *": {"kind": "boot", "label": "早上开机", "since": "08:40"}}}),
                   encoding="utf-8")
    sent = []
    saved = (wd.CONFIG, wd.alert, wd.tailscale_last_seen, dict(wd.os.environ))

    def broken(device):
        raise RuntimeError("缺 TS_OAUTH_CLIENT_ID / TS_OAUTH_SECRET secrets")

    wd.CONFIG, wd.alert, wd.tailscale_last_seen = cfg, (lambda t, b: sent.append((t, b)) or True), broken
    try:
        wd.os.environ["CHECK_CRON"] = "20 1 * * *"
        rc = wd.main()
        check("定时跑：退出码 1", rc, 1)
        check("……推了一条，标题是开机监督自身异常", [t for t, _b in sent], ["🔌 开机监督自身异常"])
        check("……正文说了原因", "TS_OAUTH" in sent[0][1], True)
        sent.clear()
        wd.os.environ.pop("CHECK_CRON")
        check("手动跑：退出码 1", wd.main(), 1)
        check("……不推送", sent, [])
    finally:
        wd.CONFIG, wd.alert, wd.tailscale_last_seen = saved[:3]
        wd.os.environ.clear()
        wd.os.environ.update(saved[3])


def _part_polling_spam_cure():
    """R-05: real-entrypoint replay of single-fault polling WARNING storms (11-25 desktop
    read 17-alert storm, 10-29 MaaEnd 4-option rename 16-alert storm, ledger bad-line
    ticks, directory watcher outage retries, stagegate put-back retries)."""
    import json
    import logging
    import threading
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import desktop as dk
    from ark_relay.core import ledger as ledger_mod
    from ark_relay.core import mastercfg
    from ark_relay.core import watch as watch_mod
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import gameupdate_games as gug
    from ark_relay.features import stagegate

    warns: list[tuple[str, str]] = []

    class _Catch(logging.Handler):
        def emit(self, rec):
            if rec.levelno >= logging.WARNING:
                warns.append((rec.name, rec.getMessage()))

    h = _Catch()
    loggers = (dk.log, gug.log, mastercfg.log, ledger_mod.log, watch_mod.log, stagegate.log)
    for lg in loggers:
        lg.addHandler(h)

    try:
        print("[1. Desktop single failed read() / read_file() emits 1 WARNING, not 2]")
        warns.clear()
        d_fail = dk.Desktop(tmpdir() / "state", spawn=lambda exe, cwd, args: False, timeout=1)
        scr = d_fail.read(focus="Games")
        check("read() returns error Screen", scr.error, "没能起来")
        check("single read() failure emits exactly 1 WARNING (no _run+read double fire)", len(warns), 1)
        warns.clear()
        res_f = d_fail.read_file(Path("fake.png"), timeout=1)
        check("read_file() returns None on failure", res_f, None)
        check("single read_file() failure emits exactly 1 WARNING", len(warns), 1)

        print("\n[2. 11-25 replay: update_endfield 20-poll desktop error storm -> 1 WARNING + final failure]")
        clock = {"t": 0.0}
        saved_gug = (gug.time.monotonic, gug._spawn, gug.kill)
        gug.time.monotonic = lambda: clock["t"]
        gug._spawn = lambda exe, cwd=None: True
        gug.kill = lambda *names: True

        def fake_sleep(s):
            clock["t"] += s

        def make_desk(scripted):
            it = iter(scripted)
            last = [scripted[-1]]

            def spawn(exe, cwd, args):
                try:
                    item = next(it)
                    last[0] = item
                except StopIteration:
                    item = last[0]
                if item is None:
                    return False
                Path(args[-1]).write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
                return True

            return dk.Desktop(tmpdir() / "state", spawn=spawn, timeout=1)

        def ok_ocr(*texts):
            return {"ok": True, "clicked": [], "log": [],
                    "ocr": [{"text": t, "x": 100, "y": 100 + i * 30, "w": 80, "h": 20} for i, t in enumerate(texts)]}

        def ok_click(txt):
            return {"ok": True, "clicked": [txt], "log": [], "ocr": []}

        def err_read(msg):
            return {"ok": False, "clicked": [], "log": [msg], "ocr": []}

        EF = (Path("Endfield.exe"), Path("Launcher.exe"))
        try:
            # 20 consecutive identical failures in download wait -> 1 WARNING + final timeout problem
            warns.clear()
            clock["t"] = 0.0
            probs: list[str] = []
            d = make_desk([ok_ocr("更新游戏"), ok_click("更新游戏"), err_read("超时")])
            out = gug.update_endfield(d, *EF, budget_s=600, poll_s=30, problems=probs, sleep=fake_sleep)
            check("timeout returns empty", out, "")
            check("20 polls of identical error -> exactly 1 WARNING", len(warns), 1)
            check("final timeout failure still reported in problems", any("没等到「开始游戏」" in p for p in probs), True)

            # Different error mid-wait -> pushes new WARNING; recovery + recurrence -> pushes again
            warns.clear()
            clock["t"] = 1000.0
            probs = []
            d2 = make_desk([
                ok_ocr("更新游戏"),
                ok_click("更新游戏"),
                err_read("超时"),
                err_read("超时"),
                err_read("ERR OCR崩溃"),
                err_read("ERR OCR崩溃"),
                ok_ocr("正在下载 50%"),
                err_read("超时"),
                err_read("超时"),
                ok_ocr("开始游戏"),
                ok_click("开始游戏"),
                ok_ocr("点击任意位置继续"),
            ])
            out2 = gug.update_endfield(d2, *EF, budget_s=600, poll_s=30, problems=probs, sleep=fake_sleep)
            check("recovered update finishes cleanly", out2, "终末地 客户端已通过启动器更新")
            check("distinct error + post-recovery recurrence each warn once (3 total)", len(warns), 3)
            check("no problems on success", probs, [])

            # New update_endfield wait instance with same error -> fresh WARNING
            warns.clear()
            clock["t"] = 2000.0
            probs = []
            d3 = make_desk([ok_ocr("更新游戏"), ok_click("更新游戏"), err_read("超时")])
            gug.update_endfield(d3, *EF, budget_s=90, poll_s=30, problems=probs, sleep=fake_sleep)
            check("new wait instance warns afresh", len(warns), 1)
        finally:
            gug.time.monotonic, gug._spawn, gug.kill = saved_gug

        print("\n[3. 10-29 replay: MaaEnd 4 renamed missing-def options -> 1 consolidated WARNING]")
        root = tmpdir()
        automas = root / "automas"
        (automas / "data" / "sid" / "Default" / "ConfigFile").mkdir(parents=True)
        master = automas / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
        maaend = root / "maaend"
        (maaend / "tasks").mkdir(parents=True)
        (maaend / "locales" / "interface").mkdir(parents=True)
        (maaend / "locales" / "interface" / "zh_cn.json").write_text(
            json.dumps({"task.AutoCollect.label": "自动采集"}, ensure_ascii=False), encoding="utf-8")
        (maaend / "interface.json").write_text('{"import": ["tasks/AutoCollect.json"]}', encoding="utf-8")
        (maaend / "tasks" / "AutoCollect.json").write_text(json.dumps({
            "task": [{"name": "AutoCollect", "label": "$task.AutoCollect.label", "option": []}],
            "option": {}}), encoding="utf-8")
        renamed = ("AutoCollectValleyIVRareItems", "AutoCollectValleyIVCommonItems",
                   "AutoCollectWulingRareItems", "AutoCollectWulingCommonItems")
        master.write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
            {"taskName": "AutoCollect", "enabled": True,
             "optionValues": {k: {"type": "checkbox", "caseNames": ["x"]} for k in renamed}}]}]}),
            encoding="utf-8")
        mastercfg._said.clear()
        warns.clear()
        for _ in range(3):
            mastercfg.read_maaend(automas, maaend)
        check("4 renamed options across 3 reads -> 1 consolidated WARNING (not 8 or 24)", len(warns), 1)
        check("consolidated WARNING names all 4 options", all(k in warns[0][1] for k in renamed), True)
        check("no redundant no_cases WARNING when defs missing", any("没有可选值" in m for _, m in warns), False)
        # Adding a 5th broken option changes signature -> immediately pushes new WARNING
        master.write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
            {"taskName": "AutoCollect", "enabled": True,
             "optionValues": {**{k: {"type": "checkbox", "caseNames": ["x"]} for k in renamed},
                              "AutoCollectSchedule": {"type": "select", "caseName": "EveryDay"}}}]}]}),
            encoding="utf-8")
        mastercfg.read_maaend(automas, maaend)
        check("new broken option triggers fresh WARNING", len(warns), 2)

        print("\n[4. Ledger bad-line polling: missing fields / bad timestamps warn once per broken line]")
        st = ledger_mod.State(tmpdir() / "lstate")
        lp = st.ledger_path("2026-11-26")
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(
            '{"script": "MAA"}\n'
            '{"run_id": "r1", "script": "MAA", "user": "u", "ok": true, "started": "bad", "finished": "bad"}\n'
            '{torn json\n', encoding="utf-8")
        ledger_mod._LEDGER_TORN_SAID.clear()
        warns.clear()
        for _ in range(5):
            st.read_ledger("2026-11-26")
        check("3 broken lines read 5 times -> 3 WARNINGs total (not 15)", len(warns), 3)
        with lp.open("a", encoding="utf-8") as fh:
            fh.write('{"script": "OK-WW"}\n')
        st.read_ledger("2026-11-26")
        check("new broken line immediately fires 1 new WARNING", len(warns), 4)

        print("\n[5. Directory watcher drop retries: 1 WARNING per outage, re-warns after rebuild]")
        wake = threading.Event()
        done_w = threading.Event()
        # Outage 1: open ok -> wait drops -> 2 failed rebuilds -> rebuild ok -> Outage 2: wait drops -> stop
        opens = iter([101, None, None, 102, None])
        waits = iter([1, 1])
        sleeps = [0]

        class _FakeK:
            class FindFirstChangeNotificationW:
                argtypes = restype = None

                def __new__(cls, *a):
                    try:
                        return next(opens)
                    except StopIteration:
                        return None

            class FindNextChangeNotification:
                argtypes = restype = None

                def __new__(cls, *a):
                    return False

            class FindCloseChangeNotification:
                argtypes = None

                def __new__(cls, *a):
                    return True

            class WaitForSingleObject:
                argtypes = restype = None

                def __new__(cls, *a):
                    return next(waits, 1)

        def fake_watch_sleep(_s):
            sleeps[0] += 1
            if sleeps[0] >= 4:
                done_w.set()
                raise SystemExit

        saved_w = (watch_mod.ctypes, watch_mod.time)
        fake_ctypes = types.SimpleNamespace(
            windll=types.SimpleNamespace(kernel32=_FakeK()),
            c_wchar_p=object, c_int=object, c_uint32=object,
            c_void_p=lambda x: types.SimpleNamespace(value=x),
        )
        watch_mod.ctypes = fake_ctypes
        watch_mod.time = types.SimpleNamespace(sleep=fake_watch_sleep)
        warns.clear()
        try:
            ok_w = watch_mod._windows("D:\\fake", wake)
            check("watcher started", ok_w, True)
            done_w.wait(5)
        finally:
            watch_mod.ctypes, watch_mod.time = saved_w
        # Outage 1 had 3 attempts (initial drop + 2 failed rebuilds) -> 1 WARNING; Outage 2 after rebuild -> 2nd WARNING
        check("2 outages across 4 sleep retries -> exactly 2 WARNINGs", len(warns), 2)

        print("\n[6. StageGate _put_back retries: 1 WARNING per (due, error); new error pushes]")
        sg_state = tmpdir() / "sg"
        sg_cfg = types.SimpleNamespace(state_dir=sg_state, automas_dir=tmpdir(), maa_dir=tmpdir())
        from ark_relay.core.statestore import StateStore
        StateStore(sg_state).set("updates", "stagegate_skips", [
            {"queue": "早班", "due": "2026-11-26 09:00", "item": "x"}])
        t_base = datetime(2026, 11, 26, 12, 0, tzinfo=SERVER_TZ)
        err_msg = ["API timeout"]

        def bad_restorer(_rec):
            raise RuntimeError(err_msg[0])

        warns.clear()
        stagegate._put_back(sg_cfg, t_base, busy=lambda: False, restorer=bad_restorer)
        stagegate._put_back(sg_cfg, t_base + timedelta(minutes=20), busy=lambda: False, restorer=bad_restorer)
        stagegate._put_back(sg_cfg, t_base + timedelta(minutes=40), busy=lambda: False, restorer=bad_restorer)
        check("3 retries with identical put-back error -> 1 WARNING", len(warns), 1)
        err_msg[0] = "Queue renamed"
        stagegate._put_back(sg_cfg, t_base + timedelta(minutes=60), busy=lambda: False, restorer=bad_restorer)
        check("different put-back error immediately fires 2nd WARNING", len(warns), 2)
    finally:
        for lg in loggers:
            lg.removeHandler(h)


if __name__ == "__main__":
    sys.exit(run_parts([_part_apphost_covers_service, _part_estop_verifies, _part_farm_launcher, _part_hidden_launch_quoting, _part_launcher_states, _part_endfield_start_retry, _part_endfield_launcher_quiet, _part_procs_wmi, _part_relaunch, _part_rollback_stop_failed, _part_unknown_process_list, _part_wait_network, _part_watch_handle_close, _part_procwatch_cancel, _part_procwatch_drop, _part_wmi_listener, _part_procnames, _part_watchdog_copy, _part_watchdog_crashloop, _part_watchdog_guard, _part_watchdog_guard_missing, _part_watchdog_push_delivery, _part_gh_watchdog, _part_polling_spam_cure]))
