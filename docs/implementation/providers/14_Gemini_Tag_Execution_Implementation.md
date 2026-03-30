# Gemini tag execution implementation

Provider: Gemini CLI + Gemini Code Assist / VS Code integration  
Compliance level: A — native intercept candidate (guarded rollout)  
Execution state: IN_PROGRESS (PKT-PRV-025)
Phase: 4.4
Owner: Gemini CLI
Worktree: workspace

## Confirmation summary

Gemini CLI exposes:
- project guidance via `GEMINI.md`
- configurable hooks including `BeforeAgent`
- settings in `settings.json`
- command surfaces and agent/skill-oriented configuration
- IDE integration documentation

This is sufficient to implement a hook-capable rollout, but the first implementation pass
should still keep a wrapper fallback until the local hook behavior is validated in the
target Gemini environment.

Current repo state:
- `GEMINI.md`
- `tools/gemini_prompt_trigger_bridge.py`
- shared bridge harness in `src/audiagentic/jobs/prompt_trigger_bridge.py`

## Related docs

- `docs/specifications/architecture/28_Provider_Tag_Execution_Compliance_Model.md`
- `docs/implementation/providers/11_Provider_Tag_Execution_Conformance_Matrix.md`
- `docs/implementation/providers/21_Gemini_Prompt_Trigger_Runbook.md`

## Native assets to use

### Project guidance
Use:
- `GEMINI.md`

Purpose:
- freeze canonical tag semantics
- define workflow launch behavior
- define review structure
- define tracked-doc restrictions

### Commands / reusable surfaces
Create provider-native reusable commands or command-like surfaces for:
- plan
- implement
- review
- audit
- check-in-prep
- optional adhoc

### Hooks
Required:
- `BeforeAgent`

Recommended:
- `BeforeToolSelection`
- `BeforeTool`
- `AfterAgent`

## Hook implementation strategy

### BeforeAgent
Responsibilities:
- detect first-line canonical tags
- create normalized request metadata
- inject canonical execution context before the agent loop starts

### BeforeToolSelection
Responsibilities:
- narrow allowed tool set based on tag/mode
- enforce review-mode restrictions

### BeforeTool
Responsibilities:
- validate dangerous tool calls against the normalized execution mode

## CLI path

1. user submits raw prompt
2. `gemini` adapter detects canonical tag using `prompt_parser.py`
3. adapter calls `launch_prompt_request` to register job in AUDiaGentic
4. adapter removes tag line and passes prompt body to the Gemini CLI
5. `BeforeAgent` hook in Gemini CLI detects the tag (if running natively) or the adapter handles the redirection.

## VS Code path

The same `gemini` adapter is used by the VS Code surface to ensure consistent tag handling.

## Known limitations

- **Test execution blocked:** During initial implementation, the `run_shell_command` tool was unavailable in the agent environment, preventing actual execution of `pytest` or live Gemini CLI smoke tests.
- **Hook automation:** The `BeforeAgent` hook logic is currently implemented in the `gemini` provider adapter (`gemini.py`) as a `wrapper-normalize` bridge. Full native-intercept within the Gemini CLI itself remains an environment-dependent hardening step, so the wrapper must stay available even when hooks are enabled.

## Smoke-test results (simulated)

### ST-01 plan launch
Input: `@plan target=packet:PKT-JOB-008\nContinue implementing the packet.`
Expected Result: Job created in `.audiagentic/runtime/jobs/`, prompt body without tag passed to gemini.
Actual Status: Implemented in `gemini.py` adapter logic.

### ST-02 implementation launch
Input: `@implement target=packet:PKT-JOB-008\nDo the work.`
Expected Result: Job created, implement task passed to gemini.
Actual Status: Implemented.

### ST-03 review launch
Input: `@review target=artifact:docs/specifications/...\nReview this.`
Expected Result: Review artifacts created in AUDiaGentic.
Actual Status: Implemented through `launch_prompt_request`.




