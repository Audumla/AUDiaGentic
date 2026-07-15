"""Validation and deterministic reference views for provider capability facts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

from .base import ProviderCapabilityFact, ProviderDescriptor

EVIDENCE_TIERS = frozenset(
    {"unverified", "documentation", "installed-artifact", "round-trip", "execution"}
)
REVIEW_STATES = frozenset({"pending-review", "verified", "quarantined"})
_NON_SUBJECT_FIELDS = frozenset({"annotations", "capability_facts"})
_DESCRIPTOR_FIELDS = frozenset(field.name for field in fields(ProviderDescriptor))


def _validation_error(number: int, message: str, **details: Any) -> AudiaGenticError:
    return AudiaGenticError(
        code=f"VAL-PCAP-{number:03d}",
        kind="providers",
        message=message,
        details=details or None,
    )


def _member_resolves(value: Any, member: str) -> bool:
    if isinstance(value, Mapping):
        return member in value
    if isinstance(value, tuple):
        if value and hasattr(value[0], "host") and hasattr(value[0], "capability_id"):
            return any(f"{item.host}:{item.capability_id}" == member for item in value)
        if value and hasattr(value[0], "rel_path"):
            return any(item.rel_path == member for item in value)
        return member in value
    return False


def _subject_resolves(descriptor: ProviderDescriptor, fact: ProviderCapabilityFact) -> bool:
    subject = fact.subject.strip()
    if subject.startswith("external:"):
        return bool(subject.removeprefix("external:").strip() and fact.evidence.fact_anchor)

    field_name, separator, member = subject.partition("[")
    if field_name not in _DESCRIPTOR_FIELDS or field_name in _NON_SUBJECT_FIELDS:
        return False
    value = getattr(descriptor, field_name)
    if not separator:
        return value is not None and value != () and value != {} and value != []
    if not member.endswith("]"):
        return False
    return _member_resolves(value, member[:-1])


def validate_provider_capability_facts(descriptor: ProviderDescriptor) -> None:
    """Validate identities, evidence values, and descriptor subject links."""
    seen: set[str] = set()
    for fact in descriptor.capability_facts:
        capability_id = fact.capability_id.strip()
        if not capability_id:
            raise _validation_error(1, "capability_id must not be empty")
        if capability_id in seen:
            raise _validation_error(
                2,
                "duplicate capability_id within provider",
                **{"provider-id": descriptor.provider_id, "capability-id": capability_id},
            )
        seen.add(capability_id)

        evidence = fact.evidence
        if evidence.evidence_tier not in EVIDENCE_TIERS:
            raise _validation_error(
                3,
                "invalid capability evidence tier",
                **{"capability-id": capability_id, "evidence-tier": evidence.evidence_tier},
            )
        if evidence.review_state not in REVIEW_STATES:
            raise _validation_error(
                4,
                "invalid capability review state",
                **{"capability-id": capability_id, "review-state": evidence.review_state},
            )
        if evidence.review_state == "verified" and not (
            evidence.tool_version and evidence.fact_anchor
        ):
            raise _validation_error(
                5,
                "verified capability fact requires tool_version and fact_anchor",
                **{"capability-id": capability_id},
            )
        if not _subject_resolves(descriptor, fact):
            raise _validation_error(
                7,
                "capability fact subject does not resolve",
                **{
                    "provider-id": descriptor.provider_id,
                    "capability-id": capability_id,
                    "subject": fact.subject,
                },
            )


def validate_capability_fact_catalog(
    descriptors: Mapping[str, ProviderDescriptor],
) -> None:
    """Validate all facts using (provider_id, capability_id) identities."""
    identities: set[tuple[str, str]] = set()
    for provider_id, descriptor in descriptors.items():
        validate_provider_capability_facts(descriptor)
        for fact in descriptor.capability_facts:
            identity = (provider_id, fact.capability_id)
            if identity in identities:
                raise _validation_error(
                    8,
                    "duplicate provider capability identity",
                    **{"provider-id": provider_id, "capability-id": fact.capability_id},
                )
            identities.add(identity)


def capability_facts_payload(
    descriptors: Mapping[str, ProviderDescriptor],
) -> dict[str, Any]:
    """Return a lossless, deterministic machine representation."""
    validate_capability_fact_catalog(descriptors)
    return {
        "contract-version": "v1",
        "providers": [
            {
                "provider_id": provider_id,
                "capability_facts": [
                    {
                        "capability_id": fact.capability_id,
                        "subject": fact.subject,
                        "mechanism": fact.mechanism,
                        "constraints": list(fact.constraints),
                        "limitations": list(fact.limitations),
                        "support_assessment": fact.support_assessment,
                        "action_needed": fact.action_needed,
                        "evidence": {
                            "evidence_tier": fact.evidence.evidence_tier,
                            "tool_version": fact.evidence.tool_version,
                            "fact_anchor": fact.evidence.fact_anchor,
                            "review_state": fact.evidence.review_state,
                        },
                    }
                    for fact in sorted(
                        descriptor.capability_facts,
                        key=lambda item: item.capability_id,
                    )
                ],
            }
            for provider_id, descriptor in sorted(descriptors.items())
        ],
    }


def render_capability_facts_json(
    descriptors: Mapping[str, ProviderDescriptor],
) -> str:
    """Render the lossless machine view as stable JSON."""
    return json.dumps(
        capability_facts_payload(descriptors),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"


def _markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (tuple, list)):
        value = "<br>".join(str(item) for item in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_capability_facts_markdown(
    descriptors: Mapping[str, ProviderDescriptor],
) -> str:
    """Render a concise deterministic human reference table."""
    validate_capability_fact_catalog(descriptors)
    headers = (
        "Provider",
        "Capability",
        "Subject",
        "Mechanism",
        "Constraints",
        "Limitations",
        "Assessment",
        "Action needed",
        "Evidence tier",
        "Tool version",
        "Fact anchor",
        "Review state",
    )
    lines = [
        "# Provider Capability Facts",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for provider_id, descriptor in sorted(descriptors.items()):
        for fact in sorted(descriptor.capability_facts, key=lambda item: item.capability_id):
            evidence = fact.evidence
            row = (
                provider_id,
                fact.capability_id,
                fact.subject,
                fact.mechanism,
                fact.constraints,
                fact.limitations,
                fact.support_assessment,
                fact.action_needed,
                evidence.evidence_tier,
                evidence.tool_version,
                evidence.fact_anchor,
                evidence.review_state,
            )
            lines.append("| " + " | ".join(_markdown_cell(value) for value in row) + " |")
    return "\n".join(lines) + "\n"
