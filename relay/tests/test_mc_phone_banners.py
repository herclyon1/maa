"""Machine checks of the phone channel, the phone orders and the banner section.

The user, 2026-10-06 04:59: the machine has to confirm by itself, after a deploy,
what nobody had confirmed on it (ark_relay/machinechecks/phone_banners.py).
Each check here gets a realistic input - recorded fixtures, the real code path
that produces the evidence (the trace, the receipts, the queue file, the
relay's own WARNING lines through errwatch) - that PASSes, and a broken one that
FAILs and is pushed to the group. The wiring is driven through the real call
sites: banners.save_trace, boot_stages publish_state / run_phone_cmd / drain.
No network, no thread left running.
"""
import functools
import json
import logging
import os
import sys
import time
import types
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
              "win32con", "win32file", "servicemanager", "win32process",
              "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
              "win32com", "win32com.client"):
    sys.modules.setdefault(_name, _Stub(_name))

from _tmp import tmpdir  # noqa: E402

os.environ.update(ARK_STATE_DIR=str(tmpdir()), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

import boot_stages  # noqa: E402
import ark_relay.banners as _b  # noqa: E402
import ark_relay.commands as C  # noqa: E402
import ark_relay.desktop as _desktop_mod  # noqa: E402
from ark_relay import (alertlog, errwatch, machinecheck as mc, maintenance, modes, phone,  # noqa: E402
                       plan, queues, resources, skland, texts)
from ark_relay.config import SERVER_TZ  # noqa: E402
from ark_relay.desktop import Line  # noqa: E402

FX = Path(__file__).parent / "fixtures"
PASS, FAIL = mc.PASS, mc.FAIL
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


class N:
    """The relay's notifier as judge sees it."""

    def __init__(self):
        self.sent = []

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body, alert))
        return []

    def failed(self, cid):
        return [(t, b, a) for t, b, a in self.sent if t.startswith(f"{texts.MACHINECHECK_FAIL}：{cid} ")]


class Group:
    """errwatch's side of the notifier: the group robot, with the copy of every
    delivered group alarm (notify.Notifier._copy_alarm -> alertlog)."""
    channels = ["企业微信机器人"]

    def __init__(self, d):
        self.d, self.sent = d, []

    def send_group(self, title, body):
        self.sent.append((title, body))
        alertlog.AlertLog(self.d).copy(title, body)
        return []

    def send(self, title, body="", alert=False, **kw):
        return self.send_group(title, body)


class Watch:
    """errwatch on the "ark" logger for one state dir: the day's error kinds, its
    queue and the alarm copy come out exactly as on the machine."""

    def __init__(self, d):
        self.group = Group(d)
        self.h = errwatch.ErrorKindAlert(self.group, lambda: False, d, known={}, pace=0, retry=(0.05,))
        logging.getLogger(errwatch.ARK).addHandler(self.h)

    def settle(self):
        t0 = time.monotonic()
        while self.h.pending() and time.monotonic() - t0 < 5:
            time.sleep(0.02)
        time.sleep(0.05)

    def close(self):
        self.settle()
        logging.getLogger(errwatch.ARK).removeHandler(self.h)
        self.h.close()


def judged(d, event, ctx, n=None):
    """{id: Result} of the checks that judged."""
    return dict(mc.judge(d, event, ctx, notifier=n if n is not None else N()))


def status(v, cid):
    r = v.get(cid)
    return r.status if r else None


def ev(v, cid):
    r = v.get(cid)
    return r.evidence if r else ""


mc.load()
MINE = ("#2", "#3", "#8", "#9", "#10", "#15", "#16", "#23", "#39", "#40", "#41", "#45", "#50", "#56", "#58")

print("[登记：十五项，写的是人话]")
check("十五项都登记了", [c for c in MINE if c in mc.CHECKS], list(MINE))
check("每项写的是人话", {c: texts.plain(mc.CHECKS[c].what) for c in MINE if c in mc.CHECKS},
      {c: [] for c in MINE if c in mc.CHECKS})
check("卡池五项听卡池那一段", {c: mc.CHECKS[c].triggers for c in ("#2", "#3", "#8", "#9", "#58") if c in mc.CHECKS},
      {c: ("banners",) for c in ("#2", "#3", "#8", "#9", "#58") if c in mc.CHECKS})

saved_pause = _b._pause
_b._pause = lambda s: None

# ------------------------------------------------------------------ #2
print("\n[#2 鸣潮版本活动日历图：读出日期过，读图没结果不过（10-02 那次是「RecognizeAsync 参数错误」）]")
CAL = "https://aki-gm-resources-back.aki-game.com/notice/image/fYrvOmEkgCfEKFTy.png"
notice = {"activity": [{"id": "50868", "tabTitle": "3.7版本活动日历", "startTimeMs": "1790712000000",
                        "content": f'<p><img src="{CAL}" alt="" width="1080" height="2159"></p>'}]}
