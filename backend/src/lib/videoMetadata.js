function parseFiniteNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseVideoInfo(probe) {
  const stream = probe?.streams?.[0] || {};
  const duration = parseFiniteNumber(probe?.format?.duration);
  const encodedWidth = Number.parseInt(stream.width, 10);
  const encodedHeight = Number.parseInt(stream.height, 10);

  if (!duration || duration <= 0) {
    throw new Error('A videó hossza nem állapítható meg.');
  }
  if (!Number.isInteger(encodedWidth) || !Number.isInteger(encodedHeight)) {
    throw new Error('A videó felbontása nem állapítható meg.');
  }

  const sideDataRotation = stream.side_data_list
    ?.map((item) => parseFiniteNumber(item?.rotation))
    .find((value) => value !== null);
  const tagRotation = parseFiniteNumber(stream.tags?.rotate);
  const rawRotation = sideDataRotation ?? tagRotation ?? 0;
  const rotation = ((Math.round(rawRotation) % 360) + 360) % 360;
  const quarterTurn = rotation === 90 || rotation === 270;
  const width = quarterTurn ? encodedHeight : encodedWidth;
  const height = quarterTurn ? encodedWidth : encodedHeight;

  return {
    duration: Math.round(duration * 100) / 100,
    width,
    height,
    encodedWidth,
    encodedHeight,
    rotation,
    orientation: width >= height ? 'landscape' : 'portrait',
  };
}

module.exports = { parseVideoInfo };
