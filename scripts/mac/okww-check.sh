#!/usr/bin/env bash
# 核实鸣潮那套配置**真的落地了**，不是「我以为设了」。
#
# 为什么要有它：2026-08-30 剿灭就是「设置看着好好的、实际没生效」——
# 写进文件的值被 AUTO-MAS 用内存里那份覆盖回去了，没人发现，白丢一周剿灭。
# 2026-09-01 周本同样栽过：母本写了 Boss Level=90，OK-WW 自己那份还是 80，
# 跑起来点的是「推荐等级80」。
#
# 查四件事：
#   1. 周本配置在**母本和 OK-WW 自己那份**里是否一致（只写母本不生效）
#   2. 本地补丁是否都在位（拿 repo/ 原始文件做 difflib 比对，数改动处数）
#   3. 周本门状态 + 游戏页面自己报的「本周剩余可收取次数」
#   4. 刷体力有没有被测试用的标记文件停着
#
#   scripts/mac/okww-check.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/winrun.sh" --timeout 250 --py "$HERE/../win/okww-landed.py"
