#!/usr/bin/env python3
"""AUDiaGentic knowledge MCP server — FastMCP stdio transport.

Single entry point for all MCP clients (Claude Code, OpenCode, Codex, Cline, etc.).
Uses FastMCP standard stdio transport — no custom framing required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Root Discovery — robust, env-var-first, .audiagentic/ marker
# ---------------------------------------------------------------------------


def _find_root_via_env() -> Path | None:
    """Get root from AUDIAGENTIC_ROOT env var if set."""
    if os.environ.get("AUDIAGENTIC_ROOT"):
        return Path(os.environ["AUDIAGENTIC_ROOT"]).resolve()
    return None


def _find_root_via_marker() -> Path:
    """Find root by walking up from current dir looking for .audiagentic/."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".audiagentic").exists():
            return parent
    # Fallback to cwd
    return current


# ---------------------------------------------------------------------------
# Bootstrap and imports
# ---------------------------------------------------------------------------

# Bootstrap root discovery FIRST (before imports)
_BOOTSTRAP_ROOT = _find_root_via_env() or _find_root_via_marker()
for _p in (str(_BOOTSTRAP_ROOT), str(_BOOTSTRAP_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import after path is set
from audiagentic.knowledge.actions import execute_deterministic_action
from audiagentic.knowledge.config import load_config
from audiagentic.knowledge.capability import doctor, show_capability_contract, show_install_profiles
from audiagentic.knowledge.events import process_events, record_event_baseline, scan_events
from audiagentic.knowledge.importers import scaffold_page, seed_from_manifest
from audiagentic.knowledge.llm import (
    answer_question,
    bootstrap_project_knowledge,
    draft_sync_proposal,
    get_job_result,
    get_job_status,
    list_profiles,
    show_execution_registry,
    submit_profile_job,
)
from audiagentic.knowledge.markdown_io import load_page_by_id
from audiagentic.knowledge.navigation import explain_navigation_contract, suggest_navigation
from audiagentic.knowledge.registry import (
    load_action_registry,
    load_importer_registry,
    load_llm_provider_registry,
    load_execution_registry,
)
from audiagentic.knowledge.search import search_pages
from audiagentic.knowledge.status import build_status
from audiagentic.knowledge.sync import generate_sync_proposals, scan_drift
from audiagentic.knowledge.validation import validate_vault

from dataclasses import asdict

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "audiagentic-knowledge",
    instructions="""
Knowledge vault operations for AUDiaGentic project.

READ COST LADDER:
  - knowledge.get_page: Get a page with sidecar metadata and sections
  - knowledge.search_pages: Lexical search over pages
  - knowledge.answer_question: Deterministic-first QA with optional LLM
  - knowledge.navigate: Suggest navigation paths for goals

MUTATIONS:
  - knowledge.scaffold_page: Create new page scaffold
  - knowledge.seed_from_manifest: Import from manifest
  - knowledge.run_action: Execute deterministic fallback action
  - knowledge.submit_profile_job: Submit task to optional provider layer

STATUS & VALIDATION:
  - knowledge.status: Vault status
  - knowledge.validate: Validate vault
  - knowledge.doctor: Check against capability contract
  - knowledge.scan_drift: Scan source drift
""",
)


# ---------------------------------------------------------------------------
# 1. PAGE OPERATIONS
# ---------------------------------------------------------------------------


@mcp.tool(description="Return a page with sidecar metadata and sections.")
def knowledge_get_page(page_id: str) -> dict[str, Any]:
    """Get a knowledge page by ID."""
    config = load_config(Path.cwd().resolve())
    page = load_page_by_id(config.pages_root, config.meta_root, page_id)
    if page is None:
        raise ValueError(f"Page not found: {page_id}")
    return {
        "page_id": page.page_id,
        "title": page.title,
        "type": page.page_type,
        "metadata": page.metadata,
        "path": str(page.content_path.relative_to(config.root)),
        "sections": [{"title": s.title, "body": s.body} for s in page.sections],
    }


@mcp.tool(description="Search pages lexically.")
def knowledge_search_pages(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search pages by query."""
    config = load_config(Path.cwd().resolve())
    return [asdict(item) for item in search_pages(config, query, limit)]


# ---------------------------------------------------------------------------
# 2. QUESTION ANSWERING
# ---------------------------------------------------------------------------


@mcp.tool(
    description="Deterministic-first question answering over knowledge pages with optional model assistance."
)
def knowledge_answer_question(
    question: str,
    limit: int = 8,
    allow_llm: bool = False,
    mode: str = "deterministic",
) -> Any:
    """Answer questions over knowledge base."""
    config = load_config(Path.cwd().resolve())
    return answer_question(config, question, limit=limit, allow_llm=allow_llm, mode=mode)


# ---------------------------------------------------------------------------
# 3. SYNC OPERATIONS
# ---------------------------------------------------------------------------


@mcp.tool(description="Create a deterministic or optional-provider sync proposal response.")
def knowledge_draft_sync_proposal(
    page_id: str,
    allow_llm: bool = False,
    mode: str = "deterministic",
) -> Any:
    """Draft sync proposal for a page."""
    config = load_config(Path.cwd().resolve())
    return draft_sync_proposal(config, page_id=page_id, allow_llm=allow_llm, mode=mode)


@mcp.tool(
    description="Build a deterministic seed inventory and investigation bundle for project knowledge."
)
def knowledge_bootstrap_project_knowledge(
    manifest: str | None = None,
    allow_llm: bool = False,
    mode: str = "deterministic",
) -> Any:
    """Bootstrap project knowledge."""
    config = load_config(Path.cwd().resolve())
    return bootstrap_project_knowledge(config, manifest=manifest, allow_llm=allow_llm, mode=mode)


@mcp.tool(description="Scan source drift.")
def knowledge_scan_drift() -> list[dict[str, Any]]:
    """Scan for source drift."""
    config = load_config(Path.cwd().resolve())
    return [asdict(item) for item in scan_drift(config)]


@mcp.tool(description="Generate sync-review proposals.")
def knowledge_generate_sync_proposals() -> list[str]:
    """Generate sync proposals."""
    config = load_config(Path.cwd().resolve())
    return [str(path.relative_to(config.root)) for path in generate_sync_proposals(config)]


# ---------------------------------------------------------------------------
# 4. PROFILE & JOB OPERATIONS
# ---------------------------------------------------------------------------


@mcp.tool(description="List configured optional-provider capability profiles.")
def knowledge_list_profiles() -> Any:
    """List profiles."""
    config = load_config(Path.cwd().resolve())
    return list_profiles(config)


@mcp.tool(description="Submit a task to the optional model provider layer.")
def knowledge_submit_profile_job(
    task_name: str,
    payload: dict[str, Any] | None = None,
    mode: str = "async",
    allow_llm: bool = False,
) -> Any:
    """Submit profile job."""
    config = load_config(Path.cwd().resolve())
    return submit_profile_job(
        config, task_name, dict(payload or {}), mode=mode, allow_llm=allow_llm
    )


@mcp.tool(description="Return queued job status.")
def knowledge_get_job_status(job_id: str) -> Any:
    """Get job status."""
    config = load_config(Path.cwd().resolve())
    return get_job_status(config, job_id)


@mcp.tool(description="Return queued job result.")
def knowledge_get_job_result(job_id: str) -> Any:
    """Get job result."""
    config = load_config(Path.cwd().resolve())
    return get_job_result(config, job_id)


# ---------------------------------------------------------------------------
# 5. REGISTRY & CONTRACT OPERATIONS
# ---------------------------------------------------------------------------


@mcp.tool(description="Show the config-driven high-level task registry.")
def knowledge_show_execution_registry() -> Any:
    """Show execution registry."""
    config = load_config(Path.cwd().resolve())
    return show_execution_registry(config)


@mcp.tool(description="Show runtime-owned capability and host profiles.")
def knowledge_show_install_profiles() -> Any:
    """Show install profiles."""
    return show_install_profiles()


@mcp.tool(description="Show the capability runtime/project ownership contract.")
def knowledge_show_capability_contract() -> Any:
    """Show capability contract."""
    config = load_config(Path.cwd().resolve())
    return show_capability_contract(config)


@mcp.tool(description="Check the project against the knowledge capability contract.")
def knowledge_doctor() -> Any:
    """Run doctor check."""
    config = load_config(Path.cwd().resolve())
    return doctor(config)


@mcp.tool(description="Suggest navigation and deterministic fallbacks for a goal.")
def knowledge_navigate(goal: str, limit: int = 5) -> Any:
    """Suggest navigation."""
    config = load_config(Path.cwd().resolve())
    return suggest_navigation(config, goal, limit=limit)


@mcp.tool(description="Explain navigation config and registered fallback actions.")
def knowledge_show_navigation_contract() -> Any:
    """Show navigation contract."""
    config = load_config(Path.cwd().resolve())
    return explain_navigation_contract(config)


@mcp.tool(description="List deterministic fallback actions.")
def knowledge_list_actions() -> list[str]:
    """List actions."""
    config = load_config(Path.cwd().resolve())
    return sorted(load_action_registry(config).keys())


@mcp.tool(description="Run a deterministic fallback action.")
def knowledge_run_action(action_id: str, arguments: dict[str, Any] | None = None) -> Any:
    """Run action."""
    config = load_config(Path.cwd().resolve())
    return execute_deterministic_action(
        config, load_action_registry(config), action_id, dict(arguments or {})
    )


@mcp.tool(description="Show importer strategies.")
def knowledge_show_importer_registry() -> Any:
    """Show importer registry."""
    config = load_config(Path.cwd().resolve())
    return load_importer_registry(config)


@mcp.tool(description="Show model provider and task policy registry configuration.")
def knowledge_show_llm_registry() -> dict[str, Any]:
    """Show LLM registry."""
    config = load_config(Path.cwd().resolve())
    return {"providers": load_llm_provider_registry(config)}


# ---------------------------------------------------------------------------
# 6. VALIDATION & STATUS
# ---------------------------------------------------------------------------


@mcp.tool(description="Validate the vault.")
def knowledge_validate() -> list[dict[str, Any]]:
    """Validate vault."""
    config = load_config(Path.cwd().resolve())
    return [asdict(item) for item in validate_vault(config)]


@mcp.tool(description="Return vault status.")
def knowledge_status() -> Any:
    """Get vault status."""
    config = load_config(Path.cwd().resolve())
    return build_status(config)


# ---------------------------------------------------------------------------
# 7. IMPORT & SCAFFOLD
# ---------------------------------------------------------------------------


@mcp.tool(description="Seed pages from an import manifest.")
def knowledge_seed_from_manifest(
    manifest_path: str,
    record_sync: bool = False,
    update_existing: bool = False,
) -> list[dict[str, Any]]:
    """Seed from manifest."""
    config = load_config(Path.cwd().resolve())
    return [
        asdict(item)
        for item in seed_from_manifest(
            config,
            (config.root / manifest_path).resolve(),
            record_sync=record_sync,
            update_existing=update_existing,
        )
    ]


@mcp.tool(description="Create a scaffold page.")
def knowledge_scaffold_page(
    page_id: str,
    title: str,
    page_type: str,
    summary: str,
    owners: list[str],
    tags: list[str] | None = None,
    related: list[str] | None = None,
    source_refs: list[str] | None = None,
    update_existing: bool = False,
) -> dict[str, Any]:
    """Scaffold a page."""
    config = load_config(Path.cwd().resolve())
    return asdict(
        scaffold_page(
            config,
            page_id=page_id,
            title=title,
            page_type=page_type,
            summary=summary,
            owners=[str(x) for x in owners],
            tags=[str(x) for x in (tags or [])],
            related=[str(x) for x in (related or [])],
            source_refs=list(source_refs or []),
            update_existing=update_existing,
        )
    )


# ---------------------------------------------------------------------------
# 8. EVENTS
# ---------------------------------------------------------------------------


@mcp.tool(description="Scan planning/runtime event adapters.")
def knowledge_scan_events() -> list[dict[str, Any]]:
    """Scan events."""
    config = load_config(Path.cwd().resolve())
    return [asdict(item) for item in scan_events(config)]


@mcp.tool(description="Process planning/runtime events.")
def knowledge_process_events() -> Any:
    """Process events."""
    config = load_config(Path.cwd().resolve())
    return process_events(config)


@mcp.tool(description="Record current event baselines.")
def knowledge_record_event_baseline() -> Any:
    """Record baseline."""
    config = load_config(Path.cwd().resolve())
    return record_event_baseline(config)


if __name__ == "__main__":
    try:
        mcp.run()
    except Exception as exc:
        print(f"Fatal MCP startup error: {exc}", file=sys.stderr)
        raise
