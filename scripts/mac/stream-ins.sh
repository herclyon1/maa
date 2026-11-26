#!/usr/bin/env bash
# HARDLOCK-1126 硬锁（用户 11-26 令「所有目前东西必须标记为不可用状态加上硬锁」）：锁着或锁模块读不出就以 75 退出，什么都不做。
/opt/homebrew/bin/python3 -I /Users/herclyon/Money/审批记录/硬锁/hardlock.py check outbound_tools "$(basename "$0") $*" || exit 75
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
