"""Maintenance: the window and its notices, the cache, the deadline and marking every script.

One part per former file, each run on its own (tests/_parts.py): test_maintenance.py, test_maintenance_cache.py, test_maintenance_mark_every_script.py.
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
    """三家停服维护公告解析——夹具是 2026-09-02/03 从官网原样抓的页面。

    Formerly test_maintenance.py.
    """
    import json
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.maintenance import maintenance as M
    from ark_relay.core.config import SERVER_TZ, USER_TZ

    FX = Path(__file__).parent / "fixtures" / "maint"

    from ark_relay.features.banners import banners as B

    FXT = FX.parent
    # The JSON endpoints, recorded 2026-10-07 (the Wuthering Waves site's article
    # index and its 3.6 预告 2026-09-12); the in-game notice is of 2026-09-02.
    JSON_FX = {B._AK_NEWS_API.format(cat="ANNOUNCEMENT", page=1): FX / "ak_announcement_p1.json",
               B._AK_POST.format(cid="5102"): FX / "ak_5102.json",
               B._EF_CMS_LIST.format(page=1): FX / "ef_list_p1.json",
               B._EF_CMS_POST.format(cid="1164"): FX / "ef_1164.json",
               B._WW_SITE_ARTICLES: FXT / "wuwa_site_articles_2026-09-12.json",
               B._WW_SITE_ARTICLE.format(id="5282"): FXT / "wuwa_site_article_5282.json",
               M._WW_NOTICE: FX / "ww_notice.json"}
    asked = []


    def fake_get(url):
        asked.append(url)
        f = JSON_FX.get(url)
        if not f:
            raise KeyError(url)
        return f.read_text(encoding="utf-8", errors="replace")

    now = datetime(2026, 9, 3, 0, 30, tzinfo=SERVER_TZ)
    ak = M.arknights_window(now, get=fake_get)
    check("方舟：09-04 06:00–12:00", (ak[0].strftime("%m-%d %H:%M"), ak[1].strftime("%H:%M")) if ak else None, ("09-04 06:00", "12:00"))
    check("方舟：公告标题进证据", "[明日方舟]09月04日06:00版本更新停机维护公告" in ak[2], True)
    check("方舟：只读公告页的列表和那一帖（接口）", [u for u in asked if "hypergryph" in u],
          [B._AK_NEWS_API.format(cat="ANNOUNCEMENT", page=1), B._AK_POST.format(cid="5102")])
    ef = M.endfield_window(now, get=fake_get)
    check("终末地：09-02 06:00–12:00", (ef[0].strftime("%m-%d %H:%M"), ef[1].strftime("%H:%M")) if ef else None, ("09-02 06:00", "12:00"))
    check("终末地：取的是预告帖 1164", ef[2], "官方公告：「雪凇幽梦」版本预下载与更新预告（09-02 06:00–12:00）")
    # The page bodies of 2026-09-02/03 read the same windows as the endpoints' posts.
    check("方舟：旧网页正文与接口正文窗口一致",
          M._AK_BODY.search(M._text((FX / "ak_5102.html").read_text(encoding="utf-8", errors="replace"))).groups(),
          M._AK_BODY.search(B.ak_post_text(fake_get, "5102")).groups())
    check("终末地：旧网页正文与接口正文窗口一致",
          M._EF_BODY.search(M._text((FX / "ef_1164.html").read_text(encoding="utf-8", errors="replace"))).groups(),
          M._EF_BODY.search(B._ef_cms_text(json.loads(fake_get(B._EF_CMS_POST.format(cid="1164")))["data"]["data"])).groups())
    # A reply that is not code 0 is a failure, never "no maintenance".
    bad_code = lambda u: '{"code":1,"msg":"x"}'  # noqa: E731
    for name, fn in (("方舟", M.arknights_window), ("终末地", M.endfield_window)):
        try:
            fn(now, get=bad_code)
            check(f"{name}：code 不是 0 要报错", "没报错", "报错")
        except ValueError:
            check(f"{name}：code 不是 0 要报错", "报错", "报错")

    # Wuthering Waves: the site's 3.6 预告 (posted 08-13) a week ahead, the in-game
    # notice not asked; once the window is over, the in-game notice.
    asked.clear()
    ww_pre = M.wuwa_window(datetime(2026, 8, 15, 9, 0, tzinfo=SERVER_TZ), get=fake_get)
    check("鸣潮：官网维护预告提前一周给出 08-20 04:00–11:00",
          (ww_pre[0].strftime("%m-%d %H:%M"), ww_pre[1].strftime("%H:%M"), ww_pre[2]) if ww_pre else None,
          ("08-20 04:00", "11:00", "官方公告：《鸣潮》3.6版本更新维护预告（08-20 04:00–11:00）"))
    check("鸣潮：有预告就不读游戏内公告", M._WW_NOTICE in asked, False)
    check("鸣潮：维护当天照样是预告的窗口",
          M.wuwa_window(datetime(2026, 8, 20, 8, 0, tzinfo=SERVER_TZ), get=fake_get)[0].strftime("%m-%d %H:%M"), "08-20 04:00")
    asked.clear()
    ww = M.wuwa_window(now, get=fake_get)
    check("鸣潮：08-20 04:00–11:00", (ww[0].strftime("%m-%d %H:%M"), ww[1].strftime("%H:%M")) if ww else None, ("08-20 04:00", "11:00"))
    check("鸣潮：预告的窗口过了，读游戏内公告", M._WW_NOTICE in asked, True)
    src = {"明日方舟": lambda n: ak, "终末地": lambda n: ef, "鸣潮": lambda n: ww}
    check("09-04 当天：只有方舟在维护", list(M.today(datetime(2026, 9, 4, 8, 46, tzinfo=SERVER_TZ), sources=src)), ["明日方舟"])
    check("09-02 当天：只有终末地", list(M.today(datetime(2026, 9, 2, 8, 46, tzinfo=SERVER_TZ), sources=src)), ["终末地"])
    check("09-03：谁都不维护", M.today(datetime(2026, 9, 3, 8, 46, tzinfo=SERVER_TZ), sources=src), {})
    bad = {"明日方舟": lambda n: (_ for _ in ()).throw(OSError("net"))}
    check("取不到就当没有，不炸", M.today(now, sources=bad), {})
    failed = []
    M.today(now, sources={**bad, "终末地": lambda n: None}, failed=failed)
    check("取不到的记进 failed，读到了没有的不记", failed, ["明日方舟"])
    # ---- 明日安排里的维护提示（用户 2026-09-03：「这个务必要体现」）----
    # maintenance_lines 是这条要求唯一的落点，之前没有任何测试碰过它。漏掉这一行，
    # 队列会在停服时段照常开跑：全是失败，客户端也不会更新。
    from ark_relay.core import plan as P
    from datetime import date

    _real_today = M.today
    M.today = lambda at, failed=None: {"明日方舟": ak}
    lines = P.maintenance_lines(date(2026, 9, 4))
    check("维护当天出一行", len(lines), 1)
    check("点名游戏", "明日方舟" in lines[0], True)
    # App review 10-14: the window on the phone's clock (Tokyo, one hour ahead) and in plain words
    check("写清窗口（手机的东京时间）", "09-04 07:00–13:00" in lines[0], True)
    check("说清这一班不跑它", "这一班先跳过它" in lines[0], True)
    check("说清跑完就更新它", "跑完就更新它" in lines[0], True)
    check("说清开服后补跑", "13:00 开服后单独补跑" in lines[0], True)
    check("不用「队列」「客户端」这些词", "队列" in lines[0] or "客户端" in lines[0], False)
    # tomorrow 07:00 on the phone's clock (06:00 on the machine's), whatever the hour the test runs
    _tmw = (datetime.now(tz=USER_TZ).replace(hour=7, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(SERVER_TZ)
    M.today = lambda at, failed=None: {"终末地": (_tmw, _tmw.replace(hour=12), "test")}
    check("明天的窗口写「明天」", "终末地 明天 07:00–13:00 停服维护" in P.maintenance_lines(_tmw.date())[0], True)
    M.today = lambda at, failed=None: {"明日方舟": ak}

    M.today = lambda at, failed=None: {"明日方舟": ak, "终末地": ef}
    check("两家维护就出两行", len(P.maintenance_lines(date(2026, 9, 4))), 2)

    M.today = lambda at, failed=None: {}
    check("没人维护就一行都不出", P.maintenance_lines(date(2026, 9, 3)), [])

    M.today = lambda at, failed=None: (_ for _ in ()).throw(OSError("net"))
    check("取不到公告时安静返回空，不许把明日安排带走", P.maintenance_lines(date(2026, 9, 4)), [])


    # 2026-11-08: a game whose bulletin could not be read was left out of today()'s
    # result, and the plan read that as "no maintenance tomorrow".
    def _unread(at, failed=None):
        failed.extend(["终末地", "终末地"])
        return {"明日方舟": ak}


    M.today = _unread
    lines = P.maintenance_lines(date(2026, 9, 4))
    check("公告没读到的游戏单独一行，不当成没有维护",
          [ln for ln in lines if "没读到" in ln], ["⚠️ 终末地 明天的停服维护公告这次没读到：不知道有没有维护，这一班照常排"])
    check("读到的维护照旧一行", sum("停服维护：" in ln for ln in lines), 1)
    M.today = _real_today


def _part_maintenance_cache():  # noqa: C901 - the whole body of the file this part was
    """The official maintenance bulletins: one retry, a cache, one WARNING per real failure.

