const test = require('node:test');
const assert = require('node:assert/strict');
const { imageDimensions, safeCaptureMetadata } = require('../src/lib/guidedImages');

test('guided upload validates JPEG and PNG dimensions without trusting metadata', () => {
  const png = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(png);
  png.writeUInt32BE(4032, 16); png.writeUInt32BE(3024, 20);
  assert.deepEqual(imageDimensions(png), { width: 4032, height: 3024, type: 'image/png' });
  const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xc0, 0, 11, 8, 0x08, 0x70,
    0x0f, 0x00, 3, 1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0]);
  assert.deepEqual(imageDimensions(jpeg), { width: 3840, height: 2160, type: 'image/jpeg' });
  assert.equal(imageDimensions(Buffer.from('not an image')), null);
});

test('guided capture metadata keeps bounded values and no fake distance', () => {
  const value = safeCaptureMetadata(JSON.stringify({ timestamp: 123, roll: 5,
    sharpnessScore: .83, captureMethod: 'native_still', cameraDistanceMeters: 2.5 }), 3);
  assert.equal(value.captureIndex, 3);
  assert.equal(value.captureMethod, 'native_still');
  assert.equal(value.sharpnessScore, .83);
  assert.equal('cameraDistanceMeters' in value, false);
});
