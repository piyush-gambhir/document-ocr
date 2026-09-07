const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

test('Clear prevents an in-flight extraction from restoring private document data', async () => {
  function element() {
    return {
      value: '', files: [], textContent: '', disabled: false,
      getContext: () => ({ clearRect() {} }),
      replaceChildren() {}, add() {}, addEventListener() {},
      setAttribute() {}, append() {},
    };
  }
  const ids = ['file', 'token', 'country', 'type', 'scan', 'clear', 'status',
    'canvas', 'fields', 'json', 'csv', 'redact', 'raw'];
  const elements = new Map(ids.map(id => [id, element()]));
  elements.get('file').files = [new File(['synthetic'], 'sample.png', { type: 'image/png' })];
  let completeScan;
  const pendingResponse = new Promise(resolve => { completeScan = resolve; });
  const context = {
    document: { getElementById: id => elements.get(id), createElement: element },
    FormData, URL, Blob, AbortController, setTimeout,
    Image: function () {}, Option: function () {},
    // Deliberately complete even after abort: state must also reject late results.
    fetch: url => url === '/scan' ? pendingResponse : Promise.resolve({ ok: false }),
  };
  const html = readFileSync(path.join(__dirname, '../../core/review.html'), 'utf8');
  vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  const extracting = elements.get('scan').onclick();
  elements.get('clear').onclick();
  completeScan({
    ok: true,
    json: async () => ({ status: 'success', documentType: 'pan', confidence: 1,
      documentFields: { name: 'PRIVATE PERSON' } }),
  });
  await extracting;
  assert.equal(elements.get('raw').textContent, '');
  assert.equal(elements.get('status').textContent, 'Document cleared.');
  for (const id of ['json', 'csv', 'redact']) assert.equal(elements.get(id).disabled, true);
});
