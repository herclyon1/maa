"""Hard lock (硬锁) - the user, 2026-11-26 ~10:50 (Tokyo):
「停止此班，把一切问题解决了再补跑，现在问题堆积到无法正常继续任务」
「所有目前东西必须标记为不可用状态加上硬锁，什么时候根治完什么时候解除状态」

While locked the relay starts nothing and writes nothing into AUTO-MAS or the games:
no dispatch (commands.run_script / commands._run_now), no inbox or phone order except
debug mode, no make-up, collect retry, activity top-up, essence filler, deferred update,
stage gate, retry-limit write, weekly gate or need-table upload (engine.LOCKED_STEPS), and
at boot no self-update, OK-WW patch, AUTO-MAS job fix, Endfield start, pre-update, MaaEnd
re-enable, game-update rerun or annihilation switch (service._main_after_selfupdate).
AUTO-MAS's own queue timers were switched off from the Mac (TimeEnabled=False, 11-26
11:03 Tokyo); nothing here turns them back on.

Power-off (shutdown.decide -> _locked_verdict): a locked boot has no shift to wait for.
A scheduled boot (the 08:40 plug, the 21:20 RTC alarm; modes.BOOT_TIMES) is powered off as
soon as nothing runs and neither debug mode nor the alarm hold holds - both end ten minutes
before the next scheduled power-on (modes.set_debug, modes.set_alarm_hold), so a locked
machine is down before the 08:40 plug cuts the mains. A boot by hand stays on, as always
(the user's rule: no power-off without his order except the relay's own after a scheduled
boot).

Sticky and fail-closed: the lock is LOCK_FILE in the state dir. Seeing it once records
modes.hardlock in state.json, so deleting the file does not release it; an unreadable
file is a lock. Only a LOCK_FILE whose "release" passes released_ok() releases - the
user, 11-26 10:54: 「所有东西必须挂上不可用的状态，必须逐个把出现过的问题根治后解除。」 and
10:58: 「用户只需要听到你方向子代理提问是否该东西已经根治掉之前所有已发生过的问题并他确认验收」:
every problem listed with its fix and an RC=0 test, none left open, and an independent
zero-context sub-agent (not one that fixed it) asked QUESTION and answering VERDICT.
"""
from __future__ import annotations

import json
import logging
import os
import re as _re
import time
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core.config import SERVER_TZ

log = logging.getLogger("ark.hardlock")

LOCK_FILE = "HARDLOCK.json"
# Two locks, each its own file and its own sticky mark: the relay itself, and every WeChat push the
# relay makes (企业微信群机器人、Server酱、企业微信自建应用; core/notify.Notifier). The user, 11-26 12:36:
# 「我觉得应该就是利用你们的那个微信的发消息的那个程序，首先这个程序也挂上不可用的锁，然后等你们修好之后再解锁。」
KINDS = {"relay": (LOCK_FILE, "hardlock"), "wechat": ("HARDLOCK_WECHAT.json", "hardlock_wechat")}
MACHINE_STATE = r"C:\ProgramData\ark-relay\state"
QUESTION = "是否已经根治掉之前所有已发生过的问题"
VERDICT = "确认已根治，验收通过"
# How far from a scheduled power-on (modes.BOOT_TIMES) a boot still counts as that one:
# the plug cuts at 08:40 and the board is up at ~08:45 (relay.log 11-26: boot 08:45:12).
BOOT_BEFORE_MIN = 15
BOOT_AFTER_MIN = 30
# Inbox / phone orders still taken while locked: debug mode only (it keeps the machine on
# for someone working on it, and ends ten minutes before the next scheduled power-on).
ORDERS_WHILE_LOCKED = frozenset({"debug_mode"})
# The 08:40 plug cuts the mains whatever is running (modes.BOOT_TIMES). A debug mode ordered in
# the 150 minutes before a power-on is stretched over the next cycle (modes.set_debug,
# CURRENT_CYCLE_MIN), so it can hold past 08:40; while locked, nothing holds the machine on in
# the CUT_LEAD_MIN before the cut (shutdown._locked_verdict, code GO_CUT).
POWER_CUT = os.environ.get("ARK_POWER_CUT", "08:40")
CUT_LEAD_MIN = 15
GO_CUT = "go-cut"
# How often a locked relay puts AUTO-MAS's queue timers back to off (timers_off).
TIMERS_EVERY_S = 60
_timers_at = [0.0]
REFUSED = "🔒 硬锁中，不可用（用户 11-26 令）：{what}没做。逐个根治、独立子代理确认验收后才解除。"


