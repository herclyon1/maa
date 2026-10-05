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
                constant) passed to a call, assigned, put in a dict or returned
                (annihilation: `_write_setting(dir, CLOSED)`); comparisons and
                `.get()` are reads and do not count.
  OFF-remove    in a function that writes (atomic_write_text, write_text, dump,
                _write*, _save*, _mas, put/post): `.remove()` / `.discard()` /
                `.pop()` / `del` on a list named or keyed "task" / "caseNames" (a
                move - removed and put back in the same function - is not a
                removal); such a list assigned from a filtering comprehension or
                rebuilt by conditional appends; and anywhere, a call to an API
                path ending in delete / remove / disable.
  OFF-keep      code that keeps a task off: it reads a state record whose key
                says "disabled", or logs that something stays off (继续关着,
                保持关闭, 不开回, "keep it off", ...).
  OFF-skip      `raise TaskDisabledException` - OK-WW's own "skipped, not failed"
                stop - in OK-WW task code the relay ships (okww_files/), or in a
                patch's `new=` text (okww_patches/; the old versions kept only to
                be found and removed are not code that runs), and a `new=` text
                that logs 已禁用.
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
                is_fault, going_down / shutting_down, levelno, or membership in
                a named module constant (`v.code not in _STUCK_CODES`).

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
  2. A command that is stored and applied later is his command where it is
     applied only when the hit's nearest controlling `if` / `for` (or, for an
     early exit, its own condition) is the reader of that command's record,
     called directly or through a local that holds only its result. The readers
     are COMMAND_RECORDS below - two of them - and the test checks each against
     commands.py: the action must be in the whitelist (REVERSIBLE | MUTATING)
     and dispatched by apply_command, and the reader must exist.

Known limits, said here rather than hidden: a value returned by an arbitrary
call (`enabled = should_run(x)`) or read off an object (`rec.ok`) is treated as
carried, not as a decision; choosing `log.warning` over `log.error` to stay out
of errwatch's group alarm is not detected; a guard reached through a verdict
code (`if v.code == "debug"`) is not traced back to the command behind it, so
it shows up as a hit; code that never names its intent (no switch key, no task
list, no wording, no alarm nearby) is invisible.

Run it with `--list` to print every hit, listed or not.

Self-checks at the bottom feed the detectors small known-bad samples (each must
be flagged under the expected rule) and known-good ones (none may be), so a
detector that silently stops matching fails this test.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
LIST_FILE = RELAY / "USER-SWITCHES.txt"

# The user's stored commands, and the function that reads each back (rule 2).
COMMAND_RECORDS = {
    "debug_mode": "ark_relay/modes.py:debug_active",
    "skip_today": "ark_relay/modes.py:_day_queues",
}

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
                      r"shutting_down|levelno", re.I)
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
            p = m.parent.get(n)
            if isinstance(p, ast.keyword):
                p = m.parent.get(p)
            written = ((isinstance(p, ast.Call) and n is not p.func and _call_name(p) != "get" and not _is_log(p))
                       or (isinstance(p, ast.Assign) and p.value is n and fn is not None)
                       or (isinstance(p, ast.Dict) and n in p.values) or isinstance(p, ast.Return))
            if written:
                self.add(m, n, "OFF-close", f"writes {v!r}", fn=fn)

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
                    for a in n.args):
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
        for n in nodes:
            if isinstance(n, ast.Raise) and n.exc is not None and SKIP_SIGNAL in _words(n.exc):
                self.add(m, n, "OFF-skip", f"raise {SKIP_SIGNAL}: OK-WW ends the task as skipped, not failed", fn=fn)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and (hit := PATCH_OFF.search(n.value)) \
                    and id(n) not in m.docstrings and self._injected(m, n):
                self.add(m, n, "OFF-skip", f"code patched into OK-WW: {hit.group(0)}", fn=fn)

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
        """The whitelisted action a hit applies (rule 2), or ''."""
        m, fn, node = self.mods[hit.rel], hit.fn, hit.node
        readers = {v: k for k, v in COMMAND_RECORDS.items()}
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
        for c in self._reader_calls(m, fn, control, frozenset()):
            target = self.resolve(m, c, fn)
            if target and f"{target[0]}:{target[1]}" in readers:
                return readers[f"{target[0]}:{target[1]}"]
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


