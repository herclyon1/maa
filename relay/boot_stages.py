#!/usr/bin/env python3
"""The boot sequence: one function per step, in the order `service.py` runs them.

Split out of `service.py` (2026-09-08, moved verbatim). What is left there is
the Windows-service plumbing and the main loop; everything that happens exactly
once, between the service starting and that loop being entered, is here.

Why this is a block of its own: the boot sequence is a list of steps that runs
top to bottom once and is then over, while the rest of `service.py` is
machinery that keeps running for as long as the machine is on - answering the
SCM, watching a directory, holding a handle on the AUTO-MAS backend. They are
read for different reasons and change for different reasons, and until now
reading either one meant scrolling through the other.
`ArkRelayService.main` stays behind as the order the steps run in, and that
order is the whole of what it says.

`_revive_automas` and `ensure_automas` live here too, although the
`_AutomasKeeper` in `service.py` uses `_revive_automas` as well: the boot steps
call the pair five times between them, and keeping them on the service side
would mean this module importing `service.py` while `service.py` imports this
one. The dependency runs one way only - `service.py` imports this module, never
the reverse - and the keeper reaches in for the one name it needs.
"""
from __future__ import annotations

import contextlib
import functools
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import win32event

from ark_relay import texts
from ark_relay.config import SERVER_TZ, both_clocks

# The directory this file and service.py share. Computed here rather than
# imported from service.py, so the import between the two stays one-way.
HERE = Path(__file__).resolve().parent

AUTOMAS_TASK = "AUTO-MAS_AutoStart"


def _maaend_dir(cfg):
    """MaaEnd's install path, as AUTO-MAS records it."""
    from ark_relay import plan  # noqa: PLC0415
    return plan.script_dir(cfg.automas_dir, "MaaEnd")


