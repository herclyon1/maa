"""The relay's state: one file, one field table (root fix #3; design in docs/STATE-MODEL.md).

`state/state.json` has sections: marks / modes / weekly / versions / updates / queues.
Every key must be registered in FIELDS; an unregistered key cannot be written -
the same rule as the phone page's "only change fields that already exist",
guarding against inventing fields out of thin air the way 826 did.

Old files (garden.json, annihilation.json, weeklyboss.json ...) are migrated in
automatically on first start; after migration the old file is kept rather than
deleted (renamed to .migrated) and cleaned up after three stable days.
"""
from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path

from .config import atomic_write_text

log = logging.getLogger("ark.statestore")

FILE = "state.json"
SECTIONS = ("marks", "modes", "weekly", "versions", "updates", "queues")

# The field table: section -> {key (may contain a * wildcard): description}.
# Changing this changes the contract - change docs/STATE-MODEL.md along with it.
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
        "alerted:*": "某天已经告警过的事（键=日期，值=告警标识列表）",
    },
    "modes": {
        "skip_next_shutdown": "下一次别关机（一次性，人按的）",
        "shutdown_skipped": "哪一次关机机会已被调试模式吃掉（机会标识）",
        "debug_until": "调试模式到什么时候（YYYY-MM-DD HH:MM）",
    },
    "versions": {
        "announced_notes": "上一条「已更新」推送的说明原文（一模一样就不再推）",
        "okww": "上次贴补丁时 OK-WW 的版本",
        "maaend": "上次预更新确认过的 MaaEnd 版本",
        "code": "本机中继代码版本",
        "announced": "已经播报过更新的那个版本，避免重复推送",
        "scoreboard": "每个代码版本跑过几趟、失败几趟（日报末尾那一行的来源）",
    },
    "updates": {
        "preupdate": "预更新今天跑过没有：{day, at, clean}",
        "gameupdate": "游戏客户端更新这次开机跑过没有：{boot, at}",
        "gameupdate_pending": "待更新登记：{游戏: 为什么}",
        "gameupdate_off": "游戏更新总开关（真=整套不动）",
        "arknights_client": "记下的明日方舟客户端版本：{version, at}",
        "queue_skips": "为更新而临时从队列里摘掉的脚本，列表",
        "maintenance_windows": "今天各游戏的停服维护时段：{游戏: {start,end,why}}",
        "maaend_disabled_1_5_3": "为 1.5.3 临时关掉的 MaaEnd 任务：{tasks, since}",
        "maaend_reenable_next_boot": "补跑时临时关掉、下次开机开回的任务：{tasks}",
        "maaend_disabled_spmed": "加强剂坏掉时关掉的任务：{tasks, since}",
    },
    "queues": {
        "echo_farm": "正在刷的声骸 boss：{boss, name, until, started, saved}",
        "pending": "还没推出去的失败告警：{脚本|账号: 记录}",
        "phone_seen": "手机指令去重用的消息 id 列表",
        "inbox_version": "待办清单处理到哪一版",
        "skip_restore": "跳过模式停用了哪个队列，用于过后恢复",
        "skip_day:*": "某天要跳过哪个队列（值=队列名）",
        "channels_down": "哪些推送渠道正挂着，避免每次重启都重报一遍",
    },
}

