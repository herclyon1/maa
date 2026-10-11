"""Phone orders that wait on disk for the running script to end (CmdQueue).

Split out of phone.py (which still re-exports every name here).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

from ark_relay.features.phone.wire import MAX_AGE

log = logging.getLogger("ark.phone")   # same logger as phone.py: log lines keep their name


# ---------- orders that wait for the run to end ----------
#
# A config write while a script runs is clobbered by AUTO-MAS's in-memory copy,
# so such an order cannot be applied on the spot. It waits here, on disk (a relay
# restart or a reboot
# between the press and the end of the run must not lose it), and
# boot_stages drains it in arrival order once nothing is running, before the
# shutdown decision of that same tick.
CMD_QUEUE_FILE = "phone-queue.json"
# Orders that start a run rather than change a setting. Pressed while a run is
# going they are answered at once and never queued: applied after the run they
# would start one more on top of it (commands.run_script). Every
# other order only writes settings and waits in the queue.
DISPATCHING_ACTIONS = frozenset({"run_now", "echo_farm"})
# Ids of drained orders, remembered so the same order is never queued twice
# (the mailbox's own `_seen` already stops a re-delivery; this is the second lock).
CMD_QUEUE_DONE_KEEP = 200
_CMD_QUEUE_LOCK = threading.Lock()


def cmd_key(body: dict) -> str:
    """What makes an order the same order: ntfy's id, else its send time and content."""
    meta = (body or {}).get("_meta") or {}
    if meta.get("ntfy_id"):
        return str(meta["ntfy_id"])
    rest = {k: v for k, v in (body or {}).items() if k != "_meta"}
    raw = json.dumps([meta.get("sent"), rest], ensure_ascii=False, sort_keys=True, default=str)
    return "h:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# What CmdQueue.add did with an order.
QUEUED, RESENT, SAME = "queued", "resent", "same"


def _content(body: dict) -> str:
    """An order without its envelope: what it asks for, not when or how it came."""
    return json.dumps({k: v for k, v in (body or {}).items() if k != "_meta"},
                      ensure_ascii=False, sort_keys=True, default=str)


def _item_keys(item: dict) -> list[str]:
    """The order's own key plus those of the presses folded into it (RESENT)."""
    return [cmd_key(item["body"])] + [str(k) for k in item.get("also") or []]


def item_sent(item: dict) -> "int | None":
    """The latest send time of a queued order: its own, or a later press of the same
    order folded into it. The final receipt carries it, so the App can match it to
    every press it answers (D207: a receipt answers presses sent no later than it)."""
    meta = (item.get("body") or {}).get("_meta") or {}
    times = [t for t in (meta.get("sent"), item.get("resent")) if isinstance(t, int)]
    return max(times) if times else None


class CmdQueue:
    """Phone orders that arrived while a script was running, oldest first.

    Every item is the order exactly as it arrived (with its "_meta": the receipt
    needs "sent", the de-dup needs "ntfy_id") plus "queued" (unix seconds), and,
    once the same order was pressed again while it waited, "also" (those presses'
    keys) and "resent" (the latest of their send times).
    Written atomically under one lock: the mailbox thread adds, the engine
    thread takes. `pop` removes the item before it is acted on, so a crash
    mid-order loses that one order rather than running it twice.
    """

    def __init__(self, state_dir):
        self.path = Path(state_dir) / CMD_QUEUE_FILE

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"items": [], "done": []}
        except (OSError, ValueError):
            log.warning("手机指令排队文件读不出来，按空的处理：%s", self.path, exc_info=True)
            return {"items": [], "done": []}
        if not isinstance(data, dict):
            return {"items": [], "done": []}
        items = [i for i in data.get("items") or [] if isinstance(i, dict) and isinstance(i.get("body"), dict)]
        done = [str(d) for d in data.get("done") or []]
        return {"items": items, "done": done}

    def _write(self, data: dict) -> None:
        from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["done"] = data["done"][-CMD_QUEUE_DONE_KEEP:]
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False))

    def add(self, body: dict, now: "float | None" = None) -> str:
        """Queue one order. QUEUED when it went in. SAME when this very message is
        already queued or done (a re-delivery). RESENT when it is a new press of
        what the latest waiting order of the same action already asks for, word for
        word (D207): it is not queued a second time, its key and send time are
        kept on the waiting one. Only the latest of that action is compared:
        「开 → 关 → 开」 still ends on 开."""
        key = cmd_key(body)
        with _CMD_QUEUE_LOCK:
            data = self._read()
            if key in data["done"] or any(key in _item_keys(i) for i in data["items"]):
                return SAME
            action = (body or {}).get("action")
            last = next((i for i in reversed(data["items"]) if i["body"].get("action") == action), None)
            if last is not None and _content(last["body"]) == _content(body):
                last["also"] = [str(k) for k in last.get("also") or []] + [key]
                sent = ((body or {}).get("_meta") or {}).get("sent")
                if isinstance(sent, int):
                    last["resent"] = max(sent, last["resent"]) if isinstance(last.get("resent"), int) else sent
                self._write(data)
                return RESENT
            data["items"].append({"body": body, "queued": int(now if now is not None else time.time())})
            self._write(data)
            return QUEUED

    def __len__(self) -> int:
        if not self.path.is_file():
            return 0
        with _CMD_QUEUE_LOCK:
            return len(self._read()["items"])

    def holds(self, body: dict) -> bool:
        """Whether this order is on the queue file: waiting, folded into a waiting
        one, or already taken off to run (the machine check #23)."""
        key = cmd_key(body)
        with _CMD_QUEUE_LOCK:
            data = self._read()
        return key in data["done"] or any(key in _item_keys(i) for i in data["items"])

    def pop(self) -> "dict | None":
        """Take the oldest order off the queue (and remember its key); None when empty."""
        with _CMD_QUEUE_LOCK:
            data = self._read()
            if not data["items"]:
                return None
            item = data["items"].pop(0)
            data["done"].extend(_item_keys(item))
            self._write(data)
            return item


def cmd_expired(item: dict, now: "float | None" = None) -> bool:
    """The mailbox's own window (MAX_AGE, 24 h) applied once more when the order
    finally runs: counted from the phone's send time (its latest press, see
    item_sent), else from when it was queued."""
    sent = item_sent(item)
    if sent is None:
        sent = item.get("queued")
    if not isinstance(sent, (int, float)):
        return False
    return (now if now is not None else time.time()) - sent > MAX_AGE
