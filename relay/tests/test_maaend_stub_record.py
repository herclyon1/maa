"""A MaaEnd record AUTO-MAS wrote for an attempt that never ran is not a run.

Real records, 2026-09-18 morning (tests/fixtures/maaend-2026-09-18/): AUTO-MAS
relaunched MaaEnd at 09:54:35 while MaaEnd was installing its own update and
restarting; the attempt's record is a 30-byte stub with 「未捕获到日志」. The
relay counted it: 「❌ MaaEnd 失败（尝试 3 次）」 for two real attempts, and the
report would have listed a third row. Also: every bundle now carries the
window's slice of relay.log and AUTO-MAS's app.log, because that stub could only
be explained from those two files and neither was in any bundle.
"""
import os
import shutil
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector, core, evidence, handle

FIX = Path(__file__).parent / "fixtures" / "maaend-2026-09-18"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "history"
    d = root / "2026-09-18" / "endfield"
    d.mkdir(parents=True)
    for f in FIX.iterdir():
        shutil.copy(f, d / f.name)
    recs = {n: collector.parse_record(d / f"{n}.json", root) for n in ("MaaEnd-05-26-03", "MaaEnd-05-54-35", "MaaEnd-05-54-44")}

    print("[空记录：解析为「中途重启」，不算失败、不进失败清单]")
    stub = recs["MaaEnd-05-54-35"]
    check("解析出来了", stub is not None)
    check("不算成功", stub.ok, False)
    check("标为中途重启", stub.transitional, True)
    check("失败清单为空", stub.failed_tasks, [])
    real1, real3 = recs["MaaEnd-05-26-03"], recs["MaaEnd-05-54-44"]
    check("真失败的两趟照旧：不是中途重启、失败清单有基质刷取",
          (real1.transitional, real3.transitional, real1.failed_tasks, real3.failed_tasks),
          (False, False, ["基质刷取"], ["基质刷取"]))

    print("\n[尝试次数：只数真跑过的]")
    ledger = [{"run_id": r.run_id, "script": r.script, "user": r.user, "ok": r.ok,
               "started": r.started.isoformat(), "finished": r.finished.isoformat(),
               "failed_tasks": r.failed_tasks, "transitional": r.transitional, "raw": r.raw}
              for r in (real1, stub, real3)]
    eng = types.SimpleNamespace(state=types.SimpleNamespace(read_ledger=lambda day: ledger))
    check("三条记录，尝试 2 次", handle._attempts(eng, real3, "2026-09-18"), 2)

    print("\n[日报：空记录不成一行；两趟真失败合并为一行]")
    kinds = core.episode_kinds(ledger)
    title, body = core.format_daily("2026-09-18", ledger, "", "")
    check("空记录不出现在日报里", "05-54-35" not in body and "未捕获" not in body)
    check("基质刷取的失败出现", "基质刷取" in body)
    check("标题不是全绿", "全绿" not in title)
    check("日报里有一行信息：重启 1 次、未计失败", "MaaEnd 发版自更新重启 1 次，未计失败" in body)
    check("标题只数两趟真失败，不含空记录", "2 项失败" in title)

    print("\n[老版本记的账没有 transitional 标记（09-18 早上的三条就是）：照样不算失败]")
    # The evening report of 2026-09-18 listed the stub as one of three failures:
    # the morning entries were booked by v20260918005050, before the flag existed.
    old_ledger = [dict(e) for e in ledger]
    for e in old_ledger:
        e.pop("transitional", None)
    title_o, body_o = core.format_daily("2026-09-18", old_ledger, "", "")
    check("没有标记也不成一行", "05-54-35" not in body_o and "未捕获" not in body_o)
    check("没有标记也只算 2 项失败（09-18 晚报成了 3 项）", "2 项失败" in title_o)
    check("信息行照样有", "MaaEnd 发版自更新重启 1 次，未计失败" in body_o)
    check("没有重启的日子不出这一行", "自更新重启" not in core.format_daily("2026-09-18", [e for e in ledger if e is not ledger[1]], "", "")[1])

print("\n[证据包带上 relay.log 与调度程序 app.log 的时间窗切片]")
with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    (t / "automas" / "debug").mkdir(parents=True)
    t0 = datetime(2026, 9, 18, 9, 54, 0)
    relay_log = t / "relay.log"
    relay_log.write_text(
        "09-18 09:40:00 INFO    ark.service  太早，不在窗内\n"
        "09-18 09:54:36 WARNING ark.handle  ⏳ MaaEnd 失败，暂不推送，等重试结果\n"
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1\n"
        "09-18 10:30:00 INFO    ark.service  太晚，不在窗内\n", encoding="utf-8")
    (t / "automas" / "debug" / "app.log").write_text(
        "2026-09-18 09:20:00.000 | INFO | 早\n"
        "2026-09-18 09:54:35.100 | INFO | MaaEnd 自动代理 | 启动 MaaEnd\n"
        "2026-09-18 09:54:44.200 | WARNING | MaaEnd 自动代理 | 未捕获到日志\n"
        "2026-09-18 11:00:00.000 | INFO | 晚\n", encoding="utf-8")
    os.environ["ARK_LOG_FILE"] = str(relay_log)
    cfg = types.SimpleNamespace(automas_dir=t / "automas", state_dir=t / "state", maaend_dir=None, maa_dir=None, okww_dir=None, history_dir=None)
    win = (t0.timestamp(), (t0 + timedelta(minutes=12)).timestamp())
    files = evidence.context_files(cfg, win, t / "out")
    names = sorted(p.name for p in files)
    check("两个切片都在", names, ["automas-app.log", "relay.log"])
    rl = (t / "out" / "relay.log").read_text(encoding="utf-8")
    check("中继日志只留窗内的行，堆栈续行跟着", "09:54:36" in rl and "Traceback" in rl and "line 1" in rl and "太早" not in rl and "太晚" not in rl)
    al = (t / "out" / "automas-app.log").read_text(encoding="utf-8")
    check("调度程序日志只留窗内的行", "09:54:35" in al and "未捕获到日志" in al and "早" not in al.replace("早", "", 0) or ("09:20" not in al and "11:00" not in al))
    res = evidence.save_and_upload(cfg, "MaaEnd", "2026-09-18/endfield/MaaEnd-05-54-35", window=win)
    check("save_and_upload 的包里带上了两个切片", set(("relay.log", "automas-app.log")) <= set(res["files"]))
    check("没有 COS 时不炸、包照打", bool(res["archive"]))

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("all checks passed")
