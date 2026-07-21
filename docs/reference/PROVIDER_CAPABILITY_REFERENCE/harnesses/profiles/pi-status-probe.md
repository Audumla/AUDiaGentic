<!-- PROBE: AS27 — Pi RPC capability status (read-only, local, no model calls) -->

# Pi RPC Capability Probe — AS27

**Probe date:** 2025-07-19  
**Installed version:** `@earendil-works/pi-coding-agent` **0.80.10**  
**Package location:** `C:\Users\mgs\AppData\Roaming\npm\node_modules\@earendil-works\pi-coding-agent\dist\`  
**Probe method:** Source-only inspection (CLI binary, `.js` dist, `.d.ts` types, `docs/rpc.md`). No model invocations. No code modifications.

---

## 1. `pi --mode rpc` — EXISTS and is fully implemented

| Question | Answer | Evidence |
|----------|--------|----------|
| Does `--mode rpc` exist? | **Yes** | `dist/cli/args.js` line ~33: accepts `"rpc"` as valid mode value. `dist/main.js` `resolveAppMode()` returns `"rpc"` for it. |
| Is there an RPC entry binary? | **Yes** | `dist/rpc-entry.js` — invokes `main(["--mode", "rpc", ...])`. Sets `process.title = "pi-rpc"`. Exported in `package.json` as `"./rpc-entry": "./dist/rpc-entry.js"`. |
| Does `--no-session` work with RPC? | **Yes** | `dist/cli/args.js`: `--no-session` sets `parsed.noSession = true`. In `main.js`, `createSessionManager()` calls `SessionManager.inMemory(cwd, ...)` when `noSession` is set — creates ephemeral (non-persisted) session. No conflict with RPC mode. |

**Exact invocation pattern:**
```bash
pi --mode rpc --no-session          # ephemeral RPC agent (no file persistence)
pi --mode rpc --session-dir /tmp    # explicit session dir
# Or use the dedicated entry point:
node dist/rpc-entry.js              # equivalent to pi --mode rpc
```

---

## 2. JSONL Message Schema

### Framing rules

- **LF-only** (`\n`) record delimiter. Not `\r\n`-split. Not `U+2028`/`U+2029`.
- Payload may contain any valid JSON (including Unicode separators inside strings).
- Input: optional `\r` stripped from end of line before parse.
- Serialization: `JSON.stringify(value) + "\n"` (strict, no trailing whitespace).

Source: `dist/modes/rpc/jsonl.js` — `serializeJsonLine()` and `attachJsonlLineReader()`.

### Command envelope (stdin → Pi)

```typescript
interface RpcCommand {
  type: string;       // command name (see §3)
  id?: string;        // optional correlation ID
  // ... command-specific fields
}
```

### Response envelope (stdout ← Pi)

```typescript
interface RpcResponse {
  type: "response";
  command: string;    // echoes the command `type`
  success: boolean;
  id?: string;        // echoes request `id` if provided
  data?: unknown;     // on success (omit if no payload)
  error?: string;     // on failure
}
```

### Event envelope (stdout ← Pi, streaming)

Events have **no** `id` field. They are `AgentSessionEvent` objects emitted via `session.subscribe()`.

---

## 3. RPC Command Types (28 total)

| Command | Key fields | Response data |
|---------|------------|---------------|
| `prompt` | `message`, `images?`, `streamingBehavior?` (`"steer"`\|`"followUp"`) | — (accepted, not result) |
| `steer` | `message`, `images?` | — |
| `follow_up` | `message`, `images?` | — |
| `abort` | — | — |
| `new_session` | `parentSession?` | `{ cancelled: boolean }` |
| `get_state` | — | full state object (model, thinkingLevel, isStreaming, sessionFile, sessionId, etc.) |
| `get_messages` | — | `{ messages: AgentMessage[] }` |
| `set_model` | `provider`, `modelId` | Model object |
| `cycle_model` | — | `{ model, thinkingLevel, isScoped }` or null |
| `get_available_models` | — | `{ models: Model[] }` |
| `set_thinking_level` | `level` | — |
| `cycle_thinking_level` | — | `{ level }` or null |
| `set_steering_mode` | `mode` (`"all"`\|`"one-at-a-time"`) | — |
| `set_follow_up_mode` | `mode` (`"all"`\|`"one-at-a-time"`) | — |
| `compact` | `customInstructions?` | CompactionResult |
| `set_auto_compaction` | `enabled` | — |
| `set_auto_retry` | `enabled` | — |
| `abort_retry` | — | — |
| `bash` | `command`, `excludeFromContext?` | BashResult |
| `abort_bash` | — | — |
| `get_session_stats` | — | stats with tokens/cost/contextUsage |
| `export_html` | `outputPath?` | `{ path }` |
| `switch_session` | `sessionPath` | `{ cancelled: boolean }` |
| `fork` | `entryId` | `{ text, cancelled }` |
| `clone` | — | `{ cancelled }` |
| `get_fork_messages` | — | `{ messages: [{ entryId, text }] }` |
| `get_entries` | `since?` (cursor) | `{ entries, leafId }` |
| `get_tree` | — | `{ tree, leafId }` |
| `get_last_assistant_text` | — | `{ text }` or `{ text: null }` |
| `set_session_name` | `name` | — |
| `get_commands` | — | `{ commands: [{ name, description, source, sourceInfo? }] }` |

Source: `dist/modes/rpc/rpc-mode.js` `handleCommand()` switch statement (lines 290–560).

---

## 4. Event Types

### Core Agent events (from `@earendil-works/pi-agent-core`)

| Event | Description | Key fields |
|-------|-------------|------------|
| `agent_start` | Agent begins processing | — |
| `agent_end` | One run completes (may retry) | `messages: AgentMessage[]`, `willRetry: boolean` |
| `turn_start` | New assistant turn begins | — |
| `turn_end` | Turn completes | `message`, `toolResults` |
| `message_start` | Message starts | `message: AgentMessage` |
| `message_update` | Streaming delta | `message`, `assistantMessageEvent` (delta type + data) |
| `message_end` | Message completes | `message` |
| `tool_execution_start` | Tool begins | `toolCallId`, `toolName`, `args` |
| `tool_execution_update` | Tool progress | `toolCallId`, `toolName`, `args`, `partialResult` |
| `tool_execution_end` | Tool completes | `toolCallId`, `toolName`, `result`, `isError` |

Source: `@earendil-works/pi-agent-core/dist/types.d.ts` — `AgentEvent` union type.

### Session-level events (from `AgentSession`)

| Event | Description | Key fields |
|-------|-------------|------------|
| `agent_settled` | Full run settled (no auto-retry/compaction pending) | — |
| `queue_update` | Steering/follow-up queue changed | `steering: string[]`, `followUp: string[]` |
| `compaction_start` | Compaction begins | `reason: "manual"\|"threshold"\|"overflow"` |
| `compaction_end` | Compaction completes | `reason`, `result`, `aborted`, `willRetry`, `errorMessage?` |
| `entry_appended` | New session entry appended | `entry: SessionEntry` |
| `session_info_changed` | Session name changed | `name?: string` |
| `thinking_level_changed` | Thinking level changed | `level: ThinkingLevel` |
| `auto_retry_start` | Auto-retry begins | `attempt`, `maxAttempts`, `delayMs`, `errorMessage` |
| `auto_retry_end` | Auto-retry ends | `success`, `attempt`, `finalError?` |

Source: `@earendil-works/pi-coding-agent/dist/core/agent-session.d.ts` — `AgentSessionEvent` union type.

### Extension UI events (RPC-mode specific)

| Event | Description | Key fields |
|-------|-------------|------------|
| `extension_ui_request` | Extension requests user interaction | `id`, `method`, method-specific fields |
| `extension_error` | Extension threw an error | `extensionPath`, `event`, `error` |

Extension UI request methods: `select`, `confirm`, `input`, `editor`, `notify`, `setStatus`, `setWidget`, `setTitle`, `set_editor_text`.

### Streaming delta types (inside `message_update.assistantMessageEvent`)

`start`, `text_start`, `text_delta`, `text_end`, `thinking_start`, `thinking_delta`, `thinking_end`, `toolcall_start`, `toolcall_delta`, `toolcall_end`, `done` (with `reason`), `error`.

---

## 5. Correlation Fields

| Field | Direction | Purpose |
|-------|-----------|---------|
| `id` (on command) | stdin → Pi | Request ID, echoed in response for correlation |
| `toolCallId` | events | Correlates `tool_execution_start` / `_update` / `_end` for a single tool call |
| `id` (on extension_ui_request) | stdout ← Pi | Correlation between request and client `extension_ui_response` on stdin |

---

## 6. Lifecycle Events

**Startup:** No explicit "ready" event is emitted. The process is ready when stdin/stdout pipes are open. The RpcClient waits 100ms after spawn as a heuristic.

**Per-run lifecycle:**
```
agent_start → [message_start → message_update* → message_end]*
            → [turn_start → tool_execution_start → tool_execution_update* → tool_execution_end]+
            → turn_end → agent_end (willRetry?) → [auto_retry_start → ... → auto_retry_end]
            → [compaction_start → compaction_end] → agent_settled
