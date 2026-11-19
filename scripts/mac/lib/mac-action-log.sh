# shellcheck shell=bash
# One line per call of a Mac-side script that drives the game PC, in one local file:
#
#   ~/.cache/ark-relay/mac_actions.log   (ARK_ACTION_LOG overrides it)
#
# Why: on 2026-11-19 22:32 (Beijing) the relay's farm watchdog alarmed (#184) because
# another session had taken the game screen over with wingui.sh and killed OK-WW, and
# the session answering the alarm spent a quarter of an hour finding that out. With
# this file the question "did someone on the Mac just touch the machine" takes one
# grep: time, script, its arguments (first 120 characters, one line), who called it
# (the Claude session id if there is one, the parent process chain otherwise) and
# the working directory.
#
# Sourced by the entry scripts (wingui, winps, winrun, order-now, order, run-one,
# estop, okww-task, adbdo); call `ark_action_log "$@"` right after `set`. It never
# fails the caller: a log that cannot be written is skipped without a word.
# Local only - nothing here is sent anywhere.

ark_action_log() {
  local file="${ARK_ACTION_LOG:-$HOME/.cache/ark-relay/mac_actions.log}"
  local args chain="" pid="$PPID" n=0 name who
  args=$(printf '%s ' "$@" | tr '\r\n\t' '   ' | cut -c1-120)
  # The parent chain, nearest first, process names only: enough to tell a Claude
  # session's shell from Antigravity's terminal or a launchd job.
  while [ -n "$pid" ] && [ "$pid" -gt 1 ] 2>/dev/null && [ "$n" -lt 6 ]; do
    name=$(ps -o comm= -p "$pid" 2>/dev/null) || break
    chain="${chain:+$chain < }${name##*/}"
    pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ') || break
    n=$((n + 1))
  done
  who="${CLAUDE_CODE_SESSION_ID:+claude:${CLAUDE_CODE_SESSION_ID:0:8}}"
  {
    mkdir -p "$(dirname "$file")" &&
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" \
      "$(basename "$0")" "${args% }" "${who:-?}" "$chain" "$PWD" >>"$file"
  } 2>/dev/null || true
}
