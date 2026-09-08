"""On a major-version update day, update the three game clients ourselves.

The user, 2026-09-02: 「大版本鸣潮和终末地都有启动器去更新，明日方舟是通过模拟器
里面去更新安装包然后再手动点进去更新……希望你能帮我实现自动化。」

Three games, three paths, all run in the boot window (after the pre-update, before the
queue):

* 终末地: the Hypergryph launcher (process Games, window 「鹰角启动器」). Read the
  screen: when the button says 「更新游戏」, click it and wait for it to become
  「开始游戏」; then start the game once to get past 「资源初始化更新完成，请重启游戏」
  and the shader compilation - it is only done once 「点击任意位置继续」 shows up.
  Walked through by hand on 2026-09-02; every string here was read off the screen that
  day.
* 鸣潮: the Kuro launcher (Wuthering Waves.exe is the shell). Same thing: read the
  screen, click 「更新」, wait for 「开始游戏」. OK-WW handles updates itself as well;
  all this does is keep it from colliding with a download in progress.
* 明日方舟: the emulator UI is never clicked. The official version endpoint gives
  clientVersion; compare it against the installed version recorded last time, and when
  they differ download the APK (official direct link, around 2 GB, resumable), start
  LDPlayer, install it with `ldconsole installapp`, read dumpsys afterwards to confirm
  the version, then quit the emulator. With no record yet, start the emulator once first
  to read and record the installed version.

Every step logs its conclusion; anything that could not be confirmed goes into problems,
and the caller pushes 「⚠️ 没能确认」.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ
from .desktop import Desktop, kill
from .config import atomic_write_text

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
    if scr.has("开始游戏"):
        log.info("游戏更新：终末地启动器已是「开始游戏」，无需更新")
        kill("Games.exe")
        return ""
    if not scr.has("更新游戏"):
        _note(problems, f"终末地：启动器画面没读到按钮（截图 {scr.shot}）：{scr.dump(12)}")
        kill("Games.exe")
        return ""
    if not desk.click_text("更新游戏", focus="Games"):
        _note(problems, "终末地：点「更新游戏」没点上")
        kill("Games.exe")
        return ""
    log.info("游戏更新：终末地已点「更新游戏」，等它下载安装")
    deadline = time.monotonic() + budget_s
    ready = False
    while time.monotonic() < deadline:
        sleep(poll_s)
        scr = desk.read(focus="Games")
        if scr.has("开始游戏"):
            ready = True
            break
        log.info("游戏更新：终末地启动器 %s", scr.find("正在下载") or scr.find("安装中") or scr.dump(4))
    if not ready:
        _note(problems, f"终末地：{budget_s / 60:.0f} 分钟内没等到「开始游戏」，启动器留在后台继续下，下次开机再确认")
        return ""
    # Installed. Start the game once to get 「资源初始化」 and the shader compilation
    # out of the way, or the morning shift's first round is certain to stall.
    desk.click_text("开始游戏", focus="Games")
    sleep(90)
    deadline = time.monotonic() + 900
    restarted = False
    while time.monotonic() < deadline:
        scr = desk.read(focus="Endfield")
        if scr.has(*READY_WORDS["终末地"]):
            log.info("游戏更新：终末地已到标题画面（读到「点击任意位置继续」），客户端可用")
            break
        if scr.has("请重启游戏") and not restarted:
            desk.click_text("确认", focus="Endfield")
            sleep(8)
            kill("Endfield.exe")
            sleep(3)
            _spawn(game)
            restarted = True
            sleep(60)
            continue
        if scr.has("客户端版本已过时"):
            _note(problems, "终末地：更新后游戏仍说客户端已过时")
            break
        sleep(poll_s)
    else:
        _note(problems, "终末地：更新后 15 分钟没走到标题画面（可能还在编译着色器）")
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
        for w in READY_WORDS.get(game, ()):
            if scr.has(w):
                log.info("游戏更新：%s 到登录界面（读到「%s」）", game, w)
                return f"读到「{w}」"
        last = scr.dump(6)
        sleep(poll_s)
    log.warning("游戏更新：%s %.0f 分钟内没读到登录界面的字，最后一屏：%s", game, budget_s / 60, last)
    return ""


def _alive(exe: str):
    import subprocess as _sp  # noqa: PLC0415
    def f() -> bool:
        try:
            out = _sp.run(["tasklist"], capture_output=True, timeout=30).stdout
            return exe.encode() in out
        except Exception:  # noqa: BLE001
            return True
    return f


# ─────────────────────────── Wuthering Waves 鸣潮 ───────────────────────────

def wuwa_launcher(okww_dir: Path | None) -> Path | None:
    """Path to the launcher (the shell): the value ending in Wuthering Waves.exe,
    taken from OK-WW's own config."""
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


