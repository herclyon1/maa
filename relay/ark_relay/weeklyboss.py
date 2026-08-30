"""鸣潮周本（战歌重奏）：本周打完就摘掉，周一 04:00 自动挂回来。

和 `garden.py`、`annihilation.py` 是同一个形状——「一周只需要做一次的事，
别每天都去做一遍」。用户 2026-08-31 要的就是「和剿灭逻辑一致」。

## 它到底改什么

两个文件，都在 OK-WW 的**母本**配置目录（AUTO-MAS 每轮无条件拷给 OK-WW 的
那一份，不受「快速配置」开关影响，理由见 garden.py 的说明）：

* `DailyTask.json` 的 `Additional Tasks to Run After Daily Task`
  里加/去 `Teleport and Farm 4C Echo`（译文「传送并刷取4C声骸」）
* `FarmEchoTask.json` 的 `Teleport to Boss` 设成 `Weekly Challenge`
  （译文「战歌重奏」，就是周本），并按设置写 `Which Weekly Boss to Teleport`
  和 `Repeat Farm Count`

## 为什么默认关着

`Repeat Farm Count` 出厂是 **10000**。照搬着打开，它会一直打下去。
周本一周能拿几次奖励是游戏规则，我没有可靠出处，所以不替用户定——
**默认关闭，次数由用户在手机上给**。编游戏规则去改生产配置正是 826 的成因。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from .annihilation import week_key          # 周界口径和剿灭完全一致
from .config import SERVER_TZ, atomic_write_text, master_config_dir

log = logging.getLogger("ark.weeklyboss")

TASK_NAME = "Teleport and Farm 4C Echo"     # 传送并刷取4C声骸
TASK_ZH = "传送并刷取4C声骸"
KEY = "Additional Tasks to Run After Daily Task"
DAILY = "DailyTask.json"
FARM = "FarmEchoTask.json"
WEEKLY = "Weekly Challenge"                 # 战歌重奏


def _file(automas_dir, name: str) -> "Path | None":
    d = master_config_dir(automas_dir, DAILY)
    return (d / name) if d else None


def _read(f: "Path | None") -> "dict | None":
    if f is None or not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(f: Path, cfg: dict) -> bool:
    # 原子替换：AUTO-MAS 可能正在拷这个目录，撕裂的 JSON 会让 OK-WW 起不来。
    tmp = f.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    return True


class WeeklyBossGate:
    """记住哪一个游戏周的周本已经打完了。默认关闭，要人明确打开。"""

    def __init__(self, state_dir: Path, automas_dir=None):
        self.path = Path(state_dir) / "weeklyboss.json"
        self.automas_dir = automas_dir
        self._last_error = ""

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=1))

    # ---------- 人来开关 ----------

    def settings(self) -> dict:
        s = self._load()
        return {"开": bool(s.get("enabled")),
                "第几个周本": int(s.get("index") or 1),
                "打几次": int(s.get("count") or 1),
                "本周已打": bool(s.get("done_week"))}

    def configure(self, *, enabled: "bool | None" = None,
                  index: "int | None" = None,
                  count: "int | None" = None) -> tuple[bool, str]:
        s = self._load()
        if enabled is not None:
            s["enabled"] = bool(enabled)
            if not enabled:
                s.pop("done_week", None)     # 关掉就把记账清了
        if index is not None:
            if not 1 <= int(index) <= 20:
                return False, f"周本序号 {index} 不像话（应在 1~20）"
            s["index"] = int(index)
        if count is not None:
            if not 1 <= int(count) <= 20:
                return False, f"打的次数 {count} 不像话（应在 1~20）"
            s["count"] = int(count)
        self._save(s)
        v = self.settings()
        return True, ("周本已开：第 {} 个，打 {} 次".format(v["第几个周本"], v["打几次"])
                      if v["开"] else "周本已关")

    # ---------- 打完了 ----------

    def on_success(self, now: "datetime | None" = None) -> str:
        s = self._load()
        if not s.get("enabled"):
            return ""
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        if s.get("done_week") == week:
            return ""
        s["done_week"] = week
        self._save(s)
        log.info("本周周本已打完，待脚本停下后摘掉（周一 04:00 后恢复）")
        return "本周周本已打完，稍后暂停到下周一"

    # ---------- 把开关推到该在的位置 ----------

    def enforce(self, now: "datetime | None" = None) -> bool:
        """可以反复跑：一次摘掉不代表一直摘着，周一到了要挂回来。"""
        s = self._load()
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        want_on = bool(s.get("enabled")) and s.get("done_week") != week

        daily_f = _file(self.automas_dir, DAILY)
        daily = _read(daily_f)
        if daily is None:
            if self._last_error != "no-master":
                log.warning("找不到 OK-WW 母本 %s，周本开关没法改", DAILY)
                self._last_error = "no-master"
            return False

        tasks = list(daily.get(KEY) or [])
        has = TASK_NAME in tasks
        changed = False

        if want_on and not has:
            tasks.append(TASK_NAME)
            changed = True
        elif not want_on and has:
            tasks.remove(TASK_NAME)
            changed = True
        if changed:
            daily[KEY] = tasks
            if not _write(daily_f, daily):
                log.warning("周本开关写不进 %s", DAILY)
                return False

        # 打开时顺带把「传送到哪」写对，否则挂上去也不知道去哪
        if want_on:
            farm_f = _file(self.automas_dir, FARM)
            farm = _read(farm_f)
            if farm is not None:
                want = {"Teleport to Boss": WEEKLY,
                        "Which Weekly Boss to Teleport": int(s.get("index") or 1),
                        "Repeat Farm Count": int(s.get("count") or 1)}
                if any(farm.get(k) != v for k, v in want.items()):
                    farm.update(want)
                    if _write(farm_f, farm):
                        changed = True
                    else:
                        log.warning("周本的传送设置写不进 %s", FARM)

        if changed:
            log.info("周本已%s（第 %s 个，打 %s 次）",
                     "挂上" if want_on else "摘掉",
                     s.get("index") or 1, s.get("count") or 1)
        self._last_error = ""
        return changed
