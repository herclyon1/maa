"""An ERROR line in a successful round's game log reaches the group unless it is on the list.

On 2026-09-29 OK-WW logged 「can not battle pass, maybe ended」 in a round AUTO-MAS booked as
a success; the battle-pass reward was not claimed and the relay said nothing. The user forbade that on
2026-10-11 17:43 (Tokyo; his words are in relay/USER-SWITCHES.txt's header).

Checked here:
* every entry of features/verify/gamelog_errors.txt has the shape `script | regex |
  verdict: recovered - why | source`, a why that does not call its cause unknown, a source,
  and a real line from the machine (SAMPLES below, copied from D:\\ark\\automas\\history,
  2026-09-27..10-11) that it matches - no dead entry, no entry nobody checked;
* `not-a-fault` only for entries on NOT_A_FAULT below (editing this test is the only way in);
* the lines that were real failures in successful rounds (MUST_PUSH) match no entry;
* check_round pushes one alarm per round (its own title and plain body) with the raw lines
  in a technical-log red item, and nothing for a log with only listed lines;
* handle's success path calls it.
"""
import logging
import os
import sys
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="")
RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))
from ark_relay.core import techlog, texts  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.features.verify import gamelog_errors as ge  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


# One real line per known shape, as the machine wrote it.
SAMPLES = {
    "MAA": [
        "[2026-09-27 09:00:55.117][ERR][AutoStart]              <2> Failed to set startup: No value exists with that name.",
        "[2026-10-02 21:46:55.570][ERR][TaskQueueViewModel]     <2> 识别错误, 已返回",
    ],
    "MaaEnd": [
        "[2026-10-21 09:55:08.002] [2026-10-21 09:55:07.977][ERR][Px6540][Tx4086][navigation_state_machine.cpp][L2696][mapnavigator::NavigationStateMachine::FailNavigation] Off-route with no route progress past the wedge timeout; terminating so the pipeline can retry. [current_distance=9.953856] [yaw_error=59.709557] [stalled_ms=0]",
        "[2026-09-27 09:33:23.006][ERR][Px23408][Tx41825][TemplateMatcher.cpp][L54][MaaNS::VisionNS::TemplateMatcher::template_match] __CancelButtonType1Icon templ size is too large [image=[258,20,16]] [templ=[29,29,16]]",
        "[2026-09-27 09:43:52.582][ERR][Px23408][Tx41825][Vision/VisionUtils.hpp][L349][MaaNS::VisionNS::correct_roi] roi is out of range [image.size()=[1280,720]] [res=[67,722,143,40]]",
        "[2026-09-27 09:44:13.860][ERR][Px23408][Tx41825][RuntimeCache.cpp][L66][MaaNS::RuntimeCache::set_reco_detail] uid is invalid ",
        "[2026-09-27 09:33:24.290][ERR][Px23408][Tx41825][ActionHelper.cpp][L30][MaaNS::TaskNS::ActionHelper::wait_freezes] failed to get target rect for wait_freezes [noti_ctx.name=__SceneImageCheckFinishExitSuccess]",
        "[2026-09-28 11:09:53.122][ERR][Px9932][Tx43027][PipelineTask.cpp][L292][MaaNS::TaskNS::PipelineTask::recognize_list] get_pipeline_data failed, node not exist [node={\"anchor\":true,\"jump_back\":true,\"name\":\"__ScenePrivateMapSwipeToStep0Anchor\"}]",
    ],
    "OK-WW": [
        "2026-09-27 09:17:33,335 ERROR ok.core.start_controller start_controller:Game window is not connected BitBlt_True_1920x1080",
        "2026-09-27 09:17:33,339 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮   is not connected, please select the game window.",
        "2026-09-29 09:20:35,119 ERROR ok.core.start_controller start_controller:waiting for game to start error Selected capture method is not supported by the game or your system!",
        "2026-09-27 09:18:09,708 ERROR TaskExecutor bitblt_utils:capture_by_bitblt exception: BitBlt failed",
        "2026-10-05 09:41:00,433 ERROR TaskExecutor post_message:PostMessage error 590386: (1400, 'PostMessage', '无效的窗口句柄。')",
        "2026-09-27 09:21:24,985 ERROR TaskExecutor CombatCheck:target_enemy failed, try recheck break out of combat",
        "2026-09-27 09:21:24,986 ERROR TaskExecutor BaseCombatTask:combat check not in combat",
        "2026-09-30 18:01:49,174 ERROR TaskExecutor Denia:clicked liberation but no effect",
        "2026-10-10 09:06:42,695 ERROR TaskExecutor BaseCombatTask:not in_team while switching",
        "2026-10-15 09:20:31,117 ERROR ok.core.start_controller DeviceManager:refresh error Traceback (most recent call last):",
        "2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:check_device_error exception: 'NoneType' object is not subscriptable Traceback (most recent call last):",
        "2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:waiting for game to start error 'NoneType' object is not subscriptable",
    ],
}
# The ERROR kinds of one whole successful round, each line as the machine wrote it (trailing
# spaces kept; a few INFO and traceback lines between them, the whole log is in the OK-WW
# corpus): 2026-10-15/wuwa/OK-WW-05-19-01, alarm f7a4bb6a. The first three were unlisted and
# pushed; the round logged in at 09:20:33 and ended with 「Daily Task Completed」.
ROUND_1015 = """\
2026-10-15 09:20:31,117 ERROR ok.core.start_controller DeviceManager:refresh error Traceback (most recent call last):
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\ok\\util\\window.py", line 343, in is_match
pywintypes.error: (1400, 'GetClassName', '无效的窗口句柄。')
2026-10-15 09:20:31,118 INFO ok.core.start_controller start_controller:start_device: None
2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:check_device_error exception: 'NoneType' object is not subscriptable Traceback (most recent call last):
TypeError: 'NoneType' object is not subscriptable
2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:waiting for game to start error 'NoneType' object is not subscriptable 
2026-10-15 09:20:33,135 ERROR ok.core.start_controller start_controller:waiting for game to start error Selected capture method is not supported by the game or your system! 
2026-10-15 09:22:59,239 ERROR TaskExecutor CombatCheck:target_enemy failed, try recheck break out of combat 
2026-10-15 09:22:59,239 ERROR TaskExecutor BaseCombatTask:combat check not in combat 
2026-10-15 09:25:19,909 ERROR TaskExecutor Qingxiao:clicked liberation but no effect 
2026-10-15 09:31:40,834 INFO TaskExecutor DailyTask:Daily Task Completed
"""
# Real failures inside rounds booked as a success: never on the list.
MUST_PUSH = {
    "OK-WW": [
        "2026-09-29 09:28:53,798 ERROR TaskExecutor DailyTask:can not battle pass, maybe ended",
        "2026-10-05 10:34:50,807 ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card Traceback (most recent call last):",
        "2026-10-05 10:35:22,335 ERROR TaskExecutor NightmareNestTask:can't find gray_book_boss, make sure f2 is the hotkey for book",
        "2026-10-05 10:34:52,359 ERROR TaskExecutor DailyTask:附加任务出错，不拖垮当趟日常:  Traceback (most recent call last):",
        # Made up from the real 10-15 lines: the same words outside the start-wait loop, or
        # a start error with another message, are not what was checked; they go to the group.
        "2026-10-15 09:25:00,000 ERROR TaskExecutor DeviceManager:refresh error Traceback (most recent call last):",
        "2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:waiting for game to start error 'NoneType' object has no attribute 'hwnd'",
    ],
    "MAA": [
        "[2026-10-02 23:40:26.537][ERR][VersionUpdateDialogViewModel] <2> mirrorc failed",
    ],
    "MaaEnd": [
        # Made up from the real anchor line: a node that does not exist without being an anchor.
        "[2026-09-28 11:09:53.122][ERR][Px9932][Tx43027][PipelineTask.cpp][L292][MaaNS::TaskNS::PipelineTask::recognize_list] get_pipeline_data failed, node not exist [node={\"jump_back\":true,\"name\":\"SomeNodeThatIsGone\"}]",
    ],
}
# Entries that may say not-a-fault (line-number free: matched by script and a sample they match).
NOT_A_FAULT = {
    ("MAA", "Failed to set startup: No value exists with that name."):
        "MAA elevated removing a start-with-Windows value that is not there (BOARD 未进群报错-MAA-MaaEnd-1010)",
    ("MaaEnd", "templ size is too large"):
        "MaaFramework: a template larger than its search region counts as not found; the pipeline goes on",
    ("MaaEnd", "roi is out of range"):
        "MaaFramework drops a search region that starts past the screen (VisionUtils.hpp L347-350)",
    ("MaaEnd", "uid is invalid"):
        "MaaFramework refuses to store the detail of a recognition that returned early (RuntimeCache.cpp L63-67)",
    ("MaaEnd", "failed to get target rect for wait_freezes"):
        "MaaFramework skips the freeze wait of an inverted node (ActionHelper.cpp L38-42, TaskBase.cpp L202-211)",
    ("MaaEnd", '"anchor":true'):
        "MaaFramework skips an [Anchor] candidate whose anchor is not set, by design (PipelineProtocol L1478-1479)",
}
UNKNOWN = ("not known", "unknown", "unexplained", "not found yet", "tbd", "to be checked", "不明", "待查", "没查清")

