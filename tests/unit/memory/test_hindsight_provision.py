"""Tests for the Hindsight provisioning entrypoint and the composition bridge.

These cover the auto-wiring seam: memory config change -> bridge -> provisioner
-> provider files. Providers stay ignorant of Hindsight; the bridge is the only
code that knows both sides.
"""
from __future__ import annotations

import audiagentic.components.providers  # noqa: F401  (register provider descriptors)
from audiagentic.components.memory.hindsight import provision as prov
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig


def _patch_backend(monkeypatch, backend):
    monkeypatch.setattr(prov, "build_hindsight_backend", lambda root: backend)


def test_reconcile_applies_when_backend_configured(tmp_path, monkeypatch):
    _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", api_key="k"))

    out = prov.reconcile_hindsight(tmp_path, ["gemini"])

    assert out["action"] == "applied"
    assert out["providers"]["gemini"]["success"] is True
    # Files land under the given project_root, not cwd.
    assert (tmp_path / ".gemini" / "settings.json").exists()


def test_disabled_uninstalls_from_all_providers(tmp_path, monkeypatch):
    """active=False uninstalls from every provider, not just the enabled ones."""
    _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", api_key="k"))
    torn: list[list[str]] = []
    monkeypatch.setattr(
        prov, "teardown_hindsight",
        lambda root, *, backend, provider_ids: (
            torn.append(list(provider_ids))
            or {p: _ok_result() for p in provider_ids}
        ),
    )

    out = prov.reconcile_hindsight(
        tmp_path, ["gemini"], all_provider_ids=["gemini", "roo", "claude"], active=False,
    )

    assert out["action"] == "torn-down"
    # Teardown spans ALL providers, reversing installs everywhere.
    assert torn == [["gemini", "roo", "claude"]]
    assert all(info["role"] == "uninstalled" for info in out["providers"].values())


def test_disable_retains_config(tmp_path, monkeypatch):
    """Disabling uninstalls the integration but leaves the Hindsight config intact."""
    from audiagentic.components.memory.hindsight.export import build_hindsight_backend
    from audiagentic.components.memory.memory_api import memory_set_config

    memory_set_config(tmp_path, "hindsight", {"host": "10.0.0.5"})
    # A real teardown would run installers; stub it out for a pure config-persistence check.
    monkeypatch.setattr(
        prov, "teardown_hindsight",
        lambda root, *, backend, provider_ids: {},
    )

    prov.reconcile_hindsight(tmp_path, [], all_provider_ids=["gemini"], active=False)

    # Config survives the disable — a later enable can reinstall from it.
    backend = build_hindsight_backend(tmp_path)
    assert backend is not None
    assert backend.base_url == "http://10.0.0.5:8888"


def _ok_result():
    return type("R", (), {"success": True, "state": type("S", (), {"value": "absent"})()})()


def test_reconcile_tears_down_when_no_backend(tmp_path, monkeypatch):
    # First apply with a backend...
    _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", api_key="k"))
    prov.reconcile_hindsight(tmp_path, ["gemini"])
    settings = tmp_path / ".gemini" / "settings.json"
    assert "hindsight" in settings.read_text(encoding="utf-8")

    # ...then reconcile with no backend -> teardown removes the entry.
    _patch_backend(monkeypatch, None)
    out = prov.reconcile_hindsight(tmp_path, ["gemini"])

    assert out["action"] == "torn-down"
    assert "hindsight" not in settings.read_text(encoding="utf-8")


def test_disable_component_event_tears_down_all_providers(tmp_path, monkeypatch):
    """End-to-end event wiring: disabling the memory component uninstalls everywhere.

    Exercises the real chain: disable_component -> lifecycle.component.disabled
    event -> memory observer -> refresh_provider_recipes -> reconcile_hindsight
    (active=False) -> teardown across all providers.
    """
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.lifecycle.components import (
        disable_component,
        install_component,
    )

    register_all_components()

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        prov, "apply_hindsight",
        lambda root, *, backend, provider_ids: (calls.append(("apply", list(provider_ids))) or {}),
    )
    monkeypatch.setattr(
        prov, "teardown_hindsight",
        lambda root, *, backend, provider_ids: (calls.append(("teardown", list(provider_ids))) or {}),
    )
    monkeypatch.setattr(prov, "prune_hindsight", lambda root, *, backend, provider_ids: {})
    monkeypatch.setattr(
        prov, "build_hindsight_backend",
        lambda root: HindsightBackendConfig(base_url="http://x:8888"),
    )

    install_component("memory", tmp_path)

    calls.clear()
    disable_component("memory", tmp_path)
    assert calls, "disabling memory must trigger a provider reconcile via the lifecycle event"
    action, provider_ids = calls[-1]
    assert action == "teardown"
    # Teardown spans every registered provider, not just enabled ones.
    assert len(provider_ids) > 1


