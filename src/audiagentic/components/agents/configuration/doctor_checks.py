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


def check_gateway_mode(context: Any) -> list[CheckResult]:
    """A provider that anchors its browser window on the gateway dashboard works reliably only with a gateway that serves one."""
    from audiagentic.components.agents.gateway.client import _resolve_implementation_id
    from audiagentic.components.providers.providers_api import list_session_surface_ids

    root = discover_project_root(context.project)
    providers = sorted({agent.fields["provider"] for agent in resolve_agents(project=context.project).values()})
    needing = [provider for provider in providers if "gpt-auto-cdp" in list_session_surface_ids(provider)]
    if not needing:
        return []
    implementation, source = _resolve_implementation_id(root)
    if implementation != "embedded":
        return [CheckResult("agents.gateway", OK, f"gateway implementation {implementation!r} ({source})")]
    return [CheckResult(
        "agents.gateway", WARN,
        f"{', '.join(needing)} anchors its browser window on the gateway dashboard, which the embedded gateway "
        "does not serve; this works only while a dashboard tab or an earlier anchor already exists in the browser",
        "If a gpt-auto request fails with ERR_CONNECTION_REFUSED or project-readiness-failed, run the gateway as a "
        "service: set gateway.implementation to automatic in your user settings (audiagentic config paths shows where)",
    )]


def check_catalog(context: Any) -> list[CheckResult]:
    """The hosted catalog loads; agent files that shadow agents.yaml entries are reported."""
    del context
    from .effective_catalog import effective_catalog_mapping
    from .repository import AgentsConfigValidationError

    try:
        mapping, clashes = effective_catalog_mapping()
    except AgentsConfigValidationError:
        from ..agents_paths import global_agents_config_path

        if global_agents_config_path().exists():
            raise  # a legacy file is present but invalid: that is a real failure
        # Nothing to load yet; agents.files reports the same state with its fix.
        return [CheckResult("agents.catalog", WARN, "no agents defined yet, so there is no hosted catalog",
                            "Create one: audiagentic agent add NAME --extends reviewer --provider P --model M")]
    if clashes:
        return [CheckResult("agents.catalog", WARN,
                            f"agent files override agents.yaml entries: {', '.join(clashes)}",
                            "Remove the duplicate entries from agents.yaml (the agent files win)")]
    return [CheckResult("agents.catalog", OK, f"hosted catalog has {len(mapping['agents'])} agent(s)")]


def check_gateway_code_drift(context: Any) -> list[CheckResult]:
    """The running gateway service must not be older than the code on disk (mixed code fails oddly)."""
    from audiagentic.components.agents.gateway.service.code_drift import (
        check_gateway_code_drift as compare,
    )

    drift = compare()
    if drift.status == "ok":
        return [CheckResult("agents.gateway-code", OK, drift.detail)]
    if drift.status == "unknown":
        return [CheckResult("agents.gateway-code", OK, f"not compared: {drift.detail}")]
    return [CheckResult(
        "agents.gateway-code", WARN, drift.detail,
        "Restart the gateway service so it loads the code on disk (the agent_gateway_restart admin tool), or put "
        "the runtime back to the commit the service loaded; check that no request is running first",
    )]
