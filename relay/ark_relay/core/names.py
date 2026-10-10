"""Queue names, plus compatibility with the names they used to have.

On 2026-09-01 the user asked for the queues to be renamed to 早班 and 晚班,
so they read at a glance. They used to be called 新队列 (the default name
AUTO-MAS gives a newly created queue) and "Evening-MAA".

The old names can still show up in: commands already queued on the phone
page, skip marker files, and resume markers. The rename must not turn those
into "no such queue" - everything goes through canonical().
This module imports nothing, so anyone can reference it with no cycles.
"""

MORNING = "早班"
EVENING = "晚班"

ALIASES = {
    "新队列": MORNING,
    "Evening-MAA": EVENING,
}


def canonical(name: str) -> str:
    """Map an old name to the current one; current or unknown names pass through."""
    return ALIASES.get((name or "").strip(), (name or "").strip())
