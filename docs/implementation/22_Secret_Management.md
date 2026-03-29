# Secret Management

## Purpose

Document the MVP secret-handling rules for local development and CI.

## MVP policy

AUDiaGentic v1 supports **`env:` references only**.

Example:
```yaml
auth-ref: env:ANTHROPIC_API_KEY
```

## Required rules

- never store raw secrets in tracked docs
- never store raw secrets in `.audiagentic/*.yaml`
- never place real secrets in fixtures
- never echo secrets into logs or JSON error output
- packet tests that require real credentials must be opt-in and skipped by default

## Local development

Set provider secrets in the shell or OS environment outside tracked files.

Example:
```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
```

## CI examples

### GitHub Actions
```yaml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

### GitLab CI
```yaml
variables:
  ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
  OPENAI_API_KEY: $OPENAI_API_KEY
```

## Validation requirement

Phase 0 validators must fail if likely raw secrets appear in tracked config or fixtures.

## DRAFT future enhancements

- other secret reference schemes
- vault integrations
- key rotation playbooks
- service-account credential partitioning
