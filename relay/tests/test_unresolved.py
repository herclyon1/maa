"""A MAA / MaaEnd problem the relay could not fix goes to the group - every time.

From 13:07 to 15:38 on 2026-10-05 such failures went to the daily report only,
and the group heard of a game only after a whole day without a good run
(dayfail.py, now removed). The user, 15:38: 「为啥群里不响？你们不是没处理好吗？
你这样不会错失第一时间修复的那个吗。」 Until 2026-10-06 a shift then rang at most
once, a MaaEnd round short of only 自动采集 / 应急理智加强剂 (engine.SOFT_FAILS)
stayed in the daily report, and runs started by hand at AUTO-MAS and MAA failures
on the update day were never pushed; the user's order of 2026-10-06, 「不论多少次
什么错误都要发」, ended all four, and put in the group as well a failure the make-up
got past, could-not-enter on an official notice and MAA short of sanity. At 05:07
that day he took the make-up that got past it back out of the group: 「报错后自己好了
的，只进日报、不进群。」 Pinned here, against a queue config shaped like AUTO-MAS's own
(早班 09:00 MAA + MaaEnd + OK-WW, 晚班 21:30 MAA):

* 早班 failed -> held for its make-up; the make-up failed too -> an alarm naming
  the game, the shift, what came of the make-up, where it failed and the
  evidence link; another 早班 failure rings again; a 晚班 failure (the day's
  make-up spent) rings for 晚班, and so does the next one;
* the make-up went through -> nothing pushed; the daily report's make-up line says
  「失败过，补跑后走通了」 with where it failed;
* a MAA failure the make-up is not for (it had fought already) -> one alarm,
  with the reason no make-up ran;
* every 「没干完」 rings, a failure of the same shift too; MaaEnd short of only
  自动采集 / 应急理智加强剂 rings like any other, and fails into the make-up path;
* a run started by hand and a MAA failure on the update day ring at once;
* could not enter (official notice), MAA short of sanity and a failure cut short by
  the red button (his own 停一切) ring at once, not held;
* a push that did not go out is tried again on the next tick, and the same
  record is never pushed twice;
* the whole-day alarm is gone.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ark_relay import handle, makeup, outcome, report, texts, unresolved   # noqa: E402
from ark_relay import engine as eng_mod                            # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord          # noqa: E402
from ark_relay.core import State                                   # noqa: E402
from ark_relay.notify import route_of                              # noqa: E402
from ark_relay import machinecheck as _mc                     # noqa: E402
_mc.load()
_mc_real = dict(_mc.CHECKS)   # put back at the end: the coverage pass runs every test file in one process
_mc.CHECKS.clear()   # the alarms themselves are tested here; the machine checks in tests/test_mc_*.py

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def automas_dir(queues) -> Path:
    """An AUTO-MAS config dir: queues = [(name, [times], [script kinds])]."""
    root = tmpdir()
    (root / "config").mkdir()
    paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
    sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
    for k, p in paths.items():
        sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
    qc = {"instances": []}
    for n, (name, times, kinds) in enumerate(queues):
        uid = f"q{n}"
        qc["instances"].append({"uid": uid})
        ts = {"instances": []}
        for i, t in enumerate(times):
            ts[f"t{i}"] = {"Info": {"Enabled": True, "Time": t}}
        items = {"instances": []}
        for i, k in enumerate(kinds):
            items[f"i{i}"] = {"Info": {"ScriptId": f"s-{k}"}}
        qc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                   "SubConfigsInfo": {"TimeSet": ts, "QueueItem": items}}
    (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
    (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
    return root


AUTOMAS = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA"])])
# Today (real clock): makeup.eligible and _flush_pending read today's date.
DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
D = f"{DAY:%Y-%m-%d}"
PAGE = "https://cos.example/run.zip"


def at(hh, mm=0, day=DAY):
    return day.replace(hour=hh, minute=mm)


class Notes:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, title, body="", **kw):
        if self.fail:
            return ["企业微信机器人：发不出去"]
        self.sent.append((title, body, kw.get("alert", False)))
        return []


class Src:
    def fetch(self, seen):
        return []


def build(automas=AUTOMAS, notes=None):
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = automas
    cfg.maa_dir = None
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=notes or Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._unfinished_queues = lambda now, entries: []
    e._deferred_update_busy = lambda: False
    e._verify_outcome = lambda r: None
    e._archive_maaend_evidence = lambda r: None
    e._maintenance_today = lambda game: False
    return e


def ship(eng, rec):
    rec.raw["evidence_page"] = PAGE
    return PAGE


handle._ship_evidence = ship
dispatched = []
makeup._dispatch = lambda script: (dispatched.append(script) or (True, "已开跑"))
makeup._kill_game = lambda: None


def rec(script, started, ok=False, failed=None, raw=None, tag=""):
    user = {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
    return RunRecord(run_id=f"{started:%Y-%m-%d}/{user}/{script}-{started:%H-%M-%S}{tag}", script=script, user=user,
                     started=started, finished=started + timedelta(minutes=20), ok=ok,
                     failed_tasks=list(failed if failed is not None else ([] if ok else ["开始唤醒"])),
                     raw=dict(raw or {}))


def alarms(e):
    return [t for t, _, a in e.notifier.sent if a]


def last_body(e):
    bodies = [b for _, b, a in e.notifier.sent if a]
    return bodies[-1] if bodies else ""


def fail_and_makeup_fails(e, script, started, failed=None):
    """A failure held, its make-up dispatched, the make-up's record failed too."""
    first = rec(script, started, failed=failed)
    handle._handle(e, first)
    e._flush_pending()
    held = (dict(e._pending), len(alarms(e)))
    makeup.maybe_run(e, started + timedelta(hours=1))
    e._flush_pending()
    waiting = dict(e._pending)
    handle._handle(e, rec(script, started + timedelta(hours=1, minutes=1), failed=failed))
    e._flush_pending()
    return held, waiting


