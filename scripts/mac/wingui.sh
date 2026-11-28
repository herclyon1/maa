#!/usr/bin/env bash
# 看游戏机的**真实屏幕**，以及对游戏窗口发按键。
#
# 为什么需要它：ssh 进游戏机拿到的是一个**非交互窗口站**，那里没有桌面。
# 2026-08-26 我在那上面调 GetCursorPos，拿到 err=1459
# （ERROR_REQUIRES_INTERACTIVE_WINDOWSTATION），差点把它误判成「游戏机锁屏了」，
# 顺着这条错线索排查了二十分钟。跨会话拿窗口句柄和内存同样不可信——
# 那天 `Client-Win64-Shipping` 明明有 331 个线程，MainWindowHandle 却报 0。
#
# 唯一可靠的办法是让代码**跑在 session 1 里**：注册一个 /it（交互式）计划任务，
# 由它截屏 / 发键，结果写文件再取回来。这就是这个脚本干的事。
#
# 还有一件当天学到的事：OK-WW 自己存的截图**会是旧帧**。
# 16:27 和 16:32 两张一模一样，看着像「游戏卡死」，其实是它对着一个被模态
# 弹窗挡住的画面反复识别失败。要判断现在到底什么样，只能用这里的 shot。
#
#   scripts/mac/wingui.sh shot [输出.png]     # 截真实屏幕
#   scripts/mac/wingui.sh key esc             # 对游戏窗口发 ESC（会先置前台）
#   ARK_GUI_PROC=Endfield wingui.sh click 1780 565   # 作用到别的游戏（默认鸣潮）
#   ARK_GUI_PROC=MAA wingui.sh shot                 # 操作 MAA 界面版（MAA 以管理员身份跑，所以计划任务要 /rl highest）
#   scripts/mac/wingui.sh key f2              # 打开传送目录
#   scripts/mac/wingui.sh key l               # 单个字母（鸣潮：L 开队伍界面）
#   scripts/mac/wingui.sh click 960 540       # 左键点一下（真实鼠标事件，游戏才认）
#   scripts/mac/wingui.sh launch [wuwa|'D:\\path\\to\\App.exe']  # 启动图形程序（必须从 session 1 起）
#   scripts/mac/wingui.sh launch 'D:\\ark\\maa\\MAA.exe -- --skip-startup-auto-run'  # 带参数
#   scripts/mac/wingui.sh scroll -3           # 滚轮，负数向下翻
#   scripts/mac/wingui.sh focus [out.png]     # 只把游戏拉到前台再截图（OK-WW 窗口会被压下去）
#
# 发键一律先 SetForegroundWindow：鸣潮失焦时照常渲染但**不收输入**，
# 这正是当天 `target_enemy failed` 的真因。
#
# 2026-11-19 夜里一次进游戏看界面踩了四个坑（时间都是游戏机的北京时间），这里都堵上了：
#  · **刷声骸在跑时不许动画面。** 那晚有人在刷的同时进游戏看界面，OK-WW 停了下来；
#    22:32:59 中继照规矩判「OK-WW 停了 6 分钟」，把它重开、拉回副本，还报了警。
#    除了只读的 shot，所有动作先读游戏机中继状态里的 queues.echo_farm：在刷就拒绝
#    （退出码 7），并打出先停、查完再续刷的两条 order-now.sh 原样命令。
#    确实要边刷边动，显式加 ARK_GUI_DURING_FARM=1。
#  · **launch wuwa 要带画质包参数。** 不带 `-krqlv=` 时 Wuthering Waves.exe 起不来游戏，
#    22:39、22:43 两次都这样，工具却照样回「已启动」。现在照 OK-WW 的读法
#    （它的 src/game_launcher.py）读启动器选的包，读不到用 hd，和 OK-WW 一样。
#    **别直接起 Client-Win64-Shipping.exe**：22:41 这样起，游戏弹
#    「The Game has crashed and will close / kuro: Use launcher to start game!」。现在直接拒绝。
#  · **launch 等结果的时间要够。** 远端起完游戏要等它出窗口，本地原来只按 35 秒等，
#    每次都报「没有产出结果」（退出码 3）。现在两头用同一个数（WUWA_LAUNCH_MAX）。
#    launch wuwa 等到游戏窗口真出来才算成；残留的崩溃弹窗先关掉；进程在但窗口是崩溃
#    弹窗的不算「已在运行」。
#  · **远端报了 ERR 就不许回 0。** 动作没做成（找不到进程、窗口没出来……）时退出码 6，
#    截图照样取回。
#
# 每次调用都在 ~/.cache/ark-relay/mac_actions.log 留一行（lib/mac-action-log.sh）。
set -euo pipefail
# 前置 Homebrew PATH 并锁定最新版 Python，防止非交互环境静默回退系统旧版
export PATH="${PATH}:/opt/homebrew/bin:/opt/homebrew/sbin"
MAC_PY="${MAC_PY:-/opt/homebrew/bin/python3}"
# Every call leaves one line in ~/.cache/ark-relay/mac_actions.log (lib/mac-action-log.sh).
# (`.` of a missing file ends a bash script, so it is looked for first: a copy of this script
# alone, as the tests make, still runs.)
ARK_ACTION_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/mac-action-log.sh"
if [ -f "$ARK_ACTION_LIB" ]; then
  # shellcheck source=lib/mac-action-log.sh
  . "$ARK_ACTION_LIB"; ark_action_log ${1+"$@"}
