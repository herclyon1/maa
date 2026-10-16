"""A gathering route that hit 「战斗中无法使用」 is booked as not gathered and re-run (ledger #29).

Route 10 (重红柱状菌) walks past a relay device; when a fight is on, the game says
「战斗中无法使用，请脱离战斗后尝试」, MaaEnd saves an on_error picture of the node
MapNavigatorObstacleDevice_InteractPost, and still ends the route normally - no
「采集失败」 line, AutoCollectRoute10End in maafw.log. Route 10 then picked up 2
(10-05), 0 (10-08) and 4 (10-12) against 6-10 on good runs, and nothing said so:
relay.log 10-14 09:59:16 says the retry found nothing to re-run: 「…全部路线走通，没有要补的」.

Fixtures (tests/fixtures/collect-blocked-1005-1012) are the 自动采集 stretch of the
real AUTO-MAS history logs (2026-10-05 MaaEnd-06-39-48, 10-08 MaaEnd-06-34-21,
10-12 MaaEnd-06-04-00 and MaaEnd-06-58-38; MaaEnd-06-47-30 is the whole 2026-09-11 run
that was cut short after its 「路线5：轻黯石」 line) and the route 9-11 node lines of
maafw.bak.2026.10.12-10.56.34.166.log. The picture names are the real ones from
MaaEnd's debug/on_error; the 10-05 one is recorded to the second only
(归档-1012/今日报错-1005.txt:18, 11:17:28), so its milliseconds are 000.
"""
import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_STATE_DIR=str(TMP / "state"),
                  SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                  WECOM_BOT_URL="", ARK_PHONE_TOPIC="", ARK_LOG_FILE=str(TMP / "relay.log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import ledger_rows, texts  # noqa: E402
from ark_relay.core.config import SERVER_TZ, RunRecord  # noqa: E402
from ark_relay.core.notify import route_of  # noqa: E402
from ark_relay.features.makeup import collect_retry as cr  # noqa: E402
from ark_relay.features.report import report  # noqa: E402
from ark_relay.features.selfcheck import machinecheck as mc  # noqa: E402
from ark_relay.features.verify import collector_maaend as cm, outcome  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures" / "collect-blocked-1005-1012"
ZH = json.loads((Path(__file__).resolve().parent / "fixtures" / "collect-retry-2026-09-11" / "zh_cn.json")
                .read_text(encoding="utf-8"))
R10 = "路线10：重红柱状菌"
PIC = "{}___MapNavigatorObstacleDevice_InteractPost.png"
P1005 = PIC.format("2026.10.05-11.17.28.000")
P1008A = PIC.format("2026.10.08-10.17.01.129")   # the 05-29-15 run's, outside 06-34-21's routes
P1008 = PIC.format("2026.10.08-10.59.41.495")
P1012A = PIC.format("2026.10.12-10.44.55.895")
P1012 = PIC.format("2026.10.12-11.25.16.239")
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def log(name):
    return (FX / name).read_text(encoding="utf-8")


def maaend_dir(*pics):
    d = tmpdir()
    (d / "debug" / "on_error").mkdir(parents=True)
    (d / "locales" / "interface").mkdir(parents=True)
    (d / "locales" / "interface" / "zh_cn.json").write_text(json.dumps(ZH, ensure_ascii=False), encoding="utf-8")
    for p in pics:
        (d / "debug" / "on_error" / p).write_bytes(b"")
    return d


print("[每一趟：出错截图落在路线10 的时段里 → 记成路线10 没采到]")
for name, pics, want in (("MaaEnd-06-39-48.log", [P1005], P1005),
                         ("MaaEnd-06-34-21.log", [P1008A, P1008], P1008),
                         ("MaaEnd-06-04-00.log", [P1012A, P1012], P1012A),
                         ("MaaEnd-06-58-38.log", [P1012A, P1012], P1012)):
    got = cm.blocked_routes(log(name), pics) if hasattr(cm, "blocked_routes") else None
    check(f"{name}: 只有路线10，截图 {want[:23]}", got, {R10: [want]})

print("\n[日报那一行：16/17 条，路线10 撞上「战斗中无法使用」没采到（10-05 那趟）]")
src = tmpdir() / "MaaEnd-06-39-48.log"
src.write_text(log("MaaEnd-06-39-48.log"), encoding="utf-8")
raw = cm.parse_maaend_log(src, maaend_dir(P1005))
check("记下这条没采到", raw.get("maaend_collect_blocked"), [R10])
check("17 条里 16 条算走通", (raw.get("maaend_collect_done"), raw.get("maaend_collect_total")), (16, 17))
fin = datetime(2026, 10, 5, 11, 30, 13)
block = "\n".join(ledger_rows._block({"script": "MaaEnd", "ok": True, "raw": raw}, fin))
line = next((x for x in block.split("；") + block.splitlines() if "自动采集" in x and "走通" in x), "")
check("日报原文", "自动采集 16/17 条走通，撞上「战斗中无法使用」没采到：路线10：重红柱状菌" in block, True)
print("    " + line.strip())
check("日报这句是人话", texts.plain(line), [])

print("\n[半路断掉的那趟（09-11 06-47-30，最后一行是「路线5：轻黯石」）：后来的截图不算它的]")
# on_error keeps pictures for days; refresh_raw re-parses every row of the day at report
# time. A later run's picture (same day 12:30, or the real 10-05/10-08/10-12 ones) used
# to land in the cut-short run's open last window and book 路线5 as not gathered.
later = PIC.format("2026.09.11-12.30.00.000")
cut = log("MaaEnd-06-47-30.log")
check("半路断掉：后面的截图都不认成路线5", cm.blocked_routes(cut, [later, P1005, P1008, P1012A, P1012]), {})
check("…路线5 的时段就停在日志最后一行", cm.route_windows(cut)[-1][1:],
      (datetime(2026, 9, 11, 10, 55, 6, 912000), datetime(2026, 9, 11, 10, 55, 6, 912000)))
in_r4 = PIC.format("2026.09.11-10.53.40.000")
check("…前面的路线照旧能认（10:53:40 落在路线4）", cm.blocked_routes(cut, [in_r4]), {"路线4：纯晶多齿叶": [in_r4]})
src = tmpdir() / "MaaEnd-06-47-30.log"
src.write_text(cut, encoding="utf-8")
raw = cm.parse_maaend_log(src, maaend_dir(later))
check("日报那行不写「撞上…没采到」", raw.get("maaend_collect_blocked"), None)
check("5 条照旧都算走通", (raw.get("maaend_collect_done"), raw.get("maaend_collect_total")), (5, 5))

print("\n[跑完当场的核对：不判失败（不进群），交给关机前补跑；不再算「已重试恢复」]")
text = log("MaaEnd-06-04-00.log") + "\n2026-10-12 10:57:01 INFO  [App] 自动执行任务完成，关闭自身\n"
checks = outcome.maaend_checks(text, [P1012A], own_log=True)
retry = [c for c in checks if c.kind == getattr(outcome, "RETRY", "?")]
check("路线10 交给补跑", [c.label for c in retry],
      [texts.collect_blocked_check(R10)] if hasattr(texts, "collect_blocked_check") else ["?"])
check("没有失败项（这时不进群，补跑结果才定）", [c.label for c in checks if not c.ok], [])
check("不再写成「出错截图 1 张（已重试恢复）」", [c.label for c in checks if "已重试恢复" in c.label], [])
check("说给人听的话是人话", texts.plain(retry[0].label) if retry else ["?"], [])

print("\n[关机前补跑：真实 10-08 那趟（AUTO-MAS 整轮重跑的 06-34-21）补路线10]")


def maybe_run(verdict, failures_before=None, day="2026-10-08"):
    """maybe_run over the real history log and picture; only MXU's part is stubbed.
    Returns (routes handed to the retry, what was sent, the day's stamp)."""
    sd, hist, md = tmpdir(), tmpdir(), maaend_dir(P1008A, P1008)
    (hist / "2026-10-08" / "endfield").mkdir(parents=True)
    (hist / "2026-10-08" / "endfield" / "MaaEnd-06-34-21.log").write_text(log("MaaEnd-06-34-21.log"), encoding="utf-8")
    if failures_before:
        (sd / "collect-retry").mkdir(parents=True)
        (sd / "collect-retry" / "failures.json").write_text(json.dumps(failures_before), encoding="utf-8")
    sent, asked = [], []
    eng = types.SimpleNamespace(
        cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(md), history_dir=str(hist),
                                  automas_dir=None),
        state=types.SimpleNamespace(read_ledger=lambda d: [{"script": "MaaEnd",
                                                            "run_id": "2026-10-08/endfield/MaaEnd-06-34-21"}],
                                    mark_incomplete=lambda *a: True),
        notifier=types.SimpleNamespace(send=lambda t, b, **kw: sent.append((t, b, kw.get("alert", False))) or []),
        _scripts_running=lambda: False)
    saved = (cr.run_retry, cr._locale, cr.restore_master)
    cr.run_retry = lambda md, routes, *a, **k: (asked.append(list(routes)) or {r: verdict for r in routes}, "")
    cr._locale, cr.restore_master = (lambda d: ZH), (lambda cfg: "")
    from ark_relay.features.makeup import makeup  # noqa: PLC0415
    saved_mc = makeup._machinecheck
    makeup._machinecheck = lambda *a, **k: None
    try:
        cr.maybe_run(eng, now=datetime(2026, 10, 8, 12, 0, tzinfo=SERVER_TZ), day=day)
    finally:
        cr.run_retry, cr._locale, cr.restore_master = saved
        makeup._machinecheck = saved_mc
    stamp = sd / "collect-retry" / f"{day}.json"
    return asked, sent, (json.loads(stamp.read_text(encoding="utf-8")) if stamp.exists() else {}), (sd, md)


