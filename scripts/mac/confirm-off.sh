#!/usr/bin/env bash
# Is the game machine actually powered off, right now? Prints measured evidence.
#
# Why this exists (user's order, 2026-09-06): "状态类结论只能贴脚本输出。"
# I have claimed "机器已关机" from a Tailscale status line more than once, and
# Tailscale is wrong about this for hours: a machine that loses power never logs
# out, so control keeps reporting it Online until its own timeout. On 2026-09-03
# the two disagreed for over four hours. So the only claim this script makes is
# one it measured itself, and the output carries the evidence and the clock.
#
#   scripts/mac/confirm-off.sh
#
# Exit 0 = measured OFF. Exit 1 = measured ON. Exit 2 = could not tell.
set -uo pipefail
HOST="${ARK_HOST:-100.65.39.119}"
TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale

echo "本机(东京) $(date '+%F %H:%M:%S')  机器(北京) $(TZ=Asia/Shanghai date '+%F %H:%M:%S')"

# 1. Tailscale's own opinion — recorded, never trusted on its own.
claim="（问不到）"
if [ -x "$TS" ]; then
  claim=$("$TS" status 2>/dev/null | grep -F "$HOST" | sed 's/  */ /g' || echo "（列表里没有它）")
fi
echo "  Tailscale 说： ${claim:-（列表里没有它）}"

# 2. The measurement that decides. ssh is what every remote action actually
#    needs, so "can I ssh in" is the question worth answering - not ICMP, which
#    this link drops even when the machine is up.
# 用 cmd 的内置命令报时刻就够了，不碰 PowerShell：闸门（lint 第 2 项）不许裸用
# powershell（5.1 读中文必乱码），而为了一行时刻去走 pwsh7 + base64 不值当。
if out=$(ssh -o ConnectTimeout=12 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
         "Administrator@${HOST}" 'echo ALIVE & time /t' 2>&1); then
  echo "  实测 ssh：  连上了 —— $(tr -d '\r' <<<"$out" | tr '\n' ' ')"
  echo "❌ 机器【开着】。别说它关了。"
  exit 1
fi
reason=$(tr -d '\r' <<<"$out" | tail -1)
echo "  实测 ssh：  连不上 —— $reason"

# 3. ssh failing is not the same as powered off: a hung sshd, an antivirus
#    quarantine, or a dead link all look like this. Say which one this is.
case "$reason" in
  *"Operation timed out"*|*"No route to host"*|*"Host is down"*)
    echo "✅ 机器【关着】（ssh 连接超时/无路由，和断电的表现一致）"
    exit 0 ;;
  *"Connection refused"*)
    echo "⚠️ 端口拒绝连接：机器**开着**但 sshd 没在听（杀毒隔离过 sshd-session.exe，见 PITFALLS）"
    exit 1 ;;
  *)
    echo "⚠️ 说不准。上面那行是原始报错，别拿它当「关了」。"
    exit 2 ;;
esac
