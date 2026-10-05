#!/usr/bin/env python3
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
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import skland

fails: list[str] = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


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
