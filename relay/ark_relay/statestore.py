"""中继的状态，一个文件、一张字段表（根治第 3 项，设计见 docs/状态模型.md）。

`state/state.json` 分段：marks / modes / weekly / versions / updates / queues。
每个键都得在 FIELDS 里登记过，没登记的写不进去——和手机页「只改已存在的字段」
一个规矩，防的是 826 那种凭空造字段。

旧文件（garden.json、annihilation.json、weeklyboss.json …）第一次启动时自动迁入；
迁入后旧文件留着不删（改名 .migrated），跑稳三天再清。
"""
from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path

from .config import atomic_write_text

log = logging.getLogger("ark.state")

FILE = "state.json"
SECTIONS = ("marks", "modes", "weekly", "versions", "updates", "queues")

# 字段表：段 → {键（可带 * 通配）: 说明}。改这里等于改契约，要连 docs/状态模型.md 一起改。
FIELDS: dict[str, dict[str, str]] = {
    "weekly": {
        "annihilation": "剿灭：{done_week, restore_to}",
        "garden": "周常乐园：{done_week}",
        "boss": "周本：{index, name, done_week}",
    },
    "marks": {
        "report:*": "某天日报已发（值=时刻）",
        "interim:*": "某天临时日报覆盖到第几条记录",
        "banner:*": "某个卡池的开服播报已发（键=游戏+开始时刻）",
    },
    "modes": {
        "skip_next_shutdown": "下一次别关机（一次性，人按的）",
        "shutdown_skipped": "哪一次关机机会已被调试模式吃掉（机会标识）",
        "debug_until": "调试模式到什么时候（YYYY-MM-DD HH:MM）",
    },
    "versions": {
        "okww": "上次贴补丁时 OK-WW 的版本",
        "maaend": "上次预更新确认过的 MaaEnd 版本",
        "code": "本机中继代码版本",
    },
    "updates": {
        "preupdate": "预更新今天跑过没有：{day, at, clean}",
        "gameupdate": "游戏客户端更新这次开机跑过没有：{boot, at}",
        "gameupdate_pending": "待更新登记：{游戏: 为什么}",
        "gameupdate_off": "游戏更新总开关（真=整套不动）",
        "arknights_client": "记下的明日方舟客户端版本：{version, at}",
        "queue_skips": "为更新而临时从队列里摘掉的脚本，列表",
        "maintenance_windows": "今天各游戏的停服维护时段：{游戏: {start,end,why}}",
    },
    "queues": {
        "pending": "还没推出去的失败告警：{脚本|账号: 记录}",
        "phone_seen": "手机指令去重用的消息 id 列表",
        "inbox_version": "待办清单处理到哪一版",
        "skip_restore": "跳过模式停用了哪个队列，用于过后恢复",
        "skip_day:*": "某天要跳过哪个队列（值=队列名）",
    },
}

# 旧文件 → (段, 键, 读法)。读法：json = 整个文件是 JSON；text = 纯文本去空白
# 通配迁移：文件名模式 → (段, 键模板, 读法)。`*` 捕获的那一段填进键模板的 {}。
LEGACY_GLOB = {
    "report-*.sent": ("marks", "report:{}", "flag"),
    "interim-*.sent": ("marks", "interim:{}", "text"),
    "banner-*.sent": ("marks", "banner:{}", "flag"),
    "skip-*.flag": ("queues", "skip_day:{}", "text"),
}

LEGACY = {
    "annihilation.json": ("weekly", "annihilation", "json"),
    "pending.json": ("queues", "pending", "json"),
    "skip-next-shutdown.flag": ("modes", "skip_next_shutdown", "flag"),
    "preupdate.json": ("updates", "preupdate", "json"),
    "gameupdate.json": ("updates", "gameupdate", "json"),
    "gameupdate-pending.json": ("updates", "gameupdate_pending", "json"),
    "gameupdate-off.flag": ("updates", "gameupdate_off", "flag"),
    "arknights-client.json": ("updates", "arknights_client", "json"),
    "queue-skips.json": ("updates", "queue_skips", "json"),
    "phone-seen.json": ("queues", "phone_seen", "json"),
    "inbox-version.txt": ("queues", "inbox_version", "text"),
    "skip-restore.json": ("queues", "skip_restore", "json"),
    "maintenance-today.json": ("updates", "maintenance_windows", "json"),
    "shutdown-skipped.txt": ("modes", "shutdown_skipped", "text"),
    "garden.json": ("weekly", "garden", "json"),
    "weeklyboss.json": ("weekly", "boss", "json"),
    "okww-version.txt": ("versions", "okww", "text"),
    "maaend-version.txt": ("versions", "maaend", "text"),
    "debug-until.txt": ("modes", "debug_until", "text"),
}