cal_lines = [Line(**o) for o in json.loads((FX / "ww-3.7-calendar-ocr.json").read_text(encoding="utf-8"))]
now = datetime(2026, 10, 6, 21, 40)
end = datetime(2026, 10, 22, 9, 59, 59)
d = tmpdir()
tr = _b.Trace.new()
_b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, lambda u: cal_lines if u == CAL else None, {}, tr)
n = N()
_b.save_trace(d, now, "🎴 卡池", tr, n)          # the real call site
row = mc.read(d).get("#2") or {}
check("经 save_trace 判了：过", row.get("status"), PASS)
check("依据是图上读出的日期和图址", ("2026-10-22 开" in str(row.get("evidence")), CAL in str(row.get("evidence"))),
      (True, True))
check("过了不推", n.sent, [])

d = tmpdir()
w = Watch(d)
_desktop_mod.log.warning(
    "桌面助手读图失败：ERR 使用“1”个参数调用“RecognizeAsync”时发生异常:“参数错误。”")
w.settle()
tr = _b.Trace.new()
_b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, lambda u: None, {}, tr)
n = N()
v = judged(d, "banners", {"trace": tr, "text": "", "now": now}, n)
w.close()
check("读图没结果：没过", status(v, "#2"), FAIL)
check("依据说读图没结果，带桌面读屏自己的原话", ("读图没有结果" in ev(v, "#2"), "参数错误" in ev(v, "#2")), (True, True))
check("没过推群", [a for _t, _b2, a in n.failed("#2")], [True])

# Another source gave the time (cross-check, notes=None): failing to read is not a
# fault; the trace writes 「另一来源已给出」 and check #2 keys on that.
d = tmpdir()
tr = _b.Trace.new()
_b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, lambda u: None, None, tr)
n = N()
v = judged(d, "banners", {"trace": tr, "text": "", "now": now}, n)
check("跨检读不出（另一来源已给）：#2 判过", status(v, "#2"), PASS)
check("……不推群", [a for _t, _b2, a in n.failed("#2")], [])
check("依据是「另一来源已给出」", "另一来源已给出" in str(ev(v, "#2")), True)

# ------------------------------------------------------------------ #3 and #58
print("\n[#3 哔哩哔哩那份：库街区没有这一帖时读出时间过，被风控挡住不过；#58 库街区没有那一帖不单独报错]")
fx = json.loads((FX / "ww-bili-feed-2026-10-05.json").read_text(encoding="utf-8"))
pages = [p["response"] for p in fx["pages"]]
empty, nav = fx["empty"]["response"], fx["nav"]["response"]
by_offset = {"": pages[0], pages[0]["data"]["offset"]: pages[1], pages[1]["data"]["offset"]: pages[2]}
IMG3 = "https://i0.hdslb.com/bfs/new_dyn/e1826ff7fe229d2f29d8a715a4ee4eee1955897084.jpg"
win = [Line(**o) for o in json.loads((FX / "ww-3.7-news-4-winocr.json").read_text(encoding="utf-8"))]


def bili(feed):
    def get(url, cookie):
        if "finger/spi" in url:
            return {"code": 0, "data": {"b_3": "B3", "b_4": "B4=="}}
        if "/nav" in url:
            return nav
        import urllib.parse  # noqa: PLC0415
        return feed(dict(urllib.parse.parse_qsl(url.split("?", 1)[1], keep_blank_values=True))["offset"])
    return get


def no_kuro_post(path, payload):
    return {"data": {"list": []}}          # the list reads fine, the post is not in it


feb = datetime(2026, 10, 5, 12, 0)
d = tmpdir()
tr = _b.Trace.new()
got = _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", feb, lambda u: win if u == IMG3 else [], tr,
                           no_kuro_post, bili(lambda off: by_offset[off]))
check("真实三页里找到那一帖、读出时间", got, (datetime(2026, 10, 22, 10, 0), datetime(2026, 11, 11, 11, 59)))
n = N()
v = judged(d, "banners", {"trace": tr, "text": "", "now": feb}, n)
check("#3 过", status(v, "#3"), PASS)
check("#3 依据：两扇门各自的结果", ("库街区：没有这一帖" in ev(v, "#3"), "哔哩哔哩：给出了「余心所向九死未悔」" in ev(v, "#3")),
      (True, True))
check("#58 过：库街区没有这一帖只记日志", (status(v, "#58"), "只记了日志" in ev(v, "#58")), (PASS, True))
check("过了不推", n.sent, [])

d = tmpdir()
tr = _b.Trace.new()
_b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", feb, lambda u: [], tr, no_kuro_post, bili(lambda off: empty))
n = N()
v = judged(d, "banners", {"trace": tr, "text": "", "now": feb}, n)
check("#3 一直空（风控）：没过", status(v, "#3"), FAIL)
check("#3 依据带原始形状", ("BiliFeedProblem" in ev(v, "#3"), "<0 items>" in ev(v, "#3")), (True, True))
check("#3 没过推群", len(n.failed("#3")), 1)

events = json.loads((FX / "ww-news-events.json").read_text(encoding="utf-8"))["data"]["list"]
post = json.loads((FX / "ww-3.7-news-post.json").read_text(encoding="utf-8"))
lines3 = [Line(**o) for o in json.loads((FX / "ww-3.7-news-3-ocr.json").read_text(encoding="utf-8"))]
KURO3 = "https://prod-alicdn-community.kurobbs.com/forum/539302b44e6e4c118735142822df9fe120260921.jpg"
d = tmpdir()
tr = _b.Trace.new()
_b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", datetime(2026, 10, 1, 2, 30),
                     lambda u: lines3 if u == KURO3 else [], tr,
                     lambda p, payload: {"data": {"list": events}} if "findEventList" in p else post,
                     bili(lambda off: by_offset[off]))
