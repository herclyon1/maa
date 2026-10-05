"""Nothing in the relay switches off a user's task, or keeps a failure out of the
group push, unless the user said so - and where he did, his words are on record.

The user, 2026-10-06 (02:46-03:12 Tokyo), after finding that a session had quietly
switched a task off and that failures were being kept out of the group:
「有办法杜绝吗」. This test is the answer. It reads the relay's source (ast plus a
few regexes; nothing is imported or run) and lists every place that

  OFF   turns a game task, queue, route or switch off, keeps one off, or takes a
        task out of a task list / queue, or
  MUTE  decides that a failure or error does not reach the group push.

Every hit is keyed `file:function`: the file relative to relay/, methods as
`Class.method`, module- or class-level code as the NAME it assigns, and a string
inside a module/class-level collection as `NAME[string]` (each soft task, each
demoted title is its own decision). A hit passes only when its key has a line in
relay/USER-SWITCHES.txt:

    file:function | what it does | the user's own words, verbatim, in 「」 | YYYY-MM-DD HH:MM

A line whose key has no hit any more fails as well: a stale line would
pre-approve whatever is written into that function next. Adding a line means
quoting him; there is no other way to make this test green.

The detectors (each hit names its rule):

  OFF-literal   a switch key - *enabled* (enabled, enabledByController,
                TimeEnabled, ...), enable, checked, If<Name> (IfSanity, ...), or
                a key the same function reads as on/off (`bool(x.get(k))`,
                `x.get(k, False)`) - written as False / 0 / "false" / "Close" /
                "Off" / 关闭 / 禁用 / 停用: by `x[k] = v` (k anywhere in the
                subscript chain, or x a local taken from a switch key), `x.k = v`,
                a dict literal that is not directly `return`ed (a returned dict
                describes what was read), a keyword argument, `setdefault(k, v)`,
                a {"type": "switch", "value": ...} option; and a call to a setter
                (below) passing such a value.
  OFF-decision  the same writes with a value the relay works out itself: a
                comparison / and / or / not / conditional that uses anything but
                the function's own parameters and constants
                (makeup.narrow_master: `_set_flag(t, n in want and ...)`).
  OFF-close     "Close" / "Off" / 关闭 / 禁用 / 停用 (literal or via a module
                constant) written: assigned (in a function, or into a subscript /
                attribute anywhere), returned, or passed - directly or inside a
                dict / list / conditional - to a write: a call named like one
                (WRITE_CALL: _write*, _mas, post, put, save, dump, ...), setdefault,
                a setter (rule 1), or a relay function that itself writes
                (annihilation: `_write_setting(dir, CLOSED)`, an API payload
                `_mas(path, {"Info": {"Annihilation": "Close"}})`). Passing it to
                any other call - a text function (texts.samples), a log line - is
                not a write; comparisons and `.get()` are reads.
  OFF-remove    in a function that writes (atomic_write_text, write_text, dump,
                _write*, _save*, _mas, put/post): `.remove()` / `.discard()` /
                `.pop()` / `del` on a list named or keyed "task" / "caseNames" (a
                move - removed and put back in the same function - is not a
                removal); such a list assigned from a filtering comprehension or
                rebuilt by conditional appends; and anywhere, a call to an API
                path ending in delete / remove / disable.
  OFF-keep      code that keeps a task off: it reads a state record whose key
                says "disabled", or logs that something stays off (继续关着,
                保持关闭, 不开回, "keep it off", ...). Not a read whose function
                only switches tasks back ON (rule R6 below).
  OFF-skip      `raise TaskDisabledException` - OK-WW's own "skipped, not failed"
                stop - under its own name or an import alias (`from ok import
                TaskDisabledException as _TDE`), and the raise of any class that
                subclasses it (`class S(TaskDisabledException)`, or built with
                `S = type("S", (_TDE,), {})`), in OK-WW task code the relay ships
                (okww_files/), or in a patch's `new=` text (okww_patches/; the
                old versions kept only to be found and removed are not code that
                runs), and a `new=` text that logs 已禁用.
  OFF-flag      a step skipped because a marker file exists: an `if` that ends in
                return / continue / break / raise and whose condition calls - not
                negated - os.path.exists / isfile / lexists or Path.exists /
                is_file on a constant path (a literal, a module constant, Path()
                or os.path.join of those), unless the same condition reads that
                file's contents (`F.is_file() and F.read_text() == x`: the file
                already says it). ark_overrides' _farm_hook: no stamina farm while
                no-stamina-farm.flag exists.
  MUTE-name     a name that says "this failure is not one": SOFT*, soft_only,
                SKIP_TASKS, *NO_ALARM*, *NOT_ALARM*, *LOG_ONLY*, *REPORT_ONLY*,
                *DAILY_ONLY*, *SUPPRESS*, *MUTE*, *DEMOTE* - where it is defined
                and wherever it is used.
  MUTE-filter   a failed-task list tested against a fixed collection
                (`set(failed) <= {...}`, `for f in failed: if f in SKIP: continue`).
  MUTE-log      a log line saying the failure stays out of the push, in the
                phrases of MUTE_LOG below: 只进日报, 记日报, 只记日志, 不报警,
                不拉警报 and 不推送 (but not 暂不推送, which is waiting for the
                retries), 不进群, 不报群, 不算失败, "no alarm", "not pushed",
                不算故障 and 不报漏跑 - the full list is MUTE_LOG below.
  MUTE-route    a failure-shaped title (⚠️ ❌ 🚩 失败 没能 没成 进不了 超时 故障 ...)
                in a collection notify.route_of uses to keep titles from the group.
  MUTE-info     a notifier `.send()` of a failure-shaped title (a literal, or a
                texts.* constant / function whose text is one) without
                alert=True: the caller decided it is not a group alarm.
  MUTE-cap      a rate cap on pushes - MAX_PER_*, *PER_HOUR*, *PER_DAY*, HOURLY*,
                RATE_LIMIT*, MAX_PUSH* / MAX_ALERT* - where defined and used.
  MUTE-once     in a function on an alarm's path - it sends one
                (`.send(..., alert=True)`, `.send_group()` of a failure-shaped
                title, a function wrapping either, a thread started on a function
                that alarms, or a failure-shaped `.send()` without alert=True), or
                calls a function that does - an early return / continue / break
                before that send (continue / break only inside a loop that sends)
                whose condition, read back through local variables up to two
                assignments deep, is a dedupe test: already*, *alerted*,
                announced, sent, seen, once, dedup, notified, rung, _pushed,
                _room, or `k in S` where the module adds to S elsewhere.
                An `if` whose own way out raises the group alarm is not a guard;
                one whose way out sends only information is (a demotion), and
                `if notifier.send(...): return` (send failed, retry) is not.
  MUTE-guard    the same early exit when its condition is keyed on the kind of
                failure: soft, maint*, sanity, manual, by hand, hand_started,
                trigger, failed_tasks, cause, debug, skip, unreachable,
                episode_kind, known_fixed, recur, is_test / test_window,
                is_fault, going_down / shutting_down / shutdown_issued, levelno,
                or membership in a named module constant (`v.code not in
                _STUCK_CODES`, which shutdown.py had until 2026-10-06).

The user's own commands. A write that applies a value the user chose on the phone
page or in the inbox (the command whitelist, commands.py / inbox.py) is his
decision, not the relay's. Two rules, and no others - no exemption by file,
directory or function name:

  1. A value that is a parameter of the function doing the write - or computed
     only from its parameters and constants, through comparisons, `bool()`,
     subscripts, `.get()` and string methods such as `.lower()` (not attribute
     access, not other calls) - is not judged there. That function becomes a
     setter, and every call to it is judged by the argument it passes: a
     literal False or a computed decision at the call is a hit; a value carried
     from elsewhere, e.g. the command's own `cmd.get("enabled")`, is not.
  2. His skip-today command (跳过今天), stored and applied later, is his command
     where it is applied only when the hit's nearest controlling `if` / `for` (or,
     for an early exit, its own condition) is the reader of that command's
     record, called directly or through a local that holds only its result. The
     reader is COMMAND_RECORDS below - one of them - and the test checks it
     against commands.py: the action must be in the whitelist (REVERSIBLE |
     MUTATING) and dispatched by apply_command, and the reader must exist.

Until 2026-10-06 rule 2 also let through his debug-mode command (missed.py and
engine.py not reporting a missed run while it is on; shutdown.py's 「debug」
verdict, rule 2a) and the red button (停一切): a run record's manual_stop kept
out of the group (handle._handle, rule 2b). The user's order that day, relayed by
the operator: a rule may let through only code that neither switches a task off
on the relay's own decision nor keeps an error out of the group. Debug mode
keeping the missed-run alarm away and a red-button run kept from the group are
both errors kept out, so 2a, 2b and debug_mode are gone and those places are hits.

Narrow rules for hits that are not a decision against him. Each judges the hit's
own code, never exempts a file or a function by its name (R4 is narrower still:
service.py only; R7 one line of notify.py, checked against route_of):

  R3 one fault, one push. The user, 2026-10-06: 「不论多少次什么错误都要发」 - every
     fault, however many times. A dedupe that holds back the same fault seen
     again (a timeout line read twice, a check repeated every tick) is not
     against that; one that holds back a second, different fault is. A MUTE-once
     hit passes only when (a) its line or the line above it carries
     `# one fault, one push: <why>`, and (b) its dedupe key - the left side of
     `k in S`, or the arguments of the dedupe call (`_already_alerted(day, k)`) -
     names a per-occurrence identity (IDENTITY: a run_id / rid / record id, a
     pid, the due time or slot of the run, the moment `at` a line was logged, the
     exact line or text), looked up through the function's own simple
     assignments (`key = f"...{rec.run_id}"`). A key built only from the day,
     script, game, user, shift or constant strings fails even with the marker; a
     name that is bound to nothing but constants does not count, whatever it is
     called.
  R4 the relay's own power-off (service.py only). The user's order of 2026-10-06,
     relayed by the operator: only the planned power-off that the relay itself
     started may skip the group. So in service.py an INFO/DEBUG MUTE-log line
     inside the body of an `if`, or an early exit (MUTE-guard / MUTE-once) whose
     own `if`, has a condition that calls - plainly, not negated, alone or and-ed
     - RELAY_POWER_OFF, errwatch.relay_shutdown_issued(), with no argument: true
     only when the relay itself issued the power-off - or R4_WRAPPER,
     service._going_down_soon, which is checked too: it may call nothing but
     relay_shutdown_issued() (no arguments) and time.monotonic / time.sleep /
     min, so it only waits a bounded while for that same signal. Until that
     order errwatch.going_down() (Windows going down for any reason - by hand,
     `sc stop`, an update) qualified, and the wrapper asked it; neither does now.
  R5 a temporary program setting for the relay's own launch: `old = setter(x,
     False)` (rule 1's setter) passes when a `finally:` of the same function,
     coming after it, gives the old value back to the same setter with the same
     other arguments - `setter(x, old)`, or `setter(x, True)` inside `if old:`.
     Without that restore it is an OFF-literal hit like any other.
  R6 re-enable only: a function that reads a record of tasks kept off only to
     switch them back ON - it calls at least one writer whose every switch write
     is ON (gameupdate.maaend_enable), and neither it nor anything it calls
     writes a switch OFF, a computed decision or a parameter (a setter) - is not
     an OFF-keep hit (gameupdate.maaend_reenable_records).
  R7 the log route of notify.py. The MUTE-log line 「不推送」 in Notifier.send
     (LOG_ROUTE_SITE) passes only when it sits in the body of `if route ==
     "log"`, `route` is bound once, to route_of(...) (LOG_ROUTER), and route_of
     can hand out "log" only from the routed collections: every `return` in it
     is a string constant, and each `return "log"` sits in the body of an `if`
     that tests the title against a module collection route_of uses - `title.
     startswith(C)`, `any(s in title for s in C)`, `title in C`, or an `or` of
     those. Every string in such a collection is then judged one by one
     (MUTE-route: a failure-shaped one is a hit), and no failure-shaped string
     in the relay (outside docstrings and log lines) may start with / contain /
     equal one of them, so a failure title cannot ride on a harmless prefix
     (「✅ 」). A second way to "log" - another condition, a variable, a title
     under a log-only prefix - and the line is a hit again.
  R8 the game's own counter at zero (OFF-skip). A `raise TaskDisabledException`
     passes when it sits in the body (the true branch) of an `if` whose whole
     condition is `x == 0`, x a local whose every binding comes - through local
     assignments, loops and comprehensions, nothing handed in (no parameter, no
     `self` state), no `+=` - from a read of the game screen in the same function
     (`self.ocr(...)` / `task.ocr(...)`, or a parse of its result: `_weekly_left
     (text)`), and the branch logs before the raise, and the function logs the
     reading itself (a log line naming a local on that chain). The weekly boss:
     the level page reads 「本周剩余可收取次数：0/3」 - the game says this week's
     claims are all taken (09-07: entering at 0/3 gave five minutes of 「收取物资
     次数已达到上限」), which is also how the last claim of the week ends. The task
     ran; the game says nothing is left. A value from the config, a counter, a
     raise with no condition, an OCR value compared to anything but 0 - hits.
  R8b a subclass of TaskDisabledException that ends as FAILED. Raising a subclass
     is OK-WW's skipped stop like the class itself (its `except
     TaskDisabledException` takes it), so it is an OFF-skip hit, and it passes
     only when the same file turns it into a failure: (a) an `except <Sub>`
     handler raises an exception that is neither TaskDisabledException nor a
     subclass of it; or (b) the function raising <Sub> records the reason on an
     attribute first (`task._ark_failed = why`), and a function with an `except
     <Sub>` handler that does not end in a raise raises such a failure, after
     that `try`, in the body of an `if` that reads the same attribute
     (through locals): ark_overrides' FarmEchoTask.run turns _ArkStop into
     ArkStopped once upstream's run() is over (upstream returns on a
     TaskDisabledException, so the handler alone does not see every one).

Known limits, said here rather than hidden: a value returned by an arbitrary
call (`enabled = should_run(x)`) or read off an object (`rec.ok`) is treated as
carried, not as a decision - rule 1 judges what reaches the write, and such a
value can be the relay's own decision made elsewhere (on 2026-10-06 every
carried value that reaches a switch is a phone / inbox command's own value or a
saved value put back); choosing `log.warning` over `log.error` to stay out of
errwatch's group alarm is not detected; R3 judges identity by name, so a
variable named like one (`rid = day`) passes (b) - the marker is there for the
human reading it; a dedupe key handed in as a parameter is not followed to the
callers, so it fails R3 (b); R5 does not follow early returns between the
setter and its `try:`; R6 looks one call deep; OFF-flag does not follow a flag
test wrapped in a function (ark_overrides' farming_echoes(), the NO_CLAIM file)
nor a path built from a parameter or the config (`Path(state_dir) / "x.flag"`),
nor a skip written as the `else:` of the test; R8 trusts the method name `ocr`
and R8b the attribute's name; a subclass raised through a variable
(`e = Sub(); raise e`) is not seen; an early exit on a verdict code compared
with a string literal (`v.code == "issued"`) names no failure kind and is not
flagged (the named-list form is); a "Close" serialised first
(`json.dumps({...})`) and posted by some other call is not followed; code that
never names its intent (no switch key, no task list, no wording, no alarm
nearby) is invisible.

Run it with `--list` to print every hit, listed or not. Hits that pass by rule 2 or
R3-R8b are printed with the rule (`·`), so what passes is always on screen.

Self-checks at the bottom feed the detectors small known-bad samples (each must
be flagged under the expected rule), known-good ones (none may be), and samples
that must pass by one of R3-R8b and nothing else, plus rule 2's, so a detector
or rule that silently stops matching, or starts letting more through, fails this
test. The places 2a, 2b, debug_mode and the old R4 let through are known-bad
samples now.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from textwrap import dedent

RELAY = Path(__file__).resolve().parents[1]
LIST_FILE = RELAY / "USER-SWITCHES.txt"

# The user's stored command, and the function that reads it back (rule 2). Until
# 2026-10-06 also debug_mode (modes.debug_active) and, as rules 2a / 2b, the debug
# verdict and the red button's manual_stop: those kept errors out of the group.
COMMAND_RECORDS = {
    "skip_today": "ark_relay/modes.py:_day_queues",
}

# R3: the marker, and the names that make a dedupe key one occurrence.
ONE_PUSH = re.compile(r"#\s*one fault, one push:\s*(\S.*)$")
IDENTITY = re.compile(r"(?:^|_)(?:run_?id|rid|record_?id|rec_?id|pid|due|slot|hhmm|at|line|text)(?:_|$)", re.I)

# R4: the relay's own power-off, the one signal that may keep a line from the group,
# and service.py's one wrapper of it (checked: it may only wait for that signal).
R4_FILE = "service.py"
RELAY_POWER_OFF = "ark_relay/errwatch.py:relay_shutdown_issued"
R4_WRAPPER = "service.py:_going_down_soon"
WRAPPER_PLAIN_CALLS = {"monotonic", "sleep", "min"}

# R7: the one log line of the log route, and the function that picks the route.
LOG_ROUTE_SITE = "ark_relay/notify.py:Notifier.send"
LOG_ROUTER = "ark_relay/notify.py:route_of"
LOG_ROUTE = "log"

# R8: OK-WW's read of the game screen, and its task log methods.
SCREEN_READ = "ocr"
TASK_LOGS = {"log_info", "log_debug", "log_warning", "log_error"}

# OFF-flag: an existence test, and the calls that build a constant path.
EXISTS_FUNCS = {"exists", "isfile", "lexists"}           # os.path.<f>(p)
EXISTS_METHODS = {"exists", "is_file"}                   # Path(p).<m>()
PATH_BUILDERS = {"Path", "PurePath", "PureWindowsPath", "WindowsPath", "join"}

# ----------------------------------------------------------------- vocabulary

SWITCH_KEY = re.compile(r"^(?:\w*[Ee]nabled\w*|[Ee]nable|[Cc]hecked|[Ii]s[Cc]hecked|If[A-Z]\w*)$")
OFF_STRINGS = {"false", "False", "FALSE", "0", "Close", "Off", "关闭", "禁用", "停用"}
CLOSE_STRINGS = {"Close", "Off", "关闭", "禁用", "停用"}
TASKY = re.compile(r"task|casenames", re.I)
WRITE_CALL = re.compile(r"^(?:atomic_write\w*|write_text|write_bytes|dump|_?write\w*|_mas|_?save\w*|_?put\w*|_?post\w*)$")
API_REMOVE = re.compile(r"^/api/.*/(?:delete|remove|disable)\b")
KEEP_LOG = re.compile(r"继续关着|继续关闭|保持关闭|先关着|一直关着|不开回|keeps? (?:it |them |the task )?off", re.I)
MUTE_NAME = re.compile(r"soft_?fail|soft_only|(?:^|_)SOFT(?:_|$)|SKIP_TASKS|NO_?ALARM|NOT_?ALARM|LOG_?ONLY|"
                       r"REPORT_?ONLY|DAILY_?ONLY|SUPPRESS|(?:^|_)MUTE|DEMOTE", re.I)
CAP_NAME = re.compile(r"^_?(?:MAX_PER\w*|\w*PER_HOUR\w*|\w*PER_DAY\w*|HOURLY\w*|RATE_LIMIT\w*|MAX_(?:PUSH|ALERT|ALARM|SEND)\w*)$")
MUTE_LOG = re.compile(r"只进日报|记日报|只记日报|只记日志|不报警|不拉警报|(?<!暂)不推送|不进群|不报群|不发群|"
                      r"不算失败|不算故障|不报漏跑|daily report only|not an alarm|no alarm|not pushed|never pushed", re.I)
FAIL_TITLE = re.compile(r"⚠️|❌|🚩|失败|没能|没走通|没成|进不了|报错|超时|故障|没跑|没干完|卡住|卡死")
DEDUPE = re.compile(r"already|alerted|announced|(?:^|_)sent(?:_|$)|(?:^|_)seen$|(?:^|_)once|dedup|notified|"
                    r"(?:^|_)rung|_pushed|_room", re.I)
FAILKIND = re.compile(r"soft|maint|sanity|manual|by_?hand|hand_started|trigger|failed_tasks|cause|debug|skip|"
                      r"unreachable|episode_kind|known_fixed|recur|is_test|test_window|is_fault|going_down|"
                      r"shutting_down|shutdown_issued|levelno", re.I)
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}
SKIP_SIGNAL = "TaskDisabledException"
PATCH_OFF = re.compile(r"raise TaskDisabledException|已禁用")
DERIVING_CALLS = {"bool", "str", "int", "list", "set", "frozenset", "tuple", "sorted", "len"}
# methods that only reshape the value they are called on (rule 1 follows them)
VALUE_METHODS = {"get", "lower", "upper", "strip", "lstrip", "rstrip", "casefold", "startswith", "endswith",
                 "split", "replace", "items", "keys", "values"}

OFF, DECISION, CARRIED, ON = "off", "decision", "carried", "on"


class _Missing:
    pass


MISSING = _Missing()


def _is_off(v) -> bool:
    if isinstance(v, bool):
        return v is False
    if isinstance(v, (int, float)):
        return v == 0
    return isinstance(v, str) and v in OFF_STRINGS


def _call_name(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


# ----------------------------------------------------------------- per function

class Fn:
    """One function: its parameters and every local binding, for the value judge."""

    def __init__(self, node, qual: str, cls: "str | None"):
        self.node, self.qual, self.cls = node, qual, cls
        self.name = node.name
        a = node.args
        self.params = [x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs)]
        self.params += [x.arg for x in (a.vararg, a.kwarg) if x is not None]
        self.free = {p for p in self.params if p not in ("self", "cls")}
        self.nodes: list = []          # every node in the body, not those of nested functions (Module._walk)
        self.assigned: dict[str, list] = {}       # name -> [("=", value) | ("for", iter) | ("other", None)]
        self.writes = False

    def finish(self):
        self.calls = [n for n in self.nodes if isinstance(n, ast.Call)]
        self.writes = any(WRITE_CALL.match(_call_name(n)) for n in self.calls)
        for n in self.nodes:
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    self._bind(t, n.value)
            elif isinstance(n, ast.AnnAssign) and n.value is not None:
                self._bind(n.target, n.value)
            elif isinstance(n, ast.AugAssign):
                self._bind(n.target, None)
            elif isinstance(n, ast.NamedExpr):
                self._bind(n.target, n.value)
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                self._bind(n.target, None, it=n.iter)
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                for it in n.items:
                    if it.optional_vars is not None:
                        self._bind(it.optional_vars, None)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                self.assigned.setdefault(n.name, []).append(("other", None))
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for al in n.names:
                    self.assigned.setdefault((al.asname or al.name).split(".")[0], []).append(("other", None))

    def _bind(self, target, value, it=None):
        if isinstance(target, ast.Name):
            entry = ("for", it) if it is not None else ("=", value) if value is not None else ("other", None)
            self.assigned.setdefault(target.id, []).append(entry)
        elif isinstance(target, (ast.Tuple, ast.List)):
            vals = value.elts if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts) else None
            for i, t in enumerate(target.elts):
                self._bind(t, vals[i] if vals is not None else None, it=None if vals is not None else it)
        elif isinstance(target, ast.Starred):
            self._bind(target.value, None)

    def method_params(self) -> list[str]:
        return self.params[1:] if self.cls and self.params[:1] in (["self"], ["cls"]) else self.params


# ----------------------------------------------------------------- per module

class Hit:
    def __init__(self, rel, line, key, rule, text, node=None, fn=None):
        self.rel, self.line, self.key, self.rule, self.text = rel, line, key, rule, text
        self.node, self.fn = node, fn

    def __repr__(self):
        return f"{self.rel}:{self.line}  {self.key}  [{self.rule}]  {self.text}"


class Module:
    def __init__(self, rel: str, src: str):
        self.rel, self.stem = rel, Path(rel).stem
        self.tree = ast.parse(src)
        self.lines = src.splitlines()
        self.parent: dict = {}
        self.scope: dict = {}                  # node -> enclosing Fn (None at module/class level)
        self.fns: dict[str, Fn] = {}           # qualname -> Fn
        self.consts: dict[str, ast.AST] = {}   # NAME / Class.NAME -> value node (module/class level)
        self.imports: dict[str, str] = {}      # alias -> relay module stem
        self.from_imports: dict[str, tuple[str, str]] = {}
        self.top_nodes: list = []              # nodes outside any function
        self.new_names: set[str] = set()       # names passed as a patch's `new=` text
        self.docstrings: set[int] = set()
        self._walk(self.tree, None, None, "")
        for f in self.fns.values():
            f.finish()
        self.fn_of_node = {f.node: f for f in self.fns.values()}

    def _walk(self, node, fn, cls, prefix):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            self.docstrings.add(id(body[0].value))
        for child in ast.iter_child_nodes(node):
            self.parent[child] = node
            self.scope[child] = fn
            (fn.nodes if fn is not None else self.top_nodes).append(child)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                f = Fn(child, f"{prefix}{child.name}", cls if fn is None else None)
                self.fns[f.qual] = f
                self._walk(child, f, None, f.qual + ".")
                continue
            if isinstance(child, ast.ClassDef):
                self._walk(child, fn, child.name if fn is None else None, f"{prefix}{child.name}.")
                continue
            if fn is None and isinstance(child, (ast.Assign, ast.AnnAssign)) and child.value is not None:
                for t in (child.targets if isinstance(child, ast.Assign) else [child.target]):
                    if isinstance(t, ast.Name):
                        self.consts[f"{prefix}{t.id}"] = child.value
            elif isinstance(child, ast.ImportFrom):
                self._import(child)
            elif isinstance(child, ast.keyword) and child.arg == "new" and isinstance(child.value, ast.Name):
                self.new_names.add(child.value.id)
            self._walk(child, fn, cls, prefix)

    def _import(self, n: ast.ImportFrom):
        relative = (n.level or 0) >= 1
        pkg = n.module or ""
        if not relative and not pkg.startswith("ark_relay"):
            return
        for a in n.names:
            if relative and not pkg or pkg == "ark_relay":
                self.imports[a.asname or a.name] = a.name
            else:
                self.from_imports[a.asname or a.name] = (pkg.split(".")[-1], a.name)

    def where(self, node) -> str:
        """The key part after 'file:' for a node outside any function."""
        names, stmt, n = [], None, node
        while n in self.parent:
            p = self.parent[n]
            if stmt is None and isinstance(n, ast.stmt):
                stmt = n
            if isinstance(p, ast.ClassDef):
                names.insert(0, p.name)
            n = p
        target = None
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            t = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
            target = t.id if isinstance(t, ast.Name) else None
        return ".".join([*names, target or f"<line {getattr(stmt or node, 'lineno', 0)}>"])

    def const_node(self, name: str, fn: "Fn | None"):
        if fn is not None and (name in fn.assigned or name in fn.params):
            return None
        if fn is not None and fn.cls and f"{fn.cls}.{name}" in self.consts:
            return self.consts[f"{fn.cls}.{name}"]
        return self.consts.get(name)

    def const_value(self, e, fn: "Fn | None"):
        """The literal behind a Constant or a module/class constant, else MISSING."""
        if isinstance(e, ast.Constant):
            return e.value
        v = None
        if isinstance(e, ast.Name):
            v = self.const_node(e.id, fn)
        elif isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id in ("self", "cls") \
                and fn is not None and fn.cls:
            v = self.consts.get(f"{fn.cls}.{e.attr}")
        return v.value if isinstance(v, ast.Constant) else MISSING

    def const_collection(self, e, fn):
        if isinstance(e, (ast.Tuple, ast.List, ast.Set)):
            return e
        if isinstance(e, ast.Name):
            v = self.const_node(e.id, fn)
            if isinstance(v, ast.Call) and v.args and _call_name(v) in ("frozenset", "set", "tuple", "list"):
                v = v.args[0]
            if isinstance(v, (ast.Tuple, ast.List, ast.Set)):
                return v
        return None

    def strings_of(self, e, fn) -> set[str]:
        """Strings a key can be: a literal, a constant, or a loop variable over a
        constant collection (`for k in _FLAG_KEYS: t[k] = ...`)."""
        v = self.const_value(e, fn)
        if isinstance(v, str):
            return {v}
        out: set[str] = set()
        if isinstance(e, ast.Name) and fn is not None:
            for kind, x in fn.assigned.get(e.id, []):
                coll = self.const_collection(x, fn) if kind == "for" else None
                if coll is not None:
                    out |= {c.value for c in coll.elts if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        return out

    # parameters and decisions ---------------------------------------------
    def derived(self, e, fn: "Fn | None", seen: frozenset = frozenset()):
        """The parameters `e` is computed from (rule 1), or None when it uses
        anything else: an attribute, a call other than bool()/.get()/..., a
        local bound from such a thing."""
        if fn is None:
            return None
        if isinstance(e, ast.Constant):
            return set()
        if isinstance(e, ast.Name):
            if e.id in fn.free:
                return {e.id}
            if e.id in ("True", "False", "None") or self.const_node(e.id, fn) is not None:
                return set()
            if e.id in seen or e.id not in fn.assigned:
                return set() if e.id in seen else None
            out: set[str] = set()
            for kind, x in fn.assigned[e.id]:
                if kind == "other":
                    return None
                if kind == "for" and self.const_collection(x, fn) is not None:
                    continue
                sub = self.derived(x, fn, seen | {e.id})
                if sub is None:
                    return None
                out |= sub
            return out
        if isinstance(e, ast.Call):
            f = e.func
            if isinstance(f, ast.Name) and f.id in DERIVING_CALLS:
                parts = [*e.args, *(k.value for k in e.keywords)]
            elif isinstance(f, ast.Attribute) and f.attr in VALUE_METHODS:
                parts = [f.value, *e.args]
            else:
                return None
        elif isinstance(e, (ast.Compare, ast.BoolOp, ast.UnaryOp, ast.IfExp, ast.Subscript, ast.Tuple, ast.List,
                            ast.Set, ast.Dict, ast.JoinedStr, ast.FormattedValue, ast.BinOp, ast.Starred, ast.Slice,
                            ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp, ast.comprehension)):
            parts = [c for c in ast.iter_child_nodes(e) if isinstance(c, (ast.expr, ast.comprehension))]
        else:
            return None
        out = set()
        bound = {t.id for c in ast.walk(e) if isinstance(c, ast.comprehension)
                 for t in ast.walk(c.target) if isinstance(t, ast.Name)}
        for p in parts:
            sub = self.derived(p, fn, seen | bound)
            if sub is None:
                return None
            out |= sub
        return out

    def judge(self, e, fn: "Fn | None", seen: frozenset = frozenset()):
        """OFF / DECISION / ("param", names) / CARRIED / ON for a value written to a switch."""
        v = self.const_value(e, fn)
        if v is not MISSING:
            return OFF if _is_off(v) else ON
        if isinstance(e, ast.Name):
            if fn is not None and e.id in fn.free:
                return ("param", {e.id})
            if fn is None or e.id not in fn.assigned or e.id in seen:
                return CARRIED
            results = []
            for kind, x in fn.assigned[e.id]:
                if kind == "=":
                    results.append(self.judge(x, fn, seen | {e.id}))
                elif kind == "for":
                    coll = self.const_collection(x, fn)
                    if coll is not None:
                        results += [self.judge(c, fn, seen | {e.id}) for c in coll.elts]
                    else:
                        ps = self.derived(x, fn)
                        results.append(("param", ps) if ps else CARRIED)
                else:
                    results.append(CARRIED)
            return _combine(results)
        ps = self.derived(e, fn)
        if ps:
            return ("param", ps)
        if isinstance(e, ast.Call) and _call_name(e) in ("bool", "str", "int") and len(e.args) == 1:
            return self.judge(e.args[0], fn, seen)
        if isinstance(e, ast.IfExp):
            parts = [self.judge(e.body, fn, seen), self.judge(e.orelse, fn, seen)]
            return DECISION if any(p in (OFF, DECISION) for p in parts) else _combine(parts)
        if isinstance(e, ast.BoolOp):
            # `x or ""` hands on one of its operands; `a in b and c` is a decision
            # because its operands are
            parts = [self.judge(v, fn, seen) for v in e.values]
            last = parts[-1]
            if isinstance(e.op, ast.Or) and last == OFF and all(p in (CARRIED, ON) for p in parts[:-1]):
                return CARRIED      # `x or False`: a default, not a decision
            return _combine(parts)
        if isinstance(e, ast.Compare) or (isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not)):
            return DECISION
        return CARRIED


def _combine(results):
    for level in (OFF, DECISION):
        if level in results:
            return level
    ps = [r for r in results if isinstance(r, tuple)]
    if ps:
        return ("param", set().union(*(p[1] for p in ps)))
    return CARRIED if CARRIED in results else ON


# ----------------------------------------------------------------- the scan

class Scan:
    def __init__(self, sources: dict[str, str]):
        self.mods = {rel: Module(rel, src) for rel, src in sources.items()}
        self.by_stem = {m.stem: m for m in self.mods.values()}
        self.hits: list[Hit] = []
        self._seen: set = set()
        self.defs_by_name: dict[str, list] = {}
        for m in self.mods.values():
            for q, f in m.fns.items():
                self.defs_by_name.setdefault(f.name, []).append((m.rel, q))
        self.setters: dict[tuple[str, str], set[str]] = {}    # (rel, qual) -> params that reach a switch
        self.alarms: dict[tuple[str, str], int] = {}          # (rel, qual) -> title param index, -1 if none
        self.resolved: dict[int, "tuple[str, str] | None"] = {}
        self.new_names = set().union(*(m.new_names for m in self.mods.values()))
        self._static: dict[int, list] = {}
        self.log_route_used = False                            # a hit relied on R7
        self.wrapper_used = False                              # a hit relied on R4's wrapper
        self._log_route_problems: "list[str] | None" = None
        for _ in range(8):     # setters calling setters, wrappers of wrappers
            size = (sum(len(v) for v in self.setters.values()), len(self.alarms))
            for m in self.mods.values():
                for q, f in m.fns.items():
                    self._learn(m, f)
            if (sum(len(v) for v in self.setters.values()), len(self.alarms)) == size:
                break
        for m in self.mods.values():
            self._scan(m)

    # resolution ----------------------------------------------------------
    def resolve(self, m: Module, call: ast.Call, fn: "Fn | None"):
        key = id(call)
        if key not in self.resolved:
            self.resolved[key] = self._resolve(m, call, fn)
        return self.resolved[key]

    def _resolve(self, m, call, fn):
        f = call.func
        if isinstance(f, ast.Name):
            if f.id in m.fns:
                return (m.rel, f.id)
            if f.id in m.from_imports:
                stem, name = m.from_imports[f.id]
                tm = self.by_stem.get(stem)
                return (tm.rel, name) if tm and name in tm.fns else None
            return None
        if not isinstance(f, ast.Attribute):
            return None
        base = f.value
        if isinstance(base, ast.Name) and base.id in m.imports:
            tm = self.by_stem.get(m.imports[base.id])
            return (tm.rel, f.attr) if tm and f.attr in tm.fns else None
        if isinstance(base, ast.Name) and base.id in ("self", "cls") and fn is not None:
            owner = fn.cls or fn.qual.split(".")[0]
            if f"{owner}.{f.attr}" in m.fns:
                return (m.rel, f"{owner}.{f.attr}")
        cands = self.defs_by_name.get(f.attr, [])
        return cands[0] if len(cands) == 1 else None

    def _arg(self, call: ast.Call, target, param: str):
        f = self.mods[target[0]].fns[target[1]]
        for kw in call.keywords:
            if kw.arg == param:
                return kw.value
        ps = f.method_params()
        if param in ps:
            i = ps.index(param)
            if i < len(call.args) and not any(isinstance(a, ast.Starred) for a in call.args[:i + 1]):
                return call.args[i]
        return None

    # what the scan looks for -----------------------------------------------
    def _switch_containers(self, m, fn) -> set[str]:
        """Locals taken from a switch key: `ctl = task.get("enabledByController")`."""
        out = set()
        for name, binds in (fn.assigned.items() if fn else []):
            for kind, x in binds:
                if kind != "=":
                    continue
                if isinstance(x, ast.Subscript) and _switch_strings(m.strings_of(x.slice, fn)):
                    out.add(name)
                elif isinstance(x, ast.Call) and _call_name(x) == "get" and x.args \
                        and _switch_strings(m.strings_of(x.args[0], fn)):
                    out.add(name)
        return out

    @staticmethod
    def _bool_keys(m, fn, nodes) -> set[str]:
        """Keys this function reads as on/off: `bool(x.get(K))`, `x.get(K, False)`."""
        out = set()
        for n in nodes:
            if not (isinstance(n, ast.Call) and _call_name(n) == "get" and n.args):
                continue
            p = m.parent.get(n)
            as_bool = isinstance(p, ast.Call) and _call_name(p) == "bool" and p.args and p.args[0] is n
            bool_default = len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, bool)
            if as_bool or bool_default:
                out |= m.strings_of(n.args[0], fn)
        return out

    def switch_writes(self, m: Module, fn: "Fn | None", nodes):
        """(node, value, what) for each value written to a switch or passed to a setter."""
        key = id(fn) if fn is not None else id(m)
        if key not in self._static:
            self._static[key] = list(self._static_writes(m, fn, nodes))
        yield from self._static[key]
        for n in (fn.calls if fn is not None else [x for x in nodes if isinstance(x, ast.Call)]):
            target = self.resolve(m, n, fn)
            for param in sorted(self.setters.get(target, ())):
                a = self._arg(n, target, param)
                if a is not None:
                    yield n, a, f"setter {target[1]}({param}=)"

    def _static_writes(self, m: Module, fn: "Fn | None", nodes):
        holders = self._switch_containers(m, fn)
        bool_keys = self._bool_keys(m, fn, nodes)
        for n in nodes:
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Attribute) and SWITCH_KEY.match(t.attr):
                        yield n, n.value, f"sets .{t.attr}"
                    elif isinstance(t, ast.Subscript):
                        chain, root = [], t
                        while isinstance(root, ast.Subscript):
                            chain.append(root.slice)
                            root = root.value
                        keys = set().union(*(m.strings_of(s, fn) for s in chain))
                        if _switch_strings(keys) or (isinstance(root, ast.Name) and root.id in holders):
                            yield n, n.value, f"sets [{'/'.join(sorted(_switch_strings(keys))) or root.id}]"
                        elif m.strings_of(t.slice, fn) & bool_keys:
                            yield n, n.value, f"sets on/off option [{'/'.join(sorted(m.strings_of(t.slice, fn)))}]"
                        elif "value" in m.strings_of(t.slice, fn) and m.judge(n.value, fn) == OFF:
                            yield n, n.value, "sets a switch option's value"
            elif isinstance(n, ast.Dict):
                p = m.parent.get(n)
                if isinstance(p, ast.Return) or (isinstance(p, ast.Call) and _call_name(p) == "get"):
                    continue
                keys = [m.strings_of(k, fn) if k is not None else set() for k in n.keys]
                is_switch_option = any("type" in k and m.const_value(v, fn) == "switch" for k, v in zip(keys, n.values))
                for k, v in zip(keys, n.values):
                    if _switch_strings(k) or (is_switch_option and "value" in k):
                        yield n, v, f"dict {{{'/'.join(sorted(k))}: ...}}"
            elif isinstance(n, ast.Call):
                for kw in n.keywords:
                    if kw.arg and SWITCH_KEY.match(kw.arg):
                        yield n, kw.value, f"{kw.arg}="
                if _call_name(n) == "setdefault" and len(n.args) == 2 and _switch_strings(m.strings_of(n.args[0], fn)):
                    yield n, n.args[1], "setdefault"

    def is_alarm_call(self, m, n, fn) -> bool:
        """A group send: `.send(..., alert=True)`, `.send_group()`, a wrapper of either, or
        a thread started on one (`Thread(target=self._push)`)."""
        if not isinstance(n, ast.Call):
            return False
        name = _call_name(n)
        if name == "send_group":      # the group also carries banner and drop notices: only failures count
            return bool(n.args) and bool(FAIL_TITLE.search(self._title_text(m, n.args[0], fn)))
        if name == "send" and any(kw.arg == "alert" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                                  for kw in n.keywords):
            return True
        target = self.resolve(m, n, fn)
        if target is not None and self.alarms.get(target, -1) >= 0:
            return True
        for kw in n.keywords:
            if kw.arg == "target":
                ref = self._resolve(m, ast.Call(func=kw.value, args=[], keywords=[]), fn)
                if ref in self.alarms:       # the thread runs a function that alarms
                    return True
        return False

    def on_alarm_path(self, m, fn) -> bool:
        """Sends an alarm itself, or calls a function that does (one level up)."""
        if (m.rel, fn.qual) in self.alarms:
            return True
        return any(self.resolve(m, n, fn) in self.alarms for n in fn.calls)

    def _learn(self, m: Module, f: Fn):
        for _, value, _ in self.switch_writes(m, f, f.nodes):
            j = m.judge(value, f)
            if isinstance(j, tuple):
                self.setters.setdefault((m.rel, f.qual), set()).update(j[1])
        for n in f.calls:
            if self.is_alarm_call(m, n, f):
                target = self.resolve(m, n, f)
                pos = self.alarms.get(target, 0) if target in self.alarms else 0
                title = n.args[pos] if len(n.args) > pos else None
                ps = f.method_params()
                idx = ps.index(title.id) if isinstance(title, ast.Name) and title.id in ps else -1
                self.alarms[(m.rel, f.qual)] = max(self.alarms.get((m.rel, f.qual), -2), idx)

    # hits ----------------------------------------------------------------
    def add(self, m: Module, node, rule: str, what: str, key: "str | None" = None, fn: "Fn | None" = None):
        if key is None:
            key = fn.qual if fn is not None else m.where(node)
        line = getattr(node, "lineno", 0)
        sig = (m.rel, line, key, rule)
        if sig in self._seen:
            return
        self._seen.add(sig)
        src = m.lines[line - 1].strip() if 0 < line <= len(m.lines) else ""
        self.hits.append(Hit(m.rel, line, f"{m.rel}:{key}", rule, f"{what} :: {src[:120]}", node, fn))

    def _scan(self, m: Module):
        routed = self._route_collections(m)
        units = [(f, f.nodes) for f in m.fns.values()] + [(None, m.top_nodes)]
        for fn, nodes in units:
            self._scan_switches(m, fn, nodes)
            self._scan_removals(m, fn, nodes)
            self._scan_names(m, fn, nodes, routed)
            self._scan_logs(m, fn, nodes)
            self._scan_info_sends(m, fn, nodes)
            self._scan_skips(m, fn, nodes)
            self._scan_flags(m, fn, nodes)
            if fn is not None and self.on_alarm_path(m, fn):
                self._scan_guards(m, fn)
        for name in sorted(routed):
            for e in m.consts[name].elts:
                if isinstance(e, ast.Constant) and isinstance(e.value, str) and FAIL_TITLE.search(e.value):
                    self.add(m, e, "MUTE-route", f"route_of keeps {e.value!r} from the group", key=f"{name}[{e.value}]")

    def _scan_switches(self, m, fn, nodes):
        for n, value, what in self.switch_writes(m, fn, nodes):
            j = m.judge(value, fn)
            if j in (OFF, DECISION):
                self.add(m, value if hasattr(value, "lineno") else n, "OFF-literal" if j == OFF else "OFF-decision",
                         what, fn=fn)
        for n in nodes:
            if not isinstance(n, (ast.Constant, ast.Name)):
                continue
            v = m.const_value(n, fn)
            if not (isinstance(v, str) and v in CLOSE_STRINGS):
                continue
            if self._close_written(m, fn, n):
                self.add(m, n, "OFF-close", f"writes {v!r}", fn=fn)

    def _close_written(self, m, fn, n, seen: frozenset = frozenset()) -> bool:
        """Whether the value `n` reaches a write (see OFF-close in the docstring). A
        local it is assigned to is followed to where that local is used."""
        x, p = n, m.parent.get(n)
        while (isinstance(p, ast.IfExp) and x is not p.test) or isinstance(p, (ast.BoolOp, ast.Tuple, ast.List,
                                                                                ast.Set, ast.Starred, ast.keyword)) \
                or (isinstance(p, ast.Dict) and x in p.values):
            x, p = p, m.parent.get(p)
        if isinstance(p, (ast.Assign, ast.AnnAssign)) and p.value is x:
            targets = p.targets if isinstance(p, ast.Assign) else [p.target]
            if any(isinstance(t, (ast.Subscript, ast.Attribute)) for t in targets):
                return True
            if fn is None:
                return False            # a module constant: judged where it is used
            names = {t.id for t in targets if isinstance(t, ast.Name)} - seen
            return any(isinstance(u, ast.Name) and u.id in names and isinstance(u.ctx, ast.Load)
                       and self._close_written(m, fn, u, seen | names) for u in fn.nodes)
        if isinstance(p, ast.Return):
            return True
        if not isinstance(p, ast.Call) or x is p.func or _is_log(p):
            return False
        if WRITE_CALL.match(_call_name(p)) or _call_name(p) == "setdefault":
            return True
        target = self.resolve(m, p, fn)
        return target is not None and (target in self.setters or self.mods[target[0]].fns[target[1]].writes)

    def _scan_removals(self, m, fn, nodes):
        def tasky(e) -> bool:
            if isinstance(e, ast.Name):
                return bool(TASKY.search(e.id))
            if isinstance(e, ast.Attribute):
                return bool(TASKY.search(e.attr))
            if isinstance(e, ast.Subscript):
                return any(TASKY.search(s) for s in m.strings_of(e.slice, fn)) or tasky(e.value)
            if isinstance(e, ast.Call) and _call_name(e) in ("get", "list"):
                inner = e.func.value if isinstance(e.func, ast.Attribute) else (e.args[0] if e.args else None)
                return any(isinstance(a, ast.Constant) and isinstance(a.value, str) and TASKY.search(a.value)
                           for a in e.args) or (inner is not None and tasky(inner))
            return False

        def filtered(e, seen=frozenset()) -> bool:
            """A filtering comprehension, or a local list rebuilt by conditional appends."""
            if any(isinstance(c, ast.comprehension) and c.ifs for c in ast.walk(e)):
                return True
            for name in {x.id for x in ast.walk(e) if isinstance(x, ast.Name)} - seen:
                binds = fn.assigned.get(name, [])
                if any(x is not None and filtered(x, seen | {name}) for _, x in binds):
                    return True
                if any(kind == "=" and isinstance(x, ast.List) and not x.elts for kind, x in binds):
                    for c in nodes:
                        if isinstance(c, ast.Call) and _call_name(c) == "append" and isinstance(c.func, ast.Attribute):
                            recv = c.func.value
                            if name in {x.id for x in ast.walk(recv) if isinstance(x, ast.Name)} \
                                    and (isinstance(recv, ast.IfExp) or _inside_if(m, c, fn)):
                                return True
            return False

        if fn is None:
            return
        put_back = {(ast.dump(n.func.value), ast.dump(n.args[-1])) for n in nodes
                    if isinstance(n, ast.Call) and _call_name(n) in ("insert", "append") and n.args
                    and isinstance(n.func, ast.Attribute)}
        for n in nodes:
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and API_REMOVE.match(n.value) \
                    and isinstance(m.parent.get(n), ast.Call):
                self.add(m, n, "OFF-remove", f"calls {n.value}", fn=fn)
            elif isinstance(n, ast.Call) and _call_name(n) == "get" and any(
                    isinstance(a, ast.Constant) and isinstance(a.value, str) and "disabled" in a.value.lower()
                    for a in n.args) and not self._reenable_only(m, fn):
                self.add(m, n, "OFF-keep", "reads a record of tasks kept off", fn=fn)
            if not fn.writes:
                continue
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr in ("remove", "discard", "pop") and tasky(n.func.value):
                if not (n.args and (ast.dump(n.func.value), ast.dump(n.args[0])) in put_back):
                    self.add(m, n, "OFF-remove", f"{n.func.attr}() on a task list", fn=fn)
            elif isinstance(n, ast.Delete) and any(isinstance(t, ast.Subscript) and tasky(t.value) for t in n.targets):
                self.add(m, n, "OFF-remove", "del on a task list", fn=fn)
            elif isinstance(n, ast.Assign) and any(tasky(t) for t in n.targets) and filtered(n.value):
                self.add(m, n, "OFF-remove", "task list rebuilt without some of its entries", fn=fn)

    def switch_profile(self, target) -> set:
        """How a function sets switches: the judgment of each of its writes (ON, OFF,
        DECISION, CARRIED, or "param" when it is a setter)."""
        m = self.mods[target[0]]
        f = m.fns[target[1]]
        return {"param" if isinstance(j, tuple) else j
                for j in (m.judge(value, f) for _, value, _ in self.switch_writes(m, f, f.nodes))}

    def _reenable_only(self, m, fn) -> bool:
        """R6: `fn` switches tasks back on and nothing else - it calls a writer whose
        every switch write is ON, and no switch write of its own or of anything it
        calls is anything but ON (a setter's own write is judged at fn's call)."""
        if self.switch_profile((m.rel, fn.qual)) - {ON}:
            return False
        enables = False
        for c in fn.calls:
            t = self.resolve(m, c, fn)
            if t is None or t == (m.rel, fn.qual) or t in self.setters:
                continue
            prof = self.switch_profile(t)
            if prof - {ON}:
                return False
            enables = enables or (bool(prof) and self.mods[t[0]].fns[t[1]].writes)
        return enables

    def _scan_names(self, m, fn, nodes, routed):
        for n in nodes:
            if isinstance(n, ast.Name):
                name = n.id
            elif isinstance(n, ast.Attribute):
                name = n.attr
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = n.name
            else:
                continue
            if name in routed:
                continue
            rule = "MUTE-name" if MUTE_NAME.search(name) else "MUTE-cap" if CAP_NAME.match(name) else None
            if rule is None:
                continue
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.add(m, n, rule, f"def {name}", key=m.fn_of_node[n].qual)
                continue
            p = m.parent.get(n)
            if fn is None and isinstance(p, (ast.Assign, ast.AnnAssign)) and isinstance(n, ast.Name) \
                    and p.value is not None and n is not p.value:
                coll = p.value
                if isinstance(coll, ast.Call) and coll.args and _call_name(coll) in ("frozenset", "set", "tuple", "list"):
                    coll = coll.args[0]
                coll = coll if isinstance(coll, (ast.Tuple, ast.List, ast.Set)) else None
                elts = [e for e in (coll.elts if coll is not None else []) if isinstance(e, ast.Constant)]
                if elts:
                    for e in elts:
                        self.add(m, e, rule, f"{name} lists {e.value!r}", key=f"{m.where(e)}[{e.value}]")
                    continue
            self.add(m, n, rule, name, fn=fn)
        for n in nodes:
            if isinstance(n, ast.Compare) and self._fixed_filter(m, fn, n):
                self.add(m, n, "MUTE-filter", "failed tasks tested against a fixed list", fn=fn)

    def _fixed_filter(self, m, fn, n: ast.Compare) -> bool:
        if not any(isinstance(o, (ast.LtE, ast.Lt, ast.In, ast.NotIn)) for o in n.ops):
            return False

        def failish(e):
            return any((isinstance(x, ast.Name) and "fail" in x.id.lower())
                       or (isinstance(x, ast.Attribute) and "fail" in x.attr.lower())
                       or (isinstance(x, ast.Constant) and isinstance(x.value, str) and "fail" in x.value.lower())
                       for x in ast.walk(e))

        def fixed(e):
            if isinstance(e, (ast.Set, ast.Tuple, ast.List)):
                return bool(e.elts) and all(isinstance(x, ast.Constant) for x in e.elts)
            if isinstance(e, ast.Name):
                return m.const_collection(e, fn) is not None
            return isinstance(e, ast.Attribute) and e.attr.isupper()

        if not any(fixed(s) for s in n.comparators):
            return False
        if failish(n.left):
            return True
        # `for f in failed: if f in SKIP: continue`
        if isinstance(n.left, ast.Name) and fn is not None:
            sources = [x for k, x in fn.assigned.get(n.left.id, []) if k == "for"]
            parent = m.parent.get(n)
            return any(failish(x) for x in sources) and isinstance(parent, ast.If) \
                and any(isinstance(s, (ast.Continue, ast.Return)) for s in parent.body)
        return False

    def _scan_logs(self, m, fn, nodes):
        for n in nodes:
            if not _is_log(n):
                continue
            text = " ".join(c.value for a in n.args for c in ast.walk(a)
                            if isinstance(c, ast.Constant) and isinstance(c.value, str))
            if hit := MUTE_LOG.search(text):
                self.add(m, n, "MUTE-log", hit.group(0), fn=fn)
            if hit := KEEP_LOG.search(text):
                self.add(m, n, "OFF-keep", hit.group(0), fn=fn)

    def _title_text(self, m, e, fn) -> str:
        """The literal text of a title: a string, a texts.* constant, or a texts.* function's returns."""
        v = m.const_value(e, fn)
        if isinstance(v, str):
            return v
        if isinstance(e, ast.JoinedStr):
            return "".join(c.value for c in e.values if isinstance(c, ast.Constant))
        target = None
        if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id in m.imports:
            tm = self.by_stem.get(m.imports[e.value.id])
            c = tm.consts.get(e.attr) if tm else None
            return c.value if isinstance(c, ast.Constant) and isinstance(c.value, str) else ""
        if isinstance(e, ast.Call):
            target = self.resolve(m, e, fn)
        if target is None:
            return ""
        tf = self.mods[target[0]].fns[target[1]]
        return " ".join(c.value for r in tf.nodes if isinstance(r, ast.Return) and r.value is not None
                        for c in ast.walk(r.value) if isinstance(c, ast.Constant) and isinstance(c.value, str))

    def _scan_skips(self, m, fn, nodes):
        """OK-WW's own "skipped, not failed" stop, in code or in code the relay patches into OK-WW."""
        base, subs = self.skip_classes(m)
        for n in nodes:
            if isinstance(n, ast.Raise) and n.exc is not None and _words(n.exc) & base:
                self.add(m, n, "OFF-skip", f"raise {SKIP_SIGNAL}: OK-WW ends the task as skipped, not failed", fn=fn)
            elif isinstance(n, ast.Raise) and n.exc is not None and (sub := _words(n.exc) & subs):
                self.add(m, n, "OFF-skip", f"raise {'/'.join(sorted(sub))}, a subclass of {SKIP_SIGNAL}: "
                                           "skipped, not failed, unless the relay turns it into a failure", fn=fn)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and (hit := PATCH_OFF.search(n.value)) \
                    and id(n) not in m.docstrings and self._injected(m, n):
                self.add(m, n, "OFF-skip", f"code patched into OK-WW: {hit.group(0)}", fn=fn)

    @staticmethod
    def skip_classes(m) -> tuple[set[str], set[str]]:
        """(names of TaskDisabledException in `m` - itself and its import aliases,
        names of its subclasses - `class S(TDE)` or `S = type("S", (TDE,), {})`)."""
        if hasattr(m, "_skip_classes"):
            return m._skip_classes
        base = {SKIP_SIGNAL} | {a.asname or a.name for x in ast.walk(m.tree) if isinstance(x, ast.ImportFrom)
                                for a in x.names if a.name == SKIP_SIGNAL}
        subs: set[str] = set()
        while True:
            known, found = base | subs, set()
            for x in ast.walk(m.tree):
                if isinstance(x, ast.ClassDef) and any(_words(b) & known for b in x.bases):
                    found.add(x.name)
                elif isinstance(x, (ast.Assign, ast.AnnAssign)) and isinstance(x.value, ast.Call) \
                        and _call_name(x.value) == "type" and len(x.value.args) >= 2 and _words(x.value.args[1]) & known:
                    targets = x.targets if isinstance(x, ast.Assign) else [x.target]
                    found |= {t.id for t in targets if isinstance(t, ast.Name)}
            if not found - known:
                break
            subs |= found - base
        m._skip_classes = (base, subs)
        return m._skip_classes

    def _scan_flags(self, m, fn, nodes):
        """OFF-flag: a step skipped while a marker file at a constant path exists."""
        if fn is None:
            return
        for n in nodes:
            if not isinstance(n, ast.If) or not n.body \
                    or not isinstance(n.body[-1], (ast.Return, ast.Continue, ast.Break, ast.Raise)):
                continue
            for c in _unnegated_calls(n.test):
                path = _exists_target(c)
                if path is None or not self._constant_path(m, fn, path):
                    continue
                if any(isinstance(r, ast.Call) and _call_name(r) in ("read_text", "read_bytes", "open")
                       and any(ast.dump(x) == ast.dump(path) for x in (getattr(r.func, "value", None), *r.args)
                               if x is not None) for r in ast.walk(n.test)):
                    continue     # `F.is_file() and F.read_text() == x`: what the file says, not that it is there
                self.add(m, n, "OFF-flag", f"skips the step while the marker file {ast.unparse(path)} exists", fn=fn)
                break

    def _constant_path(self, m, fn, e, depth: int = 0) -> bool:
        """`e` is a fixed path: a string, a module constant, a local bound only to
        such, or Path() / os.path.join() / `/` / an f-string of those."""
        if depth > 4:
            return False
        if isinstance(e, ast.Constant):
            return isinstance(e.value, str)
        if isinstance(e, ast.Name):
            if fn is not None and e.id in fn.free:
                return False
            if fn is not None and e.id in fn.assigned:
                binds = fn.assigned[e.id]
                return all(k == "=" and self._constant_path(m, fn, x, depth + 1) for k, x in binds)
            v = m.const_node(e.id, fn)
            return v is not None and self._constant_path(m, None, v, depth + 1)
        if isinstance(e, ast.Call) and _call_name(e) in PATH_BUILDERS and e.args and not e.keywords:
            return all(self._constant_path(m, fn, a, depth + 1) for a in e.args)
        if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Div):
            return self._constant_path(m, fn, e.left, depth + 1) and self._constant_path(m, fn, e.right, depth + 1)
        if isinstance(e, ast.JoinedStr):
            return all(isinstance(v, ast.Constant) for v in e.values)
        return False

    def _injected(self, m, n) -> bool:
        """A string that is the `new=` text of a patch (old versions kept only to be found and removed are not)."""
        p = m.parent.get(n)
        if isinstance(p, ast.keyword) and p.arg == "new":
            return True
        return isinstance(p, ast.Assign) and m.scope.get(n) is None and m.where(n) in self.new_names

    def failure_info_send(self, m, n, fn) -> str:
        """The title text when `n` is a notifier .send() of a failure-shaped title without alert=True."""
        if not (isinstance(n, ast.Call) and _call_name(n) == "send" and n.args and isinstance(n.func, ast.Attribute)):
            return ""
        recv = n.func.value
        recv_name = recv.attr if isinstance(recv, ast.Attribute) else recv.id if isinstance(recv, ast.Name) else ""
        if "notifier" not in recv_name.lower():
            return ""
        kws = {kw.arg: kw.value for kw in n.keywords}
        if any(isinstance(kws.get(k), ast.Constant) and kws[k].value is True for k in ("alert", "daily")):
            return ""
        text = self._title_text(m, n.args[0], fn)
        return text if text and FAIL_TITLE.search(text) else ""

    def _scan_info_sends(self, m, fn, nodes):
        for n in nodes:
            if text := self.failure_info_send(m, n, fn):
                self.add(m, n, "MUTE-info", f"failure-shaped title sent without alert=True: {text[:40]!r}", fn=fn)

    def _scan_guards(self, m, fn):
        def leads(x) -> bool:
            return self.is_alarm_call(m, x, fn) or (isinstance(x, ast.Call) and self.resolve(m, x, fn) in self.alarms) \
                or bool(self.failure_info_send(m, x, fn))
        sends = [n.lineno for n in fn.nodes if leads(n)]
        if not sends:
            return
        last = max(sends)
        for n in fn.nodes:
            if not isinstance(n, ast.If) or n.lineno >= last or not n.body \
                    or not isinstance(n.body[-1], (ast.Return, ast.Continue, ast.Break)):
                continue
            if any(self.is_alarm_call(m, x, fn) for b in n.body for x in ast.walk(b)):
                continue      # it alarms on its own way out (an info send there is a demotion: still a hit)
            if isinstance(n.body[-1], (ast.Continue, ast.Break)):
                # skipping an item only matters when the alarm is inside that loop
                loop = m.parent.get(n)
                while loop is not None and loop is not fn.node and not isinstance(loop, (ast.For, ast.While)):
                    loop = m.parent.get(loop)
                if not isinstance(loop, (ast.For, ast.While)) or not any(
                        leads(x) and x.lineno > n.lineno for x in ast.walk(loop)):
                    continue
            if any(isinstance(x, ast.Call) and _call_name(x).startswith("send") for x in ast.walk(n.test)):
                continue      # `if notifier.send(...): return` - the send failed, retry later
            # Back through locals too: `if push not in (...)` where push = ..., and
            # `if "no-shutdown" in done` where done = store.get("marks", f"alerted:{day}").
            words, todo, seen = _words(n.test), [(n.test, 0)], set()
            while todo:
                expr, depth = todo.pop()
                for name in {x.id for x in ast.walk(expr) if isinstance(x, ast.Name)} - seen:
                    seen.add(name)
                    for _, x in fn.assigned.get(name, []):
                        if x is not None and depth < 2:
                            words |= _words(x)
                            todo.append((x, depth + 1))
            once = sorted(w for w in words if DEDUPE.search(w))
            kind = sorted(w for w in words if FAILKIND.search(w))
            # `if pid in self._handled: return` where the module adds to _handled: once per key
            once += [f"{_ref(c.comparators[0])} (added to elsewhere)" for c in ast.walk(n.test)
                     if isinstance(c, ast.Compare) and isinstance(c.ops[0], ast.In)
                     and _ref(c.comparators[0]) in self._grown(m)]
            # `if v.code not in _STUCK_CODES: return`: a fixed list decides which kinds alarm
            kind += [f"{c.comparators[0].id} (fixed list)" for c in ast.walk(n.test)
                     if isinstance(c, ast.Compare) and isinstance(c.ops[0], (ast.In, ast.NotIn))
                     and isinstance(c.comparators[0], ast.Name) and m.const_collection(c.comparators[0], fn) is not None]
            if once:
                self.add(m, n, "MUTE-once", "early exit before the alarm on " + ", ".join(sorted(set(once))), fn=fn)
            elif kind:
                self.add(m, n, "MUTE-guard", "early exit before the alarm on " + ", ".join(sorted(set(kind))), fn=fn)

    def _grown(self, m: Module) -> set[str]:
        """Containers the module adds keys to (`x.add(k)`, `x.append(k)`, `x[k] = v`)."""
        if not hasattr(m, "_grown"):
            out = set()
            for n in ast.walk(m.tree):
                if isinstance(n, ast.Call) and _call_name(n) in ("add", "append") and isinstance(n.func, ast.Attribute):
                    out.add(_ref(n.func.value))
                elif isinstance(n, ast.Assign):
                    out |= {_ref(t.value) for t in n.targets if isinstance(t, ast.Subscript)}
            m._grown = out - {""}
        return m._grown

    @staticmethod
    def _route_collections(m) -> set[str]:
        f = m.fns.get("route_of")
        if f is None:
            return set()
        return {n.id for n in f.nodes if isinstance(n, ast.Name) and m.const_collection(n, None) is not None}

    # rule 2: a stored command applied --------------------------------------
    def user_command(self, hit: Hit) -> str:
        """The user's action a hit applies (rule 2), or ''."""
        m, fn, node = self.mods[hit.rel], hit.fn, hit.node
        if fn is None or node is None:
            return ""
        control = None
        if isinstance(node, ast.If) and hit.rule in ("MUTE-once", "MUTE-guard"):
            control = node.test
        else:
            n = node
            while n in m.parent and n is not fn.node:
                p = m.parent[n]
                if isinstance(p, ast.If) and n is not p.test:
                    control = p.test
                    break
                if isinstance(p, (ast.For, ast.AsyncFor)) and n is not p.iter and n is not p.target:
                    control = p.iter
                    break
                n = p
        if control is None:
            return ""
        return self._reader_action(m, fn, control)

    def _reader_action(self, m, fn, test) -> str:
        """The stored command whose reader `test` calls, directly or through a local."""
        readers = {v: k for k, v in COMMAND_RECORDS.items()}
        for c in self._reader_calls(m, fn, test, frozenset()):
            target = self.resolve(m, c, fn)
            if target and f"{target[0]}:{target[1]}" in readers:
                return readers[f"{target[0]}:{target[1]}"]
        return ""

    # R3 - R8b ----------------------------------------------------------------
    def allowed(self, hit: Hit) -> str:
        """The narrow rule a hit passes by, or ''."""
        return (self._one_push(hit) or self._relay_power_off(hit) or self._restored(hit) or self._log_route(hit)
                or self._game_counter(hit) or self._ends_failed(hit))

    def _one_push(self, hit: Hit) -> str:
        m, fn, n = self.mods[hit.rel], hit.fn, hit.node
        if hit.rule != "MUTE-once" or fn is None or not isinstance(n, ast.If):
            return ""
        mark = ""
        for ln in (n.lineno, n.lineno - 1):
            if 0 < ln <= len(m.lines) and (mt := ONE_PUSH.search(m.lines[ln - 1])):
                mark = mt.group(1).strip()
                break
        if not mark:
            return ""
        keys = []
        for c in ast.walk(n.test):
            if isinstance(c, ast.Compare) and isinstance(c.ops[0], (ast.In, ast.NotIn)):
                keys.append(c.left)
            elif isinstance(c, ast.Call) and DEDUPE.search(_call_name(c)):
                keys += [*c.args, *(k.value for k in c.keywords)]
        return f"R3 one fault, one push: {mark}" if any(self._identity(fn, k) for k in keys) else ""

    def _identity(self, fn, e, depth: int = 0) -> bool:
        """R3 (b): `e` names a per-occurrence identity, through simple local assignments."""
        def counts(name) -> bool:
            binds = fn.assigned.get(name, [])
            return bool(IDENTITY.search(name)) and not (
                binds and all(k == "=" and _constant_only(x) for k, x in binds))
        if isinstance(e, ast.Name):
            binds = fn.assigned.get(e.id, [])
            if counts(e.id):
                return True
            if depth == 0 and binds and all(k == "=" for k, _ in binds):
                return all(self._identity(fn, x, 1) for _, x in binds)
            return False
        for x in ast.walk(e):
            if isinstance(x, ast.Name) and counts(x.id):
                return True
            if isinstance(x, ast.Attribute) and IDENTITY.search(x.attr):
                return True
            if isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant) \
                    and isinstance(x.slice.value, str) and IDENTITY.search(x.slice.value):
                return True
        return False

    def _relay_power_off(self, hit: Hit) -> str:
        """R4: in service.py, under errwatch.relay_shutdown_issued() and nothing else."""
        m, fn, n = self.mods[hit.rel], hit.fn, hit.node
        if hit.rel != R4_FILE or fn is None or n is None:
            return ""
        if hit.rule in ("MUTE-guard", "MUTE-once") and isinstance(n, ast.If):
            tests = [n.test]
        elif hit.rule == "MUTE-log" and _is_log(n) and n.func.attr in ("info", "debug"):
            tests, x = [], n
            while x in m.parent and x is not fn.node:
                p = m.parent[x]
                if isinstance(p, ast.If) and x in p.body:
                    tests.append(p.test)
                x = p
        else:
            return ""
        signal, wrapper = tuple(RELAY_POWER_OFF.split(":")), tuple(R4_WRAPPER.split(":"))
        for t in tests:
            for c in _positive_calls(t):
                target = self.resolve(m, c, fn)
                if target == wrapper:
                    self.wrapper_used = True
                if (target == signal and not c.args and not c.keywords) \
                        or (target == wrapper and not self.wrapper_problems()):
                    return f"R4 the relay itself issued the power-off ({_call_name(c)})"
        return ""

    def wrapper_problems(self) -> list[str]:
        """R4: R4_WRAPPER waits for relay_shutdown_issued() and asks nothing else."""
        rel, qual = R4_WRAPPER.split(":")
        wm = self.mods.get(rel)
        wf = wm.fns.get(qual) if wm is not None else None
        if wf is None:
            return [f"R4: {R4_WRAPPER} does not exist"]
        out, asked = [], False
        for c in wf.calls:
            target = self.resolve(wm, c, wf)
            if target == tuple(RELAY_POWER_OFF.split(":")) and not c.args and not c.keywords:
                asked = True
            elif _call_name(c) not in WRAPPER_PLAIN_CALLS:
                out.append(f"R4: {R4_WRAPPER} line {c.lineno} calls {_call_name(c)}(): "
                           "not the relay's own power-off signal")
        if not asked:
            out.append(f"R4: {R4_WRAPPER} does not ask errwatch.relay_shutdown_issued()")
        return out

    def _restored(self, hit: Hit) -> str:
        """R5: `old = setter(x, False)` given back in a `finally:` of the same function."""
        m, fn, v = self.mods[hit.rel], hit.fn, hit.node
        if hit.rule != "OFF-literal" or fn is None:
            return ""
        p = m.parent.get(v)
        call = m.parent.get(p) if isinstance(p, ast.keyword) else p
        if not isinstance(call, ast.Call):
            return ""
        slot = ("kw", p.arg) if isinstance(p, ast.keyword) else ("pos", next(
            (i for i, a in enumerate(call.args) if a is v), -1))
        target = self.resolve(m, call, fn)
        asg = m.parent.get(call)
        if target not in self.setters or slot == ("pos", -1) or not (
                isinstance(asg, ast.Assign) and asg.value is call and len(asg.targets) == 1
                and isinstance(asg.targets[0], ast.Name)):
            return ""
        old = asg.targets[0].id

        def value_at(c):
            if slot[0] == "pos":
                return c.args[slot[1]] if slot[1] < len(c.args) else None
            return next((k.value for k in c.keywords if k.arg == slot[1]), None)

        def rest(c):
            args = [ast.dump(a) for i, a in enumerate(c.args) if slot != ("pos", i)]
            return args, sorted(ast.dump(k) for k in c.keywords if slot != ("kw", k.arg))

        for t in fn.nodes:
            if not isinstance(t, ast.Try) or not t.finalbody or not (
                    t.lineno > asg.lineno or any(asg is x for b in t.body for x in ast.walk(b))):
                continue
            for b in t.finalbody:
                for r in ast.walk(b):
                    if not isinstance(r, ast.Call) or self.resolve(m, r, fn) != target or rest(r) != rest(call):
                        continue
                    back = value_at(r)
                    if isinstance(back, ast.Name) and back.id == old:
                        return f"R5 put back in finally ({old})"
                    under = _body_if(m, r, fn)
                    if isinstance(back, ast.Constant) and back.value is True and under is not None \
                            and isinstance(under.test, ast.Name) and under.test.id == old \
                            and any(under is x for x in ast.walk(b)):
                        return f"R5 put back in finally (if {old})"
        return ""

    def _log_route(self, hit: Hit) -> str:
        """R7: notify's 「不推送」 line, in `if route == "log"`, route from route_of alone."""
        m, fn, n = self.mods[hit.rel], hit.fn, hit.node
        if hit.rule != "MUTE-log" or fn is None or f"{hit.rel}:{fn.qual}" != LOG_ROUTE_SITE or not _is_log(n):
            return ""
        guard, in_body = _nearest_if(m, n, fn)
        t = guard.test if guard is not None and in_body else None
        if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)):
            return ""
        sides = [t.left, t.comparators[0]]
        name = next((x.id for x in sides if isinstance(x, ast.Name)), None)
        if name is None or not any(isinstance(x, ast.Constant) and x.value == LOG_ROUTE for x in sides):
            return ""
        binds = fn.assigned.get(name, [])
        if len(binds) != 1 or binds[0][0] != "=" or not isinstance(binds[0][1], ast.Call) \
                or self.resolve(m, binds[0][1], fn) != tuple(LOG_ROUTER.split(":")):
            return ""
        self.log_route_used = True
        return "" if self.log_route_problems() else "R7 the log route is route_of's routed collections alone"

    def log_route_problems(self) -> list[str]:
        """R7 on route_of: "log" only under a test of the title against its routed
        collections, and no failure-shaped string that such a test lets through."""
        if self._log_route_problems is not None:
            return self._log_route_problems
        rel, qual = LOG_ROUTER.split(":")
        m = self.mods.get(rel)
        f = m.fns.get(qual) if m is not None else None
        if f is None:
            self._log_route_problems = [f"R7: {LOG_ROUTER} does not exist"]
            return self._log_route_problems
        routed, out, matchers = self._route_collections(m), [], []
        title = (f.method_params() or [None])[0]
        for r in f.nodes:
            if not isinstance(r, ast.Return):
                continue
            v = m.const_value(r.value, f) if r.value is not None else MISSING
            if not isinstance(v, str):
                out.append(f"R7: {LOG_ROUTER} line {r.lineno} returns something other than a route name")
                continue
            if v != LOG_ROUTE:
                continue
            guard, in_body = _nearest_if(m, r, f)
            tests = _title_tests(m, guard.test, title, routed) if guard is not None and in_body else None
            if not tests:
                out.append(f'R7: {LOG_ROUTER} line {r.lineno} returns "{LOG_ROUTE}" other than under a test of '
                           f"the title against {', '.join(sorted(routed)) or 'a routed collection'}")
                continue
            matchers += tests
        for how, coll in matchers:
            items = [e.value for e in m.const_collection(ast.Name(id=coll), None).elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            for om in self.mods.values():
                for text, line in _plain_strings(om):
                    if not FAIL_TITLE.search(text):
                        continue
                    for item in items:
                        if (how == "prefix" and text.startswith(item)) or (how == "contains" and item in text) \
                                or (how == "equals" and text == item):
                            out.append(f"R7: {om.rel}:{line} failure-shaped {text[:40]!r} is routed to "
                                       f"\"{LOG_ROUTE}\" by {coll}[{item}]")
        self._log_route_problems = out
        return out

    def _game_counter(self, hit: Hit) -> str:
        """R8: `raise TaskDisabledException` in the true branch of `x == 0`, x read off
        the game screen in the same function, the reading and the branch logged."""
        m, fn, n = self.mods[hit.rel], hit.fn, hit.node
        if hit.rule != "OFF-skip" or fn is None or not isinstance(n, ast.Raise) \
                or not _words(n.exc) & self.skip_classes(m)[0]:
            return ""
        guard, in_body = _nearest_if(m, n, fn)
        t = guard.test if guard is not None and in_body else None
        if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)):
            return ""
        sides = [t.left, t.comparators[0]]
        zero = any(isinstance(x, ast.Constant) and type(x.value) is int and x.value == 0 for x in sides)
        name = next((x.id for x in sides if isinstance(x, ast.Name)), None)
        chain = _screen_chain(fn, name) if zero and name else set()
        if not chain:
            return ""
        branch_logs = any(_is_task_log(x) and x.lineno < n.lineno for b in guard.body for x in ast.walk(b))
        reading_logged = any(_is_task_log(c) and any(isinstance(y, ast.Name) and y.id in chain
                                                     for a in [*c.args, *(k.value for k in c.keywords)]
                                                     for y in ast.walk(a)) for c in fn.calls)
        return f"R8 the game's own counter reads 0 ({name}, off the screen)" if branch_logs and reading_logged else ""

    def _ends_failed(self, hit: Hit) -> str:
        """R8b: a subclass of TaskDisabledException that the same file turns into a failure."""
        m, fn, n = self.mods[hit.rel], hit.fn, hit.node
        if hit.rule != "OFF-skip" or fn is None or not isinstance(n, ast.Raise):
            return ""
        base, subs = self.skip_classes(m)
        words = _words(n.exc)
        sub = words & subs
        if not sub or words & base:
            return ""
        skips = base | subs
        handlers = [h for h in ast.walk(m.tree) if isinstance(h, ast.ExceptHandler) and h.type is not None
                    and _words(h.type) & sub]
        for h in handlers:
            if any(_failure_raise(x, skips) for b in h.body for x in ast.walk(b)):
                return f"R8b turned into a failure in its handler (line {h.lineno})"
        flags = {t.attr for x in fn.nodes if isinstance(x, ast.Assign) and x.lineno < n.lineno
                 for t in x.targets if isinstance(t, ast.Attribute)}
        for h in handlers:
            g, tr = m.scope.get(h), m.parent.get(h)
            if g is None or not isinstance(tr, ast.Try) or (h.body and isinstance(h.body[-1], ast.Raise)):
                continue      # it always raises on: only (a) above can make that a failure
            for r in g.nodes:
                if not _failure_raise(r, skips) or r.lineno <= tr.end_lineno:
                    continue
                guard, in_body = _nearest_if(m, r, g)
                if guard is not None and in_body and _expr_words(g, guard.test) & flags:
                    attr = "/".join(sorted(_expr_words(g, guard.test) & flags))
                    return (f"R8b recorded as .{attr} and raised as a failure after its handler "
                            f"(line {h.lineno}, raise line {r.lineno})")
        return ""

    def _reader_calls(self, m, fn, e, seen):
        """Calls in `e`, following locals that hold nothing but a call's result."""
        out = []
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
            e = e.operand
        if isinstance(e, ast.Call):
            out.append(e)
        elif isinstance(e, ast.Name) and e.id in fn.assigned and e.id not in seen:
            binds = fn.assigned[e.id]
            if all(k == "=" and isinstance(x, ast.Call) for k, x in binds):
                for _, x in binds:
                    out += self._reader_calls(m, fn, x, seen | {e.id})
        return out


