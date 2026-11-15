const {test} = require('node:test');
const assert = require('node:assert/strict');
const {toEditor, snapshot, toBatch} = require('../frontend/document-model.cjs');

test('UTF-16, headings, blank paragraphs and unexposed styles round-trip', () => {
  const doc = {body: {content: [
    {sectionBreak: {}},
    {paragraph: {paragraphStyle: {namedStyleType: 'HEADING_2', spaceAbove: {magnitude: 5, unit: 'PT'}}, elements: [
      {textRun: {content: '😀', textStyle: {bold: true, fontSize: {magnitude: 16, unit: 'PT'}}}},
      {textRun: {content: ' world\n', textStyle: {italic: true}}}]}},
    {paragraph: {paragraphStyle: {}, elements: [{textRun: {content: '\n', textStyle: {underline: true}}}]}}
  ]}};
  const editor = toEditor(doc);
  const state = snapshot(editor);
  assert.equal(state.text, '😀 world\n\n');
  assert.deepEqual(state.runs[0], {startIndex: 1, endIndex: 3, textStyle: {bold: true, fontSize: {magnitude: 16, unit: 'PT'}}});
  assert.equal(state.paragraphs[0].paragraphStyle.namedStyleType, 'HEADING_2');
  assert.equal(state.paragraphs[0].paragraphStyle.spaceAbove.magnitude, 5);
  assert.equal(state.paragraphs[1].startIndex, 10);
  const batch = toBatch(editor, 11, '7');
  assert.deepEqual(batch.writeControl, {requiredRevisionId: '7'});
  assert.deepEqual(batch.requests[0], {deleteContentRange: {range: {startIndex: 1, endIndex: 10}}});
  assert.equal(batch.requests[1].insertText.text, '😀 world\n');
});

test('empty document saves without deleting final newline', () => {
  const batch = toBatch({type: 'doc', content: [{type: 'paragraph', content: []}]}, 2, '1');
  assert.equal(batch.requests.length, 2);
  assert.equal(batch.requests[0].updateTextStyle.range.endIndex, 2);
});

test('heading to normal text clears heading and removing bold does not revive it', () => {
  const state = snapshot({content: [{type: 'paragraph', attrs: {googleParagraphStyle: {namedStyleType: 'HEADING_1'}}, content: [{type: 'text', text: 'plain'}]}]});
  assert.equal(state.paragraphs[0].paragraphStyle.namedStyleType, 'NORMAL_TEXT');
  assert.deepEqual(state.runs[0].textStyle, {});
});