v = judged(d, "banners", {"trace": tr, "text": "", "now": feb})
check("库街区给出了：#3 不用判，#58 过（库街区找到了这一帖）",
      (status(v, "#3"), status(v, "#58"), "找到了这一帖" in ev(v, "#58")), (None, PASS, True))

d = tmpdir()
w = Watch(d)
tr = _b.Trace.new()
_b.log.warning("库街区官方资讯里没找到 3.7 版本资讯帖")     # the 10-05 21:47 line
_b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", feb, lambda u: win if u == IMG3 else [], tr,
                     no_kuro_post, bili(lambda off: by_offset[off]))
w.settle()
n = N()
v = judged(d, "banners", {"trace": tr, "text": "", "now": feb}, n)
w.close()
check("#58 那句又成了报错（旧代码）：没过", (status(v, "#58"), "旧报错又出现了" in ev(v, "#58")), (FAIL, True))
check("#58 没过推群", len(n.failed("#58")), 1)

# ------------------------------------------------------------------ #8
print("\n[#8 明日方舟下期「官方通讯」一行：该出就出，过期就撤，取不到不过]")
page = (FX / "prts_limited_page.html").read_text(encoding="utf-8")


# The official site's two endpoints (banners.ak_news_pages / ak_post_text): the
# NEWS tab holds newsletter #69 (09-25 16:00 +8), the ACTIVITY tab nothing.
NEWS = {"NEWS": [{"cid": "7366", "title": "《明日方舟》制作组通讯#69期", "displayTime": 1790326800}]}
COMM = ("<p>●SideStory「昨日海」限时活动将于10月上旬开启，该活动除包含全新活动关卡与剧情外，"
        "新干员和新时装以及相关主题家具也将伴随本次活动登场及上架。</p>")


def ak_site(url):
    if url.startswith("https://ak.hypergryph.com/api/news?"):
        cat = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["category"][0]
        return json.dumps({"code": 0, "data": {"list": NEWS.get(cat, []), "end": True}}, ensure_ascii=False)
    if url == _b._AK_POST.format(cid="7366"):
        return json.dumps({"code": 0, "data": {"data": COMM}}, ensure_ascii=False)
    return None


def ak_section(now, *, news_ok=True, with_leads=True):
    """The Arknights block as report._compose_daily builds it, against recorded pages."""
    real_json, real_text = _b._json, _b._text

    def no_api(url, *a, **k):
        raise OSError("503 Backend fetch failed")

    def text(url, *a, **k):
        if url.startswith(_b._PRTS_PAGE):
            return page
        got = ak_site(url) if news_ok else None
        if got is not None:
            return got
        raise OSError("offline")
    _b._json, _b._text = no_api, text
    cache = dict(_b._rarity_cache)
    try:
        tr, leads = _b.Trace.new(), {}
        rows, nxt = _b._arknights(now, trace=tr, leads=leads)
        out = _b.render(rows, now, {"明日方舟": nxt} if nxt else {}, {}, tr, [], leads if with_leads else {})
    finally:
        _b._json, _b._text = real_json, real_text
        _b._rarity_cache.clear()
        _b._rarity_cache.update(cache)
    return tr, out


oct6 = datetime(2026, 10, 6, 21, 40)
d = tmpdir()
tr, out = ak_section(oct6)
n = N()
_b.save_trace(d, oct6, out, tr, n)
row = mc.read(d).get("#8") or {}
check("通讯说 10 月上旬有新干员、日报写了：过", row.get("status"), PASS)
check("依据是日报那一行", "昨日海 · 10 月上旬 · 官方通讯" in str(row.get("evidence")), True)
d = tmpdir()
tr, out = ak_section(oct6, with_leads=False)
n = N()
v = judged(d, "banners", {"trace": tr, "text": out, "now": oct6}, n)
check("通讯给了、日报没写：没过", (status(v, "#8"), "官方未公告" in ev(v, "#8")), (FAIL, True))
check("没过推群", len(n.failed("#8")), 1)
d = tmpdir()
tr, out = ak_section(datetime(2026, 10, 11, 21, 40))
v = judged(d, "banners", {"trace": tr, "text": out, "now": datetime(2026, 10, 11, 21, 40)})
check("上旬过了、日报撤了这一行：过", (status(v, "#8"), "上旬已过" in ev(v, "#8"), "官方通讯" in out), (PASS, True, False))
d = tmpdir()
tr, out = ak_section(oct6, news_ok=False)
v = judged(d, "banners", {"trace": tr, "text": out, "now": oct6})
check("官网取不到：没过，带原因", (status(v, "#8"), "OSError: offline" in ev(v, "#8")), (FAIL, True))

