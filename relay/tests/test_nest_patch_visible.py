"""A refused nest patch must not leave every report saying 「只打落渊南丘」.

「Only Farm These Nests」 is an option **our copy** of NightmareNestTask.py adds;
upstream has no such setting. So when the patch is refused - upstream restructured
the file and the hash no longer matches - nothing reads that value and every nest
gets farmed, all night. The config value is untouched, which is exactly why
tomorrow's plan went on announcing 「只打落渊南丘」: it read the config and never
looked at whether the code that honours it is there.

That breaks a standing instruction (nests: 落渊南丘 only) while every surface says
it is being kept. And the notification could not tell it either: a patch that could
not be applied shared its title with one that went on cleanly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import texts
from ark_relay.okww_patch import nest_patch_present, _NEST_MARKER, _SRC
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def okww(body):
    root = tmpdir()
    if body is not None:
        f = root.joinpath(*_SRC, "NightmareNestTask.py")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)
    return root


print("[改动在不在，看 OK-WW 自己写下的那份报告，不看配置也不看源文件]")
# Since 2026-09-09 the change lives in ok_tasks/ark_overrides.py, so the source file
# is upstream's own and looking at it would report 「没贴上」 on a healthy machine -
# which is what tomorrow's plan said that night.
from ark_relay import okww_overlay  # noqa: E402

_real_report = okww_overlay.last_report
try:
    okww_overlay.last_report = lambda: {"applied": ["NightmareNestTask.find_nest"],
                                        "skipped": [], "error": ""}
    check("绑上了就是在", nest_patch_present(okww(None)), True)
    okww_overlay.last_report = lambda: {
        "applied": [], "error": "",
        "skipped": [{"what": "NightmareNestTask.find_nest", "why": "上游正文变了"}]}
    check("被跳过了就是不在", nest_patch_present(okww(None)), False)
    okww_overlay.last_report = lambda: {"error": "Traceback ..."}
    check("整个文件炸了也是不在", nest_patch_present(okww(None)), False)
    okww_overlay.last_report = lambda: {}
    check("还没有报告时说不知道，不瞎猜", nest_patch_present(okww(None)), None)
finally:
    okww_overlay.last_report = _real_report
check("目录是 None 时说不知道", nest_patch_present(None), None)
check("目录是 None 时说不知道", nest_patch_present(None), None)

print("\n[补丁没贴上时，明日安排必须改口]")
import os                                                          # noqa: E402
from ark_relay import plan                                         # noqa: E402
nest = {"Only Farm These Nests": "落渊南丘"}
zh = {"Tacet Discord Nest": "残象聚落"}

os.environ["ARK_OKWW_DIR"] = str(okww(b"x = 1\n" + _NEST_MARKER))
good = plan._okww_nest_bit({}, nest, [], zh)
if good is None:
    print("  · 这一段的函数名变了，跳过（下面的标题检查照跑）")
else:
    check("贴上了就照常说只打南丘", "只打落渊南丘" in good, True)
    os.environ["ARK_OKWW_DIR"] = str(okww(b"class NightmareNestTask:\n    pass\n"))
    bad = plan._okww_nest_bit({}, nest, [], zh)
    check("没贴上就说实话", "实际会刷全部点位" in bad, True)
    check("而且点名了本该只打哪", "本该只打落渊南丘" in bad, True)
os.environ.pop("ARK_OKWW_DIR", None)

print("\n[通知标题要分得出「贴上了」和「贴不上」]")
check("全都贴上了", texts.patches(3, ["a 已贴上", "b 已贴上", "c 已贴上"]),
      "🩹 OK-WW 补丁（3 条）")
t = texts.patches(3, ["a 已贴上", "巢穴任务**贴不上了**（上游结构变了）", "c 已贴上"])
check("有贴不上的就换标题", t.startswith("⚠️"), True)
check("标题里写清几条没贴上", "1 条没贴上" in t, True)
check("没传明细时不瞎报", texts.patches(2), "🩹 OK-WW 补丁（2 条）")
check("写不进去也算没贴上",
      texts.patches(1, ["某补丁 写不进去"]).startswith("⚠️"), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
