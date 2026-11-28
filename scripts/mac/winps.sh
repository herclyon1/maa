#!/usr/bin/env bash
# 在游戏机上跑一段 PowerShell。**唯一正门**——任何时候都别再手拼 ssh + 引号。
#
# 为什么必须有这个：一条内联的 PowerShell 要穿过 bash → ssh → cmd → PowerShell
# 四层，每层都会啃一遍引号。2026-08-26 一晚上我在这上面栽了四次：
#
#   · `-like "*x*"` 被啃成 `-like` 后面没参数 → "You must provide a value expression"
#   · `Name=''python.exe''` 在单引号 bash 串里退化成 `Name=python.exe` → "无效查询"
#   · `wmic ... where "name='python.exe'"` 整条语法崩掉
#   · schtasks /tr 里的 `^&^&` 没过转义 → 计划任务「上次结果: 1」
#
# 每一次都写进了文档，每一次又照犯——用户原话：「写进文档里跟放屁一样」。
# 所以规矩换成工具：**要在那台机器上跑 PowerShell，只能走这里**。
# 这里把脚本整段 base64（UTF-16LE）之后用 -EncodedCommand 送过去，
# 中间没有任何一层需要解析引号，也就没有任何一层能啃坏它。
#
#   scripts/mac/winps.sh 'Get-Process | Select-Object -First 3'
#   scripts/mac/winps.sh --file some.ps1
#   echo 'Get-Date' | scripts/mac/winps.sh --stdin
#
# 输出按 UTF-8 取回，中文不经过 936 的控制台。
set -euo pipefail
export PATH="${PATH}:/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin"
MAC_PY="${MAC_PY:-/opt/homebrew/bin/python3}"
if [ ! -x "$MAC_PY" ]; then
  echo "winps: 找不到最新版 Homebrew Python（${MAC_PY}），拒绝回退系统旧版" >&2
  exit 1
fi
# Every call leaves one line in ~/.cache/ark-relay/mac_actions.log (lib/mac-action-log.sh).
# (`.` of a missing file ends a bash script, so it is looked for first: a copy of this script
# alone, as the tests make, still runs.)
ARK_ACTION_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/mac-action-log.sh"
if [ -f "$ARK_ACTION_LIB" ]; then
  # shellcheck source=lib/mac-action-log.sh
  . "$ARK_ACTION_LIB"; ark_action_log ${1+"$@"}
fi

HOST="${ARK_HOST:-100.65.39.119}"
USER_AT="Administrator@${HOST}"
PWSH='C:\Program Files\PowerShell\7\pwsh.exe'
TIMEOUT="${WINPS_TIMEOUT:-60}"

case "${1:-}" in
  --file)   SCRIPT="$(cat "${2:?用法: winps.sh --file <本地.ps1>}")" ;;
  --stdin)  SCRIPT="$(cat)" ;;
  "")       echo "用法: $0 '<PowerShell 脚本>' | $0 --file x.ps1 | $0 --stdin" >&2; exit 2 ;;
  *)        SCRIPT="$1" ;;
esac

# 第 1 层断电硬锁（08:40:00–08:45:59 CST 禁止向游戏机发远程命令，返回 RC=78；不误伤 08:25 探活）
ARK_PC_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/powercut-guard.sh"
if [ -f "$ARK_PC_LIB" ]; then
  # shellcheck source=lib/powercut-guard.sh
  . "$ARK_PC_LIB"
  ark_powercut_guard 1 "winps.sh" || exit $?
fi

# 拦住「又在手拼引号」这件事本身：脚本里如果自己带 ssh/wmic，说明还在走老路。
if grep -qE '\bssh\b|\bwmic\b' <<<"$SCRIPT"; then
  echo "winps: 脚本里出现了 ssh 或 wmic——这说明还在手拼远程调用。" >&2
  echo "       PowerShell 侧请用 Get-CimInstance 取代 wmic；" >&2
  echo "       要跑别的机器的命令，也走这个脚本，不要嵌套。" >&2
  exit 3
fi

# Shutdown guard (11-16, Gemini's fix after I nearly shut the machine down while the morning shift was still running
# OK-WW / MaaEnd): a script that powers the machine off or restarts it first checks, on the machine, whether
# any game or automation process is up; if one is, it refuses before anything runs and winps exits 5.
# The relay shuts the machine down itself once the shift is done (debug mode only skips that one shutdown).
# shutdown /a (abort) is never stopped. ARK_SHUTDOWN_OVERRIDE='<his own words>' lets a shutdown through anyway.
BUSY_NAMES='MAA,MaaEnd,Endfield,ok-ww,Client-Win64-Shipping,dnplayer'
ARK_SG_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/shutdown-guard.sh"
if [ -f "$ARK_SG_LIB" ]; then
  # shellcheck source=lib/shutdown-guard.sh
  . "$ARK_SG_LIB"
  _sg_rc=0
  ark_sg_preflight ps "winps" "$USER_AT" "$BUSY_NAMES" "" "$SCRIPT" || _sg_rc=$?
  if [ "$_sg_rc" = 5 ]; then
    exit 5
  elif [ "$_sg_rc" = 10 ]; then
    SCRIPT="${ARK_SG_SNIPPET}