def _ref(e) -> str:
    """`self._handled` -> "_handled", `seen` -> "seen"; '' for anything else."""
    return e.attr if isinstance(e, ast.Attribute) else e.id if isinstance(e, ast.Name) else ""


def _words(e) -> set[str]:
    """Names, attributes and strings in an expression."""
    if e is None:
        return set()
    return {x.id if isinstance(x, ast.Name) else x.attr if isinstance(x, ast.Attribute) else x.value
            for x in ast.walk(e) if isinstance(x, (ast.Name, ast.Attribute))
            or (isinstance(x, ast.Constant) and isinstance(x.value, str))}


def _switch_strings(keys: set[str]) -> set[str]:
    return {k for k in keys if SWITCH_KEY.match(k)}


def _is_log(n) -> bool:
    if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute) or n.func.attr not in LOG_METHODS:
        return False
    b = n.func.value
    name = b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else ""
    return "log" in name.lower()


def _body_if(m: Module, node, fn: Fn):
    """The nearest `if` whose body (not its test, not its else) holds `node`, or None."""
    x = node
    while x in m.parent and x is not fn.node:
        p = m.parent[x]
        if isinstance(p, ast.If) and any(x is s for s in p.body):
            return p
        x = p
    return None


def _positive_calls(test) -> list:
    """Calls a condition makes true by being true: the call itself, or one and-ed in."""
    if isinstance(test, ast.Call):
        return [test]
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return [c for v in test.values for c in _positive_calls(v)]
    return []


