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
"""
import hashlib
import hmac
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import skland

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


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
import inspect  # noqa: E402
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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
