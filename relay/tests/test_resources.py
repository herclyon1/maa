"""resources: the Skland session for the phone page (one per process, a failure is
a reason not an exception) and today's run count from the ledger."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.features.phone import resources

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
from ark_relay.core import skland  # noqa: E402

calls = {"login": 0}


class Cred:
    cred, token = "c1", "t1"


def fake_login(token, did=""):
    calls["login"] += 1
    return Cred()


# Put the real functions back at the end: the coverage pass runs many test files in one
# process, and a later file (test_skland_api) must reach the real skland functions.
_REAL = (skland.get_did, skland.login, skland.refresh, skland.bindings)
skland.get_did, skland.login, skland.refresh = (lambda: "Bdev"), fake_login, (lambda c: c)
skland.bindings = lambda c: [
    {"appCode": "endfield", "bindingList": [{"uid": "247481631", "channelMasterId": "1",
                                              "roles": [{"roleId": "1234567890", "serverId": "1"}]}]},
    {"appCode": "arknights", "bindingList": [{"uid": "19237299", "channelMasterId": "1"}]},
]


class Tok:
    skland_token = "sk-token"


resources._session["sk"] = None
got = resources.skland_session(Tok)
check("会话齐全（终末地用 roles[] 的 roleId，不是 uid）", got, {"cred": "c1", "token": "t1", "dId": "Bdev", "uid": "19237299", "efRole": "1234567890", "efServer": "1"})
resources.skland_session(Tok)
check("只登录一次", calls["login"], 1)


def boom(c):
    raise RuntimeError("HTTP Error 401")


resources._session["sk"] = None
skland.bindings = boom
check("失败给原因", resources.skland_session(Tok)["错误"].startswith("RuntimeError: HTTP Error 401"), True)
check("失败后不留半个会话", resources._session["sk"], None)

print("\n[森空岛给了不止一个终末地角色：不读，报群]")
# The account has exactly one Endfield role (checked 2026-10-06); more than one
# in an answer is a refusal (skland.endfield_role) the group has to hear of.
import inspect  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
from _tmp import tmpdir  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.core import texts  # noqa: E402


class Group:
    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


grp = Group()
takes = inspect.signature(errwatch.ErrorKindAlert.__init__).parameters
hw = errwatch.ErrorKindAlert(grp, lambda: False, tmpdir(),
                             **{k: v for k, v in {"known": {}, "pace": 0}.items() if k in takes})
logging.getLogger(errwatch.ARK).addHandler(hw)
skland.bindings = lambda c: [
    {"appCode": "endfield", "bindingList": [{"uid": "1", "roles": [{"roleId": "1001", "serverId": "1"},
                                                                    {"roleId": "2002", "serverId": "2"}]}]},
    {"appCode": "arknights", "bindingList": [{"uid": "19237299"}]},
]
resources._session["sk"] = None
got = resources.skland_session(Tok)
t0 = time.monotonic()
while not grp.sent and time.monotonic() - t0 < 3:
    time.sleep(0.02)
time.sleep(0.1)
logging.getLogger(errwatch.ARK).removeHandler(hw)
hw.close()
check("没猜：会话里没有终末地角色", ("efRole" in got, got.get("uid")), (False, "19237299"))
MULTI = getattr(texts, "SKLAND_MULTI_ROLE", "⚠️ 森空岛给了不止一个终末地角色，没有读")
check("报群一条，标题是它自己的", [(t, a) for t, _, a in grp.sent], [(MULTI, True)])
check("正文说几个、编号，没读", bool(grp.sent) and "森空岛这次给了 2 个终末地角色（角色编号 1001、2002）" in grp.sent[0][1], True)
check("正文不说「服务器」", bool(grp.sent) and "服务器" in grp.sent[0][1], False)
check("正文是人话", [texts.plain(b) for _, b, _ in grp.sent], [[]])
check("拒绝是单独的一类（按类型认，不按字）", issubclass(getattr(skland, "SklandMultiRole", RuntimeError),
                                                skland.SklandError), True)

print("\n[今天：从账目数]")


class St:
    def read_ledger(self, day):
        return [{"run_id": "a", "script": "MAA", "ok": True}, {"run_id": "b", "script": "OK-WW", "ok": False},
                {"run_id": "c", "script": "MaaEnd", "ok": True}]


check("跑了 3 失败 1 最近 MaaEnd", resources.today(St(), "2026-09-15"), {"跑了": 3, "失败": 1, "最近": "MaaEnd"})


class StStop:
    """2026-09-30: the 停一切 press stopped MaaEnd (ok=False) - not a failure."""

    def read_ledger(self, day):
        return [{"run_id": "a", "script": "OK-WW", "ok": False, "raw": {"okww_error": "x"}},
                {"run_id": "b", "script": "OK-WW", "ok": True, "raw": {"manual_stop": "09:46 停一切"}},
                {"run_id": "c", "script": "MaaEnd", "ok": False, "raw": {"manual_stop": "09:46 停一切"}}]


check("停一切停掉的不算失败（跑了 3 失败 1）", resources.today(StStop(), "2026-09-30"),
      {"跑了": 3, "失败": 1, "最近": "MaaEnd"})

print("\n[today: failures by the daily headline's rule, on the machine's ledgers]")
# Audit 11 (2026-10-13): the App showed 「失败 1 趟」 on 10-06 and 10-07 for a MaaEnd
# self-update restart (transitional; episode_kinds 「update」) while the daily
# report said all green. Ledgers copied from the machine's state/ on 10-13.
import json  # noqa: E402
import shutil  # noqa: E402

from _tmp import tmpdir  # noqa: E402
from ark_relay.core.ledger import State  # noqa: E402

LEDGERS = Path(__file__).resolve().parent / "fixtures" / "phone-ledgers"
real_dir = tmpdir()
for f in LEDGERS.glob("ledger-*.jsonl"):
    shutil.copy(f, real_dir / f.name)
check("10-06: 5 runs, the update restart is not a failure",
      resources.today(State(real_dir), "2026-10-06"), {"跑了": 5, "失败": 0, "最近": "MAA"})
check("10-07: 5 runs, the update restart is not a failure",
      resources.today(State(real_dir), "2026-10-07"), {"跑了": 5, "失败": 0, "最近": "MAA"})
# A real failure on the same day is still counted.
day06 = [json.loads(x) for x in (LEDGERS / "ledger-2026-10-06.jsonl").read_text(encoding="utf-8").splitlines()]
bad = dict(day06[1], run_id="2026-10-06/wuwa/OK-WW-12-00-00", started="2026-10-06T12:00:00+08:00",
           ok=False, failed_tasks=["每日任务"])
(real_dir / "ledger-2026-10-06.jsonl").write_text(
    "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in [*day06, bad]), encoding="utf-8")
check("a real failure still counts", resources.today(State(real_dir), "2026-10-06")["失败"], 1)
# The same failure inside a run-one.sh --test window is not the day's failure.
(real_dir / "test-windows.json").write_text(json.dumps(
    [{"since": "2026-10-06T11:55:00+08:00", "until": "2026-10-06T12:30:00+08:00", "what": "OK-WW"}]),
    encoding="utf-8")
check("a failure inside a test window does not count",
      resources.today(State(real_dir), "2026-10-06")["失败"], 0)

print("\n[开机推送和停止前推送同时要会话：#10 不会读到做了一半的体力]")
# 2026-10-10 16:32:53 the stop notice came 7 s after boot: the boot state and the
# 停止前 state both asked for the session while none existed yet, both logged in and
# both ran _probe_stamina; check #10 read probe() between one call's 「at」 and its
# dungeon and pushed 「终末地体力没读到：没读」 (relay.log 16:32:55-16:32:58).
import threading  # noqa: E402

calls["login"] = 0
reads = {"n": 0}
skland.bindings = lambda c: [
    {"appCode": "endfield", "bindingList": [{"uid": "1", "roles": [{"roleId": "1001", "serverId": "1"}]}]},
    {"appCode": "arknights", "bindingList": [{"uid": "19237299"}]},
]
_REAL_CARD = getattr(skland, "endfield_card", None)


def slow_card(cred, role, server):
    reads["n"] += 1
    time.sleep(0.3)
    return {"detail": {"dungeon": {"curStamina": 1, "maxStamina": 360, "maxTs": 2}}}


skland.endfield_card = slow_card
resources._session["sk"] = None
seen = []


def watch():
    t_end = time.monotonic() + 1.5
    while time.monotonic() < t_end:
        p = resources.probe()
        if p.get("at") and "dungeon" not in p and "错误" not in p:
            seen.append(p)
        time.sleep(0.005)


w = threading.Thread(target=watch)
w.start()
ts = [threading.Thread(target=resources.skland_session, args=(Tok,)) for _ in range(2)]
for t in ts:
    t.start()
for t in ts:
    t.join()
w.join()
check("没有哪一刻是「有时间、没体力也没原因」", seen[:1], [])
check("读完 probe 里有体力", "dungeon" in resources.probe(), True)
if _REAL_CARD is not None:
    skland.endfield_card = _REAL_CARD

skland.get_did, skland.login, skland.refresh, skland.bindings = _REAL

print("[today: the ledger cannot be read]")
import logging  # noqa: E402


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.n = 0

    def emit(self, record):
        self.n += 1


class StBroken:
    def read_ledger(self, day):
        raise OSError("ledger locked")


_g = _Grab()
resources.log.addHandler(_g)
getattr(resources, "_last_error", {}).clear()
got = resources.today(StBroken(), "2026-10-10")
check("unreadable -> no counts (no fake 0 failures), an error key", (got.get("失败"), "错误" in got), (None, True))
check("unreadable -> one WARNING", _g.n, 1)
resources.today(StBroken(), "2026-10-10")
check("same condition again -> no second WARNING", _g.n, 1)
resources.today(St(), "2026-09-15")
resources.today(StBroken(), "2026-10-10")
check("broken again after a good read -> WARNING again", _g.n, 2)
resources.log.removeHandler(_g)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
