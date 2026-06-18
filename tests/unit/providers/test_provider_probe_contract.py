"""Contract: every provider probe degrades cleanly when its CLI is absent.

Guards the class of bug fixed for the npm ``.CMD`` probes — a probe that
crashed (WinError 2) or masked a failure as ``available: True``.  Runs purely
in-process: ``shutil.which`` is stubbed to None, so no real CLI is required and
the PATH-based probes never reach a subprocess.

Complements the Docker integration suite (real install/health/uninstall) and
test_adapter_probe.py (run_cli / probe_cli_version mechanics).
"""
from __future__ import annotations

import shutil

import pytest

from audiagentic.components.optional.providers.descriptors.registry import all_descriptors
from audiagentic.components.optional.providers.services.lifecycle import _probe_provider_cli

# pi probes the harness runtime on disk, not PATH — not a shutil.which contract.
_NON_PATH_PROBES = {"pi"}

_PROBE_PROVIDER_IDS = sorted(
    pid
    for pid, desc in all_descriptors().items()
    if pid not in _NON_PATH_PROBES
    and ((desc.cli_install and desc.cli_install.probe_fn) or desc.cli_probe)
)


def test_probe_provider_ids_discovered() -> None:
    # Sanity: the parametrization is not silently empty.
    assert {"opencode", "claude", "copilot", "qwen", "openhands"} <= set(_PROBE_PROVIDER_IDS)


@pytest.mark.parametrize("provider_id", _PROBE_PROVIDER_IDS)
def test_probe_reports_unavailable_when_cli_absent(provider_id: str, monkeypatch) -> None:
    """No probe may crash or report available with no resolved executable."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    descriptor = all_descriptors()[provider_id]

    result = _probe_provider_cli(descriptor)

    assert result is not None, f"{provider_id} has a probe path but returned None"
    assert result["available"] is False, f"{provider_id} reported available with no CLI"
    assert result["executable"] is None, f"{provider_id} reported an executable with no CLI"
