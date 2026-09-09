"""Judgment, bookkeeping, and message formatting.

Everything factual is decided here, in plain Python. The model is only ever
asked to phrase things (see summary.py). If it misbehaves the result is an
awkward sentence, never a wrong verdict.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from . import scoreboard, texts
from .statestore import StateStore
from .config import RunRecord, SERVER_TZ, USER_TZ, both_clocks

log = logging.getLogger("ark.core")


def _is_iso(v) -> bool:
    try:
        datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return False
    return True


class State:
    """Which runs have been handled, and today's ledger.

    Kept as line-delimited JSON so a half-written file costs at most one
    record, and so it stays readable when something goes wrong at 3am.
    """

    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.dir / "seen.txt"      # append-only and grows large; stays its own file
        self._seen: set[str] | None = None
        # The day's markers and the alert queue all live in state.json
        # (docs/STATE-MODEL.md): they used to be a dozen scattered .sent / .json
        # files where who wrote and who read what was carried in someone's head,
        # and one late write produced a false state.
        self.store = StateStore(state_dir)

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
            # Tells the model writing the report that this is not a failure but
            # a record superseded by the next round
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
        # Score the current code version while we are here. It sits here because
        # **every finished run has to pass through this line**, so nothing I write
        # into the daily report can touch it - which is exactly what the user
        # asked for on 2026-09-06:
        # 「我说『修好了』而它写『失败 1 趟』，谎话当场现形。」
        try:
            scoreboard.record(self.store, str(self.store.get("versions", "code") or ""),
                              rec.ok, rec.transitional)
        except Exception:
            # The scoreboard must never take the bookkeeping down with it: the
            # ledger is the main line, this entry is incidental.
            log.warning("记分牌没记上", exc_info=True)

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
            # A key being present does not mean its value is right. Both the
            # daily report and the shutdown decision run started/finished through
            # fromisoformat, and one unparseable record stops the whole day's
            # report from going out; shutdown waits for that report, so the
            # machine stays on all night. Same class of problem as the missing
            # keys above, and skipped the same way.
            bad = [k for k in ("started", "finished")
                   if not _is_iso(entry.get(k))]
            if bad:
                log.warning("账目里有一条时间不合法的记录（%s），已跳过: %.120s",
                            "、".join(bad), ln)
                continue
            out.append(entry)
        return out

    # ---------- undelivered alerts survive a restart ----------
    #
    # An alert held in memory is an alert lost the moment the relay restarts -
    # and this machine reboots twice a day. Anything not yet delivered goes to
    # disk and is only removed once a channel has actually accepted it.

    def save_pending(self, payload: dict) -> None:
        self.store.set("queues", "pending", dict(payload))

    def load_pending(self) -> dict:
        data = self.store.get("queues", "pending")
        return dict(data) if isinstance(data, dict) else {}

    def report_sent(self, day: str) -> bool:
        return self.store.get("marks", f"report:{day}") is not None

    def interim_sent(self, day: str) -> bool:
        return self.store.get("marks", f"interim:{day}") is not None

    def interim_covered(self, day: str) -> int:
        """How many ledger entries the day's interim reports already cover.

        Stored as a count so a make-up run later the same day (new entries
        past the covered mark) triggers a fresh interim instead of being
        swallowed by a boolean "already sent today" - the operator's design
        is one interim per finished daytime round, not one per day.
        """
        raw = self.store.get("marks", f"interim:{day}")
        if raw is None:
            return 0
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            # An old empty marker (before 2026-08-20): sent, count unknown -
            # never replay rounds that were already reported.
            return 10**6

    def mark_interim_sent(self, day: str, covered: int = 1) -> None:
        # Atomic: the machine is hard power-cut twice a day, and a torn write
        # leaves an empty marker. interim_covered reads empty as "sent, count
        # unknown" and returns 10**6, which silently suppresses every further
        # interim report that day - a failure that looks exactly like a quiet
        # afternoon.
        self.store.set("marks", f"interim:{day}", str(covered))

    def mark_report_sent(self, day: str) -> None:
        self.store.set("marks", f"report:{day}",
                       datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"))

    # The day before a banner goes live, say something in the group. Recorded by
    # "game + start time", not by day - keyed by day, two games rotating banners
    # on the same day would only ever get one announcement out.
    def banner_announced(self, key: str) -> bool:
        return self.store.get("marks", f"banner:{key}") is not None

    def mark_banner_announced(self, key: str) -> None:
        self.store.set("marks", f"banner:{key}",
                       datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"))
def format_failure(rec: RunRecord, diagnosis: str = "") -> tuple[str, str]:
    """Immediate alert for a failed run. Title, body."""
    title = texts.failed(rec.script)
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
    # The words 「失败于」 must be there. In the daily report of 2026-08-27 this
    # line read only 「赠送干员礼物、装备制造、基建任务」, and the reader had no way
    # to tell whether that was the failure list or the run list - which step the
    # ❌ broke on has to be obvious at a glance.
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
    """Pick out records that look like failures but are not faults. run_id -> kind.

    "update"      Wuthering Waves: a run of consecutive failures containing
                  「游戏更新成功，即将重启任务」 followed immediately by a success -
                  the whole run is an episode of the client updating.
                  2026-09-02 morning shift: 09:18 update restart, 09:20 failure,
                  09:28 success, yet the report said 「❌ ❌」 and pushed a ⚠️
                  self-heal notice - a false alarm the user called out by name.
    "maintenance" Endfield: every task fails instantly with zero completions
                  (collector.maaend_unreachable), i.e. the game was never
                  entered - server maintenance or a client update pending, not a
                  configuration problem.
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
            elif (not e.get("ok") and e.get("script") == "MaaEnd" and e.get("failed_tasks")
                  and set(e["failed_tasks"]) <= {"应急理智加强剂", "自动采集"}):
                kinds[e["run_id"]] = "soft"
            elif not e.get("ok") and raw.get("maintenance_day"):
                kinds[e["run_id"]] = "soft"
            if e.get("ok"):
                if any(x.get("transitional") for x in streak):
                    for x in streak:
                        kinds.setdefault(x["run_id"], "update")
                streak = []
            else:
                streak.append(e)
    return kinds


