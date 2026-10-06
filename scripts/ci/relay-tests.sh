#!/usr/bin/env bash
# Every relay test, run exactly the way deploy-relay.sh's local test gate runs
# them - used by .github/workflows/relay-windows.yml on a GitHub-hosted Windows
# runner, and runnable on the Mac as it is:
#
#   scripts/ci/relay-tests.sh [--exclude test_x.py]...
#
# Why: the relay lives on a Windows machine that is on a few hours a day, and
# until 2026-10-07 the first time a new version met Windows was when that
# machine booted it. The test code itself is not copied here: the timing block
# (timed_test / run_one_test / run_tests_timed / test_speed_gate, with the
# pass rule "exit 0 and the last line says passed" and the 10 s / 30 s limits)
# is cut out of deploy-relay.sh, which marks it as self-contained for that, so
# the deploy gate and this job cannot drift apart. The order is the gate's:
# test_manifest_covers_tree.py alone first, then all the others 8 at a time.
# The one difference: the gate runs only the tests its selector maps to the
# change, this runs all of them (the gate's own fallback).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

EXCLUDE=()
while [ $# -gt 0 ]; do
  case "$1" in
    --exclude) EXCLUDE+=("$2"); shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

BLOCK=$(mktemp)
GATED=$(mktemp -d)
trap 'rm -rf "$GATED" "$BLOCK"' EXIT
sed -n '/^# >>> test timing/,/^# <<< test timing/p' "$ROOT/scripts/mac/deploy-relay.sh" >"$BLOCK"
if ! grep -q '^run_tests_timed()' "$BLOCK" || ! grep -q '^test_speed_gate()' "$BLOCK"; then
  echo "✗ the test timing block was not found in scripts/mac/deploy-relay.sh"
  exit 1
fi
# shellcheck source=/dev/null
. "$BLOCK"
export TEST_TIMES="$GATED/times"

cd "$ROOT/relay" || exit 1
echo "python3: $(command -v python3) ($(python3 -c 'import sys; print(sys.version.split()[0])'))"

if ! timed_test tests/test_manifest_covers_tree.py "$GATED/manifest.out"; then
  cat "$GATED/manifest.out"
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

rc=0
run_tests_timed "$GATED/tests.out" "$GATED/tests.wall" <"$GATED/run" || rc=$?
cat "$GATED/tests.out"
n=$(($(wc -l <"$GATED/run") + 1))
if [ "$rc" != 0 ]; then
  echo "✗ some of the $n tests failed (see above)"
  exit 1
fi
echo "$n tests passed (test_manifest_covers_tree.py + $((n - 1)) more); excluded: ${EXCLUDE[*]:-none}"
test_speed_gate "$TEST_TIMES" "$GATED/tests.wall" || exit 1
