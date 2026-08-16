#!/bin/bash
# Record memory pressure over time, so "should I exchange this Mac for more RAM"
# gets answered with a week of evidence instead of one snapshot. sysctl only
# ever reports the current value, and the peak is gone the moment it passes.
#
# Records the top memory consumers rather than the frontmost app. The frontmost
# app is rarely the one holding the memory - a background browser with forty
# tabs outweighs whatever window happens to be in focus - and reading it needs
# accessibility permission, which made the sampler block for its full timeout.
# `ps` needs nothing and answers the more useful question.
LOG="$HOME/Library/Logs/mem-pressure.csv"
[ -f "$LOG" ] || echo "时间,swap已用MB,压缩内存MB,空闲%,内存占用前三" > "$LOG"
SW=$(sysctl -n vm.swapusage | sed -E 's/.*used = ([0-9.]+)M.*/\1/')
CM=$(vm_stat | awk '/stored in compressor/ {gsub(/\./,"",$5); print int($5*16384/1048576)}')
FP=$(memory_pressure 2>/dev/null | awk '/free percentage/ {gsub(/%/,"",$NF); print $NF}')
# rss is in KB; collapse helper processes into their parent app so one browser
# does not fill all three slots with renderers.
TOP=$(ps -Ao rss,comm | tail -n +2 | awk '
  { name=$2
    sub(/.*\//,"",name)
    sub(/ Helper.*/,"",name)
    mem[name] += $1 }
  END { for (n in mem) printf "%d %s\n", mem[n], n }' |
  sort -rn | head -3 |
  awk '{ printf "%s%s %dMB", (NR>1 ? " / " : ""), $2, $1/1024 }')
printf '%s,%s,%s,%s,%s\n' "$(date '+%Y-%m-%d %H:%M')" "${SW:-0}" "${CM:-0}" "${FP:-0}" "${TOP:-?}" >> "$LOG"
