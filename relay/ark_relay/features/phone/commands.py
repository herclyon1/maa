"""Applying commands to AUTO-MAS config - the guarded path.

Four gates, none optional (relay/README.md, "The four gates on commands"):

  ① whitelist (白名单)
      the model emits an action name from a fixed table, never a JSON patch
  ② operator confirmation (人工确认)
      config-mutating actions wait for the operator's OK; reversible ones
      (run_now / skip_today) go straight through
  ③ write-back validation (落地校验)
      backup -> edit -> json.loads -> structural diff; anything unexpected
      rolls back. While the AUTO-MAS backend answers, the change goes through
      its API instead and is read back through the API before success is
      reported; the file path is used only when the backend does not answer
      (it rewrites the file from memory while up, so a file edit would be lost)
  ④ reporting (回报)
      success, failure and rejection all get reported

Gate ③'s structural diff catches an edit that touches more than it should
(for example a regex that changes an unrelated section).
"""
from __future__ import annotations

import json
import logging
import os

from ark_relay.core import names, texts
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ark_relay.core.config import SERVER_TZ, atomic_write_text
# Config-field helpers, the AUTO-MAS client and the red button live in sibling
# modules. Names other code reaches as `commands.<name>` are re-exported here:
# mas_post (snapshot.py), the estop names (boot_stages.py, alarm/handle.py,
# alarm/records.py, machinechecks/phone_banners.py). `_mas` is bound here on
# purpose: the functions below read this module's `_mas`, so a test that
# replaces `commands._mas` fakes the backend for them.
from ark_relay.features.phone.config_fields import _dig, _flatten, _humanize, _nest
from ark_relay.features.phone.mas_client import _mas, mas_post
from ark_relay.features.phone.redbutton import (
    ESTOP_LAST, ESTOP_WINDOWS_FILE, estop, estop_label, estop_windows)

log = logging.getLogger("ark.commands")

# Public names: this module's own plus the re-exported ones above.
__all__ = [
    "ALLOWED",
    "ESTOP_LAST",
    "ESTOP_WINDOWS_FILE",
    "MUTATING",
    "REVERSIBLE",
    "apply_command",
    "estop",
    "estop_label",
    "estop_windows",
    "mas_post",
    "mas_up",
    "restore_script_in_queue",
    "run_script",
    "SkipError",
    "skip_script_all_items",
    "skip_script_in_queue",
]

# ---------- gate ① : the whitelist ----------

# Actions that only change what happens next, and undo themselves.
# `monthcard` only writes the relay's own record of the user's monthly-card purchases
# (monthcard.py), no script config, so it needs no confirmation either.
REVERSIBLE = {"skip_today", "unskip_today", "debug_mode", "skip_shutdown", "weekly_boss",
              "echo_farm_stop", "echo_farm_until", "tacet_shots", "monthcard"}

# Actions that change configuration (AUTO-MAS through its API while the backend
# is up, otherwise its config file; or a script's master copy / relay state).
MUTATING = {"set_stage", "set_medicine", "toggle_task", "set_wait_time",
            "set_config", "set_master", "run_now", "echo_farm"}

ALLOWED = REVERSIBLE | MUTATING

# Stage codes look like TO-5 / CE-6 / 1-7 / LS-6. Refuse anything else outright
# rather than trusting a model not to invent one.
_STAGE_RE = re.compile(r"^[A-Za-z0-9]{1,4}-[A-Za-z0-9]{1,3}$")


def _script_config() -> Path:
    root = os.environ.get("ARK_AUTOMAS_DIR")
    if not root:
        raise RuntimeError("ARK_AUTOMAS_DIR 未设置")
    return Path(root) / "config" / "ScriptConfig.json"


# ---------- gate ③ : safe write ----------

