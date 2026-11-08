"""Another try, inside the caller's own time limit, for a request the network cut short.

Dispatch relay-opt-round3-1108 O-03: cos_store.cos_put / cos_get (every phone-state push,
heartbeat and alarm copy) and maintenance/efstatus.update_hint were one urlopen each, so one
reset or one 502 from the gateway in front counted as COS or the bulletin being down. The
30 s heartbeat stays one try between beats (cos_put retry=False: its next beat is the retry,
round3b-1108); its shutdown bye is retried.

A retry never stretches the caller's limit. The phone state's Mailbox.COS_TIMEOUT (8 s) has
to fit in the 30 s a Windows service stop allows, and a miss there already goes over ntfy; so
call() tries again only while time is left of `limit`: a timeout that used it all is not
tried again, a failure that came back fast is, after the full-jitter pause notify._post uses
(notify._backoff), with what is left as the next attempt's limit. At most notify._RETRIES
attempts, the same as a push.

Cut short (transient()): a timeout, a body that ended early, a reset or refused connection,
a DNS failure, and the gateway statuses 502 / 503 / 504 - the server in front could not get
an answer from the one behind it
(https://www.rfc-editor.org/rfc/rfc9110#name-502-bad-gateway). Any other HTTP status is the
server's answer and is never tried again: a 404 stays a 404, a 403 a 403.

Each failed attempt is one INFO line. An attempt that went through after a failed one is one
WARNING marked errwatch.recovered() (daily report only; USER-SWITCHES.txt,
netretry.py:call). The last failure is raised to the caller, which reports it as before.
"""
from __future__ import annotations

import http.client
import logging
import time
import urllib.error

from ark_relay.core.notify import _RETRIES as ATTEMPTS
from ark_relay.core.notify import _backoff

log = logging.getLogger("ark.netretry")

GATEWAY = frozenset({502, 503, 504})
# The pause between attempts goes through here, looked up at each call: the tests' door
# (they set it to a no-op instead of patching time.sleep for every module).
_sleep = time.sleep


def transient(exc: BaseException) -> bool:
    """`exc` is the network cutting a request short, worth another try (the module docstring)."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in GATEWAY
    return isinstance(exc, (TimeoutError, http.client.IncompleteRead, http.client.BadStatusLine,
                            ConnectionError, urllib.error.URLError))


def call(fn, what: str, limit: float, *, detail: str = "", clock=None, sleep=None):
    """fn(seconds) -> its result: the first attempt gets `limit`, each later one what is left
    of it. A transient failure is tried again while time is left after the pause; anything
    else, the last attempt's failure, or no time left raises. `what` names the request in
    plain words (the recovered WARNING's first line is quoted in the daily report); `detail`
    (a key, a URL) and the first failure go on its second line. `clock` / `sleep` (default
    time.monotonic / the module's _sleep, looked up at call time) are the tests' doors."""
    clock = clock or time.monotonic
    sleep = sleep or _sleep
    start = clock()
    first = ""
    for attempt in range(ATTEMPTS):
        left = limit - (clock() - start)
        try:
            got = fn(limit if attempt == 0 else left)
        except Exception as exc:
            pause = _backoff(attempt)
            if (not transient(exc) or attempt + 1 >= ATTEMPTS
                    or limit - (clock() - start) - pause <= 0):
                raise
            first = first or f"{type(exc).__name__}: {exc}"
            log.info("%s 第 %d 次没成（%s: %s），%.1f 秒后再试：%s", what, attempt + 1, type(exc).__name__, exc,
                     pause, detail)
            sleep(pause)
            continue
        if attempt:
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415 - avoid an import cycle
            log.warning("%s第一次没成，第 %d 次成了\n%s 第一次：%s", what, attempt + 1, detail, first,
                        extra=errwatch.recovered())
        return got
    raise RuntimeError("unreachable")
