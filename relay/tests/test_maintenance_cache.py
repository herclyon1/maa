"""The official maintenance bulletins: one retry, a cache, one WARNING per real failure.

10-02 23:05:34 and 23:05:54 (#50 #53) ak.hypergryph.com and
endfield.hypergryph.com each timed out once, 20 s apart, inside one phone
state push: every state push builds tomorrow's plan, which read all three
official sites each time - dozens of times that evening, a WARNING for every
timeout. Every WARNING is pushed to the group now (2026-10-06);
the user on that: 「你正常情况应该一条都不发的」.

Pinned here: a site that does not answer is asked once more after a pause (an
HTTP answer is not); a good read is reused for OK_TTL; a failed read is a
WARNING once and, for FAIL_TTL, an INFO without asking again; `sources` given
(the tests, gameupdate's injected readers) is read as given. Fake network.
"""
import logging
import sys
import types
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import maintenance as M
from ark_relay.config import SERVER_TZ

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


class Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.recs: list[tuple[int, str]] = []

    def emit(self, record):
        self.recs.append((record.levelno, record.getMessage()))

    def warnings(self):
        return [m for lv, m in self.recs if lv >= logging.WARNING]


logs = Logs()
M.log.addHandler(logs)
M.log.setLevel(logging.DEBUG)
M.log.propagate = False


class Resp:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def net(*answers):
    calls = []
    queue = list(answers)

    def urlopen(req, timeout=None):
        calls.append(req.full_url)
        nxt = queue.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return Resp(nxt)
    M.urllib = types.SimpleNamespace(request=types.SimpleNamespace(Request=urllib.request.Request,
                                                                   urlopen=urlopen),
                                     error=urllib.error)
    return calls


slept: list = []
M._sleep = slept.append

print("[_get：没响应就停一下再试一次；答了话（HTTP 错误）不重试]")
try:
    calls = net(urllib.error.URLError("timed out"), "公告".encode())
    check("第一次超时、第二次读到", M._get("https://ak.hypergryph.com/news"), "公告")
    check("……一共问了两次", len(calls), 2)
    check("……中间停了一下", slept, [getattr(M, "GET_PAUSE", None)])
    calls = net(urllib.error.HTTPError("https://x", 404, "nf", {}, None))
    try:
        M._get("https://x")
        raised = False
    except urllib.error.HTTPError:
        raised = True
    check("404：直接报，不重试", (raised, len(calls)), (True, 1))
except Exception as exc:  # noqa: BLE001
    print(f"  ✗ _get: {type(exc).__name__}: {exc}")
    fails.append("_get")

print("\n[today：官方三家走缓存，一次真失败一条 WARNING]")
NOW = datetime(2026, 10, 2, 23, 5, tzinfo=SERVER_TZ)
WIN = (datetime(2026, 10, 2, 6, 0, tzinfo=SERVER_TZ), datetime(2026, 10, 2, 12, 0, tzinfo=SERVER_TZ), "官方公告")
asked = {"明日方舟": 0, "终末地": 0, "鸣潮": 0}


def ak(now):
    asked["明日方舟"] += 1
    raise urllib.error.URLError("timed out")


def ef(now):
    asked["终末地"] += 1
    return WIN


def ww(now):
    asked["鸣潮"] += 1
    return None


saved = dict(M.SOURCES)
M.SOURCES.update({"明日方舟": ak, "终末地": ef, "鸣潮": ww})
getattr(M, "_CACHE", {}).clear()
try:
    logs.recs.clear()
    failed: list = []
    check("第一次：终末地今天维护，方舟取不到", (list(M.today(NOW, failed=failed)), failed), (["终末地"], ["明日方舟"]))
    check("……方舟那次是一条 WARNING，说清是哪家官网",
          [("明日方舟" in m and "ak.hypergryph.com" in m) for m in logs.warnings()], [True])
    logs.recs.clear()
    for _ in range(5):        # five more state pushes in the next minutes
        failed = []
        M.today(NOW, failed=failed)
    check("再推五次状态：三家一个都不再去问", asked, {"明日方舟": 1, "终末地": 1, "鸣潮": 1})
    check("……方舟仍算取不到（调用方照样知道不知道）", failed, ["明日方舟"])
    check("……不再多记 WARNING（10-02 晚每推一次状态就是一条）", logs.warnings(), [])
    # the failure has aged past FAIL_TTL, the good reads have not
    for k in ("明日方舟",):
        at, got = M._CACHE[k]
        M._CACHE[k] = (at - M.FAIL_TTL - 1, got)
    logs.recs.clear()
    M.today(NOW)
    check("失败过了 FAIL_TTL：方舟再去问一次，读到的两家还用缓存",
          asked, {"明日方舟": 2, "终末地": 1, "鸣潮": 1})
    check("……这次又是真失败：一条 WARNING", len(logs.warnings()), 1)
    for k in ("终末地", "鸣潮"):
        at, got = M._CACHE[k]
        M._CACHE[k] = (at - M.OK_TTL - 1, got)
    M.today(NOW)
    check("读到的过了 OK_TTL：再去问", (asked["终末地"], asked["鸣潮"]), (2, 2))
    src = {"明日方舟": ak}
    before = asked["明日方舟"]
    M.today(NOW, sources=src)
    M.today(NOW, sources=src)
    check("给了 sources 就照给的读，不走缓存", asked["明日方舟"] - before, 2)
except Exception as exc:  # noqa: BLE001
    print(f"  ✗ today: {type(exc).__name__}: {exc}")
    fails.append("today")
finally:
    M.SOURCES.clear()
    M.SOURCES.update(saved)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
