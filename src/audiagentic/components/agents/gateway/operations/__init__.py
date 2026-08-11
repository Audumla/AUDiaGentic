"""Durable, provider-independent gateway operations (SH24).

This package is deliberately separate from the request/session execution
stores.  Its operation records coordinate operator work only; they never
become an alternate request lifecycle or queue authority.
"""

from .application import GatewayOperationsApplication
from .contracts import ManagementCommand, ManagementOperationKind
from .evidence import EvidenceFinding, GatewayWorkEvidenceReader
from .executor import GatewayOperationExecutor
from .notifier import ManagementWorkNotifier, NoopManagementWorkNotifier
from .operation_store import ManagementOperationStore
from .pump import ManagementOperationPump
from .reconcile import GatewayReconcileExecutor

__all__ = [
    "EvidenceFinding",
    "GatewayOperationExecutor",
    "GatewayOperationsApplication",
    "GatewayReconcileExecutor",
    "GatewayWorkEvidenceReader",
    "ManagementCommand",
    "ManagementOperationKind",
    "ManagementOperationPump",
    "ManagementOperationStore",
    "ManagementWorkNotifier",
    "NoopManagementWorkNotifier",
]
