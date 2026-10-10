"""Queue names (早班 / 晚班) and the tool -> game name table.

The queues' former names, 新队列 (AUTO-MAS's default for a new queue) and
"Evening-MAA", can still appear in commands queued on the phone page, skip
marker files and resume markers; canonical() maps them to the current names.
This module imports nothing, so anyone can import it with no cycles.
"""

MORNING = "早班"
EVENING = "晚班"

ALIASES = {
    "新队列": MORNING,
    "Evening-MAA": EVENING,
}


# Tool name -> the game it plays, for anything shown to the user.
GAME_ZH = {"MAA": "明日方舟", "MaaEnd": "终末地", "OK-WW": "鸣潮"}


def canonical(name: str) -> str:
    """Map an old name to the current one; current or unknown names pass through."""
    return ALIASES.get((name or "").strip(), (name or "").strip())
