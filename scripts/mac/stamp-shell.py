# -*- coding: utf-8 -*-
"""stamp-shell.py <webdir> [<v>] — one release stamp on every shell URL of the phone page (T4, BOARD WORKLIST).
Every `?v=…` in index.html (scripts, stylesheets, manifest, icons; the view.js loader strings too), the icons inside
manifest.webmanifest, and sw.js's CACHE name become `?v=<v>` / "ark-remote-v<v>". deploy-web.sh and export-web.sh
both call this, so the local export the phone tests run and the real release carry the same stamp (an unstamped
`?v=0` URL is served from the HTTP cache forever: the 2026-09-20 morning sweep ran the old shell).
Exit 1 if any `?v=0` survives or if a file has no stamp to replace."""
import pathlib, re, sys, time
web = pathlib.Path(sys.argv[1]); v = sys.argv[2] if len(sys.argv) > 2 else time.strftime("%Y%m%d%H%M%S")
if not re.fullmatch(r"[0-9A-Za-z_.-]+", v): raise SystemExit("bad stamp " + v)
idx = web / "index.html"; s = idx.read_text(encoding="utf-8")
pat = re.compile(r'(\.(?:js|css|png|svg|webmanifest))\?v=[0-9A-Za-z_.-]*')
n = len(pat.findall(s)); s2 = pat.sub(lambda m: f"{m.group(1)}?v={v}", s)
if n == 0: raise SystemExit("✗ index.html: no ?v= to stamp")
idx.write_text(s2, encoding="utf-8")
man = web / "manifest.webmanifest"; nm = 0
if man.exists():
    t = man.read_text(encoding="utf-8"); t2, nm = re.subn(r'"((?:icon-\d+\.png|icon\.svg))[^"]*"', rf'"\1?v={v}"', t)
    if nm == 0: raise SystemExit("✗ manifest.webmanifest: icon stamps not found")
    man.write_text(t2, encoding="utf-8")
sw = web / "sw.js"; ns = 0
if sw.exists():
    t = sw.read_text(encoding="utf-8"); t2, ns = re.subn(r'const CACHE = "ark-remote-v[0-9A-Za-z_.-]*"', f'const CACHE = "ark-remote-v{v}"', t)
    if ns == 0: raise SystemExit("✗ sw.js: CACHE name not found")
    sw.write_text(t2, encoding="utf-8")
left = re.findall(r'[\w./-]+\?v=0\b', s2)
if left: raise SystemExit("✗ still ?v=0: " + " ".join(left))
print(f"  版本号 v={v}：index.html {n} 个 URL、manifest 图标 {nm}、sw.js CACHE {ns}")
