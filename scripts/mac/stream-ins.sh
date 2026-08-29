#!/usr/bin/env bash
# 串流到 ins。画质参数与手工命令一致，唯一区别是鼠标模式。
#   stream-ins.sh              → 绝对鼠标(桌面/菜单，光标可本地渲染)
#   stream-ins.sh --relative   → 相对鼠标(游戏内转视角)
set -euo pipefail
MOUSE=--absolute-mouse
[[ "${1:-}" == "--relative" ]] && MOUSE=--no-absolute-mouse
exec /Applications/Moonlight.app/Contents/MacOS/Moonlight stream 100.65.39.119 Desktop \
  --resolution 2880x1864 --fps 60 --bitrate 70000 \
  --video-codec AV1 --hdr --no-yuv444 --video-decoder hardware \
  --no-vsync --no-frame-pacing --no-game-optimization \
  --display-mode borderless --performance-overlay --keep-awake \
  "$MOUSE"
