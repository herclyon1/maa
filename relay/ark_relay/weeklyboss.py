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
import re
import logging
import os
from datetime import datetime
from pathlib import Path

from .annihilation import week_key          # 周界口径和剿灭完全一致
from .statestore import StateStore
from .config import SERVER_TZ, master_config_dir

log = logging.getLogger("ark.weeklyboss")

TASK_NAME = "Teleport and Farm 4C Echo"     # 传送并刷取4C声骸
TASK_ZH = "传送并刷取4C声骸"
KEY = "Additional Tasks to Run After Daily Task"
# 上游对 Boss Level 的说明是 "Choose the Lowest that Drop a Echo"——
# 那是**刷声骸**的思路：能掉声骸的最低级最好打。周本正相反，
# **等级决定奖励档次，必须挑最高的**。这两种用途共用同一个配置项，
# 而我们的 FarmEchoTask 只被周本用（日常刷声骸走残象聚落），
# 所以直接钉在最高级，不存在冲突。2026-08-31 用户指出机器上是 80，错的。
LEVELS = ("50", "60", "70", "80", "90")
MAX_LEVEL = LEVELS[-1]
COUNT = 3                                   # 一周只能领 3 次奖励，游戏规则

DAILY = "DailyTask.json"
FARM = "FarmEchoTask.json"
WEEKLY = "Weekly Challenge"                 # 战歌重奏


def _file(automas_dir, name: str) -> "Path | None":
    d = master_config_dir(automas_dir, DAILY)
    return (d / name) if d else None


def _okww_file(name: str) -> "Path | None":
    """OK-WW 自己那份配置。**必须一起写**，光写母本不够。

    2026-08-31 实测：母本 `Boss Level` 已经是 '90'（16:20 写的），
    而 OK-WW 自己那份还停在 '80'（08:06 的），派发跑起来点的是
    「推荐等级80」。`master_config_dir` 的注释说 AUTO-MAS 跑之前会
    无条件把母本拷过去——**至少 /api/dispatch/start 这条路没有拷**。

    两边都写就没有这个问题：真拷了，值一样；没拷，OK-WW 读到的也对。
    """
    root = os.environ.get("ARK_OKWW_DIR")
    if not root:
        return None
    f = Path(root) / "data" / "apps" / "ok-ww" / "working" / "configs" / name
    return f if f.is_file() else None


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


def remaining_from_log() -> "int | None":
    """OK-WW 日志里最近一次读到的「本周剩余可收取次数」。读不到返回 None。

    本地补丁「进本前拍一张看剩余次数」会把那一行 OCR 出来打进日志，形如
    `周本本周剩余次数原文: [... '本周剩余可收取次数：2/3' ...]`。
    只取斜杠前那个数。

    为什么要读它：`on_success` 原来只要任务跑完就记「本周已打」，
    而**一趟不一定能领满三次**——奖励是进本时扣 60 波片，波片不够就少领。
    2026-08-31 实测：贝币刷取把波片吃到只剩 1 点，第二天早上只回到 ~147，
    只够领两次；按「跑完即打完」记账，第三次就永远丢了。
    """
    path = os.environ.get("ARK_OKWW_LOG")
    if not path:
        root = os.environ.get("ARK_OKWW_DIR")
        if not root:
            return None
        logs = Path(root) / "data" / "apps" / "ok-ww" / "working" / "logs"
        try:
            cand = max(logs.glob("*.log*"), key=lambda q: q.stat().st_mtime)
        except (OSError, ValueError):
            return None
        path = str(cand)
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    hits = re.findall(r"本周剩余可收取次数[：:]\s*(\d+)\s*/\s*(\d+)", text)
    if not hits:
        return None
    return int(hits[-1][0])


_NAME_RE = re.compile(r"周本名称原文:\s*\[(.*?)\]")


def name_from_log() -> str:
    """OK-WW 日志里最近一次 OCR 到的周本名（补丁「周本名称原文」）。读不到返回空串。"""
    path = os.environ.get("ARK_OKWW_LOG")
    if not path:
        root = os.environ.get("ARK_OKWW_DIR")
        if not root:
            return ""
        logs = Path(root) / "data" / "apps" / "ok-ww" / "working" / "logs"
        try:
            path = str(max(logs.glob("*.log*"), key=lambda q: q.stat().st_mtime))
        except (OSError, ValueError):
            return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    hits = _NAME_RE.findall(text)
    if not hits:
        return ""
    # OCR 结果形如 "千傀重楼_0.99"，取第一个词、去掉置信度
    first = hits[-1].split(",")[0].strip().strip("'\"")
    return re.sub(r"_[\d.]+$", "", first).strip()


def _mirror(name: str, want: dict) -> None:
    """把 want 里的字段同步到 OK-WW 自己那份配置。副本没有就安静跳过。"""
    f = _okww_file(name)
    if f is None:
        return
    cur = _read(f)
    if cur is None or all(cur.get(k) == v for k, v in want.items()):
        return
    cur.update(want)
    if _write(f, cur):
        log.info("周本配置已同步到 OK-WW 自己那份 %s：%s", name, want)
    else:
        log.warning("周本配置同步不进 OK-WW 自己那份 %s", name)


