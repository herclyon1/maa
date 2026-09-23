#!/bin/sh
# sim-webclean.sh [UDID|A|B|C|D] [--dry]: close every leftover web process on ONE simulator after a run (BOARD A52, 2026-09-23:
# ~35 WebKit processes of 150–260 MB each were left on the host by finished tests, one simulator held 4.3 GB).
#   1. `simctl terminate` the web hosts: Safari (com.apple.mobilesafari), home-screen clips (com.apple.webapp), in-app Safari
#      (com.apple.SafariViewService);
#   2. SIGTERM whatever com.apple.WebKit.WebContent / .GPU / .Networking process is still a child of THIS simulator's launchd_sim
#      (found by the device UDID in launchd_sim's argv, so other simulators' processes are never touched), wait 2 s, SIGKILL survivors;
#   3. print what was closed and the RSS freed, then list anything web-ish still running (should be nothing).
# Default device = simulator A. Letters: A 8E793B8A…, B C9827365…, C 2DD13EF2…, D A759965B… (BOARD A52 table).
case "${1:-A}" in
  A) UDID=8E793B8A-922B-46BC-86E2-E0F2BE845CA5 ;;
  B) UDID=C9827365-571F-4440-9844-6A44BC8D972A ;;
  C) UDID=2DD13EF2-E283-4730-B663-E1F4B88C31AE ;;
  D) UDID=A759965B-F818-4573-9FB2-43FFF0E593C1 ;;
  --dry) UDID=8E793B8A-922B-46BC-86E2-E0F2BE845CA5 ;;
  *) UDID=$1 ;;
esac
DRY=; for a in "$@"; do [ "$a" = --dry ] && DRY=1; done
LD=$(pgrep -f "launchd_sim .*/Devices/$UDID/" | head -1)
[ -n "$LD" ] || { echo "sim-webclean: $UDID not booted (no launchd_sim) — nothing to close"; exit 0; }
webkids() { ps -Ao pid=,ppid=,rss=,command= | awk -v p="$LD" '$2==p && /com\.apple\.WebKit\.(WebContent|GPU|Networking)/ {print $1, $3}'; }
before=$(webkids); nb=$(printf '%s\n' "$before" | grep -c .); kb=$(printf '%s\n' "$before" | awk '{s+=$2} END {print s+0}')
echo "sim-webclean $UDID (launchd_sim $LD): $nb WebKit processes, $((kb / 1024)) MB before"
[ -n "$DRY" ] && { printf '%s\n' "$before" | head -50; exit 0; }
for b in com.apple.mobilesafari com.apple.webapp com.apple.SafariViewService; do
  xcrun simctl terminate "$UDID" "$b" > /dev/null 2>&1 && echo "  terminated $b"
done
sleep 1
left=$(webkids | awk '{print $1}')
[ -n "$left" ] && { kill -TERM $left 2> /dev/null; sleep 2; left=$(webkids | awk '{print $1}'); [ -n "$left" ] && kill -KILL $left 2> /dev/null; sleep 0.5; }
after=$(webkids); na=$(printf '%s\n' "$after" | grep -c .); ka=$(printf '%s\n' "$after" | awk '{s+=$2} END {print s+0}')
echo "  after: $na WebKit processes, $((ka / 1024)) MB (freed $(((kb - ka) / 1024)) MB)"
[ "$na" -eq 0 ] || { echo "  still running:"; printf '%s\n' "$after"; exit 1; }