def update_wuwa(desk: Desktop, launcher: Path, *, budget_s: float = 2400, poll_s: float = 30,
                problems: list[str] | None = None, sleep=time.sleep) -> str:
    from .preupdate_okww import _okww_quiesce  # noqa: PLC0415 - kills shell + game
    if not _spawn(launcher):
        _note(problems, "鸣潮：启动器没能在桌面会话里起来")
        return ""
    sleep(30)
    scr = desk.read(focus="title:鸣潮")
    if scr.has("开始游戏"):
        log.info("游戏更新：鸣潮启动器已是「开始游戏」，无需更新")
        _okww_quiesce(sleep=sleep)
        return ""
    btn = scr.find("立即更新") or scr.find("更新游戏") or scr.find("更新")
    if btn is None:
        _note(problems, f"鸣潮：启动器画面没读到按钮（截图 {scr.shot}）：{scr.dump(12)}")
        _okww_quiesce(sleep=sleep)
        return ""
    desk.click(*btn.center, focus="title:鸣潮")
    log.info("游戏更新：鸣潮已点「%s」，等它下载安装", btn.text)
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        sleep(poll_s)
        scr = desk.read(focus="title:鸣潮")
        if scr.has("开始游戏"):
            # Installed. Click 「开始游戏」 to bring the game up to the login screen
            # (this is when the shaders get compiled)
            desk.click_text("开始游戏", focus="title:鸣潮")
            sleep(90)
            how = wait_ready(desk, "鸣潮", focus="Client-Win64-Shipping",
                             alive=_alive("Client-Win64-Shipping.exe"), sleep=sleep)
            _okww_quiesce(sleep=sleep)
            if not how:
                _note(problems, "鸣潮：更新后游戏没走到登录界面")
            return "鸣潮 客户端已通过启动器更新" + (f"，已到登录界面（{how}）" if how else "")
    _note(problems, f"鸣潮：{budget_s / 60:.0f} 分钟内没等到「开始游戏」，先把启动器关掉免得和 OK-WW 撞车")
    _okww_quiesce(sleep=sleep)
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


