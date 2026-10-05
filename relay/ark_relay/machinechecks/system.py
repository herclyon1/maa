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
next one. Only sessions that logged CODE_MARK (boot_stages._stage_bootstrap) ran the
code these checks know; older sessions are never judged. The session a boot judges
is the last one before the current that did not end in a self-update restart - and
the same session is not judged twice (its evidence is the same as the stored one).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .. import machinecheck as mc
from ..config import SERVER_TZ

# ------------------------------------------------------------------ relay.log

# The words other modules log, matched here. Each is quoted from its source.
CODE_MARK = "中继代码版本"                          # boot_stages._stage_bootstrap
SESSION_START = "服务模式启动"                       # boot_stages._stage_bootstrap
SELF_UPDATE = "代码已更新，重启以立即生效"             # boot_stages._stage_selfupdate
STOP_NOTICE = "收到停止通知"                         # service.ArkRelayService.SvcStop
POWER_OFF = "本轮已处理完毕，60 秒后关机"               # engine.Engine._power_off
PUSHED = "已上报状态到手机（"                         # boot_stages publish_state, ok
NOT_PUSHED = "状态没能上报到手机（"                    # boot_stages publish_state, failed
STOP_PUSH_FAILED = ("停止前上报状态失败", "停止前那份状态")  # service.SvcStop / _wait_stop_push
EXIT_AT_POWER_OFF = "中继自己发出了关机命令，AUTO-MAS 后台此时退出"   # service._AutomasKeeper._exited
EXIT_UNEXPLAINED = re.compile(r"^AUTO-MAS 后台(意外)?退出了")       # the same, any other exit
REVIVE_WORDS = ("中继正在重新打开它", "中继正在关掉它重新打开", "AUTO-MAS 接口不在，拉起它")
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
    """The last `nbytes` of relay.log as text, starting at a whole line; '' when unreadable."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - nbytes))
            data = fh.read()
    except (OSError, TypeError):
        return ""
    text = data.decode("utf-8", "replace")
    return text.split("\n", 1)[-1] if size > nbytes else text


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
    self-update restart; None when there is none or it ran code from before CODE_MARK."""
    found = sessions(recs)
    for s in reversed(found[:-1]):
        if not any(r.msg.startswith(CODE_MARK) for r in s):
            return None
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


def _now(ctx) -> datetime:
    return (ctx.get("now") or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)


def _day_of(md: str, now: datetime) -> str:
    """YYYY-MM-DD of a relay.log MM-DD stamp (the log has no year; a date after today is last year's)."""
    year = now.year - (1 if md > now.strftime("%m-%d") else 0)
    return f"{year}-{md}"


def _once(ctx, cid: str, result: mc.Result) -> "mc.Result | None":
    """None when this very evidence was judged before: the same session read again at a later boot."""
    row = mc.read(ctx.get("state_dir")).get(cid) or {}
    return None if row.get("evidence") == result.evidence[:300] else result


def _alert_rows(state_dir, day8: str) -> list[dict]:
    """The alarm copy of a Beijing day (alertlog.py), oldest first; [] when there is none."""
    try:
        text = (Path(state_dir) / "alerts" / f"{day8}.jsonl").read_text(encoding="utf-8")
    except (OSError, TypeError):
        return []
    rows = []
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return [r for r in rows if isinstance(r, dict)]


# ------------------------------------------------------------------ #11

@mc.check("#11", "停服务时最后推一份状态给手机（Windows 关机也通知得到中继）", "A", "boot")
def _stop_push(ctx):
    s = _prev(ctx)
    if s is None:
        return None
    stop = next((r for r in s if r.msg.startswith(STOP_NOTICE)), None)
    if stop is None:
        return _once(ctx, "#11", mc.Result(mc.FAIL, f"上一次中继没收到停止通知就没了，最后一行：{s[-1].show()}"))
    if not any(PUSHED in r.msg or NOT_PUSHED in r.msg for r in s):
        return None          # the phone channel never worked in that session: nothing to push with
    after = s[s.index(stop):]
    ok = next((r for r in after if f"{PUSHED}停止前" in r.msg), None)
    bad = next((r for r in after if f"{NOT_PUSHED}停止前" in r.msg or r.msg.startswith(STOP_PUSH_FAILED)), None)
    if ok is not None:
        return _once(ctx, "#11", mc.Result(mc.PASS, f"{stop.show()}；{ok.show()}"))
    if bad is not None:
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


