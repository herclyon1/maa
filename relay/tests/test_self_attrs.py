"""Every self.x the relay uses exists; and every fault that fixed itself leaves a red item in the technical log.

One part per former file, each run on its own (tests/_parts.py): test_self_attrs.py, test_self_heal_red.py.
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


def _part_main():  # noqa: C901 - the whole body of the file this part was
    """Every `self.x` used in the relay must actually exist.

2026-08-23: `Engine._boot_time` was called from three places and never
defined. Python does not complain until the line runs, and the line only runs
on a boot where a queue's time has already passed - so it sat undetected from
2026-08-21 until the morning it swallowed the daily report and the power-off.

The service loop catches exceptions so one bad tick cannot kill the relay.
That is right, and it is also why this went unnoticed: the relay stayed up,
logged an AttributeError, and quietly did none of the work that follows.

A whole class of bug - typo'd attribute, method renamed at one call site,
method planned and never written - is a static fact about the source. This
checks it, so it can never again depend on a particular morning to surface.

    Formerly test_self_attrs.py.
    """
    import ast

    ROOT = Path(__file__).resolve().parents[1]

    # Names that genuinely come from somewhere this file cannot see.
    INHERITED = {
        "ArkRelayService": {
            # win32serviceutil.ServiceFramework
            "ReportServiceStatus", "SvcStop", "SvcDoRun", "stop_event",
        },
        "RelayLogHandler": {
            # logging.handlers.RotatingFileHandler (logfile.py doRollover)
            "stream", "_open", "backupCount", "baseFilename", "delay", "rotate",
        },
        "_WordsOut": {
            # ast.NodeTransformer (okww_overlay.py, the shape of an OK-WW method)
            "generic_visit",
        },
    }


    def defined_names(cls: ast.ClassDef) -> set[str]:
        out = set()
        for node in ast.walk(cls):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.add(node.name)
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    # 一行赋多个属性也算定义：`self.a, self.b = x, y`。
                    # 2026-09-08 漏过这种写法，把 _DirWatch 正常的三个属性报成「没定义」。
                    for t in (tgt.elts if isinstance(tgt, (ast.Tuple, ast.List)) else [tgt]):
                        if (isinstance(t, ast.Attribute)
                                and isinstance(t.value, ast.Name) and t.value.id == "self"):
                            out.add(t.attr)
                        elif isinstance(t, ast.Name):
                            out.add(t.id)        # class-level attribute
            elif isinstance(node, ast.AnnAssign):
                tgt = node.target
                if (isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
                    out.add(tgt.attr)
                elif isinstance(tgt, ast.Name):
                    out.add(tgt.id)
            elif isinstance(node, ast.For):
                tgt = node.target
                if (isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
                    out.add(tgt.attr)
        return out


    def used_names(cls: ast.ClassDef) -> dict[str, int]:
        out: dict[str, int] = {}
        for node in ast.walk(cls):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name) and node.value.id == "self"
                    and isinstance(node.ctx, ast.Load)):
                out.setdefault(node.attr, node.lineno)
        return out


    def module_name(f: Path) -> str:
        """Dotted import name of a scanned file: ark_relay/core/config.py -> ark_relay.core.config."""
        parts = list(f.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)


    class Index:
        """Top-level classes and `from ... import` bindings of every scanned module.

    A subclass may use `self.x` defined only on its base class (GardenGate and
    WeeklyBossGate inherit `_load`, `_save`, `automas_dir` from weekgate.WeekGate).
    The base is looked up in the scanned source - same module, or followed through
    `from <module> import <name>` (relative imports and re-exports included). A base
    that cannot be found in the scanned files (stdlib, third-party, `import x` then
    `x.Base`) adds nothing, so those classes are checked exactly as before.
    """

        def __init__(self, trees: dict[str, tuple[ast.Module, bool]]):
            self.classes: dict[str, dict[str, ast.ClassDef]] = {}
            self.imports: dict[str, dict[str, tuple[str, str]]] = {}
            for mod, (tree, is_pkg) in trees.items():
                self.classes[mod] = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
                imps: dict[str, tuple[str, str]] = {}
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        src = node.module or ""
                        if node.level:
                            pkg = mod.split(".") if is_pkg else mod.split(".")[:-1]
                            pkg = pkg[:len(pkg) - (node.level - 1)]
                            src = ".".join(pkg + ([src] if src else []))
                        for a in node.names:
                            imps[a.asname or a.name] = (src, a.name)
                self.imports[mod] = imps

        def lookup(self, mod: str, name: str, depth: int = 0) -> "tuple[str, ast.ClassDef] | None":
            if depth > 10:
                return None
            if name in self.classes.get(mod, {}):
                return mod, self.classes[mod][name]
            src = self.imports.get(mod, {}).get(name)
            if src is None:
                return None
            return self.lookup(src[0], src[1], depth + 1)

        def inherited(self, mod: str, cls: ast.ClassDef, seen=None) -> set[str]:
            """Names defined on every base class reachable in the scanned source."""
            seen = set() if seen is None else seen
            out: set[str] = set()
            for b in cls.bases:
                if not isinstance(b, ast.Name):
                    continue
                hit = self.lookup(mod, b.id)
                if hit is None or id(hit[1]) in seen:
                    continue
                seen.add(id(hit[1]))
                out |= defined_names(hit[1]) | INHERITED.get(hit[1].name, set())
                out |= self.inherited(hit[0], hit[1], seen)
            return out


    def main() -> int:
        files = sorted(list([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files"} & set(p.parts)])
                       + [ROOT / "service.py", ROOT / "boot_stages.py"])
        # 地板：glob 扫到 0 个文件也会打印「通过」，闸门就成了摆设——
        # 目录改名、路径写错都会静默失效。2026-09-08 回放测试栽过一次。
        if len(files) < 20:
            print(f"  ✗ 只扫到 {len(files)} 个文件，至少该有 20 个——路径不对或目录改名了")
            return 1
        problems = []
        checked = 0
        trees = {module_name(f): (ast.parse(f.read_text(encoding="utf-8"), filename=str(f)),
                                  f.name == "__init__.py")
                 for f in files}
        index = Index(trees)
        for f in files:
            mod = module_name(f)
            tree = trees[mod][0]
            for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                checked += 1
                known = (defined_names(cls) | INHERITED.get(cls.name, set())
                         | index.inherited(mod, cls))
                for attr, line in sorted(used_names(cls).items()):
                    if attr.startswith("__") or attr in known:
                        continue
                    problems.append(f"{f.relative_to(ROOT)}:{line} {cls.name}.{attr} 用了但没定义")
        print(f"  检查了 {len(files)} 个文件、{checked} 个类")
        for p in problems:
            print(f"  FAIL {p}")
        if problems:
            print("FAILED")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_self_heal_red():
    """Every fault that fixed itself, and so stays out of the group, leaves a red item in the technical log.

