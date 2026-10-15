"""The relay keeps the App's need table current by itself (needtable.py).

Until 2026-10-14 the table was rebuilt only when someone ran scripts/mac/build-need-tables.py
and deploy-web.sh by hand; the last run was 09-23, and the two six-stars announced since
(祀, 明河) never reached the App. Pinned here:

* the object's name is the phone state's hash + `.need.json` (the App derives the same:
  ark-remote Relay.needURL; the hex for "ark-test-topic" is pinned on both sides);
* a due day builds once, on a thread of its own, and PUTs the table public-read (cos_put's
  default) with the state's timeout; a day that has its table does not build again; the next does;
* a build or a PUT that fails is an INFO line and a red item in the technical log (not a
  WARNING: every WARNING goes to the owner's group, and a table a day old is nothing he must
  act on), never raises, and is tried once more the same day at least 30 min later - at most
  two builds a server day, even when the mark file cannot be written;
* a build that works after one or more server days without a table is one WARNING marked
  errwatch.recovered() (daily report only) naming the days missed; three such days in a row
  are one plain WARNING (the group), not repeated until a build works again;
* a machine without a topic, COS or Skland token builds nothing and says so at INFO;
* the engine's tick runs the step.

No network: the table is built offline from fixtures/skland-endfield-1015 (祀 current, 明河 next;
skland-endfield-1014 until the 2026-10-15 two-standard caliber), the PUT is a recorder.
"""
import inspect
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


def done():
    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


try:
    from ark_relay.features.needtable import build, needtable
except ImportError as exc:
    check("the relay has a need-table step (ark_relay.features.needtable)", str(exc), "")
    done()
from ark_relay.core import engine, techlog  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.phone.cos_store import state_key  # noqa: E402
from ark_relay.features.phone.mailbox import Mailbox  # noqa: E402

FIX15 = HERE / "fixtures" / "skland-endfield-1015"
D1 = datetime(2026, 10, 14, 9, 0, tzinfo=SERVER_TZ)
D2, D3, D4, D5, D6, D7, D8, D9 = (datetime(2026, 10, d, 9, 0, tzinfo=SERVER_TZ) for d in range(15, 23))


class Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.rows = []

    def emit(self, record):
        self.rows.append((record.levelname, record.getMessage(), bool(getattr(record, errwatch.RECOVERED, False))))


rec = Records()
needtable.log.addHandler(rec)
needtable.log.setLevel(logging.DEBUG)
needtable.log.propagate = False


def cfg_with(topic="ark-test-topic", token="test-token"):
    # state/ inside its own temp dir: the technical log goes next to it (techlog.tech_dir)
    d = tmpdir() / "state"
    d.mkdir()
    return SimpleNamespace(state_dir=d, phone_topic=topic, skland_token=token)


def reds(c):
    """The red items the need table wrote to the day's technical log."""
    try:
        text = techlog.path_for("2026-10-14", c.state_dir).read_text(encoding="utf-8")
    except OSError:
        return []
    return [t for _, t in techlog.unhandled(text)]


def offline():
    return build.make(build.RulesSource(FIX15, None))


puts = []


def put_ok(cos, key, data, timeout):
    puts.append((cos, key, data, timeout))
    return None


print("[名字：和手机状态同一个哈希，后缀 .need.json；App 那边算出同一个]")
check("need_key", needtable.need_key("ark-test-topic"), "state/d980719e5e0b17d6d61cc31f7b36a714.need.json")
check("与 state_key 同一个哈希", needtable.need_key(" Ark-Test-Topic "), state_key("ark-test-topic")[:-5] + ".need.json")

print("\n[到期的一天：建一次、放上 COS（公开读，状态的超时）]")
c = cfg_with()
check("没建过就到期", needtable.due(c.state_dir, "2026-10-14"), True)
ok = needtable.refresh(c, D1, make=offline, cos="COS", put=put_ok)
check("建好并放上", ok, True)
check("放了一次", len(puts), 1)
cos, key, data, timeout = puts[0]
check("放的位置", (cos, key), ("COS", needtable.need_key("ark-test-topic")))
check("超时同手机状态", timeout, Mailbox.COS_TIMEOUT)
table = json.loads(data.decode("utf-8"))
check("内容就是祀（当前）+ 明河（下一位）那张表", ([x["name"] for x in table["games"][0]["standards"]], table["built"]),
      (["祀", "明河"], "2026-10-15 16:05 UTC+8"))
