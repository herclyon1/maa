"""Turn OK-WW's translated (zh_CN) log lines back into the English source strings our checks look for.

On the machine OK-WW runs with the zh_CN locale, and both OK-WW and the ok-script framework under it
translate their own log text: OK-WW through its gettext catalog (working/i18n/zh_CN/LC_MESSAGES/ok.po),
the framework through Qt (python/Lib/site-packages/ok/ui/qt/i18n/zh_CN.ts). Every check in outcome.py
and every entry of gamelog_errors.txt is written against the English source strings, so each upgrade
that translated one more string broke a check until someone hand-added the pair to
outcome._OKWW_ZH_TO_EN. Ledger #136 (2026-11-04) was the framework's
「当前游戏或模拟器不支持选择的截图方式!」 for "Selected capture method is not supported by the game
or your system!", which is in ok-script's zh_CN.ts and not in OK-WW's ok.po.

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
from dataclasses import dataclass, field
from pathlib import Path

from ark_relay.core import config

PO_REL = Path("data") / "apps" / "ok-ww" / "working" / "i18n" / "zh_CN" / "LC_MESSAGES" / "ok.po"
TS_REL = (Path("data") / "apps" / "ok-ww" / "python" / "Lib" / "site-packages" / "ok" / "ui" / "qt"
          / "i18n" / "zh_CN.ts")

_HAN = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
# str.format ({}, {0}, {name}, {name:>3}), printf (%s, %d, %(name)s) and Qt's %1 .. %99.
_HOLE = re.compile(r"\{[^{}]*\}|%\(\w+\)[sdfr]|%[sdfr]|%\d{1,2}")
# 「2026-10-06 09:19:26,058 INFO MainThread TaskExecutor:message」 (OK-WW's own log and the copy
# AUTO-MAS keeps next to its history record).
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
