"""Daily report and interim look: when to send, and what to send."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from datetime import datetime, timedelta

from ark_relay.core import texts
from ark_relay.features.banners import banners
from ark_relay.core import collector, ledger as core, ledger_report, plan
from ark_relay.features.report import scoreboard
from ark_relay.core.config import SERVER_TZ, atomic_write_text

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
    ARK_LAST_RUN_AFTER is only the fallback. The report, the interim look and
    the shutdown decision all use this one cutoff, measured by the clock.
    """
    times = sorted(t for q in plan.schedule(eng.cfg.automas_dir)
                   for t in q.get("times", []))
    hhmm = times[-1] if times else eng.cfg.last_run_after
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except ValueError:
        hh, mm = 21, 30
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def _makeup_in_flight(eng, now: datetime) -> list[str]:
    """Scripts whose make-up (makeup.py) is dispatched and has not produced a record yet.

    The report waits for it: sent in between, it describes the day with the
    failure and without the make-up that may already have fixed it.
    """
    try:
        from ark_relay.features.makeup import makeup  # noqa: PLC0415
        return makeup.in_flight(eng.cfg.state_dir, now)
    except Exception:
        log.exception("读补跑状态出错，日报不等它")
        return []


def _maybe_interim_report(eng, now: datetime | None = None) -> None:
    """Report once the day's earlier queues are done, hours before the
    daily summary is due.

    Independent of the shutdown setting: what decides it is that the earlier
    queues finished, not that a power-off is coming.
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
    if _makeup_in_flight(eng, now):
        return
    # Once per finished daytime round, not once per day: a later run adds
    # entries past the covered mark and gets its own interim.
    covered = eng.state.interim_covered(day)
    if len(entries) <= covered:
        return
    # Our own test runs (run-one.sh --test) never reach his phone: a round
    # made only of test-window records is marked covered without a push.
    fresh, _tests = core.split_test(entries[covered:], test_windows(eng.cfg.state_dir))
    if not fresh:
        eng.state.mark_interim_sent(day, len(entries))
        log.info("%s 这一轮只有测试窗口里的记录，不推速览", day)
        return
    # Judge manual-vs-scheduled from this round's new entries only; the
    # earlier rounds have each already been reported on their own.
    label = "手动执行" if eng._round_is_manual(fresh) else "临时查看"
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
        write_daily_techlog(eng, yday)
        if errors := eng.notifier.send(title + "（补发）", body, daily=True):
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
    # The cutoff is the last queue's start time, so right after it that queue's
    # game may still be launching with no process yet. Wait until every queue
    # that came due has recorded its scripts (the shutdown decision does the same).
    if unfinished := eng._unfinished_queues(now, eng.state.read_ledger(day)):
        log.info("日报再等等：%s", "；".join(unfinished))
        return
    if going := _makeup_in_flight(eng, now):
        log.info("日报再等等：%s 的补跑还没出结果", "、".join(going))
        return

    title, body = eng._compose_daily(day, entries)
    write_daily_techlog(eng, day)
    errors = eng.notifier.send(title, body, daily=True)
    if errors:
        # Do not mark it sent - retry on the next tick rather than lose the day.
        log.error("日报推送失败，稍后重试: %s", "；".join(errors))
        return
    eng.state.mark_report_sent(day)
    log.info("📋 %s 日报已推送（%d 条记录）", day, len(entries))
    _attach_tacet_shots(eng, day)


def _compose_daily(eng, day: str, entries: list[dict]) -> tuple[str, str]:
    """The daily report: the structured template (core.format_daily) over the
    day's real records, plus the countdowns and the deploy / retry / make-up /
    stage-gate lines. Every word and number comes from code."""
    # `raw` in the ledger is what the parser produced at bookkeeping time; after
    # a parser change older entries miss fields, so recompute from the history
    # logs before reporting.
    entries = [collector.refresh_raw(e, eng.cfg.history_dir, getattr(eng.cfg, "maaend_dir", None))
               for e in entries]
    _fill_single_run_sanity(entries)
    tomorrow = plan.next_plan(eng.cfg.automas_dir)
    # The event countdown goes on every daily report, not only on the last day.
    # 来龙去脉见 docs/CODE-HISTORY.md「report.py:_compose_daily」
    act = plan.activity_countdown(eng.cfg.automas_dir)
    # The banner countdown goes last. banners.collect handles each game on its
    # own, so one dead source does not take the others down; if the whole
    # section fails, only this section is missing.
    try:
        bnow = datetime.now(tz=SERVER_TZ).replace(tzinfo=None)
        banner_failed: list[str] = []
        notes: dict[str, str] = {}
        tr = banners.Trace.new()
        leads: dict[str, str] = {}
        rows, nxt = banners.collect(bnow, skland_token=eng.cfg.skland_token, failed=banner_failed, notes=notes,
                                    trace=tr, leads=leads,
                                    read_image=banners.image_reader(eng.cfg.state_dir))
        # A source that could not be read says so in its own block (render gets
        # `failed`); otherwise a missing game reads as "nothing running there".
        pool = banners.render(rows, bnow, nxt, notes, tr, banner_failed, leads)
        banners.save_trace(eng.cfg.state_dir, bnow, pool, tr)
        eng._announce_banners(bnow, nxt)
        # Banner history changes are logged only, not pushed.
        for changed in banners.update_history(eng.cfg.state_dir, bnow):
            log.info("%s", changed)
    except Exception:
        log.warning("卡池那一段整体失败", exc_info=True)
        pool = "⚠️ 卡池那一段整体没取到（不是没有卡池，是没读到）"
    # The code version's scoreboard (counted by append_ledger after every run) is
    # computed and logged here; it is not put into the message.
    log.info("记分：%s", scoreboard.line(eng.state.store, str(eng.state.store.get("versions", "code") or "")))
    tail = "".join(f"\n\n{x}" for x in (act, pool) if x)
    # The structured template is the only path (the model-written report was
    # retired on 08-30 and removed), so this is INFO, not WARNING.
    log.info("日报用结构化模板（模型撰写已废弃，这是正常路径）")
    entries, tests = core.split_test(entries, test_windows(eng.cfg.state_dir))
    shifts = _shifts(eng)
    title2, body = core.format_daily(day, entries, "", tomorrow, shifts=shifts)
    if tests:
        log.info("日报：%d 条测试窗口里的记录不列出来（%s）", len(tests),
                 "、".join(m.get("run_id", "?") for m in tests))
    # The Endfield daily list goes at the very end as a footnote.
    foot = core.daily_footnote(entries)
    # The deploy notes, the relay's own faults, the machine checks, the self-check
    # and the test-window count go to the technical log (write_daily_techlog,
    # D-1010); the report keeps one plain sentence on the deploys.
    tail2 = f"\n\n{line}" if (line := deploys_line(eng.cfg.state_dir, day)) else ""
    # The outcome of the per-route gathering retry (collect_retry).
    if retry := retry_line(eng.cfg.state_dir, day, getattr(eng.cfg, "maaend_dir", None)):
        body += f"\n\n{retry}"
    # The make-up of a failed MAA / MaaEnd run (makeup.py) never pushes on its
    # own; this line is where its outcome is said.
    if made := makeup_line(eng.cfg.state_dir, day, entries, shifts):
        body += f"\n\n{made}"
    # Shifts the stage gate stopped (stagegate.py): MAA could not navigate to the stage.
    from ark_relay.features.schedule import stagegate  # noqa: PLC0415
    if gated := stagegate.report_line(eng.cfg.state_dir, day):
        body += f"\n\n{gated}"
    # No tool is named anywhere in what the user reads (D-1010).
    return (ledger_report.plain_words(title2),
            ledger_report.plain_words(body + tail + (f"\n\n{foot}" if foot else "") + tail2))


def _shifts(eng) -> list[tuple[str, str]]:
    """[(queue name, "HH:MM")] from AUTO-MAS's queue config; [] when unreadable."""
    try:
        return [(str(q.get("name") or ""), str(t)) for q in plan.schedule(eng.cfg.automas_dir)
                for t in q.get("times", [])]
    except Exception:
        log.info("日报读不到排班，班次名不写", exc_info=True)
        return []


