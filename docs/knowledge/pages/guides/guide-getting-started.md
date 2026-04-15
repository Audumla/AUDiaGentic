---
id: guide-getting-started
title: Getting Started with AUDiaGentic
type: guide
status: current
summary: Guide for new developers and agents to get started with the AUDiaGentic project, covering repository structure, core systems, and contribution workflow
owners:
- core-team
updated_at: '2026-04-15'
tags:
- getting-started
- onboarding
- tutorial
related:
- system-planning
- system-knowledge
- guide-using-planning
- tool-cli
---

## Summary
This guide helps new developers and agents get started with the AUDiaGentic project. It covers repository structure, core systems (planning and knowledge), and how to begin contributing effectively.

## Current state
**Repository Structure:**
```
AUDiaGentic/
├── .audiagentic/           # Runtime configuration and state
│   ├── knowledge/          # Knowledge component config
│   └── planning/           # Planning system state and events
├── docs/                   # Documentation
│   ├── knowledge/          # Knowledge vault (current-state docs)
│   └── planning/           # Planning artifacts (requests, specs, plans, tasks)
├── src/                    # Source code
│   └── audiagentic/        # Core modules
│       ├── knowledge/      # Knowledge component
│       └── planning/       # Planning system
├── tools/                  # Utility scripts
└── AGENTS.md              # Agent instructions and canonical prompts
```

**Core Systems:**
1. **Planning System**: Workflow management for software engineering tasks
   - Artifacts: requests, specs, plans, work packages, tasks
   - State tracking and event logging
   - See: [Planning System](../systems/system-planning.md)

2. **Knowledge Component**: Deterministic knowledge management
   - Current-state documentation vault
   - Event-driven sync from planning and runtime
   - See: [Knowledge System](../systems/system-knowledge.md)

**Development Environment:**
- Python 3.13+
- Project uses standard Python packaging
- CLI tools available for both planning and knowledge operations

## How to use
**1. Clone and Setup:**
```bash
git clone <repository-url>
cd AUDiaGentic
# No virtualenv required for basic operations
```

**2. Explore the Planning System:**
```bash
# View recent planning events
tail -20 .audiagentic/planning/events/events.jsonl

# List ready tasks
python -m src.audiagentic.planning.cli next-tasks --state ready

# View a specific task
python -m src.audiagentic.planning.cli show --id task-XXXX
```

**3. Explore the Knowledge Vault:**
```bash
# Check knowledge vault health
python -m src.audiagentic.knowledge.cli --root . doctor

# View knowledge status
python -m src.audiagentic.knowledge.cli --root . status

# Search for documentation
python -m src.audiagentic.knowledge.cli --root . search --query "planning"
```

**4. Start Contributing:**
- Browse ready tasks in `docs/planning/tasks/`
- Claim a task by changing state to `in_progress`
- Implement the work
- Update task state to `done`
- Events are automatically logged

**5. Understand Canonical Prompts:**
- Read `AGENTS.md` for agent workflow instructions
- Canonical tags: `@ag-plan`, `@ag-implement`, `@ag-review`, `@ag-audit`, `@ag-check-in-prep`
- These trigger specific workflow jobs through the prompt bridge

## Sync notes
This page should be refreshed when:
- Repository structure changes significantly
- New core systems are added
- Development setup process changes
- Canonical prompts are modified

**Sources:**
- `AGENTS.md` - Agent instructions
- Repository root structure
- Core module implementations

**Sync frequency:** On major structural changes

## References
- [Planning System](../systems/system-planning.md)
- [Knowledge System](../systems/system-knowledge.md)
- [Using the Planning System](./guide-using-planning.md)
- [CLI Tool](../tools/tool-cli.md)
- [AGENTS.md](../../../AGENTS.md)
