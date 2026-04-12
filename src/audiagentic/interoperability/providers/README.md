# interoperability/providers/

Provider adapters, health checks, and surfaces for external AI services.

## Purpose

Implements the provider integration pattern:
- Provider-specific adapters (Claude, Gemini, Cline, etc.)
- Model selection and catalog
- Provider health and status
- Provider-specific prompt surfaces and helpers

## Owns

- `adapters/`: Provider-specific runner implementations
- `surfaces/`: Provider prompt surface renderers and skill definitions
- `execution.py`: Generic provider execution wrapper
- `health.py`: Health check logic
- `models.py`: Model selection and resolution
- `selection.py`: Provider selection logic
- `status.py`: Provider status reporting

## Special cross-layer seam

`adapters/gemini.py` imports from `execution.jobs.prompt_launch` and `execution.jobs.prompt_parser`. This is an **intentional one-way dependency** (interoperability → execution) to allow protocol implementations to launch jobs from within provider adapters. This seam is acceptable and documented.

## Must not own

- Job state machine
- Durable persistence
- Runtime lifecycle

## Migration notes

- Moved from `execution/providers/` (2026-04-12)
