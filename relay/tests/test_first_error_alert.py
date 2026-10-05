"""Each new kind of relay ERROR is pushed to the group once; a known-fixed kind
coming back is tagged; self-recovered faults (WARNING) go to the daily report
only; never more than MAX_PER_HOUR pushes an hour; shutdown-time ones never.

2026-09-17 21:21:28: 「AUTO-MAS 拉起后 45 秒内接口仍不通」 was one ERROR line that
nobody read; the 21:30 queue never ran and the first alarm came at 21:55.
2026-10-06, the user: new errors go straight to the group robot (「如果有新的错误，还是直接发到群机器人里面」);
old errors must not come back unnoticed (「我不希望之前遇到的老错误还要再犯」).
2026-09-08: an alarm flood rang the group for half an hour.
"""
import importlib
import json
import logging
import os
import sys
import time
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                  COS_SECRET_ID="", COS_SECRET_KEY="", COS_BUCKET="", COS_REGION="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import errwatch, known_fixed, texts  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402
from ark_relay import notify as notify_mod  # noqa: E402
from ark_relay.notify import route_of  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


def _wait(n, count, secs=2.0):
    t0 = time.monotonic()
    while len(n.sent) < count and time.monotonic() - t0 < secs:
        time.sleep(0.02)
    time.sleep(0.05)   # let a wrongly-sent extra one land too


ARK = logging.getLogger(errwatch.ARK)
lg = ARK.getChild("service")   # ark.service
eng = ARK.getChild("engine")
ban = ARK.getChild("banners")
han = ARK.getChild("handle")
for x in (lg, eng, ban, han):
    x.setLevel(logging.INFO)
TODAY = datetime.now(SERVER_TZ).strftime("%Y-%m-%d")


def install(n, d, **kw):
    kw.setdefault("known", {})
    return errwatch.install(n, kw.pop("down", lambda: False), state_dir=d, **kw)


def faults(d):
    return errwatch.day_faults(d, TODAY)


print("[一种新的 ERROR 报一次；同种换了数字不再报；不同种再报一条]")
A = TMP / "a"
n = _Notifier()
h = install(n, A)
lg.warning("这是警告，不报")
lg.info("这是普通信息，不报")
_wait(n, 1, 0.3)
check("WARNING/INFO 不报", n.sent, [])
lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 45)
_wait(n, 1)
check("第一条 ERROR 报了一条", len(n.sent), 1)
check("标题是 texts.RELAY_ERROR", n.sent and n.sent[0][0] == texts.RELAY_ERROR)
check("正文说出在哪一部分、原话有术语就说留在日志里", n.sent and "主程序" in n.sent[0][1]
      and "留在中继日志里" in n.sent[0][1])
check("是报警（alert=True）", n.sent and n.sent[0][2] is True)
lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 60)
_wait(n, 2, 0.4)
check("同种换数字不再报", len(n.sent), 1)
eng.error("处理运行记录失败: 2026-09-08/wuwa/OK-WW-05-35-44")
_wait(n, 2)
check("另一种 ERROR 再报一条（主线上一次开机只报第一条）", len(n.sent), 2)
eng.error("处理运行记录失败: 2026-08-26/wuwa/OK-WW-12-50-57")
_wait(n, 3, 0.4)
check("同种（换了运行编号）不再报", len(n.sent), 2)
ARK.removeHandler(h)
h = install(n, A)                          # a restart: same state dir
lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 30)
_wait(n, 3, 0.4)
check("重启后见过的种类仍不再报", len(n.sent), 2)
sig = errwatch.signature("ark.service", "AUTO-MAS 拉起后 45 秒内接口仍不通")
check("见过的种类和次数记在 errsigs.json",
      json.loads((A / "errsigs.json").read_text(encoding="utf-8"))[sig]["count"], 3)
ARK.removeHandler(h)

print("\n[自己处理过去的（WARNING）只进日报，不报群]")
B = TMP / "b"
n = _Notifier()
h = install(n, B)
ban.warning("B 站版本资讯第 2 张图没读出来，这次不再读后面的图")   # relay3.log:27790
ban.warning("B 站版本资讯第 5 张图没读出来，这次不再读后面的图")
try:
    raise ConnectionResetError("reset")
