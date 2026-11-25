"""Desktop window interaction, display wake, and relay self-update."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


class _NoSleep:
    """重试之间的等待与测试无关，跳过它；单调时钟保持真的，预算判断还要用。"""

    monotonic = staticmethod(time.monotonic)

    @staticmethod
    def sleep(_seconds):
        return None


def _net_class(su):
    """The fake network class for one part's own copy of the selfupdate module `su`."""

    class Net:
        """假网络。doors: {域名: {文件相对路径: bytes}}；没有的键就是这扇门取不到。"""

        def __init__(self, doors):
            self.doors = doors
            self.tried = []

        def get(self, url, timeout=20):
            host = su._netloc(url)
            rel = url.split("/relay/", 1)[-1]
            self.tried.append((host, rel))
            return self.doors.get(host, {}).get(rel)

        @property
        def hosts(self):
            return [h for h, _ in self.tried]

    return Net


def _workdir(StateStore, files, code_version=""):
    """一台机器：root 下摆好现有文件，state 里记好本机代码版本。"""
    root = tmpdir()
    (root / "state").mkdir()
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    if code_version:
        StateStore(root / "state").set("versions", "code", str(code_version))
    return root


def _part_desktop_focus():
    """Desktop focus and short-word matching. No Windows here: the spawn is faked to
write the result JSON the way agent.ps1 does.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import desktop as dk
    from ark_relay.core.desktop import Desktop, Line, Screen


    OTHER_WINDOW = [{"text": "版本更新公告", "x": 10, "y": 10, "w": 100, "h": 20},
                    {"text": "已是最新版本", "x": 10, "y": 40, "w": 100, "h": 20},
                    {"text": "开始游戏", "x": 10, "y": 70, "w": 100, "h": 20}]


    def agent(result):
        """A fake interactive session answering every request with `result`."""
        seen = []

        def spawn(exe, cwd, args):
            req, res = Path(args[-2]), Path(args[-1])
            seen.append(json.loads(req.read_text(encoding="utf-8")))
            res.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return True
        spawn.seen = seen
        return spawn


    print("[focus 窗口没找到（结果里 focus_missing）：读屏给空屏、标记 focus_missing，截图路径照留]")
    sp = agent({"ok": True, "focus_missing": True, "clicked": [], "ocr": OTHER_WINDOW,
                "log": ["focus: 没有 Games 的窗口", "ocr 3 行（窗口增强 0 行）"]})
    scr = Desktop(tmpdir() / "state", spawn=sp, timeout=5).read(focus="Games")
    check("请求带了 focus", sp.seen[0]["focus"], "Games")
    check("focus_missing", getattr(scr, "focus_missing", False), True)
    check("别的窗口的字不算数", [ln.text for ln in scr.lines], [])
    check("「开始游戏」读不到", scr.has("开始游戏"), False)
    check("截图路径照留", scr.shot is not None and scr.shot.name.startswith("shot-"), True)

    print("\n[只有日志行「focus: 没有 …」（旧版 agent.ps1 没有 focus_missing 字段）：同样当没找到]")
    sp = agent({"ok": True, "clicked": [], "ocr": OTHER_WINDOW,
                "log": ["focus: 没有 title:鸣潮 的窗口", "ocr 3 行（窗口增强 0 行）"]})
    scr = Desktop(tmpdir() / "state", spawn=sp, timeout=5).read(focus="title:鸣潮")
    check("focus_missing", getattr(scr, "focus_missing", False), True)
    check("别的窗口的字不算数", [ln.text for ln in scr.lines], [])

    print("\n[找到了窗口：行原样回来，focus_missing 为 False]")
    sp = agent({"ok": True, "clicked": [], "ocr": OTHER_WINDOW[2:],
                "log": ["focus: Games 「Hypergryph Launcher」", "ocr 1 行（窗口增强 0 行）"]})
    scr = Desktop(tmpdir() / "state", spawn=sp, timeout=5).read(focus="Games")
    check("focus_missing", getattr(scr, "focus_missing", None), False)
    check("行", [ln.text for ln in scr.lines], ["开始游戏"])

    print("\n[窗口没找到时点击一律不算：click_text 返回 False，即使结果里有 clicked]")
    missing = {"ok": True, "focus_missing": True, "clicked": [[60, 80]], "ocr": OTHER_WINDOW,
               "log": ["focus: 没有 Endfield 的窗口", "click 60,80"]}
    d = Desktop(tmpdir() / "state", spawn=agent(missing), timeout=5)
    check("click_text 返回 False", d.click_text("确认", focus="Endfield"), False)
    log_only = dict(missing)
    del log_only["focus_missing"]
    d = Desktop(tmpdir() / "state", spawn=agent(log_only), timeout=5)
    check("只有日志行：click_text 返回 False", d.click_text("确认", focus="Endfield"), False)
    found = {"ok": True, "clicked": [[60, 80]], "ocr": [], "log": ["focus: Endfield 「Endfield」", "click 60,80"]}
    d = Desktop(tmpdir() / "state", spawn=agent(found), timeout=5)
    check("找到窗口：click_text 照常 True", d.click_text("确认", focus="Endfield"), True)

    print("\n[Screen 构造：focus_missing 关键字；旧的 (lines, shot) 位置参数照常]")
    try:
        s = Screen([], Path("x.png"), focus_missing=True)
        check("关键字构造", s.focus_missing, True)
    except TypeError as e:
        check("关键字构造", repr(e), "no TypeError")
    s = Screen([Line("开始游戏", 0, 0, 10, 10)], Path("x.png"))
    check("位置参数构造默认 False", getattr(s, "focus_missing", None), False)

    print("\n[桌面助手自己失败（ok 为 false）：读屏给空屏、带 error，部分行不算数]")
    sp = agent({"ok": False, "clicked": [], "ocr": OTHER_WINDOW,
                "log": ["focus: Games 「Hypergryph Launcher」", "ERR 读屏出错"]})
    scr = Desktop(tmpdir() / "state", spawn=sp, timeout=5).read(focus="Games")
    check("error 带日志", "ERR 读屏出错" in getattr(scr, "error", ""), True)
    check("部分行不算数", [ln.text for ln in scr.lines], [])
    check("不是 focus_missing", getattr(scr, "focus_missing", None), False)
    scr = Desktop(tmpdir() / "state", spawn=lambda exe, cwd, args: False, timeout=5).read(focus="Games")
    check("助手没起来：error", getattr(scr, "error", ""), "没能起来")
    sp = agent({"ok": True, "clicked": [], "ocr": OTHER_WINDOW[2:], "log": []})
    check("读成功：error 为空", getattr(Desktop(tmpdir() / "state", spawn=sp, timeout=5).read(focus="Games"),
                                       "error", None), "")

    print("\n[两字以下的词要整行相等，不当子串]")
    news = Screen([Line("版本更新公告", 0, 0, 100, 20), Line("确认更新内容", 0, 30, 100, 20)])
    check("「更新」不命中「版本更新公告」", news.find("更新"), None)
    check("「确认」不命中「确认更新内容」", news.find("确认"), None)
    check("has 同理", news.has("更新", "确认"), False)
    btn = Screen([Line("版本更新公告", 0, 0, 100, 20), Line("更 新", 50, 300, 40, 20)])
    hit = btn.find("更新")
    check("按钮「更 新」整行命中（空格不算）", (hit.text, hit.y) if hit else None, ("更 新", 300))
    check("「确认」整行命中", Screen([Line("确认", 5, 5, 10, 10)]).find("确认") is not None, True)
    check("两字不容错", Screen([Line("确人", 0, 0, 10, 10)]).find("确认"), None)

    print("\n[三字及以上照旧：子串命中；四字以上容 1 个字]")
    check("「更新游戏」在长行里命中", Screen([Line("@更新游戏 v1.2", 0, 0, 10, 10)]).find("更新游戏") is not None, True)
    check("「请重启游戏」在长句里命中", Screen([Line("资源初始化更新完成，请重启游戏", 0, 0, 10, 10)]).has("请重启游戏"), True)
    check("「开始游戏」认成「丹始游戏」照样命中", Screen([Line("@丹始游戏", 0, 0, 10, 10)]).find("开始游戏") is not None, True)

    print("\n[agent.ps1（AGENT_PS）这一侧：只能在游戏机上实证，这里核脚本文本]")
    ps = dk.AGENT_PS
    check("focus 没找到时写 focus_missing", "$out.focus_missing = $true" in ps, True)
    check("focus 没找到时跳过点击", ps.count('[void]$log.Add("skip click: focus missing")'), 2)
    check("click_text 两字以下要整行相等", "if ($want.Length -le 2) { $t -eq $want }" in ps, True)
    check("旧的纯子串匹配没了", "Where-Object { ($_.text -replace '\\s', '') -like \"*$want*\" }" in ps, False)
    check("OCR 坐标按 TextAngle 旋回原图", "$result.TextAngle" in ps and "[Math]::Cos($rad)" in ps, True)

    print("\n[等待窗口时 warn_missing=False：照样返回 focus_missing 和 trace，但不刷 WARNING]")
    import logging
    warns = []
    class _W(logging.Handler):
        def emit(self, rec):
            if rec.levelno >= logging.WARNING:
                warns.append(rec.getMessage())
    wh = _W()
    dk.log.addHandler(wh)
    try:
        sp = agent({"ok": True, "focus_missing": True, "clicked": [], "ocr": OTHER_WINDOW,
                    "log": ["focus: 没有 Endfield 的窗口"]})
        d_q = Desktop(tmpdir() / "state", spawn=sp, timeout=5)
        scr_q = d_q.read(focus="Endfield", warn_missing=False)
        check("warn_missing=False 仍返回 focus_missing", scr_q.focus_missing, True)
        check("warn_missing=False 仍空行", scr_q.lines, [])
        check("warn_missing=False trace 仍记 focus_missing", d_q.trace[-1].get("focus_missing"), True)
        check("warn_missing=False 不发 WARNING", warns, [])
        d_q.read(focus="Endfield")
        check("默认 warn_missing=True 照常发 1 条 WARNING", len(warns), 1)
    finally:
        dk.log.removeHandler(wh)


def _part_desktop_kill():
    """desktop.kill says when taskkill did not end a program (review 2026-10-13, s5 #8)."""
    import logging
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import desktop


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    codes = {}


    def fake_run(cmd, **kw):
        name = cmd[-1]
        if codes.get(name) == "missing":
            raise FileNotFoundError(2, "taskkill not found")
        rc = codes.get(name, 0)
        out = {0: "成功: 已终止进程 \"x\"。", 128: "错误: 没有找到进程 \"x\"。", 1: "错误: 无法终止进程，拒绝访问。"}
        return types.SimpleNamespace(returncode=rc, stdout=out.get(rc, "").encode("gbk"), stderr=b"")


    g = Grab()
    desktop.log.addHandler(g)
    real_run = desktop.subprocess.run
    desktop.subprocess.run = fake_run
    try:
        print("[结束了、本来就不在：都算好]")
        codes.update({"Games.exe": 0, "Endfield.exe": 128})
        check("返回成功", desktop.kill("Endfield.exe", "Games.exe"), True)
        check("没有警告", g.lines, [])

        print("\n[拒绝访问：返回失败，警告里有程序名和 taskkill 原话]")
        codes.update({"Games.exe": 1})
        got = desktop.kill("Endfield.exe", "Games.exe")
        check("返回失败", got, False)
        check("一条警告", len(g.lines), 1)
        check("警告写了是哪个程序、退出码和原话",
              bool(g.lines) and "Games.exe" in g.lines[0] and "1" in g.lines[0] and "拒绝访问" in g.lines[0], True)

        print("\n[taskkill 本身起不来：也算失败]")
        g.lines.clear()
        codes.update({"Games.exe": "missing"})
        check("返回失败", desktop.kill("Games.exe"), False)
        check("一条警告", len(g.lines), 1)

        print("\n[2026-11-25 10:05:19：进程刚退出时 taskkill 返回 1 且原因为「没有此任务的实例在运行」→ 算好不警告]")
        g.lines.clear()
        def fake_race(cmd, **kw):
            name = cmd[-1]
            if name == "Endfield.exe":
                msg = '错误: 无法终止进程 "Endfield.exe"，其 PID 为 5224。\r\n\r\n原因: 没有此任务的实例在运行。\r\n'
                return types.SimpleNamespace(returncode=1, stdout=b"", stderr=msg.encode("gbk"))
            msg = ('错误: 无法终止进程 "x.exe"，其 PID 为 100。\r\n原因: 没有此任务的实例在运行。\r\n'
                   '错误: 无法终止进程 "x.exe"，其 PID 为 200。\r\n原因: 拒绝访问。\r\n')
            return types.SimpleNamespace(returncode=1, stdout=b"", stderr=msg.encode("gbk"))
        desktop.subprocess.run = fake_race
        check("竞态已退出返回成功", desktop.kill("Endfield.exe"), True)
        check("竞态已退出没有警告", g.lines, [])
        check("混有拒绝访问仍算失败", desktop.kill("x.exe"), False)
        check("混有拒绝访问仍发一条警告", len(g.lines), 1)
    finally:
        desktop.subprocess.run = real_run
        desktop.log.removeHandler(g)


def _part_desktop_no_window():
    """A desktop picture never puts a window on the screen."""
    import ast
    import json
    from pathlib import Path, PureWindowsPath

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.desktop import POWERSHELL, Desktop
    from ark_relay.features import preupdate as C


    def fake(tag, calls):
        """A spawn that behaves like the agent and records which route was used."""
        def spawn(exe, cwd, args):
            calls.append((tag, PureWindowsPath(exe).name))
            req, res = Path(args[-2]), Path(args[-1])
            r = json.loads(req.read_text(encoding="utf-8"))
            if r.get("shot"):
                Path(r["shot"]).write_bytes(b"\x89PNG fake")
            res.write_text(json.dumps({"ok": True, "log": [], "ocr": [], "clicked": []}), encoding="utf-8")
            return True
        return spawn


    print("[the task-end picture and a plain read take the windowless route]")
    calls = []
    d = Desktop(tmpdir() / "state", spawn=fake("window", calls), spawn_hidden=fake("hidden", calls), timeout=5)
    check("screenshot() got a file", d.screenshot() is not None, True)
    d.read()
    d.read_file(tmpdir() / "x.png")
    check("screenshot, read and read_file all went windowless", [c[0] for c in calls], ["hidden"] * 3)
    check("it is still PowerShell that runs the agent", {c[1] for c in calls}, {"powershell.exe"})

    print("\n[a run that brings a window to the front keeps the measured route]")
    calls.clear()
    d.read(focus="Games")
    check("focus -> the console-window route", [c[0] for c in calls], ["window"])

    print("\n[a test that passes only spawn gets it for both]")
    calls.clear()
    Desktop(tmpdir() / "state", spawn=fake("only", calls), timeout=5).screenshot()
    check("spawn used", [c[0] for c in calls], ["only"])

    print("\n[the real default: no injected spawn uses the windowless launcher]")
    d0 = Desktop(tmpdir() / "state")
    check("hidden default is _spawn_hidden_default", d0._spawn_hidden, Desktop._spawn_hidden_default)
    check("focus default is _spawn_default", d0._spawn, Desktop._spawn_default)

    print("\n[the plan the scheduled task runs]")
    cwd = tmpdir() / "desktop"
    pyw = PureWindowsPath(r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe")
    PS = PureWindowsPath(POWERSHELL)   # Windows path semantics for .stem / .name on any host
    prog, args, task = C.hidden_plan(PS, cwd, ("-File", "agent.ps1"), pyw)
    check("the task starts pythonw.exe (a GUI program, no console)", prog.name, "pythonw.exe")
    check("isolated mode, then the launcher, then PowerShell and its arguments",
          args, ("-I", str(cwd / C.HIDDEN_LAUNCHER_NAME), str(POWERSHELL), "-File", "agent.ps1"))
    check("its own task name, apart from the focus route's",
          (task, task != C._task_name(PS.stem)), ("ark-preupdate-launch-powershell-hidden", True))

    print("\n[the launcher starts its child with CREATE_NO_WINDOW and waits for it]")
    tree = ast.parse(C.HIDDEN_LAUNCHER)
    calls_ast = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "call"]
    flags = [kw.value.value for c in calls_ast for kw in c.keywords
             if kw.arg == "creationflags" and isinstance(kw.value, ast.Constant)]
    check("subprocess.call (waits), creationflags 0x08000000", flags, [0x08000000])

    print("\n[_spawn_hidden_via_task writes the launcher and hands the plan to the task route]")
    seen = []
    saved = C._spawn_via_task, C._pythonw
    try:
        C._spawn_via_task = lambda exe, cwd, args=(), **kw: seen.append((PureWindowsPath(exe).name, args, kw)) or True
        C._pythonw = lambda: pyw
        work = tmpdir() / "work"
        got = C._spawn_hidden_via_task(PS, work, ("-File", "a.ps1"))
        check("launched", got, True)
        check("launcher written next to the script", (work / C.HIDDEN_LAUNCHER_NAME).read_text(encoding="utf-8"),
              C.HIDDEN_LAUNCHER)
        check("task route got pythonw.exe and the hidden task name",
              (seen[0][0], seen[0][2]["task"].endswith("-hidden")), ("pythonw.exe", True))

        print("\n[no pythonw.exe: falls back to the plain route instead of not taking the picture]")
        seen.clear()
        C._pythonw = lambda: None
        C._spawn_hidden_via_task(PS, work, ("-File", "a.ps1"))
        check("plain route with PowerShell itself", (seen[0][0], seen[0][2]), ("powershell.exe", {}))

        print("\n[the OK-WW failure screenshot goes windowless too]")
        from ark_relay.features import handle
        used = []
        saved_h = C._spawn_hidden_via_task

        def hidden(exe, cwd, args=()):
            used.append(PureWindowsPath(exe).name)
            out.write_bytes(b"\x89PNG" + b"0" * 20_000)
            return True
        C._spawn_hidden_via_task = hidden
        C._spawn_via_task = lambda *a, **k: used.append("plain") or True
        try:
            out = tmpdir() / "screen.png"
            check("screenshot saved", handle._screenshot_to(out), True)
            check("only the windowless route was used", used, ["pwsh.exe"])
        finally:
            C._spawn_hidden_via_task = saved_h
    finally:
        C._spawn_via_task, C._pythonw = saved


def _part_desktop_screenshot():
    """Desktop.screenshot(): one picture of the real desktop through the interactive
agent, None when the agent does not come back with a file. No Windows here:
the spawn is faked to behave like the agent (write the result JSON, drop the
png the request names).
    """
    import json
    import threading

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.desktop import Desktop


    def agent(write_png=True, ok=True):
        """A fake interactive session: reads the request the way agent.ps1 does."""
        seen = []

        def spawn(exe, cwd, args):
            req, res = Path(args[-2]), Path(args[-1])
            r = json.loads(req.read_text(encoding="utf-8"))
            seen.append(r)
            if write_png:
                Path(r["shot"]).write_bytes(b"\x89PNG fake")
            res.write_text(json.dumps({"ok": ok, "log": ["shot"], "ocr": [], "clicked": []}), encoding="utf-8")
            return True
        spawn.seen = seen
        return spawn


    print("[能截到：返回 png 路径，请求里只有一个 shot 动作、不做 OCR]")
    sp = agent()
    d = Desktop(tmpdir() / "state", spawn=sp, timeout=5)
    shot = d.screenshot()
    check("拿到文件", shot is not None and shot.is_file(), True)
    check("文件名是 shot-<id>.png", shot.name.startswith("shot-") and shot.suffix == ".png", True)
    check("请求只有 shot 一个动作", sp.seen[0]["actions"], [{"act": "shot"}])
    check("请求不带 focus（不抢前台）", sp.seen[0]["focus"], None)

    print("\n[助手回来了但没写图：None]")
    d2 = Desktop(tmpdir() / "state", spawn=agent(write_png=False), timeout=5)
    check("None", d2.screenshot(), None)

    print("\n[助手说失败：None，即使有图]")
    d3 = Desktop(tmpdir() / "state", spawn=agent(ok=False), timeout=5)
    check("None", d3.screenshot(), None)

    print("\n[助手起不来：None，不抛]")
    d4 = Desktop(tmpdir() / "state", spawn=lambda *a: False, timeout=5)
    check("None", d4.screenshot(), None)

    print("\n[读图文件：请求只有 ocrfile 一个动作，行原样回来；失败 None]")
    seen = []


    def ocr_agent(exe, cwd, args):
        req, res = Path(args[-2]), Path(args[-1])
        seen.append(json.loads(req.read_text(encoding="utf-8")))
        res.write_text(json.dumps({"ok": True, "log": ["ocrfile 1 行"], "clicked": [],
                                   "ocr": [{"text": "10.22~11.11", "x": 609, "y": 172, "w": 91, "h": 22}]},
                                  ensure_ascii=False), encoding="utf-8")
        return True


    d5 = Desktop(tmpdir() / "state", spawn=ocr_agent, timeout=5)
    img = tmpdir() / "img.png"
    got = d5.read_file(img)
    check("请求", seen[0]["actions"], [{"act": "ocrfile", "path": str(img)}])
    check("行", [(x.text, x.x, x.y) for x in got or []], [("10.22~11.11", 609, 172)])
    check("助手起不来：None", Desktop(tmpdir() / "state", spawn=lambda *a: False, timeout=5).read_file(img), None)

    print("\n[two threads (task pictures and a launcher OCR): one agent at a time]")
    live, peak = [0], [0]


    def slow_spawn(exe, cwd, args):
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        time.sleep(0.3)
        live[0] -= 1
        return False          # the agent "did not come back"; only the overlap matters here


    ds = [Desktop(tmpdir() / "state", spawn=slow_spawn, timeout=2) for _ in range(2)]
    ts = [threading.Thread(target=d.screenshot) for d in ds]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    check("never two agents at once", peak[0], 1)


def _part_desktop_workfiles():
    """The desktop agent's working files do not pile up in state/desktop/ (review 2026-10-13, s5 #7).
    """
    import json
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.desktop import Desktop


    def agent(exe, cwd, args):
        """Behaves like the agent: a screenshot (and its 2x copy for OCR), then the result."""
        req, res = Path(args[-2]), Path(args[-1])
        r = json.loads(req.read_text(encoding="utf-8"))
        shot = Path(r["shot"])
        shot.write_bytes(b"\x89PNG fake")
        shot.with_name(shot.stem + "-x2.png").write_bytes(b"\x89PNG fake")
        res.write_text(json.dumps({"ok": True, "log": [], "ocr": [{"text": "开始游戏"}], "clicked": ["开始游戏"]}),
                       encoding="utf-8")
        return True


    state = tmpdir() / "state"
    d = Desktop(state, spawn=agent, timeout=5)
    work = state / "desktop"
    work.mkdir(parents=True, exist_ok=True)
    week_ago = time.time() - 8 * 24 * 3600
    stale = [work / "req-0000aaaa.json", work / "res-0000aaaa.json", work / "shot-0000aaaa.png",
             work / "shot-0000aaaa-x2.png"]
    for f in stale:
        f.write_bytes(b"old")
        os.utime(f, (week_ago, week_ago))
    others = [work / "image-ocr.json", work / "poster.png"]       # error_evidence, wuwa_posters
    for f in others:
        f.write_bytes(b"keep")
        os.utime(f, (week_ago, week_ago))

    print("[一次读屏、一次点字之后]")
    scr = d.read()
    check("读到了字", scr.has("开始游戏"), True)
    check("点到了", d.click_text("开始游戏"), True)
    check("没有留下请求文件", sorted(p.name for p in work.glob("req-*.json")), [])
    check("没有留下结果文件", sorted(p.name for p in work.glob("res-*.json")), [])
    check("这次的截图还在（问题记录里引着它的路径）", scr.shot is not None and Path(scr.shot).is_file(), True)
    check("一周前的截图和请求、结果都清掉了", [f.name for f in stale if f.exists()], [])
    check("同一个文件夹里别的功能的文件没动", [f.name for f in others if f.exists()], [f.name for f in others])

    print("\n[助手没起来：请求文件也不留]")
    d2 = Desktop(state, spawn=lambda *a: False, timeout=5)
    d2.read()
    check("没有留下请求文件", sorted(p.name for p in work.glob("req-*.json")), [])


def _part_spawn_direct():
    """The installed relay starts programs itself; each scheduled-task launch has a name of its own
(audit 11-08 A-21; dispatch relay-opt-round4-1108 R4-02; preupdate_common._spawn_here).
    """
    import subprocess
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import preupdate as C


    class SI:
        """subprocess.STARTUPINFO (Windows only)."""

        def __init__(self):
            self.dwFlags, self.wShowWindow = 0, 0


    popens, tasks = [], []
    answer = [None]          # an OSError to raise from Popen, or None


    def fake_popen(argv, **kw):
        popens.append((list(argv), kw))
        if answer[0] is not None:
            raise answer[0]
        return SimpleNamespace(pid=4242)


    def fake_task(exe, cwd, args=(), **kw):
        tasks.append((Path(exe).name, tuple(args)))
        return True


    here = [True]
    saved = (subprocess.Popen, getattr(subprocess, "STARTUPINFO", None), C._here_in_console, C._logon_env,
             C._spawn_via_task, C._direct_refused[0])
    subprocess.Popen, subprocess.STARTUPINFO = fake_popen, SI
    C._here_in_console = lambda: here[0]
    C._logon_env = lambda: {"USERPROFILE": "C:\\Users\\Administrator", "PATH": "C:\\Windows"}
    C._spawn_via_task = fake_task
    EXE = Path("D:/ark/okww/ok-ww.exe")
    work = tmpdir()
    try:
        print("[中继就在桌面会话里：直接启动，不走 PowerShell 计划任务]")
        check("启动成功", C._spawn_interactive(EXE, work, ("-t", "1"), require_console=True, minimized=True), True)
        argv, kw = popens[-1]
        check("命令行原样", argv, [str(EXE), "-t", "1"])
        check("脱离中继计划任务的作业（中继重启不连带）", bool(kw["creationflags"] & C._CREATE_BREAKAWAY_FROM_JOB), True)
        check("带自己的控制台（和计划任务那条路一样）", bool(kw["creationflags"] & C._CREATE_NEW_CONSOLE), True)
        check("用登录用户的环境变量，不是中继的", kw["env"].get("USERPROFILE"), "C:\\Users\\Administrator")
        check("最小化、不抢前台", (kw["startupinfo"].dwFlags & C._STARTF_USESHOWWINDOW, kw["startupinfo"].wShowWindow),
              (C._STARTF_USESHOWWINDOW, C._SW_SHOWMINNOACTIVE))
        check("工作目录", kw["cwd"], str(work))
        check("没建计划任务", tasks, [])

        print("\n[无窗口那条路：CREATE_NO_WINDOW，不写 pythonw 启动器]")
        PS = Path("C:/Program Files/PowerShell/7/pwsh.exe")
        check("启动成功", C._spawn_hidden_via_task(PS, work, ("-File", "a.ps1")), True)
        argv, kw = popens[-1]
        check("没有窗口", bool(kw["creationflags"] & C._CREATE_NO_WINDOW), True)
        check("……也不另开控制台", bool(kw["creationflags"] & C._CREATE_NEW_CONSOLE), False)
        check("……照样脱离作业", bool(kw["creationflags"] & C._CREATE_BREAKAWAY_FROM_JOB), True)
        check("没写无窗口启动器", (work / C.HIDDEN_LAUNCHER_NAME).exists(), False)
        check("没建计划任务", tasks, [])

        print("\n[启动失败（不是不许脱离）：这一次走计划任务，下次照旧先直接启动]")
        answer[0] = FileNotFoundError(2, "not found")
        check("走计划任务启动成功", C._spawn_interactive(EXE, work, require_console=True), True)
        check("计划任务启动的是它", tasks[-1][0], "ok-ww.exe")
        answer[0] = None
        n = len(tasks)
        C._spawn_interactive(EXE, work, require_console=True)
        check("下一次又直接启动了", len(tasks), n)

        print("\n[作业不许脱离（拒绝访问）：这次和以后都走计划任务]")
        denied = OSError(13, "Access is denied")
        denied.winerror = C._ERROR_ACCESS_DENIED
        answer[0] = denied
        n_pop, n = len(popens), len(tasks)
        check("走计划任务启动成功", C._spawn_interactive(EXE, work, require_console=True), True)
        answer[0] = None
        C._spawn_interactive(EXE, work, require_console=True)
        check("之后不再试直接启动", (len(popens) - n_pop, len(tasks) - n), (1, 2))
        C._direct_refused[0] = False

        print("\n[不在桌面会话 / 不是管理员 / 取不到环境：照旧走计划任务]")
        here[0] = False
        n_pop = len(popens)
        C._spawn_hidden_via_task(PS, work, ())
        check("不在桌面会话：没直接启动", len(popens), n_pop)
        here[0] = True
        C._logon_env = lambda: None
        C._spawn_interactive(EXE, work, require_console=True)
        check("取不到登录用户的环境：没直接启动", len(popens), n_pop)
    finally:
        (subprocess.Popen, _si, C._here_in_console, C._logon_env, C._spawn_via_task, C._direct_refused[0]) = saved
        if _si is None:
            del subprocess.STARTUPINFO
        else:
            subprocess.STARTUPINFO = _si

    print("[走不了直接启动的原因：每个原因在日志里说一次（INFO），部署后看得见]")
    import logging
    said = []


    class _Rows(logging.Handler):
        def emit(self, record):
            said.append((record.levelname, record.getMessage()))


    h = _Rows()
    C.log.addHandler(h)
    level = C.log.level
    C.log.setLevel(logging.DEBUG)
    C._not_here_said[0] = ""
    try:
        C._here_in_console()            # this Mac: no pywin32
        C._here_in_console()
    finally:
        C.log.removeHandler(h)
        C.log.setLevel(level)
    check("说了一次、是 INFO、说了原因", [(lv, "看不出中继是不是在桌面会话里" in m) for lv, m in said], [("INFO", True)])

    print("\n[计划任务那条路：每次一个新任务名]")
    scripts = []
    real_run = subprocess.run
    subprocess.run = lambda argv, **kw: scripts.append(argv[-1]) or SimpleNamespace(returncode=0, stderr=b"")
    try:
        C._spawn_via_task(PS, work, ("-File", "a.ps1"))
        C._spawn_via_task(PS, work, ("-File", "a.ps1"))
        C._spawn_via_task(PS, work, (), task="ark-efstart")
    finally:
        subprocess.run = real_run


    def name_of(ps):
        return ps.split('Register-ScheduledTask -TaskName "', 1)[1].split('"', 1)[0]


    names = [name_of(s) for s in scripts]
    check("两次启动同一个程序：任务名不同", names[0] != names[1], True)
    check("……都以程序名开头", all(n.startswith(C._task_name(PS.stem) + "-") for n in names[:2]), True)
    check("……一个脚本里注册、启动、注销的是同一个名字", all(s.count(f'"{n}"') == 4 for s, n in zip(scripts, names, strict=True)), True)
    check("指定了任务名的也加后缀", names[2].startswith("ark-efstart-") and len(names[2]) == len("ark-efstart-") + 8, True)


def _part_display_wake():
    """display_wake: the display is woken while AUTO-MAS starts Endfield through its launcher."""
    import json
    import logging
    import threading
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import config, desktop, watch
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import display_wake as dw


    FIX = fx_dir(Path(__file__), "fixtures") / "display-wake-2026-10-16" / "app.log"
    LINES = FIX.read_text(encoding="utf-8").splitlines()


    def at(hms: str) -> datetime:
        return datetime.fromisoformat(f"2026-10-16 {hms}").replace(tzinfo=SERVER_TZ)


    def stamp(line: str) -> datetime:
        return datetime.fromisoformat(line[:23]).replace(tzinfo=SERVER_TZ)


    class _ClockTail:
        """app.log as the thread sees it at `now`: every line written by then, once."""

        def __init__(self, lines):
            self.lines, self.i, self.now = lines, 0, None

        def read(self):
            out = []
            while self.i < len(self.lines) and stamp(self.lines[self.i]) <= self.now:
                out.append(self.lines[self.i])
                self.i += 1
            return out


    def replay(lines, start: str, end: str, every: float = dw.POLL_SECONDS):
        """Run the thread's step on a fake clock that looks every `every` seconds (the
    backstop alone, no change notification). Returns the moments a wake was issued."""
        waker, tail, wakes = dw.Waker(), _ClockTail(lines), []
        now, stop = at(start), at(end)
        while now <= stop:
            tail.now = now
            dw.step(waker, tail, lambda: wakes.append(tail.now) or True, now)
            now += timedelta(seconds=every)
        return wakes


    print("[attempt 1, 13:21: the display is woken right after AUTO-MAS hands off to the launcher]")
    HANDOFF1, TIMEOUT1 = at("13:21:28.423"), at("13:23:36.444")
    wakes = replay(LINES, "13:21:00", "13:27:00")
    first = wakes[0] if wakes else None
    check("a wake is issued for attempt 1", first is not None)
    if first:
        check(f"first wake {first:%H:%M:%S} within one backstop look of the hand-off line",
              HANDOFF1 <= first <= HANDOFF1 + timedelta(seconds=dw.POLL_SECONDS))
        check("well inside AUTO-MAS's 120 s launcher wait", first < HANDOFF1 + timedelta(seconds=120))
    att1 = [w for w in wakes if w < TIMEOUT1]
    check("re-woken at most every REWAKE_SECONDS during attempt 1",
          all((b - a).total_seconds() >= dw.REWAKE_SECONDS for a, b in zip(att1, att1[1:], strict=False)))
    HANDOFF2, UP2 = at("13:23:36.799"), at("13:26:14.036")
    att2 = [w for w in wakes if w >= TIMEOUT1]
    check("attempt 2 (retry) re-arms and wakes at once",
          bool(att2) and att2[0] <= HANDOFF2 + timedelta(seconds=dw.POLL_SECONDS))
    check("no wake after AUTO-MAS logs 运行脚本任务 (game up, 13:26:14)", [w for w in wakes if w > UP2], [])
    print(f"    wakes: {', '.join(f'{w:%H:%M:%S}' for w in wakes)}")

    print("\n[a change notification: the wake follows the hand-off line within a second or two]")
    wakes = replay(LINES, "13:21:27", "13:21:40", every=1.0)
    check("woken by 13:21:30", bool(wakes) and wakes[0] <= at("13:21:30"))

    print("\n[attempt 3, 13:53: woken, then left alone once the game is up]")
    wakes = replay(LINES, "13:52:50", "14:05:00")
    check("one wake right after 13:53:33.918",
          bool(wakes) and at("13:53:33.918") <= wakes[0] <= at("13:53:44"))
    check("none after 13:54:52 (运行脚本任务)", [w for w in wakes if w > at("13:54:52.502")], [])

    print("\n[no MaaEnd launch, no wake: OK-WW finishing and MaaEnd refused at its config check, 09:33-09:34]")
    check("no wake 09:33:50-09:40:00", replay(LINES, "09:33:50", "09:40:00"), [])

    print("\n[bounded: a hand-off with no end line wakes for WINDOW_SECONDS at most]")
    only = [ln for ln in LINES if ln.startswith("2026-10-16 13:21:28.423")]
    wakes = replay(only, "13:21:00", "13:45:00")
    check("hand-off line alone gives wakes", bool(wakes))
    check(f"at most {dw.WINDOW_SECONDS // dw.REWAKE_SECONDS} wakes ({len(wakes)})",
          len(wakes) <= dw.WINDOW_SECONDS // dw.REWAKE_SECONDS)
    check("none later than WINDOW_SECONDS after the hand-off",
          all(w < HANDOFF1 + timedelta(seconds=dw.WINDOW_SECONDS) for w in wakes))

    print("\n[an old hand-off line read again (app.log re-read from its start) wakes nothing]")
    waker = dw.Waker()
    waker.feed(only)
    check("not due 10 minutes later", waker.due(at("13:31:30")), False)

    print("\n[a failed wake is retried after REWAKE_SECONDS]")
    waker, tail, calls = dw.Waker(), _ClockTail(only), []
    for hms in ("13:21:29", "13:21:59", "13:22:29", "13:22:30"):
        tail.now = at(hms)
        dw.step(waker, tail, lambda: calls.append(tail.now) or False, at(hms))
    check("tried at 13:21:29 and again at 13:22:29", calls, [at("13:21:29"), at("13:22:29")])

    print("\n[AUTO-MAS v5.7.0-beta.5: the bare mode line arms it, for 「MaaEnd 启动」 too (10-17)]")
    B5 = "2026-10-16 15:00:03.832 | INFO     | MaaEnd 自动代理 | "
    B5_UP = "2026-10-16 15:01:30.100 | INFO     | MaaEnd 自动代理 | 运行脚本任务: D:\\ark\\maaend\\MaaEnd.exe"
    for mode in ("MaaEnd 启动", "启动器启动"):
        wakes = replay([B5 + f"启动方式为「{mode}」", B5_UP], "15:00:00", "15:10:00")
        check(f"「{mode}」 alone: woken within one backstop look",
              bool(wakes) and wakes[0] <= at("15:00:03.832") + timedelta(seconds=dw.POLL_SECONDS))
        check(f"「{mode}」: none after 运行脚本任务", [w for w in wakes if w > at("15:01:30.100")], [])
    check("「MAS 启动」 (Endfield.exe started directly, no launcher window): no wake",
          replay([B5 + "启动方式为「MAS 启动」"], "15:00:00", "15:10:00"), [])
    check("the scheduler's own mode line (MaaEnd 调度器, before the hand-off): no wake",
          replay([ln for ln in LINES if "MaaEnd 调度器 | 启动方式为" in ln], "13:21:00", "13:30:00"), [])


    class _Levels(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.levels = []

        def emit(self, record):
            self.levels.append(record.levelno)


    lv = _Levels()
    dw.log.addHandler(lv)
    _old_level = dw.log.level
    dw.log.setLevel(logging.DEBUG)
    waker, tail = dw.Waker(), _ClockTail(only)


    def _boom():
        raise OSError("no agent")


    for hms in ("13:21:29", "13:22:29", "13:23:29"):
        tail.now = at(hms)
        dw.step(waker, tail, _boom, at(hms))
    dw.log.removeHandler(lv)
    dw.log.setLevel(_old_level)
    check("a failing wake goes to the group (WARNING) once per attempt, then only to the log",
          lv.levels, [logging.WARNING, logging.INFO, logging.INFO])

    print("\n[Tail: starts at the end of app.log, follows AUTO-MAS's rotation]")
    d = tmpdir()
    f = d / "app.log"
    f.write_text("\n".join(LINES[:40]) + "\n", encoding="utf-8")
    t = dw.Tail(f)
    check("lines from before the start are not read", t.read(), [])
    with f.open("a", encoding="utf-8") as fh:
        fh.write(LINES[57] + "\n" + LINES[58][:30])
    check("an appended line is read, a half line is held", t.read(), [LINES[57]])
    f.write_text(LINES[58] + "\n", encoding="utf-8")
    check("after rotation the new file is read from its start", t.read(), [LINES[58]])

    print("\n[Desktop.wake: one windowless agent run with the wake act; the agent wakes the display]")
    calls = []


    def _spawn(tag):
        def spawn(exe, cwd, args):
            req, res = Path(args[-2]), Path(args[-1])
            calls.append((tag, json.loads(req.read_text(encoding="utf-8"))["actions"]))
            res.write_text(json.dumps({"ok": True, "log": ["wake"], "ocr": [], "clicked": []}), encoding="utf-8")
            return True
        return spawn


    dk = desktop.Desktop(tmpdir() / "state", spawn=_spawn("window"), spawn_hidden=_spawn("hidden"), timeout=5)
    check("wake() reports success", dk.wake(), True)
    check("windowless route, the single wake act", calls, [("hidden", [{"act": "wake"}])])
    check("the agent's wake act calls WakeDisplay", "'wake' { WakeDisplay;" in desktop.AGENT_PS)

    print("\n[start(): the thread reads a live app.log and wakes (Windows switched on, the agent faked)]")
    woken = threading.Event()
    real_windows, real_wake, real_poll = config.IS_WINDOWS, desktop.Desktop.wake, dw.POLL_SECONDS
    real_watch = watch.start
    try:
        config.IS_WINDOWS = True
        watch.start = lambda path, ev: False      # no change notification: the backstop alone
        desktop.Desktop.wake = lambda self: woken.set() or True
        dw.POLL_SECONDS = 0.3
        root = tmpdir()
        (root / "debug").mkdir()
        applog = root / "debug" / "app.log"
        applog.write_text(LINES[0] + "\n", encoding="utf-8")

        class _Cfg:
            automas_dir = str(root)
            state_dir = str(tmpdir())

        check("start() arms the thread", dw.start(_Cfg), True)
        now = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with applog.open("a", encoding="utf-8") as fh:
            fh.write(f"{now}.423 | INFO     | MaaEnd 自动代理 | 启动方式为「启动器启动」，将由 MAS 经终末地官方启动器拉起游戏\n")
        check("woken within 3 s of the hand-off line landing", woken.wait(3.0))
    finally:
        config.IS_WINDOWS, desktop.Desktop.wake, watch.start = real_windows, real_wake, real_watch
        time.sleep(dw.POLL_SECONDS)
        dw.POLL_SECONDS = real_poll


    class _NoDir:
        automas_dir = None
        state_dir = str(tmpdir())


    config.IS_WINDOWS = True
    check("no AUTO-MAS folder: start() returns False", dw.start(_NoDir), False)
    config.IS_WINDOWS = real_windows


def _part_selfupdate_atomic_sha256():
    """Self-update lands all files or none, and checks them by SHA-256 (review of 2026-10-07, item 4).
    """
    import hashlib
    import json
    import shutil
    import subprocess
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import os
    from ark_relay.features import selfupdate as su
    from ark_relay.core.statestore import StateStore

    os.environ[su.GITHUB_FALLBACK_ENV] = "1"     # the GitHub doors, as in test_selfupdate_doors.py
    RELAY = Path(__file__).resolve().parents[1]


    su.time = _NoSleep
    su._cos = lambda: None
    sha1 = lambda b: hashlib.sha1(b).hexdigest()  # noqa: E731
    sha256 = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
    OLD_A, OLD_B = b"print('a old')\n", b"print('b old')\n"
    NEW_A, NEW_B = b"print('a new')\n", b"print('b new')\n"


    def serve(man: dict, bodies: dict):
        """Every door answers with this manifest and these files."""
        data = json.dumps(man).encode("utf-8")

        def get(url, timeout=20):
            rel = url.split("/relay/", 1)[-1]
            if "/relay-" in url and rel == "manifest.json":
                return None
            return data if rel == "manifest.json" else bodies.get(rel)
        su._get_once = get
        su._last_good = ""


    def machine():
        root = tmpdir()
        (root / "state").mkdir()
        (root / "a.py").write_bytes(OLD_A)
        (root / "b.py").write_bytes(OLD_B)
        StateStore(root / "state").set("versions", "code", "20261001000000")
        return root


    def leftovers(root: Path) -> list:
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                      if p.name not in ("a.py", "b.py") and not p.relative_to(root).as_posix().startswith("state"))


    BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
    NEW = {"version": 20261007000000,
           "files": {"a.py": sha1(NEW_A), "b.py": sha1(NEW_B)},
           "sha256": {"a.py": sha256(NEW_A), "b.py": sha256(NEW_B)}}
    BODIES = {"a.py": NEW_A, "b.py": NEW_B}


    def failed_round(root, label):
        check(f"{label}：返回空", su.check(root, BASE), [])
        check(f"{label}：a.py 还是原来的", (root / "a.py").read_bytes(), OLD_A)
        check(f"{label}：b.py 还是原来的", (root / "b.py").read_bytes(), OLD_B)
        check(f"{label}：版本号没前进", StateStore(root / "state").get("versions", "code"), "20261001000000")
        check(f"{label}：没留下「已更新」的播报", su.take_announcement(root), None)
        check(f"{label}：失败记下了（下次开机重来、会报出来）", bool(su.take_failure(root)), True)
        check(f"{label}：没留下暂存文件", leftovers(root), [])


    print("[写到第二个文件时磁盘出错：两个原文件都不许动]")
    root = machine()
    serve(NEW, BODIES)
    real_write = su._atomic_write
    n = [0]


    def write_fails_second(target, data):
        n[0] += 1
        if n[0] == 2:
            raise OSError(28, "No space left on device")
        real_write(target, data)


    su._atomic_write = write_fails_second
    try:
        failed_round(root, "写入失败")
    finally:
        su._atomic_write = real_write

    print("\n[换到第二个文件时出错（文件被占用）：已换上的那个要改回原样]")
    root = machine()
    serve(NEW, BODIES)
    real_swap = getattr(su, "_swap_in", None)
    real_replace = os.replace
    m = [0]


    def swap_fails_second(src, dst):
        m[0] += 1
        if m[0] == 2:
            raise PermissionError(32, "being used by another process")
        real_replace(src, dst)


    su._swap_in = swap_fails_second
    try:
        failed_round(root, "替换失败")
    finally:
        if real_swap is None:
            del su._swap_in
        else:
            su._swap_in = real_swap

    print("\n[一切正常：两个都换上，版本号前进，没有暂存残留]")
    root = machine()
    serve(NEW, BODIES)
    check("两个都更新了", su.check(root, BASE), ["a.py", "b.py"])
    check("a.py 是新的", (root / "a.py").read_bytes(), NEW_A)
    check("b.py 是新的", (root / "b.py").read_bytes(), NEW_B)
    check("版本号前进", StateStore(root / "state").get("versions", "code"), "20261007000000")
    check("没留下暂存文件", leftovers(root), [])

    print("\n[SHA-256 对不上（SHA-1 却对得上）：按 SHA-256 判，不更新]")
    root = machine()
    bad = dict(NEW, sha256={"a.py": sha256(b"something else"), "b.py": sha256(NEW_B)})
    serve(bad, BODIES)
    check("不更新", su.check(root, BASE), [])
    check("a.py 原封不动", (root / "a.py").read_bytes(), OLD_A)
    check("b.py 也没动（整轮放弃）", (root / "b.py").read_bytes(), OLD_B)

    print("\n[SHA-256 表缺一个文件：这份清单不可信，整轮不更新]")
    root = machine()
    serve(dict(NEW, sha256={"a.py": sha256(NEW_A)}), BODIES)
    check("不更新", su.check(root, BASE), [])
    check("a.py 原封不动", (root / "a.py").read_bytes(), OLD_A)

    print("\n[旧格式清单（只有 SHA-1）：照旧能更新——兼容这一版之前做的清单]")
    root = machine()
    serve({"version": 20261007000000, "files": {"a.py": sha1(NEW_A), "b.py": sha1(NEW_B)}}, BODIES)
    check("两个都更新了", su.check(root, BASE), ["a.py", "b.py"])

    print("\n[本机已是新的：按 SHA-256 判出不用动]")
    root = machine()
    (root / "a.py").write_bytes(NEW_A)
    (root / "b.py").write_bytes(NEW_B)
    serve(NEW, BODIES)
    check("没有要改的", su.check(root, BASE), [])
    check("版本号记下", StateStore(root / "state").get("versions", "code"), "20261007000000")

    print("\n[make-manifest.py：files 仍是 SHA-1（给旧机器），另有一张一一对应的 sha256 表]")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "relay"
        shutil.copytree(RELAY, copy, ignore=shutil.ignore_patterns("tests", "state", "__pycache__"))
        out = subprocess.run([sys.executable, "make-manifest.py"], cwd=copy, capture_output=True, text=True)
        check("生成器跑得起来", out.returncode, 0)
        man = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
        files, s256 = man.get("files") or {}, man.get("sha256") or {}
        check("有 sha256 表", bool(s256), True)
        check("两张表文件一样", sorted(s256) == sorted(files), True)
        check("files 每一项都是那个文件的 SHA-1",
              [f for f, h in files.items() if h != sha1((copy / f).read_bytes())], [])
        check("sha256 每一项都是那个文件的 SHA-256",
              [f for f, h in s256.items() if h != sha256((copy / f).read_bytes())], [])


def _part_selfupdate_cos():
    """selfupdate.py's first door is the COS bucket; GitHub's four stay as the fallback."""
    import hashlib
    import io
    import json
    import os
    import threading
    import zipfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import selfupdate as su
    from ark_relay.core.statestore import StateStore


    su.time = _NoSleep
    sha = lambda b: hashlib.sha1(b).hexdigest()  # noqa: E731


    class FakeCos:
        prefix = "relay"
        host = "bucket.cos.ap-shanghai.myqcloud.com"

        def __init__(self, objects):
            self.objects = objects      # {key: bytes}
            self.got = []

        def authorization(self, *a, **k):
            return "sig"


    Net = _net_class(su)


    def fake_cos_get(cos, key, timeout=20):
        cos.got.append(key)
        return cos.objects.get(key)


    def workdir(files, code_version=""):
        return _workdir(StateStore, files, code_version)


    def bundle(files: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for rel, body in files.items():
                z.writestr(rel, body)
        return buf.getvalue()


    def setup(cos_objects, doors, local_files, local_ver):
        su._cos_get = fake_cos_get
        net = Net(doors); su._get_once = net.get; su._last_good = ""
        cos = FakeCos(cos_objects) if cos_objects is not None else None
        su._cos = lambda: cos
        return net, cos, workdir(local_files, local_ver)


    OLD_A, NEW_A, NEW_B = b"a v1\n", b"a v2\n", b"b v2\n"
    FILES_V2 = {"ark_relay/a.py": sha(NEW_A), "ark_relay/b.py": sha(NEW_B)}
    MAN_V2 = json.dumps({"version": 20260918020000, "files": FILES_V2}).encode()

    os.environ.pop(su.GITHUB_FALLBACK_ENV, None)      # the default: GitHub doors off
    print("[COS 上是新版：只碰 COS，文件全部来自 bundle，GitHub 一次都不问]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000, "uploaded": "2026-09-18T02:00:00+00:00"}',
         "20260918020000/manifest.json": MAN_V2,
         "20260918020000/bundle.zip": bundle({"ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B})},
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("两个文件都更新了", sorted(updated), ["ark_relay/a.py", "ark_relay/b.py"])
    check("落盘内容对", (root / "ark_relay/a.py").read_bytes(), NEW_A)
    check("COS 请求顺序：latest → manifest → bundle", cos.got, ["latest.json", "20260918020000/manifest.json", "20260918020000/bundle.zip"])
    check("GitHub 一扇门都没问", net.tried, [])
    check("版本号记下了", StateStore(root / "state").get("versions", "code"), "20260918020000")

    print("\n[COS 上不比本机新：只读一次 latest.json，到此为止——GitHub 一扇门都不问]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260917000000}'},
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    su._record_failure(root, "上次的失败", 1, 1, [])
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("COS 只碰了 latest.json", cos.got, ["latest.json"])
    check("不更新", updated, [])
    check("GitHub 一扇门都没问", net.tried, [])
    check("磁盘没动", (root / "ark_relay/a.py").read_bytes(), OLD_A)
    check("已是最新 = 没有未完成的事，旧的失败报告清掉", su.take_failure(root), None)

    print("\n[默认不开备用线路：COS 的清单拿不到 → 记失败、一扇 GitHub 门都不问、磁盘不动]")
    os.environ.pop(su.GITHUB_FALLBACK_ENV, None)
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}'},          # manifest / bundle missing
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("不更新", updated, [])
    check("GitHub 一扇门都没问", net.tried, [])
    check("磁盘没动", (root / "ark_relay/a.py").read_bytes(), OLD_A)
    fail = su.take_failure(root)
    check("失败记下了、开机会报", bool(fail) and "备用线路已关" in fail["reason"], True)
    check("失败记录里本机版本对", fail and fail["local"], 20260917000000)

    print("\n[默认不开备用线路：bundle 哈希不对 → 记失败，不去 GitHub 补]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}', "20260918020000/manifest.json": MAN_V2,
         "20260918020000/bundle.zip": bundle({"ark_relay/a.py": b"tampered\n", "ark_relay/b.py": NEW_B})},
        {"fastly.jsdelivr.net": {"ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("不更新", updated, [])
    check("GitHub 一扇门都没问", net.tried, [])
    check("b.py 虽然在包里是对的也不落盘（全有或全无）", (root / "ark_relay/b.py").read_bytes(), b"b v1\n")
    fail = su.take_failure(root)
    check("失败记下了，带着本来要更新的文件", fail and sorted(fail["files"]), ["ark_relay/a.py", "ark_relay/b.py"])

    print("\n[默认不开备用线路：没配 COS → 一条警告 + 失败记录，不更新]")
    net, cos, root = setup(None,
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    check("不更新", su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"), [])
    check("GitHub 一扇门都没问", net.tried, [])
    check("失败记下了", bool(su.take_failure(root)), True)

    print("\n[默认不开备用线路：COS 正常时和开着一样——两个文件从 bundle 落地]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000, "uploaded": "2026-09-18T02:00:00+00:00"}',
         "20260918020000/manifest.json": MAN_V2,
         "20260918020000/bundle.zip": bundle({"ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B})},
        {}, {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    check("两个文件都更新了", sorted(su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")),
          ["ark_relay/a.py", "ark_relay/b.py"])
    check("没有失败记录", su.take_failure(root), None)

    # ---- the same situations with the switch on: every old expectation still holds ----
    print("\n[开关打开（" + su.GITHUB_FALLBACK_ENV + "=1）：以下全是备用线路的老行为]")
    os.environ[su.GITHUB_FALLBACK_ENV] = "1"

    print("\n[COS 的对象被生命周期规则删了（404）：静默退回 GitHub，整轮照常完成]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}'},          # manifest / bundle missing
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("更新照常落地", sorted(updated), ["ark_relay/a.py", "ark_relay/b.py"])
    check("问过 COS 的 manifest 没拿到就走 GitHub", "20260918020000/manifest.json" in cos.got and any(h == "fastly.jsdelivr.net" for h, _ in net.tried))

    print("\n[COS 的 bundle 里哈希不对：一个字节都不用它，退回 GitHub]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}', "20260918020000/manifest.json": MAN_V2,
         "20260918020000/bundle.zip": bundle({"ark_relay/a.py": b"tampered\n", "ark_relay/b.py": NEW_B})},
        {"fastly.jsdelivr.net": {"ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("结果仍然正确", (root / "ark_relay/a.py").read_bytes(), NEW_A)
    check("两个文件都从 GitHub 取（bundle 整体弃用）", sorted(r for _, r in net.tried), ["ark_relay/a.py", "ark_relay/b.py"])

    print("\n[latest.json 和 manifest 版本对不上：不信 COS]")
    net, cos, root = setup(
        {"latest.json": b'{"version": 20260918020000}',
         "20260918020000/manifest.json": json.dumps({"version": 20260918010000, "files": FILES_V2}).encode()},
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("走 GitHub 完成", sorted(updated), ["ark_relay/a.py", "ark_relay/b.py"])
    check("bundle 没有被请求", "20260918020000/bundle.zip" not in cos.got)

    print("\n[没配 COS：和以前一模一样]")
    net, cos, root = setup(None,
        {"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}},
        {"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("GitHub 更新", sorted(updated), ["ark_relay/a.py", "ark_relay/b.py"])

    print("\n[COS 客户端自己抛异常：不影响 GitHub 路]")
    def boom():
        raise RuntimeError("no keys")
    su._cos = boom
    net = Net({"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}}); su._get_once = net.get; su._last_good = ""
    root = workdir({"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    check("照常更新", sorted(su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")), ["ark_relay/a.py", "ark_relay/b.py"])

    print("\n[清单里已经没有的旧包文件夹：check 这一轮把它清掉，算进改动（不清的话 Python 先认文件夹，跑的还是旧代码）]")
    net = Net({"fastly.jsdelivr.net": {"manifest.json": MAN_V2, "ark_relay/a.py": NEW_A, "ark_relay/b.py": NEW_B}}); su._get_once = net.get; su._last_good = ""
    root = workdir({"ark_relay/a.py": OLD_A, "ark_relay/b.py": b"b v1\n"}, 20260917000000)
    (root / "ark_relay" / "old" / "__pycache__").mkdir(parents=True)
    (root / "ark_relay" / "old" / "__init__.py").write_bytes(b"OLD = 1\n")
    (root / "ark_relay" / "old" / "__pycache__" / "__init__.cpython-314.pyc").write_bytes(b"pyc")
    check("旧文件夹算进这一轮的改动", sorted(su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")),
          ["ark_relay/a.py", "ark_relay/b.py", "ark_relay/old/"])
    check("旧文件夹连同里面的字节码整个没了", (root / "ark_relay" / "old").exists(), False)

    print("\n[GitHub 回退是并发的，而且仍然全有或全无]")
    many = {f"ark_relay/m{i}.py": f"m{i} v2\n".encode() for i in range(12)}
    man = json.dumps({"version": 20260918030000, "files": {k: sha(v) for k, v in many.items()}}).encode()
    class SlowNet(Net):
        lock = threading.Lock()
        def __init__(self, doors):
            super().__init__(doors); self.active = 0; self.peak = 0
        def get(self, url, timeout=20):
            with self.lock:
                self.active += 1; self.peak = max(self.peak, self.active)
            try:
                time.sleep(0.05)
                return super().get(url, timeout)
            finally:
                with self.lock:
                    self.active -= 1
    su._cos = lambda: None
    net = SlowNet({"fastly.jsdelivr.net": {"manifest.json": man, **many}}); su._get_once = net.get; su._last_good = ""
    root = workdir({k: b"old\n" for k in many}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("12 个文件全更新", len(updated), 12)
    check("确实并发了（峰值 >1）", net.peak > 1)
    check(f"并发宽度用满（峰值 = PARALLEL_FETCHES = {su.PARALLEL_FETCHES}）", net.peak, min(su.PARALLEL_FETCHES, 12))
    missing_one = dict(many); missing_one.pop("ark_relay/m7.py")
    net = SlowNet({"fastly.jsdelivr.net": {"manifest.json": man, **missing_one}}); su._get_once = net.get; su._last_good = ""
    root = workdir({k: b"old\n" for k in many}, 20260917000000)
    updated = su.check(root, "https://raw.githubusercontent.com/herclyon1/maa/main/relay/")
    check("一个文件拿不到 → 一个都不落盘", (updated, (root / "ark_relay/m0.py").read_bytes()), ([], b"old\n"))

    print()
    if fails:
        print("FAILED:", fails); sys.exit(1)
    print("all checks passed")


def _part_selfupdate_doors():
    """selfupdate.py 的四扇门、粘性、拒绝旧清单、对不上哈希就一个字节都不落盘。"""
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import selfupdate as su
    from ark_relay.core.statestore import StateStore

    import os
    os.environ[su.GITHUB_FALLBACK_ENV] = "1"


    BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
    FASTLY, CDN, GCORE, RAW = ("fastly.jsdelivr.net", "cdn.jsdelivr.net",
                               "gcore.jsdelivr.net", "raw.githubusercontent.com")


    su.time = _NoSleep


    Net = _net_class(su)


    def use(net):
        su._get_once = net.get
        su._last_good = ""          # 每个用例从「没有粘性」开始
        return net


    def manifest(version, files):
        return json.dumps({"version": version, "files": files}).encode("utf-8")


    def workdir(files, code_version=""):
        return _workdir(StateStore, files, code_version)


    # ------------------------------------------------------------------ 门的顺序

    print("[四扇门的顺序：fastly → cdn → gcore → raw，raw 永远垫底]")
    alts = su._alternates(BASE + "manifest.json")
    check("四扇门都在", len(alts), 4)
    check("顺序", [su._netloc(u) for u in alts], [FASTLY, CDN, GCORE, RAW])
    check("jsDelivr 走的是同一个仓库同一个分支", alts[0],
          "https://fastly.jsdelivr.net/gh/herclyon1/maa@main/relay/manifest.json")
    check("raw 原样保留在最后", alts[-1], BASE + "manifest.json")

    print("\n[不是 raw.githubusercontent 的地址，不许自作主张换门]")
    check("别的域名原样返回", su._alternates("https://example.com/relay/a.py"),
          ["https://example.com/relay/a.py"])
    check("raw 但路径不成形（没有 owner/repo/branch/path）",
          su._alternates("https://raw.githubusercontent.com/herclyon1/maa"),
          ["https://raw.githubusercontent.com/herclyon1/maa"])

    print("\n[_pinned_base：文件按清单自己的标签取，不按分支——标签不会动，哪扇门答都是对的字节]")
    check("有 ref 就换成标签", su._pinned_base(BASE, {"ref": "relay-20260918111328"}),
          "https://raw.githubusercontent.com/herclyon1/maa/relay-20260918111328/relay/")
    check("四扇门都跟着标签走",
          [u.split("/relay/")[0].rsplit("/", 1)[-1] for u in
           su._alternates(su._pinned_base(BASE, {"ref": "relay-20260918111328"}) + "a.py")],
          ["maa@relay-20260918111328", "maa@relay-20260918111328", "maa@relay-20260918111328",
           "relay-20260918111328"])
    check("没有 ref（09-18 之前的清单）照旧走分支", su._pinned_base(BASE, {}), BASE)
    check("ref 不是纯标签名（清单是网上来的）就不拼进地址",
          su._pinned_base(BASE, {"ref": "../../evil"}), BASE)
    check("ref 不是字符串也不拼", su._pinned_base(BASE, {"ref": 20260918}), BASE)
    check("不是 raw 的地址不动", su._pinned_base("https://example.com/relay/", {"ref": "relay-1"}),
          "https://example.com/relay/")

    print("\n[_netloc：取主机名，取不到就原样返回，任何输入都不许抛异常]")
    check("普通地址", su._netloc("https://fastly.jsdelivr.net/gh/a/b@c/d.py"), FASTLY)
    check("raw", su._netloc(BASE + "a.py"), RAW)
    check("没有主机名就返回原串", su._netloc("这不是地址"), "这不是地址")
    check("空串", su._netloc(""), "")


    # -------------------------------------------------------------------- 粘性

    print("\n[粘性：上次哪扇门成了，下次先问它]")
    body = b"print('new')\n"
    sha = su._sha1(body)
    net = use(Net({GCORE: {"a.py": body}}))     # 只有 gcore 有货
    got = su._get_with_retry(BASE + "a.py", expect_sha=sha)
    check("第三扇门拿到了", got, body)
    check("按顺序一扇扇试过来", net.hosts[:3], [FASTLY, CDN, GCORE])
    check("记住了这扇门", su._last_good, GCORE)

    net = Net({GCORE: {"a.py": body}, FASTLY: {"a.py": body}})
    su._get_once = net.get                       # 不清粘性：这次要先问 gcore
    su._get_with_retry(BASE + "a.py", expect_sha=sha)
    check("下一个文件先问上次成的那扇门", net.hosts[0], GCORE)
    check("一扇就够了，没白等前两扇", len(net.tried), 1)

    print("\n[粘的那扇门黑了，其余三扇还是要试——粘性不许变成独门]")
    net = Net({RAW: {"a.py": body}})
    su._get_once = net.get                       # 粘的还是 gcore，但 gcore 这次没货
    check("最后还是拿到了", su._get_with_retry(BASE + "a.py", expect_sha=sha), body)
    check("四扇门一扇不落", sorted(set(net.hosts[:4])), sorted([FASTLY, CDN, GCORE, RAW]))
    check("粘性改判到真正成的那扇", su._last_good, RAW)


    # ------------------------------------------------------- 缓存发旧副本换下一扇门

    print("\n[某扇门发的是旧副本：换下一扇，不是整轮放弃]")
    old = b"print('old')\n"
    net = use(Net({FASTLY: {"a.py": old}, CDN: {"a.py": old},
                   GCORE: {"a.py": old}, RAW: {"a.py": body}}))
    check("最终拿到的是对得上哈希的那份", su._get_with_retry(BASE + "a.py", expect_sha=sha), body)
    check("四扇门都问过", net.hosts[:4], [FASTLY, CDN, GCORE, RAW])

    print("\n[四扇门都只有旧副本：宁可拿不到，也不许把旧的当新的用]")
    net = use(Net({h: {"a.py": old} for h in (FASTLY, CDN, GCORE, RAW)}))
    check("拿不到就是拿不到", su._get_with_retry(BASE + "a.py", expect_sha=sha), None)


    # --------------------------------------------------------------- 清单版本判定

    print("\n[比本机旧的清单必须拒绝（2026-08-21 静默降级就是这一格）]")
    check("没有版本号的旧清单也要拦（remote=0，本机有版本）", su._is_downgrade(0, 20260821110000), True)
    check("确实更旧", su._is_downgrade(20260820, 20260821), True)
    check("一样新就不算降级", su._is_downgrade(20260821, 20260821), False)
    check("更新的当然放行", su._is_downgrade(20260822, 20260821), False)
    check("本机没有版本号时不拦（全新机器要能装上）", su._is_downgrade(0, 0), False)
    check("本机没有版本号、清单有", su._is_downgrade(20260821, 0), False)

    print("\n[_manifest_version：读不出来算 0，这个 0 是要参与比较的]")
    check("正常", su._manifest_version({"version": 20260821}), 20260821)
    check("字符串数字也认", su._manifest_version({"version": "20260821"}), 20260821)
    check("没有这个字段", su._manifest_version({}), 0)
    check("不是数字", su._manifest_version({"version": "v2"}), 0)

    print("\n[_best_manifest：挑版本号最高的那一份，绕开还没刷新的门]")
    stale, fresh = manifest(20260821, {"a.py": "x"}), manifest(20260908, {"a.py": "y"})
    net = use(Net({FASTLY: {"manifest.json": stale}, CDN: {"manifest.json": stale},
                   GCORE: {"manifest.json": stale}, RAW: {"manifest.json": fresh}}))
    m = su._best_manifest(BASE)
    check("选了最新的那份", su._manifest_version(m or {}), 20260908)
    check("四扇门都问了，不是谁先答用谁", len(net.tried), 4)

    print("\n[有一扇门返回的不是 JSON：跳过它，不许拖垮整轮]")
    net = use(Net({FASTLY: {"manifest.json": b"<html>502</html>"},
                   RAW: {"manifest.json": fresh}}))
    check("照样拿到清单", su._manifest_version(su._best_manifest(BASE) or {}), 20260908)

    print("\n[四扇门全黑：老实说没有，不许瞎编一份]")
    net = use(Net({}))
    check("没有清单", su._best_manifest(BASE), None)
    check("没有清单就不更新", su.check(workdir({"a.py": old}), BASE), [])


    # ------------------------------------------------------------------ 整轮更新

    print("\n[清单更旧：整轮拒绝，磁盘上一个字节都不动]")
    root = workdir({"a.py": old}, code_version=20260908090000)
    net = use(Net({h: {"manifest.json": manifest(20260821110000, {"a.py": sha}),
                       "a.py": body} for h in (FASTLY, CDN, GCORE, RAW)}))
    check("不更新", su.check(root, BASE), [])
    check("文件原封不动", (root / "a.py").read_bytes(), old)
    check("本机版本号没被改回去",
          StateStore(root / "state").get("versions", "code"), "20260908090000")

    print("\n[一切正常：文件落盘、版本号记下、留下给下一个进程播报的记号]")
    root = workdir({"a.py": old}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000, {"a.py": sha}), "a.py": body}
             for h in (FASTLY, CDN, GCORE, RAW)}))
    check("更新了 a.py", su.check(root, BASE), ["a.py"])
    check("内容是新的", (root / "a.py").read_bytes(), body)
    check("版本号记下了",
          StateStore(root / "state").get("versions", "code"), "20260908090000")
    note = su.take_announcement(root)
    check("留了播报记号", note and note["files"], ["a.py"])

    print("\n[清单带 ref：清单从分支取，文件从标签取；分支上的旧副本碰不到这一轮]")
    class RefNet(Net):
        def get(self, url, timeout=20):
            host = su._netloc(url)
            at_tag = "relay-20260918111328/" in url
            rel = url.split("/relay/", 1)[-1]
            self.tried.append((host, rel, "tag" if at_tag else "main"))
            if rel == "manifest.json":
                return manifest_ref if not at_tag else None
            return self.doors.get(host, {}).get(("tag" if at_tag else "main", rel))
    manifest_ref = json.dumps({"version": 20260918111328, "ref": "relay-20260918111328",
                               "files": {"a.py": sha}}).encode("utf-8")
    root = workdir({"a.py": old}, code_version=20260821110000)
    net = use(RefNet({h: {("main", "a.py"): b"stale copy\n", ("tag", "a.py"): body}
                      for h in (FASTLY, CDN, GCORE, RAW)}))
    check("更新了 a.py", su.check(root, BASE), ["a.py"])
    check("落盘的是标签下的内容", (root / "a.py").read_bytes(), body)
    check("文件只在标签下取过", [t for t in net.tried if t[1] == "a.py"], [(FASTLY, "a.py", "tag")])
    check("清单只在分支上取", {t[2] for t in net.tried if t[1] == "manifest.json"}, {"main"})

    print("\n[内容和清单对不上：一个字节都不许落盘，而且必须留下失败的原因]")
    root = workdir({"a.py": old}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000, {"a.py": sha}), "a.py": old}
             for h in (FASTLY, CDN, GCORE, RAW)}))     # 四扇门发的都是旧副本
    check("不更新", su.check(root, BASE), [])
    check("文件原封不动", (root / "a.py").read_bytes(), old)
    check("版本号不许提前记（记了下次开机就不再重试）",
          StateStore(root / "state").get("versions", "code"), "20260821110000")
    f = su.take_failure(root)
    check("失败被记下来了，不是静默的", bool(f), True)
    check("说清了是哪个文件", f and f["files"], ["a.py"])

    print("\n[两个文件只取到一个：两个都不许写——半个更新比不更新更危险]")
    b_body = b"print('b new')\n"
    root = workdir({"a.py": old, "b.py": old}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000,
                                           {"a.py": sha, "b.py": su._sha1(b_body)}),
                 "a.py": body}                      # b.py 哪扇门都没有
             for h in (FASTLY, CDN, GCORE, RAW)}))
    check("整轮放弃", su.check(root, BASE), [])
    check("取到的那个也不许落盘", (root / "a.py").read_bytes(), old)
    check("另一个当然也没动", (root / "b.py").read_bytes(), old)
    check("失败报告列出了这一轮本来要改的两个文件",
          sorted((su.take_failure(root) or {}).get("files") or []), ["a.py", "b.py"])

    print("\n[本机已经是新的：什么都不做，也不许把旧的失败报告留在那里吓人]")
    root = workdir({"a.py": body}, code_version=20260821110000)
    su._record_failure(root, "上一轮没成", 1, 2, ["a.py"])
    use(Net({h: {"manifest.json": manifest(20260908090000, {"a.py": sha})}
             for h in (FASTLY, CDN, GCORE, RAW)}))
    check("没有文件要改", su.check(root, BASE), [])
    check("旧的失败报告清掉了", su.take_failure(root), None)
    check("版本号照样记（本机确实就是这一版）",
          StateStore(root / "state").get("versions", "code"), "20260908090000")


    # --------------------------------------------------------------- 清单里的路径

    print("\n[清单是从网上取的：越界路径必须在结构上不可能，而不是靠信任]")
    root = tmpdir()
    for bad in ("../evil.py", "a/../../evil.py", "/etc/passwd", "\\windows\\system32\\x"):
        check(f"拦下 {bad}", su._safe_target(root, bad), None)
    check("正常路径落在 root 里面",
          su._safe_target(root, "ark_relay/core/engine.py"),
          (root / "ark_relay" / "core" / "engine.py").resolve())

    print("\n[越界路径走完整一轮：root 外面不许多出任何东西]")
    root = workdir({"a.py": old}, code_version=20260821110000)
    outside = root.parent / "evil.py"
    use(Net({h: {"manifest.json": manifest(20260908090000,
                                           {"../evil.py": sha, "a.py": sha}),
                 "a.py": body, "../evil.py": body}
             for h in (FASTLY, CDN, GCORE, RAW)}))
    check("正常那个还是更新了", su.check(root, BASE), ["a.py"])
    check("root 外面什么都没写出来", outside.exists(), False)

    print("\n[清单里的新源码文件跟着一轮一起创建：2026-09-15 起，模块拆分不再卡住整个更新]")
    root = workdir({"a.py": body}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000,
                                           {"a.py": sha, "brand_new.py": sha, "pkg/deep.py": sha}),
                 "brand_new.py": body, "pkg/deep.py": body} for h in (FASTLY, CDN, GCORE, RAW)}))
    check("新文件算进这一轮", su.check(root, BASE), ["brand_new.py", "pkg/deep.py"])
    check("新文件造出来了，内容对哈希", (root / "brand_new.py").read_bytes(), body)
    check("新目录也建了", (root / "pkg" / "deep.py").read_bytes(), body)

    print("\n[不是源码的新文件还是不许造：门只开给 .py/.md/.txt/.json]")
    root = workdir({"a.py": old}, code_version=20260821110000)
    use(Net({h: {"manifest.json": manifest(20260908090000,
                                           {"a.py": sha, "tool.exe": sha}),
                 "a.py": body, "tool.exe": body} for h in (FASTLY, CDN, GCORE, RAW)}))
    check("整轮放弃", su.check(root, BASE), [])
    check("a.py 也没动", (root / "a.py").read_bytes(), old)
    check("没有造出 exe", (root / "tool.exe").exists(), False)

    print("\n[_wanted_files：这一轮打算改哪些——失败报告要靠它说人话]")
    root = workdir({"same.py": body, "diff.py": old})
    check("哈希一样的不算",
          su._wanted_files(root, {"same.py": sha}), [])
    check("哈希不一样的才算",
          su._wanted_files(root, {"diff.py": sha, "same.py": sha}), ["diff.py"])
    check("本机没有的源码文件算（这一轮会创建它）",
          su._wanted_files(root, {"nope.py": sha}), ["nope.py"])
    check("本机没有的非源码文件不算（它不会被创建）",
          su._wanted_files(root, {"nope.exe": sha}), [])

    import ark_relay.features.selfupdate as SU

    _root = tmpdir()
    (_root / "state").mkdir()          # 失败记录写在 state/ 下，机器上一直有这个目录
    (_root / "old.py").write_bytes(b"x = 1\n")
    _files = {"old.py": SU._sha1(b"x = 2\n"), "a_tool.exe": SU._sha1(b"y = 1\n")}   # sorts before old.py: refused before any download
    _got = SU._stage_files(_root, "https://example.invalid/", _files, None, 7, 6, ["old.py"])
    check("有非源码新文件时整轮放弃", _got, None)
    check("一个字节都没落盘", (_root / "old.py").read_bytes(), b"x = 1\n")
    check("那个文件也没被创建", (_root / "a_tool.exe").exists(), False)
    _fail = (SU.take_failure(_root) or {}).get("reason", "")
    check("留了话说清要人工部署", "部署脚本" in _fail, True)
    check("话里点名了是哪个文件", "a_tool.exe" in _fail, True)


def _part_selfupdate_exit():
    """A self-update restart must stop the old process before the boot stages run."""
    import ast
    import types

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                 "win32com", "win32com.client"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages
    from ark_relay.features import preupdate
    from ark_relay.features import selfupdate


    class _Log:
        def info(self, *a, **k): pass
        def exception(self, *a, **k): pass
        warning = info


    def test_selfupdate_returns_true():
        print("自更新拉到新代码：返回 True，让 service.py 立刻退出")
        real_check, real_popen = selfupdate.check, boot_stages.subprocess.Popen
        spawned = []
        selfupdate.check = lambda here: ["ark_relay/features/report.py"]
        boot_stages.subprocess.Popen = lambda *a, **k: spawned.append(a)
        for flag in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):   # Windows-only
            if not hasattr(boot_stages.subprocess, flag):
                setattr(boot_stages.subprocess, flag, 0)
        try:
            check("有更新时返回", boot_stages._stage_selfupdate(_Log()), True)
            check("起了重启器", len(spawned), 1)
            selfupdate.check = lambda here: []
            check("没更新时返回", boot_stages._stage_selfupdate(_Log()), False)
        finally:
            selfupdate.check, boot_stages.subprocess.Popen = real_check, real_popen


    def test_no_bare_return_in_bool_functions():
        print("声明返回 bool 的函数里没有裸 return（None 会被当成 False）")
        bad = []
        for p in sorted(RELAY.rglob("*.py")):
            if "tests" in p.parts:
                continue
            for f in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if (isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and isinstance(f.returns, ast.Name) and f.returns.id == "bool"):
                    bad += [f"{p.relative_to(RELAY)}:{n.lineno} {f.name}"
                            for n in ast.walk(f)
                            if isinstance(n, ast.Return) and n.value is None]
        check("裸 return", bad, [])


    def test_preupdate_skipped_while_stopping():
        print("服务正在停止：不做预更新，不起任何程序")
        asked = []
        real = boot_stages._stop_requested, preupdate.wanted_today
        boot_stages._stop_requested = lambda: True
        preupdate.wanted_today = lambda *a, **k: asked.append(1) or False
        try:
            boot_stages._stage_preupdate(types.SimpleNamespace(automas_dir=None), None, _Log())
            check("停止时连「今天要不要做」都不问", asked, [])
        finally:
            boot_stages._stop_requested, preupdate.wanted_today = real


    def test_preupdate_automas_without_okww():
        print("清单-1108 A-07：今天只剩 MAA / MaaEnd 的队列：AUTO-MAS 的更新照查，OK-WW 不动")
        ran = []
        names = ("_stop_requested", "await_backend", "_once_more", "_preupdate_okww")
        real = [getattr(boot_stages, n) for n in names] + [preupdate.wanted_today, preupdate.should_run, preupdate.mark_run]
        boot_stages._stop_requested = lambda: False
        boot_stages.await_backend = lambda log, why, cfg: (True, 0)
        boot_stages._once_more = lambda cfg, log, what, budget, problems, fn: ran.append(what) or None
        boot_stages._preupdate_okww = lambda *a: ran.append("OK-WW")
        preupdate.wanted_today = lambda d, now=None, kind="OK-WW": kind == "MAA"
        preupdate.should_run = lambda *a: True
        preupdate.mark_run = lambda *a, **k: ran.append("marked")
        try:
            boot_stages._stage_preupdate(types.SimpleNamespace(automas_dir=None, state_dir=None), None, _Log())
            check("AUTO-MAS 查了、OK-WW 没动、今天记为做过", ran, ["AUTO-MAS", "marked"])
        finally:
            for n, v in zip(names, real[:len(names)], strict=True):
                setattr(boot_stages, n, v)
            preupdate.wanted_today, preupdate.should_run, preupdate.mark_run = real[len(names):]


    if __name__ == "__main__":
        test_selfupdate_returns_true()
        test_no_bare_return_in_bool_functions()
        test_preupdate_skipped_while_stopping()
        test_preupdate_automas_without_okww()
        print("all checks passed" if not fails else f"FAILED: {fails}")
        raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_desktop_focus, _part_desktop_kill, _part_desktop_no_window, _part_desktop_screenshot, _part_desktop_workfiles, _part_spawn_direct, _part_display_wake, _part_selfupdate_atomic_sha256, _part_selfupdate_cos, _part_selfupdate_doors, _part_selfupdate_exit]))
