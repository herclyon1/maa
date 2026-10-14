#!/usr/bin/env bash
# 仓库自检 —— 每一条规则都对应一次真实犯过的错。
#
#   scripts/mac/lint-repo.sh
#
# 和 shellcheck 的分工：shellcheck 查通用 shell 缺陷，这里查**这个项目特有的
# 反模式**——那些语法完全合法、但在这台游戏机上必然出问题的写法。
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1   # 绝对路径，见规则 5
# 排除自己：规则文本里就带着要查的模式，不排除会自己匹配自己。
SELF="scripts/mac/lint-repo.sh"

FAIL=0
note() { printf '  ✗ %s\n' "$1"; FAIL=1; }
ok()   { printf '  ✅ %s\n' "$1"; }

echo "▶ 1/25 shellcheck"
if command -v shellcheck >/dev/null || [ -x "$HOME/.local/bin/shellcheck" ]; then
  SC="$(command -v shellcheck || echo "$HOME/.local/bin/shellcheck")"
  bad=""
  while IFS= read -r f; do
    [ -n "$("$SC" -S warning "$f" 2>&1)" ] && bad="$bad $f"
  done < <(find scripts -name '*.sh')
  [ -z "$bad" ] && ok "全部脚本无 warning" || note "有告警:$bad"
else
  note "shellcheck 没装（gh release download --repo koalaman/shellcheck）"
fi

