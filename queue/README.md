# 待办配置

这个目录里有两个可编辑文件，用途不同：

- **config.json**（本页主角）：给游戏机的指令，机器下次开机自取并应用，微信通知你。
- **watchdog.json**：开机监督的配置，给 GitHub Actions 读（不是给机器读）。
  `pause_until` 写到哪天就静默到哪天（含当天）——**要调试机器、让它整晚开着，
  先把这个日期改到调试结束那天**，否则「该关机还在线」会半夜给你告警。
  `enabled: false` 则整个监督停用。改完即生效，不用改 version。

改 config.json 里的东西，游戏机器下次开机时会自己读到并应用，然后微信通知你。

**改完必须把 `version` 改大**，否则机器认为没有变化，什么都不会做。

**另外两个字段建议一起写上**（都是给手机推送用的，不影响执行）：

```json
{
  "version": 2026082101,
  "name": "换刷 1-7",
  "note": "TO-5 活动 08-22 结束，换回常驻关卡。",
  "commands": [ ... ]
}
```

- `name`：这次改动的**短名字**，会直接变成推送标题「⚙️ 配置已更新：换刷 1-7」。
  不写就只有干巴巴的「配置已更新」。
- `note`：一句话说明，推送正文里原样显示。

推送里还会自动带上**应用时间（双时区）**和版本号，正文中的改动会翻译成人话
（`刷取关卡：TO-5 → 1-7`，而不是 `/59da8762-.../Info/Stage`）。

格式是 `年月日 + 两位序号`：今天第一次改写 `2026081701`，同一天再改写 `2026081702`。
推送里会显示成「08-17 v2」。

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

## 跳过某天

```json
{"action": "skip_today", "queue": "新队列", "day": "2026-08-21"}
```

**务必带 `day`**：机器是开机才收指令的，晚上排的"今天跳过"到第二天早上才被收到，
不带日期就会跳错天。日期过期时机器会拒绝并告诉你。

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
改了等于没改。详见 [docs/CONFIG.md](../docs/CONFIG.md)（英文）。
