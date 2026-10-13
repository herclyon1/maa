"""What the installer and switch.py tell him matches what they did.

2026-10-13 (audit of the install / switch-over block, item 1): since e1033fb1 a failed
switch-over switches the same new relay on again (there is no old relay any more: its
service was deleted 2026-10-11 22:33), but the installer's message box still said
「已经退回老中继继续跑」 and switch.log said "reverting to the old relay". These checks
read the installer script and switch.py as text: no message may promise the old relay,
and the failed-install box names the way back that exists (launch.py rollback).
"""
import re
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


iss = (ROOT / "packaging" / "ark-relay.iss").read_text(encoding="utf-8-sig")
code = iss.split("[Code]", 1)[1]
switch_src = (ROOT / "packaging" / "switch.py").read_text(encoding="utf-8")


def proc(name: str) -> str:
    m = re.search(rf"\n(?:procedure|function) {name}\b.*?\nend;", code, re.S)
    return m.group(0) if m else ""


def boxes(body: str) -> "list[str]":
    """The text of each MsgBox in `body`, its string pieces joined."""
    out = []
    for m in re.finditer(r"MsgBox\((.*?),\s*mb\w+,", body, re.S):
        out.append("".join(re.findall(r"'([^']*)'", m.group(1))))
    return out


print("[a failed switch-over: the box says what happened]")
step = proc("CurStepChanged")
texts = boxes(step)
check("CurStepChanged has message boxes", len(texts) >= 1, True)
check("no box says the old relay took over", [t for t in texts if "退回老中继" in t], [])
failed_box = next((t for t in texts if "新中继没有装好" in t), "")
check("the failed-switch box says the new relay was switched on again",
      "重新打开" in failed_box, True)
check("the failed-switch box names launch.py rollback",
      "launch.py" in failed_box and "rollback" in failed_box, True)
check("the failed-switch box points at switch.log", "switch.log" in failed_box, True)

print("[switch.py's own lines say the same]")
for phrase in ("reverting to the old relay", "the old relay back on", "退回老中继"):
    check(f"switch.py no longer prints {phrase!r}", phrase in switch_src.split('"""', 2)[2], False)
check("no function named after going back to the old relay",
      "_back_to_old" in switch_src, False)
check("the docstring no longer promises 'the new one or the old one'",
      "the new one or the old one" in switch_src, False)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
