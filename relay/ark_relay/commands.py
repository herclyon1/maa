"""Applying commands to AUTO-MAS config - the guarded path.

Four gates, none optional (docs/04-中继设计.md §15):

  ① 白名单      the model emits an action name from a fixed table,
                never a JSON patch
  ② 人工确认    config-mutating actions wait for the operator's OK;
                reversible ones (run_now / skip_today) go straight through
  ③ 落地校验    backup -> edit -> json.loads -> structural diff;
                anything unexpected rolls back
  ④ 回报        success, failure and rejection all get reported

Gate ③ exists because it has already caught a real mistake: a regex meant to
disable three webhook tasks disabled two and damaged an unrelated section.
The diff caught it; care did not.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.commands")

# ---------- gate ① : the whitelist ----------

# Actions that only change what happens next, and undo themselves.
REVERSIBLE = {"run_now", "skip_today", "debug_mode"}

# Actions that write to a config file on disk.
MUTATING = {"set_stage", "set_medicine", "toggle_task", "set_wait_time"}

ALLOWED = REVERSIBLE | MUTATING

# Stage codes look like TO-5 / CE-6 / 1-7 / LS-6. Refuse anything else outright
# rather than trusting a model not to invent one.
_STAGE_RE = re.compile(r"^[A-Za-z0-9]{1,4}-[A-Za-z0-9]{1,3}$")


def _script_config() -> Path:
    root = os.environ.get("ARK_AUTOMAS_DIR")
    if not root:
        raise RuntimeError("ARK_AUTOMAS_DIR 未设置")
    return Path(root) / "config" / "ScriptConfig.json"


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

    detail = "；".join(f"{k}: {x!r} → {y!r}" for k, (x, y) in sorted(changed.items()))
    return True, f"已改动 {len(changed)} 处（备份 {backup.name}）：{detail}"


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
    """MaaEnd 的「游戏启动后等待秒数」（ScriptConfig 里唯一的 Game/WaitTime）。

    Why this knob exists here: every fresh boot the first MaaEnd attempt died
    within seconds of connecting - the game recreates its window during first
    startup and MaaEnd grabs the doomed early handle (2026-08-20 log
    forensics, docs/05-踩过的坑.md). Waiting past the recreation window is
    the fix; the retry mechanism was papering over it once per day.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return False, f"等待秒数不是整数: {value!r}"
    if not 0 <= n <= 600:
        return False, f"等待秒数超出范围 0–600: {n}"

    def mutate(raw: str) -> str:
        hits = re.findall(r'"WaitTime":\s*\d+', raw)
        if len(hits) != 1:
            raise ValueError(f'找到 {len(hits)} 处 "WaitTime"，预期恰好 1 处')
        return re.sub(r'("WaitTime":\s*)\d+', rf"\g<1>{n}", raw, count=1)

    return _safe_rewrite(_script_config(), mutate, expect_changed=1)


def _toggle_task(name: str, on: bool) -> tuple[bool, str]:
    # Deliberately unimplemented: task names live in a different file per
    # script and getting this wrong silently disables the wrong task.
    return False, f"toggle_task 尚未实现（{name} → {'开' if on else '关'}），需要人工处理"


def _run_now(queue: str) -> tuple[bool, str]:
    # An earlier version wrote run-now.flag here and reported success - but
    # nothing anywhere ever read that flag, so the operator got a ✅ for a
    # no-op. Refusing honestly is strictly better than lying until the
    # consumer actually exists.
    return False, (f"run_now 尚未实现（写过的请求标记没有任何组件消费），"
                   f"队列「{queue}」需要人工触发")


def _skip_today(queue: str, want_day: str = "") -> tuple[bool, str]:
    # 必须用服务器时钟：跨时区或临近午夜时，主机本地日期会跳错天
    day = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    # The command travels through the inbox and is collected at the NEXT boot,
    # which may be the following morning - "skip today" queued at 23:00 after
    # the runs would then silently skip a day the operator never named. A
    # command carrying its intended date is refused once that date has passed.
    if want_day and want_day != day:
        return False, (f"skip_today 指定的是 {want_day}，今天已是 {day}——"
                       "指令在收件箱里过期了，未生效。需要就重新排一条")
    marker = Path(os.environ.get("ARK_STATE_DIR", "./ark-state")) / f"skip-{day}.flag"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(queue), encoding="utf-8")
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
            return _run_now(str(cmd.get("queue") or "新队列"))
        if action == "skip_today":
            return _skip_today(str(cmd.get("queue") or "新队列"),
                               str(cmd.get("day") or "").strip())
        if action == "debug_mode":
            from .modes import set_debug  # noqa: PLC0415
            state_dir = Path(os.environ.get("ARK_STATE_DIR", "./ark-state"))
            return set_debug(state_dir, cmd.get("days", 1), bool(cmd.get("off")))
    except Exception as exc:  # noqa: BLE001 - report, never crash the agent
        log.exception("执行指令失败: %s", action)
        return False, f"执行出错: {exc}"
    return False, f"未处理的动作: {action}"
