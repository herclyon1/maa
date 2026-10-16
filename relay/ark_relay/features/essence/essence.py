"""MaaEnd's essence farming (基质刷取, task AutoEssence) in the AUTO-MAS master.

The owner's order, 2026-10-16 16:29 Tokyo (confirmed 17:01; quoted in full in
relay/USER-SWITCHES.txt): farm 唤月 next to 玉中身, and once both are complete switch to
filler mode (刷垫子) with engraving off and any region - the upstream note naming the best
regions is outdated. Two changes, both to the master copy only (AUTO-MAS copies
it over MaaEnd's own config before each run, mastercfg module docstring):

* `pick_weapons` - target mode (AutoEssenceMenu = Target) farms toward exactly the given
  weapons: each weapon-type switch on when one of its weapons is given, off otherwise, and
  that type's list holds exactly the given ones. Run once by hand
  (scripts/mac/lib/maaend_essence_pick.py).
* `to_filler` - filler mode (刷垫子): AutoEssenceMenu = Random, AutoEssenceDoOverride
  (使用刻写券) off, AutoEssenceChooseLocation = every region. The upstream description
  that 藏剑谷 / 清波寨 succeed most often is outdated per the owner; every region is
  ticked. Nothing else in the task changes (领取方式, 循环, 应急理智加强剂 stay).
  The relay does this by itself (`on_record` + `step`) once a MaaEnd record shows target
  mode ending with 「勾选武器的基质均已满足，结束任务」 (raw["maaend_essence_met"],
  collector_maaend._farm_one), and only while the master is still in target mode: the
  master's own mode is the idempotency key, so a later run already in filler mode, or one
  the owner put back in another mode by hand, is left alone until the next such ending.

Every option name, case and default comes from MaaEnd's own definitions
(tasks/AutoEssence/AutoEssence.json, Location/ChooseLocation.json, Target/Target.json,
v2.33.0-rc.1); a definition that is not there refuses the change. A write happens only
when no AUTO-MAS task runs and no make-up or collect retry has a temporary change in the
master; the whole file is read, changed, backed up beside itself
(mxu-MaaEnd.json.bak-essence-<what>-<time>), written atomically and read back whole.
"""
from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.essence")

TASK = "AutoEssence"
MENU = "AutoEssenceMenu"
TARGET = "Target"
RANDOM = "Random"
OVERRIDE = "AutoEssenceDoOverride"
REGIONS = "AutoEssenceChooseLocation"
TYPE_PREFIX = "AutoEssenceWeaponType"

# State store: the SATISFIED record waiting for a safe moment, and the last one handled.
SECTION = "updates"
PENDING = "essence_filler_pending"
DONE_FOR = "essence_filler_done_for"
# Ledger raw key on the SATISFIED record's line once filler mode is set (ledger_rows).
RAW_KEY = "maaend_essence_filler"


class Refused(Exception):
    """The change is not made; the message says why (Chinese, it may reach the group)."""


@dataclass
class Result:
    changed: bool = False
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    note: str = ""            # why nothing changed, or the backup file name
    names: list = field(default_factory=list)   # the target weapons' names, for the report


# ---------------------------------------------------------------- definitions

def _defs(maaend_dir) -> dict:
    from ark_relay.core import mastercfg  # noqa: PLC0415
    opts, _ = mastercfg._maaend_defs(maaend_dir)
    for name in (MENU, OVERRIDE, REGIONS):
        if not opts.get(name):
            raise Refused(f"MaaEnd 的定义里找不到 {name}，不动配置")
    return opts


def _case_names(d: dict) -> list[str]:
    return [str(c.get("name")) for c in (d.get("cases") or []) if c.get("name")]


def _case(d: dict, name: str) -> dict:
    return next((c for c in d.get("cases") or [] if c.get("name") == name), {})


def _weapon_types(opts: dict) -> dict[str, str]:
    """{type switch: its weapon list} from the Target case of AutoEssenceMenu: each
    AutoEssenceWeaponType* switch whose "Yes" case opens one checkbox list."""
    out: dict[str, str] = {}
    for sw in _case(opts[MENU], TARGET).get("option") or []:
        if not str(sw).startswith(TYPE_PREFIX):
            continue
        d = opts.get(sw) or {}
        lists = _case(d, "Yes").get("option") or []
        if d.get("type") != "switch" or len(lists) != 1 or (opts.get(lists[0]) or {}).get("type") != "checkbox":
            raise Refused(f"MaaEnd 的 {sw} 不是「开关 + 一张武器表」的样子，不动配置")
        out[str(sw)] = str(lists[0])
    if not out:
        raise Refused("MaaEnd 的目标选择里找不到武器类型，不动配置")
    return out


