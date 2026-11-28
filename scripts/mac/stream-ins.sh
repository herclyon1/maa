#!/usr/bin/env bash
# Stream to ins via Moonlight.
#   stream-ins.sh              -> absolute mouse (desktop / menus)
#   stream-ins.sh --relative   -> relative mouse (3D camera rotation in game)
set -euo pipefail
export PATH="${PATH}:/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin"

# 第 1 层断电硬锁（08:40:00–08:45:59 CST 禁止向游戏机发起串流连接，返回 RC=78）
ARK_PC_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/powercut-guard.sh"
if [ -f "$ARK_PC_LIB" ]; then
  # shellcheck source=lib/powercut-guard.sh
  . "$ARK_PC_LIB"
  ark_powercut_guard 1 "stream-ins.sh" || exit $?
fi

# 允许单测通过 ARK_MOONLIGHT_BIN 注入桩程序，避免测试误启真实 Moonlight 串流
MOON="${ARK_MOONLIGHT_BIN:-/Applications/Moonlight.app/Contents/MacOS/Moonlight}"
MOON_HOST="${ARK_HOST:-100.65.39.119}"
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
