"""Stage gate: before MAA is handed a stage, check that MAA can navigate to it.

**The incident (2026-10-10, machine clock).** At 04:25 a phone order set MAA's stage
to YW-4 (commands._set_stage, through the AUTO-MAS API). MAA's stages.json knew
YW-4, but its navigation task file resource/tasks/Stages/YW.json had no "YW-4" key
yet, so MAA core refused the Fight task when the 09:00 run handed it over (asst.log):

    [2026-10-10 09:01:10.060][ERR][Px17028][Tx55502] Unknown task: YW-4
    [2026-10-10 09:01:10.060][ERR][Px17028][Tx55502] Task YW-4 not found
    [2026-10-10 09:01:10.061][ERR][Px17028][Tx55502] The stage name is not in invalid, or is not main line stage YW-4
    [2026-10-10 09:01:10.061][ERR][Px17028][Tx55502] Cannot set stage YW-4

gui.log: 「理智作战: 理智作战 序列化失败」, then 「已停止」. One task that cannot be
set stops the whole MAA run - infrastructure, recruiting, everything - and AUTO-MAS's
three retries all died the same way. (At 13:04 the upstream YW.json with YW-4 was
placed on the machine.)

**MAA's own decision, replicated** (MAA dev-v2):

* src/MaaCore/Task/Interface/FightTask.cpp ~124-151 (set_params): stage "" ->
  LastOrCurBattleBegin, no navigation, always fine. "SSReopen-XX" (exactly 11
  characters) -> set_stage_name("XX-OpenOpt") must succeed. Anything else ->
  set_stage_name(stage) must succeed, or 「Cannot set stage」 and set_params fails.
* src/MaaCore/Task/Fight/StageNavigationTask.cpp 43-135 (set_stage_name): a task
  named exactly `stage` exists -> fine. Otherwise the name must match
  `^([A-Za-z]{0,3})(\\d{1,2})-(\\d{1,2})(?:-?(\\w+))*$` (YW-4 does not: no digit after
  the prefix, so 「not main line stage」), and task `Episode<chapter>` must exist. A
  difficulty suffix (the last `(\\w+)` repetition, capitalised by MAA) is allowed only
  for chapter 10-14 (Normal / Hard -> ChapterDifficultyNormal / ChapterDifficultyHard)
  and chapter >= 15 (Hard -> ChangeToRaidDifficulty + RaidConfirm, Normal ->
  ChangeToNormalDifficulty + NormalConfirm), and those tasks must exist. The chapter
  modes are integer ranges in get_chapter_difficulty_mode, replicated exactly.
* "Tasks that exist" = the top-level keys of every *.json under
  `<maa>/resource/tasks` (recursive: tasks.json, Stages/, MiniGame/, Roguelike/ ...)
  and `<maa>/cache/resource/tasks` (hot updates; MAA's log at 09:03:04 loads both).
  Only these two bounded folders are read. A name containing "@" that is not a key
  is "unknown": MAA can derive such a task from a template, which is not replicated.
  boost's \\w / \\d on std::string are ASCII, hence re.ASCII here.

**Safety.** A false "no" would cancel a whole MAA run, so "no" is answered only when
both folders were read and the rules above say the task is definitely absent.
`resource/tasks` missing, any file that cannot be read or parsed -> "unknown", never a
block, with one WARNING (errwatch pushes every WARNING to the group, so a broken MAA
install is still heard about) - at most once per due on the tick (kept in the due's
row, `warned`), once per refused order at set time. A missing `cache/resource/tasks` is no hot update.

**Which stage AUTO-MAS will send** (app/task/Maa/AutoProxy.py set_maa, ~842-897):
StageMode "Fixed" -> Info.Stage / Stage_1 / Stage_2 / Stage_3, otherwise
PlanConfig[<StageMode uuid>] with Info.Mode ALL -> group "ALL", Weekly -> the weekday
group of the game day (MaaPlanConfig.get_current_info: game_now, UTC+4 for the CN
servers, i.e. 04:00 Beijing). "-" is dropped, "*" is sent as "" (current stage).
Only when the user's Task.IfFight is on. Deliberately NOT checked, so never blocked on:
* the activity stage of 「活动关优先」: AUTO-MAS fetches it from the network at dispatch
  time (Config.get_stage_info(refresh=True)); the relay does not poll the network;
* Stage_Remain: AutoProxy reads it from plan_data, but upstream's MAA_STAGE_KEY has no
  Stage_Remain, so it is never filled - checking it could block on a stage never sent.
With several stages in StagePlan, MAA's GUI (UseOptionalStage) picks the first one
open today - not replicated - so the run is "no" only when every stage is "no"; a
"no" first stage with a reachable alternate is "unknown" (logged at INFO). Weekly
plans: when the weekday by the UTC+4 game day and by Beijing local time give
different plans (around 04:00), "unknown". Several users: "no" only when all are.

**Where it runs.**
1. commands._set_stage / commands._set_config (Info.Stage*): a stage that is a
   definite "no" is refused before anything is saved, with 「MAA 走不到，修改失败」,
   the stage and the reason (texts.stage_refused); "unknown" goes through. Every
   order that sets the stage ends there (commands.apply_command): the phone page /
   App / scripts/mac/order-now.sh through boot_stages._phone_execute (live, drained
   after a run, boot backlog; the refusal is the phone's receipt), and
   scripts/mac/order.sh through inbox.Inbox._apply. The user asked for exactly this
   on 2026-10-10 16:58 (Osaka); his words are USER_SAID in
   tests/test_stage_set_refused.py.
   Not gated: scripts/mac/mas-api.py and AUTO-MAS's own screen (they write
   AUTO-MAS directly) - the tick below still checks before the due.
2. Engine tick (`step`, every ~30 s, local files only): for each queue containing
   MAA, one check per due in [due - LEAD_MIN, due), persisted (state.json
   updates.stagegate_dues), so a relay restart does not check or alarm twice. And
   once at boot, right after AUTO-MAS answers and before the pre-update
   (boot_stages._stage_stagegate), with BOOT_LEAD_MIN: the machine is powered on at
   08:40 / 21:20 for the 09:00 / 21:30 queues (docs/CONFIG.md ARK_BOOT_TIMES), and the
   boot stages (the morning pre-update is budgeted up to 90 s before the queue) can
   eat the whole last 10 minutes before the loop's first tick. A boot-time "yes" /
   "unknown" is not final (row `final: False`), so the tick checks again. A "no"
   sends ONE group alarm per due. As shipped (PULL_FROM_QUEUE off) that is all
   (texts.stage_gate_warn): MAA stays in the queue and refuses the stage itself. With
   PULL_FROM_QUEUE on it also pulls MAA out of that queue only
   (commands.skip_script_in_queue; texts.stage_gate), and a boot-time "no" that a
   later file change (MAA's pre-update) turns into "yes" is put back before the due.
   Another queue / due is checked on its own.

**Putting MAA back** (PULL_FROM_QUEUE on only; records in updates.stagegate_skips, survive restarts):
* the stage becomes reachable before the due (task or config files changed) -> back
  at once, the run happens after all;
* the due is RESTORE_AFTER_MIN past and no script is running (the queue started
  without MAA and finished) -> back;
* a record from an earlier day (relay down, machine off) -> back, once nothing runs.
A failed put-back is retried every RETRY_MIN minutes (each failure is a WARNING).

**What the rest of the relay makes of a pull** (none with PULL_FROM_QUEUE off). The day's verdicts stay in
updates.stagegate_dues (KEEP_DAYS days) after the put-back: `excused` keeps the
missed-run / missing-item checks (missed.py) and the shutdown wait
(shutdown._unfinished_queues) from treating MAA's absence as a fault; for a queue the
pull left empty (an MAA-only shift) `settled_alone` silences 「没有运行」 and
`recent_pulled` lets shutdown._work_is_done count the shift as done. The daily report
lists the stopped shifts with the reason (`report_line`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ

log = logging.getLogger("ark.stagegate")

YES, NO, UNKNOWN = "yes", "no", "unknown"

# Pull MAA out of the queue run whose stage it cannot navigate to (and put it back
# afterwards). OFF: the due only gets one group alarm (texts.stage_gate_warn), MAA
# stays in the queue, starts and is refused by MAA itself, and nothing else in the
# relay treats that run specially. Taking a script out of a queue switches part of
# the user's run off: turning this on needs a line in relay/USER-SWITCHES.txt with
# the user's own words (tests/test_user_switches.py SWITCHED_PULLS fails without it).
PULL_FROM_QUEUE = False
LEAD_MIN = 10            # check this many minutes before a due
BOOT_LEAD_MIN = 60       # the boot pass: the machine boots 20 min before a due (ARK_BOOT_TIMES)
RESTORE_AFTER_MIN = 5    # put MAA back no earlier than this after the due
RETRY_MIN = 10           # between two failed put-backs
KEEP_DAYS = 3            # verdicts kept for the report / missed checks

# StageNavigationTask.cpp stage_regex; boost \w, \d on std::string are ASCII.
_STAGE_RE = re.compile(r"^([A-Za-z]{0,3})(\d{1,2})-(\d{1,2})(?:-?(\w+))*$", re.ASCII)
_STAGE_KEYS = ("Stage", "Stage_1", "Stage_2", "Stage_3")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_GAME_DAY_TZ = timezone(timedelta(hours=4))     # AUTO-MAS ARKNIGHTS_GAME_DAY_TZ, Official / Bilibili
_FMT = "%Y-%m-%d %H:%M"

_cache: dict = {"sig": None, "keys": None}


# ---------- MAA's task names ----------

def _task_dirs(maa_dir) -> list[Path]:
    root = Path(maa_dir)
    return [root / "resource" / "tasks", root / "cache" / "resource" / "tasks"]


def _task_files(maa_dir) -> list[Path]:
    out: list[Path] = []
    for d in _task_dirs(maa_dir):
        if d.is_dir():
            out.extend(sorted(d.rglob("*.json")))
    return out


def load_keys(maa_dir) -> tuple[frozenset | None, str]:
    """(every task name MAA loads, "") or (None, why it could not be read)."""
    if not maa_dir:
        return None, "MAA 的安装位置没配"
    main = _task_dirs(maa_dir)[0]
    if not main.is_dir():
        return None, f"{main} 不是文件夹"
    try:
        files = _task_files(maa_dir)
        sig = tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files)
    except OSError as exc:
        return None, f"列不出 {main} 里的文件（{exc}）"
    if sig == _cache["sig"]:
        return _cache["keys"], ""
    keys: set[str] = set()
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            return None, f"{f} 读不了（{type(exc).__name__}: {exc}）"
        if not isinstance(data, dict):
            return None, f"{f} 最外层不是一组任务"
        keys.update(str(k) for k in data)
    _cache.update(sig=sig, keys=frozenset(keys))
    return _cache["keys"], ""


def _set_stage_name(name: str, keys) -> tuple[str, str]:
    """StageNavigationTask::set_stage_name on `keys`: (verdict, reason)."""
    if name in keys:
        return YES, ""
    if "@" in name:
        return UNKNOWN, f"{name} 带 @，MAA 会按模板现生成任务，中继不复刻"
    m = _STAGE_RE.match(name)
    if not m:
        return NO, texts.stage_why("no_task", name)
    _prefix, chapter, _index, difficulty = m.groups()
    if f"Episode{chapter}" not in keys:
        return NO, texts.stage_why("no_chapter", name, chapter)
    if difficulty:
        up = difficulty[0].upper() + difficulty[1:].lower()
        n = int(chapter)
        if 10 <= n <= 14 and up in ("Hard", "Normal"):
            need = [f"ChapterDifficulty{up}"]
        elif n >= 15 and up == "Hard":
            need = ["ChangeToRaidDifficulty", "RaidConfirm"]
        elif n >= 15 and up == "Normal":
            need = ["ChangeToNormalDifficulty", "NormalConfirm"]
        else:
            return NO, texts.stage_why("bad_difficulty", name, chapter)
        if any(t not in keys for t in need):
            return NO, texts.stage_why("no_difficulty", name, chapter, hard=up == "Hard")
    return YES, ""


def navigable(stage: str, keys) -> tuple[str, str]:
    """FightTask::set_params' stage handling on `keys`: (verdict, reason for a "no")."""
    if stage == "":
        return YES, ""
    if stage.startswith("SSReopen-") and len(stage) == 11:
        v, why = _set_stage_name(stage[9:] + "-OpenOpt", keys)
        return (NO, texts.stage_why("no_reopen", stage)) if v == NO else (v, why)
    return _set_stage_name(stage, keys)