asked, sent, stamp, (sd, md) = maybe_run(True)
check("补的是路线10（没有「采集失败」那一行也补）", asked, [["AutoCollectRoute10"]])
check("补跑走通：不进群，只进日报", [(t, route_of(t, alert=a)) for t, _, a in sent],
      [(texts.COLLECT_RETRY_OK, "log")])
check("日报那句写了为什么补", report.retry_line(sd, "2026-10-08", md),
      "自动采集补跑：第一趟撞上「战斗中无法使用」没采到：路线10：重红柱状菌；走通 路线10：重红柱状菌")
check("…是人话", texts.plain(report.retry_line(sd, "2026-10-08", md)), [])
asked, sent, stamp, _ = maybe_run(False)
check("补跑还没采到：照旧报群", [(t, a) for t, _, a in sent], [(texts.COLLECT_RETRY_FAILED, True)])
asked, sent, stamp, _ = maybe_run(False, {"AutoCollectRoute10": ["2026-10-07"]})
check("连续两天：照旧按复发报群", [(t, a) for t, _, a in sent], [(texts.COLLECT_RECURRENT, True)])

print("\n[MaaEnd 的路线名里找不到这条：说一次，不每个关机判断都说（每条警告都会进群）]")
import logging  # noqa: E402


class _Warns(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.n = 0

    def emit(self, record):
        self.n += "路线名里找不到" in record.getMessage()


warns = _Warns()
cr.log.addHandler(warns)
no_label = {k: v for k, v in ZH.items() if k != "option.AutoCollectRoute10.label"}
for _ in range(2):
    got = cr.blocked_route_ids(log("MaaEnd-06-34-21.log"), [P1008], no_label)
check("认不出就不补，也不瞎猜", got, {})
check("两次判断只警告一次", warns.n, 1)
cr.log.removeHandler(warns)

print("\n[补跑时又撞上：路线10 走到了 End，但截图在 Start 和 End 之间 → 判没走通]")
fw = log("maafw-2026-10-12-routes9-11.log")
check("只看 End 会判走通（maafw 10:45:39 AutoCollectRoute10End）", cr.judge(fw, ["AutoCollectRoute10"], "10:40:00"),
      {"AutoCollectRoute10": True})
got = cr.retry_blocked(fw, ["AutoCollectRoute10"], "10:40:00", [P1012A, P1012]) \
    if hasattr(cr, "retry_blocked") else None
check("截图 10:44:55 在路线10 的 10:43:58–10:45:39 里", got, {"AutoCollectRoute10": [P1012A]})
check("补跑开始前的截图不算", cr.retry_blocked(fw, ["AutoCollectRoute10"], "10:46:00", [P1012A])
      if hasattr(cr, "retry_blocked") else None, {})

print("\n[上机核对 #29：按截图认，不再按日志里的提示原文（那句话哪份日志都没有）]")
mc.load()
REC = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-58-38", script="MaaEnd", user="endfield",
                started=datetime(2026, 10, 12, 11, 9, 47, tzinfo=SERVER_TZ),
                finished=datetime(2026, 10, 12, 11, 36, 56, tzinfo=SERVER_TZ), ok=True, failed_tasks=[], raw={})


