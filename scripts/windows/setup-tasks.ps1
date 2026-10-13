# One-off machine setup that no other script owns, plus a check of the scheduled
# tasks the system relies on.
#
# Remote GUI work (screenshots, keys, clicks) goes through scripts/mac/wingui.sh,
# which creates and refreshes its own interactive task (ark-gui) on every call: SSH
# sessions live in session 0 and have no desktop, so that work has to run as a task
# inside the interactive session. The older ark-do / ark-shot / ark-focus-watch tasks
# and their files were retired (gone from the machine, checked 2026-10-12 14:52).
#
# AUTO-MAS_AutoStart is not created here: AUTO-MAS creates and maintains it
# itself while its Start.IfSelfStart setting is on
# (app/services/platform/windows/startup.py). It stays in the verify list below.

# Keep sshd alive - it is the single point of failure for all remote access.
sc.exe failure sshd reset= 86400 actions= restart/5000/restart/10000/restart/30000

# What the relay itself needs, by the names retire_legacy.py checks before it
# retires the old service (new_relay_problems: NEW_TASK_FOLDER\NEW_TASK_NAME and
# NEW_WATCHDOG): the installed relay's scheduled task and its watchdog service.
# Until 2026-10-13 only AUTO-MAS_AutoStart was checked, so a machine without the
# relay's own task printed OK.
Write-Output "--- verify ---"
foreach ($t in @("AUTO-MAS_AutoStart", "\ArkRelay\main")) {
  schtasks /query /tn $t 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) { Write-Output "  OK      $t" } else { Write-Output "  MISSING $t" }
}
foreach ($s in @("ArkRelayWatchdog")) {
  $svc = Get-Service -Name $s -ErrorAction SilentlyContinue
  if (-not $svc) { Write-Output "  MISSING $s (service)" }
  elseif ("$($svc.Status)" -ne "Running") { Write-Output "  STOPPED $s (service, $($svc.Status))" }
  else { Write-Output "  OK      $s (service)" }
}
