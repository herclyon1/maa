"""Process listing through WMI's COM interface - the one door that still exists."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import asyncio
import hashlib
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from ark_relay.core.config import IS_WINDOWS, atomic_write_text, atomic_write_bytes

_log_procs = logging.getLogger("ark.procs")

# Properties are read through SWbemObject.Properties_, not as attributes
# (`item.ProcessId`): once the relay's DispatchWithEvents
# (service._AsyncSubscription) has generated pywin32's early-bound wrapper of the
# WMI scripting library (C:\Windows\Temp\gen_py\...), an early-bound SWbemObject
# has only the interface's own members and `item.ProcessId` raises
# AttributeError. Properties_ works bound either way.
#
# Each try lets go of every COM object - and of the exception, whose traceback
# holds them - before CoUninitialize. Released after it, they raise inside
# Release ("Win32 exception occurred releasing IUnknown"), and keeping the
# exception across tries crashed pythonservice.exe in pythoncom314.dll. A failed
# try is repeated after a pause.
ATTEMPTS = 3
PAUSE_SECONDS = 3.0
_sleep = time.sleep
_state = {"warned": False, "why": ""}   # one WARNING per outage (every WARNING reaches the group)
_QUERY = "SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='python.exe'"


def _code(exc: BaseException) -> str:
    """The COM error code when there is one (0x80041032 = the call was cancelled), else the class name."""
    hr = getattr(exc, "hresult", None)
    if hr is None and getattr(exc, "args", None) and isinstance(exc.args[0], int):
        hr = exc.args[0]
    return f"错误码 0x{hr & 0xFFFFFFFF:08X}" if isinstance(hr, int) else type(exc).__name__


def _prop(item, name: str):
    return item.Properties_(name).Value


def _query_once(query: str = _QUERY) -> "tuple[list[tuple[int, str]] | None, str]":
    """One try in its own COM initialisation: (rows, "") or (None, why). Never raises,
    and no COM object or exception outlives the CoUninitialize."""
    try:
        import pythoncom  # noqa: PLC0415
        import win32com.client  # noqa: PLC0415
    except ImportError:
        return None, "没有 pywin32"
    pythoncom.CoInitialize()
    try:
        wmi = res = item = None
        rows, why = [], ""
        try:
            wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
            res = wmi.ExecQuery(query)
            for item in res:
                rows.append((int(_prop(item, "ProcessId")), str(_prop(item, "CommandLine") or "")))
        except Exception as exc:  # noqa: BLE001 - becomes a plain string; the object must not live on
            why = _code(exc)
            rows = None
        item = res = wmi = None
        return rows, why
    finally:
        pythoncom.CoUninitialize()


def last_failure() -> str:
    """Why the last call returned None (plain words), '' after a success."""
    return _state["why"]


def python_processes(*, warn: bool = True,
                     hosts: "tuple[str, ...]" = ("python.exe",)) -> "list[tuple[int, str]] | None":
    """(pid, command line) of every python.exe, or None when every try of the query failed.

    `hosts` widens the image names (OK-WW runs as pythonw.exe: config.PYTHON_HOSTS).
    `warn=False` is for a caller that reports the failure itself (the boot self-check
    pushes one alarm naming it); that report counts as this outage's one, so a later
    caller does not push the same cause again."""
    query = _QUERY if tuple(hosts) == ("python.exe",) else (
        "SELECT ProcessId, CommandLine FROM Win32_Process WHERE "
        + " OR ".join(f"Name='{h}'" for h in hosts))
    whys = []
    for i in range(ATTEMPTS):
        rows, why = _query_once(query)
        if rows is not None:
            if whys:
                # Read on a retry: fixed itself, so not pushed, but one 「自愈待查」 red
                # item says a session looks at why the query failed (errwatch).
                from ark_relay.features import errwatch  # noqa: PLC0415
                _log_procs.warning("程序列表第 %d 次读到了（之前：%s）", i + 1, "、".join(whys),
                            extra=errwatch.recovered())
            _state["warned"] = False
            _state["why"] = ""
            return rows
        whys.append(why)
        if why == "没有 pywin32":
            break
        _log_procs.info("程序列表这次没读到（第 %d 次，%s）", i + 1, why)
        if i + 1 < ATTEMPTS:
            _sleep(PAUSE_SECONDS)
    _state["why"] = f"试了 {len(whys)} 次都失败（{'、'.join(whys)}）"
    if not warn:
        _state["warned"] = True
    elif not _state["warned"]:
        _state["warned"] = True
        _log_procs.warning("程序列表读不到：试了 %d 次都失败（%s）", len(whys), "、".join(whys))
    return None


log = logging.getLogger("ark.desktop")

# PowerShell 7 默认安装路径（零 PowerShell 5.1 回退；Windows 侧优先从注册表动态取最高版本）
PWSH = Path(r"C:\Program Files\PowerShell\7\pwsh.exe")
_RUN_LOCK = threading.Lock()


def _semver_key(raw: str) -> tuple[int, ...]:
    """把语义版本号字符串（如 '7.6.10'）拆成整数元组用于降序比对，不写死任何具体版本号。"""
    nums = [int(x) for x in re.findall(r"\d+", str(raw or ""))]
    return tuple(nums) if nums else (0,)


def resolve_pwsh() -> Path:
    """动态解析游戏机上已安装的最新版 PowerShell 7（pwsh.exe），严禁回退 PowerShell 5.1。

    查找顺序：
    1. Windows 注册表 HKLM\\SOFTWARE\\Microsoft\\PowerShellCore\\InstalledVersions\\* 中语义版本最高的 InstallDir\\pwsh.exe；
    2. 滚动安装路径 C:\\Program Files\\PowerShell\\7\\pwsh.exe；
    3. PATH 中的 pwsh / pwsh.exe。
    """
    if IS_WINDOWS:
        try:
            import winreg  # noqa: PLC0415 - 仅在 Windows 上存在

            best: tuple[tuple[int, ...], Path] | None = None
            root = r"SOFTWARE\Microsoft\PowerShellCore\InstalledVersions"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root) as key:
                idx = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, idx)
                    except OSError:
                        break
                    idx += 1
                    try:
                        with winreg.OpenKey(key, sub) as sk:
                            ver_s, _ = winreg.QueryValueEx(sk, "SemanticVersion")
                            inst, _ = winreg.QueryValueEx(sk, "InstallDir")
                    except OSError:
                        continue
                    cand = Path(str(inst)) / "pwsh.exe"
                    if cand.is_file():
                        ver_k = _semver_key(str(ver_s))
                        if best is None or ver_k > best[0]:
                            best = (ver_k, cand)
            if best is not None:
                return best[1]
        except OSError:
            pass
    for candidate in (PWSH,):
        if candidate.is_file():
            return candidate
    found = shutil.which("pwsh")
    if found:
        return Path(found)
    return PWSH


def _console_python() -> str:
    """返回与当前运行环境对应的控制台 python.exe（避免 pythonw.exe 无 stdout 管道导致读不到 OCR JSON）。"""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        return str(exe.with_name("python.exe"))
    return str(exe)


def _deskew_rect(x1: float, y1: float, x2: float, y2: float,
                 angle_deg: float, width: int, height: int) -> tuple[int, int, int, int]:
    """当 Windows.Media.Ocr 返回非零 TextAngle 时，把纠偏坐标系下的文字框旋回原图像素坐标。

    背景：2026-11-25 终末地 v1.7 启动器背景图倾斜（TextAngle=-5.6 度），若不旋回原图坐标，
    「开始游戏」按钮会被向下偏移约 40 像素误点到「DirectX 11 启动」。
    """
    if abs(angle_deg) > 0.01 and x2 > x1:
        rad = math.radians(angle_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        cx, cy = width / 2.0, height / 2.0
        rx1 = ry1 = 1e9
        rx2 = ry2 = -1e9
        for px, py in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
            dx, dy = px - cx, py - cy
            nx = cx + dx * cos_a - dy * sin_a
            ny = cy + dx * sin_a + dy * cos_a
            if nx < rx1:
                rx1 = nx
            if ny < ry1:
                ry1 = ny
            if nx > rx2:
                rx2 = nx
            if ny > ry2:
                ry2 = ny
        x1, y1, x2, y2 = rx1, ry1, rx2, ry2
    return int(x1), int(y1), int(x2 - x1), int(y2 - y1)


async def _winrt_ocr_lines_async(path: Path) -> list[dict]:
    """使用 Python 原生 WinRT（Windows.Media.Ocr）异步识别一张本地图片并返回带像素坐标的行列表。"""
    from winrt.windows.globalization import Language  # noqa: PLC0415 - Windows 专用依赖
    from winrt.windows.graphics.imaging import BitmapDecoder  # noqa: PLC0415
    from winrt.windows.media.ocr import OcrEngine  # noqa: PLC0415
    from winrt.windows.storage import FileAccessMode, StorageFile  # noqa: PLC0415

    storage_file = await StorageFile.get_file_from_path_async(str(Path(path).resolve()))
    stream = await storage_file.open_async(FileAccessMode.READ)
    try:
        dec = await BitmapDecoder.create_async(stream)
        bmp = await dec.get_software_bitmap_async()
        lang = Language("zh-Hans-CN")
        engine = OcrEngine.try_create_from_language(lang)
        if engine is None:
            raise RuntimeError("OCR 引擎建不起来（zh-Hans-CN）")
        res = await engine.recognize_async(bmp)
        ang = float(res.text_angle) if res.text_angle is not None else 0.0
        w_px, h_px = int(bmp.pixel_width), int(bmp.pixel_height)
        lines: list[dict] = []
        for line in res.lines:
            x1 = y1 = 1e9
            x2 = y2 = 0.0
            parts: list[str] = []
            for word in line.words:
                rc = word.bounding_rect
                if rc.x < x1:
                    x1 = rc.x
                if rc.y < y1:
                    y1 = rc.y
                if rc.x + rc.width > x2:
                    x2 = rc.x + rc.width
                if rc.y + rc.height > y2:
                    y2 = rc.y + rc.height
                parts.append(word.text)
            if not parts:
                continue
            bx, by, bw, bh = _deskew_rect(x1, y1, x2, y2, ang, w_px, h_px)
            lines.append({"text": "".join(parts), "x": bx, "y": by, "w": bw, "h": bh})
        return lines
    finally:
        stream.close()


def _winrt_ocr_lines(path: Path) -> list[dict]:
    """同步封装 WinRT OCR 识别，返回 [{'text','x','y','w','h'}, ...]。"""
    return asyncio.run(_winrt_ocr_lines_async(path))


# 嵌入在 desktop.py 里的独立 OCR 子脚本：由交互桌面中的 pwsh 7 agent.ps1 调用中继 Python 执行，
# 彻底摆脱 PowerShell 5.1 的 ContentType=WindowsRuntime 依赖，并与调用方保持永久同版本。
OCR_HELPER_PY = r'''"""由桌面助手（pwsh 7）调用的 Python 原生 WinRT OCR 辅助脚本。"""
import asyncio
import json
import math
import sys
from pathlib import Path

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage import FileAccessMode, StorageFile


def deskew_rect(x1, y1, x2, y2, angle_deg, width, height):
    if abs(angle_deg) > 0.01 and x2 > x1:
        rad = math.radians(angle_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        cx, cy = width / 2.0, height / 2.0
        rx1 = ry1 = 1e9
        rx2 = ry2 = -1e9
        for px, py in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
            dx, dy = px - cx, py - cy
            nx = cx + dx * cos_a - dy * sin_a
            ny = cy + dx * sin_a + dy * cos_a
            if nx < rx1:
                rx1 = nx
            if ny < ry1:
                ry1 = ny
            if nx > rx2:
                rx2 = nx
            if ny > ry2:
                ry2 = ny
        x1, y1, x2, y2 = rx1, ry1, rx2, ry2
    return int(x1), int(y1), int(x2 - x1), int(y2 - y1)


async def run(img_path: str):
    f = await StorageFile.get_file_from_path_async(str(Path(img_path).resolve()))
    stream = await f.open_async(FileAccessMode.READ)
    try:
        dec = await BitmapDecoder.create_async(stream)
        bmp = await dec.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
        if engine is None:
            raise RuntimeError("OCR 引擎建不起来（zh-Hans-CN）")
        res = await engine.recognize_async(bmp)
        ang = float(res.text_angle) if res.text_angle is not None else 0.0
        w_px, h_px = int(bmp.pixel_width), int(bmp.pixel_height)
        lines = []
        for line in res.lines:
            x1 = y1 = 1e9
            x2 = y2 = 0.0
            parts = []
            for word in line.words:
                rc = word.bounding_rect
                if rc.x < x1:
                    x1 = rc.x
                if rc.y < y1:
                    y1 = rc.y
                if rc.x + rc.width > x2:
                    x2 = rc.x + rc.width
                if rc.y + rc.height > y2:
                    y2 = rc.y + rc.height
                parts.append(word.text)
            if not parts:
                continue
            bx, by, bw, bh = deskew_rect(x1, y1, x2, y2, ang, w_px, h_px)
            lines.append({"text": "".join(parts), "x": bx, "y": by, "w": bw, "h": bh})
        return lines
    finally:
        stream.close()


if __name__ == "__main__":
    out = asyncio.run(run(sys.argv[1]))
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
'''

# 交互桌面助手脚本（由 pwsh 7 在 Session 1 执行，负责置前台、唤醒屏幕、截屏、点击；
# 文字识别委派给同目录下的 ocr_helper.py 走 Python 原生 WinRT OCR）。
# 整段内嵌在 desktop.py 里而不是单独放 .ps1，确保部署清单（仅扫 ark_relay/*.py）永远同版本下发。
AGENT_PS = r'''
param([string]$req, [string]$res)
$ErrorActionPreference = 'Stop'
$log = New-Object System.Collections.ArrayList
$out = @{ ok = $false; log = $log; ocr = @(); clicked = @() }
function Save {
  $json = $out | ConvertTo-Json -Depth 6
  [IO.File]::WriteAllText($res, $json, [Text.Encoding]::UTF8)
}
try {
  Add-Type -AssemblyName System.Windows.Forms, System.Drawing
  Add-Type @"
using System; using System.Runtime.InteropServices;
public class ArkD {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
  public static IntPtr FindByTitle(string part) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      if (!IsWindowVisible(h)) return true;
      var sb = new System.Text.StringBuilder(512); GetWindowText(h, sb, 512);
      if (sb.ToString().Contains(part)) { found = h; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
"@
  $win = $null
  $r = [IO.File]::ReadAllText($req, [Text.Encoding]::UTF8) | ConvertFrom-Json

  # 置前台：按进程名，或 title:窗口标题。同名多进程时按标题定位更稳。
  # 找不到目标窗口时标 focus_missing 并拒绝点击，避免把别的窗口文字误认成启动器。
  $focusMissing = $false
  if ($r.focus) {
    $f = [string]$r.focus
    if ($f -like 'title:*') {
      $want = $f.Substring(6)
      $p = Get-Process -ErrorAction SilentlyContinue |
           Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like "*$want*" } |
           Select-Object -First 1
    } else {
      $p = Get-Process -Name $f -ErrorAction SilentlyContinue |
           Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    }
    if ($null -eq $p -and $f -like 'title:*') {
      # Get-Process 的 MainWindowTitle 看不到雷电这类窗口（09-03 实测），
      # 退回枚举所有可见顶层窗口按标题子串找。
      $h2 = [ArkD]::FindByTitle($f.Substring(6))
      if ($h2 -ne [IntPtr]::Zero) {
        [ArkD]::ShowWindow($h2, 9) | Out-Null
        [ArkD]::SetForegroundWindow($h2) | Out-Null
        [void]$log.Add("focus(enum): $f")
        Start-Sleep -Milliseconds 800
        $rc = New-Object ArkD+RECT
        if ([ArkD]::GetWindowRect($h2, [ref]$rc)) { $win = $rc }
        $p = 'enum'
      }
    }
    if ($null -eq $p) {
      [void]$log.Add("focus: 没有 $f 的窗口")
      $focusMissing = $true
      $out.focus_missing = $true
    }
    elseif ($p -eq 'enum') { }
    else {
      [ArkD]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
      [ArkD]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
      [void]$log.Add("focus: $($p.ProcessName) 「$($p.MainWindowTitle)」")
      Start-Sleep -Milliseconds 800
      $rc = New-Object ArkD+RECT
      if ([ArkD]::GetWindowRect($p.MainWindowHandle, [ref]$rc)) { $win = $rc }
    }
  }

  # 屏幕熄灭 5 分钟后 CopyFromScreen 会吐出熄屏前的旧帧，零位移相对鼠标移动可无副作用唤醒屏幕。
  $script:ArkWoke = $false
  function WakeDisplay() {
    if ($script:ArkWoke) { return }
    $script:ArkWoke = $true
    [ArkD]::mouse_event(0x0001, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 700
  }

  function Shot([string]$path) {
    WakeDisplay
    $b = [Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object Drawing.Bitmap $b.Width, $b.Height
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [Drawing.Point]::Empty, $b.Size)
    $g.Dispose()
    $bmp.Save($path, [Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
  }

  # 文字识别统一委派给中继自带 Python 原生 WinRT OCR（ocr_helper.py），
  # 彻底不再依赖 PowerShell 5.1 的 WindowsRuntime 类型加速器。
  function Ocr([string]$path) {
    $pyExe = if ($r.python) { [string]$r.python } else { 'C:\Program Files\ArkRelay\runtime\python\python.exe' }
    if ($pyExe -match 'pythonw\.exe$') { $pyExe = $pyExe -replace 'pythonw\.exe$', 'python.exe' }
    $helper = if ($r.ocr_helper) { [string]$r.ocr_helper } else { Join-Path $PSScriptRoot 'ocr_helper.py' }
    $oldEnc = [Console]::OutputEncoding
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    try {
      $raw = (& $pyExe -X utf8 $helper $path 2>&1)
      $code = $LASTEXITCODE
    } finally {
      [Console]::OutputEncoding = $oldEnc
    }
    if ($code -ne 0) {
      throw ("Python WinRT OCR 失败（退出码 $code）：" + (($raw | Out-String).Trim()))
    }
    $text = ($raw | Out-String).Trim()
    $lines = New-Object System.Collections.ArrayList
    if (-not $text) { return $lines }
    $parsed = $text | ConvertFrom-Json
    foreach ($item in @($parsed)) {
      if ($null -ne $item) {
        [void]$lines.Add(@{ text = [string]$item.text; x = [int]$item.x; y = [int]$item.y; w = [int]$item.w; h = [int]$item.h })
      }
    }
    return $lines
  }
  # 第二遍识别：黑字配亮黄底的按钮（鹰角启动器「开始游戏」）整屏 OCR 会漏掉。
  # 把聚焦窗口裁出来，灰度 + 高对比（黄底变白、字仍黑），放大两倍再认，
  # 坐标映射回屏幕。2026-09-02 实测整屏那遍读到 15 行就是没有按钮。
  function OcrWindow([string]$shotPath, [string]$outPath) {
    if ($null -eq $win -or $win.R -le $win.L -or $win.B -le $win.T) { return @() }
    $src = [Drawing.Image]::FromFile($shotPath)
    $w = [Math]::Max(1, $win.R - $win.L); $h = [Math]::Max(1, $win.B - $win.T)
    $dst = New-Object Drawing.Bitmap ($w * 2), ($h * 2)
    $g = [Drawing.Graphics]::FromImage($dst)
    $g.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $cm = New-Object Drawing.Imaging.ColorMatrix
    # 灰度（Rec.601 权重）再乘 3 拉对比，偏移 -1.0 把中灰以上推成白
    $k = 3.0
    $cm.Matrix00 = 0.299*$k; $cm.Matrix01 = 0.299*$k; $cm.Matrix02 = 0.299*$k
    $cm.Matrix10 = 0.587*$k; $cm.Matrix11 = 0.587*$k; $cm.Matrix12 = 0.587*$k
    $cm.Matrix20 = 0.114*$k; $cm.Matrix21 = 0.114*$k; $cm.Matrix22 = 0.114*$k
    $cm.Matrix40 = -1.0; $cm.Matrix41 = -1.0; $cm.Matrix42 = -1.0
    $cm.Matrix33 = 1.0; $cm.Matrix44 = 1.0
    $ia = New-Object Drawing.Imaging.ImageAttributes
    $ia.SetColorMatrix($cm)
    $rect = New-Object Drawing.Rectangle 0, 0, ($w * 2), ($h * 2)
    $g.DrawImage($src, $rect, $win.L, $win.T, $w, $h, [Drawing.GraphicsUnit]::Pixel, $ia)
    $g.Dispose(); $src.Dispose()
    $dst.Save($outPath, [Drawing.Imaging.ImageFormat]::Png); $dst.Dispose()
    $found = Ocr $outPath
    $mapped = New-Object System.Collections.ArrayList
    foreach ($ln in $found) {
      [void]$mapped.Add(@{ text = $ln.text; x = [int]($win.L + $ln.x / 2); y = [int]($win.T + $ln.y / 2);
                           w = [int]($ln.w / 2); h = [int]($ln.h / 2) })
    }
    return $mapped
  }
  function InWin($e) {
    if ($null -eq $e) { return $false }
    if ($null -eq $win -or $win.R -le $win.L -or $win.B -le $win.T) { return $true }
    $mx = $e.x + $e.w / 2.0; $my = $e.y + $e.h / 2.0
    return ($mx -ge $win.L -and $mx -le $win.R -and $my -ge $win.T -and $my -le $win.B)
  }
  function Click([int]$x, [int]$y) {
    [ArkD]::SetCursorPos($x, $y) | Out-Null
    Start-Sleep -Milliseconds 250
    [ArkD]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 60
    [ArkD]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    $out.clicked += ,@($x, $y)
    [void]$log.Add("click $x,$y")
    Start-Sleep -Milliseconds 1200
  }

  $shot = [string]$r.shot
  $lines = $null
  foreach ($a in @($r.actions)) {
    switch ([string]$a.act) {
      'wait' { Start-Sleep -Milliseconds ([int]$a.ms); [void]$log.Add("wait $($a.ms)") }
      'shot' { Shot $shot; [void]$log.Add("shot $shot") }
      # 仅唤醒屏幕不截屏：供 display_wake.py 在 AUTO-MAS 拉起终末地启动器时使用
      'wake' { WakeDisplay; [void]$log.Add("wake") }
      'ocr' {
        Shot $shot
        # 函数返回的 ArrayList 会被 PowerShell 展开成定长数组，重新装一遍才能 Add
        # 聚焦窗口拿到边界时：窗口增强排在前面，整屏结果只保留中心点落在 $win 内的行，
        # 避免桌面图标或后台其他窗口的同名文字混入或抢先命中。
        $lines = New-Object System.Collections.ArrayList
        $extra = @(OcrWindow $shot ($shot -replace '\.png$', '-x2.png'))
        foreach ($e in $extra) { [void]$lines.Add($e) }
        foreach ($e in @(Ocr $shot)) { if (InWin $e) { [void]$lines.Add($e) } }
        $out.ocr = @($lines)
        [void]$log.Add("ocr $($lines.Count) 行（窗口增强 $($extra.Count) 行）")
      }
      'ocrfile' {
        # 识别已下载的本地图片文件（如鸣潮版本活动日历长图），不截屏
        $lines = New-Object System.Collections.ArrayList
        foreach ($e in @(Ocr ([string]$a.path))) { [void]$lines.Add($e) }
        $out.ocr = @($lines)
        [void]$log.Add("ocrfile $($lines.Count) 行")
      }
      'click' {
        if ($focusMissing) { [void]$log.Add("skip click: focus missing") }
        else { Click ([int]$a.x) ([int]$a.y) }
      }
      'click_text' {
        if ($focusMissing) { [void]$log.Add("skip click: focus missing") }
        else {
          if ($null -eq $lines) {
            Shot $shot
            $lines = New-Object System.Collections.ArrayList
            foreach ($e in @(OcrWindow $shot ($shot -replace '\.png$', '-x2.png'))) { [void]$lines.Add($e) }
            foreach ($e in @(Ocr $shot)) { if (InWin $e) { [void]$lines.Add($e) } }
            $out.ocr = @($lines)
          }
          $want = ([string]$a.text) -replace '\s', ''
          # 两字及以内的按钮词（如「确认」「更新」）必须整行完全相等，防止误点新闻标题「版本更新公告」。
          $hit = $lines | Where-Object {
            $t = ($_.text -replace '\s', '')
            if ($want.Length -le 2) { $t -eq $want } else { $t -like "*$want*" }
          } | Select-Object -First 1
          if ($null -eq $hit -and $want.Length -ge 4) {
            # 四字及以上容忍 1 个字的 OCR 误差（如「开始游戏」被认成「丹始游戏」）
            $hit = $lines | Where-Object {
              $t = ($_.text -replace '\s', ''); $ok = $false
              for ($i = 0; $i -le $t.Length - $want.Length; $i++) {
                $miss = 0
                for ($j = 0; $j -lt $want.Length; $j++) { if ($t[$i + $j] -ne $want[$j]) { $miss++ } }
                if ($miss -le 1) { $ok = $true; break }
              }
              $ok
            } | Select-Object -First 1
          }
          if ($null -eq $hit) { [void]$log.Add("click_text: 屏幕上没有「$want」") }
          else {
            # 记录命中的完整 OCR 行，供上线核对确认两字短词不会误点长标题。
            [void]$log.Add("click_text: 点了「$($hit.text)」")
            Click ([int]($hit.x + $hit.w / 2)) ([int]($hit.y + $hit.h / 2))
          }
        }
      }
      default { [void]$log.Add("不认识的动作 $($a.act)") }
    }
  }
  $out.ok = $true
} catch {
  [void]$log.Add("ERR " + $_.Exception.Message)
}
Save
'''


def _fuzzy_in(want: str, hay: str, max_miss: int = 1) -> bool:
    n = len(want)
    if n == 0 or len(hay) < n:
        return False
    for i in range(len(hay) - n + 1):
        miss = sum(1 for a, b in zip(want, hay[i:i + n], strict=True) if a != b)
        if miss <= max_miss:
            return True
    return False


def _subseq_miss(seq: str, full: str, max_miss: int) -> bool:
    """`seq` as a subsequence of `full`, skipping at most `max_miss` of `full`'s
    characters. For the banner-name matcher: the OCR line dropped that many of the
    name's characters, so the read text sits inside the true name with gaps."""
    i = skipped = 0
    for ch in seq:
        while i < len(full) and full[i] != ch:
            i += 1
            skipped += 1
            if skipped > max_miss:
                return False
        if i == len(full):
            return False
        i += 1
    return True


