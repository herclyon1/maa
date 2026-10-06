#!/usr/bin/env bash
# Every relay test, run the way deploy-relay.sh's local test gate runs them -
# used by .github/workflows/relay-windows.yml on a GitHub-hosted Windows runner,
# and runnable on the Mac as it is:
#
#   scripts/ci/relay-tests.sh [--exclude test_x.py]...
#
# Why: the relay lives on a Windows machine that is on a few hours a day, and
# until 2026-10-07 the first time a new version met Windows was when that
# machine booted it. The timing block (timed_test / run_one_test /
# run_tests_timed / test_speed_gate, with the pass rule "exit 0 and the last line
# says passed" and the 10 s / 30 s limits) is cut out of deploy-relay.sh, which
# marks it as self-contained for that, and sourced unchanged. The order is the
# gate's: test_manifest_covers_tree.py alone first, then all the others 8 at a
# time. The gate runs only the tests its selector maps to the change; this runs
# all of them (the gate's own fallback).
#
# Two things are added on top, here only (deploy-relay.sh's own gate does not
# change): every test file runs under `timeout` (TEST_TIMEOUT_S, default 180 s),
# and every file prints one line the moment it finishes. Why: the first Windows
# run (2026-10-07, run 37516174208) printed the python3 line and then nothing
# for 15 minutes until the job was cancelled - the gate collects all test output
# in a file printed at the end, and nothing bounds a single test, so there was
# no telling which test hung.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

EXCLUDE=()
while [ $# -gt 0 ]; do
  case "$1" in
    --exclude) EXCLUDE+=("$2"); shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if ! command -v timeout >/dev/null; then
  echo "✗ no timeout command on PATH (GNU coreutils in Git Bash / Linux, /usr/bin/timeout on macOS)"
  exit 1
fi
export TEST_TIMEOUT_S="${TEST_TIMEOUT_S:-180}"

BLOCK=$(mktemp)
GATED=$(mktemp -d)
trap 'rm -rf "$GATED" "$BLOCK"' EXIT
sed -n '/^# >>> test timing/,/^# <<< test timing/p' "$ROOT/scripts/mac/deploy-relay.sh" >"$BLOCK"
for fn in timed_test run_one_test run_tests_timed test_speed_gate; do
  if ! grep -q "^$fn()" "$BLOCK"; then
    echo "✗ the test timing block (with $fn) was not found in scripts/mac/deploy-relay.sh"
    exit 1
  fi
done
# shellcheck source=/dev/null
. "$BLOCK"
# The speed limits are the Mac deploy gate's; a GitHub Windows runner is slower, so CI may widen them
# (CI_TEST_FILE_MAX_S / CI_TEST_WALL_MAX_S). The pass / fail of each test is unchanged.
TEST_FILE_MAX_S=${CI_TEST_FILE_MAX_S:-$TEST_FILE_MAX_S}
TEST_WALL_MAX_S=${CI_TEST_WALL_MAX_S:-$TEST_WALL_MAX_S}
export TEST_TIMES="$GATED/times"

# The block's timed_test with the python run bounded: `timeout -k 10 N` sends
# TERM after N seconds and KILL 10 s later (only this short form, which GNU and
# macOS timeout share); exit 124 / 137 means it was cut off. The exit status and
# seconds are also left in TT_RC / TT_SECS for run_one_test below.
timed_test() {
  local secs rc=0 TIMEFORMAT=%2R
  secs=$( { time timeout -k 10 "$TEST_TIMEOUT_S" python3 "$1" >"$2" 2>&1; } 2>&1 ) || rc=$?
  TT_RC=$rc TT_SECS=$secs
  if [ -n "${TEST_TIMES:-}" ]; then
    printf '%s %s\n' "$secs" "$(basename "$1")" >>"$TEST_TIMES"
  fi
  return "$rc"
}
# The block's run_one_test (its pass rule untouched) renamed, and a run_one_test
# that calls it and then prints "<name> PASS|FAIL <secs>s" or "TIMEOUT <name>" -
# in one printf, so lines from the 8 parallel runs do not mix.
eval "$(declare -f run_one_test | sed '1s/^run_one_test /gate_run_one_test /')"
run_one_test() {
  local f="$1" name out details rc=0
  name=$(basename "$f")
  out=$(mktemp)
  TT_RC=0 TT_SECS='?'
  gate_run_one_test "$f" >"$out" 2>&1 || rc=$?
  details=$(cat "$out")
  rm -f "$out"
  [ -z "$details" ] || details="$details"$'\n'
  if [ "$TT_RC" = 124 ] || [ "$TT_RC" = 137 ]; then
    printf '%sTIMEOUT %s (over %s s)\n' "$details" "$name" "$TEST_TIMEOUT_S"
    return 1
  fi
  if [ "$rc" != 0 ]; then
    printf '%s%s FAIL %ss\n' "$details" "$name" "$TT_SECS"
    return 1
  fi
  printf '%s%s PASS %ss\n' "$details" "$name" "$TT_SECS"
}
export -f timed_test gate_run_one_test run_one_test

cd "$ROOT/relay" || exit 1
echo "python3: $(command -v python3) ($(python3 -c 'import sys; print(sys.version.split()[0])')); limit ${TEST_TIMEOUT_S} s per test file"

if ! run_one_test tests/test_manifest_covers_tree.py; then
  echo "✗ test_manifest_covers_tree.py failed"
  exit 1
fi

for f in tests/test_*.py; do
  [ "$f" = tests/test_manifest_covers_tree.py ] || echo "$f"
done >"$GATED/all"
: >"$GATED/skip"
for x in ${EXCLUDE[@]+"${EXCLUDE[@]}"}; do
  if ! grep -qxF "tests/$x" "$GATED/all"; then
    echo "✗ --exclude $x: no such test file (a stale exclusion hides nothing; drop it)"
    exit 1
  fi
  echo "tests/$x" >>"$GATED/skip"
done
grep -vxF -f "$GATED/skip" "$GATED/all" >"$GATED/run"

# run_tests_timed's line, except that the test lines go straight to this
# script's stdout instead of into a file printed at the end; the wall seconds
# still go to the file test_speed_gate reads.
rc=0
TIMEFORMAT=%2R
{ time xargs -P 8 -I{} bash -c 'run_one_test "$1"' _ {} 2>&1; } 2>"$GATED/tests.wall" <"$GATED/run" || rc=$?
n=$(($(wc -l <"$GATED/run") + 1))
if [ "$rc" != 0 ]; then
  echo "✗ some of the $n tests failed or timed out (see the FAIL / TIMEOUT lines above)"
  exit 1
fi
echo "$n tests passed (test_manifest_covers_tree.py + $((n - 1)) more); excluded: ${EXCLUDE[*]:-none}"
test_speed_gate "$TEST_TIMES" "$GATED/tests.wall" || exit 1
