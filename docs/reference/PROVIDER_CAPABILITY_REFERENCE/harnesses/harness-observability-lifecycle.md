# Harness Observability & Lifecycle Capability Model

Status: architecture reference candidate  
Last updated: 2026-07-18 (RV688 capability/validation/production split)  
Planning items: `AS15..AS26` (agent sessions; AS15 and AS18 completed), `PR05..PR07` (process lifecycle), `SH07` (durable job state, consumes the AS21 projection per RV561)

Declaration home (RV560): harness observability capability declarations live in
**provider descriptors** (`config/providers/*.yaml`) following the MA20
declaration pattern, with probe evidence recorded as MA19 `capability_facts`
(subject: harness observability signals). This document and the profiles under
`harnesses/` are the evidence source used to populate those declarations; they
are never loaded by runtime code and there is no separate runtime harness
registry.

This document defines the AUDiaGentic-owned observability model for coding agent harnesses. It specifies a coarse state model for unambiguous scheduling decisions, fine-grained activity states for diagnostics, an evidence fusion pipeline that normalizes heterogeneous harness signals, and capability levels that gate feature availability.

## Core principle

**AUDiaGentic owns the lifecycle state model. Harnesses provide evidence.** No individual ACP event, hook, plugin event, output marker, or resource heuristic is the state of the agent — each is evidence used to derive an AUDiaGentic-owned state.

Harnesses produce observations through multiple channels:

```
Core architecture
ACP events ───────────────┐
Native RPC events ────────┤
Hooks/plugins ────────────┤
Structured stdout ────────┤
Provider streaming ───────┤──► Harness Observer
Tool/MCP activity ────────┤          │
Process metrics ──────────┤          ▼
Filesystem/log changes ───┘   Evidence Normalizer
                                      │
                                      ▼
                         AUDiaGentic State Machine
                                      │
                     ┌────────────────┼───────────────┐
                     ▼                ▼               ▼
                 Scheduler       Monitoring     Session Reuse
```

The wrapper for each harness declares which evidence sources it can use and how reliable each source is.

## Capability declaration versus production policy

Every harness **surface/mode** records three independent values.  They must
never be collapsed into one O-level:

```yaml
observability:
  declared_capability: O3-candidate  # documented interface and upper bound
  validation_state: probe-required   # exact AUDiaGentic version probe has not passed
  effective_production_level: O0     # only policy the runtime may presently use
```

`declared_capability` is evidence-planning metadata: it identifies a supported
or plausible native route and the probe that can prove it. `validation_state`
is `validated`, `probe-required`, `blocked`, or `unsupported` for a pinned
surface/version. `effective_production_level` is the sole value consumed by
runtime capability resolution, scheduling, status projection, configuration
reconciliation, or control enablement. A documented O2/O3 candidate therefore
remains operationally O0 until its probe passes.

O0 process evidence applies only when AUDiaGentic directly owns or adopts the
process. Remote/cloud services, editor-hosted threads, and externally managed
instances may lack even that evidence. Official hooks, plugins, RPC/API event
streams, structured output, and status APIs are eligible probe sources. UI
scraping, human-oriented terminal parsing, resource inactivity, output silence,
EOF, and final-looking prose are never authoritative terminal evidence.

**Do not directly expose ACP, Claude hook, or OpenCode event names as scheduler state.** Normalize them into AUDiaGentic's own model.

## Canonical entities and correlation

Process, connection, session, turn, model request, tool call, permission request,
subagent, output artifact, and background work are distinct entities. An observation
must attach to the most specific known entity, preserve every harness-native ID, and
must not invent an ID the harness did not expose.

```yaml
correlation:
  harness_instance_id: harness:opencode:host-a:01
  process_instance_id: proc:01J...
  connection_id: conn:01J...
  session_id: ses:01J...
  turn_id: turn:01J...
  native_ids:
    acp_request_id: 42
  quality: exact  # exact | session-scoped | temporal | inferred | absent
```

A session-scoped terminal event is sufficient only when the adapter also proves
that the session permits at most one active turn. Correlation quality is part of
the evidence; it is not an implementation detail.

## Two-tier lifecycle model

The scheduler consumes one mutually exclusive coarse operational state. Detailed
process, session, turn, model, tool, interaction, output, background-work, and
health states remain orthogonal evidence projections for diagnostics and policy.

| Operational state | Meaning | Automatic dispatch |
| --- | --- | ---: |
| `STARTING` | Process, connection, or session is initializing or restoring | No |
| `AVAILABLE` | No turn is active and the target can accept work | Yes, subject to decision flags |
| `ACTIVE` | A correlated turn is in progress | No |
| `WAITING` | A non-terminal turn is blocked on a known condition | No |
| `COMPLETING` | Final output or partial terminal evidence exists, but terminal proof is not accepted | No |
| `STOPPING` | Cancellation or shutdown is in progress | No |
| `STOPPED` | The live target is unavailable; persisted state may remain resumable | No |
| `FAILED` | A terminal error prevents continued use without recovery | No |
| `UNKNOWN` | Evidence is absent, stale, contradictory, or insufficient | No |