def _constant_only(e) -> bool:
    """An expression built from constants alone (no name, attribute, call or subscript)."""
    return not any(isinstance(x, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)) for x in ast.walk(e))


def _nearest_if(m: Module, node, fn: Fn):
    """(the nearest `if` around `node`, whether `node` is in its body - not its test
    or its else); (None, False) when there is none inside `fn`."""
    x = node
    while x in m.parent and x is not fn.node:
        p = m.parent[x]
        if isinstance(p, ast.If):
            return p, any(x is b for b in p.body)
        x = p
    return None, False


def _is_task_log(n) -> bool:
    """A log line: `log.info(...)`, or OK-WW's own `self.log_info(...)`."""
    return _is_log(n) or (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in TASK_LOGS)


def _unnegated_calls(test) -> list:
    """Calls in a condition that are not under a `not`."""
    out, todo = [], [test]
    while todo:
        e = todo.pop()
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
            continue
        if isinstance(e, ast.Call):
            out.append(e)
        todo += list(ast.iter_child_nodes(e))
    return out


def _exists_target(c: ast.Call):
    """The path an existence test asks about: `os.path.exists(p)` -> p, `p.exists()` -> p."""
    f = c.func
    if not isinstance(f, ast.Attribute):
        return None
    if f.attr in EXISTS_FUNCS and isinstance(f.value, ast.Attribute) and f.value.attr == "path" and c.args:
        return c.args[0]
    if f.attr in EXISTS_METHODS and not c.args and not c.keywords:
        return f.value
    return None


