"""Game-client update: a state that was not recognised / not read is never counted as done.

The 2026-10-05 audit (BOARD/补丁审查-1005.md, 「MAA / 启动器 / 更新」) found these
places where the update flow took an unknown state for a known one:

* desktop: no window to focus still came back ok=true with whatever was in front;
* launchers: the first read only knew "ready" and "update button", so a download that
  had resumed by itself was killed (Endfield kill Games.exe, WuWa close());
* WuWa: find("更新") also hits a 「版本更新公告」 news headline;
* click_text / click return values were dropped;
* tasklist failing counted as "the game is alive";
* ak_prewarm tapped the bottom of the screen blind every 20 s for 15 minutes;
* boot_check: a version reply without a number logged 「已是 ?，无需更新」;
* spmed_fix_present None (shape not known) switched the task back on;
* download: a restart after the server ignored Range could never match its size.

Each case has its counter-example: the case that must still go through.
"""
import io
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import desktop
from ark_relay import gameupdate as gu
from ark_relay import gameupdate_games as gug
from ark_relay import efstatus
from ark_relay.desktop import Desktop, Line, Screen
import ark_relay.preupdate_okww as pok

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class FakeDesk:
    """Plays screens back in order (the last one repeats); records clicks.
    A screen given as None is an unreadable one (window not found)."""
    def __init__(self, screens, fail=()):
        self.screens = list(screens); self.clicks = []; self.reads = 0; self.fail = set(fail)

    def read(self, focus=None, settle_ms=0):
        self.reads += 1
        texts = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        if texts is None:
            return Screen([], Path("x.png"), ok=False, error=f"ERR focus: 没有 {focus} 的窗口")
        return Screen([Line(t, 100, 100 + 30 * i, 80, 20) for i, t in enumerate(texts)], Path("x.png"))

    def click_text(self, text, focus=None):
        self.clicks.append(text); return text not in self.fail

    def click(self, x, y, focus=None):
        self.clicks.append((x, y)); return (x, y) not in self.fail


kills = []
gug._spawn = lambda exe, cwd=None: True
gug.kill = lambda *names: kills.append(names)
closes = []
pok._okww_close = lambda **k: closes.append(1) or []
nosleep = lambda s: None  # noqa: E731
EF, LA = Path("Endfield.exe"), Path("Launcher.exe")

# ───────────────────────── desktop ─────────────────────────
print("[desktop：要找的窗口不在 = 读屏失败，不读前台随便哪个窗口]")
check("agent 找不到窗口就 throw（ok 留 false，后面的截图/点击都不做）",
      'if ($null -eq $p) { throw "focus: 没有 $f 的窗口" }' in desktop.AGENT_PS, True)
check("…不再只记一行日志就接着读屏", '[void]$log.Add("focus: 没有 $f 的窗口")' in desktop.AGENT_PS, False)


