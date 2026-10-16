"""The collector writes raw['maa_unreachable'] on an MAA record that never got into
the game, by the same rule the make-up re-runs a round by (ledger #65).

Real AUTO-MAS records from tests/gamesim/corpus/maa/history:
  2026-09-23/MAA-05-00-01   「MAA 未能正确登录 PRTS」, MAA's log never reaches a stage:
                            flagged; makeup.maa_work_done says ''; check #65 passes and
                            pushes nothing; gameupdate.needs_rerun re-runs it.
  2026-08-26/MAA-11-03-30   「MAA 部分任务执行失败」 after fighting: not flagged.
  2026-09-23/MAA-05-03-07   「Success!」: not flagged.
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