def check(stage: str, maa_dir, problems: list | None = None) -> tuple[str, str]:
    """Can MAA navigate to `stage` with the task files in `maa_dir`? (verdict, reason).

    problems: when given, an unreadable task file is added to it instead of being
    logged as a WARNING (the tick says it once per due, see _gate_due)."""
    if stage == "":
        return YES, ""
    if not maa_dir:
        log.info("关卡门：没配 MAA 的安装位置，%s 走不走得到不查", stage)
        return UNKNOWN, "MAA 的安装位置没配"
    keys, problem = load_keys(maa_dir)
    if keys is None:
        said = f"MAA 的关卡资料读不了（{problem}），{stage} 走不走得到不知道，不拦"
        if problems is None:
            log.warning("关卡门：%s", said)
        else:
            problems.append(said)
        return UNKNOWN, problem
    v, why = navigable(stage, keys)
    if v == UNKNOWN:
        log.info("关卡门：%s", why)
    return v, why


# ---------- what AUTO-MAS will send ----------

def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _plan_of(src: dict) -> list[str] | None:
    """AutoProxy's StagePlan from one group of stage keys; None when a value is not text."""
    out = []
    for k in _STAGE_KEYS:
        v = src.get(k, "-")
        if not isinstance(v, str):
            return None
        if v != "-":
            out.append("" if v == "*" else v)
    return out