fi
# 第 1 层北京时间断电硬锁：08:40–08:45 严禁对游戏机发任何远程交互命令（RC=78）
ARK_PC_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/powercut-guard.sh"
if [ -f "$ARK_PC_LIB" ]; then
  # shellcheck source=lib/powercut-guard.sh
  . "$ARK_PC_LIB"
  ark_powercut_guard 1 "wingui.sh" || exit $?
fi

HOST="${ARK_HOST:?请先 export ARK_HOST=<游戏机 Tailscale IP>}"
USER_AT="Administrator@${HOST}"
PWSH='C:\Program Files\PowerShell\7\pwsh.exe'
REMOTE_PS='C:/ProgramData/ark-gui.ps1'
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ACTION="${1:-shot}"
ARG="${2:-}"

# 远端脚本。每次都推，省得判断它在不在、是不是旧版。
cat > "$TMP/ark-gui.ps1" <<'PS1'
# 在 session 1（有真实桌面）里干活。由交互式计划任务调起。
# 动作读 C:\ProgramData\ark-gui-cmd.txt，日志写 C:\ProgramData\ark-gui.txt，
# 截图一律落 C:\ProgramData\ark-gui.png。
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class ArkW {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint mapType);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
}
"@
$log = @()
$cmd = (Get-Content 'C:\ProgramData\ark-gui-cmd.txt' -Raw -ErrorAction SilentlyContinue).Trim()
$log += "cmd=$cmd"