def _announce_banners(eng, now: datetime,
                      nxt: "dict[str, tuple[datetime, str]]") -> None:
    """Announce in the WeCom group, the day before, a banner that opens tomorrow.

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
    if mark:
        write_daily_techlog(eng, day)
    else:
        title = title.replace("📋", "🔎", 1) + f"（{label}）"
    errors = eng.notifier.send(title, body, daily=True)
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

    The index is the teleport target OK-WW itself reported (okww_info in the
    ledger), not the one written in the config. When the two differ, both are
    said. Only when the reported one cannot be read does it fall back to the
    configured one, and then it says that it is the configured value.
    """
    from ark_relay.features.weekly import weeklyboss  # noqa: PLC0415
    from ark_relay.core import wuwa_tacet  # noqa: PLC0415
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
        line = f"实际刷了第 {got} 个：{wuwa_tacet.label(got, day)}，掉 {wuwa_tacet.reward(got, day)}"
        if want is not None and want != got:
            line += f"。注意：设置里写的是第 {want} 个（{wuwa_tacet.label(want, day)}），两者不一样"
        return line
    if want is not None:
        return f"设置里写的是第 {want} 个：{wuwa_tacet.label(want, day)}，掉 {wuwa_tacet.reward(want, day)}（实际序号没读到）"
    return "无音区序号没读到，设置和实际都没拿到"