def _safe_rewrite(path: Path, mutate: Callable[[str], str],
                  expect_changed: int) -> tuple[bool, str]:
    """Back up, edit, validate, diff. Roll back unless exactly as expected."""
    if not path.exists():
        return False, f"配置文件不存在: {path}"
    original = path.read_text(encoding="utf-8")
    try:
        before = json.loads(original)
    except json.JSONDecodeError as exc:
        return False, f"原文件已经不是合法 JSON，拒绝改动: {exc}"

    try:
        updated = mutate(original)
    except Exception as exc:  # noqa: BLE001 - a failed edit must not touch disk
        return False, f"生成改动失败: {exc}"

    try:
        after = json.loads(updated)
    except json.JSONDecodeError as exc:
        return False, f"改动后 JSON 非法，已放弃: {exc}"

    a, b = _flatten(before), _flatten(after)
    added, removed = set(b) - set(a), set(a) - set(b)
    changed = {k: (a[k], b[k]) for k in a.keys() & b.keys() if a[k] != b[k]}
    # Setting a value to what it already is must read as success, not as the
    # guard tripping - a re-sent batch (or the operator repeating the current
    # stage) is fine, and "diff 不符预期" for it is indistinguishable from a
    # real corruption catch.
    if not (added or removed or changed):
        return True, "已经是这个状态，无需改动"
    if added or removed or len(changed) != expect_changed:
        return False, (
            f"改动的地方和预期不符，已放弃："
            f"新增 {len(added)}、删除 {len(removed)}、改动 {len(changed)}"
            f"（预期改动 {expect_changed}、新增 0、删除 0）"
        )

    stamp = datetime.now(tz=SERVER_TZ)
    backup = path.with_suffix(path.suffix + f".bak-{stamp:%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)
    try:
        atomic_write_text(path, updated, newline="")
    except OSError as exc:
        shutil.copy2(backup, path)
        return False, f"写入失败，已回滚: {exc}"

    detail = "；".join(_humanize(k, x, y) for k, (x, y) in sorted(changed.items()))
    return True, detail


# ---------- the actions ----------

# The stage items of an MAA user that AUTO-MAS hands to MAA's Fight task.
_STAGE_PATHS = ("Info.Stage", "Info.Stage_1", "Info.Stage_2", "Info.Stage_3")


def _stage_refusal(stage: str) -> str:
    """Why `stage` is refused, '' when it is not: MAA has no navigation for it.

    A stage MAA cannot navigate to stops the MAA run at its first task
    (stagegate.py has the asst.log lines). Only a definite "no" refuses; task
    files that cannot be read never block a setting.
    """
    from ark_relay.features.schedule import stagegate  # noqa: PLC0415
    from ark_relay.core.config import Config  # noqa: PLC0415
    try:
        maa_dir = Config().maa_dir
    except Exception:  # noqa: BLE001 - no config, no gate
        return ""
    verdict, why = stagegate.check(stage, maa_dir)
    return texts.stage_refused(stage, why) if verdict == stagegate.NO else ""


def _is_maa(script: str) -> bool:
    """Is `script` (an AUTO-MAS display name) the MAA script?"""
    automas = os.environ.get("ARK_AUTOMAS_DIR")
    if automas:
        from ark_relay.core import plan  # noqa: PLC0415
        for s in plan._scripts(Path(automas) / "config").values():
            if str(s.get("name") or "").lower() == script.lower():
                return s.get("kind") == "MAA"
    return script.lower() == "maa"


def _set_stage(value: str) -> tuple[bool, str]:
    stage = str(value).strip().upper()
    if not _STAGE_RE.match(stage):
        return False, f"关卡格式不合法: {value!r}（应形如 TO-5 / CE-6 / 1-7）"
    if why := _stage_refusal(stage):
        return False, why

    # Why the backend comes first: while AUTO-MAS runs it never re-reads
    # ScriptConfig.json and writes its in-memory copy back over any edit.
    # The file is edited only when it is down.
    scripts, why = _backend_scripts()
    if why:
        return False, why
    if scripts is not None:
        return _user_item_report("MAA", "Info.Stage", stage)

    def mutate(raw: str) -> str:
        hits = re.findall(r'"Stage":\s*"[^"]*"', raw)
        if len(hits) != 1:
            raise ValueError(f'找到 {len(hits)} 处 "Stage"，预期恰好 1 处')
        return re.sub(r'("Stage":\s*)"[^"]*"', rf'\1"{stage}"', raw, count=1)

    return _safe_rewrite(_script_config(), mutate, expect_changed=1)


def _set_medicine(value: Any) -> tuple[bool, str]:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return False, f"理智药数量不是整数: {value!r}"
    if not 0 <= n <= 999:
        return False, f"理智药数量超出范围 0–999: {n}"

    # Same as _set_stage (AUTO-MAS writes its in-memory copy back over file
    # edits): through the backend while it answers.
    scripts, why = _backend_scripts()
    if why:
        return False, why
    if scripts is not None:
        return _user_item_report("MAA", "Info.MedicineNumb", n)

    def mutate(raw: str) -> str:
        hits = re.findall(r'"MedicineNumb":\s*\d+', raw)
        if len(hits) != 1:
            raise ValueError(f'找到 {len(hits)} 处 "MedicineNumb"，预期恰好 1 处')
        return re.sub(r'("MedicineNumb":\s*)\d+', rf"\g<1>{n}", raw, count=1)

    return _safe_rewrite(_script_config(), mutate, expect_changed=1)


def _set_wait_time(value: Any) -> tuple[bool, str]:
    """MaaEnd's "seconds to wait after the game starts" - the one and only
    Game/WaitTime in ScriptConfig.

    Why this knob exists here: on a fresh boot the game recreates its window
    during first startup, and a MaaEnd that connects before that grabs the
    early handle and dies within seconds (docs/PITFALLS.md). Waiting past the
    recreation window avoids it.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return False, f"等待秒数不是整数: {value!r}"
    # AUTO-MAS's own schema declares this field as `ge=60`
    # (app/models/schema.py). Anything smaller is not rejected loudly - it is
    # accepted, written to disk, and then silently clamped back to 60 the next
    # time AUTO-MAS starts (measured 2026-08-21: 30 became 60 on the next
    # launch). Refusing here turns an invisible revert into a clear message.
    if not 60 <= n <= 600:
        return False, f"等待秒数超出范围 60–600: {n}（AUTO-MAS 最小值就是 60，写小了会被它改回去）"

    # Same as _set_stage (AUTO-MAS writes its in-memory copy back over file
    # edits). WaitTime is a script-level key (MaaEnd's top-level
    # keys are Game/Info/Run), so it goes through /api/scripts/update rather
    # than the per-user endpoint _set_config uses.
    scripts, why = _backend_scripts()
    if why:
        return False, why
    if scripts is not None:
        return _script_item_via_api(scripts, "MaaEnd", "Game.WaitTime", n)

    def mutate(raw: str) -> str:
        hits = re.findall(r'"WaitTime":\s*\d+', raw)
        if len(hits) != 1:
            raise ValueError(f'找到 {len(hits)} 处 "WaitTime"，预期恰好 1 处')
        return re.sub(r'("WaitTime":\s*)\d+', rf"\g<1>{n}", raw, count=1)

    return _safe_rewrite(_script_config(), mutate, expect_changed=1)


def _toggle_task(name: str, on: bool) -> tuple[bool, str]:
    # Deliberately unimplemented: task names live in a different file per
    # script and getting this wrong silently disables the wrong task.
    which = "开" if on else "关"
    return False, (f"toggle_task 不用了（{name} → {which}）："
                   "用 set_config 指名道姓地写路径，比猜任务名安全")


def _find_user(script: str) -> "tuple[str, str, dict]":
    """Find (scriptId, userId, current user config) by script name."""
    scripts = _mas("/api/scripts/get")["data"]
    for sid, sc in scripts.items():
        name = str((sc.get("Info") or {}).get("Name") or "")
        if name.lower() != script.lower():
            continue
        users = _mas("/api/scripts/user/get", {"scriptId": sid}).get("data") or {}
        if not users:
            raise KeyError(f"脚本「{script}」下面没有用户")
        uid = next(iter(users))
        return sid, uid, users[uid]
    raise KeyError(f"没有叫「{script}」的脚本")


def _backend_scripts() -> "tuple[dict | None, str]":
    """(the backend's `/api/scripts/get` reply, failure text).

    (reply, "") - the backend is up; (None, "") - it refused the connection
    (annihilation._backend_unreachable), so editing the file is safe; (None, why) -
    something is there but did not answer properly (timeout, HTTP error, bad JSON).

    This alone decides API or file. It cannot be `_set_config` itself: its
    `_find_user` failure (backend down included) comes back as 「找不到脚本或用户」
    and would never reach the file path. Only a refused connection means "down":
    a timeout can come from a live AUTO-MAS, which would overwrite a file edit
    from its memory after the phone had been told success.
    """
    from ark_relay.features.weekly.annihilation import _backend_unreachable  # noqa: PLC0415 - annihilation imports this module
    try:
        return _mas("/api/scripts/get", timeout=5), ""
    except Exception as exc:  # noqa: BLE001
        if _backend_unreachable(exc):
            return None, ""
        return None, (f"调度程序没应答，没改（{type(exc).__name__}: {exc}）；"
                      "它开着时改文件，会被它用自己记着的那份盖回去")


def _refused(resp: Any) -> str:
    """The backend's own complaint about an update, or '' when it accepted it.

    AUTO-MAS v5.6.0 answers a failed update with HTTP 200 and `code: 500` in
    the body (app/api/scripts.py:288-306); while the script is running the
    message says 「正在运行, 无法更新配置项」 (app/core/config.py:1056). Only
    the read-back would catch it otherwise, and its text would hide why.
    """
    if isinstance(resp, dict) and "code" in resp and resp.get("code") != 200:
        return str(resp.get("message") or f"返回码 {resp.get('code')}")
    return ""


def _user_item_via_api(script: str, path: str, value: Any) -> "tuple[str, Any, Any]":
    """Write one per-user item through the backend and read it back.

    Returns (failure text, value before, value now); an empty failure text is
    success, and `before == value` means nothing needed writing.
    """
    try:
        sid, uid, user = _find_user(script)
    except Exception as exc:  # noqa: BLE001
        return f"找不到脚本或用户: {exc}", None, None
    try:
        before = _dig(user, path)
    except KeyError:
        return (f"「{script}」里没有 {path} 这一项，已拒绝"
                "（设置里本来没有它，中继不会自己新建）"), None, None
    if before == value:
        return "", before, before
    try:
        resp = _mas("/api/scripts/user/update",
                    {"scriptId": sid, "userId": uid, "data": _nest(path, value)})
    except Exception as exc:  # noqa: BLE001
        return f"写入失败: {exc}", before, None
    if why := _refused(resp):
        return f"调度程序没有接受这次修改：{why}", before, None
    try:
        users = _mas("/api/scripts/user/get", {"scriptId": sid})["data"]
        now = _dig(users[uid], path)
    except Exception as exc:  # noqa: BLE001
        return f"写进去了，但读出来核对时失败，没法确认: {exc}", before, None
    if now != value:
        return (f"写了但没生效：{script} 的 {path} 现在是 {now!r}，"
                f"不是 {value!r}"), before, now
    return "", before, now


def _user_item_report(script: str, path: str, value: Any) -> tuple[bool, str]:
    """_user_item_via_api, reported the way the file path reports it."""
    failed, before, now = _user_item_via_api(script, path, value)
    if failed:
        return False, failed
    if before == value:
        return True, "已经是这个状态，无需改动"
    return True, _humanize("/" + path.replace(".", "/"), before, now) + "（调度程序已确认）"


def _script_item_via_api(reply: Any, script: str, path: str,
                         value: Any) -> tuple[bool, str]:
    """Write one script-level item (not a user's) through the backend, read it back.

    `reply` is the `/api/scripts/get` answer the probe already fetched. The
    update sends only this one leaf: AUTO-MAS's ConfigBase.update
    (app/models/ConfigBase.py:1110) merges per group, so the rest of the group
    stays as it is.
    """
    scripts = reply.get("data") if isinstance(reply, dict) else None
    if not isinstance(scripts, dict):
        return False, "调度程序给的脚本列表读不懂，没有改"
    sid = next((k for k, sc in scripts.items() if isinstance(sc, dict)
                and str((sc.get("Info") or {}).get("Name") or "").lower() == script.lower()),
               None)
    if sid is None:
        return False, f"没有叫「{script}」的脚本"
    try:
        before = _dig(scripts[sid], path)
    except KeyError:
        return False, (f"「{script}」里没有 {path} 这一项，已拒绝"
                       "（设置里本来没有它，中继不会自己新建）")
    if before == value:
        return True, "已经是这个状态，无需改动"
    try:
        resp = _mas("/api/scripts/update", {"scriptId": sid, "data": _nest(path, value)})
    except Exception as exc:  # noqa: BLE001
        return False, f"写入失败: {exc}"
    if why := _refused(resp):
        return False, f"调度程序没有接受这次修改：{why}"
    try:
        now = _dig(_mas("/api/scripts/get")["data"][sid], path)
    except Exception as exc:  # noqa: BLE001
        return False, f"写进去了，但读出来核对时失败，没法确认: {exc}"
    if now != value:
        return False, f"写了但没生效：现在是 {now}"
    log.info("%s %s=%r via backend, read back", script, path, now)
    return True, _humanize("/" + path.replace(".", "/"), before, now) + "（调度程序已确认）"


def _set_config(cmd: dict) -> tuple[bool, str]:
    """Change any single config item. Every setting on the phone goes through this.

    Measured 2026-08-31: `/api/scripts/user/update` has **merge semantics** -
    it writes only the keys passed in and leaves the rest untouched (verified by
    saving the whole config, writing back the same value, and diffing the whole
    config).

    Three things are mandatory here and none may be skipped:
      * read the **current value** before changing it, so the report says
        "A -> B" rather than just B;
      * the path must actually exist in the current config, and is refused if it
        does not - no inventing fields out of thin air;
      * **read back and verify** after writing, checking whether that key really
        holds that value now.
    All three live in `_user_item_via_api` (shared with set_stage /
    set_medicine), which also refuses when the update reply carries a failure
    `code` in its body.
    """
    script = str(cmd.get("script") or "").strip()
    path = str(cmd.get("path") or "").strip()
    if not script or not path:
        return False, "set_config 需要 script 和 path"
    if "value" not in cmd:
        return False, "set_config 需要 value"
    value = cmd["value"]
    # Same gate as _set_stage: the phone's stage picker writes Info.Stage through here.
    if path in _STAGE_PATHS and isinstance(value, str) and value.strip() not in ("-", "") and _is_maa(script):
        if why := _stage_refusal("" if value.strip() == "*" else value.strip()):
            return False, why
    failed, before, now = _user_item_via_api(script, path, value)
    if failed:
        return False, failed
    if before == value:
        return True, f"{script} 的 {path} 本来就是 {value!r}，没有改动"
    return True, f"{script} 的 {path}：{before!r} → {now!r}"


def _set_master(cmd: dict) -> tuple[bool, str]:
    """Change the script's own config (the master copy).

    Endfield and Wuthering Waves have 「快速配置」 turned off, so those fields in
    the MAS user config are never pushed down at all (evidence at the top of the
    mastercfg module). On the phone, those two sections edit the master copy,
    not MAS.
    """
    from ark_relay.core import mastercfg  # noqa: PLC0415
    game = str(cmd.get("game") or "").strip()
    path = str(cmd.get("path") or "").strip()
    if not game or not path or "value" not in cmd:
        return False, "set_master 需要 game、path 和 value"
    automas = os.environ.get("ARK_AUTOMAS_DIR")
    if not automas:
        return False, "ARK_AUTOMAS_DIR 未设置"
    try:
        if game == "MaaEnd":
            from ark_relay.core.config import Config  # noqa: PLC0415
            return mastercfg.write_maaend(automas, Config().maaend_dir,
                                          path, cmd["value"])
        if game == "OK-WW":
            from ark_relay.core.config import Config  # noqa: PLC0415
            return mastercfg.write_okww(automas, path, cmd["value"], Config().okww_dir)
        if game == "MAA":
            from ark_relay.core.config import Config  # noqa: PLC0415
            return mastercfg.write_maa(automas, Config().maa_dir, path, cmd["value"])
    except Exception as exc:  # noqa: BLE001
        return False, f"写母本失败: {type(exc).__name__}: {exc}"
    return False, f"不认识的游戏 {game!r}"


def mas_up() -> bool:
    """Whether the AUTO-MAS backend API is alive."""
    try:
        _mas("/api/queue/get", timeout=5)
        return True
    except Exception:  # noqa: BLE001
        return False


def _queue_id(queue: str) -> str:
    for qid, q in _mas("/api/queue/get")["data"].items():
        if str((q.get("Info") or {}).get("Name") or "") == queue:
            return qid
    raise KeyError(f"没有叫「{queue}」的队列")


def _script_id(script: str) -> str:
    for sid, sc in _mas("/api/scripts/get")["data"].items():
        if str((sc.get("Info") or {}).get("Name") or "").lower() == script.lower():
            return sid
    raise KeyError(f"没有叫「{script}」的脚本")


# The weekday words a queue item's Schedule.Days takes: AUTO-MAS
# app/models/schema.py QueueItem_Schedule.Days (a Literal of these seven) and
# config.py QueueItem.Schedule_Days (default: all of them, calendar.day_name).
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _item_days(item: dict) -> list[str]:
    """The item's Schedule.Days; an item that never set it runs every day (AUTO-MAS's default)."""
    days = (item.get("Schedule") or {}).get("Days")
    return [d for d in days if d in WEEKDAYS] if isinstance(days, list) else list(WEEKDAYS)


def _queue_item(qid: str, uid: str = "", sid: str = "") -> tuple[str | None, int, dict]:
    """(item uid, position, item) by item uid, else by script id; (None, -1, {}) when absent."""
    items = _mas("/api/queue/item/get", {"queueId": qid})
    order = [i["uid"] for i in items["index"]]
    data = items.get("data") or {}
    if uid and uid in order:
        return uid, order.index(uid), data.get(uid) or {}
    for pos, u in enumerate(order):
        if ((data.get(u) or {}).get("Info") or {}).get("ScriptId") == sid:
            return u, pos, data.get(u) or {}
    return None, -1, {}


def _write_item_days(qid: str, uid: str, days: list[str]) -> None:
    """Write one item's Schedule.Days. Only Schedule is sent, so AUTO-MAS's
    running-queue guard (Config.update_queue_item, which checks only an Info
    change) does not refuse it and no other field is touched."""
    r = _mas("/api/queue/item/update", {"queueId": qid, "queueItemId": uid,
                                        "data": {"Schedule": {"Days": days}}})
    if str(r.get("status")) != "success":
        raise RuntimeError(f"调度程序拒绝改运行日：{r.get('message')}")


class SkipError(RuntimeError):
    """A today-only skip that failed after a Schedule.Days write may have gone out.

    `recs` are the undo records of the items that may have changed (those
    already skipped, and the one that failed); the caller keeps them
    (gameupdate._add_skip) so the weekday is put back like any other skip,
    instead of staying removed for good. str() is the failure text alone.
    """

    def __init__(self, msg: str, recs: list[dict]):
        super().__init__(msg)
        self.recs = recs


def skip_script_in_queue(queue: str, script: str, uid: str = "") -> dict | None:
    """Skip one script in a queue for today only; returns the record needed to undo it.

    Used on maintenance days for "do not run it in today's queue" - the user,
    2026-09-03: 「当天队列里不跑他」. The item stays in the queue: today's weekday is
    dropped from its Schedule.Days, and AUTO-MAS skips an item whose days do not
    include the weekday it froze when the queue task was created
    (task_manager.py _is_script_scheduled_today; machine-local time, which is
    server time). None when the script is not in the queue or already does not
    run today - then there is nothing of ours to undo, and a second skip the
    same day (stage gate after a game update) cannot record an already-trimmed
    list as the original. The record carries the server day and the original
    days, so restore_script_in_queue writes them back verbatim, even on a later
    day (relay crash, power-off before the re-run).

    This skips one item: the one with id `uid`, else the first item of the
    script. skip_script_all_items skips every item of the script in the queue.
    """
    qid, sid = _queue_id(queue), _script_id(script)
    uid, pos, item = _queue_item(qid, uid=uid, sid=sid)
    if uid is None:
        return None
    now = datetime.now(tz=SERVER_TZ)
    today = WEEKDAYS[now.weekday()]
    days = _item_days(item)
    if today not in days:
        log.info("队列「%s」里的 %s 今天本来就不跑（运行日 %s），不用跳过", queue, script, "、".join(days) or "无")
        return None
    run_days = [d for d in days if d != today]
    # The record is made before the write: once the write is sent, a failure
    # (a read-back that times out, a write whose reply is lost) may leave the
    # weekday removed, and only this record puts it back. Restoring an item
    # that did not change is a no-op (restore_script_in_queue compares first).
    rec = {"queue": queue, "queueId": qid, "queueItemId": uid, "script": script, "scriptId": sid,
           "position": pos, "day": now.strftime("%Y-%m-%d"), "days": days}
    try:
        _write_item_days(qid, uid, run_days)
        _, _, back = _queue_item(qid, uid=uid)
    except Exception as exc:  # noqa: BLE001 - re-raised with the record attached
        raise SkipError(str(exc), [rec]) from exc
    if today in _item_days(back):
        raise SkipError(f"跳不掉：改了运行日之后读回来，{today} 还在里面", [rec])
    log.info("队列「%s」今天跳过 %s（第 %d 项，运行日去掉 %s）", queue, script, pos + 1, today)
    return rec


def skip_script_all_items(queue: str, script: str) -> list[dict]:
    """Skip, for today only, every item of `script` in `queue`; one record per item.

    A script can sit in a queue more than once (two items with the same
    ScriptId); skipping only the first would leave the others running today.
    Items that already leave today out are not touched and get no record, for
    the reason given in skip_script_in_queue. A failure on any item raises
    SkipError carrying the records of the items already changed and of the
    failed one, so the caller can keep them.
    """
    qid, sid = _queue_id(queue), _script_id(script)
    items = _mas("/api/queue/item/get", {"queueId": qid})
    data = items.get("data") or {}
    uids = [i["uid"] for i in items.get("index") or []
            if ((data.get(i["uid"]) or {}).get("Info") or {}).get("ScriptId") == sid]
    recs: list[dict] = []
    for uid in uids:
        try:
            rec = skip_script_in_queue(queue, script, uid=uid)
        except Exception as exc:  # noqa: BLE001 - re-raised with every record made so far
            raise SkipError(str(exc), recs + list(getattr(exc, "recs", []))) from exc
        if rec:
            recs.append(rec)
    return recs


def restore_script_in_queue(rec: dict) -> bool:
    """Write back the run days the skip_script_in_queue record saved, and read them back."""
    if not isinstance(rec.get("days"), list):
        # A record from before 2026-10-11, when a skip deleted the item
        # (item/delete). There is no item to give its days back to; a WARNING
        # reaches the group so the item can be added back by hand, and True drops
        # the record instead of failing on it at every boot.
        log.warning("%s", texts.queue_item_deleted_old_way(str(rec.get("queue")), str(rec.get("script"))))
        return True
    qid, want = rec["queueId"], list(rec["days"])
    uid, _, item = _queue_item(qid, uid=str(rec.get("queueItemId") or ""), sid=str(rec.get("scriptId") or ""))
    if uid is None:
        log.warning("队列「%s」里找不到 %s 这一项了，没法改回它的运行日，在它回到队列之前这个队列不会跑它",
                    rec["queue"], rec["script"])
        return False
    if _item_days(item) != want:
        _write_item_days(qid, uid, want)
        _, _, item = _queue_item(qid, uid=uid)
    ok = _item_days(item) == want
    if ok:
        log.info("队列「%s」已把 %s 的运行日改回 %s", rec["queue"], rec["script"], "、".join(want))
    else:
        # A WARNING, so it reaches the group (errwatch): until it is back, that game
        # does not run in this queue on that weekday. The caller keeps the record and retries.
        log.warning("队列「%s」没能把 %s 的运行日改回去（改了之后读回来还是 %s），在改回之前这个队列那天不会跑它，中继会再试",
                    rec["queue"], rec["script"], "、".join(_item_days(item)) or "无")
    return ok


def _note_dispatch(what: str) -> None:
    """AUTO-MAS labels this start 「manual_task」 like a click on its own screen; note it as
    the relay's, so its failures keep their alarms (trigger.py)."""
    from ark_relay.features.guard import trigger  # noqa: PLC0415
    trigger.note_dispatch(Path(os.environ.get("ARK_STATE_DIR", "./ark-state")), what)


def _overlay_before_start(where: str) -> None:
    """Put a skipped OK-WW overlay in place before the relay itself starts a run
    (okww_overlay.retry_pending; a no-op unless an install is waiting). Never stops
    the dispatch."""
    try:
        from ark_relay.features.okww_patch import okww_overlay  # noqa: PLC0415
        okww_overlay.retry_pending(where)
    except Exception:      # the dispatch goes ahead regardless
        log.exception("%s：重装 OK-WW 改动文件这一步自己出错", where)


def run_script(script: str) -> tuple[bool, str]:
    """Dispatch a single script (not a whole queue) through the AUTO-MAS dispatch API.

    Used when one game has to be re-run after its client update. Dispatching the
    whole queue would run the other games again too (and spend their stamina).
    """
    try:
        scripts = _mas("/api/scripts/get")["data"]
    except Exception as exc:  # noqa: BLE001
        return False, f"取不到脚本列表: {exc}"
    for sid, sc in scripts.items():
        if str((sc.get("Info") or {}).get("Name") or "").lower() != script.lower():
            continue
        _note_dispatch(f"脚本 {script}")
        _overlay_before_start(f"单独开跑「{script}」前")
        try:
            r = _mas("/api/dispatch/start", {"taskId": sid, "mode": "AutoProxy"})
        except Exception as exc:  # noqa: BLE001
            return False, f"脚本「{script}」没能启动: {exc}"
        if str(r.get("status")) != "success":
            return False, f"脚本「{script}」没能启动: {r.get('message')}"
        return True, f"脚本「{script}」已单独开跑"
    return False, f"没有叫「{script}」的脚本"


def _run_now(queue: str) -> tuple[bool, str]:
    """Run one round of a queue right now, through the AUTO-MAS dispatch API."""
    queue = names.canonical(queue)
    try:
        queues = _mas("/api/queue/get")["data"]
    except Exception as exc:  # noqa: BLE001
        return False, f"取不到队列列表: {exc}"
    have = []      # do not call this `names`: it would shadow the module (see the comment in queues.apply)
    for qid, q in queues.items():
        name = str((q.get("Info") or {}).get("Name") or "")
        have.append(name)
        if name == queue:
            _note_dispatch(f"队列 {queue}")
            _overlay_before_start(f"开跑队列「{queue}」前")
            try:
                # The only valid values for mode are AutoProxy / ScriptConfig /
                # Update (TaskCreateIn in app/models/schema.py); anything else
                # gets a 422.
                r = _mas("/api/dispatch/start",
                         {"taskId": qid, "mode": "AutoProxy"})
            except Exception as exc:  # noqa: BLE001
                return False, f"队列「{queue}」没能启动: {exc}"
            if str(r.get("status")) != "success":
                return False, f"队列「{queue}」没能启动: {r.get('message')}"
            return True, f"队列「{queue}」已开始跑"
    return False, f"没有叫「{queue}」的队列（有的是：{'、'.join(have)}）"


def _skip_today(queue: str, want_day: str = "") -> tuple[bool, str]:
    # Must use the server clock: across time zones, or close to midnight, the
    # host's own local date lands on the wrong day.
    day = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    # The command travels through the inbox and is collected at the NEXT boot,
    # which may be the following morning - "skip today" queued at 23:00 after
    # the runs would then silently skip a day the operator never named. A
    # command carrying its intended date is refused once that date has passed.
    if want_day and want_day != day:
        return False, (f"skip_today 指定的是 {want_day}，今天已是 {day}——"
                       "指令在收件箱里过期了，未生效。需要就重新排一条")
    queue = names.canonical(queue)
    from ark_relay.features.modes import modes  # noqa: PLC0415
    state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
    # The page has one skip switch per queue, so a day holds several queues; a
    # second skip is added, not written over the first.
    if queue in modes.skipped_today_all(state_dir):
        return True, f"今天（{day}）已经在跳过队列「{queue}」"
    # Atomic write: an empty value would be read as the default queue name, so a
    # torn write means skipping a queue nobody asked to skip.
    modes.add_day_queue(state_dir, day, queue)
    return True, f"今天（{day}）将跳过队列「{queue}」"


def apply_command(cmd: dict) -> tuple[bool, str]:
    """Validate and apply one command. Never raises; always reports.

    `cmd` arrives over the network and is untrusted: every field is checked
    before anything touches disk.
    """
    action = str(cmd.get("action") or "").strip()
    if action not in ALLOWED:
        return False, texts.action_not_allowed(action)

    # Gate ②: mutating actions must carry the operator's confirmation.
    if action in MUTATING and not cmd.get("confirmed"):
        return False, texts.action_needs_confirm(action)

    try:
        if action == "set_stage":
            return _set_stage(cmd.get("value", ""))
        if action == "set_medicine":
            return _set_medicine(cmd.get("value"))
        if action == "set_wait_time":
            return _set_wait_time(cmd.get("value"))
        if action == "toggle_task":
            return _toggle_task(str(cmd.get("name", "")), bool(cmd.get("on")))
        if action == "run_now":
            return _run_now(str(cmd.get("queue") or names.MORNING))
        if action == "skip_today":
            return _skip_today(str(cmd.get("queue") or names.MORNING),
                               str(cmd.get("day") or "").strip())
        if action == "unskip_today":
            # The phone's skip switch turned back on: drop the flag, or re-enable
            # the queue if the skip already engaged.
            from ark_relay.features.modes.modes import unskip  # noqa: PLC0415
            return unskip(Path(os.environ.get("ARK_STATE_DIR", "./ark-state")),
                          os.environ.get("ARK_AUTOMAS_DIR"),
                          str(cmd.get("queue") or names.MORNING))
        if action == "debug_mode":
            from ark_relay.features.modes.modes import set_debug  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            # "cycles" counts scheduled power-ons to sit out; "days" is the
            # old spelling and is still honoured so an older inbox file keeps
            # working. One cycle - the default - means "until ten minutes
            # before the next boot", not "until midnight".
            n = cmd.get("cycles", cmd.get("days", 1))
            return set_debug(state_dir, n, bool(cmd.get("off")))
        if action == "set_config":
            return _set_config(cmd)
        if action == "set_master":
            return _set_master(cmd)
        if action == "weekly_boss":
            # The Wuthering Waves weekly boss (战歌重奏). Same setup as
            # annihilation and the weekly garden: once the quota is full it is
            # removed automatically and hung back on Monday at 04:00.
            # The only thing that can be changed is which one to fight: 3 times a
            # week at level 90 is fixed (per the user, 2026-09-07).
            from ark_relay.features.weekly.weeklyboss import WeeklyBossGate  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            gate = WeeklyBossGate(state_dir, os.environ.get("ARK_AUTOMAS_DIR"))
            ok, msg = gate.configure(index=cmd.get("index"))
            if ok:
                gate.enforce()
            return ok, msg
        if action == "echo_farm":
            # Farm one overworld boss for its 4-cost echoes until a wall-clock time.
            # The count OK-WW understands is set high; echofarm owns the clock.
            from ark_relay.features.echofarm import echofarm  # noqa: PLC0415
            from ark_relay.core.config import Config  # noqa: PLC0415
            from ark_relay.core.wuwa_boss import label  # noqa: PLC0415
            # "sent" (the phone's send time, put in by run_phone_cmd) makes a
            # backlog order mean the deadline its sender meant - see echofarm.start.
            sent = cmd.get("sent")
            sent = datetime.fromtimestamp(sent, tz=SERVER_TZ) if isinstance(sent, int) else None
            return echofarm.start(Config(), cmd.get("boss"), cmd.get("until"),
                                  str(cmd.get("name") or "") or label(cmd.get("boss")), sent=sent)
        if action == "echo_farm_until":
            from ark_relay.features.echofarm.echofarm import retime  # noqa: PLC0415
            from ark_relay.core.config import Config  # noqa: PLC0415
            return retime(Config(), cmd.get("until"))
        if action == "echo_farm_stop":
            from ark_relay.features.echofarm import echofarm  # noqa: PLC0415
            from ark_relay.core.config import Config  # noqa: PLC0415
            cfg = Config()
            note = echofarm.finish(cfg, "手动停止")
            return (True, note) if note else (True, "本来就没有在刷声骸")
        if action == "monthcard":
            from ark_relay.features.phone import monthcard  # noqa: PLC0415
            return monthcard.apply(Path(os.environ.get("ARK_STATE_DIR", "./ark-state")), cmd)
        if action == "tacet_shots":
            from ark_relay.features.modes.modes import set_tacet_shots  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            return True, set_tacet_shots(state_dir, bool(cmd.get("on", False)))
        if action == "skip_shutdown":
            # The one-shot 「下次跑完不关机」 mark (phone switch, desktop .bat). No
            # expiry: it is spent when the next 早班/晚班 run finishes, that
            # occasion is skipped (re-checks after it do not power off), and the
            # run after that shuts down as usual. Once spent there is nothing to
            # cancel; "off" only pulls back a mark not yet spent. See
            # modes.skip_armed.
            # The user, 2026-08-31, wanting a control a human can use without me:
            # 「你给一个人类好去调这个模式的方法， (a way for a person to set this mode,
            # 独立于你的」「我要的是手机上面操作」 (independent of me, operated on the phone).
            from ark_relay.features.modes.modes import set_skip_shutdown  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            # Both spellings of "pull back" are accepted. The canonical form is
            # off:true, but other actions (weekly_boss / toggle_task) use `on`,
            # and two spellings in one interface get sent wrongly sooner or
            # later, so both are treated as cancel.
            off = bool(cmd.get("off")) or cmd.get("on") is False
            if not off:
                # Pressed inside the relay's own 60-second power-off countdown,
                # where storing the mark would be too late: cancel the countdown.
                # That uses the order up on this shutdown, so no mark is stored.
                from ark_relay.features.shutdown import shutdown  # noqa: PLC0415
                outcome, text = shutdown.abort_countdown()
                if outcome == "aborted":
                    return True, text
                if outcome == "failed":
                    return False, text
            return set_skip_shutdown(state_dir, not off)
    except Exception as exc:
        log.exception("执行指令失败: %s", action)
        return False, f"执行出错: {exc}"
    return False, f"未处理的动作: {action}"
