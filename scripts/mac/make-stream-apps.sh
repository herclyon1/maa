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

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/moonlight-params.sh
source "$HERE/lib/moonlight-params.sh"
HOST="$MOON_HOST"
APP="$MOON_APP"
DESK="$HOME/Desktop"

# 共用的那部分在 lib/moonlight-params.sh 里；这里只加启动器特有的两项：
# --no-performance-overlay 关掉左上角浮层（命令行那条反而要开着看链路质量）；
# --capture-system-keys always 让 ⌘（映射成 Win 键）等系统快捷键透传给 Windows。
# shellcheck disable=SC2086  # 有意按空白拆成多个参数
COMMON=$(echo $MOON_COMMON --no-performance-overlay --capture-system-keys always --absolute-mouse)

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
  # 失败必须看得见。原来是 `execv(...); return 1;`：Moonlight 被挪走、改名、
  # 或者哪次升级不认某个开关，从 Finder 双击就是「点了没反应」——没有弹窗、
  # 没有崩溃报告、没有系统日志，Moonlight 自己那份日志是 0 字节（报错走的 stderr）。
  # 用户唯一能自助的入口，失败时零线索。现在 fork 出来跑、接住 stderr，
  # 非零退出就用 osascript 把退出码和错误原文弹出来。
  cat > "$src" <<CSRC
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

int main(void) {
    char *a[] = { "$MOON", "stream", "$HOST", "$APP",
                  "--bitrate", "$br", "--video-codec", "$codec", "$yuv", "--resolution", "$res",
$(printf '%s\n' $COMMON | sed 's/.*/                  "&",/')
                  (char*)0 };
    char log[] = "/tmp/stream-launcher-XXXXXX";
    int fd = mkstemp(log);
    pid_t pid = fork();
    if (pid == 0) {
        if (fd >= 0) { dup2(fd, 1); dup2(fd, 2); }
        execv("$MOON", a);
        _exit(127);
    }
    int st = 0, code = -1;
    if (pid > 0 && waitpid(pid, &st, 0) == pid && WIFEXITED(st)) code = WEXITSTATUS(st);
    if (code == 0) { unlink(log); return 0; }
    char buf[1200];
    size_t n = 0;
    FILE *f = fopen(log, "r");
    if (f) { n = fread(buf, 1, sizeof buf - 1, f); fclose(f); }
    buf[n] = 0;
    for (size_t i = 0; i < n; i++) {
        if (buf[i] == '"' || buf[i] == 92) buf[i] = ' ';
    }
    char script[2600];
    snprintf(script, sizeof script,
             "display alert \"串流没起来\" message \"退出码 %d。原因在下面，"
             "多半是 Moonlight 换了位置，或者升级之后不认某个开关。\n\n%s\n\n"
             "完整输出：%s\" as critical",
             code, n ? buf : "（它一个字都没输出）", log);
    execl("/usr/bin/osascript", "osascript", "-e", script, (char*)0);
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

make_one "串流到ins"         "$MOON_BITRATE" "$MOON_CODEC" "$MOON_YUV" "$MOON_RES"
make_one "串流到ins-HEVC444" 55000            HEVC           --yuv444    "$MOON_RES"
echo "完成。参数要改就改 scripts/mac/lib/moonlight-params.sh，然后重跑本脚本。"
