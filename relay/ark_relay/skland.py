"""Skland (Hypergryph's official community) client: reads Endfield character progression.

**Why we need it**: we can see what the game farmed, but not "how far a
character is trained and what is still missing". Skland is the official
community, the account data is right there, and it is far more reliable than
reading it off screenshots.

**Where the credential comes from** (supplied by the user, 2026-08-27): log in
to skland.com in a browser, then open
`https://web-api.skland.com/account/info/hg`; `data.content` in the returned
JSON is the token. It is **equivalent to the account login credential**, it
lives only in the machine's `.env` (this repo is public and `.env` is the first
line of `.gitignore`), and it must never appear in any log or report.

**The token expires**, so this is built as an automatic chain: token -> code ->
cred, and cred can be renewed via `/api/v1/auth/refresh`; only when all of that
fails do we go back to a person. The user's own words were
「你最好这东西搞个自动化，我记得token会过期的」.

**Signing**: every request carries `sign`:

    secret = path + query + timestamp + json({platform,timestamp,dId,vName})
    sign   = MD5(HMAC-SHA256(cred.token, secret))     # the second digest is MD5, not SHA256

Pitfalls hit on 2026-08-27 - all three were wrong at once, which is what made it
a 403:

* `platform` must be **"3"**, not "1".
* `vName` must be **"1.0.0"**, not an empty string.
* `serverId` comes from `bindingList[].roles[].serverId`, **not
  `channelMasterId`**.

Any of these gets the same HTTP 403 `{"code":10001,"message":"操作失败，请稍后重试"}`,
and **it does not tell you what is wrong**. The control case is Arknights'
`/api/v1/game/player/info`, which goes through first try with the same signing -
so "is the signature correct" was the wrong line of investigation from the start.

Timestamps have to be aligned with the server: first `GET /web/v1/auth/refresh`
(which needs no sign) to get `timestamp`, record the offset from local time, and
from then on send `server time + local elapsed` on every request. Reusing the
raw timestamp from the moment of the refresh for any length of time is rejected
as 「请勿修改设备本地时间」 (10003).

Endpoint source: otae-1204/otae-bot-entari `docs/skland_endfield_personal_api.md`
(reverse-engineered 2026-07, re-checked 2026-08-19, with a measured code:0 record
for every endpoint).
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

log = logging.getLogger("ark.skland")

_UA = ("Skland/1.32.1 (com.hypergryph.skland; build:103201004; "
       "Android 33; ) Okhttp/4.11.0")
_HEADERS = {"User-Agent": _UA, "Accept-Encoding": "gzip", "Connection": "close"}
# The Endfield endpoints insist on exactly these two values; see the module docstring.
_SIGN_KEYS = {"platform": "3", "timestamp": "", "dId": "", "vName": "1.0.0"}

SKLAND_APP_CODE = "4ca99fa6b56cc2ba"     # Skland's appCode, used to exchange for a code
GRANT_URL = "https://as.hypergryph.com/user/oauth2/v2/grant"
ZONAI = "https://zonai.skland.com"
CRED_URL = "https://zonai.skland.com/api/v1/user/auth/generate_cred_by_code"
REFRESH_URL = "https://zonai.skland.com/web/v1/auth/refresh"
BINDING_URL = "https://zonai.skland.com/api/v1/game/player/binding"
ENDFIELD_CARD_URL = "https://zonai.skland.com/api/v1/game/endfield/card/detail"
ENDFIELD_CHAR_URL = "https://zonai.skland.com/api/v1/game/endfield/card/char"

_TIMEOUT = 20


class SklandError(RuntimeError):
    """An API error. **Never carries credential content** - exceptions end up in the log."""


@dataclass
class Cred:
    cred: str
    token: str
    userId: str = ""
    dId: str = ""
    """Device fingerprint. **Must belong to the same session as the cred**: whichever
    one was used when exchanging for the cred has to be used on every request
    afterwards (refresh included), and it has to be the one inside the signature.
    Measured 2026-08-27: leave dId out of the cred exchange and refresh answers
    「设备信息无效」 straight away."""

    def __repr__(self) -> str:          # keeps credentials from being logged by accident
        return (f"Cred(userId={self.userId!r}, cred=<hidden>, token=<hidden>, "
                f"dId={'<有>' if self.dId else '<空>'})")


def _read(resp) -> dict:
    """Read a response. The request headers carry Accept-Encoding: gzip (copied
    from the upstream implementation) and urllib does not decompress on its own -
    the very first call hit exactly that:
    `'utf-8' codec can't decode byte 0x8b`, and 0x8b is the gzip magic number.
    Decide from the actual Content-Encoding; do not assume."""
    raw = resp.read()
    if resp.headers.get("Content-Encoding", "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _post(url: str, payload: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**_HEADERS, "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return _read(r)


def _get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return _read(r)


# ── Device fingerprint (dId) ───────────────────────────────────
# The `/web/v1/` endpoints (Endfield lives among them) reject requests without a
# dId: measured 2026-08-27, sending only `sign` is turned away with a 403 whose
# body is {"code":10001,"message":"操作失败，请稍后重试"} - **it does not tell you
# what is missing**. Control case: Arknights' /api/v1/game/player/info goes
# through first try with the same signing, so the problem is not the signature,
# it is that these web endpoints additionally require a device fingerprint.
#
# The three constants below are taken verbatim from api/dId.py in
# FrostN0v0/nonebot-plugin-skland (the only publicly available implementation).
# They are a fixed device-profile payload that is exchanged for a deviceId.
V4_URL = "https://fp-it.portal101.cn/deviceprofile/v4"
V4_DATA = (
    "4ac13cbe759d757cf4fd5465233024db2b7ae6bfbddd6d2d3eb964b246b2d4c3a8405b1601c3f3cc556257bd2784bfa6"
    "c1021bed1e5509f24c229ae2366cccbe7d4bcc6fc9ab0a188743be5ed737e74b04bece1f2add13bbf5295378527eed932"
    "1a220bc16cf5224f4a955802cec68927542796a1d9f74b9430461e6428561a9768c2fec228f702742280c441985f19a29"
    "c5cef8bf360acf290953544a33c72488e1ea5531c74ae09cfdb4db1f2c85d7c25b28eb31e749f576f36c564f7376f4dd1"
    "aefc00b668e45eea9431850c2af1fe1c7bf1a640dd4640f72da023482884c317a911075a5d48b10473348997adab48ebd"
    "ca8b9c0679c1bcd24c178d18d580091b1543059a358734a5ec562b5516d625ae2eba740951429b18cd4f5bcbb43671b97"
    "253257825003d9ef191c1583025de213e051767c6d37cc6cd9af051cb7baaed79d6515a6d305038f87f3bc4fdb27e2e4e"
    "9f945d4147cecd87a34b55051eb371e3c52370e6d2ae4e05ca5832383bfa09d81cf8ab2a61dddcf1e71716a49cd19771e"
    "f0e0a1265130cbfc9a5c8809ef62a5ff701587d6fa2f84c67f3e11ce5df940ad97bb8e9eb0ec688fe152c6c0b520b58a4"
    "a3a54b39281ccac5c09853fe0de373c25ad2f26085f9163ef16bb51d42b622e16ee7fb7c16cff10da11f981ac973a9d2f"
    "7d37a1a845fdbf3ad0377c8b01d46e4372b900fd07dde79030c74649906e28d219a723958adc45bf870cba074612a5408"
    "2360df1c4f59114728f965c98176d216da23573f57b11cf8ccffdb6443f81c83977e7fe9fbcba9a4497a02aede5dd647f"
    "742551614fb84d848d36f032ea3e9096ead45932c0e7e45d3a9e4fb95533b7f84d0b0d4ec85042e0dc94aa4c2670864b9"
    "f8073fd650cafbea88860288c35f89b608a6b8b2d6f5a49a270c5f9ce7e4ca06e1ecd0ad3a57091413f53f34b2fbf9b5e"
    "143706d1542d5f40fd9deeabc74df26acdd8b273ab1ad9811ba55b4466129c465e88897d01c9e7b27bc4025b66a5d63dd"
    "61dee1b4c86cff1e9fb88153a541dba90968f70800142f876568e50f4c7f44c56555e9f9dcdce3984518c5bb10f8a8153"
    "f879a0bbb032b881eb81baf0c669536e929896d3171323fd7078fb4a490ce282c6f685d92fbd98b9b905de7ac36f44328"
    "cb4419139396b1d47b056e17e9798a9e80c5126c15f462810b1c7895794dd3efc2d6f90bf4f1c062dc3501b65bf41df03"
    "7b79ab4c833ab1e6608567565e01d87357634ba09079658fdf80ee8a9a0df051a05a2047f05f0264b729cf7eba81d004b"
    "3a707c9d43c90549c1ce5b470ba51bb32373bd6dd73c3fd1b6e857e62d1ddc64778cc1e95a9936214ac79d036f663ceea"
    "8eaf069a708c744daeb185d9da3355b36a03aec25468d14a8f43e1e0e058c72e5564c4a9f25af8519750a781430998994"
    "038ce6206cf45ba094a87ffa8c003c24875c804a611515a94be79baa2341de97ae16daac9bb28a0327420701f4241bd162"
    "0bcefd1e6b190b9f35881c3860146facbbbc40c51c57fa83c8eda711c79eaffbc2c74376d0a7f8159f864487ed1e16d29"
    "ca68c2e007bdb98d09a0a6af0070874537f759de1168615b7cbd9f2c9aac0440f8e7bcd9d6fa4bdcc7d157a59612df796"
    "3cee5600"
)
V4_EP = (
    "Pd6g1a45vL1Y34ssEr8chqwLtuB3FmAR7c5QiRVwJl6QbhfubFJ6pJwt8jIOk1G+MMNBZDrT+QYM3D2ruR/4qCit24oLYDQVk"
    "B619CtNVToVp3epdI+Vs+83TzC4TqDXU18jGqMQJgA3f+GIwMWduJpCh+Tm26BiBdasrIE3I2w="
)
ORG_ID = "UWXspnCCJN4sfYlNfqps"




_did_cache = ""


def get_did() -> str:
    """Fetch the device fingerprint. Cached for the session - do not request one per call."""
    global _did_cache  # noqa: PLW0603
    if _did_cache:
        return _did_cache
    payload = {"appId": "default", "organization": ORG_ID, "os": "web",
               "orgId": ORG_ID, "data": V4_DATA, "ep": V4_EP,
               "encode": 5, "compress": 2}
    r = _post(V4_URL, payload)
    if r.get("code") != 1100:
        raise SklandError(f"取设备指纹失败：{r.get('msg')}")
    dev = (r.get("detail") or {}).get("deviceId")
    if not dev:
        raise SklandError("设备指纹返回里没有 deviceId")
    _did_cache = f"B{dev}"
    return _did_cache


# Server time minus local time. Recorded once at refresh; every later request is
# corrected by it.
_clock_skew = 0
_synced = False


def server_now() -> int:
    """Unix seconds aligned with the Skland server.

    Using local time directly means a slightly off machine clock is rejected as
    「请勿修改设备本地时间」; using the fixed value refresh returned means it
    becomes a stale timestamp after a while. Hence the recorded offset.
    """
    return int(time.time()) + _clock_skew


def sign_headers(cred: Cred, url: str, method: str = "get",
                 body: dict | None = None, use_did: bool = False) -> dict:
    """Signed request headers. The algorithm is in the module docstring.

    With `use_did=True` the device fingerprint is folded into the signature.
    Older credentials (our own token -> code -> cred chain) can do without it; a
    cred lifted out of a live Skland app session must carry the full smidV2 or
    it fails with 10001 「设备信息无效」.
    """
    ts = server_now()
    parsed = urlparse(url)
    query = json.dumps(body) if method == "post" and body is not None else parsed.query
    keys = {**_SIGN_KEYS, "dId": cred.dId}
    if use_did and not keys["dId"]:
        keys["dId"] = get_did()
    header_ca = {**keys, "timestamp": str(ts)}
    ca_str = json.dumps(header_ca, separators=(",", ":"))
    secret = f"{parsed.path}{query}{ts}{ca_str}"
    hexed = hmac.new(cred.token.encode(), secret.encode(), hashlib.sha256).hexdigest()
    return {"cred": cred.cred, **_HEADERS,
            "sign": hashlib.md5(hexed.encode()).hexdigest(),
            **header_ca}


def login(token: str, d_id: str = "") -> Cred:
    """token -> code -> cred. Raises when the token has expired; the message carries no credential.

    The device fingerprint has to be sent on the cred exchange itself and stays
    paired with the cred that comes back - without it the cred exchange still
    succeeds, but the very next refresh answers 「设备信息无效」.
    """
    d_id = d_id or get_did()
    r = _post(GRANT_URL, {"appCode": SKLAND_APP_CODE, "token": token, "type": 0})
    if r.get("status") not in (0, None):
        raise SklandError(f"换 code 失败，森空岛没接受这个 token：{r.get('msg')}")
    code = r["data"]["code"]
    r2 = _post(CRED_URL, {"code": code, "kind": 1}, {"dId": d_id})
    if r2.get("code") not in (0, None) or "data" not in r2:
        raise SklandError(f"换 cred 失败：{r2.get('message') or r2.get('messgae')}")
    d = r2["data"]
    return Cred(cred=d["cred"], token=d["token"],
                userId=str(d.get("userId", "")), dId=d_id)


def refresh(cred: Cred) -> Cred:
    """Renew the cred's token and align clocks with the server on the way. This endpoint itself needs no sign.

    **It must be called once before any business endpoint**, otherwise the
    timestamps are not aligned.
    """
    global _clock_skew  # noqa: PLW0603
    r = _get(REFRESH_URL, {**_HEADERS, "cred": cred.cred, "dId": cred.dId})
    if r.get("code") not in (0, None):
        raise SklandError(f"刷新失败：{r.get('message')}")
    global _synced  # noqa: PLW0603
    if server_ts := r.get("timestamp"):
        _clock_skew = int(server_ts) - int(time.time())
        _synced = True
        log.debug("森空岛：与服务器时差 %d 秒", _clock_skew)
    return Cred(cred=cred.cred, token=r["data"]["token"],
                userId=cred.userId, dId=cred.dId)


def endfield_role(cred: Cred) -> tuple[str, str]:
    """Endfield's (roleId, serverId).

    `serverId` comes from `roles[].serverId` - **not `channelMasterId`**. Take
    the wrong one and all you get is the same 403 that explains nothing.
    """
    for app in bindings(cred):
        if app.get("appCode") != "endfield":
            continue
        for b in app.get("bindingList") or []:
            for role in b.get("roles") or [b]:
                if role.get("roleId") and role.get("serverId"):
                    return str(role["roleId"]), str(role["serverId"])
    raise SklandError("这个账号下没找到终末地的角色绑定")


def endfield_card(cred: Cred, role_id: str = "", server_id: str = "") -> dict:  # deadcode: allow -- public entry point of the Skland API, documented in docs/SKLAND-API.md, called by hand for ad-hoc progression checks
    """Endfield personal detail. Progression lives in `data.detail`."""
    if not _synced:
        # Forgetting to align clocks yields an "expired" timestamp and a 10003.
        # Rather than rely on the caller remembering, do it for them here.
        cred = refresh(cred)
    if not role_id or not server_id:
        role_id, server_id = endfield_role(cred)
    url = f"{ENDFIELD_CARD_URL}?roleId={role_id}&serverId={server_id}"
    r = _get(url, sign_headers(cred, url))
    if r.get("code") not in (0, None):
        raise SklandError(f"取终末地详情失败：code={r.get('code')} {r.get('message')}")
    return r.get("data") or {}


def get(cred: Cred, path: str) -> dict:
    """GET a zonai path following the signing rules. Used by banners.py so it need not rebuild the signing chain."""
    url = ZONAI + path if path.startswith("/") else path
    return _get(url, sign_headers(cred, url))


def bindings(cred: Cred) -> list[dict]:
    """The list of bound game accounts (Endfield included)."""
    r = _get(BINDING_URL, sign_headers(cred, BINDING_URL))
    if r.get("code") not in (0, None):
        raise SklandError(f"取绑定角色失败：{r.get('message')}")
    return r["data"]["list"]
