"""Pytest plugin emitting bounded collection/execution evidence, not test logs."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--ci-evidence", default=None)


def pytest_configure(config):
    config._ci_nodes = []
    config._ci_results = {}


def pytest_collection_finish(session):
    session.config._ci_nodes = [
        {"nodeid": item.nodeid, "markers": sorted({marker.name for marker in item.iter_markers()})}
        for item in session.items
    ]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    item.config._ci_results.setdefault(item.nodeid, {})[report.when] = {
        "outcome": report.outcome,
        "seconds": round(report.duration, 6),
    }


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    path = config.getoption("--ci-evidence")
    if not path:
        return
    # Nested pytest subprocesses inherit their parent's environment but are
    # not xdist workers themselves. Configuration, not inherited env, owns ID.
    worker_input = getattr(config, "workerinput", None)
    worker = worker_input.get("workerid") if isinstance(worker_input, dict) else None
    destination = Path(path)
    if worker:
        destination = destination.with_name(f"{destination.stem}-{worker}{destination.suffix}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema": 1,
                "source_sha": os.environ.get("CI_SOURCE_SHA"),
                "nodes": config._ci_nodes,
                "results": config._ci_results,
                "exitstatus": int(exitstatus),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
