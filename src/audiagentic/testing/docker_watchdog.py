from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence


def _stream_process(
    command: Sequence[str],
    *,
    timeout_seconds: int,
    idle_timeout_seconds: int | None,
    cleanup_container: str | None = None,
) -> int:
    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    lines: queue.Queue[str | None] = queue.Queue()
    last_output = time.monotonic()

    def _reader() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    started = time.monotonic()
    saw_end = False
    timed_out = False
    idle_timed_out = False

    while True:
        try:
            item = lines.get(timeout=0.25)
            if item is None:
                saw_end = True
            else:
                last_output = time.monotonic()
                sys.stdout.write(item)
                sys.stdout.flush()
        except queue.Empty:
            pass

        if saw_end and process.poll() is not None:
            break

        now = time.monotonic()
        if now - started > timeout_seconds:
            timed_out = True
            break
        if idle_timeout_seconds is not None and now - last_output > idle_timeout_seconds:
            idle_timed_out = True
            break

    if timed_out or idle_timed_out:
        reason = (
            f"overall timeout after {timeout_seconds}s"
            if timed_out else
            f"idle timeout after {idle_timeout_seconds}s without output"
        )
        print(f"\n[watchdog] aborting: {reason}", file=sys.stderr)
        if cleanup_container:
            subprocess.run(
                ["docker", "rm", "-f", cleanup_container],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return 124

    return process.wait()


def _build_command(args: argparse.Namespace) -> list[str]:
    return [
        "docker",
        "build",
        "-f",
        args.file,
        "-t",
        args.tag,
        args.context,
    ]


def _run_command(args: argparse.Namespace) -> tuple[list[str], str]:
    container_name = args.name or f"audiagentic-watchdog-{uuid.uuid4().hex[:12]}"
    command = ["docker", "run", "--rm", "--name", container_name]
    for env_item in args.env:
        command.extend(["-e", env_item])
    for volume in args.volume:
        command.extend(["-v", volume])
    if args.workdir:
        command.extend(["-w", args.workdir])
    command.append(args.image)
    remainder = list(args.command)
    if remainder[:1] == ["--"]:
        remainder = remainder[1:]
    command.extend(remainder)
    return command, container_name


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Docker build/run commands with hard timeout, idle timeout, and forced cleanup."
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    build_parser = subparsers.add_parser("build", help="Watchdog docker build")
    build_parser.add_argument("--file", required=True)
    build_parser.add_argument("--tag", required=True)
    build_parser.add_argument("--context", default=".")
    build_parser.add_argument("--timeout-seconds", type=int, default=900)
    build_parser.add_argument("--idle-timeout-seconds", type=int, default=120)

    run_parser = subparsers.add_parser("run", help="Watchdog docker run")
    run_parser.add_argument("--image", required=True)
    run_parser.add_argument("--name", default="")
    run_parser.add_argument("--workdir", default="")
    run_parser.add_argument("--env", action="append", default=[])
    run_parser.add_argument("--volume", action="append", default=[])
    run_parser.add_argument("--timeout-seconds", type=int, default=900)
    run_parser.add_argument("--idle-timeout-seconds", type=int, default=120)
    run_parser.add_argument("command", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)

    if args.mode == "build":
        command = _build_command(args)
        return _stream_process(
            command,
            timeout_seconds=args.timeout_seconds,
            idle_timeout_seconds=args.idle_timeout_seconds,
        )

    command, container_name = _run_command(args)
    return _stream_process(
        command,
        timeout_seconds=args.timeout_seconds,
        idle_timeout_seconds=args.idle_timeout_seconds,
        cleanup_container=container_name,
    )


if __name__ == "__main__":
    raise SystemExit(main())
