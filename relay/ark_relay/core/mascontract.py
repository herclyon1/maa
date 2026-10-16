"""Every AUTO-MAS setting the relay reads or writes, and a check that each is still where it looks.

AUTO-MAS v5.7.0-beta.3, installed by the relay's own pre-update on the game machine 10-14 08:46
Beijing, moved the MAA user's stage items from Info to a new Stage group (masuser.py). The relay
kept reading Info, got nothing, took "nothing" for "not set" (the stage gate logged its
current-stage placeholder at 08:55:27) and nobody heard of it for 13 hours: most readers default
a missing value silently (plan, stagegate, snapshot, annihilation).

CONTRACT lists each item once: the script kind, the level it sits at, its group and key, the
feature that goes wrong without it (an id into texts.MAS_SETTING_WHAT / MAS_SETTING_BREAKS) and
the functions that read it. Moved keys are listed at their new group (Stage / Task); masuser
accepts the old Info place too, for an AUTO-MAS from before v5.7.0-beta.3.

check() loads config/ScriptConfig.json, QueueConfig.json and PlanConfig.json the way the readers
do and returns every listed item that a node of its kind does not have. AUTO-MAS writes every
item of a node's model to the file (ConfigBase.load commits whenever its toDict differs from
the file, app/models/ConfigBase.py), so a key absent from an existing node is one the installed
version no longer keeps there. A level with no node at all (no OK-WW script, no plan table) is
not judged. scripts/mac/lib/automas_contract_watch.py compares the same list with a release's
app/models/config.py before the machine installs it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ark_relay.core import masuser


@dataclass(frozen=True)
class Item:
    kind: str       # "MAA" | "MaaEnd" | "OK-WW" | "queue" | "plan"
    level: str      # "script" | "user" | "queue" | "timeset" | "queueitem" | "plan"
    group: str
    key: str
    use: str        # feature id: texts.MAS_SETTING_WHAT / MAS_SETTING_BREAKS
    source: str     # where the relay reads (or writes) it
    since: str = "" # the AUTO-MAS version that brought it in; judged only from that version on

    @property
    def owner(self) -> str:
        """The AUTO-MAS model class that defines it (app/models/config.py)."""
        return OWNER[(self.kind, self.level)]

    @property
    def path(self) -> str:
        return f"{self.group}.{self.key}"


OWNER = {
    ("MAA", "script"): "MaaConfig", ("MAA", "user"): "MaaUserConfig",
    ("MaaEnd", "script"): "MaaEndConfig", ("MaaEnd", "user"): "MaaEndUserConfig",
    ("OK-WW", "script"): "OkwwConfig", ("OK-WW", "user"): "OkwwUserConfig",
    ("queue", "queue"): "QueueConfig", ("queue", "timeset"): "TimeSet",
    ("queue", "queueitem"): "QueueItem", ("plan", "plan"): "MaaPlanConfig",
}
# A ScriptConfig.json instance's "type" -> script kind (the machine's file has it; older test
# layouts do not, then the install path decides, as plan._script_kind does).
TYPE_KIND = {"MaaConfig": "MAA", "MaaEndConfig": "MaaEnd", "OkwwConfig": "OK-WW"}


def _items(kind, level, group, keys, use, source, since=""):
    return [Item(kind, level, group, k, use, source, since) for k in keys]


CONTRACT: tuple[Item, ...] = tuple([
    # ---- script level (ScriptConfig.json <script uid>.<group>)
    *_items("MAA", "script", "Info", ("Path",), "script_path",
            "plan.py:_scripts/_script_kind, stagegate.py:_maa_script, annihilation.py:_maa_users"),
    *_items("MaaEnd", "script", "Info", ("Path",), "script_path",
            "plan.py:_scripts/_script_kind, plan.py:script_dir, sanity_plan.py"),
    *_items("OK-WW", "script", "Info", ("RootPath",), "script_path",
            "plan.py:_scripts/_script_kind, plan.py:script_dir"),
    *_items("MAA", "script", "Info", ("Name",), "script_name",
            "snapshot.py:maa_from_files, commands.py:_find_user"),
    *_items("MaaEnd", "script", "Info", ("Name",), "script_name", "commands.py:_find_user"),
    *_items("OK-WW", "script", "Info", ("Name",), "script_name",
            "plan.py:_okww_quick_overrides, commands.py:_find_user"),
    *_items("MAA", "script", "Run", ("IfCheckGameUpdate", "IfAutoInstallGameApk"), "client_update",
            "selfcheck.py:_handed_updates_gaps"),
    *_items("OK-WW", "script", "Game", ("Enabled", "Path", "IfAutoUpdate"), "client_update",
            "selfcheck.py:_handed_updates_gaps"),
    *_items("MaaEnd", "script", "Game", ("WaitTime",), "maaend_wait",
            "commands.py:_set_wait_time (write)"),
    # LaunchMode / LauncherPath: AUTO-MAS v5.7.0-beta.4 (PR #1394); its pre-run check finds the
    # launcher from Game.Path (10-16 09:34 it refused the relay's .cmd there).
    *_items("MaaEnd", "script", "Game", ("Path",), "maaend_launch",
            "efstart_setup.py:install/launcher_for (write)"),
    *_items("MaaEnd", "script", "Game", ("LaunchMode", "LauncherPath"), "maaend_launch",
            "efstart_setup.py:install/launcher_for (write LaunchMode)", since="v5.7.0-beta.4"),
    # ---- MAA user (SubConfigsInfo.UserData.<uid>); Stage.* and Task.Annihilation via masuser
    *_items("MAA", "user", "Stage", ("StageMode", "Stage", "Stage_1", "Stage_2", "Stage_3", "SeriesNumb"),
            "stage", "plan.py:_scripts, stagegate.py:run_verdict, snapshot.py:maa_fields, "
            "commands.py:_set_stage (write)"),
    *_items("MAA", "user", "Stage", ("MedicineNumb",), "medicine",
            "plan.py:_stage_bits, snapshot.py:maa_fields, commands.py:_set_medicine (write)"),
    *_items("MAA", "user", "Task", ("IfFight",), "fight",
            "plan.py:_scripts, stagegate.py:run_verdict, snapshot.py:maa_fields"),
    *_items("MAA", "user", "Task", ("Annihilation",), "annihilation",
            "plan.py:_scripts, annihilation.py:WeeklyGate._status, snapshot.py:maa_fields"),
    *_items("MAA", "user", "Data", ("AnnihilationCompletedWeek",), "annihilation",
            "annihilation.py:WeeklyGate._status"),
    *_items("MAA", "user", "Task", ("IfActivityFirst", "ActivityStageIndex"), "activity",
            "snapshot.py:maa_fields, phone.py:state_payload"),
    # ---- MaaEnd user: the items the phone shows and changes (mas_labels.SHOWN)
    *_items("MaaEnd", "user", "Task", ("IfSanity", "IfAutoUseSpMedication", "SanityTaskType",
                                       "AutoEssenceSpecifiedLocation"), "maaend_phone",
            "snapshot.py:_mas, mas_labels.py:SHOWN, commands.py:_set_config (write)"),
    # ---- OK-WW user: the quick config the plan shows instead of OK-WW's own file
    *_items("OK-WW", "user", "Info", ("IfQuickConfig",), "okww_quick", "plan.py:_okww_quick_overrides"),
    *_items("OK-WW", "user", "Task", ("WhichToFarm", "WhichTacetSuppressionToFarm",
                                      "WhichForgeryChallengeToFarm", "MaterialSelection",
                                      "FarmNightmareNestForDailyEcho", "AdditionalTasks"), "okww_quick",
            "plan.py:_okww_quick_overrides, mas_labels.py:SHOWN"),
    # ---- QueueConfig.json
    *_items("queue", "queue", "Info", ("Name", "TimeEnabled", "CycleEnabled"), "queue_timer",
            "plan.py:_queues/queue_rows, queues.py:apply (write TimeEnabled), commands.py:skip_script_in_queue"),
    *_items("queue", "queue", "Info", ("AfterAccomplish",), "queue_after", "plan.py:_queues/next_plan"),
    *_items("queue", "queue", "Info", ("StartUpMode",), "queue_startup", "plan.py:_startup_runs"),
    *_items("queue", "timeset", "Info", ("Enabled", "Time", "Days"), "queue_timer",
            "plan.py:_queues/_queue_times"),
    *_items("queue", "queueitem", "Info", ("ScriptId",), "queue_items",
            "plan.py:_queues/queue_rows, commands.py:skip_script_in_queue, snapshot.py"),
    *_items("queue", "queueitem", "Schedule", ("Days",), "queue_items",
            "plan.py:_queues, commands.py:skip_script_in_queue (write)"),
    # ---- PlanConfig.json (the MAA stage plan a user's StageMode may point at)
    *_items("plan", "plan", "Info", ("Mode",), "plan_table", "plan.py:_stage_bits, stagegate.py"),
    *_items("plan", "plan", "ALL", ("Stage", "Stage_1", "Stage_2", "Stage_3", "MedicineNumb"),
            "plan_table", "plan.py:_stage_bits, stagegate.py"),
])


@dataclass
class Result:
    missing: list          # [Item] not found where the relay reads it
    unreadable: list       # [file name] that could not be read as JSON
    judged: int            # how many items had at least one node to be judged on


def _load(path: Path):
    """The file's JSON; None when it is not there; raises ValueError / OSError otherwise."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return json.loads(text)


