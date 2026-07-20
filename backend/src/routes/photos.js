const express = require('express');
const multer = require('multer');
const { v4: uuidv4 } = require('uuid');
const { minioClient, RAW_BUCKET } = require('../lib/minioClient');
const photoQueue = require('../queues/photoQueue');
const redis = require('../lib/redisConnection');
const sessionService = require('../services/sessionService');

const router = express.Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: 15 * 1024 * 1024, // 15MB
  },
});

router.post('/vehicles/:vehicleId/photos', upload.single('photo'), async (req, res) => {
  try {
    const { vehicleId } = req.params;
    const { photoIndex } = req.body;
    const photo = req.file;

    if (!photo) {
      return res.status(400).json({ error: 'Photo is required' });
    }

    if (!photoIndex || photoIndex < 1 || photoIndex > 24) {
      return res.status(400).json({ error: 'photoIndex must be between 1 and 24' });
    }

    // Create or get vehicle session
    await sessionService.getOrCreateSession(vehicleId);

    const objectKey = `${vehicleId}/${photoIndex}-${uuidv4()}.jpg`;

    await minioClient.putObject(RAW_BUCKET, objectKey, photo.buffer, photo.buffer.length, {
      'Content-Type': 'image/jpeg',
    });

    await photoQueue.add('process-photo', {
      vehicleId,
      photoIndex: parseInt(photoIndex),
      objectKey,
    });

    const uploadedCount = await redis.incr(`vehicle:${vehicleId}:uploaded`);

    res.status(202).json({
      status: 'accepted',
      objectKey,
      uploadedCount,
    });
  } catch (error) {
    console.error('Error processing photo upload:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
