"""大版本更新日，把三个游戏的客户端自己更新掉。

用户 2026-09-02：「大版本鸣潮和终末地都有启动器去更新，明日方舟是通过模拟器
里面去更新安装包然后再手动点进去更新……希望你能帮我实现自动化。」

三家三条路，都在开机窗口（预更新之后、队列之前）跑：

* 终末地：鹰角启动器（进程 Games，窗口「鹰角启动器」）。读屏：按钮是
  「更新游戏」就点，等它变成「开始游戏」；然后拉一次游戏过「资源初始化
  更新完成，请重启游戏」和着色器编译，看到「点击任意位置继续」才算完。
  2026-09-02 手动走过一遍，每一步的字都是当天屏幕上读到的。
* 鸣潮：库洛启动器（Wuthering Waves.exe 是壳）。同样读屏点「更新」，
  等「开始游戏」。OK-WW 自己也会处理更新，这里只是让它别撞上正在下载。
* 明日方舟：不点模拟器界面。官方版本接口给 clientVersion，和上次记下的
  已装版本比，不同就下载 APK（官方直链，2 GB 上下，支持断点续传），
  起雷电、`ldconsole installapp` 装进去，装完读 dumpsys 核对版本，再退出
  模拟器。第一次没有记录时先起模拟器读一次已装版本记下来。

每一步的结论都写日志；没能确认的进 problems，由调用方发「⚠️ 没能确认」。
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


# ─────────────────────────── 通用 ───────────────────────────

def _spawn(exe: Path, cwd: Path | None = None) -> bool:
    from .preupdate import _spawn_interactive  # noqa: PLC0415
    return _spawn_interactive(exe, cwd or exe.parent, require_console=True)


def _note(problems: list[str] | None, msg: str) -> None:
    if problems is not None:
        problems.append(msg)


# ─────────────────────────── 终末地 ───────────────────────────

def endfield_paths(maaend_dir: Path | None) -> tuple[Path | None, Path | None]:
    """(游戏 exe, 启动器 exe)。游戏路径从 MaaEnd 自己的配置读，不猜。"""
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
    # D:\endfield\Hypergryph Launcher\games\Endfield Game\Endfield.exe → 上三级是启动器目录
    launcher = game.parents[2] / "Launcher.exe" if len(game.parents) >= 3 else None
    return game, (launcher if launcher and launcher.exists() else None)


def update_endfield(desk: Desktop, game: Path, launcher: Path, *,
                    budget_s: float = 2400, poll_s: float = 30,
                    problems: list[str] | None = None, sleep=time.sleep) -> str:
    """返回给人看的一句话；没更新返回空串。"""
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
    # 装完了。拉一次游戏把「资源初始化」和着色器编译做掉，否则早班第一趟必卡。
    desk.click_text("开始游戏", focus="Games")
    sleep(90)
    deadline = time.monotonic() + 900
    restarted = False
    while time.monotonic() < deadline:
        scr = desk.read(focus="Endfield")
        if scr.has("点击任意位置继续"):
            log.info("游戏更新：终末地已到标题画面，客户端可用")
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


# ─────────────────────────── 鸣潮 ───────────────────────────

def wuwa_launcher(okww_dir: Path | None) -> Path | None:
    """启动器（壳）路径：从 OK-WW 自己的配置里找以 Wuthering Waves.exe 结尾的值。"""
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
    from .preupdate import _okww_quiesce  # noqa: PLC0415 - 关壳和游戏进程的现成办法
    if not _spawn(launcher):
        _note(problems, "鸣潮：启动器没能在桌面会话里起来")
        return ""
    sleep(30)
    scr = desk.read(focus="title:鸣潮")
    if scr.has("开始游戏"):
        log.info("游戏更新：鸣潮启动器已是「开始游戏」，无需更新")
        _okww_quiesce()
        return ""
    btn = scr.find("立即更新") or scr.find("更新游戏") or scr.find("更新")
    if btn is None:
        _note(problems, f"鸣潮：启动器画面没读到按钮（截图 {scr.shot}）：{scr.dump(12)}")
        _okww_quiesce()
        return ""
    desk.click(*btn.center, focus="title:鸣潮")
    log.info("游戏更新：鸣潮已点「%s」，等它下载安装", btn.text)
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        sleep(poll_s)
        scr = desk.read(focus="title:鸣潮")
        if scr.has("开始游戏"):
            _okww_quiesce()
            return "鸣潮 客户端已通过启动器更新"
    _note(problems, f"鸣潮：{budget_s / 60:.0f} 分钟内没等到「开始游戏」，先把启动器关掉免得和 OK-WW 撞车")
    _okww_quiesce()
    return ""


# ─────────────────────────── 明日方舟 ───────────────────────────

def ldconsole_of(maa_dir: Path | None) -> tuple[Path | None, int]:
    """(ldconsole.exe, 实例序号)。从 MAA 自己的配置读 AdbPath / 雷电快捷方式。"""
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


def remote_ak_version(fetch=None) -> str:
    data = fetch() if fetch else json.loads(
        urllib.request.urlopen(urllib.request.Request(  # noqa: S310
            AK_VERSION_URL, headers={"User-Agent": _UA}), timeout=20).read())
    return str((data or {}).get("clientVersion") or "")


def installed_ak_version(ldconsole: Path, idx: int, run=None) -> str:
    """dumpsys 里的 versionName。模拟器没起来就返回空串。"""
    run = run or (lambda args: subprocess.run(args, capture_output=True, text=True,
                                              errors="replace", timeout=60).stdout)
    out = run([str(ldconsole), "adb", "--index", str(idx), "--command",
               f"shell dumpsys package {AK_PACKAGE}"])
    hits = re.findall(r"versionName=(\S+)", out or "")
    return hits[0] if hits else ""


def _record_path(state_dir: Path) -> Path:
    return Path(state_dir) / "arknights-client.json"


def recorded_ak_version(state_dir: Path) -> str:
    try:
        return str(json.loads(_record_path(state_dir).read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def record_ak_version(state_dir: Path, version: str) -> None:
    atomic_write_text(_record_path(state_dir), json.dumps(
        {"version": version, "at": datetime.now(tz=SERVER_TZ).isoformat()}, ensure_ascii=False))


def download(url: str, dest: Path, *, timeout: float = 1500) -> bool:
    """断点续传下到 dest。完成后按 Content-Length 核对大小。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Range": f"bytes={have}-"})
    deadline = time.monotonic() + timeout
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        cr = r.headers.get("Content-Range") or ""
        total = int(cr.rsplit("/", 1)[-1]) if "/" in cr else have + int(r.headers.get("Content-Length") or 0)
        if r.status == 200:
            have = 0                      # 服务器不认 Range，从头来
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
                     fetch=None, run=None, sleep=time.sleep, downloader=download) -> str:
    """返回「明日方舟 已更新：旧 → 新」或空串。"""
    run = run or (lambda args: subprocess.run(args, capture_output=True, text=True,
                                              errors="replace", timeout=120).stdout)
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
        run([str(ldconsole), "launch", "--index", str(idx)])
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            sleep(10)
            if installed_ak_version(ldconsole, idx, run):
                return True
        return False

    if not local:
        # 第一次：起模拟器读一次已装版本记下来，之后才有得比
        if not boot():
            _note(problems, "明日方舟：起雷电读已装版本没成功（4 分钟内 adb 没通）")
            return ""
        local = installed_ak_version(ldconsole, idx, run)
        run([str(ldconsole), "quit", "--index", str(idx)])
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
    run([str(ldconsole), "installapp", "--index", str(idx), "--filename", str(apk)])
    deadline = time.monotonic() + 600
    now_ver = ""
    while time.monotonic() < deadline:
        sleep(15)
        now_ver = installed_ak_version(ldconsole, idx, run)
        if now_ver == remote:
            break
    run([str(ldconsole), "quit", "--index", str(idx)])
    if now_ver != remote:
        _note(problems, f"明日方舟：装完读到的版本是 {now_ver or '空'}，不是 {remote}")
        return ""
    record_ak_version(state_dir, remote)
    try:
        apk.unlink()
    except OSError:
        pass
    return f"明日方舟 已更新：{local} → {remote}（APK 已装进雷电）"


