"""测试用的临时目录：进程退出时自己收拾干净。

2026-09-08 量到的：39 个测试各自 `tempfile.mkdtemp()` 且从不清理，Mac 的 TMPDIR
里堆了 29753 个目录、710 MB。每跑一次全套就多几十个，macOS 只在重启时才清。

用法和 mkdtemp 一样，返回 Path：

    from _tmp import tmpdir
    d = tmpdir()

要留下现场看的时候（排查失败），设环境变量 `ARK_KEEP_TMP=1`，就不删了。
"""
from __future__ import annotations

import atexit
import gzip
import json
import logging
import os
import shutil
import tempfile
import types
from pathlib import Path

_MADE: list[str] = []
_FX_CACHE: dict[str, Path] = {}
_TESTS_DIR = Path(__file__).resolve().parent

# Config.alert_push_url defaults to the real Mac (macpush.py): a test alarm must
# never be POSTed there. A test that exercises the push sets its own URL.
os.environ.setdefault("ARK_ALERT_PUSH_URL", "")


def tmpdir(prefix: str = "arktest-") -> Path:
    d = tempfile.mkdtemp(prefix=prefix)
    _MADE.append(d)
    return Path(d)


def fx_dir(anchor: object, kind: str) -> Path:
    """Materialize the test sample catalog `fx_<kind>.json` once per process and return its root."""
    _ = anchor
    if kind in _FX_CACHE:
        return _FX_CACHE[kind]
    out = tmpdir(f"arkfx-{kind}-")
    cat_file = _TESTS_DIR / f"fx_{kind}.json"
    if cat_file.exists():
        data: dict[str, str] = json.loads(cat_file.read_text(encoding="utf-8"))
        for rel, content in data.items():
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith(".gz"):
                dest.write_bytes(gzip.compress(content.encode("utf-8"), mtime=0))
            else:
                dest.write_bytes(content.encode("utf-8"))
    native_dir = _TESTS_DIR / kind
    if native_dir.is_dir():
        for src in native_dir.rglob("*"):
            if src.is_file():
                dest = out / src.relative_to(native_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
    _FX_CACHE[kind] = out
    return out


@atexit.register
def _cleanup() -> None:
    """Remove the test's directories once the test is over.

    Logging is switched off first. A test that started a directory watcher
    (watch.start, through collect_watch.start) leaves its daemon thread holding
    a directory removed here; on Windows the change notification then fails and
    the watcher logs 「目录监听掉了，5 秒后重建」, as it should in service. That
    line landed after the test's result line (Windows CI, 2026-10-07: runs
    37519943859 test_collect.py and 37525386830 test_maaend_watchdog.py),
    and the test gate reads the last line. Nothing the test checks runs here.
    """
    logging.disable(logging.CRITICAL)
    if os.environ.get("ARK_KEEP_TMP"):
        return
    for d in _MADE:
        shutil.rmtree(d, ignore_errors=True)


def stagegate_fx():
    """Shared MAA stage-gate and AUTO-MAS config fixture builders."""
    yw_morning = ("YW-6", "YW-7", "YW-8")
    yw_afternoon = ("YW-6", "YW-7", "YW-8", "YW-4", "YW-*@SideStoryStage", "YW-OpenOpt", "YW-Open", "YW-OpenOcr")
    tasks_json = ("LastOrCurBattleBegin", "StageBegin", "Episode1", "Episode12", "Episode15",
                  "ChapterDifficultyHard", "ChapterDifficultyNormal",
                  "ChangeToRaidDifficulty", "RaidConfirm", "ChangeToNormalDifficulty")

    def _write(path: Path, keys) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({k: {"algorithm": "JustReturn"} for k in keys}), encoding="utf-8")

    def maa_dir(root: Path, yw=yw_morning) -> Path:
        tasks = root / "resource" / "tasks"
        _write(tasks / "tasks.json", tasks_json)
        _write(tasks / "Stages" / "YW.json", yw)
        _write(tasks / "Stages" / "OR.json", ("OR-8", "OR-OpenOpt"))
        _write(tasks / "Roguelike" / "Sami.json", ("Sami@Roguelike@Begin",))
        _write(tasks / "MiniGame" / "Shop.json", ("MiniGame@Shop",))
        _write(root / "cache" / "resource" / "tasks" / "tasks.json", ("HotFix-1",))
        return root

    def set_yw(root: Path, yw) -> None:
        _write(root / "resource" / "tasks" / "Stages" / "YW.json", yw)

    def automas_dir(root: Path, *, stage="YW-4", stage_1="-", fight=True, mode="Fixed",
                    plan: dict | None = None, queues=None, beta3: bool = False) -> Path:
        cfg = root / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        stage_items = {"Stage": stage, "Stage_1": stage_1, "Stage_2": "-", "Stage_3": "-",
                       "StageMode": mode, "MedicineNumb": 0}
        if beta3:
            user = {"Info": {"Name": "arknights", "Base": "Shared", "Status": True, "RemainedDay": -1},
                    "Stage": {**stage_items, "SeriesNumb": "0"},
                    "Task": {"IfFight": fight, "Annihilation": "Annihilation", "IfActivityFirst": True,
                             "ActivityStageIndex": 1},
                    "Data": {"AnnihilationCompletedWeek": "2000-W01"}}
        else:
            user = {"Info": {"Name": "arknights", **stage_items}, "Task": {"IfFight": fight}}
        scripts = {
            "instances": [{"uid": "S-MAA"}, {"uid": "S-END"}],
            "S-MAA": {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"},
                      "SubConfigsInfo": {"UserData": {"instances": [{"uid": "U1"}], "U1": user}}},
            "S-END": {"Info": {"Name": "MaaEnd", "Path": "D:\\ark\\maaend"},
                      "SubConfigsInfo": {"UserData": {"instances": [{"uid": "U2"}],
                                                      "U2": {"Info": {"Name": "x"}, "Task": {}}}}},
        }
        if beta3:
            scripts["S-MAA"]["Run"] = {"IfCheckGameUpdate": True, "IfAutoInstallGameApk": True}
            scripts["S-END"]["Game"] = {"WaitTime": 60,
                                        "Path": "D:\\endfield\\Hypergryph Launcher\\games\\Endfield Game\\Endfield.exe",
                                        "ControllerType": "Win32-Front", "SetResolution": False, "CloseOnFinish": True,
                                        "RestoreDisplayType": "Window", "RestoreResolution": "Off"}
            scripts["S-END"]["SubConfigsInfo"]["UserData"]["U2"]["Task"] = {
                "IfSanity": True, "IfAutoUseSpMedication": False, "SanityTaskType": "ProtocolSpace",
                "AutoEssenceSpecifiedLocation": ""}
        (cfg / "ScriptConfig.json").write_text(json.dumps(scripts, ensure_ascii=False), encoding="utf-8")
        sid = {"MAA": "S-MAA", "MaaEnd": "S-END"}
        queues = queues or {"早班": ("09:00", ["MAA", "MaaEnd"]), "晚班": ("21:30", ["MAA"])}
        qc: dict = {"instances": []}
        week = {"Days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]} if beta3 else {}
        for n, (name, (hhmm, kinds)) in enumerate(queues.items()):
            uid = f"Q{n}"
            qc["instances"].append({"uid": uid})
            qc[uid] = {"Info": {"Name": name, "TimeEnabled": True,
                                **({"CycleEnabled": False, "AfterAccomplish": "NoAction", "StartUpMode": "Never"}
                                   if beta3 else {})},
                       "SubConfigsInfo": {
                           "TimeSet": {"instances": [], "T1": {"Info": {"Enabled": True, "Time": hhmm, **week}}},
                           "QueueItem": {"instances": [],
                                         **{f"I{i}": {"Info": {"ScriptId": sid[k]},
                                                      **({"Schedule": dict(week)} if beta3 else {})}
                                            for i, k in enumerate(kinds)}}}}
        (cfg / "QueueConfig.json").write_text(json.dumps(qc, ensure_ascii=False), encoding="utf-8")
        if plan is not None:
            (cfg / "PlanConfig.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        return root

    return types.SimpleNamespace(
        YW_MORNING=yw_morning, YW_AFTERNOON=yw_afternoon, TASKS_JSON=tasks_json,
        maa_dir=maa_dir, set_yw=set_yw, automas_dir=automas_dir,
    )
