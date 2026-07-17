# ACP Capability Analysis

Status: investigation — pre-work for provider capability documentation
Last checked: 2026-07-16
Sources: ACP registry v1.0.0 (2026-07-16), provider evidence documents, adapter implementations, and native provider control documentation

## Scope

This document records:

1. Whether each provider in scope supports the Agent Client Protocol (ACP).
2. Whether that support is **native** or provided through a separate **adapter**.
3. Which process owns the resulting agent session.
4. Whether persisted sessions can be resumed.
5. Whether another process can attach to, steer, or inject messages into an already-running interactive session.

ACP support alone does not establish that a provider can attach to an arbitrary CLI or IDE session that was started independently.

## Terminology

| Term                         | Meaning                                                                                                               |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Native**                   | An ACP endpoint is built into the product’s own CLI or binary. No wrapper is required.                                |
| **Adapter**                  | A separate package wraps the product, SDK, or native control protocol and exposes it as an ACP agent.                 |
| **No registered agent**      | No ACP agent entry was found in the registry. This does not prove that an unregistered implementation does not exist. |
| **ACP agent**                | A process that implements the ACP agent side and can be driven by an ACP client.                                      |
| **ACP consumer**             | A product that hosts or drives ACP agents but is not itself exposed as an ACP agent.                                  |
| **Session owner**            | The process responsible for creating and maintaining the live agent runtime and conversation.                         |
| **Persisted-session resume** | Loading stored conversation history and continuing it in a new or recreated runtime.                                  |
| **Live-session attach**      | Connecting another client to the same currently running agent process and session.                                    |
| **Out-of-band injection**    | Delivering an external message or event into a running session without using its normal terminal input.               |

## Registry data

The ACP registry at `agentclientprotocol/registry` contains more than 40 agents.

Only providers relevant to our scope are listed below. Registry presence establishes a published ACP entry; registry absence establishes only that no registered ACP agent was found.

## Provider ACP matrix

| Provider       |          ACP status | Type    | Registry ID          | Launch command                                         | Notes                                                                                                                                                                                                    |
| -------------- | ------------------: | ------- | -------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OpenCode       |           Supported | Native  | `opencode`           | `opencode acp`                                         | Official entry, binary distribution across six platforms. Version 1.18.2 in registry. Runtime model override through `OPENCODE_CONFIG_CONTENT`.                                                          |
| Kilo Code      |           Supported | Native  | `kilo`               | `kilo acp`                                             | Fork of OpenCode; binary and npx distributions. Version 7.4.9.                                                                                                                                           |
| Qwen Code      |           Supported | Native  | `qwen-code`          | `npx @qwen-code/qwen-code --acp --experimental-skills` | Official Alibaba entry. Version 0.19.10. Verify whether `--experimental-skills` is required for ACP startup or only enables additional capability.                                                       |
| Gemini CLI     |           Supported | Native  | `gemini`             | `npx @google/gemini-cli@0.50.0 --acp`                  | Google official. Also runs as an ACP agent in OpenHands Agent Canvas.                                                                                                                                    |
| Claude Code    |           Supported | Adapter | `claude-acp`         | `npx -y @agentclientprotocol/claude-agent-acp`         | Adapter built on the official Claude Agent SDK. It does not make the normal Claude Code TUI a native ACP server. Version 0.59.0 in the checked registry data.                                            |
| Codex CLI      |           Supported | Adapter | `codex-acp`          | `npx -y @agentclientprotocol/codex-acp`                | Adapter starts Codex App Server and translates between ACP and the native Codex protocol. It does not make an independently started Codex TUI an ACP server. Version 1.1.4 in the checked registry data. |
| GitHub Copilot |           Supported | Native  | `github-copilot-cli` | `npx @GitHub/copilot@1.0.71 --acp`                     | Official GitHub entry.                                                                                                                                                                                   |
| Cline          |           Supported | Native  | `cline`              | `npx cline --acp`                                      | Official entry from Cline Bot Inc. Version 3.0.42.                                                                                                                                                       |
| Cursor         |           Supported | Native  | `cursor`             | `cursor-agent acp`                                     | Official Cursor entry with binary distribution. Version 2026.07.09.                                                                                                                                      |
| Pi             |           Supported | Adapter | `pi-acp`             | `npx pi-acp@0.0.31`                                    | Community adapter by Sergii Kozak. Not native to Pi.                                                                                                                                                     |
| OpenHands      | No registered agent | N/A     | —                    | —                                                      | OpenHands Agent Canvas consumes ACP agents but is not registered as an ACP agent itself.                                                                                                                 |
| Crush          | No registered agent | N/A     | —                    | —                                                      | No ACP agent entry found in the checked registry.                                                                                                                                                        |
| Continue       | No registered agent | N/A     | —                    | —                                                      | No ACP agent entry found in the checked registry.                                                                                                                                                        |
| Goose          |           Supported | Native  | `goose`              | `goose acp`                                            | Official Block/Goose entry. Binary distribution with SHA-256 verification. Version 1.43.0.                                                                                                               |
| Aider          | No registered agent | N/A     | —                    | —                                                      | No ACP agent entry found in the checked registry.                                                                                                                                                        |
| Zed            | No registered agent | N/A     | —                    | —                                                      | Zed consumes ACP agents through extensions but is not registered as an ACP agent.                                                                                                                        |

