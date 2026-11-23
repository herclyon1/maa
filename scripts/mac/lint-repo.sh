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

echo "▶ 1/17 shellcheck"
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

# PowerShell 5.1 does not read UTF-8 by default: Chinese JSON breaks.
echo "▶ 2/17 不许用 powershell 5.1（要用 pwsh 7）"
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

# bash, ssh and cmd each strip a layer of quotes; -EncodedCommand survives all three.
echo "▶ 3/17 ssh 送 PowerShell 必须走 base64"
hits=$(grep -rn 'ssh .*pwsh -\(NoProfile \)\?-\?[Cc]ommand' scripts/ 2>/dev/null \
       | grep -v EncodedCommand | grep -v "^\s*#" || true)
[ -z "$hits" ] && ok "没有内联拼接的远端 PowerShell" || { note "有内联 -Command（应改 -EncodedCommand）"; echo "$hits" | head -5 | sed 's/^/       /'; }

# A script directory resolved after cd points nowhere, and the step that uses it fails silently.
echo "▶ 4/17 脚本目录必须在 cd 之前算好"
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

echo "▶ 5/17 部署清单要包含更新说明"
if grep -q 'RELEASE-NOTES.md' relay/make-manifest.py 2>/dev/null; then
  ok "make-manifest 会带上 RELEASE-NOTES.md"
else
  note "make-manifest.py 没有把 RELEASE-NOTES.md 放进清单"
fi

if [ -n "${LINT_SKIP_TESTS:-}" ]; then
  echo "▶ 6/17 中继测试全绿"
  echo "  ⏭ 已跳过（调用方自己会跑一遍，这里再跑是重复）"