def _title_tests(m: Module, test, title, routed: set[str]):
    """R7: [(how, collection)] when `test` checks the title against routed
    collections and nothing else - `title.startswith(C)`, `any(s in title for s
    in C)`, `title in C`, or an `or` of those; None otherwise."""
    def is_title(e):
        return isinstance(e, ast.Name) and e.id == title

    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        parts = [_title_tests(m, v, title, routed) for v in test.values]
        return None if any(p is None for p in parts) else [x for p in parts for x in p]
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute) and test.func.attr == "startswith" \
            and is_title(test.func.value) and len(test.args) == 1 and not test.keywords \
            and isinstance(test.args[0], ast.Name) and test.args[0].id in routed:
        return [("prefix", test.args[0].id)]
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.In) \
            and is_title(test.left) and isinstance(test.comparators[0], ast.Name) and test.comparators[0].id in routed:
        return [("equals", test.comparators[0].id)]
    if isinstance(test, ast.Call) and _call_name(test) == "any" and len(test.args) == 1 \
            and isinstance(test.args[0], ast.GeneratorExp) and len(test.args[0].generators) == 1:
        g, gen = test.args[0], test.args[0].generators[0]
        e = g.elt
        if not gen.ifs and isinstance(gen.target, ast.Name) and isinstance(gen.iter, ast.Name) \
                and gen.iter.id in routed and isinstance(e, ast.Compare) and len(e.ops) == 1 \
                and isinstance(e.ops[0], ast.In) and isinstance(e.left, ast.Name) and e.left.id == gen.target.id \
                and is_title(e.comparators[0]):
            return [("contains", gen.iter.id)]
    return None