def _user_plan(info: dict, cfg_dir: Path, at: datetime) -> tuple[list[str] | None, str]:
    mode = info.get("StageMode", "Fixed")
    if mode == "Fixed":
        plan = _plan_of(info)
        return plan, "" if plan is not None else "关卡项不是文字"
    try:
        tables = _load(cfg_dir / "PlanConfig.json")
    except (OSError, ValueError) as exc:
        return None, f"计划表读不了（{type(exc).__name__}）"
    table = tables.get(str(mode)) if isinstance(tables, dict) else None
    if not isinstance(table, dict):
        return None, f"选关模式指向的计划表 {mode} 不在 PlanConfig.json 里"
    pmode = (table.get("Info") or {}).get("Mode", "ALL")
    if pmode == "ALL":
        groups = [table.get("ALL")]
    elif pmode == "Weekly":
        # AUTO-MAS: game_now(server).strftime("%A"), falling back to ALL when that
        # group is missing. Read by the game day and by Beijing local time: an older
        # AUTO-MAS used local time, and the two differ between 00:00 and 04:00.
        days = {_WEEKDAYS[at.astimezone(tz).weekday()] for tz in (_GAME_DAY_TZ, SERVER_TZ)}
        groups = [table.get(d) if d in table else table.get("ALL") for d in sorted(days)]
    else:
        return None, f"计划表模式 {pmode} 不认识"
    plans = []
    for g in groups:
        if not isinstance(g, dict):
            return None, "计划表里缺这一天的那组"
        plans.append(_plan_of(g))
    if any(p is None for p in plans) or any(p != plans[0] for p in plans):
        return None, "按游戏日和按北京时间算出的计划表那一天不一样，或关卡项不是文字"
    return plans[0], ""


