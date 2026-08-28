"""周常乐园：本周做完就把检查关掉，周一 04:00 自动开回来。

和 `annihilation.py` 是同一个形状——「一周只需要做一次的事，别每天都去看一眼」。
剿灭那边关的是 MAA 的 `Info.Annihilation`，这边关的是 OK-WW 的
`Task.AdditionalTasks` 里那项 `Check Weekly Garden`。

为什么值得做：上游的 `check_weekly_garden()` 每轮都要导航到乐园页面、截图、
判断有没有完成。一周里后六天全是白跑，纯粹的时间浪费。

**为什么走配置层而不是改 OK-WW 源码**：OK-WW 的自动更新会整段覆盖 `src`
（2026-08-26 实测，v3.6.5 → v3.6.6-beta.1 之后本地补丁连备份一起消失）。
配置不在覆盖范围内，所以同样的效果，配置层做就天然免疫。
非改源码不可的那些放 `okww_patch.py`，能在配置层做的一律别去改源码。

**2026-08-28 改为直接写母本，不再走 AUTO-MAS 的 API。**
原先写的是 MAS 用户配置的 `Task.AdditionalTasks`，那条路要求
`Info.IfQuickConfig` 开着才会被下发。用户当天要求废掉快速配置
（它只能开关已存在的任务、还制造静默故障），于是这个功能整个失效了。

现在直接改母本 `<automas>/data/<脚本id>/Default/ConfigFile/DailyTask.json`
里的 `Additional Tasks to Run After Daily Task`。这条路不依赖快速配置：
母本目录是 AUTO-MAS 每轮**无条件**拷给 OK-WW 的那一份。

`annihilation.py` 当年写文件被冲掉，是因为它写的是 **MAS 自己的配置**
（MAS 运行期间用内存副本覆盖）。母本 `ConfigFile/` 目录 MAS 只读不写
（`Okww/AutoProxy.py:82,264` 只有读；回写那段在 `OkNte` 里，不是 OK-WW），
所以不存在同样的问题。写入用原子替换，避免和 copytree 撞车撕裂文件。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from .annihilation import week_key          # 周界口径必须和剿灭完全一致
from .config import SERVER_TZ, atomic_write_text, master_config_dir

log = logging.getLogger("ark.garden")

TASK_NAME = "Check Weekly Garden"
KEY = "Additional Tasks to Run After Daily Task"
MARKER = "DailyTask.json"


def _daily_file(automas_dir) -> "Path | None":
    d = master_config_dir(automas_dir, MARKER)
    return (d / MARKER) if d else None


class GardenGate:
    """记住哪一个游戏周的周常乐园已经做完了。"""

    def __init__(self, state_dir: Path, automas_dir=None):
        self.path = Path(state_dir) / "garden.json"
        self.automas_dir = automas_dir
        self._last_write_error = ""     # 同一条写失败只说一次，见 enforce()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=1))

    def on_success(self, now: datetime | None = None) -> str:
        """报告里出现「周常乐园（本周已完成）」时调用。只记账，不落盘。

        落盘交给 `enforce()`：这一刻队列多半还在跑下一个脚本，
        而配置在任务运行期间是锁的，现在写必然失败。
        """
        now = now or datetime.now(tz=SERVER_TZ)
        week = week_key(now)
        state = self._load()
        if state.get("done_week") == week:
            return ""
        self._save({"done_week": week})
        log.info("本周周常乐园已完成，待脚本停下后关闭检查（周一 04:00 后恢复）")
        return "本周周常乐园已完成，稍后暂停检查到下周一"

    def enforce(self, now: datetime | None = None) -> bool:
        """把开关推到该在的位置。返回是否真的改了东西。

        必须可以反复跑：一次关掉不代表一直关着，而且周一到了要开回来。
        """
        now = now or datetime.now(tz=SERVER_TZ)
        week = week_key(now)
        state = self._load()
        want_off = state.get("done_week") == week

        f = _daily_file(self.automas_dir)
        if f is None:
            if self._last_write_error != "no-master":
                log.warning("找不到 OK-WW 母本 %s，周常乐园开关没法改", MARKER)
                self._last_write_error = "no-master"
            return False
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            if str(exc) != self._last_write_error:
                log.warning("读不了 %s：%s", f.name, exc)
                self._last_write_error = str(exc)
            return False
        tasks = list(cfg.get(KEY) or [])
        has = TASK_NAME in tasks

        if want_off and has:
            tasks.remove(TASK_NAME)
        elif not want_off and not has and state:
            # 周翻篇了：把检查放回去，并清掉记账。
            tasks.append(TASK_NAME)
        else:
            if not want_off and state:
                self._save({})          # 过期的记账，顺手清掉
            return False

        cfg[KEY] = tasks
        # 原子替换：copytree 可能正在读这个目录，撕裂的 JSON 会让 OK-WW 起不来。
        tmp = f.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, f)
        except OSError as exc:
            if str(exc) != self._last_write_error:
                log.warning("周常乐园开关写不进去：%s", exc)
                self._last_write_error = str(exc)
            tmp.unlink(missing_ok=True)
            return False
        self._last_write_error = ""

        if want_off:
            log.info("已关闭周常乐园检查（周一 04:00 后自动恢复）")
        else:
            self._save({})
            log.info("新的一周，周常乐园检查已恢复")
        return True
