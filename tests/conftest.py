from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    docker_ok = os.environ.get("AUDIAGENTIC_DOCKER_TESTS") == "1"
    opt_in_ok = os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") == "1"
    if docker_ok and opt_in_ok:
        return

    skip_mutating = pytest.mark.skip(
        reason=(
            "mutates_host tests are disabled by default; run only with "
            "AUDIAGENTIC_DOCKER_TESTS=1 and AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1"
        )
    )
    for item in items:
        if item.get_closest_marker("mutates_host") is not None:
            item.add_marker(skip_mutating)
