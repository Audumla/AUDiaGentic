"""Path constants and helpers for the state layer.

All code that needs to construct paths under the .audiagentic/runtime/jobs
directory should import from this module rather than hard-coding the string.
"""
from __future__ import annotations

from pathlib import Path

_JOBS_ROOT = Path(".audiagentic") / "runtime" / "jobs"


def jobs_root(project_root: Path) -> Path:
    """Return the .audiagentic/runtime/jobs root for a project."""
    return project_root / _JOBS_ROOT


def job_dir(project_root: Path, job_id: str) -> Path:
    """Return the job directory (.audiagentic/runtime/jobs/<job_id>)."""
    return jobs_root(project_root) / job_id


def job_stages_dir(project_root: Path, job_id: str) -> Path:
    """Return the stages directory for a job."""
    return job_dir(project_root, job_id) / "stages"


def job_reviews_dir(project_root: Path, job_id: str) -> Path:
    """Return the reviews directory for a job."""
    return job_dir(project_root, job_id) / "reviews"


def job_completions_dir(project_root: Path, job_id: str) -> Path:
    """Return the completions directory for a job."""
    return job_dir(project_root, job_id) / "completions"


def job_control_path(project_root: Path, job_id: str) -> Path:
    """Return the job-control.json path for a job."""
    return job_dir(project_root, job_id) / "job-control.json"


def job_control_events_path(project_root: Path, job_id: str) -> Path:
    """Return the control-events.ndjson path for a job."""
    return job_dir(project_root, job_id) / "control-events.ndjson"


def job_input_path(project_root: Path, job_id: str) -> Path:
    """Return the input.ndjson path for a job."""
    return job_dir(project_root, job_id) / "input.ndjson"


def job_input_events_path(project_root: Path, job_id: str) -> Path:
    """Return the input-events.ndjson path for a job."""
    return job_dir(project_root, job_id) / "input-events.ndjson"


def job_stdin_log_path(project_root: Path, job_id: str) -> Path:
    """Return the stdin.log path for a job."""
    return job_dir(project_root, job_id) / "stdin.log"


def job_launch_request_path(project_root: Path, job_id: str) -> Path:
    """Return the launch-request.json path for a job."""
    return job_dir(project_root, job_id) / "launch-request.json"


def job_subject_manifest_path(project_root: Path, job_id: str) -> Path:
    """Return the subject.json path for a job."""
    return job_dir(project_root, job_id) / "subject.json"


def job_timeline_path(project_root: Path, job_id: str) -> Path:
    """Return the timeline.ndjson path for a job."""
    return job_dir(project_root, job_id) / "timeline.ndjson"
