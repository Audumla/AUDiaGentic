# Release Notes

## v0.6.1

### Documentation
- Validate and complete silent GPT conversation restoration after browser tab changes, with deployed same-session live tests.

### Fixes
- Resume idle GPT conversations after browser restart without failing on expired physical tab IDs or replaying earlier prompts.
- Harden silent GPT conversation restoration against stale browser targets and recovery races.
