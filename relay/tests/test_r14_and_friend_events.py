"""Adversarial & replay tests for R-14 (Arknights activity open reminder),
strict 3-category friend WeChat event channel + dual hardlock, and the
hardlock-gated MAA OS-4 / MedicineNumb=999 script.
"""
from __future__ import annotations

# ruff: noqa: PLC0415
import http.server
import json
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir

_SHARED = (check, fails, require, tmpdir)
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

_SNOW_BULLETIN_HTML = (
    "<p><strong>一、SideStory「雪山降临1101」限时复刻开启</strong></p>"
    "<p><strong>活动时间：</strong>11月22日 04:00 - 12月06日 03:59</p>"
    "<p><strong>活动关卡开启时间：</strong></p>"
    "<p>◆「圣巡之旅」&amp;「变革之路」&amp;「喀兰之心」：11月22日 04:00 - 12月02日 03:59</p>"
    "<p><strong>二、【雷神推进者】系列，新装限时上架</strong></p>"
    "<p>活动时间：11月22日 04:00 - 12月06日 03:59</p>"
)

_NEWS_PAGE_1 = {
    "code": 0,
    "data": {
        "end": True,
        "list": [
            {"cid": "2808", "displayTime": 1794906000,
             "title": "[活动预告]SideStory「雪山降临1101」复刻即将开启"},
            {"cid": "7352", "displayTime": 1793505600,
             "title": "「时间啊，向前！」创作征集活动开启"},
            {"cid": "4916", "displayTime": 1792845000,
             "title": "[限定寻访·庆典]【将雪投火】限时寻访即将开启"},
        ],
    },
}


class _FakeNotifier:
    def __init__(self, *, fail_group: bool = False):
        self.fail_group = fail_group
        self.group_msgs: list[tuple[str, str]] = []
        self.sent_msgs: list[tuple[str, str]] = []

    def send_group(self, title: str, body: str) -> list[str]:
        if self.fail_group:
            return ["模拟群机器人失败"]
        self.group_msgs.append((title, body))
        return []

    def send(self, title: str, body: str, **_kw) -> list[str]:
        self.sent_msgs.append((title, body))
        return []


