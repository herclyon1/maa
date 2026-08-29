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

## BetterWW 到底能做什么（查源码确认，不是看简介）

**它只做剧情，不做日常。** 仓库里 `GameTask` 下只有三个功能目录：
`AutoSkip`（跳剧情）、`AutoPick`（自动拾取）、`GameLoading`（识别读条）。
没有体力、周本、声骸、悬赏、深渊——那些是 OK-WW 的活。

**没有自动寻路。** 整个仓库里没有任何寻路、走路、路径录制回放的代码。

### 「后台」是怎么做到的

两件事凑起来：

1. **截图认窗口句柄，不认前台。** `Fischless.GameCapture` 实现了三种：
   `BitBlt`、`DwmSharedSurface`、`Graphics`（Windows Graphics Capture）。
   都是对着游戏窗口的 HWND 截，窗口被挡住、不在前台都能截到。

2. **输入走 `PostMessage`，不走 `SendInput`。**
   `AutoSkipTrigger.cs` 里调的是 `_simulator.KeyPressBackground(...)`
   和 `skipRa.BackgroundClick()`，底层是 `PostMessageSimulator`——
   直接往游戏窗口的消息队列里投消息，不需要窗口有焦点，
   也不会抢走你正在用的鼠标键盘。

3. **认按钮靠模板匹配**（`SkipButtonRo`、`NotPromptAgainButtonRo` 这些图片资源），
   不是 OCR。所以它对分辨率和滤镜很敏感：
   只支持 16:9、推荐 1920x1080 窗口化、不许开 HDR 和显卡滤镜、要管理员权限。
   环境要求 Windows 10 64 位 + .NET 8。

### 这跟我们 wingui.sh 的做法差在哪

我们的 `wingui.sh` 用 `keybd_event` / `mouse_event`——那是**全局前台输入**，
必须把游戏切到前台、会抢鼠标，而且要靠计划任务绕到 session 1，
一次往返 30~40 秒。

BetterWW 是**在那台机器本地、对着窗口句柄发消息**，延迟接近零，
而且不抢焦点。这两者不是同一个量级的东西。

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

## 补充：Mac 上不用虚拟机跑 Windows 程序，有办法但这件事上没用

2026-08-29 查证。

### 不用虚拟机的路子确实存在

| 方案 | 状态 |
|------|------|
| **CrossOver 26**（2026-02 发布） | Wine + Apple GPTK 4，Intel 和 Apple Silicon 都支持，不装 Windows、不要 Windows 授权。商业软件 |
| **Whisky** | **已停止维护**，作者自己让大家转 CrossOver。老装的还能用，但没有更新和支持 |
| Apple Game Porting Toolkit | 苹果自己的 D3D→Metal 翻译层，CrossOver 26 里已经打包了 |
| 虚拟机（Parallels / VMware / UTM） | 跑 Windows 11 ARM，靠 Windows 自带的 x86 模拟跑 x86 程序 |

### 但鸣潮这条链在两个地方各断一次

**第一断：游戏本身在 Wine 下根本起不来。**
鸣潮用的是库洛的反作弊（ACE 的改版）。实测结论是
Whisky 和 Game Porting Toolkit 都会被反作弊挡住，游戏启动不了。
Linux/Proton 那边是同样的问题。

**第二断：就算游戏能跑，BetterWW 也接不上。**
它靠的是 `DwmSharedSurface` / Windows Graphics Capture 截窗口，
再用 `PostMessage` 往那个 HWND 发消息。这几个 API 在 Wine 里基本没实现，
而且它必须和游戏在**同一个 Wine prefix** 里才可能看到对方的窗口句柄。

**Mac 上唯一能玩鸣潮的路是 PlayCover**——在 Apple Silicon 上原生跑 iOS 版。
但那是个 iOS 应用，**根本没有 Win32 窗口**，BetterWW 连能发消息的对象都不存在。

### 结论

这件事上 Mac 不是「慢一点」或者「麻烦一点」，是**结构上走不通**。
Windows 机器必须留着当执行端。