The user, 2026-10-11 17:44 (Tokyo; his words are in relay/USER-SWITCHES.txt's header): what fixed
itself may stay out of the group, but we must look at it. So:

* techlog.add_red never hands out an id twice in one day's file (red_items numbers from 1 on
  every call: two calls in one minute gave the same id, and one `handled` cleared both);
* errwatch's one door for a record marked errwatch.recovered() writes one 「自愈待查」 red item
  with where and what the record said, every time; a plain WARNING writes none (it goes to the group);
* every errwatch.recovered() in the relay sits in the `extra=` of a log call, so it can only
  reach errwatch through that door (nothing marks a record recovered some other way);
* handle's heals (_self_heal_red) write one too;
* scripts/mac/techlog.py's patterns read these red items as unhandled until `handled`.
The USER-SWITCHES side (every `normal-state - recovered:` place has code that writes the red
item) is tests/test_mute_verdicts.py.

    Formerly test_self_heal_red.py.
    """
    import ast
    import importlib.util
    import logging
    import os
    import types
    from datetime import datetime


    TMP = tmpdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="", ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))
    from ark_relay.core import techlog
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.alarm import errwatch, handle


    def reds(state_dir, day):
        try:
            text = techlog.path_for(day, state_dir).read_text(encoding="utf-8")
        except OSError:
            return []
        return techlog.unhandled(text)


    print("[add_red: ids stay unique within a day, across calls in the same minute]")
    d = TMP / "a" / "state"
    when = datetime(2026, 10, 11, 17, 50, tzinfo=SERVER_TZ)
    first = techlog.add_red("2026-10-11", "x", ["one", "two"], state_dir=d, now=when)
    second = techlog.add_red("2026-10-11", "y", ["three"], state_dir=d, now=when)
    check("first call", first, ["R-20261011-1750-1", "R-20261011-1750-2"])
    check("second call in the same minute goes on after them", second, ["R-20261011-1750-3"])
    check("all three unhandled", [i for i, _ in reds(d, "2026-10-11")], first + second)
    check("nothing to write writes nothing", techlog.add_red("2026-10-11", "z", ["  "], state_dir=d, now=when), [])
    check("a text over several lines stays one red line",
          techlog.add_red("2026-10-11", "z", ["a\nb"], state_dir=TMP / "a2" / "state", now=when) != []
          and [t for _, t in reds(TMP / "a2" / "state", "2026-10-11")] == ["a b"], True)

    print("[the Mac reader sees them, and `handled` clears exactly one]")
    spec = importlib.util.spec_from_file_location("techlog_tool", RELAY.parent / "scripts" / "mac" / "techlog.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    text = techlog.path_for("2026-10-11", d).read_text(encoding="utf-8")
    check("the reader's red pattern matches every red line",
          sum(1 for ln in text.splitlines() if tool.RED_LINE.match(ln)), 3)
    text += "\n" + tool.handled_line("R-20261011-1750-2", "abc1234") + "\n"
    check("one handled line clears that one only", [i for i, _ in techlog.unhandled(text)],
          ["R-20261011-1750-1", "R-20261011-1750-3"])

    print("[errwatch: a recovered record writes one 「自愈待查」 red item, a plain WARNING none]")


    class _N:
        channels = ()

        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body))
            return []


    ARK = logging.getLogger(errwatch.ARK)
    ARK.setLevel(logging.INFO)
    sd = TMP / "b" / "state"
    sd.mkdir(parents=True)
    n = _N()
    h = errwatch.ErrorKindAlert(n, state_dir=sd, known={}, pace=0, retry=(0.05,))
    ARK.addHandler(h)
    try:
        lg = logging.getLogger("ark.test_self_attrs")
        lg.warning("手机通道断了 20 秒，自己重新连上了", extra=errwatch.recovered())
        lg.warning("手机通道断了 30 秒，自己重新连上了", extra=errwatch.recovered())
        lg.warning("这个没好")
        h.drain(timeout=5.0)
    finally:
        ARK.removeHandler(h)
        h.close()
    today = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    got = reds(sd, today)
    check("two recovered records, two red items", len(got), 2)
    check("each says 自愈待查, where, and what it said",
          [(t.startswith(techlog.SELF_HEAL), "ark.test_self_attrs" in t, "自己重新连上了" in t) for _, t in got],
          [(True, True, True)] * 2)
    check("their ids differ", len({i for i, _ in got}), 2)
    check("the plain WARNING went to the group and wrote no red item",
          (len(n.sent), any("这个没好" in t for _, t in got)), (1, False))

    print("[handle's heals write one too]")
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(state_dir=str(TMP / "c" / "state")))
    handle._self_heal_red(eng, "MaaEnd 2026-10-11/endfield/MaaEnd-05-30-34 中途失败过，重试后成功", "自动采集")
    got = reds(TMP / "c" / "state", today)
    check("one red item naming the run and the first failure",
          [("MaaEnd-05-30-34" in t, "自动采集" in t) for _, t in got], [(True, True)])

    print("[every errwatch.recovered() in the relay is the extra= of a log call]")
    LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
    bad, seen = [], 0
    for path in sorted(RELAY.rglob("*.py")):
        if "tests" in path.relative_to(RELAY).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "recovered" and not node.args and not node.keywords):
                continue
            seen += 1
            up, ok = node, False
            while up in parents:
                par = parents[up]
                if isinstance(par, ast.keyword) and par.arg == "extra":
                    call = parents.get(par)
                    ok = (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                          and call.func.attr in LOG_METHODS)
                    break
                if isinstance(par, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                    break
                up = par
            if not ok and path.name != "errwatch.py":
                bad.append(f"{path.relative_to(RELAY)}:{node.lineno}")
    check("found the calls", seen > 10, True)
    check("none outside a log call's extra=", bad, [])
    src = (RELAY / "ark_relay" / "features" / "alarm" / "errwatch.py").read_text(encoding="utf-8")
    check("errwatch has no daily-only door any more", "def note_daily" in src, False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_self_heal_red]))
