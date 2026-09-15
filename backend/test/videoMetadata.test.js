const test = require('node:test');
const assert = require('node:assert/strict');

const { parseVideoInfo } = require('../src/lib/videoMetadata');

test('video metadata applies display rotation before reporting orientation', () => {
  const info = parseVideoInfo({
    streams: [{
      width: 1920,
      height: 1080,
      side_data_list: [{ rotation: -90 }],
    }],
    format: { duration: '37.912333' },
  });

  assert.deepEqual(info, {
    duration: 37.91,
    width: 1080,
    height: 1920,
    encodedWidth: 1920,
    encodedHeight: 1080,
    rotation: 270,
    orientation: 'portrait',
  });
});

test('video metadata keeps an unrotated landscape stream unchanged', () => {
  const info = parseVideoInfo({
    streams: [{ width: 1920, height: 1080 }],
    format: { duration: 30 },
  });

  assert.equal(info.width, 1920);
  assert.equal(info.height, 1080);
  assert.equal(info.rotation, 0);
  assert.equal(info.orientation, 'landscape');
});