Only `AVAILABLE` permits automatic dispatch. Persistent reuse additionally requires
`session_reusable=true`; `UNKNOWN` is always conservative.

Staging note (AS21): the first projector delivery implements the six scheduler
states `ACTIVE / WAITING / COMPLETING / AVAILABLE / FAILED / UNKNOWN`.
`STARTING`, `STOPPING`, and `STOPPED` are already carried by the session store
lifecycle workflow (opening/closing/closed) and are folded into the projector
only if a scheduler decision ever needs them as coarse states — do not build
the nine-state machine up front.

Scheduler code consumes explicit decision flags instead of inferring policy from
state labels:

```yaml
decision:
  accepts_new_turn: false
  session_reusable: false
  session_resumable: true
  turn_terminal: false
  turn_slot_releasable: false
  model_slot_releasable: true
  process_slot_releasable: false
  dependent_work_releasable: false
  human_attention_required: false
```

## Detailed orthogonal state layers

States at each layer are independent. A session can be idle while the process is alive, or a turn can be active while the model is temporarily inactive (waiting for tool approval).

### Process state

| State | Meaning |
| --- | --- |
| starting | Harness process launching |
| ready | Process alive and accepting connections |
| alive | Process running (general) |
| degraded | Process alive but impaired (e.g., slow response, partial functionality) |
| exiting | Graceful shutdown in progress |
| exited | Process terminated |

### Session state

| State | Meaning | Dispatch? | Reuse? |
| --- | --- | ---: | ---: |
| opening | Session being created | No | No |
| ready | Ready to accept turns | Yes | — |
| active | Turn in progress | No | No |
| idle | Turn complete, session reusable | Yes | Yes |
| awaiting_input | Blocked on external dependency | Policy | Policy |
| closing | Session shutting down | No | No |
| closed | Session ended | No | No |
| failed | Terminal failure | No | No |

`session: idle` is detailed evidence, not the scheduler gate by itself. Safe reuse
requires coarse `AVAILABLE`, `session_reusable=true`, trusted correlated terminal
evidence for the previous turn, and no policy-blocking background work.

### Turn state

| State | Meaning |
| --- | --- |
| submitted | Prompt sent to harness |
| accepted | Harness acknowledged the turn |
| queued | Turn waiting in session queue |
| starting | Turn about to execute (turn_lock acquired) |
| active | Turn executing (model or tool work in progress) |
| paused | Turn non-terminal, no active work observed, known wait condition |
| finalizing | Output produced, awaiting terminal confirmation |
| completed | Trusted terminal evidence received |
| failed | Terminal failure during turn |
| cancelled | Turn explicitly cancelled |
| timed_out | Turn exceeded its timeout without completion |

### Activity state (fine-grained)

These are orthogonal indicators of what the harness is currently doing. Multiple can be active simultaneously.

**Model phase:**

| State | Meaning |
| --- | --- |
| preparing | Context assembly, model loading |
| thinking | Direct evidence that a model call or explicit reasoning phase is active; no hidden reasoning content is required or stored |
| streaming | Producing assistant-message text |
| retrying | Retrying a failed call |
| rate_limited | Throttled by provider |
| inactive | No model work occurring |

**Tool lifecycle:**

| State | Meaning |
| --- | --- |
| requested | Tool-call event received |
| awaiting_permission | Permission-request pending |
| executing | Tool is running (bash, file edit, etc.) |
| completed | Tool result received |
| inactive | No tool work occurring |

**Interaction:**

| State | Meaning |
| --- | --- |
| awaiting_user | User input required |
| awaiting_permission | Approval gate active |
| awaiting_external_event | Third-party webhook/callback |
| inactive | No interaction pending |

## State relationships

A reusable persistent harness is the exact condition:

```yaml
process: alive
session: idle
turn: completed
activity:
  model: inactive
  tool: inactive
```

State transitions over a typical turn:

```
session: ready    → session: active       (turn accepted)
turn: starting     (turn_lock acquired)
activity.model: thinking
activity.model: streaming
turn: active

activity.tool: requested
activity.tool: awaiting_permission
session: awaiting_input   (coarse state changes to Waiting)
turn: paused
reason: awaiting_permission

activity.tool: executing
session: active           (back to Active — tool is work)
turn: active

activity.model: streaming
activity.output: candidate
turn: finalizing

activity.model: inactive
turn: completed
session: idle             (reuse allowed)
```

## Critical semantics

### Running prompt

A prompt is running when a correlated turn has been accepted and has not produced a trustworthy terminal outcome:

```
TURN_ACTIVE = turn_accepted AND NOT terminal_completion_evidence
```

