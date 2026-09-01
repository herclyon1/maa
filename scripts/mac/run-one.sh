#!/usr/bin/env bash
# 手动跑任务的唯一入口。内含派发闸门 + 派发后 75 秒自动首查。
#
#   run-one.sh status            # 现在在跑什么
#   run-one.sh stop              # 按正确顺序停干净（API→等→残留才杀→复查拉起）
#   run-one.sh MAA|MaaEnd|OK-WW  # 单派一个脚本；忙时拒绝
#
# 为什么必须走这里：2026-09-01 上午,「派整条队列 + taskkill 队列成员」
# 让 AUTO-MAS 的整队重试和手动派发打架——MAA 重复吃药、三个游戏同时在线。
# 详见 scripts/win/dispatch_guard.py 顶部注释。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
G="$HERE/../win/dispatch_guard.py"
case "${1:-status}" in
  status|stop) exec "$HERE/winrun.sh" --timeout 220 --py "$G" "${1}" ;;
  *)
    "$HERE/winrun.sh" --timeout 220 --py "$G" start "$1"
    echo "…75 秒后首查（先看报错）…"
    sleep 75
    "$HERE/winrun.sh" --timeout 220 --py "$G" status
    ;;
esac
