#!/usr/bin/env bash
# Watch a run on the game machine; print one line per event.
#
# Replaces the throwaway monitor loops that kept failing (2026-08-21): they
# printed mojibake for the Chinese user directories, reported bogus FAILs when
# a lookup returned nothing, and stayed silent instead of saying anything when
# the machine powered off mid-run.
#
#   ARK_HOST=100.65.39.119 scripts/mac/watch-run.sh [YYYY-MM-DD]
#
#   OK <stem> <script> <result>     a run finished successfully
#   FAIL <stem> <script> <result>   a run failed
#   UPD <stem> MaaEnd <result>      AUTO-MAS installed a MaaEnd update (not a run)
#   OFFLINE                         machine stopped responding (exit 2)
#   DONE                            no game process left (exit 0)
set -uo pipefail
export PATH="${PATH}:/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin"
MAC_PY="${MAC_PY:-/opt/homebrew/bin/python3}"
if [ ! -x "$MAC_PY" ]; then
  echo "watch-run: 找不到最新版 Homebrew Python（${MAC_PY}），拒绝回退系统旧版" >&2
  exit 1
fi
# 第 1 层断电硬锁（08:40:00–08:45:59 CST 禁止向游戏机发远程命令，返回 RC=78）
ARK_PC_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/powercut-guard.sh"
if [ -f "$ARK_PC_LIB" ]; then
  # shellcheck source=lib/powercut-guard.sh
  . "$ARK_PC_LIB"
  ark_powercut_guard 1 "watch-run.sh" || exit $?
fi

HOST="${ARK_HOST:?set ARK_HOST to the game machine Tailscale IP}"
USER_AT="Administrator@${HOST}"
# 游戏机现役中继无版本号滚动 Python 入口（彻底废弃 3.12.0 旧 automas\environment\python 路径）
PY_EXE='C:\Program Files\ArkRelay\runtime\python\python.exe'
PROBE_REMOTE='C:\Users\Administrator\ark-probe.py'
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DAY="${1:-$(TZ=Asia/Shanghai date +%F)}"
INTERVAL="${WATCH_INTERVAL:-120}"

remote() {
  ssh -o ConnectTimeout=10 -o BatchMode=yes "$USER_AT" "$1" 2>/dev/null | tr -d '\r'
}

if ! scp -q -o ConnectTimeout=10 "$HERE/windows/run-probe.py" \
      "${USER_AT}:C:/Users/Administrator/ark-probe.py"; then
  echo "OFFLINE  cannot reach the machine to install the probe"
  exit 2
fi

echo "watching $DAY on $HOST every ${INTERVAL}s"
seen=""
upd_seen=""
idle=0
miss=0
while true; do
  out=$(remote "\"$PY_EXE\" -X utf8 $PROBE_REMOTE $DAY")
  if [ -z "$out" ] && ! ping -c 2 -W 3 "$HOST" >/dev/null 2>&1; then
    miss=$((miss + 1))
    if [ "$miss" -ge 2 ]; then
      echo "OFFLINE  machine stopped responding"
      exit 2
    fi
    sleep "$INTERVAL"
    continue
  fi
  miss=0

  while IFS='|' read -r tag stem kind ok res; do
    # An update install is not a run: said once, and kept out of $seen, which
    # decides whether a run has been seen before DONE may fire.
    if [ "$tag" = "UPD" ]; then
      case "$upd_seen" in *"<$stem>"*) continue ;; esac
      upd_seen="$upd_seen<$stem>"
      echo "UPD  $stem $kind $(printf '%s' "$res" | "$MAC_PY" -c 'import json,sys; print(json.loads(sys.stdin.read()))' 2>/dev/null || printf '%s' "$res")"
      continue
    fi
    [ "$tag" = "REC" ] || continue
    case "$seen" in *"<$stem>"*) continue ;; esac
    seen="$seen<$stem>"
    # The probe escapes non-ASCII so it survives the machine's GBK console;
    # decode it here so a human reads the actual failure reason rather than
    # a wall of \uXXXX.
    text=$(printf '%s' "$res" | "$MAC_PY" -c 'import json,sys; print(json.loads(sys.stdin.read()))' 2>/dev/null || printf '%s' "$res")
    if [ "$ok" = "1" ]; then
      echo "OK   $stem $kind $text"
    else
      echo "FAIL $stem $kind $text"
    fi
  done <<< "$out"

  # Same list as BUSY_PROCS in relay/ark_relay/core/config.py; test_procnames.py pins
  # them together. This had three names, so a solo Wuthering Waves run read as
  # IDLE the whole way through and was called finished after six minutes.
  busy=$(remote 'tasklist /NH | findstr /i "MAA.exe MaaEnd.exe Endfield.exe Client-Win64-Shipping.exe ok-ww.exe dnplayer.exe" >nul 2>&1 && echo RUN || echo IDLE')
  if [ "$busy" = "IDLE" ] && [ -n "$seen" ]; then
    idle=$((idle + 1))
    if [ "$idle" -ge 3 ]; then
      remote 'del C:\Users\Administrator\ark-probe.py' >/dev/null
      echo "DONE  no game process left"
      exit 0
    fi
  else
    idle=0
  fi
  sleep "$INTERVAL"
done
