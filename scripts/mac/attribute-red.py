# -*- coding: utf-8 -*-
"""attribute-red.py — S6 (BOARD SPEED2-summary): put every red row of a headless accept run on someone, without re-running.
usage: attribute-red.py [--base <sha>] [--ref <name>=<sha>]... [--register <file>] [--board <BOARD.md>] <accept-output.txt>...
For each ✗ line of the outputs (accept-run.py's format: "✗ <item> | <got> （要 <expect>）"):
  1. the row is located in web/accept*.js by its literal fragments (the most fragments matched wins; ≥ 2 needed); for a row of accept.js the
     nearest preceding sec("…") gives the section;
  2. the file / section maps to a control and its owner (OWNERS below — the file ownership of BOARD/OPEN.md);
  3. the verdict:
     归 <owner>        the batch (base..HEAD) touched that control's own files (its accept file or the control's page files);
     疑 <shared file>   the batch touched a shared page file (tokens.css / view.js / index.html / motion.js / accept.js loader) and not the control's
                        own files — the row goes to whoever merged that shared change (the --ref whose diff has it);
     记录不判           nobody touched anything that can reach the row → it is recorded in the register (A16) and NOT re-run, NOT messaged;
     未定位             the row's text is in no accept file (a runner / loader line) → shown for the merger.
The register line: "| <time> | <batch sha> | <theme> | <control> | <item ≤ 100> | <got> |". A row already in the register (or in an A16 row of BOARD.md,
quoted in 「…」) is marked 已记 and not appended again. Exit code: 0 always (attribution is a report, not a gate)."""
import sys, os, re, subprocess, time, glob
W = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OWNERS = {  # control: (owner, page files that only this control uses)
    'motion': ('界面', ['web/motion.js', 'web/motion.css']),
    'nav': ('老网页', ['web/nav.js', 'web/nav.css']),
    'nav-edge': ('老网页', ['web/nav-edge.js']),
    'sheet': ('界面', ['web/sheet.js', 'web/sheet.css']),
    'menu': ('2号', ['web/menu.js', 'web/menu.css']),
    'topbar': ('数据', ['web/topbar.js', 'web/topbar.css']),
    'refresh': ('界面', ['web/refresh.js', 'web/refresh.css']),
    'glassbtn': ('界面', ['web/glassbtn.js', 'web/glassbtn.css']),
    'alert': ('2号', ['web/alert-glass.js', 'web/alert-glass.css', 'web/alert-prewarm.js']),
    'switch': ('界面', ['web/switch.js', 'web/switch.css']),
    'tabbar': ('2号', ['web/assets/lens/tab-lens.js', 'web/assets/lens/lens-webgl.js']),
    'tile': ('界面', ['web/tile.css']),
    'segctl': ('界面', ['web/controls.js', 'web/controls.css', 'web/seg-keys.css', 'web/seg-frames-logger.js', 'web/assets/lens/']),
    'cell': ('界面', ['web/view.js']),
    'page': ('界面', ['web/view.js', 'web/live.js', 'web/pending.js', 'web/stamina.js', 'web/inventory.js', 'web/net.js', 'web/schema.js']),
    'core': ('验收', ['web/accept.js']),
}
SHARED = ['web/tokens.css', 'web/view.js', 'web/index.html', 'web/motion.js', 'web/accept.js', 'web/sw.js', 'web/controls.css']
args = sys.argv[1:]; base = None; refs = []; register = os.environ.get('ACCEPT_REGISTER', os.path.expanduser('~/Money/styl-work/BOARD/A16-register.md'))
board = os.path.expanduser('~/Money/styl-work/BOARD.md'); files = []
while args:
    a = args.pop(0)
    if a == '--base': base = args.pop(0)
    elif a == '--ref': refs.append(args.pop(0).split('=', 1))
    elif a == '--register': register = args.pop(0)
    elif a == '--board': board = args.pop(0)
    else: files.append(a)
def git(*a):
    try: return subprocess.check_output(['git', '-C', W] + list(a), text=True, stderr=subprocess.DEVNULL)
    except Exception: return ''
head = git('rev-parse', '--short', 'HEAD').strip()
changed = set(git('diff', '--name-only', base, 'HEAD').split()) if base else set()
by_ref = {}
for name, sha in refs:
    by_ref[name] = set(git('diff', '--name-only', base, sha).split()) if base else set()
