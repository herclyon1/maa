#!/bin/bash
# 把 UsbCheck 编译打包成可双击的 优盘体检.app
#     ./make-app.sh            -> ~/Desktop/优盘体检.app
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/优盘体检.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -parse-as-library -o "$APP/Contents/MacOS/UsbCheck" "$HERE/main.swift" \
  -framework SwiftUI -framework AppKit
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>优盘体检</string>
  <key>CFBundleDisplayName</key><string>优盘体检</string>
  <key>CFBundleIdentifier</key><string>local.ark.usbcheck</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>UsbCheck</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict>
    <key>NSAllowsArbitraryLoads</key><true/>
  </dict>
</dict>
</plist>
PLIST
codesign --force --deep -s - "$APP" 2>/dev/null || true
echo "打包完成: $APP"
