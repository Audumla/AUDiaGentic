# qwen

## Purpose

Qwen is treated as a local OpenAI-compatible provider in MVP, typically served through a local gateway.

## Canonical id
- `qwen`

## Install mode
- `external-configured`

## MVP capability expectation
- supports provider descriptor v1
- supports baseline health check
- supports job invocation through provider layer before any optional server work

## Model catalog (Phase 4.1)

Model catalog and selection rules are defined in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`.
Qwen typically uses `access-mode: none` with a `static` or `api` catalog source.

## Required provider-specific decisions before implementation
- auth reference shape
- health check command or request
- default model selection rule
- error translation into common provider result envelope
