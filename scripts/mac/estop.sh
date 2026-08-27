#!/usr/bin/env bash
# 红按钮 —— 一键停掉游戏机上的一切：AUTO-MAS、全部脚本、全部游戏。
#
#   scripts/mac/estop.sh            # 停：杀进程 + 关队列定时（默认，最彻底）
#   scripts/mac/estop.sh --list     # 只看现在有什么在跑，不动手
#   scripts/mac/estop.sh --keep-queue   # 只杀进程，不碰队列定时
#   scripts/mac/estop.sh --restore  # 把队列定时改回 True（停完之后恢复用）
#
# 为什么这个脚本长这样，全是 2026-08-26 那次事故当场踩出来的：
#
#   * **用 base64 编码的 pwsh**。那天 `pwsh -c "...match \"A|B\"..."` 被 bash/ssh/cmd
#     三层引号吃掉，报 `'Wuthering' 不是内部或外部命令`。EncodedCommand 没有引号问题。
#   * **用 pwsh 7 不用 powershell 5.1**。5.1 读 UTF-8 的 JSON 会乱码，
#     `ConvertFrom-Json` 直接失败。见 memory `use-pwsh7-not-powershell51`。
#   * **先杀进程再动 API**。那天 MAS 的配置接口回 `配置已锁定, 无法修改`，
#     连试 18 次都写不进去；而进程是一定杀得掉的。API 只当补充。
#   * **杀完必须回查**。那天杀完 Endfield，它立刻被 AUTO-MAS 用新 PID 拉起来了。
#     不回查就会以为停干净了。所以这里杀两轮 + 最终确认。
#   * **AUTO-MAS 必须一起杀**。只杀游戏没用，编排器还在就会重新拉起来。
#
# **会停 `ark-relay` 服务**——它会自动把 AUTO-MAS 救活（证据见 ⓪ 段），
# 不停它这个红按钮就是废的。代价是停机期间没有通知，所以用完必须 --restore。
set -uo pipefail

HOST="${ARK_HOST:-100.65.39.119}"
USER_AT="Administrator@${HOST}"
API="http://${HOST}:36163"
SSH=(ssh -o ConnectTimeout=25 -o ServerAliveInterval=5 -o ServerAliveCountMax=3)

# ── 关停顺序：MAS → 脚本 → 游戏。顺序错了等于没关。 ───────────
#
# 2026-08-26 事故当天我先杀 MAA/MaaEnd/Endfield，**没杀 AUTO-MAS**，
# 编排器还活着，Endfield 立刻用新 PID 回来了。用户原话：
# 「你一个都没有关成功，全是我手动关的，因为 mas 一直在拉进程，
#   你没有先关 mas，后关脚本，然后关游戏」。
#
# 所以这里**分三层、按顺序杀，每层杀完确认死透了再进下一层**。
# 不要合并成一条正则一次性 Stop-Process —— 那样 Get-Process 的返回顺序
# 决定了谁先死，AUTO-MAS 可能排在最后，坑一模一样。
TIER1_MAS='AUTO-MAS'                                   # 编排器：必须第一个死
TIER2_SCRIPT='MaaEnd|^MAA$|ok-ww|okww|ok_ww'           # 脚本
TIER3_GAME='Endfield|Client-Win64|Wuthering|wuwa|KRSDK|KRLauncher'  # 游戏本体
PATTERN="$TIER1_MAS|$TIER2_SCRIPT|$TIER3_GAME"

MODE="stop"
KEEP_QUEUE=0
for a in "$@"; do
  case "$a" in
    --list)       MODE="list" ;;
    --restore)    MODE="restore" ;;
    --keep-queue) KEEP_QUEUE=1 ;;
    -h|--help)    sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "不认识的参数: $a" >&2; exit 2 ;;
  esac
done

