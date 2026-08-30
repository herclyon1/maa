"""森空岛（鹰角官方社区）客户端：拿终末地的角色练度。

**为什么要它**：我们能看到游戏里刷了什么，但看不到「练到什么程度、还差什么」。
森空岛是官方社区，账号数据就在那儿，比截图识别可靠得多。

**凭证怎么来**（用户 2026-08-27 提供）：浏览器登录 skland.com 之后打开
`https://web-api.skland.com/account/info/hg`，返回 JSON 的 `data.content`
就是 token。它**等同账号登录凭证**，只存在机器的 `.env` 里（仓库是公开的，
`.gitignore` 第一行就是 `.env`），任何日志和报告里都不许出现它。

**token 会过期**，所以这里做成自动链路：token → code → cred，
cred 有 `/api/v1/auth/refresh` 可以续；全部失败才回头找人。
用户的原话是「你最好这东西搞个自动化，我记得token会过期的」。

**签名**：每个请求都要带 `sign`：

    secret = path + query + timestamp + json({platform,timestamp,dId,vName})
    sign   = MD5(HMAC-SHA256(cred.token, secret))     # 二次摘要是 MD5 不是 SHA256

2026-08-27 踩的坑，三条一起错才会 403：

* `platform` 必须是 **"3"**，不是 "1"。
* `vName` 必须是 **"1.0.0"**，不是空串。
* `serverId` 取 `bindingList[].roles[].serverId`，**不是 `channelMasterId`**。

错了就统一回 HTTP 403 `{"code":10001,"message":"操作失败，请稍后重试"}`，
**它不告诉你错在哪**。对照组是明日方舟的 `/api/v1/game/player/info`，
同一套签名一次就通——所以「签名对不对」这个方向从一开始就是错的。

时间戳要和服务器对齐：先 `GET /web/v1/auth/refresh`（它不需要 sign）拿到
`timestamp`，记下本地时间差，之后每次请求用 `服务器时间 + 本地流逝`。
长期直接用 refresh 那一刻的原始时间戳会被判「请勿修改设备本地时间」(10003)。

接口出处：otae-1204/otae-bot-entari `docs/skland_endfield_personal_api.md`
（2026-07 逆向 + 2026-08-19 复查，逐个端点都有 code:0 实测记录）。
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
# 终末地这套端点认死这两个值，见模块开头。
_SIGN_KEYS = {"platform": "3", "timestamp": "", "dId": "", "vName": "1.0.0"}

SKLAND_APP_CODE = "4ca99fa6b56cc2ba"     # 森空岛的 appCode，换 code 用
GRANT_URL = "https://as.hypergryph.com/user/oauth2/v2/grant"
ZONAI = "https://zonai.skland.com"
CRED_URL = "https://zonai.skland.com/api/v1/user/auth/generate_cred_by_code"
REFRESH_URL = "https://zonai.skland.com/web/v1/auth/refresh"
BINDING_URL = "https://zonai.skland.com/api/v1/game/player/binding"
ENDFIELD_CARD_URL = "https://zonai.skland.com/api/v1/game/endfield/card/detail"
ENDFIELD_CHAR_URL = "https://zonai.skland.com/api/v1/game/endfield/card/char"

_TIMEOUT = 20


class SklandError(RuntimeError):
    """接口报错。**不带凭证内容**——异常会进日志。"""


@dataclass
class Cred:
    cred: str
    token: str
    userId: str = ""
    dId: str = ""
    """设备指纹。**必须和 cred 是同一份会话**——换 cred 时用的哪个，
    之后每个请求（含 refresh）就得一直用哪个，签名里也得是它。
    2026-08-27 实测：换 cred 时不带 dId，refresh 直接回「设备信息无效」。"""

    def __repr__(self) -> str:          # 防止不小心把凭证打进日志
        return (f"Cred(userId={self.userId!r}, cred=<hidden>, token=<hidden>, "
                f"dId={'<有>' if self.dId else '<空>'})")


def _read(resp) -> dict:
    """读响应。请求头里带了 Accept-Encoding: gzip（照抄上游那份），
    而 urllib 不会自动解压——第一次调用就撞在这上面：
    `'utf-8' codec can't decode byte 0x8b`，0x8b 正是 gzip 的魔数。
    按实际的 Content-Encoding 判断，别假设。"""
    raw = resp.read()
    if resp.headers.get("Content-Encoding", "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _post(url: str, payload: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**_HEADERS, "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:   # noqa: S310
        return _read(r)


def _get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:   # noqa: S310
        return _read(r)


# ── 设备指纹（dId）──────────────────────────────────────────────
# `/web/v1/` 那套端点（终末地就在里面）不认没有 dId 的请求：
# 2026-08-27 实测，只带 sign 会被 403 挡回来，body 是
# {"code":10001,"message":"操作失败，请稍后重试"}——**它不告诉你缺什么**。
# 对照组：明日方舟的 /api/v1/game/player/info 同样的签名一次就通，
# 所以问题不在签名，在这套 web 端点额外要设备指纹。
#
# 下面这三个常量原样取自 FrostN0v0/nonebot-plugin-skland 的 api/dId.py
# （唯一公开可查的实现）。是一段固定的设备画像负载，换取一个 deviceId。
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
    """取设备指纹。一次会话里缓存着用，别每个请求都去要一遍。"""
    global _did_cache
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


# 服务器时间减本地时间。refresh 一次就记下来，之后所有请求都按它校正。
_clock_skew = 0
_synced = False


def server_now() -> int:
    """和森空岛服务器对齐的 Unix 秒。

    直接用本地时间，机器的钟稍微偏一点就会被判「请勿修改设备本地时间」；
    直接用 refresh 返回的那个固定值，过一会儿就变成过期时间戳。所以记差值。
    """
    return int(time.time()) + _clock_skew


def sign_headers(cred: Cred, url: str, method: str = "get",
                 body: dict | None = None, use_did: bool = False) -> dict:
    """带签名的请求头。算法见模块开头。

    `use_did=True` 时把设备指纹一起算进签名。旧凭据（我们这条 token→code→cred
    的链路）可以不用；从森空岛 App 当前登录态里抠出来的 cred 则必须带上
    完整的 smidV2，否则报 10001「设备信息无效」。
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
            "sign": hashlib.md5(hexed.encode()).hexdigest(),   # noqa: S324 - 接口就这么定的
            **header_ca}


