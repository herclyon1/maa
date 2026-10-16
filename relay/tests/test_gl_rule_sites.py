"""Every log rule in the relay has a real line that it reads (gamesim design 3, "Log-rule coverage").

A rule site is a regex or a substring test in one of the relay modules that judge game logs
(MODULES): what the verdict, the report and the echo-farm watchdog look for. A rule nobody has
seen fire on a real line can be wrong for months without a test noticing (design 3: 18 sites
had no line anywhere, 34 only a hand-made fixture). This test lists every site, from the
source, and finds a line it matches in:

  corpus    real records of the game machine: relay/tests/replay/ (the labelled replay), the
            gamesim corpora relay/tests/gamesim/corpus/ (U13a-c, U14) and the T7 machine inputs
            relay/tests/gamesim/chain/machine/; logs (.log, .log.gz) and AUTO-MAS history
            records, never a case or expectation file;
  scenario  what the real overlay printed in the OK-WW scenarios on Windows
            (relay/tests/gamesim/chain/logs/, gamesim T7: test_log_contract.py re-checks on
            every Windows run that the overlay still prints what these files count);
  fixture   relay/tests/fixtures/ only: kept apart, a fixture is not known to be real.

The sites with no corpus or scenario line are listed in GAPS with where a line is found (a
fixture only, or nowhere). The test fails on a site that is not covered and not listed, and on
a listed site that is now covered (delete it from GAPS), so the list stays the truth.
The site inventory follows the coordinator's census (scratchpad gamesim/configs/tools/rules.py,
2026-10-13: 269 sites in these 14 modules), read from the source, not from a copy.

    relay-python tests/test_gl_rule_sites.py [--show] [--gaps]
"""
from __future__ import annotations

import ast
import gzip
import importlib
import json
import os
import re
import sys
import time
from pathlib import Path

import re._parser as sre_parse  # the parser re itself uses (sre_parse is deprecated)

HERE = Path(__file__).resolve().parent
RELAY = HERE.parent
PKG = RELAY / "ark_relay"
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(HERE))
# A relay module may read the alarm URL at import: never the real Mac's (as relay/tests/_tmp.py does).
os.environ.setdefault("ARK_ALERT_PUSH_URL", "")

# The modules that judge game logs (rules.py MODULES).
MODULES = (
    "features/verify/collector_maa.py",
    "features/verify/collector_maaend.py",
    "features/verify/collector_okww.py",
    "features/verify/outcome.py",
    "features/verify/maaend_fwlog.py",
    "features/verify/gamelog_errors.py",
    "features/alarm/gamelogs.py",
    "core/collector.py",
    "features/echofarm/echofarm.py",
    "features/weekly/weeklyboss.py",
    "features/weekly/annihilation.py",
    "features/makeup/makeup.py",
    "features/makeup/collect_retry.py",
    "features/schedule/stagegate.py",
)
TIERS = ("corpus", "scenario", "fixture")
CORPUS_DIRS = (HERE / "replay", HERE / "gamesim" / "corpus", HERE / "gamesim" / "chain" / "machine")
SCENARIO_DIR = HERE / "gamesim" / "chain" / "logs"
FIXTURE_DIR = HERE / "fixtures"
# Case and expectation files hold what a case must say, not what a log said.
NOT_RECORDS = re.compile(r"^(?:expected|verdict|cases?|SOURCE)\.json$|^L\d+-.*\.json$")
RE_FUNCS = {"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"}

