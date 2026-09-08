#!/usr/bin/env bash
# 给机器下一条命令行指令（走仓库里的 queue/config.json 信箱），一条命令走完全程。
#
#   scripts/mac/order.sh '{"action":"debug_mode","minutes":90}'
#   scripts/mac/order.sh --clear                 # 清空信箱（做完就该清）
#   scripts/mac/order.sh --show                  # 看信箱现在是什么
#
# 为什么要有它（2026-09-08 审出来的两个坑，都不出声）：
#
#  1. **忘了清 CDN**。中继取这个文件走 jsDelivr，缓存不清就一直发旧的那份，
#     指令根本到不了机器，而屏幕上、GitHub 上看着都是对的。
#     purge-cdn.py 早就写好了，只是"记得跑"从来不是个可靠的机制。
#  2. **忘了删上一条**。中继按"版本号严格变大"**整批重放** commands，
#     上一条留在里面，下次为了改别的抬版本号时它会跟着再执行一遍。
#     2026-09-08 之前那里就躺着 08-23 的 debug_mode，谁改一次配置机器就白开一夜。
#
# 所以这个脚本：校验 action 在白名单里 → 覆盖式写入（不追加）→ 抬版本号 →
# 提交推送 → 清 CDN 并**等到各扇门真的发出新版本**才算完。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$HERE/../.."
BOX="$REPO/queue/config.json"

usage() { sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 1 ] || usage

case "${1:-}" in
  --show) python3 -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1])),ensure_ascii=False,indent=2))" "$BOX"; exit 0 ;;
  --clear) BODY='[]' ;;
  -h|--help) usage ;;
  *) BODY="$1" ;;
esac

python3 - "$BOX" "$BODY" <<'PY'
import json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
box, body = sys.argv[1], sys.argv[2]

# Read the relay's own whitelist rather than keeping a second copy. The copy that
# used to live here drifted the moment a command was added: on 2026-09-09 the new
# echo_farm was refused by this script while the machine accepted it perfectly well.
# `python3 -` has no __file__, so the repo root comes from the inbox path itself
# ($REPO/queue/config.json).
sys.path.insert(0, str(Path(box).resolve().parents[1] / "relay"))
from ark_relay.commands import ALLOWED  # noqa: E402

cmds = json.loads(body)
if isinstance(cmds, dict):
    cmds = [cmds]
for c in cmds:
    a = c.get("action")
    if a not in ALLOWED:
        sys.exit(f"✋ action「{a}」不在白名单里。可用：{'、'.join(sorted(ALLOWED))}")

cur = json.loads(open(box, encoding="utf-8").read())
# 版本号按服务器时间的 YYYYMMDDnn，比当前大就行
today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
n = int(cur.get("version", 0))
ver = max(int(today + "01"), n + 1)

# What the push says. Action ids are for the program; the user reads Chinese.
ZH = {"set_master": "改脚本自己的设置", "set_config": "改设置", "debug_mode": "调试模式",
      "skip_shutdown": "下次跑完不关机", "run_now": "现在跑一趟", "skip_today": "跳过一趟",
      "weekly_boss": "改打第几个周本", "estop": "停止一切", "maaend_option": "改终末地选项",
      "echo_farm": "开始刷 4C 声骸", "echo_farm_stop": "刷声骸收工"}
label = "空（安全状态）" if not cmds else "、".join(ZH.get(c["action"], c["action"]) for c in cmds)
out = {
    "version": ver,
    "name": label,
    # The note is the body of the push the user gets. It used to carry over the
    # previous file's note, which since 09-08 was a paragraph of guidance written
    # for me - and he received it as a notification. One plain sentence instead.
    "note": f"从电脑发来的指令：{label}",
    "commands": cmds,           # 覆盖，不追加——旧指令绝不留下
}
open(box, "w", encoding="utf-8").write(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(f"▶ 信箱已写：v{ver}，{len(cmds)} 条指令")
PY

git -C "$REPO" add queue/config.json
if git -C "$REPO" diff --cached --quiet -- queue/config.json; then
  echo "▶ 信箱内容没变，不用推"
  exit 0
fi
git -C "$REPO" commit -q -m "信箱：$(python3 -c "import json;print(json.load(open('$BOX'))['name'])")"
git -C "$REPO" push -q origin HEAD
echo "▶ 已推上 GitHub"

# 清缓存并等到各扇门真的发新版本——不等就等于没推。
python3 "$HERE/purge-cdn.py"
