#!/usr/bin/env bash
# accept-batch.sh [--layer daily|release] [--full] [--no-run] <label> <ref>... — merge several branches/shas into the current worktree (one at a
# time; a conflict aborts that merge and the rest continues), then ONE headless run (light + dark in one Chrome, accept-run.py `both`), then
# attribute every red row (S6, scripts/mac/attribute-red.py): rows of controls nobody touched are recorded, not re-run, not messaged.
#   --layer daily   (default) run only the controls the batch touched (?only=…; a touched shared file → the whole suite); passes ?layer=daily
#   --layer release the whole suite, ?layer=release (accept.js's page section and everything else)
#   --full          the whole suite regardless of what changed
#   --no-run        merge and report the scope only
# Outputs land in $ACCEPT_OUT (default /tmp/accept-batch): accept-<label>-{light,dark}.txt, serve-<label>.log. Port: $ACCEPT_PORT (8931).
set -u
LAYER=daily; FULL=0; RUN=1
while [ $# -gt 0 ]; do case "$1" in
  --layer) LAYER="$2"; shift 2;; --full) FULL=1; shift;; --no-run) RUN=0; shift;; *) break;; esac; done
L="$1"; shift
W="$(cd "$(dirname "$0")/../.." && pwd)"; OUT="${ACCEPT_OUT:-/tmp/accept-batch}"; mkdir -p "$OUT"; cd "$W"
BASE=$(git rev-parse --short HEAD); REFS=()
for r in "$@"; do
  if git merge -q --no-edit "$r" >/dev/null 2>&1; then echo "merged $r -> $(git rev-parse --short HEAD)"; REFS+=("--ref" "$r=$(git rev-parse --short "$r")")
  else echo "CONFLICT on $r — aborting this merge, the rest of the batch continues"; git merge --abort 2>/dev/null; fi
done
HEAD=$(git rev-parse --short HEAD)
# scope: which controls did the batch touch? (the same table as attribute-red.py OWNERS; a shared file → whole suite)
ONLY=$(git diff --name-only "$BASE" HEAD | python3 - <<'PY'
import sys, re
ctl = {'motion':['motion.js','motion.css'],'nav':['nav.js','nav.css'],'nav-edge':['nav-edge.js'],'sheet':['sheet.js','sheet.css'],'menu':['menu.js','menu.css'],
       'topbar':['topbar.js','topbar.css'],'refresh':['refresh.js','refresh.css'],'glassbtn':['glassbtn.js','glassbtn.css'],'alert':['alert-glass.js','alert-glass.css','alert-prewarm.js'],
       'switch':['switch.js','switch.css'],'tabbar':['assets/lens/tab-lens.js','assets/lens/lens-webgl.js'],'tile':['tile.css'],
       'segctl':['controls.js','controls.css','seg-keys.css','seg-frames-logger.js']}
only = set(); full = False
for f in sys.stdin.read().split():
    if not f.startswith('web/'): continue                      # scripts / docs / tools do not change the page
    w = f[4:]
    m = re.match(r'accept-([a-z-]+)\.js$', w)
    if m: only.add(m.group(1)); continue
    hit = [c for c, fs in ctl.items() if w in fs or (w.startswith('assets/lens/') and c in ('tabbar', 'segctl'))]
    if hit: only.update(hit)
    else: full = True                                          # tokens.css / view.js / index.html / accept.js / anything unmapped
print('FULL' if full else ','.join(sorted(only)))
PY
)
[ "$FULL" = 1 ] || [ "$LAYER" = release ] && ONLY=FULL
[ -z "$ONLY" ] && ONLY=NONE
echo "batch $L: $BASE -> $HEAD · layer $LAYER · scope ${ONLY}"
[ "$RUN" = 0 ] && { echo "done $L $HEAD (no run)"; exit 0; }
if [ "$ONLY" = NONE ]; then echo "nothing under web/ changed — no run"; echo "done $L $HEAD $(date '+%H:%M:%S')"; exit 0; fi
( exec python3 "$W/scripts/mac/serve.py" "$W/web" "${ACCEPT_PORT:-8931}" >"$OUT/serve-$L.log" 2>&1 ) & SRV=$!; sleep 2
ONLYARG=(); [ "$ONLY" != FULL ] && ONLYARG=(--only "$ONLY")
T0=$(date +%s)
for try in 1 2; do   # the second try is only for a runner failure (no rows), never for red rows (S6)
  timeout 400 python3 "$W/scripts/mac/accept-run.py" "http://127.0.0.1:${ACCEPT_PORT:-8931}/?layer=$LAYER" both "${ONLYARG[@]}" --out "$OUT/accept-$L" > "$OUT/accept-$L-run$try.log" 2>&1
  rows=$(cat "$OUT/accept-$L-light.txt" "$OUT/accept-$L-dark.txt" 2>/dev/null | grep -c '^[✓✗]')
  [ "$rows" -gt 0 ] && break
  echo "runner produced no rows (try $try): $(grep -m1 -E 'not ready|no result|failed' "$OUT/accept-$L-run$try.log" | cut -c1-160)"
done
kill $SRV 2>/dev/null
for th in light dark; do f="$OUT/accept-$L-$th.txt"; echo "accept $th: pass=$(grep -c '^✓' "$f" 2>/dev/null) fail=$(grep -c '^✗' "$f" 2>/dev/null) $( [ "$ONLY" != FULL ] && echo "(only $ONLY)")"; done
echo "run time $(( $(date +%s) - T0 )) s"
python3 "$W/scripts/mac/attribute-red.py" --base "$BASE" "${REFS[@]}" "$OUT/accept-$L-light.txt" "$OUT/accept-$L-dark.txt"
echo "done $L $HEAD $(date '+%H:%M:%S')"
