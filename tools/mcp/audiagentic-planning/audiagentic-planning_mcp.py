#!/usr/bin/env python3
"""AUDiaGentic planning MCP server.

This overlay extends the planning MCP with documentation surfaces, reference docs,
and structured sidecar support-doc visibility. These documentation surfaces are
queryable through planning MCP in this phase, but they are not promoted to new
first-class planning kinds in the core scan/index/validator model.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

def _bootstrap_repo_root() -> Path:
    """Find a repo root well enough to import the shared planning helper.

    The helper owns canonical project-root detection. This bootstrap only needs
    to locate the repository so `tools.planning.tm_helper` can be imported.
    """
    markers = (
        (".audiagentic", "planning"),
        ("tools", "planning", "tm_helper.py"),
    )
    search_roots = [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents]
    for candidate in search_roots:
        if any((candidate / Path(*marker)).exists() for marker in markers):
            return candidate
    raise RuntimeError(
        f"Could not locate repository root for planning MCP import. "
        f"Searched from cwd={Path.cwd()} and module={Path(__file__).resolve()}"
    )


_BOOTSTRAP_ROOT = _bootstrap_repo_root()
for _p in (str(_BOOTSTRAP_ROOT), str(_BOOTSTRAP_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import anyio
    import mcp.types as types
    from mcp.server.fastmcp import FastMCP
    from mcp.shared.message import SessionMessage
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

import tools.planning.tm_helper as tm

_ROOT = tm._find_project_root()
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

mcp = FastMCP("audiagentic-planning")


def _read_stdio_message() -> tuple[str | None, bool | None]:
    """Read either header-framed or newline-delimited JSON from stdin.

    The installed `mcp` package in this environment uses newline-delimited JSON
    for stdio, while some clients still speak the older Content-Length framing.
    Support both so the planning server can initialize reliably across clients.
    """

    stdin = sys.stdin.buffer
    first_line = stdin.readline()
    if not first_line:
        return None, None

    while first_line in (b"\r\n", b"\n"):
        first_line = stdin.readline()
        if not first_line:
            return None, None

    stripped = first_line.lstrip()
    if stripped.startswith(b"{"):
        return first_line.decode("utf-8", errors="replace").strip(), False

    headers: dict[str, str] = {}
    line = first_line
    while line not in (b"", b"\r\n", b"\n"):
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" not in decoded:
            raise ValueError(f"Invalid MCP header line: {decoded!r}")
        key, value = decoded.split(":", 1)
        headers[key.lower().strip()] = value.strip()
        line = stdin.readline()

    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        raise ValueError("Missing or invalid Content-Length header")

    payload = stdin.read(content_length)
    if len(payload) != content_length:
        raise ValueError(
            f"Incomplete MCP payload: expected {content_length} bytes, got {len(payload)}"
        )
    return payload.decode("utf-8", errors="replace"), True


def _write_stdio_message(payload: str, use_headers: bool) -> None:
    stdout = sys.stdout.buffer
    encoded = payload.encode("utf-8")
    if use_headers:
        stdout.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii"))
        stdout.write(encoded)
    else:
        stdout.write(encoded + b"\n")
    stdout.flush()


@asynccontextmanager
async def _compat_stdio_server():
    """Expose a stdio transport compatible with both MCP framing styles."""

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)
    framing_mode: dict[str, bool] = {"use_headers": True}

    async def stdin_reader() -> None:
        try:
            async with read_stream_writer:
                while True:
                    try:
                        payload, use_headers = await anyio.to_thread.run_sync(_read_stdio_message)
                    except Exception as exc:
                        await read_stream_writer.send(exc)
                        continue

                    if payload is None:
                        break
                    if use_headers is not None:
                        framing_mode["use_headers"] = use_headers

                    try:
                        message = types.JSONRPCMessage.model_validate_json(payload)
                    except Exception as exc:
                        await read_stream_writer.send(exc)
                        continue

                    await read_stream_writer.send(SessionMessage(message))
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async def stdout_writer() -> None:
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    payload = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                    await anyio.to_thread.run_sync(
                        _write_stdio_message,
                        payload,
                        framing_mode["use_headers"],
                    )
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_reader)
        tg.start_soon(stdout_writer)
        yield read_stream, write_stream


async def _run_compat_stdio() -> None:
    async with _compat_stdio_server() as (read_stream, write_stream):
        await mcp._mcp_server.run(
            read_stream,
            write_stream,
            mcp._mcp_server.create_initialization_options(),
        )


@mcp.tool(description="Create a new Request planning document")
def tm_new_request(label: str, summary: str) -> dict[str, Any]:
    return tm.new_request(label, summary)


@mcp.tool(description="Create a new Specification planning document, optionally linking to Requests")
def tm_new_spec(label: str, summary: str, request_refs: list[str] | None = None) -> dict[str, Any]:
    return tm.new_spec(label, summary, request_refs)


@mcp.tool(description="Create a new Plan planning document, optionally linked to a Specification")
def tm_new_plan(label: str, summary: str, spec: str | None = None) -> dict[str, Any]:
    return tm.new_plan(label, summary, spec)


@mcp.tool(description="Create a new Task planning document with spec, optional target packet, parent, and workflow")
def tm_new_task(
    label: str,
    summary: str,
    spec: str,
    domain: str = "core",
    target: str | None = None,
    parent: str | None = None,
    workflow: str | None = None,
) -> dict[str, Any]:
    return tm.new_task(label, summary, spec, domain, target, parent, workflow)


@mcp.tool(description="Create a new WorkPackage planning document linked to a Plan")
def tm_new_wp(
    label: str,
    summary: str,
    plan: str,
    domain: str = "core",
    workflow: str | None = None,
) -> dict[str, Any]:
    return tm.new_wp(label, summary, plan, domain, workflow)


@mcp.tool(description="Create a new Standard planning document")
def tm_new_standard(label: str, summary: str) -> dict[str, Any]:
    return tm.new_standard(label, summary)


@mcp.tool(description="Change the state of a planning item (e.g., ready → in_progress → done)")
def tm_state(id: str, new_state: str) -> dict[str, Any]:
    return tm.state(id, new_state)


@mcp.tool(description="Move a planning item to a different domain (e.g., core → contrib)")
def tm_move(id: str, domain: str) -> dict[str, Any]:
    return tm.move(id, domain)


@mcp.tool(description="Update label, summary, or body text of a planning item")
def tm_update(
    id: str, label: str | None = None, summary: str | None = None, append: str | None = None
) -> dict[str, Any]:
    return tm.update(id, label, summary, append)


@mcp.tool(description="Get the full markdown content of a planning document")
def tm_get_content(id: str) -> str:
    return tm.get_content(id)


@mcp.tool(description="Update content of a planning document (replace, append, or insert at position)")
def tm_update_content(
    id: str,
    content: str,
    mode: str = "replace",
    section: str | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    return tm.update_content(id, content, mode, section, position)


@mcp.tool(description="Create a new planning document of any kind with initial content in one operation")
def tm_create_with_content(
    kind: str,
    label: str,
    summary: str,
    content: str,
    domain: str = "core",
    spec: str | None = None,
    plan: str | None = None,
    parent: str | None = None,
    target: str | None = None,
    workflow: str | None = None,
    request_refs: list[str] | None = None,
) -> dict[str, Any]:
    return tm.create_with_content(
        kind, label, summary, content, domain, spec, plan, parent, target, workflow, request_refs
    )


@mcp.tool(description="Update a link field in a planning item (e.g., add/change spec, parent, or related items)")
def tm_relink(
    src: str, field: str, dst: str, seq: int | None = None, display: str | None = None
) -> dict[str, Any]:
    return tm.relink(src, field, dst, seq, display)


@mcp.tool(description="Group multiple Tasks into a new WorkPackage within a Plan")
def tm_package(plan: str, tasks: list[str], label: str, summary: str, domain: str = "core") -> dict[str, Any]:
    return tm.package(plan, tasks, label, summary, domain)


@mcp.tool(description="List planning items, optionally filtered by kind (request, spec, plan, task, wp, standard)")
def tm_list(kind: str | None = None) -> list[dict[str, Any]]:
    return tm.list_kind(kind)


@mcp.tool(description="Get a full view of a planning item with all metadata and relationships")
def tm_show(id: str) -> dict[str, Any]:
    return tm.show(id)


@mcp.tool(description="Extract a planning item with optional related items and resource references")
def tm_extract(id: str, with_related: bool = False, with_resources: bool = False) -> dict[str, Any]:
    return tm.extract(id, with_related, with_resources)


@mcp.tool(description="List Tasks in a given state (default: ready), optionally filtered by domain")
def tm_next_tasks(state: str = "ready", domain: str | None = None) -> list[dict[str, Any]]:
    return tm.next_tasks(state, domain)


@mcp.tool(description="List items of a given kind in a given state, optionally filtered by domain")
def tm_next_items(kind: str = "task", state: str = "ready", domain: str | None = None) -> list[dict[str, Any]]:
    return tm.next_items(kind, state, domain)


@mcp.tool(description="Get summary counts of all planning items grouped by kind and state")
def tm_status() -> dict[str, Any]:
    return tm.status()


@mcp.tool(description="List applicable standards (e.g., coding styles, docs requirements) for a planning item")
def tm_standards(id: str) -> list[str]:
    return tm.standards(id)


@mcp.tool(description="List all documentation surfaces (generated views of planning items for different audiences)")
def tm_list_doc_surfaces() -> list[dict[str, Any]]:
    return tm.list_doc_surfaces()


@mcp.tool(description="Get a specific documentation surface by ID")
def tm_get_doc_surface(surface_id: str) -> dict[str, Any] | None:
    return tm.get_doc_surface(surface_id)


@mcp.tool(description="List reference documentation that applies to planning items")
def tm_list_reference_docs() -> list[dict[str, str]]:
    return tm.list_reference_docs()


@mcp.tool(description="List available request profiles (templates/configs for creating Requests)")
def tm_list_request_profiles() -> list[dict[str, Any]]:
    return tm.list_request_profiles()


@mcp.tool(description="Get a specific request profile by ID")
def tm_get_request_profile(profile_id: str) -> dict[str, Any] | None:
    return tm.get_request_profile(profile_id)


@mcp.tool(description="List supporting documentation (sidecars) for a planning item or by role")
def tm_list_support_docs(supports_id: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
    return tm.list_support_docs(supports_id, role)


@mcp.tool(description="Get a named section (heading) from a planning document's markdown content")
def tm_get_section(id: str, section: str) -> dict[str, Any]:
    return tm.get_section(id, section)


@mcp.tool(description="Replace the content of a named section in a planning document")
def tm_set_section(id: str, section: str, content: str) -> dict[str, Any]:
    return tm.set_section(id, section, content)


@mcp.tool(description="Append content to a named section in a planning document")
def tm_append_section(id: str, section: str, content: str) -> dict[str, Any]:
    return tm.append_section(id, section, content)


@mcp.tool(description="Get nested subsection content using dot notation (e.g., 'section.subsection')")
def tm_get_subsection(id: str, section_path: str) -> dict[str, Any]:
    return tm.get_subsection(id, section_path)


@mcp.tool(description="Get documentation sync requirements for a planning item kind and profile pack")
def tm_doc_sync_requirements(kind: str, profile_pack: str = "standard") -> dict[str, Any]:
    return tm.get_doc_sync_requirements(kind, profile_pack)


@mcp.tool(description="List pending documentation updates needed for a planning item kind")
def tm_pending_doc_updates(kind: str, profile_pack: str = "standard") -> list[str]:
    return tm.pending_doc_updates(kind, profile_pack)


@mcp.tool(description="Claim ownership of a planning item (prevent concurrent edits) with optional TTL")
def tm_claim(kind: str, id: str, holder: str, ttl: int | None = None) -> dict[str, Any]:
    return tm.claim(kind, id, holder, ttl)


@mcp.tool(description="Release ownership of a planning item (unclaim)")
def tm_unclaim(id: str) -> bool:
    return tm.unclaim(id)


@mcp.tool(description="List active claims on planning items, optionally filtered by kind")
def tm_claims(kind: str | None = None) -> list[dict[str, Any]]:
    return tm.claims(kind)


@mcp.tool(description="Validate all planning documents against schemas and rules; returns list of errors")
def tm_validate() -> list[str]:
    return tm.validate()


@mcp.tool(description="Re-index all planning documents (scan, parse, build indices)")
def tm_index() -> None:
    tm.index()


@mcp.tool(description="Reconcile planning state with filesystem (fix inconsistencies)")
def tm_reconcile() -> dict[str, Any]:
    return tm.reconcile()


@mcp.tool(description="Get recent planning events from the event log")
def tm_events(tail: int = 20) -> list[dict[str, Any]]:
    return tm.events(tail)


@mcp.tool(description="Verify planning module structure is healthy (directories, configs, API)")
def tm_verify_structure() -> dict[str, Any]:
    return tm.verify_structure()


if __name__ == "__main__":
    anyio.run(_run_compat_stdio)