# ─────────────────────────── 调度 ───────────────────────────

def _stamp(state_dir: Path) -> Path:
    return Path(state_dir) / "gameupdate.json"


def should_run(state_dir: Path | None, now: datetime, *, boot_id: str) -> bool:
    """每次开机跑一遍；同一次开机不重跑（部署重启服务不算新开机）。"""
    if not state_dir:
        return False
    try:
        d = json.loads(_stamp(state_dir).read_text(encoding="utf-8"))
        return d.get("boot") != boot_id
    except (OSError, ValueError):
        return True


def mark_run(state_dir: Path | None, now: datetime, *, boot_id: str) -> None:
    if state_dir:
        atomic_write_text(_stamp(state_dir), json.dumps(
            {"boot": boot_id, "at": now.isoformat()}, ensure_ascii=False))


def today_unreachable(state_dir: Path, now: datetime) -> bool:
    """今天有没有「MaaEnd 根本没进游戏」的记录（collector.maaend_unreachable）。"""
    p = Path(state_dir) / f"ledger-{now:%Y-%m-%d}.jsonl"
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e.get("script") == "MaaEnd" and (e.get("raw") or {}).get("maaend_unreachable"):
                return True
    except (OSError, ValueError):
        pass
    return False


def endfield_signal(state_dir: Path, now: datetime, hint=None) -> str:
    """要不要动终末地启动器——有信号才动，没有信号一次都不开。

    用户 2026-09-02：「一定不要做到每天都要去检测，大版本更新是很少的。」
    信号只有两种：官方公告说今天版本更新；或今天 MaaEnd 已经因为客户端
    过时进不了游戏。两样都没有就什么都不做。
    """
    from . import efstatus  # noqa: PLC0415
    h = (hint or efstatus.update_hint)(now)
    if h:
        return h
    if today_unreachable(state_dir, now):
        return "今天 MaaEnd 进不了游戏（客户端待更新）"
    return ""


