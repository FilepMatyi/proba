export async function openStudioCamera(mediaDevices = navigator.mediaDevices) {
  const stream = await mediaDevices.getUserMedia({ audio: false, video: {
    facingMode: { ideal: 'environment' }, width: { ideal: 3840 }, height: { ideal: 2160 },
    frameRate: { ideal: 30, max: 30 }, resizeMode: 'none',
  } });
  const track = stream.getVideoTracks()[0];
  const capabilities = track.getCapabilities?.() || {};
  const advanced = {};
  if (capabilities.focusMode?.includes('continuous')) advanced.focusMode = 'continuous';
  if (capabilities.exposureMode?.includes('continuous')) advanced.exposureMode = 'continuous';
  if (capabilities.whiteBalanceMode?.includes('continuous')) advanced.whiteBalanceMode = 'continuous';
  if (capabilities.zoom && capabilities.zoom.min <= 1 && capabilities.zoom.max >= 1) advanced.zoom = 1;
  if (Object.keys(advanced).length) await track.applyConstraints({ advanced: [advanced] }).catch(() => {});
  return { stream, track, settings: track.getSettings?.() || {}, capabilities };
}

export async function captureStudioStill(track, video, imageCaptureFactory = globalThis.ImageCapture) {
  if (typeof imageCaptureFactory === 'function') {
    try {
      const capture = new imageCaptureFactory(track);
      let capabilities = null;
      if (typeof capture.getPhotoCapabilities === 'function') {
        try { capabilities = await capture.getPhotoCapabilities(); } catch { /* optional capability query */ }
      }
      const options = {};
      if (capabilities?.imageWidth?.max) options.imageWidth = capabilities.imageWidth.max;
      if (capabilities?.imageHeight?.max) options.imageHeight = capabilities.imageHeight.max;
      const blob = await capture.takePhoto(options);
      if (blob?.size && ['image/jpeg', 'image/png'].includes(blob.type)) {
        return { blob, method: 'native_still' };
      }
    } catch {
      // ImageCapture is not consistently supported across mobile browsers.
    }
  }
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  if (!canvas.width || !canvas.height) throw new Error('A kamera még nem kész a fotózáshoz.');
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', .96));
  if (!blob) throw new Error('A fotó nem készíthető el.');
  return { blob, method: 'stream_fallback' };
}

export async function imageSize(blob) {
  if (typeof createImageBitmap === 'function') {
    const bitmap = await createImageBitmap(blob);
    const size = { width: bitmap.width, height: bitmap.height };
    bitmap.close?.();
    return size;
  }
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => { resolve({ width: image.naturalWidth, height: image.naturalHeight }); URL.revokeObjectURL(url); };
    image.onerror = () => { reject(new Error('A fotó nem olvasható.')); URL.revokeObjectURL(url); };
    image.src = url;
  });
}
