"""Judgment, bookkeeping, and message formatting.

Everything factual is decided here, in plain Python. The model is only ever
asked to phrase things (see summary.py). If it misbehaves the result is an
awkward sentence, never a wrong verdict.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config, RunRecord, SERVER_TZ, USER_TZ, atomic_write_text, both_clocks

log = logging.getLogger("ark.core")


class State:
    """Which runs have been handled, and today's ledger.

    Kept as line-delimited JSON so a half-written file costs at most one
    record, and so it stays readable when something goes wrong at 3am.
    """

    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.dir / "seen.txt"
        self._seen: set[str] | None = None

    @property
    def seen(self) -> set[str]:
        if self._seen is None:
            if self.seen_path.exists():
                self._seen = {
                    ln.strip()
                    for ln in self.seen_path.read_text(encoding="utf-8").splitlines()
                    if ln.strip()
                }
            else:
                self._seen = set()
        return self._seen

    def mark_seen(self, run_id: str) -> None:
        self.seen.add(run_id)
        with self.seen_path.open("a", encoding="utf-8") as f:
            f.write(run_id + "\n")

    def ledger_path(self, day: str) -> Path:
        return self.dir / f"ledger-{day}.jsonl"

    def append_ledger(self, rec: RunRecord) -> None:
        entry = {
            "run_id": rec.run_id,
            "script": rec.script,
            "user": rec.user,
            "started": rec.started.isoformat(),
            "finished": rec.finished.isoformat(),
            "ok": rec.ok,
            "failed_tasks": rec.failed_tasks,
            "duration_known": rec.duration_known,
            # 让写日报的模型知道这条不是失败，是被下一轮取代
            "transitional": rec.transitional,
            # The model reads this verbatim. Keeping AUTO-MAS's own output
            # means the report can never disagree with what actually happened.
            "raw": rec.raw,
            "sanity": rec.sanity,
            "sanity_full_at": rec.sanity_full_at,
            "drops": rec.drops,
            "recruits": rec.recruits,
        }
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        with self.ledger_path(day).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # What every consumer of a ledger entry assumes is present. Checked once,
    # here, rather than defended against at each of the dozen places that read
    # these fields - and one of those places is the deterministic report
    # layout, the last fallback when the wording model is unavailable. A
    # KeyError there means the daily report is never sent, and since the
    # shutdown path waits for a sent report, the machine stays powered on all
    # night. A missing dictionary key should not be able to do that.
    _LEDGER_REQUIRED = ("run_id", "script", "started", "finished", "ok")

    def read_ledger(self, day: str) -> list[dict]:
        p = self.ledger_path(day)
        if not p.exists():
            return []
        out = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                entry = json.loads(ln)
            except json.JSONDecodeError:
                continue  # tolerate one torn line rather than lose the day
            if not isinstance(entry, dict):
                continue
            if missing := [k for k in self._LEDGER_REQUIRED if k not in entry]:
                # Reachable: the ledger is line-delimited JSON on a machine
                # that is hard power-cut twice a day, so a line can end up
                # valid JSON yet incomplete.
                log.warning("账目里有一条残缺记录（缺 %s），已跳过: %.120s",
                            "、".join(missing), ln)
                continue
            out.append(entry)
        return out

    # ---------- undelivered alerts survive a restart ----------
    #
    # An alert held in memory is an alert lost the moment the relay restarts -
    # and this machine reboots twice a day. Anything not yet delivered goes to
    # disk and is only removed once a channel has actually accepted it.

    @property
    def pending_path(self) -> Path:
        return self.dir / "pending.json"

    def save_pending(self, payload: dict) -> None:
        tmp = self.pending_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.pending_path)  # atomic: never leave a half-written file

    def load_pending(self) -> dict:
        if not self.pending_path.exists():
            return {}
        try:
            data = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def report_sent(self, day: str) -> bool:
        return (self.dir / f"report-{day}.sent").exists()

    def interim_sent(self, day: str) -> bool:
        return (self.dir / f"interim-{day}.sent").exists()

    def interim_covered(self, day: str) -> int:
        """How many ledger entries the day's interim reports already cover.

        Stored as a count so a make-up run later the same day (new entries
        past the covered mark) triggers a fresh interim instead of being
        swallowed by a boolean "already sent today" - the operator's design
        is one interim per finished daytime round, not one per day.
        """
        try:
            raw = (self.dir / f"interim-{day}.sent").read_text(
                encoding="utf-8").strip()
        except OSError:
            return 0
        if not raw:
            # Legacy empty marker (pre-2026-08-20): sent, count unknown -
            # never re-announce the day's already-reported rounds.
            return 10**6
        try:
            return int(raw)
        except ValueError:
            return 10**6

    def mark_interim_sent(self, day: str, covered: int = 1) -> None:
        # Atomic: the machine is hard power-cut twice a day, and a torn write
        # leaves an empty marker. interim_covered reads empty as "sent, count
        # unknown" and returns 10**6, which silently suppresses every further
        # interim report that day - a failure that looks exactly like a quiet
        # afternoon.
        atomic_write_text(self.dir / f"interim-{day}.sent", str(covered))

    def mark_report_sent(self, day: str) -> None:
        (self.dir / f"report-{day}.sent").touch()

    # 卡池开服前一天要在群里播一条。按「游戏+开始时刻」记，不按天记——
    # 按天记的话，同一天有两个游戏换池就只播得出一个。
    def banner_announced(self, key: str) -> bool:
        return (self.dir / f"banner-{key}.sent").exists()

    def mark_banner_announced(self, key: str) -> None:
        (self.dir / f"banner-{key}.sent").touch()


def is_last_run_of_day(rec: RunRecord, cfg: Config) -> bool:
    """True once the day's final scheduled queue has finished.

    Configured as ARK_LAST_RUN_AFTER (server time). Anything finishing at or
    after that hour is treated as the day's closer.
    """
    try:
        hh, mm = (int(x) for x in cfg.last_run_after.split(":"))
    except ValueError:
        hh, mm = 21, 30
    finished = rec.finished.astimezone(SERVER_TZ)
    cutoff = finished.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return finished >= cutoff


def format_failure(rec: RunRecord, diagnosis: str = "") -> tuple[str, str]:
    """Immediate alert for a failed run. Title, body."""
    title = f"❌ {rec.script} 失败"
    # duration_known=False means start/finish came from filename/mtime, which
    # is hours wrong on this install ("未捕获到日志" runs - exactly the class
    # most likely to be a failure alert). Never present those as fact.
    if rec.duration_known:
        lines = [
            f"{both_clocks(rec.started)} → {both_clocks(rec.finished)}",
            f"用时 {rec.duration_min} 分钟 · 账号 {rec.user}",
            "",
        ]
    else:
        lines = [
            f"{both_clocks(rec.started)}（文件名时间，可能有偏差）",
            f"时长未知 · 账号 {rec.user}",
            "",
        ]
    lines.append("· " + _fmt_failed(rec.failed_tasks))
    if rec.sanity is not None:
        lines += ["", f"剩余理智 {rec.sanity}"]
        if rec.sanity_full_at:
            lines.append(rec.sanity_full_at)
    if diagnosis:
        lines += ["", "─" * 12, diagnosis]
    return title, "\n".join(lines)


def _fmt_items(d: dict, limit: int | None = None) -> str:
    """Render a {name: count} map, biggest first, as one line.

    `limit=None` means never fold. Output is the whole point of the report -
    an elided "…另1项" hides exactly the number the reader opened the message
    to see, and there is no way to go look it up afterwards.
    """
    if not d:
        return ""
    try:
        pairs = sorted(d.items(), key=lambda kv: -int(kv[1]))
    except (TypeError, ValueError):
        pairs = list(d.items())
    if limit is None or len(pairs) <= limit:
        return " ".join(f"{k}×{v}" for k, v in pairs)
    out = [f"{k}×{v}" for k, v in pairs[:limit]]
    out.append(f"…另{len(pairs) - limit}项")
    return " ".join(out)


def _fmt_failed(names: list[str], limit: int = 3) -> str:
    """Fold long failure lists.

    A run where everything failed means the script never got going - listing
    fourteen separate lines implies fourteen separate faults, which is both
    wrong and unreadable on a phone.
    """
    names = names or ["未知"]
    # 一定要带上「失败于」三个字。2026-08-27 的日报里这行只写了
    # 「赠送干员礼物、装备制造、基建任务」，看的人完全不知道这是失败清单
    # 还是运行清单——❌ 是哪一步断的，必须一眼能看出来。
    if len(names) <= limit:
        return "失败于：" + "、".join(names)
    return f"失败于 {len(names)} 项：" + "、".join(names[:limit]) + "…"


def _hm(dt: datetime) -> str:
    return f"{dt.astimezone(SERVER_TZ):%H:%M}"


def _span(started: datetime, finished: datetime, known: bool = True) -> str:
    """'09:00→09:18　17m　东京 10:00→10:18'.

    Both ends on both clocks. Showing only the Tokyo start meant the reader
    could see when a run began in their own time but had to do the arithmetic
    to know when it ended - on the one line where the whole point is the span.
    """
    tk = lambda d: f"{d.astimezone(USER_TZ):%H:%M}"  # noqa: E731
    if not known:
        return f"{_hm(started)}　时长未知　东京 {tk(started)}"
    mins = max(0, round((finished - started).total_seconds() / 60))
    dur = f"{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"{mins}m"
    return (f"{_hm(started)}→{_hm(finished)}　{dur}"
            f"　东京 {tk(started)}→{tk(finished)}")


# "理智将在 2026-08-17 05:33 回满。(20h 14m 后)"
_FULL_AT = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")


def _sanity_full(raw: str, ref: datetime) -> str:
    """'次日 05:33 回满（东京 06:33）'. '' when the source says nothing.

    A bare "2026-08-17 05:33" makes the reader work out whether that is tonight
    or tomorrow, which is the only thing they actually wanted to know.
    """
    m = _FULL_AT.search(str(raw or ""))
    if not m:
        return ""
    try:
        when = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
    except ValueError:
        return ""
    when = when.replace(tzinfo=SERVER_TZ)
    delta = (when.date() - ref.astimezone(SERVER_TZ).date()).days
    day = {0: "本日", 1: "次日"}.get(delta) or f"{delta} 天后"
    return f"{day} {when:%H:%M} 回满（东京 {when.astimezone(USER_TZ):%H:%M}）"


def episode_kinds(entries: list[dict]) -> dict[str, str]:
    """把「看着像失败、其实不是故障」的记录分出来。run_id → 类型。

    "update"      鸣潮：一串连续失败里含「游戏更新成功，即将重启任务」，
                  且紧接着就有一趟成功——整串都是客户端更新的插曲。
                  2026-09-02 早班：09:18 更新重启、09:20 失败、09:28 成功，
                  日报却写「❌ ❌」还推了一条 ⚠️ 自愈，用户点名的假报警。
    "maintenance" 终末地：任务全部秒败、零完成（collector.maaend_unreachable），
                  根本没进游戏——服务器维护或客户端待更新，不是配置问题。
    """
    kinds: dict[str, str] = {}
    groups: dict[tuple, list[dict]] = {}
    for e in entries:
        groups.setdefault((e.get("script"), e.get("user")), []).append(e)
    for es in groups.values():
        es = sorted(es, key=lambda e: e.get("started") or "")
        streak: list[dict] = []
        for e in es:
            raw = e.get("raw") or {}
            if not e.get("ok") and (raw.get("maaend_unreachable") or raw.get("okww_unreachable") or raw.get("maintenance")):
                kinds[e["run_id"]] = "maintenance"
            if e.get("ok"):
                if any(x.get("transitional") for x in streak):
                    for x in streak:
                        kinds.setdefault(x["run_id"], "update")
                streak = []
            else:
                streak.append(e)
    return kinds


_KIND_ICON = {"update": "↪️", "maintenance": "⏸"}
_KIND_NOTE = {"update": "游戏更新后重跑，不算失败",
              "maintenance": "进不了游戏（服务器维护／客户端待更新），今天跳过"}


# ── 三个游戏一个版式：以 MAA 为样板 ─────────────────────────
# 用户 2026-09-02：「模范生就是 MAA，你要青出于蓝而胜于蓝」。五行的**语义**：
#   做了　刷（什么）×次数
#   消耗　理智 N，吃药 N（鸣潮：波片 N，备用体力 N；终末地：理智 N，加强剂 N）
#   产出　这次刷本的掉落（鸣潮不读奖励界面，只能说类别）
#   剩余　理智 N/上限，回满时刻
#   备注　额外任务：公招、残像聚落、日常清单、自动采集……
# 没有的写「—」。三家字段都来自 collector 的解析器，MaaEnd/OK-WW 自己不产
# 这些数，是我们从它们的日志里算出来的。
_LABELS = ("做了", "消耗", "产出", "剩余", "备注")


def _row(label: str, parts: list[str]) -> str:
    return f"· {label}　" + ("；".join(x for x in parts if x) or "—")


def _block(e: dict, finished: datetime) -> list[str]:
    raw = e.get("raw") or {}
    script = e.get("script")
    did: list[str] = []
    cost: list[str] = []
    out: list[str] = []
    left: list[str] = []
    notes: list[str] = []

    if script == "MAA":
        if stages := raw.get("stages"):
            did.append("刷 " + "、".join(stages) + (f" ×{t}" if (t := raw.get("run_times")) else ""))
        if raw.get("sanity_spent") or raw.get("medicine_used"):
            cost.append(f"理智 {raw.get('sanity_spent') or 0}，吃药 {raw.get('medicine_used') or 0}")
        if drops := _fmt_items(e.get("drops") or {}):
            out.append(drops)
        if e.get("sanity") is not None:
            s = f"理智 {e['sanity']}"
            if full := _sanity_full(e.get("sanity_full_at"), finished):
                s += "，" + full
            left.append(s)
        if recruits := _fmt_items(e.get("recruits") or {}):
            notes.append("公招 " + recruits)

    elif script == "OK-WW":
        runs = raw.get("okww_runs") or 0
        farm = raw.get("okww_farm") or "模拟领域"
        if runs:
            dbl = raw.get("okww_runs_double") or 0
            did.append(f"刷 {farm} ×{runs}" + ("（双倍）" if dbl == runs else f"（双倍 {dbl}）" if dbl else ""))
        if raw.get("okww_stamina_spent") or raw.get("okww_backup_spent"):
            cost.append(f"波片 {raw.get('okww_stamina_spent') or 0}，"
                        f"备用体力 {raw.get('okww_backup_spent') or 0}")
        if drops := _fmt_items(raw.get("okww_farm_drops") or {}):
            out.append(drops)
        elif runs:
            out.append(str(raw.get("okww_farm_reward") or "副本奖励"))
        wl = raw.get("okww_stamina_left")
        if wl is not None:
            back = raw.get("okww_backup_stamina")
            s = f"波片 {wl}/240" + (f"，备用 {back}" if back is not None else "")
            if not (raw.get("okww_stamina_left_exact") or raw.get("okww_stopped")):
                s += "　※最后一次读数"
            if full := _sanity_full(raw.get("sanity_full_at"), finished):
                s += "，" + full
            left.append(s)
        for step in raw.get("okww_steps") or []:
            # 刷本那一项已经在「做了」里，这里只留额外任务
            if any(k in step for k in ("模拟领域", "凝素领域", "无音区")):
                continue
            notes.append(step)
        if raw.get("okww_nest_full") and not any("残象聚落" in n or "残像聚落" in n for n in notes):
            notes.append("残象聚落（已刷满）")
        if raw.get("okww_daily_done_at_start"):
            notes.append("今日日常此前已完成，本轮仅领奖")

    elif script == "MaaEnd":
        farm = raw.get("maaend_farm")
        runs = raw.get("maaend_farm_runs") or raw.get("protocol_runs") or 0
        if farm:
            place = raw.get("maaend_farm_place")
            did.append(f"刷 {farm}" + (f"·{place}" if place else "") + f" ×{runs}")
        if raw.get("maaend_sanity_spent") or raw.get("maaend_medicine"):
            cost.append(f"理智 {raw.get('maaend_sanity_spent') or 0}，"
                        f"加强剂 {raw.get('maaend_medicine') or 0}")
        elif farm and raw.get("sanity_exhausted"):
            cost.append("理智不足，一次没开成")
        if drops := _fmt_items(raw.get("maaend_farm_drops") or {}):
            out.append(drops)
        if e.get("sanity") is not None:
            s = f"理智 {e['sanity']}"
            if cap := raw.get("sanity_cap"):
                s += f"/{cap}"
                if e["sanity"] > cap:
                    s += "　⚠️ 已超上限，理智在溢出"
            if full := _sanity_full(e.get("sanity_full_at"), finished):
                s += "，" + full
            left.append(s)
        done = [t for t in (raw.get("tasks_done") or []) if not any(k in t for k in _END_FARM_NOTE_SKIP)]
        failed = raw.get("tasks_failed") or []
        if done or failed:
            # 用户 2026-09-02：备注太多，缩成「日常 1-16 项完成」，名单当注释
            # 放到整条通知的最末（见 daily_footnote）。
            n = f"日常 1-{len(done)} 项完成" if done else "日常 0 项"
            if failed:
                n += "；失败 " + "、".join(failed)
            notes.append(n)
        if routes := raw.get("maaend_collect_routes"):
            notes.append(f"自动采集 {routes} 条路线")

    return [_row(l, v) for l, v in zip(_LABELS, (did, cost, out, left, notes))]


# 「做了」里已经写了刷本，日常清单里就不再重复它，也不算「结束进程」那种收尾
_END_FARM_NOTE_SKIP = ("基质刷取", "协议空间", "结束进程")

def daily_footnote(entries: list[dict]) -> str:
    """通知最末的注释：终末地日常清单的编号对照。「日常 1-16 项完成」里的
    数字就是这里的序号。取当天最后一趟成功的 MaaEnd；没有就返回空串。"""
    for e in reversed(entries):
        if e.get("script") != "MaaEnd" or not e.get("ok"):
            continue
        raw = e.get("raw") or {}
        done = [t for t in (raw.get("tasks_done") or []) if not any(k in t for k in _END_FARM_NOTE_SKIP)]
        if done:
            return "———————\n日常：" + " ".join(f"{i}.{n}" for i, n in enumerate(done, 1))
    return ""


def format_daily(day: str, entries: list[dict], prose: str = "",
                 plan: str = "") -> tuple[str, str]:
    """The one message of the day. Numbers here are copied, never generated.

    Laid out for a narrow phone screen: no nested indentation (full-width
    spaces do not line up across fonts), one fact per short line.
    """
    if not entries:
        return f"📋 {day} 日报", "今天没有任何运行记录。"

    kinds = episode_kinds(entries)
    failed = [e for e in entries if not e["ok"] and e["run_id"] not in kinds]
    if failed:
        head = f"{len(failed)} 项失败 ⚠️"
    elif "maintenance" in kinds.values():
        head = "维护日跳过，其余全绿 ✅"
    else:
        head = "全绿 ✅"
    title = f"📋 {day[5:]} · {head}"

    lines: list[str] = []
    for e in entries:
        started = datetime.fromisoformat(e["started"])
        finished = datetime.fromisoformat(e["finished"])
        raw = e.get("raw") or {}
        kind = kinds.get(e["run_id"], "")
        icon = "✅" if e["ok"] else _KIND_ICON.get(kind, "❌")
        tag = "（剿灭检查）" if raw.get("annihilation") else ""
        lines.append(icon + f" {e['script']}{tag}　"
                     + _span(started, finished, e.get('duration_known', True)))
        # 没跑成的、剿灭检查那一分钟：只有一行备注，不摆五个空格子。
        if kind:
            lines += [_row("备注", [_KIND_NOTE[kind]]), ""]
            continue
        if not e["ok"]:
            lines += [_row("备注", [_fmt_failed(e.get("failed_tasks") or [])]), ""]
            continue
        if raw.get("annihilation"):
            prog = raw.get("annihilation_progress")
            if prog and prog[0] >= prog[1]:
                note = f"本周剿灭已打满（{prog[0]}/{prog[1]}）"
            elif prog:
                note = f"⚠️ 剿灭只打到 {prog[0]}/{prog[1]}，本周还没满"
            elif raw.get("annihilation_done"):
                note = "本周剿灭此前已完成，跳过"
            else:
                note = "已打剿灭"
            lines += [_row("备注", [note]), ""]
            continue
        lines += _block(e, finished)
        lines.append("")

    if prose:
        lines += ["———————", prose, ""]
    # Knowing last night was fine is only half of it - the operator also needs
    # to know what tomorrow will farm, while there is still time to change it.
    if plan:
        lines += ["———————", plan]
    return title, "\n".join(lines).rstrip()


def format_missing(what: str, expected_at: datetime, detail: str = "") -> tuple[str, str]:
    """Alert for something that should have happened and did not.

    This is the alert only a relay outside the monitored machine can produce.
    """
    title = f"🔌 {what}"
    body = [f"预计 {both_clocks(expected_at)} 应发生，至今没有。"]
    if detail:
        body += ["", detail]
    return title, "\n".join(body)


def stale_seconds(last: datetime | None, now: datetime | None = None) -> float:
    now = now or datetime.now(tz=SERVER_TZ)
    if last is None:
        return float("inf")
    return (now - last).total_seconds()


def next_occurrence(hhmm: str, now: datetime | None = None) -> datetime:
    """Next time-of-day on the server clock, today or tomorrow."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    hh, mm = (int(x) for x in hhmm.split(":"))
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)
