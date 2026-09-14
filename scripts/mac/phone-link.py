#!/usr/bin/env python3
"""Print the phone page's free-login link with the game credentials on it.

The link is `#k=<mailbox + PIN>&t=<game credentials>`: the page reads the
fragment once, stores both in the phone's localStorage, and strips it from the
address bar (web/app.js fromLink, web/stamina.js fromLink). Nothing after `#` is
sent to any server, and nothing is written here - the link goes only to your
screen. Asked for by the user on 2026-09-15 so that nothing has to be pasted on the phone.

Sources: the mailbox topic/PIN from the machine's .env (ARK_PHONE_TOPIC / ARK_PHONE_PIN,
read over ssh like order-now.sh) or `--topic/--pin`; KUROBBS_TOKEN / KUROBBS_DID
from ~/.config/ark/.env. The Skland session is not made here: the relay hands it
to the page in the snapshot (relay/ark_relay/resources.skland_session), because
Skland rate-limits cred creation and one process already holds one.
"""
import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = Path.home() / ".config" / "ark" / ".env"
PAGE = "https://herclyon1.github.io/maa/"


def env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def machine_mailbox() -> tuple[str, str]:
    """ARK_PHONE_TOPIC and ARK_PHONE_PIN from the machine .env, read the way order-now.sh does."""
    ps = ('$e = Get-Content C:\\ProgramData\\ark-relay\\.env; '
          '($e | ? { $_ -match "^ARK_PHONE_TOPIC=" }) -replace "^ARK_PHONE_TOPIC=",""; '
          '($e | ? { $_ -match "^ARK_PHONE_PIN=" }) -replace "^ARK_PHONE_PIN=",""')
    r = subprocess.run([str(HERE / "winps.sh"), ps], capture_output=True, text=True, timeout=120)
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise SystemExit("机器上的 .env 读不到 ARK_PHONE_TOPIC / ARK_PHONE_PIN（机器开着吗？）")
    return lines[-2], lines[-1]


def b64(o: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(o, ensure_ascii=False).encode("utf-8")).decode().rstrip("=")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--topic", help="mailbox topic (default: read from the machine)")
    ap.add_argument("--pin", help="mailbox PIN (default: read from the machine)")
    a = ap.parse_args()
    topic, pin = (a.topic, a.pin) if a.topic and a.pin else machine_mailbox()
    e = env_file(ENV)
    tok: dict = {}
    if e.get("KUROBBS_TOKEN") and e.get("KUROBBS_DID"):
        tok["kuro"] = {"token": e["KUROBBS_TOKEN"], "did": e["KUROBBS_DID"]}
    else:
        print(f"{ENV} 里没有 KUROBBS_TOKEN / KUROBBS_DID，链接里不带鸣潮的", file=sys.stderr)
    link = f"{PAGE}#k={b64({'t': topic, 'p': str(pin)})}" + (f"&t={b64(tok)}" if tok else "")
    print("打开一次就全存进那台手机（信箱、PIN、库街区密钥）；森空岛的会话机器开机后自己交：")
    print(link)


if __name__ == "__main__":
    main()
