"""OpenHands probe function."""
from __future__ import annotations


def _openhands_probe(_descriptor) -> dict:
    from audiagentic.components.providers.adapters.probe import probe_cli_version
    return probe_cli_version("openhands", ["openhands", "--version"])
