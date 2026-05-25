from __future__ import annotations

import os

from audiagentic.runtime.rig.embedded.config import (
    load_rig_model,
    load_rig_profiles,
    resolve_profile_definition,
)

from .constants import _RIG_CONFIG


def load_model_profile(requested: str | None, model: str) -> tuple[str, dict[str, object]]:
    data = load_rig_profiles(_RIG_CONFIG)
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise SystemExit(f"Invalid rig config: {_RIG_CONFIG}")
    rig_profile, rig_model_id = load_rig_model(_RIG_CONFIG)
    target = requested or os.environ.get("AUDIAGENTIC_RIG_MODEL_PROFILE") or os.environ.get("AUDIAGENTIC_AG_MODEL_PROFILE")
    if target == rig_model_id:
        target = rig_profile
    if not target:
        if model in models:
            target = model
        elif model == rig_model_id:
            target = rig_profile
    if not target:
        raise SystemExit(
            f"Model profile not found: {model}. "
            f"Set AUDIAGENTIC_AG_MODEL, set model in harness config, or ensure the model name matches an entry in {_RIG_CONFIG}."
        )
    if target not in models:
        raise SystemExit(f"Model profile not found: {target}")
    return target, resolve_profile_definition(target, _RIG_CONFIG)
