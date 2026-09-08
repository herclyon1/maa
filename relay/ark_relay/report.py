"""Daily report and interim look: when to send, and what to send.

Split out of engine.py (2026-09-06, moved verbatim).
"""
from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timedelta

from . import texts
from . import banners, collector, core, plan, scoreboard, summary
from .config import SERVER_TZ

log = logging.getLogger("ark.report")




def _fill_single_run_sanity(entries: list[dict]) -> None:
    """For an Endfield record with only one run, the sanity spent has to be
    filled in from the previous entry's remaining sanity that same day.

    来龙去脉见 docs/CODE-HISTORY.md「report.py:_fill_single_run_sanity」。
    """
    prev_left: dict[str, int] = {}
    for e in entries:
        raw = e.get("raw") or {}
        script = str(e.get("script") or "")
        left = e.get("sanity")
        if raw.get("maaend_sanity_runs_only") and not raw.get("maaend_sanity_spent"):
            before = prev_left.get(script)
            if before is not None and isinstance(left, int) and before > left:
                raw["maaend_sanity_spent"] = before - left
                e["raw"] = raw
        if isinstance(left, int):
            prev_left[script] = left


def _report_cutoff(eng, now: datetime) -> datetime:
    """The time of day after which the report is due.

    Taken from AUTO-MAS's own last scheduled queue time whenever that can
    be read, so moving a queue inside AUTO-MAS moves the report with it.
    ARK_LAST_RUN_AFTER is only the fallback.

    Both this method's callers used to compute the cutoff themselves, from
    two different starting points - one of them from the *finish time of
    the last run* rather than from the clock. That made the report
    undeliverable whenever the evening queue finished earlier than the
    configured hour: the condition could never become true, so the report
    was never sent, and because shutdown waits for the report, the machine
    never powered off either.
    """
    times = sorted(t for q in plan.schedule(eng.cfg.automas_dir)
                   for t in q.get("times", []))
    hhmm = times[-1] if times else eng.cfg.last_run_after
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except ValueError:
        hh, mm = 21, 30
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def _maybe_interim_report(eng, now: datetime | None = None) -> None:
    """Report once the day's earlier queues are done, hours before the
    daily summary is due.

    This used to live inside the shutdown path, which coupled two unrelated
    things: turning shutdown off for an afternoon of maintenance also
    silently turned off the morning report, and the operator was left with
    a machine that had run and said nothing. What decides this is "the
    morning queue finished", not "I am about to power off".
    """
    if not eng.cfg.interim_report:
        return
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    day = now.strftime("%Y-%m-%d")
    if eng.state.report_sent(day):
        return
    if now >= eng._report_cutoff(now):
        return          # the real daily report is due; let it do the talking
    entries = eng.state.read_ledger(day)
    if not entries or eng._scripts_running():
        return
    if eng._unfinished_queues(now, entries):
        return
    # Once per finished daytime ROUND, not once per day: a make-up run
    # adds entries past the covered mark and deserves its own interim
    # (operator order 2026-08-20 - the silent afternoon rerun taught us).
    covered = eng.state.interim_covered(day)
    if len(entries) <= covered:
        return
    # Judge manual-vs-scheduled from this round's new entries only; the
    # earlier rounds have each already been reported on their own.
    label = "手动执行" if eng._round_is_manual(entries[covered:]) else "临时查看"
    if eng.send_daily_now(mark=False, label=label):
        eng.state.mark_interim_sent(day, len(entries))
        log.info("🔎 %s 已推送「%s」（覆盖 %d 条记录）", day, label, len(entries))


