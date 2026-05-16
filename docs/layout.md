# AUDiaGentic Directory Layout

## Shared / Machine-level — `~/.audiagentic/harness/`

One install per machine. Set `AUDIAGENTIC_HOME` to relocate the root.

```
~/.audiagentic/
└── harness/
    ├── cli/
    │   └── node_modules/
    │       ├── @earendil-works/pi-coding-agent/   ← Pi agent binary (patched at install)
    │       ├── pi-mcp-adapter/                    ← MCP bridge extension
    │       └── .bin/pi  (pi.cmd on Windows)
    ├── agent/                                     ← Pi home dir (baked once at install)
    │   ├── SYSTEM.md                              ← system prompt (static)
    │   ├── APPEND_SYSTEM.md
    │   ├── extensions/footer.ts
    │   ├── models.json                            ← provider/endpoint/model config
    │   ├── mcp.json                               ← MCP server definitions
    │   └── settings.json                          ← UI theme and flags
    ├── rig/
    │   └── bin/
    │       ├── llama-server/
    │       │   ├── windows/                       ← drop llama-server.exe here
    │       │   ├── macOS/
    │       │   └── linux/
    │       └── models/                            ← drop .gguf model files here
    └── logs/
        └── rig/                                   ← llama-server launch logs
```

Re-run `audiagentic install` after changing model, port, or harness config to rebake `agent/`.

---

## Project-level — `<project>/.audiagentic/`

One set per project, committed or gitignored as appropriate.

```
<project>/.audiagentic/
├── sessions/                          ← Pi conversation history (this project only)
├── logs/
│   └── cli/                           ← Pi run logs (smoke + interactive)
├── config/
│   ├── project.yaml                   ← project metadata
│   ├── components.yaml                ← component enable/disable
│   ├── harness/
│   │   └── ag.yaml                    ← local harness config overrides (optional)
│   ├── execution/
│   │   └── prompt-syntax.yaml        ← prompt tag aliases and provider shortcuts
│   ├── runtime/
│   │   └── providers.yaml            ← provider enable/disable and config
│   └── interoperability/
│       ├── config.yaml               ← interoperability runtime settings
│       └── events.yaml               ← event schema registry
├── planning/                          ← planning system data
├── runtime/                           ← jobs, ledger
├── knowledge/                         ← knowledge base
└── components/                        ← component marker files (machine-written, one per installed component)
```

---

## Package source (config and registry files)

These ship with the package and are read at runtime — not copied anywhere.

| File | Purpose |
|------|---------|
| `src/audiagentic/provisioning/rig/embedded/rig.yaml` | llama-server arg defaults + per-model overrides |
| `src/audiagentic/provisioning/rig/embedded/models.json` | Model profile registry (aliases, model_file, ag compat) |
| `src/audiagentic/provisioning/harness/pi/config/config.yaml` | Harness defaults (model, rig port, MCP, UI, lockdown) |
| `src/audiagentic/provisioning/harness/pi/templates/home/agent/` | Static source files copied to `harness/agent/` at install |

---

## Config override hierarchy

Harness config merges three tiers (lowest → highest priority):

1. Package default — `src/.../harness/pi/config/config.yaml`
2. User-global — `$AUDIAGENTIC_HOME/config/harness/ag.yaml`
3. Project-local — `<project>/.audiagentic/config/harness/ag.yaml`

Set `exclusive_local: true` in the project file to skip the user-global tier.
Override individual values via `AUDIAGENTIC_PI_*` env vars (highest priority of all).

---

## What runs where

| Concern | Location | Shared? |
|---------|----------|---------|
| Pi agent binary | `harness/cli/` | ✓ machine |
| Pi baked config | `harness/agent/` | ✓ machine |
| llama-server binary | `harness/rig/bin/llama-server/` | ✓ machine |
| Model files (.gguf) | `harness/rig/bin/models/` | ✓ machine |
| Pi conversation history | `<project>/.audiagentic/sessions/` | ✗ project |
| Pi run logs | `<project>/.audiagentic/logs/cli/` | ✗ project |
| Rig launch logs | `harness/logs/rig/` | ✓ machine |
| Planning / runtime data | `<project>/.audiagentic/planning/` etc. | ✗ project |
| Harness config overrides | `<project>/.audiagentic/config/harness/ag.yaml` | ✗ project |

---

## Key environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `AUDIAGENTIC_HOME` | Root for all shared state | `~/.audiagentic` |
| `AUDIAGENTIC_AG_BASE_URL` | Override rig endpoint (external rig) | `http://127.0.0.1:{rig.port}/v1` |
| `AUDIAGENTIC_AG_MODEL` | Override model at launch | value from config |
| `AUDIAGENTIC_RIG_DEVICE` | llama-server `--device` arg | unset |
| `AUDIAGENTIC_RIG_SERVER_BIN` | Override llama-server binary path | auto-detected |
| `AUDIAGENTIC_RIG_MODEL_FILE` | Override model file path | from model profile |
