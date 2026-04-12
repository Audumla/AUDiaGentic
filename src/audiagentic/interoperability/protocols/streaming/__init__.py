"""Shared streaming helpers and sink primitives."""

from audiagentic.interoperability.protocols.streaming.completion import (
    CompletionStatus,
    Decision,
    NormalizationMethod,
    ProviderCompletion,
    Recommendation,
    ResultSource,
    build_synthetic_fallback,
    completion_artifact_dir,
    completion_path,
    normalize_provider_result,
    persist_completion,
    validate_provider_completion,
)
from audiagentic.interoperability.protocols.streaming.provider_streaming import (
    StreamedCommandResult,
    build_provider_stream_sinks,
    run_streaming_command,
)
from audiagentic.interoperability.protocols.streaming.sinks import (
    ConsoleSink,
    InMemorySink,
    NormalizedEventSink,
    RawLogSink,
    StreamSink,
)

__all__ = [
    "CompletionStatus",
    "ConsoleSink",
    "Decision",
    "InMemorySink",
    "NormalizationMethod",
    "NormalizedEventSink",
    "ProviderCompletion",
    "RawLogSink",
    "Recommendation",
    "ResultSource",
    "StreamSink",
    "StreamedCommandResult",
    "build_provider_stream_sinks",
    "build_synthetic_fallback",
    "completion_artifact_dir",
    "completion_path",
    "normalize_provider_result",
    "persist_completion",
    "run_streaming_command",
    "validate_provider_completion",
]
