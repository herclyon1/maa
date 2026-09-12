# Banner data sources

Where the banner countdown / next-banner preview for each of the three games is taken from,
and why that source was chosen. Verified 2026-08-31.

## Quick reference

| Game | Current banner | Next banner | Token needed |
|---|---|---|---|
| 明日方舟 | PRTS `卡池一览/限时寻访` | official site news (「…寻访即将开启」); else "not announced" + the yituliu limited-banner projection as a far-off note | No |
| 终末地 | Skland API | official version bulletin within the version; official site news (「X」特许寻访说明, ~1 day ahead) across versions; else "not announced" | Yes for the current banner, no for the preview |
| 鸣潮 | Kuro Bbs wiki homepage API | official in-game bulletin within the version; the wiki character catalogue's teaser badge across versions | No |

## Rules that the 2026-09-12 report broke (and the fixes)

- **Reruns are never "the next banner."** The Endfield bulletin lists 重构寻访 (reruns)
  with opening times; `_endfield` used to pick the earliest future pool and label it
  （复刻）. Now only debuts qualify.
- **A far-off prediction is not "the next banner."** Yituliu's Arknights table is the
  input to a pull-saving calculator and only carries *limited* banners; its next entry
  (感谢庆典 11-01) was shown as the preview while the banner after 09-18 was simply not
  announced. The line now says 「下一池官方还没公告」 and appends the projection as
  「远期 …（一图流预测，未官宣）」. The Endfield yituliu table is no longer read at all.
- **Wiki entry names carry whitespace.** `getEntryDetail` for 景燃 returned `" 景燃"`;
  compared raw against the bulletin it was "not a debut" and the running banner vanished
  from the report. Names are stripped.
- **A version is not 42 days.** 3.6 ran 08-20 → 09-29 (40 days); the version end for 鸣潮
  is the running banners' end (all of a version's banners end on update day). The +42
  guess remains only as a fallback when no banner is running.

## Supervision (2026-09-12, third pass) - what stops an invented line from going out

The user: 「你对卡池信息这一块没有监管工具防止你瞎编或者数据出错吗？」 Three layers,
all in `banners.py` (`Trace`), exercised by `tests/test_banners.py::_supervision`:

1. **Provenance.** Every value that reaches the section is recorded as
   `game｜what｜URL or field｜value` and written to `state/banners/YYYY-MM-DD.json` with
   the rendered text and the check results. `python -m ark_relay banners` (on the
   machine: `winrun.sh --py` a stub calling `cmd_banners`) prints the section, the
   sources and any withheld line; exit 1 when something was withheld or a source failed.
2. **Two official sources per running banner**, compared field by field (name,
   characters, start, end) and reported in a 核对 footer under the section:
   - 明日方舟: PRTS row vs the official site's 「…限时寻访即将开启」 post
   - 鸣潮: Kuro wiki homepage tab vs the in-game notice's own 「[X]角色活动唤取」 post
     (`recommend[]` in the gamenotice JSON: 5星角色「X」 and 活动时间 span)
   - 终末地: Skland char-pool vs the version bulletin's 开放时间 line (closing clock)
   A disagreement prints ✗ with both values; a missing second source prints ✗ too.
   First live run flagged 终末地 12:59 vs 11:59 - the Mac converting the Skland
   timestamp in Tokyo time; `parse_endfield` now converts in the server zone.
3. **The date gate** (`gate_preview`): a 预告 line may contain a date only if a source
   assigned it to a *start* (news post opening time, bulletin pool opening, maintenance
   end), or an end when the line says 结束, or a rule/prediction when the line says
   按规律/预测. Anything else is withheld: the report shows 「⚠️ 这一行没通过来源核对，
   已扣下」 and the original goes to the log and the trace. This is exactly what the
   morning's 「09-18 03:59 之后开」 would have hit.

What it cannot catch: a wrong *wording* that carries no date (「先后等版本公告」).
That is why the notes are now restricted to what a fetched field says, and the tests
pin the exact text for the 2026-09-12 inputs.

