#!/usr/bin/env bash
# accept-batch.sh <label> <ref>... — merge several branches/shas into the current worktree (one at a time, abort and report on conflict),
# then run the headless acceptance ONCE for light and dark (BOARD SPEED-summary §二 2: batch merges, one full run per batch).
# Output: per-ref merge line, then the accept counts; outputs land in $OUT (default: scratchpad-like dir given by ACCEPT_OUT).
set -u
L="$1"; shift
W="$(cd "$(dirname "$0")/../.." && pwd)"; OUT="${ACCEPT_OUT:-/tmp/accept-batch}"; mkdir -p "$OUT"
cd "$W"
for r in "$@"; do
  if git merge -q --no-edit "$r" >/dev/null 2>&1; then echo "merged $r -> $(git rev-parse --short HEAD)"; else echo "CONFLICT on $r — aborting this merge, the rest of the batch continues"; git merge --abort 2>/dev/null; fi
done
( exec python3 "$W/scripts/mac/serve.py" "$W/web" "${ACCEPT_PORT:-8931}" >"$OUT/serve-$L.log" 2>&1 ) & SRV=$!; sleep 2
for th in light dark; do
  for try in 1 2; do
    arg=""; [ $th = dark ] && arg=dark
    timeout 300 python3 "$W/scripts/mac/accept-run.py" "http://127.0.0.1:${ACCEPT_PORT:-8931}/" $arg > "$OUT/accept-$L-$th-try$try.txt" 2>&1
    p=$(grep -c '^✓' "$OUT/accept-$L-$th-try$try.txt"); f=$(grep -c '^✗' "$OUT/accept-$L-$th-try$try.txt")
    echo "accept $th (try $try): pass=$p fail=$f"; grep '^✗' "$OUT/accept-$L-$th-try$try.txt" | cut -c1-200
    [ "$f" = "0" ] && [ "$p" -gt 200 ] && break
  done
done
kill $SRV 2>/dev/null; echo "done $L $(git rev-parse --short HEAD) $(date '+%H:%M:%S')"
