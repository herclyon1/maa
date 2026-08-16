#!/bin/bash
# Push the relay to the game machine the moment it is reachable, then restart it.
#
# The machine is off most of the day and has no wake timer of its own, so there
# is no moment anyone can plan to deploy at. This runs on a schedule, does
# nothing at all when the machine is down, and takes about ten seconds when it
# is up.
#
# It restarts the service on purpose: queued config changes are collected at
# service start, so a deploy that did not restart would leave the new code
# installed and the pending change waiting another whole day.
#
# Idempotent - deploying an unchanged tree is a no-op apart from the restart,
# and the restart is skipped when nothing was copied.

set -u
HOST="Administrator@100.65.39.119"
SRC="/Users/herclyon/Claude/maa-automation/relay"
DST="C:/ProgramData/ark-relay"
LOG="$HOME/Library/Logs/ark-deploy.log"
say() { printf '%s  %s\n' "$(date '+%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

ssh -o ConnectTimeout=8 -o BatchMode=yes "$HOST" "echo up" >/dev/null 2>&1 || exit 0

# Only ship when the remote differs, so an already-current machine is untouched.
changed=0
for f in ark_relay/maaend.py ark_relay/inbox.py ark_relay/engine.py \
         ark_relay/config.py ark_relay/plan.py ark_relay/core.py \
         ark_relay/collector.py ark_relay/commands.py ark_relay/notify.py \
         ark_relay/__main__.py service.py; do
  local_sum=$(shasum -a1 "$SRC/$f" 2>/dev/null | cut -d' ' -f1)
  [ -z "$local_sum" ] && continue
  remote_sum=$(ssh -o ConnectTimeout=8 "$HOST" \
      "certutil -hashfile \"${DST//\//\\}\\${f//\//\\}\" SHA1 2>nul | findstr /r \"^[0-9a-f]\"" \
      2>/dev/null | tr -d ' \r')
  if [ "$local_sum" != "$remote_sum" ]; then
    scp -q "$SRC/$f" "$HOST:$DST/$f" && { say "已更新 $f"; changed=1; }
  fi
done

if [ "$changed" -eq 1 ]; then
  # Stale bytecode has bitten this project before: a .pyc whose recorded source
  # mtime still matched was reused, and the machine ran code nobody had.
  ssh "$HOST" 'del /Q "C:\ProgramData\ark-relay\ark_relay\__pycache__\*.pyc" 2>nul' >/dev/null 2>&1
  ssh "$HOST" 'net stop ark-relay & net start ark-relay' >/dev/null 2>&1
  say "已重启中继（待办会在启动时被检查）"
else
  say "无需更新"
fi
