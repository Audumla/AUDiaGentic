"""Public API surface for the core project component."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from audiagentic.foundation.components.registry import is_enabled, is_installed
from audiagentic.foundation.features.registry import all_features, all_implementations
from audiagentic.foundation.features.resolver import resolve_feature, resolve_implementation
from audiagentic.foundation.io import load_yaml_file

from . import project_components, project_files, project_surfaces


def list_mcp_catalog(project_root: Path | None = None, mcp_id: str | None = None):
    """Read canonical MCP declarations, or owned help for one declaration."""
    from .onboarding.catalog import catalog

    return catalog(project_root, mcp_id)


def get_mcp_help(mcp_id: str, project_root: Path | None = None):
    """Read detailed owner metadata for one MCP."""
    return list_mcp_catalog(project_root, mcp_id)


def install_mcp(
    project_root: Path,
    *,
    mcp_id: str,
    harness_ids,
    dry_run: bool = False,
    config_file: Path | None = None,
    non_interactive: bool = True,
) -> dict:
    """Set one MCP's explicit native selection through Project-owned onboarding."""
    from .onboarding.service import install

    return install(
        project_root,
        mcp_id=mcp_id,
        harness_ids=harness_ids,
        dry_run=dry_run,
        config_file=config_file,
        non_interactive=non_interactive,
    )


def get_mcp_install_status(project_root: Path, operation_id: str | None = None) -> dict:
    """Read one operation or the latest unresolved operation without retrying it."""
    from .onboarding.service import status

    return status(project_root, operation_id)


def reconcile_mcp_bindings(project_root: Path) -> list[dict]:
    """Reconcile explicit selections only; report bounded owner failures."""
    from .onboarding.service import reconcile

    return reconcile(project_root)


def resume_mcp_installations(project_root: Path) -> list[dict]:
    """Resume interrupted local install intent at deliberate process startup."""
    from .onboarding.service import resume

    return resume(project_root)


def resolve_project_name(
    project_root: Path,
    *,
    workspace_name: str | None = None,
) -> str:
    """Resolve one canonical display name for project-owned consumers.

    In precedence order: an explicit ``project-name`` in the legacy project file,
    the declared ``project.id``, a host-provided workspace name (only a fallback
    for unmanaged repositories, since client labels need not match the provider
    project), the git repository name, then the directory name. Worktree and
    clone directories are arbitrary local names, while the repository name is the
    same in every worktree of it.
    """
    legacy = _legacy_project_config(project_root)
    configured_name = legacy.get("project-name") or legacy.get("project_name")
    if isinstance(configured_name, str) and configured_name.strip():
        return configured_name.strip()
    declared = _declared_project_id(project_root)
    if declared:
        return declared
    if isinstance(workspace_name, str) and workspace_name.strip():
        return workspace_name.strip()
    identity = _git_repository_identity(project_root)
    return identity[0] if identity else project_root.resolve().name


def _legacy_project_config(project_root: Path) -> dict[str, Any]:
    """The legacy ``.audiagentic/config/project.yaml`` mapping, empty when absent or malformed."""
    path = project_root / ".audiagentic" / "config" / "project.yaml"
    data = load_yaml_file(path) if path.is_file() else {}
    return data if isinstance(data, dict) else {}


def project_id(project_root: Path) -> tuple[str, str]:
    """The stable, path-safe project identity and where it came from.

    Unlike the display name, this is the same in every worktree and clone and
    is safe to use in file names (docs/design/configuration-model.md,
    Discovery). Sources, in precedence order: ``settings`` (``project.id`` in
    the resolved settings), ``legacy`` (``project-id`` in
    ``.audiagentic/config/project.yaml``), ``git-remote`` (origin repository
    name), ``main-checkout`` and ``folder``. The last two are provisional.
    """
    declared = _declared_project_id(project_root)
    if declared:
        return declared, "settings"
    legacy = _path_safe_id(str(_legacy_project_config(project_root).get("project-id") or ""))
    if legacy:
        return legacy, "legacy"
    name, source = _git_repository_identity(project_root) or (project_root.resolve().name, "folder")
    return _path_safe_id(name) or "project", source


def _declared_project_id(project_root: Path) -> str | None:
    """``project.id`` from the resolved settings; a root that does not exist has none."""
    if not project_root.is_dir():
        return None
    from audiagentic.foundation.config.settings import resolve_settings_cached

    declared = resolve_settings_cached(project_root).get("project.id")
    return declared if isinstance(declared, str) and declared else None


