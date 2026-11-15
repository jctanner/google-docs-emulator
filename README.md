# Google Docs emulator

An offline Google Docs v1 and supporting Drive v3 emulator for agent workflows.
Python/FastAPI, with optional SQLite persistence. It never contacts Google and does
not discover or validate real credentials. All API paths share one origin.

## Run locally

```sh
uv sync --frozen --extra dev
npm ci --ignore-scripts
make serve
# In another terminal:
make smoke
REQUIRE_NODE_CONTRACT=1 make test
make lint
```

The server listens at `http://127.0.0.1:8080`. `/` lists and creates documents;
`/ui/documents/{id}` opens the rich-text editor. `/healthz` is the health probe.
Dependencies install into this repository, not system Python or Node.

| Setting | Default | Meaning |
| --- | --- | --- |
| `DATABASE_PATH` | `:memory:` | SQLite file; use `data/docs.sqlite` for persistence |
| `SEED_FILE` | unset | JSON fixture or UTF-8 Markdown file; loaded only into an empty store |
| `AUTH_MODE` | `permissive` | `permissive`/`none` accept requests; `strict` requires any nonempty Bearer token on Docs/Drive |

Run one worker per database. Mutations serialize in-process and batch validation
happens on a copy before commit. Concurrent processes sharing a database are not
supported. Admin/UI routes are unauthenticated local test controls; bind the
server to loopback in development.

## Browser editor

The document library supports creating and finding documents. The editor offers
paragraphs, six heading levels, bold/italic/underline/strikethrough, undo/redo,
word count, and text/Markdown downloads of the saved document. Paste from other
editors is reduced to the supported paragraph and inline formatting schema.
Changes save explicitly with **Save changes** or **Ctrl/⌘ S**. Reload asks before
discarding unsaved edits. A revision check rejects stale saves when an agent or
another browser changes the document; your local draft stays visible for copying.
No autosave, collaborative cursors, tables, lists, images, or title renaming yet.
Unexposed API style metadata is retained through load/save where possible; not all
Google formatting is displayed in the browser.

The frontend uses Tiptap/ProseMirror, bundled locally. No CDN or Google calls.
The committed bundle is included in Python wheels and container images. After
changing `frontend/`, run `npm ci --ignore-scripts` and `make frontend`.
CI checks that the bundle matches source and runs real Chromium browser contracts.
For local browser tests set `CHROMIUM_PATH` to your Chromium executable and
`REQUIRE_BROWSER_TEST=1 make test` (requires `npm ci`).

For a preview on **0.0.0.0 at a random available port**, run:

```sh
make preview
```

It prints its URL and persists documents in ignored `data/preview.sqlite`.
Stop with Ctrl-C. The browser sends an emulator-only fake token so it also works
with `AUTH_MODE=strict`.

## Supported APIs

- `POST /v1/documents`, `GET /v1/documents/{id}` and
  `POST /v1/documents/{id}:batchUpdate`.
- Batch operations: `insertText`, `deleteContentRange`, `replaceAllText`,
  `updateParagraphStyle`, `updateTextStyle`. Paragraph heading styles use
  `namedStyleType: HEADING_1` through `HEADING_6`. Style field masks support
  top-level keys and `*`; omitted masked properties reset. UTF-16 indices start
  at 1 after the section break. The final newline cannot be removed.
- Structural `body.content`, paragraphs, text runs and indices; styles survive
  edits and copies. `writeControl.requiredRevisionId` prevents stale updates.
- Drive `/drive/v3/files`: list/get/create/update/copy/delete/export. Creating
  a Google document through Drive creates the corresponding Docs resource.
  Metadata-only non-Docs files (including folders) are supported.
- List supports pagination, `fields` projections, sorting by name/createdTime/
  modifiedTime, and `q` predicates on name/mimeType (`=`, `!=`, `contains`),
  trashed, and `'<id>' in parents`, composed with `and`. Unsupported queries
  return 400. Explicitly use `trashed = false` to hide trashed files.
