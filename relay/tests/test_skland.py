"""森空岛 (Skland): its API, HTTP error bodies, the role, signing and the sync guard.

One part per former file, each run on its own (tests/_parts.py): test_skland_api.py, test_skland_http_error_body.py, test_skland_role.py, test_skland_sign.py, test_skland_sync_guard.py.
"""
from __future__ import annotations

# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_skland_api():
    """The Skland calls: device id, login, refresh, bindings, Endfield card, role.

No network: urllib.request.urlopen is replaced by a recorder that answers
each URL with a canned JSON body (gzip-compressed where the real server does
it, see skland._read). What is tested is the relay's own judgement: a wrong
return code raises with its reason and is never taken as a success, the
device id is cached and sent where it must be, and with several Endfield
roles and none named the role lookup refuses with the list instead of
silently taking the first (audit 2026-10-05).

The response shapes follow docs/SKLAND-API.md (roleId / serverId in
bindingList[].roles[]); no real binding response is on file.

    Formerly test_skland_api.py.
    """
    #!/usr/bin/env python3

    import gzip
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import skland


    def raises(fn) -> str:
        """The SklandError message, or "" when nothing was raised."""
        try:
            fn()
        except skland.SklandError as exc:
            return str(exc) or "(empty)"
        return ""


    class Resp:
        def __init__(self, body: dict, gz: bool):
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self._raw = gzip.compress(raw) if gz else raw
            self.headers = {"Content-Encoding": "gzip"} if gz else {}

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    sent: list[dict] = []
    answers: dict = {}


    def fake_urlopen(req, timeout=None):
        url = req.full_url
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        sent.append({"url": url, "body": body, "headers": {k.lower(): v for k, v in req.header_items()}})
        a = answers[url.split("?")[0]]
        a = a(url) if callable(a) else a
        return Resp(a, gz=len(sent) % 2 == 0)      # every other answer gzip'd


    skland.urllib.request.urlopen = fake_urlopen
    CRED = skland.Cred(cred="c", token="t", userId="u", dId="Bdev")


    def main() -> int:
        print("[get_did: device fingerprint]")
        skland._did_cache = ""
        answers[skland.V4_URL] = {"code": 1101, "msg": "参数错误"}
        check("return code not 1100 -> raises with the reason", "参数错误" in raises(skland.get_did))
        answers[skland.V4_URL] = {"code": 1100, "detail": {}}
        check("no deviceId -> raises", "deviceId" in raises(skland.get_did))
        answers[skland.V4_URL] = {"code": 1100, "detail": {"deviceId": "XYZ"}}
        check("ok: prefixed with B", skland.get_did(), "BXYZ")
        n = len(sent)
        check("second call is cached, no request", (skland.get_did(), len(sent)), ("BXYZ", n))
        skland._did_cache = ""

        print("[login: token -> code -> cred]")
        answers[skland.GRANT_URL] = {"status": 1, "msg": "token 过期"}
        check("token refused -> raises with the reason", "token 过期" in raises(lambda: skland.login("tok", "Bdev")))
        answers[skland.GRANT_URL] = {"status": 0, "data": {"code": "CODE"}}
        answers[skland.CRED_URL] = {"code": 10002, "message": "设备信息无效"}
        check("cred exchange refused -> raises with the reason",
              "设备信息无效" in raises(lambda: skland.login("tok", "Bdev")))
        answers[skland.CRED_URL] = {"code": 0, "data": {"cred": "CR", "token": "TK", "userId": 42}}
        c = skland.login("tok", "Bdev")
        check("ok: cred / token / userId / dId", (c.cred, c.token, c.userId, c.dId), ("CR", "TK", "42", "Bdev"))
        check("the code is exchanged with the grant's code", sent[-1]["body"], {"code": "CODE", "kind": 1})
        check("the cred exchange carries the device id", sent[-1]["headers"].get("did"), "Bdev")
        check("the credential is not in repr", "TK" in repr(c) or "CR" in repr(c), False)

        print("[refresh: new token, clock offset]")
        answers[skland.REFRESH_URL] = {"code": 10001, "message": "操作失败"}
        check("refresh refused -> raises", "刷新失败" in raises(lambda: skland.refresh(CRED)))
        skland._synced, skland._clock_skew = False, 0
        now = int(skland.time.time())
        answers[skland.REFRESH_URL] = {"code": 0, "timestamp": str(now + 30), "data": {"token": "NEW"}}
        r = skland.refresh(CRED)
        check("new token", r.token, "NEW")
        check("offset recorded, marked synced", (abs(skland._clock_skew - 30) <= 1, skland._synced), (True, True))

        print("[bindings]")
        answers[skland.BINDING_URL] = {"code": 10000, "message": "未登录"}
        check("wrong return code -> raises", "未登录" in raises(lambda: skland.bindings(CRED)))

        def bind(*roles):
            return {"code": 0, "data": {"list": [
                {"appCode": "arknights", "bindingList": [{"uid": "1923", "channelMasterId": "1"}]},
                {"appCode": "endfield", "bindingList": [{"uid": "2474", "channelMasterId": "1",
                                                         "roles": [{"roleId": r, "serverId": s} for r, s in roles]}]},
            ]}}

        answers[skland.BINDING_URL] = bind(("111", "1"))
        check("ok: the list as given", [a["appCode"] for a in skland.bindings(CRED)], ["arknights", "endfield"])
        check("the request is signed", bool(sent[-1]["headers"].get("sign")) and sent[-1]["headers"].get("cred") == "c")

        print("[endfield_role]")
        check("one role -> that one", skland.endfield_role(CRED), ("111", "1"))
        answers[skland.BINDING_URL] = bind(("111", "1"), ("222", "2"))
        msg = raises(lambda: skland.endfield_role(CRED))
        check("two roles, none named -> refused with both listed, not the first",
              "2 个终末地角色" in msg and "111" in msg and "222" in msg, True)
        check("named -> that one", skland.endfield_role(CRED, role_id="222"), ("222", "2"))
        check("named but not bound -> refused", "333" in raises(lambda: skland.endfield_role(CRED, role_id="333")))
        answers[skland.BINDING_URL] = {"code": 0, "data": {"list": [{"appCode": "arknights", "bindingList": []}]}}
        check("no Endfield binding -> refused", "没找到" in raises(lambda: skland.endfield_role(CRED)))

        print("[endfield_card]")
        answers[skland.BINDING_URL] = bind(("111", "1"))
        skland._synced = False
        before = sum(1 for s in sent if s["url"] == skland.REFRESH_URL)
        answers[skland.ENDFIELD_CARD_URL] = lambda url: {"code": 0, "data": {"detail": {"url": url}}}
        d = skland.endfield_card(CRED)
        check("not synced -> refreshes first", sum(1 for s in sent if s["url"] == skland.REFRESH_URL), before + 1)
        check("no role given -> the only role", "roleId=111&serverId=1" in d["detail"]["url"])
        answers[skland.BINDING_URL] = bind(("111", "1"), ("222", "2"))
        check("two roles, none given -> refused, not the first",
              "2 个终末地角色" in raises(lambda: skland.endfield_card(CRED)))
        check("role given without server -> that role's server",
              "roleId=222&serverId=2" in skland.endfield_card(CRED, "222")["detail"]["url"])
        check("role and server given -> used as given",
              "roleId=222&serverId=2" in skland.endfield_card(CRED, "222", "2")["detail"]["url"])
        answers[skland.ENDFIELD_CARD_URL] = {"code": 10003, "message": "时间戳过期"}
        check("wrong return code -> raises with the reason",
              "时间戳过期" in raises(lambda: skland.endfield_card(CRED, "111", "1")))

        print()
        if fails:
            print(f"FAILED {len(fails)}: {fails}")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_skland_http_error_body():
    """A Skland 4xx must keep the {"code", "message"} body it came with.

Audit s6 #5 (2026-10-13): _get / _post let urllib raise a bare HTTPError, so
Skland's own reason (10001 「操作失败，请稍后重试」 on a 403, measured 2026-08-27,
docs/SKLAND-API.md) never reached the log or the phone tile, which showed only
「HTTP Error 403」. Network is faked; no request leaves.

    Formerly test_skland_http_error_body.py.
    """
    import email.message
    import io
    import urllib.error

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import skland


    def refusing(code: int, body: bytes):
        def urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "Forbidden", email.message.Message(), io.BytesIO(body))
        return urlopen


    real = skland.urllib.request.urlopen
    url = "https://zonai.skland.com/web/v1/game/endfield/card/detail?roleId=1&serverId=1"

    print("[403 with Skland's body: the code and message are in the error]")
    skland.urllib.request.urlopen = refusing(403, '{"code":10001,"message":"操作失败，请稍后重试"}'.encode())
    try:
        skland._get(url, {})
        said = ""
    except Exception as e:  # noqa: BLE001 - the text is what is checked
        said = str(e)
    check("Skland's code is kept", "10001" in said, True)
    check("Skland's message is kept", "操作失败，请稍后重试" in said, True)
    check("the HTTP status is kept", "403" in said, True)

    print("\n[403 with no readable body: the plain HTTP error, as before]")
    skland.urllib.request.urlopen = refusing(403, b"<html>nope</html>")
    try:
        skland._get(url, {})
        got = None
    except Exception as e:  # noqa: BLE001
        got = type(e).__name__
    check("bare HTTPError", got, "HTTPError")
    skland.urllib.request.urlopen = real

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")


