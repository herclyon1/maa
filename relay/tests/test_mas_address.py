"""AUTO-MAS 的地址只有一处出处，而且 ARK_MAS_PORT 真的管得住全部。

2026-09-08 审出来：地址在 relay 里有 4 份（commands / snapshot / engine 各自写死
36163，只有预更新那份读 ARK_MAS_PORT），改端口只有四分之一生效——而「四分之一生效」
比「完全不生效」难查得多。

还有一条：出处**必须是函数**。config.py 顶部那段注释写着，模块级读 os.environ 会在
.env 加载之前求值，做成常量等于让这个变量「设了也不生效」。
"""
import ast
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

print("[地址只有一处出处]")
hard = []
for p in sorted((ROOT / "ark_relay").glob("*.py")):
    if p.name == "config.py":
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if re.search(r"127\.0\.0\.1:\s*\{?36163|:36163", line):
            hard.append(f"{p.name}:{i}")
check("别处不许再写死", hard, [])

print("[出处是函数，不是模块级常量]")
cfg = ast.parse((ROOT / "ark_relay" / "config.py").read_text(encoding="utf-8"))
names = {n.name for n in cfg.body if isinstance(n, ast.FunctionDef)}
check("config.mas_base 存在且是函数", "mas_base" in names, True)
consts = [t.id for n in cfg.body if isinstance(n, ast.Assign)
          for t in n.targets if isinstance(t, ast.Name)]
check("没有模块级的地址常量", [c for c in consts if "MAS" in c.upper()], [])

print("[ARK_MAS_PORT 真的管用]")
from ark_relay.config import mas_base  # noqa: E402
old = os.environ.get("ARK_MAS_PORT")
try:
    os.environ["ARK_MAS_PORT"] = "39999"
    check("改端口立刻生效", mas_base(), "http://127.0.0.1:39999")
    del os.environ["ARK_MAS_PORT"]
    check("不设时回落到 36163", mas_base(), "http://127.0.0.1:36163")
finally:
    if old is None:
        os.environ.pop("ARK_MAS_PORT", None)
    else:
        os.environ["ARK_MAS_PORT"] = old

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