except ConnectionResetError:
    ban.warning("PRTS 接口取不到 %s，改读页面", "卡池一览", exc_info=True)
han.warning("🟡 MAA 理智不够（%s/%s），没打，不算失败", 12, 30)            # a run outcome, already in the report
lg.warning("鸣潮 3.7 版本活动日历读了 78 行，没找到日期")                    # no failure word: not a fault
_wait(n, 1, 0.5)
check("一条都没报群", n.sent, [])
rows = faults(B)
check("日报记下两种（读图没读出来两次算一种、改读页面一种）", [(r["where"], r["count"]) for r in rows],
      [("ark.banners", 2), ("ark.banners", 1)])
section = errwatch.daily_section(B, TODAY)
check("日报一段：标「中继自己处理过去了，没报群」", section.count("中继自己处理过去了，没报群"), 2)
check("日报一段：次数", "（2 次）" in section)
check("🟡 运行结果、没失败词的警告不进这一段", "理智" not in section and "活动日历" not in section)
check("日报一段是人话", texts.plain(section), [])
ARK.removeHandler(h)

print("\n[已报过群的 ERROR 再出现：日报写「以前报过群」]")
A2 = TMP / "a2"
A2.mkdir()
(A2 / "errsigs.json").write_text(json.dumps({sig: {"count": 1, "alarmed": True}}), encoding="utf-8")
n = _Notifier()
h = install(n, A2)                         # alarmed on an earlier day
lg.error("AUTO-MAS 拉起后 %.0f 秒内接口仍不通", 50)
_wait(n, 1, 0.4)
check("不报群", n.sent, [])
check("日报写出来", "以前报过群，这次只记在这里" in errwatch.daily_section(A2, TODAY))
check("同一天报过群的写「已报群」", "已报群" in errwatch.daily_section(A, TODAY))
ARK.removeHandler(h)

print("\n[已修好的毛病又出现：打上复发标记]")
check("登记表都写了修好的版本和说法", all(v.get("fixed_in") and v.get("what") for v in known_fixed.KNOWN.values()))
check("登记表的说法是人话", [texts.plain(v["what"]) for v in known_fixed.KNOWN.values()],
      [[] for _ in known_fixed.KNOWN])
C = TMP / "c"
n = _Notifier()
h = install(n, C, known=known_fixed.KNOWN, version=lambda: "20261005153900")
ban.warning("库街区官方资讯里没找到 %s 版本资讯帖", "3.7")      # relay3.log:27777, no failure word
ban.warning("库街区官方资讯里没找到 %s 版本资讯帖", "当期")
try:
    try:
        importlib.import_module("PIL_absent_for_test")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("No module named 'PIL'") from exc
except ModuleNotFoundError:
    ban.warning("官方图转 PNG 失败，原样交给系统 OCR", exc_info=True)   # relay3.log:27778-27785
_wait(n, 1, 0.5)
check("复发的是 WARNING（自己兜过去了）：不报群", n.sent, [])
rows = faults(C)
check("三条都认成登记过的复发", [r.get("fixed_in") for r in rows], ["20261005151027"] * 3)
check("日报写「复发：v… 修过的又出现了」",
      errwatch.daily_section(C, TODAY).count("复发：v20261005151027 修过的又出现了"), 3)
ARK.removeHandler(h)

KNOWN_ERR = {errwatch.signature("ark.engine", "处理运行记录失败: <path>"): {"fixed_in": "20261001000000",
                                                                       "what": "运行记录读到一半就处理"}}