def _make_engine(tmp: Path, notifier: _FakeNotifier):
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import Config
    from ark_relay.core.ledger import State

    automas = tmp / "AUTO-MAS"
    (automas / "config").mkdir(parents=True, exist_ok=True)
    (automas / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (automas / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    state_dir = tmp / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    hist_dir = tmp / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    maa_dir = tmp / "maa"
    maa_dir.mkdir(parents=True, exist_ok=True)

    cfg = Config(
        history_dir=hist_dir,
        automas_dir=automas,
        state_dir=state_dir,
        maa_dir=maa_dir,
        serverchan_key="",
        wecom_bot_url="",
        alert_push_url="",
    )

    class _EmptySrc:
        def fetch(self, _seen):
            return []

    eng = eng_mod.Engine(cfg, source=_EmptySrc(), state=State(state_dir), notifier=notifier)
    eng._scripts_running = lambda: False
    return eng


def _fake_news_get(url: str) -> str:
    if "category=ACTIVITY" in url:
        return json.dumps(_NEWS_PAGE_1, ensure_ascii=False)
    if "/bulletin/2808" in url:
        return json.dumps({"code": 0, "data": {"title": "雪山降临1101", "data": _SNOW_BULLETIN_HTML}},
                          ensure_ascii=False)
    raise AssertionError(f"unexpected url: {url}")


def _part_r14_replay_snow_mountain():
    """Replay 「雪山降临1101」复刻 (StageActivityV2.json + cid=2808): triggers once, dedupes on rerun."""
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import ak_activity, friend_events

    tmp = tmpdir("r14-replay-")
    notifier = _FakeNotifier()
    eng = _make_engine(tmp, notifier)

    # Write StageActivityV2.json with both act46side (active) and TL (already ended 11-22 03:59).
    cache_path = eng.cfg.maa_dir / "cache" / "gui" / "StageActivityV2.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    stage_doc = {
        "Official": {
            "sideStoryStage": {
                "act46side": {
                    "MinimumRequired": "v6.14.0",
                    "Activity": {
                        "Tip": "SideStory「雪山降临1101」复刻",
                        "StageName": "雪山降临1101",
                        "UtcStartTime": "2026/11/22 04:00:00",
                        "UtcExpireTime": "2026/12/02 03:59:59",
                        "TimeZone": 8,
                    },
                    "Stages": [
                        {"Display": "OS-9", "Value": "OS-9", "Drop": "31053"},
                        {"Display": "OS-4", "Value": "OS-4", "Drop": "搓玉效率0.69"},
                    ],
                },
                "TL": {
                    "MinimumRequired": "v6.21.1",
                    "Activity": {
                        "Tip": "SideStory「时间啊，向前！」",
                        "StageName": "时间啊，向前！",
                        "UtcStartTime": "2026/11/01 12:00:00",
                        "UtcExpireTime": "2026/11/22 03:59:59",
                        "TimeZone": 8,
                    },
                },
            }
        }
    }
    cache_path.write_text(json.dumps(stage_doc, ensure_ascii=False), encoding="utf-8")

    now = datetime(2026, 11, 26, 12, 36, tzinfo=SERVER_TZ)
    delivered: list[dict] = []

    def _capture(ev: dict) -> tuple[str, str]:
        delivered.append(ev)
        return "ok", ""

    got1 = ak_activity.step(eng, now=now, get=_fake_news_get, force_news=True,
                            friend_post=_capture, friend_sync=True)
    check("首次触发恰好 1 个活动（双源合并、已结束 TL 不误报）", len(got1), 1)
    check("活动名为雪山降临1101", got1[0].name, "雪山降临1101")
    check("识别为复刻", got1[0].rerun, True)
    check("合并保留 act46side 与 cid=2808 两个别名",
          ("act46side" in got1[0].all_ids(), "cid=2808" in got1[0].all_ids()), (True, True))
    check("群通道推送 1 次", len(notifier.group_msgs), 1)
    title, body = notifier.group_msgs[0]
    check("群标题来自 texts.AK_ACTIVITY_OPEN", title, texts.AK_ACTIVITY_OPEN)
    check("群文案通过 texts.plain()", texts.plain(title) + texts.plain(body), [])
    check("群文案包含雪山降临1101和复刻", ("雪山降临1101" in body, "复刻" in body), (True, True))
    check("state.json 持久化了去重标记",
          eng.state.store.get("marks", "ak_activity:act46side") is not None, True)
    check("好友通道收到 1 条 arknights_activity_open", len(delivered), 1)
    check("好友事件字段完整匹配契约",
          (delivered[0]["category"], delivered[0]["game"], delivered[0]["days_left"],
           delivered[0]["recipient_wechat_id"]),
          (friend_events.CATEGORY_AK_ACTIVITY, "明日方舟", None, "No1Urgot"))

    # Second run must dedupe completely (zero group spam, zero duplicate friend events).
    got2 = ak_activity.step(eng, now=now + timedelta(minutes=30), get=_fake_news_get, force_news=True,
                            friend_post=_capture, friend_sync=True)
    check("二次运行去重，0 重复提醒", len(got2), 0)
    check("群消息仍为 1 条", len(notifier.group_msgs), 1)
    check("好友事件仍为 1 条", len(delivered), 1)

    # Even if cache switches key from act46side to real MAA slot key SSReopen for the SAME event,
    # cross-alias dedupe by name + start date must still suppress duplicates!
    stage_doc["Official"]["sideStoryStage"] = {
        "SSReopen": stage_doc["Official"]["sideStoryStage"]["act46side"]
    }
    cache_path.write_text(json.dumps(stage_doc, ensure_ascii=False), encoding="utf-8")
    got3 = ak_activity.step(eng, now=now + timedelta(hours=1), get=_fake_news_get, force_news=True,
                            friend_post=_capture, friend_sync=True)
    check("同活动换 SSReopen 槽位键仍去重", len(got3), 0)

    # A FUTURE rerun reusing the same SSReopen slot key MUST trigger!
    stage_doc["Official"]["sideStoryStage"]["SSReopen"]["Activity"] = {
        "Tip": "SideStory「墟」复刻",
        "StageName": "墟",
        "UtcStartTime": "2027/01/15 16:00:00",
        "UtcExpireTime": "2027/01/25 03:59:59",
        "TimeZone": 8,
    }
    cache_path.write_text(json.dumps(stage_doc, ensure_ascii=False), encoding="utf-8")
    # Two days before opening: must wait.
    got_early = ak_activity.step(eng, now=datetime(2027, 1, 13, 10, 0, tzinfo=SERVER_TZ),
                                 friend_post=_capture, friend_sync=True)
    check("开服前两天不提前刷屏", len(got_early), 0)
    # Morning of opening day (before 16:00): must notify 「今日开启」.
    got_day = ak_activity.step(eng, now=datetime(2027, 1, 15, 9, 0, tzinfo=SERVER_TZ),
                               friend_post=_capture, friend_sync=True)
    check("后续复刻复用 SSReopen 槽位正常触发", len(got_day), 1)
    check("开服当日早班文案写「今日开启」", "今日开启" in notifier.group_msgs[-1][1], True)

    # Group failure must NOT mark state.json so next tick retries.
    tmp_fail = tmpdir("r14-retry-")
    bad_notifier = _FakeNotifier(fail_group=True)
    eng_fail = _make_engine(tmp_fail, bad_notifier)
    got_fail = ak_activity.step(eng_fail, now=now, get=_fake_news_get, force_news=True)
    check("群推送失败时不计已提醒", (len(got_fail), eng_fail.state.store.section("marks")), (0, {}))
    bad_notifier.fail_group = False
    got_ok = ak_activity.step(eng_fail, now=now, get=_fake_news_get, force_news=True)
    check("群恢复后下轮补发成功", (len(got_ok), len(bad_notifier.group_msgs)), (1, 1))


def _part_r14_engine_tick_integration():
    """Engine.tick() automatically detects an open Arknights activity and dedupes on tick 2."""
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import friend_events

    tmp = tmpdir("r14-tick-")
    notifier = _FakeNotifier()
    eng = _make_engine(tmp, notifier)
    now = datetime.now(tz=SERVER_TZ)
    cache_path = eng.cfg.maa_dir / "cache" / "gui" / "StageActivityV2.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "Official": {
            "sideStoryStage": {
                "act_live_test": {
                    "Activity": {
                        "Tip": "SideStory「测试活动」",
                        "StageName": "测试活动",
                        "UtcStartTime": (now - timedelta(hours=2)).strftime("%Y/%m/%d %H:%M:%S"),
                        "UtcExpireTime": (now + timedelta(days=5)).strftime("%Y/%m/%d %H:%M:%S"),
                        "TimeZone": 8,
                    }
                }
            }
        }
    }, ensure_ascii=False), encoding="utf-8")

    eng.tick()
    check("Engine.tick 首次触发群提醒", len(notifier.group_msgs), 1)
    q = friend_events.FriendEventQueue(eng.cfg.state_dir)
    check("Engine.tick 首次写入好友事件队列", len(q.pending()), 1)
    check("好友事件类别为 arknights_activity_open", q.pending()[0]["category"], "arknights_activity_open")

    eng.tick()
    check("Engine.tick 二次运行不重复推群", len(notifier.group_msgs), 1)
    check("Engine.tick 二次运行不重复入队", len(q.pending()), 1)


