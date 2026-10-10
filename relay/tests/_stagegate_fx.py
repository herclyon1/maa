"""Fixtures for the stage gate tests: an MAA install's task folders and an AUTO-MAS config.

The task folders copy the shape of the machine on 2026-10-10: resource/tasks holds
tasks.json plus sub-folders (Stages/ with 47 files incl. YW.json, MiniGame/,
Roguelike/ ...), cache/resource/tasks holds the hot-update tasks.json.

What MAA itself said that morning when AUTO-MAS handed it YW-4 (asst.log, machine
time; the stage was in stages.json but not in resource/tasks/Stages/YW.json):

    [2026-10-10 09:01:10.060][ERR][Px17028][Tx55502] Unknown task: YW-4
    [2026-10-10 09:01:10.060][ERR][Px17028][Tx55502] Task YW-4 not found
    [2026-10-10 09:01:10.061][ERR][Px17028][Tx55502] The stage name is not in invalid, or is not main line stage YW-4
    [2026-10-10 09:01:10.061][ERR][Px17028][Tx55502] Cannot set stage YW-4

gui.log then had 「理智作战: 理智作战 序列化失败」 and 「已停止」: the whole MAA run
stopped, AUTO-MAS retried three times and nothing was done.
"""
from __future__ import annotations

import json
from pathlib import Path

# Keys of Stages/YW.json in the morning (the navigation for YW-4 was not there yet)
YW_MORNING = ("YW-6", "YW-7", "YW-8")
# ... and after the upstream file was placed on the machine at 13:04
YW_AFTERNOON = ("YW-6", "YW-7", "YW-8", "YW-4", "YW-*@SideStoryStage", "YW-OpenOpt", "YW-Open", "YW-OpenOcr")

TASKS_JSON = ("LastOrCurBattleBegin", "StageBegin", "Episode1", "Episode12", "Episode15",
              "ChapterDifficultyHard", "ChapterDifficultyNormal",
              "ChangeToRaidDifficulty", "RaidConfirm", "ChangeToNormalDifficulty")


def _write(path: Path, keys) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: {"algorithm": "JustReturn"} for k in keys}), encoding="utf-8")


def maa_dir(root: Path, yw=YW_MORNING) -> Path:
    """An MAA install with the given YW.json keys; returns its folder."""
    tasks = root / "resource" / "tasks"
    _write(tasks / "tasks.json", TASKS_JSON)
    _write(tasks / "Stages" / "YW.json", yw)
    _write(tasks / "Stages" / "OR.json", ("OR-8", "OR-OpenOpt"))
    _write(tasks / "Roguelike" / "Sami.json", ("Sami@Roguelike@Begin",))
    _write(tasks / "MiniGame" / "Shop.json", ("MiniGame@Shop",))
    _write(root / "cache" / "resource" / "tasks" / "tasks.json", ("HotFix-1",))
    return root


def set_yw(root: Path, yw) -> None:
    _write(root / "resource" / "tasks" / "Stages" / "YW.json", yw)


def automas_dir(root: Path, *, stage="YW-4", stage_1="-", fight=True, mode="Fixed",
                plan: dict | None = None, queues=None) -> Path:
    """An AUTO-MAS config: MAA (one user) + MaaEnd, and two timed queues.

    queues: {name: (HH:MM, [kinds])}, default 早班 09:00 [MAA, MaaEnd] and 晚班 21:30 [MAA].
    """
    cfg = root / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    user = {"Info": {"Name": "arknights", "Stage": stage, "Stage_1": stage_1, "Stage_2": "-",
                     "Stage_3": "-", "StageMode": mode, "MedicineNumb": 0},
            "Task": {"IfFight": fight}}
    scripts = {
        "instances": [{"uid": "S-MAA"}, {"uid": "S-END"}],
        "S-MAA": {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"},
                  "SubConfigsInfo": {"UserData": {"instances": [{"uid": "U1"}], "U1": user}}},
        "S-END": {"Info": {"Name": "MaaEnd", "Path": "D:\\ark\\maaend"},
                  "SubConfigsInfo": {"UserData": {"instances": [{"uid": "U2"}],
                                                  "U2": {"Info": {"Name": "x"}, "Task": {}}}}},
    }
    (cfg / "ScriptConfig.json").write_text(json.dumps(scripts, ensure_ascii=False), encoding="utf-8")
    sid = {"MAA": "S-MAA", "MaaEnd": "S-END"}
    queues = queues or {"早班": ("09:00", ["MAA", "MaaEnd"]), "晚班": ("21:30", ["MAA"])}
    qc: dict = {"instances": []}
    for n, (name, (hhmm, kinds)) in enumerate(queues.items()):
        uid = f"Q{n}"
        qc["instances"].append({"uid": uid})
        qc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                   "SubConfigsInfo": {
                       "TimeSet": {"instances": [], "T1": {"Info": {"Enabled": True, "Time": hhmm}}},
                       "QueueItem": {"instances": [],
                                     **{f"I{i}": {"Info": {"ScriptId": sid[k]}} for i, k in enumerate(kinds)}}}}
    (cfg / "QueueConfig.json").write_text(json.dumps(qc, ensure_ascii=False), encoding="utf-8")
    if plan is not None:
        (cfg / "PlanConfig.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return root
