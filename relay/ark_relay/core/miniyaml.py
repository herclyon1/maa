"""Read the YAML AUTO-MAS writes - and only that much YAML.

AUTO-MAS v5.8.0-beta.1 (installed on the machine 2026-10-23 08:48 Beijing) keeps its settings in
config/scripts.yaml, queues.yaml and plans.yaml instead of the JSON files the relay read
(masconfig). The relay's own Python has no YAML library (Python, Pillow and pywin32 only), so
this reads the subset PyYAML's block-style dump produces there:

* block mappings and sequences, including a sequence at its parent key's indent;
* plain scalars (null / ~, YAML 1.1 booleans, ints, floats, else strings), folded over lines;
* single- and double-quoted scalars, folded over lines (scripts.yaml folds long JSON strings);
* the empty flow collections {} and [].

Anything else - a non-empty flow collection, a block scalar (| or >), an anchor or a tag - is
refused with ValueError rather than guessed at. Keys are always strings, as they were in the
JSON. Checked against PyYAML on the machine's own files (relay/tests/test_masconfig_yaml.py
has synthetic copies of every construct; the repo is public, so not the files themselves).
"""
from __future__ import annotations

import re

_BOOL = {"yes": True, "true": True, "on": True, "no": False, "false": False, "off": False}
_INT = re.compile(r"[-+]?[0-9]+")
_FLOAT = re.compile(r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?")
_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f",
            "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85",
            "_": "\xa0", "L": " ", "P": " "}
_HEX = {"x": 2, "u": 4, "U": 8}


def loads(text: str):
    """The document in `text` as dicts, lists and scalars."""
    p = _Parser(text.splitlines())
    p.skip()
    if p.i >= len(p.lines):
        return None
    value = p.node(p.indent())
    p.skip()
    if p.i < len(p.lines):
        raise ValueError(f"line {p.i + 1}: unexpected content after the document")
    return value


def _plain(s: str):
    if s in ("", "~") or s.lower() == "null":
        return None
    if s.lower() in _BOOL:
        return _BOOL[s.lower()]
    if _INT.fullmatch(s):
        return int(s)
    if _FLOAT.fullmatch(s) and any(c.isdigit() for c in s):
        return float(s)
    if s.lower() in (".inf", "+.inf"):
        return float("inf")
    if s.lower() == "-.inf":
        return float("-inf")
    if s.lower() == ".nan":
        return float("nan")
    return s


