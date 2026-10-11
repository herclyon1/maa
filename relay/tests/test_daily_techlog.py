"""The daily report keeps what a person reads; the technical parts go to the technical log.

Decision D-1010 (the user, 2026-10-10 22:47 Osaka; quoted in BOARD/DECISIONS.md and
docs/NOTIFICATIONS.md): the report is for a person to read; what we read goes
somewhere of our own (core/techlog.py, <state>/../tech/<day>.md).

Every technical source is seeded here, so each marker is first shown to land in the
technical log (proving the fixture produced it) and then shown to be absent from the
report body. With the change reverted, the body carries them again and this goes red:
* the deploy notes (remember_change) -> one sentence with their number in the report;
* the relay's own faults (errwatch day file), the machine checks, the boot self-check;
* the test-window count;
* a failed row's evidence link, MaaEnd's version, OK-WW's changed client files;
* rows name the game, not the script.
Also: written where the day's report is sent and marked, never by an interim look,
not twice on a retried send, and a technical log that cannot be written leaves the
report exactly as it was and still sends it.

No network: banners and the report-writing model are stubbed as in test_report_due.py.
"""
import json
import os
import re
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import errwatch, report
from ark_relay.config import SERVER_TZ
from ark_relay.core import techlog
from ark_relay.core.ledger import State

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + ("" if ok else f": got {got!r:.400}, want {want!r}"))
    if not ok:
        fails.append(label)


report.plan = types.SimpleNamespace(
    schedule=lambda automas_dir: [{"name": "晚班", "times": ["21:30"]}],
    next_plan=lambda automas_dir: "",
    activity_countdown=lambda automas_dir: "",
)
report.banners = types.SimpleNamespace(
    collect=lambda now, skland_token="", failed=None, notes=None, trace=None, versions=None, leads=None,
    read_image=None: ([], {}),
    image_reader=lambda state_dir: None,
    render=lambda rows, now, nxt, notes=None, trace=None, failed=None, leads=None: "",
    Trace=types.SimpleNamespace(new=lambda: None),
    save_trace=lambda state_dir, now, text, tr: None,
    update_history=lambda state_dir, now: [],
)
report.summary = types.SimpleNamespace(daily_report=lambda cfg, entries, plan="": "")

TODAY = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
URL = "https://ark-evidence-1.cos.ap-shanghai.myqcloud.com/MAA-21-30.zip?q-signature=abc"
VERSION = "v2.32.0-beta.1"
PAK = "Content\\Paks\\pakchunk0.pak"
# What a technical line looks like. None of it may reach the report body.
TECH_IN_BODY = re.compile(
    r"Traceback|myqcloud\.com|证据包|v\d+\.\d+\.\d+|v20\d{12}|pakchunk|重试后成功|耗时"
    r"|今天中继改了什么|中继自己记下的报错|上机核对|中继体检|测试跑过")
SCRIPT_ROW = re.compile(r"^\S+ (MAA|OK-WW|MaaEnd)(（|　)", re.M)


class Notifier:
    def __init__(self):
        self.sent: list = []
        self.broken = False

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body))
        return ["Server酱: 假装挂了"] if self.broken else []

    def send_group(self, title, body):
        return []

    def send_group_image(self, path):
        return []


class Eng:
    """The slice of Engine the report uses; forwards exactly as engine.py does."""

    def __init__(self, state_dir: Path):
        self.cfg = types.SimpleNamespace(
            automas_dir=None, history_dir=None, okww_dir=None, skland_token="",
            state_dir=state_dir, last_run_after="21:30", interim_report=True)
        self.state = State(state_dir)
        self.notifier = Notifier()

    def _report_cutoff(self, now):
        return report._report_cutoff(self, now)

    def _scripts_running(self):
        return False

    def _unfinished_queues(self, now, entries):
        return []

    def _round_is_manual(self, new_entries):
        return False

    def _compose_daily(self, day, entries):
        return report._compose_daily(self, day, entries)

    def _announce_banners(self, now, nxt):
        return None

    def send_daily_now(self, mark=True, label="临时查看"):
        return report.send_daily_now(self, mark, label)


def run(rid, script, hhmm, mins, ok, failed=(), transitional=False, **raw):
    start = datetime.fromisoformat(f"{TODAY}T{hhmm}:00+08:00")
    return {"run_id": f"{TODAY}/x/{rid}", "script": script, "user": "u",
            "started": start.isoformat(), "finished": (start + timedelta(minutes=mins)).isoformat(),
            "ok": ok, "failed_tasks": list(failed), "duration_known": True,
            "transitional": transitional, "raw": raw}


