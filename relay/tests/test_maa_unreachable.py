"""The collector writes raw['maa_unreachable'] on an MAA record that never got into
the game, by the same rule the make-up re-runs a round by (ledger #65).

Real AUTO-MAS records from tests/gamesim/corpus/maa/history:
  2026-09-23/MAA-05-00-01   「MAA 未能正确登录 PRTS」, MAA's log never reaches a stage:
                            flagged; makeup.maa_work_done says ''; check #65 passes and
                            pushes nothing; gameupdate.needs_rerun re-runs it.
  2026-08-26/MAA-11-03-30   「MAA 部分任务执行失败」 after fighting: not flagged.
  2026-09-23/MAA-05-03-07   「Success!」: not flagged.
  2026-08-26/MAA-05-16-47 then 2026-09-23/MAA-05-00-01, moved onto today's ledger
                            as one round: the first fought and used sanity
                            potions, the second never logged in. Neither the
                            make-up nor the re-run after a client update (flag
                            or maintenance) runs the round again; before the
                            round rule, needs_rerun read only the last record and
                            said yes.
Before the fix nothing wrote the flag, so the first case failed here and #65 went
to the group on the first real never-started round.

  python3 tests/test_maa_unreachable.py               this tree
  python3 tests/test_maa_unreachable.py --relay DIR   another relay tree (red proof)
"""
from __future__ import annotations

import gzip
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RELAY = HERE.parent
if "--relay" in sys.argv:
    RELAY = Path(sys.argv[sys.argv.index("--relay") + 1]).resolve()
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(HERE))

from _tmp import tmpdir  # noqa: E402
from ark_relay.core import collector  # noqa: E402
from ark_relay.core import engine as eng_mod  # noqa: E402
from ark_relay.core.config import Config  # noqa: E402
from ark_relay.core.ledger import State  # noqa: E402
from ark_relay.features.gameupdate import gameupdate  # noqa: E402
from ark_relay.features.makeup import makeup  # noqa: E402
from ark_relay.features.selfcheck import machinecheck as mc  # noqa: E402

CORPUS = HERE / "gamesim" / "corpus" / "maa" / "history"
fails: list[str] = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


class N:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body, alert))
        return []

    def alert_log(self):
        return None


class Src:
    def fetch(self, seen):
        return []


def booked(day: str, stem: str):
    """The corpus record as the collector books it: AUTO-MAS's layout
    <history>/<date>/<user>/<stem>.json + .log, parsed by parse_record."""
    root = tmpdir()
    dest = root / day / "arknights"
    dest.mkdir(parents=True)
    shutil.copyfile(CORPUS / day / f"{stem}.json", dest / f"{stem}.json")
    (dest / f"{stem}.log").write_bytes(gzip.decompress((CORPUS / day / f"{stem}.log.gz").read_bytes()))
    return collector.parse_record(dest / f"{stem}.json", root)


def engine(sd: Path):
    cfg = Config()
    cfg.state_dir = sd
    cfg.automas_dir = None
    cfg.maa_dir = tmpdir()            # MAA's own debug logs: none kept for the corpus runs
    return eng_mod.Engine(cfg, source=Src(), state=State(sd), notifier=N())


print("\n[没进游戏：2026-09-23 MAA-05-00-01「MAA 未能正确登录 PRTS」]")
rec = booked("2026-09-23", "MAA-05-00-01")
check("认成明日方舟的失败", (rec.script, rec.ok, rec.failed_tasks), ("MAA", False, ["MAA 未能正确登录 PRTS"]))
check("记录上写了「进不了游戏」", rec.raw.get("maa_unreachable"), True)
sd = tmpdir()
e = engine(sd)
check("补跑的判断：没开始干活，可以补", makeup.maa_work_done(e, rec), "")
makeup.never_started(e, rec)
row = mc.read(sd).get("#65") or {}
check("#65 过了", row.get("status"), mc.PASS)
check("#65 没往群里推", [t for t, _, alert in e.notifier.sent if alert], [])
State(sd).append_ledger(rec)
check("客户端更新后会重跑它", gameupdate.needs_rerun(sd, rec.started, "MAA"), True)