def git_remote_ids(project_root: Path) -> dict[str, str]:
    """Path-safe repository id per git remote, for spotting ambiguous identity."""
    common = _git_common_dir(project_root)
    if common is None:
        return {}
    ids = {}
    for remote, url in _remote_urls(common / "config").items():
        repo_id = _path_safe_id(_repository_name(url))
        if repo_id:
            ids[remote] = repo_id
    return ids


def _path_safe_id(name: str) -> str | None:
    """Restrict a name to the ``project.id`` schema: [A-Za-z0-9._-], alnum first, 64 chars."""
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).lstrip("._-")[:64].rstrip("._-")
    return candidate or None


def _strip_git_suffix(name: str) -> str:
    return name[: -len(".git")] if name.endswith(".git") else name


def _repository_name(url: str) -> str:
    return _strip_git_suffix(url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])


def _git_common_dir(project_root: Path) -> Path | None:
    """The git common directory of project_root (shared by all its worktrees).

    Reads git's own files rather than running git, so it is cheap and has no
    process or PATH dependency. Any unreadable layout yields None.
    """
    try:
        dot_git = project_root.resolve() / ".git"
        if dot_git.is_dir():
            git_dir = dot_git
        elif dot_git.is_file():
            pointer = dot_git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            git_dir = (project_root.resolve() / pointer[len("gitdir:"):].strip()).resolve()
        else:
            return None
        commondir = git_dir / "commondir"
        return (git_dir / commondir.read_text(encoding="utf-8").strip()).resolve() if commondir.is_file() else git_dir
    except OSError:
        return None


def _git_repository_identity(project_root: Path) -> tuple[str, str] | None:
    """Name the git repository at project_root: origin's repo, else main checkout."""
    common = _git_common_dir(project_root)
    if common is None:
        return None
    try:
        origin = _remote_urls(common / "config").get("origin")
    except OSError:
        return None
    name = _repository_name(origin) if origin else ""
    source = "git-remote"
    if not name:
        name, source = _strip_git_suffix(common.parent.name if common.name == ".git" else common.name), "main-checkout"
    return (name.strip(), source) if name.strip() else None


def _remote_urls(config_path: Path) -> dict[str, str]:
    """``url`` of each ``[remote "name"]`` section in a git config file."""
    if not config_path.is_file():
        return {}
    urls: dict[str, str] = {}
    remote = None
    for raw in config_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("["):
            section = line.strip("[]").strip()
            remote = section[len("remote"):].strip().strip('"') if section.startswith("remote ") else None
        elif remote and line.split("=", 1)[0].strip() == "url" and "=" in line:
            url = line.split("=", 1)[1].strip()
            if url:
                urls.setdefault(remote, url)
    return urls


def context(
    project_root: Path,
    *,
    workspace_name: str | None = None,
) -> dict[str, Any]:
    """Return stable, public project facts for prompt templates."""
    data = _legacy_project_config(project_root)
    return {
        "id": project_id(project_root)[0],
        "name": resolve_project_name(project_root, workspace_name=workspace_name),
        "root": str(project_root.resolve()),
        "workflow_profile": data.get("workflow-profile"),
        "tracked_docs_root": data.get("tracked-docs-root"),
        "release_strategy": data.get("release-strategy"),
    }


def project_status(project_root: Path) -> dict[str, Any]:
    """Return project installation state and component details."""
    return project_components.project_status(project_root)


def list_components(project_root: Path) -> list[dict[str, Any]]:
    """List all known components and current install state."""
    return project_components.list_components(project_root)


def install_component(project_root: Path, component_id: str) -> dict[str, Any]:
    """Install a component and refresh generated harness config when needed."""
    return project_components.install_component(project_root, component_id)


def uninstall_component(
    project_root: Path, component_id: str, *, remove_configs: bool = False
) -> dict[str, Any]:
    """Uninstall a non-core component and refresh generated harness config."""
    return project_components.uninstall_component(
        project_root, component_id, remove_configs=remove_configs
    )


def enable_component(project_root: Path, component_id: str) -> dict[str, Any]:
    """Enable a component and refresh generated harness config."""
    return project_components.enable_component(project_root, component_id)


