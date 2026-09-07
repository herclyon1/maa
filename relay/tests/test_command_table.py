"""relay/README.md 的命令表必须和代码里的白名单一一对上。

2026-09-08 审出来的：表里说 `run_now` 是「没实现、会明确拒绝」，代码里它真会调
`/api/dispatch/start` 派发一趟队列；`skip_shutdown`、`weekly_boss`、`set_config`、
`set_master` 四个命令干脆不在表里——其中 skip_shutdown 就是「吃掉下一次关机机会
且不带时效」的那个开关，已经让机器白开两夜，而唯一一张说明表里找不到它。

文档和代码分头维护，早晚会分家。这条测试让它们分不了家。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
code = (ROOT / "ark_relay" / "commands.py").read_text(encoding="utf-8")
doc = (ROOT / "README.md").read_text(encoding="utf-8")

allowed = set()
for m in re.finditer(r"^(REVERSIBLE|MUTATING) = \{([^}]*)\}", code, re.M | re.S):
    allowed |= {x.strip().strip('"') for x in m.group(2).split(",") if x.strip()}
listed = set(re.findall(r"^\| `(\w+)` \|", doc, re.M))

fails = []
if not allowed:
    fails.append("没从 commands.py 里读出白名单——正则该跟着代码改")
missing = sorted(allowed - listed)
extra = sorted(listed - allowed)
if missing:
    fails.append(f"命令表漏了：{missing}（代码认，文档没写）")
if extra:
    fails.append(f"命令表多了：{extra}（文档写了，代码不认）")

print(f"  代码白名单 {len(allowed)} 个，文档表 {len(listed)} 个")
for f in fails:
    print(f"  ✗ {f}")
print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
