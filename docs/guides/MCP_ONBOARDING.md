# MCP onboarding

Register one declared MCP with explicitly selected existing harnesses:

```text
audiagentic help
audiagentic mcp list
audiagentic harness list
audiagentic mcp ag-planning help
audiagentic harness pi help
audiagentic mcp install help
audiagentic mcp install ag-planning harness pi,opencode
```

Discovery/help works outside a project without adapter initialization, writes,
subprocesses or external probes. Native capability is separate from the presence
of a client binary. Installation does not install binaries, authenticate accounts,
launch chat or claim live reachability.

## Grammar and selection

```text
audiagentic mcp install MCP_ID harness ID[,ID...]
  [project PATH] [component-profile NAME] [config FILE]
  [dry-run] [non-interactive] [output json]
```

Use an existing project context or an explicit `project PATH`. Each clause occurs
once after mandatory operands. Quote paths with spaces. Values consume one token
even when named `help` or `project`. Targets are trimmed and deduplicated in order;
empty targets are rejected. Malformed management input never falls through to chat.

The list replaces the **complete selection for this MCP**. Switching planning
from Pi to Codex removes its owned Pi entry; ledger and other MCPs remain unchanged.
All affected targets, including removals, preflight before mutation.
`dry-run` reports planned changes and always has `changed: false`. Real receipts
report actual applied changes, target outcomes and completed removals. Partial
failure preserves successful targets. `output json` emits one portable JSON value.

Shipped `--project`, `--component-profile`, `-p` and `-s` retain their existing routes.
Do not supply both a root option and its keyword equivalent. There is one process
component profile, not a second onboarding profile selector.

Generated launches retain `audiagentic mcp MODULE MODULE_ARGS`. Bare
`install/list/help` and `ID help` have management precedence. Use
`audiagentic mcp -- MODULE MODULE_ARGS` for affected literal modules.
Root `--` preserves opaque arguments on the normal provider route.

## Configuration and tool results

Item help projects the owning implementation's option schema. Existing component
and implementation settings retain their precedence. CLI `config FILE` accepts
an `options` mapping of declared owner keys, not a new configuration store.
Interactive terminals may request missing nonsecret values; noninteractive and
MCP calls report missing keys. Use the owner's supported secure configuration
interface for sensitive values, not argv or onboarding history.

Configured means the owned native entry matches. Reachable/verified are omitted
unless assessed; absence is not success. Follow per-target restart instructions.
Identical repeated installation performs guarded recovery and leaves unchanged
native files byte-identical.

The internal `ag-project-mgmt` adds three tools:

| Tool | Contract |
|---|---|
| `list_mcp_catalog(mcp_id=None)` | Compact declarations; an ID requests detailed help. |
| `install_mcp(mcp_id, harness_ids, dry_run=False)` | Noninteractive installation; dry-run preflight; safe repeated recovery. |
| `get_mcp_install_status(operation_id=None)` | One operation, or latest unresolved operation; read-only. |

No unresolved operation returns `{"has_unresolved_operation": false}`.
New tools use one structured result channel; existing Project tools retain their
wire contract. Installing planning does not expose Project management in native clients.

## Ownership, lifecycle and recovery

Project-owned `.audiagentic/config/project.yaml` records intent:

```yaml
mcp-onboarding:
  contract-version: v1
  bindings:
    ag-planning: [pi, opencode]
```

New projects start with explicit empty bindings. Older projects migrate only on
an explicit mutation using recorded ownership and matching native evidence.
Matching names or bytes without ownership are never adopted. Lifecycle, provider
state and config refresh reuse this resolver instead of broadcasting.
Internal management and independent LSP ownership retain separate policies.

Authoritative MCP ownership migrates from runtime storage into
`.audiagentic/state/providers/managed-mcp-servers.json`. Operation receipts live
in `.audiagentic/state/mcp-onboarding/operations/`: keep the newest 100 completed
receipts and retain unresolved receipts. Local state is gitignored and contains
safe identity/phases/outcomes, not native snapshots or credentials.

Foreign edits, changed target identity and stale revisions block unsafe writes.
Inspect the owning error/status before retrying. Interrupted writes without enough
ownership proof require reconciliation; retry does not claim unknown entries.
Per-target recovery does not promise a global transaction across clients.
Background profile-derived payload changes require explicit installation before
replacing a proven, unmodified owned entry.

## Metadata and verification

Component YAML owns tool/parameter/server prose. A short `project/mcp-onboarding`
contribution uses existing provider managed-region rendering. Change the source
and regenerate; never hand-edit managed AGENTS regions. Planning/ledger skills,
prompt tags and user content retain their ownership.

Run `python tools/test_mcp_onboarding.py` for disposable CLI/native-format and real
Project/planning/ledger stdio checks. To test a wheel, use a fresh environment,
leave the checkout and invoke that script with the installed interpreter and
`--installed`. It verifies installed import origin, metadata/output schemas,
planning CRUD and ledger round trips. Native-format proof does not assert that
Pi/OpenCode/Codex itself recognized or loaded the configuration.

Add `--native-clients` to run read-only Codex/OpenCode discovery against the
disposable fixture, with isolated user directories. Missing executables are
reported as unavailable. Pi currently has no read-only MCP discovery command,
so its extension recognition is not claimed by this check.

MP02 slim/co-installable distributions remain separate.

