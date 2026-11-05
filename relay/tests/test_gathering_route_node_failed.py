"""A gathering route whose own Goto / Start node fails is booked as failed, and gets no whole make-up.

2026-11-05 早班 (Beijing): MaaEnd's 10:22 attempt finished every task but one route, 协议纹石（路线2）,
whose Goto node failed (maafw.log 11:20:43 Node.PipelineNode.Failed AutoCollectWulingProtocolith2Goto).
The 11:26 attempt was logged out mid-run (「登录认证已失效」 at 11:43:57) and every route after that failed
at its Start node within 20 s. Such a failure writes no 「…采集失败」 line: the AUTO-MAS history log has
「FailureCollector subtask failed task=AutoCollectValleyIVPinkBolete1Start」 instead, and the relay booked
that attempt as 17 of 17 routes walked; the live watch said 「日志里没有点名哪条路线」. Then the relay's
make-up ran the whole script a fourth time although the first attempt had done everything else.

Checked here, with the line shapes of that morning:
* collector_maaend books the routes the failure collector named as failed - by item through MaaEnd's
  locale, else by the 「采集…」 line before the failure line - and leaves a log without them as before;
* collect_retry.failed_routes returns them for the per-route retry, route_label gives v2.36 routes their
  Chinese words, and judge counts a route's own failed node as a failure;
* collect_watch's live pattern names the route in all three shapes;
* makeup.maaend_round_only_gathering: no whole make-up when an attempt of the round ran to its end
  with gathering the only unfinished task; a make-up as before otherwise.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import texts
from ark_relay.features.makeup import collect_retry as cr
from ark_relay.features.makeup import makeup
from ark_relay.features.run import collect_watch
from ark_relay.features.verify import collector_maaend as cm

FIX = Path(__file__).parent / "fixtures" / "maaend-2026-10-29"
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


def collector_line(t, node):
    return (f"[2026-11-05 {t}.737] 2026-11-05T{t}+08:00 ERR github.com/MaaXYZ/MaaEnd/agent/go-service/"
            f"common/failurecollector/action.go:60 > FailureCollector subtask failed task={node}")


# The 11:26 attempt's gathering, as its AUTO-MAS history log has it (two routes walked, then the
# logout; 协议纹石（路线2） is a Wuling route the 10-29 locale does not have).
LOG = "\n".join([
    "[2026-11-05 11:39:04.400] 任务开始: 🧺自动采集",
    "[2026-11-05 11:39:40.100] 采集纯晶多齿叶",
    "[2026-11-05 11:41:30.200] 采集轻黯石",
    "[2026-11-05 11:43:08.300] 采集轻红柱状菌",
    "[2026-11-05 11:43:56.522] [2026-11-05 11:43:56.497][ERR][Px21872][Tx56783][navigation_state_machine.cpp][L297]"
    "[mapnavigator::NavigationStateMachine::failNavigation] Localization lost beyond timeout (re-acquire failed; "
    "likely shoved off-route into another zone); terminating navigation.",
    collector_line("11:43:56", "AutoCollectValleyIVPinkBolete1Start"),
    "[2026-11-05 11:43:56.884] 采集中黯石",
    collector_line("11:50:06", "AutoCollectValleyIVAuronyx1Start"),
    "[2026-11-05 11:53:34.367] 采集协议纹石（路线2）",
    collector_line("11:53:54", "AutoCollectWulingProtocolith2Start"),
    "[2026-11-05 11:54:57.226] 任务失败: 🧺自动采集",
    "[2026-11-05 11:54:57.394] 任务开始: 📅日常奖励领取",
]) + "\n"

print("[collector_maaend: the routes the failure collector named]")
check("route ids in order", cm.collector_failed_routes(LOG),
      ["AutoCollectValleyIVPinkBolete1", "AutoCollectValleyIVAuronyx1", "AutoCollectWulingProtocolith2"])
with tempfile.TemporaryDirectory() as d:
    maaend = Path(d) / "maaend"
    (maaend / "locales" / "interface").mkdir(parents=True)
    (maaend / "locales" / "interface" / "zh_cn.json").write_bytes(
        (FIX / "locales" / "interface" / "zh_cn.json").read_bytes())
    log = Path(d) / "0.log"
    log.write_text(LOG, encoding="utf-8")
    items = cm.route_items(maaend)
    check("locale: route id -> item", items.get("AutoCollectValleyIVPinkBolete1"), "轻红柱状菌")
    out = cm.parse_maaend_log(log, maaend)
    check("booked failed: by locale, the Wuling one by its line", out.get("maaend_collect_failed"),
          ["采集轻红柱状菌", "采集中黯石", "采集协议纹石（路线2）"])
    check("walked 2 of 5, not 5 of 5", (out.get("maaend_collect_done"), out.get("maaend_collect_total")), (2, 5))
    check("ids kept for the record", out.get("maaend_collect_failed_ids"),
          ["AutoCollectValleyIVPinkBolete1", "AutoCollectValleyIVAuronyx1", "AutoCollectWulingProtocolith2"])
    out0 = cm.parse_maaend_log(log, None)
    check("no locale: every one by the line before it", out0.get("maaend_collect_failed"),
          ["采集轻红柱状菌", "采集中黯石", "采集协议纹石（路线2）"])
    plain = Path(d) / "1.log"
    plain.write_text("\n".join(l for l in LOG.splitlines() if "FailureCollector" not in l) + "\n", encoding="utf-8")
    out1 = cm.parse_maaend_log(plain, maaend)
    check("without failure lines: as before", (out1.get("maaend_collect_failed"), out1.get("maaend_collect_done"),
                                               out1.get("maaend_collect_total")), (None, 5, 5))

    print("[collect_retry: the per-route retry gets them]")
    zh = cr._locale(maaend)
    check("failed_routes", cr.failed_routes(LOG, cr.failed_labels_from_locale(zh)),
          ["AutoCollectValleyIVPinkBolete1", "AutoCollectValleyIVAuronyx1", "AutoCollectWulingProtocolith2"])
    with_line = LOG.replace("[2026-11-05 11:41:30.200] 采集轻黯石",
                            "[2026-11-05 11:41:30.200] 采集轻黯石\n[2026-11-05 11:42:00.000] 轻黯石采集失败")
    check("a 「…采集失败」 line first, then the collector's", cr.failed_routes(with_line, cr.failed_labels_from_locale(zh))[:2],
          ["AutoCollectValleyIVKalkonyx1", "AutoCollectValleyIVPinkBolete1"])
    print("[collect_retry: routes walked earlier today are not retried]")
    by_label = cr.route_ids_by_label(zh)
    check("walked: the two routes before the logout", cr.walked_routes(LOG, by_label, cr.failed_labels_from_locale(zh)),
          {"AutoCollectValleyIVChrysodendra1", "AutoCollectValleyIVKalkonyx1"})
    cut = "\n".join(LOG.splitlines()[:3]) + "\n"
    check("a run cut while a route was open: that route not counted", cr.walked_routes(cut, by_label),
          {"AutoCollectValleyIVChrysodendra1"})
    summary = ("[2026-11-05 11:00:00.000] 采集轻黯石\n[2026-11-05 11:05:00.000] 采集纯晶多齿叶\n"
               "[2026-11-05 11:06:00.000] 轻黯石采集失败\n[2026-11-05 11:06:01.000] 任务失败: 🧺自动采集\n")
    check("a 「…采集失败」 summary at the end fails that route by name, not the last one",
          cr.walked_routes(summary, by_label, cr.failed_labels_from_locale(zh)), {"AutoCollectValleyIVChrysodendra1"})
    hist = Path(d) / "history"
    hist.mkdir()
    (hist / "r1.log").write_text("\n".join(LOG.splitlines()[:3] + ["[2026-11-05 10:50:00.000] 采集轻红柱状菌",
                                                                    "[2026-11-05 11:00:00.000] 任务完成: 🧺自动采集"]),
                                 encoding="utf-8")
    (hist / "r2.log").write_text(LOG, encoding="utf-8")
    entries = [{"script": "MaaEnd", "run_id": "r1"}, {"script": "MaaEnd", "run_id": "r2"}]
    check("walked today: the first run's routes count for the second run's failures",
          cr.walked_today(entries, hist, by_label, None, zh),
          {"AutoCollectValleyIVChrysodendra1", "AutoCollectValleyIVKalkonyx1", "AutoCollectValleyIVPinkBolete1"})
    check("route_label: a v2.36 route in Chinese", cr.route_label("AutoCollectValleyIVPinkBolete1", zh), "采集轻红柱状菌")
    check("route_label: unknown stays the id", cr.route_label("AutoCollectWulingProtocolith2", zh),
          "AutoCollectWulingProtocolith2")

FW = "\n".join([
    "[2026-11-05 13:01:10.100][INF][Px1][Tx1][EventDispatcher.cpp][L1][MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! "
    "[handle=true] [msg=Node.Action.Starting] [details={\"action_id\":1,\"name\":\"AutoCollectValleyIVChrysodendra1End\",\"task_id\":2}]",
    "[2026-11-05 13:02:20.702][INF][Px1][Tx1][EventDispatcher.cpp][L1][MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! "
    "[handle=true] [msg=Node.PipelineNode.Failed] [details={\"focus\":null,\"name\":\"AutoCollectWulingProtocolith2Goto\",\"node_id\":3}]",
    "[2026-11-05 13:03:00.000][INF][Px1][Tx1][EventDispatcher.cpp][L1][MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! "
    "[handle=true] [msg=Node.PipelineNode.Failed] [details={\"focus\":null,\"name\":\"AutoCollectAfterStashBackpack\",\"node_id\":4}]",
])
def watched(line):
    m = collect_watch._ROUTE_FAILED.search(line)
    return (m.group(1) or m.group(2)) if m else None


print("[the real 11-05 lines (fixtures/maaend-2026-11-05)]")
REAL = Path(__file__).parent / "fixtures" / "maaend-2026-11-05"
real_hist = (REAL / "history-MaaEnd-07-24-54-gathering.log").read_text(encoding="utf-8")
check("15 routes named by the failure collector", len(cm.collector_failed_routes(real_hist)), 15)
with tempfile.TemporaryDirectory() as d2:
    lp = Path(d2) / "0.log"
    lp.write_text(real_hist, encoding="utf-8")
    real_out = cm.parse_maaend_log(lp, None)
    check("the logged-out attempt: 2 of 17 walked, not 17 of 17",
          (real_out.get("maaend_collect_done"), real_out.get("maaend_collect_total")), (2, 17))
    check("its first failed route is the one the logout hit", (real_out.get("maaend_collect_failed") or [""])[0], "采集轻红柱状菌")
real_fw = (REAL / "maafw-route-node-failed.log").read_text(encoding="utf-8")
check("judge on the real maafw lines", cr.judge(real_fw, ["AutoCollectWulingProtocolith2", "AutoCollectValleyIVPinkBolete1"], "11:00:00"),
      {"AutoCollectWulingProtocolith2": False, "AutoCollectValleyIVPinkBolete1": False})
check("the live watch on the real lines", [watched(x) for x in real_fw.splitlines()],
      ["WulingProtocolith2", None, "ValleyIVPinkBolete1", None])

print("[collect_retry.judge: a route's own failed node]")
check("End passes, a failed Goto fails, a non-route node is ignored",
      cr.judge(FW, ["AutoCollectValleyIVChrysodendra1", "AutoCollectWulingProtocolith2", "AutoCollectValleyIVAuronyx1"], "13:00:00"),
      {"AutoCollectValleyIVChrysodendra1": True, "AutoCollectWulingProtocolith2": False, "AutoCollectValleyIVAuronyx1": None})
check("node_lines quotes the failed node", "AutoCollectWulingProtocolith2Goto" in
      cr.node_lines(FW, ["AutoCollectWulingProtocolith2"], "13:00:00").get("AutoCollectWulingProtocolith2", ""), True)

print("[collect_watch: the live line names the route]")


check("a failed Goto node", watched(FW.splitlines()[1]), "WulingProtocolith2")
check("the old Failed node", watched('[msg=Node.Action.Starting] [details={"name":"AutoCollectRoute10Failed"}]'), "Route10")
check("v2.36's __…Failed node", watched('[msg=Node.Action.Starting] [details={"name":"__AutoCollectValleyIVChrysodendra1Failed"}]'),
      "ValleyIVChrysodendra1")
check("not a route: none", watched(FW.splitlines()[2]), None)
check("ResetFailures is not a failure", watched('[msg=Node.Action.Starting] [details={"name":"AutoCollectResetFailures"}]'), None)

print("[makeup: no whole make-up when one attempt left only gathering]")
ROWS = [
    {"script": "MaaEnd", "user": "endfield", "run_id": "MaaEnd-06-22-52", "started": "2026-11-05T10:24:37+08:00", "ok": False,
     "raw": {"maaend_result": "MaaEnd 部分任务执行失败: 🧺自动采集"}},
    {"script": "MaaEnd", "user": "endfield", "run_id": "MaaEnd-07-24-54", "started": "2026-11-05T11:26:30+08:00", "ok": False,
     "raw": {"maaend_result": "MaaEnd 部分任务执行失败: 🧺自动采集、📅日常奖励领取"}},
    {"script": "MaaEnd", "user": "endfield", "run_id": "MaaEnd-08-01-16", "started": "2026-11-05T12:02:51+08:00", "ok": False,
     "raw": {"maaend_result": "运行超过 120 分钟，已终止"}},
]


def ledger_of(rows):
    return lambda day: list(rows)


why = makeup.maaend_round_only_gathering(ledger_of(ROWS), ROWS[2])
check("the 11-05 round: no whole make-up, because of the 10:24 attempt", why, texts.makeup_only_gathering("10:24"))
check("in plain words", texts.plain(why), [])
check("a round whose complete attempts had more than gathering left: make-up as before",
      makeup.maaend_round_only_gathering(ledger_of(ROWS[1:]), ROWS[2]), "")
earlier_ok = [dict(ROWS[0], ok=True)] + ROWS[1:]
check("an ok row ends the round: an earlier round's attempt does not count",
      makeup.maaend_round_only_gathering(ledger_of(earlier_ok), ROWS[2]), "")
other_user = [dict(ROWS[0], user="someone")] + ROWS[1:]
check("another account's attempt does not count", makeup.maaend_round_only_gathering(ledger_of(other_user), ROWS[2]), "")


def broken(day):
    raise OSError("unreadable")


check("an unreadable ledger: make-up as before", makeup.maaend_round_only_gathering(broken, ROWS[2]), "")
check("the held attempt itself left only gathering", makeup.maaend_round_only_gathering(ledger_of(ROWS[:1]), ROWS[0]),
      texts.makeup_only_gathering("10:24"))

print("all checks passed" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
