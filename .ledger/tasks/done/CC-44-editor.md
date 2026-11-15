# CC-44: Browser rich-text editor

Human requested browser editing after the minimal viewer, and explicitly requested
starting on 0.0.0.0 at a random available port for review. Implement document
creation, text/heading formatting, save/reload and stale revision protection using
the existing Docs API. Bundle assets locally; no CDN or Google calls. Preserve
styles outside the toolbar where possible. Add real browser save/reload/conflict
coverage and leave a persistent local preview running. No image publication or
breadboard deployment is authorized by this request.

## Completed

- Tiptap/ProseMirror frontend, bundled locally and included in Python wheels.
- Document library with creation dialog and title search, responsive document page,
  headings 1–6, bold/italic/underline/strike, undo/redo and word count.
- Explicit save through Docs batchUpdate with requiredRevisionId. Stale saves
  preserve the local draft and explain recovery; reload confirms discarding edits.
- UTF-16-aware document conversion, paragraphs/blank lines, terminal newline and
  retained unexposed style metadata. Initial load failures support retry.
- Saved text/Markdown downloads; synthetic browser token works in strict mode.
- README, Make targets, CI browser test/build consistency checks, preview launcher
  and an editable welcome fixture. No CDN or real Google APIs.

## Evidence

- `REQUIRE_NODE_CONTRACT=1 REQUIRE_BROWSER_TEST=1 make test`: 15 pytest tests
  passed plus 3 Node editor-model tests. Browser tests use existing host Chromium
  against a strict-auth isolated localhost API. Covered create, marks, headings,
  emoji, save/reload, conflict preservation, empty save, mobile overflow and
  initial-load retry. External browser requests blocked during tests.
- `ruff check src tests scripts`: passed. `git diff --check`: passed.
- Built wheel with `uv build --offline --wheel --out-dir data/dist` and inspected
  ZIP contents for both bundled editor.js and editor.css assets.
- Browser screenshot inspected at ignored data/editor-preview.png.

## Preview

Started at human request with `scripts/preview.py`, binding 0.0.0.0 to random
available port 33291. URL http://p15.lab.net:33291; sample document at
/ui/documents/editor-welcome. PID 84913, log data/preview.log, PID file
 data/preview.pid, persistent state data/preview.sqlite (all ignored).
Launcher defaults to the same bind policy and a new OS-selected port each time.
No breadboard configuration changes, image release, or external deployment.

## Limits

Explicit saving; no realtime collaboration, autosave, tables/lists/images, title
renaming, or full Google formatting rendering. Unexposed styles are retained where
possible. Frontend commit 3457838 pushed to origin/main at the human’s explicit request.

## Handoff

Human approved pushing the editor and stopping the service. Pushed 3457838 to
origin/main. Sent SIGTERM to verified preview process 84913 and confirmed port
33291 is no longer listening. Removed stale ignored PID file; retained SQLite
data and logs. Preview is stopped.
