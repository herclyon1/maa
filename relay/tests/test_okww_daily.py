"""OK-WW's daily: the battle pass and its claim, the claim read-back, daily chests, the farm hook, the merge step, plan bits, revive and retry, the stamina end and the nest verdict, upstream with no farm.

One part per former file, each run on its own (tests/_parts.py): test_okww_battle_pass.py, test_okww_battle_pass_claim.py, test_okww_claim_readback.py, test_okww_daily_chests.py, test_okww_farm_hook.py, test_okww_merge_step.py, test_okww_plan_bits.py, test_okww_revive_and_retry.py, test_okww_stamina_end.py, test_okww_stamina_nest_verdict.py, test_okww_upstream_no_farm.py.
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


def _part_okww_battle_pass():
    """OK-WW's battle-pass line is about the battle pass, not about a fight.

DailyTask.claim_battle_pass (upstream src/task/DailyTask.py) opens the battle-pass
page and logs 「can not battle pass, maybe ended」 when no level digits are read
there; the claim is skipped and the run goes on. The relay's table read it as
「没能进入战斗」 until 10-11 (found by the 游戏-中继二 session on 10-10, BOARD
被指出.txt line 742). The lines below are the real ones of the 2026-09-29 09:28 run
(D:\\ark\\automas\\history\\2026-09-29\\wuwa\\OK-WW-05-20-18.log, the ERROR line at
09:28:53 and its neighbours), read off the game machine on 10-11.

    Formerly test_okww_battle_pass.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features.verify import collector_okww


    REAL = """2026-09-29 09:28:42,334 INFO TaskExecutor DailyTask:info_set current task in main esc=True
2026-09-29 09:28:43,334 INFO TaskExecutor DailyTask:battle pass
2026-09-29 09:28:53,798 INFO TaskExecutor TaskExecutor:wait_until timeout <function OCR.wait_ocr.<locals>.<lambda> at 0x000002BC775F9C60> 10 seconds
2026-09-29 09:28:53,798 ERROR TaskExecutor DailyTask:can not battle pass, maybe ended
2026-09-29 09:28:53,807 INFO TaskExecutor DailyTask:info_set current task wait main esc=True
"""
    REAL = REAL.replace("maybe ended\n", "maybe ended \n")    # upstream's line ends in a space
    WANT = f"日常清单：{texts.OKWW_BATTLE_PASS_UNCLAIMED}"

    print("[the battle-pass line is translated as the battle pass]")
    said = collector_okww._okww_say("DailyTask", "can not battle pass, maybe ended", "")
    check("the sentence for the raw line", said, WANT)
    check("it names 战令", "战令" in said)
    check("it no longer says 没能进入战斗", "没能进入战斗" in said, False)
    check("plain language", texts.plain(said), [])
    # When OK-WW records the line as the run's 错误 (info_set), the report takes this path.
    recorded = REAL.replace(
        "maybe ended \n",
        "maybe ended \n2026-09-29 09:28:53,799 INFO TaskExecutor DailyTask:info_set 错误 can not battle pass, maybe ended\n")
    recorded = "2026-09-29 09:27:30,000 INFO TaskExecutor DailyTask:info_set current task claim mail\n" + recorded
    check("recorded as the run's reason -> the same battle-pass sentence", collector_okww._okww_error(recorded), WANT)
    check("the 「not in combat」 line keeps its own fight wording",
          collector_okww._okww_say("BaseCombatTask", "combat check not in combat", ""), "战斗：没有进入战斗")


def _part_okww_battle_pass_claim():
    """OK-WW's battle pass (先约电台): a page that did not open is tried once more, then reported.

Upstream's DailyTask.claim_battle_pass presses Alt, clicks the podcast icon and waits
10 s for the level number; with none it logs 「can not battle pass, maybe ended」 and
the run ends 「Daily Task Completed」. 2026-09-29 09:28 that happened, the day's podcast
points went unclaimed, and the relay said nothing (BOARD 未进群报错-OKWW-AUTOMAS-1010.md).
The user (10-11 17:36) on the daily podcast points lost: 「鸣潮战令没领会导致每日的战令点数丢失，
为什么你不去查清楚？」 (he asked why nobody had looked into it).

The overlay now photographs the miss, goes back to the world and opens the page once
more in the same run; a second miss is an item undone in 「⚠️ 这一轮没干完」
(outcome.battle_pass_checks). Upstream's real method is the one in
fixtures/okww-DailyTask-v3.7.4.py.txt (read off the game machine on 10-11; upstream
master had the same body that day).

    Formerly test_okww_battle_pass_claim.py.
    """
    import ast
    import re
    import tempfile
    import textwrap
    import types

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    from ark_relay.core import texts
    from ark_relay.features.okww_patch import okww_overlay
    from ark_relay.features.verify import outcome


    # The OK-WW the machine runs (test_gl_okww_contract.INSTALLED); v3.7.4 until 2026-11-02.
    UPSTREAM = (HERE / "gamesim" / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task" / "DailyTask.py.txt").read_text(encoding="utf-8")


    def overlay():
        """A fresh copy of the overrides file. Its own install block fails here (no OK-WW) and is caught."""
        ns = {"__name__": "ark_overrides_test"}
        exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
        ns["_applied"].clear()
        ns["_skipped"].clear()
        return ns


    def upstream_method(text=UPSTREAM):
        """Upstream's claim_battle_pass as a plain function of self, cut out of the file."""
        tree = ast.parse(text)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DailyTask")
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "claim_battle_pass")
        lines = text.splitlines(keepends=True)[fn.lineno - 1:fn.end_lineno]
        scope = {"re": re}
        exec(compile(textwrap.dedent("".join(lines)), "DailyTask.py", "exec"), scope)
        return scope["claim_battle_pass"]


    class Box:
        def __init__(self, name):
            self.name = name


    class Game:
        """The world and the podcast page. `opens` says, per Alt+click, whether the page comes up."""

        def __init__(self, opens, level="37", icon=(0.86, 0.05)):
            self.opens = list(opens)
            self.icon = icon
            self.level = level
            self.page = False
            self.acts, self.logs, self.errors, self.shots = [], [], [], []

        # input
        def send_key_down(self, key):
            self.acts.append(("down", key))

        def send_key_up(self, key):
            self.acts.append(("up", key))

        def sleep(self, s):
            self.acts.append(("sleep", s))

        def click_relative(self, x, y, **kw):
            self.acts.append(("click_relative", x, y, tuple(sorted(kw.items()))))
            if (x, y) == self.icon:
                self.page = self.opens.pop(0) if self.opens else False

        def click(self, x, y, **kw):
            self.acts.append(("click", x, y, tuple(sorted(kw.items()))))

        # reading
        def wait_ocr(self, x, y, to_x, to_y, match=None, post_action=None, **kw):
            self.acts.append(("wait_ocr", x, y, to_x, to_y, match.pattern if match else None,
                              post_action is not None, tuple(sorted(kw.items()))))
            if post_action is not None and self.page:
                post_action()
            return [Box(self.level)] if self.page else None

        def ocr(self, *a, **kw):
            return [Box("先约电台" if self.page else "大世界")]

        def box_of_screen(self, *a):
            return a

        def screenshot(self, name):
            self.shots.append(name)

        def ensure_main(self, *a, **kw):
            self.page = False
            self.acts.append(("ensure_main",))

        # logging
        def log_info(self, msg, **kw):
            self.logs.append(msg)

        def log_error(self, msg, *a, **kw):
            self.errors.append(msg)

        # ok-script's translation (v3.7.14-beta.2 wraps log sentences in it); English here
        def tr(self, msg):
            return msg


    def as_log(game):
        """The lines as OK-WW writes them for the task executor (what the relay reads)."""
        out = [f"2026-10-12 09:30:{i:02d},000 INFO TaskExecutor DailyTask:{m}" for i, m in enumerate(game.logs)]
        out += [f"2026-10-12 09:31:{i:02d},000 ERROR TaskExecutor DailyTask:{m} " for i, m in enumerate(game.errors)]
        return "\n".join(out) + "\n"


    def no_logs(acts):
        return [a for a in acts if a[0] != "sleep"]


    ns = overlay()

    print("[the pin is upstream's real body]")
    with tempfile.TemporaryDirectory() as d:
        Path(d, "DailyTask.py").write_text(UPSTREAM, encoding="utf-8")
        got = okww_overlay._method_sha(okww_overlay._classes(Path(d)), "DailyTask", "claim_battle_pass")
    check("sha of claim_battle_pass in the installed v3.7.14-beta.2 == _BATTLE_PASS_SHA", got, ns["_BATTLE_PASS_SHA"])
    check("the overlay reads the same level box upstream does",
          "self.wait_ocr(0.2, 0.13, 0.32, 0.22" in UPSTREAM and ns["BATTLE_PASS_LEVEL_BOX"] == (0.2, 0.13, 0.32, 0.22), True)
    check("the overlay's line markers are the ones outcome reads",
          (ns["BATTLE_PASS_OK"], ns["BATTLE_PASS_RETRY"], ns["BATTLE_PASS_FAILED"], ns["BATTLE_PASS_UNCHECKED"]),
          (outcome._BATTLE_PASS_OK, outcome._BATTLE_PASS_RETRY, outcome._BATTLE_PASS_FAILED,
           outcome._BATTLE_PASS_UNCHECKED))

    print("\n[page opens at once: upstream's clicks, nothing more]")
    up = Game([True])
    upstream_method()(up)
    ours = Game([True])
    ns["_claim_battle_pass_checked"](ours)
    check("same inputs and reads as upstream, in the same order", no_logs(ours.acts), no_logs(up.acts))
    check("no screenshot, no error", (ours.shots, ours.errors), ([], []))
    check("the green line names the level read", ours.logs[-1], f"{ns['BATTLE_PASS_OK']}37）")
    c = outcome.battle_pass_checks(as_log(ours))
    check("relay: one green battle-pass item", [(x.label, x.ok, x.detail) for x in c],
          [(texts.OKWW_BATTLE_PASS_LABEL, True, "")])

    print("\n[first try misses (09-29 09:28), second opens: claimed in the same run]")
    g = Game([False, True])
    ns["_claim_battle_pass_checked"](g)
    opens = [a for a in g.acts if a[:3] == ("click_relative", 0.86, 0.05)]
    check("the page was opened exactly twice", len(opens), 2)
    check("a screenshot of the miss", g.shots, ["battle_pass_unopened_1"])
    check("back to the world between the two tries",
          g.acts.index(("ensure_main",)) < [i for i, a in enumerate(g.acts) if a[:3] == ("click_relative", 0.86, 0.05)][1],
          True)
    check("the miss says what the screen showed", any(m.startswith(ns["BATTLE_PASS_RETRY"]) and "整屏读到" in m
                                                       for m in g.logs), True)
    check("no ERROR line once the retry worked", g.errors, [])
    check("the claim clicks ran after the second open",
          ("click_relative", 0.04, 0.3, (("after_sleep", 1),)) in g.acts, True)
    c = outcome.battle_pass_checks(as_log(g))
    check("relay: green, saying it took a second try", [(x.ok, x.detail) for x in c],
          [(True, texts.OKWW_BATTLE_PASS_RETRIED)])

    print("\n[both tries miss: reported, nothing clicked blind]")
    g = Game([False, False])
    ns["_claim_battle_pass_checked"](g)
    check("opened twice, no third time", len([a for a in g.acts if a[:3] == ("click_relative", 0.86, 0.05)]), 2)
    check("two screenshots", g.shots, ["battle_pass_unopened_1", "battle_pass_unopened_2"])
    check("upstream's own sentence is still logged", g.errors, ["can not battle pass, maybe ended"])
    check("the failed line", any(m.startswith(ns["BATTLE_PASS_FAILED"]) for m in g.logs), True)
    check("no claim clicks on a page that is not there",
          [a for a in g.acts if a[0] == "click_relative" and a[1:3] != (0.86, 0.05)], [])
    check("ends back in the world", g.acts[-1], ("ensure_main",))
    c = outcome.battle_pass_checks(as_log(g))
    check("relay: one red item, the plain sentence", [(x.label, x.ok, x.detail) for x in c],
          [(texts.OKWW_BATTLE_PASS_LABEL, False, texts.OKWW_BATTLE_PASS_FAILED)])

    print("\n[installed on DailyTask: our copy when the body matches, upstream's otherwise]")


    def install(text):
        mod = types.ModuleType("src.task.DailyTask")
        mod.DailyTask = type("DailyTask", (), {})
        # inspect.getsource needs the function to come from a file; give it the fixture's text.
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
            fh.write("import re\n\n\nclass DailyTask:\n" + "".join(
                text.splitlines(keepends=True)[_span(text)[0]:_span(text)[1]]))
        scope = {}
        exec(compile(Path(fh.name).read_text(encoding="utf-8"), fh.name, "exec"), scope)
        mod.DailyTask.claim_battle_pass = scope["DailyTask"].claim_battle_pass
        sys.modules.update({"src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
                            "src.task.DailyTask": mod})
        n = overlay()
        n["_install_battle_pass"]()
        return n, mod.DailyTask


    def _span(text):
        tree = ast.parse(text)
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "DailyTask")
        fn = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == "claim_battle_pass")
        return fn.lineno - 1, fn.end_lineno


    n, cls = install(UPSTREAM)
    check("applied, nothing skipped", (n["_applied"], n["_skipped"]), (["DailyTask.claim_battle_pass"], []))
    g = Game([False, True])
    cls.claim_battle_pass(g)
    check("the installed method retries", len([a for a in g.acts if a[:3] == ("click_relative", 0.86, 0.05)]), 2)

    # Only words changed (ledger #130's kind: v3.7.13 -> v3.7.14-beta.2 wrapped the log text in
    # self.tr): another text, the same shape - our copy goes on, listed as adapted, not skipped
    # (dispatch relay-opt-round3-1108 O-02).
    WORDED = re.sub(r"self\.tr\(('[^']*')\)", r"\1", UPSTREAM)
    check("the worded body really differs from the pin", WORDED != UPSTREAM, True)
    n, cls = install(WORDED)
    check("words only: applied, nothing skipped", (n["_applied"], n["_skipped"]), (["DailyTask.claim_battle_pass"], []))
    check("words only: listed as adapted, saying the structure is unchanged",
          [(a["what"], "代码结构没变" in a["why"]) for a in n["_adapted"]], [("DailyTask.claim_battle_pass", True)])
    g = Game([False, True])
    cls.claim_battle_pass(g)
    check("words only: our copy runs (it retries)",
          len([a for a in g.acts if a[:3] == ("click_relative", 0.86, 0.05)]), 2)

    CHANGED = UPSTREAM.replace("self.click_relative(0.86, 0.05)", "self.click_relative(0.87, 0.05)")
    n, cls = install(CHANGED)
    check("changed upstream body: listed as skipped", [s["what"] for s in n["_skipped"]],
          ["DailyTask.claim_battle_pass（战令没打开时再开一次）"])
    g = Game([False])
    cls.claim_battle_pass(g)
    check("changed upstream body: upstream's own runs (its click, one try)",
          [a for a in g.acts if a[0] == "click_relative"], [("click_relative", 0.87, 0.05, ())])
    check("changed upstream body: the log says so", any(m.startswith(ns["BATTLE_PASS_UNCHECKED"]) for m in g.logs), True)
    check("changed upstream body + miss: still red (upstream's sentence)",
          [(x.ok, x.detail) for x in outcome.battle_pass_checks(as_log(g))],
          [(False, texts.OKWW_BATTLE_PASS_UNCLAIMED)])
    g = Game([True], icon=(0.87, 0.05))
    cls.claim_battle_pass(g)
    check("changed upstream body + page opened: green, saying no retry was there",
          [(x.ok, x.detail) for x in outcome.battle_pass_checks(as_log(g))],
          [(True, texts.OKWW_BATTLE_PASS_UNCHECKED)])

    print("\n[the relay: the real 09-29 run is an item undone]")
    REAL_0929 = """2026-09-29 09:28:31,805 INFO TaskExecutor DailyTask:info_set current task claim mail
2026-09-29 09:28:42,334 INFO TaskExecutor DailyTask:info_set current task in main esc=True
2026-09-29 09:28:43,334 INFO TaskExecutor DailyTask:battle pass
2026-09-29 09:28:53,798 INFO TaskExecutor TaskExecutor:wait_until timeout <function OCR.wait_ocr.<locals>.<lambda> at 0x000002BC775F9C60> 10 seconds
2026-09-29 09:28:53,798 ERROR TaskExecutor DailyTask:can not battle pass, maybe ended
2026-09-29 09:28:53,807 INFO TaskExecutor DailyTask:info_set current task wait main esc=True
2026-09-29 09:28:56,346 INFO TaskExecutor DailyTask:info_set current task in main esc=True
2026-09-29 09:28:56,346 INFO TaskExecutor DailyTask:Daily Task Completed
"""
    checks = outcome.okww_checks(REAL_0929, expect_nest=False)
    bp = [x for x in checks if x.label == texts.OKWW_BATTLE_PASS_LABEL]
    check("09-29: a red battle-pass item", [(x.ok, x.detail) for x in bp], [(False, texts.OKWW_BATTLE_PASS_UNCLAIMED)])
    msg = outcome.summarize(checks, "OK-WW")
    check("09-29: the push names the battle pass", msg is not None and texts.OKWW_BATTLE_PASS_LABEL in msg, True)
    done_before = "2026-09-29 09:21:00,000 INFO TaskExecutor DailyTask:info_set total daily points 100\n" + REAL_0929
    bp = [x for x in outcome.okww_checks(done_before, expect_nest=False) if x.label == texts.OKWW_BATTLE_PASS_LABEL]
    check("dailies already done before the run: the battle pass is still checked", [x.ok for x in bp], [False])
    OLD = (HERE / "fixtures" / "okww-1006-run.log").read_text(encoding="utf-8", errors="replace")
    check("a clean run from before the overlay line: no battle-pass item, no false red",
          outcome.battle_pass_checks(OLD), [])
    LABEL = "战令改动在跑（没打开时同一趟再开一次）"
    ran = {c.label: c.ok for c in outcome.patch_effect_checks(as_log(ours))}
    check("patch check: our copy ran where upstream's step began", ran.get(LABEL), True)
    check("patch check: upstream's line alone (09-29) = our copy did not run",
          {c.label: c.ok for c in outcome.patch_effect_checks(REAL_0929)}.get(LABEL), False)
    check("patch check: upstream's ERROR line is not the trigger",
          LABEL in {c.label for c in outcome.patch_effect_checks(
              "2026-09-29 09:28:53,798 ERROR TaskExecutor DailyTask:can not battle pass, maybe ended \n")}, False)
    check("plain language", [texts.plain(t) for t in (texts.OKWW_BATTLE_PASS_LABEL, texts.OKWW_BATTLE_PASS_FAILED,
                                                        texts.OKWW_BATTLE_PASS_RETRIED, texts.OKWW_BATTLE_PASS_UNCHECKED)],
          [[], [], [], []])

    print("\n[between two seasons (11-11 09:32, alarm #164): the game says 暂未开播 - nothing owed]")
    # The run's own lines, read off the game machine on 11-11: both tries met the game's
    # notice (NOTICE below) and the run went on to "Daily Task Completed". It was pushed
    # to the group as an item undone that morning.
    REAL_1111 = (HERE / "fixtures" / "okww-1111-battle-pass-closed.log").read_text(encoding="utf-8")
    NOTICE = "当前先约电台各频道暂未开播，请于下期先约电台频道开启时间段内进入。"
    check("the sample holds the notice on both misses and upstream's ERROR line",
          (REAL_1111.count(NOTICE), "can not battle pass, maybe ended" in REAL_1111, "战令没领到：" in REAL_1111),
          (2, True, True))
    c = outcome.battle_pass_checks(REAL_1111)
    check("11-11: one item, passed, kind SKIPPED, the closed-season sentence",
          [(x.label, x.ok, x.detail, x.kind) for x in c],
          [(texts.OKWW_BATTLE_PASS_CLOSED, True, "", outcome.SKIPPED)])
    checks = outcome.okww_checks(REAL_1111, expect_nest=False, expect_stamina=False)
    check("11-11: nothing about the battle pass is red in the whole verdict",
          [x.label for x in checks if not x.ok and ("战令" in x.label or "战令" in x.detail)], [])
    check("11-11: the old red label is gone from the verdict",
          texts.OKWW_BATTLE_PASS_LABEL in [x.label for x in checks], False)
    check("11-11: no push for this run", outcome.summarize(checks, "OK-WW"), None)
    other = outcome.Check("别的一项", False, "别的原因")
    msg = outcome.summarize(checks + [other], "OK-WW")
    check("with another item red: said under 按周期今天不跑, not as undone nor as 干成的",
          ("有 1 项没干成" in msg, "按周期今天不跑：" + texts.OKWW_BATTLE_PASS_CLOSED in msg,
           texts.OKWW_BATTLE_PASS_CLOSED in msg.split("干成的：")[-1] if "干成的：" in msg else False),
          (True, True, False))
    # The last miss decides. Notice on the first try only, a blank page on the second: still red.
    lines = REAL_1111.splitlines()
    last = [i for i, ln in enumerate(lines) if "战令没领到：" in ln][-1]
    blank = "\n".join(lines[:last] + [lines[last].replace(NOTICE, "鸣潮")] + lines[last + 1:]) + "\n"
    check("notice gone on the last try: red as before",
          [(x.label, x.ok, x.detail) for x in outcome.battle_pass_checks(blank)],
          [(texts.OKWW_BATTLE_PASS_LABEL, False, texts.OKWW_BATTLE_PASS_FAILED)])
    # Notice on the first try, the page open on the second: claimed, said as a retry.
    retry = [ln for ln in lines if "战令：第一次没打开" in ln][0]
    opened = retry + "\n2026-11-11 09:32:16,526 INFO TaskExecutor DailyTask:" + ns["BATTLE_PASS_OK"] + "37）（第二次打开的）\n"
    check("notice on the first try, opened on the second: green with the retry said",
          [(x.label, x.ok, x.detail) for x in outcome.battle_pass_checks(opened)],
          [(texts.OKWW_BATTLE_PASS_LABEL, True, texts.OKWW_BATTLE_PASS_RETRIED)])
    # The word alone, away from the overlay's final-miss line, decides nothing.
    check("upstream's sentence alone plus the word elsewhere: red (no overlay line to read the screen from)",
          [(x.ok, x.detail) for x in outcome.battle_pass_checks(
              REAL_0929 + "2026-09-29 09:29:00,000 INFO TaskExecutor DailyTask:暂未开播\n")],
          [(False, texts.OKWW_BATTLE_PASS_UNCLAIMED)])
    check("the closed-season sentence is plain language", texts.plain(texts.OKWW_BATTLE_PASS_CLOSED), [])