def _part_friend_events_allowlist_and_integrations():
    """Positive tests for all 3 categories + adversarial hard-rejection of everything else."""
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import friend_events, phone, report

    tmp = tmpdir("friend-allow-")
    state_dir = tmp / "state"
    state_dir.mkdir()
    now = datetime(2026, 11, 26, 21, 30, tzinfo=SERVER_TZ)

    # 1. All 3 positive categories pass validation and enqueue idempotently.
    e1 = friend_events.build_event(
        event_id="b-1",
        category="next_day_new_banner",
        game="终末地",
        days_left=1,
        title="🎴 明天开新卡池：终末地",
        text="· 终末地 11-27 12:00 开 新干员",
        now=now,
    )
    e2 = friend_events.build_event(
        event_id="mc-1",
        category="monthcard_expiring_5d",
        game="鸣潮",
        days_left=5,
        title="💳 月卡快到期",
        text="鸣潮月卡还剩 5 天",
        now=now,
    )
    e2_zero = friend_events.build_event(
        event_id="mc-0",
        category="monthcard_expiring_5d",
        game="明日方舟",
        days_left=0,
        title="💳 月卡快到期",
        text="明日方舟月卡还剩 0 天",
        now=now,
    )
    e3 = friend_events.build_event(
        event_id="ak-1",
        category="arknights_activity_open",
        game="明日方舟",
        days_left=None,
        title="🎉 明日方舟活动开启",
        text="明日方舟支线活动（复刻）「雪山降临1101」已开启。",
        now=now,
    )
    q = friend_events.FriendEventQueue(state_dir)
    for ev in (e1, e2, e2_zero, e3):
        check(f"正例放行 {ev['event_id']}", q.enqueue(ev), True)
    check("相同 event_id 幂等去重返回 False", q.enqueue(e1), False)
    check("队列恰有 4 条有效事件", len(q.pending()), 4)
    check("seen_ids 记录 4 条", len(q.seen_ids()), 4)

    # 2. Adversarial negative cases: ALL MUST raise ValueError!
    bad_cases = [
        ("报错类别", dict(event_id="x1", category="error", game="明日方舟", title="通知", text="正文")),
        ("报警类别", dict(event_id="x2", category="alarm", game="明日方舟", title="通知", text="正文")),
        ("日报类别", dict(event_id="x3", category="daily_report", game="明日方舟", title="通知", text="正文")),
        ("终末地活动类别", dict(event_id="x4", category="endfield_activity_open", game="终末地", title="通知", text="正文")),
        ("终末地伪装成方舟活动", dict(event_id="x5", category="arknights_activity_open", game="终末地", title="🎉 活动开启", text="终末地活动")),
        ("鸣潮伪装成方舟活动", dict(event_id="x6", category="arknights_activity_open", game="鸣潮", title="🎉 活动开启", text="鸣潮活动")),
        ("未知游戏卡池", dict(event_id="x7", category="next_day_new_banner", game="原神", days_left=1, title="🎴 明天开新卡池", text="正文")),
        ("月卡剩余 6 天硬拒", dict(event_id="x8", category="monthcard_expiring_5d", game="明日方舟", days_left=6, title="💳 月卡快到期", text="还剩 6 天")),
        ("月卡已过期 -1 天硬拒", dict(event_id="x9", category="monthcard_expiring_5d", game="明日方舟", days_left=-1, title="💳 月卡快到期", text="已过期")),
        ("月卡 days_left=None 硬拒", dict(event_id="x10", category="monthcard_expiring_5d", game="明日方舟", days_left=None, title="💳 月卡快到期", text="无天数")),
        ("月卡 days_left=True 硬拒", dict(event_id="x11", category="monthcard_expiring_5d", game="明日方舟", days_left=True, title="💳 月卡快到期", text="布尔值")),
        ("错误微信号 filehelper", dict(event_id="x12", category="arknights_activity_open", game="明日方舟", title="🎉 明日方舟活动开启", text="正文", recipient_wechat_id="filehelper")),
        ("错误微信号 文件传输助手", dict(event_id="x13", category="arknights_activity_open", game="明日方舟", title="🎉 明日方舟活动开启", text="正文", recipient_wechat_id="文件传输助手")),
        ("空微信号", dict(event_id="x14", category="arknights_activity_open", game="明日方舟", title="🎉 明日方舟活动开启", text="正文", recipient_wechat_id="")),
        ("伪装报警标题 ❌", dict(event_id="x15", category="arknights_activity_open", game="明日方舟", title="❌ MAA 失败", text="正文")),
        ("伪装日报标题 📋", dict(event_id="x16", category="next_day_new_banner", game="明日方舟", days_left=1, title="📋 日报", text="正文")),
        ("空正文", dict(event_id="x17", category="arknights_activity_open", game="明日方舟", title="🎉 明日方舟活动开启", text="   ")),
    ]
    for label, kw in bad_cases:
        raised = False
        try:
            friend_events.build_event(now=now, **kw)
        except ValueError:
            raised = True
        check(f"硬拒 {label}", raised, True)

    # 3. End-to-end integration with report._announce_banners (category 1).
    tmp_b = tmpdir("friend-banner-")
    notifier_b = _FakeNotifier()
    eng_b = _make_engine(tmp_b, notifier_b)
    bnow = datetime(2026, 11, 26, 21, 30)  # naive Beijing time, matching report._compose_daily!
    nxt = {
        "明日方舟": (datetime(2026, 11, 27, 16, 0), "新六星「示例卡池」"),
        "鸣潮": (datetime(2026, 11, 27, 10, 0), "新五星「海汐之歌」"),
        "终末地": (datetime(2026, 11, 29, 12, 0), "后天开的不该报"),
    }
    report._announce_banners(eng_b, bnow, nxt)
    check("原群播报正常发出 1 条", len(notifier_b.group_msgs), 1)
    qb = friend_events.FriendEventQueue(eng_b.cfg.state_dir)
    check("report._announce_banners 写入 2 条次日卡池好友事件", len(qb.pending()), 2)
    check("次日卡池事件游戏为鸣潮和明日方舟",
          [ev["game"] for ev in qb.pending()], ["鸣潮", "明日方舟"])
    check("次日卡池事件均指向 No1Urgot",
          all(ev["recipient_wechat_id"] == "No1Urgot" for ev in qb.pending()), True)

    # 4. End-to-end integration with Engine._monthcard_notice & phone.due_items (category 2).
    tmp_mc = tmpdir("friend-mc-")
    notifier_mc = _FakeNotifier()
    eng_mc = _make_engine(tmp_mc, notifier_mc)
    today = date.today()
    phone.apply(eng_mc.state.dir, {"game": "明日方舟", "left": 3}, today=today)
    phone.apply(eng_mc.state.dir, {"game": "终末地", "left": 6}, today=today)  # >5d: must NOT trigger
    eng_mc._monthcard_notice()
    check("原月卡提醒正常发出 1 条", len(notifier_mc.sent_msgs), 1)
    qmc = friend_events.FriendEventQueue(eng_mc.cfg.state_dir)
    check("月卡好友事件只收 <=5 天的 1 条（6 天被排除）", len(qmc.pending()), 1)
    check("月卡好友事件字段准确",
          (qmc.pending()[0]["category"], qmc.pending()[0]["game"], qmc.pending()[0]["days_left"]),
          ("monthcard_expiring_5d", "明日方舟", 3))