def _plain_strings(m: Module):
    """(text, line) of every string in `m` that could be a title: literals and the
    literal parts of f-strings, not docstrings and not the arguments of a log line."""
    for n in ast.walk(m.tree):
        if isinstance(n, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in m.docstrings \
                and not isinstance(m.parent.get(n), ast.JoinedStr):
            text = n.value
        else:
            continue
        x = n
        while x in m.parent and not isinstance(x, ast.stmt) and not _is_log(x):
            x = m.parent[x]
        if not _is_log(x):
            yield text, n.lineno


def _is_screen_read(c) -> bool:
    """OK-WW reading text off the game screen: `self.ocr(...)` / `task.ocr(...)`."""
    return isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == SCREEN_READ \
        and isinstance(c.func.value, ast.Name)


def _screen_chain(fn: Fn, name: str) -> set[str]:
    """R8: the locals from `name` back to a screen read in `fn`, when every binding
    on the way is a constant, a screen read, or built from such locals alone (no
    parameter, no `self`, no `+=`); empty otherwise."""
    chain, todo, rooted = set(), [name], False
    while todo:
        x = todo.pop()
        if x in chain:
            continue
        if x in fn.params or not fn.assigned.get(x):
            return set()
        chain.add(x)
        for kind, e in fn.assigned[x]:
            if kind == "other" or e is None:
                return set()
            if _constant_only(e):
                continue
            reads = [c for c in ast.walk(e) if _is_screen_read(c)]
            rooted = rooted or bool(reads)
            inside = {id(y) for c in reads for y in ast.walk(c)}
            for y in ast.walk(e):
                if id(y) in inside or not isinstance(y, ast.Name):
                    continue
                if y.id in fn.params:
                    return set()
                if y.id in fn.assigned:
                    todo.append(y.id)
    return chain if rooted else set()


def _failure_raise(r, skips: set[str]) -> bool:
    """`raise X(...)` of a class that is neither TaskDisabledException nor a subclass of it."""
    if not isinstance(r, ast.Raise) or r.exc is None:
        return False
    e = r.exc.func if isinstance(r.exc, ast.Call) else r.exc
    name = e.id if isinstance(e, ast.Name) else e.attr if isinstance(e, ast.Attribute) else ""
    return bool(name) and name not in skips


def _expr_words(fn: Fn, e) -> set[str]:
    """_words of `e` and of what its locals are bound to, two assignments deep."""
    words, todo, seen = _words(e), [(e, 0)], set()
    while todo:
        expr, depth = todo.pop()
        for name in {x.id for x in ast.walk(expr) if isinstance(x, ast.Name)} - seen:
            seen.add(name)
            for _, x in fn.assigned.get(name, []):
                if x is not None and depth < 2:
                    words |= _words(x)
                    todo.append((x, depth + 1))
    return words


def _inside_if(m: Module, node, fn: Fn) -> bool:
    n = node
    while n in m.parent and n is not fn.node:
        p = m.parent[n]
        if isinstance(p, ast.If) and n is not p.test:
            return True
        n = p
    return False


# ----------------------------------------------------------------- the list

# The key may hold spaces (`_LOG_ONLY_PREFIXES[⚠️ 自动采集：…]`): it is everything before the first " | ".
LINE_RE = re.compile(r"^(?P<key>[^|\s][^|]*?\.py:[^|]*?\S)\s+\|\s+(?P<what>.+?)\s+\|\s+(?P<words>.+?)\s+\|\s+(?P<when>.+?)\s*$")
QUOTE_RE = re.compile(r"「[^」]*[\u4e00-\u9fff][^」]*」")
WHEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}\b")


