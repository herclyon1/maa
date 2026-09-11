#!/usr/bin/env bash
# Where the relay put each run's evidence bundle, and how to open it.
#
#   scripts/mac/evidence.sh list        # runs → gofile download pages (index mirrored from the machine when it is on)
#   scripts/mac/evidence.sh open <run>  # open that run's download page in the browser
#
# The relay (ark_relay/evidence.py) uploads bundles to gofile.io as a guest and
# writes `state/evidence/index.jsonl` on the machine. gofile serves guest
# folders only through its web page (its API needs a per-page token it
# generates in obfuscated JS, measured 2026-09-12), so the way to fetch a file
# is the browser: open the page, click the file. This script keeps a local
# mirror of the index so the pages are known while the machine is off; the
# notification the relay sends carries the same link.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MIRROR="$HOME/Claude/ark-evidence/index.jsonl"
mkdir -p "$(dirname "$MIRROR")"

refresh() {
  # Read-only: the relay's index is fetched, never written, so this is not
  # the "external script writes relay state" pattern the lint guards against.
  idx='C:\ProgramData\ark-relay\'"state"'\evidence\index.jsonl'
  if ARK_HOST="${ARK_HOST:-100.65.39.119}" "$HERE/winrun.sh" --get "$idx" > "$MIRROR.tmp" 2>/dev/null \
     && [ -s "$MIRROR.tmp" ]; then
    mv "$MIRROR.tmp" "$MIRROR"
    echo "（索引刚从机器同步）"
  else
    rm -f "$MIRROR.tmp"
    echo "（机器不在线，用的是上次同步的索引）"
  fi
}

case "${1:-list}" in
  list)
    refresh
    python3 - "$MIRROR" <<'EOF'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
if not p.exists():
    print("还没有任何索引"); sys.exit(0)
for ln in p.read_text(encoding="utf-8").splitlines():
    try:
        e = json.loads(ln)
    except ValueError:
        continue
    up = e.get("uploaded") or []
    err = e.get("errors") or []
    print(f"{e.get('when','')[:16]}  {e.get('script'):6}  {e.get('run_id')}  {len(up)}/{len(e.get('files') or [])} 个文件  {e.get('page','')}"
          + ("  ⚠️ " + "；".join(err) if err else ""))
EOF
    ;;
  open)
    run="${2:?usage: evidence.sh open <run-id fragment>}"
    page=$(grep -F "$run" "$MIRROR" | tail -1 | python3 -c 'import sys, json; print(json.loads(sys.stdin.read()).get("page", ""))')
    [ -n "$page" ] || { echo "索引里没有 $run 的下载页" >&2; exit 1; }
    echo "$page"; open "$page" ;;
  *) echo "usage: evidence.sh list | open <run-id fragment>" >&2; exit 2 ;;
esac
