"""通知文案的闸门：标题只能来自 texts.py，文案必须是人话、不模糊。

用户 2026-09-07：「你写进通知的任何东西都要是人话」「描述模糊是第一大禁止」。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_relay import texts, core, collector, garden, annihilation, weeklyboss  # noqa: E402

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
for table in (core._KIND_NOTE.values(), collector._OKWW_TASK_ZH.values(),
              collector._OKWW_EXC_ZH.values(), (zh for _, zh in collector._OKWW_MSG_ZH),
              (garden.GardenGate.NAME, annihilation.WeeklyGate.NAME, weeklyboss.WeeklyBossGate.NAME)):
    for s in table:
        check(s[:40], texts.plain(s), [])

print("[代码里不许再出现写死的通知标题]")
bad = []
pat = re.compile(r"notifier\.send(?:_group)?\(\s*f?\"")
for f in list((ROOT / "ark_relay").glob("*.py")) + [ROOT / "service.py"]:
    if f.name == "texts.py":
        continue
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if pat.search(line) and not line.strip().startswith("#"):
            bad.append(f"{f.name}:{i}: {line.strip()[:80]}")
check("写死的标题为零", bad, [])
# 地板：glob 扫到 0 个文件也会「零违规」，闸门成摆设。2026-09-08 回放测试栽过一次。
_scanned = len(list((ROOT / "ark_relay").glob("*.py"))) + 1
check("确实扫到了文件（至少 20 个）", _scanned >= 20, True)

print("[plain() 本身认得出问题]")
check("英文类名", texts.plain("FarmEchoTask 抛 WaitFailedException"), ["英文「FarmEchoTask」", "英文「WaitFailedException」"])
check("模糊词", texts.plain("周本：这一步出错"), ["模糊词「这一步」", "模糊词「出错」"])
check("产品名放行", texts.plain("MaaEnd 已更新：v2.28.0-beta.1 → v2.28.0-beta.2"), [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
