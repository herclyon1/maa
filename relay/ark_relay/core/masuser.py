"""Where an AUTO-MAS MAA user keeps each setting.

AUTO-MAS v5.7.0-beta.3 (installed by its own updater on the game machine 10-14 08:46 Beijing)
moved the MAA user's stage items out of the Info group into a new Stage group, and the
annihilation and base-plan items into Task (app/models/config.py of that tag: Stage_Stage =
ConfigItem("Stage", "Stage", "-", legacy_group="Info"), Task_Annihilation, ...).
ConfigBase.load (app/models/ConfigBase.py) reads the old Info value once as a fallback and
toDict writes back only the new groups, so after the first start the file has Stage.Stage and
no Info.Stage, and the backend refuses "Info.Stage" (its get() raises for an unknown item).

The relay read and wrote Info.* everywhere and saw nothing from then on: the stage gate
logged its "current stage" placeholder at 10-14 08:55:27 instead of YW-4 (08:46:09, before the
update); the phone snapshot, the plan and the weekly annihilation switch read empty values;
the phone's stage and sanity-potion changes asked for items the backend no longer has.

Every reader and writer goes through here, so older AUTO-MAS (Info) and newer (Stage / Task)
both work: a key is taken from its new group when the user has it there, else from Info.
"""
from __future__ import annotations

# key -> the group AUTO-MAS v5.7.0-beta.3 keeps it in (Info before that).
MOVED = {
    "Stage": "Stage", "Stage_1": "Stage", "Stage_2": "Stage", "Stage_3": "Stage",
    "StageMode": "Stage", "MedicineNumb": "Stage", "SeriesNumb": "Stage",
    "Annihilation": "Task", "AnnihilationStartWeekday": "Task",
    "InfrastMode": "Task", "InfrastName": "Task",
}


def group_of(user: dict, key: str) -> str:
    """The group that holds `key` for this user: its new group when the user has it there,
    else Info (an AUTO-MAS from before v5.7.0-beta.3)."""
    new = MOVED.get(key)
    if new and isinstance(user.get(new), dict) and key in user[new]:
        return new
    return "Info"


def get(user: dict, key: str, default=None):
    """The value of `key` wherever this user keeps it."""
    return (user.get(group_of(user, key)) or {}).get(key, default)


def resolve(user: dict, old_path: str) -> str:
    """An "Info.<key>" path rewritten to where this user keeps the key now; other paths as is."""
    group, _, key = old_path.partition(".")
    if group == "Info" and key in MOVED:
        return f"{group_of(user, key)}.{key}"
    return old_path


def info_view(user: dict) -> dict:
    """The user's Info as an AUTO-MAS from before v5.7.0-beta.3 had it: Info plus the moved
    items taken from their new groups."""
    out = dict(user.get("Info") or {})
    for key, group in MOVED.items():
        src = user.get(group)
        if isinstance(src, dict) and key in src:
            out[key] = src[key]
    return out
