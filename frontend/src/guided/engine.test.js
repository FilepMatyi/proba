import assert from 'node:assert/strict';
import test from 'node:test';
import { beginRetake, captureTick, confirmCapture, evaluateQuality,
  initialCaptureState, smoothOrientation } from './engine.js';

const sample = (time, extras = {}) => ({ time, landscape: true, heading: null,
  sharpnessScore: .85, exposureScore: .8, stabilityScore: .9, roll: 3, ...extras });

test('ten sectors advance once each with a stable window and no heading fallback', () => {
  let state = initialCaptureState(0);
  for (let sector = 1; sector <= 10; sector++) {
    const start = (sector-1)*3200;
    let decision = captureTick(state, sample(start+10));
    state = decision.state;
    assert.equal(decision.capture, false);
    decision = captureTick(state, sample(start+650));
    state = decision.state;
    assert.equal(decision.capture, true, `sector ${sector}`);
    assert.equal(captureTick(state, sample(start+700)).capture, false);
    state = confirmCapture(state, start+650);
    assert.equal(state.captured.filter(Boolean).length, sector);
  }
  assert.equal(state.phase, 'done');
});

test('sensor heading uses broad sectors, smooths wrap and locks previous sector', () => {
  let state = initialCaptureState(0);
  state = captureTick(state, sample(0, { heading: 355 })).state;
  state = captureTick(state, sample(650, { heading: 355 })).state;
  state = confirmCapture(state, 650);
  state = captureTick(state, sample(1800, { heading: 5 })).state;
  assert.equal(state.maxProgress, 10);
  state = captureTick(state, sample(1900, { heading: 20 })).state;
  const decision = captureTick(state, sample(2550, { heading: 25 }));
  assert.equal(decision.capture, true);
  state = confirmCapture(decision.state, 2550);
  assert.equal(state.nextSector, 3);
  assert.equal(state.captured[1], true);
  const smoothed = smoothOrientation({ heading: 359, beta: 0, gamma: 0 },
    { heading: 1, beta: 2, gamma: 2 }, .5);
  assert.ok(smoothed.heading < 2 || smoothed.heading > 358);
});

test('roll comfort and critical quality gates are tolerant but safe', () => {
  assert.equal(evaluateQuality(sample(0, { roll: 5.9 })).grade, 'green');
  assert.equal(evaluateQuality(sample(0, { roll: 13 })).grade, 'red');
  assert.equal(evaluateQuality(sample(0, { landscape: false })).grade, 'red');
  assert.equal(evaluateQuality(sample(0, { vehicleBox: { x: .01, y: .1, width: .8, height: .6 } })).grade, 'red');
  assert.equal(evaluateQuality(sample(0, { exposureScore: .1 }), undefined, true).grade, 'red');
});

test('adaptive yellow permits a stable moment but not a critical error', () => {
  let state = initialCaptureState(0);
  const acceptable = { sharpnessScore: .31, stabilityScore: .9 };
  state = captureTick(state, sample(5100, acceptable)).state;
  assert.equal(captureTick(state, sample(5750, acceptable)).capture, true);
  state = initialCaptureState(0);
  state = captureTick(state, sample(5100, { ...acceptable, roll: 20 })).state;
  assert.equal(captureTick(state, sample(5750, { ...acceptable, roll: 20 })).capture, false);
});

test('a single retake preserves other captured positions', () => {
  let state = initialCaptureState(0);
  state.captured = Array(10).fill(true);
  state = beginRetake(state, 7, 1000);
  assert.equal(captureTick(state, sample(1000)).capture, false);
  const decision = captureTick(captureTick(state, sample(1000)).state, sample(1700));
  assert.equal(decision.capture, true);
  const finished = confirmCapture(decision.state, 1700);
  assert.equal(finished.phase, 'done');
  assert.equal(finished.captured.filter(Boolean).length, 10);
});

test('diagnostic instructions reset per sector and a red interval counts once', () => {
  let state = initialCaptureState(0);
  state = captureTick(state, sample(10, { roll: 20 })).state;
  state = captureTick(state, sample(140, { roll: 20 })).state;
  assert.equal(state.retries[0], 1);
  state = captureTick(state, sample(300)).state;
  const ready = captureTick(state, sample(950));
  assert.equal(ready.capture, true);
  assert.ok(ready.state.instructions['TARTSD STABILAN'] > 0);
  state = confirmCapture(ready.state, 950);
  assert.deepEqual(state.instructions, {});
});

test('candidate history waits briefly for a better still moment', () => {
  let state = captureTick(initialCaptureState(0), sample(10, {
    sharpnessScore: .95, stabilityScore: .95,
  })).state;
  let decision = captureTick(state, sample(650, {
    sharpnessScore: .48, stabilityScore: .55,
  }));
  assert.equal(decision.capture, false);
  state = decision.state;
  decision = captureTick(state, sample(1120, {
    sharpnessScore: .8, stabilityScore: .85,
  }));
  assert.equal(decision.capture, true);
});
