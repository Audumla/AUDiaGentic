"""Opt-in: qualify the INSTALLED Claude Code against a disposable interactive session (SH55).

A fake API key and a loopback stub model only: no sign-in, no vendor call. Select with
``pytest -m opt_in tests/integration/providers/test_claude_live_qualification.py``.
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
    if shutil.which("claude") is None:
        pytest.skip("claude is not installed")


def test_the_installed_claude_code_is_seen_but_cannot_be_sent_to(tmp_path):
    result = qualify_live("claude", state_root=tmp_path / "state")
    assert result["capabilities"] == {
        "passive-identity": True, "existing-session-attach": False, "safe-detach": False, "reconnect": True,
        "conditional-admission": False, "correlated-result": False, "concurrent-human-use": True}, result["observations"]
    assert result["reasons"] == ["unproven-no-attachment-to-detach", "unsupported-no-existing-session-endpoint"]
    assert result["cleanup-error"] is None