def _store(state_dir):
    from ark_relay.features import modes  # noqa: PLC0415 - modes imports texts, keep this light
    return modes._store(Path(state_dir))


# The Mac side (~/Money/审批记录/硬锁/hardlock.py LEGDER["relay"]) is the full check; this one is the
# subset the machine can see: every one of these must be among the release's ledger_ids.
LEDGER = ("R-01", "R-02", "R-03", "R-04", "R-05", "R-06", "R-07", "R-08", "R-09", "R-10", "R-11", "R-12",
          "R-13", "R-14", "O-01")
# The WeChat lock's own problems (Mac LEDGER["wechat_send"]): W-01 too slow, W-02 sent to the wrong
# chat (文件传输助手), W-03 only the three kinds of message the user named, and only to his friend.
LEDGERS = {"relay": LEDGER, "wechat": ("W-01", "W-02", "W-03")}
# Pushing work onto the user or promising instead of fixing; a negated phrase (不要用户…, 禁止让用户…) is not one.
_BAD_TEXT = _re.compile(
    r"(?<![不别勿免毋无需须止])(?:要|让|请|需要|等|交给|交由)(?:用户|他本人|你本人)"
    r"|(?<![不别勿免毋无需须止])(?:你|他|用户)本人(?:点头|放行|同意|批|确认|验收)|逐项点头|从现在起|以后一定|保证不再")


def _zero(x) -> bool:
    return type(x) is int and x == 0


def released_ok(rel, kind: str = "relay") -> bool:
    """Both steps of the user's unlock rule, checked field by field."""
    if not isinstance(rel, dict):
        return False
    probs = rel.get("problems")
    if not isinstance(probs, list) or not probs:
        return False
    for p in probs:
        if not isinstance(p, dict) or not _zero(p.get("rc")):
            return False
        if not all(str(p.get(k) or "").strip() for k in ("problem", "fix", "test", "evidence")):
            return False
    if [x for x in LEDGERS.get(kind, LEDGER) if x not in {str(p.get("ledger_id") or "") for p in probs}]:
        return False
    if not _zero(rel.get("unresolved")) or rel.get("confirmed_root_cured") is not True:
        return False
    fixed = [str(x) for x in (rel.get("fixed_by") or []) if str(x).strip()]
    mains = [str(x) for x in (rel.get("main_sessions") or []) if str(x).strip()]
    v = rel.get("verifier")
    if not fixed or not mains or not isinstance(v, dict) or not str(v.get("agent_id") or "").strip():
        return False
    if str(v["agent_id"]) in fixed or str(v["agent_id"]) in mains or not str(v.get("transcript") or "").strip():
        return False
    scan = dict(rel, problems=[{k: v for k, v in p.items() if k != "problem"} for p in probs])
    if _BAD_TEXT.search(json.dumps(scan, ensure_ascii=False)):
        return False
    return v.get("question") == QUESTION and v.get("verdict") == VERDICT


