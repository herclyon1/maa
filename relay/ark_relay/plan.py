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

from .config import SERVER_TZ, USER_TZ

log = logging.getLogger("ark.plan")

# 活动结束后这条提醒还出现多久。MAA 的活动缓存会把早已过期的活动一直留着
# （"红丝绒" 几个月前就没了还在里面），所以必须有窗口；三天足够跨过一个周末，
# 又不至于变成常驻噪声。提醒正文会写出剩余时长，免得看起来像卡住了。
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
    # 路径是 D:\ark\okww，里面没有 "maa"——2026-08-27 之前这里返回空串，
    # 明日安排里 OK-WW 那行因此永远是光秃秃的一个名字。
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
    """OK-WW 自带的官方简体中文译文表（msgid → msgstr）。

    汇报里不该出现英文任务名。2026-08-27 的明日安排写着
    「附加 Check Weekly Garden、Merge Echo If discar」，既是英文又被截断。
    译文用**它自己的语言包**，不自己编——`Tacet Discord Nest` 官方译作
    「残像聚落」，我先前凭感觉写成「无音区巢穴」就是错的。
    """
    global _OKWW_PO_CACHE
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


def _okww_plan_bits(automas_dir: Path | None,
                    okww_dir: Path | None = None) -> list[str]:
    """明日 OK-WW 会刷什么，从真正生效的母本配置里读出来。

    2026-08-27 的日报里 OK-WW 那行是光秃秃的「· OK-WW」——用户看不到
    明天要刷哪个副本、打不打残象聚落。信息就在
    `<automas>/data/<脚本id>/Default/ConfigFile/` 里（跑之前会整个复制给
    OK-WW 的那份母本），读它，不读会被覆盖的 OK-WW 自带配置。
    """
    if not automas_dir:
        return []
    root = Path(automas_dir) / "data"
    if not root.is_dir():
        return []
    from . import collector  # noqa: PLC0415 - 复用凝素领域的名字表，避免两处维护
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
        # 快速配置会用 AUTO-MAS 用户配置里的 Task.* 覆盖掉母本的对应键，
        # 所以母本里的附加任务清单**不是**实际会跑的那一份。
        # 2026-08-27 的明日安排里因此列出了三个根本不会执行的附加任务。
        quick = _okww_quick_overrides(automas_dir)
        if quick is not None:
            daily = {**daily, **quick}

        zh = _okww_zh(okww_dir)
        bits: list[str] = []
        which = daily.get("Which to Farm") or ""
        if which == "Forgery Challenge":
            idx = int(daily.get("Which Forgery Challenge to Farm") or 1)
            name = collector._FORGERY_NAMES.get(idx - 1, f"#{idx}")
            bits.append(f"体力刷 凝素领域·{name}")
        elif which == "Tacet Suppression":
            idx = int(daily.get("Which Tacet Suppression to Farm") or 1)
            bits.append(f"体力刷 {zh.get(which, which)} #{idx}")
        elif which == "Simulation Challenge":
            tgt = str(daily.get("Material Selection") or "")
            tgt_zh = collector._SIM_ZH.get(tgt, zh.get(tgt, tgt))
            bits.append(f"体力刷 模拟领域·{tgt_zh}" if tgt_zh else "体力刷 模拟领域")
        elif which:
            bits.append(f"体力刷 {zh.get(which, which)}")
        nest_label = zh.get("Tacet Discord Nest", "残像聚落")
        adds = [str(a) for a in (daily.get(
            "Additional Tasks to Run After Daily Task") or [])]
        # 「自动刷所有梦魇巢穴」这个勾其实只决定走刷满还是走抓一个声骸就停，
        # 刷什么范围由巢穴任务自己的两个选项管。所以不能原样列成一条附加任务：
        # 上一行刚说「只打落渊南丘」，下一行再来个「附加 自动刷所有梦魇巢穴」，
        # 自相矛盾。把它折进巢穴那一行，写它真正的效果。
        FULL = "Auto Farm all Nightmare Nest"
        scope = (nest.get("Only Farm These Nests") or "").strip()
        where = f"只打{scope}" if scope else "全部点位"
        if FULL in adds:
            bits.append(f"{nest_label} {where}，刷到打满")
        elif daily.get("Farm Nightmare Nest for Daily Echo"):
            bits.append(f"{nest_label} {where}，只取一个每日声骸就停")
        elif scope:
            bits.append(f"{nest_label} {where}（未满才打）")
        # 「Teleport and Farm 4C Echo」在我们这里被周本补丁征用：FarmEchoTask 的
        # Teleport to Boss = Weekly Challenge 时，它跑的是周本领奖，不是刷声骸。
        # 用户 2026-09-02：「我敢百分百确定鸣潮没有传送刷取 4C 的任务」——写周本。
        farm_f = d / "FarmEchoTask.json"
        try:
            farm_cfg = json.loads(farm_f.read_text(encoding="utf-8")) if farm_f.is_file() else {}
        except (OSError, ValueError):
            farm_cfg = {}
        weekly = str(farm_cfg.get("Teleport to Boss") or "") == "Weekly Challenge"
        rest = []
        for a in adds:
            if a == FULL:
                continue
            if a == "Teleport and Farm 4C Echo" and weekly:
                lvl = str(farm_cfg.get("Boss Level") or "")
                idx = int(farm_cfg.get("Which Weekly Boss to Teleport") or 1)
                done = _weekly_boss_done()
                label = f"周本 战歌重奏 第 {idx} 个" + (f"（{lvl} 级）" if lvl else "")
                # 用户 2026-09-02：「不是说都刷完了吗？」——本周已打满就明说明天不打
                rest.append(label + ("，本周已打满，明天不打" if done else "，明天会打"))
            else:
                rest.append(zh.get(str(a), str(a)))
        if rest:
            shown = "、".join(rest[:2])
            if len(rest) > 2:
                shown += f" 等 {len(rest)} 项"
            bits.append("附加 " + shown)
        # 没有附加任务就不写——「无附加任务」这一行不携带任何信息。
        return bits
    return []


