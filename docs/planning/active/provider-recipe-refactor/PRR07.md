---
id: PRR07
order: 7
plan: plan-provider-recipe-refactor
state: pending
validate-first: true
priority: P1
complexity: mid
---

# Docs, review gates, and regression tests for recipe architecture

## Description

Lock the architecture into docs and tests so future components do not put provider recipes into component packages or domain semantics into foundation toolchains.

## Steps

1. Update `docs/CREATING_A_COMPONENT.md` to explain provider recipes: component owns generic capability/backend state; providers own harness integration recipes; foundation toolchains own generic execution primitives only.
2. Update provider adapter docs to show where provider-specific Hindsight/LSP recipes live and how to add a new one.
3. Add architecture regression checks, if feasible, for forbidden imports/strings: `foundation/toolchains` must not mention provider IDs, Hindsight, memory, coding-lsp, or MCP-specific helper APIs.
4. Add memory regression checks that `components/memory` does not enumerate providers or import provider surface managers.
5. Add provider recipe tests covering dry-run, install, status/probe, uninstall/prune, and artifact ownership.
6. Add a migration note for existing prompt-only memory contributions so users understand what changed.

## Files

docs/CREATING_A_COMPONENT.md
src/audiagentic/components/providers/adapters/README.md
src/audiagentic/foundation/toolchains/README.md
tests/unit/foundation/toolchains/
tests/unit/memory/
tests/unit/providers/

## Validation

- Docs state all three ownership boundaries explicitly.
- Tests fail if provider-specific recipe logic is placed in memory or foundation toolchains.
- Provider recipe tests cover at least command, MCP/config, plugin/config, and rules/block cleanup patterns.
- Release/ledger event recorded after implementation if project process requires it.

## Effort & Risk

Risk is docs lagging implementation. Make docs part of acceptance, not cleanup.

## Notes

This closes the loop from the original failure: plan and docs must prevent the same architecture error.
