"""Score every code version by how the real runs under it went.

`record` is called from append_ledger (core/ledger.py), which every finished run
passes through, and counts the run against the code version running at the time
(runs the red button cut short are not counted). A run counts as failed only when
it failed and was not superseded by a retry (`transitional`): a round fixed by a
retry is not a failure of the code.

`line` is the one-line summary; report._compose_daily logs it.
"""
from __future__ import annotations

from datetime import datetime

from ark_relay.core.config import SERVER_TZ, USER_TZ

# One version's scoreboard: {"runs": total runs, "failed": failed runs not
# superseded by a retry, "since": timestamp of the first run}.
# Only this many versions are kept (by sorted version string) so state.json stays bounded.
KEEP_VERSIONS = 8


def record(store, code_version: str, ok: bool, transitional: bool = False) -> None:
    """Count one finished run against the code version that ran it."""
    if not code_version:
        return                     # no version, no record: an empty key is never written
    board = dict(store.get("versions", "scoreboard") or {})
    row = dict(board.get(code_version) or {})
    row["runs"] = int(row.get("runs") or 0) + 1
    if not ok and not transitional:
        row["failed"] = int(row.get("failed") or 0) + 1
    row.setdefault("since", datetime.now(tz=SERVER_TZ).isoformat(timespec="seconds"))
    board[code_version] = row
    for old in sorted(board)[:-KEEP_VERSIONS]:
        board.pop(old, None)
    store.set("versions", "scoreboard", board)


def line(store, code_version: str) -> str:
    """One line on how `code_version` has run so far. '' when there is no version."""
    if not code_version:
        return ""
    row = (store.get("versions", "scoreboard") or {}).get(code_version)
    if not row or not row.get("runs"):
        return f"代码 v{code_version} · 这版还没跑过一趟"
    runs, failed = int(row["runs"]), int(row.get("failed") or 0)
    since = ""
    try:
        t = datetime.fromisoformat(str(row.get("since") or ""))
        since = f"（自 {t.astimezone(USER_TZ):%m-%d %H:%M} 起）"
    except ValueError:
        pass
    if failed:
        return f"代码 v{code_version} · 这版跑过 {runs} 趟，失败 {failed} 趟{since}"
    return f"代码 v{code_version} · 这版跑过 {runs} 趟，一趟没失败{since}"
