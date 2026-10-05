"""Machine checks of the phone channel, the phone orders and the banner section.

The user, 2026-10-06 04:59: the machine has to confirm by itself, after a deploy,
what nobody had confirmed on it. These are the ledger items of this area:
#2 #3 #8 #9 (the daily report's banner section), #10 #15 #16 #23 (the phone
page and the phone orders), and the 10-06 log-sweep signatures fixed in
ark.phone / ark.service publish_state / ark.maintenance / ark.banners. One check
covers each group of signatures; it carries the group's first number and its
text names the rest:

    #39 states reach the phone      also #42 #44 #47 #48 #51
    #40 ntfy's 250 a day not spent  also #52 #54
    #41 the boot mailbox read
    #45 stream drops                also #49 #57
    #50 maintenance bulletins       also #53
    #56 the heartbeat on COS
    #58 the 库街区 door of the version-news post

Where they are judged (machinecheck.EVENTS):

* "banners"      banners.save_trace, right after the banner section was built;
* "phone_state"  boot_stages publish_state, after every state push. #10 on the
                 boot push, #15 on any, the signature groups on the push before
                 the relay's power-off (「关机前」, the end of a shift);
* "phone_cmd"    boot_stages: an order applied (live / drained after the run),
                 queued behind a run, or expired in the queue;
* "estop"        the red button branch of run_phone_cmd.

The evidence is what the relay already keeps: the banner trace, the state it
just pushed with its receipts, the phone queue file, the day's error kinds
(state/errkinds/<day>.json), errwatch's queue (state/errwatch-queue.json), the
copy of every group alarm (state/alerts/<YYYYMMDD>.jsonl), the ntfy day ledger,
and the tallies the phone code keeps for these checks (phone.Mailbox.report,
phone.Heartbeat.cos_report, maintenance.stats, commands.ESTOP_LAST,
resources.probe).

A signature's log lines are judged by the user's two rules: what the relay got
over by itself goes to the daily report only (2026-10-06 05:07: 「报错后自己好了的，
只进日报、不进群」), and what did not recover goes to the group, every time
(「不论多少次什么错误都要发」). So, per line of the shift:

* an old wording the fixed code no longer logs as a WARNING -> FAIL: the fix is
  not what is running;
* a recovered wording -> marked recovered, never pushed, not queued;
* an alarm wording -> pushed for every occurrence and in the group-alarm copy;
  one still in errwatch's queue FRESH_S after it was logged is a FAIL.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from .. import errwatch, machinecheck as mc, texts
from ..config import SERVER_TZ

log = logging.getLogger("ark.phone_banners")

SHIFT_END = "关机前"           # the push before the relay's own power-off (shutdown.py)
BOOT = "开机"                  # the first push of a process (boot_stages._start_phone_channel)
STOPPING = "停止前"            # the push from SvcStop
FRESH_S = 120                  # an alarm line this young may still be on its way to the group
_STAMP = "%Y-%m-%d %H:%M:%S"


# ------------------------------------------------------------------ calling judge

class ViaErrwatch:
    """A notifier for call sites that have none (banners.save_trace) or must not
    wait on the network (a service stop): a check that did not hold is logged as
    an ERROR carrying its own title and body, and errwatch pushes exactly that to
    the group - queued on disk, sent from its own thread, never dropped."""

    def send(self, title: str, body: str = "", alert: bool = False, **_kw) -> list:
        log.error("%s", title, extra=errwatch.alarm(title, body))
        return []


def fire(state_dir, event: str, ctx: dict, notifier=None) -> list:
    """machinecheck.judge for the phone and banner call sites: the running version
    from the state store, ViaErrwatch when no notifier is given. Never raises."""
    if not state_dir:
        return []
    try:
        from ..statestore import StateStore  # noqa: PLC0415
        version = str(StateStore(Path(state_dir)).get("versions", "code") or "")
    except Exception:  # noqa: BLE001 - an unreadable version only leaves the column empty
        version = ""
    try:
        return mc.judge(state_dir, event, ctx, version=version,
                        notifier=notifier if notifier is not None else ViaErrwatch())
    except Exception:
        log.exception("上机核对（%s）自己出错了", event)
        return []


# ------------------------------------------------------------------ helpers

def _now(ctx) -> datetime:
    now = ctx.get("now_bj")
    return now if isinstance(now, datetime) else datetime.now(tz=SERVER_TZ)


def _same_as_last(ctx, cid: str, evidence: str) -> bool:
    """The verdict on record already rests on this very evidence (the same receipt,
    the same session): judging it again would count one occurrence twice."""
    row = mc.read(ctx.get("state_dir")).get(cid) or {}
    return str(row.get("evidence") or "") == evidence[:300]


def _clock(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=SERVER_TZ).strftime("%H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def _rx(*patterns: str) -> tuple:
    return tuple(re.compile(p) for p in patterns)


def _hit(patterns, line: str) -> bool:
    return any(p.search(line) for p in patterns or ())


def _day_rows(state_dir, day: str) -> list[tuple[str, dict]]:
    """(signature, row) of one day's error kinds (errwatch's state/errkinds/<day>.json)."""
    try:
        data = json.loads((Path(state_dir) / errwatch.DAY_DIR / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [(str(k), v) for k, v in data.items() if isinstance(v, dict)] if isinstance(data, dict) else []


def _rows_since(state_dir, since: datetime, now: datetime) -> list[tuple[str, dict]]:
    """The error kinds logged at or after `since` (at most the last three days)."""
    since = since.astimezone(SERVER_TZ)
    cut = since.strftime(_STAMP)
    day = max(since, now - timedelta(days=2)).date()
    out: list[tuple[str, dict]] = []
    while day <= now.date():
        out += [(k, r) for k, r in _day_rows(state_dir, day.isoformat()) if str(r.get("last", "")) >= cut]
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
        try:
            lines = (Path(state_dir) / "alerts" / f"{day:%Y%m%d}.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for ln in lines:
            try:
                obj = json.loads(ln)
            except ValueError:
                continue
            if (isinstance(obj, dict) and str(obj.get("title", "")).startswith(texts.RELAY_ERROR)
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


def _lines(ctx, since: datetime, where: tuple, *, old=(), recovered=(), alarm=()) -> tuple[list, list]:
    """(problems, notes) for one signature group's WARNING / ERROR lines since `since`."""
    state_dir, now = ctx.get("state_dir"), _now(ctx)
    queued = _queued_sigs(state_dir)
    bad: list[str] = []
    notes: list[str] = []
    for sig, r in _rows_since(state_dir, since, now):
        line = str(r.get("line") or "")
        if str(r.get("where") or "") not in where:
            continue
        n, pushed = int(r.get("count") or 1), int(r.get("pushed") or 0)
        at = str(r.get("last") or "")[11:19]
        if _hit(old, line):
            bad.append(f"改掉的旧报错又出现了 {n} 次（最后 {at}）：{line[:120]}")
        elif _hit(recovered, line):
            if r.get("recovered") and pushed == 0 and sig not in queued:
                notes.append(f"自己好了的 {n} 次只进了日报（{line[:24]}…）")
            else:
                bad.append(f"自己好了的却{'进了群' if pushed else '排着队要进群'}（{at}）：{line[:120]}")
        elif _hit(alarm, line):
            if pushed >= n and _in_alert_copy(state_dir, r):
                notes.append(f"没好的 {n} 次都进了群（{line[:24]}…）")
            elif _age(r, now) < FRESH_S:
                notes.append(f"没好的那条 {at} 刚记下，正在进群（{line[:24]}…）")
            elif pushed >= n:
                bad.append(f"没好的 {n} 次推出去了，报警抄件里却没有（{at}）：{line[:120]}")
            else:
                bad.append(f"没好的 {n} 次里 {n - pushed} 次还没进群（最后 {at}）：{line[:120]}")
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
    if "日期没读出" in value:
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
    head = f"库街区：{doors.get('库街区', '没去取')}；哔哩哔哩：{bili}"
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
    from ..banners import group_notice, opening_tomorrow  # noqa: PLC0415
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
    bad, _notes = _lines(ctx, since, ("ark.banners",), old=_rx(r"^库街区官方资讯里没找到"))
    kuro = _doors(tr).get("库街区")
    if bad:
        return mc.Result(mc.FAIL, "；".join(bad))
    if kuro is None or kuro.startswith("取不到"):
        return None          # the door was not asked, or the list itself failed (not this item)
    if kuro == "没有这一帖":
        return mc.Result(mc.PASS, f"库街区这次没有这一帖，只记了日志、没进群；哔哩哔哩：{_doors(tr).get('B 站', '没去取')}")
    return mc.Result(mc.PASS, f"库街区官方资讯里找到了这一帖：{kuro}")


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
    from .. import resources  # noqa: PLC0415
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
    if _same_as_last(ctx, "#15", evidence):
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
    from .. import phone  # noqa: PLC0415
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
    bad, notes = _lines(ctx, since, ("ark.phone", "ark.service"),
                        old=_rx(r"^状态没能发到信箱", r"^第 \d+/\d+ 片没发出去",
                                r"^状态没能上报到手机（[^）]*；今天 ntfy 已发"),
                        recovered=_rx(r"^状态没存上腾讯云，这一份改走手机信箱发到了",
                                      r"^状态(的通知)?没发到手机信箱，状态已存到腾讯云",
                                      r"^发到手机信箱第一次没成"),
                        alarm=_rx(r"^状态没能上报到手机（[^；）]*）"))
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
    from .. import phone  # noqa: PLC0415
    raw = q.get("raw") or {}
    kinds = "、".join(f"{k} {v}" for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool))
    synced = raw.get("ntfy") if isinstance(raw.get("ntfy"), dict) else {}
    head = (f"手机信箱的这一天（世界时 {q.get('day')}）已用 {q.get('total')} 条，中继自己发了 {q.get('own')} 条"
            + (f"（{kinds}）" if kinds else "")
            + (f"，手机信箱自己的计数 {synced.get('n')} 条（{_clock(synced.get('at'))} 读）" if synced else ""))
    bad, notes = _lines(ctx, _since(ctx), _PHONE, old=_rx(r"^ntfy 今天的 \d+ 条额度用完了"),
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
    bad, notes = _lines(ctx, _since(ctx), _PHONE, old=_rx(r"^取不到信箱里的指令"),
                        recovered=_rx(r"^开机时没读到手机信箱，手机通道连上后补读到了"))
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
    from .. import phone  # noqa: PLC0415
    m = ctx.get("mailbox") or {}
    since = _since(ctx)
    drops = [d for d in m.get("drops") or [] if float(d.get("at") or 0) >= since.timestamp()]
    bad, notes = _lines(ctx, since, _PHONE, old=_rx(r"^手机通道断了"),
                        recovered=_rx(r"^手机通道断过 "), alarm=_rx(r"^手机通道连不上 ntfy 已经"))
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


@mc.check("#50", "三家停服维护公告读得到，第一次没响应的重试取到只进日报（一并核 #53）", "A", "phone_state")
def _maintenance(ctx):
    if not _shift_end(ctx):
        return None
    st = ctx.get("maintenance") or {}
    if not st:
        return None          # tomorrow's plan never asked for them this time
    bad, notes = _lines(ctx, _since(ctx), ("ark.maintenance",), old=_rx(r"^维护公告：\S+ 取不到$"),
                        recovered=_rx(r"^停服维护公告的官网第一次没响应"),
                        alarm=_rx(r"^维护公告：\S+ 官方公告取不到"))
    for game, row in st.items():
        if not row.get("last_ok"):
            bad.append(f"{game}最近一次（{_clock(row.get('last'))}）没取到：{row.get('why')}")
    base = _base(ctx, "maintenance")
    reads = "、".join(f"{g} {int(r.get('fetch') or 0) - int((base.get(g) or {}).get('fetch') or 0)} 次"
                     for g, r in st.items())
    n = (ctx.get("tally") or {}).get("n", 0)
    return _verdict(f"这一班状态上报 {n} 次，维护公告真去官网取了 {reads}（其余用一小时内取到的）", bad, notes)


@mc.check("#56", "心跳写得进腾讯云，写不进又好了的只进日报", "A", "phone_state")
def _cos_beat(ctx):
    if not _shift_end(ctx):
        return None
    from .. import phone  # noqa: PLC0415
    h = dict(ctx.get("heartbeat") or {})
    base = _base(ctx, "heartbeat")
    for k in ("ok", "failed"):
        h[k] = int(h.get(k) or 0) - int(base.get(k) or 0)
    if not h.get("cos") or not (h.get("ok") or h.get("failed") or h.get("down_since")):
        return None          # no COS on this machine, or no beat this shift
    bad, notes = _lines(ctx, _since(ctx), _PHONE, old=_rx(r"^心跳没能写到腾讯云 COS"),
                        recovered=_rx(r"^心跳又写得进腾讯云了"), alarm=_rx(r"^心跳从 .* 起一直写不进腾讯云"))
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
