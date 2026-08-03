"""AS59 Stage 1 — composition builder, config schema and graph invariants.

Covers the cases AS59's Validation section names: binding selection, unknown
service ID, unknown implementation ID, missing implementation, duplicate
implementation, cycle rejection, immutable built graph, reverse-order finalizer
execution, and build-time fake substitution.
"""
from __future__ import annotations

import pytest

from audiagentic.foundation.composition import (
    CompositionConfig,
    ImplementationId,
    ServiceContribution,
    ServiceId,
    build_graph,
    parse_composition_config,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

ALPHA = ServiceId("test.alpha")
BETA = ServiceId("test.beta")
GAMMA = ServiceId("test.gamma")


class _Recorder:
    """Records construction and finalization order across a whole build."""

    def __init__(self) -> None:
        self.finalized: list[str] = []


def _leaf(name: str, recorder: _Recorder | None = None) -> ServiceContribution:
    return ServiceContribution(
        service_id=ServiceId(f"test.{name}"),
        implementation_id=ImplementationId(f"test.{name}-impl"),
        factory=lambda: f"{name}-instance",
        finalizer=(lambda _inst, n=name: recorder.finalized.append(n)) if recorder else None,
    )


def _config(roots: list[str], bindings: dict[str, str]) -> CompositionConfig:
    return CompositionConfig(
        roots=tuple(ServiceId(r) for r in roots),
        bindings={ServiceId(k): ImplementationId(v) for k, v in bindings.items()},
    )


# --- binding selection -------------------------------------------------------


def test_binding_selects_between_two_implementations_of_one_service() -> None:
    contributions = (
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.first"),
            factory=lambda: "first",
        ),
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.second"),
            factory=lambda: "second",
        ),
    )
    graph = build_graph(contributions, _config(["test.alpha"], {"test.alpha": "test.second"}))
    assert graph.root(ALPHA) == "second"


def test_dependencies_are_passed_by_parameter_name() -> None:
    """`requires` keys the factory's parameter, so two deps of one shape work."""
    contributions = (
        ServiceContribution(
            service_id=BETA,
            implementation_id=ImplementationId("test.beta-impl"),
            factory=lambda: "beta",
        ),
        ServiceContribution(
            service_id=GAMMA,
            implementation_id=ImplementationId("test.gamma-impl"),
            factory=lambda: "gamma",
        ),
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.alpha-impl"),
            factory=lambda left, right: f"{left}+{right}",
            requires={"left": BETA, "right": GAMMA},
        ),
    )
    graph = build_graph(
        contributions,
        _config(
            ["test.alpha"],
            {
                "test.alpha": "test.alpha-impl",
                "test.beta": "test.beta-impl",
                "test.gamma": "test.gamma-impl",
            },
        ),
    )
    assert graph.root(ALPHA) == "beta+gamma"


def test_a_shared_dependency_is_constructed_once() -> None:
    builds: list[str] = []

    def build_shared() -> object:
        builds.append("shared")
        return object()

    contributions = (
        ServiceContribution(
            service_id=GAMMA,
            implementation_id=ImplementationId("test.gamma-impl"),
            factory=build_shared,
        ),
        ServiceContribution(
            service_id=BETA,
            implementation_id=ImplementationId("test.beta-impl"),
            factory=lambda dep: dep,
            requires={"dep": GAMMA},
        ),
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.alpha-impl"),
            factory=lambda one, two: (one, two),
            requires={"one": BETA, "two": GAMMA},
        ),
    )
    graph = build_graph(
        contributions,
        _config(
            ["test.alpha"],
            {
                "test.alpha": "test.alpha-impl",
                "test.beta": "test.beta-impl",
                "test.gamma": "test.gamma-impl",
            },
        ),
    )
    assert builds == ["shared"]
    one, two = graph.root(ALPHA)
    assert one is two


def test_unreachable_bindings_are_not_constructed() -> None:
    """An unreachable binding is dead config, not a live dependency."""
    builds: list[str] = []
    contributions = (
        _leaf("alpha"),
        ServiceContribution(
            service_id=BETA,
            implementation_id=ImplementationId("test.beta-impl"),
            factory=lambda: builds.append("beta"),
        ),
    )
    graph = build_graph(
        contributions,
        _config(["test.alpha"], {"test.alpha": "test.alpha-impl", "test.beta": "test.beta-impl"}),
    )
    assert builds == []
    assert graph.construction_order == (ALPHA,)