def run_all(cfg, *, budget_s: float, desk: Desktop | None = None,
            now: datetime | None = None) -> tuple[list[str], list[str]]:
    """跑三家。返回 (给人看的更新通知, 没能确认的问题)。

    每次开机只做两件便宜事：读一次方舟官方版本号（一个 HTTP 请求）、
    读一次终末地官方公告。启动器和模拟器只在有信号时才动：
    · 方舟：官方版本号 ≠ 记录的已装版本 → 下载装包
    · 终末地：公告说今天版本更新 / 今天 MaaEnd 进不了游戏 → 启动器流程
    · 鸣潮：不主动。OK-WW 自己会经启动器更新（今早实录：更新→重启→重跑成功），
      日报里已把这种插曲摘出来不算失败。
    """
    now = now or datetime.now(tz=SERVER_TZ)
    notes: list[str] = []
    problems: list[str] = []
    long_budget = budget_s > 1200      # 早班窗口只有十几分钟，晚上才够下大包

    ld, idx = ldconsole_of(cfg.maa_dir)
    if ld:
        try:
            if n := update_arknights(cfg.state_dir, ld, idx, budget_s=min(budget_s, 900),
                                     problems=problems):
                notes.append(n)
        except Exception:  # noqa: BLE001
            log.exception("游戏更新：明日方舟这一段出错")
            problems.append("明日方舟：更新流程出错（见日志）")
    else:
        log.info("游戏更新：找不到雷电 ldconsole，跳过明日方舟")

    game, launcher = endfield_paths(cfg.maaend_dir)
    if game and launcher:
        why = endfield_signal(cfg.state_dir, now.replace(tzinfo=None) if now.tzinfo else now)
        if why:
            log.info("游戏更新：终末地有信号（%s），去启动器看", why)
            try:
                if n := update_endfield(desk or Desktop(cfg.state_dir), game, launcher,
                                        budget_s=2400 if long_budget else max(120, budget_s - 120),
                                        problems=problems):
                    notes.append(n + f"（依据：{why}）")
            except Exception:  # noqa: BLE001
                log.exception("游戏更新：终末地这一段出错")
                problems.append("终末地：更新流程出错（见日志）")
        else:
            log.info("游戏更新：终末地没有更新信号，不开启动器")
    else:
        log.info("游戏更新：找不到终末地启动器，跳过")
    return notes, problems
