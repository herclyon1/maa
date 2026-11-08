"""The scoreboard: log times, test windows.

One part per former file, each run on its own (tests/_parts.py): test_scoreboard.py, test_scoreboard_log_time.py, test_scoreboard_test_window.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_main():
    """版本记分牌：每个代码版本跑过几趟、失败几趟，由中继自己数。

**为什么有这一项**（用户 2026-09-06 的原话）：
「设计一个彻底让你不能偷懒的东西。」
「下一趟真实班次自动给这版打分。日报末尾固定一行：『代码 v…，这版跑过 N 趟，失败 M 趟』。
 这行由中继算，不经我手。我说『修好了』而它写『失败 1 趟』，谎话当场现形。」

所以这里要钉死三件事：
1. 计数发生在 `append_ledger` 里——**每趟跑完都必经的那一行**，我写进日报的任何字都动不了它；
2. 被重试取代的那趟（`transitional`）不算失败，否则这个数会天天喊狼来了，然后没人再看它；
3. 记分牌自己出错**不许拖垮记账**：账本是主线。

    Formerly test_scoreboard.py.
    """
    import json
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.report import scoreboard
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.core.ledger import State


    def rec(ok=True, transitional=False, run_id="r1"):
        now = datetime.now(tz=SERVER_TZ)
        return RunRecord(
            run_id=run_id, script="OK-WW", user="wuwa",
            started=now - timedelta(minutes=5), finished=now,
            ok=ok, failed_tasks=[] if ok else ["某一步"], duration_known=True,
            transitional=transitional, raw={})


    print("[数得对：成功、失败、被重试取代的各算什么]")
    d = tmpdir()
    st = State(d)
    st.store.set("versions", "code", "20260908010000")
    st.append_ledger(rec(ok=True, run_id="a"))
    st.append_ledger(rec(ok=False, run_id="b"))
    st.append_ledger(rec(ok=False, transitional=True, run_id="c"))
    board = st.store.get("versions", "scoreboard")["20260908010000"]
    check("三趟都数进去了", board["runs"], 3)
    check("只有真失败那一趟算失败", board["failed"], 1)
    check("记了起算时刻", bool(board.get("since")), True)

    print("\n[那一行的措辞]")
    line = scoreboard.line(st.store, "20260908010000")
    check("点名了版本号", "20260908010000" in line, True)
    check("说了跑过几趟", "跑过 3 趟" in line, True)
    check("说了失败几趟", "失败 1 趟" in line, True)

    st2 = State(tmpdir())
    st2.store.set("versions", "code", "v2")
    st2.append_ledger(rec(ok=True, run_id="x"))
    check("一趟没失败时明说", "一趟没失败" in scoreboard.line(st2.store, "v2"), True)
    check("没跑过的版本也有话说",
          scoreboard.line(st2.store, "从没跑过的版本"), "代码 v从没跑过的版本 · 这版还没跑过一趟")
    check("版本号读不到就不出这一行", scoreboard.line(st2.store, ""), "")

    print("\n[换了版本各记各的，不混在一起]")
    st.store.set("versions", "code", "20260908020000")
    st.append_ledger(rec(ok=False, run_id="d"))
    board = st.store.get("versions", "scoreboard")
    check("旧版本的账没被改", board["20260908010000"]["runs"], 3)
    check("新版本单独一条", board["20260908020000"], {"runs": 1, "failed": 1,
                                                       "since": board["20260908020000"]["since"]})

    print("\n[只留最近几个版本，state.json 不许无限长]")
    st3 = State(tmpdir())
    for i in range(scoreboard.KEEP_VERSIONS + 5):
        st3.store.set("versions", "code", f"v{i:03d}")
        st3.append_ledger(rec(run_id=f"n{i}"))
    board = st3.store.get("versions", "scoreboard")
    check(f"最多留 {scoreboard.KEEP_VERSIONS} 个", len(board), scoreboard.KEEP_VERSIONS)
    check("留的是最新的那些", "v012" in board and "v000" not in board, True)

    print("\n[记分牌坏了也不许拖垮记账——账本是主线]")
    d4 = tmpdir()
    st4 = State(d4)
    st4.store.set("versions", "code", "v9")
    orig = scoreboard.record
    scoreboard.record = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("故意炸"))
    try:
        st4.append_ledger(rec(run_id="boom"))
    finally:
        scoreboard.record = orig
    # append_ledger files a record under the day of `started` (core.py), and rec()
    # starts five minutes before now - so between 00:00 and 00:05 server time the
    # file is yesterday's. Reading "today's" file here made this test fail on
    # 2026-09-19 00:04 (and would every night); read the same day the code wrote.
    boom = rec(run_id="boom")
    day = boom.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
    lines = [json.loads(x) for x in (d4 / f"ledger-{day}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    check("账本照样写进去了", [x["run_id"] for x in lines], ["boom"])

    print("\n[跨午夜：00:03 跑完、23:58 开始的一趟，记在开始那天的账本里]")
    d5 = tmpdir()
    st5 = State(d5)
    st5.store.set("versions", "code", "v10")
    t_end = datetime(2026, 9, 19, 0, 3, tzinfo=SERVER_TZ)
    late = RunRecord(run_id="late", script="OK-WW", user="wuwa", started=t_end - timedelta(minutes=5),
                     finished=t_end, ok=True, failed_tasks=[], duration_known=True, transitional=False, raw={})
    st5.append_ledger(late)
    check("落在 09-18 的账本", (d5 / "ledger-2026-09-18.jsonl").exists(), True)
    check("09-19 的账本不存在", (d5 / "ledger-2026-09-19.jsonl").exists(), False)
    check("记分牌照样数了这一趟", st5.store.get("versions", "scoreboard")["v10"]["runs"], 1)

    print("\n[照算照记进日志，但不再印进日报（用户 2026-09-14）]")
    src = (Path(__file__).resolve().parents[1] / "ark_relay" / "features" / "report" / "report.py").read_text(encoding="utf-8")
    check("日报流程里仍然算它", "scoreboard.line(" in src, True)
    check("不再拼进正文", "(act, pool, score)" in src, False)


def _part_scoreboard_log_time():
    """The scoreboard's 「自 … 起」 is on the machine clock, like the rest of relay.log.

