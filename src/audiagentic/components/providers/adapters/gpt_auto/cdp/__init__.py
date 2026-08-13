"""Small asynchronous Chrome DevTools Protocol client for gpt-auto."""

from .bridge import PythonCdpBridge
from .cdp_browser import CdpBrowserController, CdpPageRef, CdpWindowBounds
from .client import CdpClient, CdpError

__all__ = [
    "CdpClient",
    "CdpError",
    "CdpBrowserController",
    "CdpPageRef",
    "PythonCdpBridge",
    "CdpWindowBounds",
]