_KIND_ICON = {"update": "↪️", "maintenance": "⏸", "soft": "🟡"}
_KIND_NOTE = {"update": "游戏更新后重跑，不算失败",
              "maintenance": "进不了游戏（服务器维护／客户端待更新），今天跳过",
              "soft": "其余都做了，只有上游还没修好的那项没成"}


# ── One layout for all three games, modelled on MAA ─────────────────────────
# The user, 2026-09-02: 「模范生就是 MAA，你要青出于蓝而胜于蓝」. The **meaning** of
# the five rows:
#   做了　farmed (what) x times
#   消耗　sanity N, potions N (Wuthering Waves: waveplates N, backup stamina N;
#         Endfield: sanity N, boosters N)
#   产出　what this farming run dropped (Wuthering Waves does not read the reward
#         screen, so only the category can be given)
#   剩余　sanity N/cap, and when it refills
#   备注　extra tasks: recruitment, tacet nests, the daily list, auto-collect ...
# Anything absent is written as 「—」. All three games' fields come from
# collector's parsers; MaaEnd and OK-WW do not produce these numbers themselves,
# we compute them from their logs.
_LABELS = ("做了", "消耗", "产出", "剩余", "备注")


def _row(label: str, parts: list[str]) -> str:
    return f"· {label}　" + ("；".join(x for x in parts if x) or "—")


def _block_maa(e: dict, raw: dict, finished: datetime) -> tuple[list[str], ...]:
    """The five rows for one Arknights run: 做了 / 消耗 / 产出 / 剩余 / 备注.

    Its own function because the three games share no data-extraction rules at
    all: stage names, sanity, sanity potions and recruitment exist only for MAA.
    Merged into one place, changing MAA meant skipping sixty-odd lines belonging
    to the other two, and getting it wrong was invisible.
    The five returned lists are ordered per _LABELS; _block assembles them into
    the five rows.
    """
    did: list[str] = []
    cost: list[str] = []
    out: list[str] = []
    left: list[str] = []
    notes: list[str] = []
    if stages := raw.get("stages"):
        did.append("刷 " + "、".join(stages) + (f" ×{t}" if (t := raw.get("run_times")) else ""))
    elif not raw.get("sanity_spent"):
        # With combat turned off, the run only does base, recruitment and
        # collecting rewards. All five rows used to read 「—」, which showed
        # neither whether it ran at all nor why no stage was farmed.
        did.append("只做日常（未刷关卡）")
    if raw.get("sanity_spent") or raw.get("medicine_used"):
        cost.append(f"理智 {raw.get('sanity_spent') or 0}，吃药 {raw.get('medicine_used') or 0}")
    if drops := _fmt_items(e.get("drops") or {}):
        out.append(drops)
    # Farming a stage down to 0 sanity means that 0 is real data and must be
    # printed as-is. But a run with combat turned off never read sanity at all
    # and MAA records 0 for that too - that 0 means "no data", and printing it as
    # 「剩余 理智 0」 is a lie (the account plainly still has sanity).
    # Tell them apart by whether anything was actually fought: only then is the
    # number trusted.
    fought = bool(raw.get("stages") or raw.get("sanity_spent"))
    if e.get("sanity") is not None and (fought or e.get("sanity")):
        s = f"理智 {e['sanity']}"
        if full := _sanity_full(e.get("sanity_full_at"), finished):
            s += "，" + full
        left.append(s)
    if recruits := _fmt_items(e.get("recruits") or {}):
        notes.append("公招 " + recruits)

    return did, cost, out, left, notes


