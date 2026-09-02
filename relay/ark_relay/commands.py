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
REVERSIBLE = {"skip_today", "debug_mode", "skip_shutdown", "weekly_boss"}

# Actions that write to a config file on disk.
MUTATING = {"set_stage", "set_medicine", "toggle_task", "set_wait_time",
            "set_config", "run_now"}

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


MAS_API = "http://127.0.0.1:36163"


def _mas(path: str, body: "dict | None" = None, timeout: int = 20) -> dict:
    """AUTO-MAS 后端。**每个端点都是 POST**，读取的也是。

    走 API 而不是改文件：后端在跑的时候会用内存里那份覆写文件，
    直接改文件的值会被静静冲掉。
    """
    req = urllib.request.Request(
        MAS_API + path, data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode())


def _find_user(script: str) -> "tuple[str, str, dict]":
    """按脚本名找到 (scriptId, userId, 当前用户配置)。"""
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
    """改任意一项配置。手机端所有设置都走这一条。

    2026-08-31 实测过 `/api/scripts/user/update` 是**合并语义**：只写传进去
    的那些键，其余原样不动（先存全量、写回同值、全量比对验的）。

    这里必须做的三件事，一件都不能省——826 就是省了才出的事：
      * 改之前先把**现值**读出来，报告里写「A → B」而不是只写 B；
      * 路径必须在现有配置里真的存在，不存在就拒绝，不许凭空造字段；
      * 写完**回读验证**，验的是「这个键现在是不是这个值」。
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


def _run_now(queue: str) -> tuple[bool, str]:
    """立刻跑一趟队列。走 AUTO-MAS 的 dispatch 接口。"""
    queue = names.canonical(queue)
    try:
        queues = _mas("/api/queue/get")["data"]
    except Exception as exc:  # noqa: BLE001
        return False, f"取不到队列列表: {exc}"
    names = []
    for qid, q in queues.items():
        name = str((q.get("Info") or {}).get("Name") or "")
        names.append(name)
        if name == queue:
            try:
                # mode 的合法值只有 AutoProxy / ScriptConfig / Update
                # （app/models/schema.py 的 TaskCreateIn）。2026-08-31 我写成
                # 「队列」，接口直接 422——手机上按「现在跑一趟」毫无反应。
                r = _mas("/api/dispatch/start",
                         {"taskId": qid, "mode": "AutoProxy"})
            except Exception as exc:  # noqa: BLE001
                return False, f"队列「{queue}」没能启动: {exc}"
            if str(r.get("status")) != "success":
                return False, f"队列「{queue}」没能启动: {r.get('message')}"
            return True, f"队列「{queue}」已开始跑"
    have = "、".join(names)
    return False, f"没有叫「{queue}」的队列（有的是：{have}）"


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
    marker = Path(os.environ.get("ARK_STATE_DIR", "./ark-state")) / f"skip-{day}.flag"
    marker.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: an empty flag reads back as the default queue name, so a torn
    # write would skip a queue nobody asked to skip.
    atomic_write_text(marker, str(queue))
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
        if action == "weekly_boss":
            # 鸣潮周本（战歌重奏）。和剿灭一个形状：打完自动摘掉，
            # 周一 04:00 挂回来。默认关着——Repeat Farm Count 出厂是 10000，
            # 盲目打开会一直刷；一周能拿几次奖励是游戏规则，我不替人定。
            from .weeklyboss import WeeklyBossGate  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            gate = WeeklyBossGate(state_dir, os.environ.get("ARK_AUTOMAS_DIR"))
            ok, msg = gate.configure(
                enabled=None if "on" not in cmd else bool(cmd.get("on")),
                index=cmd.get("index"), count=cmd.get("count"),
                level=cmd.get("level"))
            if ok:
                gate.enforce()
            return ok, msg
        if action == "skip_shutdown":
            # 手机上按的那个「今晚别关机」。不带到期时间：把**下一次**
            # 真正要执行的关机吃掉一次，用完即失效，下一趟队列照常关。
            # 用户 2026-08-31：「你给一个人类好去调这个模式的方法，
            # 独立于你的」「我要的是手机上面操作」。
            from .modes import set_skip_shutdown  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            # 取消的写法两种都认。规范是 off:true，但别的动作
            # （weekly_boss / toggle_task）用的是 on，一个界面两套写法迟早
            # 发错。2026-08-31 实测就发现手机上只有「开」没有「取消」，
            # 发 on:false 会被当成「开」。宽进：两种都当取消。
            off = bool(cmd.get("off")) or cmd.get("on") is False
            return set_skip_shutdown(state_dir, not off)
    except Exception as exc:  # noqa: BLE001 - report, never crash the agent
        log.exception("执行指令失败: %s", action)
        return False, f"执行出错: {exc}"
    return False, f"未处理的动作: {action}"
