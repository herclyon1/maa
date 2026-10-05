"""Annihilation without a progress line is not "done for the week".

2026-09-14 09:00-09:06 the Monday annihilation check ran three times at 17
sanity against a 25 cost; nothing was fought, yet every ledger row says
annihilation_done: true (fixtures/ledger-2026-09-14/ledger.jsonl lines 1-3).
collector_maa read "no 「剿灭模式」 line and no sanity spent" as "MAA saw the
cap was met and left". The only real logs we hold say otherwise: on 2026-09-21
21:32, with the week already full, MAA still fought once (-25) and printed
「剿灭模式 : 1800 / 1800」 (fixtures/maa-annihilation-2026-09-21, copied from
ark-evidence/M6-0923/automas/history/2026-09-21/arknights/MAA-17-30-02.log).
handle._weekly_gates closes annihilation for the week on annihilation_done of a
run that reports success - and MAA reports Success! when it stops for lack of
sanity (handle.py, comment above _weekly_gates' checks).

No 09-14 history log survived, so the "nothing fought" input is the 09-21 real
log with its fight block (开始行动 ... 剿灭模式) removed: annihilation
selected, chain started and finished, no fight, no progress - the 09-14 shape.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402
from ark_relay import collector_maa, core, handle  # noqa: E402
from ark_relay.config import SERVER_TZ, RunRecord  # noqa: E402

FX = Path(__file__).parent / "fixtures" / "maa-annihilation-2026-09-21" / "MAA-17-30-02.log"
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


TMP = tmpdir()
real = FX.read_text(encoding="utf-8")
# The fight block runs from the 「开始行动」 line through the 「剿灭模式」 line
# (开始行动 / 理智 / 掉落统计 / drops / 剿灭模式); cut it out by content, not line
# number - the file mixes line endings.
a = real.rfind("\n", 0, real.index("开始行动 1 次, -25理智")) + 1
b = real.index("\n", real.index("剿灭模式 : 1800 / 1800")) + 1
unfought = TMP / "MAA-unfought.log"
unfought.write_text(real[:a] + real[b:], encoding="utf-8")

print("[真日志 09-21：打满那周照样打一把，有进度行]")
full = collector_maa.parse_maa_log(FX)
check("认出是剿灭", full.get("annihilation"), True)
check("进度 1800/1800", full.get("annihilation_progress"), [1800, 1800])
check("打满 = 完成", full.get("annihilation_done"), True)

print("\n[没打（09-14 那种）：没有进度行、没花理智]")
got = collector_maa.parse_maa_log(unfought)
check("认出是剿灭", got.get("annihilation"), True)
check("没有进度", got.get("annihilation_progress"), None)
check("没花理智", got.get("sanity_spent"), None)
check("不算完成", got.get("annihilation_done"), False)

print("\n[后果：报成功的这一趟不许把剿灭关一周]")


class Gate:
    def __init__(self):
        self.calls = 0

    def on_success(self, now=None):
        self.calls += 1
        return "closed"


class Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, msg):
        self.sent.append((title, msg))


class Boss:
    def on_success(self, now=None):
        return ""


class Eng:
    def __init__(self):
        self._annihilation = Gate()
        self._weeklyboss = Boss()
        self._garden = None
        self.notifier = Notifier()


t = datetime(2026, 9, 14, 9, 2, tzinfo=SERVER_TZ)
for label, raw, want in (("没打的那趟", got, 0), ("打满的那趟", full, 1)):
    eng = Eng()
    rec = RunRecord(run_id="2026-09-14/arknights/MAA-05-00-01", script="MAA", user="arknights",
                    started=t, finished=t, ok=True, raw=dict(raw))
    handle._weekly_gates(eng, rec)
    check(f"{label}：问剿灭门关不关", eng._annihilation.calls, want)

print("\n[日报：没进度行不写「此前已完成」]")
e = {"run_id": "2026-09-14/arknights/MAA-05-00-01", "script": "MAA", "user": "u", "ok": True,
     "started": t.isoformat(), "finished": t.isoformat(), "duration_known": True,
     "transitional": False, "failed_tasks": [], "raw": got, "drops": {}, "recruits": {},
     "sanity": None, "sanity_full_at": ""}
_, body = core.format_daily("2026-09-14", [e])
check("不说已完成", "此前已完成" in body, False)
check("说没读到进度", "没读到剿灭进度" in body, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
