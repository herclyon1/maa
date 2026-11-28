"""Machine checks of the relay's own machinery: the service host, the boot stages,
the pre-update and game-update flows, the make-up runs, the alarms about records,
the MaaEnd watchdog and the in-run watch.

Most items here are judged from what the relay already keeps: relay.log (read at
the next boot for everything that happens while a session ends - nothing can be
judged by a process that is being torn down), the day's errkinds file (errwatch),
the alarm copy (alertlog: state/alerts/<Beijing YYYYMMDD>.jsonl, written the moment
a group alarm is delivered), state.json, the make-up marker, the gathering retry's
stamp, and the traces the update flows and the watchdog now hand over.

A relay.log session is one service process: from its 「服务模式启动」 line to the
next one. The session a boot judges is the last one before the current that did not end
in a self-update restart - and the same session is not judged twice (its evidence is the
same as the stored one). Until 11-08 only a session that had logged CODE_MARK (the line
right after 「服务模式启动」, boot_stages._stage_bootstrap) was judged, to leave out code
from before these checks; every session of the installed relay logs it, so the rule only
hid a relay that died before that line (audit 11-08 C-13).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from ark_relay.features import machinecheck as mc, errwatch, collector_maaend as cm, collector_maaend as maaend_fwlog, outcome
from ark_relay.core.config import SERVER_TZ, USER_TZ
from ark_relay.core import texts
from contextlib import contextmanager

_log_system = logging.getLogger("ark.system")

# ------------------------------------------------------------------ relay.log

# The words other modules log, matched here. Each is quoted from its source.
CODE_MARK = "中继代码版本"                          # boot_stages._stage_bootstrap
SESSION_START = "服务模式启动"                       # boot_stages._stage_bootstrap
# A self-update restart: the service's wording, then the installed relay's. The session
# that logged either ends in a restart, not a stop, so #11 skips it (2026-10-11: the
# installed relay's wording was not known here and every update rang #11).
SELF_UPDATE = ("代码已更新，重启以立即生效",          # boot_stages._stage_selfupdate
               "代码已更新，切到新版本文件夹并重启")   # app_main.SELF_UPDATE_LINE
STOP_NOTICE = "收到停止通知"                         # service.ArkRelayService.SvcStop
POWER_OFF = "本轮已处理完毕，60 秒后关机"               # engine.Engine._power_off
PUSHED = "已上报状态到手机（"                         # boot_stages publish_state, ok
NOT_PUSHED = "状态没能上报到手机（"                    # boot_stages publish_state, failed
STOP_PUSH_FAILED = ("停止前上报状态失败", "停止前那份状态")  # service.SvcStop / _wait_stop_push
OS_STOP = "（Windows 关机）"                       # service.SvcShutdown's _stop_how in STOP_NOTICE
# app_main.stop_push, run by the watchdog service at a Windows shutdown: its lines are
# logged under this name, after the relay's own (the same session of relay.log).
WATCHDOG_PUSHER = "ark.app.stop_push"
EXIT_AT_POWER_OFF = "中继自己发出了关机命令，AUTO-MAS 后台此时退出"   # service._AutomasKeeper._exited
EXIT_UNEXPLAINED = re.compile(r"^AUTO-MAS 后台(意外)?退出了")       # the same, any other exit
REVIVE_WORDS = ("中继正在重新打开它", "中继正在关掉它重新打开", "AUTO-MAS 接口不在，拉起它")
SHUTDOWN_CANCELLED = "中继不会再自己关机"   # features/shutdown/shutdown.py: the "cancelled" verdict (system event 1075)
WMI_BACK = re.compile(r"^系统的程序启动通知(断过|订不上的情况持续了).*已经自己")   # service._ProcessWatch._subscribed
TAIL_BYTES = 4_000_000
_LINE = re.compile(r"^(\d\d-\d\d) (\d\d:\d\d:\d\d) (\w+)\s+(\S+)\s+(.*)$")


@dataclass
class Rec:
    """One relay.log record: its first line split up, and the lines that continue it."""
    md: str
    hms: str
    level: str
    name: str
    msg: str
    more: list = field(default_factory=list)

    def show(self) -> str:
        return f"{self.md} {self.hms} {self.msg}"


def read_tail(path, nbytes: int = TAIL_BYTES) -> str:
    """The last `nbytes` of relay.log as text, starting at a whole line; '' when unreadable.

    Reaches into relay.log.1 when a rotation just moved the previous session there
    (logfile.tail_bytes): a rotation at boot would otherwise cut it in two."""
    from ark_relay.core.statestore import tail_bytes  # noqa: PLC0415
    try:
        data, cut = tail_bytes(path, nbytes)
    except (OSError, TypeError):
        return ""
    text = data.decode("utf-8", "replace")
    return text.split("\n", 1)[-1] if cut else text


def records(text: str) -> list[Rec]:
    out: list[Rec] = []
    for line in text.splitlines():
        if m := _LINE.match(line):
            out.append(Rec(*m.groups()))
        elif out:
            out[-1].more.append(line)
    return out


def sessions(recs: list[Rec]) -> list[list[Rec]]:
    """The records split into service processes; what comes before the first start is dropped."""
    out: list[list[Rec]] = []
    for r in recs:
        if r.msg.startswith(SESSION_START):
            out.append([r])
        elif out:
            out[-1].append(r)
    return out


def previous_session(recs: list[Rec]) -> "list[Rec] | None":
    """The last session before the current one (the last) that did not end in a
    self-update restart; None when there is none. A session that died before its
    CODE_MARK line is one too: it ended without a stop, which #11 says."""
    found = sessions(recs)
    for s in reversed(found[:-1]):
        if any(r.msg.startswith(SELF_UPDATE) for r in s):
            continue
        return s
    return None


def _log_file(ctx) -> str:
    return str(ctx.get("log_file") or os.environ.get("ARK_LOG_FILE") or "")


# (path, size, mtime) -> the previous session: every boot check asks for it, and
# judge() hands each check a copy of the context, so the parse is kept here.
_SESSION: dict = {}


def _prev(ctx) -> "list[Rec] | None":
    path = _log_file(ctx)
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    key = (path, st.st_size, st.st_mtime_ns)
    if key not in _SESSION:
        _SESSION.clear()
        _SESSION[key] = previous_session(records(read_tail(path)))
    return _SESSION[key]


def _following(ctx, prev: list[Rec]) -> list[Rec]:
    """The session that came right after `prev` in relay.log (the one judging, or a self-update restart); [] when none."""
    found = sessions(records(read_tail(_log_file(ctx))))
    i = next((n for n, x in enumerate(found) if x[0] == prev[0]), None)
    return found[i + 1] if i is not None and i + 1 < len(found) else []


def _sys_now(ctx) -> datetime:
    return (ctx.get("now") or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)


def _day_of(md: str, now: datetime) -> str:
    """YYYY-MM-DD of a relay.log MM-DD stamp (the log has no year; a date after today is last year's)."""
    year = now.year - (1 if md > now.strftime("%m-%d") else 0)
    return f"{year}-{md}"


def _once(ctx, cid: str, result: mc.Result) -> "mc.Result | None":
    """None when this very evidence was judged before: the same session read again at a later boot."""
    return None if mc.judged_before(ctx.get("state_dir"), cid, result.evidence) else result


# ------------------------------------------------------------------ #11

@mc.check("#11", "中继停下时最后推一份状态给手机（Windows 关机也送得到）", "A", "boot")
def _stop_push(ctx):
    s = _prev(ctx)
    if s is None:
        return None
    stop = next((r for r in s if r.msg.startswith(STOP_NOTICE)), None)
    if stop is None:
        # A relay ended at a shutdown before it could log the notice: the watchdog's
        # push (app_main.stop_push) still sent the last state.
        dog = next((r for r in s if r.name == WATCHDOG_PUSHER and f"{PUSHED}停止前" in r.msg), None)
        if dog is not None:
            return _once(ctx, "#11", mc.Result(
                mc.PASS, f"中继没留下停止通知，Windows 关机时看门服务代发了停止前那份：{dog.show()}"))
        return _once(ctx, "#11", mc.Result(mc.FAIL, f"上一次中继没收到停止通知就没了，最后一行：{s[-1].show()}"))
    if not any(PUSHED in r.msg or NOT_PUSHED in r.msg for r in s):
        return None          # the phone channel never worked in that session: nothing to push with
    after = s[s.index(stop):]
    # The relay's own push, or the watchdog's when a forced shutdown cut the relay off
    # (2026-10-11 14:25:10: the stop notice, then nothing until the next boot).
    ok = next((r for r in after if f"{PUSHED}停止前" in r.msg), None)
    bad = next((r for r in after if f"{NOT_PUSHED}停止前" in r.msg or r.msg.startswith(STOP_PUSH_FAILED)), None)
    if ok is not None:
        by = "（看门服务代发）" if ok.name == WATCHDOG_PUSHER else ""
        return _once(ctx, "#11", mc.Result(mc.PASS, f"{stop.show()}；{ok.show()}{by}"))
    if bad is not None:
        # A service stop (a deploy, a restart by hand) whose next start pushed the boot
        # state left the phone with a newer state than the one cut off: recovered.
        # A Windows shutdown stays strict - its next start is the next power-on.
        boot = next((r for r in _following(ctx, s) if f"{PUSHED}开机" in r.msg), None)
        if boot is not None and OS_STOP not in stop.msg:
            # 服务重启（更新/手动重启）后开机推送已送达手机：属正常更新重启闭环，仅记 info，不刷群、不进日报。
            _log_system.info(
                "停止前那份状态没送完，中继重新启动后开机那份已送到手机：%s；%s", bad.show(), boot.show())
            return _once(ctx, "#11", mc.Result(mc.PASS, f"{stop.show()}；{bad.show()}；重启后{boot.show()}"))
        return _once(ctx, "#11", mc.Result(mc.FAIL, f"{stop.show()}；{bad.show()}"))
    # The relay's own power-off pushes 「关机前」 just before it issues the command,
    # so the page already has the last state when Windows then stops the service.
    off = next((i for i, r in enumerate(s) if r.msg.startswith(POWER_OFF)), None)
    before = next((r for r in reversed(s[:off]) if f"{PUSHED}关机前" in r.msg), None) if off is not None else None
    if before is not None:
        return _once(ctx, "#11", mc.Result(
            mc.PASS, f"{stop.show()}；停止前那份没等到送完，关机前那份已送到：{before.show()}"))
    return _once(ctx, "#11", mc.Result(mc.FAIL, f"{stop.show()}，之后没有停止前那份状态送出的记录（中继先停下了）"))


# ------------------------------------------------------------------ #14

mc.cannot("#14", "改终末地等待秒数只经调度程序改这一项、别的设置不动（改了再改回的核对）",
          "要把等待秒数真改一次再改回才看得出；手机页没有这个设置，机器自己从不改它，核对不能为了被判去改设置")


# ------------------------------------------------------------------ #18

BUSY_FILE = "machinecheck-busy.json"     # written by engine._note_other_modes


@mc.check("#18", "调度程序里开着设置脚本这类非自动代理的任务时，中继问它算不算在忙", "B", "boot")
def _other_mode_busy(ctx):
    f = Path(ctx.get("state_dir") or ".") / BUSY_FILE
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    seen = data.get("seen") if isinstance(data, dict) else None
    fresh = [o for o in seen or [] if isinstance(o, dict) and not o.get("judged")]
    if not fresh:
        return None
    for o in fresh:
        o["judged"] = True
    try:
        from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
        atomic_write_text(f, json.dumps(data, ensure_ascii=False, indent=1))
    except OSError:
        pass                     # judged again next boot: the same evidence is not recorded twice
    bad = next((o for o in fresh if not o.get("busy")), None)
    o = bad or fresh[-1]
    said = (f"{o.get('at', '')} 调度程序里开着模式为 {o.get('mode', '?')} 的任务（{o.get('line', '')}），"
            f"中继问调度程序时算{'不忙' if bad else '在忙'}")
    return mc.Result(mc.FAIL if bad else mc.PASS, said)


# ------------------------------------------------------- alarms about records

def _reached_group(ctx) -> "mc.Result | None":
    """PASS when the alarm went out and its copy is in the day's alarm copy, else FAIL."""
    title, body, run_id = ctx.get("title") or "", ctx.get("body") or "", ctx.get("run_id") or ""
    if not ctx.get("sent"):
        return mc.Result(mc.FAIL, f"「{title}」没推出去（{run_id}）")
    if not ctx.get("copies"):
        return None              # this sender keeps no alarm copy: nothing to confirm against
    from ark_relay.features import errwatch as alertlog  # noqa: PLC0415
    day8 = alertlog.beijing(_sys_now(ctx)).strftime("%Y%m%d")
    row = next((r for r in reversed(mc.alert_rows(ctx.get("state_dir"), day8))
                if r.get("title") == title and r.get("text") == body), None)
    if row is None:
        return mc.Result(mc.FAIL, f"「{title}」说推出去了，报警抄送 alerts/{day8}.jsonl 里没有这一条（{run_id}）")
    return mc.Result(mc.PASS, f"{row.get('ts', '')} 群里收到「{title}」（{run_id}）")


@mc.check("#21", "有人在调度程序上手动开的那趟出了问题，照样报到群里", "B", "unresolved")
def _hand_started_pushed(ctx):
    return _reached_group(ctx) if ctx.get("kind") == "手动" else None


@mc.check("#34", "补跑后还没成（或没补跑）的，每一条都报到群里", "B", "unresolved")
def _unresolved_pushed(ctx):
    return _reached_group(ctx) if ctx.get("kind") == "未解决" else None


@mc.check("#55", "班次超时报警只报班次自己的任务，有人手动开的不算", "B", "unresolved")
def _overrun_own_task(ctx):
    if ctx.get("kind") != "队列超时":
        return None
    where = f"{ctx.get('queue', '')} {ctx.get('hhmm', '')} 那班"
    line = ctx.get("create") or ""
    if not ctx.get("alarmed"):
        return _once(ctx, "#55", mc.Result(
            mc.PASS, f"{where}到点还没跑完的是有人手动开的任务（调度程序日志：{line}），没当成班次报超时"))
    if not line:
        return mc.Result(mc.FAIL, f"{where}报了超时，调度程序日志里找不到这个任务（{ctx.get('task_id', '')}）"
                                  "是谁开的，确认不了不是有人手动开的")
    return mc.Result(mc.PASS, f"{where}自己的任务超时（调度程序日志：{line}），已报群")


# ------------------------------------------------------------------ #31

@mc.check("#31", "终末地卡死看门狗结束 MaaEnd 时，它真的没了", "B", "watchdog")
def _watchdog_killed(ctx):
    res = ctx.get("result") or {}
    if not res:
        return None
    if ctx.get("action") != "kill":
        return None
    head = f"MaaEnd（PID {res.get('pid')}）卡死（{res.get('reason', '')}）"
    if res.get("gone"):
        return mc.Result(mc.PASS, f"{head}，结束命令成功，{res.get('waited', 0)} 秒后在跑的程序里已没有它")
    if res.get("gone") is None and res.get("ok"):
        return mc.Result(mc.FAIL, f"{head}，结束命令说成功了，之后读不到在跑的程序列表，没确认它没了")
    return mc.Result(mc.FAIL, f"{head}，没结束掉：{res.get('why', '')}")


# ---------------------------------------------------------- make-up runs