10-02 23:05:34 and 23:05:54 (#50 #53) ak.hypergryph.com and
endfield.hypergryph.com each timed out once, 20 s apart, inside one phone
state push: every state push builds tomorrow's plan, which read all three
official sites each time - dozens of times that evening, a WARNING for every
timeout. Every WARNING is pushed to the group now (2026-10-06);
the user on that: 「你正常情况应该一条都不发的」.

Pinned here: a site that does not answer is asked once more after a pause (an
HTTP answer is not); a good read is reused for OK_TTL; a failed read is a
WARNING once and, for FAIL_TTL, an INFO without asking again; `sources` given
(the tests, gameupdate's injected readers) is read as given. Fake network.

Since the user's rule of 2026-10-06 05:07 (「报错后自己好了的，只进日报、不进群」),
a retry that gets the page is one WARNING marked errwatch.recovered(): not
pushed, in the daily report; both tries failing is today()'s plain WARNING,
pushed (a real errwatch handler shows both).

    Formerly test_maintenance_cache.py.
    """
    import logging
    import tempfile
    import time
    import types
    import urllib.error
    import urllib.request
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.alarm import errwatch
    from ark_relay.features.maintenance import maintenance as M
    from ark_relay.core.config import SERVER_TZ


    class Logs(logging.Handler):
        def __init__(self):
            super().__init__()
            self.recs: list[tuple[int, str]] = []

        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage()))
            self.marked = getattr(self, "marked", [])
            if record.levelno >= logging.WARNING:
                self.marked.append(bool(getattr(record, errwatch.RECOVERED, False)))

        def warnings(self):
            return [m for lv, m in self.recs if lv >= logging.WARNING]


    class Pushes:
        def __init__(self):
            self.sent = []

        def send(self, title, body, **k):
            self.sent.append((title, body))
            return []


    STATE = Path(tempfile.mkdtemp(prefix="maint-cache-"))
    PUSHES = Pushes()
    WATCH = errwatch.ErrorKindAlert(PUSHES, state_dir=STATE, known={}, pace=0, retry=(0.05,))


    def pushed(want=0, secs=3.0):
        """What errwatch pushed to the group from M.log's records so far."""
        end = time.time() + secs
        while time.time() < end and (WATCH.pending() or len(PUSHES.sent) < want):
            time.sleep(0.02)
        time.sleep(0.1)
        return [b for _, b in PUSHES.sent]


    logs = Logs()
    M.log.addHandler(logs)
    M.log.addHandler(WATCH)
    M.log.setLevel(logging.DEBUG)
    M.log.propagate = False


    class Resp:
        def __init__(self, body: bytes):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body


    def net(*answers):
        calls = []
        queue = list(answers)

        def urlopen(req, timeout=None):
            calls.append(req.full_url)
            nxt = queue.pop(0)
            if isinstance(nxt, BaseException):
                raise nxt
            return Resp(nxt)
        M.urllib = types.SimpleNamespace(request=types.SimpleNamespace(Request=urllib.request.Request,
                                                                       urlopen=urlopen),
                                         error=urllib.error)
        return calls


    slept: list = []
    M._sleep = slept.append

    print("[_get：没响应就停一下再试一次；答了话（HTTP 错误）不重试]")
    try:
        logs.recs.clear()
        logs.marked = []
        calls = net(urllib.error.URLError("timed out"), "公告".encode())
        check("第一次超时、第二次读到", M._get("https://ak.hypergryph.com/news"), "公告")
        check("……一共问了两次", len(calls), 2)
        check("……中间停了一下", slept, [getattr(M, "GET_PAUSE", None)])
        check("recovered on the retry: one WARNING, marked recovered", logs.marked, [True])
        check("... in plain words, the URL and the first failure on the second line",
              (logs.warnings() or [""])[0].splitlines()[0], "停服维护公告的官网第一次没响应，3 秒后再取一次，取到了")
        check("... not pushed", pushed(), [])
        section = errwatch.daily_section(STATE, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
        check("... in the daily report, tagged 「自己好了，只进日报」",
              ("停服维护公告的官网第一次没响应" in section, "自己好了，只进日报" in section), (True, True))
        logs.recs.clear()
        logs.marked = []
        calls = net(urllib.error.HTTPError("https://x", 404, "nf", {}, None))
        try:
            M._get("https://x")
            raised = False
        except urllib.error.HTTPError:
            raised = True
        check("404：直接报，不重试", (raised, len(calls)), (True, 1))
        # relay-opt-round3-1108 O-03: a gateway's 503 is the network in front of the site.
        logs.recs.clear()
        logs.marked = []
        slept.clear()
        calls = net(urllib.error.HTTPError("https://x", 503, "busy", {}, None), "公告".encode())
        check("网关 503：停一下再试一次，取到了", (M._get("https://x"), len(calls), slept), ("公告", 2, [M.GET_PAUSE]))
        check("……只进日报（标自己好了），第二行写着回了 503",
              (logs.marked, "回了 503" in (logs.warnings() or [""])[0]), ([True], True))
        calls = net(urllib.error.HTTPError("https://x", 503, "busy", {}, None),
                    urllib.error.HTTPError("https://x", 503, "busy", {}, None))
        try:
            M._get("https://x")
            raised = False
        except urllib.error.HTTPError:
            raised = True
        check("两次都 503：报出来", (raised, len(calls)), (True, 2))
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ _get: {type(exc).__name__}: {exc}")
        fails.append("_get")

    print("\n[today：官方三家走缓存，一次真失败一条 WARNING]")
    NOW = datetime(2026, 10, 2, 23, 5, tzinfo=SERVER_TZ)
    WIN = (datetime(2026, 10, 2, 6, 0, tzinfo=SERVER_TZ), datetime(2026, 10, 2, 12, 0, tzinfo=SERVER_TZ), "官方公告")
    asked = {"明日方舟": 0, "终末地": 0, "鸣潮": 0}


    def ak(now):
        asked["明日方舟"] += 1
        raise urllib.error.URLError("timed out")


    def ef(now):
        asked["终末地"] += 1
        return WIN


    def ww(now):
        asked["鸣潮"] += 1
        return None


    saved = dict(M.SOURCES)
    M.SOURCES.update({"明日方舟": ak, "终末地": ef, "鸣潮": ww})
    getattr(M, "_CACHE", {}).clear()
    try:
        logs.recs.clear()
        failed: list = []
        check("第一次：终末地今天维护，方舟取不到", (list(M.today(NOW, failed=failed)), failed), (["终末地"], ["明日方舟"]))
        check("……方舟那次是一条 WARNING，说清是哪家官网",
              [("明日方舟" in m and "ak.hypergryph.com" in m) for m in logs.warnings()], [True])
        check("... not marked recovered, so it reached the group",
              (logs.marked[-1:], len(pushed(1))), ([False], 1))
        logs.recs.clear()
        for _ in range(5):        # five more state pushes in the next minutes
            failed = []
            M.today(NOW, failed=failed)
        check("再推五次状态：三家一个都不再去问", asked, {"明日方舟": 1, "终末地": 1, "鸣潮": 1})
        check("……方舟仍算取不到（调用方照样知道不知道）", failed, ["明日方舟"])
        check("……不再多记 WARNING（10-02 晚每推一次状态就是一条）", logs.warnings(), [])
        # the failure has aged past FAIL_TTL, the good reads have not
        for k in ("明日方舟",):
            k = (k, NOW.astimezone(SERVER_TZ).date())
            at, got = M._CACHE[k]
            M._CACHE[k] = (at - M.FAIL_TTL - 1, got)
        logs.recs.clear()
        M.today(NOW)
        check("失败过了 FAIL_TTL：方舟再去问一次，读到的两家还用缓存",
              asked, {"明日方舟": 2, "终末地": 1, "鸣潮": 1})
        check("……这次又是真失败：一条 WARNING", len(logs.warnings()), 1)
        for k in ("终末地", "鸣潮"):
            k = (k, NOW.astimezone(SERVER_TZ).date())
            at, got = M._CACHE[k]
            M._CACHE[k] = (at - M.OK_TTL - 1, got)
        M.today(NOW)
        check("读到的过了 OK_TTL：再去问", (asked["终末地"], asked["鸣潮"]), (2, 2))
        src = {"明日方舟": ak}
        before = asked["明日方舟"]
        M.today(NOW, sources=src)
        M.today(NOW, sources=src)
        check("给了 sources 就照给的读，不走缓存", asked["明日方舟"] - before, 2)
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ today: {type(exc).__name__}: {exc}")
        fails.append("today")
    finally:
        M.SOURCES.clear()
        M.SOURCES.update(saved)

    print("\n[缓存按问的是哪一天分开：先问明天（开机推手机状态）再问今天（开机查更新），今天的鸣潮维护照样看得到]")
    # 10-10: 「08:45:57 📱 已上报状态到手机（开机）」 (the plan asks about tomorrow), then
    # 「08:47:42 游戏更新：维护公告」 (gameupdate.boot_check asks about today). 鸣潮's answer
    # depends on the day asked (wuwa_window); one cache entry per game answered both (s16 #3).
    from datetime import timedelta
    TODAY = datetime(2026, 9, 30, 8, 45, tzinfo=SERVER_TZ)
    WIN = (datetime(2026, 9, 30, 4, 0, tzinfo=SERVER_TZ), datetime(2026, 9, 30, 11, 0, tzinfo=SERVER_TZ))
    saved = dict(M.SOURCES)
    M.SOURCES.clear()
    M.SOURCES["鸣潮"] = lambda now: WIN if WIN[1] >= now else None
    M._CACHE.clear()
    try:
        check("问明天：没有", M.today(TODAY + timedelta(days=1)), {})
        check("接着问今天：今天 04:00–11:00 停服维护", M.today(TODAY), {"鸣潮": WIN})
    finally:
        M.SOURCES.clear()
        M.SOURCES.update(saved)
        M._CACHE.clear()

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_maintenance_mark_every_script():
    """A failure inside an official maintenance window is marked for every script, on
the ledger and in the persisted hold, and its re-run is registered.

Audit 2026-10-13 s7 #1 / s1 #2: the mark sat in _archive_maaend_evidence - after
the ledger line was written and after its early returns - so the daily report
booked a plain failure, gameupdate.needs_rerun (it reads the ledger) never re-ran
what the 「进不了游戏」 alarm promised, and MAA / OK-WW never got the mark. The
alarm text also said 「20 秒内」 while the threshold is 30 seconds.
Review of 308e21b3: the mark is for a scheduled run being held (and the MaaEnd
update-restart hold, which lost it); a hand-started run (held only for its own
task's retries since 2026-10-16) and a MAA failure pushed at once on the update day
are not booked ⏸ nor re-run by the relay.

    Formerly test_maintenance_mark_every_script.py.
    """
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                      ARK_AUTOMAS_DIR=str(TMP / "nowhere"), ARK_MAAEND_DIR="", SERVERCHAN_KEY="",
                      ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng_mod
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features.alarm import handle
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.features.makeup import collect_retry


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return []


    class Src:
        def fetch(self, seen):
            return []


    handle._ship_evidence = lambda eng, rec: ""
    handle._hand_started = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None
    handle._archive_okww_evidence = lambda eng, rec: None
    collect_retry.restore_master = lambda cfg: ""


    def build(state_dir):
        cfg = Config()
        cfg.state_dir = state_dir
        cfg.maaend_dir = None
        e = eng_mod.Engine(cfg, source=Src(), state=State(state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        return e


    EVENING = datetime(2026, 10, 12, 21, 30, 5, tzinfo=SERVER_TZ)
    WHY = "官方公告：10-12 21:00–23:00 终末地停服维护"

    print("[MaaEnd fails inside the maintenance window]")
    state = TMP / "s1"
    state.mkdir()
    gameupdate.save_windows(state, {"终末地": (EVENING - timedelta(minutes=30), EVENING + timedelta(hours=1, minutes=30), WHY)})
    e = build(state)
    rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-17-30-05", script="MaaEnd", user="endfield",
                    started=EVENING, finished=EVENING + timedelta(minutes=3), ok=False,
                    failed_tasks=["协议空间"], raw={})
    handle._handle(e, rec)
    row = next(x for x in e.state.read_ledger("2026-10-12") if x["run_id"] == rec.run_id)
    check("the ledger line carries the mark", (row.get("raw") or {}).get("maintenance"), WHY)
    held = State(state).load_pending().get("pending") or []
    check("the persisted hold carries it (survives a restart)",
          [(p.get("raw") or {}).get("maintenance") for p in held], [WHY])
    check("the game is registered for the re-run", "终末地" in gameupdate.pending(state), True)
    check("needs_rerun reads it from the ledger",
          gameupdate.needs_rerun(state, EVENING + timedelta(hours=2), "MaaEnd"), True)

    print("\n[MAA fails inside the maintenance window (pushed at once as the update day)]")
    # Review of 308e21b3: the alarm says the evening shift runs it again, so it is not
    # booked ⏸ nor re-run by the relay (the mark is for scheduled runs being held).
    state = TMP / "s2"
    state.mkdir()
    gameupdate.save_windows(state, {"明日方舟": (EVENING - timedelta(minutes=30), EVENING + timedelta(hours=1), "明日方舟停服维护")})
    e = build(state)
    rec = RunRecord(run_id="2026-10-12/arknights/MAA-17-30-05", script="MAA", user="arknights",
                    started=EVENING, finished=EVENING + timedelta(minutes=1), ok=False,
                    failed_tasks=["MAA 在完成任务前中止"], raw={})
    handle._handle(e, rec)
    row = next(x for x in e.state.read_ledger("2026-10-12") if x["run_id"] == rec.run_id)
    check("pushed as the update day", [t for t, _ in e.notifier.sent][-1:], [texts.failed("MAA")])
    check("MAA's ledger line has no maintenance mark", (row.get("raw") or {}).get("maintenance"), None)
    check("明日方舟 is not registered for a relay re-run", "明日方舟" in gameupdate.pending(state), False)
    check("needs_rerun stays false", gameupdate.needs_rerun(state, EVENING + timedelta(hours=2), "MAA"), False)

    print("\n[a hand-started MaaEnd failure inside the window: pushed, not marked, not re-run]")
    state = TMP / "s4"
    state.mkdir()
    gameupdate.save_windows(state, {"终末地": (EVENING - timedelta(minutes=30), EVENING + timedelta(hours=1, minutes=30), WHY)})
    e = build(state)
    rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-17-35-00", script="MaaEnd", user="endfield",
                    started=EVENING + timedelta(minutes=5), finished=EVENING + timedelta(minutes=8), ok=False,
                    failed_tasks=["协议空间"], raw={})
    handle._hand_started = lambda eng, r: "task-hand"
    handle._handle(e, rec)
    handle._hand_started = lambda eng, r: ""
    row = next(x for x in e.state.read_ledger("2026-10-12") if x["run_id"] == rec.run_id)
    # Held until its task's later attempts decide (handle._hold_hand_started), then pushed
    # by the flush - not through its maintenance branch (no 进不了游戏 / re-run for it).
    check("the persisted hold has no maintenance mark",
          [(p.get("raw") or {}).get("maintenance") for p in State(state).load_pending().get("pending") or []], [None])
    e._flush_pending()
    check("pushed once the task's attempts are over", len(e.notifier.sent), 1)
    check("no maintenance mark on its ledger line", (row.get("raw") or {}).get("maintenance"), None)
    check("终末地 is not registered for a relay re-run", "终末地" in gameupdate.pending(state), False)
    check("needs_rerun stays false", gameupdate.needs_rerun(state, EVENING + timedelta(hours=2), "MaaEnd"), False)

    print("\n[a MaaEnd update restart held inside the window keeps the mark]")
    state = TMP / "s5"
    state.mkdir()
    gameupdate.save_windows(state, {"终末地": (EVENING - timedelta(minutes=30), EVENING + timedelta(hours=1, minutes=30), WHY)})
    e = build(state)
    rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-17-40-00", script="MaaEnd", user="endfield",
                    started=EVENING + timedelta(minutes=10), finished=EVENING + timedelta(minutes=11), ok=False,
                    failed_tasks=["协议空间"], raw={"maaend_update_restart": "v1.2.3"})
    handle._handle(e, rec)
    row = next(x for x in e.state.read_ledger("2026-10-12") if x["run_id"] == rec.run_id)
    check("held", (rec.script, rec.user) in e._pending, True)
    check("the ledger line carries the mark", (row.get("raw") or {}).get("maintenance"), WHY)
    held = State(state).load_pending().get("pending") or []
    check("the persisted hold carries it", [(p.get("raw") or {}).get("maintenance") for p in held], [WHY])
    check("终末地 is registered for the re-run", "终末地" in gameupdate.pending(state), True)

    print("\n[the 「进不了游戏」 text states the real threshold]")
    state = TMP / "s3"
    state.mkdir()
    e = build(state)
    rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-04-00", script="MaaEnd", user="endfield",
                    started=EVENING - timedelta(hours=11), finished=EVENING - timedelta(hours=11) + timedelta(minutes=2),
                    ok=False, failed_tasks=["协议空间"],
                    raw={"maaend_unreachable": True, "maaend_unreachable_why": "官方公告：今天版本更新"})
    e._pending[(rec.script, rec.user)] = rec
    e._flush_pending()
    body = "\n".join(b for _, b in e.notifier.sent)
    check("says 30 seconds", "30 秒内失败" in body, True)
    check("never 20 seconds", "20 秒" in body, False)

    print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_maintenance_cache, _part_maintenance_mark_every_script]))