def _check_case(opts: dict, name: str, value: str) -> str:
    if value not in _case_names(opts[name]):
        raise Refused(f"MaaEnd 的 {name} 没有 {value} 这一项，不动配置")
    return value


def _task(doc: dict) -> dict:
    from ark_relay.core import mastercfg  # noqa: PLC0415
    task = mastercfg._maaend_task(doc, TASK)
    if task is None:
        raise Refused("母本里没有基质刷取（AutoEssence），不动配置")
    return task


def mode(doc: dict) -> str:
    """The master's AutoEssenceMenu case ('' when it is not set)."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
    task = mastercfg._maaend_task(doc, TASK) or {}
    return str(((task.get("optionValues") or {}).get(MENU) or {}).get("caseName") or "")


def _switch(ov: dict, key: str) -> bool:
    return bool((ov.get(key) or {}).get("value"))


def _picked(ov: dict, types: dict[str, str]) -> dict[str, list[str]]:
    """{weapon list: ticked ids} for the type switches that are on."""
    return {lst: list((ov.get(lst) or {}).get("caseNames") or [])
            for sw, lst in types.items() if _switch(ov, sw)}


# ---------------------------------------------------------------- the two changes (pure)

def pick_weapons(doc: dict, opts: dict, ids: list[str]) -> Result:
    """Target mode farms toward exactly `ids`. Refused unless the master is in target mode."""
    task = _task(doc)
    ov = task.setdefault("optionValues", {})
    if (cur := mode(doc)) != TARGET:
        raise Refused(f"基质刷取现在不是「目标选择」（是 {cur or '没设'}），不动武器")
    types = _weapon_types(opts)
    want: dict[str, list[str]] = {}
    for wid in ids:
        lst = next((lst for lst in types.values() if wid in _case_names(opts[lst])), None)
        if lst is None:
            raise Refused(f"MaaEnd 的武器表里没有 {wid}，不动配置")
        if wid not in want.setdefault(lst, []):
            want[lst].append(wid)
    if not want:
        raise Refused("一把武器都没给，不动配置")
    res = Result(before={"weapons": _picked(ov, types)})
    for sw, lst in types.items():
        on = lst in want
        if _switch(ov, sw) != on or (ov.get(sw) or {}).get("type") != "switch":
            ov[sw] = {"type": "switch", "value": on}
        if on and (ov.get(lst) or {}).get("caseNames") != want[lst]:
            # Created when missing: with the switch on and no list, MaaEnd would take
            # the definition's default, every ★6 weapon of the type (Target.json).
            ov[lst] = {"type": "checkbox", "caseNames": list(want[lst])}
    res.after = {"weapons": _picked(ov, types)}
    return res


def to_filler(doc: dict, opts: dict) -> Result:
    """Filler mode, from target mode only; anything else is left as it is."""
    task = _task(doc)
    ov = task.setdefault("optionValues", {})
    cur = mode(doc)
    types = _weapon_types(opts)
    res = Result(before={MENU: cur, OVERRIDE: _switch(ov, OVERRIDE),
                         REGIONS: list((ov.get(REGIONS) or {}).get("caseNames") or [])},
                 names=[w for ws in _picked(ov, types).values() for w in ws])
    if cur != TARGET:
        res.after = dict(res.before)
        res.note = ("基质刷取已经是随机模式，不用再切" if cur == RANDOM
                    else f"基质刷取现在是 {cur or '没设'}，不是目标选择，不动")
        return res
    regions = _case_names(opts[REGIONS])
    if not regions:
        raise Refused(f"MaaEnd 的 {REGIONS} 一个地区都没有，不动配置")
    ov[MENU] = {"type": "select", "caseName": _check_case(opts, MENU, RANDOM)}
    ov[OVERRIDE] = {"type": "switch", "value": False}
    ov[REGIONS] = {"type": "checkbox", "caseNames": regions}
    res.after = {MENU: RANDOM, OVERRIDE: False, REGIONS: regions}
    return res


# ---------------------------------------------------------------- the file

def busy(cfg, scripts_running) -> str:
    """Why the master must not be written now; '' when it may."""
    from ark_relay.features.makeup import collect_retry, makeup  # noqa: PLC0415
    if scripts_running():
        return "AUTO-MAS 还有任务在跑"
    if "MaaEnd" in makeup.in_flight(cfg.state_dir):
        return "终末地补跑还没跑完"
    if makeup._narrow_file(cfg.state_dir).exists() or collect_retry._narrow_file(cfg.state_dir).exists():
        return "补跑或采集重试临时改过的母本还没改回"
    return ""


def apply(cfg, change, tag: str, *args) -> Result:
    """Read the master, run `change(doc, opts, *args)`, and when it changed something
    back the file up, write it and read it back whole. Raises Refused."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
    f = mastercfg.maaend_master(cfg.automas_dir) if cfg.automas_dir else None
    if not f or not f.is_file():
        raise Refused("找不到 MaaEnd 的母本")
    raw = f.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    orig = copy.deepcopy(doc)
    res = change(doc, _defs(cfg.maaend_dir), *args)
    if doc == orig:
        res.changed = False
        res.note = res.note or "母本本来就是这样，没有改动"
        return res
    bak = f.with_name(f"{f.name}.bak-essence-{tag}-{datetime.now(tz=SERVER_TZ).strftime('%Y%m%d-%H%M%S')}")
    bak.write_bytes(raw)
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    try:
        back = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"写进去之后读不出来（{type(exc).__name__}），{bak.name} 是原样") from exc
    if back != doc:
        raise Refused(f"写进去之后读出来和写的不一样，{bak.name} 是原样")
    res.changed = True
    res.note = bak.name
    return res