if ($cmd -like 'launch*') {
  # 启动图形程序。必须从这里（session 1）起——从 ssh 那个非交互窗口站起会死。
  # 见 memory relay-runs-in-session-0。
  #
  # 只认两种参数：别名 wuwa（路径已核实过），或**完整 exe 路径**。
  # 不在这里内置终末地/MaaEnd 的路径——2026-08-28 我凭印象填了两条，
  # 事后 grep 发现那两条只存在于我自己刚写的这个文件里，是纯猜。
  # 路径由调用方从 AUTO-MAS 的 Game.Path 之类的真实来源取好再传进来。
  # 路径后面可以再跟启动参数，用 `--` 隔开：
  #   launch D:\ark\maa\MAA.exe -- --skip-startup-auto-run
  # MAA 必须带 --skip-startup-auto-run 起，否则一启动就自动开跑任务。
  $what = ($cmd -split '\s+', 2)[1]
  if (-not $what) { $what = 'wuwa' }
  $extra = @()
  if ($what -match '^(.*?)\s+--\s+(.*)$') {
    $what  = $Matches[1].Trim()
    $extra = $Matches[2].Trim() -split '\s+'
  }
  if ($what -eq 'wuwa') { $exe = 'D:\Wuthering Waves Game\Wuthering Waves.exe' }
  else { $exe = $what }

  if ($exe -match '(^|\\)Client-Win64-Shipping\.exe$') {
    # 2026-11-19 22:41: started directly, the game shows 「The Game has crashed and will
    # close / Fatal error ... kuro: Use launcher to start game!」 and goes away.
    $log += "ERR 别直接起 Client-Win64-Shipping.exe：游戏会弹「Use launcher to start game」然后崩。用 launch wuwa"
  } elseif ($exe -notmatch '^[A-Za-z]:\\') {
    $log += "ERR 不认识 '$what'。只接受别名 wuwa 或完整 exe 路径。"
  } elseif (-not (Test-Path $exe)) {
    $log += "ERR 找不到 $exe —— 路径不对就去核对，别硬猜。"
  } elseif ([IO.Path]::GetFileNameWithoutExtension($exe) -eq 'Wuthering Waves') {
    # 鸣潮单独走：进程名和 exe 名不一样（Client-Win64-Shipping），要带画质包参数，
    # 要等游戏窗口真的出来才算起好了。
    # 这一段整个包在 try 里：这里任何一处抛错都会让结果文件写不出来，wingui 空等满预算
    # 再报「没有产出结果」；抛错就写成一行 ERR。读进程属性也一样：进程刚退、或者查不了
    # （受保护）时读 ProcessName / MainWindowTitle 会抛，所以每个进程单独 try，只留读到的。
    try {
      $crash = '^The Game has crashed'      # the box's title, 2026-11-19 22:41 screenshot
      function Find-CrashBoxes {
        foreach ($p in @(Get-Process -ErrorAction SilentlyContinue)) {
          try {
            if ($p.MainWindowHandle -ne 0 -and $p.MainWindowTitle -match $crash) {
              [pscustomobject]@{ Id = $p.Id; Name = $p.ProcessName; Title = $p.MainWindowTitle; Hwnd = $p.MainWindowHandle }
            }
          } catch { }
        }
      }
      # 游戏窗口：Client-Win64-Shipping 的窗口，标题不空、不是崩溃框（OK-WW 认的标题是
      # 「鸣潮  」，UnrealWindow；刚起的一瞬间可能是没标题的过渡窗口，不算）。
      function Find-GameWindow {
        foreach ($p in @(Get-Process -Name 'Client-Win64-Shipping' -ErrorAction SilentlyContinue)) {
          try {
            if ($p.MainWindowHandle -ne 0 -and $p.MainWindowTitle -and $p.MainWindowTitle -notmatch $crash) {
              return [pscustomobject]@{ Id = $p.Id; Title = $p.MainWindowTitle }
            }
          } catch { }
        }
      }
      # 1. 残留的崩溃弹窗先关掉。22:41 那个框到 22:46 还在屏幕上，那时游戏进程早没了，
      #    框是别的进程挂着的；按「确定」等于发 WM_CLOSE。挂框的若是游戏本身，框关了它
      #    还不退，就结束它：框上写着 will close，它已经没法玩了。
      #    关完再查一遍：还有框就不起游戏，写 ERR——顶着旧框起，新游戏出窗口之前，
      #    下面等窗口时看到的框分不清是新崩的还是旧的。
      $boxes = @(Find-CrashBoxes)
      foreach ($b in $boxes) {
        [ArkW]::PostMessage($b.Hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null  # WM_CLOSE
        $log += "关掉残留的崩溃弹窗「$($b.Title)」（$($b.Name) pid $($b.Id)）"
      }
      if ($boxes.Count -gt 0) {
        Start-Sleep -Seconds 3
        # 按关框前记下的那份查，不重新找框：框一关，挂它的游戏进程就没有框了，重新找
        # 找不到它；它若赖着不退，下面会被当成「正在启动」白等 120 秒。
        foreach ($b in $boxes) {
          if ($b.Name -eq 'Client-Win64-Shipping') {
            try {
              if (Get-Process -Id $b.Id -ErrorAction SilentlyContinue) {
                Stop-Process -Id $b.Id -Force -ErrorAction Stop
                $log += "崩掉的游戏进程 pid $($b.Id) 框关了还不退，已结束"
              }
            } catch { $log += "WARN 结束崩掉的游戏进程 pid $($b.Id) 没成：$($_.Exception.Message)" }
          }
        }
        Start-Sleep -Seconds 2
      }
      $left = @(Find-CrashBoxes)
      if ($left.Count -gt 0) {
        $log += "ERR 残留的崩溃弹窗关不掉：" + (($left | ForEach-Object { "「$($_.Title)」$($_.Name) pid $($_.Id)" }) -join '；') +
                "。没有起游戏，先看截图"
      } else {
        # 2. 画质包：照 OK-WW src/game_launcher.py 的读法。先读启动器界面状态
        #    （<游戏目录的上一级>\kr_game_cache\platform_ui_state.bin，Base64 后每字节异或 0x63），
        #    再看游戏目录下 launcherDownloadConfig.json 是否只有一个包；都不行用 hd（OK-WW 也是）。
        #    调用方自己用 `-- -krqlv=xx` 给了就照用。
        if (-not ($extra -match '^-krqlv=')) {
          $pkg = $null; $how = ''
          $dir = Split-Path $exe
          $ui = Join-Path (Split-Path $dir) 'kr_game_cache\platform_ui_state.bin'
          try {
            if (Test-Path -LiteralPath $ui) {
              $raw = [Convert]::FromBase64String((Get-Content -LiteralPath $ui -Raw).Trim())
              $plain = [byte[]]@($raw | ForEach-Object { $_ -bxor 0x63 })
              $st = [Text.Encoding]::UTF8.GetString($plain).TrimStart([char]0xFEFF) | ConvertFrom-Json
              $active = $st.activeGameScope
              if ($active -and $active.gameIdentity -eq 'Aki' -and "$($active.bundleName)".ToLower() -in 'sd','hd','uhd') {
                $pkg = "$($active.bundleName)".ToLower(); $how = '启动器当前选的'
              } elseif ($st.recentGames -and "$($st.recentGames.Aki.bundleName)".ToLower() -in 'sd','hd','uhd') {
                $pkg = "$($st.recentGames.Aki.bundleName)".ToLower(); $how = '启动器最近一次的'
              }
            }
          } catch { $log += "WARN 启动器界面状态读不出：$($_.Exception.Message)" }
          if (-not $pkg) {
            try {
              $man = Get-Content -LiteralPath (Join-Path $dir 'launcherDownloadConfig.json') -Raw -Encoding UTF8 | ConvertFrom-Json
              $have = @($man.bundles.PSObject.Properties.Name | ForEach-Object { $_.ToLower() } |
                        Where-Object { $_ -in 'sd','hd','uhd' } | Select-Object -Unique)
              if ($have.Count -eq 1) { $pkg = $have[0]; $how = '下载清单里唯一的' }
            } catch { $log += "WARN launcherDownloadConfig.json 读不出：$($_.Exception.Message)" }
          }
          if (-not $pkg) { $pkg = 'hd'; $how = 'WARN 哪儿都读不到，照 OK-WW 的做法用' }
          $log += "画质包 $pkg（$how）"
          $extra = @("-krqlv=$pkg") + $extra
        }
        # 3. 已在运行＝游戏有窗口（见 Find-GameWindow）。进程在但还没窗口，
        #    多半是别人刚起的、正在启动：不重复起，等它出窗口。
        $up = Find-GameWindow
        $game = @(Get-Process -Name 'Client-Win64-Shipping' -ErrorAction SilentlyContinue)
        $t0 = Get-Date
        if ($up) {
          $log += "Client-Win64-Shipping 已在运行（窗口「$($up.Title)」），没有重复启动"
        } else {
          if ($game.Count -gt 0) {
            $log += "Client-Win64-Shipping 进程在（pid $($game[0].Id)）但还没有游戏窗口，不重复启动，等它出窗口"
          } else {
            Start-Process -FilePath $exe -ArgumentList $extra -WorkingDirectory (Split-Path $exe)
            $log += "已启动 $exe [" + ($extra -join ' ') + "]，最多等 __WUWA_LAUNCH_MAX__ 秒游戏窗口"
          }
          $win = $null; $box = $null
          while (((Get-Date) - $t0).TotalSeconds -lt __WUWA_LAUNCH_MAX__) {
            Start-Sleep -Seconds 2
            $win = Find-GameWindow
            $box = @(Find-CrashBoxes) | Select-Object -First 1
            if ($win -or $box) { break }
          }
          $secs = [int]((Get-Date) - $t0).TotalSeconds
          if ($box) {
            $log += "ERR 启动后 $secs 秒弹了崩溃框「$($box.Title)」（$($box.Name)），游戏没起来。截图里有框上的原文"
          } elseif ($win) {
            $log += "游戏窗口出来了（启动后 $secs 秒，「$($win.Title)」），再等 8 秒截图"
            Start-Sleep -Seconds 8
          } else {
            $log += "ERR 等了 $secs 秒游戏窗口也没出来，游戏没起来（别当成功）"
          }
        }
      }
    } catch {
      $log += "ERR 起鸣潮这段出错了：$($_.Exception.Message)"
    }
  } else {
    $proc = [IO.Path]::GetFileNameWithoutExtension($exe)
    if (Get-Process -Name $proc -ErrorAction SilentlyContinue) {
      $log += "$proc 已在运行，没有重复启动"
    } else {
      if ($extra.Count -gt 0) {
        Start-Process -FilePath $exe -ArgumentList $extra -WorkingDirectory (Split-Path $exe)
        $log += "已启动 $exe [" + ($extra -join ' ') + "]，等 __LAUNCH_WAIT__ 秒"
      } else {
        Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe)
        $log += "已启动 $exe，等 __LAUNCH_WAIT__ 秒"
      }
      Start-Sleep -Seconds __LAUNCH_WAIT__
    }
  }
} elseif ($cmd -ne 'shot') {
  # 发键之前必须把游戏拉到前台。鸣潮失焦时照常渲染但不收输入，
  # 不置前台的话按键全部落空，而且**没有任何报错**。
  #
  # 目标进程名从 C:\ProgramData\ark-gui-proc.txt 读，默认鸣潮。
  # 2026-08-28：这里原本写死 Client-Win64-Shipping，对终末地发点击时
  # 会直接走到「游戏进程不在，按键跳过」——**不报错、什么也没发生**。
  $proc = (Get-Content 'C:\ProgramData\ark-gui-proc.txt' -Raw -ErrorAction SilentlyContinue)
  if ($proc) { $proc = $proc.Trim() }
  if (-not $proc) { $proc = 'Client-Win64-Shipping' }
  $log += "proc=$proc"
  # 一个进程名下可能有好几个窗口：MaaEnd 和 OK-WW 都跑在 python.exe 上，
  # `Select-Object -First 1` 会随机切到另一个程序去。2026-08-29 想截 OK-WW
  # 的配置界面，拿到的是 MaaEnd 的窗口。所以支持 `title:xxx` 按窗口标题定位。
  if ($proc -like 'title:*') {
    $want = $proc.Substring(6)
    $p = Get-Process -ErrorAction SilentlyContinue |
         Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like "*$want*" } |
         Select-Object -First 1
    if ($null -eq $p) {
      $all = (Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } |
              ForEach-Object { $_.MainWindowTitle }) -join ' | '
      $log += "ERR 没有标题含「$want」的窗口。现有窗口：$all"
    }
  } else {
    $p = Get-Process -Name $proc -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $p) { $log += "ERR 进程 $proc 不在，按键跳过" }
  }
  if ($null -eq $p) {
  } else {
    $h = $p.MainWindowHandle
    $log += "hwnd=$h title=$($p.MainWindowTitle)"
    if ($h -ne 0) {
      [ArkW]::ShowWindow($h, 9) | Out-Null      # SW_RESTORE
      [ArkW]::SetForegroundWindow($h) | Out-Null
      Start-Sleep -Milliseconds 800
    } else { $log += 'WARN hwnd=0，没能置前台' }
    # 一次调用可以跑一串动作，用 ; 或换行隔开。
    # 为什么要这个：每次 wingui 调用都要建一个交互式计划任务再等结果，
    # 一个动作十几秒。要让模型驾驶游戏（走位、转视角、交互），一步一次往返
    # 根本不可用。一串动作压成一次往返之后，延迟才落到可接受范围。
    # seq 的子动作里按键是裸写的（f5），但外层命令行写的是 `key f5`。
    # 两种写法都收，否则来回切换时会写成 `key f5` 然后收到「不认识的动作」。
    $actions = @($cmd -split '[;\r\n]+' | ForEach-Object { $_.Trim() -replace '^key\s+', '' } |
                 Where-Object { $_ -ne '' })
    foreach ($one in $actions) {
    # click x y —— 鼠标左键点一下。游戏只认真实的鼠标输入，
    # 所以走 SetCursorPos + mouse_event，不用 SendKeys。
    if ($one -eq 'focus') {
      # 只把游戏拉到前台，不发任何按键。用来看被 OK-WW 窗口盖住的真实画面。
      $log += 'focus only'
      Start-Sleep -Milliseconds 800
    } elseif ($one -match '^scroll\s+(-?\d+)(?:\s+(\d+)\s+(\d+))?$') {
      # 滚轮。游戏里的长列表只能这么翻——没有滚轮就只能靠点滚动条，不可靠。
      # 滚轮事件发给光标底下那个控件，所以坐标必须能指定：终末地活动中心的
      # 列表在最左边，光标停在屏幕中央时滚的是右边的详情页，列表纹丝不动。
      $ticks = [int]$Matches[1]
      $sx = if ($Matches[2]) { [int]$Matches[2] } else { 960 }
      $sy = if ($Matches[3]) { [int]$Matches[3] } else { 600 }
      [ArkW]::SetCursorPos($sx, $sy) | Out-Null
      Start-Sleep -Milliseconds 200
      # 向下翻是负的滚轮增量，而 mouse_event 的第 4 个参数是 uint32。
      # 直接 [uint32](-480) 会抛「值超出 UInt32 范围」，任务当场崩掉、
      # 连结果文件都不写（2026-08-26 踩过）。要按补码转。
      # 注意别写成 -band 0xFFFFFFFF：PowerShell 把这个十六进制字面量当成
      # Int32 的 -1，按位与等于没做，照样溢出。老实加 2^32。
      $raw = [long]($ticks * 120)
      if ($raw -lt 0) { $raw += 4294967296 }
      $delta = [uint32]$raw
      [ArkW]::mouse_event(0x0800, 0, 0, $delta, [UIntPtr]::Zero)  # MOUSEEVENTF_WHEEL
      $log += "scrolled $ticks @ $sx,$sy"
      Start-Sleep -Milliseconds 1500
    } elseif ($one -match '^look\s+(-?\d+)\s+(-?\d+)$') {
      # 转视角。必须是**相对位移**：游戏读的是鼠标移动量，不是光标落点，
      # SetCursorPos 那种绝对定位在锁定光标的第一/第三人称视角里根本无效。
      # mouse_event 的 dx/dy 是 uint，负数要按补码转（和滚轮同一个坑）。
      $dx = [long]$Matches[1]; $dy = [long]$Matches[2]
      if ($dx -lt 0) { $dx += 4294967296 }
      if ($dy -lt 0) { $dy += 4294967296 }
      [ArkW]::mouse_event(0x0001, [uint32]$dx, [uint32]$dy, 0, [UIntPtr]::Zero)  # MOUSEEVENTF_MOVE
      $log += "look $($Matches[1]),$($Matches[2])"
      Start-Sleep -Milliseconds 120
    } elseif ($one -match '^hold\s+([a-z0-9])\s+(\d+)$') {
      # 按住不放走位。点一下（80ms）在游戏里几乎不产生位移，
      # 走路必须按住一段时间再松。
      $k = $Matches[1]; $ms = [int]$Matches[2]
      $vk2 = if ($k -match '[0-9]') { [int][char]$k } else { [int][char]$k.ToUpper() }
      $sc2 = [ArkW]::MapVirtualKey([uint32]$vk2, 0)
      [ArkW]::keybd_event([byte]$vk2, [byte]$sc2, 0x0, [UIntPtr]::Zero)
      Start-Sleep -Milliseconds $ms
      [ArkW]::keybd_event([byte]$vk2, [byte]$sc2, 0x2, [UIntPtr]::Zero)
      $log += "hold $k ${ms}ms"
    } elseif ($one -match '^(rdown|rup|ldown|lup)$') {
      # 按住鼠标键（有些游戏要按住右键才转视角，或长按左键蓄力）。
      $f = switch ($Matches[1]) {
        'ldown' { 0x0002 } 'lup' { 0x0004 } 'rdown' { 0x0008 } 'rup' { 0x0010 } }
      [ArkW]::mouse_event([uint32]$f, 0, 0, 0, [UIntPtr]::Zero)
      $log += "mouse $($Matches[1])"
      Start-Sleep -Milliseconds 80
    } elseif ($one -match '^wait\s+(\d+)$') {
      Start-Sleep -Milliseconds ([int]$Matches[1])
      $log += "wait $($Matches[1])ms"
    } elseif ($one -eq 'shot') {
      $log += 'shot（收尾时统一截）'
    } elseif ($one -match '^click\s+(\d+)\s+(\d+)$') {
      $x = [int]$Matches[1]; $y = [int]$Matches[2]
      [ArkW]::SetCursorPos($x, $y) | Out-Null
      Start-Sleep -Milliseconds 250
      [ArkW]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)   # LEFTDOWN
      Start-Sleep -Milliseconds 60
      [ArkW]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)   # LEFTUP
      $log += "clicked $x,$y"
      Start-Sleep -Milliseconds 1800
    } else {
      # 用 keybd_event 发**真实按键**，不要 SendKeys。
      # 2026-08-26 实测：SendKeys 的 {ESC} 能被鸣潮吃到，但字母键（L）完全没反应——
      # 游戏读的是原始输入，SendKeys 那套窗口消息它不认。
      $vk = switch -Regex ($one) {
        '^esc2?$'    { 0x1B }
        '^enter$'    { 0x0D }
        '^space$'    { 0x20 }      # 跳跃。动作游戏里没这个键等于缺一条腿
        '^shift$'    { 0xA0 }      # 冲刺/闪避
        '^tab$'      { 0x09 }
        '^f(\d+)$'   { 0x6F + [int]$Matches[1] }        # VK_F1 = 0x70
        '^[a-z]$'    { [int][char]($one.ToUpper()) }     # VK_A..VK_Z 就是大写 ASCII
        '^[0-9]$'    { [int][char]$one }                 # VK_0..VK_9 同理
        default      { $null }
      }
      if ($null -eq $vk) { $log += "ERR 不认识的动作: $one" }
      else {
        $sc = [ArkW]::MapVirtualKey([uint32]$vk, 0)
        [ArkW]::keybd_event([byte]$vk, [byte]$sc, 0x0, [UIntPtr]::Zero)          # down
        Start-Sleep -Milliseconds 80
        [ArkW]::keybd_event([byte]$vk, [byte]$sc, 0x2, [UIntPtr]::Zero)          # up (KEYEVENTF_KEYUP)
        if ($one -eq 'esc2') {
          Start-Sleep -Milliseconds 1200
          [ArkW]::keybd_event([byte]$vk, [byte]$sc, 0x0, [UIntPtr]::Zero)
          Start-Sleep -Milliseconds 80
          [ArkW]::keybd_event([byte]$vk, [byte]$sc, 0x2, [UIntPtr]::Zero)
        }
        $log += ("sent {0} (vk=0x{1:X2} sc=0x{2:X2})" -f $one, $vk, $sc)
        Start-Sleep -Milliseconds 2500      # 等界面动完再截，否则截到过渡帧
      }
    }
    }
  }
}

