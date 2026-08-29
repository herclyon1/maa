# 三个游戏的辅助程序对 Mac 的兼容性

2026-08-29 查证。结论：**想在 Mac 上跑「自动剧情」，一个都没有。**

## 第一层：游戏本身就没有官方 Mac 客户端

| 游戏 | 官方 macOS 客户端 |
|------|------------------|
| 原神 | 没有。只能靠 PlayCover 装 iOS 版（仅 Apple Silicon）、或 CrossOver / Whisky 跑 PC 版 |
| 鸣潮 | 没找到官方 Mac 客户端 |
| 终末地 | PC 是 Windows，另有安卓 / iOS 端 |

非官方途径跑网游本身就有封号风险，这一点各家教程自己都写了。

## 第二层：辅助程序

| 游戏 | 工具 | 有没有自动剧情 | 有没有 Mac 包 | 怎么控制游戏 |
|------|------|--------------|-------------|-------------|
| 原神 | BetterGI（babalae/better-genshin-impact） | 有（自动对话、自动跳过） | **没有**。官方快速上手页原文：「BetterGI 只支持 Windows 系统」，要求 Win10+ 64 位 | 截 Windows 窗口 + Win32 注入输入 |
| 鸣潮 | 更好的鸣潮 BetterWW（babalae/better-wuthering-waves） | **有，而且是主打功能**——仓库标题就是「后台自动剧情」 | **没有**。v0.12 的 release 只有 `.exe` 和 `.7z` | 同上 |
| 鸣潮 | OK-WW（ok-oldking/ok-wuthering-waves） | 日常流程里有对话跳过 | **没有**。v3.6.6 的 release 全是 `win32` 包 | 同上 |
| 终末地 | MaaEnd | 没有专门的自动剧情，主要是日常 | **有**。v2.26.0 带 `macos-aarch64.dmg` 和 `macos-x86_64.dmg`，还有 Linux 包 | Win32 前台（只在 Windows）**或 ADB**（安卓模拟器/真机） |

## 为什么只有 MaaEnd 有 Mac 包

这三家的其他工具都是同一个路子：**截 Windows 游戏窗口 + 用 Win32 API 注入键鼠**。
这套 API 在 macOS 上根本不存在，所以移植不是「懒得做」，是做不了。

MaaEnd 走了另一条路——**ADB 连安卓端**，这条路本身跨平台，所以它顺手就出了
macOS 和 Linux 包。它的 README 只写了「PC 端 (Win32 前台) 与安卓端 (ADB)」，
没提 macOS，但 release 里确实有 dmg。

## 但 MaaEnd 这条路对我们没用

1. 在 Mac 上它只能走 ADB，也就是必须跑**安卓版终末地**，
   要么真机要么模拟器。Apple Silicon 上安卓模拟器的选择非常有限。
2. **它本来就没有自动剧情。** 它做的是日常。

## 结论

**自动剧情在 Mac 上是零选项。** 三个有自动剧情的工具（BetterGI、BetterWW、OK-WW）
全是 Windows 独占；唯一出 Mac 包的 MaaEnd 恰好没有自动剧情。

**真正该做的是反过来想。** 2026-08-29 我们花了一下午证明：
从 Mac 远程驱动游戏，瓶颈根本不是平台兼容性，是**一次操作 30~40 秒的往返延迟**
（见 [PLAY-MANUAL.md](PLAY-MANUAL.md)）。寻路基本等于 0。

而 **BetterWW 的「后台自动剧情」正是我们today做不到的那件事，
它在乌鲁木齐那台 Windows 机器上是原生能跑的，延迟为零。**

所以路线是：Windows 机器当执行端、Mac 当控制端——也就是现在这套。
要自动剧情就在那台机器上装 BetterWW，不要试图搬到 Mac 上。

封号风险照旧：这些都是第三方工具，库洛和米哈游都有权封号。
