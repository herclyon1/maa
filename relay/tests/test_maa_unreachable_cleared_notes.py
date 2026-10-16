"""test_maa_unreachable.py still passes on a relay tree whose RELEASE-NOTES.md is empty.

scripts/mac/deploy-relay.sh empties relay/RELEASE-NOTES.md and commits that to main on
every deploy, so an empty notes file is the normal state between deploys. The test read
the notes with a bare `next(...)` looking for the re-run line; on the emptied file that
raised StopIteration, the test exited 1 and the sections after it never ran. The test is
mapped to some 40 relay modules, so the deploy gate would have gone red on the first relay
change after the next deploy.

Here a copy of ark_relay sits next to an empty RELEASE-NOTES.md, and test_maa_unreachable.py
runs against it with --relay. Before the fix: exit 1, StopIteration. After: exit 0, and the
last section (the make-up in flight) still runs.

  python3 tests/test_maa_unreachable_cleared_notes.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RELAY = HERE.parent
sys.path.insert(0, str(HERE))

from _tmp import tmpdir  # noqa: E402

fails: list[str] = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


print("[部署后更新说明被清空：明日方舟进不了游戏那套测试照样跑完]")
shadow = tmpdir()
# A copy, not a symlink: the relay tests also run on Windows CI.
shutil.copytree(RELAY / "ark_relay", shadow / "ark_relay",
                ignore=shutil.ignore_patterns("__pycache__"))
(shadow / "RELEASE-NOTES.md").write_text("", encoding="utf-8")
p = subprocess.run([sys.executable, str(HERE / "test_maa_unreachable.py"), "--relay", str(shadow)],
                   capture_output=True, text=True, encoding="utf-8", timeout=60)
check("退出码 0", p.returncode, 0)
check("没有 StopIteration", "StopIteration" in p.stderr, False)
check("最后一节也跑到了", "补跑落地后：更新照常起" in p.stdout, True)
if fails:
    print(p.stdout[-2000:])
    print(p.stderr[-2000:])

print("\nall checks passed" if not fails else f"\n{len(fails)} check(s) failed")
sys.exit(1 if fails else 0)
