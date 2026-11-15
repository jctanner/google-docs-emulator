"""Run inside the built image with --network none; only uses standard library."""

import json
import subprocess
import time
import urllib.request


def call(path, payload=None):
    request = urllib.request.Request(
        "http://127.0.0.1:8080" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.load(response)


def start():
    process = subprocess.Popen(["uvicorn", "google_docs_emulator.app:app", "--host", "127.0.0.1", "--port", "8080"])
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Server exited")
        try:
            assert call("/healthz") == {"status": "ok"}
            return process
        except OSError:
            time.sleep(0.05)
    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError("Server did not become ready")


server = start()
try:
    identifier = call("/v1/documents", {"title": "Container smoke"})["documentId"]
    call(
        f"/v1/documents/{identifier}:batchUpdate",
        {"requests": [{"insertText": {"location": {"index": 1}, "text": "Persistence works"}}]},
    )
finally:
    server.terminate()
    server.wait(timeout=10)
server = start()
try:
    document = call("/v1/documents/" + identifier)
    assert document["body"]["content"][1]["paragraph"]["elements"][0]["textRun"]["content"] == "Persistence works\n"
    print("Container startup, editing and persistent restart passed")
finally:
    server.terminate()
    server.wait(timeout=10)
