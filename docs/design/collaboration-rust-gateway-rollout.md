# Rust collaboration + gateway push: staged rollout

**Status:** proposed implementation roadmap (2026-10-22); not a tracked ag-planning item or proof that anything is implemented.
**Base:** current `main` as reviewed during planning. Related unmerged design: PR [#29](https://github.com/Audumla/AUDiaGentic/pull/29). Rust foundation: draft PR [#24](https://github.com/Audumla/AUDiaGentic/pull/24). Existing execution-queue plans: `SH25` and `SH28`.

## Immutable ownership and branching rules

1. **Every implementation stage has its own branch and PR.** No writes or direct merges to `main`; no unrelated edits to a stage branch. This roadmap itself is changed only on a dedicated planning branch.
2. Begin each implementation branch from up-to-date `main` **when its prerequisites have landed**. Where two unmerged changes must be tested together, use a temporary integration branch with explicit dependency PRs, not a hidden cross-stage implementation branch. Avoid creating stale stage branches before the Rust foundation cleanup finishes.
3. Keep current uncommitted gateway recovery/provider work and Rust foundation PR #24 untouched. G1/G2 start only after a conflict-safe gateway recovery baseline; R1 starts when the new Rust foundation contracts are stabilised.
4. **Gateway** exclusively owns agent execution admission, capacity, provider sessions, per-session FIFO/steering, verified terminal results, persisted execution records, and request recovery.
5. **Rust collaboration** exclusively owns topics, participation, offered expertise, routing decisions, conversation history, peer requests, collaboration state and where replies need to go.
6. **Provider adapters/harnesses** remain unchanged for the MVP. Steering is opportunistic and used only when an existing surface positively proves support; queued continuation must work without it.
7. **MQTT** is an optional event transport. It is not the authority for either Work or collaboration history. Preserve separate broker-neutral contracts; `SH25`/`SH28` concern *inbound execution scheduling*, not this rollout's outbound callback and collaboration notifications.
8. The planning guide `docs/planning/CREATING_PLANS.md` requires `ag-planning` to allocate/edit tracked items. When available, reconcile existing open plans and create new tracked stage items through that interface; do not hand-create IDs or edit tracked ledger frontmatter with GitHub contents operations.

## Dependency graph

```text
Existing gateway recovery / session authority ---+--> G1: result push -----+
                                                  +--> G2: deliver-to-session-+
                                                                              +--> R2: integration/durable delivery --> V1: e2e
Rust foundation PR #24 (stabilised) ------------------> R1: topics/registry --+
                                                        |                     +--> I1: MCP --> I2: Discord
                                                        +--> M1: MQTT backend (optional after R2 event contracts)
```

G1, G2 and R1 can be developed independently. R2 integrates their *public* contracts. I1, I2 and M1 are optional for the minimal end-to-end proof. V1 gates production rollout. `SH25` and `SH28` are independent of the collaboration milestones.

## Stage G1 — Generic gateway verified-result push

**Branch:** `feat/gateway-result-push` (create later from current `main`).
**Owns:** gateway **outbound** result-delivery ledger/outbox and subscriber contract. **Does not own** inbound scheduling, collaboration topics or user-supplied arbitrary webhooks.

**Contract:**
- On submission, caller may provide a validated `subscription_id` naming a preconfigured authorised subscriber, together with existing correlation/idempotency identity. Absence retains existing gateway behaviour.
- After the authoritative request store commits a terminal state and its verified success output is available, stage a durable event with `event_id`, `request_id`, `project_id`, `correlation_id`, `subscription_id`, `outcome`, and `result_ref`. Failed/cancelled/interrupted outcomes must not advertise successful verified output.
- Do **not** copy prompt or full response bodies to the broker. Subscriber obtains any verified payload through the existing authenticated gateway response API.
- Deliver event asynchronously through a generic outbound adapter. MVP: registered authenticated local callback endpoint (or equivalent authenticated streaming subscription if security review prefers it), never a request-controlled URL. Retry from durable outbox after crash/network failure.
- Subscriber acknowledges **only after its own durable ingest**; retries have stable IDs. Unacknowledged delivery is not equivalent to incomplete *execution*. Maintain retry/attempt/backoff and inspectable terminal/dead-letter state independently of request lifecycle.
- Stage/reconcile outbox atomically with terminal state or via restart-safe replay of terminal records; no lost event at crash windows.

**Acceptance:** submit/wait/status behaviour unchanged when disabled; same terminal request yields one event identity across repeated delivery; restart/crash between terminal commit, outbox stage, POST, subscriber commit and ACK causes neither lost notification nor duplicate subscriber effect. Auth/project filtering, bounded payload, reconnect and terminal-failure classifications tested.

## Stage G2 — Provider-neutral gateway session delivery

**Branch:** `feat/gateway-session-delivery` (independent of G1 at source level).
**Owns:** generic session-delivery API, **not** collaboration inbox/history.

**Proposed request:** `deliver_to_session({session_id, expected_generation, idempotency_key, correlation_id, content_ref_or_text, policy: "steer-or-queue"})`.
- Validate project/session/generation/admission and create a durable identity before touching provider transport.
- Baseline: enqueue the response as a **normal FIFO continuation** under existing gateway session authority; return `queued` + canonical request/turn identity. It must survive gateway restart and coexist safely with a busy session and ordinary user turns.
- If provider surface *positively* supports steering, an implementation MAY use it with owner fencing and race handling; unsupported => FIFO, not provider-specific routing in Rust.
- Treat steering accepted/transport injected, gateway admitted and model consumed as distinct evidence states. Never silently queue the same prompt after an ambiguous steering side effect.
- Fail closed on session generation changes, expired/unavailable session or unknown provider side effect; no automatic new conversation or unsafe duplicate submit.

**Acceptance:** two simultaneous deliveries for one session maintain FIFO; requests during an active turn queue exactly once when steering unsupported; gateway restart restores accepted continuations; stale generation rejected; no duplicate model prompt after timeout/ambiguous transport acknowledgement. Any new provider steering adapter requires its *own* later branch with evidence-backed conformance.

## Stage R1 — Rust collaboration domain and topic registration

**Branch:** `feat/rust-collab-topics` (after Rust foundation stabilises).
**Owns:** optional Rust collaboration domain, **not** a second Agent Definition / Role / execution capability catalogue.
- Typed project-scoped `topic`, `participant`, `participant_session_binding`, `offered_skill`, `listening_policy`, `message`, `assistance_request` and `assignment`.
- Participants register to **topics** and advertise only a subset of existing `AgentDefinition.advertised_skills`; roles/launch requirements remain with Agents/gateway, and declared expertise never grants execution permission.
- Derive topic-available actions/skills from current registrations and policy; expose versioned topic metadata. A participant can request `review`, `deep-dive`, `help` by skill, without naming a recipient.
- Deterministic candidate selection from eligible registered topic participants; apply explicit permission, availability, project scope, concurrency/budget and loop-prevention policies. If none match, leave a visible bounded unassigned request or reject under topic policy; never silently pick arbitrary global agents.
- Each agent retains an **independent** Agent Context and gateway session; topic membership stores references/generations only. Collaboration messages are not gateway execution observations.
- Domain logic uses ports; do not depend on MQTT, SQL or Python provider modules. Keep Rust code modular; don't split into unnecessary crates during foundation cleanup.

**Acceptance:** registration/unregistration instantly changes available topic metadata; same inputs yield deterministic matching; no permission escalation; independent session identities preserved; optional component off leaves gateway functional.

## Stage R2 — Rust request/reply coordination + gateway adapter

**Branch:** `feat/rust-collab-dispatch` (after R1 and G1/G2 contracts land).
**Owns:** collaboration durable journal/inbox/outbox, correlated request/reply, automatic return to requester.
- Transactionally record an assistance request and dispatch intent; submit independent selected agent Work via **public gateway API** with stable idempotency/correlation keys.
- Receive G1 validated result push through named subscriber. Persist event/result identity before acknowledging gateway delivery. Retrieve verified output by authorised reference, maintain failure/partial distinction.
- Persist a requester-bound delivery intent and call G2 `deliver_to_session`; busy target => queued FIFO; idle target => automatic continuation; optional supported steering. Original agent does **not** poll or name the reviewer.
- Restart reconciliation handles ambiguous gateway submission/delivery using existing authoritative request/session reads, never resubmitting possibly sent prompts with a new id.
- Separate statuses: assistance pending/assigned/completed, outbound gateway event accepted, requester delivery admitted, and provider/model consumption proven or unconfirmed. No false exactly-once claims.
- Enforce per-topic and per-agent budgets, bounded recursion and anti-echo policy.

**Acceptance:** Codex requests unnamed concurrency review; topic selects Claude/Pi from registered capabilities; gateway verifies output; Rust records topic response; original Codex session receives it without polling. Repeated callback, lost ACK, Rust crash, gateway crash or duplicate MQTT wakeups cause no duplicate execution/turn. Failed review remains failure.

## Stage M1 — Optional MQTT 5 transport

**Branch:** `feat/collab-mqtt` (after R2's event contract; can be developed alongside I1).
**Owns:** notification transport adapter(s), **not** gateway execution scheduling or app lifecycle authority.
- Suggested namespace: `audia/v1/collab/topics/{topic_id}/events`, `audia/v1/collab/work/ready`, `audia/v1/collab/delivery/ready`; optional gateway outbound adapter may use `audia/v1/gateway/results/{subscriber_id}` after G1 proves equivalent durability.
- Events include version, immutable event ID, project/topic, correlation/causation, subject and payload **reference** only. Do not publish raw prompts/response contents or secrets.
- MQTT 5 QoS 1 with stable consumer IDs and persistent sessions where appropriate; broker-backed wakeup remains replaceable by DB dispatcher. Shared subscriptions distribute **router workers**, not specialists; Rust capability matching chooses agents.
- Prove broker reconnect/restart, duplicate/reorder, retained-message/expiry handling, backpressure and ACL topic isolation using chosen Mosquitto configuration.
- Do not modify `SH25` scheduler or imply MQTT QoS 2 guarantees exactly-once model execution.

**Acceptance:** fully functional no-MQTT mode; MQTT mode converges to same durable collaboration state; broker outage delays notifications but cannot lose accepted requests/replies.

## Stage I1 — Agent-facing collaboration MCP

**Branch:** `feat/collab-mcp` (after R2).
**Owns:** thin capability client adapter to Rust application API, no session runtime.
- Operations: discover/join/leave topics; advertise topic-approved expertise; post messages; request unnamed help/review/deep-dive; view bounded topic context and request states.
- Derive tool metadata from topic registration (not a large static taxonomy); agent responses are pushed via R2/G2, never require polling to be received.
- No direct MQTT subscription, gateway internals or provider SDK in harnesses. Role-based access and scoped project/topic checks.
- Minimal opt-in prompt guidance for agents to request help when needed; no mandatory supervisor model.

**Acceptance:** Codex/Claude/Pi/OpenCode can use the same MCP contract; disabling capability leaves their normal execution unchanged.

## Stage I2 — Optional human/forum bridge

**Branch:** `feat/collab-discord` (after I1 or equivalent public Rust API).
**Owns:** external interface only.
- Map configured Discord channel/thread to one canonical Rust topic; distinguish author identities and permissions. Humans can join, inspect discussions, post messages and explicitly request reviews.
- Avoid channel-to-gateway direct dispatch and reply echo loops; durable deduplication for bridge restarts, edited/deleted messages and outbound retries.
- No Discord installation requirement for headless or MCP-only deployments.

**Acceptance:** Discord and MCP show same canonical message IDs and topic participants; bridge outage does not affect gateway execution or lose canonical events.

## Stage V1 — Cross-process reliability, soak, release gate

**Branch:** `test/collab-end-to-end` (after G1/G2/R1/R2; M1/I1/I2 optional gates depending on deployment).
- Matrix: idle/busy requester, 2+ replies, restart at every durable boundary, failed/partial result, stale session generation, unsupported steering, gateway/SQL/MQTT outages, duplicate/reordered event, full and absent collaboration installations.
- Assert no second execution authority; one session FIFO owner; no duplicate provider side effects; terminal output verification precedes success push; original agent receives reply automatically; no cross-project leakage.
- Emit redacted diagnostics and replay controls. Start with opt-in test deployment; no automatic production enablement while Rust core is under cleanup.

## Implementation / PR policy

- Each branch contains **only its named stage**, source/tests/docs together. Keep docs and tests in the same PR as the implementation they describe. The architecture planning change lives separately from all stages.
- Never cherry-pick unfinished provider/gateway recovery files into stage branches. If blocked, document dependency rather than duplicating implementation.
- Require an independent code review and stage-specific tests before merge; G1/G2 must pass current gateway recovery, per-session FIFO and no-resubmit regression suites; Rust stages must pass framework and isolated adapter tests.
- Merge in dependency order, retarget and rebase only with verified expected-head guards, and keep feature flags default-off until V1. Do **not** auto-merge.
- Where `main` is ahead of PR #29, reconcile its base/CI before merging architecture documentation; this roadmap clarifies, rather than silently alters, PR #29's earlier general design.

## Follow-up through planning MCP

When `ag-planning` is available: inspect existing items and reviews across `agent-sessions`, `shared-gateway`, `provider-capability-model` and Rust/foundation; create or update the smallest tracked items corresponding to G1/G2/R1/R2/M1/I1/I2/V1. The gateway's existing `SH25`/`SH28` items remain concerned with inbound execution scheduling; avoid assigning them ownership of the new *outbound* result subscription.
