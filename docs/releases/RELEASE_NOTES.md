# Release Notes

## v0.5.3

### Documentation
- Audited every GA gateway-reliability plan with terminal Dev-GPT evidence and updated the planning records: completed items are marked completed, unsupported completion claims are active again, and pending recovery work now has explicit safety, dependency, and validation gates.
- Document how gateway requests recover when the browser disconnects or restarts.
- Complete the admission diagnostics and browser restart recovery plans with code review, simulated production E2E and live restart evidence.

### Fixes
- Distinguish proven-unsent gateway admission failures from ambiguous submissions without weakening duplicate-send protection.
- Keep uncertain admission evidence conservative and preserve safe diagnostic proof across repeated storage.
- Keep active GPT requests recoverable across browser outages without replaying prompts or stealing tab focus.
- Recover submitted requests safely across browser and gateway restarts without duplicate prompts or foreground tab cycling.
- Close recovery ownership and capture races and validate browser-offline restart through the production response observer.
- Complete restart recovery through durable response delivery and checkpoint cleanup instead of leaving completed GPT replies stuck as running.
- Recover completed responses even if the gateway restarted before the prompt ID was saved, without allowing duplicate sends or telemetry-only failures.

### Testing
- Run browser restart and recovery regressions automatically in required CI gates.
- Ensure required CI actually runs the browser recovery tests instead of failing collection on a missing optional socket package.