# ------------------------------------------------------------------ #9
print("\n[#9 「明天开新卡池」不带没有名字的（09-29 那条：终末地 09-30 11:59，没有名字）]")
evening = datetime(2026, 9, 29, 21, 30)
nxt = {"终末地": (datetime(2026, 9, 30, 11, 59, 59), ""), "鸣潮": (datetime(2026, 9, 30, 11, 0), "景燃「身赴三途」")}
d = tmpdir()
tr = _b.Trace.new()
out = _b.render([], evening, nxt, {}, tr)
v = judged(d, "banners", {"trace": tr, "text": out, "now": evening})
check("没名字的没进群播报：过", status(v, "#9"), PASS)
check("依据：哪一条没名字、群里播的是什么", ("终末地 09-30 11:59" in ev(v, "#9"), "🎴 明天开新卡池：鸣潮" in ev(v, "#9")),
      (True, True))
real_opening = _b.opening_tomorrow


def opening_before_0929(now, nxt):          # 30eb8b41's parent: dates only, no name filter
    day = (now + timedelta(days=1)).date()
    return sorted(((g, w, who) for g, (w, who) in nxt.items() if w is not None and w.date() == day),
                  key=lambda x: x[1])


_b.opening_tomorrow = opening_before_0929
try:
    n = N()
    v = judged(tmpdir(), "banners", {"trace": tr, "text": out, "now": evening}, n)
finally:
    _b.opening_tomorrow = real_opening
check("退回 09-29 前的写法：没过", (status(v, "#9"), "进了群播报" in ev(v, "#9")), (FAIL, True))
check("没过推群", len(n.failed("#9")), 1)
v = judged(tmpdir(), "banners", {"trace": _b.Trace.new(), "text": "", "now": evening})
check("没有没名字的：不判", status(v, "#9"), None)

# ------------------------------------------------------------------ #10
print("\n[#10 森空岛会话交到手机，终末地体力那几项的名字认得出]")
saved_sk = (skland.get_did, skland.login, skland.refresh, skland.bindings, skland.endfield_card)


class Cred:
    cred, token = "c-secret", "t-secret"


skland.get_did, skland.login, skland.refresh = (lambda: "Bdev"), (lambda tok, did="": Cred()), (lambda c: c)
skland.bindings = lambda c: [
    {"appCode": "endfield", "bindingList": [{"uid": "247481631", "roles": [{"roleId": "1234567890", "serverId": "1"}]}]},
    {"appCode": "arknights", "bindingList": [{"uid": "19237299"}]}]
# The 09-15 03:45 card/detail sample quoted in web/stamina.js.
DUNGEON = {"curStamina": "179", "maxTs": "1789490362", "maxStamina": "360"}
asked = []
skland.endfield_card = lambda cred, role="", server="": (asked.append((role, server)),
                                                         {"detail": {"dungeon": dict(DUNGEON)}})[1]
try:
    resources._session["sk"] = None
    sk = resources.skland_session(types.SimpleNamespace(skland_token="tok"))
    check("体力是拿同一个会话、同一个角色读的", asked, [("1234567890", "1")])
    d = tmpdir()
    n = N()
    v = judged(d, "phone_state", {"state": {"密钥": {"sk": sk}}, "why": "开机"}, n)
    check("会话齐、体力三项在：过", status(v, "#10"), PASS)
    check("依据有体力读数", "curStamina=179 maxStamina=360 maxTs=1789490362" in ev(v, "#10"), True)
    check("依据里没有凭据", ("c-secret" in ev(v, "#10"), "t-secret" in ev(v, "#10")), (False, False))
    check("关机前那份不再判", status(judged(d, "phone_state", {"state": {"密钥": {"sk": sk}}, "why": "关机前"}), "#10"), None)
    skland.endfield_card = lambda cred, role="", server="": {"detail": {"dungeon": {"stamina": 179, "staminaMax": 360}}}
    resources._session["sk"] = None
    sk = resources.skland_session(types.SimpleNamespace(skland_token="tok"))
    n = N()
    v = judged(tmpdir(), "phone_state", {"state": {"密钥": {"sk": sk}}, "why": "开机"}, n)
    check("森空岛改了名字：没过，列出给的是什么", (status(v, "#10"), "staminaMax" in ev(v, "#10")), (FAIL, True))
    check("没过推群", len(n.failed("#10")), 1)
    v = judged(tmpdir(), "phone_state", {"state": {"密钥": {"sk": {"错误": "没配森空岛 token"}}}, "why": "开机"})
    check("会话没给出去：没过", (status(v, "#10"), "没配森空岛 token" in ev(v, "#10")), (FAIL, True))
finally:
    skland.get_did, skland.login, skland.refresh, skland.bindings, skland.endfield_card = saved_sk
    resources._session["sk"] = None

# ------------------------------------------------------------------ #15
print("\n[#15 跳过队列的回执：成功写「调度程序已确认」，失败撤掉并给红回执]")
saved_q = (plan.schedule, queues.apply)
plan.schedule = lambda automas_dir: [{"name": "晚班", "times": ["21:30"]}]


def engage(answer):
    d = tmpdir()
    queues.apply = lambda automas_dir, name, enabled=None, scripts=None: answer(name)
    today = datetime.now(tz=SERVER_TZ)
    modes.add_day_queue(d, today.strftime("%Y-%m-%d"), "晚班")
    modes.process_skip(d, tmpdir(), today)
    return d, {"relay": {"最近指令": modes.receipts(d), "今天跳过队列": modes.skipped_today_all(d)}}