def _maa_script(data: dict) -> tuple[str, dict] | None:
    """(display name, node) of the one MAA script in ScriptConfig.json, None unless exactly one."""
    from ark_relay.core import plan  # noqa: PLC0415 - plan imports config, keep this module light
    found = []
    for inst in data.get("instances", []) if isinstance(data, dict) else []:
        node = data.get(inst.get("uid")) if isinstance(inst, dict) else None
        info = (node or {}).get("Info") or {}
        if plan._script_kind(info.get("Path") or info.get("RootPath") or "") == "MAA":
            found.append((str(info.get("Name") or "MAA"), node))
    return found[0] if len(found) == 1 else None


def run_verdict(automas_dir, maa_dir, at: datetime, problems: list | None = None) -> tuple[str, str, str]:
    """Will MAA accept the Fight stage AUTO-MAS sends at `at`? (verdict, stage, reason).

    problems: as in check - files that could not be read are added to it, not logged."""
    cfg_dir = Path(automas_dir) / "config" if automas_dir else None
    try:
        data = _load(cfg_dir / "ScriptConfig.json") if cfg_dir else None
    except (OSError, ValueError) as exc:
        said = f"AUTO-MAS 的脚本设置读不了（{type(exc).__name__}），MAA 这一班的关卡不查"
        if problems is None:
            log.warning("关卡门：%s", said)
        else:
            problems.append(said)
        return UNKNOWN, "", "脚本设置读不了"
    script = _maa_script(data) if data else None
    if script is None:
        return UNKNOWN, "", "找不到唯一的 MAA 脚本"
    users = [u for u in ((script[1].get("SubConfigsInfo") or {}).get("UserData") or {}).values()
             if isinstance(u, dict)]
    verdicts: list[tuple[str, str, str]] = []
    for u in users:
        info, task = u.get("Info") or {}, u.get("Task") or {}
        if "IfFight" not in task:
            verdicts.append((UNKNOWN, "", "用户设置里没有理智作战开关"))
            continue
        if not task.get("IfFight"):
            verdicts.append((YES, "", "理智作战关着"))
            continue
        stages, why = _user_plan(info, cfg_dir, at)
        if stages is None:
            verdicts.append((UNKNOWN, "", why))
            continue
        each = [(s, *check(s, maa_dir, problems)) for s in stages]
        if not each:
            verdicts.append((YES, "", ""))
        elif all(v == NO for _s, v, _w in each):
            verdicts.append((NO, each[0][0], each[0][2]))
        elif any(v == NO for _s, v, _w in each) and all(v != UNKNOWN for _s, v, _w in each):
            log.info("关卡门：首选/备选关卡里 %s 走不到、其余走得到，MAA 界面按开放日挑哪一关中继不复刻，不拦",
                     "、".join(s for s, v, _w in each if v == NO))
            verdicts.append((UNKNOWN, each[0][0], "有走得到的备选关卡"))
        elif any(v == UNKNOWN for _s, v, _w in each):
            first = next(x for x in each if x[1] == UNKNOWN)
            verdicts.append((UNKNOWN, first[0], first[2]))
        else:
            verdicts.append((YES, each[0][0], ""))
    if not verdicts:
        return YES, "", "MAA 没有用户"
    if all(v == NO for v, _s, _w in verdicts):
        return verdicts[0]
    if all(v == YES for v, _s, _w in verdicts):
        return YES, verdicts[0][1], verdicts[0][2]
    return next((x for x in verdicts if x[0] == UNKNOWN), (UNKNOWN, "", "几个用户结论不一样"))


