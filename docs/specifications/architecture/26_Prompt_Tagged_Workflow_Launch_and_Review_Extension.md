# Prompt-Tagged Workflow Launch and Review Extension

## Purpose

Freeze the Phase 3.2 extension that lets a prompt from VS Code, Codex/Cline/Continue-style CLIs, or similar interactive surfaces launch or resume deterministic AUDiaGentic workflow work.

This extension exists so prompt-driven work can stay inside the same build discipline as packet-driven implementation:
- explicit target selection
- explicit provenance
- explicit review policy
- deterministic handoff across prompts
- no silent direct writes to tracked docs

## Relationship to existing phases

This extension sits **after** the .1 provider/model contract work.

Required earlier work:
- Phase 3 core jobs are already complete
- Phase 4 provider access-mode work is already complete
- Phase 4.1 provider/model selection must freeze provider/model fields before prompt launch consumes them
- Phase 0.2 / 1.2 / 2.2 extension packets in this doc pack finalize contracts, lifecycle handling, and release handling for prompt metadata

The extension must not redesign the core Phase 3 state machine.

## Design goals

1. Let an explicit prompt launch a legal workflow activity.
2. Let a later prompt resume the same job safely.
3. Let generic ad hoc work run without inventing a fake packet.
4. Let review run as a first-class workflow activity.
5. Let multiple review reports be aggregated deterministically before commit/check-in.
6. Keep CLI and VS Code differences out of the jobs core.

## End-state intent

The desired end functionality for all supported providers is that any CLI or prompt-entry surface can accept the canonical launch syntax, normalize it through a repo-owned bridge, and hand the request to the jobs layer without changing workflow meaning.

This extension defines the job-side grammar and target rules. Provider-specific mechanics belong to the provider surface docs and must converge on the same bridge-backed contract.

## Frozen MVP decisions

### Prompt syntax

MVP uses **prefix-token-v1**.

The first non-empty line must contain the tag and any structured key/value directives:

```text
@implement target=packet:PKT-JOB-007 provider=codex model=gpt-5.4-mini profile=standard
```

Everything after that line is the prompt body.

Allowed tag tokens:
- `@plan`
- `@implement`
- `@review`
- `@audit`
- `@check-in-prep`

Short aliases:
- `@p` -> `@plan`
- `@i` -> `@implement`
- `@r` -> `@review`
- `@a` -> `@audit`
- `@c` -> `@check-in-prep`

Provider shorthand:
- `@codex`, `@claude`, `@gemini`, `@qwen`, `@copilot`, `@cline`, `@continue`, and `@local-openai` may be used as the first token when the provider is the most important part of the launch
- when provider shorthand is used without an explicit target, the launcher infers a default runtime subject and selects the provider's default model

Shorthand:
- `@adhoc` is part of the contract baseline and normalizes to `tag=implement` with `target=adhoc`

Feature gate note:
- the first executable pass may accept `@adhoc` in parser/schema validation while returning a deterministic `not-enabled` result unless `prompt-launch.allow-adhoc-target` is explicitly enabled
- the core launch path, packet/job target resolution, and review loop do not depend on `@adhoc` being enabled

Rejected in MVP:
- free-form natural language routing
- YAML front matter
- JSON-only envelope pasted by the user
- multiple tag lines in one prompt

### Normalization boundary

Every interactive surface must normalize the prompt into a `PromptLaunchRequest` before the jobs layer sees it.

This keeps parsing and validation consistent across:
- VS Code extensions
- Codex/Cline/Continue CLI wrappers
- future server/UI adapters

This is the canonical prompt-entry behavior the project is aiming for across all supported providers. Where a provider cannot intercept raw prompts directly, a repo-owned wrapper or bridge must take over so the same launch contract still applies.

### Target kinds

The prompt launcher supports exactly four target kinds in MVP:

#### `packet`
Use when the work clearly maps to a documented packet or workflow step tied to a packet.

Example:
```text
@implement target=packet:PKT-JOB-008
```

#### `job`
Use when resuming or advancing an existing job.

Example:
```text
@plan target=job:job_20260330_0007
```

#### `artifact`
Use when review or audit needs to inspect a specific runtime artifact.

Example:
```text
@review target=artifact:art_job_0007_impl_plan
```

#### `adhoc`
Use for generic work that is not a named packet.

Example:
```text
@adhoc review-count=2
```

Ad hoc targets still create a JobRecord. They simply use a generic subject instead of a packet id.

## Launch semantics

### New launch

A prompt creates a new job when:
- the target is `packet` or `adhoc`, and
- `existing-job-id` is omitted

### Resume

A prompt resumes an existing job when:
- `existing-job-id` is present, or
- `target.kind=job`

Resume must fail if:
- the requested tag is not a legal next stage for the current profile/state
- the requested target conflicts with the stored launch target
- the job is already terminal (`completed`, `failed`, `cancelled`)

### Tag-to-stage mapping

| Tag | Stage behavior |
|---|---|
| `plan` | enter or resume the planning stage |
| `implement` | enter or resume implementation |
| `review` | execute structured review against a subject artifact/job/packet |
| `audit` | run deterministic policy/release checks |
| `check-in-prep` | prepare release-facing summary artifacts only |

