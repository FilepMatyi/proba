// Manual end-to-end exercise: node test/manualGuidedSmoke.mjs [source-directory]
// Uses an isolated guided-smoke-* ID and existing JPEG test sources; does not
// simulate native mobile ImageCapture or device orientation.
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const source = resolve(process.argv[2] || '../ai-worker/debug/car-test-5-studio-photos-v3-selection');
const base = process.env.GUIDED_SMOKE_API || 'http://localhost:3000/api';
const vehicleId = `guided-smoke-${Date.now()}`;
const api = `${base}/vehicles/${vehicleId}`;

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const value = await response.json();
  if (!response.ok) throw new Error(`${response.status} ${url}: ${JSON.stringify(value)}`);
  return value;
}

const session = await request(`${api}/guided-studio`, { method: 'POST' });
console.log(`Session: ${vehicleId}`);
for (let index = 1; index <= 10; index++) {
  const bytes = await readFile(resolve(source, `${String(index).padStart(2, '0')}-source.jpg`));
  const form = new FormData();
  form.set('captureId', session.captureId);
  form.set('metadata', JSON.stringify({ captureIndex: index, targetSector: index,
    timestamp: Date.now() + index, captureMethod: 'stream_fallback',
    captureConfidence: 'medium', captureQuality: .7, sharpnessScore: .7,
    exposureScore: .7, stabilityScore: .8, sectorDurationMs: 1000 }));
  form.set('photo', new Blob([bytes], { type: 'image/jpeg' }), `${index}.jpg`);
  await request(`${api}/guided-studio/photos/${index}`, { method: 'PUT', body: form });
  console.log(`Uploaded ${index}/10`);
}
await request(`${api}/guided-studio/process`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ captureId: session.captureId }) });
const deadline = Date.now() + 25 * 60 * 1000;
while (Date.now() < deadline) {
  await new Promise((done) => setTimeout(done, 10000));
  const status = await request(`${api}/studio-photos`);
  console.log(`${status.status}: ${status.completed ?? 0}/10`);
  if (status.status === 'failed') throw new Error(status.error || 'Worker failed');
  if (status.status !== 'ready') continue;
  if (status.sourceMode !== 'guided_stills' || status.photos?.length !== 10) {
    throw new Error('Guided manifest is incomplete');
  }
  const image = await fetch(`${api}/studio-photos/files/01.jpg`);
  const album = await fetch(`${api}/studio-photos/files/album.zip`);
  if (!image.ok || !album.ok) throw new Error('Output download failed');
  console.log(JSON.stringify({ vehicleId, count: status.photos.length,
    sourceMode: status.sourceMode, sourceSize: [status.photos[0].sourceWidth, status.photos[0].sourceHeight],
    outputSize: [status.photos[0].width, status.photos[0].height],
    imageBytes: Number(image.headers.get('content-length')),
    albumBytes: Number(album.headers.get('content-length')) }, null, 2));
  process.exit(0);
}
throw new Error(`Timed out waiting for ${vehicleId}`);
