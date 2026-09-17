"""`python -m ark_relay evidence` never builds without a window: --hours, --since,
--run-id (that run's own window) or, with nothing given, the latest run of the
script in the ledger. The user, 2026-09-18: 「证据包永远按时间窗取」.
"""
import json
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import __main__ as cli, evidence
from ark_relay.config import SERVER_TZ

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


now = datetime.now(tz=SERVER_TZ)
with tempfile.TemporaryDirectory() as td:
    cfg = types.SimpleNamespace(state_dir=Path(td))
    day = now.strftime("%Y-%m-%d")
    t_start = (now - timedelta(hours=3)).replace(microsecond=0)
    t_end = t_start + timedelta(minutes=20)
    older = t_start - timedelta(hours=5)
    ledger = Path(td) / f"ledger-{day}.jsonl"
    ledger.write_text("\n".join(json.dumps(e) for e in [
        {"run_id": f"{day}/endfield/MaaEnd-A", "script": "MaaEnd", "started": older.isoformat(), "finished": (older + timedelta(minutes=9)).isoformat(), "duration_known": True, "ok": True, "user": "u"},
        {"run_id": f"{day}/endfield/MaaEnd-B", "script": "MaaEnd", "started": t_start.isoformat(), "finished": t_end.isoformat(), "duration_known": True, "ok": True, "user": "u"},
        {"run_id": f"{day}/arknights/MAA-C", "script": "MAA", "started": t_start.isoformat(), "finished": t_end.isoformat(), "duration_known": True, "ok": True, "user": "u"},
    ]) + "\n", encoding="utf-8")

    print("[什么都不给：最近一趟，它自己的时间窗（前后各放宽 5 分钟）]")
    rid, (t0, t1) = cli.evidence_window(cfg, "MaaEnd")
    check("挑的是最近的 B", rid, f"{day}/endfield/MaaEnd-B")
    check("窗 = 开始-5 分钟 .. 结束+5 分钟", (t0, t1), (t_start.timestamp() - evidence.WINDOW_SLACK, t_end.timestamp() + evidence.WINDOW_SLACK))

    print("\n[--run-id：那一趟的窗]")
    rid, (t0, t1) = cli.evidence_window(cfg, "MaaEnd", run_id=f"{day}/endfield/MaaEnd-A")
    check("是 A", rid.endswith("MaaEnd-A") and t0 == older.timestamp() - evidence.WINDOW_SLACK)
    try:
        cli.evidence_window(cfg, "MaaEnd", run_id="nope"); missing = "accepted"
    except SystemExit as exc:
        missing = str(exc)
    check("账本里没有的 run_id 明说", "没有 nope" in missing)

    print("\n[--hours N：最近 N 小时到现在]")
    rid, (t0, t1) = cli.evidence_window(cfg, "MaaEnd", hours=2)
    check("窗宽约 2 小时", 7190 <= t1 - t0 <= 7210)
    check("run_id 是手动标记", rid.startswith("manual/MaaEnd-"))

    print("\n[--since 时刻：从那时到现在]")
    since = (now - timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M")
    rid, (t0, t1) = cli.evidence_window(cfg, "OK-WW", since=since)
    check("起点是给的时刻（服务器时区）", abs(t0 - datetime.fromisoformat(since).replace(tzinfo=SERVER_TZ).timestamp()) < 1)
    check("终点是现在附近", t1 - now.timestamp() < 5)

    print("\n[没有这个脚本的运行、也没给窗：拒绝，不悄悄全量]")
    try:
        cli.evidence_window(cfg, "OK-WW"); got = "accepted"
    except SystemExit as exc:
        got = str(exc)
    check("明说要 --hours 或 --since", "--hours" in got)

print("\n[打包函数不给窗就拒绝]")
for fn in (lambda: evidence.bundle_for("MaaEnd", types.SimpleNamespace(maaend_dir="/x"), Path("/tmp"), None),
           lambda: evidence.save_and_upload(types.SimpleNamespace(state_dir="/tmp"), "MaaEnd", "r", window=None)):
    try:
        fn(); got = "accepted"
    except (ValueError, TypeError) as exc:
        got = type(exc).__name__
    check("拒绝", got in ("ValueError", "TypeError"))

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("all checks passed")
