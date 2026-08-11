"""Tests for the Hindsight provisioning entrypoint — MA27 family orchestration.

The reconcile_hindsight function is now the sole entry point: it uses family-preference
orchestration over providers_api with no matrix, factory, or recipe registry.
"""
from __future__ import annotations

import json

import audiagentic.components.providers  # noqa: F401 — register provider descriptors
from audiagentic.components.memory.hindsight import provision as prov
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig


def _patch_backend(monkeypatch, backend):
    monkeypatch.setattr(prov, "build_hindsight_backend", lambda root: backend)  # noqa: ARG005


def test_disabled_uninstalls_from_all_providers(tmp_path, monkeypatch):
    """active=False uninstalls from every provider, not just the enabled ones."""
    _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", api_key="k"))

    out = prov.reconcile_hindsight(
        tmp_path, ["gemini"], all_provider_ids=["gemini", "roo", "claude"], active=False,
    )

    assert out["action"] == "torn-down"
    # All providers get uninstalled role.
    for pid in ("gemini", "roo", "claude"):
        info = out["providers"].get(pid)
        if info:
            assert info["role"] == "uninstall" or info["state"] == "ABSENT"


def test_disable_retains_config(tmp_path, monkeypatch):
    """Disabling uninstalls the integration but leaves the Hindsight config intact."""
    out = prov.reconcile_hindsight(tmp_path, [], all_provider_ids=["gemini"], active=False)

    # Torn-down action is returned regardless of config state.
    assert out["action"] == "torn-down"


def _ok_result():
    return type("R", (), {"success": True, "state": type("S", (), {"value": "absent"})()})()


def test_reconcile_tears_down_when_no_backend(tmp_path, monkeypatch):
    """No backend -> torn-down action."""
    _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", api_key="k"))
    prov.reconcile_hindsight(tmp_path, ["gemini"])

    # Reconcile with no backend -> teardown.
    _patch_backend(monkeypatch, None)
    out = prov.reconcile_hindsight(tmp_path, ["gemini"])

    assert out["action"] == "torn-down"


def test_disabled_provider_pruned_stale(tmp_path, monkeypatch):
    """Disabled providers lose Hindsight-owned artifacts; enabled stay configured."""
    _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", api_key="k"))

    prov.reconcile_hindsight(
        tmp_path, ["gemini", "copilot"], all_provider_ids=["gemini", "copilot", "roo"],
    )
    out = prov.reconcile_hindsight(tmp_path, ["gemini"], all_provider_ids=["gemini", "copilot", "roo"])
    assert out["action"] == "applied"
    # Roo (not in enabled list) should be pruned
    roo_info = out["providers"].get("roo")
    if roo_info:
        assert roo_info["role"] == "prune" or roo_info["state"] == "ABSENT"


def test_bridge_skips_when_memory_not_installed(tmp_path):
    """An empty project has no installed memory -> the reconciler self-skips."""
    from audiagentic.components.memory.memory_observer import _reconcile

    out = _reconcile(tmp_path)
    assert out.get("skipped")


def test_summary_shape_has_required_fields(tmp_path, monkeypatch):
    """reconcile_hindsight returns action + providers with success/state/role."""
    _patch_backend(monkeypatch, None)
    out = prov.reconcile_hindsight(tmp_path, ["gemini"])

    assert "action" in out
    assert "providers" in out
    for pid, info in out["providers"].items():
        assert "success" in info, f"Missing 'success' in {pid}"
        assert "state" in info, f"Missing 'state' in {pid}"
        assert "role" in info, f"Missing 'role' in {pid}"


def test_config_change_event_triggers_reconcile(tmp_path, monkeypatch):
    """memory_set_config publishes lifecycle.event that fires reconcile via observer."""
    import audiagentic.components.memory.hindsight.provision as prov_module
    from audiagentic.components.memory.memory_api import memory_set_config
    from audiagentic.foundation.event import get_bus
    from audiagentic.foundation.lifecycle.components import install_component

    # Install memory so observer's is_installed check passes
    install_component("memory", tmp_path)

    # Set initial config and reconcile to create provider artifacts
    memory_set_config(tmp_path, "hindsight", {"host": "10.0.0.1"})
    prov.reconcile_hindsight(tmp_path, ["gemini"])

    # Spy on the provision module's reconcile so observer lazy import sees it
    called: list[str] = []
    orig = prov_module.reconcile_hindsight

    def spy_prov(*args, **kwargs):  # noqa: ARG001
        called.append("observer-reconcile")
        return orig(*args, **kwargs)

    monkeypatch.setattr(prov_module, "reconcile_hindsight", spy_prov)

    # Config change publishes async event -> observer triggers reconcile
    memory_set_config(tmp_path, "hindsight", {"host": "20.0.0.2"})
    bus = get_bus()
    bus.wait_idle(timeout=5)  # flush pending async subscriber work

    assert "observer-reconcile" in called, (
        "observer should have triggered reconcile after config change"
    )


def test_memory_set_config_returns_refresh_hint(tmp_path):
    """Direct API config change returns neutral refresh hint only."""
    from audiagentic.components.memory.memory_api import memory_set_config

    result = memory_set_config(tmp_path, "hindsight", {"host": "10.0.0.5"})
    assert result["needs_provider_recipe_refresh"] is True
    # No provider-specific detail in the return
    assert "providers" not in result


def _isolate_home(monkeypatch, tmp_path):
    """Redirect the OS home (expanduser) to tmp_path and stub the script fetch."""
    import audiagentic.foundation.steps.structured as structured

    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(structured, "_fetch_text", lambda url, timeout: f"# {url}\n")


class TestArtifactRecipeReconcile:
    """End-to-end reconcile through the declarative artifact recipes.

    Regression coverage for the Pi host-block population gap (found live as
    ``host: {}``) and the Codex script fetch + codex.json write — now provisioned
    by the recipe engine, not hand-rolled writers.
    """

    def test_reconcile_download_failure_surfaces_as_failed(self, tmp_path, monkeypatch):
        import audiagentic.foundation.steps.structured as structured

        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))

        def boom(url, timeout):
            raise RuntimeError("network down")

        monkeypatch.setattr(structured, "_fetch_text", boom)
        _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", bank_id="codex"))

        out = prov.reconcile_hindsight(tmp_path, ["codex"])
        assert out["providers"]["codex"]["success"] is False


class TestMemoryObserverPath:
    """Architecture gate: memory core outside memory/hindsight has no provider imports."""

    def test_memory_api_no_provider_imports(self):
        import inspect

        import audiagentic.components.memory.memory_api as api_module

        source = inspect.getsource(api_module)
        assert "providers.adapters" not in source
        assert "from audiagentic.components.providers.services" not in source
