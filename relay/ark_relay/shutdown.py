"""Shutdown decision: should this round power the machine off, and why.

Split out of engine.py (2026-09-06, moved verbatim). The command itself is issued by
Engine._power_off; this module only decides. Every gate here corresponds to a real
incident - see the comment at each one.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import modes, texts, plan, stagegate
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

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:_boot_time」。
    """
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    try:
        import ctypes  # noqa: PLC0415 - Windows only, imported where used
        # The return value is 64-bit; without a declared restype ctypes truncates it
        # to a 32-bit int, and any uptime past 24.8 days turns negative. This machine
        # boots twice a day and never gets there, but "correct by coincidence" is not
        # correct.
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

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:_unfinished_queues」。
    """
    out: list[str] = []
    for q in plan.recent_due_queues(eng.cfg.automas_dir, now):
        # Only runs started at or after this queue's own time count -
        # otherwise the morning's MaaEnd would satisfy the evening queue.
        ran = {e["script"] for e in entries
               if datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
               >= q["due"] - timedelta(minutes=5)}
        # MAA the stage gate pulled from this run is not waited for (stagegate.py).
        if missing := [k for k in q["kinds"] if k not in ran
                       and not (k == "MAA" and stagegate.excused(eng.cfg.state_dir, q["name"], q["due"]))]:
            out.append(f"队列「{q['name']}」还差 {'、'.join(missing)}")
    return out


def _work_is_done(eng, now: datetime, entries: list[dict]) -> bool:
    """True when this boot's queue has come due and produced all its records.

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:_work_is_done」。
    """
    due = plan.recent_due_queues(eng.cfg.automas_dir, now)
    # A shift the stage gate emptied (MAA-only, MAA pulled) has no item left in the
    # queue file, so recent_due_queues skips it; it is still this boot's work, done.
    due = due or stagegate.recent_pulled(eng.cfg.state_dir, now)
    if not due:
        return False
    booted = eng._boot_time(now)
    if booted is None:
        return False        # cannot prove this boot belongs to the queue
    if booted > min(q["due"] for q in due):
        return False        # somebody powered this on after the queue ran
    return not eng._unfinished_queues(now, entries)


def _ran_since_boot(eng, now: datetime, entries: list[dict]) -> bool:
    """True when the ledger holds a run that started after this machine booted.

    `_handled_any` only knows what this process saw. On 2026-10-01 the relay was
    redeployed at 17:41, fourteen minutes after the morning shift closed; the new
    process had handled nothing, the 09:00 queue was long out of
    `_work_is_done`'s two-hour window, and the gate read 「本次开机还没有跑完任何
    队列」 - the machine would have idled until the evening shift. The ledger
    survives a restart; a run that started after boot is work this boot did.
    """
    booted = eng._boot_time(now)
    if booted is None:
        return False        # cannot tell which boot a record belongs to
    for e in entries:
        try:
            if datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ) >= booted:
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return False


def _round_is_manual(eng, new_entries: list[dict]) -> bool:
    """Whether this round was triggered by hand rather than by the schedule.

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:_round_is_manual」。
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


# How far apart two consecutive records may be and still belong to one round:
# a full queue is MAA then MaaEnd then OK-WW back to back, a hand-started run
# comes hours after the morning one.
ROUND_GAP_H = 2
# AUTO-MAS retries a failed script inside the same queue run, but only after
# its own timeout has expired on the failed attempt - 2026-09-19 OK-WW hung at
# 09:34 and was killed and rerun at 11:35. Such a retry belongs to the round
# of the attempt it repeats, however long the timeout was; the bound only
# keeps a hand-run repeat the next afternoon from being chained back.
RETRY_LINK_H = 4
# AUTO-MAS's per-script time limits, minutes (ScriptConfig.json on the machine,
# 2026-10-01: OK-WW RunTimeLimit 120, MaaEnd RunTimeLimit 40, MAA
# RoutineTimeLimit 45), and the slack for AUTO-MAS to notice and move on.
TIMEOUT_LIMIT_MIN = {"OK-WW": 120, "MaaEnd": 40, "MAA": 45}
TIMEOUT_SLACK_MIN = 10
# A single script the relay itself dispatched (commands.run_script: the make-up,
# the re-run after a client update) notes 「脚本 <name>」 in relay-dispatches.json.
# Its first record's start is the script's first log line, which comes after the
# game or emulator is up: allowed this long after the note (and makeup.SLACK
# before it, two clocks on one machine).
RELAY_RUN_START_MIN = 15
RELAY_RUN_EARLY = timedelta(minutes=2)
# The power-off is `shutdown /s /t 60` (Engine._power_off); Windows stops this
# service within a minute or two after the countdown (09-20 10:11:05: WMI dropped
# about a minute after it). A relay still deciding this long after issuing it is on
# a machine that did not go down.
ISSUED_STUCK_MIN = 10

