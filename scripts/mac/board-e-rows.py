#!/usr/bin/env python3
"""BOARD E rows from commits (SPEED-summary 二 6: the E section is generated, not hand-written).
Usage: python3 board-e-rows.py [worktree] [since=YYYY-MM-DD HH:MM]  → prints one E-format row per non-merge commit not on main:
| 件 | 合入时间 | 无头亮 / 暗 | 用户看哪里（Change 行前 120 字） | 疑点（Unread 行前 120 字） |  — fill 无头 counts by hand after the batch run."""
import subprocess, re, sys, os
W = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
SINCE = sys.argv[2] if len(sys.argv) > 2 else '2026-09-19 22:50'
S = os.path.dirname(os.path.abspath(__file__))
def git(*a): return subprocess.run(['git', '-C', W, *a], capture_output=True, text=True).stdout
log = git('log', '--no-merges', '--reverse', '--format=%h%x1f%ad%x1f%s%x1f%b%x1e', '--date=format:%m-%d %H:%M', '--since=' + SINCE, 'main..night')
rows = []
for rec in log.split('\x1e'):
    rec = rec.strip('\n')
    if not rec.strip(): continue
    h, d, subj, body = (rec.split('\x1f') + ['', '', '', ''])[:4]
    files = git('show', '--pretty=', '--name-only', h).split()
    item = re.search(r'\((?:BOARD )?(#?[R0-9①②③′″‴⁗a-z]+)\)', subj)
    item = item.group(1) if item else ''
    ctrl = sorted({os.path.basename(f).split('.')[0] for f in files if f.startswith('web/') and not f.startswith('web/accept')})
    def pick(key):
        m = re.search(r'(?im)^' + key + r'[:：]\s*(.+?)(?=\n\S+[:：]|\n\n|\Z)', body, re.S)
        return re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''
    rows.append(dict(h=h, d=d, item=item, subj=subj, ctrl=', '.join(ctrl), root=(pick('Basis') or pick('Root cause')), fix=pick('Change'), cost=pick('Acceptance'), ifnot=(pick('Unread') or pick('If not done')), files=files))
for r in rows:
    print(f"| {r['item']} {r['ctrl']} | {r['d'][6:]} | 亮 ?/? · 暗 ?/? | {r['fix'][:120]} | {r['ifnot'][:120]} |")
print(f"# {len(rows)} commits since {SINCE}", file=sys.stderr)