It can remain active while the harness is: thinking, streaming, running tools, waiting for tool approval, retrying, waiting on a subagent, or temporarily producing no events.

### Thinking

"Thinking" should only be asserted when there is direct or strongly supported model-phase evidence:

- Provider request started but not completed
- Harness BeforeModel without corresponding AfterModel
- Model stream is active
- Native event indicates reasoning/model processing
- An ACP update explicitly describes model activity

**Do not infer thinking merely because a prompt has not completed.**

```yaml
turn: active
activity:
  model: thinking
confidence: explicit
```

### Pause

A pause is **not** simply "nothing happened recently." It means:

- Turn remains non-terminal
- Active work is not currently observed
- A known wait condition exists

```yaml
turn: paused
reason: awaiting_permission

turn: paused
reason: awaiting_user

turn: paused
reason: retry_backoff

turn: paused
reason: external_tool
```

When no known wait condition exists, use:

```yaml
turn: active
activity_state: unobserved

# or

turn: active
health: possibly_stalled
```

**Do not call it a pause unless you have evidence.**

### Final answer produced

This is distinct from turn completion. A harness may emit assistant text and then: call a tool, revise the answer, run validation, make another model call, append a final summary.

Therefore:

- Assistant output observed ≠ final answer
- Model response completed ≠ turn completed
- Stream stopped ≠ turn completed

Track output lifecycle separately:

```yaml
output:
  - none         # no output produced
  - partial      # streaming in progress
  - candidate    # output available but not confirmed final
  - final        # end_turn or equivalent emitted
  - committed    # result persisted to durable store
```

A candidate becomes final only when the harness or protocol confirms that no further agent-loop activity belongs to that turn.

### Turn finalized

Turn finalization requires **one** of:

1. Correlated protocol terminal response (ACP end_turn)
2. Correlated native `turn.completed` event
3. Harness end-of-agent-loop hook
4. Harness-specific idle event with validated semantics
5. Process exit in one-shot mode

Silence, low CPU, and stdout ending are **not sufficient on their own**.

## Evidence model

Each adapter emits normalized evidence rather than directly mutating scheduler state:

```yaml
evidence:
  event_id: evt-123
  harness: gemini-cli
  process_id: proc-1
  session_id: ses-1
  turn_id: turn-7

  observation: agent_loop_completed
  source:
    kind: hook
    name: AfterAgent

  semantics:
    terminal_for_turn: true
    terminal_for_session: false
    process_alive_expected: true

  reliability:
    semantic_strength: explicit
    verification_tier: execution
    confidence: 0.98

  observed_at: "2026-07-17T15:30:00+09:00"
```

These are two independent axes:

- `semantic_strength` describes what the signal can prove: `definitive`,
  `explicit`, `reliable`, `heuristic`, or `speculative`.
- `verification_tier` reuses the existing `CapabilityEvidence` vocabulary:
  `unverified`, `documentation`, `installed-artifact`, `round-trip`, or
  `execution`.

A protocol-shaped event is not automatically definitive, and a definitive event
documented upstream is not automatically execution-verified in the installed
harness version.

### Evidence precedence

Highest confidence wins. Lower-confidence evidence **cannot** override stronger evidence.

| Priority | Source | Reliability class |
| ---: | --- | --- |
| 1 | Protocol terminal response (ACP end_turn, CLI exit 0) | definitive |
| 2 | Native correlated terminal event (turn.completed) | definitive |
| 3 | End-of-agent hook/plugin event (AfterAgent) | explicit |
| 4 | Validated harness idle transition | explicit |
| 5 | Structured terminal output record | reliable |
| 6 | One-shot process exit | reliable |
| 7 | Polling result | heuristic |
| 8 | Resource/activity heuristic (CPU, GPU, I/O) | speculative |

### Conflicting evidence

When lower-priority evidence contradicts a stronger signal:

```
CPU = 0%
stdout silent for 30 seconds
BUT turn has no terminal response
AND permission request is outstanding

→ Result:
turn: paused
reason: awaiting_permission
```

Not completed. The stronger non-terminal signal (outstanding permission) wins.

## Composite observation

Standalone hooks can be used, but combining them produces much stronger evidence. Each harness maps its specific signals into the AUDiaGentic model:

### Gemini CLI hook mapping

Gemini's documented hook model gives precisely distinct lifecycle points. `AfterAgent` runs after the agent loop completes, while `SessionEnd` applies to the entire session.

```
BeforeAgent     → turn active, session active
BeforeModel     → activity.model: thinking
AfterModel      → activity.model: inactive, turn still active
BeforeTool      → activity.tool: executing
AfterTool       → activity.tool: inactive, turn still active
AfterAgent      → turn completed (strong signal)
SessionEnd      → session closed
```

This allows AUDiaGentic to distinguish: model response finished ≠ agent turn finished ≠ persistent session ended.