# 1074: "The process <param1> has initiated the power off of computer ... on behalf of
# user <param7>"; 1075: that power-off was aborted (User32, the System log).
_EVT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"


def shutdown_event_xml(window_s: int, ids: "tuple[int, ...]" = (1074, 1075)) -> "list[str] | None":
    """The System log's events `ids` (1074 / 1075 unless asked) of the last `window_s`
    seconds, newest first, as event XML (Windows Event Log API, EvtQuery + EvtRender);
    None when it cannot be read."""
    try:
        import win32evtlog  # noqa: PLC0415
        which = " or ".join(f"EventID={int(i)}" for i in ids)
        q = win32evtlog.EvtQuery(
            "System", win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
            f"*[System[({which}) and TimeCreated[timediff(@SystemTime) <= {int(window_s * 1000)}]]]")
        out = []
        while True:
            got = win32evtlog.EvtNext(q, 10)
            if not got:
                return out
            out += [win32evtlog.EvtRender(e, win32evtlog.EvtRenderEventXml) for e in got]
    except Exception:  # noqa: BLE001 - unknown, not "no event"; the caller says so
        return None


def _stamp(ev) -> "datetime | None":
    from datetime import timezone  # noqa: PLC0415
    t = ev.find(f"{_EVT_NS}System/{_EVT_NS}TimeCreated")
    raw = (t.get("SystemTime") or "") if t is not None else ""
    try:
        return datetime.fromisoformat(raw.rstrip("Z").split(".")[0]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _events(xmls: "list[str]") -> list:
    import xml.etree.ElementTree as ET  # noqa: PLC0415
    out = []
    for x in xmls:
        try:
            ev = ET.fromstring(x)
        except ET.ParseError:
            continue
        eid = (ev.findtext(f"{_EVT_NS}System/{_EVT_NS}EventID") or "").strip()
        data = {d.get("Name") or str(k): (d.text or "").strip()
                for k, d in enumerate(ev.iter(f"{_EVT_NS}Data"))}
        out.append((eid, _stamp(ev), data))
    return out


def cancel_event(xmls: "list[str]") -> "tuple[datetime | None, str] | None":
    """From System log XML, newest first: (UTC time, account) of a 1075 newer than every
    1074 - the power-off was aborted and nothing asked again - else None. Time None when
    its stamp does not parse; account "" when absent.

    2026-10-01 21:48:52 the relay's power-off went out (1074), 21:49:52 a 1075 aborted it
    with input at the machine just before (Kernel-Power 566 InputHid 21:49:36), and the
    machine stayed on until 10-02 04:42. A 1075 holds param1 = computer, param2 = account
    (read on the machine 2026-10-10: `INS` / `INS\\Administrator`). A remote `shutdown /a`
    run as that account is logged the same way as a person at the machine."""
    for eid, when, data in _events(xmls):
        if eid == "1074":
            return None
        if eid == "1075":
            return when, data.get("param2") or data.get("1") or ""
    return None


def cancelled_at(xmls: "list[str]") -> "str | None":
    """cancel_event's time as relay-clock HH:MM:SS ("时刻读不出" on a bad stamp), else None."""
    got = cancel_event(xmls)
    if got is None:
        return None
    return got[0].astimezone(SERVER_TZ).strftime("%H:%M:%S") if got[0] else "时刻读不出"


# No console keyboard / mouse input for this long before the relay powers off.
IN_USE_IDLE_MIN = 15
INPUT_HID = "32"          # Kernel-Power 566 Reason / MonitorReason: the display woke on input
PRESENCE_SLACK_S = 120    # input this long before the abort still counts as 「取消前后」


def input_woke_display(xmls: "list[str]", since: datetime) -> "datetime | None":
    """UTC time of the newest Kernel-Power 566 with Reason 32 (InputHid) at or after `since`.

    10-01 21:49:36: 566 PreviousSessionType 1 -> NextSessionType 0, Reason 32 - the screen
    was off and keyboard or mouse input woke it, 16 s before the abort. It is logged only on
    that transition: on 10-02 the person aborting had the screen on and there is none."""
    for eid, when, data in _events(xmls):
        if eid == "566" and when is not None and when >= since and \
                INPUT_HID in (data.get("Reason"), data.get("MonitorReason")):
            return when
    return None


def console_idle_s() -> "int | None":
    """Seconds since the last keyboard / mouse input in the console session, lower bound
    (`query user` prints whole minutes); None when it cannot be read or nobody is logged on.

    Read on the machine 2026-10-10 as SYSTEM (the relay's account):
    `administrator  console  1  运行中  无  2026/10/10 11:45` - idle under a minute."""
    import subprocess  # noqa: PLC0415
    try:
        r = subprocess.run(["query", "user"], capture_output=True, text=True, encoding="mbcs",
                           errors="replace", timeout=15)
    except Exception:  # noqa: BLE001 - unknown, not "nobody"; the caller says so
        return None
    return parse_console_idle(r.stdout or "")


def parse_console_idle(out: str) -> "int | None":
    """`query user` output -> the console row's idle time in seconds (whole minutes), else None.

    Idle column: digits = minutes, H:MM, D+H:MM; anything else (「无」, ".", "none") is
    input within the last minute. The language of that word is not keyed on."""
    import re  # noqa: PLC0415
    for line in out.splitlines()[1:]:
        cols = line.lstrip(">").split()
        if len(cols) < 5 or cols[1].lower() != "console":
            continue
        idle = cols[4]
        m = re.fullmatch(r"(?:(\d+)\+)?(?:(\d+):)?(\d+)", idle)
        if not m:
            return 0
        d, h, mins = (int(x) if x else 0 for x in m.groups())
        return ((d * 24 + h) * 60 + mins) * 60
    return None


def _round_of_newest(entries: list[dict]) -> list[dict]:
    """The records that make up the round the newest record belongs to.

    Walk back from the newest record: the previous one is part of the same
    round when this one starts within ROUND_GAP_H of its end, or when this one
    is a retry of it (same script and user, the previous one failed, within
    RETRY_LINK_H). The old rule - everything that started within two hours of
    the newest - cut today's queue in half whenever a retry came late: on
    2026-09-19 the tail (OK-WW retry 11:35, MaaEnd 11:42-12:09) was judged by
    its own first record, 11:35 is not 09:00, so the round read as "started by
    hand" and the machine stayed on all day.
    """
    def stamp(e: dict, key: str) -> datetime:
        return datetime.fromisoformat(e[key]).astimezone(SERVER_TZ)
    ordered = sorted(entries, key=lambda e: stamp(e, "started"))
    group = [ordered[-1]]
    for prev in reversed(ordered[:-1]):
        cur = group[0]
        cur_start = stamp(cur, "started")
        prev_end = stamp(prev, "finished") if prev.get("finished") else stamp(prev, "started")
        gap = cur_start - prev_end
        same_script = (prev.get("script") == cur.get("script")
                       and prev.get("user") == cur.get("user"))
        retry = same_script and not prev.get("ok") and gap <= timedelta(hours=RETRY_LINK_H)
        # A timed-out record's 「finished」 can be its log's last line, not the
        # moment AUTO-MAS killed it: 2026-10-01 OK-WW's third attempt reads
        # 13:21-13:22, AUTO-MAS ended it at 15:23 and moved straight on to MaaEnd
        # (15:24). The gap looked like 2 h 02 min, the round was cut there, and
        # the shift read as started by hand. What starts before AUTO-MAS's own
        # limit for that script could have run out (+ TIMEOUT_SLACK_MIN) is the
        # same round; anything later - a hand-started re-run - is not.
        timed_out = not prev.get("ok") and any(
            "超时" in str(w) for w in list(prev.get("failed_tasks") or [])
            + [str((prev.get("raw") or {}).get("general_result") or "")])
        moved_on = False
        if timed_out and (limit := TIMEOUT_LIMIT_MIN.get(str(prev.get("script")))):
            # OK-WW's and MAA's limits run from the start; MaaEnd's from its last
            # log line (15:30:03 -> 16:10:00 and 09-28 11:22:10 -> 12:02:11).
            anchor = prev_end if prev.get("script") == "MaaEnd" else stamp(prev, "started")
            moved_on = cur_start <= anchor + timedelta(minutes=limit + TIMEOUT_SLACK_MIN)
        if gap <= timedelta(hours=ROUND_GAP_H) or retry or moved_on:
            group.insert(0, prev)
        else:
            break
    return group


def _last_round_manual(eng, now: datetime, entries: list[dict]) -> bool:
    """True when the day's most recent round was triggered by hand.

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:_last_round_manual」。
    """
    if not entries:
        return False
    try:
        starts = [datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                  for e in entries]
    except (KeyError, ValueError):
        return False
    newest = max(starts)
    # A catch-up run the relay itself dispatched after the queue is not "a human
    # ran it by hand"; when it finishes, the machine should power off
    since = getattr(eng, "_gu_rerun_at", None)
    if since is not None and newest >= since:
        return False
    try:
        group = _round_of_newest(entries)
    except (KeyError, ValueError, TypeError):
        return False
    if _relay_dispatched(eng, group):
        return False
    return eng._round_is_manual(group)


def _relay_dispatched(eng, group: list[dict]) -> bool:
    """The round opens with a script the relay dispatched itself (run_script's note).

    The make-up (makeup.py) waits for an idle queue and can start hours after
    it - debug mode, a long update - beyond what _round_of_newest chains to the
    scheduled round; read by the schedule alone it would be a hand-started round
    and the machine would stay on for the rest of the day. A queue started from
    the phone (「队列 …」) is not matched here and keeps its old reading."""
    from . import trigger  # noqa: PLC0415
    try:
        first = min(group, key=lambda e: datetime.fromisoformat(e["started"]))
        start = datetime.fromisoformat(first["started"]).astimezone(SERVER_TZ)
    except (KeyError, ValueError, TypeError):
        return False
    want = f"脚本 {first.get('script')}"
    for d in trigger._read_dispatches(getattr(getattr(eng, "cfg", None), "state_dir", None)):
        if str(d.get("what") or "") != want:
            continue
        try:
            at = datetime.fromisoformat(str(d.get("at")))
        except ValueError:
            continue
        at = (at if at.tzinfo else at.replace(tzinfo=SERVER_TZ)).astimezone(SERVER_TZ)
        if at - RELAY_RUN_EARLY <= start <= at + timedelta(minutes=RELAY_RUN_START_MIN):
            return True
    return False


# ---------- power off, once everything has actually been delivered ----------

def _shutdown_key(eng, now: datetime) -> str:
    """Identifier for this one "time to power off" opportunity.

    It is the number of ledger entries for the day: the count grows every time a queue
    finishes, so "the one after the evening shift" and "the one after the morning
    shift" are two different opportunities. Debug mode eats one of them; it does not
    stop the machine powering off from then on.
    """
    day = now.strftime("%Y-%m-%d")
    return f"{day}:{len(eng.state.read_ledger(day))}"


@dataclass(frozen=True)
class Verdict:
    """Power off or not, why, and which gate. `code` drives the caller's side effects
    and de-duplication; `reason` is what a human reads.
    """

    go: bool
    code: str
    reason: str


def _cancel_verdict(at: datetime, now: datetime, xmls: "list[str]", when, account: str) -> Verdict:
    """An aborted power-off: 「cancelled」 when someone was at the machine around the abort,
    「cancelled-unseen」 (pushed) when nothing shows anyone.

    Someone = keyboard / mouse input woke the display after the command (566 InputHid), or
    the console session's last input is at or after PRESENCE_SLACK_S before the abort
    (`query user`, read once, at ISSUED_STUCK_MIN). 10-02 21:49:08 and 22:58:12 were
    aborted 7 s after the command by `shutdown -a` typed in the Run box of the logged-on
    Administrator (its RunMRU; Windows Terminal started 0.4 s before each 1075) with no 566
    - the screen was already on - so the event log alone cannot tell; the idle time can."""
    clock = when.astimezone(SERVER_TZ).strftime("%H:%M:%S") if when else "时刻读不出"
    who = account or "读不出的账户"
    head = f"关机命令 {at:%H:%M} 发出后，{clock} 被 {who} 取消了（系统事件 1075）"
    woke = input_woke_display(xmls, at)
    if woke is not None:
        return Verdict(False, "cancelled", f"{head}，{woke.astimezone(SERVER_TZ):%H:%M:%S} 有键鼠操作唤醒屏幕，"
                                           "有人在用这台电脑，中继不会再自己关机")
    idle = console_idle_s()
    if idle is not None and when is not None and \
            now - timedelta(seconds=idle + 60) >= when - timedelta(seconds=PRESENCE_SLACK_S):
        return Verdict(False, "cancelled", f"{head}，取消前后这台电脑有键鼠操作，有人在用，中继不会再自己关机")
    seen = ("读不到这台电脑有没有键鼠操作" if idle is None or when is None
            else "取消前后这台电脑没有键鼠操作，查不出是谁取消的（远程下命令取消也记在同一个账户下）")
    return Verdict(False, "cancelled-unseen", f"{head}，{seen}，中继不会再自己关机")


def decide(eng, now: datetime) -> Verdict:
    """Pure decision: reads state, writes nothing. Every gate maps to a real incident.

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:decide」。
    """
    if not eng.cfg.shutdown_after_run:
        return Verdict(False, "off", "关机功能没开")
    key = eng._shutdown_key(now)
    # Debug mode **eats this one shutdown opportunity** rather than deferring it
    # every 30 seconds (the user, 2026-08-31: 「我开了调试模式是指把一次队列的中继
    # 关机指令跳过，而不是中继一直尝试关机」). Recording the key is a side effect and
    # happens in _maybe_shutdown; this function only decides.
    if modes.debug_active(eng.state.dir):
        return Verdict(False, "debug", "调试模式开着，这一次关机跳过")
    if modes.shutdown_skipped(eng.state.dir) == key:
        return Verdict(False, "skipped",
                       "这一次关机已经跳过了（调试模式，或者手机上点了「下次跑完不关机」）")
    if eng._shutdown_issued:
        # A power-off that did not take: the command went out ISSUED_STUCK_MIN or
        # more ago and this process is still deciding, so the machine is still up.
        # Until 2026-10-06 that read 「issued」 for good and nothing was said.
        at = getattr(eng, "_shutdown_issued_at", None)
        if at is not None and now - at >= timedelta(minutes=ISSUED_STUCK_MIN):
            # Why is it still up? A 1075 after the command means the power-off was aborted
            # (see cancel_event) - not a power-off that failed. Aborted with someone using
            # the machine (_cancel_verdict) is 「cancelled」, daily report only (_note_cancel);
            # aborted with no sign of anyone is 「cancelled-unseen」 and 「not-down」, pushed.
            # Unreadable log: the not-down line as before.
            seen = getattr(eng, "_cancel_verdict", None)
            if seen and seen[0] == at:
                return seen[1]            # one reading per power-off: the text stays the same tick to tick
            xmls = shutdown_event_xml(int((now - at).total_seconds()) + 120, (1074, 1075, 566))
            got = cancel_event(xmls) if xmls is not None else None
            if got is not None:
                v = _cancel_verdict(at, now, xmls, *got)
                eng._cancel_verdict = (at, v)
                return v
            return Verdict(False, "not-down", f"关机命令 {at:%H:%M} 就发出去了，过了 {ISSUED_STUCK_MIN} 分钟机器还开着，"
                                              "没有关下去")
        # Not a reason the machine stays on - it is the opposite. Worded as
        # 「关机令已经下过了」 it read like someone had ordered it to stay awake.
        return Verdict(False, "issued", "关机命令已经发出去了，机器正在关")
    idle = eng._idle_checkpoint(now)
    entries = eng._recent_entries(now)
    if (not (eng._handled_any or eng._work_is_done(now, entries)
             or _ran_since_boot(eng, now, entries)) and not idle):
        return Verdict(False, "nothing-done", "本次开机还没有跑完任何队列")
    # The minimum-uptime floor guards against a "boot, power off at once" loop. The
    # idle checkpoint is exempt: it exists precisely to shut down a boot with nothing
    # to do, its window is only five minutes, and it cannot loop (2026-08-19).
    if (not idle and (now - eng._started_at).total_seconds()
            < eng.cfg.shutdown_min_uptime):
        return Verdict(False, "uptime", "开机不够久")
    # A make-up run the relay dispatched itself (makeup.py) is not the machine
    # being stuck: answered as 「running」 it pushed 「今晚不关机」 the first time
    # an evening make-up ran past the report cutoff.
    from . import makeup  # noqa: PLC0415
    if going := makeup.in_flight(eng.cfg.state_dir, now):
        return Verdict(False, "makeup", f"{'、'.join(going)} 正在补跑")
    if eng._scripts_running():
        return Verdict(False, "running", "还有脚本或游戏在跑")
    # A farm is a promise to keep going until a stated time. 「还有脚本在跑」 covers
    # it only while OK-WW is actually up; when the character dies OK-WW stops and the
    # relay takes up to three minutes to put it back, and a shutdown landing in that
    # window would end the night's farming without a word.
    from . import echofarm  # noqa: PLC0415 - avoids an import cycle
    if rec := echofarm.current(eng.cfg.state_dir):
        return Verdict(False, "farming",
                       f"正在刷{rec.get('name') or '声骸'}，刷到 {rec.get('until')} 才收工")
    # A held MAA / MaaEnd failure whose make-up is still to come is not an alarm
    # waiting to go out (makeup.py): counting it here kept the decision at
    # 「还有告警没推出去」 for good, and after the cutoff that read as stuck and
    # pushed 「今晚不关机」 to the group. The make-up gate further down holds it.
    held = [r for r in eng._pending.values() if not makeup.holding(eng, r, now)]
    if held or eng._recovered:
        return Verdict(False, "pending", "还有告警没推出去")
    if eng._deferred_update_busy():
        return Verdict(False, "updating", "游戏客户端正在更新或重跑")
    if eng._last_round_manual(now, entries):
        return Verdict(False, "manual", "最近一轮是手动触发的，不当作当天收工，不关机")
    if unfinished := eng._unfinished_queues(now, entries):
        return Verdict(False, "unfinished", "；".join(unfinished))
    # After every gate that means "the queue is not idle": by now the make-up step
    # (engine.tick, before this one) can dispatch, and does. Not a stuck code: it
    # clears itself once the make-up's record lands or it goes stale.
    if waiting := makeup.waiting(eng, now):
        return Verdict(False, "makeup", f"{'、'.join(waiting)} 补跑还没完")
    day = now.strftime("%Y-%m-%d")
    cutoff = eng._report_cutoff(now)   # same source as the report itself
    # An empty ledger means nothing was scheduled today, so there is no daily report
    # to wait for; wait only when something actually ran (2026-08-19: up all night).
    if (now >= cutoff and not eng.state.report_sent(day)
            and eng.state.read_ledger(day)):
        return Verdict(False, "report", "到点该关机了，但日报还没发出去，继续等")
    # Someone is using the machine: 2026-10-10 17:31 (Beijing) the relay was about to
    # power off on schedule while `query user` showed console input within the minute;
    # only a skip order stopped it. Until then nothing looked before the command, only
    # after an abort (_cancel_verdict). Unreadable idle time decides nothing, so the
    # machine is never kept on for good by a probe that fails.
    if (idle_s := console_idle_s()) is not None and idle_s < IN_USE_IDLE_MIN * 60:
        ago = "1 分钟内" if idle_s < 60 else f"{idle_s // 60} 分钟前"
        return Verdict(False, "in-use", f"有人在用这台电脑（{ago}还有键鼠操作），等没人用满 {IN_USE_IDLE_MIN} 分钟再关")
    return Verdict(True, "go", "本轮已处理完毕")


# The one verdict that is not pushed: the relay's own power-off, under way (「issued」).
# Every other reason the machine stays on past its moment goes to the group, once
# per reason text a day. Until 2026-10-06 a list of seven 「stuck」 codes was pushed
# and the rest (off, debug, skipped, uptime, makeup, nothing-done, report) were
# kept out, each with a reason a session had written next to the list; the user's
# order that day, relayed by the operator: only the planned power-off the relay
# itself started may skip the group, every other code pushes. A power-off that
# did not take (「not-down」) is pushed as before.
RELAY_POWER_OFF = "issued"


def _note_cancel(eng, now: datetime, v) -> None:
    """List an aborted power-off in the next daily report that has not gone out yet."""
    from . import report  # noqa: PLC0415
    day = now.strftime("%Y-%m-%d")
    try:
        if eng.state.report_sent(day):
            day = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        report.remember_cancel(eng.state.dir, day, f"· {now:%m-%d} {v.reason}")
        log.info("关机被取消，记进 %s 的日报，不进群：%s", day, v.reason)
    except Exception:
        log.warning("关机被取消这条没记进日报", exc_info=True)


def _note_in_use(eng, now: datetime, v) -> None:
    """List, once per shutdown opportunity, that the power-off waited for someone using the machine."""
    from . import report  # noqa: PLC0415
    try:
        mark = f"in-use:{eng._shutdown_key(now)}"
        if eng.state.store.get("marks", mark):
            return
        eng.state.store.set("marks", mark, True)
        day = now.strftime("%Y-%m-%d")
        if eng.state.report_sent(day):
            day = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        line = f"· {now:%m-%d %H:%M} 到点该关机，但有人在用这台电脑，中继等没人用满 {IN_USE_IDLE_MIN} 分钟再关"
        report.remember_cancel(eng.state.dir, day, line)
        log.info("有人在用这台电脑，先不关机，记进 %s 的日报，不进群：%s", day, v.reason)
    except Exception:
        log.warning("「有人在用、先不关机」这条没记进日报", exc_info=True)


def _say_if_moment_passed(eng, now: datetime, v) -> None:
    """Push when the moment to shut down has passed and the machine did not, once
    for each reason it stays on.

    09-03 and 09-04 the machine stayed on all night and he found out the next
    day. The decision itself is event-driven (it runs whenever anything lands);
    this only adds a message the first time the cutoff is behind us and the
    machine is still on - no polling. The same message re-checked
    tick after tick is one fault; a different reason later the same evening is
    news, and goes out too (until 2026-10-06 only the day's first one did: the
    message says 「直到这个原因消失」, and when that reason went and another one
    kept the machine on, he was not told). A power-off that did not take (「not-down」)
    does not wait for the cutoff: its moment was the command, and nor does one aborted
    with no sign of anyone at the machine (「cancelled-unseen」). One aborted while someone
    was using the machine (「cancelled」, _cancel_verdict) is daily report only (_note_cancel).
    Every other verdict but the relay's own power-off in progress is pushed (see
    RELAY_POWER_OFF; until 2026-10-06 only seven 「stuck」 codes were).
    """
    if v.code == RELAY_POWER_OFF:
        return
    if v.code == "cancelled":
        # Someone aborted the power-off to use the machine: a normal state, daily report only.
        _note_cancel(eng, now, v)
        return
    if v.code == "in-use":
        # Someone is using the machine, so it is not powered off yet: a normal state, daily report only.
        _note_in_use(eng, now, v)
        return
    try:
        if v.code not in ("not-down", "cancelled-unseen") and now < eng._report_cutoff(now):
            return
        day = now.strftime("%Y-%m-%d")
        key = f"alerted:{day}"
        done = list(eng.state.store.get("marks", key) or [])
        text = f"到点了但没关机：{v.reason}。机器会一直开着，直到这个原因消失或者你来处理。"
        # one fault, one push: one message per reason the machine stays on (its exact text), re-checked every tick
        if f"no-shutdown|{text}" in done:
            return
        eng.state.store.set("marks", key, done + [f"no-shutdown|{text}"])
        eng.notifier.send(texts.NO_SHUTDOWN, text, alert=True)
    except Exception:
        log.warning("「今晚不关机」这条没推出去", exc_info=True)


def _maybe_shutdown(eng, now: datetime | None = None) -> bool:
    """Decision plus side effects. decide() judges; this does what follows a "go"."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    v = decide(eng, now)
    if v.code == "debug":
        # Debug mode eats this one opportunity (decide). It no longer leaves before
        # the 「今晚不关机」 push: until 2026-10-06 it returned here and the group
        # never heard that the machine stayed on for it; the user's order that day,
        # relayed by the operator, is that only the relay's own power-off skips it.
        key = eng._shutdown_key(now)
        if modes.shutdown_skipped(eng.state.dir) != key:
            modes.mark_shutdown_skipped(eng.state.dir, key)
            log.info("🔧 调试模式：这一次关机已跳过（%s）；"
                     "到期后不会补关，等下一趟队列跑完再判", key)
    if not v.go:
        # One line whenever the reason changes, for every reason - not just three
        # of them. The other eight were silent, and three of those (running /
        # pending / updating) are the ones that keep the machine on all night.
        if v.reason != eng._last_wait_note:
            eng._last_wait_note = v.reason
            log.info("不关机：%s", v.reason)
        _say_if_moment_passed(eng, now, v)
        return False
    eng._last_wait_note = ""
    # The queue is idle and nothing else holds the machine: this is the one
    # moment to re-run the gathering routes that failed today, before the
    # power goes. It runs at most once a day and returns False when there is
    # nothing to retry, so the normal path below is untouched on ordinary days.
    from . import collect_retry  # noqa: PLC0415
    if collect_retry.maybe_run(eng, now):
        log.info("补跑刚做完，这一轮关机判断从头再来")
        return False
    day = now.strftime("%Y-%m-%d")
    # Never power off silently: if the day's real report has not gone out yet (the
    # case after the morning shift), send an interim view first. A scheduled task
    # cannot do this - it would have to land between "finished" and "power off", and
    # that gap moves.
    if (eng.cfg.report_before_shutdown and not eng.state.report_sent(day)
            and not eng.state.interim_sent(day)):
        log.info("关机前补发一份当前进度")
        if eng.send_daily_now(mark=False):
            eng.state.mark_interim_sent(
                day, len(eng.state.read_ledger(day)))
    # One last pull of pending orders before powering off: someone may have just
    # pressed "don't shut down tonight" on the phone. Pull once, at this moment only;
    # a failed pull does not mean somebody called a halt.
    if eng._before_shutdown is not None:
        try:
            eng._before_shutdown()
        except Exception:
            log.warning("关机前的待办检查失败，按原计划关机", exc_info=True)
    # Somebody pressed "skip this shutdown" (phone order or desktop .bat): it eats
    # this one occasion and then expires. It must sit after every gate and before the
    # actual power off, or a round that was not ready to shut down anyway would burn
    # it for nothing.
    if modes.take_skip(eng.state.dir):
        modes.mark_shutdown_skipped(eng.state.dir, eng._shutdown_key(now))
        log.info("⏸ 有人按了「这次别关机」，本次关机已跳过；"
                 "下一趟队列跑完会正常关机")
        return False
    # The final upload of today's relay.log before the power goes (error_evidence.py):
    # the error-path uploads throttle to one a minute, so this is the definitive
    # copy. A failed upload must not stop the shutdown - it is daily-report-only.
    from . import errwatch as _errwatch  # noqa: PLC0415
    try:
        from . import error_evidence  # noqa: PLC0415
        _up = error_evidence.upload_daily_logs(eng.cfg, force=True)
    except Exception:  # noqa: BLE001 - an evidence problem never delays the power-off
        _up = {"errors": ["upload raised"]}
    for _e in (_up or {}).get("errors") or []:
        log.warning("关机前证据上传失败：%s", _e, extra=_errwatch.recovered())
    if not eng._power_off():
        return False
    eng._shutdown_issued = True
    eng._shutdown_issued_at = now      # decide: still up ISSUED_STUCK_MIN later is 「not-down」
    _ISSUED[0] = eng                   # abort_countdown: a phone order can still cancel it
    # From here the machine is going down: services and COM links drop as
    # Windows tears them down. Those are not faults - 09-20 10:11:05,
    # 09-21 11:33, 09-22 10:02 each logged "进程启动事件监听中断" as ERROR about
    # a minute after this point and the daily health check counted them.
    from . import errwatch  # noqa: PLC0415
    errwatch.mark_stopping()
    return True


# ---------- 「别关机」 pressed while the 60-second countdown is already running ----------
# The engine whose _power_off was accepted, so a phone order (commands.apply_command,
# which has no engine) can reach the countdown. 2026-10-09 22:42 the user pressed
# 「别关机」 inside the countdown; the order only stored "skip the next one" and
# Windows powered off at 22:43 anyway.
_ISSUED: list = [None]
NO_SHUTDOWN_IN_PROGRESS = 1116     # shutdown /a: ERROR_NO_SHUTDOWN_IN_PROGRESS


def abort_countdown(now: datetime | None = None) -> tuple[str, str]:
    """Cancel the relay's own power-off if its countdown is still running.

    Returns (outcome, text): "aborted" - cancelled, this shutdown opportunity is
    marked as skipped so the next 30-second round does not issue it again, and
    nothing is left over for tomorrow; "none" - no countdown of ours is running
    (never issued, or Windows answered 1116), the caller stores the flag as before;
    "failed" - `shutdown /a` was refused, the machine is still going down.
    """
    eng = _ISSUED[0]
    if eng is None or not getattr(eng, "_shutdown_issued", False):
        return "none", ""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    rc = eng._abort_power_off()
    if rc == NO_SHUTDOWN_IN_PROGRESS:
        log.info("收到「别关机」：系统里已经没有关机倒计时（退出码 1116），按「下次不关机」记下")
        return "none", ""
    if rc != 0:
        log.error("收到「别关机」，取消关机倒计时失败（退出码 %s），机器还会关", rc)
        return "failed", f"取消关机失败（退出码 {rc}），机器还会关"
    from . import errwatch  # noqa: PLC0415
    # The opportunity is the one the power-off was issued for, keyed at that
    # moment - not "now", which may be past midnight or after another record.
    key = eng._shutdown_key(getattr(eng, "_shutdown_issued_at", None) or now)
    eng._shutdown_issued = False
    eng._shutdown_issued_at = None
    _ISSUED[0] = None
    modes.mark_shutdown_skipped(eng.state.dir, key)
    errwatch.clear_stopping()
    log.info("⏸ 收到「别关机」：已取消正在倒计时的关机，这一次不关；下一趟队列跑完照常关机")
    return "aborted", "已取消正在倒计时的关机，这次不关机；下一趟跑完照常关机"
