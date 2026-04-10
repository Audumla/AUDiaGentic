# qwen Provider Implementation Plan

## Purpose
Support the `qwen` provider id using the same OpenAI-compatible adapter path as `local-openai` in MVP.

## Packet mapping
- primary packet: `PKT-PRV-003` (local-openai adapter)
- dependency packets: `PKT-PRV-001`, `PKT-PRV-002`

## Required capabilities
- load provider config using canonical provider id `qwen`
- reuse OpenAI-compatible request/response normalization
- surface provider failure as provider-layer errors, not job-state corruption

## Required implementation notes
- do not add provider-specific tracked doc writers
- do not bypass provider selection rules
- keep provider-specific auth handling within `env:` policy for MVP

## Acceptance
- qwen is selectable through provider registry
- adapter path is deterministic and testable
