function imageDimensions(buffer) {
  if (buffer.length >= 24 && buffer.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20), type: 'image/png' };
  }
  if (buffer.length < 4 || buffer[0] !== 0xff || buffer[1] !== 0xd8) return null;
  let offset = 2;
  while (offset + 4 < buffer.length) {
    if (buffer[offset] !== 0xff) return null;
    const marker = buffer[offset + 1];
    offset += 2;
    if (marker === 0xd9 || marker === 0xda) break;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
    if (offset + 2 > buffer.length) break;
    const length = buffer.readUInt16BE(offset);
    if (length < 2 || offset + length > buffer.length) break;
    if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb].includes(marker)) {
      if (length < 7) return null;
      return { width: buffer.readUInt16BE(offset + 5), height: buffer.readUInt16BE(offset + 3), type: 'image/jpeg' };
    }
    offset += length;
  }
  return null;
}

function safeCaptureMetadata(raw, index) {
  const value = JSON.parse(raw || '{}');
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid metadata');
  const finite = (field, min, max) => {
    const number = Number(value[field]);
    return value[field] == null || value[field] === '' ? null
      : Number.isFinite(number) && number >= min && number <= max ? number : null;
  };
  return {
    captureIndex: index,
    targetSector: index,
    timestamp: finite('timestamp', 0, 1e15),
    roll: finite('roll', -180, 180),
    pitch: finite('pitch', -180, 180),
    deviceOrientationAvailable: value.deviceOrientationAvailable === true,
    vehicleWidthRatio: finite('vehicleWidthRatio', 0, 1),
    vehicleHeightRatio: finite('vehicleHeightRatio', 0, 1),
    sharpnessScore: finite('sharpnessScore', 0, 1),
    exposureScore: finite('exposureScore', 0, 1),
    stabilityScore: finite('stabilityScore', 0, 1),
    captureQuality: finite('captureQuality', 0, 1),
    captureConfidence: ['high', 'medium', 'low'].includes(value.captureConfidence)
      ? value.captureConfidence : 'low',
    captureMethod: value.captureMethod === 'native_still' ? 'native_still' : 'stream_fallback',
    guidance: typeof value.guidance === 'string' ? value.guidance.slice(0, 40) : null,
    sectorDurationMs: finite('sectorDurationMs', 0, 120000),
    retryCount: finite('retryCount', 0, 10000),
    instructionCounts: value.instructionCounts && typeof value.instructionCounts === 'object'
      ? Object.fromEntries(Object.entries(value.instructionCounts).slice(0, 16)
        .filter(([key, count]) => key.length <= 50 && Number.isInteger(count) && count >= 0 && count <= 10000))
      : {},
  };
}

module.exports = { imageDimensions, safeCaptureMetadata };