def _changes_file(state_dir, day: str) -> Path:
    return Path(state_dir) / f"changes-{day}.txt"


def remember_change(state_dir, notes: str, version: str = "", day: str | None = None) -> None:
    """Keep a deploy's release notes for the day's report (the push is log-only)."""
    day = day or datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    f = _changes_file(state_dir, day)
    f.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=SERVER_TZ).strftime("%H:%M")
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"· {stamp}{'（v' + version + '）' if version else ''}\n{notes.strip()}\n")


def changes_of_day(state_dir, day: str) -> str:
    """The day's accumulated release notes, '' when nothing was deployed."""
    if not state_dir:
        return ""
    try:
        return _changes_file(state_dir, day).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


_DEPLOY_STAMP = re.compile(r"^· \d{2}:\d{2}(?:（v[^）]*）)?$", re.M)


def deploys_line(state_dir, day: str) -> str:
    """The report's one sentence on the day's deploys, '' when there was none.

    Counted from remember_change's stamp lines. The notes themselves go to the
    technical log; whether a deploy changes what the games do is not guessed here.
    """
    n = len(_DEPLOY_STAMP.findall(changes_of_day(state_dir, day)))
    return f"今天中继更新了 {n} 次" if n else ""


def daily_tech_sections(eng, day: str) -> list[tuple[str, str]]:
    """(heading, text) of everything technical the day's report used to carry (D-1010)."""
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    from ark_relay.features.selfcheck import machinecheck, selfcheck  # noqa: PLC0415
    sd = eng.cfg.state_dir
    out: list[tuple[str, str]] = []

    def titled(text: str) -> None:
        # these sections start with their own heading line
        head, _, rest = (text or "").strip().partition("\n")
        if rest.strip():
            out.append((head.strip(), rest.strip()))

    if changes := changes_of_day(sd, day):
        out.append(("今天中继改了什么", changes))
    titled(selfcheck.daily_section(day))
    titled(errwatch.daily_section(sd, day))
    titled(machinecheck.daily_section(sd))
    # Same steps as _compose_daily, so the lines match the rows the report shows.
    entries = [collector.refresh_raw(e, eng.cfg.history_dir, getattr(eng.cfg, "maaend_dir", None))
               for e in eng.state.read_ledger(day)]
    _fill_single_run_sanity(entries)
    entries, tests = core.split_test(entries, test_windows(sd))
    if tests:
        out.append(("测试窗口里的记录（不计入日报）",
                    f"另外测试跑过 {len(tests)} 趟：" + "、".join(str(m.get("run_id", "?")) for m in tests)))
    # The evidence links, versions and file names format_daily keeps out of the rows.
    rows: list[str] = []
    core.format_daily(day, entries, tech=rows, shifts=_shifts(eng))
    if rows:
        out.append(("日报各行的证据包、版本和文件", "\n".join(rows)))
    return out


