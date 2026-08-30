#!/usr/bin/env bash
# 把 web/ 发到 GitHub Pages（gh-pages 分支）。
#
# 为什么要盖版本号：2026-08-31 手机上连着好几次拿的都是缓存里的旧 app.js，
# 我按修好的代码去判断，得出的结论全是错的——排查了半天，真因只是
# 「页面根本没在跑新代码」。每次发布都给 <script src> 换一个新的 ?v=，
# 浏览器就没有旧版可拿。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WT="${TMPDIR:-/tmp}/ark-ghpages"

cd "$HERE"
V="$(date +%Y%m%d%H%M%S)"
python3 - "$V" <<'PY'
import pathlib, re, sys
v = sys.argv[1]
p = pathlib.Path("web/index.html")
s = p.read_text(encoding="utf-8")
s = re.sub(r'<script src="app\.js[^"]*"></script>', f'<script src="app.js?v={v}"></script>', s)
s = re.sub(r'href="manifest\.webmanifest[^"]*"', f'href="manifest.webmanifest?v={v}"', s)
p.write_text(s, encoding="utf-8")
print(f"  版本号 v={v}")
PY

rm -rf "$WT"
git worktree prune
git worktree add -q "$WT" gh-pages
find "$WT" -maxdepth 1 ! -name .git ! -path "$WT" -exec rm -rf {} +
cp web/* "$WT"/
touch "$WT/.nojekyll"
(cd "$WT" && git add -A && git commit -q -m "发布 $V" && git push -q origin gh-pages)
git worktree remove --force "$WT"
echo "✅ 已发布：https://herclyon1.github.io/maa/"
echo "   等 1~2 分钟生效；手机上直接刷新即可，不用清缓存。"