print("[哪一班：按 AUTO-MAS 的队列时刻，读不到就按中午前后]")
e = build()
check("09:05 → 早班", unresolved.where(e, rec("MAA", at(9, 5)))[1], "早班")
check("14:00 的补跑也算早班", unresolved.where(e, rec("MAA", at(14)))[1], "早班")
check("21:35 → 晚班", unresolved.where(e, rec("MAA", at(21, 35)))[1], "晚班")
check("班前五分钟开的也算这一班", unresolved.where(e, rec("MAA", at(21, 26)))[1], "晚班")
e = build(automas=None)
check("没配置：11:00 → 早班", unresolved.where(e, rec("MAA", at(11)))[1], "早班")
check("没配置：13:00 → 晚班", unresolved.where(e, rec("MAA", at(13)))[1], "晚班")

print("\n[早班失败 → 补跑也没成 → 进群一次，带游戏、班次、原因、证据包]")
e = build()
held, waiting = fail_and_makeup_fails(e, "MAA", at(9, 5))
check("补跑前压着，不推", (list(held[0]), held[1]), ([("MAA", "arknights")], 0))
check("补跑派下去了，还在等它", list(waiting), [("MAA", "arknights")])
check("一条进群", alarms(e), [texts.unresolved("明日方舟", "早班")])
check("标题进群", route_of(texts.unresolved("明日方舟", "早班"), alert=True), "group")
head = last_body(e).splitlines()[0]
check("头一行", head, f"明日方舟早班没跑成，补跑也没成：卡在 开始唤醒（证据包 {PAGE}）")
check("证据链接只出现一次", last_body(e).count(PAGE), 1)
check("不再压着", dict(e._pending), {})
e._flush_pending()
check("下一轮不再推", len(alarms(e)), 1)
handle._handle(e, rec("MAA", at(9, 50), tag="b"))
e._flush_pending()
check("同一班再失败一次：再推一条", alarms(e), [texts.unresolved("明日方舟", "早班")] * 2)
check("…不再压着", dict(e._pending), {})
handle._handle(e, rec("MAA", at(21, 35), failed=["开始唤醒"]))
e._flush_pending()
check("晚班再失败：推晚班", alarms(e)[2:], [texts.unresolved("明日方舟", "晚班")])
check("晚班那条说补跑一天只有一次", "没补跑：补跑一天只有一次，今天的已经用过了" in last_body(e), True)
handle._handle(e, rec("MAA", at(22, 10), failed=["开始唤醒"]))
e._flush_pending()
check("晚班再来：再推", len(alarms(e)), 4)
e._flush_pending()
check("同一条记录不推两次", len(alarms(e)), 4)

