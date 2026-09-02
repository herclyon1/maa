"""在真实桌面（console 会话）里截屏、认字、点按钮。

中继是 LocalSystem 服务，跑在 session 0，没有桌面。要操作启动器这类图形程序，
得把一段脚本派到 console 会话里执行——`preupdate._spawn_interactive` 已经
的「交互式计划任务」方式起进程，这里复用它，起的是 **Windows PowerShell 5.1**。
为什么不是 pwsh 7：2026-09-02 在机器上实测 pwsh 7.6.5 加载不了 WinRT 类型
（`Unable to find type [Windows.Media.Ocr.OcrEngine]`），系统自带的 OCR 只有 5.1
能调。5.1 的编码坑逐条堵：脚本文件带 BOM 写入，请求/结果用
`[IO.File]::ReadAllText/WriteAllText(..., UTF8)`。这是全仓库唯一允许用 5.1 的地方。

OCR 用系统自带的 Windows.Media.Ocr，2026-09-02 在机器上核对过，
可用语言含 zh-Hans-CN。启动器的「更新游戏 / 开始游戏」、游戏里的
「请重启游戏 / 点击任意位置继续」都靠它读出来，不再猜坐标。

协议：请求 JSON → 助手 → 结果 JSON，都落在 state/desktop/ 下，
助手写完结果才退出；这边轮询结果文件，超时就当失败。
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import atomic_write_text

log = logging.getLogger("ark.desktop")

POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")

# 助手脚本。整段内嵌在这里而不是单独的 .ps1，因为部署清单只收 ark_relay/*.py
# （见 make-manifest.py）；内嵌也让它和调用方永远是同一个版本。
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
}
"@
  $r = [IO.File]::ReadAllText($req, [Text.Encoding]::UTF8) | ConvertFrom-Json

  # 置前台：按进程名，或 title:窗口标题。同名多进程时按标题定位更稳。
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
    if ($null -eq $p) { [void]$log.Add("focus: 没有 $f 的窗口") }
    else {
      [ArkD]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
      [ArkD]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
      [void]$log.Add("focus: $($p.ProcessName) 「$($p.MainWindowTitle)」")
      Start-Sleep -Milliseconds 800
    }
  }

  function Shot([string]$path) {
    $b = [Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object Drawing.Bitmap $b.Width, $b.Height
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [Drawing.Point]::Empty, $b.Size)
    $g.Dispose()
    $bmp.Save($path, [Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
  }

  # WinRT 的异步调用在 PowerShell 里要经 AsTask 转成 .NET Task 才能等
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
                   $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($op, $type) {
    $t = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    $t.Result
  }
  function Ocr([string]$path) {
    [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
    [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
    [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime] | Out-Null
    [Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
    [Windows.Storage.FileAccessMode,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
    [Windows.Media.Ocr.OcrResult,Windows.Media.Ocr,ContentType=WindowsRuntime] | Out-Null
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $lang = New-Object Windows.Globalization.Language 'zh-Hans-CN'
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    if ($null -eq $engine) { throw 'OCR 引擎建不起来（zh-Hans-CN）' }
    $result = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $lines = New-Object System.Collections.ArrayList
    foreach ($line in $result.Lines) {
      $x1 = 1e9; $y1 = 1e9; $x2 = 0; $y2 = 0; $txt = ''
      foreach ($w in $line.Words) {
        $rc = $w.BoundingRect
        if ($rc.X -lt $x1) { $x1 = $rc.X }; if ($rc.Y -lt $y1) { $y1 = $rc.Y }
        if ($rc.X + $rc.Width -gt $x2) { $x2 = $rc.X + $rc.Width }
        if ($rc.Y + $rc.Height -gt $y2) { $y2 = $rc.Y + $rc.Height }
        $txt += $w.Text
      }
      [void]$lines.Add(@{ text = $txt; x = [int]$x1; y = [int]$y1; w = [int]($x2 - $x1); h = [int]($y2 - $y1) })
    }
    $stream.Dispose()
    return $lines
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
  foreach ($a in $r.actions) {
    switch ([string]$a.act) {
      'wait' { Start-Sleep -Milliseconds ([int]$a.ms); [void]$log.Add("wait $($a.ms)") }
      'shot' { Shot $shot; [void]$log.Add("shot $shot") }
      'ocr' {
        Shot $shot
        $lines = Ocr $shot
        $out.ocr = @($lines)
        [void]$log.Add("ocr $($lines.Count) 行")
      }
      'click' { Click ([int]$a.x) ([int]$a.y) }
      'click_text' {
        if ($null -eq $lines) { Shot $shot; $lines = Ocr $shot; $out.ocr = @($lines) }
        $want = ([string]$a.text) -replace '\s', ''
        $hit = $lines | Where-Object { ($_.text -replace '\s', '') -like "*$want*" } | Select-Object -First 1
        if ($null -eq $hit) { [void]$log.Add("click_text: 屏幕上没有「$want」") }
        else { Click ([int]($hit.x + $hit.w / 2)) ([int]($hit.y + $hit.h / 2)) }
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
    """一次 OCR 的结果。`has("更新游戏")` 这种问法忽略空格。"""

    def __init__(self, lines: list[Line], shot: Path | None = None):
        self.lines = lines
        self.shot = shot

    def find(self, text: str) -> Line | None:
        want = text.replace(" ", "")
        for ln in self.lines:
            if want in ln.text.replace(" ", ""):
                return ln
        return None

    def has(self, *texts: str) -> bool:
        return any(self.find(t) is not None for t in texts)

    def dump(self, limit: int = 40) -> str:
        return " / ".join(ln.text for ln in self.lines[:limit])


class Desktop:
    """把动作派到桌面会话里做。所有方法失败都返回空结果，不抛。"""

    def __init__(self, state_dir: Path, spawn=None, timeout: float = 90):
        self.dir = Path(state_dir) / "desktop"
        self.agent = self.dir / "agent.ps1"
        self.timeout = timeout
        self._spawn = spawn or self._spawn_default

    # -- 派发 --
    def _ensure_agent(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        want = hashlib.sha256(AGENT_PS.encode("utf-8")).hexdigest()
        stamp = self.dir / "agent.sha256"
        if not (self.agent.exists() and stamp.exists() and stamp.read_text().strip() == want):
            # 必须带 BOM：Windows PowerShell 5.1 读没有 BOM 的 .ps1 按 ANSI（GBK）
            # 解析，脚本里的「」会把字符串撑破，整段解析失败（2026-09-02 实测）。
            tmp = self.agent.with_suffix(".tmp")
            tmp.write_bytes(b"\xef\xbb\xbf" + AGENT_PS.encode("utf-8"))
            tmp.replace(self.agent)
            atomic_write_text(stamp, want)

    @staticmethod
    def _spawn_default(exe: Path, cwd: Path, args: tuple[str, ...]) -> bool:
        # 走交互式计划任务，不走令牌直起：2026-09-02 实测令牌方式起来的助手
        # 截到图却 OCR 出 0 行（用户环境没完整加载），计划任务方式读出 45 行。
        from .preupdate import _spawn_via_task  # noqa: PLC0415 - 避免循环导入
        return _spawn_via_task(exe, cwd, args)

    def run(self, actions: list[dict], focus: str | None = None,
            timeout: float | None = None) -> dict:
        self._ensure_agent()
        rid = uuid.uuid4().hex[:8]
        req = self.dir / f"req-{rid}.json"
        res = self.dir / f"res-{rid}.json"
        shot = self.dir / f"shot-{rid}.png"
        atomic_write_text(req, json.dumps(
            {"focus": focus, "actions": actions, "shot": str(shot)}, ensure_ascii=False))
        ok = self._spawn(POWERSHELL, self.dir,
                         ("-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(self.agent), str(req), str(res)))
        if not ok:
            log.warning("桌面助手没能在交互会话里起来")
            return {"ok": False, "log": ["没能起来"], "ocr": [], "shot": str(shot)}
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            if res.exists():
                try:
                    data = json.loads(res.read_text(encoding="utf-8-sig"))
                    data["shot"] = str(shot)
                    return data
                except (OSError, ValueError):
                    time.sleep(0.5)
                    continue
            time.sleep(1)
        log.warning("桌面助手 %s 超时没有结果", rid)
        return {"ok": False, "log": ["超时"], "ocr": [], "shot": str(shot)}

    # -- 常用组合 --
    def read(self, focus: str | None = None, settle_ms: int = 0) -> Screen:
        acts = ([{"act": "wait", "ms": settle_ms}] if settle_ms else []) + [{"act": "ocr"}]
        data = self.run(acts, focus=focus)
        lines = [Line(str(o.get("text") or ""), int(o.get("x") or 0), int(o.get("y") or 0),
                      int(o.get("w") or 0), int(o.get("h") or 0))
                 for o in (data.get("ocr") or [])]
        if not data.get("ok"):
            log.warning("桌面读屏失败：%s", "；".join(map(str, data.get("log") or [])))
        return Screen(lines, Path(data.get("shot") or ""))

    def click_text(self, text: str, focus: str | None = None) -> bool:
        data = self.run([{"act": "click_text", "text": text}], focus=focus)
        return bool(data.get("ok")) and bool(data.get("clicked"))

    def click(self, x: int, y: int, focus: str | None = None) -> bool:
        data = self.run([{"act": "click", "x": x, "y": y}], focus=focus)
        return bool(data.get("ok"))


def kill(*names: str) -> None:
    """taskkill 几个进程名，不在也不报错。"""
    for name in names:
        try:
            subprocess.run(["taskkill", "/F", "/IM", name],  # noqa: S603, S607
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
