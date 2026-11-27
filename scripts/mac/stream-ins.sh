#!/usr/bin/env bash
# Stream to ins via Moonlight.
#   stream-ins.sh              -> absolute mouse (desktop / menus)
#   stream-ins.sh --relative   -> relative mouse (3D camera rotation in game)
set -euo pipefail

MOON=/Applications/Moonlight.app/Contents/MacOS/Moonlight
MOON_HOST=100.65.39.119
MOON_APP=Desktop
MOON_RES=2880x1864
MOON_BITRATE=70000
MOON_CODEC=AV1
MOON_YUV=--no-yuv444
MOON_COMMON='--fps 60 --video-decoder hardware --hdr
             --no-vsync --no-frame-pacing --no-game-optimization
             --display-mode borderless --keep-awake'

MOUSE=--absolute-mouse
[[ "${1:-}" == "--relative" ]] && MOUSE=--no-absolute-mouse

# shellcheck disable=SC2086
exec "$MOON" stream "$MOON_HOST" "$MOON_APP" \
  --resolution "$MOON_RES" --bitrate "$MOON_BITRATE" \
  --video-codec "$MOON_CODEC" "$MOON_YUV" \
  $MOON_COMMON \
  --performance-overlay \
  "$MOUSE"
