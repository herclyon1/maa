"""The overlay's contract with the OK-WW the game PC runs, checked on upstream's own source (gamesim P0, T1).

ark_overrides.tasks.py rebinds 26 methods on OK-WW's classes. Until now its tests ran it
against stand-in classes written from memory, and okww-pristine-methods.json kept the
pre-v3.7.4 `run()` green for 7 days (10-06..10-13) while the machine ran v3.7.4. This
test reads the real source of the installed tag instead - the copy
relay/tests/gamesim/tools/fetch_upstream.py fetched from GitHub - and checks, for every
rebind the overlay makes:

  1. the target exists: upstream's class (or a base, in method resolution order) defines it;
  2. ours takes every call upstream's signature accepts (inspect.Signature.bind, both ways);
  3. okww_overlay.drift() on that tree is empty, and every pinned hash is found and equal;
  4. the upstream bodies the overlay relies on without replacing them still hash as reviewed.

Each failure here broke on the machine first:
  - b24c48fc: v3.7.4 FarmEchoTask.run(self, retries=3) calls self.run(retries - 1)
    (FarmEchoTask.py:108, :123); ours was run(self), so every retry was a TypeError.
  - f6b5f432: v3.7.3 moved find_nest's OCR box (0.13 -> 0.25); the copy pinned to the old
    body was skipped 10-04 and 10-05 and upstream picked an unreachable 0/48 nest.
  - d8182f01: that nest health item sat red on the machine 10-04..10-10 (ledger 330).
This moves all of them to deploy time.

    relay-python tests/test_gl_okww_contract.py            # the installed version
    relay-python tests/test_gl_okww_contract.py v3.7.3     # another fetched copy
"""
import ast
import copy as _copy
import hashlib
import inspect
import itertools
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "gamesim" / "tools"))
import fetch_upstream as fu
from _tmp import tmpdir
from ark_relay.features.okww_patch import okww_overlay

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


# The OK-WW on the game PC: 「ok-script init v3.7.4」 at every start since 10-06, last at
# 2026-10-13 11:07:05 (OK-WW app log app.2026-10-13 line 517, pulled from the machine
# to scratchpad/gamedata/okww/ark/okww/logs). 10-04 and 10-05 it was v3.7.3 (app.2026-10-04).
INSTALLED = "v3.7.4"
VERSION = sys.argv[1] if len(sys.argv) > 1 else INSTALLED
# What each tag pointed at when fetched (git ls-remote ...ok-wuthering-waves refs/tags/<tag>^{},
# 2026-10-13); v3.7.4 = 2243d465 is also the design's W.
COMMITS = {
    "v3.7.4": "2243d465d58c74f52765b658174bff76165656ee",
    "v3.7.3": "f5f38c8d9e2b7f7e91edad77bd5fab14df3f162d",
    "v3.6.5": "f4b3799c5e0ab8bc3d7191f43a842b84197081ff",
}


# ── upstream source, read the way Python would ──────────────────────────────────
class Tree:
    """Every top-level class and function in one fetched copy."""

    def __init__(self, tag):
        self.copy = fu.copy_dir("okww", tag)
        self.files = {p: b.decode("utf-8") for p, b in fu.read_files(self.copy).items()}
        self.classes = {}       # name -> (path, lines, ClassDef)
        self.functions = {}     # "path:name" -> (lines, FunctionDef)
        for path, text in self.files.items():
            if not path.endswith(".py"):
                continue
            tree = ast.parse(text)
            lines = text.splitlines(keepends=True)
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    self.classes.setdefault(node.name, (path, lines, node))
                elif isinstance(node, ast.FunctionDef):
                    self.functions[f"{path}:{node.name}"] = (lines, node)

    def bases(self, cls):
        return [b.id for b in self.classes[cls][2].bases if isinstance(b, ast.Name)]

    def mro(self, cls):
        """C3 linearisation over the classes in this copy; a base from ok-script ends a chain."""
        if cls not in self.classes:
            return [cls]
        seqs = [self.mro(b) for b in self.bases(cls)] + [self.bases(cls)]
        out = [cls]
        while any(seqs):
            for seq in seqs:
                head = seq[0] if seq else None
                if head and not any(head in s[1:] for s in seqs):
                    break
            else:
                raise TypeError(f"no consistent MRO for {cls}")
            out.append(head)
            seqs = [s[1:] if s and s[0] == head else s for s in seqs]
        return out

    def method(self, cls, name):
        """(defining class, lines, FunctionDef) that cls.name resolves to; None when not in this copy."""
        for c in self.mro(cls):
            if c not in self.classes:
                continue
            _path, lines, node = self.classes[c]
            for fn in node.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                    return c, lines, fn
        return None


