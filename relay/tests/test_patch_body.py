"""Editing a patch's text must not silently do nothing on the machine.

present() is a probe, not a comparison with the current text. Several of them only
check an ordering or a log line, so changing the patch body leaves them saying
「already in place」 and the file is never touched. Measured on 2026-09-08: change
ensure_main(time_out=180) to 600 inside _STAMINA_NEW, re-apply, and the answer is
an empty list while the file still holds 180. Nothing downstream can see that -
the deploy gate greps this very list, and an empty list reads as success. The fix
for a morning failure would be written, deployed, reported as 「✅ 部署完成」, and
the machine would keep running the old code.

Two things are pinned:

* `_apply_one` speaks up when the probe says yes but the file holds neither the
  upstream text nor the text we now want.
* The one patch that has to opt out of that check is exactly the one another patch
  rewrites part of. That set is computed here, not remembered.
"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import okww_patch as P
from ark_relay.okww_patches.core import _apply_one
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


NAMES = ("_STAMINA", "_NOFARM", "_CLAIM", "_TACETSHOT", "_NOWAVE",
         "_RETRYCAP", "_LETPASS", "_COUNT")
PATCHES = [(n, getattr(P, n)) for n in NAMES if hasattr(P, n)]

print("[谁的正文会被别的补丁改写——这个集合是算出来的，不是记住的]")
overlapped = set()
for (an, a), (bn, b) in itertools.permutations(PATCHES, 2):
    if a.parts == b.parts and b.old and b.old in a.new:
        overlapped.add(an)
check("算出来的集合", overlapped, {"_STAMINA"})
opted_out = {n for n, p in PATCHES if not p.body_check}
check("关掉正文核对的正好是这些", opted_out, overlapped)

print("\n[改了正文却贴不上去时，必须出声——而不是返回空]")
# The host file has to compile: applying a patch compiles the result and
# reverts the whole thing if it does not.
HOST = ("class T:\n"
        "    def run(self):\n"
        "        for _ in range(1):\n"
        "            if True:\n"
        "                while True:\n"
        + P._CLAIM.old + "\n"
        "                    break\n")
root = tmpdir()
f = root.joinpath(*P._CLAIM.parts)
f.parent.mkdir(parents=True, exist_ok=True)
f.write_text(HOST, encoding="utf-8")
first = _apply_one(root, P._CLAIM)
check("第一次贴上了", bool(first), True)
check("盘上是新正文", P._CLAIM.new in f.read_text(encoding="utf-8"), True)
check("再贴一次安静返回空", _apply_one(root, P._CLAIM), [])

import dataclasses                                                  # noqa: E402
edited = dataclasses.replace(P._CLAIM, new=P._CLAIM.new + "\n        # 又改了一版\n")
said = _apply_one(root, edited)
check("正文变了就必须出声", len(said), 1)
check("话里说得出是写不进去", "写不进去" in said[0], True)
check("话里点名是哪条补丁", P._CLAIM.name in said[0], True)

print("\n[部署那道闸认得这句话——不然出声了也没人听见]")
gate = (Path(__file__).resolve().parents[2] / "scripts" / "mac" / "deploy-relay.sh"
        ).read_text(encoding="utf-8")
check("闸门的关键词抓得住这句话", "写不进" in gate, True)

print("\n[关掉核对的那条，正文变了也照旧安静——这是有意的，别误报]")
check("_STAMINA 不做正文核对", P._STAMINA.body_check, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
