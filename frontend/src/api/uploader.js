const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

export const uploadVideo = async (vehicleId, videoBlob, sensorData, onProgress) => {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    // Assuming the blob is webm or mp4
    formData.append('video', videoBlob, 'capture.webm');
    
    if (sensorData && sensorData.length > 0) {
      formData.append('sensorData', JSON.stringify(sensorData));
    }

    const xhr = new XMLHttpRequest();
    
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const percentComplete = Math.round((event.loaded / event.total) * 100);
        if (onProgress) onProgress(percentComplete);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const response = JSON.parse(xhr.responseText);
          resolve(response);
        } catch (e) {
          resolve(xhr.responseText);
        }
      } else {
        reject(new Error(`Upload failed: ${xhr.statusText}`));
      }
    });

    xhr.addEventListener('error', () => {
      reject(new Error('Network error during upload'));
    });

    xhr.addEventListener('abort', () => {
      reject(new Error('Upload aborted'));
    });

    xhr.open('POST', `${API_BASE_URL}/vehicles/${vehicleId}/video`);
    xhr.send(formData);
  });
};
