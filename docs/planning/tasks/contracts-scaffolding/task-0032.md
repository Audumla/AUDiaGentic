---
id: task-0032
label: '[PKT-FND-001](task-0032): Canonical IDs and Naming Normalization'
state: draft
summary: Define canonical ID formats and naming conventions
spec_ref: spec-0004
---


# Description

Implement canonical ID formats and naming normalization.

# [PKT-FND-001](task-0022): Canonical IDs and Naming Normalization

## Purpose

Define canonical ID formats and naming conventions for all AUDiaGentic entities.

## Scope

- Packet ID format (PKT-XXX-NNN)
- Task ID format (task-NNNN)
- Plan ID format (plan-NNNN)
- Spec ID format (spec-NNNN)
- Naming conventions for files, directories, classes, functions

## Implementation

1. Define ID format regex patterns
2. Create ID validator script
3. Implement naming normalization utilities
4. Update all existing IDs to canonical format

## Acceptance Criteria

1. All IDs match canonical format
2. Naming validator passes on all docs
3. ID conflicts detected and reported
