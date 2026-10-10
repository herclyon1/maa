"""AUTO-MAS pre-update: ask its backend for an update, download it, install it,
and wait for the restarted backend to report the new version.
"""
from __future__ import annotations

import json
import time

from ark_relay.core.config import mas_base
from pathlib import Path


from ark_relay.features.preupdate.preupdate_common import _note, _span, log


# AUTO-MAS is already running and its FastAPI backend answers on localhost, so it
# is asked over HTTP instead of being launched.
# Installing runs AUTO-MAS-Setup.exe and the AUTO-MAS process exits; service.py
# does not relaunch AUTO-MAS while "auto-mas-setup" is in the task list
# (service.INSTALLER_HINTS).
# The backend address comes from config.mas_base() at call time.
_MAS_HTTP_TIMEOUT = 20
# Seconds for the download. A package not complete by then is left for the next
# boot instead of starting an install that may not finish before the queue.
MAS_BUDGET_SECONDS = 600
# How long to wait for AUTO-MAS's backend to start listening.
MAS_WAIT_SECONDS = 180
# Seconds to wait after install for the restarted backend to report the new
# version (measured: 16 s).
MAS_INSTALL_WAIT_SECONDS = 150


def _automas_version(automas_dir: Path) -> str:
    """The version in AUTO-MAS's res/version.json; "" when unreadable."""
    try:
        data = json.loads(
            (Path(automas_dir) / "res" / "version.json").read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except (OSError, ValueError, TypeError):
        return ""


def _live_version() -> str:
    """The version the running backend reports (GET /api/core/health); '' when
    it cannot be asked.

    Electron builds no longer rewrite res/version.json, so the backend's answer
    takes precedence over the file.
    """
    import urllib.request  # noqa: PLC0415
    try:
        with urllib.request.urlopen(mas_base() + "/api/core/health",
                                    timeout=_MAS_HTTP_TIMEOUT) as resp:
            return str(json.loads(resp.read().decode("utf-8", "replace")).get("version") or "")
    except Exception:  # noqa: BLE001 - not up yet; the caller keeps waiting
        return ""


def _wait_for_version(want: str, deadline: float) -> str:
    """Poll the backend until it reports `want` or the deadline passes; returns what it last said."""
    got = ""
    while time.monotonic() < deadline:
        got = _live_version()
        if got == want:
            return got
        time.sleep(5)
    return got


def _mas_post(path: str, body: dict | None = None) -> dict:
    import urllib.request  # noqa: PLC0415 - only this path needs it
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        mas_base() + path, data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_MAS_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _mas_error(answer) -> str | None:
    """None when an AUTO-MAS answer says success; otherwise what it said instead.

    AUTO-MAS reports failure inside an HTTP 200 body: the routes in
    app/api/update.py return code=500 / status="error" (the update check also
    fills in if_need_update=False). Missing code/status take AUTO-MAS's OutBase
    defaults (200 / "success"); a body that is not a dict is a failure.
    """
    if not isinstance(answer, dict):
        return f"回答不是 JSON 对象：{answer!r}"[:200]
    code, status = answer.get("code", 200), answer.get("status", "success")
    if code == 200 and status == "success":
        return None
    return f"code={code} status={status} {answer.get('message') or ''}".strip()[:200]


def _wait_for_package(automas_dir: Path, deadline: float) -> Path | None:
    """Wait for UpdatePack_*.zip to appear and keep the same size for 9 s.

    install_update() refuses when the package is not there yet.
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
    # The backend may not be listening yet at boot: retry for MAS_WAIT_SECONDS.
    answer = None
    wait_until = time.monotonic() + MAS_WAIT_SECONDS
    while True:
        try:
            # if_force bypasses AUTO-MAS's 4-hour cache of the check result. The
            # MirrorChyan download URL in that result is single-use, so a cached
            # one returns 404 on download.
            live = _live_version()
            if live and live != version:
                log.info("预更新：AUTO-MAS 后端自报 %s（res/version.json 还写着 %s，新版不再改那个文件）",
                         live, version)
                version = live
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
    failed = _mas_error(answer)
    if failed is None and not isinstance(answer.get("if_need_update"), bool):
        failed = "回答里没有 if_need_update"
    if failed is not None:
        log.warning("预更新：AUTO-MAS 查更新没有结论（%s），本轮没有检查更新", failed)
        _note(problems, f"AUTO-MAS 预更新：查更新没有结论（{failed}），**没有检查更新**"
                        "（不是「无需更新」）")
        return ""
    if not answer["if_need_update"]:
        log.info("预更新：AUTO-MAS 已是 %s（无需更新）", version)
        return ""

    latest = answer.get("latest_version") or "新版本"
    log.info("预更新：AUTO-MAS 有更新 %s → %s，开始下载", version, latest)
    deadline = time.monotonic() + budget_s
    try:
        failed = _mas_error(_mas_post("/api/update/download"))
    except Exception as e:  # noqa: BLE001
        failed = f"{type(e).__name__}: {e}"
        log.warning("预更新：AUTO-MAS 下载没能启动，本轮照旧", exc_info=True)
    if failed is not None:
        log.warning("预更新：AUTO-MAS 下载没能启动（%s）", failed)
        _note(problems, f"AUTO-MAS 预更新：查到有 {latest}，但下载没能启动（{failed}）")
        return ""

    pack = _wait_for_package(root, deadline)
    if pack is None:
        # The partial package stays; the next boot continues from it.
        log.warning("预更新：AUTO-MAS 更新包 %.0f 秒内没下完，留到下次开机再装", budget_s)
        _note(problems,
              f"AUTO-MAS 预更新：{latest} 的更新包 {budget_s:.0f} 秒内没下完，"
              "留到下次开机再装")
        return ""

    log.info("预更新：更新包就绪（%s），开始安装", pack.name)
    try:
        failed = _mas_error(_mas_post("/api/update/install"))
    except Exception as e:  # noqa: BLE001
        failed = f"{type(e).__name__}: {e}"
        log.warning("预更新：AUTO-MAS 安装没能启动，本轮照旧", exc_info=True)
    if failed is not None:
        log.warning("预更新：AUTO-MAS 安装没能启动（%s）", failed)
        _note(problems, f"AUTO-MAS 预更新：{latest} 的更新包已下好，但安装没能启动"
                        f"（{failed}），留到下次开机再装")
        return ""
    # The backend restarts itself after install; wait for it to report the new version.
    got = _wait_for_version(latest, time.monotonic() + MAS_INSTALL_WAIT_SECONDS)
    if got == latest:
        log.info("预更新：AUTO-MAS 已更新到 %s（后端重启后自报）", latest)
        return f"AUTO-MAS 已更新：{_span(version, latest)}"
    log.warning("预更新：AUTO-MAS 装完 %.0f 秒内后端没有自报 %s（最后一次说的是 %s），留到下次开机再看",
                MAS_INSTALL_WAIT_SECONDS, latest, got or "问不到")
    _note(problems, f"AUTO-MAS 预更新：{latest} 的安装已启动，但后端没有自报新版本"
                    f"（最后说的是 {got or '问不到'}），留到下次开机再看")
    return f"AUTO-MAS 有更新：{_span(version, latest)}（安装已启动，还没确认装成）"
