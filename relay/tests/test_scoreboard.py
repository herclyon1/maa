"""版本记分牌：每个代码版本跑过几趟、失败几趟，由中继自己数。

**为什么有这一项**（用户 2026-09-06 的原话）：
「设计一个彻底让你不能偷懒的东西。」
「下一趟真实班次自动给这版打分。日报末尾固定一行：『代码 v…，这版跑过 N 趟，失败 M 趟』。
 这行由中继算，不经我手。我说『修好了』而它写『失败 1 趟』，谎话当场现形。」

所以这里要钉死三件事：
1. 计数发生在 `append_ledger` 里——**每趟跑完都必经的那一行**，我写进日报的任何字都动不了它；
2. 被重试取代的那趟（`transitional`）不算失败，否则这个数会天天喊狼来了，然后没人再看它；
3. 记分牌自己出错**不许拖垮记账**：账本是主线。
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import scoreboard
from ark_relay.config import SERVER_TZ, RunRecord
from ark_relay.core import State
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


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
day = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
lines = [json.loads(x) for x in (d4 / f"ledger-{day}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
check("账本照样写进去了", [x["run_id"] for x in lines], ["boom"])

print("\n[这一行真的挂在日报末尾，而且在我写的字之后]")
src = (Path(__file__).resolve().parents[1] / "ark_relay" / "report.py").read_text(encoding="utf-8")
check("日报里调了它", "scoreboard.line(" in src, True)
i, j = src.index("score = scoreboard.line"), src.index('tail = "".join')
check("先算出来再拼进 tail", i < j, True)
check("排在活动和卡池之后", "(act, pool, score)" in src, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