def _part_okww_claim_readback():  # noqa: C901 - the whole body of the file this part was
    """Weekly boss claim: upstream's claim step with 确认 for its ESC, and the read-back.

Runs the real overlay (claim hook, level-page read, 开启挑战 split) against
upstream's own call order, with the game's real text:

  (E) crystal -> F -> claim dialog -> 确认 (not ESC) -> 「波片不够，动用备用体力」 ->
      确认 again -> settlement page -> 「退出副本」
  backup used and still short (10-12 11:44): 取消, skipped as short, no solute
  read-back: the way back in reads the counter on the level page, which has to be
      one less - ok-script.log 2026-10-05 22:13:04 3/3, 22:15:19 2/3, 22:17:31 1/3,
      22:39:48 0/3; unchanged / unread / some other number stops
  no crystal / the walk to it fails (10-12 09:52:20, OK-WW-05-18-47.log:1103-1109):
      no stop, the lap goes back to upstream
  a dialog that is not the claim dialog, or not the weekly boss: upstream's ESC
  unread 「本周剩余可收取次数」 before entering: stop, not 「enter anyway」
  开启挑战: a dialog that is up but not recognised is never confirmed (the
      「无法获取奖励」 reminder comes after 单人挑战 under v3.7.4, see
      test_okww_weekly_entry_paths.py)

    Formerly test_okww_claim_readback.py.
    """
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay


    class Disabled(Exception):
        """ok.TaskDisabledException."""


    class Revived(Exception):
        """src.task.BaseCombatTask.CharRevivedException."""


    class _Any(type):
        """A stand-in upstream class: any method _install_hooks reads exists and does nothing."""
        def __getattr__(cls, name):
            if name.startswith("__"):
                raise AttributeError(name)

            def anything(self, *a, **kw):
                return None
            return anything


    class BaseWWTask(metaclass=_Any):
        # Upstream v3.7.4 BaseWWTask.py:520-526, verbatim: ESC, i.e. 取消.
        def handle_claim_button(self):
            while self.wait_until(self.has_claim, raise_if_not_found=False, time_out=1.5):
                self.sleep(0.5)
                self.send_key('esc')
                self.sleep(0.5)
                return True

        # Upstream v3.7.4 BaseWWTask.py:584-590, with find_one('pick_up_f...') as `f_up`.
        def pick_f(self, handle_claim=True):
            if self.f_up:
                self.send_key('f', after_sleep=1)
                if not handle_claim:
                    return True
                if not self.handle_claim_button():
                    return True

        def click_on_book_target(self, serial_number, total_number, structure=None):
            self.events.append("book")
            return True                 # the team screen, no spoiler dialog

        # Upstream v3.7.3 BaseWWTask.py:1115-1117, verbatim: the overlay replaces it
        # only while its source still hashes to the pin.
        def click_team_challenge(self):
            self.wait_click_feature('team_start_challenge', raise_if_not_found=True, click_after_delay=0.5, after_sleep=1)
            self.wait_click_skip_dialog_confirm()


    class FarmEchoTask(BaseWWTask):
        def teleport_to_configured_boss(self):
            # Upstream v3.7.4 FarmEchoTask.py:273-308, reduced to the steps after the book.
            self.entries += 1
            is_team = self.click_on_book_target(1, 9)
            if is_team and not self.arena:
                self.click_configured_boss_level()
                self.click_solo_challenge()
                self.click_team_challenge()
            self.wait_in_team_and_world(time_out=120)
            return is_team

        def teleport_to_configured_boss_and_prepare(self):
            # Upstream v3.7.3 FarmEchoTask.py:243-266, reduced.
            try:
                self.teleport_to_configured_boss()
            except Exception as e:
                raise RuntimeError("Teleport to boss failed") from e
            self.prepared = "realm"

        def click_configured_boss_level(self):
            self.events.append("level")

        # Upstream v3.7.4 FarmEchoTask.py:374-378, verbatim.
        def click_solo_challenge(self):
            self.click(0.880, 0.911, after_sleep=2)
            self.wait_click_skip_dialog_confirm(time_out=1)

        def combat_once(self, wait_combat_time=200, raise_if_not_found=True, target=False):
            return True

        def incr_drop(self, dropped):
            self.events.append("incr")


    mods = {
        "ok": types.SimpleNamespace(TaskDisabledException=Disabled,
                                    Logger=types.SimpleNamespace(get_logger=lambda n: types.SimpleNamespace(
                                        info=lambda *a, **k: None, error=lambda *a, **k: None))),
        "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
        "src.task.BaseCombatTask": types.SimpleNamespace(CharRevivedException=Revived),
        "src.task.BaseWWTask": types.SimpleNamespace(BaseWWTask=BaseWWTask),
        "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=FarmEchoTask),
    }
    for name in ("DailyTask", "ForgeryTask", "SimulationTask", "TacetTask"):
        mods[f"src.task.{name}"] = types.SimpleNamespace(**{name: _Any(name, (), {})})
    _saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    if "FarmEchoTask.incr_drop" not in ns["_applied"]:
        ns["_install_claim"]()
    check("领奖、走去结晶、读次数、开启挑战四处都换上了", all(x in ns["_applied"] for x in (
        "FarmEchoTask.handle_claim_button", "FarmEchoTask.incr_drop", "FarmEchoTask.click_configured_boss_level",
        "FarmEchoTask.click_team_challenge")))
    ns["NO_CLAIM"] = str(Path(__file__).resolve().parent / "no-such-no-claim-flag")

    # Real text. The claim dialog: the old patch's own note of the full-screen OCR
    # (okww_patches/claim.py, removed 2026-10-12); the counter: ok-script.log 2026-10-05 (see the docstring).
    CLAIM_DIALOG = ["领取奖励需消耗60点结晶波片，请确认是否领取？", "取消", "确认"]
    SETTLEMENT = ["挑战成功", "退出副本", "重新挑战"]
    PAGE = {3: ["本周剩余可收取次数：3/3_1.00", "x60_0.79"], 2: ["本周剩余可收取次数：2/3_1.00", "x60_0.79"],
            1: ["本周剩余可收取次数：1/3_1.00", "x60_0.79"], 0: ["本周剩余可收取次数：0/3_0.99", "x60_0.79"]}
    UNREAD = ["x60_0.79"]


    class _At:
        """An OCR box with a place on the 1920x1080 screen."""
        def __init__(self, name, x, y):
            self.name, self.x, self.y, self.width, self.height = name, x, y, 40, 30

        def __str__(self):
            # ok-script's Box repr as the 10-12 log prints it
            return (f"Box(name='{self.name}', x={self.x}, y={self.y}, width={self.width}, "
                    f"height={self.height}, confidence=100)")


    def claim_screen(wave, spare, cap="240"):
        """The claim dialog over the top bar (10-12 11:44:41: backup 24 at x=1208, y=50)."""
        return [_At(str(spare), 1208, 50), _At(f"{wave}/{cap}", 1480, 50), _At("15652", 1800, 50),
                _At(CLAIM_DIALOG[0], 700, 500), _At("取消", 640, 700), _At("确认", 1280, 700)]


    # The claim dialog with a readable bar: 240 full (「240/240+」, 0921-weekly.log:18), and
    # 41 + backup 24 (enough with the backup, 10-12 11:44 numbers moved up by 24).
    FULL = claim_screen(240, 0, cap="240+")
    TOPUP = claim_screen(41, 24)


    def task(left=None, pages=(), screens=(), after=(), dialogs=(), gems=0, arena_at=None, crystal=True,
             walk_error=None, claim_up=True, boss="Weekly Challenge"):
        t = object.__new__(FarmEchoTask)
        t.events, t.logs, t.errors, t.shots = [], [], [], []
        t.entries, t.arena, t.reads_after = 0, False, 0
        t.pages, t.screens, t.after, t.dialogs = list(pages), list(screens), list(after), list(dialogs)
        t.gems, t.arena_at, t.crystal, t.walk_error = gems, arena_at, crystal, walk_error
        t.claim_up, t.f_up = claim_up, True
        t.config = {"Teleport to Boss": boss}
        t._in_realm = True
        if left is not None:
            t._ark_weekly_left = left

        def ocr(box=None, **kw):
            if box == (0.58, 0.80):
                return t.pages.pop(0) if t.pages else UNREAD
            if box == (0.20, 0.35):
                t.reads_after += 1
                return t.after.pop(0) if t.after else []
            if box == (0.0, 0.0):
                return t.screens.pop(0) if t.screens else ["某个没见过的画面"]
            return []
        t.ocr = ocr
        t.box_of_screen = lambda x, y, to_x, to_y: (x, y)
        t.height_of_screen = lambda r: r * 1080
        t.in_world = lambda: False
        t.in_team_and_world = lambda: t.arena_at is not None and t.reads_after >= t.arena_at
        t.log_info = lambda msg, notify=False: t.logs.append(msg)
        t.log_error = lambda msg, notify=False: t.errors.append((msg, notify))
        t.screenshot = lambda name: t.shots.append(name)
        t.sleep = lambda s: None
        t.wait_until = lambda cond, **kw: cond()
        t.has_claim = lambda: t.claim_up
        t.find_treasure_icon = lambda: t.crystal

        def walk():
            t.events.append("walk")
            if t.walk_error:
                raise t.walk_error
        t.walk_to_treasure = walk

        def right():
            t.events.append("confirm")
            return "confirm-btn"
        t.click_dialog_right_button = right
        t.click_dialog_left_button = lambda: t.events.append("cancel")

        def click(*a, **kw):
            t.events.append("solo" if a[:2] == (0.880, 0.911) else f"click:{a[0]}")
        t.click = click
        t.click_relative = lambda x, y, **kw: t.events.append(f"rel:{x},{y}")
        t.back = lambda after_sleep=0: t.events.append("back")
        t.send_key = lambda key, **kw: t.events.append(f"key:{key}")
        t.ensure_main = lambda time_out=30: t.events.append("main")
        t.wait_in_team_and_world = lambda time_out=10, raise_if_not_found=True, esc=False: True

        def wait_feature(feature, **kw):
            if feature == "gem_add_stamina":
                if t.gems > 0:
                    t.gems -= 1
                    return "gem"
                return None
            return True                 # team_start_challenge is there
        t.wait_feature = wait_feature

        def wait_click_ocr(match=None, **kw):
            seen = t.screens.pop(0) if t.screens else ["某个没见过的画面"]
            hit = [b for b in seen if match.search(str(b))]
            if hit:
                t.events.append(f"click:{hit[0]}")
                return hit
            return None
        t.wait_click_ocr = wait_click_ocr
        t.wait_click_feature = lambda feature, **kw: t.events.append("start")
        t.wait_click_skip_dialog_confirm = lambda *a, **kw: t.events.append("skip-confirm")
        t.find_one = lambda *a, **kw: t.dialogs.pop(0) if t.dialogs else None
        return t


    def lap(t):
        """One lap's end: the fight is over, upstream calls incr_drop. 'stop' on a deliberate stop."""
        try:
            t.incr_drop(True)
        except Disabled:
            return "stop"
        return "on"


    print("[(E) 结晶按 F→领奖弹窗点确认（不按 ESC）→波片不够动用备用体力→确认→结算页「退出副本」→回去读到 2/3]")
    t = task(left=3, pages=[PAGE[2]], screens=[TOPUP, SETTLEMENT], gems=1)
    check("没停", lap(t), "on")
    claim = t.events[:t.events.index("click:退出副本") + 1]
    check("走去结晶、按 F、确认、备用体力两下、返回、再确认、点退出副本", claim,
          ["incr", "walk", "key:f", "confirm", "rel:0.7,0.71", "rel:0.7,0.71", "back", "click:confirm-btn",
           "click:退出副本"])
    check("领奖弹窗上没按 ESC（上游那一下换成了确认）", "key:esc" in t.events, False)
    check("认出弹窗那句照旧（中继认它算打过一场）", any(m.startswith("周本领奖：认出弹窗，点确认") for m in t.logs))
    check("说了动用备用体力", "周本领奖：波片不够，动用备用体力" in t.logs)
    check("截了领奖那一刻", "weekly_claimed" in t.shots)
    check("说了已点确认（中继数点击次数）", "周本领奖：已点确认" in t.logs)
    check("结算页点了退出副本", "周本领奖：结算页点了「退出副本」" in t.logs)
    check("回读确认 3/3→2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)
    check("重进了本（选等级→单人挑战→开启挑战）", [e for e in t.events if e in ("level", "solo", "start")],
          ["level", "solo", "start"])
    check("开启挑战后什么都没确认", "skip-confirm" in t.events, False)
    check("没报错", t.errors, [])
    check("这次的读数记下当下一次的「领前」", t._ark_weekly_left, 2)

    print("\n[波片够、不弹补体力：确认一下就到结算页]")
    t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    check("没停", lap(t), "on")
    check("确认一次就退出副本", t.events[:5], ["incr", "walk", "key:f", "confirm", "click:退出副本"])
    check("没碰备用体力", [e for e in t.events if e.startswith("rel:") or e == "back"], [])

    print("\n[周一一趟三次：3/3→2/3→1/3→0/3，最后那次只读数，0/3 不进本]")
    t = task(left=3, pages=[PAGE[2], PAGE[1], PAGE[0]], screens=[FULL, SETTLEMENT] * 3)
    got = [lap(t), lap(t), lap(t)]
    check("前两圈接着打，第三圈领完停（有意跳过）", got, ["on", "on", "stop"])
    check("三次回读都对上", [m for m in t.logs if "回读确认" in m],
          ["周本领奖：回读确认领到，本周剩余 3/3→2/3", "周本领奖：回读确认领到，本周剩余 2/3→1/3",
           "周本领奖：回读确认领到，本周剩余 1/3→0/3"])
    check("开启挑战只点了两次", t.events.count("start"), 2)
    check("读到 0/3 退回主界面", t.events[-1], "main")
    check("说了已领满", "本周周本次数已领满（0/3），不进本，跳过" in t.logs)
    check("一次 ESC 都没按", "key:esc" in t.events, False)
    check("没报错", t.errors, [])

    def on_screen(t):
        t.height_of_screen = lambda r: r * 1080
        return t


    print("\n[领奖弹窗：波片 17 + 备用 24 不够 60（10-12 11:44）：先读顶栏，点取消、按波片不足跳过，不动备用体力]")
    t = on_screen(task(left=3, screens=[claim_screen(17, 24)], gems=2))
    check("跳过（结束这趟周本）", lap(t), "stop")
    check("按 F 后直接点取消", t.events[:4], ["incr", "walk", "key:f", "cancel"])
    check("没点确认、没碰备用体力", [e for e in t.events if e in ("confirm", "back") or e.startswith("rel:")], [])
    check("说了波片不足那句（中继认它是波片不足）",
          any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))
    check("没说认出弹窗点确认（中继不当它领过）", any(m.startswith("周本领奖：认出弹窗") for m in t.logs), False)
    check("留图", "weekly_short_claim" in t.shots)
    check("按跳过结束：没留失败原因", getattr(t, "_ark_failed", None), None)
    check("没当报错推送", t.errors, [])

    print("\n[领奖弹窗：波片 41 + 备用 24 够 60：照旧确认、动用备用体力一次、领到]")
    t = on_screen(task(left=3, pages=[PAGE[2]], screens=[claim_screen(41, 24), SETTLEMENT], gems=1))
    check("没停", lap(t), "on")
    check("确认后动用备用体力", t.events[3:6], ["confirm", "rel:0.7,0.71", "rel:0.7,0.71"])
    check("回读确认 3/3→2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)

    print("\n[领奖弹窗：波片 60 够：照旧确认一下就到结算页]")
    t = on_screen(task(left=3, pages=[PAGE[2]], screens=[claim_screen(60, 0), SETTLEMENT]))
    check("没停", lap(t), "on")
    check("确认一次就退出副本", t.events[:5], ["incr", "walk", "key:f", "confirm", "click:退出副本"])

    print("\n[the claim dialog's bar: 「240/240+」 (0921-weekly.log:18) reads as 240, backup 0]")
    check("240/240+", ns["_waveplates"](on_screen(task()), claim_screen(240, 0, cap="240+")), (240, 0))
    check("41/240", ns["_waveplates"](on_screen(task()), claim_screen(41, 24)), (41, 24))
    check("0/240+ with a backup of 136 (the level page, 10-05 22:17:31)",
          ns["_waveplates"](on_screen(task()), claim_screen(0, 136, cap="240+")), (0, 136))
    t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    check("240/240+: not stopped", lap(t), "on")
    check("240/240+: the two values are in the log", "周本领奖：顶栏读到波片 240/240，备用 0" in t.logs)
    check("the claim line shows the /240 token", any(m.startswith("周本领奖：认出弹窗") and "240/240+" in m for m in t.logs))

    print("\n[bar not read: no blind 确认 (10-12 11:44 spent the backup that way) - picture, phone, stop]")
    t = task(left=3, pages=[PAGE[2]], screens=[[_At(CLAIM_DIALOG[0], 700, 500)], SETTLEMENT], gems=2)
    check("stopped", lap(t), "stop")
    check("nothing confirmed, backup untouched", [e for e in t.events if e in ("confirm", "back") or e.startswith("rel:")], [])
    check("picture", "weekly_claim_bar_unread" in t.shots)
    check("pushed to the phone, as a failure", len(t.errors) == 1 and t.errors[0][1] and "顶栏的波片没读全" in t.errors[0][0])
    check("ends as failed (a reason is kept)", "顶栏的波片没读全" in (getattr(t, "_ark_failed", None) or ""))

    print("\n[顶栏读到够（41+24）、备用体力用上了仍不够（又弹补体力）：返回、点取消、按波片不足跳过，不动结晶溶剂]")
    t = task(left=3, screens=[TOPUP], gems=2)
    check("跳过（结束这趟周本）", lap(t), "stop")
    check("备用体力一轮之后返回、取消，没再确认",
          t.events[3:], ["confirm", "rel:0.7,0.71", "rel:0.7,0.71", "back", "click:confirm-btn", "back", "cancel"])
    check("说了波片不足那句（中继认它是波片不足）",
          any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))
    check("没说已点确认", "周本领奖：已点确认" in t.logs, False)
    check("留图", "weekly_short_claim" in t.shots)
    check("按跳过结束：没留失败原因", getattr(t, "_ark_failed", None), None)
    check("没当报错推送", t.errors, [])

    print("\n[10-12 15:29 / 15:31: backup 0, waveplates short -> cancelled before 确认; the top-up (solute) is never clicked]")
    t = task(left=3, screens=[claim_screen(17, 0)], gems=2)
    check("skipped as short", lap(t), "stop")
    check("no confirm, no top-up clicks", [e for e in t.events if e in ("confirm", "back") or e.startswith("rel:")], [])
    check("the shortage line", any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))

    print("\n[bar reads 240 but the game still opens the top-up dialog -> cancel, picture, stop; no top-up clicks]")
    t = task(left=3, screens=[FULL, SETTLEMENT], gems=1)
    check("stopped", lap(t), "stop")
    check("confirm, then back + cancel, no top-up clicks", t.events[3:], ["confirm", "back", "cancel"])
    check("picture of the dialog", "weekly_topup_unexpected" in t.shots)
    check("pushed, as a failure", len(t.errors) == 1 and t.errors[0][1] and "不点补充" in t.errors[0][0])
    check("not counted as clicked", "周本领奖：已点确认" in t.logs, False)

    print("\n[a claim made through upstream's own pickup (pick_f in walk_find_echo) leaves us in the world: still read back and re-entered]")
    t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    check("upstream's pick_f took the claim and clicked 退出副本", t.pick_f(), None)
    check("the claim flag is set", getattr(t, "_ark_claimed", False), True)
    t.in_world = lambda: True                    # 退出副本 put us in the open world
    check("incr_drop does not stop", lap(t), "on")
    check("read back 3/3->2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)
    check("went back in (level page)", "level" in t.events)
    check("flag cleared", t._ark_claimed, False)
    check("no second walk to a crystal", t.events.count("walk"), 0)

    print("\n[回读次数没变：这次没领到，截图报手机，停下不再进本]")
    t = task(left=2, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    check("停下", lap(t), "stop")
    check("报到手机", t.errors, [("周本领奖：回读次数没变（2/3），这次没领到", True)])
    check("留图", "weekly_claim_unchanged" in t.shots)
    check("没点上游的选等级、没点开启挑战", [e for e in t.events if e in ("level", "start")], [])

    print("\n[回读没读到：截图报手机，停下]")
    t = task(left=3, pages=[UNREAD], screens=[FULL, SETTLEMENT])
    check("停下", lap(t), "stop")
    check("报到手机", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
    check("原文进日志", any("回读时选等级页读到" in m and "x60_0.79" in m for m in t.logs))
    check("留图", "weekly_readback_unread" in t.shots)

    print("\n[重进没经过选等级页（直接落在场地里）：次数没回读，停下]")
    t = task(left=3, screens=[FULL, SETTLEMENT])
    t.arena = True
    check("停下", lap(t), "stop")
    check("报回读没读到", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
    check("回读的账清掉，下一趟不拿它比", t._ark_claim_before, None)

    print("\n[no 「退出副本」 after 确认 (10-05 10:34:50 farm 4c error): picture, phone, stop - no ESC, no re-entry]")
    t = task(left=3, screens=[FULL])
    check("stopped", lap(t), "stop")
    check("pushed with the screen's text",
          len(t.errors) == 1 and t.errors[0][1] and "没等到结算页" in t.errors[0][0] and "某个没见过的画面" in t.errors[0][0])
    check("picture", "weekly_no_settlement" in t.shots)
    check("no ESC, no back", [e for e in t.events if e in ("key:esc", "back")], [])
    check("no re-entry", t.entries, 0)
    check("ends as failed", "没等到结算页" in (getattr(t, "_ark_failed", None) or ""))

    print("\n[10-12 09:51:50: the fight check broke first and the walk to the crystal failed (WaitFailedException): picture, phone, stop]")
    # ev OK-WW-05-18-47.log:1102-1109 - 「farm echo walk_find_echo None」, 「去结晶按 F」,
    # walk_to_treasure, 09:52:20 WaitFailedException. Handing it back (a8cc86b6) let
    # upstream's next lap ESC out of the realm with the reward not taken.


    class WaitFailedException(Exception):
        """ok.WaitFailedException."""


    t = task(left=3, walk_error=WaitFailedException())
    check("stopped", lap(t), "stop")
    check("walked once, no F", [e for e in t.events if e in ("walk", "key:f")], ["walk"])
    check("pushed with the reason", len(t.errors) == 1 and t.errors[0][1]
          and "没走到结晶" in t.errors[0][0] and "WaitFailedException" in t.errors[0][0])
    check("picture", t.shots, ["weekly_walk_failed"])
    check("ends as failed", "没走到结晶" in (getattr(t, "_ark_failed", None) or ""))
    check("nothing confirmed, no ESC", [e for e in t.events if e in ("confirm", "cancel", "key:esc")], [])

    print("\n[no crystal after the lap: picture, phone, stop - no walk]")
    t = task(left=3, crystal=False)
    check("stopped", lap(t), "stop")
    check("no walk, no F", [e for e in t.events if e in ("walk", "key:f")], [])
    check("pushed with the reason", len(t.errors) == 1 and t.errors[0][1] and "没看到结晶" in t.errors[0][0])
    check("picture", t.shots, ["weekly_no_crystal"])

    print("\n[领奖钩子遇到的不是领奖弹窗（退出副本的确认框也是这个取消按钮）：照上游按 ESC，不点确认]")
    t = task(screens=[["是否退出副本？", "取消", "确认"]])
    check("返回 True（上游的语义）", t.handle_claim_button(), True)
    check("按的是 ESC，没点确认", [e for e in t.events if e in ("key:esc", "confirm")], ["key:esc"])

    print("\n[没有弹窗：什么都不点，返回 None（上游的语义）]")
    t = task(claim_up=False)
    check("返回 None", t.handle_claim_button(), None)
    check("什么都没点", t.events, [])

    print("\n[不是周本（刷声骸走的是强敌）：领奖弹窗照上游按 ESC]")
    t = task(boss="Boss Challenge", screens=[CLAIM_DIALOG])
    check("返回 True", t.handle_claim_button(), True)
    check("按的是 ESC，没点确认", [e for e in t.events if e in ("key:esc", "confirm")], ["key:esc"])

    print("\n[进本前选等级页没读到本周剩余次数：截图报手机，停下不进本]")
    t = task(pages=[UNREAD])
    try:
        t.teleport_to_configured_boss_and_prepare()
        got = "in"
    except Disabled:
        got = "stop"
    check("停下（有意跳过，不算失败）", got, "stop")
    check("报到手机、带原文", len(t.errors) == 1 and t.errors[0][1] and "x60_0.79" in t.errors[0][0])
    check("留图", "weekly_left_unread" in t.shots)
    check("没点上游的选等级、没点单人挑战", [e for e in t.events if e in ("level", "solo", "start")], [])

    print("\n[进本前读到 3/3（22:13:04）：照常进本，记下 3]")
    t = task(pages=[PAGE[3]])
    t.teleport_to_configured_boss_and_prepare()
    check("进了本", t.prepared, "realm")
    check("记下 3", t._ark_weekly_left, 3)

    print("\n[开启挑战后有对话框、字一直认不出：不点确认，截图报手机，停下]")
    t = task(dialogs=["btn"] * 6)
    try:
        t.click_team_challenge()
        got = "on"
    except Disabled:
        got = "stop"
    check("停下", got, "stop")
    check("看满了整段（6 眼）", t.reads_after, 6)
    check("没点确认也没点取消", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], [])
    check("留图", "challenge_dialog_unknown" in t.shots)
    check("报到手机", len(t.errors) == 1 and t.errors[0][1] and "认不出的对话框" in t.errors[0][0])

    print("\n[开启挑战后没有对话框、到了场地：不再看，也不点任何确认]")
    t = task(arena_at=2)
    t.click_team_challenge()
    check("看到进场就停（2 眼）", t.reads_after, 2)
    check("什么都没确认", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], [])
    check("没报错", t.errors, [])

    print("\n[开启挑战后一直加载中、没有对话框：看满整段，不点确认，接着走]")
    t = task()
    t.click_team_challenge()
    check("看满 6 眼", t.reads_after, 6)
    check("什么都没确认", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], [])

    print("\n[2026-11-03 账本 #135：Boss 转阶段 walk_find_echo 检测到还在战斗（_in_combat=True）返回 False：接着打完再领结晶，不误报没看到结晶]")
    t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
    t._in_combat = True
    def _resume_combat(**kw):
        t.events.append("resume-combat")
        t._in_combat = False
    t.combat_once = _resume_combat
    t.pick_echo = lambda: False
    t.walk_find_echo = lambda: (t.events.append("pick-echo"), True)[1]
    t.incr_drop(False)
    check("先接着打完再捡声骸再领奖", t.events[:7], ["incr", "resume-combat", "pick-echo", "incr", "walk", "key:f", "confirm"])
    check("领完剩余次数变 2", t._ark_weekly_left, 2)
    check("BaseWWTask.tr 返回英文原句（不让 zh_CN 破坏 AUTO-MAS 完成判定）",
          t.tr("Daily Task Completed"), "Daily Task Completed")

    # The coverage driver runs every test in one process: leave sys.modules as found.
    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_daily_chests():
    """OK-WW's daily activity chests: every chest up to the points is claimed, and checked.

2026-10-10 the run ended at 80 points with the 20-80 chests unclaimed and
「Daily Task Completed」 in the log, and the relay said nothing (the user's words, 10-10
19:4x and 19:55, are quoted in docs/OKWW-PATCHES.md and docs/NOTIFICATIONS.md).
Upstream's claim_daily clicks one fixed point, the 100 chest, and never looks again
(DailyTask.py claim_daily, sha 2b4977b62f7c).

The sample is his own screenshot of the chest row (fixtures/ww-daily-80-1010-row.png,
from BOARD/evidence/ww-daily-80-1010.png): 80 points, 20-80 claimed (he claimed them
by hand), 100 not. The 「80 points, 20-80 not claimed」 state of that morning is the
same row with the 100 chest's unclaimed picture put over the 20-80 chests.

2026-10-11 09:29 all five were claimed (140 points), yet 「100 档点了没领到」 went out:
the 100 chest was looked for by its label's box centre, and 「100」 is a digit wider
than 「20」-「80」, so the look landed 14 px left of the tick (0.35; 0.96 where the tick
is). The reward preview the click opens was on screen too, but it stops above the
tick. That run's screenshot is fixtures/ww-daily-140-1011-row.png (the bottom of the
1920x1080 frame, y 800-1010, preview included).

    Formerly test_okww_daily_chests.py.
    """
    import types

    import numpy as np
    from PIL import Image

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    from ark_relay.features.okww_patch import okww_overlay
    from ark_relay.features.verify import outcome


    ns = {"__name__": "ark_overrides_test"}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)

    ROW = np.array(Image.open(HERE / "fixtures" / "ww-daily-80-1010-row.png").convert("RGB"))
    H, W = ROW.shape[:2]
    # The tier labels' glyph boxes in the fixture (x0, y0, x1, y1), measured on the picture.
    GLYPHS = {20: (592, 93, 615, 112), 40: (884, 93, 907, 112), 60: (1177, 93, 1201, 112),
              80: (1471, 93, 1493, 112), 100: (1749, 93, 1787, 112)}


    def box(name, x0, y0, x1, y1, pad=0):
        return types.SimpleNamespace(name=name, x=x0 - pad, y=y0 - pad, width=x1 - x0 + 1 + 2 * pad,
                                     height=y1 - y0 + 1 + 2 * pad)


    LABELS = [box(str(t), *g, pad=4) for t, g in GLYPHS.items()]
    # What else the OCR reads as a tier number: the big points 「80」 at the left, above the row,
    # and a quest row's 「20」 further up.
    DECOYS = [box("80", 225, 15, 280, 65), box("20", 180, 2, 205, 14)]

    print("[the row: labels, step, where the chests are]")
    labels = ns["tier_labels"](LABELS + DECOYS, H)
    check("five tiers, decoys dropped", sorted(labels), [20, 40, 60, 80, 100])
    check("the 80 kept is the row's", labels[80][1] > 90, True)
    step = ns["tier_step"](labels)
    check("one tier step ~ 293 px", abs(step - 293) <= 1, True)
    chest = {t: ns["chest_at"](labels, step, t) for t in labels}
    check("the 20 chest is the circle at (663, 75), within a pixel",
          abs(chest[20][0] - 663) <= 1 and abs(chest[20][1] - 75) <= 1, True)

    print("\n[his screenshot: 20-80 claimed, 100 not]")
    gray = ROW.mean(axis=2)
    scores = ns["tier_scores"](gray, labels, step)
    print("    scores:", scores)
    check("20-80 read as claimed", all(scores[t] >= ns["_CHECKED_MIN"] for t in (20, 40, 60, 80)), True)
    check("100 reads as not claimed", scores[100] < ns["_CHECKED_MIN"], True)
    small = np.array(Image.fromarray(ROW).resize((W * 3 // 5, H * 3 // 5))).mean(axis=2)
    lab_s = {t: (x * 0.6, y * 0.6) for t, (x, y) in labels.items()}
    sc_s = ns["tier_scores"](small, lab_s, ns["tier_step"](lab_s))
    check("the same at 0.6 of the size", [sc_s[t] >= ns["_CHECKED_MIN"] for t in (20, 40, 60, 80, 100)],
          [True, True, True, True, False])

    # The morning's state: the 100 chest's unclaimed picture over 20-80.
    R = 46
    cx100, cy100 = (round(v) for v in chest[100])
    UNCLAIMED = ROW[cy100 - R:cy100 + R, cx100 - R:cx100 + R].copy()
    CLAIMED = {t: ROW[round(chest[t][1]) - R:round(chest[t][1]) + R, round(chest[t][0]) - R:round(chest[t][0]) + R].copy()
               for t in (20, 40, 60, 80)}


    def morning():
        img = ROW.copy()
        for t in (20, 40, 60, 80):
            x, y = (round(v) for v in chest[t])
            img[y - R:y + R, x - R:x + R] = UNCLAIMED
        return img


    class Game:
        """The dailies page: OCR answers, clicks claim a chest (when the game takes them)."""

        def __init__(self, frame, points="80", takes=True, ocr_labels=None, chests=None):
            self.frame, self.points, self.takes = frame, points, takes
            self.ocr_labels = LABELS + DECOYS if ocr_labels is None else ocr_labels
            self.chests = chest if chests is None else chests
            self.clicks, self.logs, self.keys = [], [], []

        def next_frame(self):
            return self.frame

        def ocr(self, *a, match=None, **k):
            if match is not None and "100" in match.pattern:
                return self.ocr_labels
            return [box(self.points, 225, 15, 280, 65)] if self.points else []

        def click_relative(self, rx, ry, **k):
            x, y = rx * self.frame.shape[1], ry * self.frame.shape[0]
            for t, (cx, cy) in self.chests.items():
                if abs(x - cx) < 30 and abs(y - cy) < 30:
                    self.clicks.append(t)
                    if self.takes and t in CLAIMED:
                        ix, iy = round(cx), round(cy)
                        self.frame = self.frame.copy()
                        self.frame[iy - R:iy + R, ix - R:ix + R] = CLAIMED[t]
                    return
            self.clicks.append(("miss", round(x), round(y)))

        def log_info(self, msg, **k):
            self.logs.append(msg)

        def send_key(self, key, **k):
            self.keys.append(key)

        def openF2Book(self, *a):  # noqa: N802 - upstream's name
            self.keys.append("book")

        def click(self, *a, **k):
            pass

        def screenshot(self, name):
            self.logs.append(f"[shot {name}]")


    print("\n[the morning: 80 points, 20-80 not claimed -> each clicked, each checked]")
    g = Game(morning())
    check("before: 20-80 read as not claimed",
          [v < ns["_CHECKED_MIN"] for t, v in ns["tier_scores"](g.frame.mean(axis=2), labels, step).items() if t != 100],
          [True] * 4)
    ns["_claim_tiers"](g)
    check("clicked 20, 40, 60, 80 - not 100", g.clicks, [20, 40, 60, 80])
    check("the points line for the relay", "活跃奖励：活跃度 80" in g.logs, True)
    check("checked: all claimed", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)
    check("no ESC needed", g.keys, [])

    print("\n[the game does not take the clicks -> tried twice, then said, with a screenshot]")
    g = Game(morning(), takes=False)
    ns["_claim_tiers"](g)
    check("each chest tried twice", sorted(g.clicks), sorted([20, 40, 60, 80] * 2))
    failed = [m for m in g.logs if m.startswith("活跃奖励没领到：")]
    check("one 「没领到」 line naming 20-80", bool(failed) and "20、40、60、80 档点了没领到" in failed[0], True)
    check("screenshot taken", "[shot daily_reward_unclaimed]" in g.logs, True)

    print("\n[already claimed (his screenshot) -> nothing clicked, checked]")
    g = Game(ROW.copy())
    ns["_claim_tiers"](g)
    check("nothing clicked", g.clicks, [])
    check("checked", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)

    print("\n[points not read -> said, nothing clicked]")
    g = Game(morning(), points="")
    ns["_claim_tiers"](g)
    check("nothing clicked", g.clicks, [])
    check("said", any(m.startswith("活跃奖励没领到：活跃度的分数没读到") for m in g.logs), True)

    print("\n[10-11 09:29: all five claimed, the reward preview over the 100 chest -> checked, nothing clicked]")
    ROW11 = np.array(Image.open(HERE / "fixtures" / "ww-daily-140-1011-row.png").convert("RGB"))
    # Glyph boxes of the tier labels in that picture (x0, y0, x1, y1), and where each tick is
    # (the best match of the tick, searched over +-40 px): 「100」 is 45 px wide, the rest 29-31.
    GLYPHS11 = {20: (683, 174, 711, 193), 40: (937, 174, 967, 193), 60: (1193, 174, 1222, 193),
                80: (1449, 174, 1478, 193), 100: (1690, 174, 1734, 193)}
    TICKS11 = {80: (1520, 159), 100: (1776, 159)}
    LABELS11 = [box(str(t), *g, pad=4) for t, g in GLYPHS11.items()]
    lab11 = ns["tier_labels"](LABELS11, ROW11.shape[0])
    step11 = ns["tier_step"](lab11)
    ch11 = {t: ns["chest_at"](lab11, step11, t) for t in lab11}
    check("80 and 100 looked for within 5 px of their ticks",
          [abs(ch11[t][0] - x) <= 5 and abs(ch11[t][1] - y) <= 5 for t, (x, y) in TICKS11.items()], [True, True])
    gray11 = ROW11.mean(axis=2)
    sc11 = ns["tier_scores"](gray11, lab11, step11)
    print("    scores:", sc11)
    check("all five read as claimed, preview and all", [sc11[t] >= ns["_CHECKED_MIN"] for t in ns["DAILY_TIERS"]],
          [True] * 5)
    # The cause, kept on record: placed by the box centre (the code before), 100 misses its tick.
    by_centre = {int(b.name): (b.x + b.width / 2, b.y + b.height / 2) for b in LABELS11}
    old = ns["tier_scores"](gray11, by_centre, ns["tier_step"](by_centre))
    check("by the box centre the 100 tick is missed (the false alarm)",
          [old[t] >= ns["_CHECKED_MIN"] for t in ns["DAILY_TIERS"]], [True, True, True, True, False])
    g = Game(ROW11.copy(), points="140", takes=False, ocr_labels=LABELS11, chests=ch11)
    ns["_claim_tiers"](g)
    check("nothing clicked", g.clicks, [])
    check("checked: 领完核对通过", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)
    check("no 「没领到」", any(m.startswith("活跃奖励没领到") for m in g.logs), False)

    print("\n[the row is not found again after a click -> its own failure, no verdict from the frame before the click]")


    class LostRow(Game):
        def ocr(self, *a, match=None, **k):
            if match is not None and "100" in match.pattern and self.clicks:
                return []
            return super().ocr(*a, match=match, **k)


    g = LostRow(morning())
    ns["_claim_tiers"](g)
    check("stopped after the first click", g.clicks, [20])
    failed = [m for m in g.logs if m.startswith("活跃奖励没领到：")]
    check("one line: the row was lost after clicking 20", len(failed) == 1 and "点了 20 档宝箱后那一排宝箱认不出来了" in failed[0], True)
    check("not 「点了没领到」 for chests the game may have taken", any("点了没领到" in m for m in g.logs), False)
    check("screenshot daily_reward_row_lost", "[shot daily_reward_row_lost]" in g.logs, True)

    print("\n[a due tier whose label OCR missed was never clicked -> 「没点」, not 「点了没领到」]")
    g = Game(morning(), ocr_labels=[b for b in LABELS if b.name != "40"] + DECOYS)
    ns["_claim_tiers"](g)
    check("20, 60, 80 clicked; 40 not", g.clicks, [20, 60, 80])
    failed = [m for m in g.logs if m.startswith("活跃奖励没领到：")]
    check("40 said as not clicked", len(failed) == 1 and "40 档的数字没认出来，没点" in failed[0], True)
    check("40 not said as clicked", "40 档点了没领到" in failed[0] if failed else True, False)

    print("\n[points read too low: a claimed tick above them -> failure, not 「领完核对通过」]")
    g = Game(ROW.copy(), points="40")
    ns["_claim_tiers"](g)
    check("nothing clicked (20 and 40 already claimed)", g.clicks, [])
    failed = [m for m in g.logs if m.startswith("活跃奖励没领到：")]
    check("said: 60 and 80 claimed above 40", len(failed) == 1 and "活跃度读成 40，可 60、80 档已显示领过" in failed[0], True)
    check("no 「领完核对通过」", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), False)
    g = Game(ROW.copy(), points="80")
    ns["_claim_tiers"](g)
    check("the tier at the points read, claimed, is fine", any(m.startswith("活跃奖励：领完核对通过") for m in g.logs), True)

    print("\n[the relay: the overlay's lines -> items undone (pushed as 「这一轮没干完」)]")
    LOG_OK = "活跃奖励：活跃度 80\n活跃奖励：领完核对通过（活跃度 80，已领 20、40、60、80）\nDaily Task Completed"
    got = {c.label: (c.ok, c.detail) for c in outcome.daily_reward_checks(LOG_OK)}
    check("claimed: green", got.get("每日活跃奖励领到了"), (True, ""))
    check("80 points: red, says how many", got.get("每日活跃满 100"), (False, "今天活跃 80 分，没满 100"))
    LOG_BAD = "活跃奖励：活跃度 80\n活跃奖励没领到：20、40、60、80 档点了没领到（活跃度 80）\nDaily Task Completed"
    got = {c.label: (c.ok, c.detail) for c in outcome.daily_reward_checks(LOG_BAD)}
    check("not claimed: red, says which", got.get("每日活跃奖励领到了"), (False, "20、40、60、80 档点了没领到（活跃度 80）"))
    LOG_FULL = "活跃奖励：活跃度 100\n活跃奖励：领完核对通过（…）"
    check("100 points: both green", [c.ok for c in outcome.daily_reward_checks(LOG_FULL)], [True, True])
    LOG_UP = "活跃奖励：没有核对，上游领奖正文变了（现在 abc，我们照着 2b4977b62f7c 抄的），照上游点 100 档"
    check("upstream changed: red", [(c.label, c.ok) for c in outcome.daily_reward_checks(LOG_UP)],
          [("每日活跃奖励领到了", False)])
    check("an old log says nothing new", outcome.daily_reward_checks("Daily Task Completed"), [])


def _part_okww_farm_hook():  # noqa: C901 - the whole body of the file this part was
    """Daily task: additional tasks first, the stamina farm to empty, one settlement shot.

Runs the real overlay against a stand-in for upstream v3.7.3 DailyTask.run
(DailyTask.py:77-136, reduced to its calls) and the three farm_* methods, with the
numbers the game showed on 2026-09-07 (tests/replay/2026-09-07/wuwa):

  open_daily_first      the weekly boss (additional tasks) runs before the daily's
                        stamina read; its error does not take the daily down; the
                        trailing run_additional_tasks is a no-op; the next run resets
  _farm_hook            farm_tacet / farm_forgery / farm_simulation lose daily= and
                        used_stamina= (must_use 0: farm to empty); the no-farm flag
                        file stops all three
  claim_daily           upstream farms only when `not daily_reward_ready and
                        used_stamina < 180` (DailyTask.py:88-89). After the weekly
                        boss spent 180 the gate is shut and the rest of the stamina
                        sat unused; the overlay farms it before claim_daily
  use_stamina           the tacet settlement keeps one screenshot (tacet_drops) when
                        the farm stops there
  get_stamina           the 数/数 read, with the real OCR text, in and out of the
                        reward dialog

    Formerly test_okww_farm_hook.py.
    """
    import os
    import re
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay


    REPLAY = Path(__file__).resolve().parent / "replay" / "2026-09-07" / "wuwa"


    def logged(path, lineno, pattern):
        """The integer `pattern` captures on line `lineno` of a replay log (1-based)."""
        # Bytes, not read_text: the logs mix CRLF with bare CR, and universal newlines
        # would count the bare CRs as lines and shift every number grep -n gives.
        line = path.read_bytes().decode("utf-8").split("\n")[lineno - 1].rstrip("\r")
        m = re.search(pattern, line)
        assert m, f"{path.name}:{lineno} no longer reads {pattern!r}: {line}"
        return int(m.group(1))


    # Real numbers. OK-WW-07-27-50.log:410-411 read the daily after the farm had spent
    # 180 (the old copy farmed on anyway: :419-420 read 75 + 26 and went in);
    # OK-WW-06-08-44.log:131 read 120 earlier that morning.
    DAY = REPLAY / "OK-WW-07-27-50.log"
    USED_FULL = logged(DAY, 410, r"DailyTask:info_set current daily progress (\d+)$")
    POINTS = logged(DAY, 411, r"DailyTask:info_set total daily points (\d+)$")
    CURRENT = logged(DAY, 419, r"TacetTask:info_set current_stamina (\d+)$")
    BACK_UP = logged(DAY, 420, r"TacetTask:info_set back_up_stamina (\d+)$")
    USED_PART = logged(REPLAY / "OK-WW-06-08-44.log", 131, r"current daily progress (\d+)$")


    class Disabled(Exception):
        """ok.TaskDisabledException."""


    class Revived(Exception):
        """src.task.BaseCombatTask.CharRevivedException."""


    class _Any(type):
        """A stand-in upstream class: any method the overlay reads exists and does nothing."""
        def __getattr__(cls, name):
            if name.startswith("__"):
                raise AttributeError(name)

            def anything(self, *a, **kw):
                return None
            return anything


    number_re = re.compile(r"^(\d+)$")
    stamina_re = re.compile(r"^(\d+)/(\d+)$")
    EV = []          # one call order across every task object


    class Box:
        def __init__(self, name, x=0):
            self.name, self.x = name, x


    class BaseWWTask(metaclass=_Any):
        # Upstream v3.7.3 BaseWWTask.py:409-424, verbatim: the overlay replaces it only
        # while its source still hashes to the pin (8ba6c1344ff8).
        def get_stamina(self):
            boxes = self.wait_ocr(0.49, 0.0, 0.92, 0.10, raise_if_not_found=False,
                                  match=[number_re, stamina_re])
            if not boxes:
                self.screenshot('stamina_error')
                return -1, -1, -1
            current = 0
            back_up = 0
            for box in boxes:
                if match := stamina_re.search(box.name):
                    current = int(match.group(1))
                elif match := number_re.search(box.name):
                    back_up = int(match.group(1))
            self.info_set('current_stamina', current)
            self.info_set('back_up_stamina', back_up)
            return current, back_up, current + back_up


    class TacetTask(BaseWWTask):
        def farm_tacet(self, daily=False, used_stamina=0, config=None, max_recovery_retries=3):
            # TacetTask.py:48-55: must_use is how much the daily step insists on spending.
            must_use = 180 - used_stamina if daily else 0
            EV.append(("farm_tacet", must_use, config))
            if self.farm_error:
                raise self.farm_error

        def use_stamina(self, once, must_use=0):
            # Upstream reads the stamina inside the reward dialog; the overlay's
            # get_stamina keys on this caller's name.
            self.read = self.get_stamina()
            return self.result


    class ForgeryTask(BaseWWTask):
        def farm_forgery(self, daily=False, used_stamina=0, config=None):
            EV.append(("farm_forgery", 180 - used_stamina if daily else 0, config))


    class SimulationTask(BaseWWTask):
        def farm_simulation(self, daily=False, used_stamina=0, config=None):
            EV.append(("farm_simulation", 180 - used_stamina if daily else 0, config))


    class DailyTask(BaseWWTask):
        def run(self):
            # Upstream v3.7.3 DailyTask.py:77-136, the calls in order (validation, login
            # and the nightmare nest left out).
            used_stamina, daily_reward_ready = self.open_daily()
            need_stamina = not daily_reward_ready and used_stamina < 180
            if need_stamina:
                target = self.config.get('Which to Farm', self.support_tasks[0])
                if target == self.support_tasks[0]:
                    self.get_task_by_class(TacetTask).farm_tacet(daily=True, used_stamina=used_stamina,
                                                                 config=self.config)
                elif target == self.support_tasks[1]:
                    self.get_task_by_class(ForgeryTask).farm_forgery(daily=True, used_stamina=used_stamina,
                                                                     config=self.config)
                else:
                    self.get_task_by_class(SimulationTask).farm_simulation(daily=True, used_stamina=used_stamina,
                                                                           config=self.config)
                self.sleep(4)
            self.claim_daily()
            self.claim_mail()
            self.sleep(1)
            self.claim_battle_pass()
            self.run_additional_tasks()
            self.log_info('Daily Task Completed', notify=True)

        def open_daily(self):
            EV.append("open_daily")
            return self.used, self.points >= 100

        def run_additional_tasks(self):
            EV.append("additional")
            if self.additional_error:
                raise self.additional_error

        def claim_daily(self):
            EV.append("claim_daily")

        def claim_mail(self):
            EV.append("claim_mail")

        def claim_battle_pass(self):
            EV.append("claim_battle_pass")


    mods = {
        "ok": types.SimpleNamespace(TaskDisabledException=Disabled,
                                    Logger=types.SimpleNamespace(get_logger=lambda n: types.SimpleNamespace(
                                        info=lambda *a, **k: None, error=lambda *a, **k: None))),
        "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
        "src.task.BaseCombatTask": types.SimpleNamespace(CharRevivedException=Revived),
        "src.task.BaseWWTask": types.SimpleNamespace(BaseWWTask=BaseWWTask),
        "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=_Any("FarmEchoTask", (), {})),
        "src.task.DailyTask": types.SimpleNamespace(DailyTask=DailyTask),
        "src.task.TacetTask": types.SimpleNamespace(TacetTask=TacetTask),
        "src.task.ForgeryTask": types.SimpleNamespace(ForgeryTask=ForgeryTask),
        "src.task.SimulationTask": types.SimpleNamespace(SimulationTask=SimulationTask),
    }
    _saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    print("[绑定都换上了]")
    for b in ("DailyTask.run", "DailyTask.open_daily", "DailyTask.run_additional_tasks", "DailyTask.claim_daily",
              "TacetTask.farm_tacet", "ForgeryTask.farm_forgery", "SimulationTask.farm_simulation",
              "TacetTask.use_stamina", "BaseWWTask.get_stamina"):
        check(f"{b} 已换上", b in ns["_applied"])

    tmp = str(tmpdir("ark-farm-hook-"))
    no_farm = os.path.join(tmp, "no-stamina-farm.flag")
    ns["NO_STAMINA_FLAG"] = no_farm
    SUPPORT = ["Tacet Suppression", "Forgery Challenge", "Simulation Challenge"]


    def wire(t):
        t.logs, t.shots, t.sleeps, t.info = [], [], [], {}
        t.log_info = lambda msg, notify=False: t.logs.append(msg)
        t.log_error = lambda msg, exception=None: t.logs.append(msg)
        t.screenshot = lambda name: t.shots.append(name)
        t.sleep = lambda s: t.sleeps.append(s)
        t.info_set = lambda k, v: t.info.__setitem__(k, v)
        t.ensure_main = lambda time_out=30: EV.append("ensure_main")
        return t


    def daily(used, points=POINTS, target=SUPPORT[0], additional_error=None, farm_error=None):
        EV.clear()
        farms = {c: wire(object.__new__(c)) for c in (TacetTask, ForgeryTask, SimulationTask)}
        farms[TacetTask].farm_error = farm_error
        d = wire(object.__new__(DailyTask))
        d.used, d.points, d.additional_error = used, points, additional_error
        d.config = {"Which to Farm": target}
        d.support_tasks = SUPPORT
        d.get_task_by_class = lambda cls: farms[cls]
        d.farms = farms
        return d


    def farm_calls():
        return [e for e in EV if isinstance(e, tuple)]


    # ---------------------------------------------------------------------------
    print(f"\n[附加任务（周本）排在读日常之前；尾巴上那次是空操作。已用 {USED_PART}/180]")
    d = daily(USED_PART)
    d.run()
    check("顺序：附加任务 → 读日常 → 刷体力 → 领日常", EV,
          ["additional", "open_daily", ("farm_tacet", 0, d.config), "claim_daily", "claim_mail",
           "claim_battle_pass"])
    check("附加任务只跑了一次（上游尾巴那次没再跑）", EV.count("additional"), 1)
    check("刷体力丢掉了 daily=/used_stamina=：must_use 0，刷到空", farm_calls()[0][1], 0)
    check("上游自己刷了，就不补刷", any("上游这趟不刷体力" in m for m in d.logs), False)
    check("上游读到的数留着", getattr(d, "_ark_daily_read", None), (USED_PART, False))

    print("\n[同一个实例跑第二趟：附加任务照样先跑]")
    d.run()
    check("第二趟也有附加任务", EV.count("additional"), 2)
    check("第二趟附加任务仍在读日常之前", EV.index("additional", 6) < EV.index("open_daily", 6))

    print("\n[附加任务出错不拖垮当趟日常]")
    d = daily(USED_PART, additional_error=RuntimeError("Teleport to boss failed"))
    d.run()
    check("记了错", any("附加任务出错，不拖垮当趟日常" in m for m in d.logs))
    check("留了图", d.shots, ["additional_tasks_error"])
    check("日常照跑：刷体力、领日常都在", farm_calls() != [] and "claim_daily" in EV)
    check("尾巴上没有再跑一次", EV.count("additional"), 1)

    print("\n[a TaskDisabledException (OK-WW's stop) from the additional tasks ends the daily, as upstream does]")
    d = daily(USED_PART, additional_error=Disabled())
    try:
        d.run()
        got = "ran on"
    except Disabled:
        got = "stopped"
    check("goes up, not swallowed", got, "stopped")
    check("not logged as an additional-task error", any("附加任务出错" in m for m in d.logs), False)
    check("the daily did not carry on", "claim_daily" in EV, False)

    # ---------------------------------------------------------------------------
    print(f"\n[周本花掉 {USED_FULL}：上游的闸门关了，剩下的 {CURRENT} + {BACK_UP} 照样刷掉]")
    d = daily(USED_FULL)
    d.run()
    check(f"读到已用 {USED_FULL}/180、活跃度 {POINTS}（OK-WW-07-27-50.log:410-411）",
          getattr(d, "_ark_daily_read", None), (USED_FULL, False))
    check("补刷了一次无音区，must_use 0", farm_calls(), [("farm_tacet", 0, d.config)])
    check("补刷在领日常之前", EV.index(("farm_tacet", 0, d.config)) < EV.index("claim_daily"))
    check("说了为什么补刷", any(f"上游这趟不刷体力（已用 {USED_FULL}/180" in m for m in d.logs))
    check("补刷后照上游那样等 4 秒", 4 in d.sleeps)
    check("「Daily Task Completed」在补刷之后（中继拿它当收尾）",
          d.logs.index("Daily Task Completed") > next(i for i, m in enumerate(d.logs) if "上游这趟不刷体力" in m))

    print("\n[活跃度已满 100：上游也不刷，照样补刷]")
    d = daily(0, points=100)
    d.run()
    check("补刷了一次", farm_calls(), [("farm_tacet", 0, d.config)])
    check("只刷了一次", len(farm_calls()), 1)

    print("\n[凝素领域 / 模拟领域：上游刷时丢参数，上游不刷时补刷的是同一个]")
    for target, name in ((SUPPORT[1], "farm_forgery"), (SUPPORT[2], "farm_simulation")):
        d = daily(USED_PART, target=target)
        d.run()
        check(f"{name}：上游刷，must_use 0", farm_calls(), [(name, 0, d.config)])
        d = daily(USED_FULL, target=target)
        d.run()
        check(f"{name}：上游不刷，补刷的也是它", farm_calls(), [(name, 0, d.config)])

    print("\n[补刷出错：记一笔、回主界面，日常奖励照领]")
    d = daily(USED_FULL, farm_error=RuntimeError("can't find gray_book_boss"))
    d.run()
    check("记了错", any("补刷体力出错，照常领日常奖励" in m for m in d.logs))
    check("留了图", d.shots, ["leftover_farm_error"])
    check("回了主界面再领", EV.index("ensure_main") < EV.index("claim_daily"))
    check("日常奖励照领", "claim_daily" in EV)

    print("\n[补刷时主动停（TaskDisabledException）照原样往上抛]")
    d = daily(USED_FULL, farm_error=Disabled())
    try:
        d.run()
        raised = False
    except Disabled:
        raised = True
    check("往上抛", raised)
    check("没领日常", "claim_daily" in EV, False)

    print("\n[标记文件在：三种刷体力都不花波片，补刷那条也不花]")
    Path(no_farm).write_text("")
    for used in (USED_PART, USED_FULL):
        d = daily(used)
        d.run()
        farm = d.farms[TacetTask]
        check(f"已用 {used}：一次都没进本", farm_calls(), [])
        check(f"已用 {used}：说了刷体力已禁用", any("刷体力已禁用（标记文件在）" in m for m in farm.logs))
        check(f"used {used}: the flag line once, not again from claim_daily",
              sum("刷体力已禁用" in m for m in farm.logs), 1)
        if used == USED_PART:
            check(f"used {used}: upstream reached the farm, so no 「按刷到空」 top-up line",
                  any("上游这趟不刷体力" in m for m in d.logs), False)
    check("补刷那条没有重复禁用的话", sum("刷体力已禁用" in m for m in d.farms[TacetTask].logs), 1)
    for cls, name in ((ForgeryTask, "farm_forgery"), (SimulationTask, "farm_simulation")):
        EV.clear()
        t = wire(object.__new__(cls))
        check(f"{name} 也挡住", getattr(t, name)(daily=True, used_stamina=0, config={}), None)
        check(f"{name} 没进本", farm_calls(), [])
    os.remove(no_farm)

    # ---------------------------------------------------------------------------
    print("\n[无音区结算：刷不动了停在结算页，留一张 tacet_drops]")
    t = wire(object.__new__(TacetTask))
    t.wait_ocr = lambda *a, **kw: [Box(str(BACK_UP), 1), Box(f"{CURRENT}/240", 2)]
    t.result = (False, 60)
    check("返回值原样", t.use_stamina(once=60, must_use=0), (False, 60))
    check("留了图", t.shots, ["tacet_drops"])
    t.result = (True, 60)
    t.shots = []
    check("还能接着刷：返回值原样", t.use_stamina(once=60, must_use=0), (True, 60))
    check("还能接着刷：不留图", t.shots, [])

    print("\n[体力读数：领奖框里读字原文进日志，真实文本]")
    t.result = (False, 60)
    t.use_stamina(once=60)
    check(f"读到 {CURRENT}+{BACK_UP}（OK-WW-07-27-50.log:419-420）", t.read, (CURRENT, BACK_UP, CURRENT + BACK_UP))
    check("current_stamina 照上游记", t.info.get("current_stamina"), CURRENT)
    check("读字原文进了日志（领奖框）", any(m.startswith("体力读字原文领奖框（第 1 次）") for m in t.logs))

    # 2026-09-21 10:25:49 (test_m6_okww.py:52): the reward dialog showed 剩余180 with no
    # 数/数 at all; upstream took that as 0. Five reads 1 s apart, then unknown, not 0.
    t = wire(object.__new__(TacetTask))
    t.wait_ocr = lambda *a, **kw: [Box("挑战成功", 1), Box("剩余180", 2)]
    t.result = (True, 60)
    t.use_stamina(once=60)
    check("一直没有 数/数：-1，不当 0", t.read, (-1, -1, -1))
    check("领奖框里读了 5 次", sum(m.startswith("体力读字原文领奖框") for m in t.logs), 5)
    check("每次之间睡 1 秒", t.sleeps, [1, 1, 1, 1])
    check("留了 stamina_error 图", "stamina_error" in t.shots)

    # 2026-09-13 09:33:01 (test_outcome.py:127): outside the dialog, one read.
    t = wire(object.__new__(TacetTask))
    t.wait_ocr = lambda *a, **kw: [Box("55", 1), Box("239/240", 2), Box("+", 3)]
    check("书页上读一次：239 + 55", t.get_stamina(), (239, 55, 294))
    check("书页上只读一次", sum(m.startswith("体力读字原文") for m in t.logs), 1)

    # ---------------------------------------------------------------------------
    # 2026-11-13: the stamina on the cultivation target's boss material (莉莉, 共鸣者突破材料),
    # on while the marker file is there; the tacet farm takes whatever is left.
    boss_file = os.path.join(tmp, "ark-okww-boss-material.json")
    ns["BOSS_MATERIAL_FILE"] = boss_file
    real_boss = ns["_boss_material"]
    boss_calls = []

    def boss_stub(result=None, error=None):
        def stub(task):
            boss_calls.append(type(task).__name__)
            EV.append("boss")
            if error is not None:
                raise error
            return result
        return stub

    print("\n[强敌领奖：没有标记文件，一字不差照旧]")
    ns["_boss_material"] = boss_stub("complete")
    boss_calls.clear()
    d = daily(USED_PART)
    d.run()
    check("没碰强敌那条", boss_calls, [])
    check("照旧刷无音区", farm_calls(), [("farm_tacet", 0, d.config)])
    check("没有强敌的话", any(ns["BOSS_LINE"] in m for m in d.farms[TacetTask].logs), False)

    print("\n[强敌领奖：标记在，只刷强敌，无音区关着（他 11-13：没刷完别去刷无音区，下一个刷什么未定）]")
    Path(boss_file).write_text('{"target": "莉莉"}', encoding="utf-8")
    for got in ("complete", "short", "off", "laps"):
        ns["_boss_material"] = boss_stub(got)
        boss_calls.clear()
        d = daily(USED_PART)
        d.run()
        check(f"{got}：强敌那条跑了一次，在 TacetTask 上", boss_calls, ["TacetTask"])
        check(f"{got}：无音区没刷", farm_calls(), [])
        check(f"{got}：说了这趟怎么结束、无音区不刷",
              any(f"这趟结束（{got}），无音区不刷" in m for m in d.farms[TacetTask].logs))
        check(f"{got}：日常照领", "claim_daily" in EV)
    print("\n[强敌领奖：上游闸门关着（已用 180）时，补刷那条也只走强敌]")
    ns["_boss_material"] = boss_stub("short")
    boss_calls.clear()
    d = daily(USED_FULL)
    d.run()
    check("补刷走的也是强敌，一次", (boss_calls, farm_calls()), (["TacetTask"], []))

    print("\n[强敌领奖：出错不拖垮，回主界面，剩下的体力不刷（无音区关着）]")
    ns["_boss_material"] = boss_stub(error=RuntimeError("培养目标页上没认出"))
    d = daily(USED_PART)
    d.run()
    farm = d.farms[TacetTask]
    check("记了错", any("出错，剩下的体力不刷（无音区关着）" in m for m in farm.logs))
    check("回了主界面", "ensure_main" in EV)
    check("无音区没刷、日常照领", (farm_calls(), "claim_daily" in EV), ([], True))

    print("\n[强敌领奖：OK-WW 的停止信号照原样往上抛]")
    ns["_boss_material"] = boss_stub(error=Disabled())
    d = daily(USED_PART)
    try:
        d.run()
        raised = False
    except Disabled:
        raised = True
    check("往上抛", raised)
    check("没再刷无音区", farm_calls(), [])

    print("\n[强敌领奖：凝素领域 / 模拟领域不走强敌那条]")
    ns["_boss_material"] = boss_stub("complete")
    for target, name in ((SUPPORT[1], "farm_forgery"), (SUPPORT[2], "farm_simulation")):
        boss_calls.clear()
        d = daily(USED_PART, target=target)
        d.run()
        check(f"{name}：没碰强敌", boss_calls, [])
        check(f"{name}：照旧", farm_calls(), [(name, 0, d.config)])

    print("\n[强敌领奖：标记文件的内容]")
    want = ns["_boss_material_want"]
    check("莉莉，行名默认共鸣者突破材料", want(), {"target": "莉莉", "row": "共鸣者突破材料"})
    Path(boss_file).write_text("{坏的", encoding="utf-8")
    check("坏 JSON：说不能用，不当成开着", "error" in want())
    Path(boss_file).write_text('{"row": "共鸣者突破材料"}', encoding="utf-8")
    check("没写培养目标：说不能用", "error" in want())
    os.remove(boss_file)
    check("没有文件：None", want(), None)

    class B:
        """ok-script's Box as far as the overlay reads it: str() is its text (ok Box.__str__)."""
        def __init__(self, name, x, y, w=120, h=33):
            self.name, self.x, self.y, self.width, self.height = name, x, y, w, h

        def __str__(self):
            return self.name

    # The 培养目标 page as seen 2026-11-13 04:34:11, scaled to 1920x1080: three rows 150 apart.
    PAGE = [B("培养目标", 288, 155), B("莉莉", 288, 190), B("所需材料", 940, 155),
            B("武器经验材料", 765, 270), B("106/106", 1085, 305, 60, 20), B("21/79", 1430, 305, 60, 20),
            B("直接挑战", 1650, 270),
            B("共鸣者突破材料", 765, 420), B("1/46", 1430, 455, 50, 20), B("直接挑战", 1650, 420),
            B("武器与技能素材", 765, 570), B("1/31", 1085, 605, 50, 20), B("0/87", 1430, 605, 50, 20),
            B("直接挑战", 1650, 570),
            B("156", 1100, 50), B("152/240", 1340, 50)]
    print("\n[强敌领奖：培养目标页上认那一行（真实截图的位置）]")
    owned, need, btn = ns["_boss_row"](PAGE, "共鸣者突破材料")
    check("数量读的是这一行的 1/46，不是上下两行", (owned, need), (1, 46))
    check("直接挑战是这一行的", getattr(btn, "y", None), 420)
    check("没有这一行：三个 None", ns["_boss_row"](PAGE[:3], "共鸣者突破材料"), (None, None, None))

    print("\n[强敌领奖：整趟走一遍——差两个，领一次，再读够了就停]")
    ns["_boss_material"] = real_boss
    Path(boss_file).write_text('{"target": "莉莉"}', encoding="utf-8")

    def page(owned_now, target="莉莉"):
        out = [b for b in PAGE if b.name not in ("1/46", "莉莉")]
        return out + [B(target, 288, 190), B(f"{owned_now}/46", 1430, 455, 50, 20)]

    # The boss's reward dialog as seen 2026-11-13 04:45:58 (boss_material_no_claim, 1920x1080): the bar
    # read 「156」 at x1186 y48 and 「154/240」 at x1410 y44; the dialog has the title 领取奖励, then the
    # sentence that asks for 60 waveplates, then the two buttons 取消 (cancel) and 确认 (confirm).
    def dialog(wave, spare):
        return [B(str(spare), 1186, 48), B(f"{wave}/240", 1410, 44), B("领取奖励", 450, 350),
                B("领取奖励需消耗60点结晶波片，请确认是否领取？", 630, 520), B("取消", 640, 678), B("确认", 1260, 678)]

    def fake_task(owned_now=44, wave=152, spare=156, target="莉莉", topup=0, settle=True, claim_dialog=True):
        t = wire(object.__new__(TacetTask))
        t.state = {"owned": owned_now, "wave": wave, "spare": spare, "screen": "world", "topups": topup}
        t.steps = []

        def book(feature=""):
            t.steps.append("book")
            t.state["screen"] = "page"
        t.openF2Book = book
        t.click_relative = lambda x, y, **kw: t.steps.append(("click", x, y))
        t.box_of_screen = lambda *a, **kw: None
        t.height_of_screen = lambda f: int(1080 * f)

        def ocr(box=None, **kw):
            sc = t.state["screen"]
            if sc == "page":
                return page(t.state["owned"], target)
            if sc == "dialog":
                return dialog(t.state["wave"], t.state["spare"])
            if sc == "settle":
                return [B("挑战成功", 900, 200), B("退出副本", 700, 950), B("重新挑战", 1200, 950)]
            return []
        t.ocr = ocr
        t.get_stamina = lambda: (t.state["wave"], t.state["spare"], t.state["wave"] + t.state["spare"])
        t.back = lambda after_sleep=0: t.steps.append("back")
        t.click_box = lambda b, after_sleep=0: t.steps.append(("box", b.name, b.y))
        t.click_team_challenge = lambda: t.steps.append("challenge")
        t.wait_in_team_and_world = lambda time_out=0: None
        t.combat_once = lambda **kw: t.steps.append("fight")
        t.walk_to_treasure = lambda: t.steps.append("walk")

        def f(handle_claim=True):
            t.steps.append(("f", handle_claim))
            if claim_dialog:
                t.state["screen"] = "dialog"
        t.pick_f = f
        t.info_incr = lambda k, v: t.info.__setitem__(k, t.info.get(k, 0) + v)
        t.wait_until = lambda cond, time_out=0, raise_if_not_found=False, **kw: cond()

        def left():
            t.steps.append("cancel")
            t.state["screen"] = "world"
        t.click_dialog_left_button = left

        def take():
            t.state["owned"] += 4
            t.state["wave"] -= 60
            t.state["screen"] = "settle" if settle else "world"

        def right():
            # The game: under 60 waveplates (or a forced top-up) the 「补充结晶波片」 dialog comes first.
            t.steps.append("confirm")
            if t.state["topups"] > 0 or t.state["wave"] < 60:
                t.state["screen"] = "topup"
                return "btn"
            take()
            return "btn"
        t.click_dialog_right_button = right

        def wait_feature(name, **kw):
            return t.state["screen"] == "topup"
        t.wait_feature = wait_feature

        def click(btn, after_sleep=0):
            # After the two top-up clicks: the backup became waveplates, 确认 again.
            t.steps.append(("again", btn))
            t.state["topups"] = 0
            t.state["wave"] += t.state["spare"]
            t.state["spare"] = 0
            if t.state["wave"] >= 60:
                take()
            else:
                t.state["screen"] = "topup"
        t.click = click

        def wait_click_ocr(match=None, **kw):
            if t.state["screen"] == "settle" and match.search("退出副本"):
                t.steps.append("exit")
                t.state["screen"] = "world"
                return True
            return None
        t.wait_click_ocr = wait_click_ocr
        return t

    t = fake_task()
    check("44/46：领一次（+4），48/46 后停在 complete", real_boss(t), "complete")
    check("确认只点了一次", t.steps.count("confirm"), 1)
    check("点的是莉莉那一行的直接挑战", ("box", "直接挑战", 420) in t.steps)
    check("顺序：书 → 培养目标 → 直接挑战 → 开启挑战 → 打 → 走到宝箱 → F（不让上游取消）→ 确认 → 退出副本",
          [s if not isinstance(s, tuple) else s[0] for s in t.steps][:9],
          ["book", "click", "box", "challenge", "fight", "walk", "f", "confirm", "exit"])
    check("按 F 时 handle_claim=False", ("f", False) in t.steps)
    check("记了花的体力 60", t.info.get("used stamina"), 60)
    check("留了领奖图", "boss_material_claimed" in t.shots)
    check("每圈开头都读一次数量（44 → 48）", [m for m in t.logs if m.startswith(ns["BOSS_LINE"] + "莉莉的共鸣者突破材料 ")],
          [ns["BOSS_LINE"] + "莉莉的共鸣者突破材料 44/46", ns["BOSS_LINE"] + "莉莉的共鸣者突破材料 48/46"])
    check("领奖框上读了顶栏", any("领奖框：顶栏读到波片 152/240，备用 156" in m for m in t.logs))

    t = fake_task(owned_now=10)
    check("10/46、波片 152 + 备用 156：领到不够一次为止", real_boss(t), "short")
    check("领了 5 次（152→92→32，补备用 188→128→68→8），补充框只出一次",
          (t.info.get("used stamina"), t.steps.count(("again", "btn"))), (300, 1))
    check("剩 8 停下，说了不够", any("体力 8 + 备用 0 不够领一次的 60" in m for m in t.logs))

    t = fake_task(owned_now=46)
    check("已经够了：一次不打", (real_boss(t), "fight" in t.steps), ("complete", False))
    t = fake_task(wave=10, spare=20)
    check("体力 + 备用不够 60：一次不打", (real_boss(t), "fight" in t.steps), ("short", False))
    t = fake_task(target="锁暝")
    check("培养目标换了人：不打，回 off", (real_boss(t), "fight" in t.steps), ("off", False))
    check("培养目标换了人：留图、记错", ("boss_material_target" in t.shots,
                                       any("培养目标不是莉莉" in m for m in t.logs)), (True, True))

    print("\n[强敌领奖：波片 30 + 备用 156——游戏弹补充框，用备用，再点一次确认]")
    t = fake_task(wave=30, spare=156, topup=1)
    real_boss(t)
    check("补充框：点了两下 (0.70, 0.71)、返回、再确认", (("click", 0.70, 0.71) in t.steps, ("again", "btn") in t.steps),
          (True, True))
    check("说了动用备用体力", any("动用备用体力" in m for m in t.logs))

    print("\n[强敌领奖：波片读到 152 够领，游戏却弹补充框——不点补充，抛出]")
    t = fake_task(wave=152, topup=1)
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("抛出并说清", "游戏却弹了补充波片的框" in got)
    check("取消了，没点补充", ("cancel" in t.steps, ("click", 0.70, 0.71) in t.steps), (True, False))

    print("\n[强敌领奖：波片 20 + 备用 20 不够一次——取消，不动备用]")
    t = fake_task(wave=20, spare=20)
    t.get_stamina = lambda: (80, 0, 80)          # the page read said enough; the dialog's bar says not
    check("返回 short", real_boss(t), "short")
    check("点了取消，没点确认", ("cancel" in t.steps, "confirm" in t.steps), (True, False))

    print("\n[强敌领奖：按 F 没出「领取奖励」框——留图抛出（外面交给无音区）]")
    t = fake_task(claim_dialog=False)
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("抛出", ("没出「领取奖励」框" in got, "boss_material_no_claim" in t.shots), (True, True))

    print("\n[强敌领奖：确认后没等到「退出副本」——留图抛出]")
    t = fake_task(settle=False)
    try:
        real_boss(t)
        got = "went on"
    except RuntimeError as exc:
        got = str(exc)
    check("抛出", ("没等到结算页的「退出副本」" in got, "boss_material_no_settlement" in t.shots), (True, True))
    os.remove(boss_file)

    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_merge_step():
    """The step list does not claim 「声骸五合一」 from the line logged before the merge.

collector_okww._okww_steps added 「声骸五合一」 whenever 「check discarded echo」 was in
the log - a line upstream writes before merging. When MergeEchoTask then fails,
upstream logs 「… Failed」 and carries on; the failure reaches the group through
gamelog_errors.check_round, while the report listed the merge as done beside that
alarm (audit 2026-10-13 item 16). The label is gone; the garden's 「不算完成」 stays.

    Formerly test_okww_merge_step.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww as co


    T = "2026-10-12 10:{:02d}:00,000 {} TaskExecutor {}"
    MERGE_FAILED = "\n".join([
        T.format(1, "INFO", "MergeEchoTask:check discarded echo"),
        T.format(2, "ERROR", "MergeEchoTask:MergeEchoTask Failed"),
    ])
    GARDEN = T.format(3, "INFO", "GardenTask:garden counter 2/3")

    print("[merge started and failed: not listed as done]")
    steps = co._okww_steps(MERGE_FAILED, 0)
    check("no 声骸五合一", any("五合一" in s for s in steps), False)

    print("\n[the garden's 「不算完成」 marking is unchanged]")
    check("garden ran, not read as done", co._okww_steps(GARDEN, 0), ["周常乐园（没读到做完，不算完成）"])

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_plan_bits():
    """Tomorrow's OK-WW plan lines, read from the master config that takes effect.

plan._okww_plan_bits and plan._okww_extra_bit had no test (audit 2026-10-05,
E). They are not dead code - plan.py:665 and :365 call them - so they get
behaviour tests instead of deletion. Pinned here: the master DailyTask.json is
read, quick config overrides it when on, the weekly-boss commandeering of
「Teleport and Farm 4C Echo」 is reported as the weekly boss, and nothing at all
is said when there is nothing to read.

    Formerly test_okww_plan_bits.py.
    """
    import json
    import os
    from unittest import mock

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    os.environ["ARK_STATE_DIR"] = str(tmpdir())        # no no-stamina-farm flag
    os.environ.pop("ARK_OKWW_DIR", None)
    from ark_relay.core import plan


    def automas(daily, *, farm=None, quick=None):
        root = tmpdir()
        d = root / "data" / "okww-sid" / "Default" / "ConfigFile"
        d.mkdir(parents=True)
        (d / "DailyTask.json").write_text(json.dumps(daily), encoding="utf-8")
        if farm is not None:
            (d / "FarmEchoTask.json").write_text(json.dumps(farm), encoding="utf-8")
        if quick is not None:
            (root / "config").mkdir()
            (root / "config" / "ScriptConfig.json").write_text(json.dumps({
                "s9": {"Info": {"Name": "OK-WW"},
                       "SubConfigsInfo": {"UserData": {"u1": {
                           "Info": {"IfQuickConfig": True}, "Task": quick}}}}}), encoding="utf-8")
        return root, d


    print("[_okww_plan_bits]")
    check("no AUTO-MAS dir -> nothing", plan._okww_plan_bits(None), [])
    check("no data dir -> nothing", plan._okww_plan_bits(tmpdir()), [])

    root, _ = automas({"Which to Farm": "Simulation Challenge", "Material Selection": "Shell Credit",
                       "Additional Tasks to Run After Daily Task": ["Auto Farm all Nightmare Nest"]})
    bits = plan._okww_plan_bits(root)
    check("master read: stamina line", bits[0], "体力刷 模拟领域·贝币")
    check("master read: nest farmed to full", any("全部点位，刷到打满" in b for b in bits), True)
    check("nest-full is not repeated as an extra task", any(b.startswith("附加") for b in bits), False)

    root, _ = automas({"Which to Farm": "Simulation Challenge", "Material Selection": "Shell Credit",
                       "Additional Tasks to Run After Daily Task": []},
                      quick={"WhichToFarm": "Simulation Challenge", "MaterialSelection": "Weapon EXP",
                             "WhichTacetSuppressionToFarm": 1, "WhichForgeryChallengeToFarm": 1,
                             "FarmNightmareNestForDailyEcho": False, "AdditionalTasks": []})
    check("quick config on -> its value wins over the master",
          plan._okww_plan_bits(root)[0], "体力刷 模拟领域·武器经验")

    print("[_okww_extra_bit]")
    _, d = automas({}, farm={"Teleport to Boss": "Weekly Challenge", "Boss Level": "90",
                             "Which Weekly Boss to Teleport": 2})
    with mock.patch.object(plan, "_weekly_boss_state", lambda: (False, "")):
        check("weekly-boss commandeered, not done -> fought tomorrow",
              plan._okww_extra_bit(d, ["Teleport and Farm 4C Echo"], {}),
              "附加 周本 战歌重奏第 2 个（90 级），明天会打")
    with mock.patch.object(plan, "_weekly_boss_state", lambda: (True, "鸣式·利维亚坦")):
        check("weekly-boss quota full -> says not fought",
              plan._okww_extra_bit(d, ["Teleport and Farm 4C Echo"], {}),
              "附加 周本 鸣式·利维亚坦（90 级），本周已打满，明天不打")
    _, d2 = automas({}, farm={"Teleport to Boss": "Normal"})
    check("not commandeered -> named as the echo task (translated when the pack has it)",
          plan._okww_extra_bit(d2, ["Teleport and Farm 4C Echo"], {"Teleport and Farm 4C Echo": "传送刷4C声骸"}),
          "附加 传送刷4C声骸")
    check("more than two -> first two and a count",
          plan._okww_extra_bit(d2, ["A", "B", "C"], {}), "附加 A、B 等 3 项")
    check("only nest-full / nothing -> no line",
          (plan._okww_extra_bit(d2, ["Auto Farm all Nightmare Nest"], {}), plan._okww_extra_bit(d2, [], {})),
          ("", ""))


def _part_okww_revive_and_retry():  # noqa: C901 - the whole body of the file this part was
    """Echo farm and weekly boss: deaths go to upstream, and retries stop after three failures.

Runs the real overlay against stand-ins for upstream v3.7.4 (FarmEchoTask.py:92-106
revive_action, :108-125 run, :182-183 the is_revived continue, :216-229 the do_run
re-teleport) and checks:

  revive_action   not overridden any more (2026-10-13). Ours confirmed the revive
                  popup inside a realm while farming echoes and spent a revive item
                  per death; v3.7.4 hands a realm death to BaseCombatTask.revive_action
                  (:227-240), which cancels the popup and leaves the realm to heal,
                  and do_run re-teleports (at most 3 times per run)
  combat_once     swallows CharRevivedException only when the revive put us back at
                  the boss (is_revived: upstream's overworld revive), so the loop takes
                  its `if self.is_revived: continue`; a realm death (echo farm or
                  weekly boss) goes up to upstream's do_run handler, which re-teleports
  FarmEchoTask.run  upstream v3.7.4 retries by calling self.run(retries - 1) from its
                  own except (FarmEchoTask.py:122-123), so the wrapper must take and
                  pass on `retries` (10-13: it took none, and the retry was a
                  TypeError); it stops at _MAX_FARM_RETRIES and leaves the depth
                  counter at 0 for the next run
  scope           the one realm death on record (tests/replay/2026-09-01) was raised
                  from inside combat_once, which is where the overlay looks at it

    Formerly test_okww_revive_and_retry.py.
    """
    import os
    import re
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay


    REPLAY = Path(__file__).resolve().parent / "replay"


    class Disabled(Exception):
        """ok.TaskDisabledException."""


    class Revived(Exception):
        """src.task.BaseCombatTask.CharRevivedException."""


    class _Any(type):
        """A stand-in upstream class: any method the overlay reads exists and does nothing."""
        def __getattr__(cls, name):
            if name.startswith("__"):
                raise AttributeError(name)

            def anything(self, *a, **kw):
                return None
            return anything


    class Box:
        """ok-script's OCR box: the overlay reads .name and str()."""
        def __init__(self, name, x=0, y=0, width=10, height=10):
            self.name, self.x, self.y, self.width, self.height = name, x, y, width, height

        def __str__(self):
            return f"Box(name='{self.name}', x={self.x}, y={self.y}, width={self.width}, height={self.height})"


    class BaseWWTask(metaclass=_Any):
        pass


    class FarmEchoTask(BaseWWTask):
        def revive_action(self):
            # Upstream v3.7.4 FarmEchoTask.py:92-106, reduced: in a realm it hands over to
            # BaseCombatTask.revive_action (:227-240: close_revive_popup cancels the popup,
            # then leave and heal; returns True, is_revived untouched); in the overworld it
            # walks back to the boss and sets is_revived.
            if not self._in_realm:
                self.events.append("upstream-revive")
                self.is_revived = True
                return True
            self.events.append("cancel-popup")
            return True

        def run(self, retries=3):
            # Upstream v3.7.4 FarmEchoTask.py:108-125, verbatim apart from the stand-ins
            # (start_time and WWOneTimeTask.run left out): the retry is self.run(retries - 1)
            # from its own except, i.e. through whatever FarmEchoTask.run is bound to.
            self.retries_seen.append(retries)
            try:
                return self.do_run()
            except Disabled:
                pass
            except Exception:
                self.log_info("farm 4c error, try handle monthly card")
                if retries > 0 and (self.handle_claim_button() or self.handle_monthly_card()):
                    self.run(retries - 1)
                else:
                    raise

        def do_run(self):
            self.bodies += 1
            if self.bodies <= self.failures:
                raise RuntimeError("Teleport to boss failed")
            return "farmed"

        def handle_claim_button(self):
            return self.claim_button

        def handle_monthly_card(self):
            return False

        def combat_once(self, wait_combat_time=200, raise_if_not_found=True, target=False):
            # What BaseCombatTask.raise_not_in_combat (:310-332) does on a death: call
            # revive_action, then raise CharRevivedException when it returned True.
            if self.dies:
                if self.revive_action():
                    raise Revived("combat check not in combat")
                raise RuntimeError("revive failed")
            return True


    mods = {
        "ok": types.SimpleNamespace(TaskDisabledException=Disabled,
                                    Logger=types.SimpleNamespace(get_logger=lambda n: types.SimpleNamespace(
                                        info=lambda *a, **k: None, error=lambda *a, **k: None))),
        "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
        "src.task.BaseCombatTask": types.SimpleNamespace(CharRevivedException=Revived),
        "src.task.BaseWWTask": types.SimpleNamespace(BaseWWTask=BaseWWTask),
        "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=FarmEchoTask),
    }
    for name in ("DailyTask", "ForgeryTask", "SimulationTask", "TacetTask"):
        mods[f"src.task.{name}"] = types.SimpleNamespace(**{name: _Any(name, (), {})})
    _saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    # The function itself, not its name: a class made inside a part is named
    # "_part_okww_revive_and_retry.<locals>.FarmEchoTask".
    upstream_revive = FarmEchoTask.__dict__["revive_action"]
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    print("[绑定都换上了]")
    for b in ("FarmEchoTask.combat_once", "FarmEchoTask.run"):
        check(f"{b} 已换上", b in ns["_applied"])
    print("[revive_action is upstream's own again]")
    check("revive_action not in the applied list", "FarmEchoTask.revive_action" in ns["_applied"], False)
    check("FarmEchoTask.revive_action is still upstream's function",
          FarmEchoTask.__dict__["revive_action"] is upstream_revive, True)
    check("the overlay source has no revive_action override",
          '@override(FarmEchoTask, "revive_action")' in okww_overlay.source_text(), False)

    # farming_echoes() is 「the no-claim flag file exists」; point it at a temp file.
    tmp = str(tmpdir("ark-revive-"))
    flag = os.path.join(tmp, "ark-okww-farm.no-claim")
    ns["NO_CLAIM"] = flag

    def task(in_realm=True):
        t = object.__new__(FarmEchoTask)
        t.events, t.logs, t.clicks, t.waits = [], [], [], []
        t._in_realm = in_realm
        t.is_revived = False
        t.dies = False
        t.bodies, t.failures, t.claim_button = 0, 0, True
        t.retries_seen = []
        t.log_info = lambda msg, notify=False: t.logs.append(msg)
        t.log_error = lambda msg, notify=False, **kw: t.logs.append(msg)
        t.click = lambda target, after_sleep=0: t.clicks.append(str(getattr(target, "name", target)))
        t.wait_in_team_and_world = lambda time_out=10, **kw: t.waits.append(time_out) or True
        return t


    # ---------------------------------------------------------------------------
    print("\n[revive_action: a realm death while farming echoes runs upstream's revive (cancel the popup), no revive item]")
    Path(flag).write_text("")
    t = task()
    check("returns upstream's result", t.revive_action(), True)
    check("upstream cancelled the popup", t.events, ["cancel-popup"])
    check("nothing clicked by the overlay (no 「确认」, no revive item)", t.clicks, [])
    check("is_revived not set (do_run re-teleports)", t.is_revived, False)
    os.remove(flag)

    # ---------------------------------------------------------------------------
    print("\n[combat_once: a realm death while farming echoes goes up to upstream's do_run re-teleport]")
    Path(flag).write_text("")
    t = task()
    t.dies = True
    try:
        t.combat_once(wait_combat_time=5, raise_if_not_found=False)
        raised = False
    except Revived:
        raised = True
    check("CharRevivedException goes up (do_run: re-teleport, cap 3)", raised)
    check("did not say it carries on in place", any("复活成功" in m for m in t.logs), False)
    os.remove(flag)

    print("\n[combat_once：上游的复活（周本）照样往上抛，交给 do_run 重新传送]")
    t = task()
    t.dies = True
    try:
        t.combat_once(wait_combat_time=5, raise_if_not_found=False)
        raised = False
    except Revived:
        raised = True
    check("CharRevivedException 往上抛", raised)
    check("没说「接着刷」", any("复活成功" in m for m in t.logs), False)

    print("\n[combat_once：上游大世界那份复活也回到了 boss 跟前（is_revived），同样接着刷、不受 3 次上限]")
    t = task(in_realm=False)
    t.dies = True
    check("返回 None，不往上抛", t.combat_once(), None)
    check("走的是上游的复活", t.events, ["upstream-revive"])
    check("is_revived 留着", t.is_revived, True)

    print("\n[combat_once：没死就原样返回]")
    t = task()
    check("返回上游的结果", t.combat_once(), True)

    # ---------------------------------------------------------------------------
    print("\n[FarmEchoTask.run：上游自己的 except 里无限重试，包一层数到 3 就停——按失败结束，不是跳过]")
    cap = ns["_MAX_FARM_RETRIES"]
    check("上限是 3", cap, 3)
    t = task()
    t.failures = 99
    got = None
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("连续失败：任务按失败结束（OK-WW 记失败的普通异常）", type(got).__name__, "ArkStopped")
    check("不是 OK-WW 的「跳过」（TaskDisabledException）", isinstance(got, Disabled), False)
    check("失败原因写在异常里", str(got), f"连续 {cap} 次失败，退出本次任务，不再重试")
    check("上游正文只跑了 3 次", t.bodies, cap)
    check("日志：连续 3 次失败", any(f"连续 {cap} 次失败，退出本次任务，不再重试" in m for m in t.logs))
    check("日志：按失败结束", any(m.startswith(ns["FAILED_MARK"]) for m in t.logs))
    check("上游每次都记了 farm 4c error", sum("farm 4c error" in m for m in t.logs), cap)
    check("深度计数归零", t._ark_depth, 0)

    print("\n[FarmEchoTask.run：下一次运行从 0 数起]")
    t.bodies = 0
    try:
        t.run()
    except ns["ArkStopped"]:
        pass
    check("又是 3 次", t.bodies, cap)
    check("深度计数归零", t._ark_depth, 0)

    print("\n[FarmEchoTask.run：中途认不出的画面停下（_stop）——上游 run() 照常收尾，最外层按失败结束]")
    t = task()
    t.screenshot = lambda name: t.events.append(f"shot {name}")


    def _odd_lap(self=t):
        self.bodies += 1
        ns["_stop"](self, "weekly_claim_unchanged", "周本领奖：回读次数没变（2/3），这次没领到")
    t.do_run = _odd_lap
    got = None
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("按失败结束", (type(got).__name__, str(got)), ("ArkStopped", "周本领奖：回读次数没变（2/3），这次没领到"))
    check("上游的 except TaskDisabledException 收了这一停：没重试、没 farm 4c error",
          (t.bodies, any("farm 4c error" in m for m in t.logs)), (1, False))
    check("留了图", "shot weekly_claim_unchanged" in t.events, True)
    check("深度计数归零、原因清掉", (t._ark_depth, t._ark_failed), (0, None))

    print("\n[FarmEchoTask.run: a waveplate shortage (_skip_short) is a normal state - returns, no FAILED_MARK, no ArkStopped]")
    t = task()


    def _short_lap(self=t):
        self.bodies += 1
        self.log_info("波片不足挡住开启挑战，点取消跳过本次周本")
        ns["_skip_short"](self)
    t.do_run = _short_lap
    got = "returned"
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("缺波片：正常返回，不抛 ArkStopped", got, "returned")
    check("缺波片：日志没有按失败结束", any(m.startswith(ns["FAILED_MARK"]) for m in t.logs), False)
    check("缺波片：上游收了这一停，没重试", (t.bodies, any("farm 4c error" in m for m in t.logs)), (1, False))
    check("缺波片：深度归零、没留原因", (t._ark_depth, t._ark_failed), (0, None))

    print("\n[FarmEchoTask.run: a non-waveplate stop right after still raises ArkStopped]")
    t = task()
    t.screenshot = lambda name: t.events.append(f"shot {name}")


    def _odd_lap2(self=t):
        self.bodies += 1
        ns["_stop"](self, "weekly_claim_unchanged", "周本领奖：回读次数没变（2/3），这次没领到")
    t.do_run = _odd_lap2
    got = None
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("非波片停下仍按失败结束", (type(got).__name__, str(got)), ("ArkStopped", "周本领奖：回读次数没变（2/3），这次没领到"))
    check("非波片停下：日志写了按失败结束", any(m.startswith(ns["FAILED_MARK"]) for m in t.logs), True)

    print("\n[FarmEchoTask.run：真没事可做（上游自己的跳过）照旧是跳过]")
    t = task()


    def _done_lap(self=t):
        self.bodies += 1
        raise Disabled()
    t.do_run = _done_lap
    got = "returned"
    try:
        t.run()
    except Exception as e:  # noqa: BLE001
        got = e
    check("上游的跳过：正常返回，不算失败", got, "returned")

    print("\n[FarmEchoTask.run：第 2 次成了就不再报停]")
    t = task()
    t.failures = 1
    try:
        t.run()
        stopped = False
    except Disabled:
        stopped = True
    check("没抛", stopped, False)
    check("跑了 2 次", t.bodies, 2)
    check("没说连续失败", any("连续" in m for m in t.logs), False)
    check("深度计数归零", t._ark_depth, 0)
    check("v3.7.4 retry count passed through the wrapper: 3, then 2", t.retries_seen, [3, 2])

    print("\n[FarmEchoTask.run: v3.7.4 self.run(retries - 1) goes through the wrapper without a TypeError]")
    t = task()
    t.failures = 1
    got = None
    try:
        got = t.run()
    except TypeError as e:  # the 10-13 bug: the wrapper was def run(self)
        got = f"TypeError: {e}"
    check("retry after one failure returns upstream's result", got, None)
    check("upstream body ran twice", t.bodies, 2)
    check("each retry reached upstream with one less", t.retries_seen, [3, 2])
    t = task()
    t.failures = 0
    check("run(retries=1) reaches upstream as 1", (t.run(1), t.retries_seen), ("farmed", [1]))

    print("\n[FarmEchoTask.run：上游自己放弃（没领奖按钮也没月卡）时原样抛]")
    t = task()
    t.failures, t.claim_button = 99, False
    try:
        t.run()
        got = None
    except RuntimeError as e:
        got = str(e)
    check("上游的错原样上来", got, "Teleport to boss failed")
    check("只跑了 1 次", t.bodies, 1)
    check("深度计数归零", t._ark_depth, 0)

    # ---------------------------------------------------------------------------
    print("\n[有记录的那次副本里阵亡，是在 combat_once 里抛的（覆盖面就在那儿）]")
    log = (REPLAY / "2026-09-01" / "wuwa" / "OK-WW-02-01-22.log").read_text(encoding="utf-8")
    dead = log.index("FarmEchoTask:raise_not_in_combat char dead")
    check("2026-09-01 06:03:27 阵亡", "2026-09-01 06:03:27,238 INFO TaskExecutor FarmEchoTask:raise_not_in_combat char dead" in log)
    check("上游当时复活失败", "06:03:27,239 INFO TaskExecutor FarmEchoTask:info_set Revive Failed" in log)
    trace = log[dead:dead + 1500]
    check("报错的那一圈停在 farm 4c error", "farm 4c error, try handle monthly card" in trace)
    check("调用栈里是 do_run → combat_once", bool(re.search(r"in do_run\s+self\.combat_once\(", trace)))

    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_stamina_end():
    """结束时的剩余波片要认 OK-WW 自己报的那个数。

2026-08-28 那轮实际把体力刷到 0，报告却写「剩余波片 80/240」。
原因是我们取 `info_set current_stamina` 的最后一条，而那是**每轮开打前**
记的；之后又刷了一轮但不再记数，所以永远多算一轮。

用户当场指出两件事：一是这轮其实刷干净了、是我们误报；二是「用尽」并不等于 0，
OK-WW 的判定是「剩余不足以再开一次」，而单次消耗还会在 40/80 之间自动切换，
外部根本推算不出来。

好在 OK-WW 停手时自己会打一行 `current stamina: N not enough to continue`，
那才是结束时的真实余量。下面这段日志是 2026-08-28 的原文。

    Formerly test_okww_stamina_end.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import collector

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    REAL = """
2026-08-28 13:40:57,971 INFO TaskExecutor ForgeryTask:info_set current_stamina 240
2026-08-28 13:41:59,293 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 240 >= 80
2026-08-28 13:42:49,641 INFO TaskExecutor ForgeryTask:info_set current_stamina 160
2026-08-28 13:42:49,641 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 160 >= 80
2026-08-28 13:43:40,617 INFO TaskExecutor ForgeryTask:info_set current_stamina 80
2026-08-28 13:43:40,618 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 80 >= 80
2026-08-28 13:43:44,857 INFO TaskExecutor BaseWWTask:current stamina: 0 not enough to continue
2026-08-28 13:43:48,859 INFO TaskExecutor ForgeryTask:used all stamina
2026-08-28 13:44:57,176 INFO TaskExecutor DailyTask:Daily Task Completed
"""

    NO_END_LINE = "\n".join(
        l for l in REAL.splitlines() if "not enough to continue" not in l)

    NEST = """
2026-08-29 00:21:27,418 INFO TaskExecutor NightmareNestTask:Box(name='已击败残象：26/41', x=890) is not complete
2026-08-29 00:23:27,182 INFO TaskExecutor NightmareNestTask:nightmare nest: 指定点位都已打满，跳过
"""


    def _parse(text):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "OK-WW.log"
            f.write_text(text, encoding="utf-8")
            return collector.parse_okww_log(f)


    def main() -> int:
        print("=== 08-28 的真实日志 ===")
        out = _parse(REAL)
        check("剩余取 OK-WW 自己报的 0，不是开打前的 80",
              out.get("okww_stamina_left"), 0)
        check("标明这是精确值", out.get("okww_stamina_left_exact"), True)

        print("\n=== 没有收尾那行时，退回旧读数但要标明不精确 ===")
        out2 = _parse(NO_END_LINE)
        check("退回最后一条开打前读数", out2.get("okww_stamina_left"), 80)
        check("标明不是结束余量", out2.get("okww_stamina_left_exact"), False)

        print("\n=== 残象聚落进度 ===")
        out3 = _parse(NEST)
        check("no okww_nest field (dropped 2026-10-13, read by nothing)", "okww_nest" in out3, False)
        check("抓到已打满", out3.get("okww_nest_full"), True)

        print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_okww_stamina_nest_verdict():
    """刷体力 and the nest item are judged from the lines of the task that did the work.

Three holes found 10-13 against upstream OK-WW v3.7.4 (on the game PC since 10-06):

  stamina (a)  「enter combat」 is CombatCheck.py:181, logged by every fighting task. The
               weekly boss and the nest (both run before stamina farming) print it,
               so a run that spent no stamina passed 刷体力. Only TacetTask /
               ForgeryTask / SimulationTask lines count now.
  stamina (b)  farm_tacet / farm_domain give up after three revives and return
               quietly (TacetTask.py:79, DomainTask.py:73, 「exceeded recovery
               retries (3), stop farming」): that is a failed 刷体力 now.
  stamina (c)  when our get_stamina override cannot read 数/数 it returns -1 and logs
               「按没读到处理（-1）」; upstream then says 「used all stamina」
               (TacetTask.py:63-66, :105) or 「not enough stamina」 (DomainTask.py:61-63)
               though nothing was read. With no stamina fight that is a failure.
  nest         「click_team_challenge」, 「wait_in_team_and_world」 and 「echo captured」 are
               never logged by upstream (BaseWWTask.py:678-683, :1115-1117 have no log
               call; 「echo captured」 is only an argument at NightmareNestTask.py:74,
               stored without logging at CombatCheck.py:58-61). They appear only in
               traceback frames of other tasks' errors (fixtures/m6-okww/0921-weekly.log:
               27-28), which booked an unreachable nest as fought. The daily-report
               step and the verdict now read one classifier, outcome.nest_state.

    Formerly test_okww_stamina_nest_verdict.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww, outcome

    FX = Path(__file__).resolve().parent / "fixtures"


    def line(t, who, msg):
        return f"2026-10-13 10:{t},000 INFO TaskExecutor {who}:{msg}\n"


    def stamina(text):
        got = [c for c in outcome.okww_checks(text, expect_nest=False, expect_daily=False) if c.label == "刷体力"]
        return (got[0].ok, got[0].detail) if got else None


    def stopped(text):
        out = {}
        collector_okww._okww_progress(text, out)
        return out.get("okww_stopped")


    # Read with a fallback so that the checks run, and fail, on code without them.
    UNREAD_SAY = getattr(outcome, "STAMINA_UNREAD_SAY", "体力读不出来，没刷")
    nest_state = getattr(outcome, "nest_state", lambda text: None)
    UNREAD = "体力读了 1 次都没有「数/数」，按没读到处理（-1），不当 0"

    print("[stamina (a): the weekly boss's and the nest's fights are not stamina farming]")
    weekly_only = (line("00:01", "FarmEchoTask", "teleport_to_boss prepared as realm")
                   + line("00:20", "FarmEchoTask", "enter combat None")
                   + line("01:30", "FarmEchoTask", "start walk_to_treasure")
                   + line("02:00", "NightmareNestTask", "enter combat None"))
    ok, why = stamina(weekly_only)
    check("weekly boss + nest fights only: 刷体力 not passed", ok, False)
    check("…and it says nothing was entered", "既没进本" in why)
    ok, _ = stamina(weekly_only + line("05:00", "TacetTask", "enter combat None"))
    check("a TacetTask fight passes", ok, True)
    ok, _ = stamina(weekly_only + line("05:00", "SimulationTask", "start walk_to_treasure"))
    check("a SimulationTask walk to the treasure passes", ok, True)
    ok, why = stamina(weekly_only + line("05:00", "ForgeryTask", "not enough stamina"))
    check("ForgeryTask 「not enough stamina」 with no fight: passed as a shortage", (ok, why), (True, "体力不足，本来就没得刷"))

    print("\n[stamina (d): the 「不刷体力」 flag file was there - not farmed, and said why]")
    flagged = (weekly_only
               + line("04:00", "TacetTask", "刷体力已禁用（标记文件在），这一趟不花波片")
               + line("06:00", "DailyTask", "Daily Task Completed"))
    ok, why = stamina(flagged)
    check("the flag line: 刷体力 not passed, with the flag as the reason", (ok, why), (False, "不刷体力的标记还在"))
    check("the daily report's stop reason says the same", stopped(flagged), "不刷体力的标记还在")
    ok, why = stamina(weekly_only + line("04:00", "ForgeryTask", "刷体力已禁用（标记文件在），这一趟不花波片"))
    check("ForgeryTask prefix too", (ok, why), (False, "不刷体力的标记还在"))

    print("\n[stamina (b): three revives and upstream stops farming - a failure]")
    died = (line("05:00", "TacetTask", "info_set current_stamina 180")
            + line("05:10", "TacetTask", "enter combat None")
            + line("05:40", "TacetTask", "farm_tacet: death recovered, re-enter from F2 book")
            + line("06:10", "TacetTask", "enter combat None")
            + line("06:40", "TacetTask", "farm_tacet: death recovered, re-enter from F2 book")
            + line("07:10", "TacetTask", "enter combat None")
            + line("07:40", "TacetTask", "farm_tacet: exceeded recovery retries (3), stop farming"))
    ok, why = stamina(died)
    check("farm_tacet exceeded recovery retries: 刷体力 failed", ok, False)
    check("…says the character died 3 times and farming stopped", ("死了 3 次" in why, "停止刷体力" in why), (True, True))
    check("daily report does not say 「体力不够再开一局」", stopped(died) == "体力不够再开一局", False)
    check("daily report gives the same reason", stopped(died), why)
    ok, _ = stamina(line("05:00", "ForgeryTask", "enter combat None")
                    + line("07:40", "ForgeryTask", "farm_domain: exceeded recovery retries (3), stop farming"))
    check("farm_domain exceeded recovery retries: failed too", ok, False)
    ok, _ = stamina(line("05:00", "TacetTask", "enter combat None")
                    + line("07:40", "FarmEchoTask", "farm 4c: exceeded recovery retries (3), stop farming"))
    check("the echo farm's own give-up is not a stamina failure", ok, True)

    print("\n[stamina (c): -1 read, then upstream's 「used all stamina」 / 「not enough stamina」]")
    tacet_unread = (line("05:00", "TacetTask", UNREAD)
                    + line("05:00", "TacetTask", "info_set current_stamina -1")
                    + line("05:02", "TacetTask", UNREAD)
                    + line("05:02", "TacetTask", "info_set current_stamina -1")
                    + line("05:03", "TacetTask", "used all stamina"))
    ok, why = stamina(weekly_only + tacet_unread)
    check("tacet: -1 twice then 「used all stamina」, no tacet fight: failed", ok, False)
    check("…says stamina could not be read", why, UNREAD_SAY)
    check("daily report says the same, not 「体力不够再开一局」", stopped(weekly_only + tacet_unread), UNREAD_SAY)
    domain_unread = (line("05:00", "SimulationTask", UNREAD)
                     + line("05:00", "SimulationTask", "info_set current_stamina -1")
                     + line("05:01", "SimulationTask", "not enough stamina"))
    ok, why = stamina(domain_unread)
    check("simulation: -1 then 「not enough stamina」: failed, not 「体力不足」", (ok, why), (False, UNREAD_SAY))
    check("daily report does not say 「一局都没开成」", stopped(domain_unread), UNREAD_SAY)
    reread = (line("05:00", "TacetTask", UNREAD)
              + line("05:00", "TacetTask", "info_set current_stamina -1")
              + line("05:02", "TacetTask", "info_set current_stamina 30")
              + line("05:03", "TacetTask", "used all stamina"))
    ok, why = stamina(reread)
    check("tacet: -1, then the click-and-reread got 30, then 「used all stamina」: a real shortage", (ok, why),
          (True, "体力不足，本来就没得刷"))
    check("…and the daily report keeps its usual wording", stopped(reread), "体力不够再开一局")
    after_fight = (line("05:00", "TacetTask", "info_set current_stamina 180")
                   + line("05:10", "TacetTask", "enter combat None")
                   + line("06:00", "TacetTask", "体力领奖框读了 3 次都没有「数/数」，按没读到处理（-1），不当 0"))
    ok, _ = stamina(after_fight)
    check("a -1 in the reward dialog after a tacet fight still passes", ok, True)
    ok, _ = stamina(line("05:00", "DailyTask", UNREAD) + line("05:03", "TacetTask", "info_set current_stamina 20")
                    + line("05:03", "TacetTask", "used all stamina"))
    check("a -1 logged by another task does not taint the tacet shortage", ok, True)

    print("\n[nest: an unreachable nest plus another task's traceback is not a fight]")
    weekly_err = (FX / "m6-okww" / "0921-weekly.log").read_text(encoding="utf-8")
    check("the 0921 log carries click_team_challenge only in traceback frames",
          ("self.click_team_challenge()" in weekly_err, "NightmareNestTask:" in weekly_err), (True, False))
    unreachable = (line("00:01", "NightmareNestTask", "opened gray_book_boss")
                   + line("00:05", "NightmareNestTask", "nightmare nest unreachable, skip this run: go_nest:48:18")
                   + weekly_err)
    check("_NEST_ENGAGED does not match", bool(outcome._NEST_ENGAGED.search(unreachable)), False)
    got = {c.label: c for c in outcome.okww_checks(unreachable, expect_nest=True, expect_daily=False, expect_stamina=False)}
    check("verdict: 残象聚落 not done", got["残象聚落"].ok, False)
    check("verdict: says travel failed", "传送不过去" in got["残象聚落"].detail)
    step = collector_okww._nest_step(unreachable)
    check("daily step is not the bare name (booked as farmed)", step in ("残象聚落", "梦魇巢穴"), False)
    check("daily step says travel failed", "传送不过去" in step)
    for frame in ("    self.wait_in_team_and_world(time_out=120)\n",
                  "    return self.reset_to_false(reason='echo captured')\n"):
        t = line("00:05", "NightmareNestTask", "nightmare nest unreachable, skip this run") + frame
        check(f"a traceback frame {frame.strip()[:30]!r} is no fight", nest_state(t), "unreachable")

    print("\n[nest: the step and the verdict read one classifier, in every state]")
    SAMPLES = {
        "filter_missing": line("00:01", "NightmareNestTask", outcome._NEST_FILTER_MISSING),
        "not_found": line("00:01", "NightmareNestTask", "nightmare nest: 列表里没找到指定的点位 ['落渊南丘']"),
        "count_unread": line("00:01", "NightmareNestTask", "nightmare nest: " + outcome._NEST_COUNT_UNREAD),
        "full": line("00:01", "NightmareNestTask", "nightmare nest: 指定点位都已打满，跳过"),
        "fought": line("00:01", "NightmareNestTask", "enter combat None"),
        "partly": line("00:01", "NightmareNestTask", "enter combat None")
                  + line("00:02", "NightmareNestTask",
                         "nightmare nest: 传送两次都不过去，这一轮不打了 go_nest:48:18（梦枢天罗残象聚落）"),
        "unreachable": line("00:01", "NightmareNestTask", "nightmare nest unreachable, skip this run"),
        "failed": line("00:01", "NightmareNestTask", "opened gray_book_boss")
                  + "2026-10-13 10:00:02,000 ERROR TaskExecutor DailyTask:NightmareNestTask Failed\n",
        "quit": line("00:01", "NightmareNestTask", "opened gray_book_boss"),
    }
    for key, text in SAMPLES.items():
        check(f"{key}: nest_state", nest_state(text), key)
        verdict = [c for c in outcome.okww_checks(text, expect_nest=True, expect_daily=False, expect_stamina=False)
                   if c.label.startswith("残象聚落") and not c.label.startswith(("残象聚落只刷", "残象聚落没进"))]
        step = collector_okww._nest_step(text)
        bare = step in ("残象聚落", "梦魇巢穴")
        check(f"{key}: step booked as farmed ⇔ verdict 「残象聚落」 ok", bare,
              bool(verdict) and verdict[0].ok and verdict[0].label == "残象聚落")
        check(f"{key}: step and verdict agree on done / not done", ("已刷满" in step or bare), verdict[0].ok)
    check("fought, then the task failed: still booked as fought by both",
          (nest_state(SAMPLES["fought"] + SAMPLES["failed"]),
           collector_okww._nest_step(SAMPLES["fought"] + SAMPLES["failed"])), ("fought", "梦魇巢穴"))

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_upstream_no_farm():
    """When upstream's own gate skips the stamina farm, the verdict says so.

Upstream v3.7.4 DailyTask.run farms stamina only while open_daily reads the
180-waveplate daily task under 180 and the activity points under 100
(DailyTask.py:86-93); at 180 the farm block (:117-128) is skipped without a line.
The overlay's claim_daily then farms it anyway (the standing order 「刷到空」) and
says 「上游这趟不刷体力（…）」 first. A run with no stamina fight and no
「not enough stamina」 said only 「既没进本，也没说体力不足」 (audit 3 item 11 /
audit 2026-10-13 item 22). Lines below are in upstream's and the overlay's format.

    Formerly test_okww_upstream_no_farm.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import outcome


    T = "2026-10-14 09:{:02d}:00,000 {} TaskExecutor {}"
    OPEN = [T.format(27, "INFO", "DailyTask:open_daily"),
            T.format(27, "INFO", "DailyTask:info_set current daily progress 180"),
            T.format(27, "INFO", "DailyTask:info_set total daily points 60")]
    LEFTOVER = T.format(28, "INFO", "DailyTask:上游这趟不刷体力（已用 180/180，活跃度满 False），按「刷到空」把剩下的体力刷掉")
    DONE = T.format(40, "INFO", "DailyTask:Daily Task Completed")


    def stamina(*lines):
        got = [c for c in outcome.okww_checks("\n".join([*OPEN, *lines, DONE]) + "\n", expect_nest=False)
               if c.label == "刷体力"]
        return [(c.ok, c.detail) for c in got]


    print("[180/180, the overlay's leftover farm fought: green]")
    check("green", stamina(LEFTOVER, T.format(29, "INFO", "TacetTask:enter combat None")), [(True, "")])

    print("\n[180/180, the leftover farm raised: red, saying so]")
    got = stamina(LEFTOVER, T.format(29, "ERROR", "DailyTask:补刷体力出错，照常领日常奖励: Teleport failed"))
    check("red", [ok for ok, _ in got], [False])
    check("names upstream's skip and the error",
          bool(got) and "上游这趟不刷体力" in got[0][1] and "补刷时出错：Teleport failed" in got[0][1], True)

    print("\n[180/180, no leftover line at all: red, upstream's gate named]")
    got = stamina()
    check("red", [ok for ok, _ in got], [False])
    check("says upstream read 180/180 and the leftover farm did not run",
          bool(got) and "180/180" in got[0][1] and "补刷没有跑到" in got[0][1], True)

    print("\n[under 180, nothing: the old wording]")
    text = "\n".join([T.format(27, "INFO", "DailyTask:info_set current daily progress 0"), DONE]) + "\n"
    check("unchanged", [c.detail for c in outcome.okww_checks(text, expect_nest=False) if c.label == "刷体力"],
          ["既没进本，也没说体力不足"])

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_okww_battle_pass, _part_okww_battle_pass_claim, _part_okww_claim_readback, _part_okww_daily_chests, _part_okww_farm_hook, _part_okww_merge_step, _part_okww_plan_bits, _part_okww_revive_and_retry, _part_okww_stamina_end, _part_okww_stamina_nest_verdict, _part_okww_upstream_no_farm]))
