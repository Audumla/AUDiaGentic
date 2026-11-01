"""Opt-in: qualify the INSTALLED OpenCode against a disposable ``opencode serve`` and a real TUI in a pty (SH56).

No credentials and no vendor model: a loopback stub is the only model. Select with
``pytest -m opt_in tests/integration/providers/test_opencode_live_qualification.py``.
"""
from __future__ import annotations

import shutil

import pytest

from audiagentic.components.providers.services.qualification.live import qualify_live

pytestmark = [pytest.mark.opt_in, pytest.mark.timeout(300)]


@pytest.fixture(autouse=True)
def _only_when_asked(request):
    if "opt_in" not in (request.config.getoption("-m") or ""):
        pytest.skip("live qualification runs only with -m opt_in")
    if shutil.which("opencode") is None:
        pytest.skip("opencode is not installed")


def test_the_installed_opencode_proves_queue_admission_and_leaves_result_correlation_unproven(tmp_path):
    result = qualify_live("opencode", state_root=tmp_path / "state")
    assert result["capabilities"] == {
        "passive-identity": True, "existing-session-attach": True, "safe-detach": True, "reconnect": True,
        "conditional-admission": True, "correlated-result": False, "concurrent-human-use": True}
    assert result["reasons"] == ["unsupported-result-not-linked-by-native-id"]
    assert result["cleanup-error"] is None