def _weekly_boss_done() -> bool:
    """周本本周是否已打满——读中继自己的周本记账（weeklyboss 模块）。"""
    try:
        import os  # noqa: PLC0415
        from .weeklyboss import WeeklyBoss  # noqa: PLC0415
        state = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
        return bool(WeeklyBoss(state / "weekly-boss.json", None).settings().get("本周已打"))
    except Exception:  # noqa: BLE001
        return False


def _okww_quick_overrides(automas_dir: Path | None) -> dict | None:
    """AUTO-MAS「快速配置」实际下发给 OK-WW 的那几个键。

    返回 None 表示没开快速配置（母本原样生效）。
    键名对照抄自 `app/task/Okww/AutoProxy.py`，改那边时这里要跟着改。
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
        # 顶层不全是脚本节点，还混着列表之类的东西——2026-08-27 实测
        # 直接 .get() 会 AttributeError，把整份明日安排打断。
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
    """MaaEnd 那一轮除了日常之外还会跑什么——目前只关心自动采集。

    2026-08-27 用户在 MaaEnd 里给 AUTO-MAS 实例加了 AutoCollect，排在第一位，
    实测跑了 33 分钟。它只在选中的星期跑，而明日安排此前完全看不出这件事：
    到了那天早班会毫无预兆地多花半小时，理智药和协议空间全被推后。
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
    """服务器时区的明天。明日安排讲的是那一天，不是今天。"""
    return datetime.now(SERVER_TZ) + timedelta(days=1)


# 排班里显示的是游戏名，不是工具名。用户 2026-08-31：「那个排班搞好看一点」。
# 他关心的是哪个游戏明天干什么，MAA / MaaEnd / OK-WW 是实现细节。
_GAME_OF = {"MAA": "明日方舟", "MaaEnd": "终末地", "OK-WW": "鸣潮"}


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
    for q in queues:
        for t in q["times"]:
            lines.append(f"🕘 {t}　东京 {_tokyo(t)}")
        for uid in q["items"]:
            s = scripts.get(uid) or {}
            bits = []
            if s.get("stage"):
                mode = "固定" if s.get("stage_mode") == "Fixed" else s.get("stage_mode", "")
                bits.append(f"理智 {s['stage']}" + (f"（{mode}）" if mode else ""))
            if (anni := s.get("annihilation")):
                # Worth a line of its own. "Close" is how the weekly gate
                # leaves the switch after a pass, and it is also how it looks
                # when somebody closed it by hand - in which case nothing will
                # ever reopen it, because the gate only restores a week it
                # recorded closing itself. Either way the weekly reward is not
                # being collected, and silence about that costs a reward a week.
                # 值是英文枚举（Annihilation / Chernobog@Annihilation …），
                # 中文在 AUTO-MAS 前端的打包产物里。汇报里不该出现英文——
                # 2026-08-31 用户在手机上看到「剿灭 Annihilation」。
                from .phone import _asar_value_labels  # noqa: PLC0415
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
                # as the answer and is not one - "干员养成" does not say whether
                # that means 经验 or 进阶, and the reward set decides which item
                # actually drops. Report the resolved chain instead.
                from . import sanity_plan  # noqa: PLC0415 - avoids a cycle
                if label := sanity_plan.read(automas_dir).get("label"):
                    bits.append(f"理智用于 {label}")
                bits += _maaend_extra_bits(s.get("path"), _tomorrow())
            elif s.get("sanity_use"):
                bits.append(f"理智用于 {s['sanity_use']}")
            if s.get("kind") == "OK-WW":
                bits += _okww_plan_bits(automas_dir, s.get("path"))
            # 一行一件事。原来是「· MAA　理智 1-7 · 剿灭 … · 理智药不限」，
            # 同一个「·」既当项目符号又当分隔符，手机上一行折成三行看不清。
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
    cost the 终月地 half of 2026-08-16.

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
                gone = _EXPIRED_REMINDER + left           # 还剩多久不再提
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
