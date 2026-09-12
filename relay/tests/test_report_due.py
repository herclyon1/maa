"""日报什么时候该发、什么时候不许发，以及发出去的那份里必须有什么。

**这里坏了的后果不是「少了一条通知」，是机器整夜不关。** `_maybe_shutdown` 的前提之一
就是 `report_sent(今天)`，日报发不出去 → 关机永远等不到条件 → 机器开一整夜
（docs/PITFALLS.md 里那次是判据写错：条件用「最后一趟的**结束时刻**」和 21:30 比，
队列挪到 21:25、21:28 跑完之后这个条件**永远为真**，日报永远发不出，机器永远不关）。

report.py 的 10 个函数里 5 个从来没被执行过，`_maybe_daily_report`、`_compose_daily`、
`_maybe_interim_report` 都在里面。这个文件补的就是这几条路，钉住六件事：

1. 昨天的日报没发出去，过了零点只剩今天这一次机会——必须先补昨天；
2. 同一天不许发两遍（记号是 `marks: report:<日期>`），但**推送失败时不许落记号**，
   否则那一天就永远丢了；
3. 一天里一条记录都没有时不发也不落记号（落了记号，晚到的那趟就永远不会被报）；
4. 到点之前、脚本还在跑、队列还没跑完，一律再等——尤其最后一条：cutoff 就是晚班的
   **发车时刻**，那几秒游戏还在启动，只看早班记录会写出一份「今天就这些」的假日报，
   还把当天记号落掉，晚班从此无人过问；
5. 末尾那行版本记分（`scoreboard.line`）必须真的挂上去，而且在我写的任何字之后——
   用户 2026-09-06：「我说『修好了』而它写『失败 1 趟』，谎话当场现形。」；
6. 模型撰写不可用时走结构化模板，那是**正常路径不是故障**，不许在日志里留假伤
   （天天一条假 WARNING，真的那条就没人看了）。

不联网：卡池和撰写模型都换成了本地假货，AUTO-MAS 目录一律 None。
"""
import json
import logging
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import report, scoreboard
from ark_relay.config import SERVER_TZ
from ark_relay.core import State

fails = []


def check(label, got, want):
    ok = got == want
    text = repr(got)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f": got {text[:200]}, want {want!r}"))
    if not ok:
        fails.append(label)


# ---------------------------------------------------------- 把外面的世界掐掉
# 卡池要连 prts.wiki / 库街区 / 森空岛；撰写模型要连大模型。两个都换成本地假货，
# 这个文件才既跑得快又不会因为别人家的网站抖一下就变红。
SCHEDULE: list = []
report.plan = types.SimpleNamespace(
    schedule=lambda automas_dir: list(SCHEDULE),
    next_plan=lambda automas_dir: "",
    activity_countdown=lambda automas_dir: "",
)
report.banners = types.SimpleNamespace(
    collect=lambda now, skland_token="", failed=None, notes=None, trace=None: ([], {}),
    render=lambda rows, now, nxt, previews, notes=None, trace=None: "",
    previews=lambda now, rows, ends, trace=None: [],
    Trace=types.SimpleNamespace(new=lambda: None),
    save_trace=lambda state_dir, now, text, tr: None,
    version_ends=lambda now, rows: {},
)
MODEL = {"text": ""}          # "" = 撰写模型不可用，走结构化模板
report.summary = types.SimpleNamespace(
    daily_report=lambda cfg, entries, plan="": MODEL["text"])


class LogGrab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list = []

    def emit(self, record):
        self.records.append(record)

    def worst(self):
        return max((r.levelno for r in self.records), default=0)


GRAB = LogGrab()
# 直接挂 report 自己那个 logger 对象，不写死日志名：名字要是改了，这里跟着走。
report.log.addHandler(GRAB)
report.log.setLevel(logging.DEBUG)


# --------------------------------------------------------------- 替身零件
class FakeNotifier:
    """记下发出去的每一条；`broken` 时每次都返回「一个渠道都没送到」。"""

    def __init__(self):
        self.sent: list = []
        self.groups: list = []
        self.broken = False

    def send(self, title, body, *, alert=False):
        self.sent.append((title, body, alert))
        return ["Server酱: 假装挂了"] if self.broken else []

    def send_group(self, title, body):
        self.groups.append((title, body))
        return []

    def send_group_image(self, path):
        return []

    def titles(self):
        return [t for t, _, _ in self.sent]


