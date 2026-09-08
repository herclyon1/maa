# The four 选剑演武 failures on 08-28 are four different failure points

**Do not treat them as one problem.** Every item below has a log line number or a
screenshot behind it.

## Task configuration (`mxu-MaaEnd.json` → `instances[0].tasks[14]`, enabled=True)

| UI label | Key | Our value |
|---|---|---|
| 模式 | `TrialOfSwordmancyMode` | `Daily`（每日选剑演武） |
| 数据溢出处理 | `TrialOfSwordmancyOverflow` | `None`（不接受溢出） |
| 启用自动战斗 | `TrialOfSwordmancyAutoFight` | yes |
| 每次战斗前传送回复血量 | `TrialOfSwordmancyRecoverBeforeBattle` | no |
| 自动战斗设置 | `AutoFightSetting` | yes |
| ├ 自动切换低血量干员到后台 | `AutoFightHealthDangerousSwitch` | yes |
| ├ 自动闪避 | `AutoFightDodge` | yes |
| │  └ 兼容模式 | `AutoFightDodgeCompat` | no |
| ├ 自动锁定目标 | `AutoFightLockTarget` | yes |
| ├ 使用排轴 | `AutoFightAxis` | no |
| ├ 保留技能能量 | `AutoFightReserveSkillLevel` | 1 |
| └ 自动打断敌人蓄力 | `AutoFightBreakAccumulatingPower` | yes |

The other modes: `Coating`（刷镀层）, `Farm25`（刷25点，无奖励、不自动战斗）.
Overflow settings: `None` / `Once`（至多1次）/ `Twice`（至多2次）.
The official description says 「开启数据溢出可以取得更高的预期收益，但**自动战斗大概率失败**」.

**None of these 12 items is misconfigured.** The 7 sub-items under
`AutoFightSetting` are its own subtree, and the same set also appears on
`tasks[13] ProtocolSpace`.

## The four failures

| # | Time | Cards drawn | Combat | Failure point |
|---|---|---|---|---|
| 1 | 14:00:45→14:01:53 | **none** | **none** | never reached the card table |
| 2 | 14:05:51→14:08:04 | yes | full 45 seconds, exited normally | **post-combat wrap-up recognition** |
| 3 | 14:17:20→ | yes | full | same as above |
| 4 | 21:04 (my manual single run) | none | none | **never navigated to the venue** |

### Round 1: it never even reached the card table

The whole task is 4 lines:

```
14:00:45.289  任务开始: 🗡️选剑演武
14:01:06.992  [ERR] TemplateMatcher __WhiteConfirmButtonType1…
14:01:06.994  [ERR] TemplateMatcher __WhiteConfirmButtonType1…
14:01:53.628  任务失败: 🗡️选剑演武
```

`EnterTrialMenuSuccess = Or(DrawCard, EnemyCard5)` never matched; `EnemyCard5`
scored 0.286 (threshold 0.7).

### Round 2: it finished the fight and stuck on the wrap-up

```
14:07:03.959  进入战斗场景
14:07:04.228  共 4 名干员参战     (skills / dodges / concerto / ultimates all fired)
14:07:49.411  退出战斗场景
14:07:54.554  获得 武陵调度券 ×320000   <- this number is not trustworthy, see below
14:08:04.217  任务失败: 🗡️选剑演武
```

In the framework log `maafw.bak.2026.08.28-14.16.02.869.log`, over the
14:07:45–14:08:06 window, it polls three wrap-up nodes over and over, all
`Node.Recognition.Failed`:

```
TrialOfSwordmancyFightSuccess              73×
TrialOfSwordmancyReEnterTrialMenuSuccess  126×
TrialOfSwordmancyRewardExhausted          126×
```

**It printed no failure reason at all** — it has a string of its own,
`trialofswordmancy.recognition_failed =「选剑演武：识别失败」`, and that never fired.

### Round 4 (the 21:04 single run): the character is out in the open world

`debug/on_error/2026.08.28-21.04.13.353_TrialOfSwordmancyMain.png`: the character
is standing in the open world outside 源石研究园, the top left shows 「探索」 mode
and the daily task guidance, and it **never got to the 演武场 at all**.

## ⚠️「获得 武陵调度券 ×N」 is not evidence that a reward was received

The wording comes from `locales/go-service/zh_cn.json`:

```
ims.add_item_found   获得 %s ×%d
ims.item_current     当前 %s：%d
ims.sync_item_found  识别到 %s：%d
```

The numbers are OCR'd. **Every 调度券 reading is untrustworthy**:

```
08-14  ×2790000  ×3380000  ×835000  ×1970000  ×5030000
08-25  ×49800  ┐ same number on both days
08-26  ×49800  ┘
08-28  ×320000 (round 2)  ×320000 (round 3)  <- same number in both rounds
```

Other items over the same period read normally: `行动资历 ×1150`, `协议棱柱 ×5`,
`高级作战记录 ×1`. On top of that, `nodes.json:14036` has a threshold check for
「识别武陵调度券是否溢出」, which means it is a capped stock — several million cannot
drop in one go.

**To decide whether today's runs are done, use the game's own words**: during the
21:04 single run it reported 「今日奖励次数已用尽」. Round 1 never got in, so the
attempts were consumed by rounds 2 and 3.

## Hypotheses already ruled out

* **Bad configuration** — all 12 items checked one by one, all correct, see the
  table above.
* **Too hard to beat** (the upstream author's suggestion) — rounds 1 and 4 had
  **no combat at all**, so it does not apply; rounds 2 and 3 ran the fight to the
  end and exited normally. The log does not record whether it won, so that part can
  be neither confirmed nor refuted.
* **Card draw failed** (the upstream author's suggestion) — round 1's log has
  **not a single hand or deck line**; it never reached the card table.

## Cross-check against upstream issues (searched MaaEnd/MaaEnd on 2026-08-28)

We are running **v2.26.0-rc.1** (the `version` in `D:\ark\maaend\interface.json`).

### Pathfinding failures (round 1, and the 21:04 single run) — **issues exist, still unfixed**

| # | State | Version | Title |
|---|---|---|---|
| [#5034] | **open** | v2.25.0-beta.2 | 选剑演武-寻路异常：「传送至传送点后朝向错误跳下下一层 导致任务失败」 |
| [#5061] | **open** | v2.25.0-beta.3 | 寻路与作战bug：「选剑演武作战失败报错」 |
| #5021 / #5040 | open | v2.25.x | 多任务寻路失败合并反馈 |
| #4930 / #4987 / #4365 | closed | v2.2x | 选剑演武寻路失败 / 偶发性寻路失败 |

#5034's description matches our 21:04 `on_error` screenshot: **the character stops
in the open world and never reaches the 演武场**. Both open issues were filed
against v2.25.x, and we hit it on v2.26.0-rc.1 too — **this class reproduces.**

### Post-combat wrap-up recognition failure (rounds 2 and 3) — **no matching issue found**

Searched the keywords `选剑演武` / `TrialOfSwordmancy` / `选剑演武 识别`; there is no
选剑演武 fault issue at all after 08-20. The closed recognition ones
(#3968, #4418, #4432「选剑演武：识别失败」) have different symptoms —
**they print that `选剑演武：识别失败` line, and ours printed not one word of it.**

So this shape — combat finished, `FightSuccess` / `ReEnterTrialMenuSuccess` /
`RewardExhausted` polled 100+ times each, all `Recognition.Failed`, and no failure
text of any kind — currently has **no existing issue**.

**But this is one day of data, on an rc build**, so observe one more day before
deciding whether to report it.
