const express = require('express');
const multer = require('multer');
const { v4: uuidv4 } = require('uuid');
const { minioClient, RAW_BUCKET } = require('../lib/minioClient');
const photoQueue = require('../queues/photoQueue');
const redis = require('../lib/redisConnection');
const sessionService = require('../services/sessionService');
const ffmpeg = require('fluent-ffmpeg');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { exec } = require('child_process');

const router = express.Router();

const uploadPhoto = multer({ storage: multer.memoryStorage(), limits: { fileSize: 15 * 1024 * 1024 } });

const uploadVideo = multer({
  storage: multer.diskStorage({
    destination: (req, file, cb) => cb(null, os.tmpdir()),
    filename: (req, file, cb) => cb(null, `${uuidv4()}-${file.originalname}`)
  }),
  limits: { fileSize: 250 * 1024 * 1024 },
});

router.post('/vehicles/:vehicleId/video', uploadVideo.single('video'), async (req, res) => {
  const vehicleId = req.params.vehicleId.toLowerCase().trim();
  const videoFile = req.file;

  if (!videoFile) return res.status(400).json({ error: 'Video is required' });

  try {
    console.log(`Processing video for vehicle ${vehicleId}: ${videoFile.path}`);
    await sessionService.getOrCreateSession(vehicleId);
    
    res.status(202).json({ status: 'processing_video', message: 'Video upload successful. Extracting frames.' });

    const numFrames = 36;
    const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vs360-'));
    const fixedVideoPath = `${videoFile.path}-fixed.webm`;

    // 1. MediaRecorder produces WebM files without duration metadata.
    // We must re-mux it first so fluent-ffmpeg can read the duration for evenly spaced screenshots.
    exec(`ffmpeg -i "${videoFile.path}" -c copy "${fixedVideoPath}"`, (err, stdout, stderr) => {
      if (err) {
        console.error('Error fixing webm duration:', err);
        // Fallback to original file if fix fails (might still fail in screenshots)
        extractFrames(videoFile.path, outDir, vehicleId, numFrames, [videoFile.path, fixedVideoPath]);
        return;
      }
      
      // 2. Extract frames from the fixed video
      extractFrames(fixedVideoPath, outDir, vehicleId, numFrames, [videoFile.path, fixedVideoPath]);
    });

  } catch (error) {
    console.error('Error handling video upload:', error);
    if (!res.headersSent) res.status(500).json({ error: 'Internal server error' });
  }
});

function extractFrames(inputPath, outDir, vehicleId, numFrames, filesToCleanup) {
  ffmpeg(inputPath)
    .on('end', async () => {
      console.log(`Extracted frames for ${vehicleId}`);
      try {
        const files = fs.readdirSync(outDir).filter(f => f.endsWith('.jpg')).sort();
        for (let i = 0; i < files.length; i++) {
          const photoIndex = i + 1;
          if (photoIndex > numFrames) break;
          
          const filePath = path.join(outDir, files[i]);
          const buffer = fs.readFileSync(filePath);
          const objectKey = `${vehicleId}/${photoIndex}-${uuidv4()}.jpg`;
          
          await minioClient.putObject(RAW_BUCKET, objectKey, buffer, buffer.length, { 'Content-Type': 'image/jpeg' });
          await photoQueue.add('process-photo', { vehicleId, photoIndex, objectKey });
          await redis.incr(`vehicle:${vehicleId}:uploaded`);
        }
        console.log(`Finished queueing ${files.length} frames for ${vehicleId}`);
      } catch (error) {
        console.error('Error processing extracted frames:', error);
      } finally {
        cleanup(filesToCleanup, outDir);
      }
    })
    .on('error', (err) => {
      console.error('Error extracting frames with ffmpeg:', err);
      cleanup(filesToCleanup, outDir);
    })
    .screenshots({
      count: numFrames,
      folder: outDir,
      filename: 'frame-%03i.jpg',
      size: '1920x1080'
    });
}

function cleanup(files, dir) {
  files.forEach(f => { try { fs.unlinkSync(f); } catch (e) {} });
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) {}
}

module.exports = router;
