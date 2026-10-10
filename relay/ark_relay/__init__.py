"""ark-relay: notification relay for MAA / AUTO-MAS.

Shared parts live in ark_relay.core, each feature in ark_relay.features.<name>;
old module paths still import (see _aliases).
"""
from ark_relay import _aliases

_aliases.install()

__version__ = "0.1.0"
