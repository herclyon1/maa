#!/bin/bash
# check-shell.sh <url|port> [nofetch] — the deployed (or locally served) phone page carries ONE shell stamp (T4):
#   • every ?v= in index.html is the same stamp and not 0;  • sw.js's CACHE name carries that stamp;
#   • sw.js's SHELL list has every css/js index.html loads (accept.js excluded: test only);  • each shell URL answers 200.
# Prints each offending item; exit 1 on any. A bare port means http://127.0.0.1:<port>/.
set -uo pipefail
U="${1:?url or port}"; [[ "$U" =~ ^[0-9]+$ ]] && U="http://127.0.0.1:$U/"; [[ "$U" == */ ]] || U="$U/"
NOFETCH="${2:-}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
curl -fsS -H 'Cache-Control: no-cache' "${U}index.html" -o "$T/index.html" || { echo "✗ 取不到 ${U}index.html"; exit 1; }
curl -fsS -H 'Cache-Control: no-cache' "${U}sw.js" -o "$T/sw.js" || { echo "✗ 取不到 ${U}sw.js"; exit 1; }
python3 - "$T" "$U" "$NOFETCH" <<'PY'
import re, sys, pathlib, urllib.request
t, u, nofetch = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
idx = (t / "index.html").read_text(encoding="utf-8"); sw = (t / "sw.js").read_text(encoding="utf-8")
bad = []
urls = re.findall(r'([\w./-]+\.(?:js|css|png|svg|webmanifest))\?v=([0-9A-Za-z_.-]*)', idx)
stamps = {}
for f, v in urls: stamps.setdefault(v, set()).add(f)
if len(stamps) != 1: bad.append("戳不一致：" + " | ".join(f"v={v}: {' '.join(sorted(fs))}" for v, fs in stamps.items()))
v = next(iter(stamps)) if len(stamps) == 1 else None
if v in (None, "", "0"): bad.append(f"戳无效 v={v!r}")
m = re.search(r'const CACHE = "ark-remote-v([0-9A-Za-z_.-]*)"', sw)
if not m: bad.append("sw.js 没有 CACHE 名")
elif v and m.group(1) != v: bad.append(f"sw.js CACHE 戳 {m.group(1)} ≠ 页面戳 {v}")
shell = set(re.findall(r'"([\w./-]+\.(?:js|css|html))"', sw))
need = {f for f, _ in urls if f.endswith((".js", ".css")) and not f.startswith("accept")}
miss = sorted(need - shell)
if miss: bad.append("sw SHELL 缺：" + " ".join(miss))
if not nofetch and v:
    for f in sorted({f for f, _ in urls}):
        try:
            r = urllib.request.Request(u + f + "?v=" + v, method="HEAD", headers={"Cache-Control": "no-cache"}); urllib.request.urlopen(r, timeout=10)
        except Exception as e: bad.append(f"取不到 {f}?v={v}（{e}）")
print(f"页面戳 v={v} · {len(urls)} 个壳 URL · sw SHELL {len(shell)} 项" + ("" if nofetch else " · 逐个 HEAD 已核"))
for b in bad: print("✗ " + b)
sys.exit(1 if bad else 0)
PY