def _block_okww(raw: dict, finished: datetime) -> tuple[list[str], ...]:
    """The five rows for one Wuthering Waves (OK-WW) run: 做了 / 消耗 / 产出 / 剩余 / 备注.

    Its own function because Wuthering Waves measures everything its own way:
    stamina is called 「波片」, there is a separate pool of backup stamina, the
    remaining figure is not necessarily exact, and extra tasks have to be picked
    out of okww_steps one by one.
    The five returned lists are ordered per _LABELS; _block assembles them into
    the five rows.
    """
    did: list[str] = []
    cost: list[str] = []
    out: list[str] = []
    left: list[str] = []
    notes: list[str] = []
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
        # The farming entry is already in 做了; keep only the extra tasks here
        if any(k in step for k in ("模拟领域", "凝素领域", "无音区")):
            continue
        notes.append(step)
    if raw.get("okww_nest_full") and not any("残象聚落" in n or "残像聚落" in n for n in notes):
        notes.append("残象聚落（已刷满）")
    if raw.get("okww_daily_done_at_start"):
        notes.append("今日日常此前已完成，本轮仅领奖")

    return did, cost, out, left, notes


def _block_maaend(e: dict, raw: dict, finished: datetime) -> tuple[list[str], ...]:
    """The five rows for one Endfield (MaaEnd) run: 做了 / 消耗 / 产出 / 剩余 / 备注.

    Its own function because Endfield has a few things nothing else has: sanity
    has a cap and can overflow, which needs a warning, and the daily list is long
    enough that it has to be collapsed into 「日常 1-N 项完成」 with the names moved
    to the end of the notification.
    The five returned lists are ordered per _LABELS; _block assembles them into
    the five rows.
    """
    did: list[str] = []
    cost: list[str] = []
    out: list[str] = []
    left: list[str] = []
    notes: list[str] = []
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
        # The user, 2026-09-02: too many notes - collapse them into
        # 「日常 1-16 项完成」 and move the list to the very end of the
        # notification as a footnote (see daily_footnote).
        # A short list is clearer named than numbered: 「日常 1-1 项完成」 told the
        # reader nothing on 2026-09-09, where the one item was 据点交易.
        if not done:
            n = "日常 0 项"
        elif len(done) <= 3:
            n = "做了 " + "、".join(done)
        else:
            n = f"日常 1-{len(done)} 项完成"
        # Only when AUTO-MAS still called the run a success: the renderer already
        # names the failure on a run marked failed, and saying it twice on the
        # same line contradicted the retry note on 2026-09-09.
        if failed and e.get("ok"):
            n += "；失败 " + "、".join(failed)
        notes.append(n)
    if routes := raw.get("maaend_collect_routes"):
        notes.append(f"自动采集 {routes} 条路线")

    return did, cost, out, left, notes


def _rows_for(e: dict, finished: datetime) -> tuple[list[str], ...]:
    """The five lists for one run, before they are turned into rows."""
    raw = e.get("raw") or {}
    script = e.get("script")
    rows: tuple[list[str], ...] = ([], [], [], [], [])

    if script == "MAA":
        rows = _block_maa(e, raw, finished)
    elif script == "OK-WW":
        rows = _block_okww(raw, finished)
    elif script == "MaaEnd":
        rows = _block_maaend(e, raw, finished)
    return rows


def _block(e: dict, finished: datetime) -> list[str]:
    return [_row(l, v) for l, v in zip(_LABELS, _rows_for(e, finished))]


