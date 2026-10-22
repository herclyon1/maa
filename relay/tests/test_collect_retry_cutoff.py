"""The gathering retry, cut off mid-way, is run once more; every way out closes MaaEnd and the game.

Audit s16 #2: the 「done today」 stamp is written before run_retry, which can take
half an hour. The relay does stop on this machine (relay.log:30844, 「10-10 12:29:59
收到停止通知（停止服务）」); a stamp left without `finished` then said 「已经跑过」 for
the rest of the day - no retry, no alarm, MaaEnd.exe / Endfield.exe left running.
run_retry's early 「gave up」 returns also left both running.
"""
import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.features.makeup import collect_retry as cr
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


FX = Path(__file__).resolve().parent / "fixtures" / "collect-retry-2026-09-11"
zh = json.loads((FX / "zh_cn.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 12, 12, 0).astimezone()
killed, ran = [], []
cr._kill = lambda name: killed.append(name)


def outcome(stamp: dict | None):
    """maybe_run with the retry stubbed and `stamp` already on disk: (ran?, stamp after)."""
    sd = tmpdir()
    f = sd / "collect-retry" / "2026-09-12.json"
    if stamp is not None:
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps(stamp), encoding="utf-8")
    eng = types.SimpleNamespace(
        cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(sd), history_dir=str(sd), automas_dir=None),
        state=types.SimpleNamespace(read_ledger=lambda d: [], mark_incomplete=lambda *a: True),
        notifier=types.SimpleNamespace(send=lambda t, b, **kw: []), _scripts_running=lambda: False)
    saved = (cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master)
    cr.latest_gathering_run = lambda entries, hist, labels: ({"run_id": "r1"}, ["AutoCollectRoute15"])
    cr.run_retry = lambda *a, **k: (ran.append(1), ({"AutoCollectRoute15": True}, ""))[1]
    cr._locale, cr.restore_master = (lambda d: zh), (lambda cfg: "")
    del ran[:], killed[:]
    try:
        cr.maybe_run(eng, now=NOW, day="2026-09-12")
    finally:
        cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master = saved
    return bool(ran), json.loads(f.read_text(encoding="utf-8"))


print("[补跑开始后中继停了：印记没有结束时间，过了补跑最长用时就再补一次]")
cut = {"run_id": "r1", "routes": ["AutoCollectRoute15"], "started": (NOW - timedelta(hours=2)).isoformat()}
did, after = outcome(cut)
check("两小时前开始、没结束 → 再补一次", did, True)
check("先关掉留下的 MaaEnd 和游戏", killed[:2], ["MaaEnd.exe", "Endfield.exe"])
check("这次跑完写了结束时间", "finished" in after, True)
did, _ = outcome(dict(cut, started=(NOW - timedelta(minutes=10)).isoformat()))
check("10 分钟前开始的（可能还在跑）→ 不动", did, False)
did, _ = outcome(dict(cut, finished=NOW.isoformat()))
check("跑完了的 → 不再跑", did, False)
did, after = outcome(dict(cut, cut_off="earlier"))
check("已经补过一次又断了 → 不再补", did, False)
check("写上结束，后面不再每次都说", "finished" in after, True)
# Review of c6922283: the give-up stamp had no passed/failed, so the daily report said
# 「开始了，还没有结果」 for a retry that was given up.
from ark_relay.features.report import report  # noqa: E402
gs = tmpdir()
(gs / "collect-retry").mkdir(parents=True)
(gs / "collect-retry" / "2026-09-12.json").write_text(json.dumps(after, ensure_ascii=False), encoding="utf-8")
line = report.retry_line(gs, "2026-09-12")
check("日报不说「还没有结果」", "还没有结果" in line, False)
check("日报说补跑两次都没跑完、哪条路线没结论", ("补跑两次都没跑完" in line, "没结论" in line), (True, True))
did, _ = outcome(None)
check("没有印记 → 照常跑", did, True)

print("\n[补跑被打断后这次没补成（脚本还在跑）：下一次调用不再报、不再关一遍]")
# Review of c6922283: the WARNING and the kills came before the early returns while the
# stamp was rewritten only on the path that re-runs, so every later tick said and killed again.
import logging  # noqa: E402


class _Warnings(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.msgs = []

    def emit(self, r):
        self.msgs.append(r.getMessage())


sd = tmpdir()
f = sd / "collect-retry" / "2026-09-12.json"
f.parent.mkdir(parents=True)
f.write_text(json.dumps(cut), encoding="utf-8")
eng = types.SimpleNamespace(
    cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(sd), history_dir=str(sd), automas_dir=None),
    state=types.SimpleNamespace(read_ledger=lambda d: []), _scripts_running=lambda: True)
