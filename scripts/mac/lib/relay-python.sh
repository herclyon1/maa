#!/usr/bin/env bash
# Prints the Python that runs the relay's tests and tools on the Mac.
#
# The relay runs on the game machine under Python 3.14 (relay/requirements.txt,
# packaging/build.py PY_VERSION). Until 2026-10-12 the Mac ran its tests with the
# bare `python3`, i.e. macOS's own /usr/bin/python3 = 3.9.6, although 3.14 has been
# installed at ~/.local/bin/python3.14 since 08-23: tests passed on a Python the relay
# never runs on, and ruff's B905 (zip strict=, 3.10+) had to stay off. User 10-12
# 08:21: the newest Python is installed on this Mac, yet the system one was used.
#
# So: a virtualenv on that installed 3.14 (the interpreter itself is not touched),
# shared by every worktree (it lives in the main checkout, gitignored), holding
# relay/requirements.txt plus the test-only packages. Built on first use, rebuilt
# when its interpreter or requirements change. Exits non-zero, printing why, when no
# 3.14 is installed - callers stop instead of falling back to /usr/bin/python3.
set -euo pipefail

PY314="${RELAY_PY314:-$HOME/.local/bin/python3.14}"
if [ ! -x "$PY314" ]; then
  echo "relay-python: $PY314 not found; install Python 3.14 (uv python install 3.14), never fall back to /usr/bin/python3" >&2
  exit 3
fi
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
common=$(git -C "$here" rev-parse --path-format=absolute --git-common-dir)
venv="${RELAY_VENV:-$(dirname "$common")/.venv-relaytest}"
# numpy: relay/tests image fixtures (test_desktop_*), not a relay runtime dependency.
want="$(grep -vE '^\s*(#|$)' "$here/relay/requirements.txt" | grep -v 'sys_platform == "win32"' | sort | tr '\n' ' ')numpy|$("$PY314" -V 2>&1)"

if [ ! -x "$venv/bin/python" ] || [ "$(cat "$venv/.want" 2>/dev/null)" != "$want" ]; then
  command -v uv >/dev/null || { echo "relay-python: uv not installed (brew install uv)" >&2; exit 3; }
  lock="$venv.lock"
  # Several worktrees run lint at once: one builds, the others wait for it.
  while ! mkdir "$lock" 2>/dev/null; do sleep 1; done
  trap 'rmdir "$lock" 2>/dev/null || true' EXIT
  if [ ! -x "$venv/bin/python" ] || [ "$(cat "$venv/.want" 2>/dev/null)" != "$want" ]; then
    uv venv -q --clear --python "$PY314" "$venv" >&2
    grep -vE '^\s*(#|$)' "$here/relay/requirements.txt" | grep -v 'sys_platform == "win32"' \
      | uv pip install -q --python "$venv/bin/python" -r /dev/stdin numpy >&2
    printf '%s' "$want" > "$venv/.want"
  fi
fi
echo "$venv/bin/python"