```

---

## 7. Cancellation / Close Semantics

### Agent-level abort (`abort` command)
- Calls `session.abort()` which calls the underlying `agent.abort()`.
- Aborts the current LLM stream via `AbortSignal`.
- Returns `{"type":"response","command":"abort","success":true}`.

### Bash abort (`abort_bash` command)
- Calls `session.abortBash()`.

### Process-level shutdown

**Graceful (stdin EOF):**
1. stdin `"end"` event triggers `onInputEnd()` → calls `shutdown(0)`.
2. `shutdown()`: unsubscribes events, calls `runtimeHost.dispose()`, detaches input, pauses stdin, flushes stdout, `process.exit(0)`.

**SIGTERM:**
- Kills tracked detached child processes, then calls `shutdown(143, "SIGTERM")`.

**SIGHUP (non-Windows):**
- Calls `shutdown(129, "SIGHUP")`. Stdout is **not** flushed on SIGHUP.

**Extension-initiated shutdown:**
- Extension can call its `shutdownHandler()`, which sets `shutdownRequested = true`.
- Checked after each command and when `agent_settled` fires.
- Calls `shutdown(0)` — graceful exit.

**Idempotency:** `shutdown()` sets `shuttingDown` flag; re-entry calls `process.exit(exitCode)` directly.

---

## 8. Permission / Terminal Events in RPC Mode

### Permissions
Pi does **not** have a dedicated permission event type. Tool permission gating is handled through:
- Extension UI `confirm` dialogs (via `extension_ui_request` with `method: "confirm"`).
- `beforeToolCall` / `afterToolCall` hooks on the Agent level.

### Terminal input
Not supported in RPC mode. The `onTerminalInput()` method in the extension UI context returns a no-op function (`() => {}`).

---

## 9. Gateway Isolation Usability

### Can Pi be used through a gateway/proxy? **Yes, with caveats.**

| Concern | Assessment |
|---------|------------|
| **Stdin/stdout JSONL protocol** | Well-defined, strict, documented. LF-only framing. Suitable for pipe-based or subprocess-based gateway. |
| **No session persistence needed** | `--no-session` creates in-memory session — no filesystem I/O for session storage. |
| **Process isolation** | Each RPC invocation is a separate Node.js process. Can be spawned per-request with full isolation. |
| **Extension UI round-trips** | Extensions that require user interaction (confirm/select/input/editor) block waiting for client response on stdin. Gateway must relay these bidirectionally. |
| **Bash execution** | `bash` command spawns subprocesses from within the Pi process. These are tracked and killed on SIGTERM/SIGHUP. If Pi runs in a container, bash commands run in that container's context. |
| **No HTTP/RPC transport** | Only JSONL over stdin/stdout. No built-in HTTP server or WebSocket support. Gateway must implement the transport layer (subprocess or pipe-based). |
| **`pi-acp` separate package?** | **Does not exist.** Only `@earendil-works/pi-coding-agent` is installed. The RPC protocol is part of this single package. No separate ACP binary. |
| **Sdk alternative** | `AgentSession` can be imported directly from the npm package for in-process use (no subprocess needed). `RpcClient` class also available for typed programmatic access. |

### Isolation considerations for AS27 gateway:

1. **Process-per-request model:** Spawn Pi with `--mode rpc --no-session` per API call. No cross-request state leakage.
2. **Extension UI relay required:** If extensions use `confirm`/`select` dialogs, the gateway must forward `extension_ui_request` to the caller and relay the response back. If the gateway cannot support this, extensions that require interactivity will time out (if `timeout` is set) or block indefinitely.
3. **Bash sandboxing:** Pi's bash tool runs commands in the process's working directory with the process's environment. A container or sandboxed environment is needed for isolation.
4. **Timeout management:** The gateway must implement its own timeouts — Pi has no built-in request-level timeout in RPC mode.
5. **Graceful shutdown:** Send `abort` command + SIGTERM for clean termination. Pi handles SIGTERM with child process cleanup.

---

## 10. RpcClient API (in-process alternative)

The package exports `RpcClient` from `@earendil-works/pi-coding-agent/modes/index.js` with these methods:

```typescript
class RpcClient {
  async start(): Promise<void>;        // spawn RPC process
  async stop(): Promise<void>;         // SIGTERM + wait (1s timeout, then SIGKILL)
  async prompt(message, images?): Promise<void>;
  async steer(message, images?): Promise<void>;
  async followUp(message, images?): Promise<void>;
  async abort(): Promise<void>;
  async newSession(parentSession?): Promise<{ cancelled: boolean }>;
  async getState(): Promise<...>;
  async setModel(provider, modelId): Promise<Model>;
  async cycleModel(): Promise<...>;
  async getAvailableModels(): Promise<{ models: Model[] }>;
  async setThinkingLevel(level): Promise<void>;
  async cycleThinkingLevel(): Promise<...>;
  async setSteeringMode(mode): Promise<void>;
  async setFollowUpMode(mode): Promise<void>;
  async compact(customInstructions?): Promise<...>;
  async setAutoCompaction(enabled): Promise<void>;
  async setAutoRetry(enabled): Promise<void>;
  async abortRetry(): Promise<void>;
  async bash(command): Promise<BashResult>;
  async abortBash(): Promise<void>;
  async getSessionStats(): Promise<...>;
  async exportHtml(outputPath?): Promise<{ path }>;
  async switchSession(sessionPath): Promise<{ cancelled }>;
  async fork(entryId): Promise<{ text, cancelled }>;
  async clone(): Promise<{ cancelled }>;
  async getForkMessages(): Promise<{ messages }>;
  async getEntries(since?): Promise<{ entries, leafId }>;
  async getTree(): Promise<{ tree, leafId }>;
  async getLastAssistantText(): Promise<{ text }>;
  async setSessionName(name): Promise<void>;
  async getMessages(): Promise<{ messages }>;
  async getCommands(): Promise<{ commands }>;
  async waitForIdle(timeout?): Promise<void>;
  async collectEvents(predicate, timeout?): Promise<AgentEvent[]>;
  async promptAndWait(message, images?, timeout?): Promise<AgentMessage[]>;
  async send(command): Promise<RpcResponse>;  // low-level: send arbitrary command
}
```

---

## 11. Recommendation

### **Recommendation B: Usable with gateway adaptation layer**

Pi's RPC mode is fully implemented, well-documented, and suitable for gateway integration. The JSONL protocol over stdin/stdout is clean and strict. However:

- **Not zero-effort:** No built-in HTTP/WebSocket transport. Gateway must spawn subprocess and pipe JSONL.
- **Extension UI relay is required** for full functionality — dialogs block on stdin responses.
- **No separate `pi-acp` package** — the RPC protocol is part of the main package only.
- **Sandboxing for bash** must be handled externally (container or restricted environment).

### Recommended integration pattern:

```
Gateway API → [subprocess: pi --mode rpc --no-session --provider X --model Y]
               ↑ stdin: JSONL commands           ↓ stdout: JSONL events/responses
             Gateway pipes JSONL bidirectionally
```

For in-process integration (Node.js/TypeScript), prefer `AgentSession` or `RpcClient` over subprocess spawning.

---

*Probe completed. No code modified. No model invocations performed.*
