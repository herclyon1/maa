#!/usr/bin/env bash
# Pull the game PC's record of one Beijing day and cut it into the day-replay corpus.
#
#   scripts/mac/pull-day.sh 2026-10-13                  # pull now, slice that day
#   scripts/mac/pull-day.sh 2026-10-12 --from <pull>    # re-slice an earlier pull, no machine
#   scripts/mac/pull-day.sh 2026-10-13 --dry-run        # print what would run, touch nothing
#   scripts/mac/pull-day.sh 2026-10-13 --keep-raw       # keep the unpacked pull afterwards
#
# Design: daysim design.md section 5 ("New day"). On the machine it only reads, except
# for its own archives in %TEMP%: tar.exe packs C:\ProgramData\ark-relay and the D:\ark
# logs the replay reads (the members of the 10-13 15:26 pull), each archive's SHA-256 is
# compared with the copy here and the archive is deleted from %TEMP%. Here it is unpacked
# under ~/Claude/daysim-corpus/_pull/<stamp>/ (tar keeps the true mtimes), with
# _pull/MANIFEST.json, and relay/tests/daysim/slice.py writes ~/Claude/daysim-corpus/<D>/
# plus relay/tests/daysim/days/<D>/{events.jsonl,seed.json}. A day that was still running
# at the pull (today, Beijing) ends at the pull. The unpacked pull is removed afterwards unless
# --keep-raw: the corpus keeps clones of what it uses.
#
# Secrets: .env is never packed; AUTO-MAS Config.json / ScriptConfig.json come through
# winrun.sh --get-safe (scripts/mac/redact.py); slice.py masks COS signed links and the
# other key shapes in its SECRET_PATTERNS on the way into the corpus.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

DAY="${1:?usage: pull-day.sh <YYYY-MM-DD> [--from <pull dir>] [--dry-run] [--keep-raw]}"
shift
FROM="" DRY=0 KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="${2:?--from needs a pull dir}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --keep-raw) KEEP=1; shift ;;
    *) echo "pull-day: unknown option $1" >&2; exit 2 ;;
  esac
done
[[ "$DAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "pull-day: day must be YYYY-MM-DD" >&2; exit 2; }

HOST="${ARK_HOST:-100.65.39.119}"
CORPUS="${DAYSIM_CORPUS:-$HOME/Claude/daysim-corpus}"
TODAY_BJ="$(TZ=Asia/Shanghai date +%F)"
[[ "$DAY" > "$TODAY_BJ" ]] && { echo "pull-day: $DAY has not begun in Beijing ($TODAY_BJ)" >&2; exit 2; }
PY="$("$HERE/lib/relay-python.sh")"

slice() {
  echo "▶ slice $DAY from $1"
  "$PY" -I "$REPO/relay/tests/daysim/slice.py" "$DAY" --daydata "$1" --corpus "$CORPUS"
}

if [ -n "$FROM" ]; then
  [ -f "$FROM/_pull/MANIFEST.json" ] || { echo "pull-day: $FROM has no _pull/MANIFEST.json" >&2; exit 2; }
  [ "$DRY" = 1 ] && { echo "would run: slice.py $DAY --daydata $FROM --corpus $CORPUS"; exit 0; }
  slice "$FROM"
  exit 0
fi

STAMP="$(TZ=Asia/Shanghai date +%Y%m%d-%H%M)"
RAW="$CORPUS/_pull/$STAMP"

# The archives: name, folder tar runs in, PowerShell that fills $m with the members, and
# extra tar options. Same members as the 10-13 15:26 pull (daydata MANIFEST "archives"),
# minus what the replay never reads (MaaEnd cpp-algo, AUTO-MAS frontend.log and logs\).
pack_ps1() {   # $1 name, $2 folder, $3 member PowerShell, $4 extra tar options (PowerShell array items)
  cat <<PS1
\$out = Join-Path \$env:TEMP 'daysim-$STAMP-$1.tar.zst'
Set-Location '$2'
$3
'PACK_START ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz') + ' n=' + \$m.Count
\$x = @($4)
& tar.exe --zstd -cf \$out @x @m 2>&1 | Select-Object -First 20
'TAR_RC ' + \$LASTEXITCODE
'PACK_END ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')
'OUT ' + \$out + ' bytes=' + (Get-Item \$out).Length
'SHA ' + (Get-FileHash -Algorithm SHA256 \$out).Hash
PS1
}
C_MEMBERS="\$m = @(Get-ChildItem -Force | Where-Object { \$_.Name -notmatch '\\.env' } | ForEach-Object { \$_.Name })"
C_EXCLUDE="'--exclude','*.env','--exclude','.env','--exclude','*.png','--exclude','*.zip','--exclude','*.webp','--exclude','*.jpg','--exclude','*.jpeg','--exclude','*.mp4','--exclude','*.dmp','--exclude','state/ww37','--exclude','*gofile.json'"
D1_MEMBERS="\$m = @('automas\\history','automas\\debug','okww\\data\\apps\\ok-ww\\working\\logs','maaend\\debug\\on_error','maaend\\debug\\record')
\$m += @(Get-ChildItem 'automas\\config' -File | Where-Object { \$_.Name -match '^(QueueConfig|PlanConfig|EmulatorConfig)' } | ForEach-Object { 'automas\\config\\' + \$_.Name })
\$m += @(Get-ChildItem 'maa\\debug' -File -Filter '*.log' | ForEach-Object { 'maa\\debug\\' + \$_.Name })
\$m += @(Get-ChildItem 'maaend\\debug' -File | Where-Object { \$_.Name -match '^(20\\d\\d-\\d\\d-\\d\\d-\\d+|go-service.*|mxu-.*)\\.log\$' } | ForEach-Object { 'maaend\\debug\\' + \$_.Name })"
D1_EXCLUDE="'--exclude','*.env','--exclude','*frontend.log'"
D2_MEMBERS="\$m = @(Get-ChildItem 'maaend\\debug' -File -Filter 'maafw*.log' | ForEach-Object { 'maaend\\debug\\' + \$_.Name })"
spec() {      # $1 archive name -> dir members extra dest
  case "$1" in
    c)  dir='C:\ProgramData\ark-relay' members="$C_MEMBERS" extra="$C_EXCLUDE" dest=C/ProgramData/ark-relay ;;
    d1) dir='D:\ark' members="$D1_MEMBERS" extra="$D1_EXCLUDE" dest=D/ark ;;
    d2) dir='D:\ark' members="$D2_MEMBERS" extra="" dest=D/ark ;;
  esac
}