def ak_prewarm(ldconsole: Path, dev: str, desk: Desktop, *, run=None, sleep=time.sleep,
               budget_s: float = 900) -> str:
    """Start Arknights and get it to the login screen. Measured on 09-03: the first
    screen is a loading page carrying 「START」, and it only reaches 「开始唤醒」 after a
    tap at the bottom centre of the screen (about (800,855) at 1600x900). Returns the
    evidence sentence."""
    run = run or _sh
    adb = str(adb_of(ldconsole))
    run([adb, "-s", dev, "shell", f"am start -n {AK_ACTIVITY}"])
    sleep(60)
    m = re.search(r"(\d+)x(\d+)", run([adb, "-s", dev, "shell", "wm size"]) or "")
    W, H = (int(m.group(1)), int(m.group(2))) if m else (1600, 900)
    t0 = time.monotonic()
    while time.monotonic() - t0 < budget_s:
        scr = desk.read(focus="title:明日方舟")
        if scr.has(*READY_WORDS["明日方舟"]):
            log.info("游戏更新：明日方舟到登录界面（读到「开始唤醒」）")
            return "读到「开始唤醒」"
        # 「START」 is set in a decorative font and OCR may not read it (on 09-03 it
        # could not be read, but a blind tap worked). While not at the login screen, tap
        # the bottom centre - at the login screen that spot is empty, so it is harmless.
        run([adb, "-s", dev, "shell", f"input tap {W // 2} {int(H * 0.95)}"])
        log.info("游戏更新：明日方舟还没到登录界面，点了一下底部（START 位置）")
        sleep(20)
    log.warning("游戏更新：明日方舟 %.0f 分钟内没读到「开始唤醒」", budget_s / 60)
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
    """Resumable download to dest. Checks the size against Content-Length when done."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Range": f"bytes={have}-"})
    deadline = time.monotonic() + timeout
    with urllib.request.urlopen(req, timeout=60) as r:
        cr = r.headers.get("Content-Range") or ""
        total = int(cr.rsplit("/", 1)[-1]) if "/" in cr else have + int(r.headers.get("Content-Length") or 0)
        if r.status == 200:
            have = 0                      # server ignored Range, start over
        with open(part, "ab" if have else "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                if time.monotonic() > deadline:
                    log.warning("下载 %s 超过预算，先停在 %d/%d，下次接着下", dest.name, have, total)
                    return False
    if total and have != total:
        log.warning("下载 %s 大小不对：%d != %d", dest.name, have, total)
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
        _note(problems, f"明日方舟：官方版本接口取不到（{exc}）")
        return ""
    if not remote:
        _note(problems, "明日方舟：官方版本接口没给 clientVersion")
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
            _note(problems, "明日方舟：装完拉起后 15 分钟没读到「开始唤醒」")
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


# ─────────────────────────── scheduling ───────────────────────────

def should_run(state_dir: Path | None, now: datetime, *, boot_id: str) -> bool:
    """Runs once per boot; never twice within one boot (a deploy restarting the
    service is not a new boot)."""
    if not state_dir:
        return False
    d = _store(state_dir).get("updates", "gameupdate")
    return not isinstance(d, dict) or d.get("boot") != boot_id


def mark_run(state_dir: Path | None, now: datetime, *, boot_id: str) -> None:
    if state_dir:
        _store(state_dir).set("updates", "gameupdate",
                              {"boot": boot_id, "at": now.isoformat()})


# ─────────────────── register which game needs updating ───────────────────
# The user, 2026-09-02: 「预更新的窗口只有几分钟，更新游戏来不及。检测到有更新之后
# 直接先跳过这个游戏，等所有其他游戏跑完之后，再单独拉这个游戏进行更新，
# 然后再去重跑。」 So: the boot only registers, and the engine does the work once the
# queue has finished (run_deferred).

def pending(state_dir: Path) -> dict[str, str]:
    """{game: why}."""
    d = _store(state_dir).get("updates", "gameupdate_pending")
    return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}


def mark_pending(state_dir: Path, game: str, why: str) -> bool:
    """Register one entry; a game already registered is not registered twice.
    Returns whether this was a new registration."""
    d = pending(state_dir)
    if game in d:
        return False
    d[game] = why
    _store(state_dir).set("updates", "gameupdate_pending", d)
    log.info("游戏更新：已登记 %s 待更新（%s）", game, why)
    return True


def clear_pending(state_dir: Path, game: str) -> None:
    d = pending(state_dir)
    if game in d:
        d.pop(game)
        _store(state_dir).set("updates", "gameupdate_pending", d)


def last_run_ok(state_dir: Path, now: datetime, script: str) -> bool | None:
    """Whether this script's last round today succeeded; None when it has not run today."""
    last = None
    for e in _today(state_dir, now):
        if e.get("script") == script:
            last = bool(e.get("ok"))
    return last


def _today(state_dir: Path, now: datetime) -> list[dict]:
    p = Path(state_dir) / f"ledger-{now:%Y-%m-%d}.jsonl"
    try:
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


_UNREACHABLE_FLAG = {"MaaEnd": "maaend_unreachable", "OK-WW": "okww_unreachable"}


def needs_rerun(state_dir: Path, now: datetime, script: str) -> bool:
    """Only "today's last round failed because an outdated client could not get into
    the game" is worth re-running after an update.

    The incident on the evening of 2026-09-02: four MaaEnd tasks genuinely failed
    because upstream had not adapted to the new version; I dispatched it again on the
    rule "the last round did not succeed, so re-run", and it kicked the user off the
    account while he was playing. An ordinary task failure fails again on a re-run and
    only steals the account for nothing - that kind of failure is not the update's
    business.
    """
    if any(r.get("script") == script for r in skips(state_dir)):
        return True                     # pulled from today's queue: must be re-run
    last = None
    for e in _today(state_dir, now):
        if e.get("script") == script:
            last = e
    if last is None or last.get("ok"):
        return False
    raw = last.get("raw") or {}
    return bool(raw.get(_UNREACHABLE_FLAG.get(script, "")) or raw.get("maintenance"))


def off(state_dir: Path) -> bool:
    """Master switch: when state.json's updates.gameupdate_off is true, none of this runs."""
    return bool(_store(state_dir).get("updates", "gameupdate_off"))


# ─────────── Wuthering Waves: the maintenance day named in the official notice ───────────
_WW_NOTICE_URL = ("https://aki-gm-resources-back.aki-game.com/gamenotice/G152/"
                  "76402e5b20be2c39f095a152090afddc/zh-Hans.json")
_WW_MAINT = re.compile(r"更新维护时间[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日")


