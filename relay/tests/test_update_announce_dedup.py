"""The same change deployed twice must not be pushed twice.

A deploy refused by a gate, fixed, and deployed again is two versions but one
change. On 2026-09-09 the user got the same paragraph twice inside five minutes
and asked why. The version number differs every time, so it cannot be the test;
what he reads is the release notes, so those are what gets compared.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.statestore import StateStore
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


root = tmpdir()
(root / "state").mkdir()
st = StateStore(root / "state")

print("[「上一条推送的说明」是个正经登记字段，写得进也读得回]")
check("一开始是空的", st.get("versions", "announced_notes"), None)
st.set("versions", "announced_notes", "- 改了甲\n- 改了乙")
check("换个实例读得回", StateStore(root / "state").get("versions", "announced_notes"),
      "- 改了甲\n- 改了乙")

print("\n[判据就是原文相等：一样不推，改一个字就推]")
last = StateStore(root / "state").get("versions", "announced_notes")
check("一模一样 → 不推", "- 改了甲\n- 改了乙" == last, True)
check("多一行 → 推", "- 改了甲\n- 改了乙\n- 改了丙" == last, False)
check("空说明不参与比较（回退到列文件名那条路）", bool("") and "" == last, False)

print("\n[开机那一段真的用了这个字段，而不是只登记不看]")
boot = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
check("读了它", 'get("versions", "announced_notes")' in boot, True)
check("推成功之后才写", 'set("versions", "announced_notes", notes)' in boot, True)
check("跳过时仍然记下版本号，免得下次又当成新的",
      "_remember_announced(HERE, int(note.get(\"version\") or 0))" in boot, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
