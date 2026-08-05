"""gpt-auto — browser-driven ChatGPT via puppeteer-core CDP connect.

Connects to an already-running Chrome/Brave (``--remote-debugging-port``) so
``navigator.webdriver`` stays ``false`` — no bot detection.

Two interfaces:
1. **Framework adapter** — ``adapter.run(packet_ctx, provider_cfg)`` is the
   entry point called by the AUDiaGentic provider execution service.
2. **Standalone API** — ``run(prompt) -> str`` for direct use outside the
   framework.

No external API connectivity required — just a ChatGPT account and a browser
with remote debugging enabled.
"""

from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.provider import (
    GptAutoError,
    run,
    run_sync,
)

__all__ = [
    "GptAutoConfig",
    "GptAutoError",
    "run",
    "run_sync",
]