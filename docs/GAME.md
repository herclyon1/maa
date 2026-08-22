<title>Game knowledge</title>

# Game knowledge

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

## Crafting ratios - do not assume they are uniform

| Product | Costs | Verified |
|---|---|---|
| 固源岩 (green rock) | 源岩 **x3** + 100 LMD | [PRTS](https://prts.wiki/w/%E5%9B%BA%E6%BA%90%E5%B2%A9) |
| 酮凝集 (green ketone) | 双酮 **x3** + 100 LMD | [PRTS](https://prts.wiki/w/%E9%85%AE%E5%87%9D%E9%9B%86) |
| 固源岩组 (blue rock) | 固源岩 **x5** + 200 LMD | [PRTS](https://prts.wiki/w/%E5%9B%BA%E6%BA%90%E5%B2%A9%E7%BB%84) |
| 酮凝集组 (blue ketone) | 酮凝集 **x4** + 200 LMD | [PRTS](https://prts.wiki/w/%E9%85%AE%E5%87%9D%E9%9B%86%E7%BB%84) |

**White to green is 3 for both lines. Green to blue is 5 for rock and 4 for
ketone.** That asymmetry is the whole reason to look each one up rather than
apply a remembered rate. Assuming a flat 4 was already wrong once here, on
2026-08-22, and it was wrong in the direction that changes which stage to farm.

## Not every material has a tier line - check before converting

**Look this up on PRTS first, before touching the game.** It is faster than
navigating the depot, and it answers a question the depot cannot: whether the
material can be crafted at all.

| Material | Tier | Line | Craftable? |
|---|---|---|---|
| 糖组 (sugar pack) | T3 | 代糖 -> 糖 -> **糖组** -> 糖聚块 | yes, 糖 x4 + 200 LMD |
| 类凝结核 ("小罐茶") | T3 | **none** | **no** - certificate exchange and stage drops only |

类凝结核 is T3 like a blue, but [its PRTS page](https://prts.wiki/w/%E7%B1%BB%E5%87%9D%E7%BB%93%E6%A0%B8)
lists only what it *makes* (手性屈光体, 液化醚吸聚体), never what makes it. So
the whole convert-lower-tiers step does not exist for it: its count is its
count. The game agrees - its detail panel offers 采购中心-凭证交易所, while
糖组's offers 基建生产 / 加工站 可加工.

Getting this wrong in the other direction is easy: on 2026-08-22 the tile next
to 类凝结核 was assumed to be its green tier because it was a similar amber jar.
Tapping it showed **液化高能气体** - an unrelated material that merely looks
alike at tile size. Shape similarity is not a tier line.

## Sugar line

| Product | Costs | Verified |
|---|---|---|
| 糖 (green) | 代糖 **x3** + 100 LMD | [PRTS](https://prts.wiki/w/%E7%B3%96) |
| 糖组 (blue) | 糖 **x4** + 200 LMD | [PRTS](https://prts.wiki/w/%E7%B3%96%E7%BB%84) |

Same 3 / 4 shape as the ketone line. Still not something to assume - the rock
line is 3 / **5**.

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
| sugar | (not read) | (not read) | 321 | at least 321 |
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

1. **PRTS first.** Tier, whether it can be crafted, what the line is, the exact
   ratio. One page load answers all of it.
2. **Then the depot**, only for the quantity.

Doing it the other way round means recognising icons, which is the part I am
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
