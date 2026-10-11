#!/usr/bin/env bash
# shellcheck disable=SC2034  # SSH_OPTS USER_AT GATED FILES are read by deploy-pkg.sh
# scripts/mac/lib/deploy-pkg.sh, end to end, on the cloud Windows runner against the relay
# installed there (scripts/ci/package_switch_smoke.py runs this under Git Bash).
# deploy-pkg.sh is the Mac half of a deploy and reaches the machine over ssh/scp; here the
# machine is this runner, so those two are stand-ins that act locally
# (scripts/ci/fake_ssh.py runs the command line through cmd.exe, as Windows' OpenSSH
# does). Also stood in: python3 (the runner's is `python`) and tar's --no-mac-metadata
# (a bsdtar flag; Git's tar is GNU). Everything deploy-pkg.sh runs on the machine side -
# pkg_deploy.py, the restart PowerShell, deploy_watch.py - runs for real.
# The variables and the lap() it uses are deploy-relay.sh's (lines 22-43, 153, 291, 551).
set -euo pipefail
export MSYS_NO_PATHCONV=1           # pass C:\... and /tn arguments to Windows programs untouched
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE="$REPO/relay"
cd "$HERE"
SSH_OPTS=(-o ConnectTimeout=15)
USER_AT="Administrator@runner"
WATCH_S="${WATCH_S:-30}"
GATED=$(mktemp -d)
_TP=$SECONDS
lap() { printf '      （%d 秒）\n' "$((SECONDS-_TP))"; _TP=$SECONDS; }
FAKE_SSH=$(cygpath -w "$REPO/scripts/ci/fake_ssh.py")

# The runner's Python is a Windows program and MSYS_NO_PATHCONV is on, so absolute MSYS
# paths deploy-pkg.sh hands it (scripts/mac/lib/pkg_appfiles.py, the info file under
# $GATED, files for pkg_sha1) are turned into Windows paths here, as FAKE_SSH is.
python3() {
  local a=() x
  for x in "$@"; do case "$x" in /*) a+=("$(cygpath -w "$x")") ;; *) a+=("$x") ;; esac; done
  python "${a[@]}"
}
ssh() {
  while [ $# -gt 0 ]; do case "$1" in -o) shift 2 ;; -q) shift ;; *) break ;; esac; done
  shift                                         # user@host
  python "$FAKE_SSH" "$*"
}
scp() {
  local a=()
  while [ $# -gt 0 ]; do case "$1" in -o) shift 2 ;; -q) shift ;; *) a+=("$1"); shift ;; esac; done
  cp "${a[0]}" "$(cygpath -u "${a[1]#*:}")"
}
tar() {
  local a=() x
  for x in "$@"; do [ "$x" = --no-mac-metadata ] || a+=("$x"); done
  command tar "${a[@]}"
}

echo "▶ 1/5 重建 manifest"
python3 make-manifest.py
FILES=$(python3 -c "import json;print(' '.join(json.load(open('manifest.json'))['files']))")
# shellcheck source=../mac/lib/deploy-pkg.sh
source "$REPO/scripts/mac/lib/deploy-pkg.sh"
# deploy-relay.sh exits 14 on this after COS; here there is nothing after, so at once.
if [ -n "$WATCHDOG_FAIL_WHY" ]; then
  echo "WATCHDOG_FAIL_WHY=$WATCHDOG_FAIL_WHY"
  exit 14
fi
echo "DEPLOY_PKG_DONE NEW=$NEW"
