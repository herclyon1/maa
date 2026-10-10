"""MAA refusing its own config, a round with no fight, and sanity MAA never read.

Morning shift 2026-10-10 (machine clock): MAA core had no navigation task for
the event stage YW-4, so the GUI could not hand the Fight task over -
gui.log says 「理智作战: 理智作战 序列化失败」 and then 「已停止」, with no
「开始任务: 理智作战」 at all. AUTO-MAS tried three times with the same config,
every record read 「MAA 在完成任务前中止」 with `sanity: 0` and an empty
`sanity_full_at`. The relay then

* held the failure 「⏳ 等重试结果」 for another tick although re-running the same
  config can only be refused again;
* refused the make-up with 「拿不准有没有打过仗」 although the log it had read
  showed not one fight;
* put 「剩余理智 0」 in the alarm although MAA never read sanity that round.

The real files are under tests/fixtures/maa-2026-10-10/: MAA-05-02-18 (the
failed try, json + log), MAA-05-00-01 (the first try, json only) and
MAA-08-05-07 (a normal run at 12:05 the same day: 14 fights on YW-4, sanity 2
with MAA's own refill sentence) as the control.
"""
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
HIST = TMP / "history"
HIST.mkdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collector, core, handle, makeup, summary, texts  # noqa: E402
from ark_relay import engine as eng_mod                                 # noqa: E402
from ark_relay import machinecheck as _mc                               # noqa: E402
from ark_relay.collector_maa import parse_maa_log                       # noqa: E402
from ark_relay.config import SERVER_TZ, Config                          # noqa: E402
from ark_relay.core import State                                        # noqa: E402

_mc.load()
_mc_real = dict(_mc.CHECKS)
_mc.CHECKS.clear()     # machine checks have their own tests (tests/test_mc_*.py)

FX = Path(__file__).resolve().parent / "fixtures" / "maa-2026-10-10"
SANITY_UNREAD = getattr(texts, "SANITY_UNREAD", "理智没读到")   # getattr: the red run predates it
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def history(day: str) -> Path:
    """The fixture records under history/<day>/arknights/, log dates moved to `day`
    (a make-up is only for a failure of today, makeup.eligible)."""
    d = HIST / day / "arknights"
    d.mkdir(parents=True, exist_ok=True)
    for f in FX.iterdir():
        if f.suffix == ".log":
            (d / f.name).write_text(f.read_text(encoding="utf-8").replace("2026-10-10", day), encoding="utf-8")
        else:
            shutil.copy(f, d / f.name)
    return d


print("[MAA 自己不接受配置：从这一趟自己的日志里认出来，写明哪个任务、哪一关]")
bad = parse_maa_log(FX / "MAA-05-02-18.log")
good = parse_maa_log(FX / "MAA-08-05-07.log")
rej = bad.get("maa_config_rejected") or ""
check("失败那一趟：认出 MAA 不接受配置", bool(rej))
check("写了任务名「理智作战」和「序列化失败」", ("理智作战" in rej, "序列化失败" in rej), (True, True))
check("写了关卡 YW-4（取自 GetFightStage 那一行）", "YW-4" in rej)
check("正常那一趟：没有这一项", "maa_config_rejected" in good, False)

print("\n[打了几仗：日志读到了就记（0 也记）；读不到就不记，没数据不是零]")
check("失败那一趟：0 仗", bad.get("fight_count"), 0)
check("正常那一趟：14 仗（开始行动 1~10、11~14）", good.get("fight_count"), 14)
check("正常那一趟：打过关的次数照旧", good.get("run_times"), 14)

day = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
H = history(day)
r_bad = collector.parse_record(H / "MAA-05-02-18.json", HIST)
r_first = collector.parse_record(H / "MAA-05-00-01.json", HIST)
r_good = collector.parse_record(H / "MAA-08-05-07.json", HIST)
check("只有 json 的那一趟（第一次）：不记打了几仗", "fight_count" in (r_first.raw or {}), False)

print("\n[理智：MAA 没读到（0 且没有回满时间）就是没读到，不是 0]")
check("失败那一趟：理智记为没读到", (r_bad.sanity, r_bad.raw.get("sanity_unread")), (None, True))
check("正常那一趟：理智 2 照旧", (r_good.sanity, r_good.raw.get("sanity_unread")), (2, None))
_, body = core.format_failure(r_bad)
check("报警里写「理智没读到」", SANITY_UNREAD in body)
check("报警里不再写「剩余理智 0」", "剩余理智 0" in body, False)
check("报警里写 MAA 不接受这份配置、哪个任务、哪一关",
      ("不接受这份配置" in body, "理智作战" in body, "YW-4" in body), (True, True, True))
