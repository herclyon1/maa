#!/usr/bin/env python3
"""Print the phone page's free-login link with the game credentials on it.

The link is `#k=<mailbox + PIN>&t=<game credentials>`: the page reads the
fragment once, stores both in the phone's localStorage, and strips it from the
address bar (web/app.js fromLink, web/stamina.js fromLink). Nothing after `#` is
sent to any server, and nothing is written here - the link goes only to your
screen. Asked for by the user on 2026-09-15 so that nothing has to be pasted on the phone.

Sources: the mailbox topic/PIN from the machine's .env (ARK_PHONE_TOPIC / ARK_PHONE_PIN,
read over ssh like order-now.sh) or `--topic/--pin`; KUROBBS_TOKEN / KUROBBS_DID
and SKLAND_TOKEN from ~/.config/ark/.env. For Skland this script does the one step
a browser cannot (token -> code -> cred on as.hypergryph.com, which sends no CORS
headers) and puts the session (cred, signing token, device id, account ids) on
the link; from then on the page refreshes its own signing token. Skland creates
creds sparingly - run this when the link is needed, not in a loop. `--no-skland`
skips it.
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
    ap.add_argument("--no-skland", action="store_true", help="leave the Skland session off the link")
    a = ap.parse_args()
    topic, pin = (a.topic, a.pin) if a.topic and a.pin else machine_mailbox()
    e = env_file(ENV)
    tok: dict = {}
    if e.get("KUROBBS_TOKEN") and e.get("KUROBBS_DID"):
        tok["kuro"] = {"token": e["KUROBBS_TOKEN"], "did": e["KUROBBS_DID"]}
    else:
        print(f"{ENV} 里没有 KUROBBS_TOKEN / KUROBBS_DID，链接里不带鸣潮的", file=sys.stderr)
    if e.get("SKLAND_TOKEN") and not a.no_skland:
        sys.path.insert(0, str(HERE.parent.parent / "relay"))
        from ark_relay import skland  # noqa: PLC0415
        try:
            did = skland.get_did()
            cred = skland.refresh(skland.login(e["SKLAND_TOKEN"], did))
            sk = {"cred": cred.cred, "token": cred.token, "dId": did}
            for app in skland.bindings(cred):
                if app.get("appCode") == "arknights":
                    for b in app.get("bindingList", []):
                        if b.get("uid") and "uid" not in sk:
                            sk["uid"] = str(b["uid"])
            # Endfield wants roles[].roleId / serverId - uid + channelMasterId only earn a 403
            try:
                sk["efRole"], sk["efServer"] = skland.endfield_role(cred)
            except Exception as exc:  # noqa: BLE001 - no Endfield binding: the tile says so
                print(f"终末地角色没找到：{exc}", file=sys.stderr)
            tok["sk"] = sk
        except Exception as exc:  # noqa: BLE001 - the link is still useful without Skland
            print(f"森空岛这次没登上（{type(exc).__name__}: {exc}），链接里不带它；等会儿再跑一次", file=sys.stderr)
    elif not a.no_skland:
        print(f"{ENV} 里没有 SKLAND_TOKEN，链接里不带森空岛的", file=sys.stderr)
    link = f"{PAGE}#k={b64({'t': topic, 'p': str(pin)})}" + (f"&t={b64(tok)}" if tok else "")
    print("打开一次就全存进那台设备（信箱、PIN、库街区密钥、森空岛会话）：", file=sys.stderr)
    print(link)


if __name__ == "__main__":
    main()
