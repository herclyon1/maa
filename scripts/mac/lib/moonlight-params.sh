# shellcheck shell=bash
# shellcheck disable=SC2034  # 这些变量是给 source 它的脚本用的
# 串流参数只写这一处。用法：`source scripts/mac/lib/moonlight-params.sh`
#
# 为什么（2026-09-08 审出来）：同一套参数原来抄在两个地方——
# `make-stream-apps.sh`（生成桌面上那几个启动器）和 `stream-ins.sh`（命令行直接串）。
# 改了码率只改一处，另一处照旧，而两处**都能正常启动**，谁都不会报错，
# 只有画质莫名其妙对不上。参数分歧是静默的，所以收到一处。
#
# --absolute-mouse 为什么重要（2026-08-30 定位）：相对模式发位移增量，走可靠有序传输，
# 丢包时增量永久丢失且队头阻塞，190ms 往返一次能卡 400ms+，症状是「画面不卡但拖鼠标断成几截」。
# 绝对模式发绝对坐标，丢下一个包就自愈。游戏里转视角要相对模式，进游戏按 Ctrl+Alt+Shift+M 切。
MOON=/Applications/Moonlight.app/Contents/MacOS/Moonlight
MOON_HOST=100.65.39.119
MOON_APP=Desktop

# 画面与解码：两边完全一样的那部分
MOON_COMMON='--fps 60 --video-decoder hardware --hdr
             --no-vsync --no-frame-pacing --no-game-optimization
             --display-mode borderless --keep-awake'

# 默认档：桌面启动器和命令行都用这一档，除非调用方另给
MOON_RES=2880x1864
MOON_BITRATE=70000
MOON_CODEC=AV1
MOON_YUV=--no-yuv444