def retried_notes(entries: list[dict]) -> dict[str, str]:
    """For a failed run whose failed tasks a later run of the same script finished
    that same day: run_id -> a line saying when the retry got them.

    2026-09-09: Endfield ran 1h20m, everything went through except 据点交易, and
    AUTO-MAS retried it two minutes later and it worked. The report showed a red
    run with nothing in it and a green two-minute run with five empty rows, so
    there was no way to tell the day had in fact gone fine.
    """
    out: dict[str, str] = {}
    for e in entries:
        if e.get("ok") or not e.get("failed_tasks"):
            continue
        want = set(e["failed_tasks"])
        for later in entries:
            if later is e or not later.get("ok"):
                continue
            if later.get("script") != e.get("script") or later.get("user") != e.get("user"):
                continue
            if (later.get("started") or "") <= (e.get("started") or ""):
                continue
            done = set((later.get("raw") or {}).get("tasks_done") or [])
            if want <= done:
                when = str(later.get("finished") or "")[11:16]
                out[e["run_id"]] = ("、".join(sorted(want))
                                    + f"　后来在 {when} 那趟重试里做成了")
                break
    return out


# Farming is already stated in 做了, so it is not repeated in the daily list,
# and wrap-up steps like 「结束进程」 do not count either
_END_FARM_NOTE_SKIP = ("基质刷取", "协议空间", "结束进程")

def daily_footnote(entries: list[dict]) -> str:
    """The footnote at the end of the notification: the numbered key to Endfield's
    daily list. The number in 「日常 1-16 项完成」 is the index here. Uses the last
    successful MaaEnd run of the day; returns an empty string if there is none."""
    best: list[str] = []
    for e in entries:
        if e.get("script") != "MaaEnd":
            continue
        raw = e.get("raw") or {}
        done = [t for t in (raw.get("tasks_done") or [])
                if not any(k in t for k in _END_FARM_NOTE_SKIP)]
        # The longest list of the day, whether or not that run was marked failed.
        # Taking the last **successful** run picked the two-minute retry on
        # 2026-09-09 and printed a one-item 「daily list」.
        if len(done) > len(best):
            best = done
    if best:
        return "———————\n日常：" + " ".join(f"{i}.{n}" for i, n in enumerate(best, 1))
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
    retried = retried_notes(entries)
    failed = [e for e in entries if not e["ok"]
              and e["run_id"] not in kinds and e["run_id"] not in retried]
    if failed:
        head = f"{len(failed)} 项失败 ⚠️"
    elif retried:
        head = "全绿 ✅（有项目重试后成功）"
    elif "soft" in kinds.values():
        head = "全绿 ✅（个别上游项没成）"
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
        icon = ("✅" if e["ok"]
                else _KIND_ICON.get(kind) or ("↻" if e["run_id"] in retried else "❌"))
        tag = "（剿灭检查）" if raw.get("annihilation") else ""
        lines.append(icon + f" {e['script']}{tag}　"
                     + _span(started, finished, e.get('duration_known', True)))
        # For a run that did not go through, and for the one-minute annihilation
        # check: a single note row, not five empty slots.
        if kind == "soft":
            note = "没做成：" + "、".join(e.get("failed_tasks") or []) + "（上游问题，不算失败）"
            if routes := raw.get("maaend_collect_done"):
                note += f"；自动采集 {routes} 条路线已采"
            lines += [_row("备注", [note]), ""]
            continue
        if kind:
            lines += [_row("备注", [_KIND_NOTE[kind]]), ""]
            continue
        if not e["ok"]:
            # A run that failed one task out of twenty still did the other
            # nineteen. Printing only 「失败于：X」 threw all of it away - on
            # 2026-09-09 an 80-minute Endfield run that collected the whole
            # daily, the pass rewards and 135000 折金票 was reduced to one line
            # naming the single step that did not work.
            did, cost, out, left, notes = _rows_for(e, finished)
            notes.insert(0, retried.get(e["run_id"])
                         or _fmt_failed(e.get("failed_tasks") or []))
            if not (did or cost or out or left):
                lines += [_row("备注", notes), ""]
                continue
            lines += [_row(l, v) for l, v in
                      zip(_LABELS, (did, cost, out, left, notes))]
            lines.append("")
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
        did, cost, out, left, notes = _rows_for(e, finished)
        if notes and not (did or cost or out or left):
            # Four 「—」 rows above one real line is noise. The two-minute retry on
            # 2026-09-09 printed exactly that.
            lines += [_row("备注", notes), ""]
            continue
        lines += [_row(l, v) for l, v in
                  zip(_LABELS, (did, cost, out, left, notes))]
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
    title = texts.missing(what)
    body = [f"预计 {both_clocks(expected_at)} 应发生，至今没有。"]
    if detail:
        body += ["", detail]
    return title, "\n".join(body)
