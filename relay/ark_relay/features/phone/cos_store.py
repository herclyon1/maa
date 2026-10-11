"""The phone state and heartbeat objects on Tencent COS: their names and the PUT / GET.

Split out of phone.py (which still re-exports every name here).
"""
from __future__ import annotations

import hashlib
import urllib.error
import urllib.request

from ark_relay.features.phone.wire import _UA


# ---------- the whole state on Tencent COS ----------
#
# The state is kept off ntfy's 250 a day (the user's decision, 2026-10-02 22:22):
# a state is ~13 KB gzipped, four ntfy messages. Every state push PUTs the same
# envelope pack()
# makes (plain or gz, exactly what would have gone to ntfy, PIN inside) to the
# evidence bucket, and only a one-line notice `state <ts> <bytes>` goes to the
# topic. The App GETs the object on that notice, on open and on refresh.
#
# The object is readable by anyone who has its URL (public-read ACL), and its
# name comes from the topic: whoever can read the topic on ntfy.sh today can
# read the state, nobody else - the same exposure as the topic. sha256 so the
# name does not give the topic back (and with it the command channel).
#
# The bucket's lifecycle rule (expire-30d-not-relay, docs/OPERATIONS.md)
# covers state/: COS counts Days from the object's last modification, and
# every push rewrites it, so only a machine silent for 30 days loses it.
STATE_PREFIX = "state"


def state_key(topic: str) -> str:
    """The object name for this topic; the App derives the same (Relay.stateKey)."""
    t = (topic or "").strip().lower()
    return f"{STATE_PREFIX}/{hashlib.sha256(t.encode('utf-8')).hexdigest()[:32]}.json"


def hb_key(topic: str) -> str:
    """The heartbeat object next to the state: `state/<same hash>.hb.json`
    (the App derives the same, Relay.hbURL). Built from state_key so the two
    names cannot drift apart."""
    return state_key(topic)[:-len(".json")] + ".hb.json"


def cos_put(cos, key: str, data: bytes, timeout: float, *, public: bool = True,
            content_type: str = "application/json; charset=utf-8") -> "str | None":
    """PUT `data` to `key`: public-read by default (the App has no COS keys), never
    cached (or the App reads a stale copy). `public=False` leaves the bucket's
    private ACL (alertlog.py: only key holders read the alarm copy). None when
    stored, else why not - the caller says what that means for its own object
    in its own log line."""
    headers = {"Authorization": cos.authorization("PUT", key),
               "Cache-Control": "no-store",
               "Content-Type": content_type,
               "User-Agent": _UA}
    if public:
        headers["x-cos-acl"] = "public-read"
    req = urllib.request.Request(f"https://{cos.host}/{key}", data=data, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
    except urllib.error.HTTPError as exc:
        return f"回 {exc.code}"
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never raised
        return str(exc) or type(exc).__name__
    return None if 200 <= status < 300 else f"回 {status}"


def cos_get(cos, key: str, timeout: float) -> "tuple[bytes | None, str]":
    """GET `key` with the same signing as cos_put: (body, '') when it is there,
    (None, '') when the object does not exist (404), (None, why) for anything
    else. Never raises."""
    req = urllib.request.Request(f"https://{cos.host}/{key}",
                                 headers={"Authorization": cos.authorization("GET", key),
                                          "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), ""
    except urllib.error.HTTPError as exc:
        return None, ("" if exc.code == 404 else f"回 {exc.code}")
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never raised
        return None, str(exc) or type(exc).__name__


def state_cos(cfg):
    """The bucket client from the machine's COS_* (config.Config.cos_*), or
    None when this machine has no COS - then states go to ntfy in pieces."""
    keys = [getattr(cfg, f"cos_{k}", "") or "" for k in ("secret_id", "secret_key", "bucket", "region")]
    if not all(keys):
        return None
    from ark_relay.features.evidence.evidence import Cos  # noqa: PLC0415
    return Cos(*keys)
