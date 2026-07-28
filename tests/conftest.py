from __future__ import annotations

import os
import sys
from pathlib import Path

# Load environment-specific secrets from .audiagentic/secrets/<env>.env.
# AUDIAGENTIC_ENV defaults to "test"; set to "prod" for production env file.
# The .audiagentic/ directory is git-ignored — keys never leave the machine.
try:
    from dotenv import load_dotenv

    _AG_ROOT = Path(__file__).resolve().parents[1]
    _ag_env = os.environ.get("AUDIAGENTIC_ENV", "test")
    _secrets_file = _AG_ROOT / ".audiagentic" / "secrets" / f"{_ag_env}.env"
    if _secrets_file.is_file():
        load_dotenv(str(_secrets_file), override=False)
except ImportError:
    pass  # python-dotenv not installed — env vars must be set externally

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _p in (str(_ROOT), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TIER_MARKERS = {
    "/unit/": "unit",
    "/integration/": "integration",
    "/e2e/": "e2e",
}


@pytest.fixture(autouse=True)
def _isolate_audiagentic_home(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirect the shared AUDiaGentic home (``AUDIAGENTIC_HOME``) to a per-test tmp
    dir, so harness materialization / config refresh never touches the real
    ``~/.audiagentic``.

    This is what makes home-materializing suites host-safe without Docker.
    Subprocesses inherit os.environ, so the redirect propagates to CLI subprocess
    tests too. ``mutates_host`` tests are left alone: they perform genuine
    system-level installs and assert against the real harness home in their gated
    Docker/opt-in environment, so this fixture must not move their home.
    """
    if request.node.get_closest_marker("mutates_host") is not None:
        return
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path_factory.mktemp("audiagentic-home")))


@pytest.fixture(autouse=True)
def _reset_test_registries():
    """Restore canonical registry state between every unit test.

    Clears the feature registry and resets the coding-lsp language_registry
    (which loads from the feature registry), then invalidates the loader's
    registration cache. This ensures that a test which clears the feature
    registry (via setup_function/teardown_function or directly) does not
    leave downstream tests with stale empty state — lazy loaders will
    re-populate from component descriptors on next access.

    Also forces key service modules to re-import their registry references,
    clearing stale mock references left by patches at the definition site
    (e.g., patching descriptors.registry.all_descriptors). This prevents a
    test's patch from leaking into subsequent tests via already-imported
    module-level name bindings.

    The CP02 cache guard in register_all_components() is keyed on resolved
    config dirs; after clearing registries, a subsequent lazy call would
    short-circuit and leave them empty (RV115: 67 failures). Clearing the
    loader cache after registry resets prevents that.

    Note: We do NOT call reset_all_registries() because provider tests may
    register custom providers into other registries (e.g., renderer registry)
    and expect them to persist within their test scope. Only the feature
    registry and the language_registry (which depends on it) need explicit
    reset for cross-file test isolation.
    """
    from audiagentic.foundation.components.loader import (
        _reset_registration_cache,
    )
    from audiagentic.foundation.features.registry import clear

    clear()

    # Component and provider descriptor registries are lazy and treat any
    # non-empty registry as populated. Tests that install a small fixture set
    # must not leave that partial set visible to the next test, otherwise the
    # lazy loader never restores canonical descriptors (for example qwen).
    from audiagentic.foundation.components.registry import reset as reset_components

    reset_components()
    try:
        from audiagentic.components.providers.descriptors import registry as provider_registry

        provider_registry._registry.reset()
    except ImportError:
        pass

    # Reset the coding-lsp language_registry so its lazy loader re-populates
    # from (now-cleared) feature registry on next access.
    try:
        from audiagentic.components.coding_lsp.language_registry import _REGISTRY

        _REGISTRY.reset()
    except ImportError:
        pass

    # Force service modules to re-import their registry references, clearing
    # stale mock bindings left by definition-site patches (e.g., patching
    # descriptors.registry.all_descriptors). Without this, a test's patch can
    # leak into subsequent tests via already-imported module-level names.
    try:
        import importlib

        mod = __import__(
            "audiagentic.components.providers.services.config.feature_resolution",
            fromlist=["all_descriptors", "enabled_provider_ids"],
        )
        importlib.reload(mod)
    except (ImportError, AttributeError):
        pass

    _reset_registration_cache()


@pytest.fixture
def fake_secret_ref(monkeypatch: pytest.MonkeyPatch):
    """Set a fake env var and return its ``env:NAME`` ref string.

    Usage::

        def test_provider_needs_key(fake_secret_ref):
            ref = fake_secret_ref("OPENAI_API_KEY")
            # ref == "env:OPENAI_API_KEY" and $OPENAI_API_KEY is set
            assert has_ambient_value(ref) is True

        def test_custom_value(fake_secret_ref):
            ref = fake_secret_ref("MY_KEY", fake_value="custom-secret")
            assert resolve_secret_ref(ref) == "custom-secret"
    """

    def _factory(var_name: str, fake_value: str = "test-fake-key-00000000") -> str:
        monkeypatch.setenv(var_name, fake_value)
        return f"env:{var_name}"

    return _factory


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    docker_ok = os.environ.get("AUDIAGENTIC_DOCKER_TESTS") == "1"

    skip_mutating = pytest.mark.skip(
        reason="mutates_host tests are disabled; run with AUDIAGENTIC_DOCKER_TESTS=1"
    )

    # First pass: find every module that contains at least one no_parallel test.
    # Such tests share a stateful resource (e.g. a long-lived LSP subprocess held
    # by a module-scoped fixture). Under xdist they must not interleave AND the
    # whole module must land on a single worker, or the shared fixture is built
    # twice and the connection races. We pin the entire module to one xdist group.
    #
    # Only meaningful (and only valid under --strict-markers) when the xdist
    # plugin is loaded — it owns the `xdist_group` marker. Without xdist the suite
    # runs serially anyway, so grouping is a no-op we correctly skip.
    xdist_active = config.pluginmanager.hasplugin("xdist")
    serial_modules = {
        item.nodeid.split("::", 1)[0]
        for item in items
        if item.get_closest_marker("no_parallel") is not None
    } if xdist_active else set()

    for item in items:
        node = item.nodeid.replace("\\", "/")

        # Auto-apply tier marker from directory path
        for path_fragment, marker_name in _TIER_MARKERS.items():
            if path_fragment in node:
                item.add_marker(getattr(pytest.mark, marker_name))
                break

        # Pin no_parallel modules to a per-module xdist group. With
        # `--dist loadgroup` this forces same-worker, serial execution for the
        # whole module while the rest of the suite still fans out across workers,
        # so `pytest -n auto --dist loadgroup` is a safe single-command run.
        module_id = item.nodeid.split("::", 1)[0]
        if module_id in serial_modules:
            item.add_marker(pytest.mark.xdist_group(f"serial::{module_id}"))

        # Gate mutates_host tests — Docker alone provides isolation
        if not docker_ok:
            if item.get_closest_marker("mutates_host") is not None:
                item.add_marker(skip_mutating)
