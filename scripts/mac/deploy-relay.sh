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

REDEPLOY=0
for a in "$@"; do
  case "$a" in
    --redeploy) REDEPLOY=1 ;;
    *) echo "不认识的参数: $a" >&2; exit 2 ;;
  esac
done

HOST="${ARK_HOST:?请先 export ARK_HOST=<游戏机 Tailscale IP>}"
USER_AT="Administrator@${HOST}"
# 跨境到乌鲁木齐，每次 ssh/scp 都要重新握手一次；这个脚本要跑四十多次，
# 光握手就占掉大半时间。开连接复用：第一次连上之后所有后续调用走同一条
# 通道，ControlPersist 让通道在脚本结束后再留一会儿，紧接着的 winrun 也蹭得上。
CM_PATH="${TMPDIR:-/tmp}/ark-cm-$$"
SSH_OPTS=(-o ConnectTimeout=15 -o ControlMaster=auto
          -o "ControlPath=${CM_PATH}" -o ControlPersist=180)
cleanup_cm() { ssh -O exit -o "ControlPath=${CM_PATH}" "$USER_AT" 2>/dev/null || true; }
trap cleanup_cm EXIT
REMOTE_DIR='C:/ProgramData/ark-relay'
PY='D:\ark\automas\environment\python\python.exe'
# 两个绝对路径都要在任何 cd 之前算好。2026-08-26 我在 cd 之后才去解析
# "$(dirname "${BASH_SOURCE[0]}")"，相对路径当场失效，取日志那步静静失败了。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../relay" && pwd)"

cd "$HERE"

# 分段计时。2026-08-31 用户说部署慢到承受不起，而当时谁也说不出慢在哪一段——
# 我第一次量到的 90 秒其实是在「更新说明为空」那道闸上中止的，压根没走到网络。
# 与其每次靠猜，不如每段都把秒数打出来。
_T0=$SECONDS; _TP=$SECONDS
lap() { printf '      （%d 秒）\n' "$((SECONDS-_TP))"; _TP=$SECONDS; }

# 为什么这道闸在最前面：2026-08-24 我在 test_preupdate_session.py 红着的时候
# 部署了一次，红灯是真的（run() 拆分后断言失效），只是我先按了部署。语法自检
# 拦不住这种——代码能编译，只是行为不对。测试全绿才准上机，没有例外。
# 测试能不能拦住，前提是它真的被执行。2026-08-27 连续三次把新写的测试函数
# 放在 `if __name__` 之后——从没运行过，却一路绿灯上了机器。
# 闸门自己会坏，而且坏了不吭声。每次部署前拿已知的坏样本验一遍：
# 拦不住的闸门比没有闸门更危险——它会让人以为这一类错已经不可能发生。
echo "▶ 0b/5 闸门自检（拿坏样本验每道闸还拦不拦得住）"
if ! out=$("$HERE/../scripts/mac/guardcheck.sh" 2>&1); then
  sed 's/^/    /' <<<"$out"
  echo "  ✋ 部署已取消：闸门失效了，先修闸门。"
  exit 1
fi
echo "  $(tail -1 <<<"$out")"

lap
echo "▶ 0a/5 没有永远不会被执行的代码"
if ! out=$(python3 "$HERE/../scripts/mac/lib/deadcode.py" \
        "$HERE" "$HERE/../scripts" 2>&1); then
  sed 's/^/    /' <<<"$out"
  echo "  ✋ 部署已取消：上面这些代码写了等于没写。"
  exit 1
fi
echo "  $(tail -1 <<<"$out")"

lap
echo "▶ 0/5 回归测试（不全绿就不部署）"
# 并行跑。四十个测试各自起一个 python，串行要十几秒，而这十几秒
# 每次部署都要付两遍（lint-repo 那道闸里还会再跑一遍）。
# 判据一个没松：照样要退出码为 0，且最后一行必须写着 passed。
run_one_test() {
  local f="$1" out
  if ! out=$(python3 "$f" 2>&1) || ! grep -qiE "passed|^PASS" <<<"$(tail -1 <<<"$out")"; then
    printf '  ✗ %s\n' "$(basename "$f")"
    tail -3 <<<"$out" | sed 's/^/      /'
    return 1
  fi
}
export -f run_one_test
if ! printf '%s\n' tests/test_*.py \
     | xargs -P 8 -I{} bash -c 'run_one_test "$1"' _ {}; then
  echo "  ✋ 有测试没过（见上）。"
  echo "     部署已取消。先修测试，或者确认这些断言本身该更新。"
  exit 1