def login(token: str, d_id: str = "") -> Cred:
    """token → code → cred。token 过期时这里会抛，信息里不含凭证。

    换 cred 这一步就要把设备指纹带上，并且和返回的 cred 绑成一对——
    不带的话 cred 本身能换到，但下一步 refresh 就是「设备信息无效」。
    """
    d_id = d_id or get_did()
    r = _post(GRANT_URL, {"appCode": SKLAND_APP_CODE, "token": token, "type": 0})
    if r.get("status") not in (0, None):
        raise SklandError(f"换 code 失败（token 可能过期）：{r.get('msg')}")
    code = r["data"]["code"]
    r2 = _post(CRED_URL, {"code": code, "kind": 1}, {"dId": d_id})
    if r2.get("code") not in (0, None) or "data" not in r2:
        raise SklandError(f"换 cred 失败：{r2.get('message') or r2.get('messgae')}")
    d = r2["data"]
    return Cred(cred=d["cred"], token=d["token"],
                userId=str(d.get("userId", "")), dId=d_id)


def refresh(cred: Cred) -> Cred:
    """续 cred 的 token，顺便和服务器对表。这个接口本身不需要 sign。

    **业务接口之前必须先调它一次**，否则时间戳没对齐。
    """
    global _clock_skew
    r = _get(REFRESH_URL, {**_HEADERS, "cred": cred.cred, "dId": cred.dId})
    if r.get("code") not in (0, None):
        raise SklandError(f"刷新失败：{r.get('message')}")
    global _synced
    if server_ts := r.get("timestamp"):
        _clock_skew = int(server_ts) - int(time.time())
        _synced = True
        log.debug("森空岛：与服务器时差 %d 秒", _clock_skew)
    return Cred(cred=cred.cred, token=r["data"]["token"],
                userId=cred.userId, dId=cred.dId)


def endfield_role(cred: Cred) -> tuple[str, str]:
    """终末地的 (roleId, serverId)。

    `serverId` 取 `roles[].serverId`——**不是 `channelMasterId`**，
    拿错了同样只会得到一个不解释原因的 403。
    """
    for app in bindings(cred):
        if app.get("appCode") != "endfield":
            continue
        for b in app.get("bindingList") or []:
            for role in b.get("roles") or [b]:
                if role.get("roleId") and role.get("serverId"):
                    return str(role["roleId"]), str(role["serverId"])
    raise SklandError("这个账号下没找到终末地的角色绑定")


def endfield_card(cred: Cred, role_id: str = "", server_id: str = "") -> dict:
    """终末地个人详情。练度在 `data.detail` 里。"""
    if not _synced:
        # 忘了对表就会拿到一个「过期」的时间戳，报 10003。
        # 与其指望调用方记得，不如在这里替他做掉。
        cred = refresh(cred)
    if not role_id or not server_id:
        role_id, server_id = endfield_role(cred)
    url = f"{ENDFIELD_CARD_URL}?roleId={role_id}&serverId={server_id}"
    r = _get(url, sign_headers(cred, url))
    if r.get("code") not in (0, None):
        raise SklandError(f"取终末地详情失败：code={r.get('code')} {r.get('message')}")
    return r.get("data") or {}


def get(cred: Cred, path: str) -> dict:
    """按签名规则 GET 一个 zonai 路径。给 banners.py 用，省得它重造签名链路。"""
    url = ZONAI + path if path.startswith("/") else path
    return _get(url, sign_headers(cred, url))


def bindings(cred: Cred) -> list[dict]:
    """绑定的游戏账号列表（含终末地）。"""
    r = _get(BINDING_URL, sign_headers(cred, BINDING_URL))
    if r.get("code") not in (0, None):
        raise SklandError(f"取绑定角色失败：{r.get('message')}")
    return r["data"]["list"]