## Session and external-control matrix

This matrix distinguishes ACP session persistence from control of a session that is already running in another client.

| Provider                |                    ACP-created session |          Persisted resume through ACP |          Attach ACP to independently started TUI | Native shared/live control path                                                                                | Out-of-band injection                                                                  |
| ----------------------- | -------------------------------------: | ------------------------------------: | -----------------------------------------------: | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Codex CLI               |               Yes, through `codex-acp` |                                   Yes |       No direct attachment mechanism established | **Codex App Server** can own the session while the Codex TUI and another controller connect to the same server | App Server supports `turn/start` for a new turn and `turn/steer` for the active turn   |
| Claude Code             |        Yes, through `claude-agent-acp` |                                   Yes |       No direct attachment mechanism established | Claude background-session tooling, Remote Control, and Channels are separate native control mechanisms         | **Channels** can push events into an already-running session started with `--channels` |
| Native ACP providers    |                                    Yes | Provider and ACP-capability dependent |                Not implied by native ACP support | Provider-specific                                                                                              | Provider-specific                                                                      |
| Adapter-based providers | Yes, when launched through the adapter |                     Adapter-dependent | Normally no; the adapter owns a separate runtime | Provider-specific native interface may exist                                                                   | Provider-specific                                                                      |

### Codex control model

`codex-acp` is a stdio ACP agent server. It starts Codex App Server, translates ACP requests into Codex operations, and maps Codex events back to the ACP client.

The adapter currently advertises ACP capabilities including:

* session loading;
* session listing;
* session resumption;
* session closing and deletion;
* prompt execution;
* permission handling;
* MCP servers;
* terminal, file-change, reasoning, plan, review, web-search, image, usage, and subagent events.

This supports continuing stored Codex conversations through the adapter. It should not be described as attaching ACP to an arbitrary Codex TUI process that was started separately.

Codex also exposes a native App Server control path:

```bash
codex app-server --listen ws://127.0.0.1:4500
codex --remote ws://127.0.0.1:4500
```

In this arrangement, App Server owns the session. The terminal UI is one client, and AUDiaGentic can be another client of the same server.

Relevant native methods include:

* `thread/list`
* `thread/read`
* `thread/loaded/list`
* `thread/resume`
* `turn/start`
* `turn/steer`
* `turn/interrupt`

`turn/steer` appends input to the currently active turn and therefore provides stronger live control than ACP’s ordinary prompt-and-response session abstraction.

This is a **native Codex control transport**, not ACP. AUDiaGentic should model it separately from `codex-acp`.

### Claude Code control model

`claude-agent-acp` implements ACP using the official Claude Agent SDK. The adapter owns the SDK query and Claude process used for that ACP session.

The current adapter implementation includes ACP operations for:

* creating sessions;
* listing sessions;
* loading sessions;
* resuming sessions;
* forking sessions;
* closing and deleting sessions;
* prompting and cancelling;
* permission requests;
* configuration and mode changes.

These operations allow an ACP client to continue persisted Claude sessions through the adapter. They do not establish a general mechanism for attaching ACP to an arbitrary interactive Claude Code process that is already running.

Claude Code has separate native control mechanisms.

#### Channels

Channels are MCP servers that can push events into an already-running Claude Code session. The session must be launched with the channel enabled:

```bash
claude --channels plugin:<channel>@<marketplace>
```

Characteristics:

* The event arrives in the session already open.
* The channel can be two-way.
* Events are received only while the session remains running.
* Custom channels can bridge another agent, webhook, chat system, or AUDiaGentic service into the session.
* Channel permission relay can allow remote approval or denial of tool requests.
* Channels are currently a research-preview feature and require explicit per-session enablement.

Channels are therefore a suitable **inbound live-session injection mechanism**, but they are not ACP and should not be represented as an ACP transport.

#### Background sessions and attachment

Claude Code also provides managed background sessions and human attachment:

* `claude agents --json`
* `claude attach <id>`
* `claude logs <id>`
* `claude respawn <id>`

This allows Claude’s own supervisor to own a persistent session while a terminal attaches to it. It is a Claude-specific runtime model, not a generic ACP attachment mechanism.

#### Remote Control

`claude remote-control` exposes a Claude Code session for control from Claude.ai or the Claude application. It is another native control surface and does not expose a general ACP endpoint.

## Key findings

### Native versus adapter distinction matters

Several major providers are reachable through ACP only by using a separate adapter:

* Claude Code through `claude-agent-acp`;
* Codex through `codex-acp`;
* Pi through `pi-acp`.

Operational consequences include:

* Adapter versions and provider versions advance independently.
* Compatibility must be verified as a version pair.
* An adapter can lag behind changes to the underlying CLI, SDK, or native protocol.
* The adapter owns or launches the ACP-visible runtime.
* Authentication is mediated by the adapter, while the underlying provider still owns credentials and login state.
* Adapter process health and underlying-agent health are separate concerns.
* Adapter deprecation does not imply provider deprecation.

### Persisted resume is not live attachment

ACP `loadSession` or `resumeSession` capability means that stored conversation state can be reopened.

It does not necessarily mean:

* another client can join the same active process;
* two clients can concurrently control the session;
* prompts can be injected into an active turn;
* a normal CLI or IDE session can be converted into an ACP session after startup.

These must be represented as separate capabilities.

### ACP and native control transports can coexist

Codex demonstrates a useful separation:

```text
ACP client
    │
    ▼
codex-acp
    │
    ▼
Codex App Server
```

For generic ACP execution, AUDiaGentic can own `codex-acp`.

For shared control with a human-facing terminal, AUDiaGentic can instead connect directly to a Codex App Server also used by the remote Codex TUI.

Claude has a different split:

```text
ACP client
    │
    ▼
claude-agent-acp
    │
    ▼
Claude Agent SDK session
```

For an existing Claude Code TUI, Channels provide inbound event injection, while Claude’s background-session and Remote Control features provide other provider-specific control models.

### ACP roles

Providers can occupy one or more roles:

1. **ACP agent** — the product or an adapter exposes an agent that an ACP client can drive.
2. **ACP consumer** — the product hosts or drives ACP agents.
3. **ACP adapter target** — a product is wrapped by a separate ACP agent package.
4. **Native externally controlled agent** — the provider offers a non-ACP server, channel, daemon, or attachment interface.
5. **Neither** — no ACP or relevant native external-control mechanism has been established.

A provider can occupy several roles. For example:

* Codex is an adapter target and also has a native App Server.
* Claude is an adapter target and also has Channels, Remote Control, and background sessions.
* Zed is an ACP consumer.
* OpenHands Agent Canvas is an ACP consumer.

### Registry coverage limitation

Absence from the ACP registry means:

* no registered ACP agent was found;
* the product may still have an unregistered adapter;
* the product may expose a different programmatic control interface;
* the product may consume ACP without acting as an ACP agent.

Accordingly, `No registered agent` is more accurate than `No support` unless provider-specific investigation confirms that no implementation exists.

## Capability-model implications

ACP support should not be represented by one boolean.

Within AUDiaGentic this must align with the existing provider standards:

* `capability_facts` are evidence records. They can say "this provider has a
  native ACP agent", "this provider is wrapped by an ACP adapter", or "this
  provider has a native live-control surface". They do not authorize execution.
* `automation_capabilities` are MA20 provider automation families. ACP execution
  should not be added there unless a provider family has a frozen payload/result
  contract and an explicit registered implementation. Generic "supports ACP" is
  not a managed-config or lifecycle automation family.
* Provider descriptors own provider facts and launch mechanics. Foundation ACP
  owns only protocol framing, bounded event normalization, cancellation,
  permissions, and process lifecycle.
* Agents/session orchestration owns profile selection, retries, run records,
  worker scoring, sparse monitoring, and continuation/stop policy.
* Runtime capability probes must validate behavior. Registry metadata and docs
  are evidence, not proof of local execution behavior.
