"""One ledger entry as report rows (做了 / 消耗 / 产出 / 剩余 / 备注), one builder per tool.

Also the rule for which MaaEnd tasks count as done without evidence
(`maaend_unverified`: MaaFW's own steps for four tasks, a log line for the rest),
which the daily report and the alarm text share.
"""
from __future__ import annotations

import re
import json
import inspect
import logging
import threading
from datetime import datetime, timedelta
from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ, USER_TZ, RunRecord, both_clocks, GAME_ZH, atomic_write_text
from ark_relay.features.collector_maaend import _END_CLOSING_TASKS, _END_STOP_MARK, TRAIL_MISS_FAIL, trail_unread
from pathlib import Path
from ark_relay.core.statestore import StateStore

def _fmt_items(d: dict, limit: int | None = None) -> str:
    """Render a {name: count} map, biggest first, as one line.

    `limit=None` (what every caller passes) never folds: a drop count elided
    as "…另1项" cannot be looked up afterwards.
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


def _with_causes(names: list[str], causes: dict | None) -> list[str]:
    """「基质刷取」 -> 「基质刷取（背包满了）」 where the cause is known
    (collector_maaend._maaend_fail_causes). A CLAIM_UNCONFIRMED cause, which
    older ledger lines may carry, is not shown."""
    from ark_relay.features.collector_maaend import CLAIM_UNCONFIRMED  # noqa: PLC0415
    causes = {k: v for k, v in (causes or {}).items() if v != CLAIM_UNCONFIRMED}
    return [f"{n}（{causes[n]}）" if n in causes else n for n in names]


_FULL_AT = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")


def _sanity_full(raw: str, ref: datetime) -> str:
    """'次日 05:33 回满（东京 06:33）': today / tomorrow / N days, on both clocks.
    '' when the source says nothing.
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


# ── One layout for all three games, modelled on MAA ─────────────────────────
# The five rows:
#   做了　farmed (what) x times
#   消耗　sanity N, potions N (Wuthering Waves: waveplates N, backup stamina N;
#         Endfield: sanity N, boosters N)
#   产出　what this farming run dropped (Wuthering Waves does not read the reward
#         screen, so only the category can be given)
#   剩余　sanity N/cap, and when it refills
#   备注　extra tasks: recruitment, tacet nests, the daily list, auto-collect ...
# Anything absent is written as 「—」. The fields come from collector's parsers;
# for MaaEnd and OK-WW the numbers are computed from their logs.
_LABELS = ("做了", "消耗", "产出", "剩余", "备注")


def _row(label: str, parts: list[str]) -> str:
    return f"· {label}　" + ("；".join(x for x in parts if x) or "—")


def _block_maa(e: dict, raw: dict, finished: datetime) -> tuple[list[str], ...]:
    """The five rows for one Arknights run: 做了 / 消耗 / 产出 / 剩余 / 备注.

    Stage names, sanity, sanity potions and recruitment exist only for MAA.
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
        # Combat off: the run only does base, recruitment and rewards.
        did.append("只做日常（未刷关卡）")
    if raw.get("sanity_spent") or raw.get("medicine_used"):
        cost.append(f"理智 {raw.get('sanity_spent') or 0}，吃药 {raw.get('medicine_used') or 0}")
    if drops := _fmt_items(e.get("drops") or {}):
        out.append(drops)
    # MAA records sanity 0 also for a run that never read it (combat off), so a
    # 0 is printed only when something was fought.
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

    Stamina is 「波片」 with a separate pool of backup stamina, the remaining
    figure may be the last reading rather than exact, and extra tasks are
    picked out of okww_steps one by one.
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
    if n := raw.get("okww_weekly_topup_unread"):
        # Claims topped up with backup in a log without the top bar: the split
        # between waveplates and backup is not in the log, so it is not guessed.
        cost.append(f"另有周本领奖 {n} 次用备用体力补足（各 60，波片和备用各占多少日志里没记）")
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
        # The farming entry is already in 做了; keep only the extra tasks here.
        if any(k in step for k in ("模拟领域", "凝素领域", "无音区")):
            continue
        notes.append(step)
    if raw.get("okww_nest_full") and not any("残象聚落" in n or "残像聚落" in n for n in notes):
        notes.append("残象聚落（已刷满）")
    if raw.get("okww_daily_done_at_start"):
        notes.append("今日日常此前已完成，本轮仅领奖")

    return did, cost, out, left, notes


def _block_maaend(e: dict, raw: dict, finished: datetime,
                  footnote: "list[str] | None" = None) -> tuple[list[str], ...]:
    """The five rows for one Endfield (MaaEnd) run: 做了 / 消耗 / 产出 / 剩余 / 备注.

    Sanity has a cap and can overflow (warned), and a long daily list is
    collapsed into 「日常 1-N 项完成」 with the names in the footnote
    (ledger_report.daily_footnote; `footnote` is its list of names).
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
    if raw.get("maaend_sanity_unfit"):
        # The log's readings do not fit the per-claim rule
        # (collector_maaend._claims_fit): no sanity figure.
        cost.append("理智消耗没读到" + (f"，加强剂 {raw['maaend_medicine']}" if raw.get("maaend_medicine") else ""))
    elif raw.get("maaend_sanity_spent") or raw.get("maaend_medicine"):
        cost.append(f"理智 {raw.get('maaend_sanity_spent') or 0}，"
                    f"加强剂 {raw.get('maaend_medicine') or 0}")
    elif farm and runs:
        # It ran but no figure was read: never say it did not run.
        cost.append("理智消耗没读到")
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
    done = _maaend_listed(raw)
    # Every task MaaEnd skipped by its weekday schedule is in
    # raw["maaend_tasks_skipped"] and already out of tasks_done
    # (collector_maaend._schedule_skipped); it is named in the notes below.
    skipped = raw.get("maaend_tasks_skipped") or {}
    # Done only with evidence from the game; the rest are named as unverified, and
    # the four left unjudged (MaaFW's log held none of them) are said as such.
    unverified = maaend_unverified(raw)
    unjudged = maaend_unjudged(raw)
    done = [t for t in done if t not in unverified and t not in unjudged]
    failed = raw.get("tasks_failed") or []
    if done or failed or unverified or unjudged:
        # More than three: 「日常 1-N 项完成」, names in the footnote
        # (daily_footnote). Three or fewer are named here, and so is a list the
        # footnote's 1-N would not name (another run's longer list is the key).
        if not done:
            n = "日常 0 项"
        elif len(done) <= 3 or (footnote is not None and footnote[:len(done)] != done):
            n = "做了 " + "、".join(done)
        else:
            n = f"日常 1-{len(done)} 项完成"
        # Only when AUTO-MAS still called the run a success: on a run marked
        # failed the renderer already names the failure.
        if failed and e.get("ok"):
            n += "；失败 " + "、".join(_with_causes(failed, raw.get("maaend_fail_causes")))
        notes.append(n)
        if unverified:
            # With what MaaEnd's own record shows for each of the four (e.g. it stopped
            # itself inside the task, and why), so the report keeps the cause after
            # another run of the day did the task (machine check #28 then stays quiet).
            notes.append(UNVERIFIED + "：" + "、".join(
                f"{t}（{why}）" if (why := maaend_unbacked_why(raw, t)) else t for t in unverified))
        if unjudged:
            notes.append(texts.trail_unread_note(unjudged, int(raw.get("tasks_trail_miss") or 0), TRAIL_MISS_FAIL))
    if total := raw.get("maaend_collect_total"):
        # Walked/total from the run's own 「路线N：…」 lines (a narrowed retry
        # round reads 「自动采集 2/2 条走通」).
        n = f"自动采集 {raw.get('maaend_collect_done', 0)}/{total} 条走通"
        if bad := raw.get("maaend_collect_failed"):
            n += "，没走通：" + "、".join(bad)
        if blocked := raw.get("maaend_collect_blocked"):
            # Walked, but gathered nothing (collector_maaend.blocked_routes).
            n += "，" + texts.collect_blocked_row(blocked)
        notes.append(n)
    elif routes := raw.get("maaend_collect_routes"):
        notes.append(f"自动采集 {routes} 条路线")
    elif wd := raw.get("maaend_collect_skipped"):
        notes.append(f"自动采集 今天{wd}不是采集日（排班只有周一、周四），按排班跳过，没走路线")
    # 自动采集 has its own sentence above; the rest are said here, by name.
    if other := [(n, wd) for n, wd in skipped.items() if "自动采集" not in n]:
        notes.append("按排班跳过、没有做：" + "、".join(f"{n}（今天{wd}）" for n, wd in other))
    if isinstance(sw := raw.get("maaend_essence_filler"), dict):
        # The relay then switched 基质刷取 to filler mode (features/essence/essence.step).
        notes.append(texts.essence_filler_on(list(sw.get("weapons") or [])))
    elif raw.get("maaend_essence_met"):
        # Target mode ended with ticked weapons' essences owned (collector_maaend._farm_one):
        # either already owned before farming or finished after farming in this run.
        notes.append(texts.ESSENCE_TARGET_MET_AFTER_FARM if raw.get("maaend_farm_runs")
                     else texts.ESSENCE_TARGET_MET)

    return did, cost, out, left, notes


