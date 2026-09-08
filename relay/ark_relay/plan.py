"""What is scheduled to run next.

The daily report has to end with tomorrow's plan. Knowing last night went fine
is only half the answer - the operator also needs to know what will be farmed
tomorrow, while there is still time to change it.

Everything here is read straight from AUTO-MAS's own config, so the report can
never disagree with what the machine will actually do.
"""
from __future__ import annotations

import json
import os
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ, USER_TZ, atomic_write_text

log = logging.getLogger("ark.plan")

# How long this reminder keeps showing after an event has ended. MAA's event
# cache holds on to events that expired long ago ("红丝绒" was gone months back
# and is still in there), so a window is mandatory; three days is enough to span
# a weekend without turning into permanent noise. The reminder text spells out
# how much of the window is left, so it does not look stuck.
_EXPIRED_REMINDER = timedelta(days=3)

# AUTO-MAS stores per-user settings under an opaque uid; walk to them by shape
# rather than by hard-coded id, so a new user or a reinstall does not break it.
_SANITY_USE = {
    "OperatorProgression": "干员经验",
    "WeaponProgression": "武器经验",
    "CrisisDrills": "危机演习",
    "Essence": "精华",
}


def _tokyo(hhmm: str) -> str:
    """'09:00' on the server clock -> '10:00' in Tokyo."""
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return ""
    shift = int((USER_TZ.utcoffset(None) - SERVER_TZ.utcoffset(None)).total_seconds() // 3600)
    return f"{(hh + shift) % 24:02d}:{mm:02d}"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("读取 %s 失败: %s", path.name, exc)
        return {}


def _script_kind(path: str) -> str:
    """Classify a script by its install path: "MAA" | "MaaEnd" | "".

    The display name is whatever the operator typed ("maa明日方舟", "新 MaaEnd
    脚本"), so it cannot be matched on. The install path is set by AUTO-MAS
    itself and matches the names the collector puts in the ledger, which is
    what lets the two be compared.
    """
    p = (path or "").lower()
    if "maaend" in p:
        return "MaaEnd"
    if "maa" in p:
        return "MAA"
    # The path is D:\ark\okww, which contains no "maa" - before 2026-08-27 this
    # returned "", so the OK-WW line in tomorrow's plan was forever nothing but
    # a bare name.
    if "okww" in p or "ok-ww" in p:
        return "OK-WW"
    return ""


def _scripts(cfg_dir: Path) -> dict[str, dict]:
    """{script_uid: {name, kind, stage, medicine, sanity_use}}"""
    data = _load(cfg_dir / "ScriptConfig.json")
    out: dict[str, dict] = {}
    for inst in data.get("instances", []):
        uid = inst.get("uid")
        node = data.get(uid) or {}
        info_node = node.get("Info") or {}
        entry = {
            "name": info_node.get("Name") or "?",
            "kind": _script_kind(info_node.get("Path") or info_node.get("RootPath") or ""),
            "path": info_node.get("Path") or info_node.get("RootPath") or "",
        }
        for user in ((node.get("SubConfigsInfo") or {}).get("UserData") or {}).values():
            if not isinstance(user, dict):
                continue
            info, task = user.get("Info") or {}, user.get("Task") or {}
            # The combat switch. With it off, not a single stage is farmed
            # tomorrow, and the plan has to say so - otherwise the line
            # 「理智 1-7（固定）」 describes something that will not happen.
            if "IfFight" in task:
                entry["fight"] = bool(task.get("IfFight"))
            if info.get("Stage"):
                entry["stage"] = info["Stage"]
                entry["stage_mode"] = info.get("StageMode", "")
                entry["medicine"] = info.get("MedicineNumb")
            if info.get("Annihilation"):
                entry["annihilation"] = info["Annihilation"]
            if task.get("SanityTaskType"):
                entry["sanity_use"] = _SANITY_USE.get(
                    task["SanityTaskType"], task["SanityTaskType"]
                )
        out[uid] = entry
    return out


def _queues(cfg_dir: Path) -> list[dict]:
    data = _load(cfg_dir / "QueueConfig.json")
    out = []
    for inst in data.get("instances", []):
        node = data.get(inst.get("uid")) or {}
        info = node.get("Info") or {}
        sub = node.get("SubConfigsInfo") or {}
        times = []
        for tid, t in (sub.get("TimeSet") or {}).items():
            if tid == "instances" or not isinstance(t, dict):
                continue
            ti = t.get("Info") or {}
            if ti.get("Enabled") and ti.get("Time"):
                times.append(ti["Time"])
        items = []
        for qid, q in (sub.get("QueueItem") or {}).items():
            if qid == "instances" or not isinstance(q, dict):
                continue
            sid = (q.get("Info") or {}).get("ScriptId")
            if sid:
                items.append(sid)
        if info.get("TimeEnabled") and times:
            out.append({
                "name": info.get("Name") or "?",
                "times": sorted(times),
                "after": info.get("AfterAccomplish"),
                "items": items,
            })
    out.sort(key=lambda q: q["times"][0])
    return out


def schedule(automas_dir: Path | None) -> list[dict]:
    """[{name, times, items}] straight from AUTO-MAS's own queue config.

    Read rather than hard-coded, so changing a queue time in AUTO-MAS cannot
    leave the relay watching for a run that no longer exists.
    """
    if not automas_dir:
        return []
    cfg_dir = Path(automas_dir) / "config"
    return _queues(cfg_dir) if cfg_dir.is_dir() else []


_OKWW_PO_CACHE: dict[str, str] | None = None


def _okww_zh(okww_dir: Path | None) -> dict[str, str]:
    """OK-WW's own official Simplified Chinese translation table (msgid -> msgstr).

    English task names must not appear in a report. Tomorrow's plan on
    2026-08-27 read 「附加 Check Weekly Garden、Merge Echo If discar」 - English
    and truncated at that. Translations come from **its own language pack**, they
    are never invented: `Tacet Discord Nest` is officially 「残像聚落」, and the
    「无音区巢穴」 I wrote from intuition earlier was simply wrong.
    """
    global _OKWW_PO_CACHE  # noqa: PLW0603
    if _OKWW_PO_CACHE is not None:
        return _OKWW_PO_CACHE
    _OKWW_PO_CACHE = {}
    if not okww_dir:
        return _OKWW_PO_CACHE
    po = (Path(okww_dir) / "data" / "apps" / "ok-ww" / "working"
          / "i18n" / "zh_CN" / "LC_MESSAGES" / "ok.po")
    if not po.is_file():
        return _OKWW_PO_CACHE
    try:
        text = po.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _OKWW_PO_CACHE
    for m in re.finditer(r'msgid "((?:[^"\\]|\\.)*)"\s*\nmsgstr "((?:[^"\\]|\\.)*)"',
                         text):
        src, dst = m.group(1), m.group(2)
        if src and dst:
            _OKWW_PO_CACHE[src] = dst
    return _OKWW_PO_CACHE


# The key for the 「刷满所有梦魇巢穴」 entry in OK-WW's additional-task list. Both
# the nest line and the additional-task line have to recognise it (one uses it to
# write 「刷到打满」, the other to drop the entry from the additional list), and two
# copies of the string would eventually disagree.
_NEST_FULL = "Auto Farm all Nightmare Nest"


def _okww_farm_bit(daily: dict, zh: dict[str, str]) -> str:
    """The stamina line: which instance tomorrow's stamina goes into, and what it
    yields. "" means the line is omitted.

    A step of its own because this is a four-way branch tree where each branch
    has its own name table; it shares no intermediate value with the nest and
    additional-task lines that follow, and reading them interleaved hides which
    lines are mutually exclusive.
    """
    from . import collector  # noqa: PLC0415 - reuse of the forgery name table, kept in one place
    which = daily.get("Which to Farm") or ""
    # Both branches use the shared lookup tables, always 1-based (matching the
    # in-game F2 list). Before 2026-09-08 this file kept its own copy of
    # collector._FORGERY_NAMES, which had only 4 entries, while the phone page
    # could already pick the 5th - and picking it wrote 「凝素领域·#5」.
    from . import wuwa_forgery, wuwa_tacet  # noqa: PLC0415 - avoids an import cycle
    if which == "Forgery Challenge":
        idx = int(daily.get("Which Forgery Challenge to Farm") or 1)
        return f"体力刷 {wuwa_forgery.label(idx)}，出 {wuwa_forgery.reward(idx)}"
    if which == "Tacet Suppression":
        idx = int(daily.get("Which Tacet Suppression to Farm") or 1)
        return f"体力刷 {wuwa_tacet.label(idx)}，出 {wuwa_tacet.reward(idx)}"
    if which == "Simulation Challenge":
        tgt = str(daily.get("Material Selection") or "")
        tgt_zh = collector._SIM_ZH.get(tgt, zh.get(tgt, tgt))
        return f"体力刷 模拟领域·{tgt_zh}" if tgt_zh else "体力刷 模拟领域"
    if which:
        return f"体力刷 {zh.get(which, which)}"
    return ""


def _okww_nest_bit(daily: dict, nest: dict, adds: list[str],
                   zh: dict[str, str]) -> str:
    """The tacet nest line: which spots get fought, and how far. "" means the line
    is omitted.

    A step of its own because "will it be fought tomorrow, and how much" is
    spread across three different config keys (the farm-to-full checkbox in the
    additional-task list, the daily-echo checkbox in the daily task, and the nest
    task's own spot range), and they have to be merged into one sentence before
    anything can be reported. That merge logic has nothing to do with the lines
    on either side of it.
    """
    nest_label = zh.get("Tacet Discord Nest", "残像聚落")
    # The 「自动刷所有梦魇巢穴」 checkbox only decides between farming to full and
    # stopping after one echo; the range farmed is governed by the nest task's own
    # two options. So it must not be listed verbatim as an additional task: one
    # line saying 「只打落渊南丘」 followed by 「附加 自动刷所有梦魇巢穴」
    # contradicts itself. Fold it into the nest line and state its real effect.
    scope = (nest.get("Only Farm These Nests") or "").strip()
    where = f"只打{scope}" if scope else "全部点位"
    if _NEST_FULL in adds:
        return f"{nest_label} {where}，刷到打满"
    if daily.get("Farm Nightmare Nest for Daily Echo"):
        return f"{nest_label} {where}，只取一个每日声骸就停"
    if scope:
        return f"{nest_label} {where}（未满才打）"
    return ""


def _okww_extra_bit(cfg_dir: Path, adds: list[str], zh: dict[str, str]) -> str:
    """The additional-task line. "" means the line is omitted.

    A step of its own because it has to read one more config file
    (FarmEchoTask.json) and consult the relay's own weekly-boss bookkeeping to
    decide whether the 「传送刷 4C 声骸」 entry really farms echoes or has been
    commandeered by the weekly-boss patch. None of that relates to the config the
    two preceding lines read, and leaving it in the main function buries the main
    thread of it.
    """
    # 「Teleport and Farm 4C Echo」 is commandeered here by the weekly-boss patch:
    # when FarmEchoTask's Teleport to Boss = Weekly Challenge, it collects the
    # weekly-boss reward rather than farming echoes. The user, 2026-09-02:
    # 「我敢百分百确定鸣潮没有传送刷取 4C 的任务」 - so report the weekly boss.
    farm_f = cfg_dir / "FarmEchoTask.json"
    try:
        farm_cfg = json.loads(farm_f.read_text(encoding="utf-8")) if farm_f.is_file() else {}
    except (OSError, ValueError):
        farm_cfg = {}
    weekly = str(farm_cfg.get("Teleport to Boss") or "") == "Weekly Challenge"
    rest = []
    for a in adds:
        if a == _NEST_FULL:
            continue
        if a == "Teleport and Farm 4C Echo" and weekly:
            lvl = str(farm_cfg.get("Boss Level") or "")
            idx = int(farm_cfg.get("Which Weekly Boss to Teleport") or 1)
            done, nm = _weekly_boss_state()
            label = f"周本 {nm or f'战歌重奏第 {idx} 个'}" + (f"（{lvl} 级）" if lvl else "")
            # The user, 2026-09-02: 「不是说都刷完了吗？」 - once the week's quota
            # is full, say outright that it will not be fought tomorrow
            rest.append(label + ("，本周已打满，明天不打" if done else "，明天会打"))
        else:
            rest.append(zh.get(str(a), str(a)))
    if rest:
        shown = "、".join(rest[:2])
        if len(rest) > 2:
            shown += f" 等 {len(rest)} 项"
        return "附加 " + shown
    # No additional tasks means no line at all - 「无附加任务」 carries no
    # information.
    return ""


def _okww_plan_bits(automas_dir: Path | None,
                    okww_dir: Path | None = None) -> list[str]:
    """What OK-WW will farm tomorrow, read from the master config that actually
    takes effect.

    In the 2026-08-27 daily report the OK-WW line was a bare 「· OK-WW」 - the user
    could not see which instance would be farmed or whether the tacet nests would
    be fought. The information lives in
    `<automas>/data/<script id>/Default/ConfigFile/` (the master copied wholesale
    to OK-WW before each run); read that, not OK-WW's own config, which gets
    overwritten.
    """
    if not automas_dir:
        return []
    root = Path(automas_dir) / "data"
    if not root.is_dir():
        return []
    for sid in root.iterdir():
        d = sid / "Default" / "ConfigFile"
        daily_f = d / "DailyTask.json"
        if not daily_f.is_file():
            continue
        try:
            daily = json.loads(daily_f.read_text(encoding="utf-8"))
            nest_f = d / "NightmareNestTask.json"
            nest = (json.loads(nest_f.read_text(encoding="utf-8"))
                    if nest_f.is_file() else {})
        except (OSError, ValueError):
            continue
        # Quick config overrides the corresponding master keys with Task.* from
        # the AUTO-MAS user config, so the additional-task list in the master is
        # **not** the one that will actually run. That is why tomorrow's plan on
        # 2026-08-27 listed three additional tasks that were never going to
        # execute.
        quick = _okww_quick_overrides(automas_dir)
        if quick is not None:
            daily = {**daily, **quick}

        zh = _okww_zh(okww_dir)
        adds = [str(a) for a in (daily.get(
            "Additional Tasks to Run After Daily Task") or [])]
        return [b for b in (_okww_farm_bit(daily, zh),
                            _okww_nest_bit(daily, nest, adds, zh),
                            _okww_extra_bit(d, adds, zh)) if b]
    return []


def _weekly_boss_state() -> "tuple[bool, str]":
    """(quota full this week?, boss name) - reads the relay's own weekly-boss
    bookkeeping (the weeklyboss module)."""
    try:
        import os  # noqa: PLC0415
        from .weeklyboss import WeeklyBossGate  # noqa: PLC0415
        state = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
        v = WeeklyBossGate(state).settings()
        return bool(v.get("本周已打")), str(v.get("名字") or "")
    except Exception:  # noqa: BLE001
        return False, ""


def _okww_quick_overrides(automas_dir: Path | None) -> dict | None:
    """The keys AUTO-MAS's 「快速配置」 (quick config) actually pushes to OK-WW.

    None means quick config is off (the master config takes effect as written).
    The key mapping is copied from `app/task/Okww/AutoProxy.py`; when that
    changes, this has to change with it.
    """
    if not automas_dir:
        return None
    f = Path(automas_dir) / "config" / "ScriptConfig.json"
    if not f.is_file():
        return None
    try:
        root = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    mapping = {
        "WhichToFarm": "Which to Farm",
        "WhichTacetSuppressionToFarm": "Which Tacet Suppression to Farm",
        "WhichForgeryChallengeToFarm": "Which Forgery Challenge to Farm",
        "MaterialSelection": "Material Selection",
        "FarmNightmareNestForDailyEcho": "Farm Nightmare Nest for Daily Echo",
        "AdditionalTasks": "Additional Tasks to Run After Daily Task",
    }
    if not isinstance(root, dict):
        return None
    for script in root.values():
        # The top level is not all script nodes; lists and the like are mixed in.
        # Measured 2026-08-27: calling .get() straight away raises AttributeError
        # and breaks the whole plan.
        if not isinstance(script, dict):
            continue
        if (script.get("Info") or {}).get("Name") != "OK-WW":
            continue
        users = ((script.get("SubConfigsInfo") or {}).get("UserData") or {})
        if not isinstance(users, dict):
            continue
        for user in users.values():
            if not isinstance(user, dict):
                continue
            if not (user.get("Info") or {}).get("IfQuickConfig"):
                continue
            task = user.get("Task") or {}
            return {dst: task[src] for src, dst in mapping.items()
                    if src in task}
    return None


def _maaend_extra_bits(maaend_dir: Path | None, when) -> list[str]:
    """What the MaaEnd round runs besides the dailies - for now, only AutoCollect.

    On 2026-08-27 the user added AutoCollect to the AUTO-MAS instance inside
    MaaEnd, in first position; measured, it ran for 33 minutes. It only runs on
    the selected weekdays, and tomorrow's plan gave no hint of this at all: on one
    of those days the morning shift would spend an unannounced extra half hour,
    pushing back the sanity potions and the protocol space.
    """
    if not maaend_dir:
        return []
    f = Path(maaend_dir) / "config" / "mxu-MaaEnd.json"
    if not f.is_file():
        return []
    try:
        d = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return []
    days = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6}
    zh = "一二三四五六日"
    for inst in d.get("instances") or []:
        if inst.get("id") != "automas":
            continue
        for t in inst.get("tasks") or []:
            if t.get("taskName") != "AutoCollect" or not t.get("enabled"):
                continue
            opts = (t.get("optionValues") or {}).get("AutoCollectSchedule") or {}
            names = opts.get("caseNames") or []
            picked = sorted(days[n.replace("AutoCollectSchedule", "")]
                            for n in names
                            if n.replace("AutoCollectSchedule", "") in days)
            if not picked:
                return []
            label = "周" + "、".join(zh[i] for i in picked)
            routes = len((((t.get("optionValues") or {})
                           .get("AutoCollectRoutes") or {}).get("caseNames") or []))
            if when.weekday() in picked:
                return [f"⏳ 先跑自动采集（{routes} 条路线，实测约 33 分钟）"]
            return [f"自动采集仅 {label} 跑"]
    return []


