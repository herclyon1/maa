"""机器上**真实生效**的配置，一处读、两处用。

用户 2026-08-31：「手机上的所有状态必须和机器保持一致，否则你动了配置
不同步到我这边会造成麻烦。」

所以手机看到的东西和 `scripts/mac/config-check.py` 看到的必须是**同一份
代码读出来的**——两份各写一遍，早晚会各说各话，而「界面显示的和机器上
真实的不一样」正是 826 那类事故的温床。config-check 现在也调这里。

数据从 AUTO-MAS 自己的后端 API 拿，不读它的配置文件：后端在跑的时候会用
内存里那份覆写文件，读文件会读到一个「马上就要被冲掉」的值。
OK-WW 自己的配置 AUTO-MAS 管不到，只能读文件。
"""
from __future__ import annotations

import json
import logging
import subprocess
import urllib.request
from pathlib import Path

log = logging.getLogger("ark.snapshot")

API = "http://127.0.0.1:36163"
OKWW_CONFIGS = Path(r"D:\ark\okww\data\apps\ok-ww\working\configs")
OKWW_FILES = ("NightmareNestTask.json", "DailyTask.json",
              "TacetTask.json", "ForgeryTask.json")


def _post(path: str, body: "dict | None" = None, timeout: int = 15) -> dict:
    # AUTO-MAS 的**每个**端点都是 POST，包括读取用的那些。GET 会返回
    # Method Not Allowed——2026-08-26 在这上面花过时间。
    req = urllib.request.Request(
        API + path, data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
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
    # 用 .get：不同版本的 AUTO-MAS 字段不一样，2026-08-31 就因为
    # 直接下标 StartUpEnabled 抛了 KeyError，整段队列信息一条都拿不到。
    out["队列"] = {
        str((c.get("Info") or {}).get("Name") or "?"): {
            "定时": (c.get("Info") or {}).get("TimeEnabled"),
            "开机跑": (c.get("Info") or {}).get("StartUpEnabled"),
        }
        for c in _post("/api/queue/get")["data"].values()}


def _okww(out: dict) -> None:
    ok: dict = {}
    for f in OKWW_FILES:
        p = OKWW_CONFIGS / f
        if not p.exists():
            continue
        try:
            ok[f[:-5]] = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            ok[f[:-5]] = f"读不了: {exc}"
    out["OK-WW(本体)"] = ok


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
        out["进程"] = {n: (n + ".exe") in tl
                       for n in ("AUTO-MAS", "MAA", "MaaEnd", "Endfield", "ok-ww")}
    except Exception:  # noqa: BLE001
        pass


def read() -> dict:
    """读一份完整快照。任何一段取不到就记一条错，不影响其余。"""
    out: dict = {}
    for label, fn in (("_MAS错误", _mas), ("_队列错误", _queues),
                      ("_OKWW错误", _okww), ("_运行时错误", _runtime)):
        try:
            fn(out)
        except Exception as exc:  # noqa: BLE001
            out[label] = f"{type(exc).__name__}: {exc}"
            log.warning("快照的 %s 这一段读不到", label, exc_info=True)
    return out
