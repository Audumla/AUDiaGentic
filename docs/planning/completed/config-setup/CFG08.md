---
id: CFG08
order: 8
plan: config-setup
state: completed
created-at: '2026-10-28T21:05:53.564412+00:00'
breadth: ''
skill: intermediate
created-by: claude
work: M
priority: P1
---

# setup and doctor commands, MCP registration without env

## Description

`audiagentic setup` is idempotent: creates only needed user config, registers MCP servers in detected harnesses through the CLI entrypoint (no interpreter paths, no env vars), and runs doctor. `audiagentic doctor` checks every failure seen on 2026-10-28 and prints the exact fix.



Also: installed-wheel qualification (clean Python 3.10 wheel install passes setup, MCP and gateway smoke tests); feeds SH42. CFG07 must land first.

## Steps

1. doctor checks: config validity, agents, provider availability/qualification, project identity, MCP registration, package data, gateway reachability
2. setup flow over existing mcp install
3. MCP entries via `audiagentic mcp <id>`

## Detailed Solution & Technical Design



## Code Samples & Guidance



## Files



## Validation

Live checks 2026-10-29 (end-to-end agent_task_submit through the user-scope MCP registration, from clean throwaway homes) and 2026-10-31 (installed 0.46.0 wheel from PyPI: setup, doctor, config set dry-run, planning/ledger/gateway MCP initialize). Unit coverage: doctor checks (tests/unit/foundation/test_doctor.py), settings CLI, launcher arguments including --version. Single-port enforcement across homes is tracked by SH64.

## Effort & Risk



## Standards

docs/design/configuration-model.md (phased spec); docs/standards/ARCHITECTURE_STANDARDS.md and ARCHITECTURE_GUIDELINES.md: foundation owns mechanics (strict YAML, merge, schema registry, platform paths), components own their own checks and settings sections, no parallel loaders. Read-only doctor; setup writes only the user settings scope. Error codes registered with resolutions.

## Acceptance Criteria

On a clean container, `audiagentic setup` followed by one agent_task_submit to a gpt-auto agent succeeds with no manual file edits.

## Notes

