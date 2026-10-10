"""What is scheduled to run next, read straight from AUTO-MAS's own config.

next_plan is the 「明日安排」 block at the end of the daily report and on the
phone page. schedule / recent_due_queues / queue_rows / script_dir give the
queues, their times and scripts to the rest of the relay. activity_countdown
reads MAA's event cache.
"""
from __future__ import annotations

import json
import os
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core.config import SERVER_TZ, USER_TZ, atomic_write_text
from ark_relay.core.names import GAME_ZH

log = logging.getLogger("ark.plan")

# The plan is rebuilt on every phone-state publish (phone.state_payload ->
# next_plan), and a WARNING is a group message: a source it cannot read is said
# once per condition (site -> the error last said) and forgotten once that source
# reads again.
_last_error: dict[str, str] = {}


def _say_once(site: str, exc: BaseException, msg: str, *args, exc_info: bool = False) -> None:
    key = f"{type(exc).__name__}: {exc}"
    if _last_error.get(site) != key:
        log.warning(msg, *args, exc_info=exc_info)
        _last_error[site] = key

# How long the reminder for an ended event keeps showing. MAA's event cache keeps
# events that ended long ago, so there is a window; the reminder text says how
# much of it is left.
_EXPIRED_REMINDER = timedelta(days=3)

# MaaEnd SanityTaskType values -> the words the plan uses.
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
    脚本"), so the install path (set by AUTO-MAS, D:\\ark\\okww and the like) is
    matched instead; the kinds match the script names the collector books.
    """
    p = (path or "").lower()
    if "maaend" in p:
        return "MaaEnd"
    if "maa" in p:
        return "MAA"
    # The OK-WW path (D:\ark\okww) contains no "maa".
    if "okww" in p or "ok-ww" in p:
        return "OK-WW"
    return ""


def _scripts(cfg_dir: Path) -> dict[str, dict]:
    """{script_uid: {name, kind, path, fight, stage, stage_mode, medicine, annihilation, sanity_use}}

    Scripts and users are found by walking ScriptConfig.json's instances (opaque
    uids), not by hard-coded ids.
    """
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
            # The combat switch: off means no stage is farmed, and the plan says so.
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


def _hhmm(raw) -> "str | None":
    """A queue time as "HH:MM", from its first two fields ("09:00:00" counts);
    None when it does not read as a time of day."""
    try:
        hh, mm = (int(x) for x in str(raw).split(":")[:2])
    except ValueError:
        return None
    return f"{hh:02d}:{mm:02d}" if 0 <= hh < 24 and 0 <= mm < 60 else None


def _queues(cfg_dir: Path) -> list[dict]:
    data = _load(cfg_dir / "QueueConfig.json")
    out = []
    bad_now: set[str] = set()
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
                # Every reader of these times (the overrun alarm, the
                # don't-power-off-mid-queue guard, the plan) parses "HH:MM";
                # a time that is not is skipped, and said once.
                if (hhmm := _hhmm(ti["Time"])) is not None:
                    times.append(hhmm)
                    continue
                site = f"time:{info.get('Name') or inst.get('uid')}:{ti['Time']}"
                bad_now.add(site)
                if site not in _last_error:
                    log.warning("队列 %s 的定时「%s」认不出是几点几分，这个时刻不看超时、不防关机",
                                info.get("Name") or "?", ti["Time"])
                    _last_error[site] = "unparsable"
        items = []
        for qid, q in (sub.get("QueueItem") or {}).items():
            if qid == "instances" or not isinstance(q, dict):
                continue
            sid = (q.get("Info") or {}).get("ScriptId")
            if sid:
                items.append(sid)
        if info.get("TimeEnabled") and times:
            out.append({
                "uid": inst.get("uid"),    # runtime-snapshot's queueId
                "name": info.get("Name") or "?",
                "times": sorted(times),
                "after": info.get("AfterAccomplish"),
                "items": items,
            })
    for site in [k for k in _last_error if k.startswith("time:") and k not in bad_now]:
        _last_error.pop(site, None)
    out.sort(key=lambda q: q["times"][0])
    return out


def queue_rows(automas_dir) -> list[dict]:
    """Every queue as the phone state lists it: {"名", "定时", "开机跑", "脚本"}.

    Read from the same QueueConfig.json / ScriptConfig.json next_plan reads (not
    from the AUTO-MAS backend, which snapshot.read skips once power-off is
    issued), so the queue list and the plan text in one state agree."""
    if not automas_dir:
        return []
    cfg_dir = Path(automas_dir) / "config"
    names = {uid: s["name"] for uid, s in _scripts(cfg_dir).items()}
    data = _load(cfg_dir / "QueueConfig.json")
    out = []
    for inst in data.get("instances", []):
        node = data.get(inst.get("uid")) or {}
        info = node.get("Info") or {}
        items = (node.get("SubConfigsInfo") or {}).get("QueueItem") or {}
        sids = [(q.get("Info") or {}).get("ScriptId") for k, q in items.items()
                if k != "instances" and isinstance(q, dict)]
        out.append({"名": str(info.get("Name") or "?"),
                    "定时": info.get("TimeEnabled"),
                    "开机跑": info.get("StartUpEnabled"),
                    "脚本": [names[s] for s in sids if s in names]})
    return out


def schedule(automas_dir: Path | None) -> list[dict]:
    """[{name, times, items}] straight from AUTO-MAS's own queue config.
    Read rather than hard-coded, so a queue time changed in AUTO-MAS is the time
    the relay watches.
    """
    if not automas_dir:
        return []
    cfg_dir = Path(automas_dir) / "config"
    return _queues(cfg_dir) if cfg_dir.is_dir() else []


_OKWW_PO_CACHE: dict[str, str] | None = None


def _okww_zh(okww_dir: Path | None) -> dict[str, str]:
    """OK-WW's own official Simplified Chinese translation table (msgid -> msgstr),
    from its ok.po. Reports carry no English task names, and no translation is
    made up here. Cached for the process.
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