ENTRIES = [
    # OK-WW: the restart dialog swapped a client file, then a clean run.
    run("ww1", "OK-WW", "09:00", 1, False, transitional=True, okww_restart_dialog=True,
        okww_client_change="patch", okww_client_files=[PAK]),
    run("ww2", "OK-WW", "09:02", 10, True, tasks_done=["日常"]),
    # MaaEnd: installed its new build and restarted, then a clean run.
    run("ef1", "MaaEnd", "09:20", 2, False, failed=["MaaEnd 进程超时"], maaend_update_restart=VERSION),
    run("ef2", "MaaEnd", "09:23", 20, True, tasks_done=["赠送干员礼物"]),
    # A test run inside a marked test window.
    run("test", "MAA", "12:00", 5, True, tasks_done=["日常"]),
    # MAA's evening run failed for good; its evidence bundle was uploaded.
    run("maa", "MAA", "21:30", 3, False, failed=["基建换班"], evidence_page=URL),
]


def machine() -> Eng:
    """A machine with every technical source seeded."""
    root = tmpdir()
    sd = root / "state"
    sd.mkdir()
    e = Eng(sd)
    e.state.ledger_path(TODAY).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ENTRIES), encoding="utf-8")
    (sd / "test-windows.json").write_text(json.dumps(
        [{"since": f"{TODAY}T11:59:00+08:00", "until": f"{TODAY}T12:10:00+08:00"}]), encoding="utf-8")
    report.remember_change(sd, "周本领奖补回来了。", "20261011104917", day=TODAY)
    report.remember_change(sd, "通知分三路。", "20261011104918", day=TODAY)
    (sd / errwatch.DAY_DIR).mkdir()
    (sd / errwatch.DAY_DIR / f"{TODAY}.json").write_text(json.dumps({
        "k1": {"where": "ark.notify", "line": "推送重试后成功，耗时 3 秒", "count": 2, "pushed": 2,
               "first": f"{TODAY} 10:00:00"}}, ensure_ascii=False), encoding="utf-8")
    log = root / "relay.log"
    log.write_text(f"{TODAY[5:]} 10:00:00 ERROR    ark.report 日报推送重试后成功\n", encoding="utf-8")
    os.environ["ARK_LOG_FILE"] = str(log)
    return e


def at(hhmm):
    return datetime.fromisoformat(f"{TODAY}T{hhmm}:00+08:00").astimezone(SERVER_TZ)


def tech_of(e) -> str:
    p = techlog.path_for(TODAY, e.cfg.state_dir)
    return p.read_text(encoding="utf-8") if p.exists() else ""


print("[每一路技术内容都进技术日志（先证明它真被造出来了）]")
e = machine()
report._maybe_daily_report(e, at("22:00"))
check("日报发出去了", len(e.notifier.sent), 1)
check("当天记号落了", e.state.report_sent(TODAY), True)
title, body = e.notifier.sent[-1]
tech = tech_of(e)
check("技术日志在 <state>/../tech/<日期>.md",
      techlog.path_for(TODAY, e.cfg.state_dir) == (e.cfg.state_dir.parent / "tech" / f"{TODAY}.md").resolve())
for heading in ("今天中继改了什么", "中继自己记下的报错", "上机核对（部署后机器自己核）", "中继体检",
                "测试窗口里的记录（不计入日报）", "日报各行的证据包、版本和文件"):
    check(f"技术日志有「## HH:MM {heading}」", bool(re.search(rf"^## \d\d:\d\d {re.escape(heading)}$", tech, re.M)))
check("部署说明在技术日志里", "周本领奖补回来了" in tech and "通知分三路" in tech)
check("中继自己的报错原话在技术日志里", "推送重试后成功，耗时 3 秒" in tech)
check("测试那一趟的趟号在技术日志里", f"{TODAY}/x/test" in tech)
check("证据包链接在技术日志里，带趟号", f"{TODAY}/x/maa 证据包 {URL}" in tech)
check("终末地的版本号在技术日志里", f"{TODAY}/x/ef1 MaaEnd 装新版 {VERSION} 后自己重启" in tech)
check("鸣潮换了的文件在技术日志里", f"{TODAY}/x/ww1 OK-WW 游戏更新换了的文件：{PAK}" in tech)

