"""Request-private real activity observation for Pi's one-shot print mode.

Pi's ``--print`` route is intentionally retained for stateless gateway work.
The extension below has no UI, prompt, tool, or output responsibilities: it
only appends bounded lifecycle facts to the worker-owned normalized event file.
The isolated worker relays those facts as activity renewals.  Failure to create
or write that optional side channel must never affect Pi's stdin/stdout/stderr
or exit-code contract.
"""

from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.io import atomic_write_text

_ACTIVITY_PATH_ENV = "AUDIAGENTIC_PI_ACTIVITY_PATH"
_EXTENSION_NAME = "audiagentic-print-activity.mjs"

# This is deliberately plain ESM JavaScript: Pi loads explicit extension files
# in ``--print`` mode, and the extension must not need a package install or
# write anything to Pi's stdout/stderr protocol channels.
_EXTENSION_SOURCE = r'''import { appendFileSync } from "node:fs";

export default function registerAudiaGenticPrintActivity(pi) {
  const eventPath = process.env.AUDIAGENTIC_PI_ACTIVITY_PATH;
  if (!eventPath) return;
  const emit = (type) => {
    try {
      appendFileSync(eventPath, JSON.stringify({"event-kind": "pi-lifecycle", type}) + "\n", { encoding: "utf8" });
    } catch (_) {
      // Observation is optional and must never disrupt a provider turn.
    }
  };
  for (const type of [
    "agent_start", "turn_start", "message_start", "message_update",
    "message_end", "tool_execution_start", "tool_execution_update",
    "tool_execution_end", "turn_end", "agent_end",
  ]) {
    pi.on(type, () => emit(type));
  }
}
'''


def _request_runtime_path(packet_ctx: dict[str, object]) -> Path | None:
    """Return the contained request runtime directory, or disable the tap."""
    working_root = packet_ctx.get("working-root")
    job_id = packet_ctx.get("job-id") or packet_ctx.get("request-id")
    if not isinstance(working_root, str) or not isinstance(job_id, str) or not job_id:
        return None
    try:
        root = Path(working_root).resolve()
        runtime = (root / ".audiagentic" / "runtime" / "jobs" / job_id).resolve()
        if not runtime.is_relative_to(root):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return runtime


def prepare_print_activity_launch(
    packet_ctx: dict[str, object],
    _provider_cfg: dict[str, object],
    command: list[str],
) -> tuple[list[str], dict[str, str]]:
    """Add Pi's explicit, isolated lifecycle extension when possible.

    The returned launch remains exactly a ``pi --print`` stdin request.  A
    malformed or unavailable request runtime simply leaves the command alone;
    callers still receive Pi's normal output and terminal result.
    """
    runtime = _request_runtime_path(packet_ctx)
    if runtime is None:
        return command, {}
    try:
        runtime.mkdir(parents=True, exist_ok=True)
        extension = runtime / "pi" / _EXTENSION_NAME
        atomic_write_text(extension, _EXTENSION_SOURCE)
        event_path = runtime / "events.ndjson"
    except OSError:
        return command, {}
    # Explicit extension loading plus disabled ambient extension discovery
    # keeps the worker's private Pi environment reproducible.  Pi documents
    # that ``--no-extensions`` does not suppress explicit ``--extension``.
    return (
        [*command, "--no-extensions", "--extension", str(extension)],
        {_ACTIVITY_PATH_ENV: str(event_path)},
    )


__all__ = ["prepare_print_activity_launch"]
