"""The desktop agent: focus, killing, no window, screenshots and its work files; and the installed relay's direct starts.

One part per former file, each run on its own (tests/_parts.py): test_desktop.py, test_spawn_direct.py, test_display_wake.py.
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


def _part_desktop_focus():
    """Desktop focus and short-word matching. No Windows here: the spawn is faked to
write the result JSON the way agent.ps1 does.

1. When the window asked for (focus=) is not found, the agent still screenshots
   and OCRs whatever is in front. That text must not come back as the launcher's
   screen, and nothing may be clicked: read() gives an empty Screen with
   focus_missing=True, click()/click_text() give False.
2. Words of two characters or fewer must be the whole OCR line: 「更新」 must not
   hit a news headline 「版本更新公告」.

    Formerly test_desktop_focus.py.
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
    # relay.log 5356-5397 (09-02): 「桌面助手 … 超时没有结果」. A throw part-way (the
    # catch in AGENT_PS) can leave OCR lines in the result with ok false.
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


def _part_desktop_kill():
    """desktop.kill says when taskkill did not end a program (review 2026-10-13, s5 #8).

kill() dropped every taskkill result, so 「access denied」 (exit code 1) looked to
its callers (the game-update flows, the make-up) exactly like a kill that worked.
Now: exit 0 (ended) and 128 (no such program running) are fine; anything else, or
a taskkill that could not run, is a WARNING and kill() returns False.
No Windows here: subprocess.run is faked.

    Formerly test_desktop_kill.py.
    """
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
    finally:
        desktop.subprocess.run = real_run
        desktop.log.removeHandler(g)


def _part_desktop_no_window():
    """A desktop picture never puts a window on the screen.

2026-10-11 09:39 (evidence 2026-10-11_endfield_MaaEnd-05-30-34): the task-end
picture after 信用点购物 started PowerShell through the Interactive scheduled
task; its console window took the foreground from Endfield, which MaaEnd drives
with its foreground controller. The game stayed behind the taskbar for 25 s
(maafw.log: 159 x 「Failed to ensure foreground window before screencap」), the
taskbar covered the 「ENDFIELD」 mark MaaEnd's InMenuList check reads, and
转交委托 failed. Every picture or read that does not bring a window to the front
must go through the windowless route: pythonw.exe starting PowerShell with
CREATE_NO_WINDOW. No Windows here: spawns are faked.

    Formerly test_desktop_no_window.py.
    """
    import ast
    import json
    from pathlib import Path, PureWindowsPath

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.desktop import POWERSHELL, Desktop
    from ark_relay.features.preupdate import preupdate_common as C


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
        from ark_relay.features.alarm import handle
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

    Formerly test_desktop_screenshot.py.
    """
    import json
    import threading
    import time

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

Every read(), click_text() and screenshot() left req-<id>.json, res-<id>.json,
shot-<id>.png and shot-<id>-x2.png behind, and nothing removed them. Now the
request and result go as soon as the answer is read, and screenshots older than
Desktop.WORK_KEEP_SECONDS go at the next run (a fresh one is kept: its path is
quoted in problem notes and in the machine checks' trace). Files of other
features in the same folder are never touched. No Windows here: spawns are faked.

    Formerly test_desktop_workfiles.py.
    """
    import json
    import os
    import time

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

The relay now runs in the logged-on user's session (app_main.py, \\ArkRelay\\main, highest
privileges), yet every picture, click and launcher start still went through PowerShell
building a scheduled task and waiting 3 s, and that task was named after the program only,
so two launches of one program within those 3 s (two threads taking pictures) replaced or
unregistered each other's task. Pinned here, with Windows faked:

* elevated on the console session: Popen, no PowerShell; out of the relay task's job
  (CREATE_BREAKAWAY_FROM_JOB), the logged-on user's environment, a console window or
  CREATE_NO_WINDOW as asked, SW_SHOWMINNOACTIVE when minimized; the hidden route writes no
  pythonw launcher;
* breakaway refused (access denied): the task route, now and for every later start;
* another start failure, or not on the console / not elevated / no environment: the task
  route, as before;
* the task route: a new task name on every launch, under the program's stem.

    Formerly test_spawn_direct.py.
    """
    import subprocess
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.preupdate import preupdate_common as C


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
    """display_wake: the display is woken while AUTO-MAS starts Endfield through its launcher.

2026-10-16 13:21 (a hand-started make-up), attempt 1: the game PC's display had been
off (power plan, 300 s idle), the Hypergryph launcher kept its main window hidden
(games.log 13:21:31.615 bMainWndHide:true / 13:21:31.616 「display off」), AUTO-MAS
only wakes a running screensaver, and at 13:23:36 it gave up: 「游戏启动失败: 等待终末地
游戏窗口超时」. Nothing in the relay woke the display.

Fixture: the real app.log lines of that day (HTTP request lines left out):
09:33:54-09:34:05 (OK-WW finishing, then MaaEnd refused at its config check: no
launch), 13:21:13-13:26:14 (attempt 1 hand-off 13:21:28.423, timeout 13:23:36.444,
attempt 2 hand-off 13:23:36.799, game up 13:26:14.036) and 13:53:00-13:54:52 (attempt 3).

    Formerly test_display_wake.py.
    """
    import json
    import logging
    import threading
    import time
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import config, desktop, watch
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.run import display_wake as dw


    FIX = Path(__file__).resolve().parent / "fixtures" / "display-wake-2026-10-16" / "app.log"
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
    # beta.5 AutoProxy.py:496/503/521 log the mode alone, no 「，将由 MAS ...」 (the machine's app.log
    # 2026-10-17 11:31:03.832: 「启动方式为「MaaEnd 启动」」); efstart_setup sets 「MaaEnd 启动」 since
    # 10-17, whose pretask starts Launcher.exe and finds it by its window. Same logger and layout
    # as the 10-16 lines above; the times are this fixture's own.
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


if __name__ == "__main__":
    sys.exit(run_parts([_part_desktop_focus, _part_desktop_kill, _part_desktop_no_window, _part_desktop_screenshot, _part_desktop_workfiles, _part_spawn_direct, _part_display_wake]))
