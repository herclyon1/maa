# Banner data sources

Where the banner countdown / next-banner preview for each of the three games is taken from,
and why that source was chosen. Verified 2026-08-31.

## Quick reference

| Game | Current banner | Next banner | Token needed |
|---|---|---|---|
| 明日方舟 | PRTS `卡池一览/限时寻访` | the yituliu frontend repo (hand-maintained) | No |
| 终末地 | Skland API | official version bulletin (falls back to yituliu only across versions) | Yes for the current banner, no for the preview |
| 鸣潮 | Kuro Bbs wiki homepage API | official in-game bulletin | No |

## 明日方舟

- Current banner: PRTS `api.php?action=parse`, taking the wikitext of `卡池一览/限时寻访`.
  Note that PRTS only accepts curl's default UA — **a browser UA gets a 403**.

  **Read this page only.** Checked 2026-08-31: `卡池一览/常驻标准寻访/2026` is the operator
  rotation banner, its table has a different structure (index / banner page / opening time,
  no banner name), and parsing it always yields 0 entries; besides, every operator in it —
  提丰, 引星棘刺, 逻各斯, 鸿雪, 衡沙 — can be traced back to an earlier debut in the
  limited-time banners. A rotation banner never carries a new operator.
- Next banner: `src/utils/gachaScheduleOptions.js` in the
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

- Next banner (**across versions**, fallen back to only when both halves of the current version
  have already run): `custom/core/gacha/data/pool_info_table.json` in the
  `Arknights-yituliu/ef-frontend-v1` repository.

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
