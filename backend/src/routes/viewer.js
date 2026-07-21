const express = require('express');
const { minioClient, PROCESSED_BUCKET } = require('../lib/minioClient');

const router = express.Router();

router.get('/viewer/:vehicleId', async (req, res) => {
  try {
    const { vehicleId } = req.params.vehicleId.toLowerCase().trim();

    // Get all processed images for this vehicle
    const objects = await minioClient.listObjects(
  PROCESSED_BUCKET,
  `${vehicleId}/processed-`,
  false
);

    const imageUrls = [];
    for await (const obj of objects) {
      // Generate presigned URL valid for 7 days
      const url = await minioClient.presignedGetObject(
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
    }
    .image-container img {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      object-fit: contain;
      opacity: 0;
      transition: opacity 0.3s ease;
    }
    .image-container img.active {
      opacity: 1;
    }
    .controls {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 20px;
      padding: 20px;
      background: white;
    }
    button {
      padding: 12px 24px;
      font-size: 16px;
      background: #000;
      color: white;
      border: none;
      border-radius: 5px;
      cursor: pointer;
      transition: background 0.2s;
    }
    button:hover {
      background: #333;
    }
    button:disabled {
      background: #ccc;
      cursor: not-allowed;
    }
    .progress-indicator {
      display: flex;
      gap: 5px;
    }
    .progress-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #ddd;
      transition: background 0.3s;
    }
    .progress-dot.active {
      background: #000;
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
    }
  </style>
</head>
<body>
  <div class="viewer-container">
    <div class="image-container" id="imageContainer">
      <div class="loading">Loading images...</div>
    </div>
    <div class="controls">
      <button id="prevBtn">← Previous</button>
      <div class="progress-indicator" id="progressIndicator"></div>
      <button id="nextBtn">Next →</button>
    </div>
    <div class="info">
      <strong>Vehicle ID:</strong> ${vehicleId} | 
      <strong>Images:</strong> ${imageUrls.length} | 
      Drag or use buttons to rotate
    </div>
  </div>

  <script>
    const imageUrls = ${JSON.stringify(imageUrls)};
    let currentIndex = 0;
    let isDragging = false;
    let startX = 0;

    const imageContainer = document.getElementById('imageContainer');
    const progressIndicator = document.getElementById('progressIndicator');
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');

    // Load images
    function loadImages() {
      imageUrls.forEach((url, index) => {
        const img = document.createElement('img');
        img.src = url;
        img.alt = \`View \${index + 1}\`;
        img.dataset.index = index;
        
        img.onload = () => {
          if (index === 0) {
            img.classList.add('active');
            document.querySelector('.loading').style.display = 'none';
          }
        };
        
        imageContainer.appendChild(img);
      });

      // Create progress dots
      imageUrls.forEach((_, index) => {
        const dot = document.createElement('div');
        dot.className = 'progress-dot';
        if (index === 0) dot.classList.add('active');
        progressIndicator.appendChild(dot);
      });
    }

    function showImage(index) {
      const images = imageContainer.querySelectorAll('img');
      const dots = progressIndicator.querySelectorAll('.progress-dot');
      
      images.forEach(img => img.classList.remove('active'));
      dots.forEach(dot => dot.classList.remove('active'));
      
      if (images[index]) {
        images[index].classList.add('active');
        dots[index].classList.add('active');
      }
      
      currentIndex = index;
      prevBtn.disabled = currentIndex === 0;
      nextBtn.disabled = currentIndex === imageUrls.length - 1;
    }

    prevBtn.addEventListener('click', () => {
      if (currentIndex > 0) {
        showImage(currentIndex - 1);
      }
    });

    nextBtn.addEventListener('click', () => {
      if (currentIndex < imageUrls.length - 1) {
        showImage(currentIndex + 1);
      }
    });

    // Touch/drag support
    imageContainer.addEventListener('mousedown', (e) => {
      isDragging = true;
      startX = e.clientX;
    });

    imageContainer.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      
      const diff = e.clientX - startX;
      if (Math.abs(diff) > 50) {
        if (diff > 0 && currentIndex > 0) {
          showImage(currentIndex - 1);
        } else if (diff < 0 && currentIndex < imageUrls.length - 1) {
          showImage(currentIndex + 1);
        }
        startX = e.clientX;
      }
    });

    imageContainer.addEventListener('mouseup', () => {
      isDragging = false;
    });

    imageContainer.addEventListener('mouseleave', () => {
      isDragging = false;
    });

    // Touch events
    imageContainer.addEventListener('touchstart', (e) => {
      isDragging = true;
      startX = e.touches[0].clientX;
    });

    imageContainer.addEventListener('touchmove', (e) => {
      if (!isDragging) return;
      
      const diff = e.touches[0].clientX - startX;
      if (Math.abs(diff) > 50) {
        if (diff > 0 && currentIndex > 0) {
          showImage(currentIndex - 1);
        } else if (diff < 0 && currentIndex < imageUrls.length - 1) {
          showImage(currentIndex + 1);
        }
        startX = e.touches[0].clientX;
      }
    });

    imageContainer.addEventListener('touchend', () => {
      isDragging = false;
    });

    // Keyboard navigation
    document.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft' && currentIndex > 0) {
        showImage(currentIndex - 1);
      } else if (e.key === 'ArrowRight' && currentIndex < imageUrls.length - 1) {
        showImage(currentIndex + 1);
      }
    });

    // Initialize
    loadImages();
    showImage(0);
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