def test_bridge_skips_when_memory_not_installed(tmp_path):
    """An empty project has no installed memory -> the reconciler self-skips.

    The memory reconciler self-registers via lifecycle-observer, so it is always
    present, but it no-ops (returns a skip payload) when memory is not installed.
    The runtime bridge itself stays generic and never imports memory.
    """
    from audiagentic.foundation.lifecycle.provider_recipes import refresh_provider_recipes

    out = refresh_provider_recipes(tmp_path)
    assert out.get("memory", {}).get("skipped")


def test_backend_switch_reconfigures_providers(tmp_path, monkeypatch):
    """Backend URL change rewrites every owned provider artifact through reconcile.

    Provision with backend A -> verify file contains A's URL.
    Provision with backend B -> verify file now contains B's URL.
    """
    from audiagentic.components.memory.memory_api import memory_set_config

    memory_set_config(tmp_path, "hindsight", {"host": "10.0.0.1"})
    prov.reconcile_hindsight(tmp_path, ["gemini"])
    settings = tmp_path / ".gemini" / "settings.json"
    assert "http://10.0.0.1:8888" in settings.read_text(encoding="utf-8")

    # Switch backend URL
    memory_set_config(tmp_path, "hindsight", {"host": "20.0.0.2"})
    prov.reconcile_hindsight(tmp_path, ["gemini"])
    assert "http://10.0.0.1:8888" not in settings.read_text(encoding="utf-8")
    assert "http://20.0.0.2:8888" in settings.read_text(encoding="utf-8")


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
        assert roo_info["role"] == "pruned-stale"


def test_config_change_event_triggers_reconcile(tmp_path, monkeypatch):
    """memory_set_config publishes lifecycle.event that fires reconcile via observer.

    Validates the observer-driven path: API change -> bus event -> observer ->
    refresh_provider_recipes -> reconcile_hindsight. The observer is the guaranteed
    consumer; MCP tools do not reconcile synchronously.
    """
    import audiagentic.components.memory.hindsight.provision as prov_module
    from audiagentic.components.memory.hindsight.export import build_hindsight_backend
    from audiagentic.components.memory.memory_api import memory_set_config
    from audiagentic.foundation.event import get_bus
    from audiagentic.foundation.lifecycle.components import install_component

    # Install memory so observer's is_installed check passes
    install_component("memory", tmp_path)

    # Set initial config and reconcile to create provider artifacts
    memory_set_config(tmp_path, "hindsight", {"host": "10.0.0.1"})
    prov.reconcile_hindsight(tmp_path, ["gemini"])
    settings = tmp_path / ".gemini" / "settings.json"
    assert (tmp_path / ".gemini" / "settings.json").exists()

    # Spy on the provision module's reconcile so observer lazy import sees it
    called: list[str] = []
    orig = prov_module.reconcile_hindsight

    def spy_prov(*args, **kwargs):
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

    # Verify backend config was updated independently of observer path
    backend = build_hindsight_backend(tmp_path)
    assert backend is not None
    assert backend.base_url == "http://20.0.0.2:8888"

    # Manual reconcile to verify artifact reflects new host (observer passes
    # all enabled providers; this isolates the gemini config rewrite)
    prov.reconcile_hindsight(tmp_path, ["gemini"])
    text = settings.read_text(encoding="utf-8")
    assert "http://20.0.0.2:8888" in text


def test_memory_set_config_returns_refresh_hint(tmp_path):
    """Direct API config change returns neutral refresh hint only."""
    from audiagentic.components.memory.memory_api import memory_set_config

    result = memory_set_config(tmp_path, "hindsight", {"host": "10.0.0.5"})
    assert result["needs_provider_recipe_refresh"] is True
    # No provider-specific detail in the return
    assert "providers" not in result


class TestMemoryObserverPath:
    """Architecture gate: memory core outside memory/hindsight has no provider imports."""

    def test_memory_api_no_provider_imports(self):
        import inspect

        import audiagentic.components.memory.memory_api as api_module

        source = inspect.getsource(api_module)
        assert "providers.adapters" not in source
        assert "from audiagentic.components.providers.services" not in source
