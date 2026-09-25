import assert from 'node:assert/strict';
import test from 'node:test';
import { captureStudioStill, openStudioCamera } from './camera.js';

test('camera feature detection keeps 1× zoom when supported', async () => {
  const constraints = [];
  const track = { getCapabilities: () => ({ zoom: { min: 1, max: 4 },
    focusMode: ['continuous'] }), applyConstraints: async (value) => constraints.push(value),
    getSettings: () => ({ width: 3840, height: 2160 }) };
  const mediaDevices = { getUserMedia: async (value) => {
    assert.equal(value.video.facingMode.ideal, 'environment');
    return { getVideoTracks: () => [track] };
  } };
  const result = await openStudioCamera(mediaDevices);
  assert.equal(result.settings.width, 3840);
  assert.equal(constraints[0].advanced[0].zoom, 1);
});

test('native still is preferred when ImageCapture succeeds', async () => {
  const image = new Blob(['native'], { type: 'image/jpeg' });
  class NativeCapture {
    async getPhotoCapabilities() { return { imageWidth: { max: 4000 }, imageHeight: { max: 3000 } }; }
    async takePhoto(options) { assert.equal(options.imageWidth, 4000); return image; }
  }
  const result = await captureStudioStill({}, {}, NativeCapture);
  assert.equal(result.method, 'native_still');
  assert.equal(result.blob, image);
});

test('unsupported native still falls back to stream frame', async () => {
  const previous = globalThis.document;
  globalThis.document = { createElement: () => ({
    getContext: () => ({ drawImage: () => {} }),
    toBlob: (callback) => callback(new Blob(['stream'], { type: 'image/jpeg' })),
  }) };
  class BrokenCapture { async takePhoto() { throw new Error('unsupported'); } }
  try {
    const result = await captureStudioStill({}, { videoWidth: 1920, videoHeight: 1080 }, BrokenCapture);
    assert.equal(result.method, 'stream_fallback');
    assert.ok(result.blob.size > 0);
  } finally { globalThis.document = previous; }
});