print("\n[打过仗才失败：2026-08-26 MAA-11-03-30「MAA 部分任务执行失败」]")
rec = booked("2026-08-26", "MAA-11-03-30")
check("是失败、有干活的证据", (rec.ok, bool(rec.raw.get("drop_statistics") or rec.raw.get("stages"))), (False, True))
check("记录上不写「进不了游戏」", "maa_unreachable" in rec.raw, False)
sd = tmpdir()
e = engine(sd)
check("补跑的判断也说不是没进游戏", makeup.maa_work_done(e, rec) != "", True)
State(sd).append_ledger(rec)
check("客户端更新后不重跑", gameupdate.needs_rerun(sd, rec.started, "MAA"), False)

print("\n[跑成了：2026-09-23 MAA-05-03-07「Success!」]")
rec = booked("2026-09-23", "MAA-05-03-07")
check("成功、不写「进不了游戏」", (rec.ok, "maa_unreachable" in rec.raw), (True, False))

print("\n[一条规则：语料里每一条明日方舟失败，记账写的标记和补跑的判断都对得上]")
sd = tmpdir()
e = engine(sd)
seen, disagree = 0, []
for js in sorted(CORPUS.glob("*/*.json")):
    if js.name == "expected.json" or not js.with_suffix(".log.gz").exists():
        continue
    r = booked(js.parent.name, js.stem)
    if r is None or r.ok or r.script != "MAA" or not r.failed_tasks:
        continue
    seen += 1
    if bool(r.raw.get("maa_unreachable")) != (makeup.maa_work_done(e, r) == ""):
        disagree.append(r.run_id)
check("看过的失败不少于 20 条", seen >= 20, True)
check("没有一条对不上", disagree, [])

print("\n[同一轮：前一次打过仗才中止、后一次没登录上，客户端更新后不再整轮重跑]")
# 2026-08-26 MAA-05-16-47 (A) fought and used sanity potions, then 「MAA 在完成任务前中止」;
# 2026-09-23 MAA-05-00-01 (B) 「MAA 未能正确登录 PRTS」. Moved onto today's ledger as
# one round, B's own record is never-started (flagged), but the round already
# fought: the make-up refuses, and the re-run after a client update must too.
from datetime import datetime  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402


def today_round(*picks, maintenance=False):
    """Book the corpus records onto today's ledger one hour apart from 05:00; the
    last is the round's latest attempt. Returns (state dir, engine, last record)."""
    now = datetime.now(tz=SERVER_TZ)
    sd = tmpdir()
    e = engine(sd)
    last = None
    for i, (cday, stem) in enumerate(picks):
        r = booked(cday, stem)
        r.run_id = f"{now:%Y-%m-%d}/arknights/{stem}"
        r.started = now.replace(hour=5 + i, minute=0, second=1, microsecond=0)
        r.finished = r.started.replace(minute=10)
        last = r
        if i == len(picks) - 1 and maintenance:
            r.raw.pop("maa_unreachable", None)
            r.raw["maintenance"] = "05:00-10:00"
        e.state.append_ledger(r)
    return sd, e, last


A, B, OK = ("2026-08-26", "MAA-05-16-47"), ("2026-09-23", "MAA-05-00-01"), ("2026-09-23", "MAA-05-03-07")
a = booked(*A)
check("A：失败、吃过理智药、不写「进不了游戏」",
      (a.ok, bool(a.raw.get("medicine_used")), "maa_unreachable" in a.raw), (False, True, False))
