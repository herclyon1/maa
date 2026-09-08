#!/bin/bash
# Build ~/Desktop/云原神.app: turns Cloudflare WARP on if needed, then opens the cloud-game page in Chrome.
# The main executable is a compiled arm64 binary (a shell script there makes macOS ask for Rosetta).
set -euo pipefail
APP="$HOME/Desktop/云原神.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>云原神</string>
  <key>CFBundleDisplayName</key><string>云原神</string>
  <key>CFBundleIdentifier</key><string>local.ark.cloud-genshin</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST
cat > "$APP/Contents/Resources/run.sh" <<'SH'
#!/bin/bash
# 1) WARP on (the home ISP has no working path to mainland China; WARP is the free detour).
# 2) Open the page in Chrome. The prewarm extension in Chrome does the rest.
WARP=/usr/local/bin/warp-cli
if ! "$WARP" status 2>/dev/null | grep -q 'Connected'; then
  "$WARP" connect >/dev/null 2>&1 || true
  sleep 3   # one-shot grace for the tunnel to come up; not a loop
fi
open -a "Google Chrome" "https://ys.mihoyo.com/cloud/"
SH
chmod +x "$APP/Contents/Resources/run.sh"
SRC=$(mktemp /tmp/launcher.XXXXXX.c)
cat > "$SRC" <<'C'
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <libgen.h>
#include <mach-o/dyld.h>
int main(void){
  char path[4096]; uint32_t n=sizeof(path);
  if(_NSGetExecutablePath(path,&n)!=0) return 1;
  char *dir=dirname(path);
  char script[4600]; snprintf(script,sizeof(script),"%s/../Resources/run.sh",dir);
  execl("/bin/bash","bash",script,(char*)0);
  return 1;
}
C
clang -arch arm64 -O2 -o "$APP/Contents/MacOS/launcher" "$SRC"
rm -f "$SRC"
touch "$APP"
echo "built $APP"