def _rows_for(e: dict, finished: datetime, footnote: "list[str] | None" = None) -> tuple[list[str], ...]:
    """The five lists for one run, before they are turned into rows; `footnote`
    is the day's Endfield daily key (ledger_report.footnote_tasks)."""
    raw = e.get("raw") or {}
    script = e.get("script")
    rows: tuple[list[str], ...] = ([], [], [], [], [])

    if script == "MAA":
        rows = _block_maa(e, raw, finished)
    elif script == "OK-WW":
        rows = _block_okww(raw, finished)
    elif script == "MaaEnd":
        rows = _block_maaend(e, raw, finished, footnote)
    return rows


def _block(e: dict, finished: datetime) -> list[str]:
    return [_row(label, v) for label, v in zip(_LABELS, _rows_for(e, finished), strict=True)]


# Farming is already stated in 做了, so it is not repeated in the daily list, and
# wrap-up steps (the closing tasks 「关闭游戏（PC）」 / 「结束进程」, and 「停止任务」:
# MaaEnd stopping its own tasker) are not in-game tasks. The collector's own
# tuples, so the report and the round-closed check agree on what a wrap-up is.
_END_WRAPUP = (*_END_CLOSING_TASKS, _END_STOP_MARK)
_END_FARM_NOTE_SKIP = ("基质刷取", "协议空间", *_END_WRAPUP)


# A task the program called finished with nothing from the game to show for it:
# neither done nor failed. The daily report names it with this and never counts
# it as done.
UNVERIFIED = "没证据，不算完成（只有程序自己说做完了）"


# The same, inside an OK-WW step (collector_okww._okww_steps): 「周常乐园（没读到做完，不算完成）」.
UNVERIFIED_STEP = "不算完成"


def _maaend_listed(raw: dict) -> list[str]:
    """The MaaEnd tasks the daily list is about: farming has its own rows,
    the wrap-up is not an in-game task, a skipped gathering day is said apart."""
    done = [t for t in (raw.get("tasks_done") or []) if not any(k in t for k in _END_FARM_NOTE_SKIP)]
    if raw.get("maaend_collect_skipped"):
        done = [t for t in done if "自动采集" not in t]
    return done


def maaend_unverified(raw: dict) -> list[str]:
    """Listed MaaEnd tasks with no game evidence.

A record booked before raw['tasks_trail'] existed (no such key) is read by the rule
    it was booked under, picture included, so the days before this change keep the
    verdict they were reported with.
    """
    ev = raw.get("tasks_evidence") or {}
    if "tasks_trail" not in raw:
        shot = set(raw.get("tasks_shot") or [])
        return [t for t in _maaend_listed(raw) if not ev.get(t) and t not in shot]
    trail = raw.get("tasks_trail") or {}
    unjudged = set(maaend_unjudged(raw))

    def backed(t: str) -> bool:
        if t in unjudged:
            return True
        if isinstance(trail.get(t), dict):
            return bool(trail[t].get("ok"))
        return bool(ev.get(t))
    return [t for t in _maaend_listed(raw) if not backed(t)]


def maaend_unjudged(raw: dict) -> list[str]:
    """Listed tasks of raw['tasks_trail'] left unjudged this run: unread (MaaFW's log held
    none of the four, or does not reach back to that task's start - maaend_fwlog.
    trail_table; raw['tasks_trail_miss'] counts the runs in a row with one) and that has
    not yet happened maaend_fwlog.TRAIL_MISS_FAIL times in a row - as machine check #28
    waits. The tasks of the run the log does hold are judged as usual. The daily report
    says so; neither done nor 「没证据」 (core.day_unverified_items)."""
    miss = int(raw.get("tasks_trail_miss") or 0)
    if not 0 < miss < TRAIL_MISS_FAIL:
        return []
    trail = raw.get("tasks_trail") or {}
    return [t for t in _maaend_listed(raw) if isinstance(trail.get(t), dict) and trail_unread(trail[t])]


def maaend_unbacked_why(raw: dict, task: str) -> str:
    """What MaaFW's log shows for an unbacked task of raw['tasks_trail'] (its verdict,
    MaaEnd's own reason when it stopped itself), or '' when there is nothing to add."""
    e = (raw.get("tasks_trail") or {}).get(task)
    if not isinstance(e, dict):
        return ""
    if e.get("found") is False:
        miss = int(raw.get("tasks_trail_miss") or 0)
        if miss and trail_unread(e):
            return f"终末地自己的记录连续 {miss} 趟没读到这一项"
        return "终末地自己的记录里找不到这一项"
    return str(e.get("said") or "")


def format_failure(rec: RunRecord, diagnosis: str = "") -> tuple[str, str]:
    """Immediate alert for a failed run. Title, body."""
    title = texts.failed(rec.script)
    # duration_known=False means start/finish came from filename/mtime, which
    # is hours off on this install (「未捕获到日志」 runs, for one). Those are
    # never presented as the run's time.
    if rec.duration_known:
        lines = [
            f"{both_clocks(rec.started)} → {both_clocks(rec.finished)}",
            f"用时 {rec.duration_min} 分钟 · 账号 {rec.user}",
            "",
        ]
    else:
        lines = [
            f"{both_clocks(rec.started)}（时间取自文件名，不是日志）",
            f"时长未知 · 账号 {rec.user}",
            "",
        ]
    raw = rec.raw or {}
    lines.append("· " + _fmt_failed(rec.failed_tasks, causes=raw.get("maaend_fail_causes")))
    # collector_maa: MAA refused a task of its queue; the same config will be refused again.
    if rejected := raw.get("maa_config_rejected"):
        lines.append("· " + texts.maa_rejected_line(rejected))
    # 0 only when the log was read and covers the queue (collector_maa._maa_fights);
    # a missing count is unknown and says nothing.
    if raw.get("fight_count") == 0 and not raw.get("sanity_spent") and not rec.drops:
        lines += ["", texts.NO_FIGHT]
    if rec.sanity is not None:
        lines += ["", f"剩余理智 {rec.sanity}"]
        if rec.sanity_full_at:
            lines.append(rec.sanity_full_at)
    elif raw.get("sanity_unread"):
        lines += ["", texts.SANITY_UNREAD]
    if diagnosis:
        lines += ["", "─" * 12, diagnosis]
    if claim := (rec.raw or {}).get("maaend_claim_lines"):
        lines += _claim_block(claim)
    # The evidence bundle link is part of this alarm (no push of its own).
    if page := (rec.raw or {}).get("evidence_page"):
        lines += ["", f"证据包：{page}"]
    return title, "\n".join(lines)


