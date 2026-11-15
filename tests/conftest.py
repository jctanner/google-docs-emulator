import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from google_docs_emulator.app import create_app


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """Fail closed if any client attempts a non-loopback connection."""
    original = socket.getaddrinfo

    def resolve(host, *args, **kwargs):
        if host not in ("localhost", "127.0.0.1", "::1", None):
            raise AssertionError(f"External network forbidden in tests: {host}")
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def live_url():
    app = create_app(auth_mode="strict")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Test server failed to start")
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
