"""One make-up run of a failed MAA / MaaEnd round, dispatched once the queue is idle.

* MaaEnd: the game is closed and the MaaEnd script is dispatched once through
  AUTO-MAS (commands.run_script) with the user's master as it is. AUTO-MAS's
  dispatch takes a script and a mode only, so a chosen subset of tasks cannot be
  run. One change is made: when a failure's cause is a full bag
  (collector_maaend.BAG_FULL) and the master has 存放背包 (StashBackpack), that
  task is switched on and moved in front of the first enabled task
  (`stash_first`). Its switch and place go back when the make-up's record lands
  (handle._handle), at the top of every `maybe_run`, and at boot unless the
  make-up is still running. A full copy of the master is kept beside the saved
  flags; when the flags cannot be read the copy goes back, and when neither can
  be read restore-failed.json is written, the group gets one alarm, and no
  make-up touches the master until a person has looked.
* MAA: the whole script runs again, and only when the failed round never got
  going (`maa_work_done`): every failed task matches MAA_NOT_STARTED and no
  attempt of the round carries MAA_WORK_KEYS evidence. MAA's MedicineNumb counts
  per run, so a second whole run after one that fought uses sanity potions again.

At most one make-up per script per day (state/makeup/<day>.json). A dispatch
that did not take (`couldnt_run`) is retried, RETRY_GAP_S apart, up to
MAX_TRIES. The daily report has one line per make-up (report.makeup_line). A
failure the make-up did not get past, or one it was not run for, goes to the
group as 「没跑成」 once its make-up is over (unresolved.py); one it got past goes
to the daily report only.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core.config import SERVER_TZ, atomic_write_text

from ark_relay.features.makeup import marker as _marker
from ark_relay.features.makeup.marker import (
    COULDNT_RUN, DISPATCHED, FAILED, GAVE_UP, NO_RECORD, OK, RETRY_GAP_S, SCRIPTS, STALE_MIN,
    _at, _day, _dir, _fresh, _last_stamp, _now, _recent, _write_marker, candidates, holding,
    in_flight, read_marker,
)

# The day marker lives in marker.py. Names that only other modules and tests read
# off this module are bound here too (the same objects).
_marker_file, _unreadable, attempted, eligible = (
    _marker._marker_file, _marker._unreadable, _marker.attempted, _marker.eligible)
maaend_still_running, next_moment, waiting = (
    _marker.maaend_still_running, _marker.next_moment, _marker.waiting)

log = logging.getLogger("ark.makeup")

MAX_TRIES = 3
# A record starting up to this long before the dispatch can still be the
# make-up's: the log's first line and the dispatch time come from two clocks.
SLACK = timedelta(minutes=2)
STASH = "StashBackpack"
GAME_EXE = "Endfield.exe"
# What a MaaEnd make-up runs, for the marker and the daily report's line.
WHOLE_MAAEND = "按原设置整轮再跑"

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
                 "run_times": "打过关", "stages": "进过关卡", "annihilation_progress": "打过剿灭",
                 "fight_count": "打过仗"}


# ------------------------------------- MaaEnd master: 存放背包 in front

def _narrow_file(state_dir) -> Path:
    # Older relay versions wrote their narrowed-master save to this same file, so
    # a leftover from them is put back by the same restore.
    return _dir(state_dir) / "narrow.json"


def _strip(name: str) -> str:
    from ark_relay.features.verify.collector_maaend import _strip_emoji  # noqa: PLC0415
    return _strip_emoji(str(name or ""))


def _labels(maaend_dir) -> dict[str, str]:
    """{taskName: label as MaaEnd prints it in 「任务失败: …」, emoji stripped}."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
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
    """Set `enabled` and every per-controller copy of it."""
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
    from ark_relay.features.verify.collector_maaend import BAG_FULL  # noqa: PLC0415
    return any(c == BAG_FULL for c in (causes or {}).values())


def has_stash(doc: dict) -> bool:
    return any(t.get("taskName") == STASH for inst in doc.get("instances") or []
               for t in inst.get("tasks") or [])