check("报警里写「一仗都没打」", "一仗都没打" in body)
_, body_first = core.format_failure(r_first)
check("日志都没有的那一趟：不说一仗都没打", "一仗都没打" in body_first, False)


def build():
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = AUTOMAS
    e = eng_mod.Engine(cfg, source=type("Src", (), {"fetch": lambda self, seen: []})(),
                       state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._unfinished_queues = lambda now, entries: []
    e._deferred_update_busy = lambda: False
    return e


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []


handle._ship_evidence = lambda eng, rec: ""
summary.diagnose = lambda *a, **k: ""
dispatched = []
makeup._dispatch = lambda script: (dispatched.append(script), (True, "ok"))[1]
makeup._kill_game = lambda: None

print("\n[补跑：不接受配置的不补，理由写明；不再说「拿不准」]")
e = build()
e.state.append_ledger(r_bad)
why = makeup.maa_work_done(e, r_bad)
check("理由：MAA 不接受这份配置（理智作战 序列化失败，关卡 YW-4），原样补跑还是一样",
      why, "MAA 不接受这份配置（理智作战 序列化失败，关卡 YW-4），原样补跑还是一样")
plain = collector.parse_record(H / "MAA-05-02-18.json", HIST)
plain.raw.pop("maa_config_rejected", None)
e = build()
e.state.append_ledger(plain)
why0 = makeup.maa_work_done(e, plain)
check("别的失败、日志里 0 仗：说一仗都没打，不说拿不准", ("一仗都没打" in why0, "拿不准" in why0), (True, False))
check("还是不补（只有没进游戏的才整轮补跑）", bool(why0))
unread = collector.parse_record(H / "MAA-05-00-01.json", HIST)
e = build()
e.state.append_ledger(unread)
check("日志读不到：照旧拿不准", "拿不准" in makeup.maa_work_done(e, unread))

print("\n[整条链：两次失败落地 → 同一轮就进群一次，不压着等重试、不派补跑]")
e = build()
for r in (collector.parse_record(H / "MAA-05-00-01.json", HIST),
          collector.parse_record(H / "MAA-05-02-18.json", HIST)):
    e._handle(r)
e._flush_pending()
group = [(t, b) for t, b, a in e.notifier.sent if a]
check("这一轮就进群一次", [t for t, _ in group], [texts.unresolved("明日方舟", "早班")])
check("不再压着", dict(e._pending), {})
body = group[-1][1] if group else ""
check("开头写明没补跑的原因：不接受这份配置", "没补跑：MAA 不接受这份配置（理智作战 序列化失败，关卡 YW-4），原样补跑还是一样" in body)
check("不再说拿不准", "拿不准" in body, False)
check("理智没读到，不是 0", (SANITY_UNREAD in body, "剩余理智 0" in body), (True, False))
makeup.maybe_run(e)
check("没派补跑", dispatched, [])
mk = makeup.read_marker(e.cfg.state_dir, day).get("MAA") or {}
check("当天补跑记成不补，写明原因", (mk.get("result"), "不接受这份配置" in str(mk.get("note"))),
      (makeup.GAVE_UP, True))

print("\n[记录落地顺序反过来（带原因的先到、只有 json 的后到）：照样这一轮进群、说清原因]")
e = build()
for r in (collector.parse_record(H / "MAA-05-02-18.json", HIST),
          collector.parse_record(H / "MAA-05-00-01.json", HIST)):
    e._handle(r)
e._flush_pending()
group2 = [(t, b) for t, b, a in e.notifier.sent if a]
check("这一轮就进群一次", [t for t, _ in group2], [texts.unresolved("明日方舟", "早班")])
body2 = group2[-1][1] if group2 else ""
check("还是说 MAA 不接受这份配置、哪一关", ("没补跑：MAA 不接受这份配置" in body2, "YW-4" in body2), (True, True))
check("还是说一仗都没打、理智没读到", ("一仗都没打" in body2, SANITY_UNREAD in body2), (True, True))
check("两次都算上", "重试 2 次" in body2)
if "--show" in sys.argv and group:
    print("\n----- alarm -----\n" + group[-1][0] + "\n" + body + "\n-----------------")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
_mc.CHECKS.update(_mc_real)
sys.exit(1 if fails else 0)
