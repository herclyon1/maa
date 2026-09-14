#!/bin/bash
# Send one command to the running relay right now, the way the phone page does
# (ntfy live channel). `order.sh` writes the repo inbox, which the relay reads
# only at boot, before shutdown and on retry - so it is the "machine is off"
# path. This is the "machine is on" path.
#
#     scripts/mac/order-now.sh '{"action":"tacet_shots","on":false}'
#
# Topic and PIN come from the machine's .env (ARK_PHONE_TOPIC / ARK_PHONE_PIN),
# read over ssh so they never live in this repo. Verify the result in relay.log
# (「📱 手机指令 …」) - this script only proves ntfy accepted the message.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BODY="${1:?用法: order-now.sh '{\"action\":...}'}"
python3 -c "import json,sys; json.loads(sys.argv[1])" "$BODY"
CREDS="$("$HERE/winps.sh" '$e = Get-Content C:\ProgramData\ark-relay\.env; ($e | ? { $_ -match "^ARK_PHONE_TOPIC=" }) -replace "^ARK_PHONE_TOPIC=",""; ($e | ? { $_ -match "^ARK_PHONE_PIN=" }) -replace "^ARK_PHONE_PIN=",""' | tail -2 | tr -d '\r')"
TOPIC="$(echo "$CREDS" | sed -n 1p)"
PIN="$(echo "$CREDS" | sed -n 2p)"
[[ -n "$TOPIC" && -n "$PIN" ]] || { echo "✗ 机器 .env 里没有 ARK_PHONE_TOPIC / ARK_PHONE_PIN" >&2; exit 1; }
MSG="$(python3 -c 'import json,sys,time; print(json.dumps({"v":1,"kind":"cmd","pin":sys.argv[1],"ts":int(time.time()),"body":json.loads(sys.argv[2])}, ensure_ascii=False))' "$PIN" "$BODY")"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST --data-binary "$MSG" "https://ntfy.sh/$TOPIC")"
[[ "$code" == "200" ]] || { echo "✗ ntfy 回了 $code" >&2; exit 1; }
echo "▶ 已发到机器（ntfy $code）：$BODY —— 去 relay.log 看「📱 手机指令」"
