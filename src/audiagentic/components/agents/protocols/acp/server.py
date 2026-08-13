"""Composition helper for constructing an ACP Agent from approved public ports."""
from pathlib import Path

from .agent import AcpAgent, AgentsPort


def build_agent(project_root: Path, agent_id: str, ports: AgentsPort) -> AcpAgent:
    return AcpAgent(project_root, agent_id, ports)
