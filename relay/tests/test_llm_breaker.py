"""The wording model is a garnish, but a dead endpoint is not free: each attempt
can cost the full 60 s timeout, inside the path that must finish before the
machine may power off. After a failure it rests summary.REST_S, then is asked again
(audit 11-08 B-D7: until then one failure closed it for the whole process); the group
hears of it once per process.
"""
import logging
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import summary

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
summary._endpoint_dead = None
NOW = [1000.0]
summary._clock = lambda: NOW[0]


class Levels(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.levels = []

    def emit(self, record):
        self.levels.append(record.levelname)


levels = Levels()
summary.log.addHandler(levels)
summary.log.setLevel(logging.DEBUG)
summary.log.propagate = False

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
check("one WARNING (the group hears of it)", levels.levels, ["WARNING"])

print("\n[after the rest it is asked again; failing again is INFO, not a second push]")
NOW[0] += summary.REST_S - 1
summary._ask(Cfg(), "hi")
check("just before the rest ends: still skipped", len(calls), 1)
NOW[0] += 2
summary._ask(Cfg(), "hi")
check("after the rest: asked again", len(calls), 2)
check("……that failure is INFO", levels.levels, ["WARNING", "INFO"])


class Resp:
    def read(self):
        return '{"choices": [{"message": {"content": "好"}}]}'.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


summary.urllib.request.urlopen = lambda *a, **kw: calls.append(1) or Resp()
NOW[0] += summary.REST_S
check("back: the answer is used", summary._ask(Cfg(), "hi"), "好")
check("……and the next call is not held back", (summary._endpoint_dead, summary._ask(Cfg(), "hi")), (None, "好"))
summary.urllib.request.urlopen = slow_and_broken
summary._endpoint_dead = NOW[0]          # dead again, resting
calls[:] = [1]

print("\n[the report still renders without it]")
entry = {"run_id": "x", "script": "MAA", "user": "arknights",
         "started": "2026-08-21T21:30:00+08:00",
         "finished": "2026-08-21T22:15:00+08:00", "ok": True}
check("diagnose returns empty, caller falls back",
      summary.diagnose(Cfg(), entry["script"], ["x"], "log tail"), "")

print("\n[an explicit check must really ask again]")
try:
    summary.check(Cfg())
except Exception:  # noqa: BLE001
    pass
check("breaker was reset by check()", len(calls), 2)

print("\n[no key at all: never attempts]")
class NoKey(Cfg):
    llm_key = ""
summary._endpoint_dead = None
before = len(calls)
check("returns nothing", summary._ask(NoKey(), "hi"), "")
check("no attempt", len(calls), before)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
