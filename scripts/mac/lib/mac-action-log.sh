# shellcheck shell=bash
# One line per call of a Mac-side script that drives the game PC, in one local file:
#
#   ~/.cache/ark-relay/mac_actions.log   (ARK_ACTION_LOG overrides it; mode 0600)
#
# Why: on 2026-11-19 22:32 (Beijing) the relay's farm watchdog relaunched OK-WW and
# alarmed because another session was driving the game screen, and the session
# answering the alarm spent a quarter of an hour finding that out. With this file the
# question "did someone on the Mac just touch the machine" takes one grep: time,
# script, its arguments (secrets masked, first 120 characters, one line), who called
# it (the Claude session id if there is one, the parent process chain otherwise) and
# the working directory.
#
# Sourced by the entry scripts (wingui, winps, winrun, order-now, order, run-one,
# estop, okww-task, adbdo, deploy-relay); call `ark_action_log "$@"` right after `set`.
#
# It must never fail or disturb its caller, whatever the caller's `set -euo pipefail`,
# environment or arguments: the body runs in a subshell with those options off, no
# stdin, no stdout (winrun.sh --get pipes its stdout), no stderr, and the call returns
# 0. Before 2026-11-20 an argument with a non-UTF-8 byte made `tr` fail under
# LC_CTYPE=UTF-8 and a missing HOME tripped `set -u`, and either one ended the caller.
#
# Secrets: the arguments go through scripts/mac/redact.py's redact_text (KEY=value by
# key name), plus `Bearer <token>`, plus adbdo.sh's `text <what is typed>` (often a
# code or a password), which is masked whole. If python3 or redact.py is not there,
# the arguments are not written at all. Local only - nothing here is sent anywhere.

ARK_ACTION_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || ARK_ACTION_LIB_DIR=""

# argv: <dir holding redact.py> <calling script's name> <its arguments...>; prints one
# line of at most 120 characters, secrets masked.
ARK_ACTION_PY='
import re, sys
sys.path.insert(0, sys.argv[1])
from redact import MASK, redact_text
me, args = sys.argv[2], sys.argv[3:]
if me == "adbdo.sh" and args[:1] == ["text"]:
    args = ["text", MASK]
s = re.sub(r"[\r\n\t]+", " ", " ".join(args))
# Bearer first: redact_text would mask the word "Bearer" as the value and leave the token.
s = re.sub(r"(?i)\b(bearer|basic)(\s+)[^\s\x27\x22]{6,}", lambda m: m.group(1) + m.group(2) + MASK, s)
s = redact_text(s)
sys.stdout.buffer.write(s[:120].encode("utf-8", "replace"))
'

ark_action_log() {
  (
    set +e +u +o pipefail
    umask 077
    file="${ARK_ACTION_LOG:-}"
    if [ -z "$file" ]; then
      [ -n "${HOME:-}" ] || exit 0
      file="$HOME/.cache/ark-relay/mac_actions.log"
    fi
    [ "$file" = /dev/null ] && exit 0
    me=$(basename -- "$0")
    if [ -n "$ARK_ACTION_LIB_DIR" ] && [ -f "$ARK_ACTION_LIB_DIR/../redact.py" ]; then
      args=$(python3 -I -c "$ARK_ACTION_PY" "$ARK_ACTION_LIB_DIR/.." "$me" "$@") || args="<参数没记：脱敏没跑成>"
    else
      args="<参数没记：找不到 redact.py>"
    fi
    # The parent chain, nearest first, process names only: enough to tell a Claude
    # session's shell from Antigravity's terminal or a launchd job.
    chain="" pid="$PPID" n=0
    while [ -n "$pid" ] && [ "$pid" -gt 1 ] 2>/dev/null && [ "$n" -lt 6 ]; do
      name=$(ps -o comm= -p "$pid") || break
      chain="${chain:+$chain < }${name##*/}"
      pid=$(ps -o ppid= -p "$pid" | tr -d ' ') || break
      n=$((n + 1))
    done
    who="${CLAUDE_CODE_SESSION_ID:+claude:${CLAUDE_CODE_SESSION_ID:0:8}}"
    mkdir -p "$(dirname -- "$file")" || exit 0
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" \
      "$me" "$args" "${who:-?}" "$chain" "$PWD" >>"$file"
    chmod 600 "$file"
  ) </dev/null >/dev/null 2>&1 || true
  return 0
}
