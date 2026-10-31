"""Deterministic CI coverage policy; no provider execution or network access."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

HERMETIC = "not mutates_host and not requires_container and not opt_in and not docker"
BROWSER_MODULES = frozenset(
    {
        "tests/unit/agents/test_gateway_dashboard_visual.py",
        "tests/unit/agents/test_project_discovery_dom.py",
    }
)
CDP_MODULES = (
    "tests/gpt_auto/test_browser_outage_recovery.py",
    "tests/gpt_auto/test_browser_outage_e2e.py",
    "tests/gpt_auto/test_greenfield_bridge_turn.py",
    "tests/gpt_auto/test_simulated_cdp_matrix.py",
    "tests/gpt_auto/test_python_cdp_bridge.py",
)
FULL_ROOTS = ("tests/unit", "tests/integration", "tests/e2e", *CDP_MODULES)
CRITICAL = (
    "tests/unit/contracts",
    "tests/unit/planning/test_plan_set_integrity.py",
    "tests/unit/agents/test_gateway_worker_protocol.py",
    "tests/unit/agents/test_agents_gateway_sessions.py",
    "tests/unit/agents/test_agents_gateway_provider_capture.py",
    "tests/unit/agents/test_agents_gateway_worker_watchdog.py",
    "tests/unit/agents/test_gateway_dashboard_restart.py",
    "tests/integration/agents/test_sh06_worker_isolation.py",
    *CDP_MODULES,
)


def fast_paths(root: Path, changed: list[str]) -> list[str]:
    """Always run critical behavior, plus available changed-component tests."""
    paths = set(CRITICAL)
    for name in changed:
        parts = Path(name).as_posix().split("/")
        if parts[:3] == ["src", "audiagentic", "components"] and len(parts) > 3:
            paths.add(f"tests/unit/{parts[3]}")
        elif parts[:3] == ["src", "audiagentic", "foundation"]:
            paths.add("tests/unit/foundation")
        elif (
            name.startswith("tests/")
            and name.endswith(".py")
            and Path(name).name.startswith("test_")
        ):
            # Only already-authorized hermetic roots, never arbitrary live scripts.
            if any(name.startswith(base + "/") for base in FULL_ROOTS[:3]) or name in CDP_MODULES:
                paths.add(name)
    for required in CRITICAL:
        if not (root / required).exists():
            raise ValueError(f"missing mandatory CI coverage: {required}")
    available = {path for path in paths if (root / path).exists() and path not in BROWSER_MODULES}
    return sorted(
        path
        for path in available
        if not any(
            other != path and (root / other).is_dir() and Path(path).is_relative_to(Path(other))
            for other in available
        )
    )


def partition(nodes: list[dict], count: int) -> dict[str, list[str]]:
    """Assign whole modules, keeping every serial module out of parallel lanes.

    Node counts are an initial balancing weight. Timing artifacts allow later
    measured rebalancing without making coverage depend on a warm cache.
    """
    if count < 1:
        raise ValueError("shard count must be positive")
    ids = [node["nodeid"] for node in nodes]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("CI collection must be nonempty with unique node IDs")
    modules: dict[str, list[dict]] = defaultdict(list)
    for node in nodes:
        modules[node["nodeid"].split("::", 1)[0]].append(node)
    lanes: dict[str, list[str]] = {
        "serial": [],
        "browser": [],
        **{f"shard-{i}": [] for i in range(count)},
    }
    weights = Counter()
    parallel = []
    for module, tests in modules.items():
        if module in BROWSER_MODULES:
            lanes["browser"].append(module)
        elif any("no_parallel" in test["markers"] for test in tests):
            lanes["serial"].append(module)
        else:
            parallel.append((module, len(tests)))
    if len(parallel) < count:
        raise ValueError("not enough independent modules for nonempty shards")
    for module, size in sorted(parallel, key=lambda item: (-item[1], item[0])):
        lane = min(range(count), key=lambda index: (weights[index], index))
        lanes[f"shard-{lane}"].append(module)
        weights[lane] += size
    flattened = [module for lane in lanes.values() for module in lane]
    if len(flattened) != len(set(flattened)) or set(flattened) != set(modules):
        raise ValueError("CI partition lost or duplicated modules")
    return {lane: sorted(paths) for lane, paths in lanes.items()}
