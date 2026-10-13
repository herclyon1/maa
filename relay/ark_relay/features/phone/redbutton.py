"""The red button (estop): stop every script and game, and record when it was pressed.

Split out of commands.py; commands.py re-exports the public names (estop,
estop_windows, estop_label, ESTOP_WINDOWS_FILE,
ESTOP_LAST), so `commands.estop` and friends keep working. Tests that fake the
stop steps patch this module (`redbutton._estop_alive`, `redbutton._mas`, ...),
because estop() reads them from here. Logs go to the same "ark.commands" logger
as before the split.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ, atomic_write_text
from ark_relay.features.phone.mas_client import _mas

log = logging.getLogger("ark.commands")


# What the red button has to leave dead. MaaEnd has no process of its own, so
# Endfield.exe stands in for it; Games.exe is the Endfield launcher, which is what
# runs on a client-update day. 鸣潮 shows up under three names and none of them is
# ok-ww.exe, so checking ok-ww.exe alone would miss a running game.
# exe -> what to call it when telling the operator. The push has to be in Chinese
# and a process name is not something he should have to decode at a glance.
_ESTOP_NAMES = {
    "MAA.exe": "明日方舟的脚本",
    "MaaEnd.exe": "终末地的脚本",
    "dnplayer.exe": "雷电模拟器",
    "Endfield.exe": "终末地",
    "Games.exe": "终末地启动器",
    "ok-ww.exe": "鸣潮的脚本",
    "Wuthering Waves.exe": "鸣潮",
    "Client-Win64-Shipping.exe": "鸣潮",
    "KRSDKExternal.exe": "鸣潮的登录组件",
}
_ESTOP_EXES = tuple(_ESTOP_NAMES)
# OK-WW itself runs as pythonw.exe with its path on the command line, which a
# name-only tasklist check cannot see (config.py, "process names"); _estop_alive
# reports it under this name, told as 鸣潮的脚本.
_OKWW_PYTHON = "OK-WW (python)"
_ESTOP_LABELS = {**_ESTOP_NAMES, _OKWW_PYTHON: "鸣潮的脚本"}


def _okww_python_alive() -> bool:
    """Whether OK-WW's python may still be up (okww_overlay.okww_running). None,
    the process list unread, counts as alive: not knowing must never read as
    "all clear" (audit 11 #3, 2026-10-13)."""
    from ark_relay.features.okww_patch.okww_overlay import okww_running  # noqa: PLC0415
    try:
        return okww_running() is not False
    except Exception:
        log.info("红按钮：查不了 OK-WW 的 python 还在不在，按还活着算", exc_info=True)
        return True


def _estop_alive() -> list[str]:
    """Which of those are still alive, and OK-WW's python (_OKWW_PYTHON). Empty
    means nothing is left.

    On a machine where the process list cannot be read, every name is reported as
    still alive: not knowing must never read as "all clear".
    """
    import subprocess  # noqa: PLC0415
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=20).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ["读不到正在运行的程序列表"]
    low = out.lower()
    alive = [e for e in _ESTOP_EXES if e.lower() in low]
    if _okww_python_alive():
        alive.append(_OKWW_PYTHON)
    return alive


