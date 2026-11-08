"""Wuthering Waves: the bulletin, the middot, closing for an update.

One part per former file, each run on its own (tests/_parts.py): test_wuwa_bulletin.py, test_wuwa_middot.py, test_wuwa_update_close.py.
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


def _part_wuwa_bulletin():
    """Wuthering Waves banners: how the bulletin and the notices are read (2026-10-13 audit).

* Collaboration and memory banners say 「角色联动唤取」 / 「角色忆旅唤取」, not only
  「角色活动唤取」; the pool-name and notice-title patterns took only 活动.
* A bulletin that yields no debut (title or 「全新角色」 format changed) dropped every
  running pool without a log line; it now warns and reports them all.
* Once both halves are out, the 「下期」 line listed every wiki entry with the
  previewed badge, including a character whose own banner was running (锁暝,
  2026-10-22 audit run5.py); running and current-debut names are now left out.
  With no debut read (the fallback above), a name the bulletin quotes is left out
  too, and with no bulletin text the line is not said at all (review run6).

    Formerly test_wuwa_bulletin.py.
    """
    import logging
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ark_relay.features.banners.banners as _b
    from ark_relay.features.banners import wuwa as W


    print("[collaboration and memory banners: 联动 / 忆旅 as well as 活动]")
    for kind in ("活动", "联动", "忆旅"):
        body = f"<p>全新角色</p><p>5星共鸣者「某人」</p><p>※可通过[某池]角色{kind}唤取获得</p><p>全新武器</p>"
        check(f"bulletin pool name, 角色{kind}唤取", W.parse_wuwa_preview(body), [("某人", "某池")])
        nb = W.parse_wuwa_notice_banners({"recommend": [{
            "tabTitle": f"[某池]角色{kind}唤取",
            "content": "5星角色「某人」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}]})
        check(f"notice banner, 角色{kind}唤取", [(x.name, x.chars) for x in nb], [("某池", ("某人",))])
    check("a weapon banner is still not a character banner",
          W.parse_wuwa_notice_banners({"recommend": [{
              "tabTitle": "「碎骨」武器联动唤取",
              "content": "5星武器「某刀」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}]}), [])


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.recs = []

        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage()))


    def offline(url, *a, **k):
        raise OSError(f"offline: {url}")


    def home(*tabs):
        """A wiki homepage with one character tab per (banner, entry id, start, end)."""
        return {"code": 200, "data": {"contentJson": {"sideModules": [{
            "title": "角色活动唤取",
            "content": {"tabs": [{"name": n, "countDown": {"dateRange": [a, z]},
                                  "imgs": [{"linkConfig": {"entryId": e}}]} for n, e, a, z in tabs]}}]}}}


    def run_wuwa(now, page, notice, names, catalogue=None):
        """_wuwa against fakes; (banners, next, notes, WARNING messages)."""
        def fake(url, *a, **k):
            if url == W._WW_NOTICE:
                return notice
            if url.endswith("/wiki/core/homepage/getPage"):
                return page
            if url.endswith("/getEntryDetail"):
                eid = dict(x.split("=") for x in a[1].decode().split("&"))["id"]
                return {"code": 200, "data": {"name": names[eid]}}
            if url.endswith("/wiki/core/catalogue/item/getPage"):
                return {"code": 200, "data": {"results": {"records": catalogue or []}}}
            raise OSError(f"offline: {url}")
        g = Grab()
        _b.log.addHandler(g)
        real = _b._json, _b._text
        _b._json, _b._text = fake, offline
        notes: dict = {}
        try:
            got, nxt = _b._wuwa(now, notes=notes, trace=_b.Trace.new())
        finally:
            _b._json, _b._text = real
            _b.log.removeHandler(g)
        return got, nxt, notes, [m for lv, m in g.recs if lv == logging.WARNING]


    print("[no debut read from a fetched bulletin: warn, and report the running pools]")
    NOW = datetime(2026, 10, 13, 12, 0)
    page = home(("某某之池", "1", "2026-10-01 11:00", "2026-10-22 09:59"))
    renamed = {"game": [{"tabTitle": "3.7版本更新公告", "content": "<p>全新角色</p><p>5星共鸣者「某人」</p>"}]}
    got, _n, _notes, warns = run_wuwa(NOW, page, renamed, {"1": "某人"})
    check("bulletin title changed: the running pool is still reported", [b.name for b in got], ["某某之池"])
    check("…with a WARNING naming why", [m for m in warns if "读不出这一版的新角色" in m and "版本内容说明" in m] != [], True)
    reshaped = {"game": [{"tabTitle": "3.7版本内容说明", "content": "<p>全新角色</p><p>五星角色：某人</p><p>全新武器</p>"}]}
    got, _n, _notes, warns = run_wuwa(NOW, page, reshaped, {"1": "某人"})
    check("全新角色 format changed: the running pool is still reported", [b.name for b in got], ["某某之池"])
    check("…with a WARNING", [m for m in warns if "读不出这一版的新角色" in m and "写法变了" in m] != [], True)
    fine = {"game": [{"tabTitle": "3.7版本内容说明",
                      "content": "<p>全新角色</p><p>5星共鸣者「别人」</p><p>※可通过[别的池]角色活动唤取获得</p><p>全新武器</p>"}]}
    got, _n, _notes, warns = run_wuwa(NOW, page, fine, {"1": "某人"})
    check("a readable debut list still drops a rerun", [b.name for b in got], [])
    check("…without that WARNING", [m for m in warns if "读不出这一版的新角色" in m], [])

    print("[the next version's previewed characters leave out who is running now]")
    LATE = datetime(2026, 10, 22, 21, 30)
    both = {"game": [{"tabTitle": "3.7版本内容说明",
                      "content": "<p>全新角色</p><p>5星共鸣者「心」</p><p>※可通过[但愿长圆如此夜]角色活动唤取获得</p>"
                                 "<p>5星共鸣者「锁暝」</p><p>※可通过[余心所向九死未悔]角色活动唤取获得</p><p>全新武器</p>"}]}
    second = home(("余心所向九死未悔", "S", "2026-10-22 10:00", "2026-11-11 11:59"))


    def badge(name, a, z):
        return {"name": name, "content": {"showTeaserIcon": True, "showTeaserIconNum": 2,
                                          "teaserDateRange": [a, z]}}


    cat = [badge("锁暝", "2026-09-03 00:00:00", "2027-09-03 00:00:00"),
           badge("新来的", "2026-10-20 00:00:00", "2026-11-12 00:00:00")]
    got, _n, notes, _w = run_wuwa(LATE, second, both, {"S": "锁暝"}, cat)
    check("the running debut is reported", [b.name for b in got], ["余心所向九死未悔"])
    check("the 下期 note names only the one not out yet",
          notes.get("鸣潮", ""), "官方已预告下一版新角色：新来的")

    print("[no debut read (the fallback): this version's second half is not the next version's]")
    # 2026-10-13 review run6 (live data with the debut lines' star prefix rewritten):
    # first half running, the debut list unreadable, and this version's second-half
    # character was announced as the next version's.
    first = home(("但愿长圆如此夜", "X", "2026-10-01 11:00", "2026-10-22 09:59"))
    five = {"game": [{"tabTitle": "3.7版本内容说明",
                      "content": "<p>全新角色</p><p>五星共鸣者「心」</p><p>※可通过[但愿长圆如此夜]角色活动唤取获得</p>"
                                 "<p>五星共鸣者「锁暝」</p><p>※可通过[余心所向九死未悔]角色活动唤取获得</p><p>全新武器</p>"}]}
    cat13 = [badge("锁暝", "2026-09-03 00:00:00", "2027-09-03 00:00:00"),
             badge("新来的", "2026-10-01 00:00:00", "2026-11-12 00:00:00")]
    got, _n, notes, warns = run_wuwa(NOW, first, five, {"X": "心"}, cat13)
    check("fixture: no debut read, the running pool still reported",
          ([b.name for b in got], any("读不出这一版的新角色" in m for m in warns)), (["但愿长圆如此夜"], True))
    check("the bulletin's own second-half character is not called next version's",
          notes.get("鸣潮", ""), "官方已预告下一版新角色：新来的")
    untitled = {"game": [{"tabTitle": "3.7版本更新公告", "content": "<p>五星共鸣者「锁暝」</p>"}]}
    got, _n, notes, _w = run_wuwa(NOW, first, untitled, {"X": "心"}, cat13)
    check("no bulletin text at all: no 「next version」 claim, since none can be told apart",
          "下一版" in notes.get("鸣潮", ""), False)


def _part_wuwa_middot():
    """A debut whose name has a middle dot is not dropped as a rerun.

