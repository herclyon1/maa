#!/usr/bin/env bash
# 把一个本地 HTML 渲成 PNG。
#
#   scripts/mac/html2png.sh <in.html> <out.png> [宽] [高] [背景色]
#
# 为什么要包这一层，而不是每次现敲 Chrome 命令：
#
# 1. **Chrome 的 stderr 是脏的。** 它在日志系统初始化之前就会往 stderr 写
#    `Trying to load the allocator multiple times`，以及在这台 Mac 上还有
#    `ERROR:base/process/process_mac.cc:53 task_policy_set ...`。
#    `--log-level=3` 对它们**无效**（2026-08-26 实测过），因为那时候
#    日志级别还没生效。
# 2. **但也不能 `2>/dev/null`**：Chrome 把「N bytes written to file」这条
#    **成功信息也写在 stderr**。一刀切会把成功与否一起丢掉。
# 3. 所以只能精确滤掉已知无害的几行，**然后用产出文件本身判断成败**——
#    文件在且非空才算成功。这比看 Chrome 的退出码可靠：它对渲染失败
#    也经常返回 0。
#
# 2026-08-26 之前这段是每次现敲 + `grep -v` 现滤，属于典型的「绕过去而不修」。
set -euo pipefail

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[ -x "$CHROME" ] || { echo "html2png: 找不到 Chrome：$CHROME" >&2; exit 2; }

IN="${1:?用法: html2png.sh <in.html> <out.png> [宽] [高] [背景色]}"
OUT="${2:?用法: html2png.sh <in.html> <out.png> [宽] [高] [背景色]}"
W="${3:-1000}"
H="${4:-1400}"
BG="${5:-FFFFFF}"

[ -f "$IN" ] || { echo "html2png: 输入文件不存在：$IN" >&2; exit 2; }
rm -f "$OUT"

# 已知无害、必须滤掉的行。新出现的噪音**不要**往这里加，先确认它真的无害。
BENIGN='Trying to load the allocator multiple times|task_policy_set|process_mac\.cc|bytes written to file'

set +e
ERRTXT=$("$CHROME" --headless --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=2 \
  --default-background-color="$BG" \
  --window-size="${W},${H}" \
  --screenshot="$OUT" "$IN" 2>&1 >/dev/null)
set -e

# 滤掉已知无害之后还剩下的，是真问题，必须让人看见。
REST=$(printf '%s\n' "$ERRTXT" | grep -Ev "$BENIGN" | grep -v '^[[:space:]]*$' || true)
[ -n "$REST" ] && { echo "html2png: Chrome 报了非预期的东西：" >&2; printf '%s\n' "$REST" >&2; }

# 成败以产出为准，不看 Chrome 的退出码——它渲染失败也常常返回 0。
if [ ! -s "$OUT" ]; then
  echo "html2png: 没有产出 $OUT（或是 0 字节），渲染失败" >&2
  exit 1
fi
SIZE=$(python3 -c "import sys,os;print(f'{os.path.getsize(sys.argv[1]):,}')" "$OUT")
DIM=$(sips -g pixelWidth -g pixelHeight "$OUT" 2>/dev/null |
      awk '/pixel/{printf "%s ", $2}' | awk '{print $1"x"$2}')
echo "html2png: ✅ $OUT  ${DIM}  ${SIZE} 字节"
