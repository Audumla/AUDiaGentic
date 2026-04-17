# Component and Package Manifest

## Purpose

This document defines the release artifact manifest and managed-file ownership metadata used by install, update, cutover, and uninstall.

## Release artifact manifest

```json
{
  "contract-version": "v1",
  "bundle-version": "0.1.0",
  "components": {
    "core-lifecycle": {"version": "0.1.0", "requires": []},
    "release-audit-ledger": {"version": "0.1.0", "requires": ["core-lifecycle"]},
    "agent-jobs": {"version": "0.1.0", "requires": ["core-lifecycle", "release-audit-ledger", "provider-layer"]},
    "provider-layer": {"version": "0.1.0", "requires": ["core-lifecycle"]},
    "discord-overlay": {"version": "0.1.0", "requires": ["core-lifecycle"]},
    "optional-server": {"version": "0.1.0", "requires": ["core-lifecycle"]}
  },
  "providers": {
    "local-openai": {"version": "0.1.0"},
    "claude": {"version": "0.1.0"},
    "codex": {"version": "0.1.0"},
    "gemini": {"version": "0.1.0"},
    "copilot": {"version": "0.1.0"},
    "continue": {"version": "0.1.0"},
    "cline": {"version": "0.1.0"}
  }
}
```

## Managed file registry

All managed tracked files must be listed in one registry.

Example managed entries:
- `.github/workflows/release-please.yml` owned by `release-audit-ledger`
- `docs/releases/CHANGELOG.md` written by `sync-current-release-summary` and `finalize-release`

Conflict policy:
- managed-unmodified: may be updated automatically
- managed-modified: must not be overwritten silently
- external-unknown: preserve and warn
- legacy-detected: preserve by rename and warn
