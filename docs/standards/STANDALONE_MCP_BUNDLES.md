# Standalone MCP bundles

`tools/extract_mcp.py` generates one independently installable source distribution
per descriptor-declared internal MCP server. Generated copies are build staging,
not a second maintained implementation. Change canonical `src/audiagentic` code
and regenerate. External Git/GitHub/Hindsight MCP servers are not vendored.

## Build and install

The extraction tool needs Python 3.11+ and PyYAML; building also needs `build`.
The generated server packages retain the application's Python 3.10+ requirement.

```powershell
python tools/extract_mcp.py --list
python tools/extract_mcp.py --server ag-planning --output .tmp/mcp-bundles --build
python tools/extract_mcp.py --all --output .tmp/all-mcp-bundles --build
```

Use a fresh output directory. Extraction refuses overwriting an existing bundle.
Each output contains `pyproject.toml`, selected canonical source/resources and
`extraction.json` with the module/file inventory and SHA-256 provenance.
The wheel is in the generated package's `dist/` directory.

Install that wheel into a dedicated virtual environment. The console command is
the declared MCP name, for example `ag-planning`. Configure an MCP client to run
that environment's command with `AUDIAGENTIC_REPO_ROOT` set to the target project.
It serves stdio; no chat UI or interactive AUDiaGentic launcher is started.
The planning server reads/writes the target project's `docs/planning` tree.

**Use one bundle per environment.** These artifacts vendor the same
`audiagentic` namespace and must not be co-installed with one another or with
the full `audiagentic` distribution. They are not separately published plugins.
Optional ACP, A2A and GPT-auto dependencies remain extras, as in the source
project. External backends, credentials and toolchains are not bundled.

## Validate actual wheels

With `uv` available and the MCP SDK installed in the test runner:

```powershell
python tools/test_mcp_bundles.py .tmp/all-mcp-bundles --evidence .tmp/mcp-evidence
```

The runner builds every wheel and installs each into a separate fresh virtual
environment without system site packages. It clears inherited AUDiaGentic and
Python path settings, runs from a temporary project outside the checkout, and
asserts that imports originate in the isolated environment and the full
application distribution is absent. It checks initialization, exact server
identity and descriptor-declared tool availability for every server, rejects
unresolved-import diagnostics, and performs planning CRUD/completion and ledger
record/sync/summary round trips. Projects and mutations are test-only; it does
not submit live GPT requests or change existing gateway/browser sessions.

`results.json` is the compact aggregate. Per-server directories retain wheels,
hashes, virtual environments and diagnostic logs. These generated `.tmp` files
are ignored: do not commit environment files or raw logs.

## Current boundary and limitations

The import closure is deliberately conservative: it includes lazy imports,
package initializers, literal dynamic modules and configured Python references.
Shared component/provider registration currently couples otherwise small tools
to much of the runtime. These are executable independent bundles, **not minimal
planning-only or ledger-only packages**. Their manifests make that cost visible.
An architectural split of shared registration/core services is needed before
claiming truly slim component wheels or safe co-installable plugins.

Protocol success is not complete external-service qualification. Gateway/CDP,
LSP, release publication and provider operations still require their respective
services, configuration and dedicated integration tests. No wheels are published
automatically, and this tooling does not replace the existing application build.
