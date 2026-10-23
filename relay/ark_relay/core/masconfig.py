"""AUTO-MAS's settings files as the relay reads them, from either layout.

Up to v5.7 AUTO-MAS kept config/ScriptConfig.json, QueueConfig.json and PlanConfig.json, each
    {"instances": [{"uid", "type"}], <uid>: {..., "SubConfigsInfo": {<Kind>: <same shape>}}}
v5.8.0-beta.1 (installed on the machine 2026-10-23 08:48 Beijing) migrates them to scripts.yaml,
queues.yaml and plans.yaml (config/.config-migration-v2.json) and moves the JSON files into
config/legacy-json, where they stay as they were at the migration:
    {"order": [{"uid", "type"}], "data": {<uid>: {..., <Kind>: <same shape>}}}
That morning every reader found its JSON gone (「设置里一个脚本、队列都没有」, 「读取
QueueConfig.json 失败: [Errno 2]」, ledger #113). read() gives the v5.7 shape from either, so each
reader keeps its one walk; the JSON wins while it exists, i.e. on an AUTO-MAS before v5.8.

Only reading. A relay that wrote a JSON file next to the YAML would write where AUTO-MAS no
longer looks, and the file would then shadow the YAML for every reader here; the file-edit
fallbacks (commands._safe_rewrite, queues) read before they write, so with no JSON they fail
loudly instead.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from ark_relay.core import miniyaml

# The JSON file a reader asks for -> the YAML file v5.8 keeps the same settings in.
YAML_OF = {"ScriptConfig.json": "scripts.yaml", "QueueConfig.json": "queues.yaml",
           "PlanConfig.json": "plans.yaml"}
# v5.8 also writes every time as UTC ISO ('2000-01-01T01:00:00Z' for the 09:00 morning queue),
# where v5.7 wrote the machine's local time in a per-field form (legacy-json/QueueConfig.json of
# the same machine, 2026-10-23: "Time": "09:00", "LastTimedStart": "2026-10-22 09:00",
# "LastStartupTime": "2000-01-01", "LastProxyDate": "2026-10-22", "NextRunAt":
# "2000-01-01 00:00:00"). plan._hhmm reads "HH:MM" and found no time in the ISO form, so the
# times go back to those forms; any other key gets the date and time.
_ISO_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")
_TIME_FORM = {"Time": "%H:%M", "LastTimedStart": "%Y-%m-%d %H:%M", "LastStartupTime": "%Y-%m-%d",
              "LastProxyDate": "%Y-%m-%d"}


def source(path: Path) -> Path:
    """The file that holds what `path` names: the JSON while it exists, else its YAML."""
    path = Path(path)
    alt = YAML_OF.get(path.name)
    if alt and not path.exists() and (path.parent / alt).exists():
        return path.parent / alt
    return path


def read(path: Path) -> dict:
    """The settings `path` names, in the v5.7 JSON shape.

    Raises what reading the JSON would (OSError, ValueError) when neither file can be read,
    so a reader's error handling stays as it was."""
    src = source(path)
    text = Path(src).read_text(encoding="utf-8")
    if src.suffix == ".json":
        return json.loads(text)
    doc = miniyaml.loads(text)
    if not isinstance(doc, dict):
        raise ValueError(f"{src.name}: not a mapping")
    return legacy(doc)


def legacy(node: dict) -> dict:
    """v5.8's {"order", "data"} collection as v5.7's {"instances", <uid>: ...}."""
    out: dict = {"instances": list(node.get("order") or [])}
    for uid, item in (node.get("data") or {}).items():
        out[str(uid)] = _item(item)
    return out


def _item(item):
    if not isinstance(item, dict):
        return item
    plain, subs = {}, {}
    for k, v in item.items():
        if _collection(v):
            subs[k] = legacy(v)
        else:
            plain[k] = _local(v, k)
    if subs:
        plain["SubConfigsInfo"] = subs
    return plain


def _local(v, key: str = ""):
    """`v` with v5.8's UTC ISO times put back into v5.7's local forms (_TIME_FORM)."""
    if isinstance(v, dict):
        return {k: _local(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_local(x, key) for x in v]
    if isinstance(v, str) and _ISO_Z.fullmatch(v):
        from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415 - config imports a lot
        at = datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(SERVER_TZ)
        return at.strftime(_TIME_FORM.get(key, "%Y-%m-%d %H:%M:%S"))
    return v


def _collection(v) -> bool:
    return isinstance(v, dict) and set(v) == {"order", "data"}
