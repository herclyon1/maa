import difflib, json, os, pathlib, sys
root = pathlib.Path(r"C:\ProgramData\ark-relay"); sys.path.insert(0, str(root)); sys.path.insert(0, str(root/"lib"))
for line in (root / ".env").read_text(encoding="utf-8").splitlines():
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(), v.strip())
from ark_relay import weeklyboss as W  # noqa: E402
ok = lambda b: "✅" if b else "❌"  # noqa: E731
A = os.environ.get("ARK_AUTOMAS_DIR")

# Section 1 compared the master with OK-WW's own working/configs copy until the
# copy helper was removed (7425eff4, 2026-09-08): AutoProxy copies the master over
# that directory wholesale before every run and restores it afterwards, so the copy
# never counts (config.master_config_dir). What OK-WW reads is the master; what it
# actually did is in the last run log.
print("=== 1. Weekly boss config: the master (what OK-WW reads) and the last run ===")
for name in (W.DAILY, W.FARM):
    f = W._file(A, name)
    if f is None or not f.is_file():
        print(f"  ❌ {name}: master file not found (ARK_AUTOMAS_DIR={A!r})")
        continue
    m = json.loads(f.read_text(encoding="utf-8"))
    keys = [W.KEY] if name == W.DAILY else ["Teleport to Boss","Boss Level","Which Weekly Boss to Teleport","Repeat Farm Count"]
    for k in keys:
        print(f"  {ok(k in m)} {name} · {k}: {m.get(k)!r}")
print(f"  last run log, weekly boss name: {W.name_from_log()!r}")

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
