from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


@dataclass(frozen=True)
class ModelsProbeResult:
    payload: dict[str, object]
    first_model_id: str | None


def probe_models_endpoint(endpoint: str, timeout: float = 10.0) -> ModelsProbeResult | None:
    try:
        with urlopen(f"{endpoint}/models", timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read())
    except (URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None
    return ModelsProbeResult(payload=payload, first_model_id=_extract_first_model_id(payload))


def require_models_endpoint(endpoint: str, timeout: float = 15.0) -> ModelsProbeResult:
    status_url = f"{endpoint}/models"
    try:
        with urlopen(status_url, timeout=timeout) as response:
            if response.status != 200:
                raise SystemExit(f"Rig health failed: {status_url} -> HTTP {response.status}")
            payload = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.reason
        try:
            body = json.loads(exc.read())
            error = body.get("error", {})
            if isinstance(error, dict):
                detail = error.get("message") or detail
        except Exception:
            pass
        raise SystemExit(f"Rig not ready: {status_url} -> HTTP {exc.code}: {detail}") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise SystemExit(f"Rig unavailable: {status_url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Rig health returned invalid JSON: {status_url}") from exc

    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise SystemExit(f"Rig health returned no models: {status_url}")
    return ModelsProbeResult(payload=payload, first_model_id=_extract_first_model_id(payload))


def _extract_first_model_id(payload: dict[str, object]) -> str | None:
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and first.get("id"):
            return str(first["id"])
    models = payload.get("models")
    if isinstance(models, list) and models:
        first = models[0]
        if isinstance(first, dict) and first.get("model"):
            return str(first["model"])
        if isinstance(first, dict) and first.get("name"):
            return str(first["name"])
    return None
