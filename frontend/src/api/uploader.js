const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

async function parseResponse(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `A kérés sikertelen (${response.status}).`);
  return payload;
}

export function uploadVideo(vehicleId, videoBlob, sensorData, onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    const isMp4 = videoBlob.type.toLowerCase().includes('mp4');
    formData.append('video', videoBlob, isMp4 ? 'capture.mp4' : 'capture.webm');
    if (sensorData?.length) formData.append('sensorData', JSON.stringify(sensorData));

    const request = new XMLHttpRequest();
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener('load', () => {
      let payload = {};
      try {
        payload = JSON.parse(request.responseText);
      } catch {
        // The HTTP status below still provides a useful fallback error.
      }
      if (request.status >= 200 && request.status < 300) resolve(payload);
      else reject(new Error(payload.error || `A feltöltés sikertelen (${request.status}).`));
    });
    request.addEventListener('error', () => reject(new Error('Hálózati hiba történt a feltöltés közben.')));
    request.addEventListener('abort', () => reject(new Error('A feltöltés megszakadt.')));
    request.addEventListener('timeout', () => reject(new Error('A feltöltés túllépte az időkorlátot.')));
    request.timeout = 10 * 60 * 1000;
    request.open('POST', `${API_BASE_URL}/vehicles/${encodeURIComponent(vehicleId)}/video`);
    request.send(formData);
  });
}

export async function getSessions() {
  return parseResponse(await fetch(`${API_BASE_URL}/sessions`));
}

export async function getSession(vehicleId) {
  return parseResponse(await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(vehicleId)}`));
}

export async function deleteSession(vehicleId) {
  return parseResponse(await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(vehicleId)}`, { method: 'DELETE' }));
}

export async function getStudioPhotos(vehicleId) {
  return parseResponse(await fetch(`${API_BASE_URL}/vehicles/${encodeURIComponent(vehicleId)}/studio-photos`));
}

export async function generateStudioPhotos(vehicleId) {
  return parseResponse(await fetch(`${API_BASE_URL}/vehicles/${encodeURIComponent(vehicleId)}/studio-photos`, {
    method: 'POST',
  }));
}

export function studioPhotoUrl(vehicleId, filename, revision) {
  const url = `${API_BASE_URL}/vehicles/${encodeURIComponent(vehicleId)}/studio-photos/files/${filename}`;
  return revision ? `${url}?v=${encodeURIComponent(revision)}` : url;
}

export async function startGuidedStudio(vehicleId) {
  return parseResponse(await fetch(`${API_BASE_URL}/vehicles/${encodeURIComponent(vehicleId)}/guided-studio`, {
    method: 'POST',
  }));
}

export async function getGuidedStudio(vehicleId) {
  return parseResponse(await fetch(`${API_BASE_URL}/vehicles/${encodeURIComponent(vehicleId)}/guided-studio`));
}

export async function uploadGuidedPhoto(vehicleId, captureId, sector, blob, metadata) {
  const body = new FormData();
  body.append('photo', blob, blob.type === 'image/png' ? 'capture.png' : 'capture.jpg');
  body.append('captureId', captureId);
  body.append('metadata', JSON.stringify(metadata));
  return parseResponse(await fetch(`${API_BASE_URL}/vehicles/${encodeURIComponent(vehicleId)}/guided-studio/photos/${sector}`, {
    method: 'PUT', body,
  }));
}

export async function processGuidedStudio(vehicleId, captureId) {
  return parseResponse(await fetch(`${API_BASE_URL}/vehicles/${encodeURIComponent(vehicleId)}/guided-studio/process`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ captureId }),
  }));
}
