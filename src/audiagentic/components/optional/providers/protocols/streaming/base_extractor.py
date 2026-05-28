"""Base class for provider stream event extractors."""
from __future__ import annotations

from typing import Any

from audiagentic.components.optional.providers.protocols.streaming._utils import _utc_now
from audiagentic.components.optional.providers.protocols.streaming.sinks import StreamSink


class BaseEventExtractor:
    """Abstract base for provider-specific stream event extractors.

    Subclasses MUST define `extractor_name` as a class variable. Omitting it
    raises AttributeError at class definition time (via __init_subclass__).
    """

    extractor_name: str  # required — no default

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "extractor_name" not in cls.__dict__:
            raise AttributeError(
                f"{cls.__name__} must define 'extractor_name' as a class variable"
            )

    def __init__(
        self,
        event_sink: StreamSink,
        job_id: str,
        provider_id: str,
    ) -> None:
        self.event_sink = event_sink
        self.job_id = job_id
        self.provider_id = provider_id

    def _emit_event(
        self,
        event_kind: str,
        message: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {"extractor": self.extractor_name}
        if raw_payload is not None:
            details["raw"] = raw_payload
        self.event_sink.write_event(
            {
                "contract-version": "v1",
                "job-id": self.job_id,
                "provider-id": self.provider_id,
                "event-kind": event_kind,
                "message": message,
                "timestamp": _utc_now(),
                "details": details,
            }
        )

    def flush(self) -> None:
        self.event_sink.flush()

    def close(self) -> None:
        self.event_sink.close()
