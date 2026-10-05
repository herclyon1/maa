"""The three per-game client update flows: 终末地 / 鸣潮 / 明日方舟.

Split out of gameupdate.py on 2026-09-08, moved verbatim. Its own module because this
is the only part of the update feature that forks per game - each of the three has its
own launcher, its own screen strings, its own time budget and its own "the client is
ready" test - while gameupdate.py, which keeps the boot check, the register-now /
update-later bookkeeping and the after-the-queue re-run, is the same code whatever the
game. Everything public here is re-exported from gameupdate.py, so callers and tests
still write gameupdate.xxx.

The 「更新游戏」/「开始游戏」/「点击任意位置继续」 strings and READY_WORDS below are
**runtime data**: they are what OCR has to match on the screen, read off the machine by
hand. Rewording one of them breaks the flow silently.

Three games, three paths, all run in the boot window (after the pre-update, before the
queue):

* 终末地: the Hypergryph launcher (process Games, window 「鹰角启动器」). Read the
  screen: when the button says 「更新游戏」, click it and wait for it to become
  「开始游戏」; then start the game once to get past 「资源初始化更新完成，请重启游戏」
  and the shader compilation - it is only done once 「点击任意位置继续」 shows up.
  Walked through by hand on 2026-09-02; every string here was read off the screen that
  day.
* 鸣潮: the Kuro launcher (launcher.exe, the shell with the update button; the
  Wuthering Waves.exe in the game folder starts the game itself). Same thing: read the
  screen, click 「更新」, wait for 「开始游戏」. OK-WW handles updates itself as well;
  all this does is keep it from colliding with a download in progress.
* 明日方舟: the emulator UI is never clicked. The official version endpoint gives
  clientVersion; compare it against the installed version recorded last time, and when
  they differ download the APK (official direct link, around 2 GB, resumable), start
  LDPlayer, install it with `ldconsole installapp`, read dumpsys afterwards to confirm
  the version, then quit the emulator. With no record yet, start the emulator once first
  to read and record the installed version.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ
from .desktop import Desktop, kill

log = logging.getLogger("ark.gameupdate")

_UA = "Mozilla/5.0"
AK_VERSION_URL = "https://ak-conf.hypergryph.com/config/prod/official/Android/version"
AK_APK_URL = "https://ak.hypergryph.com/downloads/android_lastest"
AK_PACKAGE = "com.hypergryph.arknights"


# ─────────────────────────── common ───────────────────────────

def _spawn(exe: Path, cwd: Path | None = None) -> bool:
    from .preupdate_common import _spawn_interactive  # noqa: PLC0415
    return _spawn_interactive(exe, cwd or exe.parent, require_console=True)


def _note(problems: list[str] | None, msg: str) -> None:
    if problems is not None:
        problems.append(msg)


def _focus_missing(scr) -> bool:
    """The desktop agent did not find the window it was asked to bring forward, so
    whatever it read belongs to some other window (or nothing). Such a screen must
    not be taken as "ready" or "up to date", and nothing may be clicked on it."""
    return bool(getattr(scr, "focus_missing", False))


def _unread(scr) -> str:
    """Why nothing of this screen counts, or "" when it was read. Covers the focus
    window not being found and the desktop agent itself failing (did not start,
    timed out, threw - Screen.error): either way the state is unknown, and an empty
    screen must not read as "no button" or lead to a blind tap."""
    if _focus_missing(scr):
        return "窗口没找到"
    err = getattr(scr, "error", "")
    return f"桌面助手读屏失败：{err}" if err else ""


# ─────────────────────────── Endfield 终末地 ───────────────────────────

def endfield_paths(maaend_dir: Path | None) -> tuple[Path | None, Path | None]:
    """(game exe, launcher exe). The game path is read from MaaEnd's own config, not guessed."""
    if not maaend_dir:
        return None, None
    cfg = Path(maaend_dir) / "config" / "mxu-MaaEnd.json"
    try:
        m = re.search(r'"connectedProgramPath"\s*:\s*"([^"]+)"', cfg.read_text(encoding="utf-8"))
    except OSError:
        return None, None
    if not m:
        return None, None
    game = Path(m.group(1).replace("\\\\", "\\"))
    # D:\endfield\Hypergryph Launcher\games\Endfield Game\Endfield.exe -> three
    # levels up is the launcher directory
    launcher = game.parents[2] / "Launcher.exe" if len(game.parents) >= 3 else None
    return game, (launcher if launcher and launcher.exists() else None)


