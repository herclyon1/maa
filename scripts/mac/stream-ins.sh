#!/usr/bin/env bash
# 串流到 ins。画质参数与桌面上那几个启动器同源（scripts/mac/lib/moonlight-params.sh），
# 这里只多开一个左上角性能浮层，并且允许切鼠标模式。
#   stream-ins.sh              → 绝对鼠标（桌面/菜单，光标可本地渲染）
#   stream-ins.sh --relative   → 相对鼠标（游戏内转视角）
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/moonlight-params.sh
source "$HERE/lib/moonlight-params.sh"

MOUSE=--absolute-mouse
[[ "${1:-}" == "--relative" ]] && MOUSE=--no-absolute-mouse

# shellcheck disable=SC2086  # MOON_COMMON 是有意按空白拆成多个参数的
exec "$MOON" stream "$MOON_HOST" "$MOON_APP" \
  --resolution "$MOON_RES" --bitrate "$MOON_BITRATE" \
  --video-codec "$MOON_CODEC" "$MOON_YUV" \
  $MOON_COMMON \
  --performance-overlay \
  "$MOUSE"
