# Provider Optimization and Shared Workflow Extensibility Matrix

This matrix records the preferred reuse strategy for the next optimization slice.

The goal is to reduce token usage by moving repetitive file handling, scanning, and summarization into shared tooling where possible.

## Shared rule

The optimization layer should prefer shared, deterministic tooling for:

- large text search
- large text modification
- summarization/extraction
- repeated callout patterns
- template-driven rendering
- scripted consolidation of change fragments and release outputs

Providers may still use prompt text where that is the most stable path, but the shared tools should own the repetitive mechanics.
Agents should supply only the minimum parameters or intent required for the script or template to perform the work.

## Provider methods

### Cline

- Preferred method: wrapper plus shared scan/patch/template helpers.
- Why: Cline already has a strong CLI and live-stream path, so it benefits from delegated file handling.
- Reuse stance: keep prompt text short; let shared tooling handle large file inspection and repeatable rendering.

### Codex

- Preferred method: `AGENTS.md` / skills plus shared scripts and templates.
- Why: Codex already has a reference wrapper path, making it a good anchor for reusable helper calls.
- Reuse stance: use repo-local scripts for search/update/render tasks and keep the agent prompt compact.

### Claude

- Preferred method: repo instructions plus hook/wrapper-backed helpers.
- Why: Claude can benefit from shared helper scripts while keeping instruction surfaces concise.
- Reuse stance: prefer hooks or wrapper commands for mechanical file operations and template rendering.

### Gemini

- Preferred method: wrapper-first with shared scripts and templates.
- Why: Gemini works best with bounded prompts, so script-backed file handling is a natural fit.
- Reuse stance: avoid large inline file dumps where a script can extract or render the needed data.

### Copilot

- Preferred method: instruction files plus shared scripts and templates.
- Why: Copilot already uses repo-local instructions well, so shared helper scripts can keep the prompts shorter.
- Reuse stance: lean on scripts for scans, consolidation, and structured output generation.

### local-openai

- Preferred method: bridge-only plus shared scripts and templates.
- Why: the backend is already direct-response oriented, so the bridge can normalize script output.
- Reuse stance: use the bridge for orchestration and scripts for large-file or repeatable template work.

### Qwen

- Preferred method: bridge-first plus shared scripts and templates.
- Why: Qwen should stay lightweight and use shared tooling for repetitive file tasks.
- Reuse stance: keep prompt text minimal; use scripts for extraction, patching, and renderable outputs.

### Continue

- Future integration only.

## Reuse guidance

To avoid duplication:

- keep the shared helper scripts provider-neutral
- keep provider-specific behavior in the instruction/wrapper layer
- add MCP tools later only where they materially reduce token cost or improve automation
- keep the future workflow/task tracker pluggable instead of hard-wiring it into the first optimization pass

## Status note

This matrix is intentionally conservative. It does not define the final workflow/task tracker system; it only reserves the reuse seam so the system can evolve later without rewriting the prompt contracts.