def _master_file(cfg) -> Path | None:
    """The MaaEnd master file (mxu-MaaEnd.json under AUTO-MAS), None when it is not there."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
    f = mastercfg.maaend_master(cfg.automas_dir) if cfg.automas_dir else None
    return f if f and f.is_file() else None


def _backup_file(state_dir) -> Path:
    return _dir(state_dir) / "master-backup.json"


def _broken_file(state_dir) -> Path:
    return _dir(state_dir) / "restore-failed.json"


_FLAG_KEYS = ("enabled", "enabledByController")


def _flags_of(task: dict) -> dict:
    """The task's enabled flags that are present."""
    return {f: task[f] for f in _FLAG_KEYS if f in task}


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
                    "flags": {k: _flags_of(t) for k, t in zip(keys, tasks)}})
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
    f = _master_file(cfg)
    if f is None:
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
        out.append(([k for k, _ in pairs], {k: _flags_of(t) for k, t in pairs}))
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
    state_dir = cfg.state_dir
    nf, bf = _narrow_file(state_dir), _backup_file(state_dir)
    if not nf.exists():
        # Nothing changed. A backup without its narrow.json is from a change that
        # never got written; a stamp without it means a person cleared it.
        for stale in (bf, _broken_file(state_dir)):
            stale.unlink(missing_ok=True)
        return "", ""
    f = _master_file(cfg)
    if f is None:
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
    from ark_relay.core import texts  # noqa: PLC0415
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
    from ark_relay.core.desktop import kill  # noqa: PLC0415
    kill(GAME_EXE)


def _dispatch(script: str) -> tuple[bool, str]:
    from ark_relay.features.phone import commands  # noqa: PLC0415
    return commands.run_script(script)


def _blocked(eng, now: datetime) -> str:
    """Why the queue is not idle enough for a make-up; '' when it is."""
    from ark_relay.features.echofarm import echofarm  # noqa: PLC0415
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
        closed = []
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
                closed.append(script)
                log.warning("补跑：%s 派下去了，但 AUTO-MAS 没跑出记录", script)
        if changed:
            _write_marker(eng.cfg.state_dir, day, marker)
            changed_any = True
        for script in closed:
            _machinecheck(eng, {"kind": "补跑", "script": script, "day": day, "result": dict(marker[script])})
    return changed_any


def _machinecheck(eng, ctx: dict) -> None:
    """Hand one make-up outcome to the machine checks (selfcheck/machinecheck.py,
    event "makeup"; checks in selfcheck/machinechecks/system.py). Never raises: a
    broken check must not break the make-up."""
    state_dir = getattr(getattr(eng, "cfg", None), "state_dir", None)
    if not state_dir:
        return
    try:
        from ark_relay.features.selfcheck import machinecheck  # noqa: PLC0415
        from ark_relay.core.statestore import StateStore  # noqa: PLC0415
        machinecheck.judge(state_dir, "makeup", ctx, notifier=getattr(eng, "notifier", None),
                           version=str(StateStore(state_dir).get("versions", "code") or ""))
    except Exception:
        log.exception("上机核对（补跑那一步）自己出错，补跑照常")


def never_started(eng, rec) -> None:
    """A MAA failure that never got into the game (maa_work_done says ''): keep MAA's
    own gui.log / asst.log lines of that run under state/machinecheck/maa-not-started/
    and hand the run to the machine checks. Once per record."""
    done = getattr(eng, "_never_started_seen", None)
    if done is None:
        done = eng._never_started_seen = set()
    if rec.run_id in done:
        return
    done.add(rec.run_id)
    captured: dict = {}
    try:
        from ark_relay.features.verify import collector_maa
        from ark_relay.core import plan  # noqa: PLC0415
        maa_dir = getattr(eng.cfg, "maa_dir", None) or plan.script_dir(eng.cfg.automas_dir, "MAA")
        captured = collector_maa.keep_run_lines(maa_dir, rec.started, rec.finished,
                                                Path(eng.cfg.state_dir) / "machinecheck" / "maa-not-started",
                                                rec.run_id)
    except Exception:  # the sample is evidence; its absence is said in the check
        log.warning("明日方舟没进游戏的那一趟，MAA 自己的日志没存下来（%s）", rec.run_id, exc_info=True)
    _machinecheck(eng, {"kind": "没进游戏", "script": "MAA", "run_id": rec.run_id,
                        "failed": "、".join(rec.failed_tasks or []), "captured": captured,
                        "written": bool((rec.raw or {}).get("maa_unreachable"))})


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
    from ark_relay.core import texts  # noqa: PLC0415
    for row in rows:
        failed = [str(x) for x in row.get("failed_tasks") or []]
        raw = row.get("raw") or {}
        # MAA refused the config (collector_maa): the same config run again is
        # refused again, whatever else is on record.
        if rejected := raw.get("maa_config_rejected"):
            return texts.makeup_config_rejected(rejected)
        worked = [v for k, v in MAA_WORK_KEYS.items() if raw.get(k)]
        if not failed or not all(any(s in x for s in MAA_NOT_STARTED) for x in failed):
            what = "、".join(failed) or "没写失败项"
            # A fight count of 0 means the log was read and shows no fight (a
            # missing count means nothing). Still no make-up: only a round that
            # never got going is run again.
            if raw.get("fight_count") == 0 and not worked:
                return texts.makeup_no_fight(what)
            return texts.makeup_unsure(what)
        if worked:
            return "这一轮已经开始干活（" + "、".join(worked) + "），再跑一遍会再吃一份理智药"
    return ""