try:
    d, state = engage(lambda name: (True, f"队列「{name}」：定时关闭（调度程序已确认）"))
    n = N()
    v = judged(d, "phone_state", {"state": state, "why": "跳过队列"}, n)
    check("跳过生效，回执带「调度程序已确认」：过", status(v, "#15"), PASS)
    check("同一张回执下一份状态不再判", status(judged(d, "phone_state", {"state": state, "why": "手机请求"}), "#15"), None)
    d, state = engage(lambda name: (False, f"队列「{name}」定时关闭失败：调度程序报错（timed out）"))
    v = judged(d, "phone_state", {"state": state, "why": "跳过队列"})
    check("跳过没成：红回执、手机上不再显示跳过：过", (status(v, "#15"), "今天跳过的队列：无" in ev(v, "#15")), (PASS, True))
    broken = dict(state["relay"], 今天跳过队列=["晚班"])          # the pre-09-30 shape: the flag stayed
    n = N()
    v = judged(tmpdir(), "phone_state", {"state": {"relay": broken}, "why": "跳过队列"}, n)
    check("红回执但还挂着跳过：没过", status(v, "#15"), FAIL)
    check("没过推群", len(n.failed("#15")), 1)
    d, state = engage(lambda name: (True, f"队列「{name}」：定时关闭（备份 QueueConfig.bak-20261006-212000.json）"))
    v = judged(d, "phone_state", {"state": state, "why": "跳过队列"})
    check("成功却没有调度程序确认（改文件那条路）：没过", status(v, "#15"), FAIL)
finally:
    plan.schedule, queues.apply = saved_q

# ------------------------------------------------------------------ the phone orders (#16, #23)


class Eng:
    def __init__(self, busy):
        self.busy = busy

    def scripts_running(self):
        return self.busy


class Log:
    def __init__(self):
        self.lines = []

    def _rec(self, fmt, *a, **k):
        self.lines.append(fmt % a if a else fmt)

    info = warning = debug = _rec

    def exception(self, fmt, *a, **k):
        self.lines.append("EXC " + (fmt % a if a else fmt))


class HB:
    def watch(self):
        pass


def order(action, mid, sent=None, **kw):
    body = {"action": action, "confirmed": True, **kw}
    body["_meta"] = {"sent": int(time.time()) if sent is None else sent,
                     "ntfy_time": int(time.time()), "ntfy_id": mid, "via": "live"}
    return body


def make(engine, d, n):
    return boot_stages._make_phone_cmd(engine, n, Log(), HB(), phone.StatePusher(lambda why: True), d)


print("\n[#16 红按钮：游戏、脚本和调度程序里的任务都没了才回「已停一切」（经 run_phone_cmd）]")
real_estop = C.estop
saved_e = (C._estop_stop_via_mas, C._estop_kill, C._estop_alive, C._estop_live_tasks)


def rig(alive_rounds, task_rounds):
    alive_rounds, task_rounds = list(alive_rounds), list(task_rounds)
    C._estop_stop_via_mas = lambda: ["晚班"]
    C._estop_kill = lambda: None
    C._estop_alive = lambda: alive_rounds.pop(0) if alive_rounds else []
    C._estop_live_tasks = lambda: task_rounds.pop(0) if task_rounds else []
    C.estop = functools.partial(real_estop, sleep=lambda s: None)


try:
    rig([[]], [[]])
    d, n = tmpdir(), N()
    make(Eng(True), d, n)(order("estop", "e1"))
    row = mc.read(d).get("#16") or {}
    check("都没了才回已停一切：过", row.get("status"), PASS)
    check("依据是最后一轮看到的", "游戏和脚本 一个都没有" in str(row.get("evidence")), True)
    rig([["MaaEnd.exe"], ["MaaEnd.exe"]], [[], []])
    d, n = tmpdir(), N()
    make(Eng(True), d, n)(order("estop", "e2"))
    row = mc.read(d).get("#16") or {}
    check("没停干净就没说已停一切：过", (row.get("status"), "MaaEnd.exe" in str(row.get("evidence"))), (PASS, True))

    def estop_before_0930(sleep=None, state_dir=None):    # processes only, AUTO-MAS's task list not read
        C.ESTOP_LAST.clear()
        C.ESTOP_LAST.update(alive=[], live=[("7f3c", "终末地 · 日常")], rounds=1)
        return True, "已停一切：晚班；脚本和游戏都确认没了"
    C.estop = estop_before_0930
    d, n = tmpdir(), N()
    make(Eng(True), d, n)(order("estop", "e3"))
    check("调度程序里还有任务却回了已停一切：没过", (mc.read(d).get("#16") or {}).get("status"), FAIL)
    check("没过推群", len(n.failed("#16")), 1)
    rig([[]], [None, None])
    d, n = tmpdir(), N()
    make(Eng(True), d, n)(order("estop", "e4"))
    check("问不到调度程序：没过", "问不到" in str((mc.read(d).get("#16") or {}).get("evidence")), True)
finally:
    C.estop = real_estop
    C._estop_stop_via_mas, C._estop_kill, C._estop_alive, C._estop_live_tasks = saved_e

