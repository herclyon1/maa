"""A machine still carrying the old stamina patches must be put back to upstream.

Those two changes moved into ok_tasks/ark_overrides.py on 2026-09-09. What matters now
is the other direction: whatever shape they are in on disk - v1, v1 with the no-farm
switch rewritten inside it, or the version that shipped last - boot has to restore
upstream's own text and then leave the file alone.

Leaving them applied was not harmless. The old applier kept re-applying them every
boot while the new revert undid them, so every restart pushed a three-line 「补丁」
notification to the phone. 「这个通知一直在轰炸我」.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ark_relay.okww_patch as P
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


PRISTINE = P._DAILY_RUN_PRISTINE


def tree(daily_body: str):
    root = tmpdir()
    d = root.joinpath(*P._SRC)
    d.mkdir(parents=True)
    (d / "DailyTask.py").write_text(
        "class DailyTask:\n" + daily_body, encoding="utf-8")
    return root, d / "DailyTask.py"


SHAPES = {
    "上一版（v2 + 不刷体力）": P._DAILY_RUN_PATCHED,
    "v1": PRISTINE.replace(P._STAMINA_OLD, P._STAMINA_V1, 1),
    "v1 加上不刷体力开关": PRISTINE.replace(
        P._STAMINA_OLD, P._STAMINA_V1.replace(P._NOFARM_OLD, P._NOFARM_NEW), 1),
}

print("[机器上不管是哪一种旧形态，开机都要还原成上游原样]")
for name, body in SHAPES.items():
    root, f = tree(body)
    notes = P.ensure_patches(root)
    check(f"{name}：还原了", f.read_text(encoding="utf-8"), "class DailyTask:\n" + PRISTINE)
    check(f"{name}：说了一句", bool(notes))

print("[已经是上游原样就一声不吭——每次开机都推通知就是轰炸]")
root, f = tree(PRISTINE)
check("第一次就没什么可做", P.ensure_patches(root), [])
check("第二次也一样", P.ensure_patches(root), [])
check("文件没被动过", f.read_text(encoding="utf-8"), "class DailyTask:\n" + PRISTINE)

print("[不许再有人在开机时把它们贴回去]")
check("清单里一条都不贴", P.active_patches(), [])
src = Path(P.__file__).read_text(encoding="utf-8")
check("旧的 _ensure_stamina 已经删干净", "_ensure_stamina" in src, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