def _maybe_daily_report(eng, now: datetime | None = None) -> None:
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    day = now.strftime("%Y-%m-%d")
    # Yesterday first: every check below is written against "today", so if
    # yesterday's report never went out, past midnight there is no other chance
    # to make it up. It has to be settled here.
    # 来龙去脉见 docs/CODE-HISTORY.md「report.py:_maybe_daily_report」
    yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if not eng.state.report_sent(yday) and (
            y_entries := eng.state.read_ledger(yday)):
        title, body = eng._compose_daily(yday, y_entries)
        if errors := eng.notifier.send(title + "（补发）", body):
            log.error("昨日日报补发失败，稍后重试: %s", "；".join(errors))
        else:
            eng.state.mark_report_sent(yday)
            log.info("📋 %s 日报已补发（%d 条记录）", yday, len(y_entries))
    if eng.state.report_sent(day):
        return
    entries = eng.state.read_ledger(day)
    if not entries:
        return
    # Due once the clock is past the day's last queue and nothing is still
    # working - never based on when a run happened to finish.
    if now < eng._report_cutoff(now) or eng._scripts_running():
        return
    # The cutoff *is* the last queue's start time, so this check first comes
    # true in the seconds after that queue fires - while its game is still
    # launching and no process exists yet. With earlier runs already in the
    # ledger the report looked complete, so it went out describing only the
    # morning and marked the day done; the evening run would then never be
    # reported at all. Same guard the shutdown path already uses.
    if unfinished := eng._unfinished_queues(now, eng.state.read_ledger(day)):
        log.info("日报再等等：%s", "；".join(unfinished))
        return

    title, body = eng._compose_daily(day, entries)
    errors = eng.notifier.send(title, body)
    if errors:
        # Do not mark it sent - retry on the next tick rather than lose the day.
        log.error("日报推送失败，稍后重试: %s", "；".join(errors))
        return
    eng.state.mark_report_sent(day)
    log.info("📋 %s 日报已推送（%d 条记录）", day, len(entries))
    _attach_tacet_shots(eng, day)


def _compose_daily(eng, day: str, entries: list[dict]) -> tuple[str, str]:
    """Model writes the report from the raw records; code only decides the
    headline (green / how many failed), which must never be a guess."""
    # `raw` in the ledger is whatever the parser produced at bookkeeping time;
    # after a parser upgrade, older entries are missing fields. Recompute from
    # the history logs before reporting (the user pointed out on 2026-09-02
    # that the Wuthering Waves section was all stale bookkeeping).
    entries = [collector.refresh_raw(e, eng.cfg.history_dir) for e in entries]
    _fill_single_run_sanity(entries)
    tomorrow = plan.next_plan(eng.cfg.automas_dir)
    failed = [e for e in entries if not e["ok"]]
    head = "全绿 ✅" if not failed else f"{len(failed)} 项出错 ⚠️"
    title = f"📋 {day[5:]} · {head}"
    # The event countdown rides on every daily report (the user asked for this
    # on 2026-08-20): he wants to glance at the days remaining every day, not
    # be reminded only on the last one.
    # 来龙去脉见 docs/CODE-HISTORY.md「report.py:_compose_daily」
    act = plan.activity_countdown(eng.cfg.automas_dir)
    # The banner countdown works the same way and goes last (the user asked on
    # 2026-08-30 for it at the end of the notification). Each of the three
    # games is wrapped in its own try, so one dead source does not take the
    # others down; if all of them die, only this section is missing.
    try:
        bnow = datetime.now(tz=SERVER_TZ).replace(tzinfo=None)
        failed: list[str] = []
        rows, nxt = banners.collect(bnow, skland_token=eng.cfg.skland_token, failed=failed)
        pool = banners.render(rows, bnow, nxt, banners.previews(bnow, rows, banners.version_ends(bnow, rows)))
        eng._announce_banners(bnow, nxt)
        # A source that could not be read must say so in the report itself.
        # Otherwise a missing game reads as "nothing running there", and the day
        # a banner opens is exactly the day he finds out the token had expired.
        if failed:
            pool = (pool + "\n" if pool else "") + "⚠️ 卡池没取到：" + "、".join(failed) + "（不是没有卡池，是没读到）"
    except Exception:
        log.warning("卡池那一段整体失败", exc_info=True)
        pool = "⚠️ 卡池那一段整体没取到（不是没有卡池，是没读到）"
    # How this version has been doing is counted by the relay itself and stuck
    # at the end of every daily report. The user, 2026-09-06:
    # 「我说『修好了』而它写『失败 1 趟』，谎话当场现形。」
    # ("I say 'fixed it' while it writes '1 failed run' and the lie is exposed
    # on the spot.") So it must come after anything I write, and I must not be
    # able to touch its numbers -- they come from versions/scoreboard, recorded
    # by append_ledger after every run.
    score = scoreboard.line(eng.state.store, str(eng.state.store.get("versions", "code") or ""))
    tail = "".join(f"\n\n{x}" for x in (act, pool, score) if x)
    written = summary.daily_report(eng.cfg, entries, tomorrow)
    if written:
        log.info("📋 日报由模型撰写（%d 条记录）", len(entries))
        foot = core.daily_footnote(entries)
        return title, written + tail + (f"\n\n{foot}" if foot else "")
    # Settled by the user on 2026-08-30: having the model write the report is
    # an **abandoned plan** (too expensive); the structured template is the
    # final form and is good enough for now. So reaching this point is not a
    # fault, it is the normal path -- logging WARNING here used to make it look
    # broken and left a fake injury in the log every single day.
    log.info("日报用结构化模板（模型撰写已废弃，这是正常路径）")
    title2, body = core.format_daily(day, entries, "", tomorrow)
    # The Endfield daily list goes at the very end as a footnote (user, 2026-09-02)
    foot = core.daily_footnote(entries)
    return title2, body + tail + (f"\n\n{foot}" if foot else "")


