"""One ledger entry as report rows (做了 / 消耗 / 产出 / 剩余 / 备注), one builder per tool.

Also the rules for which MaaEnd steps count as done without evidence
(`maaend_unverified`), which the daily report and the alarm text share.
"""
from __future__ import annotations

import re
from datetime import datetime

from ark_relay.core.config import SERVER_TZ, USER_TZ


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
    from ark_relay.features.verify.collector_maaend import CLAIM_UNCONFIRMED  # noqa: PLC0415
    causes = {k: v for k, v in (causes or {}).items() if v != CLAIM_UNCONFIRMED}
    return [f"{n}（{causes[n]}）" if n in causes else n for n in names]


# The date and time in MAA's sentence, e.g. "理智将在 2026-08-17 05:33 回满。"
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
        if mm := raw.get("okww_stamina_mismatch"):
            s += f"（体力读数对不上：脚本读成 {mm[0]}，结算页写剩余 {mm[1]}，按结算页）"
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


def _block_maaend(e: dict, raw: dict, finished: datetime) -> tuple[list[str], ...]:
    """The five rows for one Endfield (MaaEnd) run: 做了 / 消耗 / 产出 / 剩余 / 备注.

    Sanity has a cap and can overflow (warned), and a long daily list is
    collapsed into 「日常 1-N 项完成」 with the names in the footnote
    (ledger_report.daily_footnote).
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
    done = _maaend_listed(raw)
    # Every task MaaEnd skipped by its weekday schedule is in
    # raw["maaend_tasks_skipped"] and already out of tasks_done
    # (collector_maaend._schedule_skipped); it is named in the notes below.
    skipped = raw.get("maaend_tasks_skipped") or {}
    # Done only with evidence from the game; the rest are named as unverified.
    unverified = maaend_unverified(raw)
    done = [t for t in done if t not in unverified]
    failed = raw.get("tasks_failed") or []
    if done or failed or unverified:
        # More than three: 「日常 1-N 项完成」, names in the footnote
        # (daily_footnote). Three or fewer are named here.
        if not done:
            n = "日常 0 项"
        elif len(done) <= 3:
            n = "做了 " + "、".join(done)
        else:
            n = f"日常 1-{len(done)} 项完成"
        # Only when AUTO-MAS still called the run a success: on a run marked
        # failed the renderer already names the failure.
        if failed and e.get("ok"):
            n += "；失败 " + "、".join(_with_causes(failed, raw.get("maaend_fail_causes")))
        notes.append(n)
        if unverified:
            notes.append(UNVERIFIED + "：" + "、".join(unverified))
    if total := raw.get("maaend_collect_total"):
        # Walked/total from the run's own 「路线N：…」 lines (a narrowed retry
        # round reads 「自动采集 2/2 条走通」).
        n = f"自动采集 {raw.get('maaend_collect_done', 0)}/{total} 条走通"
        if bad := raw.get("maaend_collect_failed"):
            n += "，没走通：" + "、".join(bad)
        notes.append(n)
    elif routes := raw.get("maaend_collect_routes"):
        notes.append(f"自动采集 {routes} 条路线")
    elif wd := raw.get("maaend_collect_skipped"):
        notes.append(f"自动采集 今天{wd}不是采集日（排班只有周一、周四），按排班跳过，没走路线")
    # 自动采集 has its own sentence above; the rest are said here, by name.
    if other := [(n, wd) for n, wd in skipped.items() if "自动采集" not in n]:
        notes.append("按排班跳过、没有做：" + "、".join(f"{n}（今天{wd}）" for n, wd in other))

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


# Farming is already stated in 做了, so it is not repeated in the daily list, and
# wrap-up steps (「结束进程」, and 「停止任务」: MaaEnd stopping its own tasker)
# are not in-game tasks.
_END_FARM_NOTE_SKIP = ("基质刷取", "协议空间", "结束进程", "停止任务")


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
    """Listed MaaEnd tasks with no game evidence: no line of their own in the log
    (collector_maaend.task_evidence) and no task-end picture (raw['tasks_shot'],
    handle._mark_task_shots). A record without the evidence table at all (a log
    that could not be read again) has none for any task."""
    ev = raw.get("tasks_evidence") or {}
    shot = set(raw.get("tasks_shot") or [])
    return [t for t in _maaend_listed(raw) if not ev.get(t) and t not in shot]