print("\n[终末地找不到母本、补跑没能开跑 → 进群，说补跑为什么没开跑]")
e = build()
fail_and_makeup_fails(e, "MaaEnd", at(10), failed=["基质刷取"])
# No make-up went out, so the second failed record is a failure of its own: it rings too.
check("两条进群（补跑没开跑的那条、后来又失败的那条）", alarms(e), [texts.unresolved("终末地", "早班")] * 2)
check("头一行", ([b for _, b, a in e.notifier.sent if a] or [""])[0].splitlines()[:1],
      [f"终末地早班没跑成，补跑没能开跑（找不到终末地的母本）：卡在 基质刷取（证据包 {PAGE}）"])
check("没有派补跑", makeup.read_marker(e.cfg.state_dir, D)["MaaEnd"]["result"], makeup.GAVE_UP)

print("\n[补跑走通：自己好了，不进群，只进日报（用户 2026-10-06 05:07）]")
e = build()
handle._handle(e, rec("MAA", at(9, 5)))
e._flush_pending()
makeup.maybe_run(e, at(10, 5))
handle._handle(e, rec("MAA", at(10, 6), ok=True))
e._flush_pending()
check("补跑记成走通", makeup.read_marker(e.cfg.state_dir, D)["MAA"]["result"], makeup.OK)
check("什么都没推（群、Server酱都没有）", e.notifier.sent, [])
check("日报的补跑那一行说失败过、补跑后走通了",
      report.makeup_line(e.cfg.state_dir, D), "补跑：明日方舟 整个 MAA → 失败过，补跑后走通了（原来失败于：开始唤醒）")
check("不再压着", (dict(e._pending), dict(e._recovered)), ({}, {}))
e._flush_pending()
check("下一轮也不推", e.notifier.sent, [])

print("\n[不符合补跑条件的明日方舟失败（打过仗）：进群一次，写为什么没补跑]")
e = build()
handle._handle(e, rec("MAA", at(9, 5), raw={"sanity_spent": 120}))
e._flush_pending()
makeup.maybe_run(e, at(10, 5))
check("没派补跑", makeup.read_marker(e.cfg.state_dir, D)["MAA"]["result"], makeup.GAVE_UP)
e._flush_pending()
check("一条进群", alarms(e), [texts.unresolved("明日方舟", "早班")])
check("写了没补跑的原因", "没补跑：这一轮已经开始干活（花过理智），再跑一遍会再吃一份理智药" in last_body(e), True)

print("\n[派不下去，次数用完：进群一次，说补跑没能开跑]")
e = build()
handle._handle(e, rec("MAA", at(9, 5)))
makeup._dispatch = lambda script: (False, "AUTO-MAS 没回话")
for i in range(makeup.MAX_TRIES):
    e._flush_pending()
    makeup.maybe_run(e, at(10, 5 + 3 * i))
makeup._dispatch = lambda script: (dispatched.append(script) or (True, "已开跑"))
e._flush_pending()
check("一条进群", alarms(e), [texts.unresolved("明日方舟", "早班")])
check("说补跑没能开跑", "补跑没能开跑（AUTO-MAS 没回话）" in last_body(e), True)

print("\n[没干完：每次都进群，同一班的失败也照报]")
e = build()
e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：日志里没有换班"
handle._handle(e, rec("MAA", at(9, 5), ok=True))
check("一条进群", alarms(e), [texts.unresolved_undone("明日方舟", "早班")])
check("头一行", last_body(e).splitlines()[0],
      f"明日方舟早班跑完了但没干完：基建换班，这一类不补跑（证据包 {PAGE}）")
