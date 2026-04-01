# Phase 4.13 — Canonical Prompt Entry and Bridge End State

Status: draft
Phase: 4.13
Feature slot: .13

## Goal

Make the desired end functionality explicit: every supported provider surface that accepts CLI or prompt input must converge on the same repo-owned bridge/launcher contract.

This phase is intentionally documentation-first. It does not change the canonical grammar; it freezes the end-state so provider-specific implementation work can converge on it.

## What this phase leaves behind

- one authoritative end-state spec for canonical prompt entry
- a provider-agnostic statement that all supported providers must use the same workflow grammar
- a clear distinction between shared bridge semantics and provider-specific mechanics
- explicit guidance that provider-specific hooks, wrappers, and instruction files are implementation details only

## Scope

This phase aligns the following docs and trackers to the same end-state:

- `03_Common_Contracts.md`
- `26_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md`
- `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`
- `29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- provider docs and provider rollout matrices
- roadmap, gates, registry, and current-state summaries

## Desired provider behavior

Each supported provider should have a documented entry path that can:

1. accept the canonical workflow tag or provider shorthand
2. normalize the prompt into the repo-owned bridge
3. preserve provenance
4. apply defaults when optional launch fields are omitted
5. hand the request to the shared `PromptLaunchRequest` contract

The user-facing syntax may be short or long form, but the launch contract must remain the same.

## Provider mechanics

Provider mechanics may differ by implementation:

- Codex may use `AGENTS.md` plus the shared Codex bridge
- Claude may use local instruction files and hooks plus the shared bridge fallback
- Gemini may use instruction files or command templates plus the shared bridge fallback
- Cline may use `.clinerules`, hooks, or workflow wrappers plus the shared bridge fallback
- Copilot may use repo instructions or extension surfaces plus the shared bridge fallback
- Continue is intentionally treated as a future integration where not available
- local-openai and qwen may rely on bridge-wrapper behavior when no stronger surface is available

Those differences are allowed. Diverging semantics are not.

## Acceptance expectations

- the end-state is stated in a single authoritative spec
- all provider docs refer back to that spec instead of restating the full grammar
- the build registry and roadmap mark this as a future extension line rather than a baseline rewrite
- the bridge remains the owner of normalization, provenance, and runtime persistence
