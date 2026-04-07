"""Validate packet dependency graph."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "implementation" / "31_Build_Status_and_Work_Registry.md"

PACKET_ID_PATTERN = re.compile(r"PKT-[A-Z]{3}-\d{3}")

PHASE_BY_PREFIX = {
    "FND": 0,
    "LFC": 1,
    "RLS": 2,
    "JOB": 3,
    "PRV": 4,
    "DSC": 5,
    "MIG": 6,
}


@dataclass
class PacketRow:
    packet_id: str
    dependency_state: str


def _parse_registry(path: Path) -> dict[str, PacketRow]:
    rows: dict[str, PacketRow] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("| PKT-"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if not parts:
            continue
        packet_id = parts[0]
        dependency_state = parts[5] if len(parts) > 5 else ""
        rows[packet_id] = PacketRow(packet_id=packet_id, dependency_state=dependency_state)
    return rows


def _phase_for_packet(packet_id: str) -> int:
    prefix = packet_id.split("-")[1]
    return PHASE_BY_PREFIX.get(prefix, 99)


def _extract_dependencies(dependency_state: str) -> list[str]:
    return PACKET_ID_PATTERN.findall(dependency_state)


def validate_registry(path: Path) -> dict[str, object]:
    rows = _parse_registry(path)
    issues: list[dict[str, str]] = []
    graph: dict[str, list[str]] = {packet: [] for packet in rows}

    for packet_id, row in rows.items():
        deps = _extract_dependencies(row.dependency_state)
        for dep in deps:
            if dep not in rows:
                issues.append({"packet": packet_id, "issue": f"unknown dependency: {dep}"})
                continue
            graph[packet_id].append(dep)
            packet_phase = _phase_for_packet(packet_id)
            dep_phase = _phase_for_packet(dep)
            if dep_phase > packet_phase:
                note = row.dependency_state.lower()
                if "seam" not in note and "stub" not in note:
                    issues.append(
                        {
                            "packet": packet_id,
                            "issue": f"forward-phase dependency without seam note: {dep}",
                        }
                    )

    # cycle detection
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if visit(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    for node in graph:
        if visit(node):
            issues.append({"packet": node, "issue": "circular dependency detected"})
            break

    # topological order
    indegree = {node: 0 for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            indegree[dep] += 1
    queue = deque([node for node, deg in indegree.items() if deg == 0])
    topo: list[str] = []
    while queue:
        node = queue.popleft()
        topo.append(node)
        for dep in graph.get(node, []):
            indegree[dep] -= 1
            if indegree[dep] == 0:
                queue.append(dep)

    if len(topo) != len(graph):
        issues.append({"packet": "graph", "issue": "topological sort incomplete"})

    status = "ok" if not issues else "error"
    return {"status": status, "issues": issues, "topological_order": topo}


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate packet dependency graph")
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    args = parser.parse_args(argv)
    result = validate_registry(Path(args.registry))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