def active(state_dir, kind: str = "relay") -> bool:
    """Is the relay (kind "relay") or its WeChat pushing (kind "wechat") hard-locked? Errors count as locked."""
    lock_file, mark = KINDS.get(kind, KINDS["relay"])
    if not state_dir:
        # A caller without a state dir still looks where the relay keeps its state: the env the
        # service sets (app_main), then the installed relay's own folder. Only when neither exists
        # (a test on the Mac) is there no relay state to be locked.
        state_dir = os.environ.get("ARK_STATE_DIR") or (MACHINE_STATE if os.path.isdir(MACHINE_STATE) else "")
        if not state_dir:
            return False
    path = Path(state_dir) / lock_file
    try:
        sticky = _store(state_dir).get("modes", mark)
    except Exception:  # noqa: BLE001 - cannot tell whether it was ever locked: locked (fail-closed)
        sticky = {"unreadable": True}
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return bool(sticky)
    except OSError:
        return True
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict) and released_ok(data.get("release"), kind):
        if sticky:
            try:
                _store(state_dir).pop("modes", mark)
                log.info("🔓 硬锁已按解锁记录解除（%s）", path)
            except Exception:
                log.warning("硬锁解除记不进 state.json", exc_info=True)
        return False
    if not sticky:
        try:
            _store(state_dir).set("modes", mark, {
                "since": datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"),
                "file": str(path)})
            log.info("🔒 硬锁生效（%s）：不派发、不补跑、不收信箱指令（调试模式除外）、不自更新；"
                        "定时开机这一轮没有班可等，没东西在跑就按设计关机", path)
        except Exception:
            log.warning("硬锁记不进 state.json（锁照样生效）", exc_info=True)
    return True


def refused(what: str) -> str:
    """The one line a refused action answers with."""
    log.info("硬锁中，拦下：%s", what)
    return REFUSED.format(what=what)


def scheduled_boot(booted: datetime, boot_times=None) -> bool:
    """Was this boot one of the scheduled power-ons (not a boot by hand)?"""
    if boot_times is None:
        from ark_relay.features import modes  # noqa: PLC0415
        boot_times = modes.BOOT_TIMES
    b = booted.astimezone(SERVER_TZ)
    for day in (-1, 0, 1):
        for hhmm in boot_times:
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            at = (b + timedelta(days=day)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if at - timedelta(minutes=BOOT_BEFORE_MIN) <= b <= at + timedelta(minutes=BOOT_AFTER_MIN):
                return True
    return False


def before_power_cut(now: datetime) -> bool:
    """Inside the CUT_LEAD_MIN before the plug cuts the mains (POWER_CUT)?"""
    cur = now.astimezone(SERVER_TZ)
    try:
        hh, mm = (int(x) for x in POWER_CUT.split(":"))
    except ValueError:
        return False
    cut = cur.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return cut - timedelta(minutes=CUT_LEAD_MIN) <= cur < cut


def timers_off(mas, force: bool = False) -> list[str]:
    """Put every AUTO-MAS queue's timer (TimeEnabled) and start-up run (StartUpMode) back to off.

    AUTO-MAS starts a shift from its own timer, not through the relay, so the lock re-asserts
    the off state itself (at most every TIMERS_EVERY_S) instead of trusting nobody turns it back
    on (11-26: a direct API call or an unlocked checkout's estop.sh --restore would). Returns the
    queue names it had to switch off."""
    now = time.monotonic()
    if not force and now - _timers_at[0] < TIMERS_EVERY_S:
        return []
    _timers_at[0] = now
    have = mas("/api/queue/get")["data"]
    out = []
    for qid, q in (have or {}).items():
        info = (q or {}).get("Info") or {}
        patch = {}
        if info.get("TimeEnabled"):
            patch["TimeEnabled"] = False
        if info.get("StartUpMode") not in (None, "Never"):
            patch["StartUpMode"] = "Never"
        if patch:
            mas("/api/queue/update", {"queueId": qid, "data": {"Info": patch}})
            out.append(str(info.get("Name") or qid))
    if out:
        log.info("🔒 硬锁中：调度程序里 %s 的定时/开机即跑被人打开了，已关回去", "、".join(out))
    return out
