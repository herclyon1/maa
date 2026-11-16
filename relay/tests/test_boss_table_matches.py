"""The boss list the phone carries and the one in the relay must be the same list.

The phone cannot read the table from the state payload - ntfy caps a message at
3900 bytes and adding it blew that on the first try - so, exactly as with the
forgery table, the phone carries a copy. Until 2026-11-17 this test read that copy out of
the phone page (web/schema.js `const BOSSES`); the page was removed that day, so the copy
is pinned here as it stood then. A change to wuwa_boss's list fails here until the pin, and
the App's copy with it, follows.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import wuwa_boss

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r} vs {want!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


# web/schema.js `const BOSSES` as of 2026-11-17 (git show 1c8b5828:web/schema.js).
PAGE = [(1, "天傀劫煞"), (2, "万囿牢·朽躯"), (3, "梦魇亚当·重锤"), (4, "无铭探索者")]
check("手机那份和中继一字不差", PAGE, wuwa_boss.choices())

print("\n[没登记的位置只说「第 N 个」，不许猜]")
check("登记过的给名字", wuwa_boss.label(1), "天傀劫煞")
check("没登记的说第几个", wuwa_boss.label(9), "第 9 个")
check("不是数字也不崩", wuwa_boss.label("x"), "第 x 个")
check("no VERIFIED constant (nothing read it)", hasattr(wuwa_boss, "VERIFIED"), False)
check("天傀劫煞 is listed under 瑝珑·梦州 (2026-09-30 re-read)", wuwa_boss.BOSSES[1], ("天傀劫煞", "瑝珑·梦州"))

print("\n[状态包里不许再带这张表——放进去当天就撑爆了 ntfy 的上限]")
phone = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "phone" / "phone.py").read_text(encoding="utf-8")
check("phone.py 不发 bosses", '"bosses"' in phone, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
