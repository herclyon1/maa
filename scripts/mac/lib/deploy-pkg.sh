# shellcheck shell=bash
# shellcheck disable=SC2034  # VER, CHANGED, SMOKE_*, MC_STATE_ARG, WATCHDOG_FAIL_WHY are read by the caller
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
#   (before 3p: nobody logged on at the console = exit 5, nothing changed; the relay
#   runs only in that session, so a start could not be judged. Nor when the machine's
#   runtime - {app}\runtime\python, its Python and the pinned packages - is not what
#   packaging/build.py and relay/requirements.txt build: only the installer replaces
#   it (scripts/mac/lib/pkg_appfiles.py says why), so exit 5 and say so.)
#   4.5p the other installer-written files that changed (launch.py, switch.py,
#       legacy.py, handover\*; pkg_appfiles.py): pkg_deploy.py appfiles swaps them, the
#       old ones kept, before the restart, so the restart and the watch run through the
#       new launch.py. Not swapped = current.txt back, exit 8, the relay untouched.
#   5p  launch.py stop (waits until the relay has exited), schtasks /run \ArkRelay\main;
#       read current.txt and relay.log back
#   5.2 watch (deploy_watch.py --pkg)
#   5p not running or 5.2 not steady = current.txt back to the previous folder, the
#   files of 4.5p back, and restart (exit 12; 13 when that does not hold either)
#   5.3 the watchdog service's file {app}\watchdog\ark_watchdog.py, outside the version
#       folders: only when its sha1 (info's WATCHDOG_SHA) differs from
#       packaging/watchdog/ark_watchdog.py - send it, pkg_deploy.py watchdog: copy,
#       install, restart, verify RUNNING. The relay is live by then; a failure sets
#       WATCHDOG_FAIL_WHY, and deploy-relay.sh still publishes COS, then exits 14.
# COS goes up only after the watch passed, as for the old relay (10-10).
#
# Uses from deploy-relay.sh: SSH_OPTS USER_AT HERE FILES WATCH_S.
# Sets for the steps after: VER LOGB64 CHANGED SMOKE_PY SMOKE_ARGS MC_STATE_ARG WATCHDOG_FAIL_WHY.

