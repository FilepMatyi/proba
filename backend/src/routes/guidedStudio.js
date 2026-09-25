const express = require('express');
const multer = require('multer');
const { randomUUID } = require('crypto');
const prisma = require('../lib/prisma');
const redis = require('../lib/redisConnection');
const photoQueue = require('../queues/photoQueue');
const { minioClient, RAW_BUCKET, PROCESSED_BUCKET } = require('../lib/minioClient');
const { normalizeVehicleId } = require('../lib/vehicleId');
const { imageDimensions, safeCaptureMetadata } = require('../lib/guidedImages');

const router = express.Router();
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 30 * 1024 * 1024, files: 1, fields: 2 } });
const sessionKey = (vehicleId) => `${vehicleId}/guided-studio/session.json`;
const photoKey = (vehicleId, index, extension) =>
  `${vehicleId}/guided-studio/originals/${String(index).padStart(2, '0')}.${extension}`;

async function readSession(vehicleId) {
  try {
    const stream = await minioClient.getObject(RAW_BUCKET, sessionKey(vehicleId));
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch (error) {
    if (['NoSuchKey', 'NotFound'].includes(error.code)) return null;
    throw error;
  }
}

async function writeSession(vehicleId, session) {
  const data = Buffer.from(JSON.stringify(session));
  await minioClient.putObject(RAW_BUCKET, sessionKey(vehicleId), data, data.length,
    { 'Content-Type': 'application/json' });
}

router.post('/vehicles/:vehicleId/guided-studio', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    if (!vehicleId) return res.status(400).json({ error: 'Invalid vehicle ID' });
    const existing = await readSession(vehicleId);
    if (existing) return res.json(existing);
    if (await prisma.vehicleSession.findUnique({ where: { vehicleId } })) {
      return res.status(409).json({ error: 'Ez az azonosító már videós projekthez tartozik. Válassz új azonosítót.' });
    }
    try {
      await minioClient.statObject(PROCESSED_BUCKET, `${vehicleId}/studio-photos/manifest.json`);
      return res.status(409).json({ error: 'Ehhez az azonosítóhoz már létezik export.' });
    } catch (error) {
      if (!['NoSuchKey', 'NotFound'].includes(error.code)) throw error;
    }
    const session = { vehicleId, captureId: randomUUID(), sourceMode: 'guided_stills',
      status: 'capturing', createdAt: new Date().toISOString(), photos: Array(10).fill(null) };
    await writeSession(vehicleId, session);
    return res.status(201).json(session);
  } catch (error) {
    console.error('Guided studio start failed:', error);
    return res.status(500).json({ error: 'A vezetett fotózás nem indítható.' });
  }
});

router.get('/vehicles/:vehicleId/guided-studio', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    if (!vehicleId) return res.status(400).json({ error: 'Invalid vehicle ID' });
    const session = await readSession(vehicleId);
    return session ? res.json(session) : res.status(404).json({ error: 'Guided session not found' });
  } catch (error) {
    console.error('Guided studio status failed:', error);
    return res.status(500).json({ error: 'A fotózás állapota nem érhető el.' });
  }
});

router.put('/vehicles/:vehicleId/guided-studio/photos/:index', (req, res) => {
  upload.single('photo')(req, res, async (uploadError) => {
    if (uploadError) return res.status(400).json({ error: uploadError.message });
    try {
      const vehicleId = normalizeVehicleId(req.params.vehicleId);
      const index = Number(req.params.index);
      if (!vehicleId || !Number.isInteger(index) || index < 1 || index > 10) {
        return res.status(400).json({ error: 'Invalid photo index' });
      }
      const session = await readSession(vehicleId);
      if (!session) return res.status(404).json({ error: 'Guided session not found' });
      if (session.status !== 'capturing') return res.status(409).json({ error: 'A feldolgozás már elindult.' });
      if (req.body.captureId !== session.captureId) return res.status(403).json({ error: 'Invalid capture session' });
      const file = req.file;
      const dimensions = file && imageDimensions(file.buffer);
      if (!dimensions || dimensions.width < 640 || dimensions.height < 480
          || dimensions.width / dimensions.height < 1.2 || dimensions.width > 12000 || dimensions.height > 12000) {
        return res.status(400).json({ error: 'A fotónak megfelelő felbontású fekvő képnek kell lennie.' });
      }
      const metadata = safeCaptureMetadata(req.body.metadata, index);
      const extension = dimensions.type === 'image/png' ? 'png' : 'jpg';
      const key = photoKey(vehicleId, index, extension);
      await minioClient.putObject(RAW_BUCKET, key, file.buffer, file.buffer.length,
        { 'Content-Type': dimensions.type });
      session.photos[index - 1] = { ...metadata, sourceKey: key,
        sourceWidth: dimensions.width, sourceHeight: dimensions.height,
        bytes: file.buffer.length, uploadedAt: new Date().toISOString() };
      await writeSession(vehicleId, session);
      return res.json({ status: 'uploaded', index, photo: session.photos[index - 1] });
    } catch (error) {
      console.error('Guided studio photo upload failed:', error);
      return res.status(400).json({ error: 'A fotó nem tölthető fel.' });
    }
  });
});

router.post('/vehicles/:vehicleId/guided-studio/process', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    if (!vehicleId) return res.status(400).json({ error: 'Invalid vehicle ID' });
    const session = await readSession(vehicleId);
    if (!session) return res.status(404).json({ error: 'Guided session not found' });
    if (req.body.captureId !== session.captureId) return res.status(403).json({ error: 'Invalid capture session' });
    const stateKey = `vehicle:${vehicleId}:studio_photos`;
    const workerStatus = await redis.hget(stateKey, 'status');
    if (session.status === 'ready' || (session.status === 'processing' && workerStatus !== 'failed')) {
      return res.status(202).json({ status: session.status });
    }
    if (!session.photos.every((photo) => photo?.sourceKey)) {
      return res.status(409).json({ error: 'Mind a tíz eredeti fotó feltöltése szükséges.' });
    }
    const lockKey = `vehicle:${vehicleId}:studio_photos_lock`;
    if (session.status === 'failed' || workerStatus === 'failed') await redis.del(lockKey);
    const acquired = await redis.set(lockKey, '1', 'EX', 7 * 24 * 3600, 'NX');
    if (!acquired) return res.status(202).json({ status: 'processing' });
    session.status = 'processing';
    await writeSession(vehicleId, session);
    await redis.hset(stateKey, 'status', 'processing', 'completed', '0', 'error', '');
    await redis.expire(stateKey, 7 * 24 * 3600);
    try {
      await photoQueue.add('export-guided-studio-photos', { vehicleId, captureId: session.captureId });
    } catch (error) {
      session.status = 'failed';
      await writeSession(vehicleId, session);
      await redis.del(lockKey);
      throw error;
    }
    return res.status(202).json({ status: 'processing', total: 10 });
  } catch (error) {
    console.error('Guided studio processing failed:', error);
    return res.status(500).json({ error: 'A stúdiófeldolgozás nem indítható.' });
  }
});

module.exports = router;