class Eng:
    """Engine 里跟日报有关的那一小块，其余全部换成可控的替身。
    转发方式跟 engine.py 里一模一样，改了那边的签名这里会当场对不上。"""

    def __init__(self, state, *, interim=True, last_run_after="21:30"):
        self.cfg = types.SimpleNamespace(
            automas_dir=None, history_dir=None, okww_dir=None, skland_token="",
            state_dir=None, last_run_after=last_run_after, interim_report=interim)
        self.state = state
        self.notifier = FakeNotifier()
        self.running = False
        self.unfinished: list = []
        self.manual = False

    def _report_cutoff(self, now):
        return report._report_cutoff(self, now)

    def _scripts_running(self):
        return self.running

    def _unfinished_queues(self, now, entries):
        return list(self.unfinished)

    def _round_is_manual(self, new_entries):
        return self.manual

    def _compose_daily(self, day, entries):
        return report._compose_daily(self, day, entries)

    def _announce_banners(self, now, nxt):
        return None

    def send_daily_now(self, mark=True, label="临时查看"):
        return report.send_daily_now(self, mark, label)


TODAY = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
YDAY = (datetime.now(tz=SERVER_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


def entry(day, n=1, script="MAA", ok=True):
    start = datetime.fromisoformat(f"{day}T09:0{n}:00+08:00")
    return {"run_id": f"{day}/ark/0{n}", "script": script, "user": "ark",
            "started": start.isoformat(),
            "finished": (start + timedelta(minutes=20)).isoformat(),
            "ok": ok, "failed_tasks": [] if ok else ["某一步炸了"], "raw": {}}


def make(entries_by_day=None, **kw):
    """一台干净的机器：真 State（记号和账本都是真的），假通知和假队列。"""
    st = State(tmpdir())
    for day, rows in (entries_by_day or {}).items():
        st.ledger_path(day).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8")
    return Eng(st, **kw)


def at(day, hhmm):
    return datetime.fromisoformat(f"{day}T{hhmm}:00+08:00").astimezone(SERVER_TZ)


# =========================================================== 日报什么时候到点
print("[到点时刻跟着 AUTO-MAS 自己的队列走，不是写死的]")
SCHEDULE[:] = [{"name": "早班", "times": ["09:00"]},
               {"name": "晚班", "times": ["21:25"]}]
e = make()
check("取最晚那一条队列的时刻",
      e._report_cutoff(at(TODAY, "12:00")).strftime("%H:%M"), "21:25")
SCHEDULE[:] = []
check("读不到队列才退回 ARK_LAST_RUN_AFTER",
      e._report_cutoff(at(TODAY, "12:00")).strftime("%H:%M"), "21:30")
bad = make(last_run_after="晚上")
try:
    got = bad._report_cutoff(at(TODAY, "12:00")).strftime("%H:%M")
except Exception as exc:                      # noqa: BLE001
    got = f"抛了 {exc!r}"
check("时刻写坏了兜底 21:30，不抛异常——抛了这一轮连关机也一起没了", got, "21:30")

# ================================================= 昨天没发出去，今天必须先补
print("\n[昨天的日报没发出去：过了零点只剩这一次机会]")
e = make({YDAY: [entry(YDAY)], TODAY: [entry(TODAY)]})
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("补发那条排在最前", e.notifier.titles()[0].endswith("（补发）"), True)
check("昨天的记号落上了", e.state.report_sent(YDAY), True)
check("今天那条照发，不是拿补发顶替", len(e.notifier.sent), 2)
check("今天的记号也落上了", e.state.report_sent(TODAY), True)

print("\n[补发也推不出去时：不许落记号，下一轮还要再补]")
e = make({YDAY: [entry(YDAY)]})
e.notifier.broken = True
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("试着发了", len(e.notifier.sent), 1)
check("昨天的记号绝不能落", e.state.report_sent(YDAY), False)
e.notifier.broken = False
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("下一轮补上了", e.state.report_sent(YDAY), True)

print("\n[昨天已经发过 / 昨天一条记录都没有：都不许补]")
e = make({YDAY: [entry(YDAY)]})
e.state.mark_report_sent(YDAY)
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("发过了就不重发", e.notifier.sent, [])
e = make({TODAY: [entry(TODAY)]})
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("昨天没跑过就不补一份空的",
      [t for t in e.notifier.titles() if "补发" in t], [])

# ============================================================ 同一天只发一遍
print("\n[同一天不许发两遍]")
e = make({TODAY: [entry(TODAY)]})
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("发了一条", len(e.notifier.sent), 1)
check("落了 report:<日期> 记号", e.state.report_sent(TODAY), True)
report._maybe_daily_report(e, at(TODAY, "22:05"))
check("第二轮什么都不发", len(e.notifier.sent), 1)
check("记号是写在 marks 里的",
      e.state.store.get("marks", f"report:{TODAY}") is not None, True)

print("\n[推送失败时不许落记号：落了这一天就永远丢了]")
e = make({TODAY: [entry(TODAY)]})
e.notifier.broken = True
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("没落记号", e.state.report_sent(TODAY), False)
e.notifier.broken = False
report._maybe_daily_report(e, at(TODAY, "22:01"))
check("下一轮重发成功", len(e.notifier.sent), 2)
check("这才落记号", e.state.report_sent(TODAY), True)

# ================================================================ 什么时候等
print("\n[没到点、还在跑、队列没跑完——一律再等]")
e = make({TODAY: [entry(TODAY)]})
report._maybe_daily_report(e, at(TODAY, "20:00"))
check("没到点不发", e.notifier.sent, [])
e.running = True
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("脚本还在跑不发", e.notifier.sent, [])
e.running = False
e.unfinished = ["晚班还没跑完"]
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("队列没跑完不发——cutoff 就是晚班发车时刻，那几秒游戏还没起来",
      e.notifier.sent, [])
check("也没落记号，不然晚班从此没人问", e.state.report_sent(TODAY), False)
e.unfinished = []
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("跑完了才发", len(e.notifier.sent), 1)

print("\n[一天里一条记录都没有]")
e = make({TODAY: []})
report._maybe_daily_report(e, at(TODAY, "22:00"))
check("不发空日报", e.notifier.sent, [])
check("更不许落记号——落了，晚到的那趟就永远不会被报",
      e.state.report_sent(TODAY), False)
print("  （人主动要的时候是另一回事：问了就得有答案）")
e2 = make({TODAY: []})
check("手动 report 命令照发", e2.send_daily_now(), True)
check("正文说清楚今天没跑过", "今天没有任何运行记录。" in e2.notifier.sent[0][1], True)

# ====================================================== 末尾那行版本记分牌
print("\n[版本记分那一行必须真的挂在日报末尾]")
e = make({TODAY: [entry(TODAY, ok=False)]})
e.state.store.set("versions", "code", "9.9.9")
scoreboard.record(e.state.store, "9.9.9", ok=True)
scoreboard.record(e.state.store, "9.9.9", ok=False)
want_line = scoreboard.line(e.state.store, "9.9.9")
check("记分牌自己算出来的那一串不是空的", want_line.startswith("代码 v9.9.9"), True)
check("它数的是真跑过的趟数", "跑过 2 趟，失败 1 趟" in want_line, True)
_, body = e._compose_daily(TODAY, e.state.read_ledger(TODAY))
check("原样出现在正文里", want_line in body, True)
check("而且在最后——我写的任何字都盖不住它", body.endswith(want_line), True)
e2 = make({TODAY: [entry(TODAY)]})
_, body2 = e2._compose_daily(TODAY, e2.state.read_ledger(TODAY))
check("没记录版本号时不留一截空尾巴", body2.rstrip(), body2)

# ============================================== 模型撰写 vs 结构化模板
print("\n[模型能写的时候用模型那份]")
MODEL["text"] = "今天早班晚班都跑完了，理智没剩。"
e = make({TODAY: [entry(TODAY)]})
title, body = e._compose_daily(TODAY, e.state.read_ledger(TODAY))
check("标题是代码算的，不是模型编的", title, f"📋 {TODAY[5:]} · 全绿 ✅")
check("模型那段在正文里", MODEL["text"] in body, True)

print("\n[模型不可用 → 结构化模板，这是正常路径不是故障]")
MODEL["text"] = ""
GRAB.records.clear()
e = make({TODAY: [entry(TODAY)]})
title, body = e._compose_daily(TODAY, e.state.read_ledger(TODAY))
check("照样出得来一份日报", bool(title and body), True)
check("走的是结构化模板那条路", "9:01" in body or "09:01" in body, True)
check("日志里一条 WARNING 都不许有——假伤会让真伤没人看",
      GRAB.worst() < logging.WARNING, True)
check("而且确实说了这是正常路径",
      any("正常路径" in r.getMessage() for r in GRAB.records), True)

# ============================================================ 白天那份速览
print("\n[白天速览：关掉就不发]")
e = make({TODAY: [entry(TODAY)]}, interim=False)
report._maybe_interim_report(e, at(TODAY, "12:00"))
check("开关关着就一条都不发", e.notifier.sent, [])

print("\n[到点之后不发速览，让真日报说话]")
e = make({TODAY: [entry(TODAY)]})
report._maybe_interim_report(e, at(TODAY, "22:00"))
check("过了 cutoff 就闭嘴", e.notifier.sent, [])

print("\n[今天日报已经发过 / 没有记录 / 还在跑 / 队列没完：都不发]")
e = make({TODAY: [entry(TODAY)]})
e.state.mark_report_sent(TODAY)
report._maybe_interim_report(e, at(TODAY, "12:00"))
check("日报发过了就不再速览", e.notifier.sent, [])
e = make({TODAY: []})
report._maybe_interim_report(e, at(TODAY, "12:00"))
check("没记录不发", e.notifier.sent, [])
e = make({TODAY: [entry(TODAY)]})
e.running = True
report._maybe_interim_report(e, at(TODAY, "12:00"))
check("还在跑不发", e.notifier.sent, [])
e.running = False
e.unfinished = ["早班还没跑完"]
report._maybe_interim_report(e, at(TODAY, "12:00"))
check("队列没跑完不发", e.notifier.sent, [])

print("\n[早班跑完就发一份速览，但**不许吃掉当天的日报**]")
e = make({TODAY: [entry(TODAY, 1), entry(TODAY, 2)]})
report._maybe_interim_report(e, at(TODAY, "12:00"))
check("发了一条", len(e.notifier.sent), 1)
check("标题是 🔎 不是 📋", e.notifier.titles()[0].startswith("🔎"), True)
check("说清是临时查看", "（临时查看）" in e.notifier.titles()[0], True)
check("当天日报的记号绝不能落——落了晚上那份就没了",
      e.state.report_sent(TODAY), False)
check("记下这一轮盖到第几条", e.state.interim_covered(TODAY), 2)

print("\n[同一轮不重发；补跑多出来的那一条要另算一轮]")
report._maybe_interim_report(e, at(TODAY, "12:05"))
check("同一轮闭嘴", len(e.notifier.sent), 1)
rows = e.state.read_ledger(TODAY) + [entry(TODAY, 3)]
e.state.ledger_path(TODAY).write_text(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
report._maybe_interim_report(e, at(TODAY, "15:00"))
check("补跑了就再报一次", len(e.notifier.sent), 2)
check("覆盖数跟着往前推", e.state.interim_covered(TODAY), 3)

print("\n[手动触发的那一轮要说是手动的——人得知道这份速览为什么冒出来]")
e = make({TODAY: [entry(TODAY)]})
e.manual = True
report._maybe_interim_report(e, at(TODAY, "12:00"))
check("标签是手动执行", "（手动执行）" in e.notifier.titles()[0], True)

print("\n[速览推不出去时不许记覆盖数，否则这一轮就永远没人报了]")
e = make({TODAY: [entry(TODAY)]})
e.notifier.broken = True
report._maybe_interim_report(e, at(TODAY, "12:00"))
check("试着发了", len(e.notifier.sent), 1)
check("没记覆盖数", e.state.interim_covered(TODAY), 0)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