if [ "$DRY" = 1 ]; then
  for name in c d1 d2; do
    spec "$name"
    echo "── archive $name → $RAW/$dest"
    pack_ps1 "$name" "$dir" "$members" "$extra"
  done
  echo "── then: Config.json / ScriptConfig.json via winrun.sh --get-safe; MANIFEST.json; slice.py $DAY"
  exit 0
fi

command -v zstd >/dev/null || { echo "pull-day: zstd missing (brew install zstd)" >&2; exit 1; }
mkdir -p "$RAW/_pull"
TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT
# Measured 10-13 15:26-15:29: packing took 37-48 s per archive on the machine; winps.sh's
# own 60 s would cut a bigger day short.
export WINPS_TIMEOUT=300
MANI="$RAW/_pull/archives.tsv"
: >"$MANI"
for name in c d1 d2; do
  spec "$name"
  pack_ps1 "$name" "$dir" "$members" "$extra" >"$TMPD/$name.ps1"
  echo "▶ pack $name on the machine"
  out="$("$HERE/winps.sh" --file "$TMPD/$name.ps1")"
  printf '%s\n' "$out" | sed 's/^/    /'
  remote="$(sed -n 's/^OUT \(.*\) bytes=.*/\1/p' <<<"$out" | tail -1)"
  want="$(sed -n 's/^SHA \([0-9A-Fa-f]*\).*/\1/p' <<<"$out" | tail -1 | tr 'A-F' 'a-f')"
  packed="$(sed -n 's/^PACK_END //p' <<<"$out" | tail -1)"
  [ -n "$remote" ] && [ -n "$want" ] || { echo "pull-day: archive $name was not made" >&2; exit 1; }
  scp -q "Administrator@${HOST}:$(printf '%s' "$remote" | tr '\\' '/')" "$TMPD/$name.tar.zst"
  got="$(shasum -a 256 "$TMPD/$name.tar.zst" | cut -d' ' -f1)"
  "$HERE/winps.sh" "Remove-Item -LiteralPath '$remote' -Force" >/dev/null
  [ "$got" = "$want" ] || { echo "pull-day: $name SHA-256 differs (machine $want, here $got)" >&2; exit 1; }
  mkdir -p "$RAW/$dest"
  zstd -dc "$TMPD/$name.tar.zst" | tar -xpf - -C "$RAW/$dest"
  printf '%s\t%s\t%s\t%s\n' "$name" "$want" "$(wc -c <"$TMPD/$name.tar.zst" | tr -d ' ')" "$packed" >>"$MANI"
done

# AUTO-MAS keeps keys in these two; they come masked, with the machine's mtime.
for f in Config.json ScriptConfig.json; do
  "$HERE/winrun.sh" --get-safe "D:\\ark\\automas\\config\\$f" >"$RAW/D/ark/automas/config/$f"
  ts="$("$HERE/winps.sh" "([DateTimeOffset](Get-Item 'D:\\ark\\automas\\config\\$f').LastWriteTimeUtc).ToUnixTimeSeconds()" | tail -1 | tr -d '\r ')"
  "$PY" -c 'import os, sys; t = int(sys.argv[2]); os.utime(sys.argv[1], (t, t))' "$RAW/D/ark/automas/config/$f" "$ts"
done

"$PY" - "$RAW" "$STAMP" "$HOST" <<'PY'
import json, sys
from pathlib import Path
raw, stamp, host = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
archives = {}
for line in (raw / "_pull" / "archives.tsv").read_text(encoding="utf-8").splitlines():
    name, sha, size, packed = line.split("\t")
    archives[name] = {"sha256": sha.upper(), "bytes": int(size), "packed": packed}
man = {"pulled_at_beijing": stamp, "machine": f"Administrator@{host} (scripts/mac/pull-day.sh)",
       "layout": "C/ProgramData/ark-relay/... and D/ark/... mirror the machine paths",
       "archives": archives, "redacted_locally": ["D/ark/automas/config/Config.json",
                                                   "D/ark/automas/config/ScriptConfig.json"]}
(raw / "_pull" / "MANIFEST.json").write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
PY

slice "$RAW"
if [ "$KEEP" = 0 ]; then
  rm -rf "$RAW"
  echo "▶ unpacked pull removed (--keep-raw keeps it)"
fi
echo "✅ $DAY: $CORPUS/$DAY and relay/tests/daysim/days/$DAY"
