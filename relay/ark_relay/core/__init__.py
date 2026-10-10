"""Shared parts every feature uses: config, state, process table, desktop agent, logs, game name tables, the tick engine, wording, sending."""


def __getattr__(name):
    # relay/boot_stages.py still says `from ark_relay.core import State`: the ledger was the
    # module ark_relay.core before the 2026-10-11 move. Only that name falls through to it.
    if name == "State":
        from ark_relay.core.ledger import State  # noqa: PLC0415
        return State
    raise AttributeError(f"module 'ark_relay.core' has no attribute {name!r}")
