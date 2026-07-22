const express = require('express');
const Minio = require('minio');
const { minioClient, PROCESSED_BUCKET } = require('../lib/minioClient');
const config = require('../config');

const router = express.Router();


const publicMinioClient = new Minio.Client({
  endPoint: config.minioPublic.endPoint,
  port: config.minioPublic.port,
  useSSL: config.minioPublic.useSSL,
  accessKey: config.minio.accessKey,
  secretKey: config.minio.secretKey,
  region: 'us-east-1',
});

router.get('/viewer/:vehicleId', async (req, res) => {
  try {
    const vehicleId = req.params.vehicleId.toLowerCase().trim();

    // Get all processed images for this vehicle
    const objects = await minioClient.listObjects(
  PROCESSED_BUCKET,
  `${vehicleId}/processed-`,
  false
);

    const imageUrls = [];
    for await (const obj of objects) {
      // Generate presigned URL valid for 7 days
      // Cseréld erre:
      const url = await publicMinioClient.presignedGetObject(
        PROCESSED_BUCKET,
        obj.name,
        60 * 60 * 24 * 7
      );
      imageUrls.push(url);
    }

    // Sort by photo index
    imageUrls.sort((a, b) => {
      const indexA = parseInt(a.match(/processed-(\d+)/)[1]);
      const indexB = parseInt(b.match(/processed-(\d+)/)[1]);
      return indexA - indexB;
    });

    res.send(`
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>360° Vehicle Viewer - ${vehicleId}</title>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }
    body {
      font-family: Arial, sans-serif;
      background: #f0f0f0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 20px;
    }
    .viewer-container {
      width: 100%;
      max-width: 1200px;
      background: white;
      border-radius: 10px;
      overflow: hidden;
      box-shadow: 0 4px 20px rgba(0,0,0,0.1);
    }
    .image-container {
      position: relative;
      width: 100%;
      padding-top: 56.25%; /* 16:9 aspect ratio */
      background: #000;
      cursor: grab;
      user-select: none;
      -webkit-user-select: none;
      touch-action: none;
    }
    .image-container.grabbing {
      cursor: grabbing;
    }
    .image-container img {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      object-fit: contain;
      opacity: 0;
      transition: opacity 0.15s ease;
    }
    .image-container img.active {
      opacity: 1;
    }
    .drag-hint {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
      pointer-events: none;
      transition: opacity 0.5s ease;
      z-index: 10;
    }
    .drag-hint.hidden {
      opacity: 0;
    }
    .drag-hint-icon {
      font-size: 48px;
      color: rgba(255, 255, 255, 0.8);
      text-shadow: 0 2px 10px rgba(0, 0, 0, 0.5);
    }
    .drag-hint-text {
      color: rgba(255, 255, 255, 0.9);
      font-size: 16px;
      font-weight: 500;
      text-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
      background: rgba(0, 0, 0, 0.3);
      padding: 8px 16px;
      border-radius: 20px;
    }
    .info {
      text-align: center;
      padding: 10px;
      color: #666;
      font-size: 14px;
    }
    .loading {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      color: white;
      font-size: 18px;
      z-index: 5;
    }
  </style>
</head>
<body>
  <div class="viewer-container">
    <div class="image-container" id="imageContainer">
      <div class="loading">Loading images...</div>
      <div class="drag-hint" id="dragHint">
        <div class="drag-hint-icon">↔</div>
        <div class="drag-hint-text">Drag to rotate</div>
      </div>
    </div>
    <div class="info">
      <strong>Vehicle ID:</strong> ${vehicleId} | 
      <strong>Images:</strong> ${imageUrls.length}
    </div>
  </div>

  <script>
    const imageUrls = ${JSON.stringify(imageUrls)};
    let currentIndex = 0;
    let isDragging = false;
    let startX = 0;
    let hasInteracted = false;
    const PIXELS_PER_FRAME = 18; // 15-20 pixels per frame for smooth rotation

    const imageContainer = document.getElementById('imageContainer');
    const dragHint = document.getElementById('dragHint');
    const loading = document.querySelector('.loading');

    // Preload all images before showing
    function preloadImages() {
      let loadedCount = 0;
      const totalImages = imageUrls.length;
      
      imageUrls.forEach((url, index) => {
        const img = document.createElement('img');
        img.src = url;
        img.alt = \`View \${index + 1}\`;
        img.dataset.index = index;
        
        img.onload = () => {
          loadedCount++;
          if (loadedCount === totalImages) {
            // All images loaded, hide loading screen
            loading.style.display = 'none';
            showImage(0);
          }
        };
        
        img.onerror = () => {
          console.error(\`Failed to load image: \${url}\`);
          loadedCount++;
          if (loadedCount === totalImages) {
            loading.style.display = 'none';
            showImage(0);
          }
        };
        
        imageContainer.appendChild(img);
      });
    }

    function showImage(index) {
      // Seamless looping
      if (index < 0) {
        index = imageUrls.length - 1;
      } else if (index >= imageUrls.length) {
        index = 0;
      }
      
      const images = imageContainer.querySelectorAll('img');
      images.forEach(img => img.classList.remove('active'));
      
      if (images[index]) {
        images[index].classList.add('active');
      }
      
      currentIndex = index;
    }

    function hideDragHint() {
      if (!hasInteracted) {
        hasInteracted = true;
        dragHint.classList.add('hidden');
      }
    }

    // Mouse events
    imageContainer.addEventListener('mousedown', (e) => {
      isDragging = true;
      startX = e.clientX;
      imageContainer.classList.add('grabbing');
      hideDragHint();
    });

    imageContainer.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      
      const diff = e.clientX - startX;
      const frameChange = Math.floor(diff / PIXELS_PER_FRAME);
      
      if (frameChange !== 0) {
        showImage(currentIndex - frameChange);
        startX = e.clientX;
      }
    });

    imageContainer.addEventListener('mouseup', () => {
      isDragging = false;
      imageContainer.classList.remove('grabbing');
    });

    imageContainer.addEventListener('mouseleave', () => {
      isDragging = false;
      imageContainer.classList.remove('grabbing');
    });

    // Touch events
    imageContainer.addEventListener('touchstart', (e) => {
      isDragging = true;
      startX = e.touches[0].clientX;
      imageContainer.classList.add('grabbing');
      hideDragHint();
    });

    imageContainer.addEventListener('touchmove', (e) => {
      if (!isDragging) return;
      
      const diff = e.touches[0].clientX - startX;
      const frameChange = Math.floor(diff / PIXELS_PER_FRAME);
      
      if (frameChange !== 0) {
        showImage(currentIndex - frameChange);
        startX = e.touches[0].clientX;
      }
    });

    imageContainer.addEventListener('touchend', () => {
      isDragging = false;
      imageContainer.classList.remove('grabbing');
    });

    // Keyboard navigation (optional, for accessibility)
    document.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft') {
        showImage(currentIndex - 1);
        hideDragHint();
      } else if (e.key === 'ArrowRight') {
        showImage(currentIndex + 1);
        hideDragHint();
      }
    });

    // Initialize
    preloadImages();
  </script>
</body>
</html>
    `);
  } catch (error) {
    console.error('Error serving viewer:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
