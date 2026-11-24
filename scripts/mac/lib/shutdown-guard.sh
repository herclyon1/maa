# shellcheck shell=bash
# Shared Mac-side shutdown guard sourced by winps.sh, winrun.sh, and wingui.sh (launch branch only).

ARK_SG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARK_SG_PY="$ARK_SG_DIR/shutdown_guard.py"
ARK_SG_REPO="${ARK_SHUTDOWN_GUARD_REPO:-$(cd "$ARK_SG_DIR/../../.." && pwd)}"

ark_sg_detect() {
  local kind="$1"
  shift
  if [ "$kind" = "ps" ] || [ "$kind" = "cmd" ]; then
    printf '%s' "$1" | python3 -B "$ARK_SG_PY" detect "$kind"
  else
    python3 -B "$ARK_SG_PY" detect "$kind" "$@"
  fi
}

ark_sg_check_local() {
  local caller="$1"
  if [ -n "${ARK_SHUTDOWN_OVERRIDE:-}" ]; then
    python3 -B "$ARK_SG_PY" log-override "$caller" "$ARK_SHUTDOWN_OVERRIDE"
    echo "${caller}: shutdown guard overridden: ${ARK_SHUTDOWN_OVERRIDE}" >&2
    return 0
  fi
  local why
  if ! why="$(python3 -B "$ARK_SG_PY" check-local "$ARK_SG_REPO" 2>&1)"; then
    echo "${caller}: 拒绝关机——${why}。请先修完、上机部署并通过核验。" >&2
    return 5
  fi
  return 0
}

ark_sg_check_ssh1() {
  local caller="$1" user_at="$2"
  if [ -n "${ARK_SHUTDOWN_OVERRIDE:-}" ]; then
    return 0
  fi
  local why
  if ! why="$(python3 -B "$ARK_SG_PY" check-ssh1 "$ARK_SG_REPO" "$user_at" 2>&1)"; then
    echo "${caller}: 拒绝关机——${why}。禁止先关机再等下次开机自更新。" >&2
    return 5
  fi
  return 0
}

ark_sg_ps_snippet() {
  local busy_names="$1" out_file="${2:-}"
  python3 -B "$ARK_SG_PY" ps-snippet "$busy_names" "$out_file"
}

# Single-process fast path for winps/winrun/wingui:
# Sets ARK_SG_SNIPPET on exit 10 (allowed shutdown) and returns 0/10/5.
ark_sg_preflight() {
  local kind="$1" caller="$2" user_at="$3" busy="$4" out_file="$5" target="${6:-}" extra="${7:-}"
  ARK_SG_SNIPPET=""
  local rc=0
  if [ "$kind" = "ps" ] || [ "$kind" = "cmd" ]; then
    # shellcheck disable=SC2034
    ARK_SG_SNIPPET="$(printf '%s' "$target" | python3 -B "$ARK_SG_PY" preflight "$kind" "$caller" "$ARK_SG_REPO" "$user_at" "$busy" "$out_file")" || rc=$?
  else
    # shellcheck disable=SC2034
    ARK_SG_SNIPPET="$(python3 -B "$ARK_SG_PY" preflight "$kind" "$caller" "$ARK_SG_REPO" "$user_at" "$busy" "$out_file" "$target" "$extra")" || rc=$?
  fi
  return "$rc"
}
