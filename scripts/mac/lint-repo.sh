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

echo "▶ 1/9 shellcheck"
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
echo "▶ 2/9 不许用 powershell 5.1（要用 pwsh 7）"
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
echo "▶ 3/9 ssh 送 PowerShell 必须走 base64"
hits=$(grep -rn 'ssh .*pwsh -\(NoProfile \)\?-\?[Cc]ommand' scripts/ 2>/dev/null \
       | grep -v EncodedCommand | grep -v "^\s*#" || true)
[ -z "$hits" ] && ok "没有内联拼接的远端 PowerShell" || { note "有内联 -Command（应改 -EncodedCommand）"; echo "$hits" | head -5 | sed 's/^/       /'; }

# 2026-08-26：deploy-relay.sh 在 `cd` 之后才解析 $(dirname "${BASH_SOURCE[0]}")，
# 相对路径当场失效，取日志那步静默失败。当天 cwd 类问题共撞 37 次。
echo "▶ 4/9 脚本目录必须在 cd 之前算好"
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
echo "▶ 5/9 部署清单要包含更新说明"
if grep -q 'RELEASE-NOTES.md' relay/make-manifest.py 2>/dev/null; then
  ok "make-manifest 会带上 RELEASE-NOTES.md"
else
  note "make-manifest.py 没有把 RELEASE-NOTES.md 放进清单"
fi

# 2026-08-26：新写的测试函数被 `>>` 追加到了 `main()` 之后，调用时还没定义。
# 测试跑一遍就会 NameError，所以这条直接用「全部测试能跑通」兜住。
if [ -n "${LINT_SKIP_TESTS:-}" ]; then
  echo "▶ 6/9 中继测试全绿"
  echo "  ⏭ 已跳过（调用方自己会跑一遍，这里再跑是重复）"
else
echo "▶ 6/9 中继测试全绿"
# 并行跑：这道闸每次部署会被跑两遍（部署自己一遍、闸门自检里的
# lint-repo 一遍），串行十几秒全是白等。判据没松：退出码要 0，
# 且最后一行必须写着 passed。
lint_one_test() {
  local out
  out=$(cd relay && python3 "tests/$(basename "$1")" 2>&1) || return 1
  grep -qiE "passed|^PASS" <<<"$(tail -1 <<<"$out")" || { echo "$(basename "$1")"; return 1; }
}
export -f lint_one_test
cnt=$(find relay/tests -name 'test_*.py' | wc -l | tr -d ' ')
if bad=$(printf '%s\n' relay/tests/test_*.py \
         | xargs -P 8 -I{} bash -c 'lint_one_test "$1" || { basename "$1"; exit 1; }' _ {} 2>&1); then
  ok "$cnt 个测试全过"
else
  note "没过:$(tr '\n' ' ' <<<"$bad")"
fi

fi

# 2026-08-27：同一类错的第三次——把测试函数写在 `if __name__` 之后，
# 它永远不会被调用，测试照样打印 "all checks passed"、闸门照样放行。
# 上面那条「测试全绿」拦不住：那个函数根本没被执行，谈不上红不红。
# 所以这里查的是「定义了却没人调用」这一整类，而不是某一次的写法。
echo "▶ 7/9 没有永远不会被执行的代码"
if out=$(python3 scripts/mac/lib/deadcode.py relay scripts 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "有孤立/被覆盖的函数"
  sed 's/^/    /' <<<"$out"
fi

echo "▶ 8/9 手机页文案不许有私人措辞"
# 规矩见 docs/手机页文案的规矩.md。文档拦不住，闸门才拦得住：
# 2026-09-04 页面上写着「上游 beta.5 那阵它是坏的……中继在 09-04 开机时开了回来」，
# 用户的话是「太私人措辞了」。命中下面这些词就拒绝提交。
# 后半段是「把当前状态写进静态文案」——控件自己显示着选了什么，
# 文案再写一遍必然过期：2026-09-04 写着「路线 3 和 13 已取消勾选」，
# 用户把 16 条全勾上之后那句话当场变成假的。
bad_words='上游|中继|母本|账本|脚本|issue|PR |用户|我们|原话|实录|那阵|那次|先关着|已修好|等上游|beta\.|rc\.|v[0-9]+\.[0-9]+|20[0-9]{2}-[0-9]{2}-[0-9]{2}|已取消勾选|已勾选|已关掉|已开回|目前是|现在是|当前设置'
if hits=$(grep -nE '^\s*(hint|label):' web/app.js | grep -E "$bad_words"); then
  note "手机页文案有内部措辞或会过期的信息，按 docs/手机页文案的规矩.md 重写"
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
echo "▶ 9/9 静态检查（pyflakes + 3.14 严格编译）"
PY314="$HOME/.local/bin/python3.14"
if ! command -v uvx >/dev/null; then
  note "uvx 没装（brew install uv），pyflakes 跑不了"
else
  # okww_files 是上游原样文件，不归我们管
  hits=$(uvx pyflakes relay/ark_relay relay/service.py relay/run.py relay/make-manifest.py scripts 2>&1 \
         | grep -v 'okww_files' || true)
  [ -z "$hits" ] && ok "pyflakes 零报告" || { note "pyflakes 有报告（未定义名 / 先读后绑定 / 无用导入）"; sed 's/^/       /' <<<"$hits" | head -12; }
fi
if [ -x "$PY314" ]; then
  if out=$("$PY314" -W error::SyntaxWarning -c "
import compileall, sys
ok = compileall.compile_dir('relay/ark_relay', quiet=1, force=True, legacy=False)
ok = compileall.compile_file('relay/service.py', quiet=1, force=True) and ok
ok = compileall.compile_dir('scripts', quiet=1, force=True) and ok
sys.exit(0 if ok else 1)" 2>&1); then
    ok "3.14 严格编译通过（无非法转义）"
  else
    note "3.14 严格编译失败（机器上跑的就是 3.14）"; sed 's/^/       /' <<<"$out" | tail -6
  fi
else
  note "找不到 $PY314，没法按机器的 Python 版本编译"
fi

echo
[ "$FAIL" = 0 ] && echo "✅ 仓库自检通过" || echo "❌ 有问题，先修再提交"
exit $FAIL
