# Phase 5 — Discord Overlay

## Purpose

Add Discord as an optional overlay on existing approval, event, and release surfaces.

## Scope

- event consumption and filtering
- release summary publishing
- approval request rendering and response
- migration/cutover warnings surfaced to Discord

## Non-goal

Conversation mirroring and full session ownership are not part of MVP Discord.
Those remain future enhancements and must not reshape the core.

## Implementation order

1. PKT-DSC-001 — event subscriber and filter
2. PKT-DSC-002 — release summary publishing
3. PKT-DSC-003 — approval publishing and response handling
4. PKT-DSC-004 — lifecycle and migration warning publishing

## Exit gate

- disabling Discord leaves all earlier phases fully functional
- Discord subscribes to events and uses approval APIs without owning core state