# ---------- state ----------

def _store(state_dir):
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415 - avoid an import cycle
    return StateStore(state_dir)


def skips(state_dir) -> list[dict]:
    d = _store(state_dir).get("updates", "stagegate_skips")
    return list(d) if isinstance(d, list) else []


def _dues(state_dir) -> dict:
    d = _store(state_dir).get("updates", "stagegate_dues")
    return dict(d) if isinstance(d, dict) else {}


def _note_due(state_dir, due: datetime, queue: str, row: dict) -> None:
    dues = _dues(state_dir)
    day = due.strftime("%Y-%m-%d")
    dues.setdefault(day, {})[f"{queue}/{due:%H:%M}"] = row
    keep = sorted(dues)[-KEEP_DAYS:]
    _store(state_dir).set("updates", "stagegate_dues", {d: dues[d] for d in keep})


def _row(state_dir, queue: str, due: datetime) -> dict:
    row = (_dues(state_dir).get(due.strftime("%Y-%m-%d")) or {}).get(f"{queue}/{due:%H:%M}")
    return row if isinstance(row, dict) else {}


def note_pull(state_dir, rec: dict, *, due: datetime, stage: str, why: str, others: list,
              sig: str = "") -> None:
    """Keep a stage-gate pull: the put-back record and the due's verdict."""
    rec = dict(rec, due=due.strftime(_FMT), stage=stage, why=why, others=list(others), sig=sig)
    lst = [r for r in skips(state_dir)
           if not (r.get("queueId") == rec.get("queueId") and r.get("scriptId") == rec.get("scriptId"))]
    _store(state_dir).set("updates", "stagegate_skips", lst + [rec])
    _note_due(state_dir, due, rec["queue"], {"verdict": NO, "pulled": True, "stage": stage, "why": why,
                                             "others": list(others)})