- Exports: `text/plain`, `text/markdown` (paragraph heading prefixes), and a minimal
  valid DOCX ZIP containing plain paragraphs. DOCX does not preserve rich styles.
- Permission create/list/delete stubs retain metadata; they do not enforce ACLs
  or send invitations. No comments, Sheets, tables, tabs, headers/footers, media
  upload, revisions API, regex replacement, or full Drive query language.
- Unknown batch operations return 400, never a fabricated success.

## Official Python client

The Python library ships static discovery documents. Endpoint override alone does
not redirect OAuth: set the token URI separately if using token refresh. Never
load default or real service-account credentials for this emulator.

```python
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

base = 'http://127.0.0.1:8080/'
credentials = Credentials(token='fake-local-token')
docs = build('docs', 'v1', credentials=credentials, static_discovery=True,
             cache_discovery=False, client_options={'api_endpoint': base})
drive = build('drive', 'v3', credentials=credentials, static_discovery=True,
              cache_discovery=False, client_options={'api_endpoint': base + 'drive/v3/'})
created = docs.documents().create(body={'title': 'Example'}).execute()
docs.documents().batchUpdate(documentId=created['documentId'], body={
    'requests': [{'insertText': {'location': {'index': 1}, 'text': 'Hello!'}}]
}).execute()
```

## Official Node client

```js
const {google} = require('googleapis');
const auth = new google.auth.OAuth2('local', 'local');
auth.setCredentials({access_token: 'fake-local-token'});
const docs = google.docs({version: 'v1', auth, rootUrl: 'http://127.0.0.1:8080/'});
const drive = google.drive({version: 'v3', auth, rootUrl: 'http://127.0.0.1:8080/'});
```

`POST /token` (also `/oauth2/token`) accepts refresh, authorization-code,
client-credentials, and service-account JWT bearer grants without validating the
assertion. It returns a fixed fake token and never calls an upstream issuer.
For a synthetic service-account credential set its token URI to this local path;
the SDK can sign with an ephemeral test key. No identity or scope isolation exists.

Tests use static discovery and synthetic tokens, block non-loopback DNS/socket
connections, and start isolated in-memory servers. `make test` skips the Node
contract if `npm ci` has not run; `REQUIRE_NODE_CONTRACT=1 make test` requires it.

## Fixtures and reset

```sh
curl -f -H 'Content-Type: application/json' --data-binary @fixtures/example.json \
  http://127.0.0.1:8080/api/admin/seed
curl -f -X POST http://127.0.0.1:8080/api/admin/reset
```

JSON format: `{"documents":[{"documentId":"stable-id","title":"Example","text":"Hello\n"}]}`.
The `text` form accepts Markdown as literal text; no Markdown-to-style parsing is
performed. A `body.content` structural document can be used instead of `text`;
paragraph and run styles are preserved and indices are recomputed. Fixture loading
is atomic and rejects duplicate IDs. Reset empties all docs, files and permissions
and persists the empty state; it does not automatically reload fixtures.

## Container and release

```sh
docker build -t google-docs-emulator:local .
docker run --rm -p 127.0.0.1:8080:8080 -v docs-data:/data google-docs-emulator:local
```

For a network-isolated startup/edit/persistent-restart smoke test:

```sh
docker run --rm -i --network none --entrypoint python google-docs-emulator:local - < tests/container_smoke.py
```

The image runs as UID 10001 and stores state in `/data/google-docs.sqlite`.
CI runs lint and both official clients. The container workflow builds and smoke
tests locally on pull requests. GHCR publication is manual and uses the
`image-release` environment: configure required human reviewers before enabling
publication. There is no automatic push/release publication.

Source: https://github.com/jctanner/google-docs-emulator (published with human
approval). Image publication and breadboard integration/deployment still require
separate explicit human approval.

## Compatibility references

- [Document structure and UTF-16 indices](https://developers.google.com/workspace/docs/api/concepts/structure)
- [Batch update requests](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request)
- [Drive file search](https://developers.google.com/workspace/drive/api/guides/search-files)
- [Drive export](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
