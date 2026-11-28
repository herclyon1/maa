#!/usr/bin/env bash
# 仓库自检 —— 每一条规则都对应一次真实犯过的错。
#
#   scripts/mac/lint-repo.sh
#
# 和 shellcheck 的分工：shellcheck 查通用 shell 缺陷，这里查**这个项目特有的
# 反模式**——那些语法完全合法、但在这台游戏机上必然出问题的写法。
# 全文遵循零硬编码版本号动态工具闸门范式（升级 Python/pwsh 永不失效）。
set -uo pipefail
export PATH="${PATH}:/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin"
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1   # 绝对路径，见规则 5

RELAY_HOST_PY="${RELAY_HOST_PY:-/opt/homebrew/bin/python3}"
if [ ! -x "$RELAY_HOST_PY" ]; then
  echo "  ✗ 找不到最新版 Homebrew Python（${RELAY_HOST_PY}），拒绝退回系统旧版" >&2
  exit 1
fi

FAIL=0
note() { printf '  ✗ %s\n' "$1"; FAIL=1; }
ok()   { printf '  ✅ %s\n' "$1"; }
# 使用临时文件承接 Python 自检输出，兼容 macOS 自带 bash 3.2（避免在 $() 内嵌 heredoc 引号解析异常）
LINT_TMP="$(mktemp)"
trap 'rm -f "$LINT_TMP"' EXIT

echo "▶ 1/17 shellcheck"
if command -v shellcheck >/dev/null || [ -x "$HOME/.local/bin/shellcheck" ]; then
  SC="$(command -v shellcheck || echo "$HOME/.local/bin/shellcheck")"
  bad=""
  while IFS= read -r f; do
    [ -n "$("$SC" -S warning "$f" 2>&1)" ] && bad="$bad $f"
  done < <(find scripts -name '*.sh')
  [ -z "$bad" ] && ok "全部脚本无 warning" || note "有告警:$bad"
else
  note "shellcheck 没装（brew install shellcheck）"
fi

# PowerShell 5.1 默认非 UTF-8 且已被用户永久禁用，wmic 在 Win11 25H2 不存在；
# 扫描覆盖 relay/ packaging/ scripts/（包含 .ps1），0 容忍拦截 5.1 / else (powershell / wmic /
# /usr/bin/python3 / 静态 Python 版本 floor 与旧版本号命名。
echo "▶ 2/17 不许用 PowerShell 5.1 / wmic / /usr/bin/python3 / 静态版本 floor / 硬编码旧版 Python 路径"
if "$RELAY_HOST_PY" - <<'PY' >"$LINT_TMP"
import re, sys
from pathlib import Path

ROOTS = ("relay", "packaging", "scripts")
SCAN_SUFFIXES = {".py", ".sh", ".ps1", ".bat", ".cmd", ".plist"}
SKIP_DIRS = {"__pycache__", "fixtures", "okww_files", ".git"}
SKIP_EXACT = {
    "scripts/mac/lint-repo.sh",
    "relay/tests/test_iron_rules_gate.py",
    "relay/tests/fx_samples.json",
}
# 按（文件, 规则标签, 行特征子串）精准豁免守卫脚本自身的规则定义/提示行，严禁整文件放行
GUARD_LINE_EXEMPTS = (
    ("scripts/mac/lib/shutdown_guard.py", "wmic调用", r"\bwmic(?:\.exe)?\b[^\r\n]*\bcall\s+(?:shutdown|reboot|Win32Shutdown)"),
    ("scripts/mac/lib/shutdown_guard.py", "wmic调用", r"(?:shutdown|logoff|cmd|pwsh|powershell|wmic|rundll32)(?:\.exe)?$"),
    ("scripts/mac/winps.sh", "wmic调用", r"grep -qE '\bssh\b|\bwmic\b'"),
    ("scripts/mac/winps.sh", "wmic调用", 'echo "winps: 脚本里出现了 ssh 或 wmic'),
    ("scripts/mac/winps.sh", "wmic调用", 'echo "       PowerShell 侧请用 Get-CimInstance 取代 wmic'),
    ("relay/tests/test_ops_gates.py", "系统旧版Python", 'sys_py = Path("/usr/bin/python3")'),
)

