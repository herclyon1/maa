"""Moving _STAMINA from v1 to v2 on a machine that already carries v1 + _NOFARM.

_NOFARM's anchor lives inside _STAMINA's body, so a machine with both applied
holds v1 *with NOFARM's rewrite inside it*. A plain "revert v1" does not match
that text, v2 then finds neither the upstream anchor nor its own marker, and the
result is 「贴不上了」 - which is exactly what the deploy gate caught on 2026-09-09.
This replays that machine state and demands the migration lands cleanly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import okww_patch as P
from ark_relay.okww_patches.core import _SRC
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


HEAD = "from x import *\n\n\nclass DailyTask:\n    support_tasks = [1, 2, 3]\n\n    def run(self):\n"


def machine(body: str) -> Path:
    root = tmpdir()
    f = root.joinpath(*_SRC, "DailyTask.py")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(HEAD + body + "\n", encoding="utf-8")
    return root


def text(root: Path) -> str:
    return root.joinpath(*_SRC, "DailyTask.py").read_text(encoding="utf-8")


print("[从上游原文出发：v2 + 不刷体力开关都贴上，而且能编译]")
r = machine(P._STAMINA_OLD)
done = P._ensure_stamina(r)
t = text(r)
check("v2 在", P._stamina_present(t), True)
check("不刷体力开关在", P._nofarm_present(t), True)
compile(t, "DailyTask.py", "exec")
check("再跑一遍什么都不做", P._ensure_stamina(r), [])

print("\n[从「v1 + 不刷体力」那台机器的状态出发：这就是 09-09 贴不上的那一步]")
v1_with_nofarm = P._STAMINA_V1.replace(P._NOFARM_OLD, P._NOFARM_NEW)
check("v1 里真的嵌着开关的锚点", v1_with_nofarm != P._STAMINA_V1, True)
r = machine(v1_with_nofarm)
done = P._ensure_stamina(r)
t = text(r)
check("没有一条「贴不上」", any("贴不上" in d for d in done), False)
check("v2 在", P._stamina_present(t), True)
check("开关还在", P._nofarm_present(t), True)
check("v1 的老正文没了", "本地补丁 v2" in t and t.count("self.run_additional_tasks()") == 1, True)
compile(t, "DailyTask.py", "exec")

print("\n[从裸 v1（没开关）出发也一样]")
r = machine(P._STAMINA_V1)
P._ensure_stamina(r)
t = text(r)
check("v2 在", P._stamina_present(t), True)
check("开关在", P._nofarm_present(t), True)
compile(t, "DailyTask.py", "exec")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
