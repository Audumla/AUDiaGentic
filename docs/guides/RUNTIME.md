# Service runtime

The gateway and the MCP servers run from `<runtime>/current`, never from a git worktree. `<runtime>` is
`<AUDiaGentic home>/../runtime` (`root PATH` overrides it). `current` is a symlink to one immutable,
non-editable venv `<runtime>/<version>-<id>`; `previous` is the one before it.

```
audiagentic runtime status
audiagentic runtime install ref origin/main [extras acp,a2a,gpt-auto,node] [restart yes]   # or: wheel PATH
audiagentic runtime rollback [restart yes]
```

`install` also runs `prune` (keeps `current`, `previous` and the 2 newest others; never a folder a process uses; clears `.build`). `install` exports the ref with `git archive` (never the working tree), builds a wheel with `uv`, installs it
into a new folder, imports the gateway from that folder as a health check, and only then repoints `current`.
Any failure removes the half-built folder and leaves `current` as it was. `rollback` swaps `current` and
`previous` after the same check. `restart yes` drops `/control/cmd/audiagentic-gateway.restart`, which the
container supervisor acts on for the gateway alone; running MCP servers keep the old runtime until their
client reconnects. A fresh container seeds `current` to the image's `/opt/venv` when it does not exist.

Cleanup tooling treats any worktree a running venv imports from as in use, so an editable development
install cannot be pruned from under a live service.

The default extras are `acp,a2a,gpt-auto,node`: the gateway needs them to run the providers it serves (the gpt-auto
browser provider imports `websockets`). The image's stock venv has none of them, so a gateway left on it cannot
dispatch gpt-auto work: install a runtime before pointing a service at `current`.
