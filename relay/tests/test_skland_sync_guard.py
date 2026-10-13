"""skland.get / bindings must align clocks first when this process has not yet.

Audit s6 #3 (2026-10-13): only endfield_card had the `if not _synced: refresh()`
guard. banners.py calls login() then get(), so in a process where no phone
session had refreshed first, the request was signed with the local clock
(Skland answers 10003 when it is off). Network is faked; no request leaves.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import skland

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


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
sys.exit(1 if fails else 0)
