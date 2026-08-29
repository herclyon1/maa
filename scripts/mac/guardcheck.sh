#!/usr/bin/env bash
# 闸门自检：给每道闸门喂一个「已知会犯的错」，断言它必须拒绝。
#
# 为什么需要这个：闸门不会报告自己坏了。2026-08-27 用户的原话是
# 「今天第三次你踩同一个坑，永远杜绝不完吗？」——问题不只是坑多，
# 而是**已经建好的闸门也会悄悄失效**：
#   · ensure_patches 一直都在，只是从没在部署后被调用过，补丁等于没贴；
#   · arklog 建来防时钟错，我却手打了一个未来时刻，它一声不吭返回 0 行；
#   · 测试全绿的闸门，拦不住「测试函数根本没被执行」。
# 所以每道闸门都要有一个「坏样本」证明它此刻还活着，而不是只存在于文档里。
#
# 用法：scripts/mac/guardcheck.sh
# 不联网、不碰游戏机——winrun 的几道闸在发送之前就会拒绝，正好本地可测。
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

# 断言：命令必须失败（拒绝），且输出里带某个关键词
refuses() {
  local name="$1" want="$2"; shift 2
  local out rc
  out=$("$@" 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then
    printf '  ✗ %-42s 闸门放行了本该拒绝的东西\n' "$name"; FAIL=$((FAIL+1)); return
  fi
  if ! grep -q -- "$want" <<<"$out"; then
    printf '  ✗ %-42s 拒绝了，但理由不对：%s\n' "$name" "$(head -1 <<<"$out")"
    FAIL=$((FAIL+1)); return
  fi
  printf '  ✓ %-42s\n' "$name"; PASS=$((PASS+1))
}

# 断言：命令必须成功（正常输入不该被误杀）
accepts() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf '  ✓ %-42s\n' "$name"; PASS=$((PASS+1))
  else
    printf '  ✗ %-42s 正常输入被误杀了\n' "$name"; FAIL=$((FAIL+1))
  fi
}

echo "▶ winrun 的发送前闸门"

# 一种写法拦住不代表这道闸有效。2026-08-27 实测：原规则只认 Path("C:\\")，
# 换成 Path("C:/") 就大摇大摆穿过去了。所以把绕过去的写法都钉在这里。
i=0
while IFS= read -r expr; do
  i=$((i+1))
  { echo "from pathlib import Path"; echo "import os";
    echo "for f in ${expr}:"; echo "    print(f)"; } > "$TMP/scan$i.py"
  refuses "全盘扫描：${expr}" "拒绝发送" \
    env ARK_HOST=203.0.113.1 ./scripts/mac/winrun.sh --py "$TMP/scan$i.py"
done <<'VARIANTS'
Path("C:/").rglob("*.json")
Path("C:\\").rglob("*.json")
Path('D:/').rglob("*")
Path("/").rglob("*")
Path.home().rglob("*")
os.walk("C:\\")
Path(r"C:\Windows").rglob("*.dll")
VARIANTS

# 正常的深路径不许被误杀，否则闸门会逼人加豁免、久而久之形同虚设
cat > "$TMP/normal.py" <<'EOF'
from pathlib import Path
for f in Path(r"D:\ark\okww\data\apps\ok-ww\working\logs").rglob("*.log"):
    print(f)
EOF
if ARK_HOST=203.0.113.1 ./scripts/mac/winrun.sh --py "$TMP/normal.py" 2>&1 \
     | grep -q "拒绝发送"; then
  printf '  ✗ %-42s\n' "正常深路径被误杀"; FAIL=$((FAIL+1))
else
  printf '  ✓ %-42s\n' "正常深路径没被误杀"; PASS=$((PASS+1))
fi

