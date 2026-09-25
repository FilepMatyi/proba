const express = require('express');
const redis = require('../lib/redisConnection');
const prisma = require('../lib/prisma');
const photoQueue = require('../queues/photoQueue');
const { minioClient, RAW_BUCKET, PROCESSED_BUCKET } = require('../lib/minioClient');
const { normalizeVehicleId } = require('../lib/vehicleId');

const router = express.Router();
const suffix = '/studio-photos/';

async function manifestFor(vehicleId) {
  try {
    const stream = await minioClient.getObject(PROCESSED_BUCKET, vehicleId + suffix + 'manifest.json');
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch (error) {
    if (['NoSuchKey', 'NotFound'].includes(error.code)) return null;
    throw error;
  }
}

router.get('/vehicles/:vehicleId/studio-photos', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    if (!vehicleId) return res.status(400).json({ error: 'Invalid vehicle ID' });
    const session = await prisma.vehicleSession.findUnique({ where: { vehicleId } });
    let guided = false;
    if (!session) {
      try { await minioClient.statObject(RAW_BUCKET, `${vehicleId}/guided-studio/session.json`); guided = true; }
      catch (error) {
        if (['NoSuchKey', 'NotFound'].includes(error.code)) return res.status(404).json({ error: 'Session not found' });
        throw error;
      }
    }
    const state = await redis.hgetall(`vehicle:${vehicleId}:studio_photos`);
    if (state.status === 'processing' || state.status === 'failed') {
      return res.json({ status: state.status, completed: Number(state.completed || 0),
        total: 10, sourceMode: guided ? 'guided_stills' : 'video_frame_selection',
        error: state.error || null });
    }
    const manifest = await manifestFor(vehicleId);
    if (manifest) return res.json({ status: 'ready', completed: 10, total: 10, ...manifest });
    return res.json({ status: 'not_started', completed: 0, total: 10,
      sourceMode: guided ? 'guided_stills' : 'video_frame_selection' });
  } catch (error) {
    console.error('Studio photo status failed:', error);
    return res.status(500).json({ error: 'Az export állapota nem érhető el.' });
  }
});

router.post('/vehicles/:vehicleId/studio-photos', async (req, res) => {
  const vehicleId = normalizeVehicleId(req.params.vehicleId);
  if (!vehicleId) return res.status(400).json({ error: 'Invalid vehicle ID' });
  const stateKey = `vehicle:${vehicleId}:studio_photos`;
  const lockKey = `vehicle:${vehicleId}:studio_photos_lock`;
  try {
    const session = await prisma.vehicleSession.findUnique({ where: { vehicleId } });
    if (!session) return res.status(404).json({ error: 'Session not found' });
    if (session.status !== 'completed' || session.processedFrames < 36) {
      return res.status(409).json({ error: 'Előbb a 36 nézet feldolgozásának kell elkészülnie.' });
    }
    // The persisted manifest is authoritative even after Redis state expires.
    if (await manifestFor(vehicleId)) {
      return res.json({ status: 'ready', completed: 10, total: 10 });
    }
    const current = await redis.hget(stateKey, 'status');
    if (current === 'processing') return res.status(202).json({ status: 'processing', total: 10 });
    if (current === 'failed') await redis.del(lockKey);
    const acquired = await redis.set(lockKey, '1', 'EX', 7*24*3600, 'NX');
    if (!acquired) return res.status(202).json({ status: 'processing', total: 10 });
    await redis.hset(stateKey, 'status', 'processing', 'completed', '0', 'error', '');
    await redis.expire(stateKey, 7*24*3600);
    try {
      await photoQueue.add('export-studio-photos', { vehicleId });
    } catch (error) {
      await redis.del(lockKey, stateKey);
      throw error;
    }
    return res.status(202).json({ status: 'processing', completed: 0, total: 10 });
  } catch (error) {
    console.error('Studio photo export failed to start:', error);
    return res.status(500).json({ error: 'Az export nem indítható el.' });
  }
});

router.get('/vehicles/:vehicleId/studio-photos/files/:filename', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    const filename = req.params.filename;
    if (!vehicleId || !/^(?:0[1-9]|10)\.jpg$|^album\.zip$/.test(filename)) {
      return res.status(400).end();
    }
    const key = vehicleId + suffix + filename;
    const stats = await minioClient.statObject(PROCESSED_BUCKET, key);
    res.set({ 'Content-Type': filename.endsWith('.zip') ? 'application/zip' : 'image/jpeg',
      'Content-Length': stats.size, 'Cache-Control': 'private, max-age=300',
      'Content-Disposition': filename.endsWith('.zip')
        ? `attachment; filename="${vehicleId}-studio-photos.zip"` : 'inline' });
    const stream = await minioClient.getObject(PROCESSED_BUCKET, key);
    stream.on('error', (streamError) => {
      console.error('Studio photo stream failed:', streamError);
      if (res.headersSent) res.destroy(streamError);
      else res.status(500).end();
    });
    stream.pipe(res);
  } catch (error) {
    if (['NoSuchKey', 'NotFound'].includes(error.code)) return res.status(404).end();
    console.error('Studio photo download failed:', error);
    return res.status(500).end();
  }
});

module.exports = router;
