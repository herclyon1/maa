#!/usr/bin/env python3
"""把游戏机上**真实生效**的配置一次性读回来。

    scripts/mac/config-check.py              # 打印当前全部关键配置
    scripts/mac/config-check.py --save       # 存快照
    scripts/mac/config-check.py --diff       # 和上次快照比，只显示变了的

存在的唯一理由：**防止我说「已经设好了」而其实没设。**

2026-08-26 至少两次栽在这上面：
  * 说 OK-WW 的梦魇净化「三令五申检查通过」——配置文件从 08-24 起就没被写过；
  * 说改了 MAA 的关卡序号并「回读确认」——回读的是「值存进去了」，
    而不是「这个值是不是我以为的那个关卡」。

用户的原话是：「你不是不会干活，你是有幻觉，以为自己干了但没有。」

**规矩：任何关于配置的断言，先跑这个，把它的输出贴出来，再说结论。**
不许凭印象、不许凭「我刚才改过」。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HOST = "100.65.39.119"
HERE = Path(__file__).resolve().parent
SNAP = HERE.parent.parent / "relay" / "state" / "config-snapshot.json"

# 远端读取脚本。只输出 JSON，中文走 winrun 的字节通道，不经过 936 控制台。
PROBE = r'''
import json, io, urllib.request
from pathlib import Path

API = "http://127.0.0.1:36163"
def post(p, b=None):
    r = urllib.request.Request(API + p, data=json.dumps(b or {}).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=15) as x:
        return json.loads(x.read().decode())

out = {}

# ---- AUTO-MAS 侧 ----
try:
    scripts = post("/api/scripts/get")["data"]
    for uid, sc in scripts.items():
        name = sc.get("Info", {}).get("Name") or sc.get("Info", {}).get("RootPath", uid)
        try:
            users = post("/api/scripts/user/get", {"scriptId": uid}).get("data") or {}
        except Exception:
            users = {}
        for _, u in users.items():
            if name == "MAA":
                i, t = u.get("Info", {}), u.get("Task", {})
                out["MAA"] = {
                    "关卡": i.get("Stage"), "关卡链": [i.get(f"Stage_{n}") for n in (1, 2, 3)],
                    "理智药": i.get("MedicineNumb"), "连战": i.get("SeriesNumb"),
                    "关卡模式": i.get("StageMode"), "剿灭": i.get("Annihilation"),
                    "活动关优先": t.get("IfActivityFirst"),
                    "活动关序号": t.get("ActivityStageIndex"),
                    "活动关理智药": t.get("ActivityMedicineNumb"),
                    "作战开关": t.get("IfFight"),
                }
            elif name == "MaaEnd":
                t = u.get("Task", {})
                st = t.get("SanityTaskType")
                out["MaaEnd"] = {
                    "理智任务": st, "详细": t.get(st) if st else None,
                    "开理智": t.get("IfSanity"),
                    "自动吃药": t.get("IfAutoUseSpMedication"),
                    "基质地点": t.get("AutoEssenceSpecifiedLocation"),
                }
            elif "OK-WW" in str(name) or "ok-ww" in str(name):
                out["OK-WW(MAS侧)"] = u.get("Task", {})
except Exception as exc:
    out["_MAS错误"] = f"{type(exc).__name__}: {exc}"

# ---- 队列 ----
try:
    out["队列"] = {c["Info"]["Name"]: {"定时": c["Info"]["TimeEnabled"],
                                       "开机跑": c["Info"]["StartUpEnabled"]}
                   for c in post("/api/queue/get")["data"].values()}
except Exception as exc:
    out["_队列错误"] = f"{type(exc).__name__}: {exc}"

# ---- OK-WW 自己的配置（MAS 管不到，只能读文件）----
okcfg = Path(r"D:\ark\okww\data\apps\ok-ww\working\configs")
ok = {}
for f in ("NightmareNestTask.json", "DailyTask.json", "TacetTask.json",
          "ForgeryTask.json"):
    p = okcfg / f
    if p.exists():
        try:
            ok[f[:-5]] = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            ok[f[:-5]] = f"读不了: {exc}"
out["OK-WW(本体)"] = ok

# ---- 服务与进程 ----
import subprocess as sp
try:
    q = sp.run(["sc", "query", "ark-relay"], capture_output=True, text=True,
               errors="replace").stdout
    out["ark-relay"] = "RUNNING" if "RUNNING" in q else ("STOPPED" if "STOPPED" in q else "?")
except Exception:
    out["ark-relay"] = "?"
try:
    tl = sp.run(["tasklist"], capture_output=True, text=True, errors="replace").stdout
    out["进程"] = {n: (n + ".exe") in tl
                   for n in ("AUTO-MAS", "MAA", "MaaEnd", "Endfield", "ok-ww")}
except Exception:
    pass

print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
'''


def fetch() -> dict:
    tmp = Path("/tmp/ark-config-probe.py")
    tmp.write_text(PROBE, encoding="utf-8")
    r = subprocess.run([str(HERE / "winrun.sh"), "--py", str(tmp)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"✗ 读不回配置（winrun 退出码 {r.returncode}）\n{r.stderr.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"✗ 远端返回的不是 JSON：\n{r.stdout[:600]}")


def flatten(d, pre=""):
    for k, v in sorted(d.items()):
        key = f"{pre}.{k}" if pre else k
        if isinstance(v, dict):
            yield from flatten(v, key)
        else:
            yield key, v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", action="store_true", help="存为快照")
    ap.add_argument("--diff", action="store_true", help="与快照比对，只列变化")
    a = ap.parse_args()

    cur = fetch()
    if a.diff:
        if not SNAP.exists():
            sys.exit("✗ 还没有快照，先跑一次 --save")
        old = json.loads(SNAP.read_text(encoding="utf-8"))
        o, c = dict(flatten(old)), dict(flatten(cur))
        changed = [(k, o.get(k, "（原本没有）"), c[k])
                   for k in sorted(set(o) | set(c)) if o.get(k) != c.get(k)]
        if not changed:
            print("✅ 和快照完全一致，没有任何变化")
            return 0
        print(f"⚠️  有 {len(changed)} 项和快照不同：")
        for k, ov, nv in changed:
            print(f"  {k}\n      快照: {ov!r}\n      现在: {nv!r}")
        return 0

    print(json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=True))
    if a.save:
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(cur, ensure_ascii=False, indent=1,
                                   sort_keys=True), encoding="utf-8")
        print(f"\n快照已存: {SNAP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
