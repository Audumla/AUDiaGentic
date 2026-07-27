# Provider → Hindsight Installation Map

## Canonical documented installation methods

**Audit date:** 27 July 2026  
**Purpose:** Document the complete installation method published by Hindsight and each harness, rather than forcing every provider through AUDiaGentic's current capability-family preference order.

---

## Decision

The earlier map is **not correct as a canonical installation guide**. It is partly a map of what AUDiaGentic's current provisioning abstraction happens to select. Those are different things.

The canonical installation order should be:

1. **Use the dedicated Hindsight integration when Hindsight publishes one.**
   A dedicated wrapper, plugin, or hook installer normally provides more than MCP: automatic recall, automatic retain, bank selection, transcript handling, context injection, rules, compaction handling, status, and safe uninstall.
2. **Otherwise use the harness's native remote Streamable HTTP MCP support.**
3. **Where an MCP-only harness has an instruction/rules surface, install both the MCP server and an owned memory-use instruction.** Merely exposing `recall` and `retain` tools does not make their use deterministic.
4. **Use guidance-only only when the harness has neither a published Hindsight integration nor a usable managed extension surface.**

This changes the meaning of several rows in the earlier map:

- Aider is not guidance-only.
- Claude Code should use the Hindsight plugin, not a raw MCP entry.
- Cline should use lifecycle hooks, not MCP.
- OpenCode should use the Hindsight plugin, not raw MCP.
- Continue is a context-provider integration with optional MCP + rules, not simply a managed MCP entry.
- GitHub Copilot, OpenHands, and Roo Code require an MCP entry **and** an instruction/rules artifact.
- Goose is not stdio-only and its documented config path is not `.goose/config.yaml`.
- Qwen Code does not use project `.mcp.json`.
- Gemini CLI and Gemini Spark/Antigravity are different products and must not share one upstream integration reference.
- Pi requires an MCP adapter extension before any `.mcp.json` entry can work.

---

## Common Hindsight connection contract

### Hindsight Cloud

The current Hindsight MCP documentation recommends a bank-scoped endpoint:

```text
https://api.hindsight.vectorize.io/mcp/<BANK_ID>/
```

For API-key clients:

```http
Authorization: Bearer <HINDSIGHT_API_KEY>
```

With a bank-scoped URL, `X-Bank-Id` is unnecessary. The root endpoint remains valid for multi-bank use:

```text
https://api.hindsight.vectorize.io/mcp
```

When using the root endpoint, set:

```http
X-Bank-Id: <BANK_ID>
```

Do not make the root `/mcp` plus `X-Bank-Id` form the universal default. Hindsight now documents single-bank URL mode as the recommended mode for project-specific agents.

### Local Hindsight MCP

The currently documented local MCP server is an HTTP server, not a generic `hindsight-mcp --base-url ...` stdio command:

```bash
HINDSIGHT_API_LLM_API_KEY=<LLM_API_KEY> \
  uvx --from hindsight-api hindsight-local-mcp
```

It exposes:

```text
http://localhost:8888/mcp/
http://localhost:8888/mcp/<BANK_ID>/
```

For Ollama:

```bash
HINDSIGHT_API_LLM_PROVIDER=ollama \
HINDSIGHT_API_LLM_MODEL=llama3.2 \
  uvx --from hindsight-api hindsight-local-mcp
```

### Automatic memory versus tool availability

There are three distinct capability levels:

| Level | What is installed | Result |
| --- | --- | --- |
| Deterministic integration | Hooks or a host plugin intercept lifecycle events | Recall/retain happens automatically at documented events. |
| Rule-guided MCP | MCP server plus a persistent host instruction/rule | The model is instructed to call memory tools, but compliance remains agent-driven. |
| Bare MCP | MCP server only | Tools are available; the agent may not call them unless explicitly prompted. |

AUDiaGentic status should expose this distinction. `registered=true` is not enough to describe whether memory is automatic.

---

## Summary map

| Provider | Canonical documented route | Automatic behavior | Main installed artifacts | Earlier-map correction |
| --- | --- | --- | --- | --- |
| Aider | `hindsight-aider` wrapper | Recall before session; retain after exit | Wrapper config and generated read-only memory file | **Not guidance-only** |
| Antigravity / Gemini Spark | Native remote MCP | Agent-planned only; no third-party hooks | Hosted `antigravity.yaml` or desktop MCP JSON | M1 broadly valid, but incomplete and endpoint/auth details need correction |
| Claude Code | `hindsight-memory` marketplace plugin | Hooks + tools + skill; automatic recall/retain | Claude plugin data plus `~/.hindsight/claude-code.json` | **Plugin must win over raw MCP** |
| Cline | `hindsight-cline` hook installer | Deterministic task/prompt recall and task-end retain | Cline hook scripts and Hindsight config/state | **Managed MCP route is wrong** |
| Codex | Hindsight's Codex installer | Deterministic hook-based recall/retain | Hook scripts plus `~/.hindsight/codex*.json` | H1 concept is sound; use the published installer contract |
| Continue | `hindsight-continue` HTTP context provider; optional MCP + rule | `@hindsight` on demand; agent-driven automation when MCP/rule added | Adapter process, `config.yaml`; optional MCP/rules | **MCP-only is incomplete** |
| GitHub Copilot | `hindsight-copilot init` | Rule-guided MCP | `.vscode/mcp.json` + `.github/copilot-instructions.md` | Path and lifecycle are wrong/incomplete |
| Gemini CLI | Native Gemini CLI MCP | Agent-planned unless separately instructed | `~/.gemini/settings.json` or `.gemini/settings.json` | Do not cite Gemini Spark; project path is wrong in earlier map |
| Goose | Native remote Streamable HTTP extension | Agent-planned | Goose global `config.yaml` extension | **Not stdio-only; path is wrong** |
| Local OpenAI Bridge | No Hindsight harness integration | None | None | Guidance-only remains appropriate |
| OpenCode | `@vectorize-io/opencode-hindsight` plugin | Automatic session recall, idle retain, compaction integration | `opencode.json` plugin entry and optional Hindsight config | **Plugin must win over raw MCP** |
| OpenHands | `hindsight-openhands init` | Rule-guided MCP | `config.toml` + `AGENTS.md` | MCP-only is incomplete; Docker uses UI settings |
| Pi Coding Agent | Install `pi-mcp-adapter`, then native MCP config | Agent-planned unless a separate instruction is added | Pi extension + `.mcp.json` or another adapter config layer | Adapter prerequisite missing; Pi Hindsight host block is AUDiaGentic-specific |
| Plandex | No published Hindsight integration or documented MCP route found | None | None | Guidance-only remains appropriate |
| Qwen Code | Native Qwen MCP | Agent-planned unless separately instructed | `~/.qwen/settings.json` or `.qwen/settings.json` | Path and refresh behavior are wrong |
| Roo Code | `hindsight-roo-code install` | Rule-guided MCP | `.roo/mcp.json` + `.roo/rules/hindsight-memory.md` | Root `.mcp.json` is wrong and rule was omitted |