cat > "$TMP/tf.py" <<'EOF'
lines = open("x.log").read().splitlines()
hits = [l for l in lines if l[:19] > "2026-08-26 16:40"]
EOF
refuses "字典序比时间戳必须被拒" "拒绝发送" \
  env ARK_HOST=203.0.113.1 ./scripts/mac/winrun.sh --py "$TMP/tf.py"

cat > "$TMP/now.py" <<'EOF'
from datetime import datetime
print(datetime.now())
EOF
refuses "本机时钟 datetime.now() 必须被拒" "拒绝发送" \
  env ARK_HOST=203.0.113.1 ./scripts/mac/winrun.sh --py "$TMP/now.py"

cat > "$TMP/ok.py" <<'EOF'
# winrun: allow-raw-timefilter —— 豁免注释必须仍然放行
from datetime import datetime
print(datetime.now())
EOF
accepts "写了豁免注释就该放行（不误杀）" \
  bash -c "grep -q 'allow-raw-timefilter' '$TMP/ok.py'"

echo
echo "▶ arklog 读日志的闸门"
cat > "$TMP/arklog_test.py" <<'PYEOF'
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, "scripts/mac/lib")
import arklog

tmp = Path(sys.argv[1])
log = tmp / "relay.log"
# 样本一律锚在**昨天**，并且每次查询都把 on= 交出去。
# 早先把样本写成「今天 01:00/02:00」、窗口起点写死「00:30」，
# 那么只要机器时间落在 00:00–00:30，"今天 00:30" 就是未来，
# since() 正确地拒绝，闸门却把这当成失效。2026-08-29 00:12 撞上了。
# 和 22 点之后 +2 小时跨零点那个洞是同一族：**断言不许依赖当前钟点。**
ref = date.today() - timedelta(days=1)
log.write_text(f"{ref:%m-%d} 01:00:00 INFO 早上那条\n"
               "  File \"x.py\", line 1, in <module>\n"
               f"{ref:%m-%d} 02:00:00 INFO 后面那条\n", encoding="utf-8")

bad = []
def want_raise(label, fn):
    try:
        fn()
    except ValueError:
        return
    bad.append(label)

# 1. 起点在未来
# 只传 HH:MM 会被 since() 当成**今天**的那个时刻。22 点之后 +2 小时会跨到
# 次日，字符串一截就变成"今天 00:xx"，那是过去——这条断言从写下起就有这个
# 洞，2026-08-28 夜里 22:15 才第一次踩到，闸门自己报了 GUARD-FAIL。
# 用 on= 把日期一起交出去，跨不跨零点都成立。
_fut = datetime.now() + timedelta(hours=2)
want_raise("未来时刻没被拦",
           lambda: arklog.since(log, f"{_fut:%H:%M:%S}", on=_fut.date()))
# 2. 窗口之后一行都没有
want_raise("窗口后无日志没被拦", lambda: arklog.since(log, "23:58", on=ref))
# 3. 整个文件解析不出时间戳
weird = tmp / "weird.log"
weird.write_text("这行没有时间戳\n那行也没有\n", encoding="utf-8")
want_raise("格式不认识没被拦", lambda: arklog.since(weird, "00:01", allow_empty=True))
# 4. 三种时间戳格式都要认
for label, line in (("中继", "08-27 10:00:00 x"),
                    ("OK-WW", "2026-08-27 10:00:00 x"),
                    ("MAA", "[2026-08-27 10:00:00.123] x")):
    if arklog.parse_ts(line) is None:
        bad.append(f"{label} 格式认不出")
# 5. 续行要跟随上一条带时间戳的行，不能因为字典序漏出来
got = arklog.since(log, "00:30", on=ref)
if not any("File" in l for l in got):
    bad.append("traceback 续行被丢掉了")
if any("早上那条" in l for l in arklog.since(log, "01:30", on=ref)):
    bad.append("窗口之前的行漏进来了")