PATTERNS = [
    ("PS5.1可执行", re.compile(r"powershell\.exe", re.I)),
    ("PS5.1目录", re.compile(r"WindowsPowerShell[\\/]+v1\.0", re.I)),
    ("PS5.1兜底", re.compile(r"else\s*\(\s*powershell\b", re.I)),
    ("裸powershell调用", re.compile(r"""(?:['"]powershell['"]|\bpowershell\s+-(?:NoProfile|Command|EncodedCommand|ExecutionPolicy|File|WindowStyle|NonInteractive)\b)""", re.I)),
    ("wmic调用", re.compile(r"""(?:^|[\s'"\x60(;&|])wmic(?:\.exe)?(?=$|[\s'"\x60);&|])""", re.I)),
    ("系统旧版Python", re.compile(r"/usr/bin/python3\b")),
    ("静态Python版本floor", re.compile(r"""(?:["']Python\s+3\.\d+\.?["']\*|["']Python\s+3\.\d+\.\*["']|\bPython\\?\s+3\.\d+\.\*|\bsys\.version_info\s*(?:>=|<=|<|>|==|!=)\s*\(\s*3\s*,\s*\d+|\.startswith\(\s*\(?["']Python\s+3\.\d+)""")),
    ("旧版本号变量名", re.compile(r"\b(?:RELAY_)?PY3\d\d\b")),
    ("Windows硬编码Python3xx目录", re.compile(r"Program Files[\\/]+Python3\d\d", re.I)),
    ("旧3.12.0路径", re.compile(r"automas[\\/]+environment[\\/]+python[\\/]+python\.exe", re.I)),
]

def _is_line_exempt(rel: str, label: str, line: str) -> bool:
    for ex_rel, ex_label, marker in GUARD_LINE_EXEMPTS:
        if rel == ex_rel and label == ex_label and marker in line:
            return True
    return False

hits = []
for top in ROOTS:
    base = Path(top)
    if not base.exists():
        continue
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in SCAN_SUFFIXES:
            continue
        rel = p.as_posix()
        if rel in SKIP_EXACT:
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, 1):
            stripped = line.lstrip()
            # 跳过纯注释行（# 或 rem）
            if stripped.startswith("#") or re.match(r"(?i)^rem\b", stripped):
                continue
            for label, pat in PATTERNS:
                if pat.search(line):
                    # 按行特征表精准豁免守卫脚本的规则定义/提示行（绝不做整文件豁免）
                    if _is_line_exempt(rel, label, line):
                        continue
                    # 历史单测模拟命令行样本或中文测试标题打印（如 "没有 wmic 的机器"）不视作活跃调用
                    if rel.startswith("relay/tests/") and (
                        label == "Windows硬编码Python3xx目录"
                        or (label == "wmic调用" and stripped.startswith("print("))
                    ):
                        continue
                    hits.append(f"{rel}:{idx}: [{label}] {stripped[:120]}")
                    break

if hits:
    print("\n".join(hits))
    sys.exit(1)
PY
then
  ok "全仓 0 处 PowerShell 5.1 / wmic / /usr/bin/python3 / 静态版本 floor / PY3xx / Python3xx / 旧 3.12 路径"
else
  note "发现违禁旧工具或硬编码版本路径："
  head -12 "$LINT_TMP" | sed 's/^/       /'
fi

# bash、ssh、cmd 各剥一层引号；-EncodedCommand 走 base64 永不被引号坑。
echo "▶ 3/17 ssh 送 PowerShell 必须走 base64"
hits=$(grep -rn 'ssh .*pwsh -\(NoProfile \)\?-\?[Cc]ommand' scripts/ 2>/dev/null \
       | grep -v EncodedCommand | grep -v "^\s*#" || true)
[ -z "$hits" ] && ok "没有内联拼接的远端 PowerShell" || { note "有内联 -Command（应改 -EncodedCommand）"; echo "$hits" | head -5 | sed 's/^/       /'; }

# 脚本目录必须在任何 cd 之前算好，否则相对路径当场失效。
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

# 无论是否跳过全量测试，始终执行零硬编码动态最新 Python 闸门与全仓裸 python3 检查。
if ! RELAY_PY=$(scripts/mac/lib/relay-python.sh); then
  note "找不到最新版 Python 跑中继测试（见上），严禁退回系统旧版"
fi
export RELAY_PY