---

# Provider details

## 1. Aider (`aider`)

### Canonical route

Use Hindsight's dedicated `hindsight-aider` wrapper. Aider has neither an MCP client nor per-prompt lifecycle hooks. The wrapper uses Aider's read-only context-file support before a session and its chat-history file after the session.

### Install

```bash
python -m pip install hindsight-aider aider-chat
export HINDSIGHT_API_TOKEN=<HINDSIGHT_CLOUD_KEY>
```

For self-hosted Hindsight:

```bash
export HINDSIGHT_API_URL=http://localhost:8888
```

Run the wrapper in place of `aider`:

```bash
hindsight-aider
hindsight-aider -m "add retry logic"
hindsight-aider src/app.py tests/
```

All normal Aider arguments pass through.

### Installed/runtime artifacts

- `~/.hindsight/aider.json` — optional persistent integration settings.
- `.aider.hindsight-memory.md` — generated recall result loaded with Aider's `--read` option.
- Aider's normal chat-history file — the wrapper reads only the slice written by the current session and retains it after Aider exits.
- The bank defaults to the Git repository name.

### Behavior

- **Recall:** once before each Aider process/session.
- **Retain:** once after Aider exits.
- **Mid-session recall:** unavailable because Aider does not expose a suitable hook or MCP client.
- **Automation level:** deterministic at session boundaries, provided the user launches `hindsight-aider` rather than `aider`.

### Manage/update

Update the package with the selected Python package manager. Reconcile `~/.hindsight/aider.json` or environment variables; do not write Aider MCP configuration because none exists.

### Verify

Run `hindsight-aider` in a Git repository and confirm the generated `.aider.hindsight-memory.md` is loaded as a read-only context file. Confirm the completed session appears in the configured Hindsight bank.

### Uninstall

Hindsight does not publish a dedicated Aider uninstall command. Stop invoking the wrapper and remove its package:

```bash
python -m pip uninstall hindsight-aider
```

Only remove `~/.hindsight/aider.json` and `.aider.hindsight-memory.md` when explicitly requested. Do not remove Aider or its chat history.

### AUDiaGentic correction

The guidance-only row is wrong. The present capability taxonomy needs a wrapper/launcher family, for example `managed-wrapper`, or a dedicated provider recipe that installs the package and changes the invocation command without pretending it is MCP.

### Sources