def excused(state_dir, queue: str, due: datetime) -> bool:
    """Did the gate take MAA out of this queue run (`due` = that run's time)?"""
    return bool(state_dir) and _row(state_dir, queue, due).get("pulled") is True


def settled_alone(state_dir, queue: str, due: datetime) -> bool:
    """... and was MAA all that run had (an MAA-only shift: nothing was left to run)?"""
    row = _row(state_dir, queue, due) if state_dir else {}
    return row.get("pulled") is True and not row.get("others")


def recent_pulled(state_dir, now: datetime, window_min: int = 120) -> list[dict]:
    """Shifts the gate emptied within the last `window_min`, shaped like plan.recent_due_queues."""
    out = []
    for day, rows in _dues(state_dir).items() if state_dir else ():
        for key, row in (rows or {}).items():
            if not (isinstance(row, dict) and row.get("pulled") is True and not row.get("others")):
                continue
            queue, _, hhmm = key.rpartition("/")
            try:
                due = datetime.strptime(f"{day} {hhmm}", _FMT).replace(tzinfo=SERVER_TZ)
            except ValueError:
                continue
            if due <= now < due + timedelta(minutes=window_min):
                out.append({"name": queue, "due": due, "kinds": []})
    return out


def report_line(state_dir, day: str) -> str:
    """The daily report's section on the shifts the gate stopped, '' when none.

    Only a pull (or a failed pull) is listed: with PULL_FROM_QUEUE off MAA ran and
    refused the stage itself, which the report already shows as MAA's own failure."""
    rows = []
    for key, row in sorted((_dues(state_dir).get(day) or {}).items()) if state_dir else ():
        if isinstance(row, dict) and row.get("verdict") == NO and row.get("pulled") in (True, False):
            rows.append((key.rpartition("/")[0], row.get("stage", ""), row.get("why", "")))
    return texts.stage_gate_report(rows)


# ---------- the tick ----------

