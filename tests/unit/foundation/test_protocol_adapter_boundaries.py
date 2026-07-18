"""AR25 architecture enforcement for protocol-adapter dependency direction."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPONENTS = ROOT / "src" / "audiagentic" / "components"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _component_imports(path: Path) -> set[str]:
    """Return fully qualified component imports, including from-import names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names if ".components." in alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and ".components." in node.module:
            result.update(f"{node.module}.{alias.name}" for alias in node.names)
    return result


def test_component_api_modules_do_not_import_mcp_framework() -> None:
    violations: list[str] = []
    for path in sorted(COMPONENTS.rglob("*_api.py")):
        for target in _imports(path):
            if target.startswith("audiagentic.foundation.mcp") or target.startswith("fastmcp"):
                violations.append(f"{path.relative_to(ROOT)} imports {target}")
    assert not violations, "API modules depend on MCP framework:\n" + "\n".join(violations)


def test_component_mcp_adapters_do_not_import_owning_internals() -> None:
    """Every MCP adapter stays on its component's API/client/contract edge."""
    violations: list[str] = []
    for path in sorted(COMPONENTS.rglob("*_mcp.py")):
        component = path.relative_to(COMPONENTS).parts[0]
        prefix = f"audiagentic.components.{component}."
        for target in _component_imports(path):
            if not target.startswith(prefix):
                continue
            relative = target.removeprefix(prefix)
            allowed = (
                ".contracts." in target
                or relative.endswith("_api")
                or relative.endswith("_client")
                or "_api." in relative
                or "_client." in relative
            )
            if not allowed:
                violations.append(f"{path.relative_to(ROOT)} imports {target}")
    assert not violations, "MCP adapters import owning-component internals:\n" + "\n".join(violations)


def test_gateway_mcp_imports_only_public_client_and_mcp_scaffolding() -> None:
    path = COMPONENTS / "agents" / "agents_gateway_mcp.py"
    forbidden = (
        "agents_gateway_api",
        "agents_gateway_store",
        "agents_gateway_queue",
        "agents_gateway_dispatch",
        "agents_gateway_application",
    )
    imports = _imports(path)
    violations = [target for target in imports if any(name in target for name in forbidden)]
    assert not violations
    assert "audiagentic.components.agents.agents_gateway_client" in imports


def test_gateway_core_owns_no_mcp_timeout_constant() -> None:
    source = (COMPONENTS / "agents" / "agents_gateway_api.py").read_text(encoding="utf-8")
    assert "MCP_BLOCKING_TIMEOUT_SECONDS" not in source
    assert "MAX_BLOCKING_TIMEOUT_SECONDS" not in source


def test_gateway_http_adapter_calls_only_service_application_boundary() -> None:
    path = COMPONENTS / "agents" / "agents_gateway_http_transport.py"
    imports = _imports(path)
    forbidden = (
        "agents_gateway_api",
        "agents_gateway_store",
        "agents_gateway_queue",
        "agents_gateway_dispatch",
        "managed_service",
        "managed_process",
    )
    violations = [target for target in imports if any(name in target for name in forbidden)]
    assert not violations
    assert "audiagentic.components.agents.agents_gateway_service_application" in imports


def test_gateway_service_application_has_no_http_framework_dependency() -> None:
    path = COMPONENTS / "agents" / "agents_gateway_service_application.py"
    imports = _imports(path)
    assert not any(target.startswith(("http", "urllib", "fastapi", "flask")) for target in imports)