@mc.check("#32", "关机前只补跑没走通的采集路线，真的跑出了结论", "B", "makeup")
def _collect_retry_ran(ctx):
    if ctx.get("kind") != "采集路线":
        return None
    r = ctx.get("result") or {}
    label = ctx.get("labels") or {}
    name = lambda rid: label.get(rid) or rid  # noqa: E731
    routes = "、".join(name(x) for x in r.get("routes") or [])
    unknown, note = r.get("unknown") or [], r.get("note") or ""
    if unknown or note:
        return mc.Result(mc.FAIL, f"补跑 {routes} 没跑出结论：{note or '日志里没有这几条路线走完或失败的记录'}"
                                  + (f"（没结论的：{'、'.join(name(x) for x in unknown)}）" if unknown else ""))
    nodes = r.get("nodes") or {}
    first = next(iter(nodes.values()), "")
    return mc.Result(mc.PASS, f"补跑了 {routes}：走通 {'、'.join(name(x) for x in r.get('passed') or []) or '无'}，"
                              f"没走通 {'、'.join(name(x) for x in r.get('failed') or []) or '无'}"
                              + (f"（maafw.log：{first[:120]}）" if first else ""))


@mc.check("#33", "明日方舟 / 终末地失败后补跑一次，补跑真的跑出了记录", "B", "makeup")
def _makeup_ran(ctx):
    if ctx.get("kind") != "补跑":
        return None
    from ark_relay.features import makeup  # noqa: PLC0415
    ent, script = ctx.get("result") or {}, ctx.get("script") or ""
    res, note = ent.get("result"), str(ent.get("note") or "")
    when = str(ent.get("dispatched_at") or "")[11:16]
    if res in (makeup.OK, makeup.FAILED) and ent.get("record"):
        how = "走通" if res == makeup.OK else f"没成（{note or '没写原因'}）"
        return mc.Result(mc.PASS, f"{script} 补跑 {when} 派下去，记录 {ent['record']} 落地：{how}")
    if res == makeup.NO_RECORD:
        return mc.Result(mc.FAIL, f"{script} 补跑 {when} 派下去了，{makeup.STALE_MIN} 分钟没跑出记录")
    if res == makeup.GAVE_UP and not note.startswith("不补跑"):
        return mc.Result(mc.FAIL, f"{script} 补跑没跑成：{note or '没写原因'}")
    return None                  # still to come, or not run by a rule (MAA already fought, debug mode)


@mc.check("#65", "明日方舟没进到游戏时，中继记下「进不了游戏」", "B", "makeup")
def _maa_unreachable(ctx):
    if ctx.get("kind") != "没进游戏" or ctx.get("script") != "MAA":
        return None
    run_id = ctx.get("run_id") or ""
    row = mc.read(ctx.get("state_dir")).get("#65") or {}
    if run_id and str(row.get("evidence") or "").startswith(run_id):
        return None              # this record was judged already (the make-up step runs every tick)
    if ctx.get("written"):
        return mc.Result(mc.PASS, f"{run_id} 明日方舟没进到游戏，记录上写了「进不了游戏」（maa_unreachable）")
    cap = ctx.get("captured") or {}
    return mc.Result(mc.FAIL, f"{run_id} 明日方舟像是没进到游戏（调度程序记的失败：{ctx.get('failed', '')}），"
                              f"记录上却没写「进不了游戏」（maa_unreachable），记账和补跑对这一趟的判断不一样；这一趟 MAA 自己的日志 gui.log {cap.get('gui', 0)} 行、"
                              f"asst.log {cap.get('asst', 0)} 行已存到 {cap.get('path', '（没存下）')}，"
                              f"最后一行：{cap.get('last', '（没有）')}")


# ------------------------------------------------------- power-off and WMI

def _after_power_off(ctx) -> "tuple[Rec, list[Rec]] | None":
    s = _prev(ctx)
    if s is None:
        return None
    i = next((i for i, r in enumerate(s) if r.msg.startswith(POWER_OFF)), None)
    return None if i is None else (s[i], s[i:])


@mc.check("#37", "中继自己关机时，调度程序后台退出不算意外", "A", "boot")
def _poweroff_exit(ctx):
    got = _after_power_off(ctx)
    if got is None:
        return None
    off, after = got
    if bad := next((r for r in after if EXIT_UNEXPLAINED.match(r.msg)), None):
        return _once(ctx, "#37", mc.Result(mc.FAIL, f"{off.show()}；之后 {bad.show()}"))
    ok = next((r for r in after if r.msg.startswith(EXIT_AT_POWER_OFF)), None)
    return _once(ctx, "#37", mc.Result(mc.PASS, f"{off.show()}；" + (
        ok.show() if ok else f"到中继停下（{after[-1].md} {after[-1].hms}）没有「意外退出」")))


@mc.check("#38", "中继自己关机时，不去重新打开调度程序", "A", "boot")
def _poweroff_no_revival(ctx):
    got = _after_power_off(ctx)
    if got is None:
        return None
    off, after = got
    # Someone at the machine cancelled the shutdown (system event 1075): the machine stays on and from then on the
    # relay keeps the scheduler running as on any other evening, so a revival after that line is not this check's
    # case (10-24 21:36:06 cancelled, 21:46:29 reopened; alert 4074ce7d failed #38 on it).
    cut = next((i for i, r in enumerate(after) if SHUTDOWN_CANCELLED in r.msg), None)
    if cut is not None:
        after = after[:cut + 1]
    if bad := next((r for r in after if any(w in r.msg for w in REVIVE_WORDS)), None):
        return _once(ctx, "#38", mc.Result(mc.FAIL, f"{off.show()}；之后 {bad.show()}"))
    if cut is not None:
        return _once(ctx, "#38", mc.Result(
            mc.PASS, f"{off.show()}；到关机被取消（{after[-1].md} {after[-1].hms}）没有去重新打开调度程序，之后机器开着"))
    return _once(ctx, "#38", mc.Result(
        mc.PASS, f"{off.show()}；到中继停下（{after[-1].md} {after[-1].hms}）没有去重新打开调度程序"))


_HYPOTHESIS = re.compile(r"hypothesis: (H[123])\b")
HYPOTHESIS_ZH = {"H1": "WMI 服务自己重启过", "H2": "WMI 的提供程序宿主（WmiPrvSE）没了一个",
                 "H3": "WMI 服务和提供程序宿主都没变（另有原因）"}


@mc.check("#59", "系统的程序启动通知断了又自己订上的，报群一次，并写明是哪种原因", "B", "boot")
def _wmi_recovered(ctx):
    """核验 procwatch._subscribed：未在断开期间报过群的掉线恢复记录为 WARNING 并报群一次、带 H1/H2/H3 原因；
    断开期间已经报过群的恢复改记 INFO 闭环，不再重复刷群也不进日报。"""
    s = _prev(ctx)
    if s is None:
        return None
    back = [r for r in s if r.level == "WARNING" and WMI_BACK.match(r.msg)]
    if not back:
        return None
    now = _sys_now(ctx)
    good = ""
    for r in back:
        day = _day_of(r.md, now)
        needle = r.msg.strip()[:60]      # errwatch 推送会引用日志首行前 160 字
        n = sum(1 for x in mc.alert_rows(ctx.get("state_dir"), day.replace("-", ""))
                if needle in str(x.get("text") or "") and r.hms in str(x.get("text") or ""))
        if n == 0:
            return _once(ctx, "#59", mc.Result(mc.FAIL, f"{r.show()}：没进群"))
        if n > 1:
            return _once(ctx, "#59", mc.Result(mc.FAIL, f"{r.show()}：同一次断开进了群 {n} 次"))
        diag = next((m for x in r.more if (m := _HYPOTHESIS.search(x))), None)
        if diag is None:
            raw = next((x.strip() for x in r.more if x.strip().startswith("diag:")), "（没有 diag 行）")
            raw = raw[raw.find("WMI hosts"):] if "WMI hosts" in raw else raw
            return _once(ctx, "#59", mc.Result(mc.FAIL, f"{r.show()}：说不出是哪种原因：{raw[:160]}"))
        good = f"{r.show()}；报了一次群；原因：{HYPOTHESIS_ZH[diag.group(1)]}"
    return _once(ctx, "#59", mc.Result(mc.PASS, good))


# ------------------------------------------------------------------ #63

@mc.check("#63", "开机后 state.json 里不再留着中继关掉终末地任务的旧记录（应急理智加强剂那条）", "A", "boot")
def _off_records_gone(ctx):
    from ark_relay.features.gameupdate import _OFF_RECORDS  # noqa: PLC0415
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    if not ctx.get("state_dir"):
        return None
    store = StateStore(ctx["state_dir"])
    left = [(k, v) for k in _OFF_RECORDS if (v := store.get("updates", k)) is not None]
    if left:
        k, v = left[0]
        return mc.Result(mc.FAIL, f"开机后 state.json 里还留着 {k}：{json.dumps(v, ensure_ascii=False)[:160]}")
    return mc.Result(mc.PASS, "开机后 state.json 里已经没有 maaend_disabled_spmed（另两条旧记录也没有）")


# ------------------------------------------------------------------ #R02

@mc.check("#R02", "终末地脚本预更新已交由调度程序接管（测试版通道）", "A", "boot")
def _maaend_preupdate_contract(ctx):
    """Detect MaaEnd pre-update chain break on AUTO-MAS v5.8+ scripts.yaml (R-02)."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
    cfg = ctx.get("cfg")
    automas_dir = getattr(cfg, "automas_dir", None) if cfg is not None else ctx.get("automas_dir")
    if not automas_dir:
        return None
    node, has_yaml = mastercfg._find_maaend_script(automas_dir)
    if not (has_yaml or (isinstance(node, dict) and isinstance(node.get("Update"), dict))):
        return None
    gaps = mastercfg.check_maaend_preupdate(automas_dir)
    if gaps:
        return mc.Result(mc.FAIL, "；".join(gaps))
    return mc.Result(mc.PASS, "终末地开跑前预更新已由调度程序接管，且通道为测试版")


# ------------------------------------------------------- game client updates

def _notes(ctx, what: str) -> list[dict]:
    return [x for x in ctx.get("screens") or [] if isinstance(x, dict) and x.get("what") == what]


@mc.check("#60", "桌面助手找不到窗口时报回来、不点，两个字的按钮整行对上才点", "B", "gameupdate")
def _desktop_agent(ctx):
    runs = _notes(ctx, "agent")
    said = []
    for r in runs:
        log = [str(x) for x in r.get("log") or []]
        if any(x.startswith("focus: 没有") for x in log):
            if not r.get("focus_missing"):
                return mc.Result(mc.FAIL, f"找不到「{r.get('focus')}」的窗口，桌面助手没把 focus_missing 传回来"
                                          f"（还是旧脚本？）：{'；'.join(log)[:160]}")
            if r.get("clicks") and (r.get("clicked") or not any(x.startswith("skip click") for x in log)):
                return mc.Result(mc.FAIL, f"找不到「{r.get('focus')}」的窗口，还是点了：{'；'.join(log)[:160]}")
            said.append(f"找不到「{r.get('focus')}」的窗口：传回了 focus_missing"
                        + ("，没点" if r.get("clicks") else ""))
        want = str(r.get("text") or "").replace(" ", "")
        if want and len(want) <= 2 and r.get("clicked"):
            hit = next((x[len("click_text: 点了「"):-1] for x in log if x.startswith("click_text: 点了「")), None)
            if hit is None:
                return mc.Result(mc.FAIL, f"点了「{want}」，桌面助手没说点的是哪一行：{'；'.join(log)[:160]}")
            if hit.replace(" ", "") != want:
                return mc.Result(mc.FAIL, f"要点「{want}」，点的却是整行「{hit}」")
            said.append(f"点「{want}」点的是整行「{hit}」")
    return mc.Result(mc.PASS, "；".join(said)) if said else None


# Wait frames in a row with none of the words before #61 says the launcher sat on a
# screen it cannot read. One frame is ~36 s apart (poll_s 30 plus the agent's read;
# relay.log 10-15 12:32:49, 12:33:25, 12:34:02 ...). A frame alone is not enough:
# Windows OCR misses the black-on-yellow button on single frames while it shows
# 「正在下载」 - 10-15 12:44:15 (shot-84e4bfdf.png, the button reads 「正在下载」 on
# the picture) between 20 frames before and 1 after that read it at the same place.
# On that day's download, which ended in 「开始游戏」, the longest run of such frames
# was 2 (12:46:01-12:46:37 and 12:48:33-12:49:09); 3 is about 108 s of a launcher
# screen with no known word.
LAUNCHER_MISS_RUN = 3


def _launcher_stages(notes: list[dict]) -> list[list[dict]]:
    """The launcher notes cut into stages: one look at a launcher (stage "first") and
    the wait that follows it, per game. One run_deferred can hold several rounds
    (10-15: 「前面几轮没准备好，后来一轮准备好了」), each opening with its own first look."""
    stages: list[list[dict]] = []
    open_of: dict[str, list[dict]] = {}
    for x in notes:
        game = str(x.get("game") or "")
        if x.get("stage") == "first" or game not in open_of:
            open_of[game] = []
            stages.append(open_of[game])
        open_of[game].append(x)
    return stages


def _launcher_missed(x: dict) -> bool:
    """A launcher frame on which none of the words the flow knows was read."""
    return not (x.get("busy") or x.get("ready") or x.get("dialog"))


@mc.check("#61", "启动器下载时屏上的字认得出（正在下载 / 下载中 / 解压中这些）", "B", "gameupdate")
def _launcher_busy_words(ctx):
    """Judged per stage: a stage fails when none of its wait frames read a known word
    (busy, ready, or the disk-space dialog the flow handles), or when LAUNCHER_MISS_RUN
    frames in a row read none. Single frames without a word are counted and said in
    the PASS line, not alarmed."""
    missed_all, longest_run = 0, (0, None)
    for stage in _launcher_stages(_notes(ctx, "launcher")):
        waits = [x for x in stage if x.get("stage") == "wait" and not x.get("unread")]
        if not waits:
            continue
        game = waits[0].get("game")
        missed = [x for x in waits if _launcher_missed(x)]
        if len(missed) == len(waits):
            x = missed[0]
            return mc.Result(mc.FAIL, f"{game}启动器在下载时屏上的字一个也没认出（等了 {len(waits)} 帧，"
                                      f"截图 {x.get('shot')}）：{str(x.get('dump') or '')[:160]}")
        run: list[dict] = []
        for x in waits:
            run = run + [x] if _launcher_missed(x) else []
            if len(run) >= LAUNCHER_MISS_RUN:
                return mc.Result(mc.FAIL, f"{game}启动器连着 {len(run)} 帧（约 {len(run) * 36} 秒）屏上的字"
                                          f"一个也没认出（第一帧截图 {run[0].get('shot')}）："
                                          f"{str(run[0].get('dump') or '')[:160]}")
            if len(run) > longest_run[0]:
                longest_run = (len(run), run[0])
        missed_all += len(missed)
    seen = [x for x in _notes(ctx, "launcher") if not x.get("unread")]
    hit = next((x for x in seen if x.get("busy")), None)
    if hit is None:
        return None              # the download screen never came up (or nothing was read)
    said = (f"{hit.get('game')}启动器下载时读到「{hit.get('busy')}」"
            f"（那一行：{hit.get('line', '')}，截图 {hit.get('shot')}）")
    if missed_all:
        waits = sum(1 for x in seen if x.get("stage") == "wait")
        said += (f"；等待中 {waits} 帧里 {missed_all} 帧没认出字（最长连着 {longest_run[0]} 帧，"
                 f"第一帧截图 {longest_run[1].get('shot')}），不到连着 {LAUNCHER_MISS_RUN} 帧，不报群")
    return mc.Result(mc.PASS, said)


@mc.check("#64", "终末地公告读不到时报到群里", "B", "gameupdate")
def _ef_notice_pushed(ctx):
    probs = [p for p in ctx.get("problems") or [] if str(p).startswith("终末地：官方公告读不到")]
    if not probs or "title" not in ctx:
        return None
    return _reached_group(dict(ctx, run_id=probs[0]))


_log_phone_banners = logging.getLogger("ark.phone_banners")

SHIFT_END = "关机前"           # the push before the relay's own power-off (shutdown.py)
BOOT = "开机"                  # the first push of a process (boot_stages._start_phone_channel)
FRESH_S = 120                  # an alarm line this young may still be on its way to the group
_STAMP = "%Y-%m-%d %H:%M:%S"


# ------------------------------------------------------------------ calling judge

class ViaErrwatch:
    """A notifier for call sites that have none (banners.save_trace) or must not
    wait on the network (a service stop): a check that did not hold is logged as
    an ERROR carrying its own title and body, and errwatch pushes exactly that to
    the group - queued on disk, sent from its own thread, never dropped."""

    def send(self, title: str, body: str = "", alert: bool = False, **_kw) -> list:
        _log_phone_banners.error("%s", title, extra=errwatch.alarm(title, body))
        return []


def fire(state_dir, event: str, ctx: dict, notifier=None) -> list:
    """machinecheck.judge for the phone and banner call sites: the running version
    from the state store, ViaErrwatch when no notifier is given. Never raises."""
    if not state_dir:
        return []
    try:
        from ark_relay.core.statestore import StateStore  # noqa: PLC0415
        version = str(StateStore(Path(state_dir)).get("versions", "code") or "")
    except Exception:  # noqa: BLE001 - an unreadable version only leaves the column empty
        version = ""
    try:
        return mc.judge(state_dir, event, ctx, version=version,
                        notifier=notifier if notifier is not None else ViaErrwatch())
    except Exception:  # noqa: BLE001
        _log_phone_banners.exception("上机核对（%s）自己出错了", event)
        return []


# ------------------------------------------------------------------ helpers

def _now(ctx) -> datetime:
    now = ctx.get("now_bj")
    return now if isinstance(now, datetime) else datetime.now(tz=SERVER_TZ)


def _clock(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=SERVER_TZ).strftime("%H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def _rx(*patterns: str) -> tuple:
    return tuple(re.compile(p) for p in patterns)


def _hit(patterns, line: str) -> bool:
    return any(p.search(line) for p in patterns or ())


def _rows_since(state_dir, since: datetime, now: datetime) -> list[tuple[str, dict]]:
    """The error kinds logged at or after `since` (at most the last three days)."""
    since = since.astimezone(SERVER_TZ)
    cut = since.strftime(_STAMP)
    day = max(since, now - timedelta(days=2)).date()
    out: list[tuple[str, dict]] = []
    while day <= now.date():
        out += [(k, r) for k, r in mc.errkind_rows(state_dir, day.isoformat()) if str(r.get("last", "")) >= cut]
        day += timedelta(days=1)
    return out


def _queued_sigs(state_dir) -> set[str]:
    try:
        data = json.loads((Path(state_dir) / errwatch.QUEUE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(x.get("sig")) for x in data if isinstance(x, dict)} if isinstance(data, list) else set()


def _in_alert_copy(state_dir, row: dict) -> bool:
    """The copy of every delivered group alarm (alertlog: state/alerts/<YYYYMMDD>.jsonl)
    has a 「🩺 中继自己报错了」 line for this kind, from its first occurrence on."""
    part = f"出在「{texts.relay_part(str(row.get('where') or ''))}」"
    first = str(row.get("first") or "")
    try:
        day = datetime.strptime(first[:10], "%Y-%m-%d")
        last = datetime.strptime(str(row.get("last") or first)[:10], "%Y-%m-%d")
    except ValueError:
        return False
    while day <= last + timedelta(days=1):
        for obj in mc.alert_rows(state_dir, f"{day:%Y%m%d}"):
            if (str(obj.get("title", "")).startswith(texts.RELAY_ERROR)
                    and part in str(obj.get("text", "")) and str(obj.get("ts", "")) >= first):
                return True
        day += timedelta(days=1)
    return False


def _age(row: dict, now: datetime) -> float:
    try:
        last = datetime.strptime(str(row.get("last") or ""), _STAMP).replace(tzinfo=SERVER_TZ)
    except ValueError:
        return 1e9
    return (now - last).total_seconds()


def _pb_lines(ctx, since: datetime, where: tuple, *, old=(), alarm=()) -> tuple[list, list]:
    """核验指定模块自 `since` 起的 WARNING / ERROR：旧错不得复现，真错必须全部直推企微群（废除旧「只进日报」假设）。"""
    state_dir, now = ctx.get("state_dir"), _now(ctx)
    bad: list[str] = []
    notes: list[str] = []
    for _sig, r in _rows_since(state_dir, since, now):
        line = str(r.get("line") or "")
        if str(r.get("where") or "") not in where:
            continue
        n, pushed = int(r.get("count") or 1), int(r.get("pushed") or 0)
        at = str(r.get("last") or "")[11:19]
        if _hit(old, line):
            bad.append(f"改掉的旧报错又出现了 {n} 次（最后 {at}）：{line[:120]}")
        elif _hit(alarm, line):
            if pushed >= n and _in_alert_copy(state_dir, r):
                notes.append(f"报错 {n} 次都进了群（{line[:24]}…）")
            elif _age(r, now) < FRESH_S:
                notes.append(f"那条报错 {at} 刚记下，正在进群（{line[:24]}…）")
            elif pushed >= n:
                bad.append(f"报错 {n} 次推出去了，报警抄件里却没有（{at}）：{line[:120]}")
            else:
                bad.append(f"报错 {n} 次里 {n - pushed} 次还没进群（最后 {at}）：{line[:120]}")
    return bad, notes


def _verdict(head: str, bad: list, notes: list) -> mc.Result:
    """FAIL with what did not hold first, else PASS; what held is said after it either way."""
    tail = "；".join([*bad[:3], *notes[:3]])
    return mc.Result(mc.FAIL if bad else mc.PASS, head + (f"；{tail}" if tail else ""))


def _since(ctx) -> datetime:
    t = (ctx.get("tally") or {}).get("since")
    try:
        return datetime.fromtimestamp(float(t), tz=SERVER_TZ)
    except (TypeError, ValueError, OverflowError, OSError):
        return _now(ctx) - timedelta(hours=12)


def _shift_end(ctx) -> bool:
    return ctx.get("why") == SHIFT_END


def _base(ctx, what: str) -> dict:
    """The counts `what` had at the previous shift end of this process (boot_stages
    moves them there), so a machine that stays on is judged shift by shift."""
    got = ((ctx.get("tally") or {}).get("base") or {}).get(what)
    return got if isinstance(got, dict) else {}


# ------------------------------------------------------------------ the banner section

def _sources(tr, game: str, what: str) -> list[tuple[str, str]]:
    """(where, value) of the trace lines 「game｜what｜where｜value」, in order."""
    out = []
    for s in getattr(tr, "sources", None) or []:
        parts = str(s).split("｜", 3)
        if len(parts) == 4 and parts[0] == game and parts[1] == what:
            out.append((parts[2], parts[3]))
    return out


def _doors(tr) -> dict[str, str]:
    return {where: value for where, value in _sources(tr, "鸣潮", "版本资讯门")}


def _block(text: str, game: str) -> list[str]:
    """The lines of one game's block of the rendered banner section."""
    out: list[str] = []
    inside = False
    for ln in str(text or "").splitlines():
        if ln.strip() in ("明日方舟", "鸣潮", "终末地"):
            inside = ln.strip() == game
            continue
        if inside:
            out.append(ln)
    return out


