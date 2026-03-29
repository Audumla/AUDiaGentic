# gemini Provider Implementation Plan

## Purpose
Implement the `gemini` adapter on top of the frozen provider contract from Phase 4.

## Packet mapping
- primary packet: `PKT-PRV-006`
- dependency packets: `PKT-PRV-001`, `PKT-PRV-002`

## Required capabilities
- load provider config using canonical provider id `gemini`
- implement health check returning `HealthCheckResult`
- implement request normalization and response normalization
- surface provider failure as provider-layer errors, not job-state corruption

## Required implementation notes
- do not add provider-specific tracked doc writers
- do not bypass provider selection rules
- do not change common contracts in this packet
- keep provider-specific auth handling within `env:` policy for MVP

## Pseudocode shape
```python
class GeminiAdapter:
    def healthcheck(self, cfg):
        ...

    def execute(self, request, cfg):
        ...
```

## Acceptance
- adapter is selectable through provider registry
- adapter passes health check tests
- adapter returns normalized response shape
