"""Locally bundled browser editor shell; all dynamic text is escaped."""

from html import escape


def page(doc=None, documents=()):
    title = escape(doc["title"] if doc else "Documents")
    identifier = escape(doc["documentId"], quote=True) if doc else ""
    cards = "".join(
        '<a class="document-card" href="/ui/documents/' + escape(d["documentId"], quote=True) + '">'
        '<span class="doc-icon" aria-hidden="true">▤</span><strong>'
        + escape(d["title"] or "Untitled document")
        + "</strong><span>Open document →</span></a>"
        for d in documents
    )
    workspace = (
        """<div class="document-heading"><a href="/" class="back">← All documents</a>
      <div class="title-row"><span class="doc-icon" aria-hidden="true">▤</span><h1>"""
        + title
        + """</h1></div>
      <div class="document-meta"><span id="status" role="status" aria-live="polite">Loading document…</span>
      <span id="word-count"></span></div></div>
      <section class="editor-workspace" aria-label="Document workspace">
      <div class="toolbar" role="toolbar" aria-label="Text formatting">
        <select id="block-style" aria-label="Paragraph style" disabled>
          <option value="0">Normal text</option><option value="1">Heading 1</option>
          <option value="2">Heading 2</option><option value="3">Heading 3</option>
          <option value="4">Heading 4</option><option value="5">Heading 5</option><option value="6">Heading 6</option>
        </select><span class="divider"></span>
        <button data-command="bold" aria-label="Bold" title="Bold (Ctrl/⌘ B)" disabled><b>B</b></button>
        <button data-command="italic" aria-label="Italic" title="Italic (Ctrl/⌘ I)" disabled><i>I</i></button>
        <button data-command="underline" aria-label="Underline" title="Underline (Ctrl/⌘ U)" disabled><u>U</u></button>
        <button data-command="strike" aria-label="Strikethrough" title="Strikethrough" disabled><s>S</s></button>
        <span class="divider"></span>
        <button data-command="undo" aria-label="Undo" title="Undo" disabled>↶</button>
        <button data-command="redo" aria-label="Redo" title="Redo" disabled>↷</button>
        <div class="toolbar-spacer"></div><button id="reload" disabled>Reload</button>
        <button id="save" class="primary" disabled>Save changes</button>
      </div>
      <div id="error" role="alert" hidden></div>
      <div class="page-area"><div class="paper"><div id="editor"></div></div></div>
      <footer><span>Changes save when you choose Save · Ctrl/⌘ S</span>
      <div><a id="export-text">Download text</a><a id="export-markdown">Markdown</a></div></footer>
      </section>"""
    )
    if not doc:
        workspace = (
            """<section class="library-heading"><div><p class="eyebrow">YOUR WORKSPACE</p>
          <h1>Documents</h1><p>Create a draft, shape an idea, or pick up where you left off.</p></div>
          <button id="new-document" class="primary">+ New document</button></section>
          <div class="library-tools"><h2>All documents</h2><input id="search" type="search" placeholder="Find a document…" aria-label="Find a document"></div>
          <div id="error" role="alert" hidden></div><div class="document-grid">"""
            + cards
            + '''</div>
          <p id="empty-state" class="empty-state"'''
            + (" hidden" if cards else "")
            + """>Your next idea starts here. Create your first document above.</p>
          <dialog id="create-dialog"><form id="create-form"><h2>New document</h2>
          <label for="new-title">Document title</label><input id="new-title" name="title" placeholder="Untitled document" maxlength="250" autofocus>
          <p id="create-error" role="alert" hidden></p><div class="dialog-actions"><button id="cancel-create" type="button">Cancel</button>
          <button id="confirm-create" class="primary" type="submit">Create document</button></div></form></dialog>"""
        )
    return (
        """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <title>"""
        + title
        + ''' · Docs emulator</title><link rel="stylesheet" href="/static/editor.css"></head>
      <body data-document-id="'''
        + identifier
        + """"><header class="app-header"><a class="brand" href="/"><span class="brand-mark">▤</span>Docs<span class="brand-subtitle">EMULATOR</span></a><span class="environment"><span></span>Local workspace</span></header>
      <main>"""
        + workspace
        + """</main><script type="module" src="/static/editor.js"></script></body></html>"""
    )