def _files_sig(cfg) -> str:
    """A cheap fingerprint of every file the verdict reads (stat only, no parsing)."""
    parts = []
    try:
        files = (_task_files(cfg.maa_dir) if cfg.maa_dir else []) + [
            Path(cfg.automas_dir) / "config" / n for n in ("ScriptConfig.json", "PlanConfig.json")]
        for f in files:
            if f.exists():
                st = f.stat()
                parts.append(f"{f}|{st.st_mtime_ns}|{st.st_size}")
    except OSError:
        return ""
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _maa_queues(automas_dir) -> tuple[str, list[dict]]:
    """(MAA's display name, [{name, times, others}]) for the timed queues holding MAA."""
    from ark_relay.core import plan  # noqa: PLC0415
    cfg_dir = Path(automas_dir) / "config"
    scripts = plan._scripts(cfg_dir)
    maa = [uid for uid, s in scripts.items() if s.get("kind") == "MAA"]
    if len(maa) != 1:
        return "", []
    out = []
    for q in plan.schedule(automas_dir):
        items = q.get("items", [])
        if maa[0] not in items:
            continue
        others = []
        for uid in items:
            kind = (scripts.get(uid) or {}).get("kind") or (scripts.get(uid) or {}).get("name") or "?"
            if uid != maa[0] and kind not in others:
                others.append(kind)
        out.append({"name": q["name"], "times": q.get("times", []), "others": others})
    return scripts[maa[0]].get("name") or "MAA", out


def _skip_default(queue: str, script: str):
    from ark_relay.features.phone import commands  # noqa: PLC0415
    return commands.skip_script_in_queue(queue, script)


def _restore_default(rec: dict) -> bool:
    from ark_relay.features.phone import commands  # noqa: PLC0415
    return commands.restore_script_in_queue(rec)


def _put_back(cfg, now: datetime, busy, restorer) -> None:
    recs = skips(cfg.state_dir)
    if not recs:
        return
    today = now.strftime("%Y-%m-%d")
    left, idle, changed = [], None, False
    sig = None
    for rec in recs:
        try:
            due = datetime.strptime(rec["due"], _FMT).replace(tzinfo=SERVER_TZ)
        except (KeyError, ValueError):
            due = now - timedelta(days=1)       # a record without a due: put it back
        why = ""
        if now < due and due.strftime("%Y-%m-%d") == today:
            sig = sig if sig is not None else _files_sig(cfg)
            if rec.get("sig") != sig:
                rec["sig"], changed = sig, True
                v, _stage, _w = run_verdict(cfg.automas_dir, cfg.maa_dir, due, [])
                if v == YES:
                    why = "关卡现在走得到了"
        elif now >= due + timedelta(minutes=RESTORE_AFTER_MIN):
            idle = (not busy()) if idle is None else idle
            if idle:
                why = "这一班已经过去" if due.strftime("%Y-%m-%d") == today else "之前哪天留下的"
        tried = rec.get("tried")
        if why and tried:
            try:
                if now - datetime.strptime(tried, _FMT).replace(tzinfo=SERVER_TZ) < timedelta(minutes=RETRY_MIN):
                    why = ""
            except ValueError:
                pass
        if why:
            try:
                if restorer(rec):
                    log.info("关卡门：%s，MAA 已放回队列「%s」", why, rec.get("queue"))
                    changed = True
                    continue
                problem = "放回去之后读回来还是没有"
            except Exception as exc:  # noqa: BLE001 - kept and retried
                problem = f"{type(exc).__name__}: {exc}"
            rec["tried"], changed = now.strftime(_FMT), True
            log.warning("关卡门：MAA 没能放回队列「%s」（%s），放回之前这个队列不跑 MAA，%d 分钟后再试",
                        rec.get("queue"), problem, RETRY_MIN)
        left.append(rec)
    if changed:
        _store(cfg.state_dir).set("updates", "stagegate_skips", left)


