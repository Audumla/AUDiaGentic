"""Versioned, non-editable runtime for the long-lived services (gateway, MCP servers).

No git worktree is ever load-bearing: services run from ``<runtime>/current``, a symlink to
one immutable venv ``<runtime>/<version>-<id>`` that holds an installed wheel.
"""