## What the preview line says when nothing is announced (2026-09-12, second pass)

The first pass of the day still printed 「09-18 03:59 之后开（还有 5 天）」 for Arknights
and 「先后和池名等版本公告」 for 鸣潮 - both invented. Rules now:

- **Arknights**: a new banner does not follow the current one back to back (gaps between
  debut banners in the PRTS table: 22-39 days). With nothing announced the line carries
  **no date**: 「下一池官方还没公告，官方惯例开池前约一周公告（上两池分别提前 6 天、7 天）；
  远期 …」. The lead is measured from the official site's last two debut posts
  (`arknights_banner_posts`, reruns 「…即将复刻开启」 skipped), not asserted.
- **鸣潮 / 终末地**: a new version always opens with a new banner, so the version date
  is a real date: 「09-29 版本更新后开（还有 16 天）」. Who: the wiki teaser badge names
  the characters; the order is **not** claimed from the badge. The official site's
  article index (`ArticleMenu.json`, below) shows a 「共鸣者战斗演示 | X」 / 「共鸣者「X」PV」
  a few days before X's banner - in 3.5 and 3.6 the demo order matched the banner order
  (秧秧·玄翎 07-06 → 07-10, 穗穗 07-26 → 08-13; 清宵 08-17 → 08-20, 景燃 09-06 → 09-10),
  so once a demo is up the line adds 「官网已发「X」的战斗演示（MM-DD）」 - the fact, not a
  derived opening date (the lead ranged 3-18 days).

## 鸣潮: the official site's article index

`https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/ArticleMenu.json`
is what mc.kurogames.com/main/news renders: a JSON list with `articleId`, `articleTitle`,
`articleType` (51 = 新闻: PVs, combat demos; 52 = 公告), `createTime`, `startTime`. The
per-article body is `json/G152/zh/article/<id>.json`; the 「版本资讯 | 3.x版本」 post
(two days before the update) is images only, so the order of the two halves is still not
machine-readable before the 版本内容说明 lands on update day.

## 鸣潮: who the next version's characters are (wiki teaser badge)

`POST /wiki/core/catalogue/item/getPage` with `catalogueId=1105&page=1&limit=100`
(the 共鸣者 catalogue; same three headers). Each record's `content` carries the corner
badge the wiki page draws: `showTeaserIcon` true with `showTeaserIconNum` 1 = 新,
2 = 预告, 3 = 复刻, valid inside `teaserDateRange`. Read 2026-09-12: 景燃 1, 绯雪 3,
莫宁 3, 心 2, 锁暝 2. Old entries keep stale flags with expired ranges (赞妮 3 until
2026-04-29), so the range check is mandatory. The badge names the characters only;
which half and which banner name come from the version bulletin on update day.

Tag filtering (`tagIds=`) on that endpoint is ignored, and every tag/filter endpoint
(`getFilterTags`, `config/getTags`, `getTree`) answers 「访问令牌不能为空」 - the
badge is the only token-free signal.

## 终末地: the official site's banner notices

`https://endfield.hypergryph.com/news` has the same Next.js shape as the Arknights site
(`cid` / `title` / `displayTime` inside an escaped JSON string; articles at `/news/<cid>`).
「X」特许寻访说明 is posted about a day before the banner: cid 6097 「冬猎」特许寻访说明
on 09-01 for the 09-02 opening, body 「开放时间：「雪凇幽梦」版本开启后 - 2026/09/30
11:59」 and 「概率提升的6星干员为【提弗洛斯】」. "版本开启后" resolves to the end of
the maintenance window in the 「版本预下载与更新预告」 / 「版本更新说明」 post
(「维护时间 2026/09/02 06:00 - 2026/09/02 12:00」). Reruns are 「重构寻访」 posts, not
特许寻访, so they never match.

## 明日方舟

