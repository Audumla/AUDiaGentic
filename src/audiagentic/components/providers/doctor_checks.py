"""Doctor checks owned by the providers component (read-only)."""
from __future__ import annotations

from typing import Any

from audiagentic.foundation.config.settings import discover_project_root
from audiagentic.foundation.lifecycle.doctor import OK, WARN, CheckResult


def check_qualification(context: Any) -> list[CheckResult]:
    """Enabled providers whose session surface has no evidence for this platform (CFG07)."""
    from audiagentic.runtime.system.platform import release_platform_name

    from .descriptors.registry import all_descriptors
    from .services.config.provider_config import is_provider_enabled
    from .services.qualification import platform_records

    root = discover_project_root(context.project)
    if root is None:
        return [CheckResult("providers.qualification", OK, "no project here (outside a git checkout)")]
    platform = release_platform_name()
    from audiagentic.foundation.config.settings import resolve_settings_cached

    settings = resolve_settings_cached(root)
    findings: list[str] = []
    overridden: list[str] = []
    for provider_id, descriptor in sorted(all_descriptors().items()):
        if not is_provider_enabled(root, provider_id):  # settings and recorded state only: doctor probes nothing
            continue
        for surface in descriptor.session_surfaces:
            if not surface.platforms or any(p.platform == platform for p in surface.platforms):
                continue  # vendor evidence covers this platform (or the surface declares none per platform)
            status = platform_records.check_record(
                provider_id, surface.surface_id, platform, adapter_ref=getattr(surface, "adapter_ref", None) or None,
            )
            if not status.usable and settings.get(f"providers.{provider_id}.allow-unqualified") is True:
                overridden.append(f"{provider_id}/{surface.surface_id}")
            elif not status.usable:
                findings.append(f"{provider_id}/{surface.surface_id} ({status.reason}{': ' + status.detail if status.detail else ''})")
    results: list[CheckResult] = []
    if findings:
        results.append(CheckResult(
            "providers.qualification", WARN,
            f"no usable qualification evidence for {platform}: {'; '.join(findings)}",
            "Run: audiagentic qualify PROVIDER",
        ))
    if overridden:
        results.append(CheckResult(
            "providers.qualification", WARN,
            f"running unqualified on {platform} by explicit override (allow-unqualified): {', '.join(overridden)}",
            "Run: audiagentic qualify PROVIDER, then remove providers.<id>.allow-unqualified",
        ))
    return results or [CheckResult("providers.qualification", OK, f"every enabled surface has evidence for {platform}")]