# 2026-08-26：我在 winrun.sh 的清理逻辑里用了 `powershell`（5.1），每次都失败。
# 5.1 默认不是 UTF-8，读中文 JSON 必挂。规矩立完当轮就违反了，所以要机器来查。
echo "▶ 2/25 不许用 powershell 5.1（要用 pwsh 7）"
# grep -rn 的输出是 `文件:行号:内容`，所以过滤注释要跳过前两段，
# 不能直接 `^\s*#`——2026-08-26 第一版就是这么写的，注释全都漏了过去。
# 2026-09-06：原正则只认 `powershell ` 带空格，`["powershell", "-NoProfile"` 这种
# 列表写法漏过去了——preupdate 里就藏着一处。空格、引号、逗号都算结尾。
hits=$(grep -rn "['\"\` ]powershell[ '\",]" scripts/ relay/ 2>/dev/null \
       | grep -v "^$SELF:" \
       | grep -v "PowerShell\\\\7" \
       | grep -v "else (powershell" \
       | grep -v '\.ps1:' \
       | awk -F: '{ rest=$0; sub(/^[^:]*:[0-9]+:/,"",rest);
                    if (rest !~ /^[[:space:]]*#/) print }' || true)
[ -z "$hits" ] && ok "没有裸 powershell 调用" || { note "发现裸 powershell（应改 pwsh 或 base64）"; echo "$hits" | head -5 | sed 's/^/       /'; }

# 2026-08-26：`pwsh -c "... \"A|B\" ..."` 被 bash/ssh/cmd 三层引号吃掉，
# 报 `'Wuthering' 不是内部或外部命令`。正解是 base64 -EncodedCommand。
echo "▶ 3/25 ssh 送 PowerShell 必须走 base64"
hits=$(grep -rn 'ssh .*pwsh -\(NoProfile \)\?-\?[Cc]ommand' scripts/ 2>/dev/null \
       | grep -v EncodedCommand | grep -v "^\s*#" || true)
[ -z "$hits" ] && ok "没有内联拼接的远端 PowerShell" || { note "有内联 -Command（应改 -EncodedCommand）"; echo "$hits" | head -5 | sed 's/^/       /'; }

# 2026-08-26：deploy-relay.sh 在 `cd` 之后才解析 $(dirname "${BASH_SOURCE[0]}")，
# 相对路径当场失效，取日志那步静默失败。当天 cwd 类问题共撞 37 次。
echo "▶ 4/25 脚本目录必须在 cd 之前算好"
hits=""
while IFS= read -r f; do
  cdline=$(grep -n '^cd ' "$f" | head -1 | cut -d: -f1)
  [ -z "$cdline" ] && continue
  while IFS= read -r ln; do
    n=${ln%%:*}
    [ "$n" -gt "$cdline" ] && hits="$hits$f:$n "
  done < <(grep -n 'dirname "\${BASH_SOURCE' "$f" || true)
done < <(find scripts -name '*.sh' ! -path "*/lint-repo.sh")
[ -z "$hits" ] && ok "没有 cd 之后才解析脚本目录的写法" || note "在 cd 之后解析路径: $hits"

# 2026-08-26：RELEASE-NOTES.md 忘了加进清单，部署报成功而机器上根本没这个文件。
echo "▶ 5/25 部署清单要包含更新说明"
if grep -q 'RELEASE-NOTES.md' relay/make-manifest.py 2>/dev/null; then
  ok "make-manifest 会带上 RELEASE-NOTES.md"
else
  note "make-manifest.py 没有把 RELEASE-NOTES.md 放进清单"
fi

# 2026-08-26：新写的测试函数被 `>>` 追加到了 `main()` 之后，调用时还没定义。
# 测试跑一遍就会 NameError，所以这条直接用「全部测试能跑通」兜住。
if [ -n "${LINT_SKIP_TESTS:-}" ]; then
  echo "▶ 6/25 中继测试全绿"
  echo "  ⏭ 已跳过（调用方自己会跑一遍，这里再跑是重复）"
else
echo "▶ 6/25 中继测试全绿"
# Criteria: exit code 0 and the last line says passed.
# 失败时把**报错内容**打出来，不是只报一个文件名。原来只吐文件名，人还得自己
# 再跑一遍才知道错在哪；而收进变量再 tr '\n' ' ' 会把 traceback 压成一整行，
# 比不打还难读。所以让 runner 直接往 stdout 打，外层只判成败。
lint_one_test() {
  local name out
  name=$(basename "$1")
  if ! out=$(cd relay && "$RELAY_PY" "tests/$name" 2>&1); then
    printf '  ✗ %s 抛异常：\n%s\n' "$name" "$(sed 's/^/       /' <<<"$(tail -15 <<<"$out")")"
    return 1
  fi
  if ! grep -qiE "passed|^PASS" <<<"$(tail -1 <<<"$out")"; then
    printf '  ✗ %s 没过：\n%s\n' "$name" "$(sed 's/^/       /' <<<"$(grep -E "✗|FAIL" <<<"$out" | head -8)")"
    return 1
  fi
}
export -f lint_one_test
# The Python the machine runs (3.14), not macOS's /usr/bin/python3 3.9 (user 10-12 08:21:
# the newest Python is installed, yet the system one was used). relay-python.sh never falls back.
if ! RELAY_PY=$(scripts/mac/lib/relay-python.sh); then
  note "没有 3.14 跑中继测试（见上），不许退回系统自带的 3.9"
fi
export RELAY_PY
case "$("${RELAY_PY:-false}" -V 2>&1)" in
  "Python 3.14."*) ok "中继测试用的 Python：$("$RELAY_PY" -V 2>&1)（和游戏机同一版）" ;;
  *) note "中继测试用的不是 3.14：${RELAY_PY:-无}" ;;
esac
# Nothing that runs relay tests may call the bare python3 (= /usr/bin/python3 3.9).
if bare=$(grep -nE '(^|[^"$A-Za-z_])python3 +("?\$\{?TEST_DIR|"?\$1"? *>|"?tests/|-m +(py_compile +ark_relay|ark_relay))' scripts/mac/lint-repo.sh scripts/mac/deploy-relay.sh); then
  note "跑中继测试 / 中继代码的地方又用了系统自带的 python3："; sed 's/^/       /' <<<"$bare"
fi
cnt=$(find relay/tests -name 'test_*.py' | wc -l | tr -d ' ')
# One test at a time, not `xargs -P 8`: on this Mac's macOS 27.2 beta, background-priority
# processes that exec many children at once lock the kernel (09-23 04:19 panic symbolicated in
# the board write-up of the 09-23 04:19 panic: this very xargs line started the grep that locked; 10-14 19:52 the
# Mac froze again while this check ran). Slower, but the Mac stays up.
# shellcheck source=scripts/mac/lib/wait-not-background.sh
. scripts/mac/lib/wait-not-background.sh
lint_all_tests() {
  local f rc=0
  for f in relay/tests/test_*.py; do
    wait_not_background
    lint_one_test "$f" || rc=1
  done
  return "$rc"
}
if lint_all_tests; then
  ok "$cnt 个测试全过"
