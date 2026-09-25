const clamp = (value) => Math.max(0, Math.min(1, value));

export function analyzePreview(video, canvas, previousGray = null, vehicleBox = null) {
  canvas.width = 160;
  canvas.height = 90;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(video, 0, 0, 160, 90);
  const rgba = context.getImageData(0, 0, 160, 90).data;
  const gray = new Float32Array(160*90);
  for (let i = 0; i < gray.length; i++) {
    const offset = i*4;
    const value = .2126*rgba[offset]+.7152*rgba[offset+1]+.0722*rgba[offset+2];
    gray[i] = value;
  }
  const roi = vehicleBox || { x: .12, y: .15, width: .76, height: .72 };
  const x0 = Math.max(2, Math.round(roi.x*160));
  const x1 = Math.min(158, Math.round((roi.x+roi.width)*160));
  const y0 = Math.max(2, Math.round(roi.y*90));
  const y1 = Math.min(88, Math.round((roi.y+roi.height)*90));
  let lapSquare = 0; let motion = 0; let count = 0;
  let roiTotal = 0; let roiClipped = 0;
  for (let y = y0; y < y1; y += 2) {
    for (let x = x0; x < x1; x += 2) {
      const i = y*160+x;
      const lap = 4*gray[i]-gray[i-1]-gray[i+1]-gray[i-160]-gray[i+160];
      lapSquare += lap*lap;
      roiTotal += gray[i];
      if (gray[i] < 8 || gray[i] > 247) roiClipped += 1;
      if (previousGray) motion += Math.abs(gray[i]-previousGray[i]);
      count += 1;
    }
  }
  // The analysis grid is sampled every other pixel. Energy avoids a parity
  // alias where a fine repeating edge gives a constant-sign Laplacian sample.
  const variance = lapSquare/count;
  // Keep usable dynamic range for detailed vehicle previews; a low ceiling
  // would label both a merely acceptable frame and a truly sharp one as 1.0.
  const sharpnessScore = clamp((Math.log1p(Math.max(0, variance))-Math.log1p(30))
    / (Math.log1p(12000)-Math.log1p(30)));
  const brightness = roiTotal/count;
  const exposureScore = clamp(1-Math.abs(brightness-128)/120-(roiClipped/count)*1.7);
  const stabilityScore = previousGray ? clamp(1-(motion/count)/22) : .5;
  return { gray, sharpnessScore, exposureScore, stabilityScore,
    brightness, clippingRatio: roiClipped/count, vehicleBox };
}
