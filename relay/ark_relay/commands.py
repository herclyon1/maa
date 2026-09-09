"""Applying commands to AUTO-MAS config - the guarded path.

Four gates, none optional (relay/README.md, "The four gates on commands"):

  ① whitelist (白名单)
      the model emits an action name from a fixed table, never a JSON patch
  ② operator confirmation (人工确认)
      config-mutating actions wait for the operator's OK; reversible ones
      (run_now / skip_today) go straight through
  ③ write-back validation (落地校验)
      backup -> edit -> json.loads -> structural diff; anything unexpected
      rolls back
  ④ reporting (回报)
      success, failure and rejection all get reported

Gate ③ exists because it has already caught a real mistake: a regex meant to
disable three webhook tasks disabled two and damaged an unrelated section.
The diff caught it; care did not.
"""
from __future__ import annotations

import json
import logging
import os

from . import names
import re
import urllib.request
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.commands")

# ---------- gate ① : the whitelist ----------

# Actions that only change what happens next, and undo themselves.
REVERSIBLE = {"skip_today", "debug_mode", "skip_shutdown", "weekly_boss", "echo_farm_stop",
              "echo_farm_until"}

# Actions that write to a config file on disk.
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


# Config field -> plain words. The push is read by a person on a phone, and
# something like `/59da8762-8fa7-.../Game/WaitTime` means nothing at all to
# the person reading it (operator feedback from real use, 2026-08-20).
_FIELD_LABELS = {
    "Stage": "刷取关卡",
    "MedicineNumb": "理智药上限",
    "WaitTime": "终末地启动后等待",
    "Annihilation": "剿灭",
    "TimeEnabled": "队列定时",
    "Enabled": "启用",
    "RunTimesLimit": "失败重试上限",
    "StageMode": "选关模式",
}
_FIELD_UNITS = {"WaitTime": " 秒", "MedicineNumb": " 个"}


def _humanize(path: str, before: Any, after: Any) -> str:
    """'/x/Game/WaitTime', 60, 120 -> '终末地启动后等待：60 秒 → 120 秒'"""
    field = path.rsplit("/", 1)[-1]
    label = _FIELD_LABELS.get(field, field)
    unit = _FIELD_UNITS.get(field, "")
    fmt = lambda v: f"{v}{unit}" if not isinstance(v, bool) else ("开" if v else "关")  # noqa: E731
    return f"{label}：{fmt(before)} → {fmt(after)}"


