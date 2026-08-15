#!/bin/bash
# 把 strip-transcript-images.py 打包成一个可以双击的 Mac 应用。
#
#     ./make-app.sh              -> ~/Applications/会话瘦身.app
#     ./make-app.sh /path/to/dir -> 装到别处
#
# 脚本会被复制进 app 内部，所以打包完这个仓库挪走、删掉都不影响它运行。
# 应用先预演一遍并把结果给用户看，确认之后才写回。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/Applications}"
APP="$DEST/会话瘦身.app"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$HERE/strip-transcript-images.py" "$APP/Contents/Resources/strip.py"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>会话瘦身</string>
  <key>CFBundleDisplayName</key><string>会话瘦身</string>
  <key>CFBundleIdentifier</key><string>local.ark.transcript-slimmer</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>run</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/run" <<'SH'
#!/bin/bash
# 预演 -> 让用户过目 -> 确认后才写回。
HERE="$(cd "$(dirname "$0")/../Resources" && pwd)"
PY=$(command -v python3 || echo /usr/bin/python3)

SCAN=$("$PY" "$HERE/strip.py" --live-window 0 2>&1)
if ! echo "$SCAN" | grep -q "合计"; then
  osascript -e "display dialog \"没找到可清理的会话存档。\" with title \"会话瘦身\" buttons {\"好\"} default button 1" >/dev/null 2>&1
  exit 0
fi

esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}'; }
SUMMARY=$(esc "$(echo "$SCAN" | grep -E '张截图|合计' | sed 's/^ *//' | head -20)")

CHOICE=$(osascript -e "display dialog \"下面是可以清掉的内嵌截图：\n\n$SUMMARY\n\n截图会被替换成一行文字说明，对话内容一个字都不会动。\" with title \"会话瘦身\" buttons {\"取消\",\"清理\"} default button \"清理\"" 2>/dev/null)
[ -z "$CHOICE" ] && exit 0
echo "$CHOICE" | grep -q "清理" || exit 0

RESULT=$("$PY" "$HERE/strip.py" --apply --force --live-window 0 2>&1)
DONE=$(esc "$(echo "$RESULT" | grep -E '张截图|合计|追赶' | sed 's/^ *//' | head -20)")
osascript -e "display dialog \"清理完成。\n\n$DONE\" with title \"会话瘦身\" buttons {\"好\"} default button 1" >/dev/null 2>&1
SH

chmod +x "$APP/Contents/MacOS/run"
echo "✅ 已生成 $APP"
