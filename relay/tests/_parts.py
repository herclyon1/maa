"""Run the parts of a merged test file one after another, each as if it were its own file,
and the helpers every part shares (dispatches relay-slim-round1-1108 / round2-1108).
"""
from __future__ import annotations

import atexit
import gzip
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import types
from pathlib import Path

# relay/tests/ only. relay/ itself is not put here: each part adds it as its file did, and a
# part may test what happens before it is there (test_deploy's deploy_watch part reads a cap
# from a relay folder that does not exist and wants ModuleNotFoundError).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


_MADE: list[str] = []
_FX_CACHE: dict[str, Path] = {}
_FX_DATA: dict[str, dict[str, str]] | None = None
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
    global _FX_DATA  # noqa: PLW0603
    if _FX_DATA is None:
        sf = _TESTS_DIR / "fx_samples.json"
        _FX_DATA = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    for rel, content in (_FX_DATA.get(kind) or {}).items():
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
    """Remove the test's directories once the test is over."""
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


__all__ = ["check", "fails", "fx_dir", "require", "run_parts", "stagegate_fx", "tmpdir"]

# The failed checks of the part running now; emptied before each part.
fails: list[str] = []
# How long a part's own threads get to finish once it is over (a push thread delivering to
# a fake notifier ends at once; one blocked on a real wait is left, daemon as it was).
SETTLE_S = 2.0


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)
    return ok


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok or not detail else f": {detail}"))
    if not ok:
        fails.append(name)
    return bool(ok)


def _loggers() -> dict:
    out = {"": logging.getLogger()}
    for name, lg in logging.Logger.manager.loggerDict.items():
        if isinstance(lg, logging.Logger):
            out[name] = lg
    return out


def _snapshot() -> dict:
    mods = dict(sys.modules)
    return {
        "mods": mods,
        "dicts": {n: dict(m.__dict__) for n, m in mods.items() if m is not None and hasattr(m, "__dict__")},
        "env": dict(os.environ),
        "path": list(sys.path),
        "argv": list(sys.argv),
        "cwd": os.getcwd(),
        "loggers": {n: (list(lg.handlers), lg.level, lg.propagate, lg.disabled) for n, lg in _loggers().items()},
        "threads": set(threading.enumerate()),
    }


def _settle(s: dict) -> None:
    """Close what the part left running while its modules are still loaded."""
    before = {id(h) for handlers, *_ in s["loggers"].values() for h in handlers}
    for lg in _loggers().values():
        for h in list(lg.handlers):
            if id(h) not in before:
                try:
                    h.close()
                except Exception:  # noqa: BLE001 - a handler that cannot close is dropped all the same
                    pass
    ew = sys.modules.get("ark_relay.features.errwatch")
    h = (getattr(ew, "_handler", None) or [None])[0] if ew is not None else None
    if h is not None:
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    end = time.monotonic() + SETTLE_S
    for t in [t for t in threading.enumerate() if t not in s["threads"]]:
        t.join(max(0.0, end - time.monotonic()))


def _restore(s: dict) -> None:
    for name in [n for n in sys.modules if n not in s["mods"]]:
        del sys.modules[name]
    for name, m in s["mods"].items():
        sys.modules[name] = m
    for name, saved in s["dicts"].items():
        m = s["mods"][name]
        try:
            cur = m.__dict__
            for k in [k for k in cur if k not in saved]:
                del cur[k]
            for k, v in saved.items():
                if cur.get(k, cur) is not v:
                    cur[k] = v
        except (TypeError, AttributeError):
            continue        # a read-only module dict holds nothing a test can swap
    sys.path[:] = s["path"]
    sys.argv[:] = s["argv"]
    os.environ.clear()
    os.environ.update(s["env"])
    os.chdir(s["cwd"])
    for name, lg in _loggers().items():
        handlers, level, propagate, disabled = s["loggers"].get(name, ([], logging.NOTSET, True, False))
        lg.handlers[:] = handlers
        lg.setLevel(level)
        lg.propagate, lg.disabled = propagate, disabled
    logging.Logger.manager._clear_cache()


def run_parts(parts) -> int:
    """Run each part in turn; 0 when every part passed, else 1. Never stops at a failed part."""
    saved_outer = list(fails)
    failed = []
    for part in parts:
        print(f"\n===== {part.__name__}", flush=True)
        fails.clear()
        snap = _snapshot()
        code = 0
        t0 = time.monotonic()
        try:
            part()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except BaseException:      # noqa: BLE001 - a crashing part is a failed part, the rest still run
            traceback.print_exc()
            code = 1
        finally:
            sys.stdout.flush()
            _settle(snap)
            _restore(snap)
        print(f"  ({part.__name__}: {time.monotonic() - t0:.1f} s)")
        if fails:
            print(f"  FAILED: {', '.join(fails)}")
            code = code or 1
        if code:
            failed.append(part.__name__)
    fails[:] = saved_outer
    print("\n" + (f"FAILED parts: {', '.join(failed)}" if failed else f"all {len(parts)} parts passed"))
    return 1 if failed else 0
