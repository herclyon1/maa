# -*- coding: utf-8 -*-
"""webclip_stamp.py <export-dir> [V]: apply deploy-web.sh's version-stamping step (the python block, copied verbatim in spirit — same
regexes) to an exported web/ directory, without the gh-pages push. Prints the stamp and the count of remaining ?v=0 references."""
import pathlib, re, sys, time
d = pathlib.Path(sys.argv[1]); v = sys.argv[2] if len(sys.argv) > 2 else time.strftime('%Y%m%d%H%M%S')
p = d / 'index.html'; s = p.read_text(encoding='utf-8')
s = re.sub(r'<script src="(schema|net|pending|live|stamina|inventory|view|controls|alert-prewarm|seg-frames-logger|motion|nav|nav-edge|sheet|menu|topbar|refresh|glassbtn|alert-glass|switch|accept-[a-z-]+|accept)\.js\?v=[^"]*"', lambda m: f'<script src="{m.group(1)}.js?v={v}"', s)
s = re.sub(r'controls\.css\?v=[^"]*', f'controls.css?v={v}', s)
s = re.sub(r'(motion|nav|sheet|menu|topbar|refresh|glassbtn|alert-glass|switch|tile)\.css\?v=[^"]*', lambda m: f'{m.group(1)}.css?v={v}', s)
s = re.sub(r'accept\.js\?v=[^"]*', f'accept.js?v={v}', s)
s = re.sub(r'view\.js\?v=\d+', f'view.js?v={v}', s)
s = re.sub(r'assets/lens/(tab-lens|lens-webgl)\.js\?v=[^"]*', lambda m: f'assets/lens/{m.group(1)}.js?v={v}', s)
s = re.sub(r'tokens\.css\?v=[^"]*', f'tokens.css?v={v}', s)
s = re.sub(r'href="manifest\.webmanifest[^"]*"', f'href="manifest.webmanifest?v={v}"', s)
s = re.sub(r'href="(apple-touch-icon|icon-\d+)\.png[^"]*"', rf'href="\1.png?v={v}"', s)
m = d / 'manifest.webmanifest'
if m.exists():
    t = m.read_text(encoding='utf-8'); t = re.sub(r'"(icon-\d+\.png|icon\.svg)[^"]*"', rf'"\1?v={v}"', t); m.write_text(t, encoding='utf-8')
p.write_text(s, encoding='utf-8')
left = re.findall(r'[\w./-]+\?v=0"', s)
print('stamp', v, '| remaining ?v=0:', left[:10], '| stamped refs:', len(re.findall(re.escape(f'?v={v}'), s)))