@mc.check("#2", "鸣潮版本活动日历图读出第二期卡池的开始日期", "A", "banners")
def _ww_calendar(ctx):
    rows = _sources(ctx.get("trace"), "鸣潮", "版本日历")
    if not rows:
        return None          # not read this time: the second half's time came from its own notice
    where, value = rows[-1]
    if "日期没读出" in value and "另一来源已给出" not in value:
        why = value
        # The reader's own words, when the desktop agent failed: its WARNING of today.
        for _sig, r in sorted(_rows_since(ctx.get("state_dir"), _now(ctx) - timedelta(minutes=30), _now(ctx)),
                              key=lambda kv: str(kv[1].get("last", ""))):
            if r.get("where") == "ark.desktop" and str(r.get("line", "")).startswith("桌面助手读图失败"):
                why = f"{value}；桌面读屏：{str(r.get('line'))[:120]}"
        return mc.Result(mc.FAIL, why)
    return mc.Result(mc.PASS, f"{value}（{where.rsplit('」', 1)[-1] or where}）")


@mc.check("#3", "库街区那份没给时，哔哩哔哩那份版本资讯读出第二期卡池的时间", "B", "banners")
def _bili_door(ctx):
    doors = _doors(ctx.get("trace"))
    bili = doors.get("B 站")
    if bili is None:
        return None          # 库街区 gave the time (or nothing asked for it): the door was not needed
    kuro = doors.get("库街区", "没去取")
    head = f"库街区：{kuro}；哔哩哔哩：{bili}"
    if bili == "没有这一帖" and (kuro == "没有这一帖" or kuro.startswith("取不到")):
        # Bilibili's feed was read and the post is not in it, nor in Kuro's list:
        # the publisher has not posted it yet, the door did its job. Until
        # 2026-11-08 this was a FAIL every evening before the post went up.
        return mc.Result(mc.PASS, f"官方还没发这一帖（{head}）")
    return mc.Result(mc.PASS if bili.startswith("给出了") else mc.FAIL, head)


@mc.check("#8", "明日方舟下期「官方通讯」一行：该出就出，过期就撤", "A", "banners")
def _ak_comm(ctx):
    rows = _sources(ctx.get("trace"), "明日方舟", "官方通讯")
    if not rows:
        return None          # an announced banner answered the 下期 line first
    where, value = rows[-1]
    nxt = next((ln for ln in _block(ctx.get("text"), "明日方舟") if ln.startswith("· 下期")), "")
    shown = "官方通讯" in nxt
    if value.startswith("取不到"):
        return mc.Result(mc.FAIL, f"官网制作组通讯{value}")
    if value.startswith("没用上（过期："):
        reason = value[len("没用上（过期："):]
        reason = reason[:-1] if reason.endswith("）") else reason
        if shown:
            return mc.Result(mc.FAIL, f"官方通讯已经过期（{reason}），日报还写着：{nxt}")
        return mc.Result(mc.PASS, f"官方通讯已经过期（{reason}），日报明日方舟下期：{nxt[5:] or '没有这一行'}")
    if value.startswith("没用上"):
        return None          # nothing to say: no newsletter, or none with new operators
    if shown:
        return mc.Result(mc.PASS, f"日报明日方舟下期：{nxt[5:]}（{where}）")
    return mc.Result(mc.FAIL, f"官网通讯给了「{value[:80]}」，日报明日方舟下期却是：{nxt or '没有这一行'}")


@mc.check("#9", "「明天开新卡池」群播报不带没有名字的", "B", "banners")
def _nameless(ctx):
    tr, now = ctx.get("trace"), ctx.get("now")
    nxt = getattr(tr, "nexts", None) or {}
    if not isinstance(now, datetime):
        return None
    day = (now + timedelta(days=1)).date()
    blank = [(g, w) for g, (w, who) in nxt.items()
             if isinstance(w, datetime) and w.date() == day and not who]
    if not blank:
        return None          # the trigger: a next entry for tomorrow that has no name
    from ark_relay.features.banners import group_notice, opening_tomorrow  # noqa: PLC0415
    title, body = group_notice(opening_tomorrow(now, nxt))
    said = "、".join(f"{g} {w:%m-%d %H:%M}" for g, w in blank)
    leaked = [g for g, _ in blank if g in title]
    if leaked:
        return mc.Result(mc.FAIL, f"没有名字的 {said} 进了群播报：{title}｜" + " / ".join(body.splitlines()))
    return mc.Result(mc.PASS, f"{said} 没有名字（下一个卡池官方还没公告），没进群播报；"
                     + (f"群播报：{title}" if title else "明天没有要播报的卡池"))


@mc.check("#58", "库街区没有那一帖时不单独报错", "A", "banners")
def _kuro_door(ctx):
    tr = ctx.get("trace")
    born = getattr(tr, "born", None)
    since = datetime.fromtimestamp(born, tz=SERVER_TZ) if isinstance(born, (int, float)) else _now(ctx)
    bad, _notes = _pb_lines(ctx, since, ("ark.banners",), old=_rx(r"^库街区官方资讯里没找到"))
    kuro = _doors(tr).get("库街区")
    if bad:
        return mc.Result(mc.FAIL, "；".join(bad))
    if kuro is None or kuro.startswith("取不到"):
        return None          # the door was not asked, or the list itself failed (not this item)
    if kuro == "没有这一帖":
        return mc.Result(mc.PASS, f"库街区这次没有这一帖，只记了日志、没进群；哔哩哔哩：{_doors(tr).get('B 站', '没去取')}")
    return mc.Result(mc.PASS, f"库街区官方资讯里找到了这一帖：{kuro}")


# The three checks below hold what the section ends with, whatever went wrong on the
# way. The user, 2026-11-08 00:15, after 明河「烟火邀星河」 was lost for three days
# with no alarm at all, in his words: 「有很多问题他根本不报」 (many faults are never reported).

@mc.check("#66", "卡池几个来源互相核对，对不上的都已经补上", "A", "banners")
def _no_open_mismatch(ctx):
    checks = [str(c) for c in getattr(ctx.get("trace"), "checks", None) or []]
    if not checks:
        return None          # nothing was cross-checked this time
    bad = [c for c in checks if "✗" in c]
    # 「已按公告补正」: a wiki's own bookkeeping opening replaced with the first-hand one (banners.crosscheck_fix)
    filled = [c for c in checks if ("补进当期" in c or "补回当期" in c or "补正" in c) and "✗" not in c]
    if bad:
        return mc.Result(mc.FAIL, f"{len(bad)} 条对不上：" + "；".join(bad[:3]))
    return mc.Result(mc.PASS, f"{len(checks)} 条核对都对得上"
                     + (f"，其中 {len(filled)} 条是官方来源补上的：" + "；".join(filled[:2]) if filled else ""))


def _block_says(text: str, game: str, pool: str) -> "str | None":
    """How the game's block treats the open banner `pool`: None when a 当期 line
    names it, else the lines it has instead."""
    lines = _block(text, game)
    if any(ln.startswith("· 当期：") and pool and pool in ln for ln in lines):
        return None
    return " / ".join(ln.strip() for ln in lines if ln.startswith("· 当期") or "没读到" in ln) or "没有这一块"


@mc.check("#67", "官方写着正在开的新角色卡池，日报当期都写上了", "A", "banners")
def _opens_shown(ctx):
    tr, text = ctx.get("trace"), str(ctx.get("text") or "")
    opens = getattr(tr, "opens", None) or []
    if not opens:
        return None          # no official source had a new-character banner open
    bad, ok, omitted = [], [], []
    for game, pool, who, start, end, by in opens:
        said = _block_says(text, game, pool)
        if said is None:
            ok.append(f"{game}「{pool}」")
        elif said == "没有这一块":
            # 日报白名单：未读到该游戏卡池时日报严格省略整块（报错已直推企微群），绝不写「当期无新角色卡池」误导。
            omitted.append(f"{game}「{pool}」（未读到已省略并报群）")
        else:
            bad.append(f"{game}「{pool}」{who}（{by}：{start or '版本更新后'} 开，{end or '结束未公布'} 结束）日报却是：{said}")
    if bad:
        return mc.Result(mc.FAIL, "；".join(bad[:3]))
    return mc.Result(mc.PASS, "日报当期写上了：" + "、".join(ok) + (f"；未读到已省略：{'、'.join(omitted)}" if omitted else ""))


@mc.check("#68", "预告过的卡池开了以后，日报没有变成「当期无新角色卡池」", "A", "banners")
def _announced_kept(ctx):
    rows = getattr(ctx.get("trace"), "continuity", None)
    if not rows:
        return None          # the gate did not run, or nothing announced has opened
    lost = [r[2] for r in rows if r[1] == "lost"]
    back = [r[2] for r in rows if r[1] == "recovered"]
    if lost:
        return mc.Result(mc.FAIL, "；".join(lost))
    return mc.Result(mc.PASS, "；".join(back + [r[2] for r in rows if r[1] == "ok"]))


# ------------------------------------------------------------------ the phone page and orders

