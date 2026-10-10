"""Message text built from ledger entries: the failure message, the daily report, the missing-run message."""
from __future__ import annotations

from datetime import datetime

from ark_relay.core import texts
from ark_relay.core.config import RunRecord, SERVER_TZ, USER_TZ, both_clocks
from ark_relay.core.ledger_rows import (
    UNVERIFIED_STEP, _END_FARM_NOTE_SKIP, _LABELS, _maaend_listed, _row, _rows_for, _with_causes,
    maaend_unverified,
)
from ark_relay.core.names import GAME_ZH


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
    done = [t for t in (raw.get("tasks_done") or []) if t not in ("自动采集", "结束进程")]
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
            if later.get("script") != e.get("script") or later.get("user") != e.get("user"):
                continue
            if (later.get("started") or "") <= (e.get("started") or ""):
                continue
            done = set((later.get("raw") or {}).get("tasks_done") or [])
            # 「超时」 names no task: a later success of the same script covers it.
            # Every task the record does name still has to be in that success.
            named = {t for t in want if "超时" not in t}
            if (named != want and named <= done) or want <= done:
                when = str(later.get("finished") or "")[11:16]
                # A MaaEnd retry's 「任务完成」 with nothing from the game is not
                # 「做成了」; the day's title counts it as unverified.
                bare = named & set(maaend_unverified(later.get("raw") or {})) if later.get("script") == "MaaEnd" else set()
                got = "程序说做完了，但没证据，不算完成" if bare else "做成了"
                out[e["run_id"]] = ("、".join(sorted(want))
                                    + f"　后来在 {when} 那趟重试里{got}")
                break
    return out


def daily_footnote(entries: list[dict]) -> str:
    """The footnote at the end of the notification: the numbered key to Endfield's
    daily list. The number in 「日常 1-16 项完成」 is the index here. Uses the
    longest list of done tasks among the day's MaaEnd runs (failed runs included);
    returns an empty string if there is none."""
    best: list[str] = []
    for e in entries:
        if e.get("script") != "MaaEnd":
            continue
        raw = e.get("raw") or {}
        unverified = maaend_unverified(raw)
        done = [t for t in (raw.get("tasks_done") or [])
                if not any(k in t for k in _END_FARM_NOTE_SKIP) and t not in unverified]
        # The longest list of the day, whether or not that run was marked failed.
        if len(done) > len(best):
            best = done
    if best:
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


def _no_exit_note(e: dict) -> str:
    idle = (e.get("raw") or {}).get("maaend_no_self_exit")
    tail = f"（空等 {idle} 分钟）" if idle else ""
    return f"{_game(e.get('script'))}任务全完成，但跑完没自己退出{tail}"