fi
echo "  $(ls tests/test_*.py | wc -l | tr -d ' ') 个测试全过"

# ── 0.5 闸：更新说明必须是新的 ──────────────────────────────
# 2026-08-26 用户当场指出：「你的更新内容不能一直都是一样的，我看你更新了
# 两次，第二次还在用旧的内容」。说明是静态文件，不换内容就会一直播报同一份，
# 而**陈旧的说明比没有说明更糟**——它看起来像是新的。
#
# 所以：这次的说明和上次部署的一字不差就拒绝部署。
# 真要重推同一份改动（比如部署链路本身出问题在反复试），加 --redeploy。
NOTES="$HERE/RELEASE-NOTES.md"
NOTES_STAMP="$HERE/state/last-deployed-notes.sha1"
mkdir -p "$HERE/state"
if [ ! -s "$NOTES" ]; then
  echo "  ✋ relay/RELEASE-NOTES.md 是空的（上次部署后自动清空的，不是丢了）。" >&2
  echo "     用人话写清楚**这次**改了什么——只写新增的，不要重复上次播报过的。" >&2
  echo "     写完再部署。这段文字就是用户会收到的那条通知。" >&2
  exit 7
fi
NOTES_SHA=$(shasum -a 1 "$NOTES" | awk '{print $1}')
LAST_SHA=$(cat "$NOTES_STAMP" 2>/dev/null || echo "")
if [ "$NOTES_SHA" = "$LAST_SHA" ] && [ "$REDEPLOY" != "1" ]; then
  echo "  ✋ RELEASE-NOTES.md 和上次部署的一字不差。" >&2
  echo "     这次改了什么？写进 relay/RELEASE-NOTES.md，用人话。" >&2
  echo "     确实是重推同一份改动的话：$0 --redeploy" >&2
  exit 8
fi

lap
echo "▶ 1/5 重建 manifest"
python3 make-manifest.py

