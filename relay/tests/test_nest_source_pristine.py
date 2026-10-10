"""The health check's 「nest source = upstream's own」 item follows OK-WW's updates.

10-10 22:4x the item was red: the machine's working/src/task/NightmareNestTask.py
(11932 bytes, sha1 8e3a251042, 10-04 08:47) was compared byte for byte with the copy
stored in okww_files (08-27, 11138 bytes). The machine's file was upstream's own -
the same bytes as OK-WW v3.7.4 on cnb.cool and on GitHub - so every OK-WW update
turned the item red. It is now judged against OK-WW's own git checkout (repo/).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.okww_patches import nest as N

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


STORED = N._NEST_UPSTREAM.read_bytes()
NEWER = STORED + b"\n# a later OK-WW release\n"
OURS = N._NEST_PATCHED.read_bytes()


def machine(work, repo=None):
    root = Path(tempfile.mkdtemp())
    for parts, data in ((N._SRC, work), (N._REPO, repo)):
        if data is not None:
            f = root.joinpath(*parts, "NightmareNestTask.py")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
    return root


print("[the stored reference is OK-WW v3.7.4, the machine's file on 10-10]")
check("sha1 8e3a251042, 11932 bytes", (__import__("hashlib").sha1(STORED).hexdigest()[:10], len(STORED)),
      ("8e3a251042", 11932))

print("\n[OK-WW updated past what we stored: upstream's own, green (red before)]")
ok, why = N.nest_source_pristine(machine(NEWER, NEWER))
check("ok", ok, True)
check("says it is newer than the stored copy", "比仓库里存的参照新" in why, True)
check("the old check would have said red", NEWER == STORED, False)

print("\n[the same as stored: green]")
ok, why = N.nest_source_pristine(machine(STORED, STORED))
check("ok", ok, True)
check("says it matches the stored copy", "和仓库里存的参照一致" in why, True)
print("  CRLF on the machine is the same content")
check("ok with CRLF", N.nest_source_pristine(machine(STORED.replace(b"\n", b"\r\n"), STORED))[0], True)

print("\n[our old whole-file replacement left behind: red]")
ok, why = N.nest_source_pristine(machine(OURS, NEWER))
check("not ok", ok, False)
check("says it is ours", "我们以前整份换上去的" in why, True)

print("\n[someone edited the running copy: red]")
ok, why = N.nest_source_pristine(machine(NEWER + b"x = 1\n", NEWER))
check("not ok", ok, False)
check("says it differs from OK-WW's own copy", "有人改过" in why, True)

print("\n[OK-WW's own checkout missing: red, says it cannot tell]")
ok, why = N.nest_source_pristine(machine(NEWER))
check("not ok", ok, False)
check("says the checkout is unreadable", "git 副本读不了" in why, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
