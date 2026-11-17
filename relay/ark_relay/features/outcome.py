"""Turn OK-WW's translated (zh_CN) log lines back into the English source strings our checks look for.

Here the reverse table is read from the catalogs the machine itself has, so the upgrade that
translates a string also ships what turns it back. Only a whole log message is turned back (the
text after 「<logger>:」 in an OK-WW log line), never a piece of a longer line: a short catalog entry
such as 「完成」 must not rewrite our own Chinese lines or OCR text quoted in a line. Two shapes
besides an exact whole message:

* concatenation: a message that starts with a translation whose source ends in a space or a colon,
  the way upstream builds a line from self.tr(prefix) + value, e.g. 「进入战斗，控物状态：…」 for
  "enter combat " + state;
* placeholders: a source with {}, {0}, {name}, %s or %1 holes, whose translation becomes a pattern
  that takes the values and puts them back into the source.

A translation that more than one source maps to is left alone: turning it back would be a guess.
The catalogs are read again only when one of the files changes (an OK-WW upgrade), so a long-lived
relay picks up the new ones without a restart.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import logging
import bisect
from dataclasses import dataclass, field
from pathlib import Path
from ark_relay.core import config, texts
from datetime import datetime
from collections import Counter
from ark_relay.features import collector_maaend, weeklyboss
from ark_relay.core.wuwa_tables import wuwa_forgery, wuwa_tacet
from ark_relay.core.config import okww_root

PO_REL = Path("data") / "apps" / "ok-ww" / "working" / "i18n" / "zh_CN" / "LC_MESSAGES" / "ok.po"
TS_REL = (Path("data") / "apps" / "ok-ww" / "python" / "Lib" / "site-packages" / "ok" / "ui" / "qt"
          / "i18n" / "zh_CN.ts")

_HAN = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
# str.format ({}, {0}, {name}, {name:>3}), printf (%s, %d, %(name)s) and Qt's %1 .. %99.
_HOLE = re.compile(r"\{[^{}]*\}|%\(\w+\)[sdfr]|%[sdfr]|%\d{1,2}")
_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[,.]\d+ +[A-Z]+ +\S+ +[^\s:]+:)(.*)$")
_CONCAT_END = (" ", ":", "：")


def _unquote(s: str) -> str:
    """A PO string body without its quotes: C escapes \\n \\t \\" \\\\ resolved."""
    return re.sub(r'\\(.)', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def po_pairs(text: str) -> list[tuple[str, str]]:
    """(msgid, msgstr) of a gettext .po file: multi-line strings joined, obsolete (#~) entries,
    plural forms and empty translations left out."""
    pairs: list[tuple[str, str]] = []
    cur: dict[str, str] = {}
    key = ""

    def flush() -> None:
        if cur.get("msgid") and cur.get("msgstr") and "msgid_plural" not in cur:
            pairs.append((cur["msgid"], cur["msgstr"]))

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if not line and cur:
                flush()
                cur, key = {}, ""
            continue
        m = re.match(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+"(.*)"$', line)
        if m:
            if m.group(1) == "msgid" and "msgid" in cur:
                flush()
                cur = {}
            key = m.group(1)
            cur[key] = _unquote(m.group(2))
        elif line.startswith('"') and line.endswith('"') and key:
            cur[key] = cur.get(key, "") + _unquote(line[1:-1])
    if cur:
        flush()
    return pairs


def ts_pairs(text: str) -> list[tuple[str, str]]:
    """(source, translation) of a Qt Linguist .ts file. A translation marked unfinished, obsolete or
    vanished is not compiled into the .qm the program runs with, so it is left out."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    pairs = []
    for msg in root.iter("message"):
        src, tr = msg.find("source"), msg.find("translation")
        if src is None or tr is None or not (src.text or "") or not (tr.text or ""):
            continue
        if tr.get("type") in ("unfinished", "obsolete", "vanished"):
            continue
        pairs.append((src.text, tr.text))
    return pairs


@dataclass
class _Pattern:
    rx: re.Pattern
    source_parts: list[str]
    order: list[int]          # order[k]: the translation's hole that fills the source's k-th hole
    probe: str                # the translation's longest literal piece, to skip messages cheaply


@dataclass
class Tables:
    exact: dict[str, str] = field(default_factory=dict)        # translation -> source
    prefix: list[tuple[str, str]] = field(default_factory=list)  # (translation, source), longest first
    patterns: list[_Pattern] = field(default_factory=list)

    def message(self, msg: str) -> str | None:
        """The source string for a whole translated message, None when it is not one."""
        hit = self.exact.get(msg)
        if hit is None and msg != msg.rstrip():
            hit = self.exact.get(msg.rstrip())
        if hit is not None:
            return hit
        for zh, en in self.prefix:
            if msg.startswith(zh):
                return en + msg[len(zh):]
        for p in self.patterns:
            if p.probe and p.probe not in msg:
                continue
            m = p.rx.fullmatch(msg)
            if not m:
                continue
            vals = m.groups()
            out = [p.source_parts[0]]
            for k, part in enumerate(p.source_parts[1:]):
                out.append(vals[p.order[k]])
                out.append(part)
            return "".join(out)
        return None


def _hole_order(src_holes: list[str], dst_holes: list[str]) -> list[int] | None:
    """For each hole of the source, which hole of the translation carries its value: named
    holes by name, the rest in order. None when they do not pair up."""
    if len(src_holes) != len(dst_holes):
        return None
    named = lambda h: h not in ("{}", "%s", "%d", "%f", "%r")  # noqa: E731
    order, used = [], set()
    plain_dst = [i for i, h in enumerate(dst_holes) if not named(h)]
    plain_i = 0
    for h in src_holes:
        if named(h):
            idx = next((i for i, d in enumerate(dst_holes) if d == h and i not in used), None)
        else:
            idx = plain_dst[plain_i] if plain_i < len(plain_dst) else None
            plain_i += 1
        if idx is None or idx in used:
            return None
        used.add(idx)
        order.append(idx)
    return order


def build(pairs: list[tuple[str, str]]) -> Tables:
    """The reverse tables from (source, translation) pairs. Only translations with Chinese in them
    and sources with Latin letters are used; a translation more than one source maps to is dropped."""
    by_zh: dict[str, set[str]] = {}
    for en, zh in pairs:
        if en == zh or not _HAN.search(zh) or not _LATIN.search(en):
            continue
        by_zh.setdefault(zh, set()).add(en)
    t = Tables()
    for zh, ens in by_zh.items():
        if len(ens) != 1:
            continue
        en = next(iter(ens))
        src_holes, dst_holes = _HOLE.findall(en), _HOLE.findall(zh)
        if not src_holes and not dst_holes:
            t.exact[zh] = en
            if en.endswith(_CONCAT_END):
                t.prefix.append((zh, en))
            continue
        order = _hole_order(src_holes, dst_holes)
        dst_parts = _HOLE.split(zh)
        if order is None or not any(_HAN.search(x) for x in dst_parts):
            continue
        body = "".join(re.escape(part) + ("(.*?)" if k < len(dst_holes) else "")
                       for k, part in enumerate(dst_parts))
        if dst_parts[-1] == "":
            body = body[: -len("(.*?)")] + "(.*)" if body.endswith("(.*?)") else body
        t.patterns.append(_Pattern(re.compile(body, re.S), _HOLE.split(en), order,
                                   max(dst_parts, key=len)))
    t.prefix.sort(key=lambda p: len(p[0]), reverse=True)
    t.patterns.sort(key=lambda p: len(p.probe), reverse=True)
    return t


_CACHE: dict[str, tuple[tuple, Tables]] = {}


def _stamp(*paths: Path) -> tuple:
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((str(p), None, None))
    return tuple(out)


def tables(okww_dir: Path | None = None) -> Tables:
    """The reverse tables from the catalogs under OK-WW's install root, rebuilt when a file changes;
    empty tables when neither catalog is there."""
    root = Path(okww_dir) if okww_dir else config.okww_root()
    po, ts = root / PO_REL, root / TS_REL
    stamp = _stamp(po, ts)
    got = _CACHE.get(str(root))
    if got and got[0] == stamp:
        return got[1]
    pairs: list[tuple[str, str]] = []
    for path, parse in ((po, po_pairs), (ts, ts_pairs)):
        try:
            pairs += parse(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    t = build(pairs)
    _CACHE[str(root)] = (stamp, t)
    return t


def normalize(text: str, okww_dir: Path | None = None) -> str:
    """`text` with every OK-WW log line whose whole message is a catalog translation turned back
    into its source; every other line exactly as it was."""
    if not _HAN.search(text):
        return text
    t = tables(okww_dir)
    if not (t.exact or t.patterns):
        return text
    out, changed = [], False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        m = _LINE.match(body)
        if m and _HAN.search(m.group(2)):
            new = t.message(m.group(2))
            if new is not None and new != m.group(2):
                line = m.group(1) + new + line[len(body):]
                changed = True
        out.append(line)
    return "".join(out) if changed else text


_log_gamelog_errors = logging.getLogger("ark.gamelog_errors")

REGISTRY = Path(__file__).with_name("gamelog_errors.txt")
VERDICT = re.compile(r"^verdict:\s+(recovered|not-a-fault)\s+-\s+(\S.*)$")

# The ERROR marker of each script's log, and how much of a line to quote.
_MARK = {
    "MAA": re.compile(r"\[ERR\]"),                  # MAA's gui.log copy
    "MaaEnd": re.compile(r"\[ERR\]"),               # MaaFramework's log copy
    "OK-WW": re.compile(r" ERROR "),                # OK-WW's ok-script log copy
}
_NUM = re.compile(r"\d+")
QUOTE = 300


class Entry:
    __slots__ = ("script", "pattern", "kind", "why", "source", "line_no")

    def __init__(self, script, pattern, kind, why, source, line_no):
        self.script, self.pattern, self.kind, self.why, self.source, self.line_no = \
            script, pattern, kind, why, source, line_no


def parse(text: str) -> "tuple[list[Entry], list[str]]":
    """(entries, problems) of a registry text; problems name the line."""
    entries, problems = [], []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) != 4:
            problems.append(f"line {i}: not `script | regex | verdict: ... | source`")
            continue
        script, rx, verdict, source = parts
        if script not in _MARK:
            problems.append(f"line {i}: unknown script {script!r}")
            continue
        try:
            pattern = re.compile(rx)
        except re.error as exc:
            problems.append(f"line {i}: bad regex ({exc})")
            continue
        m = VERDICT.match(verdict)
        if not m:
            problems.append(f"line {i}: verdict is not `verdict: recovered - why` / `verdict: not-a-fault - why`")
            continue
        entries.append(Entry(script, pattern, m.group(1), m.group(2), source, i))
    return entries, problems


_cache: dict = {}


def registry() -> "list[Entry]":
    """The shipped registry, read once per process. Unreadable: no entry (everything is pushed)."""
    if "entries" not in _cache:
        try:
            entries, problems = parse(REGISTRY.read_text(encoding="utf-8"))
        except OSError as exc:
            entries, problems = [], [f"{REGISTRY.name} unreadable: {type(exc).__name__}"]
        if problems:
            _log_gamelog_errors.warning("游戏日志报错清单有 %d 行读不了，这些行不算登记：%s", len(problems), "；".join(problems[:3]))
        _cache["entries"] = entries
    return _cache["entries"]


def error_lines(script: str, text: str) -> "list[str]":
    """The ERROR lines of one script's log text."""
    mark = _MARK.get(script)
    if mark is None:
        return []
    if script == "OK-WW":
        pass
        text = normalize_okww_log(text)
    return [ln.rstrip() for ln in text.splitlines() if mark.search(ln)]


def known(script: str, line: str, entries=None) -> "Entry | None":
    for e in registry() if entries is None else entries:
        if e.script == script and e.pattern.search(line):
            return e
    return None


def unregistered(script: str, text: str, entries=None) -> "list[tuple[str, int]]":
    """Distinct ERROR lines no entry matches: (first such line, how many lines of that
    shape - digits folded), in order of first appearance."""
    out: dict[str, list] = {}
    for line in error_lines(script, text):
        if known(script, line, entries) is not None:
            continue
        body = line[_MARK[script].search(line).start():]
        shape = _NUM.sub("#", body)[:160]
        if shape in out:
            out[shape][1] += 1
        else:
            out[shape] = [line[:QUOTE], 1]
    return [(first, n) for first, n in out.values()]


def recovered_kinds(script: str, text: str, entries=None) -> "list[tuple[Entry, str, int]]":
    """The `recovered` entries this log's ERROR lines matched: (entry, its first line, how
    many lines), in order of first appearance."""
    out: dict[int, list] = {}
    for line in error_lines(script, text):
        e = known(script, line, entries)
        if e is None or e.kind != "recovered":
            continue
        if id(e) in out:
            out[id(e)][2] += 1
        else:
            out[id(e)] = [e, line[:QUOTE], 1]
    return [tuple(v) for v in out.values()]


def check_round(eng, rec) -> "list[tuple[str, int]]":
    """Push the unregistered ERROR lines of a round AUTO-MAS booked as a success.

    One WARNING per round, titled and worded for him (texts.gamelog_unknown_errors),
    the raw lines to the technical log as one red item. Lines of `recovered` entries:
    one WARNING marked recovered per round (red item, not pushed); `not-a-fault`
    entries: nothing. Returns what was unregistered.
    Never raises: a log that cannot be read is said (a WARNING), never taken as clean."""
    from ark_relay.core import statestore as techlog, texts  # noqa: PLC0415
    from ark_relay.core.config import GAME_ZH  # noqa: PLC0415
    from ark_relay.features import errwatch  # noqa: PLC0415
    script = getattr(rec, "script", "")
    if script not in _MARK or not getattr(rec, "log_path", None):
        return []
    try:
        text = Path(rec.log_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _log_gamelog_errors.warning("%s %s 的日志读不了（%s），这一趟日志里的报错没查", script, rec.run_id, type(exc).__name__)
        return []
    if healed := recovered_kinds(script, text):
        # Each kind the program got past by itself in this round: one red item per round.
        # The first line is what the daily report quotes (plain words, one kind per game);
        # the run and the raw lines follow for us.
        _log_gamelog_errors.warning("%s那一趟跑成功了，日志里有 %d 种报错是程序自己恢复过来的\n%s %s: %s",
                    GAME_ZH.get(script, script), len(healed), script, rec.run_id,
                    "; ".join(f"{line} ({n} lines, line {e.line_no} of {REGISTRY.name})" for e, line, n in healed[:8]),
                    extra=errwatch.recovered())
    found = unregistered(script, text)
    if not found:
        return []
    from datetime import datetime  # noqa: PLC0415
    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
    game = GAME_ZH.get(script, script)
    started = getattr(rec, "started", None)
    at = started.strftime("%H:%M") if started else ""
    day = (started or datetime.now(tz=SERVER_TZ)).strftime("%Y-%m-%d")
    shown = "；".join(f"{line}（{n} 行）" for line, n in found[:8])
    techlog.add_red(day, "游戏日志里没登记的报错",
                    [f"{script} {rec.run_id}：{len(found)} 种没登记的报错：{shown}"],
                    state_dir=getattr(eng.cfg, "state_dir", None))
    _log_gamelog_errors.warning("%s %s 跑成功了，日志里有 %d 种没登记的报错：%s", script, rec.run_id, len(found), shown,
                extra=errwatch.alarm(texts.gamelog_unknown_errors(game),
                                     texts.gamelog_unknown_errors_body(game, at, len(found))))
    return found


log = logging.getLogger("ark.outcome")


@dataclass
class Check:
    """One verification result. `ok=False` gets reported."""

    label: str          # plain language, goes straight into the notification
    ok: bool
    detail: str = ""    # why it was judged this way, for troubleshooting
    # "" = a task that did or did not do its job; SETTINGS = the run went by defaults
    # because a new version reset the user's settings (failed, but not 「没干成」);
    # SKIPPED = the task's own schedule says not today (passed, but not 「干成的」);
    # SATISFIED = essence target mode found the ticked weapons' essences already
    # owned and stopped without farming (passed, but not 「干成的」 either);
    # RETRY = a gathering route that gathered nothing and is handed to the per-route
    # retry before power-off, whose outcome decides the group alarm (not 「干成的」).
    kind: str = ""


SETTINGS = "settings"
SKIPPED = "skipped"
SATISFIED = "satisfied"
RETRY = "retry"


_OKWW_ZH_TO_EN = (
    ("每日任务已完成，开始传送并刷取", "Daily task completed, start teleport to farm "),
    ("每日任务已完成", "Daily Task Completed"),
    ("每周乐园任务已完成", "weekly garden already completed"),
    ("Garden task completed; limit reached", "乐园任务完成, 已达到上限"),
    ("进入战斗，控物状态：", "enter combat "),
    ("重新传送后行走搜索声骸成功", "farm echo walk find true after re-teleport"),
    ("行走搜索声骸成功", "farm echo walk find true"),
    ("梦魇巢穴：拾取后检测到战斗", "nightmare nest: combat detected after pick"),
    ("梦魇巢穴无法到达，跳过本次：", "nightmare nest unreachable, skip this run: "),
    ("战斗中已吸收声骸", "Captured echo during combat"),
    ("已打开残象探寻", "opened gray_book_boss"),
    ("开始走向奖励", "start walk_to_treasure"),
    ("体力已用尽", "used all stamina"),
    ("体力不足", "not enough stamina"),
    ("首领传送准备结果：", "teleport_to_boss prepared as "),
    ("梦魇巢穴任务失败", "NightmareNestTask Failed"),
    ("无法领取先约电台奖励", "can not battle pass"),
    ("请在大世界并在队伍中开始", "Please start in game world and in team"),
    ("传送到首领失败", "Teleport to boss failed"),
    ("找不到boss列表", "can't find gray_book_boss"),
    ("找不到前往挑战按钮", "can't find boss_proceed"),
    ("未进入战斗", "not in combat"),
    ("每日任务异常停止", "Daily Task exception stopped"),
    ("等待游戏启动错误", "waiting for game to start error"),
    ("游戏窗口未连接", "Game window is not connected"),
    ("当前游戏或模拟器不支持选择的截图方式!", "Selected capture method is not supported by the game or your system!"),
)


def normalize_okww_log(text: str) -> str:
    """Restore zh_CN OK-WW log lines to their canonical upstream strings.

    First every whole message the machine's own catalogs translate (okww_i18n: OK-WW's ok.po and
    ok-script's zh_CN.ts), so an upgrade that translates more strings needs no change here; then
    the hand-written pairs above, for what the catalogs do not hold (pieces of longer messages,
    strings from elsewhere). A catalog that cannot be read leaves the text to the pairs alone, and
    a line neither turns back keeps failing its check, which is pushed as before."""
    try:
        text = normalize(text)
    except Exception:  # see above: the pairs still apply and unmatched lines still alarm
        log.warning("OK-WW 翻译表读不出来，只用手写对照表", exc_info=True)
    for zh, en in _OKWW_ZH_TO_EN:
        text = text.replace(zh, en)
    return text


# Lines that mean a nest fight happened. Opening the book, teleporting and reading
# the list (「Box(已击败残象：0/48) is not complete」) do not count. Only the nest
# task's own lines: upstream v3.7.4 never logs click_team_challenge or
# wait_in_team_and_world (BaseWWTask.py:678-683, :1115-1117 have no log call), and
# 「echo captured」 is only a reason stored without a log line (NightmareNestTask.py:74,
# CombatCheck.py:58-61). Those words appeared only in traceback frames of other
# tasks' errors (tests/fixtures/m6-okww/0921-weekly.log:27-28), which booked an
# unreachable nest as fought.
_NEST_ENGAGED = re.compile(r"NightmareNestTask:(enter combat|farm echo walk|nightmare nest: combat detected)")
# Printed by our patch when every chosen nest is at its cap (a normal skip).
_NEST_ALL_FULL = "指定点位都已打满，跳过"
# The overrides log the nest filter they applied; every nest entered is clicked
# through its count box:
#   NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）
#   NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2
_NEST_FILTER_LINE = re.compile(r"nightmare nest: 只刷 \[")
_NEST_CLICK = re.compile(r"left_click 已击败残象[：:]\s*\d+/(\d+)")
# The overlay's combat_nest names the nest it clicks, as OCR read it beside the count
# (ark_overrides NEST_NAME_LINE; 「?」 when no name was read):
#   NightmareNestTask:nightmare nest: nest name: 落渊南丘残象聚落
_NEST_NAME = re.compile(r"nightmare nest: nest name: ([^\n]*)")
_NEST_NOT_FOUND = "列表里没找到指定的点位"
# Upstream's line when travel to a nest did not happen (NightmareNestTask
# _travel_to_nest_or_skip), e.g. 「nightmare nest unreachable, skip this run: go_nest:48:18」.
_NEST_UNREACHABLE = re.compile(r"nightmare nest unreachable")
# The overrides' line when a nest's travel failed a second time in the run (ark_overrides
# NEST_GAVE_UP_LINE; the first failure is retried at once):
#   NightmareNestTask:nightmare nest: 传送两次都不过去，这一轮不打了 go_nest:48:18（梦枢天罗残象聚落）
_NEST_GAVE_UP = re.compile(r"nightmare nest: 传送两次都不过去，这一轮不打了 \S+（([^）\n]*)）")
# The overrides' line when find_nest could not be installed at all: no nests this run
# rather than upstream's 「every nest that reads 0」 (ark_overrides.tasks.py, NightmareNestTask.run).
_NEST_FILTER_MISSING = "只刷指定点位的改动没装上，这一轮不刷巢穴"
# The overrides' find_nest when a wanted nest's name was read and its count was not
# (NEST_COUNT_UNREAD there): stopped on that page, with screenshot nest_count_unread.
_NEST_COUNT_UNREAD = "指定点位的名字读到了，计数没读到"
# The overrides' line when find_nest went in adapted to a changed upstream body
# (NEST_ADAPTED there): installed, but not checked against the new body by us.
_NEST_ADAPTED = "只刷指定点位的过滤是按 OK-WW 新版适配装上的"
# Marker that DailyTask finished (printed by upstream itself).
_DAILY_DONE = "Daily Task Completed"
# Stamina is farmed by TacetTask, ForgeryTask or SimulationTask (upstream v3.7.4
# DailyTask.py:117-128; the last two are DomainTask subclasses, and the log prefix is
# the instance's class). Only their own lines count: 「enter combat」 is CombatCheck.py:181
# and 「start walk_to_treasure」 BaseWWTask.py:606, logged by every fighting task, and
# the weekly boss and the nest run before stamina farming.
_STAMINA_TASK = r"(?:TacetTask|ForgeryTask|SimulationTask):"
# A stamina fight happened.
_STAMINA_SPENT = re.compile(_STAMINA_TASK + r"(?:enter combat|start walk_to_treasure)")
# Nothing (more) to farm: TacetTask.py:105 (not_enough_stamina, logged when the total
# is under one run) and DomainTask.py:63 / :106.
_STAMINA_SHORT = re.compile(_STAMINA_TASK + r"(?:used all stamina|not enough stamina)")
_BOSS_FAILED = re.compile(_STAMINA_TASK + r"强敌领奖：(出错，[^\n]*|培养目标不是[^\n]*|设置读不出[^\n]*|已经打了[^\n]*)")
_BOSS_FULL = re.compile(_STAMINA_TASK + r"强敌领奖：(\S+?)的(\S+?)已经够了（([^）\n]*)）")
_BOSS_SHORT = re.compile(_STAMINA_TASK + r"强敌领奖：体力 -?\d+ \+ 备用 -?\d+ 不够领一次")
# Three revives and upstream stops farming and returns quietly: TacetTask.py:79,
# DomainTask.py:73 (FarmEchoTask's own 「farm 4c: …」 is not stamina farming).
_STAMINA_DIED = re.compile(_STAMINA_TASK + r"farm_(?:tacet|domain): exceeded recovery retries \((\d+)\)")
# A stamina reading. Our get_stamina override logs 「…按没读到处理（-1）…」 and returns -1
# when 数/数 could not be read (okww_files/ark_overrides.tasks.py _read_stamina);
# upstream then compares -1 with one run's cost and says 「used all stamina」 /
# 「not enough stamina」 though nothing was read (TacetTask.py:61-66, DomainTask.py:61-63).
# A real reading is logged by info_set (BaseWWTask.py:422; -1 does not match).
_STAMINA_READ = re.compile(_STAMINA_TASK + r"(?:[^\n]*(按没读到处理（-1）)|info_set current_stamina \d)")
STAMINA_UNREAD_SAY = "体力读不出来，没刷"
# The 「不刷体力」 flag file was there: the overlay's farm hook logs this line and
# returns without farming (okww_files/ark_overrides.tasks.py, _farm_hook). Only the
# line's start is matched: the rest names the file, a word the texts gate keeps out
# of the relay's literals; no other overlay line starts this way.
_STAMINA_FLAGGED = re.compile(_STAMINA_TASK + r"刷体力已禁用（")
STAMINA_FLAG_SAY = "不刷体力的标记还在"


# The activity points read after open_daily opens the dailies page. A first reading
# already >= 100 means the dailies were finished before this run started, and OK-WW
# only claims the rewards.
_DAILY_POINTS = re.compile(r"info_set total daily points (\d+)")
# open_daily's reading of the 180-waveplate daily task (upstream DailyTask.py:225-233).
# Upstream farms only while it is under 180 and the points are under 100 (:88-89);
# at 180 it skips the farm with no line of its own (:117-128).
_DAILY_PROGRESS = re.compile(r"DailyTask:info_set current daily progress (\d+)")
# The overlay's claim_daily then farms what upstream skipped (「刷到空」), saying so
# first, and logs an error line when that farm raised (okww_files/ark_overrides.tasks.py
# claim_daily_after_farm).
_LEFTOVER_FARM = re.compile(r"DailyTask:(上游这趟不刷体力（[^）\n]*）)")
_LEFTOVER_FAILED = re.compile(r"DailyTask:补刷体力出错，照常领日常奖励: ([^\n]*)")
# Full value of the daily activity meter; the reading can go above it.
_DAILY_POINTS_TARGET = 100

# The overlay's daily-chest lines (okww_files/ark_overrides.tasks.py DAILY_*): every
# chest up to the points is clicked and checked for the claimed tick. A chest not
# claimed is an item undone; so are points under 100, saying only the score
# (docs/NOTIFICATIONS.md, 「⚠️ 这一轮没干完」).
_DAILY_REWARD_POINTS = re.compile(r"活跃奖励：活跃度 (\d+)")
_DAILY_REWARD_FAILED = re.compile(r"活跃奖励没领到：(.+)")
_DAILY_REWARD_OK = "活跃奖励：领完核对通过"
_DAILY_REWARD_UNCHECKED = re.compile(r"活跃奖励：没有核对，(.+)")

_BATTLE_PASS_OK = "战令：页面打开了，点了领取（等级 "
_BATTLE_PASS_RETRY = "战令：第一次没打开，回大世界再开一次"
_BATTLE_PASS_FAILED = "战令没领到："
_BATTLE_PASS_UNCHECKED = "战令：没有重试，"
# upstream's 「can not battle pass, maybe ended」
_BATTLE_PASS_UPSTREAM_FAILED = "can not battle pass"
_BATTLE_PASS_CLOSED = "暂未开播"

# ── weekly boss claims ──
# 「周本领奖：已点确认」 is logged right after the click and proves nothing on its
# own. A claim counts only when the overlay re-reads the game's weekly counter and
# logs one of the three read-back lines (written verbatim by the overlay).
WEEKLY_CLICKED = "周本领奖：已点确认"
WEEKLY_CLAIM_OK = re.compile(r"周本领奖：回读确认领到，本周剩余 (\d+)/3→(\d+)/3")
WEEKLY_CLAIM_SAME = re.compile(r"周本领奖：回读次数没变（(\d+)/3），这次没领到")
WEEKLY_CLAIM_UNREAD = "周本领奖：回读没读到本周剩余次数"
# The pre-entry reading, e.g. 「本周剩余可收取次数：2/3」 inside 周本本周剩余次数原文.
WEEKLY_READ = re.compile(r"本周剩余可收取次数[：:]\s*(\d+)\s*[/／]\s*(\d+)")
# The overlay's end-as-failed mark (okww_files/ark_overrides.tasks.py FAILED_MARK)
# and the line it starts.
FAILED_MARK = "这一趟按失败结束："
_WEEKLY_FAILED = re.compile(FAILED_MARK + r"(.+)")
_SCREEN_DUMP = re.compile(r"[。，,；;\s]*整屏读到.*$", re.S)


def without_screen_dump(reason: str) -> str:
    """`reason` without the overlay's trailing 「整屏读到 …」 OCR dump."""
    return _SCREEN_DUMP.sub("", reason).strip()
# The overlay's waveplate-shortage skip lines (current and old wording); both
# overlay paths log one before ending the run. Also read by
# collector_okww._okww_steps.
WEEKLY_SHORT = re.compile(r"波片不足挡住开启挑战|结晶波片不足，取消并跳过本次周本")
WEEKLY_SHORT_SAY = "周本奖励没领：结晶波片不足"
# A weekly fight happened. 「teleport_to_boss prepared as」 is only the landing and
# 「周本领奖：打完了」 can be logged without a fight; a real fight logs upstream's
# 「FarmEchoTask:enter combat」, and the claim dialog appears only after a won fight.
_WEEKLY_FOUGHT = re.compile(r"FarmEchoTask:enter combat|周本领奖：认出弹窗|周本领奖：回读确认领到")
_ADDITIONAL_FAILED = re.compile(r"附加任务出错[^:：\n]*[:：][ \t]*(.*)")
_TRACEBACK_TAIL = re.compile(r"\s*Traceback \(most recent call last\):.*$")


# An OK-WW log also holds other loggers' lines (pyappify-update prints its whole
# changelog after an update; MainThread, ok.core.start_controller, RefreshAdb), which
# can contain the words the checks look for. The run checks read only the task
# executor's lines: 「YYYY-MM-DD HH:MM:SS,mmm LEVEL TaskExecutor msg」. A bare
# 「TaskName:msg」 line (no timestamp, no level) is kept too; the tests use that form.
_OKWW_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \w+ (\S+)")


def _task_lines(text: str) -> str:
    """Keep only the task executor's own lines of an OK-WW run log.

    Drops every line of a logger other than TaskExecutor. Idempotent.
    """
    kept = [line for line in normalize_okww_log(text).splitlines()
            if (m := _OKWW_LINE.match(line)) is None or m.group(1) == "TaskExecutor"]
    return "\n".join(kept)


def weekly_claims(text: str) -> dict:
    """Count the weekly claim attempts of one log by what the read-back said.

    verified: the counter dropped. unchanged: it did not. unread: the read-back
    failed. no_readback: a click with no read-back line at all (logs from before
    the read-back existed). attempted: clicks, or read-backs if more.
    """
    verified = len(WEEKLY_CLAIM_OK.findall(text))
    unchanged = len(WEEKLY_CLAIM_SAME.findall(text))
    unread = text.count(WEEKLY_CLAIM_UNREAD)
    clicked = text.count(WEEKLY_CLICKED)
    attempted = max(clicked, verified + unchanged + unread)
    return {"verified": verified, "unchanged": unchanged, "unread": unread,
            "no_readback": attempted - verified - unchanged - unread,
            "attempted": attempted}


def weekly_left(text: str) -> "int | None":
    """Claims left this week: the newest reading of the game's own counter in the log.

    Readings are the pre-entry OCR and the read-back after a claim (its 「after」, or
    the unchanged count). A click without a read-back changes nothing here, so an
    old log keeps its pre-entry number; the 0/3 gate on the next entry catches an
    overshoot. None when the log has no reading at all.
    """
    found = [(m.start(), int(m.group(1))) for m in WEEKLY_READ.finditer(text)]
    found += [(m.start(), int(m.group(2))) for m in WEEKLY_CLAIM_OK.finditer(text)]
    found += [(m.start(), int(m.group(1))) for m in WEEKLY_CLAIM_SAME.finditer(text)]
    if not found:
        return None
    return max(max(found)[1], 0)


def weekly_unverified(c: dict) -> str:
    """The claim attempts that are not a confirmed claim, in words; "" when none."""
    parts = []
    if c["no_readback"]:
        parts.append(f"点了确认 {c['no_readback']} 次、领完没再读次数，没核实领到")
    if c["unchanged"]:
        parts.append(f"领完再读次数没变 {c['unchanged']} 次，没领到")
    if c["unread"]:
        parts.append(f"领完再读没读到剩余次数 {c['unread']} 次，没核实领到")
    return "；".join(parts)


def latest_okww_run_log(history_dir) -> "tuple[Path, str] | None":
    """(path, text) of the newest OK-WW run log AUTO-MAS kept, looking back a week. None when there is none."""
    hist = Path(history_dir)
    if not hist.is_dir():
        return None
    days = sorted((d for d in hist.iterdir() if d.is_dir()), reverse=True)[:7]
    logs = [f for d in days for f in d.rglob("OK-WW-*.log")]
    from ark_relay.core.collector import _db_rows  # noqa: PLC0415 - collector imports this module
    week = {d.name for d in days}
    for rid, _t, date_s, _u, script_name, _m, _d, log_rel in _db_rows(hist):
        if str(script_name).startswith("OK-WW") and str(date_s) in week:
            if (f := hist / (log_rel or f"{date_s}/{rid}/0.log")).is_file():
                logs.append(f)
    if not logs:
        return None
    newest = max(logs, key=lambda f: f.stat().st_mtime)
    return newest, newest.read_text(encoding="utf-8", errors="replace")


_PATCH_EFFECTS = (
    ("周本改动在跑（进本前读剩余次数）",
     r"FarmEchoTask:left_click boss_proceed",
     r"周本本周剩余次数原文: .*次数[^0-9]{0,6}\d\s*[/／]\s*3", "周本任务点了「前往」"),
    # Triggered only by a real fight (see _WEEKLY_FOUGHT): a 0/3 or short-on-waveplates
    # skip never reaches the crystal, so it has nothing to claim. Done means the
    # read-back confirmed a claim, or the game said this week is already capped.
    ("周本领奖改动在跑（打完按 F 领奖）",
     r"(?s)Teleport to Boss Weekly Challenge.*FarmEchoTask:enter combat",
     r"周本领奖：回读确认领到|收取物资次数已达到上限", "周本打了一场"),
    ("巢穴改动在跑（只刷指定点位）",
     r"NightmareNestTask:opened gray_book_boss", r"nightmare nest: 只刷 \[", "巢穴任务打开了残象聚落页"),
    ("巢穴进点位留图在跑（点进点位前截图）",
     r"NightmareNestTask:(farm echo walk find true|Captured echo during combat|nightmare nest unreachable)",
     r"nightmare nest: 点进点位", "巢穴任务进了点位"),
    ("巢穴传送不过去留图在跑（传送前后截图）",
     r"NightmareNestTask:nightmare nest unreachable", r"nightmare nest: 传送不过去", "巢穴传送不过去"),
    ("日常改动在跑（附加任务提到刷体力之前）",
     r"NightmareNestTask:opened gray_book_boss", r"TacetTask:info_set current_stamina|ForgeryTask:info_set current_stamina|SimulationTask:info_set current_stamina", "巢穴任务先跑、刷体力后跑"),
    ("刷到空改动在跑（上游不刷时补刷体力）",
     r"DailyTask:info_set current daily progress 180\b", r"上游这趟不刷体力", "日常读到已用 180/180"),
    ("体力读数改动在跑（读字原文进日志）",
     r"(Tacet|Forgery|Simulation)Task:info_set current_stamina", r"体力读字原文", "读了体力"),
    # Upstream's own first line of claim_battle_pass, which our copy keeps; the
    # effect is our line after the page opened (its retry included).
    ("战令改动在跑（没打开时同一趟再开一次）",
     r"(?m)DailyTask:battle pass\s*$", r"战令：页面打开了，点了领取", "日常走到了领战令"),
)


# Which override each effect check vouches for. test_okww_overlay_copies refuses
# an @override that is neither here nor in BEHAVIOUR_TESTS - that is the gate
# against 「贴了补丁，实际没运行」 recurring: every binding must come with a way to see it ran.
PATCH_COVERAGE = {
    "FarmEchoTask.click_configured_boss_level": "周本改动在跑（进本前读剩余次数）",
    "FarmEchoTask.incr_drop": "周本领奖改动在跑（打完按 F 领奖）",
    "FarmEchoTask.handle_claim_button": "周本领奖改动在跑（打完按 F 领奖）",
    "NightmareNestTask.find_nest": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.run": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.run_capture_mode": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.get_nest_to_go": "巢穴改动在跑（只刷指定点位）",
    "NightmareNestTask.combat_nest": "巢穴进点位留图在跑（点进点位前截图）",
    "NightmareNestTask._travel_to_nest_or_skip": "巢穴传送不过去留图在跑（传送前后截图）",
    "DailyTask.run": "日常改动在跑（附加任务提到刷体力之前）",
    "DailyTask.open_daily": "日常改动在跑（附加任务提到刷体力之前）",
    "DailyTask.run_additional_tasks": "日常改动在跑（附加任务提到刷体力之前）",
    "DailyTask.claim_daily": "刷到空改动在跑（上游不刷时补刷体力）",
    "TacetTask.use_stamina": "无音区改动在跑（结算页留图）",
    "BaseWWTask.get_stamina": "体力读数改动在跑（读字原文进日志）",
    "DailyTask.claim_battle_pass": "战令改动在跑（没打开时同一趟再开一次）",
}
# Overrides whose path has no upstream line to check against in a run log (a death
# in the realm, three failed laps, a late teleport screen...). Each is pinned by a
# behaviour test instead: the file named here drives that method with a fake task.
# The gate checks the file exists and names the method.
BEHAVIOUR_TESTS = {
    "FarmEchoTask.combat_once": "test_okww.py",
    "FarmEchoTask.click_team_challenge": "test_okww.py",
    "FarmEchoTask.click_solo_challenge": "test_okww.py",
    "BaseWWTask.click_on_book_target": "test_okww.py",
    "FarmEchoTask.teleport_to_configured_boss": "test_okww.py",
    "FarmEchoTask.teleport_to_configured_boss_and_prepare": "test_okww.py",
    "FarmEchoTask.run": "test_okww.py",
    "TacetTask.farm_tacet": "test_okww.py",
    "ForgeryTask.farm_forgery": "test_okww.py",
    "SimulationTask.farm_simulation": "test_okww.py",
    "DailyTask.get_total_daily_points": "test_okww.py",
}


def patch_effect_checks(text: str, tacet_shot_today: bool | None = None) -> list[Check]:
    """Did each override actually run where its trigger appeared? Empty entries for paths not triggered."""
    text = normalize_okww_log(text)
    out: list[Check] = []
    for label, trig, effect, what in _PATCH_EFFECTS:
        if not re.search(trig, text):
            continue
        if label.startswith("日常改动"):
            t = re.search(trig, text); e = re.search(effect, text)
            ok = bool(t and e and t.start() < e.start())
            out.append(Check(label, ok, "" if ok else f"{what}——日志里刷体力出现在巢穴之前，或根本没有一方"))
            continue
        ok = bool(re.search(effect, text))
        out.append(Check(label, ok, "" if ok else f"{what}，但日志里没有我们那句做成了的话：改动没跑到或没做成"))
    if tacet_shot_today is not None and re.search(r"TacetTask:info_set current_stamina", text):
        out.append(Check("无音区改动在跑（结算页留图）", tacet_shot_today,
                         "" if tacet_shot_today else "今天刷了无音区，screenshots 里却没有今天的 tacet_drops 图"))
    return out


_MAA_SANITY = re.compile(r"analyze_sanity_remain Current Sanity: (\d+) , Max Sanity: (\d+)")
_MAA_COST = re.compile(r'"sanity_cost":(\d+),"series":\d+,"times_finished":(\d+)')


def maa_annihilation_no_proxy(text: str) -> bool:
    """Whether this run's annihilation stopped at a locked auto-deploy (MAA's
    Annihilation@UnableToAgent template, asst.log 2026-10-26 09:02:39)."""
    return "Annihilation@UnableToAgent" in _one_run_only(text)


def maa_sanity_short(text: str) -> "dict | None":
    """{'have': 17, 'cost': 25} when the Fight chain never ran because sanity was below the cost; else None.
    """
    text = _one_run_only(text)
    have = [int(m.group(1)) for m in _MAA_SANITY.finditer(text)]
    costs = [(int(m.group(1)), int(m.group(2))) for m in _MAA_COST.finditer(text)]
    if not have or not costs:
        return None
    cost, done = costs[-1]
    if done == 0 and have[-1] < cost:
        return {"have": have[-1], "cost": cost}
    return None


def nest_filter_checks(text: str, only_nest: str) -> list[Check]:
    """Did the run honour 「only these nests」? Empty when no filter is configured.

    Facts from lines the run itself writes: the overrides announce the filter they
    loaded (no announcement = the filter code never had a name to work with); each
    nest entered is clicked through its 「已击败残象 N/D」 box, so more different
    denominators than names asked for mean a nest outside the setting; and the
    overlay names each nest it enters (「nightmare nest: nest name: …」, 「?」 when
    unread). Both rules must pass. The names alone cannot go red while the filter
    works - the overlay only clicks a row next to a wanted name and logs that name -
    so the cap rule stays: it is what catches a click on the neighbouring row.
    """
    text = _task_lines(text)
    if not (only_nest or "").strip() or "NightmareNestTask" not in text:
        return []
    out: list[Check] = []
    announced = bool(_NEST_FILTER_LINE.search(text))
    denoms = list(dict.fromkeys(_NEST_CLICK.findall(text)))
    if announced:
        why = ""
    else:
        # Say what the log shows: nests entered, or entered and unreachable.
        entered = (f"进了 {len(denoms)} 个点位（计数上限 {'、'.join(denoms)}）" if denoms
                   else "一个点位都没进")
        if denoms and len(_NEST_UNREACHABLE.findall(text)) >= len(denoms):
            entered = f"点了 {len(denoms)} 个点位，都没传送过去，一个都没刷"
        why = f"日志里没有「nightmare nest: 只刷 […]」这一行，只刷{only_nest}的过滤没生效；这一趟{entered}"
    out.append(Check("残象聚落只刷指定点位（过滤生效）", announced, why))
    if len(denoms) <= 1 and not _NEST_ENGAGED.search(text):
        return out      # nothing was fought, so 「没进别的点位」 says nothing worth a green line
    names = [n.strip() for n in re.split(r"[,，]", only_nest) if n.strip()]
    problems = []
    if len(denoms) > max(1, len(names)):
        problems.append(f"这一趟进了 {len(denoms)} 个不同的点位（计数上限 {'、'.join(denoms)}）")
    clicks = _nest_clicks(text)
    outside = list(dict.fromkeys(n for _d, n in clicks if n and not any(w in n for w in names)))
    if outside:
        problems.append(f"进了设置以外的点位：{'、'.join(outside)}")
    # One wanted name read beside two different caps: one of those clicks was on
    # another row (nests sharing a cap cannot be told apart by the cap alone).
    for w in names:
        caps = list(dict.fromkeys(d for d, n in clicks if n and w in n))
        if len(caps) > 1:
            problems.append(f"「{w}」这个名字点进了 {len(caps)} 个计数上限不同的点位（{'、'.join(caps)}），有一次点到了别的行")
    out.append(Check("残象聚落没进别的点位", not problems,
                     "" if not problems else "；".join(problems) + f"，设置是只刷{only_nest}"))
    return out


def _nest_clicks(text: str) -> "list[tuple[str, str]]":
    """(denominator, name or '') for each nest click, in order.

    The overlay logs the name in combat_nest just before upstream clicks the count
    box (10-13 log: 「点进点位 go_nest:48:18」 then the left_click 0.2 s later), so a
    name line goes with the click right after it; a name line with no click after it
    goes with an unnamed click right before it. 「?」 is no name.
    """
    events = sorted([(m.start(), "click", m.group(1)) for m in _NEST_CLICK.finditer(text)]
                    + [(m.start(), "name", m.group(1).strip()) for m in _NEST_NAME.finditer(text)])
    clicks: list = []        # [denominator, name]
    pending = ""
    for _pos, kind, val in events:
        if kind == "click":
            clicks.append([val, pending])
            pending = ""
            continue
        name = "" if val in ("", "?") else val
        if pending == "" and clicks and clicks[-1][1] == "" and _next_is_not_click(events, _pos):
            clicks[-1][1] = name
        else:
            pending = name
    return [(d, n) for d, n in clicks]


def _next_is_not_click(events: list, pos: int) -> bool:
    later = [k for p, k, _v in events if p > pos]
    return not later or later[0] != "click"


def daily_reward_checks(text: str) -> list[Check]:
    """The daily activity chests and points, from the overlay's lines (none: nothing said)."""
    out: list[Check] = []
    if failed := _DAILY_REWARD_FAILED.findall(text):
        out.append(Check("每日活跃奖励领到了", False, failed[-1].strip()))
    elif unchecked := _DAILY_REWARD_UNCHECKED.findall(text):
        out.append(Check("每日活跃奖励领到了", False, "领完没有核对：" + unchecked[-1].strip()))
    elif _DAILY_REWARD_OK in text:
        out.append(Check("每日活跃奖励领到了", True, ""))
    if points := _DAILY_REWARD_POINTS.findall(text):
        n = int(points[-1])
        full = n >= _DAILY_POINTS_TARGET
        out.append(Check("每日活跃满 100", full, "" if full else f"今天活跃 {n} 分，没满 100"))
    return out


def battle_pass_checks(text: str) -> list[Check]:
    """The battle-pass claim, from the overlay's lines or upstream's own (none: step not reached).

    Not owed (SKIPPED) when the overlay's last miss shows the game's between-seasons notice.
    Red when the page did not open after the overlay's second try, or when upstream's
    「can not battle pass」 is there (a run without the overlay, or our fallback to
    upstream's body). The overlay logs that sentence too on its final miss, so it is
    read only after the overlay's own lines."""
    text = normalize_okww_log(text)
    if _BATTLE_PASS_FAILED in text:
        last = [ln for ln in text.splitlines() if _BATTLE_PASS_FAILED in ln][-1]
        if _BATTLE_PASS_CLOSED in last:
            return [Check(texts.OKWW_BATTLE_PASS_CLOSED, True, kind=SKIPPED)]
        return [Check(texts.OKWW_BATTLE_PASS_LABEL, False, texts.OKWW_BATTLE_PASS_FAILED)]
    if _BATTLE_PASS_UPSTREAM_FAILED in text:
        return [Check(texts.OKWW_BATTLE_PASS_LABEL, False, texts.OKWW_BATTLE_PASS_UNCLAIMED)]
    if _BATTLE_PASS_OK in text:
        return [Check(texts.OKWW_BATTLE_PASS_LABEL, True,
                      texts.OKWW_BATTLE_PASS_RETRIED if _BATTLE_PASS_RETRY in text else "")]
    if _BATTLE_PASS_UNCHECKED in text:
        return [Check(texts.OKWW_BATTLE_PASS_LABEL, True, texts.OKWW_BATTLE_PASS_UNCHECKED)]
    return []


# nest_state() keys -> the verdict's (label, ok, detail). collector_okww._nest_step
# maps the same keys to the daily report's step text.
_NEST_VERDICT = {
    # Not farming the other nests is right when the filter is gone, but the nest he
    # asked for was not farmed either: that is a failure and goes to the group now.
    # The boot drift line alone can arrive only at the next relay boot (a refused
    # find_nest), i.e. after the run.
    "filter_missing": ("残象聚落", False, "只刷指定点位的补丁没贴上，这一轮没刷巢穴（没去乱刷别的点位）"),
    "not_found": ("残象聚落", False, "配置里的点位名在游戏列表里没找到，请核对配置里的名字和游戏里的写法"),
    "count_unread": ("残象聚落", False, "列表里指定点位的计数没读到，停下没刷（截图 nest_count_unread）"),
    "full": ("残象聚落（已满，跳过）", True, "指定点位都打满了"),
    "fought": ("残象聚落", True, "有进本/战斗记录"),
    "partly": ("残象聚落", False, "有一处点位传送两次都不过去，那一处没打"),
    "unreachable": ("残象聚落", False, "点了点位，但传送不过去，一次没打"),
    "failed": ("残象聚落", False, "任务中途出错退出，一次没打"),
    "quit": ("残象聚落", False, "任务起来了，但既没打、也没说点位已满——开了界面就原地退出了"),
    "not_run": ("残象聚落", False, "这一轮根本没跑到这个任务"),
}


def nests_given_up(text: str) -> list[str]:
    """Names of the nests given up after two failed travels in one OK-WW run log, in order."""
    return list(dict.fromkeys(m.group(1) for m in _NEST_GAVE_UP.finditer(_task_lines(text))))


def nest_state(text: str) -> str:
    """What the nightmare-nest task did in one OK-WW run log, as one key of _NEST_VERDICT.

    The one classifier behind both the run's verdict (okww_checks) and the daily
    report's step (collector_okww._nest_step), so the two cannot disagree. Reads only
    the task executor's lines (_task_lines), whatever text it is given.
    """
    text = _task_lines(text)
    engaged = bool(_NEST_ENGAGED.search(text))
    if _NEST_FILTER_MISSING in text:
        return "filter_missing"
    if _NEST_NOT_FOUND in text:
        return "not_found"
    if _NEST_COUNT_UNREAD in text and not engaged:
        return "count_unread"
    if _NEST_GAVE_UP.search(text):
        return "partly" if engaged else "unreachable"
    if engaged:
        return "fought"
    if _NEST_ALL_FULL in text:
        return "full"
    if _NEST_UNREACHABLE.search(text):
        return "unreachable"
    if "NightmareNestTask Failed" in text:
        return "failed"
    if "NightmareNestTask" in text:
        return "quit"
    return "not_run"


def stamina_failure(text: str) -> str:
    """Why stamina farming failed in one OK-WW run log, or "" when no known failure.

    Read by okww_checks (the 刷体力 item) and collector_okww._okww_progress (why it
    stopped), so the two say the same. Three failures:
      - the 「不刷体力」 flag file was there and nothing was farmed (_STAMINA_FLAGGED);
      - upstream gave up after three revives (_STAMINA_DIED);
      - the stamina task stopped right after a reading our override could not make
        (-1), with no stamina fight at all: its 「used all stamina」 / 「not enough
        stamina」 was judged on nothing. A -1 followed by a real reading (TacetTask's
        click and second read, TacetTask.py:63-64) is a real reading.
    """
    text = _task_lines(text)
    if _STAMINA_FLAGGED.search(text):
        return STAMINA_FLAG_SAY
    if m := _BOSS_FAILED.search(text):
        return "刷培养目标的突破材料没刷完：" + without_screen_dump(m.group(1))[:160]
    if m := _STAMINA_DIED.search(text):
        return f"刷体力时角色死了 {m.group(1)} 次，OK-WW 停止刷体力，体力没刷完"
    if _STAMINA_SPENT.search(text):
        return ""
    reads = list(_STAMINA_READ.finditer(text))
    for stop in _STAMINA_SHORT.finditer(text):
        last = [r for r in reads if r.start() < stop.start()]
        if last and last[-1].group(1):
            return STAMINA_UNREAD_SAY
    return ""


def okww_checks(text: str, *, expect_nest: bool, expect_daily: bool = True,
                expect_stamina: bool = True, only_nest: str = "") -> list[Check]:
    """Verify one OK-WW run. `text` is the full log of that run.

    `expect_nest` comes from DailyTask.json by upstream's own rule
    (gamelogs._okww_nest_expected: 「Auto Farm all Nightmare Nest」 ticked, or the
    daily-echo option on with a farm target other than Tacet Suppression); the
    nest filter only narrows a run that happens.
    `only_nest` is the configured 「Only Farm These Nests」 value; when set, the run
    must show the filter was active and must not have walked into other nests.
    """
    text = _task_lines(text)
    out: list[Check] = []
    out.extend(nest_filter_checks(text, only_nest))

    m = _DAILY_POINTS.search(text)
    dailies_done = bool(m and int(m.group(1)) >= _DAILY_POINTS_TARGET)
    if dailies_done:
        done = _DAILY_DONE in text
        out.append(Check("今日日常此前已完成，本轮仅领奖", done,
                         "" if done else "但连领奖收尾都没跑完"))
        expect_daily = expect_stamina = False
        expect_nest = expect_nest and "NightmareNestTask" in text

    if expect_daily:
        done = _DAILY_DONE in text
        out.append(Check("每日任务跑完", done,
                         "" if done else f"日志里没有「{_DAILY_DONE}」"))
    out.extend(daily_reward_checks(text))
    out.extend(battle_pass_checks(text))

    if expect_nest:
        label, ok, why = _NEST_VERDICT[nest_state(text)]
        if names := nests_given_up(text):
            why += f"（{'、'.join(names)}）"
        out.append(Check(label, ok, why))

    # The weekly boss passes only on a confirmed reward claim.
    if "Teleport to Boss Weekly Challenge" in text:
        c = weekly_claims(text)
        capped = "收取物资次数已达到上限" in text or bool(re.search(r"本周剩余可收取次数[：:]\s*0\s*/", text))
        stopped = _WEEKLY_FAILED.search(text)
        short = bool(WEEKLY_SHORT.search(text))
        ok_ = (c["verified"] > 0 or capped or "本周周本次数已领满" in text) and not (stopped or short)
        # 「info_set Teleport to Boss Weekly Challenge 0」 is logged before the book
        # is opened (the 0 is the boss's index). Getting in is 「teleport_to_boss
        # prepared as …」 (FarmEchoTask.py:240); fighting is _WEEKLY_FOUGHT.
        entered = "teleport_to_boss prepared as" in text
        fought = bool(_WEEKLY_FOUGHT.search(text))
        if ok_:
            out.append(Check("周本领到了奖励", True, ""))
        elif short:
            label = (f"周本（这一趟领到了 {c['verified']} 次，之后结晶波片不足，剩下的奖励没领）"
                     if c["verified"] else "周本（结晶波片不足，奖励没领）")
            out.append(Check(label, False, WEEKLY_SHORT_SAY))
        elif stopped:
            got = f"（这一趟领到了 {c['verified']} 次）" if c["verified"] else ""
            out.append(Check("周本领到了奖励", False, without_screen_dump(stopped.group(1)) + got))
        elif c["attempted"]:
            out.append(Check("周本领到了奖励", False,
                             weekly_unverified(c)))
        elif not entered:
            why = ("选了等级后没等到「开启挑战」" if re.search(r"找不到开启挑战|都没进开启挑战", text)
                   else "传送去 Boss 没成")
            out.append(Check("周本", False, f"没进本，一次没打：{why}"))
        elif not fought:
            out.append(Check("周本", False, "进了本，但日志里没有开打的记录：一次没打"))
        else:
            out.append(Check("周本领到了奖励", False, "周本打了，但没有领奖那一步：奖励没拿到"))

    if expect_stamina:
        if why := stamina_failure(text):
            out.append(Check("刷体力", False, why))
        elif _STAMINA_SPENT.search(text):
            out.append(Check("刷体力", True, ""))
        elif m := _BOSS_FULL.search(text):
            out.append(Check("刷体力", True, f"{m.group(1)}的{m.group(2)}已经够了（{m.group(3)}），"
                                            "体力先留着不刷（无音区关着，等定下一个刷什么）"))
        elif _STAMINA_SHORT.search(text) or _BOSS_SHORT.search(text):
            out.append(Check("刷体力", True, "体力不足，本来就没得刷"))
        else:
            out.append(Check("刷体力", False, _no_farm_reason(text)))

    out.extend(_ended_failed_checks(text, out))
    return out


def _no_farm_reason(text: str) -> str:
    """Why no stamina was farmed when the log shows neither a fight nor 「not enough」."""
    t = _task_lines(text)
    if m := _LEFTOVER_FARM.search(t):
        if e := _LEFTOVER_FAILED.search(t):
            return f"{m.group(1)}，中继按「刷到空」补刷时出错：{without_screen_dump(e.group(1))}"
        return f"{m.group(1)}，中继按「刷到空」补刷了，但既没进本，也没说体力不足"
    progress = [int(x) for x in _DAILY_PROGRESS.findall(t)]
    if progress and max(progress) >= 180:
        return (f"上游读到每日波片任务已到 {max(progress)}/180，按它自己的规矩不刷体力；"
                "中继「刷到空」的补刷没有跑到（日志里没有它那句）")
    return "既没进本，也没说体力不足"


def _ended_failed_checks(text: str, out: list[Check]) -> list[Check]:
    """A failed Check for every 「这一趟按失败结束：」 or 「附加任务出错」 line that no failed
    Check in `out` already reports.

    Whatever the branches above judged, a run whose log carries either line did not
    get its work done. On 10-12 the 11:41 hand-started run (OK-WW-07-41-07) had the
    dailies already done and a weekly stop, okww_checks returned after the dailies
    item, and the run was booked silently (relay log 11:49:23). This catch-all does
    not depend on any branch reaching its own check. A reason already in a failed
    Check's detail (the weekly block quotes the failed mark; the additional-task line
    repeats the same ArkStopped text) is not listed twice, and neither is a weekly-boss
    reason (the overlay starts those with 「周本」) once the weekly block has a failed
    item: older logs carry the failed mark after the waveplate-shortage line, which the
    weekly block already reports as the shortage.
    """
    found: list[tuple[str, str]] = []
    for m in _WEEKLY_FAILED.finditer(text):
        found.append(("这一趟按失败结束", without_screen_dump(_TRACEBACK_TAIL.sub("", m.group(1)))))
    for m in _ADDITIONAL_FAILED.finditer(text):
        found.append(("附加任务出错", without_screen_dump(_TRACEBACK_TAIL.sub("", m.group(1)))))
    weekly_red = any(c.label.startswith("周本") and not c.ok for c in out)
    extra: list[Check] = []
    for label, why in found:
        if why and any(why in c.detail for c in out + extra if not c.ok):
            continue
        if why.startswith("周本") and weekly_red:
            continue
        if not why and any(c.label == label for c in extra):
            continue
        extra.append(Check(label, False, why or "日志里只有这一句，没写原因"))
    return extra


_MAAEND_DONE = "自动执行任务完成"
_MAAEND_STUCK = re.compile(r"SceneAnyEnterWorld|PipelineTask bad next")
_MAAEND_DROPPED = re.compile(r'选项 "([^"]+)" (?:已不存在，已丢弃保存值'
                             r'|的类型已从 "[^"]*" 变更为 "[^"]*"，已重置为默认值)')
_DROPPED_OWNER = (
    ("AutoStockBuy", "自动囤货", "购买", "买"),
    ("AutoCollect", "自动采集", "路线", "走"),
)


def _dropped_checks(dropped: list[str]) -> list[Check]:
    """One failed SETTINGS Check per task whose saved options MaaEnd threw away."""
    groups: dict[tuple[str, str, str], list[str]] = {}
    for key in dropped:
        owner = next(((task, what, verb) for prefix, task, what, verb in _DROPPED_OWNER
                      if key.startswith(prefix)), ("其他", "", "跑"))
        groups.setdefault(owner, []).append(key)
    out = []
    for (task, what, verb), keys in groups.items():
        head = "、".join(keys[:5]) + ("…" if len(keys) > 5 else "")
        out.append(Check(f"{task}的设置", False,
                         f"{len(keys)} 个{what}选项被 MaaEnd 新版本重置成默认值，"
                         f"今天没按你的设置{verb}（{head}）", kind=SETTINGS))
    return out


_MAAEND_WORK = (
    ("自动采集", re.compile(r"(?:路线|线路)\d+[：:]|(?m:^(?:\[[^\]]+\]\s*)?采集(?!失败\s*$)[^\s：:]+\s*$)|库存已达目标，本次跳过"), "走了路线"),
    ("基质刷取", re.compile(r"已完成一次基质刷取|理智不足|体力不足[，,]\s*任务结束"), "刷了"),
    ("协议空间", re.compile(r"进入协议空间成功|理智不足|体力不足[，,]\s*任务结束"), "进了"),
)
_MAAEND_SKIPPED = re.compile(r"根据执行周期跳过")
_MAAEND_ESSENCE_MET = re.compile(r"勾选武器的基质均已满足")
_MAAEND_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def _maaend_segments(text: str):
    """(task name, its lines, seconds it took) for every 「任务开始」…「任务完成」 pair."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if m := re.search(r"任务开始[:：]\s*(\S.+?)\s*$", line):
            start = (i, m.group(1).strip())
            continue
        if start is None:
            continue
        if m := re.search(r"任务(?:完成|失败)[:：]\s*(\S.+?)\s*$", line):
            if m.group(1).strip() != start[1]:
                continue
            seg = "\n".join(lines[start[0]:i + 1])
            secs = 0
            t0, t1 = _MAAEND_TS.match(lines[start[0]]), _MAAEND_TS.match(line)
            if t0 and t1:
                fmt = "%Y-%m-%d %H:%M:%S"
                secs = int((datetime.strptime(t1.group(1), fmt)
                            - datetime.strptime(t0.group(1), fmt)).total_seconds())
            yield start[1], seg, secs
            start = None


_MAAEND_SCHEDULED = re.compile(r"开始执行任务, 数量: (\d+)")


def _all_done_no_exit(text: str, own_log: bool) -> bool:
    """Every scheduled task finished, none failed, and no wrap-up line.

    Needs MaaEnd's own log (`own_log`): the wrap-up line and the scheduled count
    live only there, and without it a truncated log would read as 「all done」.
    「All done」 is checked against the scheduled count, not just against the
    tasks that started: a crash between two tasks leaves later ones never begun.
    """
    if not own_log or _MAAEND_DONE in text:
        return False
    counts = [int(n) for n in _MAAEND_SCHEDULED.findall(text)]
    if not counts:
        return False
    started = re.findall(r"任务开始[:：]\s*(\S+)", text)
    finished = re.findall(r"任务完成[:：]\s*(\S+)", text)
    ended = re.findall(r"任务(?:完成|失败)[:：]\s*(\S+)", text)
    return (bool(started) and not (Counter(started) - Counter(ended))
            and not re.search(r"任务失败[:：]", text)
            and len(finished) >= counts[-1])


def maaend_no_self_exit(text: str, own_log: bool = False) -> bool:
    """Every scheduled task finished, none failed, and MaaEnd never wrote its wrap-up line."""
    return _all_done_no_exit(text, own_log)


def _maaend_cut_short(text: str) -> list[Check]:
    """Failed checks for a round MaaEnd cut short although AUTO-MAS booked it ok (audit
    2026-11-08 B-03): a task with more 「任务开始」 than 「任务完成/失败」, and MaaEnd's own stop
    (「任务开始: 停止任务」, __SceneCheckAbortPipeline PostStopping the chain, 2026-10-08
    10:34:16) before the round's closing task with fewer tasks finished than it was given.

    The stop alone is not enough: MXU prints it whenever the chain is stopped, also when
    AUTO-MAS stops a MaaEnd that finished everything and sat (collector_maaend
    _maaend_round_closed). Without the scheduled count (MaaEnd's own log missing) a stop
    before the closing task counts."""
    stop = collector_maaend._END_STOP_MARK
    starts = [collector_maaend._strip_emoji(n) for n in re.findall(r"任务开始[:：]\s*(\S.+?)\s*$", text, re.M)]
    ends = [collector_maaend._strip_emoji(n) for n in re.findall(r"任务(?:完成|失败)[:：]\s*(\S.+?)\s*$", text, re.M)]
    out = [Check(f"{name} 跑完", False, f"{name} 开始了 {Counter(starts)[name]} 次，只结束了 {Counter(ends)[name]} 次")
           for name in (Counter(n for n in starts if n != stop) - Counter(ends))]
    if stop in starts and not collector_maaend._maaend_round_closed(text):
        counts = [int(n) for n in _MAAEND_SCHEDULED.findall(text)]
        finished = len([n for n in ends if n != stop])
        if not counts or finished < counts[-1]:
            out.append(Check("MaaEnd 没被中途停掉", False,
                             "日志里有「停止任务」，停在收尾之前"
                             + (f"，排了 {counts[-1]} 个任务只结束了 {finished} 个" if counts else "")))
    return out


def maaend_checks(text: str, on_error_names: list[str], own_log: bool = False) -> list[Check]:
    """Verify one MaaEnd run.

    `on_error_names` are the screenshot filenames newly added during that run.
    `own_log`: MaaEnd's own app log is part of `text` (see _all_done_no_exit).
    """
    out: list[Check] = []
    done = _MAAEND_DONE in text
    all_done_no_exit = _all_done_no_exit(text, own_log)
    if all_done_no_exit:
        out.append(Check("任务全部完成（跑完没自己退出）", True))
    else:
        out.append(Check("MaaEnd 跑完", done,
                         "" if done else "日志里没有「自动执行任务完成」"))
    done = done or all_done_no_exit
    out += _maaend_cut_short(text)

    dropped = sorted(set(_MAAEND_DROPPED.findall(text)))
    out += _dropped_checks(dropped) or [Check("新版本认得全部旧设置", True)]
    for name, seg, secs in _maaend_segments(text):
        for key, evidence, what in _MAAEND_WORK:
            if key not in name:
                continue
            if evidence.search(seg):
                out.append(Check(f"{key} 真的{what}", True))
            elif key == "基质刷取" and _MAAEND_ESSENCE_MET.search(seg):
                out.append(Check(key, True, kind=SATISFIED))
            elif _MAAEND_SKIPPED.search(seg):
                out.append(Check(key, True, kind=SKIPPED))
            else:
                out.append(Check(f"{key} 真的{what}", False,
                                 f"{key} {secs} 秒就报「任务完成」，日志里没有{what}的痕迹"))

    # A route that hit 「战斗中无法使用」 at a relay device walked on and gathered
    # nothing (collector_maaend.blocked_routes; ledger #29). Its picture used to land in
    # 「出错截图 N 张（已重试恢复）」 below - a false green. It is booked by route and
    # handed to collect_retry, which re-runs it before power-off: not a failed Check,
    # so nothing goes to the group now; the retry's outcome decides that.
    blocked = collector_maaend.blocked_routes(text, on_error_names)
    for label, pics in blocked.items():
        out.append(Check(texts.collect_blocked_check(label), True, "出错截图：" + "、".join(pics[:3]),
                         kind=RETRY))
    # Only a finished run drops those pictures from the count below (they would read
    # "recovered by retry"). A run that did not finish keeps every picture in its failed
    # stuck-UI line - the reader needs the names to see where it stopped - while the
    # route stays booked once, by the RETRY check above, and the run as unfinished by
    # the run-finished check.
    used = {n for pics in blocked.values() for n in pics}
    all_names = on_error_names
    on_error_names = [n for n in on_error_names if n not in used]

    stuck = [n for n in on_error_names if _MAAEND_STUCK.search(n)]
    if stuck:
        out.append(Check("界面没卡住", False,
                         f"万能跳转失败 {len(stuck)} 次，存了截图："
                         + "、".join(stuck[:3])))
    elif all_names and not done:
        out.append(Check("界面没卡住", False,
                         f"有 {len(all_names)} 张出错截图："
                         + "、".join(all_names[:3])))
    elif on_error_names:
        out.append(Check(f"出错截图 {len(on_error_names)} 张（已重试恢复）", True))
    else:
        out.append(Check("界面没卡住", True))
    return out


# ── MAA ────────────────────────────────────────────────────────────
# MAA prints a pair for every task chain:
#   TaskChainStart  {"taskchain":"Infrast", ...}
#   TaskChainCompleted {"taskchain":"Infrast", ...}
# A chain started and never completed, or ended by Error / Stopped, is a failure.
# Error strings in the log are not counted: harmless ones (`skill has no
# recognition result`, `Unknown task`) appear in normal runs.
_MAA_CHAIN = re.compile(
    r'TaskChain(Start|Completed|Error|Stopped)\b.*?"taskchain":"(\w+)"')


_MAA_STARTUP = re.compile(
    r'TaskChainStart\b.*?"taskchain":"StartUp"')
_MAA_PROCESS = re.compile(r"^\[[^\]]*\]\[\w+\]\[Px(\d+)\]", re.M)


def _one_run_only(text: str) -> str:
    """Keep only this run: from the first line another MAA process wrote, and from
    the second StartUp, the rest belongs to the next run and is cut off.
    """
    procs = list(_MAA_PROCESS.finditer(text))
    if procs and (other := next((m for m in procs if m.group(1) != procs[0].group(1)), None)):
        text = text[:other.start()].rstrip("\n")
    hits = list(_MAA_STARTUP.finditer(text))
    if len(hits) < 2:
        return text
    cut = text.rfind("\n", 0, hits[1].start())
    return text[:cut] if cut > 0 else text


def _closedown_after_all_done(text: str) -> bool:
    """The last CloseDown start comes after an AllTasksCompleted receipt (MAA's post-action)."""
    start = text.rfind('TaskChainStart {"taskchain":"CloseDown"')
    return start > 0 and "AllTasksCompleted" in text[:start]


def maa_checks(text: str) -> list[Check]:
    """Verify one MAA run. `text` is the asst.log within that run's time window."""
    text = _one_run_only(text)
    started: Counter = Counter()
    ended: Counter = Counter()
    bad: list[str] = []
    for kind, chain in _MAA_CHAIN.findall(text):
        if kind == "Start":
            started[chain] += 1
        else:
            # A Stopped receipt for a chain that already completed is not an
            # abort (MAA can log TaskChainStopped CloseDown after
            # TaskChainCompleted CloseDown).
            if kind == "Stopped" and ended[chain] >= started[chain] > 0:
                continue
            ended[chain] += 1
            if kind in ("Error", "Stopped"):
                bad.append(f"{chain}({'报错' if kind == 'Error' else '被中止'})")

    out: list[Check] = []
    if not started:
        # No task chain event at all: the window or the log is wrong; not a pass.
        out.append(Check("MAA 的日志里有这一轮的记录", False,
                         "MAA 自己的日志里没有这一轮开始的记录，核对不了"))
        return out

    dangling = started - ended
    if dangling.get("CloseDown") and _closedown_after_all_done(text):
        del dangling["CloseDown"]
    out.append(Check("每一项都做到了结尾", not dangling,
                     "" if not dangling else
                     "开了没收尾：" + "、".join(sorted(dangling))))
    out.append(Check("没有哪一项报错或被中止", not bad,
                     "" if not bad else "、".join(sorted(set(bad)))))
    return out


def summarize(checks: list[Check], who: str) -> str | None:
    """Return a plain-language paragraph if anything failed; None if all succeeded."""
    bad = [c for c in checks if not c.ok]
    if not bad:
        return None
    undone = [c for c in bad if c.kind != SETTINGS]
    reset = [c for c in bad if c.kind == SETTINGS]
    lines = []
    if undone:
        lines.append(f"{who} 这一轮有 {len(undone)} 项没干成，但它自己没报错：")
        lines += [_bullet(c) for c in undone]
    if reset:
        lines.append(f"{who} {texts.OUTCOME_SETTINGS_HEAD}" if not undone else f"另外{texts.OUTCOME_SETTINGS_HEAD}")
        lines += [_bullet(c) for c in reset]
    if skipped := [c.label for c in checks if c.ok and c.kind == SKIPPED]:
        lines.append("按周期今天不跑：" + "、".join(skipped))
    if met := [c.label for c in checks if c.ok and c.kind == SATISFIED]:
        lines.append(texts.OUTCOME_ESSENCE_MET_HEAD + "、".join(met))
    lines += [c.label for c in checks if c.ok and c.kind == RETRY]
    ok = [c.label for c in checks if c.ok and c.kind not in (SKIPPED, SATISFIED, RETRY)]
    if ok:
        lines.append("干成的：" + "、".join(ok))
    return "\n".join(lines)


def _bullet(c: Check) -> str:
    return f"· {c.label}：{c.detail}" if c.detail else f"· {c.label}"


# The module logger, so tests can capture it as <module>.log (scripts/mac/lib/loggernames.py).
_log_collector_okww = logging.getLogger("ark.collector")


# Stamina reading, logged by `info_set` before each run.
_OKWW_STAMINA = re.compile(r"info_set current_stamina (\d+)")
# The reserve (green) stamina reading.
_OKWW_BACKUP = re.compile(r"info_set back_up_stamina (\d+)")
# OK-WW's own remainder line when it stops; two wordings follow the number
# (「not enough to continue」, 「must_use completed, no need to use back_up」), so
# only the first half is matched.
_OKWW_STAMINA_END = re.compile(r"current stamina:\s*(\d+)")
# One of these is logged per domain entry, so counting them counts the runs.
_OKWW_ENTRY = re.compile(r"使用单倍体力|当前体力大于等于双倍|使用双倍")
_OKWW_NEST_FULL = re.compile(r"指定点位都已打满")

_OKWW_FORGERY_INDEX = re.compile(r"info_set Teleport to Forgery Challenge (\d+)")
# The Simulation Challenge target (one of three in OK-WW's SimulationTask);
# translations from OK-WW's ok.po.
_OKWW_SIM_TARGET = re.compile(r"info_set Target Simulation Challenge (.+?)\s*$", re.M)
_SIM_ZH = {"Shell Credit": "贝币", "Resonator EXP": "共鸣者经验", "Weapon EXP": "武器经验"}
# Shell Credits per single run at full difficulty (game8 / fandom data, 2026-09);
# a double run gives two lots.
_SIM_REWARD_PER_RUN = {"贝币": 84000}
_OKWW_DOUBLE = re.compile(r"当前体力大于等于双倍|使用双倍")
_OKWW_SINGLE = re.compile(r"使用单倍体力")
_OKWW_TACET_INDEX = re.compile(r"info_set Teleport to Tacet Suppression (\d+)")


_LOG_DAY = re.compile(r"\d{4}-\d{2}-\d{2}(?= \d\d:\d\d)")
# The overlay's boss-material lines (ark_overrides.tasks.py BOSS_LINE): a claim, and the count read
# on the 培养目标 page before each lap (「强敌领奖：莉莉的共鸣者突破材料 1/46」).
_OKWW_BOSS_CLAIM = "强敌领奖：领了一次"
_OKWW_BOSS_COUNT = re.compile(r"强敌领奖：(\S+?)的(\S+?) (\d+)/(\d+)")


def _okww_farm(text: str, info: dict | None = None) -> "tuple[str, str]":
    """(the domain farmed, the yield category). OK-WW never reads the reward
    screen, so the yield can only be stated as a category.
    """
    info = info if info is not None else okww_info(text)
    if "SimulationTask:" in text:
        hits = _OKWW_SIM_TARGET.findall(text)
        tgt = _SIM_ZH.get(hits[-1].strip(), hits[-1].strip()) if hits else ""
        return (f"模拟领域·{tgt}" if tgt else "模拟领域", tgt or "模拟领域奖励")
    if "ForgeryTask:" in text:
        hits = _OKWW_FORGERY_INDEX.findall(text)
        idx = int(hits[-1]) + 1 if hits else 0
        return (_forgery_label(text), wuwa_forgery.reward(idx))
    if _OKWW_BOSS_CLAIM in text:
        hits = _OKWW_BOSS_COUNT.findall(text)
        who, row, owned, need = hits[-1] if hits else ("", "共鸣者突破材料", "", "")
        label = f"强敌·{who}{row}" + (f"（最后读到 {owned}/{need}）" if owned else "")
        if "info_set Teleport to Tacet Suppression" in text:
            label += "，余下的刷了无音区"
        return (label, row)
    if "TacetTask:" in text:
        # Name and drop sets come from wuwa_tacet's table. The index is the one
        # OK-WW teleported to (info_set, from 0), else the last teleport line.
        got = (info.get("fields") or {}).get("Teleport to Tacet Suppression")
        hits = _OKWW_TACET_INDEX.findall(text)
        if got is None and not hits:
            return ("无音区（日志里没有序号）", "声骸（无音区序号没读到，套装不明）")
        idx = (int(got) if got is not None else int(hits[-1])) + 1
        # The list moved in 3.7 (wuwa_tacet.NEW_LIST_FROM): read it as of the run's own day.
        day = (_LOG_DAY.search(text) or [None])[0]
        return (wuwa_tacet.label(idx, day), wuwa_tacet.reward(idx, day))
    return ("", "")


def _forgery_label(text: str) -> str:
    """Which instance follows 「凝素领域」. When it cannot be identified, only
    the index is stated.

    The index in the log counts from 0 (`Teleport to Forgery Challenge 0`);
    the lookup table counts from 1 (matching the game's F2 list). **The
    conversion happens only here**, and callers always get plain language.
    """
    hits = _OKWW_FORGERY_INDEX.findall(text)
    if not hits:
        return "凝素领域"          # The step list reads 「做了 凝素领域 ×5」; do not stuff brackets in
    return wuwa_forgery.label(int(hits[-1]) + 1)


_OKWW_GAME_ERR = "waiting for game to start error"
_OKWW_ACTIVITY = re.compile(r" INFO TaskExecutor \w+:")
_OKWW_TB_HEAD = re.compile(r" ERROR TaskExecutor (\w+):(.*?) Traceback \(most recent call last\):")
_OKWW_EXC_LINE = re.compile(r"^\s*([\w.]*(?:Exception|Error)\w*)\b(.*)$", re.M)


def _okww_got_in(text: str) -> bool:
    """Whether any task executor was still working after the last
    "cannot get the game window". If so, it got in later on.
    """
    i = text.rfind(_OKWW_GAME_ERR)
    return bool(_OKWW_ACTIVITY.search(text, i if i >= 0 else 0))


# Chinese for task class names, exception names and known raw messages, used in
# notifications; untranslated ones are quoted raw (see _okww_say).
_OKWW_TASK_ZH = {
    "DailyTask": "日常清单", "FarmEchoTask": "周本", "TacetTask": "无音区",
    "NightmareNestTask": "残象聚落", "GardenTask": "周常乐园", "DomainTask": "模拟领域",
    "FarmWorldBossTask": "世界 Boss", "CombatCheck": "战斗", "BaseCombatTask": "战斗",
    "TaskExecutor": "任务执行", "AutoCombatTask": "战斗",
}
_OKWW_EXC_ZH = {
    "WaitFailedException": "等一个画面没等到", "CannotFindException": "画面上找不到要点的东西",
    "NotInCombatException": "没有进入战斗", "CharDeadException": "角色倒下了",
    "TimeoutError": "超时", "TaskDisabledException": "任务被关掉了",
}
_OKWW_MSG_ZH = (
    ("Teleport to boss failed", "传送去打 Boss 没成（图鉴传送、选关卡、进本其中一步没过），没进本，一次没打"),
    ("can't find gray_book_boss", "按 F2 打不开图鉴——先核对键位是不是游戏默认"),
    ("NightmareNestTask Failed", "没打成"),
    ("Logger.error() got an unexpected keyword", "旧版补丁自己的日志调用写错（已撤回）"),
    ("can not battle pass", texts.OKWW_BATTLE_PASS_UNCLAIMED),
    ("Game window is not connected", "连不上游戏窗口"),
    ("not in combat", "没有进入战斗"),
    ("can't find boss_proceed", "图鉴里找不到「前往」按钮"),
    ("Please start in game world and in team",
     "开跑时游戏不在大世界、或者没有出战队伍，OK-WW 不肯开工"),
)
_OKWW_WRAPPER = "Daily Task exception stopped"
_OKWW_WAIT_SEC = re.compile(r"wait_until timeout .*? (\d+(?:\.\d+)?) seconds")
_OKWW_ANY_ERR = re.compile(r" ERROR TaskExecutor (\w+):(.*)")
_OKWW_UNTRANSLATED: set = set()


_OKWW_INFO = re.compile(r" INFO TaskExecutor (\w+):info_set (.+)$", re.M)
_OKWW_INFO_NUM = ("current_stamina", "back_up_stamina", "current daily progress",
                  "total daily points", "Teleport to Tacet Suppression",
                  "Teleport to Boss Weekly Challenge")
# Keys whose value contains spaces: the rest of the line is the value, so it
# must not be split on the last space
_OKWW_INFO_REST = ("Chars", "Revive", "Target Simulation Challenge")


def okww_info(text: str, until: int | None = None) -> dict:
    """The structured state OK-WW writes itself (`info_set key value`), taking
    the last occurrence of each key.

    `current task` is the step OK-WW is on, `错误` is the failure reason it
    logged, and `Teleport to Tacet Suppression` is the Tacet Suppression it
    teleported to (counting from 0).

    Returns {"fields": {key: value}, "tasks": [current task in order of
    appearance], "error": the reason, or empty}.
    """
    fields: dict = {}
    tasks: list[str] = []
    error = ""
    for m in _OKWW_INFO.finditer(text):
        if until is not None and m.start() >= until:
            break           # Only the state before this point
        body = m.group(2).strip()
        if body.startswith("current task"):
            what = body[len("current task"):].strip()
            if what and not what.startswith(("wait main", "in main")):
                tasks.append(what)
            continue
        if body == "错误" or body.startswith("错误 "):
            error = body[len("错误"):].strip()
            continue
        key, _, value = body.rpartition(" ")
        for whole in _OKWW_INFO_REST:
            if body.startswith(whole + " "):
                key, value = whole, body[len(whole) + 1:]
                break
        if not key:
            continue
        if key in _OKWW_INFO_NUM:
            try:
                fields[key] = int(value)
            except ValueError:
                continue
        else:
            fields[key] = value
    return {"fields": fields, "tasks": tasks, "error": error}


def _okww_error(text: str) -> str:
    """The real reason for the failure, in plain language. Taken from the
    innermost task's section of the last traceback cluster.

    When OK-WW raises, it prints three tracebacks in a row (the task itself,
    DailyTask.run_task_by_class, and TaskExecutor's
    「Daily Task exception stopped」) for the same event; the innermost one
    carries the explanation.
    """
    text = normalize_okww_log(text)
    info = okww_info(text)
    heads = list(_OKWW_TB_HEAD.finditer(text))
    if not heads:
        # No traceback, but upstream said 「错误 …」itself: write what it said
        if info["error"] and info["tasks"]:
            step = info["tasks"][-1].split()[0]
            return _okww_say(_OKWW_TASK_BY_STEP.get(step, step), info["error"], "")
        return ""
    cluster = _last_event(text, heads)
    inner = [m for m in cluster if m.group(1) not in ("DailyTask", "TaskExecutor")]
    head = (inner or cluster)[0]
    task, msg = head.group(1), head.group(2).strip()
    nxt = heads[heads.index(head) + 1].start() if heads.index(head) + 1 < len(heads) else len(text)
    excs = _OKWW_EXC_LINE.findall(text[head.end():nxt])
    exc = excs[-1][0].rsplit(".", 1)[-1] if excs else ""
    if "farm 4c error" in msg:
        # The catch-all sentence (see _OKWW_MSG_ZH): the reason is the exception
        # printed under it, e.g. 「RuntimeError: Teleport to boss failed」.
        msg = excs[-1][1].lstrip(": ").strip() if excs else ""
    if task in ("DailyTask", "TaskExecutor"):
        # Raised by the wrapper layer itself (such as
        # 「NightmareNestTask Failed」or 「run_task_by_class <class …>」): the real
        # task name is in that sentence, and the real reason is in the ERROR
        # line before it
        if m := re.search(r"<class '[\w.]*\.(\w+)'>", msg):
            task = m.group(1)
        elif m := re.match(r"(\w+Task) Failed", msg):
            task = m.group(1)
        before = text[max(0, head.start() - 1500):head.start()]
        prior = [m for m in _OKWW_ANY_ERR.finditer(before)
                 if m.group(1) not in ("DailyTask", "TaskExecutor", "CombatCheck", "BaseCombatTask")]
        if prior:
            task, msg = prior[-1].group(1), prior[-1].group(2).strip()
    # When still on a wrapper header (such as 「Daily Task exception stopped」
    # with no inner task class in msg or prior ERROR), use the step upstream
    # recorded via `current task`.
    if task in ("DailyTask", "TaskExecutor"):
        before_tasks = okww_info(text, until=head.start())["tasks"]
        if before_tasks:
            task = _OKWW_TASK_BY_STEP.get(before_tasks[-1].split()[0], task)
    # No generic catch-all: an untranslated error is quoted raw (_okww_say).
    return _okww_say(task, msg, exc, text, head.start())


_EVENT_GAP_SECONDS = 2.0
_HEAD_TS = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{1,6})")


def _head_time(text: str, m: re.Match) -> "float | None":
    """The timestamp (seconds) at the start of the line holding traceback header `m`."""
    line = text.rfind("\n", 0, m.start()) + 1
    t = _HEAD_TS.match(text, line)
    return _ts(t.group(1), t.group(2)) if t else None


def _last_event(text: str, heads: list) -> list:
    """The traceback headers of the last event: walking back from the last header,
    each one within _EVENT_GAP_SECONDS of the next.
    """
    cluster = [heads[-1]]
    for m in reversed(heads[:-1]):
        nxt = cluster[0]
        a, b = _head_time(text, m), _head_time(text, nxt)
        near = (b - a <= _EVENT_GAP_SECONDS) if a is not None and b is not None \
            else nxt.start() - m.start() < 6000
        if not near:
            break
        cluster.insert(0, m)
    return cluster


_OKWW_TASK_BY_STEP = {
    "garden_start_game": "GardenTask", "garden": "GardenTask",
    "check": "GardenTask", "claim": "DailyTask", "farm": "FarmEchoTask",
    "tacet": "TacetTask", "nest": "NightmareNestTask",
}


def _okww_say(task: str, msg: str, exc: str, text: str = "", at: int = 0) -> str:
    """Turn (task, raw message, exception name) into one plain-language
    sentence. When it cannot be translated, say so outright -- never be vague.
    """
    msg = normalize_okww_log(msg)
    task_zh = _OKWW_TASK_ZH.get(task)
    if FAILED_MARK in msg:
        # The overlay ended the run as failed and logged why in Chinese.
        why = without_screen_dump(msg.split(FAILED_MARK, 1)[1])
        who = task_zh or "某个任务"
        return why if why.startswith(who) else f"{who}：{why}"
    msg_zh = next((zh for en, zh in _OKWW_MSG_ZH if en in msg), "")
    exc_zh = _OKWW_EXC_ZH.get(exc)
    if task_zh is not None and not (msg_zh or exc_zh) and _OKWW_WRAPPER in msg:
        # Only the outermost traceback (the daily list stopped) was found. Use
        # OK-WW's own 「错误 …」 line when it has one, else say the list stopped.
        # The wrapper is not in _OKWW_MSG_ZH because that table also decides which
        # traceback is reported, and the wrapper must not win there.
        err = (okww_info(text).get("error") or "").strip() if text else ""
        if err and _OKWW_WRAPPER not in err:
            return _okww_say(task, err, "")      # text="" so this branch cannot recurse
        return f"{task_zh}：日常清单整个停了（真正的原因在它上面那条）"
    if task_zh is None or not (msg_zh or exc_zh):
        sig = (task, exc, msg[:80])
        if sig not in _OKWW_UNTRANSLATED:      # Warn once per process for the same raw message
            _OKWW_UNTRANSLATED.add(sig)
            _log_collector_okww.warning(
                "OK-WW 报错中继还没有翻译，通知里只能说不认识：任务 %s，异常 %s，原文「%s」",
                task, exc or "（没抓到异常名）", msg)
        who = task_zh or "某个任务"
        # The raw text goes into the notification itself: the machine is often
        # off by the time the alert is read, so the log cannot be looked up.
        raw = " ".join((msg or "").split())[:110] or exc or "（连原文都没抓到）"
        return f"{who}：中继还不认识这条错，原文照抄——「{raw}」"
    what = msg_zh or exc_zh
    if "Teleport to boss failed" in msg and text and _said_before(text, at, _NO_CHALLENGE):
        what = "选了等级后没等到「开启挑战」，没进本，一次没打"
    # The 「wait_until timeout … N seconds」 line right before the traceback says
    # how long it waited.
    if (w := _wait_before(text, at)) and "等" in what:
        sec = w[:-2] if w.endswith(".0") else w
        what += f"（等了 {sec} 秒）"
    return f"{task_zh}：{what}"


_OKWW_WAIT_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{1,6}) [^\n]*?"
                             r"wait_until timeout [^\n]*? (\d+(?:\.\d+)?) seconds", re.M)


def _wait_before(text: str, at: int) -> str:
    """Seconds of the 「wait_until timeout」 that raised the traceback at `at`; '' when none."""
    if not text:
        return ""
    line = text.rfind("\n", 0, at) + 1
    hm = _HEAD_TS.match(text, line)
    if hm is None:
        got = _OKWW_WAIT_SEC.findall(text[max(0, at - 4000):at])
        return got[-1] if got else ""
    head_t = _ts(hm.group(1), hm.group(2))
    best = ""
    for m in _OKWW_WAIT_LINE.finditer(text, max(0, at - 200_000), at):
        t = _ts(m.group(1), m.group(2))
        if t is not None and head_t is not None and 0 <= head_t - t <= _EVENT_GAP_SECONDS:
            best = m.group(3)
    return best


# The overlay's lines when the boss level was chosen but 「开启挑战」 never came (the
# teleport then fails with 「Teleport to boss failed」).
_NO_CHALLENGE = re.compile(r"找不到开启挑战|都没进开启挑战")
_LINE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{1,6}) ", re.M)


def _said_before(text: str, at: int, what: "re.Pattern") -> bool:
    """Is `what` on a line logged within _EVENT_GAP_SECONDS before the header at `at`?"""
    hm = _HEAD_TS.match(text, text.rfind("\n", 0, at) + 1)
    head_t = _ts(hm.group(1), hm.group(2)) if hm else None
    if head_t is None:
        return bool(what.search(text, max(0, at - 3000), at))
    for m in what.finditer(text, max(0, at - 200_000), at):
        lm = _LINE_TS.match(text, text.rfind("\n", 0, m.start()) + 1)
        t = _ts(lm.group(1), lm.group(2)) if lm else None
        if t is not None and 0 <= head_t - t <= _EVENT_GAP_SECONDS:
            return True
    return False


def _ts(stamp: str, frac: str) -> "float | None":
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").timestamp() + float("0." + frac)
    except ValueError:
        return None


def parse_okww_log(log_path: Path) -> dict:
    """Recover stamina spend / entry count / daily progress from an OK-WW log.

    Stamina is summed from the *drops* between consecutive readings rather than
    from first-minus-last: the reserve tops the bar back up mid-run, and a
    naive subtraction reads that refill as if it had never been spent.
    """
    try:
        text = normalize_okww_log(log_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}

    out: dict = {}
    readings, entries = _okww_stamina_fields(text, out)
    _okww_health(text, out, entries)
    _okww_farm_fields(text, out)
    _okww_stamina_left(text, out, readings)
    _okww_progress(text, out)
    if steps := _okww_steps(text, entries):
        out["okww_steps"] = steps
    if "游戏更新成功, 游戏即将重启" in text:
        out["okww_restart_dialog"] = True
        out["okww_client_change"], out["okww_client_files"] = _client_change(log_path, text)
    return out


_OKWW_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", re.M)


def _client_change(log_path: Path, text: str) -> "tuple[str, list[str]]":
    """What the game client changed on disk during this run: (「none」 (nothing
    outside saves) / 「anticheat」 (only files under AntiCheatExpert) / 「patch」
    (anything else) / 「unknown」 (game root not found), the changed paths relative
    to the game root, at most twelve).

    OK-WW logs 「游戏更新成功, 游戏即将重启」 for any dialog that says 游戏即将重启
    (BaseWWTask.py:777), including an anti-cheat refresh, so the files on disk
    decide which it was.
    """
    stamps = _OKWW_TS.findall(text)
    if not stamps:
        return "unknown", []
    try:
        lo = datetime.strptime(stamps[0], "%Y-%m-%d %H:%M:%S")
        hi = datetime.strptime(stamps[-1], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "unknown", []
    root = wuwa_game_root(log_path)
    if root is None:
        return "unknown", []
    anticheat: list[str] = []
    other: list[str] = []
    for p in (root / "Client").rglob("*"):
        try:
            if not p.is_file():
                continue
            rel = str(p.relative_to(root))
            if "\\Saved\\" in rel or "/Saved/" in rel or ".quality" in rel:
                continue
            if lo.timestamp() <= p.stat().st_mtime <= hi.timestamp():
                # Shown as the part under Client\Binaries\Win64 when it is there:
                # 「AntiCheatExpert\pld.dat」 says more than the full path.
                short = rel.split("Win64" + ("\\" if "\\" in rel else "/"), 1)[-1]
                (anticheat if "AntiCheatExpert" in rel else other).append(short)
        except OSError:
            continue
    if other:
        return "patch", sorted(other)[:12]
    return ("anticheat", sorted(anticheat)[:12]) if anticheat else ("none", [])


def wuwa_game_root(log_path: Path) -> "Path | None":
    """The game install root, from OK-WW's own devices.json (the exe it launches)."""
    base = okww_root()
    dev = base / "data" / "apps" / "ok-ww" / "working" / "configs" / "devices.json"
    try:
        # JSON-escaped Windows path (D:\\Wuthering...) on the machine; a plain
        # POSIX path in the tests.
        m = re.search(r"(?:[A-Z]:\\\\|/)[^\"]*?Client-Win64-Shipping\.exe", dev.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    if not m:
        return None
    exe = Path(m.group(0).replace("\\\\", "\\"))
    # <root>\Client\Binaries\Win64\Client-Win64-Shipping.exe
    root = exe.parents[3] if len(exe.parents) > 3 else None
    return root if root and root.is_dir() else None


def _okww_stamina_fields(text: str, out: dict) -> "tuple[list[int], int]":
    """Waveplates spent, domain entries, reserve stamina. Returns
    (the series of readings, the entry count) for the checks that follow.
    """
    marks = list(_OKWW_STAMINA.finditer(text))
    readings = [int(m.group(1)) for m in marks]
    # The wrap-up line 「current stamina: 8 not enough to continue」 is the last
    # reading and holds the final run's cost.
    tail = [int(x) for x in _OKWW_STAMINA_END.findall(text)]
    series = readings + tail[-1:]
    spent = sum(a - b for a, b in zip(series, series[1:], strict=False) if a > b)
    costs = _weekly_claim_costs(text)
    spent += _not_yet_shown(text, [m.start() for m in marks] + [len(text)] * len(tail[-1:]), series,
                            [(at, w) for at, w, _b in costs if w])
    if spent:
        out["okww_stamina_spent"] = spent
    entries = len(_OKWW_ENTRY.findall(text))
    if entries:
        out["okww_runs"] = entries
    back_marks = list(_OKWW_BACKUP.finditer(text))
    backs = [int(m.group(1)) for m in back_marks]
    if backs:
        out["okww_backup_stamina"] = backs[-1]
    used = sum(a - b for a, b in zip(backs, backs[1:], strict=False) if a > b)
    used += _not_yet_shown(text, [m.start() for m in back_marks], backs, [(at, b) for at, _w, b in costs if b])
    if used:
        out["okww_backup_spent"] = used
    if unread := sum(1 for _at, w, _b in costs if w is None):
        out["okww_weekly_topup_unread"] = unread
    return readings, entries


# Waveplates one weekly-boss reward claim costs (the game's own price; the overlay's
# claim code checks for the same 60 before it confirms).
_WEEKLY_CLAIM_WAVEPLATES = 60
# The overlay's claim lines: the game's 「用备用体力补足」 dialog was answered, and (from
# okww-fix-a on) the top bar it read before confirming.
_WEEKLY_TOPUP = "周本领奖：波片不够，动用备用体力"
_WEEKLY_TOPBAR = re.compile(r"周本领奖：顶栏读到波片 (\d+)/240，备用 (\d+)")
# Waveplates come back one per 6 minutes, so a drop between two readings can be up
# to (minutes / 6) short of what was spent between them.
_REGEN_SECONDS = 360


def _weekly_claim_costs(text: str) -> "list[tuple[int, int | None, int | None]]":
    """(position, waveplates, backup) for each verified weekly claim."""
    out: list = []
    prev = 0
    for m in WEEKLY_CLAIM_OK.finditer(text):
        seg, prev = text[prev:m.start()], m.end()
        if _WEEKLY_TOPUP not in seg:
            out.append((m.start(), _WEEKLY_CLAIM_WAVEPLATES, 0))
        elif bars := _WEEKLY_TOPBAR.findall(seg):
            wave, spare = (int(x) for x in bars[-1])
            backup = min(spare, max(0, _WEEKLY_CLAIM_WAVEPLATES - wave))
            out.append((m.start(), _WEEKLY_CLAIM_WAVEPLATES - backup, backup))
        else:
            out.append((m.start(), None, None))
    return out


def _not_yet_shown(text: str, pos: "list[int]", series: "list[int]", items: "list[tuple[int, int]]") -> int:
    """The part of `items` ((position, amount) spent between readings) the readings do not show.
    """
    per_gap: dict = {}
    for at, amount in items:
        i = bisect.bisect_right(pos, at)
        per_gap[i] = per_gap.get(i, 0) + amount
    extra = 0
    for i, need in per_gap.items():
        if 0 < i < len(series):
            a, b = _pos_time(text, pos[i - 1]), _pos_time(text, pos[i])
            margin = int((b - a) // _REGEN_SECONDS) + 1 if a is not None and b is not None and b >= a else 10
            if series[i - 1] - series[i] + margin >= need:
                continue
        extra += need
    return extra


def _pos_time(text: str, pos: int) -> "float | None":
    """The timestamp of the line holding `pos`; None past the end or without one."""
    if pos >= len(text):
        return None
    t = _HEAD_TS.match(text, text.rfind("\n", 0, pos) + 1)
    return _ts(t.group(1), t.group(2)) if t else None


def _okww_health(text: str, out: dict, entries: int) -> None:
    """Whether it got into the game, and the real reason for a failure."""
    # Never got into the game: the window wait errored, no run started, and no
    # task worked after the last window error (a transient window error can be
    # followed by a normal run).
    if "waiting for game to start error" in text and not entries and not _okww_got_in(text):
        out["okww_unreachable"] = True
    if err := _okww_error(text):
        out["okww_error"] = err


def _okww_farm_fields(text: str, out: dict) -> None:
    """Which domain was farmed, how many single and double runs, and the yield
    estimated at full difficulty.
    """
    info = okww_info(text)
    if info["fields"] or info["tasks"]:
        out["okww_info"] = info["fields"]
    farm, reward = _okww_farm(text, info)
    if farm:
        out["okww_farm"] = farm
        out["okww_farm_reward"] = reward
        double = len(_OKWW_DOUBLE.findall(text))
        single = len(_OKWW_SINGLE.findall(text))
        if double:
            out["okww_runs_double"] = double
        if single:
            out["okww_runs_single"] = single
        if (per := _SIM_REWARD_PER_RUN.get(reward)) and (double or single):
            out["okww_farm_drops"] = {reward: per * (2 * double + single)}


def _okww_stamina_left(text: str, out: dict, readings: list) -> None:
    if end := _OKWW_STAMINA_END.findall(text):
        out["okww_stamina_left"] = int(end[-1])
        out["okww_stamina_left_exact"] = True
    elif readings:
        # No wrap-up line: the last pre-run reading, flagged as not final.
        out["okww_stamina_left"] = readings[-1]
        out["okww_stamina_left_exact"] = False


def _okww_progress(text: str, out: dict) -> None:
    """Nightmare Nests all full, daily points, and why it stopped."""
    if _OKWW_NEST_FULL.search(text):
        out["okww_nest_full"] = True
    if points := _DAILY_POINTS.findall(text):
        top = max(int(x) for x in points)
        out["okww_points"] = f"{top}/{_DAILY_POINTS_TARGET}"
        if top >= _DAILY_POINTS_TARGET:
            out["okww_points"] += "（已满）"
        # The first reading already at the target: the dailies were done before
        # this run started, so farming nothing is expected.
        if int(points[0]) >= _DAILY_POINTS_TARGET:
            out["okww_daily_done_at_start"] = True
    # Why it stopped, in its own words. A failure the 刷体力 verdict reports
    # (outcome.stamina_failure: three revives, or a stop judged on a stamina reading
    # that failed) comes first, in the verdict's words. Otherwise "used all stamina"
    # is the good ending.
    if why := stamina_failure(text):
        out["okww_stopped"] = why
    elif "used all stamina" in text:
        # OK-WW's `used all stamina` means what is left is less than one run,
        # not that 0 is left.
        out["okww_stopped"] = "体力不够再开一局"
    elif "not enough stamina" in text:
        out["okww_stopped"] = "体力不够，一局都没开成"


# outcome.nest_state() keys -> the note after the nest's name in the step list.
_NEST_STEP = {
    "filter_missing": "（只刷指定点位的补丁没贴上，一次没打）",
    "not_found": "（点位名对不上，一次没打）",
    "count_unread": "（计数没读到，停下没刷）",
    "full": "（已刷满）",
    "fought": "",
    "partly": "（有一处传送两次都不过去，那一处没打）",
    "unreachable": "（传送不过去，一次没打）",
    "failed": "（失败，一次没打）",
    "quit": "（开了界面就退出，一次没打）",
    "not_run": "（没跑到，一次没打）",
}


def _nest_step(text: str) -> str:
    """The nightmare-nest item of the daily report's step list."""
    nest = "残象聚落" if "canxiang" in text else "梦魇巢穴"
    # The verdict's own classifier (outcome.nest_state), so the step and the
    # 残象聚落 item of the result check cannot disagree. A nest counts as farmed
    # only on a fight line, not on the task appearing in the log; the bare name
    # means farmed (selfcheck #25 reads it that way).
    line = nest + _NEST_STEP[nest_state(text)]
    if names := nests_given_up(text):
        line += f"（{'、'.join(names)}）"
    if _NEST_ADAPTED in text:
        # find_nest was installed adapted to a changed upstream body.
        line += "（只刷指定点位的过滤按 OK-WW 新版适配，请核对）"
    return line


def _okww_steps(text: str, entries: int) -> list[str]:
    """The step list in the daily report's 「备注」, each item marked with its
    own success or failure.
    """
    # Listed: the farmed domain, Nightmare Nests, the weekly boss, the weekly
    # garden and echo merging; each with its own outcome. Mail, radio and daily
    # rewards are not listed.
    steps = []
    for needle, name in (
        ("ForgeryTask:", _forgery_label(text)),
        ("TacetTask:", "无音区"),
        ("SimulationTask:", "模拟领域"),
    ):
        if needle not in text:
            continue
        if entries:
            steps.append(f"{name} ×{entries}")
        else:
            steps.append(f"{name}（未进本）")
    if "NightmareNestTask:" in text:
        steps.append(_nest_step(text))
    # The weekly boss; handle.py books the week from this step.
    if "Teleport to Boss Weekly Challenge" in text:
        # Only a claim the overlay re-read the counter for counts (outcome.weekly_claims);
        # 「已点确认」 alone is a click, not a claim. handle.py books the week on
        # 「周本…已完成」, so no unverified wording below may contain 已完成.
        c = weekly_claims(text)
        claims, tried = c["verified"], c["attempted"]
        unverified = weekly_unverified(c)
        left = [int(m) for m in re.findall(r"本周剩余可收取次数[：:]\s*(\d+)\s*/", text)]
        # The same shortage reading as the run's result check (outcome.WEEKLY_SHORT).
        short = bool(WEEKLY_SHORT.search(text))
        if "本周周本次数已领满" in text and not tried:
            # Read 0/3 before entering and skipped: full, but not by this run.
            steps.append("周本（已完成：进本前读到本周 0/3，早已领满，这一趟没领）")
        elif "Teleport to boss failed" in text and not tried:
            steps.append("周本（没进本，一次没打，原因见失败于）")
        elif short and not tried:
            # The overrides' own skip lines (old and current wording).
            steps.append("周本（奖励没领：结晶波片不足，这一趟没打）")
        elif "farm 4c error" in text:
            steps.append(f"周本（领了 {claims} 次，之后出错，原因见失败于）" if claims
                         else f"周本（{unverified}，之后出错，原因见失败于）" if tried
                         else "周本（没做完，原因见失败于）")
        elif not claims and ("收取物资次数已达到上限" in text or (left and left[-1] == 0 and not tried)):
            steps.append("周本（已完成，本周已领满）")
        elif claims:
            # The newest reading of the game's counter, pre-entry or read-back.
            remain = weeklyboss.left_after_claims(text)
            if remain is None:
                where = "本周剩余次数没读到"
            elif remain == 0:
                where = "本周已领满"
            else:
                where = f"本周还剩 {remain} 次"
            extra = f"；另有{unverified}" if unverified else ""
            if short:
                extra += "；剩下的奖励没领：结晶波片不足"
            steps.append(f"周本（已完成，领了 {claims} 次，{where}{extra}）")
        elif tried:
            steps.append(f"周本（{unverified}）")
        elif _WEEKLY_FOUGHT.search(text):
            steps.append("周本（打了，没领到奖励）")
        elif "teleport_to_boss prepared as" in text:
            # Landed in the realm, no fight line.
            steps.append("周本（进了本，没打起来，没领到奖励）")
        else:
            steps.append("周本（没进本，一次没打）")
    # GardenTask logs 「乐园任务完成, 已达到上限」 when the week is already done and
    # right after finishing it; DailyTask logs 「weekly garden already completed」.
    if "weekly garden already completed" in text or "乐园任务完成" in text:
        steps.append("周常乐园（本周已完成）")
    elif "GardenTask:" in text:
        # Ran, but no 「乐园任务完成」: the counter read alone does not show it done
        # (core.UNVERIFIED_STEP; the daily title counts it as unverified).
        steps.append("周常乐园（没读到做完，不算完成）")
    return steps