print("[the registry: shape, why, source, a real sample per entry]")
entries, problems = ge.parse(ge.REGISTRY.read_text(encoding="utf-8"))
check("every line parses", problems, [])
check("it has entries for all three scripts", {e.script for e in entries}, {"MAA", "MaaEnd", "OK-WW"})
for e in entries:
    tag = f"line {e.line_no} {e.script}"
    check(f"{tag}: a why of some length", len(e.why) >= 30, True)
    check(f"{tag}: the why does not call the cause unknown", [w for w in UNKNOWN if w in e.why.lower()], [])
    check(f"{tag}: a source", len(e.source) >= 10, True)
    hits = [s for s in SAMPLES.get(e.script, []) if e.pattern.search(s)]
    check(f"{tag}: matches a real sample", bool(hits), True)
    if e.kind == "not-a-fault":
        ok = any(k[0] == e.script and any(k[1] in s for s in hits) for k in NOT_A_FAULT)
        check(f"{tag}: not-a-fault is on NOT_A_FAULT", ok, True)
for script, lines in SAMPLES.items():
    for s in lines:
        check(f"sample is listed: {s[:70]}", ge.known(script, s) is not None, True)
for script, lines in MUST_PUSH.items():
    for s in lines:
        check(f"real failure is not listed: {s[:70]}", ge.known(script, s), None)

