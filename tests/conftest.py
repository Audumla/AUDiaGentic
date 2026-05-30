from __future__ import annotations

import os

import pytest

_TIER_MARKERS = {
    "/unit/": "unit",
    "/integration/": "integration",
    "/e2e/": "e2e",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    docker_ok = os.environ.get("AUDIAGENTIC_DOCKER_TESTS") == "1"
    opt_in_ok = os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") == "1"

    skip_mutating = pytest.mark.skip(
        reason=(
            "mutates_host tests are disabled by default; run only with "
            "AUDIAGENTIC_DOCKER_TESTS=1 and AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1"
        )
    )

    for item in items:
        node = item.nodeid.replace("\\", "/")

        # Auto-apply tier marker from directory path
        for path_fragment, marker_name in _TIER_MARKERS.items():
            if path_fragment in node:
                item.add_marker(getattr(pytest.mark, marker_name))
                break

        # Gate mutates_host tests
        if not (docker_ok and opt_in_ok):
            if item.get_closest_marker("mutates_host") is not None:
                item.add_marker(skip_mutating)
