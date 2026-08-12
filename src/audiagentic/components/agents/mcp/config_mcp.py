"""Operator-owned canonical Agents configuration MCP surface."""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents.configuration.configuration_api import AgentsConfigService
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
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
    return AgentsConfigService().read(project_root_from_env()).document.to_mapping()


@mcp.tool()
@tool_boundary
def agent_config_describe() -> dict[str, Any]:
    snapshot = AgentsConfigService().read(project_root_from_env())
    return {"contract-version": snapshot.document.contract_version, "digest": snapshot.digest, "kinds": ["prompt", "role", "execution_profile", "agent", "trigger"]}


@mcp.tool()
@tool_boundary
def agent_config_apply(document: dict[str, Any], expected_digest: str | None = None) -> dict[str, Any]:
    root = project_root_from_env()
    service = AgentsConfigService()
    current = service.read(root)
    written = service.apply(root, AgentsConfigDocument.from_mapping(document), expected_digest=expected_digest)
    return {"digest": written.digest, "previous-digest": current.digest}


@mcp.tool()
@tool_boundary
def agent_config_put(kind: str, item: dict[str, Any], expected_digest: str) -> dict[str, Any]:
    return {"digest": AgentsConfigService().put(project_root_from_env(), kind, item, expected_digest=expected_digest).digest}


@mcp.tool()
@tool_boundary
def agent_config_delete(kind: str, item_id: str, expected_digest: str) -> dict[str, Any]:
    return {"digest": AgentsConfigService().delete(project_root_from_env(), kind, item_id, expected_digest=expected_digest).digest}


@mcp.tool()
@tool_boundary
def agent_config_validate(document: dict[str, Any] | None = None) -> list[str]:
    root = project_root_from_env()
    service = AgentsConfigService()
    candidate = AgentsConfigDocument.from_mapping(document) if document is not None else service.read(root).document
    return list(service.validate(candidate))


@mcp.tool()
@tool_boundary
def agent_config_get(kind: str, item_id: str) -> dict[str, Any]:
    return AgentsConfigService().get(project_root_from_env(), kind, item_id)


@mcp.tool()
@tool_boundary
def agent_resolve(agent_id: str) -> dict[str, Any]:
    return AgentsConfigService().resolve(project_root_from_env(), agent_id)


def main() -> None:
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
