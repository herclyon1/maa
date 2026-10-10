# shellcheck shell=bash
# shellcheck disable=SC2034  # VER, CHANGED, SMOKE_*, MC_STATE_ARG are read by the caller
# Sourced by scripts/mac/deploy-relay.sh when the machine runs the installed relay
# (packaging/ark-relay.iss: task \ArkRelay\main, watchdog ArkRelayWatchdog). Replaces
# its steps 3-5.2 for that layout; the steps before (local gates, manifest) and after
# (COS, smoke, after-deploy check, manifest to GitHub) are the script's own.
#
# The installed relay runs {app}\versions\<current.txt>\ (relay/pkg_layout.py). So:
#   3p  push every file into a new folder {app}\versions\.incoming (one tar stream)
#   4p  scripts/windows/pkg_deploy.py commit: every hash checked there, then the folder
#       becomes versions\<n>, the recorded code version is n, current.txt -> n.
#       The folder in use is never written to.
#   5p  launch.py stop (waits until the relay has exited), schtasks /run \ArkRelay\main;
#       read current.txt and relay.log back
#   5.2 watch (deploy_watch.py --pkg); not steady = current.txt back to the previous
#       folder and restart (exit 12; 13 when that does not hold either)
# COS goes up only after the watch passed, as for the old relay (10-10).
#
# Uses from deploy-relay.sh: SSH_OPTS USER_AT HERE FILES WATCH_S.
# Sets for the steps after: VER LOGB64 CHANGED SMOKE_PY SMOKE_ARGS MC_STATE_ARG.

APP_WIN='C:\Program Files\ArkRelay'
PKGPY="\"$APP_WIN\\runtime\\python\\python.exe\""
PKG_DEPLOY='C:\Users\Administrator\ark-pkg-deploy.py'
WATCH_PY='C:\Users\Administrator\ark-deploy-watch.py'

pkg_ssh() { ssh "${SSH_OPTS[@]}" "$USER_AT" "$@" 2>&1 | tr -d '\r'; }
# Commands whose program path has a space go through base64 pwsh (repo rule 3): cmd.exe
# keeps a quoted program path only when the line holds exactly two quotes (cmd /? on /C),
# and these need a quoted argument as well. pkg_py <args...> runs the package's Python
# with them, each argument single-quoted for PowerShell.
pkg_py() {
  local a ps="[Console]::OutputEncoding = [Text.Encoding]::UTF8; & '$APP_WIN\runtime\python\python.exe' -X utf8"
  for a in "$@"; do ps+=" '${a//\'/\'\'}'"; done
  ps+="; exit \$LASTEXITCODE"
  pkg_ssh "\"C:\\Program Files\\PowerShell\\7\\pwsh.exe\" -NoProfile -EncodedCommand $(printf '%s' "$ps" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')"
}

echo "▶ 3/5 推进新的版本文件夹（安装版：$APP_WIN\\versions）"
if ! scp -q "${SSH_OPTS[@]}" "$HERE/../scripts/windows/pkg_deploy.py" "${USER_AT}:C:/Users/Administrator/ark-pkg-deploy.py" \
   || ! scp -q "${SSH_OPTS[@]}" "$HERE/../scripts/windows/deploy_watch.py" "${USER_AT}:C:/Users/Administrator/ark-deploy-watch.py"; then
  echo "  ✋ 部署用的两个脚本没送上机器，什么都没改" >&2
  exit 5
fi
trap 'rm -rf "$GATED"; ssh "${SSH_OPTS[@]}" "$USER_AT" "del $PKG_DEPLOY & del $WATCH_PY" >/dev/null 2>&1 || true' EXIT
INFO=$(pkg_py "$PKG_DEPLOY" info "$APP_WIN" || true)
PREV=$(sed -n 's/^CUR=//p' <<<"$INFO")
MC_STATE=$(sed -n 's/^STATEDIR=//p' <<<"$INFO")
if [ -z "$PREV" ]; then
  echo "  ✋ 读不到机器上正在用的版本（current.txt），什么都没改：" >&2
  printf '%s\n' "$INFO" | tail -5 | sed 's/^/      /' >&2
  exit 5
fi
echo "    正在用的版本文件夹：$PREV"
INC=$(pkg_py "$PKG_DEPLOY" stage "$APP_WIN" | sed -n 's/^INCOMING=//p' || true)
if [ -z "$INC" ]; then
  echo "  ✋ 新版本文件夹没建起来，什么都没改" >&2
  exit 5
fi
# All files, not only the changed ones: the new folder starts empty. One tar stream
# (2026-09-08: 71 files in 2 s, against 119 s one scp each); no ._ files (see step 3 above).
# shellcheck disable=SC2086  # FILES is a word list on purpose
if ! COPYFILE_DISABLE=1 tar --no-mac-metadata -czf - manifest.json $FILES \
     | ssh "${SSH_OPTS[@]}" "$USER_AT" "tar xzf - -C \"$INC\""; then
  echo "  ✋ 推送失败，什么都没切换（正在用的还是 $PREV）" >&2
  exit 5
fi
echo "    推了 $(($(wc -w <<<"$FILES") + 1)) 个文件到 $INC"

lap
echo "▶ 4/5 逐文件核对哈希，核对过了才切到新文件夹"
COMMIT=$(pkg_py "$PKG_DEPLOY" commit "$APP_WIN" || true)
if ! grep -q '^NAME=' <<<"$COMMIT"; then
  echo "  ✋ 没切到新版本（正在用的还是 $PREV）：" >&2
  printf '%s\n' "$COMMIT" | tail -5 | sed 's/^/      /' >&2
  exit 8
