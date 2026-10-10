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


_CFG_ITEM = re.compile(
    r'##\s*(?P<label>[^\n]+)\n\s*self\.\w+\s*=\s*ConfigItem\(\s*'
    r'"(?P<sec>\w+)"\s*,\s*"(?P<key>\w+)"\s*,(?P<rest>.*?)\n\s*\)',
    re.S)
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
        for i, cm in enumerate(marks):
            game = _CLASS_OF.get(cm.group(1))
            if not game:
                continue
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            for m in _CFG_ITEM.finditer(text[cm.end():end]):
                o = _OPTS.search(m.group("rest"))
                out[game][f'{m.group("sec")}.{m.group("key")}'] = {
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
