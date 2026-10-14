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
`_AutomasKeeper` in `ark_relay/features/host/automas_keeper.py` uses
`_revive_automas` as well: the boot steps call the pair five times between them,
and keeping them on the keeper's side would mean this module importing the keeper
while the keeper imports this one. The dependency runs one way only - `service.py`
and `automas_keeper.py` import this module, never the reverse - and the keeper
reaches in for the one name it needs.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ, atomic_write_text, both_clocks

# The module logger, so tests can capture it as <module>.log (scripts/mac/lib/loggernames.py).
log = logging.getLogger("ark.service")

# The directory this file and service.py share. Computed here rather than
# imported from service.py, so the import between the two stays one-way.
HERE = Path(__file__).resolve().parent

AUTOMAS_TASK = "AUTO-MAS_AutoStart"


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
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    return errwatch.going_down()


def _wait_for_api(deadline: float) -> "float | None":
    """Poll the API until `deadline` (monotonic). Returns seconds waited on success,
    None on timeout - or at once, still None, when the service is stopping."""
    from ark_relay.features.phone import commands  # noqa: PLC0415
    t0 = time.monotonic()
    while time.monotonic() < deadline:
        if _stop_requested():
            return None
        time.sleep(3)
        if commands.mas_up():
            return time.monotonic() - t0
    return None


def ensure_automas(timeout: float = 120, grace: float = SHELL_STARTUP_GRACE, notifier=None) -> bool:
    """Start AUTO-MAS if its API is not answering, then wait for it to come up.

    The user, 2026-09-03: 「MAS 不在的时候你要拉起他，
    不希望见到任何理由开机时检测不到配置，而且要快。」

    Order matters: a shell that is already up is given `grace` seconds to open
    its API on its own before anything is killed - killing it earlier is what
    lost the 2026-09-17 evening queue (see _revive_automas). Only a shell that
    is absent, or one that has used up its grace, is force-restarted, and the
    restart itself gets `timeout` seconds.

    AUTO-MAS not answering is INFO when found, and decided by the restart: up
    again -> one WARNING, pushed since 2026-10-10 (why it was not answering is not
    known; daily report only before);
    still not answering after `timeout` -> ERROR, pushed. Given `notifier` (the boot
    caller, phone_channel._start_phone_channel), that ERROR is 「🔌 AUTO-MAS 启动不起来」
    instead: the alarm goes first and the ERROR line is marked as already in the group
    (errwatch.group_pushed), so one fault is one message - until 10-13 it was the 🩺
    push of this line plus the caller's own 🔌 (audit s23 F2).
    selfcheck.daily_lines reads these lines back for the daily report by their
    words: keep 「杀掉重」, 「AUTO-MAS 已…秒）」 and 「秒内…仍不通」.
    """
    import logging  # noqa: PLC0415
    from ark_relay.features.phone import commands  # noqa: PLC0415
    log = logging.getLogger("ark.service")
    if commands.mas_up():
        return True
    why = "它没在运行"
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
        log.info("AUTO-MAS 等了 %.0f 秒接口还是不通，杀掉重拉", grace)
        why = f"窗口开着、等了 {grace:.0f} 秒还没应答"
    if _stop_requested():
        log.info("服务正在停止，不拉 AUTO-MAS")
        return False
    log.info("AUTO-MAS 接口不在，拉起它；起来了报到群里（没应答的原因还没查清），%.0f 秒还不通也报到群里", timeout)
    _revive_automas()
    waited = _wait_for_api(time.monotonic() + timeout)
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    if waited is not None:
        # Why it was not answering is not known: pushed (until 2026-10-10 daily-report-only).
        log.warning("AUTO-MAS 已由中继重新打开（%s，打开后等了 %.0f 秒）", why, waited)
        return True
    if _stop_requested():
        # Not seen to come back before the stop: not recovered, so pushed -
        # unless the stop is the relay's own power-off.
        if errwatch.relay_shutdown_issued():
            log.info("服务正在停止，不再等 AUTO-MAS 起来")
        else:
            log.warning("AUTO-MAS 没在运行（%s），中继打开它之后服务就停了，没等到它起来", why)
        return False
    pushed: dict = {}
    if notifier is not None:
        errs = notifier.send(texts.AUTOMAS_DOWN, texts.automas_boot_down_body(), alert=True)
        pushed = errwatch.group_pushed(texts.AUTOMAS_DOWN, errs, notifier)
    log.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", timeout, extra=pushed)
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