def _tomorrow():
    """Tomorrow in the server timezone. The plan is about that day, not today."""
    return datetime.now(SERVER_TZ) + timedelta(days=1)


# The schedule shows game names, not tool names. The user, 2026-08-31:
# 「那个排班搞好看一点」. What he cares about is which game does what tomorrow;
# MAA / MaaEnd / OK-WW are implementation detail.
_GAME_OF = {"MAA": "明日方舟", "MaaEnd": "终末地", "OK-WW": "鸣潮"}


def maintenance_lines(day) -> list[str]:
    """Server-maintenance notices in tomorrow's plan (the user, 2026-09-03:
    「这个务必要体现」 - this must be shown)."""
    try:
        from datetime import datetime as _dt  # noqa: PLC0415
        from . import maintenance  # noqa: PLC0415
        from .config import SERVER_TZ  # noqa: PLC0415
        at = _dt(day.year, day.month, day.day, 8, 46, tzinfo=SERVER_TZ)
        wins = maintenance.today(at)
    except Exception:  # noqa: BLE001
        return []
    return [f"⚠️ {game} {start:%m-%d %H:%M}–{end:%H:%M} 停服维护：当天队列里不跑它，"
            f"队列跑完立刻更新客户端，{end:%H:%M} 开服后单独补跑"
            for game, (start, end, _why) in wins.items()]


