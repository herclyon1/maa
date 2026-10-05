"""Desktop focus and short-word matching. No Windows here: the spawn is faked to
write the result JSON the way agent.ps1 does.

1. When the window asked for (focus=) is not found, the agent still screenshots
   and OCRs whatever is in front. That text must not come back as the launcher's
   screen, and nothing may be clicked: read() gives an empty Screen with
   focus_missing=True, click()/click_text() give False.
2. Words of two characters or fewer must be the whole OCR line: 「更新」 must not
   hit a news headline 「版本更新公告」.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import desktop as dk
from ark_relay.desktop import Desktop, Line, Screen
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


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

print("\n[窗口没找到时点击一律不算：click_text / click 返回 False，即使结果里有 clicked]")
missing = {"ok": True, "focus_missing": True, "clicked": [[60, 80]], "ocr": OTHER_WINDOW,
           "log": ["focus: 没有 Endfield 的窗口", "click 60,80"]}
d = Desktop(tmpdir() / "state", spawn=agent(missing), timeout=5)
check("click_text 返回 False", d.click_text("确认", focus="Endfield"), False)
check("click 返回 False", d.click(60, 80, focus="Endfield"), False)
log_only = dict(missing)
del log_only["focus_missing"]
d = Desktop(tmpdir() / "state", spawn=agent(log_only), timeout=5)
check("只有日志行：click_text 返回 False", d.click_text("确认", focus="Endfield"), False)
check("只有日志行：click 返回 False", d.click(60, 80, focus="Endfield"), False)
found = {"ok": True, "clicked": [[60, 80]], "ocr": [], "log": ["focus: Endfield 「Endfield」", "click 60,80"]}
d = Desktop(tmpdir() / "state", spawn=agent(found), timeout=5)
check("找到窗口：click_text 照常 True", d.click_text("确认", focus="Endfield"), True)
check("找到窗口：click 照常 True", d.click(60, 80, focus="Endfield"), True)

print("\n[Screen 构造：focus_missing 关键字；旧的 (lines, shot) 位置参数照常]")
try:
    s = Screen([], Path("x.png"), focus_missing=True)
    check("关键字构造", s.focus_missing, True)
except TypeError as e:
    check("关键字构造", repr(e), "no TypeError")
s = Screen([Line("开始游戏", 0, 0, 10, 10)], Path("x.png"))
check("位置参数构造默认 False", getattr(s, "focus_missing", None), False)

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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
