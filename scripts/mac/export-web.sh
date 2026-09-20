#!/bin/zsh
# export-web.sh <sha|HEAD> <outdir> [<v>] — export web/ of a commit for a local phone test with the SAME stamp step as the
# release (T4): git archive → stamp-shell.py. The phone must never load an unstamped ?v=0 shell (HTTP cache serves it forever).
set -euo pipefail
HERE="$(cd "$(dirname "${0:A}")/../.." && pwd)"
SHA="${1:?sha}"; OUT="${2:?outdir}"; V="${3:-$(date +%Y%m%d%H%M%S)}"
mkdir -p "$OUT"; cd "$HERE"
git archive "$SHA" web | tar -x -C "$OUT"
python3 scripts/mac/stamp-shell.py "$OUT/web" "$V"
echo "  导出 $(git rev-parse --short "$SHA") → $OUT/web（戳 $V）"