Context: brief /work/development/tmp/AUDiaGentic/config-review/BRIEF.md; proposals /work/development/tmp/AUDiaGentic/config-review/claude-proposal.md and /work/development/tmp/AUDiaGentic/config-review/round1-gpt.md (GPT round 2 pending in /work/development/tmp/AUDiaGentic/config-review/round2-gpt.md). Evidence from the 2026-10-28 agent-dev container setup (PRs #77, #78, #80, #81, #82).



Phase 1 (approved 2026-10-28; see 'Phasing' in docs/design/configuration-model.md). Installed-wheel qualification without CFG07 evidence.



2026-10-29: PR #100 (stacked on #98): audiagentic doctor (read-only, no app graph) running component-declared checks from config/components/<component>/doctor/checks.yaml via foundation.config.refs; checks: package.data, settings.valid (foundation), project.identity, mcp.onboarding (project), agents.files, provider.<id> availability (agents; new providers_api.check_provider_availability incl. gpt-auto CDP probe). audiagentic setup creates only missing user settings then runs doctor. Not yet: MCP registration through the CLI entrypoint (needs the providers MCP writer change) and installed-wheel qualification.

2026-10-29: merged in PR #100 (squash). Validation: tests/unit/foundation/test_doctor.py (component-declared checks, read-only doctor, idempotent setup, crashing check reported not raised).

2026-10-29 live check of the acceptance criterion (throwaway home and repo, throwaway settings; main at the CFG06 slice 2 merge). Result: NOT met, but a gpt-auto submit through the gateway MCP did complete (CFG08 LIVE OK) once the gaps below were worked around by hand.

Worked: setup creates the user settings; doctor reports settings, package data, agent files, provider availability (CDP answered) and project identity.

Gaps that needed a manual step on a clean home:
1. doctor fails agents.catalog (legacy agents.yaml missing) before any agent exists; the required-file check should treat agent files as sufficient (CFG09 made agents.yaml optional only once agent files exist).
2. setup creates no agent; the flow needs audiagentic agent add NAME --extends reviewer --provider gpt-auto --model chatgpt. setup should offer a first agent or doctor should say exactly that.
3. gpt-auto first navigates the browser to the gateway dashboard URL as a window anchor. An embedded gateway serves no dashboard, so the anchor failed with ERR_CONNECTION_REFUSED. window_anchor.py reads AUDIAGENTIC_GATEWAY_PORT (default 8765) and ignores the gateway.port setting (providers cannot import gateway internals, so ownership of that value is undecided). Worked around with a stub page and AUDIAGENTIC_GATEWAY_DASHBOARD_URL.
4. gpt-auto selects the ChatGPT project named after the repository. A repo without a remote resolves its name from the directory (project), so the Projects page lookup failed (EXT-GPTAUTO-004, submission-attempted false). A git origin remote fixed it. doctor warns on the provisional name but does not say it also selects the ChatGPT project.
5. setup registered no MCP servers and printed nothing about it (still listed under Not yet).

Next: a doctor check that the gpt-auto dashboard anchor and project name resolve; setup offering a first agent; agent files sufficient for agents.catalog. The live check is repeatable: setup, doctor, agent add, then agent_task_submit with a one-line prompt, in a throwaway _AUDIAGENTIC_HOME.

2026-10-29: PR #140 fixed gaps 1, 2 and 4 of the live check as far as doctor can: agents.catalog warns with the agent add fix on a clean home (an invalid legacy file still fails); a declared project.id is now the project name providers use, so declaring it fixes the gpt-auto ChatGPT project lookup; and a new agents.gateway check flags gpt-auto on the default embedded gateway and gives the fix (gateway.implementation: automatic in user settings). Still open: gap 3 (the embedded gateway serves no dashboard for gpt-auto window anchor, and window_anchor.py ignores gateway.port; needs a gateway/providers ownership decision, or a different default) and gap 5 (setup registers no MCP servers). CFG08 stays in progress until a repeat of the live check passes with only setup, agent add and the documented settings; that repeat is not yet done after #140.

2026-10-29 repeat of the live check on main with #140, using only documented steps in a fresh throwaway home and a repo with no remote: audiagentic setup; audiagentic agent add NAME --extends reviewer --provider gpt-auto --model chatgpt; settings gateway.implementation: automatic (user) and project.id (tracked project settings) as doctor instructs; doctor all ok; agent_task_submit of a one-line prompt through the gateway MCP completed with the expected reply. No stub page, no environment variables, no hand-edited catalog. The criterion holds when two documented settings are counted as configuration, not as manual file edits; a default install still needs them because the default implementation is embedded and a repo without a remote is named after its directory. Remaining before CFG08 can complete: decide whether setup should offer or apply those two settings, and MCP registration through the CLI entrypoint.

2026-10-29 correction to the live-check findings above. Gap 3 (gpt-auto dashboard anchor) is environment-dependent, not a general clean-install failure: ensure_dedicated_window_anchor reuses any open browser tab whose scheme, host and path match the dashboard URL (served or not) and keeps an in-memory handle between calls, so gpt-auto works under the embedded gateway whenever such a tab or handle already exists (the other session ran many requests that way) and fails with ERR_CONNECTION_REFUSED only when none does, as in my fresh-browser first run. Not reproduced on a truly clean browser since. The agents.gateway doctor check now says exactly that. Whether to make shared (automatic) the default is an explicit decision, not a side effect: the SH11 item is closed but records no soak or rollback rehearsal, embedded.yaml still says default until that soak, and every session using the global gateway MCP runs the embedded default today. Before any flip: run the five integration files that set the gateway mode, a real gpt-auto request under the flipped default, and reproduce the anchor failure on a clean browser.

2026-10-29: gap 5 closed by PR #174. `audiagentic setup harness ID[,ID...] [dry-run]` registers every worktree-scoped MCP server (worktree-scoped: true on its component YAML declaration; ag-planning, ag-ledger, ag-agents-gateway) at the named harnesses' user scope, so sessions started outside a project have them; each tool takes a per-call worktree (#167). Only named harnesses are touched (the MCP onboarding rule). Claude's user scope (mcpServers in $CLAUDE_CONFIG_DIR/.claude.json, else ~/.claude.json) is changed only through `claude mcp add-json/remove --scope user`. Entries are this installation's absolute audiagentic console script plus `mcp MODULE`, no interpreter path, no env. Ownership is recorded per target file in the user state directory; foreign same-named entries are reported, never overwritten. doctor check mcp.user.<harness> reports configured, or warns on missing/drifted/foreign with the setup command as fix. The bogus ~/.claude/mcp.json fallback is removed.

Applied on the agent-dev container for accounts mgai2 and clai2 (shared runtime venv at main with #174): `claude mcp list` shows ag-planning, ag-ledger and ag-agents-gateway connected at user scope. Each further account needs the same one command.

Open gap found while applying it: the registered servers inherit the session environment, and container sessions set no _AUDIAGENTIC_HOME, so the user-scope gateway sees the default home (no agent files; doctor warns agents.files) rather than /work/development/AUDiaGentic/home where reviewer-gpt-agent lives. Needs a settings-level home choice (or an agent added to the default home), not an env var in the entries. CFG08 stays in progress for the end-to-end criterion and installed-wheel qualification.

2026-10-29: the home gap is closed by PR #208. A foundation-owned settings key `home` (absolute path or ~/...) chooses the AUDiaGentic home when _AUDIAGENTIC_HOME is unset: precedence env, then the machine-scope setting (user settings or explicit file; a project's own settings are never read), then ~/.audiagentic. An invalid settings file raises instead of picking another home. `audiagentic config paths` prints the home in effect and its source. Verified read-only against the real shared home with no environment: doctor saw the hosted catalog (2 agents) with the setting and none without. Each account's user settings still need `home:` added; that file is the user's, so it is not edited here.

Remaining before CFG08 can complete: (1) the end-to-end criterion has not been repeated with the user-scope MCP tools and a `home` setting in place (setup harness, then agent_task_submit from a session started outside a project); (2) installed-wheel qualification; (3) the fixed gateway port 8765 still collides if two homes ever run services (CON-MSVC-037 now reports it instead of timing out), which the single home removes in practice but does not enforce. Related finding from the shared-service restart: a handoff replacement started while the retiring process still held 8765 died with 'Address already in use' (a race, belongs to SH63).

2026-10-29 (20:45) end-to-end criterion repeated through the user-scope registration. Setup: `audiagentic setup harness` registered the worktree-scoped MCP servers (#174) and the shared user settings (/agents/home/.config/audiagentic/settings.yaml, HOME=/agents/home) now has `home: /work/development/AUDiaGentic/home` (#208). Check: the registered gateway command (the audiagentic console script, `mcp audiagentic.components.agents.mcp.gateway_mcp`, no environment) was started fresh from /work, outside any project, with no AUDIAGENTIC_* variable. It listed the agents of the shared home (reviewer-gpt-agent, gpt-auto-reviewer-agent), and one agent_task_submit of a one-line prompt to reviewer-gpt-agent completed with the exact reply, attaching to the single running shared service (no second service). Not done by hand: no stub, no env, no hand-edited catalog; the only manual steps were `setup harness` and the `home` line in user settings.

A caveat found on the way: an MCP server process that was already running when the runtime moved forward (here, started 19:27, before #203 at 20:41) fails lazily with an ImportError from a mixed old/new module set (gateway_session_generation_lock_path); a freshly started server is fine. A harness session must restart its MCP servers after the shared runtime changes.

Still open before CFG08 can complete: installed-wheel qualification (the criterion above ran from the editable shared runtime, not an installed wheel), and the fixed gateway port 8765 is not enforced against two homes (CON-MSVC-037 reports it; one shared home avoids it in practice).

2026-10-31 installed-wheel qualification (the remaining CFG08 item). audiagentic 0.46.0 installed from PyPI into a throwaway virtualenv (python 3.14), fresh _AUDIAGENTIC_HOME and XDG_* directories, and a git project with no remote; run with `python -I` so the package resolves from site-packages. Result: PASS. `audiagentic setup` created the user settings; `doctor` reported package.data ok (packaged defaults and schemas present) and settings.valid ok, with only the expected clean-install warnings (no agent files or catalog yet, project id from the directory name, no remote default branch, port 8765 held by the shared gateway of another home = SH64). `audiagentic config set providers.pi.enabled=false --scope project --dry-run` produced the correct new-file diff (the CFG06 writer works installed). The planning, ledger and gateway MCP entrypoints (`audiagentic mcp audiagentic.components.<x>`) each answered a JSON-RPC initialize from the wheel. Finding fixed with this note: `audiagentic --version` did not exist and fell through to the launch path (update check, provider reconcile, wrote CLAUDE.md, AGENTS.md and .audiagentic into the project, exit 1); a --version/-V argument now prints the version and exits without launching (tests/unit/test_launcher_arguments.py). Not part of CFG08: the gateway end-to-end submit from the wheel needs a configured agent and provider and was already verified from the shared runtime on 2026-10-29; the single-port enforcement across two homes is owned by SH64.

2026-10-31 GPT on-track review (ADJUST): CFG08 stays complete. Its installed-wheel qualification (0.46.0) and the `--version` addition (#265) are recorded above; neither implies that CFG07's broader qualification evidence is satisfied.

## Change Log

- 2026-10-28T21:05:53.564412+00:00 (created-by): Created by claude
- 2026-10-28T21:05:55.898893+00:00 (updated-by): Updated: section:description, section:steps, section:acceptance_criteria, section:notes
- 2026-10-28T21:21:36.632840+00:00 (updated-by): Updated: section:description
- 2026-10-28T22:06:56.145222+00:00 (updated-by): Updated: section:notes
- 2026-10-28T23:39:26.834124+00:00 (updated-by): Updated: section:notes
- 2026-10-28T23:39:29.268659+00:00 (state-transition): State: pending → in_progress
- 2026-10-29T02:22:47.262707+00:00 (updated-by): Updated: section:notes
- 2026-10-29T05:00:17.238284+00:00 (updated-by): Updated: section:notes
- 2026-10-29T05:27:58.309590+00:00 (updated-by): Updated: section:notes
- 2026-10-29T05:31:22.215189+00:00 (updated-by): Updated: section:notes
- 2026-10-29T07:40:55.635463+00:00 (updated-by): Updated: section:notes
- 2026-10-29T14:28:12.548201+00:00 (updated-by): Updated: section:notes
- 2026-10-29T20:28:37.050401+00:00 (updated-by): Updated: section:notes
- 2026-10-29T20:46:36.103718+00:00 (updated-by): Updated: section:notes
- 2026-10-31T02:03:33.579897+00:00 (updated-by): Updated: section:notes
- 2026-10-31T02:03:35.992897+00:00 (updated-by): Updated: section:validation
- 2026-10-31T02:03:41.106413+00:00 (state-transition): State: in_progress → completed
- 2026-10-31T03:42:16.671108+00:00 (updated-by): Updated: section:notes
