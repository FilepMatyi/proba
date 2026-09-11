const test = require('node:test');
const assert = require('node:assert/strict');

const { normalizeVehicleId, parsePhotoIndex } = require('../src/lib/vehicleId');

test('vehicle IDs are normalized for storage and URLs', () => {
  assert.equal(normalizeVehicleId('  Lancer-16  '), 'lancer-16');
  assert.equal(normalizeVehicleId('stock_2026'), 'stock_2026');
});

test('unsafe vehicle IDs are rejected', () => {
  assert.equal(normalizeVehicleId('../escape'), null);
  assert.equal(normalizeVehicleId('<script>'), null);
  assert.equal(normalizeVehicleId('contains space'), null);
  assert.equal(normalizeVehicleId(''), null);
});

test('photo indexes stay inside the configured spin', () => {
  assert.equal(parsePhotoIndex('1', 36), 1);
  assert.equal(parsePhotoIndex(36, 36), 36);
  assert.equal(parsePhotoIndex(0, 36), null);
  assert.equal(parsePhotoIndex(37, 36), null);
  assert.equal(parsePhotoIndex('1.5', 36), null);
});
