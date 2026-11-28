# shellcheck shell=bash
# Mac 侧直连游戏机脚本的分层北京时间断电硬锁公共库（对齐 F-POWER-SCHEDULE）。
#
# 用法（在任何 SSH/SCP/HTTP/串流直连游戏机之前调用）：
#   ARK_PC_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/powercut-guard.sh"
#   if [ -f "$ARK_PC_LIB" ]; then
#     . "$ARK_PC_LIB"
#     ark_powercut_guard 1 "winps.sh" || exit $?
#   fi
#
# 两层硬拦截策略（统一返回码 78）：
#   - tier 1（全量 16 入口）：北京时间 08:40:00–08:45:59 严禁向游戏机发远程命令（不误伤 08:25 探活）；
#   - tier 2（长耗时写盘/部署/演练入口）：北京时间 08:22:00–08:46:59 严禁启动（防写盘拖跨 08:40 硬断电）。
#   - 环境变量 ARK_CLOCK_OVERRIDE 供单测与验收注入模拟时刻（自动委托 powercut_guard.py 精确解析时区与边界）。

ARK_PC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARK_PC_PY="$ARK_PC_DIR/powercut_guard.py"

ark_powercut_guard() {
  local tier="${1:-1}"
  local caller="${2:-$(basename -- "$0")}"
  # 注入了模拟时钟时走 Python 解析器，支持 HH:MM / HH:MM:SS / 任意时区 ISO-8601
  if [ -n "${ARK_CLOCK_OVERRIDE:-}" ]; then
    local py_bin="${MAC_PY:-/opt/homebrew/bin/python3}"
    if [ ! -x "$py_bin" ]; then
      echo "${caller}: 断电锁找不到最新版 Python（${py_bin}），拒绝放行（RC=78）" >&2
      return 78
    fi
    "$py_bin" -B "$ARK_PC_PY" check --tier "$tier" --caller "$caller"
    return $?
  fi
  # 常规运行走纯 bash + date 快路径（<2ms，不额外启动 Python 进程）
  local hms cur_n hh mm ss
  hms="$(TZ=Asia/Shanghai date +%H%M%S)"
  hh="${hms:0:2}"
  mm="${hms:2:2}"
  ss="${hms:4:2}"
  cur_n=$((10#$hms))
  if [ "$tier" = "2" ]; then
    if [ "$cur_n" -ge 82200 ] && [ "$cur_n" -le 84659 ]; then
      echo "${caller}: 拒绝操作——当前北京时间 ${hh}:${mm}:${ss} 处于第 2 层 08:22:00–08:46:59 长耗时写盘/部署/演练断电保护窗口（RC=78）" >&2
      return 78
    fi
  else
    if [ "$cur_n" -ge 84000 ] && [ "$cur_n" -le 84559 ]; then
      echo "${caller}: 拒绝操作——当前北京时间 ${hh}:${mm}:${ss} 处于第 1 层 08:40:00–08:45:59 智能插座硬断电窗口（RC=78）" >&2
      return 78
    fi
  fi
  return 0
}
