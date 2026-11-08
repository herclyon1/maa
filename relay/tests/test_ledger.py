"""The ledger: bad times, gaps, its guard, incomplete items, one row per run, rewrites, the scoreboard, and what it says is true.

One part per former file, each run on its own (tests/_parts.py): test_ledger_bad_times.py, test_ledger_gap.py, test_ledger_guard.py, test_ledger_incomplete.py, test_ledger_once_per_run.py, test_ledger_rewrite_race.py, test_ledger_scoreboard_started.py, test_ledger_truth_1001.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tmp  # loaded before the parts: its atexit cleanup and env default stay
from _parts import run_parts

_BEFORE_THE_PARTS = (_tmp,)


def _part_ledger_bad_times():
    """账本里一条时间不合法的记录，不能让整天的日报发不出去。

read_ledger 原来只查键在不在。日报和关机判定都要拿 started/finished 去
fromisoformat，值不合法照样 ValueError → 日报发不出 → 关机等日报 → 机器开一夜。
账本是一行一条追加写的，写到一半被关机打断就会留下半行——一天两次关机，
这是能发生的事。

    Formerly test_ledger_bad_times.py.
    """
    import json
    import pathlib
    import sys
    from datetime import datetime

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from _tmp import tmpdir

    fails = []
    d = tmpdir()
    st = core.State(d)
    good = {"run_id": "a", "script": "MAA", "user": "u", "ok": True,
            "started": datetime(2026, 9, 6, 9, 0, tzinfo=SERVER_TZ).isoformat(),
            "finished": datetime(2026, 9, 6, 9, 20, tzinfo=SERVER_TZ).isoformat()}
    bad_value = {**good, "run_id": "b", "started": "2026-09-06 09:0"}   # 被截断的一行
    bad_type = {**good, "run_id": "c", "finished": None}
    (d / "ledger-2026-09-06.jsonl").write_text(
        "\n".join(json.dumps(x) for x in (good, bad_value, bad_type)) + "\n", encoding="utf-8")

    rows = st.read_ledger("2026-09-06")
    ids = [r["run_id"] for r in rows]
    if ids != ["a"]:
        fails.append(f"应只留下合法那条，得到 {ids}")

    # 留下的那些，日报模板必须能渲染（这正是原来会炸的地方）
    try:
        title, body = core.format_daily("2026-09-06", rows)
        if "明日方舟" not in body:
            fails.append("日报里没有那条合法记录")
    except Exception as exc:  # noqa: BLE001
        fails.append(f"日报渲染炸了：{exc}")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_ledger_gap():
    """scripts/mac/ledger-gap.py: a relay.log ERROR with no ledger line is listed.

10-10 04:28:51 the process-start listener's ERROR was fixed (30cc1e94) and never
written into BOARD/报错台账.txt; 验收 found it at 22:4x.

    Formerly test_ledger_gap.py.
    """
    import importlib.util
    import sys
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "ledger_gap", Path(__file__).resolve().parents[2] / "scripts" / "mac" / "ledger-gap.py")
    lg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lg)

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
        if not ok:
            fails.append(label)


    ERR = ["ERR|10-10 04:28:51 ERROR   ark.service  系统的程序启动通知断了 6 秒（远程过程调用失败，0x800706BE），到中继停下时还没重新订上"]
    # Line 190 of the real ledger: another error in the same minute, which must not count.
    BEFORE = ("10-10 04:28 验收 报错：own_mess_guard_test 卡住 2 分钟不退出。 根因：_scope.py 第 14 行非 tty 时读 stdin\n"
              "10-10 17:18 | 开机自检 2 项 ✗（16:14，中继二部署后）\n10-10 20:33 | 样图坐车层\n")
    AFTER = BEFORE + "10-10 22:41 游戏-中继一 | relay.log 10-10 04:28:51 ERROR「系统的程序启动通知断了 6 秒」| 根因 | 已解决\n"

    check("the 10-10 ledger before the entry: listed", len(lg.gaps(ERR, BEFORE)), 1)
    check("after the entry: nothing", lg.gaps(ERR, AFTER), [])
    check("date and second must be on one line", lg.gaps(ERR, "10-10 something\n04:28:51 elsewhere\n") != [], True)
    check("another day's 04:28:51 does not count", lg.gaps(ERR, "10-09 04:28:51 x\n") != [], True)
    check("the same minute is not the same error", lg.gaps(ERR, "10-10 04:28 x\n") != [], True)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_ledger_guard():
    """A malformed ledger line must not be able to keep the machine powered on.

