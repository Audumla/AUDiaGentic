# $display_name

This repository uses AUDiaGentic workflow jobs.

## Bridge

When a prompt begins with a workflow tag, route it through the repo-owned bridge:

```powershell
$bridge_command
```

If a hook surface is available, `UserPromptSubmit` should hand the raw prompt to the bridge
before planning starts. If the hook surface is partial, fall back to the bridge.