* Generic capability code must never branch on provider names. Provider-specific
  details belong in descriptors, provider adapters, or explicit registered
  control handlers. A capability can ask "does this descriptor declare a
  verified ACP launch binding with these semantics?", not "is this provider
  Codex/OpenCode/Claude/Qwen?".

### Standards-aligned capability layers

Use separate records for separate claims:

| Layer | Question answered | AUDiaGentic owner | Execution authority? |
| --- | --- | --- | --- |
| Provider evidence fact | What has been documented or observed about this provider? | provider descriptor `capability_facts` / MA19 evidence | No |
| ACP launch binding | How does AUDiaGentic start a provider-owned ACP process? | provider adapter launch builder | Only after code registration |
| Foundation ACP transport | How are ACP frames normalized and bounded? | foundation execution/session transport | Protocol only, provider-agnostic |
| Agent session orchestration | Which profile/model/run should be launched and monitored? | agents/session gateway | Yes |
| Native live control | Can another process attach, steer, inject, interrupt, or share clients? | provider-specific control adapter | Only if separately registered |

This means a provider can have verified `capability_facts` for ACP but still be
unavailable for execution until there is a launch builder or registered session
adapter. Conversely, a provider can have a native control transport such as Codex
App Server or Claude Channels without that being represented as ACP.

### Generic capability doctrine

ACP capability handling must be capability-driven:

* Generic code reads typed declarations and probe results; it does not know
  provider names, executable names, adapter package names, or native-control
  product vocabulary.
* Provider-specific launch commands, environment shaping, config overrides,
  adapter package names, session-id translation, and native-control methods live
  behind provider adapters or registered handlers.
* Runtime decisions use explicit capability predicates, for example
  `supports_acp_launch`, `session_owner == "audiagentic"`,
  `active_turn_steer == true`, or `concurrent_clients == false`.
* Missing or unverified capabilities default to unsupported/unknown, never to
  provider-name heuristics.
* New generic semantics require schema/test additions before any provider opts
  in; adding a provider must not require editing generic orchestration logic.

### Capability fact naming

Capability fact IDs should stay narrow and stable. Suggested IDs:

| Capability fact ID | Meaning |
| --- | --- |
| `acp-agent-native` | Provider binary natively exposes an ACP agent endpoint. |
| `acp-agent-adapter` | Separate package exposes the provider through ACP. |
| `acp-consumer` | Product can host/drive ACP agents but is not itself an ACP agent. |
| `acp-session-persistence` | ACP path can list/load/resume/delete stored sessions. |
| `native-live-control` | Non-ACP provider surface can share, attach, steer, inject, or interrupt live sessions. |
| `native-inbound-channel` | Non-ACP channel/event bridge can inject messages into an already-running session. |

`subject` should resolve to a descriptor field where the repository has a
structured field. For facts that intentionally describe upstream behavior not
yet represented in the descriptor, use `external:<stable-subject>` with a
specific `fact_anchor`. This matches the current `ProviderCapabilityFact`
validator and prevents evidence prose from becoming hidden execution state.

### Descriptor shape: evidence first, runtime later

A first pass should use capability facts, for example:

```yaml
capability_facts:
  - capability_id: acp-agent-native
    subject: "external:acp-agent"
    mechanism: "<provider-declared ACP launch over stdio>"
    constraints:
      - "AUDiaGentic owns the ACP-created process/session."
      - "Live attachment to an independently started TUI is not implied."
    limitations:
      - "Runtime behavior must be verified by local probe."
    support_assessment: verified
    action_needed: null
    evidence:
      evidence_tier: execution
      tool_version: "<verified tool or adapter version>"
      fact_anchor: "<provider evidence document or registry snapshot>"
      review_state: verified
```

Only after the runtime contract is frozen should provider execution expose a
separate launch/runtime declaration. That declaration should be minimal and
composition-owned, similar to existing descriptor-backed mechanisms:

```yaml
execution_transports:
  acp:
    launch:
      kind: native-agent | adapter
      registry_id: "<registry id when present>"
      command: ["<executable-or-adapter>", "<acp-args>"]
    session_semantics:
      owner: audiagentic
      persisted_resume: unverified | supported | unsupported
      live_attach: unsupported
      active_turn_steer: unsupported
    evidence:
      probe_id: acp-smoke/v1
      last_verified_tool_version: "<verified tool or adapter version>"
```

