"""The 「今晚不关机」 message must never go out when the machine is in fact shutting down.

At 22:46 on 2026-09-09 the command had already been sent, and the push still read
「到点了但没关机：关机令已经下过了。机器会一直开着」 - then the machine shut down.
The verdict code for "the command has gone out" was listed among the reasons a machine
stays awake, and its wording read as though someone had ordered it to stay on.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import shutdown

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


src = Path(shutdown.__file__).read_text(encoding="utf-8")

print("[关机命令已经发出去，就不是「没关机」]")
check("issued 不在「该关没关」那一类里", '"issued"' in shutdown._STUCK_CODES, False)
verdict = re.search(r'Verdict\(False, "issued", "([^"]+)"\)', src)
check("找得到那句话", bool(verdict))
check("不再像「有人下令别关」", "已经下过了" in (verdict.group(1) if verdict else ""), False)
check("改成说清是正在关", "机器正在关" in src)

print("[真正会让机器一直开着的，才值得每天报一次]")
for code in ("running", "pending", "updating", "manual", "unfinished", "farming"):
    check(f"{code} 在名单里", code in shutdown._STUCK_CODES)

print("[刷声骸那条要说清刷到几点，不能只说「在刷」]")
check("理由里带收工时刻", "才收工" in src)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
