"""CFG12: live qualification runner and the Codex probe's helpers (hermetic: no binary is started)."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.codex import join
from audiagentic.components.providers.services.qualification import evidence, live
from audiagentic.components.providers.services.qualification.live import (
    CAPABILITIES,
    LiveContext,
    LiveTarget,
    ProbeOutcome,
    qualify_live,
)
from audiagentic.components.providers.services.qualification.probes import codex as codex_probe

FACTS = {"platform": "linux-amd64", "executable-version": "9.9.9", "executable-digest": "sha256:" + "c" * 64,
         "executable": "/nonexistent/fake"}
STRICT = {"passive-identity", "existing-session-attach", "safe-detach", "conditional-admission", "correlated-result"}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """A fake provider whose probe returns whatever the test sets; the evidence store is a temp dir."""
    behaviour = {"proven": set(), "reason": "unproven", "raise": None}

    def probe(context: LiveContext):
        assert context.root.is_dir() and context.facts["executable-version"] == "9.9.9"
        if behaviour["raise"]:
            raise behaviour["raise"]
        return [ProbeOutcome(name, name in behaviour["proven"], None if name in behaviour["proven"] else behaviour["reason"],
                             {"seen": name}) for name in CAPABILITIES]

    module = type("M", (), {"probe": staticmethod(probe)})
    monkeypatch.setitem(live.LIVE_TARGETS, "fake", LiveTarget(
        surface_id="fake-surface", native_protocol="fake-proto", endpoint_kind="stdio", fixture_id="fake-fixture",
        adapter_ref="audiagentic.components.providers.adapters.codex.join:AppServerClient", probe_ref="fake.module:probe"))
    monkeypatch.setattr("audiagentic.foundation.config.refs.resolve_ref",
                        lambda ref: module.probe if ref == "fake.module:probe" else __import__("importlib").import_module(
                            ref.split(":")[0]).__dict__[ref.split(":")[1]])
    monkeypatch.setattr(evidence, "inventory", lambda provider_id: dict(FACTS))
    monkeypatch.setattr(live.inspect, "getsourcefile", lambda obj: str(Path(join.__file__)))
    return behaviour, tmp_path / "state"


def _run(state_root):
    return qualify_live("fake", state_root=state_root)


def test_nothing_proven_with_plain_unproven_reasons_is_inconclusive_not_unsupported(fake):
    behaviour, state = fake
    result = _run(state)
    assert result["state"] == "inconclusive" and not any(result["capabilities"].values())
    assert result["reasons"] == ["unproven"]


def test_explicitly_unsupported_reasons_make_the_record_unsupported(fake):
    behaviour, state = fake
    behaviour["reason"] = "unsupported-protocol-method-missing"
    assert _run(state)["state"] == "unsupported"


def test_partial_when_some_are_proven_and_supported_only_when_the_strict_join_is(fake):
    behaviour, state = fake
    behaviour["proven"] = {"passive-identity", "safe-detach"}
    result = _run(state)
    assert result["state"] == "partial" and result["capabilities"]["passive-identity"] and not result["capabilities"]["reconnect"]
    behaviour["proven"] = STRICT
    assert _run(state)["state"] == "supported"
    behaviour["proven"] = STRICT - {"conditional-admission"} | {"concurrent-human-use"}
    assert _run(state)["state"] == "partial"  # a neighbouring capability does not stand in for a required one


def test_a_crashed_probe_proves_nothing_and_is_reported_not_raised(fake):
    behaviour, state = fake
    behaviour["raise"] = RuntimeError("boom")
    result = _run(state)
    assert result["state"] == "inconclusive" and "probe-failed" in result["reasons"]
    assert result["observations"]["passive-identity"] == {"error": "RuntimeError"}


def test_the_record_is_immutable_exact_match_evidence_that_resolves_the_proven_set(fake):
    behaviour, state = fake
    behaviour["proven"] = {"passive-identity", "reconnect"}
    result = _run(state)
    from audiagentic.components.providers.services.session.join_readiness import adapter_identity

    adapter = adapter_identity("audiagentic.components.providers.adapters.codex.join:AppServerClient")
    record = evidence.find_exact(provider_id="fake", surface_id="fake-surface", platform="linux-amd64",
                                 executable_digest=FACTS["executable-digest"], adapter_digest=adapter.adapter_digest,
                                 native_schema_version=adapter.native_schema_version, state_root=state)
    assert record["evidence-id"] == result["evidence-id"]
    assert evidence.proven_capabilities(record) == {"passive-identity", "reconnect"}
    assert record["target"]["executable-version"] == "9.9.9"
    assert "vendor-model" in result["claim"] or "not vendor-model" in result["claim"]


def test_a_different_executable_never_matches_the_evidence(fake):
    behaviour, state = fake
    behaviour["proven"] = {"passive-identity"}
    _run(state)
    from audiagentic.components.providers.services.session.join_readiness import adapter_identity

    adapter = adapter_identity("audiagentic.components.providers.adapters.codex.join:AppServerClient")
    assert evidence.find_exact(provider_id="fake", surface_id="fake-surface", platform="linux-amd64",
                               executable_digest="sha256:" + "d" * 64, adapter_digest=adapter.adapter_digest,
                               native_schema_version=adapter.native_schema_version, state_root=state) is None


def test_the_scratch_directory_is_removed_and_cleanup_is_reported(fake):
    behaviour, state = fake
    seen = []
    original = live.tempfile.mkdtemp
    live.tempfile.mkdtemp = lambda **kw: (seen.append(original(**kw)) or seen[-1])
    try:
        assert _run(state)["cleanup-error"] is None
    finally:
        live.tempfile.mkdtemp = original
    assert seen and not Path(seen[0]).exists()


def test_unknown_provider_and_uninstalled_provider_are_refused(fake, monkeypatch):
    with pytest.raises(KeyError):
        qualify_live("nobody")
    monkeypatch.setattr(evidence, "inventory", lambda provider_id: {**FACTS, "executable-digest": None})
    with pytest.raises(RuntimeError, match="not installed"):
        qualify_live("fake")


# --- the Codex probe's helpers -------------------------------------------------------------------------

def test_the_disposable_environment_inherits_no_credentials_and_roots_everything_in_the_scratch_dir(tmp_path, monkeypatch):
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GH_TOKEN", "HTTPS_PROXY", "AUDIAGENTIC_CONFIG", "CODEX_API_KEY"):
        monkeypatch.setenv(key, "secret-value")
    env = codex_probe.disposable_env(tmp_path)
    assert not any("secret-value" in value for value in env.values())
    assert set(env) <= {*codex_probe._ENV_ALLOWLIST, "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                        "XDG_STATE_HOME", "CODEX_HOME", "TMPDIR"}
    for key in ("HOME", "CODEX_HOME", "XDG_CONFIG_HOME", "TMPDIR"):
        assert Path(env[key]).resolve().is_relative_to(tmp_path.resolve())


def test_thread_list_helpers_accept_bare_ids_and_objects():
    assert codex_probe._ids({"data": ["a", {"id": "b"}, {"x": 1}, 3]}) == {"a", "b"}
    assert codex_probe._ids({}) == set()
    assert codex_probe._thread_id({"thread": {"id": "t"}}) == "t" and codex_probe._thread_id({}) is None


def test_a_codex_that_lacks_a_required_method_is_unsupported_not_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_probe, "_protocol_methods", lambda *a: ({"initialize"}, "sha256:" + "e" * 64))
    outcomes = codex_probe.run(LiveContext(root=tmp_path, facts={"executable": "/x"}))
    assert {o.capability for o in outcomes} == set(CAPABILITIES) and not any(o.proven for o in outcomes)
    assert {o.reason for o in outcomes} == {"unsupported-protocol-method-missing"}


def test_a_schema_failure_proves_nothing(tmp_path, monkeypatch):
    def broken(*args):
        raise RuntimeError("cannot generate")

    monkeypatch.setattr(codex_probe, "_protocol_methods", broken)
    outcomes = codex_probe.run(LiveContext(root=tmp_path, facts={"executable": "/x"}))
    assert not any(o.proven for o in outcomes) and {o.reason for o in outcomes} == {"probe-failed"}


def test_the_adapter_declares_its_identity_and_the_methods_it_relies_on():
    assert join.JOIN_ADAPTER.adapter_id == "codex-app-server" and join.JOIN_ADAPTER.native_schema_version
    assert {"thread/start", "thread/resume", "thread/unsubscribe", "thread/loaded/list"} <= join.REQUIRED_METHODS
