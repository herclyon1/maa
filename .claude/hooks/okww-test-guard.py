#!/usr/bin/env python3
"""Game-patch change guard: a commit that changes how the relay drives OK-WW / MaaEnd / MAA must change a behaviour test with it, and may not grow the untested exemption lists."""
import json, os, re, subprocess, sys
WATCH = re.compile(r'^relay/ark_relay/(okww_files/|okww_patches/|okww_\w+\.py$|maaend\.py$|collector_\w+\.py$|outcome\.py$|'
                   r'weeklyboss\.py$|wuwa_\w+\.py$|echofarm\.py$|annihilation\.py$|garden\.py$|mastercfg\.py$|preupdate_\w+\.py$|plan\.py$)')
TESTS = re.compile(r'^relay/tests/')
COMMIT = re.compile(r'(?:^|[;&|(\n]|&&)\s*git\b(?:\s+-C\s+(\S+))?[^\n;&|]*\bcommit\b')
def staged(d):
    out = subprocess.run(['git', '-C', d, 'diff', '--cached', '--name-only'], capture_output=True, text=True, timeout=5).stdout
    return [l for l in out.splitlines() if l]
def exemption_growth(d, files):
    """New lines in relay/tests/untested-baseline.txt or new PATCH_NO_TRIGGER entries in outcome.py."""
    out = []
    for f in files:
        if f.endswith('untested-baseline.txt') or f.endswith('ark_relay/outcome.py'):
            diff = subprocess.run(['git', '-C', d, 'diff', '--cached', '-U0', '--', f], capture_output=True, text=True, timeout=5).stdout
            added = [l[1:].strip() for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++')]
            removed = {l[1:].strip() for l in diff.splitlines() if l.startswith('-') and not l.startswith('---')}
            if f.endswith('.txt'):
                new = [a for a in added if a and not a.startswith('#') and a not in removed]
            else:
                new = [a for a in added if a.startswith('PATCH_NO_TRIGGER') or (re.match(r'"\w+\.\w+":\s*"only', a) and a not in removed)]
            if new:
                out.append(f + ' adds ' + '; '.join(new[:3]))
    return '，'.join(out)


def ours(d):
    url = subprocess.run(['git', '-C', d, 'remote', 'get-url', 'origin'], capture_output=True, text=True, timeout=3).stdout
    return bool(re.search(r'herclyon1/maa(\.git)?\s*$|maa-automation', url))
def main():
    try: d = json.load(sys.stdin)
    except Exception: return 0
    cmd = (d.get('tool_input') or {}).get('command') or ''
    m = COMMIT.search(cmd)
    if not m: return 0
    dirs = [m.group(1)] if m.group(1) else re.findall(r'\bcd\s+([^\s;&|]+)', cmd) or [d.get('cwd') or '.']
    for x in dirs:
        x = os.path.expanduser(x.strip('\'"'))
        try:
            if not ours(x): continue
            files = staged(x)
        except Exception:
            continue
        grow = exemption_growth(x, files)
        if grow:
            print(json.dumps({'decision': 'block', 'reason':
                'Blocked: this commit adds entries to the untested exemption list: ' + grow +
                '. The weekly-boss failure came from registering a path as never-triggered (09-13). Write a behaviour test instead.'}, ensure_ascii=False))
            return 0
        if any(WATCH.search(f) for f in files) and not any(TESTS.search(f) for f in files):
            print(json.dumps({'decision': 'block', 'reason':
                'Blocked: this commit changes relay code that drives or judges OK-WW / MaaEnd / MAA but changes no behaviour test under relay/tests/. '
                'Every screen and path needs a test built from a real screenshot or log that passes before and after the change; add it, then commit.'}, ensure_ascii=False))
            return 0
    return 0
if __name__ == '__main__':
    sys.exit(main())
