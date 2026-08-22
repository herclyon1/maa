$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System;using System.Runtime.InteropServices;
public class M {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,int e);
  [DllImport("user32.dll")] public static extern uint SendInput(uint n, INPUT[] i, int cb);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint f);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,IntPtr l,uint fl,uint to,out IntPtr r);
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L; public int T; public int R; public int B; }
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT {
    public int dx; public int dy; public uint mouseData; public uint dwFlags;
    public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public MOUSEINPUT mi; }
}
"@
$log = "C:\ProgramData\ark-do.log"
function L($m){ Add-Content -Path $log -Value ((Get-Date).ToString("HH:mm:ss") + " " + $m) }
# --- input primitives ---------------------------------------------------
# Every step of a click used to be fire-and-forget: move the cursor, press,
# release, and never look at whether any of it landed. That is why a missed
# click was always silent. Each step below now checks itself.

$SM_CXSCREEN = 0; $SM_CYSCREEN = 1; $GA_ROOT = 2

function SendMouse([uint32]$flags,[int]$nx,[int]$ny){
  # SendInput, not mouse_event: mouse_event is the superseded API and it does
  # not report whether the event was accepted. SendInput returns the number of
  # events actually injected, which is how a blocked injection becomes visible
  # (UIPI refuses input aimed at a higher-integrity window, silently, forever).
  # Build MOUSEINPUT in its own variable and assign it whole. Writing
  # $i.mi.dx = ... instead silently mutates a COPY - PowerShell hands back a
  # copy when you reach through a field of a value type - so every event went
  # out with dx=dy=dwFlags=0. SendInput still returned 1, the cursor still
  # moved (MoveTo falls back to SetCursorPos) and hover highlights still lit
  # up, so it looked exactly like "the app ignores synthetic clicks".
  $mi = New-Object M+MOUSEINPUT
  $mi.dx = $nx; $mi.dy = $ny; $mi.dwFlags = $flags
  $i = New-Object M+INPUT
  $i.type = 0
  $i.mi = $mi
  $n = [M]::SendInput(1, [M+INPUT[]]@($i), [Runtime.InteropServices.Marshal]::SizeOf([type]("M+INPUT")))
  if ($n -ne 1) { L ("  !! SendInput rejected, flags=" + $flags) }
  return ($n -eq 1)
}

function MoveTo($x,$y){
  # Absolute SendInput move, then verify with GetCursorPos. SetCursorPos can be
  # refused outright (another process holding capture, a UAC-elevated window
  # under the pointer) and it returns before the cursor has settled.
  $w = [M]::GetSystemMetrics($SM_CXSCREEN); $h = [M]::GetSystemMetrics($SM_CYSCREEN)
  $nx = [int](($x * 65535) / [Math]::Max(1, $w - 1))
  $ny = [int](($y * 65535) / [Math]::Max(1, $h - 1))
  SendMouse 0x8001 $nx $ny | Out-Null      # MOVE | ABSOLUTE
  Start-Sleep -Milliseconds 40
  $p = New-Object M+POINT
  [M]::GetCursorPos([ref]$p) | Out-Null
  if ([Math]::Abs($p.X - $x) -gt 2 -or [Math]::Abs($p.Y - $y) -gt 2) {
    [M]::SetCursorPos($x,$y) | Out-Null    # fallback
    Start-Sleep -Milliseconds 60
    [M]::GetCursorPos([ref]$p) | Out-Null
  }
  $ok = ([Math]::Abs($p.X - $x) -le 2 -and [Math]::Abs($p.Y - $y) -le 2)
  if (-not $ok) { L ("  !! cursor would not go to " + $x + "," + $y + " (stuck at " + $p.X + "," + $p.Y + ")") }
  return $ok
}

