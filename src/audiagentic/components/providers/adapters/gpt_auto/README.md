# gpt-auto adapter

ChatGPT browser automation via Chrome DevTools Protocol (CDP). Connects to an existing browser or launches one using the system default profile, preserving ChatGPT login and workspace state.

## Browser Launch Behavior

The gpt-auto provider uses CDP to control a browser instance. The launch behavior depends on whether a browser is already running:

### Default Profile (Recommended)

When launching a **fresh** browser with only `--remote-debugging-port` and `--no-first-run` flags, the browser uses its **default profile** — preserving existing ChatGPT login, workspace, and preferences:

```bash
# Windows PowerShell
Start-Process -FilePath "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" `
  -ArgumentList "--remote-debugging-port=9225","--no-first-run"
```

This works **only when no other browser instance is already running**. If another browser process holds the default profile lock, the new launch will fail silently or refuse CDP binding.

### Why Default Profile Matters

ChatGPT workspace authentication and project context are stored in the default browser profile. Using an isolated profile (`--user-data-dir`) creates a fresh session with no login — which breaks gpt-auto's ability to access your ChatGPT projects.

**Key rule:** Do NOT use `--user-data-dir` unless you explicitly want an isolated session without login state.

## Configuration

Config lives in `.audiagentic/config/providers/gpt-auto.yaml`:

```yaml
settings:
  chatgpt_project_url: https://chat.openai.com/projects/your-project
  browser_port: 9225        # CDP port — must match the browser you launch
  browser-autostart: false  # Set to true for managed browser lifecycle (experimental on Windows)
  response-timeout: 600     # Max seconds per turn
```

### Manual Browser Launch (Stable)

For reliable operation, launch the browser yourself before starting the gateway:

1. **Close all existing browser instances** — default profile can only be held by one process
2. **Launch with CDP flags:**

   ```powershell
   Start-Process -FilePath "path\to\browser.exe" `
     -ArgumentList "--remote-debugging-port=9225","--no-first-run"
   ```

3. **Verify CDP is responding:**

   ```powershell
   Invoke-WebRequest -Uri "http://127.0.0.1:9225/json/version"
   ```

4. Set `browser-autostart: false` in config so the provider connects to your existing instance

### Managed Browser Launch (Experimental)

Setting `browser-autostart: true` enables the `BrowserManager` to automatically launch the browser on first use. This works on Linux and macOS but has known limitations on Windows where detached process flags can prevent the CDP server from initializing properly.

## Session Transport

The `GptAutoSessionTransport` implements the neutral `AgentSessionTransport` protocol (AS28) on top of CDP:

- **Open**: Navigates to ChatGPT workspace, captures live URL for resume
- **Prompt**: Injects text via CDP, waits for response stability
- **Close**: Detaches CDP connection but preserves browser tab state
- **Resume**: Reconnects to existing conversation using captured chat-id or workspace URL

## Troubleshooting

| Symptom | Cause | Fix |
| --------- | ------- | ----- |
| "No browser listening on port X" | Browser not launched with CDP flags | Launch browser manually with `--remote-debugging-port=X` |
| "Project not found" | Default profile has no ChatGPT login | Close browser, launch fresh with default profile |
| CDP binds but workspace missing | Isolated profile used by accident | Remove `--user-data-dir` from launch command |
| Port already in use | Another process holds the port | Use a different port or kill the existing process |
