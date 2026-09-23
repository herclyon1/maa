#!/bin/sh
# webclip_serve.sh <sha> [port] [clip-id]: serve web/ of a maa-automation commit to the resident home-screen web clip on simulator A the
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
# Default clip: dd25 = 735B060F82CA4FE0B664FEE3BA81A139 → http://localhost:9320/?demo=1 (the only clip left on simulator A, 12:09).
HERE=$(cd "$(dirname "$0")" && pwd)
S=${SCRATCH:-${TMPDIR:-/tmp}/webclip-serve}; mkdir -p "$S"
UDID=${UDID:-8E793B8A-922B-46BC-86E2-E0F2BE845CA5}
REPO=${REPO:-$(cd "$HERE/../.." && pwd)}
SHA=$1; PORT=${2:-9320}; CLIP=${3:-735B060F82CA4FE0B664FEE3BA81A139}
[ -n "$SHA" ] || { echo "usage: webclip_serve.sh <sha> [port] [clip-id]"; exit 1; }
D=$S/web-$SHA
rm -rf "$D"; mkdir -p "$D"
git -C "$REPO" archive "$SHA" web | tar -x -C "$D" --strip-components 1
V=$(date +%Y%m%d%H%M%S)
python3 "$HERE/stamp-shell.py" "$D" "$V" || { echo "stamp failed — not serving"; exit 3; }
git -C "$REPO" log -1 --format='%h %ci %s' "$SHA" | cut -c1-120
kill "$(cat "$S/serve-$PORT.pid" 2>/dev/null)" 2>/dev/null; sleep 0.3
nohup python3 "$REPO/scripts/mac/serve.py" "$D" "$PORT" > "$S/serve-$PORT.log" 2>&1 &
echo $! > "$S/serve-$PORT.pid"; sleep 1.2
curl -s -o /dev/null -w "manifest %{http_code}\n" "http://localhost:$PORT/manifest.webmanifest"
curl -s "http://localhost:$PORT/" | grep -o "view.js?v=[0-9]*" | head -1
xcrun simctl terminate "$UDID" com.apple.webapp > /dev/null 2>&1; sleep 1
W=/Users/herclyon/Library/Developer/CoreSimulator/Devices/$UDID/data/Library/WebClips/$CLIP.webclip/Storage
[ -d "$W" ] || { echo "no clip storage at $W (clip id wrong?)"; exit 2; }
for o in "$W"/Default/*/; do [ "$(basename "$o")" = salt ] || rm -rf "$o"; done
rm -rf "$W/NetworkCache" "$W/MediaCache"
echo "clip $CLIP storage wiped: $(ls "$W" | tr '\n' ' ')"
echo "stamp $V — now tap the clip icon, then: 页面版本 == $V and $(basename "$S")/serve-$PORT.log lists every shell file"