def shell_running() -> bool:
    """True if the Electron shell (AUTO-MAS.exe) is up, whatever the backend is doing.

    Lives here rather than in service.py because ensure_automas needs it and the
    import between the two modules runs one way only. service.py re-exports it.
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq AUTO-MAS.exe", "/NH"],
            capture_output=True, timeout=25,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True   # cannot tell -> assume it is there, i.e. do not kill
    return b"AUTO-MAS.exe" in out


def _revive_automas() -> None:
    """Restart AUTO-MAS through its scheduled task, which owns session 1.

    Three steps, and skipping any of them makes this silently do nothing:

    The Electron shell outlives its own Python backend - the window sits there
    looking healthy while nothing is scheduling runs, which is the exact state
    the machine was found in. So the shell has to go first.

    The task also still counts as running while that shell is alive, and
    `schtasks /run` on an already-running task returns 0x41301 and starts
    nothing. `/end` clears that before `/run` can take.

    Since v5.5.0-beta.6 (2026-09-17) the shell does its start-up through a
    separate `auto-mas-runtime.exe` ("Runtime managed" mode: sync the backend
    repo, prepare the managed Python, sync the locked dependencies, then
    supervise the backend). That process survives `taskkill AUTO-MAS.exe` and
    keeps holding the environment lock; the shell started next then fails its
    own bootstrap with MUTATION_IN_PROGRESS and parks on the initialisation page
    「等待用户处理」 - no backend, no queue, until a person clicks. That is what
    took out the 21:30 queue on 2026-09-17. So the runtime goes too.
    """
    for cmd in (
        ["taskkill", "/IM", "AUTO-MAS.exe", "/F"],
        ["taskkill", "/IM", "auto-mas-runtime.exe", "/F"],
        ["schtasks", "/end", "/tn", AUTOMAS_TASK],
    ):
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    time.sleep(4)  # let the shell actually exit before the task is re-run
    try:
        subprocess.run(["schtasks", "/run", "/tn", AUTOMAS_TASK],
                       capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass  # next check will try again


# How long an AUTO-MAS shell that is already up gets to open its API before it
# is killed and restarted. The logon task starts the shell seconds after the
# relay service starts, and since v5.5.0-beta.6 the shell first runs a
# bootstrap (repo sync, managed Python, locked dependencies) before the backend
# even starts: 20-25 s measured on 2026-09-17 with the mirrors answering, and
# longer the first time after an update or on a slow mirror (0.12 MB/s that
# evening). On 2026-09-17 21:20 the relay checked 11 s after the shell started,
# found no API, killed the shell mid-bootstrap, and the evening queue never ran.
SHELL_STARTUP_GRACE = 150


def _stop_requested() -> bool:
    """The service has been told to stop (SvcStop, or Windows going down).

    Checked inside every wait here: on 2026-09-18 23:10 the self-update
    restarted the service while ensure_automas() was in its 150 s
    「先等它自己起来」 sleep, SvcStop waited 15 s and the hard guard had to
    force-exit the process. A wait that cannot hear the stop is a hang.
    """
    from ark_relay import errwatch  # noqa: PLC0415
    return errwatch.going_down()


def _wait_for_api(deadline: float) -> "float | None":
    """Poll the API until `deadline` (monotonic). Returns seconds waited on success,
    None on timeout - or at once, still None, when the service is stopping."""
    from ark_relay import commands  # noqa: PLC0415
    t0 = time.monotonic()
    while time.monotonic() < deadline:
        if _stop_requested():
            return None
        time.sleep(3)
        if commands.mas_up():
            return time.monotonic() - t0
    return None


def ensure_automas(timeout: float = 120, grace: float = SHELL_STARTUP_GRACE) -> bool:
    """Start AUTO-MAS if its API is not answering, then wait for it to come up.

    The user, 2026-09-03: 「MAS 不在的时候你要拉起他，
    不希望见到任何理由开机时检测不到配置，而且要快。」

    Order matters: a shell that is already up is given `grace` seconds to open
    its API on its own before anything is killed - killing it earlier is what
    lost the 2026-09-17 evening queue (see _revive_automas). Only a shell that
    is absent, or one that has used up its grace, is force-restarted, and the
    restart itself gets `timeout` seconds.
    """
    import logging  # noqa: PLC0415
    from ark_relay import commands  # noqa: PLC0415
    log = logging.getLogger("ark.service")
    if commands.mas_up():
        return True
    if shell_running():
        log.info("AUTO-MAS 窗口已在、接口还没开，先等它自己起来（最多 %.0f 秒）", grace)
        waited = _wait_for_api(time.monotonic() + grace)
        if waited is not None:
            log.info("AUTO-MAS 自己起来了（等了 %.0f 秒）", waited)
            return True
        if _stop_requested():
            # A stop (the self-update restart, a shutdown) arrived mid-wait: leave
            # the shell alone - killing a healthy, still-bootstrapping AUTO-MAS is
            # the 2026-09-17 incident - and let the next process pick it up.
            log.info("服务正在停止，不再等 AUTO-MAS，也不动它")
            return False
        log.warning("AUTO-MAS 等了 %.0f 秒接口还是不通，杀掉重拉", grace)
    if _stop_requested():
        log.info("服务正在停止，不拉 AUTO-MAS")
        return False
    log.warning("AUTO-MAS 接口不在，拉起它")
    _revive_automas()
    waited = _wait_for_api(time.monotonic() + timeout)
    if waited is not None:
        log.info("AUTO-MAS 已拉起（%.0f 秒）", waited)
        return True
    if _stop_requested():
        log.info("服务正在停止，不再等 AUTO-MAS 起来")
        return False
    log.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", timeout)
    return False


def _boot_stamp(now: datetime) -> str:
    """Identifier for this boot: the power-on moment to the minute. Restarting the service for a deploy does not change it."""
    try:
        import ctypes  # noqa: PLC0415
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong  # 64-bit; do not truncate
        up_ms = ctypes.windll.kernel32.GetTickCount64()
        return (now - timedelta(milliseconds=int(up_ms))).strftime("%Y%m%d%H%M")
    except Exception:  # noqa: BLE001
        return now.strftime("%Y%m%d%H")


def _seconds_to_next_queue(automas_dir, now: datetime) -> float:
    """Seconds until today's next queue; when today has none left, hand back the large evening budget."""
    from ark_relay import plan  # noqa: PLC0415
    best = None
    for q in plan.schedule(automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due > now and (best is None or due < best):
                best = due
    if best is None:
        return 3600.0
    return max(120.0, (best - now).total_seconds() - 90)


def _stage_bootstrap():
    """First boot step: environment variables, logging, config, engine. Returns None when the config is unusable."""
    import logging  # noqa: PLC0415

    # The scheduled-task launcher used to set these before starting Python,
    # and .env never carried them - so a service, which does not go through
    # that launcher, ran fine but wrote its log nowhere. A service with no
    # log is a service you cannot debug, which defeats the point of making
    # the relay unkillable. Set them here, but let .env win if it says
    # otherwise.
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("ARK_LOG_FILE", str(HERE / "relay.log"))

    from ark_relay.__main__ import _force_utf8_console, _load_dotenv, _setup_logging  # noqa: PLC0415
    _force_utf8_console()
    # Absolute path: a service starts with an unrelated working directory,
    # and a silently empty config would disable every push channel.
    _load_dotenv(HERE / ".env")
    _setup_logging(verbose=False)

    from ark_relay.config import Config  # noqa: PLC0415
    from ark_relay.core import State  # noqa: PLC0415
    from ark_relay.engine import Engine  # noqa: PLC0415
    from ark_relay.notify import Notifier  # noqa: PLC0415
    from ark_relay.transport import LocalSource  # noqa: PLC0415

    log = logging.getLogger("ark.service")
    cfg = Config()
    if problems := cfg.validate():
        for p in problems:
            log.error("配置有问题: %s", p)
        return

    notifier = Notifier(cfg)
    engine = Engine(cfg, LocalSource(cfg), State(cfg.state_dir), notifier)
    # From here on each new kind of ERROR any module logs reaches the group once,
    # and the self-recovered faults go to the daily report (see errwatch).
    from ark_relay import errwatch  # noqa: PLC0415
    from ark_relay.statestore import StateStore  # noqa: PLC0415
    errwatch.install(notifier, lambda: bool(getattr(engine, "_shutdown_issued", False)),
                     version=lambda: StateStore(cfg.state_dir).get("versions", "code"))
    # Alarm copies a shutdown cut off before they reached COS go up now (alertlog.py).
    try:
        notifier.alert_log().flush_async()
    except Exception:   # the copy never stops the boot
        log.warning("报警抄送补传没能开始", exc_info=True)
    engine.bootstrap()
    log.info("服务模式启动，监视 %s（变更即处理，兜底 %d 秒）",
             cfg.history_dir, cfg.poll_seconds)
    return log, cfg, notifier, engine


def _stage_patch_okww(cfg, notifier, log) -> None:
    """Apply the OK-WW patches once per startup (idempotent)."""
    # Idempotent: it writes nothing at all when they are already in place.
    # Here, not only in the boot pre-update block: after a deploy the machine
    # should already be in its final state, with no "takes effect next boot"
    # loose end.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_patch_okww」
    try:
        # Local import: a module-level one would be evaluated during service
        # installation, when ark_relay may not be on sys.path yet.
        from ark_relay import okww_patch as _okww_patch  # noqa: PLC0415

        okww_at_boot = cfg.okww_dir or (
            Path(cfg.automas_dir).parent / "okww" if cfg.automas_dir else None)
        notes = _okww_patch.ensure_patches(okww_at_boot)
        # The overrides that live in OK-WW's own ok_tasks/ folder instead of in its
        # source files. Installed here so a deploy leaves the machine in its final
        # state, and read back so an override that did not take is audible.
        from ark_relay import okww_overlay as _overlay  # noqa: PLC0415
        if line := _overlay.install(okww_at_boot):
            notes.append(line)
        if line := _overlay.write_master_pointer(cfg.automas_dir):
            notes.append(line)
        if line := _overlay.report_line():
            notes.append(line)
        if line := _overlay.drift_line(okww_at_boot, cfg.state_dir):
            notes.append(line)
        for note in notes:
            log.info("启动：%s", note)
        # One push per startup. It used to push one message per patch, so a
        # single OK-WW update dumped eight of them on the phone at once
        # (the user, 2026-09-06: 「你这个通知一直在轰炸我」). alert=True: a patch that
        # did not bind goes to the group, each time (until 2026-10-06 Server酱 only);
        # the healthy 「🩹 OK-WW 补丁」 stays log-only (notify.route_of).
        if notes:
            notifier.send(texts.patches(len(notes), notes), "\n".join(f"· {n}" for n in notes), alert=True)
    except Exception:
        log.exception("启动时贴 OK-WW 补丁失败，服务照常继续")


def _stage_selfupdate(log) -> bool:
    """Pull new code; when something really updated, trigger a restart and return True so the caller exits at once."""
    try:
        from ark_relay import selfupdate  # noqa: PLC0415

        if changed := selfupdate.check(HERE):
            # Take effect now, not next boot. The files are on disk but this
            # process imported the old ones, so the only honest way to run
            # the new code is to be a new process. Waiting for the next boot
            # meant a fix pushed in the morning sat unused all day - and a
            # queued command that needs that fix could not be understood.
            #
            # A detached restarter rather than exiting and trusting the SCM's
            # failure actions: if those are ever unset, exiting would leave
            # the relay down until tomorrow, which is worse than the problem
            # being fixed.
            log.info("代码已更新，重启以立即生效: %s", "、".join(changed))
            subprocess.Popen(
                ["cmd", "/c", "timeout /t 3 /nobreak >nul & "
                              "net stop ark-relay & net start ark-relay"],
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                               | subprocess.DETACHED_PROCESS))
            # True, not a bare return: service.py exits on it. From 09-08
            # (25b76dd4 moved this out of main) to 09-29 it returned None, so
            # the dying process ran the boot stages anyway - on 09-29 08:45 it
            # launched MAA, got force-exited with MAA still open, and the new
            # process's MAA became a "secondary launch" that never logged a
            # verdict: 180 s wasted and a false 「没能确认」.
            return True
    except Exception:
        log.exception("自更新出错，跳过")
    return False