D = TMP / "d"
D.mkdir()
sig_e = errwatch.signature("ark.engine", "处理运行记录失败: /x/y/z")
(D / "errsigs.json").write_text(json.dumps({sig_e: {"count": 5, "alarmed": True}}), encoding="utf-8")
n = _Notifier()
h = install(n, D, known=KNOWN_ERR, version=lambda: "20261005153900")
eng.error("处理运行记录失败: /x/y/z")
_wait(n, 1)
check("ERROR 复发：修之前报过群也再报一次", len(n.sent), 1)
check("复发有自己的标题，带修好的版本", n.sent and n.sent[0][0] == texts.relay_error_recurred("20261001000000"))
check("复发标题照样进群", route_of(texts.relay_error_recurred("20261001000000"), alert=True), "group")
check("复发正文说当时修的是什么", n.sent and "运行记录读到一半就处理" in n.sent[0][1])
eng.error("处理运行记录失败: /x/y/w")
_wait(n, 2, 0.4)
check("同一次修复的复发不再报", len(n.sent), 1)
ARK.removeHandler(h)
h = install(n, D, known=KNOWN_ERR, version=lambda: "20261005153900")
eng.error("处理运行记录失败: /x/y/v")
_wait(n, 2, 0.4)
check("重启后也不再报", len(n.sent), 1)
ARK.removeHandler(h)
newer = {k: dict(v, fixed_in="20261006000000") for k, v in KNOWN_ERR.items()}
h = install(n, D, known=newer, version=lambda: "20261006010000")
eng.error("处理运行记录失败: /x/y/u")
_wait(n, 2)
check("又修了一次之后再复发：再报一次", len(n.sent), 2)
ARK.removeHandler(h)
E = TMP / "e"
n = _Notifier()
h = install(n, E, known=newer, version=lambda: "20261005153900")   # running code older than the fix
eng.error("处理运行记录失败: /x/y/t")
_wait(n, 1)
check("运行的版本比修复还旧：不算复发，按新种类报", n.sent and n.sent[0][0], texts.RELAY_ERROR)
check("也不打复发标记", [r.get("fixed_in") for r in faults(E)], [None])
ARK.removeHandler(h)

print("\n[一小时最多报 3 条：多出来的进日报，下次出现时再报]")
F = TMP / "f"
clock = {"t": 1_000_000.0}
n = _Notifier()
h = errwatch.ErrorKindAlert(n, lambda: False, F, {}, None, clock=lambda: clock["t"])
ARK.addHandler(h)
for word in ("甲", "乙", "丙", "丁", "戊"):
    eng.error(f"{word}出了错")
    clock["t"] += 60
_wait(n, 3)
check("五种新 ERROR 只报了三条", len(n.sent), 3)
rows = {r["line"]: r for r in faults(F)}
check("后两种记着「没报群」", (rows["丁出了错"].get("held"), rows["戊出了错"].get("held")), (True, True))
check("日报写清楚", errwatch.daily_section(F, TODAY).count("一小时内新报错太多，没报群，下次再出现时报"), 2)
eng.error("丁出了错")
_wait(n, 4, 0.4)
check("一小时内再出现：还是不报", len(n.sent), 3)
clock["t"] += 3600
eng.error("丁出了错")
_wait(n, 4)
check("过了一小时再出现：补报", len(n.sent), 4)
check("补报的是它", n.sent[-1][1].count("丁出了错"), 1)
rows = {r["line"]: r for r in faults(F)}
check("日报改成「已报群」", (rows["丁出了错"].get("pushed"), rows["丁出了错"].get("held")), (True, None))
ARK.removeHandler(h)

print("\n[推送时自己打的 ERROR 不回到这里]")


class _LoudNotifier(_Notifier):
    def send(self, title, body, *, alert=False, daily=False):
        super().send(title, body, alert=alert)
        notify_mod.log.error("通知一条渠道都没送到：x ｜ 标题：%s", title)
        return ["x"]


n = _LoudNotifier()
h = install(n, TMP / "g")
lg.error("一种新错")
_wait(n, 2, 0.6)
check("推送里打的 ERROR 不再引出第二条", len(n.sent), 1)
ARK.removeHandler(h)

print("\n[关机令已发出之后的 ERROR 不报]")
REAL = "进程启动事件监听中断，改用 120 秒活性检查，5 秒后重订阅"
n2 = _Notifier()
h2 = install(n2, TMP / "h2", down=lambda: True)
lg.error(REAL)
_wait(n2, 1, 0.4)
check("关机中的 ERROR 不报", n2.sent, [])
check("也不记成见过（下次正常时照报）", (TMP / "h2" / "errsigs.json").exists(), False)
ARK.removeHandler(h2)