def c29(checks, raw=None, pics=(P1012A, P1012)):
    n = types.SimpleNamespace(sent=[])
    n.send = lambda t, b="", alert=False, **kw: n.sent.append((t, alert)) or []
    n.send_group = lambda t, b="": n.send(t, b, alert=True)
    r = dict(mc.judge(tmpdir(), "run", {"rec": REC, "raw": raw or {}, "log_text": log("MaaEnd-06-58-38.log"),
                                        "maaend_dir": str(maaend_dir(*pics)),
                                        "outcome": None if checks is None else {"checks": checks}},
                      notifier=n, now=datetime(2026, 10, 12, 21, 0, tzinfo=SERVER_TZ))).get("#29")
    if r is not None:
        print(f"    #29 {r.status}: {r.evidence}")
    return r.status if r else None, r.evidence if r else ""


good = outcome.maaend_checks(log("MaaEnd-06-58-38.log"), [P1012])
st, ev = c29(good, {"maaend_collect_total": 17, "maaend_collect_blocked": [R10]})
check("记成没采到、交给补跑：PASS", (st, R10 in ev, P1012 in ev), ("PASS", True, True))
st, ev = c29([outcome.Check("出错截图 1 张（已重试恢复）", True)])
check("核对没记它（改之前的样子）：FAIL", st, "FAIL")
st, ev = c29(good, {"maaend_collect_total": 17})
check("日报那行没写：FAIL", st, "FAIL")
# A failed run is not outcome-checked (AUTO-MAS re-runs it: 10-12 06-04-00, 10-08 05-29-15);
# its daily row is the booking (daysim 10-08 / 10-12 had #29 go red on exactly those).
st, ev = c29(None, {"maaend_collect_total": 17, "maaend_collect_blocked": [R10]})
check("失败的那趟（没做结果核对）：日报记了就 PASS", st, "PASS")
st, ev = c29(None, {"maaend_collect_total": 17})
check("失败的那趟：日报也没记：FAIL", st, "FAIL")