# ---------------------------------------------------------------------------------------------
# Sites with no line in a corpus or a scenario log, as of 2026-10-13 (gamesim U8). Key: (module,
# pattern) - the pattern as written, or for a pattern built at run time the expression that
# builds it. Value: (where a line is found - "fixture": only a fixture, "none": nowhere; why).
_MAAEND = "no MaaEnd record in the corpora prints it (U13b's 17 cases; replay 10-10)"
_OKWW_RARE = "no recorded OK-WW run (corpus okww 11 runs, replay 09-01..09-07) nor scenario prints it"
_SCEN_STOPS = "its overlay line comes after the moment the scenario ends, or on a path no scenario plays"
GAPS: "dict[tuple[str, str], tuple[str, str]]" = {
    ("features/verify/collector_maa.py", r"Cannot set stage\W*([A-Za-z0-9\-]+)"):
        ("none", "design 3: cite MAA's producer line at the installed tag or delete the rule (not done)"),
    ("features/verify/collector_maaend.py", r"^是(\S+?基质)\s*$"): ("none", _MAAEND),
    ("features/verify/collector_maaend.py", r"(\d+)\s*条路线"):
        ("none", "design 3: cite MaaEnd's producer line or delete the rule (not done); " + _MAAEND),
    ("features/verify/collector_maaend.py", r"^获得以下物品[:：]\s*$"):
        ("none", _MAAEND + "; the corpus has the stamped form, the rule reads the message part"),
    ("features/verify/collector_maaend.py", r"^任务(开始|完成|失败)[:：]\s*(\S.+?)\s*$"):
        ("none", "reads the message part of a stamped line (_LINE_STAMP strips the stamp first); "
                 "the corpus lines carry the stamp"),
    ("features/verify/collector_maaend.py", r"(?:路线|线路)(\d+)[：:][^\n]*采集失败"):
        ("fixture", "only fixtures/collect-retry-2026-09-11 (real MXU lines, no SOURCE in the census)"),
    ("features/verify/collector_maaend.py", r"((?:路线|线路)(\d+)[：:][^\n]*?)采集失败"):
        ("fixture", "only fixtures/collect-retry-2026-09-11 (real MXU lines, no SOURCE in the census)"),
    ("features/verify/collector_okww.py", r"info_set Teleport to Forgery Challenge (\d+)"):
        ("none", "the machine farms Tacet; no Forgery run recorded"),
    ("features/verify/collector_okww.py", "ForgeryTask:"): ("none", "the machine farms Tacet; no Forgery run recorded"),
    ("features/verify/outcome.py", "_STAMINA_TASK + 'farm_(?:tacet|domain): exceeded recovery retries \\\\((\\\\d+)\\\\)'"):
        ("none", "upstream TacetTask.py:79 / DomainTask.py:73; three deaths while farming never recorded"),
    ("features/verify/outcome.py", r"DailyTask:补刷体力出错，照常领日常奖励: ([^\n]*)"): ("none", _OKWW_RARE),
    ("features/verify/outcome.py", r"活跃奖励：没有核对，(.+)"): ("none", _OKWW_RARE),
    ("features/verify/outcome.py", r"周本领奖：回读次数没变（(\d+)/3），这次没领到"):
        ("none", _OKWW_RARE + "; no scenario claims without the count dropping"),
    ("features/verify/outcome.py", "战令没领到："): ("none", _SCEN_STOPS + " (battle_pass_reopen opens it)"),
    ("features/verify/outcome.py", "战令：没有重试，"): ("none", _SCEN_STOPS + " (battle_pass_reopen retries)"),
    ("features/verify/outcome.py", "指定点位的名字读到了，计数没读到"): ("none", _OKWW_RARE),
    ("features/verify/outcome.py", "只刷指定点位的改动没装上，这一轮不刷巢穴"):
        ("none", "in none of 131 recorded runs (U13a); the overlay leaves find_nest bound on v3.5.28..v3.7.5 (U9)"),
    ("features/verify/outcome.py", "列表里没找到指定的点位"): ("none", _OKWW_RARE),
    ("core/collector.py", r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \|[^|]*\| MaaEnd 自动代理 \| MaaEnd 队列已结束但进程未退出"):
        ("fixture", "AUTO-MAS AutoProxy.py _wait_maaend_stage (MXU#371); real app.log line 2026-10-16 13:53:01 "
                    "only in fixtures/display-wake-2026-10-16"),
    ("core/collector.py", "未捕获"): ("fixture", "AUTO-MAS's 「未捕获到日志」 result; only fixtures"),
    ("core/collector.py", "模拟器启动失败"):
        ("fixture", "design 3: cite AUTO-MAS's producer line or delete the rule (not done); only fixtures"),
    ("core/collector.py", "未捕获到日志"): ("fixture", "AUTO-MAS's result text; only fixtures"),
    ("features/echofarm/echofarm.py", r"^L[Vv]\.?\s*(\d{1,3})\.?\s*(.*?)_\d+(?:\.\d+)?$"):
        ("none", "reads one OCR box cut out of a boss_string line, not a line; the chain judges it "
                 "(gamesim/chain test_log_contract.py, main_book_team_1013 level)"),
    ("features/makeup/collect_retry.py", r"^\[[^\]]+\]\s*(.+?采集失败)\s*$"):
        ("fixture", "only fixtures/collect-retry-2026-09-11 (real MXU lines, no SOURCE in the census)"),
    ("features/makeup/collect_retry.py", r"\[msg=Node\.Action\.Starting\].*?\"name\":\"(AutoCollect(?:Common)?Route\d+)(End|Failed)\""):
        ("fixture", "only fixtures/collect-retry-2026-09-11 (real MXU lines, no SOURCE in the census)"),
    ("features/makeup/collect_retry.py", r"Web server listening on http://127\.0\.0\.1:(\d+)"):
        ("none", "MXU's own stdout at start; not kept in any record"),
}
# Sites that read something other than a game's log - a config, a stage name, a path, a locale
# key, the registry file's own format - so no log line is owed. Key as in GAPS; value: what it reads.
NOT_LOG: "dict[tuple[str, str], str]" = {
    ("features/verify/outcome.py", "日常改动"): "a label of outcome._PATCH_EFFECTS, not a log line",
    ("features/verify/collector_okww.py", "\\Saved\\"): "a changed client file's path (_client_change)",
    ("features/verify/collector_okww.py", "/Saved/"): "a changed client file's path (_client_change)",
    ("features/verify/collector_okww.py", ".quality"): "a changed client file's path (_client_change)",
    ("features/verify/collector_okww.py", "AntiCheatExpert"): "a changed client file's path (_client_change)",
    ("features/verify/gamelog_errors.py", r"^verdict:\s+(recovered|not-a-fault)\s+-\s+(\S.*)$"):
        "the format of gamelog_errors.txt itself",
    ("features/alarm/gamelogs.py", "Auto Farm all Nightmare Nest"): "OK-WW's DailyTask.json option list",
    ("features/weekly/weeklyboss.py", "Teleport and Farm 4C Echo"): "OK-WW's DailyTask.json option list",
    ("features/weekly/annihilation.py", "backend-error"): "the relay's own once-per-condition set",
    ("features/makeup/makeup.py", ".label"): "MaaEnd locale keys (task.<name>.label)",
    ("features/makeup/collect_retry.py", r"^(AutoCollect(?:Common)?Route\d+)(Start|Dispatch)$"): "MaaEnd pipeline node names",
    ("features/makeup/collect_retry.py", r"^AutoCollect.*Routes$"): "MaaEnd option names",
    ("features/makeup/collect_retry.py", r"option\.(AutoCollect(?:Common)?Route\d+)\.failed"): "MaaEnd locale keys",
    ("features/makeup/collect_retry.py", "no-labels"): "the relay's own once-per-condition set",
    ("features/schedule/stagegate.py", r"^([A-Za-z]{0,3})(\d{1,2})-(\d{1,2})(?:-?(\w+))*$"): "an MAA stage name",
    ("features/schedule/stagegate.py", "SSReopen-"): "an MAA stage name",
    ("features/schedule/stagegate.py", "IfFight"): "an MAA gui.new.json task entry",
    ("features/schedule/stagegate.py", "final"): "the relay's own stage-gate row",
}
# ---------------------------------------------------------------------------------------------


def _flags(node) -> int:
    if node is None:
        return 0
    try:
        return int(eval(compile(ast.Expression(node), "<flags>", "eval"), {"re": re}))  # re.X | re.Y only
    except Exception:  # noqa: BLE001 - a flag expression that is not re.* is no flag we can read
        return 0


def _row_tables(tree: ast.Module) -> "dict[str, list[tuple]]":
    """Module-level tables of rows of constants: NAME = ((str, str, ...), ...)."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, (ast.Tuple, ast.List)) and node.value.elts \
                and all(isinstance(r, ast.Tuple) and all(isinstance(e, ast.Constant) for e in r.elts)
                        for r in node.value.elts):
            out[node.targets[0].id] = [tuple(e.value for e in r.elts) for r in node.value.elts]
    return out


def _loop_columns(tree: ast.Module, tables: "dict[str, list[tuple]]") -> "dict[str, tuple[str, int]]":
    """`for a, b, c in TABLE:` -> {a: (TABLE, 0), b: (TABLE, 1), ...}."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id in tables \
                and isinstance(node.target, ast.Tuple):
            for i, el in enumerate(node.target.elts):
                if isinstance(el, ast.Name):
                    out[el.id] = (node.iter.id, i)
    return out


def _const_strs(tree: ast.Module) -> "dict[str, list[str]]":
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            v = node.value
            if isinstance(v, (ast.Tuple, ast.List, ast.Set)) and v.elts and all(
                    isinstance(e, ast.Constant) and isinstance(e.value, str) for e in v.elts):
                out[node.targets[0].id] = [e.value for e in v.elts]
            elif isinstance(v, ast.Constant) and isinstance(v.value, str):
                out[node.targets[0].id] = [v.value]
    return out


def extract(rel: str) -> "list[dict]":
    """The rule sites of one module: {kind, pat, flags, line, expr?} (rules.py extract)."""
    path = PKG / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts = _const_strs(tree)
    tables = _row_tables(tree)
    columns = _loop_columns(tree, tables)
    rules, used = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" \
                and node.func.attr in RE_FUNCS and node.args:
            a0, fl = node.args[0], None
            if node.func.attr == "compile" and len(node.args) > 1:
                fl = node.args[1]
            elif node.func.attr in ("search", "match", "fullmatch", "findall", "finditer", "split") \
                    and len(node.args) > 2:
                fl = node.args[2]
            for kw in node.keywords:
                if kw.arg == "flags":
                    fl = kw.value
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                rules.append({"kind": "regex", "pat": a0.value, "flags": _flags(fl), "line": node.lineno})
            elif isinstance(a0, ast.Name) and a0.id in columns:
                # A column of a table the function loops over: one site per row.
                name, col = columns[a0.id]
                for row in tables[name]:
                    if col < len(row) and isinstance(row[col], str):
                        rules.append({"kind": "regex", "pat": row[col], "flags": _flags(fl),
                                      "line": node.lineno, "table": f"{name}[{col}]"})
            else:
                rules.append({"kind": "regex-dynamic", "pat": ast.unparse(a0), "flags": _flags(fl),
                              "line": node.lineno})
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn)):
            left = node.left
            if isinstance(left, ast.Constant) and isinstance(left.value, str) and len(left.value) >= 3:
                rules.append({"kind": "substr", "pat": left.value, "flags": 0, "line": node.lineno})
            elif isinstance(left, ast.Name) and left.id in consts:
                used.add(left.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("startswith", "endswith") and node.args:
            a0 = node.args[0]
            vals = []
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                vals = [a0.value]
            elif isinstance(a0, ast.Tuple):
                vals = [e.value for e in a0.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            elif isinstance(a0, ast.Name) and a0.id in consts:
                used.add(a0.id)
            rules += [{"kind": "substr", "pat": v, "flags": 0, "line": node.lineno} for v in vals if len(v) >= 3]
        elif isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            for gen in node.generators:
                if isinstance(gen.iter, ast.Name) and gen.iter.id in consts and isinstance(gen.target, ast.Name):
                    v = gen.target.id
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Compare) and isinstance(sub.left, ast.Name) and sub.left.id == v \
                                and any(isinstance(o, (ast.In, ast.NotIn)) for o in sub.ops):
                            used.add(gen.iter.id)
                        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                                and sub.func.attr in ("startswith", "endswith", "find") and sub.args \
                                and isinstance(sub.args[0], ast.Name) and sub.args[0].id == v:
                            used.add(gen.iter.id)
    for name in sorted(used):
        rules += [{"kind": "substr-const", "pat": v, "flags": 0, "line": 0, "const": name}
                  for v in consts[name] if len(v) >= 2]
    return rules


def _resolve_dynamic(rel: str, rules: "list[dict]") -> None:
    """A pattern built from module constants (`_STAMINA_TASK + r"..."`): evaluated in the
    imported module, so it is checked like any other. One that needs a local stays dynamic."""
    dyn = [r for r in rules if r["kind"] == "regex-dynamic"]
    if not dyn:
        return
    mod = importlib.import_module("ark_relay." + rel[:-3].replace("/", "."))
    for r in dyn:
        try:
            val = eval(r["pat"], dict(vars(mod)))  # the module's own expression
        except Exception:  # noqa: BLE001 - a local name: not resolvable statically
            continue
        if isinstance(val, re.Pattern):
            val = val.pattern
        if isinstance(val, str):
            r["resolved"] = val


def registry_sites() -> "list[dict]":
    """The ERROR lines gamelog_errors.txt registers: each entry is a rule over a game's log too."""
    from ark_relay.features.verify import gamelog_errors as ge  # noqa: PLC0415
    rel = "features/verify/" + ge.REGISTRY.name
    entries, bad = ge.parse(ge.REGISTRY.read_text(encoding="utf-8"))
    if bad:
        raise SystemExit(f"{rel}: {bad[:3]}")
    return [{"kind": "registry", "pat": e.pattern.pattern, "flags": e.pattern.flags & ~re.U,
             "line": e.line_no, "module": rel, "key": (rel, e.pattern.pattern)} for e in entries]


def sites() -> "list[dict]":
    out = []
    for rel in MODULES:
        if not (PKG / rel).is_file():
            raise SystemExit(f"{rel} is gone: update MODULES (and GAPS) to where its rules went")
        rules = extract(rel)
        if rel == "features/verify/gamelog_errors.py":
            # `re.compile(rx)` in parse(): rx is each regex of gamelog_errors.txt, which
            # registry_sites() lists one by one.
            rules = [r for r in rules if not (r["kind"] == "regex-dynamic" and r["pat"] == "rx")]
        _resolve_dynamic(rel, rules)
        for r in rules:
            r["module"] = rel
            r["key"] = (rel, r["pat"])
        out += rules
    return out + registry_sites()


# --------------------------------------------------------------------------------- the lines

def _read(f: Path) -> "str | None":
    try:
        if f.name.endswith(".gz"):
            return gzip.decompress(f.read_bytes()).decode("utf-8", "replace")
        return f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _files(root: Path, fixture: bool) -> "list[Path]":
    out = []
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        name = f.name
        if name.endswith((".log", ".log.gz")):
            out.append(f)
        elif name.endswith(".json") and not NOT_RECORDS.match(name):
            out.append(f)
        elif fixture and name.endswith((".txt", ".jsonl")):
            out.append(f)
    return out


class Lines:
    """The text of some files: `blob` holds their distinct lines (for one-line rules), `texts`
    each file whole (for a rule that spans lines)."""

    def __init__(self, files: "list[Path]"):
        seen, self.texts = {}, []
        for f in files:
            text = _read(f)
            if text is None:
                continue
            self.texts.append(text)
            for ln in text.splitlines():
                seen.setdefault(ln, None)
        self.blob = "\n".join(seen)


def corpora() -> "dict[str, Lines]":
    corpus = [f for d in CORPUS_DIRS if d.is_dir() for f in _files(d, fixture=False)]
    scen = sorted(SCENARIO_DIR.glob("*.log.gz")) if SCENARIO_DIR.is_dir() else []
    return {"corpus": Lines(corpus), "scenario": Lines(scen), "fixture": Lines(_files(FIXTURE_DIR, fixture=True))}


def _literal(pat: str, flags: int) -> str:
    """The longest run of literal characters every match must contain ('' if none)."""
    if flags & re.I:
        return ""
    try:
        parsed = sre_parse.parse(pat, flags)
    except re.error:
        return ""
    best, cur = "", []
    for op, av in parsed:
        if op is sre_parse.LITERAL:
            cur.append(chr(av))
            continue
        if len("".join(cur)) > len(best):
            best = "".join(cur)
        cur = []
        if op is sre_parse.MAX_REPEAT or op is sre_parse.MIN_REPEAT:
            pass
    if len("".join(cur)) > len(best):
        best = "".join(cur)
    return best


def _spans_lines(pat: str, flags: int) -> bool:
    """A rule over several lines: \\n in it, or DOTALL (passed or inline, `(?s)`)."""
    try:
        dotall = bool(re.compile(pat, flags).flags & re.S)
    except re.error:
        dotall = False
    return "\\n" in pat or "\n" in pat or dotall


def hit(rule: dict, lines: Lines) -> "str | None":
    """The first line of `lines` the rule matches (for a rule over several lines, where its
    match starts), or None."""
    pat = rule.get("resolved") if rule["kind"] == "regex-dynamic" else rule["pat"]
    if rule["kind"] not in ("substr", "substr-const") and pat is not None and _spans_lines(pat, rule["flags"]):
        rx = re.compile(pat, rule["flags"] | re.M)
        for text in lines.texts:
            if m := rx.search(text):
                a, b = text.rfind("\n", 0, m.start()) + 1, text.find("\n", m.start())
                return text[a:] if b < 0 else text[a:b]
        return None
    text = lines.blob
    if rule["kind"] in ("substr", "substr-const"):
        i = text.find(rule["pat"])
    else:
        if pat is None:
            return None
        rx = re.compile(pat, rule["flags"] | re.M)
        lit = _literal(pat, rule["flags"])
        i = -1
        if lit:
            j = text.find(lit)
            while j >= 0:
                a, b = text.rfind("\n", 0, j) + 1, text.find("\n", j)
                line = text[a:] if b < 0 else text[a:b]
                # gamelog_errors.error_lines strips each line before the registry reads it.
                if rx.search(line) or (rule["kind"] == "registry" and rx.search(line.rstrip())):
                    i = j
                    break
                j = text.find(lit, b if b >= 0 else len(text))
        else:
            m = rx.search(text)
            i = m.start() if m else -1
    if i < 0:
        return None
    a, b = text.rfind("\n", 0, i) + 1, text.find("\n", i)
    return text[a:] if b < 0 else text[a:b]


def census(texts: "dict[str, Lines] | None" = None) -> "list[dict]":
    """Every site with `where` (the first tier with a line) and `line` (that line)."""
    texts = texts if texts is not None else corpora()
    out = []
    for r in sites():
        r["where"], r["line_seen"] = "none", None
        if r["kind"] == "regex-dynamic" and "resolved" not in r:
            r["where"] = "dynamic"
        else:
            for tier in TIERS:
                seen = hit(r, texts[tier]) if tier in texts else None
                if seen is not None:
                    r["where"], r["line_seen"] = tier, seen[:200]
                    break
        out.append(r)
    return out


def problems(found: "list[dict]") -> "list[str]":
    bad = []
    covered = {r["key"] for r in found if r["where"] in ("corpus", "scenario")}
    keys = {r["key"] for r in found}
    for r in found:
        if r["where"] in ("corpus", "scenario") or r["key"] in NOT_LOG:
            continue
        listed = GAPS.get(r["key"])
        if listed is None:
            bad.append(f"{r['module']}:{r['line']} {r['kind']} {r['pat']!r}: no real line "
                       f"({r['where']}); give it one, or list it in GAPS with why")
        elif listed[0] != r["where"]:
            bad.append(f"{r['module']}:{r['line']} {r['pat']!r}: GAPS says {listed[0]!r}, found {r['where']!r}")
    for key in GAPS:
        if key in covered:
            bad.append(f"{key[0]} {key[1]!r} is covered now: delete it from GAPS")
        elif key not in keys:
            bad.append(f"{key[0]} {key[1]!r} is in GAPS but no longer a rule site: delete it")
    for key in NOT_LOG:
        if key not in keys:
            bad.append(f"{key[0]} {key[1]!r} is in NOT_LOG but no longer a rule site: delete it")
        if key in GAPS:
            bad.append(f"{key[0]} {key[1]!r} is in both GAPS and NOT_LOG")
    return bad


def main(argv: "list[str]") -> int:
    t0 = time.monotonic()
    found = census()
    took = time.monotonic() - t0
    counts = {w: sum(1 for r in found if r["where"] == w) for w in (*TIERS, "none", "dynamic")}
    print(f"{len(found)} rule sites in {len(MODULES)} modules ({took:.1f} s): "
          + ", ".join(f"{w} {n}" for w, n in counts.items()))
    if "--show" in argv:
        for r in found:
            print(json.dumps({k: r.get(k) for k in ("module", "line", "kind", "pat", "where", "line_seen")},
                             ensure_ascii=False))
    gaps = [r for r in found if r["where"] not in ("corpus", "scenario") and r["key"] not in NOT_LOG]
    print(f"{len(gaps)} log rule sites without a real line (GAPS), "
          f"{sum(1 for r in found if r['key'] in NOT_LOG)} sites that read no log (NOT_LOG)")
    if "--gaps" in argv:
        for r in gaps:
            why = GAPS.get(r["key"], ("", "not listed"))[1]
            print(f"  {r['where']:8} {r['module']}:{r['line']} {r['kind']} {r['pat']!r}: {why}")
    bad = problems(found)
    for b in bad:
        print(f"  ✗ {b}")
    print("\n" + (f"FAILED: {len(bad)}" if bad else "all checks passed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
