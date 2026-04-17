# DRAFT — Release Please Invocation Options

## Status
Draft design note. MVP baseline remains GitHub-workflow-driven Release Please.

## MVP position
- AUDiaGentic prepares tracked release files locally
- the managed GitHub workflow is the authoritative Release Please execution surface
- operator or CI review is used to observe outcome

## Future options
- GitHub workflow dispatch from AUDiaGentic
- GitHub API polling for workflow completion
- webhook callback integration
- local Release Please CLI execution for non-GitHub environments

## Constraint
Any future option must preserve Release Please as a pluggable release strategy rather than hard-coding one invocation path into core release logic.

## Project bootstrap note

The repository may expose a project-level `release-bootstrap` command that prepares the same tracked docs and managed workflow state before the managed Release Please workflow runs. This is a bootstrap orchestration convenience, not an alternative Release Please backend.