# The annihilation field's values are an English enum (Annihilation /
# Chernobog@Annihilation, ...); the Chinese exists only inside the AUTO-MAS
# frontend's bundled build. This block used to live in phone.py and was deleted
# there on 2026-09-04 as "no longer needed" while that file was slimmed down -
# but this file still imported it, so every tick raised ImportError and took the
# catch-up update, the daily report and the auto-shutdown down with it, unnoticed
# for a whole morning. Hence it now lives in the only place that still uses it,
# with nothing borrowed across modules.
_LABEL_PAIR = re.compile(
    r'label\s*:\s*"([^"]{1,40})"\s*,\s*value\s*:\s*"([^"]{1,60})"')


def _asar_value_labels(automas_dir, state_dir) -> dict:
    """`{English value: Chinese name}`, extracted from the frontend bundle and
    cached by size + mtime."""
    if not automas_dir:
        return {}
    asar = Path(automas_dir) / "resources" / "app.asar"
    try:
        st = asar.stat()
    except OSError:
        log.warning("找不到 app.asar，剿灭那一项会留下英文取值")
        return {}
    stamp = f"{st.st_size}-{int(st.st_mtime)}"
    # Pure cache: the Chinese labels extracted from AUTO-MAS's asar bundle,
    # rebuilt by itself if lost. Deliberately a file of its own rather than part
    # of state.json - it is derived data, not state.
    cache = Path(state_dir) / "asar-labels.json"
    try:
        got = json.loads(cache.read_text(encoding="utf-8"))
        if got.get("stamp") == stamp:
            return got.get("map") or {}
    except (OSError, json.JSONDecodeError):
        pass
    try:
        text = asar.read_bytes().decode("utf-8", "replace")
    except OSError:
        log.warning("读不了 app.asar", exc_info=True)
        return {}
    out: dict = {}
    for label, value in _LABEL_PAIR.findall(text):
        if any("\u4e00" <= ch <= "\u9fff" for ch in label):
            out.setdefault(value, label)
    try:
        atomic_write_text(cache, json.dumps({"stamp": stamp, "map": out},
                                            ensure_ascii=False))
    except OSError:
        pass
    return out