print("\n[边界：同一秒里按毫秒分（截图名、历史日志、maafw.log 都带毫秒），日志和补跑用同一条规矩]")
# 10-12 10:45:39 holds, to the millisecond (maafw.bak.2026.10.12-10.56.34.166.log and
# the history log MaaEnd-06-04-00): AutoCollectRoute10End recognised .488 / acted .489,
# AutoCollectRoute11Start recognised .510 - the moment MaaEnd announces 「路线11：重黯石」,
# which AUTO-MAS stamps .533 - and acted .717. Cut to the second, a picture anywhere in
# that second went to route 11 in the history log (route 10 booked as walked, route 11
# re-run for nothing) and to route 11 or nothing in the retry (Start->End windows).
R11 = "路线11：重黯石"
ms = {k: PIC.format("2026.10.12-10.45.39." + k) for k in ("400", "500", "600")}
check("in_window 是半开区间", [cm.in_window(datetime(2026, 1, 1, 0, 0, s), datetime(2026, 1, 1, 0, 0, 1),
                                            datetime(2026, 1, 1, 0, 0, 2)) for s in (0, 1, 2)]
      if hasattr(cm, "in_window") else None, [False, True, False])
check("截图名的毫秒：MaaFW 不补零，「.93」是 93 毫秒",
      cm.shot_time(PIC.format("2026.10.15-16.39.29.93")), datetime(2026, 10, 15, 16, 39, 29, 93000))
check("截图名的毫秒：.895", cm.shot_time(P1012A), datetime(2026, 10, 12, 10, 44, 55, 895000))
check("截图名只隔一个下划线的也认（2026-10-08 的 AutoCollectRoute1Start）",
      cm.shot_time("2026.10.08-10.01.43.463_AutoCollectRoute1Start.png"), datetime(2026, 10, 8, 10, 1, 43, 463000))
for k, want_log, want_fw in (("400", R10, "AutoCollectRoute10"),   # before End .489 and 路线11 .533
                             ("500", R10, "AutoCollectRoute10"),   # after End, before Route11 is announced
                             ("600", R11, "AutoCollectRoute11")):  # after 路线11 .533 / Route11 .510
    check(f"日志：10:45:39.{k} 算{want_log[:4]}",
          cm.blocked_routes(log("MaaEnd-06-04-00.log"), [ms[k]]), {want_log: [ms[k]]})
    check(f"补跑：10:45:39.{k} 算 {want_fw}（和日志一致）",
          cr.retry_blocked(fw, ["AutoCollectRoute10", "AutoCollectRoute11"], "10:40:00", [ms[k]]),
          {want_fw: [ms[k]]})
# A retry of route 10 alone runs no route after it: its window ends at its End node.
fw10 = "\n".join(x for x in fw.splitlines() if "AutoCollectRoute11" not in x)
check("补跑只补路线10、后面没有路线：时段停在它的 End（10:45:39.489），.500 不算它的",
      cr.retry_blocked(fw10, ["AutoCollectRoute10"], "10:40:00", [ms["400"], ms["500"]]),
      {"AutoCollectRoute10": [ms["400"]]})