class WeeklyBossGate:
    """记住哪一个游戏周的周本已经打完了。默认关闭，要人明确打开。

    和剿灭、周常乐园同一套接口：settings / week_line / on_success / enforce / maybe_reopen。
    """

    NAME = "鸣潮 · 周本"

    def __init__(self, state_dir: Path, automas_dir=None):
        self.path = Path(state_dir) / "weeklyboss.json"
        self._store = StateStore(state_dir)   # 状态收口：真正落盘在 state.json 的 weekly 段
        self.automas_dir = automas_dir
        self._last_error = ""

    def _load(self) -> dict:
        return dict(self._store.get("weekly", "boss") or {})

    def _save(self, data: dict) -> None:
        self._store.set("weekly", "boss", dict(data))

    # ---------- 人来开关 ----------

    def settings(self, now: "datetime | None" = None) -> dict:
        """给手机页看的。一周 3 次、90 级是游戏规则，固定死，不给改（用户 2026-09-07）；
        也没有总开关——和剿灭一样，打满自动停，周一自动开回来。"""
        s = self._load()
        # 「本周已打」必须拿 done_week 跟**当前这一周**比，不能只看有没有值。
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        return {"名字": str(s.get("name") or ""),
                "第几个周本": int(s.get("index") or 1),
                "打几次": COUNT,
                "难度等级": MAX_LEVEL,
                "本周已打": s.get("done_week") == week}

    def configure(self, *, index: "int | None" = None) -> tuple[bool, str]:
        s = self._load()
        if index is not None:
            if not 1 <= int(index) <= 20:
                return False, f"周本序号 {index} 不像话（应在 1~20）"
            s["index"] = int(index)
        self._save(s)
        return True, f"周本：打第 {self.settings()['第几个周本']} 个"

    def week_line(self, now: "datetime | None" = None) -> str:
        """「新的一周」通知里周本那一行：这周是什么状态。永远有话说。"""
        v = self.settings(now)
        what = v["名字"] or f"第 {v['第几个周本']} 个"
        if v["本周已打"]:
            return f"{self.NAME}：{what} 本周三次已领满，暂停到下周一"
        return f"{self.NAME}：{what}，本周还没领满"

    def maybe_reopen(self, now: "datetime | None" = None) -> str:
        """开机时调。上周记的「已领满」过了周就清掉，返回 week_line；没过周返回空串。"""
        s = self._load()
        done = s.get("done_week")
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        if not done or done == week:
            return ""
        s.pop("done_week", None)
        self._save(s)
        log.info("新的一周，周本记账已清（上周 %s）", done)
        return self.week_line(now)

    # ---------- 打完了 ----------

    def on_success(self, now: "datetime | None" = None) -> str:
        s = self._load()
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        if s.get("done_week") == week:
            return ""
        if nm := name_from_log():
            if s.get("name") != nm:
                s["name"] = nm
                self._save(s)
        left = remaining_from_log()
        if left is None:
            log.info("周本：读不到本周剩余次数，这趟先不记账，下一趟再看")
            return ""
        if left > 0:
            log.info("周本：本周还剩 %d 次没领，开关继续挂着", left)
            return f"{self.NAME}：这趟领了，本周还剩 {left} 次没领，下一趟接着打"
        s["done_week"] = week
        self._save(s)
        log.info("本周周本三次已领满，待脚本停下后摘掉（周一 04:00 后恢复）")
        return f"{self.NAME}：本周三次已领满，暂停到下周一"

    # ---------- 把开关推到该在的位置 ----------

    def enforce(self, now: "datetime | None" = None) -> bool:
        """可以反复跑：一次摘掉不代表一直摘着，周一到了要挂回来。"""
        s = self._load()
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        want_on = s.get("done_week") != week

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
            _mirror(DAILY, {KEY: tasks})

        # 打开时顺带把「传送到哪」写对，否则挂上去也不知道去哪
        if want_on:
            farm_f = _file(self.automas_dir, FARM)
            farm = _read(farm_f)
            if farm is not None:
                want = {"Teleport to Boss": WEEKLY,
                        "Which Weekly Boss to Teleport": int(s.get("index") or 1),
                        "Repeat Farm Count": COUNT,
                        "Boss Level": MAX_LEVEL}
                if any(farm.get(k) != v for k, v in want.items()):
                    farm.update(want)
                    if _write(farm_f, farm):
                        changed = True
                    else:
                        log.warning("周本的传送设置写不进 %s", FARM)
                _mirror(FARM, want)          # 母本一致了也要保证副本一致

        if changed:
            log.info("周本已%s（第 %s 个，打 %s 次）",
                     "挂上" if want_on else "摘掉", s.get("index") or 1, COUNT)
        self._last_error = ""
        return changed