def _estop_live_tasks() -> "list[tuple[str, str]] | None":
    """AUTO-MAS's unfinished dispatch tasks: [(taskId, label)]. None when it cannot be asked.

    The taskId here is the dispatch id, the only id /api/dispatch/stop acts on
    (scripts/windows/dispatch_guard.py live_tasks, 2026-09-14). runtime-snapshot
    is a GET, unlike every other AUTO-MAS endpoint, so this does not go through
    _mas(). "Unfinished" is engine._task_unfinished, the same criterion the
    relay uses everywhere else. The label is the task_info names joined with
    「、」, or the mode when there are none.
    """
    from ark_relay.core.config import mas_base  # noqa: PLC0415 - avoids an import cycle
    from ark_relay.core.engine import _RUNTIME_PATH, _task_unfinished  # noqa: PLC0415
    try:
        with urllib.request.urlopen(mas_base() + _RUNTIME_PATH, timeout=10) as r:
            snap = json.loads(r.read().decode("utf-8"))
        tasks = list((snap or {}).get("tasks") or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("红按钮：读不到 AUTO-MAS 的 runtime-snapshot（%s）", exc)
        return None
    live: list[tuple[str, str]] = []
    for t in tasks:
        if not _task_unfinished(t):
            continue
        names = [str(i.get("name") or "") for i in (t.get("task_info") or []) if i.get("name")]
        live.append((str(t.get("taskId") or ""), "、".join(names) or str(t.get("mode") or "?")))
    log.info("红按钮：runtime-snapshot 里 %d 个任务，未结束 %d 个 %s",
             len(tasks), len(live), [(tid[:8], label) for tid, label in live])
    return live


def _estop_stop_by_config_ids() -> None:
    """Post every script and queue id to /api/dispatch/stop.

    AUTO-MAS answers 操作成功 to these and stops nothing (dispatch_guard.py,
    2026-09-14). Used only as the fallback when runtime-snapshot cannot be read:
    harmless, and it costs nothing to try.
    """
    try:
        ids = [sid for sid in _mas("/api/scripts/get")["data"]]
        ids += [qid for qid in _mas("/api/queue/get")["data"]]
        for tid in ids:
            try:
                _mas("/api/dispatch/stop", {"taskId": tid})
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        log.warning("红按钮：AUTO-MAS 接口停不了（%s），直接杀进程", exc)


def _estop_stop_via_mas() -> list[str]:
    """Stop every unfinished AUTO-MAS task by its dispatch taskId. Returns the labels stopped.

    Only the dispatch taskId stops a task; script and queue ids are accepted and
    ignored (_estop_stop_by_config_ids).
    """
    live = _estop_live_tasks()
    if live is None:
        log.warning("红按钮：读不到在跑的任务，退回按脚本和队列编号发停止（这条停不到正在跑的任务）")
        _estop_stop_by_config_ids()
        return []
    stopped: list[str] = []
    for tid, label in live:
        if not tid:
            log.warning("红按钮：任务「%s」没有 taskId，停不了，只能靠杀", label)
            continue
        try:
            r = _mas("/api/dispatch/stop", {"taskId": tid})
            # AUTO-MAS answers a stop it could not do with code 500 and the reason
            # (app/api/dispatch.py stop_task -> OutBase(code=500, status="error")),
            # not an HTTP error: only code 200 is a stop (audit 11 #6).
            if not isinstance(r, dict) or r.get("code") != 200:
                log.warning("红按钮：停「%s」(%s) AUTO-MAS 没停：%s", label, tid[:8],
                            r.get("message", r) if isinstance(r, dict) else r)
                continue
            log.info("红按钮：停「%s」(%s)：%s", label, tid[:8], r.get("message", r))
            stopped.append(label)
        except Exception as exc:  # noqa: BLE001
            log.warning("红按钮：停「%s」(%s) 失败：%s", label, tid[:8], exc)
    return stopped


def _estop_kill() -> None:
    import subprocess  # noqa: PLC0415
    from ark_relay.features.preupdate.preupdate_okww import _okww_quiesce  # noqa: PLC0415
    for exe in _ESTOP_EXES:
        subprocess.run(["taskkill", "/IM", exe, "/T", "/F"], capture_output=True)
    _okww_quiesce()


# When the red button was pressed. handle._handle reads it back so that the run
# the button cut short is booked as a manual stop, not as the success that heals
# the failures before it (AUTO-MAS can record a stopped run as Success!).
ESTOP_WINDOWS_FILE = "estop-windows.json"
_ESTOP_WINDOWS_KEEP = 20


def _estop_windows_path(state_dir) -> Path:
    if state_dir:
        return Path(state_dir) / ESTOP_WINDOWS_FILE
    from ark_relay.core.config import _env_path  # noqa: PLC0415 - the same default as Config.state_dir
    return Path(_env_path("ARK_STATE_DIR", "./ark-state")) / ESTOP_WINDOWS_FILE


def _estop_windows_raw(path: Path) -> list[dict]:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except ValueError:
        # A torn file must not stop the next press from being recorded.
        log.warning("红按钮时间记录 %s 读不懂，从空的重新记", path)
        return []
    return [w for w in got if isinstance(w, dict)] if isinstance(got, list) else []


def _estop_window_mark(state_dir, start: str, end: "str | None" = None) -> None:
    """Record the start of a press, or fill in its end. Never raises: the stop comes first."""
    try:
        path = _estop_windows_path(state_dir)
        rows = _estop_windows_raw(path)
        if end is None:
            rows.append({"start": start})
        else:
            for w in reversed(rows):
                if w.get("start") == start:
                    w["end"] = end
                    break
            else:
                rows.append({"start": start, "end": end})
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(rows[-_ESTOP_WINDOWS_KEEP:], ensure_ascii=False, indent=1))
        log.info("红按钮：%s %s → %s", "结束" if end else "开始", end or start, path)
    except Exception:
        log.exception("红按钮：按下的时间没记下（不影响停）")