def read_list(text: str) -> tuple[dict[str, str], list[str]]:
    """{key: line}, and what is wrong with lines that lack one of the four fields."""
    out, bad = {}, []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        mt = LINE_RE.match(line)
        if not mt:
            bad.append(f"USER-SWITCHES.txt:{i}: not `file:function | what | 「his words」 | YYYY-MM-DD HH:MM`")
            continue
        if not QUOTE_RE.search(mt["words"]):
            bad.append(f"USER-SWITCHES.txt:{i}: {mt['key']}: no quote of the user's own Chinese words in 「」")
        if not WHEN_RE.match(mt["when"]):
            bad.append(f"USER-SWITCHES.txt:{i}: {mt['key']}: no date and time (YYYY-MM-DD HH:MM)")
        out[mt["key"]] = line
    return out, bad


def relay_sources(root: Path = RELAY) -> dict[str, str]:
    files = sorted((root / "ark_relay").rglob("*.py")) + [root / "service.py", root / "boot_stages.py"]
    return {f.relative_to(root).as_posix(): f.read_text(encoding="utf-8") for f in files if f.is_file()}


def command_records_hold(scan: Scan) -> list[str]:
    """Rule 2's readers are what COMMAND_RECORDS says: whitelisted, dispatched, present."""
    out = []
    cm = scan.mods.get("ark_relay/commands.py")
    if cm is None:
        return ["commands.py not found: rule 2 cannot be checked"]
    allowed = set()
    for name in ("REVERSIBLE", "MUTATING"):
        coll = cm.const_collection(ast.Name(id=name), None)
        allowed |= {e.value for e in (coll.elts if coll is not None else []) if isinstance(e, ast.Constant)}
    apply = cm.fns.get("apply_command")
    dispatched = {c.comparators[0].value for c in (apply.nodes if apply else [])
                  if isinstance(c, ast.Compare) and isinstance(c.left, ast.Name) and c.left.id == "action"
                  and isinstance(c.comparators[0], ast.Constant)}
    for action, reader in COMMAND_RECORDS.items():
        rel, qual = reader.split(":")
        if action not in allowed:
            out.append(f"rule 2: {action} is not in commands.REVERSIBLE | MUTATING")
        if action not in dispatched:
            out.append(f"rule 2: commands.apply_command does not dispatch {action}")
        if rel not in scan.mods or qual not in scan.mods[rel].fns:
            out.append(f"rule 2: the reader {reader} does not exist")
    return out


def verdict(hits: list[Hit], listed: dict[str, str]) -> list[str]:
    fails = [f"{h.rel}:{h.line}: {h.key} [{h.rule}] is not in USER-SWITCHES.txt - {h.text}"
             for h in hits if h.key not in listed]
    keys = {h.key for h in hits}
    fails += [f"USER-SWITCHES.txt: {k} has no hit any more - delete the line (a stale line pre-approves the next one)"
              for k in listed if k not in keys]
    return fails


def findings(scan: Scan) -> tuple[list[Hit], list[tuple[Hit, str]], list[tuple[Hit, str]]]:
    """(hits that need a line, hits that apply a stored user command, hits that pass R3-R5)."""
    need, commands, allowed = [], [], []
    for h in sorted(scan.hits, key=lambda h: (h.rel, h.line, h.rule)):
        if action := scan.user_command(h):
            commands.append((h, action))
        elif why := scan.allowed(h):
            allowed.append((h, why))
        else:
            need.append(h)
    return need, commands, allowed


# ----------------------------------------------------------------- self-checks

LOG = "import logging\nlog = logging.getLogger()\n"
ERRWATCH = ("def going_down(extra=None):\n    return False\ndef system_shutting_down():\n    return False\n"
            "def relay_shutdown_issued():\n    return False\n")
AUTO_START = dedent('''\
    import json
    def _auto(path, value):
        data = json.loads(path.read_text())
        was = bool(data.get("Auto Start", False))
        data["Auto Start"] = value
        path.write_text(json.dumps(data))
        return was
    ''')
COMMAND_SAMPLE_BASE = {
    "ark_relay/commands.py": ('REVERSIBLE = {"debug_mode", "skip_today"}\nMUTATING = set()\n'
                              'def apply_command(cmd):\n    action = cmd["action"]\n'
                              '    if action == "debug_mode":\n        return 1\n'
                              '    if action == "skip_today":\n        return 2\n'),
    "ark_relay/modes.py": ('from . import queues\ndef debug_active(d):\n    return False\n'
                           'def _day_queues(store, day):\n    return []\n'
                           'def _maybe_engage(store, d, day):\n    wanted = _day_queues(store, day)\n'
                           '    for queue in wanted:\n        queues.apply(d, queue, enabled=False)\n'),
    "ark_relay/queues.py": 'def apply(d, name, enabled=None):\n    pass\n',
}
# Shaped like commands.py / handle.py / boot_stages.py: the red button's chain that
# rule 2b checked until 2026-10-06. Now its manual_stop exit is a hit like any other.
ESTOP_SAMPLE = {
    "ark_relay/commands.py": dedent('''\
        ESTOP_SEED = ({"start": "2026-09-30T09:46:28+08:00", "end": "2026-09-30T09:47:22+08:00"},)
        def _estop_windows_path(d):
            return d
        def _estop_window_mark(d, start):
            atomic_write_text(_estop_windows_path(d), start)
        def merge_estop_seed(d):
            atomic_write_text(_estop_windows_path(d), str(ESTOP_SEED))
        def estop_windows(d):
            return []
        def estop_label(windows, started, finished):
            return ""
        def estop(state_dir=None):
            _estop_window_mark(state_dir, "now")
            return True, ""
        '''),
    "ark_relay/handle.py": dedent('''\
        from . import commands
        def _estop_overlap(eng, rec):
            try:
                return commands.estop_label(commands.estop_windows(eng.d), rec.started, rec.finished)
            except Exception:
                pass
            return ""
        def backfill(eng, entries):
            windows = commands.estop_windows(eng.d)
            for e in entries:
                if not (label := commands.estop_label(windows, e["s"], e["f"])):
                    continue
                e["raw"]["manual_stop"] = label
        def _handle(eng, rec):
            if stop := _estop_overlap(eng, rec):
                rec.raw["manual_stop"] = stop
            if rec.raw.get("manual_stop"):
                return
            eng.notifier.send("❌ 失败", "b", alert=True)
        '''),
    "boot_stages.py": dedent('''\
        def _make_phone_cmd(cfg_state_dir):
            def run_phone_cmd(body):
                action = str(body.get("action") or "")
                if action == "estop":
                    from ark_relay import commands as _cmd
                    ok, msg = _cmd.estop(state_dir=cfg_state_dir)
                    return
            return run_phone_cmd
        '''),
}
# R7 on a sample shaped like notify.py.
NOTIFY = dedent('''\
    import logging
    log = logging.getLogger()
    _LOG_ONLY_PREFIXES = ("🔄 中继已更新", "✅ ")
    def route_of(title, *, alert=False, daily=False):
        if daily:
            return "daily"
        if title.startswith(_LOG_ONLY_PREFIXES):
            return "log"
        if alert:
            return "group"
        return "info"
    class Notifier:
        def send(self, title, body, *, alert=False, daily=False):
            route = route_of(title, alert=alert, daily=daily)
            if route == "log":
                log.info("不推送（日报或手机页已有）：%s", title)
                return []
            return self._fan_out(title, body)
    ''')
# R8 on a sample shaped like ark_overrides' click_configured_boss_level.
BOSS = dedent('''\
    def _left(text):
        return 0 if "0/3" in text else None
    class T:
        def click_level(self):
            left = None
            try:
                left = self.ocr(box=self.box_of_screen(0.58, 0.80, 0.98, 0.90))
                self.log_info(f"剩余次数原文: {left}")
            except Exception:
                pass
            text = " ".join(str(b) for b in (left or []))
            now = _left(text)
            if now == 0:
                self.log_info("本周次数已领满（0/3），跳过")
                raise TaskDisabledException()
            return now
    ''')
# R8b on a sample shaped like ark_overrides' _ArkStop / _end_failed / FarmEchoTask.run.
STOP = dedent('''\
    class Stopped(Exception):
        pass
    _Stop = Exception
    def install():
        global _Stop
        from ok import TaskDisabledException as _TDE
        _Stop = type("Stop", (_TDE,), {})
    def end_failed(task, why):
        task._failed = why
        raise _Stop()
    def run(self):
        try:
            got = self.inner()
        except _Stop:
            got = None
        why = getattr(self, "_failed", None)
        if why:
            raise Stopped(why)
        return got
    ''')