The ledger is line-delimited JSON on a box that is hard power-cut twice a day.
A line can end up valid JSON yet incomplete, and a dozen call sites read these
fields directly - including the deterministic report layout, which is the last
fallback when the wording model is down. A KeyError there means the daily
report is never sent, and the shutdown path waits for a sent report.

    Formerly test_ledger_guard.py.
    """
    import json, logging, sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.ledger import State, format_daily, log as core_log
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    fails = []
    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
        if not ok:
            fails.append(label)

    GOOD = {"run_id": "2026-08-21/arknights/21-30-00", "script": "MAA",
            "user": "arknights", "started": "2026-08-21T21:30:00+08:00",
            "finished": "2026-08-21T22:15:00+08:00", "ok": True,
            "failed_tasks": [], "raw": {"sanity": 6}}

    def ledger(*lines):
        d = tmpdir()
        (d / "ledger-2026-08-21.jsonl").write_text("\n".join(lines), encoding="utf-8")
        return State(d)

    print("[a good line survives]")
    check("kept", len(ledger(json.dumps(GOOD)).read_ledger("2026-08-21")), 1)

    print("\n[torn line: valid JSON, missing fields]")
    st = ledger(json.dumps(GOOD), json.dumps({"script": "MaaEnd"}))
    entries = st.read_ledger("2026-08-21")
    check("incomplete one dropped", len(entries), 1)
    check("the good one kept", entries[0]["run_id"], GOOD["run_id"])

    print("\n[unparseable line]")
    check("dropped", len(ledger(json.dumps(GOOD), "{not json").read_ledger("2026-08-21")), 1)

    print("\n[unparseable line is said once, not on every read]")
    # Until 2026-10-10 the torn line vanished silently while its siblings (missing
    # keys, bad times) warned. read_ledger runs every tick, so once per line.


    class _Warn(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    _w = _Warn()
    core_log.addHandler(_w)
    try:
        st = ledger(json.dumps(GOOD), '{"run_id": "torn' + "x" * 200)
        st.read_ledger("2026-08-21")
        st.read_ledger("2026-08-21")
        torn = [ln for ln in _w.lines if "不是完整的 JSON" in ln]
        check("one WARNING for two reads", len(torn), 1)
        check("quotes the line, cut at 120 chars", torn and torn[0].endswith('{"run_id": "torn' + "x" * 104), True)
        p = st.ledger_path("2026-08-21")
        p.write_text(json.dumps(GOOD), encoding="utf-8")
        st.read_ledger("2026-08-21")
        p.write_text(json.dumps(GOOD) + "\n{bad", encoding="utf-8")
        st.read_ledger("2026-08-21")
        check("said again once the line was gone and a new one tore",
              len([ln for ln in _w.lines if "不是完整的 JSON" in ln]), 2)
    finally:
        core_log.removeHandler(_w)

    print("\n[a JSON value that is not an object]")
    check("dropped", len(ledger(json.dumps(GOOD), "[1,2,3]", '"x"').read_ledger("2026-08-21")), 1)

    print("\n[the report still renders - this is the whole point]")
    entries = ledger(json.dumps(GOOD), json.dumps({"script": "MaaEnd"})).read_ledger("2026-08-21")
    try:
        title, body = format_daily("2026-08-21", entries)
        check("rendered", bool(title and body), True)
        check("mentions the surviving run", "明日方舟" in body, True)
    except Exception as exc:                       # noqa: BLE001
        check(f"rendered (raised {exc!r})", False, True)

    print("\n[every entry malformed: still no crash]")
    entries = ledger(json.dumps({"script": "MAA"}), "{bad").read_ledger("2026-08-21")
    check("nothing survives", entries, [])

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_ledger_incomplete():
    """A failed outcome check must reach the ledger and the daily headline.

