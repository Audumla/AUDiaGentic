"""OpenCode provider config materialization — owns OpenCode's own config shapes.

Moved from runtime/harness/opencode/install/__init__.py as part of HA11: the
runtime should not need a bespoke module per harness type when the provider
already knows its own config shapes and delivery mechanism.
"""

from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


def materialize_model_config_path(project_root: Path, agent_runtime: Path | None) -> Path:
    """OpenCode launches consume the project-local config document."""
    del agent_runtime
    return project_root / ".opencode" / "config.json"


def _build_agents_md(project_root: Path) -> str:
    """Build AGENTS.md from the bundled template + component injections."""
    from audiagentic.foundation.components.prompt_injections import (
        apply_system_prompt_injections,
        build_system_prompt_injections,
    )

    template_path = _TEMPLATES_DIR / "AGENTS.md"
    content = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    injections = build_system_prompt_injections(project_root)
    if injections:
        content = apply_system_prompt_injections(content, injections)
    return content


def materialize_provider_config(
    project_root: Path,
    harness_cfg: dict,
    *,
    agent_runtime: Path | None = None,
) -> None:
    """Write all OpenCode-specific config files.

    Called at install and refresh time. Writes:
      - <project_root>/AGENTS.md             — template + injections + provider surface contributions
      - <project_root>/.opencode/config.json — rig provider entry

    No .mcp.json is written: stock opencode never reads bare .mcp.json, and that
    path collides with Pi's PROVIDER mcp_config target. The AUDiaGentic-curated
    MCP surface for OpenCode is delivered at launch time via OPENCODE_CONFIG_CONTENT
    (see opencode/mcp_surface.py), not a file.

    Args:
        project_root: Project root (all files are written relative to this).
        harness_cfg: Harness config dict (rig.model, rig.port, rig.provider).
    """
    del agent_runtime  # OpenCode's durable config is project-scoped.
    # AGENTS.md — template + injections.
    agents_md = _build_agents_md(project_root)
    if agents_md:
        (project_root / "AGENTS.md").write_text(agents_md, encoding="utf-8")

    # Apply provider surface contributions for OpenCode (managed blocks inside
    # AGENTS.md — apply_managed_blocks only touches its own previously-managed
    # region, so this cannot clobber the template or user-authored content).
    try:
        from audiagentic.components.providers import providers_api

        providers_api.operate_provider_surfaces(project_root, "opencode", mode="apply")
    except AudiaGenticError:
        logger.warning("Failed to apply opencode provider surface contributions", exc_info=True)

    print_message(f"Materialized OpenCode config in {project_root}")


# --------------------------------------------------------------------------- #
# Constants and bundled templates
# --------------------------------------------------------------------------- #

_TEMPLATES_DIR = Path(__file__).parent / "templates"