def _part_friend_events_dual_hardlock_and_http():
    """HARDLOCK + HARDLOCK_WECHAT dual lock guarantees 0 outbound; unlocking drains cleanly over HTTP."""
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import friend_events

    received: list[dict] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            received.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, _fmt, *_args):
            return

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}/friend-event"

    try:
        tmp = tmpdir("friend-lock-")
        sd = tmp / "state"
        sd.mkdir()
        now = datetime(2026, 11, 26, 12, 36, tzinfo=SERVER_TZ)

        # Lock 1: HARDLOCK.json active -> 0 outbound.
        (sd / "HARDLOCK.json").write_text(json.dumps({"locked": True, "reason": "全局硬锁"}), encoding="utf-8")
        check("HARDLOCK.json 判定为硬锁", friend_events.is_hardlocked(sd), True)
        added = friend_events.emit_arknights_activity_open(
            sd, "act46side", "🎉 明日方舟活动开启", "雪山降临1101已开启", now=now, url=url, sync=True
        )
        check("硬锁态事件可本地入队", added, True)
        check("HARDLOCK 锁态零触发外发", len(received), 0)

        # Lock 2: HARDLOCK.json removed, HARDLOCK_WECHAT.json active -> still 0 outbound.
        (sd / "HARDLOCK.json").unlink()
        (sd / "HARDLOCK_WECHAT.json").write_text(json.dumps({"locked": True, "reason": "微信硬锁"}), encoding="utf-8")
        check("HARDLOCK_WECHAT.json 单独生效也判定为硬锁", friend_events.is_hardlocked(sd), True)
        friend_events.flush_pending(sd, url=url)
        check("HARDLOCK_WECHAT 锁态零触发外发", len(received), 0)

        # Corrupt HARDLOCK_WECHAT.json -> fail-closed, 0 outbound.
        (sd / "HARDLOCK_WECHAT.json").write_text("{corrupt", encoding="utf-8")
        check("损坏锁文件按锁定处理（fail-closed）", friend_events.is_hardlocked(sd), True)
        friend_events.flush_pending(sd, url=url)
        check("损坏锁文件零触发外发", len(received), 0)

        # Inject a tampered non-allowlisted row into queue on disk, then unlock both locks.
        (sd / "HARDLOCK_WECHAT.json").write_text(json.dumps({"locked": False}), encoding="utf-8")
        check("双锁解除后判定为未锁", friend_events.is_hardlocked(sd), False)
        qpath = sd / friend_events.QUEUE_FILE
        rows = json.loads(qpath.read_text(encoding="utf-8"))
        rows.append({
            "event_id": "tampered-1",
            "category": "arknights_activity_open",
            "game": "明日方舟",
            "days_left": None,
            "title": "🎉 篡改测试",
            "text": "企图发到文件传输助手",
            "recipient_wechat_id": "filehelper",
            "created_at": now.isoformat(timespec="seconds"),
        })
        qpath.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

        left = friend_events.flush_pending(sd, url=url)
        check("解封后队列清零", left, 0)
        check("仅 1 条合规事件送达 Mac，篡改事件被拦截", len(received), 1)
        check("送达事件收件人为 No1Urgot", received[0]["recipient_wechat_id"], "No1Urgot")
        check("送达事件 event_id 准确", received[0]["event_id"], "arknights_activity_open:act46side")
    finally:
        srv.shutdown()
        srv.server_close()


