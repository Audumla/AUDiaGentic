"""Composition root for the `audiagentic` process.

Only this package reads composition bindings and builds the service graph.
"""

from audiagentic.runtime.bootstrap.application_host import ApplicationHost
from audiagentic.runtime.bootstrap.composition import (
    APPLICATION_HOST,
    build_application_graph,
    builtin_contributions,
)

__all__ = [
    "APPLICATION_HOST",
    "ApplicationHost",
    "build_application_graph",
    "builtin_contributions",
]
