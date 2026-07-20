const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

class UploadQueue {
  constructor(onProgress) {
    this.queue = [];
    this.isUploading = false;
    this.onProgress = onProgress;
  }

  add(vehicleId, photoIndex, blob) {
    return new Promise((resolve, reject) => {
      this.queue.push({
        vehicleId,
        photoIndex,
        blob,
        resolve,
        reject,
        attempts: 0,
        maxAttempts: 3
      });

      this.processQueue();
    });
  }

  async processQueue() {
    if (this.isUploading || this.queue.length === 0) {
      return;
    }

    this.isUploading = true;

    while (this.queue.length > 0) {
      const job = this.queue[0];

      try {
        await this.uploadWithRetry(job);
        this.queue.shift();
        this.onProgress(job.photoIndex);
      } catch (error) {
        if (job.attempts >= job.maxAttempts) {
          this.queue.shift();
          job.reject(error);
        }
      }
    }

    this.isUploading = false;
  }

  async uploadWithRetry(job) {
    const formData = new FormData();
    formData.append('photo', job.blob);
    formData.append('photoIndex', job.photoIndex);

    job.attempts++;

    const response = await fetch(
      `${API_BASE_URL}/vehicles/${job.vehicleId}/photos`,
      {
        method: 'POST',
        body: formData
      }
    );

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.statusText}`);
    }

    const data = await response.json();
    return data;
  }
}

export default UploadQueue;