def disable_component(project_root: Path, component_id: str) -> dict[str, Any]:
    """Disable a component and refresh generated harness config."""
    return project_components.disable_component(project_root, component_id)


def read_project_file(project_root: Path, relative_path: str) -> dict[str, Any]:
    """Read a file under the managed project `.audiagentic` tree."""
    return project_files.read_project_file(project_root, relative_path)


def list_project_instructions(project_root: Path) -> list[dict[str, Any]]:
    return project_surfaces.list_project_instructions(project_root)


def get_project_instruction(project_root: Path, item_id: str) -> dict[str, Any]:
    return project_surfaces.get_project_instruction(project_root, item_id)


def create_project_instruction(
    project_root: Path,
    item_id: str,
    title: str,
    body: str,
    preferred_targets: list[str] | None = None,
) -> dict[str, Any]:
    return project_surfaces.create_project_instruction(
        project_root, item_id, title, body, preferred_targets
    )


def update_project_instruction(
    project_root: Path,
    item_id: str,
    title: str | None = None,
    body: str | None = None,
    preferred_targets: list[str] | None = None,
) -> dict[str, Any]:
    return project_surfaces.update_project_instruction(
        project_root, item_id, title, body, preferred_targets
    )


def delete_project_instruction(project_root: Path, item_id: str) -> dict[str, Any]:
    return project_surfaces.delete_project_instruction(project_root, item_id)


def list_project_skills(project_root: Path) -> list[dict[str, Any]]:
    return project_surfaces.list_project_skills(project_root)


def get_project_skill(project_root: Path, item_id: str) -> dict[str, Any]:
    return project_surfaces.get_project_skill(project_root, item_id)


def create_project_skill(project_root: Path, item_id: str, content: str) -> dict[str, Any]:
    return project_surfaces.create_project_skill(project_root, item_id, content)


def update_project_skill(project_root: Path, item_id: str, content: str) -> dict[str, Any]:
    return project_surfaces.update_project_skill(project_root, item_id, content)


def delete_project_skill(project_root: Path, item_id: str) -> dict[str, Any]:
    return project_surfaces.delete_project_skill(project_root, item_id)


def runtime_sync_contract() -> dict[str, Any]:
    """Describe the runtime-sync contract expected by Pi runtime clients."""
    from audiagentic.foundation.capabilities import get_harness_status

    hs = get_harness_status()
    return {
        "target": "pi-runtime",
        "actions": {
            "refresh_required": "Refresh local client state only.",
            "reload_required": "Reload Pi runtime after request completes.",
            "restart_required": "Prompt for full Pi session restart.",
        },
        "example": hs["build_runtime_sync"](
            reason="component-installed", component_id="providers"
        ),  # cross-component example payload,
    }


def get_option_provenance(
    project_root: Path,
    component_id: str | None = None,
) -> dict[str, Any]:
    """Return option provenance for all features and implementations.

    For each feature/implementation, shows which layer provided each option value.
    Source values: 'schema-default', 'component-state', 'feature-state', 'implementation-state'.

    If component_id is provided, only returns provenance for that component.
    """
    results: dict[str, list[dict[str, Any]]] = {"features": [], "implementations": []}

    for key, descriptor in all_features().items():
        if component_id and descriptor.parent != component_id:
            continue
        if not is_installed(descriptor.parent, project_root):
            continue
        if not is_enabled(descriptor.parent, project_root):
            continue
        resolved = resolve_feature(project_root, descriptor)
        if resolved.option_provenance:
            results["features"].append(
                {
                    "parent": descriptor.parent,
                    "kind": descriptor.kind,
                    "feature_id": descriptor.feature_id,
                    "provenance": {
                        k: {"value": v.value, "source": v.source}
                        for k, v in resolved.option_provenance.items()
                    },
                }
            )

    for key, descriptor in all_implementations().items():
        if component_id and descriptor.parent != component_id:
            continue
        if not is_installed(descriptor.parent, project_root):
            continue
        if not is_enabled(descriptor.parent, project_root):
            continue
        resolved = resolve_implementation(project_root, descriptor)
        if resolved.option_provenance:
            results["implementations"].append(
                {
                    "parent": descriptor.parent,
                    "implementation_id": descriptor.implementation_id,
                    "provenance": {
                        k: {"value": v.value, "source": v.source}
                        for k, v in resolved.option_provenance.items()
                    },
                }
            )

    return results
