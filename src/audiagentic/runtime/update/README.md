# runtime/update/

Self-update check and prompt flow.

## Intent

Separate update detection from session APIs and installers so harnesses can offer lightweight version awareness.

## Capabilities

- Detect current installed version.
- Check for newer package versions.
- Build prompt/update messages.
- Run update workflow entrypoints when auto-update or explicit refresh is requested.
