"""The Skland calls: device id, login, refresh, bindings, Endfield card, role.

The transport (_post / _get) is faked; only the relay's own judgement is
tested: a wrong return code raises with its reason and is never a success,
and with several Endfield roles and none named the role lookup refuses
instead of silently taking the first (audit 2026-10-05).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import skland

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def raises(fn):
    """The SklandError message, or "" when nothing was raised."""
    try:
        fn()
    except skland.SklandError as exc:
        return str(exc) or "(empty)"
    return ""


posts: list = []
gets: list = []
answers: dict = {}


def fake_post(url, payload, headers=None):
    posts.append((url, payload, headers))
    return answers[url]


def fake_get(url, headers):
    gets.append((url, headers))
    a = answers[url.split("?")[0]]
    return a(url) if callable(a) else a


skland._post, skland._get = fake_post, fake_get
CRED = skland.Cred(cred="c", token="t", userId="u", dId="Bdev")

print("[get_did：取设备指纹]")
skland._did_cache = ""
answers[skland.V4_URL] = {"code": 1101, "msg": "参数错误"}
check("返回码不是 1100 → 报错带原因", "参数错误" in raises(skland.get_did), True)
answers[skland.V4_URL] = {"code": 1100, "detail": {}}
check("没有 deviceId → 报错", "deviceId" in raises(skland.get_did), True)
answers[skland.V4_URL] = {"code": 1100, "detail": {"deviceId": "XYZ"}}
check("正常：前面加 B", skland.get_did(), "BXYZ")
n = len(posts)
check("第二次用缓存，不再请求", (skland.get_did(), len(posts)), ("BXYZ", n))
skland._did_cache = ""

print("\n[login：token → code → cred]")
answers[skland.GRANT_URL] = {"status": 1, "msg": "token 过期"}
check("token 不被接受 → 报错带原因", "token 过期" in raises(lambda: skland.login("tok", "Bdev")), True)
answers[skland.GRANT_URL] = {"status": 0, "data": {"code": "CODE"}}
answers[skland.CRED_URL] = {"code": 10002, "message": "设备信息无效"}
check("换 cred 失败 → 报错带原因", "设备信息无效" in raises(lambda: skland.login("tok", "Bdev")), True)
answers[skland.CRED_URL] = {"code": 0, "data": {"cred": "CR", "token": "TK", "userId": 42}}
c = skland.login("tok", "Bdev")
check("正常：cred / token / userId / dId", (c.cred, c.token, c.userId, c.dId), ("CR", "TK", "42", "Bdev"))
check("换 cred 时带上了设备指纹", posts[-1][2], {"dId": "Bdev"})
check("凭据不进 repr", "TK" in repr(c) or "CR" in repr(c), False)

print("\n[refresh：换 token、对时]")
answers[skland.REFRESH_URL] = {"code": 10001, "message": "操作失败"}
check("刷新失败 → 报错", "刷新失败" in raises(lambda: skland.refresh(CRED)), True)
skland._synced, skland._clock_skew = False, 0
now = int(skland.time.time())
answers[skland.REFRESH_URL] = {"code": 0, "timestamp": str(now + 30), "data": {"token": "NEW"}}
r = skland.refresh(CRED)
check("新 token", r.token, "NEW")
check("记下了时差、标记已对时", (abs(skland._clock_skew - 30) <= 1, skland._synced), (True, True))

print("\n[bindings：取绑定角色]")
answers[skland.BINDING_URL] = {"code": 10000, "message": "未登录"}
check("返回码不对 → 报错", "未登录" in raises(lambda: skland.bindings(CRED)), True)


def bind(*roles):
    return {"code": 0, "data": {"list": [
        {"appCode": "arknights", "bindingList": [{"uid": "1923", "channelMasterId": "1"}]},
        {"appCode": "endfield", "bindingList": [{"uid": "2474", "channelMasterId": "1",
                                                 "roles": [{"roleId": r, "serverId": s} for r, s in roles]}]},
    ]}}


answers[skland.BINDING_URL] = bind(("111", "1"))
check("正常：原样给列表", [a["appCode"] for a in skland.bindings(CRED)], ["arknights", "endfield"])

print("\n[endfield_role：挑终末地角色]")
check("只有一个角色 → 就是它（反例）", skland.endfield_role(CRED), ("111", "1"))
answers[skland.BINDING_URL] = bind(("111", "1"), ("222", "2"))
msg = raises(lambda: skland.endfield_role(CRED))
check("两个角色、没指定 → 拒绝，不静默取第一个", "2 个终末地角色" in msg and "111" in msg and "222" in msg, True)
check("指定了 → 用指定的", skland.endfield_role(CRED, role_id="222"), ("222", "2"))
check("指定的不在账号里 → 拒绝", "333" in raises(lambda: skland.endfield_role(CRED, role_id="333")), True)
answers[skland.BINDING_URL] = {"code": 0, "data": {"list": [{"appCode": "arknights", "bindingList": []}]}}
check("没有终末地绑定 → 拒绝", "没找到" in raises(lambda: skland.endfield_role(CRED)), True)

print("\n[endfield_card：取终末地详情]")
answers[skland.BINDING_URL] = bind(("111", "1"))
skland._synced = False
refreshes = len([g for g in gets if g[0] == skland.REFRESH_URL])
answers[skland.ENDFIELD_CARD_URL] = lambda url: {"code": 0, "data": {"detail": {"url": url}}}
d = skland.endfield_card(CRED)
check("没对时 → 自己先刷新一次", len([g for g in gets if g[0] == skland.REFRESH_URL]), refreshes + 1)
check("没给角色 → 用唯一的那个角色", "roleId=111&serverId=1" in d["detail"]["url"], True)
answers[skland.BINDING_URL] = bind(("111", "1"), ("222", "2"))
check("两个角色、没给 → 拒绝（不取第一个）", "2 个终末地角色" in raises(lambda: skland.endfield_card(CRED)), True)
check("给了角色 → 直接用", "roleId=222&serverId=2" in skland.endfield_card(CRED, "222", "2")["detail"]["url"], True)
answers[skland.ENDFIELD_CARD_URL] = {"code": 10003, "message": "时间戳过期"}
check("返回码不对 → 报错带原因", "时间戳过期" in raises(lambda: skland.endfield_card(CRED, "111", "1")), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
