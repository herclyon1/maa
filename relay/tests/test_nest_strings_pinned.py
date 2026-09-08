"""The two nest sentences the relay reads are written by our own patch.

outcome.py and collector_okww.py decide whether the nests were farmed by looking
for two sentences in OK-WW's log (the "all full, skipping" one and the "spot not
found in the list" one). Both are printed by relay/ark_relay/okww_files/NightmareNestTask.patched.py - our file, not
upstream's. Nothing tied the two sides together: change a character in the patch
and 99 tests stay green while the daily report starts saying, every day, that the
nests were opened and never fought. That patch is due to shrink once upstream
PR #1657 lands, which is exactly when this would have gone quiet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector_okww, outcome

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


patched = (Path(__file__).resolve().parents[1] / "ark_relay" / "okww_files"
           / "NightmareNestTask.patched.py").read_text(encoding="utf-8")

print("[读的那两句话，写的一侧必须还在补丁源码里]")
check("「已打满」在补丁里", outcome._NEST_ALL_FULL in patched, True)
check("「没找到点位」在补丁里", outcome._NEST_NOT_FOUND in patched, True)
check("collector 那份正则也匹配补丁里的句子",
      bool(collector_okww._OKWW_NEST_FULL.search(patched)), True)

print("\n[两个读的模块用的是同一句话，不许各写一份]")
check("outcome 与 collector 一致",
      bool(collector_okww._OKWW_NEST_FULL.search(outcome._NEST_ALL_FULL)), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
