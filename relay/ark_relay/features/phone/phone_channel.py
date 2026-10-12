"""The phone channel at the relay's end: what happens when a button is pressed on the phone
(_make_phone_cmd: run it now, or queue it while a script runs and drain the queue after), the
boot backlog of presses, and the long-lived connection with its heartbeat (_start_phone_channel).

Moved out of relay/boot_stages.py (2026-10-11); behaviour unchanged. boot_stages'
_stage_inbox_and_phone starts it; ensure_automas and _stop_requested stay there and are
called through the module, so a test that swaps them on boot_stages still reaches this code.
"""
from __future__ import annotations

import contextlib
import functools
import logging
import os
import threading
import time
from datetime import datetime

import win32event

import boot_stages  # relay/boot_stages.py, which imports this module; names are read at call time

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ

# boot_stages' logger: these lines were always ark.service, and machine checks and tests read them there.
log = logging.getLogger("ark.service")


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


def _machine_check(state_dir, event: str, ctx: dict, notifier, log) -> None:
    """Judge the machine checks listening to `event` (machinecheck.py; the phone ones
    are in ark_relay/features/selfcheck/machinechecks/phone_banners.py). Never breaks the phone path."""
    try:
        from ark_relay.features.selfcheck.machinechecks import phone_banners  # noqa: PLC0415
        phone_banners.fire(state_dir, event, ctx, notifier)
    except Exception:
        log.exception("上机核对（%s）没能做", event)


def _push_farm_trouble(notifier, log) -> None:
    """An echo farm stopped by hand (the phone's stop-farm order, the red button) whose
    wrap-up went wrong: the same group alarm as at the deadline (echofarm.push_manual_trouble)."""
    from ark_relay.features.echofarm import echofarm  # noqa: PLC0415
    try:
        echofarm.push_manual_trouble(notifier)
    except Exception:
        log.exception("刷声骸收工出问题没推出去")


def _phone_execute(apply_command, notifier, log, push_state, receipt,
                   body: dict, action: str, sent, notify: bool, meta: dict | None = None,
                   *, state_dir=None, via: str = "live", queued_at=None) -> None:
    """Apply one order, write its receipt, push the state - live or drained alike.

    `notify` False (an order drained after the run) keeps a success off the
    channels - the receipt is the answer; a failure goes to the group either way.
    `via` / `queued_at` tell the machine check #23 how it got here."""
    from ark_relay.core import engine as _engine_mod  # noqa: PLC0415
    if action == "echo_farm":
        _phone_stamp_sent(body, sent, meta)
    ok, msg = apply_command(body)
    log.info("📱 手机指令 %s：%s", action, msg)
    _push_farm_trouble(notifier, log)
    # Whatever the order changed or started, the next 「is anything running」
    # asks AUTO-MAS afresh: the drain loop's own next check, and the shutdown
    # decision of the same tick, which would otherwise reuse a 「nothing runs」
    # read from up to three seconds before.
    _engine_mod.forget_scripts_cache()
    # The answer goes onto the phone page (state snapshot) - the user reads
    # it where he pressed the button (2026-09-14); a failed order also goes
    # to the group.
    try:
        receipt(action, sent, ok, msg)
    except Exception:
        log.exception("手机指令回执没记下")
    if notify or not ok:
        # A failed order is an error: the group (the user, 2026-10-06: every error, every time),
        # drained after the run too - until 10-06 a queued order that failed was only a receipt.
        notifier.send(texts.CONFIG_CHANGED if ok else texts.CONFIG_FAILED, msg, alert=not ok)
    _machine_check(state_dir, "phone_cmd", {"action": action, "ok": ok, "msg": msg, "receipt": (ok, msg),
                                            "via": via, "queued_at": queued_at, "sent": sent}, notifier, log)
    push_state("改完配置")


