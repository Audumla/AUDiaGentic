"""Shared narrow mode vocabularies for provider automation family contracts.

Three value-sets recur across the family Mode aliases (managed-mcp,
managed-hooks, language-server, plugin-entry, model-projection,
generated-surface, self-provided-lsp). Each family keeps its own name
(e.g. ``ManagedMcpMode``) for readability at call sites, but the accepted
values are declared once here rather than restated per file.

``CliLifecycleMode`` (plan/apply/prune/status/upgrade-status/upgrade) is a
distinct, wider vocabulary of CLI verbs and intentionally does not alias to
any of these — see contracts/cli_lifecycle.py.
"""
from __future__ import annotations

from typing import Literal

ProviderAutomationMode = Literal["plan", "apply", "prune", "status"]
ProviderReconcileMode = Literal["apply", "prune", "status"]
ProviderApplyStatusMode = Literal["apply", "status"]

__all__ = [
    "ProviderApplyStatusMode",
    "ProviderAutomationMode",
    "ProviderReconcileMode",
]
