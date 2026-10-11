"""Each group alarm is also POSTed straight to the Mac, so the Mac never polls for it.

The user, 2026-10-11 18:25: 「又在那轮询你们他妈只会做轮询是吗」, about the Mac
pulling COS alerts/ every two minutes.
The decision (BOARD/DECISIONS.md, the amended 「D-1011-报警交到手上」): no polling,
the relay pushes.

What is sent. The very row alertlog.py writes to COS alerts/<day>.jsonl (its
FIELDS: ts, game, title, text, version, evidence_run - nothing added), one JSON
object per request:

    POST <Config.alert_push_url>          default http://100.110.87.36:8931/alert
    Content-Type: application/json; charset=utf-8
    body: {"ts": ..., "game": ..., "title": ..., "text": ..., "version": ..., "evidence_run": ...}

A 2xx answer is delivered. No proxy is used (the address is the Mac's Tailscale
address). ARK_ALERT_PUSH_URL in .env overrides the address; empty turns this off.

How. Like errwatch's push queue (errwatch-queue.json): the row is first appended
to state/mac-push-queue.json on the caller's thread, so an alarm the process
dies right after is not lost; a thread of its own then sends the queue oldest
first, each with a TIMEOUT-second limit, and drops an entry only once the Mac
took it. The first entry the Mac cannot be reached for stops the pass; what is
left goes with the next alarm or at the next boot (boot_stages.py). A 4xx other
than 408 / 429 means the Mac refused that entry for good: it is dropped, so it
cannot hold every later alarm behind it. The queue keeps at most MAX_QUEUE
entries (newest kept).

The Mac being asleep or off is a normal state, not a fault: it is logged at INFO
(once per change, like alertlog's COS warning), never as a WARNING - errwatch
pushes every WARNING to the group. The group alarm and the COS copy never wait
for or depend on this. A resend after a lost answer can deliver one row twice;
the Mac side tells them apart by (ts, title).
"""
from __future__ import annotations

import http.client
import json
import logging
import threading
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("ark.macpush")

TIMEOUT = 3.0
QUEUE_FILE = "mac-push-queue.json"
MAX_QUEUE = 500
_RETRY_4XX = (408, 429)          # "try later" answers, kept like a timeout


class MacPush:
    """The on-disk queue of rows for the Mac and the sender that drains it.

    `post(row) -> (verdict, why)` sends one row; verdict is "ok", "drop" (refused
    for good) or "retry". Tests pass a fake; production POSTs over HTTP.
    """

    def __init__(self, state_dir, url: str, timeout: float = TIMEOUT, post=None):
        self.url = str(url or "").strip()
        self._path = Path(state_dir) / QUEUE_FILE
        self._timeout = timeout
        self._post = post or self._http_post
        self._lock = threading.Lock()
        self._busy = False           # a drain is running
        self._again = False          # a row came in while it ran: go round once more
        self._ok = True              # the last attempt reached the Mac
        self._queue: list[dict] = self._load()

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def pending(self) -> list[dict]:
        with self._lock:
            return list(self._queue)

    # ---------- the queue on disk ----------

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            log.info("%s 读不出来（%s），按空队列处理", QUEUE_FILE, type(exc).__name__)
            return []
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []

    def _save(self) -> None:
        """Write the queue (called with the lock held)."""
        from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
        if not self._queue:
            self._path.unlink(missing_ok=True)
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path, json.dumps(self._queue, ensure_ascii=False))

    def add(self, row: dict) -> None:
        """Queue one row (no network)."""
        if not self.enabled:
            return
        with self._lock:
            self._queue.append(dict(row))
            del self._queue[:-MAX_QUEUE]
            self._save()

    # ---------- sending ----------

    def _http_post(self, row: dict) -> tuple[str, str]:
        data = json.dumps(row, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=self._timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500 and exc.code not in _RETRY_4XX:
                return "drop", f"HTTP {exc.code}"
            return "retry", f"HTTP {exc.code}"
        except (OSError, http.client.HTTPException) as exc:   # refused, timeout, reset
            return "retry", f"{type(exc).__name__}: {exc}"
        return "ok", ""

    def _drain(self) -> int:
        """Send the queue oldest first until it is empty or the Mac cannot be reached. -> rows left."""
        sent = 0
        while True:
            with self._lock:
                if not self._queue:
                    break
                head = self._queue[0]
            verdict, why = self._post(head)
            if verdict == "retry":
                with self._lock:
                    left = len(self._queue)
                if self._ok:
                    log.info("报警直送 Mac 没送到（%s），%d 条留着，下一条报警或下次开机再补", why, left)
                self._ok = False
                return left
            with self._lock:
                # The head can only have gone by the MAX_QUEUE trim in add().
                if self._queue and self._queue[0] is head:
                    self._queue.pop(0)
                    self._save()
            if verdict == "drop":
                log.info("Mac 拒收这条报警（%s），丢掉不再补：%s", why, head.get("title", ""))
            else:
                sent += 1
        if not self._ok:
            log.info("报警直送 Mac 又通了，这次送到 %d 条", sent)
        self._ok = True
        return 0

    def flush(self) -> "int | None":
        """Send what is queued. -> rows left, or None when another flush is already running
        (that one goes round again and takes what was added)."""
        if not self.enabled:
            return None
        with self._lock:
            if self._busy:
                self._again = True
                return None
            self._busy, self._again = True, False
        try:
            while True:
                left = self._drain()
                with self._lock:
                    if not self._again:
                        self._busy = False
                        return left
                    self._again = False
        except BaseException:
            with self._lock:
                self._busy = False
            raise

    def flush_async(self) -> "threading.Thread | None":
        """flush() on a thread of its own (never raises into the caller)."""
        if not self.enabled:
            return None

        def run() -> None:
            try:
                self.flush()
            except Exception:   # a bug here must not break anything else
                log.warning("报警直送 Mac 出错", exc_info=True)

        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        name = f"{errwatch.PUSH_THREAD}-mac" if errwatch.in_push_path() else "alarm-mac"
        t = threading.Thread(target=run, name=name, daemon=True)
        t.start()
        return t

    def push(self, row: dict) -> "threading.Thread | None":
        """Queue the row, then send the queue on a thread. -> that thread or None."""
        self.add(row)
        return self.flush_async()


def for_config(cfg) -> MacPush:
    return MacPush(cfg.state_dir, getattr(cfg, "alert_push_url", ""))
