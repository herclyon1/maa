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

echo "▶ 1/19 shellcheck"
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
echo "▶ 2/19 不许用 powershell 5.1（要用 pwsh 7）"
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
echo "▶ 3/19 ssh 送 PowerShell 必须走 base64"
hits=$(grep -rn 'ssh .*pwsh -\(NoProfile \)\?-\?[Cc]ommand' scripts/ 2>/dev/null \
       | grep -v EncodedCommand | grep -v "^\s*#" || true)
[ -z "$hits" ] && ok "没有内联拼接的远端 PowerShell" || { note "有内联 -Command（应改 -EncodedCommand）"; echo "$hits" | head -5 | sed 's/^/       /'; }

# 2026-08-26：deploy-relay.sh 在 `cd` 之后才解析 $(dirname "${BASH_SOURCE[0]}")，
# 相对路径当场失效，取日志那步静默失败。当天 cwd 类问题共撞 37 次。
echo "▶ 4/19 脚本目录必须在 cd 之前算好"
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
echo "▶ 5/19 部署清单要包含更新说明"
if grep -q 'RELEASE-NOTES.md' relay/make-manifest.py 2>/dev/null; then
  ok "make-manifest 会带上 RELEASE-NOTES.md"
else
  note "make-manifest.py 没有把 RELEASE-NOTES.md 放进清单"
fi

# 2026-08-26：新写的测试函数被 `>>` 追加到了 `main()` 之后，调用时还没定义。
# 测试跑一遍就会 NameError，所以这条直接用「全部测试能跑通」兜住。
if [ -n "${LINT_SKIP_TESTS:-}" ]; then
  echo "▶ 6/19 中继测试全绿"
  echo "  ⏭ 已跳过（调用方自己会跑一遍，这里再跑是重复）"
else
echo "▶ 6/19 中继测试全绿"
# 并行跑：这道闸每次部署会被跑两遍（部署自己一遍、闸门自检里的
# lint-repo 一遍），串行十几秒全是白等。判据没松：退出码要 0，
# 且最后一行必须写着 passed。
# 失败时把**报错内容**打出来，不是只报一个文件名。原来只吐文件名，人还得自己
# 再跑一遍才知道错在哪；而收进变量再 tr '\n' ' ' 会把 traceback 压成一整行，
# 比不打还难读。所以让 runner 直接往 stdout 打，外层只判成败。
lint_one_test() {
  local name out
  name=$(basename "$1")
  if ! out=$(cd relay && python3 "tests/$name" 2>&1); then
    printf '  ✗ %s 抛异常：\n%s\n' "$name" "$(sed 's/^/       /' <<<"$(tail -15 <<<"$out")")"
    return 1
  fi
  if ! grep -qiE "passed|^PASS" <<<"$(tail -1 <<<"$out")"; then
    printf '  ✗ %s 没过：\n%s\n' "$name" "$(sed 's/^/       /' <<<"$(grep -E "✗|FAIL" <<<"$out" | head -8)")"
    return 1
  fi
}
export -f lint_one_test
cnt=$(find relay/tests -name 'test_*.py' | wc -l | tr -d ' ')
if printf '%s\n' relay/tests/test_*.py \
   | xargs -P 8 -I{} bash -c 'lint_one_test "$1"' _ {}; then
  ok "$cnt 个测试全过"
else
  note "有测试没过（见上）"
fi

fi

