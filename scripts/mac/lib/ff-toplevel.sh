#!/usr/bin/env bash
# Bring the repository's shared top-level checkout up to origin/main, when that is safe.
#
#   scripts/mac/lib/ff-toplevel.sh <any path inside the repository>
#
# The top-level checkout (the main worktree, ~/Claude/maa-automation) is what other
# sessions and the user's own tools run from: estop.sh, okww-check.sh and the rest. Every
# change reaches main through a worktree and a push, and nothing moved the top-level
# checkout along - on 10-11 it sat 359 commits behind, with an estop.sh that did not know
# the installed relay. deploy-relay.sh runs this after its push.
#
# Only a fast-forward, only on main, only with no uncommitted changes to tracked files;
# anything else is printed and left alone - never a stash, never a reset (the house rules,
# ~/Claude/CLAUDE.md safety rule 4). Always exits 0: the deploy is done by then.
set -uo pipefail

top=$(git -C "${1:?usage: ff-toplevel.sh <path inside the repository>}" worktree list --porcelain 2>/dev/null \
      | sed -n '1s/^worktree //p')
if [ -z "$top" ]; then
  echo "  top-level checkout: not found from $1, nothing done"
  exit 0
fi
behind=$(git -C "$top" rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
if [ "$behind" = 0 ]; then
  echo "  top-level checkout $top: already at origin/main"
  exit 0
fi
branch=$(git -C "$top" symbolic-ref -q --short HEAD || true)
if [ "$branch" != main ]; then
  echo "  ⚠️ top-level checkout $top is on ${branch:-a detached HEAD}, not main ($behind behind origin/main): left alone"
  exit 0
fi
if [ -n "$(git -C "$top" status --porcelain --untracked-files=no)" ]; then
  echo "  ⚠️ top-level checkout $top has uncommitted changes ($behind behind origin/main): left alone, no stash, no reset"
  exit 0
fi
if out=$(git -C "$top" merge -q --ff-only origin/main 2>&1); then
  echo "  top-level checkout $top: fast-forwarded $behind commits to origin/main"
else
  echo "  ⚠️ top-level checkout $top: fast-forward refused, left as it was:"
  printf '%s\n' "$out" | head -5 | sed 's/^/       /'
fi
exit 0
