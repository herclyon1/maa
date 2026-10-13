"""Ask the real MaaCore whether it accepts the tasks the machine's config makes AUTO-MAS hand it.

MAA's GUI logs 「<task> 序列化失败」 when AsstAppendTask returns 0: the core refused the
params (2026-10-10 09:01, stage YW-4, the whole run stopped). The relay decides ahead of
time with stagegate.py, which imitates FightTask::set_params and
StageNavigationTask::set_stage_name. Here the real core gives the verdict instead, on the
params MAA itself sent (asst.log), and the imitation is compared with it stage by stage.

Why no device is needed: asst::Assistant::append_task (pinned
src/MaaCore/Assistant.cpp; its body hash is in tests/test_gl_maa_config.py PINNED_BODIES)
parses the JSON, builds the task, calls set_params and returns 0 when that fails, else a
task id. It touches no controller. AsstCreate needs only a loaded resource (AsstCaller.cpp,
inited()). So: AsstLoadResource -> AsstCreate -> AsstAppendTask, nothing else.

MaaCore loads every resource file in one AsstLoadResource call and a partial folder does
not load (ResourceLoader::load requires the models and config files), so each task tree
(the release's own, plus MAA dev's Stages/YW.json at c09d3fe7 and at cc780293, as the
machine had them on 10-10 and 10-11) runs in its own child process over the same unpacked
release, with YW.json swapped in between.

    python append_check.py --maa <unpacked MAA release>     # MaaCore next to resource/
    python append_check.py --fetch <empty folder>           # download the pinned tag first

Not run on the Mac (no MaaCore there by design); it runs in the Windows job.
Exit 0 with "all checks passed": every verdict as recorded; 1: a verdict differs;
2: MaaCore could not be loaded or the release could not be fetched.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))          # relay/tests: gamesim.lib
sys.path.insert(0, str(HERE.parents[2]))          # relay: ark_relay (stagegate)

from gamesim.lib import maa_schema as S  # noqa: E402

TAG = "v6.19.0-beta.1"
REPO = "MaaAssistantArknights/MaaAssistantArknights"
ASSET = {"win32": f"MAA-{TAG}-win-x64.zip", "linux": f"MAA-{TAG}-linux-x86_64.tar.gz"}
CORE = {"win32": "MaaCore.dll", "linux": "libMaaCore.so", "darwin": "libMaaCore.dylib"}

# Params as MAA's GUI sent them (asst.log, COS bundle 2026-10-10_arknights_MAA-05-00-01,
# 2026-10-06 21:31:12 and 2026-10-10 09:01:10); penguin_id emptied.
FIGHT = {"medicine": 999, "medicine_expire_days": 0, "stone": 0, "times": 2147483647, "series": 0,
         "DrGrandet": False, "report_to_penguin": True, "penguin_id": "", "report_to_yituliu": True,
         "server": "CN", "client_type": "Official"}
INFRAST = {"facility": ["Mfg", "Trade", "Control", "Power", "Reception", "Office", "Dorm", "Processing",
                        "Training", "AssistantChange"],
           "drones": "Money", "continue_training": False, "threshold": 0.3, "dorm_notstationed_enabled": True,
           "dorm_trust_enabled": True, "replenish": True, "reception_message_board": True,
           "reception_clue_exchange": True, "reception_send_clue": True,
           "fiammetta_targets": ["清流", "可露希尔", "但书"], "fiammetta_recovery_enabled": False,
           "use_pinus_sylvestris": False, "use_perception_information": False, "use_worldly_plight": False,
           "use_abyssal_hunter": False, "mode": 0}
AWARD = {"award": True, "mail": False, "recruit": False, "orundum": False, "mining": False,
         "specialaccess": False, "signinevent": False}

# (tree, task type, params, accepted?, evidence). Trees: "tag" = the release's own,
# "c09d3fe7" / "cc780293" = with that dev commit's Stages/YW.json.
CASES = [
    ("c09d3fe7", "Fight", {"stage": "YW-4", **FIGHT}, False,
     "asst.log 2026-10-10 09:01:10.061 'Cannot set stage YW-4' / 'append_task | invalid params'"),
    ("cc780293", "Fight", {"stage": "YW-4", **FIGHT}, True,
     "asst.log 2026-10-11 21:30:43.512 'directly task YW-4', set_params left without error"),
    ("tag", "Fight", {"stage": "1-7", **FIGHT}, True,
     "asst.log 2026-10-06 21:31:12.189 'directly task 1-7', 'append_task | task_id: 2'"),
    ("tag", "Fight", {"stage": "YW-8", "enable": True, "medicine": 0, "stone": 0, "times": 99, "series": 0}, False,
     "asst.log 2026-10-09 19:57:34.256 'Cannot set stage YW-8': the machine had no YW.json yet "
     "(c09d3fe7's has YW-8, so with it YW-8 would have been taken)"),
]
CASES += [("tag", "Infrast", {**INFRAST, "drones": d}, True,
           "MAA's own UsesOfDronesList offers it (InfrastSettingsUserControlModel.cs); "
           "'Money' sent and accepted 2026-10-06 21:31:12.194") for d in S.drone_keys()]
CASES += [("tag", "Award", {**AWARD, key: True}, True,
           "AwardTask.cpp set_params reads it; the GUI's AsstAwardTask sends it")
          for key in ("mail", "orundum", "mining", "specialaccess")]


def fetch(dest: Path) -> Path:
    """Download and unpack the release asset of TAG for this platform into dest."""
    name = ASSET[sys.platform]
    api = f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"
    with urllib.request.urlopen(api, timeout=60) as r:
        asset = next(a for a in json.load(r)["assets"] if a["name"] == name)
    archive = dest / name
    with urllib.request.urlopen(asset["browser_download_url"], timeout=600) as r, archive.open("wb") as out:
        shutil.copyfileobj(r, out)
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest / "MAA")
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest / "MAA", filter="data")
    core = next((dest / "MAA").rglob(CORE[sys.platform]))
    return core.parent


def run_tree(maa: Path, jobs: list[list]) -> list[int]:
    """In this process: load MaaCore and the resource once, append every job, return task ids."""
    if sys.platform == "win32":
        os.add_dll_directory(str(maa))
    lib = ctypes.CDLL(str(maa / CORE[sys.platform]))
    lib.AsstLoadResource.argtypes, lib.AsstLoadResource.restype = [ctypes.c_char_p], ctypes.c_uint8
    lib.AsstCreate.argtypes, lib.AsstCreate.restype = [], ctypes.c_void_p
    lib.AsstAppendTask.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    lib.AsstAppendTask.restype = ctypes.c_int32
    lib.AsstDestroy.argtypes, lib.AsstDestroy.restype = [ctypes.c_void_p], None
    if not lib.AsstLoadResource(str(maa).encode("utf-8")):
        raise RuntimeError(f"AsstLoadResource({maa}) failed")
    handle = lib.AsstCreate()
    if not handle:
        raise RuntimeError("AsstCreate returned null")
    try:
        return [lib.AsstAppendTask(handle, t.encode(), json.dumps(p, ensure_ascii=False).encode("utf-8"))
                for t, p in jobs]
    finally:
        lib.AsstDestroy(handle)


def set_tree(maa: Path, tree: str) -> None:
    yw = maa / "resource" / "tasks" / "Stages" / "YW.json"
    if tree == "tag":
        yw.unlink(missing_ok=True)
    else:
        shutil.copyfile(S.PIN / f"maa-dev-{tree}" / "resource" / "tasks" / "Stages" / "YW.json", yw)


def stage_names() -> list[str]:
    """Stage names to compare stagegate with the core on: every non-template key of the
    pinned Stages/*.json, and main-line chapter/episode pairs either side of what exists."""
    names = {""}
    for f in sorted((S.MAA / "resource" / "tasks" / "Stages").glob("*.json")):
        names |= {k for k in json.loads(f.read_text(encoding="utf-8")) if "@" not in k}
    names |= {f"{c}-{n}" for c in range(0, 17) for n in (1, 7, 20)}
    names |= {f"{c}-1-{d}" for c in (9, 10, 15) for d in ("Hard", "Normal")}
    return sorted(names)


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--child"]:        # one tree, in its own process
        jobs = json.loads(sys.stdin.read())
        print(json.dumps(run_tree(Path(args[1]), jobs)))
        return 0
    try:
        if args[:1] == ["--fetch"]:
            maa = fetch(Path(args[1]))
        elif args[:1] == ["--maa"]:
            maa = Path(args[1])
        else:
            print(__doc__)
            return 2
    except (OSError, StopIteration, KeyError) as exc:
        print(f"could not get MaaCore: {type(exc).__name__}: {exc}")
        return 2

    from ark_relay.features.schedule import stagegate  # noqa: PLC0415 - needs the relay path set above

    fails: list[str] = []
    names = stage_names()
    for tree in ("tag", "c09d3fe7", "cc780293"):
        set_tree(maa, tree)
        mine = [(t, p) for tr, t, p, _, _ in CASES if tr == tree]
        jobs = [[t, p] for t, p in mine] + [["Fight", {"stage": n, **FIGHT}] for n in names]
        out = subprocess.run([sys.executable, __file__, "--child", str(maa)], input=json.dumps(jobs),
                             capture_output=True, text=True, timeout=600, check=False)
        if out.returncode != 0:
            print(f"[{tree}] MaaCore did not run: {out.stderr[-2000:]}")
            return 2
        ids = json.loads(out.stdout.strip().splitlines()[-1])
        print(f"[{tree}]")
        for (tr, t, p, want, why), task_id in zip([c for c in CASES if c[0] == tree], ids, strict=False):
            ok = (task_id > 0) == want
            label = f"{t} {p.get('stage', p.get('drones', [k for k, v in p.items() if v is True]))}"
            print(f"  {'✓' if ok else '✗'} {label}: core {'accepts' if task_id > 0 else 'refuses'}"
                  f" ({'expected' if ok else 'recorded otherwise'}: {why})")
            if not ok:
                fails.append(f"{tree} {label}")
        for name, task_id in zip(names, ids[len(mine):], strict=True):
            verdict, why = stagegate.check(name, maa)
            if verdict == stagegate.UNKNOWN:
                continue
            if (verdict == stagegate.YES) != (task_id > 0):
                print(f"  ✗ stagegate says {verdict} for {name!r}, MaaCore {'accepts' if task_id > 0 else 'refuses'}: {why}")
                fails.append(f"{tree} stagegate {name!r}")
        print(f"  stagegate agrees with MaaCore on {len(names)} stage names (unknown ones skipped)")
    set_tree(maa, "tag")
    if fails:
        print(f"FAIL: {len(fails)}: " + "; ".join(fails[:8]))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