# --- deterministic errors ----------------------------------------------------


def test_binding_naming_unknown_service_is_rejected() -> None:
    with pytest.raises(AudiaGenticError) as exc:
        build_graph((_leaf("alpha"),), _config(["test.alpha"], {"test.nope": "test.x"}))
    assert exc.value.code == "VAL-COMPOSE-003"


def test_binding_naming_unknown_implementation_is_rejected() -> None:
    with pytest.raises(AudiaGenticError) as exc:
        build_graph((_leaf("alpha"),), _config(["test.alpha"], {"test.alpha": "test.missing"}))
    assert exc.value.code == "VAL-COMPOSE-004"


def test_unknown_binding_is_caught_even_when_unreachable() -> None:
    """A typo in an unused binding must not lie dormant until it is reached."""
    with pytest.raises(AudiaGenticError) as exc:
        build_graph(
            (_leaf("alpha"),),
            _config(["test.alpha"], {"test.alpha": "test.alpha-impl", "test.ghost": "test.x"}),
        )
    assert exc.value.code == "VAL-COMPOSE-003"


def test_duplicate_implementation_for_one_service_is_rejected() -> None:
    duplicate = (
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.same"),
            factory=lambda: 1,
        ),
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.same"),
            factory=lambda: 2,
        ),
    )
    with pytest.raises(AudiaGenticError) as exc:
        build_graph(duplicate, _config(["test.alpha"], {"test.alpha": "test.same"}))
    assert exc.value.code == "VAL-COMPOSE-005"


def test_reachable_service_without_a_binding_is_rejected() -> None:
    """No implicit default, even when a service has exactly one implementation."""
    contributions = (
        _leaf("beta"),
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.alpha-impl"),
            factory=lambda dep: dep,
            requires={"dep": BETA},
        ),
    )
    with pytest.raises(AudiaGenticError) as exc:
        build_graph(contributions, _config(["test.alpha"], {"test.alpha": "test.alpha-impl"}))
    assert exc.value.code == "VAL-COMPOSE-006"
    assert exc.value.details is not None
    assert exc.value.details["required_by"] == "test.alpha"


def test_cycle_is_rejected_and_reports_the_participating_services_in_order() -> None:
    contributions = (
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.alpha-impl"),
            factory=lambda dep: dep,
            requires={"dep": BETA},
        ),
        ServiceContribution(
            service_id=BETA,
            implementation_id=ImplementationId("test.beta-impl"),
            factory=lambda dep: dep,
            requires={"dep": ALPHA},
        ),
    )
    with pytest.raises(AudiaGenticError) as exc:
        build_graph(
            contributions,
            _config(["test.alpha"], {"test.alpha": "test.alpha-impl", "test.beta": "test.beta-impl"}),
        )
    assert exc.value.code == "CON-COMPOSE-001"
    assert exc.value.details is not None
    assert exc.value.details["cycle"] == ["test.alpha", "test.beta", "test.alpha"]


def test_malformed_contribution_is_rejected_at_construction() -> None:
    with pytest.raises(AudiaGenticError) as exc:
        ServiceContribution(
            service_id=ServiceId(""),
            implementation_id=ImplementationId("test.x"),
            factory=lambda: None,
        )
    assert exc.value.code == "VAL-COMPOSE-007"


# --- graph shape and lifetime ------------------------------------------------


def test_built_graph_exposes_roots_only_not_arbitrary_services() -> None:
    """There is no runtime get(): a dependency is not reachable through roots."""
    contributions = (
        _leaf("beta"),
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.alpha-impl"),
            factory=lambda dep: dep,
            requires={"dep": BETA},
        ),
    )
    graph = build_graph(
        contributions,
        _config(["test.alpha"], {"test.alpha": "test.alpha-impl", "test.beta": "test.beta-impl"}),
    )
    assert graph.root(ALPHA) == "beta-instance"
    with pytest.raises(KeyError):
        graph.root(BETA)


