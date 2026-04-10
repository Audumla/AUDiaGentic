# Archive Decisions

## Decision summary

This archive pass preserves the older pre-ACP provider/prompt/Discord line without leaving it in active governance.

The main decisions were:

1. Move, do not delete, all clearly superseded Discord, Continue, and local-openai implementation/spec/packet docs.
2. Treat the moved packet lines as cancelled scope, not merely deferred.
3. Remove the archived line from active indexes, roadmap text, provider index, contracts, and tracker/registry summaries.
4. Preserve reusable guidance separately before archive-only material becomes harder to find.
5. Leave broader secondary stale references visible in the execution report when they are outside the primary governing-doc pass.

## Active direction after this pass

- ACP-first internal provider/session direction
- OpenACP-preferred external messaging/control direction
- reduced active provider scope
- canonical project documentation, issue-tracking, and changelog-extension direction instead of a Discord-specific overlay revival

## Non-decisions

- This pass does not introduce new code-package roots for ACP/OpenACP or documentation-sync work.
- This pass does not remove implementation history from git.
- This pass does not silently repurpose Qwen dependencies that were coupled to local-openai packet lines; those are left as explicit follow-up candidates.
