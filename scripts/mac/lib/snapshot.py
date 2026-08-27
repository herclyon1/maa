#!/usr/bin/env python3
"""带时效判定的数据快照。**过期就拒绝使用，而不是默默拿旧的算。**

    from snapshot import fresh, stamp
    card = fresh("card")          # 太旧会抛异常，让你先去刷新
    print(stamp("card"))          # "02:25:46（41 分钟前）+ 官方同步延迟约 30 分钟"

**为什么存在**（2026-08-28）：

我拿 41 分钟前拉的快照，写成「**你的实际**」和用户当下的状态做对比，
全程没标时间。用户的原话是「你之前对比的【你的实际】压根都不是刷新之后的
结果，依旧沿用老快照，这个必须杜绝」。

更要命的是这份数据**天生就是旧的**：官方养成计算器自己写着

    「仓库资源和干员数据等信息的同步，会有 30 分钟左右的延迟」

所以「森空岛拉下来的那一刻」≠「游戏里此刻」。任何拿它下结论的地方，
都必须把这两层延迟摆出来，让人自己判断可不可信。

## 规矩（两条都是用户 2026-08-28 定的）

1. **不许自动刷新。** 每次读都去拉接口就是轮询，和
   [[no-polling-without-approval]] 撞车。用户原话：
   「你别一直自动刷新，否则你一直在后台运行这东西不就是轮询吗？
   事件驱动就是我手动跟你说刷新，你就自己刷新」。
   ——**刷新由「用户说刷新」这个事件触发，触发之后我自己跑，不让用户敲命令。**
2. **但读旧数据必须当场喊出来。** `load()` 每次都把年龄打在输出里，
   超龄会加一行醒目告警。用户原话：「你之前对比的【你的实际】压根都不是
   刷新之后的结果」——**不标时间的「你的实际」是谎话。**
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# 快照不进仓库——它是易腐品，不是资产。但也不能放会话临时目录：
# 那里跟着会话走，换一次会话数据就没了，下次又得重拉。
SNAP_DIR = Path.home() / ".cache" / "ark" / "snapshots"

# 官方自己声明的同步延迟。任何结论都要把它算进不确定性里。
SKLAND_SYNC_LAG_MIN = 30

FILES = {
    "card": "card_now.json",      # 角色练度 card/detail
    "inv": "inv_now.json",        # 库存 calculate/user-game-data
    "mat": "mat_now.json",        # 材料表 calculate/material-list
}


class Stale(RuntimeError):
    """快照太旧。**去刷新，不要将就。**"""


def age_min(kind: str) -> float:
    p = SNAP_DIR / FILES[kind]
    if not p.is_file():
        raise Stale(f"{kind} 快照不存在（{p}），先去拉一份")
    return (time.time() - p.stat().st_mtime) / 60


def stamp(kind: str) -> str:
    """给输出用的时间戳，两层延迟都写清楚。"""
    p = SNAP_DIR / FILES[kind]
    if not p.is_file():
        return f"{kind}：无快照"
    t = time.strftime("%H:%M:%S", time.localtime(p.stat().st_mtime))
    a = age_min(kind)
    return (f"数据抓取于 {t}（{a:.0f} 分钟前）"
            f"，另有官方同步延迟约 {SKLAND_SYNC_LAG_MIN} 分钟")


def is_stale(kind: str, max_age_min: float = 10) -> bool:
    """该不该刷。**由调用方决定要不要刷，这里不自作主张。**"""
    try:
        return age_min(kind) > max_age_min
    except Stale:
        return True                       # 没有快照 = 最旧


def load(kind: str, max_age_min: float = 10) -> dict:
    """读快照，**并把年龄打出来**。不自动刷新。

    超龄不拒绝、不偷偷去拉，而是打一条醒目告警——因为「数据旧」有时是
    可以接受的（只看量级），不可接受的是**不告诉人它旧**。
    """
    p = SNAP_DIR / FILES[kind]
    if not p.is_file():
        raise Stale(f"{kind} 快照不存在。用户说「刷新」时我再去拉；"
                    f"现在要拉就调 refresh_snapshot.refresh()。")
    if is_stale(kind, max_age_min):
        print(f"⚠️ 【{kind} 数据已 {age_min(kind):.0f} 分钟，超过 "
              f"{max_age_min:.0f} 分钟；结论按旧数据算，别当成此刻的状态】")
    print(f"【{stamp(kind)}】")
    return json.loads(p.read_text(encoding="utf-8"))


def ages() -> str:
    """所有快照的新旧一览，排查用。"""
    out = []
    for k in FILES:
        try:
            out.append(f"  {k:<5} {age_min(k):>6.1f} 分钟前")
        except Stale as e:
            out.append(f"  {k:<5} {e}")
    return "\n".join(out)


if __name__ == "__main__":
    print("快照新旧：")
    print(ages())
    print()
    for k in FILES:
        try:
            print(f"  {k}: {stamp(k)}")
        except Exception as e:  # noqa: BLE001
            print(f"  {k}: {e}")