def _name_in(want: str, hay: str, max_miss: int = 1) -> bool:
    """`want` appears in the OCR line `hay` allowing at most `max_miss` OCR errors:
    a wrong character (substitution, `_fuzzy_in`) or dropped characters
    (`_subseq_miss`). Windows OCR read 「余心所向九死未悔」 as 「余心所向九悔」 on
    2026-10-06 (two dropped); a same-length substitution match cannot see that.
    With `max_miss` 0 this is an exact substring match."""
    if want in hay or _fuzzy_in(want, hay, max_miss):
        return True
    return len(hay) >= len(want) - max_miss and _subseq_miss(hay, want, max_miss)


@dataclass
class Line:
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


class Screen:
    """The result of one OCR pass. Queries like `has("更新游戏")` ignore whitespace.

    focus_missing: the window the read asked for was not found, so nothing was
    read (lines is empty) - the screen in front belongs to some other program.
    error: the agent itself failed (did not start, timed out, threw), so nothing
    was read either. Both are "unknown", not "a screen without the button".
    """

    def __init__(self, lines: list[Line], shot: Path | None = None,
                 focus_missing: bool = False, error: str = ""):
        self.lines = [] if (focus_missing or error) else lines
        self.shot = shot
        self.focus_missing = focus_missing
        self.error = error

    def find(self, text: str) -> Line | None:
        """Exact match first, then tolerate one wrong character (only for >=4 chars)."""
        want = text.replace(" ", "")
        short = len(want) <= 2
        for ln in self.lines:
            got = ln.text.replace(" ", "")
            if (got == want) if short else (want in got):
                return ln
        if len(want) >= 4:
            for ln in self.lines:
                if _fuzzy_in(want, ln.text.replace(" ", "")):
                    return ln
        return None

    def has(self, *texts: str) -> bool:
        return any(self.find(t) is not None for t in texts)

    def dump(self, limit: int = 40) -> str:
        return " / ".join(ln.text for ln in self.lines[:limit])