### Claude Code hook mapping

```
UserPromptSubmit  → turn submitted
PreToolUse        → activity.tool: requested
PostToolUse       → activity.tool: completed
Stop              → turn completed
SessionEnd        → session closed
```

### OpenCode signal mapping

Combines ACP boundaries with native events:

```
ACP prompt boundary     → turn accepted
session status events   → session state transitions
message-part updates    → activity.model: streaming
tool lifecycle events   → activity.tool transitions
session idle event      → session idle (with validation)
```

**The exact semantics must be validated for each harness version rather than assuming similarly named events mean the same thing.**

## Completion policy

The terminal determination can require agreement or accept the strongest available signal:

```yaml
completion_policy:
  accepted_terminal_sources:
    - acp.prompt.response
    - native.turn.completed
    - hook.AfterAgent

  strategy: first_valid_correlated_terminal

  cross_check:
    wait_for_secondary_signal_ms: 250

  disagreement:
    state: completion_uncertain
    release_session: false
    raise_observability_incident: true
```

This is better than choosing one universal mechanism. The cross-check window catches cases where a harness emits what appears to be a terminal signal but then continues working.

## Resource and concurrency policy

Turn serialization, model capacity, process ownership, and tool execution are
separate resource concerns. A held `turn_lock` proves only serialization; it does
not prove model activity or terminal completion.

| Condition | Turn slot | Model/LLM slot | Process slot |
| --- | ---: | ---: | ---: |
| Waiting for the session `turn_lock` | Retain queue ownership | Release | Retain if process exists |
| Model preparing/thinking/streaming | Retain | Retain | Retain |
| Tool executing with O3 evidence | Retain | Release | Retain |
| Permission or user-input wait with O3 evidence | Retain | Release | Retain |
| Retry backoff with explicit evidence | Retain | Release | Retain |
| `COMPLETING` without terminal proof | Retain | Policy; conservative by default | Retain |
| `AVAILABLE` after trusted completion | Release | Release | Keep-alive policy |
| `UNKNOWN` or event gap | Retain or quarantine | Retain conservatively | Retain pending reconciliation |

AS15 implements the O2 boundary with `pq.running` and `pq.idle`: work waiting on
`turn_lock` does not consume active compute capacity. A future O3 optimization
may add `pq.llm_running` as a distinct projection rather than redefining
`pq.running`, but only after an installed harness proves a controllable
pre-model boundary. Post-facto asynchronous observations cannot guarantee that
capacity was re-acquired before model work resumed. Until that control boundary
is proven, model capacity remains held conservatively.

Background work is also explicit. Turn completion does not imply detached tools,
terminals, child processes, remote jobs, or asynchronous hooks have stopped.
Wrappers declare whether background work blocks reuse, blocks process teardown,
or is intentionally allowed to survive the turn.

## Existing infrastructure alignment

This model is implemented by composing existing project mechanisms:

- `TransitionEngine` loads YAML workflows for coarse lifecycle, turn, model,
  tool, interaction, output, and health transitions. Illegal transitions do not
  silently mutate scheduler state.
- `EventBus` and its topic registry carry normalized observations. Harness-native
  events remain provenance in the evidence envelope rather than becoming public
  scheduler topics.
- `CapabilityEvidence` records verification tier separately from semantic
  strength and confidence.
- Per-resource timeline events persist normalized lifecycle history. O4 requires
  ordered, deduplicated evidence plus replay or deterministic state reconstruction;
  merely writing a timeline event is not sufficient to claim O4.

Observation remains non-controlling through AS18: loss of an observer or a
best-effort timeline write must not alter the underlying turn. Terminal
completion and session reuse require AS21's completion projector. Capacity
optimization is a separate, evidence-gated future item.

## Staged delivery

Each stage must be usable and testable before the next one begins. Later stages
consume the same normalized evidence; they do not require the earlier stage to
implement the whole reference model up front.

| Stage | Plan item | Smallest useful result | Explicitly deferred |
| ---: | --- | --- | --- |
| 1 | AS15 | O2 session-aware `pq.running`/`pq.idle` accounting | Intra-turn phase inference |
| 2 | AS18 | ACP callback publishes a minimal correlated model/tool event slice | Scheduler control, full event taxonomy, completion arbitration |
| 3 | AS19 | Minimal descriptor schema and YAML transitions for the first validated ACP harness | Fleet-wide declarations and speculative capability claims |
| 4 | AS21 | Minimal trusted-terminal projector and scheduler decision flags | Capacity optimization, replay, and broad harness rollout |

Further harness declarations are created as one bounded provider/harness item
per installed-version probe. O3 capacity optimization is created only when a
probe demonstrates a controllable pre-model boundary and an operational need.
O4 replay is created only from evidenced restart-reconstruction requirements;
best-effort timelines alone are not an O4 journal.

