"""A task a person started at AUTO-MAS that retried inside itself gives one outcome.

2026-10-16 (machine clock), AUTO-MAS task c6d40887 (app.log 13:21:27 「创建任务: …,
触发来源: manual_task」, no relay start in state/relay-dispatches.json) ran MaaEnd
three times: 「原配置阶段尝试次数: 1/3」 13:21:28 -> MaaEnd-09-21-28 游戏启动失败;
「2/3」 13:23:36 -> MaaEnd-09-23-36 转交委托、选剑演武、基质刷取 failed; MaaEnd's
update install (MaaEnd-09-53-01, not a run); 「3/3」 13:53:33 -> MaaEnd-09-53-33
Success!. AUTO-MAS wrote all four records at the task's end, 14:11:40. The relay
pushed each failed attempt as its own final failure: relay.log 14:11:55 and 14:12:04
「❌ MaaEnd 失败」, both saying 「这一趟是有人在 AUTO-MAS 上手动开的」, although the
third attempt redid every failed step. (Its 14:12:12 「⚠️ 这一轮没干完」 came from
the outcome check on 基质刷取, a separate matter; stubbed here.)

The scheduled path folds such attempts: held, replaced by the next failure, healed
by a later success (daily report only), only the last failure pushed. These are
the real records (tests/fixtures/hand-started-1016/, dates moved to today: a
make-up is only for a failure of today, so the no-make-up checks mean something).
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

FX = Path(__file__).resolve().parent / "fixtures" / "hand-started-1016"
REAL_DAY = "2026-10-16"
TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "debug").mkdir()
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
HIST = TMP / "history"
HIST.mkdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import collector, texts                     # noqa: E402
from ark_relay.core import engine as eng_mod                    # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config             # noqa: E402
from ark_relay.core.ledger import State                         # noqa: E402
from ark_relay.features.alarm import handle                     # noqa: E402
from ark_relay.features.makeup import collect_retry, makeup, marker  # noqa: E402
from ark_relay.features.selfcheck import machinecheck as _mc    # noqa: E402

_mc.load()
_mc_real = dict(_mc.CHECKS)
_mc.CHECKS.clear()     # machine checks have their own tests (tests/test_mc_*.py)

TODAY = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
TASK = "c6d40887-2c99-43e7-9bbf-a94f9bf49d6d"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def moved(data: bytes) -> bytes:
    return data.replace(REAL_DAY.encode(), TODAY.encode())


(AUTOMAS / "debug" / "app.log").write_bytes(moved((FX / "app.log").read_bytes()))
DAY_DIR = HIST / TODAY / "endfield"
DAY_DIR.mkdir(parents=True)
for f in (FX / "history" / REAL_DAY / "endfield").iterdir():
    (DAY_DIR / f.name).write_bytes(moved(f.read_bytes()))


class Notes:
    def __init__(self):
        self.sent, self.down = [], False

    def send(self, title, body="", **kw):
        if self.down:
            return ["企业微信机器人 超时"]
        self.sent.append((title, body, kw.get("alert", False)))
        return []


handle._ship_evidence = lambda eng, rec: ""
handle._weekly_gates = lambda eng, rec: None
handle._push_unverified = lambda eng, rec: None   # task screenshots are not in the fixture
handle._check_d3d11_after_maaend = lambda: None
collect_retry.restore_master = lambda cfg: ""
dispatched = []
makeup._dispatch = lambda script: (dispatched.append(script), (True, "ok"))[1]
makeup._kill_game = lambda: None


def build(state_dir=None):
    cfg = Config()
    cfg.state_dir = state_dir or tmpdir()
    cfg.automas_dir = AUTOMAS
    cfg.history_dir = HIST
    e = eng_mod.Engine(cfg, source=type("Src", (), {"fetch": lambda self, seen: []})(),
                       state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._unfinished_queues = lambda now, entries: []
    e._deferred_update_busy = lambda: False
    e._verify_outcome = lambda r: None
    e._archive_maaend_evidence = lambda r: None
    return e


def alarms(e):
    return [(t, b) for t, b, a in e.notifier.sent if a]


def held_id(e, where="_pending"):
    r = getattr(e, where).get(KEY)
    return r.run_id if r is not None else None


def records(*stems):
    got = collector.scan(HIST, set())
    return [r for r in got if not stems or r.run_id.rsplit("/", 1)[-1].removeprefix("MaaEnd-") in stems]


KEY = ("MaaEnd", "endfield")
FIRST, SECOND, THIRD = (f"{TODAY}/endfield/MaaEnd-{s}" for s in ("09-21-28", "09-23-36", "09-53-33"))

print("[the real records: three runs reach the relay, all in task c6d40887]")
recs = records()
check("09-53-01 (the update install) is not a run; the other three are, in start order",
      [r.run_id for r in recs], [FIRST, SECOND, THIRD])
check("results as AUTO-MAS wrote them", [(r.ok, r.raw.get("maaend_result")) for r in recs],
      [(False, "游戏启动失败"), (False, "MaaEnd 部分任务执行失败: 🚚转交委托、🗡️选剑演武、🎱基质刷取"),
       (True, "Success!")])

print("\n[the whole task lands in one tick: one outcome, the work got done -> nothing in the group]")
e = build()
for r in records():
    handle._handle(e, r)
e._flush_pending()
makeup.maybe_run(e)
check("all three booked as started by hand, task c6d40887",
      [x.get("raw", {}).get("hand_started") for x in e.state.read_ledger(TODAY)], [TASK] * 3)
check("no alarm in the group (relay.log 14:11:55 / 14:12:04 pushed two ❌)", alarms(e), [])
check("nothing left held", dict(e._pending), {})
check("nothing left to heal", dict(e._recovered), {})
check("no make-up dispatched", dispatched, [])
check("no make-up marker written", makeup.read_marker(e.cfg.state_dir, TODAY), {})

print("\n[step by step: 09-21-28 held, replaced by 09-23-36, healed by 09-53-33]")
e = build()
r1, r2, r3 = records()
handle._handle(e, r1)
check("09-21-28 (游戏启动失败) is held, not pushed", (held_id(e),
                                                  alarms(e)), (FIRST, []))
check("held, it gets no make-up", (marker.candidates(e), KEY in e._pending and makeup.holding(e, e._pending[KEY])),
      ([], False))
handle._handle(e, r2)
check("09-23-36 replaces it (same task), still nothing pushed",
      (held_id(e), alarms(e)), (SECOND, []))
handle._handle(e, r3)
check("09-53-33's success heals the held 09-23-36: off the queue, onto the self-heal path",
      (KEY in e._pending, held_id(e, "_recovered")), (False, SECOND))
e._flush_pending()
check("the flush says it in the log only", (alarms(e), dict(e._recovered)), ([], {}))

print("\n[no later success in the task -> exactly one ❌, about the last failure, saying whose run]")
e = build()
for r in records("09-21-28", "09-23-36"):
    handle._handle(e, r)
check("nothing pushed while the records are booked", alarms(e), [])
e._flush_pending()
makeup.maybe_run(e)
got = alarms(e)
check("one alarm", [t for t, _ in got], [texts.failed("MaaEnd")])
body = got[0][1] if got else ""
check("first line: started by hand", body.splitlines()[:1], [texts.HAND_STARTED_NOTE])
check("names the last attempt's failed tasks", ("转交委托" in body, "选剑演武" in body, "基质刷取" in body),
      (True, True, True))
check("not about 游戏启动失败 (the replaced attempt)", "游戏启动失败" in body, False)
check("no make-up dispatched, no marker", (dispatched, makeup.read_marker(e.cfg.state_dir, TODAY)), ([], {}))
check("queue empty", dict(e._pending), {})

print("\n[the task is still running when a record lands -> nothing pushed until it stops]")
e = build()
running = {"MaaEnd"}
e._script_running = lambda name: name in running
e._scripts_running = lambda: bool(running)
for r in records("09-21-28"):
    handle._handle(e, r)
e._flush_pending()
check("still running: held, nothing pushed", (KEY in e._pending, alarms(e)), (True, []))
running.clear()
e._flush_pending()
check("stopped with no later record: one ❌ saying started by hand",
      [(t, b.splitlines()[0]) for t, b in alarms(e)], [(texts.failed("MaaEnd"), texts.HAND_STARTED_NOTE)])

print("\n[the group robot is down at the flush: kept held, no make-up meanwhile, sent next tick]")
e = build()
for r in records("09-21-28", "09-23-36"):
    handle._handle(e, r)
e.notifier.down = True
e._flush_pending()
makeup.maybe_run(e)
check("not sent, still held", (alarms(e), held_id(e)), ([], SECOND))
check("no make-up dispatched for a person's run", dispatched, [])
check("no make-up marker written", makeup.read_marker(e.cfg.state_dir, TODAY), {})
check("shutdown counts it as an alarm still to go out (not a make-up to wait for)",
      [r.run_id for r in e._pending.values() if not makeup.holding(e, r)], [SECOND])
# A relay restart in between (a deploy): the hold survives with its task id.
e2 = build(e.cfg.state_dir)
check("restored from disk with its task id", (e2._pending.get(KEY).raw if KEY in e2._pending else {}).get("hand_started"), TASK)
e2._flush_pending()
check("robot back: exactly one ❌ saying started by hand",
      [(t, b.splitlines()[0]) for t, b in alarms(e2)], [(texts.failed("MaaEnd"), texts.HAND_STARTED_NOTE)])
e2._flush_pending()
check("not sent twice", len(alarms(e2)), 1)

print("\n[the last attempt ran but left items undone -> only that round's ⚠️, the earlier failures healed]")
e = build()
e._verify_outcome = lambda r: "MaaEnd 这一轮有 1 项没干成" if r.ok else None
for r in records():
    handle._handle(e, r)
e._flush_pending()
check("one ⚠️ about the round, no ❌", [t for t, _ in alarms(e)], [texts.ROUND_INCOMPLETE])
check("held failure healed, not pushed", (dict(e._pending), dict(e._recovered)), ({}, {}))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
_mc.CHECKS.update(_mc_real)
sys.exit(1 if fails else 0)
