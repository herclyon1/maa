"""The copied methods in the overlay must equal upstream's own plus our patches.

Four of our changes sit in the middle of long methods, so the overlay carries a copy
of the whole method. A copy is the one thing here that can go stale silently: edit it
by hand and it stops matching what `okww_patches/` says we do, and nobody notices.

So the copies are checked against their recipe: take the pristine method (the fixture
below is the exact text `inspect.getsource` returns on the machine, from OK-WW's own
repo/ copy), apply the patches that belong in it, and the result must be what the
overlay actually ships, character for character. The pinned hashes are checked too:
a wrong one means the override refuses to bind on the machine and the change silently
does not happen.
"""
import json
import hashlib
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import okww_overlay, okww_patch as P

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


PRISTINE = json.loads((Path(__file__).parent / "fixtures" / "okww-pristine-methods.json")
                      .read_text(encoding="utf-8"))

RECIPE = {
    "FarmEchoTask.py:run": ("farm_run", [P._RETRYCAP]),
    "FarmEchoTask.py:do_run": ("farm_do_run", [P._CLAIM, P._REVIVELOOP]),
    "FarmEchoTask.py:teleport_to_configured_boss": ("farm_teleport", [P._COUNT, P._NOWAVE]),
    "TacetTask.py:farm_tacet": ("tacet_farm", [P._TACETSHOT]),
}

src = okww_overlay.source_text()


def code_only(text: str) -> str:
    """Drop whole-line comments. The copies carry code, never the reasoning: that
    lives once, in okww_patches/, so it cannot drift into two versions."""
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))


def shipped(fn_name: str) -> str:
    """The function the overlay actually ships, by name."""
    lines = src.splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if l.startswith(f"def {fn_name}("))
    end = start + 1
    while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
        end += 1
    return "".join(lines[start:end]).rstrip("\n")


print("[每一份抄过来的正文 = 上游原文 + 我们登记在案的补丁]")
for key, (fn_name, patches) in RECIPE.items():
    want = PRISTINE[key]["source"]
    for p in patches:
        check(f"{key}：「{p.name}」的锚点在上游原文里", p.old in want)
        want = want.replace(p.old, p.new, 1)
    want = textwrap.dedent(code_only(want)).rstrip("\n")
    want = want.replace(f"def {key.split(':')[1]}(", f"def {fn_name}(", 1)
    check(f"{key}：抄的和配方一字不差", code_only(shipped(fn_name)).rstrip("\n"), want)

print("[钉住的指纹必须是上游原文的指纹，不是我们改完之后的]")
for key, (fn_name, _) in RECIPE.items():
    want_sha = hashlib.sha1(PRISTINE[key]["source"].encode("utf-8")).hexdigest()[:12]
    m = re.search(rf'expect_sha="([0-9a-f]+)"\)\({fn_name}\)', src)
    check(f"{key}：钉了指纹", bool(m))
    if m:
        check(f"{key}：指纹对得上（{want_sha}）", m.group(1), want_sha)

print("[整段替换的一律要钉指纹；包一层的不用钉，但必须真的调用上游那份]")
# The two shapes must not be confused. A copy runs instead of upstream and needs the
# pin. A wrapper runs upstream inside it, which is why it needs no pin - and why it
# has to actually call the original it captured, or it is a copy pretending not to be.
copies = {fn for fn, _ in RECIPE.values()} | {"revive_action"}
for name in copies:
    m = re.search(rf'override\([^)]*?"{name}"[^)]*expect_sha=', src) or \
        re.search(rf'expect_sha="[0-9a-f]+"\)\({name}\)', src)
    check(f"{name} 钉了指纹", bool(m))

for captured, wrapped in (("inner", "click_on_book_target"),
                          ("outer", "teleport_to_configured_boss"),
                          ("prepare", "teleport_to_configured_boss_and_prepare")):
    block = src.split(f'@override(FarmEchoTask, "{wrapped}")')[-1] \
        if f'@override(FarmEchoTask, "{wrapped}")' in src \
        else src.split(f'@override(BaseWWTask, "{wrapped}")')[-1]
    head = block.split("@override")[0]
    check(f"包 {wrapped} 的那层调用了上游原方法", f"{captured}(self" in head)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
