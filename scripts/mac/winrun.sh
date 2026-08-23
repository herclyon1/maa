#!/usr/bin/env bash
# Run a command on the game machine, or fetch a file, without corrupting Chinese.
#
# The Windows console is codepage 936 (GBK) and Windows PowerShell 5.1 reads
# files as ANSI unless told otherwise. So a UTF-8 file printed by a remote
# command is already destroyed before it reaches the wire, and "pipe it through
# iconv" is worse than useless because some output is already UTF-8 - decoding
# that twice shreds it silently. On 2026-08-23 that produced two drop names
# invented out of broken bytes and reported as fact.
#
# Rules this enforces:
#   * a file's contents are fetched as bytes, never printed by a remote command
#   * a command's output is written to a UTF-8 file on the machine, then copied
#   * no Chinese ever appears on a command line
#
#   scripts/mac/winrun.sh 'dir C:\ProgramData'          # cmd
#   scripts/mac/winrun.sh --ps 'Get-Process MAA'        # PowerShell
#   scripts/mac/winrun.sh --get 'D:\path\file.json'     # a file, verbatim
set -euo pipefail

HOST="${ARK_HOST:-100.65.39.119}"
USER_AT="Administrator@${HOST}"
STRIP='import sys;d=open(sys.argv[1],"rb").read();d=d[3:] if d.startswith(b"\xef\xbb\xbf") else d;sys.stdout.write(d.decode("utf-8","replace").replace("\r\n","\n"))'

if [ "${1:-}" = "--get" ]; then
  REMOTE="${2:?用法: winrun.sh --get '<远端文件路径>'}"
  TMP="$(mktemp)"
  scp -q -o ConnectTimeout=30 "${USER_AT}:$(printf '%s' "$REMOTE" | tr '\\' '/')" "$TMP"
  python3 -c "$STRIP" "$TMP"
  rm -f "$TMP"
  exit 0
fi

MODE=cmd
if [ "${1:-}" = "--ps" ]; then MODE=ps; shift; fi
CMD="${1:?用法: winrun.sh [--ps|--get] '<命令或路径>'}"

LOCAL_PS="$(mktemp)"
{
  # Windows PowerShell 5.1 reads a .ps1 as ANSI unless it opens with a
  # UTF-8 BOM. Without these three bytes, Chinese inside the script -
  # including in the command being run - is decoded as GBK and destroyed
  # before it executes.
  printf '\xef\xbb\xbf'
  echo '$ErrorActionPreference = "Continue"'
  echo '$ProgressPreference = "SilentlyContinue"'
  if [ "$MODE" = ps ]; then
    # A child process that writes UTF-8 (python with PYTHONUTF8, curl, git) is
    # decoded by whatever [Console]::OutputEncoding says. Pin it to UTF-8 so
    # their output survives capture; without this the bytes are read as GBK.
    echo '[Console]::OutputEncoding = [Text.Encoding]::UTF8'
    echo '$OutputEncoding = [Text.Encoding]::UTF8'
    echo '$env:PYTHONUTF8 = "1"'
    echo '$env:PYTHONIOENCODING = "utf-8"'
    printf '$out = & {\n%s\n} 2>&1 | Out-String\n' "$CMD"
  else
    # chcp 65001 first: cmd's default codepage here is 936, so a UTF-8
    # command line reaches it as mojibake before it ever runs.
    echo '$enc = [Console]::OutputEncoding'
    echo '[Console]::OutputEncoding = [Text.Encoding]::UTF8'
    printf '$out = & cmd /c "chcp 65001 >nul & %s" 2>&1 | Out-String\n' "$CMD"
    echo '[Console]::OutputEncoding = $enc'
  fi
  echo '[IO.File]::WriteAllText("C:\ProgramData\winrun.out", $out, (New-Object Text.UTF8Encoding($false)))'
} > "$LOCAL_PS"

# Delete the previous output first. Without this, a command that fails to
# produce output leaves the last run's file in place - and reading that as if
# it were the current result is exactly how stale data gets reported as fresh.
ssh -o ConnectTimeout=30 "$USER_AT" 'del /Q C:\ProgramData\winrun.out 2>nul' >/dev/null 2>&1 || true
scp -q -o ConnectTimeout=30 "$LOCAL_PS" "${USER_AT}:C:/ProgramData/winrun.ps1"
# Prefer PowerShell 7: it defaults to UTF-8 everywhere, so Get-Content on a
# UTF-8 file is simply correct, where Windows PowerShell 5.1 would decode it as
# ANSI and destroy it. 5.1 stays as the fallback because it is always present.
ssh -o ConnectTimeout=90 "$USER_AT" \
  'if exist "C:\Program Files\PowerShell\7\pwsh.exe" ("C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\winrun.ps1) else (powershell -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\winrun.ps1)' \
  >/dev/null 2>&1 || true
TMP="$(mktemp)"
scp -q -o ConnectTimeout=30 "${USER_AT}:C:/ProgramData/winrun.out" "$TMP"
python3 -c "$STRIP" "$TMP"
rm -f "$TMP" "$LOCAL_PS"
