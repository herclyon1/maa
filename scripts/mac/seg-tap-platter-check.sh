#!/usr/bin/env bash
# seg-tap-platter-check.sh [web-dir] — README §0.8.12's fixed check: through a whole tap the segmented control's platter is visible on at
# least one side every tick (the DOM platter or the WebGL canvas). Serves web/ (or the given dir) on 127.0.0.1:8131, runs
# web/assets/lens/calib/tap-platter-check.js in an offscreen WKWebView (scripts/mac/wk/wksnapjs.swift, compiled on first use), prints the
# count of bad ticks and exits 1 on any. Needs Xcode's swiftc.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB="${1:-$HERE/web}"; WK="$HERE/scripts/mac/wk"; BIN="${TMPDIR:-/tmp}/wksnapjs-$(id -u)"
[ -x "$BIN" ] && [ "$BIN" -nt "$WK/wksnapjs.swift" ] || swiftc -O -o "$BIN" "$WK/wksnapjs.swift"
(cd "$WEB" && python3 -m http.server 8131 --bind 127.0.0.1 >/dev/null 2>&1 &)
sleep 0.6
OUT="$("$BIN" "http://127.0.0.1:8131/index.html?demo=1" "${TMPDIR:-/tmp}/tap-platter-check.png" 440 956 1 light "$WEB/assets/lens/calib/tap-platter-check.js" 4 "$WEB/assets/lens/calib/tap-platter-dump.js" 0.1 2>&1 | grep -v '^wrote' || true)"
pkill -f "http.server 8131" || true
echo "$OUT"
if echo "$OUT" | grep -q '"bad":0' && echo "$OUT" | grep -q '"done":true'; then echo "PASS: platter visible every tick"; else echo "FAIL: ticks with .lift on and the canvas clear (or the run did not finish)"; exit 1; fi
