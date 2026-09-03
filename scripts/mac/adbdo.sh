#!/usr/bin/env bash
# 直接驱动游戏机上那台安卓模拟器（雷电里的明日方舟）。
#
# **为什么不用 winrun**：winrun 一次约 10 秒——scp 一个脚本过去、建一个计划
# 任务、再轮询产出文件。那一套是为了拿到**有桌面的交互会话**（见 memory
# relay-runs-in-session-0）。而 adb 是跟一个 TCP 端口说话，**不需要桌面**，
# 普通 ssh 就够。手动驱动游戏界面时一步一截图，一步 10 秒和一步 1 秒是
# 能不能干活的分界。2026-09-04 手动打保全时量的：winrun 9.9s，这里 1.1s。
#
# **为什么每次都先 connect**：LDPlayer 的 adb 连接会自己掉，掉了之后
# `adb devices` 是空的、`exec-out` 返回 0 字节、`dumpsys` 也空——看起来像
# 截图坏了，其实只是没连上。connect 是幂等的，白连一次不花钱。
#
# 用法：
#   adbdo.sh tap X Y                 点一下
#   adbdo.sh swipe X1 Y1 X2 Y2 [MS]  滑动
#   adbdo.sh key KEYCODE             按键（如 KEYCODE_BACK）
#   adbdo.sh shot [本地路径]          截图并取回（默认 ./shot.png）
#   adbdo.sh focus                   当前前台窗口
#   adbdo.sh raw <adb 参数...>        任意 adb 命令
#   adbdo.sh seq 'tap 100 200' 'sleep 2' 'tap 300 400' 'shot'
#                                    一次连发多步，**只走一趟 ssh**
set -euo pipefail

HOST="${ARK_HOST:-100.65.39.119}"
USER_AT="Administrator@${HOST}"
CM_PATH="${TMPDIR:-/tmp}/ark-cm-${HOST}"
SSH_OPTS=(-o ControlMaster=auto -o "ControlPath=${CM_PATH}" -o ControlPersist=300
          -o ConnectTimeout=20)
ADB='D:\LD-MRFZ\LDPlayer9\adb.exe'
DEV="127.0.0.1:7555"
REMOTE_PNG='C:\ProgramData\ark-shot.png'

run() { ssh "${SSH_OPTS[@]}" "$USER_AT" "$@"; }

# 一条命令里先 connect 再干活，省一趟往返。
with_connect() { run "\"$ADB\" connect $DEV >nul 2>&1 & $*"; }

fetch_shot() {
  local dest="${1:-shot.png}"
  with_connect "\"$ADB\" -s $DEV shell screencap -p /sdcard/ark.png & \
                \"$ADB\" -s $DEV pull /sdcard/ark.png $REMOTE_PNG >nul 2>&1" >/dev/null
  scp -q "${SSH_OPTS[@]}" "${USER_AT}:$(printf '%s' "$REMOTE_PNG" | tr '\\' '/')" "$dest"
  printf '%s  %s 字节\n' "$dest" "$(wc -c < "$dest" | tr -d ' ')"
}

case "${1:-}" in
  tap)    shift; with_connect "\"$ADB\" -s $DEV shell input tap $1 $2" >/dev/null ;;
  swipe)  shift; with_connect "\"$ADB\" -s $DEV shell input swipe $1 $2 $3 $4 ${5:-400}" >/dev/null ;;
  key)    shift; with_connect "\"$ADB\" -s $DEV shell input keyevent $1" >/dev/null ;;
  text)   shift; with_connect "\"$ADB\" -s $DEV shell input text '$1'" >/dev/null ;;
  focus)  with_connect "\"$ADB\" -s $DEV shell dumpsys window | findstr mCurrentFocus" ;;
  shot)   shift; fetch_shot "${1:-shot.png}" ;;
  raw)    shift; with_connect "\"$ADB\" -s $DEV $*" ;;
  seq)
    # 一趟 ssh 里按顺序做完，最后如果有 shot 再单独取回图。
    shift
    cmd=""
    want_shot=""
    for step in "$@"; do
      set -- $step
      case "$1" in
        tap)   cmd+="\"$ADB\" -s $DEV shell input tap $2 $3 & " ;;
        swipe) cmd+="\"$ADB\" -s $DEV shell input swipe $2 $3 $4 $5 ${6:-400} & " ;;
        key)   cmd+="\"$ADB\" -s $DEV shell input keyevent $2 & " ;;
        sleep) cmd+="ping -n $(( $2 + 1 )) 127.0.0.1 >nul & " ;;
        shot)  cmd+="\"$ADB\" -s $DEV shell screencap -p /sdcard/ark.png & \
                     \"$ADB\" -s $DEV pull /sdcard/ark.png $REMOTE_PNG >nul 2>&1 & "
               want_shot=1 ;;
        *) echo "seq 不认识这一步：$step" >&2; exit 2 ;;
      esac
    done
    with_connect "$cmd echo done" >/dev/null
    [ -n "$want_shot" ] && scp -q "${SSH_OPTS[@]}" \
      "${USER_AT}:$(printf '%s' "$REMOTE_PNG" | tr '\\' '/')" "${ARK_SHOT:-shot.png}" \
      && printf '%s  %s 字节\n' "${ARK_SHOT:-shot.png}" \
         "$(wc -c < "${ARK_SHOT:-shot.png}" | tr -d ' ')"
    ;;
  *)
    sed -n '/^# 用法：/,/^set -euo/p' "$0" | sed '$d'
    exit 2 ;;
esac
