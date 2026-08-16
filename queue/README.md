# 待办配置

改这个文件里的东西，游戏机器下次开机时会自己读到并应用，然后微信通知你。

**改完必须把 `version` 加一**，否则机器认为没有变化，什么都不会做。

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
