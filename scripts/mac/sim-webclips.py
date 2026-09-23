#!/usr/bin/env python3
"""sim-webclips.py [A|B|C|D|UDID] [PORT]: the home-screen web clips of ONE simulator — look here before adding one.

Every clip is Library/WebClips/<id>.webclip (Info.plist Title / URL) and, when it is on the home screen, its <id> sits in
Library/SpringBoard/IconState.plist. Without PORT: one line per clip — id, title, URL, home-screen page / slot (or 「not in layout」),
and who is listening on its port right now (pid + cwd, or 「no server」). With PORT: print the id of the clip whose URL is on that port
and exit 0, or exit 1 when there is none.

Reuse rule (用户 2026-09-24 01:57「还要留下了复用的啊」, BOARD A52 one resident clip per simulator): before adding a clip through
Safari, run this with your port; if a clip on that port exists, serve to it (webclip-serve.sh looks it up the same way) and do not add
another. Clips are never deleted by a script; a clip nobody serves any more is listed to 验收, who decides.
"""
import os
import plistlib
import subprocess
import sys
from urllib.parse import urlsplit

SIMS = {
    'A': '8E793B8A-922B-46BC-86E2-E0F2BE845CA5',
    'B': 'C9827365-571F-4440-9844-6A44BC8D972A',
    'C': '2DD13EF2-E283-4730-B663-E1F4B88C31AE',
    'D': 'A759965B-F818-4573-9FB2-43FFF0E593C1',
}


def layout(lib):
    """{id: 'page P slot S' or 'page P folder <name>'} from IconState.plist."""
    where = {}
    try:
        with open(os.path.join(lib, 'SpringBoard', 'IconState.plist'), 'rb') as f:
            st = plistlib.load(f)
    except OSError:
        return where
    for p, page in enumerate(st.get('iconLists', [])):
        for s, e in enumerate(page):
            if isinstance(e, str):
                where[e] = f'page {p + 1} slot {s + 1}'
            elif isinstance(e, dict):
                for sub in e.get('iconLists', []):
                    for x in sub:
                        if isinstance(x, str):
                            where[x] = f'page {p + 1} folder {e.get("displayName", "?")}'
    return where


def listener(port):
    if not port:
        return 'no port'
    pid = subprocess.run(['lsof', '-tiTCP:%d' % port, '-sTCP:LISTEN'], capture_output=True, text=True).stdout.split()
    if not pid:
        return 'no server'
    cwd = subprocess.run(['lsof', '-p', pid[0], '-a', '-d', 'cwd', '-Fn'], capture_output=True, text=True).stdout
    cwd = next((l[1:] for l in cwd.splitlines() if l.startswith('n')), '?')
    return f'pid {pid[0]} cwd {cwd}'


def clips(udid):
    lib = os.path.expanduser(f'~/Library/Developer/CoreSimulator/Devices/{udid}/data/Library')
    where = layout(lib)
    d = os.path.join(lib, 'WebClips')
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith('.webclip'):
            continue
        cid = name[:-len('.webclip')]
        try:
            with open(os.path.join(d, name, 'Info.plist'), 'rb') as f:
                info = plistlib.load(f)
        except OSError:
            continue
        url = info.get('URL', '')
        yield cid, info.get('Title', ''), url, urlsplit(url).port, where.get(cid, 'not in layout')


def main():
    args = sys.argv[1:]
    dev = args.pop(0) if args and not args[0].isdigit() else 'A'
    udid = SIMS.get(dev, dev)
    port = int(args[0]) if args else None
    rows = list(clips(udid))
    if port is not None:
        hit = [r for r in rows if r[3] == port]
        for r in hit:
            print(r[0])
        if not hit:
            print(f'no clip on port {port} on {udid} — add one in Safari (Share › Add to Home Screen), then reuse it', file=sys.stderr)
        return 0 if hit else 1
    print(f'{udid}: {len(rows)} web clips')
    for cid, title, url, p, pos in rows:
        print(f'  {cid}  {title!r:12} {url:40} {pos:24} {listener(p)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