check("账本记了没干完", bool(e.state.read_ledger(D)[0].get("incomplete")), True)
e._verify_outcome = lambda r: None
fail_and_makeup_fails(e, "MAA", at(9, 40))
check("同一班后来失败、补跑也没成：照报", alarms(e),
      [texts.unresolved_undone("明日方舟", "早班"), texts.unresolved("明日方舟", "早班")])
e = build()
fail_and_makeup_fails(e, "MAA", at(9, 5))
e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：日志里没有换班"
handle._handle(e, rec("MAA", at(11, 30), ok=True))
check("先失败已报过，同一班再没干完：照报", alarms(e),
      [texts.unresolved("明日方舟", "早班"), texts.unresolved_undone("明日方舟", "早班")])
handle._handle(e, rec("MAA", at(21, 35), ok=True))
check("晚班没干完：再报", alarms(e)[2:], [texts.unresolved_undone("明日方舟", "晚班")])

print("\n[终末地只差自动采集 / 应急理智加强剂：照样进群]")
e = build()
e._verify_outcome = lambda r: ("MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n"
                               "· 自动采集 真的走了路线：自动采集 38 秒就报「任务完成」，日志里没有走了路线的痕迹\n干成的：MaaEnd 跑完")
handle._handle(e, rec("MaaEnd", at(9, 5), ok=True))
check("没干完只差自动采集：进群", alarms(e), [texts.unresolved_undone("终末地", "早班")])
check("头一行写出自动采集", last_body(e).startswith("终末地早班跑完了但没干完：自动采集"), True)
e._verify_outcome = lambda r: "MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n· 每个任务都收了尾：开了没收尾：🧺自动采集"
handle._handle(e, rec("MaaEnd", at(9, 30), ok=True))
check("只有自动采集没收尾：也进群", len(alarms(e)), 2)
e._verify_outcome = lambda r: None
handle._handle(e, rec("MaaEnd", at(9, 50), failed=["自动采集", "应急理智加强剂"]))
check("失败只在自动采集 / 应急理智加强剂：压着等补跑，不丢", list(e._pending), [("MaaEnd", "endfield")])
e._flush_pending()
makeup.maybe_run(e, at(10, 30))
e._flush_pending()
check("补跑之后没成：进群", alarms(e)[2:], [texts.unresolved("终末地", "早班")])
check("写了卡在哪", "卡在 自动采集、应急理智加强剂" in last_body(e), True)
for only in ("应急理智加强剂", "自动采集"):
    e = build()
    handle._handle(e, rec("MaaEnd", at(9, 50), failed=[only]))
    e._flush_pending()
    makeup.maybe_run(e, at(10, 30))
    e._flush_pending()
    check(f"只有「{only}」失败：进群", alarms(e), [texts.unresolved("终末地", "早班")])
check("SOFT_FAILS 没了", hasattr(e, "SOFT_FAILS") or hasattr(unresolved, "soft_only"), False)

