# Check-In Summary

Total changes: 25

- Renamed the Agent LLM Gateway to Agent Execution Gateway — all public contracts (MCP tools, API methods, topics, schemas) now use provider-neutral 'execution' vocabulary instead of technology-specific 'LLM' terms
- Fixed leftover references to the old agent-LLM-gateway terminology in component READMEs, and tightened the vocabulary-cutover test so future doc drift is caught automatically.
- Removed unnecessary legacy-path migration code left over from the agent-execution rename -- there was no real deployed state depending on the old path, so per architecture standards it should not have been kept.
- Renamed the agent-profile system to execution-profile terminology throughout the agents component, its MCP tools, error codes, and config -- part of the larger AS60 migration (composition-graph wiring still to come).
- Implemented the execution-profile resolver contract and its composition wiring for the shared gateway service -- the design corrected in RV888 after finding the original composition-root reasoning was based on a mistaken lifecycle assumption.
- Added the DI/composition-candidate evaluation rules to the durable architecture standards, so future composition decisions are checked against a standing document rather than a plan item.
- Implemented a minimal, reusable Role type for agents -- instructions, required capabilities, and an inert future-policy placeholder -- with CRUD via the existing management MCP server, deliberately kept independent of the agent_jobs prompt-tag system slated for rework.
- Implemented AgentDefinition, the minimal composition of an execution profile and a role into a named logical agent, keeping the same evidence-led scoping discipline as the two items it builds on.
- Fixed cross-project planning leakage: projected MCP servers are now always scoped to the project that created them, so a new project cannot list reviews from the AUDiaGentic project.
- Implemented the agent_id-primary task submission API (AgentTaskFactory/AgentTask) as a real, MCP-reachable surface over the existing gateway -- the first genuine, non-test consumer of Agent Definition resolution.
- Fixed fresh OpenCode projects receiving AUDiaGentic managed instruction blocks in AGENTS.md during install. Surface content is now applied only through explicit surface reconciliation.
- AUDiaGentic now lets you control which detected provider CLIs (claude, codex, opencode, etc.) get auto-enabled in a project, instead of always enabling everything found on PATH. Choose auto/allowlist/prompt mode via the new interactive first-run question or the providers MCP tools.
- Added project-local CRUD for instructions and skills through the project MCP server. Project-owned guidance now renders across enabled harnesses without spreading AUDiaGentic-specific doctrine into other projects.
- Corrected the implementation direction: provider surface application remains automatic, but AUDiaGentic-specific doctrine is now stored and rendered only from the owning project.
- Fixed fresh installs reporting optional components as installed and enabled. New projects now start with only the core project scaffold; install optional components explicitly when needed.
- Removed the stray test hook from the local Codex configuration; managed-config tests are container-only.
- Completed validation for project-local surfaces: fresh projects can now create instructions and skills without optional components, and generated skills are limited to enabled providers.
- Added real Docker end-to-end tests proving the new provider reconciliation-policy behaves correctly against actual installed provider CLIs (opencode, pi, codex, claude), not just mocked probes.
- Reorganized the agents component's flat file layout into functional subfolders (models, mcp, gateway, status) with no behavior change; full unit suite and integration/agents test collection verified green.
- Composed the agent gateway's queue manager for its process lifetime instead of a bare global, and removed a redundant blocking MCP tool now that the same capability exists directly on the underlying API for programmatic callers.
- Split the agent execution gateway's MCP tools into two servers: a primary, self-sufficient agent-task server, and a separate thin server for the older direct-execution-profile submission path that's expected to be retired.
- Kept the agent execution gateway as one MCP server, but renamed its shared status/wait/cancel/list/overview/session tools from agent_execution_* to agent_task_* so they read consistently alongside the primary agent_task_submit tool.
- Fixed the reported test failures, including the Windows rig replacement failure; the requested targeted test suite now passes completely.
- Added a test proving the new agent-task submission path and the older raw path both funnel through the same underlying gateway machinery rather than duplicating it.
- Created and tested the project's first real Agent Definition (a local rig test model wired through an execution profile and placeholder role), and filed a plan item to track populating real agent content going forward.
