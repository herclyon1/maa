# 基建「双指滑动到总览」失败的真因（2026-08-28 查实）

## 结论：上游已知 bug，已修，已在我们跑的版本里

**MAA issue [#17895]，修复提交 `b2fc6bf`（2026-08-26 16:51），
已确认是 `v6.17.0-beta.7` 的祖先提交（`compare` 返回 `behind_by=0`）。**
我们 08-28 晚班起跑 beta.7，当晚首次尝试即成功。

修复改了三处：

```cpp
// src/MaaCore/Controller/Controller.cpp
- CHECK_EXIST(m_controller, false);
- return m_controller->inject_input_event(event);
+ // 与 click/swipe 一致必须经 scale proxy，否则任务层的基准坐标未乘分辨率倍率直发设备
+ CHECK_EXIST(m_scale_proxy, false);
+ return m_scale_proxy->inject_input_event(event);
```

1. **捏合手势坐标没走缩放代理**——按 1280×720 的基准值直发给 1600×900 的设备，
   行程只有应有的 80%，所以缩放缩不到位。**这就是根因。**
2. `InfrastInfoTask.cpp`：单步瞬移 → 20 步插值（每步 25ms）+ 抬手前保持 100ms。
3. `resource/tasks/tasks.json`：`InfrastInfoZoomOutPointer1` 起点 `y 700 → 640`。

### 只影响非 720p 设备

缩放系数 = 设备宽 / 1280。我们 1600×900 → 1.25，捏合行程被砍掉 20%。
**原生 1280×720 的用户系数是 1.0，乘不乘一样，不会中招。**

所以「改模拟器分辨率能不能避免」的答案是：**能，但不需要**——
beta.7 已从根上修复，而 1600×900 在官方兼容表里是雷电「完美支持」的配置。
官方对分辨率的要求原文是「仅对 **720p 以上 16:9 分辨率**支持较好」
（`docs/zh-cn/manual/device/windows.md`），1600×900 完全在范围内。

### 不要再提 issue

已有 #17895，且已修复关闭。相关：#17913、#17926。

---

## 以下是当时的现场取证（保留，用于将来比对）

**结论：MAA 自身缺陷，不是我们的配置、不是模拟器分辨率、不是 beta 版本。**
每次失败后的重试都成功过，所以基建换班从未真正漏做。

## 现象

```
InfrastInfoTask | zoom gesture sent
InfrastInfoTask | no facility matched, attempt 1 / 2 / 3
[ERR] InfrastInfoTask | facility layout recognition failed after 3 attempts
```

## 历史成败（asst.log + asst.bak.log 全量）

| 时刻 | 首次尝试 | 版本 |
|---|---|---|
| 08-26 15:24:37 | ❌ → 15:27:54 重试 ✅ | beta.6 |
| 08-26 21:35:32 | ❌ → 21:38:55 重试 ✅ | beta.6 |
| 08-26 22:58:57 | ✅ | beta.6 |
| 08-27 09:08:02 | ✅ | beta.6 |
| 08-27 21:35:12 | ❌ → 21:38:55 重试 ✅ | beta.6 |
| 08-28 13:18:04 | ❌ → 13:23:56 重试 ✅ | beta.6 |
| 08-28 21:35:58 | ✅ | beta.7 |

**beta.6 首次成功 2/6，beta.7 只有 1 个样本。**
「beta.7 修好了」在统计上完全不成立——33% 的成功率下抽中一次成功是常事。

## 机制（源码 `src/MaaCore/Task/Infrast/InfrastInfoTask.cpp`）

`InfrastFacilityImageAnalyzer::analyze()` 的返回是 `return !m_result.empty();`
——**九类设施在两种模板尺寸下一个都没匹配到，才会返回 false**。

模板是两个**离散固定尺寸**（`resource/tasks/tasks.json`）：

| 设施 | 正常模板 | 最小模板 | 阈值 |
|---|---|---|---|
| 制造站 | 201×96 | 70×64 | 0.90 |
| 贸易站 | 199×93 | 71×63 | 0.90 |
| 会客室 | 95×83 | 60×43 | 0.95 |

MAA 自己的注释已经写明这个失败模式：

> A pinch may advance only one zoom level. When the first gesture leaves the
> overview at an intermediate scale, waiting cannot make the fixed-size normal
> or mini templates match; pinch again before retrying.

## 实测（拿 MAA 自己的模板对失败帧做匹配）

失败帧：`D:\ark\maa\debug\infrast\facility_layout\*_raw.png`（1280×720）

| 帧 | 设施 | 正常模板 | 最小模板 | 阈值 |
|---|---|---|---|---|
| 08-28 | 制造站 | 0.499 | **0.814** | 0.90 |
| 08-28 | 贸易站 | 0.509 | 0.788 | 0.90 |
| 08-28 | 会客室 | 0.540 | 0.719 | 0.95 |
| 08-27 | 制造站 | 0.497 | **0.805** | 0.90 |

多尺度扫描：画面里制造站实际约 82×39，**卡在 201×96 与 70×64 之间**。

两天的数字几乎相同（0.805 / 0.814），是同一个稳定的中间缩放态；
离阈值只差 0.09，所以表现为间歇性——捏合到位就过，差一档就 0.81。

## 已排除

* **分辨率**：LDPlayer9 1600×900 / DPI 240 / 16:9，asst.log 无分辨率告警。
* **触控模式**：`ConnectSettings.TouchMode = MiniTouch`，支持多指；
  日志是 `zoom gesture sent` 而非 `unsupported`（源码里不支持多指会打后者）。
* **捏合落点**：`(980,180)→(650,350)` 与 `(300,640)→(630,370)`，
  在失败帧上两点都落在空白格背景，没打在设施卡上。
* **版本**：见上表。

## 影响

`NumOfTrade 0` 这类错值**不影响换班**：`Infrast.DefaultInfrast = user_defined`，
房间遍历由自定义排班表驱动。08-28 晚班 `NumOfTrade 0` 那轮，
实际处理的房间是 `Trade=[0,1,2,3] Mfg=[0,1,2,3,4] Power=[0,1,2] Dorm=[0,1,2,3,4]`，
与正常各晚完全一致。（真正没做的长这样：08-23 09时 `Trade=[] Mfg=[]`。）

代价只是失败那轮多花约 5 分钟重试。

## 决定性对比：成功帧 vs 失败帧（宿舍，同模板同 ROI）

| 帧 | ×1.00 得分 | 最佳尺度 | 阈值 |
|---|---|---|---|
| 08-28 失败 `facility_layout` | 0.787 ❌ | ×1.07 → 0.988 | 0.90 |
| 08-27 失败 `facility_layout` | 0.752 ❌ | ×1.08 → 0.992 | 0.90 |
| 08-27 成功那轮 `enter_facility` | **0.964 ✅** | ×1.02 → 0.972 | 0.90 |
| 08-26 成功那轮 `enter_facility` | **0.964 ✅** | ×1.02 → 0.972 | 0.90 |

**成功时画面正好落在模板原生尺度；失败时大 7~8%。**
所以失败帧不是「已经缩到最小仍然对不上」，而是**捏合没缩到位，还差最后一档**。
（制造站模板在成功帧上也只有 0.85——它本来就不是靠制造站过的，
宿舍 0.964 才是把 `analyze()` 拉过线的那个。别用制造站下结论。）

**分辨率无关**：成功帧和失败帧都出自同一台 1600×900 模拟器、同样降采样到 1280×720。
MAA 官方要求原文是「仅对 **720p 以上 16:9 分辨率**支持较好」
（`docs/zh-cn/manual/device/windows.md`），1600×900 完全在范围内；
雷电在官方表里是「完美支持」。**改分辨率不解决这个问题。**

## 雷电截图增强模式：开着的，而且生效（别再怀疑）

配置 `ConnectSettings.Extras.LDPlayer.IsEnabled = True`，运行时实证（asst.log 21:31）：

```
Loading library[libname=D:\LD-MRFZ\LDPlayer9\ldopengl64]
[ld_inst_index_=1000] [ld_pid_=8340]
LDExtras cost 24 ms
The fastest way is LDExtras , cost: 24 ms
```

**注意别误读**：紧邻上方那几行 `screencap | busybox nc` / `gzip -1` / `screencap -p`
是 MAA 在 `Try to find the fastest way to screencap` 阶段**挨个测速**，
不是在用 adb 截图。测完选的是 LDExtras（24ms，adb 各法 238/261/496ms）。
2026-08-28 我就是把测速读成了「在用 adb」，还断言「增强模式没开」，两处都错。

截图通道是雷电直取的高速通道、画面干净（成功帧宿舍 0.964），
**所以那 7~8% 是游戏内缩放没到位，不是截图糊。**

## 复发率

首次尝试 7 次里失败 4 次（约 57%），**会复发**；但 4 次失败后的重试 **4/4 全部成功**，
代价只是那一轮多花约 5 分钟。

## 修法（未执行，等用户定）

| 方案 | 做法 | 风险 |
|---|---|---|
| A 不动 | 靠 MAA 自己重试自愈 | 无。每次多花约 5 分钟 |
| B 提 issue | 把本文的匹配得分给上游：捏合幅度不足 / 建议加尺度容差或增加重试次数 | 无。见效慢 |
| C 本地改捏合坐标 | 改 `resource/tasks/tasks.json` 的 `InfrastInfoZoomOutPointer0/1`，加大起点间距、缩小终点间距 | **高**：① MAA 启动时跑 `ResourceIntegrityChecker`（08-28 晚班「Integrity check passed, 9302 file(s) verified」），改动可能被判失败；② `tasks.json` 会被 OTA 更新覆盖 |

推荐 **A + B**。C 在整改前不要做。
