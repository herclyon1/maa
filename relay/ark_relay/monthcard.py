"""Monthly-card expiry reminders (user order 2026-09-26 02:47, spec BOARD/月卡到期提示-规格.md).

The user buys the monthly cards by hand, so nothing on the machine knows when
they run out. He registers each purchase on the phone page ("充值了 N 次") or
sets what the game shows ("还剩 X 天"); the relay keeps the last day a reward
can still be claimed and, from five days before it, sends one Server酱 line a
day until he renews or the card lapses.

His own definition of the last claim day, verbatim: 「有效期比如说还剩一天，那就是到明天登录时领取算最后一次」
So the last claim day is today + the remaining days. A renewal adds 30 days per
purchase on top of the last claim day; a card already lapsed restarts today
(the day of purchase is day 1).

Days are counted on the relay's clock (SERVER_TZ), like every other day here.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.monthcard")

# Days added by one purchase, per game.
DAYS = {
    # PRTS wiki, item page for the monthly card voucher: 「增加30天月卡有效期」
    "明日方舟": 30,
    # PlayStation Store UB0018-PPSA18538_00-ZMDPS5GL0MONTHLY: 「同时获得30天的月卡权益」
    "终末地": 30,
    # 月相观测卡, 30 days per purchase: shop text as quoted by gamekee / 17173; the
    # official page was not found (spec, 「未核对官方原文」).
    "鸣潮": 30,
}

WARN_DAYS = 5          # start warning five days ahead, his words: 「临近到期前五天开始通知」
MAX_ADD = 12
MAX_LEFT = 400
FILE = "monthcard.json"
# A phone-computed `last` further out than this is refused: the most the page can reach is
# left 400, or a card with up to 400 days left topped up 12 times.
MAX_AHEAD = MAX_LEFT + 30 * MAX_ADD


def _today() -> date:
    return datetime.now(tz=SERVER_TZ).date()


def _load(state_dir) -> dict:
    try:
        return json.loads((Path(state_dir) / FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        # Keep the unreadable file beside it: the next registration rewrites FILE, and his
        # earlier entries would otherwise be gone without a trace.
        bad = Path(state_dir) / (FILE + ".bad")
        try:
            bad.write_bytes((Path(state_dir) / FILE).read_bytes())
        except OSError:
            pass
        log.error("monthcard.json unreadable, treated as empty; copy kept as %s", bad, exc_info=True)
        return {}


def _save(state_dir, data: dict) -> None:
    atomic_write_text(Path(state_dir) / FILE, json.dumps(data, ensure_ascii=False, indent=1))


def _md(d: date) -> str:
    return f"{d.month} 月 {d.day} 日"


def _line(game: str, last: date, today: date) -> str:
    left = (last - today).days
    if left < 0:
        return f"{game}月卡：已过期（最后一次领取是 {_md(last)}）"
    return f"{game}月卡：最后一次领取 {_md(last)}（还剩 {left} 天）"


def _int(v, lo: int, hi: int) -> "int | None":
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi and str(n) == str(v).strip() else None


def _when(v) -> "datetime | None":
    """An ISO timestamp from the phone (`toISOString`, trailing Z) or from this file."""
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        t = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)


def apply(state_dir, cmd: dict, today: "date | None" = None) -> tuple[bool, str]:
    """The phone's `monthcard` order: `{"game", "add": N}` or `{"game", "left": X}`.

    Since 2026-09-26 03:30 the phone computes the date itself and shows it at once.
    The user asked why registering needs the game machine at all, verbatim: 「为什么月卡功能要绑定游戏机？我刚登记还跟我提示说要等电脑开机」
    So the order also carries `last` (the last claim day it computed) and `at` (when he registered).
    The machine may read the order the next morning, and counting from that day would
    put the dates days apart; so `last` is taken as is when present, `at` is stored as
    the registration time, and an order older than the stored registration (a resend
    arriving after a newer one) changes nothing. add / left are still checked, and
    still used when `last` is absent.
    """
    today = today or _today()
    game = str(cmd.get("game") or "").strip()
    if game not in DAYS:
        return False, f"月卡：不认识的游戏 {game!r}，只认 明日方舟 / 终末地 / 鸣潮"
    has_add, has_left = cmd.get("add") is not None, cmd.get("left") is not None
    if has_add == has_left:
        return False, "月卡：add（充值次数）和 left（还剩几天）要填且只填一个"
    data = _load(state_dir)
    rec = dict(data.get(game) or {})
    at = _when(cmd.get("at"))
    if cmd.get("at") is not None and at is None:
        return False, f"月卡：登记时间看不懂，收到 {cmd.get('at')!r}"
    stored = _when(rec.get("set"))
    phone_last = None
    if cmd.get("last") is not None:
        try:
            phone_last = date.fromisoformat(str(cmd.get("last")).strip())
        except ValueError:
            return False, f"月卡：最后领取日要是 YYYY-MM-DD，收到 {cmd.get('last')!r}"
        if (phone_last - today).days > MAX_AHEAD:
            return False, f"月卡：最后领取日 {phone_last.isoformat()} 离今天超过 {MAX_AHEAD} 天，没记"
    if has_left:
        left = _int(cmd.get("left"), 0, MAX_LEFT)
        if left is None:
            return False, f"月卡：还剩天数要是 0 到 {MAX_LEFT} 的整数，收到 {cmd.get('left')!r}"
        last = today + timedelta(days=left)
    else:
        n = _int(cmd.get("add"), 1, MAX_ADD)
        if n is None:
            return False, f"月卡：充值次数要是 1 到 {MAX_ADD} 的整数，收到 {cmd.get('add')!r}"
    if at is not None and stored is not None and at < stored:
        return True, _line(game, date.fromisoformat(rec["last"]), today) + "（已有更晚的登记，这条没改）"
    if phone_last is not None:
        last = phone_last
    elif not has_left:
        prev = date.fromisoformat(rec["last"]) if rec.get("last") else None
        if prev is not None and prev >= today:
            last = prev + timedelta(days=DAYS[game] * n)
        else:
            # Never registered, or lapsed: the purchase day is day 1.
            last = today + timedelta(days=DAYS[game] * n - 1)
    rec.update(last=last.isoformat(),
               set=(at or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ).isoformat(timespec="milliseconds"))
    # milliseconds: the page compares 登记于 with its own registration time, which has them
    data[game] = rec
    _save(state_dir, data)
    return True, _line(game, last, today)


def status(state_dir, today: "date | None" = None) -> dict:
    """`relay.月卡` for the phone page: registered games only."""
    today = today or _today()
    out = {}
    for game, rec in _load(state_dir).items():
        if game not in DAYS or not isinstance(rec, dict) or not rec.get("last"):
            continue
        try:
            last = date.fromisoformat(rec["last"])
        except ValueError:
            continue
        left = (last - today).days
        out[game] = {"最后领取": last.isoformat(), "还剩": left, "已过期": left < 0}
        if rec.get("set"):
            out[game]["登记于"] = rec["set"]   # the phone keeps whichever registration is newer
    return out


def due_notice(state_dir, today: "date | None" = None) -> "tuple[str, str] | None":
    """Today's reminder: (title, body), or None when nothing is due or it already went out today.

    The caller sends it and then calls `mark_sent`, so a push that reached nobody
    is tried again on the next tick instead of being lost for the day.
    """
    today = today or _today()
    due = [(g, v) for g, v in status(state_dir, today).items() if 0 <= v["还剩"] <= WARN_DAYS]
    if not due:
        return None
    data = _load(state_dir)
    if data.get("_notified") == today.isoformat():
        return None
    due.sort(key=lambda gv: gv[1]["还剩"])
    lines = [f"{g}月卡还剩 {v['还剩']} 天，最后一次领取是 {_md(date.fromisoformat(v['最后领取']))}"
             for g, v in due]
    return "💳 月卡快到期", "\n".join(lines)


def mark_sent(state_dir, today: "date | None" = None) -> None:
    data = _load(state_dir)
    data["_notified"] = (today or _today()).isoformat()
    _save(state_dir, data)
