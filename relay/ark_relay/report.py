"""日报与临时查看：什么时候发、发什么。

从 engine.py 拆出来（2026-09-06，只搬不改）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timedelta

from . import banners, collector, core, plan, summary
from .config import SERVER_TZ

log = logging.getLogger("ark.report")




def _fill_single_run_sanity(entries: list[dict]) -> None:
    """只刷了一趟的终末地记录，消耗要拿当天上一条的余量来补。

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
    # Yesterday first. Everything below keys off "today", so a report that
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
    # 账本里的 raw 是记账那一刻的解析结果；解析器升级后旧条目会缺字段。
    # 出报告前按 history 日志重算一遍（用户 2026-09-02 指出鸣潮那块全是老账）。
    entries = [collector.refresh_raw(e, eng.cfg.history_dir) for e in entries]
    _fill_single_run_sanity(entries)
    tomorrow = plan.next_plan(eng.cfg.automas_dir)
    failed = [e for e in entries if not e["ok"]]
    head = "全绿 ✅" if not failed else f"{len(failed)} 项出错 ⚠️"
    title = f"📋 {day[5:]} · {head}"
    # Event countdown rides on every report (operator order, 2026-08-20):
    # 来龙去脉见 docs/CODE-HISTORY.md「report.py:_compose_daily」
    act = plan.activity_countdown(eng.cfg.automas_dir)
    # 卡池倒计时同理，挂在最后（用户 2026-08-30 的要求：放在通知末尾）。
    # 三个游戏各自 try 住，一个源挂了不影响其余，全挂了就少这一段。
    try:
        bnow = datetime.now(tz=SERVER_TZ).replace(tzinfo=None)
        rows, nxt = banners.collect(bnow, skland_token=eng.cfg.skland_token)
        pool = banners.render(rows, bnow, nxt, banners.previews(bnow, rows, banners.version_ends(bnow, rows)))
        eng._announce_banners(bnow, nxt)
    except Exception:  # noqa: BLE001
        log.warning("卡池那一段整体失败", exc_info=True)
        pool = ""
    tail = "".join(f"\n\n{x}" for x in (act, pool) if x)
    written = summary.daily_report(eng.cfg, entries, tomorrow)
    if written:
        log.info("📋 日报由模型撰写（%d 条记录）", len(entries))
        foot = core.daily_footnote(entries)
        return title, written + tail + (f"\n\n{foot}" if foot else "")
    # 用户 2026-08-30 定的：模型写日报是**废除的规划**（太贵），
    # 结构化模板就是最终形态、目前够用。所以走到这里不是故障，
    # 是常态路径——原来打 WARNING 会让人以为坏了，天天在日志里留一条假伤。
    log.info("日报用结构化模板（模型撰写已废弃，这是正常路径）")
    title2, body = core.format_daily(day, entries, "", tomorrow)
    # 终末地日常名单当注释放在最后最后（用户 2026-09-02）
    foot = core.daily_footnote(entries)
    return title2, body + tail + (f"\n\n{foot}" if foot else "")


def _announce_banners(eng, now: datetime,
                      nxt: "dict[str, tuple[datetime, str]]") -> None:
    """开服前一天在企业微信群里说一声。

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
        return                      # 没送到就不打标记，下一轮再试
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


def _tacet_caption(eng) -> str:
    """「配置刷第 N 个：名字，掉 套装」——和日报里那一行同一个来源。"""
    try:
        from . import weeklyboss, wuwa_tacet  # noqa: PLC0415
        daily = weeklyboss._read(weeklyboss._file(eng.cfg.automas_dir, "DailyTask.json"))  # noqa: SLF001
        idx = int((daily or {}).get("Which Tacet Suppression to Farm") or 1)
        return f"配置刷第 {idx} 个：{wuwa_tacet.label(idx)}，掉 {wuwa_tacet.reward(idx)}"
    except Exception:  # noqa: BLE001
        return "配置的无音区序号没读到"


def _attach_tacet_shots(eng, day: str) -> list[str]:
    """日报发完，把这一天无音区刷完的结算页（OK-WW 补丁 tacetshot 拍的）用群机器人跟在后面。

    用户 2026-09-07：「我想确认一下是不是刷的是我想要的无音区种类，因为我不放心。
    刷完之后能不能贴一张截图在日报通知里面？」每张只发一次（状态目录记文件名）。
    返回发出去的文件名，测试用。
    """
    shots = _tacet_shots_dir(eng)
    if shots is None:
        return []
    sent_file = Path(eng.state.dir) / f"tacet-shots-{day}.sent"
    try:
        already = set(sent_file.read_text(encoding="utf-8").split())
    except OSError:
        already = set()
    # 只发一张：刷完最后一轮的结算页（用户 2026-09-07：「不要发没有用的截图，
    # 我只需要刷完之后产出的那一张就行」）。同一天拍了多张就发最新的。
    cands = [p for p in shots.glob("*_tacet_drops_original.png")
             if datetime.fromtimestamp(p.stat().st_mtime, tz=SERVER_TZ).strftime("%Y-%m-%d") == day
             and p.name not in already]
    if not cands:
        return []
    picks = [("tacet_drops", max(cands, key=lambda p: p.stat().st_mtime))]
    eng.notifier.send_group("🖼️ 无音区产出", f"{_tacet_caption(eng)}。下面是刷完的结算页。")
    done = []
    for _tag, p in picks:
        if not eng.notifier.send_group_image(p):
            done.append(p.name)
    if done:
        try:
            sent_file.write_text("\n".join(sorted(already | set(done))), encoding="utf-8")
        except OSError:
            log.warning("无音区截图的记账写不下来", exc_info=True)
        log.info("🖼️ 无音区截图已发 %d 张：%s", len(done), "、".join(done))
    return done