def body_sha(lines, fn):
    """inspect.getsource's hash (sha1, 12 hex) of a def, decorators included."""
    start = min([d.lineno for d in fn.decorator_list] + [fn.lineno]) - 1
    return hashlib.sha1("".join(inspect.getblock(lines[start:])).encode("utf-8")).hexdigest()[:12]


def signature(fn):
    """inspect.Signature of a def read from source: same parameters, no annotations."""
    args = _copy.deepcopy(fn.args)
    for a in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
        if a is not None:
            a.annotation = None
    # A default is kept when it is a literal (for the message) and stands in as "..." otherwise:
    # only whether a parameter has one matters to the call shapes.
    args.defaults = [d if isinstance(d, ast.Constant) else ast.Constant(...) for d in args.defaults]
    args.kw_defaults = [d if d is None or isinstance(d, ast.Constant) else ast.Constant(...)
                        for d in args.kw_defaults]
    stub = ast.Module(body=[ast.FunctionDef(name="f", args=args, body=[ast.Pass()], decorator_list=[],
                                            returns=None, type_params=[])], type_ignores=[])
    ns = {}
    exec(compile(ast.fix_missing_locations(stub), "<signature>", "exec"), ns)
    return inspect.signature(ns["f"])


def call_shapes(sig):
    """Every way of calling a bound method that sig accepts: (n positional, keyword names).

    Optional parameters are left out, passed by position or passed by name in every
    combination; *args gets one extra positional and **kwargs one extra keyword.
    """
    P = inspect.Parameter
    ps = list(sig.parameters.values())[1:]          # self is bound
    pos = [p for p in ps if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD)]
    kwonly = [p for p in ps if p.kind == P.KEYWORD_ONLY]
    out = []
    for k in range(len(pos) + 1):
        rest = [p for p in pos[k:] if p.kind == P.POSITIONAL_OR_KEYWORD] + kwonly
        need = tuple(p.name for p in rest if p.default is P.empty)
        opt = [p.name for p in rest if p.default is not P.empty]
        for r in range(len(opt) + 1):
            out += [(k, need + sub) for sub in itertools.combinations(opt, r)]
    if any(p.kind == P.VAR_POSITIONAL for p in ps):
        out.append((len(pos) + 1, ()))
    if any(p.kind == P.VAR_KEYWORD for p in ps):
        out.append((len(pos), ("ark_probe_extra",)))
    return [s for s in out if _binds(sig, s)]


def _binds(sig, shape):
    k, names = shape
    try:
        sig.bind(object(), *([object()] * k), **dict.fromkeys(names, object()))
    except TypeError:
        return False
    return True


def sig_gaps(up, ours):
    """Calls upstream accepts that ours refuses, as readable shapes ([] = ours is a superset)."""
    return [f"{k} positional + {list(names)}" for k, names in call_shapes(up) if not _binds(ours, (k, names))]


# ── the overlay, read as source ─────────────────────────────────────────────────
def rebinds(text):
    """[(class, method, our def)] for every rebind in the overrides file.

    `@override(Cls, "name", ...)` on a def, and the defs a helper hands to
    `override(cls, name)(fn)` with the class and name it was called with
    (`_farm_hook(TacetTask, "farm_tacet")`).
    """
    return _read_rebinds(text)[0]


def stray_overrides(text):
    """Line numbers of override(...) calls neither form above accounts for ([] = none escape)."""
    return _read_rebinds(text)[1]


def _read_rebinds(text):
    tree = ast.parse(text)
    out, helpers, seen = [], {}, set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for d in node.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "override"
                    and isinstance(d.args[0], ast.Name) and isinstance(d.args[1], ast.Constant)):
                out.append((d.args[0].id, d.args[1].value, node))
                seen.add(id(d))
        params = [a.arg for a in node.args.args]
        for call in ast.walk(node):
            # override(cls, name)(fn) inside a helper whose parameters are cls and name
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Call)
                    and isinstance(call.func.func, ast.Name) and call.func.func.id == "override"
                    and all(isinstance(a, ast.Name) and a.id in params for a in call.func.args[:2])
                    and call.args and isinstance(call.args[0], ast.Name)):
                inner = next(f for f in ast.walk(node)
                             if isinstance(f, ast.FunctionDef) and f.name == call.args[0].id)
                helpers[node.name] = (params.index(call.func.args[0].id),
                                      params.index(call.func.args[1].id), inner)
                seen.add(id(call.func))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in helpers:
            ci, ni, inner = helpers[node.func.id]
            out.append((node.args[ci].id, node.args[ni].value, inner))
    stray = [c.lineno for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
             and c.func.id == "override" and id(c) not in seen]
    return out, stray