The Kuro wiki spells 秧秧·玄翎 with U+00B7 (wuwa_catalogue_2026-09-12.json); the
in-game notice spells it 秧秧・玄翎 with U+30FB (maint/ww_notice.json). _wuwa keeps
only the running pools whose character is in the bulletin's 「全新角色」 section,
comparing the strings as they are, so the running debut was filtered out as a
rerun and its line vanished without a warning. Runs _wuwa itself with fakes.

    Formerly test_wuwa_middot.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ark_relay.features.banners.banners as _b
    from ark_relay.features.banners import wuwa as W


    WIKI = "秧秧·玄翎"       # U+00B7, as the wiki writes it
    GAME = "秧秧・玄翎"       # U+30FB, as the game notice writes it
    NOW = datetime(2026, 10, 13, 12, 0)

    home = {"code": 200, "data": {"contentJson": {"sideModules": [{
        "title": "角色活动唤取",
        "content": {"tabs": [{"name": "某某之池",
                              "countDown": {"dateRange": ["2026-10-01 11:00", "2026-10-22 09:59"]},
                              "imgs": [{"linkConfig": {"entryId": 777}}]}]}}]}}}
    notice = {
        "game": [{"tabTitle": "3.7版本内容说明",
                  "content": f"<p>全新角色</p><p>5星共鸣者「{GAME}」</p>"
                             "<p>※可通过[某某之池]角色活动唤取获得</p><p>全新武器</p>"}],
        "recommend": [{"tabTitle": "[某某之池]角色活动唤取",
                       "content": f"5星角色「{GAME}」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}],
    }


    def fake_json(url, *a, **k):
        if url == W._WW_NOTICE:
            return notice
        if url.endswith("/wiki/core/homepage/getPage"):
            return home
        if url.endswith("/wiki/core/catalogue/item/getEntryDetail"):
            return {"code": 200, "data": {"name": WIKI}}
        if url.endswith("/wiki/core/catalogue/item/getPage"):
            return {"code": 200, "data": {"results": {"records": []}}}
        raise OSError(f"offline: {url}")


    def offline(url, *a, **k):
        raise OSError(f"offline: {url}")


    print("[parsers fold every middle dot to U+00B7]")
    check("bulletin debut", W.parse_wuwa_preview(notice["game"][0]["content"]), [(WIKI, "某某之池")])
    check("notice banner", W.parse_wuwa_notice_banners(notice)[0].chars, (WIKI,))
    for dot in ("·", "・", "･", "•", "‧"):
        check(f"U+{ord(dot):04X} folds", W._one_dot(f"秧秧{dot}玄翎"), WIKI)

    print("[_wuwa keeps the running debut]")
    real = _b._json, _b._text
    _b._json, _b._text = fake_json, offline
    try:
        tr = _b.Trace.new()
        got, _nxt = _b._wuwa(NOW, notes={}, trace=tr)
    finally:
        _b._json, _b._text = real
    check("the running debut is reported", [(b.name, b.chars) for b in got], [("某某之池", (WIKI,))])
    check("the game notice is matched to it",
          any("游戏公告" in x and "某某之池" in x for x in tr.sources), True)


def _part_wuwa_update_close():
    """Closing WuWa for real: the game, OK-WW and the Kuro launcher (preupdate_okww._okww_close).

The launcher runs as launcher_main.exe in a version folder
(D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe), which the old full-path match on
…\\Wuthering Waves\\launcher.exe missed (2026-09-30). And 「已关掉」 was said without
looking: taskkill from session 0 does not reach the game under its anti-cheat
(echofarm._kill_on_desktop, 2026-09-09), and its return code was never read.

The relay's own WuWa client update through the launcher (update_wuwa, whose ready
words and timeouts were tested here) went on 2026-10-12: AUTO-MAS updates the
client before an OK-WW run (item 10b).

    Formerly test_wuwa_update_close.py.
    """
    import json
    import subprocess
    from pathlib import Path, PureWindowsPath

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.echofarm import echofarm
    from ark_relay.features.preupdate import preupdate_okww as pk


    nosleep = lambda s: None  # noqa: E731

    print("[启动器进程：按启动器目录前缀认 launcher.exe 和 launcher_main.exe]")
    root = PureWindowsPath("D:/Wuthering Waves")
    check("版本子目录里的 launcher_main.exe", pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe", root), True)
    check("入口壳 launcher.exe", pk._is_wuwa_launcher("D:\\Wuthering Waves\\launcher.exe", root), True)
    check("斜杠和大小写不影响", pk._is_wuwa_launcher("d:/wuthering waves/2.6.5.0/LAUNCHER_MAIN.EXE", root), True)
    check("别的目录同名不算", pk._is_wuwa_launcher("C:\\Other\\launcher_main.exe", root), False)
    check("前缀要到目录边界（Wuthering Waves Game 不算）",
          pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher.exe", root), False)
    check("同目录别的程序不算", pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\Client.exe", root), False)
    check("没有目录时按 \\Wuthering Waves\\ 这一段认 launcher_main.exe",
          pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe"), True)
    check("没有目录时游戏本体目录不算", pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher_main.exe"), False)

    print("[taskkill 看返回码：失败的不算关掉]")
    PROCS = [{"ProcessId": 4242, "ExecutablePath": "D:\\Wuthering Waves\\launcher.exe"},
             {"ProcessId": 4343, "ExecutablePath": "D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe"},
             {"ProcessId": 5151, "ExecutablePath": "C:\\Program Files\\Other\\launcher_main.exe"}]


    class R:
        def __init__(self, rc=0, out=b""):
            self.returncode, self.stdout, self.stderr = rc, out, b"ERROR: Access is denied."


    calls = []
    real_run = subprocess.run


    def fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        if any("launcher_main.exe" in str(x) and "CimInstance" in str(x) for x in cmd):
            return R(0, json.dumps(PROCS).encode())
        if cmd[:3] == ["taskkill", "/F", "/PID"]:
            return R(0 if cmd[3] == "4242" else 1)
        return R()


    subprocess.run = fake_run
    try:
        stopped = pk._stop_wuwa_launcher(root)
    finally:
        subprocess.run = real_run
    kills = [c for c in calls if c[:1] == ["taskkill"]]
    check("两个都试了（按 PID）", [c[3] for c in kills], ["4242", "4343"])
    check("只记返回 0 的那个", stopped, [4242])
    check("别处的不碰", any("5151" in c for c in kills), False)
    check("列进程一次查两个名字", sum(1 for c in calls if any("Name='launcher_main.exe'" in str(x) for x in c)), 1)

    print("[_okww_close：关完复查，剩下的从桌面会话再关一次，再说实话]")
    bat = tmpdir() / "ark-okww-stop.bat"
    echofarm.STOP_BAT = str(bat)          # never the repo cwd
    alive = {"game": ["Client-Win64-Shipping.exe"], "procs": [PROCS[1]]}
    real_alive = echofarm.game_alive
    echofarm.game_alive = lambda timeout=None: list(alive["game"])
    calls.clear()


    def run2(cmd, *a, **k):
        calls.append(list(cmd))
        if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
            return R(0, json.dumps(alive["procs"]).encode())
        if cmd[:1] == ["taskkill"]:
            return R(1)                   # session 0 cannot reach it
        if cmd[:2] == ["schtasks", "/run"]:
            alive["game"], alive["procs"] = [], []    # the desktop door worked
        return R()


    subprocess.run = run2
    try:
        left = pk._okww_close(sleep=nosleep, launcher_root=root)
    finally:
        subprocess.run = real_run
    check("桌面那边关掉了 → []", left, [])
    text = bat.read_text(encoding="utf-8")
    check("bat 里按 PID 关启动器", "taskkill /F /PID 4343" in text, True)
    check("bat 里照旧按名字关游戏", 'taskkill /F /IM "Client-Win64-Shipping.exe"' in text, True)
    check("走了计划任务", any(c[:2] == ["schtasks", "/run"] for c in calls), True)

    alive.update(game=["Client-Win64-Shipping.exe"], procs=[PROCS[1]])


    def run3(cmd, *a, **k):
        calls.append(list(cmd))
        if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
            return R(0, json.dumps(alive["procs"]).encode())
        return R(1) if cmd[:1] == ["taskkill"] else R()


    subprocess.run = run3
    try:
        left = pk._okww_close(sleep=nosleep, launcher_root=root)
    finally:
        subprocess.run = real_run
    check("都没关掉 → 点名", left, ["Client-Win64-Shipping.exe", "launcher_main.exe"])

    # Bounded as echofarm.stop_okww (audit 11-08 A-22: run_okww now waits on this before it puts
    # the switch back): a look that takes long uses the budget up and the looks stop.
    clock = [0.0]


    def run4(cmd, *a, **k):
        calls.append(list(cmd))
        if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
            clock[0] += 20                # a slow WMI answer
            return R(0, json.dumps(alive["procs"]).encode())
        return R(1) if cmd[:1] == ["taskkill"] else R()


    subprocess.run = run4
    looks = []
    real_left = pk._okww_left
    pk._okww_left = lambda r, t=None: looks.append(t) or real_left(r, t)
    try:
        left = pk._okww_close(sleep=nosleep, launcher_root=root, clock=lambda: clock[0])
    finally:
        subprocess.run, pk._okww_left = real_run, real_left
    check("限时：用完 STOP_OKWW_SECONDS 就不再看（不是看满十次）", 1 < len(looks) < 10, True)
    check("……每次给 PowerShell 的时间不超过剩下的", all(t is not None and t <= echofarm.STOP_OKWW_SECONDS for t in looks), True)
    check("……照实说还在", left, ["Client-Win64-Shipping.exe", "launcher_main.exe"])

    alive.update(game=[], procs=[])
    subprocess.run = lambda cmd, *a, **k: (_ for _ in ()).throw(OSError("no pwsh")) \
        if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd) else R()
    try:
        left, pids = pk._okww_left(root)
    finally:
        subprocess.run = real_run
    check("启动器列表读不到 → 说读不到，不当没了", left, ["鸣潮启动器（查不到它还开没开着）"])
    check("…也没有 PID 可关", pids, [])

    print("[启动器列表：pwsh 里出错（没输出）不当成「启动器已关」（审计 11-08 A-22）]")
    for label, answer, want in (("返回码不是 0", R(1, b""), None),
                                ("返回码 0、没输出、stderr 有错", R(0, b""), None),
                                ("返回码 0、没输出、stderr 也空：真的一个都没有", None, []),
                                ("返回码 0、有列表", R(0, json.dumps(PROCS[:1]).encode()), [(4242, PROCS[0]["ExecutablePath"])])):
        if answer is None:
            answer = R(0, b"")
            answer.stderr = b""
        subprocess.run = lambda cmd, *a, _r=answer, **k: _r
        try:
            check(label, pk._wuwa_launcher_procs(root), want)
        finally:
            subprocess.run = real_run
    echofarm.game_alive = real_alive


if __name__ == "__main__":
    sys.exit(run_parts([_part_wuwa_bulletin, _part_wuwa_middot, _part_wuwa_update_close]))
