const VEHICLE_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;

function normalizeVehicleId(value) {
  if (typeof value !== 'string') return null;

  const normalized = value.trim().toLowerCase();
  return VEHICLE_ID_PATTERN.test(normalized) ? normalized : null;
}

function parsePhotoIndex(value, totalFrames = 36) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > totalFrames) return null;
  return parsed;
}

module.exports = { VEHICLE_ID_PATTERN, normalizeVehicleId, parsePhotoIndex };