# The key for the 「刷满所有梦魇巢穴」 entry in OK-WW's additional-task list. The
# nest line uses it to write 「刷到打满」 and the additional-task line drops it.
_NEST_FULL = "Auto Farm all Nightmare Nest"


def _okww_farm_bit(daily: dict, zh: dict[str, str]) -> str:
    """The stamina line: which instance tomorrow's stamina goes into, and what it
    yields. "" means the line is omitted.
    """
    from ark_relay.features.verify import collector_okww  # noqa: PLC0415 - reuse of the forgery name table, kept in one place
    # The hand-set "no stamina farm" flag wins over every configured value: the
    # patched OK-WW skips stamina entirely while it is there.
    from ark_relay.core.config import no_stamina_farm  # noqa: PLC0415
    if no_stamina_farm():
        return "⚠️ 今天不刷体力：「不刷体力」的开关开着，波片会一直涨到上限。关掉这个开关才恢复"
    which = daily.get("Which to Farm") or ""
    # Forgery and tacet names come from the shared tables (wuwa_forgery /
    # wuwa_tacet), always 1-based like the in-game F2 list.
    from ark_relay.core import wuwa_forgery, wuwa_tacet  # noqa: PLC0415 - avoids an import cycle
    if which == "Forgery Challenge":
        idx = int(daily.get("Which Forgery Challenge to Farm") or 1)
        return f"体力刷 {wuwa_forgery.label(idx)}，出 {wuwa_forgery.reward(idx)}"
    if which == "Tacet Suppression":
        idx = int(daily.get("Which Tacet Suppression to Farm") or 1)
        return f"体力刷 {wuwa_tacet.label(idx)}，出 {wuwa_tacet.reward(idx)}"
    if which == "Simulation Challenge":
        tgt = str(daily.get("Material Selection") or "")
        tgt_zh = collector_okww._SIM_ZH.get(tgt, zh.get(tgt, tgt))
        return f"体力刷 模拟领域·{tgt_zh}" if tgt_zh else "体力刷 模拟领域"
    if which:
        return f"体力刷 {zh.get(which, which)}"
    return ""


