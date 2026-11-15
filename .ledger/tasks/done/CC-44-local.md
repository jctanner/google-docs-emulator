# CC-44: Google Docs emulator

Scope confirmed by human on 2026-11-14: Docs v1 editing, supporting Drive subset,
fake auth, seed/reset/persistence, viewer, Python and Node official client contracts,
local packaging and CI. Sheets and comments deferred. No first consumer identified.
Remote repository creation, pushes, image publication, and breadboard integration
require separate approval. No external writes or deployment authorized.

Implementation in progress. Evidence and limitations will be recorded here.

## Completed local work

- Python/FastAPI Docs v1 create/get/atomic batch editing with UTF-16 indices,
  paragraphs, runs, text/paragraph styles and required-revision checks.
- Drive metadata lifecycle, supported q filters/pagination/projections/sorting,
  document copying, plain text/heading Markdown/minimal DOCX exports, ACL metadata stubs.
- Local OAuth refresh/JWT grants, permissive/strict fake Bearer auth.
- Atomic JSON/structural fixture import, literal Markdown fixture loading,
  reset, optional SQLite persistence, escaped read-only document viewer.
- Locked Python and Node dependencies, Dockerfile, CI and manual GHCR workflow.
- README documents client endpoint overrides and compatibility limits.

## Verification (2026-11-14)

- `UV_CACHE_DIR=/tmp/cc44-uv-cache REQUIRE_NODE_CONTRACT=1 make test`: 14 passed.
  Includes official google-api-python-client 2.202.0 and googleapis Node 166,
  synthetic service-account JWT exchange, invalid/atomic batches, UTF-16,
  concurrent edits, fixtures, reset, persistence, exports, metadata and permissions.
- `make lint`: passed. `git diff --check`: passed.
- `podman build --format docker -t localhost/google-docs-emulator:cc44 .`: passed.
- `podman run --rm -i --network none --entrypoint python
  localhost/google-docs-emulator:cc44 - < tests/container_smoke.py`: passed;
  verified startup, edit and SQLite state after server restart, without external networking.
- Local tests ran under Python 3.14; image smoke under Python 3.13.
- TestClient emits an upstream httpx deprecation warning; no test failures.
- Restricted sandbox cannot run TestClient/localhost tests reliably; tests ran
  with sandbox escalation. Tests reject external network destinations and use
  only synthetic credentials. No real Google API calls or credentials used.

## Deliberate limits

Single process per database. Paragraph/text-run body only; no tabs/tables/media,
Sheets or comments. Markdown fixture text is literal. DOCX preserves text only.
Drive query grammar and style masks are subsets, documented in README.
Permissions do not enforce ACLs. No identity/scope isolation. Admin controls are
for a trusted local test environment.

Local scope complete. See pending publication/integration task for approvals.