def test_finalizers_run_in_reverse_construction_order() -> None:
    recorder = _Recorder()
    contributions = (
        _leaf("gamma", recorder),
        ServiceContribution(
            service_id=BETA,
            implementation_id=ImplementationId("test.beta-impl"),
            factory=lambda dep: dep,
            requires={"dep": GAMMA},
            finalizer=lambda _inst: recorder.finalized.append("beta"),
        ),
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.alpha-impl"),
            factory=lambda dep: dep,
            requires={"dep": BETA},
            finalizer=lambda _inst: recorder.finalized.append("alpha"),
        ),
    )
    graph = build_graph(
        contributions,
        _config(
            ["test.alpha"],
            {
                "test.alpha": "test.alpha-impl",
                "test.beta": "test.beta-impl",
                "test.gamma": "test.gamma-impl",
            },
        ),
    )
    assert graph.construction_order == (GAMMA, BETA, ALPHA)
    graph.shutdown()
    assert recorder.finalized == ["alpha", "beta", "gamma"]


def test_shutdown_is_idempotent() -> None:
    recorder = _Recorder()
    graph = build_graph(
        (_leaf("alpha", recorder),),
        _config(["test.alpha"], {"test.alpha": "test.alpha-impl"}),
    )
    graph.shutdown()
    graph.shutdown()
    assert recorder.finalized == ["alpha"]


def test_a_failing_finalizer_does_not_abandon_the_remaining_ones() -> None:
    recorder = _Recorder()

    def explode(_inst: object) -> None:
        raise RuntimeError("finalizer failed")

    contributions = (
        _leaf("gamma", recorder),
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.alpha-impl"),
            factory=lambda dep: dep,
            requires={"dep": GAMMA},
            finalizer=explode,
        ),
    )
    graph = build_graph(
        contributions,
        _config(["test.alpha"], {"test.alpha": "test.alpha-impl", "test.gamma": "test.gamma-impl"}),
    )
    graph.shutdown()
    assert recorder.finalized == ["gamma"]


def test_build_time_substitution_replaces_a_service_and_its_subtree() -> None:
    built: list[str] = []

    def real_dependency() -> str:
        built.append("real")
        return "real"

    contributions = (
        ServiceContribution(
            service_id=BETA,
            implementation_id=ImplementationId("test.beta-impl"),
            factory=real_dependency,
        ),
        ServiceContribution(
            service_id=ALPHA,
            implementation_id=ImplementationId("test.alpha-impl"),
            factory=lambda dep: f"alpha({dep})",
            requires={"dep": BETA},
        ),
    )
    graph = build_graph(
        contributions,
        _config(["test.alpha"], {"test.alpha": "test.alpha-impl", "test.beta": "test.beta-impl"}),
        overrides={BETA: "fake"},
    )
    assert graph.root(ALPHA) == "alpha(fake)"
    assert built == []


# --- config schema -----------------------------------------------------------


def test_config_parses_roots_and_bindings() -> None:
    config = parse_composition_config(
        {
            "composition": {
                "roots": ["runtime.application-host"],
                "bindings": {"runtime.application-host": "runtime.default-host"},
            }
        }
    )
    assert config.roots == (ServiceId("runtime.application-host"),)
    assert config.bindings[ServiceId("runtime.application-host")] == "runtime.default-host"


@pytest.mark.parametrize(
    "value",
    [
        "audiagentic.runtime.bootstrap:ApplicationHost",
        "runtime/bootstrap/application_host.py",
        "audiagentic.runtime.bootstrap.ApplicationHost",
        "runtime.application_host",
    ],
)
def test_config_rejects_python_paths_in_bindings(value: str) -> None:
    """AS59: composition YAML selects identifiers; it never names code."""
    with pytest.raises(AudiaGenticError) as exc:
        parse_composition_config({"composition": {"bindings": {"runtime.application-host": value}}})
    assert exc.value.code == "VAL-COMPOSE-002"


def test_config_rejects_python_paths_in_roots() -> None:
    with pytest.raises(AudiaGenticError) as exc:
        parse_composition_config({"composition": {"roots": ["pkg.mod:Class"]}})
    assert exc.value.code == "VAL-COMPOSE-002"


@pytest.mark.parametrize(
    "raw",
    [
        {"composition": {"roots": "not-a-list"}},
        {"composition": {"bindings": ["not-a-mapping"]}},
        {"composition": {"unexpected": {}}},
        {"composition": {"roots": ["test.a", "test.a"]}},
        "not-a-mapping",
    ],
)
def test_config_rejects_malformed_shapes(raw: object) -> None:
    with pytest.raises(AudiaGenticError) as exc:
        parse_composition_config(raw)
    assert exc.value.code == "VAL-COMPOSE-001"


def test_empty_config_is_valid_and_builds_nothing() -> None:
    config = parse_composition_config({})
    graph = build_graph((), config)
    assert graph.construction_order == ()
