# 卡池数据源

三个游戏的卡池倒计时/预告分别从哪里取数,以及为什么这么选。
核实日期:2026-08-31。

## 结论速查

| 游戏 | 当前池 | 下期预告 | 要不要 token |
|---|---|---|---|
| 明日方舟 | PRTS `卡池一览/限时寻访` | 一图流前端仓库(人工维护) | 否 |
| 终末地 | 森空岛 API | 官方版本公告(跨版本才退回一图流) | 当前池要,预告不要 |
| 鸣潮 | 库街区 wiki 首页 API | 官方游戏内公告 | 否 |

## 明日方舟

- 当前池:PRTS `api.php?action=parse` 取 `卡池一览/限时寻访` 的 wikitext。
  注意 PRTS 只认 curl 默认 UA,**浏览器 UA 会被 403**。

  **只读这一页。** 2026-08-31 核对:`卡池一览/常驻标准寻访/2026` 是
  干员轮换池,表格结构不同(序号/寻访页面/开启时间,没有池名),
  解析出来恒为 0 条;而且里面每个干员——提丰、引星棘刺、逻各斯、
  鸿雪、衡沙——都能在限时寻访里追到更早的首发。轮换池不会有新人。
- 下期预告:`Arknights-yituliu/frontend-v2-plus` 仓库的
  `src/utils/gachaScheduleOptions.js`。

  ```
  https://raw.githubusercontent.com/Arknights-yituliu/frontend-v2-plus/main/src/utils/gachaScheduleOptions.js
  ```

  纯人工维护(提交记录全是人写的 `fix:` / `update:`,无机器人、无定时任务)。
  字段 `accuracyFlag: false` 表示这条是**预测排期**而非官宣,展示时要带不确定标记。
  当前两条都是预测:P3R联动 09-04、感谢庆典 11-01。

## 终末地

- 当前池:森空岛 API,需要 `SKLAND_TOKEN`(见 CONFIG)。
  `dotType == "label_type_up"` 的才是 UP,角色名要再查 `item/info`。
- 下期预告(**本版之内**):官方公告聚合口,免 token:

  ```
  https://game-hub.hypergryph.com/bulletin/v2/aggregate?lang=zh-cn&platform=Windows&channel=1&type=0&code=endfield_5SD9TN&hideDetail=0
  ```

  `data.list[]` 里 title 为「版本更新说明」的那条,正文在 `data.html`。
  和鸣潮是一个路数——整版上下半一次给全:

  ```
  ■ 全新干员
  6星干员【诀】【梨诺】
  ■ 全新寻访及申领
  1.「临渊望北」特许寻访 · ... 6星干员【诀】获取概率提升 ...
  3.「晨星于此闪耀」特许寻访 · ... 6星干员【梨诺】获取概率提升 ...
  ```

  「全新干员」那一节天然不含复刻,是判首发的依据;池名靠
  「X」特许寻访 到下一个之间那段里的「6星干员【Y】获取概率提升」对上。

  **判「下一期」不能用「已公布但不在开」**:本版上半开完了也满足这个条件,
  照那个判据会把上一期当成下一期报出去。公告是按时间顺序列的,
  要取在开的那位**之后**的(`upcoming()`)。

- 下期预告(**跨版本**,本版两半都开完时才退到这里):
  `Arknights-yituliu/ef-frontend-v1` 仓库的
  `custom/core/gacha/data/pool_info_table.json`。

  ```
  https://raw.githubusercontent.com/Arknights-yituliu/ef-frontend-v1/main/custom/core/gacha/data/pool_info_table.json
  ```

  同样是纯人工维护,一个人(yamasakura)每隔几周手改一次,十几条记录。
  字段:`poolName` / `character` / `poolStart` / `poolEnd` / `version`。

  **时刻以森空岛为准,不以这个文件为准。** 2026-08-31 对过:一图流写
  梨诺池 09-02 12:00 结束,森空岛 `poolEndAtTs=1788300000` 换算是
  09-02 06:00。前者是手填的,后者是官方接口。这个文件只用来取
  「下一期叫什么、大概什么时候」,精确时刻走森空岛。

  另外 `chars[].name` 在 char-pool 里是**空的**,角色名必须拿
  `pcLink` 里的 `gameEntryId` 再查一次 `item/info`;
  `dotType == "label_type_up"` 才是 UP,其余是陪跑的。
  同一响应里还有 `europePool*` 字段,那是别的服,不要用。
  **不要去爬 ef.yituliu.cn 的 `_nuxt/*.js` 分块**——数据就是这个文件编译进去的,
  直接读源仓库既稳定又不会因为构建产物改名而失效。

## 鸣潮

两个接口都不需要 token,固定三个 header 即可:

```
wiki_type: 9
source: h5
referer: https://wiki.kurobbs.com/
```

### 当前池 + 倒计时

```
POST https://api.kurobbs.com/wiki/core/homepage/getPage
```

`data.contentJson.sideModules[]` 里找 title 含「唤取」的模块:

- `角色活动唤取` / `武器活动唤取`,各自 `content.tabs[]` 是并行的两个池
- 池子起止时间:`tab.countDown.dateRange` → `["2026-08-20 11:00", "2026-09-10 09:59"]`
  (爬虫惯例是给首尾分别补 `:00` / `:59` 凑成秒)
- 池名:`tab.name`
- 角色名:取 `tab.imgs[0].linkConfig.entryId`,再查

  ```
  POST https://api.kurobbs.com/wiki/core/catalogue/item/getEntryDetail
  Content-Type: application/x-www-form-urlencoded
  id=<entryId>
  ```

  返回 `data.name`。**`imgs` 后三项在所有 tab 里是同一组通用条目,只有第一项是角色。**

同一模块的 `版本活动` 给出版本级活动的起止,可用来推版本结束时间。

### 下期预告

```
GET https://aki-gm-resources-back.aki-game.com/gamenotice/G152/<hash>/zh-Hans.json
```

hash 会随版本变,从 `555me/game-CDN-List` 的 `data/ww/game/notice.json` 里能拿到当前值。

`game[]` 里找标题形如「N.N版本内容说明」的那条,`content` 是带 HTML 的公告全文。
其中「✦全新角色✦」一节把**整个版本上下半的全新 5 星一次性列全**,格式固定:

```
5星共鸣者「景燃」（热熔 | 长刃）
...
※可通过[身赴三途]角色活动唤取获得。
```

也就是说版本更新当天就能拿到三周后下半池的角色和池名。
这一节天然只含全新角色、不含复刻,正好对上「只要全新角色」的口径。

## 试过但不用的路

- **`iaoongin/GachaClock`** —— 带 GitHub Actions 的卡池倒计时爬虫,思路可借鉴
  (鸣潮那部分的接口就是从它源码里看来的),但仓库 2026-05 起停更,
  `spider/data/ww/` 最新只到 4 月,**数据本身不能用**。
- **`anemone9/Game_Update_Dashboard`** —— `prisma/seed.js` 里确实有下期角色,
  能用来交叉验证,但是 ★0 的个人看板、纯散文摘要、两周手动刷一次,不能当数据源。
- **鸣潮个人 token(库街区登录态)** —— 上面两个接口都不需要,不要为了卡池去要用户的 token。
