const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const viewerRouter = require('../src/routes/viewer');

test('viewer emits valid progressive-loading client JavaScript', () => {
  const html = viewerRouter.renderViewer({
    vehicleId: 'demo-car',
    imageSources: [
      { preview: '/viewer/demo-car/image/preview-1.jpg', hd: '/viewer/demo-car/image/processed-1.jpg' },
      { preview: '/viewer/demo-car/image/preview-2.jpg', hd: '/viewer/demo-car/image/processed-2.jpg' },
    ],
    nonce: 'test-nonce',
    canonicalUrl: 'https://example.com/viewer/demo-car',
    socialImageUrl: 'https://example.com/viewer/demo-car/image/processed-1.jpg',
  });

  const script = html.match(/<script nonce="test-nonce">([\s\S]*?)<\/script>/);
  assert.ok(script, 'inline viewer script is present');
  assert.doesNotThrow(() => new vm.Script(script[1]));
  assert.match(html, /adaptív HD/);
  assert.match(html, /preview-1\.jpg/);
  assert.match(html, /processed-1\.jpg/);
});