def estop_windows(state_dir=None) -> "list[tuple[datetime, datetime]]":
    """Every recorded press as (start, end), SERVER_TZ-aware.

    A press with no end (the relay died mid-stop, or the stop is still running)
    is left out: when it ended is unknown, so which runs it cut short is too.
    Such a run is 「原因不明」 - not booked as a manual stop, so its own ok stands."""
    out = []
    try:
        rows = _estop_windows_raw(_estop_windows_path(state_dir))
    except Exception:
        log.exception("红按钮时间记录读不了")
        return []
    for w in rows:
        if not w.get("end"):
            continue
        try:
            start = datetime.fromisoformat(str(w["start"]))
            end = datetime.fromisoformat(str(w["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=SERVER_TZ)
        if end.tzinfo is None:
            end = end.replace(tzinfo=SERVER_TZ)
        out.append((start, end))
    return out


def estop_label(windows, started: datetime, finished: datetime) -> str:
    """「HH:MM 停一切」 for the first press that cut [started, finished] short, else ''.

    Cut short = the run was going while the press was (started before it ended)
    and it finished inside the press. A run that went on past the end of the
    press was not stopped by it.

    One rule for both readers: handle._estop_overlap at record time and
    handle.backfill_manual_stops at boot. Naive times are server time.
    """
    if started.tzinfo is None:
        started = started.replace(tzinfo=SERVER_TZ)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=SERVER_TZ)
    for w_start, w_end in windows:
        if started < w_end and w_start <= finished <= w_end:
            return w_start.astimezone(SERVER_TZ).strftime("%H:%M") + " 停一切"
    return ""


# What the last red-button press saw in its final check, before it answered:
# {"alive": [exe names], "live": [(taskId, label)] or None (AUTO-MAS could not be
# asked), "rounds": 1 or 2, "at": ISO time}. The machine check #16 compares it
# with the answer (machinechecks/phone_banners.py); {} before any press.
ESTOP_LAST: dict = {}


def estop(sleep=None, state_dir=None) -> tuple[bool, str]:
    """The red button: stop every script and game. The red one on the phone page.

    The order is the one in scripts/windows/dispatch_guard.py:
    (1) stop every running AUTO-MAS task by its dispatch taskId, so it does not
    treat this as a fault and retry; (2) wait 12 seconds, and only taskkill what
    is left; (3) check again - both the process list and AUTO-MAS's own list of
    unfinished tasks - and if either still shows something, run another stop
    round.

    Step (3) is what makes the answer true: AUTO-MAS relaunches the whole queue
    when a member is killed under it, so "killed it twice" says nothing about
    whether anything is still running half a minute later, and an empty process
    list does not mean AUTO-MAS has not started the queue's next member. An
    unreadable task list counts as "still running", the same way an unreadable
    process list does. (The user, 2026-08-26, on a stop that only
    reported success: 「你没有进行任何有效的停止行为，
    全是我手动关的」 - nothing had really been stopped, he closed it all by hand.)

    Killing AUTO-MAS itself is deliberately NOT done here: service.py's reviver
    holds its process handle and brings it back within seconds. When the relay
    cannot get the machine quiet, the honest answer is to say so and let the
    operator use scripts/mac/estop.sh, which stops this service first.

    Start and end of the press go to <state_dir>/estop-windows.json (see
    estop_windows), so the run it cut short is not booked as a success.
    """
    import time  # noqa: PLC0415
    sleep = sleep or time.sleep
    began = datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds")
    _estop_window_mark(state_dir, began)
    ESTOP_LAST.clear()
    rounds = 1
    try:
        farm, farm_ok = _estop_echo_farm(state_dir)
        stopped = _estop_stop_via_mas()
        sleep(12 if stopped else 2)
        _estop_kill()
        sleep(6)
        _estop_kill()
        sleep(6)

        alive, live = _estop_alive(), _estop_live_tasks()
        if alive or live is None or live:
            # Relaunched from under us, or AUTO-MAS moved on to the next member:
            # another stop round, then the truth either way.
            log.warning("红按钮：杀完还活着 %s，AUTO-MAS 未结束任务 %s，再停一轮", alive, live)
            stopped += [s for s in _estop_stop_via_mas() if s not in stopped]
            sleep(8)
            _estop_kill()
            sleep(6)
            alive, live = _estop_alive(), _estop_live_tasks()
            rounds = 2
    finally:
        _estop_window_mark(state_dir, began, datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"))
    ESTOP_LAST.update(alive=list(alive), live=None if live is None else [tuple(x) for x in live],
                      rounds=rounds, at=datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"))

    head = "、".join(stopped) if stopped else "AUTO-MAS 那边一个都没停到"
    farm = f"。{farm}" if farm else ""
    if not farm_ok:
        return False, texts.estop_farm_left_body(farm, head)
    if alive or live is None or live:
        left = []
        if alive:
            left.append("、".join(sorted({_ESTOP_LABELS.get(a, a) for a in alive})))
        if live is None:
            left.append("问不到 AUTO-MAS 还有没有任务在跑")
        elif live:
            left.append("AUTO-MAS 还记着有任务在跑：" + "、".join(label for _, label in live))
        return False, texts.estop_not_clean_body("；".join(left), head, farm)
    return True, f"已停一切：{head}；脚本和游戏都确认没了，AUTO-MAS 也没有在跑的任务了{farm}"


def _estop_echo_farm(state_dir) -> tuple[str, bool]:
    """End a running echo farm first, so the red button stops it for good.

    While the farm's record stays, echofarm.tick (every engine tick) relaunches
    OK-WW within minutes and farms on until the deadline, holding off the
    shutdown. It goes first so the tick cannot relaunch it while the stop rounds
    run. Returns (what to add to the answer, ok).
    """
    from ark_relay.features.echofarm import echofarm  # noqa: PLC0415
    from ark_relay.core.config import Config  # noqa: PLC0415
    try:
        cfg = Config()
        if state_dir:
            cfg.state_dir = Path(state_dir)
        note = echofarm.finish(cfg, "停止一切")
    except Exception as exc:
        log.exception("红按钮：结束刷声骸失败")
        return f"结束刷声骸时出错：{exc}", False
    return (f"刷声骸也停了：{note}" if note else ""), True