# The screen sleeps after 5 minutes and CopyFromScreen then returns the last frame
# drawn before it went dark - no error, just an old picture. `shot` is what CLAUDE.md
# names as the way to see the real screen, and it is used precisely when nothing has
# touched the machine for a while. On 2026-08-24 a frame frozen 27 minutes earlier
# was read as "the installer never started"; the taskbar clock in the image was the
# only clue, and a cropped game view has no clock in it at all.
# A zero-distance relative mouse move wakes the display without moving the cursor.
[ArkW]::mouse_event(0x0001, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 700

$b   = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g   = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save('C:\ProgramData\ark-gui.png', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
$log += "shot $($b.Width)x$($b.Height) $(Get-Date -Format 'HH:mm:ss')"
$log -join "`n" | Set-Content 'C:\ProgramData\ark-gui.txt' -Encoding utf8
PS1

# 远端起程序等多久、本地等结果等多久，用同一组数。2026-11-19 之前远端写死等 45 秒，
# 本地预算却只按动作串算（launch 一个动作 = 35 秒），launch 每次都假超时（退出码 3）。
WUWA_LAUNCH_MAX=120   # launch wuwa：最多等这么久让游戏窗口出来
LAUNCH_WAIT=45        # launch 别的程序：起完固定等这么久
sed -e "s/__WUWA_LAUNCH_MAX__/$WUWA_LAUNCH_MAX/g" -e "s/__LAUNCH_WAIT__/$LAUNCH_WAIT/g" \
  "$TMP/ark-gui.ps1" >"$TMP/ark-gui.ps1.new" && mv "$TMP/ark-gui.ps1.new" "$TMP/ark-gui.ps1"
if grep -q '__[A-Z_]*__' "$TMP/ark-gui.ps1"; then
  echo "✋ wingui.sh 自己的毛病：远端脚本里还有没替换的占位符" >&2; exit 2
fi

# 刷声骸在跑时读出来的样子：一段说明，含停和续刷的原样命令；没在刷就什么也不打；
# 状态读不出就退出 1。
FARM_PY='
import json, sys
from datetime import datetime, timedelta, timezone
t = sys.stdin.read().lstrip("\ufeff").strip()
try:
    rec = (json.loads(t).get("queues") or {}).get("echo_farm")
except (ValueError, AttributeError):
    sys.exit(1)
if not isinstance(rec, dict) or not rec:
    sys.exit(0)
until = str(rec.get("until") or "")
print("✋ 刷声骸正在跑：%s，%s 开始，刷到 %s（游戏机时钟）。没有动画面。"
      % (rec.get("name") or "第 %s 个" % rec.get("boss"), rec.get("started"), until))
print("   边刷边点界面会跟 OK-WW 抢键鼠；OK-WW 一停，中继过 5 分钟就把它重开、拉回副本，还会报警。也别单杀 OK-WW。")
q = chr(39)   # a single quote; this program sits inside a single-quoted bash string
print("   要进游戏看，先停：scripts/mac/order-now.sh " + q + json.dumps({"action": "echo_farm_stop"}) + q)
try:
    end = datetime.strptime(until, "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=8)))
except ValueError:
    end = None
if end is not None and end > datetime.now(timezone.utc):
    go = {"action": "echo_farm", "boss": rec.get("boss"), "until": until[-5:], "confirmed": True}
    if rec.get("weekly"):
        go["weekly"] = True
    if rec.get("name"):
        go["name"] = rec["name"]
    print("   看完续刷：scripts/mac/order-now.sh " + q + json.dumps(go, ensure_ascii=False) + q)
else:
    print("   原定收工时刻已过或读不懂，看完不用续刷（续刷会被当成明天这个点）。")
print("   确实要边刷边动，加 ARK_GUI_DURING_FARM=1。")
'

case "$ACTION" in
  shot) CMD="shot" ;;
  # 动作后面的参数全收：没加引号的 `launch wuwa -- -krqlv=sd` 原来只剩 wuwa。
  launch)
    shift
    LAUNCH_ARG="${*:-wuwa}"
    ARK_SG_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/shutdown-guard.sh"
    if [ -f "$ARK_SG_LIB" ]; then
      # shellcheck source=lib/shutdown-guard.sh
      . "$ARK_SG_LIB"
      _sg_rc=0
      ark_sg_preflight launch "wingui launch" "" "" "" "$LAUNCH_ARG" || _sg_rc=$?
      [ "$_sg_rc" = 5 ] && exit 5
    fi
    CMD="launch ${LAUNCH_ARG}" ;;   # wuwa 或完整 exe 路径
  key)  CMD="${ARG:?用法: wingui.sh key <esc|esc2|enter|space|shift|tab|f1-f12|单个字母或数字>}" ;;
  focus) CMD="focus" ;;
  scroll) CMD="scroll ${2:?用法: wingui.sh scroll <格数，负数向下> [x y]}${3:+ $3 ${4:?给了 x 就得给 y}}" ;;
  click) CMD="click ${2:?用法: wingui.sh click <x> <y>} ${3:?缺 y 坐标}" ;;
  look) CMD="look ${2:?用法: wingui.sh look <dx> <dy>（相对位移，转视角）} ${3:?缺 dy}" ;;
  hold) CMD="hold ${2:?用法: wingui.sh hold <键> <毫秒>} ${3:?缺毫秒}" ;;
  # 一次跑一串动作，用 ; 隔开。每次调用都要建计划任务再等结果（十几秒），
  # 一步一次往返没法驾驶游戏；一串压成一次才够用。
  seq)  CMD="${2:?用法: wingui.sh seq 'hold w 1500; look 300 0; key f; wait 800'}" ;;
  *)    cat >&2 <<'USAGE'