Before 2026-09-10 the check only produced a push; the ledger line kept `ok: true`
and the evening report still said 全绿 for a run that walked zero routes.

    Formerly test_ledger_incomplete.py.
    """
    import json
    import sys
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger as core

    fails = []


    def check(label, got, want=True):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
        if not ok:
            fails.append(label)


    with tempfile.TemporaryDirectory() as d:
        st = core.State(Path(d)) if hasattr(core, "State") else None
        if st is None:
            # The ledger lives on whichever class owns append_ledger/read_ledger.
            owner = next(v for v in vars(core).values()
                         if isinstance(v, type) and hasattr(v, "read_ledger") and hasattr(v, "mark_incomplete"))
            st = owner(Path(d))
        day = "2026-09-10"
        e1 = {"run_id": f"{day}/endfield/MaaEnd-05-38-38", "script": "MaaEnd", "user": "endfield",
              "started": "2026-09-10T09:38:38", "finished": "2026-09-10T10:08:38", "ok": True,
              "failed_tasks": [], "raw": {"tasks_done": ["赠送干员礼物", "装备制造", "拜访好友", "基建任务"],
                                          # each task with a line of its own in the log (2026-10-05 rule)
                                          "tasks_evidence": {"赠送干员礼物": "获得 信用 ×400", "装备制造": "获得 嵌晶玉 ×25",
                                                             "拜访好友": "获得 信用 ×200", "基建任务": "获得 燎石子簇 ×1"}}}
        e2 = {"run_id": f"{day}/endfield/MaaEnd-06-08-39", "script": "MaaEnd", "user": "endfield",
              "started": "2026-09-10T10:08:39", "finished": "2026-09-10T10:09:35", "ok": True,
              "failed_tasks": [], "raw": {"tasks_done": ["自动采集"]}}
        with st.ledger_path(day).open("w", encoding="utf-8") as f:
            f.write(json.dumps(e1, ensure_ascii=False) + "\n" + json.dumps(e2, ensure_ascii=False) + "\n")

        print("[写回账本]")
        why = ("MaaEnd 这一轮有 2 项没干成，但它自己没报错：\n"
               "· 新版本认得全部旧设置：MaaEnd 新版本不认 36 项旧设置\n"
               "· 自动采集 真的走了路线：自动采集 38 秒就报「任务完成」，日志里没有走了路线的痕迹")
        check("找得到那条并写回", st.mark_incomplete(day, e2["run_id"], why))
        check("找不到的 run_id 返回 False", st.mark_incomplete(day, "nope", why), False)
        back = st.read_ledger(day)
        check("两条都还在", len(back), 2)
        check("第一条没被碰", "incomplete" not in back[0])
        check("第二条带上原因", back[1].get("incomplete"), why)
        check("ok 仍然是 True（不进重试队列）", back[1]["ok"], True)

        print("\n[日报]")
        title, body = core.format_daily(day, back)
        check("标题不再是全绿", "全绿" not in title)
        check("标题说几项没干完", "1 项没干完" in title)
        check("那一趟的图标是 ⚠️", "⚠️ 终末地" in body)
        check("正文写明没干完的原因", "没干完：" in body and "自动采集" in body)
        check("多条原因并成一行，冒号后面不带分号", "：；" not in body and "没报错：新版本认得全部旧设置" in body)
        check("好的那趟还是 ✅", "✅ 终末地" in body)

        print("\n[只是设置被新版本重置：日报说没按你的设置跑，不说没干完（2026-10-12）]")
        from ark_relay.features.verify import outcome
        reset = outcome.summarize([outcome.Check("任务全部完成（跑完没自己退出）", True),
                                   *outcome._dropped_checks(["AutoStockBuyDailyGoodsValleyIV"])], "MaaEnd")
        title3, body3 = core.format_daily(day, [e1, dict(e2, incomplete=reset)])
        check("标题说没按你的设置跑", "终末地 1 趟没按你的设置跑" in title3, True)
        check("标题不说没干完", "没干完" not in title3, True)
        check("正文那一行以「没按你的设置跑：」开头，不重复总说法", "没按你的设置跑：自动囤货的设置：1 个购买选项" in body3
              and "这一轮没按你的设置跑" not in body3, True)
        check("正文不说没干完", "没干完" not in body3, True)

        print("\n[没有 incomplete 时一切照旧]")
        title2, _ = core.format_daily(day, [e1])
        check("纯绿仍报全绿", "全绿 ✅" in title2)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_ledger_once_per_run():
    """One run is one ledger line, however many times its record is handled.

