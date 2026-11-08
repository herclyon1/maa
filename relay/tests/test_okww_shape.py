"""A pinned OK-WW copy survives an upstream change that is only words (ledger #130; dispatch
relay-opt-round3-1108 O-02).

11-02 OK-WW v3.7.14-beta.2 wrapped the log text of claim_daily and claim_battle_pass in
self.tr(...) and changed nothing else; the text hash no longer matched, both copies were
skipped and upstream's bodies ran. The shape (the syntax tree without docstrings, log text and
self.tr; comments and layout are not in the tree) is checked next to the hash. Pinned here:

* the shape the overrides compute at OK-WW start and the one okww_overlay computes before the
  run are the same function: same answers on every sample;
* _SHAPES holds the shapes of the bodies the hashes were copied from (the installed
  v3.7.14-beta.2 fixture), and the overrides file and okww_overlay.shapes() read one table;
* words only (the v3.7.13 form: no self.tr, f-strings, comments, a docstring, layout): the
  hash differs, the shape does not - drift() calls it adapted, drift_line says so without a
  fault word, said once;
* a coordinate, a call or a feature name changed: the shape differs - skipped, said every boot.
"""
import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0]))
sys.path.insert(0, str(HERE))
from _tmp import tmpdir  # noqa: E402

from ark_relay.core import texts  # noqa: E402
from ark_relay.features.okww_patch import okww_overlay as ov  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


INST = HERE / "gamesim" / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task"
DAILY = (INST / "DailyTask.py.txt").read_text(encoding="utf-8")


def overrides_shape():
    """The overrides file's own _shape_text, without OK-WW: only its shape helpers, run here."""
    tree = ast.parse(ov.source_text())
    keep = {"_LOG_CALLS", "_canon", "_is_text", "_WordsOut", "_shape_text"}
    body = [n for n in tree.body if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in keep)
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in keep for t in n.targets))]
    ns = {}
    imports = ast.parse("import ast\nimport hashlib\nimport textwrap\n").body
    exec(compile(ast.Module(body=imports + body, type_ignores=[]), "ark_overrides.py", "exec"), ns)
    return ns["_shape_text"]


print("[两边算的是同一个形状]")
theirs = overrides_shape()
src = tmpdir() / "src"
src.mkdir()
for f in INST.glob("*.py.txt"):
    (src / f.name[:-4]).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
classes = ov._classes(src)
samples = []
for cls, (lines, methods, _bases) in classes.items():
    for name in methods:
        samples.append(ov._method_text(classes, cls, name))
check("扫到了很多方法", len(samples) > 50, True)
check("每一个方法两边算的都一样", [i for i, t in enumerate(samples) if theirs(t) != ov._shape_text(t)], [])
check("没有一个算成空的", [i for i, t in enumerate(samples) if not ov._shape_text(t)], [])

print("\n[钉住的形状就是装着的 v3.7.14-beta.2 那几段]")
pinned = ov.shapes()
check("覆盖文件里有四处", sorted(pinned), sorted(["DailyTask.claim_daily", "DailyTask.claim_battle_pass",
                                              "FarmEchoTask.click_team_challenge", "BaseWWTask.get_stamina"]))
for label, want in pinned.items():
    cls, name = label.split(".")
    # FarmEchoTask reaches BaseWWTask's click_team_challenge through src/combat/, which the
    # fixture does not carry: read it where it is defined.
    text = ov._method_text(classes, cls, name) or ov._method_text(classes, "BaseWWTask", name)
    check(f"{label} 对得上", ov._shape_text(text), want)
check("没有正文就没有形状（不是空文本的哈希）", (ov._shape_text(""), theirs("")), ("", ""))
check("这四处都是钉了哈希的", sorted(set(pinned) - {f"{c}.{m}" for c, m, _s, _a in ov.pins()}), [])


def okww(daily_text):
    root = tmpdir()
    d = root.joinpath(*ov._SRC)
    d.mkdir(parents=True)
    for f in INST.glob("*.py.txt"):
        (d / f.name[:-4]).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    (d / "DailyTask.py").write_text(daily_text, encoding="utf-8")
    return root


print("\n[只改了字（v3.7.13 那样）：哈希变了、形状没变 —— 照样换上，只说一次，不算毛病]")
WORDS = re.sub(r"self\.tr\(('[^']*')\)", r"\1", DAILY)
WORDS = WORDS.replace("    def claim_daily(self):\n", "    def claim_daily(self):\n        # a comment upstream added\n", 1)
WORDS = WORDS.replace("self.log_info('claim daily reward via  coordinate')",
                      "self.log_info(f'claim daily reward via coordinate {1}')")
check("真的改了 claim_daily 和 claim_battle_pass 的文字", WORDS != DAILY, True)
found = {d["what"]: d for d in ov.drift(okww(WORDS))}
check("两处都看出了哈希变化", sorted(found), ["DailyTask.claim_battle_pass", "DailyTask.claim_daily"])
check("两处都算适配（只改了字）", [(d["adapt"], d["words"]) for d in found.values()], [(True, True)] * 2)
state = tmpdir()
line = ov.drift_line(okww(WORDS), state)
check("那句话说只改了日志文字、照样换上", "只改了" in line and "照样换上" in line, True)
check("……不带「对不上」", "对不上" in line, False)
check("……标题是 🩹（不是 ⚠️）", texts.patches(1, [line]).startswith("🩹"), True)
check("……第二次开机不再说", ov.drift_line(okww(WORDS), state), "")

print("\n[改了坐标或调用：形状变了 —— 照旧不换、每次开机都说]")
for label, changed in (("坐标", DAILY.replace("self.click_relative(0.86, 0.05)", "self.click_relative(0.87, 0.05)")),
                       ("少了一步", DAILY.replace("self.ensure_main()", "pass", 1))):
    check(f"{label}：确实改了正文", changed != DAILY, True)
    d = [x for x in ov.drift(okww(changed)) if not x["adapt"]]
    check(f"{label}：算不上（跳过）", bool(d) and all(not x["words"] for x in d), True)
    state = tmpdir()
    first = ov.drift_line(okww(changed), state)
    check(f"{label}：说对不上、等重抄", "对不上" in first and "等我们重抄" in first, True)
    check(f"{label}：第二次开机照样说", ov.drift_line(okww(changed), state), first)

print("\n[文字里的功能名不是日志：改了照样算变了]")
FEATURE = DAILY.replace("'gray_book_quest'", "'gray_book_quest_v2'")
if FEATURE != DAILY:
    found = {d["what"]: d for d in ov.drift(okww(FEATURE))}
    check("改了找图用的名字：不算只改了字", [d["words"] for d in found.values()], [False] * len(found))
else:
    print("  · (the fixture names no gray_book_quest feature in DailyTask)")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
