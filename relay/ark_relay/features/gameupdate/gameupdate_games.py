"""The client update flow for Endfield (终末地), the one game AUTO-MAS cannot update.
Called from gameupdate.run_deferred after the queue, and its public names are
re-exported from gameupdate. Arknights (明日方舟) has none: AUTO-MAS checks and
installs its client before an MAA run since the 2026-10-11 switch-over
(Run.IfCheckGameUpdate / IfAutoInstallGameApk, item 10a of the hand-over list).
Wuthering Waves (鸣潮) has none since 2026-10-12: AUTO-MAS checks the official
version and patches the client before an OK-WW run (OK-WW script Game.Enabled /
Game.Path / Game.IfAutoUpdate, item 10b).

The screen strings (「更新游戏」, 「开始游戏」, READY_WORDS ...) are runtime data: OCR
matches them on the screen. They were read off the real screens; changing one
breaks the flow without an error.

* Endfield: the Hypergryph launcher (process Games). When its button reads
  「更新游戏」, click it and wait for 「开始游戏」; then start the game once, through
  「资源初始化更新完成，请重启游戏」, until 「点击任意位置继续」 shows.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from ark_relay.core.desktop import Desktop, kill
from ark_relay.features.preupdate.preupdate_common import _note

log = logging.getLogger("ark.gameupdate")


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


# ─────────────── "reached the title screen" ───────────────
# The title-screen string, read from screenshots of the game. Readiness is only
# ever this string on screen, never inferred from elapsed time.
READY_WORDS = {
    "终末地": ("点击任意位置继续",),
}


def _store(state_dir):
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415 - avoid an import cycle
    return StateStore(state_dir)