def _part_set_maa_os4_medicine999():
    """Verify set_maa_os4_medicine999.py: --check (0/2), HARDLOCK RC=4, --apply backup + write + 8-field verify."""
    script_path = REPO / "scripts" / "windows" / "set_maa_os4_medicine999.py"
    require("锁控脚本存在", script_path.is_file(), str(script_path))

    state: dict = {
        "calls": [],
        "drop_medicine": False,
        "user": {
            "Info": {"Name": "arknights", "Status": True, "RemainedDay": -1},
            "Stage": {
                "StageMode": "Plan-UUID",
                "Stage": "1-7",
                "Stage_1": "CE-6",
                "Stage_2": "LS-6",
                "Stage_3": "AP-5",
                "MedicineNumb": 0,
            },
            "Task": {
                "IfFight": False,
                "IfActivityFirst": True,
                "Annihilation": "Annihilation",
            },
        },
    }

    class _MasHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            state["calls"].append((self.path, body))
            if self.path == "/api/scripts/get":
                reply = {
                    "code": 200,
                    "data": {
                        "S-MAA": {"Info": {"Name": "MAA", "Path": r"D:\ark\maa"}},
                        "S-END": {"Info": {"Name": "MaaEnd", "Path": r"D:\ark\maaend"}},
                    },
                }
            elif self.path == "/api/scripts/user/get":
                reply = {"code": 200, "data": {"U-AK": state["user"]}}
            elif self.path == "/api/scripts/user/update":
                patch = body.get("data") or {}
                for grp, vals in patch.items():
                    state["user"].setdefault(grp, {})
                    for k, v in vals.items():
                        if state["drop_medicine"] and grp == "Stage" and k == "MedicineNumb":
                            continue
                        state["user"][grp][k] = v
                reply = {"code": 200, "message": "ok"}
            else:
                self.send_response(404)
                self.end_headers()
                return
            raw = json.dumps(reply, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, _fmt, *_args):
            return

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MasHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{port}"
    py = sys.executable

    try:
        tmp = tmpdir("maa-os4-")
        hl_file = tmp / "state" / "HARDLOCK.json"
        hl_file.parent.mkdir(parents=True)
        bak_dir = tmp / "backups"

        # 1. Default / --check on drifted config -> RC=2, zero writes.
        r_chk = subprocess.run(
            [py, str(script_path), "--check", "--mas-url", base_url],
            capture_output=True, text=True, check=False,
        )
        check("未修改前 --check 退出码为 2（待修改）", r_chk.returncode, 2)
        chk_out = json.loads(r_chk.stdout)
        check("未修改前检出全部 8 个漂移字段", len(chk_out["diffs"]), 8)
        check("--check 期间零写入 API",
              any(p == "/api/scripts/user/update" for p, _ in state["calls"]), False)

        # 2. --apply under HARDLOCK.json -> RC=4, ZERO HTTP calls!
        state["calls"].clear()
        hl_file.write_text(json.dumps({"locked": True, "reason": "11-26 硬锁"}), encoding="utf-8")
        r_lk = subprocess.run(
            [py, str(script_path), "--apply", "--mas-url", base_url,
             "--hardlock", str(hl_file), "--backup-dir", str(bak_dir)],
            capture_output=True, text=True, check=False,
        )
        check("HARDLOCK 锁态 --apply 退出码为 4", r_lk.returncode, 4)
        check("HARDLOCK 锁态零 API 请求", len(state["calls"]), 0)
        check("HARDLOCK 锁态不建备份", bak_dir.exists(), False)

        # 3. Corrupt HARDLOCK.json -> fail-closed RC=4, zero calls.
        hl_file.write_text("not-json", encoding="utf-8")
        r_bad = subprocess.run(
            [py, str(script_path), "--apply", "--mas-url", base_url,
             "--hardlock", str(hl_file), "--backup-dir", str(bak_dir)],
            capture_output=True, text=True, check=False,
        )
        check("损坏 HARDLOCK.json 按锁拒写 RC=4", r_bad.returncode, 4)
        check("损坏 HARDLOCK.json 零 API 请求", len(state["calls"]), 0)

        # 4. Unlocked --apply -> RC=0, backup written, all 8 fields written & read-back verified!
        hl_file.write_text(json.dumps({"locked": False}), encoding="utf-8")
        r_app = subprocess.run(
            [py, str(script_path), "--apply", "--mas-url", base_url,
             "--hardlock", str(hl_file), "--backup-dir", str(bak_dir)],
            capture_output=True, text=True, check=False,
        )
        check("解封后 --apply 退出码为 0", r_app.returncode, 0)
        app_out = json.loads(r_app.stdout)
        check("解封后回读核验 8 字段全部到位", app_out["verified_fields"], 8)
        check("写入值精确为 OS-4 与 MedicineNumb=999 等 8 项",
              (state["user"]["Stage"]["StageMode"],
               state["user"]["Stage"]["Stage"],
               state["user"]["Stage"]["Stage_1"],
               state["user"]["Stage"]["Stage_2"],
               state["user"]["Stage"]["Stage_3"],
               state["user"]["Stage"]["MedicineNumb"],
               state["user"]["Task"]["IfFight"],
               state["user"]["Task"]["IfActivityFirst"]),
              ("Fixed", "OS-4", "-", "-", "-", 999, True, False))
        bak_path = Path(app_out["backup"])
        check("备份文件已落盘且保留修改前原值",
              bak_path.is_file() and json.loads(bak_path.read_text(encoding="utf-8"))["before"]["Stage"]["Stage"] == "1-7",
              True)

        # 5. Re-running --check now -> RC=0!
        r_chk2 = subprocess.run(
            [py, str(script_path), "--mas-url", base_url],
            capture_output=True, text=True, check=False,
        )
        check("修改后默认只读模式退出码为 0（已到位）", r_chk2.returncode, 0)

        # 6. Simulated silent API drop on MedicineNumb -> read-back catches it and exits 1!
        state["user"]["Stage"]["MedicineNumb"] = 0
        state["drop_medicine"] = True
        r_mismatch = subprocess.run(
            [py, str(script_path), "--apply", "--mas-url", base_url,
             "--hardlock", str(hl_file), "--backup-dir", str(bak_dir)],
            capture_output=True, text=True, check=False,
        )
        check("回读发现字段未生效时 --apply 退出码为 1", r_mismatch.returncode, 1)
    finally:
        srv.shutdown()
        srv.server_close()

    # Exercise module imports directly as well (ensures deadcode coverage).
    sys.path.insert(0, str(REPO / "scripts" / "windows"))
    import set_maa_os4_medicine999 as mod
    check("TARGET_FIELDS 包含精确 8 项", len(mod.TARGET_FIELDS), 8)
    check("Stage 目标为 OS-4（非 GS-4）", mod.TARGET_FIELDS["Stage.Stage"], "OS-4")
    check("diff_target 可直接调用", mod.diff_target(state["user"]) != {}, True)
    check("check_hardlock 缺省锁文件返回空", mod.check_hardlock(tmp / "no_lock.json", explicit=True), "")
    check("run_check/run_apply 可导入", (callable(mod.run_check), callable(mod.run_apply)), (True, True))


if __name__ == "__main__":
    raise SystemExit(run_parts([
        _part_r14_replay_snow_mountain,
        _part_r14_engine_tick_integration,
        _part_friend_events_allowlist_and_integrations,
        _part_friend_events_dual_hardlock_and_http,
        _part_set_maa_os4_medicine999,
    ]))
