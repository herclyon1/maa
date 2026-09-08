"""A one-shot switch nobody displays is a switch that gets forgotten.

`no-stamina-farm.flag` is set by hand while testing the weekly boss and makes the
patched OK-WW skip stamina entirely. Nothing reported it: tomorrow's plan still
announced what the stamina would be spent on, healthcheck still ticked, and the
phone page still offered the choice. Only an ssh session running okww-landed.py by
hand could see it. Forget it and waveplates sit at the 240 cap, overflowing every
minute, while every surface says farming is happening.

This is the same shape as 「下次跑完不关机」, which has already cost a whole night
twice - and the answer is the same: the switch has to show up where the person is
looking.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

STATE = tmpdir()
os.environ["ARK_STATE_DIR"] = str(STATE)
FLAG = STATE / "no-stamina-farm.flag"

from ark_relay import plan                                    # noqa: E402
from ark_relay.config import no_stamina_farm                  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


DAILY = {"Which to Farm": "Simulation Domain"}

print("[没挂开关时，一切照旧]")
check("读出来是没挂", no_stamina_farm(), False)
line = plan._okww_farm_bit(DAILY, {"Simulation Domain": "模拟领域"})
check("照常预告刷什么", line.startswith("体力刷"), True)
check("不提那个开关", "不刷体力" in line, False)

print("\n[挂上开关：明日安排必须改口，而且要说清怎么恢复]")
FLAG.touch()
check("读出来是挂着的", no_stamina_farm(), True)
line = plan._okww_farm_bit(DAILY, {"Simulation Domain": "模拟领域"})
check("不再说在刷什么", line.startswith("体力刷"), False)
check("说清今天不刷", "今天不刷体力" in line, True)
check("说清波片会涨到上限", "上限" in line, True)
check("说清怎么恢复", "删掉标记文件" in line, True)

print("\n[删掉之后自己恢复，不需要谁去清什么状态]")
FLAG.unlink()
check("读出来又是没挂", no_stamina_farm(), False)
check("预告也回来了", plan._okww_farm_bit(DAILY, {"Simulation Domain": "模拟领域"}
                                          ).startswith("体力刷"), True)

print("\n[补丁认的那个路径，和这里读的是同一个]")
from ark_relay.okww_patches.nofarm import _NOFARM_NEW           # noqa: E402
from ark_relay.config import NO_STAMINA_FARM_FLAG               # noqa: E402
check("补丁正文里就是这个文件名", "no-stamina-farm.flag" in _NOFARM_NEW, True)
check("常量指的也是它", NO_STAMINA_FARM_FLAG.endswith("no-stamina-farm.flag"), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