Follow-up to 359fea45 (2026-10-13): a record whose handling raises after its
ledger line is written is handled again on every retry tick, and once more
after a deploy if it was given up. handle._append_ledger_once skips the append
when read_ledger already has the run, but that check sits outside the ledger
lock and any other caller of State.append_ledger had no guard at all, so the
same run could be booked twice. State.append_ledger now keeps the existing
line for a (day, run_id) already in the ledger.

    Formerly test_ledger_once_per_run.py.
    """
    import json
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger
    from ark_relay.core.config import RunRecord, SERVER_TZ

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
        if not ok:
            fails.append(label)


    def rec(hms: str, ok: bool = True) -> RunRecord:
        t = datetime(2026, 10, 13, int(hms[:2]), int(hms[3:5]), int(hms[6:]), tzinfo=SERVER_TZ)
        return RunRecord(run_id=f"2026-10-13/arknights/{hms}", script="MAA", user="arknights",
                         started=t, finished=t + timedelta(minutes=20), ok=ok)


    def lines(st, day="2026-10-13"):
        p = st.ledger_path(day)
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


    print("[handling raises after the ledger write; the record is retried 3 times]")
    st = ledger.State(tmpdir())
    st.store.set("versions", "code", "v1")
    r = rec("05-00-00")
    for _ in range(3):
        try:
            st.append_ledger(r)
            raise RuntimeError("judging failed after the ledger write")
        except RuntimeError:
            pass
    got = lines(st)
    check("exactly one ledger line for the run", [e["run_id"] for e in got], [r.run_id])

    print("[a mark written after the first append survives the retry]")
    st.mark_incomplete("2026-10-13", r.run_id, "no evidence")
    st.append_ledger(r)
    got = lines(st)
    check("still one line, mark kept", ([e["run_id"] for e in got], got[0].get("incomplete")),
          ([r.run_id], "no evidence"))

    print("[the scoreboard counts the run once]")
    board = st.store.get("versions", "scoreboard") or {}
    check("one run scored for v1", (board.get("v1") or {}).get("runs"), 1)

    print("[another run on the same day is still appended]")
    st.append_ledger(rec("06-00-00"))
    check("two runs, two lines", len(lines(st)), 2)

    if fails:
        print(f"\n{len(fails)} FAIL: {fails}")
        sys.exit(1)
    print("\nall checks passed")


def _part_ledger_rewrite_race():
    """An append landing during a ledger rewrite must not be lost.