def _read_legacy(f: Path, how: str):
    """按读法把旧文件读成值。读不出来返回 None（调用方跳过）。"""
    try:
        raw = f.read_text(encoding="utf-8")
    except OSError:
        log.warning("旧状态文件 %s 读不出来，跳过", f.name)
        return None
    if how == "json":
        try:
            return json.loads(raw)
        except ValueError:
            log.warning("旧状态文件 %s 不是 JSON，跳过", f.name)
            return None
    if how == "flag":
        return True         # 文件存在本身就是值
    return raw.strip()


def _registered(section: str, key: str) -> bool:
    return any(fnmatch.fnmatchcase(key, pat) for pat in FIELDS.get(section, {}))


# 这个进程里已经清扫过旧文件的目录。清扫要**每个进程一次**，不能只在
# state.json 不存在时做：2026-09-08 加了第二批旧文件（日报标记、告警队列、
# 更新记账）之后，机器上 state.json 早就存在了，那一批一个都没迁进来——
# 而 `report-*.sent` 没迁进来意味着昨天的日报会被当成没发过、再发一遍。
_SWEPT: set = set()


class StateStore:
    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir)
        self.path = self.dir / FILE
        self._data: dict | None = None
        self._mtime = -1.0
        if str(self.dir) not in _SWEPT:
            _SWEPT.add(str(self.dir))
            try:
                self._sweep_legacy()
            except OSError:
                log.warning("清扫旧状态文件时出错，下次进程启动再试", exc_info=True)

    # ---------- 读 ----------
    def _load(self) -> dict:
        try:
            m = self.path.stat().st_mtime
        except OSError:
            m = -1.0
        if self._data is not None and m == self._mtime:
            return self._data
        data: dict = {}
        if m >= 0:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("state.json 读不出来，按空处理（旧内容在磁盘上没动）", exc_info=True)
                data = {}
        for s in SECTIONS:
            data.setdefault(s, {})
        self._data, self._mtime = data, m
        return data

    def section(self, name: str) -> dict:
        if name not in SECTIONS:
            raise KeyError(f"没有 {name!r} 这一段")
        return dict(self._load()[name])

    def get(self, section: str, key: str, default=None):
        return self._load().get(section, {}).get(key, default)

    # ---------- 写 ----------
    def set(self, section: str, key: str, value) -> None:
        if not _registered(section, key):
            raise KeyError(f"state.{section}.{key} 没在字段表里登记，拒绝写入（见 docs/状态模型.md）")
        data = self._load()
        data[section][key] = value
        self._flush(data)

    def pop(self, section: str, key: str) -> None:
        data = self._load()
        if key in data.get(section, {}):
            del data[section][key]
            self._flush(data)

    def _flush(self, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=1))
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime = -1.0
        self._data = data

    # ---------- 迁移 ----------

    def _sweep_legacy(self) -> None:
        """把还留在磁盘上的旧状态文件迁进来。每个进程对每个目录只做一次。

        已经有值的键不覆盖：state.json 是权威，旧文件只是没人清理的遗留。
        迁完把旧文件改名 `.migrated` 留着，跑稳几天再删。
        """
        if not self.dir.is_dir():
            return
        data = None
        moved = []

        def take(section: str, key: str, value) -> bool:
            nonlocal data
            if value in ("", {}, None) and value is not False:
                return False
            if data is None:
                data = self._load()
            if key in data.get(section, {}):
                return False        # 已经有值：state.json 说了算
            data.setdefault(section, {})[key] = value
            return True

        for name, (section, key, how) in LEGACY.items():
            f = self.dir / name
            if not f.is_file():
                continue
            if take(section, key, _read_legacy(f, how)):
                moved.append(name)
            else:
                moved.append(name)   # 值已在 state.json 里：旧文件也该收走
        for pattern, (section, tmpl, how) in LEGACY_GLOB.items():
            head, _, tail = pattern.partition("*")
            for f in sorted(self.dir.glob(pattern)):
                if f.name in LEGACY:
                    continue        # 上面按全名迁过了（skip-next-shutdown.flag 会撞 skip-*.flag）
                stem = f.name[len(head):-len(tail)] if tail else f.name[len(head):]
                value = _read_legacy(f, how)
                if value is None:
                    continue
                # 空内容原样保留成空串：`interim-*.sent` 的空标记表示「发过、条数不详」，
                # 换成 "1" 会被读成「只覆盖了 1 条」，当天已报过的轮次就会重播一遍。
                if value == "" and how == "text":
                    if data is None:
                        data = self._load()
                    data.setdefault(section, {}).setdefault(tmpl.format(stem), "")
                    moved.append(f.name)
                    continue
                take(section, tmpl.format(stem), value)
                moved.append(f.name)
        if not moved:
            return
        if data is not None:
            self._flush(data)
        for name in moved:
            try:
                (self.dir / name).rename(self.dir / f"{name}.migrated")
            except OSError:
                log.warning("旧状态文件 %s 改名失败，下次启动会再迁一次（幂等）", name)
        log.info("状态已迁入 state.json：%s", "、".join(sorted(moved)))
