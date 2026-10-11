"""The per-game client update flows: Endfield (终末地), Wuthering Waves (鸣潮).
Called from gameupdate.run_deferred after the queue, and its public names are
re-exported from gameupdate. Arknights (明日方舟) has none: AUTO-MAS checks and
installs its client before an MAA run since the 2026-10-11 switch-over
(Run.IfCheckGameUpdate / IfAutoInstallGameApk, item 10a of the hand-over list).

The screen strings (「更新游戏」, 「开始游戏」, READY_WORDS ...) are runtime data: OCR
matches them on the screen. They were read off the real screens; changing one
breaks the flow without an error.

* Endfield: the Hypergryph launcher (process Games). When its button reads
  「更新游戏」, click it and wait for 「开始游戏」; then start the game once, through
  「资源初始化更新完成，请重启游戏」, until 「点击任意位置继续」 shows.
* Wuthering Waves: the Kuro launcher (launcher.exe; the Wuthering Waves.exe in the
  game folder starts the game itself). Click its update button, wait for the
  ready button, start the game until the login screen.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from ark_relay.core.desktop import Desktop, kill
from ark_relay.features.preupdate.preupdate_common import _note

log = logging.getLogger("ark.gameupdate")

_UA = "Mozilla/5.0"


# ─────────────────────────── common ───────────────────────────

def _spawn(exe: Path, cwd: Path | None = None) -> bool:
    from ark_relay.features.preupdate.preupdate_common import _spawn_interactive  # noqa: PLC0415
    return _spawn_interactive(exe, cwd or exe.parent, require_console=True)


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


def _trace(desk, **entry) -> None:
    """One reading of a launcher or game screen for the machine checks of a game update
    (Desktop.note; machinechecks/system.py). A desk without a trace is left alone."""
    note = getattr(desk, "note", None)
    if callable(note):
        try:
            note(**entry)
        except Exception:  # evidence only, never in the flow's way
            log.debug("游戏更新：这一屏没记进核对用的记录", exc_info=True)


def _launcher_note(desk, game: str, stage: str, scr, busy_words, ready_words) -> None:
    """What a launcher screen read as: the working word on it (正在下载 / 下载中 ...),
    whether the ready button was there, and the raw text and screenshot."""
    try:
        why = _unread(scr)
        busy = "" if why else next((w for w in busy_words if scr.has(w)), "")
        line = scr.find(busy) if busy else None
        _trace(desk, what="launcher", game=game, stage=stage, unread=why, busy=busy,
               ready=bool(not why and any(scr.has(w) for w in ready_words)),
               line=getattr(line, "text", ""), dump=scr.dump(8), shot=str(scr.shot))
    except Exception:  # evidence only, never in the flow's way
        log.debug("游戏更新：这一屏没记进核对用的记录", exc_info=True)


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


# Words on the Hypergryph launcher while it downloads or installs. Seen on the
# first look, it is resuming an earlier download: wait, do not click, do not kill.
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
    _launcher_note(desk, "终末地", "first", scr, _EF_BUSY, ("开始游戏",))
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
        _launcher_note(desk, "终末地", "wait", scr, _EF_BUSY, ("开始游戏",))
        if not _unread(scr) and scr.has("开始游戏"):
            ready = True
            break
        log.info("游戏更新：终末地启动器 %s", _unread(scr) or
                 (next((ln for w in _EF_BUSY if (ln := scr.find(w))), None) or scr.dump(4)))
    if not ready:
        _note(problems, f"终末地：{budget_s / 60:.0f} 分钟内没等到「开始游戏」，启动器留在后台继续下，下次开机再确认")
        return ""
    # Installed. Start the game once so 「资源初始化」 and shader compilation are done
    # before the next round.
    if not desk.click_text("开始游戏", focus="Games"):
        # Said in the returned sentence, not as a problem: the update is installed,
        # and a problem would make _prepare_until_ready redo the update, which would
        # then read 「开始游戏」 as "no update needed".
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
# The login-screen strings, read from screenshots of each game. Readiness is only
# ever this string on screen, never inferred from elapsed time: wait_ready reports
# "not ready" when the budget runs out.
READY_WORDS = {
    "终末地": ("点击任意位置继续",),
    "鸣潮": ("点击连接",),
}


def wait_ready(desk: Desktop, game: str, *, focus: str, alive, budget_s: float = 900,
               poll_s: float = 30, sleep=time.sleep) -> str:
    """Wait for the login screen. Returns the evidence sentence (empty = not read
    within the budget, or the process is gone)."""
    t0 = time.monotonic()
    last = ""
    while time.monotonic() - t0 < budget_s:
        # Only a definite False ends the wait; None (the process list could not
        # be read, _alive) leaves the decision to the screen.
        if alive() is False:
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
    """A probe for "is exe still running": True / False from a process list that
    was read, None when tasklist cannot answer (it raised, exited non-zero or
    printed nothing). None is "unknown"; wait_ready keeps reading the screen on
    None and only False ends the wait."""
    import subprocess as _sp  # noqa: PLC0415
    def f() -> "bool | None":
        try:
            r = _sp.run(["tasklist"], capture_output=True, timeout=30)
            code, out = r.returncode, (r.stdout or b"")
        except Exception as exc:  # noqa: BLE001 - any failure to read the list is "unknown"
            log.warning("游戏更新：tasklist 没跑成（%s），%s 在不在不知道，接着看屏幕", exc, exe)
            return None
        if code != 0 or not out.strip():
            log.warning("游戏更新：tasklist 退出码 %s、输出 %d 字节，读不出 %s 在不在，接着看屏幕",
                        code, len(out), exe)
            return None
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
    from ark_relay.features.preupdate.preupdate_okww import _okww_close  # noqa: PLC0415 - kills shell + game + launcher
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
    _launcher_note(desk, "鸣潮", "first", scr, _WW_BUSY, _WW_READY)
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
        _launcher_note(desk, "鸣潮", "wait", scr, _WW_BUSY, _WW_READY)
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


def _store(state_dir):
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415 - avoid an import cycle
    return StateStore(state_dir)
