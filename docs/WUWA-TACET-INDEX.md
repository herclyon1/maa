# Wuthering Waves Tacet Suppression index map (incomplete, but the method works)

**Why this is needed**: OK-WW's `Which Tacet Suppression to Farm` stores nothing but an
**index number**, and it teleports by counting down the in-game list from the top
(`TacetTask.py:96` → `click_on_book_target`). **Nowhere in the whole OK-WW project is
any Tacet Suppression named** — I searched the full tree, and the string 无音区 appears
exactly once, in a language pack. Upstream's own UI is likewise just a numeric field,
described as `The Tacet Suppression number in the F2 list.` So whoever edits the config
from another machine has no idea what 1234 means. The user's own words, 2026-09-04:
「给我标数字，我怎么知道 1234 是什么东西呢？这不是在搞笑吗？」

## Which list the index counts

In game: **F2 → 素材获取 → left column 无音清剿**. The list is grouped by region, and
**the index = the position from the top, counting continuously across groups**.

This matches: OK-WW's `TacetTask.structure = [2, 5, 5, 7]`, and the first group
瑝珑·梦州 has exactly 2 entries, 19 across the four groups.

## The part already verified (read in game 2026-09-04 around 03:2x)

| Index | Region | Tacet Suppression | The two echo sets (icons) |
|---|---|---|---|
| 1 | 瑝珑·梦州 | 方掌西峰无音区 | white feather + red quadrangle |
| 2 | 瑝珑·梦州 | **玄幽东岳无音区** | **white feather + green swirl** |
| 3 | 索拉里斯之极·拉海洛 | 落日堤屿无音区 | blue snowflake + blue shield |
| 4 | 索拉里斯之极·拉海洛 | 冰原运输港无音区 | red gem + green crosshair |
| 5 | 索拉里斯之极·拉海洛 | 加拉尔冠阶无音区 | red gem + (not fully read) |

What the user wants is **index 2, 玄幽东岳无音区**; the "white set + green set" he
described matches the icons.

## Set → Tacet Suppression (picked out one by one with the in-game echo-set filter)

Selecting a set in the filter narrows the list to the Tacet Suppressions that drop it.
Verified:

| Echo set | Tacet Suppressions that drop it |
|---|---|
| 凝夜白霜 | 荒石高地无音区 Ⅰ、虎口山脉无音区 |
| 熔山裂谷 | 归墟港市无音区、荒石高地无音区 Ⅱ |
| 彻空冥雷 | 虎口山脉无音区、荒石高地无音区 Ⅱ |
| 啸谷长风 | 荒石高地无音区 Ⅰ |
| 雪落无声之愿 | 落日堤屿无音区 |
| 剪心辑梦之影 | 落日堤屿无音区 |
| 听唤语义之愿 | 冰原运输港无音区 |
| 羽落空尘之歌 | 方掌西峰无音区、玄幽东岳无音区 |
| 清邪荡煞之心 | 玄幽东岳无音区 |
| 冥途夜行之灯 | 方掌西峰无音区 |
| 长路启航之星 | 冰原运输港无音区、加拉尔冠阶无音区 |
| 斑驳粉饰之沫 | 加拉尔冠阶无音区 |

Inverted, Tacet Suppression → sets (two sets each, matching one-to-one the two icons on
the left of each row):

| Index | Tacet Suppression | The two echo sets |
|---|---|---|
| 1 | 方掌西峰无音区 | 羽落空尘之歌 ＋ 冥途夜行之灯 |
| 2 | **玄幽东岳无音区** | **羽落空尘之歌 ＋ 清邪荡煞之心** |
| 3 | 落日堤屿无音区 | 雪落无声之愿 ＋ 剪心辑梦之影 |
| 4 | 冰原运输港无音区 | 听唤语义之愿 ＋ 长路启航之星 |
| 5 | 加拉尔冠阶无音区 | 长路启航之星 ＋ 斑驳粉饰之沫 |
| — | 荒石高地无音区 Ⅰ | 凝夜白霜 ＋ 啸谷长风 |
| — | 荒石高地无音区 Ⅱ | 熔山裂谷 ＋ 彻空冥雷 |
| — | 虎口山脉无音区 | 凝夜白霜 ＋ 彻空冥雷 |
| — | 归墟港市无音区 | 熔山裂谷 ＋ (the other one still missing) |

Only the first four have an index — those are the positions from the top of the F2
list; the 今州 ones have not been counted yet.

Order of the sets in the filter dropdown (top to bottom, newer further down):
凝夜白霜、熔山裂谷、彻空冥雷、啸谷长风、浮星祛暗、沉日劫明、隐世回光、
轻云出月、不绝余音、……、奔狼燎原之焰、逆光跃彩之约、星构寻辉之环、
流金溯真之式、长路启航之星、斑驳粉饰之沫、听唤语义之愿、雪落无声之愿、
剪心辑梦之影、羽落空尘之歌、清邪荡煞之心、冥途夜行之灯。

## How to finish the rest: query Kurobbs, do not open the game

The table above was read screen by screen from game screenshots. That is slow, and the
icons were cut out of screenshots, so they always carry a black fringe. **All of this is
on Kurobbs, and plain curl reaches it.**

### The two endpoints that need no login

```
# List: catalogueId=1219 is 「合鸣效果」, 34 sets
curl -s -X POST https://api.kurobbs.com/wiki/core/catalogue/item/getPage \
  -H 'wiki_type: 9' --data 'catalogueId=1219&page=1&limit=60'

# Detail: entryId comes from each record in the list above
curl -s -X POST https://api.kurobbs.com/wiki/core/catalogue/item/getEntryDetail \
  -H 'wiki_type: 9' --data 'id=<entryId>'
```