# ------------------------------------------------------------------ #17

@mc.check("#17", "预更新改终末地设置前，先关掉已经开着的终末地程序", "B", "preupdate")
def _maaend_closed_first(ctx):
    if ctx.get("script") != "MaaEnd":
        return None
    for step in ctx.get("steps") or []:
        before, left = step.get("open_before"), step.get("left")
        if before is None:
            return mc.Result(mc.FAIL, "预更新写终末地设置前读不到在跑的程序列表，不知道终末地程序开没开着")
        if not before:
            continue
        pids = "、".join(map(str, before))
        if left:
            return mc.Result(mc.FAIL, f"预更新前终末地程序开着（PID {pids}），关了还在（PID {'、'.join(map(str, left))}），"
                                      "没改设置、没检查更新")
        if left is None:
            return mc.Result(mc.FAIL, f"预更新前终末地程序开着（PID {pids}），关完读不到在跑的程序列表，没确认它关掉了")
        return mc.Result(mc.PASS, f"预更新前终末地程序开着（PID {pids}），先关掉了（在跑的程序里已没有它）才改设置")
    return None


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
        from ..config import atomic_write_text  # noqa: PLC0415
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
    from .. import alertlog  # noqa: PLC0415
    day8 = alertlog.beijing(_now(ctx)).strftime("%Y%m%d")
    row = next((r for r in reversed(_alert_rows(ctx.get("state_dir"), day8))
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
    if ctx.get("action") != "kill" or not res:
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
    from .. import makeup  # noqa: PLC0415
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
                              f"中继还不会在记录上写「进不了游戏」（maa_unreachable）；这一趟 MAA 自己的日志 gui.log {cap.get('gui', 0)} 行、"
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
    if bad := next((r for r in after if any(w in r.msg for w in REVIVE_WORDS)), None):
        return _once(ctx, "#38", mc.Result(mc.FAIL, f"{off.show()}；之后 {bad.show()}"))
    return _once(ctx, "#38", mc.Result(
        mc.PASS, f"{off.show()}；到中继停下（{after[-1].md} {after[-1].hms}）没有去重新打开调度程序"))


_HYPOTHESIS = re.compile(r"hypothesis: (H[123])\b")
HYPOTHESIS_ZH = {"H1": "WMI 服务自己重启过", "H2": "WMI 的提供程序宿主（WmiPrvSE）没了一个",
                 "H3": "WMI 服务和提供程序宿主都没变（另有原因）"}


@mc.check("#59", "系统的程序启动通知断了又自己订上的，只进日报不进群，并写明是哪种原因", "B", "boot")
def _wmi_recovered(ctx):
    s = _prev(ctx)
    if s is None:
        return None
    back = [r for r in s if r.level == "WARNING" and WMI_BACK.match(r.msg)]
    if not back:
        return None
    now = _now(ctx)
    good = ""
    for r in back:
        day = _day_of(r.md, now)
        rows = _errkinds(ctx.get("state_dir"), day)
        if not any(x.get("line") == r.msg.strip()[:200] and x.get("recovered") for x in rows):
            return _once(ctx, "#59", mc.Result(mc.FAIL, f"{r.show()}：日报的报错记录里没记成「自己好了」"))
        needle = r.msg.strip()[:60]      # errwatch's push quotes the line cut at 160
        if any(needle in str(x.get("text") or "") for x in _alert_rows(ctx.get("state_dir"), day.replace("-", ""))):
            return _once(ctx, "#59", mc.Result(mc.FAIL, f"{r.show()}：自己好了的，却进了群"))
        diag = next((m for x in r.more if (m := _HYPOTHESIS.search(x))), None)
        if diag is None:
            raw = next((x.strip() for x in r.more if x.strip().startswith("diag:")), "（没有 diag 行）")
            raw = raw[raw.find("WMI hosts"):] if "WMI hosts" in raw else raw    # the part that tells them apart
            return _once(ctx, "#59", mc.Result(mc.FAIL, f"{r.show()}：说不出是哪种原因：{raw[:160]}"))
        good = f"{r.show()}；只进了日报；原因：{HYPOTHESIS_ZH[diag.group(1)]}"
    return _once(ctx, "#59", mc.Result(mc.PASS, good))


def _errkinds(state_dir, day: str) -> list[dict]:
    try:
        data = json.loads((Path(state_dir) / "errkinds" / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return [r for r in data.values() if isinstance(r, dict)] if isinstance(data, dict) else []


# ------------------------------------------------------------------ #63

@mc.check("#63", "开机后 state.json 里不再留着中继关掉终末地任务的旧记录（应急理智加强剂那条）", "A", "boot")
def _off_records_gone(ctx):
    from ..gameupdate import _OFF_RECORDS  # noqa: PLC0415
    from ..statestore import StateStore  # noqa: PLC0415
    if not ctx.get("state_dir"):
        return None
    store = StateStore(ctx["state_dir"])
    left = [(k, v) for k in _OFF_RECORDS if (v := store.get("updates", k)) is not None]
    if left:
        k, v = left[0]
        return mc.Result(mc.FAIL, f"开机后 state.json 里还留着 {k}：{json.dumps(v, ensure_ascii=False)[:160]}")
    return mc.Result(mc.PASS, "开机后 state.json 里已经没有 maaend_disabled_spmed（另两条旧记录也没有）")


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


_BUSY_WORDS = {"终末地": ("正在下载", "安装中"), "鸣潮": ("下载中", "解压中", "进入中", "检查游戏版本和文件")}


@mc.check("#61", "启动器下载时屏上的字认得出（正在下载 / 下载中 / 解压中这些）", "B", "gameupdate")
def _launcher_busy_words(ctx):
    seen = [x for x in _notes(ctx, "launcher") if not x.get("unread")]
    for x in seen:
        if x.get("stage") == "wait" and not x.get("busy") and not x.get("ready"):
            return mc.Result(mc.FAIL, f"{x.get('game')}启动器在下载时屏上的字一个也没认出（截图 {x.get('shot')}）："
                                      f"{str(x.get('dump') or '')[:160]}")
    hit = next((x for x in seen if x.get("busy")), None)
    if hit is None:
        return None              # the download screen never came up (or nothing was read)
    return mc.Result(mc.PASS, f"{hit.get('game')}启动器下载时读到「{hit.get('busy')}」"
                              f"（那一行：{hit.get('line', '')}，截图 {hit.get('shot')}）")


@mc.check("#62", "明日方舟预热点满 5 下之后，画面到了登录界面", "B", "gameupdate")
def _ak_prewarm_taps(ctx):
    for x in _notes(ctx, "ak_prewarm"):
        if not x.get("full"):
            continue
        after = f"点满 {x.get('taps')} 下后那一屏（截图 {x.get('shot_after')}）：{x.get('dump_after', '')[:120]}"
        if x.get("reached"):
            return mc.Result(mc.PASS, f"{after}；后来读到「开始唤醒」")
        return mc.Result(mc.FAIL, f"{after}；到最后也没读到「开始唤醒」，最后一屏（截图 {x.get('shot_last')}）："
                                  f"{x.get('dump_last', '')[:120]}")
    return None


@mc.check("#64", "终末地公告读不到时报到群里", "B", "gameupdate")
def _ef_notice_pushed(ctx):
    probs = [p for p in ctx.get("problems") or [] if str(p).startswith("终末地：官方公告读不到")]
    if not probs or "title" not in ctx:
        return None
    return _reached_group(dict(ctx, run_id=probs[0]))
