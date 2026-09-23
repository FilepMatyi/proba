const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const viewerRouter = require('../src/routes/viewer');

// Execute the actual emitted client, including cached/synchronous load events.
// This reproduces the previous unbounded HD onload -> show -> upgrade loop.
function mountViewer({ count = 36 } = {}) {
  let now = 0;
  const timers = new Map(), raf = [], requests = [];
  let nextTimer = 1;
  class Element {
    constructor() {
      this.listeners = {}; this.dataset = {}; this.style = {}; this.children = [];
      this.clientWidth = 1000; this.clientHeight = 600;
      const names = new Set();
      this.classList = { add: n => names.add(n), remove: n => names.delete(n), contains: n => names.has(n) };
    }
    addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
    emit(type, data = {}) { for (const f of this.listeners[type] || []) f({ type, target: this, preventDefault() {}, ...data }); }
    setAttribute() {}
    appendChild(el) { this.children.push(el); }
    closest() { return null; }
    setPointerCapture() {}
    getBoundingClientRect() { return { left: 0, top: 0, width: 1000, height: 600 }; }
  }
  class FakeImage extends Element {
    set src(value) { this.url = value; requests.push({ image: this, url: value }); }
    get src() { return this.url; }
    decode() { return Promise.resolve(); }
  }
  const elements = Object.fromEntries(['stage','frame','loading','loadingText','empty','hint','toast','current','play','zoomIn','zoomOut','reset','share','fullscreen','scrubber'].map(id => [id, new Element()]));
  const window = new Element();
  Object.assign(window, { matchMedia: () => ({ matches: true }),
    setTimeout: fn => { const id = nextTimer++; timers.set(id, fn); return id; },
    clearTimeout: id => timers.delete(id), setInterval: () => 0, clearInterval() {} });
  const document = new Element();
  Object.assign(document, { getElementById: id => elements[id], visibilityState: 'visible' });
  const sources = Array.from({ length: count }, (_, i) => ({ preview: 'preview-'+i, hd: 'hd-'+i }));
  const html = viewerRouter.renderViewer({ vehicleId: 'test', imageSources: sources, nonce: 'test', canonicalUrl: '', socialImageUrl: '' });
  vm.runInNewContext(html.match(/<script nonce="test">([\s\S]*?)<\/script>/)[1], {
    document, window, Image: FakeImage, performance: { now: () => now },
    requestAnimationFrame: fn => raf.push(fn), navigator: {}, location: {},
  });
  const tick = (dt = 16) => { now += dt; raf.shift()(now); };
  const flushTimers = () => { const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()); };
  const load = request => request.image.onload?.();
  // Five preview loads suffice to start interaction, with the rest lazy-loaded.
  [...requests].forEach(load);
  tick();
  return { ...elements, window, document, requests, tick, flushTimers, load };
}

test('zoom pan updates one shared layer and survives lost pointer capture', () => {
  const ui = mountViewer();
  ui.stage.emit('dblclick', { clientX: 600, clientY: 300 });
  ui.tick();
  assert.equal(ui.frame.style.transform, 'translate(-100px,0px) scale(2)');
  ui.stage.emit('pointerdown', { pointerId: 1, clientX: 500, clientY: 300 });
  for (let x = 510; x <= 600; x += 10) ui.stage.emit('pointermove', { pointerId: 1, clientX: x, clientY: 330 });
  assert.equal(ui.frame.style.transform, 'translate(-100px,0px) scale(2)', 'batched until RAF');
  ui.tick();
  assert.equal(ui.frame.style.transform, 'translate(0px,30px) scale(2)');
  assert.ok(ui.frame.children.every(img => img.style.transform === undefined));
  ui.stage.emit('lostpointercapture', { pointerId: 1 });
  assert.equal(ui.stage.classList.contains('grabbing'), false);
  ui.stage.emit('pointerdown', { pointerId: 2, clientX: 600, clientY: 330 });
  ui.stage.emit('pointermove', { pointerId: 2, clientX: 520, clientY: 300 });
  ui.tick();
  assert.equal(ui.frame.style.transform, 'translate(-80px,0px) scale(2)');
  ui.window.emit('blur');
  assert.equal(ui.stage.classList.contains('grabbing'), false);
});

