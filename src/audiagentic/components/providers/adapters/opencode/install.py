"""OpenCode provider config materialization — owns OpenCode's own config shapes.

Moved from runtime/harness/opencode/install/__init__.py as part of HA11: the
runtime should not need a bespoke module per harness type when the provider
already knows its own config shapes and delivery mechanism.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.runtime.harness.paths import _RIG_CONFIG
from audiagentic.runtime.rig.embedded.config import load_rig_model, resolve_profile_definition

logger = logging.getLogger(__name__)


def _build_agents_md(project_root: Path) -> str:
    """Build AGENTS.md from the bundled template + component injections."""
    from audiagentic.runtime.harness.system_prompt import (
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
    from audiagentic.components.providers.adapters.opencode import (
        local_rig_config as _rig,
    )
    from audiagentic.runtime.harness.config import (
        require_harness_provider,
        require_harness_rig_port,
    )

    model_name: str = harness_cfg.get("rig", {}).get("model", "")
    if not model_name:
        raise make_error(
            prefix="CFG",
            component="HCFG",
            number=10,
            kind="harness-config",
            message="No model configured. Set 'model' in ag.yaml.",
            details={"field": "rig.model"},
        )

    model_profile: dict = {}
    if _RIG_CONFIG.exists():
        try:
            profile_name, rig_model_id = load_rig_model(_RIG_CONFIG)
            ref = profile_name if model_name == rig_model_id else model_name
            model_profile = resolve_profile_definition(ref, _RIG_CONFIG)
        except AudiaGenticError:
            logger.warning("could not resolve model profile, using empty", exc_info=True)

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

    # .opencode/config.json — rig provider entry (shape builder lives here).
    provider_cfg = _rig.build_provider_config(
        provider_id=require_harness_provider(harness_cfg),
        rig_port=require_harness_rig_port(harness_cfg),
        api_key=DEFAULT_API_KEY,
        model_name=harness_cfg.get("rig", {}).get("model", "audiagentic-rig"),
        model_profile=model_profile,
    )
    opencode_dir = project_root / ".opencode"
    opencode_dir.mkdir(parents=True, exist_ok=True)
    (opencode_dir / "config.json").write_text(
        json.dumps(provider_cfg, indent=2) + "\n",
        encoding="utf-8",
    )

    print_message(f"Materialized OpenCode config in {project_root}")


# --------------------------------------------------------------------------- #
# Constants and bundled templates
# --------------------------------------------------------------------------- #

_TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_API_KEY = "dummy"
