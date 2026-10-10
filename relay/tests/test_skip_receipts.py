"""Skip-queue outcomes reach the phone page's receipts, and a failed skip lets go of the day.

2026-09-30 (检查, BOARD/evidence/回执显示-0930 row 2a): process_skip only returned
strings, which the engine pushed as notifications. Nothing went to the receipts
the phone page shows, and on failure _maybe_engage kept the day flag "to retry on
the next tick", so the snapshot's 「今天跳过队列」 still listed the queue and the
page showed the switch as skipped and applied while the queue was going to run.

Now: a failed engage drops the flag and writes a red receipt saying the skip did
not take and the queue runs today; a successful one writes a green receipt whose
text is queues.apply's own answer (「调度程序已确认」 only when the backend read
the value back). Restores write receipts too. The engine pushes a fresh snapshot
after a skip step so the receipt reaches the page without waiting for a refresh.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay import modes
from ark_relay import plan as _plan
from ark_relay import queues as _q
from ark_relay import texts
from ark_relay.config import SERVER_TZ
from ark_relay.statestore import StateStore

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


T0 = datetime(2026, 9, 30, 8, 51, tzinfo=SERVER_TZ)
DAY = T0.strftime("%Y-%m-%d")
AM = Path("/tmp/automas-not-used")
ANSWER = {"早班": (True, ""), "晚班": (True, "")}
live = {"早班": True, "晚班": True}


def fake_apply(d, q, enabled):
    ok, detail = ANSWER[q]
    if ok:
        live[q] = enabled
    return ok, detail


_real_apply, _real_sched = _q.apply, _plan.schedule
_q.apply = fake_apply
_plan.schedule = lambda d: [{"name": q, "times": {"早班": ["09:00"], "晚班": ["21:00"]}[q]}
                           for q in live if live[q]]


def fresh():
    s = tmpdir() / "state"
    s.mkdir(parents=True)
    live.update({"早班": True, "晚班": True})
    return s


def rcpt(s):
    return [(r["action"], r["ok"], r["text"]) for r in modes.receipts(s)]


try:
    print("[a] 生效时失败：回执红、说今天照常跑、当天跳过标记清掉、快照不再列它")
    S = fresh()
    ANSWER["早班"] = (False, "队列「早班」定时关闭没生效：调度程序里它仍是开启")
    modes.add_day_queue(S, DAY, "早班")
    msgs = modes.process_skip(S, AM, T0)
    r = rcpt(S)
    check("一条回执", len(r), 1)
    check("动作是 skip_today（手机开关发的那个）", r and r[0][0], "skip_today")
    check("ok=false", r and r[0][1], False)
    check("回执带队列名、说没生效、今天照常跑",
          bool(r) and all(w in r[0][2] for w in ("「早班」", "没生效", "今天照常跑")), True)
    check("回执带上调度程序的原话", bool(r) and "仍是开启" in r[0][2], True)
    check("推送也是同一句", bool(r) and r[0][2] in msgs, True)
    check("当天跳过标记没了", StateStore(S).get("queues", f"skip_day:{DAY}"), None)
    check("快照的今天跳过队列不再列它", modes.skipped_today_all(S, T0), [])
    check("没留恢复标记", StateStore(S).get("queues", "skip_restore"), None)
    check("队列还开着", live["早班"], True)
    msgs2 = modes.process_skip(S, AM, T0)
    check("下一拍不再重试、不再出消息", msgs2, [])
    check("下一拍不多写回执", len(modes.receipts(S)), 1)

    print("\n[a2] 没有 AUTO-MAS 目录：同样红回执、标记清掉")
    S = fresh()
    modes.add_day_queue(S, DAY, "晚班")
    msgs = modes.process_skip(S, None, T0)
    r = rcpt(S)
    check("一条红回执", [(a, ok) for a, ok, _ in r], [("skip_today", False)])
    check("说了今天照常跑", bool(r) and "今天照常跑" in r[0][2] and "「晚班」" in r[0][2], True)
    check("标记清掉", modes.skipped_today_all(S, T0), [])

    print("\n[a3] 两个队列一个成一个败：只丢败的那个")
    S = fresh()
    ANSWER["早班"] = (False, "队列「早班」定时关闭失败：调度程序报错（超时）")
    ANSWER["晚班"] = (True, "队列「晚班」：定时关闭（调度程序已确认）")
    modes.add_day_queue(S, DAY, "早班")
    modes.add_day_queue(S, DAY, "晚班")
    modes.process_skip(S, AM, T0)
    check("今天跳过的只剩晚班", modes.skipped_today_all(S, T0), ["晚班"])
    check("两条回执：早班红、晚班绿", [(ok, "早班" in t) for _, ok, t in rcpt(S)],
          [(False, True), (True, False)])

    print("\n[b] 生效成功：绿回执，文字是 queues.apply 自己的话")
    S = fresh()
    ANSWER["早班"] = (True, "队列「早班」：定时关闭（调度程序已确认）")
    modes.add_day_queue(S, DAY, "早班")
    modes.process_skip(S, AM, T0)
    r = rcpt(S)
    check("一条绿回执 skip_today", [(a, ok) for a, ok, _ in r], [("skip_today", True)])
    check("带「调度程序已确认」", bool(r) and "队列「早班」：定时关闭（调度程序已确认）" in r[0][2], True)
    check("仍算今天跳过（恢复标记在）", modes.skipped_today_all(S, T0), ["早班"])

    print("\n[b2] 走改文件那条路（调度程序没开）：不说调度程序已确认")
    S = fresh()
    ANSWER["早班"] = (True, "队列「早班」：定时关闭（备份 QueueConfig.bak-20260930-085100.json）")
    modes.add_day_queue(S, DAY, "早班")
    modes.process_skip(S, AM, T0)
    r = rcpt(S)
    check("绿回执", [(a, ok) for a, ok, _ in r], [("skip_today", True)])
    check("没有「调度程序已确认」", bool(r) and "调度程序已确认" in r[0][2], False)
    check("带备份文件名（apply 的原话）", bool(r) and "备份" in r[0][2], True)

    print("\n[c] 过点恢复成功：unskip_today 绿回执")
    ANSWER["早班"] = (True, "队列「早班」：定时开启（调度程序已确认）")
    modes.process_skip(S, AM, datetime(2026, 9, 30, 9, 31, tzinfo=SERVER_TZ))
    r = rcpt(S)
    check("第二条是 unskip_today 绿", r[-1][:2] if r else None, ("unskip_today", True))
    check("文字带队列名和 apply 的原话", bool(r) and "「早班」" in r[-1][2] and "调度程序已确认" in r[-1][2], True)

    print("\n[c2] 过点恢复失败：unskip_today 红回执，每拍重试但回执只写一次")
    S = fresh()
    ANSWER["早班"] = (True, "队列「早班」：定时关闭（调度程序已确认）")
    modes.add_day_queue(S, DAY, "早班")
    modes.process_skip(S, AM, T0)
    ANSWER["早班"] = (False, "队列「早班」定时开启没生效：调度程序里它仍是关闭")
    later = datetime(2026, 9, 30, 9, 31, tzinfo=SERVER_TZ)
    for _ in range(5):
        modes.process_skip(S, AM, later)
    r = rcpt(S)
    check("一绿一红", [(a, ok) for a, ok, _ in r], [("skip_today", True), ("unskip_today", False)])
    check("红的说了恢复失败和原话", bool(r) and "恢复失败" in r[-1][2] and "仍是关闭" in r[-1][2], True)
    check("恢复标记还在（下拍再试）", modes.skipped_today_all(S, T0), ["早班"])
    ANSWER["早班"] = (True, "队列「早班」：定时开启（调度程序已确认）")
    modes.process_skip(S, AM, later)
    check("再试成功补一条绿", rcpt(S)[-1][:2], ("unskip_today", True))

    print("\n[d] 回执文字过人话闸门")
    for _, _, t in rcpt(S):
        check(t[:30], texts.plain(t), [])
finally:
    _q.apply, _plan.schedule = _real_apply, _real_sched

print("\n[e] 引擎：跳过这一步有新消息就把状态推给手机页，同一句不重复推")
TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "h"), ARK_AUTOMAS_DIR="",
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
from ark_relay import engine as eng_mod  # noqa: E402
from ark_relay.config import Config        # noqa: E402
from ark_relay.ledger import State           # noqa: E402


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body))
        return []


class Src:
    def fetch(self, seen):
        return []


cfg = Config()
cfg.state_dir = tmpdir()
e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
e._scripts_running = lambda: False
pushed = []
e._push_state = lambda why: pushed.append(why)
real_ps = modes.process_skip
modes.process_skip = lambda *a, **k: ["跳过「早班」失败：x——没生效，今天照常跑；要跳过请再按一次"]
try:
    e._observe_modes()
    check("推了一次状态", len(pushed), 1)
    e._observe_modes()
    check("同一句第二拍不再推", len(pushed), 1)
    modes.process_skip = lambda *a, **k: []
    e._observe_modes()
    check("没消息不推", len(pushed), 1)
    e._push_state = None
    modes.process_skip = lambda *a, **k: ["另一句"]
    e._observe_modes()
    check("没接手机通道（None）也不出错", len(e.notifier.sent), 2)
finally:
    modes.process_skip = real_ps

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
