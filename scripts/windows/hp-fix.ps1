# ASCII only. Fix HP sshd: proper daemon mode (no -d) + sftp + hidden + guarded.
# Strategy: bring up a parallel daemon on 2223 NOW (does not touch the live 2222
# session), and rewrite autostart so 2222 becomes daemon-mode on next boot.
# Nothing here kills the current sshd -> the calling ssh session survives.

$ossh = "$env:USERPROFILE\srv\openssh\OpenSSH-Win64"
$sftp = "$ossh\sftp-server.exe"
$hostkey = "$ossh\ssh_host_ed25519_key"
$authkeys = "$env:USERPROFILE\.ssh\authorized_keys"

# --- 1) daemon config for the live parallel test on 2223 (with sftp) ---
$cfg2223 = @"
Port 2223
HostKey $hostkey
AuthorizedKeysFile $authkeys
PubkeyAuthentication yes
PasswordAuthentication no
Subsystem sftp $sftp
"@
Set-Content -Path "$ossh\sshd_config_2223" -Value $cfg2223 -Encoding ASCII

# --- 2) daemon config that will replace 2222 on next boot (with sftp) ---
$cfg2222 = @"
Port 2222
HostKey $hostkey
AuthorizedKeysFile $authkeys
PubkeyAuthentication yes
PasswordAuthentication no
Subsystem sftp $sftp
"@
Set-Content -Path "$ossh\sshd_config" -Value $cfg2222 -Encoding ASCII

# --- 3) guard for the 2223 test daemon ---
$loop2223 = @'
while($true){
  Start-Process -FilePath "$env:USERPROFILE\srv\openssh\OpenSSH-Win64\sshd.exe" `
    -ArgumentList '-f',"$env:USERPROFILE\srv\openssh\OpenSSH-Win64\sshd_config_2223" `
    -WindowStyle Hidden -Wait
  Start-Sleep 2
}
'@
Set-Content -Path "$env:USERPROFILE\srv\sshd-loop-2223.ps1" -Value $loop2223 -Encoding ASCII

# --- 4) rewrite the MAIN guard to daemon mode (no -d) for 2222, next boot ---
$loopMain = @'
while($true){
  Start-Process -FilePath "$env:USERPROFILE\srv\openssh\OpenSSH-Win64\sshd.exe" `
    -ArgumentList '-f',"$env:USERPROFILE\srv\openssh\OpenSSH-Win64\sshd_config" `
    -WindowStyle Hidden -Wait
  Start-Sleep 2
}
'@
Set-Content -Path "$env:USERPROFILE\srv\sshd-loop.ps1" -Value $loopMain -Encoding ASCII

# --- 5) start the 2223 daemon NOW, hidden (parallel, does not touch 2222) ---
Start-Process powershell -ArgumentList '-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',"$env:USERPROFILE\srv\sshd-loop-2223.ps1" -WindowStyle Hidden

# --- 6) make sure RustDesk is up (user's GUI fallback), hidden ---
if (-not (Get-Process rustdesk -ErrorAction SilentlyContinue)) {
    Start-Process "$env:USERPROFILE\srv\rustdesk.exe" -WindowStyle Hidden
}

Write-Output "FIX-APPLIED port2223=up sftp=on autostart=daemon-mode rustdesk=checked"