print("\n[进不了游戏、理智不够、手动开的、更新日、红按钮停的都响]")
e = build()
# 「进不了游戏」needs official evidence (handle._confirm_unreachable); here the
# update notice. Without it the shape alone rings: test_unreachable_evidence.py.
real_hint = handle.efstatus.update_hint
handle.efstatus.update_hint = lambda now=None, fetch=None: "官方公告：今天 10:00 「雪凇幽梦」版本更新"
handle._handle(e, rec("MaaEnd", at(9, 5), raw={"maaend_unreachable_shape": True}))
handle.efstatus.update_hint = real_hint
e._flush_pending()
check("进不了游戏（有更新公告）：进群", alarms(e), [texts.cant_enter("MaaEnd")])
check("…写着那条官方公告", "官方依据：官方公告：今天 10:00 「雪凇幽梦」版本更新" in last_body(e), True)
e = build()
e._maintenance_today = lambda game: True
handle._handle(e, rec("MAA", at(9, 5)))
check("更新日：马上进群，不压着、不补跑", (alarms(e), dict(e._pending)), ([texts.failed("MAA")], {}))
check("更新日：头一行说是更新日", last_body(e).splitlines()[:1], [getattr(texts, "UPDATE_DAY_NOTE", "-")])
check("更新日：带证据包", PAGE in last_body(e), True)
e._flush_pending()
check("更新日：下一轮不重推", len(alarms(e)), 1)
e = build()
real_short = outcome.maa_sanity_short
outcome.maa_sanity_short = lambda text: {"have": 17, "cost": 25}
handle._handle(e, rec("MAA", at(9, 5)))
e._flush_pending()
check("理智不够：马上进群、不压着", (alarms(e), dict(e._pending)), ([getattr(texts, "MAA_SANITY_SHORT", "-")], {}))
check("…写着两个数", "理智 17" in last_body(e) and "一次要 25" in last_body(e), True)
handle._handle(e, rec("MAA", at(9, 5)))      # the same record replayed
check("…同一条记录不推两次", (len(alarms(e)), dict(e._pending)), (1, {}))
outcome.maa_sanity_short = real_short
e = build()
real_hand = handle._hand_started
handle._hand_started = lambda eng, r: "手动开始"
handle._handle(e, rec("MAA", at(9, 5)))
check("手动开的失败：马上进群，不压着", (alarms(e), dict(e._pending)), ([texts.failed("MAA")], {}))
check("…头一行说是手动开的", last_body(e).splitlines()[:1], [getattr(texts, "HAND_STARTED_NOTE", "-")])
e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：x"
handle._handle(e, rec("MAA", at(9, 40), ok=True))
handle._hand_started = real_hand
e._flush_pending()
check("手动开的没干完：也进群", alarms(e), [texts.failed("MAA"), texts.ROUND_INCOMPLETE])
check("…说是手动开的", last_body(e).startswith(getattr(texts, "HAND_STARTED_NOTE", "-")), True)
check("不补跑（没派）", makeup.read_marker(e.cfg.state_dir, D).get("MAA"), None)
e = build()
handle._handle(e, rec("MAA", at(9, 5), raw={"manual_stop": "停一切"}))
e._flush_pending()
# da99a04d (2026-10-06): a failure cut short by 停一切 is pushed, saying so - it did not recover.
check("红按钮停的失败：进群，不压着", (alarms(e), dict(e._pending)), ([texts.failed("MAA")], {}))
check("…说是停一切停掉的", last_body(e).startswith("这一趟是停一切停掉的（停一切）"), True)

print("\n[推不出去：留着，下一轮再推]")
notes = Notes(fail=True)
e = build(notes=notes)
fail_and_makeup_fails(e, "MAA", at(9, 5))
check("推不出去：还压着", list(e._pending), [("MAA", "arknights")])
check("…没记成已报", e._already_alerted(D, unresolved.alert_key(e._pending[("MAA", "arknights")])), False)
notes.fail = False
e._flush_pending()
check("下一轮推出去一条", alarms(e), [texts.unresolved("明日方舟", "早班")])
check("推出去了才放下", dict(e._pending), {})
notes = Notes(fail=True)
e = build(notes=notes)
e._verify_outcome = lambda r: "MAA 这一轮有 1 项没干成，但它自己没报错：\n· 基建换班：x"
handle._handle(e, rec("MAA", at(9, 5), ok=True))
check("没干完推不出去：留着", len(e._unsent_unresolved), 1)
notes.fail = False
e._flush_pending()
check("下一轮推出去", alarms(e), [texts.unresolved_undone("明日方舟", "早班")])
check("推出去就不再留", e._unsent_unresolved, [])
e._flush_pending()
check("不重复推", len(alarms(e)), 1)

print("\n[程序说做完了但没证据：一轮跑完、重试也没补上证据，进群一次（用户 10-08 13:31「这个为什么不报警」）]")
GIFT = {"tasks_done": ["赠送干员礼物", "装备制造"],
        "tasks_evidence": {"赠送干员礼物": "", "装备制造": "正在检查画面，提示登出账号是正常现象"}}
