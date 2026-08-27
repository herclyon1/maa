#!/usr/bin/env bash
# Run a command on the game machine, or fetch a file, without corrupting Chinese.
#
# The Windows console is codepage 936 (GBK) and Windows PowerShell 5.1 reads
# files as ANSI unless told otherwise. So a UTF-8 file printed by a remote
# command is already destroyed before it reaches the wire, and "pipe it through
# iconv" is worse than useless because some output is already UTF-8 - decoding
# that twice shreds it silently. On 2026-08-23 that produced two drop names
# invented out of broken bytes and reported as fact.
#
# Rules this enforces:
#   * a file's contents are fetched as bytes, never printed by a remote command
#   * a command's output is written to a UTF-8 file on the machine, then copied
#   * no Chinese ever appears on a command line
#
#   scripts/mac/winrun.sh 'dir C:\ProgramData'          # cmd
#   scripts/mac/winrun.sh --ps 'Get-Process MAA'        # PowerShell
#   scripts/mac/winrun.sh --put <本地文件> 'D:\path\file'  # 放一个文件上去
#   scripts/mac/winrun.sh --get 'D:\path\file.json'      # a file, verbatim
#   scripts/mac/winrun.sh --get-safe 'D:\path\file.json' # 同上但遮蔽密钥，
#       只在内容要贴进 issue 或公开仓库时才需要
#   scripts/mac/winrun.sh --py  local.py [args...]      # 在 session 0 跑（够用就用它）
#   scripts/mac/winrun.sh --py1 local.py [args...]      # 在**交互桌面会话**里跑
#       —— 要看屏幕、要枚举窗口、要启动图形程序，必须用 --py1
#
# Use --py for anything longer than one line. A command typed inline crosses
# bash quoting, ssh, PowerShell and sometimes cmd, and each layer gets its own
# turn at the quotes; a PowerShell string containing '' ends the surrounding
# bash string instead. That has cost this project several wasted round trips.
# Shipping the script as a file means no layer has to parse it at all.
set -euo pipefail

# 远端脚本的**硬墙钟上限**（秒）。ConnectTimeout 只管建连接，管不了脚本跑多久，
# 所以 2026-08-26 一个全盘 rglob 在远端跑了十分钟，期间用户完全插不上手。
# 用户当场的要求：「你这超时10分钟，我在中间根本都没办法阻止你」。
# 默认压到 120 秒；真需要更久的活儿必须显式 --timeout N 说出来。
WINRUN_TIMEOUT="${WINRUN_TIMEOUT:-120}"
if [ "${1:-}" = "--timeout" ]; then
  WINRUN_TIMEOUT="${2:?--timeout 后面要跟秒数}"
  case "$WINRUN_TIMEOUT" in ''|*[!0-9]*) echo "--timeout 必须是数字" >&2; exit 2 ;; esac
  shift 2
fi

HOST="${ARK_HOST:-100.65.39.119}"
USER_AT="Administrator@${HOST}"
STRIP='import sys;d=open(sys.argv[1],"rb").read();d=d[3:] if d.startswith(b"\xef\xbb\xbf") else d;sys.stdout.write(d.decode("utf-8","replace").replace("\r\n","\n"))'