class _Parser:
    def __init__(self, lines: list[str]):
        self.lines = list(lines)
        self.i = 0

    def skip(self) -> None:
        while self.i < len(self.lines) and (not self.lines[self.i].strip()
                                            or self.lines[self.i].lstrip().startswith("#")):
            self.i += 1

    def indent(self) -> int:
        line = self.lines[self.i]
        return len(line) - len(line.lstrip(" "))

    def body(self) -> str:
        return self.lines[self.i].strip()

    def node(self, ind: int):
        b = self.body()
        if b == "-" or b.startswith("- "):
            return self.sequence(ind)
        if self.split_key(b) is not None:
            return self.mapping(ind)
        return self.scalar(b, ind - 1)

    def split_key(self, b: str) -> "tuple[str, str] | None":
        """(key, rest) when `b` is a mapping entry, else None."""
        if b[:1] in ("'", '"'):
            q = b[0]
            j = 1
            while j < len(b):
                if b[j] == q:
                    if q == "'" and b[j + 1:j + 2] == "'":
                        j += 2
                        continue
                    break
                j += 2 if (q == '"' and b[j] == "\\") else 1
            after = b[j + 1:]
            if after == ":" or after.startswith(": "):
                return _Parser([b[1:j + 1]]).quoted_line(q), after[1:].strip()
            return None
        if b[:1] in ("{", "[", "|", ">", "&", "*", "!"):
            return None
        if b.endswith(":") and ": " not in b:
            return b[:-1], ""
        k = b.find(": ")
        return (b[:k], b[k + 2:].strip()) if k > 0 else None

    def quoted_line(self, q: str) -> str:
        # A quoted key: the text up to and including its closing quote, on one line.
        return self.quoted(self.lines[0], q, consume=False)

    def mapping(self, ind: int) -> dict:
        out: dict = {}
        while True:
            self.skip()
            if self.i >= len(self.lines) or self.indent() != ind:
                break
            b = self.body()
            if b == "-" or b.startswith("- "):
                break
            kv = self.split_key(b)
            if kv is None:
                raise ValueError(f"line {self.i + 1}: expected 'key: value', got {b[:40]!r}")
            key, rest = kv
            if rest:
                out[str(key)] = self.scalar(rest, ind)
                continue
            self.i += 1
            self.skip()
            if self.i < len(self.lines) and self.indent() > ind:
                out[str(key)] = self.node(self.indent())
            elif self.i < len(self.lines) and self.indent() == ind and (
                    self.body() == "-" or self.body().startswith("- ")):
                out[str(key)] = self.sequence(ind)
            else:
                out[str(key)] = None
        return out

    def sequence(self, ind: int) -> list:
        out: list = []
        while True:
            self.skip()
            if self.i >= len(self.lines) or self.indent() != ind:
                break
            b = self.body()
            if not (b == "-" or b.startswith("- ")):
                break
            content = b[2:].strip()
            if not content:
                self.i += 1
                self.skip()
                out.append(self.node(self.indent()) if self.i < len(self.lines)
                           and self.indent() > ind else None)
                continue
            # The item's own content, re-read as if it started on a line of its own at ind + 2.
            self.lines[self.i] = " " * (ind + 2) + content
            out.append(self.node(ind + 2))
        return out

    def scalar(self, rest: str, parent: int):
        """The value `rest` begins on the current line; consumes it and any continuation."""
        if rest[:1] in ("'", '"'):
            return self.quoted(rest[1:], rest[0])
        if rest == "{}":
            self.i += 1
            return {}
        if rest == "[]":
            self.i += 1
            return []
        if rest[:1] in ("{", "[", "|", ">", "&", "*", "!"):
            raise ValueError(f"line {self.i + 1}: unsupported YAML construct {rest[:20]!r}")
        if " #" in rest:
            rest = rest[:rest.index(" #")].rstrip()
        parts = [rest]
        self.i += 1
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.strip():
                # A blank line inside a plain scalar is a line break, if the scalar goes on.
                j = self.i
                while j < len(self.lines) and not self.lines[j].strip():
                    j += 1
                if j < len(self.lines) and len(self.lines[j]) - len(self.lines[j].lstrip(" ")) > parent:
                    parts.append("\n" * (j - self.i))
                    self.i = j
                    continue
                break
            if len(line) - len(line.lstrip(" ")) <= parent or line.lstrip().startswith("#"):
                break
            parts.append(" " + line.strip() if not parts[-1].endswith("\n") else line.strip())
            self.i += 1
        return _plain("".join(parts)) if len(parts) == 1 else "".join(parts)

    def quoted(self, text: str, q: str, consume: bool = True) -> str:
        """A quoted scalar whose text after the opening quote is `text`, folded over lines."""
        out: list[str] = []
        while True:
            j, escaped_break = 0, False
            while j < len(text):
                c = text[j]
                if c == q:
                    if q == "'" and text[j + 1:j + 2] == "'":
                        out.append("'")
                        j += 2
                        continue
                    if consume:
                        tail = text[j + 1:].strip()
                        if tail and not tail.startswith("#"):
                            raise ValueError(f"line {self.i + 1}: text after a closing quote")
                        self.i += 1
                    return "".join(out)
                if q == '"' and c == "\\":
                    if j + 1 == len(text):
                        escaped_break = True
                        break
                    e = text[j + 1]
                    if e in _HEX:
                        n = _HEX[e]
                        out.append(chr(int(text[j + 2:j + 2 + n], 16)))
                        j += 2 + n
                        continue
                    if e not in _ESCAPES:
                        raise ValueError(f"line {self.i + 1}: unknown escape \\{e}")
                    out.append(_ESCAPES[e])
                    j += 2
                    continue
                out.append(c)
                j += 1
            if not consume:
                raise ValueError("unterminated quoted key")
            if not escaped_break:
                while out and out[-1] in " \t":
                    out.pop()
            self.i += 1
            blanks = 0
            while self.i < len(self.lines) and not self.lines[self.i].strip():
                blanks += 1
                self.i += 1
            if self.i >= len(self.lines):
                raise ValueError("unterminated quoted scalar")
            out.append("\n" * blanks if blanks else ("" if escaped_break else " "))
            text = self.lines[self.i].lstrip(" \t")
