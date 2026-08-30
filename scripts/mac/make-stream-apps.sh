#!/usr/bin/env bash
# 生成/更新桌面上的串流启动器。**参数只在这里改，改 app 内部没用**（会被下次重跑覆盖）。
#
# 为什么要有这个脚本：2026-08-30 我要改浮层开关，发现桌面上的 app 是上次做的、
# 仓库里没有源码，只能 strings 逆向二进制猜参数，来回折腾了很久。
#
# --absolute-mouse 为什么必须开（2026-08-30 定位）：
#   相对模式发的是位移增量，走可靠有序传输。链路丢包时增量永久丢失，
#   且有序传输会**队头阻塞**——后面的包得等重传，190ms 往返一次卡 400ms+。
#   症状是「画面不卡，但拖鼠标断成几截」。
#   绝对模式发的是绝对坐标，丢包由下一个包自愈，不重传不阻塞。
#   注意：游戏里转视角要相对模式，进游戏按 Ctrl+Alt+Shift+M 切回。
#
# 两个坑，都踩过：
#  1. **Moonlight 命令行参数优先级高于配置文件**。app 里写死了 --performance-overlay，
#     所以 `defaults write ... showperfoverlay 0` 完全无效。改设置要改这里。
#  2. **macOS 不让覆盖已签名 app 内部的文件**（无完全磁盘访问时）。
#     没权限时表现为：列目录拒绝、按路径读允许、新建允许、**覆盖/删除拒绝**。
#     而 TCC 按版本号路径授权，Claude Code 自动更新后旧会话会失权，要重开。
#     见 memory/tcc-breaks-after-autoupdate.md
set -euo pipefail

MOON=/Applications/Moonlight.app/Contents/MacOS/Moonlight
HOST=100.65.39.119
APP=Desktop
DESK="$HOME/Desktop"

# 所有启动器共用。--no-performance-overlay 关掉左上角浮层；
# --capture-system-keys always 让 ⌘（映射成 Win 键）等系统快捷键透传给 Windows。
COMMON='--fps 60 --video-decoder hardware --hdr
        --no-vsync --no-frame-pacing --no-game-optimization
        --display-mode borderless --keep-awake
        --no-performance-overlay --capture-system-keys always
        --absolute-mouse'
COMMON=$(echo $COMMON)

make_one() {   # $1=app名  $2=码率  $3=编码  $4=yuv444开关
  local name="$1" br="$2" codec="$3" yuv="$4" res="$5"
  local d="$DESK/$name.app"
  mkdir -p "$d/Contents/MacOS"
  [ -f "$d/Contents/Info.plist" ] || cat > "$d/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$name</string>
  <key>CFBundleDisplayName</key><string>$name</string>
  <key>CFBundleIdentifier</key><string>local.moonlight.$(echo "$name" | md5 -q | cut -c1-10)</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST
  printf 'APPL????' > "$d/Contents/PkgInfo"
  # 主可执行文件必须是**真正的 Mach-O 二进制**，不能是 shell 脚本。
  # 2026-08-30 我图省事写成了脚本，双击时 macOS 弹「需要安装 Rosetta」——
  # 脚本当 app 主程序，LaunchServices 判不出架构就会这样。原版本来就是编译的。
  local src; src=$(mktemp /tmp/launcher-XXXX.c)
  cat > "$src" <<CSRC
#include <unistd.h>
int main(void) {
    char *a[] = { "$MOON", "stream", "$HOST", "$APP",
                  "--bitrate", "$br", "--video-codec", "$codec", "$yuv", "--resolution", "$res",
$(printf '%s\n' $COMMON | sed 's/.*/                  "&",/')
                  (char*)0 };
    execv("$MOON", a);
    return 1;
}
CSRC
  clang -arch arm64 -O2 -o "$d/Contents/MacOS/launcher" "$src"
  rm -f "$src"
  chmod +x "$d/Contents/MacOS/launcher"
  rm -rf "$d/Contents/_CodeSignature"
  codesign -f -s - "$d" 2>/dev/null || true
  echo "  ✓ $name  (码率 $br, $codec, $yuv)"
}

make_one "串流到ins"         70000 AV1  --no-yuv444 2880x1864
make_one "串流到ins-HEVC444" 55000 HEVC --yuv444   2880x1864
echo "完成。参数要改就改本脚本顶部，然后重跑。"
