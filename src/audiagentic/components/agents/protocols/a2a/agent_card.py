"""Deterministic Agent Card projection for published Agent Definitions."""
from __future__ import annotations


def build_agent_card(definition: dict) -> dict:
    publication = definition.get("publication") or {}
    if not publication.get("a2a"):
        raise ValueError("only A2A-published Agent Definitions have Agent Cards")
    return {
        "name": definition["agent_id"],
        "description": definition.get("description") or definition.get("name"),
        "skills": [{"id": skill, "name": skill} for skill in definition.get("advertised_skills", [])],
        "capabilities": {"streaming": False, "pushNotifications": False},
    }