- [Hindsight: Aider integration](https://hindsight.vectorize.io/sdks/integrations/aider)
- [Hindsight Aider package README](https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/aider)

---

## 2. Antigravity / Gemini Spark (`antigravity`)

### Canonical route

Use Spark's/Antigravity's native remote MCP surface. Hindsight code cannot run inside Spark's cloud agent loop, so there are no automatic third-party hooks.

### Cloud-hosted agent configuration

Hindsight documents an `antigravity.yaml` manifest fragment:

```yaml
tools:
  mcp_servers:
    - name: hindsight
      endpoint: https://api.hindsight.vectorize.io/mcp
      auth: bearer
      description: >
        Long-term memory across sessions. Call recall whenever the user
        references past work, decisions, or preferences from earlier
        conversations. Call retain whenever the user shares a fact,
        preference, or decision worth remembering.
```

Important: Hindsight's example itself says this manifest shape follows the I/O 2026 developer guide and may need adjustment when Google publishes a formal schema. Treat hosted-manifest mutation as provisional, not a permanently stable writer contract.

### Antigravity desktop/IDE configuration

Documented file:

```text
~/.gemini/antigravity/mcp_config.json
```

Documented example:

```json
{
  "mcpServers": {
    "hindsight": {
      "serverUrl": "https://api.hindsight.vectorize.io/mcp",
      "headers": {
        "Authorization": "Bearer <HINDSIGHT_API_KEY>"
      }
    }
  }
}
```

The integration-specific example currently uses the root multi-bank endpoint. Hindsight's generic MCP documentation now recommends bank-scoped URLs. AUDiaGentic should support both forms and avoid silently changing a working integration-specific example without a compatibility test.

### Self-hosted constraint

Spark runs on Google's infrastructure. A local-only URL is not reachable. Hindsight documents:

1. Public HTTPS exposure for the self-hosted Hindsight MCP server.
2. A Cloudflare Tunnel or equivalent.
3. `cloudflare-oauth-proxy`, because Spark's MCP client speaks OAuth 2.1.

### Behavior

- `recall`, `retain`, and related tools are available.
- No hook-based prompt injection.
- No transcript interception at turn end.
- Calls are planner/model initiated.

### Verify

Prompt Spark with an explicit memory task, for example asking it to recall a past decision or remember a stated preference, and confirm the corresponding MCP tool call.

### Uninstall

Remove only the Hindsight server block from the applicable manifest or MCP JSON. Do not remove other MCP servers or Antigravity configuration.

### AUDiaGentic correction

Managed MCP is reasonable for desktop Antigravity, but the row must include:

- the hosted `antigravity.yaml` route;
- the provisional status of that schema;
- OAuth/public-HTTPS requirements for self-hosting;
- agent-planned rather than automatic behavior;
- exact `serverUrl` shape rather than assuming a generic `url` schema.

### Sources

- [Hindsight: Gemini Spark integration](https://hindsight.vectorize.io/sdks/integrations/gemini-spark)
- [Hindsight Antigravity manifest example](https://github.com/vectorize-io/hindsight/blob/main/hindsight-integrations/gemini-spark/manifest.example.yaml)
- [Hindsight Antigravity desktop MCP example](https://github.com/vectorize-io/hindsight/blob/main/hindsight-integrations/gemini-spark/mcp_config.example.json)

---

## 3. Claude Code (`claude`)

### Canonical route

Use the official Hindsight Claude Code marketplace plugin. Do not reduce this integration to a raw Hindsight MCP server. The plugin combines lifecycle hooks, an MCP knowledge server, a skill, bank resolution, daemon management, and configuration.

### Install

```bash
claude plugin marketplace add vectorize-io/hindsight
claude plugin install hindsight-memory
```

Choose one connection mode.

#### Local auto-managed Hindsight daemon

Set a supported LLM provider for memory extraction:

```bash
export OPENAI_API_KEY=<KEY>
# or
export ANTHROPIC_API_KEY=<KEY>
# or, for personal/local use, let the plugin use Claude Code itself:
export HINDSIGHT_LLM_PROVIDER=claude-code
```

The plugin can start and stop `hindsight-embed` with `uvx`.

#### External Hindsight server

```bash
mkdir -p ~/.hindsight
cat > ~/.hindsight/claude-code.json <<'JSON'
{
  "hindsightApiUrl": "https://api.hindsight.vectorize.io",
  "hindsightApiToken": "<HINDSIGHT_API_KEY>"
}
JSON
```

Then start Claude Code:

```bash
claude
```

### Plugin components

| Component | Claude event/surface | Purpose |
| --- | --- | --- |
| `session_start.py` | `SessionStart` hook | Health check and daemon readiness |
| `recall.py` | `UserPromptSubmit` hook | Query and inject relevant memory as `additionalContext` |
| `retain.py` | `Stop` hook | Retain transcript asynchronously |
| `session_end.py` | `SessionEnd` hook | Clean up an auto-managed daemon |
| `mcp_server.py` | Plugin MCP server | Expose `agent_knowledge_*` tools |
| `create-agent` | Plugin skill | Create a subagent with an isolated memory bank |

Python dependencies are bootstrapped into a private plugin venv under `${CLAUDE_PLUGIN_DATA}/venv`.

### Configuration

Primary user config:

```text
~/.hindsight/claude-code.json
```

Loading order:

1. plugin defaults;
2. plugin `settings.json`;
3. `~/.hindsight/claude-code.json`;
4. environment variables.

The plugin supports static or dynamic bank IDs, project/worktree resolution, recall budget and token limits, retain frequency, role selection, tags, knowledge tools, and local daemon settings.

### Manage/update

Use Claude's plugin manager. Marketplace plugins can be updated through Claude's normal plugin workflow. `/reload-plugins` applies plugin changes to the current session on supported Claude Code versions.

### Verify

- Inspect the installed plugin with `/plugin`.
- Confirm the Hindsight hooks and plugin MCP server load after `claude` starts.
- Submit a prompt and check that recall context is injected.
- After a response, confirm the session is retained.
- Confirm `agent_knowledge_*` tools are exposed.

### Uninstall

```bash
claude plugin uninstall hindsight-memory --prune
```

Claude's plugin manager removes the plugin data directory when the last installed scope is removed unless `--keep-data` is supplied. Treat `~/.hindsight/claude-code.json` as user-owned persistent configuration unless the user explicitly requests its deletion.

### AUDiaGentic correction

`plugin-entry` should take precedence for Claude Code. A raw managed MCP entry omits automatic per-prompt recall, automatic retain, daemon management, dynamic bank selection, and the subagent skill.

### Sources

- [Hindsight: Claude Code integration](https://hindsight.vectorize.io/sdks/integrations/claude-code)
- [Claude Code plugin reference](https://code.claude.com/docs/en/plugins-reference)

---

## 4. Cline (`cline`)

### Canonical route

Use `hindsight-cline`, which installs Cline lifecycle hooks. Hindsight explicitly documents this as a **no-MCP-required** integration.

### Prerequisites

- Python 3.
- Hindsight Cloud or a running self-hosted Hindsight API.
- Hindsight's integration page currently states that the hooks run on macOS and Linux, not Windows.

### Install

```bash
python -m pip install hindsight-cline
cd <PROJECT>
hindsight-cline install \
  --api-url https://api.hindsight.vectorize.io \
  --api-token <HINDSIGHT_API_KEY>
```

Global install:

```bash
hindsight-cline install --global \
  --api-url https://api.hindsight.vectorize.io \
  --api-token <HINDSIGHT_API_KEY>
```

Then enable hooks in Cline:

```text
Settings → Features → Hooks
```

### Installed hooks

- `TaskStart` — recall using the task description.
- `UserPromptSubmit` — recall using each user prompt and append the prompt to task state.
- `TaskComplete` — retain accumulated task transcript and summary.
- `TaskCancel` — retain partial task state.

Project install destination documented by Hindsight:

```text
.clinerules/hooks/
```

Global destination documented by Hindsight:

```text
~/Documents/Cline/Rules/Hooks/
```

Persistent user config:

```text
~/.hindsight/cline.json
```

Task state:

```text
~/.hindsight/cline/state/
```

### Documentation conflict to preserve

Current Cline hook documentation lists global hooks under `~/Documents/Cline/Hooks/`, while the Hindsight README says `~/Documents/Cline/Rules/Hooks/`. Newer Cline configuration documentation also describes `~/.cline/`-based global resources.

Therefore AUDiaGentic should invoke `hindsight-cline install --global` rather than hard-code a global destination until the supported Cline/Hindsight versions are tested together. Record the resolved path in status.

### Verify

- Confirm all four installed hooks are visible/enabled in Cline.
- Start a task and inspect hook execution for `TaskStart`.
- Send another prompt and verify `UserPromptSubmit` recall.
- Complete or cancel the task and confirm retention.

### Uninstall

Project:

```bash
hindsight-cline uninstall
```

Global:

```bash
hindsight-cline uninstall --global
```

### AUDiaGentic correction

The `.cline/mcp.json` managed-MCP row is wrong for the canonical Hindsight integration. Cline should advertise a managed-hook or dedicated-installer capability. Status must also report unsupported-platform cases and whether hooks are enabled in Cline.

### Sources

- [Hindsight Cline integration README](https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/cline)
- [Cline lifecycle hooks](https://docs.cline.bot/customization/hooks)

---

## 5. Codex (`codex`)

### Canonical route

Use Hindsight's published Codex installer. It installs three pure-Python hook scripts and Hindsight configuration.

### Install

```bash
curl -fsSL https://hindsight.vectorize.io/get-codex | bash
```

The installer prompts for Hindsight Cloud versus local-daemon mode and writes the appropriate configuration.

### Installed behavior

| Hook | Event | Behavior |
| --- | --- | --- |
| `session_start.py` | `SessionStart` | Verify Hindsight is reachable |
| `recall.py` | `UserPromptSubmit` | Recall and emit `hookSpecificOutput.additionalContext` |
| `retain.py` | `Stop` | Read the transcript, strip injected memory tags, and retain asynchronously |

### Configuration

User override:

```text
~/.hindsight/codex.json
```

Plugin settings:

```text
~/.hindsight/codex/settings.json
```

Loading order:

1. built-in defaults;
2. plugin settings;
3. user config;
4. environment variables.

For a separately run local daemon:

```bash
uvx hindsight-embed
```

The Codex integration does **not** auto-start that daemon. With `hindsightApiUrl` empty, it connects to the configured local `apiPort`, default `9077`.

### Manage/update

Re-running the published installer is the canonical reconciliation route. AUDiaGentic may internally materialize equivalent owned scripts and hook entries, but it must preserve the installer contract, stable configuration, and unrelated Codex hooks.

### Verify

Start a new Codex session, submit a prompt, and confirm:

- SessionStart health check succeeds;
- recalled memory appears as additional context;
- Stop retains the turn/session;
- repeated session IDs update rather than duplicate the same retained session document.

### Uninstall

```bash
curl -fsSL https://hindsight.vectorize.io/get-codex | bash -s -- --uninstall
```

### AUDiaGentic correction

The hook-based classification is directionally correct. The map should identify the published installer as canonical and avoid asserting undocumented Codex internal files as upstream facts. Any AUDiaGentic-specific hook writer is an alternative implementation of the same contract, not the documented installation method itself.

### Source

- [Hindsight: Codex integration](https://hindsight.vectorize.io/sdks/integrations/codex)

---

## 6. Continue (`continue`)

### Canonical route

The primary documented integration is `hindsight-continue`, a local HTTP context-provider adapter. An optional Hindsight MCP server plus a Continue rule adds agent-mode recall/retain behavior.

### Install the context-provider adapter

```bash
python -m pip install hindsight-continue
export HINDSIGHT_API_KEY=<HINDSIGHT_API_KEY>
export HINDSIGHT_CONTINUE_BANK_ID=<PROJECT_BANK>
hindsight-continue
```

The adapter listens on:

```text
http://127.0.0.1:8123/
```

For self-hosted Hindsight:

```bash
export HINDSIGHT_API_URL=http://localhost:8888
```

### Register the context provider

Add this to Continue's `config.yaml`:

```yaml
context:
  - provider: http
    params:
      url: "http://127.0.0.1:8123/"
      title: hindsight
      displayTitle: Hindsight
      description: Recall long-term memory from Hindsight
```

Continue's current default local config is normally:

```text
~/.continue/config.yaml
```

On Windows:

```text
%USERPROFILE%\.continue\config.yaml
```

Use in chat:

```text
@hindsight <query>
```

### Optional automatic agent-mode route

Hindsight documents a second layer:

1. Add the Hindsight MCP server to Continue's MCP configuration.
2. Add a project rule under `.continue/rules/` instructing the agent to recall at task start and retain durable facts/decisions.

Continue currently discovers project MCP definitions under:

```text
.continue/mcpServers/
```

A JSON MCP definition can also be placed in that directory. The exact example assets are published in Hindsight's Continue integration directory.

### Behavior

- Context provider: precise, on-demand recall with `@hindsight`.
- MCP + rule: agent-driven recall/retain in Agent mode.
- Fully passive pre-prompt injection is unavailable because Continue does not expose a suitable pre-message hook.

### Manage/update

AUDiaGentic must supervise the `hindsight-continue` adapter process if it claims the context-provider route is installed. A static `config.yaml` entry without the adapter process is incomplete. MCP/rule artifacts should be independently owned and reconciled.

### Verify

- Confirm `hindsight-continue` is listening on port 8123.
- Type `@hindsight` in Continue and confirm returned context.
- For the optional MCP route, switch to Agent mode and confirm memory tools load and the rule is active.

### Uninstall

No dedicated uninstall command is published on the Hindsight integration page. Remove only:

- the Hindsight HTTP context-provider block;
- any Hindsight-owned MCP definition;
- the Hindsight-owned Continue rule;
- the `hindsight-continue` package if no longer required.

Do not remove unrelated Continue config, MCP servers, or rules.

### AUDiaGentic correction

A single managed-MCP row is incomplete. Continue needs either a `managed-context-provider`/managed-service capability or a compound recipe: adapter process + config, with optional MCP + rule.

### Sources

- [Hindsight: Continue integration](https://hindsight.vectorize.io/sdks/integrations/continue)
- [Continue configuration](https://docs.continue.dev/cli/configuration)
- [Continue rules](https://docs.continue.dev/customize/rules)
- [Continue MCP configuration](https://docs.continue.dev/customize/deep-dives/mcp)

---

## 7. GitHub Copilot in VS Code (`copilot`)

### Canonical route

Use `hindsight-copilot init`. It installs both the native VS Code MCP server and the persistent Copilot instruction that tells Agent mode how to use memory.

### Install

```bash
python -m pip install hindsight-copilot
cd <PROJECT>
hindsight-copilot init \
  --api-token <HINDSIGHT_API_KEY> \
  --bank-id <PROJECT_BANK>
```

For self-hosted Hindsight:

```bash
hindsight-copilot init \
  --api-url http://localhost:8888 \
  --bank-id <PROJECT_BANK>
```

### Installed artifacts

#### `.vscode/mcp.json`

```json
{
  "servers": {
    "hindsight": {
      "type": "http",
      "url": "https://api.hindsight.vectorize.io/mcp/<PROJECT_BANK>/",
      "headers": {
        "Authorization": "Bearer <HINDSIGHT_API_KEY>"
      }
    }
  }
}
```

VS Code uses `servers`, not `mcpServers`.

#### `.github/copilot-instructions.md`

The installer adds a Hindsight recall/retain instruction applied to workspace Copilot chats.

### Activate

1. Reload VS Code.
2. Open Copilot Chat.
3. Select Agent mode.
4. Start/enable the `hindsight` MCP server from the tools menu.

### Manage/status

```bash
hindsight-copilot status
```

If the target JSON contains comments that cannot be safely rewritten, `init` prints the snippet rather than overwriting it. `--print-only` is available for a non-mutating preview.

### Uninstall

```bash
hindsight-copilot uninstall
```

This removes the Hindsight server and its instruction block while preserving unrelated file content.

### AUDiaGentic correction

The destination is `.vscode/mcp.json`, not project root `.mcp.json`. Installing only the server is incomplete; `.github/copilot-instructions.md` is part of the documented capability.

### Sources

- [Hindsight Copilot integration README](https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/github-copilot)
- [Hindsight MCP: VS Code configuration](https://docs.hindsight.vectorize.io/mcp/)

---

## 8. Gemini CLI (`gemini`)

### Canonical route

There is no dedicated Hindsight Gemini CLI integration page. Use Gemini CLI's native MCP support with Hindsight's generic remote HTTP endpoint.

This is **not** the Gemini Spark/Antigravity integration.

### Install with Gemini CLI

Project scope:

```bash
gemini mcp add \
  --scope project \
  --transport http \
  --header "Authorization: Bearer <HINDSIGHT_API_KEY>" \
  hindsight \
  https://api.hindsight.vectorize.io/mcp/<BANK_ID>/
```

User scope:

```bash
gemini mcp add \
  --scope user \
  --transport http \
  --header "Authorization: Bearer <HINDSIGHT_API_KEY>" \
  hindsight \
  https://api.hindsight.vectorize.io/mcp/<BANK_ID>/
```

### Config destinations

- User: `~/.gemini/settings.json`
- Project: `.gemini/settings.json`

Gemini writes an `mcpServers` entry into the selected settings file.

### Instruction surface

Gemini CLI loads persistent instructions from:

- global `~/.gemini/GEMINI.md`;
- project/workspace `GEMINI.md` files.

No Hindsight-published Gemini CLI rule is currently documented. Therefore the canonical documented installation stops at MCP tool availability. An AUDiaGentic-authored recall/retain policy in `GEMINI.md` would be a project integration decision, not an upstream Hindsight installation fact.

### Verify

```bash
gemini mcp list
```

Inside Gemini CLI:

```text
/mcp
```

If the server was added while Gemini CLI was already running, restart it in the same project.

### Disable/remove

```bash
gemini mcp disable hindsight

gemini mcp remove --scope project hindsight
# or --scope user
```

### AUDiaGentic correction

- Do not cite the Gemini Spark integration as the Gemini CLI upstream reference.
- Use `.gemini/settings.json` for project scope, not an undifferentiated `.gemini/settings.json` description without scope.
- Treat any `GEMINI.md` memory policy as a separately owned artifact.
- Project-level deprecation/replacement by Antigravity is an AUDiaGentic registry decision, not evidence that Gemini CLI and Spark share a configuration contract.

### Sources

- [Gemini CLI MCP servers](https://geminicli.com/docs/tools/mcp-server/)
- [Gemini CLI `GEMINI.md` context](https://geminicli.com/docs/cli/gemini-md/)
- [Hindsight generic MCP integration](https://docs.hindsight.vectorize.io/mcp/)

---

## 9. Goose (`goose`)

### Canonical route

Use Goose's native remote Streamable HTTP extension. Goose is not stdio-only.

### Config destination

- macOS/Linux: `~/.config/goose/config.yaml`
- Windows: `%APPDATA%\Block\goose\config\config.yaml`

### Install through Goose UI/CLI

CLI:

```bash
goose configure
```

Then select:

```text
Add Extension → Remote Extension (Streamable HTTP)
```

Enter the Hindsight bank-scoped URL and authentication values.

Goose Desktop:

```text
Extensions → Add custom extension
```

### Direct config form

```yaml
extensions:
  hindsight:
    type: streamable_http
    name: hindsight
    enabled: true
    uri: "https://api.hindsight.vectorize.io/mcp/<BANK_ID>/"
    headers:
      Authorization: "Bearer <HINDSIGHT_API_KEY>"
    env_keys: []
    envs: {}
    timeout: 300
```

Goose documents `streamable_http` as a supported extension type and keeps SSE only for compatibility.

### Behavior

This is bare MCP unless the session/user provides an instruction to call memory tools. There is no dedicated Hindsight Goose hook/plugin documented. Default extension changes apply to future sessions; Goose can also change enabled extensions in the current session through its session UI/commands.

### Verify

- Inspect the extension in `goose configure` or Goose Desktop.
- Start a new session with the extension enabled.
- Explicitly ask Goose to call Hindsight `recall` and confirm the tool response.

### Uninstall

Disable the extension first, then remove it with Goose Desktop or:

```bash
goose configure
```

Select `Remove Extension`. Preserve all unrelated extension and provider settings.

### AUDiaGentic correction

The earlier row is materially wrong:

- destination is not `.goose/config.yaml`;
- Goose is not stdio-only;
- Streamable HTTP is the documented native route;
- refresh should be described in terms of current versus future Goose sessions, not a generic restart-required flag.

### Sources

- [Goose: using extensions](https://goose-docs.ai/docs/getting-started/using-extensions/)
- [Goose configuration files](https://goose-docs.ai/docs/guides/config-files/)

---

## 10. Local OpenAI Bridge (`local-openai`)

### Canonical route

No Hindsight integration is installed into an OpenAI-compatible endpoint bridge merely because it exposes a model API. Hindsight must be connected to the **agent/harness that owns the conversation and tool loop**, not to the model endpoint.

### Install/manage/uninstall

- Do not mutate the bridge.
- Report no Hindsight harness integration.
- Point the operator to the actual calling harness's integration method.
- Uninstall is a no-op because AUDiaGentic should own no bridge artifact.

### AUDiaGentic correction

Guidance-only remains appropriate. The status message should explain why: this provider is a model transport, not a host extension surface.

---

## 11. OpenCode (`opencode`)

### Canonical route

Use the official Hindsight OpenCode plugin. Raw MCP is a reduced alternative and should not win over the plugin.

### Install

Add to project `opencode.json` or global `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["@vectorize-io/opencode-hindsight"]
}
```

OpenCode auto-installs plugins listed in `plugin`; no separate `npm install` is required.

### Configure a local Hindsight server

```bash
export HINDSIGHT_API_URL=http://localhost:8888
opencode
```

### Configure Hindsight Cloud

```bash
export HINDSIGHT_API_URL=https://api.hindsight.vectorize.io
export HINDSIGHT_API_TOKEN=<HINDSIGHT_API_KEY>
opencode
```

Inline plugin configuration is also documented:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    ["@vectorize-io/opencode-hindsight", {
      "hindsightApiUrl": "https://api.hindsight.vectorize.io",
      "hindsightApiToken": "<HINDSIGHT_API_KEY>",
      "bankId": "<PROJECT_BANK>",
      "autoRecall": true,
      "autoRetain": true,
      "recallBudget": "mid",
      "retainEveryNTurns": 3
    }]
  ]
}
```

Persistent Hindsight config may be placed at:

```text
~/.hindsight/opencode.json
```

### Behavior

- Registers `hindsight_retain`, `hindsight_recall`, and `hindsight_reflect` tools.
- Recalls project memory at session creation and injects it into the system prompt.
- Retains the conversation on `session.idle` according to configured frequency.
- Before compaction, retains current conversation state and injects relevant memory into compaction context.
- Supports dynamic bank IDs.

### Manage/update

OpenCode manages the package declared in its plugin array. Reconcile the plugin entry without replacing other plugins. Plugin options, user config, and environment variables are separate configuration layers.

### Verify

- Start OpenCode after adding the plugin.
- Confirm the three Hindsight tools are registered.
- Start a new session and inspect recall behavior.
- Let the session become idle and confirm retention.
- Trigger/observe compaction and confirm memory preservation behavior.

### Uninstall

Remove only `@vectorize-io/opencode-hindsight` from the plugin array. Hindsight does not publish a dedicated uninstall command on the integration page. Preserve `~/.hindsight/opencode.json` unless explicit data/config deletion is requested.

### AUDiaGentic correction

The current preference rule that makes managed MCP beat `plugin-entry` is wrong for canonical Hindsight installation. The plugin is the full integration; MCP alone drops automatic recall, idle retention, and compaction handling.

### Source

- [Hindsight: OpenCode integration](https://hindsight.vectorize.io/sdks/integrations/opencode)

---

## 12. OpenHands (`openhands`)

### Canonical route

Use `hindsight-openhands init`. It installs a native Streamable HTTP MCP entry and an `AGENTS.md` rule.

### CLI/project install

```bash
python -m pip install hindsight-openhands
cd <PROJECT>
hindsight-openhands init \
  --api-token <HINDSIGHT_API_KEY> \
  --bank-id <PROJECT_BANK>
```

For self-hosted Hindsight:

```bash
hindsight-openhands init \
  --api-url http://localhost:8888 \
  --bank-id <PROJECT_BANK>
```

### Installed artifacts

#### `./config.toml`

```toml
[mcp]
shttp_servers = [
  {url = "https://api.hindsight.vectorize.io/mcp/<PROJECT_BANK>/", api_key = "<HINDSIGHT_API_KEY>"}
]
```

#### `./AGENTS.md`

The installer adds a Hindsight recall/retain rule that OpenHands loads into each task's context.

If `config.toml` cannot be parsed safely, the installer prints the exact snippet rather than overwriting it. `--print-only` previews the snippets.

### Docker app route

The containerized OpenHands app reads MCP servers from UI settings, not project `config.toml`:

```text
Settings → MCP → Add Streamable HTTP server
```

For a Hindsight server running on the Docker host:

```text
http://host.docker.internal:8888/mcp/<BANK_ID>/
```

Launch the container with host-gateway resolution where required:

```text
--add-host host.docker.internal:host-gateway
```

The repository's `AGENTS.md` rule still applies.

### Status/uninstall

```bash
hindsight-openhands status
hindsight-openhands uninstall
```

### Behavior

Rule-guided MCP, not lifecycle-hook automation. The rule instructs the model to recall and retain; the agent remains responsible for calling the tools.

### AUDiaGentic correction

A TOML MCP block alone is incomplete. The documented integration also owns an `AGENTS.md` rule. Docker-hosted OpenHands requires a separate UI-managed route and should not be reported installed merely because project `config.toml` was changed.

### Sources

- [Hindsight OpenHands integration README](https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/openhands)

---

## 13. Pi Coding Agent (`pi`)

### Canonical route

Pi core does not natively provide this MCP configuration surface. Install `pi-mcp-adapter`, then add Hindsight to one of the adapter's documented config layers.

There is no dedicated official Hindsight Pi integration page. The extra Pi block in `~/.hindsight/config.json` described by AUDiaGentic is therefore an AUDiaGentic recipe, not an upstream Hindsight install contract.

### Install the MCP adapter

```bash
pi install npm:pi-mcp-adapter
```

Restart Pi after installation.

### Add Hindsight to preferred project config

Create or merge `.mcp.json`:

```json
{
  "mcpServers": {
    "hindsight": {
      "url": "https://api.hindsight.vectorize.io/mcp/<BANK_ID>/",
      "headers": {
        "Authorization": "Bearer ${HINDSIGHT_API_KEY}"
      },
      "lifecycle": "lazy"
    }
  }
}
```

The adapter supports Streamable HTTP with SSE fallback via `url`. It supports header and environment interpolation.

### Documented adapter config layers

Current documented precedence:

1. `~/.config/mcp/mcp.json`
2. `~/.agents/mcp.json`
3. `~/.agents/mcp/mcp.json`
4. `<PI_CODING_AGENT_DIR>/mcp.json` — normally `~/.pi/agent/mcp.json`
5. `.mcp.json`
6. `.pi/mcp.json`

The project `.pi/mcp.json` layer has highest precedence and can persist `disabled` overrides without rewriting lower source files.

### Useful setup/status commands

Inside Pi:

```text
/mcp setup
/mcp
/mcp reconnect hindsight
```

Terminal setup:

```bash
pi-mcp-adapter init
```

For isolated AUDiaGentic launches, place the Pi-global MCP file under the request-specific `PI_CODING_AGENT_DIR` rather than the operator's global Pi directory.

### Tool exposure

By default, the adapter exposes MCP through one proxy tool to avoid placing every tool schema in the prompt. `directTools` can expose selected Hindsight tools directly, but this is a Pi adapter tuning decision, not required by Hindsight.

Example:

```json
{
  "mcpServers": {
    "hindsight": {
      "url": "https://api.hindsight.vectorize.io/mcp/<BANK_ID>/",
      "headers": {
        "Authorization": "Bearer ${HINDSIGHT_API_KEY}"
      },
      "directTools": ["recall", "retain", "reflect"]
    }
  }
}
```

### Behavior

Bare MCP unless Pi receives a separate instruction/skill telling it when to use memory. No official Hindsight Pi hooks or Pi-specific auto-recall/retain plugin are currently documented.

### Uninstall

- Remove only the Hindsight server from the owned MCP layer, or disable it in `.pi/mcp.json`.
- Remove `pi-mcp-adapter` only when no other Pi MCP servers depend on it.
- Remove the AUDiaGentic-specific `~/.hindsight/config.json` Pi host block only if AUDiaGentic owns it and the user requests Hindsight removal.

### AUDiaGentic correction

The original row omits the adapter prerequisite. `M1 + R1` should be described as:

1. third-party Pi adapter installation;
2. managed MCP entry in an isolated Pi config layer;
3. optional AUDiaGentic-owned Hindsight host recipe, explicitly labelled non-upstream.

### Source

- [Pi package registry: pi-mcp-adapter](https://pi.dev/packages/pi-mcp-adapter)

---

## 14. Plandex (`plandex`)

### Canonical route

No dedicated Hindsight integration and no current documented Plandex MCP/plugin/hook installation route was found in the published Plandex and Hindsight integration documentation reviewed for this audit.

### Install/manage/uninstall

- Do not mutate Plandex configuration based on assumptions.
- Return guidance-only.
- Explain that a future supported route requires a documented Plandex extension/tool surface or an external wrapper that can own prompt/session boundaries.
- Uninstall is a no-op because no artifact should be created.

### AUDiaGentic correction

Guidance-only remains appropriate. Phrase this as "no published supported route found" rather than an absolute claim that integration is impossible.

### Sources

- [Plandex context management](https://docs.plandex.ai/core-concepts/context-management/)
- [Hindsight integrations hub](https://hindsight.vectorize.io/integrations)

---

## 15. Qwen Code (`qwen`)

### Canonical route

Use Qwen Code's native remote HTTP MCP support with Hindsight's generic bank-scoped endpoint.

### Install with Qwen CLI

User scope:

```bash
qwen mcp add \
  --scope user \
  --transport http \
  hindsight \
  https://api.hindsight.vectorize.io/mcp/<BANK_ID>/ \
  --header "Authorization: Bearer <HINDSIGHT_API_KEY>"
```

Project scope:

```bash
qwen mcp add \
  --scope project \
  --transport http \
  hindsight \
  https://api.hindsight.vectorize.io/mcp/<BANK_ID>/ \
  --header "Authorization: Bearer <HINDSIGHT_API_KEY>"
```

### Config destinations

- User: `~/.qwen/settings.json`
- Project: `.qwen/settings.json`

Equivalent JSON:

```json
{
  "mcpServers": {
    "hindsight": {
      "httpUrl": "https://api.hindsight.vectorize.io/mcp/<BANK_ID>/",
      "headers": {
        "Authorization": "Bearer <HINDSIGHT_API_KEY>"
      },
      "timeout": 15000
    }
  }
}
```

Qwen uses `httpUrl` for HTTP transport. It recommends HTTP over legacy SSE where both are available.

### Instruction surface

Qwen Code loads persistent context from `QWEN.md`, including global `~/.qwen/QWEN.md` and project hierarchy files. No official Hindsight Qwen-specific rule is currently published. A rule added by AUDiaGentic must therefore be identified as an AUDiaGentic-owned policy artifact.

### Verify

Start Qwen Code and use:

```text
/mcp
```

If Qwen was already running when the server was added, restart it in the same project.

### Uninstall

Use Qwen's MCP management command to remove the server from the same scope in which it was installed, or remove only the owned `hindsight` entry from `settings.json`. Preserve all other settings and servers.

### AUDiaGentic correction

The earlier row is wrong on two material points:

- Qwen does not use project root `.mcp.json` for its documented native configuration.
- Qwen documentation says to restart an already-running process after adding a server; a generic file-watch claim is unsupported.

### Sources

- [Qwen Code MCP](https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/)
- [Qwen Code settings and `QWEN.md`](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/)

---

## 16. Roo Code (`roo`)

### Canonical route

Use `hindsight-roo-code install`. The installer registers Hindsight's MCP server and adds custom rules.

### Project install

```bash
python -m pip install hindsight-roo-code
cd <PROJECT>
hindsight-roo-code install
```

Self-hosted:

```bash
hindsight-roo-code install --api-url http://localhost:8888
```

Specific project:

```bash
hindsight-roo-code install --project-dir /path/to/project
```

### Global install

```bash
hindsight-roo-code install --global
```

### Installed artifacts

Project:

```text
.roo/mcp.json
.roo/rules/hindsight-memory.md
```

Global:

```text
~/.roo/mcp.json
~/.roo/rules/hindsight-memory.md
```

Documented MCP shape:

```json
{
  "mcpServers": {
    "hindsight": {
      "type": "streamable-http",
      "url": "http://localhost:8888/mcp",
      "timeout": 30,
      "alwaysAllow": ["recall", "retain"]
    }
  }
}
```

The rule instructs Roo to recall at task start, retain significant decisions during work, and retain a summary at task end.

### Verify

1. Restart Roo Code.
2. Open `Settings → MCP Servers`.
3. Confirm `hindsight` is connected.
4. Start a task and confirm `recall` appears in the tool-call log.

### Manage/update

Re-run the installer to update the API URL or edit the owned entry. Preserve unrelated Roo MCP servers and rules.

### Uninstall

The Hindsight page does not currently publish an uninstall command. Remove only the installer-owned Hindsight server entry and `hindsight-memory.md` rule. Do not delete `.roo/` wholesale.

### AUDiaGentic correction

The destination is `.roo/mcp.json`, not project root `.mcp.json`. The rules file is an essential part of the documented integration and must be owned/reconciled/uninstalled with the MCP entry.

### Source

- [Hindsight: Roo Code integration](https://hindsight.vectorize.io/sdks/integrations/roo-code)

---

# Required AUDiaGentic model changes

## 1. Do not use one global family-preference order as installation truth

A fixed order such as:

```text
managed-hooks > managed-mcp > plugin-entry
```

cannot represent the canonical routes. For Claude Code and OpenCode, the plugin is the full integration and must beat a generic MCP route. For Continue, neither hook nor plugin nor a static MCP entry captures the primary context-provider service.

The descriptor should advertise **integration recipes**, not merely low-level mutation surfaces. Example conceptual families:

- `managed-wrapper`
- `managed-plugin`
- `managed-hooks`
- `managed-context-provider`
- `managed-mcp-with-rules`
- `managed-mcp`
- `guidance-only`

A provider may still expose low-level APIs for other callers, but the Hindsight recipe should select the provider-specific full integration.

## 2. Represent compound installations explicitly

At minimum:

| Provider | Compound components |
| --- | --- |
| Claude | marketplace plugin + plugin config/data + optional daemon |
| Continue | supervised adapter + context config + optional MCP + rule |
| Copilot | MCP + Copilot instruction |
| OpenHands | MCP + `AGENTS.md`; separate Docker UI route |
| Pi | adapter extension + MCP config + optional AUDiaGentic host recipe |
| Roo | MCP + rule |

Install status must not report success when only one component exists.

## 3. Track automation semantics

Add a field such as:

```text
memory-behavior: deterministic-hooks | deterministic-wrapper | host-plugin | rule-guided-mcp | bare-mcp | none
```

This prevents a bare MCP connection from being presented as equivalent to automatic session memory.

## 4. Track provider scope and destination

The managed key must include at least:

```text
provider + scope + project/root identity + integration id
```

Several harnesses have different global and project files. A single provider-level ownership record is insufficient.

## 5. Treat secrets as references where possible

Do not make raw API tokens part of reusable project configuration when the harness supports environment/secret indirection. Status output must redact tokens and avoid logging full Authorization headers.

## 6. Separate upstream-documented artifacts from AUDiaGentic artifacts

Examples:

- `~/.hindsight/config.json` Pi host block — AUDiaGentic-specific unless an upstream Hindsight Pi integration begins documenting it.
- `ag-hindsight` managed ID — AUDiaGentic ownership identifier, not necessarily the name used by upstream installers (`hindsight` is common).
- custom `GEMINI.md` or `QWEN.md` memory instructions — AUDiaGentic policy unless published by Hindsight.

The status model should expose artifact origin:

```text
origin: upstream-installer | harness-native | audiagentic-recipe
```

## 7. Do not hard-code undocumented refresh behavior

Use documented activation semantics:

- Claude plugin: `/reload-plugins` or next startup.
- Cline: enable hooks in settings; test execution.
- Codex: start a new session after install.
- Copilot: reload VS Code and start the MCP server.
- Goose: default changes affect future sessions; current sessions can be changed separately.
- Qwen: restart an already-running Qwen process after adding a server.
- Roo: restart Roo Code.

A generic `file-watch` versus `restart-required` flag loses important host-specific behavior.

---

# Corrected lifecycle contract

For each provider-specific integration, AUDiaGentic should implement:

### Install

1. Validate platform and prerequisite versions.
2. Select the canonical provider-specific route.
3. Materialize every required component.
4. Preserve unowned config and use parser-safe merging.
5. Store ownership per artifact and scope.
6. Validate connection and activation, not merely file presence.
7. Report the exact host action still required.

### Reconcile/manage

1. Re-read all owned artifacts.
2. Detect missing, changed, stale, duplicate, or collision state.
3. Update backend URL, bank, auth reference, scripts/plugin version, and rules as applicable.
4. Supervise required adapter/daemon processes.
5. Preserve unowned content.
6. Distinguish configured, connected, active, and automatically operating.

### Uninstall

1. Use the upstream uninstall command when published.
2. Otherwise remove only precisely owned entries/blocks/files.
3. Stop only processes owned by this integration.
4. Preserve user Hindsight banks and user configuration unless explicit data deletion is requested.
5. Preserve all unrelated provider settings, MCP servers, hooks, plugins, and rules.

---

# Source index

## Hindsight

- [Integrations hub](https://hindsight.vectorize.io/integrations)
- [Generic Hindsight Cloud MCP](https://docs.hindsight.vectorize.io/mcp/)
- [Local Hindsight MCP](https://hindsight.vectorize.io/sdks/integrations/local-mcp)
- [Aider](https://hindsight.vectorize.io/sdks/integrations/aider)
- [Gemini Spark / Antigravity](https://hindsight.vectorize.io/sdks/integrations/gemini-spark)
- [Claude Code](https://hindsight.vectorize.io/sdks/integrations/claude-code)
- [Cline package](https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/cline)
- [Codex](https://hindsight.vectorize.io/sdks/integrations/codex)
- [Continue](https://hindsight.vectorize.io/sdks/integrations/continue)
- [GitHub Copilot package](https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/github-copilot)
- [OpenCode](https://hindsight.vectorize.io/sdks/integrations/opencode)
- [OpenHands package](https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/openhands)
- [Roo Code](https://hindsight.vectorize.io/sdks/integrations/roo-code)

## Harness documentation

- [Claude Code plugins](https://code.claude.com/docs/en/plugins-reference)
- [Cline hooks](https://docs.cline.bot/customization/hooks)
- [Continue configuration](https://docs.continue.dev/cli/configuration)
- [Continue MCP](https://docs.continue.dev/customize/deep-dives/mcp)
- [Continue rules](https://docs.continue.dev/customize/rules)
- [Gemini CLI MCP](https://geminicli.com/docs/tools/mcp-server/)
- [Gemini CLI context files](https://geminicli.com/docs/cli/gemini-md/)
- [Goose extensions](https://goose-docs.ai/docs/getting-started/using-extensions/)
- [Goose config files](https://goose-docs.ai/docs/guides/config-files/)
- [Pi MCP adapter](https://pi.dev/packages/pi-mcp-adapter)
- [Plandex context management](https://docs.plandex.ai/core-concepts/context-management/)
- [Qwen Code MCP](https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/)
- [Qwen Code settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/)
