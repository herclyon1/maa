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
import subprocess
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


man = json.loads((RELAY / "manifest.json").read_text(encoding="utf-8"))
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
probe = RELAY / "zz_manifest_probe.py"
try:
    probe.write_text("# 临时探针，测完就删\n", encoding="utf-8")
    out = subprocess.run([sys.executable, "make-manifest.py"], cwd=RELAY,
                         capture_output=True, text=True)
    check("生成器跑得起来", out.returncode, 0)
    again = json.loads((RELAY / "manifest.json").read_text(encoding="utf-8"))
    check("新文件被收进清单", "zz_manifest_probe.py" in again["files"], True)
finally:
    probe.unlink(missing_ok=True)
    # 还原成不含探针的那份，别把探针留在清单里
    subprocess.run([sys.executable, "make-manifest.py"], cwd=RELAY,
                   capture_output=True, text=True)

back = json.loads((RELAY / "manifest.json").read_text(encoding="utf-8"))
check("还原后清单里没有探针", "zz_manifest_probe.py" in back["files"], False)
check("还原后文件数和开工时一致", len(back["files"]), len(listed))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
