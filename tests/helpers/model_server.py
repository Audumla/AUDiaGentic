"""A real llama-server for the tests that need a model to answer.

Test-only. AUDiaGentic never launches or hosts a model server: a harness talks to an
OpenAI-compatible endpoint that already runs. Tests that must see a real model
(Pi against a real model, the resume and RPC-tap lanes, the smoke lanes) get one here.

``start_model_server()`` downloads the pinned llama.cpp release for this platform
(``llama_cpp_release.yaml``, checksum verified) and a small GGUF model into a cache
directory, starts ``llama-server`` on a free loopback port, waits until ``/models``
answers, and returns a handle whose ``stop()`` terminates it. Nothing here is imported
by product code.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import platformdirs
import yaml

_MANIFEST = Path(__file__).with_name("llama_cpp_release.yaml")
_ASSET_KEY = {"win32": "win-x64", "darwin": "darwin-arm64"}
_DEFAULT_MODEL_URL = (
    "https://huggingface.co/lmstudio-community/Qwen3.5-0.8B-GGUF/resolve/main/"
    "Qwen3.5-0.8B-Q4_K_M.gguf?download=true"
)
MODEL_URL_ENV = "AUDIAGENTIC_TEST_MODEL_URL"
CACHE_ENV = "AUDIAGENTIC_TEST_MODEL_CACHE"


@dataclass
class ModelServer:
    endpoint: str  # the OpenAI-compatible base URL, ending in /v1
    model_id: str
    port: int
    log_path: Path
    process: subprocess.Popen[bytes]

    def stop(self, timeout: float = 15.0) -> None:
        """Terminate the server this handle started (only that process)."""
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=timeout)


def cache_dir() -> Path:
    return Path(os.environ.get(CACHE_ENV) or platformdirs.user_cache_path("audiagentic-tests")) / "llama-cpp"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _asset() -> dict[str, Any]:
    manifest = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
    key = _ASSET_KEY.get(sys.platform, "linux-x64")
    return {"version": manifest["release"]["version"], **manifest["assets"][key]}


def _unsafe(names: list[str]) -> bool:
    return any(Path(name).is_absolute() or ".." in Path(name).parts for name in names)


def _extract(archive: Path, kind: str, destination: Path) -> None:
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            if _unsafe(zf.namelist()):
                raise RuntimeError("llama.cpp archive contains an unsafe member path")
            zf.extractall(destination)
        return
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        if _unsafe([m.name for m in members]) or any(
            (m.issym() or m.islnk()) and (PurePosixPath(m.linkname).is_absolute() or ".." in PurePosixPath(m.linkname).parts)
            for m in members
        ):
            raise RuntimeError("llama.cpp archive contains an unsafe member or link")
        try:
            tf.extractall(destination, members=members, filter="fully_trusted")
        except TypeError:  # interpreters before the PEP 706 filter argument
            tf.extractall(destination, members=members)


def install_llama_server(cache: Path | None = None) -> Path:
    """The pinned ``llama-server`` for this platform, downloaded and checksum-verified once."""
    asset = _asset()
    target = (cache or cache_dir()) / asset["version"]
    binary = target / asset["executable"]
    if binary.is_file():
        return binary
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{asset['version']}/{asset['filename']}"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="llama-cpp-", dir=target.parent) as temporary:
        archive = Path(temporary) / asset["filename"]
        urllib.request.urlretrieve(url, archive)  # noqa: S310 - pinned https URL
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != asset["sha256"]:
            raise RuntimeError(f"llama.cpp checksum mismatch for {asset['filename']}: {digest}")
        stage = Path(temporary) / "stage"
        stage.mkdir()
        _extract(archive, asset["archive"], stage)
        root = next((p for p in stage.iterdir() if p.is_dir() and (p / asset["executable"]).exists()), stage)
        if not (root / asset["executable"]).exists():
            raise RuntimeError(f"{asset['executable']} not found in the llama.cpp archive")
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(root), str(target))
    if sys.platform != "win32":
        binary.chmod(0o755)
    return binary


def ensure_model(cache: Path | None = None) -> Path:
    """A small GGUF model: ``$AUDIAGENTIC_TEST_MODEL_URL`` or the default 0.8B, downloaded once."""
    url = os.environ.get(MODEL_URL_ENV) or _DEFAULT_MODEL_URL
    name = hashlib.sha256(url.encode()).hexdigest()[:12] + ".gguf"
    model = (cache or cache_dir()) / "models" / name
    if not model.is_file():
        model.parent.mkdir(parents=True, exist_ok=True)
        partial = model.with_suffix(".part")
        urllib.request.urlretrieve(url, partial)  # noqa: S310 - https URL chosen by the test environment
        partial.replace(model)
    return model


def _models_answer(endpoint: str) -> bool:
    try:
        with urllib.request.urlopen(f"{endpoint}/models", timeout=5) as response:  # noqa: S310 - loopback
            return response.status == 200 and bool(json.loads(response.read()).get("data"))
    except (OSError, ValueError):
        return False


def start_model_server(
    model_id: str = "audiagentic-rig",
    *,
    port: int | None = None,
    context_size: int = 4096,
    health_timeout: float = 180.0,
    log_dir: Path | None = None,
) -> ModelServer:
    """Start ``llama-server`` on a free loopback port; the caller must ``stop()`` it."""
    binary = install_llama_server()
    model = ensure_model()
    port = port or _free_port()
    log_path = (log_dir or Path(tempfile.mkdtemp(prefix="model-server-"))) / "llama-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(binary), "--host", "127.0.0.1", "--port", str(port), "--model", str(model),
        "--alias", model_id, "--ctx-size", str(context_size), "--parallel", "1",
        "--chat-template-kwargs", json.dumps({"enable_thinking": False}, separators=(",", ":")),
    ]
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=binary.parent)  # noqa: S603
    endpoint = f"http://127.0.0.1:{port}/v1"
    server = ModelServer(endpoint=endpoint, model_id=model_id, port=port, log_path=log_path, process=process)
    deadline = time.monotonic() + health_timeout
    while time.monotonic() < deadline:
        if _models_answer(endpoint):
            return server
        if process.poll() is not None:
            raise RuntimeError(f"llama-server exited with {process.returncode}; see {log_path}")
        time.sleep(0.5)
    server.stop()
    raise RuntimeError(f"llama-server did not answer {endpoint}/models in {health_timeout:.0f}s; see {log_path}")


@contextmanager
def model_server(model_id: str = "audiagentic-rig", **options: Any) -> Iterator[ModelServer]:
    """``with model_server() as server:`` starts one and always stops it."""
    server = start_model_server(model_id, **options)
    try:
        yield server
    finally:
        server.stop()
