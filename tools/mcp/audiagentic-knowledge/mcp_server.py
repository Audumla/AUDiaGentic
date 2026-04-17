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
from audiagentic.knowledge.models import SearchResult
from audiagentic.knowledge.navigation import explain_navigation_contract, suggest_navigation
from audiagentic.knowledge.registry import (
    load_action_registry,
    load_importer_registry,
    load_llm_provider_registry,
    load_execution_registry,
)
from audiagentic.knowledge.search import search_pages, filter_by_metadata
from audiagentic.knowledge.status import build_status
from audiagentic.knowledge.sync import generate_sync_proposals, scan_drift
from audiagentic.knowledge.validation import validate_vault
from audiagentic.knowledge.index_maintenance import (
    maintain_index_pages,
    validate_index_links,
    refresh_index,
)

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
  - knowledge.search_pages: Text search or metadata filtering (type, tags, owners, id, title)
  - knowledge.answer_question: Deterministic-first QA with optional LLM
  - knowledge.registry(op='navigate', goal='...'): Suggest navigation paths

MUTATIONS:
  - knowledge.scaffold_page: Create new page scaffold
  - knowledge.seed_from_manifest: Import from manifest
  - knowledge.run_action: Execute deterministic fallback action
  - knowledge.submit_profile_job: Submit task to optional provider layer

FLEXIBLE SEARCH:
  - knowledge.search_pages(query='...'): Text search
  - knowledge.search_pages(filters={'type':'task'}): Metadata filter
  - knowledge.search_pages(filters={'tags':['template','example']}): Multiple tags (OR)
  - knowledge.search_pages(query='...', filters={'type':'task'}): Combined search

CONSOLIDATED OPERATIONS:
   - knowledge.registry(op='...'): Registry/config (execution, importer, llm, capability, navigation, actions, profiles, install, doctor, navigate)
   - knowledge.events(op='...'): Event ops (scan, process, baseline)
   - knowledge.job(op='...', job_id='...'): Job ops (status, result)
   - knowledge.validate(op='...'): Validation (validate, status, drift)
   - knowledge.index(op='...'): Index maintenance (maintain, validate, refresh)
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