def _drop(*files: Path) -> None:
    """Delete the agent's working files; one held open or already gone is left for the next prune."""
    for f in files:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass


def _focus_missing(data: dict) -> bool:
    """The agent could not bring the requested window to the front."""
    return bool(data.get("focus_missing")) or any(
        str(x).startswith("focus: 没有") for x in (data.get("log") or []))


class Desktop:
    """Dispatch actions into the desktop session. Every method returns an empty
    result on failure and never raises."""

    def __init__(self, state_dir: Path, spawn=None, timeout: float = 90, spawn_hidden=None):
        self.dir = Path(state_dir) / "desktop"
        self.agent = self.dir / "agent.ps1"
        self.ocr_helper = self.dir / "ocr_helper.py"
        self.timeout = timeout
        # `spawn` 用于需要置前台的交互任务（Session 1 保留 SetForegroundWindow 权限）；
        # `spawn_hidden` 用于截屏/纯读屏等无窗口后台任务，绝不抢前台焦点。
        self._spawn = spawn or self._spawn_default
        self._spawn_hidden = spawn_hidden or spawn or self._spawn_hidden_default
        # 记录每次桌面助手调用的问答明细，供上线核对（machinechecks/system.py #60-#62）读取。
        self.trace: list[dict] = []

    TRACE_KEEP = 300

    def note(self, **entry) -> None:
        """Add one entry to the trace (a flow's own reading of a screen)."""
        self.trace.append(entry)
        del self.trace[:-self.TRACE_KEEP]

    def _remember(self, actions: list[dict], focus: str | None, data: dict) -> None:
        acts = [str(a.get("act") or "") for a in actions]
        self.note(what="agent", focus=focus, acts=acts,
                  text=next((str(a.get("text") or "") for a in actions if a.get("act") == "click_text"), ""),
                  clicks=any(a in ("click", "click_text") for a in acts), ok=bool(data.get("ok")),
                  focus_missing=bool(data.get("focus_missing")),
                  log=[str(x) for x in (data.get("log") or [])][:30],
                  clicked=list(data.get("clicked") or []), shot=str(data.get("shot") or ""),
                  lines=[str(o.get("text") or "") for o in (data.get("ocr") or []) if isinstance(o, dict)][:40])

    # -- 派发与落盘 --
    def _ensure_agent(self) -> None:
        """把内嵌的 agent.ps1（pwsh 7）与 ocr_helper.py（Python WinRT）按 SHA-256 原子同步落盘。"""
        self.dir.mkdir(parents=True, exist_ok=True)
        want = hashlib.sha256(AGENT_PS.encode("utf-8")).hexdigest()
        stamp = self.dir / "agent.sha256"
        if not (self.agent.exists() and stamp.exists() and stamp.read_text().strip() == want):
            atomic_write_bytes(self.agent, b"\xef\xbb\xbf" + AGENT_PS.encode("utf-8"))
            atomic_write_text(stamp, want)
        want_ocr = hashlib.sha256(OCR_HELPER_PY.encode("utf-8")).hexdigest()
        stamp_ocr = self.dir / "ocr_helper.sha256"
        if not (self.ocr_helper.exists() and stamp_ocr.exists() and stamp_ocr.read_text().strip() == want_ocr):
            atomic_write_text(self.ocr_helper, OCR_HELPER_PY)
            atomic_write_text(stamp_ocr, want_ocr)

    @staticmethod
    def _spawn_default(exe: Path, cwd: Path, args: tuple[str, ...]) -> bool:
        from ark_relay.features.preupdate import _spawn_via_task  # noqa: PLC0415 - avoids a circular import
        return _spawn_via_task(exe, cwd, args)

    @staticmethod
    def _spawn_hidden_default(exe: Path, cwd: Path, args: tuple[str, ...]) -> bool:
        from ark_relay.features.preupdate import _spawn_hidden_via_task  # noqa: PLC0415 - avoids a circular import
        return _spawn_hidden_via_task(exe, cwd, args)

    def run(self, actions: list[dict], focus: str | None = None,
            timeout: float | None = None, *, warn_error: bool = True) -> dict:
        with _RUN_LOCK:
            data = self._run(actions, focus, timeout, warn_error=warn_error)
        try:
            self._remember(actions, focus, data)
        except Exception:  # the trace is evidence only; never breaks a run
            log.debug("桌面助手这一次没记进核对用的记录", exc_info=True)
        return data

    WORK_KEEP_SECONDS = 7 * 24 * 3600
    _WORK_GLOBS = ("req-*.json", "res-*.json", "shot-*.png")

    def _prune_work(self) -> None:
        cutoff = time.time() - self.WORK_KEEP_SECONDS
        for pattern in self._WORK_GLOBS:
            for f in self.dir.glob(pattern):
                try:
                    old = f.stat().st_mtime < cutoff
                except OSError:
                    continue
                if old:
                    _drop(f)

    def _run(self, actions: list[dict], focus: str | None, timeout: float | None, *,
             warn_error: bool = True) -> dict:
        self._ensure_agent()
        self._prune_work()
        rid = uuid.uuid4().hex[:8]
        req = self.dir / f"req-{rid}.json"
        res = self.dir / f"res-{rid}.json"
        shot = self.dir / f"shot-{rid}.png"
        atomic_write_text(req, json.dumps(
            {"focus": focus, "actions": actions, "shot": str(shot),
             "python": _console_python(), "ocr_helper": str(self.ocr_helper)},
            ensure_ascii=False))
        # 需要置前台（focus）时保留交互会话路由以确保 SetForegroundWindow 权限；
        # 纯截屏/读图/唤醒走无窗口路由。外壳统一使用动态解析的最新版 pwsh 7，零 5.1 回退。
        spawn = self._spawn if focus else self._spawn_hidden
        ok = spawn(resolve_pwsh(), self.dir,
                   ("-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File",
                    str(self.agent), str(req), str(res)))
        if not ok:
            (log.warning if warn_error else log.info)("桌面助手没能在交互会话里起来")
            _drop(req)
            return {"ok": False, "log": ["没能起来"], "ocr": [], "shot": str(shot)}
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            if res.exists():
                try:
                    data = json.loads(res.read_text(encoding="utf-8-sig"))
                    data["shot"] = str(shot)
                except (OSError, ValueError):
                    time.sleep(0.5)
                    continue
                # The answer is in `data` now; the request and the result file are
                # not read again. The screenshot stays (WORK_KEEP_SECONDS).
                _drop(req, res)
                return data
            time.sleep(1)
        (log.warning if warn_error else log.info)("桌面助手 %s 超时没有结果", rid)
        return {"ok": False, "log": ["超时"], "ocr": [], "shot": str(shot)}

    # -- common combinations --
    def read(self, focus: str | None = None, settle_ms: int = 0, *,
             warn_missing: bool = True, warn_error: bool = True) -> Screen:
        acts = ([{"act": "wait", "ms": settle_ms}] if settle_ms else []) + [{"act": "ocr"}]
        data = self.run(acts, focus=focus, warn_error=False)
        lines = [Line(str(o.get("text") or ""), int(o.get("x") or 0), int(o.get("y") or 0),
                      int(o.get("w") or 0), int(o.get("h") or 0))
                 for o in (data.get("ocr") or [])]
        if focus and _focus_missing(data):
            # What was read is whatever window happened to be in front - another
            # program's text must never pass for the launcher's. Polling loops waiting
            # for a newly-launched game window pass warn_missing=False so each poll
            # does not fire a separate group alarm before the loop retries or reports.
            (log.warning if warn_missing else log.info)(
                "桌面读屏：没找到 %s 的窗口，读到的不算数（截图 %s）", focus, data.get("shot"))
            return Screen([], Path(data.get("shot") or ""), focus_missing=True)
        if not data.get("ok"):
            # The agent failed part-way (did not start, timed out, threw): whatever
            # lines came back are not a full read of the screen, so none count.
            why = "；".join(map(str, data.get("log") or [])) or "桌面助手没给结果"
            (log.warning if warn_error else log.info)("桌面读屏失败：%s", why)
            return Screen([], Path(data.get("shot") or ""), error=why)
        return Screen(lines, Path(data.get("shot") or ""))

    def read_file(self, path: Path, timeout: float = 90) -> "list[Line] | None":
        """OCR one image file (not the screen); None when the agent failed."""
        data = self.run([{"act": "ocrfile", "path": str(path)}], timeout=timeout, warn_error=False)
        if not data.get("ok"):
            log.warning("桌面助手读图失败：%s", "；".join(map(str, data.get("log") or [])))
            return None
        return [Line(str(o.get("text") or ""), int(o.get("x") or 0), int(o.get("y") or 0),
                     int(o.get("w") or 0), int(o.get("h") or 0))
                for o in (data.get("ocr") or [])]

    def screenshot(self, timeout: float = 45) -> "Path | None":
        """One picture of the real desktop, no OCR; None when it could not be taken.
        Used for evidence: a log that stops mid-run says nothing about what the
        game was showing (OK-WW, 2026-09-19 09:34-11:35)."""
        data = self.run([{"act": "shot"}], timeout=timeout)
        shot = Path(data.get("shot") or "")
        return shot if data.get("ok") and shot.is_file() else None

    def wake(self, timeout: float = 30) -> bool:
        """Wake the display (WakeDisplay: a zero-distance mouse move), no picture, no
        window brought to the front. For display_wake.py: the Hypergryph launcher
        keeps its window hidden while the display is off."""
        data = self.run([{"act": "wake"}], timeout=timeout)
        return bool(data.get("ok")) and "wake" in [str(x) for x in (data.get("log") or [])]

    def click_text(self, text: str, focus: str | None = None, *,
                   warn_missing: bool = True) -> bool:
        data = self.run([{"act": "click_text", "text": text}], focus=focus)
        if focus and _focus_missing(data):
            (log.warning if warn_missing else log.info)(
                "桌面点击：没找到 %s 的窗口，不点「%s」", focus, text)
            return False
        return bool(data.get("ok")) and bool(data.get("clicked"))

    def click(self, x: int, y: int, focus: str | None = None) -> bool:
        """Click one screen point: for a button the OCR cannot read, placed from a
        line it did read (the Hypergryph launcher's 「确认」, gameupdate_games)."""
        data = self.run([{"act": "click", "x": int(x), "y": int(y)}], focus=focus)
        if focus and _focus_missing(data):
            log.warning("桌面点击：没找到 %s 的窗口，不点 (%d, %d)", focus, x, y)
            return False
        return bool(data.get("ok")) and bool(data.get("clicked"))


