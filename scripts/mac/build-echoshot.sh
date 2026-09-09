#!/usr/bin/env bash
# Build EchoShot, install it into ~/Applications, and run it at login.
#
# One key, one screenshot, into ~/Pictures/EchoShots. See EchoShot/main.swift for why this
# is a hand-rolled 60-line app rather than Karabiner or Hammerspoon.
#
#   scripts/mac/build-echoshot.sh          build, install, start, run at login
#   scripts/mac/build-echoshot.sh --off    stop it and stop launching it at login
#   scripts/mac/build-echoshot.sh --on     start it again
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/EchoShot/main.swift"
APP="$HOME/Applications/EchoShot.app"
BIN="$APP/Contents/MacOS/EchoShot"
PLIST="$HOME/Library/LaunchAgents/local.ark.echoshot.plist"
LABEL="gui/$(id -u)/local.ark.echoshot"

stop_it() { launchctl bootout "$LABEL" 2>/dev/null || true; pkill -f "EchoShot.app/Contents/MacOS/EchoShot" 2>/dev/null || true; }

case "${1:-}" in
  --off)
    stop_it
    launchctl disable "$LABEL" 2>/dev/null || true
    echo "✅ 已停。那个键恢复正常打字。要再开：$0 --on"
    exit 0 ;;
  --on)
    launchctl enable "$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || open "$APP"
    echo "✅ 已开。按一下热键截一张。"
    exit 0 ;;
  "") ;;
  *) echo "不认识的参数: $1" >&2; exit 2 ;;
esac

[ -f "$SRC" ] || { echo "找不到源码 $SRC" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "▶ 编译"
swiftc -O -target arm64-apple-macos13.0 -o "$TMP/EchoShot" "$SRC"

echo "▶ 装进 $APP"
stop_it
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<'PLI'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>EchoShot</string>
  <key>CFBundleDisplayName</key><string>EchoShot</string>
  <key>CFBundleIdentifier</key><string>local.ark.echoshot</string>
  <key>CFBundleExecutable</key><string>EchoShot</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLI
cp "$TMP/EchoShot" "$BIN"
chmod +x "$BIN"
# An unsigned bundle whose executable changed gets killed by Gatekeeper on launch.
codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "  （临时签名没成功，继续）"

echo "▶ 登录时自动起"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<PLI
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.ark.echoshot</string>
  <key>ProgramArguments</key>
  <array><string>$BIN</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
PLI
launchctl bootout "$LABEL" 2>/dev/null || true
launchctl enable "$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

/bin/sleep 1
if pgrep -f "EchoShot.app/Contents/MacOS/EchoShot" >/dev/null; then
  echo "✅ 起来了"
else
  echo "❌ 没起来，直接跑一次看报什么：$BIN" >&2; exit 1
fi

cat <<'MSG'

按一下 ¥ 键（JIS 键盘数字键行最右边、delete 左边）就截一张，存到 ~/Pictures/EchoShots。
ANSI 键盘上是数字 1 左边那个 ` 键，开机时自己判断，不用你选。
听到「叮」＝存好了；听到「咚」＝没截到，那是屏幕录制权限没给：
系统设置 → 隐私与安全性 → 屏幕录制 → 打开 EchoShot。给完再按一次。

这个键被独占了，以后在别处打不出这个字符。不需要时：scripts/mac/build-echoshot.sh --off
想换成别的键：defaults write local.ark.echoshot keyCode -int <键码>，再跑一次这个脚本。
MSG
