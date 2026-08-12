---
name: ag-check-in-prep
description: Plan a careful, ledger-grouped code check-in — never git stash
---

# Check-in prep

Do:
- Read the full working tree state first (git_status, git_diff, git_diff_staged) before proposing anything.
- Call the ledger's `get_pending_events` tool to get the pre-computed check-in grouping — it clusters unreleased events via union-find, not a hint to re-derive by hand:
  - `group_by="plan-items"` (default) clusters events that share a plan-item-id — prefer this when the work traces to tracked plan items.
  - `group_by="files"` clusters events with overlapping file sets — use this when work wasn't tracked by plan item.
  - Each returned entry in `groups` is one commit candidate: its `files` list is the stage set, its `summaries` (event-id, change-class, user-summary-candidate) are the material for the commit message.
  - Entries in `ungrouped` are singleton events with no overlap with anything else pending — each is its own commit unless you find a reason to fold it in manually.
  - Use `get_fragment(event_id)` when a group's summary is too thin to write a good commit message and you need the full event.
- Treat the returned groups as the check-in plan; state it (group → files → message) before staging anything. Only deviate from the ledger's clustering with a stated reason.
- Stage and commit deliberately per group with the git MCP tools (git_add naming exactly that group's files, git_commit) — never a blanket add of the whole tree.
- Re-run git_status after each commit to confirm only the intended files moved before starting the next group.
- If working-tree changes exist with no matching pending ledger event, record one first (ag-ledger's `record_change_event`) so it can be grouped — don't check in untracked work blind.

Do not:
- never use `git stash`, under any circumstance — this repo is a shared, multi-agent working tree and a stash can silently swallow or collide with another session's live edits; if work needs to be set aside, split it into its own deliberate group or leave it uncommitted and say so
- do not use destructive git operations (reset --hard, clean -f, checkout/restore discarding edits) as a shortcut to get to a clean tree
- do not commit generated release artifacts or ledger fragments directly — those are owned by the release and ledger components
- do not broaden scope beyond the tagged request