_SK_KEYS = ("cred", "token", "dId", "uid", "efRole", "efServer")
# What web/stamina.js endfieldFromDungeon reads first from card/detail's detail.dungeon.
_DUNGEON_KEYS = ("curStamina", "maxStamina", "maxTs")


def _number(v) -> bool:
    try:
        float(v)
    except (TypeError, ValueError):
        return False
    return v not in ("", None) and not isinstance(v, bool)


@mc.check("#10", "森空岛会话交到手机，终末地体力那几项的名字认得出", "A", "phone_state")
def _skland(ctx):
    if ctx.get("why") != BOOT:
        return None          # the session is made once per process, for the boot push
    state = ctx.get("state")
    if not isinstance(state, dict):
        return mc.Result(mc.FAIL, "开机那份状态没做出来，看不到交给手机的森空岛会话")
    sk = (state.get("密钥") or {}).get("sk") if isinstance(state.get("密钥"), dict) else None
    if not isinstance(sk, dict):
        return mc.Result(mc.FAIL, "开机那份状态里没有森空岛会话")
    if sk.get("错误"):
        return mc.Result(mc.FAIL, f"森空岛会话没交给手机：{sk['错误']}")
    from ark_relay.features import resources  # noqa: PLC0415
    probe = resources.probe()
    made = _clock(probe.get("at")) if probe.get("at") else "?"
    lack = [k for k in _SK_KEYS if not sk.get(k)]
    if lack:
        return mc.Result(mc.FAIL, f"{made} 交给手机的森空岛会话缺 {'、'.join(lack)}"
                         + (f"（{probe['错误']}）" if probe.get("错误") else ""))
    dg = probe.get("dungeon")
    if not isinstance(dg, dict):
        return mc.Result(mc.FAIL, f"{made} 会话交给了手机，终末地体力没读到：{probe.get('错误') or '没读'}")
    miss = [k for k in _DUNGEON_KEYS if not _number(dg.get(k))]
    if miss:
        return mc.Result(mc.FAIL, f"森空岛给的终末地体力里没有 {'、'.join(miss)}，给的是："
                         + json.dumps(dg, ensure_ascii=False)[:160])
    return mc.Result(mc.PASS, f"{made} 森空岛会话交给手机（{len(_SK_KEYS)} 项都在）；森空岛给的终末地体力："
                     + " ".join(f"{k}={dg[k]}" for k in _DUNGEON_KEYS))


# modes._maybe_engage's two answers (a receipt keeps 200 characters, so no tail is required).
_SKIP_ENGAGED = re.compile(r"^今天（\d{4}-\d\d-\d\d）跳过队列「([^」]+)」：(.*?)(?:，过后自动恢复)?$")
_SKIP_FAILED = re.compile(r"^跳过「([^」]+)」失败：")


@mc.check("#15", "跳过队列的回执：成功写「调度程序已确认」，失败撤掉并给红回执", "B", "phone_state")
def _skip_receipt(ctx):
    state = ctx.get("state")
    relay = state.get("relay") if isinstance(state, dict) else None
    if not isinstance(relay, dict):
        return None
    mine = [r for r in relay.get("最近指令") or []
            if isinstance(r, dict) and r.get("action") == "skip_today" and not r.get("queued")]
    if not mine:
        return None
    r = mine[-1]             # the newest answer to the skip switch, and only that one
    text, at = str(r.get("text") or ""), str(r.get("at") or "")
    skipped = [str(q) for q in relay.get("今天跳过队列") or []]
    if m := _SKIP_FAILED.match(text):
        queue = m.group(1)
        evidence = f"{at} 回执（{'红' if r.get('ok') is False else '不是红的'}）：{text}；今天跳过的队列：{'、'.join(skipped) or '无'}"
        ok = r.get("ok") is False and queue not in skipped
    elif m := _SKIP_ENGAGED.match(text):
        if "已经是这个状态" in m.group(2):
            return None      # nothing was switched off: not this item's case
        evidence = f"{at} 回执：{text}"
        ok = r.get("ok") is True and "调度程序已确认" in m.group(2)
    else:
        return None          # the press's own answer, not the skip taking effect
    if mc.judged_before(ctx.get("state_dir"), "#15", evidence):
        return None
    return mc.Result(mc.PASS if ok else mc.FAIL, evidence)


@mc.check("#16", "红按钮等游戏、脚本和调度程序里的任务都没了才回「已停一切」", "B", "estop")
def _estop(ctx):
    res = ctx.get("result")
    if not res:
        return None
    ok, msg = res
    reads = ctx.get("reads") or {}
    if "alive" not in reads:
        return mc.Result(mc.FAIL, f"红按钮回了「{str(msg)[:60]}」，没留下它最后看到的程序和任务")
    alive, live = list(reads.get("alive") or []), reads.get("live")
    tasks = "问不到" if live is None else ("、".join(str(x[1]) for x in live) or "一个都没有")
    seen = (f"第 {reads.get('rounds', '?')} 轮核对看到：游戏和脚本 {'、'.join(alive) or '一个都没有'}；"
            f"调度程序里没结束的任务 {tasks}")
    if live is None:
        return mc.Result(mc.FAIL, f"红按钮问不到调度程序还有没有任务在跑，回的是「{str(msg)[:40]}」；{seen}")
    quiet = not alive and not live
    if ok:
        return mc.Result(mc.PASS if quiet else mc.FAIL, f"回「{str(msg)[:30]}」时{seen}")
    if quiet:
        return None          # not stopped for another reason (the echo farm), not this rule
    return mc.Result(mc.PASS, f"没停干净时没说「已停一切」，回的是「{str(msg)[:40]}」；{seen}")


@mc.check("#23", "跑着时按的手机指令先排队，跑完照样执行", "B", "phone_cmd")
def _phone_queue(ctx):
    from ark_relay.features import phone  # noqa: PLC0415
    via, action = ctx.get("via"), str(ctx.get("action") or "")
    name = texts.action_name(action) if action else "?"
    q = phone.CmdQueue(ctx.get("state_dir"))
    if via == "queued":
        if q.holds(ctx.get("raw") or {}):
            return None      # on disk; judged when it runs
        return mc.Result(mc.FAIL, f"「{name}」在跑的时候到了，却不在排队文件 {phone.CMD_QUEUE_FILE} 里")
    queued = ctx.get("queued_at")
    if via == "expired":
        return mc.Result(mc.FAIL, f"「{name}」{_clock(queued)} 排进 {phone.CMD_QUEUE_FILE}，"
                         "过了 24 小时都没轮到执行")
    if via != "drained":
        return None
    result = "改成了" if ctx.get("ok") else "没改成"
    return mc.Result(mc.PASS, f"「{name}」{_clock(queued)} 在跑时排进 {phone.CMD_QUEUE_FILE}，"
                     f"{_clock(time.time())} 跑完后执行，{result}：{str(ctx.get('msg') or '')[:60]}"
                     f"（还排着 {len(q)} 条）")


# ------------------------------------------------------------------ signatures, end of a shift

_PHONE = ("ark.phone",)


@mc.check("#39", "每一份状态都送到了手机（一并核 #42 #44 #47 #48 #51）", "A", "phone_state")
def _states(ctx):
    if not _shift_end(ctx) or "tally" not in ctx:
        return None          # the tally is kept by publish_state, the one call site
    t = ctx.get("tally") or {}
    since = _since(ctx)
    bad, notes = _pb_lines(ctx, since, ("ark.phone", "ark.service"),
                        old=_rx(r"^状态没能发到信箱", r"^第 \d+/\d+ 片没发出去",
                                r"^状态没能上报到手机（[^）]*；今天 ntfy 已发"),
                        alarm=_rx(r"^状态没存上腾讯云，这一份改走手机信箱发到了",
                                  r"^状态(的通知)?没发到手机信箱，状态已存到腾讯云",
                                  r"^状态没能上报到手机（[^；）]*）"))
    failed = t.get("failed") or []
    if not t.get("n"):
        bad.insert(0, "这一班一份状态都没上报（关机前那份也没算上）")
    if failed:
        bad.insert(0, f"{len(failed)} 份没送到：" + "；".join(f"{a}（{w}）{e}" for a, w, e in failed[:2]))
    routes = "、".join(f"{k} {v}" for k, v in (t.get("routes") or {}).items())
    head = (f"这一班（{since:%m-%d %H:%M} 起）上报状态 {t.get('n', 0)} 次，送到 {t.get('ok', 0)} 次"
            + (f"（{routes}）" if routes else ""))
    return _verdict(head, bad, notes)


@mc.check("#40", "手机信箱每天 250 条的额度中继没用完（一并核 #52 #54）", "A", "phone_state")
def _quota(ctx):
    if not _shift_end(ctx):
        return None
    q = ctx.get("quota") or {}
    if not q:
        return None
    from ark_relay.features import phone  # noqa: PLC0415
    raw = q.get("raw") or {}
    kinds = "、".join(f"{k} {v}" for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool))
    synced = raw.get("ntfy") if isinstance(raw.get("ntfy"), dict) else {}
    head = (f"手机信箱的这一天（世界时 {q.get('day')}）已用 {q.get('total')} 条，中继自己发了 {q.get('own')} 条"
            + (f"（{kinds}）" if kinds else "")
            + (f"，手机信箱自己的计数 {synced.get('n')} 条（{_clock(synced.get('at'))} 读）" if synced else ""))
    bad, notes = _pb_lines(ctx, _since(ctx), _PHONE, old=_rx(r"^ntfy 今天的 \d+ 条额度用完了"),
                        alarm=_rx(r"^ntfy 今天 \d+ 条的额度用完了"))
    if q.get("full"):
        bad.insert(0, f"手机信箱已经拒收：{phone.NTFY_DAILY_LIMIT} 条用完了")
    return _verdict(head + f"；到 {phone.HB_STOP_AT} 停心跳、到 {phone.NOTICE_STOP_AT} 停通知"
                    + ("" if q.get("full") else "，没用完"), bad, notes)


@mc.check("#41", "开机没读到的手机指令，连上后补读到", "B", "phone_state")
def _backlog(ctx):
    if not _shift_end(ctx):
        return None
    m = ctx.get("mailbox") or {}
    bad, notes = _pb_lines(ctx, _since(ctx), _PHONE, old=_rx(r"^取不到信箱里的指令"),
                        alarm=_rx(r"^开机时没读到手机信箱，手机通道连上后补读到了"))
    late = m.get("backlog_late") or {}
    if m.get("backlog_missed"):
        head = f"开机读信箱没成（{m.get('backlog_why') or '原因没记下'}）"
        bad.insert(0, "到关机前都没补读到，开机前手机上按的指令还没执行")
    elif late:
        head = f"开机读信箱没成（{late.get('why') or '原因没记下'}），{_clock(late.get('at'))} 补读到 {late.get('n')} 条"
    elif bad:
        head = "开机读信箱读到了"
    else:
        return None          # the boot read worked: nothing to make up for
    return _verdict(head, bad, notes)


@mc.check("#45", "手机通道断了自己连上（一并核 #49 #57）", "B", "phone_state")
def _stream(ctx):
    if not _shift_end(ctx):
        return None
    from ark_relay.features import phone  # noqa: PLC0415
    m = ctx.get("mailbox") or {}
    since = _since(ctx)
    drops = [d for d in m.get("drops") or [] if float(d.get("at") or 0) >= since.timestamp()]
    bad, notes = _pb_lines(ctx, since, _PHONE, old=_rx(r"^手机通道断了"),
                        alarm=_rx(r"^手机通道断过 ", r"^手机通道连不上 ntfy 已经"))
    if not drops and not bad:
        return None          # it never dropped this shift
    down = m.get("down_since")
    if not m.get("connected") and down:
        gone = _now(ctx).timestamp() - float(down)
        if gone >= phone.Mailbox.OUTAGE_SEC:
            bad.insert(0, f"关机前手机通道已经断了 {gone / 60:.0f} 分钟（{drops[-1]['why'] if drops else '原因没记下'}）")
        else:
            notes.insert(0, f"关机前正在重连（断了 {gone:.0f} 秒）")
    listed = "、".join(f"{_clock(d.get('at'))} {d.get('why')}" for d in drops[-3:])
    return _verdict(f"这一班手机通道断过 {len(drops)} 次（{listed}）", bad, notes)


@mc.check("#50", "三家停服维护公告读得到，两次全失败必须报群（一并核 #53）", "A", "phone_state")
def _maintenance(ctx):
    if not _shift_end(ctx):
        return None
    st = ctx.get("maintenance") or {}
    if not st:
        return None          # tomorrow's plan never asked for them this time
    bad, notes = _pb_lines(ctx, _since(ctx), ("ark.maintenance",), old=_rx(r"^维护公告：\S+ 取不到$"),
                        alarm=_rx(r"^维护公告：\S+ 官方公告取不到"))
    for game, row in st.items():
        if not row.get("last_ok"):
            bad.append(f"{game}最近一次（{_clock(row.get('last'))}）没取到：{row.get('why')}")
    base = _base(ctx, "maintenance")
    reads = "、".join(f"{g} {int(r.get('fetch') or 0) - int((base.get(g) or {}).get('fetch') or 0)} 次"
                     for g, r in st.items())
    n = (ctx.get("tally") or {}).get("n", 0)
    return _verdict(f"这一班状态上报 {n} 次，维护公告真去官网取了 {reads}（其余用一小时内取到的）", bad, notes)


@mc.check("#56", "心跳写得进腾讯云，连续写不进必须报群", "A", "phone_state")
def _cos_beat(ctx):
    if not _shift_end(ctx):
        return None
    from ark_relay.features import phone  # noqa: PLC0415
    h = dict(ctx.get("heartbeat") or {})
    base = _base(ctx, "heartbeat")
    for k in ("ok", "failed"):
        h[k] = int(h.get(k) or 0) - int(base.get(k) or 0)
    if not h.get("cos") or not (h.get("ok") or h.get("failed") or h.get("down_since")):
        return None          # no COS on this machine, or no beat this shift
    bad, notes = _pb_lines(ctx, _since(ctx), _PHONE, old=_rx(r"^心跳没能写到腾讯云 COS"),
                        alarm=_rx(r"^心跳从 .* 起一直写不进腾讯云"))
    down = h.get("down_since")
    if down:
        gone = _now(ctx).timestamp() - float(down)
        if gone >= phone.Heartbeat.COS_OUTAGE_SEC:
            bad.insert(0, f"关机前心跳已经 {gone / 60:.0f} 分钟写不进腾讯云（{h.get('why')}）")
        else:
            notes.insert(0, f"最后几跳没写上（{gone:.0f} 秒前起：{h.get('why')}），还在等它自己好")
    head = (f"这一班心跳写腾讯云 {h['ok'] + h['failed']} 次，写上 {h['ok']} 次"
            + (f"，最后一次写上在 {_clock(h.get('last_ok'))}" if h.get("last_ok") else ""))
    return _verdict(head, bad, notes)


_log_runs = logging.getLogger("ark.runs")

PASS, FAIL = mc.PASS, mc.FAIL
LINE_CHARS = 160


def _r(status: str, evidence: str) -> mc.Result:
    return mc.Result(status, evidence)


def _script(ctx, name: str) -> bool:
    rec = ctx.get("rec")
    return getattr(rec, "script", None) == name


def _unattended(ctx) -> bool:
    raw = ctx.get("raw") or {}
    return not (ctx.get("test_run") or raw.get("hand_started") or raw.get("manual_stop"))


def _lines(text: str, pattern) -> list[str]:
    """Every line of `text` matching `pattern` (a regex or a plain substring)."""
    rx = pattern if isinstance(pattern, re.Pattern) else re.compile(re.escape(pattern))
    return [ln for ln in (text or "").splitlines() if rx.search(ln)]


def _cut(line: str) -> str:
    line = line.strip()
    return line if len(line) <= LINE_CHARS else line[:LINE_CHARS] + "…"