# 在游戏机上跑一段 PowerShell，不经过任何一层引号解析。
#
# 为什么必须这样：一条内联命令要穿过 bash → ssh → cmd → PowerShell 四层，
# 每层都要啃一遍引号。2026-08-26 光这一个原因就炸了五次，
# 包括 `'Wuthering' 不是内部或外部命令`，以及本文件里清理残留那一行。
# base64 之后管道里只有 A-Za-z0-9+/=，没有任何一层需要解析它。
#
# 一律用 pwsh 7：5.1 默认不是 UTF-8，读中文 JSON 必乱码。7 没装才退回 5.1。
# 送出去之前先看一眼脚本本身。全盘扫描是**在远端**烧时间，本地看不见进度，
# 而且十有八九一无所获——CLAUDE.md 里「不许全盘 rglob」这条已经被违反两次。
# 真要扫，在文件里写一行 `# winrun: allow-scan` 明示，别让它默默发生。
preflight_scan_check() {
  local f="$1"
  grep -q '# winrun: allow-scan' "$f" && return 0
  local hits
  # 盘符根目录：反斜杠、正斜杠、没斜杠、单双引号、带不带 r 前缀，全都算。
  # 2026-08-27 闸门自检发现：原来的规则只认 Path("C:\\")，
  # 一个 Path("C:/") 就能大摇大摆穿过去——闸门看着在，其实拦不住。
  local root_pat='(Path|os\.walk)\(\s*r?["'"'"']([A-Za-z]:[\\/]{0,2}|/|~)["'"'"']'
  local sys_pat='["'"'"'][A-Za-z]:[\\/](Windows|Users|Program Files|ProgramData)'
  hits=$(grep -nE 'rglob|os\.walk|glob\.glob' "$f" \
         | grep -viE 'logs|configs|history|screenshots|state|\bsrc\b|working' \
         | grep -iE "$root_pat|$sys_pat|Path\.home\(\)" \
         || true)
  [ -z "$hits" ] && return 0
  echo "winrun: 拒绝发送——这个脚本像是要在远端做全盘/系统目录扫描：" >&2
  sed 's/^/        /' <<<"$hits" >&2
  echo "        改成从配置或代码里读确切路径；确实要扫就在脚本里加一行" >&2
  echo "        # winrun: allow-scan   并配 --timeout <秒数>" >&2
  return 1
}

# 自己拼时间戳过滤是今晚重复最多的错（3 次）：拿本机（东京）的日期去比
# 机器（北京）的日志，跨零点还会差一整天；而且字典序比较会让没有时间戳的
# traceback 续行全部漏出来。arklog.since() 两个坑都堵了，所以别再手写。
preflight_timefilter_check() {
  local f="$1"
  grep -q '# winrun: allow-raw-timefilter' "$f" && return 0
  local hits
  hits=$(grep -nE '\[:1[0-9]\][[:space:]]*[<>]|\[:19\]|datetime\.now\(\)|date\.today\(\)' "$f" \
         | grep -vE 'arklog' || true)
  [ -z "$hits" ] && return 0
  echo "winrun: 拒绝发送——这个脚本在自己拼时间过滤／取本机时间：" >&2
  sed 's/^/        /' <<<"$hits" >&2
  echo "        改用已经送到机器上的 arklog：" >&2
  echo "          from arklog import since, summarise, mtime, OKWW_LOG" >&2
  echo "          lines = since(OKWW_LOG, \"21:06\")" >&2
  echo "        真有理由自己写就在脚本里加一行 # winrun: allow-raw-timefilter" >&2
  return 1
}

