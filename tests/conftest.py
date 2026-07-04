from __future__ import annotations

import os
import sys
from pathlib import Path

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