def _part_skland_role():
    """endfield_role never guesses between several bound Endfield roles.

No binding response has been recorded (fixtures/skland-endfield holds wiki and
catalog pages only), so the shape below follows docs/SKLAND-API.md line 24:
roleId and serverId sit in bindingList[].roles[]. Before 2026-10-06 the first
role was returned whatever else was bound.

    Formerly test_skland_role.py.
    """
    #!/usr/bin/env python3


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import skland

    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
        if not ok:
            FAILED.append(name)


    def _apps(*roles):
        return [{"appCode": "arknights", "bindingList": [{"uid": "1"}]},
                {"appCode": "endfield", "bindingList": [{"uid": "9", "roles": list(roles)}]}]


    def _role(apps):
        skland.bindings = lambda cred: apps
        try:
            return skland.endfield_role(None)
        except skland.SklandError as exc:
            return str(exc)


    def main() -> int:
        a = {"roleId": "1001", "serverId": "1"}
        b = {"roleId": "2002", "serverId": "2"}
        require("one role is returned", _role(_apps(a)) == ("1001", "1"), repr(_role(_apps(a))))
        require("the same role listed twice is still one role", _role(_apps(a, dict(a))) == ("1001", "1"))
        two = _role(_apps(a, b))
        require("two roles: refused, not the first one", isinstance(two, str) and "2 个终末地角色" in two, repr(two))
        skland.bindings = lambda cred: _apps(a, b)
        try:
            skland.endfield_role(None)
            kind, roles = "returned", []
        except skland.SklandError as exc:
            kind, roles = type(exc).__name__, getattr(exc, "roles", None)
        require("the refusal is its own type, carrying the roles (callers tell it by type, not text)",
                (kind, roles) == ("SklandMultiRole", [("1001", "1"), ("2002", "2")]), repr((kind, roles)))
        none = _role(_apps())
        require("no role: refused", isinstance(none, str) and "没找到" in none, repr(none))
        print()
        if FAILED:
            print(f"FAILED {len(FAILED)}: {FAILED}")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_skland_sign():
    """The Skland request signature, recomputed independently.

Every Skland call carries a `sign`. Get any part of it wrong and the server
answers HTTP 403 `{"code":10001,"message":"操作失败，请稍后重试"}` - **it never
says which part**. On 2026-08-27 three things were wrong at once (platform,
vName, serverId) and the whole day went into the wrong line of investigation.

So this test does not trust the implementation to check itself. It rebuilds the
signature from the algorithm written in the module docstring, with its own
constants and its own key order, and demands the two agree:

    secret = path + query + timestamp + json({platform,timestamp,dId,vName})
    sign   = MD5(HMAC-SHA256(cred.token, secret))

That pins two things a refactor cannot see it has broken: the exact key order
inside the signed JSON (a dict rebuilt in a different order signs a different
string), and `platform` / `vName` staying at "3" / "1.0.0".

    Formerly test_skland_sign.py.
    """
    import hashlib
    import hmac
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import skland


    FIXED = 1757000000
    skland.time = type("t", (), {"time": staticmethod(lambda: float(FIXED))})()

    CRED = skland.Cred(cred="CRED-abc", token="TOKEN-xyz", userId="u1", dId="DID-1")


    def expect(path, query, ts, did):
        """The signature, spelled out from the docstring rather than reused."""
        header_ca = {"platform": "3", "timestamp": str(ts), "dId": did, "vName": "1.0.0"}
        secret = f"{path}{query}{ts}{json.dumps(header_ca, separators=(',', ':'))}"
        hexed = hmac.new(CRED.token.encode(), secret.encode(), hashlib.sha256).hexdigest()
        return hashlib.md5(hexed.encode()).hexdigest()


    print("[时钟：没校准过时就是本机时间]")
    skland._clock_skew = 0
    check("本机时间", skland.server_now(), FIXED)

    print("\n[校准过之后每次请求都带「服务器时间＋本机走过的时间」]")
    skland._clock_skew = 37
    check("带上偏移", skland.server_now(), FIXED + 37)
    skland._clock_skew = -12
    check("偏移是负的也算得对", skland.server_now(), FIXED - 12)
    skland._clock_skew = 0

    print("\n[GET：签名和照着文档算出来的一模一样]")
    url = "https://zonai.skland.com/api/v1/game/player/binding?uid=1"
    h = skland.sign_headers(CRED, url)
    check("sign", h["sign"], expect("/api/v1/game/player/binding", "uid=1", FIXED, "DID-1"))
    check("cred 带上了", h["cred"], "CRED-abc")
    check("platform 是 3", h["platform"], "3")
    check("vName 是 1.0.0", h["vName"], "1.0.0")
    check("timestamp 是字符串", h["timestamp"], str(FIXED))
    check("dId 带上了", h["dId"], "DID-1")
    check("User-Agent 还在", "Skland" in h["User-Agent"], True)

    print("\n[时钟偏移会进签名——签的时刻和头里写的时刻必须是同一个]")
    skland._clock_skew = 60
    h4 = skland.sign_headers(CRED, url)
    check("头里是校准后的时刻", h4["timestamp"], str(FIXED + 60))
    check("签的也是同一个时刻", h4["sign"],
          expect("/api/v1/game/player/binding", "uid=1", FIXED + 60, "DID-1"))
    skland._clock_skew = 0

    print("\n[只有 GET 一种签法：没人用的 POST 请求体、现取 dId 两个参数删掉了（audit s6 #4）]")
    import inspect
    check("参数只剩凭据和网址", list(inspect.signature(skland.sign_headers).parameters), ["cred", "url"])

    print("\n[凭据没有 dId 时不去现取一个：签进去的就是凭据自己的]")
    calls = []
    orig_get_did = skland.get_did
    skland.get_did = lambda: (calls.append(1), "DID-NEW")[1]
    bare = skland.Cred(cred="CRED-abc", token="TOKEN-xyz")
    h7 = skland.sign_headers(bare, url)
    check("没去要新的", calls, [])
    check("头里是空的", h7["dId"], "")
    check("签名里也是空的", h7["sign"],
          expect("/api/v1/game/player/binding", "uid=1", FIXED, ""))
    skland.get_did = orig_get_did

    print("\n[token 不同签名必须不同，否则等于没签]")
    other = skland.Cred(cred="CRED-abc", token="TOKEN-OTHER", dId="DID-1")
    check("换了 token 签名就变", skland.sign_headers(other, url)["sign"] != h["sign"], True)


