"""The boss list on the phone page and the one in the relay must be the same list.

The page cannot read the table from the state payload - ntfy caps a message at
3900 bytes and adding it blew that on the first try - so, exactly as with the
forgery table, the page carries a copy. Two copies of a list that decides which
boss gets farmed will disagree eventually; this is the thing that stops them.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import wuwa_boss

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r} vs {want!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


app = (Path(__file__).resolve().parents[2] / "web" / "app.js").read_text(encoding="utf-8")
m = re.search(r"const BOSSES = \[(.*?)\];", app, re.S)
check("页面里有这张表", bool(m), True)
page = [] if not m else [(int(i), n) for i, n in re.findall(r'\[\s*(\d+)\s*,\s*"([^"]+)"\s*\]', m.group(1))]
check("页面和中继一字不差", page, wuwa_boss.choices())

print("\n[没登记的位置只说「第 N 个」，不许猜]")
check("登记过的给名字", wuwa_boss.label(1), "天傀劫煞")
check("没登记的说第几个", wuwa_boss.label(9), "第 9 个")
check("不是数字也不崩", wuwa_boss.label("x"), "第 x 个")
check("只有 1 是真的跑通过的", set(wuwa_boss.VERIFIED), {1})

print("\n[状态包里不许再带这张表——放进去当天就撑爆了 ntfy 的上限]")
phone = (Path(__file__).resolve().parents[1] / "ark_relay" / "phone.py").read_text(encoding="utf-8")
check("phone.py 不发 bosses", '"bosses"' in phone, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
