# Check-In Summary

Total changes: 27

- Removed unused, unreferenced llama.cpp binaries from the source tree; rig binaries are provisioned at runtime via the LlamaCppRecipe, not checked into git.
- Removed the deprecated agent_execution_submit MCP tool; agent_task_submit (agent-definition-based) is now the only way to submit agent work over MCP.
- Investigated whether agent capability checks (AS64) are needed yet; found no real Role or Execution Profile currently requires one, so closed the item without building unused infrastructure.
- Documented how Role selection will interact with Execution Profile/workflow-profile/component-profile precedence once a standalone role-selection field exists.
- Added a public API to query whether a provider supports exact MCP launch isolation (currently pi and opencode only), first increment toward the Role capability resolver.
- Audited AS52 (interactive-session child-process supervision) and found most of it already built; shrunk the plan item down to the one real remaining bug (a Windows close() race that orphans a child process).
- Completed the harness-observation capability matrix by adding the last two missing provider surface entries (Cline SDK/hooks candidates).
- Corrected AS55's scope: OpenCode ACP's basic transport already works and is proven, but permission/tool/cancel/binding-rollback/content-channel behavior still needs real test proof.
- Fixed 13 error codes that were silently unreachable due to a casing bug, and registered 33 more codes that a new automated scan found were missing from the error catalogue.
- Fixed provider MCP refresh: agent, gateway, Git, and GitHub servers now complete startup handshakes from the rendered OpenCode config. OpenCode refreshes no longer modify hand-managed model configs.
- Restored automatic OpenCode model projection without sacrificing user models: AUDiaGentic now manages only its own marked model entry in the real OpenCode config file.
- Added comprehensive protection tests so OpenCode model refreshes retain every user-owned configuration section, not only user-defined models.
- Fixed the OpenCode Hindsight recipe so it installs and configures the real Hindsight plugin without removing your existing OpenCode settings or plugins.
- Provider installation now preserves first-run provider choices instead of automatically enabling detected tools before you choose.
- gpt-auto: CDP connect to existing browser avoids ChatGPT bot detection
- gpt-auto: full conversation flow works - inject prompt via DOM, read response from DOM
- gpt-auto now manages puppeteer-core through the provider lifecycle and stores it in the AUDiaGentic runtime instead of the project root.
- GPT Auto's npm dependency is now stored under the provider runtime namespace, with no harness ownership implied.
- Fixed ChatGPT project navigation — can now find a named project from /projects and start a scoped chat within that project
- Prevented repeated planning ledger events from creating duplicate ledger sections or links.
- gpt-auto ChatGPT automation now rotates realistic prompts, types/pastes with human-like variable timing to avoid bot detection, and can resume the same conversation via its conversation-id.
- Fixed ChatGPT response detection so a follow-up answer is captured even when it is shorter than the previous response.
- gpt-auto now reuses an already-open ChatGPT tab for the same project instead of opening a fresh one each run, tracking the tab-to-conversation mapping in a runtime state file.
- New ChatGPT conversations now start with a random plan item review request instead of reusing the same prompt, so each run asks ChatGPT to review something different.
- Plan-item review prompts now embed the full plan item text so ChatGPT can review it without needing repo access via the GitHub plugin.
- ChatGPT conversations can now be managed as first-class sessions through the AgentSessionTransport seam: open resumes the project's existing chat, prompts stream progress observations to the gateway, and CANCEL stops generation without ever closing your browser tab.
- Fixed truncated ChatGPT responses in the gpt-auto provider by bringing the browser tab to the foreground during generation (ChatGPT pauses streaming for backgrounded tabs) and using a stability window to detect completion.