def ocr_image_file(path: Path, timeout: float = 15.0) -> "str | None":
    """直接使用 Python 原生 WinRT（Windows.Media.Ocr）识别一张本地图片，不碰桌面、不闪黑框、不调 PowerShell 5.1。

    成功返回按行拼接的文本（可能为空串）；非 Windows、文件缺失、超时或 OCR 出错时返回 None。
    """
    if not IS_WINDOWS or not Path(path).is_file():
        return None
    target = Path(path).resolve()
    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_winrt_ocr_lines, target)
    try:
        lines = fut.result(timeout=timeout)
    except FutureTimeoutError:
        log.info("本地读图超时（%s，超过 %.1f 秒）", target.name, timeout)
        pool.shutdown(wait=False, cancel_futures=True)
        return None
    except Exception as exc:  # noqa: BLE001 - WinRT 依赖缺失或图片损坏时记录并安全返回 None
        log.info("本地读图失败（%s）：%s", target.name, exc)
        pool.shutdown(wait=False, cancel_futures=True)
        return None
    pool.shutdown(wait=False)
    return "\n".join(str(ln.get("text") or "") for ln in lines).strip()


# taskkill's exit code when no process has that image name: not being there is not
# an error here. Exit code 1 can also happen when every matched PID exited between
# taskkill's snapshot and TerminateProcess (2026-11-25 10:05:19 Endfield.exe PID 5224:
# 「错误: 无法终止进程 ... 原因: 没有此任务的实例在运行。」). Any other non-zero
# code (1 = access denied) is a kill that failed.
_TASKKILL_NOT_FOUND = 128
_TASKKILL_GONE = ("没有此任务的实例在运行", "there is no running instance of the task")