def wuwa_update_day(now: datetime, fetch=None) -> str:
    """Returns the evidence sentence when the newest 「版本内容说明」 notice names today
    as the maintenance day; otherwise an empty string.

    The notice goes up a few days ahead and always in the same form:
    「更新维护时间：2026年8月20日04:00 ~ …」 (checked 2026-09-02). One HTTP request; the
    launcher is not opened.
    """
    try:
        data = fetch() if fetch else json.loads(
            urllib.request.urlopen(urllib.request.Request(
                _WW_NOTICE_URL, headers={"User-Agent": _UA}), timeout=20).read())
        items = [(str(n.get("tabTitle") or ""), str(n.get("content") or ""))
                 for n in (data.get("game") or []) if "版本内容说明" in str(n.get("tabTitle") or "")]
        from .banners import newest_version  # noqa: PLC0415
        body = newest_version(items)
        m = _WW_MAINT.search(re.sub(r"<[^>]+>", " ", body))
        if not m:
            return ""
        y, mo, d = (int(x) for x in m.groups())
        if (y, mo, d) == (now.year, now.month, now.day):
            ver = next((t for t, _ in items if body == dict(items).get(t)), "")
            return f"官方公告：今天更新维护（{ver.strip().splitlines()[-1] if ver else '新版本'}）"
    except Exception:  # noqa: BLE001 - it is only a signal
        return ""
    return ""


# ─────────────────────── boot: only the cheap checks ───────────────────────

def boot_check(cfg, *, budget_s: float, now: datetime | None = None,
               hint=None, fetch=None, wuwa_fetch=None, maint_sources=None,
               skipper=None) -> tuple[list[str], list[str]]:
    """What the boot window does: one HTTP read of the Arknights version, one HTTP read
    of the Endfield notice.

    Arknights version differs: install on the spot when the window is long enough
    (>= 10 minutes), otherwise register it.
    Endfield notice says there is a version update today: register it; the launcher is
    never opened once.
    Wuthering Waves: register when the notice names today as the maintenance day (OK-WW
    only clicks the in-game 「即将重启」, never 「更新」 on the launcher - pointed out by
    the user on 2026-09-02).
    """
    now = now or datetime.now(tz=SERVER_TZ)
    notes: list[str] = []
    problems: list[str] = []
    if off(cfg.state_dir):
        log.info("游戏更新：总开关关着（state.json 的 updates.gameupdate_off），不检查")
        return notes, problems
    ld, idx = ldconsole_of(cfg.maa_dir)
    if ld:
        try:
            remote = remote_ak_version(fetch)
            local = recorded_ak_version(cfg.state_dir)
            if remote and local and remote != local:
                # The user, 2026-09-02: 「你能保证 10 分钟之内更新完吗？」 No. Always defer.
                mark_pending(cfg.state_dir, "明日方舟", f"官方版本 {remote}，已装 {local}")
            elif remote and not local:
                # First time: start the emulator to record the installed version (~1 min)
                if n := update_arknights(cfg.state_dir, ld, idx, budget_s=min(budget_s, 300),
                                         problems=problems, fetch=fetch):
                    notes.append(n)
            else:
                log.info("游戏更新：明日方舟已是 %s，无需更新", remote or "?")
        except Exception:
            log.exception("游戏更新：明日方舟开机检查出错")
            problems.append("明日方舟：开机检查出错（见日志）")
    from . import efstatus  # noqa: PLC0415
    n0 = now.replace(tzinfo=None) if now.tzinfo else now
    try:
        h = (hint or efstatus.update_hint)(n0)
    except Exception:  # noqa: BLE001
        h = ""
    if h and last_run_ok(cfg.state_dir, now, "MaaEnd") is not True:
        # Do not register when it already succeeded today; an ordinary task failure is
        # not the update's business either (needs_rerun blocks that a second time)
        mark_pending(cfg.state_dir, "终末地", h)
    w = wuwa_update_day(n0, fetch=None if wuwa_fetch is None else wuwa_fetch)
    if w and last_run_ok(cfg.state_dir, now, "OK-WW") is not True:
        mark_pending(cfg.state_dir, "鸣潮", w)
    # The three official maintenance notices (maintenance.py): for a game under
    # maintenance today, persist the window and register it. Settled by the user on
    # 2026-09-02: maintenance does not count as a failure; after the queue finishes, wait
    # for the servers to come back, update, re-run, and only then power off.
    try:
        from . import maintenance  # noqa: PLC0415
        wins = maintenance.today(now, sources=maint_sources) if maint_sources is not None else maintenance.today(now)
    except Exception:  # noqa: BLE001
        wins = {}
    save_windows(cfg.state_dir, wins)
    for game, (start, end, why) in wins.items():
        script = maintenance.SCRIPT_OF[game]
        if last_run_ok(cfg.state_dir, now, script) is True:
            continue
        mark_pending(cfg.state_dir, game, why)
        # The user, 2026-09-03: 「当天队列里不跑他」. Where today's queue time falls
        # inside the maintenance window (plus 45 minutes after the servers return, for
        # the client update), pull the script out of the queue through the API and add
        # it back after the re-run (restore_skips). Pull and restore were measured to be
        # reversible on the morning shift on 09-03.
        from datetime import timedelta as _td  # noqa: PLC0415
        for q in _queues_today(cfg.automas_dir, now):
            for due in q["dues"]:
                if start - _td(minutes=30) <= due <= end + _td(minutes=45):
                    try:
                        rec = skipper(q["name"], script) if skipper else _skip_default(q["name"], script)
                    except Exception as exc:  # noqa: BLE001
                        problems.append(f"{game}：从队列「{q['name']}」摘掉 {script} 失败（{exc}）")
                        continue
                    if rec:
                        rec["why"] = why
                        _add_skip(cfg.state_dir, rec)
                        log.info("游戏更新：%s 维护（%s），今天从队列「%s」摘掉 %s", game, why, q["name"], script)
                    break
    return notes, problems