def next_plan(automas_dir: Path | None) -> str:
    """Human-readable summary of what will run next. '' if it cannot be read."""
    if not automas_dir:
        return ""
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        log.warning("找不到 AUTO-MAS 配置目录: %s", cfg_dir)
        return ""

    scripts, queues = _scripts(cfg_dir), _queues(cfg_dir)
    if not queues:
        return ""

    lines = ["📅 明日安排"]
    from datetime import datetime as _dt, timedelta as _td  # noqa: PLC0415
    from .config import SERVER_TZ as _TZ  # noqa: PLC0415
    lines += maintenance_lines((_dt.now(tz=_TZ) + _td(days=1)).date())
    for q in queues:
        for t in q["times"]:
            lines.append(f"🕘 {t}　东京 {_tokyo(t)}")
        for uid in q["items"]:
            s = scripts.get(uid) or {}
            bits = []
            if s.get("fight") is False:
                # With combat off no stage is farmed tomorrow. Printing
                # 「理智 1-7（固定）」 from the stage number anyway would announce
                # a plan that will not happen.
                bits.append("不刷关卡（只做日常）")
            elif s.get("stage"):
                mode = "固定" if s.get("stage_mode") == "Fixed" else s.get("stage_mode", "")
                bits.append(f"理智 {s['stage']}" + (f"（{mode}）" if mode else ""))
            if (anni := s.get("annihilation")):
                # Worth a line of its own. "Close" is how the weekly gate
                # leaves the switch after a pass, and it is also how it looks
                # when somebody closed it by hand - in which case nothing will
                # ever reopen it, because the gate only restores a week it
                # recorded closing itself. Either way the weekly reward is not
                # being collected, and silence about that costs a reward a week.
                # The values are an English enum (Annihilation /
                # Chernobog@Annihilation, ...), with the Chinese living in the
                # AUTO-MAS frontend bundle. English must not appear in a report -
                # on 2026-08-31 the user saw 「剿灭 Annihilation」 on his phone.
                zh = {}
                try:
                    zh = _asar_value_labels(automas_dir, Path(os.environ.get(
                        "ARK_STATE_DIR", "./ark-state")))
                except Exception:  # noqa: BLE001
                    pass
                bits.append("剿灭 本周已完成/关闭" if anni == "Close"
                            else f"剿灭 {zh.get(anni, anni)}")
            if (med := s.get("medicine")) is not None:
                # AUTO-MAS stores "use as many as you have" as a sentinel, not
                # as a real count. Printing 999 makes a reader stop and wonder.
                bits.append("理智药不限" if int(med) >= 999
                            else ("不吃理智药" if int(med) <= 0 else f"理智药 {med} 个"))
            if s.get("kind") == "MaaEnd":
                # AUTO-MAS's SanityTaskType is only the tab; on its own it reads
                # as the answer and is not one - 「干员养成」 does not say whether
                # that means 经验 (exp) or 进阶 (ascension), and the reward set
                # decides which item actually drops. Report the resolved chain
                # instead.
                from . import sanity_plan  # noqa: PLC0415 - avoids a cycle
                if label := sanity_plan.read(automas_dir).get("label"):
                    bits.append(f"理智用于 {label}")
                bits += _maaend_extra_bits(s.get("path"), _tomorrow())
            elif s.get("sanity_use"):
                bits.append(f"理智用于 {s['sanity_use']}")
            if s.get("kind") == "OK-WW":
                bits += _okww_plan_bits(automas_dir, s.get("path"))
            # One thing per line. It used to read
            # 「· MAA　理智 1-7 · 剿灭 … · 理智药不限」, where the same 「·」 served
            # as both bullet and separator, and on a phone that one line wrapped
            # into three unreadable ones.
            label = s.get("name", "?")
            game = _GAME_OF.get(str(s.get("kind") or ""), "")
            lines.append(f"▸ {game}" if game else f"▸ {label}")
            lines += [f"　{b}" for b in bits]
        if q["after"] == "Shutdown":
            lines.append("⏻ 跑完自动关机")
        lines.append("")
    return "\n".join(lines)


