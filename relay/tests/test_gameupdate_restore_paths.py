"""A script pulled from a queue for a game update goes back on every path.

The user, 2026-09-03: 「当天队列里不跑他」 - today's queue only. A pull that is not
put back takes his task out of every later day, which nobody asked for
(「我开的任务是谁说要关的」, 2026-10-06). So: the after-queue job puts it back on
every way out (an exception included), the boot check puts back a pull from an
earlier day before it does anything else, and the update switch being off does
not keep it out.
"""
import sys
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402
from ark_relay import gameupdate as gu  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


def _cfg():
    st = tmpdir()
    return types.SimpleNamespace(state_dir=st, automas_dir=None, maa_dir=None, maaend_dir=None, okww_dir=None)


REC = {"queue": "早班", "queueId": "Q", "script": "MAA", "scriptId": "S", "position": 1}
restored = []
saved = gu.restore_skips


def _fake_restorer(rec):
    restored.append((rec["script"], rec.get("day")))
    return True


def _restore(state_dir, restorer=None, **kw):
    return saved(state_dir, restorer=_fake_restorer, **kw)


gu.restore_skips = _restore
try:
    print("[队列后那一步中途出错：摘掉的照样加回]")
    cfg = _cfg()
    gu._add_skip(cfg.state_dir, dict(REC, day="2026-09-04"))
    gu.mark_pending(cfg.state_dir, "明日方舟", "维护")
    real_prep = gu._prepare_until_ready
    gu._prepare_until_ready = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        gu.run_deferred(cfg, now=datetime(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ), desk=object(),
                        dispatch=lambda s: (True, "ok"), sleep=lambda s: None)
        check("异常照样往外抛（由调用方报）", False, True)
    except RuntimeError:
        check("异常照样往外抛（由调用方报）", True, True)
    finally:
        gu._prepare_until_ready = real_prep
    check("出错也加回了", (restored, gu.skips(cfg.state_dir)), ([("MAA", "2026-09-04")], []))

    print("\n[总开关关着 / 没登记了：摘掉的也加回]")
    restored.clear()
    cfg = _cfg()
    gu._add_skip(cfg.state_dir, dict(REC, day="2026-09-04"))
    gu.run_deferred(cfg, now=datetime(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ), desk=object())
    check("没登记：加回", [r[0] for r in restored], ["MAA"])

    print("\n[开机：之前哪天摘掉没加回的先加回；今天摘的不动]")
    restored.clear()
    cfg = _cfg()
    gu._add_skip(cfg.state_dir, dict(REC, day="2026-09-04"))
    gu._add_skip(cfg.state_dir, dict(REC, queueId="Q2", queue="晚班", day="2026-09-05"))
    gu._add_skip(cfg.state_dir, dict(REC, queueId="Q3", queue="午班"))          # written before records had a day
    gu.boot_check(cfg, budget_s=0, now=datetime(2026, 9, 5, 8, 40, tzinfo=gu.SERVER_TZ),
                  hint=lambda n: "", wuwa_fetch=lambda: {"game": []}, maint_sources={})
    check("前一天的和没写日期的加回了", sorted(restored, key=str), sorted([("MAA", "2026-09-04"), ("MAA", None)], key=str))
    check("今天摘的留着", [r["queue"] for r in gu.skips(cfg.state_dir)], ["晚班"])
finally:
    gu.restore_skips = saved

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
