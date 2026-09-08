"""Score every code version by how the real runs under it actually went.

Why this exists — the user's order on 2026-09-06, after being told once too
often that something was fixed:

    「设计一个彻底让你不能偷懒的东西。」
    「下一趟真实班次自动给这版打分。日报末尾固定一行：『代码 v…，这版跑过 N 趟，
     失败 M 趟』。这行由中继算，不经我手。我说『修好了』而它写『失败 1 趟』，
     谎话当场现形。」

So the count is taken where run outcomes already land — `Engine.append_ledger`,
the one funnel every finished run passes through — and keyed by the code version
that was running at the time. Nothing I write into a report can move it.

A run counts as failed only when it failed *and* was not superseded by a retry
(`transitional`), because a retried-and-fixed round is not a failure of the
code; counting it would make the number cry wolf and get ignored, which is the
one way this line could fail at its job.
"""
from __future__ import annotations

from datetime import datetime

from .config import SERVER_TZ, USER_TZ

# 一个版本的记分牌：{"runs": 总趟数, "failed": 真失败趟数, "since": 第一趟的时刻}
# 只留最近这些个版本，免得 state.json 无限长——部署一天十几次，一周就上百个键。
KEEP_VERSIONS = 8


def record(store, code_version: str, ok: bool, transitional: bool = False) -> None:
    """Count one finished run against the code version that ran it."""
    if not code_version:
        return                     # 版本号读不到时不记——记成空键比不记更难查
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
    """The one line that rides on every daily report. '' when nothing to say."""
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
