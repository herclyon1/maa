"""The health check's 「nest source = upstream's own」 item follows OK-WW's updates.

10-10 22:4x the item was red: the machine's working/src/task/NightmareNestTask.py
(11932 bytes, sha1 8e3a251042, 10-04 08:47) was compared byte for byte with the copy
stored in okww_files (08-27, 11138 bytes). The machine's file was upstream's own -
the same bytes as OK-WW v3.7.4 on cnb.cool and on GitHub - so every OK-WW update
turned the item red. It is judged against OK-WW's own git checkout (repo/); the stored
copy itself was removed 2026-10-12 with the code that restored it.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.okww_patch import okww_overlay as O

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