saved = (cr.latest_gathering_run, cr._locale, cr.restore_master)
cr.latest_gathering_run = lambda entries, hist, labels: ({"run_id": "r1"}, ["AutoCollectRoute15"])
cr._locale, cr.restore_master = (lambda d: zh), (lambda cfg: "")
w = _Warnings()
cr.log.addHandler(w)
del killed[:]
try:
    r1 = cr.maybe_run(eng, now=NOW, day="2026-09-12")
    r2 = cr.maybe_run(eng, now=NOW + timedelta(minutes=1), day="2026-09-12")
finally:
    cr.log.removeHandler(w)
    cr.latest_gathering_run, cr._locale, cr.restore_master = saved
check("两次都没补（脚本还在跑）", (r1, r2), (False, False))
check("只报一次没跑完", sum("没跑完" in m for m in w.msgs), 1)
check("只关一次 MaaEnd 和游戏", killed, ["MaaEnd.exe", "Endfield.exe"])
check("印记还没写结束，脚本停了还会补", "finished" in json.loads(f.read_text(encoding="utf-8")), False)

print("\n[没跑完的两句警告原样进群：时刻写成「10-22 16:44」，不带 ISO 的「T16」（账本 #110）]")
from ark_relay.core.texts import plain  # noqa: E402
w2 = _Warnings()
cr.log.addHandler(w2)
try:
    outcome(cut)
    outcome(dict(cut, cut_off="earlier"))
finally:
    cr.log.removeHandler(w2)
said = [m for m in w.msgs + w2.msgs if "没跑完" in m]
check("两种没跑完都说了", (any("再补一次" in m for m in said), any("今天不再补" in m for m in said)), (True, True))
check("每句都是白话（texts.plain 没挑出毛病）", [plain(m) for m in said], [[] for _ in said])
check("时刻是机器上的「月-日 时:分」", all(cr._clock(cut["started"]) in m for m in said), True)
check("读不懂的时刻原样留着", cr._clock("earlier"), "earlier")

print("\n[run_retry 半路放弃（MaaEnd 不响应）也关掉 MaaEnd 和游戏]")
md = tmpdir() / "maaend"
(md / "debug").mkdir(parents=True)
(md / "debug" / "2026-09-12-1.log").write_bytes((FX / "mxu-app-override-line.log").read_bytes())
cr._running = lambda names: set()
cr._wait = lambda pred, seconds, step=3.0: False
cr.mxu_port = lambda d: 12701
cr.time = types.SimpleNamespace(sleep=lambda s: None, strftime=lambda f: "00:00:00", time=lambda: 0)
del killed[:]
verdict, note = cr.run_retry(md, ["AutoCollectRoute15"], "saturday", spawn=lambda exe, cwd, args: None)
check("放弃了", note, "MaaEnd 起来 60 秒了还不响应")
check("关掉了 MaaEnd 和游戏", sorted(killed), ["Endfield.exe", "MaaEnd.exe"])

print("\n[关游戏前先停掉补跑那组助手：MXU 不停旧的，新的连不上（10-22 21:56:40，账本 #111）]")
import urllib.error  # noqa: E402
calls, attached = [], {"n": 2}   # the gathering's go-service and cpp-algo, still attached


def fake_api(path, body=None, timeout=30):
    calls.append(path.rsplit("/", 2)[-2] + "/" + path.rsplit("/", 1)[-1])
    if path.endswith("/agent/stop"):
        attached["n"] = 0
    elif path.endswith("/tasks/start"):
        if attached["n"]:
            # mxu-tauri.log 21:56:40: 「Connection failed: MaaFramework internal error: status 0」
            raise urllib.error.HTTPError(path, 500, "agent failed to start", {}, None)
        attached["n"] = 2
    return {}


saved_api, saved_wait = cr.api, cr._wait
cr.api, cr._wait = fake_api, (lambda pred, seconds, step=3.0: pred())
try:
    why = cr._close_game("automas", {"CloseGamePC": {}}, lambda: {"is_running": False}, tmpdir())
finally:
    cr.api, cr._wait = saved_api, saved_wait
check("关游戏这一步被接下了（不再是 HTTPError）", why, "")
check("先停旧助手，再开关游戏任务", calls[:2], ["agent/stop", "tasks/start"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
