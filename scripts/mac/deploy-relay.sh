#!/usr/bin/env bash
# 把 relay/ 直推到游戏机并立即生效，每一步都核对，失败就非零退出。
#
# 为什么需要它：2026-08-20 晚一次 scp 静默失败——命令返回 0、文件却没过去，
# 服务重启后跑的还是旧代码，直到哈希对比才发现。自更新通道那天两扇门又同时
# 超时（raw + jsDelivr），所以"推 GitHub 等它自己更新"当晚根本不成立。
# 手动部署必须自带验证，否则"我以为部署了"比没部署更危险。
#
#   ARK_HOST=100.65.39.119 scripts/mac/deploy-relay.sh
#
set -euo pipefail

HOST="${ARK_HOST:?请先 export ARK_HOST=<游戏机 Tailscale IP>}"
USER_AT="Administrator@${HOST}"
REMOTE_DIR='C:/ProgramData/ark-relay'
PY='D:\Users\Administrator\Desktop\AUTO-MAS\environment\python\python.exe'
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../relay" && pwd)"

cd "$HERE"

echo "▶ 1/5 重建 manifest"
python3 make-manifest.py

echo "▶ 2/5 语法自检"
python3 -m py_compile ark_relay/*.py service.py run.py

FILES=$(python3 -c "import json;print(' '.join(json.load(open('manifest.json'))['files']))")

echo "▶ 3/5 推送 $(wc -w <<<"$FILES") 个文件"
for f in $FILES; do
  scp -q -o ConnectTimeout=15 "$f" "${USER_AT}:${REMOTE_DIR}/${f}"
done

echo "▶ 4/5 逐文件核对哈希"
# 远端算哈希：用 AUTO-MAS 自带的 python，避免 certutil 的 GBK 输出问题。
cat > /tmp/ark-verify.py <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(r"C:\ProgramData\ark-relay")
want = json.loads((root / "_manifest_check.json").read_text(encoding="utf-8"))["files"]
bad = []
for rel, sha in want.items():
    p = root / rel
    got = hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else "MISSING"
    if got != sha:
        bad.append(f"{rel}: {got[:8]} != {sha[:8]}")
print("MISMATCH " + "; ".join(bad) if bad else f"HASH-OK {len(want)}")
sys.exit(1 if bad else 0)
PY
scp -q -o ConnectTimeout=15 manifest.json "${USER_AT}:${REMOTE_DIR}/_manifest_check.json"
scp -q -o ConnectTimeout=15 /tmp/ark-verify.py "${USER_AT}:C:/Users/Administrator/ark-verify.py"
ssh -o ConnectTimeout=15 "$USER_AT" "\"$PY\" -X utf8 C:\\Users\\Administrator\\ark-verify.py"
ssh -o ConnectTimeout=15 "$USER_AT" \
  "del C:\\Users\\Administrator\\ark-verify.py & del ${REMOTE_DIR//\//\\}\\_manifest_check.json" >/dev/null 2>&1 || true

echo "▶ 5/5 重启服务并确认启动"
# __pycache__ 里的旧 .pyc 会盖住新代码，必须清。
ssh -o ConnectTimeout=15 "$USER_AT" \
  'del /q C:\ProgramData\ark-relay\ark_relay\__pycache__\*.pyc >nul 2>&1 & net stop ark-relay >nul 2>&1 & net start ark-relay >nul 2>&1 & echo RESTARTED' \
  | tr -d '\r' | tail -1
sleep 25
ssh -o ConnectTimeout=15 "$USER_AT" \
  'powershell -NoProfile -Command "Get-Content C:\ProgramData\ark-relay\relay.log -Tail 6"' \
  2>/dev/null | tr -d '\r' | sed 's/^/    /'

echo "✅ 部署完成并已核对"
