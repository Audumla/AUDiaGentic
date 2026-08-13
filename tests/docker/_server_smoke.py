"""Smoke test every declared AUDiaGentic Python MCP server.

Loads server declarations from the component registry so new MCP servers are
covered automatically. For each server, import/build it, list tools, and run a
small read-only smoke subset when arguments are simple and deterministic.

Empty/not-installed results count as pass; only raised exceptions are failures.
Exit non-zero if any declared server errors.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

_ROOT = Path("/tmp/audiagentic-server-smoke").resolve()
_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["AUDIAGENTIC_REPO_ROOT"] = str(_ROOT)

# module -> tool -> params
SMOKE_CALLS: dict[str, dict[str, dict[str, object]]] = {
    "audiagentic.components.project.project_mcp": {
        "list_components": {},
        "project_status": {},
    },
    "audiagentic.components.session.session_mcp": {
        "config": {},
    },
    "audiagentic.components.ledger.ledger_mcp": {
        "get_current_summary": {},
    },
    "audiagentic.components.ledger.ledger_manage_mcp": {
        "get_ledger_status": {},
    },
    "audiagentic.components.coding_lsp.lsp_manage_mcp": {
        "lsp_config_status": {},
        "lsp_list_languages": {},
        "lsp_list_missing": {},
    },
    "audiagentic.components.providers.providers_mcp": {
        "list_providers": {},
        "list_provider_descriptors": {},
    },
    "audiagentic.components.source_control.source_control_mcp": {
        "get_source_control_status": {},
    },
    "audiagentic.components.release.release_mcp": {
        "get_release_status": {},
    },
}


def _declared_servers() -> list[tuple[str, str]]:
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import all_descriptors

    register_all_components()
    servers: list[tuple[str, str]] = []
    for descriptor in all_descriptors().values():
        for server in descriptor.mcp_servers:
            servers.append((server.name, server.module))
    return sorted(set(servers), key=lambda item: item[0])


async def get_mcp(mod: str):
    if mod == "audiagentic.components.session.session_mcp":
        # The smoke harness imports/builds the server directly instead of
        # invoking its __main__ composition root.
        from audiagentic.runtime.harness import wire_harness_status

        wire_harness_status()
    m = importlib.import_module(mod)
    return m.build_server() if hasattr(m, "build_server") else m.mcp


async def main() -> int:
    failures = 0
    for label, mod in _declared_servers():
        try:
            mcp = await get_mcp(mod)
            tools = await mcp.list_tools()
            names = [t.name for t in tools]
            print(f"[OK ] {label:<16} {len(names)} tools")
            for c, params in SMOKE_CALLS.get(mod, {}).items():
                if c not in names:
                    print(f"        - {c}: SKIP (not registered)")
                    continue
                try:
                    result = await mcp.call_tool(c, params)
                    # Semantic success: no raised exception AND not an error envelope.
                    if getattr(result, "is_error", False):
                        text_parts = [
                            getattr(b, "text", str(b)) for b in getattr(result, "content", [])
                        ]
                        detail = " ".join(text_parts)[:120]
                        if "missing materialized models config" in detail:
                            print(f"        - {c}: SKIP (harness not materialized)")
                        else:
                            failures += 1
                            print(f"        - {c}: FAIL (error envelope) {detail}")
                    else:
                        print(f"        - {c}: ok")
                except Exception as e:  # noqa: BLE001
                    failures += 1
                    print(f"        - {c}: FAIL {type(e).__name__}: {str(e)[:120]}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"[ERR] {label:<16} {type(e).__name__}: {str(e)[:160]}")
    print(f"\n=== {'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'} ===")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