def _stage_backfill_manual_stops(engine, log) -> None:
    """Book as manual stops the runs a recorded red-button press cut short but the ledger missed.

    Right after the self-update, so it runs in the new code, and before the main
    loop, whose ticks push held alarms and send the daily report. The engine has
    already loaded held alarms in its constructor; the backfill edits those in
    memory. Never fatal: a failure here only costs the ⏹ on those rows.
    """
    try:
        from ark_relay import handle  # noqa: PLC0415
        if n := handle.backfill_manual_stops(engine):
            log.info("⏹ 开机补记：%d 趟被停一切停掉的运行已记成手动停止", n)
    except Exception:
        log.exception("开机补记停一切出错（日报那几行会照原样显示）")


def _stage_evidence_sources(cfg, notifier, log) -> None:
    """Compare the pinned upstream export sources with their default branches; say so if they moved.

    The evidence bundles copy three upstream functions (evidence.py). If any
    of those files changes upstream, the copy may no longer match what the
    project's own button produces - and nobody would know. So every boot
    fetches the current file (jsDelivr, reachable from the machine) and
    compares hashes. Unreachable is only logged: that is the CDN, not a change.
    """
    try:
        from ark_relay import evidence, texts  # noqa: PLC0415
        changed, unreachable = evidence.check_sources()
        # One upstream change is one notice. Every boot compared again and
        # re-sent the same change until somebody re-pinned. Remember what was
        # announced, by the upstream text's fingerprint; a further upstream
        # change to the same file has a new fingerprint and is sent again.
        import json  # noqa: PLC0415
        seen_file = Path(cfg.state_dir) / "evidence-source-notified.json"
        try:
            told = json.loads(seen_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            told = {}
        new = [n for n in changed if told.get(n) != evidence.LAST_SEEN.get(n)]
        if changed:
            log.warning("上游导出代码变了：%s%s", "、".join(changed),
                        "" if new else "（都已报过，不再重发）")
        if new:
            notifier.send(texts.EVIDENCE_SOURCE_CHANGED, texts.evidence_source_changed_body(new))
            told.update({n: evidence.LAST_SEEN.get(n) for n in new})
            try:
                seen_file.write_text(json.dumps(told, ensure_ascii=False), encoding="utf-8")
            except OSError:
                log.exception("记不下已报过的上游变化，下次开机可能重报")
        elif unreachable:
            log.info("上游导出代码核对：%d 个文件今天拉不到，明天再比", len(unreachable))
        else:
            log.info("上游导出代码核对：三处都和登记的一致")
        n = evidence.prune(cfg.state_dir)
        if n:
            log.info("清掉 %d 个超过 30 天的本地证据目录", n)
    except Exception:  # a check must never stop the boot
        log.exception("核对上游导出代码时出错")


def _stage_announce_update(notifier, log) -> None:
    """First thing once the new code is up: announce either the failed update or the applied one."""
    # We only reach here on a process that did NOT just apply an update -
    # which, after a self-restart, is the process running the new code. So
    # this is the first honest moment to say the update took effect, and
    # the operator asked to be told the moment it does.
    try:
        from ark_relay import selfupdate  # noqa: PLC0415 - see the block above

        # An update that was available and did not land must be as loud
        # as one that did. Otherwise the machine quietly runs old code
        # while everything upstream assumes the push took effect - the
        # same trap as an scp that returns 0 without transferring.
        if fail := selfupdate.take_failure(HERE):
            files = fail.get("files") or []
            more = max(0, int(fail.get("count") or 0) - len(files))
            body = "\n".join([
                f"原因：{fail.get('reason') or '未知'}",
                f"仓库 v{fail.get('remote') or '?'}，本机仍是 v{fail.get('local') or '?'}",
                "没更新的文件：" + "、".join(files) + (f" 等 {more} 个" if more else ""),
                "",
                "本机现在跑的是旧代码。下次开机会自动重试；",
                "要立刻生效请在控制端执行 scripts/mac/deploy-relay.sh。",
            ])
            if errors := notifier.send(texts.SELFUPDATE_FAILED, body, alert=True):
                log.error("更新失败通知没发出去: %s", "；".join(errors))
            else:
                log.info("已推送更新失败通知")

        if note := selfupdate.pending_announcement(HERE):
            files = note.get("files") or []
            title = (f"🔄 中继已更新（{len(files)} 个文件）" if files
                     else "🔄 中继已更新")
            applied = note.get("at") or ""
            try:
                when = both_clocks(datetime.fromisoformat(applied))
            except ValueError:
                when = applied
            lines = [f"{when} 生效" if when else "刚刚生效"]
            prev = note.get("previous")
            lines.append(f"版本 v{prev} → v{note.get('version') or '?'}"
                         if prev else f"版本 v{note.get('version') or '?'}")
            # Plain language first: take "which problem you hit did this fix"
            # from RELEASE-NOTES.md, and only fall back to listing file names
            # when there is no notes file.
            # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_announce_update」
            notes = ""
            try:
                nf = HERE / "RELEASE-NOTES.md"
                if nf.exists():
                    notes = nf.read_text(encoding="utf-8").strip()
            except OSError:
                notes = ""
            if notes:
                lines += ["", notes]
            else:
                # The file list only exists when the process that applied the
                # update was already running this code; the first update after
                # this shipped has no list, and saying so beats an empty line.
                lines.append("改动文件：" + "、".join(files) if files
                             else "（改动清单由上一版代码写入，本次没有）")
            lines += ["", "更新在开机后、队列开跑前落地，本轮直接使用新代码。"]
            body = "\n".join(lines)
            # Two deploys of the same change - one refused by a gate, fixed, and
            # deployed again - are one change to the person reading his phone, and
            # he got the same paragraph twice within five minutes on 2026-09-09 and
            # asked why the identical update ships twice. The version differs, so
            # nothing upstream can tell; the notes are what he actually reads, so
            # they are what gets compared. A changed line pushes as normal.
            from ark_relay.statestore import StateStore  # noqa: PLC0415
            _st = StateStore(HERE / "state")
            _last = str(_st.get("versions", "announced_notes") or "")
            if notes and notes == _last:
                log.info("这次更新的说明和上一条一模一样，不再推一遍（v%s）",
                         note.get("version") or "?")
                selfupdate._remember_announced(HERE, int(note.get("version") or 0))
                return
            # The notes are what he reads; since 2026-09-14 the push itself is
            # log-only (docs/NOTIFICATIONS.md), so they go into the day's report
            # instead (「今天中继改了」 at the end of the daily). Appended per
            # deploy; the report reads the day's file.
            if notes:
                try:
                    from ark_relay import report as _rp  # noqa: PLC0415
                    _rp.remember_change(HERE / "state", notes, str(note.get("version") or ""))
                except Exception:
                    log.exception("更新说明没记进当天的日报")
            if errors := notifier.send(title, body):
                log.error("更新通知没发出去: %s", "；".join(errors))
            else:
                log.info("更新说明已记入当天日报（v%s）", note.get("version") or "?")
                _st.set("versions", "announced_notes", notes)
    except Exception:
        log.exception("推送更新通知出错，跳过")


def _make_collect(inbox, engine, notifier, log, deferred_inbox):
    """Build the action that checks the todo mailbox once and pushes a message if anything new landed.

    A separate step because it is called at three moments - at boot, on every
    round of the loop, and before shutdown - and all three have to make the
    same decision. The most important part of that decision: nothing may land
    while a script is running, because config written then is clobbered by
    AUTO-MAS's in-memory copy. So it defers on the spot and records the
    outstanding check in deferred_inbox for the main loop to see.
    """

    def collect(reason: str) -> None:
        """Check for queued changes and push whatever landed.

        来龙去脉见 docs/CODE-HISTORY.md「service.py:collect」。
        """
        if engine.scripts_running():
            if not deferred_inbox[0]:
                log.info("待办检查（%s）推迟：脚本正在运行，"
                         "此时改配置会被 AUTO-MAS 冲掉", reason)
            deferred_inbox[0] = True
            return
        deferred_inbox[0] = False
        try:
            version, messages = inbox.poll()
        except Exception:
            log.exception("待办检查出错，跳过")
            return
        if messages:
            for m in messages:
                log.info("待办: %s", m)
            notifier.send(messages[0], "\n".join(messages[1:]).strip())
        else:
            log.debug("待办检查（%s）：无新配置（当前 v%s）", reason, version)

    return collect


# Phone commands that only mean something while the machine is running. A
# backlog of them is read once at boot (Mailbox.fetch, the last 24 h); a red
# button pressed at 17:5x on a machine that had been off since 14:47
# (2026-09-19) would otherwise fire at the 21:20 boot: stop every AUTO-MAS
# task, taskkill every game, push 「已停一切」 - all against nothing, minutes
# before the 21:30 queue. Nothing was running when it was pressed and nothing
# is running at boot; the press is stale by definition.
LIVE_ONLY_ACTIONS = ("estop",)


def boot_backlog(cmds: list[dict], log) -> list[dict]:
    """The boot-time mailbox backlog with the live-only presses dropped, each one logged."""
    out: list[dict] = []
    for body in cmds:
        action = str((body or {}).get("action") or "")
        if action in LIVE_ONLY_ACTIONS:
            log.warning("信箱里有一条关机期间按的「%s」，开机不执行（当时和现在都没有在跑的东西）", action)
            continue
        out.append(body)
    return out


def _phone_answer(receipt, log, push_state, action: str, sent, ok: bool, msg: str) -> None:
    """Write an order's receipt and push the state: the answer is on the page where he pressed."""
    try:
        receipt(action, sent, ok, msg)
    except Exception:
        log.exception("手机指令回执没记下")
    push_state("改完配置")


def _phone_stamp_sent(body: dict, sent, meta: dict | None) -> None:
    """echo_farm's deadline is read against when it was sent. ntfy's own clock first:
    a phone whose clock runs a few minutes fast would turn 「刷到 21:00」 pressed at
    20:58 into tomorrow's 21:00."""
    ntime = (meta or {}).get("ntfy_time")
    when = ntime if isinstance(ntime, int) else sent
    if when is not None:
        body["sent"] = when


def _phone_execute(apply_command, notifier, log, push_state, receipt,
                   body: dict, action: str, sent, notify: bool, meta: dict | None = None) -> None:
    """Apply one order, write its receipt, push the state - live or drained alike."""
    from ark_relay import engine as _engine_mod  # noqa: PLC0415
    if action == "echo_farm":
        _phone_stamp_sent(body, sent, meta)
    ok, msg = apply_command(body)
    log.info("📱 手机指令 %s：%s", action, msg)
    # Whatever the order changed or started, the next 「is anything running」
    # asks AUTO-MAS afresh: the drain loop's own next check, and the shutdown
    # decision of the same tick, which would otherwise reuse a 「nothing runs」
    # read from up to three seconds before.
    _engine_mod.forget_scripts_cache()
    # The answer goes onto the phone page (state snapshot) - the user reads
    # it where he pressed the button (2026-09-14); a failed order is still
    # pushed as information.
    try:
        receipt(action, sent, ok, msg)
    except Exception:
        log.exception("手机指令回执没记下")
    if notify:
        notifier.send(texts.CONFIG_CHANGED if ok else texts.CONFIG_FAILED, msg)
    push_state("改完配置")


def _phone_enqueue(queue, log, queued_receipt, raw: dict, action: str, mid: str, sent) -> None:
    """Put one order on the queue (phone.CmdQueue). While a script runs (`queued_receipt`
    given), a new order - or a new press of the same waiting one - is answered at
    once with a 「排队中」 receipt and a state push (D207)."""
    from ark_relay import phone as _phone  # noqa: PLC0415
    got = queue.add(raw)
    if got == _phone.QUEUED:
        log.info("📱 手机指令 %s 排队，等脚本跑完再执行（id %s）", action, mid)
    elif got == _phone.RESENT:
        # Pressed again while the same order waits: not queued twice, but this
        # press gets its own receipt (the App matches a receipt to a press by
        # send time).
        log.info("📱 手机指令 %s 又按了一次，和排着的那条一样，不重复排（id %s）", action, mid)
    else:
        log.info("📱 手机指令 %s 已经排过队或执行过，不再重复（id %s）", action, mid)
    if queued_receipt is not None and got in (_phone.QUEUED, _phone.RESENT):
        queued_receipt(action, sent)


def _make_phone_cmd(engine, notifier, log, hb, push_state, cfg_state_dir=None):
    """Build the callback for what happens after a button is pressed on the phone.

    A separate step because it has two entry points: at boot the commands that
    piled up are worked through one by one, and after that the long-lived
    connection calls it again for every command it hears - both have to be the
    same logic.
    """
    from ark_relay.commands import apply_command  # noqa: PLC0415
    from ark_relay import phone as _phone  # noqa: PLC0415

    # Orders that came in while a script was running wait here for the end of
    # the run (phone.CmdQueue). Same state dir the commands themselves use.
    queue = _phone.CmdQueue(cfg_state_dir if cfg_state_dir is not None
                            else os.environ.get("ARK_STATE_DIR", "./ark-state"))
    drain_lock = threading.Lock()

    def _receipt(action, sent, ok, msg, queued=False):
        # "sent" beside "at": the page shows both (「HH:MM 发出 · HH:MM 执行」,
        # web data 5238f367), so the text itself stays the plain answer.
        from ark_relay import modes as _modes  # noqa: PLC0415
        _modes.add_receipt(cfg_state_dir, action, ok, msg, sent=sent, queued=queued)

    def _queued_receipt(action: str, sent) -> None:
        """D207: the moment an order is queued behind a running script, a receipt says
        so and a state goes out, so the App shows 「排队中」 instead of 「没生效」."""
        try:
            _receipt(action, sent, True, texts.PHONE_QUEUED, queued=True)
        except Exception:
            log.exception("手机指令排队回执没记下")
        push_state("指令排队")

    _execute = functools.partial(_phone_execute, apply_command, notifier, log, push_state, _receipt)

    def _refuse_dispatch(action: str, sent) -> None:
        """An order that starts a run, pressed while one is running: answered on the
        page, not queued. Run after the run it would start one more - the whole
        queue again for 「现在跑」, which is how MAA got an extra run and burned
        sanity potions on 2026-09-01 (commands.run_script). No push."""
        msg = f"「{texts.action_name(action)}」没执行：{texts.phone_busy_reason(action)}"
        log.info("📱 手机指令 %s 在跑的时候到，不排队：%s", action, msg)
        _phone_answer(_receipt, log, push_state, action, sent, False, msg)

    def drain() -> int:
        """Run the queued orders, oldest first, once nothing is running. Returns how many ran.

        Called at the top of every engine tick (before the shutdown decision of
        that tick, so a queued 「现在跑」 or skip is seen by it) and right after an
        order is queued while idle. Nothing is pushed to the group or Server酱:
        the receipt and the state are the answer, on the page where he pressed.
        """
        if not len(queue):
            return 0
        n = 0
        held = getattr(push_state, "held", None)
        with drain_lock, (held() if held is not None else contextlib.nullcontext()):
            while True:
                if engine.scripts_running():
                    break           # a run started again; the rest waits for its end
                item = queue.pop()
                if item is None:
                    break
                body = dict(item["body"])
                meta = body.pop("_meta", None) or {}
                # The latest press of it: the final receipt answers every press (D207).
                sent = _phone.item_sent(item)
                action = str(body.get("action") or "")
                if action in _phone.DISPATCHING_ACTIONS:
                    # Queued before this rule (or behind older orders when a run
                    # started): it would start a run the user did not see coming.
                    _refuse_dispatch(action, sent)
                    n += 1
                    continue
                if _phone.cmd_expired(item):
                    msg = (f"「{texts.action_name(action)}」等这一趟跑完时已过了 24 小时，"
                           "过期没执行；需要就重新发一次")
                    log.warning("📱 排队的手机指令 %s 过期没执行（id %s）",
                                action, meta.get("ntfy_id") or "?")
                    _phone_answer(_receipt, log, push_state, action, sent, False, msg)
                    n += 1
                    continue
                log.info("📱 脚本已停，执行排队的手机指令 %s（id %s，%s 排进来）",
                         action, meta.get("ntfy_id") or "?",
                         datetime.fromtimestamp(int(item.get("queued") or 0), tz=SERVER_TZ)
                         .strftime("%H:%M:%S"))
                _execute(body, action, sent, notify=False, meta=meta)
                n += 1
        return n

    def run_phone_cmd(body: dict) -> None:
        """One press from the phone. Refresh only answers with state; everything else really changes config, and notifies the moment it is done."""
        # phone.stamp's "_meta" (when it was sent, how it arrived) is for the log
        # and the receipt only; the command itself goes on without it.
        raw = dict(body or {})
        meta = (body or {}).get("_meta") or {}
        body = {k: v for k, v in (body or {}).items() if k != "_meta"}
        sent = meta.get("sent") if isinstance(meta.get("sent"), int) else None

        def receipt(ok, msg):
            _receipt(action, sent, ok, msg)

        action = str((body or {}).get("action") or "")
        if action == "refresh":
            # A state that already reached the mailbox answers it (phone.StatePusher):
            # the App's 4-second re-ask and the refreshes read back at boot.
            answered = getattr(push_state, "answered", None)
            if answered is not None and answered(meta.get("ntfy_time")):
                return
            ensure_automas()          # make sure it is alive before reading config
            push_state("手机请求")
            return
        if action == "watch":
            hb.watch()          # the page is open: beat every 30s for the next 10 minutes
            return
        if action == "estop":
            # Red button: it gets pressed precisely while scripts are running,
            # so it must not be blocked by the gate below.
            from ark_relay import commands as _cmd  # noqa: PLC0415
            ok, msg = _cmd.estop(state_dir=cfg_state_dir)
            log.warning("🛑 红按钮：%s", msg)
            try:
                receipt(ok, msg)
            except Exception:
                log.exception("红按钮回执没记下")
            # The title has to follow the answer. It used to be 「已停一切」 whatever
            # came back, so the one case that needs the operator - the relay could
            # not get the machine quiet - was pushed to his phone as a success.
            notifier.send(texts.ESTOP if ok else texts.ESTOP_FAILED, msg, alert=not ok)
            push_state("红按钮")
            return
        # These two write the relay's own StateStore and nothing else, so the
        # AUTO-MAS in-memory copy cannot clobber them and the gate below does not
        # apply. 「下次跑完不关机」 in particular is only ever pressed **while** a
        # run is going - that is the whole point of it - and it was the one command
        # the gate reliably threw away.
        if action not in ("skip_shutdown", "debug_mode"):
            # Config changed while a script is running gets clobbered by
            # AUTO-MAS's in-memory copy, so the order waits for the end of the
            # run (it used to be dropped with a 「再按一次」 push). An order that
            # comes in while older ones still wait queues behind them, so they
            # run in the order they were pressed.
            running = engine.scripts_running()
            if action in _phone.DISPATCHING_ACTIONS:
                # Never queued (see _refuse_dispatch). Older orders still waiting
                # go first, so a setting pressed before it is in place for its run.
                if not running and len(queue):
                    drain()
                    running = engine.scripts_running()
                if running:
                    _refuse_dispatch(action, sent)
                    return
            elif running or len(queue):
                _phone_enqueue(queue, log, _queued_receipt if running else None,
                               raw, action, meta.get("ntfy_id") or "?", sent)
                if not running:
                    drain()
                return
        _execute(body, action, sent, notify=True, meta=meta)

    run_phone_cmd.drain = drain
    return run_phone_cmd


def _start_phone_channel(svc, cfg, engine, notifier, log):
    """Bring up the whole phone channel: mailbox, heartbeat, two background threads.

    A separate step because this section does exactly one thing - let the phone
    both see the state and change the config - and it exposes only one thing to
    the outside: push_state, which reports state and is needed once more before
    shutdown.
    """
    # Fetching once at boot is enough: the machine restarts for every queue run,
    # and the config is almost always changed while it is off, so the next boot
    # is bound to pick it up. Online/offline must not be done by polling; how it
    # is done instead is in phone.py's module docstring.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_inbox_and_phone」
    from ark_relay.phone import Mailbox, state_cos  # noqa: PLC0415

    # The whole state goes to COS and ntfy only carries a notice (phone.state_cos)
    box = Mailbox(cfg.phone_topic, cfg.phone_pin, cfg.state_dir, cos=state_cos(cfg))
    svc._mailbox = box          # SvcStop uses this to cut the long-lived connection

    def publish_state(why: str) -> bool:
        if not box.enabled:
            return False
        try:
            from ark_relay.phone import state_payload  # noqa: PLC0415
            ok = box.publish(state_payload(cfg, cfg.state_dir))
        except Exception:
            log.warning("状态没能上报到手机（%s）", why, exc_info=True)
            return False
        # The day's count rides along: on 2026-10-02 nobody could see the 250
        # running out until it had (phone.Quota; ntfy's own count once synced).
        if ok:
            log.info("📱 已上报状态到手机（%s；今天 ntfy 已用 %d 条）", why, box.quota.total())
        else:
            # Only when the phone cannot see this state at all: neither COS nor
            # ntfy carried it (a state on COS is delivered even when the ntfy
            # notice is refused - 10-02 22:56 that was logged here as a failure,
            # with 「今天 ntfy 已发 0 条」 beside ntfy's own 42908).
            log.warning("状态没能上报到手机（%s）：%s；手机上留着上一份状态", why,
                        box.last_error or "原因没说")
        return ok

    from ark_relay.phone import StatePusher  # noqa: PLC0415
    # Callable like the old push_state(why); also skips refreshes a state
    # already answered and folds the boot backlog's pushes into one.
    push_state = StatePusher(publish_state)

    # SvcStop pushes one last state before the mailbox is cut, so a shutdown
    # issued by hand (not by the relay) still leaves the phone page current.
    # 2026-09-11 the page said 「最后状态 1 小时 38 分前」 after such a shutdown.
    svc._push_state = push_state
    # A skip that engages, fails or is restored writes a receipt on the engine
    # thread; this sends the page the snapshot that carries it.
    engine._push_state = push_state

    from ark_relay.phone import Heartbeat  # noqa: PLC0415
    hb = Heartbeat(box.topic, cfg.state_dir, cos=box.cos)   # its beat on COS too
    run_phone_cmd = _make_phone_cmd(engine, notifier, log, hb, push_state, cfg.state_dir)
    # Orders queued while a script ran are applied at the top of the first tick
    # that finds nothing running - before that tick's shutdown decision.
    engine._phone_drain = run_phone_cmd.drain

    if not ensure_automas() and not _stop_requested():
        # Say it now, to the group: with no backend the next queue will not run,
        # and the keeper's own alarm only fires after its third failed revival
        # (2026-09-17: 45 s of silence in the log, then nothing until 21:55).
        # Not when the service is stopping: that False means "did not wait",
        # not "down", and the restarted process checks again.
        notifier.send(texts.AUTOMAS_DOWN, texts.automas_boot_down_body(), alert=True)
    def run_backlog(cmds) -> None:
        # One state for the whole backlog, after it: each order used to push
        # its own (09-30 08:46: 5 orders + 11 refreshes = 64 messages).
        with push_state.held():
            for body in boot_backlog(cmds, log):
                run_phone_cmd(body)

    push_state("开机")
    if box.enabled:
        run_backlog(box.fetch())
        threading.Thread(
            target=lambda: box.listen(
                run_phone_cmd,
                lambda: win32event.WaitForSingleObject(svc.stop_event, 0)
                == win32event.WAIT_OBJECT_0,
                # a boot read that timed out is read again once ntfy answers
                on_backlog=run_backlog),
            name="phone-mailbox", daemon=True).start()
        # ToDesk-style presence: it only beats while the page says it is
        # watching, and sends bye when the service stops. The page uses it to
        # flip between powered on and off by itself, with no manual refresh
        # (asked for by the user on 2026-09-02).
        threading.Thread(
            target=lambda: hb.loop(
                lambda: win32event.WaitForSingleObject(svc.stop_event, 0)
                == win32event.WAIT_OBJECT_0),
            name="phone-heartbeat", daemon=True).start()

    return push_state


def _stage_inbox_and_phone(svc, cfg, engine, notifier, log):
    """Todo mailbox plus phone channel. Returns (inbox, collect, deferred_inbox), which the main loop needs."""
    from ark_relay.inbox import Inbox  # noqa: PLC0415

    inbox = Inbox(cfg.state_dir, cfg.inbox_url,
                  cfg.maaend_dir or _maaend_dir(cfg), cfg.automas_dir)

    # A config command that arrives while a queue is running waits here
    # until every script has stopped, then lands.
    deferred_inbox = [False]
    collect = _make_collect(inbox, engine, notifier, log, deferred_inbox)
    push_state = _start_phone_channel(svc, cfg, engine, notifier, log)

    # One last todo fetch and state report before shutdown: someone may have
    # just pressed 「今晚别关机」 on their phone, and the state shown there has
    # to come to rest looking the way it did the moment the machine powered off.
    def before_shutdown() -> None:
        collect("关机前")
        push_state("关机前")

    engine._before_shutdown = before_shutdown
    collect("启动")
    return inbox, collect, deferred_inbox


def _note(problems, msg: str) -> None:
    problems.append(msg)


def _once_more(cfg, log, name: str, budget_s: float, problems: list[str], step):
    """Run one pre-update item; when it gave no verdict, try it once more, as a person would.

    `step(problems)` is the item; the notes it leaves in `problems` are what it
    could not confirm. When there are any, the item runs once more and only the
    second try's notes are kept (a verdict then clears them). No second try when
    the next queue is too close for a whole one: it would start with the program
    still open. Each item closes what it opened before returning (run_maa closes
    MAA on both sides of its wait), so a second launch starts clean.
    """
    n0 = len(problems)
    out = step(problems)
    if len(problems) == n0:
        return out
    try:
        left = _seconds_to_next_queue(cfg.automas_dir, datetime.now(tz=SERVER_TZ))
    except Exception:  # noqa: BLE001 - not knowing the schedule is no reason to risk the queue
        left = 0.0
    if left < budget_s + 60:
        log.info("预更新：%s 没给出结论，离下一个队列只有 %.0f 秒，不再试", name, left)
        return out
    log.info("预更新：%s 没给出结论（%s），再试一次", name, "；".join(problems[n0:]))
    del problems[n0:]
    return step(problems) or out


def _preupdate_maaend(maaend, cfg, notifier, log, problems) -> None:
    """The MaaEnd slot of the pre-update: upgrade it, then clear the two loose ends it leaves behind.

    A separate step because it runs one stretch longer than the other three: a
    new version means AUTO-MAS has to re-read the task table, and the tasks that
    were temporarily switched off while waiting for that version have to be
    switched back on.
    """
    from ark_relay import preupdate  # noqa: PLC0415

    if updated := _once_more(cfg, log, "MaaEnd", preupdate.BUDGET_SECONDS, problems,
                             lambda problems: preupdate.run(maaend, problems=problems,
                                                            state_dir=cfg.state_dir)):
        log.info("预更新：MaaEnd 已更新：%s", updated)
        notifier.send(texts.PREUPDATE,
                      f"MaaEnd 已更新：{updated}")
        # AUTO-MAS preloads MaaEnd's task table into an in-memory cache at
        # boot, and when MaaEnd is upgraded afterwards that cache is not
        # refreshed: on 2026-09-06 upstream renamed SellProduct's definition
        # file, MAS was holding the old table and could not match
        # 「任务完成: 🛒据点交易」, so the whole run was judged a failure and
        # retried twice.
        # The maintainer (AUTO-MAS#573): 「缓存更新逻辑的问题，重启 MAS 就好」.
        # Verified true on this machine, so restart MAS after the upgrade and
        # make it read MaaEnd again.
        log.info("预更新：MaaEnd 换了版本，重启 AUTO-MAS 刷新它的任务表缓存")
        _revive_automas()
        if not ensure_automas(timeout=120):
            _note(problems, "MaaEnd 更新后重启 AUTO-MAS，120 秒内没响应")
    # Tasks the relay once switched off are switched back on by
    # _stage_reenable_maaend, which runs right after the pre-update at every boot.


def _preupdate_okww(cfg, notifier, log, problems) -> None:
    """The OK-WW slot of the pre-update: update first, then re-apply the local patches.

    A separate step because it differs from the other three - its update
    overwrites the whole of src, so "update" and "re-apply the patches" are a
    bound pair, and doing half of it is the same as doing none of it.
    """
    # Until 2026-08-26 okww_patch was missing from this line: line 549 below
    # uses it and raised NameError the moment it was reached, which means
    # **re-applying the patches had never once actually run**.
    # tests/test_undefined_names.py was added for exactly this class of error.
    from ark_relay import okww_patch, preupdate  # noqa: PLC0415

    # OK-WW last: it is the newest of the four and the only one whose
    # update comes from a CNB git mirror rather than MirrorChyan.
    okww = cfg.okww_dir or (Path(cfg.automas_dir).parent / "okww"
                            if cfg.automas_dir else None)
    # OK-WW's auto-update overwrites the whole of src and wipes out the local
    # patches, so they have to be re-applied after every update.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
    if note := _once_more(cfg, log, "OK-WW", preupdate.OKWW_BUDGET_SECONDS, problems,
                          lambda problems: preupdate.run_okww(okww, problems=problems)):
        log.info("预更新：%s", note)
        notifier.send(texts.PREUPDATE, note)
    patch_notes = okww_patch.ensure_patches(okww)
    # Right after the update and before any queue: does each pinned copy still match
    # the source now on disk? Until 10-05 the first to notice was the result check,
    # after the run, as a group alarm (okww_overlay.drift).
    from ark_relay import okww_overlay  # noqa: PLC0415
    if line := okww_overlay.drift_line(okww, cfg.state_dir):
        patch_notes.append(line)
    for note in patch_notes:
        log.info("预更新：%s", note)
    if patch_notes:      # one combined push, not one per patch; the ⚠️ variant to the group
        notifier.send(texts.patches(len(patch_notes), patch_notes),
                      "\n".join(f"· {n}" for n in patch_notes), alert=True)


def _stage_selfcheck(cfg, notifier, log) -> None:
    """Verify every assumption the relay stands on, once, and tell the group about any that fails (selfcheck.py)."""
    from ark_relay import selfcheck  # noqa: PLC0415
    selfcheck.report(cfg, notifier, log)


def _stage_preupdate(cfg, notifier, log) -> None:
    """Do the updates for all four programs inside the boot window (once a day)."""
    # MaaEnd only checks for updates at startup, and when it finds one it
    # downloads it and **restarts its own process** - while AUTO-MAS is watching
    # the pid it launched, so on any day with a new version the first queue run
    # is bound to fail. Hence moving this step into the boot window, so it
    # finishes updating while nobody is waiting on it.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
    if _stop_requested():
        # A stopping process must not start programs it will not live to close.
        log.info("服务正在停止，不做预更新")
        return
    try:
        from ark_relay import plan, preupdate  # noqa: PLC0415

        # Once a day is enough: re-running on every service restart would
        # launch MAA, MaaEnd and OK-WW one by one to check for updates all over
        # again. On 2026-08-31 I deployed three times in one morning, it ran
        # three times, and on the third MAA did not answer within 180 seconds
        # and we reported 「没能确认」.
        _pre_now = datetime.now(tz=SERVER_TZ)
        if (preupdate.wanted_today(cfg.automas_dir)
                and preupdate.should_run(cfg.state_dir, _pre_now)):
            ensure_automas()          # 09-03 01:08: AUTO-MAS was shut down and the pre-update asked for 180s
            maaend = cfg.maaend_dir or _maaend_dir(cfg)
            # Both are pushed, per the standing order: when an auto-update
            # takes effect, say so at once. An earlier version of this block
            # suppressed the MaaEnd notice on the grounds that its beta
            # channel "ships most days" - that was never measured, and the
            # log shows the MaaEnd pre-update had in fact never once run to
            # a verdict. Measured cadence on MAA is one update per ~6 days,
            # which is not a channel anyone learns to tune out. If either
            # ever does become daily noise, coalesce the two into one
            # message rather than going silent.
            maa = plan.script_dir(cfg.automas_dir, "MAA")
            # Everything that could not be confirmed goes into this basket and
            # is then sent as an **alert**. A false "all fine" is worse than an
            # honest failure: nobody goes looking into something that was
            # reported as normal.
            # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
            problems: list[str] = []
            # MAA first: its update is applied by a delegated process at
            # startup, so getting it out of the way is quick and the
            # launch of MaaEnd afterwards is unaffected either way.
            if note := _once_more(cfg, log, "MAA", preupdate.BUDGET_SECONDS, problems,
                                  lambda problems: preupdate.run_maa(maa, problems=problems)):
                log.info("预更新：%s", note)
                notifier.send(texts.PREUPDATE, note)
            _preupdate_maaend(maaend, cfg, notifier, log, problems)
            # AUTO-MAS is asked, not launched - it is already running.
            if note := _once_more(cfg, log, "AUTO-MAS", preupdate.MAS_BUDGET_SECONDS, problems,
                                  lambda problems: preupdate.run_automas(cfg.automas_dir,
                                                                         problems=problems)):
                notifier.send(texts.PREUPDATE, note)
            _preupdate_okww(cfg, notifier, log, problems)
            preupdate.mark_run(cfg.state_dir, _pre_now,
                               clean=not problems)
            if problems:
                # A group alarm, each time. From 10-05 until 2026-10-06 it was said
                # on Server酱 and not alarmed (the user, 10-05 13:07, on stopping at every
                # small hitch: 「几乎就是遇到一点小毛病就停下来报错」); his order of
                # 10-06, every error every time (「不论多少次什么错误都要发」), reverses that. The queue still runs as usual and every program
                # checks for updates itself when it starts; the text says so. The
                # WARNING line comes after the push and is not pushed a second time
                # when the alarm reached the group (errwatch.group_pushed).
                from ark_relay import errwatch  # noqa: PLC0415
                body = "\n".join(f"· {p}" for p in problems)
                title = texts.unconfirmed("预更新", len(problems))
                errs = notifier.send(title, body + texts.preupdate_unconfirmed_tail(), alert=True)
                log.warning("预更新有 %d 项没能确认：\n%s", len(problems), body,
                            extra=errwatch.group_pushed(title, errs, notifier))
    except Exception:
        log.exception("预更新出错，跳过（本轮照旧）")


def _stage_reenable_maaend(cfg, notifier, log) -> None:
    """Switch back on every MaaEnd task the relay once switched off, and check the
    sanity-booster step."""
    # Every boot, outside the pre-update block: on the morning of 09-03 the
    # pre-update was skipped (it had already run overnight) and a step inside it
    # was skipped along with it. gameupdate.maaend_reenable_records logs what it
    # did itself (INFO when switched on, WARNING when it could not).
    try:
        from ark_relay import gameupdate as _gu2  # noqa: PLC0415
        _gu2.maaend_reenable_records(cfg)
    except Exception:
        log.exception("开回 MaaEnd 任务出错")
    # The sanity booster (应急理智加强剂) stays on; a booster step the relay does not
    # know rings the group at every boot that sees it. The user, 2026-10-06, on it:
    # 「那个要一直开着，如果上游maaend改了导致没生效就要报警」 - every time it is seen, he wants the alarm.
    try:
        from ark_relay import gameupdate as _gu3  # noqa: PLC0415
        if shape := _gu3.spmed_check(cfg):
            notifier.send(texts.SPMED_UNRECOGNISED, texts.spmed_unrecognised_body(shape), alert=True)
    except Exception:
        log.exception("检查应急理智加强剂那段出错")
    # Entries for tasks this MaaEnd no longer has are removed, not warned about
    # (the user, 2026-09-09: 「你光报警不去修吗？」). Two independent signals are
    # required before a line is deleted; see mastercfg.prune_maaend_orphans.
    try:
        from ark_relay import mastercfg as _mc  # noqa: PLC0415
        removed, note = _mc.prune_maaend_orphans(cfg.automas_dir, cfg.maaend_dir)
        if removed:
            log.info("开机：%s", note)
            notifier.send(texts.MAAEND_PRUNED, note)
        elif note:
            log.warning("MaaEnd 死条目清理没做：%s", note)
    except Exception:
        log.exception("清理 MaaEnd 死条目出错")
    # Same reasoning one level down: option *values* the new version no longer
    # reads. Left alone, MaaEnd drops them on load and runs the task on its
    # defaults - 2026-09-10 that was 自动采集 with no routes, reported green.
    try:
        from ark_relay import mastercfg as _mc2  # noqa: PLC0415
        changed, note = _mc2.migrate_maaend_options(cfg.automas_dir, cfg.maaend_dir)
        if changed:
            log.info("开机：%s", note)
            notifier.send(texts.MAAEND_MIGRATED, note)
        elif note:
            log.warning("MaaEnd 设置格式迁移没做：%s", note)
    except Exception:
        log.exception("迁移 MaaEnd 设置格式出错")
    # Route lists narrowed for an AUTO-MAS retry round must never survive a boot:
    # the next morning's gathering would walk only yesterday's failed routes.
    try:
        from ark_relay import collect_retry as _cr  # noqa: PLC0415
        if back := _cr.restore_master(cfg):
            log.warning("开机：%s（上次关机前没改回）", back)
    except Exception:
        log.exception("开机改回母本路线出错")
    # Same for the make-up's narrowing (ark_relay/makeup.py): the next morning's
    # MaaEnd must run every task, not just yesterday's failed ones.
    # Not while that make-up is still running (a relay restart in the middle of
    # it, the machine still up): the full master would go back under the run and
    # AUTO-MAS's retries of it would run every task. Its record puts it back
    # (handle._handle).
    try:
        from ark_relay import makeup as _mk  # noqa: PLC0415
        if _mk.maaend_still_running(cfg.state_dir):
            log.info("开机：终末地补跑还在跑，母本等它的记录出来再改回")
        else:
            back, err = _mk.try_restore(cfg, notifier)
            if back:
                log.warning("开机：%s（上次关机前没改回）", back)
            elif err:
                log.warning("开机：补跑改过的母本没能改回（%s）", err)
    except Exception:
        log.exception("开机改回补跑收窄的母本出错")


def _stage_collect_watch(cfg, notifier, log) -> None:
    """Arm the live watch on MaaEnd's log that narrows the gathering routes for a retry."""
    try:
        from ark_relay import collect_watch  # noqa: PLC0415
        collect_watch.start(cfg, notifier)
    except Exception:
        log.exception("挂 MaaEnd 日志监听出错，采集路线收窄这一步不工作")


def _stage_gameupdate(cfg, notifier, log) -> None:
    """Major version update days: register the game clients that need updating."""
    # On major update days, update the game clients too (asked for by the user
    # on 2026-09-02). Once per boot: the morning window is short, only enough
    # for Arknights to install its package or for a launcher to be clicked; the
    # evening run is MAA only, so the large Endfield and Wuthering Waves
    # downloads go here. The budget is however long there is until the next
    # queue.
    try:
        from ark_relay import gameupdate  # noqa: PLC0415
        _gu_now = datetime.now(tz=SERVER_TZ)
        _boot_id = _boot_stamp(_gu_now)
        if gameupdate.should_run(cfg.state_dir, _gu_now, boot_id=_boot_id):
            budget = _seconds_to_next_queue(cfg.automas_dir, _gu_now)
            log.info("游戏更新：开始检查三家客户端（预算 %.0f 秒）", budget)
            notes, gproblems = gameupdate.boot_check(cfg, budget_s=budget, now=_gu_now)
            for n in notes:
                log.info("游戏更新：%s", n)
                notifier.send(texts.GAME_UPDATE, n)
            if gproblems:
                # A group alarm, each time (until 2026-10-06 demoted to Server酱); the
                # WARNING line is not pushed again when the alarm reached the group.
                from ark_relay import errwatch  # noqa: PLC0415
                body = "\n".join(f"· {x}" for x in gproblems)
                title = texts.unconfirmed("游戏更新", len(gproblems))
                errs = notifier.send(title, body, alert=True)
                log.warning("游戏更新有 %d 项没能确认：\n%s", len(gproblems), body,
                            extra=errwatch.group_pushed(title, errs, notifier))
            gameupdate.mark_run(cfg.state_dir, _gu_now, boot_id=_boot_id)
    except Exception:
        log.exception("游戏更新出错，跳过（本轮照旧）")


def _stage_annihilation(engine, notifier, log) -> None:
    """Restore the three once-a-week switches for a new week, and assert them once at boot.

    Annihilation, the weekly garden and the weekly boss share one piece of logic
    and one notification (the user, 2026-09-07: 「逻辑上一致的
    东西就应该强统一」). When any one of them rolls over into a new week, this
    week's state for all three is sent together.
    """
    gates = [("剿灭", engine._annihilation), ("周常乐园", engine._garden),
             ("周本", engine._weeklyboss)]
    rolled: dict[str, str] = {}
    for name, gate in gates:
        if gate is None:
            continue
        try:
            if line := gate.maybe_reopen():
                if hasattr(gate, "enforce") and name != "剿灭":
                    gate.enforce()      # really put it back first, then say it is restored
                rolled[name] = line
        except Exception:
            log.exception("%s 周期检查出错，跳过", name)
    if rolled:
        lines = []
        for name, gate in gates:
            if gate is None:
                continue
            try:
                lines.append(rolled.get(name) or gate.week_line())
            except Exception:
                log.exception("%s 状态读不出来", name)
        notifier.send(texts.NEW_WEEK, "\n".join(lines))

    # Assert the annihilation switch once at startup rather than leaving it
    # to tick(): ticks are driven by file events and alarms, and neither has
    # fired yet on a machine that just booted. By the time the first tick
    # arrives it is usually the queue's own start time, so that round would
    # still pay for the pointless annihilation pass.
    engine._enforce_annihilation()
