"""Operator-owned canonical Agents configuration MCP surface."""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def agent_config_read() -> dict[str, Any]:
    return AgentsConfigRepository().read(project_root_from_env()).document.to_mapping()


@mcp.tool()
@tool_boundary
def agent_config_describe() -> dict[str, Any]:
    snapshot = AgentsConfigRepository().read(project_root_from_env())
    return {"contract-version": snapshot.document.contract_version, "digest": snapshot.digest, "kinds": ["prompt", "role", "execution_profile", "agent"]}


@mcp.tool()
@tool_boundary
def agent_config_apply(document: dict[str, Any], expected_digest: str | None = None) -> dict[str, Any]:
    root = project_root_from_env()
    repository = AgentsConfigRepository()
    current = repository.read(root)
    written = repository.replace(root, AgentsConfigDocument.from_mapping(document), expected_digest=expected_digest)
    return {"digest": written.digest, "previous-digest": current.digest}


@mcp.tool()
@tool_boundary
def agent_config_put(kind: str, item: dict[str, Any], expected_digest: str) -> dict[str, Any]:
    return {"digest": AgentsConfigRepository().put(project_root_from_env(), kind, item, expected_digest=expected_digest).digest}


@mcp.tool()
@tool_boundary
def agent_config_delete(kind: str, item_id: str, expected_digest: str) -> dict[str, Any]:
    return {"digest": AgentsConfigRepository().delete(project_root_from_env(), kind, item_id, expected_digest=expected_digest).digest}


@mcp.tool()
@tool_boundary
def agent_config_validate(document: dict[str, Any] | None = None) -> list[str]:
    root = project_root_from_env()
    candidate = AgentsConfigDocument.from_mapping(document) if document is not None else AgentsConfigRepository().read(root).document
    return list(AgentsConfigRepository().validate(candidate))


@mcp.tool()
@tool_boundary
def agent_config_get(kind: str, item_id: str) -> dict[str, Any]:
    return AgentsConfigRepository().get(project_root_from_env(), kind, item_id)


@mcp.tool()
@tool_boundary
def agent_resolve(agent_id: str) -> dict[str, Any]:
    from audiagentic.components.agents.configuration.resolution import resolve_agent
    return resolve_agent(AgentsConfigRepository().read(project_root_from_env()).document, agent_id)


def main() -> None:
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
