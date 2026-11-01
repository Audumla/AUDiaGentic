"""Opt-in: qualify the INSTALLED Codex against a disposable app-server (SH54-A).

Runs the real ``codex app-server`` in a throw-away environment: no credentials, no model call. Not part of
a default run; select it with ``pytest -m opt_in tests/integration/providers/test_codex_live_qualification.py``.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from audiagentic.components.providers.services.qualification import evidence
from audiagentic.components.providers.services.qualification.live import qualify_live
from audiagentic.components.providers.services.session.join_readiness import adapter_identity

pytestmark = pytest.mark.opt_in


@pytest.fixture(autouse=True)
def _only_when_asked(request):
    if "opt_in" not in (request.config.getoption("-m") or ""):
        pytest.skip("live qualification runs only with -m opt_in")
    if shutil.which("codex") is None:
        pytest.skip("codex is not installed")


def _own_servers() -> list[str]:
    """Codex processes (by executable, not by text anywhere in a command line) serving a qualification socket."""
    out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines():
        words = line.split()
        if words and words[0].rsplit("/", 1)[-1] == "codex" and "app-server" in words and any(
                word.startswith("unix://") and "qualify-live" in word for word in words):
            found.append(line)
    return found


def test_the_installed_codex_proves_identity_attach_detach_reconnect_and_measures_admission_as_unsupported(tmp_path):
    result = qualify_live("codex", state_root=tmp_path / "state")
    assert result["state"] == "partial", result["observations"]
    assert result["capabilities"] == {
        "passive-identity": True, "existing-session-attach": True, "safe-detach": True, "reconnect": True,
        "conditional-admission": False, "correlated-result": False, "concurrent-human-use": False}
    assert result["reasons"] == ["unproven-needs-human-ui-probe", "unsupported-concurrent-callers-share-a-turn",
                                 "unsupported-turn-start-steers-active-turn"]
    assert result["cleanup-error"] is None and not _own_servers()  # nothing left running, nothing left on disk


def test_a_second_turn_start_on_a_busy_thread_steers_the_active_turn_and_is_not_admission(tmp_path):
    """The decisive measurement behind the unsupported verdict (codex 0.166.0): B's turn/start while A's turn is
    active returns A's own turn id and adds a model request to A's turn; idle admission and idle attribution work."""
    observed = qualify_live("codex", state_root=tmp_path / "state")["observations"]["conditional-admission"]
    assert observed["idle-admitted-exactly-once"] is True and observed["idle-callers-attributed-by-turn-id"] is True
    assert observed["busy-second-caller-got-the-active-turn-id"] is True
    assert observed["model-requests-added-to-the-active-turn"] >= 1 and observed["active-turn-output-unchanged"] is False
    assert observed["stub-unexpected-requests"] == 0  # the harness reached for nothing but the stub's responses route


def test_the_evidence_is_exact_match_for_this_executable_and_adapter(tmp_path):
    result = qualify_live("codex", state_root=tmp_path / "state")
    facts = evidence.inventory("codex")
    adapter = adapter_identity("audiagentic.components.providers.adapters.codex.join:AppServerClient")
    record = evidence.find_exact(provider_id="codex", surface_id=result["surface"], platform=facts["platform"],
                                 executable_digest=facts["executable-digest"], adapter_digest=adapter.adapter_digest,
                                 native_schema_version=adapter.native_schema_version, state_root=tmp_path / "state")
    assert record and record["evidence-id"] == result["evidence-id"]
    assert record["target"]["executable-version"] == facts["executable-version"]
    assert evidence.proven_capabilities(record) == {"passive-identity", "existing-session-attach", "safe-detach", "reconnect"}
    assert "conditional-admission" not in evidence.proven_capabilities(record)
    assert "human-UI" in result["claim"] and "never sufficient for a join" in result["claim"]


def test_safe_detach_is_measured_in_both_directions_and_the_last_subscriber_case_is_recorded(tmp_path):
    result = qualify_live("codex", state_root=tmp_path / "state")
    detach = result["observations"]["safe-detach"]
    assert result["capabilities"]["safe-detach"] is True
    assert detach["observer-leaves"] == {"server-alive": True, "thread-still-loaded": True, "original-client-operational": True}
    assert detach["original-leaves"] == {"observer-reattached": True, "thread-still-loaded-for-observer": True,
                                         "observer-can-read": True}  # the human closing their client does not end the session
    assert detach["last-subscriber-leaves"]["resumable"] is True  # recorded, not gating