${SCRIPT}"
  fi
elif grep -qiE '(^|[^a-z])shutdown(\.exe)?[^;|]*[/-][sr]([^a-z]|$)|Stop-Computer|Restart-Computer' <<<"$SCRIPT"; then
  if [ -n "${ARK_SHUTDOWN_OVERRIDE:-}" ]; then
    echo "winps: shutdown guard overridden: ${ARK_SHUTDOWN_OVERRIDE}" >&2
  else
    SCRIPT="\$__busy = @(Get-Process -Name ${BUSY_NAMES} -ErrorAction SilentlyContinue | ForEach-Object { \$_.ProcessName } | Sort-Object -Unique)
if (\$__busy.Count) { 'WINPS_REFUSED: ' + (\$__busy -join ', '); return }
${SCRIPT}"
  fi
fi

# 输出落 UTF-8 文件再整体取回。直接读 stdout 会经过 936 的控制台，中文必碎。
RUN_ID="$$-$(date +%s)"
OUT="C:/ProgramData/winps-${RUN_ID}.out"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

# 把「结果写文件」这段和用户脚本拼在一起——拼的是 PowerShell 源码，不是命令行，
# 所以不涉及任何 shell 层的转义。
FULL="\$ErrorActionPreference='Continue'
\$__out = @()
try { \$__out = @(& { ${SCRIPT} } 2>&1 | Out-String -Stream) }
catch { \$__out = @('winps: 脚本抛异常: ' + \$_.Exception.Message) }
\$__out -join \"\`n\" | Set-Content -Path '${OUT}' -Encoding utf8
# 结果在**同一次连接里**用 base64 带回来，顺手删掉临时文件。
# 原来是写文件 → scp 取回 → 再 ssh 删，三次跨境往返；scp 还要单独谈一条 SFTP 通道。
# 2026-09-08 实测那两步占 winps 的一大半。base64 是纯 ASCII，照样绕开 936 控制台。
Write-Output ('WINPS_B64=' + [Convert]::ToBase64String([IO.File]::ReadAllBytes('${OUT}')))
Remove-Item '${OUT}' -Force -ErrorAction SilentlyContinue"

B64=$(printf '%s' "$FULL" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')

RAW=$(ssh -o ConnectTimeout=20 -o ServerAliveInterval=15 \
      -o ServerAliveCountMax=$(( TIMEOUT / 15 + 3 )) "$USER_AT" \
      "\"${PWSH}\" -NoProfile -EncodedCommand ${B64}" 2>/dev/null | tr -d '\r') || \
  echo "winps: 远端 pwsh 以非零退出结束（下面是它写下的输出，可能不完整）" >&2

OUTB64=$(sed -n 's/^WINPS_B64=//p' <<<"$RAW")
if [ -z "$OUTB64" ]; then
  echo "winps: 远端没有产生输出——脚本可能根本没跑起来，或机器不可达。" >&2
  exit 4
fi
printf '%s' "$OUTB64" | base64 -d > "$TMP" 2>/dev/null || {
  echo "winps: 输出解码失败，远端可能中途被打断" >&2; exit 4; }

if grep -q 'WINPS_REFUSED: ' "$TMP"; then
  busy=$(sed -n 's/.*WINPS_REFUSED: //p' "$TMP" | tr -d '\r' | head -1)
  echo "winps: 拒绝关机——${busy}。请先处理完当前任务或故障，或等中继收工后自动关机。" >&2
  exit 5
fi

# 去 BOM、统一换行；空输出如实说明，不当成成功。
"$MAC_PY" - "$TMP" <<'PY'
import sys, pathlib
d = pathlib.Path(sys.argv[1]).read_bytes()
if d.startswith(b"\xef\xbb\xbf"):
    d = d[3:]
s = d.decode("utf-8", "replace").replace("\r\n", "\n")
if not s.strip():
    print("winps: 脚本没有任何输出（这不一定是成功，请自己判断）", file=sys.stderr)
else:
    sys.stdout.write(s if s.endswith("\n") else s + "\n")
PY