The related `catalogue/config/getPage`, `getEntryDetailById` and `entry/detail` all
require a token (`{"code":220,"msg":"访问令牌不能为空"}`); **only the two above do not**.

### Icons

`content.contentUrl` in each list record is the icon: a native 76×76 transparent PNG,
and the image host `prod-alicdn-community.kurobbs.com` can be downloaded with plain
curl. That is where `SET_ICONS` in `web/app.js` came from.

For comparison, the other route: the Wuthering Waves wiki's
`wuwa.huijiwiki.com/wiki/Special:FilePath/<set name>图标.png` is a 128×128 transparent
image of better quality, **but curl always gets a Cloudflare challenge page from those
two domains** (6KB of HTML instead of a PNG — `file` says so immediately); changing the
UA or adding a Referer does not help. The only way is to fetch it inside the browser and
then find a way to move it back to this machine — a download pops the system save dialog
and needs a human click, POSTing to a local HTTP server is blocked by the page's CSP,
connecting straight to the CDN in reverse has no CORS headers, and writing to the
clipboard inside the sandbox never reaches the system clipboard. **Do not take this route
again; use Kurobbs.**

### Ordering

The order `getPage` returns **is the order of the in-game echo-set filter dropdown:
newest to oldest**. `SET_ICONS` is sorted oldest to newest, i.e. exactly its reverse.

Verified (consistent with what was measured in game), newest to oldest:

| Release version | Sets (newest to oldest) |
|---|---|
| 3.5 | 冥途夜行之灯、清邪荡煞之心、羽落空尘之歌 |
| ?  | **碎梦亡鬼之魇** |
| 3.3 | 剪心辑梦之影、雪落无声之愿 |
| 3.1 | 听唤语义之愿、斑驳粉饰之沫、长路启航之星 |

**「碎梦亡鬼之魇」 is an open question**: in the Kurobbs list it sits between 3.3 and 3.5,
but when the in-game echo-set filter dropdown was read on 2026-09-04 it was not recorded.
Whether one entry was missed in the reading, or it is simply not in that dropdown at all,
**has never been verified**. Until it is, do not use this ordering to derive any index —
the meaning of an index comes only from the registry, see memory `idmap-no-guessing`.

### Set → Tacet Suppression

`getEntryDetail` has a 「对应无音区」 field. Pulled on 2026-09-04:

| Set | 对应无音区 |
|---|---|
| 长路启航之星 | 冰原运输港无音区、加拉尔冠阶无音区、盲望之榻残象聚落、复生丘原残象聚落、陷足流川残象聚落 |
| 斑驳粉饰之沫 | 加拉尔冠阶无音区、复生丘原残象聚落、陷足流川残象聚落、盲望之榻残象聚落 |
| 听唤语义之愿 | 冰原运输港无音区 |
| 雪落无声之愿 | 落日堤屿无音区 |
| 剪心辑梦之影 | 落日堤屿无音区 |
| 碎梦亡鬼之魇 | empty on Kurobbs |
| 羽落空尘之歌 | empty on Kurobbs |
| 清邪荡煞之心 | empty on Kurobbs |
| 冥途夜行之灯 | empty on Kurobbs |

**The last four are 3.5 sets and nobody has filled that field in on Kurobbs yet** — this
is not a gap in the scraping. To get their mapping you have to go back into the game and
work backwards with the echo-set filter (pick a set in the top right; the list is reduced
to the Tacet Suppressions that contain it).

That is exactly how the hand-made table above was produced. Its conclusions are sound;
there is simply no need to redo the part that is already there.

---

# Forgery Challenge index map (read screen by screen in game 2026-09-04, complete)

`Which Forgery Challenge to Farm` is likewise just an index, counting the position from
the top of the **F2 → 素材获取 → 凝素领域** list. Each region has exactly 5, always
ordered 迅刀 / 音感仪 / 长刃 / 臂铠 / 佩枪.

| Index | Region | Name | Weapon material it drops |
|---|---|---|---|
| 1 | 瑝珑·梦州 | 陨翼云渊 | 迅刀 |
| 2 | 瑝珑·梦州 | 静灭云渊 | 音感仪 |
| 3 | 瑝珑·梦州 | 裂斩云渊 | 长刃 |
| 4 | 瑝珑·梦州 | 碎蚀云渊 | 臂铠 |
| 5 | 瑝珑·梦州 | 沉熄云渊 | 佩枪 |
| 6 | 索拉里斯之极·拉海洛 | 荒蓁旧殿 | 迅刀 |
| 7 | 索拉里斯之极·拉海洛 | 残照终课 | 音感仪 |
| 8 | 索拉里斯之极·拉海洛 | 灾逆旧殿 | 长刃 |
| 9 | 索拉里斯之极·拉海洛 | 虚诞终课 | 臂铠 |
| 10 | 索拉里斯之极·拉海洛 | 余烬终课 | 佩枪 |
| 11 | 黎那汐塔 | 赦罪庭园 | 迅刀 |
| 12 | 黎那汐塔 | 浸礼海渊 | 音感仪 |
| 13 | 黎那汐塔 | 赞颂庭园 | 长刃 |
| 14 | 黎那汐塔 | 祝祭海渊 | 臂铠 |
| 15 | 黎那汐塔 | 告解海渊 | 佩枪 |
| 16 | 瑝珑·今州 | 熔毁废都 | 迅刀 |
| 17 | 瑝珑·今州 | 旋雾之森 | 音感仪 |
| 18 | 瑝珑·今州 | 侵蚀废都 | 长刃 |
| 19 | 瑝珑·今州 | 流月之森 | 臂铠 |
| 20 | 瑝珑·今州 | 欲燃之森 | 佩枪 |

The dropdown on the phone page only offers **the 梦州 group** (that is the one actually
in use); the rest stay in this table for reference.
