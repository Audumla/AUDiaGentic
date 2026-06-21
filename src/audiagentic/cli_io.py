"""Unified CLI output helpers.

Provides consistent stdout/stderr separation and JSON serialization for all
CLI entrypoints and harness user-facing output. Shared library code should use
`logging` instead.

Usage
-----
    from audiagentic.cli_io import print_json, print_message, print_error

    # Structured machine-readable output (stdout)
    print_json({"status": "ok", "version": "1.0.0"})

    # Human-readable user message (stdout)
    print_message("Install complete.")

    # Error / warning (stderr)
    print_error("Harness not installed. Run: audiagentic install")
"""
from __future__ import annotations

import json
import sys
from typing import Any


def print_json(
    data: Any,
    *,
    indent: int = 2,
    sort_keys: bool = False,
) -> None:
    """Print structured JSON to stdout."""
    print(json.dumps(data, indent=indent, sort_keys=sort_keys))  # noqa: T201


def print_message(text: str, *, flush: bool = True) -> None:
    """Print a human-readable message to stdout."""
    print(text, flush=flush)  # noqa: T201


def print_error(text: str, *, flush: bool = True) -> None:
    """Print an error or warning message to stderr."""
    print(text, file=sys.stderr, flush=flush)  # noqa: T201
