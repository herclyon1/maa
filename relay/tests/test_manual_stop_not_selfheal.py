"""A run the red button (停一切) cut short is a manual stop, not the retry that healed the day.

2026-09-30 morning: OK-WW failed at 09:19 and 09:30 (both held in _pending). At
09:46:58 the phone's red button stopped the third attempt; AUTO-MAS recorded that
stopped run as Success!, and the relay took it as 「重试后成功」 - a self-heal
notice for a run nobody let finish, and a green row in the daily report.

commands.estop now writes when it was pressed (estop-windows.json); handle._handle
marks any run overlapping that window raw.manual_stop, books it, drops the held
failures' final alarm (they stay in the ledger) and does nothing else. The daily
report shows it as ⏹, never ✅, and never as the later run that 「做成了」 the
earlier failures.
"""
import json
import os
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

from ark_relay import collect_retry, commands, core, handle  # noqa: E402
from ark_relay import engine as eng_mod                      # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord    # noqa: E402
from ark_relay.core import State                             # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body))
        return False


class Src:
    def fetch(self, seen):
        return []


def at(hh, mm, ss=0):
    return datetime(2026, 9, 30, hh, mm, ss, tzinfo=SERVER_TZ)


def rec(run_id, started, finished, script="OK-WW", user="wuwa", ok=False):
    return RunRecord(run_id=run_id, script=script, user=user, started=started, finished=finished,
                     ok=ok, failed_tasks=[] if ok else ["任务执行：卡在对话框"],
                     raw={"tasks_done": ["日常"]} if ok else {})


def build():
    cfg = Config()
    cfg.state_dir = tmpdir()
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._verify_outcome = lambda r: None
    return e


def press(e, start, end):
    (Path(e.cfg.state_dir) / commands.ESTOP_WINDOWS_FILE).write_text(
        json.dumps([{"start": start.isoformat(timespec="seconds"),
                     "end": end.isoformat(timespec="seconds")}]), encoding="utf-8")


gates = []
handle._weekly_gates = lambda eng, r: gates.append(r.run_id)


def morning(e):
    """The two genuine failures of 09-30, booked and held the way _hold_for_retry leaves them."""
    for rid, s, f in (("2026-09-30/wuwa/09-19-00", at(9, 12), at(9, 19)),
                      ("2026-09-30/wuwa/09-30-00", at(9, 21), at(9, 30))):
        r = rec(rid, s, f)
        e.state.append_ledger(r)
        e._pending[("OK-WW", "wuwa")] = r
    e._persist_pending()


print("[09-30 原样：两次失败在等，第三趟被停一切停掉、AUTO-MAS 记成功]")
e = build()
morning(e)
press(e, at(9, 46, 40), at(9, 47, 30))
stopped = rec("2026-09-30/wuwa/09-47-05", at(9, 38), at(9, 47, 5), ok=True)
e._handle(stopped)
check("不进自愈", dict(e._recovered), {})
check("前面的失败不再等着推最终告警", dict(e._pending), {})
check("重启读回来也是空的", dict(State(e.cfg.state_dir).load_pending() or {}).get("pending") or [], [])
check("没走成功那条路（周常门没碰）", gates, [])
check("没有推送", e.notifier.sent, [])
ledger = e.state.read_ledger("2026-09-30")
row = [x for x in ledger if x["run_id"] == stopped.run_id]
check("账本记了这一趟", len(row), 1)
check("账本那行记着是停一切停掉的", (row[0]["raw"] or {}).get("manual_stop"), "09:46 停一切")
check("前两次失败还在账本里", sum(1 for x in ledger if not x["ok"]), 2)

print("\n[被停掉的那趟 AUTO-MAS 记成失败：也不当新失败压着等推]")
e = build()
press(e, at(9, 46, 40), at(9, 47, 30))
e._handle(rec("2026-09-30/endfield/09-47-10", at(9, 47, 0), at(9, 47, 12),
              script="MaaEnd", user="endfield"))
check("没进待推", dict(e._pending), {})
check("没有推送", e.notifier.sent, [])

