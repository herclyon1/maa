"""Wuthering Waves banners: how the bulletin and the notices are read (2026-10-13 audit).

* Collaboration and memory banners say 「角色联动唤取」 / 「角色忆旅唤取」, not only
  「角色活动唤取」; the pool-name and notice-title patterns took only 活动.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.banners import wuwa as W

fails = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


print("[collaboration and memory banners: 联动 / 忆旅 as well as 活动]")
for kind in ("活动", "联动", "忆旅"):
    body = f"<p>全新角色</p><p>5星共鸣者「某人」</p><p>※可通过[某池]角色{kind}唤取获得</p><p>全新武器</p>"
    check(f"bulletin pool name, 角色{kind}唤取", W.parse_wuwa_preview(body), [("某人", "某池")])
    nb = W.parse_wuwa_notice_banners({"recommend": [{
        "tabTitle": f"[某池]角色{kind}唤取",
        "content": "5星角色「某人」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}]})
    check(f"notice banner, 角色{kind}唤取", [(x.name, x.chars) for x in nb], [("某池", ("某人",))])
check("a weapon banner is still not a character banner",
      W.parse_wuwa_notice_banners({"recommend": [{
          "tabTitle": "「碎骨」武器联动唤取",
          "content": "5星武器「某刀」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}]}), [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
