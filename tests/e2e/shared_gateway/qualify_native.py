"""Isolated real-provider installed shared-service qualification driver."""

import argparse
import ipaddress
import json
import os
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    package = parser.add_mutually_exclusive_group(required=True)
    package.add_argument(
        "--installed-package", type=Path, help="pip --target directory, including dependencies"
    )
    package.add_argument(
        "--wheel", type=Path, help="wheel to install with dependencies in the evidence directory"
    )
    parser.add_argument(
        "--catalog", type=Path, required=True, help="existing agents.yaml; copied before loading"
    )
    parser.add_argument("--native-profile", required=True)
    parser.add_argument("--provider", choices=["codex"], required=True)
    parser.add_argument("--access-mode", choices=["cli"], required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="new evidence directory; must not exist"
    )
    return parser.parse_args()


def clone_cli_profile(source, *, provider, access_mode):
    """Clone a no-surface Codex CLI profile without changing the source catalog entry."""
    if provider != "codex" or access_mode != "cli" or source.get("provider_id") != provider:
        raise ValueError("existing profile provider must match explicit codex CLI selection")
    if source.get("surface_id") is not None:
        raise ValueError("CLI qualification requires no surface override; ACP is not downgraded")
    from copy import deepcopy

    profile = deepcopy(source)
    profile.update(
        profile_id="qualification-codex-cli-" + uuid.uuid4().hex, surface_id=None, is_default=False
    )
    return profile


