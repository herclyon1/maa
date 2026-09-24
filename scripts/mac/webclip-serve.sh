#!/bin/sh
# webclip_serve.sh <sha> [port] [clip-id] (run end: webclip_serve.sh done [port]): serve web/ of a maa-automation commit to the resident home-screen web clip on simulator A the
# way a deploy would — T5 (2026-09-20), the fix for the 09-20 morning "旧壳" run (the ?v=0 shell scripts never left WebKit's cache):
#   1. `git archive <sha> web` into the scratchpad;
#   2. stamp every ?v= reference with the step deploy-web.sh / export-web.sh run (stamp-shell.py: every .js/.css/.png/.svg/.webmanifest
#      ?v= in index.html, the manifest icons, sw.js's CACHE name; exits non-zero if a ?v=0 survives — the old per-name webclip_stamp.py
#      missed the segmented-lens assets/lens/seg-f-*.png, 2026-09-23 17:10; no gh-pages push);
#   3. serve it with night's scripts/mac/serve.py on <port> (default 9320);
#   4. terminate Web.app (com.apple.webapp) and wipe the clip's site data: Storage/Default/<origin>/ (LocalStorage, CacheStorage,
#      ServiceWorkers), NetworkCache, MediaCache — so the next launch must fetch the stamped shell;
#   5. print the stamp. Then tap the clip icon (simulator tool) and check: the page's 「页面版本」row = the stamp, and
#      `tail scratchpad/serve-<port>.log` shows every shell file (controls / motion / nav / nav-edge / sheet / menu / topbar / refresh /
#      glassbtn / switch / alert-glass / tab-lens / tile.css …) fetched with 200 — both, or the run does not count.
# One resident clip per simulator, reused for every commit (serve a new sha to the same port; never add another icon): A = dd25
# (735B060F…) on 9320; B = UDID=C9827365-571F-4440-9844-6A44BC8D972A, B9322 (A90FF59F…) on 9322. Without [clip-id] the clip is the one
# whose URL is on <port> on that simulator (sim-webclips.py <UDID> <port>); none there → stop and say so — add a clip in Safari only
# then, once, and reuse it from then on (用户 2026-09-24 01:57「还要留下了复用的啊」; `sim-webclips.py A` lists what already exists).
HERE=$(cd "$(dirname "$0")" && pwd)
S=${SCRATCH:-${TMPDIR:-/tmp}/webclip-serve}; mkdir -p "$S"
UDID=${UDID:-8E793B8A-922B-46BC-86E2-E0F2BE845CA5}
REPO=${REPO:-$(cd "$HERE/../.." && pwd)}
SHA=$1; PORT=${2:-9320}; CLIP=$3
# `webclip-serve.sh done [port]` = end of the run (BOARD A52): stop this port's server and close every web process left on the simulator.
if [ "$SHA" = "done" ]; then
  kill "$(cat "$S/serve-$PORT.pid" 2>/dev/null)" 2>/dev/null && echo "server on $PORT stopped"; rm -f "$S/serve-$PORT.pid"
  sh "$HERE/sim-webclean.sh" "$UDID"; exit $?
fi
[ -n "$SHA" ] || { echo "usage: webclip_serve.sh <sha> [port] [clip-id] | webclip_serve.sh done [port]"; exit 1; }
[ -n "$CLIP" ] || CLIP=$(python3 "$HERE/sim-webclips.py" "$UDID" "$PORT" | head -1)
[ -n "$CLIP" ] || { echo "no home-screen clip on port $PORT (sim-webclips.py $UDID lists the existing ones — reuse one of those ports)"; exit 2; }
sh "$HERE/sim-webclean.sh" "$UDID" | tail -1   # previous run's leftovers go before a new serve
D=$S/web-$SHA
rm -rf "$D"; mkdir -p "$D"
git -C "$REPO" archive "$SHA" web | tar -x -C "$D" --strip-components 1
V=$(date +%Y%m%d%H%M%S)
python3 "$HERE/stamp-shell.py" "$D" "$V" || { echo "stamp failed — not serving"; exit 3; }
git -C "$REPO" log -1 --format='%h %ci %s' "$SHA" | cut -c1-120
kill "$(cat "$S/serve-$PORT.pid" 2>/dev/null)" 2>/dev/null; sleep 0.3
# another session's server on the port (its own SCRATCH, so not the pid file above) would answer the curls below with ITS build and the
# bind of ours would fail in the log only — the run then checks the wrong commit (老网页 19:03: 数据's 42ff6d0 still on 9320). Refuse.
HOLD=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)
[ -z "$HOLD" ] || { echo "port $PORT is held by pid $HOLD ($(lsof -p "$HOLD" -a -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')) — not ours; ask its owner to stop it"; exit 4; }
nohup python3 "$REPO/scripts/mac/serve.py" "$D" "$PORT" > "$S/serve-$PORT.log" 2>&1 &
echo $! > "$S/serve-$PORT.pid"; sleep 1.2
[ "$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)" = "$(cat "$S/serve-$PORT.pid")" ] || { echo "serve.py did not come up on $PORT:"; tail -2 "$S/serve-$PORT.log"; exit 4; }
curl -s -o /dev/null -w "manifest %{http_code}\n" "http://localhost:$PORT/manifest.webmanifest"
curl -s "http://localhost:$PORT/" | grep -o "view.js?v=[0-9]*" | head -1
xcrun simctl terminate "$UDID" com.apple.webapp > /dev/null 2>&1; sleep 1
W=/Users/herclyon/Library/Developer/CoreSimulator/Devices/$UDID/data/Library/WebClips/$CLIP.webclip/Storage
[ -d "$W" ] || { echo "no clip storage at $W (clip id wrong?)"; exit 2; }
# caches only: CacheStorage / ServiceWorkers per origin + NetworkCache / MediaCache. LocalStorage stays — it holds the mailbox name and PIN the
# page asks for once; wiping the whole origin (up to 2026-09-23) made every serve a new sign-in, and workers started a fresh port / clip each time
# instead (用户 18:19「正常来说不是创建一个，填一次就能重复利用了吗？」). The stamp already changes every shell URL and sw.js's CACHE name.
for o in "$W"/Default/*/*/; do rm -rf "$o/CacheStorage" "$o/ServiceWorkers"; done
rm -rf "$W/NetworkCache" "$W/MediaCache"
echo "clip $CLIP caches wiped (LocalStorage kept): $(ls "$W" | tr '\n' ' ')"
echo "stamp $V — now tap the clip icon, then: 页面版本 == $V and $(basename "$S")/serve-$PORT.log lists every shell file"