def _okww_nest_bit(daily: dict, nest: dict, adds: list[str],
                   zh: dict[str, str]) -> str:
    """The tacet nest line: which spots get fought, and how far. "" means the line
    is omitted.

    Three config keys decide it: the farm-to-full entry in the additional-task
    list, the daily-echo checkbox in the daily task, and the nest task's own spot
    range.
    """
    nest_label = zh.get("Tacet Discord Nest", "残像聚落")
    # The 「自动刷所有梦魇巢穴」 entry only decides between farming to full and
    # stopping after one echo; the spots farmed come from the nest task's own
    # options. So it is folded into this line, not listed as an additional task.
    scope = (nest.get("Only Farm These Nests") or "").strip()
    # 「Only Farm These Nests」 is read only by the patched OK-WW: when the nest
    # patch is not in place, every nest is farmed whatever the config says, and
    # the line says that.
    import os as _os  # noqa: PLC0415
    from ark_relay.features.okww_patch.okww_patch import nest_patch_present  # noqa: PLC0415
    patched = nest_patch_present(_os.environ.get("ARK_OKWW_DIR"))
    if scope and patched is False:
        where = f"⚠️ 本该只打{scope}，但巢穴补丁没贴上，实际会刷全部点位"
    else:
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

    Reads FarmEchoTask.json and the relay's weekly-boss bookkeeping to tell
    whether the 「传送刷 4C 声骸」 entry farms echoes or is used by the
    weekly-boss patch.
    """
    # 「Teleport and Farm 4C Echo」 is used by the weekly-boss patch: when
    # FarmEchoTask's Teleport to Boss = Weekly Challenge it collects the weekly
    # boss reward rather than farming echoes, so the line names the weekly boss.
    farm_f = cfg_dir / "FarmEchoTask.json"
    unreadable = False
    try:
        farm_cfg = json.loads(farm_f.read_text(encoding="utf-8")) if farm_f.is_file() else {}
        _last_error.pop("farm", None)
    except (OSError, ValueError) as exc:
        # Unread, the slot may be the weekly boss or the echo farm, so it is
        # named as unreadable.
        _say_once("farm", exc, "鸣潮 FarmEchoTask.json 读不到（%s），明日安排那一项写成「周本/4C 设置读不到」",
                  exc)
        farm_cfg, unreadable = {}, True
    weekly = str(farm_cfg.get("Teleport to Boss") or "") == "Weekly Challenge"
    rest = []
    for a in adds:
        if a == _NEST_FULL:
            continue
        if a == "Teleport and Farm 4C Echo" and unreadable:
            rest.append("周本/4C 设置读不到")
        elif a == "Teleport and Farm 4C Echo" and weekly:
            lvl = str(farm_cfg.get("Boss Level") or "")
            idx = int(farm_cfg.get("Which Weekly Boss to Teleport") or 1)
            done, nm = _weekly_boss_state()
            label = f"周本 {nm or f'战歌重奏第 {idx} 个'}" + (f"（{lvl} 级）" if lvl else "")
            # Once the week's quota is full the line says it will not be fought.
            rest.append(label + ("，本周打没打满读不到" if done is None
                                 else "，本周已打满，明天不打" if done else "，明天会打"))
        else:
            rest.append(zh.get(str(a), str(a)))
    if rest:
        shown = "、".join(rest[:2])
        if len(rest) > 2:
            shown += f" 等 {len(rest)} 项"
        return "附加 " + shown
    # No additional tasks: no line at all.
    return ""


def _okww_plan_bits(automas_dir: Path | None,
                    okww_dir: Path | None = None) -> list[str]:
    """What OK-WW will farm tomorrow, read from the master config that takes
    effect: `<automas>/data/<script id>/Default/ConfigFile/` (copied wholesale to
    OK-WW before each run), with the quick-config overrides on top.
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
        # the AUTO-MAS user config, so the master's values are not the ones that run.
        quick = _okww_quick_overrides(automas_dir)
        if isinstance(quick, dict):
            daily = {**daily, **quick}

        zh = _okww_zh(okww_dir)
        adds = [str(a) for a in (daily.get(
            "Additional Tasks to Run After Daily Task") or [])]
        # Unread, the quick config may replace the master's additional tasks, so
        # the master's list is not shown.
        extra = ("附加任务读不到" if quick is _UNREADABLE
                 else _okww_extra_bit(d, adds, zh))
        return [b for b in (_okww_farm_bit(daily, zh),
                            _okww_nest_bit(daily, nest, adds, zh),
                            extra) if b]
    return []


def _weekly_boss_state() -> "tuple[bool | None, str]":
    """(quota full this week?, boss name) - reads the relay's own weekly-boss
    bookkeeping (the weeklyboss module). None: it could not be read, which is
    neither 「明天会打」 nor 「本周已打满」."""
    try:
        import os  # noqa: PLC0415
        from ark_relay.features.weekly.weeklyboss import WeeklyBossGate  # noqa: PLC0415
        state = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
        v = WeeklyBossGate(state).settings()
    except Exception as exc:  # noqa: BLE001
        _say_once("weekly_boss", exc, "周本记账读不到（%s），明日安排写「本周打没打满读不到」", exc,
                  exc_info=True)
        return None, ""
    _last_error.pop("weekly_boss", None)
    return bool(v.get("本周已打")), str(v.get("名字") or "")