def findings(scan: Scan) -> tuple[list[Hit], list[tuple[Hit, str]]]:
    """(hits that need a line, hits that apply a stored user command)."""
    need, commands = [], []
    for h in sorted(scan.hits, key=lambda h: (h.rel, h.line, h.rule)):
        action = scan.user_command(h)
        (commands.append((h, action)) if action else need.append(h))
    return need, commands


# ----------------------------------------------------------------- self-checks

LOG = "import logging\nlog = logging.getLogger()\n"
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
    "Close constant": ('CLOSED = "Close"\ndef _w(d, v):\n    pass\n'
                       'class G:\n    def enforce(self):\n        _w(self.d, CLOSED)\n', "OFF-close"),
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
}

# Rule 2 on a sample shaped like modes.py / missed.py: the stored command's reader
# controls the write and the guard, so neither is a hit that needs a line.
COMMAND_SAMPLE = {
    "ark_relay/commands.py": ('REVERSIBLE = {"debug_mode", "skip_today"}\nMUTATING = set()\n'
                              'def apply_command(cmd):\n    action = cmd["action"]\n'
                              '    if action == "debug_mode":\n        return 1\n'
                              '    if action == "skip_today":\n        return 2\n'),
    "ark_relay/modes.py": ('from . import queues\ndef debug_active(d):\n    return False\n'
                           'def _day_queues(store, day):\n    return []\n'
                           'def _maybe_engage(store, d, day):\n    wanted = _day_queues(store, day)\n'
                           '    for queue in wanted:\n        queues.apply(d, queue, enabled=False)\n'),
    "ark_relay/missed.py": ('from . import modes\ndef check(eng):\n    if modes.debug_active(eng.d):\n'
                            '        return\n    eng.notifier.send("t", "b", alert=True)\n'),
    "ark_relay/queues.py": 'def apply(d, name, enabled=None):\n    pass\n',
}


def self_check() -> list[str]:
    fails = []
    for label, (src, rule) in BAD.items():
        scan = Scan({"ark_relay/_sample.py": src})
        need, _ = findings(scan)
        if not any(h.rule == rule for h in need):
            fails.append(f"known-bad sample not flagged as {rule}: {label} (got {need})")
    for label, src in GOOD.items():
        hits = Scan({"ark_relay/_sample.py": src}).hits
        if hits:
            fails.append(f"known-good sample flagged: {label}: {hits}")
    scan = Scan(COMMAND_SAMPLE)
    need, applied = findings(scan)
    if need or sorted(a for _, a in applied) != ["debug_mode", "skip_today"] or command_records_hold(scan):
        fails.append(f"rule 2 sample: need {need}, applied {applied}, records {command_records_hold(scan)}")
    _, bad = read_list("ark_relay/x.py:f | does a thing | he said so | 2026-10-06\n")
    if len(bad) != 2:
        fails.append(f"a line with no quote and no time must be refused twice, got {bad}")
    listed, bad = read_list("ark_relay/x.py:f | does | 「我说的」 | 2026-10-06 02:53\n"
                            "ark_relay/x.py:_T[⚠️ 采集 没走通] | does | 「我说的」 | 2026-10-06 02:53\n")
    if bad or sorted(listed) != ["ark_relay/x.py:_T[⚠️ 采集 没走通]", "ark_relay/x.py:f"]:
        fails.append(f"well-formed lines (one key with spaces) must be accepted, got {sorted(listed)} {bad}")
    if not verdict([], {"ark_relay/x.py:f": "x"}):
        fails.append("a listed key with no hit must fail")
    return fails


def main(argv: list[str]) -> int:
    fails = ["self-check: " + f for f in self_check()]
    print(f"  self-check: {len(BAD)} known-bad samples flagged, {len(GOOD)} known-good samples clean, rule 2 sample ok"
          if not fails else "  self-check FAILED")
    scan = Scan(relay_sources())
    need, applied = findings(scan)
    fails += command_records_hold(scan)
    if "--list" in argv:
        for h in need:
            print(f"  {h!r}")
    for h, action in applied:
        print(f"  · {h.rel}:{h.line} applies the user's own {action} command (rule 2) - {h.text}")
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
        if f.startswith(("self-check", "rule 2")):
            print("  ✗ " + f)
    print("\n" + (f"FAILED: {len(fails)} problem(s)" if fails else "all checks passed"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
