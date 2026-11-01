"""``gateway where``: one offline report of where the gateway's configuration lives (CFG15-B).

Nothing is started or contacted and no credential is read; a missing or invalid document is
reported as a status, never raised, so the report is always available as the first thing to run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

from . import init_setup, shared_config


def _origin(settings: Any, key: str) -> str | None:
    origin = settings.origin(key)
    return None if origin is None else f"{origin.scope} ({origin.file or 'command line'})"


def _document(loader: Any, path: Path, **kwargs: Any) -> tuple[str, Any]:
    if not path.is_file():
        return "missing", None
    try:
        return "valid", loader(path, **kwargs)
    except AudiaGenticError as error:
        return f"invalid: {error.message}", None


def gateway_where(*, project: Path | None = None) -> dict[str, Any]:
    """The default gateway directory, the effective connector binding and the project's served identity."""
    from audiagentic.foundation.config.settings import discover_project_root, resolve_settings

    directory = init_setup.default_directory()
    report: dict[str, Any] = {"directory": str(directory)}
    server_status, server = _document(shared_config.load_shared_server_config, directory / "server.yaml",
                                      default_root=None)
    connector_status, _ = _document(shared_config.load_shared_connector_config, directory / "connector.yaml")
    report["files"] = {
        "server.yaml": server_status, "connector.yaml": connector_status,
        "credentials/operator.token": "present" if (directory / "credentials" / "operator.token").is_file()
        else "missing",
    }
    if server is not None:
        report["served-projects"] = {key: str(root) for key, root in server.projects.items()}
        report["server-id"] = server.server_id
    try:
        root = discover_project_root(project, cwd=Path.cwd())
        settings = resolve_settings(project=root, cwd=Path.cwd())
    except AudiaGenticError as error:
        report["settings"] = f"invalid: {error.message}"
        return report
    bound = settings.get("gateway.connector")
    report["implementation"] = {"value": settings.get("gateway.implementation"),
                                "source": _origin(settings, "gateway.implementation")}
    connection: dict[str, Any] = {"connector": bound, "source": _origin(settings, "gateway.connector")}
    if bound:
        path = Path(str(bound)).expanduser()
        connection["is-generated-default"] = path == directory / "connector.yaml"
        status, connector = _document(shared_config.load_shared_connector_config, path)
        connection["status"] = status
        if connector is not None:
            connection.update({"mode": connector.mode, "endpoint": connector.endpoint,
                               "server-id": connector.server_id})
    report["connection"] = connection
    declared = settings.get("project.id")
    if root is None:
        report["project"] = {"root": None}
    elif declared:
        report["project"] = {"root": str(root), "id": declared, "source": _origin(settings, "project.id")}
    else:
        report["project"] = {"root": str(root), "id": None,
                             "note": "no declared project.id; run: audiagentic gateway init"}
    return report
