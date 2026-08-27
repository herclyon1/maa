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

# 拦住「又在手拼引号」这件事本身：脚本里如果自己带 ssh/wmic，说明还在走老路。
if grep -qE '\bssh\b|\bwmic\b' <<<"$SCRIPT"; then
  echo "winps: 脚本里出现了 ssh 或 wmic——这说明还在手拼远程调用。" >&2
  echo "       PowerShell 侧请用 Get-CimInstance 取代 wmic；" >&2
  echo "       要跑别的机器的命令，也走这个脚本，不要嵌套。" >&2
  exit 3
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
\$__out -join \"\`n\" | Set-Content -Path '${OUT}' -Encoding utf8"

B64=$(printf '%s' "$FULL" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')

if ! ssh -o ConnectTimeout=20 -o ServerAliveInterval=15 \
     -o ServerAliveCountMax=$(( TIMEOUT / 15 + 3 )) "$USER_AT" \
     "\"${PWSH}\" -NoProfile -EncodedCommand ${B64}" >/dev/null 2>&1; then
  echo "winps: 远端 pwsh 以非零退出结束（下面是它写下的输出，可能不完整）" >&2
fi

if ! scp -q -o ConnectTimeout=20 "${USER_AT}:${OUT}" "$TMP" 2>/dev/null; then
  echo "winps: 远端没有产生输出文件——脚本可能根本没跑起来，或机器不可达。" >&2
  exit 4
fi
ssh -o ConnectTimeout=15 "$USER_AT" "del /Q ${OUT//\//\\}" >/dev/null 2>&1 || true

# 去 BOM、统一换行；空输出如实说明，不当成成功。
python3 - "$TMP" <<'PY'
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