def _announce_banners(eng, now: datetime,
                      nxt: "dict[str, tuple[datetime, str]]") -> None:
    """Say so in the WeCom group the day before a banner opens.

    来龙去脉见 docs/CODE-HISTORY.md「report.py:_announce_banners」。
    """
    due = banners.opening_tomorrow(now, nxt)
    fresh = [d for d in due
             if not eng.state.banner_announced(f"{d[0]}-{d[1]:%Y%m%d%H%M}")]
    if not fresh:
        return
    title, body = banners.group_notice(fresh)
    if not title:
        return
    if eng.notifier.send_group(title, body):
        return                      # Not delivered, so do not mark it; retry next round
    for game, when, _ in fresh:
        eng.state.mark_banner_announced(f"{game}-{when:%Y%m%d%H%M}")
    log.info("📣 已在群里播报明天开的卡池：%s",
             "、".join(g for g, _, _ in fresh))


def send_daily_now(eng, mark: bool = True, label: str = "临时查看") -> bool:
    """Force today's report out (used by the `report` command and tests).

    `mark=False` sends an interim look at the day so far without consuming
    the day's report - the evening summary still goes out on schedule.
    Marking it would silently cancel that summary, which is the opposite of
    what someone asking for a mid-day check wants.

    `label` distinguishes the two non-consuming kinds: 「临时查看」for a
    scheduled daytime round, 「手动执行」for a round someone triggered by
    hand. See docs/NOTIFICATIONS.md - that distinction is required, not
    cosmetic: the operator has to be able to tell why a summary appeared.
    """
    now = datetime.now(tz=SERVER_TZ)
    day = now.strftime("%Y-%m-%d")
    entries = eng.state.read_ledger(day)
    title, body = eng._compose_daily(day, entries)
    if not mark:
        title = title.replace("📋", "🔎", 1) + f"（{label}）"
    errors = eng.notifier.send(title, body)
    if errors:
        log.error("日报推送失败: %s", "；".join(errors))
        return False
    if mark:
        eng.state.mark_report_sent(day)
    _attach_tacet_shots(eng, day)
    return True


def _tacet_shots_dir(eng) -> "Path | None":
    root = getattr(eng.cfg, "okww_dir", None)
    if not root:
        return None
    d = Path(root) / "data" / "apps" / "ok-ww" / "working" / "screenshots"
    return d if d.is_dir() else None


