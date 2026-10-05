#!/usr/bin/env python3
"""Full relay suite guard: run only the test files you touched; the whole suite, changed_covered.py, guardcheck.sh and test_replay.py run once, at merge time, with MERGE_FULL_SUITE=1."""
import json, re, sys
EXEC = re.compile(r'(?:^|[;&|(]\s*|\b(?:bash|sh|zsh|python3?|env)\s+(?:-\S+\s+)*|\./)[\w./~-]*(?:changed_covered\.py|guardcheck\.sh|test_replay\.py)')
PYTEST = re.compile(r'(?:^|[;&|(]\s*|\s)(?:python3?\s+-m\s+)?pytest\b([^;&|\n]*)')


def full(cmd):
    """True when the command executes a whole-suite script, or runs pytest over relay without naming a test file / -k."""
    if EXEC.search(cmd):
        return True
    for m in PYTEST.finditer(cmd):
        args = m.group(1)
        if re.search(r'\.py\b|\s-k\s|::', args):
            continue
        if 'relay' in cmd or re.search(r'(^|\s)tests/?(\s|$)', args):
            return True
    return False


def main():
    try:
        cmd = (json.load(sys.stdin).get('tool_input') or {}).get('command', '')
    except Exception:
        return 0
    if 'MERGE_FULL_SUITE=1' in cmd or not full(cmd):
        return 0
    print('Blocked: run only the test files you touched (pytest relay/tests/test_x.py). The whole suite, changed_covered.py, guardcheck.sh and test_replay.py run once at merge time: prefix MERGE_FULL_SUITE=1.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
