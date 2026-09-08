"""The config **actually in effect** on the machine: read in one place, used in two.

The user, 2026-08-31: 「手机上的所有状态必须和机器保持一致，否则你动了配置
不同步到我这边会造成麻烦。」

So what the phone shows and what `scripts/mac/config-check.py` shows must come out of
**the same code** — write the reader twice and the two will disagree sooner or later,
and "the screen says one thing, the machine another" is exactly the soil incidents of
the 826 kind grow in. config-check calls in here now as well.

The data comes from AUTO-MAS's own backend API, not from its config files: while the
backend is running it overwrites those files from its in-memory copy, so reading a file
gets you a value that is about to be flushed away. OK-WW's own config is outside
AUTO-MAS's reach, so that one can only be read from file.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.request
from pathlib import Path

log = logging.getLogger("ark.snapshot")

def _api() -> str:
    from .config import mas_base  # noqa: PLC0415
    return mas_base()
# Read the **master copy**, not OK-WW's own. Before every run AUTO-MAS copies the
# master over wholesale (see the comment on config.master_config_dir), so the copy in
# the script directory reflects the config used on the **previous** round, not the one
# in effect now. On 2026-08-31 I used it to decide whether the weekly boss was
# configured and reached the exact opposite conclusion from the master copy.
OKWW_FILES = ("NightmareNestTask.json", "DailyTask.json", "FarmEchoTask.json",
              "TacetTask.json", "ForgeryTask.json")


def _post(path: str, body: "dict | None" = None, timeout: int = 15) -> dict:
    # **Every** AUTO-MAS endpoint is POST, the read-only ones included. GET returns
    # Method Not Allowed — this cost time on 2026-08-26.
    req = urllib.request.Request(
        _api() + path, data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _mas(out: dict) -> None:
    scripts = _post("/api/scripts/get")["data"]
    for uid, sc in scripts.items():
        info = sc.get("Info", {})
        name = info.get("Name") or info.get("RootPath", uid)
        try:
            users = _post("/api/scripts/user/get", {"scriptId": uid}).get("data") or {}
        except Exception:  # noqa: BLE001
            users = {}
        for _, u in users.items():
            if name == "MAA":
                i, t = u.get("Info", {}), u.get("Task", {})
                out["MAA"] = {
                    "关卡": i.get("Stage"),
                    "关卡链": [i.get(f"Stage_{n}") for n in (1, 2, 3)],
                    "理智药": i.get("MedicineNumb"),
                    "连战": i.get("SeriesNumb"),
                    "关卡模式": i.get("StageMode"),
                    "剿灭": i.get("Annihilation"),
                    "活动关优先": t.get("IfActivityFirst"),
                    "活动关序号": t.get("ActivityStageIndex"),
                    "活动关理智药": t.get("ActivityMedicineNumb"),
                    "作战开关": t.get("IfFight"),
                }
            elif name == "MaaEnd":
                t = u.get("Task", {})
                st = t.get("SanityTaskType")
                out["MaaEnd"] = {
                    "理智任务": st,
                    "详细": t.get(st) if st else None,
                    "开理智": t.get("IfSanity"),
                    "自动吃药": t.get("IfAutoUseSpMedication"),
                    "基质地点": t.get("AutoEssenceSpecifiedLocation"),
                }
            elif "OK-WW" in str(name) or "ok-ww" in str(name):
                out["OK-WW(MAS侧)"] = u.get("Task", {})


def _queues(out: dict) -> None:
    # Use .get: field names differ between AUTO-MAS versions, and on 2026-08-31
    # indexing StartUpEnabled directly raised KeyError, which took out the whole
    # queue section — not a single line of it came through.
    # Which scripts each shift runs. The phone filters config by shift with this —
    # the user, 2026-09-04: 「早班晚班切换的时候应该只显示当次班次的游戏，否则极
    # 容易和早班混淆。」
    names = {sid: str((v.get("Info") or {}).get("Name") or "")
             for sid, v in _post("/api/scripts/get")["data"].items()}
    out["队列"] = {}
    for qid, c in _post("/api/queue/get")["data"].items():
        info = c.get("Info") or {}
        try:
            items = _post("/api/queue/item/get", {"queueId": qid})["data"].values()
            scripts = [names.get(str((i.get("Info") or {}).get("ScriptId")), "")
                       for i in items]
        except Exception:  # noqa: BLE001 - unreadable = absent; don't sink the queue section
            scripts = []
        out["队列"][str(info.get("Name") or "?")] = {
            "定时": info.get("TimeEnabled"),
            "开机跑": info.get("StartUpEnabled"),
            "脚本": [x for x in scripts if x],
        }


def _automas_dir() -> "str | None":
    """AUTO-MAS root directory. Environment variable first, then the relay's .env.

    This module is imported by the service process (where the environment is complete)
    and also run by config-check.py as a standalone probe (where nothing is set). On
    2026-08-31 it read os.environ only, so the probe path never found anything and the
    snapshot held nothing but the one line 「找不到母本目录」.
    """
    if v := os.environ.get("ARK_AUTOMAS_DIR"):
        return v
    env = Path(r"C:\ProgramData\ark-relay\.env")
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ARK_AUTOMAS_DIR=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip() or None
    except OSError:
        pass
    return None


def _okww(out: dict) -> None:
    from .config import master_config_dir  # noqa: PLC0415 - avoid an import cycle

    d = master_config_dir(_automas_dir(), "DailyTask.json")
    if d is None:
        out["OK-WW(母本)"] = "找不到母本目录（ARK_AUTOMAS_DIR 没设或结构变了）"
        return
    ok: dict = {}
    for f in OKWW_FILES:
        p = d / f
        if not p.exists():
            continue
        try:
            ok[f[:-5]] = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            ok[f[:-5]] = f"读不了: {exc}"
    out["OK-WW(母本·生效的)"] = ok


def _runtime(out: dict) -> None:
    try:
        q = subprocess.run(["sc", "query", "ark-relay"], capture_output=True,
                           text=True, errors="replace", timeout=15).stdout
        out["ark-relay"] = ("RUNNING" if "RUNNING" in q
                            else "STOPPED" if "STOPPED" in q else "?")
    except Exception:  # noqa: BLE001
        out["ark-relay"] = "?"
    try:
        tl = subprocess.run(["tasklist"], capture_output=True, text=True,
                            errors="replace", timeout=20).stdout
        # One list, in config.py. This one used to be blind to Wuthering Waves'
        # own process and to the emulator, so while the game was playing the
        # phone page's 「在跑的」 was empty - it reads as idle at a glance.
        from .config import BUSY_PROCS, ORCHESTRATOR_PROC  # noqa: PLC0415
        names = (ORCHESTRATOR_PROC,) + BUSY_PROCS
        out["进程"] = {n[:-4] if n.endswith(".exe") else n: n in tl for n in names}
    except Exception:  # noqa: BLE001
        pass


def read() -> dict:
    """Read one full snapshot. A section that fails records an error; the rest is unaffected."""
    out: dict = {}
    for label, fn in (("_MAS错误", _mas), ("_队列错误", _queues),
                      ("_OKWW错误", _okww), ("_运行时错误", _runtime)):
        try:
            fn(out)
        except Exception as exc:
            out[label] = f"{type(exc).__name__}: {exc}"
            log.warning("快照的 %s 这一段读不到", label, exc_info=True)
    return out