def _skip_default(queue: str, script: str):
    from . import commands  # noqa: PLC0415
    return commands.skip_script_in_queue(queue, script)


def _queues_today(automas_dir, now: datetime) -> list[dict]:
    """Today's queue times that have not come yet: [{name, dues:[datetime]}]."""
    from . import plan  # noqa: PLC0415
    out = []
    for q in plan.schedule(automas_dir) if automas_dir else []:
        dues = []
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due >= now:
                dues.append(due)
        out.append({"name": q["name"], "dues": dues})
    return out


def skips(state_dir: Path) -> list[dict]:
    d = _store(state_dir).get("updates", "queue_skips")
    return list(d) if isinstance(d, list) else []


def _add_skip(state_dir: Path, rec: dict) -> None:
    lst = skips(state_dir)
    if not any(r.get("queueId") == rec.get("queueId") and r.get("scriptId") == rec.get("scriptId") for r in lst):
        lst.append(rec)
    _store(state_dir).set("updates", "queue_skips", lst)


def restore_skips(state_dir: Path, restorer=None) -> list[str]:
    """Add back everything pulled today; returns which ones. Every call retries, and
    only the ones that succeed are dropped from the record."""
    from . import commands  # noqa: PLC0415
    restorer = restorer or commands.restore_script_in_queue
    left, done = [], []
    for rec in skips(state_dir):
        try:
            if restorer(rec):
                done.append(f"{rec['script']}→「{rec['queue']}」")
                continue
        except Exception:
            log.exception("加回队列失败：%s", rec)
        left.append(rec)
    _store(state_dir).set("updates", "queue_skips", left)
    return done


def save_windows(state_dir: Path, wins: dict) -> None:
    _store(state_dir).set("updates", "maintenance_windows",
        {g: {"start": w[0].isoformat(), "end": w[1].isoformat(), "why": w[2]} for g, w in wins.items()})


def windows(state_dir: Path) -> dict[str, tuple[datetime, datetime, str]]:
    d = _store(state_dir).get("updates", "maintenance_windows")
    if not isinstance(d, dict):
        return {}
    try:
        return {g: (datetime.fromisoformat(v["start"]), datetime.fromisoformat(v["end"]), str(v.get("why") or ""))
                for g, v in d.items()}
    except (ValueError, KeyError, TypeError):
        return {}


def in_maintenance(state_dir: Path, script: str, at: datetime) -> str:
    """Whether this script hits an official maintenance window at this moment (plus a
    45-minute grace after the servers return, for the client update). Returns the
    evidence sentence, or an empty string when it does not."""
    from . import maintenance  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415
    game = next((g for g, s in maintenance.SCRIPT_OF.items() if s == script), "")
    w = windows(state_dir).get(game)
    if not w:
        return ""
    start, end, why = w
    if start - timedelta(minutes=30) <= at.astimezone(start.tzinfo) <= end + timedelta(minutes=45):
        return why
    return ""


# ─────────────── after the queue finishes: update + re-run ───────────────

