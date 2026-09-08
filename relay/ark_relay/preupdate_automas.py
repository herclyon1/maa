"""preupdate_automas：从 preupdate.py 拆出（2026-09-08，只搬不改）。"""
from __future__ import annotations

import json
import time

from .config import mas_base
from pathlib import Path


from .preupdate_common import _note, log
from .preupdate_maaend import _span



# AUTO-MAS is the odd one of the three. It does not need to be launched to be
# asked - it is already running, and its FastAPI backend answers on localhost.
#
# It also cannot land an update mid-queue: its Run/IfAutoUpdateAfterQueue
# defaults to false and is not set on this machine, so the 4-hourly checker
# (frontend.log: "版本更新检查服务已启动（每4小时检查一次）") only ever reports.
# Unattended, it reports to a window nobody is looking at and the version never
# moves - which is the whole reason this exists.
#
# Applying it here is safe against the one interference that could plausibly
# break it: AUTO-MAS installs by launching AUTO-MAS-Setup.exe
# (app/services/update.py), which means the process exits - and service.py's
# _revive_automas would normally relaunch it. It does not, because
# INSTALLER_HINTS already vetoes revival while "auto-mas-setup" is in the
# task list. That gate was built for the manual installer; it covers this too.
# 模块级读 os.environ 会在 .env 加载之前求值（见 config.py 那段注释），
# 所以地址只能在用的时候现算——config.mas_base() 是唯一出处。
_MAS_PORT = None   # 旧名字，别处 import 过；真正的地址走 config.mas_base()
_MAS_HTTP_TIMEOUT = 20
# Boot is 08:40 and the queue checks in at 09:00. Downloading is harmless at any
# point - the package just sits there - but starting an install we cannot finish
# before the queue is not. If the download runs past this, leave the package for
# the next boot rather than opening a setup window in front of the run.
MAS_BUDGET_SECONDS = 600
# How long to wait for AUTO-MAS's backend to start listening.
MAS_WAIT_SECONDS = 180


def _automas_version(automas_dir: Path) -> str:
    """AUTO-MAS keeps its version in res/version.json - the same string its
    update check expects back."""
    try:
        data = json.loads(
            (Path(automas_dir) / "res" / "version.json").read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except (OSError, ValueError, TypeError):
        return ""


def _mas_post(path: str, body: dict | None = None) -> dict:
    import urllib.request  # noqa: PLC0415 - only this path needs it
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        mas_base() + path, data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_MAS_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _wait_for_package(automas_dir: Path, deadline: float) -> Path | None:
    """Wait for UpdatePack_*.zip to appear and stop growing.

    install_update() refuses with "未检测到更新包, 请先下载更新" if the package is
    not there, so calling install the moment download returns would simply fail.
    """
    stable_at = None
    last_size = -1
    while time.monotonic() < deadline:
        time.sleep(3)
        packs = sorted(Path(automas_dir).glob("UpdatePack_*.zip"),
                       key=lambda f: f.stat().st_mtime)
        if not packs:
            continue
        pack = packs[-1]
        try:
            size = pack.stat().st_size
        except OSError:
            continue
        if size == last_size and size > 0:
            if stable_at is None:
                stable_at = time.monotonic()
            elif time.monotonic() - stable_at >= 9:
                return pack
        else:
            stable_at = None
            last_size = size
    return None


def run_automas(automas_dir: Path | None,
                budget_s: float = MAS_BUDGET_SECONDS,
                problems: list[str] | None = None) -> str:
    """Check, download and apply an AUTO-MAS update now. Returns a note or ""."""
    if not automas_dir:
        return ""
    root = Path(automas_dir)
    version = _automas_version(root)
    if not version:
        log.info("预更新：读不到 AUTO-MAS 版本号，跳过")
        _note(problems, "AUTO-MAS 预更新：读不到版本号，**没有检查更新**")
        return ""
    # AUTO-MAS starts at logon, and its backend is not listening the instant the
    # relay wakes: on 2026-08-24 the relay asked at 08:45:33 and AUTO-MAS's own
    # log shows its backend only came up at 08:46:09. Asking once at boot is
    # therefore guaranteed to miss it. Wait for the port instead - the boot
    # window runs to 09:00, so a couple of minutes costs nothing.
    answer = None
    wait_until = time.monotonic() + MAS_WAIT_SECONDS
    while True:
        try:
            # if_force 是必须的，不是保险起见。AUTO-MAS 的检查结果缓存四小时
            # （`app/services/update.py:178-184`），而 MirrorChyan 的下载地址是
            # **一次性令牌**，随检查响应带回来、存进 `mirror_chyan_download_url`。
            # 走缓存 = 拿一个早就过期的令牌去下载，三次重试全 404，更新包一个字节
            # 都不落地，然后我们在这儿干等 600 秒超时。
            # 2026-08-29 实测：不强制 → 404；强制 → 换到新令牌，状态码 200。
            # 这就是 AUTO-MAS 从 08-27 起反复「开始下载」却始终装不上的原因。
            answer = _mas_post("/api/update/check",
                               {"current_version": version, "if_force": True})
            break
        except Exception:  # noqa: BLE001 - not up yet, or genuinely unreachable
            if time.monotonic() >= wait_until:
                log.warning("预更新：等了 %.0f 秒仍问不到 AUTO-MAS 更新状态，跳过",
                            MAS_WAIT_SECONDS)
                _note(problems,
                      f"AUTO-MAS 预更新：等了 {MAS_WAIT_SECONDS:.0f} 秒仍问不到"
                      "更新状态，**没有检查更新**")
                return ""
            time.sleep(5)
    if not answer.get("if_need_update"):
        log.info("预更新：AUTO-MAS 已是 %s（无需更新）", version)
        return ""

    latest = answer.get("latest_version") or "新版本"
    log.info("预更新：AUTO-MAS 有更新 %s → %s，开始下载", version, latest)
    deadline = time.monotonic() + budget_s
    try:
        _mas_post("/api/update/download")
    except Exception:  # noqa: BLE001
        log.warning("预更新：AUTO-MAS 下载没能启动，本轮照旧", exc_info=True)
        _note(problems, f"AUTO-MAS 预更新：查到有 {latest}，但下载没能启动")
        return ""

    pack = _wait_for_package(root, deadline)
    if pack is None:
        # The package keeps whatever it downloaded; next boot picks it up.
        log.warning("预更新：AUTO-MAS 更新包 %.0f 秒内没下完，留到下次开机再装", budget_s)
        _note(problems,
              f"AUTO-MAS 预更新：{latest} 的更新包 {budget_s:.0f} 秒内没下完，"
              "留到下次开机再装")
        return ""

    log.info("预更新：更新包就绪（%s），开始安装", pack.name)
    try:
        _mas_post("/api/update/install")
    except Exception:  # noqa: BLE001
        log.warning("预更新：AUTO-MAS 安装没能启动，本轮照旧", exc_info=True)
        return ""
    return f"AUTO-MAS 有更新：{_span(version, latest)}（安装中，装完自动重启）"