print("[a source on this Mac's BOARD exists (2026-10-12: nine OK-WW lines cited a file that had moved)]")
BOARD = Path.home() / "Money" / "styl-work" / "BOARD"
if BOARD.is_dir():
    for e in entries:
        if e.source.startswith("~/"):
            where = e.source.split(" (", 1)[0]
            check(f"line {e.line_no}: its source {where} exists", Path(where).expanduser().is_file(), True)

print("[the 10-15 09:20 round (alarm f7a4bb6a): every ERROR line is listed, as recovered]")
check("nothing unlisted in the whole round", ge.unregistered("OK-WW", ROUND_1015), [])
check("the start-wait kinds count as recovered, not not-a-fault",
      sorted({e.kind for e, _l, _n in ge.recovered_kinds("OK-WW", ROUND_1015)}), ["recovered"])

print("[the parser refuses the bad shapes]")
bad = ("MAA | x | verdict: fine - it is ok | src\n"
       "MAA | ( | verdict: recovered - a long enough reason for a bad regex | src\n"
       "Foo | x | verdict: recovered - a long enough reason for a bad script | src\n"
       "MAA | x | recovered - no verdict: prefix here at all, so it is refused | src\n"
       "MAA | x | verdict: recovered - three parts only\n")
_, probs = ge.parse(bad)
check("five bad lines, five problems", len(probs), 5)