# The Hypergryph launcher while it is working (read off the screen 2026-09-02, the
# same words the wait loop below logs). Seen on the first look, the launcher is
# resuming a download it started earlier: wait for it, never click and never kill.
_EF_BUSY = ("正在下载", "安装中")


def update_endfield(desk: Desktop, game: Path, launcher: Path, *,
                    budget_s: float = 2400, poll_s: float = 30,
                    problems: list[str] | None = None, sleep=time.sleep) -> str:
    """Returns one sentence for a human; empty string when nothing was updated."""
    kill("Endfield.exe")
    if not _spawn(launcher):
        _note(problems, "终末地：启动器没能在桌面会话里起来")
        return ""
    sleep(25)
    scr = desk.read(focus="Games")
    if why := _unread(scr):
        # Not "up to date" and not "no button": nothing of the launcher was read.
        # Not killed either - a launcher sitting in the tray may be downloading.
        where = "没找到启动器窗口（Games）" if _focus_missing(scr) else f"启动器画面没读成（{why}）"
        _note(problems, f"终末地：{where}，画面读不到，没判断是否要更新，启动器没关（截图 {scr.shot}）")
        return ""
    busy = next((w for w in _EF_BUSY if scr.has(w)), "")
    if busy:
        log.info("游戏更新：终末地启动器一打开就是「%s」，在接着上次的下载，不点不关，等它装完", busy)
    elif scr.has("开始游戏"):
        log.info("游戏更新：终末地启动器已是「开始游戏」，无需更新")
        kill("Games.exe")
        return ""
    elif not scr.has("更新游戏"):
        _note(problems, f"终末地：启动器画面没读到按钮（截图 {scr.shot}）：{scr.dump(12)}")
        kill("Games.exe")
        return ""
    elif not desk.click_text("更新游戏", focus="Games"):
        _note(problems, "终末地：点「更新游戏」没点上")
        kill("Games.exe")
        return ""
    else:
        log.info("游戏更新：终末地已点「更新游戏」，等它下载安装")
    deadline = time.monotonic() + budget_s
    ready = False
    while time.monotonic() < deadline:
        sleep(poll_s)
        scr = desk.read(focus="Games")
        if not _unread(scr) and scr.has("开始游戏"):
            ready = True
            break
        log.info("游戏更新：终末地启动器 %s", _unread(scr) or
                 (next((ln for w in _EF_BUSY if (ln := scr.find(w))), None) or scr.dump(4)))
    if not ready:
        _note(problems, f"终末地：{budget_s / 60:.0f} 分钟内没等到「开始游戏」，启动器留在后台继续下，下次开机再确认")
        return ""
    # Installed. Start the game once to get 「资源初始化」 and the shader compilation
    # out of the way, or the morning shift's first round is certain to stall.
    if not desk.click_text("开始游戏", focus="Games"):
        # Said in the sentence, not as a problem: the update itself is installed, and
        # a problem entry would make _prepare_until_ready redo the whole update in 10
        # minutes - which then finds 「开始游戏」 and calls it "no update needed",
        # hiding this. The game was not started, so nothing is waited for.
        log.warning("游戏更新：终末地装完了，但「开始游戏」没点上，没预热（截图 %s）", scr.shot)
        kill("Games.exe")
        return "终末地 客户端已通过启动器更新，但「开始游戏」没点上，没预热，早班第一轮会卡在资源初始化"
    sleep(90)
    deadline = time.monotonic() + 900
    restarted = False
    while time.monotonic() < deadline:
        scr = desk.read(focus="Endfield")
        if not _unread(scr) and scr.has(*READY_WORDS["终末地"]):
            log.info("游戏更新：终末地已到标题画面（读到「点击任意位置继续」），客户端可用")
            break
        if scr.has("请重启游戏") and not restarted:
            if not desk.click_text("确认", focus="Endfield"):
                # The kill below closes the game either way; only say it.
                log.warning("游戏更新：终末地「请重启游戏」的「确认」没点上，直接关掉重开")
            sleep(8)
            kill("Endfield.exe")
            sleep(3)
            _spawn(game)
            restarted = True
            sleep(60)
            continue
        if scr.has("客户端版本已过时"):
            _note(problems, "终末地：更新后游戏仍说客户端已过时")
            kill("Endfield.exe", "Games.exe")
            # A problem plus 「已更新」 contradicts itself in the daily report.
            return ""
        sleep(poll_s)
    else:
        _note(problems, f"终末地：更新后 15 分钟没走到标题画面，中继不再等（最后一屏截图 {scr.shot}）")
        kill("Endfield.exe", "Games.exe")
        return ""
    kill("Endfield.exe", "Games.exe")
    return "终末地 客户端已通过启动器更新"