def _nodes(data) -> list[tuple[dict, dict]]:
    """[(instance, node)] of a MultipleConfig file / SubConfigsInfo block, in instance order."""
    if not isinstance(data, dict):
        return []
    out = []
    for inst in data.get("instances") or []:
        node = data.get(inst.get("uid")) if isinstance(inst, dict) else None
        if isinstance(node, dict):
            out.append((inst, node))
    return out


def _entries(block) -> list[dict]:
    """The entries of a TimeSet / QueueItem block: every dict value but the instances list."""
    if not isinstance(block, dict):
        return []
    return [v for k, v in block.items() if k != "instances" and isinstance(v, dict)]


def _script_kind(inst: dict, node: dict) -> str:
    from ark_relay.core import plan  # noqa: PLC0415 - plan imports config; keep this module light
    kind = TYPE_KIND.get(str(inst.get("type") or ""))
    if kind:
        return kind
    info = node.get("Info") or {}
    return plan._script_kind(info.get("Path") or info.get("RootPath") or "")


def _has(node: dict, group: str, key: str) -> bool:
    g = node.get(group)
    return isinstance(g, dict) and key in g


def _user_has(user: dict, item: Item) -> bool:
    if masuser.MOVED.get(item.key) == item.group:
        return _has(user, masuser.group_of(user, item.key), item.key)
    return _has(user, item.group, item.key)