check("cos_put 默认公开读（App 没有 COS 钥匙）",
      inspect.signature(needtable.cos_put).parameters["public"].default, True)
check("当天不再到期", needtable.due(c.state_dir, "2026-10-14"), False)
check("第二天又到期", needtable.due(c.state_dir, "2026-10-15"), True)
check("成功是一行 INFO", [r for r in rec.rows if r[0] != "INFO"], [])

print("\n[引擎的那一步：到期才起线程，同一天不起第二次]")
needtable._running.clear()
c2 = cfg_with()
started = []


def fake_start(fn):
    started.append(fn)


check("到期：起一个", needtable.step(c2, D1, start=fake_start), True)
started[0]()   # the thread's work, run here: this config has no COS, so it ends at INFO without the network
check("到期那次跑完记了当天", needtable.due(c2.state_dir, "2026-10-14"), False)
check("同一天：不起", needtable.step(c2, D1, start=fake_start), False)
check("第二天：再起", needtable.step(c2, D2, start=fake_start), True)
src = inspect.getsource(engine.Engine.tick)
check("tick 里有这一步", '("需求表", self._need_table)' in src, True)
check("这一步调 needtable.step", "needtable.step(self.cfg)" in inspect.getsource(engine.Engine._need_table), True)

print("\n[第一次建不成：INFO + 技术日志红项，不推送；表还是上次的]")
rec.rows.clear()
puts.clear()
c3 = cfg_with()
T = "2026-10-14"


def broken():
    raise RuntimeError("明河: cannot pick hers")


def mins(m, base=D1):
    return base + timedelta(minutes=m)


check("建不成返回 False", needtable.refresh(c3, D1, make=broken, cos="COS", put=put_ok), False)
check("没放（COS 上留着上次那份）", puts, [])
check("一条 INFO，带原因，没有 WARNING", [(lv, "cannot pick hers" in m) for lv, m, _ in rec.rows], [("INFO", True)])
check("技术日志一条红项，带原因", [("cannot pick hers" in t) for t in reds(c3)], [True])
check("30 分钟内不再试", needtable.due(c3.state_dir, T, mins(10)), False)
check("30 分钟后再试一次", needtable.due(c3.state_dir, T, mins(31)), True)

print("\n[当天只再试一次：一天最多建两次]")
rec.rows.clear()
check("第二次也建不成", needtable.refresh(c3, mins(31), make=broken, cos="COS", put=put_ok), False)
check("还是 INFO", {lv for lv, _, _ in rec.rows}, {"INFO"})
check("第二条红项", len(reds(c3)), 2)
check("当天不再到期", needtable.due(c3.state_dir, T, mins(240)), False)
check("第二天又到期", needtable.due(c3.state_dir, "2026-10-15", D2), True)
rec.rows.clear()
c3b = cfg_with()
check("放不上返回 False", needtable.refresh(c3b, D1, make=offline, cos="COS", put=lambda *a: "回 403"), False)
check("放不上也是 INFO，带原因", [(lv, "回 403" in m) for lv, m, _ in rec.rows], [("INFO", True)])
check("放不上也记红项", [("回 403" in t) for t in reds(c3b)], [True])


def fail_day(c, day, tries=2):
    for i in range(tries):
        needtable.refresh(c, mins(31 * i, day), make=broken, cos="COS", put=put_ok)


def warnings():
    return [(m, recovered) for lv, m, recovered in rec.rows if lv == "WARNING"]


print("\n[连着三个服务器日没建成：一条进群的 WARNING，之后不再重复]")
rec.rows.clear()
c5 = cfg_with()
fail_day(c5, D1)
fail_day(c5, D2)
fail_day(c5, D3, tries=1)
check("两天半：还没有 WARNING", warnings(), [])
needtable.refresh(c5, mins(31, D3), make=broken, cos="COS", put=put_ok)
w = warnings()
check("第三天也没建成：一条 WARNING", len(w), 1)
check("它进群（没标自己好了），说 3 天", [(r, "3" in m) for m, r in w], [(False, True)])
fail_day(c5, D4)
check("第四天：不再发", len(warnings()), 1)