relay.log:33229, written at 10-12 11:49:59 Beijing, said 「自 10-12 12:38 起」
for since 2026-10-12T11:38:15+08:00: the Tokyo clock inside a Beijing log.

    Formerly test_scoreboard_log_time.py.
    """
    #!/usr/bin/env python3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.ledger import State
    from ark_relay.features.report import scoreboard

    d = tmpdir()
    st = State(Path(d))
    st.store.set("versions", "scoreboard", {"20261012033118": {"runs": 1, "since": "2026-10-12T11:38:15+08:00"}})
    got = scoreboard.line(st.store, "20261012033118")
    ok = "（自 10-12 11:38 起）" in got
    print(("  ✓ " if ok else "  ✗ ") + got)
    print("\n" + ("all checks passed" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


def _part_scoreboard_test_window():
    """A run inside a test window does not count on the scoreboard (like the report rows).

10-13: the 11:07 test OK-WW run (test window 11:05:49 open) was counted as
「20261013030327: runs 1」 in state.json. split_test already keeps such runs out
of the daily report; the scoreboard now does the same.

    Formerly test_scoreboard_test_window.py.
    """
    #!/usr/bin/env python3
    import json
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.ledger import State
    from ark_relay.features.report import scoreboard


    V = "20261013030327"
    d = tmpdir()
    st = State(Path(d))
    (Path(d) / "test-windows.json").write_text(json.dumps(
        [{"since": "2026-10-13T11:05:49+08:00", "until": "2026-10-13T11:57:41+08:00"}]), encoding="utf-8")
    scoreboard.record(st.store, V, True, started=datetime(2026, 10, 13, 11, 5, 49, tzinfo=SERVER_TZ))
    check("test run not counted", (st.store.get("versions", "scoreboard") or {}).get(V), None)
    scoreboard.record(st.store, V, True, started=datetime(2026, 10, 13, 9, 0, 36, tzinfo=SERVER_TZ))
    check("real run counted", ((st.store.get("versions", "scoreboard") or {}).get(V) or {}).get("runs"), 1)
    # Booked with no start time while a window is still open (no until): a test.
    (Path(d) / "test-windows.json").write_text(json.dumps(
        [{"since": datetime.now(tz=SERVER_TZ).replace(microsecond=0).isoformat()}]), encoding="utf-8")
    scoreboard.record(st.store, V, False)
    check("open window, no start: not counted", st.store.get("versions", "scoreboard")[V].get("failed"), None)


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_scoreboard_log_time, _part_scoreboard_test_window]))
