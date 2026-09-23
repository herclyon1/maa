#!/usr/bin/env bash
# accept-batch.sh [--layer daily|release] [--full] [--no-run] [--base <sha>] <label> [<ref>...]   |   accept-batch.sh --gate <控件>[,…] — merge several branches/shas into the current worktree (one at a
# time; a conflict aborts that merge and the rest continues), then ONE headless run (light + dark in one Chrome, accept-run.py `both`), then
# attribute every red row (S6, scripts/mac/attribute-red.py): rows of controls nobody touched are recorded, not re-run, not messaged.
#   --layer daily   (default) run only the controls the batch touched (?only=…; a touched shared file → the whole suite); passes ?layer=daily
#   --layer release the whole suite, ?layer=release (accept.js's page section and everything else)
#   --full          the whole suite regardless of what changed
#   --no-run        merge and report the scope only
#   --gate <控件>[,…]  (BOARD A29, 2号's meeting4 knife) run by a worker in its own worktree before a self-merge: merge origin/night here (a
#                   conflict = 不可合), refuse a change to an A7 hook line (验收 adds those); a change to another shared file runs the WHOLE suite + attribute-red.py (A44 补), run ?only=<控件> light + dark UNSHARDED, compare the row
#                   counts (its own tags only) with scripts/mac/accept-baseline.json — written by 验收's green whole-suite batch runs, read-only
#                   here (2号 13:57 ③) — and the red rows
#                   → prints 可合 / 不可合 + the reason, and on 可合 the commit's first line「?only=… 亮 a/b 暗 c/d @ night <sha>」. Exit 0 = 可合.
# A whole-suite run is sharded (--shard $ACCEPT_SHARD, default 3). Outputs land in $ACCEPT_OUT (default $TMPDIR/accept-batch-<worktree>): accept-<label>-{light,dark}.txt,
# serve-<label>.log. The server port is a free one unless $ACCEPT_PORT is set (several sessions run this at once).
set -u
LAYER=daily; FULL=0; RUN=1; BASE0=; GATE=
while [ $# -gt 0 ]; do case "$1" in
  --layer) LAYER="$2"; shift 2;; --base) BASE0="$2"; shift 2;; --gate) GATE="$2"; shift 2;; --full) FULL=1; shift;; --no-run) RUN=0; shift;; *) break;; esac; done