def _around(line: str, needle: str, width: int = 60) -> str:
    """The line's leading time stamp and the stretch around `needle` (framework lines run to kilobytes)."""
    i = line.find(needle)
    if i < 0 or len(line) <= LINE_CHARS:
        return _cut(line)
    stamp = m.group(0) if (m := re.match(r"^\[[^\]]+\]", line)) else ""
    return f"{stamp} …{line[max(0, i - width):i + len(needle) + width].strip()}…"


def _first(text: str, pattern) -> str:
    got = _lines(text, pattern)
    return _cut(got[0]) if got else ""


def _last(text: str, pattern) -> str:
    got = _lines(text, pattern)
    return _cut(got[-1]) if got else ""


def _after(text: str, marker: str) -> str:
    """The part of `text` from the last line holding `marker` on ('' when none)."""
    i = text.rfind(marker)
    return text[text.rfind("\n", 0, i) + 1:] if i >= 0 else ""


# ------------------------------------------------------------------ OK-WW

WEEKLY = "Teleport to Boss Weekly Challenge"
_WEEKLY_ANY = re.compile(r"周本|FarmEchoTask")
_WEEKLY_CAPPED = re.compile(r"本周周本次数已领满|收取物资次数已达到上限|本周剩余可收取次数[：:]\s*0\s*/")


