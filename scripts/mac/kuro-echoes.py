#!/usr/bin/env python3
"""Which of my characters wear which echo set, straight from the Kuro BBS account.

Why this exists: a bag echo belongs to nobody, and the scorer needs a character because the
weights are per character. The account knows which characters actually have a set equipped,
which is the honest answer to "who are these for" - no guessing from set names.

Kuro BBS only ever exposes *equipped* echoes. Nothing here can see the bag.

**A token on its own is not enough: it is bound to the did that was sent when it was issued.**
XutheringWavesUID's own login makes one up (`did = str(uuid.uuid4()).upper()`) and hands it to
the login call, so the pair is what authenticates, not the token alone. Measured 2026-09-10:
with the real token and an *invented* did, every /aki/roleBox/* endpoint answers
`10901 禁止访问` under source h5, ios and android alike - while /gamer/role/list and
/encourage/signIn/initSignInV2 answer 200 on the same token in the same second. So 10901 is
"wrong device", not "no permission" and not "expired".

Both values have to come from the **phone app**, not from www.kurobbs.com. The web session
stores no did at all - the only long ids in its localStorage are analytics (`distinct_id` is
Sensors Analytics, `HMACCOUNT` is Baidu Tongji) - and the web token draws 10901 from the data
box with did empty, absent, or set to anything. XutheringWavesUID's own tutorial
(维里奈.com/kurobbs.html) says the same: capture the app's 角色卡 request with ProxyPin and
read `did` and `token` out of the ~1.3 KB packet. Put that pair in .env as KUROBBS_TOKEN and
KUROBBS_DID.

A wrong header reads exactly like a dead credential: with source "ios" the same live token
answers 「登录已过期，请重新登录」. Match the header to where a token came from before ever
telling anyone their credential expired.

The token comes from ~/.config/ark/.env (KUROBBS_TOKEN), the same private file the push
credentials live in - never the repo, never a CLI argument. KUROBBS_DID is optional: the
account endpoints accept a synthetic devCode, and only requestToken is picky about it, so a
missing did is reported as such rather than silently producing an empty report.

The endpoints, headers and payloads below were read out of XutheringWavesUID's own API layer
(utils/api/api.py and utils/api/requests.py), not guessed:

    POST /gamer/role/list          headers token + devCode      -> roleId, serverId
    POST /aki/roleBox/requestToken headers token + did          -> accessToken, used as b-at
    POST /aki/roleBox/akiBox/roleData     headers did + b-at    -> owned characters
    POST /aki/roleBox/akiBox/getRoleDetail headers did + b-at   -> equipped echoes per character

    scripts/mac/kuro-echoes.py            report by character and by set
    scripts/mac/kuro-echoes.py --json     the same data as JSON
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

MAIN = "https://api.kurobbs.com"
GAME_ID = 3
SERVER_ID = "76402e5b20be2c39f095a152090afddc"
ENV = pathlib.Path.home() / ".config" / "ark" / ".env"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko)  KuroGameBox/3.1.3")
# The token in .env was copied out of a logged-in www.kurobbs.com session, so it is an h5
# token. Presented with source "ios" every call answers 「登录已过期，请重新登录」 - which
# reads exactly like an expired token and is not one. Measured 2026-09-10: the same token,
# same second, source "h5" + version returns real data. Match the header to where the token
# came from before ever concluding that a credential died.
SOURCE = "h5"
KURO_VERSION = "3.1.3"


def post(path: str, headers: dict, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    head = {"source": SOURCE, "version": KURO_VERSION, "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
    head.update(headers)
    req = urllib.request.Request(MAIN + path, data=body, headers=head, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def need(resp: dict, what: str):
    """Kuro answers 200 with code!=200 on failure, so the HTTP layer never raises."""
    if not resp.get("success") or resp.get("code") != 200:
        msg = resp.get("msg") or resp.get("message") or json.dumps(resp, ensure_ascii=False)
        sys.exit(f"✗ {what}失败：{msg}")
    return resp.get("data")


def main() -> None:
    env = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    token = env.get("KUROBBS_TOKEN", "")
    if not token:
        sys.exit(f"✗ {ENV} 里没有 KUROBBS_TOKEN。")
    did = env.get("KUROBBS_DID", "")
    if not did:
        sys.exit(f"✗ {ENV} 里没有 KUROBBS_DID。\n"
                 "  token 是和签发它的那台设备绑在一起的，少了设备号，数据坞那组接口\n"
                 "  一律回「禁止访问」（实测：编一个假的也是这个结果）。\n"
                 "  在登录着库街区的浏览器控制台里跑那行取 did 的命令，取到写进同一个文件。")

    roles = need(post("/gamer/role/list", {"token": token, "devCode": did},
                      {"gameId": GAME_ID}), "取账号下的角色")
    waves = [r for r in roles if int(r.get("gameId", 0)) == GAME_ID]
    if not waves:
        sys.exit("✗ 这个账号下没有鸣潮的角色。")
    role_id = str(waves[0]["roleId"])
    server_id = waves[0].get("serverId") or SERVER_ID
    print(f"账号 {waves[0].get('roleName', '?')}  UID {role_id}")

    bat = need(post("/aki/roleBox/requestToken",
                    {"token": token, "did": did, "b-at": ""},
                    {"serverId": server_id, "roleId": role_id}),
               "换取数据令牌")["accessToken"]
    box = {"did": did, "b-at": bat}
    base = {"gameId": GAME_ID, "serverId": server_id, "roleId": role_id}

    chars = need(post("/aki/roleBox/akiBox/roleData", box, base), "取共鸣者列表")["roleList"]
    print(f"共鸣者 {len(chars)} 个，逐个读已装备的声骸…\n")

    by_char: dict[str, list[str]] = {}
    by_set: dict[str, list[str]] = defaultdict(list)
    for i, c in enumerate(chars, 1):
        name = c.get("roleName", str(c["roleId"]))
        detail = post("/aki/roleBox/akiBox/getRoleDetail", box,
                      {**base, "channelId": "19", "countryCode": "1", "id": c["roleId"]})
        data = detail.get("data") or {}
        phantoms = ((data.get("phantomData") or {}).get("equipPhantomList")) or []
        sets = [p["fetterDetail"]["name"] for p in phantoms
                if p and p.get("fetterDetail", {}).get("name")]
        by_char[name] = sets
        for s in set(sets):
            by_set[s].append(f"{name}×{sets.count(s)}")
        print(f"  [{i}/{len(chars)}] {name}", end="\r", flush=True)
        time.sleep(0.4)  # the account API is not a bulk endpoint; do not hammer it
    print(" " * 40, end="\r")

    if "--json" in sys.argv:
        print(json.dumps({"by_character": by_char, "by_set": dict(by_set)},
                         ensure_ascii=False, indent=2))
        return

    print("── 每个套装被谁在用 ──")
    for s, who in sorted(by_set.items(), key=lambda kv: -len(kv[1])):
        print(f"  {s}: {'、'.join(who)}")
    print("\n── 每个共鸣者身上是什么套装 ──")
    for name, sets in by_char.items():
        if not sets:
            continue
        counted = "、".join(f"{s}×{sets.count(s)}" for s in dict.fromkeys(sets))
        print(f"  {name}: {counted}")
    bare = [n for n, s in by_char.items() if not s]
    if bare:
        print(f"\n  没装声骸的：{'、'.join(bare)}")


if __name__ == "__main__":
    main()
