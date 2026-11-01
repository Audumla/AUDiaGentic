"""Opt-in: qualify the INSTALLED Pi against a disposable interactive instance (SH56).

Offline, no provider, no model. Select with ``pytest -m opt_in tests/integration/providers/test_pi_live_qualification.py``.
"""
from __future__ import annotations

import shutil

import pytest

from audiagentic.components.providers.services.qualification.live import qualify_live

pytestmark = [pytest.mark.opt_in, pytest.mark.timeout(180)]


@pytest.fixture(autouse=True)
def _only_when_asked(request):
    if "opt_in" not in (request.config.getoption("-m") or ""):
        pytest.skip("live qualification runs only with -m opt_in")
    if shutil.which("pi") is None:
        pytest.skip("pi is not installed")


def test_a_running_interactive_pi_exposes_no_endpoint_so_every_join_capability_is_unsupported(tmp_path):
    result = qualify_live("pi", state_root=tmp_path / "state")
    assert result["state"] == "unsupported", result["observations"]
    assert not any(result["capabilities"].values())
    assert result["reasons"] == ["unsupported-no-existing-session-endpoint"]
    observed = result["observations"]["passive-identity"]
    assert observed["inet-listeners"] == 0 and observed["unix-sockets"] == 0 and observed["rpc-get-state-answered"]
    assert result["cleanup-error"] is None