@mc.check("#4", "鸣潮周本打完自己领到奖励（领完回读本周剩余次数少了一次）", "A", "run")
def _c4(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    t = outcome._task_lines(ctx.get("log_text") or "")
    if WEEKLY not in t:
        return None
    c = outcome.weekly_claims(t)
    short = bool(outcome.WEEKLY_SHORT.search(t))
    stopped = outcome._WEEKLY_FAILED.search(t)
    incomplete = outcome.weekly_incomplete_reason(t, c)
    if c["verified"]:
        if stopped and not short:
            why = outcome.without_screen_dump(outcome._TRACEBACK_TAIL.sub("", stopped.group(1)))
            return _r(FAIL, f"这一趟按失败结束：{why}（领到了 {c['verified']} 次）")
        if incomplete:
            return _r(FAIL, incomplete)
        return _r(PASS, _first(t, outcome.WEEKLY_CLAIM_OK))
    if not c["attempted"] and (_WEEKLY_CAPPED.search(t) or short):
        # Already capped this week, or the game refused for want of waveplates: no
        # claim to make, so nothing here says whether claiming works (the run's
        # own result check says the waveplate case).
        return None
    return _r(FAIL, f"{_weekly_why(t, c)}；日志最后一行周本：{_last(t, _WEEKLY_ANY) or '（没有）'}")


def _weekly_why(text: str, c: dict) -> str:
    """Why a weekly run has no confirmed claim, in the result check's words (outcome.okww_checks)."""
    if stopped := outcome._WEEKLY_FAILED.search(text):
        return "这一趟按失败结束：" + stopped.group(1).strip()
    if c["attempted"]:
        return outcome.weekly_unverified(c)
    if "teleport_to_boss prepared as" not in text and not _PAGE_KNOWN.search(text):
        return "没进本，一次没打"
    if not outcome._WEEKLY_FOUGHT.search(text):
        return "进了本，但日志里没有开打的记录：一次没打"
    return "周本打了，但没有领奖那一步：奖励没拿到"


DIALOG = "限时提前开放的剧情提示框，点确认前往"
_PAGE_KNOWN = re.compile(r"限时提前开放：确认后是(这个 Boss 的选等级页|队伍界面)")
_PAGE_UNKNOWN = re.compile(r"进本：.*这一屏认不出|限时提前开放确认后是传送地图")
_FOUGHT = re.compile(r"FarmEchoTask:enter combat|周本领奖：认出弹窗|周本领奖：回读确认领到")
_LEGIT_STOP = re.compile(r"本周周本次数已领满|结晶波片不足|波片不足挡住开启挑战")


@mc.check("#27", "鸣潮周本「确认前往」后读屏认出选等级页并进本（日常早班自动那趟）", "A", "run")
def _c27(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    if WEEKLY not in text or DIALOG not in text:
        return None
    tail = _after(text, DIALOG)
    page = _first(tail, _PAGE_KNOWN)
    if not page:
        rest = tail.splitlines()[1:]
        seen = _first(tail, _PAGE_UNKNOWN) or (_cut(rest[0]) if rest else "确认前往之后日志没有下一行")
        return _r(FAIL, f"点了确认前往，之后没认出选等级页：{seen}")
    if _FOUGHT.search(tail) or _LEGIT_STOP.search(tail):
        then = _first(tail, _FOUGHT) or _first(tail, _LEGIT_STOP)
        return _r(PASS, f"{page[:90]}…；之后：{then}")
    return _r(FAIL, f"认出了选等级页，但之后没开打：{_last(tail, _WEEKLY_ANY) or page}")


def _nest_settings(ctx) -> "tuple[bool | None, str]":
    o = ctx.get("outcome") or {}
    return o.get("expect_nest"), str(o.get("only_nest") or "").strip()


@mc.check("#5", "鸣潮残象聚落「只刷指定点位」的改动在真跑里贴上了", "A", "run")
def _c5(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    expect, only = _nest_settings(ctx)
    if not expect or not only or "NightmareNestTask" not in text:
        return None
    if outcome._NEST_FILTER_MISSING in text:
        return _r(FAIL, _first(text, outcome._NEST_FILTER_MISSING))
    if line := _first(text, outcome._NEST_FILTER_LINE):
        return _r(PASS, line)
    if opened := _first(text, "NightmareNestTask:opened gray_book_boss"):
        return _r(FAIL, f"打开了残象聚落页，日志里却没有「nightmare nest: 只刷 […]」（设置是只刷{only}）：{opened}")
    # Fought a nest with no filter line: the copy was not in that run, whatever upstream now
    # logs when it opens the page (audit 11-08 C-11). A run cut short before the nests (no
    # page, no fight) did not exercise the copy and says nothing, as before: the filter line
    # is written while the nests are picked (ark_overrides only_names, from wanted_rows).
    if fought := _first(text, _NEST_COMBAT):
        return _r(FAIL, f"进了残象聚落的战斗，日志里却没有「nightmare nest: 只刷 […]」（设置是只刷{only}）：{fought}")
    return None


_NEST_COMBAT = outcome._NEST_ENGAGED  # the verdict's own fight lines
_NEST_FARMED_LABEL = "残象聚落"


def _nest_verdict(ctx):
    for c in (ctx.get("outcome") or {}).get("checks") or []:
        if c.label.startswith("残象聚落") and not c.label.startswith(("残象聚落只刷", "残象聚落没进")):
            return c
    return None


def _nest_step(ctx) -> str:
    for s in (ctx.get("raw") or {}).get("okww_steps") or []:
        if s.startswith(("残象聚落", "梦魇巢穴")):
            return s
    return ""


@mc.check("#25", "鸣潮残象聚落只有真进了战斗才算刷了", "A", "run")
def _c25(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    verdict, step = _nest_verdict(ctx), _nest_step(ctx)
    if verdict is None and not step:
        return None
    combat = _first(text, _NEST_COMBAT)
    # Booked as farmed: the result check's plain 「残象聚落」 that is ok, or the daily
    # step that is the bare name (any note in brackets says it was not farmed),
    # the adapted-filter note excepted.
    plain = re.sub(r"（只刷指定点位的过滤按 OK-WW 新版适配，请核对）$", "", step)
    booked = (verdict is not None and verdict.ok and verdict.label == _NEST_FARMED_LABEL) \
        or plain in ("残象聚落", "梦魇巢穴")
    if booked and not combat:
        seen = _last(text, re.compile(r"nightmare nest|NightmareNestTask")) or "（巢穴任务一行都没有）"
        return _r(FAIL, f"一次没进战斗，却记成刷了（结果核对：{verdict.label if verdict else '—'}，"
                        f"日报：{step or '—'}）；巢穴最后一行：{seen}")
    if combat:
        return _r(PASS, combat)
    why = verdict.detail if verdict is not None else step
    line = _first(text, outcome._NEST_UNREACHABLE) or _first(text, outcome._NEST_ALL_FULL) \
        or _first(text, outcome._NEST_FILTER_MISSING) or _last(text, "NightmareNestTask")
    return _r(PASS, f"没进战斗，也没记成刷了（{why}）：{line or '—'}")


FIND_NEST = "NightmareNestTask.find_nest"
# A report written this long before the run's first line still belongs to its start
# (AUTO-MAS starts OK-WW first, the overrides run as ok-script loads).
_REPORT_EARLY = timedelta(minutes=5)


def _log_says(text: str) -> str:
    if outcome._NEST_FILTER_MISSING in text:
        return "没装上"
    if outcome._NEST_ADAPTED in text:
        return "按新版适配装上"
    if outcome._NEST_FILTER_LINE.search(text):
        return "装上"
    return ""


def _report_says(rep: dict) -> str:
    if rep.get("error"):
        return "出错（一条都没生效）"
    whats = lambda key: {str((x or {}).get("what")) for x in rep.get(key) or [] if isinstance(x, dict)}  # noqa: E731
    if FIND_NEST in whats("adapted"):
        return "按新版适配装上"
    if FIND_NEST in whats("skipped"):
        return "没装上"
    return "装上" if FIND_NEST in (rep.get("applied") or []) else "没装上"


@mc.check("#26", "鸣潮 find_nest 装没装上：这一趟日志和覆盖层报告说的一样", "A", "run")
def _c26(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    log_says = _log_says(text)
    if not log_says:
        return None
    rec = ctx["rec"]
    rep = ctx.get("overlay") or {}
    if not rep:
        return _r(FAIL, f"日志说 find_nest {log_says}，覆盖层报告（ark-okww-overlay.json）读不到")
    try:
        written = datetime.fromisoformat(str(rep.get("written")))
    except (TypeError, ValueError):
        return _r(FAIL, f"覆盖层报告没有写入时间：{str(rep)[:120]}")
    if written > rec.finished + timedelta(minutes=1):
        return None          # a later OK-WW start rewrote it; that start's own run is judged
    if written < rec.started - _REPORT_EARLY:
        return _r(FAIL, f"这一趟 OK-WW 启动没写覆盖层报告（盘上那份是 {written:%m-%d %H:%M:%S} 写的）；"
                        f"日志说 find_nest {log_says}")
    rep_says = _report_says(rep)
    line = (_first(text, outcome._NEST_FILTER_MISSING) or _first(text, outcome._NEST_ADAPTED)
            or _first(text, outcome._NEST_FILTER_LINE))
    ev = f"日志：{line}；覆盖层报告（{written:%H:%M:%S} 写）：find_nest {rep_says}"
    same = rep_says == log_says or (log_says == "装上" and rep_says == "按新版适配装上")
    return _r(PASS if same else FAIL, ev if same else "对不上——" + ev)


# ------------------------------------------------------------------ MaaEnd

SEEN_FILE = "machinecheck-runs.json"
# A run id as HELD_28 keys them ("2026-10-08/endfield/MaaEnd-06-31-06"): what a file that
# no longer parses is searched for, to name the held FAILs it took with it.
_RUN_ID = re.compile(r'"(\d{4}-\d{2}-\d{2}/[^"/]+/[^"/]+-\d{2}-\d{2}-\d{2})"\s*:\s*\{')
# machinecheck-runs.json files set aside as unreadable: path -> the mtime that was
# (statestore.set_aside); dropped once the file reads again.
_CORRUPT_SAID: dict[str, float] = {}
# The held #28 FAILs of the last good read, per file: named when a settle cannot read it.
_HELD_KNOWN: dict[str, list] = {}
# Files whose settle-blocking unreadability _settle_held has said (held_stuck), and
# why the last read of each failed (for the ERROR lines).
_STUCK_SAID: set = set()
_READ_ERR: dict[str, str] = {}
# Per thread: the files whose lock outlasted every wait in the booking or tick open on
# it (one_pass), read without waiting for the rest of it; None outside one.
_PASS = threading.local()


@contextmanager
def one_pass():
    """One booking (handle._handle) or one tick's _flush_pending: once a read of
    machinecheck-runs.json has waited out every mc.LOCK_WAITS and still failed, later
    reads of it in the same pass fail at once instead of waiting again - about six
    reads a booking, 0.5 s each, held the engine thread ~3 s while a lock lasted.
    Nested passes are the outer one."""
    if getattr(_PASS, "gave_up", None) is not None:
        yield
        return
    _PASS.gave_up = set()
    try:
        yield
    finally:
        _PASS.gave_up = None


def _state_read(state_dir) -> "dict | None":
    """state/machinecheck-runs.json as a table, read as UTF-8 with or without a BOM (a
    hand edit in Notepad adds one). {} when it is not there yet.

    A read that fails is tried again after each of mc.LOCK_WAITS (a Windows sharing
    violation lasts a moment); one still failing is None: the file is there and may
    hold anything, so nobody may write over it. A file that keeps reading as broken
    JSON or as something other than a table is copied aside (statestore.set_aside:
    <name>.corrupt-<mtime>), said in one ERROR naming the held #28 FAILs in it, and
    read as {} - the next write replaces it. Until 2026-10-17 it was None forever:
    every settle stopped without a word and every later write was an ERROR."""
    from ark_relay.core import statestore  # noqa: PLC0415
    if not state_dir:
        return None                 # nowhere to read it from: unreadable, nothing to wait for
    f = Path(state_dir) / SEEN_FILE
    key = str(f)
    gave_up = getattr(_PASS, "gave_up", None)
    for wait in (*mc.LOCK_WAITS, None):
        text, broken = "", None
        try:
            text = f.read_text(encoding="utf-8-sig")
            data = json.loads(text)
        except FileNotFoundError:
            _CORRUPT_SAID.pop(key, None)
            return {}
        except OSError as exc:
            if wait is None or (gave_up is not None and key in gave_up):
                _READ_ERR[key] = f"{type(exc).__name__}: {exc}"
                if gave_up is not None:
                    gave_up.add(key)
                return None
            time.sleep(wait)
            continue
        except ValueError as exc:       # broken JSON, or bytes that are not UTF-8
            broken = exc
        else:
            if isinstance(data, dict):
                _CORRUPT_SAID.pop(key, None)
                _STUCK_SAID.discard(key)    # a stretch it could not be read in is over
                if gave_up is not None:
                    gave_up.discard(key)
                held = data.get(HELD_28)
                _HELD_KNOWN[key] = sorted(held) if isinstance(held, dict) else []
                return data
            broken = TypeError(f"不是一张表（{type(data).__name__}）")
        try:
            mtime = f.stat().st_mtime
        except OSError:
            mtime = -1.0
        if _CORRUPT_SAID.get(key) == mtime:
            return {}               # set aside already and said once
        if wait is not None:
            time.sleep(wait)        # a hand edit being saved: read it again first
            continue
        where = statestore.set_aside(f, mtime, _CORRUPT_SAID)
        lost = list(dict.fromkeys(_RUN_ID.findall(text)))
        _log_runs.error("上机核对：%s 读出来坏了（%s: %s），按空的重来；%s；%s", SEEN_FILE, type(broken).__name__,
                  broken, where, f"里面等重试的 #28 结论 {'、'.join(lost)} 不会再结，要人看一眼"
                  if lost else "里面等重试的 #28 结论（如有）不会再结，要人看一眼")
        return {}
    return None


def _state_get(state_dir, key: str):
    """One key of state/machinecheck-runs.json (_state_read); None when missing or unreadable."""
    data = _state_read(state_dir)
    return data.get(key) if data else None


def _state_update(state_dir, change, what: str = "", quiet_unheld: bool = False) -> bool:
    """Read state/machinecheck-runs.json once (_state_read), apply `change(data)` to it
    and write it back. True when the file was written, or `change` returned False:
    nothing to change, nothing written. One that cannot be read is never rewritten from
    nothing - that wiped every other key: the held #28 FAILs, the seen lists, the miss
    counts - and the caller is told it was not written. A failed read or write is an
    ERROR (errwatch: the group hears of it), never raised; the write is atomic, so
    nothing of a failed one landed, and a Windows lock on it is waited out first
    (mc.write_waiting); `what` says on that ERROR what was not written.

    `quiet_unheld`: a failed read is no ERROR when the last good read held no #28 FAIL
    - for a change that only touches held FAILs (covered_28), nothing it could have
    written is lost (as held_stuck)."""
    data = _state_read(state_dir)
    if data is None:
        if quiet_unheld and state_dir and _HELD_KNOWN.get(str(Path(state_dir) / SEEN_FILE)) == []:
            return False
        _log_runs.error("上机核对：%s 读不出来（%s），%s没写，免得把里面别的记录冲掉", SEEN_FILE,
                  _READ_ERR.get(str(Path(state_dir) / SEEN_FILE), "原因不明") if state_dir
                  else "没给 state 目录", what or "这次")
        return False
    f = Path(state_dir) / SEEN_FILE
    if change(data) is False:
        return True
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        mc.write_waiting(f, json.dumps(data, ensure_ascii=False))
    except OSError as exc:
        _log_runs.error("上机核对：%s 写不进去（%s: %s），%s没写", SEEN_FILE, type(exc).__name__, exc, what or "这次")
        return False
    held = data.get(HELD_28)
    _HELD_KNOWN[str(f)] = sorted(held) if isinstance(held, dict) else []
    return True


def _state_set(state_dir, key: str, value) -> bool:
    """Set one key of state/machinecheck-runs.json (_state_update). True when the file
    was written; a caller whose push depends on it says so."""
    return _state_update(state_dir, lambda data: data.__setitem__(key, value))


def _state_bump(state_dir, key: str, change, what: str) -> "int | None":
    """Counter `key` set to change(what is on file, as an int) in one read and one write
    (_state_update); the new value, or None when the file could not be read - never a
    count restarted from 0 because one read failed (a streak of misses then started
    over at 1, until 2026-10-17)."""
    box = {}

    def bump(data):
        try:
            was = int(data.get(key) or 0)
        except (TypeError, ValueError):
            was = 0
        box["n"] = data[key] = change(was)

    _state_update(state_dir, bump, what)
    return box.get("n")


def held_stuck(state_dir) -> "list | None":
    """The held #28 FAILs on file, or None when machinecheck-runs.json cannot be read;
    then one ERROR, until it reads again, names the ones of the last good read, which
    cannot be settled meanwhile (runchecks._settle_held). Silent when the last good
    read held nothing: nothing is stuck behind it, and a hold kept meanwhile cannot be
    written (_state_update), so its FAIL is pushed at once (_hold_28)."""
    data = _state_read(state_dir)
    if data is not None:
        held = data.get(HELD_28)
        return sorted(held) if isinstance(held, dict) else []
    if not state_dir:
        return None
    key = str(Path(state_dir) / SEEN_FILE)
    known = _HELD_KNOWN.get(key)
    if known != [] and key not in _STUCK_SAID:
        _STUCK_SAID.add(key)
        _log_runs.error("上机核对：%s 读不出来（%s），等重试的 #28 结论结不了，读得出来再结；%s", SEEN_FILE,
                  _READ_ERR.get(key, "原因不明"),
                  f"上次读到在等的是 {'、'.join(known)}" if known else "这次进程里没读到过它，不知道有哪几条在等")
    return None


def _seen(state_dir, cid: str) -> "set | None":
    """Run ids check `cid` has given its verdict on already; None when that cannot be
    read, so nothing is judged twice on a failed read (it was an empty set until
    2026-10-17: #6 / #24a judged a settled restart again)."""
    data = _state_read(state_dir)
    if data is None:
        return None
    got = data.get(cid)
    return set(got) if isinstance(got, list) else set()


def _mark_seen(state_dir, cid: str, run_ids: list) -> None:
    """Add `run_ids` to check `cid`'s seen list, keeping the last 50 - on the list as
    read in the same write, so a failed read never cuts it to `run_ids`."""
    def add(data):
        got = data.get(cid)
        data[cid] = ((list(got) if isinstance(got, list) else []) + list(run_ids))[-50:]
    _state_update(state_dir, add)


def _about_restart(row: dict, run_id: str, version: str) -> bool:
    """Whether a group alarm copy is about the MaaEnd update restart `run_id`: it names
    the record, or the build it restarted into (every failure text of such a record
    says 「MaaEnd 装新版 <build> 后自己重启」, handle._mark_update_restart)."""
    title, text = str(row.get("title") or ""), str(row.get("text") or "")
    stem = run_id.rsplit("/", 1)[-1]
    return (row.get("evidence_run") == run_id or stem in title or stem in text
            or bool(version) and f"装新版 {version}" in title + text)


def _update_restart_check(ctx, cid: str):
    """#6 / #24a: a MaaEnd attempt spent restarting into its new build, in a shift whose
    round already got everything done, ends without any alarm about it: none in
    the copies of what went to the group (state/alerts, errwatch's pushes included)
    since it started, and no relay WARNING / ERROR naming it in this handling.

    Judged once per restart, once it is settled - no longer held for a later push
    (a held one is let go at the push step, handle._update_restart_done). Every
    restart of the batch is judged before the verdict: they are all marked seen
    here, so one returned early on the first FAIL (until 2026-10-13) left the
    others never judged."""
    if not _script(ctx, "MaaEnd"):
        return None
    state_dir = ctx.get("state_dir")
    seen = _seen(state_dir, cid)
    todo = {rid: x for rid, x in (ctx.get("update_restarts") or {}).items()
            if x.get("done") and not x.get("held") and rid not in (seen or ())}
    if not todo:
        return None
    if seen is None:
        # Which of them were judged already cannot be told: judged at the next booking
        # whose read gets through, none of them marked seen meanwhile.
        _log_runs.info("上机核对 %s：%s 读不出来，%s 这一回先不判", cid, SEEN_FILE, "、".join(todo))
        return None
    _mark_seen(state_dir, cid, list(todo))
    passed, failed = [], []
    for rid, x in todo.items():
        stem, version = rid.rsplit("/", 1)[-1], str(x.get("version") or "")
        head = f"{stem} 装新版 {version} 后自己重启，同班 {str(x['done']).rsplit('/', 1)[-1]} 已经做完"
        try:
            since = datetime.fromisoformat(str(x.get("started")))
        except ValueError:
            since = ctx["rec"].started
        if rows := [a for a in _day_alerts(state_dir, since) if _about_restart(a, rid, version)]:
            failed.append(f"{head}，却进了群：{rows[0].get('ts')} 「{rows[0].get('title')}」")
            continue
        noisy = [e for e in ctx.get("relay_errors") or []
                 if stem in e.get("msg", "") and not e.get("pushed")]
        if noisy:
            failed.append(f"{head}，中继却记了一条会进群的报错：{_cut(noisy[0]['msg'])}")
            continue
        passed.append(head)
    if failed:
        return _r(FAIL, "；".join(failed))
    return _r(PASS, "；".join(passed) + "：放下了，报警抄送里没有它，也没记报错")


@mc.check("#6", "终末地做完以后装新版自己重启，不再报「最终失败」也不进群", "A", "run")
def _c6(ctx):
    return _update_restart_check(ctx, "#6")


@mc.check("#24a", "三处误报修复之一：终末地做完后装新版重启不进群", "A", "run")
def _c24a(ctx):
    return _update_restart_check(ctx, "#24a")


def _task_window(text: str, task: str) -> "tuple[datetime, datetime] | None":
    return cm.task_times(text).get(task)


ENV = "环境监测"
# Where the framework-log stretch of each 环境监测 run is kept, newest ENV_KEEP files.
ENV_DIR = "machinecheck-env"
ENV_KEEP = 10
ENV_LINES = 4000          # head and tail kept of a longer stretch
# 环境监测 runs in a row with no framework-log lines in their window before that
# missing evidence is a FAIL of its own (MaaFW writes maafw.log on every run).
ENV_MISS_FAIL = 2
_FW_NODE = re.compile(r'"name":"([^"]+)"')
_FW_ENTRY = re.compile(r'"entry":"([^"]+)"')


def _keep_env_lines(state_dir, rec, t0: datetime, t1: datetime, lines: list[str]) -> str:
    """Write the stretch to state/machinecheck-env/<run>.log; returns that path under the state folder."""
    from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
    d = Path(state_dir) / ENV_DIR
    name = rec.run_id.replace("/", "_") + ".log"
    body = lines
    if len(lines) > ENV_LINES:
        half = ENV_LINES // 2
        body = lines[:half] + [f"…（中间 {len(lines) - ENV_LINES} 行没留）…"] + lines[-half:]
    head = f"# {rec.run_id} 环境监测 {t0:%Y-%m-%d %H:%M:%S} → {t1:%H:%M:%S}，框架日志 {len(lines)} 行"
    try:
        d.mkdir(parents=True, exist_ok=True)
        atomic_write_text(d / name, "\n".join([head, *body]) + "\n")
        for old in sorted(d.glob("*.log"), key=lambda f: f.stat().st_mtime)[:-ENV_KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        return ""
    return f"{ENV_DIR}/{name}"


@mc.check("#7", "终末地环境监测那一段的框架日志每趟都收下来（拿到真实样本、定下判据之前只收不判）", "B", "run")
def _c7(ctx):
    """Capture only. Whether 环境监测 did its job is #28's verdict since 10-16
    (maaend_fwlog.task_verdict over TRAIL_TASKS, with #28's own 「没证据」 dedup and hold);
    judging it here too would push one cause twice (audit 11-08 C-12 asked for it, declined).
    When this was written it could not be told: it writes no line
    of its own in the AUTO-MAS log even on a run that took 110 s (2026-09-04), and the
    repo holds no framework-log sample and no pipeline of it (only its locale strings:
    per-route 「…任务失败」 and 「当前任务尚未适配，仅接取并追踪」). So each run's
    framework-log stretch from its 「任务开始」 to its 「任务完成」 is kept in
    state/machinecheck-env/ and named in the daily section (PASS = captured, never
    pushed), until a real sample states what failing looks like. No lines in the
    window: not judged; ENV_MISS_FAIL runs in a row without them is a FAIL."""
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    raw = ctx.get("raw") or {}
    span = _task_window(text, ENV)
    if span is None or ENV in (raw.get("maaend_tasks_skipped") or {}):
        return None
    t0, t1 = span
    state_dir = ctx.get("state_dir")
    lines, why = cm.maafw_window(ctx.get("maaend_dir"), t0, t1)
    if not lines:
        misses = _state_bump(state_dir, "#7-miss", lambda n: n + 1, "#7 连着几趟没框架日志")
        if misses is None:
            _log_runs.info("上机核对 #7：%s 这一趟的环境监测没有框架日志，连着几趟数不出来（%s 读不出来），先不判",
                     getattr(ctx.get("rec"), "run_id", ""), SEEN_FILE)
            return None
        if misses >= ENV_MISS_FAIL:
            return _r(FAIL, f"连续 {misses} 趟环境监测（这一趟 {t0:%m-%d %H:%M:%S}→{t1:%H:%M:%S}）"
                            f"那一段的框架日志都没有：{why}")
        return None
    _state_set(state_dir, "#7-miss", 0)
    kept = _keep_env_lines(state_dir, ctx["rec"], t0, t1, lines)
    nodes = list(dict.fromkeys(n for ln in lines for n in _FW_NODE.findall(ln)))
    entries = list(dict.fromkeys(n for ln in lines for n in _FW_ENTRY.findall(ln)))
    secs = int((t1 - t0).total_seconds())
    shot = (raw.get("tasks_shot_files") or {}).get(ENV)
    return _r(PASS, f"只收不判：环境监测 {secs} 秒（{t0:%H:%M:%S}→{t1:%H:%M:%S}），框架日志 {len(lines)} 行"
                    + (f"，任务 {'、'.join(entries[:3])}" if entries else "")
                    + f"，节点 {len(nodes)} 个" + (f"：{'、'.join(nodes[:6])}" + ("…" if len(nodes) > 6 else "") if nodes else "")
                    + (f"；全文 {kept}" if kept else "；全文没存下")
                    + (f"；结束截图 {shot}" if shot else ""))


# The four tasks and how each is judged from MaaFW's own steps live in maaend_fwlog
# (TRAIL_TASKS, TRAIL_RULES, task_verdict, trail_table), shared with the ledger's
# 「没证据」 rule, which reads the same verdicts booked in raw['tasks_trail'].
SHOT_TASKS = maaend_fwlog.TRAIL_TASKS
# Runs in a row with none of the four in MaaFW's log before that is a FAIL of its own
# (as #7: MaaEnd clears its debug folder when it restarts). The ledger waits as long.
SHOT_MISS_FAIL = maaend_fwlog.TRAIL_MISS_FAIL


def _shot_note(state: Path, rel: str, ended) -> str:
    """The desktop picture of this task, said for what it is: task_shots takes it after
    the task's end event through the desktop agent, 5-8 s late (2026-10-08, -11, -16:
    file times against file names), while MaaEnd posts the next task within 2 ms and
    its first input lands 0.1-1.5 s later (maafw.log 2026-10-16). So it shows the
    next task, never this one's result screen."""
    p = state / rel
    try:
        taken = datetime.fromtimestamp(p.stat().st_mtime)
    except (OSError, ValueError):
        return ""
    where = f"{Path(rel).parent.as_posix()} 里 {p.stem[:6]} 那张"
    if ended is None:
        return f"桌面截图 {where} 只作参考"
    late = (taken - ended).total_seconds()
    if late <= 0:
        return f"桌面截图 {where} 是它结束前拍的"
    return f"桌面截图 {where} 是它结束后 {late:.0f} 秒才拍到的，那时下一个任务已经开始，只作参考"


@mc.check("#28", "终末地送礼/装备制造/转交委托/环境监测每趟在终末地自己的记录里看得到做成了（或没东西可做）", "A", "run")
def _c28(ctx):
    """Judged from MaaFW's own steps of each task (maaend_fwlog.task_verdict), not from the desktop
    picture. Until 2026-10-16 this passed when the picture file existed, and the
    pictures of 10-08 showed the next task: 093302-赠送干员礼物.png the 装备制造 page,
    093322-装备制造.png 拜访好友, 103416-装备制造.png the bare desktop after MaaEnd
    stopped itself (maaend_fwlog.ABORT_STEP; verify ledger #28). The picture is still
    named, with how late it was.

    The verdicts are the ones booked with the record (raw['tasks_trail'],
    alarm.records._mark_task_trails), so MaaFW's log is read once a run; a record
    without them is read here the same way.

    A task another MaaEnd run of the same day did (or found nothing to do in) does not
    need a person: it is no FAIL, its line says which run did it, and the run's own
    ledger row keeps the cause for the daily report (core.maaend_unverified). On
    2026-10-08 MaaEnd stopped itself in 装备制造 at 10:34:16 (MaaEnd-06-31-06) after
    the 09:33 run (MaaEnd-05-29-15) had crafted. Only runs booked before this one are
    seen: a later run that does the task comes after this verdict. Such a verdict is a
    PASS marked healed, which the daily section says as failed and made up for.

    A task MaaFW's log does not cover (maaend_fwlog.trail_unread: a rotated or cleared
    log beginning inside the run, or none of the four in it) is not judged until that
    has happened SHOT_MISS_FAIL runs in a row, as the ledger waits; the rest of the run
    is judged as usual.

    A FAIL whose tasks are all on the 「没证据」 alarm sent (or queued) while this record
    was booked (ctx['unverified_alarm'], pushes._push_unverified) is not pushed again:
    that alarm carries MaaEnd's own verdict and reason for each of them
    (maaend_unbacked_why), so one cause goes to the group as one message; the FAIL
    stays on record. An alarm for the same items sent earlier that day does not count:
    that one was about another run. A FAIL about a run held for its retry - how the
    machine books MaaEnd stopping itself: ok=False, every later task failed
    (MaaEnd-06-31-06) - waits for the hold to end (_fail_28, settle_28)."""
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    raw = ctx.get("raw") or {}
    state_dir = ctx.get("state_dir")
    if "tasks_trail" in raw:
        table = raw.get("tasks_trail") or {}
        misses = int(raw.get("tasks_trail_miss") or 0)
    else:
        times = cm.task_times(text)
        skipped = raw.get("maaend_tasks_skipped") or {}
        table, why = maaend_fwlog.trail_table(ctx.get("maaend_dir"),
                                              {t: v for t, v in times.items() if t not in skipped}, text)
        misses = (_state_bump(state_dir, "#28-miss", lambda n: n + 1 if why else 0, "#28 连着几趟没盖到")
                  if table else 0)
        if misses is None:
            # How many runs in a row cannot be told: this run's unread tasks wait.
            _log_runs.info("上机核对 #28：%s 连着几趟没盖到数不出来（%s 读不出来），没盖到的先不判",
                     getattr(ctx.get("rec"), "run_id", ""), SEEN_FILE)
            misses = 1 if why else 0
    done = [t for t in SHOT_TASKS if isinstance(table.get(t), dict)]
    if not done:
        return None
    unread = [t for t in done if misses and maaend_fwlog.trail_unread(table[t])]
    if unread and misses < SHOT_MISS_FAIL:
        # Not judged this run; said on the verdict's line when the rest is judged.
        done = [t for t in done if t not in unread]
        if not done:
            return None
        waits = f"{'、'.join(unread)} 这一趟终末地自己的记录没盖到，先不判"
    else:
        waits = ""
    if unread and len(unread) == len(done) and not waits:
        return _fail_28(ctx, done, f"连续 {misses} 趟，{'、'.join(done)} 在终末地自己的记录里都找不到，做成没有看不出来")
    files = raw.get("tasks_shot_files") or {}
    state = Path(state_dir or ".")
    good, bad, healed = [], [], False
    for t in done:
        e = table[t]
        t0, t1 = datetime.fromisoformat(e["t0"]), datetime.fromisoformat(e["t1"])
        line = f"{t}（{t0:%H:%M:%S}→{t1:%H:%M:%S}）"
        if not e.get("found"):
            line += (f"连续 {misses} 趟在终末地自己的记录里读不到" if t in unread
                     else "在终末地自己的记录里找不到")
        else:
            line += str(e.get("said") or "")
            ended = datetime.fromisoformat(e["ended"]) if e.get("ended") else None
            if note := (_shot_note(state, files[t], ended) if files.get(t) else ""):
                line += f"；{note}"
        if e.get("ok"):
            good.append(line)
        elif by := _done_elsewhere(ctx, t):
            # The work got done that day: no FAIL, but a session looks at why this run
            # did not do it (one 「自愈待查」 red item, techlog.self_heal).
            good.append(f"{line}；{by}，不用人管")
            healed = True
            rid = getattr(ctx.get("rec"), "run_id", "")
            _log_runs.info("上机核对 #28：%s 的%s没做成，%s，不进群，只进日报", rid, t, by)
            try:
                from ark_relay.core import statestore as techlog  # noqa: PLC0415
                techlog.self_heal(f"上机核对 #28 {rid} {t}", f"{line}；{by}", state_dir=state_dir)
            except Exception:  # noqa: BLE001 - the verdict stands; the group hears the failure to write
                _log_runs.warning("自愈待查的红项没写进技术日志：#28 %s %s", rid, t, exc_info=True)
        else:
            bad.append((t, line))
    tail = f"；{waits}" if waits else ""
    if bad:
        return _fail_28(ctx, [t for t, _ in bad], "；".join(x for _, x in bad)
                        + (f"。做成的：{'；'.join(good)}" if good else "") + tail)
    return mc.Result(PASS, "；".join(good) + tail, healed=healed)


# The alarm a #28 FAIL rides along with (pushes._push_unverified, its kind 「没证据」).
UNVERIFIED_ALARM = "没证据"
RODE_ALONG = "。已写在「没证据」那条报警里一起进群"
# #28 FAILs of runs held for their retry, until settle_28 settles them (machinecheck-runs.json):
# {run_id: {script, user, day, tasks, evidence, covered}}.
HELD_28 = "#28-held"
HELD_NOTE = "。这一趟中途停了，等这一班的重试跑完再定要不要报"


def _fail_28(ctx, tasks: list, evidence: str) -> mc.Result:
    """#28's FAIL about `tasks`: not pushed on its own when the 「没证据」 alarm sent while
    this record was booked names every one of them (ctx['unverified_alarm']) - that
    alarm carries the same verdicts - so the group gets one message for one cause.

    A run held for its retry (ctx['held']: booked ok=False, as AUTO-MAS books MaaEnd
    stopping itself, every later task failed) is not pushed yet either: its 「没证据」
    alarm, if any, comes with the retry's booking (handle._handle_success), and the
    retry may do the task. _hold_28 keeps it until settle_28 settles it."""
    sent = set(ctx.get("unverified_alarm") or [])
    if tasks and all(t in sent for t in tasks):
        return mc.Result(FAIL, evidence + RODE_ALONG, pushed_with=UNVERIFIED_ALARM)
    rec = ctx.get("rec")
    if tasks and getattr(rec, "run_id", None) in (ctx.get("held") or []):
        return _hold_28(ctx, tasks, evidence)
    return _r(FAIL, evidence)


def _hold_28(ctx, tasks: list, evidence: str) -> mc.Result:
    """Keep the FAIL about the held record (machinecheck-runs.json HELD_28) for
    settle_28; pushed at once when it cannot be kept, so it is never lost. Whether it
    is kept is what _state_update returned: a read that fails leaves the file as it
    was (rewriting it from nothing dropped every other held FAIL, never pushed), a
    read after a good write does not decide it (one failing pushed it here and again
    at settle_28). A push at once is marked sent (#28|<run id>, ctx['alerted'] as
    settle_28's `alerted`) once judge's push went out (Result.after_push): an entry of
    this run already on file is then dropped by settle_28 without a second push. Never
    before the push - one that failed, or a process gone in between, left that entry
    dropped unpushed (until 2026-10-17): it stays and settle_28 pushes it."""
    rec, state_dir = ctx.get("rec"), ctx.get("state_dir")
    entry = {"script": rec.script, "user": rec.user, "day": ctx.get("day") or "",
             "tasks": list(tasks), "evidence": evidence, "covered": []}

    def add(data):
        held = data.get(HELD_28)
        held = dict(held) if isinstance(held, dict) else {}
        held[rec.run_id] = entry
        data[HELD_28] = held

    if _state_update(state_dir, add, f"#28 等重试的 {rec.run_id}"):
        return mc.Result(FAIL, evidence + HELD_NOTE, deferred=True)
    _log_runs.info("上机核对 #28：%s 在等重试，但没记下来，现在就报", rec.run_id)
    mark, day, key = _alerted(ctx.get("alerted"))[1], ctx.get("day") or "", f"#28|{rec.run_id}"
    return mc.Result(FAIL, evidence, after_push=lambda: mark(day, key))


def covered_28(state_dir, script: str, day: str, items: list) -> None:
    """A 「没证据」 alarm naming `items` of `script` on `day` was just sent (or queued
    until it goes out): the held #28 FAILs of that day about those tasks are in it.
    One read and one write (_state_update), nothing written when no held FAIL is
    about them: a separate first read that failed skipped the cover without a word
    (until 2026-10-17), and settle_28 then pushed the same cause a second time. A read
    that fails is an ERROR only when the last good read held a FAIL or none was had:
    held nothing, there is nothing to cover, and the group hears no line about it."""
    def cover(data):
        held = data.get(HELD_28)
        changed = False
        for e in (held.values() if isinstance(held, dict) else ()):
            if not isinstance(e, dict) or e.get("script") != script or e.get("day") != day:
                continue
            add = [t for t in e.get("tasks") or [] if t in items and t not in (e.get("covered") or [])]
            if add:
                e["covered"] = list(e.get("covered") or []) + add
                changed = True
        return changed

    _state_update(state_dir, cover, f"#28 等重试的 {script} {day} 已由「没证据」报警带上的那几项",
                  quiet_unheld=True)


# Run ids whose #28 FAIL settle_28 pushed in this process: its guard against a repeat
# when no day marks are given (see settle_28 `alerted`).
_PUSHED_28: set = set()


def _alerted(alerted):
    """(already(day, key), mark(day, key)): the engine's day marks when given, else
    this process's _PUSHED_28."""
    return alerted or (lambda day, key: key in _PUSHED_28, lambda day, key: _PUSHED_28.add(key))


def settle_28(state_dir, hold_over, ledger, notifier, alerted=None) -> None:
    """Settle each held #28 FAIL whose hold is over (`hold_over(script, user)`: no record
    of that script and user held any more, the script not running): the tasks a
    「没证据」 alarm sent for them carries (covered_28) are in the group already; a task
    another run of the day did (`ledger(day)`, _done_elsewhere) was made up for, which
    the daily report says, as for a FAIL healed at once; any other task is pushed now
    as the check's own FAIL, with the evidence of the held run. A push that did not go
    out is kept and tried again at the next settle.

    A push that went out is pushed once: it is marked sent (`alerted`: (already(day,
    key), mark(day, key)), the engine's state.json day marks, as unresolved.send keys
    its pushes; without them, this process's _PUSHED_28) before anything else is
    written, and its entry is dropped from HELD_28 right then, entry by entry. A
    HELD_28 that cannot be written is an ERROR; the mark, in another file, keeps the
    next settle from pushing it again. Rewording the recorded verdict (mc.restate)
    comes last and its failure is only a warning."""
    held = _state_get(state_dir, HELD_28)
    if not isinstance(held, dict) or not held:
        return
    mc.load()
    what = mc.CHECKS["#28"].what
    already, mark = _alerted(alerted)
    for rid, e in held.items():
        if not hold_over(e.get("script"), e.get("user")):
            continue
        tasks = list(e.get("tasks") or [])
        covered = set(e.get("covered") or [])
        evidence = str(e.get("evidence") or "")
        was = evidence + HELD_NOTE
        day = e.get("day") or ""
        ctx = {"rec": type("Held", (), {"run_id": rid})(), "ledger": ledger(day)}
        healed = {t: by for t in tasks if t not in covered and (by := _done_elsewhere(ctx, t))}
        rest = [t for t in tasks if t not in covered and t not in healed]
        key = f"#28|{rid}"
        if rest and already(day, key):
            _log_runs.info("上机核对 #28：%s 这一条已经进过群（上回没从等重试的单子上划掉），不重推", rid)
        elif rest:
            errs = notifier.send(texts.machinecheck_failed("#28", what),
                                 texts.machinecheck_failed_body(what, evidence), alert=True)
            if errs:
                _log_runs.error("上机核对 #28 没过（%s 等重试的那一趟），推送也没推出去，下一轮再推：%s", rid, "；".join(errs))
                continue
            _log_runs.info("上机核对 #28 没过，%s 的重试完了，%s 没有别的报警带上，已报群：%s", rid, "、".join(rest), evidence[:120])
            try:
                mark(day, key)
            except Exception:  # noqa: BLE001 - HELD_28 below is the other record of it
                _log_runs.error("上机核对 #28：%s 已进群，但「已进群」没记下", rid, exc_info=True)
        _state_update(state_dir, lambda data, rid=rid: _drop_held(data, rid),
                      f"#28 已结掉的 {rid}（等重试的单子上还留着它）")
        try:
            if rest:
                mc.restate(state_dir, "#28", was, evidence)
            elif covered:
                _log_runs.info("上机核对 #28 没过，%s 已写在「没证据」那条报警里进群，不另发：%s", rid, evidence[:120])
                mc.restate(state_dir, "#28", was, evidence + RODE_ALONG)
            else:
                by = "；".join(f"{t}：{b}" for t, b in healed.items())
                _log_runs.info("上机核对 #28：%s 的%s没做成，%s，不进群，只进日报", rid, "、".join(healed), by)
                mc.restate(state_dir, "#28", was, f"{evidence}；{by}，不用人管", healed=True)
                try:
                    from ark_relay.core import statestore as techlog  # noqa: PLC0415
                    techlog.self_heal(f"上机核对 #28 {rid} {'、'.join(healed)}", f"{evidence}；{by}", state_dir=state_dir)
                except Exception:  # noqa: BLE001 - the verdict stands; the group hears the failure to write
                    _log_runs.warning("自愈待查的红项没写进技术日志：#28 %s", rid, exc_info=True)
        except OSError:
            _log_runs.warning("上机核对 #28：%s 的结论没改写进 machinecheck.json", rid, exc_info=True)


def _drop_held(data: dict, rid: str) -> None:
    held = data.get(HELD_28)
    if isinstance(held, dict):
        held.pop(rid, None)


def _done_elsewhere(ctx, task: str) -> str:
    """「同一天 HH:MM（东京 HH:MM）开始的那趟已经做成了」 - on both clocks, as the daily
    report names a run (core.retried_notes) - when another MaaEnd run of the day booked before
    this one did `task` or found nothing to do in it (its raw['tasks_trail'] verdict,
    ctx['ledger']), else ''. A row booked before raw['tasks_trail'] backs nothing here."""
    rec = ctx.get("rec")
    me = getattr(rec, "run_id", None)
    for row in ctx.get("ledger") or []:
        if row.get("script") != "MaaEnd" or row.get("run_id") == me:
            continue
        e = ((row.get("raw") or {}).get("tasks_trail") or {}).get(task)
        if isinstance(e, dict) and e.get("ok"):
            try:
                at = datetime.fromisoformat(row.get("started") or "").astimezone(SERVER_TZ)
            except ValueError:
                return "同一天另一趟已经做成了"
            return f"同一天 {at:%H:%M}（东京 {at.astimezone(USER_TZ):%H:%M}）开始的那趟已经做成了"
    return ""


_CLAIM = "确认领取奖励"
_HEAD = re.compile(r"^获得以下物品[:：]\s*$")
_ITEM = re.compile(r"^([^\[\s].*?)\s*[×x]\s*(\d+)\s*$")
_READING = re.compile(r"当前理智\s*(\d+)\s*/\s*(\d+)")
# MaaEnd v2.34 says 「体力不足，任务结束」 where it said 理智不足 (collector_maaend._END_SANITY_OUT;
# dispatch relay-opt-round3-1108 O-04).
_STOP = re.compile(r"理智不足|体力不足[，,]\s*任务结束")
_MSG = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[.\d]*\] (.*)$")
# What one Protocol Space claim cost, told by its own payout: the double reward pays
# 折金票 ×68000 and costs 160 (MaaEnd-05-29-05, 2026-10-07: 277 -> 117 across one such
# claim, no potion between); the single reward pays 折金票 ×34000 and costs 80 (same log:
# 117 -> single claim -> 37, which 10-08's first reading 237 = 37 + 200 overnight
# regeneration confirms). The MaaEnd logs kept in the day-replay corpus (pulls of
# 2026-10-06..10-13, history back to 09-24) hold no third amount within four lines of a
# 「确认领取奖励」: 108 such lines of 68000, 49 of 34000 (copies across pulls counted);
# on the 16 distinct list-era farming runs among them (09-29..10-13) this check and the
# collector agree. Another amount leaves the remaining sanity unjudged rather than guessed.
_PAY_ITEM = "折金票"
_CLAIM_COST = {68000: 160, 34000: 80}
_CLAIM_KIND = {68000: "双倍，扣 160", 34000: "单倍，扣 80"}


def _game_numbers(lines: list[str]) -> dict:
    """What the game showed in one farming task: claims that paid out (each
    「确认领取奖励」 followed by a 「获得以下物品：」 list before the next claim,
    reading or 「理智不足」), the items in those lists, and the 「当前理智」 readings."""
    msgs = [(m.group(1).strip() if (m := _MSG.match(x)) else x.strip()) for x in lines]
    landed, items, readings, last_landed = 0, {}, [], None
    claim_open, in_list = False, False
    for msg in msgs:
        if in_list and (m := _ITEM.match(msg)):
            items[m.group(1).strip()] = items.get(m.group(1).strip(), 0) + int(m.group(2))
            continue
        in_list = False
        if r := _READING.search(msg):
            readings.append((int(r.group(1)), int(r.group(2))))
            claim_open = False
        elif _CLAIM in msg:
            claim_open, last_landed = True, False
        elif _HEAD.match(msg):
            in_list = True
            if claim_open:
                landed, last_landed, claim_open = landed + 1, True, False
        elif _STOP.search(msg):
            claim_open = False
    return {"landed": landed, "items": items, "readings": readings, "last_landed": last_landed}


@mc.check("#20", "终末地产出和剩余理智按游戏自己的结算和读数记", "A", "run")
def _c20(ctx):
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    raw = ctx.get("raw") or {}
    lines = text.splitlines()
    segs = [s for s in cm._named_farm_segments(lines) if s[0] not in (raw.get("maaend_tasks_skipped") or {})]
    games = [(name, _game_numbers(lines[a:(b + 1) if b is not None else None])) for name, a, b in segs]
    games = [(n, g) for n, g in games if g["items"]]
    if not games:
        return None          # no farming task listed what it paid out (essence farming, or nothing claimed)
    runs = sum(g["landed"] for _, g in games)
    items: dict = {}
    for _, g in games:
        for k, n in g["items"].items():
            items[k] = items.get(k, 0) + n
    # Remaining sanity: the game's last reading in the whole log, plus the potions used
    # after it, less what the claim after it cost - read from that claim's own payout
    # (_claim_cost), not from the collector's rule, so the two are checked against each other.
    readings = [(int(m.group(1)), int(m.group(2))) for ln in lines if (m := _READING.search(ln))]
    want_sanity, landed_last, last_pay = None, False, None
    if readings:
        last_at = max(i for i, ln in enumerate(lines) if _READING.search(ln))
        end = next((b for _, a, b in cm._named_farm_segments(lines) if a <= last_at and (b is None or last_at <= b)),
                   None)
        tail = lines[last_at:(end + 1) if end is not None else None]
        after = _game_numbers(tail)
        landed_last = after["landed"] > 0
        have = readings[-1][0] + sum(1 for x in tail if cm._END_POTION.search(x)) * cm._END_POTION_SANITY
        if not landed_last:
            want_sanity = have
        else:
            last_pay = after["items"].get(_PAY_ITEM)
            if (cost := _CLAIM_COST.get(last_pay)) is not None:
                want_sanity = max(0, have - cost)
    got_drops = raw.get("maaend_farm_drops") or {}
    bad = []
    if raw.get("maaend_farm_runs") != runs:
        bad.append(f"趟数 {raw.get('maaend_farm_runs')}≠{runs}")
    if any(got_drops.get(k) != n for k, n in items.items()):
        bad.append("产出 " + " ".join(f"{k}×{got_drops.get(k, 0)}≠{n}" for k, n in items.items()
                                     if got_drops.get(k) != n))
    if want_sanity is not None and raw.get("sanity") != want_sanity:
        bad.append(f"剩余理智 {raw.get('sanity')}≠{want_sanity}")
    shown = " ".join(f"{k}×{n}" for k, n in items.items())
    paid = (f"，到账 {_PAY_ITEM}×{last_pay}（{_CLAIM_KIND[last_pay]}）" if last_pay in _CLAIM_KIND
            else f"，到账 {_PAY_ITEM}×{last_pay}（认不出单双倍）" if last_pay is not None else "")
    reading = (f"最后一次读数 当前理智 {readings[-1][0]}/{readings[-1][1]}（{'那次到账了' if landed_last else '那次没到账'}{paid}）"
               if readings else "没有理智读数")
    game = f"游戏结算 {runs} 次到账（{shown}），{reading}"
    if bad:
        return _r(FAIL, f"{game}；中继记的对不上：{'；'.join(bad)}")
    return _r(PASS, f"{game} → 中继记 {runs} 趟、{shown}"
                    + (f"、剩 {want_sanity}" if want_sanity is not None else "，剩余理智这趟算不出来不比"))


COMBAT_BLOCK = "战斗中无法使用"
_FW_STAMP = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
COLLECT = "自动采集"


def _collect_window(text: str) -> "tuple[datetime, datetime] | None":
    """The 自动采集 task's [start, end), to the millisecond (cm.line_time, as the routes')."""
    start = end = None
    for line in text.splitlines():
        if (t := cm.line_time(line)) is None:
            continue
        if re.search(r"任务开始[:：]\s*\S*" + COLLECT, line):
            start = t
        elif start and re.search(r"任务(完成|失败)[:：]\s*\S*" + COLLECT, line):
            end = t
    return (start, end) if start and end else None


# Triggered by MaaEnd's on_error picture of the relay-device node, not by the toast
# text: that text is in no log (0 hits in 202 maafw logs, ledger #29), so the old
# text grep never fired. The route still ends normally, so the relay has to book it
# as not gathered itself (outcome.maaend_checks, kind RETRY) for collect_retry to
# re-run it before power-off. This judges that booking, right after the record.
@mc.check("#29", "终末地采集撞上「战斗中无法使用」的那条路线采没采到", "A", "run")
def _c29(ctx):
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    span = _collect_window(text)
    if span is None:
        return None
    t0, t1 = span
    # The pictures the outcome check was handed (verdict keeps them with its checks),
    # or, for a run it did not check, the same round_shots over the same bounds: by
    # name time both, so #29 judges no picture the check never saw.
    checked = ctx.get("outcome")
    shots = (checked or {}).get("shots")
    if shots is None:
        rec = ctx["rec"]
        shots = cm.round_shots(ctx.get("maaend_dir"), rec.started, cm.round_until(rec))
    maaend_dir = ctx.get("maaend_dir")
    pics = [n for n in shots if cm.is_obstacle_shot(n)
            and (t := cm.shot_time(n)) is not None and cm.in_window(t, t0, t1)
            and cm.is_combat_block_shot(maaend_dir, n)]
    if not pics:
        return None
    blocked = cm.blocked_routes(text, pics, maaend_dir=maaend_dir)
    if lost := [n for n in pics if not any(n in v for v in blocked.values())]:
        return _r(FAIL, f"撞了「{COMBAT_BLOCK}」，存了出错截图 {lost[0]}，日志里认不出是哪条路线")
    # A failed run is not outcome-checked (handle: AUTO-MAS's own retry follows), so its
    # booking is the daily row's alone; the per-route retry reads the day's last run.
    raw = ctx.get("raw") or {}
    if checked is None and "maaend_collect_total" not in raw:
        return None
    booked = {c.label for c in (checked or {}).get("checks") or [] if getattr(c, "kind", "") == outcome.RETRY}
    for label, shots in blocked.items():
        if checked is not None and texts.collect_blocked_check(label) not in booked:
            return _r(FAIL, f"{label} 撞了「{COMBAT_BLOCK}」（{shots[0]}），这一趟的核对没把它记成没采到、没交给关机前补跑")
        if "maaend_collect_total" in raw and label not in (raw.get("maaend_collect_blocked") or []):
            return _r(FAIL, f"{label} 撞了「{COMBAT_BLOCK}」（{shots[0]}），日报那一行没写它没采到")
    names = "、".join(blocked)
    return _r(PASS, f"{names} 撞了「{COMBAT_BLOCK}」（{next(iter(blocked.values()))[0]}），记成没采到"
                    + ("，交给关机前单独补跑" if checked is not None else "（这一趟没跑完，补跑看当天最后一趟）"))


def _at(line: str) -> "datetime | None":
    m = _FW_STAMP.match(line or "")
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None


@mc.check("#30", "终末地基质刷取领奖后失败：背包满了就写背包满了，不是就带原始日志", "A", "run")
def _c30(ctx):
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    from ark_relay.core import ledger as core  # noqa: PLC0415
    text = ctx.get("log_text") or ""
    fails = cm.claim_failures(text)
    if not fails:
        return None
    raw = ctx.get("raw") or {}
    rec = ctx["rec"]
    causes = raw.get("maaend_fail_causes") or {}
    claim = raw.get("maaend_claim_lines") or {}
    notices = [x for x in (text + "\n" + cm.maafw_text(ctx.get("maaend_dir"))).splitlines()
               if cm._END_STORAGE_FULL in x]
    _, body = core.format_failure(rec, texts.known_cause(causes))
    out = []
    for name, click, failed in fails:
        c0, c1 = _at(click), _at(failed)
        seen = [x for x in notices if c0 and c1 and (t := _at(x)) and c0 <= t <= c1 + timedelta(seconds=cm._STORAGE_FULL_AFTER_S)]
        full = causes.get(name) == cm.BAG_FULL
        if seen and not full:
            return _r(FAIL, f"{name} 点确认领取后失败，看到了「{cm._END_STORAGE_FULL}」却没写背包满了："
                            f"{_around(seen[0], cm._END_STORAGE_FULL)}")
        if full and not seen:
            return _r(FAIL, f"{name} 写成了背包满了，日志里却找不到「{cm._END_STORAGE_FULL}」：{_cut(failed)}")
        if full:
            if f"{name}（{cm.BAG_FULL}）" not in body:
                return _r(FAIL, f"{name} 认出背包满了，报警正文里却没有「{name}（{cm.BAG_FULL}）」")
            out.append(f"{name}（{cm.BAG_FULL}）：{_around(seen[0], cm._END_STORAGE_FULL)}")
            continue
        part = claim.get(name) if isinstance(claim.get(name), dict) else {}
        run = part.get("run") or []
        if not run or texts.CLAIM_LINES_RUN not in body:
            return _r(FAIL, f"{name} 点确认领取后失败，没看到仓储已满，报警却没带原始日志：{_cut(failed)}")
        out.append(f"{name} 没看到仓储已满，报警带了原始日志 {len(run)} 行（{_cut(run[0])[:60]}…）")
    return _r(PASS, "；".join(out))


# ------------------------------------------------------- alarms that must go out

def _undone_alarm(ctx, script: str):
    """#43 / #46: a round that exited normally with work left undone gets no make-up
    and no other way to recover (handle._handle_success pushes it at once), so its
    alarm must be among the copies of what went to the group (alertlog.py)."""
    if not _script(ctx, script) or ctx.get("test_run"):
        return None
    rec = ctx["rec"]
    msg = str((ctx.get("outcome") or {}).get("msg") or "")
    if not rec.ok or not msg or (ctx.get("raw") or {}).get("manual_stop"):
        return None
    bullet = next((ln for ln in msg.splitlines() if ln.startswith("· ")), msg.splitlines()[0])
    rows = [a for a in ctx.get("alerts") or [] if bullet in str(a.get("text") or "")]
    if not rows:
        rows = [a for a in _day_alerts(ctx.get("state_dir"), rec.finished)
                if msg in str(a.get("text") or "")]
    if rows:
        return _r(PASS, f"已进群：{rows[0].get('ts')} 「{rows[0].get('title')}」（报警抄送里有，{bullet[2:60]}）")
    why = "推送没成，排在下一轮重推" if rec.run_id in (ctx.get("unsent") or []) else "这一趟处理完，报警抄送里没有它"
    return _r(FAIL, f"「{bullet[2:80]}」没进群：{why}")


def _day_alerts(state_dir, since: datetime) -> list[dict]:
    """Alarm copies of the Beijing days from `since` to now that are no older than it."""
    if not state_dir:
        return []
    from ark_relay.features import errwatch as alertlog  # noqa: PLC0415
    start = alertlog.beijing(since)
    days = sorted({start.strftime("%Y%m%d"), alertlog.beijing().strftime("%Y%m%d")})
    cut = start.strftime("%Y-%m-%d %H:%M:%S")
    return [row for day in days for row in mc.alert_rows(state_dir, day) if str(row.get("ts") or "") >= cut]


@mc.check("#43", "终末地「有项目没干成」的每一趟都进了群", "A", "run")
def _c43(ctx):
    return _undone_alarm(ctx, "MaaEnd")


@mc.check("#46", "鸣潮「有项目没干成」的每一趟都进了群", "A", "run")
def _c46(ctx):
    return _undone_alarm(ctx, "OK-WW")


# ------------------------------------------------------- #24: the three false-alarm fixes of 10-05

_PRE_RETRY = re.compile(r"预更新：(\S+) 没给出结论（.*），再试一次")
_PRE_NO_ROOM = re.compile(r"预更新：(\S+) 没给出结论，离下一个队列只有 \d+ 秒，不再试")
_PRE_LEFT = re.compile(r"预更新有 (\d+) 项没能确认")
# boot_stages._once_more: the second try gave a verdict. A retry line followed by neither
# this nor _PRE_LEFT is a pre-update that did not finish (a stop during the retry, which
# says nothing by design), so it is not judged rather than passed.
_PRE_FIXED = re.compile(r"预更新：(\S+) 第一次没给出结论，再试一次给出了结论")
RELAY_TAIL = 4 * 1024 * 1024


def _relay_today(now: datetime) -> list[str]:
    """relay.log (ARK_LOG_FILE) lines stamped today on the machine's clock; [] when there is none."""
    path = os.environ.get("ARK_LOG_FILE", "")
    if not path:
        return []
    from ark_relay.core.statestore import tail_bytes  # noqa: PLC0415
    try:
        # Reaches into relay.log.1 after a rotation (logfile.py).
        raw = tail_bytes(path, RELAY_TAIL)[0].decode("utf-8", errors="replace")
    except OSError:
        return []
    day = now.strftime("%m-%d")
    return [ln for ln in raw.splitlines() if ln.startswith(day + " ")]


@mc.check("#24b", "三处误报修复之二：预更新某项没给出结论就再试一次，还没结论就进群", "B", "run")
def _c24b(ctx):
    now = datetime.now(tz=SERVER_TZ)
    lines = _relay_today(now)
    first = [ln for ln in lines if _PRE_RETRY.search(ln) or _PRE_NO_ROOM.search(ln)]
    left = [ln for ln in lines if _PRE_LEFT.search(ln)]
    if not first and not left:
        return None
    stamp = (first or left)[0][:14]
    seen = (mc.read(ctx.get("state_dir")).get("#24b") or {}).get("evidence", "")
    if seen.startswith(stamp):
        return None          # this pre-update was judged already
    msg = lambda ln: _cut(ln.split("  ", 1)[-1])  # noqa: E731 - the message part of a relay.log line
    if left and not first:
        return _r(FAIL, f"{stamp} {msg(left[0])}，之前没有「再试一次」也没有「不再试」那一行")
    head = f"{stamp} {msg(first[0])}"
    if not left:
        if any(_PRE_NO_ROOM.search(ln) for ln in first):
            return _r(FAIL, f"{head}；说了不再试，后面却没有「预更新有 N 项没能确认」")
        if not any(_PRE_FIXED.search(ln) for ln in lines):
            return None      # the retry never finished: nothing was judged yet
        return _r(PASS, f"{head}；第二次给出了结论")
    n = int(_PRE_LEFT.search(left[-1]).group(1))
    title = texts.unconfirmed("预更新", n)
    rows = [a for a in _day_alerts(ctx.get("state_dir"), now.replace(hour=0, minute=0, second=0))
            if a.get("title") == title]
    if not rows:
        return _r(FAIL, f"{head}；还有 {n} 项没确认，报警抄送里没有「{title}」")
    return _r(PASS, f"{head}；还有 {n} 项没确认，{rows[0].get('ts')} 已进群")


mc.cannot("#24c", "三处误报修复之三：卡池下期扣下只记提醒、不进群",
          "这条修复要的「不进群」，10-06 已按「不论多少次什么错误都要发」改回进群，没有要核的了")
mc.cannot("#24d", "部署前闸门那次红的原因",
          "闸门在 Mac 上部署时跑，不在游戏机上，机器看不到")