def write_daily_techlog(eng, day: str) -> bool:
    """Append the day's technical sections to the technical log, once per day.

    Called only where the day's report is sent and marked (an interim look does
    not write), and a section whose heading is already marked for the day is not
    written again, so a retried send does not duplicate it. Never raises and never
    changes the report: the user reads the report, we read this file.
    """
    sd = getattr(eng.cfg, "state_dir", None)
    if not sd:
        return False
    try:
        from ark_relay.core import techlog  # noqa: PLC0415
        done = eng.state.techlog_written(day)
        todo = [(h, t) for h, t in daily_tech_sections(eng, day) if h not in done]
        wrote = {h for h, t in todo if techlog.append(day, h, t, state_dir=sd)}
        if wrote:
            eng.state.mark_techlog_written(day, done | wrote)
        return len(wrote) == len(todo)
    except Exception as exc:  # noqa: BLE001
        # A WARNING, so the group hears it: the report still goes out, but the technical
        # log we read every day would be missing the day (the user, 2026-10-11 17:43:
        # nothing that did not fix itself stays out of the group).
        log.warning("日报的技术部分没写进技术日志：%s: %s", type(exc).__name__, exc)
        return False


def retry_line(state_dir, day: str, maaend_dir=None) -> str:
    """One line on the day's per-route gathering retry (collect_retry's stamp), '' when none."""
    if not state_dir:
        return ""
    p = Path(state_dir) / "collect-retry" / f"{day}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if "passed" not in d and "failed" not in d:
        return "自动采集补跑：开始了，还没有结果"
    from ark_relay.features.makeup import collect_retry  # noqa: PLC0415
    zh = collect_retry._locale(Path(maaend_dir)) if maaend_dir else {}
    name = lambda r: collect_retry.route_label(r, zh)  # noqa: E731
    parts = []
    if d.get("blocked"):
        # Routes booked for the retry because they walked through 「战斗中无法使用」.
        parts.append(texts.collect_blocked_row([name(r) for r in d["blocked"]], first=True))
    if d.get("passed"):
        parts.append("走通 " + "、".join(name(r) for r in d["passed"]))
    if d.get("failed"):
        parts.append("仍失败 " + "、".join(name(r) for r in d["failed"]))
    if d.get("blocked_again"):
        parts.append(texts.collect_blocked_row([name(r) for r in d["blocked_again"]], again=True))
    if d.get("unknown"):
        parts.append("没结论 " + "、".join(name(r) for r in d["unknown"]))
    if d.get("recurrent"):
        # Also its own group alarm (collect_retry; daily-only 2026-10-05..06).
        parts.append("连续两天没走通 " + "、".join(name(r) for r in d["recurrent"]) + "，已交给我们这边去查")
    if d.get("note"):
        parts.append(str(d["note"]))
    return "自动采集补跑：" + ("；".join(parts) if parts else "没有要补的")


_MAKEUP_GAME = {"MAA": "明日方舟", "MaaEnd": "终末地"}


def _plain_makeup_reason(note: str) -> str:
    """Why no make-up ran, in plain words (makeup.maa_work_done's reasons, read back
    from the marker, older wording included)."""
    why = note.removeprefix("不补跑：").strip()
    if "拿不准" in why and "打过仗" in why:
        return "拿不准第一次打没打过仗，怕重复花理智"
    if "一仗都没打" in why:
        return "第一次开起来了但没做完、一仗没打，这种不自动整轮重跑"
    if m := re.search(r"不接受这份配置（(.*)）", why):
        return ledger_report.plain_rejected(m.group(1)) + "，原样补跑还是一样"
    if "已经开始干活" in why:
        return "第一次已经开始干活，再跑一遍会再吃一份理智药"
    return ledger_report.plain_words(why)