def refuse_rejected(eng, rec, now: datetime | None = None) -> None:
    """Spend today's MAA make-up at once for a held record whose config MAA refused
    (collector_maa `maa_config_rejected`), with maa_work_done's reason.

    Called by handle._flush_pending before it asks unresolved.after_makeup, so the
    alarm goes out on the tick the records land instead of waiting for maybe_run's
    tick. Nothing is stopped or changed in AUTO-MAS or the config."""
    if getattr(rec, "script", None) != "MAA" or not (rec.raw or {}).get("maa_config_rejected"):
        return
    now = _now(now)
    if not holding(eng, rec, now):
        return
    why = maa_work_done(eng, rec)
    day = _day(now)
    log.info("补跑：明日方舟这次不补（%s），失败马上进群", why)
    _give_up(eng.cfg.state_dir, day, read_marker(eng.cfg.state_dir, day), "MAA", f"不补跑：{why}", rec.run_id)


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
    """Put the make-up's change to the master back whenever no MaaEnd make-up is running.
    When that fails, today's MaaEnd make-up is given up with the reason, so the
    shutdown decision and the reports do not wait for it."""
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
        _machinecheck(eng, {"kind": "补跑", "script": "MaaEnd", "day": day,
                            "result": dict(marker.get("MaaEnd") or {})})


def maybe_run(eng, now: datetime | None = None) -> bool:
    """Dispatch one make-up when the queue is idle. True when something was dispatched
    (or a dispatch that did not take is to be tried again), False otherwise.

    Its own tick step (engine.tick), before the interim and daily reports and the
    shutdown decision: a held failure keeps the shutdown decision at "pending", so
    it could not host this step.
    """
    now = _now(now)
    day = _day(now)
    state_dir = eng.cfg.state_dir
    _settle_stale(eng, now)
    marker = read_marker(state_dir, day)
    _restore_at_top(eng, now, day, marker)
    # A MAA round that already worked gets no make-up (a second whole run uses
    # potions again). Spent at once, not when the queue goes idle, so it is not held.
    for r in candidates(eng, now):
        if r.script == "MAA" and (why := maa_work_done(eng, r)):
            log.info("补跑：明日方舟这次不补（%s），失败照常进群", why)
            _give_up(state_dir, day, marker, "MAA", f"不补跑：{why}", r.run_id)
        elif r.script == "MAA":
            never_started(eng, r)
    # Debug mode: no make-up, and the held failures are not kept waiting for one.
    from ark_relay.features.modes import modes  # noqa: PLC0415
    if modes.debug_active(state_dir):
        for r in candidates(eng, now):
            log.info("补跑：%s 这次不补（调试模式开着），失败照常进群", r.script)
            _give_up(state_dir, day, marker, r.script, "不补跑：调试模式开着", r.run_id)
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
            _machinecheck(eng, {"kind": "补跑", "script": rec.script, "day": day, "result": dict(ent)})
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
        if ent["result"] == GAVE_UP:
            _machinecheck(eng, {"kind": "补跑", "script": rec.script, "day": day, "result": dict(ent)})
        return ent["result"] == COULDNT_RUN
    # The run has just been started: drop the cached "nothing runs" read so this
    # tick's shutdown decision does not use it. commands.run_script's dispatch note
    # records that the relay started it (read by shutdown._relay_dispatched).
    from ark_relay.core import engine  # noqa: PLC0415
    engine.forget_scripts_cache()
    log.info("🔁 补跑：%s 只补一次（%s）→ %s", rec.script, "、".join(ent.get("tasks") or []), msg)
    return True


def _prepare_maaend(eng, rec, ent: dict, now: datetime) -> tuple[bool, dict]:
    """The user's master runs as it is; on a full bag 存放背包 goes in front first.
    (False, ent marked gave_up) when the master cannot be found, or an earlier
    temporary change to it cannot be put back."""
    cfg = eng.cfg
    if _master_file(cfg) is None:
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
    _machinecheck(eng, {"kind": "补跑", "script": rec.script, "day": day, "result": dict(ent)})
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
            # The make-up ran the whole script again and it went through.
            eng.state.mark_incomplete(day, e["run_id"], "")
    log.info("✅ 补跑：%s %s 走通", rec.script, rec.run_id)
