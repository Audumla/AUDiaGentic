# AUDiaGentic

Multi-agent workflow orchestration system for AI coding agents. Provides the infrastructure to plan, execute, and track software engineering work across coordinated agent sessions.

## Quick links

- **[docs/layout.md](docs/layout.md)** — directory layout and config hierarchy
- **[docs/planning/](docs/planning/)** — planning system (requests, specs, tasks, plans, work packages)
- **[docs/releases/](docs/releases/)** — current release and audit docs
- **[docs/testing/](docs/testing/)** — test environment and architecture
- **[docs/knowledge/](docs/knowledge/)** — knowledge vault
- **[docs/examples/](docs/examples/)** — example project scaffold
- **[docs/archive/](docs/archive/)** — superseded references

## Source code

| Layer | Path | Contents |
|-------|------|----------|
| Foundation | `src/audiagentic/foundation/` | Contracts, config, events, workflow primitives |
| Runtime | `src/audiagentic/runtime/` | Lifecycle management, state |
| Components | `src/audiagentic/components/optional/` | Providers, coding LSP, ledger, agent jobs, release, source control |

## Docker test path

Use the existing Docker base image as the normal test path. Do not rebuild test images for routine validation unless the image inputs changed.

Normal path:

```bash
docker run --rm \
  -v "${PWD}:/app" \
  -w /app \
  -e AUDIAGENTIC_DOCKER_TESTS=1 \
  -e AUDIAGENTIC_REPO_ROOT=/app \
  audia-test-base:latest \
  bash -lc "python3 -m pip install --no-cache-dir --break-system-packages -e . pytest pytest-asyncio mcp==1.27.0 && pytest tests/integration/release tests/e2e/release -q"
```

Rebuild only when one of these changed:

- `tests/docker/Dockerfile.test-base`
- `tests/docker/Dockerfile.test`
- `tests/docker/Dockerfile.release-test`
- image-level package/tool bootstrap requirements
- the local image is missing or known-bad

Use `tests/docker/Dockerfile.release-test` only when validating the wheel-installed release path or package-data bundling. It is not the default recheck path.

## Testing

- **[docs/testing/TEST_ENVIRONMENT.md](docs/testing/TEST_ENVIRONMENT.md)** — primary test environment guide
- **[docs/testing/TEST_ARCHITECTURE.md](docs/testing/TEST_ARCHITECTURE.md)** — test architecture overview
