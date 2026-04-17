# AUDiaGentic Extension Scope Boundaries for Coordinator and UI

## Purpose

Make the extension boundary explicit so coordinator and UI behavior can consume backend seams without becoming part of core AUDiaGentic scope.

## Boundary rule

- AUDiaGentic defines the backend contracts.
- Coordinator/board/UI systems may consume those contracts.
- Coordinator/UI concerns must not become baseline dependencies of core AUDiaGentic modules.

## What is allowed

- query seams
- control seams
- event consumption seams
- future board/UI clients built on top of the stable backend contracts

## What is not allowed

- UI-specific control logic in core backend modules
- coordinator-specific source-of-truth behavior
- baseline dependency on an external board or UI
