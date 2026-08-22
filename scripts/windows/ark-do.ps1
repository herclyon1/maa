$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System;using System.Runtime.InteropServices;
public class M {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,int e);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,IntPtr l,uint fl,uint to,out IntPtr r);
}
"@
$log = "C:\ProgramData\ark-do.log"
function L($m){ Add-Content -Path $log -Value ((Get-Date).ToString("HH:mm:ss") + " " + $m) }
function Click($x,$y,$rb){
  [M]::SetCursorPos($x,$y); Start-Sleep -Milliseconds 90
  if($rb){ [M]::mouse_event(0x08,0,0,0,0); Start-Sleep -Milliseconds 55; [M]::mouse_event(0x10,0,0,0,0) }
  else   { [M]::mouse_event(0x02,0,0,0,0); Start-Sleep -Milliseconds 55; [M]::mouse_event(0x04,0,0,0,0) }
}
L "--- batch start ---"
foreach ($line in (Get-Content "C:\ProgramData\ark-cmd.txt" -Encoding UTF8)) {
  $line = $line.Trim(); if (-not $line -or $line.StartsWith("#")) { continue }
  $p = $line.Split(' ',2); $cmd = $p[0].ToLower(); $arg = if ($p.Count -gt 1) { $p[1] } else { "" }
  L ("> " + $line)
  switch ($cmd) {
    "move"   { $a=$arg.Split(' '); [M]::SetCursorPos([int]$a[0],[int]$a[1]) }
    "click"  { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $false }
    "uiclick" {
      # Click for Electron / WebView UIs, where a plain click misses twice over.
      # 1. They only arm a control after it has seen a mouseover, so move the
      #    cursor there and let the hover register before pressing.
      # 2. When the window is not foreground, the first click is swallowed
      #    activating it. Press once to take focus, then again to act.
      # Both failures were observed on AUTO-MAS on 2026-08-22 and both are
      # silent: the cursor is in the right place and nothing happens.
      $a=$arg.Split(' '); $x=[int]$a[0]; $y=[int]$a[1]
      [M]::SetCursorPos($x,$y); Start-Sleep -Milliseconds 400
      [M]::SetCursorPos($x,$y); Start-Sleep -Milliseconds 900
      Click $x $y $false
      Start-Sleep -Milliseconds 350
      Click $x $y $false
      L ("  uiclick done at " + $x + "," + $y)
    }
    "focus"  {
      # Bring a window to the front by title substring and wait for it to
      # settle, so the click that follows is not spent on activation.
      $t = $arg
      $sig = @"
using System;using System.Runtime.InteropServices;using System.Text;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
"@
      if (-not ("W" -as [type])) { Add-Type $sig }
      # Prefer a process whose window is actually on screen. An emulator keeps
      # background processes with the same name, and picking one of those hands
      # back a minimized phantom window parked off-screen - which then silently
      # poisons every coordinate computed from it.
      $cand = Get-Process | Where-Object {
        $_.MainWindowHandle -ne 0 -and ($_.MainWindowTitle -like "*$t*" -or $_.ProcessName -like "*$t*")
      }
      $p = $cand | Sort-Object { if ($_.MainWindowTitle) { 0 } else { 1 } } | Select-Object -First 1
      if ($p) {
        [W]::ShowWindow($p.MainWindowHandle, 9) | Out-Null   # SW_RESTORE
        [W]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 1200
        L ("  focus -> " + $p.MainWindowTitle)
      } else { L ("  focus: no window matching " + $t) }
    }
    "dclick" { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $false; Start-Sleep -Milliseconds 90; Click ([int]$a[0]) ([int]$a[1]) $false }
    "rclick" { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $true }
    "gdrag" {
      # gdrag x1 y1 x2 y2 [steps]  - drag using ARKNIGHTS coordinates.
      #
      # MAA writes every gesture against a 1280x720 reference frame and scales
      # it to whatever the device is. That is why its numbers can be copied
      # straight out of resource/tasks/tasks.json - e.g. the depot's own swipe:
      #
      #   DepotSlowlySwipeToTheRight: (1150,340) -> (110,340)
      #
      # The mapping below is the emulator window as it is currently laid out,
      # measured from a screenshot. Detecting it at run time was tried and
      # abandoned: the visible window does not belong to dnplayer.exe, and the
      # dnplayer process that does exist owns an off-screen phantom at
      # -9999,-10000. A measured constant that is wrong when the window moves
      # beats a detector that is confidently wrong right now - and gdrag prints
      # the mapping it used, so a bad result is visible in the log.
      #
      # If the emulator window is moved or resized, re-measure and update these
      # four numbers (client origin and size on screen).
      $CLX = 163; $CLY = 88; $CLW = 1595; $CLH = 892
      $a=$arg.Split(' ')
      $gx1=[double]$a[0]; $gy1=[double]$a[1]; $gx2=[double]$a[2]; $gy2=[double]$a[3]
      $n = if ($a.Count -gt 4) { [int]$a[4] } else { 14 }
      $x1=[int]($CLX + $gx1*$CLW/1280.0); $y1=[int]($CLY + $gy1*$CLH/720.0)
      $x2=[int]($CLX + $gx2*$CLW/1280.0); $y2=[int]($CLY + $gy2*$CLH/720.0)
      L ("  gdrag game(" + $gx1 + "," + $gy1 + ")->(" + $gx2 + "," + $gy2 + ")  screen(" + $x1 + "," + $y1 + ")->(" + $x2 + "," + $y2 + ")")
      [M]::SetCursorPos($x1,$y1); Start-Sleep -Milliseconds 250
      [M]::mouse_event(0x02,0,0,0,0)
      Start-Sleep -Milliseconds 150
      # Ease in, stop hard: MAA uses slope-in 2, slope-out 0 for depot swipes,
      # over about 200 ms. A linear drag reads as a flick and overshoots.
      for ($i=1; $i -le $n; $i++) {
        $f = [Math]::Pow($i / [double]$n, 2)
        [M]::SetCursorPos([int]($x1 + ($x2-$x1)*$f), [int]($y1 + ($y2-$y1)*$f))
        Start-Sleep -Milliseconds 14
      }
      Start-Sleep -Milliseconds 120
      [M]::mouse_event(0x04,0,0,0,0)
    }
    "drag" {
      # drag x1 y1 x2 y2 [steps]
      # For touch-derived UIs - the game inside the emulator, and anything else
      # that turns mouse input into gestures. A wheel event does nothing there
      # (verified 2026-08-22 on the Arknights depot: scroll moved the view zero
      # pixels), and a single down-move-up is often read as a tap because the
      # travel arrives in one jump. Decompose it: press, glide through
      # intermediate points, release. Same shape as the PlayCover rule in
      # docs/OPERATIONS.md, and for the same reason.
      $a=$arg.Split(' ')
      $x1=[int]$a[0]; $y1=[int]$a[1]; $x2=[int]$a[2]; $y2=[int]$a[3]
      $n = if ($a.Count -gt 4) { [int]$a[4] } else { 12 }
      if ($n -lt 2) { $n = 2 }
      [M]::SetCursorPos($x1,$y1); Start-Sleep -Milliseconds 250
      [M]::mouse_event(0x02,0,0,0,0)          # left down
      Start-Sleep -Milliseconds 180
      for ($i=1; $i -le $n; $i++) {
        $x = [int]($x1 + ($x2-$x1) * $i / $n)
        $y = [int]($y1 + ($y2-$y1) * $i / $n)
        [M]::SetCursorPos($x,$y)
        Start-Sleep -Milliseconds 22
      }
      Start-Sleep -Milliseconds 180
      [M]::mouse_event(0x04,0,0,0,0)          # left up
      L ("  drag " + $x1 + "," + $y1 + " -> " + $x2 + "," + $y2 + " in " + $n + " steps")
    }
    "scroll" {
      # scroll x y notches  (positive = up, negative = down; one notch = 120)
      $a=$arg.Split(' '); [M]::SetCursorPos([int]$a[0],[int]$a[1]); Start-Sleep -Milliseconds 90
      $d = [int]$a[2] * 120
      $ud = [BitConverter]::ToUInt32([BitConverter]::GetBytes($d),0)
      [M]::mouse_event(0x0800,0,0,$ud,0)
    }
    "type"   { [System.Windows.Forms.SendKeys]::SendWait($arg) }
    "sleep"  { Start-Sleep -Milliseconds ([int]$arg) }
    "run"    { try { Start-Process -FilePath $arg; L ("  launched: " + $arg) } catch { L ("  RUN FAIL: " + $_.Exception.Message) } }
    "monitoroff" {
      $r = [IntPtr]::Zero
      [void][M]::SendMessageTimeout([IntPtr](-1), 0x0112, [IntPtr]0xF170, [IntPtr]2, 0x0002, 3000, [ref]$r)
      L "  monitor -> OFF (SC_MONITORPOWER 2)"
    }
    "shot"   {
      $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
      $bmp = New-Object System.Drawing.Bitmap($b.Width,$b.Height)
      $g = [System.Drawing.Graphics]::FromImage($bmp)
      $g.CopyFromScreen($b.X,$b.Y,0,0,$bmp.Size)
      $bmp.Save($arg,[System.Drawing.Imaging.ImageFormat]::Png)
      $g.Dispose(); $bmp.Dispose(); L ("  saved " + $arg)
    }
    default  { L ("  UNKNOWN: " + $cmd) }
  }
}
L "--- batch end ---"