def fake_spawn(result):
    def spawn(exe, cwd, args):
        Path(args[-1]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return True
    return spawn


ST = tmpdir()
nowin = {"ok": False, "log": ["ERR focus: 没有 Games 的窗口"],
         "ocr": [{"text": "前台别的程序的字", "x": 1, "y": 1, "w": 1, "h": 1}]}
scr = Desktop(ST, spawn=fake_spawn(nowin), timeout=5).read(focus="Games")
check("找不到窗口 → scr.ok False", scr.ok, False)
check("…error 说清是哪个窗口", "没有 Games 的窗口" in scr.error, True)
check("…读不到的屏上什么都没有（不拿前台的字当启动器的）", (scr.lines, scr.has("前台别的程序的字")), ([], False))
check("…click_text 也算没点上", Desktop(ST, spawn=fake_spawn(nowin), timeout=5).click_text("更新游戏", focus="Games"), False)
good = {"ok": True, "log": ["focus: Games 「鹰角启动器」"], "ocr": [{"text": "开始游戏", "x": 10, "y": 10, "w": 40, "h": 20}]}
scr = Desktop(ST, spawn=fake_spawn(good), timeout=5).read(focus="Games")
check("反例：找到窗口 → ok True、读到按钮", (scr.ok, scr.has("开始游戏")), (True, True))
check("反例：老写法 Screen(lines) 默认 ok", Screen([Line("x", 0, 0, 1, 1)]).ok, True)

print("[Screen.find whole=True：按钮要整行是那个词，新闻标题里的「更新」不算]")
news = Screen([Line("版本更新公告", 0, 0, 10, 10), Line("活动", 0, 20, 10, 10)])
check("子串匹配会命中新闻标题（审查说的风险）", news.find("更新") is not None, True)
check("整行匹配不命中新闻标题", news.find("更新", whole=True), None)
check("整行匹配：「立即更新公告」不是「立即更新」", Screen([Line("立即更新公告", 0, 0, 1, 1)]).find("立即更新", whole=True), None)
check("反例：按钮那一行就是「更新」→ 命中", Screen([Line("更 新", 0, 0, 1, 1)]).find("更新", whole=True) is not None, True)
check("反例：四字按钮错一个字仍命中（OCR 认错一个字）",
      Screen([Line("立即更斩", 0, 0, 1, 1)]).find("立即更新", whole=True) is not None, True)

# ───────────────────────── Endfield launcher ─────────────────────────
print("[终末地启动器：第一眼就在下载 → 不点不关，等它下完]")
kills.clear(); probs = []
d = FakeDesk([["正在下载 37%"], ["安装中"], ["开始游戏"], ["点击任意位置继续"]])
out = gu.update_endfield(d, EF, LA, poll_s=0, problems=probs, sleep=nosleep)
check("等下完后照常更新完", out, "终末地 客户端已通过启动器更新")
check("没点「更新游戏」，只点了装完的「开始游戏」", d.clicks, ["开始游戏"])
check("Games.exe 只在最后关，下载中没被杀", kills, [("Endfield.exe",), ("Endfield.exe", "Games.exe")])
check("没有问题", probs, [])
kills.clear(); probs = []
d = FakeDesk([["安装中"], ["开始游戏"], ["点击任意位置继续"]])
gu.update_endfield(d, EF, LA, poll_s=0, problems=probs, sleep=nosleep)
check("第一眼「安装中」同样等", (d.clicks, probs), (["开始游戏"], []))

print("[终末地启动器：画面不认识 / 窗口没读到 → 报原因，不杀启动器]")
kills.clear(); probs = []
out = gu.update_endfield(FakeDesk([["已暂停", "继续"]]), EF, LA, problems=probs, sleep=nosleep)
check("不认识 → 空", out, "")
check("…问题里说不认识、带读到的字", len(probs) == 1 and "画面不认识，没点也没关" in probs[0] and "已暂停" in probs[0], True)
check("…没杀 Games.exe", kills, [("Endfield.exe",)])
kills.clear(); probs = []
d = FakeDesk([None])
out = gu.update_endfield(d, EF, LA, problems=probs, sleep=nosleep)
check("窗口没读到 → 空、报原因、不杀、不点",
      (out, len(probs) == 1 and "启动器窗口没读到" in probs[0] and "没有 Games 的窗口" in probs[0], kills, d.clicks),
      ("", True, [("Endfield.exe",)], []))
kills.clear(); probs = []
gu.update_endfield(FakeDesk([["开始游戏"]]), EF, LA, problems=probs, sleep=nosleep)
check("反例：已是「开始游戏」→ 照旧关启动器、无问题", (kills, probs), ([("Endfield.exe",), ("Games.exe",)], []))

print("[终末地：点击没点上 = 失败]")
kills.clear(); probs = []
d = FakeDesk([["开始游戏"]]); d.fail = {"开始游戏"}
d.screens = [["更新游戏"], ["开始游戏"]]
out = gu.update_endfield(d, EF, LA, poll_s=0, problems=probs, sleep=nosleep)
check("装完点「开始游戏」没点上 → 报问题、不去等标题画面",
      (len(probs) == 1 and "没点上" in probs[0], d.reads), (True, 2))
check("…更新本身报出来", out, "终末地 客户端已通过启动器更新")
probs = []
d = FakeDesk([["更新游戏"], ["开始游戏"], ["资源初始化更新完成，请重启游戏", "确认"]], fail={"确认"})
gu.update_endfield(d, EF, LA, poll_s=0, problems=probs, sleep=nosleep)
check("「确认」没点上 → 报问题、不重启", any("「确认」没点上" in p for p in probs), True)

# ───────────────────────── WuWa launcher ─────────────────────────
print("[鸣潮启动器：第一眼就在下载 / 解压 → 不点不关，等它好]")
closes.clear(); probs = []
d = FakeDesk([["下载中 12.3MB/s"], ["解压中"], ["进入游戏"], ["点击连接"]])
out = gu.update_wuwa(d, Path("launcher.exe"), poll_s=0, problems=probs, sleep=nosleep)
check("等到「进入游戏」后照常更新完", out.startswith("鸣潮 客户端已通过启动器更新"), True)
check("没点更新按钮，只点了「进入游戏」", d.clicks, ["进入游戏"])
check("只在最后关一次，下载中没关", closes, [1])
check("没有问题", probs, [])
closes.clear(); probs = []
d = FakeDesk([["解压中"], ["开始游戏"], ["点击连接"]])
gu.update_wuwa(d, Path("launcher.exe"), poll_s=0, problems=probs, sleep=nosleep)
check("第一眼「解压中」同样等", (d.clicks, closes, probs), (["开始游戏"], [1], []))

print("[鸣潮启动器：新闻标题里的「更新」不点；不认识 / 读不到 → 报原因、不关]")
closes.clear(); probs = []
d = FakeDesk([["版本更新公告", "活动"]])
out = gu.update_wuwa(d, Path("launcher.exe"), problems=probs, sleep=nosleep)
check("新闻标题 → 没点", d.clicks, [])
check("…报不认识、没关", (out, len(probs) == 1 and "画面不认识，没点也没关" in probs[0], closes), ("", True, []))
closes.clear(); probs = []
d = FakeDesk([None])
out = gu.update_wuwa(d, Path("launcher.exe"), problems=probs, sleep=nosleep)
check("窗口没读到 → 报原因、不关、不点",
      (out, len(probs) == 1 and "启动器窗口没读到" in probs[0], closes, d.clicks), ("", True, [], []))
closes.clear(); probs = []
d = FakeDesk([["版本更新公告", "更新"], ["下载中"], ["进入游戏"], ["点击连接"]])
gu.update_wuwa(d, Path("launcher.exe"), poll_s=0, problems=probs, sleep=nosleep)
check("反例：按钮那一行就是「更新」→ 点的是按钮（第二行中心），不是标题", d.clicks[0], (140, 140))
check("反例：已是「进入游戏」→ 照旧关", (lambda c: (gu.update_wuwa(FakeDesk([["进入游戏"]]), Path("launcher.exe"), problems=[], sleep=nosleep), len(closes) - c))(len(closes)), ("", 1))

print("[鸣潮：点击没点上 = 失败]")
closes.clear(); probs = []
d = FakeDesk([["立即更新"]], fail={(140, 110)})
out = gu.update_wuwa(d, Path("launcher.exe"), problems=probs, sleep=nosleep)
check("点更新没点上 → 报问题、关掉（状态已知：没在下载）", (out, len(probs) == 1 and "没点上" in probs[0], closes), ("", True, [1]))
closes.clear(); probs = []
d = FakeDesk([["立即更新"], ["进入游戏"]], fail={"进入游戏"})
out = gu.update_wuwa(d, Path("launcher.exe"), poll_s=0, problems=probs, sleep=nosleep)
check("装完点「进入游戏」没点上 → 报问题、不去等登录界面",
      (out, len(probs) == 1 and "装完点「进入游戏」没点上" in probs[0], d.reads), ("鸣潮 客户端已通过启动器更新", True, 2))

# ───────────────────────── tasklist / wait_ready ─────────────────────────
print("[tasklist 出错 = 不知道，不是活着也不是没了]")
_real_run = subprocess.run


class _R:
    def __init__(self, rc, out):
        self.returncode, self.stdout = rc, out


def _with_run(fake, fn):
    subprocess.run = fake
    try:
        return fn()
    finally:
        subprocess.run = _real_run


def _raise(*a, **k):
    raise OSError("tasklist 起不来")


check("tasklist 抛异常 → None", _with_run(_raise, gug._alive("Game.exe")), None)
check("tasklist 返回码非 0 → None", _with_run(lambda *a, **k: _R(1, b""), gug._alive("Game.exe")), None)
check("tasklist 给回的东西不像结果 → None（不炸）", _with_run(lambda *a, **k: None, gug._alive("Game.exe")), None)
check("反例：列表里有 → True", _with_run(lambda *a, **k: _R(0, b"Game.exe  123"), gug._alive("Game.exe")), True)
check("反例：列表里没有 → False", _with_run(lambda *a, **k: _R(0, b"explorer.exe  1"), gug._alive("Game.exe")), False)


class _Warn(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING); self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


w = _Warn(); gug.log.addHandler(w)
tick = lambda s: time.sleep(0.002)  # noqa: E731
check("不知道 + 画面到了 → 照样认登录界面",
      gug.wait_ready(FakeDesk([["点击连接"]]), "鸣潮", focus="x", alive=lambda: None, sleep=tick), "读到「点击连接」")
check("…并写了查不到的 warning", any("进程状态查不到" in m for m in w.msgs), True)
w.msgs.clear()
check("不知道 + 画面一直没到 → 空，最后一行说有几次查不到",
      (gug.wait_ready(FakeDesk([["加载中"]]), "鸣潮", focus="x", alive=lambda: None, budget_s=0.03, sleep=tick),
       any("次进程状态查不到" in m for m in w.msgs)), ("", True))
w.msgs.clear()
check("反例：进程确实没了 → 立刻空", gug.wait_ready(FakeDesk([["点击连接"]]), "鸣潮", focus="x", alive=lambda: False, sleep=tick), "")
check("…写的是进程没了", any("进程没了" in m for m in w.msgs), True)

# ───────────────────────── ak_prewarm ─────────────────────────
print("[方舟预热：读到「START」才点，读不到不盲点]")
taps = []


def adb(args):
    s = " ".join(map(str, args))
    if "input tap" in s:
        taps.append(s)
    if s.endswith("wm size"):
        return "Physical size: 1600x900\n"
    return ""


out = gug.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", FakeDesk([["加载中"], ["START"], ["开始唤醒"]]), run=adb, sleep=nosleep)
check("加载页 → 读到 START 点一下 → 登录界面", (out, len(taps)), ("读到「开始唤醒」", 1))
check("…点的是底部中央", taps[0].endswith("input tap 800 855"), True)
taps.clear(); why = []
out = gug.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", FakeDesk([["加载中", "Ver 2.7.61"]]), run=adb, sleep=tick,
                     budget_s=0.03, why=why)
