#!/usr/bin/env bash
# 在游戏机上单独跑 OK-WW 的某一个任务，绕开 AUTO-MAS 的每日任务流程。
#
# 为什么需要它：AUTO-MAS 永远用 `-t 1`（每日任务）拉 OK-WW，而每日任务里
# 有一堆闸门——活跃度满了就跳过刷取、体力不够就跳过副本。想单独验证
# 「合并声骸」「巢穴刷取」这类任务时，走每日任务根本进不去那段代码。
# AUTO-MAS 的 `Task.TaskIndex` 改不动（写 API 报 success、回读还是 1，
# 2026-08-26 实测），所以直接调 OK-WW 自己。
#
# `-t N` 的含义在 `ok/__init__.py` 里写死了：`onetime_tasks[N-1]`，1 起算。
# 顺序取自 OK-WW 的 config.py，2026-08-26 核对：
#
#   1 每日任务          2 副本/大世界刷4C声骸   3 梦魇巢穴/残象聚落
#   4 无音区            5 凝素领域              6 模拟领域
#   7 多账号每日        8 合并已弃置声骸        9 批量强化声骸
#   10 批量改主属性     11 周常乐园
#
# **顺序会随上游版本变**。跑之前用 --list 核对一次，别凭这段注释下手。
#
#   scripts/mac/okww-task.sh --list      # 打印当前真实的任务顺序
#   scripts/mac/okww-task.sh 8           # 跑第 8 个（合并已弃置声骸）
#
# 图形程序必须从 session 1 起（ssh 那个会话没有桌面），所以照例走 /it 计划任务。
set -euo pipefail

HOST="${ARK_HOST:?请先 export ARK_HOST=<游戏机 Tailscale IP>}"
USER_AT="Administrator@${HOST}"
PY='D:\ark\okww\data\apps\ok-ww\python\python.exe'
MAIN='D:\ark\okww\data\apps\ok-ww\working\main.py'
# 必须设工作目录：OK-WW 的日志路径是相对的，不设就写进 C:\Windows\System32\logs。
# 2026-08-26 我因此盯着 working\logs 那个不动的文件，把跑成功的任务误判成「没起来」。
CWD='D:\ark\okww\data\apps\ok-ww\working'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ "${1:-}" = "--list" ]; then
  cat > "$TMP/list.py" <<'PY'
import re
from pathlib import Path
cfg = Path(r"D:\ark\okww\data\apps\ok-ww\working\config.py").read_text(
    encoding="utf-8", errors="replace")
m = re.search(r"'onetime_tasks':\s*\[(.*?)\],\s*'trigger_tasks'", cfg, re.S)
if not m:
    print("认不出 onetime_tasks，别按下标跑")
    raise SystemExit(1)
rows = [l for l in m.group(1).splitlines()
        if '["' in l and not l.strip().startswith('#')]
print(f"当前 onetime_tasks（-t 的下标，1 起算）共 {len(rows)} 个：")
for i, line in enumerate(rows, 1):
    name = re.search(r'"(\w+)"\s*\]', line)
    print(f"  {i:>2}  {name.group(1) if name else line.strip()[:60]}")
PY
  exec "$SCRIPT_DIR/winrun.sh" --py "$TMP/list.py"
fi

N="${1:?用法: $0 <任务下标>   （先跑 $0 --list 核对下标）}"
case "$N" in
  ''|*[!0-9]*) echo "任务下标必须是数字，收到: $N" >&2; exit 2 ;;
esac

log_stamp() {
  ssh -o ConnectTimeout=15 "$USER_AT" \
    "for %I in (\"${CWD}\\logs\\ok-script.log\") do @echo %~tI" 2>/dev/null | tr -d '\r'
}
BEFORE="$(log_stamp)"

echo "▶ 在 session 1 里跑 OK-WW -t $N"
# 不在 schtasks /tr 里拼命令。`&&`、引号、`^` 要穿过 bash → ssh → cmd → 计划任务
# 四层，每层啃一遍；2026-08-26 就是这么拿到 `上次结果: 1` 的。
# 落一个 .bat，schtasks 只负责跑这个文件——没有任何需要转义的东西。
cat > "$TMP/okww-run.bat" <<BAT
@echo off
cd /d "${CWD}"
"${PY}" "${MAIN}" -t ${N} -e
BAT
scp -q -o ConnectTimeout=20 "$TMP/okww-run.bat" "${USER_AT}:C:/ProgramData/okww-run.bat" \
  || { echo "okww-task: .bat 送不上去" >&2; exit 4; }
ssh -o ConnectTimeout=20 "$USER_AT" \
  "schtasks /delete /tn ark-okww /f >nul 2>&1 & \
   schtasks /create /tn ark-okww /tr C:\\ProgramData\\okww-run.bat \
     /sc once /st 00:00 /ru Administrator /it /f >nul 2>&1 & \
   schtasks /run /tn ark-okww >nul 2>&1 & echo STARTED" >/dev/null 2>&1

# schtasks /run 立刻返回，进程是异步起的。等它真的出现，别一返回就说成功。
for _ in $(seq 1 15); do
  # 判据：日志的**时间戳变了**才算起来了。
  #   · grep 一个 python.exe 必然误报（AUTO-MAS 和 winrun 常年都是 python.exe）；
  #   · `forfiles /D +0` 只判「今天改过」，今天的旧日志一直满足，同样是弱判据。
  # 两样 2026-08-26 都栽过，所以这里比的是启动前后的具体时间戳。
  NOW_STAMP="$(log_stamp)"
  if [ -n "$NOW_STAMP" ] && [ "$NOW_STAMP" != "$BEFORE" ]; then
    echo "  已启动（OK-WW 日志时间戳 $BEFORE → $NOW_STAMP）"
    exit 0
  fi
  sleep 2
done
echo "✋ 30 秒内没看到 OK-WW 的进程起来。" >&2
echo "   /it 的计划任务要求 console 会话有人登录：ssh $USER_AT qwinsta" >&2
exit 3
