# Draft Provider Auto-Install and Availability Orchestration

Status: draft
Phase: 4.7
Feature slot: .7

## Purpose

This spec defines how AUDiaGentic can detect provider availability and, when permitted by
project configuration, automatically install or bootstrap the provider integration that is
missing.

The goal is to let a project declare provider availability behavior once and then let the
installer or runtime bridge do the right thing when a provider CLI, extension, or local
bridge is not present.

## Problem statement

At the moment, provider configuration can say how a provider should be used, but the system
does not yet define a full install-or-bootstrap path when the provider is missing.

That creates two gaps:
- projects cannot declare whether missing providers should be auto-installed, prompted, or skipped
- the installer cannot prepare provider-specific local surfaces during project setup in a standard way

## Normative rules

- auto-install behavior must be opt-in through configuration
- the installer must never silently install a provider without a declared policy
- provider execution, prompt-trigger behavior, and provider installation remain separate layers
- a provider may declare a CLI install path, an editor-extension install path, a repo-bridge install path, or a manual-only path
- backend-only providers may expose bridge bootstrap or availability wiring even when they do not install a native CLI
- any install action must be re-checked with the same provider availability probe after completion
- install policies must be project-local and should live under `.audiagentic/` configuration

## Availability model

The provider layer should answer three questions before a job or surface launch runs:
1. is the provider configured
2. is the provider available on this machine or in this workspace
3. if not, should the installer attempt a provider-specific bootstrap

A provider can be considered available when one of the following is true:
- the CLI exists on PATH
- the editor extension or hook surface is installed and reachable
- the repo bridge that fronts a backend-only provider is present
- the provider-specific bootstrap completed successfully during project install

## Configuration contract

This phase introduces a provider installation policy that can be declared in either the
provider config or the project config, depending on whether the behavior is provider-specific
or project-wide.

Suggested fields:
- `install-mode`: `external-configured`, `auto-install`, `bridge-only`, or `manual`
- `install-policy.on-missing`: `auto`, `prompt`, or `skip`
- `install-policy.requires-confirmation`: boolean
- `install-command`: command or command array used for bootstrap
- `install-check`: command or predicate used to re-validate availability
- `install-source`: `cli`, `editor-extension`, `repo-script`, or `bridge`
- `post-install-command`: optional follow-up command for auth/login/config sync

The exact schema fields may be split across the provider config and project config, but the
semantics above must remain stable.

## Shared orchestration contract

The installer or runtime bridge should follow this flow:
1. check provider availability using the existing status/check path
2. if available, continue without modification
3. if unavailable, consult project and provider install policy
4. if policy allows, run the provider-specific bootstrap
5. re-check availability
6. record the installation outcome in project-local runtime state

## Surface classes

### CLI installable

The provider can be installed or bootstrapped through a command-line step, package manager,
or repo-owned helper script.

### Editor installable

The provider surface is a local editor extension or hook surface and must be prepared by
repository-owned setup guidance or a workspace bootstrap command.

### Bridge-only

The provider is backend-only or only partially local. The repository-owned bridge may be
installed or configured automatically, but the backend itself may remain external.

### Manual-only

The provider must be installed by the user or administrator and the project may only verify
availability and give instructions.

## Existing contract impact

This feature does not replace the current provider execution contract or the prompt-trigger
launch contract.

It adds a new layer above them:
- Phase 4.3 still governs prompt-tag recognition
- Phase 4.4 still governs provider execution behavior
- Phase 4.6 still governs prompt-trigger launch behavior
- Phase 4.7 governs availability checks and auto-install/bootstrap orchestration

## Non-goals

- silently changing the user’s environment without config permission
- changing provider execution semantics
- redefining prompt tags or launch grammar
- replacing the provider model catalog and selection contract
