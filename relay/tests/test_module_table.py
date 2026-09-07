"""relay/README.md 的模块表要覆盖 ark_relay 下每一个模块。

2026-09-08 审出来：47 个模块里表上只有 16 个，而且把 shutdown/report/missed 说成
还在 engine.py 里——按它找代码会找错地方。表和文件分头长，早晚对不上。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
doc = (ROOT / "README.md").read_text(encoding="utf-8")
mods = {p.stem for p in (ROOT / "ark_relay").glob("*.py")
        if p.stem != "__init__"} | {"service"}

listed = set(re.findall(r"`(\w+)\.py`", doc))
missing = sorted(mods - listed)
extra = sorted(n for n in listed - mods if n not in ("run", "make-manifest"))

fails = []
print(f"  模块 {len(mods)} 个，表里提到 {len(listed & mods)} 个")
if missing:
    fails.append(f"表里没提到：{missing}")
    print(f"  ✗ 表里没提到：{missing}")
if extra:
    fails.append(f"表里提到了不存在的：{extra}")
    print(f"  ✗ 表里提到了不存在的：{extra}")

# 拆出去的四块不许还写成在 engine 里
for name in ("shutdown", "report", "missed", "handle"):
    if re.search(rf"engine\.py[^|\n]*{name}", doc):
        fails.append(f"{name} 已经从 engine 拆出来了，表里还说在 engine 里")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
