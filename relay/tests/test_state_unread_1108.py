"""Reads put off with nothing to bring them back (dispatch relay-audit-round2-1108 N-02 / N-05).

N-02, the running half of 08635a7b (its boot half stays shelved, BOARD D-1017): state.json
refusing reads (a lock outlasting LOCK_WAITS, any OSError) was one INFO line per refused read
and nothing else - a lock that never let go kept every write failing, the relay silent and the
machine on. Pinned here:

* a refused read starts a run: one INFO line, statestore.refused_since names when; a plain
  read still answers with the last good copy, a write still raises;
* while the run lasts every read tries the file again (the cached copy is not served);
* UNREAD_WARN_S (600 s, the relay's other outage marks) after the first refusal: one WARNING
  (the group), not repeated while the same run lasts; a read that gets through ends the run
  with one INFO line, and a later lock is a new run;
* engine.next_deadline wakes the loop UNREAD_RETRY_S (45 s) later while the run lasts.

N-05: the need table's same-day second try (「过半小时再试一次」) and AUTO-MAS records the
last scan put off (a missing log, a history.db read that failed) had no moment either; the
loop slept to the hour backstop. needtable.next_moment / collector.next_moment and their
place in next_deadline are pinned here too.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _tmp import tmpdir  # noqa: E402

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(TMP / "history").mkdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"),
                  SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                  WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(HERE.parent))

from ark_relay.core import collector, statestore  # noqa: E402
from ark_relay.core import engine as eng  # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config  # noqa: E402
from ark_relay.core.ledger import State  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.features.needtable import needtable  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


class Rows(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.rows = []

    def emit(self, record):
        self.rows.append((record.levelname, record.getMessage(), bool(getattr(record, errwatch.RECOVERED, False))))


rows = Rows()
statestore.log.addHandler(rows)
statestore.log.setLevel(logging.DEBUG)
statestore.log.propagate = False

clock = [1000.0]
import time as _time  # noqa: E402
statestore.time = SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda s: None, time=_time.time)
REAL_READ = Path.read_text
lock = {"on": False, "tries": 0}


def read_text(self, *a, **kw):
    if lock["on"] and self.name == statestore.FILE:
        lock["tries"] += 1
        raise PermissionError(13, "being used by another process (test)")
    return REAL_READ(self, *a, **kw)


Path.read_text = read_text


def levels():
    return [lv for lv, _, _ in rows.rows]


d = tmpdir() / "state"
st = statestore.StateStore(d)
st.update("weekly", "garden", lambda _: {"done_week": "2026-W45"})
path = d / statestore.FILE

print("[读不出来：一条 INFO，接着用上次读到的，写照样报错]")
rows.rows.clear()
lock["on"] = True
lock["tries"] = 0
check("同一个实例、文件没变：直接用它手上那份，不去读", (st.get("weekly", "garden"), lock["tries"]),
      ({"done_week": "2026-W45"}, 0))
check("…不算读不出来", statestore.refused_since(path), None)
# Most call sites build a StateStore per call: that one reads the file.
check("新建的实例读不出来：拿到的是上次读到的那份", statestore.StateStore(d).get("weekly", "garden"),
      {"done_week": "2026-W45"})
check("记下了从什么时候开始读不出来", statestore.refused_since(path), 1000.0)
check("一条 INFO", levels(), ["INFO"])
raised = ""
try:
    st.update("weekly", "garden", lambda _: {"done_week": "2026-W46"})
except OSError as exc:
    raised = type(exc).__name__
check("写不进去就报错（不拿空的盖上去）", raised, "PermissionError")
lock["tries"] = 0
st.get("weekly", "garden")
check("读不出来期间每次读都再去读文件（不用缓存）", lock["tries"], 1)
check("还是只有那一条 INFO", levels(), ["INFO"])

print("\n[连着 10 分钟读不出来：一条进群的 WARNING，同一段里不再重复]")
check("和别的中断报警同一个时长", (statestore.UNREAD_WARN_S, statestore.UNREAD_RETRY_S), (600, 45))
from ark_relay.features.phone.mailbox import Mailbox  # noqa: E402
check("就是 Mailbox.OUTAGE_SEC", float(statestore.UNREAD_WARN_S), float(Mailbox.OUTAGE_SEC))
clock[0] = 1000.0 + 599
st.get("weekly", "garden")
check("599 秒：还没有 WARNING", "WARNING" in levels(), False)
clock[0] = 1000.0 + 600
st.get("weekly", "garden")
w = [(m, r) for lv, m, r in rows.rows if lv == "WARNING"]
check("600 秒：一条 WARNING，没标自己好了，说 10 分钟、带原因",
      [(r, "10 分钟" in m, "PermissionError" in m) for m, r in w], [(False, True, True)])
clock[0] = 1000.0 + 1800
st.get("weekly", "garden")
check("再过 20 分钟：不再发第二条", levels().count("WARNING"), 1)

print("\n[读回来了：一条 INFO，说之前报过；再锁住是新的一段]")
lock["on"] = False
rows.rows.clear()
check("读得到", st.get("weekly", "garden"), {"done_week": "2026-W45"})
check("不再记着读不出来", statestore.refused_since(path), None)
check("一条 INFO，说持续了多久、之前报过",
      [(lv, "30 分钟" in m and "已报过" in m) for lv, m, _ in rows.rows], [("INFO", True)])
st.update("weekly", "garden", lambda _: {"done_week": "2026-W46"})
check("又写得进去", json.loads(REAL_READ(path, encoding="utf-8"))["weekly"]["garden"], {"done_week": "2026-W46"})
lock["on"] = True
clock[0] = 5000.0
rows.rows.clear()
statestore.StateStore(d).get("weekly", "garden")
check("再锁住：新的一段从这次算起", statestore.refused_since(path), 5000.0)
clock[0] = 5000.0 + 600
st.get("weekly", "garden")
check("新的一段到 10 分钟：又一条 WARNING", levels().count("WARNING"), 1)
lock["on"] = False
st.get("weekly", "garden")

print("\n[主循环：读不出来时 45 秒后再醒一次]")


def build():
    cfg = Config()
    cfg.state_dir = tmpdir()
    e = eng.Engine(cfg, source=SimpleNamespace(fetch=lambda seen: []), state=State(cfg.state_dir),
                   notifier=SimpleNamespace(send=lambda *a, **k: False))
    e._scripts_running = lambda: False
    return e


NOW = datetime(2026, 11, 8, 10, 0, tzinfo=SERVER_TZ)
e = build()
got = e.next_deadline(NOW)
check("读得到时：没有重读的闹钟", "重读 state.json" in (got[1] if got else ""), False)
e.state.store.update("weekly", "garden", lambda _: {"done_week": "2026-W45"})
lock["on"] = True
statestore.StateStore(e.cfg.state_dir).get("weekly", "garden")
got = e.next_deadline(NOW)
check("读不出来时：45 秒后重读", got, (NOW + timedelta(seconds=45), "重读 state.json"))
lock["on"] = False
e.state.store.get("weekly", "garden")
check("读回来后闹钟就没了", "重读 state.json" in (e.next_deadline(NOW) or (None, ""))[1], False)
Path.read_text = REAL_READ

print("\n[需求表：当天第一次没成，半小时后叫醒主循环去试第二次]")
needtable._running.clear()
nd = tmpdir()
check("今天还没建过：没有这个闹钟", needtable.next_moment(nd, NOW), None)
(nd / needtable.MARK).write_text(json.dumps({"day": "2026-11-08", "ok": False, "skip": False, "tries": 1,
                                             "last_at": (NOW - timedelta(minutes=5)).isoformat()}),
                                 encoding="utf-8")
check("第一次没成：失败后 30 分钟", needtable.next_moment(nd, NOW),
      (NOW + timedelta(minutes=25), "终末地需求表当天第二次重算"))
check("到点之后不再给过去的时刻（这一轮就会去试）", needtable.next_moment(nd, NOW + timedelta(minutes=26)), None)
e2 = build()
e2.cfg.state_dir = nd
check("next_deadline 里有这个闹钟", e2.next_deadline(NOW), (NOW + timedelta(minutes=25), "终末地需求表当天第二次重算"))
for done in ({"ok": True}, {"skip": True}, {"tries": 2}, {"day": "2026-11-07"}):
    m = {"day": "2026-11-08", "ok": False, "skip": False, "tries": 1,
         "last_at": (NOW - timedelta(minutes=5)).isoformat(), **done}
    (nd / needtable.MARK).write_text(json.dumps(m), encoding="utf-8")
    check(f"不用再试（{done}）：没有闹钟", needtable.next_moment(nd, NOW), None)


class Alive:
    def is_alive(self):
        return True


needtable._running.update(thread=Alive(), day="2026-11-08", count=1)
check("正在建：最晚 30 分钟后看一眼", needtable.next_moment(nd, NOW), (NOW + timedelta(minutes=30), "看终末地需求表重算完没有"))
needtable._running.clear()

print("\n[AUTO-MAS 记录：缺日志等着补记、history.db 读不了，都要叫醒主循环]")
collector._put_off.clear()
collector._db_fail_streak[0] = 0
check("没有等着的：没有闹钟", collector.next_moment(NOW), None)
collector._put_off.extend([(NOW + timedelta(seconds=90)).timestamp(), (NOW + timedelta(seconds=30)).timestamp(),
                           (NOW - timedelta(seconds=5)).timestamp()])
check("缺日志的：最早那条到点时（过去的不算）", collector.next_moment(NOW), (NOW + timedelta(seconds=30), "补记缺日志的运行记录"))
collector._put_off.clear()
collector._db_fail_streak[0] = 1
check("history.db 读不了：45 秒后再读", collector.next_moment(NOW), (NOW + timedelta(seconds=45), "重读 AUTO-MAS 的 history.db"))
e3 = build()
check("next_deadline 里有它", e3.next_deadline(NOW), (NOW + timedelta(seconds=45), "重读 AUTO-MAS 的 history.db"))
collector._db_fail_streak[0] = 0

hist = TMP / "history2"
young = hist / "2026-11-08" / "MAA" / "10-00-00.json"
young.parent.mkdir(parents=True)
young.write_text("{}", encoding="utf-8")
collector.scan(hist, set())
check("扫到一条没日志的新记录：记下它 120 秒后补记", len(collector._put_off), 1)
check("…时刻就是它写下后 120 秒", round(collector._put_off[0] - young.stat().st_mtime), 120)
(young.with_suffix(".log")).write_text("", encoding="utf-8")
collector.scan(hist, set())
check("日志来了：不再等", collector._put_off, [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
