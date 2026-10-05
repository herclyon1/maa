"""What recovered by itself goes to the daily report only; what did not, to the group.

The user, 2026-10-06 05:07, on faults fixed by themselves: 「报错后自己好了的，只进日报、
不进群。」 (and that it had been so before: 「本来不就这样吗？」). Earlier that day, by
his order that every error be pushed
(「不论多少次什么错误都要发」), each of these had been put in the group; this pins
them back, each with the case that did not recover, which still rings every time:

* a held failure AUTO-MAS's own retry got past (「中途失败过，重试后成功」): nothing
  sent, the daily row says the retry got it; no later success -> the final alarm;
* a failure the relay's make-up got past (「失败过，补跑后走通了」): nothing sent, the
  daily report's make-up line says it; the make-up failed too -> 「没跑成」;
* a failure in an update's streak with a success after it (「更新时失败过，重跑后成功」):
  nothing sent, the daily rows are ↪️; no success after it -> the final alarm;
* an attempt AUTO-MAS recorded as a restart (「中途重启了一次」): nothing sent when it
  lands, it is held and the attempts after it decide - a success heals it (daily
  only), a failure after it is alarmed on, nothing after it and the final alarm
  names it, with what AUTO-MAS wrote;
* a push that went through on a later transport attempt (「推送传输失败（第 n/3
  次）」), or on Server酱's second address: one WARNING marked recovered, counted for
  the daily report's 「中继自己记下的报错」, not queued for the group; a send that
  reached nobody is still an ERROR that errwatch pushes.

MaaEnd's update restart after a done round and the gathering retry are pinned
where they live (test_maaend_update_after_done, test_collect_retry).
"""
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import core, errwatch, handle, makeup, notify, report, texts   # noqa: E402
from ark_relay import engine as eng_mod                                       # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord                     # noqa: E402
from ark_relay import machinecheck as _mc                     # noqa: E402
_mc.load()
_mc.CHECKS.clear()   # the alarms themselves are tested here; the machine checks in tests/test_mc_*.py
from ark_relay.core import State                                              # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def automas_dir() -> Path:
    """AUTO-MAS's config with one 早班 09:00 queue running all three scripts."""
    root = tmpdir()
    (root / "config").mkdir()
    paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
    sc = {"instances": [{"uid": f"s-{k}"} for k in paths], **{f"s-{k}": {"Info": {"Name": k, "Path": p}}
                                                            for k, p in paths.items()}}
    qc = {"instances": [{"uid": "q0"}],
          "q0": {"Info": {"Name": "早班", "TimeEnabled": True},
                 "SubConfigsInfo": {"TimeSet": {"instances": [], "t0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                    "QueueItem": {"instances": [], **{f"i{i}": {"Info": {"ScriptId": f"s-{k}"}}
                                                                      for i, k in enumerate(paths)}}}}}
    (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
    (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
    return root


AUTOMAS = automas_dir()
# Today (real clock): makeup.eligible and _flush_pending read today's date.
DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
D = f"{DAY:%Y-%m-%d}"
UPDATE = "游戏更新成功，即将重启任务"


def at(hh, mm=0):
    return DAY.replace(hour=hh, minute=mm)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []

    def went_to_group(self):
        return True


class Src:
    def fetch(self, seen):
        return []


def build():
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = AUTOMAS
    cfg.maa_dir = None
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._unfinished_queues = lambda now, entries: []
    e._deferred_update_busy = lambda: False
    e._verify_outcome = lambda r: None
    e._archive_maaend_evidence = lambda r: None
    e._maintenance_today = lambda game: False
    return e


def rec(script, started, ok=False, failed=None, raw=None, transitional=False):
    user = {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
    return RunRecord(run_id=f"{started:%Y-%m-%d}/{user}/{script}-{started:%H-%M-%S}", script=script, user=user,
                     started=started, finished=started + timedelta(minutes=20), ok=ok,
                     failed_tasks=list(failed if failed is not None else ([] if ok or transitional else ["日常"])),
                     raw=dict(raw or {}), transitional=transitional)


def restart(script, started):
    """An attempt AUTO-MAS recorded as a restart (collector._TRANSITIONAL)."""
    key = {"MAA": "maa_result", "MaaEnd": "maaend_result", "OK-WW": "general_result"}[script]
    return rec(script, started, raw={key: UPDATE if script == "OK-WW" else "未捕获到日志"}, transitional=True)


def alarms(e):
    return [t for t, _, a in e.notifier.sent if a]


def body_of(e, title):
    return next((b for t, b, a in e.notifier.sent if a and t == title), "")


def daily(e):
    return core.format_daily(D, e.state.read_ledger(D))


handle._ship_evidence = lambda eng, r: ""
handle._archive_okww_evidence = lambda eng, r: None
handle._weekly_gates = lambda eng, r: None
makeup._dispatch = lambda script: (True, "已开跑")
makeup._kill_game = lambda: None


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def said(self, *parts):
        return any(all(p in r.getMessage() for p in parts) for r in self.records)


LINES = Lines()
for _name in ("ark.handle", "ark.notify"):
    logging.getLogger(_name).addHandler(LINES)
    logging.getLogger(_name).setLevel(logging.DEBUG)


print("[AUTO-MAS 自己重试过去了：什么都不发，日报那一行说重试做成了]")
e = build()
handle._handle(e, rec("OK-WW", at(9, 10), failed=["日常"]))
handle._handle(e, rec("OK-WW", at(9, 40), ok=True, raw={"tasks_done": ["日常"]}))
e._flush_pending()
check("什么都没发（群、Server酱都没有）", e.notifier.sent, [])
check("放下了", (dict(e._pending), dict(e._recovered)), ({}, {}))
check("日志：自愈那句，只进日报", LINES.said(texts.self_healed("OK-WW"), "只进日报"))
title, body = daily(e)
check("日报那一行：后来在 10:00 那趟重试里做成了", "日常　后来在 10:00 那趟重试里做成了" in body)
check("日报标题不算鸣潮失败", "鸣潮失败" in title, False)
print("  …没有后来那次成功：照样进群")
e = build()
handle._handle(e, rec("OK-WW", at(9, 10), failed=["日常"]))
e._flush_pending()
check("最终失败进群", alarms(e), [texts.failed("OK-WW")])

print("\n[中继补跑走通了：什么都不发，日报的补跑那一行说失败过、补跑后走通了]")
e = build()
handle._handle(e, rec("MAA", at(9, 5), failed=["开始唤醒"]))
e._flush_pending()
makeup.maybe_run(e, at(10, 5))
handle._handle(e, rec("MAA", at(10, 6), ok=True))
e._flush_pending()
check("补跑记成走通", makeup.read_marker(e.cfg.state_dir, D)["MAA"]["result"], makeup.OK)
check("什么都没发", e.notifier.sent, [])
check("放下了", (dict(e._pending), dict(e._recovered)), ({}, {}))
check("日志：补跑走通，只进日报", LINES.said(texts.makeup_passed("明日方舟", "早班"), "只进日报"))
check("日报的补跑那一行", report.makeup_line(e.cfg.state_dir, D),
      "补跑：明日方舟 整个 MAA → 失败过，补跑后走通了（原来失败于：开始唤醒）")
check("日报那一行：后来在补跑里做成了", "后来在 10:26 那趟补跑里做成了" in daily(e)[1])
print("  …补跑也没成：进群")
e = build()
handle._handle(e, rec("MAA", at(9, 5), failed=["开始唤醒"]))
e._flush_pending()
makeup.maybe_run(e, at(10, 5))
handle._handle(e, rec("MAA", at(10, 6), failed=["开始唤醒"]))
e._flush_pending()
check("没跑成进群", alarms(e), [texts.unresolved("明日方舟", "早班")])

print("\n[更新那一串后面有一次成功：什么都不发，日报是 ↪️]")
e = build()
handle._handle(e, rec("OK-WW", at(9, 10), failed=["日常"]))
handle._handle(e, restart("OK-WW", at(9, 18)))
check("前面压着的失败还是它（重启不顶替它）", e._pending[("OK-WW", "wuwa")].started, at(9, 10))
handle._handle(e, rec("OK-WW", at(9, 28), ok=True))
e._flush_pending()
check("什么都没发", e.notifier.sent, [])
check("日志：更新时失败过，只进日报", LINES.said(texts.healed_after_update("OK-WW"), "只进日报"))
title, body = daily(e)
check("日报里这一串是更新，不算失败", ("鸣潮失败" in title, body.count("↪️ OK-WW"), body.count("更新后重跑")), (False, 2, 2))
print("  …那一串后面没有成功：照样进群，报的是前面那次失败")
e = build()
handle._handle(e, rec("OK-WW", at(9, 10), failed=["日常"]))
handle._handle(e, restart("OK-WW", at(9, 18)))
e._flush_pending()
check("最终失败进群", alarms(e), [texts.failed("OK-WW")])
check("…说的是 09:10 那次的日常", "· 失败于：日常" in body_of(e, texts.failed("OK-WW")))

print("\n[AUTO-MAS 记成重启的那一次：落地时不发，压着，后面那次定]")
e = build()
handle._handle(e, restart("OK-WW", at(9, 18)))
check("落地时什么都没发", e.notifier.sent, [])
check("压着", list(e._pending), [("OK-WW", "wuwa")])
check("日志：先压着", LINES.said("是中途重启", "先压着"))
handle._handle(e, rec("OK-WW", at(9, 28), ok=True))
e._flush_pending()
check("后面成功了：什么都没发", e.notifier.sent, [])
check("放下了", (dict(e._pending), dict(e._recovered)), ({}, {}))
check("日报里是 ↪️ 更新后重跑", ("↪️ OK-WW" in daily(e)[1], "更新后重跑" in daily(e)[1]), (True, True))
print("  …后面没有再跑：最终失败进群，写着 AUTO-MAS 记的什么")
e = build()
handle._handle(e, restart("OK-WW", at(9, 18)))
e._flush_pending()
check("最终失败进群", alarms(e), [texts.failed("OK-WW")])
got = body_of(e, texts.failed("OK-WW"))
check("…写着那次的时间和结果", f"09:18 开始的这一次，AUTO-MAS 记的结果是「{UPDATE}」" in got)
check("…写着之后没有再跑出记录", "这次之后没有再跑出一次记录" in got)
check("放下了", dict(e._pending), {})
print("  …后面那次失败了：报的是后面那次")
e = build()
handle._handle(e, restart("OK-WW", at(9, 18)))
handle._handle(e, rec("OK-WW", at(9, 20), failed=["周常乐园"]))
e._flush_pending()
check("一条最终失败进群", alarms(e), [texts.failed("OK-WW")])
got = body_of(e, texts.failed("OK-WW"))
check("…说的是 09:20 那次（周常乐园），不带重启那句", ("周常乐园" in got, "这次之后没有再跑出一次记录" in got), (True, False))
print("  …重启那条比后面成功的那条晚落地：已经好了，不压着、不发")
e = build()
handle._handle(e, rec("OK-WW", at(9, 28), ok=True))
handle._handle(e, restart("OK-WW", at(9, 18)))
e._flush_pending()
check("什么都没发", e.notifier.sent, [])
check("不压着", (dict(e._pending), dict(e._recovered)), ({}, {}))
check("日志：后面那次已经成功，只进日报", LINES.said("是中途重启", "已经成功", "只进日报"))
check("日报里是 ↪️ 更新后重跑", "↪️ OK-WW" in daily(e)[1])
print("  …终末地的空壳记录（未捕获到日志）也一样：落地不发，压着")
e = build()
handle._handle(e, restart("MaaEnd", at(10, 1)))
check("落地时什么都没发", e.notifier.sent, [])
check("压着", list(e._pending), [("MaaEnd", "endfield")])


print("\n[推送传输：后一次送到了 → 一条标「自己好了」的 WARNING，只进日报；全没送到 → 照样报]")


class Resp:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.data).encode("utf-8")


def fake_urlopen(script):
    """urlopen that, for each URL in turn, raises (an Exception in `script`) or answers (a dict)."""
    calls = []

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return Resp(step)
    urlopen.calls = calls
    return urlopen


class Refuses:
    """errwatch's notifier: the group refuses, so whatever it queues stays queued."""
    def send_group(self, title, body):
        return ["企业微信机器人：拒收"]

    def send(self, title, body, **kw):
        return ["拒收"]


def watch():
    sd = tmpdir()
    h = errwatch.ErrorKindAlert(Refuses(), state_dir=sd, known={}, retry=(3600.0,), fallback_after=1e9)
    logging.getLogger(errwatch.ARK).addHandler(h)
    LINES.records.clear()
    return h, sd


def unwatch(h):
    logging.getLogger(errwatch.ARK).removeHandler(h)
    h.close()


def warnings():
    return [r for r in LINES.records if r.levelno >= logging.WARNING]


real_urlopen, real_sleep = urllib.request.urlopen, notify.time.sleep
notify.time.sleep = lambda s: None
REQ = urllib.request.Request("https://push.example/send", data=b"{}")
try:
    h, sd = watch()
    urllib.request.urlopen = fake_urlopen([urllib.error.URLError("handshake timed out"), {"errcode": 0}])
    check("第二次送到了", notify._post(REQ), {"errcode": 0})
    check("失败的那一次是 INFO", [r.levelname for r in LINES.records if "推送传输失败（第 1/3 次）" in r.getMessage()],
          ["INFO"])
    check("送到时一条 WARNING，标着自己好了", [(r.getMessage().split(":")[0], getattr(r, errwatch.RECOVERED, False))
                                            for r in warnings()], [("推送传输失败 1 次，第 2 次送到了", True)])
    check("没排进推群的队", h.pending(), [])
    rows = errwatch.day_faults(sd, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
    check("日报「中继自己记下的报错」里有它，标自己好了", [(r.get("recovered"), r.get("level")) for r in rows],
          [(True, "WARNING")])
    unwatch(h)

    print("  …三次都没送到：_post 抛出去，调用方报 ERROR，errwatch 排进推群的队")
    h, sd = watch()
    urllib.request.urlopen = fake_urlopen([urllib.error.URLError("down")] * 3)
    try:
        notify._post(REQ)
        raised = False
    except urllib.error.URLError:
        raised = True
    check("抛出去了", raised)
    check("_post 自己没写「送到了」", any(getattr(r, errwatch.RECOVERED, False) for r in LINES.records), False)
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.wecom_bot_url = "https://bot.example/send"
    cfg.serverchan_key = ""
    cfg.wecom_corpid = ""
    n = notify.Notifier(cfg)
    urllib.request.urlopen = fake_urlopen([urllib.error.URLError("down")] * 3)
    check("一条渠道都没送到：返回错误", bool(n.send("❌ OK-WW 失败", "正文", alert=True)), True)
    check("…调用方的 ERROR 没标自己好了", [(r.levelname, getattr(r, errwatch.RECOVERED, False)) for r in warnings()],
          [("ERROR", False)])
    check("…排进了推群的队", len(h.pending()), 1)
    unwatch(h)

    print("  …Server酱 第一个地址没送到、第二个送到了：一条标自己好了的 WARNING")
    h, sd = watch()
    sc = notify.ServerChan(type("C", (), {"serverchan_key": "sctp123tabc"})())
    urllib.request.urlopen = fake_urlopen([urllib.error.URLError("down")] * 3 + [{"code": 0}])
    sc.send_text("📋 日报", "正文")
    check("两个地址都试了", len(urllib.request.urlopen.calls), 4)
    check("一条 WARNING，标着自己好了", [(r.getMessage().startswith("Server酱 前面的地址没送到"),
                                         getattr(r, errwatch.RECOVERED, False)) for r in warnings()], [(True, True)])
    check("没排进推群的队", h.pending(), [])
    unwatch(h)
finally:
    urllib.request.urlopen, notify.time.sleep = real_urlopen, real_sleep

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
