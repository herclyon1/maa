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