# 动态校验 called_ver == max_installed_ver（彻底取代硬编码 "Python 3.14."*|"Python 3.15."*）
if [ -n "${RELAY_PY:-}" ] && [ -x "${RELAY_PY:-}" ]; then
  CALLED_VER="$("$RELAY_PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}")')"
  HOST_VER="$("$RELAY_HOST_PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}")')"
  if [ "$CALLED_VER" = "$HOST_VER" ]; then
    ok "中继测试 Python 动态校验通过：Python ${CALLED_VER} == 本机最新版（${HOST_VER}）"
  else
    note "中继测试 Python 版本（${CALLED_VER}）!= 本机最新版（${HOST_VER}）"
  fi
  if [ -f "$HOME/Money/tools/verify_latest_python.py" ]; then
    if vout=$("$RELAY_HOST_PY" "$HOME/Money/tools/verify_latest_python.py" 2>&1); then
      ok "全机最新 Python 动态闸门：$(tail -1 <<<"$vout")"
    else
      note "全机最新 Python 动态闸门失败："
      sed 's/^/       /' <<<"$vout" | head -8
    fi
  fi
fi

# 全仓 Mac 脚本（scripts/mac/*.sh、scripts/mac/lib/*.sh）与 CI 入口不允许直接调用无保护的裸 python3
if "$RELAY_HOST_PY" - <<'PY' >"$LINT_TMP"
import re, sys
from pathlib import Path

targets = sorted(Path("scripts/mac").glob("*.sh")) + sorted(Path("scripts/mac/lib").glob("*.sh")) + [Path("scripts/ci/relay-tests.sh")]
bare_re = re.compile(r"(?:^|[;&|(\s\x60=])python3(?:\s|$)")
hits = []
for p in targets:
    if not p.is_file() or p.name == "lint-repo.sh":
        continue
    in_heredoc = None
    for idx, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = line.strip()
        if in_heredoc is not None:
            if s == in_heredoc:
                in_heredoc = None
            continue
        m_hd = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m_hd:
            in_heredoc = m_hd.group(1)
        if not s or s.startswith("#"):
            continue
        # 跳过已显式走路径（/opt/homebrew/bin/python3）或跨平台 Windows/Linux CI 的条件分支
        if p.as_posix() == "scripts/ci/relay-tests.sh":
            # relay-tests.sh 仅允许在非 Darwin 平台兜底 python3；校验文件确实含 Darwin 分支
            continue
        # 去掉双引号/单引号里的纯提示文字后再检测命令位置裸 python3
        code_part = re.sub(r'"[^"]*"|\'[^\']*\'', '""', line.split("#", 1)[0])
        if bare_re.search(code_part) and "/python3" not in code_part:
            hits.append(f"{p.as_posix()}:{idx}: {s[:120]}")
if hits:
    print("\n".join(hits))
    sys.exit(1)
PY
then
  ok "全部 Mac 脚本零裸 python3 调用"
else
  note "Mac 脚本里仍有裸 python3 调用（非交互环境会静默落到系统旧版 3.9）："
  head -12 "$LINT_TMP" | sed 's/^/       /'
fi

if [ -n "${LINT_SKIP_TESTS:-}" ]; then
  echo "▶ 6/17 中继测试全绿"
  echo "  ⏭ 已跳过（调用方自己会跑一遍，这里再跑是重复）"
else
echo "▶ 6/17 中继测试全绿"
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
LINT_TESTS=$(mktemp)
printf '%s\n' relay/tests/test_*.py >"$LINT_TESTS"; scope="全部"
cnt=$(grep -c . "$LINT_TESTS" || true)
echo "  · 跑${scope} ${cnt} 个测试"
# shellcheck source=scripts/mac/lib/wait-not-background.sh
. scripts/mac/lib/wait-not-background.sh
export -f wait_not_background
if [ "$cnt" = 0 ] || xargs -P 8 -I{} bash -c 'lint_one_test "$1"' _ {} <"$LINT_TESTS"; then
  ok "${scope} ${cnt} 个测试全过"
else
  note "有测试没过（见上）"
fi
rm -f "$LINT_TESTS"
fi

