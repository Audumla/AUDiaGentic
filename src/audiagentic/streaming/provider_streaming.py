"""Shared streaming command execution helpers for provider adapters."""
from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO


@dataclass
class StreamedCommandResult:
    returncode: int
    stdout: str
    stderr: str
    command: list[str]


def _append_text(path: Path | None, text: str) -> None:
    if path is None or not text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def _reader(
    stream: TextIO,
    *,
    sink: list[str],
    log_path: Path | None,
    tee_console: bool,
    console: TextIO,
) -> None:
    while True:
        line = stream.readline()
        if not line:
            break
        sink.append(line)
        _append_text(log_path, line)
        if tee_console:
            console.write(line)
            console.flush()


def run_streaming_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    stdout_log_path: Path | None = None,
    stderr_log_path: Path | None = None,
    tee_console: bool = False,
    input_text: str | None = None,
) -> StreamedCommandResult:
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_thread = threading.Thread(
        target=_reader,
        args=(process.stdout,),
        kwargs={
            "sink": stdout_lines,
            "log_path": stdout_log_path,
            "tee_console": tee_console,
            "console": sys.stdout,
        },
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_reader,
        args=(process.stderr,),
        kwargs={
            "sink": stderr_lines,
            "log_path": stderr_log_path,
            "tee_console": tee_console,
            "console": sys.stderr,
        },
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    if input_text is not None and process.stdin is not None:
        process.stdin.write(input_text)
        process.stdin.flush()
        process.stdin.close()

    returncode = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    return StreamedCommandResult(
        returncode=returncode,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
        command=command,
    )