else
echo "▶ 6/17 中继测试全绿"
# Criteria: exit code 0 and the last line says passed.
# 失败时把**报错内容**打出来，不是只报一个文件名。原来只吐文件名，人还得自己
# 再跑一遍才知道错在哪；而收进变量再 tr '\n' ' ' 会把 traceback 压成一整行，
# 比不打还难读。所以让 runner 直接往 stdout 打，外层只判成败。
lint_one_test() {
  local name out
  wait_not_background
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
# Every test file, every time (until 2026-11-17 scripts/mac/lib/lint_pick_tests.py picked the ones a
# change reached; it was removed with relay/tests/test-map.json).
LINT_TESTS=$(mktemp)
printf '%s\n' relay/tests/test_*.py >"$LINT_TESTS"; scope="全部"
cnt=$(grep -c . "$LINT_TESTS" || true)
echo "  · 跑${scope} ${cnt} 个测试"
# Eight at a time, but every test first waits while macOS runs this check at background priority:
# on this Mac's macOS 27.2 beta a background-priority process that starts programs can lock the
# kernel (09-23 04:19 panic; 10-14 19:52 the Mac froze 62 s after Game Mode put Claude and all it
# started at background priority while this check was starting about five tests a second). That
# priority only comes with a game in front, so the rest of the time the check keeps its speed.
# shellcheck source=scripts/mac/lib/wait-not-background.sh
. scripts/mac/lib/wait-not-background.sh
export -f wait_not_background
if [ "$cnt" = 0 ] || xargs -P 8 -I{} bash -c 'lint_one_test "$1"' _ {} <"$LINT_TESTS"; then
  ok "${scope} ${cnt} 个测试全过"
else
  note "有测试没过（见上）"
fi

fi

# A function defined and never called (a test placed after `if __name__`) never runs, and its file still
# says passed; the whole class is checked, not one way of writing it.
echo "▶ 7/17 没有永远不会被执行的代码"
if out=$(python3 scripts/mac/lib/deadcode.py relay scripts 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "有孤立/被覆盖的函数"
  sed 's/^/    /' <<<"$out"
fi

# pyflakes catches a name read before it is bound (F823), which the tests can miss; the strict 3.14
# compile catches invalid escapes ('\d') that the Mac's own 3.9 accepts in silence.
echo "▶ 8/17 静态检查（pyflakes + 3.14 严格编译）"
PY314="/opt/homebrew/bin/python3"   # 11-22 全机统一最新 Python（方案 p01）；原 ~/.local/bin/python3.14 已删
if ! command -v uvx >/dev/null; then
  note "uvx 没装（brew install uv），pyflakes 跑不了"
else
  # okww_files 是上游原样文件，不归我们管。
  # 2026-09-08 把 relay/tests 也纳进来：之前不查，于是 55 条报告在里面躺着，
  # 其中 test_preupdate.py 那条 f-string 缺占位符指向一个真断言错误——
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

echo "▶ 9/17 测试语料必须入库"
missing=0
while IFS= read -r f; do
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 || { note "测试语料没入库：$f"; missing=1; }
done < <(find relay/tests/fixtures -type f 2>/dev/null; ls relay/tests/fx_samples.json 2>/dev/null)
[ "$missing" = 0 ] && ok "测试语料都在库里"

echo "▶ 10/17 中继的状态只能由中继自己写"
# A state the relay reads is changed only through its own functions, never by writing the file.
if hits=$(grep -rnE 'ark-relay[\\/]state[\\/][A-Za-z0-9_.-]+' scripts/windows scripts/mac 2>/dev/null \
          | grep -vE 'statestore|state\.json|\.migrated|^\s*(#|rem )' \
          | grep -iE '>|set-content|write_text|echo .*>|del |remove-item'); then
  note "外部脚本在直接写中继的状态文件（要改走 ark_relay.features.modes / statestore）："
  sed 's/^/       /' <<<"$hits"
else
  ok "没有外部脚本直接写状态文件"
fi

echo "▶ 11/17 公开仓库里不许有他人身份信息"
# 仓库是 public 的。别人的姓名、主机名、登录方式一旦提交就等于公开挂出去。
# The owner's game UID too: OK-WW's OCR dumps read it off the screen as the UID label followed
# by digits (the last alternative of ID_RE), and until 2026-10-13 it sat in plain text in eight
# committed files (now UIDREDACT, same length so offsets hold). Machine logs are committed as
# .log / .jsonl / .json and gzip / zstd, so the scan covers those and the compressed files'
# contents. ID_RE is the one copy of the pattern (relay/tests/test_verify.py reads it from this
# line); never put the UID itself here.
# .claude/worktrees is git-ignored, so nothing there is public; a worktree older than 10-13 still holds the
# unredacted logs and failed the scan on 10-29 / 10-31 (95 lines in relay1-skipabort, none of them in the repo).
ID_RE='卢智超|Administrator[^a-zA-Z].{0,20}(空密码|无密码|自动登录)|特征码(:|：) *[0-9]'
if hits=$( { grep -rnE "$ID_RE" \
          --include='*.md' --include='*.py' --include='*.sh' --include='*.js' \
          --include='*.log' --include='*.jsonl' --include='*.json' --include='*.txt' \
          --include='*.csv' --include='*.tsv' --include='*.yml' --include='*.yaml' --include='*.html' \
          --exclude-dir=worktrees . 2>/dev/null | grep -v '^\./\.git/' | grep -v 'lint-repo.sh'
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

echo "▶ 12/17 文档和脚本都要有入口"
# A document or script nothing points to is never read again, and gets written a second time.
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

echo "▶ 13/17 部署清单要和代码对得上"
# Code that differs from the manifest never reaches the machine, and nothing says so.
# RELEASE-NOTES.md differs on purpose: the deploy builds the manifest, then empties the notes.
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

echo "▶ 14/17 日志名要和模块名对得上"
# A logger named other than its module makes a grep of the log by module name find nothing.
# Modules that share a name on purpose (preupdate_*, gameupdate_*, the collector split, __main__ as the root) are allow-listed.
if out=$(python3 scripts/mac/lib/deadcode.py --loggernames); then
  ok "每个模块的日志名都等于 ark.<模块名>"
else
  note "日志名和模块名对不上，按模块名翻日志会翻空："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 15/17 测试里的 check() 只准有一个意思"
# check(label, got, want) compares, require(name, ok, detail) asserts; swapped arguments would pass silently.
if out=$(python3 scripts/mac/lib/deadcode.py --checkshape); then
  ok "check() 与 require() 的参数意思全仓一致"
else
  note "测试里的断言函数参数意思对不上，写反了不会报错："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 16/17 ruff（让那些 noqa 真的有人验）"
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

echo "▶ 17/17 中继代码按 ruff 的 F（会出错的）和 B（bugbear，容易藏错的）两类查，0 处"
# 2026-10-11: pyflakes (item 8) and the noqa set (item 16) never looked at the bugbear class.
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

echo
[ "$FAIL" = 0 ] && echo "✅ 仓库自检通过" || echo "❌ 有问题，先修再提交"
exit $FAIL