def _flatten(obj: Any, path: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{path}/{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{path}[{i}]"))
    else:
        out[path] = obj
    return out


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
            f"结构化 diff 不符预期，已放弃："
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

def _set_stage(value: str) -> tuple[bool, str]:
    stage = str(value).strip().upper()
    if not _STAGE_RE.match(stage):
        return False, f"关卡格式不合法: {value!r}（应形如 TO-5 / CE-6 / 1-7）"

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

    def mutate(raw: str) -> str:
        hits = re.findall(r'"MedicineNumb":\s*\d+', raw)
        if len(hits) != 1:
            raise ValueError(f'找到 {len(hits)} 处 "MedicineNumb"，预期恰好 1 处')
        return re.sub(r'("MedicineNumb":\s*)\d+', rf"\g<1>{n}", raw, count=1)

    return _safe_rewrite(_script_config(), mutate, expect_changed=1)


def _set_wait_time(value: Any) -> tuple[bool, str]:
    """MaaEnd's "seconds to wait after the game starts" - the one and only
    Game/WaitTime in ScriptConfig.

    Why this knob exists here: every fresh boot the first MaaEnd attempt died
    within seconds of connecting - the game recreates its window during first
    startup and MaaEnd grabs the doomed early handle (2026-08-20 log
    forensics, docs/PITFALLS.md). Waiting past the recreation window is
    the fix; the retry mechanism was papering over it once per day.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return False, f"等待秒数不是整数: {value!r}"
    # AUTO-MAS's own schema declares this field as `ge=60`
    # (app/models/schema.py). Anything smaller is not rejected loudly - it is
    # accepted, written to disk, and then silently clamped back to 60 the next
    # time AUTO-MAS starts. Refusing here turns an invisible revert into a
    # clear message (measured 2026-08-21: 30 became 60 on the next launch).
    if not 60 <= n <= 600:
        return False, f"等待秒数超出范围 60–600: {n}（AUTO-MAS 最小值就是 60，写小了会被它改回去）"

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


# The address has exactly one source; see config.mas_base()
def _mas_api() -> str:
    from .config import mas_base  # noqa: PLC0415 - avoids an import cycle
    return mas_base()


def _mas(path: str, body: "dict | None" = None, timeout: int = 20) -> dict:
    """The AUTO-MAS backend. **Every endpoint is POST**, including the reads.

    Go through the API rather than editing files: while the backend is running
    it overwrites the file from its in-memory copy, so a value written straight
    into the file is silently wiped out.
    """
    req = urllib.request.Request(
        _mas_api() + path, data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


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


def _dig(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def _nest(path: str, value) -> dict:
    out: dict = {}
    cur = out
    parts = path.split(".")
    for part in parts[:-1]:
        cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
    return out


def _set_config(cmd: dict) -> tuple[bool, str]:
    """Change any single config item. Every setting on the phone goes through this.

    Measured 2026-08-31: `/api/scripts/user/update` has **merge semantics** -
    it writes only the keys passed in and leaves the rest untouched (verified by
    saving the whole config, writing back the same value, and diffing the whole
    config).

    Three things are mandatory here and none may be skipped - 826 happened
    because they were:
      * read the **current value** before changing it, so the report says
        "A -> B" rather than just B;
      * the path must actually exist in the current config, and is refused if it
        does not - no inventing fields out of thin air;
      * **read back and verify** after writing, checking whether that key really
        holds that value now.
    """
    script = str(cmd.get("script") or "").strip()
    path = str(cmd.get("path") or "").strip()
    if not script or not path:
        return False, "set_config 需要 script 和 path"
    if "value" not in cmd:
        return False, "set_config 需要 value"
    value = cmd["value"]
    try:
        sid, uid, user = _find_user(script)
    except Exception as exc:  # noqa: BLE001
        return False, f"找不到脚本或用户: {exc}"
    try:
        before = _dig(user, path)
    except KeyError:
        return False, (f"「{script}」里没有 {path} 这一项，已拒绝"
                       "（不许凭空造字段——826 就是这么出的事）")
    if before == value:
        return True, f"{script} 的 {path} 本来就是 {value!r}，没有改动"
    try:
        _mas("/api/scripts/user/update",
             {"scriptId": sid, "userId": uid, "data": _nest(path, value)})
    except Exception as exc:  # noqa: BLE001
        return False, f"写入失败: {exc}"
    try:
        users = _mas("/api/scripts/user/get", {"scriptId": sid})["data"]
        now = _dig(users[uid], path)
    except Exception as exc:  # noqa: BLE001
        return False, f"写了但回读不了，无法确认: {exc}"
    if now != value:
        return False, (f"写了但没生效：{script} 的 {path} 现在是 {now!r}，"
                       f"不是 {value!r}")
    return True, f"{script} 的 {path}：{before!r} → {now!r}"


def _set_master(cmd: dict) -> tuple[bool, str]:
    """Change the script's own config (the master copy).

    Endfield and Wuthering Waves have 「快速配置」 turned off, so those fields in
    the MAS user config are never pushed down at all (evidence at the top of the
    mastercfg module). On the phone, those two sections edit the master copy,
    not MAS.
    """
    from . import mastercfg  # noqa: PLC0415
    game = str(cmd.get("game") or "").strip()
    path = str(cmd.get("path") or "").strip()
    if not game or not path or "value" not in cmd:
        return False, "set_master 需要 game、path 和 value"
    automas = os.environ.get("ARK_AUTOMAS_DIR")
    if not automas:
        return False, "ARK_AUTOMAS_DIR 未设置"
    try:
        if game == "MaaEnd":
            from .config import Config  # noqa: PLC0415
            return mastercfg.write_maaend(automas, Config().maaend_dir,
                                          path, cmd["value"])
        if game == "OK-WW":
            return mastercfg.write_okww(automas, path, cmd["value"])
        if game == "MAA":
            from .config import Config  # noqa: PLC0415
            return mastercfg.write_maa(automas, Config().maa_dir, path, cmd["value"])
    except Exception as exc:  # noqa: BLE001
        return False, f"写母本失败: {type(exc).__name__}: {exc}"
    return False, f"不认识的游戏 {game!r}"


# What the red button has to leave dead. MaaEnd has no process of its own, so
# Endfield.exe stands in for it; Games.exe is the Endfield launcher, which is what
# runs on a client-update day. 鸣潮 shows up under three names and none of them is
# ok-ww.exe, which is why the 08-26 verification passed while the game was running.
# exe -> what to call it when telling the operator. The push has to be in Chinese
# and a process name is not something he should have to decode at a glance.
_ESTOP_NAMES = {
    "MAA.exe": "明日方舟的脚本",
    "MaaEnd.exe": "终末地的脚本",
    "dnplayer.exe": "雷电模拟器",
    "Endfield.exe": "终末地",
    "Games.exe": "终末地启动器",
    "ok-ww.exe": "鸣潮的脚本",
    "Wuthering Waves.exe": "鸣潮",
    "Client-Win64-Shipping.exe": "鸣潮",
    "KRSDKExternal.exe": "鸣潮的登录组件",
}
_ESTOP_EXES = tuple(_ESTOP_NAMES)


def _estop_alive() -> list[str]:
    """Which of those are still alive. Empty means nothing is left.

    On a machine where the process list cannot be read, every name is reported as
    still alive: not knowing must never read as "all clear".
    """
    import subprocess  # noqa: PLC0415
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=20).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ["进程表读不到"]
    low = out.lower()
    return [e for e in _ESTOP_EXES if e.lower() in low]


def _estop_stop_via_mas() -> list[str]:
    """Ask AUTO-MAS to stop every queue and script. Returns the names it accepted."""
    stopped: list[str] = []
    try:
        ids = {str((v.get("Info") or {}).get("Name") or ""): sid
               for sid, v in _mas("/api/scripts/get")["data"].items()}
        ids.update({str((q.get("Info") or {}).get("Name") or ""): qid
                    for qid, q in _mas("/api/queue/get")["data"].items()})
        for name, tid in ids.items():
            try:
                _mas("/api/dispatch/stop", {"taskId": tid})
                stopped.append(name)
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        log.warning("红按钮：AUTO-MAS 接口停不了（%s），直接杀进程", exc)
    return stopped


def _estop_kill() -> None:
    import subprocess  # noqa: PLC0415
    from .preupdate_okww import _okww_quiesce  # noqa: PLC0415
    for exe in _ESTOP_EXES:
        subprocess.run(["taskkill", "/IM", exe, "/T", "/F"], capture_output=True)
    _okww_quiesce()


def estop(sleep=None) -> tuple[bool, str]:
    """The red button: stop every script and game. The red one on the phone page.

    The order is copied from scripts/windows/dispatch_guard.py (bought with the
    mess of the morning of 2026-09-01):
    (1) stop everything through the AUTO-MAS API (queues and scripts both, so it
    does not treat this as a fault and retry); (2) wait 12 seconds, and only
    taskkill what is left; (3) check again whether anything was relaunched, and
    if so run another stop round.

    Step (3) was missing here for as long as this function existed, and so was any
    check at all: it killed twice and then returned a hard-coded 「已停一切」.
    That is the exact shape of 2026-08-26, whose conclusion in the user's own words
    was 「你没有进行任何有效的停止行为，全是我手动关的」 - except that this version
    also pushes him a success message. AUTO-MAS relaunches the whole queue when a
    member is killed under it, so "killed it twice" says nothing about whether
    anything is still running half a minute later.

    Killing AUTO-MAS itself is deliberately NOT done here: service.py's reviver
    holds its process handle and brings it back within seconds. When the relay
    cannot get the machine quiet, the honest answer is to say so and let the
    operator use scripts/mac/estop.sh, which stops this service first.
    """
    import time  # noqa: PLC0415
    sleep = sleep or time.sleep

    stopped = _estop_stop_via_mas()
    sleep(12 if stopped else 2)
    _estop_kill()
    sleep(6)
    _estop_kill()
    sleep(6)

    alive = _estop_alive()
    if alive:
        # Relaunched from under us: another stop round, then the truth either way.
        log.warning("红按钮：杀完还活着 %s，再停一轮", alive)
        _estop_stop_via_mas()
        sleep(8)
        _estop_kill()
        sleep(6)
        alive = _estop_alive()

    head = "、".join(stopped) if stopped else "接口没停到东西"
    if alive:
        zh = sorted({_ESTOP_NAMES.get(a, a) for a in alive})
        return False, (f"没能停干净。接口这边：{head}。"
                       f"还活着：{'、'.join(zh)}。"
                       "调度器会把被停掉的队列整队重试，中继自己压不住它——"
                       "请到电脑上跑那个紧急停止的脚本，它会先把中继停掉再动手。")
    return True, f"已停一切：{head}；脚本和游戏都确认没了"


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


def skip_script_in_queue(queue: str, script: str) -> dict | None:
    """Pull one script out of a queue (through the AUTO-MAS API); returns the record needed to put it back.

    Used on maintenance days for "do not run it in today's queue". Measured on
    the 早班 queue on 2026-09-03: item/delete takes it out, and
    item/add -> item/update(ScriptId) -> item/order puts it back exactly as it was.
    """
    qid, sid = _queue_id(queue), _script_id(script)
    items = _mas("/api/queue/item/get", {"queueId": qid})
    order = [i["uid"] for i in items["index"]]
    target = next((u for u in order if (items["data"].get(u, {}).get("Info") or {}).get("ScriptId") == sid), None)
    if target is None:
        return None
    r = _mas("/api/queue/item/delete", {"queueId": qid, "queueItemId": target})
    if str(r.get("status")) != "success":
        raise RuntimeError(f"摘不掉：{r.get('message')}")
    rec = {"queue": queue, "queueId": qid, "script": script, "scriptId": sid, "position": order.index(target)}
    log.info("队列「%s」今天摘掉 %s（原第 %d 位）", queue, script, rec["position"] + 1)
    return rec


def restore_script_in_queue(rec: dict) -> bool:
    """Add it back per the skip_script_in_queue record, restoring its position too."""
    qid, sid = rec["queueId"], rec["scriptId"]
    items = _mas("/api/queue/item/get", {"queueId": qid})
    order = [i["uid"] for i in items["index"]]
    if any((items["data"].get(u, {}).get("Info") or {}).get("ScriptId") == sid for u in order):
        return True                                   # already there
    r = _mas("/api/queue/item/add", {"queueId": qid})
    uid = r.get("queueItemId")
    if not uid:
        raise RuntimeError(f"加不回：{r.get('message')}")
    _mas("/api/queue/item/update", {"queueId": qid, "queueItemId": uid, "data": {"Info": {"ScriptId": sid}}})
    pos = min(int(rec.get("position", len(order))), len(order))
    _mas("/api/queue/item/order", {"queueId": qid, "indexList": order[:pos] + [uid] + order[pos:]})
    back = _mas("/api/queue/item/get", {"queueId": qid})
    ok = any((back["data"].get(u, {}).get("Info") or {}).get("ScriptId") == sid for u in (i["uid"] for i in back["index"]))
    log.info("队列「%s」已把 %s 加回第 %d 位：%s", rec["queue"], rec["script"], pos + 1, "成功" if ok else "失败")
    return ok


def run_script(script: str) -> tuple[bool, str]:
    """Dispatch a single script (not a whole queue) through the AUTO-MAS dispatch API.

    Used when one game has to be re-run after its client update. Dispatching the
    whole queue would run the other games again too - that is exactly how MAA
    got an extra run on 2026-09-01, and burned sanity potions doing it.
    """
    try:
        scripts = _mas("/api/scripts/get")["data"]
    except Exception as exc:  # noqa: BLE001
        return False, f"取不到脚本列表: {exc}"
    for sid, sc in scripts.items():
        if str((sc.get("Info") or {}).get("Name") or "").lower() != script.lower():
            continue
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
            try:
                # The only valid values for mode are AutoProxy / ScriptConfig /
                # Update (TaskCreateIn in app/models/schema.py). On 2026-08-31 it
                # was written as 「队列」 and the API returned a flat 422 - pressing
                # "run a round now" on the phone did absolutely nothing.
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
    from .statestore import StateStore  # noqa: PLC0415
    # Atomic write: an empty value would be read as the default queue name, so a
    # torn write means skipping a queue nobody asked to skip.
    StateStore(Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))).set(
        "queues", f"skip_day:{day}", str(queue))
    return True, f"今天（{day}）将跳过队列「{queue}」"


def apply_command(cmd: dict) -> tuple[bool, str]:
    """Validate and apply one command. Never raises; always reports.

    `cmd` arrives over the network and is untrusted: every field is checked
    before anything touches disk.
    """
    action = str(cmd.get("action") or "").strip()
    if action not in ALLOWED:
        return False, f"动作不在白名单内，已拒绝: {action!r}"

    # Gate ②: mutating actions must carry the operator's confirmation.
    if action in MUTATING and not cmd.get("confirmed"):
        return False, f"动作 {action} 需要人工确认，未确认前不执行"

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
        if action == "debug_mode":
            from .modes import set_debug  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            # "cycles" counts scheduled power-ons to sit out; "days" is the
            # old spelling and is still honoured so an inbox file written
            # before 2026-08-23 keeps working. One cycle - the default - now
            # means "until ten minutes before the next boot", not "until
            # midnight", which is what the operator meant all along.
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
            from .weeklyboss import WeeklyBossGate  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            gate = WeeklyBossGate(state_dir, os.environ.get("ARK_AUTOMAS_DIR"))
            ok, msg = gate.configure(index=cmd.get("index"))
            if ok:
                gate.enforce()
            return ok, msg
        if action == "echo_farm":
            # Farm one overworld boss for its 4-cost echoes until a wall-clock time.
            # The count OK-WW understands is set high; echofarm owns the clock.
            from . import echofarm  # noqa: PLC0415
            from .config import Config  # noqa: PLC0415
            from .wuwa_boss import label  # noqa: PLC0415
            return echofarm.start(Config(), cmd.get("boss"), cmd.get("until"),
                                  str(cmd.get("name") or "") or label(cmd.get("boss")))
        if action == "echo_farm_until":
            from .echofarm import retime  # noqa: PLC0415
            from .config import Config  # noqa: PLC0415
            return retime(Config(), cmd.get("until"))
        if action == "echo_farm_stop":
            from . import echofarm  # noqa: PLC0415
            from .config import Config  # noqa: PLC0415
            cfg = Config()
            note = echofarm.finish(cfg, "手动停止")
            return (True, note) if note else (True, "本来就没有在刷声骸")
        if action == "skip_shutdown":
            # The 「今晚别关机」 button on the phone. It carries no expiry: it eats
            # the **next** shutdown that would actually be executed, once, and is
            # spent after that - the queue after it shuts down as usual.
            # The user, 2026-08-31: 「你给一个人类好去调这个模式的方法，
            # 独立于你的」「我要的是手机上面操作」.
            from .modes import set_skip_shutdown  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            # Both spellings of "cancel" are accepted. The canonical form is
            # off:true, but other actions (weekly_boss / toggle_task) use `on`,
            # and two spellings in one interface get sent wrongly sooner or
            # later. Measured 2026-08-31: the phone only had 「开」 and no
            # 「取消」, and sending on:false was read as 「开」. Be liberal: treat
            # both as cancel.
            off = bool(cmd.get("off")) or cmd.get("on") is False
            return set_skip_shutdown(state_dir, not off)
    except Exception as exc:
        log.exception("执行指令失败: %s", action)
        return False, f"执行出错: {exc}"
    return False, f"未处理的动作: {action}"
