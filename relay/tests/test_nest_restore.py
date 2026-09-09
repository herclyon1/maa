"""The nest file replacement is retired and has to be undone on the machine.

Replacing a whole upstream file is the worst thing to leave behind: an OK-WW update
to that file gets overwritten every boot, silently. The behaviour moved into
ok_tasks/ark_overrides.py on 2026-09-09, so what is left is to put upstream's own file
back - but only when the file on disk is recognisably ours. Anything else is upstream's,
possibly newer than the copy we stored, and must not be touched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.okww_patches import nest
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def tree(content: bytes):
    root = tmpdir()
    d = root / "data" / "apps" / "ok-ww" / "working" / "src" / "task"
    d.mkdir(parents=True)
    (d / "NightmareNestTask.py").write_bytes(content)
    return root, d / "NightmareNestTask.py"


upstream = nest._NEST_UPSTREAM.read_bytes()
ours = nest._NEST_PATCHED.read_bytes()

print("[我们那份要被换回上游原样，并且说出来]")
root, f = tree(ours)
notes = nest._restore_nest(root)
check("换回来了", f.read_bytes() == upstream)
check("有留言", bool(notes))
check("留言说清是撤销", any("还原成上游原样" in n for n in notes))

print("[已经是上游原样就什么都不做，也不刷屏]")
check("不动", nest._restore_nest(root), [])

print("[上游自己的新版本不许碰——它可能比我们存的还新]")
newer = upstream.replace(b"class NightmareNestTask", b"# upstream changed this\nclass NightmareNestTask", 1)
root2, f2 = tree(newer)
check("原样留着", nest._restore_nest(root2), [])
check("文件一个字节没动", f2.read_bytes() == newer)

print("[文件不存在时不炸]")
check("空目录返回空", nest._restore_nest(tmpdir()), [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
