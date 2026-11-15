"""Offline API server. No outbound HTTP or credential discovery."""

import json
import os
import re
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from html import escape
from io import BytesIO
from pathlib import Path
from threading import RLock
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape
from zipfile import ZipFile

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .model import Invalid, batch, document, from_fixture, new_document

DOC_MIME = "application/vnd.google-apps.document"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class APIError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Store:
    def __init__(self, path):
        self.lock = RLock()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        row = self.db.execute("SELECT payload FROM state WHERE id=1").fetchone()
        self.state = json.loads(row[0]) if row else {"files": {}, "docs": {}, "permissions": {}}

    def save(self):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(self.state),))
        self.db.commit()

    def file(self, identifier):
        if identifier not in self.state["files"]:
            raise APIError(404, "File not found")
        return self.state["files"][identifier]

    def create(self, metadata, doc=None):
        identifier = doc["documentId"] if doc else uuid4().hex
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        file = {
            "kind": "drive#file",
            "id": identifier,
            "name": metadata.get("name", "Untitled"),
            "mimeType": metadata.get("mimeType", DOC_MIME),
            "trashed": False,
            "parents": metadata.get("parents", []),
            "createdTime": now,
            "modifiedTime": now,
        }
        self.state["files"][identifier] = file
        if file["mimeType"] == DOC_MIME:
            self.state["docs"][identifier] = doc or new_document(file["name"], document_id=identifier)
        return file


def split_fields(value):
    depth, start, parts = 0, 0, []
    for i, c in enumerate(value):
        depth += (c == "(") - (c == ")")
        if c == "," and depth == 0:
            parts.append(value[start:i].strip())
            start = i + 1
    parts.append(value[start:].strip())
    if depth != 0:
        raise Invalid("Invalid fields mask")
    return parts


def project(value, fields):
    if not fields or fields == "*":
        return value
    if isinstance(value, list):
        return [project(v, fields) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for field in split_fields(fields):
        match = re.fullmatch(r"([\w*]+)(?:\((.*)\)|/(.*))?", field)
        if not match:
            raise Invalid("Invalid fields mask")
        key, sub, slash = match.groups()
        if key == "*":
            result.update(value)
        elif key in value:
            result[key] = project(value[key], sub or slash) if sub or slash else value[key]
    return result


def query_filter(files, query):
    if not query:
        return files
    # Deliberately restricted grammar; reject unsupported queries rather than returning all files.
    pattern = r"\s*(?:(name|mimeType|trashed)\s*(=|!=|contains)\s*('(?:\\.|[^'\\])*'|true|false)|('(?:\\.|[^'\\])*')\s+in\s+(parents))\s*"
    predicates = []
    rest = query
    while rest:
        match = re.match(pattern, rest)
        if not match:
            raise Invalid("Supported q: name/mimeType =, !=, contains; trashed =; parent in parents; joined by and")
        key, op, raw, parent, _ = match.groups()
        if parent:
            key, op, raw = "parents", "in", parent
        val = raw == "true" if raw in ("true", "false") else re.sub(r"\\(.)", r"\1", raw[1:-1])
        predicates.append((key, op, val))
        rest = rest[match.end() :]
        if rest:
            separator = re.match(r"and\s+", rest)
            if not separator:
                raise Invalid("Only and query composition is supported")
            rest = rest[separator.end() :]
            if not rest:
                raise Invalid("Missing predicate")

    def matches(file):
        for key, op, val in predicates:
            actual = file.get(key)
            if op == "=" and actual != val or op == "!=" and actual == val:
                return False
            if op in ("contains", "in") and val not in (actual or []):
                return False
        return True

    return [f for f in files if matches(f)]


def export(doc, mime):
    paragraphs = [x["paragraph"] for x in document(doc)["body"]["content"] if "paragraph" in x]
    texts = ["".join(e["textRun"]["content"] for e in p["elements"]) for p in paragraphs]
    if mime == "text/plain":
        return "".join(texts).encode()
    if mime in ("text/markdown", "text/x-markdown"):
        lines = []
        for p, text in zip(paragraphs, texts):
            style = p["paragraphStyle"].get("namedStyleType", "")
            prefix = "#" * int(style[-1]) + " " if re.fullmatch("HEADING_[1-6]", style) else ""
            lines.append(prefix + text)
        return "".join(lines).encode()
    if mime == DOCX_MIME:
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            )
            archive.writestr(
                "_rels/.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            )
            body = "".join(
                '<w:p><w:r><w:t xml:space="preserve">' + xml_escape(t.rstrip("\n")) + "</w:t></w:r></w:p>"
                for t in texts
            )
            archive.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                + body
                + "</w:body></w:document>",
            )
        return buffer.getvalue()
    raise Invalid("Unsupported export MIME type")


