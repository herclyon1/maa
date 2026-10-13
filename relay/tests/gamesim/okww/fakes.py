"""Pinned stand-ins for the few upstream functions a case does not test (gamesim design 1, rule 2).

Runs inside an OK-WW checkout laid out by ci_prepare.py, like harness.py. A fake replaces one
upstream method for the length of one scenario, and only while that method's body is the one
the fake was written against: the hash is the overlay's own (`_src_sha`, ark_overrides.tasks.py,
and okww_overlay._method_sha, okww_overlay.py:359 - sha1 of inspect.getsource, first 12 hex), so
an upstream change turns every case that leans on the fake into an error first. A pin mismatch
raises RuntimeError, never AssertionError: a red lane must fail at its own assertion, not here.

Why each one exists (the frame library has no open-world frame, frames.json `unrecorded`):
  openF2Book   presses F2 in the world and waits for the book's tab icon; every daily and nest
               case starts with the book already open on the recorded page instead.
  ensure_main  presses Esc until the world's team bar shows; the battle-pass case starts and
               ends in the world, which has no frame.
Pins were read from the fetched upstream copies (relay/tests/gamesim/upstream/okww-<tag>/src) with
okww_overlay._method_sha: the same on v3.6.5, v3.7.3 and v3.7.4.
"""
from __future__ import annotations

import contextlib
import hashlib
import inspect
from unittest import mock

PINS = {
    ("BaseWWTask", "openF2Book"): "1a5b9827a7fb",     # BaseWWTask.py v3.7.4 lines 1016-1039
    ("BaseWWTask", "ensure_main"): "a376a810ce91",    # BaseWWTask.py v3.7.4 lines 717-724
}


def body_sha(fn) -> str:
    """sha1 of the method's source, first 12 hex: what the overlay pins its own copies by."""
    return hashlib.sha1(inspect.getsource(fn).encode("utf-8")).hexdigest()[:12]


@contextlib.contextmanager
def pinned(cls, name: str, replacement):
    """Replace cls.name with `replacement` while its upstream body still hashes to the pin."""
    pin = PINS[(cls.__name__, name)]
    got = body_sha(getattr(cls, name))
    if got != pin:
        raise RuntimeError(f"upstream {cls.__name__}.{name} is {got}, the fake was written against {pin}; "
                           "read the new body and update the fake")
    with mock.patch.object(cls, name, replacement):
        yield


def book_already_open(case):
    """openF2Book's stand-in: the scenario's start state is the page the book shows."""
    def open_book(self, feature="gray_book_all_monsters"):
        case.decide("openF2Book", feature)
    return open_book


def world_already_shown(case):
    """ensure_main's stand-in: no input, the next state is whatever the scenario says."""
    def ensure_main(self, esc=True, time_out=30):
        case.decide("ensure_main", time_out)
    return ensure_main
