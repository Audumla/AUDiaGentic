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

#: Number of no_parallel tests held back from a parallel run, reported at the
#: end so a green parallel run is never mistaken for a complete one.
_DESELECTED_SERIAL_COUNT: pytest.StashKey[int] = pytest.StashKey[int]()

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
def _seed_global_agent_catalog(_isolate_audiagentic_home) -> None:
    """Provide a minimal canonical prompt authority to unit tests."""
    from audiagentic.foundation.paths.home import audiagentic_home

    config = audiagentic_home() / "config"
    templates = config / "agent-templates"
    templates.mkdir(parents=True, exist_ok=True)
    (config / "agents.yaml").write_text(
        """contract-version: v2
prompts: {}
""",
        encoding="utf-8",
    )


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

    # Surface adapter modules register their renderers at import time. The
    # foundation registry reset above clears those entries, so repopulate the
    # provider surface registries before the next test starts.
    try:
        from audiagentic.components.providers.surfaces.registry import (
            load_contribution_renderer_registry,
            load_renderer_registry,
        )

        load_renderer_registry()
        load_contribution_renderer_registry()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _restore_event_bus_after_closed_tests():
    """Keep tests that close the singleton event bus from poisoning later tests.

    The production bus is intentionally process-scoped, while unit tests may
    exercise shutdown directly. A closed singleton cannot publish lifecycle
    status for an otherwise unrelated test, especially when xdist reuses a
    worker, so replace it at the test boundary when needed.
    """
    from audiagentic.foundation.event.event_bus import get_bus, reset_bus

    bus = get_bus()
    if getattr(bus, "_closed", False):
        reset_bus()
    yield
    if getattr(get_bus(), "_closed", False):
        reset_bus()


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
    skip_container = pytest.mark.skip(
        reason="requires_container tests are disabled; run inside the Docker test environment"
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

    # Grouping alone does NOT isolate a no_parallel test: --dist loadgroup pins
    # the group to one worker, but that worker still runs unrelated tests, so a
    # test that mutates or reads process-global state can still be poisoned by
    # (or poison) whatever lands beside it. The only reliable isolation is to
    # keep these out of the parallel run entirely and execute them in a separate
    # serial pass — see _run_serial_phase in tests/TESTING.md.
    # `hasplugin` is true whenever xdist is merely installed, so it cannot tell
    # a parallel run from a serial one. `-n` is what actually forks workers —
    # but this hook also runs inside each worker, where `numprocesses` is unset
    # and `workerinput` is present instead. Both must be checked or the
    # controller deselects while the workers still collect and run the tests.
    running_parallel = bool(getattr(config.option, "numprocesses", None)) or hasattr(
        config, "workerinput"
    )
    if running_parallel and os.environ.get("AUDIAGENTIC_SERIAL_PHASE") != "1":
        deselected = [
            item for item in items if item.get_closest_marker("no_parallel") is not None
        ]
        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = [item for item in items if item not in deselected]
            config.stash[_DESELECTED_SERIAL_COUNT] = len(deselected)
        serial_modules = set()

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
            if item.get_closest_marker("requires_container") is not None:
                item.add_marker(skip_container)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Warn loudly when a parallel run held back the serial-only tests.

    Without this, `pytest -n auto` reports all-green while silently omitting
    every test that asserts process-global state — exactly the tests most
    likely to catch a real regression.
    """
    held = config.stash.get(_DESELECTED_SERIAL_COUNT, 0)
    if not held:
        return
    terminalreporter.write_sep("=", "serial-only tests NOT run", yellow=True, bold=True)
    terminalreporter.write_line(
        f"{held} test(s) marked no_parallel were excluded from this parallel run."
    )
    terminalreporter.write_line(
        "They need process isolation. Run the serial phase to complete the suite:"
    )
    terminalreporter.write_line(
        '    AUDIAGENTIC_SERIAL_PHASE=1 python -m pytest -m no_parallel <paths>'
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail Docker lanes that collected tests but ran none successfully.

    A marker-gated Docker command can otherwise report success when every
    collected test is skipped. Docker lanes are intended to prove execution,
    so an all-skipped lane must be visible as a failure.
    """
    if os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1":
        return
    if not session.testscollected:
        return
    terminalreporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminalreporter is None:
        return
    passed = len(terminalreporter.stats.get("passed", []))
    if passed == 0:
        terminalreporter.write_sep("=", "Docker lane ran no passing tests", red=True, bold=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