W="$(cd "$(dirname "$0")/../.." && pwd)"; OUT="${ACCEPT_OUT:-${TMPDIR:-/tmp}/accept-batch-$(basename "$W")}"; mkdir -p "$OUT"; cd "$W" || exit 1   # outputs per worktree unless ACCEPT_OUT is set
PORT="${ACCEPT_PORT:-$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')}"   # a free port unless ACCEPT_PORT is set: several sessions run this at once
BASELINE="$W/scripts/mac/accept-baseline.json"
serve() { ( exec python3 "$W/scripts/mac/serve.py" "$W/web" "$PORT" >"$OUT/serve-$1.log" 2>&1 ) & SRV=$!; disown $SRV; sleep 2; }
counts() { python3 - "$1" <<'PY'
import sys, re, collections
c = collections.Counter()
for line in open(sys.argv[1], encoding='utf-8'):
    m = re.search(r'⟨([a-z-]+)⟩\s*$', line)
    if line[:1] in '✓✗' and m and m.group(1) != 'core': c[m.group(1)] += 1
print(' '.join(f'{k}={v}' for k, v in sorted(c.items())) or 'none')
PY
}
if [ -n "$GATE" ]; then
  L="gate-$(echo "$GATE" | tr ',' '+')"; BR=$(git rev-parse --abbrev-ref HEAD)
  git fetch -q origin night || { echo "不可合：fetch origin night 失败"; exit 2; }
  if ! git merge -q --no-edit origin/night >/dev/null 2>&1; then echo "不可合：merge origin/night 冲突 — $(git diff --name-only --diff-filter=U | tr '\n' ' ')（别人文件里的冲突 → 停，等文件主；A29）"; git merge --abort 2>/dev/null; exit 2; fi
  NIGHT=$(git rev-parse --short origin/night)
  SCOPE=$(git diff --name-only origin/night HEAD | python3 "$W/scripts/mac/attribute-red.py" --scope)
  A7=$(git diff -U0 origin/night HEAD -- web/accept.js web/sw.js web/index.html scripts/mac/deploy-web.sh scripts/mac/stamp-shell.py | python3 -c "
import sys, re
f = ''; hits = []
for l in sys.stdin:
    if l.startswith('+++ b/'): f = l[6:].strip(); continue
    if not l[:1] in '+-' or l.startswith(('+++', '---')): continue
    if (f == 'web/accept.js' and 'ACCEPT.files' in l) or (f == 'web/sw.js' and 'SHELL' in l) \\
       or (f == 'web/index.html' and re.search(r'<script[^>]*\\bsrc=|<link[^>]*stylesheet|\\.src\\s*=\\s*\\S+\\.js', l)) \\
       or (f == 'scripts/mac/deploy-web.sh' and re.search(r'stamp|\\?v=', l)) or f == 'scripts/mac/stamp-shell.py':
        hits.append(f)
print(' '.join(sorted(set(hits))))")   # BOARD A7: the four hook lines only 验收 adds (A44 补 / meeting12d, D56)
  [ -n "$A7" ] && { echo "不可合：改动碰了 A7 保留给验收的挂钩行（$A7）→ status 写一行要加什么，交验收合（A7 / A44 补）"; exit 3; }
  if [ "$SCOPE" = FULL ]; then   # other shared files (view.js, tokens.css, index.html body …): the worker self-merges on the WHOLE suite + attribution (A44 补, D56)
    echo "gate $BR @ night $NIGHT · 碰共享文件 $(git diff --name-only origin/night HEAD | grep -E '^web/' | tr '\n' ' ')→ 整套（亮暗，分片 ${ACCEPT_SHARD:-3}）+ 红行归属"
    serve "$L"; T0=$(date +%s)
    timeout "${ACCEPT_TIMEOUT:-900}" python3 "$W/scripts/mac/accept-run.py" "http://127.0.0.1:$PORT/?layer=$LAYER" both --shard "${ACCEPT_SHARD:-3}" --out "$OUT/accept-$L" > "$OUT/accept-$L-run1.log" 2>&1
    kill $SRV 2>/dev/null
    for th in light dark; do f="$OUT/accept-$L-$th.txt"; p=$(grep -c '^✓' "$f" 2>/dev/null); n=$(grep -c '^✗' "$f" 2>/dev/null)
      [ "$((p + n))" = 0 ] && { echo "不可合：runner 无行（$th）— $(grep -m1 -E 'not ready|no result|failed' "$OUT/accept-$L-run1.log" | cut -c1-140)"; exit 4; }
      case $th in light) P_light=$p; N_light=$n ;; dark) P_dark=$p; N_dark=$n ;; esac
    done
    ATTR=$(python3 "$W/scripts/mac/attribute-red.py" --base origin/night --ref "$BR=$(git rev-parse --short HEAD)" "$OUT/accept-$L-light.txt" "$OUT/accept-$L-dark.txt")
    echo "$ATTR"
    echo "?only=FULL 亮 $P_light/$((P_light + N_light)) 暗 $P_dark/$((P_dark + N_dark)) · $(( $(date +%s) - T0 )) s"
    BAD=$(echo "$ATTR" | grep -E '^(归 |疑 |未定位)')   # red rows this branch can reach, or rows nobody can place → not mergeable; 记录不判 / 已记 rows go to the A16 register
    [ -n "$BAD" ] && { echo "不可合：本分支能碰到的红行 $(echo "$BAD" | grep -c .) 条（见上）"; exit 1; }
    echo "可合（整套，余下红行均为记录不判 / 已记）。"
    echo "提交信首行：?only=FULL 亮 $P_light/$((P_light + N_light)) 暗 $P_dark/$((P_dark + N_dark)) @ night $NIGHT"
    echo "下一步（A29）：git push origin HEAD:night（被拒 = 别人刚推过 → 回到本闸重跑）→ status 一行；30 分钟内自己看一次 night 日常层"
    exit 0
  fi
  ONLY="$GATE"; for c in $(echo "$SCOPE" | tr ',' ' '); do echo ",$ONLY," | grep -q ",$c," || ONLY="$ONLY,$c"; done
  [ "$ONLY" != "$GATE" ] && echo "提示：分支还改了 $SCOPE，闸门按 $ONLY 跑"
  echo "gate $BR @ night $NIGHT · ?only=$ONLY（亮暗各一遍，不分片）"
  serve "$L"; T0=$(date +%s)
  timeout "${ACCEPT_TIMEOUT:-900}" python3 "$W/scripts/mac/accept-run.py" "http://127.0.0.1:$PORT/?layer=$LAYER" both --only "$ONLY" --out "$OUT/accept-$L" > "$OUT/accept-$L-run1.log" 2>&1
  kill $SRV 2>/dev/null
  R=0; MSG=""
  for th in light dark; do f="$OUT/accept-$L-$th.txt"; p=$(grep -c '^✓' "$f" 2>/dev/null); n=$(grep -c '^✗' "$f" 2>/dev/null)
    [ "$((p + n))" = 0 ] && { echo "不可合：runner 无行（$th）— $(grep -m1 -E 'not ready|no result|failed' "$OUT/accept-$L-run1.log" | cut -c1-140)"; exit 4; }
    case $th in light) P_light=$p; N_light=$n ;; dark) P_dark=$p; N_dark=$n ;; esac   # named, not eval'd: shellcheck (and a reader) can see them
    [ "$n" != 0 ] && { R=1; MSG="$MSG 红行（$th）：$(grep '^✗' "$f" | cut -c1-110 | tr '\n' '；')"; }
    NOW=$(counts "$f"); KEY="$LAYER:FULL:$th"   # the baseline = the last green whole-suite batch run (验收 writes it; the gate never writes — 2号 13:57 ③)
    BASE=$(python3 -c "import json,sys,os; d=json.load(open(sys.argv[1])) if os.path.exists(sys.argv[1]) else {}; print(d.get(sys.argv[2],{}).get('counts',''))" "$BASELINE" "$KEY")
    if [ -z "$BASE" ]; then MSG="$MSG 无基线（$th；验收整套绿跑后 accept-baseline.json 才有，只看红行）；"
    else
      DROP=$(python3 -c "
b=dict(x.split('=') for x in '$BASE'.split() if '=' in x); n=dict(x.split('=') for x in '$NOW'.split() if '=' in x); want='$ONLY'.split(',')
print(' '.join(f'{k} {n.get(k,0)}<{v}' for k,v in b.items() if k in want and int(n.get(k,0))<int(v)))")
      [ -n "$DROP" ] && { R=1; MSG="$MSG 行数减少（$th，A9）：$DROP（基线 night $(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]]['night'])" "$BASELINE" "$KEY")）；"; }
    fi
  done
  echo "?only=$ONLY 亮 $P_light/$((P_light + N_light)) 暗 $P_dark/$((P_dark + N_dark)) · $(( $(date +%s) - T0 )) s"
  if [ "$R" = 1 ]; then echo "不可合：$MSG"; exit 1; fi
  echo "可合。$MSG"
  echo "提交信首行：?only=$ONLY 亮 $P_light/$((P_light + N_light)) 暗 $P_dark/$((P_dark + N_dark)) @ night $NIGHT"
  echo "下一步（A29）：git push origin HEAD:night（被拒 = 别人刚推过 → 回到本闸重跑） → status 一行；30 分钟内自己看一次 night 日常层。"
  exit 0
fi
L="$1"; shift
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
serve "$L"
ONLYARG=()
if [ "$ONLY" != FULL ]; then
  N=$(echo "$ONLY" | tr ',' '\n' | grep -c .); ONLYARG=(--only "$ONLY")
  [ "$N" -ge 2 ] && ONLYARG+=(--shard "$(( N < ${ACCEPT_SHARD:-3} ? N : ${ACCEPT_SHARD:-3} ))")   # several controls: shard them too (a tabbar-sized file alone is ~40 s; 2号 S2: --only and --shard combine)
else ONLYARG=(--shard "${ACCEPT_SHARD:-3}"); fi   # the whole suite runs sharded (2号 S2: 3 contexts per theme, 115 s → 46 s)
T0=$(date +%s)
for try in 1 2; do   # the second try is only for a runner failure (no rows), never for red rows (S6)
  timeout "${ACCEPT_TIMEOUT:-900}" python3 "$W/scripts/mac/accept-run.py" "http://127.0.0.1:$PORT/?layer=$LAYER" both ${ONLYARG[@]+"${ONLYARG[@]}"} --out "$OUT/accept-$L" > "$OUT/accept-$L-run$try.log" 2>&1
  rows=$(cat "$OUT/accept-$L-light.txt" "$OUT/accept-$L-dark.txt" 2>/dev/null | grep -c '^[✓✗]')
  [ "$rows" -gt 0 ] && break
  echo "runner produced no rows (try $try): $(grep -m1 -E 'not ready|no result|failed' "$OUT/accept-$L-run$try.log" | cut -c1-160)"
done
kill $SRV 2>/dev/null
for th in light dark; do f="$OUT/accept-$L-$th.txt"; echo "accept $th: pass=$(grep -c '^✓' "$f" 2>/dev/null) fail=$(grep -c '^✗' "$f" 2>/dev/null) $( [ "$ONLY" != FULL ] && echo "(only $ONLY)")"; done
echo "run time $(( $(date +%s) - T0 )) s"
python3 "$W/scripts/mac/attribute-red.py" --base "$BASE" ${REFS[@]+"${REFS[@]}"} "$OUT/accept-$L-light.txt" "$OUT/accept-$L-dark.txt"
for th in light dark; do f="$OUT/accept-$L-$th.txt"   # a WHOLE-SUITE run records the row counts per tag (✓ and ✗ both are rows present) as the gate's baseline (key layer:FULL:theme; the gate only reads)
  [ "$ONLY" = FULL ] && python3 - "$BASELINE" "$LAYER:FULL:$th" "$(counts "$f")" "$HEAD" <<'PY'
import json, os, sys, time
p, k, now, sha = sys.argv[1:]
d = json.load(open(p)) if os.path.exists(p) else {}
d[k] = {'counts': now, 'night': sha, 'at': time.strftime('%m-%d %H:%M')}
json.dump(d, open(p, 'w'), ensure_ascii=False, indent=1, sort_keys=True)
PY
done
echo "done $L $HEAD $(date '+%H:%M:%S')"