function EnsureForeground($x,$y){
  # The first click on a background window is spent activating it, so it has to
  # be dealt with - but NOT by clicking the target, which is what the first
  # version of this function did. On a checkbox the activating click toggles it
  # and the real click toggles it straight back: the batch reports success and
  # the setting is unchanged. Activate the window itself instead, and only fall
  # back to a click on its title bar - a place with nothing to toggle.
  $p = New-Object M+POINT; $p.X = $x; $p.Y = $y
  $under = [M]::GetAncestor([M]::WindowFromPoint($p), $GA_ROOT)
  if ($under -eq [IntPtr]::Zero) { return $true }
  if ($under -eq [M]::GetForegroundWindow()) { return $true }
  [M]::ShowWindow($under, 9) | Out-Null          # SW_RESTORE
  [M]::SetForegroundWindow($under) | Out-Null
  Start-Sleep -Milliseconds 350
  if ([M]::GetForegroundWindow() -eq $under) {
    L "  activated the window under the cursor (no click spent)"
    MoveTo $x $y | Out-Null
    return $true
  }
  # SetForegroundWindow is refused unless the caller owns the foreground; when
  # that happens, click the title bar rather than the control.
  $r = New-Object M+RECT
  if ([M]::GetWindowRect($under, [ref]$r)) {
    $tx = [int]($r.L + [Math]::Min(120, ($r.R - $r.L) / 2)); $ty = $r.T + 12
    L ("  falling back to a title-bar click at " + $tx + "," + $ty)
    MoveTo $tx $ty | Out-Null
    SendMouse 0x0002 0 0 | Out-Null; Start-Sleep -Milliseconds 60
    SendMouse 0x0004 0 0 | Out-Null; Start-Sleep -Milliseconds 450
    MoveTo $x $y | Out-Null
  }
  return ([M]::GetForegroundWindow() -eq $under)
}

function Click($x,$y,$rb){
  if (-not (MoveTo $x $y)) { return $false }
  if (-not $rb) { EnsureForeground $x $y | Out-Null }
  Start-Sleep -Milliseconds 60
  if($rb){ SendMouse 0x0008 0 0 | Out-Null; Start-Sleep -Milliseconds 55; SendMouse 0x0010 0 0 | Out-Null }
  else   { SendMouse 0x0002 0 0 | Out-Null; Start-Sleep -Milliseconds 55; SendMouse 0x0004 0 0 | Out-Null }
  return $true
}

