from __future__ import annotations

import json
import os
from pathlib import Path

from .constants import _MODELS_JSON


def load_model_profile(requested: str | None, model: str) -> tuple[str, dict[str, object]]:
    data = json.loads(_MODELS_JSON.read_text(encoding="utf-8"))
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise SystemExit(f"Invalid model profile file: {_MODELS_JSON}")
    target = requested or os.environ.get("AUDIAGENTIC_RIG_MODEL_PROFILE") or os.environ.get("AUDIAGENTIC_AG_MODEL_PROFILE")
    if not target:
        if model in models:
            target = model
        else:
            for name, raw_profile in models.items():
                if isinstance(raw_profile, dict) and model in raw_profile.get("aliases", []):
                    target = str(name)
                    break
    if not target:
        raise SystemExit(
            f"Model profile not found: {model}. "
            f"Set AUDIAGENTIC_AG_MODEL, set model in harness config, or ensure the model name or alias matches an entry in {_MODELS_JSON}."
        )
    raw = models.get(target)
    if raw is None:
        for name, raw_profile in models.items():
            if isinstance(raw_profile, dict) and target in raw_profile.get("aliases", []):
                target = str(name)
                raw = raw_profile
                break
    if not isinstance(raw, dict):
        raise SystemExit(f"Model profile not found: {target}")
    return target, raw