- Current banner: PRTS `api.php?action=parse`, taking the wikitext of `卡池一览/限时寻访`.
  Note that PRTS only accepts curl's default UA — **a browser UA gets a 403**.

  **Read this page only.** Checked 2026-08-31: `卡池一览/常驻标准寻访/2026` is the operator
  rotation banner, its table has a different structure (index / banner page / opening time,
  no banner name), and parsing it always yields 0 entries; besides, every operator in it —
  提丰, 引星棘刺, 逻各斯, 鸿雪, 衡沙 — can be traced back to an earlier debut in the
  limited-time banners. A rotation banner never carries a new operator.
- Next banner: the official site's 「…寻访即将开启」 post (`arknights_next_from_news`), then a
  PRTS row with a future start (time only). **Far-off projection only** (never presented as
  the next banner, 2026-09-12): `src/utils/gachaScheduleOptions.js` in the
  `Arknights-yituliu/frontend-v2-plus` repository.

  ```
  https://raw.githubusercontent.com/Arknights-yituliu/frontend-v2-plus/main/src/utils/gachaScheduleOptions.js
  ```

  Purely hand-maintained (the commit history is all human `fix:` / `update:` commits, no bots,
  no scheduled jobs). The field `accuracyFlag: false` marks an entry as a **predicted schedule**
  rather than an official announcement, and it must be displayed with an uncertainty marker.
  Both current entries are predictions: the P3R collaboration on 09-04 and the anniversary
  celebration on 11-01.

## 终末地

- Current banner: the Skland API, which needs `SKLAND_TOKEN` (see CONFIG).
  Only entries with `dotType == "label_type_up"` are the rate-up ones, and the character name
  has to be looked up separately through `item/info`.
- Next banner (**within the current version**): the official bulletin aggregation endpoint,
  no token needed:

  ```
  https://game-hub.hypergryph.com/bulletin/v2/aggregate?lang=zh-cn&platform=Windows&channel=1&type=0&code=endfield_5SD9TN&hideDetail=0
  ```

  In `data.list[]`, take the entry whose title is 「版本更新说明」; the body is in `data.html`.
  It works the same way as 鸣潮 — the whole version, both halves, is published at once:

  ```
  ■ 全新干员
  6星干员【诀】【梨诺】
  ■ 全新寻访及申领
  1.「临渊望北」特许寻访 · ... 6星干员【诀】获取概率提升 ...
  3.「晨星于此闪耀」特许寻访 · ... 6星干员【梨诺】获取概率提升 ...
  ```

  The 「全新干员」 section by its nature contains no reruns, which is what makes it usable for
  deciding what is a debut; banner names are matched by pairing 「X」特许寻访 with the
  「6星干员【Y】获取概率提升」 that appears before the next one starts.

  **"Announced but not currently running" must not be used to decide what "the next one" is**:
  once the first half of the current version has ended it also satisfies that condition, and
  that test would report the previous banner as the next one. The bulletin is listed in
  chronological order, so take the one **after** the banner that is currently running
  (`upcoming()`).

- Next banner (**across versions**): the official site's 「X」特许寻访说明 (see above).
  **No longer read (2026-09-12)**: `custom/core/gacha/data/pool_info_table.json` in the
  `Arknights-yituliu/ef-frontend-v1` repository - kept here only as the record of why not.

  ```
  https://raw.githubusercontent.com/Arknights-yituliu/ef-frontend-v1/main/custom/core/gacha/data/pool_info_table.json
  ```

  Also purely hand-maintained: one person (yamasakura) edits it by hand every few weeks, a
  dozen or so records. Fields: `poolName` / `character` / `poolStart` / `poolEnd` / `version`.

  **Skland is the authority for times, not this file.** Compared 2026-08-31: yituliu says the
  梨诺 banner ends 09-02 12:00, while Skland's `poolEndAtTs=1788300000` converts to
  09-02 06:00. The former is typed in by hand, the latter is the official endpoint. This file
  is used only for "what the next banner is called and roughly when"; exact times come from
  Skland.

  Also, `chars[].name` is **empty** in char-pool, so the character name has to be looked up
  again through `item/info` using the `gameEntryId` inside `pcLink`;
  only `dotType == "label_type_up"` is the rate-up one, the rest are just along for the ride.
  The same response also carries `europePool*` fields, which belong to a different server —
  do not use them.
  **Do not scrape the `_nuxt/*.js` chunks of ef.yituliu.cn** — the data there is just this file
  compiled in, and reading the source repository directly is both more stable and immune to
  build artifacts being renamed.