The exact field name may differ when implemented. The standard is the important
part: this is not a free-form capability blob, and it is not an
`automation_capabilities` entry unless the corresponding code path is explicitly
registered and tested.

A provider descriptor should be able to express at least:

```yaml
protocols:
  acp:
    agent:
      supported: true
      implementation: native | adapter
      registry-id: codex-acp
      launch-command:
        - npx
        - -y
        - "@agentclientprotocol/codex-acp"

    consumer:
      supported: false

sessions:
  persisted:
    list: true
    load: true
    resume: true
    fork: false
    delete: true

  live:
    attach: false
    concurrent-clients: false
    inject-new-turn: false
    steer-active-turn: false
    interrupt-active-turn: true

control:
  native:
    kind: codex-app-server
    transport:
      - stdio
      - websocket
    shared-session: true
    inject-new-turn: true
    steer-active-turn: true
    interrupt-active-turn: true
```

A provider with a non-ACP inbound channel could instead declare a separate
native-control capability:

```yaml
control:
  native:
    kind: <provider-native-channel-kind>
    shared-session: true
    external-event-injection: true
    request-response-bridge: true
    requires-session-start-flag: true
    maturity: research-preview
```

Exact schema naming should follow the provider capability standards, but these concepts should remain distinct.

### Runtime probe contract

Every executable ACP claim should have a small probe result that is stored as
evidence, not guessed from metadata:

1. launch process;
2. initialize ACP session;
3. run a no-edit prompt;
4. verify streamed event kinds normalize into the frozen event vocabulary;
5. verify exactly one terminal result is returned from `AcpResult`;
6. close and verify the root process tree is gone;
7. record adapter/provider version, registry id, session id shape, event counts,
   dropped event count, and cleanup result.

Optional deeper probes can cover persisted resume, cancellation, permission
requests, concurrent clients, active-turn steering, and native session discovery.
Those deeper probes must not be inferred from the basic launch smoke.

## Implications for AUDiaGentic

* **OpenCode** and **Kilo Code** have strong native ACP launch paths with binary distributions.
* **Qwen Code** provides native ACP; test whether `--experimental-skills` is required for ACP operation or only enriches the session.
* Adapter-backed providers require lifecycle ownership for both the adapter and the underlying agent runtime.
* Do not infer live-session attachment from ACP session-load or resume support.
* Record which component created each session and which transport currently owns it.
* Prevent multiple transports from issuing turns concurrently unless the provider explicitly supports shared clients.
* Persist the provider-native session or thread identifier separately from the AUDiaGentic run identifier.
* Treat Codex App Server as a separate execution/control candidate from `codex-acp`.
* Treat Claude Channels as a separate inbound-control candidate from `claude-agent-acp`.
* For Claude Channels, hooks can provide outbound status while the channel provides inbound instructions, but correlation and loop prevention will be required.
* OpenHands is an ACP host rather than an ACP agent. Driving a child agent inside OpenHands is not equivalent to controlling OpenHands itself.
* Goose should be evaluated as a native ACP execution candidate.
* Remote WebSocket, channel, and permission-relay paths require explicit authentication, authorization, and trust-boundary review.
* Capability probes should test actual operations rather than accepting registry metadata as proof of runtime behaviour.

## Required verification tests

For each supported provider or adapter:

1. Start a new ACP session.
2. Execute a prompt and collect streamed events.
3. List the created session.
4. Stop the adapter or provider process.
5. Recreate the process and resume the session.
6. Confirm whether the provider session ID remains stable.
7. Attempt a second concurrent client.
8. Attempt to inject a new turn while another turn is active.
9. Attempt active-turn steering where claimed.
10. Exercise cancellation and permission requests.
11. Confirm adapter and child-process termination behaviour.
12. Confirm authentication works in interactive and headless environments.
13. Record whether sessions created by the native CLI or IDE are discoverable through the ACP adapter.
14. Record whether sessions created through ACP are discoverable through the native CLI or IDE.
15. Verify that persisted resume does not silently create a disconnected duplicate session.

## Evidence used for the control additions

* `agentclientprotocol/codex-acp/README.md`
* `agentclientprotocol/codex-acp/src/CodexAcpServer.ts`
* `agentclientprotocol/claude-agent-acp/README.md`
* `agentclientprotocol/claude-agent-acp/src/acp-agent.ts`
* OpenAI Codex App Server documentation
* Claude Code Channels documentation
* Claude Code CLI reference