# 11:36:55.978 is 06-58-38's 「任务完成: 🧺自动采集」: .900 is still 路线17's, .990 no route's.
END_IN, END_EDGE = PIC.format("2026.10.12-11.36.55.900"), PIC.format("2026.10.12-11.36.55.990")
check("日志：「任务完成: 自动采集」之前 78 毫秒的截图算路线17",
      cm.blocked_routes(log("MaaEnd-06-58-38.log"), [END_IN]), {"路线17：塔罗斯菌": [END_IN]})
check("日志：「任务完成: 自动采集」之后的截图不算任何路线",
      cm.blocked_routes(log("MaaEnd-06-58-38.log"), [END_EDGE]), {})
st, ev = c29(outcome.maaend_checks(log("MaaEnd-06-58-38.log"), [END_EDGE]),
             {"maaend_collect_total": 17}, pics=(END_EDGE,))
check("#29：这张也不算这一趟的（不报「认不出是哪条路线」）", st, None)

print("\n[#29 和跑完当场的核对看同一批截图、同一个时间（截图名里的时间）]")
# The outcome check used to take the round's pictures by file time and #29 by name
# time: a picture whose file time is off (copied, touched later) was #29's and not the
# check's, and #29 then failed 「核对没把它记成没采到」 on a picture the check never saw.
from ark_relay.features.alarm import runchecks, verdict  # noqa: E402

hist = tmpdir() / "MaaEnd-06-58-38.log"
hist.write_text(log("MaaEnd-06-58-38.log"), encoding="utf-8")


def end_to_end(pic, mtime):
    """verdict._verify_outcome over the real history log, then #29 on what it kept."""
    md = maaend_dir(pic)
    os.utime(md / "debug" / "on_error" / pic, (mtime.timestamp(), mtime.timestamp()))
    rec = RunRecord(run_id=REC.run_id, script="MaaEnd", user="endfield", started=REC.started,
                    finished=REC.finished, ok=True, failed_tasks=[], raw={}, log_path=hist)
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=str(md), state_dir=tmpdir()))
    verdict._verify_outcome(eng, rec)
    checked = runchecks._OUTCOME.pop(rec.run_id, None)
    booked = [c.label for c in (checked or {}).get("checks") or [] if c.kind == outcome.RETRY]
    n = types.SimpleNamespace(sent=[])
    n.send = lambda t, b="", alert=False, **kw: n.sent.append((t, alert)) or []
    n.send_group = lambda t, b="": n.send(t, b, alert=True)
    r = dict(mc.judge(tmpdir(), "run", {"rec": rec, "raw": {"maaend_collect_total": 17,
                                                            "maaend_collect_blocked": [R10]},
                                        "log_text": log("MaaEnd-06-58-38.log"), "maaend_dir": str(md),
                                        "outcome": checked},
                      notifier=n, now=datetime(2026, 10, 12, 21, 0, tzinfo=SERVER_TZ))).get("#29")
    return booked, (r.status if r else None)


# P1012 is named 11:25:16 (inside the run); its file written two days later.
booked, st = end_to_end(P1012, datetime(2026, 10, 14, 9, 0, tzinfo=SERVER_TZ))
check("文件时间在这一趟外、名字在里面：核对记了路线10", booked, [texts.collect_blocked_check(R10)])
check("…#29 判的就是这一张：PASS（不再 FAIL「核对没把它记成没采到」）", st, "PASS")
# Named the morning before, its file time inside the run: the run's picture by neither.
old_pic = PIC.format("2026.10.11-11.25.16.239")
booked, st = end_to_end(old_pic, datetime(2026, 10, 12, 11, 25, 16, tzinfo=SERVER_TZ))
check("名字在这一趟外、文件时间在里面：核对不记", booked, [])
check("…#29 也不判", st, None)

print("\n[没跑完的那趟：「界面没卡住」照旧写出那张截图的名字，路线10 只记一次]")
# 06-04-00 as it is: no 「自动执行任务完成」 line (AUTO-MAS re-ran it).
checks = outcome.maaend_checks(log("MaaEnd-06-04-00.log"), [P1012A])
stuck = [c for c in checks if c.label == "界面没卡住"]
check("「MaaEnd 跑完」判没跑完", [c.ok for c in checks if c.label == "MaaEnd 跑完"], [False])
check("「界面没卡住」判失败、写了截图名", [(c.ok, P1012A in c.detail) for c in stuck], [(False, True)])
check("路线10 还是只交给补跑一次", [c.label for c in checks if c.kind == outcome.RETRY],
      [texts.collect_blocked_check(R10)])

print("\nall checks passed" if not fails else f"\nFAILED: {len(fails)}")
sys.exit(1 if fails else 0)
