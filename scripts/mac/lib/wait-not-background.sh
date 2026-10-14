# shellcheck shell=bash
# Sourced by the Mac test runners (lint-repo.sh, deploy-relay.sh). wait_not_background blocks while
# macOS runs this process at background priority, which it does to every app's processes when a
# game is in front: runningboardd logged "[app<application.com.anthropic.claudefordesktop...>]
# Set darwin role to: Background" each time Game Mode turned on (10-14 19:40:44, 19:46:21,
# 19:47:31, 19:51:17). On this Mac's macOS 27.2 beta, starting programs from a background-priority
# process can lock the kernel (09-23 04:19 panic: the locking process was a background-priority
# grep in mid-exec; 10-14 19:52 the Mac froze 62 s after Claude went to the background while a
# lint run was starting about five test programs a second). A background-priority thread runs at
# scheduler priority 4, which is what ps shows; anything above 4 means the game is not in front.
# Outside macOS it returns at once.
# Poll every 30 s. Measured: on 10-14 the background spells lasted 56 s to 2 min 56 s (runningboardd
# log 19:40:44-19:42:55, 19:46:21-19:47:17, 19:47:31-19:50:27), so 30 s resumes within about half of the
# shortest one and costs one ps every 30 s while waiting.
wait_not_background() {
  [ "$(uname -s)" = Darwin ] || return 0
  local p said=""
  while p=$(ps -o pri= -p $$ 2>/dev/null) && p=${p// /} && [ -n "$p" ] && [ "$p" -le 4 ]; do
    if [ -z "$said" ]; then
      echo "  · macOS put this run at background priority (a game is in front); waiting until it is not" >&2
      said=1
    fi
    # Measured: 10-14 background spells lasted 56 s to 2 min 56 s (see the note above the function).
    sleep "${WAIT_BG_POLL_S:-30}"
  done
}
