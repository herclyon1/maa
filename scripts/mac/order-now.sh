#!/bin/bash
# Send one command to the running relay right now, the way the phone page does
# (ntfy live channel). `order.sh` writes the repo inbox, which the relay reads
# only at boot, before shutdown and on retry - so it is the "machine is off"
# path. This is the "machine is on" path.
#
#     scripts/mac/order-now.sh '{"action":"tacet_shots","on":false}'
#
# Topic and PIN come from the Mac's ~/.config/ark/push.env (ARK_PHONE_TOPIC /
# ARK_PHONE_PIN; index: ~/.config/ark/密钥总表.md) - the same pair the relay
# reads from its own .env on the machine. They never live in this repo, and the
# machine does not have to be on to read them. Verify the result in relay.log
# (「📱 手机指令 …」) - this script only proves ntfy accepted the message.
set -euo pipefail
BODY="${1:?用法: order-now.sh '{\"action\":...}'}"
python3 -c "import json,sys; json.loads(sys.argv[1])" "$BODY"
ENV="$HOME/.config/ark/push.env"
TOPIC="$(sed -n 's/^ARK_PHONE_TOPIC=//p' "$ENV" 2>/dev/null | tail -1 | tr -d '\r')"
PIN="$(sed -n 's/^ARK_PHONE_PIN=//p' "$ENV" 2>/dev/null | tail -1 | tr -d '\r')"
[[ -n "$TOPIC" && -n "$PIN" ]] || { echo "✗ $ENV 里没有 ARK_PHONE_TOPIC / ARK_PHONE_PIN——按 ~/.config/ark/密钥总表.md 补上" >&2; exit 1; }
MSG="$(python3 -c 'import json,sys,time; print(json.dumps({"v":1,"kind":"cmd","pin":sys.argv[1],"ts":int(time.time()),"body":json.loads(sys.argv[2])}, ensure_ascii=False))' "$PIN" "$BODY")"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST --data-binary "$MSG" "https://ntfy.sh/$TOPIC")"
[[ "$code" == "200" ]] || { echo "✗ ntfy 回了 $code" >&2; exit 1; }
echo "▶ 已发到机器（ntfy $code）：$BODY —— 去 relay.log 看「📱 手机指令」"

# "Don't shut down" must also stop a power-off that has already begun. 10-09 22:42:35 this
# order reached the relay about 20 s into its `shutdown /s /t 60` countdown; the relay only
# stored it for the *next* shutdown and the machine went off at 22:43. So for skip_shutdown
# (not the cancel form) abort any countdown in progress. The relay has the flag by now, so
# its next pass eats it instead of powering off again. Exit 1116 = no shutdown was pending.
if python3 -c 'import json,sys; b=json.loads(sys.argv[1]); sys.exit(0 if b.get("action")=="skip_shutdown" and not b.get("off") and b.get("on") is not False else 1)' "$BODY"; then
  sleep 8
  out="$("$(dirname "$0")/winps.sh" 'shutdown /a 2>$null; "exit=$LASTEXITCODE"' 2>&1 | tr -d '\r' | grep -o 'exit=[0-9]*' | tail -1)"
  case "$out" in
    exit=0)    echo "▶ 机器正在关机倒数，已当场叫停（shutdown /a）" ;;
    exit=1116) echo "▶ 机器没有在关机，不用叫停" ;;
    *)         echo "✗ 叫停关机没拿到结果（${out:-机器没回}）——马上用 winps.sh 看机器还在不在" >&2; exit 1 ;;
  esac
fi