print("\n[#23 跑着时按的手机指令先进 phone-queue.json，跑完照样执行]")
real_apply = C.apply_command
C.apply_command = lambda body: (True, f"刷取关卡：{body.get('value')}")
try:
    eng, d, n = Eng(True), tmpdir(), N()
    fn = make(eng, d, n)
    fn(order("set_config", "q1", value="1-7"))
    check("排上了，还没判", ("#23" in mc.read(d), len(phone.CmdQueue(d))), (False, 1))
    eng.busy = False
    fn.drain()
    row = mc.read(d).get("#23") or {}
    check("跑完执行了：过", row.get("status"), PASS)
    check("依据：排进文件、跑完执行、结果", ("phone-queue.json" in str(row.get("evidence")),
                                       "跑完后执行，改成了" in str(row.get("evidence"))), (True, True))
    eng, d, n = Eng(True), tmpdir(), N()
    fn = make(eng, d, n)
    fn(order("set_config", "q2", sent=int(time.time()) - phone.MAX_AGE - 60, value="TO-5"))
    eng.busy = False
    fn.drain()
    check("排到过期都没执行：没过", (mc.read(d).get("#23") or {}).get("status"), FAIL)
    check("没过推群", len(n.failed("#23")), 1)
    real_add = phone.CmdQueue.add
    phone.CmdQueue.add = lambda self, body, now=None: phone.QUEUED      # says queued, writes nothing
    try:
        eng, d, n = Eng(True), tmpdir(), N()
        make(eng, d, n)(order("set_config", "q3", value="1-7"))
    finally:
        phone.CmdQueue.add = real_add
    check("说排了却不在文件里：没过", (mc.read(d).get("#23") or {}).get("status"), FAIL)
finally:
    C.apply_command = real_apply

# ------------------------------------------------------------------ #39 through publish_state


class FakeBox:
    """The mailbox as _start_phone_channel uses it; `ok` decides each publish."""
    ok = [True]

    def __init__(self, topic, pin, state_dir, cos=None):
        self.topic, self.cos, self.enabled = topic, cos, True
        self.quota = phone.Quota(state_dir)
        self.last_error, self.last_route = "", ""

    def publish(self, body):
        good = FakeBox.ok.pop(0) if FakeBox.ok else True
        self.last_route = "腾讯云" if good else ""
        self.last_error = "" if good else "腾讯云 COS 没存上（回 403），ntfy 也没发出去（ntfy 回 502（试了 2 次））"
        return good

    def report(self):
        return {"connected": True, "down_since": None, "drops": [], "backlog_missed": False,
                "backlog_why": "", "backlog_late": None}

    def fetch(self):
        return []

    def listen(self, on_cmd, stop, **kw):
        return None


class FakeHb:
    def __init__(self, *a, **k):
        pass

    def loop(self, stop):
        return None

    def cos_report(self):
        return {"cos": False}


STATE = [{"at": 1}]       # what the faked state_payload hands out


def channel(d, n, results, state=None):
    """_start_phone_channel with the fakes; the push_state it returns."""
    FakeBox.ok = list(results)
    STATE[0] = dict(state or {"at": 1})
    cfg = types.SimpleNamespace(phone_topic="topic-abc", phone_pin="8964", state_dir=d,
                                cos_secret_id="", cos_secret_key="", cos_bucket="", cos_region="")
    return boot_stages._start_phone_channel(types.SimpleNamespace(stop_event=None), cfg,
                                            types.SimpleNamespace(scripts_running=lambda: False),
                                            n, boot_stages.log)


saved_channel = (phone.Mailbox, phone.Heartbeat, phone.state_payload, boot_stages.ensure_automas)
phone.Mailbox, phone.Heartbeat = FakeBox, FakeHb
phone.state_payload = lambda cfg, state_dir: dict(STATE[0])
boot_stages.ensure_automas = lambda *a, **k: True


print("\n[#39 每一份状态都送到了手机（经 publish_state，关机前那份时判）]")
d, n = tmpdir(), N()
w = Watch(d)
push = channel(d, n, [True, True, True])
push("手机请求")
check("开机、手机请求都不判 #39", "#39" in mc.read(d), False)
saved_channel[0]._carried_by_ntfy("回 403")         # COS refused one, ntfy carried it: got over by itself
w.settle()
push("关机前")
w.close()
row = mc.read(d).get("#39") or {}
check("三份都送到：过", row.get("status"), PASS)
check("依据：次数、走哪条、自己好了的那条只进日报",
      ("上报状态 3 次，送到 3 次（腾讯云 3）" in str(row.get("evidence")), "只进了日报" in str(row.get("evidence"))),
      (True, True))
push("关机前")                                      # the machine stayed on: the next shift starts afresh
check("下一班重新数", "上报状态 1 次，送到 1 次" in str((mc.read(d).get("#39") or {}).get("evidence")), True)
d, n = tmpdir(), N()
w = Watch(d)
push = channel(d, n, [True, False])
push("关机前")
w.close()
row = mc.read(d).get("#39") or {}
check("关机前那份没送到：没过", row.get("status"), FAIL)
check("依据带原因", "ntfy 回 502" in str(row.get("evidence")), True)
check("没过推群（走 notifier，带 alert）", [a for _t, _b2, a in n.failed("#39")], [True])
d, n = tmpdir(), N()
w = Watch(d)
push = channel(d, n, [True, True])
phone.log.warning("状态没能发到信箱：ntfy 回 429 42908 daily message quota reached"
                                       "（本机今天记了 0 条，ntfy 每天 250 条，北京时间 8 点清零）")
