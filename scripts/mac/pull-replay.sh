#!/usr/bin/env bash
# 把游戏机上某一天的 AUTO-MAS 运行记录拉回来当回放样本（根治第 2 项）。
#
#   scripts/mac/pull-replay.sh 2026-09-07          # 整天
#   scripts/mac/pull-replay.sh 2026-09-07 wuwa     # 只要一个账号目录
#
# 做三件事：scp 那天的 history/<日期>/ → 脱敏（redact.py）→ 用当前解析器生成
# expected.json 草稿。**草稿必须人看过**：它记的是「现在怎么判」，不是「该怎么判」。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DAY="${1:?用法: pull-replay.sh <YYYY-MM-DD> [账号目录]}"
ONLY="${2:-}"
HOST="${ARK_HOST:-100.65.39.119}"
DEST="$HERE/../../relay/tests/replay/$DAY"
mkdir -p "$DEST"
if [ -n "$ONLY" ]; then
  scp -q -r "Administrator@${HOST}:D:/ark/automas/history/${DAY}/${ONLY}" "$DEST/"
else
  scp -q -r "Administrator@${HOST}:D:/ark/automas/history/${DAY}/*" "$DEST/"
fi
# 脱敏：日志里可能有账号名以外的东西（密钥、路径里的用户名）
for f in "$DEST"/*/*.log "$DEST"/*/*.json; do
  [ -f "$f" ] || continue
  python3 "$HERE/redact.py" < "$f" > "$f.tmp" && mv "$f.tmp" "$f"
done
# 生成 expected.json 草稿
python3 - "$DEST" <<'PY'
import json, sys
from pathlib import Path
day = Path(sys.argv[1]); root = day.parent
sys.path.insert(0, str(root.parents[1]))
from ark_relay import collector
sys.path.insert(0, str(root.parent))
from test_replay import snapshot
for user_dir in sorted(p for p in day.iterdir() if p.is_dir()):
    exp = {}
    for js in sorted(user_dir.glob("*.json")):
        if js.name == "expected.json": continue
        rec = collector.parse_record(js, root)   # history 根目录 = replay/，路径里才带日期
        exp[js.stem] = snapshot(rec) if rec else None
    (user_dir / "expected.json").write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {user_dir.name}: {len(exp)} 条 → expected.json（草稿，要人看）")
PY
echo "✅ 样本在 $DEST；看过 expected.json 再 git add"