# _okww_quick_overrides: ScriptConfig.json exists but cannot be read, so it is
# unknown whether quick config is on.
_UNREADABLE = object()


def _okww_quick_overrides(automas_dir: Path | None) -> "dict | None | object":
    """The keys AUTO-MAS's 「快速配置」 (quick config) actually pushes to OK-WW.

    None means quick config is off (the master config takes effect as written).
    _UNREADABLE means ScriptConfig.json could not be read.
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
    except (OSError, ValueError) as exc:
        _say_once("quick", exc, "AUTO-MAS ScriptConfig.json 读不到（%s），明日安排鸣潮写「附加任务读不到」", exc)
        return _UNREADABLE
    _last_error.pop("quick", None)
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
        # The top level mixes script nodes with lists and other values.
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

    AutoCollect runs only on its selected weekdays and takes about half an hour,
    so the plan says whether tomorrow is one of them.
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
            routes = _collect_route_count(t.get("optionValues") or {})
            if when.weekday() in picked:
                return [f"⏳ 先跑自动采集（{routes} 条路线，上次实测 33 分钟）"]
            return [f"自动采集仅 {label} 跑"]
    return []


def _annihilation_reopens(automas_dir) -> str:
    """The value the weekly gate will restore tomorrow, or "".

    The gate reopens annihilation at the first boot of a new week, so on a
    "Close" switch the plan says what it will be tomorrow. Mirrors
    WeeklyGate.maybe_reopen: it restores only a week it recorded closing itself.
    """
    from ark_relay.features.weekly.annihilation import DEFAULT_WHEN_UNKNOWN, WeeklyGate, week_key  # noqa: PLC0415
    try:
        state = WeeklyGate(Path(os.environ.get("ARK_STATE_DIR", "./ark-state")),
                             automas_dir)._load()
    except Exception as exc:  # noqa: BLE001
        # "" makes the plan say 「剿灭 本周已完成/关闭」.
        _say_once("annihilation", exc, "剿灭周记账读不到，明日安排里剿灭只按开关现状写，看不出新一周会不会自动恢复",
                  exc_info=True)
        return ""
    _last_error.pop("annihilation", None)
    done = state.get("done_week")
    tomorrow_noon = _tomorrow().replace(hour=12, minute=0, second=0, microsecond=0)
    if done and done != week_key(tomorrow_noon):
        return state.get("restore_to") or DEFAULT_WHEN_UNKNOWN
    return ""


def _collect_route_count(ov: dict) -> int:
    """Routes the gathering task will walk, from the master's option values.

    Counts the old single AutoCollectRoutes list plus the per-region lists
    (AutoCollect<Region><Rare|Common>Routes), each region only when its own
    AutoCollect<Region> switch is not off.
    """
    total = len((ov.get("AutoCollectRoutes") or {}).get("caseNames") or [])
    for key, val in ov.items():
        m = re.fullmatch(r"AutoCollect(\w+?)(?:Rare|Common)Routes", key)
        if not m:
            continue
        switch = ov.get(f"AutoCollect{m.group(1)}")
        if isinstance(switch, dict) and switch.get("value") is False:
            continue
        total += len((val or {}).get("caseNames") or [])
    return total


def _tomorrow():
    """Tomorrow in the server timezone. The plan is about that day, not today."""
    return datetime.now(SERVER_TZ) + timedelta(days=1)


# The plan shows game names, not tool names.
_GAME_OF = GAME_ZH                 # features/run/runwatch.py reads plan._GAME_OF


def maintenance_lines(day) -> list[str]:
    """Server-maintenance notices for `day`, for tomorrow's plan."""
    try:
        from datetime import datetime as _dt  # noqa: PLC0415
        from ark_relay.features.maintenance import maintenance  # noqa: PLC0415
        from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
        at = _dt(day.year, day.month, day.day, 8, 46, tzinfo=SERVER_TZ)
        wins = maintenance.today(at)
    except Exception as exc:  # noqa: BLE001
        # A site that did not answer is WARNed inside maintenance.today; this is
        # anything else, and without it the plan reads as "no maintenance".
        _say_once("maintenance", exc, "明日安排的停服维护那一行没算出来，这次不写", exc_info=True)
        return []
    _last_error.pop("maintenance", None)
    return [f"⚠️ {game} {start:%m-%d %H:%M}–{end:%H:%M} 停服维护：当天队列里不跑它，"
            f"队列跑完立刻更新客户端，{end:%H:%M} 开服后单独补跑"
            for game, (start, end, _why) in wins.items()]


