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
set -euo pipefail

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

  if ($exe -notmatch '^[A-Za-z]:\\') {
    $log += "ERR 不认识 '$what'。只接受别名 wuwa 或完整 exe 路径。"
  } elseif (-not (Test-Path $exe)) {
    $log += "ERR 找不到 $exe —— 路径不对就去核对，别硬猜。"
  } else {
    $proc = [IO.Path]::GetFileNameWithoutExtension($exe)
    # 鸣潮的进程名和 exe 名不一样，单独映射；其余按 exe 名判断。
    if ($proc -eq 'Wuthering Waves') { $proc = 'Client-Win64-Shipping' }
    if (Get-Process -Name $proc -ErrorAction SilentlyContinue) {
      $log += "$proc 已在运行，没有重复启动"
    } else {
      if ($extra.Count -gt 0) {
        Start-Process -FilePath $exe -ArgumentList $extra -WorkingDirectory (Split-Path $exe)
        $log += "已启动 $exe [" + ($extra -join ' ') + "]，等 45 秒"
      } else {
        Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe)
        $log += "已启动 $exe，等 45 秒"
      }
      Start-Sleep -Seconds 45
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

$b   = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g   = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save('C:\ProgramData\ark-gui.png', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
$log += "shot $($b.Width)x$($b.Height) $(Get-Date -Format 'HH:mm:ss')"
$log -join "`n" | Set-Content 'C:\ProgramData\ark-gui.txt' -Encoding utf8
PS1

case "$ACTION" in
  shot) CMD="shot" ;;
  launch) CMD="launch ${2:-wuwa}" ;;   # wuwa 或完整 exe 路径
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
  wingui.sh launch [wuwa|<完整exe路径>]  在交互桌面启动图形程序
  wingui.sh key <esc|esc2|f1..f12|字母|数字>
  wingui.sh click <x> <y>               真实鼠标左键点击
  wingui.sh scroll <格数> [x y]         滚轮（负数向下）；不给坐标就在屏幕中央滚
  wingui.sh look <dx> <dy>              转视角（相对位移）
  wingui.sh hold <键> <毫秒>            按住走位，例如 hold w 1500
  wingui.sh seq '<动作1; 动作2; ...>'    一次往返跑一串
      动作还支持 rdown/rup/ldown/lup（按住鼠标键）、wait <毫秒>
目标窗口: ARK_GUI_PROC=<进程名> 或 ARK_GUI_PROC=title:<窗口标题片段>
USAGE
        exit 2 ;;
esac

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
   schtasks /create /tn ark-gui /tr \"\\\"${PWSH}\\\" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\\ProgramData\\ark-gui.ps1\" /sc once /st 00:00 /ru Administrator /it /f >nul 2>&1 & \
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
BUDGET=${ARK_GUI_WAIT:-$BUDGET}
OUT=""
for _ in $(seq 1 $(( (BUDGET + 1) / 2 ))); do
  if OUT=$(ssh -o ConnectTimeout=15 "$USER_AT" 'type C:\ProgramData\ark-gui.txt' 2>/dev/null | tr -d '\r') \
     && [ -n "$OUT" ]; then break; fi
  sleep 2
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