def _part_skland_sync_guard():
    """skland.get / bindings must align clocks first when this process has not yet.

Audit s6 #3 (2026-10-13): only endfield_card had the `if not _synced: refresh()`
guard. banners.py calls login() then get(), so in a process where no phone
session had refreshed first, the request was signed with the local clock
(Skland answers 10003 when it is off). Network is faked; no request leaves.

    Formerly test_skland_sync_guard.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import skland


    calls: list = []


    def fake_get(url, headers):
        calls.append(url.split("?")[0])
        if url.startswith(skland.REFRESH_URL):
            return {"code": 0, "timestamp": 2_000_000_000, "data": {"token": "TOKEN-NEW"}}
        return {"code": 0, "data": {"list": []}}


    skland._get = fake_get
    cred = skland.Cred(cred="CRED", token="TOKEN-OLD", dId="DID")

    for name, call, target in (("get", lambda: skland.get(cred, "/api/v1/game/x"), skland.ZONAI + "/api/v1/game/x"),
                               ("bindings", lambda: skland.bindings(cred), skland.BINDING_URL)):
        print(f"\n[{name}: first call in a fresh process refreshes first]")
        skland._synced = False
        skland._clock_skew = 0
        calls.clear()
        call()
        check("refresh, then the request", calls, [skland.REFRESH_URL, target])
        print(f"[{name}: once aligned, no second refresh]")
        calls.clear()
        call()
        check("only the request", calls, [target])

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")


if __name__ == "__main__":
    sys.exit(run_parts([_part_skland_api, _part_skland_http_error_body, _part_skland_role, _part_skland_sign, _part_skland_sync_guard]))
