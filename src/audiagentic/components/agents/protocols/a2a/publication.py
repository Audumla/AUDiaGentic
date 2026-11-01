"""What the A2A facade serves, derived from the settings and the published agent catalog (SH65b-3).

Settings (see ``settings.py``) name the loopback port, the externally advertised origin and the gateway project
ids. Which agents are served is NOT configured: every Agent Definition published to A2A in the
machine-global catalog is served in each project. Cards are built from that catalog (local data the gateway
itself uses, so the facade needs no credential to publish them) and carry only what the adapter implements.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from a2a.types import a2a_pb2 as pb

from audiagentic.foundation.contracts.errors import make_error_factory

from .facade import A2aRoute
from .settings import A2aSettings

error = make_error_factory("VAL", "A2A", "agents")

def published_agents(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Definitions published to A2A, in a stable order."""
    chosen = [d for d in definitions if (d.get("publication") or {}).get("a2a")]
    return sorted(chosen, key=lambda d: str(d["agent_id"]))


def build_cards(settings: A2aSettings, definitions: list[dict[str, Any]]) -> dict[A2aRoute, pb.AgentCard]:
    """One Agent Card per served (project, published agent). URLs come from the validated base URL only."""
    if settings.base_url is None:
        raise error(6, "a2a.base_url is not set")
    cards: dict[A2aRoute, pb.AgentCard] = {}
    for project_id in settings.projects:
        for definition in published_agents(definitions):
            route = A2aRoute(project_id, str(definition["agent_id"]))
            cards[route] = _card(definition, settings.base_url + route.path)
    return cards


def _card(definition: dict[str, Any], url: str) -> pb.AgentCard:
    card = pb.AgentCard(
        name=str(definition.get("name") or definition["agent_id"]),
        description=str(definition.get("description") or definition.get("name") or definition["agent_id"]),
        version="1",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )
    interface = card.supported_interfaces.add()
    interface.url, interface.protocol_binding, interface.protocol_version = url, "JSONRPC", "1.0"
    card.capabilities.streaming = False
    card.capabilities.push_notifications = False
    card.capabilities.extended_agent_card = False
    for skill in definition.get("advertised_skills") or []:
        card.skills.add(id=str(skill), name=str(skill), description=str(skill), tags=[str(skill)])
    # The facade forwards the caller's own bearer to the gateway, which authenticates it.
    card.security_schemes["bearer"].http_auth_security_scheme.scheme = "Bearer"
    card.security_requirements.add().schemes["bearer"].list.extend([])
    return card


def served_routes(cards: Mapping[A2aRoute, pb.AgentCard]) -> tuple[A2aRoute, ...]:
    return tuple(sorted(cards, key=lambda route: (route.project_id, route.agent_id)))