def create_app(database=None, seed=None, auth_mode=None):
    app = FastAPI(title="Google Docs emulator")
    store = Store(database or os.getenv("DATABASE_PATH", ":memory:"))
    app.state.store = store
    mode = auth_mode or os.getenv("AUTH_MODE", "permissive")
    if mode not in ("permissive", "strict", "none"):
        raise ValueError("Unknown AUTH_MODE")

    @app.exception_handler(APIError)
    async def api_error(request, exc):
        status = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 404: "NOT_FOUND", 409: "ABORTED"}.get(
            exc.code, "UNKNOWN"
        )
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "status": status}}, status_code=exc.code
        )

    @app.exception_handler(Invalid)
    async def invalid(request, exc):
        return await api_error(request, APIError(400, str(exc)))

    @app.middleware("http")
    async def auth(request, call_next):
        if mode == "strict" and request.url.path.startswith(("/v1/", "/drive/")):
            header = request.headers.get("authorization", "")
            if not header.startswith("Bearer ") or not header[7:].strip():
                return await api_error(request, APIError(401, "A fake Bearer token is required"))
        return await call_next(request)

    def save_doc(doc):
        identifier = doc["documentId"]
        store.state["docs"][identifier] = doc
        store.file(identifier)["modifiedTime"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def get_doc(identifier):
        store.file(identifier)
        if identifier not in store.state["docs"]:
            raise Invalid("File is not a Google document")
        return store.state["docs"][identifier]

    def seed_items(payload):
        items = payload.get("documents", [])
        state_before = deepcopy(store.state)
        try:
            for item in items:
                doc = from_fixture(item)
                if doc["documentId"] in store.state["files"]:
                    raise Invalid("Duplicate documentId in seed")
                store.create({"name": doc["title"]}, doc)
            store.save()
        except Exception:
            store.state = state_before
            raise
        return {"loaded": len(items)}

    seed_path = seed or os.getenv("SEED_FILE")
    if seed_path and not store.state["files"]:
        path = Path(seed_path)
        payload = (
            {"documents": [{"documentId": path.stem, "title": path.stem, "text": path.read_text()}]}
            if path.suffix == ".md"
            else json.loads(path.read_text())
        )
        seed_items(payload)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.post("/token")
    @app.post("/oauth2/token")
    async def token(request: Request):
        form = await request.form()
        if form.get("grant_type") not in (
            "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "refresh_token",
            "authorization_code",
            "client_credentials",
        ):
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        return {"access_token": "emulator-local-token", "token_type": "Bearer", "expires_in": 3600}

    @app.post("/v1/documents")
    def create_document(payload: dict):
        with store.lock:
            doc = new_document(payload.get("title", ""))
            store.create({"name": doc["title"]}, doc)
            store.save()
            return document(doc)

    @app.get("/v1/documents/{identifier}")
    def get_document(identifier: str, fields: str = "", includeTabsContent: bool = False):
        with store.lock:
            if includeTabsContent:
                raise Invalid("Tabs are not supported")
            return project(document(get_doc(identifier)), fields)

    @app.post("/v1/documents/{identifier}:batchUpdate")
    def update_document(identifier: str, payload: dict):
        with store.lock:
            doc = get_doc(identifier)
            control = payload.get("writeControl", {})
            if "targetRevisionId" in control:
                raise Invalid("targetRevisionId merge is not supported; use requiredRevisionId")
            if "requiredRevisionId" in control and control["requiredRevisionId"] != str(doc["revision"]):
                raise APIError(400, "Revision mismatch")
            try:
                updated, replies = batch(doc, payload.get("requests", []))
            except (KeyError, TypeError, AttributeError) as exc:
                raise Invalid("Malformed batch request") from exc
            save_doc(updated)
            store.save()
            return {
                "documentId": identifier,
                "replies": replies,
                "writeControl": {"requiredRevisionId": str(updated["revision"])},
            }

    @app.get("/drive/v3/files")
    def list_files(q: str = "", pageSize: int = 100, pageToken: str = "", fields: str = "", orderBy: str = ""):
        with store.lock:
            if not 1 <= pageSize <= 1000:
                raise Invalid("pageSize must be between 1 and 1000")
            try:
                offset = int(pageToken or "0")
                if offset < 0:
                    raise ValueError()
            except ValueError as exc:
                raise Invalid("Invalid pageToken") from exc
            files = query_filter(list(store.state["files"].values()), q)
            if orderBy:
                terms = [term.strip().split() for term in orderBy.split(",")]
                for term in reversed(terms):
                    if (
                        not term
                        or term[0] not in ("name", "createdTime", "modifiedTime")
                        or len(term) > 2
                        or len(term) == 2
                        and term[1] not in ("asc", "desc")
                    ):
                        raise Invalid("Unsupported orderBy")
                    files.sort(key=lambda f: f[term[0]], reverse=len(term) == 2 and term[1] == "desc")
            result = {"kind": "drive#fileList", "incompleteSearch": False, "files": files[offset : offset + pageSize]}
            if offset + pageSize < len(files):
                result["nextPageToken"] = str(offset + pageSize)
            return project(result, fields)

    @app.post("/drive/v3/files")
    def create_file(payload: dict, fields: str = ""):
        with store.lock:
            file = store.create(payload)
            store.save()
            return project(file, fields)

    @app.get("/drive/v3/files/{identifier}")
    def get_file(identifier: str, fields: str = "", alt: str = "json"):
        with store.lock:
            if alt != "json":
                raise Invalid("Use files.export for document content")
            return project(store.file(identifier), fields)

    @app.patch("/drive/v3/files/{identifier}")
    def update_file(identifier: str, payload: dict, fields: str = ""):
        with store.lock:
            file = store.file(identifier)
            if set(payload) - {"name", "trashed", "description"}:
                raise Invalid("Supported file updates: name, trashed, description")
            file.update(payload)
            if "name" in payload and identifier in store.state["docs"]:
                store.state["docs"][identifier]["title"] = payload["name"]
                store.state["docs"][identifier]["revision"] += 1
            store.save()
            return project(file, fields)

    @app.post("/drive/v3/files/{identifier}/copy")
    def copy_file(identifier: str, payload: dict, fields: str = ""):
        with store.lock:
            source = deepcopy(store.file(identifier))
            new_id = uuid4().hex
            doc = deepcopy(store.state["docs"].get(identifier))
            source.update(payload)
            if doc:
                doc.update(documentId=new_id, title=source["name"], revision=1)
            file = store.create(source, doc)
            store.save()
            return project(file, fields)

    @app.delete("/drive/v3/files/{identifier}", status_code=204)
    def delete_file(identifier: str):
        with store.lock:
            store.file(identifier)
            for category in ("files", "docs", "permissions"):
                store.state[category].pop(identifier, None)
            store.save()
            return Response(status_code=204)

    @app.get("/drive/v3/files/{identifier}/export")
    def export_file(identifier: str, mimeType: str):
        with store.lock:
            return Response(export(get_doc(identifier), mimeType), media_type=mimeType)

    @app.get("/drive/v3/files/{identifier}/permissions")
    def list_permissions(identifier: str):
        with store.lock:
            store.file(identifier)
            return {
                "kind": "drive#permissionList",
                "permissions": list(store.state["permissions"].get(identifier, {}).values()),
            }

    @app.post("/drive/v3/files/{identifier}/permissions")
    def create_permission(identifier: str, payload: dict):
        with store.lock:
            store.file(identifier)
            permission = {**payload, "id": uuid4().hex, "kind": "drive#permission"}
            store.state["permissions"].setdefault(identifier, {})[permission["id"]] = permission
            store.save()
            return permission

    @app.delete("/drive/v3/files/{identifier}/permissions/{permission_id}", status_code=204)
    def delete_permission(identifier: str, permission_id: str):
        with store.lock:
            store.file(identifier)
            permissions = store.state["permissions"].get(identifier, {})
            if permission_id not in permissions:
                raise APIError(404, "Permission not found")
            del permissions[permission_id]
            store.save()
            return Response(status_code=204)

    @app.post("/api/admin/reset")
    def reset():
        with store.lock:
            store.state = {"files": {}, "docs": {}, "permissions": {}}
            store.save()
            return {"status": "reset"}

    @app.post("/api/admin/seed")
    def seed_documents(payload: dict):
        with store.lock:
            return seed_items(payload)

    @app.get("/", response_class=HTMLResponse)
    def index():
        with store.lock:
            links = "".join(
                f'<li><a href="/ui/documents/{escape(d["documentId"], quote=True)}">{escape(d["title"])}</a></li>'
                for d in store.state["docs"].values()
            )
            return "<!doctype html><title>Google Docs emulator</title><h1>Documents</h1><ul>" + links + "</ul>"

    @app.get("/ui/documents/{identifier}", response_class=HTMLResponse)
    def viewer(identifier: str):
        with store.lock:
            doc = get_doc(identifier)
            return (
                '<!doctype html><meta charset="utf-8"><title>'
                + escape(doc["title"])
                + '</title><a href="/">Documents</a><h1>'
                + escape(doc["title"])
                + "</h1><pre>"
                + escape(export(doc, "text/plain").decode())
                + "</pre>"
            )

    return app


app = create_app()
