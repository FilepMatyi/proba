const express = require('express');
const { minioClient, PROCESSED_BUCKET } = require('../lib/minioClient');

const router = express.Router();

router.get('/viewer3d/:vehicleId/status', async (req, res) => {
  try {
    const vehicleId = req.params.vehicleId.toLowerCase().trim();
    const objectKey = `${vehicleId}/model.splat`;

    try {
      const stat = await minioClient.statObject(PROCESSED_BUCKET, objectKey);
      res.json({ has3d: true, fileSize: stat.size });
    } catch (err) {
      if (err.code === 'NotFound' || err.message.includes('not found') || err.code === 'NoSuchKey') {
        res.json({ has3d: false });
      } else {
        throw err;
      }
    }
  } catch (error) {
    console.error('Error checking splat status:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

router.get('/viewer3d/:vehicleId/model.splat', async (req, res) => {
  try {
    const vehicleId = req.params.vehicleId.toLowerCase().trim();
    const objectKey = `${vehicleId}/model.splat`;

    const stream = await minioClient.getObject(PROCESSED_BUCKET, objectKey);
    res.setHeader('Content-Type', 'application/octet-stream');
    res.setHeader('Cache-Control', 'public, max-age=604800');
    res.setHeader('Access-Control-Allow-Origin', '*');
    
    stream.on('error', (err) => {
      console.error('Stream error:', err.message);
      if (!res.headersSent) {
        res.status(500).json({ error: 'Failed to stream model' });
      }
    });
    stream.pipe(res);
  } catch (error) {
    console.error('Error proxying model:', error.message);
    res.status(404).json({ error: 'Model not found' });
  }
});

router.get('/viewer3d/:vehicleId', (req, res) => {
  const vehicleId = req.params.vehicleId.toLowerCase().trim();
  
  res.send(`
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>3D Vehicle Viewer - ${vehicleId}</title>
  
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #111114;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 16px;
      color: #ddd;
    }

    .viewer-wrapper {
      width: 100%;
      max-width: 1200px;
    }

    .viewer-container {
      position: relative;
      width: 100%;
      aspect-ratio: 16/9;
      background: #000;
      border-radius: 14px;
      overflow: hidden;
      box-shadow:
        0 12px 48px rgba(0,0,0,0.5),
        0 0 0 1px rgba(255,255,255,0.06);
    }
    
    @media (max-width: 768px) {
      .viewer-container {
        aspect-ratio: auto;
        height: 70vh;
      }
    }

    /* ── Controls ── */
    .controls {
      position: absolute;
      bottom: 14px;
      right: 14px;
      display: flex;
      flex-direction: column;
      gap: 5px;
      z-index: 20;
    }
    .controls button {
      width: 34px; height: 34px;
      border: none;
      border-radius: 8px;
      background: rgba(0,0,0,0.50);
      color: #fff;
      font-size: 17px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      transition: background 0.15s;
      line-height: 1;
    }
    .controls button:hover  { background: rgba(0,0,0,0.70); }
    .controls button:active { background: rgba(0,0,0,0.85); }

    /* ── Info Bar ── */
    .info-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 20px;
      background: #1a1a1e;
      color: #777;
      font-size: 12px;
      border-radius: 0 0 14px 14px;
      border-top: 1px solid rgba(255,255,255,0.04);
    }
    .info-bar strong { color: #bbb; font-weight: 500; }
  </style>
  
  <script type="importmap">
  {
    "imports": {
      "@mkkellogg/gaussian-splats-3d": "https://cdn.jsdelivr.net/npm/@mkkellogg/gaussian-splats-3d@0.4.8/build/gaussian-splats-3d.module.min.js",
      "three": "https://cdn.jsdelivr.net/npm/three@0.162.0/build/three.module.min.js"
    }
  }
  </script>
</head>
<body>

<div class="viewer-wrapper">
  <div class="viewer-container" id="viewer-container">
    <div class="controls" id="controls">
      <button id="fullscreenBtn" title="Fullscreen" style="font-size:16px">⛶</button>
    </div>
  </div>

  <div class="info-bar">
    <span><strong>Vehicle:</strong> ${vehicleId}</span>
    <span><strong>Format:</strong> 3D Gaussian Splatting</span>
  </div>
</div>

<script type="module">
  import * as GaussianSplats3D from '@mkkellogg/gaussian-splats-3d';
  import * as THREE from 'three';

  const viewer = new GaussianSplats3D.Viewer({
    cameraUp: [0, -1, 0],
    initialCameraPosition: [0, -2, 6],
    initialCameraLookAt: [0, 0, 0],
    rootElement: document.getElementById('viewer-container'),
    selfDrivenMode: true,
    useBuiltInControls: true,
    dynamicScene: false,
    sharedMemoryForWorkers: false // Required for cross-origin
  });

  viewer.addSplatScene('/viewer3d/${vehicleId}/model.splat', {
    splatAlphaRemovalThreshold: 5,
    showLoadingUI: true,
    progressiveLoad: true
  }).then(() => {
    console.log('Splat scene loaded');
  }).catch(err => {
    console.error('Error loading splat scene:', err);
  });

  // Fullscreen toggle
  const $fullscreen = document.getElementById('fullscreenBtn');
  $fullscreen.onclick = e => {
    e.stopPropagation();
    const container = document.getElementById('viewer-container');
    if (!document.fullscreenElement) {
      container.requestFullscreen().catch(err => {
        console.error("Error attempting to enable fullscreen:", err);
      });
    } else {
      document.exitFullscreen();
    }
  };
</script>
</body>
</html>
  `);
});

module.exports = router;
