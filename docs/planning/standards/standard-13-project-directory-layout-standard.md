---
id: standard-13
label: Project directory layout standard
state: ready
summary: Default directory structure and file organization for AUDiaGentic-based Python
  projects, covering source trees, configuration, tests, tools, and documentation
  layouts.
---







## Standard

Default directory structure for Python projects in the AUDiaGentic ecosystem. Applies to all new projects and significant reorganizations. Ensures consistency across the organization, makes tooling predictable, and aligns code structure with architectural layers.

## Source Basis

This standard is derived from:

- [The Hitchhiker's Guide to Python — Project Structure](https://docs.python-guide.org/writing/structure/)
- [Python Packaging Guide (setuptools)](https://setuptools.pypa.io/en/stable/installation.html)
- Repository existing project patterns (AUDiaGentic, AUDiaLLMGateway, BookReader)
- Standard-0011 (component architecture layers)
- Standard-0008 (Python implementation)

## Requirements

## Root Level Organization

1. **`src/`** — all production Python source code organized by package name. This isolation prevents tests and tools from accidentally importing development code.

2. **`tests/`** — unit and integration tests, organized to mirror `src/` structure. No production dependencies; test code never ships.

3. **`docs/`** — all documentation: architecture, API specs, planning records, standards, user guides. Committed to repo.

4. **`tools/`** — dev tools, scripts, CLI utilities, MCP servers, and automation code that is NOT part of the shipped package. Examples:
   - `tools/mcp/{server-name}/` — standalone MCP servers
   - `tools/scripts/` — build, test, migration scripts
   - `tools/hooks/` — Claude Code hooks, git hooks

5. **`pyproject.toml`** — single source of truth for package metadata, dependencies, build config, tool settings (pytest, ruff, mypy, etc.).

6. **`.gitignore`, `.git/`** — version control root.

7. **`.claude/`** — Claude Code settings, hooks, skills (project-level overrides of user settings). Committed.

8. **README.md** — project summary, quick start, key links. At repository root.

9. **LICENSE** — license text. At repository root.

10. **CHANGELOG.md** or **RELEASES.md** — version history. At repository root.

11. **`config/`** (optional) — default configuration templates, not environment-specific configs. Environment-specific config is external (env vars, mounted volumes, or runtime flags). Schema definitions go here.

## Source Tree (`src/` Organization)

12. **Package root:** `src/{package_name}/` where `{package_name}` matches `pyproject.toml` project name (converted to underscores). Example: `src/audiagentic/`.

13. **Layer modules:** Follow standard-0011 layering. Organize by layer, then by domain:
    ```
    src/audiagentic/
      domain/           # core business logic, data models, rules
        planning/       # planning domain
        knowledge/      # knowledge domain
      application/      # orchestration, use cases, workflows
        planning_app.py
      infrastructure/   # storage, file I/O, external APIs
        file_store.py
      surface/          # MCP tools, CLI, HTTP handlers, entry points
        cli/
        mcp_server.py
      __init__.py
    ```

14. **Private modules:** prefix with `_` or place in `_internal/` subdirectory. Example: `src/audiagentic/_internal/bootstrap.py`.

15. **Shared utilities:** place in `src/{package_name}/shared/` or `src/{package_name}/utils/`. For cross-project reuse, consider a dedicated package.

16. **MCP servers:** place in `tools/mcp/{server-name}/` by default (standard-0008 #2). Never put working MCP servers in `src/` unless tightly coupled to package runtime.

## Tests (`tests/` Organization)

17. **Mirror source structure:** `tests/` mirrors `src/` so imports remain clear.
    ```
    tests/
      domain/
        test_planning.py
      application/
        test_planning_app.py
      infrastructure/
        test_file_store.py
      surface/
        test_mcp_server.py
    ```

18. **Test fixtures:** shared fixtures go in `tests/conftest.py` (pytest auto-discovers). Per-module fixtures go in module-level `conftest.py`.

19. **Integration tests:** `tests/integration/` for tests spanning multiple layers or components. Example: `tests/integration/test_end_to_end_planning.py`.

20. **Test data:** `tests/fixtures/` or `tests/data/` for mock files, JSON, YAML, or test databases. Never use production config files as test data.

## Tools (`tools/` Organization)

21. **MCP servers:** `tools/mcp/{server-name}/` with:
    ```
    tools/mcp/{server-name}/
      {server-name}_mcp.py      # entry point
      test_{server-name}_mcp.py # tests
      README.md                  # server documentation
      requirements.txt           # server-specific deps (if separate)
    ```

22. **Scripts:** `tools/scripts/` for Python, shell, or batch scripts. Group by purpose:
    ```
    tools/scripts/
      build/
        generate_docs.py
      deploy/
        migrate_config.py
      test/
        run_type_check.sh
    ```

23. **Hooks:** `tools/hooks/` for git hooks, Claude Code hooks, CI/CD hooks.

24. **Avoid tool code in `src/`:** tools must never be importable from the main package. They are dev/infrastructure concerns, not production.

## Documentation (`docs/` Organization)

25. **Planning records:** `docs/planning/` for requests, specs, plans, tasks (AUDiaGentic-specific).

26. **Standards:** `docs/planning/standards/` for all standards.

27. **Architecture:** `docs/architecture/` for component diagrams, layer decisions, external service integrations.

28. **API reference:** `docs/api/` for auto-generated or manual API documentation.

29. **User guides:** `docs/guide/` or `docs/user/` for tutorials, walkthroughs, troubleshooting.

30. **Changelogs and release notes:** root level (`CHANGELOG.md`) or `docs/releases/`.

## Configuration

31. **Config schema:** `config/schema.yaml` (or `.json`) documents expected config shape, required fields, defaults.

32. **Default config:** `config/defaults.yaml` provides documented defaults (read-only reference, not loaded at runtime).

33. **Environment-specific config:** NEVER committed. Loaded via:
    - Environment variables (secrets, paths, URLs)
    - Runtime flags (`--config-dir`, `--env production`)
    - Mounted volumes (Kubernetes, Docker)
    - Config server or remote source

34. **Config per component:** if a component has its own config, place schema in `config/{component_name}/` but load it from the environment. Document required vs optional fields in the component's `__init__.py` docstring.

## Special Files at Root

35. **`.claude/`** — checked in; team-level Claude Code settings, hooks, skills.

36. **`.claude/settings.json`** — project hooks, permissions, MCP server enables (team-wide).

37. **`.claude/settings.local.json`** — personal overrides, never committed (add to `.gitignore`).

38. **`CLAUDE.md`** — project-specific instructions for Claude, checked in.

39. **`.gitignore`** — must exclude: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `venv/`, `.env*`, local config, build artifacts.

## Ruff and Type Checker Targets

40. **Ruff and pyright must scan:** `src/` and `tests/`.

41. **Exclude from linting:** `tools/` (unless tool is core infrastructure), `build/`, `dist/`, `*.egg-info/`, `.git/`.

42. **Configure in `pyproject.toml`:**
    ```toml
    [tool.ruff]
    src = ["src", "tests"]
    
    [tool.ruff.lint]
    exclude = ["tools/**", "build/**"]
    
    [tool.pyright]
    include = ["src", "tests"]
    exclude = ["**/node_modules", "tools"]
    ```

# Default Rules

- Do not check in generated code or build artifacts (`dist/`, `build/`, `*.egg-info/`).
- Keep `src/` and `tests/` separate; never import tests from source.
- One package per repository unless explicitly documented as a monorepo.
- README at root; detailed guides in `docs/`.
- Tools are infrastructure, not libraries; never import from `tools/` in `src/`.
- Config files are documentation; never hardcode config fallbacks (standard-0011 #18).

# Verification Expectations

- Structure auditable by `find src tests tools -type d | head -20`.
- Linting (`ruff check src tests`) covers all production and test code.
- Type checking (`pyright --pythonversion 3.10`) covers all production and test code.
- Import isolation testable: `python -c "import src.{package_name}; import tools.something"` fails (tools not importable).
- MCP servers in `tools/mcp/` discoverable by path walk without importing main package.

# Cross-References and Related Standards

**Configuration handling** (standard-0011 rules #12, #17-18): Config must not be hardcoded. This standard defines WHERE config lives on disk; standard-0011 defines HOW it's loaded and passed. Config files go in `config/` or external sources, never in `src/` or `tools/`.

**MCP server placement** (standard-0008 rule #2): MCP servers go in `tools/mcp/{server-name}/` by default. Per this standard, MCP servers are infrastructure tools, not part of the shipped package. Place in `src/` only if tightly coupled to package runtime and imported by other code.

**Component architecture** (standard-0011): Layering (domain, application, infrastructure, surface) is orthogonal to this standard's filesystem layout. Both apply: organize by layer (architectural concern) AND place source in `src/`, tools in `tools/`, tests in `tests/` (filesystem concern).

**Python implementation** (standard-0008): Requires type hints, linting, testing. This standard defines the directories those tools target: `ruff check src/ tests/`, `pyright src/ tests/`.

# Non-Goals

- Mandating a specific build tool (setuptools, poetry, pdm are equivalent if they meet these structure requirements).
- Enforcing file naming conventions beyond Python standard (`test_*.py`, `*_test.py`).
- Prescribing the structure of `docs/` beyond these categories.
- Replacing `pyproject.toml` or `setup.py` conventions; we follow PEP 517/518.
