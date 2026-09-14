#!/bin/bash
# Prove on the machine that the live gathering-route watcher works end to end:
# feed the real 2026-09-14 failure lines into maafw.log, expect the master to
# narrow to Route10 and to be restored at the retry's start line, then undo.
#
#     ARK_HOST=100.65.39.119 scripts/mac/collect-watch-drill.sh
#
# Sends one real 「🔁 自动采集：这一轮重跑只走没走通的路线」 notification (that is
# the point - the whole chain runs). Refuses while MaaEnd or the game is up.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# winrun --ps ships the script as a file; winps.sh inlines it into one command
# line and this one (with its 330-char log lines) is over the 8 KB limit.
exec "$HERE/winrun.sh" --timeout 180 --ps "$(cat "$HERE/lib/collect_watch_drill.ps1")"