# ─────────────── "reached the login screen": one test per game ───────────────
# The login-screen strings for all three games come verbatim from the screenshots the
# user supplied on 2026-09-03; not one of them is a guess:
#   终末地「点击任意位置继续」(also read during the 09-02 update)
#   明日方舟「开始唤醒」(inside LDPlayer, Ver 2.7.61 screenshot)
#   鸣潮「点击连接」(CN_Android_Product_3.6.0 screenshot)
# If the string is never read, wait until the budget runs out and then report "not
# ready" - readiness is never inferred from elapsed time (the user:
# 「合着窗口四五分钟后还在更新你就按就绪处理了？」).
READY_WORDS = {
    "终末地": ("点击任意位置继续",),
    "鸣潮": ("点击连接",),
    "明日方舟": ("开始唤醒",),
}


def wait_ready(desk: Desktop, game: str, *, focus: str, alive, budget_s: float = 900,
               poll_s: float = 30, sleep=time.sleep) -> str:
    """Wait for the login screen. Returns the evidence sentence (empty = not read
    within the budget, or the process is gone)."""
    t0 = time.monotonic()
    last = ""
    while time.monotonic() - t0 < budget_s:
        if not alive():
            log.warning("游戏更新：%s 进程没了，没等到登录界面", game)
            return ""
        scr = desk.read(focus=focus)
        for w in (() if _unread(scr) else READY_WORDS.get(game, ())):
            if scr.has(w):
                log.info("游戏更新：%s 到登录界面（读到「%s」）", game, w)
                return f"读到「{w}」"
        last = _unread(scr) or scr.dump(6)
        sleep(poll_s)
    log.warning("游戏更新：%s %.0f 分钟内没读到登录界面的字，最后一屏：%s", game, budget_s / 60, last)
    return ""


def _alive(exe: str):
    """A probe for "is exe still running". When tasklist cannot answer (it raised,
    exited non-zero or printed nothing) the answer is unknown, and unknown is not
    "dead": it says True, but says so in the log - an empty listing used to read as
    「进程没了」 and end the wait for the login screen."""
    import subprocess as _sp  # noqa: PLC0415
    def f() -> bool:
        try:
            r = _sp.run(["tasklist"], capture_output=True, timeout=30)
            code, out = r.returncode, (r.stdout or b"")
        except Exception as exc:  # noqa: BLE001 - any failure to read the list is "unknown"
            log.warning("游戏更新：tasklist 没跑成（%s），当 %s 还在", exc, exe)
            return True
        if code != 0 or not out.strip():
            log.warning("游戏更新：tasklist 退出码 %s、输出 %d 字节，读不出 %s 在不在，当它还在",
                        code, len(out), exe)
            return True
        return exe.encode() in out
    return f


# ─────────────────────────── Wuthering Waves 鸣潮 ───────────────────────────

def wuwa_launcher(okww_dir: Path | None) -> Path | None:
    """The Kuro launcher: the shell with the 「更新」 button, launcher.exe.

    Not Wuthering Waves.exe in the game folder: that one is the game body's
    starter and goes straight to Client-Win64-Shipping.exe with no button to
    click. On 2026-09-30 this returned D:\\Wuthering Waves Game\\Wuthering Waves.exe,
    update_wuwa found no button and gave up (15:50); the real launcher,
    D:\\Wuthering Waves\\launcher.exe, clicked 「更新」 at 15:53.

    The game folder comes from OK-WW's config (_wuwa_game_exe); the launcher is
    looked for next to it (<parent>\\Wuthering Waves\\launcher.exe, the layout on
    the machine) or one level up (<launcher dir>\\<game dir>, Kuro's default).
    When neither exists, fall back to the game body and say so in the log.
    """
    game = _wuwa_game_exe(okww_dir)
    if game is None:
        return None
    looked = _wuwa_launcher_candidates(game.parent)
    for cand in looked:
        if cand.is_file():
            return cand
    log.warning("游戏更新：没找到鸣潮启动器 launcher.exe（找过 %s），只能用游戏本体 %s——它没有「更新」按钮",
                "、".join(str(c) for c in looked), game)
    return game