print("[unregistered: listed lines drop out, the rest folded by shape]")
text = "\n".join(SAMPLES["OK-WW"] + MUST_PUSH["OK-WW"][:1] * 3 + ["2026-10-11 09:00:00,000 INFO fine"])
got = ge.unregistered("OK-WW", text)
check("one shape left, seen three times", [(("battle pass" in line), n) for line, n in got], [(True, 3)])
check("nothing for a log with listed lines only", ge.unregistered("OK-WW", "\n".join(SAMPLES["OK-WW"])), [])
check("an unknown script reads nothing", ge.unregistered("X", "\n".join(MUST_PUSH["OK-WW"])), [])

print("[check_round: one alarm per round, plain words, raw lines to the technical log]")


class _H(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, r):
        self.records.append(r)


ARK = logging.getLogger(errwatch.ARK)
h = _H()
ARK.addHandler(h)
try:
    sd = TMP / "r" / "state"
    sd.mkdir(parents=True)
    logp = TMP / "r" / "OK-WW-09-12-00.log"
    logp.write_text(text, encoding="utf-8")
    started = datetime(2026, 10, 11, 9, 12, tzinfo=SERVER_TZ)
    rec = types.SimpleNamespace(script="OK-WW", run_id="2026-10-11/wuwa/OK-WW-09-12-00", log_path=logp,
                                started=started)
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(state_dir=str(sd)))
    found = ge.check_round(eng, rec)
    check("returns the unlisted shape", len(found), 1)
    pushed = [r for r in h.records if not getattr(r, errwatch.RECOVERED, False)]
    check("one pushed WARNING (the listed recovered lines are the round's other, recovered one)",
          (len(pushed), len(h.records)), (1, 2))
    alarm = getattr(pushed[0], errwatch.ALARM, None) if pushed else None
    check("with its own title and body", alarm, (texts.gamelog_unknown_errors("鸣潮"),
                                                texts.gamelog_unknown_errors_body("鸣潮", "09:12", 1)))
    check("title and body read as plain words", (texts.plain(alarm[0]), texts.plain(alarm[1])) if alarm else None,
          ([], []))
    red = techlog.unhandled(techlog.path_for("2026-10-11", sd).read_text(encoding="utf-8"))
    check("one red item quoting the raw line", [("can not battle pass" in t, rec.run_id in t) for _, t in red],
          [(True, True)])
    h.records.clear()
    # 2026-10-12 (mute audit item 4): a listed `recovered` line is a fault the program got
    # past by itself - one red item per round (errwatch.recovered()), never silence.
    logp.write_text("\n".join(SAMPLES["OK-WW"]), encoding="utf-8")
    check("a log with listed recovered lines only: nothing unlisted", ge.check_round(eng, rec), [])
    check("... but one WARNING marked recovered for the round, not pushed",
          [(getattr(r, errwatch.RECOVERED, False), getattr(r, errwatch.ALARM, None)) for r in h.records],
          [(True, None)])
    check("... naming the run and each recovered kind once",
          bool(h.records) and rec.run_id in h.records[0].getMessage()
          and h.records[0].getMessage().count("combat check not in combat") == 1, True)
    check("... its first line (what the daily report quotes) is plain words, the same every run",
          [texts.plain(errwatch.first_line(r)) for r in h.records], [[]])
    h.records.clear()
    maa = types.SimpleNamespace(script="MAA", run_id="2026-10-11/ak/MAA-09-00-00", log_path=TMP / "r" / "gui.log",
                                started=started)
    maa.log_path.write_text(SAMPLES["MAA"][0], encoding="utf-8")
    check("a log with listed not-a-fault lines only: nothing at all", (ge.check_round(eng, maa), h.records), ([], []))
    h.records.clear()
    rec.log_path = TMP / "r" / "missing.log"
    ge.check_round(eng, rec)
    check("an unreadable log is said, never taken as clean", [("日志读不了" in r.getMessage()) for r in h.records],
          [True])
finally:
    ARK.removeHandler(h)

print("[handle's success path calls it]")
src = (RELAY / "ark_relay" / "features" / "alarm" / "handle.py").read_text(encoding="utf-8")
body = src[src.index("def _handle_success"):src.index("def _retry_healed")]
check("_handle_success calls gamelog_errors.check_round", "gamelog_errors.check_round(eng, rec)" in body, True)
check("after the outcome check's early return", body.index("gamelog_errors.check_round") > body.index("_verify_outcome"),
      True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