def _claim_block(claim: dict) -> list[str]:
    """The raw MaaEnd lines of an essence failure right after the claim click with no
    storage-full notice (collector_maaend.claim_lines), under plain headings."""
    out: list[str] = []
    for task, part in (claim or {}).items():
        if not isinstance(part, dict):
            continue
        out += ["", texts.claim_lines_head(task), texts.CLAIM_LINES_RUN, *(part.get("run") or [])]
        if part.get("fw"):
            out += [texts.CLAIM_LINES_FW, *part["fw"]]
        else:
            out.append(texts.claim_lines_fw_none(part.get("fw_why") or "没有"))
    return out


def _fmt_failed(names: list[str], limit: int = 3, causes: dict | None = None) -> str:
    """Fold long failure lists: a run where everything failed is one line with a
    count, not one line per task.
    """
    names = _with_causes(names, causes) or ["未知"]
    # 「失败于」 marks the list as the failed steps, not the steps that ran.
    if len(names) <= limit:
        return "失败于：" + "、".join(names)
    return f"失败于 {len(names)} 项：" + "、".join(names[:limit]) + "…"


def _hm(dt: datetime) -> str:
    return f"{dt.astimezone(SERVER_TZ):%H:%M}"


def _span(started: datetime, finished: datetime, known: bool = True) -> str:
    """'09:00→09:18　17m　东京 10:00→10:18': both ends on both clocks."""
    tk = lambda d: f"{d.astimezone(USER_TZ):%H:%M}"  # noqa: E731
    if not known:
        return f"{_hm(started)}　时长未知　东京 {tk(started)}"
    mins = max(0, round((finished - started).total_seconds() / 60))
    dur = f"{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"{mins}m"
    return (f"{_hm(started)}→{_hm(finished)}　{dur}"
            f"　东京 {tk(started)}→{tk(finished)}")


def maa_mode(e: dict) -> str:
    """Which of AUTO-MAS's MAA jobs a ledger line (or a record's fields) was: its
    Annihilation mode (raw.annihilation from collector_maa) or its Routine mode.
    """
    if not isinstance(e, dict) or e.get("script") != "MAA":
        return ""
    raw = e.get("raw")
    return "剿灭" if isinstance(raw, dict) and raw.get("annihilation") else "日常"


def manual_stop(e: dict) -> bool:
    """Whether a ledger line is a run the red button (停一切) cut short
    (raw.manual_stop, set by handle._handle or handle.backfill_manual_stops).

    Whatever AUTO-MAS wrote for such a run - Success! or a failure - says nothing
    about the script, so it is neither a success nor a failure. The one definition
    for every reader: episode_kinds, the daily headline, the phone's run counts,
    gameupdate's "last round today".
    """
    raw = e.get("raw") if isinstance(e, dict) else None
    return isinstance(raw, dict) and bool(raw.get("manual_stop"))


