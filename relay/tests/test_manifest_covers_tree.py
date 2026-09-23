"""推送清单必须覆盖 relay/ 下真正会被送上机器的每一个文件。

**这个测试是一次事故换来的**（2026-09-08 14:00）：`boot_stages.py` 从 service.py
拆出来之后，清单生成器那份**手写的文件名单**里没有它，于是它没被推上机器。
而「逐文件核对哈希」那道闸门只核对清单里有的文件——清单里没有它，闸门就一路绿灯，
服务却因为 `ModuleNotFoundError: No module named 'boot_stages'` 起不来，
通知链路断了十分钟。

判据：手写名单和「目录里实际有什么」迟早会分家，所以清单必须**扫目录**得到。
这个测试就是钉住这一点——往 relay/ 里放个新 .py，清单没收它就红。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


# The generator stamps a fresh version and ref every time it runs, so the
# probe below must never run it against the real tree. Restoring the bytes in a
# `finally` was not enough: a run killed mid-way (or one from an older checkout)
# still left a version nobody deployed in the shared tree - 2026-09-23 10:55:04,
# maa-automation-controls, version 20260923001824, which exists on no branch.
# The probe now runs on a throwaway copy; the real file is only read.
original = (RELAY / "manifest.json").read_bytes()
man = json.loads(original.decode("utf-8"))
listed = set(man["files"])

print("[顶层每个 .py 都在清单里]")
top = {p.name for p in RELAY.glob("*.py")} - {"make-manifest.py"}
check("顶层 .py 全覆盖", sorted(top - listed), [])
check("service.py 在", "service.py" in listed, True)
check("boot_stages.py 在（就是它没进清单，服务起不来）", "boot_stages.py" in listed, True)

print("\n[ark_relay 包里每个 .py 都在清单里]")
pkg = {p.relative_to(RELAY).as_posix() for p in (RELAY / "ark_relay").rglob("*.py")}
check("包内 .py 全覆盖", sorted(pkg - listed), [])

print("\n[清单里的每个文件都真的存在——否则部署会推一个空气]")
check("清单无幽灵条目",
      sorted(f for f in listed if f != "RELEASE-NOTES.md" and not (RELAY / f).exists()), [])

print("\n[新放一个文件进去，重新生成的清单必须收它]")
with tempfile.TemporaryDirectory() as tmp:
    copy = Path(tmp) / "relay"
    shutil.copytree(RELAY, copy,
                    ignore=shutil.ignore_patterns("tests", "state", "__pycache__"))
    (copy / "zz_manifest_probe.py").write_text("# 临时探针，测完就删\n", encoding="utf-8")
    out = subprocess.run([sys.executable, "make-manifest.py"], cwd=copy,
                         capture_output=True, text=True)
    check("生成器跑得起来", out.returncode, 0)
    again = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    check("新文件被收进清单", "zz_manifest_probe.py" in again["files"], True)
    check("副本里的清单和真清单文件集一致（除探针）",
          sorted(set(again["files"]) - {"zz_manifest_probe.py"}), sorted(listed))

check("真树里没留下探针", (RELAY / "zz_manifest_probe.py").exists(), False)
check("真清单测试前后逐字节不变", (RELAY / "manifest.json").read_bytes() == original, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