# the accept sources, with their sec() positions
SRC = {}
for p in sorted(glob.glob(os.path.join(W, 'web', 'accept*.js'))):
    SRC[os.path.relpath(p, W)] = open(p, encoding='utf-8').read()
def section_at(src, pos):
    cur = 'core'
    for m in re.finditer(r'sec\("([a-z-]+)"', src[:pos]): cur = m.group(1)
    return cur
def fragments(item):
    # literal pieces an author would have typed: split at digits / ${ } / spaces / brackets, keep ≥ 3 chars
    return [f for f in re.split(r'[\d\s${}()（）:：|/,，;；=+×±≤≥.…→\-–—«»"“”\'`]+', item) if len(f) >= 3]
def locate(item):
    fr = fragments(item); best = (0, None, None)
    for path, src in SRC.items():
        hits = [f for f in fr if f in src]
        if len(hits) > best[0]:
            pos = src.find(hits[0]) if hits else -1
            best = (len(hits), path, pos)
    n, path, pos = best
    if n < 2 or path is None: return None, None
    ctrl = 'accept.js' if path.endswith('/accept.js') else re.sub(r'^web/accept-|\.js$', '', path)
    if ctrl == 'accept.js': ctrl = section_at(SRC[path], pos)
    return path, ctrl
def known(item):
    quoted = set()
    for src in (board, register):
        try: txt = open(src, encoding='utf-8').read()
        except Exception: continue
        for line in txt.splitlines():
            if src == board and 'A16' in line: quoted.update(re.findall(r'「([^」]{6,})」', line))          # BOARD.md: only the A16 rows' quoted items
            elif src == register and line.startswith('| ') and line.count('|') >= 7: quoted.add(line.split('|')[5].strip())   # the register's 行 cell
    return any(q[:10] in item for q in quoted if q)
def owner_of_shared(f):
    for name, fs in by_ref.items():
        if f in fs: return name
    return '本批某 ref'
out = []; reg_lines = []
for fpath in files:
    theme = 'dark' if 'dark' in os.path.basename(fpath) else 'light'
    try: lines = open(fpath, encoding='utf-8').read().splitlines()
    except Exception: continue
    for line in lines:
        if not line.startswith('✗'): continue
        body = line[1:].strip(); item = body.split(' | ')[0].strip(); got = body.split(' | ', 1)[1].strip() if ' | ' in body else ''
        path, ctrl = locate(item)
        if path is None: out.append(f'未定位 · {theme} · {item[:100]} | {got[:60]}'); continue
        owner, own_files = OWNERS.get(ctrl, ('?', []))
        touched = [f for f in changed if f == path or any(f == o or (o.endswith('/') and f.startswith(o)) for o in own_files)]
        shared = [f for f in changed if f in SHARED and f not in touched]
        already = known(item)
        if touched: verdict = f'归 {owner}（本批改了 {", ".join(sorted(touched))[:80]}）'
        elif shared: verdict = f'疑 {", ".join(sorted(shared))[:60]}（{owner_of_shared(sorted(shared)[0])} 合入）→ 归改它的人；{ctrl} 自身未动'
        else:
            verdict = '记录不判' + ('（已记）' if already else '（新记入 A16 表）')
            if not already: reg_lines.append(f'| {time.strftime("%m-%d %H:%M")} | {head} | {theme} | {ctrl} | {item[:100]} | {got[:60]} |')
        out.append(f'{verdict} · {theme} · {ctrl} · {item[:100]} | {got[:60]}')
if reg_lines:
    new = not os.path.exists(register)
    with open(register, 'a', encoding='utf-8') as f:
        if new: f.write('# A16 记录不判（attribute-red.py 自动追加：红行所在控件本批无人改 → 记下不复跑不发信；作者改成确定性判法后删行）\n\n| 时间 | 批次 | 主题 | 控件 | 行 | 读到 |\n|---|---|---|---|---|---|\n')
        f.write('\n'.join(reg_lines) + '\n')
print('\n'.join(out) if out else '红行：无')
if reg_lines: print(f'记入 A16 表 {len(reg_lines)} 行 → {register}')