lap
echo "▶ 2/5 语法自检"
python3 -m py_compile ark_relay/*.py service.py run.py

FILES=$(python3 -c "import json;print(' '.join(json.load(open('manifest.json'))['files']))")

lap
# 远端算哈希：用 AUTO-MAS 自带的 python，避免 certutil 的 GBK 输出问题。
cat > /tmp/ark-verify.py <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(r"C:\ProgramData\ark-relay")
want = json.loads((root / "_manifest_check.json").read_text(encoding="utf-8"))["files"]
listing = "--list" in sys.argv
bad = []
for rel, sha in want.items():
    p = root / rel
    got = hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else "MISSING"
    if got != sha:
        bad.append(rel if listing else f"{rel}: {got[:8]} != {sha[:8]}")
if listing:
    # 只报差异，退出码恒 0——这一趟是用来决定推哪些文件的，不是判决。
    print("\n".join(bad))
    sys.exit(0)
print("MISMATCH " + "; ".join(bad) if bad else f"HASH-OK {len(want)}")
sys.exit(1 if bad else 0)
PY

echo "▶ 3/5 推送 $(wc -w <<<"$FILES") 个文件"
# 清单里现在有嵌套路径（ark_relay/okww_files/*.py）。scp 不会自己建目录，
# 目录不在的话那几个文件会静静推不过去，而哈希核对那步才会发现。先建好。
MKDIRS=""
for d in $(printf '%s\n' $FILES | xargs -n1 dirname | sort -u | grep -v '^\.$'); do
  win="${REMOTE_DIR//\//\\}\\${d//\//\\}"
  MKDIRS="${MKDIRS}${MKDIRS:+ & }if not exist \"$win\" mkdir \"$win\""
done
# 一次调用建完所有目录——原来是一个目录一次 ssh，跨境往返白白多花好几秒。
[ -n "$MKDIRS" ] && ssh "${SSH_OPTS[@]}" "$USER_AT" "$MKDIRS" >/dev/null 2>&1 || true
# 只推真正变了的。整份推一遍要一分多钟，而绝大多数部署只动一两个文件。
# 先把清单和校验脚本送上去，问机器哪些对不上，再按名单推。
# 安全性没有变化：推完之后那道严格校验（下一段）一个文件都不放过。
scp -q "${SSH_OPTS[@]}" manifest.json "${USER_AT}:${REMOTE_DIR}/_manifest_check.json"
scp -q "${SSH_OPTS[@]}" /tmp/ark-verify.py "${USER_AT}:C:/Users/Administrator/ark-verify.py"
CHANGED=$(ssh "${SSH_OPTS[@]}" "$USER_AT" \
  "\"$PY\" -X utf8 C:\\Users\\Administrator\\ark-verify.py --list" 2>/dev/null | tr -d '\r')
if [ -z "$CHANGED" ]; then
  echo "    机器上的文件和本地一致，无需推送"
else
  echo "    需要推送 $(printf '%s\n' "$CHANGED" | grep -c .) 个（共 $(wc -w <<<"$FILES") 个）"
  for f in $CHANGED; do
    scp -q "${SSH_OPTS[@]}" "$f" "${USER_AT}:${REMOTE_DIR}/${f}"
  done
fi

lap
echo "▶ 4/5 逐文件核对哈希"
scp -q "${SSH_OPTS[@]}" manifest.json "${USER_AT}:${REMOTE_DIR}/_manifest_check.json"
scp -q "${SSH_OPTS[@]}" /tmp/ark-verify.py "${USER_AT}:C:/Users/Administrator/ark-verify.py"
ssh "${SSH_OPTS[@]}" "$USER_AT" "\"$PY\" -X utf8 C:\\Users\\Administrator\\ark-verify.py"
ssh "${SSH_OPTS[@]}" "$USER_AT" \
  "del C:\\Users\\Administrator\\ark-verify.py & del ${REMOTE_DIR//\//\\}\\_manifest_check.json" >/dev/null 2>&1 || true

lap
echo "▶ 4.5/5 写入代码版本号（否则自更新会拿旧清单把这次部署顶回去）"
# 手动部署之后必须把本地 manifest 的版本号刻到机器上。不写的话，机器的
# code-version 还停在上一次自更新的值，下次启动时某扇缓存落后的门给一份
# 更旧（甚至没有版本号）的 manifest，自更新就会认为"机器落后了"，把刚
# 部署好的文件覆盖回旧版——2026-08-21 就这么被静默降级过一次。
VER=$(python3 -c "import json;print(json.load(open('manifest.json'))['version'])")
ssh "${SSH_OPTS[@]}" "$USER_AT" \
  "if exist \"C:\\Program Files\\PowerShell\\7\\pwsh.exe\" (\"C:\\Program Files\\PowerShell\\7\\pwsh.exe\" -NoProfile -Command \"Set-Content -Path 'C:/ProgramData/ark-relay/state/code-version.txt' -Value '$VER' -NoNewline\") else (powershell -NoProfile -Command \"Set-Content -Path 'C:/ProgramData/ark-relay/state/code-version.txt' -Value '$VER' -NoNewline\")" >/dev/null
echo "    code-version = $VER"

lap
echo "▶ 5/5 重启服务并确认真的起来了"
# 2026-08-26：这一段原本是
#   ... & net stop ... & net start ... & echo RESTARTED
# 三个问题叠在一起：
#   1. `echo RESTARTED` 是**无条件**的，start 失败也照样打印；
#   2. 所谓「确认」只是 tail 了几行日志，**从没查过服务状态**；
#   3. 最后无脑打印「✅ 部署完成并已核对」。
# 结果那天一次部署把服务停了没起回来，脚本全程绿灯，
# 直到我手动 `sc query` 才发现 STATE=STOPPED——**通知链路断了一小时没人知道**。
# 现在：先等它真的停，再启，再轮询到 RUNNING 为止，起不来就非零退出。

# __pycache__ 里的旧 .pyc 会盖住新代码，必须清。
ssh "${SSH_OPTS[@]}" "$USER_AT" \
  'del /q C:\ProgramData\ark-relay\ark_relay\__pycache__\*.pyc >nul 2>&1 & sc stop ark-relay >nul 2>&1 & echo STOPPING' \
  >/dev/null 2>&1 || true

svc_state() {
  ssh "${SSH_OPTS[@]}" "$USER_AT" 'sc query ark-relay' 2>/dev/null \
    | tr -d '\r' | awk '/STATE/{print $4}'
}

for _ in $(seq 1 15); do
  [ "$(svc_state)" = "STOPPED" ] && break
  sleep 2
done
echo "    停止确认：$(svc_state)"

ssh "${SSH_OPTS[@]}" "$USER_AT" 'sc start ark-relay' >/dev/null 2>&1 || true
STATE=""
for _ in $(seq 1 20); do
  STATE=$(svc_state)
  [ "$STATE" = "RUNNING" ] && break
  sleep 2
done

if [ "$STATE" != "RUNNING" ]; then
  echo "  ✋ ark-relay 没能启动（当前状态 ${STATE:-未知}）。" >&2
  echo "     代码已经推上去了，但服务是停的——通知链路是断的，必须立刻处理：" >&2
  echo "     ssh $USER_AT 'sc start ark-relay'" >&2
  exit 6
fi
echo "    启动确认：RUNNING"

sleep 10
# 日志尾巴走 winrun.sh，不要自己 ssh 打印。
#
# 换过一轮 pwsh 还是乱码——问题根本不在哪个 PowerShell，而在**中文穿过
# 936 的控制台**这一层：不管谁写的 UTF-8，经过 cmd 管道就已经碎了。
# winrun.sh 从一开始就是为这件事写的：远端写 UTF-8 文件，整体拷回来再解码，
# 中文一个字节都不上命令行。同目录的现成工具，不要重复造。
"$SCRIPT_DIR/winrun.sh" --get 'C:\ProgramData\ark-relay\relay.log' \
  2>/dev/null | tail -6 | sed 's/^/    /' \
  || echo "    （取日志失败，不影响部署结果——服务状态上面已确认）"

printf '%s' "$NOTES_SHA" > "$NOTES_STAMP"

# 说明已经推上去也播报过了，**本地清零**。
# 用户 2026-08-26：「每次更新中继的时候把通知更新内容清零并且要求填写更新内容」。
# 清零之后，上面那道「文件为空就拒绝部署」的闸自然会逼下一次写新的——
# 比对哈希更彻底：哈希闸只防「一字不差」，清零连「改一个字蒙混」都防住了，
# 因为你面对的是一张白纸，只能从头写这次干了什么。
: > "$NOTES"
echo "✅ 部署完成：文件哈希已核对，服务已确认 RUNNING"
lap
printf "⏱  全程 %d 秒\n" "$((SECONDS-_T0))"
echo "   （relay/RELEASE-NOTES.md 已清空——下次部署前必须写清楚这次改了什么）"

# 把这次部署的 manifest 推上 GitHub。**不推的话自更新永远用不成**：
# 部署会把 manifest.json 的 version 改成这一刻的时间戳，但那是本地改动；
# GitHub 上还是旧版本号，自更新一比「清单比本机旧」就拒绝更新——
# 它是对的，只是永远等不到新清单。2026-08-30 查了半天 CDN 缓存，
# 真因在这里：不是缓存没刷新，是根本没推上去。
if git -C "$HERE/.." diff --quiet -- relay/manifest.json; then
  echo "▶ manifest 没变化，不用推"
else
  git -C "$HERE/.." add relay/manifest.json relay/state/last-deployed-notes.sha1 2>/dev/null || true
  if git -C "$HERE/.." commit -q -m "deploy: manifest $(date -u +%Y%m%d%H%M%S)" 2>/dev/null; then
    if git -C "$HERE/.." push -q origin HEAD 2>/dev/null; then
      echo "▶ manifest 已推上 GitHub，自更新下次开机就能看到"
    else
      echo "✋ manifest 提交了但推送失败——自更新会一直看到旧清单，记得手动 push" >&2
    fi
  fi
fi
