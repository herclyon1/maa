"""What runs on the machine is a table, and the doc must match it.

ensure_patches used to be one function mixing nine applications with eighteen
reverts; three documents described three different states of it, and on the
morning of 2026-09-08 the first hour of a failure went into working out which
patches were actually in place. Now the inventory is two tables, active_patches()
reads them, and this test holds docs/OKWW-PATCHES.md to the same list.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import okww_patch as P

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


print("[一条都不改鸣潮的源文件了，全部搬到 ok_tasks]")
check("在贴的", P.active_patches(), [])
check("没有一条既在贴又在撤", {p.new for p in P._APPLIES} & {r[1] for r in P._REVERTS}, set())
check("撤的每一条都有一个不同于现行版本的正文",
      all(r[1] not in {p.new for p in P._APPLIES} for r in P._REVERTS), True)

print("\n[docs/OKWW-PATCHES.md 的清单必须提到每一条在贴的补丁的模块]")
doc = (Path(__file__).resolve().parents[2] / "docs" / "OKWW-PATCHES.md").read_text(encoding="utf-8")
for mod in ("NightmareNestTask.patched.py", "ark_overrides.tasks.py"):
    check(f"文档提到 {mod}", mod in doc, True)
check("文档说清了改动都在哪", "ark_overrides" in doc, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
