const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

class UploadQueue {
  constructor(onProgress) {
    this.queue = [];
    this.activeUploads = 0;
    this.maxConcurrent = 2;
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
    if (this.activeUploads >= this.maxConcurrent || this.queue.length === 0) {
      return;
    }

    const job = this.queue.shift();
    this.activeUploads++;

    try {
      await this.uploadWithRetry(job);
      this.onProgress(job.photoIndex);
      job.resolve();
    } catch (error) {
      if (job.attempts >= job.maxAttempts) {
        job.reject(error);
      } else {
        // Re-queue for retry
        this.queue.unshift(job);
      }
    } finally {
      this.activeUploads--;
      this.processQueue();
    }
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
