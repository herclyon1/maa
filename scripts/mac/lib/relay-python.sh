#!/usr/bin/env bash
# 解析 Mac 上运行中继测试与工具的最新版 Python（零硬编码版本号，绝不回退 /usr/bin/python3）。
#
# 工作方式（严格遵循 ~/Money/tools/verify_latest_python.py 动态范式）：
#   1. 前置 /opt/homebrew/bin 到 PATH，入口固定为滚动无版本号 /opt/homebrew/bin/python3；
#   2. 运行时动态读取 /opt/homebrew/Cellar/python@* 最高已装版本，强制要求
#      called_ver == max_installed_ver（未来升级 3.15->3.16 / 3.18->3.19 零改码自动跟进）；
#   3. 在主仓库共享目录维护 .venv-relaytest（装齐 relay/requirements.txt 非 win32 依赖 + numpy），
#      当底层 Python 版本或依赖变化时自动重建，并校验虚拟环境实际版本与最新版完全一致。
set -euo pipefail
export PATH="${PATH}:/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin"

RELAY_BASE_PY="${RELAY_BASE_PY:-/opt/homebrew/bin/python3}"
if [ ! -x "$RELAY_BASE_PY" ]; then
  echo "relay-python: 找不到最新版 Python（${RELAY_BASE_PY}）；请用 brew install python 安装，严禁回退系统旧版" >&2
  exit 3
fi

# 动态比对 called_ver == max_installed_ver（零硬编码任何版本号字符串）
BASE_VER="$("$RELAY_BASE_PY" -c 'import re, sys; from pathlib import Path
cur = (sys.version_info[0], sys.version_info[1])
cellar = Path("/opt/homebrew/Cellar")
if cellar.is_dir():
    vers = []
    for p in cellar.glob("python@*"):
        m = re.search(r"(\d+)\.(\d+)", p.name)
        if m:
            vers.append((int(m.group(1)), int(m.group(2))))
    if vers and cur != max(vers):
        sys.stderr.write(f"relay-python: 调用版本 {cur[0]}.{cur[1]} != 本机 Homebrew 最高版本 {max(vers)[0]}.{max(vers)[1]}\n")
        sys.exit(4)
print(f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}")')"

here=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
common=$(git -C "$here" rev-parse --path-format=absolute --git-common-dir)
venv="${RELAY_VENV:-$(dirname "$common")/.venv-relaytest}"
# numpy 仅供 relay/tests 图像测试夹具使用，非游戏机中继运行依赖
want="$(grep -vE '^\s*(#|$)' "$here/relay/requirements.txt" | grep -v 'sys_platform == "win32"' | sort | tr '\n' ' ')numpy|Python ${BASE_VER}"

if [ ! -x "$venv/bin/python" ] || [ "$(cat "$venv/.want" 2>/dev/null)" != "$want" ]; then
  command -v uv >/dev/null || { echo "relay-python: 缺少 uv（brew install uv）" >&2; exit 3; }
  lock="$venv.lock"
  # 多 worktree 同时跑 lint 时用目录锁串行重建虚拟环境
  while ! mkdir "$lock" 2>/dev/null; do sleep 1; done
  trap 'rmdir "$lock" 2>/dev/null || true' EXIT
  if [ ! -x "$venv/bin/python" ] || [ "$(cat "$venv/.want" 2>/dev/null)" != "$want" ]; then
    uv venv -q --clear --python "$RELAY_BASE_PY" "$venv" >&2
    grep -vE '^\s*(#|$)' "$here/relay/requirements.txt" | grep -v 'sys_platform == "win32"' \
      | uv pip install -q --python "$venv/bin/python" -r /dev/stdin numpy >&2
    printf '%s' "$want" > "$venv/.want"
  fi
fi

# 二次核验：确保虚拟环境实际运行版本 == 本机最新版（防悬空旧软链）
VENV_VER="$("$venv/bin/python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}")')"
if [ "$VENV_VER" != "$BASE_VER" ]; then
  echo "relay-python: 虚拟环境版本（${VENV_VER}）与本机最新版（${BASE_VER}）不一致，拒绝使用" >&2
  exit 4
fi
echo "$venv/bin/python"