def _tacet_caption(eng, day: str = "") -> str:
    """The caption line: 「实际刷了第 N 个：名字，掉 套装」.

    The index comes from **the teleport target OK-WW itself reported**
    (okww_info in the ledger), not from the "which one do we want" written in
    the config -- what the user was uneasy about on 2026-09-07 is exactly that
    the two can differ. When they disagree, say both, so it is visible at a
    glance. Only when the actual value cannot be read does it fall back to the
    configured one, and then it says outright that it is the configured value.
    """
    from . import weeklyboss, wuwa_tacet  # noqa: PLC0415
    want = None
    try:
        daily = weeklyboss._read(weeklyboss._file(eng.cfg.automas_dir, "DailyTask.json"))
        want = int((daily or {}).get("Which Tacet Suppression to Farm") or 0) or None
    except Exception:  # noqa: BLE001
        want = None
    got = None
    try:
        for e in reversed(eng.state.read_ledger(day or "")):
            v = (e.get("raw") or {}).get("okww_info") or {}
            if "Teleport to Tacet Suppression" in v:
                got = int(v["Teleport to Tacet Suppression"]) + 1   # Upstream counts from 0
                break
    except Exception:  # noqa: BLE001
        got = None
    if got is not None:
        line = f"实际刷了第 {got} 个：{wuwa_tacet.label(got)}，掉 {wuwa_tacet.reward(got)}"
        if want is not None and want != got:
            line += f"。注意：设置里写的是第 {want} 个（{wuwa_tacet.label(want)}），两者不一样"
        return line
    if want is not None:
        return f"设置里写的是第 {want} 个：{wuwa_tacet.label(want)}，掉 {wuwa_tacet.reward(want)}（实际序号没读到）"
    return "无音区序号没读到，设置和实际都没拿到"


def _attach_tacet_shots(eng, day: str) -> list[str]:
    """After the daily report goes out, send the day's Tacet Suppression
    settlement screen (captured by the OK-WW tacetshot patch) behind it via the
    group bot.

    The user, 2026-09-07: 「我想确认一下是不是刷的是我想要的无音区种类，因为我不放心。
    刷完之后能不能贴一张截图在日报通知里面？」("I want to confirm it is farming
    the kind of Tacet Suppression I want, because I am not comfortable. Can you
    put a screenshot in the daily report notification once it finishes?")
    Each image is sent only once (the file name is recorded in the state dir).
    Returns the file names sent, for tests.
    """
    shots = _tacet_shots_dir(eng)
    if shots is None:
        return []
    sent_file = Path(eng.state.dir) / f"tacet-shots-{day}.sent"
    try:
        already = set(sent_file.read_text(encoding="utf-8").split())
    except OSError:
        already = set()
    # Send exactly one: the settlement screen of the last round
    # (user, 2026-09-07: 「不要发没有用的截图，我只需要刷完之后产出的那一张就行」
    # -- "do not send useless screenshots, I only need the one produced after
    # the farming finishes"). If several were captured the same day, send the
    # newest.
    cands = [p for p in shots.glob("*_tacet_drops_original.png")
             if datetime.fromtimestamp(p.stat().st_mtime, tz=SERVER_TZ).strftime("%Y-%m-%d") == day
             and p.name not in already]
    if not cands:
        return []
    picks = [("tacet_drops", max(cands, key=lambda p: p.stat().st_mtime))]
    eng.notifier.send_group(texts.TACET_DROPS, f"{_tacet_caption(eng, day)}。下面是刷完的结算页。")
    done = []
    for _tag, p in picks:
        if not eng.notifier.send_group_image(p):
            done.append(p.name)
    if done:
        # Mark the earlier captures as handled too: the next report only sends
        # ones captured after this point.
        try:
            sent_file.write_text("\n".join(sorted(already | {p.name for p in cands})), encoding="utf-8")
        except OSError:
            log.warning("无音区截图的记账写不下来", exc_info=True)
        log.info("🖼️ 无音区截图已发 %d 张：%s", len(done), "、".join(done))
    return done