def weapon_names(maaend_dir, ids: list[str]) -> list[str]:
    """Chinese names from MaaEnd's own language pack (iconRecognition.name.<id>); an id
    it does not name stays as it is."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
    table = mastercfg._Locale(Path(maaend_dir) if maaend_dir else None).table
    return [str(table.get(f"iconRecognition.name.{w}") or w) for w in ids]


# ---------------------------------------------------------------- the relay's part

def _store(eng):
    return eng.state.store


def on_record(eng, rec, day: str) -> None:
    """A MaaEnd record whose essence task ended with every ticked weapon satisfied:
    remember it, so `step` switches to filler mode at the next safe moment. `day` is
    the ledger day the record is booked on (records.run_day)."""
    raw = rec.raw or {}
    if rec.script != "MaaEnd" or not raw.get("maaend_essence_met") or raw.get("manual_stop"):
        return
    st = _store(eng)
    if st.get(SECTION, DONE_FOR) == rec.run_id:
        return              # this record was already acted on (a replayed record)
    st.set(SECTION, PENDING, {"run_id": rec.run_id, "day": day,
                              "at": datetime.now(tz=SERVER_TZ).isoformat()})
    log.info("基质刷取：%s 勾选的武器基质都已齐，等没有任务在跑时切成随机地区刷垫子", rec.run_id)


def step(eng, now: datetime | None = None) -> None:
    """Engine tick step: carry out a pending switch to filler mode when it is safe."""
    st = _store(eng)
    pending = st.get(SECTION, PENDING)
    if not isinstance(pending, dict) or not pending.get("run_id"):
        return
    cfg = eng.cfg
    if why := busy(cfg, eng._scripts_running):
        if why != getattr(eng, "_essence_wait_note", ""):
            eng._essence_wait_note = why
            log.info("基质刷取：切刷垫子等着（%s）", why)
        return
    eng._essence_wait_note = ""
    run_id = str(pending["run_id"])
    try:
        res = apply(cfg, to_filler, "filler")
    except Exception as exc:  # noqa: BLE001 - Refused or a broken file: said once, not retried
        st.pop(SECTION, PENDING)
        st.set(SECTION, DONE_FOR, run_id)
        why = str(exc) if isinstance(exc, Refused) else f"{type(exc).__name__}: {exc}"
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        body = texts.essence_filler_failed(why)
        log.warning("%s", body, extra=errwatch.alarm(texts.ESSENCE_FILLER_FAILED, body))
        return
    st.pop(SECTION, PENDING)
    st.set(SECTION, DONE_FOR, run_id)
    if not res.changed:
        log.info("基质刷取：%s 之后没切（%s）", run_id, res.note)
        return
    names = weapon_names(cfg.maaend_dir, res.names)
    eng.state.mark_raw(str(pending.get("day") or ""), run_id, RAW_KEY,
                       {"at": (now or datetime.now(tz=SERVER_TZ)).isoformat(), "weapons": names})
    log.info("基质刷取：已切成随机地区刷垫子、刻写券关了（%s 之后；%s → %s；原文件备份为 %s）",
             run_id, res.before, res.after, res.note)
