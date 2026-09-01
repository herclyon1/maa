import difflib, json, os, pathlib, sys
root = pathlib.Path(r"C:\ProgramData\ark-relay"); sys.path.insert(0, str(root)); sys.path.insert(0, str(root/"lib"))
for line in (root / ".env").read_text(encoding="utf-8").splitlines():
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(), v.strip())
from ark_relay import weeklyboss as W
ok = lambda b: "✅" if b else "❌"
A = os.environ.get("ARK_AUTOMAS_DIR")

print("=== 1. 周本配置：母本 vs OK-WW 自己那份 ===")
for name in (W.DAILY, W.FARM):
    m = json.loads(W._file(A, name).read_text(encoding="utf-8"))
    o = json.loads(W._okww_file(name).read_text(encoding="utf-8"))
    keys = [W.KEY] if name == W.DAILY else ["Teleport to Boss","Boss Level","Which Weekly Boss to Teleport","Repeat Farm Count"]
    for k in keys:
        same = m.get(k) == o.get(k)
        print(f"  {ok(same)} {name} · {k}: 母本={m.get(k)!r} 副本={o.get(k)!r}")

print("\n=== 2. 补丁：与上游原始文件比对 ===")
for f, want in (("FarmEchoTask.py", 4), ("DailyTask.py", None), ("NightmareNestTask.py", None)):
    w = pathlib.Path(rf"D:\ark\okww\data\apps\ok-ww\working\src\task\{f}")
    r = pathlib.Path(rf"D:\ark\okww\data\apps\ok-ww\repo\src\task\{f}")
    if not (w.exists() and r.exists()): print(f"  ?? {f} 少一份"); continue
    ops = [o for o in difflib.SequenceMatcher(None, r.read_text(encoding='utf-8').splitlines(),
           w.read_text(encoding='utf-8').splitlines()).get_opcodes() if o[0] != "equal"]
    tag = ok(want is None or len(ops) == want)
    print(f"  {tag} {f}: {len(ops)} 处改动" + (f"（应 {want}）" if want else ""))

print("\n=== 3. 周本门状态 ===")
print("  ", W.WeeklyBossGate(root/"state", A).settings(), "｜游戏报的剩余次数:", W.remaining_from_log())
print("\n=== 4. 刷体力 ===")
print("  禁用标记:", (root/"state"/"no-stamina-farm.flag").exists(), "（False＝已恢复刷体力）")
