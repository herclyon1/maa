"""A MaaEnd round is judged on its own error pictures and app-log lines only,
not on those of the rounds after it.

Real case, 2026-10-01 (ledger-2026-10-01.jsonl; relay.log 24567-24571): round
MaaEnd-11-23-07 ran 15:24:12-15:29:59, round MaaEnd-12-11-12 ran
16:12:15-16:58:22; both were judged at 17:27:45, and the first was failed with
「有 1 张出错截图：2026.10.01-16.44.46.960___MapNavigatorObstacleDevice_InteractPost.png」,
a picture taken inside the second round. Audit 2026-10-13 s8 #2.
"""
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.config import SERVER_TZ, RunRecord     # noqa: E402
from ark_relay.features.alarm import gamelogs, verdict     # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def at(h, m, s=0):
    return datetime(2026, 10, 1, h, m, s, tzinfo=SERVER_TZ)


def touch(p: Path, when: datetime):
    os.utime(p, (when.timestamp(), when.timestamp()))


START1, END1 = at(15, 24, 12), at(15, 29, 59)
UNTIL1 = END1 + timedelta(minutes=5)
LATER_SHOT = "2026.10.01-16.44.46.960___MapNavigatorObstacleDevice_InteractPost.png"

root = tmpdir()
oe = root / "debug" / "on_error"
oe.mkdir(parents=True)
(oe / LATER_SHOT).write_bytes(b"png")
touch(oe / LATER_SHOT, at(16, 44, 46))
own = "2026.10.01-15.27.03.000___Own.png"
(oe / own).write_bytes(b"png")
touch(oe / own, at(15, 27, 3))
app = root / "debug" / "2026-10-01-3.log"
app.write_text("\n".join([
    "2026-10-01 15:24:20 INFO  [App] 开始任务: 🛍️信用点购物",
    "2026-10-01 15:29:50 INFO  [App] 任务完成: 🛍️信用点购物",
    "2026-10-01 16:12:20 INFO  [App] 开始任务: 🛍️信用点购物",
    "  continuation of the 16:12 line",
    "2026-10-01 16:58:20 INFO  [App] 任务失败: 🛍️信用点购物",
]) + "\n", encoding="utf-8")
touch(app, at(16, 58, 20))

def call(f, *a):
    try:
        return f(*a)
    except TypeError as exc:     # the code before the bound took no `until`
        return f"TypeError: {exc}"


print("[pictures: only the round's own, up to finish + 5 min]")
check("the first round's pictures", call(gamelogs._maaend_new_shots, root, START1, UNTIL1), [own])
check("no bound -> as before", gamelogs._maaend_new_shots(root, START1), sorted([LATER_SHOT, own]))

print("\n[app log: lines cut by their own stamps]")
text = call(gamelogs._maaend_app_log, root, START1, UNTIL1)
check("keeps the round's lines", "15:29:50" in text, True)
check("drops the later round's lines", ("16:12:20" in text, "continuation" in text, "16:58:20" in text),
      (False, False, False))
check("a file with no stamps is kept whole",
      call(getattr(gamelogs, "_in_window", lambda *a: None), "no stamp here\nnor here", START1, UNTIL1),
      "no stamp here\nnor here")

print("\n[the outcome check, real functions: judged without the later round's picture and lines]")
hist = root / "MaaEnd-11-23-07.log"
hist.write_text("[2026-10-01 15:24:20.000] 任务开始: 🛍️信用点购物\n"
                "[2026-10-01 15:29:40.000] 任务完成: 🛍️信用点购物\n", encoding="utf-8")
rec = RunRecord(run_id="2026-10-01/endfield/MaaEnd-11-23-07", script="MaaEnd", user="endfield",
                started=START1, finished=END1, ok=True, log_path=hist)
eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=root, state_dir=root))
msg = verdict._verify_outcome(eng, rec) or ""
check("the later picture is not named", LATER_SHOT in msg, False)
check("its own picture is (the round, like 10-01's, has no 「自动执行任务完成」)", own in msg, True)

print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
