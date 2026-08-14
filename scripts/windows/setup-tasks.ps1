# Create the scheduled tasks required for remote GUI control.
# SSH sessions live in session 0 and have no desktop, so screen capture and
# input injection must run as a task inside the interactive session.
# -WindowStyle Hidden is REQUIRED: a visible console steals focus and covers
# the left half of the screen, i.e. the automation blocks its own target.

$ps = "powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File"

schtasks /create /tn "ark-do"   /tr "$ps C:\ProgramData\ark-do.ps1"   /sc once /st 00:00 /rl highest /f
schtasks /create /tn "ark-shot" /tr "$ps C:\ProgramData\ark-shot.ps1" /sc once /st 00:00 /rl highest /f

# AUTO-MAS autostart. Its own set_SelfStart() is supposed to create this but
# was observed to fail silently, so create it explicitly.
$exe = "D:\Users\Administrator\Desktop\AUTO-MAS\AUTO-MAS.exe"
schtasks /create /tn "AUTO-MAS_AutoStart" /tr "`"$exe`"" /sc onlogon /rl highest /f

# Keep sshd alive - it is the single point of failure for all remote access.
sc.exe failure sshd reset= 86400 actions= restart/5000/restart/10000/restart/30000

Write-Output "--- verify ---"
foreach ($t in @("ark-do","ark-shot","AUTO-MAS_AutoStart")) {
  schtasks /query /tn $t | Out-Null
  if ($LASTEXITCODE -eq 0) { Write-Output "  OK      $t" } else { Write-Output "  MISSING $t" }
}