def _prepare_client(cfg, desk: Desktop, game: str, problems: list[str], sleep) -> tuple[bool, str]:
    """Update through to the login screen. Returns (ready, notification sentence). When
    it is not ready, the reason is in problems.

    Its own step because this is the only place in the whole flow that forks per game -
    launcher, time budget and the "counts as ready" test all differ between the three.
    With it pulled out, the main flow is a straight line: wait until ready -> wait for
    the servers -> re-run.
    """
    before = len(problems)
    if game == "终末地":
        g, l = endfield_paths(cfg.maaend_dir)
        if not (g and l):
            problems.append("终末地：找不到启动器"); return False, ""
        n = update_endfield(desk, g, l, budget_s=2400, problems=problems, sleep=sleep)
    elif game == "鸣潮":
        l = wuwa_launcher(cfg.okww_dir)
        if not l:
            problems.append("鸣潮：找不到启动器"); return False, ""
        n = update_wuwa(desk, l, budget_s=2400, problems=problems, sleep=sleep)
    else:
        ld, idx = ldconsole_of(cfg.maa_dir)
        if not ld:
            problems.append("明日方舟：找不到雷电 ldconsole"); return False, ""
        n = update_arknights(cfg.state_dir, ld, idx, budget_s=1800, problems=problems, sleep=sleep, desk=desk, maa_dir=cfg.maa_dir)
    return len(problems) == before, n


def _prepare_until_ready(cfg, desk: Desktop, game: str, *, deadline: datetime, clock, sleep,
                         problems: list[str], expect_new: bool,
                         local0: str) -> tuple[bool, str]:
    """Update over and over until the client is ready or the deadline passes. Returns
    (ready, notification sentence).

    Its own step because the retry here hides a rule that is easy to get wrong: on every
    failed round, **every** entry that round wrote into problems has to be taken back as
    a batch, cut at mark (the reason is in the comment at the end of the loop). That is a
    separate matter from the outer "what to do once it is ready", and mixing the two into
    one function makes the rule hard to see.
    """
    ready, note = False, ""
    while True:
        mark = len(problems)
        ready, note = _prepare_client(cfg, desk, game, problems, sleep)
        if game == "明日方舟" and expect_new and ready and not note:
            # prepare saying "no update needed" = the official version number has not
            # changed yet (during maintenance the package is not out), so keep waiting
            ready = False
            if not problems or "版本号还没变" not in problems[-1]:
                problems.append(f"明日方舟：官方版本号还没变（还是 {local0}），维护中包体还没放出来")
        if ready or clock() >= deadline:
            break
        # The update package is most likely not out yet: take this round's problems
        # back as a batch and try again in 10 minutes.
        # Cut at mark rather than dropping only the last entry: one prepare can write two
        # (wrong version after install + login screen never read), and dropping one would
        # leave the other in the final report - reporting a failure even though it
        # succeeded later.
        log.info("游戏更新：%s 还没准备好（%s），10 分钟后再试", game, problems[-1] if problems else "")
        del problems[mark:]
        sleep(600)
    return ready, note


def _rerun_script(cfg, now: datetime, dispatch, script: str,
                  reran: list[str], problems: list[str]) -> None:
    """Once the client is updated, re-run the script whose round failed today.

    Its own step because "should it be re-run, and does the result count as success or
    as a problem" shares no state with the update wait above; it is a self-contained
    little job, and leaving it in the main loop only makes that loop longer.
    """
    if needs_rerun(cfg.state_dir, now, script) and dispatch is not None:
        ok, msg = dispatch(script)
        log.info("游戏更新：补跑 %s → %s", script, msg)
        if ok:
            reran.append(script)
        else:
            problems.append(f"{script}：更新后没能补跑（{msg}）")


