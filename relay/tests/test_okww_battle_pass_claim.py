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
"""
import ast
import re
import sys
import tempfile
import textwrap
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from ark_relay import okww_overlay, outcome, texts  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


UPSTREAM = (HERE / "fixtures" / "okww-DailyTask-v3.7.4.py.txt").read_text(encoding="utf-8")


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
check("sha of claim_battle_pass in v3.7.4 == _BATTLE_PASS_SHA", got, ns["_BATTLE_PASS_SHA"])
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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
