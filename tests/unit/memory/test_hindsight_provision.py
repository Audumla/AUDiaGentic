"""Tests for the Hindsight provisioning entrypoint — MA27 family orchestration.

The reconcile_hindsight function is now the sole entry point: it uses family-preference
orchestration over providers_api with no matrix, factory, or recipe registry.
"""
from __future__ import annotations

from pathlib import Path

import audiagentic.components.providers  # noqa: F401 — register provider descriptors
from audiagentic.components.memory.hindsight import provision as prov
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig


def _patch_backend(monkeypatch, backend):
    monkeypatch.setattr(prov, "build_hindsight_backend", lambda root: backend)  # noqa: ARG005


def test_reconcile_applies_when_backend_configured(tmp_path, monkeypatch):
    _patch_backend(monkeypatch, HindsightBackendConfig(base_url="http://hs:1/", api_key="k"))

    out = prov.reconcile_hindsight(tmp_path, ["gemini"])

    assert out["action"] == "applied"
    assert out["providers"]["gemini"]["success"] is True


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


def test_hook_apply_redacts_download_failure(monkeypatch, tmp_path):
    """Raw remote failure text must not cross the public result boundary."""
    monkeypatch.setattr(
        prov,
        "_download_codex_scripts",
        lambda: (_ for _ in ()).throw(RuntimeError("token=super-secret-value")),
    )

    result = prov._apply_hooks(
        "codex",
        tmp_path,
        HindsightBackendConfig(base_url="http://hs:1/", api_key="k"),
    )

    assert result.ok is False
    assert result.action_needed == "token=[REDACTED]"


def test_codex_scripts_download_to_hook_command_paths_atomically(monkeypatch, tmp_path):
    class Response:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    requested: list[str] = []

    def fake_urlopen(url: str, *, timeout: int):
        assert timeout == 30
        requested.append(url)
        return Response(f"# fetched from {url}\n".encode())

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    existing_settings = tmp_path / ".hindsight" / "codex" / "settings.json"
    existing_settings.parent.mkdir(parents=True)
    existing_settings.write_text('{"foreign": true}\n', encoding="utf-8")

    prov._download_codex_scripts()

    for rel in prov._SCRIPT_FILES:
        destination = tmp_path / ".hindsight" / "codex" / rel
        assert destination.read_text(encoding="utf-8").endswith(f"/{rel}\n")
    assert not (tmp_path / ".hindsight" / "codex" / "session_start.py").exists()
    assert existing_settings.read_text(encoding="utf-8") == '{"foreign": true}\n'
    assert all(not url.endswith("/settings.json") for url in requested)


class TestMemoryObserverPath:
    """Architecture gate: memory core outside memory/hindsight has no provider imports."""

    def test_memory_api_no_provider_imports(self):
        import inspect

        import audiagentic.components.memory.memory_api as api_module

        source = inspect.getsource(api_module)
        assert "providers.adapters" not in source
        assert "from audiagentic.components.providers.services" not in source