# Old file -> (section, key, how to read). How: json = the whole file is JSON;
# text = plain text, stripped.
# Wildcard migration: filename pattern -> (section, key template, how to read).
# Whatever `*` captures is filled into the {} of the key template.
LEGACY_GLOB = {
    "report-*.sent": ("marks", "report:{}", "flag"),
    "interim-*.sent": ("marks", "interim:{}", "text"),
    "banner-*.sent": ("marks", "banner:{}", "flag"),
    "alerted-*.json": ("marks", "alerted:{}", "json"),
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
    "maaend-disabled-for-1.5.3.json": ("updates", "maaend_disabled_1_5_3", "json"),
    "maaend-reenable-next-boot.json": ("updates", "maaend_reenable_next_boot", "json"),
    "maaend-disabled-spmed.json": ("updates", "maaend_disabled_spmed", "json"),
    "channels-down.json": ("queues", "channels_down", "json"),
    "phone-seen.json": ("queues", "phone_seen", "json"),
    "inbox-version.txt": ("queues", "inbox_version", "text"),
    "skip-restore.json": ("queues", "skip_restore", "json"),
    "maintenance-today.json": ("updates", "maintenance_windows", "json"),
    "shutdown-skipped.txt": ("modes", "shutdown_skipped", "text"),
    "garden.json": ("weekly", "garden", "json"),
    "weeklyboss.json": ("weekly", "boss", "json"),
    "okww-version.txt": ("versions", "okww", "text"),
    "code-version.txt": ("versions", "code", "text"),
    "announced-version.txt": ("versions", "announced", "text"),
    "maaend-version.txt": ("versions", "maaend", "text"),
    "debug-until.txt": ("modes", "debug_until", "text"),
}


def _read_legacy(f: Path, how: str):
    """Read an old file into a value per `how`. Returns None if unreadable (the caller skips it)."""
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
        return True         # the file existing is itself the value
    return raw.strip()


def _registered(section: str, key: str) -> bool:
    return any(fnmatch.fnmatchcase(key, pat) for pat in FIELDS.get(section, {}))


# Directories whose old files this process has already swept. The sweep must run
# **once per process**, not only when state.json is missing: after a second batch
# of old files was added on 2026-09-08 (report marks, alert queue, update
# bookkeeping), state.json already existed on the machine, so not one of that
# batch got migrated - and `report-*.sent` not being migrated means yesterday's
# daily report counts as never sent and goes out a second time.
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

    # ---------- read ----------
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

    # ---------- write ----------
    def set(self, section: str, key: str, value) -> None:
        if not _registered(section, key):
            raise KeyError(f"state.{section}.{key} 没在字段表里登记，拒绝写入（见 docs/STATE-MODEL.md）")
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

    # ---------- migration ----------

    def _sweep_legacy(self) -> None:
        """Migrate in whatever old state files are still on disk. Once per process, per directory.

        A key that already has a value is not overwritten: state.json is
        authoritative, the old file is just leftovers nobody cleaned up.
        After migrating, the old file is renamed `.migrated` and kept, to be
        deleted after a few stable days.
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
                return False        # already has a value: state.json wins
            data.setdefault(section, {})[key] = value
            return True

        for name, (section, key, how) in LEGACY.items():
            f = self.dir / name
            if not f.is_file():
                continue
            if take(section, key, _read_legacy(f, how)):
                moved.append(name)
            else:
                moved.append(name)   # value already in state.json: the old file should still be taken away
        for pattern, (section, tmpl, how) in LEGACY_GLOB.items():
            head, _, tail = pattern.partition("*")
            for f in sorted(self.dir.glob(pattern)):
                if f.name in LEGACY:
                    continue        # migrated by full name above (skip-next-shutdown.flag collides with skip-*.flag)
                stem = f.name[len(head):-len(tail)] if tail else f.name[len(head):]
                value = _read_legacy(f, how)
                if value is None:
                    continue
                # Empty content is kept as an empty string: an empty
                # `interim-*.sent` marker means "sent, count unknown". Turning it
                # into "1" would read as "only covered 1 record", and rounds
                # already reported that day would be replayed.
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
                # replace, not rename: a .migrated of the same name may already
                # be there (migrated in an earlier round, then written again by
                # old code); on Windows rename fails when the target exists, so
                # that file would be re-migrated on every start and warn every
                # time.
                (self.dir / name).replace(self.dir / f"{name}.migrated")
            except OSError:
                log.warning("旧状态文件 %s 收不走，下次启动再试（不影响读写）", name)
        log.info("状态已迁入 state.json：%s", "、".join(sorted(moved)))