The exit rule for every stage is narrow: targeted tests pass, operator-visible
state is understandable, conservative fallback works when evidence is absent,
and the ledger/plan item records exactly what was proven. Avoid expanding a stage
merely because the reference contains a richer eventual model.

## Harness capability schema

Each harness's observability capabilities are declared in its **provider
descriptor** (RV560; see the declaration-home note at the top). The shape below
is the reference vocabulary for that descriptor declaration — it is not a
standalone registry file:

```yaml
harness_observability:
  interfaces:
    acp:
      supported: true
      version: 1
    native_events:
      supported: true
      transport: rpc
    hooks:
      supported: true
      install_scope:
        - project
        - user
    plugins:
      supported: false
    structured_output:
      supported: true
      format: jsonl

  correlation:
    process_id: native
    session_id: native
    turn_id: native
    model_request_id: derived
    tool_call_id: native

  signals:
    turn:
      accepted:
        sources:
          - acp.request.accepted
      started:
        sources:
          - hook.BeforeAgent
      completed:
        sources:
          - acp.prompt.response
          - hook.AfterAgent
        fusion: any_strong
        reliability: protocol
    model:
      started:
        sources:
          - hook.BeforeModel
      completed:
        sources:
          - hook.AfterModel
    tool:
      started:
        sources:
          - hook.BeforeTool
          - acp.tool_call.started
      completed:
        sources:
          - hook.AfterTool
          - acp.tool_call.completed
    interaction:
      awaiting_permission:
        sources:
          - acp.permission.request
          - native.permission.required

  derived_states:
    pause_detection:
      supported: true
      known_reasons:
        - permission
        - user_input
        - retry_backoff
        - external_tool
    stall_detection:
      supported: heuristic
      timeout_seconds: 120

  guarantees:
    explicit_turn_completion: true
    session_reusable_after_turn: true
    background_work_finished_on_completion: unknown
    events_ordered_per_turn: true
    events_replayable: false
```

## Capability levels

| Level | Name | What it provides | Turn completion | Session reuse |
| ---: | --- | --- | --- | --- |
| O0 | Process only | PID liveness, exit code | Process exit only | Unsafe |
| O1 | Heuristic | Output silence, polling, resource activity | Inferred from heuristics | Restricted |
| O2 | Explicit turn boundary | Correlated completion signal (end_turn, AfterAgent) | Explicit | Allowed |
| O3 | Phase observable | Distinguishes model, tool, permission, output phases | Explicit + phase-aware | Allowed, capacity optimization |
| O4 | Fully correlated and recoverable | Ordered events, replay or state reconstruction | Deterministic | Safe with crash recovery |

## Feature gating by capability level

```yaml
feature_requirements:
  reusable_persistent_sessions:
    minimum_observability: O2

  automatic_dependent_dispatch:
    minimum_observability: O2

  mark_work_item_complete:
    minimum_observability: O2

  release_turn_concurrency_slot:
    minimum_observability: O2

  release_model_capacity_during_tool_execution:
    minimum_observability: O3

  detect_permission_deadlock:
    minimum_observability: O3

  distinguish_thinking_from_tool_execution:
    minimum_observability: O3

  recover_state_after_gateway_restart:
    minimum_observability: O4
```

An O1 harness can still run, but conservatively: one-shot mode, keep the slot occupied, require manual completion, or use timeout + process termination.

## Current harness capability mapping

All rows are capability facts, not runtime declarations. `effective` is O0
unless and until the exact version/mode has a passing Docker probe and the
provider descriptor has been enabled. "Candidate" does not authorize an adapter,
hook installation, status enum, or control action.

**Platform eligibility**: a validated surface publishes only on platforms
listed in its `platform_evidence` (AS27 inventory). OpenCode native `opencode acp`
supports Windows, macOS, and Linux as vendor product platforms; Windows config
handles pwsh/cmd. However, local observability validation is proven only for
**linux-amd64** — the AS27 inventory's `platform_evidence` contains only that
platform. Vendor product support (windows/macOS/linux) does NOT imply local
validation: the session-surface resolver enforces an inventory proof gate
(AS27 RV770) that rejects O1+ validated claims on platforms absent from the
inventory. Platform support alone is not status evidence — AS29 surface validation
with exact launch/version/correlation proof gates publication.

