"""Pi's one-shot runner with real lifecycle observation.

The regular descriptor runner already owns Pi's ``--print`` transport and
completion normalization.  This tiny adapter only contributes the request
private extension that reports actual Pi lifecycle events to the worker.
"""

from __future__ import annotations

from typing import Any

from audiagentic.components.providers.adapters.base_runner import make_cli_runner
from audiagentic.components.providers.adapters.pi.print_activity import (
    prepare_print_activity_launch,
)
from audiagentic.components.providers.descriptors.registry import all_descriptors
from audiagentic.foundation.contracts.errors import AudiaGenticError


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    descriptor = all_descriptors().get("pi")
    execution = getattr(descriptor, "execution", None) if descriptor else None
    if not isinstance(execution, dict):
        raise AudiaGenticError(
            code="INT-PI-001",
            kind="providers",
            message="Pi execution recipe is unavailable",
            details={},
        )
    return make_cli_runner(
        "pi",
        execution,
        prepare_launch=prepare_print_activity_launch,
    )(packet_ctx, provider_cfg)


__all__ = ["run"]