def contract(tree, text):
    """{rebind label: [problems]} for the overlay text against one upstream copy."""
    out = {}
    for cls, name, fn in rebinds(text):
        label, why = f"{cls}.{name}", []
        if cls not in tree.classes:
            why.append(f"class {cls} is not in the OK-WW source (nothing to check it against)")
        elif (found := tree.method(cls, name)) is None:
            why.append(f"upstream {cls} has no {name} (renamed or removed)")
        elif gaps := sig_gaps(signature(found[2]), signature(fn)):
            why.append(f"upstream {found[0]}.{name}{signature(found[2])} is called in ways "
                       f"ours {fn.name}{signature(fn)} refuses: {gaps}")
        out.setdefault(label, []).extend(why)
    return out


def materialized(tree):
    """An OK-WW directory as okww_overlay.drift() reads it: <dir>/data/apps/ok-ww/working/src/..."""
    root = tmpdir()
    # The machine runs D:/ark/okww/data/apps/ok-ww/working/main.py (app.2026-10-13 line 517).
    fu.materialize(tree.copy, root / "data" / "apps" / "ok-ww" / "working")
    return root


def pin_problems(tree):
    """Pinned copies whose upstream body is missing or hashes differently, by our own hash."""
    out = []
    for cls, name, want, _adapt in okww_overlay.pins():
        found = tree.method(cls, name) if cls in tree.classes else None
        got = body_sha(found[1], found[2]) if found else ""
        if got != want:
            out.append(f"{cls}.{name}: pinned {want}, upstream {got or 'not found'}")
    return out


# The upstream bodies the overlay leans on without replacing them, as reviewed per version.
# A new installed version needs its own row, written after reading each body against the
# comment that relies on it (gamesim design, P0). Values: body_sha of the fetched copy.
RELIED = {
    "v3.7.4": [
        # AO comment above _TEAM_CHALLENGE_SHA: a realm death goes FarmEchoTask.revive_action
        # (:92-106) -> BaseCombatTask.revive_action (:227-240), which cancels the popup;
        # do_run teleports back. Ours stopped spending a revive item on that (2026-10-13).
        ("FarmEchoTask.revive_action", "cbdf4bb7e32d"),
        ("BaseCombatTask.revive_action", "5da4d78b71ef"),
        # FarmEchoTask.py:374-378: one click, then wait_click_skip_dialog_confirm(time_out=1)
        # auto-confirms 「无法获取奖励」 and ticks 「本次登录不再提示」 (ok-script.2026-10-12.log
        # 1864-1870, 2735-2740); a0db4b38 answers it ourselves.
        ("FarmEchoTask.click_solo_challenge", "c0bd68198fbf"),
        # DailyTask.py:98-99 swaps NightmareNestTask.ensure_main for a do-nothing lambda so the
        # nest run keeps the F2 book open; get_nest_to_go's override relies on it.
        ("DailyTask.run", "a447990af646"),
        # Tacet groups: TacetTask.py:18 structure = [4, 5, 5, 7] (WuWa 3.7 order, 36e42748
        # dropped our regrouping for it), used by teleport_to_tacet (:109-113).
        ("TacetTask.__init__", "6936f96f63b2"),
        ("TacetTask.teleport_to_tacet", "a82b61f4ccb5"),
        # Launch argument: config.py:203 'launch_arguments': get_game_launch_arguments ->
        # src/game_launcher.py:4-7 returns -krqlv=<Game Package> (788c031b dropped our hook).
        ("src/game_launcher.py:get_game_launch_arguments", "b95c95abe903"),
        # find_nest is replaced and pinned in the overlay (_NEST_FIND_SHA); its OCR box top,
        # NightmareNestTask.py:229 `self.ocr(0.35, 0.25, 1, 0.96, ...)`, is checked below.
        ("NightmareNestTask.find_nest", "12d040afa102"),
    ],
}
# config.py:203 at v3.7.4, the line that hands the launch argument to ok-script.
LAUNCH_LINE = "'launch_arguments': get_game_launch_arguments,"
# NightmareNestTask.py:229 at v3.7.3 and v3.7.4; v3.6.5 had 0.13 (NightmareNestTask.py:212).
NEST_TOP = {"v3.7.4": "0.25", "v3.7.3": "0.25", "v3.6.5": "0.13"}