# The annihilation field's values are an English enum (Annihilation /
# Chernobog@Annihilation, ...); the Chinese names exist only inside the AUTO-MAS
# frontend bundle (resources/app.asar), read here.
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
    # A cache of derived data, rebuilt when lost; a file of its own, not state.json.
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
    from ark_relay.core.config import SERVER_TZ as _TZ  # noqa: PLC0415
    lines += maintenance_lines((_dt.now(tz=_TZ) + _td(days=1)).date())
    for q in queues:
        for t in q["times"]:
            lines.append(f"🕘 {t}　东京 {_tokyo(t)}")
        for uid in q["items"]:
            s = scripts.get(uid) or {}
            bits = []
            if s.get("fight") is False:
                # Combat off: no stage is farmed tomorrow.
                bits.append("不刷关卡（只做日常）")
            elif s.get("stage"):
                mode = "固定" if s.get("stage_mode") == "Fixed" else s.get("stage_mode", "")
                bits.append(f"理智 {s['stage']}" + (f"（{mode}）" if mode else ""))
            if (anni := s.get("annihilation")):
                # "Close" is how the weekly gate leaves the switch after a pass,
                # and also how it looks when closed by hand (then nothing reopens
                # it). The values are an English enum; the Chinese names come
                # from the AUTO-MAS frontend bundle.
                zh = {}
                try:
                    zh = _asar_value_labels(automas_dir, Path(os.environ.get(
                        "ARK_STATE_DIR", "./ark-state")))
                except Exception:  # noqa: BLE001
                    pass
                reopen = _annihilation_reopens(automas_dir) if anni == "Close" else ""
                if reopen:
                    bits.append(f"剿灭 {zh.get(reopen, reopen)}（新一周自动恢复）")
                else:
                    bits.append("剿灭 本周已完成/关闭" if anni == "Close"
                                else f"剿灭 {zh.get(anni, anni)}")
            if (med := s.get("medicine")) is not None:
                # AUTO-MAS stores "use as many as you have" as 999.
                bits.append("理智药不限" if int(med) >= 999
                            else ("不吃理智药" if int(med) <= 0 else f"理智药 {med} 个"))
            if s.get("kind") == "MaaEnd":
                # AUTO-MAS's SanityTaskType is only the tab; sanity_plan resolves
                # which item the chain actually farms.
                from ark_relay.features.weekly import sanity_plan  # noqa: PLC0415 - avoids a cycle
                if label := sanity_plan.read(automas_dir).get("label"):
                    bits.append(f"理智用于 {label}")
                bits += _maaend_extra_bits(s.get("path"), _tomorrow())
            elif s.get("sanity_use"):
                bits.append(f"理智用于 {s['sanity_use']}")
            if s.get("kind") == "OK-WW":
                bits += _okww_plan_bits(automas_dir, s.get("path"))
            # One thing per line: a phone wraps one long line into several.
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

    Two bounds:

    A queue that just became due may still be working through its items, and
    between two of them no game process exists at all (one has exited, the
    next is still launching). The shutdown guard uses this list so the machine
    does not power off in that gap.

    The wait is not open-ended: a script that never runs (crashed, game would
    not start) is written off once the window has passed.
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
            # Yesterday's occurrence too: a 21:30 queue is still inside its
            # window at 00:10.
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
    maintained by the MAA resource repo and OTA-updated), so the relay holds no
    copy of event dates. Empty string when anything is missing.

    An event that ended within _EXPIRED_REMINDER gets a reminder to clear out
    the event shop, with how long the reminder keeps showing; older ones are
    dropped.
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
            # Only a recently ended event gets the reminder (the cache keeps
            # whole past events); it says how long it will keep showing.
            if left >= -_EXPIRED_REMINDER:
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

    AUTO-MAS already knows each script's install path, so it is not configured
    a second time.
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