check("一直没读到 START → 一次都不点", (out, taps), ("", []))
check("…原因写明没有盲点、带最后一屏", len(why) == 1 and "没有盲点" in why[0] and "Ver 2.7.61" in why[0], True)
taps.clear(); why = []
out = gug.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", FakeDesk([None]), run=adb, sleep=tick, budget_s=0.03, why=why)
check("窗口读不到 → 不点、原因写读不到", (out, taps, len(why) == 1 and "读不到" in why[0]), ("", [], True))
taps.clear()
check("反例：一上来就是登录界面 → 不点", (gug.ak_prewarm(Path("ldconsole.exe"), "e", FakeDesk([["开始唤醒"]]), run=adb, sleep=nosleep), taps),
      ("读到「开始唤醒」", []))

# ───────────────────────── download ─────────────────────────
print("[下载 APK：断点续传、服务器不认 Range 时重下、大小核不上不算完]")


class _Resp(io.BytesIO):
    def __init__(self, body, status, headers):
        super().__init__(body); self.status = status; self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(body, status, headers):
    seen = []

    def urlopen(req, timeout=0):
        seen.append(req.get_header("Range"))
        return _Resp(body, status, headers)
    return urlopen, seen


_real_urlopen = gug.urllib.request.urlopen
D = tmpdir()
try:
    gug.urllib.request.urlopen, seen = _serve(b"A" * 10, 200, {"Content-Length": "10"})
    check("全新下载 → 成功", gug.download("http://x/a", D / "a.apk"), True)
    check("…文件到位、.part 没了", ((D / "a.apk").read_bytes(), (D / "a.apk.part").exists()), (b"A" * 10, False))
    (D / "b.apk.part").write_bytes(b"B" * 4)
    gug.urllib.request.urlopen, seen = _serve(b"B" * 6, 206, {"Content-Range": "bytes 4-9/10", "Content-Length": "6"})
    check("续传 206 → 接着写、成功", (gug.download("http://x/b", D / "b.apk"), seen), (True, ["bytes=4-"]))
    check("…拼起来的大小对", len((D / "b.apk").read_bytes()), 10)
    (D / "c.apk.part").write_bytes(b"old!")
    gug.urllib.request.urlopen, seen = _serve(b"C" * 10, 200, {"Content-Length": "10"})
    check("服务器不认 Range（200）→ 从头重下并成功（以前大小对不上，每次都失败）", gug.download("http://x/c", D / "c.apk"), True)
    check("…文件就是新下的全文", (D / "c.apk").read_bytes(), b"C" * 10)
    gug.urllib.request.urlopen, seen = _serve(b"D" * 5, 200, {"Content-Length": "10"})
    check("下到的比说的少 → 不算完", (gug.download("http://x/d", D / "d.apk"), (D / "d.apk").exists()), (False, False))
    gug.urllib.request.urlopen, seen = _serve(b"E" * 5, 200, {})
    check("服务器没给大小 → 核不了，不算完", (gug.download("http://x/e", D / "e.apk"), (D / "e.apk").exists()), (False, False))
