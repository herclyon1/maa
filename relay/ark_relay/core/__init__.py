"""Shared parts every feature uses: config, state, process table, desktop agent, logs, game name tables, the tick engine, wording, sending."""


def __getattr__(name):
    # `from ark_relay.core import State` (relay/boot_stages.py says it) gives the ledger's
    # State. Only that name falls through to the ledger.
    if name == "State":
        from ark_relay.core.ledger import State  # noqa: PLC0415
        return State
    raise AttributeError(f"module 'ark_relay.core' has no attribute {name!r}")
