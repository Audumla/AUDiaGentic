# PKT-FND-010 — Repository inventory, migration map, and ambiguity report

**Phase:** Phase 0.3  
**Status:** READY_TO_START  
**Owner:** Foundations  
**Scope:** workspace

## Goal

Inventory the current repository, map existing modules into the target domains, and document ambiguous or mixed-responsibility areas before code moves begin.

## Dependencies

- current baseline verified
- `49_Repository_Domain_Refactor_and_Package_Realignment.md` in place

## Owns

- migration map document
- ambiguity report for mixed-responsibility modules
- first-pass old-path -> target-domain mapping

## Acceptance criteria

- major modules/folders are classified into canonical domains
- mixed-responsibility hotspots are explicitly listed
- refactor notes capture unresolved ambiguity instead of hiding it
