"""Pure declaration discovery and owner help projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.components.loader import read_component_metadata
from audiagentic.foundation.contracts.errors import AudiaGenticError


def error(message: str, **details: Any) -> AudiaGenticError:
    return AudiaGenticError(code="VAL-MCPONB-001", kind="project", message=message, details=details)


def catalog(
    root: Path | None = None, mcp_id: str | None = None
) -> list[dict[str, Any]] | dict[str, Any]:
    from audiagentic.components.providers import providers_api

    targets = providers_api.list_harness_mcp_targets()
    entries: dict[str, dict[str, Any]] = {}
    managed: set[str] = set()
    for owner in read_component_metadata(root):
        for declaration in (*owner.mcp_servers, *owner.external_mcp_servers):
            identity = declaration.managed_id or declaration.name
            if declaration.name in entries or identity in managed:
                raise error("Duplicate MCP declaration identity")
            if declaration.name in {"help", "list", "install"}:
                raise error("MCP identity conflicts with a management keyword")
            managed.add(identity)
            eligible = "providers" in declaration.propagate
            entry: dict[str, Any] = {
                "mcp_id": declaration.name,
                "component_id": owner.component_id,
                "managed_id": identity,
                "description": declaration.description,
                "provider_eligible": eligible,
            }
            if mcp_id == declaration.name:
                from .requirements import describe

                entry.update(
                    configuration=describe(root, owner.component_id),
                    instructions=declaration.instructions,
                    tool_descriptions=getattr(declaration, "tool_descriptions", {}),
                    harness_targets=[
                        t.to_mapping() for t in targets if t.supported and t.project_scoped
                    ]
                    if eligible
                    else [],
                    requires=list(getattr(declaration, "requires", ())),
                )
            entries[declaration.name] = entry
    if mcp_id is not None:
        if mcp_id not in entries:
            raise error("Unknown canonical MCP ID", mcp_id=mcp_id)
        return entries[mcp_id]
    return [entries[key] for key in sorted(entries)]
