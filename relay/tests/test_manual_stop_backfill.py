"""Runs the red button cut short before the press was recorded get ⏹ at the next boot.

2026-09-30 09:46:28-09:47:22 (Beijing) the red button was pressed through a
one-off script, before commands.estop wrote estop-windows.json. The ledger
already held the OK-WW run it stopped (ok=True, which AUTO-MAS wrote as
Success!) and the MaaEnd run it stopped (ok=False), neither with
raw.manual_stop, so the evening report would show ✅ and ❌ for two runs nobody
let finish.

At boot, after the self-update, handle.backfill_manual_stops merges the shipped
seed window into estop-windows.json (once, only while it is under three days
old), marks every ledger line of today and yesterday that overlaps a recorded
press, and drops held alarms for those runs the way _handle does at record time.
The report is rendered through report._compose_daily, the same function the
`python -m ark_relay report --again` command pushes.
"""
import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import commands, handle, report                # noqa: E402
handle._screenshot_to = lambda out: False   # the real one waits up to 10 s for a Windows screenshot file
from ark_relay import engine as eng_mod                       # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord     # noqa: E402
from ark_relay.core import State                              # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


# No network: the banner section and the report-writing model are stubbed, as in
# test_report_due.py.
report.plan = types.SimpleNamespace(next_plan=lambda d: "", activity_countdown=lambda d: "",
                                    schedule=lambda d: [])
report.banners = types.SimpleNamespace(
    collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
    read_image=None: ([], {}),
    image_reader=lambda state_dir: None,
    render=lambda rows, now, nxt, notes=None, trace=None, failed=None, leads=None: "",
    Trace=types.SimpleNamespace(new=lambda: None),
    save_trace=lambda state_dir, now, text, tr: None,
    opening_tomorrow=lambda now, nxt: [],
)
report.summary = types.SimpleNamespace(daily_report=lambda cfg, entries, plan="": "")


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body))
        return []

    def send_group(self, title, body):
        return []


class Src:
    def fetch(self, seen):
        return []


def at(d, hh, mm, ss=0):
    return datetime(2026, 9, d, hh, mm, ss, tzinfo=SERVER_TZ)


def line(rid, script, user, s, f, ok, failed=None):
    return {"run_id": rid, "script": script, "user": user, "started": s.isoformat(),
            "finished": f.isoformat(), "ok": ok, "failed_tasks": failed or [],
            "duration_known": True, "transitional": False, "raw": {"tasks_done": ["日常"]} if ok else {}}


OKWW = line("OK-WW-05-40-56", "OK-WW", "wuwa", at(30, 9, 38), at(30, 9, 46, 58), True)
MAAEND = line("MaaEnd-05-46-45", "MaaEnd", "endfield", at(30, 9, 46, 58), at(30, 9, 47, 10), False,
              ["据点交易"])
MAA = line("MAA-09-00-00", "MAA", "ark", at(30, 9, 0), at(30, 9, 30), True)
TORN = '{"run_id": "half'