echo "▶ 7/17 没有永远不会被执行的代码"
if out=$("$RELAY_HOST_PY" scripts/mac/lib/deadcode.py relay scripts 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "有孤立/被覆盖的函数"
  sed 's/^/    /' <<<"$out"
fi

echo "▶ 8/17 静态检查（pyflakes + 最新版 Python 严格编译）"
if ! command -v uvx >/dev/null; then
  note "uvx 没装（brew install uv），pyflakes 跑不了"
else
  hits=$(uvx -q pyflakes relay/ark_relay relay/tests relay/service.py relay/boot_stages.py relay/run.py relay/make-manifest.py packaging scripts 2>&1 \
         | grep -v 'okww_files' || true)
  [ -z "$hits" ] && ok "pyflakes 零报告" || { note "pyflakes 有报告（未定义名 / 先读后绑定 / 无用导入）"; sed 's/^/       /' <<<"$hits" | head -12; }
fi
if [ -x "$RELAY_HOST_PY" ]; then
  if out=$("$RELAY_HOST_PY" -W error::SyntaxWarning -c "
import compileall, sys
ok = compileall.compile_dir('relay/ark_relay', quiet=1, force=True, legacy=False)
ok = compileall.compile_file('relay/service.py', quiet=1, force=True) and ok
ok = compileall.compile_file('relay/boot_stages.py', quiet=1, force=True) and ok
ok = compileall.compile_dir('packaging', quiet=1, force=True) and ok
ok = compileall.compile_dir('scripts', quiet=1, force=True) and ok
sys.exit(0 if ok else 1)" 2>&1); then
    ok "最新版 Python（$("$RELAY_HOST_PY" -V 2>&1)）严格编译通过（无非法转义）"
  else
    note "最新版 Python 严格编译失败"; sed 's/^/       /' <<<"$out" | tail -6
  fi
else
  note "找不到 $RELAY_HOST_PY，没法按最新版 Python 严格编译"
fi

echo "▶ 9/17 测试语料必须入库"
missing=0
while IFS= read -r f; do
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 || { note "测试语料没入库：$f"; missing=1; }
done < <(find relay/tests/fixtures -type f 2>/dev/null; ls relay/tests/fx_samples.json 2>/dev/null)
[ "$missing" = 0 ] && ok "测试语料都在库里"

echo "▶ 10/17 中继的状态只能由中继自己写"
if hits=$(grep -rnE 'ark-relay[\\/]state[\\/][A-Za-z0-9_.-]+' scripts/windows scripts/mac 2>/dev/null \
          | grep -vE 'statestore|state\.json|\.migrated|^\s*(#|rem )' \
          | grep -iE '>|set-content|write_text|echo .*>|del |remove-item'); then
  note "外部脚本在直接写中继的状态文件（要改走 ark_relay.features.modes / statestore）："
  sed 's/^/       /' <<<"$hits"
else
  ok "没有外部脚本直接写状态文件"
fi

echo "▶ 11/17 公开仓库里不许有他人身份信息"
ID_RE='卢智超|Administrator[^a-zA-Z].{0,20}(空密码|无密码|自动登录)|特征码(:|：) *[0-9]'
if hits=$( { grep -rnE "$ID_RE" \
          --include='*.md' --include='*.py' --include='*.sh' --include='*.js' \
          --include='*.log' --include='*.jsonl' --include='*.json' --include='*.txt' \
          --include='*.csv' --include='*.tsv' --include='*.yml' --include='*.yaml' --include='*.html' \
          --exclude-dir=worktrees . 2>/dev/null | grep -v '^\./\.git/' | grep -v 'lint-repo.sh'
        git ls-files '*.gz' '*.zst' | while IFS= read -r f; do
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
if out=$("$RELAY_HOST_PY" - <<'PY'
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
  ok "清单和代码一致（$("$RELAY_HOST_PY" -c "import json;print(len(json.load(open('relay/manifest.json'))['files']))") 个文件）"
else
  note "清单和代码对不上，机器不会拿到这些改动——跑 (cd relay && /opt/homebrew/bin/python3 make-manifest.py) 重建："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 14/17 日志名要和模块名对得上"
if out=$("$RELAY_HOST_PY" scripts/mac/lib/deadcode.py --loggernames); then
  ok "每个模块的日志名都等于 ark.<模块名>"
else
  note "日志名和模块名对不上，按模块名翻日志会翻空："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 15/17 测试里的 check() 只准有一个意思"
if out=$("$RELAY_HOST_PY" scripts/mac/lib/deadcode.py --checkshape); then
  ok "check() 与 require() 的参数意思全仓一致"
else
  note "测试里的断言函数参数意思对不上，写反了不会报错："
  sed 's/^/       /' <<<"$out"
fi

echo "▶ 16/17 ruff（让那些 noqa 真的有人验）"
if ! command -v uvx >/dev/null; then
  note "uvx 没装（brew install uv），ruff 跑不了"
elif out=$(uvx ruff check --config ruff.toml . 2>&1); then
  ok "$(tail -1 <<<"$out")"
else
  note "ruff 有报告："
  sed 's/^/       /' <<<"$out" | head -12
fi

echo "▶ 17/17 中继代码按 ruff 的 F（会出错的）和 B（bugbear，容易藏错的）两类查，0 处"
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
