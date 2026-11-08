"""The nest patch: visible, the source pristine, the strings pinned.

One part per former file, each run on its own (tests/_parts.py): test_nest_patch_visible.py, test_nest_source_pristine.py, test_nest_strings_pinned.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_nest_patch_visible():
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

    Formerly test_nest_patch_visible.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features.okww_patch import okww_overlay
    from ark_relay.features.okww_patch.okww_overlay import nest_patch_present


    def okww(_body):
        """An OK-WW folder; presence is read from the overlay report, not from its files."""
        return tmpdir()


    print("[改动在不在，看 OK-WW 自己写下的那份报告，不看配置也不看源文件]")
    # Since 2026-09-09 the change lives in ok_tasks/ark_overrides.py, so the source file
    # is upstream's own and looking at it would report 「没贴上」 on a healthy machine -
    # which is what tomorrow's plan said that night.

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
        # The file raised after find_nest was bound (audit 2026-10-13, A5): it is bound.
        okww_overlay.last_report = lambda: {"applied": ["NightmareNestTask.find_nest"], "error": "Traceback ..."}
        check("raised after binding find_nest: present", nest_patch_present(okww(None)), True)
        okww_overlay.last_report = lambda: {"applied": ["FarmEchoTask.run"], "error": "Traceback ..."}
        check("raised before binding find_nest: absent", nest_patch_present(okww(None)), False)
        okww_overlay.last_report = lambda: {}
        check("还没有报告时说不知道，不瞎猜", nest_patch_present(okww(None)), None)
    finally:
        okww_overlay.last_report = _real_report
    check("目录是 None 时说不知道", nest_patch_present(None), None)
    check("目录是 None 时说不知道", nest_patch_present(None), None)

    print("\n[补丁没贴上时，明日安排必须改口]")
    import os
    from ark_relay.core import plan
    nest = {"Only Farm These Nests": "落渊南丘"}
    zh = {"Tacet Discord Nest": "残象聚落"}

    # Presence is read from OK-WW's binding report (okww_overlay.last_report), not
    # from the source file. Until 2026-09-14 this block passed only because a stray
    # report file with an error in it sat in the repo's cwd - stub the report here.
    os.environ["ARK_OKWW_DIR"] = str(okww(None))
    okww_overlay.last_report = lambda: {"applied": ["NightmareNestTask.find_nest"], "skipped": []}
    good = plan._okww_nest_bit({}, nest, [], zh)
    if good is None:
        print("  · 这一段的函数名变了，跳过（下面的标题检查照跑）")
    else:
        check("贴上了就照常说只打南丘", "只打落渊南丘" in good, True)
        okww_overlay.last_report = lambda: {
            "applied": [], "skipped": [{"what": "NightmareNestTask.find_nest", "why": "结构变了"}]}
        bad = plan._okww_nest_bit({}, nest, [], zh)
        check("没贴上就说实话", "这一轮不会刷巢穴" in bad, True)
        check("而且点名了本该只打哪", "本该只打落渊南丘" in bad, True)
    okww_overlay.last_report = _real_report
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


def _part_nest_source_pristine():
    """The health check's 「nest source = upstream's own」 item follows OK-WW's updates.

10-10 22:4x the item was red: the machine's working/src/task/NightmareNestTask.py
(11932 bytes, sha1 8e3a251042, 10-04 08:47) was compared byte for byte with the copy
stored in okww_files (08-27, 11138 bytes). The machine's file was upstream's own -
the same bytes as OK-WW v3.7.4 on cnb.cool and on GitHub - so every OK-WW update
turned the item red. It is judged against OK-WW's own git checkout (repo/); the stored
copy itself was removed 2026-10-12 with the code that restored it.

    Formerly test_nest_source_pristine.py.
    """
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay as O


    UPSTREAM = b"class NightmareNestTask:\n    def run(self):\n        pass\n"
    NEWER = UPSTREAM + b"\n# a later OK-WW release\n"
    WORK = ("data", "apps", "ok-ww", "working", "src", "task")
    REPO = ("data", "apps", "ok-ww", "repo", "src", "task")


    def machine(work, repo=None):
        root = Path(tempfile.mkdtemp())
        for parts, data in ((WORK, work), (REPO, repo)):
            if data is not None:
                f = root.joinpath(*parts, "NightmareNestTask.py")
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
        return root


    print("[the running copy is OK-WW's own checkout: green, whatever version]")
    ok, why = O.nest_source_pristine(machine(NEWER, NEWER))
    check("ok", ok, True)
    check("says size and sha1", f"{len(NEWER)} 字节" in why and "sha1" in why, True)
    check("ok with CRLF on the machine",
          O.nest_source_pristine(machine(UPSTREAM.replace(b"\n", b"\r\n"), UPSTREAM))[0], True)

    print("\n[someone edited the running copy: red]")
    ok, why = O.nest_source_pristine(machine(NEWER + b"x = 1\n", NEWER))
    check("not ok", ok, False)
    check("says it differs from OK-WW's own copy", "有人改过" in why, True)

    print("\n[the running copy missing: red]")
    ok, why = O.nest_source_pristine(machine(None, NEWER))
    check("not ok", ok, False)
    check("says it cannot read it", "读不了运行的那份" in why, True)

    print("\n[OK-WW's own checkout missing: red, says it cannot tell]")
    ok, why = O.nest_source_pristine(machine(NEWER))
    check("not ok", ok, False)
    check("says the checkout is unreadable", "git 副本读不了" in why, True)


def _part_nest_strings_pinned():
    """The two nest sentences the relay reads are written by our own override.

outcome.py and collector_okww.py decide whether the nests were farmed by looking
for two sentences in OK-WW's log (the "all full, skipping" one and the "spot not
found in the list" one). Both are printed by
relay/ark_relay/features/okww_patch/okww_files/ark_overrides.tasks.py - our file, not
upstream's (until 2026-09-09 the whole-file NightmareNestTask replacement printed them).
Nothing tied the two sides together: change a character in the override and 99 tests
stay green while the daily report starts saying, every day, that the nests were opened
and never fought.

    Formerly test_nest_strings_pinned.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww, outcome


    patched = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "okww_patch" / "okww_files"
               / "ark_overrides.tasks.py").read_text(encoding="utf-8")

    print("[读的那两句话，写的一侧必须还在补丁源码里]")
    check("「已打满」在补丁里", outcome._NEST_ALL_FULL in patched, True)
    check("「没找到点位」在补丁里", outcome._NEST_NOT_FOUND in patched, True)
    check("collector 那份正则也匹配补丁里的句子",
          bool(collector_okww._OKWW_NEST_FULL.search(patched)), True)

    print("\n[两个读的模块用的是同一句话，不许各写一份]")
    check("outcome 与 collector 一致",
          bool(collector_okww._OKWW_NEST_FULL.search(outcome._NEST_ALL_FULL)), True)


if __name__ == "__main__":
    sys.exit(run_parts([_part_nest_patch_visible, _part_nest_source_pristine, _part_nest_strings_pinned]))