def _gate_due(cfg, notifier, q: dict, maa_name: str, due: datetime, now: datetime, skipper) -> None:
    problems: list = []
    v, stage, why = run_verdict(cfg.automas_dir, cfg.maa_dir, due, problems)
    log.info("关卡门：%s %s 的 MAA 关卡 %s —— %s%s", q["name"], f"{due:%H:%M}", stage or "（当前关）",
             {YES: "走得到", NO: "走不到", UNKNOWN: "不知道，不拦"}[v], f"（{why}）" if why else "")
    # Files that could not be read: one WARNING per due (errwatch pushes each WARNING
    # to the group), kept in the due's row so the boot pass, every tick and a relay
    # restart do not say it again.
    warned = bool(_row(cfg.state_dir, q["name"], due).get("warned"))
    if problems and not warned:
        log.warning("关卡门：%s %s：%s", q["name"], f"{due:%H:%M}", "；".join(dict.fromkeys(problems)))
        warned = True
    if v != NO:
        # A boot-pass (early) "yes" / "unknown" is kept as not final: the tick checks
        # again in the last LEAD_MIN minutes.
        row = {"verdict": v, "stage": stage, "why": why}
        if warned:
            row["warned"] = True
        if now < due - timedelta(minutes=LEAD_MIN):
            row["final"] = False
        if row.get("warned") or "final" not in row:
            _note_due(cfg.state_dir, due, q["name"], row)
        return
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    if not PULL_FROM_QUEUE:
        _note_due(cfg.state_dir, due, q["name"], {"verdict": NO, "alarm_only": True, "stage": stage, "why": why})
        title = texts.stage_gate_warn(q["name"])
        errs = notifier.send(title, texts.stage_gate_warn_body(q["name"], stage, why), alert=True)
        log.warning("关卡门：%s %s 的 MAA 关卡 %s 走不到（%s），MAA 照跑", q["name"], f"{due:%H:%M}", stage, why,
                    extra=errwatch.group_pushed(title, errs, notifier))
        return
    try:
        rec = skipper(q["name"], maa_name)
    except Exception as exc:  # noqa: BLE001 - the alarm below says it
        log.info("关卡门：从队列「%s」拿掉 MAA 失败（%s: %s）", q["name"], type(exc).__name__, exc)
        _note_due(cfg.state_dir, due, q["name"], {"verdict": NO, "pulled": False, "stage": stage, "why": why})
        pulled = False
    else:
        if rec:
            note_pull(cfg.state_dir, rec, due=due, stage=stage, why=why, others=q["others"], sig=_files_sig(cfg))
            pulled = True
        else:
            # Already out of the queue (a maintenance pull got there first): this run
            # does not hand MAA the stage, the next one will - still said, once.
            log.info("关卡门：队列「%s」里已经没有 MAA，不用拿", q["name"])
            _note_due(cfg.state_dir, due, q["name"], {"verdict": NO, "absent": True, "stage": stage, "why": why})
            pulled = None
    title = texts.stage_gate(q["name"])
    errs = notifier.send(title, texts.stage_gate_body(stage, why, pulled), alert=True)
    log.warning("关卡门：%s %s 的 MAA 关卡 %s 走不到（%s），%s", q["name"], f"{due:%H:%M}", stage, why,
                {True: "这一班先拿掉 MAA", False: "没能拿掉 MAA", None: "这一班队列里本来就没有 MAA"}[pulled],
                extra=errwatch.group_pushed(title, errs, notifier))


def step(cfg, notifier, now: datetime | None = None, *, busy=lambda: False,
         skipper=None, restorer=None, lead_min: int = LEAD_MIN) -> None:
    """One pass: put back what is due to go back, then check the MAA dues coming up.

    lead_min: how far ahead a due is checked. The boot pass uses BOOT_LEAD_MIN; only a
    "no" found that early is kept (and acted on), so the tick still checks again in
    the last LEAD_MIN minutes - a stage changed after boot is not missed."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    if not getattr(cfg, "automas_dir", None):
        return
    _put_back(cfg, now, busy, restorer or _restore_default)
    maa_name, queues = _maa_queues(cfg.automas_dir)
    day = now.strftime("%Y-%m-%d")
    for q in queues:
        for hhmm in q["times"]:
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if not (due - timedelta(minutes=lead_min) <= now < due):
                continue
            row = (_dues(cfg.state_dir).get(day) or {}).get(f"{q['name']}/{hhmm}")
            if isinstance(row, dict) and row.get("final", True):
                continue
            _gate_due(cfg, notifier, q, maa_name, due, now, skipper or _skip_default)
