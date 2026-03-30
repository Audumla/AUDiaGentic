# gemini Provider Implementation Plan

## Purpose
Implement the `gemini` adapter on top of the frozen provider contract from Phase 4.

## Packet mapping
- primary packet: `PKT-PRV-006` (VERIFIED)
- surface integration packet: `PKT-PRV-017` (IN_PROGRESS)
- dependency packets: `PKT-PRV-001`, `PKT-PRV-002`, `PKT-PRV-014`

## Required capabilities
- load provider config using canonical provider id `gemini`
- implement health check returning `HealthCheckResult`
- implement request normalization and response normalization
- surface provider failure as provider-layer errors, not job-state corruption
- detect canonical prompt tags (@plan, @implement, @review, etc.)
- normalize tagged prompts to `PromptLaunchRequest`
- forward launch requests to the jobs core
- preserve surface (cli/vscode) and session identifiers

## Required implementation notes
- do not add provider-specific tracked doc writers
- do not bypass provider selection rules
- do not change common contracts in this packet
- keep provider-specific auth handling within `env:` policy for MVP
- use `audiagentic.jobs.prompt_parser` for tag recognition
- use `audiagentic.jobs.prompt_launch` for forwarding to core

## Surface Configuration
- CLI mode: `wrapper-normalize`
- VS Code mode: `extension-normalize`
- settings-profile: `gemini-prompt-tags-v1`

## Pseudocode shape
```python
class GeminiAdapter:
    def healthcheck(self, cfg):
        ...

    def execute(self, request, cfg):
        # detect tags in prompt-body
        # if tag:
        #   launch_prompt_request(...)
        #   adjust prompt for provider
        ...
```

## Acceptance
- adapter is selectable through provider registry
- adapter passes health check tests
- adapter returns normalized response shape
