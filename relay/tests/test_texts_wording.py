"""Copy that said more than the code does (review 2026-10-13, s1).

Each block pins one sentence against the code it describes; the reason is in the
block's header.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_relay.core import texts  # noqa: E402

# automas_keeper imports win32api at module level, so read its constants from source.
_KEEPER = ast.parse((ROOT / "ark_relay/features/host/automas_keeper.py").read_text(encoding="utf-8"))
KEEPER = {t.id: n.value.value for n in _KEEPER.body if isinstance(n, ast.Assign)
          for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


print("[AUTO-MAS 开机没起来：重拉的间隔写的是翻倍，不是每 3 分钟（s1 #9）]")
# automas_keeper: the first wait is REVIVE_FIRST_WAIT (180 s), then it doubles up to
# REVIVE_MAX_WAIT; relay.log 08-22 23:12:56 -> 23:16:06 -> 23:22:16 shows the doubling.
body = texts.automas_boot_down_body()
check("第一次等 3 分钟（代码里也是 180 秒）", (KEEPER["REVIVE_FIRST_WAIT"], "3 分钟后" in body), (180, True))
check("说了之后翻倍", "翻倍" in body, True)
check("不再说每 3 分钟", "每 3 分钟" in body, False)
check("连拉几次再报，和代码一致", f"连拉 {KEEPER["REVIVE_ALERT_AFTER"]} 次" in body, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