def episode_kinds(entries: list[dict]) -> dict[str, str]:
    """Pick out records that look like failures but are not faults. run_id -> kind.

    "update"      A run of consecutive failures of one script and account that
                  contains 「游戏更新成功，即将重启任务」 (a transitional record) or a
                  MaaEnd self-update restart, followed by a success: the client
                  updating, not a fault. Also a MaaEnd update restart after its
                  shift's round was already done.
    "maintenance" A failed run flagged maaend_unreachable, okww_unreachable or
                  maintenance: the game was never entered (server maintenance
                  or a client update pending).
    "nosanity"    MAA: not enough sanity for the stage (maa_sanity_short).
    "manual"      Any script: the red button (停一切) cut this run short
                  (raw.manual_stop, set by handle._handle). Neither a success
                  nor a failure, so it neither closes a streak nor joins one.
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
            if manual_stop(e):
                kinds[e["run_id"]] = "manual"
                continue
            # A MaaEnd run failing on 自动采集 / 应急理智加强剂 alone, and a MAA
            # run failing on its update day, are failures like any other.
            if not e.get("ok") and (raw.get("maaend_unreachable") or raw.get("okww_unreachable") or raw.get("maintenance")):
                kinds[e["run_id"]] = "maintenance"
            elif not e.get("ok") and raw.get("maa_sanity_short"):
                kinds[e["run_id"]] = "nosanity"
            elif not e.get("ok") and raw.get("maaend_update_restart") and raw.get("maaend_update_after_done"):
                # MaaEnd installing its new build after its shift's round was
                # already done (handle._drop_update_after_done): no success follows
                # it, and none is needed.
                kinds[e["run_id"]] = "update"
            if e.get("ok"):
                if any((x.get("raw") or {}).get("maaend_update_restart") for x in streak):
                    # A MaaEnd update restart explains only its own attempt, not
                    # the other failures in the streak.
                    for x in streak:
                        if (x.get("raw") or {}).get("maaend_update_restart"):
                            kinds.setdefault(x["run_id"], "update")
                elif any(x.get("transitional") for x in streak):
                    for x in streak:
                        kinds.setdefault(x["run_id"], "update")
                streak = []
            else:
                streak.append(e)
    return kinds


def _ran_later(e: dict, entries: list[dict]) -> bool:
    """Whether the same script and user ran again after this run that day."""
    return any(x is not e and x.get("script") == e.get("script") and x.get("user") == e.get("user")
               and (x.get("started") or "") > (e.get("started") or "") for x in entries)


_KIND_ICON = {"update": "↪️", "maintenance": "⏸", "nosanity": "🟡", "manual": "⏹"}


_KIND_NOTE = {"update": "游戏更新后重跑，不算失败",
              "manual": "被停一切中途停掉，不算成功也不算失败",
              "maintenance": "进不了游戏（服务器维护／客户端待更新），今天跳过",
              "nosanity": "理智不够这关的费用，没打，不算失败"}


def _collapse_retries(entries: list[dict], kinds: dict) -> list[tuple[dict, list[dict]]]:
    """Consecutive "nosanity" records of one script become one row.

    AUTO-MAS retries a failed phase up to three times, which would list three
    identical 🟡 rows. The row keeps the first record's data and spans to the
    last attempt's finish.
    """
    out: list[tuple[dict, list[dict]]] = []
    for e in entries:
        kind = kinds.get(e["run_id"], "")
        if out and kind == "nosanity":
            prev, group = out[-1]
            if prev["script"] == e["script"] and kinds.get(prev["run_id"], "") == kind:
                group.append(e)
                continue
        out.append((e, [e]))
    return out


def _skipped_gathering_only(e: dict, raw: dict) -> bool:
    """A clean record whose only content is the gathering task skipped by weekday."""
    if not e.get("ok") or e.get("incomplete") or not raw.get("maaend_collect_skipped"):
        return False
    done = [t for t in (raw.get("tasks_done") or []) if not any(k in t for k in ("自动采集", *_END_WRAPUP))]
    return not done and not raw.get("tasks_failed") and not raw.get("maaend_collect_total")


def retried_notes(entries: list[dict]) -> dict[str, str]:
    """For a failed run whose failed tasks a later run of the same script and
    account finished that same day (or the relay's make-up run did): run_id -> a
    line saying when they were done.
    """
    out: dict[str, str] = {}
    for e in entries:
        if e.get("ok") or not e.get("failed_tasks"):
            continue
        # The relay's own make-up run (makeup.on_record) went through after this
        # failure. MAA's failure names no task a later run could list as done, so
        # the task match below can never see it; the make-up booked it instead.
        if when := (e.get("raw") or {}).get("makeup_ok"):
            out[e["run_id"]] = "、".join(sorted(e["failed_tasks"])) + f"　后来在 {when} 那趟补跑里做成了"
            continue
        want = set(e["failed_tasks"])
        for later in entries:
            if later is e or not later.get("ok"):
                continue
            if (later.get("raw") or {}).get("manual_stop"):
                continue          # stopped by the red button: it did not "get them later"
            if maa_mode(later) != maa_mode(e):
                continue          # a Routine round is no retry of Annihilation (2026-10-26)
            if later.get("script") != e.get("script") or later.get("user") != e.get("user"):
                continue
            if (later.get("started") or "") <= (e.get("started") or ""):
                continue
            done = set((later.get("raw") or {}).get("tasks_done") or [])
            # 「超时」 names no task: a later success of the same script covers it.
            # Every task the record does name still has to be in that success.
            named = {t for t in want if "超时" not in t}
            if (named != want and named <= done) or want <= done:
                # By start time on both clocks, the way the run's own line is labelled.
                st = datetime.fromisoformat(later["started"])
                when = f"{_hm(st)}（东京 {st.astimezone(USER_TZ):%H:%M}）开始的"
                # Said per task: a MaaEnd retry's 「任务完成」 with nothing from the game
                # is not 「做成了」 (the day's title counts it as unverified), and one of
                # the four MaaEnd's own record did not cover is not judged yet
                # (maaend_unjudged); the others the retry did are 做成了. A 「超时」 item
                # goes with the done ones: the later success is what covers it.
                lraw = later.get("raw") or {}
                end = later.get("script") == "MaaEnd"
                bare = named & set(maaend_unverified(lraw)) if end else set()
                unread = named & set(maaend_unjudged(lraw)) if end else set()
                out[e["run_id"]] = texts.retry_outcome(
                    sorted(want), when, [t for t in sorted(want) if t not in bare and t not in unread],
                    sorted(bare), sorted(unread))
                break
    return out


def footnote_tasks(entries: list[dict]) -> list[str]:
    """The names in daily_footnote, in order: the longest list of done tasks among
    the day's MaaEnd runs (failed runs included)."""
    best: list[str] = []
    for e in entries:
        if e.get("script") != "MaaEnd":
            continue
        raw = e.get("raw") or {}
        unverified = {*maaend_unverified(raw), *maaend_unjudged(raw)}
        # The same list the run's row counts (ledger_rows._block_maaend).
        done = [t for t in _maaend_listed(raw) if t not in unverified]
        # The longest list of the day, whether or not that run was marked failed.
        if len(done) > len(best):
            best = done
    return best


def daily_footnote(entries: list[dict]) -> str:
    """The footnote at the end of the notification: the numbered key to Endfield's
    daily list. The number in 「日常 1-16 项完成」 is the index here; returns an
    empty string if there is no list."""
    if best := footnote_tasks(entries):
        return "———————\n日常：" + " ".join(f"{i}.{n}" for i, n in enumerate(best, 1))
    return ""


def _game(script: str) -> str:
    return GAME_ZH.get(str(script), str(script))


def _count_by_script(entries: list) -> list[tuple[str, int]]:
    """[(script, count)] in the order each script first appears."""
    counts: dict[str, int] = {}
    for e in entries:
        counts[str(e.get("script"))] = counts.get(str(e.get("script")), 0) + 1
    return list(counts.items())


_PLAIN_PHRASES = {
    "MAA 在完成任务前中止": "明日方舟这一趟没跑完就停了",
    "MaaEnd 部分任务执行失败": "终末地有任务没做成",
    "MaaEnd 进程超时": "终末地跑得太久，被停掉了",
    "MAA 不接受这份配置": "明日方舟不接受这份设置",
    "MAA 走不到": "明日方舟走不到",
}
_TOOL_WORD = re.compile(r"(?<![A-Za-z])(MaaEnd|MAA|OK-WW|AUTO-MAS)(?![A-Za-z])")
_TOOL_ZH = dict(GAME_ZH, **{"AUTO-MAS": "调度程序"})
_REJECT_STAGE_TAIL = re.compile(r"，关卡 (\S+)$")


def plain_words(text: str) -> str:
    """`text` with the tools' own phrases said plainly and no tool named."""
    for phrase, plain in _PLAIN_PHRASES.items():
        text = text.replace(phrase, plain)
    return _TOOL_WORD.sub(lambda m: _TOOL_ZH.get(m.group(1), m.group(1)), text)


def plain_rejected(rejected: str) -> str:
    """MAA's refusal (texts.maa_config_rejected, ending in the stage) said as "that stage could not be reached"."""
    if m := _REJECT_STAGE_TAIL.search(rejected or ""):
        return f"关卡 {m.group(1)} 当时走不到"
    return "设置不被接受" + (f"（{rejected}）" if rejected else "")


def _minute_of(hhmm: str) -> "int | None":
    try:
        hh, mm = (int(x) for x in str(hhmm).split(":"))
    except ValueError:
        return None
    return hh * 60 + mm


def shift_of(started: "str | datetime", shifts: "list[tuple[str, str]] | None") -> str:
    """The queue a run belongs to: the latest queue time at or before its start,
    within three hours; '' when unknown. shifts: [(name, "HH:MM")]."""
    try:
        at = started if isinstance(started, datetime) else datetime.fromisoformat(str(started))
        at = at.astimezone(SERVER_TZ)
    except (TypeError, ValueError):
        return ""
    best, best_min = "", None
    now_min = at.hour * 60 + at.minute
    for name, hhmm in shifts or []:
        m = _minute_of(hhmm)
        if m is not None and m <= now_min and now_min - m <= 180 and (best_min is None or m > best_min):
            best, best_min = str(name), m
    return best


def _next_shift_minute(started: datetime, shifts: "list[tuple[str, str]] | None") -> "int | None":
    at = started.astimezone(SERVER_TZ)
    now_min = at.hour * 60 + at.minute
    later = [m for _, hhmm in shifts or [] if (m := _minute_of(hhmm)) is not None and m > now_min]
    return min(later) if later else None


def later_success(entries: list[dict], failed: dict,
                  shifts: "list[tuple[str, str]] | None") -> "tuple[str, bool] | None":
    """(HH:MM, by hand) of the run that made `failed` up the same day, or None.

    The first later clean run of the same script and account that starts before
    the next queue (so the next shift's own run is not taken for a make-up); with
    no schedule known, only a run started by hand counts."""
    try:
        after = datetime.fromisoformat(str(failed.get("started")))
    except (TypeError, ValueError):
        return None
    nxt = _next_shift_minute(after, shifts) if shifts else None
    for e in entries:
        if not e.get("ok") or manual_stop(e) or e.get("incomplete"):
            continue
        if e.get("script") != failed.get("script") or e.get("user") != failed.get("user"):
            continue
        if maa_mode(e) != maa_mode(failed):
            continue
        try:
            at = datetime.fromisoformat(str(e.get("started")))
        except (TypeError, ValueError):
            continue
        if at <= after:
            continue
        hand = bool((e.get("raw") or {}).get("hand_started"))
        local = at.astimezone(SERVER_TZ)
        if shifts:
            if nxt is not None and local.hour * 60 + local.minute >= nxt and not hand:
                return None
        elif not hand:
            continue
        return _hm(at), hand
    return None


# What _block_maa says for a run with no stage on record: nothing was fought.
_NOTHING_FARMED = "只做日常（未刷关卡）"


def _bare(e: dict) -> bool:
    """A failed run with nothing to show: no cost, no output, nothing left over, no note."""
    did, cost, out, left, notes = _rows_for(e, datetime.fromisoformat(e["finished"]))
    return (not (cost or out or left or notes) and set(did) <= {_NOTHING_FARMED}
            and not e.get("incomplete"))


def _bare_reason(runs: list[dict]) -> str:
    """Why a group of bare failures did not run, in plain words."""
    for e in runs:
        if rejected := (e.get("raw") or {}).get("maa_config_rejected"):
            return plain_rejected(str(rejected))
        if (e.get("raw") or {}).get("annihilation_no_proxy"):
            return texts.ANNIHILATION_NO_PROXY
        # AUTO-MAS refused the script before starting it (runwatch.check_config_skips).
        if skipped := (e.get("raw") or {}).get("automas_config_skip"):
            return "开跑前检查没过：" + texts.config_skip_why(str(skipped))
    if runs[0].get("script") == "MAA" and all((e.get("raw") or {}).get("fight_count") == 0 for e in runs):
        return "一仗都没打就停了"
    said: dict[str, None] = {}      # a tool's own sentence, said plainly
    tasks: dict[str, None] = {}     # task names
    for e in runs:
        for n in _with_causes([str(x) for x in e.get("failed_tasks") or []],
                              (e.get("raw") or {}).get("maaend_fail_causes")):
            p = plain_words(n)
            (said if p != n else tasks)[p] = None
    parts = list(said) + (["失败于：" + "、".join(tasks)] if tasks else [])
    return "；".join(parts) or "原因没写"


def _bare_failure_groups(entries: list[dict], failed: list[dict],
                         shifts: "list[tuple[str, str]] | None") -> dict[str, dict]:
    """run_id -> its group, for consecutive bare failures of one game in one shift.

    A group: {script, user, shift, runs, reason, later}; `later` is later_success()."""
    failed_ids = {e["run_id"] for e in failed}
    out: dict[str, dict] = {}
    group: "dict | None" = None
    for e in entries:
        if e["run_id"] not in failed_ids or not _bare(e):
            group = None
            continue
        shift = shift_of(e.get("started"), shifts)
        prev_end = datetime.fromisoformat(group["runs"][-1]["finished"]) if group else None
        if group and group["script"] == e.get("script") and group["user"] == e.get("user") \
                and group["shift"] == shift \
                and datetime.fromisoformat(e["started"]) <= prev_end + timedelta(minutes=30):
            group["runs"].append(e)
        else:
            group = {"script": e.get("script"), "user": e.get("user"), "shift": shift, "runs": [e]}
        out[e["run_id"]] = group
    for g in {id(g): g for g in out.values()}.values():
        g["reason"] = _bare_reason(g["runs"])
        g["later"] = later_success(entries, g["runs"][-1], shifts)
    return out


def _bare_line(g: dict) -> str:
    """One line for a group: game, shift, both clocks, tries, why, and the later run that made it up."""
    runs = g["runs"]
    first = datetime.fromisoformat(runs[0]["started"])
    last = datetime.fromisoformat(runs[-1]["finished"])
    tk = lambda d: f"{d.astimezone(USER_TZ):%H:%M}"  # noqa: E731
    span = _hm(first) if _hm(first) == _hm(last) else f"{_hm(first)}–{_hm(last)}"
    tspan = tk(first) if tk(first) == tk(last) else f"{tk(first)}–{tk(last)}"
    tries = f"连试 {len(runs)} 次" if len(runs) > 1 else ""
    shift = f" {g['shift']}" if g["shift"] else ""
    made = ""
    if g["later"]:
        made = f"，{g['later'][0]} " + ("手动补跑成功" if g["later"][1] else "补跑成功")
    return f"❌ {_game(g['script'])}{shift} {span}（东京 {tspan}）{tries}没跑成（{g['reason']}）{made}"


def _no_exit_note(e: dict) -> str:
    idle = (e.get("raw") or {}).get("maaend_no_self_exit")
    tail = f"（空等 {idle} 分钟）" if idle else ""
    return f"{_game(e.get('script'))}任务全完成，但跑完没自己退出{tail}"


def day_unverified_items(entries: list[dict]) -> list[tuple[str, list[str]]]:
    """[(script, [item, ...])]: items of the day the program called done with
    nothing from the game to show for it, after every run of the day (one run's
    evidence covers the same item in another). Runs stopped by hand are left out.

    MaaEnd: listed tasks (maaend_unverified). MAA: annihilation without a
    「剿灭模式 x/y」 line, unless Skland's figure backs a pass MAA skipped
    (annihilation_official). OK-WW: steps the parser marked unverified (UNVERIFIED_STEP).
    The report title counts these (day_unverified); handle._push_unverified sends
    the same items to the group."""
    end_listed: dict[str, None] = {}
    end_ok: set[str] = set()
    anni = anni_ok = False
    ww_unv: dict[str, None] = {}
    ww_ok: set[str] = set()
    for e in entries:
        if manual_stop(e):
            continue
        raw = e.get("raw") or {}
        script = e.get("script")
        if script == "MaaEnd":
            unv = maaend_unverified(raw)
            # Left unjudged this run (MaaFW's log held none of the four, not yet
            # TRAIL_MISS_FAIL runs in a row): neither backs nor lacks evidence.
            unj = set(maaend_unjudged(raw))
            for t in _maaend_listed(raw):
                if t in unj:
                    continue
                end_listed[t] = None
                if t not in unv:
                    end_ok.add(t)
        elif (script == "MAA" and raw.get("annihilation") and e.get("ok")
              and not raw.get("maa_sanity_short")):
            # Only where the report would otherwise say it was fought or already
            # full; a run short of sanity or a failed one is said as such.
            anni = True
            # A pass MAA skipped (no annihilation in the terminal) is backed only by the game
            # server's own figure (handle._annihilation_checked_full), never by MAA's guess.
            anni_ok = anni_ok or bool(raw.get("annihilation_progress") or raw.get("annihilation_official"))
        elif script == "OK-WW":
            for step in raw.get("okww_steps") or []:
                name = step.split("（", 1)[0]
                if UNVERIFIED_STEP in step:
                    ww_unv[name] = None
                else:
                    ww_ok.add(name)
    out = []
    if items := [t for t in end_listed if t not in end_ok]:
        out.append(("MaaEnd", items))
    if anni and not anni_ok:
        out.append(("MAA", ["剿灭"]))
    if items := [t for t in ww_unv if t not in ww_ok]:
        out.append(("OK-WW", items))
    return out


def day_unjudged_items(entries: list[dict]) -> list[str]:
    """MaaEnd tasks of the day left unjudged in some run (maaend_unjudged: MaaFW's log not
    read, fewer than TRAIL_MISS_FAIL runs in a row) that no run of the day backs. Not pushed -
    one unread run is MaaEnd clearing its debug folder or MaaFW rotating its log as often as
    anything - but not green either: the title says 待核 (audit 2026-11-08 C-02; until then
    backed() let such a day read 全绿 ✅ while the run's row said 不算做成)."""
    unj: dict[str, None] = {}
    backed: set[str] = set()
    for e in entries:
        if e.get("script") != "MaaEnd" or manual_stop(e):
            continue
        raw = e.get("raw") or {}
        skip = set(maaend_unjudged(raw))
        unv = set(maaend_unverified(raw))
        for t in _maaend_listed(raw):
            if t in skip:
                unj[t] = None
            elif t not in unv:
                backed.add(t)
    return [t for t in unj if t not in backed]


def day_unverified(entries: list[dict]) -> list[tuple[str, int]]:
    """[(script, n)]: how many day_unverified_items each game has."""
    return [(s, len(items)) for s, items in day_unverified_items(entries)]


def _daily_head(failed: list, undone: list, retried: dict, kinds: dict,
                no_exit: list | None = None, unverified: list | None = None,
                bare: "dict | None" = None, unjudged: "list | None" = None) -> str:
    """The verdict in the report title, worst thing first.

    Failures and unfinished runs are counted per game. Items done with no
    evidence (day_unverified) keep the title off 全绿: they are neither done nor
    failed, and are named as such.
    """
    # A group of bare failures (_bare_failure_groups) is one item: game + shift + not run.
    bare = bare or {}
    parts: list[str] = []
    for g in {id(g): g for g in bare.values()}.values():
        made = f"（{g['later'][0]} 补上了）" if g["later"] else ""
        parts.append(f"{_game(g['script'])}{g['shift']}没跑成{made}")
    parts += [f"{_game(s)}失败 {n} 次"
              for s, n in _count_by_script([e for e in failed if e["run_id"] not in bare])]
    # Settings reset to defaults (outcome.summarize) is its own item, not 「没干完」.
    reset = [e for e in undone if texts.outcome_settings_only(str(e.get("incomplete") or ""))]
    parts += [f"{_game(s)} {n} 项没干完" for s, n in _count_by_script([e for e in undone if e not in reset])]
    parts += [f"{_game(s)} {n} 趟没按你的设置跑" for s, n in _count_by_script(reset)]
    parts += [_no_exit_note(e) for e in (no_exit or [])]
    unv = [f"{_game(s)} {n} 项没证据" for s, n in (unverified or [])]
    if unjudged:
        unv.append(f"{_game('MaaEnd')} {len(unjudged)} 项待核（自己的记录没读到）")
    if parts:
        return "、".join(parts + unv) + " ⚠️"
    if unv:
        return "、".join(unv) + "，不算完成 ❔"
    # Before the retry line on purpose: a run stopped by hand means that
    # script's work is not done today, which outranks "a retry got it".
    if manual := sum(1 for k in kinds.values() if k == "manual"):
        return "其余全绿 ✅（" + ("有一趟" if manual == 1 else f"有 {manual} 趟") + "被手动停止）"
    if retried:
        return "全绿 ✅（有项目重试后成功）"
    if "nosanity" in kinds.values():
        return "全绿 ✅（有一关理智不够没打）"
    if "maintenance" in kinds.values():
        return "维护日跳过，其余全绿 ✅"
    return "全绿 ✅"


def _maaend_restart(e: dict) -> bool:
    """AUTO-MAS's record for a MaaEnd that exited before writing a line: it
    restarted for its own update (「未捕获到日志」). Matched on the text, not the
    `transitional` flag, because older ledger entries do not carry the flag."""
    return "未捕获到日志" in str((e.get("raw") or {}).get("maaend_result") or "")


def _launch_miss(e: dict) -> bool:
    """A record AUTO-MAS wrote for an attempt that never ran (emulator launch miss,
    or MaaEnd restarting for its own update - 「未捕获到日志」)."""
    if _maaend_restart(e):
        return True
    return (not e.get("ok")
            and any("模拟器启动失败" in str(t) for t in (e.get("failed_tasks") or [])))


def test_windows(state_dir) -> list[dict]:
    """The test windows run-one.sh marked (state/test-windows.json); [] when none."""
    if not state_dir:
        return []
    p = Path(state_dir) / "test-windows.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


# = shutdown.OPEN_WINDOW_MAX_H (measured there: the longest run plus its wait).
OPEN_TEST_WINDOW_MAX_H = 3


def split_test(entries: list[dict], windows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(real records, records inside a marked test window).

    A test window is opened on purpose by `run-one.sh <script> --test` and
    closed by `run-one.sh test-off` (state/test-windows.json); nothing is
    inferred from timing. A hand-started run outside a window is real work -
    a rerun after a game update, a run started from the phone - and stays a
    normal row. Test records are kept out of the rows and counted in one line.
    """
    spans = []
    for w in windows or []:
        try:
            since = datetime.fromisoformat(w["since"])
            until = (datetime.fromisoformat(w["until"]) if w.get("until")
                     else since + timedelta(hours=OPEN_TEST_WINDOW_MAX_H))
        except (KeyError, TypeError, ValueError):
            continue
        spans.append((since, until))
    if not spans:
        return list(entries), []
    real, test = [], []
    for e in entries:
        try:
            started = datetime.fromisoformat(e["started"])
        except (KeyError, ValueError):
            real.append(e)
            continue
        inside = any(since <= started and (until is None or started <= until) for since, until in spans)
        (test if inside else real).append(e)
    return real, test


def _incomplete_note(text: str) -> str:
    """The daily row's note for a round the outcome check found wanting.

    summarize() writes one bullet per line; here the bullets are joined with 「；」,
    except right after a 「：」. Settings reset to defaults: the work was done, not
    left undone, and the summary's own head would say 「没按你的设置跑」 a second time.
    """
    reset = texts.outcome_settings_only(text)
    if reset:
        text = text.partition("\n· ")[2]
    why = text.replace("\n· ", "；").replace("\n", "；").replace("：；", "：")
    return ("没按你的设置跑：" if reset else "没干完：") + why


def _annihilation_note(raw: dict) -> str:
    """The daily row's note for an Annihilation pass: fought to the cap, short of it,
    skipped with Skland's figure behind it (handle._annihilation_checked_full), or nothing
    to show."""
    prog = raw.get("annihilation_progress")
    off = raw.get("annihilation_official") or {}
    if prog and prog[0] >= prog[1]:
        return f"本周剿灭已打满（{prog[0]}/{prog[1]}）"
    if prog:
        return f"⚠️ 剿灭只打到 {prog[0]}/{prog[1]}，本周还没满"
    if off:
        return (f"终端里没有剿灭入口，MAA 没打；森空岛官方数据本周剿灭已满"
                f"（{off.get('current')}/{off.get('total')}，{str(off.get('read_at', ''))[11:16]} 读）")
    # No progress line = no proof of anything fought (collector_maa);
    # the gate stays open, so say exactly that.
    return "没读到剿灭进度，本周按没打满算，下一轮再打"


def format_daily(day: str, entries: list[dict], prose: str = "",
                 plan: str = "", tech: "list[str] | None" = None,
                 shifts: "list[tuple[str, str]] | None" = None) -> tuple[str, str]:
    """The one message of the day. Numbers here are copied, never generated.

    Laid out for a narrow phone screen: no nested indentation (full-width
    spaces do not line up across fonts), one fact per short line.

    Rows name the game, not the script. Evidence links, version numbers and
    file names are not in the message (D-1010: the report is for a person, the
    technical parts are ours); one line each goes to `tech` when a list is
    given, for the technical log (report.write_daily_techlog).

    Failed runs of one game in one shift that have nothing to show (no cost, no
    output, nothing left) are one line saying why and whether it was made up
    later; `shifts` [(name, "HH:MM")] names the shift. A finished run that did
    not exit by itself (the relay closed it) is not the user's business: it
    goes to `tech`, not the title or a row.
    """
    tech = tech if tech is not None else []
    # An emulator-launch miss is a one-second attempt with no game in it: no
    # row. Matched on the text as well as the flag, so older records read the
    # same way. A MaaEnd self-update restart gets one information line at the
    # end, not a row and not a failure.
    restarts = sum(1 for e in entries if _maaend_restart(e))
    entries = [e for e in entries if not _launch_miss(e)]
    if not entries:
        return f"📋 {day} 日报", "今天没有任何运行记录。"

    kinds = episode_kinds(entries)
    retried = retried_notes(entries)
    failed = [e for e in entries if not e["ok"]
              and e["run_id"] not in kinds and e["run_id"] not in retried]
    # A run that exited cleanly but did not do its work (incomplete) is not
    # green either.
    undone = [e for e in entries if e["ok"] and e.get("incomplete")
              and kinds.get(e["run_id"]) != "manual"]
    no_exit = [e for e in entries if e["ok"] and "maaend_no_self_exit" in (e.get("raw") or {})
               and not e.get("incomplete")]
    for e in no_exit:
        tech.append(f"{e['run_id']} {_no_exit_note(e)}")
    bare = _bare_failure_groups(entries, failed, shifts)
    title = f"📋 {day[5:]} · {_daily_head(failed, undone, retried, kinds, None, day_unverified(entries), bare, day_unjudged_items(entries))}"

    foot = footnote_tasks(entries)
    lines: list[str] = []
    for e, attempts in _collapse_retries(entries, kinds):
        started = datetime.fromisoformat(e["started"])
        finished = datetime.fromisoformat(attempts[-1]["finished"])
        raw = e.get("raw") or {}
        kind = kinds.get(e["run_id"], "")
        if _skipped_gathering_only(e, raw):
            # AUTO-MAS runs the gathering task as its own record; on a day that is
            # not a gathering day it opens and closes with nothing done: not listed.
            continue
        if e["run_id"] in bare:
            if raw.get("evidence_page"):
                tech.append(f"{e['run_id']} 证据包 {raw['evidence_page']}")
            group = bare[e["run_id"]]
            if group["runs"][0] is e:
                lines += [_bare_line(group), ""]
            continue
        icon = (_KIND_ICON["manual"] if kind == "manual"
                else "⚠️" if e["ok"] and e.get("incomplete") else "✅" if e["ok"]
                else _KIND_ICON.get(kind) or ("↻" if e["run_id"] in retried else "❌"))
        tag = "（剿灭检查）" if raw.get("annihilation") else ""
        tries = f"　连试 {len(attempts)} 次" if len(attempts) > 1 else ""
        lines.append(icon + f" {_game(e['script'])}{tag}　"
                     + _span(started, finished, e.get('duration_known', True)) + tries)
        # A run that did not go through: its evidence bundle link goes to the
        # technical log (the failure alarm carries it too), not into a row.
        if not e["ok"] and not kind and raw.get("evidence_page"):
            tech.append(f"{e['run_id']} 证据包 {raw['evidence_page']}")
        if kind:
            note = _KIND_NOTE[kind]
            if kind == "manual" and not _ran_later(e, entries):
                # A script the red button stopped is not re-dispatched
                # automatically that day (gameupdate.stopped_today).
                note += "；已停，未补"
            if kind == "nosanity":
                sh = raw.get("maa_sanity_short") or {}
                note = f"理智 {sh.get('have')} 不够这关要的 {sh.get('cost')}，没打，不算失败"
            if kind == "update" and raw.get("maaend_update_restart"):
                note = "终末地装了新版后自己重启，用掉一次重试，不算失败"
                tech.append(f"{e['run_id']} MaaEnd 装新版 {raw['maaend_update_restart']} 后自己重启")
            if kind == "update" and raw.get("okww_restart_dialog"):
                # OK-WW says 「游戏更新成功」 for any 「游戏即将重启」 dialog. The
                # collector looked at the game folder; the note says what it found
                # in one of three definite forms. The file names go to the technical log.
                files = "、".join(raw.get("okww_client_files") or [])
                if files:
                    tech.append(f"{e['run_id']} OK-WW 游戏更新换了的文件：{files}")
                note = {
                    "patch": "游戏更新成功（更新了客户端文件），重启后重跑，不算失败",
                    "anticheat": "游戏更新成功（只更新了反作弊组件），重启后重跑，不算失败",
                    "none": "游戏弹了「即将重启」但客户端文件没有变，重启后重跑，不算失败",
                }.get(str(raw.get("okww_client_change")), "游戏弹了「即将重启」，重启后重跑；客户端有没有换文件没查到，不算失败")
            lines += [_row("备注", [note]), ""]
            continue
        if not e["ok"]:
            # A failed run still shows what it did: the rows, with the failure
            # (or the retry that fixed it) as the first note.
            did, cost, out, left, notes = _rows_for(e, finished, foot)
            notes.insert(0, retried.get(e["run_id"])
                         or _fmt_failed(e.get("failed_tasks") or [],
                                        causes=(e.get("raw") or {}).get("maaend_fail_causes")))
            if not (did or cost or out or left):
                lines += [_row("备注", notes), ""]
                continue
            lines += [_row(label, v) for label, v in
                      zip(_LABELS, (did, cost, out, left, notes), strict=True)]
            lines.append("")
            continue
        if raw.get("annihilation"):
            lines += [_row("备注", [_annihilation_note(raw)]), ""]
            continue
        did, cost, out, left, notes = _rows_for(e, finished, foot)
        if e.get("incomplete"):
            notes.insert(0, _incomplete_note(str(e["incomplete"])))
        if notes and not (did or cost or out or left):
            # Notes only: one 备注 row, not four 「—」 rows above it.
            lines += [_row("备注", notes), ""]
            continue
        lines += [_row(label, v) for label, v in
                  zip(_LABELS, (did, cost, out, left, notes), strict=True)]
        lines.append("")

    if restarts:
        lines += [f"ℹ️ 终末地装新版后自己重启 {restarts} 次，未计失败", ""]
    if prose:
        lines += ["———————", prose, ""]
    # Tomorrow's plan goes last, while there is still time to change it.
    if plan:
        lines += ["———————", plan]
    return title, "\n".join(lines).rstrip()


def format_missing(what: str, expected_at: datetime, detail: str = "") -> tuple[str, str]:
    """Alert for something that should have happened and did not."""
    title = texts.missing(what)
    body = [f"预计 {both_clocks(expected_at)} 应发生，至今没有。"]
    if detail:
        body += ["", detail]
    return title, "\n".join(body)


# Report text lives in ledger_rows / ledger_report; callers and tests still say
# ledger.<name>, so every name defined there is importable from here too.


# This module's public names plus every name re-exported from the modules above
# (callers and tests say ledger.<name>); pyflakes and ruff count a listed name as used.

log = logging.getLogger("ark.core")


def _is_iso(v) -> bool:
    try:
        datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return False
    return True


# The torn lines already said per ledger file (path -> torn lines): read_ledger
# runs every tick and on every phone-state publish, so a torn line is said once,
# not on every read. Reset when the file no longer has it.
_LEDGER_TORN_SAID: dict[str, frozenset] = {}
# The last non-numeric interim marker said, {day: raw} with at most one entry:
# interim_covered is asked every tick. Cleared once that day's marker reads as a
# count again.
_INTERIM_SAID: dict[str, str] = {}

_LEDGER_LOCK = threading.RLock()


_UNDONE_HEAD = re.compile(r"这一轮有 (\d+) 项没干成")


def strip_incomplete_items(why: str, keyword: str) -> str:
    """outcome.summarize's paragraph less the 「· …」 items naming `keyword`; "" when no
    item is left. The 「有 N 项没干成」 head is recounted, or dropped with its items."""
    lines = why.splitlines()
    kept = [ln for ln in lines if not (ln.startswith("· ") and keyword in ln)]
    if len(kept) == len(lines):
        return why
    if not any(ln.startswith("· ") for ln in kept):
        return ""
    out: list[str] = []
    i = 0
    while i < len(kept):
        ln = kept[i]
        if m := _UNDONE_HEAD.search(ln):
            j = i + 1
            while j < len(kept) and kept[j].startswith("· "):
                j += 1
            if j == i + 1:
                # No undone item left under this head: the settings head after it, if
                # any, said 「另外…」 and now opens the paragraph.
                who = ln[:m.start()].strip()
                if j < len(kept) and kept[j].startswith("另外"):
                    kept[j] = f"{who} {kept[j][len('另外'):]}"
                i = j
                continue
            out.append(ln[:m.start()] + f"这一轮有 {j - i - 1} 项没干成" + ln[m.end():])
            out += kept[i + 1:j]
            i = j
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)

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
        # The day's markers and the alert queue live in state.json (docs/STATE-MODEL.md).
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
            # A record superseded by the next attempt (collector._TRANSITIONAL).
            "transitional": rec.transitional,
            # AUTO-MAS's own output plus what the parsers added, verbatim.
            "raw": rec.raw,
            "sanity": rec.sanity,
            "sanity_full_at": rec.sanity_full_at,
            "drops": rec.drops,
            "recruits": rec.recruits,
        }
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        with _LEDGER_LOCK:
            # One line per (day, run_id): a record handled again (a retry after
            # handling raised past this point, or the post-deploy retry of a
            # given-up record) keeps the line already there, with any marks written
            # onto it since, and is not scored a second time.
            if rec.run_id in self._ledger_run_ids(day):
                log.info("记录 %s 已在 %s 的账上，不重记", rec.run_id, day)
                return
            with self.ledger_path(day).open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # Score the current code version (scoreboard.py). Every finished run
        # passes through this line, so the daily report's text cannot change
        # the score.
        try:
            # A run the red button cut short says nothing about the code version.
            if not (rec.raw or {}).get("manual_stop"):
                kw = {}
                # Judge a test run by when it started (scoreboard.record takes
                # `started` from relay-report on; older versions judge by now).
                if "started" in inspect.signature(scoreboard.record).parameters:
                    kw["started"] = rec.started
                scoreboard.record(self.store, str(self.store.get("versions", "code") or ""),
                                  rec.ok, rec.transitional, **kw)
        except Exception:
            # The scoreboard must never take the bookkeeping down with it.
            log.warning("记分牌没记上", exc_info=True)

    def _ledger_run_ids(self, day: str) -> set:
        """Every run_id on the day's ledger, read raw: a line read_ledger would skip
        (missing key, bad time) still holds its run's place. Torn lines hold none."""
        p = self.ledger_path(day)
        if not p.exists():
            return set()
        ids = set()
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and "run_id" in entry:
                ids.add(entry["run_id"])
        return ids

    def mark_incomplete(self, day: str, run_id: str, why: str) -> bool:
        """Write a failed outcome check back onto the day's ledger line.

        The record stays `ok` (AUTO-MAS did see the process exit normally, and
        the retry logic keys off that); `incomplete` is a second, independent
        fact about the same run: it finished, and it did not do the work. The
        daily report reads it.
        """
        return self._rewrite_entry(day, run_id, lambda e: e.__setitem__("incomplete", why))

    def clear_incomplete_items(self, day: str, run_id: str, keyword: str) -> bool:
        """Drop from the line's `incomplete` only the undone items naming `keyword`
        (strip_incomplete_items); the field empties only when no undone item is left.
        """
        def put(e: dict) -> None:
            if why := e.get("incomplete"):
                e["incomplete"] = strip_incomplete_items(str(why), keyword)
        return self._rewrite_entry(day, run_id, put)

    def mark_raw(self, day: str, run_id: str, key: str, value) -> bool:
        """Set one raw field on the day's ledger line (the line is written first)."""
        def put(e: dict) -> None:
            raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
            raw[key] = value
            e["raw"] = raw
        return self._rewrite_entry(day, run_id, put)

    def mark_evidence(self, day: str, run_id: str, page: str) -> bool:
        """Write the evidence link back onto the day's ledger line.

        handle.py appends the run before its bundle is shipped (so a crash later
        cannot lose it); this puts the link into the line already on disk, where
        the daily report's 证据包 row reads it.
        """
        def put(e: dict) -> None:
            raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
            raw["evidence_page"] = page
            e["raw"] = raw
        return self._rewrite_entry(day, run_id, put)

    def _rewrite_entry(self, day: str, run_id: str, edit) -> bool:
        p = self.ledger_path(day)
        with _LEDGER_LOCK:
            if not p.exists():
                return False
            lines = p.read_text(encoding="utf-8").splitlines()
            hit = False
            for i, ln in enumerate(lines):
                try:
                    entry = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("run_id") == run_id:
                    edit(entry)
                    lines[i] = json.dumps(entry, ensure_ascii=False)
                    hit = True
            if hit:
                atomic_write_text(p, "\n".join(lines) + "\n")
            return hit

    # What every consumer of a ledger entry assumes is present; checked once here.
    # A missing key or a bad time would stop the daily report, and shutdown
    # waits for that report.
    _LEDGER_REQUIRED = ("run_id", "script", "started", "finished", "ok")

    def read_ledger(self, day: str) -> list[dict]:
        p = self.ledger_path(day)
        if not p.exists():
            return []
        out = []
        bad_lines: list[tuple[str, str]] = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                entry = json.loads(ln)
            except json.JSONDecodeError:
                bad_lines.append((ln, "账目里有一行不是完整的 JSON，已跳过: %.120s"))
                continue  # tolerate one torn line rather than lose the day
            if not isinstance(entry, dict):
                continue
            if missing := [k for k in self._LEDGER_REQUIRED if k not in entry]:
                # A line can be valid JSON yet incomplete (power cut mid-write).
                bad_lines.append((ln, f"账目里有一条残缺记录（缺 {'、'.join(missing)}），已跳过: %.120s"))
                continue
            # started/finished go through fromisoformat in the daily report and
            # the shutdown decision; an unparseable one is skipped like a missing key.
            bad = [k for k in ("started", "finished")
                   if not _is_iso(entry.get(k))]
            if bad:
                bad_lines.append((ln, f"账目里有一条时间不合法的记录（{'、'.join(bad)}），已跳过: %.120s"))
                continue
            out.append(entry)
        said = _LEDGER_TORN_SAID.get(str(p), frozenset())
        for line_text, fmt in bad_lines:
            # one fault, one push: one broken ledger line by line_text
            if line_text not in said:
                log.warning(fmt, line_text)
        if bad_lines:
            _LEDGER_TORN_SAID[str(p)] = frozenset(line_text for line_text, _ in bad_lines)
        else:
            _LEDGER_TORN_SAID.pop(str(p), None)
        return out

    # ---------- undelivered alerts survive a restart ----------
    # Anything not yet delivered is kept on disk and removed only once a channel
    # has accepted it.

    def save_pending(self, payload: dict) -> None:
        self.store.set("queues", "pending", dict(payload))

    def load_pending(self, *, fresh: bool = False) -> dict:
        data = self.store.get("queues", "pending", fresh=fresh)
        return dict(data) if isinstance(data, dict) else {}

    def report_sent(self, day: str) -> bool:
        return self.store.get("marks", f"report:{day}") is not None

    def interim_sent(self, day: str) -> bool:
        return self.store.get("marks", f"interim:{day}") is not None

    def interim_covered(self, day: str) -> int:
        """How many ledger entries the day's interim reports already cover.

        A count, not a flag: a make-up run later the same day (entries past the
        covered mark) gets a fresh interim report.
        """
        raw = self.store.get("marks", f"interim:{day}")
        try:
            got = 0 if raw is None else int(str(raw).strip())
        except (TypeError, ValueError):
            # A non-numeric marker: treated as sent with count unknown (10**6),
            # which suppresses every further interim that day; said once.
            if _INTERIM_SAID.get(day) != str(raw):
                log.warning("临时日报标记 interim:%s 不是条数（%.40r），按已发处理，今天不再推临时日报",
                            day, raw)
                _INTERIM_SAID.clear()
                _INTERIM_SAID[day] = str(raw)
            return 10**6
        _INTERIM_SAID.pop(day, None)
        return got

    def mark_interim_sent(self, day: str, covered: int = 1) -> None:
        # store.set writes atomically; an empty marker would read as "sent,
        # count unknown" (interim_covered).
        self.store.set("marks", f"interim:{day}", str(covered))

    def mark_report_sent(self, day: str) -> None:
        self.store.set("marks", f"report:{day}",
                       datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"))

    # Headings of the day's technical sections already in the technical log
    # (report.write_daily_techlog), so a retried send does not write them twice.
    def techlog_written(self, day: str) -> set[str]:
        got = self.store.get("marks", f"techlog:{day}")
        return {str(h) for h in got} if isinstance(got, list) else set()

    def mark_techlog_written(self, day: str, headings: "set[str]") -> None:
        self.store.set("marks", f"techlog:{day}", sorted(headings))

    # Banner heads-up marks, keyed by "game + start time" (two games can start
    # banners on the same day).
    def banner_announced(self, key: str) -> bool:
        return self.store.get("marks", f"banner:{key}") is not None

    def mark_banner_announced(self, key: str) -> None:
        self.store.set("marks", f"banner:{key}",
                       datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"))


from ark_relay.features import report as scoreboard  # noqa: E402

__all__ = ['State', 'UNVERIFIED', 'UNVERIFIED_STEP', '_END_FARM_NOTE_SKIP', '_FULL_AT', '_KIND_ICON', '_KIND_NOTE', '_LABELS', '_block', '_block_maa', '_block_maaend', '_block_okww', '_claim_block', '_collapse_retries', '_count_by_script', '_daily_head', '_fmt_failed', '_fmt_items', '_game', '_hm', '_launch_miss', '_maaend_listed', '_maaend_restart', '_no_exit_note', '_ran_later', '_row', '_rows_for', '_sanity_full', '_skipped_gathering_only', '_span', '_with_causes', 'daily_footnote', 'day_unverified', 'day_unverified_items', 'episode_kinds', 'format_daily', 'format_failure', 'format_missing', 'log', 'maaend_unverified', 'maa_mode', 'manual_stop', 'retried_notes', 'split_test']