test('HD decoding is deduplicated, concurrency limited and not restarted by cached loads', async () => {
  const ui = mountViewer();
  ui.flushTimers();
  const hd = () => ui.requests.filter(r => r.url.startsWith('hd-') && !ui.frame.children.includes(r.image));
  assert.equal(hd().length, 2, 'at most two HD preloads at once');
  for (let i = 0; i < 120; i++) ui.tick();
  assert.equal(hd().length, 2, 'no repeat HD requests for the same view');
  await ui.load(hd()[0]);
  assert.equal(hd().length, 3, 'next neighbour after first decode');
  await ui.load(ui.requests.find(r => r.image === ui.frame.children[0] && r.url === 'hd-0'));
  assert.equal(hd().length, 3, 'cached image onload must not recurse into another upgrade');
  await ui.load(hd()[1]); await ui.load(hd()[2]);
  assert.equal(ui.frame.children.filter(img => img.dataset.hd === 'true').length, 3);
});

test('rotation wraps across the seam and zoom/reset keep interaction alive', () => {
  const ui = mountViewer();
  ui.stage.emit('keydown', { key: 'ArrowLeft' });
  assert.equal(ui.current.textContent, '36');
  ui.stage.emit('keydown', { key: 'ArrowRight' });
  assert.equal(ui.current.textContent, '01');
  ui.zoomIn.emit('click'); ui.tick();
  ui.reset.emit('click'); ui.tick();
  assert.equal(ui.frame.style.transform, 'translate(0px,0px) scale(1)');
  ui.stage.emit('pointerdown', { pointerId: 1, clientX: 500, clientY: 300 });
  ui.stage.emit('pointermove', { pointerId: 1, clientX: 516, clientY: 300 });
  ui.tick();
  assert.equal(ui.current.textContent, '02');
  ui.stage.emit('pointercancel', { pointerId: 1 });
  ui.tick(40);
  assert.equal(ui.current.textContent, '02', 'cancel stops inertia');
});

test('changing views evicts HD outside the three-view working set', async () => {
  const ui = mountViewer();
  ui.flushTimers();
  for (let i = 0; i < 3; i++) {
    const request = ui.requests.filter(r => r.url.startsWith('hd-') && !ui.frame.children.includes(r.image))[i];
    await ui.load(request);
  }
  ui.flushTimers();
  ui.requests.filter(r => r.url.startsWith('preview-')).forEach(ui.load);
  ui.scrubber.emit('input', { target: { value: '18' } });
  ui.flushTimers();
  assert.equal(ui.current.textContent, '19');
  assert.equal(ui.frame.children.filter(img => img.dataset.hd === 'true').length, 0);
  assert.equal(ui.frame.children[0].src, 'preview-0');
  const latest = ui.requests.filter(r => r.url.startsWith('hd-') && !ui.frame.children.includes(r.image)).slice(-2);
  await ui.load(latest[0]); await ui.load(latest[1]);
  assert.ok(ui.frame.children.filter(img => img.dataset.hd === 'true').length <= 3);
});

test('failed HD does not replace a working preview or freeze zoom', () => {
  const ui = mountViewer();
  ui.flushTimers();
  const high = ui.requests.find(r => r.url === 'hd-0' && !ui.frame.children.includes(r.image));
  high.image.onerror();
  assert.equal(ui.frame.children[0].src, 'preview-0');
  ui.zoomIn.emit('click'); ui.tick();
  assert.match(ui.frame.style.transform, /scale\(1.35\)/);
  assert.equal(ui.frame.children[0].classList.contains('active'), true);
});

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
  assert.match(html, /Ellenőrzött képsorozat/);
});

test('viewer marks a low-quality sequence for review', () => {
  const html = viewerRouter.renderViewer({
    vehicleId: 'review-car',
    imageSources: [],
    nonce: 'test-nonce',
    canonicalUrl: 'https://example.com/viewer/review-car',
    socialImageUrl: 'https://example.com/viewer/review-car/image/processed-1.jpg',
    qualityNeedsReview: true,
    qualityLabel: 'Minőségellenőrzés szükséges',
  });

  assert.match(html, /class="quality review"/);
  assert.match(html, /Minőségellenőrzés szükséges/);
});