function GrabRegion($x,$y,$w,$h){
  # Raw 24bpp pixels, not a PNG. A PNG byte-compare calls one changed pixel a
  # change, and the taskbar clock alone guarantees one every minute - which
  # would report every click as a success including the ones that missed.
  $sw = [M]::GetSystemMetrics($SM_CXSCREEN); $sh = [M]::GetSystemMetrics($SM_CYSCREEN)
  $l = [Math]::Max(0, [Math]::Min($x - [int]($w/2), $sw - $w))
  $t = [Math]::Max(0, [Math]::Min($y - [int]($h/2), $sh - $h))
  $bmp = New-Object Drawing.Bitmap $w, $h, ([Drawing.Imaging.PixelFormat]::Format24bppRgb)
  $g = [Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($l, $t, 0, 0, (New-Object Drawing.Size $w, $h))
  $g.Dispose()
  $rect = New-Object Drawing.Rectangle 0, 0, $w, $h
  $data = $bmp.LockBits($rect, [Drawing.Imaging.ImageLockMode]::ReadOnly, $bmp.PixelFormat)
  $bytes = New-Object byte[] ($data.Stride * $h)
  [Runtime.InteropServices.Marshal]::Copy($data.Scan0, $bytes, 0, $bytes.Length)
  $bmp.UnlockBits($data); $bmp.Dispose()
  return $bytes
}

function ChangedFraction($a,$b){
  # Fraction of bytes that differ by more than a hair. Compression noise and a
  # blinking caret are a handful; a control reacting is thousands.
  #
  # Compare ALL THREE channels. The first version stepped $i += 3 and looked at
  # one channel only - which in BGR is blue - so a checkbox going from white
  # (255,255,255) to the theme blue (255,119,22) scored 0% changed: blue is 255
  # either way. The batch reported NO REACTION for a click that had just
  # toggled the setting, which is worse than no check at all, because it invites
  # a retry that undoes the change.
  if ($a.Length -ne $b.Length -or $a.Length -eq 0) { return 1.0 }
  $diff = 0
  for ($i = 0; $i -lt $a.Length; $i++) {
    if ([Math]::Abs([int]$a[$i] - [int]$b[$i]) -gt 8) { $diff++ }
  }
  return ($diff / [double]$a.Length)
}
L "--- batch start ---"
foreach ($line in (Get-Content "C:\ProgramData\ark-cmd.txt" -Encoding UTF8)) {
  $line = $line.Trim(); if (-not $line -or $line.StartsWith("#")) { continue }
  $p = $line.Split(' ',2); $cmd = $p[0].ToLower(); $arg = if ($p.Count -gt 1) { $p[1] } else { "" }
  L ("> " + $line)
  switch ($cmd) {
    "move"   { $a=$arg.Split(' '); [M]::SetCursorPos([int]$a[0],[int]$a[1]) }
    "click"  { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $false | Out-Null }
    "vclick" {
      # Verified click: photograph a patch around the target, click, photograph
      # again. Identical pixels means the click did nothing - which is the one
      # outcome the old click could never tell apart from success. Retries once,
      # then says so in the log rather than reporting a batch that "worked".
      # vclick x y                     - verify a patch centred on the click
      # vclick x y cx cy w h            - verify a DIFFERENT rectangle, centred
      #                                   on (cx,cy). Use this whenever the
      #                                   effect appears somewhere other than
      #                                   under the mouse - a menu item that
      #                                   swaps the content pane, for instance.
      # Verifying at the cursor is what made the 2026-08-22 test lie: AUTO-MAS
      # highlights a menu item on hover, the highlight moved 0.84% of the patch,
      # and the batch called a click that never navigated a success.
      $a=$arg.Split(' '); $x=[int]$a[0]; $y=[int]$a[1]
      $cx = $x; $cy = $y; $w = 260; $h = 160
      if ($a.Count -ge 6) { $cx=[int]$a[2]; $cy=[int]$a[3]; $w=[int]$a[4]; $h=[int]$a[5] }
      elseif ($a.Count -ge 4) { $w=[int]$a[2]; $h=[int]$a[3] }
      # ONE attempt, never a silent retry. A retry is only safe on a control
      # that ignores a second press; on a checkbox the retry undoes the first
      # click and the batch then reports failure for a setting it changed twice.
      # That happened on 2026-08-22 against AUTO-MAS's log-style checkboxes.
      # If a click needs repeating, repeat it in the batch file, having looked.
      $before = GrabRegion $cx $cy $w $h
      MoveTo $x $y | Out-Null
      Start-Sleep -Milliseconds 450    # let hover-armed controls arm
      Click $x $y $false | Out-Null
      Start-Sleep -Milliseconds 900
      $after = GrabRegion $cx $cy $w $h
      $frac = ChangedFraction $before $after
      if ($frac -gt 0.002) {
        L ("  vclick OK at " + $x + "," + $y + " (" + [Math]::Round($frac*100,2) + "% of the checked patch changed)")
      } else {
        L ("  !! VCLICK NO REACTION at " + $x + "," + $y + " (" + [Math]::Round($frac*100,2) + "% changed) - do NOT blind-retry a toggle")
      }
    }
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
      Click $x $y $false | Out-Null
      Start-Sleep -Milliseconds 350
      Click $x $y $false | Out-Null
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
    "dclick" { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $false | Out-Null; Start-Sleep -Milliseconds 90; Click ([int]$a[0]) ([int]$a[1]) $false | Out-Null }
    "rclick" { $a=$arg.Split(' '); Click ([int]$a[0]) ([int]$a[1]) $true | Out-Null }
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
    "runargs" {
      # runargs <exe> <args...>  - start a program WITH arguments.
      # `run` deliberately takes a bare path, which is right for the common
      # case but cannot express things like `dnplayer.exe --index 1000`. That
      # limitation cost a failed launch on 2026-08-22: the whole string was
      # treated as a path and the batch reported RUN FAIL with no clue why.
      # First token is the executable, the rest are passed through.
      $sp = $arg.Split(' ')
      $exe = $sp[0]
      $rest = if ($sp.Count -gt 1) { $sp[1..($sp.Count-1)] } else { @() }
      try {
        Start-Process -FilePath $exe -ArgumentList $rest -ErrorAction Stop
        L ("  launched: " + $exe + " [" + ($rest -join ' ') + "]")
      } catch {
        L ("  RUNARGS FAIL: " + $_.Exception.Message)
      }
    }
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