fi
NEW=$(sed -n 's/^NAME=//p' <<<"$COMMIT")
VER=$(python3 -c "import json;print(json.load(open('manifest.json'))['version'])")
grep '^HASH-OK' <<<"$COMMIT" | sed 's/^/    /'
echo "    current.txt：$PREV → $NEW（code-version = $VER）"

# Stop (launch.py stop waits until the relay has exited), then the logon task. If the
# watchdog starts it first, the task run is ignored (IgnoreNew) - either way it runs
# the folder current.txt now names.
read -r -d '' PKG_RESTART_PS1 <<'PS1' || true
$ErrorActionPreference = 'Continue'
$app = 'C:\Program Files\ArkRelay'
$py = "$app\runtime\python\python.exe"
& $py "$app\launch.py" stop | Out-Null
Write-Output ("STOPPED_OK=" + ($LASTEXITCODE -eq 0))
Write-Output ("T0=" + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
& schtasks.exe /run /tn '\ArkRelay\main' | Out-Null
$deadline = (Get-Date).AddSeconds(40)
$up = $false
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  $p = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -EA SilentlyContinue |
       Where-Object { $_.CommandLine -like '*ArkRelay\launch.py*' }
  if ($p) { $up = $true; break }
}
Write-Output ("STATE=" + $(if ($up) { 'Running' } else { 'Stopped' }))
Write-Output ("CURRENT=" + (Get-Content "$app\current.txt" -Raw).Trim())
Start-Sleep -Seconds 3
try {
  $tail = Get-Content 'C:\ProgramData\ark-relay\relay.log' -Tail 6 -Encoding utf8
  Write-Output ("LOG=" + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($tail -join "`n"))))
} catch {}
PS1
PKG_ENC=$(printf '%s' "$PKG_RESTART_PS1" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')
pkg_restart() {
  OUT=$(pkg_ssh "\"C:\\Program Files\\PowerShell\\7\\pwsh.exe\" -NoProfile -EncodedCommand $PKG_ENC" || true)
  STATE=$(sed -n 's/^STATE=//p' <<<"$OUT")
  T0=$(sed -n 's/^T0=//p' <<<"$OUT")
  CURRENT=$(sed -n 's/^CURRENT=//p' <<<"$OUT")
}

lap
echo "▶ 5/5 重启中继并确认真的起来了"
pkg_restart
grep -q 'STOPPED_OK=True' <<<"$OUT" \
  && echo "    停止确认：旧的已退出" \
  || echo "    停止确认：没等到旧的退出（继续启动了）"
if [ "$STATE" != "Running" ] || [ "$CURRENT" != "$NEW" ]; then
  echo "  ✋ 新版本没起来（中继：${STATE:-未知}，current.txt：${CURRENT:-读不到}，应为 $NEW）" >&2
  echo "     有人登录桌面时中继才会跑（计划任务只在登录会话里起）。看门服务 30 秒内会再试。" >&2
  exit 6
fi
echo "    启动确认：在跑，用的是 $CURRENT"
if LOGB64=$(sed -n 's/^LOG=//p' <<<"$OUT") && [ -n "$LOGB64" ]; then
  printf '%s' "$LOGB64" | base64 -d 2>/dev/null | sed 's/^/    /' || true
fi

echo "▶ 5.2/5 上线后盯 ${WATCH_S} 秒（不许重启、开机自检要全过、要挂上调度程序句柄）"
WATCH_OUT=$(mktemp)
pkg_py "$WATCH_PY" watch 'C:\ProgramData\ark-relay\relay.log' "$T0" "$WATCH_S" deploy --pkg \
  | tee "$WATCH_OUT" | sed 's/^/    /' || true
if ! grep -q '^WATCH_OK' "$WATCH_OUT"; then
  echo "❌❌ 上线后没稳住：$(sed -n 's/^WATCH_FAIL //p' "$WATCH_OUT" | tail -1)"
  echo "▶ 自动退回上一版 $PREV（current.txt 改回去，新文件夹留着查）"
  BACK=$(pkg_py "$PKG_DEPLOY" back "$APP_WIN" "$PREV" || true)
  printf '%s\n' "$BACK" | tail -2 | sed 's/^/    /'
  pkg_restart
  echo "    退回后：中继 ${STATE:-未知}，current.txt $CURRENT"
  pkg_py "$WATCH_PY" watch 'C:\ProgramData\ark-relay\relay.log' "$T0" 60 rollback "$PREV" --pkg \
    | tee "$WATCH_OUT" | sed 's/^/    /' || true
  if [ "$CURRENT" = "$PREV" ] && [ "$STATE" = "Running" ] && grep -q '^WATCH_OK' "$WATCH_OUT"; then
    echo "↩️  已自动退回上一版 $PREV，退回后 60 秒没有重启。这次部署失败，没有发到 COS。"
    exit 12
  fi
  echo "❌❌❌ 退回上一版后也没稳住——中继现在可能是坏的，必须立刻有人处理。"
  exit 13
fi

# For the steps after: the smoke imports the whole new folder with the package's Python
# (every file is new to that folder), the after-deploy check reads the relay's state dir.
# Both of these lines hold exactly the two quotes around the program path (see pkg_py).
CHANGED=""
SMOKE_PY="$PKGPY"
SMOKE_ARGS="--pkg-version=$NEW"
MC_STATE_ARG="$MC_STATE"
if [[ "$MC_STATE" == *" "* ]]; then
  echo "    ⚠️ 状态目录路径带空格（$MC_STATE），部署后核对那步可能读不到" >&2
fi
