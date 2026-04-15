---
id: standard-0008
label: Python implementation standard
state: ready
summary: Default standard for Python implementation work in AUDiaGentic-based projects,
  covering code quality, tests, change boundaries, and MCP server development.
---

# Standard

Default standard for Python implementation work in AUDiaGentic-based projects. Covers code quality, module boundaries, test expectations, change scope, and MCP server structure and deployment.

# Source Basis

This standard is derived from the repository's existing Python code style and test expectations, MCP implementation patterns, and the official MCP protocol specification.

Sources:
- current repository Python modules and tests
- repository validation and review expectations
- [Model Context Protocol Specification (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Best Practices Guide](https://modelcontextprotocol.info/docs/best-practices/)
- [Official MCP Build Guide](https://modelcontextprotocol.io/docs/develop/build-server)

# Requirements

## General Python

1. Python changes must preserve existing module boundaries and avoid unnecessary rewrites.
2. New behavior should be added in the smallest coherent seam that matches the current architecture.
3. Public or tool-facing behavior changes should include focused tests where practical.
4. Error handling should fail clearly and specifically rather than hiding important problems.
   - Use custom exception classes (inherit from `Exception`) with actionable error messages.
   - Include relevant context in exceptions (what operation failed, why, suggested recovery).
   - Avoid bare `except:` or `except Exception:` unless truly handling all cases; catch specific exceptions.
5. Optional configuration should remain optional in runtime behavior and validation unless the spec explicitly changes that contract.
6. Helper layers and wrappers must stay aligned with the underlying API signatures they expose.
7. Changes must not silently broaden scope into unrelated runtime, lifecycle, or provider behavior.
8. Tests and verification should be proportional to risk, with direct coverage for regressions being fixed.
9. Production code must not reference or depend on development infrastructure, planning system internals, or machine-local paths. Keep project source separate from tooling/orchestration state.
10. Type hints are required for public APIs and function parameters; use `pyright --pythonversion 3.10` or `mypy` to verify. Type annotations enable schema generation and catch errors early.
11. Async functions must use `async def` and `await` consistently; avoid mixing sync and async without clear boundaries. Document which functions are async-only in module docstrings.
12. Logging must use the standard `logging` module, not print statements for diagnostic output. Import as `import logging; logger = logging.getLogger(__name__)` at module level.

## MCP Server Development

1. All MCP servers must use a supported transport framework (stdio, SSE, or configured transport) unless explicitly justified in the specification.

2. Server location must follow the primary pattern:
    - **`tools/mcp/{server-name}/`** — default for all standalone MCP servers (single domain, separate lifecycle, optional deployment)
    - **`src/{package}/mcp_server.{ext}`** — only if the server is tightly coupled to the package runtime, imported by other code, or not independently launchable

    Default to `tools/mcp/` unless there is a clear reason the server must live in the package.

3. Each MCP server must have a single, clear purpose. Multi-domain servers must be explicitly justified in their specification.

4. Root discovery and project location detection must use a consistent shared pattern:
    - Check `AUDIAGENTIC_ROOT` environment variable first
    - Walk up the directory tree from current working directory looking for `.audiagentic/` marker
    - Fall back to current working directory as final resort
    - Bootstrap root discovery before importing domain modules so paths are available for all downstream imports
    - Extract to a shared module if the pattern is used across multiple servers

5. Optional component installation must be handled gracefully:
    - Servers must document required vs optional dependencies
    - Missing optional dependencies must fail with clear, actionable error messages that suggest installation steps
    - Optional imports must not block server startup unless their feature is explicitly requested

6. Tool registration must follow the framework's decorator or registration pattern:
    - Include description/summary parameters for protocol documentation
    - Include type hints for automatic parameter schema generation
    - Document parameter purposes in docstrings
    - Validate inputs at operation boundaries (user input, external APIs), not within domain logic

7. Server instructions must be defined in the framework constructor and must document:
    - Read operations organized by cost tier (cheapest to most expensive)
    - Mutations grouped by category
    - Status and validation operations
    - Any authorization or special requirements

8. Tool categorization must follow cost-aware patterns:
    - Read operations ordered by resource cost (lexical search before full-text, scan before retrieval)
    - Mutations grouped by domain
    - Status and validation operations kept separate
    - Cost tier differences documented for agent decision-making

9. MCP error handling must be structured and user-facing:
    - Use custom exception classes with actionable suggestions
    - Return sufficient error context for agent recovery
    - Do not expose internal paths, system details, or infrastructure specifics in error output

10. MCP servers must be compatible with framework 3.0+ features or explicitly document version requirements.

# Default Rules

- Prefer explicit code over clever shortcuts.
- Keep helper functions small and single-purpose where practical.
- Reuse existing managers and app-layer seams instead of introducing parallel abstractions without need.
- Add comments only where the code would otherwise be hard to follow.
- Keep file and function names aligned with repository conventions.
- Place all MCP servers in `tools/mcp/{server-name}/` as standalone tools by default.
- Prefer wrapping existing domain functions with framework decorators over reimplementing logic in the MCP layer.
- Keep MCP validation and error handling lightweight; complex business logic belongs in the domain layer.
- Avoid duplicating root discovery, bootstrap, or configuration loading patterns across servers.

# Verification Expectations

## Test Coverage

- Run the smallest focused tests that exercise the changed behavior.
- Run broader validation when the change affects planning structure or shared configuration.
- Record what was not verified if full coverage was not practical.
- Async functions must be tested with `pytest.mark.asyncio`; use strict mode configuration from `pyproject.toml`.
- Optional dependencies must be tested for both present and missing cases; skip tests gracefully if unavailable.

## Type and Lint Checks

- Run `pyright` with Python 3.10 target (OpenCode LSP configured) to verify type consistency.
- Run `ruff check` to catch style and logical issues (repository already uses ruff).
- Address all type errors and linting issues before merge; undocumented suppressions are not acceptable.

## MCP Server Testing

- All MCP servers must be tested for tool discovery and schema generation using the mcp CLI or test harness.
- Parameter type hints must match intended JSON Schema; document any edge cases.
- Servers in `tools/mcp/` should have a test entry point (e.g., `test_mcp_server.py`).
- Root discovery and bootstrap must be tested across different working directories and environment configurations.

# Non-Goals

- Mandating one formatter or linter policy beyond what the repo already uses.
- Replacing language-specific framework standards in downstream installed projects.
- Forcing every small change to carry broad integration-test coverage.
- Prescribing a single MCP server architecture for all servers in the ecosystem.
- Replacing framework built-in validation or schema generation with custom implementations.
- Defining MCP authorization or authentication policy beyond structure and error conventions.