w.settle()
push("关机前")
w.close()
check("旧报错又出现（旧代码在跑）：没过", "旧报错又出现了" in str((mc.read(d).get("#39") or {}).get("evidence")), True)

print("\n[停止前的那份：没过的走 errwatch 进群，不在停服务的 30 秒里等网络]")
d, n = tmpdir(), N()
w = Watch(d)
bad_receipt = {"relay": {"最近指令": [{"at": "10-06 21:31", "action": "skip_today", "ok": True,
                                     "text": "今天（2026-10-06）跳过队列「晚班」：队列「晚班」：定时关闭（备份 Q.json），过后自动恢复"}],
                         "今天跳过队列": ["晚班"]}}
push = channel(d, n, [True, True], state=bad_receipt)     # 开机 judges #15 with n; reset below
n.sent.clear()
(Path(d) / mc.STATE_FILE).unlink(missing_ok=True)
push("停止前")
w.close()
check("没用 notifier", n.sent, [])
check("errwatch 把 #15 推进了群，标题和依据都在",
      [t for t, b in w.group.sent if t.startswith(f"{texts.MACHINECHECK_FAIL}：#15 ") and "备份 Q.json" in b] != [], True)
phone.Mailbox, phone.Heartbeat, phone.state_payload, boot_stages.ensure_automas = saved_channel

# ------------------------------------------------------------------ #40
print("\n[#40 手机信箱每天 250 条的额度中继没用完]")
d = tmpdir()
q = phone.Quota(d)
q.add("hb", 150)
q.add("state", 40)
q.add("bye", 2)


def quota_ctx(q, since):
    return {"why": "关机前", "tally": {"since": since},
            "quota": {"day": q.day(), "total": q.total(), "own": q.own(), "full": q.full(), "raw": q.read()}}


t0 = time.time() - 5
v = judged(d, "phone_state", quota_ctx(q, t0))
check("192 条，没用完：过", (status(v, "#40"), "已用 192 条" in ev(v, "#40")), (PASS, True))
w = Watch(d)
q.mark_full("ntfy 回 429 42908 daily message quota reached")
w.settle()
n = N()
v = judged(d, "phone_state", quota_ctx(q, t0), n)
w.close()
check("用完了：没过", (status(v, "#40"), "已经拒收" in ev(v, "#40")), (FAIL, True))
check("没过推群", len(n.failed("#40")), 1)

# ------------------------------------------------------------------ #41
print("\n[#41 开机没读到的手机指令，连上后补读到]")
d = tmpdir()
w = Watch(d)
t0 = time.time() - 5
box = phone.Mailbox("topic-x", "8964", d)


def timed_out(since="24h"):
    raise TimeoutError("timed out")


box._read_backlog = timed_out
check("开机读信箱超时：先不丢", (box.fetch(), box.backlog_missed), ([], True))
box._read_backlog = lambda since="24h": [{"action": "skip_shutdown", "on": True}]
got_cmds = []
box._late_backlog(got_cmds.append, None)
w.settle()
v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": box.report()})
w.close()
check("补读到了：过", status(v, "#41"), PASS)
check("依据：开机那次的原因、补读到几条、只进日报",
      ("TimeoutError: timed out" in ev(v, "#41"), "补读到 1 条" in ev(v, "#41"), "只进了日报" in ev(v, "#41")),
      (True, True, True))
check("那条指令照样交出去了", got_cmds, [{"action": "skip_shutdown", "on": True}])
d = tmpdir()
box = phone.Mailbox("topic-x", "8964", d)
box._read_backlog = timed_out
box.fetch()
n = N()
v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": box.report()}, n)
check("到关机前都没补读到：没过", (status(v, "#41"), "没补读到" in ev(v, "#41")), (FAIL, True))
check("没过推群", len(n.failed("#41")), 1)
d = tmpdir()
v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0},
                              "mailbox": phone.Mailbox("topic-x", "8964", d).report()})
check("开机就读到了：不判", status(v, "#41"), None)

# ------------------------------------------------------------------ #45
print("\n[#45 手机通道断了自己连上（10054 被对方断开，连上后补收）]")
d = tmpdir()
w = Watch(d)
t0 = time.time() - 5
done = {"stop": False, "n": 0}


class Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        done["stop"] = True
        return False

    def __iter__(self):
        return iter([json.dumps({"event": "keepalive", "time": int(time.time())}).encode()])

    def close(self):
        pass


def flaky_urlopen(req, timeout=None):
    done["n"] += 1
    if done["n"] == 1:
        raise urllib.error.URLError(ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。"))
    return Resp()


real_urlopen = phone.urllib.request.urlopen
phone.urllib.request.urlopen = flaky_urlopen
try:
    box = phone.Mailbox("topic-x", "8964", d)
    box._sleep = lambda s: None
    box.listen(lambda body: None, lambda: done["stop"])
finally:
    phone.urllib.request.urlopen = real_urlopen
w.settle()
v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": box.report()})
w.close()
check("断了一次自己连上：过", status(v, "#45"), PASS)
check("依据：哪一次、什么原因、只进日报", ("10054" in ev(v, "#45"), "只进了日报" in ev(v, "#45")), (True, True))
d = tmpdir()
w = Watch(d)
phone.log.warning("手机通道断了，5 秒后重连")         # the 10-06 sweep's line
w.settle()
n = N()
v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": box.report()}, n)
w.close()
check("旧报错又出现：没过", (status(v, "#45"), "旧报错又出现了" in ev(v, "#45")), (FAIL, True))
check("没过推群", len(n.failed("#45")), 1)
down = dict(box.report(), connected=False, down_since=time.time() - 900)
v = judged(tmpdir(), "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": down})
check("关机前已经断了 15 分钟：没过", (status(v, "#45"), "已经断了 15 分钟" in ev(v, "#45")), (FAIL, True))

