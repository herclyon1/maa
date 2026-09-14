# Drill for relay/ark_relay/collect_watch.py on the game machine (run through
# scripts/mac/collect-watch-drill.sh). Appends the real 2026-09-14 event lines to
# the live maafw.log, checks that the relay narrows the master and restores it,
# then cuts the log back to its previous length and restarts the relay so the
# watcher's offset starts over. Only while nothing is running.
# winrun.sh wraps this in a script block: `return`, never `exit` (exit kills the
# output capture).
$log = "D:\ark\MaaEnd\debug\maafw.log"
$m = Get-ChildItem "D:\ark\automas\data\*\*\ConfigFile\mxu-MaaEnd.json" | Select-Object -First 1
if (-not $m) { "FAIL: master mxu-MaaEnd.json not found"; return }
if (Get-Process MaaEnd, Endfield -ErrorAction SilentlyContinue) { "FAIL: MaaEnd or the game is running; drill only when idle"; return }

# Plain foreach loops throughout: inside the `& { }` wrapper, `$_` in a
# ForEach-Object block within a function came back null (2026-09-14).
function Lists {
  $doc = Get-Content $m.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
  $t = $null
  foreach ($task in $doc.instances[0].tasks) { if ($task.taskName -eq "AutoCollect") { $t = $task } }
  $parts = @()
  foreach ($prop in $t.optionValues.PSObject.Properties) {
    if ($prop.Name -match "^AutoCollect.*RareRoutes$") {
      $parts += $prop.Name.Replace("AutoCollect", "").Replace("RareRoutes", "") + "=" + ($prop.Value.caseNames -join ",")
    }
  }
  $parts -join " | "
}
function Append([string[]]$lines) {
  $fs = [System.IO.File]::Open($log, 'Append', 'Write', 'ReadWrite')
  $sw = New-Object System.IO.StreamWriter($fs, (New-Object System.Text.UTF8Encoding($false)))
  foreach ($l in $lines) { $sw.WriteLine($l) }
  $sw.Close(); $fs.Close()
}
function LastWatch([int]$n) {
  $r = Select-String -Path C:\ProgramData\ark-relay\relay.log -Pattern "ark.collect_watch" | Select-Object -Last $n
  foreach ($x in $r) { "    " + $x.Line }
}

$before = Lists
"before:  $before"
$size0 = (Get-Item $log).Length
$failed = @(
'[2026-09-14 11:20:22.594][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] [details={"action_id":500001459,"focus":{"Node.Recognition.Succeeded":"$option.AutoCollectRoute10.failed"},"name":"AutoCollectRoute10Failed","task_id":200000297}] ',
'[2026-09-14 11:20:23.065][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.Failed] [details={"entry":"AutoCollectSchedule","hash":"1dd55aee6e9ac409","task_id":200000001,"uuid":"00000000001E0236"}] ')
$start = '[2026-09-14 11:21:43.264][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.Starting] [details={"entry":"AutoCollectSchedule","hash":"1dd55aee6e9ac409","task_id":200000001,"uuid":"00000000001E0236"}] '

$ok = $true
Append $failed
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline -and (Lists) -eq $before) { Start-Sleep -Milliseconds 500 }
$mid = Lists
"narrowed: $mid"
if ($mid -ne "ValleyIV= | Wuling=Route10") { "FAIL: master did not narrow to Route10 within 15 s"; $ok = $false }
if (-not (Test-Path "C:\ProgramData\ark-relay\state\collect-retry\narrow.json")) { "FAIL: narrow.json missing"; $ok = $false }
LastWatch 2

Append @($start)
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline -and (Lists) -ne $before) { Start-Sleep -Milliseconds 500 }
$after = Lists
"restored: $after"
if ($after -ne $before) { "FAIL: master not restored within 15 s"; $ok = $false }
if (Test-Path "C:\ProgramData\ark-relay\state\collect-retry\narrow.json") { "FAIL: narrow.json still there"; $ok = $false }
LastWatch 1

$fs = [System.IO.File]::Open($log, 'Open', 'ReadWrite', 'ReadWrite'); $fs.SetLength($size0); $fs.Close()
"maafw.log cut back to $size0 bytes"
$svc = Get-Service ark-relay
& sc.exe stop ark-relay | Out-Null
$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 800; $svc.Refresh(); if ($svc.Status -eq 'Stopped') { break } }
Start-Service ark-relay -ErrorAction SilentlyContinue
try { $svc.WaitForStatus('Running', [TimeSpan]::FromSeconds(40)) } catch {}
$svc.Refresh(); "relay restarted: $($svc.Status)"
if ($ok) { "DRILL_OK" } else { "DRILL_FAILED" }