print("\n[日报正文里一行技术内容都没有]")
check("正文里没有技术行", TECH_IN_BODY.findall(body), [])
check("行首是游戏名，不是脚本名", SCRIPT_ROW.findall(body), [])
check("各游戏的行都在", all(f"{icon} {g}　" in body for icon, g in
                         (("↪️", "鸣潮"), ("✅", "鸣潮"), ("↪️", "终末地"), ("✅", "终末地"), ("❌", "明日方舟"))))
check("失败那一行还说没成的是哪一步", "失败于：基建换班" in body)
check("鸣潮更新那一行还在，只是不点名文件", "游戏更新成功（更新了客户端文件），重启后重跑，不算失败" in body)
check("终末地更新那一行还在，只是不报版本", "终末地装了新版后自己重启，用掉一次重试，不算失败" in body)
check("部署只剩一句次数", body.rstrip().endswith("今天中继更新了 2 次"))
check("测试那一趟不在日报里", "12:00→" in body, False)
check("标题照旧点名失败的游戏", "明日方舟失败 1 次" in title)

print("\n[只在发出并落记号的那一次写；重试发送不写第二遍]")
e = machine()
e.notifier.broken = True
report._maybe_daily_report(e, at("22:00"))
check("推送失败：不落记号", e.state.report_sent(TODAY), False)
first = tech_of(e)
check("推送失败那一次技术日志已经写了", "今天中继改了什么" in first)
e.notifier.broken = False
report._maybe_daily_report(e, at("22:05"))
check("重试发出去了", e.state.report_sent(TODAY), True)
check("重试没把技术日志再写一遍", tech_of(e).count("今天中继改了什么"), 1)

print("\n[临时查看不写技术日志，正文一样干净]")
e = machine()
check("临时查看发出去了", e.send_daily_now(mark=False), True)
check("临时查看不写技术日志", tech_of(e), "")
check("临时查看的正文也没有技术行", TECH_IN_BODY.findall(e.notifier.sent[-1][1]), [])
check("send_daily_now(mark=True) 写技术日志", (e.send_daily_now(mark=True), "日报各行的证据包" in tech_of(e)), (True, True))

print("\n[技术日志写不进去：日报照旧、照发]")
ok = machine()
report._maybe_daily_report(ok, at("22:00"))
e = machine()
(e.cfg.state_dir.parent / "tech").write_text("not a directory", encoding="utf-8")
report._maybe_daily_report(e, at("22:00"))
check("日报照发、记号照落", (len(e.notifier.sent), e.state.report_sent(TODAY)), (1, True))
check("正文和写得进去时一字不差", e.notifier.sent[-1][1], ok.notifier.sent[-1][1])
check("一段都没记成已写，下次还能补", e.state.techlog_written(TODAY), set())

print("\n[红项的格式：读取工具按这个认（ac38f466 的格式）]")
when = datetime(2026, 10, 11, 21, 45, tzinfo=SERVER_TZ)
reds = techlog.red_items(TODAY, ["收工体检：补丁不在", "明早的队列读不到"], now=when)
check("每条红项带自己的编号", reds, ["🔴 R-20261011-2145-1 收工体检：补丁不在",
                                   "🔴 R-20261011-2145-2 明早的队列读不到"])
text = "\n".join(reds + [techlog.handled_line("R-20261011-2145-1", "abc1234")])
check("已处理那一行的样子", techlog.handled_line("R-20261011-2145-1", "abc1234"),
      "✅ R-20261011-2145-1 已处理（abc1234）")
check("处理过的不再算没处理", techlog.unhandled(text), [("R-20261011-2145-2", "明早的队列读不到")])
d = tmpdir() / "state"
check("空内容不写文件也算成功", (techlog.append(TODAY, "空", "  ", state_dir=d), techlog.path_for(TODAY, d).exists()),
      (True, False))
check("一段写成 ## HH:MM 标题",
      (techlog.append(TODAY, "收工体检", "\n".join(reds), state_dir=d, now=when),
       techlog.path_for(TODAY, d).read_text(encoding="utf-8")),
      (True, "\n## 21:45 收工体检\n" + "\n".join(reds) + "\n"))

if fails:
    print(f"\nFAILED: {fails}")
    sys.exit(1)
print("\nall checks passed")
