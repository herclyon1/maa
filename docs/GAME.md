<title>Game knowledge</title>

# Game knowledge

> **When something here is unclear, or a lookup fails: check PRTS and MAA's
> documentation first. Do not guess from the game screen.**
>
> Icons at depot-tile size are not distinguishable - 固源岩, 异铁 and 装置 are
> all grey-brown polygons, and 类凝结核 sits next to an unrelated amber jar
> that was mistaken for its green tier. A wiki page settles tier, recipe and
> whether a line exists at all, in one load.


Arknights facts that decide what this system farms. Separate from CONFIG.md
because those are settings on a machine; these are true of the game itself and
would still be true on a different machine.

Every number here was checked on [PRTS](https://prts.wiki) and carries its
source. Anything unchecked says so.

## Material tiers

Most materials come in a four-tier line. Two lines matter for current planning:

| Tier | Colour | Rock line | Ketone line |
|---|---|---|---|
| T1 | white | 源岩 | 双酮 |
| T2 | green | **固源岩** ("green rock") | **酮凝集** ("green ketone") |
| T3 | blue | **固源岩组** ("blue rock") | **酮凝集组** ("blue ketone") |
| T4 | purple | 提纯源岩 | 酮阵列 |

The operator refers to these by colour - 绿石头 / 蓝石头 for the rock line,
绿酮 / 蓝酮 for the ketone line. "石头" alone means the rock line.

## Every conversion ratio in the game

Complete, from the game's own `building_data.json` -> `workshopFormulas`
(`formulaType: F_EVOLVE`), mirrored at
[Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData).
Every ratio previously read off PRTS one page at a time - 固源岩, 酮凝集,
固源岩组, 酮凝集组, 糖, 糖组 - matches this table exactly, so the table is the
lookup and PRTS is the second opinion.

**Six lines have a single-ingredient upgrade chain. Only these convert.**

| Line | T1 white | -> | T2 green | -> | T3 blue | -> | T4 purple |
|---|---|---|---|---|---|---|---|
| rock 石头 | 源岩 | x3 | 固源岩 | **x5** | 固源岩组 | x4 | 提纯源岩 |
| ketone 酮 | 双酮 | x3 | 酮凝集 | x4 | 酮凝集组 | - | (酮阵列, mixed) |
| iron 铁 | 异铁碎片 | x3 | 异铁 | x4 | 异铁组 | - | (异铁块, mixed) |
| sugar 糖 | 代糖 | x3 | 糖 | x4 | 糖组 | - | (糖聚块, mixed) |
| polyester 酯 | 酯原料 | x3 | 聚酸酯 | x4 | 聚酸酯组 | - | (聚酸酯块, mixed) |
| device 装置 | 破损装置 | x3 | 装置 | x4 | 全新装置 | - | (改量装置, mixed) |

White to green is **x3 everywhere**. Green to blue is **x4 everywhere except
the rock line, which is x5**. That single exception is why each one gets looked
up rather than remembered - and it is the one that matters most, since the rock
line is what the daily loop burns.

LMD cost rises with tier: 100 for a green, 200 for a blue, 300 for a purple. It
never changes the item ratio and is not a constraint here.

The T4 column stops at 提纯源岩 because that is the only purple in the game made
from one ingredient (固源岩组 x4). Every other T4 mixes three different T3s, so
there is no ratio to fold and a purple stock stays a purple stock.

### Materials with no line at all - the count is the count

Nothing folds into these, and they fold into nothing. Stage drops, certificate
exchange or mixed recipes only:

> T3: RMA70-12, 凝胶, 化合切削液, 半自然溶剂, 扭转醇, 晶体元件, 液化高能气体,
> 炽合金, 环烃聚质, 电极单元, 研磨石, **类凝结核**, 褐素纤维, 转质盐组, 轻锰矿
>
> T4: RMA70-24, 三水锰矿, 五水研磨石, 切削原液, 固化纤维板, 异铁块, 手性屈光体,
> 改量装置, 晶体电路, 液化醚吸聚体, 炽合金块, 环烃预制体, 白马醇, 精炼溶剂,
> 糖聚块, 聚合凝胶, 聚能动力单元, 聚酸酯块, 转质盐聚块, 酮阵列

If a material being asked about is on this list, read one number and stop. If it
is in the six-line table, reading one number is a wrong answer.

## Not every material has a tier line - check the table before converting

The table above answers this without a page load: if the name is not in the six
lines, there is nothing to fold.

| Material | Tier | Line | Craftable? |
|---|---|---|---|
| 糖组 (sugar pack) | T3 | 代糖 -> 糖 -> **糖组** | yes, 糖 x4 + 200 LMD |
| 类凝结核 ("小罐茶") | T3 | **none** | **no** - certificate exchange and stage drops only |

类凝结核 is T3 like a blue, but [its PRTS page](https://prts.wiki/w/%E7%B1%BB%E5%87%9D%E7%BB%93%E6%A0%B8)
lists only what it *makes* (手性屈光体, 液化醚吸聚体), never what makes it - and
the game data agrees, with no `F_EVOLVE` formula producing it. So the
convert-lower-tiers step does not exist for it: its count is its count. The
game's own UI says the same thing: its detail panel offers 采购中心-凭证交易所,
while 糖组's offers 基建生产 / 加工站 可加工.

Getting this wrong in the other direction is easy: on 2026-08-22 the tile next
to 类凝结核 was assumed to be its green tier because it was a similar amber jar.
Tapping it showed **液化高能气体** - an unrelated material that merely looks
alike at tile size, and itself another no-line T3. Shape similarity is not a
tier line.

## Reading a depot stock - the blue number alone is never the answer

**Never report only the blue tier.** A depot request for a material means the
whole line: read white, green and blue, then fold upward. Reporting the blue
count on its own understates the real holding by however much sits in the lower
tiers, and that error runs one way only - it always looks scarcer than it is.

On 2026-08-22 糖组 was reported as "321" with white and green never opened. The
ketone line the same day showed why that is not a rounding error: 365 blue, but
937 green folded in on top of it, so the honest figure was 599 - **64% more
than the blue count**. A plan built on 321 would farm sugar that was already
sitting in the depot.

Two materials, and only two, are exempt:

| Material | Treatment | Why |
|---|---|---|
| 固源岩 (green rock) | **count as zero** | spent daily by the 搓玉 loop - it is fuel in transit, not stock |
| 装置 | **count as zero** | same, permanently outrun by demand |

Everything else converts. There is no third exception, and a material being
inconvenient to find in the depot is not one.

## Converting a stock into "how many blues is that"

Fold white into green first, then green into blue, at that material's own rate:

```
blue_equivalent = blue + green/g2b + white/(g2b * w2g)
```

Worked from the depot readout of 2026-08-22:

| | white | green | blue | blue-equivalent |
|---|---|---|---|---|
| rock | (not read) | 162 | 569 | 569 + 162/5 = **601** |
| ketone | (not read) | 937 | 365 | 365 + 937/4 = **599** |
| sugar | (not read) | (not read) | 321 | **incomplete** - lower tiers never opened, see rule above |
| 类凝结核 | - | - | 157 | **157** - no line, nothing to fold in |

Read from the depot on 2026-08-22 evening. The rock line's green is listed for
completeness only; per the rule below it counts as zero.

**Do not add the crafting by-product into this.** The factory has a chance of
an extra item, but it is drawn at random from a wide pool, so the chance it
lands on the material being counted is close to zero. Its expected contribution
to "how many more do I need" is nil - treat it as if it did not exist. An
earlier note here said the by-product made real yield "slightly higher than the
converted figure"; that confused "produces something extra" with "produces more
of this".

## The green rock is not stock - it is fuel

The standing daily loop consumes it:

```
2 固源岩 + 1,600 LMD  ->  1 源石碎片      (factory, 1 hour)
2 源石碎片            ->  20 合成玉        (trading post)
```

1-7 is the cheapest 固源岩 stage per sanity, which is why it is the default
stage rather than something with a richer table.

**Operator's standing rule: count 固源岩 and 装置 as zero.** Whatever number
the depot shows for them is work-in-progress on its way into the factory, not a
reserve. The formula above is only valid for greens that nothing else spends -
applying it to 固源岩 turns fuel into imaginary blues and points planning at
the wrong stage.

## Look it up before looking at it

The order that works:

1. **This file first.** Tier, whether a line exists, which lower tiers to read,
   the exact ratio - the table above is the whole game's set, so no lookup is
   needed at all any more.
2. **PRTS second**, only for something the table cannot answer: drop stages,
   acquisition routes, event availability.
3. **The depot last**, only for the quantities - all of them, per the rule
   above, not just the blue one.

Doing it in the other order means recognising icons, which is the part I am
worst at (see below), and reading a detail panel that needs scrolling before it
shows every acquisition route.

**PRTS is reachable from here but not from the game machine.** Measured
2026-08-22: this Mac got 5/5 with 1.8-3.4 s; the game machine got **403
Forbidden** on all five attempts, in under 300 ms, with TCP 443 open and ping
at 63 ms / 0% loss. It is a server-side refusal for that address, not a network
problem and not distance. So look things up here; do not try to fetch reference
data from the machine.

## Reading the depot

MAA's cached figures are not live. Its `DepotData.json`, and the numbers its
UI shows next to event stages, are **the same cache** - not two sources
agreeing. It updates from stage drops only, so it **adds and never subtracts**;
after three months the green rock read 1,527 in cache against 162 in reality,
because every craft had been invisible to it.

Live numbers come from 小工具 -> 仓库识别, which walks the depot and rewrites
the cache with a fresh `syncTime`. See [OPERATIONS.md](OPERATIONS.md) for
driving that, or for reading the shelves directly over ADB.

## What I can and cannot recognise on sight

Worth being explicit, because it was overstated once.

I can tell a mineral chunk from a book from a chip, and I can read the quantity
printed on a tile. What I cannot reliably do is tell **which** mineral - 固源岩
and 异铁 and 装置 are all grey-brown polygons at that size. When the depot was
read on 2026-08-22 and two tiles were named as the rock line, the actual
evidence was that their numbers matched figures already known from the cache,
plus their being adjacent in a column. That is finding known answers on the
screen, not identifying icons.

So: to read a material off a screenshot, either have its expected magnitude in
hand first, or tap the tile and read the name from the detail panel. Do not
claim an icon was recognised when it was a number that was recognised.
