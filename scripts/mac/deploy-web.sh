#!/usr/bin/env bash
# 把 web/ 发到 GitHub Pages（gh-pages 分支）。
#
# 为什么要盖版本号：2026-08-31 手机上连着好几次拿的都是缓存里的旧 app.js，
# 我按修好的代码去判断，得出的结论全是错的——排查了半天，真因只是
# 「页面根本没在跑新代码」。每次发布都给 <script src> 换一个新的 ?v=，
# 浏览器就没有旧版可拿。
#
# **图标也要盖**：2026-09-04 换了 apple-touch-icon 和 icon-192，文件是新的，
# 可 index.html 里的 ?v= 还是上一次那个数，手机上拿到的仍是缓存里的旧图标。
# 已经加到主屏的 PWA 更顽固，它认的就是那个 URL。凡是带 ?v= 的链接一律盖。
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
# 图标：<link rel="...icon..." href="xxx.png?v=...">，连 manifest 里的一起盖
s = re.sub(r'href="(apple-touch-icon|icon-\d+)\.png[^"]*"', rf'href="\1.png?v={v}"', s)

m = pathlib.Path("web/manifest.webmanifest")
if m.exists():
    t = m.read_text(encoding="utf-8")
    # [^"?]* 只能匹配「还没盖过版本号」的那次：盖过一次之后串里有了 ?，
    # 排除 ? 就再也匹配不上，于是第二次起永远盖不上——手机上拿到的是缓存里的旧图标。
    before = t
    t = re.sub(r'"(icon-\d+\.png|icon\.svg)[^"]*"', rf'"\1?v={v}"', t)
    if t == before:
        raise SystemExit("✗ manifest 的图标版本号没盖上，检查正则")
    m.write_text(t, encoding="utf-8")
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
# 版本号是写进被跟踪文件里的，不提交的话 main 的工作树永久是脏的，
# git status 就再也不能用来判断「我有没有没提交的活」。
if ! git -C "$HERE" diff --quiet -- web/; then
  git -C "$HERE" add web/ \
    && git -C "$HERE" commit -q -m "发布手机页 $V" \
    && echo "▶ 版本号已提交（$V）" \
    || { echo "✋ 版本号提交失败，工作树还是脏的" >&2; exit 9; }
fi
# 推完不等于发布好了。GitHub Pages 要重新构建，一两分钟内取到的还是上一版——
# 这是整套部署里最后一条「推完就宣布成功」的路（2026-09-08 审出来）。
# 中继那条早就是「哈希核对 + 服务确认 RUNNING」才算完，这条也得实测。
echo "▶ 等 Pages 真的发出新版本"
python3 - "$V" <<'PY'
import sys, time, urllib.request
v = sys.argv[1]
url = "https://herclyon1.github.io/maa/index.html"
for i in range(1, 21):                      # 最多等 100 秒
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "replace")
    except Exception as e:                  # noqa: BLE001
        print(f"  [{i}/20] 取不到：{type(e).__name__}")
    else:
        if f"app.js?v={v}" in html:
            print(f"✅ 手机页已经在发 v={v}（实测取回来核对过）")
            print("   https://herclyon1.github.io/maa/ 手机上直接刷新即可，不用清缓存。")
            raise SystemExit(0)
        print(f"  [{i}/20] 还是旧版")
    time.sleep(5)
print("⚠️ 等了 100 秒，Pages 还在发旧版。代码推上去了，但**手机上此刻拿到的还是上一版**。")
print("   再等几分钟自己刷新页面核对，或重跑本脚本。")
raise SystemExit(1)
PY
