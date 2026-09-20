#!/usr/bin/env bash
# accept-batch.sh [--layer daily|release] [--full] [--no-run] [--base <sha>] <label> [<ref>...] — merge several branches/shas into the current worktree (one at a
# time; a conflict aborts that merge and the rest continues), then ONE headless run (light + dark in one Chrome, accept-run.py `both`), then
# attribute every red row (S6, scripts/mac/attribute-red.py): rows of controls nobody touched are recorded, not re-run, not messaged.
#   --layer daily   (default) run only the controls the batch touched (?only=…; a touched shared file → the whole suite); passes ?layer=daily
#   --layer release the whole suite, ?layer=release (accept.js's page section and everything else)
#   --full          the whole suite regardless of what changed
#   --no-run        merge and report the scope only
# A whole-suite run is sharded (--shard $ACCEPT_SHARD, default 3). Outputs land in $ACCEPT_OUT (default /tmp/accept-batch): accept-<label>-{light,dark}.txt, serve-<label>.log. Port: $ACCEPT_PORT (8931).
set -u
LAYER=daily; FULL=0; RUN=1; BASE0=
while [ $# -gt 0 ]; do case "$1" in
  --layer) LAYER="$2"; shift 2;; --base) BASE0="$2"; shift 2;; --full) FULL=1; shift;; --no-run) RUN=0; shift;; *) break;; esac; done
L="$1"; shift
W="$(cd "$(dirname "$0")/../.." && pwd)"; OUT="${ACCEPT_OUT:-/tmp/accept-batch}"; mkdir -p "$OUT"; cd "$W"
BASE=${BASE0:-$(git rev-parse --short HEAD)}; REFS=()   # --base <sha>: the batch was merged already; scope and attribution from that sha
for r in "$@"; do
  if git merge -q --no-edit "$r" >/dev/null 2>&1; then echo "merged $r -> $(git rev-parse --short HEAD)"; REFS+=("--ref" "$r=$(git rev-parse --short "$r")")
  else echo "CONFLICT on $r — aborting this merge, the rest of the batch continues"; git merge --abort 2>/dev/null; fi
done
HEAD=$(git rev-parse --short HEAD)
# scope: which controls did the batch touch? (the same table as attribute-red.py OWNERS; a shared file → whole suite)
ONLY=$(git diff --name-only "$BASE" HEAD | python3 "$W/scripts/mac/attribute-red.py" --scope)
[ "$FULL" = 1 ] || [ "$LAYER" = release ] && ONLY=FULL
[ -z "$ONLY" ] && ONLY=NONE
echo "batch $L: $BASE -> $HEAD · layer $LAYER · scope ${ONLY}"
[ "$RUN" = 0 ] && { echo "done $L $HEAD (no run)"; exit 0; }
if [ "$ONLY" = NONE ]; then echo "nothing under web/ changed — no run"; echo "done $L $HEAD $(date '+%H:%M:%S')"; exit 0; fi
( exec python3 "$W/scripts/mac/serve.py" "$W/web" "${ACCEPT_PORT:-8931}" >"$OUT/serve-$L.log" 2>&1 ) & SRV=$!; disown $SRV; sleep 2
ONLYARG=()
if [ "$ONLY" != FULL ]; then
  N=$(echo "$ONLY" | tr ',' '\n' | grep -c .); ONLYARG=(--only "$ONLY")
  [ "$N" -ge 2 ] && ONLYARG+=(--shard "$(( N < ${ACCEPT_SHARD:-3} ? N : ${ACCEPT_SHARD:-3} ))")   # several controls: shard them too (a tabbar-sized file alone is ~40 s; 2号 S2: --only and --shard combine)
else ONLYARG=(--shard "${ACCEPT_SHARD:-3}"); fi   # the whole suite runs sharded (2号 S2: 3 contexts per theme, 115 s → 46 s)
T0=$(date +%s)
for try in 1 2; do   # the second try is only for a runner failure (no rows), never for red rows (S6)
  timeout 400 python3 "$W/scripts/mac/accept-run.py" "http://127.0.0.1:${ACCEPT_PORT:-8931}/?layer=$LAYER" both ${ONLYARG[@]+"${ONLYARG[@]}"} --out "$OUT/accept-$L" > "$OUT/accept-$L-run$try.log" 2>&1
  rows=$(cat "$OUT/accept-$L-light.txt" "$OUT/accept-$L-dark.txt" 2>/dev/null | grep -c '^[✓✗]')
  [ "$rows" -gt 0 ] && break
  echo "runner produced no rows (try $try): $(grep -m1 -E 'not ready|no result|failed' "$OUT/accept-$L-run$try.log" | cut -c1-160)"
done
kill $SRV 2>/dev/null
for th in light dark; do f="$OUT/accept-$L-$th.txt"; echo "accept $th: pass=$(grep -c '^✓' "$f" 2>/dev/null) fail=$(grep -c '^✗' "$f" 2>/dev/null) $( [ "$ONLY" != FULL ] && echo "(only $ONLY)")"; done
echo "run time $(( $(date +%s) - T0 )) s"
python3 "$W/scripts/mac/attribute-red.py" --base "$BASE" ${REFS[@]+"${REFS[@]}"} "$OUT/accept-$L-light.txt" "$OUT/accept-$L-dark.txt"
echo "done $L $HEAD $(date '+%H:%M:%S')"
