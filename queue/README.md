# 待办配置

改这个文件里的东西，游戏机器下次开机时会自己读到并应用，然后微信通知你。

**改完必须把 `version` 改大**，否则机器认为没有变化，什么都不会做。

格式是 `年月日 + 两位序号`：今天第一次改写 `2026081701`，同一天再改写 `2026081702`。
推送里会显示成「08-17 第2次」。

为什么不直接写日期字符串：这个值要用来判断「是不是比机器上那份新」，
而 raw.githubusercontent 是 CDN，可能回一份几分钟前的旧副本。
整数比大小不会出错，日期字符串在跨月的时候会。

## 怎么写一条指令

```json
{"action": "maaend_option", "task": "任务名", "option": "选项名", "case": "取值"}
```

`task` / `option` / `case` 用的都是 MaaEnd 自己的内部名，不是界面上的中文。
写错了不会造成损害——机器会拒绝执行并在微信里告诉你正确的取值有哪些。

按选项类型，字段不同：

| 选项类型 | 用哪个字段 | 例子 |
|---|---|---|
| 单选 select | `case` | `"case": "OperatorEXP"` |
| 开关 switch | `value` | `"value": false` |
| 多选 checkbox | `cases` | `"cases": ["ProtocolSpaceScheduleMonday"]` |
| 输入框 input | `values` | `"values": {"SupplyPlanLimit_CAST_DIE": 80}` |

再加 `"enabled": true/false` 可以顺便开关整个任务。

同一批里的所有指令**要么全部生效，要么一条都不生效**——协议空间的选项彼此依赖，
只落地一半会让机器刷一个谁都没要的东西。

## 明日方舟

```json
{"action": "set_stage",    "value": "CE-6"}
{"action": "set_medicine", "value": 2}
```

## 换终末地刷什么（最常用）

```json
{"action":"sanity_plan","tab":"OperatorProgression","line":"OperatorEXP","rewards_set":"RewardsSetA"}
```

`tab` 选哪一栏，`line` 选哪条线，`rewards_set` 选 A 组还是 B 组：

| tab | line | A 组掉 | B 组掉 |
|---|---|---|---|
| OperatorProgression 干员养成 | OperatorEXP 干员经验 | 高级认知载体、初级认知载体 | 高级作战记录 |
| | Promotions 干员进阶 | 协议圆盘组 | 协议圆盘 |
| | SkillUp 技能提升 | 协议棱柱组 | 协议棱柱 |
| | T-Creds 钱币收集 | — | — |
| WeaponProgression 武器养成 | WeaponEXP 武器经验 | — | — |
| | WeaponTune 武器进阶 | 重型强固模具 | 强固模具 |
| CrisisDrills 危境预演 | AdvancedProgression1–5 | — | — |

**写进的是 AUTO-MAS 的配置，不是 MaaEnd 的**——MaaEnd 那份每次运行都会被覆盖，
改了等于没改。详见 `docs/05-踩过的坑.md`。