@mcp.tool(
    description=(
        "Search pages lexically or by metadata filters. "
        "Provide query for text search, or use filters for metadata-based search. "
        "filters: dict with keys like 'type', 'tags', 'owners', 'id', 'title' (supports arrays for multiple values). "
        "Can combine query and filters for refined results."
    )
)
def knowledge_search_pages(
    query: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search pages by query or metadata filters."""
    config = load_config(Path.cwd().resolve())

    # Load all pages for filtering
    from audiagentic.knowledge.markdown_io import load_pages

    pages = load_pages(config.pages_root, config.meta_root)

    # Apply metadata filters first
    if filters:
        pages = filter_by_metadata(pages, filters)

    # Apply text search if query provided
    if query:
        results = search_pages(config, query, limit)
        return [asdict(item) for item in results]

    # Return filtered pages as search results
    if filters:
        # Convert filtered pages to search result format
        results = [
            SearchResult(
                path=str(p.content_path.relative_to(config.root)),
                page_id=p.page_id,
                title=p.title,
                score=1.0,
                snippet="",
                matches=["filtered"],
            )
            for p in pages[:limit]
        ]
        return [asdict(item) for item in results]

    raise ValueError(
        "Either query or filters must be provided. Example: {{query:'task templates'}} or {{filters:{{'type':'task'}}}}"
    )


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


@mcp.tool(
    description=(
        "Job operations. "
        "op: status (get job status) | result (get job result). "
        "Requires job_id parameter."
    )
)
def knowledge_job(op: str, job_id: str) -> Any:
    """Job operations."""
    config = load_config(Path.cwd().resolve())
    valid_ops = {"status", "result"}
    if op not in valid_ops:
        raise ValueError(f"Unknown op: {op!r}. Valid ops: {', '.join(sorted(valid_ops))}")

    if op == "status":
        return get_job_status(config, job_id)
    elif op == "result":
        return get_job_result(config, job_id)


# ---------------------------------------------------------------------------
# 5. REGISTRY & CONTRACT OPERATIONS
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Registry and configuration operations. "
        "op: execution (task registry) | importer (importer strategies) | "
        "llm (model provider registry) | capability (capability contract) | "
        "navigation (navigation contract) | actions (list actions) | "
        "profiles (list profiles) | install (install profiles) | "
        "doctor (check against capability contract) | "
        "navigate (suggest navigation, requires goal param)."
    )
)
def knowledge_registry(
    op: str,
    goal: str | None = None,
    limit: int = 5,
) -> Any:
    """Registry and configuration operations."""
    config = load_config(Path.cwd().resolve())
    valid_ops = {
        "execution",
        "importer",
        "llm",
        "capability",
        "navigation",
        "actions",
        "profiles",
        "install",
        "doctor",
        "navigate",
    }
    if op not in valid_ops:
        raise ValueError(f"Unknown op: {op!r}. Valid ops: {', '.join(sorted(valid_ops))}")

    if op == "execution":
        return show_execution_registry(config)
    elif op == "importer":
        return load_importer_registry(config)
    elif op == "llm":
        return {"providers": load_llm_provider_registry(config)}
    elif op == "capability":
        return show_capability_contract(config)
    elif op == "navigation":
        return explain_navigation_contract(config)
    elif op == "actions":
        return sorted(load_action_registry(config).keys())
    elif op == "profiles":
        return list_profiles(config)
    elif op == "install":
        return show_install_profiles()
    elif op == "doctor":
        return doctor(config)
    elif op == "navigate":
        if not goal:
            raise ValueError(
                "op=navigate requires goal. Example: {{op:'navigate', goal:'find task templates'}}"
            )
        return suggest_navigation(config, goal, limit=limit)


@mcp.tool(description="Run a deterministic fallback action.")
def knowledge_run_action(action_id: str, arguments: dict[str, Any] | None = None) -> Any:
    """Run action."""
    config = load_config(Path.cwd().resolve())
    return execute_deterministic_action(
        config, load_action_registry(config), action_id, dict(arguments or {})
    )


# ---------------------------------------------------------------------------
# 6. VALIDATION & STATUS
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Validation and status operations. "
        "op: validate (validate vault) | status (vault status) | "
        "drift (scan source drift)."
    )
)
def knowledge_validate(op: str = "validate") -> list[dict[str, Any]] | Any:
    """Validation and status operations."""
    config = load_config(Path.cwd().resolve())
    valid_ops = {"validate", "status", "drift"}
    if op not in valid_ops:
        raise ValueError(f"Unknown op: {op!r}. Valid ops: {', '.join(sorted(valid_ops))}")

    if op == "validate":
        return [asdict(item) for item in validate_vault(config)]
    elif op == "status":
        return build_status(config)
    elif op == "drift":
        return [asdict(item) for item in scan_drift(config)]


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


@mcp.tool(
    description=(
        "Event operations. "
        "op: scan (scan event adapters) | process (process events) | "
        "baseline (record event baselines)."
    )
)
def knowledge_events(op: str) -> Any:
    """Event operations."""
    config = load_config(Path.cwd().resolve())
    valid_ops = {"scan", "process", "baseline"}
    if op not in valid_ops:
        raise ValueError(f"Unknown op: {op!r}. Valid ops: {', '.join(sorted(valid_ops))}")

    if op == "scan":
        return [asdict(item) for item in scan_events(config)]
    elif op == "process":
        return process_events(config)
    elif op == "baseline":
        return record_event_baseline(config)


# ---------------------------------------------------------------------------
# 9. INDEX MAINTENANCE
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Index maintenance operations. "
        "op: maintain (update index pages) | validate (check index links) | "
        "refresh (maintain and validate)."
    )
)
def knowledge_index(op: str = "maintain") -> dict[str, Any]:
    """Index maintenance operations."""
    config = load_config(Path.cwd().resolve())
    valid_ops = {"maintain", "validate", "refresh"}
    if op not in valid_ops:
        raise ValueError(f"Unknown op: {op!r}. Valid ops: {', '.join(sorted(valid_ops))}")

    if op == "maintain":
        updated = maintain_index_pages(config)
        return {
            "status": "maintained",
            "updated_files": [str(p.relative_to(config.root)) for p in updated],
        }
    elif op == "validate":
        errors = validate_index_links(config)
        return {
            "status": "valid" if not errors else "invalid",
            "errors": errors,
        }
    elif op == "refresh":
        return refresh_index(config)


if __name__ == "__main__":
    try:
        mcp.run()
    except Exception as exc:
        print(f"Fatal MCP startup error: {exc}", file=sys.stderr)
        raise