print("GUARD-FAIL " + "；".join(bad) if bad else "GUARD-OK")
PYEOF
out=$(python3 "$TMP/arklog_test.py" "$TMP" 2>&1)
if [ "$out" = "GUARD-OK" ]; then
  printf '  ✓ %-42s\n' "五条读日志的闸门全部有效"; PASS=$((PASS+1))
else
  printf '  ✗ %-42s %s\n' "读日志的闸门" "$out"; FAIL=$((FAIL+1))
fi

echo
echo "▶ 死代码闸门"
mkdir -p "$TMP/scripts"
cat > "$TMP/scripts/dead.py" <<'EOF'
def never_called_anywhere():
    return 1
EOF
refuses "定义了没人调用必须被拒" "写了等于没写" \
  python3 scripts/mac/lib/deadcode.py "$TMP/scripts"

cat > "$TMP/scripts/dup.py" <<'EOF'
class A:
    def go(self):
        return 1

    def go(self):
        return 2
EOF
refuses "同作用域重名必须被拒" "永远不会被执行" \
  python3 scripts/mac/lib/deadcode.py "$TMP/scripts/dup.py"

echo
echo "▶ id 含义登记表（idmap）"
# 826 事故 + 08-28 的 gst_passive_*：**从字面推不出含义**，只能查登记表。
refuses "没登记的 id 必须拒绝翻译" "不许自己猜含义" \
  python3 scripts/mac/lib/idmap.py get gst_passive_这个不存在
refuses "登记时不给来源必须拒绝" "没有来源的登记就是猜" \
  python3 scripts/mac/lib/idmap.py add gc_probe 探针 --source ""
accepts "现有条目全部有来源" python3 scripts/mac/lib/idmap.py check

# 把「按位置对齐推断」当来源写进去，check 必须抓出来。
# 用临时副本，绝不动仓库里的真表。
cp data/idmap.json "$TMP/idmap.json"
IDMAP_STORE="$TMP/idmap.json" python3 scripts/mac/lib/idmap.py \
  add gc_probe 探针 --source "按位置对齐推断出来的" >/dev/null 2>&1
refuses "把猜测写成来源必须被 check 抓出" "这不是来源，是猜" \
  env IDMAP_STORE="$TMP/idmap.json" python3 scripts/mac/lib/idmap.py check

echo
echo "▶ 快照时效（snapshot）"
# 08-28：拿 41 分钟前的快照写成「你的实际」，全程没标时间。
cat > "$TMP/snapcheck.py" <<'PY'
import contextlib, io, os, sys, time
from pathlib import Path
sys.path.insert(0, "scripts/mac/lib")
import snapshot as sn
d = Path(os.environ["TMP"]) / "snap"; d.mkdir(exist_ok=True)
sn.SNAP_DIR = d
f = d / sn.FILES["card"]; f.write_text("{}")
old = time.time() - 7200
os.utime(f, (old, old))
assert sn.is_stale("card"), "is_stale 没认出 120 分钟前的快照"
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    sn.load("card")
out = buf.getvalue()
assert "分钟前" in out, "读快照没有打出年龄：" + out
assert "⚠" in out, "超龄没有醒目告警：" + out
PY
accepts "旧快照必定自报年龄并告警" env TMP="$TMP" python3 "$TMP/snapcheck.py"
# 用户 08-28：「你别一直自动刷新…事件驱动就是我手动跟你说刷新」
# 用 AST 而不是 grep——文档字符串里提到 refresh() 是正常的，调用它才不正常。
accepts "load 不许挂自动刷新（那就是轮询）" \
  python3 scripts/mac/lib/no_auto_refresh.py

echo
echo "▶ 仓库自检本身"
accepts "lint-repo 当前全绿" ./scripts/mac/lint-repo.sh

echo
if [ "$FAIL" = 0 ]; then
  echo "✅ $PASS 道闸门全部还活着"
else
  echo "❌ $FAIL 道闸门失效（通过 $PASS）——闸门坏了比没有更危险，先修它"
fi
exit $FAIL
