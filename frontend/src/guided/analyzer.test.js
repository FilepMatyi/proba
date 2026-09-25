import assert from 'node:assert/strict';
import test from 'node:test';
import { analyzePreview } from './analyzer.js';

function canvasFor(pattern) {
  const data = new Uint8ClampedArray(160*90*4);
  for (let y = 0; y < 90; y++) for (let x = 0; x < 160; x++) {
    const value = pattern(x, y);
    const offset = (y*160+x)*4;
    data[offset] = data[offset+1] = data[offset+2] = value;
    data[offset+3] = 255;
  }
  return { getContext: () => ({ drawImage() {}, getImageData: () => ({ data }) }) };
}

test('preview analysis prefers fine detail and steady frames without full-resolution work', () => {
  const flat = analyzePreview({}, canvasFor(() => 128));
  const detailed = analyzePreview({}, canvasFor((x, y) => (x+y)%2 ? 195 : 60));
  assert.ok(detailed.sharpnessScore > flat.sharpnessScore);
  assert.ok(detailed.sharpnessScore > .5);
  assert.equal(flat.gray.length, 160*90);
  const steady = analyzePreview({}, canvasFor((x, y) => (x+y)%2 ? 195 : 60), detailed.gray);
  assert.equal(steady.stabilityScore, 1);
});