def _phone_enqueue(queue, log, queued_receipt, raw: dict, action: str, mid: str, sent) -> None:
    """Put one order on the queue (phone.CmdQueue). While a script runs (`queued_receipt`
    given), a new order - or a new press of the same waiting one - is answered at
    once with a 「排队中」 receipt and a state push (D207)."""
    from ark_relay.features.phone import phone as _phone  # noqa: PLC0415
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
    from ark_relay.features.phone.commands import apply_command  # noqa: PLC0415
    from ark_relay.features.phone import phone as _phone  # noqa: PLC0415

    # Orders that came in while a script was running wait here for the end of
    # the run (phone.CmdQueue). Same state dir the commands themselves use.
    state_dir = cfg_state_dir if cfg_state_dir is not None else os.environ.get("ARK_STATE_DIR", "./ark-state")
    queue = _phone.CmdQueue(state_dir)
    drain_lock = threading.Lock()

    def _receipt(action, sent, ok, msg, queued=False):
        # "sent" beside "at": the page shows both (「HH:MM 发出 · HH:MM 执行」,
        # web data 5238f367), so the text itself stays the plain answer.
        from ark_relay.features.modes import modes as _modes  # noqa: PLC0415
        _modes.add_receipt(cfg_state_dir, action, ok, msg, sent=sent, queued=queued)

    def _queued_receipt(action: str, sent) -> None:
        """D207: the moment an order is queued behind a running script, a receipt says
        so and a state goes out, so the App shows 「排队中」 instead of 「没生效」."""
        try:
            _receipt(action, sent, True, texts.PHONE_QUEUED, queued=True)
        except Exception:
            log.exception("手机指令排队回执没记下")
        push_state("指令排队")

    _execute = functools.partial(_phone_execute, apply_command, notifier, log, push_state, _receipt,
                                 state_dir=state_dir)

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
        order is queued while idle. An order that went through is not pushed: the
        receipt and the state are the answer, on the page where he pressed. One
        that failed goes to the group like a live one (_phone_execute); one that
        expired is a WARNING (errwatch pushes it).
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
                    _machine_check(state_dir, "phone_cmd", {"action": action, "ok": False, "msg": msg,
                                                            "via": "expired", "queued_at": item.get("queued"),
                                                            "sent": sent}, notifier, log)
                    n += 1
                    continue
                log.info("📱 脚本已停，执行排队的手机指令 %s（id %s，%s 排进来）",
                         action, meta.get("ntfy_id") or "?",
                         datetime.fromtimestamp(int(item.get("queued") or 0), tz=SERVER_TZ)
                         .strftime("%H:%M:%S"))
                _execute(body, action, sent, notify=False, meta=meta, via="drained",
                         queued_at=item.get("queued"))
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
            boot_stages.ensure_automas()          # make sure it is alive before reading config
            push_state("手机请求")
            return
        if action == "watch":
            hb.watch()          # the page is open: beat every 30s for the next 10 minutes
            return
        if action == "estop":
            # Red button: it gets pressed precisely while scripts are running,
            # so it must not be blocked by the gate below.
            from ark_relay.features.phone import commands as _cmd  # noqa: PLC0415
            ok, msg = _cmd.estop(state_dir=cfg_state_dir)
            log.warning("🛑 红按钮：%s", msg)
            _push_farm_trouble(notifier, log)
            try:
                receipt(ok, msg)
            except Exception:
                log.exception("红按钮回执没记下")
            # The title has to follow the answer. It used to be 「已停一切」 whatever
            # came back, so the one case that needs the operator - the relay could
            # not get the machine quiet - was pushed to his phone as a success.
            notifier.send(texts.ESTOP if ok else texts.ESTOP_FAILED, msg, alert=not ok)
            _machine_check(state_dir, "estop", {"result": (ok, msg), "reads": dict(_cmd.ESTOP_LAST)},
                           notifier, log)
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
                _machine_check(state_dir, "phone_cmd", {"action": action, "via": "queued", "raw": raw,
                                                        "sent": sent}, notifier, log)
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
    from ark_relay.features.phone.phone import Mailbox, state_cos  # noqa: PLC0415

    # The whole state goes to COS and ntfy only carries a notice (phone.state_cos)
    box = Mailbox(cfg.phone_topic, cfg.phone_pin, cfg.state_dir, cos=state_cos(cfg))
    svc._mailbox = box          # SvcStop uses this to cut the long-lived connection
    # A new process whose 「停止前」 state has not gone out yet: the watchdog's push at a
    # Windows shutdown sends it unless this process's own push did (phone.STOP_PUSHED_FILE).
    from ark_relay.features.phone.phone import clear_stop_pushed  # noqa: PLC0415
    clear_stop_pushed(cfg.state_dir)
    # Every state of this process and whether it reached the phone, plus the
    # heartbeat once it exists: what the machine checks of the phone channel
    # read at the end of a shift (machinechecks/phone_banners.py, #39-#56).
    tally: dict = {"since": time.time(), "n": 0, "ok": 0, "routes": {}, "failed": []}
    beat: list = []

    def _judge_state(why: str, payload, ok: bool) -> None:
        try:
            from ark_relay.features.maintenance import maintenance as _maint  # noqa: PLC0415
            quota = box.quota
            hb_now = beat[0] if beat else None
            ctx = {"state": payload, "why": why, "ok": ok, "error": box.last_error, "tally": tally,
                   "mailbox": box.report() if hasattr(box, "report") else {},
                   "heartbeat": hb_now.cos_report() if hasattr(hb_now, "cos_report") else {},
                   "quota": {"day": quota.day(), "total": quota.total(), "own": quota.own(),
                             "full": quota.full(), "raw": quota.read()},
                   "maintenance": _maint.stats()}
        except Exception:
            log.exception("上机核对（phone_state）没能做")
            return
        # A service stop has 30 s: no network push from here then - a check that did
        # not hold goes through errwatch's queue (on disk, its own push thread).
        _machine_check(cfg.state_dir, "phone_state", ctx, None if why == "停止前" else notifier, log)
        if why == "关机前":
            # The shift is judged; a machine that stays on starts the next one afresh
            # (the heartbeat's and the bulletins' own counts run on: their base moves).
            tally.update(since=time.time(), n=0, ok=0, routes={}, failed=[],
                         base={"heartbeat": ctx["heartbeat"], "maintenance": ctx["maintenance"]})

    def publish_state(why: str) -> bool:
        if not box.enabled:
            return False
        tally["n"] += 1
        stamp = datetime.now(tz=SERVER_TZ).strftime("%H:%M:%S")
        # The state, the send and its log line are phone.send_state, shared with the
        # watchdog's push at a Windows shutdown (app_main.py stop-push).
        from ark_relay.features.phone.phone import send_state  # noqa: PLC0415
        ok, payload, why_not = send_state(box, cfg, why, log)
        if ok:
            tally["ok"] += 1
            route = getattr(box, "last_route", "") or "没说走哪条"
            tally["routes"][route] = tally["routes"].get(route, 0) + 1
        else:
            tally["failed"].append((stamp, why, why_not))
        _judge_state(why, payload, ok)
        return ok

    from ark_relay.features.phone.phone import StatePusher  # noqa: PLC0415
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

    from ark_relay.features.phone.phone import Heartbeat  # noqa: PLC0415
    hb = Heartbeat(box.topic, cfg.state_dir, cos=box.cos)   # its beat on COS too
    beat.append(hb)
    run_phone_cmd = _make_phone_cmd(engine, notifier, log, hb, push_state, cfg.state_dir)
    # Orders queued while a script ran are applied at the top of the first tick
    # that finds nothing running - before that tick's shutdown decision.
    engine._phone_drain = run_phone_cmd.drain

    if not boot_stages.ensure_automas() and not boot_stages._stop_requested():
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
