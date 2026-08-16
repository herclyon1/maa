#!/bin/bash
# Record memory pressure over time, so "should I exchange this Mac for more RAM"
# gets answered with a week of evidence instead of one snapshot. sysctl only
# ever reports the current value, and the peak is gone the moment it passes.
#
# Deliberately no osascript here: asking System Events for the frontmost app
# blocks for the full timeout when accessibility is not granted, which turned a
# sub-second sampler into a two-minute one.
LOG="$HOME/Library/Logs/mem-pressure.csv"
[ -f "$LOG" ] || echo "时间,swap已用MB,压缩内存MB,空闲%" > "$LOG"
SW=$(sysctl -n vm.swapusage | sed -E 's/.*used = ([0-9.]+)M.*/\1/')
CM=$(vm_stat | awk '/stored in compressor/ {gsub(/\./,"",$5); print int($5*16384/1048576)}')
FP=$(memory_pressure 2>/dev/null | awk '/free percentage/ {gsub(/%/,"",$NF); print $NF}')
printf '%s,%s,%s,%s\n' "$(date '+%Y-%m-%d %H:%M')" "${SW:-0}" "${CM:-0}" "${FP:-0}" >> "$LOG"
