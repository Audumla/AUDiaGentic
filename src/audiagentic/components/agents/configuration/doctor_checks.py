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


def check_gateway_port(context: Any) -> list[CheckResult]:
    """A gateway port held by another home's service explains CON-MSVC-037; name the setting that fixes it."""
    from audiagentic.components.agents.gateway.service.port_holder import (
        check_gateway_port as inspect_port,
    )

    finding = inspect_port()
    if finding.status == "ok":
        return [CheckResult("agents.gateway-port", OK, finding.detail)]
    if finding.status == "unknown":
        return [CheckResult("agents.gateway-port", WARN, finding.detail,
                            "Check what listens on that port, or set gateway.port to a free port in your user settings")]
    other = finding.holder.home if finding.holder else None
    fix = (f"Use that service by setting home: {other} in your user settings (audiagentic config paths shows "
           "where), or give this home its own port with gateway.port") if other else (
        "Stop the process holding the port if it is not a gateway you want, or set gateway.port to a free port "
        "in your user settings")
    return [CheckResult("agents.gateway-port", WARN, finding.detail, fix)]


def check_a2a(context: Any) -> list[CheckResult]:
    """The A2A facade (``a2a`` settings): read-only. Nothing is started, bound or contacted."""
    del context
    from audiagentic.components.agents.protocols.a2a.settings import load_settings
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        settings = load_settings()
    except AudiaGenticError as error:
        return [CheckResult("agents.a2a", FAIL, f"a2a settings are invalid: {error.message}",
                            "Fix the a2a section (port, base_url, projects) in your user settings")]
    if not settings.enabled:
        return [CheckResult("agents.a2a", OK, "the A2A facade is off (a2a.enabled is not set)")]
    results: list[CheckResult] = []
    try:
        import a2a.server.routes  # noqa: F401
    except ImportError:
        results.append(CheckResult("agents.a2a.sdk", FAIL, "the A2A SDK is not installed",
                                   'Install it: pip install "audiagentic[a2a]"'))
    else:
        results.append(CheckResult("agents.a2a.sdk", OK, "the A2A SDK is installed"))
    results.append(_a2a_connector_result())
    results.append(_a2a_publication_result())
    results.append(CheckResult("agents.a2a", OK, f"serving {len(settings.projects)} project(s) on 127.0.0.1:{settings.port}, "
                                                 f"advertised as {settings.base_url}"))
    return results


def _a2a_connector_result() -> CheckResult:
    from audiagentic.components.agents.gateway.settings import gateway_setting
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    connector = gateway_setting("connector")
    if not connector:
        return CheckResult("agents.a2a.connector", FAIL, "no gateway connector is configured",
                           "Connect to a shared gateway: audiagentic gateway connect config FILE")
    try:
        from pathlib import Path

        from audiagentic.components.agents.gateway.service.shared_config import (
            load_shared_connector_config,
        )

        document = load_shared_connector_config(Path(str(connector)).expanduser())
    except AudiaGenticError as error:
        return CheckResult("agents.a2a.connector", FAIL, f"the gateway connector does not load: {error.message}",
                           "Fix or recreate the connector document")
    if document.mode != "shared":
        return CheckResult("agents.a2a.connector", FAIL,
                           "the facade needs a shared connector: a plain gateway has no principals to forward",
                           "Connect to a shared gateway (mode: shared)")
    return CheckResult("agents.a2a.connector", OK, f"shared connector {document.server_id} is configured")


def _a2a_publication_result() -> CheckResult:
    from pathlib import Path

    from audiagentic.components.agents.configuration.management import list_agent_definitions
    from audiagentic.components.agents.protocols.a2a.publication import published_agents

    try:
        published = published_agents(list_agent_definitions(Path.cwd()))
    except Exception as error:  # noqa: BLE001 - a broken catalog is reported by agents.catalog; here it is one fact
        return CheckResult("agents.a2a.agents", WARN, f"the agent catalog could not be read ({type(error).__name__})",
                           "See agents.catalog")
    if not published:
        return CheckResult("agents.a2a.agents", WARN, "no agent is published to A2A, so the facade serves nothing",
                           "Set publication.a2a on an Agent Definition")
    return CheckResult("agents.a2a.agents", OK, f"{len(published)} agent(s) published to A2A: "
                                                f"{', '.join(str(d['agent_id']) for d in published)}")
