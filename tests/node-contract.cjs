const assert = require('node:assert/strict');
const {google} = require('googleapis');
// Fail closed: block every outgoing socket except literal loopback.
const net = require('node:net');
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const opts = Array.isArray(args[0]) ? args[0][0] : args[0];
  if (!opts || typeof opts !== 'object' || opts.host !== '127.0.0.1') {
    throw new Error('Only literal loopback is allowed in contract tests');
  }
  return connect.apply(this, args);
};
(async () => {
  const base = process.argv[2];
  assert.match(base, /^http:\/\/127\.0\.0\.1:\d+$/);
  const auth = new google.auth.OAuth2('local', 'local');
  auth.setCredentials({access_token: 'fake-node-token'});
  const docs = google.docs({version: 'v1', auth, rootUrl: base + '/'});
  const drive = google.drive({version: 'v3', auth, rootUrl: base + '/'});
  const {data: created} = await docs.documents.create({requestBody: {title: 'Node contract'}});
  const documentId = created.documentId;
  await docs.documents.batchUpdate({documentId, requestBody: {requests: [
    {insertText: {location: {index: 1}, text: 'Node 😀 works'}},
    {deleteContentRange: {range: {startIndex: 1, endIndex: 6}}},
    {replaceAllText: {containsText: {text: 'works', matchCase: true}, replaceText: 'tested'}}
  ]}});
  const {data: doc} = await docs.documents.get({documentId});
  assert.equal(doc.body.content[1].paragraph.elements[0].textRun.content, '😀 tested\n');
  const {data: exported} = await drive.files.export({fileId: documentId, mimeType: 'text/plain'}, {responseType: 'text'});
  assert.equal(exported, '😀 tested\n');
  const {data: listed} = await drive.files.list({q: "name = 'Node contract'", fields: 'files(id,name)'});
  assert.equal(listed.files[0].id, documentId);
  const {data: copied} = await drive.files.copy({fileId: documentId, requestBody: {name: 'Node copy'}});
  await drive.files.delete({fileId: copied.id});
  console.log('Official Node googleapis contract passed');
})().catch(error => { console.error(error); process.exit(1); });
