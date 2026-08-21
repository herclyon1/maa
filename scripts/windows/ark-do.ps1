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
# Leave a timestamp the relay can see. Any GUI action here means a human (or
# me) is working on this desktop right now, and the relay must not power the
# machine off underneath them. ASCII only - this file is read as GBK.
$mark = "C:\ProgramData\ark-relay\state\ark-do-last.txt"
try {
  New-Item -ItemType Directory -Force -Path (Split-Path $mark) | Out-Null
  Set-Content -Path $mark -Value ([DateTimeOffset]::Now.ToUnixTimeSeconds()) -Encoding ASCII
} catch { }
L "--- batch start ---"
foreach ($line in (Get-Content "C:\ProgramData\ark-cmd.txt" -Encoding UTF8)) {
  $line = $line.Trim(); if (-not $line -or $line.StartsWith("#")) { continue }
  $p = $line.Split(' ',2); $cmd = $p[0].ToLower(); $arg = if ($p.Count -gt 1) { $p[1] } else { "" }
  L ("> " + $line)
  switch ($cmd) {
    "move"   { $a=$arg.Split(' '); [M]::SetCursorPos([int]$a[0],[int]$a[1]) }
    "click"  { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $false }
    "dclick" { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $false; Start-Sleep -Milliseconds 90; Click ([int]$a[0]) ([int]$a[1]) $false }
    "rclick" { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $true }
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
