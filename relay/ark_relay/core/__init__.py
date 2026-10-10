"""Shared parts every grid uses: settings, stored state, the log file, pushing
messages, file watching, processes, transport, the desktop agent, and name tables.

Docstring only on purpose: the old top-level paths are sys.modules aliases onto
these modules, and an eager import here would set up import cycles.
"""
