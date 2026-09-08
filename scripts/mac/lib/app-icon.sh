#!/bin/bash
# set_app_icon <app dir> <1024px png>
# Builds Contents/Resources/AppIcon.icns from the PNG and registers it in Info.plist.
set_app_icon() {
  local app="$1" png="$2" set
  set=$(mktemp -d /tmp/iconset-XXXX)/AppIcon.iconset
  mkdir -p "$set" "$app/Contents/Resources"
  local sz
  for sz in 16 32 128 256 512; do
    sips -z "$sz" "$sz" "$png" --out "$set/icon_${sz}x${sz}.png" >/dev/null
    sips -z $((sz*2)) $((sz*2)) "$png" --out "$set/icon_${sz}x${sz}@2x.png" >/dev/null
  done
  iconutil -c icns -o "$app/Contents/Resources/AppIcon.icns" "$set"
  rm -rf "$(dirname "$set")"
  /usr/libexec/PlistBuddy -c 'Delete :CFBundleIconFile' "$app/Contents/Info.plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string AppIcon' "$app/Contents/Info.plist"
  touch "$app"
}