# 2026-08-27：同一类错的第三次——把测试函数写在 `if __name__` 之后，
# 它永远不会被调用，测试照样打印 "all checks passed"、闸门照样放行。
# 上面那条「测试全绿」拦不住：那个函数根本没被执行，谈不上红不红。
# 所以这里查的是「定义了却没人调用」这一整类，而不是某一次的写法。
echo "▶ 7/19 没有永远不会被执行的代码"
if out=$(python3 scripts/mac/lib/deadcode.py relay scripts 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "有孤立/被覆盖的函数"
  sed 's/^/    /' <<<"$out"
fi

echo "▶ 8/19 手机页文案不许有私人措辞"
# 规矩见 docs/PHONE-COPY-RULES.md。文档拦不住，闸门才拦得住：
# 2026-09-04 页面上写着「上游 beta.5 那阵它是坏的……中继在 09-04 开机时开了回来」，
# 用户的话是「太私人措辞了」。命中下面这些词就拒绝提交。
# 后半段是「把当前状态写进静态文案」——控件自己显示着选了什么，
# 文案再写一遍必然过期：2026-09-04 写着「路线 3 和 13 已取消勾选」，
# 用户把 16 条全勾上之后那句话当场变成假的。
bad_words='上游|中继|母本|账本|脚本|issue|PR |用户|我们|原话|实录|那阵|那次|先关着|已修好|等上游|beta\.|rc\.|v[0-9]+\.[0-9]+|20[0-9]{2}-[0-9]{2}-[0-9]{2}|已取消勾选|已勾选|已关掉|已开回|目前是|现在是|当前设置'
if hits=$(grep -nE '^\s*(hint|label):' web/app.js | grep -E "$bad_words"); then
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
echo "▶ 9/19 静态检查（pyflakes + 3.14 严格编译）"
PY314="$HOME/.local/bin/python3.14"
if ! command -v uvx >/dev/null; then
  note "uvx 没装（brew install uv），pyflakes 跑不了"
else
  # okww_files 是上游原样文件，不归我们管。
  # 2026-09-08 把 relay/tests 也纳进来：之前不查，于是 55 条报告在里面躺着，
  # 其中 test_preupdate_problems.py 那条 f-string 缺占位符指向一个真断言错误——
  # 它用 for + break 只查了四个函数里的第一个。
  hits=$(uvx pyflakes relay/ark_relay relay/tests relay/service.py relay/run.py relay/make-manifest.py scripts 2>&1 \
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

echo "▶ 10/19 测试语料必须入库"
# 2026-09-08：.gitignore 的 *.log 把 relay/tests 下的 12 个日志样本挡在库外，
# 新克隆里 10 条回放全判失败、两个测试直接崩，而代码一个字没错。
# 语料不入库 = 闸门在别的机器上失效，且失效得像「代码坏了」。
missing=0
while IFS= read -r f; do
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 || { note "测试语料没入库：$f"; missing=1; }
done < <(find relay/tests/fixtures relay/tests/replay -name '*.log' -o -name '*.json' 2>/dev/null)
[ "$missing" = 0 ] && ok "测试语料都在库里"

echo "▶ 11/19 中继的状态只能由中继自己写"
# 2026-09-08：状态收口把开关搬进 state.json，桌面那个 .bat 还在写旧的
# skip-next-shutdown.flag——按下去界面显示「不关机」，中继照常关机，一声不吭。
# 凡是中继会读的状态，外部脚本只能调它的函数，不许自己写文件。
if hits=$(grep -rnE 'ark-relay[\\/]state[\\/][A-Za-z0-9_.-]+' scripts/windows scripts/mac 2>/dev/null \
          | grep -vE 'statestore|state\.json|\.migrated|^\s*(#|rem )' \
          | grep -iE '>|set-content|write_text|echo .*>|del |remove-item'); then
  note "外部脚本在直接写中继的状态文件（要改走 ark_relay.modes / statestore）："
  sed 's/^/       /' <<<"$hits"
else
  ok "没有外部脚本直接写状态文件"
fi

echo "▶ 12/19 公开仓库里不许有他人身份信息"
# 仓库是 public 的。别人的姓名、主机名、登录方式一旦提交就等于公开挂出去。
if hits=$(grep -rnE '卢智超|Administrator[^a-zA-Z].{0,20}(空密码|无密码|自动登录)' \
          --include='*.md' --include='*.py' --include='*.sh' --include='*.js' \
          . 2>/dev/null | grep -v '^\./\.git/' | grep -v 'lint-repo.sh'); then
  note "公开仓库里出现了他人身份信息或登录方式："
  sed 's/^/       /' <<<"$hits"
else
  ok "没有他人身份信息"
fi

echo "▶ 13/19 文档和脚本都要有入口"
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

echo "▶ 14/19 部署清单要和代码对得上"
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

echo "▶ 15/19 文档自检（check-docs --local）"
# 2026-09-08：这个检查器一直存在、一直在报错，却没有任何闸门会跑它，所以
# 「文档说的和代码做的对不对得上」这件事从来没人盯。只跑本地部分（纯只读、不联网）。
if out=$(python3 scripts/mac/check-docs.py --local 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "文档和代码对不上："
  grep -E "FAIL" <<<"$out" | sed 's/^/       /'
fi

echo "▶ 16/19 日志名要和模块名对得上"
# 2026-09-08 审出来：selfupdate.py 的日志名叫 ark.update、statestore.py 叫 ark.state、
# sanity_plan.py 叫 ark.sanity。翻日志时按模块名 grep 一无所获，会得出「这个模块没跑」
# 的错误结论——PITFALLS.md 里那条 WinError 10054 当时就是这么被找了半天。
# 故意共用一个名字的几家（okww_patches 四个模块、preupdate_* 一家、__main__ 用根名）在白名单里。
if out=$(python3 scripts/mac/lib/loggernames.py); then
  ok "每个模块的日志名都等于 ark.<模块名>"
else
  note "日志名和模块名对不上，按模块名翻日志会翻空："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 17/19 测试里的 check() 只准有一个意思"
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

echo "▶ 18/19 指向 CODE-HISTORY 的锚点要唯一、上面那句话要说完"
# 2026-09-08：那份文档里有 5 组同名章节，代码里指过去的人会落在第一段——读到的是
# 另一件事的来龙去脉。同一次搬迁还在代码里留下二十来处半截话（「…has NO process of its」
# 后面直接是指针），半截话比没有更糟，读的人以为自己读到了理由。
if out=$(python3 scripts/mac/lib/history-anchors.py); then
  ok "锚点都指得到，指针上面的话都说完了"
else
  note "CODE-HISTORY 的锚点或指针有问题："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 19/19 ruff（让那些 noqa 真的有人验）"
# 2026-09-08：仓库里当时有 521 条 `# noqa:`，而既没有 ruff 配置、也没有任何脚本或 CI
# 跑过 ruff——一条都没被验证过。其中一条把规则号写成 PLC4015（正确的是 PLC0415），
# 静静地错着。清掉 239 条空头支票之后，剩下的每一条都是**真的在压住一条规则**，
# RUF100 会盯着：哪条豁免变得多余，这里就会红。规则的取舍和理由写在 ruff.toml 里。
if ! command -v uvx >/dev/null; then
  note "uvx 没装（brew install uv），ruff 跑不了"
elif out=$(uvx ruff check --config ruff.toml . 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "ruff 有报告："
  sed 's/^/       /' <<<"$out" | head -12
fi

echo
[ "$FAIL" = 0 ] && echo "✅ 仓库自检通过" || echo "❌ 有问题，先修再提交"
exit $FAIL
