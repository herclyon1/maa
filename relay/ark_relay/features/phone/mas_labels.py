"""Chinese labels for AUTO-MAS config fields, read from AUTO-MAS's own models.

AUTO-MAS's UI is in Chinese and each field's label is in its models: one line of
`## 中文名` above each ConfigItem, with the legal values inside
OptionsValidator([...]). They are read from there rather than translated here, so
a field upstream renames keeps its label. phone.state_payload sends them as
"options".
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("ark.phone")   # same logger as phone.py: log lines keep their module name


# The start of one labelled field: a `## 中文名` line, then `self.X = ConfigItem(` in a
# class body or `config.X = ConfigItem(` in a module-level helper the class calls
# with itself (init_maaend_task_config(self): the MaaEnd sanity-task fields). The
# call's arguments are cut out with balanced parentheses (_call_args): a one-line
# ConfigItem(...) has no `\n)` of its own, and a lazy match up to one swallowed
# the next field (audit 11 #4, 2026-10-13: 7 of the 19 SHOWN fields unlabelled).
_ITEM_HEAD = re.compile(r"##\s*(?P<label>[^\n]+)\n\s*(?:self|config)\.\w+\s*=\s*ConfigItem\(")
_SEC_KEY = re.compile(r'\s*"(?P<sec>\w+)"\s*,\s*"(?P<key>\w+)"\s*(?:,|$)')
_DEF = re.compile(r"^def\s+(\w+)\s*\(", re.M)
# A line at column 0 that is not a comment or the close of a wrapped signature.
_TOP_LEVEL = re.compile(r"^(?=[^\s#)\]])", re.M)
_OPTS = re.compile(r"OptionsValidator\(\s*\[(.*?)\]", re.S)
_QUOTED = re.compile(r"""["']([^"']+)["']""")


# One class per script: MaaUserConfig / MaaEndUserConfig / OkwwUserConfig.
# Matching "section.key" globally would cross labels between identically named
# fields, so the classes are kept apart.
_CLASS = re.compile(r"^class\s+(\w+)", re.M)
_CLASS_OF = {"MaaUserConfig": "MAA", "MaaEndUserConfig": "MaaEnd",
             "OkwwUserConfig": "OK-WW"}


def _mas_labels(automas_dir) -> dict:
    """Chinese labels and legal values per script. `{"MAA": {"Info.Stage": {...}}}`"""
    out: dict = {"MAA": {}, "MaaEnd": {}, "OK-WW": {}}
    if not automas_dir:
        return out
    models = Path(automas_dir) / "app" / "models"
    if not models.is_dir():
        log.warning("找不到 AUTO-MAS 的 models 目录，手机上只能显示英文字段名")
        return out
    for f in sorted(models.glob("*.py")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        marks = list(_CLASS.finditer(text))
        helpers = _helpers(text)
        for i, cm in enumerate(marks):
            game = _CLASS_OF.get(cm.group(1))
            if not game:
                continue
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            body = text[cm.end():end]
            found = _items(body)
            # Module-level helpers the class calls with itself declare fields too.
            for name in dict.fromkeys(re.findall(r"\b(\w+)\(self\)", body)):
                for path, info in _items(helpers.get(name, "")).items():
                    found.setdefault(path, info)
            out[game].update(found)
    return out


def _helpers(text: str) -> dict[str, str]:
    """Module-level functions: name -> source, up to the next top-level line."""
    out = {}
    for m in _DEF.finditer(text):
        line_end = text.find("\n", m.end())
        nxt = _TOP_LEVEL.search(text, line_end + 1) if line_end >= 0 else None
        out[m.group(1)] = text[m.start():nxt.start() if nxt else len(text)]
    return out


def _call_args(text: str, start: int) -> "str | None":
    """The arguments of the call whose `(` ends just before `start`, up to its
    matching `)`; quotes and comments are skipped. None when it never closes."""
    depth, i, quote = 1, start, ""
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "#":
            j = text.find("\n", i)
            i = len(text) if j < 0 else j
            continue
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


def _items(text: str) -> dict:
    """Every labelled ConfigItem("Section", "Key", ...) in `text`: {"Section.Key": {label, options}}."""
    out: dict = {}
    for m in _ITEM_HEAD.finditer(text):
        args = _call_args(text, m.end())
        sk = _SEC_KEY.match(args) if args is not None else None
        if not sk:
            continue
        o = _OPTS.search(args)
        out[f'{sk.group("sec")}.{sk.group("key")}'] = {
            "label": m.group("label").strip(),
            "options": _QUOTED.findall(o.group(1)) if o else None,
        }
    return out


# The items the phone displays. Only these are sent: all ~154 labels together push
# one message past ntfy's size limit, the message is truncated, the page's
# JSON.parse fails and the phone shows the machine as 「关机中」.
SHOWN = (
    "Info.Stage", "Info.StageMode", "Info.MedicineNumb", "Info.SeriesNumb",
    "Info.Annihilation", "Task.IfFight", "Task.IfActivityFirst",
    "Task.ActivityStageIndex", "Task.ActivityMedicineNumb",
    "Task.IfSanity", "Task.IfAutoUseSpMedication", "Task.SanityTaskType",
    "Task.AutoEssenceSpecifiedLocation",
    "Task.WhichToFarm", "Task.WhichTacetSuppressionToFarm",
    "Task.WhichForgeryChallengeToFarm", "Task.MaterialSelection",
    "Task.FarmNightmareNestForDailyEcho", "Task.TaskIndex",
)


def _options(cfg) -> dict:
    """Per-game options. When they cannot be read, none are sent and the page
    falls back to a text box for that item."""
    out: dict = {"MAA": {}, "MaaEnd": {}, "OK-WW": {}}
    try:
        names: dict = {}
        for game, items in _mas_labels(getattr(cfg, "automas_dir", None)).items():
            for path, info in items.items():
                if path not in SHOWN:
                    continue
                names[f"{game}|{path}"] = info["label"]
                # Only the Chinese field names are sent, not the candidate lists:
                # the stage list alone is over a thousand bytes and would push the
                # packet towards ntfy's size limit.
        out["_labels"] = names
    except Exception:
        log.warning("AUTO-MAS 的中文标注读不到", exc_info=True)
    return out
