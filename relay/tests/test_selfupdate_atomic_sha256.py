"""Self-update lands all files or none, and checks them by SHA-256 (review of 2026-10-07, item 4).

Two gaps were left after the download-everything-first rule:

* _write_staged wrote the targets one by one. A disk or permission error on the
  second file left the first one new and the rest old - and check() then
  cleared the failure it had just recorded and announced an update, and
  service.py restarted into the mixed version. Now every file is written to a
  staging directory first, and only when all of them are there are they swapped
  in; a failure while swapping puts back the ones already swapped. Either way
  the originals are what is on disk after a failure, and the failure stays
  recorded.
* Files were checked by SHA-1 only, which hashlib lists as a legacy algorithm.
  make-manifest.py now writes a `sha256` map next to `files`; the relay checks
  by it when it is there. `files` stays SHA-1 for one version, so a machine
  still on the old code (which only reads `files`) updates normally onto this
  one; a manifest with no `sha256` (one made before this change) is still
  checked by SHA-1.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import os
from ark_relay import selfupdate as su
from ark_relay.statestore import StateStore
from _tmp import tmpdir

os.environ[su.GITHUB_FALLBACK_ENV] = "1"     # the GitHub doors, as in test_selfupdate_doors.py
RELAY = Path(__file__).resolve().parents[1]
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class _NoSleep:
    monotonic = staticmethod(time.monotonic)

    @staticmethod
    def sleep(_s):
        return None


su.time = _NoSleep
su._cos = lambda: None
sha1 = lambda b: hashlib.sha1(b).hexdigest()      # noqa: E731
sha256 = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
OLD_A, OLD_B = b"print('a old')\n", b"print('b old')\n"
NEW_A, NEW_B = b"print('a new')\n", b"print('b new')\n"


def serve(man: dict, bodies: dict):
    """Every door answers with this manifest and these files."""
    data = json.dumps(man).encode("utf-8")

    def get(url, timeout=20):
        rel = url.split("/relay/", 1)[-1]
        if "/relay-" in url and rel == "manifest.json":
            return None
        return data if rel == "manifest.json" else bodies.get(rel)
    su._get_once = get
    su._last_good = ""


def machine():
    root = tmpdir()
    (root / "state").mkdir()
    (root / "a.py").write_bytes(OLD_A)
    (root / "b.py").write_bytes(OLD_B)
    StateStore(root / "state").set("versions", "code", "20261001000000")
    return root


def leftovers(root: Path) -> list:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.name not in ("a.py", "b.py") and not p.relative_to(root).as_posix().startswith("state"))


BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
NEW = {"version": 20261007000000,
       "files": {"a.py": sha1(NEW_A), "b.py": sha1(NEW_B)},
       "sha256": {"a.py": sha256(NEW_A), "b.py": sha256(NEW_B)}}
BODIES = {"a.py": NEW_A, "b.py": NEW_B}


def failed_round(root, label):
    check(f"{label}：返回空", su.check(root, BASE), [])
    check(f"{label}：a.py 还是原来的", (root / "a.py").read_bytes(), OLD_A)
    check(f"{label}：b.py 还是原来的", (root / "b.py").read_bytes(), OLD_B)
    check(f"{label}：版本号没前进", StateStore(root / "state").get("versions", "code"), "20261001000000")
    check(f"{label}：没留下「已更新」的播报", su.take_announcement(root), None)
    check(f"{label}：失败记下了（下次开机重来、会报出来）", bool(su.take_failure(root)), True)
    check(f"{label}：没留下暂存文件", leftovers(root), [])


print("[写到第二个文件时磁盘出错：两个原文件都不许动]")
root = machine()
serve(NEW, BODIES)
real_write = su._atomic_write
n = [0]


def write_fails_second(target, data):
    n[0] += 1
    if n[0] == 2:
        raise OSError(28, "No space left on device")
    real_write(target, data)


su._atomic_write = write_fails_second
try:
    failed_round(root, "写入失败")
finally:
    su._atomic_write = real_write

print("\n[换到第二个文件时出错（文件被占用）：已换上的那个要改回原样]")
root = machine()
serve(NEW, BODIES)
real_swap = getattr(su, "_swap_in", None)
real_replace = os.replace
m = [0]


def swap_fails_second(src, dst):
    m[0] += 1
    if m[0] == 2:
        raise PermissionError(32, "being used by another process")
    real_replace(src, dst)


su._swap_in = swap_fails_second
try:
    failed_round(root, "替换失败")
finally:
    if real_swap is None:
        del su._swap_in
    else:
        su._swap_in = real_swap

print("\n[一切正常：两个都换上，版本号前进，没有暂存残留]")
root = machine()
serve(NEW, BODIES)
check("两个都更新了", su.check(root, BASE), ["a.py", "b.py"])
check("a.py 是新的", (root / "a.py").read_bytes(), NEW_A)
check("b.py 是新的", (root / "b.py").read_bytes(), NEW_B)
check("版本号前进", StateStore(root / "state").get("versions", "code"), "20261007000000")
check("没留下暂存文件", leftovers(root), [])

print("\n[SHA-256 对不上（SHA-1 却对得上）：按 SHA-256 判，不更新]")
root = machine()
bad = dict(NEW, sha256={"a.py": sha256(b"something else"), "b.py": sha256(NEW_B)})
serve(bad, BODIES)
check("不更新", su.check(root, BASE), [])
check("a.py 原封不动", (root / "a.py").read_bytes(), OLD_A)
check("b.py 也没动（整轮放弃）", (root / "b.py").read_bytes(), OLD_B)

print("\n[SHA-256 表缺一个文件：这份清单不可信，整轮不更新]")
root = machine()
serve(dict(NEW, sha256={"a.py": sha256(NEW_A)}), BODIES)
check("不更新", su.check(root, BASE), [])
check("a.py 原封不动", (root / "a.py").read_bytes(), OLD_A)

print("\n[旧格式清单（只有 SHA-1）：照旧能更新——兼容这一版之前做的清单]")
root = machine()
serve({"version": 20261007000000, "files": {"a.py": sha1(NEW_A), "b.py": sha1(NEW_B)}}, BODIES)
check("两个都更新了", su.check(root, BASE), ["a.py", "b.py"])

print("\n[本机已是新的：按 SHA-256 判出不用动]")
root = machine()
(root / "a.py").write_bytes(NEW_A)
(root / "b.py").write_bytes(NEW_B)
serve(NEW, BODIES)
check("没有要改的", su.check(root, BASE), [])
check("版本号记下", StateStore(root / "state").get("versions", "code"), "20261007000000")

print("\n[make-manifest.py：files 仍是 SHA-1（给旧机器），另有一张一一对应的 sha256 表]")
with tempfile.TemporaryDirectory() as tmp:
    copy = Path(tmp) / "relay"
    shutil.copytree(RELAY, copy, ignore=shutil.ignore_patterns("tests", "state", "__pycache__"))
    out = subprocess.run([sys.executable, "make-manifest.py"], cwd=copy, capture_output=True, text=True)
    check("生成器跑得起来", out.returncode, 0)
    man = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    files, s256 = man.get("files") or {}, man.get("sha256") or {}
    check("有 sha256 表", bool(s256), True)
    check("两张表文件一样", sorted(s256) == sorted(files), True)
    check("files 每一项都是那个文件的 SHA-1",
          [f for f, h in files.items() if h != sha1((copy / f).read_bytes())], [])
    check("sha256 每一项都是那个文件的 SHA-256",
          [f for f, h in s256.items() if h != sha256((copy / f).read_bytes())], [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