finally:
    gug.urllib.request.urlopen = _real_urlopen

# ───────────────────────── boot_check: reply without a version ─────────────────────────
print("[开机检查：官方回包没有版本号 → 进问题清单，不写「已是 ?，无需更新」]")
S2 = tmpdir()
maa = S2 / "maa"; (maa / "config").mkdir(parents=True)
ld = S2 / "ld"; ld.mkdir(); (ld / "ldconsole.exe").write_bytes(b""); (ld / "adb.exe").write_bytes(b"")
(maa / "config" / "gui.new.json").write_text(json.dumps({"AdbPath": str(ld / "adb.exe")}), encoding="utf-8")


class Cfg:
    pass


cfg = Cfg(); cfg.state_dir = S2; cfg.maa_dir = maa; cfg.maaend_dir = None; cfg.okww_dir = None; cfg.automas_dir = None
gu.record_ak_version(S2, "2.7.61")
NO_WW = lambda: {"game": []}  # noqa: E731
_n, p = gu.boot_check(cfg, budget_s=600, maint_sources={}, hint=lambda n: "", wuwa_fetch=NO_WW,
                      fetch=lambda: {"resVersion": "x"})
check("回包没 clientVersion → 问题清单里有", p, ["明日方舟：官方的版本信息里没有客户端版本号"])
_n, p = gu.boot_check(cfg, budget_s=600, maint_sources={}, hint=lambda n: "", wuwa_fetch=NO_WW,
                      fetch=lambda: {"clientVersion": "2.7.61"})
