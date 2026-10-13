import difflib, json, os, pathlib
# winrun ships scripts/mac/lib/relay_code.py next to this script. root = the data folder
# (.env, state); the code is the installed relay's version folder.
from relay_code import DATA as root, use_relay_code
use_relay_code()
for line in (root / ".env").read_text(encoding="utf-8").splitlines():
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(), v.strip())
from ark_relay.features.weekly import weeklyboss as W  # noqa: E402
ok = lambda b: "✅" if b else "❌"  # noqa: E731
A = os.environ.get("ARK_AUTOMAS_DIR")

# Since 2026-09-09 nothing of ours edits an upstream file: the changes live in
# ok_tasks/ark_overrides.py (okww_overlay.py), so every upstream task file must be
# identical to OK-WW's own checkout - 0 changed spots, no exceptions.
UPSTREAM_TASKS = ("FarmEchoTask.py", "DailyTask.py", "NightmareNestTask.py")


def upstream_untouched(n_changes: int) -> bool:
    return n_changes == 0


def overlay_problems(installed: "str | None", want: str, report: dict) -> list:
    """What is wrong with the overlay itself, [] when it is in place and bound.

    The same check as scripts/mac/lib/healthcheck.py section 1: the installed
    ok_tasks/ark_overrides.py equals this relay's copy, and the report OK-WW
    wrote at its last start has no error, nothing skipped and something applied.
    """
    out = []
    if installed is None:
        out.append("ok_tasks/ark_overrides.py is not installed: none of the relay's changes are in")
    elif installed != want:
        out.append("the installed overlay differs from this relay's copy")
    if not report:
        out.append("no overlay report: OK-WW has not started since the install, binding unknown")
        return out
    if report.get("error"):
        out.append("the overlay reported an error: " + str(report["error"])[-200:])
    if report.get("skipped"):
        out.append("overrides not bound: " + "; ".join(str(x.get("what")) for x in report["skipped"]))
    if not report.get("applied"):
        out.append("the report lists nothing applied")
    return out

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

print("\n=== 2. Relay changes: overlay installed and bound, upstream files untouched ===")
from ark_relay.features.okww_patch import okww_overlay  # noqa: E402
_ov = okww_overlay.target(r"D:\ark\okww")
_bad = overlay_problems(_ov.read_text(encoding="utf-8") if _ov is not None and _ov.is_file() else None,
                        okww_overlay.source_text(), okww_overlay.last_report())
print(f"  {ok(not _bad)} overlay {_ov}" + ("" if not _bad else ": " + "; ".join(_bad)))
for f in UPSTREAM_TASKS:
    w = pathlib.Path(rf"D:\ark\okww\data\apps\ok-ww\working\src\task\{f}")
    r = pathlib.Path(rf"D:\ark\okww\data\apps\ok-ww\repo\src\task\{f}")
    if not (w.exists() and r.exists()): print(f"  ?? {f} 少一份"); continue
    ops = [o for o in difflib.SequenceMatcher(None, r.read_text(encoding='utf-8').splitlines(),
           w.read_text(encoding='utf-8').splitlines()).get_opcodes() if o[0] != "equal"]
    print(f"  {ok(upstream_untouched(len(ops)))} {f}: {len(ops)} changed spots (want 0)")

print("\n=== 3. 周本门状态 ===")
print("  ", W.WeeklyBossGate(root/"state", A).settings(), "｜游戏报的剩余次数:", W.remaining_from_log())
print("\n=== 4. 刷体力 ===")
# The one fixed path the OK-WW override obeys (ark_overrides.tasks.py NO_STAMINA_FLAG,
# relay config.NO_STAMINA_FARM_FLAG); built from the data folder it could disagree.
from ark_relay.core.config import NO_STAMINA_FARM_FLAG  # noqa: E402
print("  禁用标记:", pathlib.Path(NO_STAMINA_FARM_FLAG).exists(), "（False＝已恢复刷体力）")