## 鸣潮

Neither endpoint needs a token; three fixed headers are enough:

```
wiki_type: 9
source: h5
referer: https://wiki.kurobbs.com/
```

### Current banner + countdown

```
POST https://api.kurobbs.com/wiki/core/homepage/getPage
```

In `data.contentJson.sideModules[]`, find the modules whose title contains 「唤取」:

- `角色活动唤取` / `武器活动唤取`, and within each of them `content.tabs[]` holds the two
  parallel banners
- Banner start/end times: `tab.countDown.dateRange` → `["2026-08-20 11:00", "2026-09-10 09:59"]`
  (the scraper convention is to append `:00` / `:59` respectively to make full seconds)
- Banner name: `tab.name`
- Character name: take `tab.imgs[0].linkConfig.entryId`, then look it up

  ```
  POST https://api.kurobbs.com/wiki/core/catalogue/item/getEntryDetail
  Content-Type: application/x-www-form-urlencoded
  id=<entryId>
  ```

  which returns `data.name`. **The last three items of `imgs` are the same generic set in every
  tab; only the first one is the character.**

The `版本活动` entry in the same module gives the start and end of version-level events, which
can be used to infer when the version ends.

### Next banner

```
GET https://aki-gm-resources-back.aki-game.com/gamenotice/G152/<hash>/zh-Hans.json
```

The hash changes with each version; the current value can be obtained from
`data/ww/game/notice.json` in `555me/game-CDN-List`.

In `game[]`, find the entry whose title has the form 「N.N版本内容说明」; `content` is the full
bulletin text with HTML. Its 「✦全新角色✦」 section lists **every new 5-star of both halves of
the version at once**, in a fixed format:

```
5星共鸣者「景燃」（热熔 | 长刃）
...
※可通过[身赴三途]角色活动唤取获得。
```

In other words, on the day the version drops we already have the character and banner name for
the second-half banner three weeks out. This section by its nature contains only new characters
and no reruns, which matches the "new characters only" rule exactly.

## Routes tried and rejected

- **`iaoongin/GachaClock`** — a banner-countdown scraper with GitHub Actions; the approach is
  worth borrowing (the 鸣潮 endpoints above were read out of its source), but the repository
  has been unmaintained since 2026-05 and `spider/data/ww/` only goes up to April, so
  **the data itself is unusable**.
- **`anemone9/Game_Update_Dashboard`** — `prisma/seed.js` does contain the next characters and
  can be used for cross-checking, but it is a ★0 personal dashboard, prose summaries only,
  hand-refreshed once every two weeks; not usable as a data source.
- **A personal 鸣潮 token (Kuro Bbs login session)** — neither endpoint above needs one; do not
  ask the operator for a token just to get banner data.

## How to fetch those two hand-maintained tables on GitHub

Measured 2026-08-31 on the game machine (Urumqi) against the same file:

| Route | Result |
|---|---|
| `raw.githubusercontent.com` | works, but **33.2 seconds** |
| `fastly.jsdelivr.net/gh/...` | 2.8 seconds |
| `cdn.jsdelivr.net/gh/...` | 4.6 seconds |
| `gh-proxy.com/https://raw...` | 3.8 seconds |
| `raw.gitmirror.com` | completely unreachable |
| `ghfast.top` | completely unreachable |

Those 33 seconds on raw exceed the timeout in the code, which is why the 明日方舟 and 终末地
previews **came and went**. `gh_raw()` orders the mirrors as in the table above and uses raw
only as the last fallback. Do not add the two unreachable ones back.
