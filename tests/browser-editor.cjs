const {chromium} = require('@playwright/test');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const base = process.argv[2];
  assert.match(base, /^http:\/\/127\.0\.0\.1:\d+$/);
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium-browser', args: ['--no-sandbox']});
  const context = await browser.newContext({viewport: {width: 1360, height: 1000}});
  const errors = [];
  await context.route('**/*', route => {
    if (route.request().url().startsWith(base + '/')) return route.continue();
    errors.push('External request: ' + route.request().url());
    return route.abort();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  let failFirstLoad = true;
  await page.route('**/v1/documents/*', route => {
    if (failFirstLoad && route.request().method() === 'GET') {
      failFirstLoad = false;
      return route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({error: {message: 'Simulated load failure'}})});
    }
    return route.continue();
  });
  const api = async (url, body) => {
    const response = await context.request.fetch(base + url, {method: body ? 'POST' : 'GET', headers: {Authorization: 'Bearer fake-browser-test'}, ...(body ? {data: body} : {})});
    assert.ok(response.ok(), await response.text());
    return response.json();
  };
  try {
    await page.goto(base);
    await page.getByRole('button', {name: '+ New document'}).click();
    await page.getByLabel('Document title').fill('Rich text browser contract');
    await page.getByRole('button', {name: 'Create document', exact: true}).click();
    await page.waitForURL('**/ui/documents/*');
    const id = page.url().split('/').at(-1);
    const editor = page.getByRole('textbox', {name: 'Document content'});
    await page.getByRole('alert').filter({hasText: 'Simulated load failure'}).waitFor();
    await page.getByRole('button', {name: 'Reload', exact: true}).click();
    await page.getByRole('status').filter({hasText: 'All changes saved'}).waitFor();
    await editor.fill('Hello 😀 world');
    await editor.press('ControlOrMeta+a');
    await page.getByRole('button', {name: 'Bold', exact: true}).click();
    await page.getByRole('button', {name: 'Italic', exact: true}).click();
    await page.getByRole('button', {name: 'Underline', exact: true}).click();
    await page.getByRole('button', {name: 'Strikethrough', exact: true}).click();
    await page.getByLabel('Paragraph style').selectOption('2');
    await page.getByRole('button', {name: 'Save changes'}).click();
    await page.getByRole('status').filter({hasText: 'All changes saved'}).waitFor();
    let doc = await api('/v1/documents/' + id);
    let paragraph = doc.body.content[1].paragraph;
    assert.equal(paragraph.paragraphStyle.namedStyleType, 'HEADING_2');
    assert.equal(paragraph.elements[0].textRun.content, 'Hello 😀 world');
    assert.deepEqual(paragraph.elements[0].textRun.textStyle, {bold: true, italic: true, underline: true, strikethrough: true});
    await page.reload();
    await page.getByRole('status').filter({hasText: 'All changes saved'}).waitFor();
    assert.equal(await editor.locator('h2').textContent(), 'Hello 😀 world');
    // An API edit after load must not be overwritten by a stale browser save.
    await api('/v1/documents/' + id + ':batchUpdate', {requests: [{insertText: {location: {index: 1}, text: 'Agent update: '}}]});
    await editor.press('ControlOrMeta+End');
    await page.keyboard.type(' local draft');
    await page.getByRole('button', {name: 'Save changes'}).click();
    await page.getByRole('alert').filter({hasText: 'changed elsewhere'}).waitFor();
    assert.ok((await editor.textContent()).includes('local draft'));
    assert.ok(!(await api('/v1/documents/' + id)).body.content[1].paragraph.elements.some(e => e.textRun.content.includes('local draft')));
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', {name: 'Reload', exact: true}).click();
    await page.getByRole('status').filter({hasText: 'All changes saved'}).waitFor();
    assert.ok((await editor.textContent()).startsWith('Agent update:'));
    // Clear formatting and all text; empty saves must retain the required newline.
    await editor.press('ControlOrMeta+a');
    await page.keyboard.press('Backspace');
    await page.getByLabel('Paragraph style').selectOption('0');
    await page.getByRole('button', {name: 'Save changes'}).click();
    await page.getByRole('status').filter({hasText: 'All changes saved'}).waitFor();
    doc = await api('/v1/documents/' + id);
    assert.equal(doc.body.content[1].paragraph.elements[0].textRun.content, '\n');
    await editor.fill('A calmer space for your next idea.');
    await page.getByRole('button', {name: 'Save changes'}).click();
    await page.getByRole('status').filter({hasText: 'All changes saved'}).waitFor();
    await page.screenshot({path: path.join('data', 'editor-preview.png'), fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('Browser create, rich formatting, save/reload, stale revision, empty document, and mobile layout passed');
  } catch (error) { console.error('Browser errors:', errors, 'Alert:', await page.locator('#error').textContent(), 'Status:', await page.getByRole('status').textContent()); throw error; }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