print("\n[手动 shutdown /s：中继自己没下过关机令，但服务收到了停止/关机控制 → 不报]")
# The real record, 2026-09-18 02:20 (the machine was being switched off by hand;
# the group got 「🩺 中继自己报错了（主程序）」 for it).
n4 = _Notifier()
h4 = install(n4, TMP / "h4")
errwatch.mark_stopping()                          # what SvcStop now does (Windows routes SERVICE_CONTROL_SHUTDOWN there)
lg.error(REAL)
_wait(n4, 1, 0.4)
check("服务已收到停止/关机控制 → 不报", n4.sent, [])
ARK.removeHandler(h4)
errwatch._stopping.clear()

print("\n[Windows 自己说正在关机（GetSystemMetrics）→ 不报]")
n5 = _Notifier()
h5 = install(n5, TMP / "h5")
orig_ssd = errwatch.system_shutting_down
errwatch.system_shutting_down = lambda: True
lg.error(REAL)
_wait(n5, 1, 0.4)
check("系统关机中 → 不报", n5.sent, [])
errwatch.system_shutting_down = orig_ssd
ARK.removeHandler(h5)

print("\n[平时同一条 ERROR 照报（不是关机就是真掉了）]")
n6 = _Notifier()
h6 = install(n6, TMP / "h6")
lg.error(REAL)
_wait(n6, 1)
check("不在关机就报", len(n6.sent), 1)
ARK.removeHandler(h6)

print("\n[探测函数自己坏了也不拦报警]")
n3 = _Notifier()
h3 = install(n3, TMP / "h3", down=lambda: 1 / 0)
lg.error("探测坏了也要报")
_wait(n3, 1)
check("照样报", len(n3.sent), 1)
ARK.removeHandler(h3)

print("\n[日报里有这一段（report._compose_daily）]")
from ark_relay import report  # noqa: E402
from ark_relay import engine as eng_mod  # noqa: E402
from ark_relay.config import Config  # noqa: E402
from ark_relay.core import State  # noqa: E402

# No network: the banner section and the report-writing model are stubbed, as in test_report_due.py.
report.plan = types.SimpleNamespace(next_plan=lambda d: "", activity_countdown=lambda d: "",
                                    schedule=lambda d: [])
report.banners = types.SimpleNamespace(
    collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
    read_image=None: ([], {}),
    image_reader=lambda state_dir: None,
    render=lambda rows, now, nxt, notes=None, trace=None, failed=None, leads=None: "",
    Trace=types.SimpleNamespace(new=lambda: None),
    save_trace=lambda state_dir, now, text, tr: None,
    opening_tomorrow=lambda now, nxt: [],
)
report.summary = types.SimpleNamespace(daily_report=lambda cfg, entries, plan="": "")
cfg = Config()
cfg.state_dir, cfg.history_dir, cfg.automas_dir = B, None, None


class _Src:
    def fetch(self, seen):
        return []


e = eng_mod.Engine(cfg, source=_Src(), state=State(B), notifier=_Notifier())
now = datetime.now(SERVER_TZ)
entry = {"run_id": f"{TODAY}/ark/MAA-09-00-00", "script": "MAA", "user": "ark", "started": now.isoformat(),
         "finished": now.isoformat(), "ok": True, "failed_tasks": [], "duration_known": True,
         "transitional": False, "raw": {"tasks_done": ["日常"]}}
_, body = e._compose_daily(TODAY, [entry])
check("日报带「中继自己记下的报错」", "中继自己记下的报错" in body)
check("日报带那条自己处理过去的", "中继自己处理过去了，没报群" in body)

print("\n[文案与路由]")
check("标题走群", route_of(texts.RELAY_ERROR, alert=True), "group")
check("原话是人话时照抄", "它说：日报没发出去" in texts.relay_error_body("ark.report", "日报没发出去", "10:47"))
check("正文是人话（两种样例）", [texts.plain(x) for x in (texts.relay_error_body("ark.service", "ConnectionRefusedError: [WinError 10061]", "21:21"), texts.relay_error_body("ark.report", "日报没发出去", "10:47"))], [[], []])
check("正文不再说「同一次开机只报这一条」", "同一次开机只报这一条" in texts.relay_error_body("ark.report", "x", ""), False)

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