def _taskkill_already_gone(returncode: int, out: str) -> bool:
    """True when taskkill returned 1 solely because every matched PID was already gone."""
    if returncode != 1:
        return False
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    reasons = [ln for ln in lines if ln.lower().startswith(("原因:", "原因：", "reason:"))]
    errors = [ln for ln in lines if ln.lower().startswith(("错误:", "错误：", "error:"))]
    return (bool(reasons) and len(reasons) >= len(errors)
            and all(any(m in r.lower() for m in _TASKKILL_GONE) for r in reasons))


def kill(*names: str) -> bool:
    """taskkill a few process names; not being there is not an error."""
    ok = True
    for name in names:
        try:
            r = subprocess.run(["taskkill", "/F", "/IM", name],
                               capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("结束 %s 的命令没能运行：%s", name, exc)
            ok = False
            continue
        if r.returncode not in (0, _TASKKILL_NOT_FOUND):
            out = ((r.stdout or b"") + (r.stderr or b"")).decode("gbk", "replace").strip()
            if _taskkill_already_gone(r.returncode, out):
                log.info("结束 %s：进程已自行退出（%s）", name, " ".join(out.split()))
                continue
            log.warning("结束 %s 没成功（退出码 %s）：%s", name, r.returncode, out)
            ok = False
    return ok
