"""One make-up run, the way a person would do it, before a MAA / MaaEnd failure is called final.

The user asked for one thing only (2026-10-05 13:07): 「中继我就要求一个，他不要再报错了……
几乎就是遇到一点小毛病就停下来报错」 - it stopped at every small glitch. Until then
a MAA or MaaEnd failure that outlived AUTO-MAS's own three attempts went
straight to the group as 「最终失败」
(handle._flush_pending). 2026-09-25: MaaEnd's 送礼 / 基质刷取 / 日常奖励 failed
3/3 and the group got an alarm, although a fresh game and one more go is all
anyone would have done about it.

So, once the queue is idle:

* MaaEnd: the user's own master (mxu-MaaEnd.json) runs again as it is - the
  game is closed and the MaaEnd script is dispatched through AUTO-MAS once.
  Nothing the user switched on is switched off for it (the user, 2026-10-06:
  「我开的任务是谁说要关的」). Until then the master was narrowed to the failed
  tasks; there is no other way to run a chosen set through AUTO-MAS: its
  dispatch takes a script and a mode only (commands.run_script), and before
  every attempt it copies the whole master into MaaEnd (docs/AUTOMAS.md,
  「Master copy vs the script's own copy」). The one change: when a failure's
  cause is a full bag (collector_maaend.BAG_FULL, the storage-full notice seen
  after the claim) and the master has 存放背包 (StashBackpack), that task is
  switched on and moved in front of the first enabled task, so the bag is
  cleared before anything claims; its own switch and place go back when the
  make-up's record lands (handle._handle), at the top of every `maybe_run`,
  and at boot (unless the make-up is still running). A full copy of the master
  is kept beside the saved flags; when the flags cannot be read the copy goes
  back instead, and when neither can be read the group gets one real alarm and
  no make-up touches the master again until a person has looked
  (restore-failed.json). The same restore puts back a narrowing left behind by
  the code before 2026-10-06.
* MAA: there is no single-task path, so the whole MAA script runs again - but
  only when the failed run never got going (only 开始唤醒 / emulator /
  connection failures, and no fight, drop, sanity or potion on record). MAA's
  MedicineNumb counts per run: a second whole run after one that fought eats
  another round of sanity potions (2026-09-01, commands.run_script). Any other
  MAA failure gets no make-up and goes to the group at once (unresolved.py).

At most one make-up per script per day (state/makeup/<day>.json). A dispatch
that never got going (AUTO-MAS unreachable, API refused) is `couldnt_run` and
is tried again, up to MAX_TRIES. The daily report carries one line on the
make-up (report.makeup_line). Every failure reaches the group once its make-up
is over: one that did not go through - or a failure that got none - as
「没跑成」 (unresolved.py; the user, 15:38: 「为啥群里不响？你们不是没处理好吗？」),
one that went through as 「失败过，补跑后走通了」 (until 2026-10-06 that one was the
daily report's alone, and the others rang once per game per shift; the user's
order of that day, every error every time: 「不论多少次什么错误都要发」).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.makeup")

SCRIPTS = ("MAA", "MaaEnd")
MAX_TRIES = 3
# A dispatch that did not take is retried no sooner than this.
RETRY_GAP_S = 120
# A dispatched make-up that has neither produced a record nor been seen running
# for this long never ran (AUTO-MAS took the order and did nothing with it).
STALE_MIN = 10
# A record this much older than the dispatch can still be the make-up's: the log's
# first line and the dispatch moment come from two clocks on the same machine.
SLACK = timedelta(minutes=2)
STASH = "StashBackpack"
GAME_EXE = "Endfield.exe"
# What a MaaEnd make-up runs, for the marker and the daily report's line.
WHOLE_MAAEND = "按原设置整轮再跑"

# Results kept in the marker. `couldnt_run` is the only one that does not count
# as today's attempt.
DISPATCHED, COULDNT_RUN, GAVE_UP, OK, FAILED, NO_RECORD = (
    "dispatched", "couldnt_run", "gave_up", "ok", "failed", "no_record")
# AUTO-MAS retries a failed attempt at once (the next attempt's log starts
# seconds after the last one ends, collector._TRANSITIONAL); a record starting
# this soon after the booked one's end is the make-up's own retry, anything
# later (the evening queue) is not the make-up.
RETRY_CHAIN = timedelta(minutes=10)

# MAA's whole script is re-run only after a run that never got going. Every
# failure has to read as one of these (AUTO-MAS's 「MAA 未能正确登录 PRTS」 is
# the StartUp task, 开始唤醒, failing), and the record must carry none of
# collector_maa's evidence of work.
MAA_NOT_STARTED = ("开始唤醒", "StartUp", "未能正确登录", "模拟器", "连接", "ADB", "adb")
MAA_WORK_KEYS = {"drop_statistics": "有掉落", "sanity_spent": "花过理智", "medicine_used": "吃过理智药",
                 "run_times": "打过关", "stages": "进过关卡", "annihilation_progress": "打过剿灭"}


# ------------------------------------------------------------------ marker

def _dir(state_dir) -> Path:
    return Path(state_dir) / "makeup"


def _marker_file(state_dir, day: str) -> Path:
    return _dir(state_dir) / f"{day}.json"


def read_marker(state_dir, day: str) -> dict:
    """{script: {...}} for the day, {} when there is none or it cannot be read."""
    if not state_dir:
        return {}
    try:
        d = json.loads(_marker_file(state_dir, day).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write_marker(state_dir, day: str, data: dict) -> None:
    f = _marker_file(state_dir, day)
    f.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(f, json.dumps(data, ensure_ascii=False, indent=1))


def _day(t: datetime) -> str:
    return t.astimezone(SERVER_TZ).strftime("%Y-%m-%d")


def _at(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)


def attempted(state_dir, day: str, script: str) -> bool:
    """True once the day's make-up for `script` is spent: dispatched (whatever came of
    it) or given up. A dispatch that did not take (`couldnt_run`) is not an attempt."""
    ent = read_marker(state_dir, day).get(script)
    return bool(ent) and ent.get("result") != COULDNT_RUN


# ------------------------------------------------------------- candidates

def eligible(rec, now: datetime | None = None) -> bool:
    """Whether a held failure is one a make-up is for: MAA / MaaEnd, started today,
    not a maintenance day, not a game it could not even enter, not stopped by hand."""
    if getattr(rec, "script", None) not in SCRIPTS:
        return False
    if _day(rec.started) != _day(_now(now)):
        return False
    raw = rec.raw or {}
    return not (raw.get("maintenance") or raw.get("maaend_unreachable") or raw.get("manual_stop"))


def candidates(eng, now: datetime | None = None) -> list:
    """Held failures a make-up is still to be dispatched for (today's marker not spent)."""
    today = _day(_now(now))
    return [r for r in eng._pending.values()
            if eligible(r, now) and not attempted(eng.cfg.state_dir, today, r.script)]


def holding(eng, rec, now: datetime | None = None) -> bool:
    """_flush_pending keeps `rec` held (no push, no drop): its make-up is still to come."""
    return eligible(rec, now) and not attempted(eng.cfg.state_dir, _day(_now(now)), rec.script)


def _recent(state_dir, now: datetime) -> list[tuple[str, dict]]:
    """(day, marker) for today and yesterday. A make-up dispatched at 23:55 is still
    running after midnight, and its entry sits in the day it was dispatched on."""
    return [(d, read_marker(state_dir, d)) for d in (_day(now - timedelta(days=1)), _day(now))]


def _last_stamp(ent: dict) -> datetime | None:
    stamps = [t for t in (_at(ent.get("dispatched_at")), _at(ent.get("seen_running_at"))) if t]
    return max(stamps) if stamps else None


def _fresh(ent, now: datetime) -> bool:
    """A dispatched make-up that has not gone stale."""
    if not isinstance(ent, dict) or ent.get("result") != DISPATCHED:
        return False
    last = _last_stamp(ent)
    return last is not None and now - last <= timedelta(minutes=STALE_MIN)


def in_flight(state_dir, now: datetime | None = None) -> list[str]:
    """Scripts whose dispatched make-up has not produced a record yet and is not stale,
    whichever day it was dispatched on."""
    now = _now(now)
    return sorted({script for _, marker in _recent(state_dir, now)
                   for script, ent in marker.items() if _fresh(ent, now)})


def maaend_still_running(state_dir, now: datetime | None = None) -> bool:
    """A MaaEnd make-up is in flight and AUTO-MAS says MaaEnd has not finished.

    For the boot-time restore: a relay restart in the middle of the make-up
    must not put the full master back under it. AUTO-MAS not answering counts as
    not running (a real boot: nothing can be running yet)."""
    if "MaaEnd" not in in_flight(state_dir, now):
        return False
    from . import engine  # noqa: PLC0415
    snap = engine._automas_snapshot()
    return snap is not None and engine._script_unfinished(snap, "MaaEnd")


def next_moment(state_dir, now: datetime | None = None) -> tuple[datetime, str] | None:
    """The next moment a make-up decision changes by the clock alone, for engine.next_deadline."""
    now = _now(now)
    out: list[tuple[datetime, str]] = []
    for script, ent in (kv for _, marker in _recent(state_dir, now) for kv in marker.items()):
        if not isinstance(ent, dict):
            continue
        stamps = [t for t in (_at(ent.get("dispatched_at")), _at(ent.get("seen_running_at"))) if t]
        if not stamps:
            continue
        if ent.get("result") == COULDNT_RUN:
            out.append((max(stamps) + timedelta(seconds=RETRY_GAP_S), f"补跑 {script} 再派一次"))
        elif ent.get("result") == DISPATCHED:
            out.append((max(stamps) + timedelta(minutes=STALE_MIN, seconds=1), f"补跑 {script} 有没有跑起来"))
    out = [m for m in out if m[0] > now]
    return min(out) if out else None


def waiting(eng, now: datetime | None = None) -> list[str]:
    """What the shutdown decision and the reports wait for: make-ups still to dispatch or running."""
    names = {r.script for r in candidates(eng, now)} | set(in_flight(eng.cfg.state_dir, now))
    return sorted(names)


# ------------------------------------- MaaEnd master: 存放背包 in front

def _narrow_file(state_dir) -> Path:
    # The name predates 2026-10-06 (the master used to be narrowed to the failed
    # tasks); kept so a leftover from that code is still found and put back.
    return _dir(state_dir) / "narrow.json"


def _strip(name: str) -> str:
    from .collector_maaend import _strip_emoji  # noqa: PLC0415
    return _strip_emoji(str(name or ""))


def _labels(maaend_dir) -> dict[str, str]:
    """{taskName: label as MaaEnd prints it in 「任务失败: …」, emoji stripped}."""
    from . import mastercfg  # noqa: PLC0415
    zh = mastercfg._Locale(Path(maaend_dir) if maaend_dir else None)
    _, decls = mastercfg._maaend_defs(maaend_dir)
    out: dict[str, str] = {}
    for name, decl in decls.items():
        if ref := (decl or {}).get("label"):
            out[name] = _strip(zh(ref))
    for key, val in zh.table.items():
        if key.startswith("task.") and key.endswith(".label") and key.count(".") == 2:
            out.setdefault(key[5:-6], _strip(val))
    return out


def _set_flag(task: dict, on: bool) -> None:
    """`enabled` and every per-controller copy of it (maaend.py does the same)."""
    task["enabled"] = on
    ctl = task.get("enabledByController")
    if isinstance(ctl, dict):
        for k in ctl:
            ctl[k] = on
    elif isinstance(ctl, bool):
        task["enabledByController"] = on


def bag_full(causes: dict | None) -> bool:
    """A failure of the held run was proven a full bag (the storage-full notice was
    seen after the claim; collector_maaend._maaend_fail_causes)."""
    from .collector_maaend import BAG_FULL  # noqa: PLC0415
    return any(c == BAG_FULL for c in (causes or {}).values())


def has_stash(doc: dict) -> bool:
    return any(t.get("taskName") == STASH for inst in doc.get("instances") or []
               for t in inst.get("tasks") or [])


def _backup_file(state_dir) -> Path:
    return _dir(state_dir) / "master-backup.json"


def _broken_file(state_dir) -> Path:
    return _dir(state_dir) / "restore-failed.json"


_FLAG_KEYS = ("enabled", "enabledByController")


def _keys(tasks: list) -> list[str]:
    """One key per task that survives moving a task: its id, else its taskName and
    how many id-less tasks of that name come before it."""
    out: list[str] = []
    seen: dict[str, int] = {}
    for t in tasks:
        if t.get("id"):
            out.append(f"id:{t.get('id')}")
        else:
            n = str(t.get("taskName") or "")
            k = seen.get(n, 0)
            seen[n] = k + 1
            out.append(f"name:{n}#{k}")
    return out


def _snapshot(doc: dict) -> list[dict]:
    """Per instance: the tasks' order and their enabled flags (present keys only)."""
    out = []
    for inst in doc.get("instances") or []:
        tasks = inst.get("tasks") or []
        keys = _keys(tasks)
        out.append({"order": keys,
                    "flags": {k: {f: t[f] for f in _FLAG_KEYS if f in t} for k, t in zip(keys, tasks)}})
    return out


def _read_json(path: Path):
    """The parsed file, None when it is missing or cannot be read."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _saved_ok(saved) -> bool:
    return (isinstance(saved, dict) and saved.get("v") == 2 and isinstance(saved.get("instances"), list)
            and all(isinstance(i, dict) and isinstance(i.get("order"), list) and isinstance(i.get("flags"), dict)
                    for i in saved["instances"]))


def restore_broken(state_dir) -> bool:
    """A temporary change that could not be put back is waiting for a person (the
    make-up does not touch the master until then)."""
    return bool(state_dir) and _broken_file(state_dir).exists()


def stash_first(cfg, run_id: str, now: datetime) -> tuple[bool, str]:
    """Switch 存放背包 on and move it in front of the first enabled task, in every
    instance that has it; every other task keeps its switch and its place. The
    original flags and order go to state/makeup/narrow.json first, a full copy of
    the master to master-backup.json before that (both written atomically); an
    existing save is kept, never overwritten. Read back: anything but 存放背包
    changed, or 存放背包 not on, puts the original back.

    Returns (changed, why 存放背包 will not run first - '' when it will, whether it
    was changed now or was already on and in front)."""
    from . import mastercfg  # noqa: PLC0415
    f = mastercfg.maaend_master(cfg.automas_dir) if cfg.automas_dir else None
    if not f or not f.is_file():
        return False, "找不到终末地的母本"
    if restore_broken(cfg.state_dir):
        return False, "上次临时改过的终末地设置还没改回，等人看过"
    text = f.read_text(encoding="utf-8")
    doc = json.loads(text)
    if not has_stash(doc):
        return False, "母本里没有存放背包这一项，没法先清背包"
    # Copies, not views: _set_flag below changes the controller dicts in place.
    before = json.loads(json.dumps(_snapshot(doc)))
    others0 = json.loads(json.dumps(_others(doc)))
    changed = False
    for inst in doc.get("instances") or []:
        tasks = inst.get("tasks") or []
        stash = next((t for t in tasks if t.get("taskName") == STASH), None)
        if stash is None:
            continue
        if not stash.get("enabled") or stash.get("enabledByController") is False or (
                isinstance(stash.get("enabledByController"), dict)
                and not all(stash["enabledByController"].values())):
            _set_flag(stash, True)
            changed = True
        first = next((i for i, t in enumerate(tasks)
                      if t.get("enabled") and t is not stash
                      and not str(t.get("taskName") or "").startswith("__")), None)
        if first is not None and tasks.index(stash) > first:
            tasks.remove(stash)
            tasks.insert(first, stash)
            changed = True
    if not changed:
        return False, ""
    nf, bf = _narrow_file(cfg.state_dir), _backup_file(cfg.state_dir)
    nf.parent.mkdir(parents=True, exist_ok=True)
    if not nf.exists():
        # The full copy first: a narrow.json that exists always has its backup.
        atomic_write_text(bf, text)
        atomic_write_text(nf, json.dumps({"v": 2, "run_id": run_id, "at": now.isoformat(),
                                          "instances": before}, ensure_ascii=False))
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    back = json.loads(f.read_text(encoding="utf-8"))
    stash_on = all(t.get("enabled") for inst in back.get("instances") or []
                   for t in inst.get("tasks") or [] if t.get("taskName") == STASH)
    others_same = json.loads(json.dumps(_others(back))) == others0
    if not stash_on or not others_same:
        log.warning("补跑：开存放背包后回读不对（存放背包%s、其他任务%s），改回原样、按原设置跑",
                    "开着" if stash_on else "没开", "没动" if others_same else "变了")
        restore(cfg)
        return False, "开存放背包后读出来不对，已改回原样"
    return True, ""


def _others(doc: dict) -> list:
    """Per instance: the order and the switches of every task but 存放背包 - what
    stash_first must leave exactly as it found it."""
    out = []
    for inst in doc.get("instances") or []:
        tasks = inst.get("tasks") or []
        pairs = [(k, t) for k, t in zip(_keys(tasks), tasks) if t.get("taskName") != STASH]
        out.append(([k for k, _ in pairs], {k: {f: t[f] for f in _FLAG_KEYS if f in t} for k, t in pairs}))
    return out


def restore(cfg, notifier=None) -> str:
    """Put the saved enabled flags and task order back. '' when there is nothing to
    restore or it did not work (see `try_restore` for why)."""
    return try_restore(cfg, notifier)[0]


def try_restore(cfg, notifier=None) -> tuple[str, str]:
    """(log line, '') when the master was put back, ('', '') when there was nothing to
    put back, ('', why) when it could not be. Never raises on a bad file.

    narrow.json unreadable: the full copy taken before the change goes back.
    Both unreadable: the files stay, no make-up changes the master again, and the group gets
    one alarm (`notifier`, whichever caller first has one).

    Anything else that goes wrong (a locked file that cannot be removed, the
    master's path not resolvable) comes back as the reason too: its callers log
    an exception as ERROR, and an ERROR line is itself a group alarm (errwatch)."""
    try:
        return _try_restore(cfg, notifier)
    except Exception as exc:  # noqa: BLE001
        return "", f"母本改回时出错（{type(exc).__name__}: {exc}）"


def _try_restore(cfg, notifier) -> tuple[str, str]:
    from . import mastercfg  # noqa: PLC0415
    state_dir = cfg.state_dir
    nf, bf = _narrow_file(state_dir), _backup_file(state_dir)
    if not nf.exists():
        # Nothing changed. A backup without its narrow.json is from a change that
        # never got written; a stamp without it means a person cleared it.
        for stale in (bf, _broken_file(state_dir)):
            stale.unlink(missing_ok=True)
        return "", ""
    f = mastercfg.maaend_master(cfg.automas_dir) if cfg.automas_dir else None
    if not f or not f.is_file():
        return "", "找不到终末地的母本"
    saved = _read_json(nf)
    if not _saved_ok(saved):
        return _restore_from_backup(cfg, f, nf, bf, notifier)
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
        for inst, s in zip(doc.get("instances") or [], saved["instances"]):
            tasks = inst.get("tasks") or []
            rank = {k: n for n, k in enumerate(s["order"])}
            pairs = sorted(zip(_keys(tasks), tasks), key=lambda kt: rank.get(kt[0], len(rank)))  # stable: unknown ones keep their place at the end
            for k, t in pairs:
                if not isinstance(old := s["flags"].get(k), dict):
                    continue
                for fk in _FLAG_KEYS:
                    if fk in old:
                        t[fk] = old[fk]
                    else:
                        t.pop(fk, None)
            if "tasks" in inst:
                inst["tasks"] = [t for _, t in pairs]
        atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
        back = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return "", f"母本改回时读写不成（{type(exc).__name__}: {exc}）"
    got = _snapshot(back)
    for i, s in enumerate(saved["instances"][:len(got)]):
        g = got[i]
        if any(g["flags"].get(k) != v for k, v in s["flags"].items() if k in g["flags"]) \
                or [k for k in g["order"] if k in s["flags"]] != [k for k in s["order"] if k in g["flags"]]:
            return "", "母本改回后读出来和原样不一样"
    nf.unlink()
    bf.unlink(missing_ok=True)
    return f"母本里的终末地任务已改回原样（{saved.get('run_id', '')} 补跑时临时改过）", ""


def _restore_from_backup(cfg, f: Path, nf: Path, bf: Path, notifier) -> tuple[str, str]:
    try:
        text = bf.read_text(encoding="utf-8")
        json.loads(text)
    except (OSError, ValueError):
        _restore_failed(cfg, f, nf, notifier)
        return "", "临时改动的记录和完整备份都读不出来，母本没法自动改回"
    try:
        atomic_write_text(f, text)
        same = f.read_text(encoding="utf-8") == text
    except OSError as exc:
        return "", f"母本用完整备份改回时写不进去（{type(exc).__name__}: {exc}）"
    if not same:
        return "", "母本用完整备份改回后读出来不一样"
    nf.unlink()
    bf.unlink(missing_ok=True)
    log.warning("补跑：临时改动的记录读不出来，母本已用完整备份改回")
    return "母本里的终末地任务已用完整备份改回原样（临时改动的记录读不出来）", ""


def _restore_failed(cfg, f: Path, nf: Path, notifier) -> None:
    """Stamp restore-failed.json (no change to the master until a person clears narrow.json) and
    push the one alarm, once: the stamp remembers it was delivered."""
    from . import texts  # noqa: PLC0415
    bfile = _broken_file(cfg.state_dir)
    stamp = _read_json(bfile)
    if not isinstance(stamp, dict):
        stamp = {"at": datetime.now(tz=SERVER_TZ).isoformat(), "alerted": False,
                 "master": str(f), "narrow": str(nf)}
        log.warning("补跑：终末地母本临时改过，记录和备份都读不出来，没法自动改回（%s）", nf)
    if not stamp.get("alerted") and notifier is not None:
        errs = notifier.send(texts.MAKEUP_RESTORE_FAILED, texts.makeup_restore_failed_body(str(f), str(nf)),
                             alert=True)
        stamp["alerted"] = not errs
    try:
        bfile.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(bfile, json.dumps(stamp, ensure_ascii=False))
    except OSError:
        log.warning("补跑：没能记下母本改回失败（%s）", bfile, exc_info=True)


# ---------------------------------------------------------------- dispatch

def _kill_game() -> None:
    from .desktop import kill  # noqa: PLC0415
    kill(GAME_EXE)


def _dispatch(script: str) -> tuple[bool, str]:
    from . import commands  # noqa: PLC0415
    return commands.run_script(script)


def _blocked(eng, now: datetime) -> str:
    """Why the queue is not idle enough for a make-up; '' when it is."""
    from . import echofarm, modes  # noqa: PLC0415
    if modes.debug_active(eng.state.dir):
        return "调试模式开着"
    if eng._scripts_running():
        return "脚本或游戏还在跑"
    if echofarm.current(eng.cfg.state_dir):
        return "正在刷声骸"
    if eng._deferred_update_busy():
        return "游戏客户端正在更新或重跑"
    if unfinished := eng._unfinished_queues(now, eng._recent_entries(now)):
        return "；".join(unfinished)
    return ""


def _settle_stale(eng, now: datetime) -> bool:
    """Note a running make-up, and close out one that never ran - today's or one
    dispatched before midnight. True if a marker changed."""
    changed_any = False
    for day, marker in _recent(eng.cfg.state_dir, now):
        changed = False
        for script, ent in marker.items():
            if not isinstance(ent, dict) or ent.get("result") != DISPATCHED:
                continue
            if eng._script_running(script):
                last = _at(ent.get("seen_running_at"))
                if last is None or now - last >= timedelta(seconds=60):
                    ent["seen_running_at"] = now.isoformat()
                    changed = True
            elif not _fresh(ent, now):
                ent["result"] = NO_RECORD
                changed = True
                log.warning("补跑：%s 派下去了，但 AUTO-MAS 没跑出记录", script)
        if changed:
            _write_marker(eng.cfg.state_dir, day, marker)
            changed_any = True
    return changed_any


def maa_work_done(eng, rec) -> str:
    """Why a whole-MAA make-up would spend sanity a second time; '' when the failed
    round never got going (and the make-up may run).

    Looks at the held record and at every failed attempt of the same round before
    it on the ledger (AUTO-MAS's earlier attempts may have fought before the last
    one failed to log in). Anything not clearly 「never started」 is a no."""
    rows = [{"failed_tasks": list(rec.failed_tasks or []), "raw": dict(rec.raw or {})}]
    try:
        ledger = eng.state.read_ledger(_day(rec.started))
    except Exception:  # noqa: BLE001
        return "账本读不出来，拿不准前面几次有没有打过仗"
    earlier = []
    for e in ledger:
        if e.get("script") != rec.script or e.get("user") != rec.user or e.get("run_id") == rec.run_id:
            continue
        started = _at(e.get("started"))
        if started is None:
            return "账本里有一条没有开始时间，拿不准前面几次有没有打过仗"
        if started < rec.started:
            earlier.append((started, e))
    for _, e in sorted(earlier, key=lambda x: x[0], reverse=True):
        if e.get("ok"):
            break                      # the round before this one; its spending was its own
        rows.append(e)
    for row in rows:
        failed = [str(x) for x in row.get("failed_tasks") or []]
        if not failed or not all(any(s in x for s in MAA_NOT_STARTED) for x in failed):
            return ("失败的不只是开始唤醒或连模拟器（" + ("、".join(failed) or "没写失败项")
                    + "），拿不准有没有打过仗")
        raw = row.get("raw") or {}
        if worked := [v for k, v in MAA_WORK_KEYS.items() if raw.get(k)]:
            return "这一轮已经开始干活（" + "、".join(worked) + "），再跑一遍会再吃一份理智药"
    return ""


def _give_up(state_dir, day: str, marker: dict, script: str, note: str, run_id: str = "") -> None:
    """Spend the day's make-up of `script` without running it (a no-op once it is spent).
    `run_id` is the held failure it was for (unresolved.after_makeup tells it from a
    later round of the same day)."""
    ent = marker.get(script)
    if isinstance(ent, dict) and ent.get("result") not in (None, COULDNT_RUN):
        return
    ent = dict(ent or {})
    ent.update(result=GAVE_UP, note=note)
    if run_id and not ent.get("run_id"):
        ent["run_id"] = run_id
    marker[script] = ent
    _write_marker(state_dir, day, marker)


def _restore_at_top(eng, now: datetime, day: str, marker: dict) -> None:
    """The make-up's change to the master goes back whenever no MaaEnd make-up is running. When it
    cannot, today's MaaEnd make-up is given up (with the reason), so that neither the
    shutdown decision nor the reports wait for it until midnight."""
    if "MaaEnd" in in_flight(eng.cfg.state_dir, now):
        return
    try:
        back, err = try_restore(eng.cfg, eng.notifier)
    except Exception as exc:  # noqa: BLE001 - a bad master must not raise every tick
        back, err = "", f"{type(exc).__name__}: {exc}"
    if back:
        log.info("补跑：%s", back)
    if err != getattr(eng, "_makeup_restore_note", ""):
        eng._makeup_restore_note = err
        if err:
            # WARNING, not ERROR: an ERROR line is itself a group alarm (errwatch).
            log.warning("补跑：终末地母本没能改回（%s）", err)
    if err and (held := [r for r in candidates(eng, now) if r.script == "MaaEnd"]):
        _give_up(eng.cfg.state_dir, day, marker, "MaaEnd", f"母本没能改回原样（{err}）", held[0].run_id)


def maybe_run(eng, now: datetime | None = None) -> bool:
    """Dispatch one make-up when the queue is idle. True when something was dispatched
    (or a dispatch that did not take is to be tried again), False otherwise.

    A tick step of its own (engine.tick, before the interim and daily reports and
    the shutdown decision): the shutdown decision cannot host it, because a held
    failure keeps that decision at 「还有告警没推出去」 and it would never reach the
    point of running anything.
    """
    now = _now(now)
    day = _day(now)
    state_dir = eng.cfg.state_dir
    _settle_stale(eng, now)
    marker = read_marker(state_dir, day)
    _restore_at_top(eng, now, day, marker)
    # A MAA run that fought already: a second whole run would eat another round of
    # potions. Spent at once, not when the queue goes idle, so it is not held.
    for r in candidates(eng, now):
        if r.script == "MAA" and (why := maa_work_done(eng, r)):
            log.info("补跑：明日方舟这次不补（%s），失败照常进群", why)
            _give_up(state_dir, day, marker, "MAA", f"不补跑：{why}", r.run_id)
    todo = candidates(eng, now)
    if not todo:
        return False
    if why := _blocked(eng, now):
        if why != getattr(eng, "_makeup_wait_note", ""):
            eng._makeup_wait_note = why
            log.info("补跑：%s 等着（%s）", "、".join(sorted({r.script for r in todo})), why)
        return False
    eng._makeup_wait_note = ""
    rec = sorted(todo, key=lambda r: r.started)[0]   # one at a time: two games at once is not what a person does
    ent = dict(marker.get(rec.script) or {})
    if (last := _at(ent.get("dispatched_at"))) is not None and (now - last).total_seconds() < RETRY_GAP_S:
        return True
    tries = int(ent.get("tries") or 0) + 1
    ent.update({"dispatched_at": now.isoformat(), "tries": tries, "run_id": rec.run_id,
                "failed": list(rec.failed_tasks or []), "result": DISPATCHED, "note": ""})
    if rec.script == "MaaEnd":
        try:
            ok, ent = _prepare_maaend(eng, rec, ent, now)
        except Exception as exc:  # a bad master must not raise every tick
            # WARNING, not ERROR: an ERROR line is itself a group alarm (errwatch),
            # and the outcome is already in the marker and the daily report.
            log.warning("补跑：准备终末地母本出错", exc_info=True)
            restore(eng.cfg, eng.notifier)    # never raises (try_restore)
            ok = False
            ent.update(result=GAVE_UP, note=f"母本读写出错（{type(exc).__name__}: {exc}）")
        if not ok:
            marker[rec.script] = ent
            _write_marker(state_dir, day, marker)
            log.warning("补跑：终末地这次不补（%s）", ent.get("note"))
            return False
    else:
        ent["tasks"] = ["整个 MAA"]
    marker[rec.script] = ent
    _write_marker(state_dir, day, marker)        # before the dispatch: a crash after it must not dispatch twice
    if rec.script == "MaaEnd":
        _kill_game()
    try:
        ok, msg = _dispatch(rec.script)
    except Exception as exc:  # noqa: BLE001 - a make-up must never take the service down
        ok, msg = False, f"{type(exc).__name__}: {exc}"
    if not ok:
        if rec.script == "MaaEnd":
            restore(eng.cfg, eng.notifier)
        ent["result"] = COULDNT_RUN if tries < MAX_TRIES else GAVE_UP
        ent["note"] = msg
        marker[rec.script] = ent
        _write_marker(state_dir, day, marker)
        log.warning("补跑：%s 没派下去（第 %d 次，%s）", rec.script, tries, msg)
        return ent["result"] == COULDNT_RUN
    # The run has just been started: the 「nothing runs」 read cached a moment ago
    # must not reach this tick's shutdown decision. That the relay started it (not a
    # person) is on record through commands.run_script's dispatch note, which
    # shutdown._last_round_manual reads.
    from . import engine  # noqa: PLC0415
    engine.forget_scripts_cache()
    log.info("🔁 补跑：%s 只补一次（%s）→ %s", rec.script, "、".join(ent.get("tasks") or []), msg)
    return True


def _prepare_maaend(eng, rec, ent: dict, now: datetime) -> tuple[bool, dict]:
    """The user's master runs as it is; on a full bag 存放背包 goes in front first.
    (False, ent marked gave_up) when the master cannot be found, or an earlier
    temporary change to it cannot be put back."""
    from . import mastercfg  # noqa: PLC0415
    cfg = eng.cfg
    f = mastercfg.maaend_master(cfg.automas_dir) if cfg.automas_dir else None
    if not f or not f.is_file():
        ent.update(result=GAVE_UP, tasks=[WHOLE_MAAEND], note="找不到终末地的母本")
        return False, ent
    _, err = try_restore(cfg, eng.notifier)     # a leftover change is not the user's own master
    if err or restore_broken(cfg.state_dir) or _narrow_file(cfg.state_dir).exists():
        ent.update(result=GAVE_UP, tasks=[WHOLE_MAAEND],
                   note=f"上次临时改过的终末地设置没能自动改回（{err or '等人看过'}），这次不补")
        return False, ent
    tasks, note = [WHOLE_MAAEND], ""
    if bag_full((rec.raw or {}).get("maaend_fail_causes")):
        changed, why_not = stash_first(cfg, rec.run_id, now)
        if why_not:
            note = f"背包满了，但{why_not}"
            log.info("补跑：终末地背包满了，%s；按原设置跑", why_not)
        else:
            tasks = [_labels(cfg.maaend_dir).get(STASH) or "存放背包", WHOLE_MAAEND]
            log.info("补跑：终末地背包满了，%s", "存放背包暂时开着并排到最前" if changed
                     else "存放背包本来就开着、排在最前")
    ent["tasks"] = tasks
    ent["note"] = ent["prep_note"] = note
    return True, ent


# ------------------------------------------------------- the make-up's record

def _find_entry(state_dir, script: str, started: datetime):
    """(day, marker, entry, dispatched_at) of the make-up `started` can belong to: the
    latest one dispatched before it (less SLACK), looked up on the dispatch day,
    which is not always the record's own day (dispatched 23:59, started 00:01)."""
    best = None
    days = {_day(started - timedelta(days=1)), _day(started), _day(started + SLACK)}
    for day in sorted(days):
        marker = read_marker(state_dir, day)
        ent = marker.get(script)
        if not isinstance(ent, dict) or ent.get("result") not in (DISPATCHED, OK, FAILED, NO_RECORD):
            continue
        since = _at(ent.get("dispatched_at"))
        if since is None or started < since - SLACK:
            continue
        if best is None or since > best[3]:
            best = (day, marker, ent, since)
    return best


def _belongs(ent: dict, rec, since: datetime) -> bool:
    """Is `rec` the make-up's record, rather than a later run of the same script?

    Not yet booked (dispatched / no_record): its first attempt starts soon after the
    dispatch, or while it was last seen running. Booked as passed: final. Booked as
    failed: only AUTO-MAS's own retry of the booked attempt (same user, starting
    within RETRY_CHAIN of its end) can still change it; the evening queue cannot."""
    res = ent.get("result")
    if ent.get("record") == rec.run_id:
        return False
    if res in (DISPATCHED, NO_RECORD):
        last = _last_stamp(ent) or since
        return rec.started <= last + timedelta(minutes=STALE_MIN) + SLACK
    if res == FAILED:
        booked_end = _at(ent.get("record_finished"))
        return (booked_end is not None and ent.get("record_user") == rec.user
                and booked_end - SLACK <= rec.started <= booked_end + RETRY_CHAIN)
    return False


def on_record(eng, rec) -> None:
    """Book the make-up's own record into the marker; on success, tie the earlier
    failures to it on the ledger (raw.makeup_ok), so the report reads them as retried."""
    if rec.script not in SCRIPTS or rec.transitional:
        return
    found = _find_entry(eng.cfg.state_dir, rec.script, rec.started)
    if found is None:
        return
    day, marker, ent, since = found
    if not _belongs(ent, rec, since):
        return
    stopped = bool((rec.raw or {}).get("manual_stop"))
    ent["result"] = OK if rec.ok and not stopped else FAILED
    ent["record"] = rec.run_id
    ent["record_user"] = rec.user
    ent["record_finished"] = rec.finished.astimezone(SERVER_TZ).isoformat()
    if stopped:
        ent["note"] = "被停一切停掉"
    elif not rec.ok:
        ent["note"] = "、".join(rec.failed_tasks or []) or ent.get("note", "")
    else:
        # A retry that went through: the failed attempt's note no longer applies;
        # what the preparation said (a full bag it could not clear first) still does.
        ent["note"] = ent.get("prep_note", "")
    marker[rec.script] = ent
    _write_marker(eng.cfg.state_dir, day, marker)
    if ent["result"] != OK:
        log.info("补跑：%s %s 没成（%s）", rec.script, rec.run_id, ent.get("note"))
        return
    when = rec.finished.astimezone(SERVER_TZ).strftime("%H:%M")
    # The failures it makes up for sit on the dispatch day's ledger.
    for e in eng.state.read_ledger(day):
        if e.get("script") != rec.script or e.get("user") != rec.user:
            continue
        started = _at(e.get("started"))
        if started is None or started >= since - SLACK:
            continue
        if not e.get("ok"):
            eng.state.mark_raw(day, e["run_id"], "makeup_ok", when)
        elif e.get("incomplete"):
            # The whole script ran again and went through - MAA always, MaaEnd
            # since 2026-10-06 (its master is no longer narrowed to the failed tasks).
            eng.state.mark_incomplete(day, e["run_id"], "")
    log.info("✅ 补跑：%s %s 走通", rec.script, rec.run_id)
