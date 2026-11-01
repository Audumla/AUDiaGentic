import os
import socket
import subprocess

from audiagentic.components.providers.services.qualification.probes.pi import listening_endpoints


def test_a_listening_tcp_socket_is_counted_and_a_plain_process_has_none(tmp_path):
    idle = subprocess.Popen(["sleep", "5"])  # a process with no sockets at all
    try:
        assert listening_endpoints([idle.pid]) == (0, 0)
    finally:
        idle.kill()
        idle.wait()
    before = listening_endpoints([os.getpid()])
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        assert listening_endpoints([os.getpid()])[0] == before[0] + 1
    path = tmp_path / "s.sock"
    with socket.socket(socket.AF_UNIX) as unix:
        unix.bind(str(path))
        assert listening_endpoints([os.getpid()])[1] == before[1] + 1
