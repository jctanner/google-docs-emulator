import {Editor, Extension, Mark} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import {toEditor, snapshot, toBatch} from './document-model.cjs';

const $ = selector => document.querySelector(selector);
const id = document.body.dataset.documentId;
const errorBox = $('#error');
function showError(message) { errorBox.textContent = message; errorBox.hidden = !message; }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json', Authorization: 'Bearer emulator-browser', ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || data.detail || `Request failed (${response.status})`);
  return data;
}

if (!id) {
  const dialog = $('#create-dialog');
  $('#new-document').onclick = () => { $('#create-error').hidden = true; dialog.showModal(); };
  $('#cancel-create').onclick = () => dialog.close();
  $('#create-form').onsubmit = async event => {
    event.preventDefault();
    $('#confirm-create').disabled = true;
    try {
      const doc = await api('/v1/documents', {method: 'POST', body: JSON.stringify({title: $('#new-title').value.trim() || 'Untitled document'})});
      location.assign('/ui/documents/' + encodeURIComponent(doc.documentId));
    } catch (error) { $('#create-error').textContent = error.message; $('#create-error').hidden = false; }
    finally { $('#confirm-create').disabled = false; }
  };
  $('#search').oninput = event => {
    let count = 0;
    document.querySelectorAll('.document-card').forEach(card => {
      card.hidden = !card.querySelector('strong').textContent.toLowerCase().includes(event.target.value.toLowerCase());
      if (!card.hidden) count++;
    });
    $('#empty-state').textContent = 'No documents found. Create a document or try another search.';
    $('#empty-state').hidden = count !== 0;
  };
} else {
  let revision, previousEnd, dirty = false, busy = false, editor;
  const status = $('#status');
  const endpoint = '/v1/documents/' + encodeURIComponent(id);
  const attributes = Extension.create({
    name: 'googleParagraphAttributes',
    addGlobalAttributes() {
      return [{types: ['paragraph', 'heading'], attributes: {
        googleParagraphStyle: {default: {}, rendered: false}, newlineStyle: {default: {}, rendered: false},
      }}];
    },
  });
  const googleStyle = Mark.create({
    name: 'googleStyle', inclusive: true,
    addAttributes() { return {value: {default: {}, rendered: false}}; },
    parseHTML() { return []; },
    renderHTML() { return ['span', {}, 0]; },
  });
  function toolbar() {
    if (!editor) { $('#reload').disabled = busy; return; }
    document.querySelectorAll('[data-command]').forEach(button => {
      const command = button.dataset.command;
      button.disabled = busy || (command === 'undo' ? !editor.can().undo() : command === 'redo' ? !editor.can().redo() : false);
      if (!['undo', 'redo'].includes(command)) button.setAttribute('aria-pressed', String(editor.isActive(command)));
    });
    $('#block-style').disabled = busy;
    $('#block-style').value = editor.isActive('heading') ? String(editor.getAttributes('heading').level) : '0';
    $('#save').disabled = !dirty || busy;
    $('#reload').disabled = busy;
    const value = snapshot(editor.getJSON()).text.trim();
    $('#word-count').textContent = `${value ? value.split(/\s+/u).length : 0} words`;
  }
  async function load() {
    if (dirty && !confirm('Discard your unsaved changes and reload the latest document?')) return;
    busy = true;
    if (editor) editor.setEditable(false, false);
    toolbar();
    showError('');
    try {
      const doc = await api(endpoint);
      const content = toEditor(doc);
      if (editor) editor.destroy(); // Clear undo history: reloading cannot resurrect stale edits.
      editor = new Editor({
        element: $('#editor'),
        extensions: [StarterKit.configure({bulletList: false, orderedList: false, listItem: false, listKeymap: false,
          blockquote: false, code: false, codeBlock: false, hardBreak: false, horizontalRule: false, link: false, trailingNode: false}),
          attributes, googleStyle],
        content,
        editorProps: {attributes: {'aria-label': 'Document content', role: 'textbox', 'aria-multiline': 'true'},
          handleKeyDown: (_, event) => {
            // Every visual line is a Docs paragraph; prevent unsupported hard-break nodes.
            if (event.key === 'Enter' && event.shiftKey) { event.preventDefault(); editor.commands.splitBlock(); return true; }
            return false;
          }},
        onUpdate: () => { dirty = true; status.textContent = 'Unsaved changes'; toolbar(); },
        onSelectionUpdate: toolbar,
        onTransaction: toolbar,
      });
      revision = doc.revisionId;
      previousEnd = doc.body.content.at(-1).endIndex;
      document.querySelector('h1').textContent = doc.title || 'Untitled document';
      document.title = (doc.title || 'Untitled document') + ' · Docs emulator';
      dirty = false;
      status.textContent = 'All changes saved';
    } catch (error) { showError(error.message); status.textContent = 'Could not load document'; }
    finally { busy = false; if (editor) editor.setEditable(true, false); toolbar(); }
  }
  async function save() {
    if (!editor || busy || !dirty) return;
    busy = true;
    editor.setEditable(false, false);
    toolbar(); showError(''); status.textContent = 'Saving…';
    try {
      const json = editor.getJSON();
      const result = await api(endpoint + ':batchUpdate', {method: 'POST', body: JSON.stringify(toBatch(json, previousEnd, revision))});
      revision = result.writeControl.requiredRevisionId;
      previousEnd = snapshot(json).text.length + 1;
      dirty = false;
      status.textContent = 'All changes saved';
    } catch (error) {
      showError(error.message === 'Revision mismatch'
        ? 'This document changed elsewhere. Your edits are still here. Copy them before choosing Reload to load the latest version.'
        : `Could not save: ${error.message}. Your edits are still here; try Save again.`);
      status.textContent = 'Changes not saved';
    } finally { busy = false; editor.setEditable(true, false); toolbar(); }
  }
  document.querySelectorAll('[data-command]').forEach(button => {
    button.onmousedown = event => event.preventDefault();
    button.onclick = () => {
      const commands = {bold: 'toggleBold', italic: 'toggleItalic', underline: 'toggleUnderline', strike: 'toggleStrike', undo: 'undo', redo: 'redo'};
      editor.chain().focus()[commands[button.dataset.command]]().run();
      toolbar();
    };
  });
  $('#block-style').onchange = event => {
    const level = +event.target.value;
    if (level) editor.chain().focus().setHeading({level}).run();
    else editor.chain().focus().setParagraph().run();
    toolbar();
  };
  $('#save').onclick = save;
  $('#reload').onclick = load;
  for (const [name, mime] of [['text', 'text/plain'], ['markdown', 'text/markdown']]) {
    const anchor = $('#export-' + name);
    anchor.href = '#';
    anchor.onclick = async event => {
      event.preventDefault();
      try {
        const response = await fetch(`/drive/v3/files/${encodeURIComponent(id)}/export?mimeType=${encodeURIComponent(mime)}`, {headers: {Authorization: 'Bearer emulator-browser'}});
        if (!response.ok) throw new Error('Export failed');
        const url = URL.createObjectURL(await response.blob());
        const download = document.createElement('a'); download.href = url; download.download = `${document.querySelector('h1').textContent}.${name === 'text' ? 'txt' : 'md'}`;
        download.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (error) { showError(error.message); }
    };
  }
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save(); } });
  load();
}
