"""The wording model is a garnish, but a dead endpoint is not free: each attempt
can cost the full 60 s timeout, inside the path that must finish before the
machine may power off. One failure per process is enough to learn from.
"""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import summary  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

class Cfg:
    llm_key = "sk-test"
    llm_provider = "openai"
    llm_model = "deepseek-chat"
    llm_base_url = "https://api.deepseek.com"

calls = []
def slow_and_broken(*a, **kw):
    calls.append(1)
    time.sleep(0.05)                      # stand-in for a 60 s timeout
    raise OSError("connection refused")

summary.urllib.request.urlopen = slow_and_broken
summary._endpoint_dead = False

print("[first call tries, and fails]")
check("returns nothing", summary._ask(Cfg(), "hi"), "")
check("did attempt", len(calls), 1)

print("\n[every later call in this process is free]")
t0 = time.monotonic()
for _ in range(20):
    summary._ask(Cfg(), "hi")
elapsed = time.monotonic() - t0
check("no further attempts", len(calls), 1)
check("cost ~nothing", elapsed < 0.05, True)

print("\n[the report still renders without it]")
entry = {"run_id": "x", "script": "MAA", "user": "arknights",
         "started": "2026-08-21T21:30:00+08:00",
         "finished": "2026-08-21T22:15:00+08:00", "ok": True}
check("daily_report returns empty, caller falls back",
      summary.daily_report(Cfg(), [entry]), "")

print("\n[an explicit check must really ask again]")
try:
    summary.check(Cfg())
except Exception:
    pass
check("breaker was reset by check()", len(calls), 2)

print("\n[no key at all: never attempts]")
class NoKey(Cfg):
    llm_key = ""
summary._endpoint_dead = False
before = len(calls)
check("returns nothing", summary._ask(NoKey(), "hi"), "")
check("no attempt", len(calls), before)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