def day_unverified_items(entries: list[dict]) -> list[tuple[str, list[str]]]:
    """[(script, [item, ...])]: items of the day the program called done with
    nothing from the game to show for it, after every run of the day (one run's
    evidence covers the same item in another). Runs stopped by hand are left out.

    MaaEnd: listed tasks (maaend_unverified). MAA: annihilation without a
    「剿灭模式 x/y」 line. OK-WW: steps the parser marked unverified (UNVERIFIED_STEP).
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
            for t in _maaend_listed(raw):
                end_listed[t] = None
                if t not in unv:
                    end_ok.add(t)
        elif (script == "MAA" and raw.get("annihilation") and e.get("ok")
              and not raw.get("maa_sanity_short")):
            # Only where the report would otherwise say it was fought or already
            # full; a run short of sanity or a failed one is said as such.
            anni = True
            anni_ok = anni_ok or bool(raw.get("annihilation_progress"))
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


def day_unverified(entries: list[dict]) -> list[tuple[str, int]]:
    """[(script, n)]: how many day_unverified_items each game has."""
    return [(s, len(items)) for s, items in day_unverified_items(entries)]


def _daily_head(failed: list, undone: list, retried: dict, kinds: dict,
                no_exit: list | None = None, unverified: list | None = None) -> str:
    """The verdict in the report title, worst thing first.

    Failures and unfinished runs are counted per game. Items done with no
    evidence (day_unverified) keep the title off 全绿: they are neither done nor
    failed, and are named as such.
    """
    parts = [f"{_game(s)}失败 {n} 次" for s, n in _count_by_script(failed)]
    parts += [f"{_game(s)} {n} 项没干完" for s, n in _count_by_script(undone)]
    parts += [_no_exit_note(e) for e in (no_exit or [])]
    unv = [f"{_game(s)} {n} 项没证据" for s, n in (unverified or [])]
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
            until = datetime.fromisoformat(w["until"]) if w.get("until") else None
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


def format_daily(day: str, entries: list[dict], prose: str = "",
                 plan: str = "") -> tuple[str, str]:
    """The one message of the day. Numbers here are copied, never generated.

    Laid out for a narrow phone screen: no nested indentation (full-width
    spaces do not line up across fonts), one fact per short line.
    """
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
    title = f"📋 {day[5:]} · {_daily_head(failed, undone, retried, kinds, no_exit, day_unverified(entries))}"

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
        icon = (_KIND_ICON["manual"] if kind == "manual"
                else "⚠️" if e["ok"] and e.get("incomplete") else "✅" if e["ok"]
                else _KIND_ICON.get(kind) or ("↻" if e["run_id"] in retried else "❌"))
        tag = "（剿灭检查）" if raw.get("annihilation") else ""
        tries = f"　连试 {len(attempts)} 次" if len(attempts) > 1 else ""
        lines.append(icon + f" {e['script']}{tag}　"
                     + _span(started, finished, e.get('duration_known', True)) + tries)
        if e in no_exit:
            lines.append(_row("注意", [_no_exit_note(e)]))
        # A run that did not go through gets its evidence bundle link as a row.
        if not e["ok"] and not kind and raw.get("evidence_page"):
            lines.append(_row("证据包", [raw["evidence_page"]]))
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
                note = f"MaaEnd 装新版 {raw['maaend_update_restart']} 后自己重启，用掉一次重试，不算失败"
            if kind == "update" and raw.get("okww_restart_dialog"):
                # OK-WW says 「游戏更新成功」 for any 「游戏即将重启」 dialog. The
                # collector looked at the game folder; the note says what it found
                # in one of three definite forms.
                files = "、".join(raw.get("okww_client_files") or [])
                note = {
                    "patch": f"游戏更新成功（更新了客户端文件：{files}），重启后重跑，不算失败",
                    "anticheat": f"游戏更新成功（只更新了反作弊组件，文件位于 {files}），重启后重跑，不算失败",
                    "none": "游戏弹了「即将重启」但客户端文件没有变，重启后重跑，不算失败",
                }.get(str(raw.get("okww_client_change")), "游戏弹了「即将重启」，重启后重跑；客户端有没有换文件没查到，不算失败")
            lines += [_row("备注", [note]), ""]
            continue
        if not e["ok"]:
            # A failed run still shows what it did: the rows, with the failure
            # (or the retry that fixed it) as the first note.
            did, cost, out, left, notes = _rows_for(e, finished)
            notes.insert(0, retried.get(e["run_id"])
                         or _fmt_failed(e.get("failed_tasks") or [],
                                        causes=(e.get("raw") or {}).get("maaend_fail_causes")))
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
            else:
                # No progress line = no proof of anything fought (collector_maa);
                # the gate stays open, so say exactly that.
                note = "没读到剿灭进度，本周按没打满算，下一轮再打"
            lines += [_row("备注", [note]), ""]
            continue
        did, cost, out, left, notes = _rows_for(e, finished)
        if e.get("incomplete"):
            # summarize() writes one bullet per line; here the bullets are joined
            # with 「；」, except right after a 「：」.
            why = str(e["incomplete"]).replace("\n· ", "；").replace("\n", "；").replace("：；", "：")
            notes.insert(0, "没干完：" + why)
        if notes and not (did or cost or out or left):
            # Notes only: one 备注 row, not four 「—」 rows above it.
            lines += [_row("备注", notes), ""]
            continue
        lines += [_row(l, v) for l, v in
                  zip(_LABELS, (did, cost, out, left, notes))]
        lines.append("")

    if restarts:
        lines += [f"ℹ️ MaaEnd 发版自更新重启 {restarts} 次，未计失败", ""]
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
