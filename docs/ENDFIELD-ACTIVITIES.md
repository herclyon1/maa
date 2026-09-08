# 终末地: the activity centre

## Keybind: the activity centre is F7, not F5

| Key | Screen it opens |
|----|-----------|
| F5 | 采购中心 (the shop, with real-money purchase buttons) |
| F7 | **活动中心 (activity centre)** <- press this one to see activity progress |
| F8 | 任务 (missions) |
| F9 | 武库 (armoury) |
| B | 背包 (bag) |
| C | 干员 (operators) |
| ESC | system menu |
| TAB | 探索 (exploration, the world map) |

The keybinds need neither guessing nor asking - once in the game, every icon in
the top-right corner has its own key printed above it. Crop `1330,0,1920,100`
out of a screenshot, enlarge it, and they are readable.

## The orange square in the sidebar means unread, not undone

Measured 2026-08-29: `根脉奇境`, `密境行者` and `协议邀约：重归` all carried an
orange dot, but on opening them `密境行者` had all three space groups at PERFECT
and `根脉奇境` showed 「奖励预览 已全部领取」. Opening the dot once makes it
disappear.

**Whether an activity is finished can only be read off the bottom right of its
detail page**:

- A green 「已全部领取 ✓」 = this activity is squeezed dry
- No such line = something is still unclaimed; go in and look

## Actual progress as of 2026-08-29 16:16 (Beijing time)

> This is a snapshot from that moment. For current numbers, open F7 again - do
> not read this as "now".

| Activity | Type | Time left | State |
|------|------|---------|------|
| 根脉奇境 | 趣味活动 | 3d 14h | **done** 奇境任务 14/14, 根脉历程 3600/3600, all rewards claimed, 蚀刻章 plated |
| 战争回响 | 挑战活动 | 3d 14h | **done** 谵妄赛季·谵妄轮换 III (last rotation of the season); 白刃穿水 / 战争简史 / 铳弹砺石 all three at full stars |
| 理智补给 | 限时活动 | 3d 12h | **done** all three tiers COMPLETED and claimed; refreshes in 12h 54m, the next tier can be claimed again |
| 每周事务 | 每周 | **1d 12h** | **not done** - see below |
| 密境行者 | 常驻·解谜 | permanent | **done** 密境初显 / 行探险窟 / 六方巧境 all three groups PERFECT, 六方巧境 6/6, all rewards claimed |
| 协议邀约：重归 | 分享活动 | 3d 14h | For inviting returning players; cannot be done alone |
| 深林覆雪签到 | 限时签到 | 3d 14h | **done** all 3 days claimed |
| 明耀晨星签到 | 限时签到 | 3d 14h | **done** all 7 days CHECKED |
| 作战演练 | 干员试用 | 3d 14h | **done** all rewards claimed |

### 每周事务: 5 of 10 tasks done, 9 points

Completed (5+1+1+1+1 = 9 points, which matches the 「已拥有 9」 on screen):

- 在「密境行者」中通关任意密境协议空间 1 次 1/1 (+5)
- 累计登录 3 天 3/3 (+1)
- 在物资调度系统中累计购买 1 次弹性物资 1/1 (+1)
- 于信用交易所累计购买 15 次商品 15/15 (+1)
- 累计击败 150 个敌人 150/150 (+1)

In progress:

| Task | Progress | Points |
|------|------|----|
| 拍摄 10 张照片 | 6/10 | +5 |
| 累计触发 100 次物理异常／法术爆发／法术异常效果 | 77/100 | +2 |
| 清理 15 次能量淤积点 | 5/15 | +2 |
| 在「影拓丰碑」中通关任意关卡 2 次 | 0/2 | +1 |
| 在帝江号上向干员赠送 10 次礼物 | 8/10 | +1 |

The last tier of the reward track sits at 10 points and the count is 9, so it is
**1 point short** of 100 源石 + 40,000. The cheapest way to close it is two more
gifts to operators on 帝江号.

## The 2400/2400 in the top right of the world screen is not sanity

On 2026-08-29 I took the `2400/2400` with the lightning ring in the top right of
the world screen for sanity and reported it as "sanity is capped and
overflowing". Wrong.

Sanity actually lives in the **top bar of the F8 行动手册**, and it read `68/360`
at the time - nowhere near full. The one in the top right is the energy bar of a
facility in the scene (the durability of 重锤迫击炮 and 暴雨铳械塔 is right next
to it) and has nothing to do with sanity.

**To read sanity, open F8; do not read the top right of the world screen.**
