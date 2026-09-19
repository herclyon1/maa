"""The round a record belongs to, for the 「最近一轮是手动触发的」 gate.

2026-09-19: OK-WW hung at 09:34, AUTO-MAS killed it at 11:35 and reran it, MaaEnd
followed 11:42-12:09. The old rule took "everything started within two hours of the
newest record", judged that tail by its own first record (11:35, not 09:00) and read
the whole scheduled queue as started by hand - the machine stayed on all day. A
hand-started afternoon run must still read as manual, that is the gate's job.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import shutdown
from ark_relay.config import SERVER_TZ

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def e(run_id, script, start, end, ok=True, user=None):
    day = datetime(2026, 9, 19, tzinfo=SERVER_TZ)
    def at(hms):
        h, m, s = (int(x) for x in hms.split(":"))
        return (day + timedelta(hours=h, minutes=m, seconds=s)).isoformat()
    return {"run_id": run_id, "script": script, "user": user or script.lower(),
            "started": at(start), "finished": at(end), "ok": ok}


class Eng:
    """Just enough engine: the schedule is 09:00 and 21:30, MANUAL_WINDOW_MIN=30."""
    _gu_rerun_at = None

    def _round_is_manual(self, group):
        times = ["09:00", "21:30"]
        first = min(datetime.fromisoformat(x["started"]).astimezone(SERVER_TZ) for x in group)
        for hhmm in times:
            hh, mm = (int(v) for v in hhmm.split(":"))
            due = first.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if abs((first - due).total_seconds()) <= shutdown.MANUAL_WINDOW_MIN * 60:
                return False
        return True


eng = Eng()
NOW = datetime(2026, 9, 19, 12, 9, 32, tzinfo=SERVER_TZ)

print("[今天的账本回放：09:00 早班，OK-WW 挂两小时后被重跑，尾巴 11:35-12:09]")
today = [
    e("arknights/MAA-05-00-01", "MAA", "09:00:51", "09:16:02"),
    e("wuwa/OK-WW-05-16-07", "OK-WW", "09:16:22", "09:34:40", ok=False),
    e("wuwa/OK-WW-07-35-45", "OK-WW", "11:35:58", "11:42:27"),
    e("endfield/MaaEnd-07-42-32", "MaaEnd", "11:42:36", "12:08:47"),
    e("endfield/MaaEnd-08-08-51", "MaaEnd", "12:08:57", "12:09:15"),
]
group = shutdown._round_of_newest(today)
check("整轮五条都在同一轮里", [x["run_id"] for x in group], [x["run_id"] for x in today])
check("第一条是 09:00:51 的 MAA", group[0]["run_id"], "arknights/MAA-05-00-01")
check("不是手动 → 允许关机", shutdown._last_round_manual(eng, NOW, today), False)

print("\n[旧规则的样子：只看最近两小时，尾巴自成一轮，会判成手动]")
tail = [x for x in today if x["started"] >= today[2]["started"]]
check("尾巴单看确实像手动（这就是 09-19 卡住的原因）", eng._round_is_manual(tail), True)

print("\n[下午手动跑一趟：和早班隔了四个多小时，仍算手动，不关机]")
afternoon = today[:1] + [e("endfield/MaaEnd-07-00-00", "MaaEnd", "15:00:00", "15:20:00")]
check("下午那趟自成一轮", [x["run_id"] for x in shutdown._round_of_newest(afternoon)], ["endfield/MaaEnd-07-00-00"])
check("判为手动", shutdown._last_round_manual(eng, NOW.replace(hour=15, minute=25), afternoon), True)

print("\n[手动重跑早上失败的那家，但隔了六小时：不再串回早班]")
late_retry = today[:2] + [e("wuwa/OK-WW-late", "OK-WW", "15:40:00", "15:46:00")]
check("六小时后的重跑自成一轮", [x["run_id"] for x in shutdown._round_of_newest(late_retry)], ["wuwa/OK-WW-late"])
check("判为手动", shutdown._last_round_manual(eng, NOW.replace(hour=15, minute=50), late_retry), True)

print("\n[晚班照旧：21:30 的方舟自成一轮，贴着排班，不是手动]")
evening = today + [e("arknights/MAA-17-30-03", "MAA", "21:32:01", "21:46:37")]
check("晚班那条自成一轮", [x["run_id"] for x in shutdown._round_of_newest(evening)], ["arknights/MAA-17-30-03"])
check("不是手动", shutdown._last_round_manual(eng, NOW.replace(hour=21, minute=47), evening), False)

print("\n[没有 finished 的旧记录也不炸]")
odd = [{"run_id": "x", "script": "MAA", "user": "a", "started": today[0]["started"], "ok": True}]
check("单条就是一轮", len(shutdown._round_of_newest(odd)), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