`@adhoc` maps to `implement` against an `adhoc` target.

## Ad hoc job rules

Ad hoc jobs exist so a user can ask for work that is real but not packet-shaped, such as:
- draft a migration note
- prepare a small refactor plan
- review an implementation summary
- analyze a runtime issue

Rules:
- ad hoc jobs must still use a valid workflow profile
- ad hoc jobs may write runtime artifacts only
- ad hoc jobs must not claim or mutate a packet unless a later prompt retargets them explicitly
- check-in/release-facing tracked docs still require the standard release path

Recommended generated ids:
- `adh_YYYYMMDD_NNNN` for the subject id
- a runtime subject manifest under `.audiagentic/runtime/jobs/<job-id>/subject.json`

## Review loop design

### Single review

A review prompt creates a `ReviewReport`.

Minimum review inputs:
- subject reference
- criteria list
- reviewer provenance
- prompt body
- prior artifact(s) being reviewed

### Multi-review

When policy requires more than one review:
- each review creates a distinct `ReviewReport`
- the job creates or updates a `ReviewBundle`
- the bundle aggregates reports using a deterministic rule

### MVP aggregation rule

MVP supports one enforced rule:

- `all-pass`

Meaning:
- every required review must be present
- every counted review must come from a distinct reviewer if `require-distinct-reviewers=true`
- any `rework` or `block` recommendation prevents approval

A documented but not yet implemented future rule is:
- `majority-pass`

### Distinct reviewer identity

A `reviewer-key` should be stable within one project session and derived from:
- provider id
- surface
- session id or another deterministic interactive-session key

This is used only for counting unique reviewers, not for identity or access control.

## Commit/check-in gating

The extension does **not** authorize direct commits.
It provides deterministic review evidence that later commit/check-in flows can inspect.

MVP gating behavior:
- a review bundle with `decision=approved` may satisfy the review requirement for a later check-in or approval step
- a review bundle with `decision=rework` or `decision=blocked` prevents automatic progression
- approval policy remains with the existing approval core and workflow profile rules

## Provenance rules

Prompt provenance must survive into runtime data.

Minimum provenance fields:
- prompt id
- tag
- surface
- provider id
- session id
- optional model id / model alias
- target kind / target ref
- related review id when applicable

This provenance belongs in runtime job/event data.
It is not release-visible by default.

## Runtime artifact layout

Recommended runtime locations:

```text
.audiagentic/runtime/jobs/<job-id>/
  launch-request.json
  subject.json
  stage-results/
  reviews/
    review-report.<review-id>.json
    review-bundle.json
```

Exact filenames may vary, but the following rules are fixed:
- launch envelopes and review artifacts are runtime-only
- review artifacts live under the owning job
- tracked docs are updated only through existing release/check-in mechanisms

## Lifecycle and tracked config impact

Tracked config stays minimal.

For MVP the only tracked config additions are optional fields in `.audiagentic/project.yaml`:
- `workflow-overrides`
- `prompt-launch.syntax`
- `prompt-launch.allow-adhoc-target`
- `prompt-launch.default-review-policy.*`

`.audiagentic/workflows.yaml` is deferred.

## Release/audit impact

Release outputs must remain deterministic.
Prompt metadata is internal-only unless a deliberate `check-in-prep` step converts findings into tracked summaries.

Default release behavior:
- omit raw prompt text
- omit runtime prompt provenance
- omit raw review reports
- allow summarized review outcome only when check-in/release scripts explicitly surface it

## Explicit non-goals

Not in MVP:
- intent inference without a tag
- automatic fan-out to multiple agents from one prompt
- automatic merge/commit execution
- semantic duplicate detection across unrelated prompts
- cross-project review federation

## Acceptance bar for implementation

The extension is ready to implement only when all of the following are true:
- `.1` provider/model contract work is merged
- PromptLaunchRequest, ReviewReport, and ReviewBundle schemas validate
- project config schema includes the prompt-launch policy block
- packet dependency graph and build registry reflect the .2 packets
- packet docs define recovery and tests
- `@adhoc` is covered by fixtures as a baseline contract case, but executable enablement may remain feature-gated in the first pass
- multi-review aggregation is covered by fixtures

## Implementation sequence

1. `PKT-PRV-012` — finalize provider model contract
2. `PKT-FND-008` — finalize .1 shared contract/schema deltas
3. `PKT-JOB-007` — carry provider/model metadata into jobs
4. `PKT-FND-009` — add prompt/review contracts and fixtures
5. `PKT-LFC-009` — preserve/validate prompt-launch config
6. `PKT-RLS-010` — deterministic release handling for prompt/review metadata
7. `PKT-JOB-008` — prompt launch core + ad hoc target
8. `PKT-JOB-009` — structured review loop + multi-review aggregation

## Why this version is implementation-ready

The original idea survived as intent but not as an executable contract.
This extension closes the missing details by freezing:
- the syntax
- the normalization boundary
- the target model
- the ad hoc path
- the review aggregation policy
- the runtime artifact rules
- the packet sequence
