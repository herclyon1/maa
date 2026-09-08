"""The claim patch must never spend waveplates while the 4-cost echo farm runs.

Claiming a boss reward costs 60 waveplates every time. Farming echoes is free. On
2026-09-09 the time-bounded farm was wired onto the very branch that claims, so an
unattended overnight run would have drained the waveplates and then the reserve.
The gate is a marker file the relay writes while farming; this pins both halves of
it together so neither can drift away from the other.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import echofarm
from ark_relay.okww_patches.claim import _CLAIM_NEW, _CLAIM_V5, _CLAIM_V6, _claim_present
from ark_relay import okww_patch

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


print("[补丁正文里真的有这道闸]")
check("正文检查标记文件", "ark-okww-farm.no-claim" in _CLAIM_NEW)
check("挂着标记时不点确认", "if not _claim_ok:" in _CLAIM_NEW)
check("确认那一步排在闸后面", _CLAIM_NEW.index("_claim_ok") < _CLAIM_NEW.index("click_dialog_right_button"))

print("[中继写的路径和补丁读的路径是同一个]")
name = Path(echofarm.NO_CLAIM.replace("\\", "/")).name
check(f"文件名一致（{name}）", name in _CLAIM_NEW)

print("[刷声骸时不退本，走 F 重进一趟——退了就没有下一趟]")
check("刷声骸模式会重进副本", "enter_configured_boss_realm_from_f" in _CLAIM_NEW)
check("只在秘境里才重进", "self._in_realm" in _CLAIM_NEW)
check("重进之后不再走退本那段", "_exited = True" in _CLAIM_NEW)

print("[旧版留着能退，不然新版贴不上去]")
check("v5 还在", "ark-okww-farm.no-claim" not in _CLAIM_V5)
check("v5 登记在可退列表里", any(old is _CLAIM_V5 for _, old, _, _ in okww_patch._REVERTS))
check("v6 登记在可退列表里", any(old is _CLAIM_V6 for _, old, _, _ in okww_patch._REVERTS))
check("v6 里还没有重进那步", "enter_configured_boss_realm_from_f" not in _CLAIM_V6)

print("[在不在的判据认的是新版]")
check("认得出新版", _claim_present(_CLAIM_NEW))
check("认不出旧版", _claim_present(_CLAIM_V5), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