def run_deferred(cfg, *, now: datetime | None = None, desk: Desktop | None = None,
                 dispatch=None, sleep=time.sleep, clock=None) -> tuple[list[str], list[str], list[str]]:
    """Work through everything registered. Returns (update notices, problems, scripts
    that were re-run).

    The order the user settled on 2026-09-03: **update the moment the queue finishes**
    (download, install, start the game to get through shader compilation - it only
    counts as ready at the 「点击任意位置继续」 login screen), without waiting for the
    servers to come back; once ready, if the servers are still more than 10 minutes
    away, close the game and re-run separately when the time comes. When the update
    package is not out yet (common during maintenance), retry every 10 minutes, up to
    2 hours past the servers returning.
    """
    now = now or datetime.now(tz=SERVER_TZ)
    clock = clock or (lambda: datetime.now(tz=SERVER_TZ))
    notes: list[str] = []
    problems: list[str] = []
    reran: list[str] = []
    todo = pending(cfg.state_dir)
    if not todo or off(cfg.state_dir):
        return notes, problems, reran
    desk = desk or Desktop(cfg.state_dir)
    wins = windows(cfg.state_dir)
    from datetime import timedelta as _td  # noqa: PLC0415

    from . import maintenance  # noqa: PLC0415
    for game, why in list(todo.items()):
        script = maintenance.SCRIPT_OF.get(game, "")
        start, end = (wins.get(game) or (None, None, ""))[:2]
        deadline = (end + _td(hours=2)) if end else clock() + _td(hours=1)
        expect_new = bool(end)              # maintenance window = a new version today;
                                            # without one it does not count as ready
        local0 = recorded_ak_version(cfg.state_dir) if game == "明日方舟" else ""
        ready, note = _prepare_until_ready(cfg, desk, game, deadline=deadline, clock=clock,
                                           sleep=sleep, problems=problems,
                                           expect_new=expect_new, local0=local0)
        if note:
            notes.append(note + f"（依据：{why}）")
        if not ready:
            problems.append(f"{game}：到 {deadline:%m-%d %H:%M} 仍没准备好客户端，今天不补跑")
            continue
        # Ready. If the servers are still far off, close the game and wait; re-run
        # when the time comes
        if end and clock() < end:
            if end - clock() > _td(minutes=10):
                kill("Endfield.exe", "Client-Win64-Shipping.exe")
            log.info("游戏更新：%s 客户端已就绪，等 %s 开服再补跑", game, end.strftime("%H:%M"))
            while clock() < end:
                sleep(60)
            sleep(120)
        _rerun_script(cfg, now, dispatch, script, reran, problems)
        clear_pending(cfg.state_dir, game)
    if done := restore_skips(cfg.state_dir):
        log.info("游戏更新：已把摘掉的加回队列：%s", "、".join(done))
    return notes, problems, reran


# ───────── MaaEnd tasks switched off temporarily: back on after an upstream update ─────────
# On 2026-09-02 MaaEnd v2.27.0-beta.4 had not adapted to 1.5.3 and the user told us to
# switch four items off; the notes for beta.5 (the night of 09-02) mention 「适配新版本」,
# 「装备制造弹窗」 and 「栖云生态点」. Switch them back on as soon as upstream changes
# version.

def maaend_reenable_if_updated(cfg) -> str:
    # Kept in state.json under updates.maaend_disabled_1_5_3. Before 2026-09-08 this
    # read a standalone file, and the state-consolidation sweep renames the old file to
    # .migrated - the read side and the write side must change together. Add the
    # migration without changing the read and this record can never be read again,
    # leaving those dailies switched off with nobody knowing.
    store = _store(cfg.state_dir)
    rec = store.get("updates", "maaend_disabled_1_5_3")
    if not isinstance(rec, dict) or not rec:
        return ""
    from .preupdate_maaend import _maaend_file_version  # noqa: PLC0415
    ver = _maaend_file_version(cfg.maaend_dir) if cfg.maaend_dir else ""
    since = str(rec.get("since") or "v2.27.0-beta.4")
    if not ver or ver == since:
        return ""
    # The master copy is at AUTO-MAS's data/<script id>/Default/ConfigFile/mxu-MaaEnd.json
    root = Path(cfg.automas_dir) / "data" if cfg.automas_dir else None
    target = next((f for f in (root.glob("*/Default/ConfigFile/mxu-MaaEnd.json") if root else [])), None)
    if not target:
        return ""
    names = set(rec.get("disabled") or [])
    j = json.loads(target.read_text(encoding="utf-8"))
    on = []
    for t in j.get("instances", [{}])[0].get("tasks", []):
        if t.get("taskName") in names and not t.get("enabled"):
            t["enabled"] = True
            on.append(t["taskName"])
    if on:
        atomic_write_text(target, json.dumps(j, ensure_ascii=False, indent=2))
    store.pop("updates", "maaend_disabled_1_5_3")
    zh = {"GiftOperator": "赠送干员礼物", "GearAssembly": "装备制造", "DeliveryJobs": "转交委托", "EnvironmentMonitoring": "环境监测"}
    return (f"MaaEnd 已更新到 {ver}（之前是 {since}），关掉的 {len(on)} 项日常已开回来："
            + "、".join(zh.get(n, n) for n in on)) if on else ""


