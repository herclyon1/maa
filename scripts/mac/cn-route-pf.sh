#!/usr/bin/env bash
# 把「发往中国网段的 UDP」改写源地址为 Tailscale IP 并强制送进隧道。
#   sudo cn-route-pf.sh on / off / status
#
# 为什么要改源地址：macOS 按默认路由挑源地址→选中 en5 的 10.76.139.67，
# 一旦源地址属于 en5，目的地路由（指向 utun4）就被忽略。实测绑成
# 100.110.87.36 就能走隧道。所以 nat 改写源地址是必须的，
# 而且 ins 侧 WireGuard 只接受来自本机 100.x/32 的包，不改写会被静默丢弃。
#
# user UID：只改写**本机发起**的流量。转发的包（手机连 Mac 热点、
# bridge100/192.168.2.0/24）没有 user 归属，天然被排除——
# 2026-09-01 用户反馈没加这个时手机上网被影响。
#
# 必须放行 112.43.41.80（ins 的 WireGuard endpoint，落在 112.0.0.0/8 内），
# 否则会把隧道自己堵死。
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "要用 sudo 跑"; exit 1; }
A=/etc/pf.anchors/cnvideo
TSIP=100.110.87.36          # Mac 的 Tailscale 地址
TUN=utun4
EP=112.43.41.80             # ins 的 WireGuard endpoint

case "${1:-}" in
  on)
    cat > "$A" <<RULES
table <cnvideo> const { 101.0.0.0/8, 106.0.0.0/8, 112.0.0.0/8, 117.0.0.0/8, 120.0.0.0/8, 223.0.0.0/8 }
no nat on en5 proto udp from any to $EP
no nat on en5 proto udp from 192.168.2.0/24 to <cnvideo>
nat on en5 proto udp from any to <cnvideo> -> $TSIP
pass out quick on en5 proto udp from any to $EP
pass out quick on en5 route-to ($TUN $TSIP) proto udp from any to <cnvideo> user 501
RULES
    # 子网路由平时关着（开着会让所有中国网段绕道 ins，日常上网变慢）。
    # 这里顺手打开，off 时再关掉。
    /Applications/Tailscale.app/Contents/MacOS/Tailscale set --accept-routes 2>/dev/null || true
    sleep 3
    pfctl -E 2>/dev/null || true
    pfctl -f <(cat /etc/pf.conf; echo 'anchor "cnvideo"'; echo "load anchor \"cnvideo\" from \"$A\"")
    echo "✓ 已挂载"
    ;;
  off)
    # ★ 必须先清锚点内部的规则。只跑 pfctl -f /etc/pf.conf 不会清掉锚点里
    # 已加载的规则——2026-09-01 就是这个 bug 让用户手机断网：残留的
    # route-to 规则（且是没有 user 过滤的旧版）把手机的 UDP/DNS 塞进了隧道。
    pfctl -a cnvideo -F all 2>/dev/null || true
    pfctl -f /etc/pf.conf 2>/dev/null || true
    pfctl -F states 2>/dev/null || true
    /Applications/Tailscale.app/Contents/MacOS/Tailscale set --accept-routes=false 2>/dev/null || true
    rm -f "$A"
    echo "✓ 已还原（锚点已清空、连接状态已重置、子网路由已关）"
    ;;
  status)
    pfctl -a cnvideo -s rules 2>/dev/null || echo "(未挂载)"
    ;;
  *) echo "用法: sudo $0 on|off|status"; exit 2 ;;
esac
