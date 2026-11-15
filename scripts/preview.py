"""Persistent local preview: random available port on all interfaces by default."""

import os
import socket
from pathlib import Path

import uvicorn

os.environ.setdefault("DATABASE_PATH", str(Path("data/preview.sqlite").resolve()))
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", 0))
port = sock.getsockname()[1]
print(f"PREVIEW_URL=http://{socket.getfqdn()}:{port}", flush=True)
server = uvicorn.Server(uvicorn.Config("google_docs_emulator.app:app", log_level="info"))
server.run(sockets=[sock])