def nodes_by_level(cfg_dir: Path, unreadable: list) -> dict[tuple[str, str], list[dict]]:
    """{(kind, level): [node]} from the three files; a file that cannot be read goes to
    `unreadable` and gives no nodes."""
    def load(name):
        try:
            return _load(cfg_dir / name)
        except (OSError, ValueError):
            unreadable.append(name)
            return None
    out: dict = {k: [] for k in OWNER}
    for inst, node in _nodes(load("ScriptConfig.json")):
        kind = _script_kind(inst, node)
        if not kind:
            continue
        out[(kind, "script")].append(node)
        users = (node.get("SubConfigsInfo") or {}).get("UserData")
        out[(kind, "user")] += [u for _, u in _nodes(users)] or _entries(users)
    for _, node in _nodes(load("QueueConfig.json")):
        out[("queue", "queue")].append(node)
        sub = node.get("SubConfigsInfo") or {}
        out[("queue", "timeset")] += _entries(sub.get("TimeSet"))
        out[("queue", "queueitem")] += _entries(sub.get("QueueItem"))
    plans = load("PlanConfig.json")
    for inst, node in _nodes(plans) or [({}, v) for v in _entries(plans)]:
        # Only the MAA stage plans: the file may hold MaaEnd / BAAH / MSS plans as well.
        if inst.get("type", "MaaPlanConfig") == "MaaPlanConfig" and isinstance(node.get("ALL"), dict):
            out[("plan", "plan")].append(node)
    return out


_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")


def version_key(version: str) -> "tuple[int, ...] | None":
    """v5.7.0-beta.4 -> (5, 7, 0, 0, 4); v5.7.0 -> (5, 7, 0, 1, 0), after its betas; None
    when it does not read as an AUTO-MAS version."""
    m = _VERSION.match(str(version or "").strip())
    if not m:
        return None
    major, minor, patch, beta = m.groups()
    return (int(major), int(minor), int(patch), 0 if beta else 1, int(beta or 0))


def check(automas_dir, version: str = "") -> Result:
    """Every CONTRACT item a node of its kind does not have, read from <automas_dir>/config.

    `version` is the installed AUTO-MAS's own (the backend's /api/core/health; its
    res/version.json is not rewritten by newer builds). An item with `since` is judged only
    when that version is known and not older: an older AUTO-MAS never had it, and the
    recorded days of the day simulator run v5.6.2 to v5.7.0-beta.3."""
    cfg_dir = Path(automas_dir) / "config" if automas_dir else None
    if cfg_dir is None or not cfg_dir.is_dir():
        return Result([], ["config"], 0)
    unreadable: list = []
    by_level = nodes_by_level(cfg_dir, unreadable)
    have = version_key(version)
    missing, judged = [], 0
    for item in CONTRACT:
        nodes = by_level.get((item.kind, item.level)) or []
        if not nodes:
            continue
        if item.since and (have is None or have < version_key(item.since)):
            continue
        judged += 1
        if item.level == "user":
            ok = all(_user_has(n, item) for n in nodes)
        else:
            ok = all(_has(n, item.group, item.key) for n in nodes)
        if not ok:
            missing.append(item)
    return Result(missing, unreadable, judged)