# 把一段 PowerShell 编码后送过去执行。返回它的 stdout。
run_ps() {
  local b64
  b64=$(printf '%s' "$1" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')
  "${SSH[@]}" "$USER_AT" "pwsh -NoProfile -EncodedCommand $b64" 2>&1
}

list_ps="Get-Process | Where-Object { \$_.ProcessName -match '$PATTERN' } |
  ForEach-Object { '  ' + \$_.ProcessName + '  pid=' + \$_.Id }"

# 杀一层，然后原地等它真的消失（最多 ~6 秒），再返回。
# 「发了 Stop-Process」不等于「它死了」；不等就进下一层，等于没分层。
# PowerShell 侧**只输出 ASCII**，中文一律由 bash 这边打印。
# 2026-08-26 实测：中文经过 936 的控制台必然变成 `[MAS] ��ȷ��ȫ���˳�`，
# 而红按钮是应急工具，输出看不懂等于没有输出。
# 约定的机器可读行：KILL <名字> <pid> / NONE / GONE / STUCK <名字> <pid>
mk_kill_tier() {
  local re="$1"
  cat <<PSEOF
\$re = '$re'
\$hit = Get-Process | Where-Object { \$_.ProcessName -match \$re }
if (-not \$hit) { Write-Output 'NONE' }
foreach (\$p in \$hit) {
  Write-Output ('KILL ' + \$p.ProcessName + ' ' + \$p.Id)
  Stop-Process -Id \$p.Id -Force -ErrorAction SilentlyContinue
}
for (\$i = 0; \$i -lt 12; \$i++) {
  \$left = Get-Process | Where-Object { \$_.ProcessName -match \$re }
  if (-not \$left) { Write-Output 'GONE'; break }
  Start-Sleep -Milliseconds 500
}
foreach (\$p in (Get-Process | Where-Object { \$_.ProcessName -match \$re })) {
  Write-Output ('STUCK ' + \$p.ProcessName + ' ' + \$p.Id)
}
PSEOF
}

# 把上面那些 ASCII 行翻成中文。杀不掉的返回非零，让调用方能判死。
kill_tier() {
  local re="$1" label="$2" out rc=0
  # 必须 tr -d '\r'：Windows 行尾会让 `NONE\r` / `GONE\r` 匹配不上 case 分支，
  # 于是那两层一行都不打印，看着像「什么都没发生」。KILL 那行反而正常，
  # 因为 \r 挂在最后一个字段（pid）上，动词没被污染——这种半哑的失败最难发现。
  out=$(run_ps "$(mk_kill_tier "$re")" | tr -d '\r')
  while IFS=' ' read -r verb nm pid; do
    case "$verb" in
      KILL)  echo "  [$label] 已终止 $nm (pid=$pid)" ;;
      NONE)  echo "  [$label] 本来就没有在跑" ;;
      GONE)  echo "  [$label] 已确认全部退出" ;;
      STUCK) echo "  [$label] ⚠️ 杀不掉 $nm (pid=$pid)"; rc=1 ;;
    esac
  done <<<"$out"
  return $rc
}

# ── 只看不动 ────────────────────────────────────────────────
if [[ "$MODE" == "list" ]]; then
  echo "== 现在在跑的（匹配红按钮清单）=="
  out=$(run_ps "$list_ps")
  [[ -z "${out// /}" ]] && echo "  （没有）" || echo "$out"
  exit 0
fi

# ── 恢复：中继服务 + 队列定时 ───────────────────────────────
if [[ "$MODE" == "restore" ]]; then
  echo "-- 先把 ark-relay 拉回来（红按钮停过它，不恢复就再也收不到任何通知）--"
  "${SSH[@]}" "$USER_AT" 'sc start ark-relay' >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5 6; do
    st=$("${SSH[@]}" "$USER_AT" 'sc query ark-relay' 2>/dev/null | tr -d '\r')
    case "$st" in
      *RUNNING*) echo "  ✅ ark-relay 已在运行"; break ;;
      *)         sleep 2 ;;
    esac
  done
  case "${st:-}" in
    *RUNNING*) : ;;
    *) echo "  ❌ ark-relay 没起来，通知链路是断的，必须人工看一眼" >&2 ;;
  esac
  # 中继要等 180 秒（REVIVE_FIRST_WAIT）才会去救 AUTO-MAS，而队列 API 就住在
  # AUTO-MAS 里。2026-08-26 第一版 --restore 启动中继后立刻调 API，必然超时失败。
  # 直接踢它的计划任务——中继内部 `_revive_automas()` 也是这么干的，不用干等。
  echo "-- 拉起 AUTO-MAS（不等中继那 180 秒）--"
  "${SSH[@]}" "$USER_AT" 'schtasks /run /tn AUTO-MAS_AutoStart' >/dev/null 2>&1 || true
  MAS_UP=0
  for _ in $(seq 1 30); do
    if curl -s --max-time 4 -X POST -H 'Content-Type: application/json' -d '{}' \
         "$API/api/queue/get" >/dev/null 2>&1; then MAS_UP=1; break; fi
    sleep 4
  done
  if [[ "$MAS_UP" == "1" ]]; then
    echo "  ✅ AUTO-MAS 已就绪（API 能应答了）"
  else
    echo "  ❌ 等了两分钟 AUTO-MAS 的 API 还是不通，队列恢复不了" >&2
    echo "     手动看一眼：ssh $USER_AT 'schtasks /run /tn AUTO-MAS_AutoStart'" >&2
    exit 9
  fi

  echo "-- 再恢复队列定时 --"
  python3 - "$API" <<'PY'
import json, sys, urllib.request
API = sys.argv[1]
def post(p, b):
    r = urllib.request.Request(API + p, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=20) as x:
        return json.loads(x.read().decode())
try:
    q = post("/api/queue/get", {})
except Exception as e:
    sys.exit(f"✗ 连不上 MAS（是不是没开？）：{e}")
for uid, cfg in q["data"].items():
    cfg["Info"]["TimeEnabled"] = True
    post("/api/queue/update", {"queueId": uid, "data": cfg})
