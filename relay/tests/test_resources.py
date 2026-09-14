"""resources: the Skland session for the phone page (one per process, a failure is
a reason not an exception) and today's run count from the ledger."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import resources

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


print("[森空岛会话：没配 token 就是一句说明]")


class NoTok:
    skland_token = ""


check("没配", resources.skland_session(NoTok), {"错误": "没配森空岛 token"})

print("\n[有 token：登录一次、找出两个游戏的账号，第二次直接复用]")
from ark_relay import skland  # noqa: E402

calls = {"login": 0}


class Cred:
    cred, token = "c1", "t1"


def fake_login(token, did=""):
    calls["login"] += 1
    return Cred()


skland.get_did, skland.login, skland.refresh = (lambda: "Bdev"), fake_login, (lambda c: c)
skland.bindings = lambda c: [
    {"appCode": "endfield", "bindingList": [{"uid": "247481631", "channelMasterId": "1"}]},
    {"appCode": "arknights", "bindingList": [{"uid": "19237299", "channelMasterId": "1"}]},
]


class Tok:
    skland_token = "sk-token"


resources._session["sk"] = None
got = resources.skland_session(Tok)
check("会话齐全", got, {"cred": "c1", "token": "t1", "dId": "Bdev", "uid": "19237299", "efRole": "247481631", "efServer": "1"})
resources.skland_session(Tok)
check("只登录一次", calls["login"], 1)


def boom(c):
    raise RuntimeError("HTTP Error 401")


resources._session["sk"] = None
skland.bindings = boom
check("失败给原因", resources.skland_session(Tok)["错误"].startswith("RuntimeError: HTTP Error 401"), True)
check("失败后不留半个会话", resources._session["sk"], None)

print("\n[今天：从账目数]")


class St:
    def read_ledger(self, day):
        return [{"script": "MAA", "ok": True}, {"script": "OK-WW", "ok": False}, {"script": "MaaEnd", "ok": True}]


check("跑了 3 失败 1 最近 MaaEnd", resources.today(St(), "2026-09-15"), {"跑了": 3, "失败": 1, "最近": "MaaEnd"})

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