else
  note "有测试没过（见上）"
fi

fi

# 2026-08-27：同一类错的第三次——把测试函数写在 `if __name__` 之后，
# 它永远不会被调用，测试照样打印 "all checks passed"、闸门照样放行。
# 上面那条「测试全绿」拦不住：那个函数根本没被执行，谈不上红不红。
# 所以这里查的是「定义了却没人调用」这一整类，而不是某一次的写法。
echo "▶ 7/25 没有永远不会被执行的代码"
if out=$(python3 scripts/mac/lib/deadcode.py relay scripts 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "有孤立/被覆盖的函数"
  sed 's/^/    /' <<<"$out"
fi

echo "▶ 8/25 手机页文案不许有私人措辞"
# 规矩见 docs/PHONE-COPY-RULES.md。文档拦不住，闸门才拦得住：
# 2026-09-04 页面上写着「上游 beta.5 那阵它是坏的……中继在 09-04 开机时开了回来」，
# 用户的话是「太私人措辞了」。命中下面这些词就拒绝提交。
# 后半段是「把当前状态写进静态文案」——控件自己显示着选了什么，
# 文案再写一遍必然过期：2026-09-04 写着「路线 3 和 13 已取消勾选」，
# 用户把 16 条全勾上之后那句话当场变成假的。
bad_words='上游|中继|母本|账本|脚本|issue|PR |用户|我们|原话|实录|那阵|那次|先关着|已修好|等上游|beta\.|rc\.|v[0-9]+\.[0-9]+|20[0-9]{2}-[0-9]{2}-[0-9]{2}|已取消勾选|已勾选|已关掉|已开回|目前是|现在是|当前设置'
if hits=$(grep -nE '^\s*(hint|label):' web/schema.js web/view.js | grep -E "$bad_words"); then
  note "手机页文案有内部措辞或会过期的信息，按 docs/PHONE-COPY-RULES.md 重写"
  printf '%s\n' "$hits" | sed 's/^/    /' | head -10
else
  echo "  ✅ 没有私人措辞"
fi

# 2026-09-06：queues.apply / commands._run_now 里一个局部变量叫 names，把模块
# names 遮住了，函数第一行 names.canonical() 就 UnboundLocalError——从 09-02
# 起四天里每次调用必崩，61 个测试全绿，自写的 test_undefined_names 也没抓到
# （它只看名字有没有绑定过，不看先读后绑定）。pyflakes 的 F823 一行就报。
# 顺带用机器上那个版本的 Python（3.14）严格编译：`'\d'` 这类非法转义在 3.12+
# 是 SyntaxWarning、将来是 SyntaxError，本地 3.9 一声不吭。
echo "▶ 9/25 静态检查（pyflakes + 3.14 严格编译）"
PY314="$HOME/.local/bin/python3.14"
if ! command -v uvx >/dev/null; then
  note "uvx 没装（brew install uv），pyflakes 跑不了"
else
  # okww_files 是上游原样文件，不归我们管。
  # 2026-09-08 把 relay/tests 也纳进来：之前不查，于是 55 条报告在里面躺着，
  # 其中 test_preupdate_problems.py 那条 f-string 缺占位符指向一个真断言错误——
  # 它用 for + break 只查了四个函数里的第一个。
  # -q: on a cold cache uvx itself prints "Installed 1 package in 1ms" to stderr, which the
  # 2>&1 below turned into a pyflakes "hit" (M4 lint, 2026-09-23 08:20:57; reproduced with an
  # empty UV_CACHE_DIR). pyflakes' own reports and syntax errors still come through.
  hits=$(uvx -q pyflakes relay/ark_relay relay/tests relay/service.py relay/boot_stages.py relay/run.py relay/make-manifest.py scripts 2>&1 \
         | grep -v 'okww_files' || true)
  [ -z "$hits" ] && ok "pyflakes 零报告" || { note "pyflakes 有报告（未定义名 / 先读后绑定 / 无用导入）"; sed 's/^/       /' <<<"$hits" | head -12; }
fi
if [ -x "$PY314" ]; then
  if out=$("$PY314" -W error::SyntaxWarning -c "
import compileall, sys
ok = compileall.compile_dir('relay/ark_relay', quiet=1, force=True, legacy=False)
ok = compileall.compile_file('relay/service.py', quiet=1, force=True) and ok
ok = compileall.compile_file('relay/boot_stages.py', quiet=1, force=True) and ok
ok = compileall.compile_dir('scripts', quiet=1, force=True) and ok
sys.exit(0 if ok else 1)" 2>&1); then
    ok "3.14 严格编译通过（无非法转义）"
  else
    note "3.14 严格编译失败（机器上跑的就是 3.14）"; sed 's/^/       /' <<<"$out" | tail -6
  fi
else
  note "找不到 $PY314，没法按机器的 Python 版本编译"
fi

echo "▶ 10/25 测试语料必须入库"
# 2026-09-08：.gitignore 的 *.log 把 relay/tests 下的 12 个日志样本挡在库外，
# 新克隆里 10 条回放全判失败、两个测试直接崩，而代码一个字没错。
# 语料不入库 = 闸门在别的机器上失效，且失效得像「代码坏了」。
missing=0
while IFS= read -r f; do
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 || { note "测试语料没入库：$f"; missing=1; }
done < <(find relay/tests/fixtures relay/tests/replay -name '*.log' -o -name '*.json' 2>/dev/null)
[ "$missing" = 0 ] && ok "测试语料都在库里"

echo "▶ 11/25 中继的状态只能由中继自己写"
# 2026-09-08：状态收口把开关搬进 state.json，桌面那个 .bat 还在写旧的
# skip-next-shutdown.flag——按下去界面显示「不关机」，中继照常关机，一声不吭。
# 凡是中继会读的状态，外部脚本只能调它的函数，不许自己写文件。
if hits=$(grep -rnE 'ark-relay[\\/]state[\\/][A-Za-z0-9_.-]+' scripts/windows scripts/mac 2>/dev/null \
          | grep -vE 'statestore|state\.json|\.migrated|^\s*(#|rem )' \
          | grep -iE '>|set-content|write_text|echo .*>|del |remove-item'); then
  note "外部脚本在直接写中继的状态文件（要改走 ark_relay.features.modes.modes / statestore）："
  sed 's/^/       /' <<<"$hits"
else
  ok "没有外部脚本直接写状态文件"
fi

echo "▶ 12/25 公开仓库里不许有他人身份信息"
# 仓库是 public 的。别人的姓名、主机名、登录方式一旦提交就等于公开挂出去。
# The owner's game UID too: OK-WW's OCR dumps read it off the screen as the UID label followed
# by digits (the last alternative of ID_RE), and until 2026-10-13 it sat in plain text in eight
# committed files (now UIDREDACT, same length so offsets hold). Machine logs are committed as
# .log / .jsonl / .json and gzip / zstd, so the scan covers those and the compressed files'
# contents. ID_RE is the one copy of the pattern (relay/tests/daysim/pack.py identity_pattern()
# reads it from this line); never put the UID itself here.
ID_RE='卢智超|Administrator[^a-zA-Z].{0,20}(空密码|无密码|自动登录)|特征码(:|：) *[0-9]'
if hits=$( { grep -rnE "$ID_RE" \
          --include='*.md' --include='*.py' --include='*.sh' --include='*.js' \
          --include='*.log' --include='*.jsonl' --include='*.json' --include='*.txt' \
          --include='*.csv' --include='*.tsv' --include='*.yml' --include='*.yaml' --include='*.html' \
          . 2>/dev/null | grep -v '^\./\.git/' | grep -v 'lint-repo.sh'
        git ls-files '*.gz' '*.zst' | while IFS= read -r f; do
          # (pattern) with both parens: bash 3.2 (macOS /bin/bash) misreads a lone `)` inside $( ).
          case "$f" in
            (*.gz) gzip -dc "$f" ;;
            (*.zst) zstd -qdc "$f" ;;
          esac 2>/dev/null | LC_ALL=C grep -aqE "$ID_RE" && echo "$f (decompressed)"
        done
        command -v zstd >/dev/null || echo "zstd missing: the .zst files were not scanned (brew install zstd)"
      } ); [ -n "$hits" ]; then
  note "公开仓库里出现了他人身份信息、登录方式或游戏 UID（特征码后的数字）："
  sed 's/^/       /' <<<"$hits"
else
  ok "没有他人身份信息"
fi

echo "▶ 13/25 文档和脚本都要有入口"
# 2026-09-08：40 篇文档没有任何索引，只有 5 篇能从 CLAUDE.md 走到；
# 66 个脚本里只有 18 个在工具表里，包括「手动派发唯一入口」run-one.sh。
# 没有入口 = 下一次会话读不到 = 写了白写，而且会重复造一个。
orphan=0
for f in docs/*.md; do
  base=$(basename "$f")
  [ "$base" = "README.md" ] && continue
  grep -q "($base)" docs/README.md || { note "文档没进索引：docs/$base（加到 docs/README.md）"; orphan=1; }
done
[ "$orphan" = 0 ] && ok "每篇文档都在 docs/README.md 里"

miss=0
for f in scripts/mac/*.sh scripts/windows/*.py scripts/windows/*.bat; do
  [ -e "$f" ] || continue
  base=$(basename "$f")
  grep -qr "$base" CLAUDE.md docs/ --include='*.md' || { note "脚本没有任何文档提到：$f"; miss=1; }
done
[ "$miss" = 0 ] && ok "每个入口脚本都有文档提到"

echo "▶ 14/25 部署清单要和代码对得上"
# 2026-09-08 审出来：历史上 546 个带 manifest 的提交里，174 个改了真代码却和清单
# 对不上（32%）。后果是**静默的**：机器开机比哈希，发现「本机文件都和清单一致」，
# 不下载、不写日志、不播报，还照样把版本号刻上去——那次修改永远上不了机器。
# RELEASE-NOTES.md 例外：部署是先建清单、后清空正文，这个差异是设计如此。
if out=$(python3 - <<'PY'
import hashlib, json, sys
from pathlib import Path
m = json.loads(Path("relay/manifest.json").read_text(encoding="utf-8"))
bad = []
for name, want in m["files"].items():
    if name == "RELEASE-NOTES.md":
        continue
    p = Path("relay") / name
    if not p.exists():
        bad.append(f"{name}（清单里有，工作树没有）")
    elif hashlib.sha1(p.read_bytes()).hexdigest() != want:
        bad.append(f"{name}（内容和清单对不上）")
print("\n".join(bad))
sys.exit(1 if bad else 0)
PY
); then
  ok "清单和代码一致（$(python3 -c "import json;print(len(json.load(open('relay/manifest.json'))['files']))") 个文件）"
else
  note "清单和代码对不上，机器不会拿到这些改动——跑 (cd relay && python3 make-manifest.py) 重建："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 15/25 文档自检（check-docs --local）"
# 2026-09-08：这个检查器一直存在、一直在报错，却没有任何闸门会跑它，所以
# 「文档说的和代码做的对不对得上」这件事从来没人盯。只跑本地部分（纯只读、不联网）。
if out=$(python3 scripts/mac/check-docs.py --local 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "文档和代码对不上："
  grep -E "FAIL" <<<"$out" | sed 's/^/       /'
fi

echo "▶ 16/25 日志名要和模块名对得上"
# 2026-09-08 审出来：selfupdate.py 的日志名叫 ark.update、statestore.py 叫 ark.state、
# sanity_plan.py 叫 ark.sanity。翻日志时按模块名 grep 一无所获，会得出「这个模块没跑」
# 的错误结论——PITFALLS.md 里那条 WinError 10054 当时就是这么被找了半天。
# Modules that share a name on purpose (preupdate_*, gameupdate_*, the collector split, __main__ as the root) are allow-listed.
if out=$(python3 scripts/mac/lib/loggernames.py); then
  ok "每个模块的日志名都等于 ark.<模块名>"
else
  note "日志名和模块名对不上，按模块名翻日志会翻空："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 17/25 测试里的 check() 只准有一个意思"
# 2026-09-08：66 个测试各写各的 check()，其中两个把第二、第三个参数的意思写反了
# （名字, 成立与否, 补充说明）。在那两个文件里按大多数人的习惯写一句比较，
# 期望值会被当成说明打出来，断言退化成「实际值是不是真的」——永远通过，一声不吭。
# 现在比较相等的叫 check(label, got, want)，判真假的叫 require(name, ok, detail)。
if out=$(python3 scripts/mac/lib/checkshape.py); then
  ok "check() 与 require() 的参数意思全仓一致"
else
  note "测试里的断言函数参数意思对不上，写反了不会报错："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 18/25 指向 CODE-HISTORY 的锚点要唯一、上面那句话要说完"
# 2026-09-08: that document has 5 groups of same-named sections, so a pointer into it
# lands on the first one - which explains a different thing entirely. The same move
# left two dozen half-finished sentences in the code (「…has NO process of its」 and then
# straight into the pointer). A half sentence is worse than none: the reader believes
# they have just been given the reason.
if out=$(python3 scripts/mac/lib/history-anchors.py); then
  ok "锚点都指得到，指针上面的话都说完了"
else
  note "CODE-HISTORY 的锚点或指针有问题："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 19/25 ruff（让那些 noqa 真的有人验）"
# 2026-09-08: the repo held 521 `# noqa:` comments while there was no ruff config and
# nothing - no script, no CI - had ever run ruff. Not one of them had been checked.
# One named the rule PLC4015 (the real one is PLC0415) and had been quietly wrong ever
# since. With 239 empty ones cleared out, every remaining noqa really does suppress a
# rule, and RUF100 watches them: the moment an exemption becomes redundant this goes red.
# Which rules are on, and why, is written in ruff.toml.
if ! command -v uvx >/dev/null; then
  note "uvx 没装（brew install uv），ruff 跑不了"
elif out=$(uvx ruff check --config ruff.toml . 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "ruff 有报告："
  sed 's/^/       /' <<<"$out" | head -12
fi

echo "▶ 20/25 桌面串流图标是不是当前参数编出来的"
# The parameters live in one file, but the two desktop apps are compiled snapshots
# of them: change a value and stream-ins.sh picks it up at once while the icons the
# user double-clicks keep the old one. Both still launch and neither complains, so
# nothing noticed - MAC-CHANGES.md claimed the two agree with no check behind it.
if out=$(python3 scripts/mac/lib/stream_apps_current.py); then
  ok "$(tail -1 <<<"$out")"
else
  note "桌面图标和当前参数对不上："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 21/25 注释里的中文只准变少"
# The user, 2026-09-08: 「除了 readme 之外的部分都用英文，因为是你看的不是人看的。」
# docs/ was converted that day; the code still carries three thousand-odd lines.
# Converting them in one sweep would touch nearly every file, so this is a ratchet,
# the same shape as the untested-function ledger: record what is there, allow it to
# fall, never to rise. Whatever file gets touched gets translated on the way past.
# Zero is not the goal - quoting his own words keeps the Chinese original on purpose,
# because translating his words destroys the evidence.
if out=$(python3 scripts/mac/lib/zh_ratchet.py); then
  ok "$(tail -1 <<<"$out")"
else
  note "注释里的中文变多了："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 22/25 记下来的工具都在、都对着新中继"
# The user, 10-11 17:28, asked whether the relay's tools are all current - the four programs
# update themselves (BOARD/DECISIONS.md D-1011, tools current). Our own tools did not: that day eight
# of them still imported the ark_relay frozen in C:\ProgramData\ark-relay at the switch-over
# (the health check would have re-applied old OK-WW patches), memory and docs pointed at
# module paths that had moved, and the shared top-level checkout sat 359 commits behind.
# Offline; the parts that need the network (bundled Python, Pillow, pywin32) are
# scripts/mac/lib/parts_latest.py, run by deploy-relay.sh.
if out=$(python3 scripts/mac/lib/tool_refs.py 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "工具 / 文档 / 记忆里有指向老中继或不存在的路径："
  sed 's/^/       /' <<<"$out" | head -40
fi

echo "▶ 23/25 新加的等待 / 超时 / 重试 / 阈值数字要写出处"
# The user, 10-11 19:14, on numbers we picked ourselves and then kept: 「下次是一百二十秒」.
# That day's 120 s post-deploy wait (22c925b8) had no measurement behind it; c76d94a5 made it
# the measured 22 s and wrote the measurement above it. Only lines added since the branch left
# origin/main are judged (*.py / *.sh under scripts/ and relay/, not relay/tests/), so old code
# never blocks a push. A source is "Measured" / 实测, a doc URL, or his words 「...」 with a time,
# on the line or within the 6 lines above. Rules and examples: scripts/mac/lib/num_source.py.
if out=$(python3 scripts/mac/lib/num_source.py 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "new timing / retry / threshold numbers without a source:"
  sed 's/^/       /' <<<"$out" | head -40
fi

echo "▶ 24/25 中继代码按 ruff 的 F（会出错的）和 B（bugbear，容易藏错的）两类查，0 处"
# 2026-10-11: pyflakes (item 9) and the noqa set (item 19) never looked at the bugbear class.
# The first run over the relay code found 4 besides the zip() ones: two raises that dropped
# their cause, a dead loop variable, a closure over a name the loop rebinds (harmless there,
# noqa with the reason). B905 (zip() without strict=) was off while the Mac ran the tests on
# 3.9; since 10-12 they run on 3.14 (item 6) and each of its 15 sites says strict=. Line length (E501) and `;` (E702) are left
# out on purpose: they change how code reads, not what it does.
# Rules: https://docs.astral.sh/ruff/rules/#flake8-bugbear-b
if ! command -v uvx >/dev/null; then
  note "uvx 没装（brew install uv），ruff 跑不了"
elif out=$(uvx ruff check --config ruff.toml --select F,B relay/ark_relay relay/*.py scripts/windows 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "ruff F/B 有报告："
  sed 's/^/       /' <<<"$out" | head -12
fi

echo "▶ 25/25 整天回放：每天的 expected.json 审过带出处，known-red 清单有效，10-13 这一天跑得过"
# The day replay (relay/tests/daysim, design.md section 5). The schema check refuses an
# unreviewed or unsourced expected.json entry (oracle.py); run.py refuses an expired or
# closed known-red entry before it runs a day. One day only here (10-13, the shortest:
# 8 boots, 23 CPU-s measured 2026-10-13 19:3x); deploy-relay.sh step 0.8 runs every day plus
# the bad-patch self-check, which is why a deploy's own lint (LINT_SKIP_TESTS) skips the day.
# Each run gets its own out folder: every session lints in its own worktree at the same time.
# RELAY_PY is set by item 6, which LINT_SKIP_TESTS skips.
DPY="${RELAY_PY:-}"
[ -n "$DPY" ] || DPY=$(scripts/mac/lib/relay-python.sh 2>/dev/null) || DPY=false
if out=$(cd relay && "$DPY" -I tests/daysim/oracle.py schema 2>&1); then
  ok "expected.json：$(grep -c '^ok ' <<<"$out") 天都审过、带出处"
else
  note "expected.json 有没审过或没出处的条目："
  sed 's/^/       /' <<<"$out" | head -20
fi
if [ -n "${LINT_SKIP_TESTS:-}" ]; then
  echo "  ⏭ 10-13 回放已跳过（部署第 0.8 步会把每天都跑一遍）"
else
  DAY_OUT=$(mktemp -d "${TMPDIR:-/tmp}/lint-daysim.XXXXXX")
  if out=$("$DPY" -I relay/tests/daysim/run.py --day 2026-10-13 --out "$DAY_OUT" 2>&1); then
    ok "10-13 回放：$(grep -E '^  verdict ' <<<"$out" | sed 's/^  verdict //')"
  else
    note "10-13 回放不通过："
    grep -vE '^  ok   |^       why:' <<<"$out" | sed 's/^/       /' | head -20
  fi
  rm -rf "$DAY_OUT"
fi

echo
[ "$FAIL" = 0 ] && echo "✅ 仓库自检通过" || echo "❌ 有问题，先修再提交"
exit $FAIL