check("反例：版本号相同 → 无问题", p, [])

print("[终末地公告严格模式：读不到会抛出来，默认仍返回空]")


def _boom():
    raise OSError("连不上")


try:
    efstatus.update_hint(fetch=_boom, strict=True)
    check("strict 读挂 → 抛", "没抛", "抛了")
except OSError:
    check("strict 读挂 → 抛", "抛了", "抛了")
check("反例：默认（handle.py 用的）读挂 → 空", efstatus.update_hint(fetch=_boom), "")

# ───────────────────────── spmed None ─────────────────────────
print("[加强剂那一步写法不认识（None）→ 不开回、不删备忘，说要人看]")


def spmed_cfg(node):
    root = tmpdir()
    me = root / "maaend"; (me / "resource" / "pipeline").mkdir(parents=True)
    (me / "resource" / "pipeline" / "nodes.json").write_text(
        json.dumps({"AutoUseSpMedicationQuickUse": node}), encoding="utf-8")
    (me / "interface.json").write_text(json.dumps({"version": "v2.28.0-beta.4"}), encoding="utf-8")
    master = root / "automas" / "data" / "S1" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
    master.parent.mkdir(parents=True)
    master.write_text(json.dumps({"instances": [{"tasks": [{"taskName": "AutoUseSpMedication", "enabled": False}]}]}),
                      encoding="utf-8")
    c = Cfg(); c.state_dir = root / "state"; c.maaend_dir = me; c.automas_dir = root / "automas"
    c.state_dir.mkdir()
    gu._store(c.state_dir).set("updates", "maaend_disabled_spmed",
                               {"since": "v2.27.0-beta.5", "tasks": ["AutoUseSpMedication"]})
    return c, master


def enabled(master):
    return json.loads(master.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["enabled"]


c, m = spmed_cfg({"next": ["x"]})            # v2.28.0-beta.4 shape: no recognition block
check("前提：这个形状判为 None", gu.spmed_fix_present(c.maaend_dir), None)
msg = gu.maaend_reenable_spmed_if_updated(c)
check("None → 说看不出、继续关着", "看不出修没修" in msg and "继续关着" in msg, True)
check("…任务没开回", enabled(m), False)
check("…备忘还在（下次还能接着判）", bool(gu._store(c.state_dir).get("updates", "maaend_disabled_spmed")), True)
c, m = spmed_cfg({"recognition": {"param": {"all_of": [{"recognition": "OCR", "expected": "确认"}]}}})
msg = gu.maaend_reenable_spmed_if_updated(c)
check("反例：修好的形状 → 开回、删备忘", (enabled(m), gu._store(c.state_dir).get("updates", "maaend_disabled_spmed"),
                                 "已经修好" in msg), (True, None, True))
c, m = spmed_cfg({"recognition": {"param": {"all_of": [{"expected": "确认"}]}}})
check("反例：坏的形状 → 不开回、不出声", (gu.maaend_reenable_spmed_if_updated(c), enabled(m)), ("", False))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
