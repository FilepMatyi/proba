const express = require('express');
const { minioClient, PROCESSED_BUCKET } = require('../lib/minioClient');

const router = express.Router();

router.get('/viewer/:vehicleId', async (req, res) => {
  try {
    const vehicleId = req.params.vehicleId.toLowerCase().trim();

    const objects = minioClient.listObjects(
      PROCESSED_BUCKET,
      `${vehicleId}/processed-`,
      false
    );

    const imageData = [];
    for await (const obj of objects) {
      const filename = obj.name.split('/').pop();
      imageData.push({
        filename,
        url: `/viewer/${vehicleId}/image/${encodeURIComponent(filename)}`
      });
    }

    imageData.sort((a, b) => {
      const indexA = parseInt(a.filename.match(/processed-(\d+)/)[1]);
      const indexB = parseInt(b.filename.match(/processed-(\d+)/)[1]);
      return indexA - indexB;
    });

    const imageUrls = imageData.map(d => d.url);

    res.send(`
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>360° Vehicle Viewer - ${vehicleId}</title>
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
      width: 100%;
      background: #f4f4f6;
      border-radius: 14px;
      overflow: hidden;
      box-shadow:
        0 12px 48px rgba(0,0,0,0.5),
        0 0 0 1px rgba(255,255,255,0.06);
    }

    /* ── Image Container ── */
    .image-container {
      position: relative;
      width: 100%;
      padding-top: 66%;
      background: linear-gradient(180deg, #ececee 0%, #dcdce0 100%);
      cursor: grab;
      user-select: none;
      -webkit-user-select: none;
      touch-action: none;
      overflow: hidden;
    }
    .image-container.grabbing { cursor: grabbing; }
    .image-container.zoomed  { cursor: move; }

    .image-container img {
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      object-fit: contain;
      opacity: 0;
      transform-origin: center center;
      will-change: transform, opacity;
      pointer-events: none;
    }
    .image-container img.active { opacity: 1; }

    /* ── Zoom Controls ── */
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
    .controls button:disabled { opacity: 0.25; cursor: default; }

    /* ── Zoom Badge ── */
    .zoom-badge {
      position: absolute;
      top: 14px; right: 14px;
      background: rgba(0,0,0,0.50);
      color: #fff;
      font-size: 11px; font-weight: 500;
      padding: 3px 9px;
      border-radius: 10px;
      z-index: 20;
      opacity: 0;
      transition: opacity 0.3s;
      backdrop-filter: blur(8px);
      pointer-events: none;
    }
    .zoom-badge.visible { opacity: 1; }

    /* ── Drag Hint ── */
    .drag-hint {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      pointer-events: none;
      transition: opacity 0.6s;
      z-index: 10;
    }
    .drag-hint.hidden { opacity: 0; }
    .drag-hint-icon  { font-size: 36px; color: rgba(0,0,0,0.18); }
    .drag-hint-text  {
      color: rgba(0,0,0,0.35);
      font-size: 13px; font-weight: 500;
      background: rgba(255,255,255,0.6);
      padding: 5px 14px;
      border-radius: 14px;
      backdrop-filter: blur(4px);
    }

    /* ── Loading ── */
    .loading-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: linear-gradient(180deg, #ececee 0%, #dcdce0 100%);
      z-index: 30;
      gap: 14px;
    }
    .loading-spinner {
      width: 36px; height: 36px;
      border: 3px solid #d0d0d0;
      border-top-color: #666;
      border-radius: 50%;
      animation: spin 0.75s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .loading-text { color: #888; font-size: 13px; }
    .loading-bar {
      width: 180px; height: 3px;
      background: #d4d4d4;
      border-radius: 2px;
      overflow: hidden;
    }
    .loading-bar-fill {
      height: 100%;
      background: linear-gradient(90deg, #888, #555);
      border-radius: 2px;
      transition: width 0.3s;
      width: 0%;
    }

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
</head>
<body>

<div class="viewer-wrapper">
  <div class="viewer-container">
    <div class="image-container" id="imageContainer">

      <div class="loading-overlay" id="loadingOverlay">
        <div class="loading-spinner"></div>
        <div class="loading-text" id="loadingText">Loading images…</div>
        <div class="loading-bar"><div class="loading-bar-fill" id="loadingBarFill"></div></div>
      </div>

      <div class="drag-hint" id="dragHint">
        <div class="drag-hint-icon">↔</div>
        <div class="drag-hint-text">Drag to rotate · Scroll to zoom</div>
      </div>

      <div class="zoom-badge" id="zoomBadge">1.0×</div>

      <div class="controls" id="controls">
        <button id="zoomInBtn"    title="Zoom in">+</button>
        <button id="zoomOutBtn"   title="Zoom out" disabled>−</button>
        <button id="zoomResetBtn" title="Reset" disabled style="font-size:12px">⟲</button>
      </div>
    </div>
  </div>

  <div class="info-bar">
    <span><strong>Vehicle:</strong> ${vehicleId}</span>
    <span><strong>Frames:</strong> ${imageUrls.length}</span>
  </div>
</div>

<script>
  const imageUrls = ${JSON.stringify(imageUrls)};
  let currentIndex  = 0;
  let isDragging     = false;
  let startX = 0, startY = 0;
  let hasInteracted  = false;
  const PX_PER_FRAME = 18;

  /* ── Zoom state ── */
  let zoomLevel = 1;
  let panX = 0, panY = 0;
  const MIN_ZOOM  = 1;
  const MAX_ZOOM  = 4;
  const ZOOM_STEP = 0.35;
  let badgeTimer  = null;

  const $container  = document.getElementById('imageContainer');
  const $hint       = document.getElementById('dragHint');
  const $overlay    = document.getElementById('loadingOverlay');
  const $loadTxt    = document.getElementById('loadingText');
  const $loadBar    = document.getElementById('loadingBarFill');
  const $badge      = document.getElementById('zoomBadge');
  const $zoomIn     = document.getElementById('zoomInBtn');
  const $zoomOut    = document.getElementById('zoomOutBtn');
  const $zoomReset  = document.getElementById('zoomResetBtn');

  /* ═══════════════ Preloader ═══════════════ */
  function preloadImages() {
    let loaded = 0;
    const total = imageUrls.length;
    let ratioSet = false;

    if (total === 0) {
      $loadTxt.textContent = 'No processed images yet — check back shortly';
      return;
    }

    imageUrls.forEach((url, i) => {
      const img = document.createElement('img');
      img.src = url;
      img.alt = 'View ' + (i + 1);
      img.dataset.index = i;
      img.draggable = false;

      img.onload = () => {
        loaded++;
        if (!ratioSet) {
          ratioSet = true;
          $container.style.paddingTop =
            ((img.naturalHeight / img.naturalWidth) * 100) + '%';
        }
        $loadTxt.textContent = 'Loading ' + loaded + ' of ' + total;
        $loadBar.style.width = Math.round(loaded / total * 100) + '%';
        if (loaded === total) { $overlay.style.display = 'none'; showImage(0); }
      };
      img.onerror = () => {
        loaded++;
        if (loaded === total) { $overlay.style.display = 'none'; showImage(0); }
      };
      $container.appendChild(img);
    });
  }

  /* ═══════════════ Show / Rotate ═══════════════ */
  function showImage(idx) {
    if (idx < 0) idx = imageUrls.length - 1;
    else if (idx >= imageUrls.length) idx = 0;
    const imgs = $container.querySelectorAll('img');
    imgs.forEach(im => im.classList.remove('active'));
    if (imgs[idx]) imgs[idx].classList.add('active');
    currentIndex = idx;
  }

  /* ═══════════════ Zoom helpers ═══════════════ */
  function updateTransform() {
    const t = 'scale(' + zoomLevel + ') translate(' + panX + 'px,' + panY + 'px)';
    $container.querySelectorAll('img').forEach(im => { im.style.transform = t; });

    const isZ = zoomLevel > 1.01;
    $container.classList.toggle('zoomed', isZ);
    $zoomIn.disabled    = zoomLevel >= MAX_ZOOM;
    $zoomOut.disabled   = zoomLevel <= MIN_ZOOM;
    $zoomReset.disabled = !isZ;

    $badge.textContent = zoomLevel.toFixed(1) + '×';
    $badge.classList.add('visible');
    clearTimeout(badgeTimer);
    badgeTimer = setTimeout(() => $badge.classList.remove('visible'), 1200);
  }

  function clampPan() {
    const r = $container.getBoundingClientRect();
    const mx = (zoomLevel - 1) * r.width  / (2 * zoomLevel);
    const my = (zoomLevel - 1) * r.height / (2 * zoomLevel);
    panX = Math.max(-mx, Math.min(mx, panX));
    panY = Math.max(-my, Math.min(my, panY));
  }

  function setZoom(z) {
    zoomLevel = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z));
    if (zoomLevel <= 1.01) { zoomLevel = 1; panX = 0; panY = 0; }
    clampPan();
    updateTransform();
  }

  function hideHint() {
    if (!hasInteracted) { hasInteracted = true; $hint.classList.add('hidden'); }
  }

  /* ═══════════════ Zoom controls ═══════════════ */
  $zoomIn.onclick    = e => { e.stopPropagation(); setZoom(zoomLevel + ZOOM_STEP); };
  $zoomOut.onclick   = e => { e.stopPropagation(); setZoom(zoomLevel - ZOOM_STEP); };
  $zoomReset.onclick = e => { e.stopPropagation(); setZoom(1); };

  /* Scroll wheel */
  $container.addEventListener('wheel', e => {
    e.preventDefault(); hideHint();
    setZoom(zoomLevel + (e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP));
  }, { passive: false });

  /* ═══════════════ Mouse events ═══════════════ */
  $container.addEventListener('mousedown', e => {
    if (e.target.closest('.controls')) return;
    isDragging = true; startX = e.clientX; startY = e.clientY;
    $container.classList.add('grabbing'); hideHint();
  });

  $container.addEventListener('mousemove', e => {
    if (!isDragging) return;
    if (zoomLevel > 1.01) {
      panX += (e.clientX - startX) / zoomLevel;
      panY += (e.clientY - startY) / zoomLevel;
      clampPan(); updateTransform();
      startX = e.clientX; startY = e.clientY;
    } else {
      const fc = Math.floor((e.clientX - startX) / PX_PER_FRAME);
      if (fc !== 0) { showImage(currentIndex - fc); startX = e.clientX; }
    }
  });

  $container.addEventListener('mouseup',    () => { isDragging = false; $container.classList.remove('grabbing'); });
  $container.addEventListener('mouseleave', () => { isDragging = false; $container.classList.remove('grabbing'); });

  /* ═══════════════ Touch events ═══════════════ */
  let pinchDist = 0, pinchZoom = 1;

  $container.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      pinchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY);
      pinchZoom = zoomLevel;
    } else if (e.touches.length === 1) {
      isDragging = true;
      startX = e.touches[0].clientX; startY = e.touches[0].clientY;
      $container.classList.add('grabbing'); hideHint();
    }
  });

  $container.addEventListener('touchmove', e => {
    e.preventDefault();
    if (e.touches.length === 2) {
      const d = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY);
      setZoom(pinchZoom * (d / pinchDist));
    } else if (e.touches.length === 1 && isDragging) {
      const tx = e.touches[0].clientX, ty = e.touches[0].clientY;
      if (zoomLevel > 1.01) {
        panX += (tx - startX) / zoomLevel;
        panY += (ty - startY) / zoomLevel;
        clampPan(); updateTransform();
      } else {
        const fc = Math.floor((tx - startX) / PX_PER_FRAME);
        if (fc !== 0) { showImage(currentIndex - fc); startX = tx; }
      }
      startX = tx; startY = ty;
    }
  }, { passive: false });

  $container.addEventListener('touchend', () => {
    isDragging = false; $container.classList.remove('grabbing');
  });

  /* ═══════════════ Double-click / tap to toggle zoom ═══════════════ */
  let lastTap = 0;
  $container.addEventListener('click', e => {
    if (e.target.closest('.controls')) return;
    const now = Date.now();
    if (now - lastTap < 300) { setZoom(zoomLevel > 1.01 ? 1 : 2.5); }
    lastTap = now;
  });

  /* ═══════════════ Keyboard ═══════════════ */
  document.addEventListener('keydown', e => {
    switch (e.key) {
      case 'ArrowLeft':  showImage(currentIndex - 1); hideHint(); break;
      case 'ArrowRight': showImage(currentIndex + 1); hideHint(); break;
      case '+': case '=': setZoom(zoomLevel + ZOOM_STEP); break;
      case '-':            setZoom(zoomLevel - ZOOM_STEP); break;
      case '0':            setZoom(1); break;
    }
  });

  /* ═══════════════ Init ═══════════════ */
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

// ─────────────────────────────────────────────────────────────────────
// Image proxy — streams processed images from MinIO through the backend.
// Eliminates the need to expose MinIO directly and fixes the localhost
// presigned URL issue when viewing from external devices.
// ─────────────────────────────────────────────────────────────────────
router.get('/viewer/:vehicleId/image/:filename', async (req, res) => {
  try {
    const vehicleId = req.params.vehicleId.toLowerCase().trim();
    const filename = decodeURIComponent(req.params.filename);
    const objectKey = `${vehicleId}/${filename}`;

    const stream = await minioClient.getObject(PROCESSED_BUCKET, objectKey);
    res.setHeader('Content-Type', 'image/jpeg');
    res.setHeader('Cache-Control', 'public, max-age=604800');
    stream.on('error', (err) => {
      console.error('Stream error:', err.message);
      if (!res.headersSent) {
        res.status(500).json({ error: 'Failed to stream image' });
      }
    });
    stream.pipe(res);
  } catch (error) {
    console.error('Error proxying image:', error.message);
    res.status(404).json({ error: 'Image not found' });
  }
});

module.exports = router;
