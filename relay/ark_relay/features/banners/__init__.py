"""Banner and event announcements for the three games.

banners.py is the entry point; the game modules import from it, so it is loaded
first whichever module is imported.
"""
from ark_relay.features.banners import banners  # noqa: F401
