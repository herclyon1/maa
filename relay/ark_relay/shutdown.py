"""关机判定：这一趟到底该不该关，为什么。

从 engine.py 拆出来（2026-09-06，只搬不改）。真正执行关机命令的是
Engine._power_off，这里只判定；每一道门都对应一次真实事故，见各处注释。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import modes, plan
from .config import SERVER_TZ

log = logging.getLogger("ark.shutdown")

# A wake-up checkpoint is judged once, in this window past the hour: open two
# minutes late (a queue may start a moment behind), closed five minutes later.
CHECK_OPEN_MIN, CHECK_CLOSE_MIN = 2, 7
# How far a round's FIRST record may sit from a scheduled time and still count
# as that scheduled round. Only the first record is tested: a queue's later
# scripts legitimately land 40+ minutes in (MAA then MaaEnd), so testing every
# record against this window would call every healthy morning "manual".
MANUAL_WINDOW_MIN = 30


def _idle_checkpoint(eng, now: datetime | None = None) -> bool:
    """True when a wake-up time has passed with nothing scheduled for it.

    The machine is woken at fixed times - 09:00 and 21:30 here - and each
    wake exists to serve the queues at that time. So the morning check asks
    only about 09:00 and the evening check only about 21:30. With 明日方舟
    paused there is no 21:30 queue any more, but the wake still fires; that
    boot has no purpose and should end.

    Two earlier attempts got this wrong and are worth remembering. Keying
    off "up for 25 minutes with every queue time past" would also have
    powered off a machine booted at three in the afternoon to work on. And
    vetoing on an open SSH or ToDesk session was worse than useless: both
    start automatically at boot, so the veto always held and the feature
    never fired at all.
    """
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    if eng._handled_any:
        return False
    scheduled: set[str] = {t for q in plan.schedule(eng.cfg.automas_dir)
                           for t in q.get("times", [])}
    for raw in eng.cfg.check_times.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            hh, mm = (int(x) for x in raw.split(":"))
        except ValueError:
            continue
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # A checkpoint is a moment, not a state. The window opens two
        # minutes after the time - long enough for a queue that starts a
        # little late - and closes five minutes later. Without the closing
        # edge the condition stayed true all evening, so 21:33 and 22:00
        # were still "checking 21:30", and a machine someone had been
        # working on since the afternoon would be powered off the moment
        # the loop next ran.
        if not (due + timedelta(minutes=CHECK_OPEN_MIN)
                <= now <= due + timedelta(minutes=CHECK_CLOSE_MIN)):
            continue
        if due < eng._started_at:
            continue        # this boot was not up for that checkpoint
        if raw in scheduled:
            return False        # this wake has work; the normal path decides
        log.info("%s 这个时间点没有任何排期，本次开机无事可做", raw)
        return True
    return False


def _boot_time(eng, now: datetime | None = None) -> datetime | None:
    """When this machine last booted, or None when it cannot be told.

    Uptime, not the relay's own start time. The relay restarts itself for
    every selfupdate, so `eng._started_at` moves - and an update that ran
    past a queue's time made the new process disqualify itself from
    reporting the missed run, on precisely the boot where something had
    already gone slowly enough to be worth knowing about.

    `GetTickCount64` is milliseconds since boot and never needs a clock
    that agrees with anything. It is Windows-only; anywhere else this
    returns None and the callers fall back to their own start time, which
    is the conservative direction - a missed-run alarm that is skipped
    beats one invented out of a wrong boot time.

    This method was referenced from three places since 2026-08-21 and never
    actually written. It raised AttributeError inside `_check_missed_runs`,
    which the service loop caught and logged, so the relay stayed up while
    silently doing none of the work that follows: no missed-run alarms, no
    daily report, no power-off. See PITFALLS.
    """
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    try:
        import ctypes  # noqa: PLC0415 - Windows only, imported where used
        # 返回值是 64 位；不声明 restype 的话 ctypes 按 32 位 int 截断，
        # 开机超过 24.8 天就变成负数——这台机器一天两开机撞不到，但
        # 「靠巧合正确」不算正确。
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        ms = ctypes.windll.kernel32.GetTickCount64()
    except (AttributeError, OSError):
        return None
    if not ms or ms < 0:
        return None
    return now - timedelta(milliseconds=int(ms))


def _recent_entries(eng, now: datetime) -> list[dict]:
    """Today's ledger plus yesterday's, for queue-completion checks.

    The ledger is keyed by each run's *start* date, so an evening queue
    checked just after midnight has its records in yesterday's file; a
    today-only read makes a finished queue look like it never ran.
    """
    return (eng.state.read_ledger(now.strftime("%Y-%m-%d"))
            + eng.state.read_ledger((now - timedelta(days=1)).strftime("%Y-%m-%d")))


def _unfinished_queues(eng, now: datetime, entries: list[dict]) -> list[str]:
    """Queues that came due recently and are still missing one of their scripts.

    "No game process" is not the same as "the queue is finished". Between
    two scripts in one queue there is a window - MAA has exited, MaaEnd's
    game is still launching - where neither process exists, and the same
    window exists at the very start before the first game comes up. Acting
    in it costs a run: it cost 终末地 the morning of 2026-08-16.
    """
    out: list[str] = []
    for q in plan.recent_due_queues(eng.cfg.automas_dir, now):
        # Only runs started at or after this queue's own time count -
        # otherwise the morning's MaaEnd would satisfy the evening queue.
        ran = {e["script"] for e in entries
               if datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
               >= q["due"] - timedelta(minutes=5)}
        if missing := [k for k in q["kinds"] if k not in ran]:
            out.append(f"队列「{q['name']}」还差 {'、'.join(missing)}")
    return out


def _work_is_done(eng, now: datetime, entries: list[dict]) -> bool:
    """True when this boot's queue has come due and produced all its records.

    The durable version of `_handled_any`, which only knows what *this
    process* watched land. A relay restart after the last run - a
    selfupdate is exactly that - cleared the flag, so nothing was left to
    trigger the shutdown and the machine stayed awake all night. It cost
    2026-08-20 a manual power-off.

    Two requirements, and dropping either one costs a run:

    A queue must actually have come due. "Nothing is unfinished" is
    vacuously true at 08:50 with the 09:00 queue still ahead, and acting on
    it would power the machine off minutes before its own run.

    And the machine must have booted *before* that queue was due - this
    boot has to be the one the queue was scheduled for. Without that test
    the rule reaches a machine somebody powered on at 10:35 to work on: the
    09:00 queue is still inside its two-hour window and its records are
    already in the ledger from the morning, so "everything is finished"
    reads true and the machine switches off under them ten minutes later.
    Uptime is what distinguishes the two, not the relay's start time, which
    every selfupdate resets.

    Residual, deliberately not widened: `recent_due_queues` forgets a queue
    two hours after it was due, so a restart later than that still leaves
    no one to shut down. Widening the window here would also widen the
    "wait for a script that never ran" hold that shares it.
    """
    due = plan.recent_due_queues(eng.cfg.automas_dir, now)
    if not due:
        return False
    booted = eng._boot_time(now)
    if booted is None:
        return False        # cannot prove this boot belongs to the queue
    if booted > min(q["due"] for q in due):
        return False        # somebody powered this on after the queue ran
    return not eng._unfinished_queues(now, entries)


def _round_is_manual(eng, new_entries: list[dict]) -> bool:
    """Whether this round was triggered by hand rather than by the schedule.

    Manual rounds have to be labelled separately (operator order,
    2026-08-20): a scheduled round and a hand-triggered make-up run must
    be distinguishable at a glance, or the operator cannot judge whether
    a given message was supposed to appear at all.

    The test looks only at how far this round's earliest record sits from
    a scheduled time - and the scheduled times are read straight from
    AUTO-MAS's queue config, so changing the schedule needs no matching
    change here. If no schedule can be read it returns False: better to
    leave a round unlabelled than to mislabel a scheduled one as manual.
    """
    times = [t for q in plan.schedule(eng.cfg.automas_dir)
             for t in q.get("times", [])]
    if not times or not new_entries:
        return False
    try:
        first = min(datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                    for e in new_entries)
    except (KeyError, ValueError):
        return False
    for hhmm in times:
        try:
            hh, mm = (int(x) for x in hhmm.split(":"))
        except ValueError:
            continue
        due = first.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if abs((first - due).total_seconds()) <= MANUAL_WINDOW_MIN * 60:
            return False
    return True


def _last_round_manual(eng, now: datetime, entries: list[dict]) -> bool:
    """True when the day's most recent round was triggered by hand.

    A manual round must not count as "the day's work is done". On
    2026-08-21 a hand-triggered MaaEnd test finished at 12:29 and the
    relay promptly powered the machine off - while the operator was in
    the middle of working on it, and hours before the evening queue.

    The round is the group of records that finished close together; two
    hours is comfortably wider than a full queue (MAA then MaaEnd) and
    far narrower than the gap between the morning and evening queues.
    """
    if not entries:
        return False
    try:
        starts = [datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                  for e in entries]
    except (KeyError, ValueError):
        return False
    newest = max(starts)
    # 队列后由中继自己派发的补跑不是「人手动跑的」，跑完该关机
    since = getattr(eng, "_gu_rerun_at", None)
    if since is not None and newest >= since:
        return False
    group = [e for e, t in zip(entries, starts)
             if newest - t <= timedelta(hours=2)]
    return eng._round_is_manual(group)


# ---------- power off, once everything has actually been delivered ----------

def _shutdown_key(eng, now: datetime) -> str:
    """这一次「该关机了」的机会标识。

    用当天流水的条数：一趟队列跑完就会增加，所以「晚班跑完那一次」和
    「早班跑完那一次」是两个不同的机会。调试模式吃掉的是其中一次，
    不是从此不关机。
    """
    day = now.strftime("%Y-%m-%d")
    return f"{day}:{len(eng.state.read_ledger(day))}"


@dataclass(frozen=True)
class Verdict:
    """关不关、为什么、哪道门。`code` 给上层做副作用和去重用，`reason` 给人看。"""

    go: bool
    code: str
    reason: str


def decide(eng, now: datetime) -> Verdict:
    """纯判定：只读状态，不写任何东西。每一道门都对应一次真实事故。

      - 功能没开 -> never
      - 调试模式 / 已被吃掉的这一次机会 -> never（2026-08-31 改判，见下）
      - 已经下过关机令 -> never（2026-08-16 一分钟内报了三次、关了两次）
      - 本次开机还没跑完队列 -> never
      - 开机不够久 -> never（防开机即关机的死循环）
      - 有脚本在跑 / 有告警没推 / 客户端在更新 -> never
      - 最近一轮是手动跑的 -> never（2026-08-21 把正在维护的机器关了）
      - 队列还差脚本 -> never（2026-08-16 两个脚本之间的空档关掉了终末地）
      - 到点了但日报没发 -> never（关机等日报，日报从不静默）
    """
    if not eng.cfg.shutdown_after_run:
        return Verdict(False, "off", "关机功能没开")
    key = eng._shutdown_key(now)
    # 调试模式**吃掉这一次关机机会**而不是每 30 秒推迟一次（用户 2026-08-31：
    # 「我开了调试模式是指把一次队列的中继关机指令跳过，而不是中继一直尝试关机」）。
    # 记标识的副作用在 _maybe_shutdown 里做，这里只判。
    if modes.debug_active(eng.state.dir):
        return Verdict(False, "debug", f"调试模式生效，这一次关机机会（{key}）跳过")
    if modes.shutdown_skipped(eng.state.dir) == key:
        return Verdict(False, "skipped", "这一次关机机会已被调试模式吃掉，人可能正在用电脑")
    if eng._shutdown_issued:
        return Verdict(False, "issued", "关机令已经下过了")
    idle = eng._idle_checkpoint(now)
    entries = eng._recent_entries(now)
    if not (eng._handled_any or eng._work_is_done(now, entries)) and not idle:
        return Verdict(False, "nothing-done", "本次开机还没有跑完任何队列")
    # 开机时长下限防「开机即关机」死循环；空开机检查点例外——它本来就是
    # 对无事可做的开机的快速关机，窗口只有五分钟，循环不起来（2026-08-19）。
    if (not idle and (now - eng._started_at).total_seconds()
            < eng.cfg.shutdown_min_uptime):
        return Verdict(False, "uptime", "开机不够久")
    if eng._scripts_running():
        return Verdict(False, "running", "还有脚本或游戏在跑")
    if eng._pending or eng._recovered:
        return Verdict(False, "pending", "还有告警没推出去")
    if eng._deferred_update_busy():
        return Verdict(False, "updating", "游戏客户端正在更新或重跑")
    if eng._last_round_manual(now, entries):
        return Verdict(False, "manual", "最近一轮是手动触发的，不当作当天收工，不关机")
    if unfinished := eng._unfinished_queues(now, entries):
        return Verdict(False, "unfinished", "；".join(unfinished))
    day = now.strftime("%Y-%m-%d")
    cutoff = eng._report_cutoff(now)   # same source as the report itself
    # 空账本 = 今天本来就没排任何事，没有日报可等；只有真跑过才等日报（2026-08-19 开了一夜）。
    if (now >= cutoff and not eng.state.report_sent(day)
            and eng.state.read_ledger(day)):
        return Verdict(False, "report", "到点该关机了，但日报还没发出去，继续等")
    return Verdict(True, "go", "本轮已处理完毕")


def _maybe_shutdown(eng, now: datetime | None = None) -> bool:
    """判定 + 副作用。判定在 decide()，这里只做判定说了「关」之后的事。"""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    v = decide(eng, now)
    if v.code == "debug":
        key = eng._shutdown_key(now)
        if modes.shutdown_skipped(eng.state.dir) != key:
            modes.mark_shutdown_skipped(eng.state.dir, key)
            log.info("🔧 调试模式：这一次关机已跳过（%s）；"
                     "到期后不会补关，等下一趟队列跑完再判", key)
        return False
    if not v.go:
        if v.code in ("manual", "unfinished"):
            # 原因变了才写一行，免得四十行一样的把要紧的埋掉
            if v.reason != eng._last_wait_note:
                eng._last_wait_note = v.reason
                log.info("不关机：%s", v.reason)
        elif v.code == "report":
            log.info(v.reason)
        return False
    eng._last_wait_note = ""
    day = now.strftime("%Y-%m-%d")
    # 绝不静默关机：当天正式日报还没发（早班跑完就是这种情况）就先补一份
    # 临时查看。定时任务做不了这件事——它得落在「跑完」和「关机」之间，而那个空档会动。
    if (eng.cfg.report_before_shutdown and not eng.state.report_sent(day)
            and not eng.state.interim_sent(day)):
        log.info("关机前补发一份当前进度")
        if eng.send_daily_now(mark=False):
            eng.state.mark_interim_sent(
                day, len(eng.state.read_ledger(day)))
    # 关机前最后拉一次待办：人可能刚在手机上按了「今晚别关机」。只在这一刻拉一次，
    # 拉不到不等于有人喊停。
    if eng._before_shutdown is not None:
        try:
            eng._before_shutdown()
        except Exception:  # noqa: BLE001
            log.warning("关机前的待办检查失败，按原计划关机", exc_info=True)
    # 人按过「这次别关机」（手机指令或桌面 .bat）：吃掉这一次，用完即失效。
    # 必须放在所有门之后、真关之前，否则会被一次「其实还没到时候」白白消耗掉。
    if modes.take_skip(eng.state.dir):
        modes.mark_shutdown_skipped(eng.state.dir, eng._shutdown_key(now))
        log.info("⏸ 有人按了「这次别关机」，本次关机已跳过；"
                 "下一趟队列跑完会正常关机")
        return False
    if not eng._power_off():
        return False
    eng._shutdown_issued = True
    return True