e = build()
handle._handle(e, rec("MaaEnd", at(9, 5), ok=True, raw=dict(GIFT)))
title = texts.unverified_alarm("终末地", "早班", 1)
check("终末地 1 项没证据：进群", alarms(e), [title])
check("标题走群", route_of(title, alert=True), "group")
check("头一行写出哪一项、为什么不算、证据包", last_body(e).splitlines()[0],
      "终末地早班：赠送干员礼物 程序说做完了，但游戏里拿不出证据（日志里没有游戏回显，也没有任务结束的截图），"
      f"不算完成，要人去看（证据包 {PAGE}）")
handle._handle(e, rec("MaaEnd", at(9, 40), ok=True, raw=dict(GIFT)))
check("同一天同样这几项又没证据：不重推", len(alarms(e)), 1)
e = build()
handle._handle(e, rec("MaaEnd", at(9, 5), ok=True, raw=dict(GIFT, tasks_shot=["赠送干员礼物"])))
check("有任务结束截图就是证据：不推", alarms(e), [])
e = build()
handle._handle(e, rec("MaaEnd", at(9, 5), failed=["基建任务"], raw=dict(GIFT)))
handle._handle(e, rec("MaaEnd", at(9, 40), ok=True,
                      raw={"tasks_done": ["赠送干员礼物"], "tasks_evidence": {"赠送干员礼物": "获得 物品"}}))
e._flush_pending()
check("前一趟没证据、重试那趟补上了：不推", alarms(e), [])
e = build()
handle._handle(e, rec("MAA", at(9, 5), ok=True, raw={"annihilation": "Annihilation"}))
check("明日方舟剿灭没有进度行：进群", alarms(e), [texts.unverified_alarm("明日方舟", "早班", 1)])
check("写出剿灭和原因", "剿灭 程序说做完了" in last_body(e) and "剿灭模式 x/y" in last_body(e), True)
e = build()
handle._handle(e, rec("MAA", at(9, 5), ok=True, raw={"annihilation": "Annihilation", "maa_sanity_short": True}))
check("理智不够没打剿灭是正常状态：不推", alarms(e), [])
e = build()
handle._handle(e, rec("MAA", at(9, 5), ok=True,
                      raw={"annihilation": "Annihilation", "annihilation_progress": "400/400"}))
check("剿灭有进度行：不推", alarms(e), [])
e = build()
handle._handle(e, rec("OK-WW", at(9, 5), ok=True, raw={"okww_steps": ["周常乐园（没读到做完，不算完成）"]}))
check("鸣潮一步没读到做完：进群", alarms(e), [texts.unverified_alarm("鸣潮", "早班", 1)])

print("\n[send 自己拼去重的键：一种报警 + 一条记录（2026-10-06 之前调用方拼好了递进来，看不出是不是一条记录）]")
e = build()
check("键是「种类|记录号」，和 state.json 里旧的标记一样", unresolved.alert_key(rec("MAA", at(9, 5))),
      f"未解决|{rec('MAA', at(9, 5)).run_id}")
check("推出去了", unresolved.send(e, D, "手动", "rid-1", "t1", "b1"), True)
check("记的是「手动|rid-1」", e._already_alerted(D, "手动|rid-1"), True)
check("同一条记录再来一遍：不重推，算推过", (unresolved.send(e, D, "手动", "rid-1", "t1", "b1"), len(alarms(e))), (True, 1))
check("另一条记录：照推", (unresolved.send(e, D, "手动", "rid-2", "t2", "b2"), len(alarms(e))), (True, 2))
check("同一条记录的另一种报警：照推", (unresolved.send(e, D, "重启", "rid-1", "t3", "b3"), len(alarms(e))), (True, 3))

print("\n[整天报警没了]")
check("dayfail.py 删了", (ROOT / "ark_relay" / "dayfail.py").exists(), False)
src = (ROOT / "ark_relay" / "engine.py").read_text(encoding="utf-8")
check("引擎每轮没有「全天没成」这一步", "全天没成" in src or "dayfail" in src, False)
check("文案里没有「一整天一趟都没跑成」", any("一整天" in s for s in texts.samples()), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
_mc.CHECKS.update(_mc_real)
sys.exit(1 if fails else 0)
