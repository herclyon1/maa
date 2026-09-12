"""通知文案的闸门：标题只能来自 texts.py，文案必须是人话、不模糊。

用户 2026-09-07：「你写进通知的任何东西都要是人话」「描述模糊是第一大禁止」。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_relay import texts, core, collector_okww, garden, annihilation, weeklyboss  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)

print("[texts.py 里每一句都是人话]")
for s in texts.samples():
    check(s[:40], texts.plain(s), [])

print("[各处中文对照表也是人话]")
for table in (core._KIND_NOTE.values(), collector_okww._OKWW_TASK_ZH.values(),
              collector_okww._OKWW_EXC_ZH.values(), (zh for _, zh in collector_okww._OKWW_MSG_ZH),
              (garden.GardenGate.NAME, annihilation.WeeklyGate.NAME, weeklyboss.WeeklyBossGate.NAME)):
    for s in table:
        check(s[:40], texts.plain(s), [])

print("[每个模块里所有会送到人眼前的中文句子都过 plain()：不只是 texts.py]")
# The user, 2026-09-12: 「你不是有工具在拦截吗，搞毛呢？」 - a hedged sentence sat in
# core.py, which this gate never read. Now every Chinese string literal in every
# module is checked, except log calls (they are for me) and docstrings.
import ast  # noqa: E402
_HAN = re.compile(r"[\u4e00-\u9fff]")
def _user_facing_literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("info", "warning", "error", "exception", "debug", "critical")):
            for c in ast.walk(n):
                skip.add(id(c))
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
            skip.add(id(n.value))          # docstrings
    for n in ast.walk(tree):
        if id(n) in skip or not isinstance(n, ast.Constant) or not isinstance(n.value, str):
            continue
        if _HAN.search(n.value):
            yield n.lineno, n.value
_HEDGE_ONLY = [v for v in texts.VAGUE if v not in ("未知错误", "这一步", "有问题", "出错")]
vague_hits = []
_scanned_literals = 0
for f in sorted((ROOT / "ark_relay").glob("*.py")) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
    if f.name == "summary.py":
        continue                            # the model prompt, abandoned path; not a notification
    for ln, val in _user_facing_literals(f):
        _scanned_literals += 1
        if f.name == "texts.py" and val in texts.VAGUE:
            continue                        # the word list itself
        for v in _HEDGE_ONLY:
            if v in val:
                vague_hits.append(f"{f.name}:{ln} 「{v}」 {val[:50]!r}")
check("没有一句含糊话（多半/可能/大概/疑似/约…）", vague_hits, [])
check("确实扫到了很多句子（至少 300）", _scanned_literals >= 300, True)

print("[代码里不许再出现写死的通知标题]")
bad = []
pat = re.compile(r"notifier\.send(?:_group)?\(\s*f?\"")
for f in list((ROOT / "ark_relay").glob("*.py")) + [ROOT / "service.py", ROOT / "boot_stages.py"]:
    if f.name == "texts.py":
        continue
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if pat.search(line) and not line.strip().startswith("#"):
            bad.append(f"{f.name}:{i}: {line.strip()[:80]}")
check("写死的标题为零", bad, [])
# 地板：glob 扫到 0 个文件也会「零违规」，闸门成摆设。2026-09-08 回放测试栽过一次。
_scanned = len(list((ROOT / "ark_relay").glob("*.py"))) + 2
check("确实扫到了文件（至少 20 个）", _scanned >= 20, True)

print("[plain() 本身认得出问题]")
check("英文类名", texts.plain("FarmEchoTask 抛 WaitFailedException"), ["英文「FarmEchoTask」", "英文「WaitFailedException」"])
check("模糊词", texts.plain("周本：这一步出错"), ["模糊词「这一步」", "模糊词「出错」"])
check("产品名放行", texts.plain("MaaEnd 已更新：v2.28.0-beta.1 → v2.28.0-beta.2"), [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