用法:
  wingui.sh shot [out.png]              截图
  wingui.sh focus                       把目标窗口拉到前台
  wingui.sh launch [wuwa|<完整exe路径>]  在交互桌面启动图形程序（鸣潮只用 wuwa：自动带 -krqlv，等到窗口出来）
  wingui.sh key <esc|esc2|f1..f12|字母|数字>
  wingui.sh click <x> <y>               真实鼠标左键点击
  wingui.sh scroll <格数> [x y]         滚轮（负数向下）；不给坐标就在屏幕中央滚
  wingui.sh look <dx> <dy>              转视角（相对位移）
  wingui.sh hold <键> <毫秒>            按住走位，例如 hold w 1500
  wingui.sh seq '<动作1; 动作2; ...>'    一次往返跑一串
      动作还支持 rdown/rup/ldown/lup（按住鼠标键）、wait <毫秒>
目标窗口: ARK_GUI_PROC=<进程名> 或 ARK_GUI_PROC=title:<窗口标题片段>
刷声骸在跑时除 shot 外一律拒绝（退出码 7），先 order-now.sh echo_farm_stop；硬要动加 ARK_GUI_DURING_FARM=1
退出码：3 没等到结果  6 远端报了 ERR  7 刷声骸在跑/状态读不出
USAGE
        exit 2 ;;
