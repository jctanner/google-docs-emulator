// Google Docs indices and JavaScript string lengths both use UTF-16 code units.
const clone = value => JSON.parse(JSON.stringify(value));
const knownMarks = {bold: 'bold', italic: 'italic', underline: 'underline', strikethrough: 'strike'};

function toEditor(doc) {
  const content = doc.body.content.filter(x => x.paragraph).map(({paragraph}) => {
    const style = clone(paragraph.paragraphStyle || {});
    const heading = /^HEADING_([1-6])$/.exec(style.namedStyleType || '');
    const runs = paragraph.elements.map((element, i, all) => {
      if (!element.textRun) throw new Error('This editor supports text paragraphs only.');
      let text = element.textRun.content;
      if (i === all.length - 1 && text.endsWith('\n')) text = text.slice(0, -1);
      if (!text) return null;
      const extra = clone(element.textRun.textStyle || {});
      const marks = [];
      for (const [key, name] of Object.entries(knownMarks)) {
        if (extra[key]) marks.push({type: name});
        delete extra[key];
      }
      if (Object.keys(extra).length) marks.push({type: 'googleStyle', attrs: {value: extra}});
      return {type: 'text', text, marks};
    }).filter(Boolean);
    const last = paragraph.elements.at(-1)?.textRun;
    return {type: heading ? 'heading' : 'paragraph',
      attrs: {googleParagraphStyle: style, newlineStyle: clone(last?.textStyle || {}), ...(heading ? {level: +heading[1]} : {})},
      content: runs};
  });
  return {type: 'doc', content};
}

function snapshot(json) {
  let text = '';
  const paragraphs = [], runs = [];
  for (const paragraph of json.content || []) {
    if (!['paragraph', 'heading'].includes(paragraph.type)) throw new Error('Unsupported editor block');
    const startIndex = text.length + 1;
    for (const node of paragraph.content || []) {
      if (node.type !== 'text') throw new Error('Unsupported editor content');
      const style = clone(node.marks?.find(m => m.type === 'googleStyle')?.attrs.value || {});
      for (const [key, name] of Object.entries(knownMarks)) {
        if (node.marks?.some(m => m.type === name)) style[key] = true;
      }
      const start = text.length + 1;
      text += node.text;
      if (node.text.length) runs.push({startIndex: start, endIndex: text.length + 1, textStyle: style});
    }
    const end = text.length + 1;
    text += '\n';
    runs.push({startIndex: end, endIndex: end + 1, textStyle: clone(paragraph.attrs?.newlineStyle || {})});
    const style = clone(paragraph.attrs?.googleParagraphStyle || {});
    if (paragraph.type === 'heading') style.namedStyleType = 'HEADING_' + paragraph.attrs.level;
    else if (/^HEADING_[1-6]$/.test(style.namedStyleType || '')) style.namedStyleType = 'NORMAL_TEXT';
    paragraphs.push({startIndex, endIndex: text.length + 1, paragraphStyle: style});
  }
  return {text: text || '\n', runs, paragraphs};
}

function toBatch(json, previousEndIndex, revisionId) {
  const state = snapshot(json);
  const requests = [];
  if (previousEndIndex > 2) requests.push({deleteContentRange: {range: {startIndex: 1, endIndex: previousEndIndex - 1}}});
  if (state.text.length > 1) requests.push({insertText: {location: {index: 1}, text: state.text.slice(0, -1)}});
  // Clear inherited styles, including the final newline that cannot be deleted.
  requests.push({updateTextStyle: {range: {startIndex: 1, endIndex: state.text.length + 1}, textStyle: {}, fields: '*'}});
  for (const run of state.runs) {
    if (Object.keys(run.textStyle).length) requests.push({updateTextStyle: {range: {startIndex: run.startIndex, endIndex: run.endIndex}, textStyle: run.textStyle, fields: '*'}});
  }
  for (const paragraph of state.paragraphs) {
    requests.push({updateParagraphStyle: {range: {startIndex: paragraph.startIndex, endIndex: paragraph.endIndex}, paragraphStyle: paragraph.paragraphStyle, fields: '*'}});
  }
  return {requests, writeControl: {requiredRevisionId: revisionId}};
}

module.exports = {toEditor, snapshot, toBatch};
