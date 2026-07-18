# Validation Methodology

## Evidence preference

1. Runtime probe against a pinned version.
2. Upstream source code or generated schema for that version.
3. Official product/API documentation.
4. Official release notes.
5. Maintainer issue or discussion.
6. Reputable secondary material.
7. Local observation without reproducible probe.

## Validation states

- `verified`: directly supported by primary evidence and, where practical, a probe.
- `documented`: supported by current primary documentation but not locally probed.
- `observed`: seen in local output or help text.
- `expected`: inferred from architecture or compatibility; probe required.
- `unsupported`: evidence says the capability is unavailable.
- `unknown`: insufficient evidence.
- `stale`: evidence no longer matches a current supported version.

## Probe requirements

Every harness should eventually have probes for version, provider projection, config isolation, endpoint qualification, session lifecycle, ACP/MCP support, usage events and failure behavior. Probe outputs should be stored separately from this reference package because they are generated evidence.