APP_WIN='C:\Program Files\ArkRelay'
PKGPY="\"$APP_WIN\\runtime\\python\\python.exe\""
PKG_DEPLOY='C:\Users\Administrator\ark-pkg-deploy.py'
WATCH_PY='C:\Users\Administrator\ark-deploy-watch.py'
WD_SRC="$HERE/../packaging/watchdog/ark_watchdog.py"
WD_STAGED='C:\Users\Administrator\ark-watchdog-new.py'
pkg_sha1() { python3 -c 'import hashlib,sys;print(hashlib.sha1(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }

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
trap 'rm -rf "$GATED"; ssh "${SSH_OPTS[@]}" "$USER_AT" "del $PKG_DEPLOY & del $WATCH_PY & del $WD_STAGED" >/dev/null 2>&1 || true' EXIT
# The plain installer-written files: info returns each one's sha1 on the machine, and
# step 4.5p swaps only the ones that differ from the repo.
APPFILES_LIST=$(python3 "$HERE/../scripts/mac/lib/pkg_appfiles.py" list)
# shellcheck disable=SC2046  # one argument per path on purpose (no spaces in them)
INFO=$(pkg_py "$PKG_DEPLOY" info "$APP_WIN" $(cut -f1 <<<"$APPFILES_LIST") || true)
PREV=$(sed -n 's/^CUR=//p' <<<"$INFO")
MC_STATE=$(sed -n 's/^STATEDIR=//p' <<<"$INFO")
WD_SHA=$(sed -n 's/^WATCHDOG_SHA=//p' <<<"$INFO")
if [ -z "$PREV" ]; then
  echo "  ✋ 读不到机器上正在用的版本（current.txt），什么都没改：" >&2
  printf '%s\n' "$INFO" | tail -5 | sed 's/^/      /' >&2
  exit 5
fi
echo "    正在用的版本文件夹：$PREV"
# The relay runs only in the console user's session: with nobody logged on, a new
# version cannot start, and a failed start would say nothing about the new code.
CONSOLE=$(sed -n 's/^CONSOLE=//p' <<<"$INFO")
if [ -z "$CONSOLE" ]; then
  echo "  ✋ 游戏机上没人登录桌面，中继起不来，没法确认新版本能跑，什么都没改（正在用的还是 $PREV）" >&2
  exit 5
fi
printf '%s\n' "$INFO" >"$GATED/pkg-info.txt"
if ! RUNTIME_GAP=$(python3 "$HERE/../scripts/mac/lib/pkg_appfiles.py" runtime-gap "$GATED/pkg-info.txt"); then
  echo "  ✋ 机器上的运行环境（Python 和它装的包）跟仓库要的不一样，什么都没改（正在用的还是 $PREV）：" >&2
  printf '%s\n' "$RUNTIME_GAP" | sed 's/^/      /' >&2
  echo "      运行环境只能由安装包换（中继和看门服务都开着它的文件，部署换不了）：重新打包，在游戏机上跑一次 setup.exe" >&2
  exit 5
fi
APP_CHANGED=$(python3 "$HERE/../scripts/mac/lib/pkg_appfiles.py" changed "$GATED/pkg-info.txt")
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

# >>> appfiles step
# The installer-written files outside the version folders that changed (APP_CHANGED,
# from info's sha1s): sent in one tar stream laid out as under {app}, then
# pkg_deploy.py appfiles checks every hash and that each file loads, and only then
# swaps them, keeping the old ones for appfiles-back. 1 = not swapped (APPFILES_WHY);
# the caller runs appfiles-back in case the answer was lost half way.
APPFILES_WHY=""
pkg_appfiles_step() {
  local dir rel src inc out pairs=() rels=()
  dir=$(mktemp -d)
  while IFS=$'\t' read -r rel src; do
    grep -qxF "$rel" <<<"$APP_CHANGED" || continue
    mkdir -p "$dir/$(dirname "$rel")"
    cp "$HERE/../$src" "$dir/$rel"
    rels+=("$rel")
    pairs+=("$rel=$(pkg_sha1 "$dir/$rel")")
  done <<<"$APPFILES_LIST"
  inc=$(pkg_py "$PKG_DEPLOY" appfiles-stage "$APP_WIN" | sed -n 's/^APPFILES_IN=//p' || true)
  if [ -z "$inc" ]; then
    APPFILES_WHY="机器上放文件的临时文件夹没建起来"
  elif ! COPYFILE_DISABLE=1 tar --no-mac-metadata -czf - -C "$dir" "${rels[@]}" \
       | ssh "${SSH_OPTS[@]}" "$USER_AT" "tar xzf - -C \"$inc\""; then
    APPFILES_WHY="文件没推上机器"
  else
    out=$(pkg_py "$PKG_DEPLOY" appfiles "$APP_WIN" "${pairs[@]}" || true)
    grep -E '^APPFILE' <<<"$out" | sed 's/^/    /' || true
    if ! grep -q '^APPFILES_OK' <<<"$out"; then
      APPFILES_WHY=$(sed -n 's/^APPFILES_FAIL //p' <<<"$out" | tail -1)
      [ -n "$APPFILES_WHY" ] || APPFILES_WHY="机器上没给结果：$(tail -1 <<<"$out")"
    fi
  fi
  rm -rf "$dir"
  [ -z "$APPFILES_WHY" ]
}
# <<< appfiles step
APPFILES_SWAPPED=0
if [ -n "$APP_CHANGED" ]; then
  echo "▶ 4.5/5 安装目录里这几个文件改了，重启前换上：$(tr '\n' ' ' <<<"$APP_CHANGED")"
  if ! pkg_appfiles_step; then
    echo "  ✋ 没换成（${APPFILES_WHY}），换了一半的放回去、current.txt 退回 $PREV，中继没动过：" >&2
    pkg_py "$PKG_DEPLOY" appfiles-back "$APP_WIN" | tail -1 | sed 's/^/      /' >&2 || true
    pkg_py "$PKG_DEPLOY" back "$APP_WIN" "$PREV" | tail -1 | sed 's/^/      /' >&2 || true
    exit 8
  fi
  APPFILES_SWAPPED=1
else
  echo "    安装目录里的 launch.py / switch.py / legacy.py / handover 都没变，不动它们"
fi

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
       Where-Object { $_.CommandLine -like '*ArkRelay\launch.py*' -and $_.CommandLine -notlike '*relaunch*' }
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
WATCH_OUT=$(mktemp)
pkg_restart
grep -q 'STOPPED_OK=True' <<<"$OUT" \
  && echo "    停止确认：旧的已退出" \
  || echo "    停止确认：没等到旧的退出（继续启动了）"
FAILED_WHY=""
if [ "$STATE" != "Running" ] || [ "$CURRENT" != "$NEW" ]; then
  FAILED_WHY="新版本没起来（中继：${STATE:-未知}，current.txt：${CURRENT:-读不到}，应为 $NEW）"
else
  echo "    启动确认：在跑，用的是 $CURRENT"
  if LOGB64=$(sed -n 's/^LOG=//p' <<<"$OUT") && [ -n "$LOGB64" ]; then
    printf '%s' "$LOGB64" | base64 -d 2>/dev/null | sed 's/^/    /' || true
  fi
  echo "▶ 5.2/5 上线后盯 ${WATCH_S} 秒（不许重启、开机自检要全过、要挂上调度程序句柄）"
  pkg_py "$WATCH_PY" watch 'C:\ProgramData\ark-relay\relay.log' "$T0" "$WATCH_S" deploy --pkg \
    | tee "$WATCH_OUT" | sed 's/^/    /' || true
  grep -q '^WATCH_OK' "$WATCH_OUT" \
    || FAILED_WHY="上线后没稳住：$(sed -n 's/^WATCH_FAIL //p' "$WATCH_OUT" | tail -1)"
fi
if [ -n "$FAILED_WHY" ]; then
  echo "❌❌ $FAILED_WHY"
  echo "▶ 自动退回上一版 $PREV（current.txt 改回去，新文件夹留着查）"
  BACK=$(pkg_py "$PKG_DEPLOY" back "$APP_WIN" "$PREV" || true)
  printf '%s\n' "$BACK" | tail -2 | sed 's/^/    /'
  if [ "$APPFILES_SWAPPED" = 1 ]; then
    pkg_py "$PKG_DEPLOY" appfiles-back "$APP_WIN" | tail -1 | sed 's/^/    /' || true
  fi
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

# >>> watchdog step
# The watchdog service runs {app}\watchdog\ark_watchdog.py, outside the version folders,
# which until 10-11 only the installer wrote: a watchdog fix (d0c0e12b) needed setup.exe
# run again. Now a deploy brings it too, after the relay is live and watched, so a
# failure here never holds back the relay's own update. $1 is the installed file's sha1
# (info's WATCHDOG_SHA). An unchanged file sends nothing and runs nothing. A failure
# sets WATCHDOG_FAIL_WHY (deploy-relay.sh reports it and exits 14 after COS); the
# machine side has put the previous file back and started the service on it.
WATCHDOG_FAIL_WHY=""
pkg_watchdog_step() {
  local want out why
  want=$(pkg_sha1 "$WD_SRC")
  if [ "$1" = "$want" ]; then
    echo "    看门服务的文件没变（${want:0:8}），不动它"
    return 0
  fi
  echo "▶ 5.3/5 看门服务的文件改了（${1:0:8} → ${want:0:8}），换上新的并重启看门服务"
  if ! scp -q "${SSH_OPTS[@]}" "$WD_SRC" "${USER_AT}:C:/Users/Administrator/ark-watchdog-new.py"; then
    WATCHDOG_FAIL_WHY="看门服务的新文件没送上机器，机器上跑的还是旧的"
    return 0
  fi
  out=$(pkg_py "$PKG_DEPLOY" watchdog "$APP_WIN" "$want" "$WD_STAGED" || true)
  printf '%s\n' "$out" | grep -E '^(WATCHDOG|install:)' | sed 's/^/    /' || true
  if ! grep -q '^WATCHDOG=' <<<"$out"; then
    why=$(sed -n 's/^WATCHDOG_FAIL //p' <<<"$out" | tail -1)
    [ -n "$why" ] || why="机器上没给结果：$(tail -1 <<<"$out")"
    WATCHDOG_FAIL_WHY="看门服务没换成新的（${why}）$(sed -n 's/^WATCHDOG_RESTORED /；/p' <<<"$out" | tail -1)"
  fi
}
# <<< watchdog step
pkg_watchdog_step "$WD_SHA"

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
