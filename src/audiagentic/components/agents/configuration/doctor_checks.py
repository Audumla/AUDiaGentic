"""Doctor checks owned by the agents component (read-only)."""
from __future__ import annotations

from typing import Any

from audiagentic.foundation.config.settings import discover_project_root
from audiagentic.foundation.lifecycle.doctor import FAIL, OK, WARN, CheckResult

from .agent_files import resolve_agents


def check_agent_files(context: Any) -> list[CheckResult]:
    agents = resolve_agents(project=context.project)
    if not agents:
        return [CheckResult("agents.files", WARN, "no agent files found",
                            "Create one: audiagentic agent add NAME --extends reviewer --provider P --model M")]
    return [CheckResult("agents.files", OK, f"{len(agents)} agent(s) resolve: {', '.join(sorted(agents))}")]


def check_agent_providers(context: Any) -> list[CheckResult]:
    from audiagentic.components.providers.providers_api import (
        check_provider_availability,
        is_provider_enabled_for_launch,
    )

    root = discover_project_root(context.project)
    providers = sorted({agent.fields["provider"] for agent in resolve_agents(project=context.project).values()})
    results = []
    for provider in providers:
        if root is not None and not is_provider_enabled_for_launch(root, provider):
            results.append(CheckResult(f"provider.{provider}", WARN, f"{provider} is disabled in this project",
                                       f"Enable provider {provider} for this project"))
            continue
        available, detail = check_provider_availability(root, provider)
        status = OK if available else WARN if available is None else FAIL
        fix = None if available is not False else f"Make {provider} available: {detail}"
        results.append(CheckResult(f"provider.{provider}", status, detail, fix))
    return results


def check_catalog(context: Any) -> list[CheckResult]:
    """The hosted catalog loads; agent files that shadow agents.yaml entries are reported."""
    del context
    from .effective_catalog import effective_catalog_mapping

    mapping, clashes = effective_catalog_mapping()
    if clashes:
        return [CheckResult("agents.catalog", WARN,
                            f"agent files override agents.yaml entries: {', '.join(clashes)}",
                            "Remove the duplicate entries from agents.yaml (the agent files win)")]
    return [CheckResult("agents.catalog", OK, f"hosted catalog has {len(mapping['agents'])} agent(s)")]
