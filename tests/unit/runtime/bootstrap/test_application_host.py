"""AS59 Stage 1 — the application host starts/stops the graph, and is injected.

AS59's Validation asks this file to prove two things: the host starts and shuts
down through the graph, and the first migrated dependency is *injected* rather
than constructed inside the host.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.composition import (
    CompositionConfig,
    ImplementationId,
    ServiceId,
    build_graph,
    parse_composition_config,
)
from audiagentic.foundation.io import load_yaml_file
from audiagentic.runtime.bootstrap import (
    APPLICATION_HOST,
    ApplicationHost,
    build_application_graph,
    builtin_contributions,
)
from audiagentic.runtime.bootstrap.composition import INTERACTION_BACKEND, _pkg_default_path

# The shipped package default, parsed once. Tests below build against this
# rather than a hand-written config so the packaged file stays covered.
_PACKAGED_CONFIG = parse_composition_config(load_yaml_file(_pkg_default_path()))


class _FakeBackend:
    """Stands in for CliBackend; identity is all these tests need."""


def test_packaged_config_builds_the_documented_graph() -> None:
    graph = build_graph(builtin_contributions(), _PACKAGED_CONFIG)
    try:
        assert graph.construction_order == (INTERACTION_BACKEND, APPLICATION_HOST)
        assert isinstance(graph.root(APPLICATION_HOST), ApplicationHost)
    finally:
        graph.shutdown()


def test_the_interaction_backend_is_injected_not_constructed_by_the_host() -> None:
    """The host must receive its dependency, not build one."""
    fake = _FakeBackend()
    graph = build_application_graph(
        config=_PACKAGED_CONFIG,
        overrides={INTERACTION_BACKEND: fake},
    )
    try:
        host = graph.root(APPLICATION_HOST)
        assert host._interaction_backend is fake
    finally:
        graph.shutdown()


def test_start_installs_the_injected_backend_as_the_live_one(tmp_path: Path) -> None:
    from audiagentic.foundation.interaction import backend as backend_mod

    fake = _FakeBackend()
    graph = build_application_graph(
        config=_PACKAGED_CONFIG,
        overrides={INTERACTION_BACKEND: fake},
    )
    previous = backend_mod._backend
    try:
        graph.root(APPLICATION_HOST).start(
            project_root=tmp_path,
            command="component",
            harness_status_functions=dict,
        )
        assert backend_mod._backend is fake
    finally:
        graph.shutdown()
        backend_mod._backend = previous


def test_start_is_idempotent_and_wires_harness_status_once(tmp_path: Path) -> None:
    calls: list[int] = []

    def status_functions() -> dict:
        calls.append(1)
        return {}

    host = ApplicationHost(interaction_backend=_FakeBackend())
    from audiagentic.foundation.interaction import backend as backend_mod

    previous = backend_mod._backend
    try:
        host.start(
            project_root=tmp_path, command=None, harness_status_functions=status_functions
        )
        host.start(
            project_root=tmp_path, command=None, harness_status_functions=status_functions
        )
        assert calls == [1]
    finally:
        host.shutdown()
        backend_mod._backend = previous


def test_harness_status_functions_are_resolved_lazily(tmp_path: Path) -> None:
    """Passing a callable keeps the runtime.harness import off the fast path."""
    resolved: list[str] = []

    def status_functions() -> dict:
        resolved.append("resolved")
        return {}

    host = ApplicationHost(interaction_backend=_FakeBackend())
    assert resolved == []

    from audiagentic.foundation.interaction import backend as backend_mod

    previous = backend_mod._backend
    try:
        host.start(
            project_root=tmp_path, command=None, harness_status_functions=status_functions
        )
        assert resolved == ["resolved"]
    finally:
        host.shutdown()
        backend_mod._backend = previous


def test_graph_shutdown_finalizes_the_host() -> None:
    graph = build_application_graph(
        config=_PACKAGED_CONFIG,
        overrides={INTERACTION_BACKEND: _FakeBackend()},
    )
    host = graph.root(APPLICATION_HOST)
    host._started = True
    graph.shutdown()
    assert host._started is False


def test_shutdown_before_start_is_a_no_op() -> None:
    ApplicationHost(interaction_backend=_FakeBackend()).shutdown()


def test_a_root_not_in_the_config_is_not_reachable() -> None:
    config = CompositionConfig(
        roots=(INTERACTION_BACKEND,),
        bindings={
            INTERACTION_BACKEND: ImplementationId("foundation.cli-interaction"),
        },
    )
    graph = build_graph(builtin_contributions(), config)
    try:
        with pytest.raises(KeyError):
            graph.root(ServiceId("runtime.application-host"))
    finally:
        graph.shutdown()
