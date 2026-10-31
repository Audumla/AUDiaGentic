# Release Notes

## v0.46.0

### Features
- Task worktrees now have one command set for starting, publishing, merging, syncing and cleaning up.
- Agents are told the worktree workflow by the project instructions.
- The gateway can be restarted from the audiagentic command line.
- Doctor now reports a gateway running old code or a port held by another install.
- Settings can be written with config set; providers are configured as named instances.

### Fixes
- Gateway restarts no longer fail because the old process still holds the port.
- Release pull requests merge again under the required-checks rule; PyPI publishing waits for an explicit switch.

### Improvements
- Agent tool descriptions are much smaller, with operator tools opt-in.

### Testing
- More tests cover the gateway activity lease.