print("\n[MaaEnd 被停掉：母本路线照样改回]")
restored = []
real_restore = collect_retry.restore_master
collect_retry.restore_master = lambda cfg: restored.append(1) or ""
e = build()
press(e, at(9, 46, 40), at(9, 47, 30))
e._handle(rec("2026-09-30/endfield/09-47-11", at(9, 47, 0), at(9, 47, 12),
              script="MaaEnd", user="endfield", ok=True))
check("restore_master 跑了", restored, [1])
collect_retry.restore_master = real_restore

print("\n[回归：窗口外的成功照旧算重试后成功（自愈）]")
gates.clear()
e = build()
morning(e)
press(e, at(8, 0), at(8, 1))
ok_later = rec("2026-09-30/wuwa/09-47-05", at(9, 38), at(9, 47, 5), ok=True)
e._handle(ok_later)
check("进了自愈", list(e._recovered), [("OK-WW", "wuwa")])
check("走了成功那条路", gates, [ok_later.run_id])
row = [x for x in e.state.read_ledger("2026-09-30") if x["run_id"] == ok_later.run_id]
check("账本那行没有手动停止记号", (row[0]["raw"] or {}).get("manual_stop"), None)

print("\n[没有按过红按钮（没有文件）：照旧]")
e = build()
morning(e)
e._handle(rec("2026-09-30/wuwa/09-47-05", at(9, 38), at(9, 47, 5), ok=True))
check("进了自愈", list(e._recovered), [("OK-WW", "wuwa")])

print("\n[日报：停掉的那趟是 ⏹ 不是 ✅，标题不说重试后成功]")


def entry(rid, s, f, ok, raw=None, failed=None):
    return {"run_id": rid, "script": "OK-WW", "user": "wuwa",
            "started": s.isoformat(), "finished": f.isoformat(), "ok": ok,
            "failed_tasks": failed or [], "duration_known": True, "transitional": False,
            "raw": raw or {}}


fail1 = entry("r1", at(9, 12), at(9, 19), False, failed=["日常"])
fail2 = entry("r2", at(9, 21), at(9, 30), False, failed=["日常"])
manual = entry("r3", at(9, 38), at(9, 47, 5), True,
               raw={"manual_stop": "09:46 停一切", "tasks_done": ["日常"]})
entries = [fail1, fail2, manual]
check("episode_kinds 把它记成 manual", core.episode_kinds(entries).get("r3"), "manual")
check("retried_notes 不把它当后来做成了", core.retried_notes(entries), {})
title, body = core.format_daily("2026-09-30", entries)
row3 = [ln for ln in body.splitlines() if "09:38" in ln]
check("那一行的图标是 ⏹", bool(row3) and row3[0].startswith("⏹"), True)
check("那一行不是 ✅", bool(row3) and row3[0].startswith("✅"), False)
check("有备注说明被停一切停掉", "被停一切中途停掉，不算成功也不算失败" in body, True)
check("标题不含「重试后成功」", "重试后成功" in title, False)
check("前两次仍按失败算", "2 项失败" in title, True)

title, body = core.format_daily("2026-09-30", [manual])
check("只有停掉的那趟：标题说有一趟被手动停止", title.endswith("其余全绿 ✅（有一趟被手动停止）"), True)

ok_run = entry("r4", at(10, 0), at(10, 20), True, raw={"tasks_done": ["日常"]})
retried = [fail1, ok_run, dict(manual, run_id="r5", started=at(11, 0).isoformat())]
title, _ = core.format_daily("2026-09-30", retried)
check("手动停止排在重试后成功之前", title.endswith("其余全绿 ✅（有一趟被手动停止）"), True)

print("\n[记分牌不算停掉的那趟]")
from ark_relay import scoreboard  # noqa: E402
calls = []
real_record = scoreboard.record
scoreboard.record = lambda *a, **k: calls.append(a)
st = State(tmpdir())
st.append_ledger(rec("x/1", at(9, 38), at(9, 47), ok=True))
m = rec("x/2", at(9, 38), at(9, 47), ok=True)
m.raw["manual_stop"] = "09:46 停一切"
st.append_ledger(m)
check("只记了正常那趟", len(calls), 1)
scoreboard.record = real_record

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
