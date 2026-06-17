# providers/adapters/claude/

Claude provider adapter.

Owns Claude-specific descriptor, execution bridge, hook integration, and managed surface content. `hooks.py` exists because Claude integration needs extra lifecycle behavior beyond base adapter/descriptor pattern.
