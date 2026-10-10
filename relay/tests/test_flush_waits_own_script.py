"""A held failure alarm waits only for its own script, never for the whole queue.

2026-10-01 morning shift: OK-WW timed out three times in a row, two hours each
(09:18 / 11:20 / 13:21), and AUTO-MAS wrote all three records at 15:23:06. The
relay held the failure, and _flush_pending's first line returned while anything
was running - MaaEnd started at 15:23, so the alarm stayed held. At 17:12 the
user asked why a shift due to end four hours earlier was still stuck.

Replayed here with that day's shape: three OK-WW failures plus the real
runtime-snapshot read on the machine at 16:11 (MAA done, OK-WW failed, MaaEnd running).
Before the fix nothing is pushed; after it, exactly one alarm.
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

from ark_relay import engine as eng                       # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.ledger import State                          # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return False


class Src:
    def fetch(self, seen):
        return []


def snap(okww, maaend):
    """The runtime-snapshot read on the machine at 2026-10-01 16:11, two statuses swapped in."""
    return {"tasks": [{"taskId": "8f47a684", "mode": "AutoProxy", "stopping": False,
                       "task_info": [
                           {"name": "MAA", "status": "完成", "userList": [{"name": "arknights", "status": "完成"}]},
                           {"name": "OK-WW", "status": okww, "userList": [{"name": "wuwa", "status": okww}]},
                           {"name": "MaaEnd", "status": maaend, "userList": [{"name": "endfield", "status": maaend}]}]}],
            "scheduledScripts": []}


TODAY = snap("异常", "运行")


def okww_rounds():
    """That day's three rounds: two hours each, written together at 15:23:06."""
    out = []
    for run_id, a, b in (("2026-10-01/wuwa/OK-WW-05-18-20", (9, 18), (11, 20)),
                         ("2026-10-01/wuwa/OK-WW-07-20-22", (11, 20), (13, 21)),
                         ("2026-10-01/wuwa/OK-WW-09-21-22", (13, 21), (15, 23))):
        out.append(RunRecord(run_id=run_id, script="OK-WW", user="wuwa",
                             started=datetime(2026, 10, 1, *a, tzinfo=SERVER_TZ),
                             finished=datetime(2026, 10, 1, *b, tzinfo=SERVER_TZ),
                             ok=False, failed_tasks=["OK-WW 运行超时"], raw={}))
    return out


def build(snapshot):
    cfg = Config()
    cfg.state_dir = tmpdir()
    e = eng.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    # The queue-wide check answers truthfully (MaaEnd running -> busy), as on the machine
    e._scripts_running = lambda: True if snapshot is None else eng._judge_snapshot(snapshot)
    eng._automas_snapshot = lambda: snapshot
    for r in okww_rounds():
        e._pending[(r.script, r.user)] = r          # a later round replaces the earlier one, as in _hold_for_retry
    return e


real_os, real_snapshot = eng.os, getattr(eng, "_automas_snapshot", None)
try:
    eng.os = types.SimpleNamespace(name="nt")

    print("[10-01 回放：OK-WW 已「异常」、MaaEnd 还在跑 → OK-WW 的告警现在就推]")
    e = build(TODAY)
    e._flush_pending()
    alarms = [t for t, _, alert in e.notifier.sent if alert]
    check("推了一条真报警", len(alarms), 1)
    check("推的是 OK-WW", any("OK-WW" in t or "鸣潮" in t for t in alarms), True)
    check("推完从待推里拿掉", dict(e._pending), {})

    print("\n[OK-WW 自己还在重试 → 照旧等它]")
    e = build(snap("运行", "等待"))
    e._flush_pending()
    check("一条都不推", e.notifier.sent, [])
    check("还在待推里", list(e._pending), [("OK-WW", "wuwa")])

    print("\n[OK-WW 排着队还没轮到（等待）→ 也算在跑]")
    e = build(snap("等待", "等待"))
    e._flush_pending()
    check("一条都不推", e.notifier.sent, [])

    print("\n[问不到 AUTO-MAS → 退回整条队列的判断，宁可多等]")
    e = build(None)
    e._flush_pending()
    check("一条都不推", e.notifier.sent, [])
    check("还在待推里", list(e._pending), [("OK-WW", "wuwa")])

    print("\n[只看名字对得上的那一格]")
    check("MaaEnd 运行 → MaaEnd 在跑", eng._script_unfinished(TODAY, "MaaEnd"), True)
    check("OK-WW 异常 → OK-WW 不在跑", eng._script_unfinished(TODAY, "OK-WW"), False)
    check("MAA 完成 → MAA 不在跑", eng._script_unfinished(TODAY, "MAA"), False)
    check("刚派下去没状态 → 当作在跑", eng._script_unfinished({"tasks": [{"task_info": []}]}, "OK-WW"), True)
    check("没有任务 → 不在跑", eng._script_unfinished({"tasks": []}, "OK-WW"), False)
finally:
    eng.os, eng._automas_snapshot = real_os, real_snapshot

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