# _seconds_to_next_queue's three numbers. Their one reader that decides anything is
# _once_more (a second pre-update try only when left >= its budget + 60); the game
# update logs the figure and no longer uses it (gameupdate.boot_check).
# The margin kept before the queue: the boot steps after the last pre-update item
# (closing it, the remaining stages, the main loop hooked up) took 2-11 s on 85
# mornings 08-25..10-13 and 33 s once (09-08), measured in relay.log from the OK-WW
# verdict to 「已挂上目录变更通知」; 90 s is that worst case with room.
QUEUE_MARGIN_S = 90.0
# The floor and the no-queue-left figure are derived, not measured: any floor below
# the smallest budget + 60 (preupdate.OKWW_BUDGET_SECONDS 240 -> 300) means "no
# second try", and any figure above the largest (preupdate.MAS_BUDGET_SECONDS 600 ->
# 660) means "time for one"; today has no queue left, so the next is hours away.
QUEUE_FLOOR_S = 120.0
NO_QUEUE_LEFT_S = 3600.0


def _seconds_to_next_queue(automas_dir, now: datetime) -> float:
    """Seconds until today's next queue, less QUEUE_MARGIN_S; when today has none left,
    NO_QUEUE_LEFT_S. A time that runs nothing today (its weekdays, or every item
    sitting the day out: plan.runs_at) is not a queue (232948ba missed this reader)."""
    from ark_relay.core import plan  # noqa: PLC0415
    best = None
    for q in plan.schedule(automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if not plan.runs_at(q, hhmm, due):
                continue
            if due > now and (best is None or due < best):
                best = due
    if best is None:
        return NO_QUEUE_LEFT_S
    return max(QUEUE_FLOOR_S, (best - now).total_seconds() - QUEUE_MARGIN_S)


def _relay_poweroff_live(engine, now=None) -> bool:
    """The relay itself issued the machine power-off, less than ISSUED_STUCK_MIN ago.

    errwatch.relay_shutdown_issued() asks this. Past that window a power-off that did
    not take is shutdown.decide's 「not-down」 and pushed, so nothing is excused any more."""
    if not getattr(engine, "_shutdown_issued", False):
        return False
    at = getattr(engine, "_shutdown_issued_at", None)
    if at is None:
        return True
    from datetime import datetime as _dt, timedelta as _td  # noqa: PLC0415
    from ark_relay.features.shutdown import shutdown as _sd  # noqa: PLC0415
    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
    return (now or _dt.now(tz=SERVER_TZ)) - at < _td(minutes=_sd.ISSUED_STUCK_MIN)


# How long a bad-config exit waits for its alarm to leave. Measured: the 21 🩺 pushes in
# state/alerts 10-06..10-13 reached the group 0-7 s after their record was logged
# (median 3 s, 7 s for the second of a burst); twice the slowest.
BAD_CONFIG_PUSH_WAIT_S = 15.0


def _say_log_file_problem(log) -> None:
    """relay.log that _setup_logging could not create, said now that errwatch
    listens: the relay then runs on stderr only, and the evidence slices, the
    daily self-check and the machine checks have nothing to read."""
    from ark_relay.__main__ import log_file_error  # noqa: PLC0415
    if (exc := log_file_error()) is not None:
        log.warning("relay.log 建不起来（%s: %s），中继这次的日志只到控制台，证据、日报体检和上机核对都读不到",
                    type(exc).__name__, exc)


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

    from ark_relay.core.config import Config  # noqa: PLC0415
    from ark_relay.core import State  # noqa: PLC0415
    from ark_relay.core.engine import Engine  # noqa: PLC0415
    from ark_relay.core.notify import Notifier  # noqa: PLC0415
    from ark_relay.core.transport import LocalSource  # noqa: PLC0415

    log = logging.getLogger("ark.service")
    cfg = Config()
    # The day's tape of what AUTO-MAS, the System log and the information sources
    # answer (selfcheck/tape.py), for the day replay; it never stops or changes the relay.
    from ark_relay.features.selfcheck import tape  # noqa: PLC0415
    tape.install(cfg.state_dir, cfg.automas_dir)
    # From here on every WARNING / ERROR any module logs reaches the group (see
    # errwatch). Installed before the config check: it needs only the notifier and the
    # state folder, and until 10-13 the check's 「配置提醒」 warnings and the reasons of a
    # bad-config exit were logged before it and reached relay.log only (audit s23 F1).
    notifier = Notifier(cfg)
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    built: list = []          # the engine, once there is one: the power-off probe reads it
    errwatch.install(notifier, lambda: bool(built) and _relay_poweroff_live(built[0]),
                     version=lambda: StateStore(cfg.state_dir).get("versions", "code"))
    _say_log_file_problem(log)
    # Each relay-error push uploads today's relay.log first, so the push ends with
    # 「日志：<链接>，出事时刻 HH:MM」 (error_evidence.py, fix bill L) - the bad-config
    # push below too, whose details are in that log.
    from ark_relay.features.evidence import error_evidence  # noqa: PLC0415
    errwatch.set_evidence_uploader(lambda: error_evidence.upload_daily_logs(cfg))
    if problems := cfg.validate():
        # One record, so one group message. Its first line is what the push quotes,
        # in plain words (texts.plain); the problems themselves name settings and go
        # to relay.log on the lines below. Then wait for the push: the caller exits
        # straight after (a push still queued goes out at the next start).
        log.error("中继的设置有 %d 处不对，中继没有启动，哪一处写在中继日志里：\n%s",
                  len(problems), "\n".join(f"· {p}" for p in problems))
        errwatch.drain(BAD_CONFIG_PUSH_WAIT_S)
        return

    engine = Engine(cfg, LocalSource(cfg), State(cfg.state_dir), notifier)
    built.append(engine)
    engine.bootstrap()
    log.info("服务模式启动，监视 %s（变更即处理，兜底 %d 秒）",
             cfg.history_dir, cfg.poll_seconds)
    # The machine checks judge a finished session from relay.log only when it ran
    # code that writes the lines they look for; this line marks such a session
    # (machinechecks/system.py CODE_MARK - keep the words).
    log.info("中继代码版本 v%s", StateStore(cfg.state_dir).get("versions", "code") or "?")
    return log, cfg, notifier, engine


def _stage_flush_copies(notifier, log) -> None:
    """Alarm copies a shutdown cut off before they reached COS go up now (alertlog.py),
    and the ones the Mac did not take are POSTed to it again (macpush.py).

    After the self-update, not in _stage_bootstrap: on a self-update boot the outgoing
    process ran both, then the new one ran them again (relay.log 10-05 21:20:19 /
    21:20:27, audit s23 F3)."""
    try:
        notifier.alert_log().flush_async()
    except Exception:   # the copy never stops the boot
        log.warning("报警抄送补传没能开始", exc_info=True)
    try:
        notifier.mac_push().flush_async()
    except Exception:   # nor does the push to the Mac
        log.warning("报警直送 Mac 补发没能开始", exc_info=True)


def _stage_patch_okww(cfg, notifier, log) -> None:
    """Install the OK-WW overrides once per startup (idempotent).

    Runs after the self-update, in the process that stays: before it, a self-update
    boot sent the same 🩹 note twice, 8 s apart, from the outgoing and the new process
    (relay.log 10-05 21:20:19 / 21:20:27; audit s23 F3)."""
    # Idempotent: it writes nothing at all when they are already in place.
    # Here, not only in the boot pre-update block: after a deploy the machine
    # should already be in its final state, with no "takes effect next boot"
    # loose end.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_patch_okww」
    try:
        okww_at_boot = cfg.okww_dir or (
            Path(cfg.automas_dir).parent / "okww" if cfg.automas_dir else None)
        notes: list[str] = []
        faults: list[str] = []
        # The overrides live in OK-WW's own ok_tasks/ folder; nothing edits its
        # source files (the last source patches and the code that restored them
        # were removed 2026-10-12). Installed here so a deploy leaves the machine in
        # its final state, and read back so an override that did not take is audible.
        # Local import: a module-level one would be evaluated during service
        # installation, when ark_relay may not be on sys.path yet.
        from ark_relay.features.okww_patch import okww_overlay as _overlay  # noqa: PLC0415
        # Each step on its own: one that cannot do its job raises OverlayTrouble,
        # which is a failure by construction (the ⚠️ title, the group), whatever its
        # words - and must not skip the steps after it or the push.
        for step, arg in ((_overlay.install, okww_at_boot),
                          (_overlay.write_master_pointer, cfg.automas_dir)):
            try:
                if line := step(arg):
                    notes.append(line)
            except _overlay.OverlayTrouble as exc:
                notes.append(str(exc))
                faults.append(str(exc))
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
            notifier.send(texts.patches(len(notes), notes, faults), "\n".join(f"· {n}" for n in notes), alert=True)
    except Exception:
        log.exception("启动时贴 OK-WW 补丁失败，服务照常继续")


# The installed relay runs app_main._packaged_selfupdate instead (app_main.py swaps it in); this body runs in tests/test_selfupdate_exit.py.
def _stage_selfupdate(log) -> bool:
    """Pull new code; when something really updated, trigger a restart and return True so the caller exits at once."""
    try:
        from ark_relay.features.selfupdate import selfupdate  # noqa: PLC0415

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
        from ark_relay.features.alarm import handle  # noqa: PLC0415
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
        from ark_relay.features.evidence import evidence  # noqa: PLC0415
        from ark_relay.core import texts  # noqa: PLC0415
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
            # Our work, not his: a red item in the technical log, which the sessions read
            # (scripts/mac/techlog.py red), instead of a Server酱 notice to him. The
            # WARNING above still goes to the group every boot until it is re-pinned.
            from datetime import datetime as _dt  # noqa: PLC0415
            from ark_relay.core import techlog  # noqa: PLC0415
            techlog.add_red(_dt.now(tz=SERVER_TZ).strftime("%Y-%m-%d"), "上游导出代码变了",
                            [f"{texts.EVIDENCE_SOURCE_CHANGED}：{texts.evidence_source_changed_body(new)}"],
                            state_dir=cfg.state_dir)
            told.update({n: evidence.LAST_SEEN.get(n) for n in new})
            try:
                atomic_write_text(seen_file, json.dumps(told, ensure_ascii=False))
            except OSError:
                log.exception("记不下已报过的上游变化，下次开机可能重报")
        elif unreachable:
            # Compared again on the next boot (this stage runs on every boot).
            log.info("上游导出代码核对：%d 个文件这次拉不到，下次开机再比（%s）", len(unreachable),
                     "；".join(f"{n}：{evidence.LAST_ERRORS.get(n, '原因没记下')}" for n in unreachable))
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
        from ark_relay.features.selfupdate import selfupdate  # noqa: PLC0415 - see the block above

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
            from ark_relay.core.statestore import StateStore  # noqa: PLC0415
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
            recorded = False
            if notes:
                try:
                    from ark_relay.features.report import report as _rp  # noqa: PLC0415
                    _rp.remember_change(HERE / "state", notes, str(note.get("version") or ""))
                    recorded = True
                except Exception:
                    log.exception("更新说明没记进当天的日报")
            # 🔄 is log-only (notify.route_of): this writes the 「不推送」 line and returns
            # no errors, so there is no failed-send branch to take any more.
            notifier.send(title, body)
            if recorded:
                log.info("更新说明已记入当天日报（v%s）", note.get("version") or "?")
            elif not notes:
                # Said only when it happened: until 10-13 the line above was logged with
                # no notes and nothing recorded (audit s23 F6).
                log.info("中继已更新到 v%s，这次没有更新说明，当天日报里不记", note.get("version") or "?")
            if notes:
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
            # A failed batch (inbox.receipt_failed: its title is texts.CONFIG_FAILED)
            # goes to the group like a failed phone order; one that went through is
            # log only by its title (notify._LOG_ONLY_PREFIXES).
            notifier.send(messages[0], "\n".join(messages[1:]).strip(),
                          alert=messages[0].startswith(texts.CONFIG_FAILED))
        else:
            log.debug("待办检查（%s）：无新配置（当前 v%s）", reason, version)

    return collect


def _stage_inbox_and_phone(svc, cfg, engine, notifier, log):
    """Todo mailbox plus phone channel. Returns (inbox, collect, deferred_inbox), which the main loop needs."""
    from ark_relay.features.phone.inbox import Inbox  # noqa: PLC0415
    from ark_relay.features.phone import phone_channel  # noqa: PLC0415 - it imports boot_stages

    inbox = Inbox(cfg.state_dir, cfg.inbox_url, automas_dir=cfg.automas_dir)

    # A config command that arrives while a queue is running waits here
    # until every script has stopped, then lands.
    deferred_inbox = [False]
    collect = _make_collect(inbox, engine, notifier, log, deferred_inbox)
    push_state = phone_channel._start_phone_channel(svc, cfg, engine, notifier, log)

    # One last todo fetch and state report before shutdown: someone may have
    # just pressed 「下次跑完不关机」 on their phone, and the state shown there has
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
    still open. Each item closes what it opened before returning, so a second
    launch starts clean.
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
    first = "；".join(problems[n0:])
    log.info("预更新：%s 没给出结论（%s），再试一次", name, first)
    del problems[n0:]
    out = step(problems) or out
    if len(problems) == n0:
        # The second try gave a verdict: the first try's problem fixed itself, one red item.
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        log.warning("预更新：%s 第一次没给出结论，再试一次给出了结论\n%s", name, first,
                    extra=errwatch.recovered())
    return out


def _preupdate_okww(cfg, notifier, log, problems) -> None:
    """The OK-WW slot of the pre-update: update first, then check the overrides still fit.

    A separate step because it differs from the other pre-updates - its update
    replaces the whole of src, so right after it the pinned copies in the overrides
    are compared with the new source (okww_overlay.drift_line).
    """
    from ark_relay.features.preupdate import preupdate  # noqa: PLC0415

    # OK-WW last: it is the newest of the four and the only one whose
    # update comes from a CNB git mirror rather than MirrorChyan.
    okww = cfg.okww_dir or (Path(cfg.automas_dir).parent / "okww"
                            if cfg.automas_dir else None)
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
    if note := _once_more(cfg, log, "OK-WW", preupdate.OKWW_BUDGET_SECONDS, problems,
                          lambda problems: preupdate.run_okww(okww, problems=problems)):
        log.info("预更新：%s", note)
        notifier.send(texts.PREUPDATE, note)
    patch_notes: list[str] = []
    # The pre-update closed OK-WW: put a skipped overlay in place now (a relay
    # restart mid-run left it pending; a WARNING when it still cannot be).
    from ark_relay.features.okww_patch import okww_overlay  # noqa: PLC0415
    okww_overlay.retry_pending("预更新后")
    # Right after the update and before any queue: does each pinned copy still match
    # the source now on disk? Until 10-05 the first to notice was the result check,
    # after the run, as a group alarm (okww_overlay.drift).
    if line := okww_overlay.drift_line(okww, cfg.state_dir):
        patch_notes.append(line)
    for note in patch_notes:
        log.info("预更新：%s", note)
    if patch_notes:      # one combined push, not one per patch; the ⚠️ variant to the group
        notifier.send(texts.patches(len(patch_notes), patch_notes),
                      "\n".join(f"· {n}" for n in patch_notes), alert=True)


def _stage_selfcheck(cfg, notifier, log) -> None:
    """Verify every assumption the relay stands on, once, and tell the group about any that fails (selfcheck.py)."""
    from ark_relay.features.selfcheck import selfcheck  # noqa: PLC0415
    selfcheck.report(cfg, notifier, log)


def _contract_after_update(cfg, notifier, log, version: str) -> None:
    """A new AUTO-MAS just came up: are the settings the relay reads still where it looks?
    (selfcheck.report_contract; the boot self-check ran before this install.)"""
    from ark_relay.features.selfcheck import selfcheck  # noqa: PLC0415
    selfcheck.report_contract(cfg, notifier, version, log)


def _stage_preupdate(cfg, notifier, log) -> None:
    """Do the program updates inside the boot window (once a day).

    MaaEnd and MAA are not among them: since the 2026-10-11 switch-over AUTO-MAS
    updates MaaEnd at the start of a MaaEnd run, and has MAA download its update
    during a run and installs it after each account (items 9a and 9b of the
    hand-over list).
    """
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
    if _stop_requested():
        # A stopping process must not start programs it will not live to close.
        log.info("服务正在停止，不做预更新")
        return
    try:
        from ark_relay.features.preupdate import preupdate  # noqa: PLC0415

        # Once a day is enough: re-running on every service restart would
        # launch the programs one by one to check for updates all over
        # again. On 2026-08-31 I deployed three times in one morning, it ran
        # three times, and on the third MAA did not answer within 180 seconds
        # and we reported 「没能确认」.
        _pre_now = datetime.now(tz=SERVER_TZ)
        if (preupdate.wanted_today(cfg.automas_dir)
                and preupdate.should_run(cfg.state_dir, _pre_now)):
            from ark_relay.features.phone import commands  # noqa: PLC0415
            # Every update that lands is pushed, per the standing order: when an
            # auto-update takes effect, say so at once.
            # Everything that could not be confirmed goes into this basket and
            # is then sent as an **alert**. A false "all fine" is worse than an
            # honest failure: nobody goes looking into something that was
            # reported as normal.
            # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
            problems: list[str] = []
            # AUTO-MAS is asked, not launched: the phone-channel step just before
            # (_stage_inbox_and_phone) has brought it up, or said in the group that it
            # could not. A second ensure_automas() here (09-03 01:08: AUTO-MAS was shut
            # down and the pre-update asked it for 180 s) waited 150 + 120 s again and
            # pushed the same ERROR a second time (audit s23 F2); the item is skipped
            # with one line instead. OK-WW's pre-update does not go through AUTO-MAS.
            if not commands.mas_up():
                log.info("预更新：AUTO-MAS 没有应答，不再等它，它的更新这次不查")
                _note(problems, "AUTO-MAS 没有应答（开机时已经拉过它），它的更新这次没查")
            elif note := _once_more(cfg, log, "AUTO-MAS", preupdate.MAS_BUDGET_SECONDS, problems,
                                    lambda problems: preupdate.run_automas(
                                        cfg.automas_dir, problems=problems,
                                        after_update=lambda version: _contract_after_update(
                                            cfg, notifier, log, version))):
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
                from ark_relay.features.alarm import errwatch  # noqa: PLC0415
                body = "\n".join(f"· {p}" for p in problems)
                title = texts.unconfirmed("预更新", len(problems))
                errs = notifier.send(title, body + texts.preupdate_unconfirmed_tail(), alert=True)
                log.warning("预更新有 %d 项没能确认：\n%s", len(problems), body,
                            extra=errwatch.group_pushed(title, errs, notifier))
    except Exception:
        log.exception("预更新出错，跳过（本轮照旧）")


def _stage_reenable_maaend(cfg, notifier, log) -> None:
    """Check the sanity-booster step and prune master entries for tasks MaaEnd no
    longer has. (Switching back on tasks the relay once switched off went with
    the last such record, audit s18 F5.)"""
    # The sanity booster (应急理智加强剂) stays on; a booster step the relay does not
    # know rings the group at every boot that sees it. The user, 2026-10-06, on it:
    # 「那个要一直开着，如果上游maaend改了导致没生效就要报警」 - every time it is seen, he wants the alarm.
    try:
        from ark_relay.features.gameupdate import gameupdate as _gu3  # noqa: PLC0415
        if shape := _gu3.spmed_check(cfg):
            notifier.send(texts.SPMED_UNRECOGNISED, texts.spmed_unrecognised_body(shape), alert=True)
    except Exception:
        log.exception("检查应急理智加强剂那段出错")
    # Entries for tasks this MaaEnd no longer has are removed (the user,
    # 2026-09-09 03:49: 「另外手机遥控里还有黄色警告，你光报警不去修吗？」; listed in
    # relay/USER-SWITCHES.txt), and every removal is pushed to the group naming
    # them: mastercfg.prune_maaend_orphans logs that WARNING itself under its own
    # title (texts.MAAEND_PRUNED), and its refusals too, so nothing is sent here.
    try:
        from ark_relay.core import mastercfg as _mc  # noqa: PLC0415
        removed, note = _mc.prune_maaend_orphans(cfg.automas_dir, cfg.maaend_dir)
        if removed:
            log.info("开机：%s", note)
        elif note:
            log.info("开机：MaaEnd 死条目清理没做（上面那条 WARNING 已报群）：%s", note)
    except Exception:
        log.exception("清理 MaaEnd 死条目出错")
    # Same reasoning one level down: option *values* the new version no longer
    # reads. Left alone, MaaEnd drops them on load and runs the task on its
    # defaults - 2026-09-10 that was 自动采集 with no routes, reported green.
    try:
        from ark_relay.core import mastercfg as _mc2  # noqa: PLC0415
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
    # Left over and put back here, before anything runs: a fault the relay got
    # over by itself - the daily report only (why: USER-SWITCHES.txt at
    # boot_stages.py:_stage_reenable_maaend). What cannot be put back is pushed.
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    try:
        from ark_relay.features.makeup import collect_retry as _cr  # noqa: PLC0415
        if back := _cr.restore_master(cfg):
            log.warning("开机：%s（上次关机前没改回，这次开机改回了）", back, extra=errwatch.recovered())
    except Exception:
        log.exception("开机改回母本路线出错")
    # Same for the make-up's narrowing (ark_relay/makeup.py): the next morning's
    # MaaEnd must run every task, not just yesterday's failed ones.
    # Not while that make-up is still running (a relay restart in the middle of
    # it, the machine still up): the full master would go back under the run and
    # AUTO-MAS's retries of it would run every task. Its record puts it back
    # (handle._handle).
    try:
        from ark_relay.features.makeup import makeup as _mk  # noqa: PLC0415
        if _mk.maaend_still_running(cfg.state_dir):
            log.info("开机：终末地补跑还在跑，母本等它的记录出来再改回")
        else:
            back, err = _mk.try_restore(cfg, notifier)
            if back:
                log.warning("开机：%s（上次关机前没改回，这次开机改回了）", back, extra=errwatch.recovered())
            elif err:
                log.warning("开机：补跑改过的母本没能改回（%s）", err)
    except Exception:
        log.exception("开机改回补跑改过的母本出错")


def _stage_collect_watch(cfg, notifier, log) -> None:
    """Arm the live watch on MaaEnd's log: records failed gathering routes, puts back a narrowing left by old code."""
    try:
        from ark_relay.features.run import collect_watch  # noqa: PLC0415
        collect_watch.start(cfg, notifier)
    except Exception:
        log.exception("挂 MaaEnd 日志监听出错，采集路线失败记不下来")


def _stage_gameupdate(cfg, notifier, log) -> None:
    """Major version update days: register the game clients that need updating."""
    # On major update days, update the game clients too (asked for by the user
    # on 2026-09-02). Once per boot: the morning window is short, only enough
    # for Arknights to install its package or for a launcher to be clicked; the
    # evening run is MAA only, so the large Endfield and Wuthering Waves
    # downloads go here. The budget is however long there is until the next
    # queue.
    try:
        from ark_relay.features.gameupdate import gameupdate  # noqa: PLC0415
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
                from ark_relay.features.alarm import errwatch  # noqa: PLC0415
                body = "\n".join(f"· {x}" for x in gproblems)
                title = texts.unconfirmed("游戏更新", len(gproblems))
                errs = notifier.send(title, body, alert=True)
                log.warning("游戏更新有 %d 项没能确认：\n%s", len(gproblems), body,
                            extra=errwatch.group_pushed(title, errs, notifier))
                # Did the alarm reach the group (machine check #64: an unreadable
                # Endfield notice is one of these problems)?
                _machinecheck(cfg, notifier, log, "gameupdate", {
                    "game": "", "problems": list(gproblems), "title": title, "body": body,
                    "sent": not errs, "copies": hasattr(notifier, "alert_log")})
            gameupdate.mark_run(cfg.state_dir, _gu_now, boot_id=_boot_id)
    except Exception:
        log.exception("游戏更新出错，跳过（本轮照旧）")


def _stage_stagegate(engine, log) -> None:
    """The stage gate at boot: put back a pull left from an earlier day and check the
    MAA due coming up (within stagegate.BOOT_LEAD_MIN). Runs right after AUTO-MAS
    answers (the pull goes through its API) and before the pre-update, which may take
    the boot window up to 90 s before the queue (stagegate.py, "Where it runs")."""
    try:
        from ark_relay.features.schedule import stagegate  # noqa: PLC0415
        engine._stage_gate(lead_min=stagegate.BOOT_LEAD_MIN)
    except Exception:
        log.exception("开机关卡门出错，跳过（循环里每一轮还会再查）")


def _stage_annihilation(engine, notifier, log) -> None:
    """Restore the once-a-week switches for a new week, and say the week's state once.

    The weekly garden and the weekly boss share one piece of logic and one
    notification with annihilation's status line (the user, 2026-09-07: 「逻辑上一致的
    东西就应该强统一」). When either rolls over into a new week, this week's state
    of all three is sent together. Annihilation itself no longer rolls over here:
    AUTO-MAS keeps its weekly record and switch since the 2026-10-11 hand-over
    (item 13), so it only contributes its status line, read from AUTO-MAS, and
    the alarm when its switch is off (_annihilation_switch_off).
    """
    rolling = [("周常乐园", engine._garden), ("周本", engine._weeklyboss)]
    rolled: dict[str, str] = {}
    for name, gate in rolling:
        if gate is None:
            continue
        try:
            if line := gate.maybe_reopen():
                if hasattr(gate, "enforce"):
                    gate.enforce()      # really put it back first, then say it is restored
                rolled[name] = line
        except Exception:
            log.exception("%s 周期检查出错，跳过", name)
    if rolled:
        lines = []
        for name, gate in [("剿灭", getattr(engine, "_annihilation", None))] + rolling:
            if gate is None:
                continue
            try:
                lines.append(rolled.get(name) or gate.week_line())
            except Exception:
                log.exception("%s 状态读不出来", name)
        notifier.send(texts.NEW_WEEK, "\n".join(lines))
    _annihilation_switch_off(engine, notifier, log)


def _annihilation_switch_off(engine, notifier, log) -> None:
    """Alarm when MAA's annihilation switch is "Close" and this game-week is not done.

    AUTO-MAS keeps the switch and the week record since the 2026-10-11 hand-over
    (item 13) and never turns the switch back on; the relay no longer writes it.
    So a switch left off means no annihilation from now on: one group alarm per
    boot, and the setting is not touched.
    """
    gate = getattr(engine, "_annihilation", None)
    if gate is None:
        return
    try:
        line = gate.switch_off_line()
    except Exception:
        log.exception("剿灭开关读不出来")
        return
    if not line:
        return
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    errs = notifier.send(texts.ANNIHILATION_OFF, line, alert=True)
    log.warning("剿灭：%s", line, extra=errwatch.group_pushed(texts.ANNIHILATION_OFF, errs, notifier))


def _machinecheck(cfg, notifier, log, event: str, ctx: dict) -> None:
    """Hand one event to the machine checks (ark_relay/machinecheck.py). Never raises:
    a broken check must not break the boot (judge logs a broken check as ERROR itself)."""
    if not getattr(cfg, "state_dir", None):
        return                  # nowhere to keep a verdict
    try:
        from ark_relay.features.selfcheck import machinecheck  # noqa: PLC0415
        from ark_relay.core.statestore import StateStore  # noqa: PLC0415
        machinecheck.judge(cfg.state_dir, event, ctx, notifier=notifier,
                           version=str(StateStore(cfg.state_dir).get("versions", "code") or ""))
    except Exception:
        log.exception("上机核对（%s）自己出错，开机照常", event)


def _stage_machinecheck(cfg, notifier, log) -> None:
    """Last boot step: the machine checks that judge what the relay keeps across a
    restart - the session that ended before this one in relay.log (its stop, the
    relay's own power-off, a WMI drop it got over) and the state the boot stages
    leave (machinechecks/system.py). Every FAIL goes to the group."""
    _machinecheck(cfg, notifier, log, "boot",
                  {"cfg": cfg, "log_file": os.environ.get("ARK_LOG_FILE", "")})
