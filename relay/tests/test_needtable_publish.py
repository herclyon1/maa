"""The relay keeps the App's need table current by itself (needtable.py).

Until 2026-10-14 the table was rebuilt only when someone ran scripts/mac/build-need-tables.py
and deploy-web.sh by hand; the last run was 09-23, and the two six-stars announced since
(祀, 明河) never reached the App. Pinned here:

* the object's name is the phone state's hash + `.need.json` (the App derives the same:
  ark-remote Relay.needURL; the hex for "ark-test-topic" is pinned on both sides);
* a due day builds once, on a thread of its own, and PUTs the table public-read (cos_put's
  default) with the state's timeout; the same server day does not build again; the next does;
* a build or a PUT that fails is one WARNING (pushed), never raises, and is not retried
  the same day; a machine without a topic or COS builds nothing and says so at INFO;
* the engine's tick runs the step.

No network: the table is built offline from fixtures/skland-endfield-1014, the PUT is a recorder.
"""
import inspect
import json
import logging
import sys
from datetime import datetime
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
from ark_relay.core import engine  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.phone.cos_store import state_key  # noqa: E402
from ark_relay.features.phone.mailbox import Mailbox  # noqa: E402

FIX14 = HERE / "fixtures" / "skland-endfield-1014"
D1 = datetime(2026, 10, 14, 9, 0, tzinfo=SERVER_TZ)
D2 = datetime(2026, 10, 15, 9, 0, tzinfo=SERVER_TZ)


class Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.rows = []

    def emit(self, record):
        self.rows.append((record.levelname, record.getMessage()))


rec = Records()
needtable.log.addHandler(rec)
needtable.log.setLevel(logging.DEBUG)
needtable.log.propagate = False


def cfg_with(topic="ark-test-topic"):
    return SimpleNamespace(state_dir=tmpdir(), phone_topic=topic, skland_token="")


def offline():
    return build.make(build.RulesSource(FIX14, None))


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
check("内容就是明河那张表", (table["games"][0]["standards"][0]["name"], table["built"]), ("明河", "2026-10-14 03:36 UTC+8"))
check("cos_put 默认公开读（App 没有 COS 钥匙）",
      inspect.signature(needtable.cos_put).parameters["public"].default, True)
check("当天不再到期", needtable.due(c.state_dir, "2026-10-14"), False)
check("第二天又到期", needtable.due(c.state_dir, "2026-10-15"), True)
check("成功是一行 INFO", [r for r in rec.rows if r[0] != "INFO"], [])

print("\n[引擎的那一步：到期才起线程，同一天不起第二次]")
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

print("\n[建不成 / 放不上：一条 WARNING，不抛，当天不再试]")
rec.rows.clear()
puts.clear()
c3 = cfg_with()


def broken():
    raise RuntimeError("明河: cannot pick hers")


check("建不成返回 False", needtable.refresh(c3, D1, make=broken, cos="COS", put=put_ok), False)
check("没放", puts, [])
check("一条 WARNING，带原因", [(lv, "cannot pick hers" in m) for lv, m in rec.rows], [("WARNING", True)])
check("当天不再试", needtable.due(c3.state_dir, "2026-10-14"), False)
rec.rows.clear()
c4 = cfg_with()
check("放不上返回 False", needtable.refresh(c4, D1, make=offline, cos="COS", put=lambda *a: "回 403"), False)
check("一条 WARNING，带原因", [(lv, "回 403" in m) for lv, m in rec.rows], [("WARNING", True)])

print("\n[没配信箱或 COS 的机器：不建，INFO 说一句]")
rec.rows.clear()
c5 = cfg_with(topic="")
check("没 topic", needtable.refresh(c5, D1, make=offline, cos="COS", put=put_ok), False)
c6 = cfg_with()
c6.cos_secret_id = ""
check("没 COS", needtable.refresh(c6, D1, make=offline, put=put_ok), False)
check("都只是 INFO", {lv for lv, _ in rec.rows}, {"INFO"})
check("没放", puts, [])

done()
