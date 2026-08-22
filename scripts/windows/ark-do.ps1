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
      $p = Get-Process | Where-Object { $_.MainWindowTitle -like "*$t*" } | Select-Object -First 1
      if ($p) {
        [W]::ShowWindow($p.MainWindowHandle, 9) | Out-Null   # SW_RESTORE
        [W]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 1200
        L ("  focus -> " + $p.MainWindowTitle)
      } else { L ("  focus: no window matching " + $t) }
    }
    "dclick" { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $false; Start-Sleep -Milliseconds 90; Click ([int]$a[0]) ([int]$a[1]) $false }
    "rclick" { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $true }
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