esac

# 刷声骸在跑时，除了只读的 shot 一律不动画面（见文件头）。状态读不出也不动：宁可让人
# 看一眼再加开关，也不能在不知道的时候跟 OK-WW 抢键鼠。
if [ "$ACTION" != shot ] && [ "${ARK_GUI_DURING_FARM:-}" != 1 ]; then
  STATE=$(ssh -o ConnectTimeout=20 "$USER_AT" 'type C:\ProgramData\ark-relay\state\state.json' 2>/dev/null | tr -d '\r') || STATE=""
  if ! FARM=$(printf '%s' "$STATE" | "$MAC_PY" -c "$FARM_PY"); then
    echo "✋ 读不到游戏机上中继的状态（C:\\ProgramData\\ark-relay\\state\\state.json），不知道刷声骸在不在跑，没有动画面。" >&2
    echo "   确认没在刷（或者就是要边刷边动）再加 ARK_GUI_DURING_FARM=1 重跑。" >&2
    exit 7
  fi
  if [ -n "$FARM" ]; then
    printf '%s\n' "$FARM" >&2
    exit 7
  fi
fi

printf '%s' "$CMD" > "$TMP/cmd.txt"
# 按键/点击要作用在哪个进程的窗口上。默认鸣潮；终末地传 ARK_GUI_PROC=Endfield。
printf '%s' "${ARK_GUI_PROC:-Client-Win64-Shipping}" > "$TMP/proc.txt"
scp -q -o ConnectTimeout=20 "$TMP/ark-gui.ps1" "${USER_AT}:${REMOTE_PS}"
scp -q -o ConnectTimeout=20 "$TMP/cmd.txt" "${USER_AT}:C:/ProgramData/ark-gui-cmd.txt"
scp -q -o ConnectTimeout=20 "$TMP/proc.txt" "${USER_AT}:C:/ProgramData/ark-gui-proc.txt"

