#!/usr/bin/env bash
# 编译 Fleet Monitor 并装进 ~/Applications，然后重启它。
#
# 为什么有这个脚本（2026-09-08 审出来的）：仓库里躺着一个编译好的
# `scripts/mac/FleetMonitor/FleetMonitor`，是 09-03 编的；而 main.swift 到 09-07
# 还在改（那天修的正是「机器关了一小时页面还是绿的」那个缓存问题）。
# 也就是说仓库里那份二进制**比源码旧四天**，谁照它跑谁拿到的是没修过的版本。
# 二进制从此不入库（.gitignore 挡着），要用就跑这个脚本现编。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/FleetMonitor/main.swift"
APP="$HOME/Applications/Fleet Monitor.app"
BIN="$APP/Contents/MacOS/FleetMonitor"

[ -f "$SRC" ] || { echo "找不到源码 $SRC"; exit 1; }
[ -d "$APP" ] || { echo "找不到应用包 $APP —— 它是手工搭的，别让脚本凭空造一个"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "▶ 编译（arm64，优化）"
swiftc -O -target arm64-apple-macos13.0 -o "$TMP/FleetMonitor" "$SRC"

if pgrep -f "Fleet Monitor.app/Contents/MacOS/FleetMonitor" >/dev/null; then
  echo "▶ 先退掉正在跑的那个"
  osascript -e 'quit app id "local.ark.fleetmonitor"' 2>/dev/null || pkill -f "Fleet Monitor.app/Contents/MacOS/FleetMonitor" || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    pgrep -f "Fleet Monitor.app/Contents/MacOS/FleetMonitor" >/dev/null || break
    /bin/sleep 0.3
  done
fi

echo "▶ 装进应用包"
cp "$TMP/FleetMonitor" "$BIN"
# 无签名的包换了可执行文件后，旧的签名会让 Gatekeeper 直接杀掉进程。
codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "  （临时签名没成功，继续）"

echo "▶ 起来"
open "$APP"
/bin/sleep 1
if pgrep -f "Fleet Monitor.app/Contents/MacOS/FleetMonitor" >/dev/null; then
  echo "✅ Fleet Monitor 已是当前源码编出来的版本"
else
  echo "❌ 起不来，自己开一次看报什么"; exit 1
fi
