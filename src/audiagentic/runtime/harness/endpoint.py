"""Reaching the model server a harness talks to.

The server is an OpenAI-compatible endpoint that is already running (a llama-server
or any other); AUDiaGentic does not launch or host it.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelsProbeResult:
    payload: dict[str, object]
    first_model_id: str | None


def _error(prefix: str, number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(prefix=prefix, component="HRNEP", number=number, kind="harness", message=message, details=details)


def _first_model_id(payload: dict[str, object]) -> str | None:
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get("id"):
        return str(data[0]["id"])
    models = payload.get("models")
    if isinstance(models, list) and models and isinstance(models[0], dict):
        name = models[0].get("model") or models[0].get("name")
        return str(name) if name else None
    return None


def probe_models_endpoint(endpoint: str, timeout: float = 10.0) -> ModelsProbeResult | None:
    """The server's ``/models`` answer, or None when it is not reachable or not valid."""
    try:
        with urlopen(f"{endpoint}/models", timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read())
    except (URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None
    return ModelsProbeResult(payload=payload, first_model_id=_first_model_id(payload))


def require_models_endpoint(endpoint: str, timeout: float = 15.0) -> ModelsProbeResult:
    """Like ``probe_models_endpoint`` but raise a specific error for each way it can fail."""
    url = f"{endpoint}/models"
    try:
        with urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                raise _error("EXT", 1, f"Model server health failed: {url} -> HTTP {response.status}", url=url)
            payload = json.loads(response.read())
    except HTTPError as exc:
        raise _error("EXT", 2, f"Model server not ready: {url} -> HTTP {exc.code}: {exc.reason}", url=url) from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise _error("NET", 3, f"Model server unavailable: {url}: {exc}", url=url) from exc
    except json.JSONDecodeError as exc:
        raise _error("EXT", 4, f"Model server health returned invalid JSON: {url}", url=url) from exc
    if not isinstance(payload.get("data"), list) or not payload["data"]:
        raise _error("EXT", 5, f"Model server reported no models: {url}", url=url)
    return ModelsProbeResult(payload=payload, first_model_id=_first_model_id(payload))


def query_server_model(endpoint: str, timeout: float = 10.0) -> str | None:
    """The first model id the server reports, or None."""
    probe = probe_models_endpoint(endpoint, timeout=timeout)
    return probe.first_model_id if probe else None