run_remote_ps() {
  local b64
  b64=$(printf '%s' "$1" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')
  ssh -o ConnectTimeout="${2:-30}" "$USER_AT" \
    "if exist \"C:\\Program Files\\PowerShell\\7\\pwsh.exe\" (\"C:\\Program Files\\PowerShell\\7\\pwsh.exe\" -NoProfile -EncodedCommand $b64) else (powershell -NoProfile -EncodedCommand $b64)" \
    2>/dev/null
}

if [ "${1:-}" = "--put" ]; then
  # 往机器上放一个文件。**存在的唯一理由是不让我再手拼 scp**：
  # 2026-08-27 我手写 `scp ... herclyon@<ip>:...`，远端用户其实是
  # Administrator，于是连着两次 `scp: Connection closed`，
  # 而我把「没传上去」当成了「传上去了」，测的是旧代码还以为修复没生效。
  # 用户名、超时、反斜杠转正斜杠，这里一次性管掉。
  LOCAL="${2:?用法: winrun.sh --put <本地文件> '<远端路径>'}"
  REMOTE="${3:?用法: winrun.sh --put <本地文件> '<远端路径>'}"
  [ -f "$LOCAL" ] || { echo "找不到 $LOCAL" >&2; exit 1; }
  DEST="$(printf '%s' "$REMOTE" | tr '\\' '/')"
  # 父目录不存在时 scp 只会失败，不会替你建。deploy-relay.sh 早就单独处理过
  # 这件事，`--put` 却没有——同一个坑不该在两个地方各修一次。
  PARENT="${DEST%/*}"
  if [ "$PARENT" != "$DEST" ]; then
    MK_B64=$(printf '%s' "New-Item -ItemType Directory -Force -Path '${PARENT}' | Out-Null" \
             | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')
    ssh -o ConnectTimeout=30 "$USER_AT" \
      "pwsh -NoProfile -EncodedCommand ${MK_B64}" >/dev/null 2>&1 || true
  fi
  scp -q -o ConnectTimeout=30 "$LOCAL" "${USER_AT}:${DEST}" || {
    echo "winrun --put: 传输失败（上面是 scp 的报错）" >&2; exit 1; }
  # 传完必须核对大小，不然「静默没传上去」这个坑还在。
  WANT=$(wc -c < "$LOCAL" | tr -d ' ')
  # 用 pwsh 7，不是 powershell 5.1；而且不内联拼 PowerShell——照规矩走 base64。
  SZ_PS="(Get-Item -LiteralPath '${DEST}').Length"
  SZ_B64=$(printf '%s' "$SZ_PS" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')
  GOT=$(ssh -o ConnectTimeout=30 "$USER_AT" \
        "pwsh -NoProfile -EncodedCommand ${SZ_B64}" 2>/dev/null | tr -d '\r ')
  if [ "$WANT" != "$GOT" ]; then
    echo "winrun --put: 大小对不上（本地 ${WANT}，远端 ${GOT:-读不到}）" >&2
    exit 1
  fi
  echo "已上传 ${DEST}（${WANT} 字节，已核对）"
  exit 0
fi

if [ "${1:-}" = "--get" ] || [ "${1:-}" = "--get-safe" ]; then
  # --get 默认脱敏。泄漏过两次（WECOM_SECRET、cdkEncrypted），而转录一旦写下
  # 就收不回来，所以安全的那个必须是默认值。真要原始字节用 --get-raw，并且
  # 只在结果不会被打印出来的时候用。
  # 默认原样取回。脱敏只在内容要贴出去（issue、公开仓库）时才有意义，
  # 平时挡在中间只会碍事：配置里正常字段也可能被误伤，而且多一层要排查。
  # 要脱敏就显式用 --get-safe，或者自己管道接 scripts/mac/redact.py。
  RAW=1; [ "${1}" = "--get-safe" ] && RAW=0
  REMOTE="${2:?用法: winrun.sh --get|--get-safe '<远端文件路径>'}"
  TMP="$(mktemp)"
  scp -q -o ConnectTimeout=30 "${USER_AT}:$(printf '%s' "$REMOTE" | tr '\\' '/')" "$TMP"
  if [ "$RAW" = 1 ]; then
    python3 -c "$STRIP" "$TMP"
  else
    python3 -c "$STRIP" "$TMP" | python3 "$(dirname "$0")/redact.py"
  fi
  rm -f "$TMP"
  exit 0
fi

if [ "${1:-}" = "--py1" ]; then
  # 和 --py 的唯一区别：脚本跑在**交互桌面会话**里，而不是 SSH 落地的 session 0。
  # 为什么需要：SSH 会话没有桌面，EnumWindows 枚举不到任何窗口、截图拿不到画面、
  # 图形程序拉起来就死。2026-08-24 为此浪费了好几个来回，一次是 MaaEnd 起不来，
  # 一次是明明满屏窗口却枚举出零个。判断依据很简单：脚本要不要"看见"或"碰到"
  # 屏幕上的东西 —— 要，就用 --py1。
  LOCAL_PY="${2:?用法: winrun.sh --py1 <本地 .py 文件> [参数...]}"
  [ -f "$LOCAL_PY" ] || { echo "找不到 $LOCAL_PY" >&2; exit 1; }
  shift 2
  scp -q -o ConnectTimeout=30 "$LOCAL_PY" "${USER_AT}:C:/ProgramData/winrun-run.py"
  ARGS="$*"
  TMP="$(mktemp)"
  LOCAL_PS1="$(mktemp)"
  {
    printf '\xef\xbb\xbf'
    cat <<PS1EOF
\$ErrorActionPreference = "SilentlyContinue"
Remove-Item C:\\ProgramData\\winrun.out -Force -ErrorAction SilentlyContinue
# 先清上一轮残留：脚本超时（比如误遍历整个 APPDATA）时任务会被注销，但 python
# 进程还在，占着 winrun.out，下一次调用只能拿到 0 字节空文件。2026-08-24 连着
# 两次静默失败就是这么来的，表面看像断网。
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { \$_.CommandLine -like "*winrun-run.py*" } |
  ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }
Unregister-ScheduledTask -TaskName "winrun-py1" -Confirm:\$false -ErrorAction SilentlyContinue
\$py  = "C:\\Program Files\\Python314\\python.exe"
# 用 powershell -WindowStyle Hidden 取代 cmd.exe：cmd 会在交互桌面上弹一个黑框，
# 盖住正在操作的窗口。2026-08-24 装鸣潮时它就挡住了登录区域，用户直接看见了。
# 输出必须显式 -Encoding utf8：任务跑的是 powershell.exe（5.1），它的 *> 写的是
# UTF-16，取回来就是一片乱码。
\$inner = '[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$env:PYTHONUTF8=1; \$env:PYTHONIOENCODING="utf-8"; & "' + \$py + '" C:\\ProgramData\\winrun-run.py $ARGS *>&1 | Out-File -FilePath C:\\ProgramData\\winrun.out -Encoding utf8'  
\$b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(\$inner))
\$act = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ("-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -EncodedCommand " + \$b64)
\$pri = New-ScheduledTaskPrincipal -UserId "administrator" -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "winrun-py1" -Action \$act -Principal \$pri -Force | Out-Null
Start-ScheduledTask -TaskName "winrun-py1"
# 等它跑完：任务状态回到 Ready 就算结束，最多等 5 分钟。
for (\$i = 0; \$i -lt 150; \$i++) {
  Start-Sleep -Milliseconds 2000
  if ((Get-ScheduledTask -TaskName "winrun-py1").State -ne "Running") { break }
}
Unregister-ScheduledTask -TaskName "winrun-py1" -Confirm:\$false -ErrorAction SilentlyContinue
PS1EOF
  } > "$LOCAL_PS1"
  scp -q -o ConnectTimeout=30 "$LOCAL_PS1" "${USER_AT}:C:/ProgramData/winrun1.ps1" \
    || { echo "winrun1: 送不上去 ps1（scp 失败）" >&2; rm -f "$TMP" "$LOCAL_PS1"; exit 3; }
  # 计划任务本身失败与否 ssh 不一定反映得出来，所以判据放在「有没有产出」上。
  ssh -o ConnectTimeout=330 "$USER_AT" \
    'if exist "C:\Program Files\PowerShell\7\pwsh.exe" ("C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\winrun1.ps1) else (powershell -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\winrun1.ps1)' \
    >/dev/null 2>&1 || true
  if ! scp -q -o ConnectTimeout=30 "${USER_AT}:C:/ProgramData/winrun.out" "$TMP" 2>/dev/null; then
    echo "winrun1: 远端没有产生 winrun.out（计划任务可能没跑起来）" >&2
    rm -f "$TMP" "$LOCAL_PS1"; exit 4
  fi
  if [ ! -s "$TMP" ]; then
    # 和 --py 同样的道理：空输出不是成功。--py1 走计划任务，最常见的原因是
    # 交互会话不存在（没登录）或任务被策略拦下。
    echo "winrun1: 脚本没有任何输出（0 字节）。检查是否有交互桌面会话在。" >&2
    rm -f "$TMP" "$LOCAL_PS1"; exit 5
  fi
  python3 -c "$STRIP" "$TMP"
  rm -f "$TMP" "$LOCAL_PS1"
  exit 0
fi

if [ "${1:-}" = "--py" ]; then
  # 2026-08-26：这个分支曾经能**静默失败**——三处叠加：
  #   ssh ... >/dev/null 2>&1 || true   ssh 挂了不说
  #   scp ... 2>/dev/null   || true     取不到文件不说
  #   [ -s "$TMP" ] && ...              文件是空的就什么都不打印，然后退出码 0
  # 于是「命令成功但没有输出」，我当天撞了三次，以为工具坏了就改用裸 ssh 绕过去。
  #
  # 而卡住的根因 --py1 早就写在上面了（见那段注释）：脚本被超时杀掉后，
  # **远端 python 进程还活着占着 winrun.out**，之后每次调用都只能拿到 0 字节。
  # 那套清理当时只加进了 --py1，没加进 --py。现在补齐，并且**失败一律出声**。
  LOCAL_PY="${2:?用法: winrun.sh --py <本地 .py 文件> [参数...]}"
  [ -f "$LOCAL_PY" ] || { echo "找不到 $LOCAL_PY" >&2; exit 1; }
  shift 2
  # 每次调用用**唯一的**文件名。共用 winrun.out 那版栽过：上一轮的僵尸
  # （cmd.exe 攥着重定向 + python 还在跑）会把文件锁住，之后每一次调用都
  # 拿到 0 字节，而真正的原因在几百行日志之外。名字唯一了就锁不到下一次。
  # 两道发送前闸门放在**碰网络之前**：它们判的是脚本内容，跟机器无关，
  # 排在清理残留后面等于要先连一次机器才轮到它们——慢，而且
  # guardcheck.sh 想离线验证「闸门还活着」时会被网络失败挡在前面。
  # 2026-08-27 闸门自检就是这么发现这个顺序问题的。
  preflight_scan_check "$LOCAL_PY" || exit 2
  preflight_timefilter_check "$LOCAL_PY" || exit 2

  RUN_ID="$$-$(date +%s)"
  REMOTE_PY="C:/ProgramData/winrun-run-${RUN_ID}.py"
  REMOTE_GUARD="C:/ProgramData/winrun-guard-${RUN_ID}.py"
  REMOTE_OUT="C:/ProgramData/winrun-${RUN_ID}.out"
  TMP="$(mktemp)"
  trap 'rm -f "$TMP" "$TMP.guard"' EXIT

  # ① 清上一轮残留：先杀掉还占着 winrun.out 的旧 python，再删旧输出。
  #    不做这一步，上一轮的僵尸进程会让这一轮拿到空文件或陈旧内容。
  #
  #    这段第一版是用 `powershell -Command "...嵌套引号..."` 拼的，每次都失败——
  #    在同一行里同时踩了当天刚立的两条规矩：用了 5.1 而不是 pwsh，
  #    以及硬拼引号而不是 base64。改成 run_remote_ps 之后一次通过。
  run_remote_ps '
    Get-CimInstance Win32_Process -Filter "Name=''python.exe''" -EA SilentlyContinue |
      Where-Object { $_.CommandLine -like "*winrun-run*" -or
                     $_.CommandLine -like "*winrun-guard*" } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
    # 顺手收掉历史残留：唯一文件名之后这些都没人用了，留着只会堆垃圾。
    Get-ChildItem C:\ProgramData\winrun-*.out, C:\ProgramData\winrun-run-*.py,
                  C:\ProgramData\winrun-guard-*.py -EA SilentlyContinue |
      Where-Object { $_.LastWriteTime -lt (Get-Date).AddMinutes(-10) } |
      Remove-Item -Force -EA SilentlyContinue
    Remove-Item C:\ProgramData\winrun.out -Force -EA SilentlyContinue
    "cleanup-ok"
  ' | grep -q "cleanup-ok" \
    || echo "winrun: 警告——清理上一轮残留失败，结果可能是陈旧的" >&2
  # 判据用**它自己打印的暗号**，不用退出码：这段全程 -EA SilentlyContinue，
  # pwsh 的退出码在这里根本不反映成败，一直误报「清理失败」，
  # 而虚假的警告会把真正的失败淹掉。

  scp -q -o ConnectTimeout=30 "$LOCAL_PY" "${USER_AT}:${REMOTE_PY}" \
    || { echo "winrun: 送不上去 $LOCAL_PY（scp 失败）" >&2; exit 3; }

  # 远端看门狗：脚本自己超时就把自己打死，不用等本地那层。
  # 只有本地 ssh 超时的话，远端进程会继续跑并占住 winrun.out——正是上面
  # 「清上一轮残留」要处理的那个僵尸。两头都设上限，才是真的有上限。
  cat > "$TMP.guard" <<GUARD
import os, runpy, sys, threading, time
sys.path.insert(0, r"C:\ProgramData")      # 让脚本能 import arklog
# 机器的钟打在第一行：我在东京、机器在北京，差一小时。
# 手打时刻窗口时若抄了手机（东京）上的时间，这行就在同屏打脸。
print("[机器时间] " + time.strftime("%m-%d %H:%M:%S"), flush=True)
LIMIT = ${WINRUN_TIMEOUT}
def _bail():
    print("\n[winrun] 远端脚本超过 %d 秒硬上限，已强制中止。" % LIMIT, flush=True)
    print("[winrun] 需要更久就加 --timeout <秒数>，但先想清楚为什么这么久。", flush=True)
    os._exit(124)
t = threading.Timer(LIMIT, _bail); t.daemon = True; t.start()
sys.argv = ["winrun-run.py"] + sys.argv[1:]
runpy.run_path(r"${REMOTE_PY//\//\\}", run_name="__main__")
GUARD
  # 顺手送上 arklog.py：读日志的三个坑（时钟、字典序、格式）都在里面堵掉了，
  # 临时脚本 `from arklog import since` 就能用，不用每次自己拼过滤。
  if [ -f "$(dirname "${BASH_SOURCE[0]}")/lib/arklog.py" ]; then
    scp -q -o ConnectTimeout=30 "$(dirname "${BASH_SOURCE[0]}")/lib/arklog.py" \
      "${USER_AT}:C:/ProgramData/arklog.py" || true
  fi

  scp -q -o ConnectTimeout=30 "$TMP.guard" "${USER_AT}:${REMOTE_GUARD}" \
    || { echo "winrun: 看门狗送不上去（scp 失败）" >&2; exit 3; }
  rm -f "$TMP.guard"

  # ② 跑。输出写到机器上的 UTF-8 文件再整体拷回，中文不经过 936 的控制台。
  #    本地这层也加上限：ssh 自己不会因为远端卡住而返回。
  if ! ssh -o ConnectTimeout=30 -o ServerAliveInterval=15 \
      -o ServerAliveCountMax=$(( WINRUN_TIMEOUT / 15 + 4 )) "$USER_AT" \
      "set PYTHONUTF8=1&& set PYTHONIOENCODING=utf-8&& \"C:\\Program Files\\Python314\\python.exe\" ${REMOTE_GUARD//\//\\} $* > ${REMOTE_OUT//\//\\} 2>&1" \
      >/dev/null 2>&1; then
    # python 自己非零退出也会走到这里，所以不能直接判死——先把输出取回来看。
    SSH_FAILED=1
  else
    SSH_FAILED=0
  fi

  # ③ 取结果。取不回来是硬错误，必须出声。
  if ! scp -q -o ConnectTimeout=30 "${USER_AT}:${REMOTE_OUT}" "$TMP" 2>/dev/null; then
    echo "winrun: 远端没有产生输出文件（脚本可能根本没跑起来，或机器不可达）" >&2
    exit 4
  fi
  ssh -o ConnectTimeout=30 "$USER_AT" \
    "del /Q ${REMOTE_PY//\//\\} ${REMOTE_GUARD//\//\\} ${REMOTE_OUT//\//\\}" >/dev/null 2>&1 || true

  # ④ 空输出**不再当成成功**。这正是 826 那天骗过我的那一步。
  if [ ! -s "$TMP" ]; then
    echo "winrun: 脚本没有任何输出（0 字节）。可能是脚本本身没 print，" >&2
    echo "        也可能是远端 python 被杀/卡住。这不是成功，请当失败处理。" >&2
    exit 5
  fi
  python3 -c "$STRIP" "$TMP"
  [ "$SSH_FAILED" = 1 ] && echo "winrun: 注意——远端命令以非零退出结束（上面是它的输出）" >&2
  exit 0
fi

MODE="cmd"
if [ "${1:-}" = "--ps" ]; then MODE="ps"; shift; fi
CMD="${1:?用法: winrun.sh [--ps|--get] '<命令或路径>'}"

LOCAL_PS="$(mktemp)"
{
  # Windows PowerShell 5.1 reads a .ps1 as ANSI unless it opens with a
  # UTF-8 BOM. Without these three bytes, Chinese inside the script -
  # including in the command being run - is decoded as GBK and destroyed
  # before it executes.
  printf '\xef\xbb\xbf'
  echo '$ErrorActionPreference = "Continue"'
  echo '$ProgressPreference = "SilentlyContinue"'
  if [ "$MODE" = ps ]; then
    # A child process that writes UTF-8 (python with PYTHONUTF8, curl, git) is
    # decoded by whatever [Console]::OutputEncoding says. Pin it to UTF-8 so
    # their output survives capture; without this the bytes are read as GBK.
    echo '[Console]::OutputEncoding = [Text.Encoding]::UTF8'
    echo '$OutputEncoding = [Text.Encoding]::UTF8'
    echo '$env:PYTHONUTF8 = "1"'
    echo '$env:PYTHONIOENCODING = "utf-8"'
    printf '$out = & {\n%s\n} 2>&1 | Out-String\n' "$CMD"
  else
    # chcp 65001 first: cmd's default codepage here is 936, so a UTF-8
    # command line reaches it as mojibake before it ever runs.
    echo '$enc = [Console]::OutputEncoding'
    echo '[Console]::OutputEncoding = [Text.Encoding]::UTF8'
    printf '$out = & cmd /c "chcp 65001 >nul & %s" 2>&1 | Out-String\n' "$CMD"
    echo '[Console]::OutputEncoding = $enc'
  fi
  echo '[IO.File]::WriteAllText("C:\ProgramData\winrun.out", $out, (New-Object Text.UTF8Encoding($false)))'
} > "$LOCAL_PS"

# Delete the previous output first. Without this, a command that fails to
# produce output leaves the last run's file in place - and reading that as if
# it were the current result is exactly how stale data gets reported as fresh.
ssh -o ConnectTimeout=30 "$USER_AT" 'del /Q C:\ProgramData\winrun.out 2>nul' >/dev/null 2>&1 || true
scp -q -o ConnectTimeout=30 "$LOCAL_PS" "${USER_AT}:C:/ProgramData/winrun.ps1"
# Prefer PowerShell 7: it defaults to UTF-8 everywhere, so Get-Content on a
# UTF-8 file is simply correct, where Windows PowerShell 5.1 would decode it as
# ANSI and destroy it. 5.1 stays as the fallback because it is always present.
ssh -o ConnectTimeout=90 "$USER_AT" \
  'if exist "C:\Program Files\PowerShell\7\pwsh.exe" ("C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\winrun.ps1) else (powershell -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\winrun.ps1)' \
  >/dev/null 2>&1 || true
TMP="$(mktemp)"
trap 'rm -f "$TMP" "$LOCAL_PS"' EXIT
# 取不回输出文件是硬错误：说明脚本压根没跑（机器不可达 / pwsh 没起来），
# 而不是「这条命令没有输出」。这两件事必须分开报，混在一起就是静默失败。
if ! scp -q -o ConnectTimeout=30 "${USER_AT}:C:/ProgramData/winrun.out" "$TMP" 2>/dev/null; then
  echo "winrun: 远端没有产生 winrun.out（命令没跑起来，或机器不可达）" >&2
  exit 4
fi
# 空输出在 cmd/ps 模式下可能是合法的（比如 Get-Process 没匹配到），
# 所以不当失败，但要在 stderr 说一声，免得又被当成「成功且无事发生」。
[ -s "$TMP" ] || echo "winrun: 命令执行了，但没有任何输出（可能正常，也可能是命令写错了）" >&2
python3 -c "$STRIP" "$TMP"
