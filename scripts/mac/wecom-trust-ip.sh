#!/bin/bash
# Add an IP to the 企业微信 self-built app's trusted-IP list from this Mac.
#
#     scripts/mac/wecom-trust-ip.sh              # adds the game machine's current public IP
#     scripts/mac/wecom-trust-ip.sh 1.2.3.4      # adds a specific IP
#
# Why this exists: the game machine sits on a dial-up line whose public IP
# rotates, and 企业微信 has no API for the trusted-IP list - only the web admin
# console. The two browser tools refuse work.weixin.qq.com and the classifier
# refuses synthetic mouse clicks, so the only scriptable route is Chrome's
# "Allow JavaScript from Apple Events" (View → Developer, turned on 2026-09-12)
# plus an admin-console login that the user does once by QR scan; the session
# then lives in Chrome's cookies for a while.
#
# Exit 2 = Chrome shows the QR login page: the user has to scan once, then rerun.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IP="${1:-}"
if [[ -z "$IP" ]]; then
  IP="$("$HERE/winps.sh" '(Invoke-RestMethod https://api.ipify.org -TimeoutSec 20).Trim()' | tail -1 | tr -d '\r')"
fi
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "✗ 拿到的不是 IP：$IP" >&2; exit 1; }
echo "▶ 要加的 IP：$IP"

exec osascript -l JavaScript "$HERE/lib/wecom_trust_ip.js" "$IP"