def maaend_set_enabled(cfg, names: set, enabled: bool) -> list[str]:
    """Set `enabled` on a few items in the master mxu-MaaEnd.json. Returns the ones
    that actually changed."""
    root = Path(cfg.automas_dir) / "data" if cfg.automas_dir else None
    target = next((f for f in (root.glob("*/Default/ConfigFile/mxu-MaaEnd.json") if root else [])), None)
    if not target:
        return []
    j = json.loads(target.read_text(encoding="utf-8"))
    changed = []
    for t in j.get("instances", [{}])[0].get("tasks", []):
        if t.get("taskName") in names and bool(t.get("enabled")) != enabled:
            t["enabled"] = enabled
            changed.append(t["taskName"])
    if changed:
        atomic_write_text(target, json.dumps(j, ensure_ascii=False, indent=2))
    return changed


def maaend_reenable_next_boot(cfg) -> str:
    """Items switched off temporarily for a re-run (e.g. 自动采集, already done that
    day) are switched back on at the next boot."""
    # Kept in state.json under updates.maaend_reenable_next_boot. Before 2026-09-08
    # this read a standalone file, and the state-consolidation sweep renames the old
    # file to .migrated - the read side and the write side must change together. Add the
    # migration without changing the read and this record can never be read again,
    # leaving those dailies switched off with nobody knowing.
    store = _store(cfg.state_dir)
    rec = store.get("updates", "maaend_reenable_next_boot")
    if not isinstance(rec, dict) or not rec:
        return ""
    on = maaend_set_enabled(cfg, set(rec.get("tasks") or []), True)
    store.pop("updates", "maaend_reenable_next_boot")
    zh = {"AutoCollect": "自动采集", "AutoUseSpMedication": "应急理智加强剂"}
    return ("已开回：" + "、".join(zh.get(n, n) for n in on)) if on else ""


# What the broken node looks like (beta.5, read verbatim off the machine 2026-09-03):
#   "all_of": ["YellowConfirmButtonType2", {"param": {...}, "type": "OCR"}]
# The elements of all_of are **nodes**, and the recognition has to be written inside the
# node's own recognition block; hanging type/param straight off the top of the node is
# something the framework does not understand, which makes that test as good as absent
# and leaves the confirm button unclickable.
# Upstream PR #5453 does exactly that - wraps it in recognition, and while there widens
# the roi and adds a wait for the screen to settle.
def spmed_fix_present(maaend_dir) -> bool:
    """Has the confirm node for the sanity booster been fixed yet?

    A new version does **not** mean this bug is fixed: the 2026-09-03 fix (upstream PR
    #5453) had still not been merged that evening, so switching the task back on by
    version number alone just buys another wasted failure. The test now looks straight at
    the shape of that check in the resource file - switch it back on only once it is
    fixed, whatever the version.
    """
    if not maaend_dir:
        return False
    f = Path(maaend_dir) / "resource" / "pipeline" / "nodes.json"
    try:
        node = json.loads(f.read_text(encoding="utf-8")).get("AutoUseSpMedicationQuickUse")
    except (OSError, ValueError):
        return False
    if not isinstance(node, dict):
        return False
    all_of = ((node.get("recognition") or {}).get("param") or {}).get("all_of") or []
    inline = [x for x in all_of if isinstance(x, dict)]
    return bool(inline) and all("recognition" in x for x in inline)


def maaend_reenable_spmed_if_updated(cfg) -> str:
    """The 应急理智加强剂 task broke in beta.5 (09-03); switch it back on once upstream
    has fixed it."""
    # Kept in state.json under updates.maaend_disabled_spmed. Before 2026-09-08 this
    # read a standalone file, and the state-consolidation sweep renames the old file to
    # .migrated - the read side and the write side must change together. Add the
    # migration without changing the read and this record can never be read again,
    # leaving those dailies switched off with nobody knowing.
    store = _store(cfg.state_dir)
    rec = store.get("updates", "maaend_disabled_spmed")
    if not isinstance(rec, dict) or not rec:
        return ""
    from .preupdate_maaend import _maaend_file_version  # noqa: PLC0415
    ver = _maaend_file_version(cfg.maaend_dir) if cfg.maaend_dir else ""
    if not ver or ver == str(rec.get("since") or ""):
        return ""
    if not spmed_fix_present(cfg.maaend_dir):
        log.info("MaaEnd 已是 %s，但加强剂那条判据还是坏的写法，继续关着", ver)
        return ""
    on = maaend_set_enabled(cfg, set(rec.get("tasks") or []), True)
    store.pop("updates", "maaend_disabled_spmed")
    return f"MaaEnd 已是 {ver}，加强剂的判据已修好，任务开回来" if on else ""