print("\n[失败几天后建成：一条标「自己好了」的 WARNING（只进日报），说漏了几天]")
rec.rows.clear()
check("第五天建成", needtable.refresh(c5, D5, make=offline, cos="COS", put=put_ok), True)
w = warnings()
check("一条 WARNING，标自己好了", [r for _, r in w], [True])
check("说漏了 4 天", ["4 天" in m for m, _ in w], [True])
rec.rows.clear()
needtable.refresh(c5, D6, make=offline, cos="COS", put=put_ok)
check("再下一天建成：没有 WARNING", warnings(), [])
fail_day(c5, D7)
fail_day(c5, D8)
fail_day(c5, D9)
check("成功清零后，再连着三天没成：又一条进群的 WARNING", [r for _, r in warnings()], [False])
rec.rows.clear()
c6 = cfg_with()
needtable.refresh(c6, D1, make=broken, cos="COS", put=put_ok)
check("当天重试建成：不算漏了一天，没有 WARNING",
      (needtable.refresh(c6, mins(31), make=offline, cos="COS", put=put_ok), warnings()), (True, []))
c7 = cfg_with()
fail_day(c7, D1)
needtable.refresh(c7, D2, make=offline, cos="COS", put=put_ok)
check("漏了一天后建成：一条自己好了的 WARNING，说 1 天", [(r, "1 天" in m) for m, r in warnings()], [(True, True)])

print("\n[没有森空岛令牌：INFO 一句，不建，当天不再试]")
rec.rows.clear()
puts.clear()
c8 = cfg_with(token="")
called = []
check("没令牌返回 False",
      needtable.refresh(c8, D1, make=lambda: called.append(1) or offline(), cos="COS", put=put_ok), False)
check("没建、没放", (len(called), len(puts)), (0, 0))
check("只是 INFO", {lv for lv, _, _ in rec.rows}, {"INFO"})
check("当天不再到期", needtable.due(c8.state_dir, T, mins(240)), False)

print("\n[记号写不进去：一天照样最多建两次]")
needtable._running.clear()
c9 = cfg_with()    # no COS: each build ends at INFO, no network
real_write = needtable.atomic_write_text


def no_disk(*a, **k):
    raise OSError("disk full")


needtable.atomic_write_text = no_disk
starts = []
try:
    for m in (0, 5, 31, 40, 62, 180, 360, 840):   # 09:00 to 23:00 of one server day
        needtable.step(c9, mins(m), start=lambda fn: (starts.append(1), fn()))
    check("同一天起了 2 次", len(starts), 2)
    needtable.step(c9, D2, start=lambda fn: (starts.append(1), fn()))
    check("第二天又能起", len(starts), 3)
finally:
    needtable.atomic_write_text = real_write

print("\n[机器上建表：把装着的 MaaEnd 交给建表（基质建议读它自己的数据）]")
seen = {}
real_rs, real_make = build.RulesSource, build.make
build.RulesSource = lambda offline, save, token="", maaend_dir=None: seen.update(token=token, maaend_dir=maaend_dir) or "SRC"
build.make = lambda src, **k: {"src": src}
try:
    got = needtable._live_table(SimpleNamespace(skland_token="tok", maaend_dir=Path("D:/ark/maaend")))
finally:
    build.RulesSource, build.make = real_rs, real_make
check("令牌和 MaaEnd 目录都交过去", (got, seen), ({"src": "SRC"}, {"token": "tok", "maaend_dir": Path("D:/ark/maaend")}))

print("\n[没配信箱或 COS 的机器：不建，INFO 说一句]")
rec.rows.clear()
puts.clear()
c10 = cfg_with(topic="")
check("没 topic", needtable.refresh(c10, D1, make=offline, cos="COS", put=put_ok), False)
c11 = cfg_with()
c11.cos_secret_id = ""
check("没 COS", needtable.refresh(c11, D1, make=offline, put=put_ok), False)
check("都只是 INFO", {lv for lv, _, _ in rec.rows}, {"INFO"})
check("没放", puts, [])

done()
