from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .envelope import EventEnvelope

logger = logging.getLogger(__name__)


class CodeFormatter:
    """Automatic code formatter triggered on task completion events."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.formatter = "ruff"  # Default to ruff

    def handle_task_done(self, envelope: EventEnvelope) -> None:
        """Format code when a task is marked done."""
        subject = envelope.metadata.get("subject", {})
        if subject.get("kind") != "task":
            return

        task_id = subject.get("id")
        if not task_id:
            return

        try:
            files = self._get_task_files(task_id)
            if not files:
                return

            self._format_files(files)
            logger.info("Formatted %d files for task %s", len(files), task_id)

        except Exception as e:
            logger.warning("Code formatting failed for task %s: %s", task_id, e)

    def _get_task_files(self, task_id: str) -> list[Path]:
        """Get files modified by a task."""
        task_path = self.project_root / "docs" / "planning" / "tasks" / task_id.replace("-", "_")
        if not task_path.exists():
            task_path = self.project_root / "docs" / "planning" / "tasks" / task_id

        if not task_path.exists():
            return []

        # Read task file to find modified files
        task_content = task_path.read_text(encoding="utf-8")

        files = []
        for line in task_content.split("\n"):
            if line.startswith("- `") and ".py" in line:
                # Extract file path from markdown link
                try:
                    file_ref = line.split("`")[1]
                    if file_ref.startswith("src/"):
                        files.append(self.project_root / file_ref)
                except (IndexError, ValueError):
                    continue

        return files

    def _format_files(self, files: list[Path]) -> None:
        """Format files using ruff."""
        if not files:
            return

        file_paths = [str(f) for f in files if f.exists()]
        if not file_paths:
            return

        # Format with ruff
        result = subprocess.run(
            ["ruff", "format"] + file_paths,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            logger.warning("Ruff format failed: %s", result.stderr)

        # Fix issues with ruff check
        result = subprocess.run(
            ["ruff", "check", "--fix"] + file_paths,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode not in (0, 1):
            logger.warning("Ruff check failed: %s", result.stderr)