# -WindowStyle Hidden 很重要：不加的话 pwsh 的黑控制台会**盖在游戏上**，
# 截出来的图中间一大块黑，而且它自己抢了前台。2026-08-26 第一版就这样。
ssh -o ConnectTimeout=20 "$USER_AT" \
  "schtasks /delete /tn ark-gui /f >nul 2>&1 & \
   schtasks /create /tn ark-gui /tr \"\\\"${PWSH}\\\" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\\ProgramData\\ark-gui.ps1\" /sc once /st 00:00 /ru Administrator /rl highest /it /f >nul 2>&1 & \
   del C:\\ProgramData\\ark-gui.png C:\\ProgramData\\ark-gui.txt >nul 2>&1 & \
   schtasks /run /tn ark-gui >nul 2>&1 & echo STARTED" >/dev/null 2>&1

# 等结果文件出现。计划任务是异步的，schtasks /run 一返回不代表跑完了。
#
# 等多久不能写死。seq 串一长（拍三张照片 ≈ 75 秒）就会超过固定上限，
# 脚本报「没有产出结果」，但**远端其实跑完了**——这种假失败最坑人。
# 所以按动作串自己算预算：把 wait/hold 里写的毫秒加起来，
# 再给每个动作留 5 秒（keybd_event 之后脚本自己要 sleep 2.5 秒，
# click 之后 1.8 秒），最后加 30 秒的启动和截图开销。
BUDGET=$(printf '%s' "$CMD" | awk '
  { n = gsub(/[;\n]/, ";") + 1 }
  { s = $0
    while (match(s, /(wait|hold [A-Za-z0-9]+)[ ]+[0-9]+/)) {
      seg = substr(s, RSTART, RLENGTH)
      sub(/^.*[ ]/, "", seg); ms += seg
      s = substr(s, RSTART + RLENGTH)
    } }
  END { printf "%d", 30 + ms/1000 + 5*n }')
# launch 远端自己要等：鸣潮最多 WUWA_LAUNCH_MAX 秒等窗口、再 8 秒截图，关崩溃框 5 秒；
# 别的程序固定 LAUNCH_WAIT 秒。按大的那个加，加 15 秒余量。预算只管失败时等多久，
# 结果一出来就不等了，所以宁大勿小。
if [ "$ACTION" = launch ]; then
  BUDGET=$((BUDGET + (WUWA_LAUNCH_MAX > LAUNCH_WAIT ? WUWA_LAUNCH_MAX : LAUNCH_WAIT) + 15))
fi
BUDGET=${ARK_GUI_WAIT:-$BUDGET}
POLL=${ARK_GUI_POLL:-2}
OUT=""
for _ in $(seq 1 $(( (BUDGET + POLL - 1) / POLL ))); do
  if OUT=$(ssh -o ConnectTimeout=15 "$USER_AT" 'type C:\ProgramData\ark-gui.txt' 2>/dev/null | tr -d '\r') \
     && [ -n "$OUT" ]; then break; fi
  sleep "$POLL"
done
if [ -z "$OUT" ]; then
  echo "✋ session 1 里的任务没有产出结果（等了 ${BUDGET} 秒）。" >&2
  echo "   多半是没人登录 console 会话——/it 的任务要求用户已登录。" >&2
  echo "   查一下：ssh $USER_AT qwinsta" >&2
  exit 3
fi
sed 's/^/  /' <<<"$OUT"

DEST="${ARG:-}"
# 这些动作的第二个参数是动作内容，不是输出路径。漏一个就会拿动作串当文件名
# （2026-08-29 加 seq 时就漏了，截图存成了「focus; wait 800; ...」这个文件）。
case "$ACTION" in key|click|launch|scroll|look|hold|seq) DEST="" ;; esac
[ "$ACTION" = "focus" ] && DEST="${2:-}"
DEST="${DEST:-$TMPDIR/wingui-$(date +%H%M%S).png}"
if ! scp -q -o ConnectTimeout=30 "${USER_AT}:C:/ProgramData/ark-gui.png" "$DEST"; then
  echo "✋ 截图取不回来。" >&2
  exit 4
fi
[ -s "$DEST" ] || { echo "✋ 取回的截图是 0 字节。" >&2; exit 5; }
echo "  → $DEST ($(wc -c <"$DEST" | tr -d ' ') 字节)"
# 远端报了 ERR（找不到进程、游戏窗口没出来、崩溃框……）就是动作没做成，不许回 0。
# 截图照样取回来了，看图就知道卡在哪。
if grep -q '^ERR ' <<<"$OUT"; then
  echo "✋ 远端报了错（上面 ERR 那行），这次动作没做成。" >&2
  exit 6
fi