| Harness surface/mode | Declared route / level | Validation | Effective | Platform evidence | Online docs / evidence reference |
| --- | --- | --- | ---: | --- | --- |
| OpenCode ACP | Native ACP, O2/O3 candidate | Validated | O1 | linux-amd64 (vendor supports windows/macOS/linux; local probe only proven on linux-amd64) | [ACP docs](https://opencode.ai/docs/acp/), [CLI docs](https://opencode.ai/docs/cli/) |
| OpenCode server/plugin/CLI | Server event/status API and plugin route, O2/O3-partial candidate | Probe required | O0 | windows/macOS/Linux | [Config docs](https://opencode.ai/docs/config/), plugins in `.opencode/plugins/`, LSP via `lspServers` key |
| Codex ACP bridge | ACP adapter, O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | [codex-acp adapter](https://github.com/agentclientprotocol/codex-acp), [Codex App Server API](https://developers.openai.com/codex/) |
| Codex CLI hooks | Native hooks, O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | Config: `~/.codex/config.toml` (global), `.codex/config.toml` (project-local), CLI overrides: `-c`, `--config-dir` |
| Claude Code ACP | ACP adapter, O2 candidate | Probe required | O0 | windows/macOS/Linux | [claude-agent-acp adapter](https://github.com/agentclientprotocol/claude-agent-acp), [Agent SDK hooks](https://code.claude.com/docs/en/agent-sdk/hooks.md) |
| Claude Code CLI | Native lifecycle hooks, O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | [Hooks reference](https://code.claude.com/docs/en/hooks.md), hook locations: `~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json` |
| Cline ACP | ACP, O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | [Cline ACP registry entry](https://github.com/agentclientprotocol/registry), launch: `npx cline --acp`, version 3.0.42 |
| Cline SDK/core/hooks/JSON CLI | [Runtime/core event stream](https://docs.cline.bot/sdk/events), hooks, structured output; O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | [SDK events docs](https://docs.cline.bot/sdk/events), `AgentRuntimeEvent` from `@cline/agents`, `agent.subscribe(listener)` |
| Gemini ACP | Native ACP, O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | Registry ID: `gemini`, launch: `npx @google/gemini-cli@0.50.0 --acp` |
| Gemini CLI | Native lifecycle hooks, O3 candidate | Probe required | O0 | windows/macOS/Linux | Prove exact installed hook config and event semantics |
| Qwen ACP | Native ACP, O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | Registry ID: `qwen-code`, launch: `npx @qwen-code/qwen-code --acp --experimental-skills`, [Alibaba docs](https://www.alibabacloud.com/help/doc-detail/3023091.html) |
| Kilo ACP | Native ACP, O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | Registry ID: `kilo`, launch: `kilo acp`, [Kilo CLI reference](https://kilo.ai/docs/code-with-ai/platforms/cli-reference) |
| Copilot ACP | [Official ACP server](https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server) and correlated terminal result, O2 candidate; public preview | Probe required | O0 | windows/macOS/Linux | [GitHub Copilot CLI ACP docs](https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server), [Changelog](https://github.blog/changelog/2026-01-28-acp-support-in-copilot-cli-is-now-in-public-preview/) |
| Pi native RPC | [JSONL agent/turn/message/tool events](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md), O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | [Pi RPC docs](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md), strict JSONL semantics with LF (`\n`) record delimiter |
| Pi community ACP | Community adapter, optional O2 candidate | Probe required | O0 | windows/macOS/Linux | [vkozak/pi-acp](https://github.com/vkozak/pi-acp) (513 stars), community adapter not native to Pi |
| Goose ACP/API | [Official ACP/API route](https://block-goose.mintlify.app/advanced/acp-protocol), O2 candidate | Probe required | O0 | windows/macOS/Linux | [Goose ACP Protocol docs](https://block-goose.mintlify.app/advanced/acp-protocol), registry ID: `goose`, launch: `goose acp`, version 1.43.0 |
| OpenHands Agent Canvas / remote server | [WebSocket event stream and conversation state](https://docs.openhands.dev/openhands/usage/agent-canvas/acp-agents), O2/O3 candidate | Probe required | O0 | windows/macOS/Linux | [OpenHands ACP Agents docs](https://docs.openhands.dev/openhands/usage/agent-canvas/acp-agents), uses `ACPAgent` to delegate conversations to external ACP-compatible servers |
| Zed external-agent thread | Delegates to the selected external agent's ACP/native route | Inherits child surface | O0 | windows/macOS/Linux | [Zed External Agents docs](https://zed.dev/docs/ai/external-agents), [Zed ACP docs](https://zed.dev/acp), MCP servers forwarded via ACP |
| Zed terminal thread | Process/terminal path only | Unresolved | O0 if adopted | windows/macOS/Linux | No UI or terminal scraping |
| Zed native agent UI | UI states may exist; machine API not evidenced | Investigation required | O0 | windows/macOS/Linux | Pending supported consumable event API |
| Antigravity CLI | Hooks/plugins/status mentioned, candidate route not source-pinned | Primary-source probe required | O0 | windows/macOS/Linux | B candidate; prove machine terminal event and config lifecycle; no Gemini inference |
| Continue headless | Structured one-shot result candidate | Probe required | O0 | windows/macOS/Linux | [Continue headless docs](https://docs.continue.dev/cli/headless-mode), `cn -p "prompt"` mode, tools requiring approval automatically excluded |
| Continue persistent TUI | Machine-readable persistent lifecycle not evidenced | Unresolved | O0 | windows/macOS/Linux | [Continue TUI docs](https://docs.continue.dev/cli/tui-mode), interactive session with `cn`, reference files with `@`, approve tool calls |
| Crush native backend | Possible server/session event route needs primary-source evidence | Investigation required | O0 | windows/macOS/Linux | [Crush server mode docs](https://deepwiki.com/charmbracelet/crush/3.9-server-mode-and-backend), enabled via `CRUSH_CLIENT_SERVER` env var |
| Aider CLI | No supported lifecycle route found | Unresolved | O0 if owned | windows/macOS/Linux | Scriptable via CLI (`--message`) or Python APIs; hooks/plugins not currently implemented (see [issue #2557](https://github.com/Aider-AI/aider/issues/2557)) |
| Plandex CLI | No supported lifecycle route found | Unresolved | O0 if owned | windows/macOS/Linux | [Plandex docs](https://docs.plandex.ai/install), install via `curl -sL <https://plandex.ai/install.sh> | bash`, Windows supported via WSL |
| Roo CLI | No supported lifecycle route found | Unresolved | O0 if owned | windows/macOS/Linux | [Roo Code docs](https://docs.roocode.com/features/skills), skills package task-specific instructions loaded on-demand, custom instructions/rules supported |

`local-openai` is intentionally absent: it is an endpoint/protocol family that
can expose provider request/response/usage telemetry, not an agent-loop harness
that can declare tool-loop or turn completion.

## ACP's role

ACP remains the common control plane for: open session, send prompt, receive updates, receive terminal response, cancel, close.

But ACP alone should not be expected to represent every internal phase consistently across harnesses. The wrapper enriches ACP-derived evidence with native signals:

```
ACP prompt submitted
    +
Gemini BeforeModel    (or Claude PreToolUse, or OpenCode tool event)
    +
Gemini AfterModel     (model done, but turn may continue with tools)
    +
Gemini BeforeTool
    +
Gemini AfterTool
    +
Gemini AfterAgent     (strong: agent loop completed)
    +
ACP terminal response

→ Completion Arbiter applies policy → turn state
```

## Ordering, persistence, and recovery

Normalized evidence carries an event ID, correlation keys, source sequence when
available, observed time, received time, and adapter version. Consumers must be
idempotent. Duplicate events are ignored; sequence gaps, clock regressions, and
late terminal events are recorded and force reconciliation when they could change
a scheduling decision.

O4 recovery persists both the evidence journal and a derived snapshot. On restart,
the gateway loads the last snapshot, replays later evidence, probes live process,
connection, and session state, and leaves the lane `UNKNOWN` until contradictions
are resolved. Completion side effects use idempotency keys based on turn ID and
terminal outcome so replay cannot dispatch dependent work twice.

## Validation probe suite

Capability declarations are claims until probes establish their evidence tier.
At minimum, adapters must cover:

| Probe | Required observation |
| --- | --- |
| Readiness | Process and connection readiness are distinct from turn availability |
| Simple prompt | Correlated terminal proof and committed output |
| Streaming | Partial output never becomes terminal by itself |
| Tool loop | Model and tool phases alternate without premature completion |
| Permission/user wait | Known wait reason; no completion or session reuse |
| Stop-hook continuation | A veto or continuation after candidate output remains non-terminal |
| Retry/rate limit | Backoff releases only resources permitted by policy |
| Cancellation/crash | Terminal outcome and session health are projected independently |
| Subagent/background work | Parent completion and surviving work are represented explicitly |
| Event loss/reconnect | Gap detection produces conservative `UNKNOWN` and reconciliation |
| Concurrent sessions | Correlation isolation and slot accounting remain correct |
| Long silence | Silence alone never proves waiting, thinking, or completion |

AS18 validates normalized callback publication and correlation. AS19 validates
surface/version-specific descriptor declarations, workflows, and
negative/unknown cases. Any later capacity item must prove release and
pre-model re-acquisition against a real controllable harness boundary.

## Recommended component split and plan-item ownership

| Component | Responsibility | Owning plan item |
| --- | --- | --- |
| **HarnessObserver** | Collects harness-specific signals (ACP events, hooks, stdout, process metrics) | AS18 (ACP binding, done); AS14 and bounded provider probes add further bindings |
| **EvidenceNormalizer** | Converts heterogeneous observations into AUDiaGentic evidence vocabulary | AS18 (envelope), AS19 (declaration gating) |
| **TurnStateMachine** | Tracks authoritative turn state (submitted → active → completed/failed/cancelled) | AS21 (TransitionEngine workflows) |
| **ActivityStateMachine** | Tracks model/tool/wait activity (thinking, executing, awaiting_permission) | AS18/AS19; future scheduler optimization remains separate |
| **CompletionArbiter** | Determines whether sufficient evidence exists for terminal turn state | AS21 — sole arbiter; its projection feeds SH07's durable record (RV561) |
| **SessionReusePolicy** | Determines whether the persistent session can accept another prompt | AS21 flags consumed by session runtime (AS08) |
| **ResourceScheduler** | Releases or retains model, process, and concurrency capacity based on state | AS15 (done); SH08 for machine-wide arbitration; later O3 work requires a proven control boundary |
| **EvidenceJournal / replay** | Ordered durable evidence, snapshots, restart reconstruction | Not implemented; foundation timelines/FileEventStore are best-effort evidence, not an O4 journal |
| **Reconciler** | Post-restart/orphan reconciliation | AS26 owns active-turn orphan recovery; SH07 owns durable gateway request recovery |

SH07 owns durable gateway request state. Agent-jobs separately owns its workflow
job records and consumes projected terminal/dependency decisions exactly once.
Every component above is evidence production or projection and must not create
a competing durable store for either authority.

## Design principle: scheduler questions

The scheduler must always be able to answer these six questions unambiguously and quickly:

1. **Can I dispatch another prompt?** — Is session Ready or Idle?
2. **Can I reuse this session?** — Is session Idle (not just Awaiting Input)?
3. **Is work still occurring?** — Is turn Active with model or tool activity?
4. **Is the harness waiting on something?** — Is turn Paused with a known reason?
5. **Has the current turn definitely finished?** — Do we have trusted terminal evidence?
6. **Is the process still healthy?** — Is process Alive/Ready, or Degraded/Exited?

Everything else belongs to the detailed activity model and does not need to be visible to the scheduler.

## Consolidated ACP Capabilities & Protocol Mapping

This section consolidates all ACP (Agent Client Protocol) capabilities, OS/platform support, hooks/plugins, and configuration details for all harnesses.

### ACP Provider Matrix

| Provider | ACP status | Type | Registry ID | Launch command | Platform support |
| --- | --- | --- | --- | --- | --- |
| OpenCode | Supported | Native | `opencode` | `opencode acp` | Windows/macOS/Linux |
| Kilo Code | Supported | Native | `kilo` | `kilo acp` | Windows/macOS/Linux |
| Qwen Code | Supported | Native | `qwen-code` | `npx @qwen-code/qwen-code --acp --experimental-skills` | Windows/macOS/Linux |
| Gemini CLI | Supported | Native | `gemini` | `npx @google/gemini-cli@0.50.0 --acp` | Windows/macOS/Linux |
| Claude Code | Supported | Adapter | `claude-acp` | `npx -y @agentclientprotocol/claude-agent-acp` | Windows/macOS/Linux |
| Codex CLI | Supported | Adapter | `codex-acp` | `npx -y @agentclientprotocol/codex-acp` | Windows/macOS/Linux |
| GitHub Copilot | Supported | Native | `github-copilot-cli` | `npx @GitHub/copilot@1.0.71 --acp` | Windows/macOS/Linux |
| Cline | Supported | Native | `cline` | `npx cline --acp` | Windows/macOS/Linux |
| Cursor | Supported | Native | `cursor` | `cursor-agent acp` | Windows/macOS/Linux |
| Pi | Supported | Adapter | `pi-acp` | `npx pi-acp@0.0.31` | Windows/macOS/Linux |
| Goose | Supported | Native | `goose` | `goose acp` | Windows/macOS/Linux |
| OpenHands | No registered agent | N/A | — | — | ACP consumer/host |
| Crush | No registered agent | N/A | — | — | No ACP agent entry found |
| Continue | No registered agent | N/A | — | — | No ACP agent entry found |
| Aider | No registered agent | N/A | — | — | No ACP agent entry found |
| Zed | No registered agent | N/A | — | — | ACP consumer (via extensions)

### Session and External-Control Matrix

| Provider | ACP-created session | Persisted resume through ACP | Attach ACP to independently started TUI | Native shared/live control path | Out-of-band injection |
| --- | --- | --- | --- | --- | --- |
| Codex CLI | Yes, through `codex-acp` | Yes | No direct attachment mechanism established | **Codex App Server** can own the session while the Codex TUI and another controller connect to the same server | App Server supports `turn/start` for a new turn and `turn/steer` for the active turn |
| Claude Code | Yes, through `claude-agent-acp` | Yes | No direct attachment mechanism established | Claude background-session tooling, Remote Control, and Channels are separate native control mechanisms | **Channels** can push events into an already-running session started with `--channels` |
| Native ACP providers | Yes | Provider and ACP-capability dependent | Not implied by native ACP support | Provider-specific | Provider-specific |
| Adapter-based providers | Yes, when launched through the adapter | Adapter-dependent | Normally no; the adapter owns a separate runtime | Provider-specific native interface may exist | Provider-specific |