# ------------------------------------------------------------------ #50
print("\n[#50 三家停服维护公告：缓存一小时，第一次没响应重试取到只进日报]")
saved_m = (maintenance.SOURCES, maintenance._sleep, maintenance.urllib.request.urlopen)
maintenance._CACHE.clear()
maintenance._STATS.clear()
tries = {"n": 0}


class Page:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return "<html>news</html>".encode()


def slow_once(req, timeout=None):
    tries["n"] += 1
    if tries["n"] == 1:
        raise TimeoutError("timed out")
    return Page()


d = tmpdir()
w = Watch(d)
t0 = time.time() - 5
maintenance._sleep = lambda s: None
maintenance.urllib.request.urlopen = slow_once
maintenance.SOURCES = {"明日方舟": lambda now: (maintenance._get("https://ak.hypergryph.com/news"), None)[1],
                       "终末地": lambda now: None, "鸣潮": lambda now: None}
try:
    maintenance.today()
    maintenance.today()                          # the next state push: served from the cache
    w.settle()
    v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0, "n": 2}, "maintenance": maintenance.stats()})
    check("两次上报只真取了一次、重试取到：过", status(v, "#50"), PASS)
    check("依据：真去取的次数、只进日报", ("明日方舟 1 次" in ev(v, "#50"), "只进了日报" in ev(v, "#50")), (True, True))

    def down_site(now):
        raise TimeoutError("timed out")
    maintenance._CACHE.clear()
    maintenance._STATS.clear()
    maintenance.SOURCES = {"明日方舟": lambda now: None, "终末地": down_site, "鸣潮": lambda now: None}
    maintenance.today()
    w.settle()
    n = N()
    v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0, "n": 1}, "maintenance": maintenance.stats()},
               n)
    check("终末地取不到：没过", (status(v, "#50"), "终末地最近一次" in ev(v, "#50")), (FAIL, True))
    check("那条报错进了群（报警抄件里有）", "没好的 1 次都进了群" in ev(v, "#50"), True)
    check("没过推群", len(n.failed("#50")), 1)
finally:
    maintenance.SOURCES, maintenance._sleep, maintenance.urllib.request.urlopen = saved_m
    maintenance._CACHE.clear()
    maintenance._STATS.clear()
    w.close()

# ------------------------------------------------------------------ #56
print("\n[#56 心跳写得进腾讯云，写不进又好了的只进日报]")
answers = ["timed out", None]
real_put = phone.cos_put
phone.cos_put = lambda cos, key, data, timeout, **kw: answers.pop(0) if answers else None
d = tmpdir()
w = Watch(d)
t0 = time.time() - 5
try:
    hb = phone.Heartbeat("topic-x", d, post=lambda *a: None, cos=object())
    hb.cos_beat()
    hb.cos_beat()
    w.settle()
    v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "heartbeat": hb.cos_report()})
    check("一跳没写上、下一跳好了：过", (status(v, "#56"), "写上 1 次" in ev(v, "#56"), "只进了日报" in ev(v, "#56")),
          (PASS, True, True))
    same = {"since": time.time(), "base": {"heartbeat": hb.cos_report()}}
    check("机器没关、下一班一跳都没写：不判（按上一班末的数算）",
          status(judged(d, "phone_state", {"why": "关机前", "tally": same, "heartbeat": hb.cos_report()}), "#56"), None)
    phone.cos_put = lambda cos, key, data, timeout, **kw: "回 503"
    hb2 = phone.Heartbeat("topic-x", d, post=lambda *a: None, cos=object())
    hb2.cos_beat()
    hb2._cos_down = time.time() - 700            # the outage began 11 minutes ago
    hb2.cos_beat()
    w.settle()
    n = N()
    v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "heartbeat": hb2.cos_report()}, n)
    check("写不进 11 分钟：没过", (status(v, "#56"), "分钟写不进腾讯云" in ev(v, "#56")), (FAIL, True))
    check("没过推群", len(n.failed("#56")), 1)
finally:
    phone.cos_put = real_put
    w.close()

print("\n[卡池那段没给 notifier：没过的走 errwatch，标题是「🔬 上机核对没过」，正文带依据]")
d = tmpdir()
w = Watch(d)
tr = _b.Trace.new()
_b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, lambda u: None, {}, tr)
_b.save_trace(d, now, "", tr)
w.close()
check("进了群", [(t, "读图没有结果" in b) for t, b in w.group.sent if t.startswith(texts.MACHINECHECK_FAIL)],
      [(texts.machinecheck_failed("#2", mc.CHECKS["#2"].what) if "#2" in mc.CHECKS else "#2", True)])

_b._pause = saved_pause
print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
