"""Shared streaming helpers and sink primitives."""

from audiagentic.streaming.provider_streaming import StreamedCommandResult, build_provider_stream_sinks, run_streaming_command
from audiagentic.streaming.sinks import ConsoleSink, InMemorySink, NormalizedEventSink, RawLogSink, StreamSink

__all__ = [
    "ConsoleSink",
    "InMemorySink",
    "NormalizedEventSink",
    "RawLogSink",
    "StreamSink",
    "StreamedCommandResult",
    "build_provider_stream_sinks",
    "run_streaming_command",
]