def recent_due_queues(automas_dir: Path | None, now, window_minutes: int = 120) -> list[dict]:
    """Queues whose time came up in the last `window_minutes`, with their scripts.

    [{"name": ..., "due": datetime, "kinds": ["MAA", "MaaEnd"]}]

    Two bounds matter, and getting either wrong breaks the machine's day:

    A queue that just became due may still be working through its items, and
    between two of them no game process exists at all - MAA has exited, the
    next game is still launching. Powering off in that window costs a run; it
    cost the Endfield half of 2026-08-16.

    But the wait cannot be open-ended either. If a script simply never runs -
    it crashed, the game would not start - waiting for it forever would keep
    the machine powered on all day and every day after. Past the window the
    queue is written off and the machine may sleep.
    """
    if not automas_dir:
        return []
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        return []
    scripts = _scripts(cfg_dir)
    out: list[dict] = []
    for q in _queues(cfg_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            # Yesterday's occurrence too: a 21:30 queue still inside its
            # window at 00:10 used to vanish from this list the moment the
            # date rolled, dropping the "don't power off mid-queue" guard in
            # exactly the inter-script gap it exists for.
            due = None
            for day_shift in (0, -1):
                cand = (now + timedelta(days=day_shift)).replace(
                    hour=hh, minute=mm, second=0, microsecond=0)
                if cand <= now < cand + timedelta(minutes=window_minutes):
                    due = cand
                    break
            if due is None:
                continue
            kinds = []
            for uid in q.get("items", []):
                kind = (scripts.get(uid) or {}).get("kind")
                if kind and kind not in kinds:
                    kinds.append(kind)
            if kinds:
                out.append({"name": q.get("name", "?"), "due": due, "kinds": kinds})
    return out


def activity_countdown(automas_dir: Path | None, now=None,
                       cache_path: Path | None = None) -> str:
    """One line per current event: name, remaining time, end on both clocks.

    Read from MAA's own activity cache (cache/gui/StageActivityV2.json,
    maintained by the MAA resource repo and OTA-updated), so the relay never
    holds its own copy of event dates. Empty string when anything is missing -
    a report without a countdown beats no report.

    Requested 2026-08-20: the operator farms event stages on a fixed-stage
    config; an event ending overnight silently turns the next morning's run
    into guaranteed failures. The countdown makes that visible in every
    report, and an expired event is flagged instead of dropped.

    What the *expired* notice says changed on 2026-08-24. It used to warn
    "换关" - the main stage is fixed, so an event stage left behind would fail
    every run. By then the config had been on AT-4, a permanent stage, for
    weeks, so that advice could never apply and the line read as stale. The
    operator asked for the thing that is actually still time-critical after an
    event ends: **clear out the event shop before it goes away.** The line now
    also states how long it will keep appearing, so it cannot be mistaken for
    something stuck.
    """
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    try:
        if cache_path is None:
            maa = script_dir(automas_dir, "MAA")
            if not maa:
                return ""
            cache_path = Path(maa) / "cache" / "gui" / "StageActivityV2.json"
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return ""
    now = now or datetime.now(tz=SERVER_TZ)
    lines: list[str] = []
    for node in ((data.get("Official") or {}).get("sideStoryStage") or {}).values():
        act = node.get("Activity") if isinstance(node, dict) else None
        if not isinstance(act, dict):
            continue
        name = str(act.get("StageName") or "").strip() or "当期活动"
        raw = str(act.get("UtcExpireTime") or "")
        try:
            tz_hours = int(act.get("TimeZone", 8))
            end = datetime.strptime(raw, "%Y/%m/%d %H:%M:%S").replace(
                tzinfo=timezone(timedelta(hours=tz_hours)))
        except (ValueError, TypeError):
            continue
        left = end - now
        end_txt = (f"{end.astimezone(SERVER_TZ):%m-%d %H:%M} 结束"
                   f"（东京 {end.astimezone(USER_TZ):%H:%M}）")
        if left.total_seconds() <= 0:
            # Only a *recently* ended event deserves the warning - the cache
            # keeps whole past events around ("红丝绒" months gone), and a
            # permanent stale alarm teaches the reader to ignore alarms.
            if left >= -_EXPIRED_REMINDER:
                # Say how much of the window is left. Without it the same line
                # reads identically on day 1 and day 3, so it looks stuck even
                # though it does expire - which is exactly how the operator
                # read it on 2026-08-24.
                gone = _EXPIRED_REMINDER + left    # how long until it stops showing
                g_days, g_rem = divmod(int(gone.total_seconds()), 86400)
                g_hours = g_rem // 3600
                g_span = (f"{g_days} 天 {g_hours} 时" if g_days
                          else f"{g_hours} 时")
                lines.append(
                    f"⚠️ 活动「{name}」已于 {end.astimezone(SERVER_TZ):%m-%d %H:%M}"
                    f" 结束——请及时检查活动商店的奖励是否已经搬空"
                    f"（此提醒还会出现 {g_span}）")
            continue
        days, rem = divmod(int(left.total_seconds()), 86400)
        hours, rem = divmod(rem, 3600)
        mins = rem // 60
        span = (f"{days} 天 {hours} 时" if days else
                (f"{hours} 时 {mins} 分" if hours else f"{mins} 分"))
        head = "⚠️ " if left <= timedelta(hours=36) else ""
        lines.append(f"{head}🗓️ 活动「{name}」剩 {span}，{end_txt}")
    return "\n".join(lines)


def script_dir(automas_dir: Path | None, kind: str) -> Path | None:
    """Where AUTO-MAS says a given script is installed. None if unknown.

    Saves having to configure the MaaEnd path a second time: AUTO-MAS already
    knows it, and a path configured twice is a path that will disagree with
    itself the day one of them moves.
    """
    if not automas_dir:
        return None
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        return None
    for s in _scripts(cfg_dir).values():
        if s.get("kind") == kind and s.get("path"):
            return Path(s["path"])
    return None
