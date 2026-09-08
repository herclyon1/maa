# 终末地 build materials: what one build costs, and how much to stockpile

**Every number here comes from 森空岛's official endpoints** (`calculate/rules`, `material-list`,
`user-game-data`), measured on 2026-08-27. None of it is estimated.
Endpoint usage is in [SKLAND-API.md](SKLAND-API.md).

"One build" = **one six-star operator + their matching signature weapon, taken from level 1 with
nothing invested up to the target tier**. The four tiers are defined by the official front-end
constants: 基础 60/技6/武60, 晋级 80/技9/武80, 高阶 90/技9/武90, 完美 90/技12/武90.

## 1. What one 完美 build costs

Sampled on 莱万汀 + 《熔铸火焰》:

| Item | Amount |
|---|--:|
| 金币 | 1,693,510 |
| 干员经验 | 1,792,290 |
| 武器经验 | 2,524,080 |

## 2. Universal materials (identical for all 16 six-stars — stockpiling these is never wrong)

**Operator side** (promotions + skills to level 12):

| Material | Per build |
|---|--:|
| 协议棱柱组 | 472 |
| 协议棱柱 | 328 |
| 协议圆盘组 | 60 |
| 协议圆盘 | 33 |
| 存续的痕迹 | 24 |
| 纯晶多齿叶 | 16 |
| 至晶多齿叶 | 16 |
| 晶化多齿叶 | 12 |
| 重红柱状菌 | 5 |
| 中红柱状菌 | 5 |
| 轻红柱状菌 | 3 |

**Signature weapon side** (all promotions):

| Material | Per build |
|---|--:|
| 重型强固模具 | 50 |
| 强固模具 | 23 |
| 中黯石 | 5 |
| 重黯石 | 5 |
| 轻黯石 | 3 |

## 3. Variable materials (they differ by operator/weapon; only one of each group is ever used)

**Operators**:

| Group | Per build | How many of the 16 use it |
|---|--:|---|
| 三相纳米片 / D96钢样品四 / 象限拟合液 / 快子遴捡晶格 / 超距辉映管 — **pick 1 of 5** | 116 (a few need 20 or 136) | 8–11 each |
| 受蚀玉化叶 / 岩天使叶 / 红矛叶 — **pick 1 of 3** | 84 | 9 / 6 / 1 |
| 星门菌 / 塔罗斯菌 / 血菌 — **pick 1 of 3** | 8 | 7 / 2 / 7 |

**Signature weapons**:

| Group | Per build | How many of the 16 use it |
|---|--:|---|
| 超距辉映管 / D96钢样品四 / 象限拟合液 / 快子遴捡晶格 / 三相纳米片 / 协议纹石 — **pick 1 of 6** | 16 (协议纹石: 8) | 1–5 each |
| 武陵石 / 燎石 — **pick 1 of 2** | 8 | 8 / 7 |

> Those 116 units in the pick-1-of-5 group are **the only variable item that is genuinely large**.
> Which of the five you need cannot be known before the operator is pulled, which makes this the
> hardest part of the stockpile to prepare for in advance.

## 4. Inventory and bottlenecks as they stand (2026-08-27 17:48)

Sorted by "how many 完美 builds the universal material on hand covers":

| Material | Per build | On hand | Builds covered |
|---|--:|--:|--:|
| **协议棱柱** | 328 | 1,486 | **4** ← bottleneck |
| **重型强固模具** | 50 | 294 | **5** |
| 金币 (counting 金票) | 1,693,510 | 6,809,727 | 4 |
| 武器经验 | 2,524,080 | 16,861,000 | 6 |
| 协议棱柱组 | 472 | 3,905 | 8 |
| 强固模具 | 23 | 232 | 10 |
| 存续的痕迹 | 24 | 273 | 11 |
| 重红柱状菌 | 5 | 58 | 11 |
| 干员经验 | 1,792,290 | 24,443,000 | 13 |
| 至晶多齿叶 | 16 | 288 | 18 |
| all other universal materials | — | — | 20–125 |

**Conclusion: 协议棱柱 and 金币 are the hard bottlenecks; both cover only 4 builds.**
EXP materials are wildly in surplus (干员经验 covers 13 builds), so farming more EXP stages
accomplishes nothing.

Where the variable materials stand (shortfall measured against maxing one 完美 build):
超距辉映管 22, 象限拟合液 3, 快子遴捡晶格 3, 三相纳米片 84, D96钢样品四 0 — within the
pick-1-of-5 group **only 三相纳米片 just barely covers one build**; none of the others do.

## 5. How much is worth stockpiling

The community has **no** published numeric stockpiling targets (checked cmyyx/cep and several guide
sites). Qualitatively the guides agree in calling out 「协议棱柱是精英化核心稀缺资源」, which matches
the bottleneck computed above.

Measured as "able to max out N new operators the moment they arrive", the target = per build × N:

| Target | 协议棱柱 | 协议棱柱组 | 重型强固模具 | 金币 |
|---|--:|--:|--:|--:|
| ready for 2 builds | 656 | 944 | 100 | 3,390,000 |
| ready for 3 builds | 984 | 1,416 | 150 | 5,080,000 |
| **ready for 4 builds (where we are)** | 1,312 | 1,888 | 200 | 6,770,000 |

Variable materials cannot be stockpiled per build — which one is needed is unknown until the
operator is pulled. The workable approach is to hold **116 of each of the five in the pick-1-of-5
group** (580 in total), so that any new operator can be maxed immediately. The current stock is
nowhere near that.