def _wuwa_launcher_candidates(game_dir: Path) -> list[Path]:
    """Where launcher.exe may sit relative to the game folder: a sibling folder
    named Wuthering Waves, or the game folder's parent (never a drive root)."""
    parent = game_dir.parent
    out = [parent / "Wuthering Waves" / "launcher.exe"]
    if parent != parent.parent:
        out.append(parent / "launcher.exe")
    return out


def _wuwa_game_exe(okww_dir: Path | None) -> Path | None:
    """The game body's starter: the value ending in Wuthering Waves.exe in
    OK-WW's own config, else the usual install path."""
    if not okww_dir:
        return None
    root = Path(okww_dir) / "data" / "apps" / "ok-ww" / "working" / "configs"
    for f in root.glob("*.json"):
        try:
            m = re.search(r'"([^"]*Wuthering Waves\.exe)"', f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if m:
            p = Path(m.group(1).replace("\\\\", "\\"))
            if p.exists():
                return p
    fallback = Path(r"D:\Wuthering Waves Game\Wuthering Waves.exe")
    return fallback if fallback.exists() else None


# The Kuro launcher's "ready to play" button. Measured 2026-09-30 16:58 on launcher
# 3.7: after the update it reads 「进入游戏」, not 「开始游戏」 (while downloading
# 「下载中」, while unpacking 「解压中」, once pressed 「进入中」 / 「检查游戏版本和文件」).
# Waiting for 「开始游戏」 alone sat out the full 40 minutes with the update done.
_WW_READY = ("开始游戏", "进入游戏")
# The same measurement's "working" words. Seen on the first look, the launcher is
# resuming a download (or already starting the game): wait, never click, never close.
_WW_BUSY = ("下载中", "解压中", "进入中", "检查游戏版本和文件")


def _ww_update_button(scr):
    """The update button. 「更新」 alone counts only as a whole OCR line: as a
    substring it also hits news titles like 「版本更新公告」, and that line got clicked."""
    btn = scr.find("立即更新") or scr.find("更新游戏")
    if btn is None:
        btn = next((ln for ln in scr.lines if ln.text.replace(" ", "") == "更新"), None)
    return btn


def _ww_ready(scr) -> str:
    """The ready word on the launcher screen, or ''."""
    return next((w for w in _WW_READY if scr.has(w)), "")


def _ww_closed(left: list[str]) -> str:
    """How the launcher and game ended up after _okww_close, said as it is."""
    return "已关掉启动器和游戏" if not left else "没关掉：" + "、".join(left) + " 还在"


def update_wuwa(desk: Desktop, launcher: Path, *, budget_s: float = 2400, poll_s: float = 30,
                problems: list[str] | None = None, sleep=time.sleep) -> str:
    from .preupdate_okww import _okww_close  # noqa: PLC0415 - kills shell + game + launcher
    # The launcher is stopped under the folder it was started from (the same
    # wuwa_launcher lookup), so launcher_main.exe in its version subfolder goes too.
    # When wuwa_launcher fell back to the game body there is no launcher folder;
    # _launcher_root then works it out (and falls back to the folder name).
    root = launcher.parent if launcher.name.lower() == "launcher.exe" else None

    def close() -> list[str]:
        left = _okww_close(sleep=sleep, launcher_root=root)
        if left:
            log.warning("游戏更新：鸣潮%s", _ww_closed(left))
        return left

    if not _spawn(launcher):
        _note(problems, "鸣潮：启动器没能在桌面会话里起来")
        return ""
    sleep(30)
    # The Kuro launcher's window is found by this title: measured on the machine
    # 2026-09-30 15:53, focus="title:鸣潮" read and clicked its update button.
    scr = desk.read(focus="title:鸣潮")
    if why := _unread(scr):
        # Nothing of the launcher was read: not "up to date", not "no button". Not
        # closed either - a launcher in the tray may be downloading.
        where = "没找到启动器窗口（标题含「鸣潮」）" if _focus_missing(scr) else f"启动器画面没读成（{why}）"
        _note(problems, f"鸣潮：{where}，画面读不到，没判断是否要更新，启动器没关（截图 {scr.shot}）")
        return ""
    busy = next((w for w in _WW_BUSY if scr.has(w)), "")
    if busy:
        log.info("游戏更新：鸣潮启动器一打开就是「%s」，在接着上次的活，不点不关，等它装完", busy)
    elif word := _ww_ready(scr):
        log.info("游戏更新：鸣潮启动器已是「%s」，无需更新", word)
        close()
        return ""
    else:
        btn = _ww_update_button(scr)
        if btn is None:
            _note(problems, f"鸣潮：启动器画面没读到按钮（截图 {scr.shot}）：{scr.dump(12)}")
            close()
            return ""
        if not desk.click(*btn.center, focus="title:鸣潮"):
            left = close()
            _note(problems, f"鸣潮：点「{btn.text}」没点上（截图 {scr.shot}），{_ww_closed(left)}")
            return ""
        log.info("游戏更新：鸣潮已点「%s」，等它下载安装", btn.text)
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        sleep(poll_s)
        scr = desk.read(focus="title:鸣潮")
        if why := _unread(scr):
            log.info("游戏更新：鸣潮启动器这一眼没读到（%s），接着等", why)
            continue
        if word := _ww_ready(scr):
            # Installed. Press the ready button to bring the game up to the login
            # screen (this is when the shaders get compiled)
            if not desk.click_text(word, focus="title:鸣潮"):
                # In the sentence, not a problem: the update is installed, and a
                # problem would send run_deferred round the whole update again,
                # where 「进入游戏」 then reads as "no update needed". The game was not
                # started, so there is no login screen to wait for.
                log.warning("游戏更新：鸣潮装完了，但「%s」没点上，没进游戏（截图 %s）", word, scr.shot)
                left = close()
                return (f"鸣潮 客户端已通过启动器更新，但「{word}」没点上，没进游戏预热"
                        + (f"；{_ww_closed(left)}" if left else ""))
            sleep(90)
            how = wait_ready(desk, "鸣潮", focus="Client-Win64-Shipping",
                             alive=_alive("Client-Win64-Shipping.exe"), sleep=sleep)
            left = close()
            if not how:
                _note(problems, "鸣潮：更新后游戏没走到登录界面")
            # Not a problem entry: the update itself went through, and a problem
            # would send run_deferred round the whole update again in 10 minutes.
            return ("鸣潮 客户端已通过启动器更新" + (f"，已到登录界面（{how}）" if how else "")
                    + (f"；{_ww_closed(left)}" if left else ""))
    # Closed first, then said as it is: session 0's taskkill does not always reach
    # the game (echofarm._kill_on_desktop), so 「已关掉」 is only written when it is.
    left = close()
    _note(problems, f"鸣潮：{budget_s / 60:.0f} 分钟内没等到「开始游戏」或「进入游戏」，"
                    f"{_ww_closed(left)}" + ("，免得和 OK-WW 撞车" if not left else "，会和 OK-WW 撞车"))
    return ""


# ─────────────────────────── Arknights 明日方舟 ───────────────────────────

def ldconsole_of(maa_dir: Path | None) -> tuple[Path | None, int]:
    """(ldconsole.exe, instance index). Read from MAA's own config: AdbPath and the
    LDPlayer shortcut."""
    if not maa_dir:
        return None, 0
    try:
        text = (Path(maa_dir) / "config" / "gui.new.json").read_text(encoding="utf-8")
    except OSError:
        return None, 0
    m = re.search(r'"AdbPath"\s*:\s*"([^"]+)"', text)
    if not m:
        return None, 0
    exe = Path(m.group(1).replace("\\\\", "\\")).parent / "ldconsole.exe"
    idx = 0
    if mi := re.search(r"雷电模拟器-(\d+)\.lnk", text):
        idx = int(mi.group(1))
    return (exe if exe.exists() else None), idx


# Worked out step by step on the machine on 09-03 (written down here; stop guessing):
# * `ldconsole launch/isrunning/quit` **does not work** on this machine's instance
#   (isrunning always says stop, quit/quitall cannot close it). Starting the emulator
#   goes through the shortcut MAA uses: dnplayer.exe index=1000, and it must be started
#   in an interactive session (from session 0 it comes up as a zombie process).
# * "It is up" is judged with adb: emulator-7554 appears in `adb devices`, and dumpsys
#   can read a versionName.
# * Start the game: `adb shell am start -n com.hypergryph.arknights/com.u8.sdk.U8UnityContext`
#   (the entry point resolve-activity found); stop the game with `am force-stop`; stop
#   the emulator with taskkill dnplayer.
AK_ACTIVITY = "com.hypergryph.arknights/com.u8.sdk.U8UnityContext"
_EMU_EXES = ("dnplayer.exe", "LdVBoxHeadless.exe", "LdBoxHeadless.exe")


def _sh(args, t=120) -> str:
    try:
        r = subprocess.run(args, capture_output=True, timeout=t)
        return (r.stdout + r.stderr).decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def _sh_long(args) -> str:
    return _sh(args, 900)        # installing a 2 GB APK


def adb_of(ldconsole: Path) -> Path:
    return Path(ldconsole).parent / "adb.exe"


def adb_device(ldconsole: Path, run=None) -> str:
    out = (run or _sh)([str(adb_of(ldconsole)), "devices"])
    for l in (out or "").splitlines()[1:]:
        if l.strip().endswith("device"):
            return l.split()[0]
    return ""


def installed_ak_version(ldconsole: Path, idx: int, run=None) -> str:
    """versionName from dumpsys. Empty string when the emulator is not up."""
    run = run or _sh
    dev = adb_device(ldconsole, run)
    if not dev:
        return ""
    out = run([str(adb_of(ldconsole)), "-s", dev, "shell", f"dumpsys package {AK_PACKAGE}"])
    hits = re.findall(r"versionName=(\S+)", out or "")
    return hits[0] if hits else ""


def emulator_shortcut(maa_dir: Path | None, idx: int) -> tuple[Path, tuple[str, ...]]:
    """Target of the shortcut MAA uses to start the emulator: (dnplayer.exe, ('index=1000',))."""
    ld, _ = ldconsole_of(maa_dir)
    exe = Path(ld).parent / "dnplayer.exe" if ld else Path(r"D:\LD-MRFZ\LDPlayer9\dnplayer.exe")
    return exe, (f"index={idx}",)


def _spawn_args(exe: Path, args: tuple[str, ...]) -> bool:
    from .preupdate_common import _spawn_interactive  # noqa: PLC0415
    return _spawn_interactive(exe, exe.parent, args, require_console=True)


def emulator_boot(maa_dir: Path | None, ldconsole: Path, idx: int, *, run=None, sleep=time.sleep,
                  spawn=None, wait_s: float = 240) -> bool:
    """Start LDPlayer until adb answers. Clear zombie processes first (isrunning is
    not trustworthy; go by adb only)."""
    run = run or _sh
    spawn = spawn or _spawn_args
    if not adb_device(ldconsole, run):
        for exe in _EMU_EXES:
            run(["taskkill", "/F", "/IM", exe])
        sleep(3)
        exe, args = emulator_shortcut(maa_dir, idx)
        if not spawn(exe, args):
            return False
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait_s:
        if installed_ak_version(ldconsole, idx, run):
            return True
        sleep(8)
    return False


# ak_prewarm's blind taps. The real prewarm on 09-04 (relay.log 12:38:55-12:40:17)
# needed three taps before 「开始唤醒」; five leaves room and still stops a tap loop
# on a screen nobody has seen.
_AK_MAX_TAPS = 5
# Words of a dialog: a tap at the bottom centre may land on one of its buttons, so
# while one is up nothing is tapped - just keep looking.
_AK_DIALOG = ("确认", "取消", "确定", "下载", "重试", "更新")


def ak_prewarm(ldconsole: Path, dev: str, desk: Desktop, *, run=None, sleep=time.sleep,
               budget_s: float = 900, max_taps: int = _AK_MAX_TAPS) -> str:
    """Start Arknights and get it to the login screen. Measured on 09-03: the first
    screen is a loading page carrying 「START」, and it only reaches 「开始唤醒」 after a
    tap at the bottom centre of the screen (about (800,855) at 1600x900). Returns the
    evidence sentence; empty when the login screen was not read (update_arknights
    notes that as the problem)."""
    run = run or _sh
    adb = str(adb_of(ldconsole))
    run([adb, "-s", dev, "shell", f"am start -n {AK_ACTIVITY}"])
    sleep(60)
    m = re.search(r"(\d+)x(\d+)", run([adb, "-s", dev, "shell", "wm size"]) or "")
    W, H = (int(m.group(1)), int(m.group(2))) if m else (1600, 900)
    t0 = time.monotonic()
    taps = 0
    last, shot = "", None
    while time.monotonic() - t0 < budget_s:
        scr = desk.read(focus="title:明日方舟")
        if why := _unread(scr):
            # Whatever was read belongs to another window, or nothing was read at
            # all: neither "ready" nor "unrecognised" can be told from it, so no tap
            last, shot = f"（{why}）", scr.shot
            log.info("游戏更新：明日方舟这一眼没读到（%s），不点，接着看", why)
            sleep(20)
            continue
        if scr.has(*READY_WORDS["明日方舟"]):
            log.info("游戏更新：明日方舟到登录界面（读到「开始唤醒」）")
            return "读到「开始唤醒」"
        last, shot = scr.dump(12), scr.shot
        # 「START」 is set in a decorative font and OCR may not read it (on 09-03 it
        # could not be read, but a blind tap worked), so an unrecognised screen gets a
        # tap at the bottom centre - but only a few, and never while a dialog is up:
        # that spot can be a dialog's button.
        # A substring scan of its own, not scr.has: Screen.find matches words of two
        # characters or fewer only as a whole line, and 「点击重试」 is a dialog too.
        dialog = next((w for w in _AK_DIALOG
                       if any(w in ln.text.replace(" ", "") for ln in scr.lines)), "")
        if dialog:
            log.info("游戏更新：明日方舟画面上有「%s」，像是弹窗，不点，接着看：%s", dialog, scr.dump(6))
        elif taps < max_taps:
            run([adb, "-s", dev, "shell", f"input tap {W // 2} {int(H * 0.95)}"])
            taps += 1
            log.info("游戏更新：明日方舟还没到登录界面，点了一下底部（START 位置）")
        else:
            log.info("游戏更新：明日方舟底部已点满 %d 下，不再点，接着看", max_taps)
        sleep(20)
    log.warning("游戏更新：明日方舟 %.0f 分钟内没读到「开始唤醒」（点了 %d 下），最后一屏（截图 %s）：%s",
                budget_s / 60, taps, shot, last)
    return ""


def emulator_quit(ldconsole: Path, idx: int, run=None, sleep=time.sleep) -> None:
    run = run or _sh
    dev = adb_device(ldconsole, run)
    if dev:
        run([str(adb_of(ldconsole)), "-s", dev, "shell", f"am force-stop {AK_PACKAGE}"])
    run([str(ldconsole), "quit", "--index", str(idx)])
    sleep(5)
    for exe in _EMU_EXES:
        run(["taskkill", "/F", "/IM", exe])


def remote_ak_version(fetch=None) -> str:
    data = fetch() if fetch else json.loads(
        urllib.request.urlopen(urllib.request.Request(
            AK_VERSION_URL, headers={"User-Agent": _UA}), timeout=20).read())
    return str((data or {}).get("clientVersion") or "")



def _store(state_dir):
    from .statestore import StateStore  # noqa: PLC0415 - avoid an import cycle
    return StateStore(state_dir)


def recorded_ak_version(state_dir: Path) -> str:
    d = _store(state_dir).get("updates", "arknights_client") or {}
    return str(d.get("version") or "") if isinstance(d, dict) else ""


def record_ak_version(state_dir: Path, version: str) -> None:
    _store(state_dir).set("updates", "arknights_client",
                          {"version": version, "at": datetime.now(tz=SERVER_TZ).isoformat()})


def download(url: str, dest: Path, *, timeout: float = 1500) -> bool:
    """Resumable download to dest. True only when the file is complete: its size
    matches the size the server gave. dest exists only once that is true, and
    update_arknights trusts an existing dest without looking again, so a file whose
    size could not be checked never becomes dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Range": f"bytes={have}-"})
    deadline = time.monotonic() + timeout
    try:
        r = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code != 416 or not have:
            raise
        # 416: nothing left after `have` bytes. That is "complete" only when the
        # server's own size (Content-Range: bytes */N) says so; anything else is a
        # .part that no Range request can ever finish, so it is dropped and the next
        # boot starts over (otherwise every boot raises 416 again).
        cr = (exc.headers.get("Content-Range") if exc.headers else "") or ""
        m = re.search(r"/(\d+)\s*$", cr)
        if m and int(m.group(1)) == have:
            part.replace(dest)
            return True
        log.warning("下载 %s：服务器说已下的 %d 字节之后没有内容（%s），对不上大小，删掉重下",
                    dest.name, have, cr or "没给总大小")
        part.unlink(missing_ok=True)
        return False
    with r:
        cr = r.headers.get("Content-Range") or ""
        if r.status == 200:
            # Server ignored Range: start over, and the size is the whole body.
            # (Adding the old partial size here made a restarted download never
            # match and fail on every boot.)
            have = 0
            total = int(r.headers.get("Content-Length") or 0)
        else:
            # 206: the full size is after the slash of Content-Range; without one,
            # what is already here plus this body
            m = re.search(r"/(\d+)\s*$", cr)
            total = int(m.group(1)) if m else (have + int(r.headers.get("Content-Length") or 0)
                                                if r.headers.get("Content-Length") else 0)
        with open(part, "ab" if have else "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                if total and have >= total:
                    break
                if time.monotonic() > deadline:
                    log.warning("下载 %s 超过预算，先停在 %d/%d，下次接着下", dest.name, have, total)
                    return False
    if not total:
        # No size from the server: nothing to check the file against, so it does
        # not count as complete (a truncated APK would go to adb install, and then
        # stay as dest for good).
        log.warning("下载 %s 服务器没给大小，核不了是否下完，不算完成（已下 %d）", dest.name, have)
        return False
    if have != total:
        log.warning("下载 %s 大小不对：%d != %d", dest.name, have, total)
        if have > total:
            part.unlink(missing_ok=True)      # can never shrink back to the right size
        return False
    part.replace(dest)
    return True


def update_arknights(state_dir: Path, ldconsole: Path, idx: int, *,
                     budget_s: float = 900, problems: list[str] | None = None,
                     fetch=None, run=None, sleep=time.sleep, downloader=download,
                     desk: Desktop | None = None, maa_dir: Path | None = None,
                     spawn=None) -> str:
    """Returns 「明日方舟 已更新：旧 → 新」 or an empty string."""
    run = run or _sh
    try:
        remote = remote_ak_version(fetch)
    except Exception as exc:  # noqa: BLE001
        _note(problems, f"明日方舟：官方的版本信息取不到（{exc}）")
        return ""
    if not remote:
        _note(problems, "明日方舟：官方的版本信息里没有客户端版本号")
        return ""
    local = recorded_ak_version(state_dir)

    def boot() -> bool:
        return emulator_boot(maa_dir, ldconsole, idx, run=run, sleep=sleep, spawn=spawn)

    if not local:
        # First time: start the emulator, read the installed version and record it;
        # only then is there anything to compare against
        if not boot():
            _note(problems, "明日方舟：起雷电读已装版本没成功（4 分钟内 adb 没通）")
            return ""
        local = installed_ak_version(ldconsole, idx, run)
        emulator_quit(ldconsole, idx, run, sleep)
        if local:
            record_ak_version(state_dir, local)
            log.info("游戏更新：明日方舟已装 %s（首次记录）", local)
        if not local or local == remote:
            return ""
    if local == remote:
        log.info("游戏更新：明日方舟已是 %s，无需更新", remote)
        return ""

    log.info("游戏更新：明日方舟 %s → %s，下载 APK", local, remote)
    apk = Path(state_dir) / "apk" / f"arknights-{remote}.apk"
    if not apk.exists():
        try:
            if not downloader(AK_APK_URL, apk, timeout=budget_s):
                _note(problems, f"明日方舟：APK 没下完（{local} → {remote}），下次开机接着下")
                return ""
        except Exception as exc:  # noqa: BLE001
            _note(problems, f"明日方舟：下载 APK 失败（{exc}）")
            return ""
    if not boot():
        _note(problems, "明日方舟：起雷电装包没成功（adb 没通）")
        return ""
    dev = adb_device(ldconsole, run)
    (_sh_long if run is _sh else run)([str(adb_of(ldconsole)), "-s", dev, "install", "-r", "-d", str(apk)])
    deadline = time.monotonic() + 600
    now_ver = ""
    while time.monotonic() < deadline:
        sleep(15)
        now_ver = installed_ak_version(ldconsole, idx, run)
        if now_ver == remote:
            break
    if now_ver == remote and desk is not None:
        # Start it once so it finishes downloading the version's assets and reaches
        # the login screen (the user, 2026-09-03: only the login screen counts as OK)
        how = ak_prewarm(ldconsole, dev, desk, run=run, sleep=sleep)
        log.info("游戏更新：明日方舟预热%s", f"完成（{how}）" if how else "没等到登录界面")
        if not how:
            _note(problems, "明日方舟：装完启动后 15 分钟没读到「开始唤醒」")
    emulator_quit(ldconsole, idx, run, sleep)
    if now_ver != remote:
        _note(problems, f"明日方舟：装完读到的版本是 {now_ver or '空'}，不是 {remote}")
        return ""
    record_ak_version(state_dir, remote)
    try:
        apk.unlink()
    except OSError:
        pass
    return f"明日方舟 已更新：{local} → {remote}（APK 已装进雷电）"
