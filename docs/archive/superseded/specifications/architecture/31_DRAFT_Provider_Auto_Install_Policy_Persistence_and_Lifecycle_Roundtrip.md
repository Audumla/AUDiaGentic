# Draft Provider Auto-Install Policy Persistence and Lifecycle Roundtrip

Status: draft
Phase relationship: Phase 1.3 follow-on to Phase 4.7

## Purpose

This note defines how the lifecycle layer preserves provider auto-install policy fields
without changing lifecycle semantics.

Phase 4.7 introduces new optional install/bootstrap policy fields for providers and/or
project-local configuration. Phase 1.3 ensures those fields survive install, update,
cutover, uninstall, and migration reporting flows.

## Scope

The lifecycle layer must round-trip the following fields wherever they are persisted:
- `install-mode`
- `install-policy.on-missing`
- `install-policy.requires-confirmation`
- `install-command`
- `install-check`
- `install-source`
- `post-install-command`

These fields may live in either `.audiagentic/providers.yaml` or `.audiagentic/project.yaml`,
depending on the final Phase 4.7 schema choice.

## Required behavior

- install/update/cutover/uninstall must preserve provider install-policy fields unchanged
- lifecycle validators must reject malformed policy fields, but may not drop valid ones
- installed-state records must retain enough information to detect whether provider
  availability/bootstrap behavior was configured at the time of install
- migration and cutover reports should summarize these fields at a stable level if they are
  user-visible in the tracked config

## Non-goals

- implementing auto-install behavior itself
- changing provider execution or prompt-trigger behavior
- redefining the provider configuration schema
- changing lifecycle command semantics
