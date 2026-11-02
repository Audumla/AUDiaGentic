# Service runtime

The gateway and the MCP servers run from `<runtime>/current`, never from a git worktree. `<runtime>` is
`<AUDiaGentic home>/../runtime` (`root PATH` overrides it). `current` is a symlink to one immutable,
non-editable venv `<runtime>/<version>-<id>`; `previous` is the one before it.

```
audiagentic runtime status
audiagentic runtime install ref origin/main [extras acp,a2a] [restart yes]   # or: wheel PATH
audiagentic runtime rollback [restart yes]
```

`install` exports the ref with `git archive` (never the working tree), builds a wheel with `uv`, installs it
into a new folder, imports the gateway from that folder as a health check, and only then repoints `current`.
Any failure removes the half-built folder and leaves `current` as it was. `rollback` swaps `current` and
`previous` after the same check. `restart yes` drops `/control/cmd/audiagentic-gateway.restart`, which the
container supervisor acts on for the gateway alone; running MCP servers keep the old runtime until their
client reconnects. A fresh container seeds `current` to the image's `/opt/venv` when it does not exist.

Cleanup tooling treats any worktree a running venv imports from as in use, so an editable development
install cannot be pruned from under a live service.