def build(windows=None):
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.history_dir = None
    cfg.automas_dir = None
    st = State(cfg.state_dir)
    p = st.ledger_path("2026-09-30")
    p.write_text("\n".join([json.dumps(MAA, ensure_ascii=False), json.dumps(OKWW, ensure_ascii=False),
                            TORN, json.dumps(MAAEND, ensure_ascii=False)]) + "\n", encoding="utf-8")
    if windows is not None:
        (Path(cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).write_text(json.dumps(windows), encoding="utf-8")
    e = eng_mod.Engine(cfg, source=Src(), state=st, notifier=Notes())
    e._scripts_running = lambda: False
    return e


def stops(e, day="2026-09-30"):
    return {x["run_id"]: (x.get("raw") or {}).get("manual_stop") for x in e.state.read_ledger(day)}


def kind_line(body, script):
    return next((ln for ln in body.splitlines() if f" {script}" in ln and ln[:1] in "✅❌⏹↻⚠"), "")


EVENING = at(30, 21, 25)

print("[改前的日报：两趟被停掉的显示成 ✅ / ❌]")
e = build(windows=[])
_, body0 = e._compose_daily("2026-09-30", e.state.read_ledger("2026-09-30"))
check("OK-WW 原来是 ✅", kind_line(body0, "OK-WW")[:1], "✅")
check("MaaEnd 原来是 ❌", kind_line(body0, "MaaEnd")[:1], "❌")

print("\n[窗口文件里有这次按下：两趟补记，窗口外的不动，第二次是空操作]")
e = build(windows=[{"start": "2026-09-30T09:46:28+08:00", "end": "2026-09-30T09:47:22+08:00"}])
n = handle.backfill_manual_stops(e, EVENING)
got = stops(e)
check("补了两趟", n, 2)
check("OK-WW 记停一切", got.get("OK-WW-05-40-56"), "09:46 停一切")
check("MaaEnd 记停一切", got.get("MaaEnd-05-46-45"), "09:46 停一切")
check("窗口外的 MAA 不动", got.get("MAA-09-00-00"), None)
raw_text = e.state.ledger_path("2026-09-30").read_text(encoding="utf-8")
check("残行原样保留", TORN in raw_text.splitlines(), True)
check("行数不变", len(raw_text.splitlines()), 4)
before = raw_text
check("再跑一次什么都不补", handle.backfill_manual_stops(e, EVENING), 0)
check("文件逐字节不变", e.state.ledger_path("2026-09-30").read_text(encoding="utf-8"), before)

print("\n[日报走 _compose_daily（report 命令同一个函数）：两趟都是 ⏹]")
title, body = e._compose_daily("2026-09-30", e.state.read_ledger("2026-09-30"))
check("OK-WW 那行是 ⏹", kind_line(body, "OK-WW")[:1], "⏹")
check("MaaEnd 那行是 ⏹", kind_line(body, "MaaEnd")[:1], "⏹")
check("有被停一切停掉的备注", "被停一切中途停掉，不算成功也不算失败" in body, True)
check("标题不算失败", "失败" in title, False)
check("两趟都写「已停，未补」", body.count("已停，未补"), 2)

print("\n[停掉之后同一脚本又跑过一趟：那趟停的不写「未补」]")
later = line("OK-WW-10-30-00", "OK-WW", "wuwa", at(30, 10, 30), at(30, 10, 50), True)
title, body = e._compose_daily("2026-09-30", e.state.read_ledger("2026-09-30") + [later])
check("只剩 MaaEnd 那条写「已停，未补」", body.count("已停，未补"), 1)
from ark_relay import core as _core  # noqa: E402
check("共用判定：有 manual_stop 才算", [_core.manual_stop(x) for x in (
    {"raw": {"manual_stop": "09:46 停一切"}}, {"raw": {}}, {"raw": None}, {})], [True, False, False, False])

print("\n[只有随包带的种子（机器上没有窗口文件）：并进窗口文件，照样补]")
e = build(windows=None)
n = handle.backfill_manual_stops(e, EVENING)
check("补了两趟", n, 2)
w = json.loads((Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).read_text(encoding="utf-8"))
check("种子并进了窗口文件", [x.get("start") for x in w], ["2026-09-30T09:46:28+08:00"])
handle.backfill_manual_stops(e, EVENING)
w = json.loads((Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).read_text(encoding="utf-8"))
check("第二次不重复并", len(w), 1)

print("\n[已有别的按下记录：种子并进去、原记录不丢]")
e = build(windows=[{"start": "2026-09-30T20:00:00+08:00", "end": "2026-09-30T20:01:00+08:00"}])
handle.backfill_manual_stops(e, EVENING)
w = json.loads((Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).read_text(encoding="utf-8"))
check("两条，按时间排", [x.get("start")[11:16] for x in w], ["09:46", "20:00"])

print("\n[过了午夜（北京时间）：昨天的账本照样补]")
e = build(windows=None)
check("10-01 00:30 开机也补了两趟", handle.backfill_manual_stops(e, datetime(2026, 10, 1, 0, 30, tzinfo=SERVER_TZ)), 2)

print("\n[种子三天后自己作废]")
e = build(windows=None)
check("10-04 开机：不补", handle.backfill_manual_stops(e, datetime(2026, 10, 4, 21, 25, tzinfo=SERVER_TZ)), 0)
check("窗口文件没被写出来", (Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).exists(), False)

print("\n[压着的告警：被停掉的两趟相关的清掉，别的不动]")


def rec_of(d, **over):
    x = dict(d, **over)
    return RunRecord(run_id=x["run_id"], script=x["script"], user=x["user"],
                     started=datetime.fromisoformat(x["started"]),
                     finished=datetime.fromisoformat(x["finished"]), ok=x["ok"],
                     failed_tasks=x["failed_tasks"], raw=dict(x["raw"]))


e = build(windows=None)
# 09:30 OK-WW failure moved to _recovered when the stopped OK-WW run read as a success.
fail930 = rec_of(OKWW, run_id="OK-WW-05-21-00", started=at(30, 9, 21).isoformat(),
                 finished=at(30, 9, 30).isoformat(), ok=False, failed_tasks=["日常"], raw={})
e._recovered[("OK-WW", "wuwa")] = fail930
# The stopped MaaEnd run itself, held for the final alarm.
e._pending[("MaaEnd", "endfield")] = rec_of(MAAEND)
# Something unrelated that must stay.
other = rec_of(MAA, run_id="MAA-08-00-00", ok=False, failed_tasks=["x"], raw={})
e._pending[("MAA", "ark")] = other
e._persist_pending()
handle.backfill_manual_stops(e, EVENING)
check("OK-WW 不算重试后成功", list(e._recovered), [])
check("MaaEnd 不再等着重试", ("MaaEnd", "endfield") in e._pending, False)
check("MAA 的照旧压着", list(e._pending), [("MAA", "ark")])
# 2026-10-06: both failures are pushed now, not dropped (「只要是报错…都要发」).
check("两条失败都进群", sorted(t for t, _ in e.notifier.sent), ["❌ MaaEnd 失败", "❌ OK-WW 失败"])
check("都说明后面那趟是停一切停掉的", all("停一切停掉" in b for _, b in e.notifier.sent), True)
disk = State(e.cfg.state_dir).load_pending()
check("磁盘上也清掉了（重启读回一致）",
      (len(disk.get("pending") or []), len(disk.get("recovered") or [])), (1, 0))

print("\n[被停掉那趟之后的新失败：不清]")
e = build(windows=None)
late = rec_of(MAAEND, run_id="MaaEnd-10-30-00", started=at(30, 10, 30).isoformat(),
              finished=at(30, 10, 50).isoformat())
e._pending[("MaaEnd", "endfield")] = late
handle.backfill_manual_stops(e, EVENING)
check("10:30 的失败还压着", ("MaaEnd", "endfield") in e._pending, True)

print("\n[自愈之后又有真成功：那次自愈是真的，不清]")
e = build(windows=None)
real_ok = line("OK-WW-09-35-00", "OK-WW", "wuwa", at(30, 9, 32), at(30, 9, 36), True)
p = e.state.ledger_path("2026-09-30")
p.write_text(p.read_text(encoding="utf-8") + json.dumps(real_ok, ensure_ascii=False) + "\n", encoding="utf-8")
e._recovered[("OK-WW", "wuwa")] = fail930
handle.backfill_manual_stops(e, EVENING)
check("09:36 真成功治好的自愈通知还在", list(e._recovered), [("OK-WW", "wuwa")])

print("\n[开机阶段：出错不抛、写一行日志]")
sys.modules.setdefault("win32event", types.ModuleType("win32event"))
import boot_stages  # noqa: E402


class Log:
    def __init__(self):
        self.lines = []

    def info(self, *a, **k):
        self.lines.append(a)

    def exception(self, *a, **k):
        self.lines.append(("EXC",) + a)


lg = Log()
e = build(windows=None)
# The stage passes no clock, and backfill looks at yesterday and today only: pin "now" to the
# evening of the fixture day, or this check starts failing two days after the fixture (2026-10-02).
_real_backfill = handle.backfill_manual_stops
handle.backfill_manual_stops = lambda eng, now=None: _real_backfill(eng, now or EVENING)
try:
    boot_stages._stage_backfill_manual_stops(e, lg)
finally:
    handle.backfill_manual_stops = _real_backfill
check("阶段跑完两趟有停一切", sorted(v for v in stops(e).values() if v), ["09:46 停一切", "09:46 停一切"])
real = handle.backfill_manual_stops
handle.backfill_manual_stops = lambda *a, **k: 1 / 0
try:
    boot_stages._stage_backfill_manual_stops(e, lg)
    check("出错不抛", True, True)
    check("记了异常", any(x and x[0] == "EXC" for x in lg.lines), True)
finally:
    handle.backfill_manual_stops = real

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
