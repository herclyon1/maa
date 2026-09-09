"""Every change must hook the smallest method that holds it, and every replacement
must be pinned.

The first shape of the overlay carried five whole-method copies, 30 to 90 lines each.
Upstream ships roughly every other day; each copy would have gone stale the first time
they touched that method. The pin would have said so, but the change would have
stopped happening all the same. So the rule is: hook one call deeper, and replace a
method outright only when upstream's own body is the thing that has to go.

This pins that rule. It is not a style preference: a copy is exposure to every edit
upstream makes inside it, and a wrapper is exposure to none.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import okww_overlay

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


src = okww_overlay.source_text()

# Everything we change, and the marker that proves it is still in the file.
CHANGES = {
    "刷声骸时角色阵亡原地复活": "刷声骸模式：角色阵亡，用一个复苏物品点",
    "复活之后接着刷下一趟": "刷声骸模式：复活成功，接着刷下一趟",
    "连败三次就收手": "次失败，退出本次任务，不再重试",
    "周本进本前读剩余次数": "本周周本次数已领满（0/3）",
    "波片不足就跳过周本": "波片不足挡住开启挑战",
    "无音区结算页留一张图": "tacet_drops",
    "附加任务提到刷体力之前": "附加任务出错，不拖垮当趟日常",
    "标记文件在就不刷体力": "刷体力已禁用（标记文件在）",
    "限时提前开放的剧情提示框": "限时提前开放的剧情提示框",
    "限时提前开放后直接进场": "限时提前开放：确认后直接进场",
    "主动跳过的信号照原样抛": "isinstance(exc.__cause__, TaskDisabledException)",
    "传送界面来晚了再等一次": "多等 15 秒",
}

print("[每一条改动都还在]")
for name, marker in CHANGES.items():
    check(name, marker in src)

# A replacement stops upstream's body from running, so it must be pinned.
# Everything else wraps.
REPLACEMENTS = {"revive_action", "click_team_challenge"}

print("[只有两处整段替换，而且都钉了指纹]")
bound = re.findall(r'@override\((\w+), "(\w+)"([^)]*)\)', src)
bound += [(c, m, r) for c, m, r in re.findall(r'override\((\w+), "(\w+)"([^)]*)\)\(', src)]
names = {m for _, m, _ in bound}
check("绑上的方法数不为零", len(names) > 0)
for cls, meth, rest in bound:
    if meth in REPLACEMENTS:
        check(f"{cls}.{meth} 钉了指纹", "expect_sha" in rest)
    else:
        check(f"{cls}.{meth} 不是整段替换", "expect_sha" in rest, False)

print("[不许再出现整段抄件：抄件里必然带着上游的循环和分支]")
for banned in ("def farm_do_run(", "def farm_teleport(", "def daily_run(",
               "def tacet_farm(", "def farm_run("):
    check(f"没有 {banned.strip('def (')}", banned in src, False)

print("[包一层的必须真的调用上游那份]")
for captured in ("farm_run(self", "farm_combat(self", "pick_level(self", "tacet_stamina(self",
                 "open_daily(self", "run_additional(self", "original(self",
                 "inner(self", "outer(self", "prepare(self"):
    check(f"调用了 {captured.split('(')[0]}", captured in src)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