Audit s4 A6 (2026-10-13): State._rewrite_entry (mark_incomplete / mark_raw /
mark_evidence) reads the day's ledger, edits one line and replaces the whole file.
append_ledger runs on another thread (the engine's next record) with no lock; an
append between the read and the replace vanished from the day, so the daily report
and the boot-check missed that run.

Made deterministic: the rewrite is held just before its replace while the append runs.

    Formerly test_ledger_rewrite_race.py.
    """
    import sys
    import threading
    import time
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger
    from ark_relay.core.config import RunRecord, SERVER_TZ

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
        if not ok:
            fails.append(label)


    def rec(hms: str) -> RunRecord:
        t = datetime(2026, 10, 13, int(hms[:2]), int(hms[3:5]), int(hms[6:]), tzinfo=SERVER_TZ)
        return RunRecord(run_id=f"2026-10-13/arknights/{hms}", script="MAA", user="arknights",
                         started=t, finished=t + timedelta(minutes=20), ok=True)


    print("[an append runs while mark_incomplete is between its read and its replace]")
    st = ledger.State(tmpdir())
    st.append_ledger(rec("05-00-00"))
    real_write = ledger.atomic_write_text
    other: list = []


    def slow_write(path, text, *a, **k):
        if not other:
            t = threading.Thread(target=lambda: st.append_ledger(rec("06-00-00")))
            other.append(t)
            t.start()
            time.sleep(0.3)          # the append gets every chance to land now
        return real_write(path, text, *a, **k)


    ledger.atomic_write_text = slow_write
    try:
        hit = st.mark_incomplete("2026-10-13", "2026-10-13/arknights/05-00-00", "no evidence")
    finally:
        ledger.atomic_write_text = real_write
    other[0].join(5)
    rows = {e["run_id"]: e for e in st.read_ledger("2026-10-13")}
    check("the rewrite found its line", hit, True)
    check("the rewritten line carries the mark",
          rows.get("2026-10-13/arknights/05-00-00", {}).get("incomplete"), "no evidence")
    check("the appended run is still in the day", "2026-10-13/arknights/06-00-00" in rows, True)

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")
    sys.exit(1 if fails else 0)


def _part_ledger_scoreboard_started():
    """append_ledger hands the run's start time to the scoreboard when it takes one.

Follow-up to d1bc5721 (2026-10-13): scoreboard.record takes an optional start
time and otherwise judges a test run by now; append_ledger did not pass it, so a
run booked after its test window closed was scored. append_ledger now passes
started=rec.started when scoreboard.record accepts it, and still calls the
older signature without it.

    Formerly test_ledger_scoreboard_started.py.
    """
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger
    from ark_relay.core.config import RunRecord, SERVER_TZ

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
        if not ok:
            fails.append(label)


    def rec(hms: str) -> RunRecord:
        t = datetime(2026, 10, 13, int(hms[:2]), int(hms[3:5]), int(hms[6:]), tzinfo=SERVER_TZ)
        return RunRecord(run_id=f"2026-10-13/arknights/{hms}", script="MAA", user="arknights",
                         started=t, finished=t + timedelta(minutes=20), ok=True)


    real = ledger.scoreboard.record
    calls = []
    try:
        print("[scoreboard.record takes started]")

        def new_record(store, code_version, ok, transitional=False, started=None):
            calls.append(started)
        ledger.scoreboard.record = new_record
        st = ledger.State(tmpdir())
        st.store.set("versions", "code", "v1")
        r = rec("05-00-00")
        st.append_ledger(r)
        check("passed the run's start time", calls, [r.started])

        print("[older scoreboard.record without started]")
        calls.clear()

        def old_record(store, code_version, ok, transitional=False):
            calls.append("called")
        ledger.scoreboard.record = old_record
        st.append_ledger(rec("06-00-00"))
        check("still called, no TypeError", calls, ["called"])
    finally:
        ledger.scoreboard.record = real

    if fails:
        print(f"\n{len(fails)} FAIL: {fails}")
        sys.exit(1)
    print("\nall checks passed")


def _part_ledger_truth():
    """The ledger tells the truth about killed runs: their verdict and their end.

2026-10-01, seven records. Two were wrong in the ledger and so in the daily
report: MaaEnd's 15:24 attempt (plugin crashed, AUTO-MAS killed it for
「MaaEnd 进程超时」) read as a success, and every timed-out attempt ended at its
log's last line - OK-WW at 09:19 / 11:21 / 13:22 - instead of when AUTO-MAS
killed it (11:20 / 13:21 / 15:23). The JSON verdicts and app.log result lines
below are verbatim from the machine; the run logs keep their real first and
last stamps.

    Formerly test_ledger_truth_1001.py.
    """
    import json
    import sys
    from datetime import datetime
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.core.config import SERVER_TZ
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
        if not ok:
            fails.append(label)


    root = tmpdir() / "AUTO-MAS"
    hist = root / "history"
    (root / "debug").mkdir(parents=True)
    (root / "debug" / "app.log").write_text("\n".join([
        "2026-10-01 09:18:16.344 | INFO     | MAA 自动代理 | MAA 任务结果: Success!, 日志锁已释放",
        "2026-10-01 11:20:12.246 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 13:21:12.400 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 15:23:06.615 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 16:10:00.012 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 进程超时, 日志锁已释放",
        "2026-10-01 16:11:10.839 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 部分任务执行失败: 🎁赠送干员礼物, 日志锁已释放",
        "2026-10-01 17:27:43.100 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: Success!, 日志锁已释放",
    ]) + "\n", encoding="utf-8")


    def record(user, stem, verdict, log_lines):
        d = hist / "2026-10-01" / user
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stem}.json").write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
        (d / f"{stem}.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        return collector.parse_record(d / f"{stem}.json", hist)


    def at(hh, mm, ss=0):
        return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)


    def okww_log(h, m, s, h2, m2, s2):
        return [f"2026-10-01 {h:02d}:{m:02d}:{s:02d},787 INFO MainThread ok:ok-script init v3.6.9-beta.1",
                f"2026-10-01 {h2:02d}:{m2:02d}:{s2:02d},632 INFO MainThread UpdateCard:update_available=False"]


    print("[OK-WW's three timed-out attempts end when AUTO-MAS killed them]")
    for stem, a, b, want in (("OK-WW-05-18-20", (9, 18, 37), (9, 19, 16), at(11, 20, 12)),
                             ("OK-WW-07-20-22", (11, 20, 35), (11, 21, 10), at(13, 21, 12)),
                             ("OK-WW-09-21-22", (13, 21, 35), (13, 22, 10), at(15, 23, 6))):
        r = record("wuwa", stem, {"general_result": "OK-WW 运行超时"}, okww_log(*a, *b))
        check(f"{stem} failed", r.ok, False)
        check(f"{stem} ends {want:%H:%M:%S}", r.finished, want)
        check(f"{stem} starts where its log starts", r.started, at(*a))

    print("\n[MaaEnd 15:24: plugin crashed, killed for 进程超时 -> a failure, ending 16:10:00]")
    r = record("endfield", "MaaEnd-11-23-07", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 15:24:12.047] 正在连接窗口... Endfield",
        "[2026-10-01 15:26:00.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-01 15:27:00.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-01 15:28:00.000] 任务开始: 🛍️信用点购物",
        "[2026-10-01 15:29:59.681] 信用 ×300"])
    check("not a success", r.ok, False)
    check("says it timed out", r.failed_tasks, ["MaaEnd 进程超时"])
    check("ends 16:10:00", r.finished, at(16, 10, 0))

    print("\n[MaaEnd 16:11: a real partial failure keeps its own log end]")
    r = record("endfield", "MaaEnd-12-10-02",
               {"maaend_result": "MaaEnd 部分任务执行失败: 🎁赠送干员礼物、🔧装备制造"},
               ["[2026-10-01 16:11:06.462] 正在连接窗口... Endfield",
                "[2026-10-01 16:11:06.808] 稳定性最好，需要游戏窗口保持在最前且不被遮挡，会完全抢占鼠标"])
    check("failed", r.ok, False)
    check("its tasks", r.failed_tasks, ["赠送干员礼物", "装备制造"])
    check("ends 16:11:06", r.finished, at(16, 11, 6))

    print("\n[MaaEnd 16:12 Success!, MAA 09:00 Success! - unchanged]")
    r = record("endfield", "MaaEnd-12-11-12", {"maaend_result": "Success!"},
               ["[2026-10-01 16:12:15.138] 正在连接窗口... Endfield",
                "[2026-10-01 16:58:19.333] 任务开始: ❌关闭游戏（PC）",
                "[2026-10-01 16:58:22.143] 任务完成: ❌关闭游戏（PC）"])
    check("MaaEnd ok", (r.ok, r.finished), (True, at(16, 58, 22)))
    r = record("arknights", "MAA-05-00-01", {"maa_result": "Success!"},
               ["[2026-10-01 09:00:50.368][INF][Bootstrapper] ===", "[2026-10-01 09:18:15.000][INF] done"])
    check("MAA ok", (r.ok, r.finished), (True, at(9, 18, 15)))

    print("\n[MaaEnd finished every task, then never exited and was killed (09-28 11:22 shape)]")
    r = record("endfield", "MaaEnd-07-22-00", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 10:29:47.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-01 10:40:00.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-01 11:22:10.000] 任务开始: ❌关闭游戏（PC）",
        "[2026-10-01 11:22:10.500] 任务完成: ❌关闭游戏（PC）"])
    check("the work was done -> ok", r.ok, True)
    check("marked as done-then-hung", r.raw.get("maaend_done_then_hung"), True)
    check("its work ended at 11:22:10", r.finished, at(11, 22, 10))

    print("\n[timed out, every started task finished, but 关闭游戏 never ran: hung between tasks -> failure]")
    r = record("endfield", "MaaEnd-07-30-00", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 10:29:47.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-01 10:40:00.000] 任务完成: 🎁赠送干员礼物"])
    check("not a success", r.ok, False)
    check("says it timed out", r.failed_tasks, ["MaaEnd 进程超时"])
    check("not marked done-then-hung", r.raw.get("maaend_done_then_hung"), None)

    print("\n[timed out before any task started -> failure]")
    r = record("endfield", "MaaEnd-07-31-00", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 10:29:47.000] 正在连接窗口... Endfield"])
    check("not a success", r.ok, False)

    print("\n[timed out inside 关闭游戏 (started, never finished) -> failure]")
    r = record("endfield", "MaaEnd-07-32-00", {"maaend_result": "MaaEnd 进程超时"}, [
        "[2026-10-01 10:29:47.000] 任务开始: 🎁赠送干员礼物",
        "[2026-10-01 10:40:00.000] 任务完成: 🎁赠送干员礼物",
        "[2026-10-01 11:22:10.000] 任务开始: ❌关闭游戏（PC）"])
    check("not a success", r.ok, False)

    print("\n[no app.log (older day, rotated away) -> keep the log end]")
    (root / "debug" / "app.log").unlink()
    r = record("wuwa", "OK-WW-01-00-00", {"general_result": "OK-WW 运行超时"}, okww_log(5, 0, 0, 5, 1, 0))
    check("falls back to the log", r.finished, at(5, 1, 0))

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_ledger_bad_times, _part_ledger_gap, _part_ledger_guard, _part_ledger_incomplete, _part_ledger_once_per_run, _part_ledger_rewrite_race, _part_ledger_scoreboard_started, _part_ledger_truth]))