for uid, cfg in post("/api/queue/get", {})["data"].items():
    print(f"  {cfg['Info']['Name']}  定时启用 = {cfg['Info']['TimeEnabled']}")
PY
  exit $?
fi

# ── 停 ──────────────────────────────────────────────────────
echo "== 红按钮：停止一切（顺序 中继 → MAS → 脚本 → 游戏）=="
# 队列定时必须**趁 MAS 还活着**关——它的 API 就住在 AUTO-MAS 里，人一杀就调不通了。
# 2026-08-26 第一次实测时这段排在杀进程之后，于是每次都超时失败，
# 还照样打印「队列定时已关闭」——**谎报**。现在提到最前面，并且如实汇报成败。
QUEUE_OFF="skipped"
if [[ "$KEEP_QUEUE" == "0" ]]; then
  echo "-- 先关队列定时（趁 MAS 还在，它的 API 在 MAS 里）--"
  python3 - "$API" <<'PYQ'
import json, sys, urllib.request
API = sys.argv[1]
def post(p, b):
    r = urllib.request.Request(API + p, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=8) as x:
        return json.loads(x.read().decode())
try:
    q = post("/api/queue/get", {})
    for uid, cfg in q["data"].items():
        cfg["Info"]["TimeEnabled"] = False
        post("/api/queue/update", {"queueId": uid, "data": cfg})
        print(f"  [队列] {cfg['Info']['Name']} 定时已关")
except Exception as exc:                     # 一行话，不许甩 traceback
    print(f"  [队列] 关不掉（{type(exc).__name__}）——MAS 可能已经不在了",
          file=sys.stderr)
    sys.exit(1)
PYQ
  if [ $? -eq 0 ]; then QUEUE_OFF="done"; else QUEUE_OFF="failed"; fi
fi


# ⓪ 2026-08-26 从 relay.log 里挖出来的：**中继会把 AUTO-MAS 救活。**
#
#   09:28:13 WARNING ark.service  AUTO-MAS 后端退出了
#   09:28:13 WARNING ark.service  AUTO-MAS 后端不在，正在拉起（第 1 次）
#   09:29:06 INFO    ark.service  AUTO-MAS 已启动，进程句柄已挂上
#
# service.py 里 `_revive_automas()` 是**无条件调用**的，没有任何 debug 门控
# （调试模式只管「不关机、不报漏跑」，不管这个）。它还挂了进程句柄 + WMI
# 事件订阅专门盯着 AUTO-MAS 退没退，所以杀掉后几十秒就回来。
#
# 事故当天我以为是 MAS 自己复活，其实是中继救的。**不先停中继，这个红按钮是废的。**
# 代价：停了中继就没有任何通知了（包括「机器出事」的通知），所以 --restore 必须拉回来。
echo "-- ⓪ ark-relay 服务（它会把 AUTO-MAS 救活，必须第一个停）--"
if "${SSH[@]}" "$USER_AT" 'sc stop ark-relay' >/dev/null 2>&1; then
  echo "  [中继] 已发停止指令"
else
  echo "  [中继] 停止指令返回非零（可能本来就没在跑）"
fi
for _ in 1 2 3 4 5 6; do
  st=$("${SSH[@]}" "$USER_AT" 'sc query ark-relay' 2>/dev/null | tr -d '\r')
  case "$st" in
    *STOPPED*) echo "  [中继] 已确认停止"; break ;;
    *)         sleep 2 ;;
  esac
done

echo "-- ① AUTO-MAS（编排器，杀在中继之后，否则会被救活）--"
kill_tier "$TIER1_MAS" "MAS" || true

echo "-- ② 脚本（MAA / MaaEnd / OK-WW）--"
kill_tier "$TIER2_SCRIPT" "脚本" || true

echo "-- ③ 游戏（终末地 / 鸣潮 / 库洛启动器）--"
kill_tier "$TIER3_GAME" "游戏" || true

# 收尾再扫一遍全清单：万一 ① 死之前恰好拉起了什么，这一轮兜掉。
echo "-- ④ 兜底复扫（防止 ① 咽气前又拉起了东西）--"
kill_tier "$PATTERN" "兜底" || true


echo "-- 最终确认 --"
left=$(run_ps "$list_ps")
if [[ -z "${left// /}" ]]; then
  echo "  ✅ 进程干净了，一个都没剩"
  case "$QUEUE_OFF" in
    done)    echo "  ⚠️  队列定时已关闭 —— 恢复用 scripts/mac/estop.sh --restore" ;;
    failed)  echo "  ⚠️  队列定时**没能关掉**。现在没进程在跑所以安全，但下次 MAS 起来会照常触发。" >&2 ;;
    skipped) echo "  · 队列定时未改动（--keep-queue）" ;;
  esac
  echo "  · ark-relay 已停 —— 通知链路是断的，恢复用 scripts/mac/estop.sh --restore"
  exit 0
fi
echo "  ❌ 还有残留："
echo "$left"
echo "  再跑一次这个脚本；仍然杀不掉就是权限问题，需要人工介入。"
exit 1