def relied_sha(tree, what):
    if ":" in what:
        lines, fn = tree.functions.get(what, (None, None))
        return body_sha(lines, fn) if fn else ""
    found = tree.method(*what.split("."))
    return body_sha(found[1], found[2]) if found else ""


def overlay_nest_top_re(text):
    """The overlay's own _NEST_TOP_RE (it reads upstream's box top with it at install)."""
    for node in ast.parse(text).body:
        if (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_NEST_TOP_RE"
                and isinstance(node.value, ast.Call)):
            return re.compile(node.value.args[0].value)
    return None


def main():
    text = okww_overlay.source_text()
    tree = Tree(VERSION)
    man = fu.read_manifest(tree.copy)
    print(f"\n[the OK-WW source checked is {VERSION} as fetched, untouched]"
          + ("" if VERSION == INSTALLED else f" (not the installed {INSTALLED})"))
    check("copy is of that tag", man.get("tag"), VERSION)
    check("tag's commit", man.get("commit"), COMMITS.get(VERSION, "<unrecorded>"))
    edited = [p for p, sha in man["files"].items()
              if hashlib.sha256((tree.copy / (p + fu.SUFFIX)).read_bytes()).hexdigest() != sha]
    check("no file differs from its fetched sha256", edited, [])

    print("\n[the checker itself catches the failures it exists for]")
    # b24c48fc: upstream v3.7.4 run(self, retries=3) calls self.run(retries - 1)
    # (FarmEchoTask.py:108, :123); an override run(self) refuses that call.
    up = signature(ast.parse("def run(self, retries=3): pass").body[0])
    check("run(self) vs upstream run(self, retries=3): refused calls found",
          sig_gaps(up, signature(ast.parse("def run(self): pass").body[0])) != [], True)
    check("run(self, retries=3) vs the same: none",
          sig_gaps(up, signature(ast.parse("def run(self, retries=3): pass").body[0])), [])
    check("a (self, *a, **kw) wrapper takes everything",
          sig_gaps(up, signature(ast.parse("def f(self, *a, **kw): pass").body[0])), [])
    # f6b5f432: find_nest read the nest list from 0.13 in v3.6.5 (NightmareNestTask.py:212) and
    # from 0.25 since v3.7.3 (:229). Two different bodies cannot both match one pin, so drift()
    # must name find_nest on at least one of the two trees, whatever the overlay pins.
    def nest_body(t):
        _c, lines, fn = t.method("NightmareNestTask", "find_nest")
        return "".join(inspect.getblock(lines[fn.lineno - 1:]))

    old, new = Tree("v3.6.5"), Tree("v3.7.4")
    check("v3.6.5 find_nest reads from 0.13", "self.ocr(0.35, 0.13, 1, 0.96" in nest_body(old), True)
    check("v3.7.4 find_nest reads from 0.25", "self.ocr(0.35, 0.25, 1, 0.96" in nest_body(new), True)
    named = [("NightmareNestTask.find_nest" in [d["what"] for d in okww_overlay.drift(materialized(t))])
             for t in (old, new)]
    check("drift() names find_nest on v3.6.5 or v3.7.4", any(named), True)

    print(f"\n[every rebind in the overlay against {VERSION}]")
    found = rebinds(text)
    check("every override(...) call in the overlay is one of the rebinds read", stray_overrides(text), [])
    print(f"  ({len(found)} rebinds)")
    for label, why in contract(tree, text).items():
        check(f"{label}: target exists, takes upstream's calls", why, [])

    print(f"\n[pinned copies match {VERSION}]")
    check("pins read from the overlay", len(okww_overlay.pins()) > 0, True)
    check("every pinned body found upstream and equal", pin_problems(tree), [])
    check("okww_overlay.drift() is empty", okww_overlay.drift(materialized(tree)), [])

    print(f"\n[upstream bodies the overlay relies on, as reviewed for {VERSION}]")
    rows = RELIED.get(VERSION)
    check(f"{VERSION} has a reviewed row", rows is not None, True)
    for what, want in rows or []:
        check(f"{what} is the body reviewed", relied_sha(tree, what), want)
    check("config.py hands get_game_launch_arguments to ok-script",
          LAUNCH_LINE in tree.files.get("config.py", ""), True)
    top_re = overlay_nest_top_re(text)
    nest = tree.method("NightmareNestTask", "find_nest")
    m = top_re.search("".join(inspect.getblock(nest[1][nest[2].lineno - 1:]))) if top_re and nest else None
    check("the overlay reads find_nest's box top as upstream wrote it",
          m.group(1) if m else None, NEST_TOP.get(VERSION))

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