def makeup_line(state_dir, day: str, entries: "list[dict] | None" = None,
                shifts: "list[tuple[str, str]] | None" = None) -> str:
    """One line per script on the day's make-up run (makeup.py's marker), '' when there was none.

    Plain words, game and shift named, e.g.
    「明日方舟早班失败后没有自动补跑（拿不准第一次打没打过仗，怕重复花理智），12:05 已手动补上」;
    the other endings are 「失败后自动补跑，走通了」, 「…还是没成（…）」, 「…已开跑，
    还没有结果」, 「…派了自动补跑，N 分钟没跑出记录」 and 「…想自动补跑，没能开跑（…）」.
    `entries` (the day's ledger) gives the shift and a later run that made it up.

    A make-up that went through is not pushed (handle._flush_pending), so this
    line and the failed run's row are where it is said.
    """
    from ark_relay.features.makeup import makeup  # noqa: PLC0415
    by_id = {e.get("run_id"): e for e in entries or []}
    lines = []
    for script, ent in sorted(makeup.read_marker(state_dir, day).items()):
        if not isinstance(ent, dict):
            continue
        failed_run = by_id.get(ent.get("run_id"))
        shift = ledger_report.shift_of(failed_run.get("started"), shifts) if failed_run else ""
        what = "、".join(ent.get("tasks") or ent.get("failed") or [])
        head = _MAKEUP_GAME.get(script, script) + shift
        # 「整个 MAA」 is the whole game: the game name already says it.
        redo = f"「{what}」" if what and not what.startswith("整个") else ""
        note = str(ent.get("note") or "").strip()
        res = ent.get("result")
        if res == makeup.OK:
            failed = "、".join(ent.get("failed") or [])
            said = [f"原来失败于：{failed}"] if failed and failed != what else []
            said += [note] if note else []
            line = f"{head}失败后自动补跑{redo}，走通了" + (f"（{'；'.join(said)}）" if said else "")
        elif res == makeup.FAILED:
            line = f"{head}失败后自动补跑{redo}，还是没成" + (f"（{note}）" if note else "")
        elif res == makeup.DISPATCHED:
            line = f"{head}失败后自动补跑{redo}已开跑，还没有结果"
        elif res == makeup.NO_RECORD:
            line = f"{head}失败后派了自动补跑{redo}，{makeup.STALE_MIN} 分钟没跑出记录"
        elif res == makeup.GAVE_UP and note.startswith("不补跑"):
            # decided not to (MAA that already fought), not a dispatch that failed
            line = f"{head}失败后没有自动补跑（{_plain_makeup_reason(note)}）"
            if failed_run and (later := ledger_report.later_success(entries or [], failed_run, shifts)):
                line += f"，{later[0]} " + ("已手动补上" if later[1] else "已补上")
        else:   # couldnt_run / gave_up
            line = f"{head}失败后想自动补跑{redo}，没能开跑" + (f"（{note}）" if note else "")
        lines.append(ledger_report.plain_words(line))
    return "\n".join(lines)


# The test windows run-one.sh marked; kept under this name for its callers.
test_windows = ledger_report.test_windows


def _attach_tacet_shots(eng, day: str) -> list[str]:
    """After the daily report goes out, send the day's Tacet Suppression
    settlement screen (captured by the OK-WW tacetshot patch) to the group bot,
    with a caption saying which one was farmed (`_tacet_caption`).

    Each image is sent only once (file names are recorded in
    tacet-shots-<day>.sent in the state dir). Returns the file names sent.
    """
    from ark_relay.features.modes import modes  # noqa: PLC0415
    if not modes.tacet_shots_on(eng.state.dir):
        return []
    shots = _tacet_shots_dir(eng)
    if shots is None:
        return []
    sent_file = Path(eng.state.dir) / f"tacet-shots-{day}.sent"
    try:
        already = set(sent_file.read_text(encoding="utf-8").split())
    except OSError:
        already = set()
    # Send exactly one: the newest settlement screen of the day not sent yet.
    cands = [p for p in shots.glob("*_tacet_drops_original.png")
             if datetime.fromtimestamp(p.stat().st_mtime, tz=SERVER_TZ).strftime("%Y-%m-%d") == day
             and p.name not in already]
    if not cands:
        return []
    pick = max(cands, key=lambda p: p.stat().st_mtime)
    # The caption says what the picture is; without it the picture is not sent
    # either, and nothing is marked, so a later send of the day tries both again.
    if eng.notifier.send_group(texts.TACET_DROPS, f"{_tacet_caption(eng, day)}。下面是刷完的结算页。"):
        return []
    done = [] if eng.notifier.send_group_image(pick) else [pick.name]
    if done:
        # Mark the earlier captures as handled too: the next report only sends
        # ones captured after this point.
        try:
            atomic_write_text(sent_file, "\n".join(sorted(already | {p.name for p in cands})))
        except OSError:
            log.warning("无音区截图的记账写不下来", exc_info=True)
        log.info("🖼️ 无音区截图已发 %d 张：%s", len(done), "、".join(done))
    return done