def main(args, resources):
    import yaml
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    base = args.output.resolve()
    base.mkdir(parents=True, exist_ok=False)
    machine = base / "machine"
    (machine / "config").mkdir(parents=True)
    shutil.copyfile(args.catalog.resolve(strict=True), machine / "config" / "agents.yaml")
    os.environ["_AUDIAGENTIC_HOME"] = str(machine)
    package = (
        args.installed_package.resolve(strict=True)
        if args.installed_package
        else base / "installed"
    )
    if args.wheel:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(package),
                str(args.wheel.resolve(strict=True)),
            ],
            check=True,
            timeout=300,
        )
    if not (package / "audiagentic" / "__init__.py").is_file():
        raise ValueError("installed package directory must contain audiagentic/__init__.py")
    sys.path.insert(0, str(package))
    import audiagentic

    if not Path(audiagentic.__file__).resolve().is_relative_to(package):
        raise RuntimeError("qualification imported source checkout instead of installed package")
    from audiagentic.components.agents.configuration.management import (
        create_execution_profile,
        get_execution_profile,
    )
    from audiagentic.components.agents.gateway import store
    from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.state import set_implementation_state

    # Isolate the qualification profile using the supported machine-home override;
    # no live user catalog or Codex credentials/configuration are modified.
    native_profile = clone_cli_profile(
        get_execution_profile(base, args.native_profile),
        provider=args.provider,
        access_mode=args.access_mode,
    )
    create_execution_profile(base, native_profile)

    tokens = {name: secrets.token_urlsafe(32) for name in ("alice", "bob")}
    markers = {name: secrets.token_hex(8) for name in tokens}
    roots = {}
    for name in tokens:
        root = base / name
        root.mkdir(exist_ok=True)
        config = root / ".audiagentic" / "config"
        (config / "providers").mkdir(parents=True, exist_ok=True)
        (config / "project.yaml").write_text(
            yaml.safe_dump(
                {
                    "contract-version": "v1",
                    "project-id": name,
                    "project-name": name,
                    "workflow-profile": "standard",
                    "tracked-docs-root": "docs",
                    "runtime-root": ".audiagentic/runtime",
                    "release-strategy": "semver",
                }
            )
        )
        (config / "providers" / "codex.yaml").write_text(
            yaml.safe_dump({"install-mode": "external-configured", "access-mode": "cli"})
        )
        set_implementation_state(
            root, "providers", "codex", ImplementationState(enabled=True, options={})
        )
        (root / "qualification-input.txt").write_text(markers[name])
        token_file = base / (name + ".token")
        token_file.write_text(tokens[name])
        token_file.chmod(0o600)
        roots[name] = root
        (root / ".audiagentic").mkdir(parents=True, exist_ok=True)
        (root / ".audiagentic" / "settings.yaml").write_text(f"schema_version: 1\nproject:\n  id: {name}\n")
    (base / "state").mkdir(exist_ok=True)
    workspace_config_home = base / "xdg-config"
    (workspace_config_home / "audiagentic").mkdir(parents=True, exist_ok=True)
    (workspace_config_home / "audiagentic" / "settings.yaml").write_text(
        "schema_version: 1\ngateway:\n  workspace_roots:\n" + "".join(f"    - {r}\n" for r in roots.values()),
        encoding="utf-8",
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        backend_port = s.getsockname()[1]
    server_config = {
        "schema-version": 1,
        "server-id": "qualification-" + secrets.token_hex(6),
        "listen": {"port": backend_port},
        "service-root": "state",
        "projects": [name for name in roots],
        "principals": {
            name: {
                "token-file": name + ".token",
                "projects": [name],
                "actions": ["read", "submit", "cancel", "session"],
            }
            for name in roots
        },
    }
    (base / "server.yaml").write_text(yaml.safe_dump(server_config))
    (base / "client-config.json").write_text(
        json.dumps(
            {
                "server-id": server_config["server-id"],
                "execution-profile-id": native_profile["profile_id"],
            }
        )
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = base / "cert.pem", base / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    key_path.chmod(0o600)

    class Proxy(BaseHTTPRequestHandler):
        drop_first_submit = True
        dropped_request_id = None

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def forward(self):
            if self.path not in {
                "/shared/v1/health",
                "/shared/v1/call",
                "/shared/v1/client-leases/acquire",
                "/shared/v1/client-leases/renew",
                "/shared/v1/client-leases/release",
            }:
                self.send_error(404)
                return
            body = (
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.command == "POST"
                else None
            )
            request = Request(
                f"http://127.0.0.1:{backend_port}" + self.path,
                data=body,
                method=self.command,
                headers={
                    k: v
                    for k, v in self.headers.items()
                    if k.lower() in {"authorization", "content-type"}
                },
            )
            try:
                response = urlopen(request, timeout=95)
            except HTTPError as error:
                response = error
            except OSError:
                self.send_error(503)
                return
            with response:
                data = response.read()
                if (
                    200 <= response.code < 300
                    and type(self).drop_first_submit
                    and body
                    and self.path == "/shared/v1/call"
                    and json.loads(body).get("operation") == "submit_execution_request"
                    and self.headers.get("Authorization") == "Bearer " + tokens["alice"]
                ):
                    type(self).dropped_request_id = json.loads(data)["result"]["request-id"]
                    type(self).drop_first_submit = False
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.send_response(response.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        def log_message(self, *args):
            pass

    class ProxyServer(ThreadingHTTPServer):
        daemon_threads = True

    proxy = ProxyServer(("127.0.0.1", 0), Proxy)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    proxy.socket = tls.wrap_socket(proxy.socket, server_side=True)
    resources.callback(proxy.server_close)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    resources.callback(thread.join, 3)
    resources.callback(proxy.shutdown)
    endpoint = f"https://127.0.0.1:{proxy.server_port}"
    env = dict(
        os.environ,
        PYTHONPATH=str(package),
        PYTHONUNBUFFERED="1",
        XDG_CONFIG_HOME=str(workspace_config_home),
    )
    clients = {
        name: StandaloneGatewayClient(
            endpoint,
            token,
            shared_server_id=server_config["server-id"],
            shared_project_id=name,
            ssl_context=ssl.create_default_context(cafile=str(cert_path)),
            request_timeout=10,
        )
        for name, token in tokens.items()
    }
    for client in clients.values():
        resources.callback(client.close)
    log = resources.enter_context((base / "server.log").open("w"))
    process = spawn(
        resources,
        [
            sys.executable,
            "-m",
            "audiagentic.launcher",
            "gateway",
            "serve",
            "config",
            str(base / "server.yaml"),
        ],
        cwd=base,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
    )
    proof = {
        "package": str(package),
        "status": "running",
        "native-profile": args.native_profile,
        "qualification-profile": native_profile["profile_id"],
        "provider": args.provider,
        "access-mode": args.access_mode,
        "base": str(base),
        "endpoint": endpoint,
        "requests": {},
        "events": [],
    }

    def emit(event, **fields):
        row = {"event": event, **fields}
        proof["events"].append(row)
        (base / "proof.json").write_text(json.dumps(proof, indent=2, default=str))
        print(json.dumps(row, default=str), flush=True)

    try:
        deadline = time.monotonic() + 25
        while True:
            assert process.poll() is None, (base / "server.log").read_text()
            try:
                health = clients["alice"].health()
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        assert_proxy_boundaries(endpoint, cert_path, tokens["alice"], clients["alice"])
        emit("service-ready", epoch=health["owner-epoch"], base=str(base))
        helper = Path(__file__).with_name("shared_native_client.py")

        def child(name, action, request_id=None):
            command = [sys.executable, str(helper), str(package), str(base), endpoint, name, action]
            if request_id:
                command += ["--request-id", request_id]
            worker = spawn(
                resources,
                command,
                cwd=base,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = worker.communicate(timeout=200)
            return subprocess.CompletedProcess(command, worker.returncode, stdout, stderr)

        lost = child("alice", "submit")
        assert lost.returncode == 3, (lost.stdout, lost.stderr)
        assert json.loads(lost.stdout)["error-code"] == "NET-AGSV-002", lost.stdout
        # A real accepted request persists despite its reply being deliberately lost.
        assert len(store.list_records(roots["alice"])) == 1
        emit("lost-admission-response", client="alice", automatically_replayed=False)
        for name in clients:
            submitted = child(name, "submit")
            assert submitted.returncode == 0, submitted.stderr
            admitted = json.loads(submitted.stdout)
            proof["requests"][name] = admitted
            emit("independent-submitter-exited", client=name, result=admitted)
        assert len(store.list_records(roots["alice"])) == 1
        assert proof["requests"]["alice"]["request-id"] == Proxy.dropped_request_id
        assert not Proxy.drop_first_submit
        assert process.poll() is None
        emit("idempotent-recovery", request_count=1)
        observers = {}
        for name in clients:
            out = resources.enter_context((base / (name + "-observe.log")).open("w"))
            observers[name] = (
                spawn(
                    resources,
                    [
                        sys.executable,
                        str(helper),
                        str(package),
                        str(base),
                        endpoint,
                        name,
                        "observe",
                        "--request-id",
                        proof["requests"][name]["request-id"],
                    ],
                    cwd=base,
                    env=env,
                    stdout=out,
                    stderr=out,
                ),
                out,
            )
        for name, (observer, out) in observers.items():
            observer.wait(timeout=200)
            out.close()
            result = json.loads((base / (name + "-observe.log")).read_text())
            assert observer.returncode == 0, result
            assert result["status"].get("outcome") == "success", result
            assert markers[name] in result.get("response", ""), result
            record = store.read_record(roots[name], proof["requests"][name]["request-id"])
            assert len(record["attempts"]) == 1, record["attempts"]
            emit("independent-observer-completed", client=name, result=result, native_attempts=1)
        for client in clients.values():
            client.close()
        assert process.poll() is None
        emit("all-clients-exited-service-alive")
        # Existing readers carry a stale lease across an actual installed-server restart.
        clients["alice"].list_agent_definition_cards(base)
        previous_epoch = clients["alice"].health()["owner-epoch"]
        stop_tree(process)
        process = spawn(
            resources,
            [
                sys.executable,
                "-m",
                "audiagentic.launcher",
                "gateway",
                "serve",
                "config",
                str(base / "server.yaml"),
            ],
            cwd=base,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )
        deadline = time.monotonic() + 25
        while True:
            try:
                health = clients["alice"].health()
                if health["owner-epoch"] != previous_epoch:
                    break
            except Exception:
                pass
            assert process.poll() is None, (base / "server.log").read_text()
            if time.monotonic() > deadline:
                raise RuntimeError("restart did not become ready")
            time.sleep(0.1)
        emit("installed-server-restarted", epoch_changed=True)
        recovered = clients["alice"].get_execution_request(
            base, proof["requests"]["alice"]["request-id"]
        )
        assert recovered.get("outcome") == "success", recovered
        emit("cached-reader-recovered", success=True)
        for name in clients:
            observed = child(name, "observe", proof["requests"][name]["request-id"])
            assert observed.returncode == 0, observed.stderr
            assert markers[name] in json.loads(observed.stdout).get("response", "")
        emit("independent-clients-retrieved-after-restart", success=True)
        proof["status"] = "passed"
    except BaseException as error:
        proof["status"] = "failed"
        emit("qualification-failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        for client in clients.values():
            client.close()
        stop_tree(process)
        log.close()
        proxy.shutdown()
        thread.join(timeout=3)
        proxy.server_close()
        emit("qualification-process-stopped")


def stop_tree(process):
    """Stop only this qualification's process tree, including timed-out children."""
    if getattr(process, "_qualification_stopped", False):
        return
    close_job = getattr(process, "_qualification_job_close", None)
    if close_job is not None:
        close_job()
    elif os.name == "nt":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=15)
    process._qualification_stopped = True


def spawn(resources, command, **kwargs):
    # Windows job containment also covers descendants if the direct child exits.
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x00000004  # CREATE_SUSPENDED
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    resources.callback(stop_tree, process)
    if os.name == "nt":
        try:
            process._qualification_job_close = contain_windows_process(process)
        except BaseException:
            stop_tree(process)
            raise
    return process


def contain_windows_process(process):
    """Put a suspended child in a kill-on-close job before it can spawn workers."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io_counters", ctypes.c_uint64 * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
            raise ctypes.WinError(ctypes.get_last_error())
        native = ctypes.WinDLL("ntdll")
        native.NtResumeProcess.argtypes = [wintypes.HANDLE]
        native.NtResumeProcess.restype = ctypes.c_long
        if native.NtResumeProcess(wintypes.HANDLE(int(process._handle))) != 0:
            raise RuntimeError("could not resume qualification child")
    except BaseException:
        kernel.CloseHandle(job)
        raise
    return lambda: kernel.CloseHandle(job)


def assert_proxy_boundaries(endpoint, cert_path, token, client):
    context = ssl.create_default_context(cafile=str(cert_path))

    def rejected(path, body=None):
        request = Request(
            endpoint + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, context=context, timeout=10) as response:
                raise AssertionError(f"invalid route/scope accepted: {path}: {response.status}")
        except HTTPError as error:
            assert 400 <= error.code < 500, error.code

    for path in ("/health", "/call", "/dashboard", "/images/test", "/shared/v1/../health"):
        rejected(path)
    # Valid lease and protocol envelope: rejection must exercise scope validation.
    from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION

    client.list_execution_requests(Path.cwd())
    envelope = {
        "protocol-version": PROTOCOL_VERSION,
        "lease-id": client._lease_id,
        "owner-epoch": client._owner_epoch,
        "operation": "list_execution_requests",
        "params": {},
    }
    for scope in (
        {"project-id": "not-enrolled"},
        {"project-id": "alice", "project-root": "/not-authorized"},
    ):
        rejected("/shared/v1/call", {**envelope, **scope})


if __name__ == "__main__":
    with ExitStack() as resources:
        main(parse_args(), resources)
