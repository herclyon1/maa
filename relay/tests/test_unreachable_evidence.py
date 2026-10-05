"""「进不了游戏」needs official evidence; the log's shape alone silences nothing.

The shape (every task fails within 30 s, none completes, >= 3 fails;
collector_maaend.maaend_unreachable) is what the 2026-09-02 maintenance looked
like, but a local fault can look the same. The fixture is the real 2026-09-25
09:55 MaaEnd round (bag full - a local fault: three tasks failed, none
completed), every line kept, with the first two failure times moved to within
30 s of their start (24 s and 28 s, like its third task's real 24 s) - the
same local fault, failing a little faster. No real log in ark-evidence or
relay/tests has the shape at all (0 of 80), so this is the nearest real round.

* shape, no maintenance window, no update notice -> an ordinary failure:
  held, make-up eligible, not booked as 「进不了游戏」, no client update
  registered, and the final alarm goes to the group naming the shape;
* shape + an official maintenance window -> skipped, one explanation, no alarm
  (the user's own words on 2026-09-02, kept as said in the original:
  「检测到服务器在维护时候就跳过，不报警」 - when maintenance is detected, skip it, no alarm);
* shape + an official update notice for today -> the same.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ark_relay import collector, gameupdate, handle, makeup, texts   # noqa: E402
from ark_relay import engine as eng_mod                             # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord           # noqa: E402
from ark_relay.core import State                                    # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "maaend_shape_local_fault_2026-09-25.log"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []


class Src:
    def fetch(self, seen):
        return []


DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
START = DAY.replace(hour=9, minute=55)


def build():
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = None
    cfg.maa_dir = None
    cfg.maaend_dir = tmpdir()
    (Path(cfg.maaend_dir) / "debug").mkdir()
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._unfinished_queues = lambda now, entries: []
    e._deferred_update_busy = lambda: False
    e._verify_outcome = lambda r: None
    e._maintenance_today = lambda game: False
    return e


handle._ship_evidence = lambda eng, rec: ""
makeup._dispatch = lambda script: (True, "已开跑")
makeup._kill_game = lambda: None


def rec_from_fixture():
    raw = collector.parse_maaend_log(FIX)
    return RunRecord(run_id=f"{START:%Y-%m-%d}/endfield/MaaEnd-{START:%H-%M-%S}", script="MaaEnd",
                     user="endfield", started=START, finished=START + timedelta(minutes=4), ok=False,
                     failed_tasks=["🎁赠送干员礼物", "🎱基质刷取", "📅日常奖励领取"], raw=raw)


def ledger_raw(e, r):
    p = Path(e.cfg.state_dir) / f"ledger-{START:%Y-%m-%d}.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        ent = json.loads(line)
        if ent.get("run_id") == r.run_id:
            return ent.get("raw") or {}
    return None


def cant_enter_sent(e):
    return any(t == texts.cant_enter("MaaEnd") for t, _b, _a in e.notifier.sent)


check("反例日志确实是「秒败、零完成」的形状", collector.maaend_unreachable(FIX.read_text(encoding="utf-8")), True)

print("[形状有、没有官方维护也没有更新公告 → 普通故障]")
handle.efstatus.update_hint = lambda now=None, fetch=None: ""
e = build()
r = rec_from_fixture()
handle._handle(e, r)
check("压着等补跑", ("MaaEnd", "endfield") in e._pending)
check("不记成进不了游戏", r.raw.get("maaend_unreachable"), None)
check("账本上也不是进不了游戏", (ledger_raw(e, r) or {}).get("maaend_unreachable"), None)
check("补跑有份", makeup.eligible(r), True)
check("没登记客户端待更新", gameupdate.pending(e.cfg.state_dir), {})
e._flush_pending()
check("没发「进不了游戏」的说明", cant_enter_sent(e), False)
check("没被当维护丢掉（还压着等补跑）", ("MaaEnd", "endfield") in e._pending)
# The make-up did not fix it: the alarm goes to the group and names the shape.
handle._push_unresolved(e, r, "补跑也没成", 1)
body = e.notifier.sent[-1][1] if e.notifier.sent else ""
check("报警里说了像没进游戏、按故障报", "像没进游戏" in body and "按故障报" in body, True)

print("[形状有 + 官方维护窗口 → 跳过、不报警]")
e = build()
gameupdate._store(e.cfg.state_dir).set("updates", "maintenance_windows", {"终末地": {
    "start": DAY.replace(hour=6).isoformat(), "end": DAY.replace(hour=10).isoformat(),
    "why": "官方公告：06:00–10:00 停服维护"}})
r = rec_from_fixture()
handle._handle(e, r)
check("记成进不了游戏", r.raw.get("maaend_unreachable"), True)
check("账本上也是", (ledger_raw(e, r) or {}).get("maaend_unreachable"), True)
check("补跑没份", makeup.eligible(r), False)
check("登记了客户端待更新", "终末地" in gameupdate.pending(e.cfg.state_dir))
e._flush_pending()
check("发了一条说明", cant_enter_sent(e), True)
check("没有报警", [t for t, _b, a in e.notifier.sent if a], [])
check("不再压着", dict(e._pending), {})

print("[形状有 + 官方更新公告 → 跳过、不报警]")
handle.efstatus.update_hint = lambda now=None, fetch=None: "官方公告：今天 10:00 「雪凇幽梦」版本更新"
e = build()
r = rec_from_fixture()
handle._handle(e, r)
check("记成进不了游戏", r.raw.get("maaend_unreachable"), True)
check("补跑没份", makeup.eligible(r), False)
e._flush_pending()
check("发了一条说明、没报警", (cant_enter_sent(e), [t for t, _b, a in e.notifier.sent if a]), (True, []))

if fails:
    print(f"\n✗ {len(fails)} 项失败")
    sys.exit(1)
print("\nall checks passed")
