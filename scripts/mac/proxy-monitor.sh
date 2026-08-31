#!/usr/bin/env bash
# 监视云原神的流量到底走没走 ins 隧道。**要在游戏画面真的在跑的时候用。**
#   proxy-monitor.sh [秒数，默认10]
#
# 判据：
#   隧道下行几十 Mbps        → 视频走隧道，加速生效
#   隧道几乎为 0 但游戏在跑  → 视频走 UDP 直连，绕过了 SOCKS（WebRTC 常见），加速没用上
set -uo pipefail
SEC="${1:-10}"
PID=$(pgrep -f 'ssh -f -N -D 127.0.0.1:1080' | head -1)
[ -z "$PID" ] && { echo "✋ 隧道没在跑"; exit 1; }

snap() { nettop -P -J bytes_in,bytes_out -l 1 -p "$1" 2>/dev/null | awk '/ssh\./{gsub(/[^0-9 ]/,"");print $(NF-1), $NF}'; }
kib() { awk -v a="$1" -v b="$2" -v s="$3" 'BEGIN{printf "%.2f", (b-a)*1024*8/s/1000000}'; }

set -- $(snap "$PID"); i0=${1:-0}; o0=${2:-0}
sleep "$SEC"
set -- $(snap "$PID"); i1=${1:-0}; o1=${2:-0}

echo "── 隧道吞吐（${SEC} 秒）──"
printf "  下行 %s Mbps    上行 %s Mbps\n" "$(kib $i0 $i1 $SEC)" "$(kib $o0 $o1 $SEC)"
echo
echo "── Chrome 走代理的连接数 ──"
printf "  %s 条 → 127.0.0.1:1080\n" "$(lsof -nP -iTCP:1080 2>/dev/null | grep -c ESTABLISHED)"
echo
echo "── Chrome 绕过代理的外网连接 ──"
d=$(lsof -nP -iTCP -sTCP:ESTABLISHED 2>/dev/null | grep -i Google | awk '{print $9}' |
    grep -oE '\->[0-9.]+:[0-9]+' | sed 's/->//' | grep -v '^127\.' | sort | uniq -c | sort -rn | head -6)
[ -n "$d" ] && echo "$d" | sed 's/^/  /' || echo "  无（TCP 全部走代理）"
echo
echo "── Chrome 的 UDP 对端（视频若走这里就绕过了代理）──"
u=$(lsof -nP -iUDP 2>/dev/null | grep -i Google | awk '{print $9}' | grep -E '\->' | sort -u | head -8)
[ -n "$u" ] && echo "$u" | sed 's/^/  /' || echo "  无对端（只有本地监听）"