BAD = {
    "literal False to enabled": ('def f(t):\n    t["enabled"] = False\n', "OFF-literal"),
    "If-switch off, deep key": ('def f(cfg):\n    cfg["Task"]["IfSanity"] = 0\n', "OFF-literal"),
    "flag keys in a loop": ('KEYS = ("enabled", "enabledByController")\ndef f(t):\n'
                            '    for k in KEYS:\n        t[k] = False\n', "OFF-literal"),
    "per-controller copy": ('def f(task):\n    ctl = task.get("enabledByController")\n'
                            '    for k in ctl:\n        ctl[k] = False\n', "OFF-literal"),
    "dict literal written": ('def f(api):\n    api.post({"Info": {"TimeEnabled": False}})\n', "OFF-literal"),
    "switch option": ('def f(ov):\n    ov["X"] = {"type": "switch", "value": False}\n', "OFF-literal"),
    "keyword enabled=False": ('from . import queues\ndef f(d, q):\n    queues.apply(d, q, enabled=False)\n',
                              "OFF-literal"),
    "attribute switch": ('def f(task):\n    task.enabled = False\n', "OFF-literal"),
    "decision through a setter": ('import json\ndef _set(t, on):\n    t["enabled"] = on\n'
                                  'def narrow(path, want):\n    doc = json.loads(path.read_text())\n'
                                  '    for t in doc["tasks"]:\n        _set(t, t["taskName"] in want)\n',
                                  "OFF-decision"),
    "literal through a setter": ('def set_task(path, name, value):\n    j = {}\n'
                                 '    j[name] = {"enabled": bool(value)}\n'
                                 'def g(p):\n    set_task(p, "AutoCollect", False)\n', "OFF-literal"),
    "local decision": ('def f(t, store, now):\n    state = store.load()\n'
                       '    on = state.get("done") != week_key(now)\n    t["checked"] = on\n', "OFF-decision"),
    "Close constant to a writer": ('CLOSED = "Close"\ndef _write_setting(d, v):\n    d.write_text(v)\n'
                                   'class G:\n    def enforce(self):\n        _write_setting(self.d, CLOSED)\n',
                                   "OFF-close"),
    "Close in an API payload": ('def f(sid):\n    _mas("/api/scripts/user/update", '
                                '{"scriptId": sid, "data": {"Info": {"Annihilation": "Close"}}})\n', "OFF-close"),
    "Close stored in a config": ('def f(info, done):\n    info["Annihilation"] = "Close" if done else "x"\n',
                                 "OFF-close"),
    "task removed": ('def f(cfg, write):\n    tasks = list(cfg["TaskList"])\n'
                     '    tasks.remove("Weekly")\n    cfg["TaskList"] = tasks\n    write(cfg)\n', "OFF-remove"),
    "task list filtered": ('def f(cfg, path):\n    cfg["tasks"] = [t for t in cfg["tasks"] if t["n"] != "x"]\n'
                           '    path.write_text(str(cfg))\n', "OFF-remove"),
    "task list rebuilt": ('def f(doc, path, gone):\n    for inst in doc["instances"]:\n        keep = []\n'
                          '        for t in inst["tasks"]:\n            if t["n"] not in gone:\n'
                          '                keep.append(t)\n        inst["tasks"] = keep\n'
                          '    atomic_write_text(path, doc)\n', "OFF-remove"),
    "routes narrowed": ('def f(task, lists, failed, path):\n'
                        '    kept = {k: [r for r in v if r in failed] for k, v in lists.items()}\n'
                        '    for k, v in kept.items():\n        task["optionValues"][k]["caseNames"] = v\n'
                        '    atomic_write_text(path, task)\n', "OFF-remove"),
    "queue item deleted": ('def f(mas, q):\n    mas("/api/queue/item/delete", {"queueId": q})\n', "OFF-remove"),
    "kept off by record": ('def f(store):\n    rec = store.get("updates", "x_disabled_y")\n    return rec\n',
                           "OFF-keep"),
    "kept off by log": (LOG + 'def f():\n    log.info("还是坏的，继续关着")\n', "OFF-keep"),
    "soft set": ('class E:\n    SOFT_FAILS = {"自动采集"}\n', "MUTE-name"),
    "soft use": ('def f(rec, eng):\n    if set(rec.failed_tasks) <= eng.SOFT_FAILS:\n        return\n', "MUTE-name"),
    "soft_only def": ('def soft_only(msg, soft):\n    return True\n', "MUTE-name"),
    "failed vs fixed set": ('def f(e):\n    if set(e["failed_tasks"]) <= {"A", "B"}:\n        return "s"\n',
                            "MUTE-filter"),
    "failed skipped by list": ('PASS = frozenset({"A"})\ndef f(failed):\n    for x in failed:\n'
                               '        if x in PASS:\n            continue\n', "MUTE-filter"),
    "daily-only log": (LOG + 'def f(r):\n    log.warning("%s 记日报不拉警报", r)\n', "MUTE-log"),
    "f-string log": (LOG + 'def f(r):\n    log.info(f"{r} 只进日报")\n', "MUTE-log"),
    "log phrase in a later argument": (LOG + 'def f(r, ok):\n    log.info("%s", "只进日报" if ok else "x")\n',
                                       "MUTE-log"),
    "route table": ('_LOG_ONLY_PREFIXES = ("🔄 中继已更新", "⚠️ 采集没走通")\n'
                    'def route_of(t):\n    if t.startswith(_LOG_ONLY_PREFIXES):\n        return "log"\n'
                    '    return "group"\n', "MUTE-route"),
    "failure sent as information": ('def f(eng, b):\n    eng.notifier.send("❌ 采集失败", b)\n', "MUTE-info"),
    "failure title from a function": ('def title(s):\n    return f"⚠️ {s} 没能确认"\n'
                                      'def f(eng, b):\n    eng.notifier.send(title("x"), b)\n', "MUTE-info"),
    "hourly cap": ('MAX_PER_HOUR = 3\ndef room(p):\n    return len(p) < MAX_PER_HOUR\n', "MUTE-cap"),
    "once per key": ('def push(eng, key, t, b):\n    if eng._already_alerted(key):\n        return True\n'
                     '    eng.notifier.send(t, b, alert=True)\n', "MUTE-once"),
    "kind guard": ('def push(eng, rec, t, b):\n    if rec.maintenance:\n        return\n'
                   '    eng.notifier.send_group("❌ 采集失败", b)\n', "MUTE-guard"),
    "guard before a wrapper": ('def _send(eng, title, body):\n    eng.notifier.send(title, body, alert=True)\n'
                               'def push(eng, rec):\n    for f in rec.items:\n'
                               '        if f.cause == "soft":\n            continue\n        _send(eng, "x", f)\n',
                               "MUTE-guard"),
    "OK-WW stop raised": ('class TaskDisabledException(Exception):\n    pass\n'
                          'def stop(t):\n    raise TaskDisabledException()\n', "OFF-skip"),
    "OK-WW stop patched in": ('_X_NEW = """    self.log_info(\'x\')\n    raise TaskDisabledException()"""\n'
                              'P = _Patch(new=_X_NEW)\n', "OFF-skip"),
    "on/off option through a setter": ('import json\ndef _set(path, value):\n    data = json.loads(path.read_text())\n'
                                       '    was = bool(data.get("Auto Start", False))\n    data["Auto Start"] = value\n'
                                       '    path.write_text(json.dumps(data))\ndef run(p):\n    _set(p, False)\n',
                                       "OFF-literal"),
    "membership dedupe": ('class W:\n    def tick(self, pid):\n        if pid in self._done:\n            return\n'
                          '        self._done.add(pid)\n        self.notifier.send("❌ 卡住", "b", alert=True)\n', "MUTE-once"),
    "fixed list of alarming kinds": ('STUCK = ("a", "b")\ndef say(eng, v):\n    if v.code not in STUCK:\n        return\n'
                                     '    eng.notifier.send("t", "b", alert=True)\n', "MUTE-guard"),
    "guard before a thread that alarms": ('import threading\nclass A:\n    def emit(self, r):\n        if self._sent:\n'
                                          '            return\n        threading.Thread(target=self._push).start()\n'
                                          '    def _push(self):\n        self.n.send("t", "b", alert=True)\n', "MUTE-once"),
    "alarm demoted to information": ('def f(eng, rec):\n    if rec.maintenance:\n        eng.notifier.send("⏸ 进不了游戏", "b")\n'
                                     '        return\n    eng.notifier.send("❌ 失败", "b", alert=True)\n', "MUTE-guard"),
    "debug-like guard not a stored command": ('def debug_active(d):\n    return True\n'
                                              'def check(eng):\n    if debug_active(eng.d):\n        return\n'
                                              '    eng.notifier.send("t", "b", alert=True)\n', "MUTE-guard"),
    # R3: the marker alone is not enough, and an identity alone is not enough
    "one-push marker on a per-day key": (dedent('''\
        def push(eng, day, rec, t, b):
            key = f"{day}|{rec.script}|{rec.user}"
            # one fault, one push: once a day per script
            if eng._already_alerted(day, key):
                return
            eng.notifier.send(t, b, alert=True)
        '''), "MUTE-once"),
    "per-record key without the marker": (dedent('''\
        def push(eng, day, rec, t, b):
            key = f"x|{rec.run_id}"
            if eng._already_alerted(day, key):
                return
            eng.notifier.send(t, b, alert=True)
        '''), "MUTE-once"),
    "one-push marker on a constant member": (dedent('''\
        def say(eng, day):
            done = eng.store.get("marks", f"alerted:{day}") or []
            # one fault, one push: once a day
            if "no-shutdown" in done:
                return
            eng.notifier.send("t", "b", alert=True)
        '''), "MUTE-once"),
    "an identity name bound to a constant": (dedent('''\
        def say(eng, sent):
            text = "今晚不关机"
            # one fault, one push: the same text
            if text in sent:
                return
            sent.add(text)
            eng.notifier.send("t", "b", alert=True)
        '''), "MUTE-once"),
    "one-push marker two lines above": (dedent('''\
        def push(eng, day, rec, t, b):
            key = f"x|{rec.run_id}"
            # one fault, one push: one record
            # (something else in between)
            if eng._already_alerted(day, key):
                return
            eng.notifier.send(t, b, alert=True)
        '''), "MUTE-once"),
    # R4: only service.py, only relay_shutdown_issued(), only its true branch, only below WARNING
    "the relay's power-off outside service.py": ({"ark_relay/errwatch.py": ERRWATCH, "ark_relay/_sample.py": LOG + dedent('''\
        from . import errwatch
        def f(eng):
            if errwatch.relay_shutdown_issued():
                log.info("按关机处理，不算故障")
                return
        ''')}, "MUTE-log"),
    "the relay's power-off negated": ({"ark_relay/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay import errwatch
            if not errwatch.relay_shutdown_issued():
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
    "the else of the relay's power-off": ({"ark_relay/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay import errwatch
            if errwatch.relay_shutdown_issued():
                pass
            else:
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
    "the relay's power-off asked with an argument": ({"ark_relay/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay import errwatch
            if errwatch.relay_shutdown_issued(lambda: True):
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
    "a WARNING kept from the group at the relay's power-off": ({"ark_relay/errwatch.py": ERRWATCH,
                                                                "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay import errwatch
            if errwatch.relay_shutdown_issued():
                log.warning("按关机处理，不算故障")
        ''')}, "MUTE-log"),
    "a wrapper that asks something besides the relay's power-off": ({"ark_relay/errwatch.py": ERRWATCH,
                                                                       "service.py": LOG + dedent('''\
        def _going_down_soon():
            from ark_relay import errwatch
            return errwatch.relay_shutdown_issued() or errwatch.system_shutting_down()
        def f(eng):
            if _going_down_soon():
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
    # until 2026-10-06 these passed R4: Windows going down for any reason is not the relay's power-off
    "Windows going down": ({"ark_relay/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        def f(eng):
            from ark_relay import errwatch
            if errwatch.going_down():
                log.info("按关机处理，不算故障")
        ''')}, "MUTE-log"),
    "a wrapper that asks Windows going down": ({"ark_relay/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        import time
        def _going_down_soon(seconds=15.0):
            from ark_relay import errwatch
            deadline = time.monotonic() + seconds
            while not errwatch.going_down():
                if deadline - time.monotonic() <= 0:
                    return False
                time.sleep(0.5)
            return True
        class K:
            def exited(self):
                if _going_down_soon():
                    log.info("按关机处理，不算故障")
                    return
                log.warning("意外退出")
        ''')}, "MUTE-log"),
    # R5: given back in a finally, by the same setter, for the same thing - or it is a hit
    "temporary setting never put back": (AUTO_START + dedent('''\
        def run(p):
            was = _auto(p, False)
            launch(p)
        '''), "OFF-literal"),
    "put back, but not in a finally": (AUTO_START + dedent('''\
        def run(p):
            was = _auto(p, False)
            launch(p)
            _auto(p, was)
        '''), "OFF-literal"),
    "a finally that puts back another file": (AUTO_START + dedent('''\
        def run(p, q):
            was = _auto(p, False)
            try:
                launch(p)
            finally:
                _auto(q, was)
        '''), "OFF-literal"),
    # R6: a reader that also keeps something off
    "record read to switch on and off": (dedent('''\
        def enable(cfg, names):
            for t in cfg["tasks"]:
                if t["n"] in names:
                    t["enabled"] = True
            cfg.write_text("x")
        def disable(cfg, names):
            for t in cfg["tasks"]:
                t["enabled"] = False
            cfg.write_text("x")
        def keep(store, cfg):
            rec = store.get("updates", "x_disabled")
            enable(cfg, set())
            disable(cfg, set(rec.get("tasks") or []))
        '''), "OFF-keep"),
    # until 2026-10-06 rule 2 / 2a / 2b let these through; each keeps an error out of the group
    "debug mode keeping an alarm away": ({**COMMAND_SAMPLE_BASE, "ark_relay/missed.py": (
        'from . import modes\ndef check(eng):\n    if modes.debug_active(eng.d):\n'
        '        return\n    eng.notifier.send("t", "b", alert=True)\n')}, "MUTE-guard"),
    "debug mode's 不报漏跑 line": ({**COMMAND_SAMPLE_BASE, "ark_relay/engine.py": LOG + (
        'from . import modes\ndef tick(eng):\n    if modes.debug_active(eng.d):\n'
        '        log.info("调试模式生效：不关机、不报漏跑")\n')}, "MUTE-log"),
    "the debug verdict's early exit": ({**COMMAND_SAMPLE_BASE, "ark_relay/shutdown.py": dedent('''\
        from . import modes
        def decide(eng):
            if modes.debug_active(eng.d):
                return V(False, "debug", "x")
            return V(True, "go", "")
        def maybe(eng):
            v = decide(eng)
            if v.code == "debug":
                return False
            eng.notifier.send("t", "b", alert=True)
        ''')}, "MUTE-guard"),
    "the red button's run kept from the group": (ESTOP_SAMPLE, "MUTE-guard"),
    # R7: a second way to the log route, or a failure title on a log-only prefix
    "a second way to the log route": ({"ark_relay/notify.py": NOTIFY.replace(
        '    if alert:\n', '    if "测试" in title:\n        return "log"\n    if alert:\n')}, "MUTE-log"),
    "the log route from a variable": ({"ark_relay/notify.py": NOTIFY.replace(
        '    if alert:\n', '    r = "log" if title.endswith("。") else "info"\n    if alert:\n').replace(
        '    return "info"\n', '    return r\n')}, "MUTE-log"),
    "the log branch not on route_of": ({"ark_relay/notify.py": NOTIFY.replace(
        'route = route_of(title, alert=alert, daily=daily)', 'route = "log" if body == "" else route_of(title)')},
        "MUTE-log"),
    "a failure title on a log-only prefix": ({"ark_relay/notify.py": NOTIFY + 'COLLECT_FAILED = "✅ 自动采集：3 条没走通"\n'},
                                             "MUTE-log"),
    "the log line outside the log branch": ({"ark_relay/notify.py": NOTIFY.replace(
        '        if route == "log":\n            log.info("不推送（日报或手机页已有）：%s", title)\n            return []\n',
        '        log.info("不推送（日报或手机页已有）：%s", title)\n')}, "MUTE-log"),
    # R8: the game's own counter at 0, read off the screen in the same function, and logged
    "skipped on a config value": (BOSS.replace("now = _left(text)", 'now = self.config.get("Weekly Left", 3)'),
                                  "OFF-skip"),
    "skipped on a retry counter": (BOSS.replace("now = _left(text)", "now = 3\n        for b in left or []:\n"
                                                "            now -= 1"), "OFF-skip"),
    "skipped on a value handed in": (BOSS.replace("def click_level(self):", "def click_level(self, given):")
                                     .replace("now = _left(text)", "now = given"), "OFF-skip"),
    "skipped on the screen and the task's own state": (BOSS.replace("now = _left(text)",
                                                                    "now = _left(text) - self._tries"), "OFF-skip"),
    "skipped with no condition": (BOSS.replace("        if now == 0:\n            self.log_info",
                                               "        self.log_info").replace(
        "            raise TaskDisabledException()", "        raise TaskDisabledException()"), "OFF-skip"),
    "skipped on a read other than 0": (BOSS.replace("if now == 0:", "if now == 1:"), "OFF-skip"),
    "skipped on a read that is not 0": (BOSS.replace("if now == 0:", "if now != 0:"), "OFF-skip"),
    "skipped without a word in the branch": (BOSS.replace('            self.log_info("本周次数已领满（0/3），跳过")\n', ""),
                                             "OFF-skip"),
    "skipped without the reading in the log": (BOSS.replace('            self.log_info(f"剩余次数原文: {left}")\n',
                                                            "            pass\n"), "OFF-skip"),
    # R8b: a subclass raised is the skip unless the same file makes it a failure
    "alias of the stop raised": ('from ok import TaskDisabledException as _TDE\ndef stop(t):\n    raise _TDE()\n',
                                 "OFF-skip"),
    "subclass never caught": ('class Stop(TaskDisabledException):\n    pass\ndef end(t):\n    raise Stop()\n',
                              "OFF-skip"),
    "type() subclass never caught": (STOP[:STOP.index("def run(self):")], "OFF-skip"),
    "subclass caught and swallowed": (STOP.replace('    why = getattr(self, "_failed", None)\n'
                                                   '    if why:\n        raise Stopped(why)\n', ""), "OFF-skip"),
    "subclass turned into a failure on another flag": (STOP.replace('getattr(self, "_failed", None)',
                                                                    'getattr(self, "_other", None)'), "OFF-skip"),
    "subclass always re-raised by its handler": (STOP.replace("    except _Stop:\n        got = None\n",
                                                              "    except _Stop:\n        raise\n"), "OFF-skip"),
    "subclass handed on as another skip": (STOP.replace("    except _Stop:\n        got = None\n",
                                                        "    except _Stop:\n        raise _Skip()\n").replace(
        "class Stopped(Exception):", "class _Skip(TaskDisabledException):\n    pass\nclass Stopped(Exception):"),
                                           "OFF-skip"),
    # OFF-flag: a marker file that switches a step off
    "a marker file skips the step": ('import os\nFLAG = r"C:\\ProgramData\\x\\no-farm.flag"\nclass T:\n'
                                     '    def farm(self):\n        if os.path.exists(FLAG):\n'
                                     '            self.log_info("刷体力已禁用")\n            return None\n'
                                     '        return self.go()\n', "OFF-flag"),
    "a Path marker in a loop": ('from pathlib import Path\nSKIP = Path("C:/ProgramData") / "skip-weekly.flag"\n'
                                'def run(tasks):\n    for t in tasks:\n        if SKIP.is_file():\n'
                                '            continue\n        t.go()\n', "OFF-flag"),
    "a marker or-ed in": ('import os\ndef farm(self, weekly):\n    flag = "C:/x/no-claim"\n'
                          '    if not weekly or os.path.isfile(flag):\n        return\n    self.go()\n', "OFF-flag"),
    "a marker and-ed with a reading of something else": (
        'import os\nF = "C:/x/no-farm.flag"\ndef farm(self):\n    if os.path.exists(F) and self.read_text():\n'
        '        return\n    self.go()\n', "OFF-flag"),
}

# For samples with more than one place, the place that must be the hit.
BAD_AT = {
    **{k: "Notifier.send" for k in ("a second way to the log route", "the log route from a variable",
                                    "the log branch not on route_of", "a failure title on a log-only prefix",
                                    "the log line outside the log branch")},
    **{k: "end_failed" for k in ("type() subclass never caught", "subclass caught and swallowed",
                                 "subclass turned into a failure on another flag",
                                 "subclass always re-raised by its handler", "subclass handed on as another skip")},
    **{k: "T.click_level" for k in BAD if k.startswith("skipped ")},
    "the debug verdict's early exit": "maybe",
    "the red button's run kept from the group": "_handle",
}

GOOD = {
    "turning on": 'def f(t):\n    t["enabled"] = True\n',
    "reading a switch": 'def f(t):\n    return t.get("enabled", False) is False\n',
    "comparing with Close": 'def f(v):\n    return "剿灭关闭" if v == "Close" else ""\n',
    "returned description": 'def read(on):\n    if not on:\n        return {"enabled": False, "label": "全关"}\n',
    "setter with a parameter": 'def set_task(t, value):\n    t["enabled"] = bool(value)\n',
    "user's command carried": ('from . import queues\ndef run(cmds, d):\n    for cmd in cmds:\n'
                               '        queues.apply(d, cmd.get("name"), cmd.get("enabled"))\n'),
    "user's command through a setter": ('def set_task(t, value):\n    t["enabled"] = bool(value)\n'
                                        'def apply(cmd, t):\n    set_task(t, cmd["value"])\n'),
    "user's choice computed from parameters": ('TASKS = ("A", "B")\ndef toggle(have, want_task):\n'
                                               '    for name in TASKS:\n        want_on = name == want_task\n'
                                               '        have[name]["enabled"] = want_on\n'),
    "restore saved flags": ('KEYS = ("enabled",)\ndef restore(t, saved):\n    for k in KEYS:\n'
                            '        t[k] = saved[k]\n'),
    "task moved, not removed": 'def f(tasks, s, i, p):\n    tasks.remove(s)\n    tasks.insert(i, s)\n    p.write_text("")\n',
    "reader filtering a parsed log": 'def parse(tasks, skipped):\n    tasks = [t for t in tasks if t not in skipped]\n'
                                     '    return tasks\n',
    "plain early exit before an alarm": ('def push(eng, rows):\n    if not rows:\n        return\n'
                                         '    eng.notifier.send("t", "b", alert=True)\n'),
    "waiting for retries is not muting": LOG + 'def f(r):\n    log.info("%s 失败，暂不推送，等重试结果", r)\n',
    "route of a non-failure": ('_LOG_ONLY_PREFIXES = ("🔄 中继已更新",)\n'
                               'def route_of(t):\n    if t.startswith(_LOG_ONLY_PREFIXES):\n        return "log"\n'),
    "information that is not a failure": 'def f(eng, b):\n    eng.notifier.send("🆕 游戏更新", b)\n',
    "a cap that is not about pushes": 'def f(got, cap):\n    return got >= cap\n',
    "off as a command key": 'def f(cmd):\n    return bool(cmd.get("off"))\n',
    "old patch text kept only to be found": ('_X_V1 = """    self.log_info(\'x\')\n    raise TaskDisabledException()"""\n'
                                             'OLD = [(_X_V1, "")]\n'),
    "skipping items in a loop with no alarm in it": ('PLUGINS = ("a",)\ndef end(self, procs):\n    for n in procs:\n'
                                                     '        if n not in PLUGINS:\n            continue\n        kill(n)\n'
                                                     '    self.notifier.send("t", "b", alert=True)\n'),
    "checking a send's result": ('def f(eng, b):\n    if eng.notifier.send("🆕 更新", b):\n        return\n'
                                 '    eng.notifier.send("t", b, alert=True)\n'),
    "a banner on the group is not an alarm": ('def f(eng, fresh):\n    if not fresh:\n        return\n'
                                              '    eng.notifier.send_group("📣 明天开卡池", "b")\n'),
    "Close passed to a text function": ('def body(what, detail, back):\n    return f"{what}{detail}{back}"\n'
                                        'def samples():\n    return [body("Annihilation", "", "Close")]\n'),
    "a missing file is nothing to read": ('import os\nF = "C:/x/state.json"\ndef read(self):\n'
                                          '    if not os.path.exists(F):\n        return None\n    return self.load(F)\n'),
    "the file already says it": ('from pathlib import Path\nPOINTER = Path(r"C:\\ProgramData\\p.txt")\n'
                                 'def point(d):\n    if POINTER.is_file() and POINTER.read_text().strip() == str(d):\n'
                                 '        return ""\n    POINTER.write_text(str(d))\n    return ""\n'),
    "a record read only to switch tasks back on": dedent('''\
        def enable(cfg, names):
            for t in cfg["tasks"]:
                if t["n"] in names:
                    t["enabled"] = True
            cfg.write_text("x")
        def reenable(store, cfg):
            rec = store.get("updates", "x_disabled")
            enable(cfg, set(rec.get("disabled") or []))
        '''),
}

# Hits that are there and must pass by the narrow rule named (R3 - R5).
ALLOWED = {
    "one record is one fault": (dedent('''\
        def send(eng, day, rec, t, b):
            key = f"未解决|{rec.run_id}"
            # one fault, one push: one record handled twice is one fault
            if eng._already_alerted(day, key):
                return True
            eng.notifier.send(t, b, alert=True)
        '''), "R3"),
    "one process is one fault": (dedent('''\
        class W:
            def tick(self, pid):
                if pid in self._done:  # one fault, one push: one hung process, by its PID
                    return
                self._done.add(pid)
                self.notifier.send("❌ 卡住", "b", alert=True)
        '''), "R3"),
    "one missed slot is one fault": (dedent('''\
        def check(eng, day, queues):
            for q in queues:
                for hhmm in q["times"]:
                    key = f"{day}/{q['name']}/{hhmm}"
                    # one fault, one push: one queue that did not run at its time
                    if key in eng._missed_alerted:
                        continue
                    eng.notifier.send("t", "b", alert=True)
                    eng._missed_alerted.add(key)
        '''), "R3"),
    "the relay's own power-off, in service.py": ({"ark_relay/errwatch.py": ERRWATCH, "service.py": LOG + dedent('''\
        class K:
            def exited(self):
                from ark_relay import errwatch
                if errwatch.relay_shutdown_issued():
                    log.info("按关机处理，不算故障")
                    return
                log.warning("意外退出")
            def check(self):
                from ark_relay import errwatch
                if self.handle is None and errwatch.relay_shutdown_issued():
                    return
                self.notifier.send("❌ 起不来", "b", alert=True)
        ''')}, "R4"),
    "the relay's own power-off, waited for in service.py": ({"ark_relay/errwatch.py": ERRWATCH,
                                                            "service.py": LOG + dedent('''\
        import time
        def _going_down_soon(seconds=15.0):
            from ark_relay import errwatch
            deadline = time.monotonic() + seconds
            while not errwatch.relay_shutdown_issued():
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                time.sleep(min(0.5, left))
            return True
        class K:
            def exited(self):
                if _going_down_soon():
                    log.info("按关机处理，不算故障")
                    return
                log.warning("意外退出")
        ''')}, "R4"),
    "the log route of route_of's collections": ({"ark_relay/notify.py": NOTIFY}, "R7"),
    "the log route, three tests or-ed": ({"ark_relay/notify.py": NOTIFY.replace(
        "if title.startswith(_LOG_ONLY_PREFIXES):",
        "if title.startswith(_LOG_ONLY_PREFIXES) or any(s in title for s in _LOG_ONLY_CONTAINS) "
        "or title in _LOG_ONLY_TITLES:").replace(
        '_LOG_ONLY_PREFIXES = ("🔄 中继已更新", "✅ ")',
        '_LOG_ONLY_PREFIXES = ("🔄 中继已更新", "✅ ")\n_LOG_ONLY_CONTAINS = ("已送出机器",)\n'
        '_LOG_ONLY_TITLES = ("📱 配置已修改",)')}, "R7"),
    "the weekly counter read 0 off the screen": (BOSS, "R8"),
    "a subclass recorded and raised as a failure": (STOP, "R8b"),
    "a subclass turned into a failure in its handler": (
        'class Stop(TaskDisabledException):\n    pass\ndef end(t):\n    raise Stop()\n'
        'def run(self):\n    try:\n        self.inner()\n    except Stop as exc:\n'
        '        raise RuntimeError("failed") from exc\n', "R8b"),
    "a temporary setting put back in finally": (AUTO_START + dedent('''\
        def run(p):
            was = _auto(p, False)
            if was is None:
                return
            try:
                launch(p)
            finally:
                _auto(p, was)
        '''), "R5"),
    "a temporary setting put back only if it was on": (AUTO_START + dedent('''\
        def run(p):
            was = _auto(p, False)
            try:
                launch(p)
            finally:
                close(p)
                if was:
                    _auto(p, True)
        '''), "R5"),
}

# Rule 2 on a sample shaped like modes.py: his skip-today command's reader controls
# the write, so it is not a hit that needs a line.
COMMAND_SAMPLE = dict(COMMAND_SAMPLE_BASE)


def _sample_scan(src) -> Scan:
    return Scan(src if isinstance(src, dict) else {"ark_relay/_sample.py": src})


def self_check() -> list[str]:
    fails = []
    for label, (src, rule) in BAD.items():
        need, _, _ = findings(_sample_scan(src))
        if not any(h.rule == rule for h in need):
            fails.append(f"known-bad sample not flagged as {rule}: {label} (got {need})")
    # the hit must be the place the sample is about, not some other line of it
    for label, where in BAD_AT.items():
        src, rule = BAD[label]
        need, _, _ = findings(_sample_scan(src))
        if not any(h.rule == rule and h.key.endswith(":" + where) for h in need):
            fails.append(f"known-bad sample not flagged at {where}: {label} (got {need})")
    for label, src in GOOD.items():
        hits = _sample_scan(src).hits
        if hits:
            fails.append(f"known-good sample flagged: {label}: {hits}")
    for label, (src, rule) in ALLOWED.items():
        scan = _sample_scan(src)
        need, _, allowed = findings(scan)
        if need or not allowed or any(not why.startswith(rule + " ") for _, why in allowed) \
                or (rule == "R4" and scan.wrapper_used and scan.wrapper_problems()):
            fails.append(f"sample must pass by {rule} alone: {label} (need {need}, passed {allowed})")
    scan = Scan(COMMAND_SAMPLE)
    need, applied, _ = findings(scan)
    if need or [a for _, a in applied] != ["skip_today"] or command_records_hold(scan):
        fails.append(f"rule 2 sample: need {need}, applied {applied}, records {command_records_hold(scan)}")
    _, bad = read_list("ark_relay/x.py:f | does a thing | he said so | 2026-10-06\n")
    if len(bad) != 2:
        fails.append(f"a line with no quote and no time must be refused twice, got {bad}")
    _, bad = read_list("ark_relay/x.py:f | does a thing | 「我说的」 | 2026-09-03 (time not recorded)\n")
    if len(bad) != 1:
        fails.append(f"a line with a date but no time must be refused, got {bad}")
    listed, bad = read_list("ark_relay/x.py:f | does | 「我说的」 | 2026-10-06 02:53\n"
                            "ark_relay/x.py:_T[⚠️ 采集 没走通] | does | 「我说的」 | 2026-10-06 02:53\n"
                            "ark_relay/y.py:g | does | 「我说的？就是这样，对吧」 | 2026-09-03 02:34 (Tokyo)\n")
    if bad or sorted(listed) != ["ark_relay/x.py:_T[⚠️ 采集 没走通]", "ark_relay/x.py:f", "ark_relay/y.py:g"]:
        fails.append(f"well-formed lines (a key with spaces, a time zone note) must be accepted, "
                     f"got {sorted(listed)} {bad}")
    if not verdict([], {"ark_relay/x.py:f": "x"}):
        fails.append("a listed key with no hit must fail")
    return fails


def main(argv: list[str]) -> int:
    fails = ["self-check: " + f for f in self_check()]
    print(f"  self-check: {len(BAD)} known-bad samples flagged, {len(GOOD)} known-good samples clean, "
          f"{len(ALLOWED)} samples pass by R3-R8b alone, rule 2 sample ok" if not fails else "  self-check FAILED")
    scan = Scan(relay_sources())
    need, applied, allowed = findings(scan)
    fails += command_records_hold(scan)
    if scan.log_route_used:
        fails += scan.log_route_problems()
    if scan.wrapper_used:
        fails += scan.wrapper_problems()
    if "--list" in argv:
        for h in need:
            print(f"  {h!r}")
    for h, action in applied:
        print(f"  · {h.rel}:{h.line} applies the user's own {action} command (rule 2) - {h.text}")
    for h, why in allowed:
        print(f"  · {h.rel}:{h.line} {h.key} [{h.rule}] passes {why}")
    listed, bad = read_list(LIST_FILE.read_text(encoding="utf-8") if LIST_FILE.is_file() else "")
    if not LIST_FILE.is_file():
        bad.append("relay/USER-SWITCHES.txt is missing")
    problems = bad + verdict(need, listed)
    if "--list" not in argv:
        for p in problems:
            print("  ✗ " + p)
    fails += problems
    print(f"  {len(need)} places switch something off or keep a failure from the group; "
          f"{sum(1 for h in need if h.key in listed)} of them on the user's list ({len(listed)} lines)")
    for f in fails:
        if f.startswith(("self-check", "rule 2", "R4", "R7")):
            print("  ✗ " + f)
    print("\n" + (f"FAILED: {len(fails)} problem(s)" if fails else "all checks passed"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