sd, e, b = today_round(A, B)
check("B 自己写了「进不了游戏」", b.raw.get("maa_unreachable"), True)
check("补跑的判断：这一轮打过仗，不补", makeup.maa_work_done(e, b) != "", True)
check("客户端更新后不整轮重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), False)
sd, e, b = today_round(A, B, maintenance=True)
check("B 撞上维护：这一轮打过仗，维护后也不整轮重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), False)
# The round crossed midnight: A started yesterday 23:50, B today 00:05 (AUTO-MAS's
# retry within makeup.RETRY_CHAIN); the ledger files each by its own start day.
from datetime import timedelta  # noqa: E402
sd = tmpdir()
e = engine(sd)
today0 = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
for (cday, stem), start in ((A, today0 - timedelta(minutes=10)), (B, today0 + timedelta(minutes=5))):
    r = booked(cday, stem)
    r.run_id = f"{start:%Y-%m-%d}/arknights/{stem}"
    r.started, r.finished = start, start + timedelta(minutes=8)
    e.state.append_ledger(r)
check("跨午夜的一轮：前一天打过仗，客户端更新后也不整轮重跑", gameupdate.needs_rerun(sd, r.started, "MAA"), False)
# Controls: the round rule still re-runs a round that never got going.
sd, e, b = today_round(B)
check("只有 B 一次：重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), True)
sd, e, b = today_round(A, OK, B)
check("A 和 B 中间跑成过一轮：B 这一轮没开始干活，重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), True)
check("补跑的判断也一样", makeup.maa_work_done(e, b), "")
sd, e, b = today_round(B, maintenance=True)
check("只有 B 一次、撞上维护：维护后重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), True)
# A maintenance attempt whose failure text is not a login failure but shows no work
# (the servers were down, so it could not fight) is still re-run after the update.
sd = tmpdir()
b = booked(*B)
b.run_id = f"{datetime.now(tz=SERVER_TZ):%Y-%m-%d}/arknights/MAA-05-00-01"
b.started = b.finished = datetime.now(tz=SERVER_TZ).replace(hour=5, minute=0, second=1, microsecond=0)
b.failed_tasks = ["MAA 在完成任务前中止"]
b.raw.pop("maa_unreachable", None)
b.raw["maintenance"] = "05:00-10:00"
State(sd).append_ledger(b)
check("撞上维护、没打过仗的别的失败：维护后照旧重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), True)
# The same attempt with its log unread (no fight count): the marked span reaches
# 45 minutes past the window, when the servers may be up, so it may have fought.
sd = tmpdir()
b.raw.pop("fight_count", None)
State(sd).append_ledger(b)
check("撞上维护、日志没读到的别的失败：拿不准打没打过，不重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), False)

print("\n[整轮不补时发一条通知（Server酱，不进群）说为什么]")
import types  # noqa: E402
from ark_relay.core import texts  # noqa: E402
for label, maint in (("登录不上", False), ("撞上维护", True)):
    sd, e, b = today_round(A, B, maintenance=maint)
    notes, reran, problems, sent = [], [], [], []
    gameupdate._rerun_script(types.SimpleNamespace(state_dir=sd), b.started,
                             lambda s: sent.append(s) or (True, "ok"), "MAA", reran, problems, notes)
    check(f"{label}：没派明日方舟", (sent, reran, problems), ([], [], []))
    why = makeup.maa_round_work_done(State(sd).read_ledger, e.state.read_ledger(f"{b.started:%Y-%m-%d}")[-1],
                                     downtime=maint)
    check(f"{label}：说了为什么不补跑（补跑的同一条理由）",
          (bool(why), notes), (True, [f"MAA：客户端更新好了，这一轮不再整轮补跑：{why}"]))
    # A fought (fight_count 8, medicine_used 2): the reason names it, not 「拿不准」.
    check(f"{label}：理由说的是前面打过仗、吃过理智药",
          ("这一轮已经开始干活" in why, "吃过理智药" in why, "拿不准" in why), (True, True, False))
    check(f"{label}：那句话是大白话", [texts.plain(n) for n in notes], [[]])
sd, e, b = today_round(B)
notes, reran, sent = [], [], []
gameupdate._rerun_script(types.SimpleNamespace(state_dir=sd), b.started,
                         lambda s: sent.append(s) or (True, "ok"), "MAA", reran, [], notes)
check("只有 B 一次：照旧补跑、不多说话", (sent, reran, notes), (["MAA"], ["MAA"], []))

# Where the note lands: the engine sends run_deferred's notes; follow it through
# notify.route_of. It is not an alarm, so the info route only (notify._INFO_ORDER),
# never the group - and the release note must say so (it claimed the group before).
from ark_relay.core import notify  # noqa: E402
sd, e, b = today_round(A, B)
e._unfinished_queues = lambda *a, **k: []
e._scripts_running = lambda *a, **k: False


def _deferred(cfg, now=None, dispatch=None, **k):
    out: list = []
    gameupdate._rerun_script(cfg, now, lambda s: (True, "ok"), "MAA", [], [], out)
    return out, [], []


real_gu = (gameupdate.pending, gameupdate.run_deferred)
gameupdate.pending = lambda state_dir: {"明日方舟": "今天官方维护"}
gameupdate.run_deferred = _deferred
try:
    e._maybe_deferred_update()
    t = getattr(e, "_gu_thread", None)
    if t is not None:
        t.join(10)
finally:
    gameupdate.pending, gameupdate.run_deferred = real_gu
routes = [notify.route_of(title, alert=alert) for title, body, alert in e.notifier.sent
          if "不再整轮补跑" in body]
check("不补跑的那句：走通知，不进群", routes, ["info"])
check("通知那一路就是 Server酱", notify._ORDERS["info"], ("Server酱",))
line = next(x for x in (RELAY / "RELEASE-NOTES.md").read_text(encoding="utf-8").splitlines()
            if "不再把整轮重跑" in x)
check("更新说明说对了去处：不说「群里会说」，说不进群", ("群里" in line, "不进群" in line), (False, True))

print("\n[维护日：补跑刚派下去还没落地，队列后更新先不起，不会把同一趟明日方舟再派一次]")
from datetime import datetime  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.makeup import marker as mk  # noqa: E402

now = datetime.now(tz=SERVER_TZ)
day = now.strftime("%Y-%m-%d")
rec = booked("2026-09-23", "MAA-05-00-01")
rec.run_id = f"{day}/arknights/MAA-05-00-01"
rec.started = rec.finished = now.replace(hour=0, minute=0, second=1)
sd = tmpdir()
e = engine(sd)
e.state.append_ledger(rec)
e._unfinished_queues = lambda *a, **k: []
mk._write_marker(sd, day, {"MAA": {"result": mk.DISPATCHED, "dispatched_at": now.isoformat(),
                                   "run_id": rec.run_id, "tries": 1}})
ran: list = []
real_gu = (gameupdate.pending, gameupdate.run_deferred)
gameupdate.pending = lambda state_dir: {"明日方舟": "今天官方维护"}
gameupdate.run_deferred = lambda cfg, now=None, dispatch=None, **k: (ran.append(gameupdate.needs_rerun(sd, now, "MAA")) or ([], [], []))
try:
    e._maybe_deferred_update()
    t = getattr(e, "_gu_thread", None)
    if t is not None:
        t.join(10)
    check("补跑在路上：更新没起", ran, [])
    check("没往群里推", [x for x in e.notifier.sent if x[2]], [])
    mk._write_marker(sd, day, {"MAA": {"result": mk.OK, "dispatched_at": now.isoformat(),
                                       "run_id": rec.run_id, "record": rec.run_id, "tries": 1}})
    e._maybe_deferred_update()
    e._gu_thread.join(10)
    check("补跑落地后：更新照常起", len(ran), 1)
finally:
    gameupdate.pending, gameupdate.run_deferred = real_gu

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
