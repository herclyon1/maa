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


def _revive_automas() -> None:
    """Restart AUTO-MAS through its scheduled task, which owns session 1.

    Three steps, and skipping any of them makes this silently do nothing:

    The Electron shell outlives its own Python backend - the window sits there
    looking healthy while nothing is scheduling runs, which is the exact state
    the machine was found in. So the shell has to go first.

    The task also still counts as running while that shell is alive, and
    `schtasks /run` on an already-running task returns 0x41301 and starts
    nothing. `/end` clears that before `/run` can take.
    """
    for cmd in (
        ["taskkill", "/IM", "AUTO-MAS.exe", "/F"],
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


def ensure_automas(timeout: float = 45) -> bool:
    """Start AUTO-MAS if its API is not answering, then wait for it to come up.

    The user, 2026-09-03: 「MAS 不在的时候你要拉起他，
    不希望见到任何理由开机时检测不到配置，而且要快。」
    """
    import logging  # noqa: PLC0415
    from ark_relay import commands  # noqa: PLC0415
    log = logging.getLogger("ark.service")
    if commands.mas_up():
        return True
    log.warning("AUTO-MAS 接口不在，拉起它")
    _revive_automas()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(3)
        if commands.mas_up():
            log.info("AUTO-MAS 已拉起（%.0f 秒）", timeout - (deadline - time.monotonic()))
            return True
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
        for note in notes:
            log.info("启动：%s", note)
        # One push per startup. It used to push one message per patch, so a
        # single OK-WW update dumped eight of them on the phone at once
        # (the user, 2026-09-06: 「你这个通知一直在轰炸我」).
        if notes:
            notifier.send(texts.patches(len(notes)), "\n".join(f"· {n}" for n in notes))
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
            return
    except Exception:
        log.exception("自更新出错，跳过")
    return False


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
            if errors := notifier.send(title, body):
                log.error("更新通知没发出去: %s", "；".join(errors))
            else:
                log.info("已推送更新通知：%d 个文件", len(files))
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


def _make_phone_cmd(engine, notifier, log, hb, push_state):
    """Build the callback for what happens after a button is pressed on the phone.

    A separate step because it has two entry points: at boot the commands that
    piled up are worked through one by one, and after that the long-lived
    connection calls it again for every command it hears - both have to be the
    same logic.
    """
    from ark_relay.commands import apply_command  # noqa: PLC0415

    def run_phone_cmd(body: dict) -> None:
        """One press from the phone. Refresh only answers with state; everything else really changes config, and notifies the moment it is done."""
        action = str((body or {}).get("action") or "")
        if action == "refresh":
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
            ok, msg = _cmd.estop()
            log.warning("🛑 红按钮：%s", msg)
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
        if engine.scripts_running() and action not in ("skip_shutdown", "debug_mode"):
            # Config changed while a script is running gets clobbered by
            # AUTO-MAS's in-memory copy.
            notifier.send(texts.PHONE_DEFERRED,
                          texts.phone_deferred_body(texts.action_name(action)))
            return
        ok, msg = apply_command(body)
        log.info("📱 手机指令 %s：%s", action, msg)
        # Asked for by the user on 2026-08-31: pressing save has to be followed
        # by a notification saying the change succeeded.
        notifier.send(texts.CONFIG_CHANGED if ok else texts.CONFIG_FAILED, msg)
        push_state("改完配置")

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
    from ark_relay.phone import Mailbox  # noqa: PLC0415

    box = Mailbox(cfg.phone_topic, cfg.phone_pin, cfg.state_dir)
    svc._mailbox = box          # SvcStop uses this to cut the long-lived connection

    def push_state(why: str) -> None:
        if not box.enabled:
            return
        try:
            from ark_relay.phone import state_payload  # noqa: PLC0415
            box.publish(state_payload(cfg, cfg.state_dir))
            log.info("📱 已上报状态到手机（%s）", why)
        except Exception:
            log.warning("状态没能上报到手机（%s）", why, exc_info=True)

    from ark_relay.phone import Heartbeat  # noqa: PLC0415
    hb = Heartbeat(box.topic, cfg.state_dir)
    run_phone_cmd = _make_phone_cmd(engine, notifier, log, hb, push_state)

    ensure_automas()
    push_state("开机")
    if box.enabled:
        for body in box.fetch():
            run_phone_cmd(body)
        threading.Thread(
            target=lambda: box.listen(
                run_phone_cmd,
                lambda: win32event.WaitForSingleObject(svc.stop_event, 0)
                == win32event.WAIT_OBJECT_0),
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


def _preupdate_maaend(maaend, cfg, notifier, log, problems) -> None:
    """The MaaEnd slot of the pre-update: upgrade it, then clear the two loose ends it leaves behind.

    A separate step because it runs one stretch longer than the other three: a
    new version means AUTO-MAS has to re-read the task table, and the tasks that
    were temporarily switched off while waiting for that version have to be
    switched back on.
    """
    from ark_relay import preupdate  # noqa: PLC0415

    if updated := preupdate.run(maaend, problems=problems,
                                state_dir=cfg.state_dir):
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
            _note(problems, "MaaEnd 更新后重启 AUTO-MAS，120 秒内接口没起来")
    try:
        from ark_relay import gameupdate as _gu  # noqa: PLC0415
        if back := _gu.maaend_reenable_if_updated(cfg):
            log.info("预更新：%s", back)
            notifier.send(texts.MAAEND_REENABLED, back)
    except Exception:
        log.exception("开回 MaaEnd 任务出错")


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
    if note := preupdate.run_okww(okww, problems=problems):
        log.info("预更新：%s", note)
        notifier.send(texts.PREUPDATE, note)
    patch_notes = okww_patch.ensure_patches(okww)
    for note in patch_notes:
        log.info("预更新：%s", note)
    if patch_notes:      # one combined push, not one per patch
        notifier.send(texts.patches(len(patch_notes)),
                      "\n".join(f"· {n}" for n in patch_notes))


def _stage_preupdate(cfg, notifier, log) -> None:
    """Do the updates for all four programs inside the boot window (once a day)."""
    # MaaEnd only checks for updates at startup, and when it finds one it
    # downloads it and **restarts its own process** - while AUTO-MAS is watching
    # the pid it launched, so on any day with a new version the first queue run
    # is bound to fail. Hence moving this step into the boot window, so it
    # finishes updating while nobody is waiting on it.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_preupdate」
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
            if note := preupdate.run_maa(maa, problems=problems):
                log.info("预更新：%s", note)
                notifier.send(texts.PREUPDATE, note)
            _preupdate_maaend(maaend, cfg, notifier, log, problems)
            # AUTO-MAS is asked, not launched - it is already running.
            if note := preupdate.run_automas(cfg.automas_dir,
                                             problems=problems):
                notifier.send(texts.PREUPDATE, note)
            _preupdate_okww(cfg, notifier, log, problems)
            preupdate.mark_run(cfg.state_dir, _pre_now,
                               clean=not problems)
            if problems:
                # An alert, not a routine note: a silent pre-update leaves
                # the machine running a version nobody chose.
                body = "\n".join(f"· {p}" for p in problems)
                log.error("预更新有 %d 项没能确认：\n%s", len(problems), body)
                notifier.send(texts.unconfirmed("预更新", len(problems)),
                              body + texts.preupdate_unconfirmed_tail(), alert=True)
    except Exception:
        log.exception("预更新出错，跳过（本轮照旧）")


def _stage_reenable_maaend(cfg, notifier, log) -> None:
    """Switch the temporarily disabled tasks back on once MaaEnd has changed version."""
    # Once MaaEnd changes version, switch the four items disabled on 09-02 back
    # on. Outside the pre-update block, because on the morning of 09-03 the
    # pre-update was skipped (it had already run overnight), this step was
    # skipped along with it, and the four stayed off.
    try:
        from ark_relay import gameupdate as _gu2  # noqa: PLC0415
        for back in (_gu2.maaend_reenable_if_updated(cfg), _gu2.maaend_reenable_next_boot(cfg),
                     _gu2.maaend_reenable_spmed_if_updated(cfg)):
            if back:
                log.info("开机：%s", back)
                notifier.send(texts.MAAEND_REENABLED, back)
    except Exception:
        log.exception("开回 MaaEnd 任务出错")


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
                body = "\n".join(f"· {x}" for x in gproblems)
                log.warning("游戏更新有 %d 项没能确认：\n%s", len(gproblems), body)
                notifier.send(texts.unconfirmed("游戏更新", len(gproblems)), body)
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
